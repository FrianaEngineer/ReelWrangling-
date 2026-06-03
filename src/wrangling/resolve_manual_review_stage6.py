#!/usr/bin/env python3
"""
Resolve current manual-review rows into Stage 6 outcome buckets.

Inputs:
  data/output/manual_review_titles.csv
  data/output/manual_resolution_log.csv

Outputs:
  data/output/manual_review_stage6.csv
  data/output/manual_review_stage6_summary.csv
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = REPO_ROOT / "data" / "output"

MANUAL_REVIEW = OUTPUTS / "manual_review_titles.csv"
MANUAL_LOG = OUTPUTS / "manual_resolution_log.csv"
OUT_ROWS = OUTPUTS / "manual_review_stage6.csv"
OUT_SUMMARY = OUTPUTS / "manual_review_stage6_summary.csv"


OTHER_CONTENT_TYPES = {
    "documentary",
    "short",
    "tvMiniSeries",
    "tvMovie",
    "tvSeries",
    "tvSpecial",
    "video",
}

YEARS_OFF_TITLES = {
    "I Am Curious—Blue",
    "The Gold Rush",
    "Gray’s Anatomy",
    "Blind Chance",
    "War and Peace",
    "Nobody’s Children",
}

YEARS_MATCH_OVERRIDES = {
    "Fanny and Alexander": "Resolved to the 1982 theatrical film; the source row lacks a year, but the Criterion title is being normalized to that single movie.",
}


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def stage6_bucket(row: dict, log_row: dict) -> tuple[str, str]:
    title = row["criterion_title_original"]
    criterion_year = row["criterion_year"].strip()
    entity_type = log_row["entity_type"].strip()

    # King Kong vs. Godzilla was previously misfiled as a collection label.
    if title == "King Kong vs. Godzilla":
        return "Years Match", "IMDb resolves this row as the 1963 film entry, not a collection label."

    if entity_type in OTHER_CONTENT_TYPES:
        return "Other Content", f"IMDb entity type is {entity_type}."

    if entity_type in {"collection", "collection_label"}:
        return "Unverified Titles", "Bundled/collection record; not a single-title feature-film row."

    if entity_type == "movie":
        if title in YEARS_MATCH_OVERRIDES:
            return "Years Match", YEARS_MATCH_OVERRIDES[title]
        if not criterion_year:
            return "Unverified Titles", "Resolved as a movie, but the Criterion row lacks a usable year for final verification."
        if title in YEARS_OFF_TITLES:
            return "Years Off", "Resolved as a feature film, but Criterion and IMDb years do not agree."
        return "Years Match", "Resolved as a feature film with matching Criterion and IMDb year."

    return "Data Issues / Untracked", "No stable Stage 6 mapping rule matched this row."


def main() -> None:
    manual_rows = load_csv(MANUAL_REVIEW)
    log_rows = {row["criterion_row_id"]: row for row in load_csv(MANUAL_LOG)}

    resolved_rows: list[dict] = []
    bucket_counts: Counter[str] = Counter()

    for row in manual_rows:
        log_row = log_rows[row["criterion_row_id"]]
        bucket, reason = stage6_bucket(row, log_row)
        bucket_counts[bucket] += 1
        resolved_rows.append(
            {
                "criterion_row_id": row["criterion_row_id"],
                "criterion_source_id": row["criterion_source_id"],
                "criterion_title_original": row["criterion_title_original"],
                "criterion_year": row["criterion_year"],
                "current_status": row["status"],
                "current_entity_type": row["entity_type"],
                "resolved_entity_type": log_row["entity_type"],
                "imdb_id": log_row["imdb_id"],
                "imdb_title": log_row["imdb_title"],
                "stage6_bucket": bucket,
                "reason": reason,
                "notes": log_row["notes"],
            }
        )

    write_csv(OUT_ROWS, resolved_rows)

    summary_rows = [
        {"stage6_bucket": bucket, "count": count}
        for bucket, count in sorted(bucket_counts.items())
    ]
    write_csv(OUT_SUMMARY, summary_rows)

    print(f"wrote {OUT_ROWS} ({len(resolved_rows)} rows)")
    print(f"wrote {OUT_SUMMARY} ({len(summary_rows)} buckets)")


if __name__ == "__main__":
    main()
