#!/usr/bin/env python3
"""공식 자료팩 스냅숏 갱신 — 법제처 현행판에서 대상 조문만 다시 받아 **새 배치**로 적재한다.

source-pack-refresh(설계 `docs/archive/2026-11/source-pack-refresh/source-pack-refresh.design.md`). 2026-10-09 자료팩
(`qpack_20261009_`, 원장 `data/vector_ledgers/qpack_20261009.json`)은 저장소 밖 스크립트로 만들어졌고,
산식·표가 이미지인 조문을 통째로 보류했다(실재하는 조문 7개가 코퍼스에 없었다 — calculator-statute-audit §4.4).
이 스크립트가 그 절차를 저장소로 옮긴다.

    python3 source_pack_refresh.py fetch     --targets data/source_pack_refresh/targets_20261112.json
    python3 source_pack_refresh.py prepare   --targets …            # 청크 + review.md(사람 검토 표)
    python3 source_pack_refresh.py upload    --targets … [--apply]  # 임베딩·upsert(기본 dry-run)
    python3 source_pack_refresh.py verify    --targets …
    python3 source_pack_refresh.py ledger    --targets …            # data/vector_ledgers/qpack_<batch>.json
    python3 source_pack_refresh.py supersede --targets … [--apply]  # 구 배치에서 대체된 조문 ID 삭제 + 구 원장 갱신
    python3 source_pack_refresh.py audit     --targets …            # 저장된 현행판 XML의 대상 조문 키 ↔ 원장(검토 보류 조문 제외)

지킬 것:
- **이미지 조문은 `<img>`·`</img>` 태그만 걷고 상자 표 텍스트를 쓴다**(D2). 표 텍스트가 없으면 보류. 표 텍스트는 다듬지 않는다(D3).
- **사람 검토(review.md 판정 칸)가 비어 있으면 upload가 거절한다**(D4, S8).
- 업로드·삭제는 `--apply` 없이는 쓰기 0. 업로드 전 새 ID의 선존재가 0이어야 한다(덮어쓰기 금지).
- 법제처 응답이 `<Response>`면 인증 오류로 멈춘다(exit 2) — 등록 IP에서 실행할 것.
- **상자 표 줄의 `?`·U+FFFD는 손실 의심 문자(G1 `suspect_glyph`)다**(source-pack-held-articles). 법제처 텍스트 변환이
  계산식의 `≤`를 `?`로 잃는다(고용보험법 시행령 제60조의2·제104조의8·제104조의15). 남은 의심 문자가 있는 조문의
  `적재` 판정은 `의심 문자 확인:` 사유가 없으면 upload가 거절한다.
- **정정은 대상 파일 `corrections`로만 한다** — 문맥 문자열(`find`)이 본문에 정확히 1회, `find`↔`replace`는
  `?` 한 글자만 다르고, 근거 이미지 sha256과 법제처 화면의 그 이미지 `alt` LaTeX(`latex_token`)가 맞을 때만
  치환한다(fail-closed). 정정 사실은 청크 머리글 `정정:` 줄과 원장 `documents[].corrections`에 남는다 — 메타데이터
  키는 늘리지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGER_DIR = ROOT / "data" / "vector_ledgers"
NAMESPACE = "laborlaw-v2"
LAW_SERVICE = "https://www.law.go.kr/DRF/lawService.do"
BOX_CHARS = re.compile(r"[┌┐└┘│─├┤┬┴┼━┃┏┓┗┛┠┨┯┷]")
IMG_TAG = re.compile(r"</?img\b[^>]*>", re.I)
FLDOWNLOAD = "https://www.law.go.kr/flDownload.do"
SUSPECT_CHARS = ("?", "\ufffd")
SUSPECT_OVERRIDE = "의심 문자 확인:"
CORRECTION_GLYPHS = {"≤": "\\leq", "≥": "\\geq", "<": "<", ">": ">", "=": "=", "+": "+", "×": "\\times", "÷": "\\div"}
SECTION_MAX = 160      # 메타데이터 section 저장 폭 — 비교 키도 같은 폭으로 자른다
EMPTY_ARTICLE_MAX = 10   # 제목·항 없이 조문 번호만 있는 자리 조문(임금채권보장법 제3조의2 등 — 5~6자)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean(text: str) -> str:
    """저장소 밖 준비 스크립트(integrate_sources.py)의 clean()과 같은 규칙 — 행 단위 공백 축약만."""
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:p|span|div|b|strong|table|tr|td|tbody|ul|li|a|font)(?:\s[^>]*)?>", "", text, flags=re.I)
    text = text.replace("\x00", "").replace("\xa0", " ")
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip())


def _cdata(s: str) -> str:
    return re.sub(r"<!\[CDATA\[|\]\]>", "", s or "")


def _tag(tag: str, unit: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", unit, re.S)
    return _cdata(m.group(1)).strip() if m else ""


def article_units(xml: str) -> list[str]:
    """`<조문단위 …>` — 속성이 있어 `<조문단위>`로 찾으면 0건이다."""
    return [u for u in re.findall(r"<조문단위[^>]*>(.*?)</조문단위>", xml, re.S) if _tag("조문여부", u) == "조문"]


def article_key(unit: str) -> str:
    branch = _tag("조문가지번호", unit)
    return _tag("조문번호", unit) + (f"의{branch}" if branch and branch != "0" else "")


def section_title(unit: str) -> str:
    """기존 배치와 같은 섹션 이름 — `제N조(의M) 제목`. ID의 섹션 해시가 이 문자열로 정해진다."""
    branch = _tag("조문가지번호", unit)
    title = "제" + _tag("조문번호", unit) + "조" + (f"의{branch}" if branch and branch != "0" else "")
    return (title + " " + _tag("조문제목", unit)).strip()


def article_body(unit: str) -> tuple[str, str]:
    """(본문, 상태). 상태: ok | held_image(이미지뿐) | empty_article(자리 조문)."""
    parts = [_cdata(p) for p in re.findall(
        r"<(?:조문내용|항내용|호내용|목내용)[^>]*>(.*?)</(?:조문내용|항내용|호내용|목내용)>", unit, re.S)]
    raw = "\n".join(parts)
    if IMG_TAG.search(raw):
        if not BOX_CHARS.search(raw):
            return "", "held_image"
        raw = IMG_TAG.sub("", raw)
    body = clean(raw)
    if not _tag("조문제목", unit) and len(body) <= EMPTY_ARTICLE_MAX:
        return body, "empty_article"
    return body, "ok"


# ── G1 의심 문자·정정 ─────────────────────────────────────────────────────────────────────

def suspect_glyphs(body: str) -> int:
    """상자 표 문자가 있는 줄의 `?`·U+FFFD 수(G1). 상자 밖 문장의 `?`는 세지 않는다."""
    return sum(sum(line.count(c) for c in SUSPECT_CHARS) for line in body.splitlines() if BOX_CHARS.search(line))


def article_heading(article: str) -> str:
    """대상 키 → 조문 표기: `60의2` → `제60조의2`, `126` → `제126조`."""
    no, _, branch = article.partition("의")
    return f"제{no}조" + (f"의{branch}" if branch else "")


def corrections_for(spec: dict, work_id: str, article: str) -> list[dict]:
    return [c for c in spec.get("corrections", []) if c["work_id"] == work_id and c["article"] == article]


def apply_corrections(body: str, fixes: list[dict]) -> str:
    """D3 — `find`가 본문에 정확히 1회, `find`→`replace`는 `?` 한 글자만 다를 때만 치환. 위반 시 중단."""
    for fx in fixes:
        find, repl = fx["find"], fx["replace"]
        diff = [(a, b) for a, b in zip(find, repl) if a != b]
        if len(find) != len(repl) or len(diff) != 1 or diff[0][0] not in SUSPECT_CHARS:
            raise SystemExit(f"[중단] 정정은 의심 문자 한 글자만 바꿀 수 있다: {fx['article']} {find!r} → {repl!r}")
        glyph = diff[0][1]
        if glyph not in CORRECTION_GLYPHS or ("latex_token" in fx and fx["latex_token"] != CORRECTION_GLYPHS[glyph]):
            raise SystemExit(f"[중단] 허용되지 않은 정정 기호이거나 latex_token과 어긋난다: {fx['article']} {glyph!r}")
        n = body.count(find)
        if n != 1:
            raise SystemExit(f"[중단] 정정 문맥이 본문에 {n}회 일치(정확히 1회여야 함): {fx['article']} {find!r}")
        body = body.replace(find, repl)
    return body


def verify_correction_sources(spec: dict, out: Path, manifest: dict) -> None:
    """D4 — 근거 이미지 sha256 = 기록값, 화면 HTML의 그 이미지 `alt`에 `latex_token`. 하나라도 어긋나면 중단."""
    assets = {}
    for m in manifest.values():
        assets.update(m.get("assets", {}))
    for fx in spec.get("corrections", []):
        seq = fx["image_flseq"]
        img = out / f"img_{seq}.gif"
        if not img.exists() or sha(img.read_bytes()) != fx["image_sha256"] or assets.get(seq) != fx["image_sha256"]:
            raise SystemExit(f"[중단] 정정 근거 이미지가 기록과 다르다: {fx['article']} flSeq={seq}")
        html_path = out / f"{fx['work_id']}.screen.html"
        if not html_path.exists():
            raise SystemExit(f"[중단] 화면 HTML 없음: {html_path.name} — fetch를 다시 돌릴 것")
        raw = html_path.read_bytes()             # 바이트로 대조 — read_text는 CRLF를 LF로 바꿔 해시가 달라진다(실측)
        if sha(raw) != assets.get(f"screen:{fx['work_id']}"):
            raise SystemExit(f"[중단] fetch 이후 화면 HTML이 바뀌었다: {html_path.name}")
        page = raw.decode("utf-8", errors="replace")
        tags = [m.group(0) for m in re.finditer(r"<img\b[^>]*>", page) if re.search(rf"flSeq={seq}(?!\d)", m.group(0))]
        alts = [html.unescape(a) for tag in tags for a in re.findall(r'alt="([^"]*)"', tag)]
        if not alts or not any(fx["latex_token"] in a for a in alts):
            raise SystemExit(f"[중단] 화면 수식에 {fx['latex_token']} 없음: {fx['article']} flSeq={seq}")


# ── 대상·경로 ──────────────────────────────────────────────────────────────────────────────

def load_targets(path: str) -> dict:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("batch", "as_of", "prior_ledger", "laws"):
        assert key in spec, f"targets에 {key} 없음"
    assert re.fullmatch(r"\d{8}", spec["batch"]), "batch는 YYYYMMDD"
    return spec


def work_dir(spec: dict) -> Path:
    return ROOT / "data" / "source_pack_refresh" / spec["batch"]


def id_prefix(spec: dict) -> str:
    return f"qpack_{spec['batch']}_"


def vector_id(spec: dict, work_id: str, section: str, k: int) -> str:
    return f"{id_prefix(spec)}{sha(work_id.encode())[:16]}_{sha(section.encode())[:10]}_{k}"


# ── fetch ─────────────────────────────────────────────────────────────────────────────────

def fetch(spec: dict) -> int:
    import requests
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    key = os.environ.get("LAW_API_KEY")
    if not key:
        print("[오류] LAW_API_KEY 없음"); return 2
    out = work_dir(spec); out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for law in spec["laws"]:
        r = requests.get(LAW_SERVICE, params={"OC": key, "target": "eflaw", "LM": law["law"], "type": "XML"}, timeout=120)
        if "<Response>" in r.text[:300]:
            print("[중단] 법제처 인증 오류 — 등록 IP에서 실행하세요"); return 2
        if "<법령" not in r.text[:500]:
            print(f"[중단] {law['law']}: 법령 루트 아님"); return 2
        path = out / f"{law['work_id']}.xml"
        path.write_text(r.text, encoding="utf-8")
        eff = _tag("시행일자", r.text[:4000])
        manifest[law["work_id"]] = {"law": law["law"], "effective": eff, "sha256": sha(r.text.encode()),
                                    "url": f"https://www.law.go.kr/법령/{law['law']}/({eff})"}
        print(f"  ✓ {law['law']} 시행 {eff} ({len(r.text):,}자)")
        time.sleep(0.3)
        fixes = [c for c in spec.get("corrections", []) if c["work_id"] == law["work_id"]]
        if fixes:
            assets = {}
            for fx in fixes:      # 키 불요 경로 — OC를 넘기지 않는다
                img = requests.get(FLDOWNLOAD, params={"flSeq": fx["image_flseq"]}, timeout=60)
                img.raise_for_status()
                (out / f"img_{fx['image_flseq']}.gif").write_bytes(img.content)
                assets[fx["image_flseq"]] = sha(img.content)
            screens = sorted({fx["screen_url"] for fx in fixes})
            assert len(screens) == 1, f"{law['work_id']}: 화면 주소는 법령당 하나"
            page = requests.get(screens[0], headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.law.go.kr/"},
                                timeout=120)
            page.raise_for_status()
            (out / f"{law['work_id']}.screen.html").write_text(page.text, encoding="utf-8")
            assets[f"screen:{law['work_id']}"] = sha(page.text.encode())
            manifest[law["work_id"]]["assets"] = assets
            print(f"    정정 근거: 이미지 {len(fixes)} · 화면 HTML {len(page.text):,}자")
    (out / "fetch_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


# ── prepare ───────────────────────────────────────────────────────────────────────────────

def prepare(spec: dict) -> tuple[list[dict], list[dict]]:
    """대상 조문 → (vectors, report rows). 파일로도 쓴다(prepared_vectors.jsonl, review 표)."""
    from pinecone_upload_official_rules import split_text
    out = work_dir(spec)
    manifest = json.loads((out / "fetch_manifest.json").read_text(encoding="utf-8"))
    vectors, rows, applied = [], [], set()
    if spec.get("corrections"):
        verify_correction_sources(spec, out, manifest)
    for law in spec["laws"]:
        xml = (out / f"{law['work_id']}.xml").read_text(encoding="utf-8")
        m = manifest[law["work_id"]]
        assert sha(xml.encode()) == m["sha256"], f"{law['work_id']}: fetch 이후 XML 변경"
        units = {article_key(u): u for u in article_units(xml)}
        for art in law["articles"]:
            unit = units.get(art)
            if unit is None:
                rows.append({"work_id": law["work_id"], "article": art, "status": "missing", "chunks": 0}); continue
            body, status = article_body(unit)
            fixes = corrections_for(spec, law["work_id"], art)
            if fixes and status == "ok":
                body = apply_corrections(body, fixes)
                applied.update((law["work_id"], art, fx["find"]) for fx in fixes)
            else:
                fixes = []
            section = section_title(unit)
            ef = _tag("조문시행일자", unit)
            ef = f"{ef[:4]}-{ef[4:6]}-{ef[6:8]}" if len(ef) == 8 else ""
            if ef and ef > spec["as_of"]:
                status = "future"
            row = {"work_id": law["work_id"], "law": law["law"], "article": art, "section": section[:SECTION_MAX],
                   "status": status, "effective": ef, "chunks": 0, "box_table": bool(BOX_CHARS.search(body)),
                   "suspect_glyph": suspect_glyphs(body) if status == "ok" else 0, "corrected": len(fixes)}
            if status == "ok":
                for k, chunk in enumerate(split_text(body)):
                    header = (f"{law['law']} — {section}\n공식기관: 법제처 국가법령정보센터\n수집 기준일: {spec['as_of']}"
                              + (f" | 조문/규칙 시행일: {ef}" if ef else "")
                              + (f"\n{correction_note(fixes)}" if fixes else ""))
                    content = header + "\n\n" + chunk
                    meta = {"source_type": "regulation", "title": law["law"][:200], "section": section[:SECTION_MAX],
                            "text": content, "chunk_text": content, "official_url": m["url"], "url": m["url"],
                            "official": True, "issuer": "법제처 국가법령정보센터", "date": ef or spec["as_of"],
                            "effective_date": ef, "retrieved_on": spec["as_of"],
                            "source_batch": f"sourcepack_{spec['batch']}", "source_pack_id": law["work_id"],
                            "source_sha256": m["sha256"], "chunk_sha256": sha(content.encode()), "chunk_index": k,
                            "version_scope": "current_body", "rights_basis": "copyright_act_article7_primary"}
                    vectors.append({"id": vector_id(spec, law["work_id"], section, k), "metadata": meta,
                                    "embed_text": content})
                    row["chunks"] += 1
            rows.append(row)
    unused = [fx for fx in spec.get("corrections", []) if (fx["work_id"], fx["article"], fx["find"]) not in applied]
    if unused:
        raise SystemExit(f"[중단] 적용되지 않은 정정 {len(unused)}건(조문 없음·보류 상태·대상 밖): "
                         + ", ".join(f"{fx['work_id']} {fx['article']}" for fx in unused))
    assert len({v["id"] for v in vectors}) == len(vectors), "ID 중복"
    with (out / "prepared_vectors.jsonl").open("w", encoding="utf-8") as f:
        for v in vectors:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    (out / "prepare_rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return vectors, rows


def correction_note(fixes: list[dict]) -> str:
    """청크 머리글 한 줄(D6) — LLM이 읽는 근거라 정정 사실이 본문과 함께 간다."""
    pairs = sorted({(a, b) for fx in fixes for a, b in zip(fx["find"], fx["replace"]) if a != b})
    what = ", ".join(f"'{a}'를 '{b}'로" for a, b in pairs)
    return f"정정: 법제처 텍스트 계산식의 {what} 바로잡음 — 법제처 조문 이미지·화면 수식 대조"


def review_label(law: str, section: str) -> str:
    """검토 표의 조문 이름 — `고용보험법 시행령 제104조의2`."""
    head = re.match(r"제\d+조(?:의\d+)?", section).group(0)
    return f"{law} {head}"


_VERDICT_RE = re.compile(r"^### (.+)\n(?:.*\n)*?판정: (.*)$", re.M)


def write_review(spec: dict, vectors: list[dict], rows: list[dict]) -> Path:
    """사람 검토 표 — 판정 칸(`판정:`)을 채워야 upload가 진행된다(D4)."""
    path = ROOT / "data" / "source_pack_refresh" / f"review_{spec['batch']}.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    verdicts = dict(_VERDICT_RE.findall(old))
    lines = [f"# 자료팩 갱신 검토 — {spec['batch']}", "",
             "판정 칸에 `적재` 또는 `보류(사유)`를 적는다. 상자 표가 이미지와 같은 산식·표를 빠짐없이 담는지 법제처 화면과 대조할 것.",
             f"상자 표 줄의 `?`·U+FFFD(의심 문자)가 남은 조문을 적재하려면 판정에 `{SUSPECT_OVERRIDE} 근거`를 적는다.",
             "", "| 법령 | 조문 | 상태 | 청크 | 상자 표 | 의심 문자 | 정정 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.get('law', r['work_id'])} | {r['article']} | {r['status']} | {r['chunks']} | "
                     f"{'있음' if r.get('box_table') else ''} | {r.get('suspect_glyph') or ''} | {r.get('corrected') or ''} |")
    lines.append("")
    by_section = {}
    for v in vectors:
        by_section.setdefault((v["metadata"]["source_pack_id"], v["metadata"]["section"]), []).append(v)
    for r in rows:
        if r["status"] != "ok":
            continue
        label = review_label(r["law"], r["section"])
        body = "\n".join(v["embed_text"].split("\n\n", 1)[1]
                         for v in by_section[(r["work_id"], r["section"][:SECTION_MAX])])
        lines += [f"### {label}", "", "```", body, "```", "", f"판정: {verdicts.get(label, '')}", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def review_verdicts(spec: dict) -> dict[str, str]:
    path = ROOT / "data" / "source_pack_refresh" / f"review_{spec['batch']}.md"
    if not path.exists():
        return {}
    return {k: v.strip() for k, v in _VERDICT_RE.findall(path.read_text(encoding="utf-8"))}


def approved_vectors(spec: dict) -> list[dict]:
    """review의 판정이 `적재`인 조문의 벡터만. 판정이 비면 예외(S8)."""
    vectors = [json.loads(l) for l in (work_dir(spec) / "prepared_vectors.jsonl").read_text(encoding="utf-8").splitlines()]
    verdicts = review_verdicts(spec)
    suspect: dict[tuple[str, str], int] = {}       # G1은 적재할 본문 자체에서 센다 — 별도 파일에 기대지 않는다
    for v in vectors:
        key = (v["metadata"]["source_pack_id"], v["metadata"]["section"])
        suspect[key] = suspect.get(key, 0) + suspect_glyphs(v["embed_text"].split("\n\n", 1)[-1])
    keep = []
    for v in vectors:
        meta = v["metadata"]
        label = review_label(meta["title"], meta["section"])
        verdict = verdicts.get(label, "")
        if not verdict:
            raise SystemExit(f"[중단] 검토 판정이 비어 있음: {label} — review 파일을 채울 것")
        if verdict.startswith("적재"):
            if suspect.get((meta["source_pack_id"], meta["section"]), 0) and SUSPECT_OVERRIDE not in verdict:
                raise SystemExit(f"[중단] 의심 문자가 남은 조문: {label} — 정정(corrections)하거나 판정에 "
                                 f"'{SUSPECT_OVERRIDE} 근거'를 적을 것")
            keep.append(v)
    return keep


# ── Pinecone ──────────────────────────────────────────────────────────────────────────────

def _index():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    from pinecone import Pinecone
    from app.config import resolve_index_name
    name = resolve_index_name()
    assert name == "laborconsult", f"예상 밖 인덱스 {name}"
    return Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(name)


def upload(spec: dict, apply: bool) -> int:
    vectors = approved_vectors(spec)
    print(f"적재 대상 {len(vectors)}벡터 ({id_prefix(spec)}…, ns={NAMESPACE})")
    if not apply:
        print("[dry-run] 실행하려면 --apply"); return 0
    index = _index()
    ids = [v["id"] for v in vectors]
    pre = [i for s in range(0, len(ids), 100) for i in index.fetch(ids=ids[s:s + 100], namespace=NAMESPACE).vectors]
    if pre:
        print(f"[중단] 이미 존재하는 ID {len(pre)}건 — verify를 쓸 것"); return 1
    from openai import OpenAI
    from app.config import EMBED_MODEL
    client, tokens = OpenAI(api_key=os.environ["OPENAI_API_KEY"]), 0
    for s in range(0, len(vectors), 64):
        batch = vectors[s:s + 64]
        resp = client.embeddings.create(model=EMBED_MODEL, input=[v["embed_text"] for v in batch])
        embs = sorted(resp.data, key=lambda e: e.index)
        assert len(embs) == len(batch) and all(len(e.embedding) == 1536 for e in embs)
        index.upsert(vectors=[{"id": v["id"], "values": e.embedding, "metadata": v["metadata"]}
                              for v, e in zip(batch, embs)], namespace=NAMESPACE)
        tokens += resp.usage.total_tokens
    (work_dir(spec) / "upload_result.json").write_text(json.dumps({"ids": ids, "embedding_tokens": tokens}) + "\n")
    print(f"업로드 {len(ids)} · 임베딩 토큰 {tokens:,}")
    return verify(spec)


def verify(spec: dict) -> int:
    vectors, index = approved_vectors(spec), _index()
    for attempt in range(5):
        missing, bad = [], []
        for s in range(0, len(vectors), 100):
            batch = vectors[s:s + 100]
            got = index.fetch(ids=[v["id"] for v in batch], namespace=NAMESPACE).vectors
            for v in batch:
                a = got.get(v["id"])
                if a is None:
                    missing.append(v["id"])
                elif a.metadata.get("chunk_sha256") != v["metadata"]["chunk_sha256"] or a.metadata.get("text") != v["metadata"]["text"]:
                    bad.append(v["id"])
        if not missing:
            break
        time.sleep(5)
    print(f"verify: 존재 {len(vectors) - len(missing)}/{len(vectors)} · 불일치 {len(bad)}")
    return 1 if missing or bad else 0


# ── 원장 ──────────────────────────────────────────────────────────────────────────────────

def build_ledger(spec: dict, vectors: list[dict]) -> dict:
    manifest = json.loads((work_dir(spec) / "fetch_manifest.json").read_text(encoding="utf-8"))
    tokens = None
    res = work_dir(spec) / "upload_result.json"
    if res.exists():
        tokens = json.loads(res.read_text())["embedding_tokens"]
    docs = {}
    for v in vectors:
        meta = v["metadata"]; wid = meta["source_pack_id"]
        doc = docs.setdefault(wid, {"title": meta["title"], "source_type": meta["source_type"],
                                    "official_url": manifest[wid]["url"], "source_sha256": manifest[wid]["sha256"],
                                    "ids": []})
        doc["ids"].append(v["id"])
    loaded = {(v["metadata"]["source_pack_id"], v["metadata"]["section"].split(" ", 1)[0]) for v in vectors}
    for fx in spec.get("corrections", []):
        if (fx["work_id"], article_heading(fx["article"])) in loaded:
            docs[fx["work_id"]].setdefault("corrections", []).append(
                {k: fx[k] for k in ("article", "find", "replace", "image_flseq", "image_sha256", "screen_url",
                                    "latex_token", "reviewed_by")})
    return {
        "batch": f"sourcepack_{spec['batch']}", "id_prefix": id_prefix(spec),
        "id_pattern": rf"^{id_prefix(spec)}[0-9a-f]{{16}}_[0-9a-f]{{10}}_\d+$",
        "index": "laborconsult", "namespace": NAMESPACE, "uploaded_on": f"{spec['batch'][:4]}-{spec['batch'][4:6]}-{spec['batch'][6:]}",
        "state": "verified", "vector_count": len(vectors), "document_count": len(docs),
        "composition": {"regulation": len(vectors)},
        "metadata_flags": {"official": True, "source_batch": f"sourcepack_{spec['batch']}"},
        "embedding_tokens": tokens, "supersedes": spec.get("supersede", []),
        "note": "source_pack_refresh.py로 법제처 현행판에서 대상 조문만 받아 적재했다. 대상·사람 검토는 "
                f"data/source_pack_refresh/targets_{spec['batch']}.json·review_{spec['batch']}.md.",
        "documents": docs,
    }


def superseded_ids(prior: dict, spec: dict) -> list[str]:
    """구 원장에서 대체 대상 조문(work_id + 섹션 이름)의 ID만 고른다(D6, S6)."""
    out = []
    done = prior.get("revision", {}).get(f"superseded_by_{spec['batch']}", {}).get("ids", [])
    for item in spec.get("supersede", []):
        doc = prior["documents"][item["work_id"]]
        tag = f"_{sha(item['work_id'].encode())[:16]}_{sha(item['section'].encode())[:10]}_"
        hit = [i for i in doc["ids"] + done if tag in i]      # 이미 대체했으면 revision 기록에서 찾는다(멱등)
        assert hit, f"구 원장에 없는 섹션: {item}"
        out.extend(hit)
    return sorted(set(out))


def already_superseded(prior: dict, spec: dict) -> bool:
    return f"superseded_by_{spec['batch']}" in prior.get("revision", {})


def supersede(spec: dict, apply: bool) -> int:
    path = ROOT / spec["prior_ledger"]
    prior = json.loads(path.read_text(encoding="utf-8"))
    ids = superseded_ids(prior, spec)
    print(f"{prior['batch']}: 대체 삭제 대상 {len(ids)}벡터 {ids}")
    if already_superseded(prior, spec):
        print("이미 대체됨 — 구 원장 revision에 기록이 있다(재실행 불필요)"); return 0
    if not apply:
        print("[dry-run] 실행하려면 --apply"); return 0
    index = _index()
    index.delete(ids=ids, namespace=prior["namespace"])
    gone = set(ids)
    for item in spec["supersede"]:
        prior["documents"][item["work_id"]]["ids"] = [i for i in prior["documents"][item["work_id"]]["ids"] if i not in gone]
    prior["vector_count"] -= len(ids)
    prior["composition"]["regulation"] -= len(ids)   # 대체 대상은 법령(regulation)만
    prior.setdefault("revision", {})[f"superseded_by_{spec['batch']}"] = {
        "ids": ids, "sections": spec["supersede"], "reason": "현행판 본문 변경 — 새 배치로 대체"}
    path.write_text(json.dumps(prior, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"삭제 {len(ids)} · 구 원장 갱신 {path.relative_to(ROOT)}")
    return 0


# ── audit ─────────────────────────────────────────────────────────────────────────────────

def audit(spec: dict) -> int:
    """대상 법령의 현행판 조문 키 ↔ 원장 섹션 키. 적재 대상인데 원장에 없는 조문을 실패로 센다."""
    ledgers = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(LEDGER_DIR.glob("qpack_*.json"))]
    have: dict[str, set[str]] = {}
    for led in ledgers:
        for wid, doc in led["documents"].items():
            have.setdefault(wid, set()).update(i.rsplit("_", 2)[1] for i in doc["ids"])
    fail, verdicts = 0, review_verdicts(spec)
    for law in spec["laws"]:
        xml = (work_dir(spec) / f"{law['work_id']}.xml").read_text(encoding="utf-8")
        units = {article_key(u): u for u in article_units(xml)}
        for art in law["articles"]:
            unit = units.get(art)
            if unit is None:
                continue
            body, status = article_body(unit)
            if status != "ok":
                continue
            label = review_label(law["law"], section_title(unit))
            if verdicts.get(label, "").startswith("보류"):
                print(f"  - {label} (검토 보류)")
                continue
            key = sha(section_title(unit).encode())[:10]
            ok = key in have.get(law["work_id"], set())
            fail += not ok
            print(f"  {'✓' if ok else '✗'} {label}")
    print("audit: " + ("누락 0" if not fail else f"누락 {fail}"))
    return 1 if fail else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("action", choices=["fetch", "prepare", "upload", "verify", "ledger", "supersede", "audit"])
    p.add_argument("--targets", default="data/source_pack_refresh/targets_20261112.json")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args(argv)
    spec = load_targets(str(ROOT / a.targets))
    if a.action == "fetch":
        return fetch(spec)
    if a.action == "prepare":
        vectors, rows = prepare(spec)
        path = write_review(spec, vectors, rows)
        for r in rows:
            print(f"  {r['status']:14s} {r.get('law', r['work_id'])} 제{r['article']}조 청크 {r['chunks']}")
        print(f"벡터 {len(vectors)} · 검토 파일 {path.relative_to(ROOT)}")
        return 0
    if a.action == "upload":
        return upload(spec, a.apply)
    if a.action == "verify":
        return verify(spec)
    if a.action == "ledger":
        ledger = build_ledger(spec, approved_vectors(spec))
        out = LEDGER_DIR / f"qpack_{spec['batch']}.json"
        out.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"원장 {out.relative_to(ROOT)} · {ledger['vector_count']}벡터 {ledger['document_count']}문서")
        return 0
    if a.action == "supersede":
        return supersede(spec, a.apply)
    return audit(spec)


if __name__ == "__main__":
    sys.exit(main())
