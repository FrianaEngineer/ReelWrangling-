from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Tuple

from src.criterion.collection_manifest import discover_collection_groups, load_new_criterion_rows
from src.criterion.load_criterion import CriterionRow, load_criterion_rows
from src.shared.utils import ensure_output_dir, write_csv


def _read_csv(path: Path) -> List[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _index_final_by_row_id(final_rows: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for row in final_rows:
        row_id = (row.get("criterion_row_id") or "").strip()
        if row_id:
            out[row_id] = row
    return out


def _row_ids(path: Path, column: str = "criterion_row_id") -> set[str]:
    return {(row.get(column) or "").strip() for row in _read_csv(path) if (row.get(column) or "").strip()}


def _expand_status_by_collection_source(path: Path) -> Dict[str, str]:
    return {
        (row.get("collection_source_id") or "").strip(): (row.get("collection_status") or "").strip()
        for row in _read_csv(path)
        if (row.get("collection_source_id") or "").strip()
    }


def _manual_by_row_id(path: Path) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for row in _read_csv(path):
        row_id = (row.get("criterion_row_id") or "").strip()
        if row_id:
            out[row_id] = row
    return out


def _collection_root_source_ids(new_criterion_path: Path, overrides_path: Path) -> set[str]:
    if not new_criterion_path.exists():
        return set()
    return {
        group.collection_source_id
        for group in discover_collection_groups(load_new_criterion_rows(new_criterion_path), overrides_path)
    }


def disposition_bucket_four(disposition: str) -> str:
    if disposition == "matched_direct_feature":
        return "1_matched_direct_full_length"
    if disposition == "collection_unpacked":
        return "2_unpacked_from_collection"
    if disposition == "excluded_short":
        return "3_identified_short_excluded"
    if disposition == "rare_edge_case":
        return "4_rare_edge_case"
    return "unresolved"


def build_criterion_dispositions(
    criterion_path: Path,
    new_criterion_path: Path,
    overrides_path: Path,
    final_clean_path: Path,
    excluded_shorts_path: Path,
    rare_edge_cases_path: Path,
    resolved_collections_path: Path,
    manual_log_path: Path,
) -> Tuple[List[dict], Dict[str, int]]:
    catalog: List[CriterionRow] = load_criterion_rows(criterion_path)
    final_by_row_id = _index_final_by_row_id(_read_csv(final_clean_path))
    excluded_ids = _row_ids(excluded_shorts_path)
    rare_ids = _row_ids(rare_edge_cases_path)
    collection_root_ids = _collection_root_source_ids(new_criterion_path, overrides_path)
    expand_status = _expand_status_by_collection_source(resolved_collections_path)
    manual_by_row_id = _manual_by_row_id(manual_log_path)

    counts = {
        "matched_direct_feature": 0,
        "collection_unpacked": 0,
        "excluded_short": 0,
        "rare_edge_case": 0,
        "unresolved": 0,
    }
    rows_out: List[dict] = []

    for row in catalog:
        row_id = row.criterion_row_id
        source_id = row.criterion_source_id
        disposition = "unresolved"
        detail = "not_classified"

        if row_id in rare_ids:
            disposition, detail = "rare_edge_case", "listed_in_rare_edge_cases.csv"
        elif row_id in excluded_ids:
            disposition, detail = "excluded_short", "listed_in_excluded_shorts.csv"
        elif row_id in final_by_row_id:
            final_row = final_by_row_id[row_id]
            matched_via = (final_row.get("matched_via") or "").strip()
            if matched_via == "expanded_collection":
                disposition, detail = "collection_unpacked", "final_via_expanded_collection"
            else:
                disposition, detail = "matched_direct_feature", f"final_matched_via={matched_via or 'unknown'}"
        else:
            manual = manual_by_row_id.get(row_id)
            if manual:
                action = (manual.get("final_action") or "").strip().casefold()
                if action in {"collection", "collection_label"}:
                    disposition, detail = "collection_unpacked", f"manual_resolution_{action}"
                elif action in {"matched", "matched_directly", "include"}:
                    disposition, detail = "matched_direct_feature", "manual_resolution_pending_build_final"
                elif action in {"exclude_short", "exclude_as_short"}:
                    disposition, detail = "excluded_short", "manual_resolution_exclude_short"
                elif action in {"rare_edge_case", "flag_edge_case"}:
                    disposition, detail = "rare_edge_case", "manual_resolution_rare_edge"
                elif action in {"no_imdb_entry", "unresolved"}:
                    disposition, detail = "unresolved", action
            if disposition == "unresolved" and source_id in collection_root_ids:
                action = (manual.get("final_action") or "").strip().casefold() if manual else ""
                if action not in {"no_imdb_entry", "unresolved"}:
                    status = expand_status.get(source_id, "")
                    if status == "resolved":
                        disposition, detail = "collection_unpacked", "collection_container_expand_resolved"
                    elif status in {"partial", "needs_manual_decomposition"}:
                        disposition, detail = "unresolved", f"collection_expand_{status}"

        counts[disposition] += 1
        rows_out.append(
            {
                "criterion_row_id": row_id,
                "criterion_source_id": source_id,
                "criterion_title_original": row.title_original,
                "disposition": disposition,
                "disposition_bucket": disposition_bucket_four(disposition),
                "detail": detail,
            }
        )

    return rows_out, counts


if __name__ == "__main__":
    import argparse

    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Write criterion_dispositions.csv from the scriptsNew pipeline outputs.")
    parser.add_argument("--criterion", type=Path, default=repo_root / "new-criterion.csv")
    parser.add_argument("--new-criterion", type=Path, default=repo_root / "new-criterion.csv")
    parser.add_argument("--overrides", type=Path, default=repo_root / "data" / "collection_constituents_overrides.csv")
    parser.add_argument("--final-clean", type=Path, default=repo_root / "outputs" / "final_clean_films.csv")
    parser.add_argument("--excluded-shorts", type=Path, default=repo_root / "outputs" / "excluded_shorts.csv")
    parser.add_argument("--rare-edge-cases", type=Path, default=repo_root / "outputs" / "rare_edge_cases.csv")
    parser.add_argument("--resolved-collections", type=Path, default=repo_root / "outputs" / "resolved_collections.csv")
    parser.add_argument("--manual-resolution-log", type=Path, default=repo_root / "outputs" / "manual_resolution_log.csv")
    parser.add_argument("--output", type=Path, default=repo_root / "outputs" / "criterion_dispositions.csv")
    args = parser.parse_args()

    rows, counts = build_criterion_dispositions(
        args.criterion,
        args.new_criterion,
        args.overrides,
        args.final_clean,
        args.excluded_shorts,
        args.rare_edge_cases,
        args.resolved_collections,
        args.manual_resolution_log,
    )
    ensure_output_dir(args.output.parent)
    write_csv(args.output, rows)
    print(counts)
