#!/usr/bin/env python3

from __future__ import annotations

import csv

from criterion_second_pass import (
    AUTO_ACCEPT_MARGIN,
    AUTO_ACCEPT_SCORE,
    BASIC_INFO_CSV,
    OUTPUT,
    TITLE_AKAS_TSV,
    TITLE_BASICS_TSV,
    UNMATCHED_CSV,
    build_exact_indexes,
    build_remaining_unmatched,
    canonical_title_tokens,
    clean,
    load_criterion_rows,
    loose_norm,
    score_candidates,
    strict_norm,
    title_similarity,
    title_variants,
    update_translation_exports,
    write_csv,
    jaccard,
)


csv.field_size_limit(10_000_000)


MANUAL_REVIEW_FIELDS = [
    "row_id",
    "rank",
    "title",
    "criterion_director",
    "criterion_country",
    "criterion_year",
    "candidate_tt_identifier",
    "candidate_title",
    "candidate_original_title",
    "candidate_year",
    "candidate_title_type",
    "candidate_director_nconst",
    "candidate_director_names",
    "director_match_status",
    "director_similarity",
    "candidate_writer_nconst",
    "score",
    "margin_to_second",
    "auto_accept",
    "evidence",
    "source",
    "matched_title_variant",
    "title_similarity",
    "token_overlap",
]

MATCHED_FIELDS = [
    "title",
    "criterion_director",
    "criterion_country",
    "criterion_year",
    "tt_identifier",
    "title_type",
    "runtime_minutes",
    "year",
    "director_nconst",
    "writer_nconst",
    "english_title",
    "match_score",
    "match_stage",
    "match_evidence",
]

UNMATCHED_FIELDS = [
    "title",
    "director",
    "country",
    "year",
    "best_candidate_tt_identifier",
    "best_candidate_title",
    "best_candidate_score",
    "best_candidate_evidence",
]


def _choose_better_candidate(prev: dict[str, str] | None, curr: dict[str, str]) -> dict[str, str]:
    if prev is None:
        return curr
    prev_key = (
        prev["strict_match"],
        prev["loose_match"],
        prev["title_similarity"],
        prev["token_overlap"],
    )
    curr_key = (
        curr["strict_match"],
        curr["loose_match"],
        curr["title_similarity"],
        curr["token_overlap"],
    )
    return curr if curr_key > prev_key else prev


