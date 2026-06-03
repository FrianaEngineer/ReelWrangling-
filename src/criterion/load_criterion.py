from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from src.shared.normalize_titles import normalize_title
from src.shared.utils import parse_year


@dataclass
class CriterionRow:
    criterion_row_id: str
    criterion_source_id: str
    title_original: str
    title_normalized: str
    director_original: str
    director_normalized: str
    country_original: str
    year: Optional[int]
    original_row_number: int


def load_criterion_rows(path: Path) -> List[CriterionRow]:
    rows: List[CriterionRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=1):
            source_id = (
                str(row.get("spine", "")).strip()
                or str(row.get("spine_number", "")).strip()
                or f"row_{idx}"
            )
            title = (row.get("title", "") or "").strip()
            director = (row.get("director", "") or "").strip()
            country = (row.get("country", "") or "").strip()
            rows.append(
                CriterionRow(
                    criterion_row_id=f"criterion_row_{idx:05d}",
                    criterion_source_id=source_id,
                    title_original=title,
                    title_normalized=normalize_title(title),
                    director_original=director,
                    director_normalized=normalize_title(director),
                    country_original=country,
                    year=parse_year(row.get("year", "")),
                    original_row_number=idx,
                )
            )
    return rows
