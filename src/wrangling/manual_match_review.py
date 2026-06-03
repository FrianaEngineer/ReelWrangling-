#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import List

from src.shared.normalize_titles import normalize_title
from src.shared.utils import ensure_output_dir, timestamp_utc, write_csv

REPO_ROOT = Path(__file__).resolve().parents[2]


AMBIGUOUS_DIRECT_MATCH_TITLES = {
    "america lost and found bbs story",
    "beastie boys video anthology",
    "by brakhage anthology volume two",
    "carl theodor dreyer",
    "fanny and alexander",
    "human condition",
    "lone wolf and cub",
    "the apu trilogy",
    "three colors",
    "underground railroad",
    "world on a wire",
}


def is_collectionish(title: str) -> bool:
    lowered = (title or "").casefold()
    if any(token in lowered for token in ("trilogy", "anthology", "collection", "archive", "complete", "series")):
        return True
    return ":" in lowered or "/" in lowered


def choose_best_candidates(path: Path) -> dict[str, dict]:
    by_row_id: dict[str, list[dict]] = defaultdict(list)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            by_row_id[row["criterion_row_id"]].append(row)
    best: dict[str, dict] = {}
    for row_id, candidates in by_row_id.items():
        candidates.sort(key=lambda row: int(row["score"]), reverse=True)
        best[row_id] = candidates[0]
    return best


def should_auto_exclude_short(row: dict, best: dict) -> bool:
    if best.get("short_signal") == "feature_or_unknown" or is_collectionish(row["criterion_title_original"]):
        return False
    criterion_title = normalize_title(row["criterion_title_original"])
    if criterion_title not in {normalize_title(best.get("imdb_primary_title", "")), normalize_title(best.get("imdb_original_title", ""))}:
        return False
    return best.get("year_difference", "") in {"", "0", "1", "2"}


def should_auto_match_direct(row: dict, best: dict) -> bool:
    if best.get("short_signal") != "feature_or_unknown" or is_collectionish(row["criterion_title_original"]):
        return False
    criterion_title = normalize_title(row["criterion_title_original"])
    if criterion_title in AMBIGUOUS_DIRECT_MATCH_TITLES:
        return False
    if criterion_title not in {normalize_title(best.get("imdb_primary_title", "")), normalize_title(best.get("imdb_original_title", ""))}:
        return False
    year_diff = best.get("year_difference", "")
    score = int(best.get("score", "0"))
    if year_diff in {"0", "1"} and score >= 65:
        return True
    has_support = any(best.get(field, "").strip() and best.get(field, "").strip() != r"\N" for field in ("imdb_start_year", "imdb_runtime_minutes", "imdb_directors"))
    return year_diff == "" and score >= 55 and has_support


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize a manual resolution log from the unmatched tracking file.")
    parser.add_argument("--tracking", default=str(REPO_ROOT / "data" / "output" / "unmatched_tracking.csv"))
    parser.add_argument("--review-candidates", default=str(REPO_ROOT / "data" / "output" / "match_candidates_review.csv"))
    parser.add_argument("--output", default=str(REPO_ROOT / "data" / "output" / "manual_resolution_log.csv"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows: List[dict] = []
    best_candidates = choose_best_candidates(Path(args.review_candidates))
    with Path(args.tracking).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            best = best_candidates.get(row["criterion_row_id"], {})
            final_action = row.get("final_action", "")
            rationale = row.get("rationale", "")
            entity_type = row.get("entity_type", "")
            review_status = row.get("review_status", "unreviewed")
            if best and should_auto_exclude_short(row, best):
                final_action = "exclude_short"
                entity_type = "short"
                review_status = "auto_resolved"
                rationale = f"Auto-excluded: IMDb candidate {best['imdb_id']} is a short and title alignment is exact."
            elif best and should_auto_match_direct(row, best):
                final_action = "matched_directly"
                entity_type = "film"
                review_status = "auto_resolved"
                rationale = f"Auto-matched: IMDb candidate {best['imdb_id']} has exact title alignment and acceptable year agreement."
            rows.append(
                {
                    "criterion_row_id": row["criterion_row_id"],
                    "criterion_source_id": row["criterion_source_id"],
                    "criterion_title_original": row["criterion_title_original"],
                    "criterion_year": row["criterion_year"],
                    "review_status": review_status,
                    "entity_type": entity_type,
                    "candidate_imdb_id": row.get("candidate_imdb_id", ""),
                    "candidate_imdb_title": row.get("candidate_imdb_title", ""),
                    "final_action": final_action,
                    "rationale": rationale,
                    "notes": row.get("notes", ""),
                    "last_updated": row.get("last_updated") or timestamp_utc(),
                }
            )
    ensure_output_dir(Path(args.output).parent)
    write_csv(Path(args.output), rows)


if __name__ == "__main__":
    main()
