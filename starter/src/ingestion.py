"""Read and normalize source data. TODO: implement functions."""
import logging
import re
import unicodedata
from pathlib import Path
from pypdf import PdfReader
from .models import DocumentPage

logger = logging.getLogger(__name__)

def load_pdf(
    path: Path,
    document_id: str,
    source: str,
) -> list[DocumentPage]:
    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy PDF: {path}")

    reader = PdfReader(path)
    pages: list[DocumentPage] = []

    for page_number, pdf_page in enumerate(reader.pages, start=1):
        try:
            raw_text = pdf_page.extract_text() or ""
        except Exception:
            logger.exception(
                "Lỗi trích xuất PDF %s, trang %s",
                path,
                page_number,
            )
            raise

        text = normalize_text(raw_text)
        # Một số font công thức PDF xuất glyph thành mã điều khiển C0/NUL.
        # PostgreSQL không cho NUL trong text; ghi số ký tự bỏ để audit thay vì
        # giả định đã khôi phục đúng công thức gốc.
        removed_controls = len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", raw_text))
        if removed_controls:
            logger.warning("Loại %s ký tự điều khiển: %s, trang %s", removed_controls, path, page_number)

        if not text:
            logger.warning(
                "Trang không có chữ trích xuất: %s, trang %s",
                path,
                page_number,
            )

        pages.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=page_number,
                text=text,
                metadata={
                    "extraction_status": "ok" if text else "empty",
                    "character_count": len(text),
                    "control_characters_removed": removed_controls,
                },
            )
        )

    return pages


def normalize_text(text: str) -> str:
    # Chuẩn hóa các cách biểu diễn Unicode tương đương.
    text = unicodedata.normalize("NFC", text)

    # Thống nhất ký tự xuống dòng.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Giữ tab/newline cho bước xử lý whitespace, bỏ mã điều khiển vô hình khác.
    # Đây không phải OCR hoặc sửa công thức; phần mất ký hiệu cần kiểm tra PDF.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Chuẩn hóa khoảng trắng trong từng dòng, giữ ngắt dòng.
    lines = [
        re.sub(r"[^\S\n]+", " ", line).strip()
        for line in text.split("\n")
    ]
    text = "\n".join(lines)

    # Giữ tối đa một dòng trống giữa các đoạn.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
