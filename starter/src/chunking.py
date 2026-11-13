"""A: cửa sổ ký tự có overlap. B/C: ưu tiên đoạn, rồi câu nếu PDF mất dòng trống.

Mọi chunk giữ nguồn, trang và offset. Không ghép nội dung qua trang PDF.
"""
import hashlib
import json
import re

from .models import Chunk, DocumentPage


def _chunk(page: DocumentPage, start: int, end: int, method: str, params: dict) -> Chunk:
    # Cập nhật offset sau khi bỏ whitespace để text vẫn khớp trang gốc.
    while start < end and page.text[start].isspace():
        start += 1
    while end > start and page.text[end - 1].isspace():
        end -= 1
    text = page.text[start:end]
    identity = [page.document_id, page.page, method, params, start, end, text]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    metadata = {**page.metadata, 'char_start': start, 'char_end': end,
                'chunking_method': method, 'chunking_params': params}
    return Chunk(digest, page.document_id, page.source, page.page, text, metadata)


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """size/overlap tính bằng ký tự, không phải token. ID ổn định khi nạp lại."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError('Cần size > 0 và 0 <= overlap < size.')
    chunks = []
    for start in range(0, len(page.text), size - overlap):
        end = min(start + size, len(page.text))
        if page.text[start:end].strip():
            chunks.append(_chunk(page, start, end, 'fixed', {'size': size, 'overlap': overlap}))
        if end == len(page.text):
            break
    return chunks


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Gom đoạn/câu; chỉ cắt đơn vị quá dài. Không tự viết lại nội dung.

    pypdf thường mất dòng trống. Khi đó dùng ranh giới câu làm heuristic;
    nhược điểm này phải được xem xét khi chấm coherence thủ công.
    """
    if max_size <= 0:
        raise ValueError('max_size phải > 0.')
    text = page.text
    if not text.strip():
        return []
    boundaries = list(re.finditer(r'\n\s*\n+', text))
    mode = 'blank_lines'
    if not boundaries:
        boundaries = list(re.finditer(r'(?<=[.!?])\s+(?=[A-Z“"(])', text))
        mode = 'sentence_fallback'
    units = []
    start = 0
    for match in boundaries:
        if text[start:match.start()].strip():
            units.append((start, match.start()))
        start = match.end()
    if text[start:].strip():
        units.append((start, len(text)))
    pieces = []
    for start, end in units:
        while end - start > max_size:
            cut = start + max_size
            space = text.rfind(' ', start, cut + 1)
            if space > start:
                cut = space
            pieces.append((start, cut))
            start = cut
            while start < end and text[start].isspace():
                start += 1
        if text[start:end].strip():
            pieces.append((start, end))
    groups = []
    for start, end in pieces:
        if groups and end - groups[-1][0] <= max_size:
            groups[-1] = (groups[-1][0], end)
        else:
            groups.append((start, end))
    params = {'max_size': max_size, 'boundary_detection': mode}
    return [_chunk(page, start, end, 'paragraph', params) for start, end in groups]
