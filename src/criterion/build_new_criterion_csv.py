#!/usr/bin/env python3

from __future__ import annotations

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_CSV = REPO_ROOT / "data" / "criterion" / "criterion.csv"
OUTPUT_CSV = REPO_ROOT / "data" / "criterion" / "new-criterion.csv"

MISSING_ROWS = [
    {"spine": "1306", "title": "Point Blank", "director": "John Boorman", "country": "United States", "year": "1967"},
    {"spine": "1307", "title": "John Singleton’s Hood Trilogy", "director": "", "country": "", "year": ""},
    {"spine": "1308", "title": "Body Heat", "director": "Lawrence Kasdan", "country": "United States", "year": "1981"},
    {"spine": "1309", "title": "The Delta", "director": "Ira Sachs", "country": "United States", "year": "1996"},
    {"spine": "1310", "title": "Fresh Kill", "director": "Shu Lea Cheang", "country": "United Kingdom, United States", "year": "1994"},
    {"spine": "1311", "title": "Sentimental Value", "director": "Joachim Trier", "country": "Norway", "year": "2025"},
    {"spine": "1312", "title": "Lenny", "director": "Bob Fosse", "country": "United States", "year": "1974"},
    {"spine": "1313", "title": "West Indies: The Fugitive Slaves of Liberty", "director": "Med Hondo", "country": "France", "year": "1979"},
    {"spine": "1314", "title": "High Art", "director": "Lisa Cholodenko", "country": "United States", "year": "1998"},
    {"spine": "1315", "title": "Hairspray", "director": "John Waters", "country": "United States", "year": "1988"},
    {"spine": "1316", "title": "Desperate Living", "director": "John Waters", "country": "United States", "year": "1977"},
    {"spine": "1317", "title": "It Was Just an Accident", "director": "Jafar Panahi", "country": "Iran", "year": "2025"},
    {"spine": "", "title": "Peter Hujar’s Day", "director": "Ira Sachs", "country": "United States", "year": "2025"},
    {"spine": "", "title": "Resurrection", "director": "Bi Gan", "country": "China, France", "year": "2025"},
    {"spine": "", "title": "Boyz n the Hood", "director": "John Singleton", "country": "United States", "year": "1991"},
    {"spine": "", "title": "Poetic Justice", "director": "John Singleton", "country": "United States", "year": "1993"},
    {"spine": "", "title": "Baby Boy", "director": "John Singleton", "country": "United States", "year": "2001"},
    {"spine": "", "title": "Eclipse Series 48: Kinuyo Tanaka Directs", "director": "", "country": "", "year": ""},
    {"spine": "", "title": "Love Letter", "director": "Kinuyo Tanaka", "country": "Japan", "year": "1953"},
    {"spine": "", "title": "The Moon Has Risen", "director": "Kinuyo Tanaka", "country": "Japan", "year": "1955"},
    {"spine": "", "title": "Forever a Woman", "director": "Kinuyo Tanaka", "country": "Japan", "year": "1955"},
    {"spine": "", "title": "The Wandering Princess", "director": "Kinuyo Tanaka", "country": "Japan", "year": "1960"},
    {"spine": "", "title": "Girls of the Night", "director": "Kinuyo Tanaka", "country": "Japan", "year": "1961"},
    {"spine": "", "title": "Love Under the Crucifix", "director": "Kinuyo Tanaka", "country": "Japan", "year": "1962"},
    {"spine": "", "title": "Magellan", "director": "Lav Diaz", "country": "Philippines", "year": "2025"},
]


def clean_country(value: str) -> str:
    return (value or "").strip().rstrip(",").strip()


def clean_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "spine": (row.get("spine") or "").strip(),
        "title": (row.get("title") or "").strip(),
        "director": (row.get("director") or "").strip(),
        "country": clean_country(row.get("country", "")),
        "year": (row.get("year") or "").strip(),
    }


def main() -> None:
    with SOURCE_CSV.open("r", encoding="utf-8-sig", newline="") as infile:
        base_rows = [clean_row(row) for row in csv.DictReader(infile)]

    existing_titles = {row["title"] for row in base_rows}
    additions = [row for row in MISSING_ROWS if row["title"] not in existing_titles]

    numeric_rows = [row for row in base_rows if row["spine"].isdigit()]
    blank_rows = [row for row in base_rows if not row["spine"].isdigit()]
    new_numeric_rows = [row for row in additions if row["spine"].isdigit()]
    new_blank_rows = [row for row in additions if not row["spine"].isdigit()]

    numeric_rows.extend(new_numeric_rows)
    numeric_rows.sort(key=lambda row: int(row["spine"]))
    blank_rows.extend(new_blank_rows)

    all_rows = numeric_rows + blank_rows

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=["spine", "title", "director", "country", "year"])
        writer.writeheader()
        writer.writerows(all_rows)


if __name__ == "__main__":
    main()
