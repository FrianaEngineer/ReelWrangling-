from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "imdb_poster_pipeline.py"
SPEC = importlib.util.spec_from_file_location("imdb_poster_pipeline", MODULE_PATH)
pipeline = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pipeline
SPEC.loader.exec_module(pipeline)


def make_settings(tmp_path: Path, **overrides) -> "pipeline.Settings":
    defaults = dict(
        database_path=tmp_path / "db.duckdb",
        poster_source_query="SELECT DISTINCT imdb_tt_id AS tt_id FROM titles",
        output_dir=tmp_path / "posters",
        status_table="poster_download_status",
        dry_run=False,
        limit=None,
        resume=True,
        refresh=False,
        force=False,
        tt_id=None,
        batch_size=25,
        max_workers=1,
        connect_timeout_seconds=5.0,
        read_timeout_seconds=5.0,
        metadata_max_retries=1,
        image_max_retries=1,
        backoff_base_seconds=0.01,
        jpeg_quality=90,
        max_edge_pixels=None,
        user_agent="test-agent",
        env_path=tmp_path / ".env",
        imdb_api_endpoint="https://example.invalid/graphql",
        imdb_api_key="key",
        imdb_dataset_id="dataset",
        imdb_revision_id="revision",
        imdb_asset_id="asset",
        aws_region="us-east-1",
        aws_service="appsync",
        graphql_query=pipeline.DEFAULT_GRAPHQL_QUERY,
    )
    defaults.update(overrides)
    defaults["output_dir"].mkdir(parents=True, exist_ok=True)
    return pipeline.Settings(**defaults)


# ---------------------------------------------------------------------------
# Identifier validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tt_id",
    ["tt0050083", "tt12345678", "tt00500831234"],
)
def test_valid_tt_ids_accepted(tt_id):
    assert pipeline.is_valid_tt_id(tt_id) is True


@pytest.mark.parametrize(
    "tt_id",
    [
        "",
        "tt123",
        "tt 0050083",
        "https://www.imdb.com/title/tt0050083/",
        "nm0000001",
        "TT0050083",
        "tt0050083x",
        "../../etc/passwd",
    ],
)
def test_invalid_tt_ids_rejected(tt_id):
    assert pipeline.is_valid_tt_id(tt_id) is False


# ---------------------------------------------------------------------------
# Filename / path construction
# ---------------------------------------------------------------------------

def test_poster_path_builds_expected_filename(tmp_path):
    output_dir = tmp_path / "posters"
    path = pipeline.poster_path(output_dir, "tt0050083")
    assert path == output_dir / "tt0050083.jpg"


def test_poster_path_rejects_invalid_ids_and_never_escapes(tmp_path):
    output_dir = tmp_path / "posters"
    output_dir.mkdir()
    for malicious_id in ["../../etc/passwd", "tt../../x", "tt0050083/../../x"]:
        with pytest.raises(ValueError):
            pipeline.poster_path(output_dir, malicious_id)


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "current_status,new_status,expected",
    [
        (None, "success", True),
        (None, "retryable_error", True),
        ("retryable_error", "success", True),
        ("retryable_error", "retryable_error", True),
        ("success", "success", True),
        ("success", "pending", False),
        ("no_image", "pending", False),
        ("permanent_error", "pending", False),
        ("invalid_id", "pending", False),
    ],
)
def test_status_transitions(current_status, new_status, expected):
    assert pipeline.is_allowed_status_transition(current_status, new_status) is expected


# ---------------------------------------------------------------------------
# Image validation
# ---------------------------------------------------------------------------

def _make_real_jpeg(path: Path, size=(10, 10)) -> None:
    from PIL import Image

    Image.new("RGB", size, color=(255, 0, 0)).save(path, format="JPEG")


def test_validate_existing_jpeg_missing_file(tmp_path):
    assert pipeline.validate_existing_jpeg(tmp_path / "missing.jpg") is False


def test_validate_existing_jpeg_empty_file(tmp_path):
    path = tmp_path / "empty.jpg"
    path.write_bytes(b"")
    assert pipeline.validate_existing_jpeg(path) is False


def test_validate_existing_jpeg_html_body(tmp_path):
    path = tmp_path / "error.jpg"
    path.write_bytes(b"<html><body>404 Not Found</body></html>")
    assert pipeline.validate_existing_jpeg(path) is False


def test_validate_existing_jpeg_wrong_format_content(tmp_path):
    from PIL import Image

    path = tmp_path / "actually_png.jpg"
    Image.new("RGB", (5, 5)).save(path, format="PNG")
    assert pipeline.validate_existing_jpeg(path) is False


def test_validate_existing_jpeg_accepts_real_jpeg(tmp_path):
    path = tmp_path / "real.jpg"
    _make_real_jpeg(path)
    assert pipeline.validate_existing_jpeg(path) is True


# ---------------------------------------------------------------------------
# Atomic write / normalization behavior
# ---------------------------------------------------------------------------

def test_normalize_and_save_rejects_corrupt_image_without_leaving_partial_file(tmp_path):
    settings = make_settings(tmp_path)
    downloader = pipeline.PosterDownloader(settings)

    raw_path = tmp_path / "raw.download"
    raw_path.write_bytes(b"not-an-image-just-garbage-bytes")
    part_path = settings.output_dir / "tt0050083.jpg.part"

    with pytest.raises(pipeline.PermanentItemError):
        downloader._normalize_and_save(raw_path, part_path)

    assert not part_path.exists()


def test_normalize_and_save_writes_valid_jpeg_and_checksum(tmp_path):
    settings = make_settings(tmp_path)
    downloader = pipeline.PosterDownloader(settings)

    raw_path = tmp_path / "raw.download"
    _make_real_jpeg(raw_path, size=(50, 50))
    part_path = settings.output_dir / "tt0050083.jpg.part"

    file_bytes, sha256 = downloader._normalize_and_save(raw_path, part_path)

    assert part_path.exists()
    assert file_bytes > 0
    assert len(sha256) == 64
    assert pipeline.validate_existing_jpeg(part_path) is True
