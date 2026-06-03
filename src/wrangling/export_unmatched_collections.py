#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "data" / "output" / "resolved_collections.csv"
DEFAULT_CONSTITUENTS = REPO_ROOT / "data" / "output" / "collection_constituent_films.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "output" / "unmatchedCollections.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export unresolved collection rows that include feature-length movie constituents."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--constituents", default=str(DEFAULT_CONSTITUENTS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    constituents_path = Path(args.constituents)
    output_path = Path(args.output)

    with input_path.open("r", encoding="utf-8", newline="") as infile:
        rows = list(csv.DictReader(infile))
    with constituents_path.open("r", encoding="utf-8", newline="") as infile:
        constituent_rows = list(csv.DictReader(infile))

    feature_counts_by_source: dict[str, int] = defaultdict(int)
    for row in constituent_rows:
        if row.get("include_in_dataset") != "true":
            continue
        if row.get("imdb_title_type") != "movie":
            continue
        if row.get("is_short") != "false":
            continue
        feature_counts_by_source[row.get("collection_source_id", "")] += 1

    filtered = [
        row
        for row in rows
        if (row.get("collection_status") or "").strip() != "resolved"
        and feature_counts_by_source.get(row.get("collection_source_id", ""), 0) > 0
    ]

    with output_path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(filtered)


if __name__ == "__main__":
    main()
