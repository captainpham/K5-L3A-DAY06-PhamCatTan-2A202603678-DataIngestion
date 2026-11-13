# Bộ câu hỏi MIL papers v1

`benchmark.json` chứa object có danh sách `questions`: 20 câu tiếng Việt, đáp án tiếng Việt và bằng chứng tiếng Anh giữ nguyên từ PDF. Pipeline cần đọc `payload["questions"]`.

- Q01–Q15: dev; Q16–Q20: test. Hai split được thiết kế trước khi chạy retrieval; chưa có điểm embedding/retrieval.
- Filter ở Q02, Q09, Q12 và Q17; Q17 thuộc test. `filter: null` nghĩa là không lọc, kể cả với cấu hình C.
- `gold_source_id` khớp `DocumentPage.document_id` khi dùng tên file không có `.pdf`, như lệnh đọc PDF đã chạy. `gold_page` là số trang vật lý, bắt đầu từ 1, không phải số trang in trên bài.
- Câu hỏi gồm trực tiếp, diễn đạt lại, điều kiện và giới hạn kết luận. Không hỏi đọc thông tin chỉ có trong ảnh. Các câu về kết quả nghiên cứu chỉ đánh giá truy xuất phát biểu của tác giả, không xác nhận tính đúng đắn của nghiên cứu hoặc tạo lời khuyên y tế.

## Nguồn và metadata

`benchmark_metadata.json` định nghĩa `section_group` theo các heading của tài liệu: GCE-MIL trang 1–9 là nội dung chính, trang 15–28 là phụ lục; Symb-xMIL trang 2–9 là nội dung chính trong phạm vi được chọn. Đây là 31 trang ứng viên, không thay thế kiểm tra chất lượng từng trang hay manifest về nguồn/giấy phép.

Khi đọc tài liệu, gán `page.metadata["section_group"]` từ ánh xạ này và giữ trường đó ở chunk. Cả A/B/C đều nhận cùng metadata; chỉ C áp dụng filter đã có sẵn trong câu hỏi. Phạm vi “nội dung chính” hoặc “phụ lục” được nêu trực tiếp trong câu hỏi trước truy xuất; không dùng gold source/page/answer để tạo filter. Giá trị filter không phải tên paper hoặc ID đáp án.

`manifest.json` đã được điền cho hai PDF và phạm vi trang trong `benchmark_metadata.json`. Script sinh manifest đã được bỏ theo lựa chọn của học viên; manifest là file cấu hình được quản lý riêng, không tự sinh khi Docker khởi động. Khi thay dữ liệu, cập nhật checksum, trang, số ký tự và ghi chú review trong manifest. Ngày truy cập là ngày kiểm tra file local, không khẳng định ngày tải gốc. Ký tự điều khiển từ glyph công thức được loại ở bước chuẩn hóa; số ký tự đã loại được ghi để audit. Kiểm tra trực quan các trang vẫn cần thực hiện trước khi chốt chất lượng corpus.

Nếu dùng ID tài liệu khác thì đổi ID đồng bộ trong manifest, benchmark, metadata và code, trước khi chạy thí nghiệm. Không đọc toàn bộ 57 trang rồi vô tình đưa trang tham khảo ngoài phạm vi vào index.

## Kiểm chứng và hạn chế

Chạy từ thư mục `starter/`:

```powershell
uv run python -X utf8 scripts/validate_benchmark.py
```

Script xác minh cấu trúc, split, filter và từng excerpt có trong đúng trang sau chuẩn hóa. Bộ câu hỏi được hỗ trợ soạn bằng Codex từ phần chữ của hai PDF; `verification.visual_pdf_review` còn là `false` vì chưa đối chiếu trực quan toàn bộ 20 đoạn với bản render PDF. Học viên cần đọc lại đáp án và evidence, nhất là ký hiệu công thức và chữ xuống dòng. Kiểm tra substring không chứng minh đầy đủ ngữ nghĩa hoặc chất lượng bố cục.

`alternative_gold` ghi thêm vị trí có cùng excerpt trong phạm vi đã chọn nếu tìm thấy. Danh sách không bao quát mọi cách diễn đạt tương đương; khi audit cần chấp nhận nguồn bằng chứng hợp lệ khác có hỗ trợ đầy đủ đáp án và ghi lại cách chấm, không chỉ so khớp ID cứng.

## Cố định trước thử nghiệm

Giữ nguyên bộ câu hỏi, phạm vi corpus, embedding model và metric giữa A/B/C. Chọn cấu hình bằng dev: ưu tiên Evidence Hit@3, sau đó Hit@1, rồi ít tổng ký tự chunk hơn khi hòa (proxy tài nguyên, không phải token chính xác), cuối cùng thứ tự A/B/C. Sau khi chốt cấu hình mới dùng test để báo kết quả; các bảng test so sánh không được dùng để chỉnh lại cấu hình. Không so thời gian warm-cache như các lần chạy lạnh độc lập.

Split hiện tại chia theo câu hỏi, không cách ly paper hoặc chủ đề: hai split dùng cùng paper và có một số trang gần nhau, nên nguy cơ tương đồng nội dung còn cao. Nêu giới hạn này khi báo cáo và không suy rộng từ 5 câu test. Không thay test theo kết quả; nếu đã dùng test để chỉnh, phải công khai việc đó và tạo tập kiểm tra mới khi có thể.
