#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from src.imdb.classify_shorts import classify_short_candidate
from src.criterion.collection_manifest import collection_container_source_ids, load_new_criterion_rows
from src.criterion.load_criterion import CriterionRow, load_criterion_rows
from src.shared.normalize_titles import normalize_title
from src.shared.utils import ensure_output_dir, parse_year, timestamp_utc, write_csv


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMDB_DIR = REPO_ROOT / "data" / "imdb"
DEFAULT_CRITERION = REPO_ROOT / "data" / "criterion" / "new-criterion.csv"
DEFAULT_NEW_CRITERION = REPO_ROOT / "data" / "criterion" / "new-criterion.csv"
ALLOWED_TITLE_TYPES = {"movie", "tvMovie", "video", "tvSpecial", "short"}
csv.field_size_limit(sys.maxsize)


@dataclass
class ImdbMeta:
    tconst: str
    title_type: str
    primary_title: str
    original_title: str
    start_year: str
    runtime_minutes: str
    genres: str
    directors: List[str] = field(default_factory=list)


@dataclass
class Candidate:
    criterion_row_id: str
    imdb_id: str
    title_type: str
    primary_title: str
    original_title: str
    start_year: str
    runtime_minutes: str
    genres: str
    matched_via: Set[str] = field(default_factory=set)
    directors: List[str] = field(default_factory=list)
    score: int = 0
    year_difference: Optional[int] = None
    short_signal: str = ""


DIRECTOR_SPLIT_RE = re.compile(r"\s*(?:,| and | & | et | y )\s*", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate conservative initial Criterion-to-IMDb matches from new-criterion.csv.")
    parser.add_argument("--criterion", default=str(DEFAULT_CRITERION))
    parser.add_argument("--title-basics", default=str(DEFAULT_IMDB_DIR / "title.basics.tsv"))
    parser.add_argument("--title-akas", default=str(DEFAULT_IMDB_DIR / "title.akas.tsv"))
    parser.add_argument("--title-crew", default=str(DEFAULT_IMDB_DIR / "title.crew.tsv"))
    parser.add_argument("--name-basics", default=str(DEFAULT_IMDB_DIR / "name.basics.tsv"))
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "data" / "output"))
    return parser.parse_args()


def exact_key(value: str) -> str:
    return value.strip().casefold()


def normalize_person_name(value: str) -> str:
    value = normalize_title(value)
    tokens = [token for token in value.split() if len(token) > 1]
    return " ".join(tokens)


def split_director_field(value: str) -> List[str]:
    value = (value or "").strip()
    if not value:
        return []
    parts = [part.strip() for part in DIRECTOR_SPLIT_RE.split(value) if part.strip()]
    return parts or [value]


def directors_match(criterion_director_field: str, imdb_directors: List[str]) -> bool:
    criterion_names = {normalize_person_name(name) for name in split_director_field(criterion_director_field)}
    imdb_names = {normalize_person_name(name) for name in imdb_directors}
    criterion_names.discard("")
    imdb_names.discard("")
    if not criterion_names or not imdb_names:
        return False
    if criterion_names & imdb_names:
        return True
    for criterion_name in criterion_names:
        criterion_tokens = set(criterion_name.split())
        for imdb_name in imdb_names:
            imdb_tokens = set(imdb_name.split())
            if criterion_tokens and imdb_tokens and (criterion_tokens <= imdb_tokens or imdb_tokens <= criterion_tokens):
                return True
    return False


def load_collection_skip_source_ids() -> Set[str]:
    if not DEFAULT_NEW_CRITERION.exists():
        return set()
    return collection_container_source_ids(load_new_criterion_rows(DEFAULT_NEW_CRITERION))


