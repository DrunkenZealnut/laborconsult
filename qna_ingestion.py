"""Document identities and parsers for the isolated nodong.kr refresh pipeline."""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from bs4 import BeautifulSoup

PARSE_VERSION = "nodong-qna-v2"
ORIGIN = "nodong_qna"

def normal(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).replace("\\\n", "\n")).strip()

def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def iso_date(value: str | None) -> str | None:
    m = re.match(r"^\s*(\d{4})[.-](\d{2})[.-](\d{2})(?:\s|$)", value or "")
    if not m:
        return None
    try:
        return date(*map(int, m.groups())).isoformat()
    except ValueError:
        return None

def post_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc not in {"www.nodong.kr", "nodong.kr"}:
        return None
    m = re.fullmatch(r"/qna/(\d+)", parsed.path)
    if m:
        return m[1]
    query = parse_qs(parsed.query)
    if query.get("mid") == ["qna"]:
        value = query.get("document_srl", [""])[0]
        return value if value.isdigit() else None
    return None

def document(post_id: str, title: str, posted_at: str | None,
             question: str, answers: list[str], *, category: str = "",
             fetched_at: str | None = None, answer_updated_at: str | None = None) -> dict:
    if not re.fullmatch(r"[0-9]+", post_id):
        raise ValueError("invalid post_id")
    question_hash = digest(normal(question))
    answer_hash = digest([normal(a) for a in answers])
    return {
        "corpus_origin": ORIGIN, "post_id": post_id,
        "canonical_url": f"https://www.nodong.kr/qna/{post_id}",
        "title": unicodedata.normalize("NFC", title).strip(),
        "category": category, "posted_at": posted_at,
        "answer_updated_at": answer_updated_at, "fetched_at": fetched_at,
        "question": question, "answers": answers,
        "question_hash": question_hash, "answer_hash": answer_hash,
        "content_hash": digest([normal(title), posted_at, normal(category), question_hash, answer_hash]),
        "parse_version": PARSE_VERSION,
        "status": "answered" if answers else "unanswered",
    }

def parse_legacy(text: str, post_id: str) -> dict:
    # Dates inside the question are events, not document metadata.
    header, sep, remainder = text.partition("\n## 질문\n")
    if not sep:
        raise ValueError("question heading missing")
    question, has_answers, answer = remainder.partition("\n## 답변\n")
    fields = dict(re.findall(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", header, re.M))
    title = re.search(r"^#\s+(.+)", header, re.M)
    answers = []
    if has_answers and answer.strip():
        if not re.search(r"답변 글[^\n]{0,40}'0'", answer):
            answers = [a.strip() for a in re.split(r"^### 답변 \d+\s*$", answer, flags=re.M) if a.strip()]
    return document(post_id, title[1] if title else "", iso_date(fields.get("작성일")),
                    question.strip(), answers, category=fields.get("카테고리", ""))

def public_manifest(record: dict) -> dict:
    """Manifest remains private operational data; omit bodies to keep it small."""
    return {k: v for k, v in record.items() if k not in {"question", "answers"}}

def inventory(directories: list[Path]) -> dict[str, dict]:
    records = {}
    for directory in directories:
        if not directory.is_dir():
            raise ValueError(f"source directory missing: {directory}")
        for path in sorted(directory.glob("*.md")):
            m = re.match(r"^(\d+)_", unicodedata.normalize("NFC", path.name))
            if not m:
                continue
            post_id = m[1]
            try:
                doc = parse_legacy(path.read_text(encoding="utf-8"), post_id)
            except ValueError as exc:
                doc = document(post_id, "", None, "", [])
                doc.update(status="parse_error", parse_error=str(exc))
            row = public_manifest(doc)
            row.update(local_paths=[str(path.resolve())], selected_path=str(path.resolve()))
            row["versions"] = [{"path": str(path.resolve()), "content_hash": doc["content_hash"]}]
            if post_id not in records:
                records[post_id] = row
                continue
            existing = records[post_id]
            existing["local_paths"].extend(row["local_paths"])
            existing["versions"].extend(row["versions"])
            if existing["content_hash"] != row["content_hash"]:
                existing["status"] = "conflict"
                # Legacy files have no reliable fetch timestamp: refetch conflicts.
    return records

def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.bd_lst tbody")
    if table is None:
        raise ValueError("listing_missing_or_blocked")
    rows, seen = [], set()
    for tr in table.select("tr"):
        if "notice" in tr.get("class", []):
            continue
        for link in tr.select("td.title a[href]"):
            post_id = post_id_from_url(link["href"])
            if not post_id or post_id in seen:
                continue
            seen.add(post_id)
            when = tr.select_one("td.time")
            rows.append({"post_id": post_id, "canonical_url": f"https://www.nodong.kr/qna/{post_id}",
                         "title": link.get_text(" ", strip=True),
                         "posted_at": iso_date(when.get_text() if when else None)})
            break
    if not rows:
        raise ValueError("empty_listing_unconfirmed")
    return rows

def parse_live(html: str, post_id: str, fetched_at: str) -> dict:
    from crawl_qna import parse_post_html
    parsed = parse_post_html(html, f"https://www.nodong.kr/qna/{post_id}")
    if parsed.get("error"):
        raise ValueError(parsed["error"])
    if not parsed["title"].strip() or not parsed["content"].strip():
        raise ValueError("empty_document")
    # Comment creation dates are not answer edit timestamps.
    record = document(post_id, parsed["title"], iso_date(parsed["date"]),
                      parsed["content"], parsed["answers"], category=parsed["category"],
                      fetched_at=fetched_at)
    soup = BeautifulSoup(html, "lxml")
    stamp = soup.select_one(".rd .rd_hd .date")
    match = re.search(r"(\d{4}[.-]\d{2}[.-]\d{2})\s+(\d{2}:\d{2})(?!\d)", stamp.get_text() if stamp else "")
    if match:
        try:
            when = datetime.fromisoformat(match[1].replace(".", "-") + "T" + match[2])
            record["posted_datetime"] = when.replace(tzinfo=ZoneInfo("Asia/Seoul")).isoformat()
        except ValueError:
            pass
    return record

def render_markdown(record: dict) -> str:
    from crawl_qna import build_markdown
    return build_markdown({"url": record["canonical_url"]}, {
        "title": record["title"], "date": record["posted_at"] or "",
        "category": record["category"], "content": record["question"], "answers": record["answers"],
    })
