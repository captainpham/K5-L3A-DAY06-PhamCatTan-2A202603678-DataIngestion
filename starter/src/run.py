"""Điểm vào pipeline: prepare -> preflight -> ingest -> eval.

Mặc định chỉ prepare (không API/DB). `--stage all` chạy ingest + đánh giá dev.
Test cần selection.json được chốt trên dev, không tự dùng test để chọn cấu hình.
Đọc PIPELINE.md để xem sơ đồ file và các lệnh uv.
"""
import argparse
import importlib.metadata
import logging
import os
import platform
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .artifacts import (chunk_stats, prepare_coherence_audit, prepare_retrieval_audit,
                        write_csv, write_json, write_jsonl)
from .chunking import by_paragraph, fixed_size
from .corpus import file_hash, fingerprint, load_benchmark, load_corpus, read_json
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .store import PgVectorStore

BASE = Path(__file__).resolve().parents[1]
LOG = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['prepare', 'preflight', 'ingest', 'eval', 'all'], default='prepare')
    parser.add_argument('--split', choices=['dev', 'test'], default='dev')
    parser.add_argument('--selection', type=Path, help='selection.json tạo từ dev trước khi chạy test')
    parser.add_argument('--manifest', type=Path, default=BASE / 'data/manifest.json')
    parser.add_argument('--benchmark', type=Path, default=BASE / 'data/benchmark.json')
    parser.add_argument('--metadata', type=Path, default=BASE / 'data/benchmark_metadata.json')
    parser.add_argument('--results', type=Path, default=BASE / 'results')
    parser.add_argument('--size', type=int, default=500)
    parser.add_argument('--overlap', type=int, default=50)
    parser.add_argument('--paragraph-size', type=int, default=500)
    parser.add_argument('--batch-size', type=int, default=32)
    return parser.parse_args()


def choose_on_dev(summary: dict, statistics: dict) -> str:
    # Tiêu chí chốt trước test: Hit@3, Hit@1, ít tổng ký tự hơn, rồi A/B/C.
    # Không chọn bằng thời gian warm-cache vì B/C tái dùng embedding.
    return min('ABC', key=lambda s: (-summary[f'{s}:dev']['hit_at_3'],
                                    -summary[f'{s}:dev']['hit_at_1'],
                                    statistics[s]['characters'], s))


