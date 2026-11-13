"""Xuất JSON/CSV và các bảng chấm tay; tuyệt đối không tự điền nhãn audit."""
import csv
import json
from pathlib import Path


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    # utf-8-sig giúp Excel nhận diện tiếng Việt; JSON/JSONL vẫn là UTF-8 thường.
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def chunk_stats(chunks) -> dict:
    sizes = sorted(len(c.text) for c in chunks)
    return {'count': len(chunks), 'characters': sum(sizes),
            'min_characters': sizes[0] if sizes else 0,
            'max_characters': sizes[-1] if sizes else 0,
            'mean_characters': sum(sizes) / len(sizes) if sizes else 0,
            'p50_characters': sizes[len(sizes) // 2] if sizes else 0,
            'p95_characters': sizes[min(int(len(sizes) * .95), len(sizes) - 1)] if sizes else 0}


def prepare_coherence_audit(output: Path, pages, strategies) -> None:
    # Cùng 10 vị trí nguồn, chọn trước khi xem điểm; không lấy 10 chunk tùy ý.
    rows = []
    for page in pages[:10]:
        position = len(page.text) // 2
        for strategy, chunks in strategies.items():
            covering = [c for c in chunks if c.document_id == page.document_id and c.page == page.page
                        and c.metadata['char_start'] <= position < c.metadata['char_end']]
            if not covering:
                # Nếu midpoint nằm trong whitespace, chọn chunk gần nhất và ghi rõ vị trí.
                covering = sorted([c for c in chunks if c.document_id == page.document_id and c.page == page.page],
                                  key=lambda c: abs(c.metadata['char_start'] - position))[:1]
            for chunk in covering:
                rows.append({'strategy': strategy, 'document_id': page.document_id, 'page': page.page,
                             'source_position': position, 'chunk_id': chunk.chunk_id, 'text': chunk.text,
                             'coherence_0_1_2': '', 'reason': '', 'reviewer': ''})
    write_csv(output / 'coherence_audit.csv', rows,
              ['strategy', 'document_id', 'page', 'source_position', 'chunk_id', 'text',
               'coherence_0_1_2', 'reason', 'reviewer'])


def prepare_retrieval_audit(output: Path, traces) -> None:
    grounding = []
    metadata = []
    for trace in traces:
        grounding.append({'strategy': trace['strategy'], 'split': trace['split'],
                          'question_id': trace['question_id'], 'question': trace['question'],
                          'grounding_0_1_2': '', 'equivalent_evidence_override': '', 'reason': '', 'reviewer': ''})
        for rank, hit in enumerate(trace['hits'], 1):
            metadata.append({'strategy': trace['strategy'], 'split': trace['split'],
                             'question_id': trace['question_id'], 'rank': rank,
                             'chunk_id': hit['chunk_id'], 'document_id': hit['document_id'],
                             'source': hit['source'], 'page': hit['page'],
                             'metadata': json.dumps(hit['metadata'], ensure_ascii=False),
                             'requested_filter': json.dumps(trace['requested_filter'], ensure_ascii=False),
                             'metadata_complete_and_correct': '', 'filter_compliant': '', 'reason': '', 'reviewer': ''})
    write_csv(output / 'grounding_audit.csv', grounding,
              ['strategy', 'split', 'question_id', 'question', 'grounding_0_1_2',
               'equivalent_evidence_override', 'reason', 'reviewer'])
    write_csv(output / 'metadata_audit.csv', metadata,
              ['strategy', 'split', 'question_id', 'rank', 'chunk_id', 'document_id', 'source', 'page',
               'metadata', 'requested_filter', 'metadata_complete_and_correct', 'filter_compliant', 'reason', 'reviewer'])
