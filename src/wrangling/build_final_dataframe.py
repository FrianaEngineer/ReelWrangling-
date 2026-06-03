#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from src.imdb.classify_shorts import classify_short_candidate
from src.wrangling.criterion_dispositions import build_criterion_dispositions
from src.shared.utils import ensure_output_dir, timestamp_utc, write_csv


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TITLE_BASICS = REPO_ROOT / "data" / "imdb" / "title.basics.tsv"


def _is_rich_collection_row(row: dict) -> bool:
    return bool(row.get("collection_source_id")) and ("film_title" in row or "include_in_dataset" in row)


def _normalize_collection_constituent_to_final(row: dict) -> dict:
    collection_id = row.get("collection_source_id", "")
    seq = row.get("seq", "")
    film_source_id = (row.get("film_source_id") or "").strip()
    source_id = film_source_id if film_source_id else f"coll_{collection_id}_{seq}"
    return {
        "criterion_row_id": f"collection_constituent_{collection_id}_{seq}",
        "criterion_source_id": source_id,
        "criterion_title_original": row.get("film_title", ""),
        "criterion_title_normalized": "",
        "criterion_director_original": row.get("film_director", ""),
        "criterion_year": row.get("film_year", ""),
        "imdb_id": row.get("imdb_id", ""),
        "imdb_primary_title": row.get("imdb_primary_title", ""),
        "imdb_original_title": row.get("imdb_original_title", ""),
        "imdb_title_type": row.get("imdb_title_type", ""),
        "imdb_start_year": row.get("imdb_start_year", ""),
        "imdb_runtime_minutes": row.get("imdb_runtime_minutes", ""),
        "imdb_genres": row.get("imdb_genres", ""),
        "imdb_directors": "",
        "matched_via": "expanded_collection",
        "score": "",
        "year_difference": "",
        "short_signal": "feature_or_unknown",
        "decision_bucket": "expanded_collection",
        "generated_at": row.get("generated_at", ""),
    }


def _dedup_key(row: dict) -> Tuple[str, str, str]:
    imdb_id = (row.get("imdb_id") or row.get("candidate_imdb_id") or "").strip()
    criterion_row_id = row.get("criterion_row_id", "")
    if row.get("matched_via") == "expanded_collection":
        return ("expanded", criterion_row_id, imdb_id)
    return ("direct", criterion_row_id, imdb_id)


def _load_title_basics_subset(basics_path: Path, tconsts: Set[str]) -> Dict[str, dict]:
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


def _merge_basics_into_row(row: dict, basics_row: Optional[dict]) -> dict:
    if not basics_row:
        return dict(row)
    out = dict(row)
    if not (out.get("imdb_title_type") or "").strip():
        out["imdb_title_type"] = basics_row.get("titleType", "")
    if not (out.get("imdb_primary_title") or "").strip():
        out["imdb_primary_title"] = basics_row.get("primaryTitle", "")
    if not (out.get("imdb_original_title") or "").strip():
        out["imdb_original_title"] = basics_row.get("originalTitle", "")
    if not (out.get("imdb_start_year") or "").strip():
        out["imdb_start_year"] = basics_row.get("startYear", "")
    if not (out.get("imdb_runtime_minutes") or "").strip():
        out["imdb_runtime_minutes"] = basics_row.get("runtimeMinutes", "")
    if not (out.get("imdb_genres") or "").strip():
        out["imdb_genres"] = basics_row.get("genres", "")
    return out


