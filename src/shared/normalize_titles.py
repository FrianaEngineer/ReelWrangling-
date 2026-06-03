from __future__ import annotations

import re
import unicodedata


ARTICLE_RE = re.compile(r"^(a|an|the)\s+")
PUNCT_RE = re.compile(r"[^a-z0-9]+")
JOINER_RE = re.compile(r"[’'`´]")


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def normalize_title(text: str) -> str:
    text = ascii_fold((text or "").strip().casefold())
    text = JOINER_RE.sub("", text)
    text = text.replace("&", " and ")
    text = ARTICLE_RE.sub("", text)
    text = PUNCT_RE.sub(" ", text)
    return " ".join(text.split())
