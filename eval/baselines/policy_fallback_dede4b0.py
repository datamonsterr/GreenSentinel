"""Exact pre-optimization method from dede4b0; retained for offline/shallow comparisons."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SOURCE_COMMIT = "dede4b070a03726e1bfd3e17a4e484d4d96ada9c"
SOURCE_METHOD_AST_SHA256 = "c351d547ae3166ac999e107c7061972f79f2c5d6e3e7288fc3a857fc3937f5c6"
SOURCE_METHOD_SHA256 = "3b625177d2b572dd5970d40c9c02bdafdd49f5d4d7b6123598274d002f77b609"
QUERY_STOPWORDS = set(
    [
        "a",
        "an",
        "and",
        "any",
        "are",
        "at",
        "by",
        "can",
        "does",
        "for",
        "from",
        "green",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "should",
        "sm",
        "that",
        "the",
        "this",
        "to",
        "use",
        "what",
        "will",
        "with",
        "you",
        "your",
    ]
)


def _fallback_local_search(
    self,
    query: str,
    top_k: int = 4,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fallback keyword search over data/processed markdown files when Qdrant is empty or unavailable."""
    manifest_paths = [
        Path("data/processed/manifest.json"),
        Path("/home/dat/dev/vinuni_aia/P-063/data/processed/manifest.json"),
    ]
    manifest_file = next((p for p in manifest_paths if p.is_file()), None)
    if not manifest_file:
        return []

    try:
        items = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    base_dir = manifest_file.parent
    q_tokens = [
        w
        for w in re.findall(r"[a-zA-Z0-9_\u00C0-\u024F\u1EA0-\u1EF9]+", query.lower())
        if len(w) > 1 and w not in QUERY_STOPWORDS
    ]

    cat_filter = None
    if where and "category" in where:
        cat_filter = str(where["category"]).lower()

    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        item_cat = str(item.get("category", "")).lower()
        if cat_filter and cat_filter != "all" and cat_filter != item_cat:
            continue

        slug = item.get("slug")
        doc_file = base_dir / f"{slug}.md"
        if not doc_file.is_file():
            continue

        try:
            content = doc_file.read_text(encoding="utf-8")
        except Exception:
            continue

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if len(p.strip()) > 30]
        for idx, para in enumerate(paragraphs):
            para_lower = para.lower()
            score = 0
            for tok in q_tokens:
                if re.search(r"\b" + re.escape(tok) + r"\b", para_lower):
                    score += 10
                elif tok in para_lower:
                    score += 2

            title_lower = str(item.get("title", "")).lower()
            for tok in q_tokens:
                if tok in title_lower:
                    score += 5

            if score > 0 or not q_tokens:
                candidates.append(
                    (
                        score,
                        {
                            "id": f"{item.get('id', slug)}#sec_{idx}",
                            "content": para[:1000],
                            "metadata": {
                                "title": item.get("title", slug),
                                "category": item.get("category", "general"),
                                "source_url": item.get("source_url", ""),
                                "doc_id": item.get("id", slug),
                            },
                            "distance": round(max(0.01, 1.0 - (score / 100.0)), 4),
                            "similarity": round(min(0.99, score / 100.0), 4),
                        },
                    )
                )

    candidates.sort(key=lambda x: -x[0])
    results = [c[1] for c in candidates[:top_k]]
    for r, res in enumerate(results):
        res["rank"] = r + 1
    return results