def collect_candidates_first_pass(criterion_rows):
    strict_index, loose_index = build_exact_indexes(criterion_rows)
    raw_index = {}
    for row in criterion_rows:
        raw_index.setdefault(row.title, set()).add(row.row_id)
    title_by_id = {row.row_id: row.title for row in criterion_rows}
    strict_norm_by_id = {row.row_id: row.strict_title for row in criterion_rows}
    loose_norm_by_id = {row.row_id: row.loose_title for row in criterion_rows}
    tokens_by_id = {row.row_id: row.canonical_title_tokens for row in criterion_rows}

    candidates: dict[tuple[int, str], dict[str, str]] = {}
    basics: dict[str, dict[str, str]] = {}
    aka_hits: dict[tuple[int, str], dict[str, str]] = {}

    def exact_row_ids_for_title(title: str) -> set[int]:
        row_ids: set[int] = set()
        row_ids.update(raw_index.get(title, set()))
        row_ids.update(strict_index.get(strict_norm(title), set()))
        row_ids.update(loose_index.get(loose_norm(title), set()))
        return row_ids

    def record_candidate(row_ids: set[int], tconst: str, imdb_title: str, source: str):
        for row_id in row_ids:
            title_sim = title_similarity(title_by_id[row_id], imdb_title)
            overlap = jaccard(tokens_by_id[row_id], canonical_title_tokens(imdb_title))
            entry = {
                "row_id": str(row_id),
                "tconst": tconst,
                "matched_title_variant": imdb_title,
                "source": source,
                "strict_match": "1" if strict_norm(imdb_title) == strict_norm_by_id[row_id] else "0",
                "loose_match": "1" if loose_norm(imdb_title) == loose_norm_by_id[row_id] else "0",
                "title_similarity": f"{title_sim:.4f}",
                "token_overlap": f"{overlap:.4f}",
            }
            key = (row_id, tconst)
            candidates[key] = _choose_better_candidate(candidates.get(key), entry)

    with TITLE_BASICS_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tconst = row["tconst"]
            primary = clean(row["primaryTitle"])
            original = clean(row["originalTitle"])

            all_row_ids = set()
            for title, source in ((primary, "primary"), (original, "original")):
                if not title:
                    continue
                row_ids = exact_row_ids_for_title(title)
                if not row_ids:
                    continue
                all_row_ids.update(row_ids)
                record_candidate(row_ids, tconst, title, source)

            if all_row_ids:
                basics[tconst] = {
                    "tt_identifier": tconst,
                    "title_type": clean(row["titleType"]),
                    "runtime_minutes": clean(row["runtimeMinutes"]),
                    "year": clean(row["startYear"]),
                    "primary_title": primary,
                    "original_title": original,
                }

    with TITLE_AKAS_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            aka_title = clean(row["title"])
            if not aka_title:
                continue
            row_ids = exact_row_ids_for_title(aka_title)
            if not row_ids:
                continue
            tconst = row["titleId"]
            for row_id in row_ids:
                aka_hits[(row_id, tconst)] = {
                    "aka_title": aka_title,
                    "aka_language": clean(row["language"]),
                    "aka_region": clean(row["region"]),
                    "aka_types": clean(row["types"]),
                }
            record_candidate(row_ids, tconst, aka_title, "aka")

    missing_tconsts = {tconst for _, tconst in candidates} - basics.keys()
    if missing_tconsts:
        with TITLE_BASICS_TSV.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                tconst = row["tconst"]
                if tconst not in missing_tconsts:
                    continue
                basics[tconst] = {
                    "tt_identifier": tconst,
                    "title_type": clean(row["titleType"]),
                    "runtime_minutes": clean(row["runtimeMinutes"]),
                    "year": clean(row["startYear"]),
                    "primary_title": clean(row["primaryTitle"]),
                    "original_title": clean(row["originalTitle"]),
                }
                missing_tconsts.remove(tconst)
                if not missing_tconsts:
                    break

    exact_count = sum(1 for item in candidates.values() if item["strict_match"] == "1" or item["loose_match"] == "1" or item["source"] == "aka")
    fuzzy_count = 0
    return candidates, basics, aka_hits, exact_count, fuzzy_count


def main() -> None:
    criterion_rows = load_criterion_rows()

    all_candidates, basics, aka_hits, exact_count, fuzzy_count = collect_candidates_first_pass(criterion_rows)
    auto_matches, manual_review = score_candidates(criterion_rows, all_candidates, basics, aka_hits)

    matched_rows = []
    for criterion_row in criterion_rows:
        matched = auto_matches.get(criterion_row.row_id)
        if not matched:
            continue
        row = dict(matched)
        row["match_stage"] = "first_pass_auto"
        matched_rows.append(row)

    matched_rows.sort(key=lambda row: (row["title"], row["criterion_year"], row["criterion_director"]))
    remaining_unmatched = build_remaining_unmatched(criterion_rows, auto_matches, manual_review)

    write_csv(BASIC_INFO_CSV, MATCHED_FIELDS, matched_rows)
    write_csv(UNMATCHED_CSV, UNMATCHED_FIELDS, remaining_unmatched)
    write_csv(OUTPUT / "manual_review_candidates.csv", MANUAL_REVIEW_FIELDS, manual_review)
    update_translation_exports(matched_rows)

    print(f"criterion rows: {len(criterion_rows)}")
    print(f"exact candidates: {exact_count}")
    print(f"fuzzy review candidates: {fuzzy_count}")
    print(f"auto matches: {len(matched_rows)}")
    print(f"remaining unmatched: {len(remaining_unmatched)}")
    print(f"manual review rows: {len(manual_review)}")
    print(f"auto-accept score threshold: {AUTO_ACCEPT_SCORE}")
    print(f"auto-accept margin threshold: {AUTO_ACCEPT_MARGIN}")


if __name__ == "__main__":
    main()
