#!/usr/bin/env python3
"""
Expand Criterion collection rows into per-film IMDb rows (rich CSV), classify shorts,
and write collection_shorts_excluded.csv + resolved_collections summary.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

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
    p = argparse.ArgumentParser(description="Expand collections into constituent films with IMDb ids.")
    p.add_argument("--new-criterion", type=Path, default=DEFAULT_NEW_CRITERION)
    p.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    p.add_argument("--title-basics", type=Path, default=DEFAULT_IMDB_DIR / "title.basics.tsv")
    p.add_argument("--title-akas", type=Path, default=DEFAULT_IMDB_DIR / "title.akas.tsv")
    p.add_argument("--title-crew", type=Path, default=DEFAULT_IMDB_DIR / "title.crew.tsv")
    p.add_argument("--name-basics", type=Path, default=DEFAULT_IMDB_DIR / "name.basics.tsv")
    p.add_argument("--films-output", type=Path, default=REPO_ROOT / "data" / "output" / "collection_constituent_films.csv")
    p.add_argument("--shorts-output", type=Path, default=REPO_ROOT / "data" / "output" / "collection_shorts_excluded.csv")
    p.add_argument("--resolved-output", type=Path, default=REPO_ROOT / "data" / "output" / "resolved_collections.csv")
    return p.parse_args()


def directors_for_tconsts(
    tconsts: Set[str],
    crew_path: Path,
    names_path: Path,
) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = defaultdict(list)
    needed_names: Set[str] = set()
    if not tconsts or not crew_path.exists():
        return {}
    with crew_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["tconst"] not in tconsts:
                continue
            d = row.get("directors") or ""
            if d == r"\N" or not d:
                continue
            ids = d.split(",")
            out[row["tconst"]] = ids
            needed_names.update(ids)
    name_by_nconst: Dict[str, str] = {}
    if not needed_names or not names_path.exists():
        return {t: [] for t in out}
    with names_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["nconst"] in needed_names:
                name_by_nconst[row["nconst"]] = row["primaryName"]
    resolved: Dict[str, List[str]] = {}
    for t, ids in out.items():
        resolved[t] = [name_by_nconst[n] for n in ids if n in name_by_nconst]
    return resolved


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
        matched = [
            c
            for c in candidates
            if directors_match(film_director, director_by_tconst.get(c.imdb_id, []))
        ]
        if matched:
            candidates = matched
    y = parse_year(film_year)
    if y is not None:
        year_fit = [c for c in candidates if parse_year(c.start_year) == y]
        if year_fit:
            candidates = year_fit
    return max(candidates, key=lambda c: c.score)


def load_basics_for_tconsts(basics_path: Path, tconsts: Set[str]) -> Dict[str, dict]:
    if not tconsts or not basics_path.exists():
        return {}
    found: Dict[str, dict] = {}
    with basics_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            t = row["tconst"]
            if t in tconsts and t not in found:
                found[t] = row
                if len(found) == len(tconsts):
                    break
    return found


def main() -> None:
    args = parse_args()
    ensure_output_dir(args.films_output.parent)
    overrides = load_overrides(args.overrides)
    nc_rows = load_new_criterion_rows(args.new_criterion)
    groups = discover_collection_groups(nc_rows, args.overrides)

    all_titles: List[str] = []
    for g in groups:
        for c in g.constituents:
            t = (c.film_title or "").strip()
            if t:
                all_titles.append(t)

    grouped_matches: Dict[str, List[ImdbCandidate]] = {}
    if all_titles and args.title_basics.exists() and args.title_akas.exists():
        grouped_matches = stream_matches(args.title_basics, args.title_akas, all_titles)

    director_tconsts: Set[str] = set()
    for cands in grouped_matches.values():
        ranked = sorted(cands, key=lambda x: x.score, reverse=True)[:10]
        for c in ranked:
            director_tconsts.add(c.imdb_id)
    for g in groups:
        for seq in range(1, len(g.constituents) + 1):
            ov = overrides.get((g.collection_source_id, seq), {})
            tid = (ov.get("imdb_id") or "").strip()
            if tid:
                director_tconsts.add(tid)
    director_by_tconst = directors_for_tconsts(director_tconsts, args.title_crew, args.name_basics)

    ts = timestamp_utc()
    pending: List[tuple] = []
    resolved_rows: List[dict] = []

    for g in groups:
        missing = 0
        for seq, c in enumerate(g.constituents, start=1):
            ov = overrides.get((g.collection_source_id, seq), {})
            imdb_id = (ov.get("imdb_id") or "").strip()
            notes = (ov.get("notes") or "").strip()
            title_for_match = (c.film_title or "").strip()
            cands = grouped_matches.get(title_for_match, [])
            best = pick_best_candidate(
                title_for_match,
                c.film_director,
                c.film_year,
                cands,
                director_by_tconst,
            )
            if not imdb_id and best:
                imdb_id = best.imdb_id
            if not imdb_id:
                missing += 1
                pending.append(
                    (
                        "missing",
                        g,
                        seq,
                        c,
                        title_for_match,
                        notes,
                        None,
                        None,
                    )
                )
                continue

            pending.append(
                (
                    "ok",
                    g,
                    seq,
                    c,
                    title_for_match,
                    notes,
                    imdb_id,
                    best,
                )
            )

        status = "resolved" if missing == 0 else ("partial" if missing < len(g.constituents) else "needs_manual_decomposition")
        resolved_rows.append(
            {
                "collection_source_id": g.collection_source_id,
                "collection_title": g.collection_title,
                "collection_type": g.collection_type,
                "extraction_method": g.extraction_method,
                "extracted_titles_count": str(len(g.constituents)),
                "collection_status": status,
                "collection_notes": f"{missing} missing IMDb" if missing else "",
                "last_updated": ts,
            }
        )

    chosen_tconsts = {t[6] for t in pending if t[0] == "ok" and t[6]}
    basics_map = load_basics_for_tconsts(args.title_basics, chosen_tconsts)

    film_rows: List[dict] = []
    short_rows: List[dict] = []

    for kind, g, seq, c, title_for_match, notes, imdb_id, best in pending:
        if kind == "missing":
            film_rows.append(
                {
                    "collection_type": g.collection_type,
                    "collection_source_id": g.collection_source_id,
                    "collection_title": g.collection_title,
                    "seq": seq,
                    "film_source_id": c.film_source_id,
                    "film_title": title_for_match,
                    "film_director": c.film_director,
                    "film_year": c.film_year,
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
                    "generated_at": ts,
                }
            )
            continue

        assert imdb_id is not None
        basics_row = basics_map.get(imdb_id)
        if basics_row:
            title_type = basics_row["titleType"]
            primary = basics_row["primaryTitle"]
            original = basics_row["originalTitle"]
            start_year = basics_row["startYear"]
            runtime = basics_row["runtimeMinutes"]
            genres = basics_row["genres"]
        elif best:
            title_type = best.title_type
            primary = best.primary_title
            original = best.original_title
            start_year = best.start_year
            runtime = best.runtime_minutes
            genres = best.genres
        else:
            title_type = primary = original = start_year = runtime = genres = ""

        ov = overrides.get((g.collection_source_id, seq), {})
        short_override = (ov.get("is_short") or "").strip().lower()
        if short_override in {"true", "1", "yes"}:
            is_short = True
            short_signal = "override_short"
        elif short_override in {"false", "0", "no"}:
            is_short = False
            short_signal = "override_feature"
        else:
            short_signal = classify_short_candidate(title_type, runtime, genres)
            is_short = short_signal != "feature_or_unknown"

        include = not is_short
        extra = []
        if not c.from_catalog:
            extra.append("virtual_constituent")
        if notes:
            extra.append(notes)
        if best and not (ov.get("imdb_id") or "").strip():
            extra.append(f"matched_score={best.score}")
        row_notes = "; ".join(extra) if extra else ("catalog" if c.from_catalog else "expanded")

        film_rows.append(
            {
                "collection_type": g.collection_type,
                "collection_source_id": g.collection_source_id,
                "collection_title": g.collection_title,
                "seq": seq,
                "film_source_id": c.film_source_id,
                "film_title": title_for_match,
                "film_director": c.film_director,
                "film_year": c.film_year,
                "imdb_id": imdb_id,
                "imdb_primary_title": primary,
                "imdb_original_title": original,
                "imdb_title_type": title_type,
                "imdb_start_year": start_year,
                "imdb_runtime_minutes": runtime,
                "imdb_genres": genres,
                "entity_type": title_type or "unknown",
                "is_short": str(is_short).lower(),
                "short_signal": short_signal if is_short else "feature_or_unknown",
                "include_in_dataset": str(include).lower(),
                "notes": row_notes,
                "generated_at": ts,
            }
        )
        if is_short:
            short_rows.append(
                {
                    "collection_source_id": g.collection_source_id,
                    "collection_title": g.collection_title,
                    "seq": seq,
                    "film_title": title_for_match,
                    "film_director": c.film_director,
                    "film_year": c.film_year,
                    "imdb_id": imdb_id,
                    "imdb_primary_title": primary,
                    "short_signal": short_signal,
                    "rationale": "Collection constituent classified as short (track only; excluded from final dataset).",
                    "generated_at": ts,
                }
            )

    write_csv(args.films_output, film_rows)
    write_csv(args.shorts_output, short_rows)
    write_csv(args.resolved_output, resolved_rows)
    print(f"Wrote {len(film_rows)} constituent rows → {args.films_output}")
    print(f"Wrote {len(short_rows)} collection shorts → {args.shorts_output}")
    print(f"Wrote {len(resolved_rows)} collection summaries → {args.resolved_output}")


if __name__ == "__main__":
    main()
