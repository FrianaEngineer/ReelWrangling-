#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from src.shared.normalize_titles import normalize_title
from src.shared.utils import ensure_output_dir, parse_year, timestamp_utc, write_csv

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COLLECTIONS = REPO_ROOT / "data" / "output" / "resolved_collections.csv"
DEFAULT_CONSTITUENTS = REPO_ROOT / "data" / "output" / "collection_constituent_films.csv"
DEFAULT_EXISTING_MOVIES = REPO_ROOT / "data" / "output" / "final_clean_films.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "output" / "collection_unpack_dry_run.csv"
DEFAULT_SUMMARY = REPO_ROOT / "data" / "output" / "collection_unpack_summary.csv"

TV_TYPES = {"tvseries", "tvepisode", "tvminiseries", "tvmovie", "tvspecial"}
VIDEO_TYPES = {"short", "video", "tvshort", "videogame"}
DOC_CATEGORY = "TV / Docs / Shorts / Video"
MOVIE_CATEGORY = "Movies"
PROBLEM_CATEGORY = "Untracked / Problem"
NOT_ANALYZED_CATEGORY = "Data Not Analyzed"
UNKNOWN_CATEGORY = "Unknown"

GENERIC_TITLE_NORMALIZED = {
    "an anthology",
    "anthology",
    "volume one",
    "volume two",
    "volumes one and two",
    "volume 1",
    "volume 2",
    "disc one",
    "disc two",
    "disc 1",
    "disc 2",
    "part one",
    "part two",
    "program one",
    "program two",
}

