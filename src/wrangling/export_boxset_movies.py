#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "data" / "output" / "collection_constituent_films.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "output" / "boxSets.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export full-length movie constituents from Criterion box sets/collections."
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

    filtered_rows = []
    for row in rows:
        if row.get("include_in_dataset") != "true":
            continue
        if row.get("imdb_title_type") != "movie":
            continue
        if row.get("is_short") != "false":
            continue
        filtered_rows.append(
            {
                "collection_type": row.get("collection_type", ""),
                "collection_source_id": row.get("collection_source_id", ""),
                "collection_title": row.get("collection_title", ""),
                "seq": row.get("seq", ""),
                "film_source_id": row.get("film_source_id", ""),
                "film_title": row.get("film_title", ""),
                "film_director": row.get("film_director", ""),
                "film_year": row.get("film_year", ""),
                "imdb_id": row.get("imdb_id", ""),
                "imdb_primary_title": row.get("imdb_primary_title", ""),
                "imdb_original_title": row.get("imdb_original_title", ""),
                "imdb_start_year": row.get("imdb_start_year", ""),
                "imdb_runtime_minutes": row.get("imdb_runtime_minutes", ""),
                "imdb_genres": row.get("imdb_genres", ""),
                "notes": row.get("notes", ""),
            }
        )

    with output_path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(
            outfile,
            fieldnames=[
                "collection_type",
                "collection_source_id",
                "collection_title",
                "seq",
                "film_source_id",
                "film_title",
                "film_director",
                "film_year",
                "imdb_id",
                "imdb_primary_title",
                "imdb_original_title",
                "imdb_start_year",
                "imdb_runtime_minutes",
                "imdb_genres",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(filtered_rows)


if __name__ == "__main__":
    main()
