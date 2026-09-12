#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import getpass
import os
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT_CSV = PROJECT_ROOT / "data" / "output" / "query.csv"
DEFAULT_POSTER_DIR = PROJECT_ROOT / "data" / "posters"
DEFAULT_MANIFEST_CSV = PROJECT_ROOT / "data" / "output" / "poster_manifest.csv"

TMDB_TOKEN_ENV_VAR = "TMDB_BEARER_TOKEN"
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
POSTER_SIZE = "w500"

REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1.0

ESSENTIAL_COLUMNS = ["filmLabel", "tmdbId"]
EXPECTED_COLUMNS = ["ceremonyYear", "filmLabel", "imdbId", "tmdbId"]
MANIFEST_FIELDS = [
    "ceremonyYear",
    "filmLabel",
    "imdbId",
    "tmdbId",
    "posterPath",
    "posterUrl",
    "localPosterPath",
    "status",
    "error",
]


class CsvValidationError(RuntimeError):
    pass


class MovieNotFoundError(RuntimeError):
    pass


class ApiRequestError(RuntimeError):
    pass


class AuthenticationError(ApiRequestError):
    pass


class DownloadError(RuntimeError):
    pass


@dataclass
class ManifestRow:
    ceremonyYear: str
    filmLabel: str
    imdbId: str
    tmdbId: str
    posterPath: str = ""
    posterUrl: str = ""
    localPosterPath: str = ""
    status: str = ""
    error: str = ""


def normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (key or "").strip().lower())


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise CsvValidationError("CSV file has no header row.")

        normalized_to_actual = {normalize_key(name): name for name in reader.fieldnames}
        canonical_map: dict[str, str] = {}
        for canonical in EXPECTED_COLUMNS:
            actual = normalized_to_actual.get(normalize_key(canonical))
            if actual is not None:
                canonical_map[canonical] = actual

        missing_essential = [c for c in ESSENTIAL_COLUMNS if c not in canonical_map]
        if missing_essential:
            raise CsvValidationError(
                f"Missing required column(s): {', '.join(missing_essential)}. "
                f"Found headers: {', '.join(reader.fieldnames)}"
            )

        rows = []
        for raw_row in reader:
            normalized_row = {}
            for canonical in EXPECTED_COLUMNS:
                actual = canonical_map.get(canonical)
                normalized_row[canonical] = (raw_row.get(actual) or "").strip() if actual else ""
            rows.append(normalized_row)
        return rows


def slugify(title: str) -> str:
    if not title:
        return "untitled"
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    if not ascii_text.strip():
        ascii_text = title
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    return slug or "untitled"


def relative_to_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def backoff_delay(attempt: int) -> float:
    return RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


