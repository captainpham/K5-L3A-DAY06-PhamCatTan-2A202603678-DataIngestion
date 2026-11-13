"""Chấm evidence retrieval bằng quy tắc rõ ràng, không giả nhãn người chấm.

Hit: cùng source/page và MỘT chunk chứa trọn excerpt sau chuẩn hóa whitespace.
Không ghép nhiều chunk để làm tăng Hit@3; không gọi điểm này là độ đúng LLM.
"""
import re
from typing import Any

from .ingestion import normalize_text


def canonical(text: str) -> str:
    return re.sub(r'\s+', ' ', normalize_text(text)).strip()


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    golds = [question, *question.get('alternative_gold', [])]
    checked = []
    for hit in hits[:3]:
        matches = []
        for gold in golds:
            quote = canonical(gold['evidence_quote'])
            if (hit['document_id'] == gold['gold_source_id'] and hit['page'] == gold['gold_page']
                    and quote and quote in canonical(hit['text'])):
                matches.append({'source_id': gold['gold_source_id'], 'page': gold['gold_page']})
        checked.append({**hit, 'evidence_hit': bool(matches), 'matched_gold': matches})
    return {'question_id': question['id'], 'split': question['split'],
            'question': question['question'], 'expected_answer': question['expected_answer'],
            'gold': [{k: g[k] for k in ('gold_source_id', 'gold_page', 'evidence_quote')} for g in golds],
            'requested_filter': question.get('filter'), 'hits': checked,
            'hit_at_1': bool(checked and checked[0]['evidence_hit']),
            'hit_at_3': any(h['evidence_hit'] for h in checked),
            'scoring_method': 'source_page_and_full_excerpt_normalized_whitespace',
            'manual_equivalence_review': 'pending'}


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {}
    for trace in traces:
        key = f"{trace['strategy']}:{trace['split']}"
        row = groups.setdefault(key, {'strategy': trace['strategy'], 'split': trace['split'],
                                      'questions': 0, 'hit1_count': 0, 'hit3_count': 0})
        row['questions'] += 1
        row['hit1_count'] += int(trace['hit_at_1'])
        row['hit3_count'] += int(trace['hit_at_3'])
    for row in groups.values():
        row['hit_at_1'] = row['hit1_count'] / row['questions']
        row['hit_at_3'] = row['hit3_count'] / row['questions']
    return groups
