#!/usr/bin/env python3

from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

csv.field_size_limit(10_000_000)


ROOT = Path("/Users/friana/ReelWrangling")
DATA = ROOT / "data"
OUTPUT = DATA / "output"

CRITERION_CSV = DATA / "criterion" / "criterion_films.csv"
TITLE_BASICS_TSV = DATA / "imdb" / "title.basics.tsv"
TITLE_AKAS_TSV = DATA / "imdb" / "title.akas.tsv"
TITLE_CREW_TSV = DATA / "imdb" / "title.crew.tsv"
TITLE_PRINCIPALS_TSV = DATA / "imdb" / "title.principals.tsv"
NAME_BASICS_TSV = DATA / "imdb" / "name.basics.tsv"

BASIC_INFO_CSV = OUTPUT / "criterion_basic_info.csv"
UNMATCHED_CSV = OUTPUT / "criterion_unmatched_films.csv"

TITLE_BUCKET = 45.0
DIRECTOR_BUCKET = 35.0
YEAR_BUCKET = 15.0
TYPE_BUCKET = 5.0
AUTO_ACCEPT_SCORE = 85.0
AUTO_ACCEPT_MARGIN = 15.0

STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "de",
    "des",
    "du",
    "episode",
    "for",
    "in",
    "la",
    "le",
    "les",
    "of",
    "on",
    "or",
    "part",
    "the",
    "to",
    "with",
}

PUNCT_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2044": "/",
        "\u00a0": " ",
    }
)

ARTICLE_RE = re.compile(r"^(the|a|an)\s+(.+)$", re.IGNORECASE)
EPISODE_RE = re.compile(r"\bepisode\s+(\d+)\b", re.IGNORECASE)
ROMAN_SUFFIX_RE = re.compile(r"(st|nd|rd|th)$")
PAREN_RE = re.compile(r"\([^)]*\)")
BRACKET_RE = re.compile(r"\[[^]]*\]")
VERSION_RE = re.compile(
    r"\b(english dubbed version|dubbed version|black and white version|comprehensive version|excerpt|parts?\s+\d+(?:\s*&\s*\d+)?)\b",
    re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"\s+")

ROMAN_MAP = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
    "xiii": 13,
    "xiv": 14,
    "xv": 15,
    "xvi": 16,
    "xvii": 17,
    "xviii": 18,
    "xix": 19,
    "xx": 20,
}


def clean(value: str) -> str:
    return "" if value == "\\N" else value


def normalize_ascii(text: str) -> str:
    text = (text or "").translate(PUNCT_TRANSLATION)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_token(token: str) -> str:
    token = ROMAN_SUFFIX_RE.sub("", token.lower())
    return str(ROMAN_MAP[token]) if token in ROMAN_MAP else token


def canonical_tokens(text: str) -> list[str]:
    text = normalize_ascii(text).lower().replace("&", " and ")
    return [normalize_token(part) for part in re.split(r"[^a-z0-9]+", text) if part]


def strict_norm(text: str) -> str:
    return " ".join(canonical_tokens(text))


def loose_norm(text: str) -> str:
    value = strict_norm(text)
    value = re.sub(r"\b(the|a|an)\b", " ", value)
    value = WHITESPACE_RE.sub(" ", value)
    return value.strip()


def token_set(text: str) -> set[str]:
    return {tok for tok in canonical_tokens(text) if tok not in STOPWORDS}


