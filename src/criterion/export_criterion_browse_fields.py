#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "data" / "criterion" / "criterion.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "criterion" / "criterion_browse_fields.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Criterion browse fields as a cleaned CSV."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def clean_country(value: str) -> str:
    return (value or "").strip().rstrip(",").strip()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        rows = []
        for row in reader:
            rows.append(
                {
                    "spine_number": (row.get("spine") or "").strip(),
                    "title": (row.get("title") or "").strip(),
                    "country": clean_country(row.get("country", "")),
                    "director": (row.get("director") or "").strip(),
                    "year": (row.get("year") or "").strip(),
                }
            )

    with output_path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(
            outfile,
            fieldnames=["spine_number", "title", "country", "director", "year"],
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
