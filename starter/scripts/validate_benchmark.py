"""Validate benchmark structure and gold excerpts against local PDF extraction.

No embedding calls or retrieval runs. This cannot replace visual evidence review.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STARTER))

from src.ingestion import load_pdf, normalize_text


def canonical(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text)).strip()


def main() -> None:
    benchmark_path = STARTER / "data/benchmark.json"
    questions = json.loads(benchmark_path.read_text(encoding="utf-8"))["questions"]
    mapping = json.loads((STARTER / "data/benchmark_metadata.json").read_text(encoding="utf-8"))
    pages = {}
    sections = {}
    for doc in mapping["documents"]:
        source_id = doc["document_id"]
        pages[source_id] = {
            p.page: p for p in load_pdf(STARTER / doc["source"], source_id, doc["source"])
        }
        for section in doc["sections"]:
            for page in section["pages"]:
                key = (source_id, page)
                if key in sections:
                    raise ValueError(f"Duplicate section mapping: {key}")
                sections[key] = section["section_group"]

    ids = set()
    counts = {"dev": 0, "test": 0}
    filtered = {"dev": 0, "test": 0}
    for q in questions:
        for field in ("id", "split", "question", "expected_answer", "gold_source_id", "gold_page", "evidence_quote"):
            if not q.get(field):
                raise ValueError(f"Missing field {field}: {q.get('id')}")
        if q["id"] in ids:
            raise ValueError(f"Duplicate question ID: {q['id']}")
        ids.add(q["id"])
        counts[q["split"]] += 1
        golds = [q, *q.get("alternative_gold", [])]
        for gold in golds:
            key = (gold["gold_source_id"], gold["gold_page"])
            if key not in sections:
                raise ValueError(f"Gold page outside selected scope: {q['id']}: {key}")
            page = pages[key[0]][key[1]]
            if canonical(gold["evidence_quote"]) not in canonical(page.text):
                raise ValueError(f"Evidence missing from source page: {q['id']}: {key}")
            if q.get("filter") and q["filter"] != {"section_group": sections[key]}:
                raise ValueError(f"Gold does not satisfy filter: {q['id']}")
        if q.get("filter"):
            filtered[q["split"]] += 1

    if counts["dev"] < 15 or counts["test"] < 5:
        raise ValueError(f"Need at least 15 dev and 5 test: {counts}")
    if sum(filtered.values()) < 3 or filtered["test"] < 1:
        raise ValueError(f"Insufficient metadata-filter questions: {filtered}")
    print(f"PASS: {len(questions)} questions; dev={counts['dev']}, test={counts['test']}")
    print(f"Filters: dev={filtered['dev']}, test={filtered['test']}")
    print("All gold excerpts found on the selected PDF pages after normalization.")
    print("Visual review and semantic sufficiency still require author review.")
    print("SHA256:", hashlib.sha256(benchmark_path.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
