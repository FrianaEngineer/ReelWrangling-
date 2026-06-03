from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HTML = REPO_ROOT / "outputs" / "eclipse.html"
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "criterion_eclipse_imdb_hints.csv"
DEFAULT_TITLE_BASICS = REPO_ROOT / "data" / "title.basics.tsv"
DEFAULT_TITLE_AKAS = REPO_ROOT / "data" / "title.akas.tsv"
DEFAULT_TITLE_CREW = REPO_ROOT / "data" / "title.crew.tsv"
DEFAULT_NAME_BASICS = REPO_ROOT / "data" / "name.basics.tsv"
ALLOWED_TITLE_TYPES = {"movie", "tvMovie", "video", "tvSpecial", "short"}

PRODUCT_RE = re.compile(
    r'"boxset_films":"(?P<boxset_films>.*?)".*?"directors":"(?P<directors>.*?)".*?"slug":"(?P<slug>boxsets/[^"]+)".*?"title":"(?P<title>Eclipse Series[^"]+)"',
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
COLLECTION_NUMBER_RE = re.compile(r"Eclipse Series\s+(\d+):", re.IGNORECASE)
DIRECTOR_SPLIT_RE = re.compile(r"\s*(?:,| and | & | et | y )\s*", re.IGNORECASE)
ARTICLE_RE = re.compile(r"^(a|an|the)\s+")
PUNCT_RE = re.compile(r"[^a-z0-9]+")
JOINER_RE = re.compile(r"[’'`´]")
WHITESPACE_RE = re.compile(r"\s+")
csv.field_size_limit(sys.maxsize)


@dataclass
class CollectionSeed:
    collection_title: str
    collection_number: int
    collection_url: str
    collection_directors: str
    boxset_films_raw: str


@dataclass
class ImdbRecord:
    tconst: str
    title_type: str
    primary_title: str
    original_title: str
    start_year: str
    genres: str
    directors: list[str] = field(default_factory=list)
    matched_via: set[str] = field(default_factory=set)


@dataclass
class CandidateScore:
    record: ImdbRecord
    score: int
    confidence: str
    candidate_count: int
    matched_via: set[str] = field(default_factory=set)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local IMDb hint rows for Criterion Eclipse collections.")
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--title-basics", type=Path, default=DEFAULT_TITLE_BASICS)
    parser.add_argument("--title-akas", type=Path, default=DEFAULT_TITLE_AKAS)
    parser.add_argument("--title-crew", type=Path, default=DEFAULT_TITLE_CREW)
    parser.add_argument("--name-basics", type=Path, default=DEFAULT_NAME_BASICS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def ascii_fold(text: str) -> str:
    return text.encode("ascii", "ignore").decode("ascii")


def normalize_title(text: str) -> str:
    text = html.unescape((text or "").strip().casefold())
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = JOINER_RE.sub("", text)
    text = ARTICLE_RE.sub("", text)
    text = text.replace("&", " and ")
    text = ascii_fold(text)
    text = PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def normalize_person_name(text: str) -> str:
    tokens = [token for token in normalize_title(text).split() if len(token) > 1]
    return " ".join(tokens)


def strip_html(text: str) -> str:
    return WHITESPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(text or ""))).strip()


def decode_jsonish(value: str) -> str:
    value = value or ""
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return html.unescape(value).replace("\\/", "/")


def extract_collection_number(title: str) -> int | None:
    match = COLLECTION_NUMBER_RE.search(title or "")
    return int(match.group(1)) if match else None


def parse_saved_html(path: Path) -> list[CollectionSeed]:
    html_text = html.unescape(html.unescape(path.read_text(encoding="utf-8")))
    seeds: list[CollectionSeed] = []
    seen_numbers: set[int] = set()
    for match in PRODUCT_RE.finditer(html_text):
        collection_title = strip_html(decode_jsonish(match.group("title")))
        collection_number = extract_collection_number(collection_title)
        if collection_number is None or collection_number in seen_numbers:
            continue
        collection_url = "https://www.criterion.com/" + decode_jsonish(match.group("slug")).lstrip("/")
        seeds.append(
            CollectionSeed(
                collection_title=collection_title,
                collection_number=collection_number,
                collection_url=collection_url,
                collection_directors=strip_html(decode_jsonish(match.group("directors"))),
                boxset_films_raw=strip_html(decode_jsonish(match.group("boxset_films"))),
            )
        )
        seen_numbers.add(collection_number)
    return sorted(seeds, key=lambda seed: seed.collection_number)


