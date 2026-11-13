# Pipeline phần 3 — cách chạy và đọc code

Chạy các lệnh dưới đây từ `starter/`, dùng môi trường uv đã cài `requirements.txt`. Không cần SDK embedding mới: adapter gọi HTTPS bằng `urllib` có sẵn trong Python. Database phải có `Setup OK`.

## Luồng dữ liệu

1. `corpus.py` đọc manifest, kiểm tra checksum PDF và chỉ lấy `included_pages`. Nó kiểm chứng gold của bộ câu hỏi có trong đúng trang trước khi gọi API.
2. `ingestion.py` trích chữ từng trang và chuẩn hóa Unicode/whitespace; không OCR, không hiểu ảnh, không tự sửa công thức.
3. `chunking.py` tạo A theo cửa sổ ký tự, B theo đoạn/câu; C dùng đúng chunk của B.
4. `embeddings.py` gửi document/query tới provider thật. Query Qwen có instruction tiếng Anh cố định theo model card; document không thêm prefix. Không dùng đáp án/gold để tạo query.
5. `store.py` lưu vector thật trong PostgreSQL + pgvector. Truy xuất dùng cosine distance và SQL JSONB filter; không tính vector search bằng Python và không có fallback mock.
6. `evaluation.py` so source/page và toàn bộ evidence trong một chunk, tính Hit@1/Hit@3. Đây là metric tự động bảo thủ; bằng chứng tương đương cần được kiểm tra thủ công.
7. `artifacts.py` xuất CSV/JSONL để đọc lại; coherence/metadata/grounding để trống cho người chấm, không suy nhãn người từ string matching.
8. `run.py` nối các bước, lưu cấu hình/hash/phiên bản/usage, chặn việc đánh giá test khi chưa có selection đã chốt từ dev.

## Cấu hình

Giữ `DATABASE_URL` và API key trong `.env`. Cấu hình đang dùng:

```dotenv
EMBEDDING_PROVIDER=openrouter
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
```

Không cần thêm provider nếu chỉ có một key OpenRouter được cấu hình. Không commit `.env`. Nếu dùng OpenAI trực tiếp, adapter cũng hỗ trợ `EMBEDDING_PROVIDER=openai` và `OPENAI_API_KEY`; Gemini/local chưa được implement trong adapter này. Không tự chuyển sang provider khác khi lỗi.

Số chiều được phát hiện từ response, không cần điền tay. `EMBEDDING_DIMENSIONS` là tùy chọn chỉ dùng khi provider/model hỗ trợ yêu cầu số chiều; thay nó sẽ tạo profile/cache khác. Không cắt hoặc pad vector âm thầm.

## Các lệnh

### 1. Chuẩn bị offline — không API và không database

```powershell
uv run python -X utf8 -m src.run --stage prepare
```

Đọc 31 trang đã chọn, tạo chunk và các file xem trước. Mặc định `uv run python -m src.run` cũng chỉ chạy prepare để tránh gọi API ngoài ý muốn.

### 2. Kiểm tra một request embedding và kết nối pgvector

```powershell
uv run python -X utf8 -m src.run --stage preflight
```

Probe dùng một câu trung tính, không dùng câu test. Có thể phát sinh chi phí API nhỏ; các lần lặp cùng input dùng cache nếu đã có.

### 3. Ingest và benchmark dev

```powershell
uv run python -X utf8 -m src.run --stage all --split dev
```

Mỗi stage tạo thư mục mới `results/<run_id>/`; terminal in đường dẫn cuối cùng. Lệnh trên thực hiện API embedding, ghi database, kiểm tra nạp lại không nhân đôi và đánh giá 15 câu dev cho A/B/C. Model hiện tại phục vụ câu hỏi tiếng Việt trên paper tiếng Anh nên đây còn là một yếu tố truy xuất xuyên ngôn ngữ cần ghi trong báo cáo.

Chỉ ingest, chưa đánh giá:

```powershell
uv run python -X utf8 -m src.run --stage ingest
```

Đánh giá dev lại từ index đã có:

```powershell
uv run python -X utf8 -m src.run --stage eval --split dev
```

`selection.json` chốt cấu hình theo dev: ưu tiên Hit@3, sau đó Hit@1, ít tổng ký tự chunk hơn khi hòa, rồi thứ tự A/B/C. Tổng ký tự là proxy tài nguyên, không phải token chính xác hay chi phí API. Thời gian B/C có lợi do cache, nên không dùng thời gian warm-cache để chọn.

### 4. Test sau khi cố định cấu hình

```powershell
uv run python -X utf8 -m src.run --stage eval --split test --selection results/<run_id_dev>/selection.json
```

Thay `<run_id_dev>` bằng thư mục dev thật. Đây là placeholder hướng dẫn, không dán nguyên ký tự `< >` vào PowerShell. Lệnh báo cả A/B/C để so sánh nhưng giữ lựa chọn từ dev; không tạo lựa chọn mới từ test. Selection phải khớp corpus, benchmark, model, số chiều, code và tham số hiện tại. Nếu đã xem test để sửa cấu hình, công khai việc đó và không nhận là đánh giá độc lập.

