#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlparse


ROOT = Path("/Users/friana/ReelWrangling")
DEFAULT_ENV_PATH = ROOT / ".env"
DEFAULT_OUTPUT_DIR = ROOT / "posters"
DEFAULT_STATUS_TABLE = "poster_download_status"
VALID_TT_ID_RE = re.compile(r"^tt\d{7,}$")
DEFAULT_USER_AGENT = "ReelWranglingPosterPipeline/1.0 (+local)"
DEFAULT_GRAPHQL_QUERY = """
query TitlePrimaryImages($ids: [ID!]!) {
  titles(ids: $ids) {
    id
    titleId
    meta {
      canonicalId
    }
    primaryImage {
      id
      url
      width
      height
    }
  }
}
""".strip()


class PipelineConfigurationError(RuntimeError):
    pass


class RetryableItemError(RuntimeError):
    def __init__(self, code: str, message: str, http_status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.retry_after = retry_after


class PermanentItemError(RuntimeError):
    def __init__(self, code: str, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class Settings:
    database_path: Path
    poster_source_query: str
    output_dir: Path
    status_table: str
    dry_run: bool
    limit: int | None
    resume: bool
    refresh: bool
    force: bool
    tt_id: str | None
    batch_size: int
    max_workers: int
    connect_timeout_seconds: float
    read_timeout_seconds: float
    metadata_max_retries: int
    image_max_retries: int
    backoff_base_seconds: float
    jpeg_quality: int
    max_edge_pixels: int | None
    user_agent: str
    env_path: Path
    imdb_api_endpoint: str
    imdb_api_key: str
    imdb_dataset_id: str
    imdb_revision_id: str
    imdb_asset_id: str
    aws_region: str
    aws_service: str
    graphql_query: str


@dataclass(frozen=True)
class ImageMetadata:
    tt_id: str
    canonical_tt_id: str | None
    image_url: str | None
    image_id: str | None
    width: int | None
    height: int | None


@dataclass(frozen=True)
class WorkItem:
    tt_id: str
    existing_status: dict[str, Any] | None


@dataclass
class DownloadResult:
    tt_id: str
    status: str
    canonical_tt_id: str | None = None
    image_id: str | None = None
    image_url: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    file_path: str | None = None
    file_bytes: int | None = None
    sha256: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def env_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def env_int(name: str, default: int) -> int:
    value = env_str(name)
    if value is None:
        return default
    return int(value)


def env_float(name: str, default: float) -> float:
    value = env_str(name)
    if value is None:
        return default
    return float(value)


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def is_valid_tt_id(tt_id: str) -> bool:
    return bool(VALID_TT_ID_RE.fullmatch(tt_id.strip()))


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def poster_path(output_dir: Path, tt_id: str) -> Path:
    if not is_valid_tt_id(tt_id):
        raise ValueError(f"Refusing to build a poster path for an invalid tt_id: {tt_id!r}")
    resolved_output_dir = output_dir.resolve()
    candidate = (resolved_output_dir / f"{tt_id}.jpg").resolve()
    if candidate.parent != resolved_output_dir:
        raise ValueError(f"Poster path escaped the output directory for tt_id: {tt_id!r}")
    return output_dir / f"{tt_id}.jpg"


TERMINAL_STATUSES = frozenset({"success", "no_image", "invalid_id", "permanent_error"})


def is_allowed_status_transition(current_status: str | None, new_status: str) -> bool:
    if current_status is None:
        return True
    if current_status in TERMINAL_STATUSES and new_status == "pending":
        return False
    return True


def normalize_tt_id(value: Any) -> str | None:
    if value is None:
        return None
    tt_id = str(value).strip()
    return tt_id or None


def coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def truncate_error_message(message: str, limit: int = 500) -> str:
    message = " ".join(str(message).split())
    return message[:limit]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_existing_jpeg(path: Path) -> bool:
    name = path.name.lower()
    if not path.exists() or not (name.endswith(".jpg") or name.endswith(".jpg.part")):
        return False
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.format == "JPEG" and image.width > 0 and image.height > 0
    except Exception:
        return False


def require_module(module_name: str, package_hint: str) -> Any:
    try:
        return __import__(module_name)
    except ImportError as exc:
        raise PipelineConfigurationError(
            f"Missing dependency '{module_name}'. Install {package_hint} before running the poster pipeline."
        ) from exc


def build_settings(args: argparse.Namespace) -> Settings:
    env_path = Path(args.env_file).expanduser().resolve()
    load_env_file(env_path)

    if args.tt_id:
        normalized_tt_id = normalize_tt_id(args.tt_id)
        if not normalized_tt_id:
            raise PipelineConfigurationError("--tt-id requires a non-empty value.")
    else:
        normalized_tt_id = None

    database_path_raw = args.database_path or env_str("DATABASE_PATH", "")
    if not database_path_raw:
        raise PipelineConfigurationError("DATABASE_PATH is required.")
    database_path = Path(database_path_raw).expanduser()

    poster_source_query = args.poster_source_query or env_str("POSTER_SOURCE_QUERY", "")
    if not normalized_tt_id and not poster_source_query:
        raise PipelineConfigurationError("POSTER_SOURCE_QUERY is required unless --tt-id is supplied.")

    output_dir = Path(args.output_dir or env_str("POSTER_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))).expanduser()
    status_table = env_str("POSTER_STATUS_TABLE", DEFAULT_STATUS_TABLE) or DEFAULT_STATUS_TABLE
    graphql_query = env_str("IMDB_GRAPHQL_QUERY", DEFAULT_GRAPHQL_QUERY) or DEFAULT_GRAPHQL_QUERY

    imdb_api_endpoint = env_str("IMDB_API_ENDPOINT", "")
    imdb_api_key = env_str("IMDB_API_KEY", "")
    imdb_dataset_id = env_str("IMDB_DATASET_ID", "")
    imdb_revision_id = env_str("IMDB_REVISION_ID", "")
    imdb_asset_id = env_str("IMDB_ASSET_ID", "")
    aws_region = env_str("AWS_REGION", "")
    aws_service = env_str("IMDB_AWS_SERVICE", "appsync") or "appsync"

    if not args.dry_run:
        required_pairs = {
            "IMDB_API_ENDPOINT": imdb_api_endpoint,
            "IMDB_API_KEY": imdb_api_key,
            "IMDB_DATASET_ID": imdb_dataset_id,
            "IMDB_REVISION_ID": imdb_revision_id,
            "IMDB_ASSET_ID": imdb_asset_id,
            "AWS_REGION": aws_region,
        }
        missing = [name for name, value in required_pairs.items() if not value]
        if missing:
            raise PipelineConfigurationError(f"Missing required configuration: {', '.join(missing)}")

    return Settings(
        database_path=database_path.resolve(),
        poster_source_query=poster_source_query,
        output_dir=output_dir.resolve(),
        status_table=status_table,
        dry_run=args.dry_run,
        limit=args.limit,
        resume=args.resume,
        refresh=args.refresh,
        force=args.force,
        tt_id=normalized_tt_id,
        batch_size=max(1, env_int("POSTER_BATCH_SIZE", 25)),
        max_workers=max(1, env_int("POSTER_MAX_WORKERS", 4)),
        connect_timeout_seconds=max(1.0, env_float("POSTER_CONNECT_TIMEOUT_SECONDS", 10.0)),
        read_timeout_seconds=max(1.0, env_float("POSTER_READ_TIMEOUT_SECONDS", 30.0)),
        metadata_max_retries=max(1, env_int("POSTER_METADATA_MAX_RETRIES", 4)),
        image_max_retries=max(1, env_int("POSTER_IMAGE_MAX_RETRIES", 4)),
        backoff_base_seconds=max(0.1, env_float("POSTER_BACKOFF_BASE_SECONDS", 1.0)),
        jpeg_quality=min(95, max(50, env_int("POSTER_JPEG_QUALITY", 90))),
        max_edge_pixels=max(256, env_int("POSTER_MAX_EDGE_PIXELS", 2500))
        if env_str("POSTER_MAX_EDGE_PIXELS") not in {None, ""}
        else None,
        user_agent=env_str("POSTER_USER_AGENT", DEFAULT_USER_AGENT) or DEFAULT_USER_AGENT,
        env_path=env_path,
        imdb_api_endpoint=imdb_api_endpoint,
        imdb_api_key=imdb_api_key,
        imdb_dataset_id=imdb_dataset_id,
        imdb_revision_id=imdb_revision_id,
        imdb_asset_id=imdb_asset_id,
        aws_region=aws_region,
        aws_service=aws_service,
        graphql_query=graphql_query,
    )


class DuckDBRepository:
    def __init__(self, settings: Settings) -> None:
        duckdb = require_module("duckdb", "the 'duckdb' package")
        self._duckdb = duckdb
        self._settings = settings
        self.conn = duckdb.connect(str(settings.database_path))

    def close(self) -> None:
        self.conn.close()

    def ensure_schema(self) -> None:
        self.conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self._settings.status_table} (
                tt_id VARCHAR PRIMARY KEY,
                canonical_tt_id VARCHAR,
                status VARCHAR NOT NULL,
                image_id VARCHAR,
                image_url VARCHAR,
                source_width INTEGER,
                source_height INTEGER,
                file_path VARCHAR,
                file_bytes BIGINT,
                sha256 VARCHAR,
                http_status INTEGER,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                error_code VARCHAR,
                error_message VARCHAR,
                first_attempted_at TIMESTAMP,
                last_attempted_at TIMESTAMP,
                completed_at TIMESTAMP
            )
            """
        )

    def fetch_input_ids(self) -> list[str]:
        if self._settings.tt_id:
            raw_ids = [self._settings.tt_id]
        else:
            rows = self.conn.execute(self._settings.poster_source_query).fetchall()
            raw_ids = [normalize_tt_id(row[0]) for row in rows]

        deduped: list[str] = []
        seen: set[str] = set()
        for raw_id in raw_ids:
            if not raw_id or raw_id in seen:
                continue
            deduped.append(raw_id)
            seen.add(raw_id)

        deduped.sort()
        if self._settings.limit is not None:
            return deduped[: self._settings.limit]
        return deduped

    def fetch_status_rows(self) -> dict[str, dict[str, Any]]:
        cursor = self.conn.execute(f"SELECT * FROM {self._settings.status_table}")
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        return {
            row_dict["tt_id"]: row_dict
            for row_dict in (dict(zip(columns, row)) for row in rows)
        }

    def upsert_status(self, tt_id: str, result: DownloadResult, previous_attempts: int) -> None:
        attempted_at = now_utc()
        completed_at = attempted_at if result.status in {"success", "no_image", "invalid_id", "permanent_error"} else None

        existing = self.conn.execute(
            f"SELECT first_attempted_at, status FROM {self._settings.status_table} WHERE tt_id = ?",
            [tt_id],
        ).fetchone()
        first_attempted_at = existing[0] if existing and existing[0] is not None else attempted_at
        current_status = existing[1] if existing else None
        if not is_allowed_status_transition(current_status, result.status):
            raise RuntimeError(
                f"Refusing to regress {tt_id} from terminal status '{current_status}' to '{result.status}'."
            )

        self.conn.execute(
            f"""
            INSERT INTO {self._settings.status_table} (
                tt_id,
                canonical_tt_id,
                status,
                image_id,
                image_url,
                source_width,
                source_height,
                file_path,
                file_bytes,
                sha256,
                http_status,
                attempt_count,
                error_code,
                error_message,
                first_attempted_at,
                last_attempted_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tt_id) DO UPDATE SET
                canonical_tt_id = EXCLUDED.canonical_tt_id,
                status = EXCLUDED.status,
                image_id = EXCLUDED.image_id,
                image_url = EXCLUDED.image_url,
                source_width = EXCLUDED.source_width,
                source_height = EXCLUDED.source_height,
                file_path = EXCLUDED.file_path,
                file_bytes = EXCLUDED.file_bytes,
                sha256 = EXCLUDED.sha256,
                http_status = EXCLUDED.http_status,
                attempt_count = EXCLUDED.attempt_count,
                error_code = EXCLUDED.error_code,
                error_message = EXCLUDED.error_message,
                first_attempted_at = EXCLUDED.first_attempted_at,
                last_attempted_at = EXCLUDED.last_attempted_at,
                completed_at = EXCLUDED.completed_at
            """,
            [
                tt_id,
                result.canonical_tt_id,
                result.status,
                result.image_id,
                result.image_url,
                result.source_width,
                result.source_height,
                result.file_path,
                result.file_bytes,
                result.sha256,
                result.http_status,
                previous_attempts + 1,
                result.error_code,
                truncate_error_message(result.error_message or "") if result.error_message else None,
                first_attempted_at,
                attempted_at,
                completed_at,
            ],
        )


class IMDbGraphQLSource:
    def __init__(self, settings: Settings) -> None:
        require_module("requests", "the 'requests' package")
        self._requests = __import__("requests")
        self._settings = settings
        self._session = self._requests.Session()
        self._session.headers.update({"User-Agent": settings.user_agent})

    def fetch_primary_images(self, tt_ids: list[str]) -> dict[str, ImageMetadata]:
        results: dict[str, ImageMetadata] = {}
        for batch in chunked(tt_ids, self._settings.batch_size):
            batch_results = self._fetch_batch(batch)
            results.update(batch_results)
            for tt_id in batch:
                results.setdefault(
                    tt_id,
                    ImageMetadata(
                        tt_id=tt_id,
                        canonical_tt_id=None,
                        image_url=None,
                        image_id=None,
                        width=None,
                        height=None,
                    ),
                )
        return results

    def _fetch_batch(self, tt_ids: list[str]) -> dict[str, ImageMetadata]:
        payload = {
            "query": self._settings.graphql_query,
            "variables": {"ids": tt_ids},
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        headers = self._build_signed_headers(payload_bytes)

        last_error: Exception | None = None
        for attempt in range(1, self._settings.metadata_max_retries + 1):
            try:
                response = self._session.post(
                    self._settings.imdb_api_endpoint,
                    data=payload_bytes,
                    headers=headers,
                    timeout=(
                        self._settings.connect_timeout_seconds,
                        self._settings.read_timeout_seconds,
                    ),
                )
            except self._requests.RequestException as exc:
                last_error = exc
                if attempt == self._settings.metadata_max_retries:
                    raise PipelineConfigurationError(f"Metadata request failed after retries: {exc}") from exc
                time.sleep(self._backoff_delay(attempt))
                continue

            if response.status_code in {401, 403}:
                raise PipelineConfigurationError(
                    f"IMDb API returned HTTP {response.status_code}. Check credentials, subscription access, and endpoint."
                )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == self._settings.metadata_max_retries:
                    raise PipelineConfigurationError(
                        f"IMDb API metadata request failed with HTTP {response.status_code} after retries."
                    )
                time.sleep(self._retry_after_or_backoff(response, attempt))
                continue
            if response.status_code >= 400:
                raise PipelineConfigurationError(
                    f"IMDb API metadata request failed with HTTP {response.status_code}: {response.text[:200]}"
                )

            data = response.json()
            if data.get("errors"):
                raise PipelineConfigurationError(
                    "IMDb API returned GraphQL errors. Verify the configured GraphQL query against the current API schema."
                )
            return self._extract_metadata(tt_ids, data.get("data") or {})

        raise PipelineConfigurationError(f"Metadata request failed: {last_error}")

    def _build_signed_headers(self, payload_bytes: bytes) -> dict[str, str]:
        try:
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
            from botocore.session import Session
        except ImportError as exc:
            raise PipelineConfigurationError(
                "Missing dependency 'botocore'. Install boto3 or botocore so AWS SigV4 signing can be applied."
            ) from exc

        credentials = Session().get_credentials()
        if credentials is None:
            raise PipelineConfigurationError("No AWS credentials were found in the standard credential chain.")

        frozen = credentials.get_frozen_credentials()
        request = AWSRequest(
            method="POST",
            url=self._settings.imdb_api_endpoint,
            data=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "host": urlparse(self._settings.imdb_api_endpoint).netloc,
                "x-api-key": self._settings.imdb_api_key,
                "x-imdb-dataset-id": self._settings.imdb_dataset_id,
                "x-imdb-revision-id": self._settings.imdb_revision_id,
                "x-imdb-asset-id": self._settings.imdb_asset_id,
            },
        )
        SigV4Auth(frozen, self._settings.aws_service, self._settings.aws_region).add_auth(request)
        return dict(request.headers.items())

    def _extract_metadata(self, requested_ids: list[str], data: dict[str, Any]) -> dict[str, ImageMetadata]:
        by_id: dict[str, ImageMetadata] = {}
        nodes = list(self._candidate_nodes(data))
        unresolved = set(requested_ids)

        for node in nodes:
            primary_id = self._find_first_tt_id(node)
            if primary_id not in unresolved:
                continue
            image = self._find_primary_image(node)
            metadata = ImageMetadata(
                tt_id=primary_id,
                canonical_tt_id=self._find_canonical_tt_id(node),
                image_url=image.get("url") if image else None,
                image_id=image.get("id") if image else None,
                width=coerce_int(image.get("width")) if image else None,
                height=coerce_int(image.get("height")) if image else None,
            )
            by_id[primary_id] = metadata
            unresolved.discard(primary_id)

        return by_id

    def _candidate_nodes(self, value: Any) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        if isinstance(value, dict):
            nodes.append(value)
            for nested in value.values():
                nodes.extend(self._candidate_nodes(nested))
        elif isinstance(value, list):
            for nested in value:
                nodes.extend(self._candidate_nodes(nested))
        return nodes

    def _find_first_tt_id(self, value: Any) -> str | None:
        if isinstance(value, str) and is_valid_tt_id(value):
            return value
        if isinstance(value, dict):
            for key, nested in value.items():
                if key.lower() in {"id", "titleid", "ttid"} and isinstance(nested, str) and is_valid_tt_id(nested):
                    return nested
            for nested in value.values():
                found = self._find_first_tt_id(nested)
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = self._find_first_tt_id(nested)
                if found:
                    return found
        return None

    def _find_canonical_tt_id(self, value: Any) -> str | None:
        if isinstance(value, dict):
            for key, nested in value.items():
                lowered = key.lower()
                if lowered in {"canonicalid", "remappedtotitleid", "preferredtitleid"} and isinstance(nested, str) and is_valid_tt_id(nested):
                    return nested
                found = self._find_canonical_tt_id(nested)
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = self._find_canonical_tt_id(nested)
                if found:
                    return found
        return None

    def _find_primary_image(self, value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key.lower() == "primaryimage" and isinstance(nested, dict) and nested.get("url"):
                    return nested
            for nested in value.values():
                found = self._find_primary_image(nested)
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = self._find_primary_image(nested)
                if found:
                    return found
        return None

    def _backoff_delay(self, attempt: int) -> float:
        return self._settings.backoff_base_seconds * (2 ** (attempt - 1)) + random.uniform(0.0, 0.25)

    def _retry_after_or_backoff(self, response: Any, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return self._backoff_delay(attempt)


class PosterDownloader:
    def __init__(self, settings: Settings) -> None:
        require_module("requests", "the 'requests' package")
        self._requests = __import__("requests")
        self._settings = settings
        self._local = threading.local()

    def process(self, metadata: ImageMetadata) -> DownloadResult:
        if not metadata.image_url:
            return DownloadResult(
                tt_id=metadata.tt_id,
                status="no_image",
                canonical_tt_id=metadata.canonical_tt_id,
                image_id=metadata.image_id,
                source_width=metadata.width,
                source_height=metadata.height,
            )

        output_path = poster_path(self._settings.output_dir, metadata.tt_id)
        part_path = output_path.with_suffix(".jpg.part")

        for attempt in range(1, self._settings.image_max_retries + 1):
            raw_temp_path: Path | None = None
            try:
                raw_temp_path, http_status = self._download_to_temp(metadata.image_url)
                file_bytes, sha256 = self._normalize_and_save(raw_temp_path, part_path)
                os.replace(part_path, output_path)
                return DownloadResult(
                    tt_id=metadata.tt_id,
                    status="success",
                    canonical_tt_id=metadata.canonical_tt_id,
                    image_id=metadata.image_id,
                    image_url=metadata.image_url,
                    source_width=metadata.width,
                    source_height=metadata.height,
                    file_path=display_path(output_path),
                    file_bytes=file_bytes,
                    sha256=sha256,
                    http_status=http_status,
                )
            except RetryableItemError as exc:
                self._cleanup_path(part_path)
                if raw_temp_path:
                    self._cleanup_path(raw_temp_path)
                if attempt == self._settings.image_max_retries:
                    return DownloadResult(
                        tt_id=metadata.tt_id,
                        status="retryable_error",
                        canonical_tt_id=metadata.canonical_tt_id,
                        image_id=metadata.image_id,
                        image_url=metadata.image_url,
                        source_width=metadata.width,
                        source_height=metadata.height,
                        http_status=exc.http_status,
                        error_code=exc.code,
                        error_message=str(exc),
                    )
                time.sleep(exc.retry_after or self._backoff_delay(attempt))
            except PermanentItemError as exc:
                self._cleanup_path(part_path)
                if raw_temp_path:
                    self._cleanup_path(raw_temp_path)
                return DownloadResult(
                    tt_id=metadata.tt_id,
                    status="permanent_error",
                    canonical_tt_id=metadata.canonical_tt_id,
                    image_id=metadata.image_id,
                    image_url=metadata.image_url,
                    source_width=metadata.width,
                    source_height=metadata.height,
                    http_status=exc.http_status,
                    error_code=exc.code,
                    error_message=str(exc),
                )
            except OSError:
                self._cleanup_path(part_path)
                if raw_temp_path:
                    self._cleanup_path(raw_temp_path)
                raise
            finally:
                if raw_temp_path:
                    self._cleanup_path(raw_temp_path)

        raise AssertionError("unreachable")

    def _session(self) -> Any:
        if not hasattr(self._local, "session"):
            session = self._requests.Session()
            session.headers.update({"User-Agent": self._settings.user_agent})
            self._local.session = session
        return self._local.session

    def _download_to_temp(self, image_url: str) -> tuple[Path, int]:
        try:
            response = self._session().get(
                image_url,
                stream=True,
                timeout=(
                    self._settings.connect_timeout_seconds,
                    self._settings.read_timeout_seconds,
                ),
            )
        except self._requests.Timeout as exc:
            raise RetryableItemError("timeout", f"Timed out downloading image: {image_url}") from exc
        except self._requests.ConnectionError as exc:
            raise RetryableItemError("connection_error", f"Connection error downloading image: {image_url}") from exc
        except self._requests.RequestException as exc:
            raise RetryableItemError("request_error", f"Request failed downloading image: {image_url}") from exc

        if response.status_code == 429:
            raise RetryableItemError(
                "http_429",
                f"Image URL returned HTTP 429 for {image_url}",
                http_status=response.status_code,
                retry_after=self._retry_after(response),
            )
        if 500 <= response.status_code < 600:
            raise RetryableItemError(
                f"http_{response.status_code}",
                f"Image URL returned HTTP {response.status_code} for {image_url}",
                http_status=response.status_code,
            )
        if response.status_code in {404, 410}:
            raise PermanentItemError(
                "image_not_found",
                f"Image URL returned HTTP {response.status_code} for {image_url}",
                http_status=response.status_code,
            )
        if response.status_code >= 400:
            raise PermanentItemError(
                f"http_{response.status_code}",
                f"Image URL returned HTTP {response.status_code} for {image_url}",
                http_status=response.status_code,
            )

        content_type = (response.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("image/"):
            raise PermanentItemError(
                "invalid_content_type",
                f"Expected image content but received '{content_type or 'unknown'}' from {image_url}",
                http_status=response.status_code,
            )

        with NamedTemporaryFile(delete=False, dir=self._settings.output_dir, suffix=".download") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    fh.write(chunk)
            temp_path = Path(fh.name)

        if temp_path.stat().st_size == 0:
            raise PermanentItemError("empty_body", f"Downloaded image body was empty for {image_url}")

        return temp_path, response.status_code

    def _normalize_and_save(self, raw_path: Path, part_path: Path) -> tuple[int, str]:
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise PipelineConfigurationError("Missing dependency 'Pillow'. Install the 'Pillow' package.") from exc

        self._cleanup_path(part_path)

        try:
            with Image.open(raw_path) as image:
                image.load()
                image = ImageOps.exif_transpose(image)
                if image.width <= 0 or image.height <= 0:
                    raise PermanentItemError("invalid_dimensions", "Image decoded with non-positive dimensions.")
                if self._settings.max_edge_pixels:
                    image.thumbnail(
                        (self._settings.max_edge_pixels, self._settings.max_edge_pixels),
                        getattr(Image, "Resampling", Image).LANCZOS,
                    )
                image = image.convert("RGB")
                image.save(
                    part_path,
                    format="JPEG",
                    quality=self._settings.jpeg_quality,
                    optimize=True,
                )
        except PermanentItemError:
            raise
        except OSError as exc:
            raise PermanentItemError("corrupt_image", f"Unable to decode or normalize image: {exc}") from exc

        if not validate_existing_jpeg(part_path):
            raise PermanentItemError("invalid_normalized_jpeg", "Normalized image failed JPEG validation.")

        file_bytes = part_path.stat().st_size
        sha256 = file_sha256(part_path)
        return file_bytes, sha256

    def _cleanup_path(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except FileNotFoundError:
            return

    def _backoff_delay(self, attempt: int) -> float:
        return self._settings.backoff_base_seconds * (2 ** (attempt - 1)) + random.uniform(0.0, 0.25)

    def _retry_after(self, response: Any) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(float(value), 0.0)
        except ValueError:
            return None


def classify_work(
    settings: Settings,
    input_ids: list[str],
    status_rows: dict[str, dict[str, Any]],
) -> tuple[list[WorkItem], list[DownloadResult], int]:
    work_items: list[WorkItem] = []
    immediate_results: list[DownloadResult] = []
    skipped = 0

    for tt_id in input_ids:
        existing = status_rows.get(tt_id)

        if not is_valid_tt_id(tt_id):
            immediate_results.append(
                DownloadResult(
                    tt_id=tt_id,
                    status="invalid_id",
                    error_code="invalid_id",
                    error_message=f"Identifier does not match ^tt\\d{{7,}}$: {tt_id}",
                )
            )
            continue

        output_path = poster_path(settings.output_dir, tt_id)
        valid_file = validate_existing_jpeg(output_path)

        if settings.force:
            work_items.append(WorkItem(tt_id=tt_id, existing_status=existing))
            continue

        if settings.refresh:
            work_items.append(WorkItem(tt_id=tt_id, existing_status=existing))
            continue

        if existing and existing.get("status") == "success" and valid_file:
            skipped += 1
            continue

        if existing and existing.get("status") in {"no_image", "invalid_id", "permanent_error"}:
            skipped += 1
            continue

        work_items.append(WorkItem(tt_id=tt_id, existing_status=existing))

    return work_items, immediate_results, skipped


def process_items(
    settings: Settings,
    repository: DuckDBRepository,
    work_items: list[WorkItem],
    source: IMDbGraphQLSource,
) -> list[DownloadResult]:
    results: list[DownloadResult] = []
    downloader = PosterDownloader(settings)

    for batch in chunked([item.tt_id for item in work_items], settings.batch_size):
        metadata_by_id = source.fetch_primary_images(batch)
        download_candidates: list[tuple[WorkItem, ImageMetadata]] = []

        for tt_id in batch:
            item = next(work_item for work_item in work_items if work_item.tt_id == tt_id)
            metadata = metadata_by_id.get(tt_id) or ImageMetadata(tt_id, None, None, None, None, None)
            existing = item.existing_status or {}
            output_path = poster_path(settings.output_dir, tt_id)

            if settings.refresh and not settings.force:
                if (
                    existing.get("status") == "success"
                    and validate_existing_jpeg(output_path)
                    and existing.get("image_id")
                    and existing.get("image_id") == metadata.image_id
                ):
                    results.append(
                        DownloadResult(
                            tt_id=tt_id,
                            status="success",
                            canonical_tt_id=metadata.canonical_tt_id or existing.get("canonical_tt_id"),
                            image_id=metadata.image_id or existing.get("image_id"),
                            image_url=metadata.image_url or existing.get("image_url"),
                            source_width=metadata.width or existing.get("source_width"),
                            source_height=metadata.height or existing.get("source_height"),
                            file_path=display_path(output_path),
                            file_bytes=output_path.stat().st_size,
                            sha256=existing.get("sha256") or file_sha256(output_path),
                            http_status=existing.get("http_status"),
                        )
                    )
                    continue

            if not metadata.image_url:
                results.append(
                    DownloadResult(
                        tt_id=tt_id,
                        status="no_image",
                        canonical_tt_id=metadata.canonical_tt_id,
                        image_id=metadata.image_id,
                        image_url=metadata.image_url,
                        source_width=metadata.width,
                        source_height=metadata.height,
                    )
                )
                continue

            download_candidates.append((item, metadata))

        with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
            future_map = {
                executor.submit(downloader.process, metadata): item for item, metadata in download_candidates
            }
            for future in as_completed(future_map):
                results.append(future.result())

    return results


def persist_results(
    repository: DuckDBRepository,
    work_items: list[WorkItem],
    results: list[DownloadResult],
) -> None:
    previous_attempts = {
        item.tt_id: int((item.existing_status or {}).get("attempt_count") or 0)
        for item in work_items
    }
    for result in results:
        repository.upsert_status(result.tt_id, result, previous_attempts.get(result.tt_id, 0))


def print_summary(
    total_ids: int,
    skipped: int,
    dry_run: bool,
    results: list[DownloadResult],
    started_at: float,
) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    print(f"total_input_ids={total_ids}")
    print(f"skipped_existing={skipped}")
    for key in ["success", "no_image", "invalid_id", "retryable_error", "permanent_error"]:
        print(f"{key}={counts.get(key, 0)}")
    print(f"dry_run={str(dry_run).lower()}")
    print(f"elapsed_seconds={time.time() - started_at:.2f}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retrieve and normalize IMDb poster images into posters/<tt_id>.jpg")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH), help="Path to a .env file containing runtime configuration.")
    parser.add_argument("--database-path", help="DuckDB database path. Overrides DATABASE_PATH.")
    parser.add_argument("--poster-source-query", help="SQL query that returns one column aliased as tt_id.")
    parser.add_argument("--output-dir", help="Output directory for normalized posters. Defaults to posters/.")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and report work without API calls or file writes.")
    parser.add_argument("--limit", type=int, help="Process at most N input IDs.")
    parser.add_argument("--resume", action="store_true", help="Resume pending or retryable work. This is the default behavior.")
    parser.add_argument("--refresh", action="store_true", help="Refresh metadata for completed rows and redownload only when image_id changed.")
    parser.add_argument("--force", action="store_true", help="Redownload even if a valid local file already exists.")
    parser.add_argument("--tt-id", help="Process a single tt identifier without executing POSTER_SOURCE_QUERY.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    started_at = time.time()

    try:
        settings = build_settings(args)
        settings.output_dir.mkdir(parents=True, exist_ok=True)

        repository = DuckDBRepository(settings)
        repository.ensure_schema()
        input_ids = repository.fetch_input_ids()
        status_rows = repository.fetch_status_rows()
        work_items, immediate_results, skipped = classify_work(settings, input_ids, status_rows)

        if settings.dry_run:
            print(f"dry_run_input_ids={len(input_ids)}")
            print(f"dry_run_work_items={len(work_items)}")
            print(f"dry_run_invalid_ids={sum(1 for item in immediate_results if item.status == 'invalid_id')}")
            print(f"dry_run_skipped_existing={skipped}")
            return 0

        source = IMDbGraphQLSource(settings)
        processed_results = process_items(settings, repository, work_items, source)
        all_results = immediate_results + processed_results
        persist_results(repository, work_items, all_results)
        print_summary(len(input_ids), skipped, settings.dry_run, all_results, started_at)
        return 0
    except PipelineConfigurationError as exc:
        print(f"configuration_error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    finally:
        repository = locals().get("repository")
        if repository is not None:
            repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