def retry_after_or_backoff(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    return backoff_delay(attempt)


def has_valid_image_signature(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            header = fh.read(12)
    except OSError:
        return False
    if header.startswith(b"\xff\xd8\xff"):
        return True
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return True
    if header.startswith((b"GIF87a", b"GIF89a")):
        return True
    return False


def get_tmdb_token() -> str:
    token = os.environ.get(TMDB_TOKEN_ENV_VAR, "").strip()
    if token:
        return token

    if sys.stdin.isatty():
        token = getpass.getpass("Paste your TMDB API Read Access Token: ").strip()
        if token:
            return token

    raise RuntimeError(
        f"{TMDB_TOKEN_ENV_VAR} is not set. Set the environment variable, or run this "
        "script in an interactive terminal so it can prompt for the token, then run "
        "the command again."
    )


def fetch_movie_details(session: requests.Session, tmdb_id: str, token: str) -> dict:
    url = f"{TMDB_API_BASE}/movie/{tmdb_id}?language=en-US"
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    last_error = "unknown error"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt == MAX_RETRIES:
                raise ApiRequestError(last_error) from exc
            time.sleep(backoff_delay(attempt))
            continue

        if response.status_code == 404:
            raise MovieNotFoundError(f"TMDB returned HTTP 404 for movie id {tmdb_id}")

        if response.status_code == 401:
            raise AuthenticationError(
                "TMDB rejected the API token (HTTP 401). Check that TMDB_BEARER_TOKEN is a "
                "valid, current TMDB API Read Access Token, or regenerate it."
            )

        if response.status_code == 403:
            raise AuthenticationError(
                "TMDB token does not have permission for this request (HTTP 403)."
            )

        if response.status_code == 429 or 500 <= response.status_code < 600:
            last_error = f"HTTP {response.status_code}"
            if attempt == MAX_RETRIES:
                raise ApiRequestError(last_error)
            time.sleep(retry_after_or_backoff(response, attempt))
            continue

        if response.status_code >= 400:
            raise ApiRequestError(f"HTTP {response.status_code}: {response.text[:200]}")

        try:
            return response.json()
        except ValueError as exc:
            raise ApiRequestError(f"Invalid JSON response from TMDB: {exc}") from exc

    raise ApiRequestError(last_error)


def download_poster(session: requests.Session, url: str, dest_path: Path) -> None:
    part_path = dest_path.with_name(dest_path.name + ".part")
    last_error = "unknown error"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt == MAX_RETRIES:
                raise DownloadError(last_error) from exc
            time.sleep(backoff_delay(attempt))
            continue

        try:
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = f"HTTP {response.status_code}"
                if attempt == MAX_RETRIES:
                    raise DownloadError(last_error)
                time.sleep(retry_after_or_backoff(response, attempt))
                continue

            if response.status_code != 200:
                raise DownloadError(f"HTTP {response.status_code} downloading poster image")

            with open(part_path, "wb") as fh:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        fh.write(chunk)
        finally:
            response.close()

        if not part_path.exists() or part_path.stat().st_size == 0:
            part_path.unlink(missing_ok=True)
            raise DownloadError("Downloaded poster file was empty.")

        if not has_valid_image_signature(part_path):
            part_path.unlink(missing_ok=True)
            raise DownloadError("Downloaded content was not a recognized image (possibly an error page).")

        os.replace(part_path, dest_path)
        return

    raise DownloadError(last_error)


def find_existing_poster(poster_dir: Path, year_seg: str, slug: str, tmdb_id: str) -> Path | None:
    pattern = f"{year_seg}_{slug}_{tmdb_id}.*"
    for candidate in sorted(poster_dir.glob(pattern)):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def process_row(
    session: requests.Session,
    token: str,
    row: dict[str, str],
    index: int,
    total: int,
    poster_dir: Path,
    overwrite: bool,
) -> ManifestRow:
    ceremony_year = row.get("ceremonyYear", "")
    film_label = row.get("filmLabel", "") or "Untitled"
    imdb_id = row.get("imdbId", "")
    tmdb_id = row.get("tmdbId", "")

    year_seg = ceremony_year if ceremony_year else "unknown_year"
    slug = slugify(film_label)

    manifest_row = ManifestRow(
        ceremonyYear=ceremony_year,
        filmLabel=film_label,
        imdbId=imdb_id,
        tmdbId=tmdb_id,
    )

    if not tmdb_id or not tmdb_id.isdigit():
        manifest_row.status = "missing_tmdb_id"
        manifest_row.error = "tmdbId is blank or not numeric"
        print(f"[{index}/{total}] {film_label}: skipped (missing TMDB id)")
        return manifest_row

    if not overwrite:
        existing = find_existing_poster(poster_dir, year_seg, slug, tmdb_id)
        if existing is not None:
            manifest_row.status = "already_exists"
            manifest_row.localPosterPath = relative_to_root(existing)
            print(f"[{index}/{total}] {film_label}: already exists")
            return manifest_row

    try:
        details = fetch_movie_details(session, tmdb_id, token)
    except MovieNotFoundError as exc:
        manifest_row.status = "movie_not_found"
        manifest_row.error = str(exc)
        print(f"[{index}/{total}] {film_label}: TMDB movie not found (id {tmdb_id})")
        return manifest_row
    except AuthenticationError:
        raise
    except ApiRequestError as exc:
        manifest_row.status = "api_failed"
        manifest_row.error = str(exc)
        print(f"[{index}/{total}] {film_label}: TMDB request failed ({exc})")
        return manifest_row

    poster_path_field = (details or {}).get("poster_path")
    if not poster_path_field:
        manifest_row.status = "missing_poster"
        manifest_row.error = "TMDB has no primary poster for this movie"
        print(f"[{index}/{total}] {film_label}: no poster available")
        return manifest_row

    poster_url = f"{TMDB_IMAGE_BASE}/{POSTER_SIZE}{poster_path_field}"
    manifest_row.posterPath = poster_path_field
    manifest_row.posterUrl = poster_url

    ext = Path(poster_path_field).suffix or ".jpg"
    filename = f"{year_seg}_{slug}_{tmdb_id}{ext}"
    dest_path = poster_dir / filename

    if not overwrite and dest_path.exists() and dest_path.stat().st_size > 0:
        manifest_row.status = "already_exists"
        manifest_row.localPosterPath = relative_to_root(dest_path)
        print(f"[{index}/{total}] {film_label}: already exists")
        return manifest_row

    try:
        download_poster(session, poster_url, dest_path)
    except DownloadError as exc:
        manifest_row.status = "download_failed"
        manifest_row.error = str(exc)
        print(f"[{index}/{total}] {film_label}: download failed ({exc})")
        return manifest_row

    manifest_row.status = "downloaded"
    manifest_row.localPosterPath = relative_to_root(dest_path)
    print(f"[{index}/{total}] {film_label}: downloaded -> {manifest_row.localPosterPath}")
    return manifest_row


def write_manifest(path: Path, rows: list[ManifestRow]) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    os.replace(tmp_path, path)


def resolve_path_arg(value: str | None, default: Path) -> Path:
    if value is None:
        return default
    return Path(value).expanduser().resolve()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="get_poster.py",
        description=(
            "Download primary TMDB posters (w500) for the Best Picture winners listed in "
            "data/output/query.csv, and write a manifest of the results."
        ),
        epilog=(
            f"Credential: reads the TMDB API Read Access Token from the {TMDB_TOKEN_ENV_VAR} "
            "environment variable (never hard-coded). If that variable is unset and the session is "
            "interactive, you will be prompted to paste the token (input hidden, held only in memory "
            "for this run). Non-interactive runs without the variable fail with a clear error. "
            f"Default input: {relative_to_root(DEFAULT_INPUT_CSV)} (resolved relative to this script, "
            "not the current working directory). "
            f"Default poster output directory: {relative_to_root(DEFAULT_POSTER_DIR)}. "
            f"Default manifest: {relative_to_root(DEFAULT_MANIFEST_CSV)}. "
            "By default, existing nonempty posters are left alone so reruns are fast; pass --overwrite "
            "to redownload them. Paths given via --input/--output-dir/--manifest are resolved relative "
            "to the current working directory."
        ),
    )
    parser.add_argument("--input", help="Path to the input CSV (default: data/output/query.csv next to this script).")
    parser.add_argument("--output-dir", help="Directory to write downloaded posters into (default: data/posters).")
    parser.add_argument("--manifest", help="Path to write the poster manifest CSV (default: data/output/poster_manifest.csv).")
    parser.add_argument("--overwrite", action="store_true", help="Redownload and overwrite posters that already exist locally.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    try:
        token = get_tmdb_token()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    input_csv = resolve_path_arg(args.input, DEFAULT_INPUT_CSV)
    poster_dir = resolve_path_arg(args.output_dir, DEFAULT_POSTER_DIR)
    manifest_csv = resolve_path_arg(args.manifest, DEFAULT_MANIFEST_CSV)

    if not input_csv.exists():
        print(f"Input CSV not found: {input_csv}", file=sys.stderr)
        return 1

    try:
        rows = read_csv_rows(input_csv)
    except CsvValidationError as exc:
        print(f"CSV validation error: {exc}", file=sys.stderr)
        return 1

    poster_dir.mkdir(parents=True, exist_ok=True)
    manifest_csv.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    manifest_rows: list[ManifestRow] = []
    total = len(rows)
    auth_failed = False

    try:
        for index, row in enumerate(rows, start=1):
            manifest_rows.append(process_row(session, token, row, index, total, poster_dir, args.overwrite))
    except AuthenticationError as exc:
        auth_failed = True
        print(f"\nStopping: {exc}", file=sys.stderr)
        for row in rows[len(manifest_rows):]:
            manifest_rows.append(
                ManifestRow(
                    ceremonyYear=row.get("ceremonyYear", ""),
                    filmLabel=row.get("filmLabel", "") or "Untitled",
                    imdbId=row.get("imdbId", ""),
                    tmdbId=row.get("tmdbId", ""),
                    status="api_failed",
                    error="Skipped: run stopped after a TMDB authentication failure.",
                )
            )

    write_manifest(manifest_csv, manifest_rows)

    counts: dict[str, int] = {}
    for row in manifest_rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    downloaded = counts.get("downloaded", 0)
    already_present = counts.get("already_exists", 0)
    missing_or_failed = total - downloaded - already_present

    print()
    print("Poster download complete" if not auth_failed else "Poster download stopped early")
    print(f"Rows processed: {total}")
    print(f"Downloaded: {downloaded}")
    print(f"Already present: {already_present}")
    print(f"Missing or failed: {missing_or_failed}")
    print(f"Manifest: {relative_to_root(manifest_csv)}")

    return 1 if auth_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
