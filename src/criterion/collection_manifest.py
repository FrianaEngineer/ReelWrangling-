from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from src.criterion.collection_helpers import extract_constituent_titles, is_likely_collection
from src.shared.normalize_titles import normalize_title


KNOWN_COLLECTIONS_RAW: Dict[str, List[str]] = {
    "The Orphic Trilogy": ["The Blood of a Poet", "Orpheus", "Testament of Orpheus"],
    "The BRD Trilogy": ["The Marriage of Maria Braun", "Lola", "Veronika Voss"],
    "The Apu Trilogy": ["Pather Panchali", "Aparajito", "The World of Apu"],
    "The Before Trilogy": ["Before Sunrise", "Before Sunset", "Before Midnight"],
    "The Qatsi Trilogy": ["Koyaanisqatsi", "Powaqqatsi", "Naqoyqatsi"],
    "The Infernal Affairs Trilogy": ["Infernal Affairs", "Infernal Affairs II", "Infernal Affairs III"],
    "The Samurai Trilogy": [
        "Samurai I: Musashi Miyamoto",
        "Samurai II: Duel at Ichijoji Temple",
        "Samurai III: Duel at Ganryu Island",
    ],
    "The Koker Trilogy": ["Where Is the Friend's House?", "And Life Goes On", "Through the Olive Trees"],
    "Trilogy of Life": ["The Decameron", "The Canterbury Tales", "Arabian Nights"],
    "The Marseille Trilogy": ["Marius", "Fanny", "Cesar"],
    "The Complete Lady Snowblood": ["Lady Snowblood", "Lady Snowblood: Love Song of Vengeance"],
    "The Heroic Trio / Executioners": ["The Heroic Trio", "Executioners"],
    "Police Story / Police Story 2": ["Police Story", "Police Story 2"],
    "Yojimbo / Sanjuro: Two Samurai Films by Akira Kurosawa": ["Yojimbo", "Sanjuro"],
    "The Shooting/Ride in the Whirlwind": ["The Shooting", "Ride in the Whirlwind"],
    "Gates of Heaven/Vernon, Florida": ["Gates of Heaven", "Vernon, Florida"],
    "The Emigrants/The New Land": ["The Emigrants", "The New Land"],
    "Brief Encounters / The Long Farewell: Two Films by Kira Muratova": ["Brief Encounters", "The Long Farewell"],
    "The Only Son/There Was a Father: Two Films by Yasujiro Ozu": ["The Only Son", "There Was a Father"],
    "Jean de Florette / Manon of the Spring: Two Films by Claude Berri": ["Jean de Florette", "Manon of the Spring"],
    "A Confucian Confusion / Mahjong: Two Films by Edward Yang": ["A Confucian Confusion", "Mahjong"],
    "The Three Musketeers / The Four Musketeers: Two Films by Richard Lester": ["The Three Musketeers", "The Four Musketeers"],
    "I Walked with a Zombie / The Seventh Victim: Produced by Val Lewton": ["I Walked with a Zombie", "The Seventh Victim"],
    "W. C. Fields—Six Short Films": [
        "The Dentist",
        "The Fatal Glass of Beer",
        "The Pharmacist",
        "Hip Action",
        "The Barber Shop",
        "The Golf Specialist",
    ],
    "John Singleton's Hood Trilogy": ["Boyz n the Hood", "Poetic Justice", "Baby Boy"],
}

KNOWN_COLLECTIONS: Dict[str, List[str]] = {
    normalize_title(title): constituents for title, constituents in KNOWN_COLLECTIONS_RAW.items()
}


def extract_titles_for_collection(collection_title: str) -> Tuple[List[str], str]:
    normalized = normalize_title(collection_title)
    if normalized in KNOWN_COLLECTIONS:
        return list(KNOWN_COLLECTIONS[normalized]), "known_collection_map"
    titles, method = extract_constituent_titles(collection_title)
    return titles, method


