"""Test DB thật, namespace test riêng; synthetic vector chỉ để kiểm tra SQL.

Bật bằng DAY6_TEST_DATABASE_URL. Không thay vector của pipeline corpus bằng fixture.
"""
import os
import unittest
import uuid

from src.models import Chunk
from src.store import PgVectorStore


@unittest.skipUnless(os.getenv('DAY6_TEST_DATABASE_URL'), 'Set DAY6_TEST_DATABASE_URL to run real PostgreSQL tests.')
class StoreIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = PgVectorStore(os.environ['DAY6_TEST_DATABASE_URL'], 2, namespace='unit-test-' + uuid.uuid4().hex)
        self.store.create_schema()
        self.main = Chunk('one', 'paper', 'file.pdf', 1, 'main text', {'section_group': 'main'})
        self.appendix = Chunk('two', 'paper', 'file.pdf', 2, 'appendix text', {'section_group': 'appendix'})
        self.store.upsert('A', [self.main, self.appendix], [[1, 0], [0, 1]])

    def tearDown(self):
        with self.store._connect() as conn:
            conn.execute('DELETE FROM day6_chunks WHERE namespace=%s', (self.store.namespace,))

    def test_cosine_rank_and_sql_filter(self):
        self.assertEqual(self.store.search('A', [1, 0])[0]['chunk_id'], 'one')
        hits = self.store.search('A', [1, 0], filters={'section_group': 'appendix'})
        self.assertEqual([h['chunk_id'] for h in hits], ['two'])

    def test_reingest_removes_obsolete_chunks(self):
        self.store.upsert('A', [self.main], [[1, 0]])
        self.store.upsert('A', [self.main], [[1, 0]])
        self.assertEqual(self.store.inventory('A'), {'one'})

    def test_invalid_dimensions_do_not_erase_existing_snapshot(self):
        with self.assertRaises(ValueError):
            self.store.upsert('A', [self.main], [[1, 0, 0]])
        self.assertEqual(self.store.inventory('A'), {'one', 'two'})

    def test_failed_transaction_restores_old_snapshot(self):
        invalid = Chunk('invalid', 'paper', 'file.pdf', 0, 'invalid page', {})
        with self.assertRaises(Exception):
            self.store.upsert('A', [invalid], [[1, 0]])
        self.assertEqual(self.store.inventory('A'), {'one', 'two'})

    def test_filter_value_cannot_inject_sql(self):
        self.assertEqual(self.store.search('A', [1, 0], filters={'section_group': "main' OR true --"}), [])
        self.assertEqual(self.store.inventory('A'), {'one', 'two'})
