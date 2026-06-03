#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

from src.imdb.classify_shorts import classify_short_candidate
from src.criterion.collection_manifest import discover_collection_groups, load_new_criterion_rows, load_overrides
from src.imdb.generate_initial_matches import directors_match
from src.imdb.resolve_single_collection import Candidate as ImdbCandidate, stream_matches
from src.shared.utils import ensure_output_dir, parse_year, timestamp_utc, write_csv


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMDB_DIR = REPO_ROOT / "data" / "imdb"
DEFAULT_NEW_CRITERION = REPO_ROOT / "data" / "criterion" / "new-criterion.csv"
DEFAULT_OVERRIDES = REPO_ROOT / "data" / "criterion" / "collection_constituents_overrides.csv"
csv.field_size_limit(sys.maxsize)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expand collections into constituent films with IMDb ids.")
    parser.add_argument("--new-criterion", type=Path, default=DEFAULT_NEW_CRITERION)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--title-basics", type=Path, default=DEFAULT_IMDB_DIR / "title.basics.tsv")
    parser.add_argument("--title-akas", type=Path, default=DEFAULT_IMDB_DIR / "title.akas.tsv")
    parser.add_argument("--title-crew", type=Path, default=DEFAULT_IMDB_DIR / "title.crew.tsv")
    parser.add_argument("--name-basics", type=Path, default=DEFAULT_IMDB_DIR / "name.basics.tsv")
    parser.add_argument("--films-output", type=Path, default=REPO_ROOT / "data" / "output" / "collection_constituent_films.csv")
    parser.add_argument("--shorts-output", type=Path, default=REPO_ROOT / "data" / "output" / "collection_shorts_excluded.csv")
    parser.add_argument("--resolved-output", type=Path, default=REPO_ROOT / "data" / "output" / "resolved_collections.csv")
    return parser.parse_args()


def is_likely_collection(title: str, director: str, year: str) -> bool:
    lowered = title.casefold()
    if any(hint in lowered for hint in COLLECTION_HINTS):
        return True
    if not director.strip() or not year.strip():
        if "/" in title or ":" in title:
            return True
    return False


def directors_for_tconsts(tconsts: Set[str], crew_path: Path, names_path: Path) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = defaultdict(list)
    needed_names: Set[str] = set()
    if not tconsts or not crew_path.exists():
        return {}
    with crew_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["tconst"] not in tconsts:
                continue
            director_ids = row.get("directors") or ""
            if director_ids == r"\N" or not director_ids:
                continue
            ids = director_ids.split(",")
            out[row["tconst"]] = ids
            needed_names.update(ids)
    if not needed_names or not names_path.exists():
        return {tconst: [] for tconst in out}
    name_by_nconst: Dict[str, str] = {}
    with names_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["nconst"] in needed_names:
                name_by_nconst[row["nconst"]] = row["primaryName"]
    return {tconst: [name_by_nconst[nconst] for nconst in ids if nconst in name_by_nconst] for tconst, ids in out.items()}


def pick_best_candidate(
    film_title: str,
    film_director: str,
    film_year: str,
    candidates: List[ImdbCandidate],
    director_by_tconst: Dict[str, List[str]],
) -> ImdbCandidate | None:
    if not candidates:
        return None
    if film_director.strip():
        director_matched = [
            candidate
            for candidate in candidates
            if directors_match(film_director, director_by_tconst.get(candidate.imdb_id, []))
        ]
        if director_matched:
            candidates = director_matched
    year_value = parse_year(film_year)
    if year_value is not None:
        exact_year = [candidate for candidate in candidates if parse_year(candidate.start_year) == year_value]
        if exact_year:
            candidates = exact_year
    return max(candidates, key=lambda candidate: candidate.score)


def load_basics_for_tconsts(basics_path: Path, tconsts: Set[str]) -> Dict[str, dict]:
    if not tconsts or not basics_path.exists():
        return {}
    found: Dict[str, dict] = {}
    with basics_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            tconst = row["tconst"]
            if tconst in tconsts and tconst not in found:
                found[tconst] = row
                if len(found) == len(tconsts):
                    break
    return found