def canonical_title_base(text: str) -> str:
    text = normalize_ascii(text).lower()
    text = PAREN_RE.sub(" ", text)
    text = BRACKET_RE.sub(" ", text)
    text = VERSION_RE.sub(" ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9:]+", " ", text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def canonical_title_variants(text: str) -> set[str]:
    base = canonical_title_base(text)
    variants = {base} if base else set()
    if not base:
        return variants
    collapsed = loose_norm(base)
    if collapsed:
        variants.add(collapsed)
    article_match = ARTICLE_RE.match(base)
    if article_match:
        variants.add(f"{article_match.group(2)} {article_match.group(1)}".strip())
    if ":" in base:
        head, tail = [part.strip() for part in base.split(":", 1)]
        if head:
            variants.add(head)
        if tail:
            variants.add(tail)
    if " part " in base:
        variants.add(re.sub(r"\bpart\b", "", base).strip())
    if " episode " in base:
        variants.add(re.sub(r"\bepisode\b", "", base).strip())
    return {WHITESPACE_RE.sub(" ", variant).strip() for variant in variants if variant.strip()}


def canonical_title_tokens(text: str) -> set[str]:
    tokens = set()
    for variant in canonical_title_variants(text):
        tokens.update(tok for tok in canonical_tokens(variant) if tok not in STOPWORDS)
    return tokens


def parse_year(value: str) -> int | None:
    try:
        return int(float(value))
    except Exception:
        return None


def parse_episode_number(text: str) -> int | None:
    m = EPISODE_RE.search(text or "")
    return int(m.group(1)) if m else None


def director_parts(text: str) -> set[str]:
    parts = set()
    for part in re.split(r"\band\b|&|,|/|;", text or "", flags=re.IGNORECASE):
        part = loose_norm(part)
        if part:
            parts.add(part)
    whole = loose_norm(text)
    if whole:
        parts.add(whole)
    return parts


def director_variants(text: str) -> set[str]:
    variants = set()
    for part in director_parts(text):
        variants.add(part)
        tokens = part.split()
        if len(tokens) >= 2:
            variants.add(f"{tokens[-1]} {' '.join(tokens[:-1])}".strip())
        variants.add("".join(tokens))
    return {variant for variant in variants if variant}


def surname_set(text: str) -> set[str]:
    names = set()
    for part in director_parts(text):
        tokens = part.split()
        if tokens:
            names.add(tokens[-1])
    return names


def best_ratio(left: set[str], right: set[str]) -> float:
    best = 0.0
    for lval in left:
        for rval in right:
            best = max(best, SequenceMatcher(None, lval, rval).ratio())
    return best


def director_similarity(criterion_director: str, imdb_director_names: list[str]) -> float:
    crit_variants = director_variants(criterion_director)
    imdb_variants = set()
    for name in imdb_director_names:
        imdb_variants.update(director_variants(name))
    if not crit_variants or not imdb_variants:
        return 0.0
    return best_ratio(crit_variants, imdb_variants)


def director_match_status(
    criterion_director_norms: set[str],
    criterion_director_surnames: set[str],
    imdb_director_norms: set[str],
    imdb_director_surnames: set[str],
) -> str:
    if not imdb_director_norms:
        return "no_imdb_director"
    if criterion_director_norms & imdb_director_norms:
        return "exact_or_split_match"
    if criterion_director_surnames & imdb_director_surnames:
        return "surname_match"
    return "mismatch"


def article_variants(text: str) -> set[str]:
    text = (text or "").strip()
    variants = {text}
    m = ARTICLE_RE.match(text)
    if m:
        variants.add(f"{m.group(2)}, {m.group(1).title()}")
    elif "," in text:
        head, tail = [part.strip() for part in text.rsplit(",", 1)]
        if tail.lower() in {"the", "a", "an"}:
            variants.add(f"{tail} {head}")
    return {variant for variant in variants if variant}


def title_variants(text: str) -> set[str]:
    variants = set()
    for article_variant in article_variants(text):
        variants.add(article_variant)
        if ":" in article_variant:
            head, tail = article_variant.split(":", 1)
            variants.add(head.strip())
            variants.add(tail.strip())
    return {variant for variant in variants if variant}


def title_similarity(a: str, b: str) -> float:
    a_variants = canonical_title_variants(a)
    b_variants = canonical_title_variants(b)
    if not a_variants or not b_variants:
        return 0.0
    return best_ratio(a_variants, b_variants)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def title_points(
    strict_match: bool,
    loose_match: bool,
    similarity: float,
    overlap: float,
    aka: dict[str, str] | None,
) -> tuple[float, list[str]]:
    evidence = []
    exact_component = 1.0 if strict_match else 0.85 if loose_match else 0.0
    fuzzy_component = (similarity + overlap) / 2.0
    aka_component = 0.0
    if aka:
        if aka["aka_language"] == "en":
            aka_component = 1.0
            evidence.append("english-aka")
        elif aka["aka_region"] in {"US", "GB", "CA", "AU", "NZ"}:
            aka_component = 0.9
            evidence.append("regional-aka")
    combined = max(exact_component, fuzzy_component, aka_component if (exact_component > 0 or fuzzy_component > 0) else 0.0)
    points = TITLE_BUCKET * combined
    if strict_match:
        evidence.append("strict-title")
    elif loose_match:
        evidence.append("loose-title")
    if similarity >= 0.90:
        evidence.append("title-high-similarity")
    elif similarity >= 0.80:
        evidence.append("title-medium-similarity")
    if overlap >= 0.85:
        evidence.append("title-high-overlap")
    return points, evidence


def year_points(criterion_year: int | None, imdb_year: int | None) -> tuple[float, list[str]]:
    if criterion_year is None or imdb_year is None:
        return 0.0, []
    diff = abs(criterion_year - imdb_year)
    if diff == 0:
        return YEAR_BUCKET, ["same-year"]
    if diff == 1:
        return YEAR_BUCKET * 0.8, ["year+/-1"]
    if diff == 2:
        return YEAR_BUCKET * 0.55, ["year+/-2"]
    if diff == 3:
        return YEAR_BUCKET * 0.25, ["year+/-3"]
    return 0.0, []


def director_points(
    criterion_director_norms: set[str],
    criterion_director_surnames: set[str],
    imdb_director_norms: set[str],
    imdb_director_surnames: set[str],
) -> tuple[float, list[str]]:
    if not imdb_director_norms:
        return 0.0, []
    if criterion_director_norms & imdb_director_norms:
        return DIRECTOR_BUCKET, ["director-match"]
    if criterion_director_surnames & imdb_director_surnames:
        return DIRECTOR_BUCKET * 0.6, ["director-surname"]
    return 0.0, []


def type_points(criterion_episode_number: int | None, title_type: str, imdb_episode_number: int | None) -> tuple[float, list[str]]:
    evidence = []
    points = 0.0
    if criterion_episode_number is not None:
        if title_type == "tvEpisode":
            points += TYPE_BUCKET * 0.6
            evidence.append("episode-type")
        elif title_type in {"movie", "short", "tvMovie"}:
            points += TYPE_BUCKET * 0.2
        if imdb_episode_number is not None and imdb_episode_number == criterion_episode_number:
            points += TYPE_BUCKET * 0.4
            evidence.append("episode-number")
        return min(TYPE_BUCKET, points), evidence
    if title_type in {"movie", "short", "tvMovie"}:
        return TYPE_BUCKET, ["plausible-type"]
    if title_type == "tvEpisode":
        return TYPE_BUCKET * 0.3, ["episode-type"]
    return 0.0, []


@dataclass
class CriterionRow:
    row_id: int
    title: str
    director: str
    country: str
    year: str
    strict_title: str
    loose_title: str
    title_tokens: set[str]
    canonical_title_tokens: set[str]
    director_norms: set[str]
    director_surnames: set[str]
    director_variant_norms: set[str]
    episode_number: int | None


def load_criterion_rows() -> list[CriterionRow]:
    rows = []
    with CRITERION_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            title = row["title"].strip()
            director = row["director"].strip()
            rows.append(
                CriterionRow(
                    row_id=idx,
                    title=title,
                    director=director,
                    country=row["country"].strip(),
                    year=row["year"].strip(),
                    strict_title=strict_norm(title),
                    loose_title=loose_norm(title),
                    title_tokens=token_set(title),
                    canonical_title_tokens=canonical_title_tokens(title),
                    director_norms=director_parts(director),
                    director_surnames=surname_set(director),
                    director_variant_norms=director_variants(director),
                    episode_number=parse_episode_number(title),
                )
            )
    return rows


def assign_row_ids(rows: list[dict[str, str]], criterion_rows: list[CriterionRow]) -> list[dict[str, str]]:
    key_to_ids = defaultdict(list)
    for row in criterion_rows:
        key_to_ids[(row.title, row.director, row.country, row.year)].append(row.row_id)
    used = Counter()
    assigned = []
    for row in rows:
        key = (
            row["title"],
            row.get("criterion_director", row.get("director", "")),
            row.get("criterion_country", row.get("country", "")),
            row.get("criterion_year", row.get("year", "")),
        )
        index = used[key]
        if index < len(key_to_ids[key]):
            row = dict(row)
            row["row_id"] = str(key_to_ids[key][index])
            assigned.append(row)
            used[key] += 1
    return assigned


def load_first_pass_matches(criterion_rows: list[CriterionRow]) -> dict[int, dict[str, str]]:
    with BASIC_INFO_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assigned = assign_row_ids(rows, criterion_rows)
    return {int(row["row_id"]): row for row in assigned}


def load_first_pass_unmatched(criterion_rows: list[CriterionRow]) -> list[CriterionRow]:
    with UNMATCHED_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assigned = assign_row_ids(rows, criterion_rows)
    unmatched_ids = {int(row["row_id"]) for row in assigned}
    return [row for row in criterion_rows if row.row_id in unmatched_ids]


def build_exact_indexes(rows: list[CriterionRow]) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    strict_index = defaultdict(set)
    loose_index = defaultdict(set)
    for row in rows:
        for variant in title_variants(row.title):
            s_norm = strict_norm(variant)
            l_norm = loose_norm(variant)
            if s_norm:
                strict_index[s_norm].add(row.row_id)
            if l_norm:
                loose_index[l_norm].add(row.row_id)
    return strict_index, loose_index


def build_token_index(rows: list[CriterionRow]) -> dict[str, set[int]]:
    index = defaultdict(set)
    for row in rows:
        for token in row.canonical_title_tokens:
            if len(token) >= 4:
                index[token].add(row.row_id)
    return index


def collect_exact_candidates(unmatched_rows: list[CriterionRow]) -> tuple[dict[tuple[int, str], dict[str, str]], dict[str, dict[str, str]], dict[tuple[int, str], dict[str, str]]]:
    strict_index, loose_index = build_exact_indexes(unmatched_rows)
    candidates = {}
    basics = {}
    aka_hits = {}

    def consider_title(row_ids: set[int], tconst: str, imdb_title: str, source: str) -> None:
        for row_id in row_ids:
            key = (row_id, tconst)
            s_match = strict_norm(imdb_title) == strict_norm_by_id[row_id]
            l_match = loose_norm(imdb_title) == loose_norm_by_id[row_id]
            entry = {
                "row_id": str(row_id),
                "tconst": tconst,
                "matched_title_variant": imdb_title,
                "source": source,
                "strict_match": "1" if s_match else "0",
                "loose_match": "1" if l_match else "0",
                "title_similarity": f"{title_similarity(title_by_id[row_id], imdb_title):.4f}",
                "token_overlap": f"{jaccard(tokens_by_id[row_id], canonical_title_tokens(imdb_title)):.4f}",
            }
            prev = candidates.get(key)
            if prev is None or (entry["strict_match"], entry["loose_match"], entry["title_similarity"], entry["token_overlap"]) > (
                prev["strict_match"],
                prev["loose_match"],
                prev["title_similarity"],
                prev["token_overlap"],
            ):
                candidates[key] = entry

    title_by_id = {row.row_id: row.title for row in unmatched_rows}
    strict_norm_by_id = {row.row_id: row.strict_title for row in unmatched_rows}
    loose_norm_by_id = {row.row_id: row.loose_title for row in unmatched_rows}
    tokens_by_id = {row.row_id: row.canonical_title_tokens for row in unmatched_rows}

    with TITLE_BASICS_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tconst = row["tconst"]
            primary = clean(row["primaryTitle"])
            original = clean(row["originalTitle"])
            row_ids = set()
            for title in (primary, original):
                if not title:
                    continue
                for variant in title_variants(title):
                    s_norm = strict_norm(variant)
                    l_norm = loose_norm(variant)
                    row_ids.update(strict_index.get(s_norm, set()))
                    row_ids.update(loose_index.get(l_norm, set()))
            if not row_ids:
                continue
            basics[tconst] = {
                "tt_identifier": tconst,
                "title_type": clean(row["titleType"]),
                "runtime_minutes": clean(row["runtimeMinutes"]),
                "year": clean(row["startYear"]),
                "primary_title": primary,
                "original_title": original,
            }
            for title, source in ((primary, "primary"), (original, "original")):
                if title:
                    consider_title(row_ids, tconst, title, source)

    with TITLE_AKAS_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            aka_title = clean(row["title"])
            if not aka_title:
                continue
            row_ids = set()
            for variant in title_variants(aka_title):
                row_ids.update(strict_index.get(strict_norm(variant), set()))
                row_ids.update(loose_index.get(loose_norm(variant), set()))
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
            consider_title(row_ids, tconst, aka_title, "aka")

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

    return candidates, basics, aka_hits


def collect_fuzzy_review_candidates(
    unmatched_rows: list[CriterionRow],
    exact_candidates: dict[tuple[int, str], dict[str, str]],
) -> dict[tuple[int, str], dict[str, str]]:
    unresolved_ids = {row.row_id for row in unmatched_rows}
    unresolved_ids -= {row_id for row_id, _ in exact_candidates}
    if not unresolved_ids:
        return {}

    rows_by_id = {row.row_id: row for row in unmatched_rows if row.row_id in unresolved_ids}
    token_index = build_token_index(list(rows_by_id.values()))
    fuzzy_candidates = {}

    with TITLE_BASICS_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            imdb_year = parse_year(clean(row["startYear"]))
            for title, source in ((clean(row["primaryTitle"]), "primary_fuzzy"), (clean(row["originalTitle"]), "original_fuzzy")):
                if not title:
                    continue
                title_tokens = {token for token in canonical_title_tokens(title) if len(token) >= 4}
                if len(title_tokens) < 2:
                    continue
                overlap_counts = Counter()
                for token in title_tokens:
                    overlap_counts.update(token_index.get(token, set()))
                if not overlap_counts:
                    continue
                for row_id, overlap_count in overlap_counts.items():
                    if overlap_count < 2:
                        continue
                    crit = rows_by_id[row_id]
                    crit_year = parse_year(crit.year)
                    if crit_year is not None and imdb_year is not None and abs(crit_year - imdb_year) > 2:
                        continue
                    sim = title_similarity(crit.title, title)
                    overlap = jaccard(crit.canonical_title_tokens, canonical_title_tokens(title))
                    if sim < 0.72 and overlap < 0.55:
                        continue
                    key = (row_id, row["tconst"])
                    entry = {
                        "row_id": str(row_id),
                        "tconst": row["tconst"],
                        "matched_title_variant": title,
                        "source": source,
                        "strict_match": "0",
                        "loose_match": "0",
                        "title_similarity": f"{sim:.4f}",
                        "token_overlap": f"{overlap:.4f}",
                    }
                    prev = fuzzy_candidates.get(key)
                    if prev is None or (entry["title_similarity"], entry["token_overlap"]) > (prev["title_similarity"], prev["token_overlap"]):
                        fuzzy_candidates[key] = entry
    return fuzzy_candidates


def score_candidates(
    unmatched_rows: list[CriterionRow],
    candidates: dict[tuple[int, str], dict[str, str]],
    basics: dict[str, dict[str, str]],
    aka_hits: dict[tuple[int, str], dict[str, str]],
) -> tuple[dict[int, dict[str, str]], list[dict[str, str]]]:
    rows_by_id = {row.row_id: row for row in unmatched_rows}
    candidate_tconsts = {tconst for _, tconst in candidates}
    crew_by_tconst = {}
    director_ids = set()

    with TITLE_CREW_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tconst = row["tconst"]
            if tconst not in candidate_tconsts:
                continue
            directors = clean(row["directors"])
            writers = clean(row["writers"])
            crew_by_tconst[tconst] = {"directors": directors, "writers": writers}
            if directors:
                director_ids.update(directors.split(","))

    director_names = {}
    with NAME_BASICS_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row["nconst"] in director_ids:
                director_names[row["nconst"]] = clean(row["primaryName"])

    ranked = defaultdict(list)
    auto_matches = {}

    for (row_id, tconst), cand in candidates.items():
        crit = rows_by_id[row_id]
        basic = basics.get(tconst)
        if basic is None:
            continue
        sim = float(cand["title_similarity"])
        overlap = float(cand["token_overlap"])
        score = 0.0
        evidence = []
        aka = aka_hits.get((row_id, tconst))
        points, ev = title_points(cand["strict_match"] == "1", cand["loose_match"] == "1", sim, overlap, aka)
        score += points
        evidence.extend(ev)

        imdb_year = parse_year(basic["year"])
        crit_year = parse_year(crit.year)
        points, ev = year_points(crit_year, imdb_year)
        score += points
        evidence.extend(ev)

        title_type = basic["title_type"]
        director_ids_for_title = crew_by_tconst.get(tconst, {}).get("directors", "")
        director_norms = {loose_norm(director_names.get(nconst, "")) for nconst in director_ids_for_title.split(",") if nconst}
        director_display_names = [director_names.get(nconst, "") for nconst in director_ids_for_title.split(",") if nconst]
        director_surnames = set()
        for nconst in director_ids_for_title.split(","):
            director_surnames.update(surname_set(director_names.get(nconst, "")))
        director_status = director_match_status(
            crit.director_norms,
            crit.director_surnames,
            director_norms,
            director_surnames,
        )
        fuzzy_director_score = director_similarity(crit.director, director_display_names)
        points, ev = director_points(
            crit.director_norms,
            crit.director_surnames,
            director_norms,
            director_surnames,
        )
        score += points
        evidence.extend(ev)

        imdb_episode = parse_episode_number(cand["matched_title_variant"]) or parse_episode_number(basic["primary_title"])
        points, ev = type_points(crit.episode_number, title_type, imdb_episode)
        score += points
        evidence.extend(ev)

        ranked[row_id].append(
            {
                "row_id": str(row_id),
                "title": crit.title,
                "criterion_director": crit.director,
                "criterion_country": crit.country,
                "criterion_year": crit.year,
                "candidate_tt_identifier": tconst,
                "candidate_title": basic["primary_title"],
                "candidate_original_title": basic["original_title"],
                "candidate_year": basic["year"],
                "candidate_title_type": title_type,
                "candidate_director_nconst": director_ids_for_title,
                "candidate_director_names": "|".join(name for name in director_display_names if name),
                "director_match_status": director_status,
                "director_similarity": f"{fuzzy_director_score:.4f}",
                "candidate_writer_nconst": crew_by_tconst.get(tconst, {}).get("writers", ""),
                "score": f"{min(100.0, score):.2f}",
                "evidence": "|".join(evidence),
                "source": cand["source"],
                "matched_title_variant": cand["matched_title_variant"],
                "title_similarity": cand["title_similarity"],
                "token_overlap": cand["token_overlap"],
            }
        )

    manual_review = []
    for row in unmatched_rows:
        row_candidates = sorted(ranked.get(row.row_id, []), key=lambda item: float(item["score"]), reverse=True)
        if not row_candidates:
            continue
        top = row_candidates[0]
        second_score = float(row_candidates[1]["score"]) if len(row_candidates) > 1 else -999.0
        margin = float(top["score"]) - second_score
        if float(top["score"]) >= AUTO_ACCEPT_SCORE and margin >= AUTO_ACCEPT_MARGIN:
            auto_matches[row.row_id] = {
                "title": top["title"],
                "criterion_director": top["criterion_director"],
                "criterion_country": top["criterion_country"],
                "criterion_year": top["criterion_year"],
                "tt_identifier": top["candidate_tt_identifier"],
                "title_type": top["candidate_title_type"],
                "runtime_minutes": basics[top["candidate_tt_identifier"]]["runtime_minutes"],
                "year": top["candidate_year"],
                "director_nconst": top["candidate_director_nconst"],
                "writer_nconst": top["candidate_writer_nconst"],
                "english_title": top["candidate_title"],
                "match_score": top["score"],
                "match_stage": "second_pass_auto",
                "match_evidence": top["evidence"],
            }
        for rank, candidate in enumerate(row_candidates[:5], start=1):
            manual_review.append(
                {
                    **candidate,
                    "rank": str(rank),
                    "margin_to_second": f"{margin:.2f}",
                    "auto_accept": "yes" if row.row_id in auto_matches and rank == 1 else "no",
                }
            )
    return auto_matches, manual_review


def combine_matches(
    criterion_rows: list[CriterionRow],
    first_pass_matches: dict[int, dict[str, str]],
    second_pass_matches: dict[int, dict[str, str]],
) -> list[dict[str, str]]:
    combined = dict(first_pass_matches)
    combined.update(second_pass_matches)
    rows = []
    for row in criterion_rows:
        if row.row_id not in combined:
            continue
        item = dict(combined[row.row_id])
        item.setdefault("match_stage", "first_pass")
        item.setdefault("match_evidence", "")
        item["row_id"] = str(row.row_id)
        rows.append(item)
    return rows


def build_remaining_unmatched(
    unmatched_rows: list[CriterionRow],
    second_pass_matches: dict[int, dict[str, str]],
    manual_review: list[dict[str, str]],
) -> list[dict[str, str]]:
    top_candidates = {}
    for row in manual_review:
        if row["rank"] == "1":
            top_candidates[int(row["row_id"])] = row
    remaining = []
    for row in unmatched_rows:
        if row.row_id in second_pass_matches:
            continue
        top = top_candidates.get(row.row_id, {})
        remaining.append(
            {
                "title": row.title,
                "director": row.director,
                "country": row.country,
                "year": row.year,
                "best_candidate_tt_identifier": top.get("candidate_tt_identifier", ""),
                "best_candidate_title": top.get("candidate_title", ""),
                "best_candidate_score": top.get("score", ""),
                "best_candidate_evidence": top.get("evidence", ""),
            }
        )
    return remaining


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def update_translation_exports(combined_matches: list[dict[str, str]]) -> None:
    matched_tconsts = {row["tt_identifier"] for row in combined_matches}

    english_titles = {row["tt_identifier"]: row["english_title"] for row in combined_matches}
    with TITLE_AKAS_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        best_score = defaultdict(int)
        for row in reader:
            tconst = row["titleId"]
            if tconst not in matched_tconsts:
                continue
            title = clean(row["title"])
            if not title:
                continue
            language = clean(row["language"])
            region = clean(row["region"])
            types = clean(row["types"])
            score = 0
            if language == "en":
                score = 100
            elif region in {"US", "GB", "CA", "AU", "NZ"}:
                score = 90
            elif "imdbDisplay" in types:
                score = 80
            if score > best_score[tconst]:
                best_score[tconst] = score
                english_titles[tconst] = title

    write_csv(
        OUTPUT / "criterion_title_translations.csv",
        ["title_tconst", "english_title"],
        [{"title_tconst": tconst, "english_title": english_titles.get(tconst, "")} for tconst in sorted(matched_tconsts)],
    )

    actor_pairs = []
    actor_ids = set()
    seen = set()
    with TITLE_PRINCIPALS_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tconst = row["tconst"]
            if tconst not in matched_tconsts or row["category"] not in {"actor", "actress"}:
                continue
            pair = (row["nconst"], tconst)
            if pair in seen:
                continue
            seen.add(pair)
            actor_pairs.append({"actor_nconst": row["nconst"], "title_tconst": tconst})
            actor_ids.add(row["nconst"])

    actor_names = {}
    with NAME_BASICS_TSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            nconst = row["nconst"]
            if nconst in actor_ids:
                actor_names[nconst] = clean(row["primaryName"])

    actor_pairs.sort(key=lambda row: (row["actor_nconst"], row["title_tconst"]))
    write_csv(OUTPUT / "criterion_actor_filmographies.csv", ["actor_nconst", "title_tconst"], actor_pairs)
    write_csv(
        OUTPUT / "criterion_actor_name_translations.csv",
        ["actor_nconst", "english_name"],
        [{"actor_nconst": nconst, "english_name": actor_names.get(nconst, "")} for nconst in sorted(actor_ids)],
    )


def main() -> None:
    criterion_rows = load_criterion_rows()
    first_pass_matches = load_first_pass_matches(criterion_rows)
    unmatched_rows = load_first_pass_unmatched(criterion_rows)

    exact_candidates, basics, aka_hits = collect_exact_candidates(unmatched_rows)
    fuzzy_candidates = collect_fuzzy_review_candidates(unmatched_rows, exact_candidates)
    all_candidates = dict(exact_candidates)
    all_candidates.update(fuzzy_candidates)

    second_pass_matches, manual_review = score_candidates(unmatched_rows, all_candidates, basics, aka_hits)
    combined_matches = combine_matches(criterion_rows, first_pass_matches, second_pass_matches)
    combined_matches.sort(key=lambda row: int(row["row_id"]))
    remaining_unmatched = build_remaining_unmatched(unmatched_rows, second_pass_matches, manual_review)

    write_csv(
        BASIC_INFO_CSV,
        [
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
        ],
        [{key: value for key, value in row.items() if key != "row_id"} for row in combined_matches],
    )
    write_csv(
        UNMATCHED_CSV,
        ["title", "director", "country", "year", "best_candidate_tt_identifier", "best_candidate_title", "best_candidate_score", "best_candidate_evidence"],
        remaining_unmatched,
    )
    write_csv(
        OUTPUT / "manual_review_candidates.csv",
        [
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
        ],
        manual_review,
    )
    update_translation_exports(combined_matches)

    print(f"first-pass matches: {len(first_pass_matches)}")
    print(f"exact candidates: {len(exact_candidates)}")
    print(f"fuzzy review candidates: {len(fuzzy_candidates)}")
    print(f"second-pass auto matches: {len(second_pass_matches)}")
    print(f"combined matches: {len(combined_matches)}")
    print(f"remaining unmatched: {len(remaining_unmatched)}")
    print(f"manual review rows: {len(manual_review)}")


if __name__ == "__main__":
    main()