def split_raw_parts(boxset_films_raw: str) -> list[str]:
    return [part.strip() for part in boxset_films_raw.split(",") if part.strip()]


def possible_title_keys(collections: list[CollectionSeed]) -> set[str]:
    keys: set[str] = set()
    for collection in collections:
        parts = split_raw_parts(collection.boxset_films_raw)
        for start in range(len(parts)):
            for width in range(1, min(4, len(parts) - start) + 1):
                candidate = ", ".join(part.strip() for part in parts[start : start + width]).strip()
                normalized_candidate = normalize_title(candidate)
                if normalized_candidate:
                    keys.add(normalized_candidate)
    return keys


def load_basics(
    path: Path,
    target_title_keys: set[str],
) -> tuple[dict[str, ImdbRecord], dict[str, dict[str, set[str]]]]:
    records: dict[str, ImdbRecord] = {}
    title_index: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["titleType"] not in ALLOWED_TITLE_TYPES:
                continue
            normalized_primary = normalize_title(row["primaryTitle"])
            normalized_original = normalize_title(row["originalTitle"])
            if normalized_primary not in target_title_keys and normalized_original not in target_title_keys:
                continue
            record = ImdbRecord(
                tconst=row["tconst"],
                title_type=row["titleType"],
                primary_title=row["primaryTitle"],
                original_title=row["originalTitle"],
                start_year=row["startYear"],
                genres=row["genres"],
            )
            records[record.tconst] = record
            title_index[normalized_primary]["primary"].add(record.tconst)
            title_index[normalized_original]["original"].add(record.tconst)
    return records, title_index


def load_akas(
    path: Path,
    basics_path: Path,
    target_title_keys: set[str],
    records: dict[str, ImdbRecord],
    title_index: dict[str, dict[str, set[str]]],
) -> None:
    needed_tconsts: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            normalized_aka = normalize_title(row["title"])
            if normalized_aka not in target_title_keys:
                continue
            title_id = row["titleId"]
            needed_tconsts.add(title_id)
            title_index[normalized_aka]["aka"].add(title_id)

    missing_tconsts = needed_tconsts.difference(records)
    if not missing_tconsts:
        return

    with basics_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["tconst"] not in missing_tconsts or row["titleType"] not in ALLOWED_TITLE_TYPES:
                continue
            records[row["tconst"]] = ImdbRecord(
                tconst=row["tconst"],
                title_type=row["titleType"],
                primary_title=row["primaryTitle"],
                original_title=row["originalTitle"],
                start_year=row["startYear"],
                genres=row["genres"],
            )


def load_directors(crew_path: Path, names_path: Path, records: dict[str, ImdbRecord]) -> None:
    needed_tconsts = set(records)
    director_ids_by_tconst: dict[str, list[str]] = {}
    needed_names: set[str] = set()
    with crew_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["tconst"] not in needed_tconsts:
                continue
            director_ids = [] if row["directors"] == r"\N" else [value for value in row["directors"].split(",") if value]
            director_ids_by_tconst[row["tconst"]] = director_ids
            needed_names.update(director_ids)
    name_by_nconst: dict[str, str] = {}
    with names_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row["nconst"] in needed_names:
                name_by_nconst[row["nconst"]] = row["primaryName"]
    for tconst, director_ids in director_ids_by_tconst.items():
        records[tconst].directors = [name_by_nconst[nconst] for nconst in director_ids if nconst in name_by_nconst]


def split_collection_directors(value: str) -> set[str]:
    return {normalize_person_name(part) for part in DIRECTOR_SPLIT_RE.split(value or "") if normalize_person_name(part)}


def title_candidates(normalized_title: str, title_index: dict[str, dict[str, set[str]]]) -> tuple[set[str], set[str]]:
    entries = title_index.get(normalized_title, {})
    matched_tconsts: set[str] = set()
    matched_via: set[str] = set()
    for source, tconsts in entries.items():
        if tconsts:
            matched_tconsts.update(tconsts)
            matched_via.add(source)
    return matched_tconsts, matched_via


def choose_fragment_merge(parts: list[str], start: int, title_index: dict[str, dict[str, set[str]]]) -> tuple[str, int]:
    max_window = min(4, len(parts) - start)
    for width in range(max_window, 0, -1):
        candidate = ", ".join(part.strip() for part in parts[start : start + width]).strip()
        if not candidate:
            continue
        matched_tconsts, _ = title_candidates(normalize_title(candidate), title_index)
        if matched_tconsts:
            return candidate, width
    return parts[start].strip(), 1


