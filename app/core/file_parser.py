"""파일 첨부 파싱 — 이미지/PDF/TXT에서 텍스트 또는 Vision 블록 추출"""

import base64
import io
from dataclasses import dataclass

# ── 상수 ──────────────────────────────────────────────────────────────────────

MAX_IMAGE_SIZE = 3 * 1024 * 1024    # 3MB (Vercel 4.5MB body limit)
MAX_PDF_SIZE = 3 * 1024 * 1024      # 3MB (Vercel 4.5MB body limit)
MAX_TEXT_SIZE = 1 * 1024 * 1024     # 1MB
MAX_PDF_PAGES = 20
MAX_ATTACHMENTS = 3
MAX_EXTRACTED_CHARS = 15_000

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_TEXT_TYPES = {"text/plain", "text/markdown"}
ALLOWED_PDF_TYPES = {"application/pdf"}

MAGIC_BYTES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/webp": [b"RIFF"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "application/pdf": [b"%PDF"],
}


@dataclass
class ParsedAttachment:
    """파싱된 첨부파일 결과"""
    filename: str
    content_type: str
    vision_block: dict | None = None
    extracted_text: str | None = None
    raw_data: bytes | None = None


class FileValidationError(Exception):
    """파일 검증 실패"""
    pass


# ── 검증 ──────────────────────────────────────────────────────────────────────

def validate_file(data: bytes, content_type: str, filename: str) -> None:
    if content_type in ALLOWED_IMAGE_TYPES:
        if len(data) > MAX_IMAGE_SIZE:
            raise FileValidationError(f"이미지 파일은 3MB 이하만 가능합니다. ({filename})")
    elif content_type in ALLOWED_PDF_TYPES:
        if len(data) > MAX_PDF_SIZE:
            raise FileValidationError(f"PDF 파일은 3MB 이하만 가능합니다. ({filename})")
    elif content_type in ALLOWED_TEXT_TYPES:
        if len(data) > MAX_TEXT_SIZE:
            raise FileValidationError(f"텍스트 파일은 1MB 이하만 가능합니다. ({filename})")
    else:
        raise FileValidationError(
            f"지원하지 않는 파일 형식입니다: {content_type} ({filename}). "
            "이미지(JPG/PNG/WEBP/GIF), PDF, TXT 파일만 가능합니다."
        )

    if content_type in MAGIC_BYTES:
        prefixes = MAGIC_BYTES[content_type]
        if not any(data[:len(p)] == p for p in prefixes):
            raise FileValidationError(
                f"파일 내용이 확장자와 일치하지 않습니다. ({filename})"
            )


# ── 파싱 ──────────────────────────────────────────────────────────────────────

def parse_image(data: bytes, content_type: str, filename: str) -> ParsedAttachment:
    media_type = content_type.split(";")[0].strip()
    b64 = base64.standard_b64encode(data).decode("ascii")
    return ParsedAttachment(
        filename=filename,
        content_type=content_type,
        vision_block={
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64,
            },
        },
    )


def parse_pdf(data: bytes, filename: str) -> ParsedAttachment:
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise FileValidationError(
            f"PDF는 {MAX_PDF_PAGES}페이지 이하만 가능합니다. "
            f"({filename}: {len(reader.pages)}페이지)"
        )

    pages_text = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(f"[{i+1}페이지]\n{text.strip()}")

    extracted = "\n\n".join(pages_text)
    if not extracted.strip():
        raise FileValidationError(
            f"PDF에서 텍스트를 추출할 수 없습니다. "
            f"스캔된 이미지 PDF라면 이미지 파일로 첨부해 주세요. ({filename})"
        )

    if len(extracted) > MAX_EXTRACTED_CHARS:
        extracted = extracted[:MAX_EXTRACTED_CHARS] + f"\n\n... (이하 생략, 총 {len(extracted):,}자)"

    return ParsedAttachment(
        filename=filename,
        content_type="application/pdf",
        extracted_text=extracted,
    )


def parse_text(data: bytes, filename: str) -> ParsedAttachment:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("euc-kr")
        except UnicodeDecodeError:
            raise FileValidationError(f"텍스트 파일 인코딩을 인식할 수 없습니다. ({filename})")

    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS] + f"\n\n... (이하 생략, 총 {len(text):,}자)"

    return ParsedAttachment(
        filename=filename,
        content_type="text/plain",
        extracted_text=text,
    )


# ── 통합 파서 ─────────────────────────────────────────────────────────────────

def parse_attachment(data: bytes, content_type: str, filename: str) -> ParsedAttachment:
    validate_file(data, content_type, filename)

    if content_type in ALLOWED_IMAGE_TYPES:
        result = parse_image(data, content_type, filename)
    elif content_type in ALLOWED_PDF_TYPES:
        result = parse_pdf(data, filename)
    elif content_type in ALLOWED_TEXT_TYPES:
        result = parse_text(data, filename)
    else:
        raise FileValidationError(f"지원하지 않는 파일 형식입니다: {content_type}")

    result.raw_data = data
    return result
