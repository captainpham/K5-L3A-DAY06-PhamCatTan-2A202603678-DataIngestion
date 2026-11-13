"""Lưu bền vững trên PostgreSQL, exact cosine search + filter JSONB trong SQL.

namespace tách các thí nghiệm/model. Không có index ANN nên đây là exact search.
vector không khóa số chiều ở schema để nhiều thí nghiệm dùng cùng bảng; mọi
insert/query vẫn kiểm tra số chiều và chỉ truy vấn namespace của thí nghiệm.
"""
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .embeddings import validate_vector
from .models import Chunk


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int, *, namespace: str = 'day6') -> None:
        if not database_url or not namespace or not 1 <= dimensions <= 16000:
            raise ValueError('Cần database URL, namespace và 1..16000 chiều.')
        self._database_url = database_url
        self.dimensions = dimensions
        self.namespace = namespace

    def _connect(self):
        return psycopg.connect(self._database_url, connect_timeout=5, row_factory=dict_row)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
            conn.execute('''CREATE TABLE IF NOT EXISTS day6_chunks (
                namespace text NOT NULL,
                strategy text NOT NULL,
                chunk_id text NOT NULL,
                document_id text NOT NULL,
                source text NOT NULL,
                page integer NOT NULL CHECK (page > 0),
                text text NOT NULL,
                metadata jsonb NOT NULL,
                dimensions integer NOT NULL,
                embedding vector NOT NULL,
                CHECK (vector_dims(embedding) = dimensions),
                PRIMARY KEY (namespace, strategy, chunk_id)
            )''')

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Thay snapshot của đúng namespace/strategy trong MỘT transaction.

        Xóa snapshot cũ xử lý cả chunk biến mất khi PDF thay đổi. Nếu insert lỗi,
        transaction rollback giữ snapshot trước. Không đụng namespace khác.
        """
        if len(chunks) != len(vectors) or len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError('Số chunk/vector không khớp hoặc trùng chunk ID.')
        rows = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            values = validate_vector(vector, self.dimensions)
            if not chunk.text.strip():
                raise ValueError('Không lưu chunk rỗng.')
            if '\x00' in chunk.text:
                raise ValueError('Chunk còn NUL; cần normalize_text trước khi lưu PostgreSQL.')
            rows.append((self.namespace, strategy, chunk.chunk_id, chunk.document_id,
                         chunk.source, chunk.page, chunk.text, Jsonb(chunk.metadata),
                         self.dimensions, self._literal(values)))
        with self._connect() as conn:
            # Serialize hai writer của cùng namespace/strategy, tránh snapshot chồng nhau.
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                         (self.namespace + ':' + strategy,))
            conn.execute('DELETE FROM day6_chunks WHERE namespace=%s AND strategy=%s',
                         (self.namespace, strategy))
            with conn.cursor() as cur:
                cur.executemany('''INSERT INTO day6_chunks
                    (namespace,strategy,chunk_id,document_id,source,page,text,metadata,dimensions,embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)''', rows)

    @staticmethod
    def _literal(vector: list[float]) -> str:
        return '[' + ','.join(repr(x) for x in vector) + ']'

    def inventory(self, strategy: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute('''SELECT chunk_id FROM day6_chunks
                WHERE namespace=%s AND strategy=%s AND dimensions=%s''',
                (self.namespace, strategy, self.dimensions)).fetchall()
        return {r['chunk_id'] for r in rows}

    def server_info(self) -> dict:
        with self._connect() as conn:
            return conn.execute('''SELECT current_setting('server_version') AS postgres,
                (SELECT extversion FROM pg_extension WHERE extname='vector') AS pgvector''').fetchone()

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not 1 <= top_k <= 100:
            raise ValueError('top_k phải trong 1..100.')
        filters = filters or {}
        allowed = {'section_group', 'year', 'version', 'category', 'language', 'audience'}
        if not set(filters) <= allowed or any(isinstance(v, (list, dict)) for v in filters.values()):
            raise ValueError('Filter chỉ hỗ trợ các trường metadata được cho phép và giá trị scalar.')
        literal = self._literal(validate_vector(query_vector, self.dimensions))
        # <=> trả COSINE DISTANCE (nhỏ tốt). score=1-distance là similarity (lớn tốt).
        # Tất cả giá trị, kể cả JSON filter, đều truyền parameter; không nội suy SQL.
        with self._connect() as conn:
            rows = conn.execute('''SELECT chunk_id,document_id,source,page,text,metadata,
                1 - (embedding <=> %s::vector) AS score
                FROM day6_chunks
                WHERE namespace=%s AND strategy=%s AND dimensions=%s AND metadata @> %s
                ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s''',
                (literal, self.namespace, strategy, self.dimensions, Jsonb(filters), literal, top_k)).fetchall()
        return rows
