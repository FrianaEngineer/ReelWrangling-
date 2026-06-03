#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from src.shared.utils import ensure_output_dir, timestamp_utc, write_csv

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the stable unmatched tracking worklist.")
    parser.add_argument("--unmatched-input", default=str(REPO_ROOT / "data" / "output" / "unmatched_initial.csv"))
    parser.add_argument("--review-input", default=str(REPO_ROOT / "data" / "output" / "match_candidates_review.csv"))
    parser.add_argument("--excluded-shorts-input", default=str(REPO_ROOT / "data" / "output" / "excluded_shorts_seed.csv"))
    parser.add_argument("--output", default=str(REPO_ROOT / "data" / "output" / "unmatched_tracking.csv"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows_by_id: dict[str, dict] = {}
    excluded_row_ids = set()
    excluded_path = Path(args.excluded_shorts_input)
    if excluded_path.exists() and excluded_path.stat().st_size > 0:
        with excluded_path.open("r", encoding="utf-8", newline="") as handle:
            excluded_row_ids = {row["criterion_row_id"] for row in csv.DictReader(handle)}

    with Path(args.review_input).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row_id = row["criterion_row_id"]
            if row_id in excluded_row_ids or row_id in rows_by_id:
                continue
            rows_by_id[row_id] = {
                "criterion_row_id": row_id,
                "criterion_source_id": row["criterion_source_id"],
                "criterion_title_original": row["criterion_title_original"],
                "criterion_year": row["criterion_year"],
                "review_status": "needs_manual_review",
                "entity_type": "",
                "candidate_imdb_id": row["imdb_id"],
                "candidate_imdb_title": row["imdb_primary_title"],
                "final_action": "",
                "rationale": "",
                "notes": "",
                "last_updated": timestamp_utc(),
            }

    with Path(args.unmatched_input).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row_id = row["criterion_row_id"]
            if row_id in excluded_row_ids:
                continue
            rows_by_id[row_id] = {
                "criterion_row_id": row_id,
                "criterion_source_id": row["criterion_source_id"],
                "criterion_title_original": row["criterion_title_original"],
                "criterion_year": row["criterion_year"],
                "review_status": row.get("review_status") or "unreviewed",
                "entity_type": row.get("entity_type", ""),
                "candidate_imdb_id": row.get("candidate_imdb_id", ""),
                "candidate_imdb_title": "",
                "final_action": row.get("final_action", ""),
                "rationale": row.get("rationale", ""),
                "notes": row.get("notes", ""),
                "last_updated": row.get("last_updated") or timestamp_utc(),
            }

    ensure_output_dir(Path(args.output).parent)
    write_csv(Path(args.output), list(rows_by_id.values()))


if __name__ == "__main__":
    main()
