#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "data" / "output" / "manual_resolution_log.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "output" / "nonFeatureMismatches.csv"
NONFEATURE_TYPES = {"tvSeries", "tvMiniSeries", "tvMovie", "video"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export manual-review non-feature mismatch entries."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    with input_path.open("r", encoding="utf-8", newline="") as infile:
        rows = list(csv.DictReader(infile))

    filtered = [
        {
            "criterion_row_id": row.get("criterion_row_id", ""),
            "criterion_source_id": row.get("criterion_source_id", ""),
            "criterion_title_original": row.get("criterion_title_original", ""),
            "criterion_director_original": row.get("criterion_director_original", ""),
            "criterion_year": row.get("criterion_year", ""),
            "entity_type": row.get("entity_type", ""),
            "final_action": row.get("final_action", ""),
            "imdb_id": row.get("imdb_id", ""),
            "imdb_title": row.get("imdb_title", ""),
            "notes": row.get("notes", ""),
            "resolved_at": row.get("resolved_at", ""),
        }
        for row in rows
        if row.get("final_action") == "matched" and row.get("entity_type") in NONFEATURE_TYPES
    ]

    with output_path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(
            outfile,
            fieldnames=[
                "criterion_row_id",
                "criterion_source_id",
                "criterion_title_original",
                "criterion_director_original",
                "criterion_year",
                "entity_type",
                "final_action",
                "imdb_id",
                "imdb_title",
                "notes",
                "resolved_at",
            ],
        )
        writer.writeheader()
        writer.writerows(filtered)


if __name__ == "__main__":
    main()
