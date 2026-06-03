from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

from src.criterion.collection_helpers import extract_constituent_titles
from src.criterion.collection_manifest import KNOWN_COLLECTIONS
from src.shared.normalize_titles import normalize_title
from src.shared.utils import ensure_output_dir, parse_year, timestamp_utc, write_csv


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMDB_DIR = REPO_ROOT / "data" / "imdb"
ALLOWED_TITLE_TYPES = {"movie", "tvMovie", "video", "tvSpecial", "tvMiniSeries"}
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


@dataclass
class Candidate:
    constituent_title: str
    imdb_id: str
    title_type: str
    primary_title: str
    original_title: str
    start_year: str
    runtime_minutes: str
    genres: str
    matched_via: Set[str] = field(default_factory=set)
    score: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve one collection title into constituent titles and best IMDb matches.")
    parser.add_argument("--collection-title", required=True)
    parser.add_argument("--title-basics", default=str(DEFAULT_IMDB_DIR / "title.basics.tsv"))
    parser.add_argument("--title-akas", default=str(DEFAULT_IMDB_DIR / "title.akas.tsv"))
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "data" / "output" / "collection_lookup"))
    parser.add_argument("--output-stem", default="")
    return parser.parse_args()


def exact_key(value: str) -> str:
    return (value or "").strip().casefold()


def output_stem_for(title: str) -> str:
    normalized = normalize_title(title).replace(" ", "_")
    return normalized or "collection_lookup"


def extract_titles(collection_title: str) -> Tuple[List[str], str]:
    normalized = normalize_title(collection_title)
    if normalized in KNOWN_COLLECTIONS:
        return KNOWN_COLLECTIONS[normalized], "known_collection_map"
    return extract_constituent_titles(collection_title)


def add_candidate(candidates: Dict[Tuple[str, str], Candidate], constituent_title: str, meta: ImdbMeta, matched_via: str) -> None:
    key = (constituent_title, meta.tconst)
    if key not in candidates:
        candidates[key] = Candidate(
            constituent_title=constituent_title,
            imdb_id=meta.tconst,
            title_type=meta.title_type,
            primary_title=meta.primary_title,
            original_title=meta.original_title,
            start_year=meta.start_year,
            runtime_minutes=meta.runtime_minutes,
            genres=meta.genres,
        )
    candidates[key].matched_via.add(matched_via)


