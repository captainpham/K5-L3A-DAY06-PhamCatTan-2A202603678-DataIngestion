# Báo cáo cá nhân — Day 6

- Họ và tên: Phạm Cát Tân
- MSSV: 2A202603678

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:** giải thích Multiple Instance Learning trong digital pathology; hai paper tiếng Anh [GCE-MIL v1](https://arxiv.org/abs/2605.17456v1) (CC BY 4.0) và [Symb-xMIL v2](https://arxiv.org/abs/2606.06224v2) (CC BY-NC-ND 4.0), giấy phép ghi theo metadata PDF. Từ 57 trang vật lý chọn 31 trang: GCE-MIL trang 1–9, 15–28 (23 trang); Symb-xMIL trang 2–9 (8 trang). Đếm theo trang vật lý PDF, không nhân bản, loại trang chỉ có tài liệu tham khảo và các trang ngoài phạm vi; không tính nội dung hình chưa xử lý. Nguồn, checksum và thống kê từng trang nằm trong [manifest](../../starter/data/manifest.json); chất lượng trích xuất vẫn cần đối chiếu trực quan.
- **Chuẩn hóa, lỗi và giới hạn:** dùng pypdf 6.21.4, Unicode NFC, chuẩn hóa khoảng trắng/ngắt dòng; bỏ ký tự điều khiển C0/NUL và ghi số lượng theo trang. NUL từ glyph công thức từng gây lỗi PostgreSQL, đã sửa và cập nhật manifest. Giữ nguồn/trang/offset; chưa OCR hoặc hiểu hình, bảng và công thức có thể mất cấu trúc. Nạp lại snapshot trong transaction không nhân đôi và loại chunk cũ.
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:** OpenRouter `qwen/qwen3-embedding-8b`, 4096 chiều; API không ghi revision trọng số cụ thể. Query có instruction cố định, document giữ nguyên. PostgreSQL 16.16 + pgvector 0.8.7, exact cosine search, top-3. Hit yêu cầu đúng nguồn/trang và một chunk chứa trọn evidence sau chuẩn hóa, chấp nhận alternative gold đã khai báo; không phải độ chính xác câu trả lời LLM. Python 3.12.16; lệnh chạy từ `starter/`:

```powershell
uv run python -X utf8 -m src.run --stage all --split dev
uv run python -X utf8 -m src.run --stage eval --split test --selection results/20261113T113832345795Z/selection.json
uv run python -X utf8 -m src.run --stage all --split dev --size 1000 --overlap 50 --paragraph-size 1000
```

- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:** `document_id`, `source`, `page`; bổ sung `section_group` từ heading/phạm vi trang trong [ánh xạ metadata](../../starter/data/benchmark_metadata.json), `version` từ phiên bản paper và offset từ text. `section_group=main/appendix` giúp lọc nội dung chính/phụ lục; nguồn/trang hỗ trợ truy vết. Chỉ lọc khi câu hỏi nêu phạm vi, không lấy gold source/page làm filter.

## Cấu hình và benchmark

- **A / B / C:** baseline A chia cố định 500 ký tự, overlap 50; B gom đoạn, tối đa 500 ký tự, không overlap, fallback ranh giới câu khi PDF mất dòng trống; C dùng đúng chunk/metadata của B, chỉ thêm filter lúc truy xuất. Thử nghiệm tiếp theo tăng giới hạn A/B/C lên 1.000 ký tự, giữ overlap A=50. Cùng corpus, embedding và top-3; A–B so cách chunking, B–C chỉ khác filter.
- **Bộ câu hỏi:** [benchmark](../../starter/data/benchmark.json) có 20 câu tiếng Việt, evidence tiếng Anh; Q01–Q15 dev, Q16–Q20 test, chia trước lần retrieval đầu tiên. Q02/Q09/Q12/Q17 có filter, Q17 thuộc test. Đã kiểm tra tự động 20 đoạn evidence có trên đúng trang sau chuẩn hóa và thực hiện review nội dung top-3 của cả 5 câu test cho A/B/C. Gold còn thiếu một số đoạn tương đương, thể hiện ở Q01 và Q18; không sửa benchmark sau khi xem test.
- **Tiêu chí chọn trước test:** ưu tiên dev Hit@3, rồi Hit@1, ít tổng ký tự chunk hơn và thứ tự A/B/C khi hòa. Baseline chọn A trước test. Thử nghiệm 1.000 ký tự diễn ra sau khi đã xem test baseline, nên không coi đây là kiểm tra holdout mới.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A — 500 | dev | 5/15 | 7/15 | 272 | 8,39 s | 0,00006244 USD |
| B — 500 | dev | 4/15 | 6/15 | 297 | 54,85 s | 0,00058517 USD |
| C — 500 | dev | 4/15 | 6/15 | 297 | 5,40 s | 0 USD mới, tái dùng vector B |
| A — 500 | test | 1/5 | 1/5 | 272 | Chung cả lượt test | Chung cả lượt test |
| B — 500 | test | 3/5 | 3/5 | 297 | Chung cả lượt test | Chung cả lượt test |
| C — 500 | test | 3/5 | 3/5 | 297 | Chung cả lượt test | Chung cả lượt test |
| A — 1.000 | dev | 5/15 | 9/15 | 135 | 41,46 s | 0,00037737 USD |
| B — 1.000 | dev | 5/15 | 7/15 | 149 | 33,10 s | 0,00035515 USD |
| C — 1.000 | dev | 5/15 | 7/15 | 149 | 2,53 s | 0 USD mới, tái dùng vector B |

Thời gian/chi phí từng strategy ở hàng dev là **ingest gồm kiểm tra nạp lại**, chưa gồm retrieval. Cả lượt baseline dev: 93,38 s / 0,00065672 USD; baseline test: 79,69 s / 0,00000383 USD; dev 1.000: 81,03 s / 0,00073252 USD. Chi phí do provider trả về, có cache; không phải chi phí chạy lạnh độc lập. Tổng ba lượt này 0,00139307 USD, chưa gồm setup, lần lỗi và thí nghiệm chẩn đoán khác. Chưa có artifact test 1.000 để đưa vào bảng.

Bảng audit dưới đây dành cho baseline 500. Tôi sử dụng Codex hỗ trợ đọc từng chunk/top-3, đối chiếu text và trang PDF đã render, gán nhãn theo rubric 0–2 và ghi lý do/reviewer trong CSV. Metadata được đối chiếu nguồn, trang, offset text và phạm vi section. Đây là đánh giá có LLM hỗ trợ, chưa có người chấm độc lập; không suy coherence/grounding trực tiếp từ điểm Hit.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A — 500 | 1,00/2 (10) | 15/15 | 0/1 | 0: 0; 1: 3; 2: 2 — 1,40/2 |
| B — 500 | 1,10/2 (10) | 15/15 | 0/1 | 0: 0; 1: 2; 2: 3 — 1,60/2 |
| C — 500 | 1,10/2 (10) | 15/15 | 1/1 | 0: 0; 1: 2; 2: 3 — 1,60/2 |

Metadata đúng không đồng nghĩa retrieval đúng: Q17 của A/B trỏ đúng nguồn/trang nhưng ngoài phạm vi main, nên filter chỉ đạt 0/1. Grounding Q16 của A thiếu coverage target 0,95; Q17 của cả ba thiếu danh sách đầy đủ theo phạm vi yêu cầu; Q19 thiếu giới hạn hypothesis-generating. Q18 của A vẫn đủ đáp án 39 query dù mất phần đầu excerpt: review xác nhận bằng chứng tương đương trên cùng trang 6, ghi riêng trong `equivalent_evidence_override`. Nếu tính bổ sung trường hợp này, A test có Hit@1/Hit@3 sau review là 2/5; bảng retrieval phía trên giữ nguyên điểm tự động 1/5 để đối chiếu.

Coherence ở 1.000 ký tự: A đạt 1,18/2 trên 11 chunk phủ cùng 10 vị trí (trang 6 có hai chunk overlap); B/C đạt 1,50/2 trên 10 chunk. Nhãn B/C giống nhau vì dùng cùng chunk. Các bảng số thiếu header và công thức bị dàn phẳng vẫn làm giảm độ mạch lạc dù tăng kích thước.

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:** [baseline dev](../../starter/results/20261113T113832345795Z/traces.jsonl), [baseline test](../../starter/results/20261113T115914660698Z/traces.jsonl), [dev 1.000](../../starter/results/20261113T124446335645Z/traces.jsonl). Coherence chọn cùng midpoint của 10 trang đầu đã sắp theo document/page (GCE-MIL trang 1–9 và 15), nhãn ghi trong `coherence_audit.csv` của cả ba thư mục; bản baseline dev/test dùng cùng mẫu. Metadata/grounding lấy toàn bộ Q16–Q20 × top-3 của mỗi strategy, nhãn ở [metadata_audit.csv](../../starter/results/20261113T115914660698Z/metadata_audit.csv) và [grounding_audit.csv](../../starter/results/20261113T115914660698Z/grounding_audit.csv). Các mẫu metadata/grounding của dev không nằm trong audit test này. Reviewer được ghi là Codex, ngày 14/11/2026, có lý do cụ thể cho từng nhãn.

## Phân tích và kết luận

- **So sánh A–B và B–C; hai ví dụ lỗi:** A có dev Hit@3 cao hơn B ở cả 500 và 1.000 ký tự, nhưng baseline test B/C tốt hơn A. Trên mẫu audit, B/C có coherence và grounding cao hơn A; chênh lệch coherence baseline chỉ 0,10/2 trên mẫu nhỏ, chưa chứng minh ưu thế tổng quát. B không mặc nhiên giữ trọn ý: 262/297 chunk baseline dùng fallback câu và không có overlap. C lọc đúng phạm vi nhưng không tăng Hit so với B; Q17 loại được các trang phụ lục mà vẫn chưa tìm đủ gold. **Q05, A–500, GCE-MIL trang 6:** có đúng trang trong top-3 nhưng evidence bị chia qua chunk, nên miss. **Q01, B–500:** top-1 GCE-MIL trang 3 nêu đủ Sufficiency/Necessity/Recoverability, nhưng gold chỉ ghi trang 1 nên bị chấm miss; đây là thiếu alternative gold, không phải hoàn toàn thiếu đáp án.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** A–500 là lựa chọn baseline chốt trước test; test chỉ đạt 1/5 nên chưa đủ cơ sở triển khai. A–1.000 tốt nhất trên dev với 9/15, giảm số chunk và giữ thêm ngữ cảnh; chưa có test độc lập để khẳng định tốt hơn ngoài dev. Chunk dài hơn cũng có thể thêm nội dung nhiễu. Giữ câu hỏi tiếng Việt và tài liệu tiếng Anh.
- **Hạn chế:** hai paper, 5 câu test, split không cách ly paper; gold chưa bao quát bằng chứng tương đương, metric full-excerpt khá chặt. Audit có LLM hỗ trợ, không được thực hiện độc lập với việc đã xem điểm retrieval nên có nguy cơ thiên lệch; chưa kiểm chứng trực quan toàn bộ corpus. Bảng/công thức PDF có thể sai cấu trúc. Tăng chunk sau khi xem test baseline phải được công khai; không dùng test để đổi lựa chọn rồi nhận là holdout. Cache, mạng và retry ảnh hưởng thời gian/chi phí. Code và benchmark có hỗ trợ Codex; kiểm thử chức năng không thay thế đánh giá chất lượng nội dung.
- **Nếu làm lại/mở rộng:** kiểm chứng và bổ sung bằng chứng tương đương trước khi chạy; cải thiện tách heading/đoạn và xử lý ranh giới câu; thử kích thước/overlap có kiểm soát trên dev; tạo tập test mới chưa được dùng để chỉnh cấu hình. Mở rộng mẫu audit và bổ sung người chấm độc lập để kiểm tra độ nhất quán của nhãn.
