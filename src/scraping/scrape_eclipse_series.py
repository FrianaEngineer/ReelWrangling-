from __future__ import annotations

import argparse
import csv
import html
import random
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


BASE_URL = "https://www.criterion.com"
BOXSET_PREFIX = f"{BASE_URL}/boxsets/"
ECLIPSE_COLLECTION_INDEX_URL = f"{BASE_URL}/shop/collection/546-eclipse-box-sets"
ECLIPSE_SEARCH_RESULTS_URL = f"{BASE_URL}/search/films?q=eclipse+serie"
YEAR_RE = re.compile(r"\b(18|19|20)\d{2}\b")
COLLECTION_NUMBER_RE = re.compile(r"Eclipse Series\s+(\d+):", re.IGNORECASE)
COLLECTION_NUMBER_SLUG_RE = re.compile(r"/boxsets/\d+-eclipse-series-(\d+)(?:-|$)", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
TRAILING_PUNCT_RE = re.compile(r"[\s\.,;:!?-]+$")
SMART_PUNCT_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)
FILMS_SECTION_HEADING_XPATH = (
    "//*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6]"
    "[contains(translate(normalize-space(.), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),"
    " 'FILMS IN THIS SET')]"
)
STOP_SECTION_PATTERNS = (
    "purchase options",
    "newsletter",
    "shopping cart",
    "related films",
    "related boxsets",
)
OUTPUT_FIELDS = [
    "collection_row_id",
    "collection_source_id",
    "collection_title",
    "collection_number",
    "collection_url",
    "movie_order_in_collection",
    "movie_title",
    "movie_year",
    "scraped_at_utc",
    "status",
    "error_message",
]
FAILURE_FIELDS = [
    "collection_row_id",
    "collection_title",
    "failure_stage",
    "error_message",
    "attempted_url",
    "scraped_at_utc",
]
CACHE_FIELDS = [
    "collection_title",
    "collection_number",
    "collection_url",
    "matched_title",
    "match_confidence",
]
RESULT_LINK_RE = re.compile(
    r'<a[^>]+class="[^"]*global-search__film-result-link[^"]*"[^>]+href="(?P<href>/boxsets/[^"]+)"[^>]*>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
RESULT_TITLE_SPAN_RE = re.compile(
    r'<span[^>]+class="[^"]*global-search__result-title[^"]*"[^>]*>(?P<title>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
IMG_ALT_RE = re.compile(r'<img[^>]+alt="(?P<alt>[^"]+)"', re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
ESCAPED_RESULT_URL_RE = re.compile(
    r'global-search__film-result-link.*?href="(?P<url>https://www\.criterion\.com/boxsets/[^"]+)"',
    re.IGNORECASE | re.DOTALL,
)
ESCAPED_ALT_RE = re.compile(
    r'<span class="html-attribute-name">alt</span>="<span class="html-attribute-value">(?P<title>[^<]+)</span>"',
    re.IGNORECASE | re.DOTALL,
)
ESCAPED_TITLE_TEXT_RE = re.compile(
    r'global-search__result-title[^>]*</span>&gt;</span>(?P<title>.*?)<span class="html-tag">&lt;/span&gt;</span>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class MovieRecord:
    movie_title: str
    movie_year: int
    movie_order_in_collection: int


@dataclass
class UrlMatch:
    collection_url: str
    matched_title: str
    match_confidence: str


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Scrape films from Criterion Eclipse Series box set pages.")
    parser.add_argument("--input", type=Path, default=repo_root / "outputs" / "eclipse_series_titles.csv")
    parser.add_argument("--output", type=Path, default=repo_root / "outputs" / "criterion_eclipse_movies.csv")
    parser.add_argument("--failures", type=Path, default=repo_root / "outputs" / "criterion_eclipse_failures.csv")
    parser.add_argument("--url-cache", type=Path, default=repo_root / "outputs" / "criterion_eclipse_url_cache.csv")
    parser.add_argument("--url-source-html", type=Path, default=None)
    parser.add_argument("--imdb-hints", type=Path, default=repo_root / "outputs" / "criterion_eclipse_imdb_hints.csv")
    parser.add_argument("--headless", type=parse_bool, default=True)
    parser.add_argument("--page-timeout", type=int, default=30)
    parser.add_argument("--search-timeout", type=int, default=20)
    return parser.parse_args()


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def normalize_title(text: str) -> str:
    text = (text or "").translate(SMART_PUNCT_TRANSLATION).strip().lower()
    text = WHITESPACE_RE.sub(" ", text)
    return TRAILING_PUNCT_RE.sub("", text)


def extract_collection_number(title: str) -> int | None:
    match = COLLECTION_NUMBER_RE.search(title or "")
    return int(match.group(1)) if match else None


def dedupe_movies(movies: Iterable[MovieRecord]) -> tuple[list[MovieRecord], int]:
    seen: set[tuple[str, str]] = set()
    deduped: list[MovieRecord] = []
    duplicate_count = 0
    for movie in movies:
        key = (normalize_title(movie.movie_title), str(movie.movie_year))
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        deduped.append(movie)
    return deduped, duplicate_count


def get_collection_delay_seconds() -> float:
    """
    Return the delay before fetching a new Eclipse collection page.

    Formula:
    5 seconds + abs(Normal(mean=3 seconds, standard_deviation=1 second))

    This guarantees a minimum delay of 5 seconds.
    The usual delay will be around 8 seconds.
    """
    return 5.0 + abs(random.gauss(3.0, 1.0))


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def configure_driver(headless: bool, page_timeout: int) -> WebDriver:
    options = ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1200")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(page_timeout)
    return driver


def load_input(path: Path) -> list[dict]:
    required_columns = {
        "criterion_row_id",
        "criterion_source_id",
        "criterion_title_original",
        "criterion_year",
        "status",
        "entity_type",
    }
    frame = pd.read_csv(path, dtype=str).fillna("")
    missing = required_columns.difference(frame.columns)
    if missing:
        raise ValueError(f"Input CSV missing required columns: {sorted(missing)}")
    return frame.to_dict(orient="records")


def load_url_cache(path: Path) -> dict[str, UrlMatch]:
    if not path.exists():
        return {}
    cache: dict[str, UrlMatch] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            title = row.get("collection_title", "").strip()
            if not title:
                continue
            cache[normalize_title(title)] = UrlMatch(
                collection_url=(row.get("collection_url", "") or "").strip(),
                matched_title=(row.get("matched_title", "") or "").strip(),
                match_confidence=(row.get("match_confidence", "") or "").strip(),
            )
    return cache


def load_imdb_hints(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    hints_by_collection: dict[str, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            collection_title = (row.get("collection_title") or "").strip()
            movie_title = (row.get("movie_title") or row.get("parsed_movie_title") or "").strip()
            movie_year = (row.get("movie_year") or "").strip()
            if not collection_title or not movie_title or not movie_year.isdigit():
                continue
            hints_by_collection[normalize_title(collection_title)].append(row)
    for rows in hints_by_collection.values():
        rows.sort(key=lambda row: int((row.get("movie_order_in_collection") or "0").strip() or "0"))
    return hints_by_collection


def cache_rows(cache: dict[str, UrlMatch], original_titles: dict[str, tuple[str, int | None]]) -> list[dict]:
    rows: list[dict] = []
    for normalized_title, url_match in sorted(cache.items(), key=lambda item: item[0]):
        original_title, collection_number = original_titles.get(normalized_title, (normalized_title, None))
        rows.append(
            {
                "collection_title": original_title,
                "collection_number": collection_number if collection_number is not None else "",
                "collection_url": url_match.collection_url,
                "matched_title": url_match.matched_title,
                "match_confidence": url_match.match_confidence,
            }
        )
    return rows


def strip_html(text: str) -> str:
    return WHITESPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(text or ""))).strip()


def parse_url_matches_from_html(html_text: str) -> tuple[dict[str, UrlMatch], dict[int, UrlMatch]]:
    matches_by_title: dict[str, UrlMatch] = {}
    matches_by_number: dict[int, UrlMatch] = {}
    for match in RESULT_LINK_RE.finditer(html_text):
        href = (match.group("href") or "").strip()
        body = match.group("body") or ""
        title_match = RESULT_TITLE_SPAN_RE.search(body)
        raw_title = title_match.group("title") if title_match else ""
        if not raw_title:
            img_match = IMG_ALT_RE.search(body)
            raw_title = img_match.group("alt") if img_match else ""
        candidate_title = strip_html(raw_title)
        if not candidate_title:
            continue
        collection_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        collection_number = extract_collection_number(candidate_title) or extract_collection_number_from_url(collection_url)
        if collection_number is None:
            continue
        url_match = UrlMatch(
            collection_url=collection_url,
            matched_title=candidate_title,
            match_confidence="saved_html",
        )
        matches_by_title[normalize_title(candidate_title)] = url_match
        matches_by_number[collection_number] = url_match

    if matches_by_number:
        return matches_by_title, matches_by_number

    for match in ESCAPED_RESULT_URL_RE.finditer(html_text):
        collection_url = (match.group("url") or "").strip()
        window = html_text[match.start() : match.start() + 2500]
        title_match = ESCAPED_ALT_RE.search(window)
        if title_match:
            candidate_title = strip_html(title_match.group("title") or "")
        else:
            title_match = ESCAPED_TITLE_TEXT_RE.search(window)
            candidate_title = strip_html(title_match.group("title") or "") if title_match else ""
        if not collection_url or not candidate_title:
            continue
        collection_number = extract_collection_number(candidate_title) or extract_collection_number_from_url(collection_url)
        if collection_number is None:
            continue
        url_match = UrlMatch(
            collection_url=collection_url,
            matched_title=candidate_title,
            match_confidence="saved_html_escaped",
        )
        matches_by_title[normalize_title(candidate_title)] = url_match
        matches_by_number[collection_number] = url_match
    return matches_by_title, matches_by_number


def load_saved_html_matches(path: Path) -> tuple[dict[str, UrlMatch], dict[int, UrlMatch]]:
    html_text = path.read_text(encoding="utf-8")
    return parse_url_matches_from_html(html_text)


def wait_for_boxset_links(driver: WebDriver, timeout: int) -> None:
    wait = WebDriverWait(driver, timeout)

    def _probe(_driver: WebDriver) -> bool:
        if _driver.find_elements(By.CSS_SELECTOR, "a[href*='/boxsets/']"):
            return True
        body = normalize_title(_driver.find_element(By.TAG_NAME, "body").text)
        return "0 results" in body or "no results" in body

    wait.until(_probe)


def normalized_similarity(left: str, right: str) -> float:
    left_tokens = set(normalize_title(left).split())
    right_tokens = set(normalize_title(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return intersection / union if union else 0.0


def score_candidate(input_title: str, input_number: int | None, candidate_title: str, candidate_url: str) -> tuple[float, str]:
    normalized_input = normalize_title(input_title)
    normalized_candidate = normalize_title(candidate_title)
    similarity = normalized_similarity(input_title, candidate_title)
    candidate_number = extract_collection_number(candidate_title)

    if "/boxsets/" not in candidate_url:
        return 0.0, "reject_non_boxset"
    if input_number is not None and candidate_number != input_number:
        return 0.0, "reject_series_number_mismatch"

    score = similarity
    if normalized_candidate == normalized_input:
        score += 0.5
    if normalized_input in normalized_candidate or normalized_candidate in normalized_input:
        score += 0.15

    confidence = "weak"
    if score >= 1.0:
        confidence = "exact"
    elif score >= 0.72:
        confidence = "high"
    elif score >= 0.55:
        confidence = "medium"
    return score, confidence


def candidate_matches(driver: WebDriver) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/boxsets/']")
    for anchor in anchors:
        href = (anchor.get_attribute("href") or "").strip()
        text_candidates = [
            anchor.text.strip(),
            (anchor.get_attribute("title") or "").strip(),
            (anchor.get_attribute("aria-label") or "").strip(),
        ]
        try:
            parent_text = anchor.find_element(By.XPATH, "./ancestor::*[self::article or self::li or self::div][1]").text.strip()
            text_candidates.append(parent_text)
        except Exception:
            pass
        text = " ".join(part for part in text_candidates if part).strip()
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)
        matches.append((text, href))
    return matches


def load_boxset_list_page(driver: WebDriver, url: str, timeout: int) -> list[tuple[str, str]]:
    driver.get(url)
    wait_for_boxset_links(driver, timeout)
    return candidate_matches(driver)


def extract_collection_number_from_url(url: str) -> int | None:
    match = COLLECTION_NUMBER_SLUG_RE.search(url or "")
    return int(match.group(1)) if match else None


def discover_collection_urls_from_indexes(driver: WebDriver, timeout: int) -> tuple[dict[str, UrlMatch], dict[int, UrlMatch]]:
    matches_by_title: dict[str, UrlMatch] = {}
    best_by_number: dict[int, UrlMatch] = {}
    source_urls = [
        ECLIPSE_COLLECTION_INDEX_URL,
        ECLIPSE_SEARCH_RESULTS_URL,
    ]
    for source_url in source_urls:
        for candidate_title, candidate_url in load_boxset_list_page(driver, source_url, timeout):
            collection_number = extract_collection_number(candidate_title) or extract_collection_number_from_url(candidate_url)
            if collection_number is None:
                continue
            normalized_candidate_title = normalize_title(candidate_title)
            url_match = UrlMatch(
                collection_url=candidate_url,
                matched_title=candidate_title,
                match_confidence="index_exact" if normalized_candidate_title else "index_number_match",
            )
            if collection_number not in best_by_number or (
                url_match.match_confidence == "index_exact"
                and best_by_number[collection_number].match_confidence != "index_exact"
            ):
                best_by_number[collection_number] = url_match
            if normalized_candidate_title:
                matches_by_title[normalized_candidate_title] = url_match

    return matches_by_title, best_by_number


def discover_collection_url(driver: WebDriver, collection_title: str, collection_number: int | None, timeout: int) -> UrlMatch | None:
    if collection_number is None:
        return None
    driver.get(f"{BASE_URL}/search/films?q=eclipse+series+{collection_number}")
    wait_for_boxset_links(driver, timeout)
    scored: list[tuple[float, str, str, str]] = []
    for candidate_title, candidate_url in candidate_matches(driver):
        score, confidence = score_candidate(collection_title, collection_number, candidate_title, candidate_url)
        if score > 0:
            scored.append((score, confidence, candidate_title, candidate_url))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, confidence, matched_title, collection_url = scored[0]
    if confidence not in {"exact", "high"}:
        return None
    if best_score < 0.72:
        return None
    return UrlMatch(collection_url=collection_url, matched_title=matched_title, match_confidence=confidence)


def wait_before_collection_fetch(collection_url: str, progress_label: str) -> None:
    delay_seconds = get_collection_delay_seconds()
    print(f"{progress_label} Sleeping {delay_seconds:.2f} seconds before fetching collection page")
    time.sleep(delay_seconds)


def load_collection_page(
    driver: WebDriver,
    collection_url: str,
    collection_title: str,
    timeout: int,
    progress_label: str,
) -> None:
    wait_before_collection_fetch(collection_url, progress_label)
    driver.get(collection_url)
    wait = WebDriverWait(driver, timeout)
    normalized_collection_title = normalize_title(collection_title)

    def _probe(d: WebDriver) -> bool:
        if d.find_elements(By.XPATH, FILMS_SECTION_HEADING_XPATH):
            return True
        heading_texts = [normalize_title(element.text) for element in d.find_elements(By.XPATH, "//h1 | //h2")]
        if normalized_collection_title in heading_texts:
            return True
        return normalized_collection_title in normalize_title(d.title)

    wait.until(_probe)


def extract_title_year_from_text(text: str) -> tuple[str, int] | None:
    compact = WHITESPACE_RE.sub(" ", (text or "").translate(SMART_PUNCT_TRANSLATION)).strip()
    year_match = YEAR_RE.search(compact)
    if not year_match:
        return None
    title = compact[: year_match.start()].strip(" :-")
    if not title:
        return None
    year = int(year_match.group(0))
    return title, year


def collect_section_text_blocks(section_root) -> list[str]:
    blocks: list[str] = []
    for selector in ("a", "li", "article", "div", "p"):
        for element in section_root.find_elements(By.CSS_SELECTOR, selector):
            text = WHITESPACE_RE.sub(" ", element.text).strip()
            if text and text not in blocks:
                blocks.append(text)
    return blocks


def is_heading_tag(tag_name: str) -> bool:
    return tag_name.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}


def iter_films_section_blocks(heading) -> list[str]:
    blocks: list[str] = []
    sibling_elements = heading.find_elements(By.XPATH, "following-sibling::*")
    for sibling in sibling_elements:
        sibling_tag = (sibling.tag_name or "").lower()
        sibling_text = WHITESPACE_RE.sub(" ", sibling.text).strip()
        normalized_sibling_text = normalize_title(sibling_text)
        if is_heading_tag(sibling_tag):
            break
        if any(stop_pattern in normalized_sibling_text for stop_pattern in STOP_SECTION_PATTERNS):
            break
        if sibling_text and sibling_text not in blocks:
            blocks.append(sibling_text)
        for block in collect_section_text_blocks(sibling):
            normalized_block = normalize_title(block)
            if any(stop_pattern in normalized_block for stop_pattern in STOP_SECTION_PATTERNS):
                continue
            if block not in blocks:
                blocks.append(block)
    return blocks


def find_films_section_container(driver: WebDriver):
    headings = driver.find_elements(By.XPATH, FILMS_SECTION_HEADING_XPATH)
    if not headings:
        raise ValueError("Could not find Films In This Set heading")
    heading = headings[0]
    container = None
    for xpath in (
        "./ancestor::section[1]",
        "./ancestor::div[1]",
        "./parent::*",
    ):
        candidates = heading.find_elements(By.XPATH, xpath)
        if candidates:
            container = candidates[0]
            break
    return heading, container or heading


def parse_films_section(driver: WebDriver) -> tuple[list[MovieRecord], int]:
    headings = driver.find_elements(By.XPATH, FILMS_SECTION_HEADING_XPATH)
    if not headings:
        raise ValueError("Could not find Films In This Set heading")

    blocks: list[str] = []
    for heading in headings:
        for block in iter_films_section_blocks(heading):
            if block not in blocks:
                blocks.append(block)

    if not blocks:
        heading, container = find_films_section_container(driver)
        blocks = collect_section_text_blocks(container)

    movies: list[MovieRecord] = []
    for block in blocks:
        normalized_block = normalize_title(block)
        if any(stop_pattern in normalized_block for stop_pattern in STOP_SECTION_PATTERNS):
            continue
        parsed = extract_title_year_from_text(block)
        if not parsed:
            continue
        title, year = parsed
        movies.append(
            MovieRecord(
                movie_title=title,
                movie_year=year,
                movie_order_in_collection=len(movies) + 1,
            )
        )

    deduped_movies, duplicate_count = dedupe_movies(movies)
    for index, movie in enumerate(deduped_movies, start=1):
        movie.movie_order_in_collection = index
    return deduped_movies, duplicate_count


def validate_movie_rows(rows: list[dict], expected_collection_number: int | None) -> None:
    for row in rows:
        if not row["collection_title"]:
            raise ValueError("Output row missing collection_title")
        if not row["movie_title"]:
            raise ValueError("Output row missing movie_title")
        if not YEAR_RE.fullmatch(str(row["movie_year"])):
            raise ValueError(f"Output row has invalid movie_year: {row['movie_year']}")
        if not row["collection_url"].startswith(BOXSET_PREFIX):
            raise ValueError(f"Output row has invalid collection_url: {row['collection_url']}")
        if expected_collection_number is not None and int(row["collection_number"]) != expected_collection_number:
            raise ValueError("Collection number mismatch between input title and output row")


def fallback_rows_from_hints(
    hint_rows: list[dict],
    collection_row_id: str,
    collection_source_id: str,
    collection_title: str,
    collection_number: int,
    collection_url: str,
    fallback_reason: str,
) -> list[dict]:
    scraped_at = timestamp_utc()
    rows: list[dict] = []
    for order, hint in enumerate(hint_rows, start=1):
        movie_title = (hint.get("movie_title") or hint.get("parsed_movie_title") or "").strip()
        movie_year = (hint.get("movie_year") or "").strip()
        if not movie_title or not movie_year.isdigit():
            continue
        rows.append(
            {
                "collection_row_id": collection_row_id,
                "collection_source_id": collection_source_id,
                "collection_title": collection_title,
                "collection_number": collection_number,
                "collection_url": collection_url,
                "movie_order_in_collection": int((hint.get("movie_order_in_collection") or order)),
                "movie_title": movie_title,
                "movie_year": int(movie_year),
                "scraped_at_utc": scraped_at,
                "status": "imdb_hint_fallback",
                "error_message": fallback_reason,
            }
        )
    return rows


def failure_row(collection_row_id: str, collection_title: str, stage: str, error_message: str, attempted_url: str = "") -> dict:
    return {
        "collection_row_id": collection_row_id,
        "collection_title": collection_title,
        "failure_stage": stage,
        "error_message": error_message,
        "attempted_url": attempted_url,
        "scraped_at_utc": timestamp_utc(),
    }


def main() -> int:
    args = parse_args()
    output_rows: list[dict] = []
    failure_rows: list[dict] = []
    stats = Counter()

    try:
        records = load_input(args.input)
    except Exception as exc:
        print(f"FAILED at input_validation: {exc}", file=sys.stderr)
        return 1

    original_titles = {
        normalize_title(row["criterion_title_original"]): (
            row["criterion_title_original"],
            extract_collection_number(row["criterion_title_original"]),
        )
        for row in records
    }
    url_cache = load_url_cache(args.url_cache)
    imdb_hints = load_imdb_hints(args.imdb_hints)

    driver: WebDriver | None = None
    if args.url_source_html and args.url_source_html.exists():
        try:
            index_matches, index_matches_by_number = load_saved_html_matches(args.url_source_html)
            print(
                f"Loaded {len(index_matches_by_number)} Eclipse collection URLs from saved HTML"
            )
        except Exception as exc:
            print(f"WARNING: failed to parse saved HTML URL source: {exc}")
            index_matches = {}
            index_matches_by_number = {}
    else:
        index_matches = {}
        index_matches_by_number = {}

    need_browser = True
    if need_browser:
        try:
            driver = configure_driver(args.headless, args.page_timeout)
        except Exception as exc:
            if not index_matches_by_number:
                print(f"FAILED at browser_setup: {exc}", file=sys.stderr)
                return 1
            print(f"WARNING: browser setup failed, continuing with saved HTML/cache only: {exc}")

    try:
        if driver is not None and not index_matches_by_number:
            try:
                index_matches, index_matches_by_number = discover_collection_urls_from_indexes(driver, args.search_timeout)
                print(
                    f"Loaded {len(index_matches_by_number)} Eclipse collection URLs from stable list pages"
                )
            except Exception as exc:
                index_matches = {}
                index_matches_by_number = {}
                print(f"WARNING: failed to load stable list pages, will use direct search-results fallback only: {exc}")

        total = len(records)
        for index, row in enumerate(records, start=1):
            collection_row_id = row["criterion_row_id"].strip()
            collection_source_id = row["criterion_source_id"].strip()
            collection_title = row["criterion_title_original"].strip()
            collection_number = extract_collection_number(collection_title)
            attempted_url = ""

            if not collection_title or collection_number is None:
                failure_rows.append(
                    failure_row(
                        collection_row_id,
                        collection_title,
                        "input_validation",
                        "Missing collection title or could not parse Eclipse Series number",
                    )
                )
                stats["failed"] += 1
                print(f"[{index}/{total}] FAILED at input_validation: invalid collection title")
                continue

            normalized_collection_title = normalize_title(collection_title)
            print(f"[{index}/{total}] Searching URL for {collection_title}")
            try:
                url_match = url_cache.get(normalized_collection_title)
                if url_match and url_match.collection_url.startswith(BOXSET_PREFIX):
                    attempted_url = url_match.collection_url
                    print(f"[{index}/{total}] Found cached URL: {attempted_url}")
                elif normalized_collection_title in index_matches:
                    url_match = index_matches[normalized_collection_title]
                    attempted_url = url_match.collection_url
                    url_cache[normalized_collection_title] = url_match
                    print(f"[{index}/{total}] Found index URL: {attempted_url}")
                elif collection_number in index_matches_by_number:
                    url_match = index_matches_by_number[collection_number]
                    attempted_url = url_match.collection_url
                    url_cache[normalized_collection_title] = url_match
                    print(f"[{index}/{total}] Found index URL by collection number: {attempted_url}")
                else:
                    if driver is None:
                        raise ValueError("No saved HTML/cache match and browser discovery is unavailable")
                    print(f"[{index}/{total}] Falling back to direct search-results URL")
                    url_match = discover_collection_url(driver, collection_title, collection_number, args.search_timeout)
                    if url_match is None:
                        raise ValueError("No high-confidence Criterion /boxsets/ result found")
                    attempted_url = url_match.collection_url
                    url_cache[normalized_collection_title] = url_match
                    print(f"[{index}/{total}] Found URL: {attempted_url}")
            except Exception as exc:
                failure_rows.append(
                    failure_row(collection_row_id, collection_title, "url_discovery", str(exc), attempted_url)
                )
                stats["failed"] += 1
                print(f"[{index}/{total}] FAILED at url_discovery: {exc}")
                continue

            try:
                if driver is None:
                    raise ValueError("Browser is unavailable for collection page scraping")
                load_collection_page(
                    driver,
                    attempted_url,
                    collection_title,
                    args.page_timeout,
                    f"[{index}/{total}]",
                )
            except TimeoutException as exc:
                hint_rows = fallback_rows_from_hints(
                    imdb_hints.get(normalized_collection_title, []),
                    collection_row_id,
                    collection_source_id,
                    collection_title,
                    collection_number,
                    attempted_url,
                    "page_load_timeout",
                )
                if hint_rows:
                    output_rows.extend(hint_rows)
                    stats["success"] += 1
                    stats["movie_rows"] += len(hint_rows)
                    print(f"[{index}/{total}] Used IMDb hint fallback for {len(hint_rows)} movies after page_load timeout")
                    continue
                failure_rows.append(
                    failure_row(collection_row_id, collection_title, "page_load", f"Timed out: {exc}", attempted_url)
                )
                stats["failed"] += 1
                print(f"[{index}/{total}] FAILED at page_load: timeout")
                continue
            except Exception as exc:
                hint_rows = fallback_rows_from_hints(
                    imdb_hints.get(normalized_collection_title, []),
                    collection_row_id,
                    collection_source_id,
                    collection_title,
                    collection_number,
                    attempted_url,
                    f"page_load_error:{exc}",
                )
                if hint_rows:
                    output_rows.extend(hint_rows)
                    stats["success"] += 1
                    stats["movie_rows"] += len(hint_rows)
                    print(f"[{index}/{total}] Used IMDb hint fallback for {len(hint_rows)} movies after page_load error")
                    continue
                failure_rows.append(failure_row(collection_row_id, collection_title, "page_load", str(exc), attempted_url))
                stats["failed"] += 1
                print(f"[{index}/{total}] FAILED at page_load: {exc}")
                continue

            try:
                movies, duplicate_count = parse_films_section(driver)
            except Exception as exc:
                hint_rows = fallback_rows_from_hints(
                    imdb_hints.get(normalized_collection_title, []),
                    collection_row_id,
                    collection_source_id,
                    collection_title,
                    collection_number,
                    attempted_url,
                    f"parse_films_section_error:{exc}",
                )
                if hint_rows:
                    output_rows.extend(hint_rows)
                    stats["success"] += 1
                    stats["movie_rows"] += len(hint_rows)
                    print(f"[{index}/{total}] Used IMDb hint fallback for {len(hint_rows)} movies after parse failure")
                    continue
                failure_rows.append(
                    failure_row(collection_row_id, collection_title, "parse_films_section", str(exc), attempted_url)
                )
                stats["failed"] += 1
                print(f"[{index}/{total}] FAILED at parse_films_section: {exc}")
                continue

            if not movies:
                hint_rows = fallback_rows_from_hints(
                    imdb_hints.get(normalized_collection_title, []),
                    collection_row_id,
                    collection_source_id,
                    collection_title,
                    collection_number,
                    attempted_url,
                    "movie_extraction_zero_movies",
                )
                if hint_rows:
                    output_rows.extend(hint_rows)
                    stats["success"] += 1
                    stats["movie_rows"] += len(hint_rows)
                    print(f"[{index}/{total}] Used IMDb hint fallback for {len(hint_rows)} movies after zero-movie extraction")
                    continue
                failure_rows.append(
                    failure_row(
                        collection_row_id,
                        collection_title,
                        "movie_extraction",
                        "Parsed Films In This Set section but found zero valid movie rows",
                        attempted_url,
                    )
                )
                stats["failed"] += 1
                stats["zero_movie_collections"] += 1
                print(f"[{index}/{total}] FAILED at movie_extraction: zero movies")
                continue

            scraped_at = timestamp_utc()
            rows_for_collection = [
                {
                    "collection_row_id": collection_row_id,
                    "collection_source_id": collection_source_id,
                    "collection_title": collection_title,
                    "collection_number": collection_number,
                    "collection_url": attempted_url,
                    "movie_order_in_collection": movie.movie_order_in_collection,
                    "movie_title": movie.movie_title,
                    "movie_year": movie.movie_year,
                    "scraped_at_utc": scraped_at,
                    "status": "success",
                    "error_message": "",
                }
                for movie in movies
            ]

            try:
                validate_movie_rows(rows_for_collection, collection_number)
            except Exception as exc:
                failure_rows.append(
                    failure_row(collection_row_id, collection_title, "write_output", str(exc), attempted_url)
                )
                stats["failed"] += 1
                print(f"[{index}/{total}] FAILED at write_output: {exc}")
                continue

            output_rows.extend(rows_for_collection)
            stats["success"] += 1
            stats["movie_rows"] += len(rows_for_collection)
            stats["duplicates_removed"] += duplicate_count
            print(f"[{index}/{total}] Scraped {len(rows_for_collection)} movies")
    finally:
        if driver is not None:
            driver.quit()

    try:
        write_csv(args.output, OUTPUT_FIELDS, output_rows)
        write_csv(args.failures, FAILURE_FIELDS, failure_rows)
        write_csv(args.url_cache, CACHE_FIELDS, cache_rows(url_cache, original_titles))
    except Exception as exc:
        print(f"FAILED at write_output: {exc}", file=sys.stderr)
        return 1

    print("")
    print("Scrape summary")
    print(f"total collections in input: {len(records)}")
    print(f"total collections successfully scraped: {stats['success']}")
    print(f"total failed collections: {stats['failed']}")
    print(f"total movie rows written: {stats['movie_rows']}")
    print(f"collections with zero movies: {stats['zero_movie_collections']}")
    print(f"duplicate movie rows removed: {stats['duplicates_removed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