## Ba cấu hình mặc định

| Cấu hình | Chunk | Truy xuất |
|---|---|---|
| A | 500 ký tự, overlap 50 | Exact cosine, không filter |
| B | Gom đoạn/câu, tối đa 500 ký tự | Exact cosine, không filter |
| C | Giống hoàn toàn B | Exact cosine, áp dụng filter có trong câu hỏi |

Cả ba giữ cùng metadata, corpus, model, query embedding và top-3. A–B đo thay đổi chunking; B–C chỉ thay filter. Không có filter trong câu hỏi thì C cũng không lọc. Filter lấy từ ngữ cảnh người dùng trong benchmark, không suy từ gold.

Đổi tham số trên dev bằng `--size`, `--overlap`, `--paragraph-size`. Không dùng test để lựa chọn. Vì PDF thường mất ngắt đoạn, B dùng heuristic câu nếu không có dòng trống; bảng/công thức và viết tắt vẫn có thể bị tách chưa tốt.

## Đầu ra để kiểm chứng

| File trong `results/<run_id>/` | Ý nghĩa |
|---|---|
| `run.json` | Trạng thái, cấu hình, hash, số chiều, phiên bản, usage và lỗi nếu có |
| `pipeline.log` | Log trang rỗng/lỗi; có thể rỗng khi không có cảnh báo |
| `pages.jsonl`, `page_extraction_audit.jsonl` | Text trang được chọn và thống kê tất cả trang |
| `chunks_A/B/C.jsonl`, `chunk_stats.json` | Nội dung, metadata, offset và phân bố độ dài chunk |
| `ingest_stats.json` | Thời gian và bằng chứng nạp lại không nhân đôi; có ở stage ingest/all |
| `traces.jsonl` | Câu hỏi, gold, top-3, score và filter thực tế; ghi sau từng câu |
| `summary.json`, `metrics.csv` | Tử số/mẫu số và Hit@1/Hit@3 theo strategy/split |
| `selection.json` | Lựa chọn chốt bằng dev |
| `coherence_audit.csv` | Chunk phủ cùng 10 vị trí nguồn, nhãn 0–2 để trống |
| `grounding_audit.csv`, `metadata_audit.csv` | Mẫu chấm tay cho split đang chạy, nhãn để trống |

Coherence/grounding 0–2 và metadata đúng/đủ vẫn do học viên kiểm chứng từ PDF. `visual_reviewed: false` trong manifest không tự chuyển thành true khi chạy code. Bộ test chỉ có 5 câu và split không cách ly paper, nên không suy rộng kết quả ngoài corpus.

`api_usage` chỉ ghi lượt gọi/token/cost provider trả về cho lần chạy này; cache không bị tính như request mới. Nếu `responses_without_cost > 0`, cost trả về là chưa đầy đủ, không được kết luận miễn phí. Lượt retry thất bại có thể có chi phí upstream chưa biết. B/C tái dùng vector nên không cộng chi phí B/C như các lần chạy lạnh độc lập. Không quy đổi USD sang VND tự động.

Cache ở `.cache/embeddings/`, đã được gitignore. Key cache dựa trên provider/model/cách xử lý input và text; không có API key. Thay PDF hoặc code/params tạo namespace mới; nạp lại cùng namespace/strategy thay snapshot trong transaction, xóa chunk cũ. Dữ liệu namespace khác không bị xóa. Trong lab nhỏ dùng exact search; vector 4096 chiều không cần tạo index ANN.

## Chạy kiểm thử

Offline, không tốn API:

```powershell
uv run python -X utf8 -m unittest discover -s tests -v
```

Mặc định 5 test DB sẽ skip. Để chạy cả test PostgreSQL thật mà không hiện URL/mật khẩu:

```powershell
@'
import os
import unittest
from dotenv import load_dotenv
load_dotenv('.env')
os.environ['DAY6_TEST_DATABASE_URL'] = os.environ['DATABASE_URL']
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests'))
raise SystemExit(not result.wasSuccessful())
'@ | uv run python -X utf8 -
```

Test DB dùng namespace tạm và xóa đúng namespace đó sau test. Vector fixture chỉ phục vụ test SQL; pipeline corpus dùng embedding API thật.

## Nguồn kỹ thuật

- [OpenRouter embeddings API](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request)
- [Qwen3-Embedding-8B model card](https://huggingface.co/Qwen/Qwen3-Embedding-8B)
- [pgvector: exact search và cosine distance](https://github.com/pgvector/pgvector)
- [Psycopg JSONB adaptation](https://www.psycopg.org/psycopg3/docs/basic/adapt.html)

Code có chú thích để học viên kiểm tra, thay đổi và giải thích trong báo cáo; không thay thế audit dữ liệu hay báo cáo cá nhân.
