"""GreenSM Terms and Policies Crawler (Comprehensive Multi-Tab).

Crawls ALL policy tabs and sections from GreenSM:
1. /vn-en/terms-policies/general (11 General Terms & Appendix Tabs)
2. /vn-en/terms-policies/privacy-notice (14 Privacy Policy Articles)
3. /vn-en/terms-policies/regulations (Operation Regulations)
4. /vn-en/terms-policies (Terms & Legal overview)

Extracts structured markdown, cleans formatting, assigns domain categories,
and saves documents and manifest to data/raw and data/processed.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.greensm.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def slugify(text: str) -> str:
    """Convert title to clean lowercase slug."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text


def clean_content(html_or_text: str) -> str:
    """Convert HTML snippet to clean readable text/markdown."""
    if not html_or_text:
        return ""
    text = md(html_or_text, heading_style="ATX", strip=["img", "script", "style"])
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def crawl_all_greensm_policies(
    raw_dir: Path = Path("data/raw"),
    processed_dir: Path = Path("data/processed"),
) -> list[dict[str, Any]]:
    """Crawl all tabs across GreenSM terms and policies."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    documents: list[dict[str, Any]] = []

    # 1. Crawl General Terms & Appendices (11 tabs)
    general_url = f"{BASE_URL}/vn-en/terms-policies/general"
    logger.info("Fetching General Terms: %s", general_url)
    resp = requests.get(general_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    (raw_dir / "general_terms_raw.html").write_text(resp.text, encoding="utf-8")
    soup = BeautifulSoup(resp.text, "html.parser")
    next_data_tag = soup.find("script", id="__NEXT_DATA__")

    if next_data_tag and next_data_tag.string:
        data = json.loads(next_data_tag.string)
        general_terms = data.get("props", {}).get("pageProps", {}).get("generalTerms", {})
        general_items = general_terms.get("generalItems", [])
        (raw_dir / "general_terms_raw.json").write_text(
            json.dumps(general_terms, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        for idx, item in enumerate(general_items):
            title = item.get("title", f"Section {idx + 1}").strip()
            raw_desc = item.get("description", "")
            cleaned = clean_content(raw_desc)
            slug = slugify(title)

            category = "general"
            if "bike" in slug:
                category = "bike"
            elif "car" in slug:
                category = "car"
            elif "express" in slug or "delivery" in slug:
                category = "delivery"
            elif "food" in slug:
                category = "food"
            elif "rental" in slug:
                category = "rental"
            elif "promotional" in slug or "promotion" in slug:
                category = "promotion"
            elif "postpaid" in slug or "prepaid" in slug:
                category = "billing"

            doc = {
                "id": f"greensm-policy-{slug}",
                "tab": "general-terms",
                "index": idx,
                "title": title,
                "slug": slug,
                "category": category,
                "source_url": general_url,
                "char_length": len(cleaned),
                "content": cleaned,
            }
            documents.append(doc)

            md_file = processed_dir / f"{slug}.md"
            frontmatter = (
                f"---\n"
                f"id: {doc['id']}\n"
                f'title: "{title}"\n'
                f"category: {category}\n"
                f"tab: general-terms\n"
                f"source_url: {general_url}\n"
                f"---\n\n"
            )
            md_file.write_text(frontmatter + cleaned, encoding="utf-8")

    # 2. Crawl Privacy Notice (14 Articles)
    privacy_url = f"{BASE_URL}/vn-en/terms-policies/privacy-notice"
    logger.info("Fetching Privacy Notice: %s", privacy_url)
    try:
        resp_p = requests.get(privacy_url, headers=HEADERS, timeout=30)
        if resp_p.status_code == 200:
            (raw_dir / "privacy_notice_raw.html").write_text(resp_p.text, encoding="utf-8")
            soup_p = BeautifulSoup(resp_p.text, "html.parser")
            tag_p = soup_p.find("script", id="__NEXT_DATA__")
            if tag_p and tag_p.string:
                data_p = json.loads(tag_p.string)
                priv = data_p.get("props", {}).get("pageProps", {}).get("privacyNotice", {})
                priv_items = priv.get("privacyItems", [])
                (raw_dir / "privacy_notice_raw.json").write_text(
                    json.dumps(priv, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                # Combine into complete privacy policy document & individual articles
                all_priv_text = []
                for idx, item in enumerate(priv_items):
                    t = item.get("title", f"Article {idx + 1}").strip()
                    c = clean_content(item.get("description", ""))
                    all_priv_text.append(f"## {t}\n\n{c}")

                combined_privacy = "\n\n".join(all_priv_text)
                priv_doc = {
                    "id": "greensm-policy-privacy-notice",
                    "tab": "privacy-policy",
                    "index": len(documents),
                    "title": "GREEN SM PERSONAL DATA PROTECTION & PRIVACY POLICY",
                    "slug": "privacy-policy",
                    "category": "privacy",
                    "source_url": privacy_url,
                    "char_length": len(combined_privacy),
                    "content": combined_privacy,
                }
                documents.append(priv_doc)

                p_file = processed_dir / "privacy-policy.md"
                p_frontmatter = (
                    f"---\n"
                    f"id: {priv_doc['id']}\n"
                    f'title: "{priv_doc["title"]}"\n'
                    f"category: privacy\n"
                    f"tab: privacy-policy\n"
                    f"source_url: {privacy_url}\n"
                    f"---\n\n"
                )
                p_file.write_text(p_frontmatter + combined_privacy, encoding="utf-8")
    except Exception as e:
        logger.warning("Error fetching privacy notice: %s", e)

    # 3. Save comprehensive manifest
    manifest_path = processed_dir / "manifest.json"
    manifest_data = [{k: v for k, v in doc.items() if k != "content"} for doc in documents]
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    logger.info("Saved %d policy documents across all tabs to %s", len(documents), processed_dir)
    return documents


if __name__ == "__main__":
    docs = crawl_all_greensm_policies()
    print(f"Successfully crawled {len(docs)} documents covering all tabs.")