TRUSTED_PARTIAL_COLLECTIONS = {
    "A Story of Floating Weeds / Floating Weeds: Two Films by Yasujiro Ozu": {
        normalize_title("A Story of Floating Weeds"),
        normalize_title("Floating Weeds"),
    },
    "Freaks / The Unknown / The Mystic: Tod Browning’s Sideshow Shockers": {
        normalize_title("Freaks"),
        normalize_title("The Unknown"),
        normalize_title("The Mystic"),
    },
    "Yojimbo / Sanjuro: Two Samurai Films by Akira Kurosawa": {
        normalize_title("Yojimbo"),
        normalize_title("Sanjuro"),
    },
    "The Complete Lady Snowblood": {
        normalize_title("Lady Snowblood"),
        normalize_title("Lady Snowblood: Love Song of Vengeance"),
    },
    "Melvin Van Peebles: Essential Films": {
        normalize_title("The Story of a Three Day Pass"),
        normalize_title("Watermelon Man"),
        normalize_title("Sweet Sweetback’s Baadasssss Song"),
        normalize_title("Don’t Play Us Cheap"),
    },
    "Eclipse Series 2: The Documentaries of Louis Malle": {
        normalize_title("Humain, trop humain"),
        normalize_title("Place de la République"),
        normalize_title("Calcutta"),
    },
    "Eclipse Series 26: Silent Naruse": {
        normalize_title("No Blood Relation"),
        normalize_title("Apart from You"),
        normalize_title("Every-Night Dreams"),
        normalize_title("Street Without End"),
    },
    "Eclipse Series 43: Agnès Varda in California": {
        normalize_title("Lions Love (. . . and Lies)"),
        normalize_title("Mur Murs"),
        normalize_title("Documenteur"),
    },
    "Eclipse Series 46: Ingrid Bergman’s Swedish Years": {
        normalize_title("The Count of the Old Town"),
        normalize_title("Walpurgis Night"),
        normalize_title("Intermezzo"),
        normalize_title("Dollar"),
        normalize_title("A Woman’s Face"),
        normalize_title("June Night"),
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run collection unpacking agent for Criterion + IMDb classification."
    )
    parser.add_argument("--collections", default=str(DEFAULT_COLLECTIONS))
    parser.add_argument("--constituents", default=str(DEFAULT_CONSTITUENTS))
    parser.add_argument("--existing-movies", default=str(DEFAULT_EXISTING_MOVIES))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument(
        "--docs-as-movies",
        action="store_true",
        help="Treat feature-length documentaries as Movies instead of TV / Docs / Shorts / Video.",
    )
    return parser.parse_args()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def to_int(value: str) -> int | None:
    value = (value or "").strip()
    if not value or value == r"\N":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def to_bool(value: str) -> bool | None:
    lowered = (value or "").strip().casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def preflight_collection_guard(
    collection_title: str,
    collection_status: str,
    normalized_title: str,
) -> tuple[str, str, str, bool] | None:
    if normalized_title in GENERIC_TITLE_NORMALIZED:
        return (
            PROBLEM_CATEGORY,
            "low",
            "The extracted title is a generic label such as a volume or anthology marker, not a stable film title.",
            True,
        )

    if collection_status == "partial":
        trusted_titles = TRUSTED_PARTIAL_COLLECTIONS.get(collection_title)
        if trusted_titles is None:
            return (
                PROBLEM_CATEGORY,
                "low",
                "This collection is only partially resolved and does not yet have a trusted decomposition map, so its extracted children stay in manual review.",
                True,
            )
        if normalized_title not in trusted_titles:
            return (
                PROBLEM_CATEGORY,
                "low",
                "This extracted title is not part of the trusted decomposition for this partially resolved collection.",
                True,
            )

    return None


def classify_row(
    row: dict[str, str],
    *,
    docs_as_movies: bool,
) -> tuple[str, str, str, bool]:
    imdb_id = (row.get("imdb_id") or "").strip()
    title_type = ((row.get("imdb_title_type") or row.get("entity_type") or "").strip()).casefold()
    genres = {part.strip().casefold() for part in (row.get("imdb_genres") or "").split(",") if part.strip()}
    runtime = to_int(row.get("imdb_runtime_minutes") or "")
    criterion_year = parse_year(row.get("film_year") or "")
    imdb_year = parse_year(row.get("imdb_start_year") or "")
    notes = (row.get("notes") or "").strip()
    include_in_dataset = to_bool(row.get("include_in_dataset") or "")
    is_short = to_bool(row.get("is_short") or "")

    if not imdb_id:
        return (
            PROBLEM_CATEGORY,
            "low",
            "No reliable IMDb match is attached to this extracted collection item.",
            True,
        )

    if not title_type and runtime is None and imdb_year is None and criterion_year is None:
        return (
            UNKNOWN_CATEGORY,
            "low",
            "IMDb id exists but type, runtime, and year metadata are all missing.",
            True,
        )

    if title_type in TV_TYPES:
        return (
            DOC_CATEGORY,
            "high",
            f"IMDb titleType is {title_type}, so this is not counted as a feature film.",
            False,
        )

    if title_type in VIDEO_TYPES:
        return (
            DOC_CATEGORY,
            "high",
            f"IMDb titleType is {title_type}, so this is classified as non-feature video or short-form media.",
            False,
        )

    if "documentary" in genres and not docs_as_movies:
        return (
            DOC_CATEGORY,
            "high" if runtime is not None else "medium",
            "IMDb genres include Documentary and the current project rule excludes documentaries from Movies.",
            runtime is None,
        )

    if is_short is True:
        return (
            DOC_CATEGORY,
            "high",
            "Existing pipeline already flagged this constituent as a short-form item.",
            False,
        )

    if runtime is not None and runtime < 40:
        return (
            DOC_CATEGORY,
            "high",
            f"Runtime is {runtime} minutes, which is below the 40-minute feature threshold.",
            False,
        )

    if title_type == "movie" and runtime is not None and runtime >= 40:
        if criterion_year is not None and imdb_year is not None:
            year_diff = abs(criterion_year - imdb_year)
            if year_diff > 1:
                return (
                    MOVIE_CATEGORY,
                    "medium",
                    f"IMDb titleType is movie and runtime is {runtime} minutes, but Criterion year {criterion_year} and IMDb year {imdb_year} differ by {year_diff}.",
                    True,
                )
            if year_diff == 1:
                return (
                    MOVIE_CATEGORY,
                    "medium",
                    f"IMDb titleType is movie and runtime is {runtime} minutes; Criterion and IMDb years differ by 1 year.",
                    False,
                )
        return (
            MOVIE_CATEGORY,
            "high",
            f"IMDb titleType is movie and runtime is {runtime} minutes, so this qualifies as a feature-length film.",
            False,
        )

    if title_type == "movie" and runtime is None:
        return (
            UNKNOWN_CATEGORY,
            "low",
            "IMDb titleType is movie, but runtime is missing so the feature-length threshold cannot be verified.",
            True,
        )

    if include_in_dataset is False and not notes:
        return (
            DOC_CATEGORY,
            "medium",
            "Existing pipeline excluded this constituent from the dataset, but the current row lacks enough metadata to explain the exact subtype.",
            True,
        )

    return (
        UNKNOWN_CATEGORY,
        "low",
        "Available metadata does not safely resolve this item into feature-film or non-feature categories.",
        True,
    )


def build_existing_movie_index(rows: Iterable[dict[str, str]]) -> tuple[set[str], set[tuple[str, str]]]:
    imdb_ids: set[str] = set()
    title_year: set[tuple[str, str]] = set()
    for row in rows:
        imdb_id = (row.get("imdb_id") or "").strip()
        if imdb_id:
            imdb_ids.add(imdb_id)
        title = normalize_title(row.get("criterion_title_original") or row.get("imdb_primary_title") or "")
        year = (row.get("criterion_year") or row.get("imdb_start_year") or "").strip()
        if title and year:
            title_year.add((title, year))
    return imdb_ids, title_year


def main() -> None:
    args = parse_args()
    collections_path = Path(args.collections)
    constituents_path = Path(args.constituents)
    existing_movies_path = Path(args.existing_movies)
    output_path = Path(args.output)
    summary_path = Path(args.summary)

    collections = load_csv(collections_path)
    constituents = load_csv(constituents_path)
    existing_movies = load_csv(existing_movies_path)
    existing_imdb_ids, existing_title_year = build_existing_movie_index(existing_movies)

    collection_children: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in constituents:
        collection_children[(row.get("collection_source_id") or "").strip()].append(row)

    generated_at = timestamp_utc()
    output_rows: list[dict[str, str]] = []

    for collection in collections:
        source_collection_id = (collection.get("collection_source_id") or "").strip()
        source_collection_title = (collection.get("collection_title") or "").strip()
        children = collection_children.get(source_collection_id, [])
        collection_status = (collection.get("collection_status") or "").strip()
        extraction_method = (collection.get("extraction_method") or "").strip()
        collection_notes = (collection.get("collection_notes") or "").strip()

        if not children:
            output_rows.append(
                {
                    "source_collection_id": source_collection_id,
                    "source_collection_title": source_collection_title,
                    "item_title": "",
                    "normalized_title": "",
                    "criterion_url": "",
                    "imdb_id": "",
                    "imdb_title": "",
                    "criterion_year": "",
                    "imdb_year": "",
                    "runtime_minutes": "",
                    "title_type": "",
                    "final_category": NOT_ANALYZED_CATEGORY,
                    "confidence": "low",
                    "reason": (
                        "This collection has no extracted child items in the current constituent file, "
                        f"so it still needs decomposition. collection_status={collection_status or 'missing'}; "
                        f"extraction_method={extraction_method or 'missing'}."
                    ),
                    "needs_manual_review": "true",
                    "processing_status": "not_analyzed",
                    "years_match_status": "",
                    "already_tracked_movie": "",
                    "duplicate_key": "",
                    "collection_status": collection_status,
                    "collection_notes": collection_notes,
                    "generated_at": generated_at,
                }
            )
            continue

        for row in sorted(children, key=lambda item: to_int(item.get("seq") or "") or 0):
            item_title = (row.get("film_title") or "").strip()
            normalized_title = normalize_title(item_title)
            guard_result = preflight_collection_guard(
                source_collection_title,
                collection_status,
                normalized_title,
            )
            if guard_result is not None:
                final_category, confidence, reason, needs_manual_review = guard_result
            else:
                final_category, confidence, reason, needs_manual_review = classify_row(
                    row,
                    docs_as_movies=args.docs_as_movies,
                )
            criterion_year = (row.get("film_year") or "").strip()
            imdb_year = (row.get("imdb_start_year") or "").strip()
            imdb_id = (row.get("imdb_id") or "").strip()
            title_type = (row.get("imdb_title_type") or row.get("entity_type") or "").strip()
            runtime = (row.get("imdb_runtime_minutes") or "").strip()
            years_match_status = ""
            if criterion_year and imdb_year:
                try:
                    diff = abs(int(criterion_year) - int(imdb_year))
                    years_match_status = "exact" if diff == 0 else "within_1" if diff == 1 else "off"
                except ValueError:
                    years_match_status = ""

            duplicate_key = ""
            already_tracked_movie = ""
            if imdb_id:
                already_tracked_movie = "true" if imdb_id in existing_imdb_ids else "false"
                duplicate_key = imdb_id
            elif normalized_title and criterion_year:
                already_tracked_movie = (
                    "true" if (normalized_title, criterion_year) in existing_title_year else "false"
                )
                duplicate_key = f"{normalized_title}|{criterion_year}"

            output_rows.append(
                {
                    "source_collection_id": source_collection_id,
                    "source_collection_title": source_collection_title,
                    "item_title": item_title,
                    "normalized_title": normalized_title,
                    "criterion_url": "",
                    "imdb_id": imdb_id,
                    "imdb_title": (row.get("imdb_primary_title") or "").strip(),
                    "criterion_year": criterion_year,
                    "imdb_year": imdb_year,
                    "runtime_minutes": runtime,
                    "title_type": title_type,
                    "final_category": final_category,
                    "confidence": confidence,
                    "reason": reason,
                    "needs_manual_review": "true" if needs_manual_review else "false",
                    "processing_status": "analyzed",
                    "years_match_status": years_match_status,
                    "already_tracked_movie": already_tracked_movie,
                    "duplicate_key": duplicate_key,
                    "collection_status": collection_status,
                    "collection_notes": collection_notes,
                    "generated_at": generated_at,
                }
            )

    ensure_output_dir(output_path.parent)
    write_csv(output_path, output_rows)

    category_counts = Counter(row["final_category"] for row in output_rows)
    confidence_counts = Counter(row["confidence"] for row in output_rows)
    review_counts = Counter(row["needs_manual_review"] for row in output_rows)
    processing_counts = Counter(row["processing_status"] for row in output_rows)

    summary_rows = [
        {"metric": "collections_total", "value": str(len(collections))},
        {"metric": "constituent_rows_total", "value": str(len(constituents))},
        {"metric": "output_rows_total", "value": str(len(output_rows))},
    ]
    summary_rows.extend(
        {"metric": f"final_category::{key}", "value": str(value)}
        for key, value in sorted(category_counts.items())
    )
    summary_rows.extend(
        {"metric": f"confidence::{key}", "value": str(value)}
        for key, value in sorted(confidence_counts.items())
    )
    summary_rows.extend(
        {"metric": f"needs_manual_review::{key}", "value": str(value)}
        for key, value in sorted(review_counts.items())
    )
    summary_rows.extend(
        {"metric": f"processing_status::{key}", "value": str(value)}
        for key, value in sorted(processing_counts.items())
    )
    write_csv(summary_path, summary_rows)


if __name__ == "__main__":
    main()