def main() -> None:
    args = parse_args()
    ensure_output_dir(args.films_output.parent)
    overrides = load_overrides(args.overrides)
    nc_rows = load_new_criterion_rows(args.new_criterion)
    groups = discover_collection_groups(nc_rows, args.overrides)

    all_titles = [
        (constituent.film_title or "").strip()
        for group in groups
        for constituent in group.constituents
        if (constituent.film_title or "").strip()
    ]
    grouped_matches: Dict[str, List[ImdbCandidate]] = {}
    if all_titles and args.title_basics.exists() and args.title_akas.exists():
        grouped_matches = stream_matches(args.title_basics, args.title_akas, all_titles)

    director_tconsts: Set[str] = set()
    for candidates in grouped_matches.values():
        for candidate in sorted(candidates, key=lambda item: item.score, reverse=True)[:10]:
            director_tconsts.add(candidate.imdb_id)
    for group in groups:
        for seq in range(1, len(group.constituents) + 1):
            override = overrides.get((group.collection_source_id, seq), {})
            imdb_id = (override.get("imdb_id") or "").strip()
            if imdb_id:
                director_tconsts.add(imdb_id)
    director_by_tconst = directors_for_tconsts(director_tconsts, args.title_crew, args.name_basics)

    generated_at = timestamp_utc()
    pending_rows: List[tuple] = []
    resolved_rows: List[dict] = []

    for group in groups:
        missing = 0
        short_count = 0
        for seq, constituent in enumerate(group.constituents, start=1):
            override = overrides.get((group.collection_source_id, seq), {})
            forced_imdb_id = (override.get("imdb_id") or "").strip()
            notes = (override.get("notes") or "").strip()
            title_for_match = (constituent.film_title or "").strip()
            candidates = grouped_matches.get(title_for_match, [])
            best = pick_best_candidate(
                title_for_match,
                constituent.film_director,
                constituent.film_year,
                candidates,
                director_by_tconst,
            )
            imdb_id = forced_imdb_id or (best.imdb_id if best else "")
            if not imdb_id:
                missing += 1
                pending_rows.append(("missing", group, seq, constituent, notes, None))
                continue
            pending_rows.append(("matched", group, seq, constituent, notes, imdb_id, best))

        status = "resolved" if missing == 0 else ("partial" if missing < len(group.constituents) else "needs_manual_decomposition")
        resolved_rows.append(
            {
                "collection_source_id": group.collection_source_id,
                "collection_title": group.collection_title,
                "collection_type": group.collection_type,
                "extraction_method": group.extraction_method,
                "extracted_titles_count": str(len(group.constituents)),
                "collection_status": status,
                "collection_notes": f"{missing} missing IMDb; {short_count} shorts excluded" if missing or short_count else "",
                "last_updated": generated_at,
            }
        )

    chosen_tconsts = {row[5] for row in pending_rows if row[0] == "matched" and row[5]}
    basics_map = load_basics_for_tconsts(args.title_basics, chosen_tconsts)

    film_rows: List[dict] = []
    short_rows: List[dict] = []
    for pending in pending_rows:
        kind, group, seq, constituent, notes, *rest = pending
        if kind == "missing":
            film_rows.append(
                {
                    "collection_type": group.collection_type,
                    "collection_source_id": group.collection_source_id,
                    "collection_title": group.collection_title,
                    "seq": seq,
                    "film_source_id": constituent.film_source_id,
                    "film_title": constituent.film_title,
                    "film_director": constituent.film_director,
                    "film_year": constituent.film_year,
                    "imdb_id": "",
                    "imdb_primary_title": "",
                    "imdb_original_title": "",
                    "imdb_title_type": "",
                    "imdb_start_year": "",
                    "imdb_runtime_minutes": "",
                    "imdb_genres": "",
                    "entity_type": "",
                    "is_short": "",
                    "short_signal": "",
                    "include_in_dataset": "false",
                    "notes": notes or "No IMDb match yet",
                    "generated_at": generated_at,
                }
            )
            continue

        imdb_id, best = rest
        basics_row = basics_map.get(imdb_id)
        if basics_row:
            title_type = basics_row["titleType"]
            primary = basics_row["primaryTitle"]
            original = basics_row["originalTitle"]
            start_year = basics_row["startYear"]
            runtime = basics_row["runtimeMinutes"]
            genres = basics_row["genres"]
        else:
            title_type = best.title_type if best else ""
            primary = best.primary_title if best else ""
            original = best.original_title if best else ""
            start_year = best.start_year if best else ""
            runtime = best.runtime_minutes if best else ""
            genres = best.genres if best else ""

        short_signal = classify_short_candidate(title_type, runtime, genres)
        is_short = short_signal != "feature_or_unknown"
        base_row = {
            "collection_type": group.collection_type,
            "collection_source_id": group.collection_source_id,
            "collection_title": group.collection_title,
            "seq": seq,
            "film_source_id": constituent.film_source_id,
            "film_title": constituent.film_title,
            "film_director": constituent.film_director,
            "film_year": constituent.film_year,
            "imdb_id": imdb_id,
            "imdb_primary_title": primary,
            "imdb_original_title": original,
            "imdb_title_type": title_type,
            "imdb_start_year": start_year,
            "imdb_runtime_minutes": runtime,
            "imdb_genres": genres,
            "entity_type": "short" if is_short else "movie",
            "is_short": str(is_short),
            "short_signal": short_signal,
            "include_in_dataset": "false" if is_short else "true",
            "notes": notes or (f"matched_score={best.score}" if best else ""),
            "generated_at": generated_at,
        }
        if is_short:
            short_rows.append(base_row)
        else:
            film_rows.append(base_row)

    write_csv(args.films_output, film_rows)
    write_csv(args.shorts_output, short_rows)
    write_csv(args.resolved_output, resolved_rows)


if __name__ == "__main__":
    main()
