from __future__ import annotations

import re
from typing import List


COLLECTION_HINTS = (
    "collection",
    "trilogy",
    "anthology",
    "three films",
    "five films",
    "six films",
    "adventures of",
    "by brakhage",
    "box set",
    "films of",
    "volumes one and two",
    "two films",
    "complete",
    "series",
)

SLASH_SPLIT_RE = re.compile(r"\s*/\s*")


def split_candidate_list(text: str) -> List[str]:
    parts = [part.strip(" ,") for part in text.split(",")]
    return [part for part in parts if part]


def extract_constituent_titles(title: str) -> tuple[list[str], str]:
    stripped = title.strip()
    if " / " in stripped:
        return [part.strip() for part in SLASH_SPLIT_RE.split(stripped) if part.strip()], "slash_split"
    if ":" in stripped:
        left, right = [part.strip() for part in stripped.split(":", 1)]
        if " / " in left:
            return [part.strip() for part in SLASH_SPLIT_RE.split(left) if part.strip()], "colon_left_slash_split"
        if "," in right and any(token in right.casefold() for token in ("trilogy", "two films", "three films", "five films")):
            return split_candidate_list(right), "colon_right_comma_split"
        if "," in right and len(split_candidate_list(right)) > 1:
            return split_candidate_list(right), "colon_right_comma_split"
    if stripped.casefold().startswith("a whit stillman trilogy:"):
        _, right = stripped.split(":", 1)
        return split_candidate_list(right), "whit_stillman_comma_split"
    return [], "needs_manual_decomposition"


def is_likely_collection(title: str, director: str, year: str) -> bool:
    lowered = (title or "").casefold()
    if any(hint in lowered for hint in COLLECTION_HINTS):
        return True
    if not (director or "").strip() or not (year or "").strip():
        if "/" in title or ":" in title:
            return True
    return False
