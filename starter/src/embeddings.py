"""Embedding API thật bằng urllib; cache không chứa key, không fallback vector giả."""
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, question: str) -> list[float]: ...


class EmbeddingError(RuntimeError):
    """Lỗi được lược bỏ thông tin xác thực trước khi ghi log."""


def validate_vector(values, dimensions: int = 0) -> list[float]:
    if not isinstance(values, list) or not values:
        raise ValueError('Vector phải là list số không rỗng.')
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) for x in values):
        raise ValueError('Vector chứa giá trị không phải số.')
    vector = [float(x) for x in values]
    if any(not math.isfinite(x) for x in vector) or not any(vector):
        raise ValueError('Vector phải hữu hạn và khác vector 0 để tính cosine.')
    if dimensions and len(vector) != dimensions:
        raise ValueError(f'Sai số chiều: cần {dimensions}, nhận {len(vector)}.')
    return vector


class MyEmbedder:
    def __init__(self, model_name: str, *, provider: str | None = None,
                 cache_dir: Path | None = None, batch_size: int = 32,
                 dimensions: int | None = None) -> None:
        if not model_name or batch_size <= 0:
            raise ValueError('Cần tên model và batch_size > 0.')
        self.model_name = model_name
        provider = provider or os.getenv('EMBEDDING_PROVIDER')
        if not provider:
            configured = [p for p, k in [('openrouter', 'OPENROUTER_API_KEY'),
                                         ('openai', 'OPENAI_API_KEY')] if os.getenv(k)]
            if len(configured) != 1:
                raise EmbeddingError('Đặt EMBEDDING_PROVIDER=openrouter hoặc openai trong .env.')
            provider = configured[0]
        endpoints = {
            'openrouter': ('https://openrouter.ai/api/v1/embeddings', 'OPENROUTER_API_KEY'),
            'openai': ('https://api.openai.com/v1/embeddings', 'OPENAI_API_KEY'),
        }
        if provider not in endpoints:
            raise EmbeddingError('Adapter hỗ trợ OpenRouter/OpenAI; không tự chuyển provider khác.')
        self.provider = provider
        self.endpoint, key_name = endpoints[provider]
        self._api_key = os.getenv(key_name)
        if not self._api_key:
            raise EmbeddingError(f'Thiếu {key_name}.')
        self.requested_dimensions = dimensions
        self.dimensions = dimensions or 0  # Phát hiện số chiều từ response, không đoán theo tên model.
        self.batch_size = batch_size
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        # Qwen model card: instruction chỉ thêm ở query, document giữ nguyên.
        self.query_instruction = ('Given a question, retrieve relevant passages from scientific papers.'
                                  if 'qwen3-embedding' in model_name.lower() else '')
        self.stats = {'api_requests': 0, 'cache_hits': 0, 'embedded_inputs': 0,
                      'prompt_tokens': 0, 'api_seconds': 0.0,
                      'reported_cost_usd': 0.0, 'responses_without_cost': 0}

    def public_config(self) -> dict:
        """Cấu hình được phép lưu; tuyệt đối không trả key hoặc header."""
        return {'provider': self.provider, 'model': self.model_name,
                'requested_dimensions': self.requested_dimensions,
                'query_instruction': self.query_instruction, 'document_prefix': '',
                'encoding_format': 'float'}

    def _cache_path(self, text: str) -> Path | None:
        if self.cache_dir is None:
            return None
        key = json.dumps([self.public_config(), text], ensure_ascii=False, sort_keys=True)
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest() + '.json')

    def _accept(self, values) -> list[float]:
        vector = validate_vector(values, self.dimensions)
        self.dimensions = len(vector)
        return vector

    def _request(self, texts: list[str]) -> list[list[float]]:
        body = {'model': self.model_name, 'input': texts, 'encoding_format': 'float'}
        if self.requested_dimensions:
            body['dimensions'] = self.requested_dimensions
        request = Request(self.endpoint, data=json.dumps(body).encode('utf-8'), headers={
            'Authorization': f'Bearer {self._api_key}', 'Content-Type': 'application/json'}, method='POST')
        for attempt in range(3):
            started = time.perf_counter()
            self.stats['api_requests'] += 1
            try:
                with urlopen(request, timeout=60) as response:
                    payload = json.load(response)
                break
            except HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                hints = {401: 'API key không hợp lệ', 402: 'thiếu credit',
                         404: 'model/endpoint không tồn tại', 429: 'rate limit'}
                raise EmbeddingError(f'Embedding HTTP {exc.code}: {hints.get(exc.code, "request bị từ chối")}.') from None
            except (URLError, TimeoutError, OSError):
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise EmbeddingError('Không kết nối được embedding API sau 3 lần thử.') from None
            finally:
                self.stats['api_seconds'] += time.perf_counter() - started
        if payload.get('error'):
            raise EmbeddingError('Provider trả lỗi thay cho embedding; không fallback mock.')
        rows = payload.get('data', [])
        if len(rows) != len(texts) or {r.get('index') for r in rows} != set(range(len(texts))):
            raise EmbeddingError('Response thiếu/trùng index; không thể ghép vector với text.')
        rows.sort(key=lambda row: row['index'])
        vectors = [self._accept(row.get('embedding')) for row in rows]
        usage = payload.get('usage') or {}
        self.stats['prompt_tokens'] += int(usage.get('prompt_tokens', usage.get('total_tokens', 0)))
        if usage.get('cost') is not None:
            self.stats['reported_cost_usd'] += float(usage['cost'])
        else:
            self.stats['responses_without_cost'] += 1
        self.stats['embedded_inputs'] += len(texts)
        return vectors

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError('Không gửi input rỗng tới embedding API.')
        found = {}
        missing = []
        for text in dict.fromkeys(texts):
            path = self._cache_path(text)
            if path and path.exists():
                found[text] = self._accept(json.loads(path.read_text(encoding='utf-8')))
                self.stats['cache_hits'] += 1
            else:
                missing.append(text)
        for start in range(0, len(missing), self.batch_size):
            batch = missing[start:start + self.batch_size]
            vectors = self._request(batch)
            for text, vector in zip(batch, vectors, strict=True):
                found[text] = vector
                path = self._cache_path(text)
                if path:
                    temporary = path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(vector), encoding='utf-8')
                    temporary.replace(path)
        return [found[text] for text in texts]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, question: str) -> list[float]:
        text = (f'Instruct: {self.query_instruction}\nQuery: {question}'
                if self.query_instruction else question)
        return self._embed([text])[0]
