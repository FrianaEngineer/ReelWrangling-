#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from src.shared.normalize_titles import normalize_title

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNMATCHED = REPO_ROOT / "data" / "output" / "unmatched_tracking.csv"
DEFAULT_TITLE_BASICS = REPO_ROOT / "data" / "imdb" / "title.basics.tsv"
DEFAULT_TITLE_AKAS = REPO_ROOT / "data" / "imdb" / "title.akas.tsv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "output" / "noEntry.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find unresolved manual-review rows with no detectable IMDb title entry."
    )
    parser.add_argument("--unmatched", default=str(DEFAULT_UNMATCHED))
    parser.add_argument("--title-basics", default=str(DEFAULT_TITLE_BASICS))
    parser.add_argument("--title-akas", default=str(DEFAULT_TITLE_AKAS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def load_targets(path: Path) -> tuple[list[dict[str, str]], set[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    unresolved_no_candidate = [
        row
        for row in rows
        if not (row.get("final_action") or "").strip()
        and not (row.get("candidate_imdb_id") or "").strip()
    ]

    normalized_titles = {
        normalize_title(row.get("criterion_title_original", ""))
        for row in unresolved_no_candidate
        if normalize_title(row.get("criterion_title_original", ""))
    }
    return unresolved_no_candidate, normalized_titles


def collect_matching_titles_from_basics(path: Path, target_titles: set[str]) -> set[str]:
    matched_titles: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        next(handle, None)
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            for raw_title in (parts[2], parts[3]):
                norm = normalize_title(raw_title)
                if norm in target_titles:
                    matched_titles.add(norm)
            if matched_titles == target_titles:
                break
    return matched_titles


def collect_matching_titles_from_akas(path: Path, target_titles: set[str]) -> set[str]:
    matched_titles: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        next(handle, None)
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            norm = normalize_title(parts[2])
            if norm in target_titles:
                matched_titles.add(norm)
            if matched_titles == target_titles:
                break
    return matched_titles


def main() -> None:
    args = parse_args()
    unmatched_rows, target_titles = load_targets(Path(args.unmatched))
    basics_hits = collect_matching_titles_from_basics(Path(args.title_basics), target_titles)
    akas_hits = collect_matching_titles_from_akas(Path(args.title_akas), target_titles)
    all_hits = basics_hits | akas_hits

    no_entry_rows = []
    for row in unmatched_rows:
        normalized = normalize_title(row.get("criterion_title_original", ""))
        if normalized and normalized not in all_hits:
            no_entry_rows.append(row)

    lines = []
    lines.append("Unresolved Manual Review Rows With No Detectable IMDb Title Entry")
    lines.append("Generated: 2026-05-16")
    lines.append("")
    lines.append(f"Checked unresolved rows with no candidate IMDb ID: {len(unmatched_rows)}")
    lines.append(f"No exact normalized title hit in title.basics/title.akas: {len(no_entry_rows)}")
    lines.append("")
    for row in no_entry_rows:
        lines.append(
            f"- {row.get('criterion_source_id', '-')}: {row.get('criterion_title_original', '')} "
            f"({row.get('criterion_year', '')})"
        )

    Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