def is_collection_container_candidate(title: str, director: str, year: str) -> bool:
    if is_likely_collection(title, director, year):
        return True
    if normalize_title(title) in KNOWN_COLLECTIONS:
        return True
    return "eclipse series" in (title or "").casefold()


@dataclass
class ConstituentSpec:
    film_source_id: str
    film_title: str
    film_director: str
    film_year: str
    from_catalog: bool = True


@dataclass
class CollectionGroup:
    collection_type: str
    collection_source_id: str
    collection_title: str
    extraction_method: str
    expected_titles: List[str]
    constituents: List[ConstituentSpec] = field(default_factory=list)


def load_overrides(path: Path) -> Dict[tuple, dict]:
    if not path.exists() or not path.is_file():
        return {}
    out: Dict[tuple, dict] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            collection_id = (row.get("collection_source_id") or "").strip()
            seq_s = (row.get("seq") or "").strip()
            if not collection_id or not seq_s:
                continue
            try:
                seq = int(seq_s)
            except ValueError:
                continue
            out[(collection_id, seq)] = row
    return out


def load_new_criterion_rows(path: Path) -> List[dict]:
    rows: List[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for idx, row in enumerate(csv.DictReader(handle), start=1):
            spine = (row.get("spine") or "").strip()
            source_id = spine if spine.isdigit() else f"row_{idx}"
            rows.append(
                {
                    "_idx": idx,
                    "spine": spine,
                    "source_id": source_id,
                    "title": (row.get("title") or "").strip(),
                    "director": (row.get("director") or "").strip(),
                    "country": (row.get("country") or "").strip(),
                    "year": (row.get("year") or "").strip(),
                }
            )
    return rows


def _virtual_constituents(expected_titles: List[str]) -> List[ConstituentSpec]:
    return [
        ConstituentSpec("", film_title, "", "", from_catalog=False)
        for film_title in expected_titles
    ]


def _enrich_virtual_constituents_from_spineless_rows(group: CollectionGroup, nc_rows: List[dict]) -> None:
    if not group.constituents or not all(not constituent.from_catalog for constituent in group.constituents):
        return
    spineless_rows = [row for row in nc_rows if not row["spine"].strip() and row["director"].strip()]
    by_normalized_title: Dict[str, List[dict]] = defaultdict(list)
    for row in spineless_rows:
        by_normalized_title[normalize_title(row["title"])].append(row)
    for index, constituent in enumerate(group.constituents):
        if index >= len(group.expected_titles):
            break
        expected_title = group.expected_titles[index]
        candidates = by_normalized_title.get(normalize_title(expected_title), [])
        if not candidates:
            continue
        row = candidates[0]
        constituent.film_source_id = row["source_id"]
        constituent.film_title = row["title"]
        constituent.film_director = row["director"]
        constituent.film_year = row["year"]
        constituent.from_catalog = True


def _apply_overrides_to_groups(groups: List[CollectionGroup], overrides: Dict[tuple, dict]) -> None:
    for group in groups:
        for seq, _ in enumerate(group.constituents, start=1):
            override = overrides.get((group.collection_source_id, seq))
            if not override:
                continue
            constituent = group.constituents[seq - 1]
            if (override.get("film_title") or "").strip():
                constituent.film_title = override["film_title"].strip()
            if (override.get("film_director") or "").strip():
                constituent.film_director = override["film_director"].strip()
            if (override.get("film_year") or "").strip():
                constituent.film_year = override["film_year"].strip()
            if (override.get("film_source_id") or "").strip():
                constituent.film_source_id = override["film_source_id"].strip()


def discover_collection_groups(nc_rows: List[dict], overrides_path: Path) -> List[CollectionGroup]:
    overrides = load_overrides(overrides_path)
    groups: List[CollectionGroup] = []
    row_count = len(nc_rows)
    index = 0

    while index < row_count:
        row = nc_rows[index]
        spine = row["spine"]
        director = row["director"]
        title = row["title"]
        year_s = row["year"]
        source_id = row["source_id"]

        if not spine and not director and is_collection_container_candidate(title, director, year_s):
            expected, method = extract_titles_for_collection(title)
            children: List[ConstituentSpec] = []
            child_index = index + 1
            while child_index < row_count:
                next_row = nc_rows[child_index]
                if next_row["spine"].strip() or not next_row["director"].strip():
                    break
                children.append(
                    ConstituentSpec(
                        film_source_id=next_row["source_id"],
                        film_title=next_row["title"],
                        film_director=next_row["director"],
                        film_year=next_row["year"],
                        from_catalog=True,
                    )
                )
                child_index += 1
            if not children and not expected:
                index += 1
                continue
            if expected:
                if len(children) == len(expected):
                    method += "+spineless_block"
                elif children:
                    method += "+spineless_partial"
                else:
                    method += "+spineless_no_children"
            elif children:
                method = "spineless_catalog_children"
            groups.append(
                CollectionGroup(
                    collection_type="spineless",
                    collection_source_id=source_id,
                    collection_title=title,
                    extraction_method=method,
                    expected_titles=expected or [child.film_title for child in children],
                    constituents=children if children else _virtual_constituents(expected),
                )
            )
            index = child_index
            continue

        if spine.isdigit() and not director and is_collection_container_candidate(title, director, year_s):
            expected, method = extract_titles_for_collection(title)
            if not expected:
                index += 1
                continue
            children = []
            child_index = index + 1
            while child_index < row_count and len(children) < len(expected):
                next_row = nc_rows[child_index]
                if not next_row["spine"].strip().isdigit() or not next_row["director"].strip():
                    break
                expected_title = expected[len(children)]
                normalized_next = normalize_title(next_row["title"])
                normalized_expected = normalize_title(expected_title)
                if normalized_next != normalized_expected and normalized_expected not in normalized_next and normalized_next not in normalized_expected:
                    break
                children.append(
                    ConstituentSpec(
                        film_source_id=next_row["spine"],
                        film_title=next_row["title"],
                        film_director=next_row["director"],
                        film_year=next_row["year"],
                        from_catalog=True,
                    )
                )
                child_index += 1
            if len(children) == len(expected):
                method += "+following_spines"
            elif children:
                method += "+following_spines_partial"
            else:
                children = _virtual_constituents(expected)
                method += "+virtual_only"
            groups.append(
                CollectionGroup(
                    collection_type="spined",
                    collection_source_id=source_id,
                    collection_title=title,
                    extraction_method=method,
                    expected_titles=expected,
                    constituents=children,
                )
            )
            index = child_index
            continue

        if spine.isdigit() and director and is_collection_container_candidate(title, director, year_s):
            expected, method = extract_titles_for_collection(title)
            if expected:
                constituents = []
                for seq, expected_title in enumerate(expected, start=1):
                    override = overrides.get((source_id, seq), {})
                    constituents.append(
                        ConstituentSpec(
                            film_source_id=(override.get("film_source_id") or "").strip(),
                            film_title=(override.get("film_title") or "").strip() or expected_title,
                            film_director=(override.get("film_director") or "").strip(),
                            film_year=(override.get("film_year") or "").strip(),
                            from_catalog=False,
                        )
                    )
                groups.append(
                    CollectionGroup(
                        collection_type="spined",
                        collection_source_id=source_id,
                        collection_title=title,
                        extraction_method=method + "+single_row_box",
                        expected_titles=expected,
                        constituents=constituents,
                    )
                )
            index += 1
            continue

        index += 1

    _apply_overrides_to_groups(groups, overrides)
    for group in groups:
        _enrich_virtual_constituents_from_spineless_rows(group, nc_rows)
    return groups


def collection_container_source_ids(nc_rows: List[dict], overrides_path: Path | None = None) -> set[str]:
    if overrides_path is None:
        overrides_path = Path(__file__).resolve().parents[2] / "data" / "collection_constituents_overrides.csv"
    return {group.collection_source_id for group in discover_collection_groups(nc_rows, overrides_path)}
