# Starter · PostgreSQL + pgvector

> Xem [PIPELINE.md](PIPELINE.md) để đọc giải thích code, đầu ra, giới hạn và các lệnh uv. Bắt đầu bằng `uv run python -X utf8 -m src.run --stage prepare`, rồi dùng `--stage all --split dev` khi muốn gọi API và ingest.

Bản làm bài cá nhân dùng Docker Compose tạo PostgreSQL + pgvector local. Pipeline trong `src/` đã triển khai đọc PDF, chunking, embedding API thật, lưu/tìm vector và benchmark; không có chatbot hay model đọc ảnh. Audit thủ công và báo cáo vẫn do học viên hoàn thiện theo [GUIDE.md](../GUIDE.md).

## Cấu trúc

```text
starter/
├── docker-compose.yml     # PostgreSQL 16 + pgvector, chỉ mở cổng local
├── init.sql               # bật extension khi tạo database mới
├── requirements.txt       # psycopg, pypdf và python-dotenv
├── .env.example           # cấu hình mẫu; copy thành .env
├── scripts/check_setup.py # kiểm tra kết nối và extension (đã chạy được)
├── src/
│   ├── models.py          # cấu trúc dữ liệu mẫu
│   ├── ingestion.py       # đọc / chuẩn hóa tài liệu, ghi lỗi PDF
│   ├── chunking.py        # fixed-size và đoạn/câu
│   ├── embeddings.py      # OpenRouter/OpenAI, cache, kiểm tra vector
│   ├── store.py           # snapshot pgvector, exact cosine, JSONB filter
│   ├── evaluation.py      # chấm evidence retrieval, không giả nhãn audit
│   ├── corpus.py          # đọc manifest, chọn trang và kiểm tra gold
│   ├── artifacts.py       # xuất JSON/CSV và mẫu chấm tay
│   └── run.py             # điều phối từng stage và khóa lựa chọn dev
├── data/                  # bạn tự chuẩn bị corpus được phép sử dụng
└── results/               # lưu kết quả của bạn
```

## 1. Cài và kiểm tra database

Cần Docker Desktop hoặc Docker Engine + Compose, Python **3.11–3.14**, và mạng để tải image/dependencies lần đầu. Các lệnh sau chạy từ thư mục `starter/`:

```powershell
uv venv --python 3.12
```

Nếu đã có `.venv` đang hoạt động thì bỏ qua bước tạo lại. Dùng `uv run` nên không cần kích hoạt môi trường trong PowerShell. Sau đó:

```powershell
uv pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose -p day6_student_starter up -d --wait
uv run python scripts/check_setup.py
```

Kỳ vọng: hiện tên database, phiên bản PostgreSQL và pgvector, sau đó `Setup OK`. Đây **chỉ là kiểm tra hạ tầng**, không phải kết quả benchmark. Docker dùng cổng `127.0.0.1:55433` và mật khẩu cố định **chỉ dùng local cho lab**; nếu cổng bận, sửa đồng thời port trong `docker-compose.yml` và `DATABASE_URL` trong `.env`. `init.sql` chỉ chạy khi volume mới được tạo; nếu database sẵn có chưa bật extension, xem log Docker và kiểm tra cấu hình thay vì xóa volume chứa dữ liệu.

Dừng container nhưng giữ dữ liệu:

```bash
docker compose -p day6_student_starter stop
```

## 2. Chọn embedding model

Điền `EMBEDDING_MODEL` và key tương ứng trong `.env`; **không commit `.env`**. Adapter hiện hỗ trợ OpenRouter/OpenAI qua urllib, không cần SDK mới; Gemini/local chưa được triển khai. Số chiều thực được lấy từ API và ghi vào run.json. Cùng model và cách xử lý document/query được dùng cho cả A/B/C. Xem [PIPELINE.md](PIPELINE.md) về cache và instruction cho query Qwen.

## 3. Hoàn thiện pipeline

1. Đặt corpus vào `data/` hoặc cung cấp manifest/hướng dẫn truy cập. Đọc [GUIDE.md](../GUIDE.md) về **30 trang nội dung**, quyền dữ liệu và metadata.
2. Các hàm trong `src/` đã triển khai. Chạy `uv run python -X utf8 -m src.run --stage prepare` để kiểm tra manifest, gold và xem chunk trước khi gọi API.
3. Xây ít nhất ba cấu hình; ví dụ A fixed-size, B theo đoạn, C như B nhưng có filter. Cần cùng corpus, model và benchmark; nạp lại không nhân đôi và xử lý chunk cũ khi dữ liệu đổi.
4. Tự viết ít nhất 20 câu hỏi kèm evidence, tách dev/test trước khi thử theo [BENCHMARK.md](../BENCHMARK.md). Lưu trace top-3 và báo cáo đủ năm tiêu chí.
5. Chạy `uv run python -X utf8 -m src.run --stage all --split dev` từ `starter/`. Khi đã cố định cấu hình theo dev, dùng `--stage eval --split test --selection <đường-dẫn-selection.json>`. Hướng dẫn đầy đủ trong [PIPELINE.md](PIPELINE.md).

Lưu code, cấu hình, kết quả và lệnh chạy để người chấm tái lập; không commit key, dữ liệu mật hoặc dữ liệu không có quyền chia sẻ.
