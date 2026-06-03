from __future__ import annotations

from src.shared.utils import parse_year


def classify_short_candidate(title_type: str, runtime_minutes: str, genres: str) -> str:
    title_type = (title_type or "").strip()
    genres = (genres or "").strip()
    runtime = parse_year(runtime_minutes)
    if title_type == "short":
        return "imdb_title_type_short"
    if "Short" in genres.split(","):
        return "imdb_genre_short"
    if runtime is not None and runtime <= 40:
        return "runtime_40_or_less"
    return "feature_or_unknown"
