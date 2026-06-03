#!/usr/bin/env python3
"""
Re-anchor existing IMDb match results to new-criterion.csv by spine number
(for spined rows) and title+director+year (for spineless rows).

Produces:
  data/output/new_initial_matches.csv       — high-confidence matches carried over from old pipeline
  data/output/new_unmatched_tracking.csv    — everything needing further work (~230 rows)
  data/output/new_match_status_summary.csv  — one row per new-criterion row with disposition

Does NOT require access to IMDb data files; it reuses existing match outputs.
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.wrangling.resolve_collections import is_likely_collection

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_CRITERION   = REPO_ROOT / "data" / "criterion" / "new-criterion.csv"
OUTPUTS         = REPO_ROOT / "data" / "output"

OLD_MATCHES     = OUTPUTS / "initial_matches.csv"
OLD_REVIEW      = OUTPUTS / "match_candidates_review.csv"
OLD_UNMATCHED   = OUTPUTS / "unmatched_initial.csv"
OLD_SHORTS      = OUTPUTS / "excluded_shorts_seed.csv"
MANUAL_LOG      = OUTPUTS / "manual_resolution_log.csv"

OUT_MATCHES     = OUTPUTS / "new_initial_matches.csv"
OUT_UNMATCHED   = OUTPUTS / "new_unmatched_tracking.csv"
OUT_SUMMARY     = OUTPUTS / "new_match_status_summary.csv"

csv.field_size_limit(sys.maxsize)

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------
_NOISE_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE    = re.compile(r"\s+")

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = _NOISE_RE.sub(" ", text.casefold())
    return _WS_RE.sub(" ", text).strip()


def person_key(name: str) -> str:
    tokens = [t for t in normalize(name).split() if len(t) > 1]
    return " ".join(tokens)


def title_key(title: str) -> str:
    t = normalize(title)
    t = re.sub(r"^(the|a|an|le|la|les|l|los|las|el|un|une|des|il|lo|i) ", "", t)
    return t.strip()


def year_ok(y1: str, y2: str, tolerance: int = 1) -> bool:
    try:
        return abs(int(y1) - int(y2)) <= tolerance
    except (ValueError, TypeError):
        return True   # no year → don't block match


# ---------------------------------------------------------------------------
# Load / write helpers
# ---------------------------------------------------------------------------
def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  [WARN] not found: {path}", file=sys.stderr)
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        print(f"  Wrote 0 rows → {path.name}")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows):,} rows → {path.name}")


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ---------------------------------------------------------------------------
# Step 1 – load new-criterion.csv, assign criterion_row_id
# ---------------------------------------------------------------------------
def load_new_criterion() -> list[dict]:
    raw = load_csv(NEW_CRITERION)
    rows = []
    for idx, r in enumerate(raw, start=1):
        spine = r.get("spine", "").strip()
        source_id = spine if spine else f"row_{idx}"
        rows.append({
            "criterion_row_id":             f"criterion_row_{idx:05d}",
            "criterion_source_id":          source_id,
            "criterion_title_original":     r.get("title", "").strip(),
            "criterion_title_key":          title_key(r.get("title", "")),
            "criterion_director_original":  r.get("director", "").strip(),
            "criterion_director_key":       person_key(r.get("director", "")),
            "criterion_country":            r.get("country", "").strip(),
            "criterion_year":               r.get("year", "").strip(),
            "_spine_is_numeric":            spine.isdigit(),
            "_spine_raw":                   spine,
        })
    return rows


# ---------------------------------------------------------------------------
# Step 2 – build lookup indexes from old pipeline outputs
# ---------------------------------------------------------------------------
def build_spine_index(rows: list[dict]) -> dict[str, dict]:
    """numeric spine → row dict"""
    return {r["criterion_source_id"]: r for r in rows if r["criterion_source_id"].isdigit()}


def build_title_index(old_matches: list[dict]) -> dict[tuple, list[dict]]:
    """(title_key, director_key) → list of match rows (for spineless lookup)"""
    idx: dict[tuple, list[dict]] = defaultdict(list)
    for row in old_matches:
        src = row.get("criterion_source_id", "")
        # Only index spineless old rows (collection constituents)
        if src.startswith("row_"):
            tk = title_key(row.get("criterion_title_original", ""))
            dk = person_key(row.get("criterion_director_original", ""))
            idx[(tk, dk)].append(row)
    return idx


def build_shorts_set(old_shorts: list[dict]) -> tuple[set[str], set[tuple]]:
    """Return (numeric_spine_set, (title_key, director_key) set) for excluded shorts."""
    spine_set: set[str] = set()
    title_set: set[tuple] = set()
    for r in old_shorts:
        src = r.get("criterion_source_id", "")
        if src.isdigit():
            spine_set.add(src)
        else:
            tk = title_key(r.get("criterion_title_original", ""))
            dk = person_key(r.get("criterion_director_original", ""))
            title_set.add((tk, dk))
    return spine_set, title_set


def build_review_index(old_review: list[dict]) -> dict[str, dict]:
    """criterion_source_id → first review candidate"""
    idx: dict[str, dict] = {}
    for row in old_review:
        src = row.get("criterion_source_id", "")
        if src not in idx:
            idx[src] = row
    return idx


def build_unmatched_spine_index(old_unmatched: list[dict]) -> dict[str, dict]:
    return {r.get("criterion_source_id", ""): r for r in old_unmatched}


def build_manual_resolution_index(rows: list[dict]) -> dict[str, dict]:
    return {r.get("criterion_row_id", ""): r for r in rows if r.get("criterion_row_id", "")}


def make_manual_match_row(nc: dict, resolution: dict, title_type_override: str | None = None) -> dict:
    title_type = title_type_override or resolution.get("entity_type", "")
    return {
        "criterion_row_id":           nc["criterion_row_id"],
        "criterion_source_id":        nc["criterion_source_id"],
        "criterion_title_original":   nc["criterion_title_original"],
        "criterion_title_normalized": nc["criterion_title_key"],
        "criterion_director_original":nc["criterion_director_original"],
        "criterion_year":             nc["criterion_year"],
        "imdb_id":                    resolution.get("imdb_id", ""),
        "imdb_primary_title":         resolution.get("imdb_title", ""),
        "imdb_original_title":        resolution.get("imdb_title", ""),
        "imdb_title_type":            title_type,
        "imdb_start_year":            "",
        "imdb_runtime_minutes":       "",
        "imdb_genres":                "",
        "imdb_directors":             "",
        "matched_via":                "manual_resolution_rule",
        "score":                      "",
        "year_difference":            "",
        "short_signal":               "",
        "decision_bucket":            "matched",
        "generated_at":               ts(),
    }


# ---------------------------------------------------------------------------
# Step 3 – classify each new-criterion row
# ---------------------------------------------------------------------------
def classify_row(
    nc: dict,
    spine_match: dict[str, dict],
    title_match: dict[tuple, list[dict]],
    spine_review: dict[str, dict],
    spine_unmatched: dict[str, dict],
    shorts_spines: set[str],
    shorts_titles: set[tuple],
    manual_resolution: dict | None,
) -> tuple[str, dict | None, str]:
    """
    Returns (status, best_old_row_or_None, notes).
    Status values:
      matched          — high-confidence carry-over from old pipeline
      excluded_short   — classified as short in old pipeline
      other_content    — deterministically identified as TV/docs/shorts/video
      needs_review     — had review candidates but unresolved
      new_entry        — genuinely new or old-pipeline gap; needs fresh IMDb lookup
      collection_header— spineless row with no director (collection label, not a film)
    """
    src = nc["criterion_source_id"]
    tk  = nc["criterion_title_key"]
    dk  = nc["criterion_director_key"]
    yr  = nc["criterion_year"]
    has_dir = bool(nc["criterion_director_original"].strip())
    has_country = bool(nc["criterion_country"].strip())

    # Promote prior manual-review resolutions into deterministic upstream rules.
    if nc["criterion_title_original"] == "King Kong vs. Godzilla":
        pseudo = {
            "imdb_id": "tt0056142",
            "imdb_primary_title": "King Kong vs. Godzilla",
            "imdb_original_title": "King Kong tai Gojira",
            "imdb_title_type": "movie",
            "matched_via": "manual_resolution_rule",
        }
        return "matched", pseudo, "Promoted manual-review correction: single-film movie row."

    if nc["criterion_title_original"] == "Fanny and Alexander" and nc["_spine_is_numeric"]:
        pseudo = {
            "imdb_id": "tt0083922",
            "imdb_primary_title": "Fanny and Alexander",
            "imdb_original_title": "Fanny och Alexander",
            "imdb_title_type": "movie",
            "matched_via": "manual_resolution_rule",
        }
        return "matched", pseudo, "Promoted manual-review rule: normalize blank-year row to the 1982 theatrical film."

    if manual_resolution:
        resolved_type = manual_resolution.get("entity_type", "")
        note = manual_resolution.get("notes", "")
        if resolved_type == "movie":
            return "matched", make_manual_match_row(nc, manual_resolution), note
        if resolved_type in {"documentary", "short", "tvMiniSeries", "tvMovie", "tvSeries", "tvSpecial", "video"}:
            return "other_content", make_manual_match_row(nc, manual_resolution), note
        if resolved_type in {"collection", "collection_label"}:
            return "collection_header", make_manual_match_row(nc, manual_resolution, title_type_override=resolved_type), note

    # ── Spined rows (named Criterion entries) ──────────────────────────────
    if nc["_spine_is_numeric"]:
        if src in shorts_spines:
            return "excluded_short", None, ""
        if src in spine_match:
            return "matched", spine_match[src], ""
        if src in spine_review:
            return "needs_review", spine_review[src], ""
        if src in spine_unmatched:
            return "needs_review", spine_unmatched[src], ""  # was unmatched in old pipeline too
        return "new_entry", None, ""

    # ── Spineless rows (collection constituents / headers) ─────────────────
    if not has_dir:
        # Most spineless rows with no director are collection/container labels.
        # But some real single-film rows are sparse and only carry title/year/country.
        if is_likely_collection(nc["criterion_title_original"], nc["criterion_director_original"], yr):
            return "collection_header", None, ""
        if not yr and not has_country:
            return "collection_header", None, ""
        return "new_entry", None, ""

    # Check short-film title lookup
    if (tk, dk) in shorts_titles:
        return "excluded_short", None, ""

    # Check old matched results by title+director
    candidates = title_match.get((tk, dk), [])
    if candidates:
        if yr:
            year_best = [c for c in candidates if year_ok(yr, c.get("criterion_year", ""))]
            if year_best:
                return "matched", year_best[0], ""
        return "matched", candidates[0], ""

    # Title-only relaxed match (director key mismatch or empty)
    title_only = [
        row
        for (t, d), rows in title_match.items()
        if t == tk
        for row in rows
    ]
    if title_only:
        if yr:
            year_best = [c for c in title_only if year_ok(yr, c.get("criterion_year", ""))]
            if year_best:
                return "matched", year_best[0], ""
        # Director key differs → soft match, route to needs_review
        return "needs_review", title_only[0], ""

    # Nothing found → new entry
    return "new_entry", None, ""


# ---------------------------------------------------------------------------
# Step 4 – build output rows
# ---------------------------------------------------------------------------
MATCHED_FIELDS = [
    "criterion_row_id", "criterion_source_id",
    "criterion_title_original", "criterion_title_normalized",
    "criterion_director_original", "criterion_year",
    "imdb_id", "imdb_primary_title", "imdb_original_title",
    "imdb_title_type", "imdb_start_year", "imdb_runtime_minutes",
    "imdb_genres", "imdb_directors",
    "matched_via", "score", "year_difference", "short_signal",
    "decision_bucket", "generated_at",
]

UNMATCHED_FIELDS = [
    "criterion_row_id", "criterion_source_id",
    "criterion_title_original", "criterion_title_normalized",
    "criterion_director_original", "criterion_country", "criterion_year",
    "entity_type", "review_status",
    "candidate_imdb_id", "candidate_imdb_title",
    "final_action", "rationale", "notes", "last_updated",
]

SUMMARY_FIELDS = [
    "criterion_row_id", "criterion_source_id",
    "criterion_title_original", "criterion_director_original", "criterion_year",
    "status", "entity_type", "imdb_id", "imdb_title", "notes",
]


def infer_entity_type(nc: dict, status: str, old: dict | None) -> str:
    if status == "collection_header":
        if old and old.get("imdb_title_type") in {"collection", "collection_label"}:
            return old.get("imdb_title_type")
        return "collection_header"
    if status == "other_content" and old and old.get("imdb_title_type"):
        return old.get("imdb_title_type")
    if nc["_spine_is_numeric"]:
        return "named_criterion_entry"
    if not nc["criterion_director_original"].strip():
        return "named_criterion_entry"
    return "collection_constituent_film"


def make_matched_row(nc: dict, old: dict) -> dict:
    return {
        "criterion_row_id":           nc["criterion_row_id"],
        "criterion_source_id":        nc["criterion_source_id"],
        "criterion_title_original":   nc["criterion_title_original"],
        "criterion_title_normalized": nc["criterion_title_key"],
        "criterion_director_original":nc["criterion_director_original"],
        "criterion_year":             nc["criterion_year"],
        "imdb_id":                    old.get("imdb_id", ""),
        "imdb_primary_title":         old.get("imdb_primary_title", ""),
        "imdb_original_title":        old.get("imdb_original_title", ""),
        "imdb_title_type":            old.get("imdb_title_type", ""),
        "imdb_start_year":            old.get("imdb_start_year", ""),
        "imdb_runtime_minutes":       old.get("imdb_runtime_minutes", ""),
        "imdb_genres":                old.get("imdb_genres", ""),
        "imdb_directors":             old.get("imdb_directors", ""),
        "matched_via":                old.get("matched_via", "reanchored"),
        "score":                      old.get("score", ""),
        "year_difference":            old.get("year_difference", ""),
        "short_signal":               old.get("short_signal", ""),
        "decision_bucket":            "matched",
        "generated_at":               ts(),
    }


def make_unmatched_row(nc: dict, old: dict | None, review_status: str,
                       entity_type: str, notes: str = "") -> dict:
    return {
        "criterion_row_id":            nc["criterion_row_id"],
        "criterion_source_id":         nc["criterion_source_id"],
        "criterion_title_original":    nc["criterion_title_original"],
        "criterion_title_normalized":  nc["criterion_title_key"],
        "criterion_director_original": nc["criterion_director_original"],
        "criterion_country":           nc["criterion_country"],
        "criterion_year":              nc["criterion_year"],
        "entity_type":                 entity_type,
        "review_status":               review_status,
        "candidate_imdb_id":           (old or {}).get("imdb_id", ""),
        "candidate_imdb_title":        (old or {}).get("imdb_primary_title", ""),
        "final_action":                "",
        "rationale":                   "",
        "notes":                       notes,
        "last_updated":                ts(),
    }


def make_summary_row(nc: dict, status: str, entity_type: str, old: dict | None, notes: str = "") -> dict:
    return {
        "criterion_row_id":            nc["criterion_row_id"],
        "criterion_source_id":         nc["criterion_source_id"],
        "criterion_title_original":    nc["criterion_title_original"],
        "criterion_director_original": nc["criterion_director_original"],
        "criterion_year":              nc["criterion_year"],
        "status":                      status,
        "entity_type":                 entity_type,
        "imdb_id":                     (old or {}).get("imdb_id", ""),
        "imdb_title":                  (old or {}).get("imdb_primary_title", ""),
        "notes":                       notes,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("Loading new-criterion.csv …")
    new_rows = load_new_criterion()
    print(f"  {len(new_rows):,} rows")

    print("\nLoading old pipeline outputs …")
    old_matches   = load_csv(OLD_MATCHES)
    old_review    = load_csv(OLD_REVIEW)
    old_unmatched = load_csv(OLD_UNMATCHED)
    old_shorts    = load_csv(OLD_SHORTS)
    manual_log    = load_csv(MANUAL_LOG)

    print("\nBuilding indexes …")
    spine_match    = build_spine_index(old_matches)
    title_match    = build_title_index(old_matches)
    spine_review   = build_review_index(old_review)
    spine_unmatched = build_unmatched_spine_index(old_unmatched)
    shorts_spines, shorts_titles = build_shorts_set(old_shorts)
    manual_resolution_index = build_manual_resolution_index(manual_log)

    old_max_spine = max((int(s) for s in spine_match), default=0)
    new_spines = sorted(
        int(r["criterion_source_id"])
        for r in new_rows
        if r["_spine_is_numeric"] and int(r["criterion_source_id"]) > old_max_spine
    )
    print(f"  Old matched spines: {len(spine_match)}, max={old_max_spine}")
    print(f"  New spines (>{old_max_spine}): {new_spines}")
    print(f"  Title index entries: {len(title_match)}")
    print(f"  Shorts (spine): {len(shorts_spines)}, (title): {len(shorts_titles)}")

    print("\nClassifying rows …")
    matched_rows  : list[dict] = []
    unmatched_rows: list[dict] = []
    summary_rows  : list[dict] = []
    excluded_short_rows: list[dict] = []

    status_counts: dict[str, int] = defaultdict(int)

    for nc in new_rows:
        status, old, notes = classify_row(
            nc, spine_match, title_match,
            spine_review, spine_unmatched,
            shorts_spines, shorts_titles,
            manual_resolution_index.get(nc["criterion_row_id"]),
        )
        et = infer_entity_type(nc, status, old)
        status_counts[status] += 1

        summary_rows.append(make_summary_row(nc, status, et, old, notes=notes))

        if status == "matched":
            matched_rows.append(make_matched_row(nc, old))

        elif status == "other_content":
            row = make_matched_row(nc, old)
            row["decision_bucket"] = "other_content"
            matched_rows.append(row)

        elif status == "excluded_short":
            # Record in matched file with decision_bucket=excluded_short
            if old:
                row = make_matched_row(nc, old)
            else:
                row = {
                    "criterion_row_id":           nc["criterion_row_id"],
                    "criterion_source_id":        nc["criterion_source_id"],
                    "criterion_title_original":   nc["criterion_title_original"],
                    "criterion_title_normalized": nc["criterion_title_key"],
                    "criterion_director_original":nc["criterion_director_original"],
                    "criterion_year":             nc["criterion_year"],
                    "imdb_id": "", "imdb_primary_title": "", "imdb_original_title": "",
                    "imdb_title_type": "", "imdb_start_year": "", "imdb_runtime_minutes": "",
                    "imdb_genres": "", "imdb_directors": "",
                    "matched_via": "excluded_short_seed", "score": "", "year_difference": "",
                    "short_signal": "short", "decision_bucket": "excluded_short",
                    "generated_at": ts(),
                }
            row["decision_bucket"] = "excluded_short"
            excluded_short_rows.append(row)

        elif status == "needs_review":
            unmatched_rows.append(make_unmatched_row(
                nc, old, "needs_manual_review", et,
            ))

        elif status == "new_entry":
            notes = "Not in prior pipeline — requires fresh IMDb lookup"
            if int(nc["criterion_source_id"]) > old_max_spine if nc["_spine_is_numeric"] else False:
                notes = "New Criterion addition — requires fresh IMDb lookup"
            unmatched_rows.append(make_unmatched_row(
                nc, None, "new_entry_needs_imdb_lookup", et, notes=notes,
            ))

        elif status == "collection_header":
            # Collection-level label row: not a matchable film on its own
            unmatched_rows.append(make_unmatched_row(
                nc, None, "collection_resolution_needed", et,
            ))

    print("\nResults:")
    for k, v in sorted(status_counts.items()):
        print(f"  {k:30s}: {v:,}")

    collection_only = [r for r in unmatched_rows if r["entity_type"] in {"collection", "collection_label", "collection_header"}]
    named_only = [r for r in unmatched_rows if r["entity_type"] == "named_criterion_entry"]
    constituent_only = [
        r for r in unmatched_rows
        if r["entity_type"] not in {"named_criterion_entry", "collection", "collection_label", "collection_header"}
    ]

    print(f"\nSummary:")
    print(f"  Matched (carry-over):       {len(matched_rows):,}")
    print(f"  Excluded shorts:            {len(excluded_short_rows):,}")
    print(f"  Unmatched tracking total:   {len(unmatched_rows):,}")
    print(f"  Other content (resolved):   {status_counts['other_content']:,}")
    print(f"    — named Criterion entries:         {len(named_only):,}")
    print(f"    — collection constituent films:    {len(constituent_only):,}")
    print(f"    — collection records:              {len(collection_only):,}")

    print("\nWriting outputs …")
    write_csv(OUT_MATCHES,  matched_rows + excluded_short_rows)
    write_csv(OUT_UNMATCHED, unmatched_rows)
    write_csv(OUT_SUMMARY,   summary_rows)


if __name__ == "__main__":
    main()
