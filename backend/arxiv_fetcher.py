"""arxiv_fetcher.py -- Fetch papers from arxiv API for SHARD research mode (#34).

Returns List[Dict] with keys {url, title, body, authors, year} —
matching the structure AggregatePhase expects (url, title, body).
Extra fields (authors, year) are ignored by downstream phases.

Usage:
    from arxiv_fetcher import fetch_arxiv
    papers = fetch_arxiv("JEPA world model LeCun", max_results=5)
"""

import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List

logger = logging.getLogger("shard.arxiv_fetcher")

_ARXIV_API = "http://export.arxiv.org/api/query"
_ATOM_NS   = "http://www.w3.org/2005/Atom"


def fetch_arxiv(topic: str, max_results: int = 5) -> List[Dict]:
    """Query arxiv and return papers as {url, title, body, authors, year}.

    Args:
        topic       : free-text query (same string used for DuckDuckGo in normal mode)
        max_results : max papers to return (default 5)

    Returns:
        List of dicts. Empty list on any error.
    """
    params = urllib.parse.urlencode({
        "search_query": f"all:{topic}",
        "start":        0,
        "max_results":  max_results,
        "sortBy":       "relevance",
        "sortOrder":    "descending",
    })
    url = f"{_ARXIV_API}?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SHARD/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_xml = resp.read()
    except Exception as exc:
        logger.warning("[ARXIV] Request failed for '%s': %s", topic[:60], exc)
        return []

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        logger.warning("[ARXIV] XML parse error: %s", exc)
        return []

    papers = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):

        title_el   = entry.find(f"{{{_ATOM_NS}}}title")
        summary_el = entry.find(f"{{{_ATOM_NS}}}summary")
        published_el = entry.find(f"{{{_ATOM_NS}}}published")

        title   = title_el.text.strip().replace("\n", " ") if title_el is not None else ""
        summary = summary_el.text.strip().replace("\n", " ") if summary_el is not None else ""
        year    = published_el.text[:4] if published_el is not None else ""

        # Prefer the HTML abstract link over the raw arxiv id link
        link = ""
        for link_el in entry.findall(f"{{{_ATOM_NS}}}link"):
            if link_el.attrib.get("type") == "text/html":
                link = link_el.attrib.get("href", "")
                break
        if not link:
            id_el = entry.find(f"{{{_ATOM_NS}}}id")
            link = id_el.text.strip() if id_el is not None else ""

        authors = [
            a.find(f"{{{_ATOM_NS}}}name").text.strip()
            for a in entry.findall(f"{{{_ATOM_NS}}}author")
            if a.find(f"{{{_ATOM_NS}}}name") is not None
        ]

        if not title or not summary:
            continue

        papers.append({
            "url":     link,
            "title":   title,
            "body":    summary,
            "authors": authors,
            "year":    year,
        })

    logger.info("[ARXIV] '%s' -> %d papers", topic[:60], len(papers))
    return papers


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    topic = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "JEPA world model LeCun"
    print(f"\nQuery: '{topic}'\n{'-'*60}")

    results = fetch_arxiv(topic, max_results=5)

    if not results:
        print("Nessun risultato.")
    else:
        for i, p in enumerate(results, 1):
            print(f"\n[{i}] {p['title']}")
            print(f"    {p['year']} | {', '.join(p['authors'][:3])}")
            print(f"    {p['url']}")
            print(f"    Abstract: {p['body'][:120]}...")
