"""Kiểm tra offline các bất biến; mock API chỉ có trong test, không là embedding lab."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from src.chunking import by_paragraph, fixed_size
from src.embeddings import EmbeddingError, MyEmbedder, validate_vector
from src.evaluation import evaluate_query, summarize
from src.ingestion import normalize_text
from src.models import Chunk, DocumentPage
from src.run import choose_on_dev


class ChunkTests(unittest.TestCase):
    def page(self, text):
        return DocumentPage('paper', 'data/paper.pdf', 2, text, {'section_group': 'main'})

    def assert_coverage(self, page, chunks, maximum):
        covered = set()
        for chunk in chunks:
            start, end = chunk.metadata['char_start'], chunk.metadata['char_end']
            self.assertEqual(chunk.text, page.text[start:end])
            self.assertLessEqual(len(chunk.text), maximum)
            self.assertEqual((chunk.document_id, chunk.source, chunk.page), ('paper', 'data/paper.pdf', 2))
            self.assertEqual(chunk.metadata['section_group'], 'main')
            covered.update(range(start, end))
        self.assertTrue(all(i in covered for i, char in enumerate(page.text) if not char.isspace()))

    def test_fixed_covers_text_and_retains_source(self):
        page = self.page('  Alpha beta gamma delta epsilon zeta. ' * 9)
        chunks = fixed_size(page, 30, 5)
        self.assert_coverage(page, chunks, 30)
        self.assertEqual([c.chunk_id for c in chunks], [c.chunk_id for c in fixed_size(page, 30, 5)])

    def test_fixed_does_not_duplicate_exact_tail(self):
        self.assertEqual(len(fixed_size(self.page('abcdefghij'), 10, 5)), 1)

    def test_invalid_overlap_does_not_loop_forever(self):
        for size, overlap in [(0, 0), (10, 10), (10, -1)]:
            with self.assertRaises(ValueError):
                fixed_size(self.page('abc'), size, overlap)

    def test_paragraphs_preserve_all_nonwhitespace(self):
        page = self.page('First paragraph.\n\nSecond paragraph has more words.\n\n' + 'x' * 83)
        self.assert_coverage(page, by_paragraph(page, 25), 25)

    def test_sentence_fallback_for_pdf_without_blank_lines(self):
        page = self.page('First sentence. Second sentence. Third sentence.')
        chunks = by_paragraph(page, 32)
        self.assertEqual(chunks[0].text, 'First sentence. Second sentence.')
        self.assert_coverage(page, chunks, 32)

    def test_empty_page_produces_no_chunks(self):
        self.assertEqual(by_paragraph(self.page('  \n'), 20), [])
        self.assertEqual(fixed_size(self.page('  \n'), 20, 2), [])

    def test_normalization_keeps_paragraphs_and_unicode(self):
        self.assertEqual(normalize_text(' e\u0301\t A\r\n\r\n\r\nB '), 'é A\n\nB')

    def test_pdf_formula_controls_do_not_reach_postgres_text(self):
        self.assertEqual(normalize_text('A\x00\x01 + B\x12\x13\nC'), 'A + B\nC')


class EmbeddingTests(unittest.TestCase):
    def embedder(self, **kwargs):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-only-not-a-real-key'}):
            return MyEmbedder('qwen/qwen3-embedding-8b', provider='openrouter', **kwargs)

    def response(self, rows):
        return io.BytesIO(json.dumps({'data': rows, 'usage': {'prompt_tokens': 7}}).encode())

    def test_response_reordered_by_index(self):
        response = self.response([{'index': 1, 'embedding': [0, 1]}, {'index': 0, 'embedding': [1, 0]}])
        with patch('src.embeddings.urlopen', return_value=response):
            self.assertEqual(self.embedder().embed_documents(['a', 'b']), [[1, 0], [0, 1]])

    def test_missing_index_is_not_silently_zipped(self):
        with patch('src.embeddings.urlopen', return_value=self.response([{'index': 2, 'embedding': [1, 0]}])):
            with self.assertRaises(EmbeddingError):
                self.embedder().embed_documents(['a'])

    def test_cache_reuses_vectors_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('src.embeddings.urlopen', return_value=self.response([{'index': 0, 'embedding': [1, 0]}])) as mock:
                first = self.embedder(cache_dir=Path(directory))
                self.assertEqual(first.embed_documents(['a', 'a']), [[1, 0], [1, 0]])
                second = self.embedder(cache_dir=Path(directory))
                self.assertEqual(second.embed_documents(['a']), [[1, 0]])
                self.assertEqual(mock.call_count, 1)
                self.assertEqual(second.dimensions, 2)

    def test_query_instruction_is_not_added_to_documents(self):
        embedder = self.embedder()
        with patch.object(embedder, '_request', return_value=[[1, 0]]) as mock:
            embedder.embed_query('Question?')
            self.assertTrue(mock.call_args.args[0][0].startswith('Instruct:'))
            embedder.embed_documents(['Document.'])
            self.assertEqual(mock.call_args.args[0], ['Document.'])

    def test_api_error_never_becomes_mock_vectors_or_leaks_body(self):
        error = HTTPError('https://example.test', 401, 'private body', {}, None)
        with patch('src.embeddings.urlopen', side_effect=error):
            with self.assertRaises(EmbeddingError) as captured:
                self.embedder().embed_documents(['a'])
        self.assertNotIn('private body', str(captured.exception))

    def test_dimension_nan_and_zero_rejected(self):
        for vector in ([0, 0], [float('nan'), 1], [True, 1], [1]):
            with self.assertRaises(ValueError):
                validate_vector(vector, 2)


class EvaluationTests(unittest.TestCase):
    def question(self):
        return dict(id='Q', split='dev', question='What?', expected_answer='Answer',
                    gold_source_id='p1', gold_page=2, evidence_quote='Full evidence.', filter=None)

    def hit(self, text, source='p1', page=2):
        return dict(text=text, document_id=source, page=page)

    def test_source_and_page_are_required(self):
        q = self.question()
        for hit in [self.hit('Full evidence.', 'p2'), self.hit('Full evidence.', page=3)]:
            self.assertFalse(evaluate_query(q, [hit])['hit_at_3'])

    def test_partial_evidence_across_two_chunks_does_not_count(self):
        result = evaluate_query(self.question(), [self.hit('Full'), self.hit('evidence.')])
        self.assertFalse(result['hit_at_3'])

    def test_top3_hit_is_not_top1_hit_and_whitespace_normalizes(self):
        result = evaluate_query(self.question(), [self.hit('Other'), self.hit('Full\nevidence.')])
        self.assertFalse(result['hit_at_1'])
        self.assertTrue(result['hit_at_3'])

    def test_alternative_gold_is_accepted(self):
        q = self.question()
        q['alternative_gold'] = [dict(gold_source_id='p2', gold_page=4, evidence_quote='Equivalent evidence.')]
        self.assertTrue(evaluate_query(q, [self.hit('Equivalent evidence.', 'p2', 4)])['hit_at_1'])

    def test_summary_reports_numerator_and_denominator(self):
        rows = [dict(strategy='A', split='dev', hit_at_1=False, hit_at_3=True),
                dict(strategy='A', split='dev', hit_at_1=False, hit_at_3=False)]
        row = summarize(rows)['A:dev']
        self.assertEqual((row['hit3_count'], row['questions'], row['hit_at_3']), (1, 2, .5))

    def test_selection_uses_dev_only(self):
        summary = {f'{s}:dev': {'hit_at_3': .5, 'hit_at_1': .2} for s in 'ABC'}
        summary['A:test'] = {'hit_at_3': 1, 'hit_at_1': 1}
        stats = {'A': {'characters': 200}, 'B': {'characters': 100}, 'C': {'characters': 100}}
        self.assertEqual(choose_on_dev(summary, stats), 'B')


if __name__ == '__main__':
    unittest.main()
