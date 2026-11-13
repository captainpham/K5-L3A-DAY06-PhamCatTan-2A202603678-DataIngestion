"""Đọc manifest và kiểm tra gold trước khi tốn chi phí API.

Manifest là hợp đồng chọn trang; không âm thầm ingest mọi trang của PDF.
"""
import hashlib
import json
from pathlib import Path

from .evaluation import canonical
from .ingestion import load_pdf


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def load_corpus(manifest_path: Path, metadata_path: Path, base: Path):
    manifest = read_json(manifest_path)
    mapping = read_json(metadata_path)
    sections = {(d['document_id'], p): section['section_group'] for d in mapping['documents']
                for section in d['sections'] for p in section['pages']}
    selected = []
    audit = []
    known = set()
    for doc in manifest['documents']:
        source_id = doc['source_id']
        path = (base / doc['source_path_or_url']).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError('Đường dẫn corpus phải nằm trong starter/.')
        digest = file_hash(path)
        if doc.get('sha256') and doc['sha256'] != digest:
            raise ValueError(f'PDF đã đổi nhưng manifest chưa cập nhật: {source_id}')
        pages = load_pdf(path, source_id, doc['source_path_or_url'])
        if len(pages) != doc['physical_page_count']:
            raise ValueError(f'Số trang khác manifest: {source_id}')
        include = doc['included_pages']
        if len(include) != len(set(include)) or any(not 1 <= p <= len(pages) for p in include):
            raise ValueError(f'Danh sách trang không hợp lệ: {source_id}')
        for page in pages:
            audit.append({'document_id': source_id, 'page': page.page,
                          'included': page.page in include, **page.metadata})
        for number in include:
            key = source_id, number
            if key in known or key not in sections:
                raise ValueError(f'Trùng trang hoặc thiếu section_group: {key}')
            known.add(key)
            page = pages[number - 1]
            if not page.text:
                raise ValueError(f'Trang được chọn không có text: {key}')
            page.metadata.update({'section_group': sections[key], 'title': doc['title'],
                                  'version': doc.get('version'), 'pdf_sha256': digest})
            selected.append(page)
    if len(selected) < 30:
        raise ValueError(f'Cần ít nhất 30 trang text đã chọn, hiện có {len(selected)}.')
    return sorted(selected, key=lambda p: (p.document_id, p.page)), audit


def load_benchmark(path: Path, pages) -> list[dict]:
    payload = read_json(path)
    questions = payload['questions'] if isinstance(payload, dict) else payload
    lookup = {(p.document_id, p.page): p for p in pages}
    ids = set()
    counts = {'dev': 0, 'test': 0}
    filters = {'dev': 0, 'test': 0}
    for q in questions:
        if q['id'] in ids or q['split'] not in counts:
            raise ValueError('ID câu hỏi trùng hoặc split không hợp lệ.')
        ids.add(q['id'])
        counts[q['split']] += 1
        for key in ('question', 'expected_answer', 'evidence_quote'):
            if not q.get(key, '').strip():
                raise ValueError(f'Câu {q["id"]} thiếu {key}.')
        if q.get('filter'):
            filters[q['split']] += 1
        for gold in [q, *q.get('alternative_gold', [])]:
            key = gold['gold_source_id'], gold['gold_page']
            page = lookup.get(key)
            if page is None or canonical(gold['evidence_quote']) not in canonical(page.text):
                raise ValueError(f'Gold không có trong trang được chọn: {q["id"]}')
            if q.get('filter') and any(page.metadata.get(k) != v for k, v in q['filter'].items()):
                raise ValueError(f'Gold không tuân thủ filter: {q["id"]}')
    if counts['dev'] < 15 or counts['test'] < 5 or sum(filters.values()) < 3 or filters['test'] < 1:
        raise ValueError('Cần >=15 dev, >=5 test, >=3 filter và >=1 filter thuộc test.')
    return questions