def _postprocess_final_clean_rows(rows: List[dict], basics_path: Path, excluded_shorts: List[dict]) -> List[dict]:
    tconsts = {(row.get("imdb_id") or "").strip() for row in rows if (row.get("imdb_id") or "").strip().startswith("tt")}
    basics_map = _load_title_basics_subset(basics_path, tconsts) if basics_path.exists() else {}
    kept: List[dict] = []
    for row in rows:
        imdb_id = (row.get("imdb_id") or "").strip()
        if not imdb_id.startswith("tt"):
            excluded_shorts.append(
                {
                    "criterion_row_id": row.get("criterion_row_id", ""),
                    "criterion_source_id": row.get("criterion_source_id", ""),
                    "criterion_title_original": row.get("criterion_title_original", ""),
                    "criterion_year": row.get("criterion_year", ""),
                    "candidate_imdb_id": imdb_id,
                    "candidate_imdb_title": row.get("imdb_primary_title", ""),
                    "rationale": "final_deliverable_excluded: missing_or_invalid_imdb_id",
                    "review_status": "auto_resolved",
                }
            )
            continue
        merged = _merge_basics_into_row(row, basics_map.get(imdb_id))
        short_signal = classify_short_candidate(
            merged.get("imdb_title_type", ""),
            merged.get("imdb_runtime_minutes", ""),
            merged.get("imdb_genres", ""),
        )
        if short_signal != "feature_or_unknown":
            excluded_shorts.append(
                {
                    "criterion_row_id": merged.get("criterion_row_id", ""),
                    "criterion_source_id": merged.get("criterion_source_id", ""),
                    "criterion_title_original": merged.get("criterion_title_original", ""),
                    "criterion_year": merged.get("criterion_year", ""),
                    "candidate_imdb_id": imdb_id,
                    "candidate_imdb_title": merged.get("imdb_primary_title", ""),
                    "rationale": f"final_deliverable_excluded_short ({short_signal})",
                    "review_status": "auto_resolved",
                }
            )
            continue
        merged["short_signal"] = "feature_or_unknown"
        kept.append(merged)
    return kept


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the final clean film-level dataframe and the four-bucket dispositions file.")
    parser.add_argument("--criterion", default=str(REPO_ROOT / "data" / "criterion" / "new-criterion.csv"))
    parser.add_argument("--new-criterion", default=str(REPO_ROOT / "data" / "criterion" / "new-criterion.csv"))
    parser.add_argument("--overrides", default=str(REPO_ROOT / "data" / "criterion" / "collection_constituents_overrides.csv"))
    parser.add_argument("--initial-matches", default=str(REPO_ROOT / "data" / "output" / "initial_matches.csv"))
    parser.add_argument("--excluded-shorts-seed", default=str(REPO_ROOT / "data" / "output" / "excluded_shorts_seed.csv"))
    parser.add_argument("--manual-resolution-log", default=str(REPO_ROOT / "data" / "output" / "manual_resolution_log.csv"))
    parser.add_argument("--collection-films", default=str(REPO_ROOT / "data" / "output" / "collection_constituent_films.csv"))
    parser.add_argument("--final-output", default=str(REPO_ROOT / "data" / "output" / "final_clean_films.csv"))
    parser.add_argument("--excluded-shorts-output", default=str(REPO_ROOT / "data" / "output" / "excluded_shorts.csv"))
    parser.add_argument("--rare-edge-cases-output", default=str(REPO_ROOT / "data" / "output" / "rare_edge_cases.csv"))
    parser.add_argument("--criterion-dispositions-output", default=str(REPO_ROOT / "data" / "output" / "criterion_dispositions.csv"))
    parser.add_argument("--resolved-collections", default=str(REPO_ROOT / "data" / "output" / "resolved_collections.csv"))
    parser.add_argument("--title-basics", type=Path, default=DEFAULT_TITLE_BASICS)
    parser.add_argument("--skip-final-short-pass", action="store_true")
    return parser.parse_args()


