#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from src.shared.normalize_titles import normalize_title

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_FOUND = REPO_ROOT / "data" / "output" / "unmatchedCollectionFullLengthMovieIds.csv"
DEFAULT_OUTPUT_MISSING = REPO_ROOT / "data" / "output" / "unmatchedCollectionStillUnresolved.txt"


TRUSTED_COLLECTIONS = {
    "A Story of Floating Weeds / Floating Weeds: Two Films by Yasujiro Ozu": [
        "A Story of Floating Weeds",
        "Floating Weeds",
    ],
    "Freaks / The Unknown / The Mystic: Tod Browning’s Sideshow Shockers": [
        "Freaks",
        "The Unknown",
        "The Mystic",
    ],
    "Yojimbo / Sanjuro: Two Samurai Films by Akira Kurosawa": [
        "Yojimbo",
        "Sanjuro",
    ],
    "The Complete Lady Snowblood": [
        "Lady Snowblood",
        "Lady Snowblood: Love Song of Vengeance",
    ],
    "Melvin Van Peebles: Essential Films": [
        "The Story of a Three Day Pass",
        "Watermelon Man",
        "Sweet Sweetback’s Baadasssss Song",
        "Don’t Play Us Cheap",
    ],
    "Eclipse Series 2: The Documentaries of Louis Malle": [
        "Humain, trop humain",
        "Place de la République",
        "Calcutta",
    ],
    "Eclipse Series 26: Silent Naruse": [
        "No Blood Relation",
        "Apart from You",
        "Every-Night Dreams",
        "Street Without End",
    ],
    "Eclipse Series 43: Agnès Varda in California": [
        "Lions Love (. . . and Lies)",
        "Mur Murs",
        "Documenteur",
    ],
    "Eclipse Series 46: Ingrid Bergman’s Swedish Years": [
        "The Count of the Old Town",
        "Walpurgis Night",
        "Intermezzo",
        "Dollar",
        "A Woman’s Face",
        "June Night",
    ],
}

# Manual fixes where local logs contain a bad IMDb id or no direct reusable row.
TITLE_OVERRIDES = {
    normalize_title("Lady Snowblood: Love Song of Vengeance"): {
        "imdb_id": "tt0072157",
        "imdb_title": "Lady Snowblood 2: Love Song of Vengeance",
        "imdb_start_year": "1974",
        "evidence": "title.basics exact title search",
    }
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export confidently recoverable full-length movie IMDb IDs from unmatched collections."
    )
    parser.add_argument("--output-found", default=str(DEFAULT_OUTPUT_FOUND))
    parser.add_argument("--output-missing", default=str(DEFAULT_OUTPUT_MISSING))
    return parser.parse_args()


def build_title_index() -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    sources = [
        (str(REPO_ROOT / "data" / "output" / "final_clean_films.csv"), "criterion_title_original"),
        (str(REPO_ROOT / "data" / "output" / "initial_matches.csv"), "criterion_title_original"),
        (str(REPO_ROOT / "data" / "output" / "manual_resolution_log.csv"), "criterion_title_original"),
        (str(REPO_ROOT / "data" / "output" / "collection_constituent_films.csv"), "film_title"),
    ]

    for path_str, title_key in sources:
        path = Path(path_str)
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                raw_title = (row.get(title_key) or "").strip()
                if not raw_title:
                    continue
                key = normalize_title(raw_title)
                if not key:
                    continue

                imdb_id = (row.get("imdb_id") or "").strip()
                if not imdb_id:
                    continue

                imdb_title = (
                    row.get("imdb_primary_title")
                    or row.get("imdb_title")
                    or row.get("imdb_title_original")
                    or raw_title
                )
                imdb_start_year = row.get("imdb_start_year") or row.get("criterion_year") or ""
                title_type = row.get("imdb_title_type") or row.get("entity_type") or ""

                if key not in index:
                    index[key] = {
                        "imdb_id": imdb_id,
                        "imdb_title": imdb_title.strip(),
                        "imdb_start_year": str(imdb_start_year).strip(),
                        "title_type": title_type.strip(),
                        "evidence": path.name,
                    }
    index.update(TITLE_OVERRIDES)
    return index


def main() -> None:
    args = parse_args()
    title_index = build_title_index()
    found_rows: list[dict[str, str]] = []
    unresolved_collections: list[str] = []

    for collection_title, film_titles in TRUSTED_COLLECTIONS.items():
        missing_titles: list[str] = []
        for film_title in film_titles:
            key = normalize_title(film_title)
            match = title_index.get(key)
            if not match:
                missing_titles.append(film_title)
                continue
            found_rows.append(
                {
                    "collection_title": collection_title,
                    "film_title": film_title,
                    "imdb_id": match.get("imdb_id", ""),
                    "imdb_title": match.get("imdb_title", ""),
                    "imdb_start_year": match.get("imdb_start_year", ""),
                    "evidence": match.get("evidence", ""),
                }
            )
        if missing_titles:
            unresolved_collections.append(
                f"- {collection_title}: missing title ids for {', '.join(missing_titles)}"
            )

    missing_lines = [
        "Unmatched Collections Still Not Reliably Decomposed To Full-Length Movie IMDb IDs",
        "Generated: 2026-05-16",
        "",
        "Excluded because they are short-film/anthology releases rather than full-length movie collections:",
        "- W. C. Fields—Six Short Films",
        "- By Brakhage: An Anthology, Volume One",
        "- By Brakhage: An Anthology, Volume Two",
        "- By Brakhage: An Anthology, Volumes One and Two",
        "",
        "Still unresolved from local evidence:",
        "- Essential Art House: 50 Years of Janus Films",
        "- Eclipse Series 47: Abbas Kiarostami—Early Shorts and Features",
    ]
    missing_lines.extend(unresolved_collections)

    output_found = Path(args.output_found)
    with output_found.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "collection_title",
                "film_title",
                "imdb_id",
                "imdb_title",
                "imdb_start_year",
                "evidence",
            ],
        )
        writer.writeheader()
        writer.writerows(found_rows)

    output_missing = Path(args.output_missing)
    output_missing.write_text("\n".join(missing_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