def build_indexes(rows: Iterable[CriterionRow]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    exact_index: Dict[str, List[str]] = defaultdict(list)
    normalized_index: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        exact_index[exact_key(row.title_original)].append(row.criterion_row_id)
        normalized_index[row.title_normalized].append(row.criterion_row_id)
    return exact_index, normalized_index


def make_meta(row: dict) -> ImdbMeta:
    return ImdbMeta(
        tconst=row["tconst"],
        title_type=row["titleType"],
        primary_title=row["primaryTitle"],
        original_title=row["originalTitle"],
        start_year=row["startYear"],
        runtime_minutes=row["runtimeMinutes"],
        genres=row["genres"],
    )


def add_candidate(candidates: Dict[Tuple[str, str], Candidate], criterion_row_id: str, meta: ImdbMeta, matched_via: str) -> None:
    key = (criterion_row_id, meta.tconst)
    if key not in candidates:
        candidates[key] = Candidate(
            criterion_row_id=criterion_row_id,
            imdb_id=meta.tconst,
            title_type=meta.title_type,
            primary_title=meta.primary_title,
            original_title=meta.original_title,
            start_year=meta.start_year,
            runtime_minutes=meta.runtime_minutes,
            genres=meta.genres,
        )
    candidates[key].matched_via.add(matched_via)


def stream_basics(basics_path: Path, exact_index: Dict[str, List[str]], normalized_index: Dict[str, List[str]]) -> Tuple[Dict[Tuple[str, str], Candidate], Dict[str, ImdbMeta]]:
    candidates: Dict[Tuple[str, str], Candidate] = {}
    meta_by_tconst: Dict[str, ImdbMeta] = {}
    with basics_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["titleType"] not in ALLOWED_TITLE_TYPES:
                continue
            meta = make_meta(row)
            exact_titles = {exact_key(meta.primary_title), exact_key(meta.original_title)}
            normalized_titles = {normalize_title(meta.primary_title), normalize_title(meta.original_title)}
            matched_ids: Set[str] = set()
            matched_via: Set[str] = set()
            for title in exact_titles:
                if title in exact_index:
                    matched_ids.update(exact_index[title])
                    matched_via.add("title_exact")
            for title in normalized_titles:
                if title in normalized_index:
                    matched_ids.update(normalized_index[title])
                    matched_via.add("title_normalized")
            if not matched_ids:
                continue
            meta_by_tconst[meta.tconst] = meta
            for criterion_row_id in matched_ids:
                for via in matched_via:
                    add_candidate(candidates, criterion_row_id, meta, via)
    return candidates, meta_by_tconst


def stream_akas(
    akas_path: Path,
    exact_index: Dict[str, List[str]],
    normalized_index: Dict[str, List[str]],
    candidates: Dict[Tuple[str, str], Candidate],
    meta_by_tconst: Dict[str, ImdbMeta],
    basics_path: Path,
) -> None:
    needed_tconsts: Set[str] = set()
    pending_matches: Dict[str, Set[str]] = defaultdict(set)
    pending_via: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    with akas_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            exact_title = exact_key(row["title"])
            normalized_title = normalize_title(row["title"])
            matched_ids: Set[str] = set(exact_index.get(exact_title, []))
            matched_via: Set[str] = set()
            if matched_ids:
                matched_via.add("aka_exact")
            if normalized_title in normalized_index:
                matched_ids.update(normalized_index[normalized_title])
                matched_via.add("aka_normalized")
            if not matched_ids:
                continue
            needed_tconsts.add(row["titleId"])
            for criterion_row_id in matched_ids:
                pending_matches[row["titleId"]].add(criterion_row_id)
                pending_via[(criterion_row_id, row["titleId"])].update(matched_via)
    missing_tconsts = needed_tconsts.difference(meta_by_tconst)
    if missing_tconsts:
        with basics_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                if row["tconst"] in missing_tconsts and row["titleType"] in ALLOWED_TITLE_TYPES:
                    meta_by_tconst[row["tconst"]] = make_meta(row)
    for title_id, criterion_row_ids in pending_matches.items():
        if title_id not in meta_by_tconst:
            continue
        for criterion_row_id in criterion_row_ids:
            for via in pending_via[(criterion_row_id, title_id)]:
                add_candidate(candidates, criterion_row_id, meta_by_tconst[title_id], via)


def attach_directors(candidates: Dict[Tuple[str, str], Candidate], crew_path: Path, names_path: Path) -> None:
    tconsts = {candidate.imdb_id for candidate in candidates.values()}
    director_ids_by_tconst: Dict[str, List[str]] = {}
    needed_names: Set[str] = set()
    with crew_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["tconst"] not in tconsts:
                continue
            director_ids = [] if row["directors"] == r"\N" else row["directors"].split(",")
            director_ids_by_tconst[row["tconst"]] = director_ids
            needed_names.update(director_ids)
    name_by_nconst: Dict[str, str] = {}
    with names_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["nconst"] in needed_names:
                name_by_nconst[row["nconst"]] = row["primaryName"]
    for candidate in candidates.values():
        candidate.directors = [name_by_nconst[nconst] for nconst in director_ids_by_tconst.get(candidate.imdb_id, []) if nconst in name_by_nconst]


def score_candidate(criterion: CriterionRow, candidate: Candidate) -> None:
    exact_titles = {exact_key(candidate.primary_title), exact_key(candidate.original_title)}
    normalized_titles = {normalize_title(candidate.primary_title), normalize_title(candidate.original_title)}
    if "title_exact" in candidate.matched_via or "aka_exact" in candidate.matched_via:
        candidate.score += 40
    elif "title_normalized" in candidate.matched_via or "aka_normalized" in candidate.matched_via:
        candidate.score += 28

    if exact_key(criterion.title_original) in exact_titles:
        candidate.score += 10
    elif criterion.title_normalized in normalized_titles:
        candidate.score += 6

    imdb_year = parse_year(candidate.start_year)
    if criterion.year is not None and imdb_year is not None:
        diff = abs(criterion.year - imdb_year)
        candidate.year_difference = diff
        if diff == 0:
            candidate.score += 25
        elif diff == 1:
            candidate.score += 10
        elif diff == 2:
            candidate.score += 4
        else:
            candidate.score -= 20

    if directors_match(criterion.director_original, candidate.directors):
        candidate.score += 25
    elif criterion.director_original.strip() and candidate.directors:
        candidate.score -= 5

    if candidate.title_type in {"movie", "tvMovie", "video"}:
        candidate.score += 5
    if candidate.title_type == "short":
        candidate.score -= 20

    candidate.short_signal = classify_short_candidate(candidate.title_type, candidate.runtime_minutes, candidate.genres)
    if candidate.short_signal != "feature_or_unknown":
        candidate.score -= 15


def decide_bucket(ranked: List[Candidate]) -> str:
    if not ranked:
        return "unmatched"
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    margin = best.score - second.score if second else best.score
    if best.short_signal != "feature_or_unknown":
        if best.score >= 50 and best.year_difference == 0 and (len(ranked) == 1 or margin >= 15):
            return "exclude_short"
        return "review"
    if best.score >= 80 and margin >= 15:
        return "matched"
    if best.score >= 92:
        return "matched"
    if best.score >= 75 and best.year_difference == 0 and (len(ranked) == 1 or margin >= 15):
        return "matched"
    return "review"


def candidate_row(criterion: CriterionRow, candidate: Candidate, bucket: str) -> dict:
    return {
        "criterion_row_id": criterion.criterion_row_id,
        "criterion_source_id": criterion.criterion_source_id,
        "criterion_title_original": criterion.title_original,
        "criterion_title_normalized": criterion.title_normalized,
        "criterion_director_original": criterion.director_original,
        "criterion_year": criterion.year if criterion.year is not None else "",
        "imdb_id": candidate.imdb_id,
        "imdb_primary_title": candidate.primary_title,
        "imdb_original_title": candidate.original_title,
        "imdb_title_type": candidate.title_type,
        "imdb_start_year": candidate.start_year,
        "imdb_runtime_minutes": candidate.runtime_minutes,
        "imdb_genres": candidate.genres,
        "imdb_directors": " | ".join(candidate.directors),
        "matched_via": " | ".join(sorted(candidate.matched_via)),
        "score": candidate.score,
        "year_difference": candidate.year_difference if candidate.year_difference is not None else "",
        "short_signal": candidate.short_signal,
        "decision_bucket": bucket,
        "generated_at": timestamp_utc(),
    }


def unmatched_row(criterion: CriterionRow, notes: str = "") -> dict:
    return {
        "criterion_row_id": criterion.criterion_row_id,
        "criterion_source_id": criterion.criterion_source_id,
        "criterion_title_original": criterion.title_original,
        "criterion_title_normalized": criterion.title_normalized,
        "criterion_director_original": criterion.director_original,
        "criterion_country": criterion.country_original,
        "criterion_year": criterion.year if criterion.year is not None else "",
        "review_status": "unreviewed",
        "entity_type": "",
        "candidate_imdb_id": "",
        "final_action": "",
        "rationale": "",
        "notes": notes,
        "last_updated": timestamp_utc(),
    }


def main() -> None:
    args = parse_args()
    output_dir = ensure_output_dir(Path(args.output_dir))
    criterion_rows = load_criterion_rows(Path(args.criterion))
    criterion_by_id = {row.criterion_row_id: row for row in criterion_rows}
    exact_index, normalized_index = build_indexes(criterion_rows)

    candidates, meta_by_tconst = stream_basics(Path(args.title_basics), exact_index, normalized_index)
    stream_akas(Path(args.title_akas), exact_index, normalized_index, candidates, meta_by_tconst, Path(args.title_basics))

    for candidate in candidates.values():
        if candidate.imdb_id in meta_by_tconst:
            meta = meta_by_tconst[candidate.imdb_id]
            candidate.title_type = meta.title_type
            candidate.primary_title = meta.primary_title
            candidate.original_title = meta.original_title
            candidate.start_year = meta.start_year
            candidate.runtime_minutes = meta.runtime_minutes
            candidate.genres = meta.genres

    attach_directors(candidates, Path(args.title_crew), Path(args.name_basics))

    ranked_by_criterion: Dict[str, List[Candidate]] = defaultdict(list)
    for (criterion_row_id, _), candidate in candidates.items():
        score_candidate(criterion_by_id[criterion_row_id], candidate)
        ranked_by_criterion[criterion_row_id].append(candidate)
    for criterion_row_id in ranked_by_criterion:
        ranked_by_criterion[criterion_row_id].sort(key=lambda item: (item.score, item.year_difference is not None and -item.year_difference), reverse=True)

    matched_rows: List[dict] = []
    excluded_short_rows: List[dict] = []
    review_rows: List[dict] = []
    unmatched_rows: List[dict] = []
    skip_collection_sources = load_collection_skip_source_ids()

    for criterion in criterion_rows:
        if criterion.criterion_source_id in skip_collection_sources:
            unmatched_rows.append(unmatched_row(criterion, "collection_container_row; expanded via scriptsNew/resolve_collections.py"))
            continue
        ranked = ranked_by_criterion.get(criterion.criterion_row_id, [])
        bucket = decide_bucket(ranked)
        if bucket == "matched":
            matched_rows.append(candidate_row(criterion, ranked[0], bucket))
        elif bucket == "exclude_short":
            excluded_short_rows.append(candidate_row(criterion, ranked[0], bucket))
        elif bucket == "review":
            if ranked:
                for candidate in ranked[:5]:
                    review_rows.append(candidate_row(criterion, candidate, bucket))
            else:
                unmatched_rows.append(unmatched_row(criterion))
        else:
            unmatched_rows.append(unmatched_row(criterion))

    write_csv(output_dir / "initial_matches.csv", matched_rows)
    write_csv(output_dir / "excluded_shorts_seed.csv", excluded_short_rows)
    write_csv(output_dir / "match_candidates_review.csv", review_rows)
    write_csv(output_dir / "unmatched_initial.csv", unmatched_rows)


if __name__ == "__main__":
    main()
