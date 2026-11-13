# Kiểm chứng triển khai phần 3

Ngày 13/11/2026, đã chạy trên Windows, môi trường uv của học viên và PostgreSQL Docker. Không commit/push trong quá trình triển khai.

## Kết quả đã chạy

- **25/25 test pass**, gồm 20 test offline và 5 test PostgreSQL thật. Test API dùng mock để kiểm tra hợp đồng; không dùng mock làm vector corpus.
- Validate benchmark: đủ 20 câu, 15 dev / 5 test; 4 câu có filter (3 dev, 1 test), gold có trong phần chữ của trang nguồn sau chuẩn hóa.
- Preflight API thật: OpenRouter `qwen/qwen3-embedding-8b`, vector **4096 chiều**, PostgreSQL **16.16**, pgvector **0.8.7**.
- Pipeline ingest/eval dev hoàn tất ở [results/20261113T113832345795Z](results/20261113T113832345795Z/run.json): 31 trang chọn, A=272 chunk, B=C=297 chunk.
- Nạp lại A/B/C bằng cùng vector xác nhận tập ID không thay đổi, không nhân đôi. Test DB xác nhận loại chunk cũ khi snapshot mới ngắn hơn và rollback giữ snapshot trước nếu insert lỗi.
- Cú pháp Python và `git diff --check` đạt; đã quét key cấu hình trong code, .env.example và artifact kết quả, không phát hiện key bị ghi ra ở phạm vi đã kiểm tra. `.env` và `.cache/` được gitignore.

| Strategy | Dev Hit@1 | Dev Evidence Hit@3 |
|---|---|---|
| A | 5/15 | 7/15 |
| B | 4/15 | 6/15 |
| C | 4/15 | 6/15 |

Pipeline chọn A theo tiêu chí đã chốt trên dev, ghi [selection.json](results/20261113T113832345795Z/selection.json). Chưa chạy retrieval trên 5 câu test, chưa có điểm test hoặc nhãn audit thủ công. `artifacts/experiment_log.csv` ở root đã ghi điểm dev thật; ô test để trống.

Đây là metric yêu cầu một chunk đúng trang chứa trọn excerpt, không phải điểm trả lời của LLM. Kết quả còn thấp; không điều chỉnh evidence hoặc test để tăng điểm. Khi audit cần phân biệt: retrieval sai trang, evidence bị cắt qua chunk, excerpt dài hơn chunk, và bằng chứng tương đương nhưng không khớp chuỗi. Chưa quy mọi miss cho một nguyên nhân duy nhất.

## Usage thực tế và lỗi đã xử lý

Lần dev thành công báo 26 request mới, 38,468 prompt tokens, cost provider trả về **0.00065672 USD**; 558 cache hits. Đây là chi phí của riêng lần chạy đó, đã tái dùng cache từ lần trước; không phải chi phí ingest lạnh độc lập của cả ba strategy.

Lần chạy trước [20261113T113638324603Z](results/20261113T113638324603Z/run.json) dừng ở `DataError` do glyph công thức PDF trích xuất ra ký tự NUL mà PostgreSQL không nhận. Provider đã báo 0.00040307 USD cho phần embedding chạy trước lỗi. Preflight trước đó báo 0.00000013 USD. Tổng chi phí provider đã báo của ba lần này là **0.00105992 USD**, không tính hoạt động bên ngoài pipeline hoặc chi phí upstream không được trả về. Lưu lại log lỗi thay vì nhận lần đó là thành công.

Đã sửa normalization để bỏ C0 controls vô hình, giữ newline/tab, ghi `control_characters_removed` trong metadata và cảnh báo theo trang. Cập nhật số ký tự manifest theo cách chuẩn hóa mới: **117,006 ký tự trên 31 trang chọn**. Gold vẫn xác minh được. Bỏ control không khôi phục ký hiệu công thức bị sai; vẫn cần đối chiếu trực quan.

## Phần còn do học viên thực hiện

- Xem lại trang PDF/gold để xác nhận chất lượng ngữ nghĩa, đặc biệt công thức, bảng và paper hai cột.
- Chấm coherence/metadata/grounding trong các CSV audit bằng nguồn thực; không nhận nhãn rỗng là Pass.
- Cố định cấu hình trên dev rồi chạy test theo PIPELINE.md, ghi giới hạn split và mẫu nhỏ.
- Hoàn thiện thông tin cá nhân và báo cáo, ghi rõ hỗ trợ của Codex và các kiểm chứng đã thực hiện.

Hướng dẫn chạy và giải thích từng module: [PIPELINE.md](PIPELINE.md).