def build_indexes(titles: List[str]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    exact_index: Dict[str, List[str]] = defaultdict(list)
    normalized_index: Dict[str, List[str]] = defaultdict(list)
    for title in titles:
        exact_index[exact_key(title)].append(title)
        normalized_index[normalize_title(title)].append(title)
    return exact_index, normalized_index


def score_candidate(candidate: Candidate) -> None:
    if "title_exact" in candidate.matched_via or "aka_exact" in candidate.matched_via:
        candidate.score += 50
    if "title_normalized" in candidate.matched_via or "aka_normalized" in candidate.matched_via:
        candidate.score += 25
    if candidate.title_type == "movie":
        candidate.score += 20
    elif candidate.title_type in {"tvMovie", "video", "tvMiniSeries"}:
        candidate.score += 10
    if parse_year(candidate.start_year) is not None:
        candidate.score += 5
    runtime = parse_year(candidate.runtime_minutes)
    if runtime is not None and runtime >= 41:
        candidate.score += 10
    if "Short" in candidate.genres.split(","):
        candidate.score -= 20


def stream_matches(title_basics: Path, title_akas: Path, constituent_titles: List[str]) -> Dict[str, List[Candidate]]:
    exact_index, normalized_index = build_indexes(constituent_titles)
    candidates: Dict[Tuple[str, str], Candidate] = {}
    meta_by_tconst: Dict[str, ImdbMeta] = {}

    with title_basics.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["titleType"] not in ALLOWED_TITLE_TYPES:
                continue
            meta = ImdbMeta(
                tconst=row["tconst"],
                title_type=row["titleType"],
                primary_title=row["primaryTitle"],
                original_title=row["originalTitle"],
                start_year=row["startYear"],
                runtime_minutes=row["runtimeMinutes"],
                genres=row["genres"],
            )
            meta_by_tconst[meta.tconst] = meta
            exact_titles = {exact_key(meta.primary_title), exact_key(meta.original_title)}
            normalized_titles = {normalize_title(meta.primary_title), normalize_title(meta.original_title)}
            for title_key in exact_titles:
                for constituent_title in exact_index.get(title_key, []):
                    add_candidate(candidates, constituent_title, meta, "title_exact")
            for title_key in normalized_titles:
                for constituent_title in normalized_index.get(title_key, []):
                    add_candidate(candidates, constituent_title, meta, "title_normalized")

    with title_akas.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            matched_titles: Set[str] = set()
            matched_via: Set[str] = set()
            for constituent_title in exact_index.get(exact_key(row["title"]), []):
                matched_titles.add(constituent_title)
                matched_via.add("aka_exact")
            for constituent_title in normalized_index.get(normalize_title(row["title"]), []):
                matched_titles.add(constituent_title)
                matched_via.add("aka_normalized")
            if not matched_titles or row["titleId"] not in meta_by_tconst:
                continue
            for constituent_title in matched_titles:
                for via in matched_via:
                    add_candidate(candidates, constituent_title, meta_by_tconst[row["titleId"]], via)

    grouped: Dict[str, List[Candidate]] = defaultdict(list)
    for candidate in candidates.values():
        score_candidate(candidate)
        grouped[candidate.constituent_title].append(candidate)
    for title in grouped:
        grouped[title].sort(key=lambda candidate: candidate.score, reverse=True)
    return grouped


def best_match_row(collection_title: str, extraction_method: str, sequence: int, constituent_title: str, candidates: List[Candidate]) -> dict:
    best = candidates[0] if candidates else None
    return {
        "collection_title_original": collection_title,
        "extraction_method": extraction_method,
        "constituent_sequence": sequence,
        "constituent_title_original": constituent_title,
        "constituent_title_normalized": normalize_title(constituent_title),
        "imdb_id": best.imdb_id if best else "",
        "imdb_primary_title": best.primary_title if best else "",
        "imdb_original_title": best.original_title if best else "",
        "imdb_title_type": best.title_type if best else "",
        "imdb_start_year": best.start_year if best else "",
        "imdb_runtime_minutes": best.runtime_minutes if best else "",
        "imdb_genres": best.genres if best else "",
        "matched_via": " | ".join(sorted(best.matched_via)) if best else "",
        "match_score": best.score if best else "",
        "match_status": "matched" if best else "no_match_found",
        "generated_at": timestamp_utc(),
    }


def candidate_rows(collection_title: str, extraction_method: str, sequence: int, constituent_title: str, candidates: List[Candidate]) -> List[dict]:
    rows: List[dict] = []
    for rank, candidate in enumerate(candidates, start=1):
        rows.append(
            {
                "collection_title_original": collection_title,
                "extraction_method": extraction_method,
                "constituent_sequence": sequence,
                "constituent_title_original": constituent_title,
                "candidate_rank": rank,
                "imdb_id": candidate.imdb_id,
                "imdb_primary_title": candidate.primary_title,
                "imdb_original_title": candidate.original_title,
                "imdb_title_type": candidate.title_type,
                "imdb_start_year": candidate.start_year,
                "imdb_runtime_minutes": candidate.runtime_minutes,
                "imdb_genres": candidate.genres,
                "matched_via": " | ".join(sorted(candidate.matched_via)),
                "match_score": candidate.score,
                "generated_at": timestamp_utc(),
            }
        )
    return rows


def main() -> None:
    args = parse_args()
    collection_title = args.collection_title.strip()
    constituent_titles, extraction_method = extract_titles(collection_title)
    output_dir = ensure_output_dir(Path(args.output_dir))
    stem = args.output_stem.strip() or output_stem_for(collection_title)

    best_rows: List[dict] = []
    review_rows: List[dict] = []

    if constituent_titles:
        grouped_candidates = stream_matches(Path(args.title_basics), Path(args.title_akas), constituent_titles)
        for index, constituent_title in enumerate(constituent_titles, start=1):
            candidates = grouped_candidates.get(constituent_title, [])
            best_rows.append(best_match_row(collection_title, extraction_method, index, constituent_title, candidates))
            review_rows.extend(candidate_rows(collection_title, extraction_method, index, constituent_title, candidates[:10]))
    else:
        best_rows.append(
            {
                "collection_title_original": collection_title,
                "extraction_method": extraction_method,
                "constituent_sequence": "",
                "constituent_title_original": "",
                "constituent_title_normalized": "",
                "imdb_id": "",
                "imdb_primary_title": "",
                "imdb_original_title": "",
                "imdb_title_type": "",
                "imdb_start_year": "",
                "imdb_runtime_minutes": "",
                "imdb_genres": "",
                "matched_via": "",
                "match_score": "",
                "match_status": "no_constituent_titles_extracted",
                "generated_at": timestamp_utc(),
            }
        )

    write_csv(output_dir / f"{stem}_best_matches.csv", best_rows)
    write_csv(output_dir / f"{stem}_candidate_review.csv", review_rows)


if __name__ == "__main__":
    main()