def parse_boxset_film_titles(boxset_films_raw: str, title_index: dict[str, dict[str, set[str]]]) -> list[str]:
    parts = split_raw_parts(boxset_films_raw)
    titles: list[str] = []
    index = 0
    while index < len(parts):
        title, width = choose_fragment_merge(parts, index, title_index)
        titles.append(title)
        index += width
    return titles


def score_record(
    parsed_title: str,
    record: ImdbRecord,
    matched_via: set[str],
    collection_directors: set[str],
    candidate_count: int,
) -> CandidateScore:
    score = 0
    normalized_parsed = normalize_title(parsed_title)
    if normalize_title(record.primary_title) == normalized_parsed:
        score += 50
    elif normalize_title(record.original_title) == normalized_parsed:
        score += 44

    if "aka" in matched_via:
        score += 18
    if "primary" in matched_via or "original" in matched_via:
        score += 12

    if record.title_type == "movie":
        score += 20
    elif record.title_type in {"tvMovie", "video", "tvSpecial"}:
        score += 10
    elif record.title_type == "short":
        score += 4

    imdb_directors = {normalize_person_name(name) for name in record.directors if normalize_person_name(name)}
    if collection_directors and imdb_directors and collection_directors & imdb_directors:
        score += 14

    if (record.start_year or "").isdigit():
        score += 2

    confidence = "low"
    if candidate_count == 1 and score >= 70:
        confidence = "high"
    elif score >= 60:
        confidence = "medium"
    return CandidateScore(
        record=record,
        score=score,
        confidence=confidence,
        candidate_count=candidate_count,
        matched_via=set(matched_via),
    )


def best_match_for_title(
    parsed_title: str,
    collection_directors: set[str],
    title_index: dict[str, dict[str, set[str]]],
    records: dict[str, ImdbRecord],
) -> CandidateScore | None:
    normalized_parsed = normalize_title(parsed_title)
    matched_tconsts, matched_via = title_candidates(normalized_parsed, title_index)
    if not matched_tconsts:
        return None
    scored = [
        score_record(parsed_title, records[tconst], matched_via, collection_directors, len(matched_tconsts))
        for tconst in matched_tconsts
    ]
    scored.sort(
        key=lambda candidate: (
            candidate.score,
            1 if candidate.record.title_type == "movie" else 0,
            int(candidate.record.start_year) if (candidate.record.start_year or "").isdigit() else -1,
        ),
        reverse=True,
    )
    return scored[0]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(rows[0].keys()) if rows else [
            "collection_title",
            "collection_number",
            "collection_url",
            "collection_directors",
            "movie_order_in_collection",
            "parsed_movie_title",
            "movie_title",
            "movie_year",
            "imdb_id",
            "imdb_primary_title",
            "imdb_original_title",
            "imdb_title_type",
            "imdb_directors",
            "match_confidence",
            "candidate_count",
            "matched_via",
            "boxset_films_raw",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    collections = parse_saved_html(args.html)
    target_title_keys = possible_title_keys(collections)
    records, title_index = load_basics(args.title_basics, target_title_keys)

    rows: list[dict] = []
    for collection in collections:
        directors = split_collection_directors(collection.collection_directors)
        parsed_titles = parse_boxset_film_titles(collection.boxset_films_raw, title_index)
        for order, parsed_title in enumerate(parsed_titles, start=1):
            best = best_match_for_title(parsed_title, directors, title_index, records)
            rows.append(
                {
                    "collection_title": collection.collection_title,
                    "collection_number": collection.collection_number,
                    "collection_url": collection.collection_url,
                    "collection_directors": collection.collection_directors,
                    "movie_order_in_collection": order,
                    "parsed_movie_title": parsed_title,
                    "movie_title": best.record.primary_title if best else parsed_title,
                    "movie_year": best.record.start_year if best else "",
                    "imdb_id": best.record.tconst if best else "",
                    "imdb_primary_title": best.record.primary_title if best else "",
                    "imdb_original_title": best.record.original_title if best else "",
                    "imdb_title_type": best.record.title_type if best else "",
                    "imdb_directors": " | ".join(best.record.directors) if best else "",
                    "match_confidence": best.confidence if best else "unmatched",
                    "candidate_count": best.candidate_count if best else 0,
                    "matched_via": ",".join(sorted(best.matched_via)) if best else "",
                    "boxset_films_raw": collection.boxset_films_raw,
                }
            )

    write_csv(args.output, rows)
    print(f"collections: {len(collections)}")
    print(f"hint rows: {len(rows)}")
    print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
