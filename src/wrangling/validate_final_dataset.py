#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List

from src.criterion.collection_manifest import collection_container_source_ids, load_new_criterion_rows
from src.wrangling.criterion_dispositions import build_criterion_dispositions
from src.criterion.load_criterion import load_criterion_rows
from src.shared.utils import ensure_output_dir, write_csv

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a simple validation report for the current pipeline outputs.")
    parser.add_argument("--criterion", default=str(REPO_ROOT / "data" / "criterion" / "criterion_browse_fields.csv"))
    parser.add_argument("--new-criterion", default=str(REPO_ROOT / "data" / "criterion" / "new-criterion.csv"))
    parser.add_argument("--initial-matches", default=str(REPO_ROOT / "data" / "output" / "initial_matches.csv"))
    parser.add_argument("--unmatched-tracking", default=str(REPO_ROOT / "data" / "output" / "unmatched_tracking.csv"))
    parser.add_argument("--resolved-collections", default=str(REPO_ROOT / "data" / "output" / "resolved_collections.csv"))
    parser.add_argument("--collection-films", default=str(REPO_ROOT / "data" / "output" / "collection_constituent_films.csv"))
    parser.add_argument("--collection-shorts", default=str(REPO_ROOT / "data" / "output" / "collection_shorts_excluded.csv"))
    parser.add_argument("--final-clean-films", default=str(REPO_ROOT / "data" / "output" / "final_clean_films.csv"))
    parser.add_argument("--excluded-shorts", default=str(REPO_ROOT / "data" / "output" / "excluded_shorts.csv"))
    parser.add_argument("--rare-edge-cases", default=str(REPO_ROOT / "data" / "output" / "rare_edge_cases.csv"))
    parser.add_argument("--manual-resolution-log", default=str(REPO_ROOT / "data" / "output" / "manual_resolution_log.csv"))
    parser.add_argument("--collection-overrides", default=str(REPO_ROOT / "data" / "collection_constituents_overrides.csv"))
    parser.add_argument("--dispositions-output", default=str(REPO_ROOT / "data" / "output" / "criterion_dispositions.csv"))
    parser.add_argument("--output", default=str(REPO_ROOT / "data" / "output" / "validation_report.csv"))
    return parser.parse_args()


def count_rows(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def read_ids(path: Path, column: str) -> List[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [row[column] for row in csv.DictReader(handle) if row.get(column)]


def read_csv_rows(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    args = parse_args()
    ensure_output_dir(Path(args.output).parent)
    matched_ids = set(read_ids(Path(args.initial_matches), "criterion_row_id"))
    unresolved_ids = set(read_ids(Path(args.unmatched_tracking), "criterion_row_id"))
    final_ids = set(read_ids(Path(args.final_clean_films), "criterion_row_id"))
    excluded_short_ids = set(read_ids(Path(args.excluded_shorts), "criterion_row_id"))
    rare_edge_ids = set(read_ids(Path(args.rare_edge_cases), "criterion_row_id"))
    terminal_ids = matched_ids | excluded_short_ids | rare_edge_ids

    container_source_ids: set[str] = set()
    nc_path = Path(args.new_criterion)
    if nc_path.exists():
        container_source_ids = collection_container_source_ids(load_new_criterion_rows(nc_path))

    final_rows = read_csv_rows(Path(args.final_clean_films))
    final_invalid_imdb = sum(
        1 for r in final_rows if not (r.get("imdb_id") or "").strip().startswith("tt")
    )
    final_non_feature_short_signal = sum(
        1
        for r in final_rows
        if (r.get("short_signal") or "").strip() and (r.get("short_signal") or "").strip() != "feature_or_unknown"
    )
    container_as_single_film = 0
    for row in final_rows:
        src = (row.get("criterion_source_id") or "").strip()
        if not src or src not in container_source_ids:
            continue
        if (row.get("matched_via") or "").strip() == "expanded_collection":
            continue
        container_as_single_film += 1

    coll_films = read_csv_rows(Path(args.collection_films))
    with_imdb = sum(1 for r in coll_films if (r.get("imdb_id") or "").strip())
    included_flag = sum(1 for r in coll_films if (r.get("include_in_dataset") or "").strip().casefold() == "true")

    disposition_rows, disposition_counts = build_criterion_dispositions(
        Path(args.criterion),
        Path(args.new_criterion),
        Path(args.collection_overrides),
        Path(args.final_clean_films),
        Path(args.excluded_shorts),
        Path(args.rare_edge_cases),
        Path(args.resolved_collections),
        Path(args.manual_resolution_log),
    )
    write_csv(Path(args.dispositions_output), disposition_rows)
    four_bucket_terminal = (
        disposition_counts["matched_direct_feature"]
        + disposition_counts["collection_unpacked"]
        + disposition_counts["excluded_short"]
        + disposition_counts["rare_edge_case"]
    )
    source_count = len(load_criterion_rows(Path(args.criterion)))

    report: List[dict] = [
        {"metric": "criterion_source_rows", "value": source_count},
        {"metric": "initial_matches_rows", "value": count_rows(Path(args.initial_matches))},
        {"metric": "unmatched_tracking_rows", "value": count_rows(Path(args.unmatched_tracking))},
        {"metric": "resolved_collections_rows", "value": count_rows(Path(args.resolved_collections))},
        {"metric": "collection_constituent_films_rows", "value": count_rows(Path(args.collection_films))},
        {"metric": "collection_shorts_rows", "value": count_rows(Path(args.collection_shorts))},
        {"metric": "final_clean_films_rows", "value": count_rows(Path(args.final_clean_films))},
        {"metric": "final_clean_rows_missing_valid_imdb_tt", "value": final_invalid_imdb},
        {"metric": "final_clean_rows_short_signal_not_feature", "value": final_non_feature_short_signal},
        {"metric": "excluded_shorts_rows", "value": count_rows(Path(args.excluded_shorts))},
        {"metric": "rare_edge_cases_rows", "value": count_rows(Path(args.rare_edge_cases))},
        {"metric": "final_clean_unique_row_ids", "value": len(final_ids)},
        {"metric": "terminal_status_row_ids", "value": len(terminal_ids)},
        {"metric": "still_unresolved_row_ids", "value": len(unresolved_ids.difference(terminal_ids))},
        {
            "metric": "criterion_disposition_unresolved",
            "value": disposition_counts["unresolved"],
        },
        {
            "metric": "criterion_disposition_matched_direct_feature",
            "value": disposition_counts["matched_direct_feature"],
        },
        {
            "metric": "criterion_disposition_collection_unpacked",
            "value": disposition_counts["collection_unpacked"],
        },
        {
            "metric": "criterion_disposition_excluded_short",
            "value": disposition_counts["excluded_short"],
        },
        {
            "metric": "criterion_disposition_rare_edge_case",
            "value": disposition_counts["rare_edge_case"],
        },
        {"metric": "criterion_four_bucket_terminal_rows", "value": four_bucket_terminal},
        {
            "metric": "criterion_four_bucket_coverage_pct",
            "value": round(100.0 * four_bucket_terminal / source_count, 2) if source_count else 0.0,
        },
        {"metric": "collection_container_single_film_violations", "value": container_as_single_film},
        {"metric": "collection_constituents_with_imdb_id", "value": with_imdb},
        {"metric": "collection_constituents_include_in_dataset_true", "value": included_flag},
    ]
    write_csv(Path(args.output), report)


if __name__ == "__main__":
    main()