def execute(args, output: Path, state: dict) -> None:
    started = time.perf_counter()
    pages, page_audit = load_corpus(args.manifest, args.metadata, BASE)
    questions = load_benchmark(args.benchmark, pages)
    strategies = {
        'A': [c for p in pages for c in fixed_size(p, args.size, args.overlap)],
        'B': [c for p in pages for c in by_paragraph(p, args.paragraph_size)],
    }
    strategies['C'] = strategies['B']  # C chỉ thay filter, không thay chunking/metadata.
    statistics = {s: chunk_stats(chunks) for s, chunks in strategies.items()}
    for strategy, chunks in strategies.items():
        write_jsonl(output / f'chunks_{strategy}.jsonl', [asdict(c) for c in chunks])
    write_jsonl(output / 'pages.jsonl', [asdict(p) for p in pages])
    write_jsonl(output / 'page_extraction_audit.jsonl', page_audit)
    write_json(output / 'chunk_stats.json', statistics)
    prepare_coherence_audit(output, pages, strategies)
    # Hash code + data giúp chống trộn cache/index giữa các phiên bản thí nghiệm.
    data_config = {
        'manifest_sha256': file_hash(args.manifest), 'benchmark_sha256': file_hash(args.benchmark),
        'metadata_sha256': file_hash(args.metadata),
        'implementation_sha256': {name: file_hash(BASE / 'src' / name) for name in
                                   ['ingestion.py', 'chunking.py', 'embeddings.py', 'store.py', 'evaluation.py', 'corpus.py', 'run.py']},
        'strategies': {'A': {'method': 'fixed', 'size': args.size, 'overlap': args.overlap, 'filter': False},
                       'B': {'method': 'paragraph', 'size': args.paragraph_size, 'filter': False},
                       'C': {'method': 'paragraph', 'size': args.paragraph_size, 'filter': True}},
        'pages': len(pages), 'search': 'exact_cosine', 'top_k': 3,
    }
    state.update({'status': 'prepared', 'stage': args.stage, 'split': args.split,
                  'config': data_config, 'chunk_stats': statistics,
                  'python': platform.python_version(),
                  'libraries': {p: importlib.metadata.version(p) for p in ['pypdf', 'psycopg', 'python-dotenv']},
                  'corpus_review': 'Programmatic text checks only; visual content review remains required.',
                  'prepare_seconds': time.perf_counter() - started})
    write_json(output / 'run.json', state)
    print(f'Prepared {len(pages)} pages; chunks: ' + ', '.join(f'{s}={v["count"]}' for s, v in statistics.items()), flush=True)
    if args.stage == 'prepare':
        return

    model = os.getenv('EMBEDDING_MODEL', '').strip()
    dim = os.getenv('EMBEDDING_DIMENSIONS', '').strip()
    embedder = MyEmbedder(model, cache_dir=BASE / '.cache/embeddings',
                          batch_size=args.batch_size, dimensions=int(dim) if dim else None)
    # state giữ cùng object stats để khi có lỗi giữa chừng vẫn ghi được usage đã biết.
    state['api_usage'] = embedder.stats
    state['embedding'] = embedder.public_config()
    # Probe là input trung tính, không dùng một câu test để quyết định model.
    embedder.embed_documents(['Multiple instance learning represents a slide as a bag of patches.'])
    state['dimensions'] = embedder.dimensions
    experiment = {**data_config, 'embedding': embedder.public_config(), 'dimensions': embedder.dimensions}
    namespace = fingerprint(experiment)
    state['experiment_fingerprint'] = namespace
    store = PgVectorStore(os.getenv('DATABASE_URL', ''), embedder.dimensions, namespace=namespace)
    store.create_schema()
    state['database'] = store.server_info()
    if args.stage == 'preflight':
        state['status'] = 'preflight_ok'
        return

    # Trước khi đọc kết quả test, yêu cầu cấu hình đã được cố định từ dev.
    selection = None
    if args.split == 'test':
        if args.selection is None:
            raise ValueError('Chạy dev trước, rồi dùng --split test --selection <selection.json>.')
        selection = read_json(args.selection)
        if (selection.get('experiment_fingerprint') != namespace
                or selection.get('selected_on') != 'dev'
                or selection.get('selected_strategy') not in ('A', 'B', 'C')):
            raise ValueError('Selection không khớp model/corpus/benchmark/code/cấu hình hiện tại.')
        state['dev_selection'] = selection

    ingest_stats = {}
    if args.stage in ('ingest', 'all'):
        for strategy, chunks in strategies.items():
            tick = time.perf_counter()
            print(f'Embedding and storing {strategy}: {len(chunks)} chunks...', flush=True)
            before = dict(embedder.stats)
            vectors = embedder.embed_documents([c.text for c in chunks])
            store.upsert(strategy, chunks, vectors)
            first_ids = store.inventory(strategy)
            # Nạp lại cùng input bằng vector đã có: kiểm tra không nhân đôi, không tốn API.
            store.upsert(strategy, chunks, vectors)
            if first_ids != store.inventory(strategy) or first_ids != {c.chunk_id for c in chunks}:
                raise RuntimeError(f'Kiểm tra idempotency thất bại: {strategy}')
            ingest_stats[strategy] = {'seconds_including_reingest_check': time.perf_counter() - tick,
                                      'stored_chunks': len(first_ids), 'reingest_ids_equal': True,
                                      'usage_delta': {k: embedder.stats[k] - before[k] for k in before}}
        write_json(output / 'ingest_stats.json', ingest_stats)
        state['ingest_stats'] = ingest_stats
        state['status'] = 'ingested'
    if args.stage == 'ingest':
        return

    for strategy, chunks in strategies.items():
        if store.inventory(strategy) != {c.chunk_id for c in chunks}:
            raise RuntimeError(f'Index {strategy} thiếu hoặc khác snapshot; chạy --stage ingest trước.')
    traces = []
    for question in [q for q in questions if q['split'] == args.split]:
        # Query embedding chỉ nhận câu hỏi. Không gửi gold/answer/source hay filter vào embedding.
        vector = embedder.embed_query(question['question'])
        for strategy in 'ABC':
            filters = question.get('filter') if strategy == 'C' else None
            hits = store.search(strategy, vector, top_k=3, filters=filters)
            traces.append({'strategy': strategy, 'applied_filter': filters,
                           **evaluate_query(question, hits)})
        # Ghi tiến độ mỗi câu; có trace thực nếu API lỗi ở câu sau.
        write_jsonl(output / 'traces.jsonl', traces)
        print(f'Evaluated {question["id"]} ({args.split})', flush=True)
    summary = summarize(traces)
    write_json(output / 'summary.json', summary)
    write_csv(output / 'metrics.csv', list(summary.values()),
              ['strategy', 'split', 'questions', 'hit1_count', 'hit3_count', 'hit_at_1', 'hit_at_3'])
    prepare_retrieval_audit(output, traces)
    if args.split == 'dev':
        chosen = choose_on_dev(summary, statistics)
        selection = {'selected_strategy': chosen, 'experiment_fingerprint': namespace,
                     'selected_on': 'dev', 'dev_summary': summary,
                     'criteria': 'Hit@3 desc, Hit@1 desc, total chunk characters asc, strategy name asc',
                     'timestamp_utc': datetime.now(timezone.utc).isoformat()}
        write_json(output / 'selection.json', selection)
        print(f'Selected on dev: {chosen}. Freeze this selection before test.', flush=True)
    state['status'] = 'evaluated'
    state['summary'] = summary
    state['wall_seconds'] = time.perf_counter() - started
    for row in summary.values():
        print(f"{row['strategy']} {row['split']}: Hit@1={row['hit1_count']}/{row['questions']}, Hit@3={row['hit3_count']}/{row['questions']}", flush=True)


def main() -> None:
    args = parse_args()
    load_dotenv(BASE / '.env')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = args.results.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(output / 'pipeline.log', encoding='utf-8')],
                        format='%(asctime)s %(levelname)s %(message)s', force=True)
    state = {'run_id': run_id, 'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'status': 'started'}
    try:
        execute(args, output, state)
    except Exception as exc:
        # psycopg/HTTP exceptions đôi khi chứa connection info. Chỉ lưu lỗi custom
        # an toàn, còn backend errors dùng loại lỗi và hướng chẩn đoán.
        safe = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        for name in ('OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'DATABASE_URL'):
            secret = os.getenv(name)
            if secret:
                safe = safe.replace(secret, '[REDACTED]')
        state.update(status='failed', error_type=type(exc).__name__, error=safe)
        LOG.error('%s: %s', type(exc).__name__, safe)
        print(f'FAILED: {safe}. Xem run.json/pipeline.log; kiểm tra API credit hoặc Docker/.env.', flush=True)
        raise SystemExit(1) from None
    finally:
        write_json(output / 'run.json', state)
        print(f'Artifacts: {output}', flush=True)


if __name__ == '__main__':
    main()