def read_csv_if_exists(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    args = parse_args()
    ensure_output_dir(Path(args.final_output).parent)

    direct_matches = read_csv_if_exists(Path(args.initial_matches))
    excluded_shorts_seed = read_csv_if_exists(Path(args.excluded_shorts_seed))
    manual_log = read_csv_if_exists(Path(args.manual_resolution_log))
    collection_films = read_csv_if_exists(Path(args.collection_films))

    final_rows: List[dict] = []
    excluded_shorts: List[dict] = []
    rare_edge_cases: List[dict] = []

    for row in direct_matches:
        short_signal = classify_short_candidate(row.get("imdb_title_type", ""), row.get("imdb_runtime_minutes", ""), row.get("imdb_genres", ""))
        if short_signal != "feature_or_unknown":
            excluded_shorts.append(row)
            continue
        final_rows.append(row)

    for row in excluded_shorts_seed:
        excluded_shorts.append(
            {
                "criterion_row_id": row.get("criterion_row_id", ""),
                "criterion_source_id": row.get("criterion_source_id", ""),
                "criterion_title_original": row.get("criterion_title_original", ""),
                "criterion_year": row.get("criterion_year", ""),
                "candidate_imdb_id": row.get("imdb_id", ""),
                "candidate_imdb_title": row.get("imdb_primary_title", ""),
                "rationale": "Auto-excluded during initial matching because the best IMDb candidate is a short.",
                "review_status": "auto_resolved",
            }
        )

    for row in manual_log:
        action = (row.get("final_action") or "").strip().casefold()
        if action in {"matched_directly", "include", "matched"}:
            final_rows.append(
                {
                    "criterion_row_id": row.get("criterion_row_id", ""),
                    "criterion_source_id": row.get("criterion_source_id", ""),
                    "criterion_title_original": row.get("criterion_title_original", ""),
                    "criterion_title_normalized": "",
                    "criterion_director_original": "",
                    "criterion_year": row.get("criterion_year", ""),
                    "imdb_id": row.get("candidate_imdb_id", ""),
                    "imdb_primary_title": row.get("candidate_imdb_title", ""),
                    "imdb_original_title": "",
                    "imdb_title_type": "",
                    "imdb_start_year": "",
                    "imdb_runtime_minutes": "",
                    "imdb_genres": "",
                    "imdb_directors": "",
                    "matched_via": "manual_resolution_log",
                    "score": "",
                    "year_difference": "",
                    "short_signal": "feature_or_unknown",
                    "decision_bucket": "manual_match",
                    "generated_at": "",
                }
            )
        elif action in {"exclude_short", "exclude_as_short"}:
            excluded_shorts.append(
                {
                    "criterion_row_id": row.get("criterion_row_id", ""),
                    "criterion_source_id": row.get("criterion_source_id", ""),
                    "criterion_title_original": row.get("criterion_title_original", ""),
                    "criterion_year": row.get("criterion_year", ""),
                    "candidate_imdb_id": row.get("candidate_imdb_id", ""),
                    "candidate_imdb_title": row.get("candidate_imdb_title", ""),
                    "rationale": row.get("rationale", ""),
                    "review_status": row.get("review_status", ""),
                }
            )
        elif action in {"rare_edge_case", "flag_edge_case", "no_imdb_entry", "unresolved"}:
            rare_edge_cases.append(
                {
                    "criterion_row_id": row.get("criterion_row_id", ""),
                    "criterion_source_id": row.get("criterion_source_id", ""),
                    "criterion_title_original": row.get("criterion_title_original", ""),
                    "criterion_year": row.get("criterion_year", ""),
                    "candidate_imdb_id": row.get("candidate_imdb_id", ""),
                    "candidate_imdb_title": row.get("candidate_imdb_title", ""),
                    "rationale": row.get("rationale", "") or action,
                    "review_status": row.get("review_status", ""),
                    "last_updated": row.get("last_updated") or timestamp_utc(),
                }
            )

    for row in collection_films:
        if not _is_rich_collection_row(row):
            continue
        imdb_id = (row.get("imdb_id") or "").strip()
        if not imdb_id:
            continue
        short_signal = classify_short_candidate(
            row.get("imdb_title_type", ""),
            row.get("imdb_runtime_minutes", ""),
            row.get("imdb_genres", ""),
        )
        include = (row.get("include_in_dataset") or "").strip().casefold() == "true"
        if short_signal != "feature_or_unknown" or not include:
            reason = short_signal if short_signal != "feature_or_unknown" else "include_in_dataset_false"
            excluded_shorts.append(
                {
                    "criterion_row_id": f"collection_constituent_{row.get('collection_source_id', '')}_{row.get('seq', '')}",
                    "criterion_source_id": (row.get("film_source_id") or "").strip() or f"coll_{row.get('collection_source_id', '')}_{row.get('seq', '')}",
                    "criterion_title_original": row.get("film_title", ""),
                    "criterion_year": row.get("film_year", ""),
                    "candidate_imdb_id": imdb_id,
                    "candidate_imdb_title": row.get("imdb_primary_title", ""),
                    "rationale": f"collection_constituent_excluded ({reason})",
                    "review_status": "auto_resolved",
                }
            )
            continue
        final_rows.append(_normalize_collection_constituent_to_final(row))

    deduped: Dict[tuple, dict] = {}
    for row in final_rows:
        deduped[_dedup_key(row)] = row
    merged_rows = list(deduped.values())
    deliverable_rows = merged_rows if args.skip_final_short_pass else _postprocess_final_clean_rows(merged_rows, args.title_basics, excluded_shorts)

    write_csv(Path(args.final_output), deliverable_rows)
    write_csv(Path(args.excluded_shorts_output), excluded_shorts)
    write_csv(Path(args.rare_edge_cases_output), rare_edge_cases)

    disposition_rows, _ = build_criterion_dispositions(
        Path(args.criterion),
        Path(args.new_criterion),
        Path(args.overrides),
        Path(args.final_output),
        Path(args.excluded_shorts_output),
        Path(args.rare_edge_cases_output),
        Path(args.resolved_collections),
        Path(args.manual_resolution_log),
    )
    write_csv(Path(args.criterion_dispositions_output), disposition_rows)


if __name__ == "__main__":
    main()
