#!/usr/bin/env python3
"""스캔 이미지 폴더 → marker 변환 → 쪽 마커(`<!-- page: N -->`)가 든 단일 .md (해설서 코퍼스 수집용).

낱장 이미지를 marker에 하나씩 넣으면 OCR 배치가 안 돼 쪽당 30초가 걸린다(실측 2026-10-27, MPS).
한 PDF로 묶어 `marker_single --paginate_output`으로 돌리면 쪽당 약 17초다. 산출 .md의 paginate
구분자(`{N}----…`)를 `<!-- page: N -->`로 바꿔 기존 변환본과 같은 형식으로 맞춘다.

    python3 convert_textbook_scans.py "output_노동법교재/산안법1" --pattern ' - (\\d+)\\.jpg$' \\
        --out "output_노동법교재/산안법1/산안법1.md"

- 파일명의 번호로 정렬한다. "(1)"처럼 번호 뒤에 꼬리가 붙은 파일은 재스캔 중복(원본과 바이트 동일)이라 건너뛴다.
- marker는 ~/DEV/marker/.venv의 `marker_single`을 쓴다(TORCH_DEVICE는 그쪽 .env).
- 중간 산출물(PDF·marker 원본 출력)은 --work 디렉터리에 남겨 재시도 때 PDF 조립을 건너뛴다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MARKER_HOME = Path.home() / "DEV" / "marker"
MARKER_BIN = MARKER_HOME / ".venv" / "bin" / "marker_single"
_PAGINATE_RE = re.compile(r"^\{(\d+)\}-{8,}\s*$", re.M)


def ordered_images(folder: Path, pattern: str) -> list[Path]:
    rx = re.compile(pattern)
    picked: dict[int, Path] = {}
    skipped = 0
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        m = rx.search(f.name)
        if not m:
            skipped += 1
            continue
        n = int(m.group(1))
        if n in picked:
            skipped += 1   # 재스캔 중복("(1)")
            continue
        picked[n] = f
    nums = sorted(picked)
    gaps = [i for i in range(nums[0], nums[-1] + 1) if i not in picked]
    print(f"이미지 {len(nums)}장 ({nums[0]}~{nums[-1]}), 건너뜀 {skipped}, 결번 {gaps}")
    return [picked[n] for n in nums]


def build_pdf(images: list[Path], pdf_path: Path) -> None:
    from PIL import Image
    if pdf_path.exists():
        print(f"PDF 재사용: {pdf_path}")
        return
    t0 = time.time()
    first, *rest = (Image.open(p).convert("RGB") for p in images)
    first.save(pdf_path, save_all=True, append_images=rest, resolution=200.0)
    print(f"PDF 조립: {pdf_path} ({pdf_path.stat().st_size/1e6:.0f}MB, {time.time()-t0:.0f}s)")


def run_marker(pdf_path: Path, out_dir: Path) -> Path:
    env = dict(os.environ)
    for line in (MARKER_HOME / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())
    env.setdefault("TORCH_DEVICE", "mps")
    cmd = [str(MARKER_BIN), str(pdf_path), "--output_dir", str(out_dir), "--output_format", "markdown",
           "--paginate_output", "--disable_image_extraction"]
    print("marker:", " ".join(cmd)); t0 = time.time()
    with open(out_dir / "marker.log", "a") as log:
        subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    md = next((out_dir / pdf_path.stem).glob("*.md"))
    print(f"marker 완료: {md} ({time.time()-t0:.0f}s)")
    return md


def paginate_to_markers(text: str) -> str:
    return _PAGINATE_RE.sub(lambda m: f"<!-- page: {m.group(1)} -->", text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--pattern", default=r" - (\d+)\.jpe?g$", help="파일명에서 쪽 번호를 뽑는 정규식(그룹 1)")
    ap.add_argument("--out", required=True, help="최종 .md 경로")
    ap.add_argument("--work", default=None, help="중간 산출물 디렉터리(기본: <out>의 폴더/_convert)")
    a = ap.parse_args()
    folder = Path(a.folder); out = Path(a.out)
    work = Path(a.work) if a.work else out.parent / "_convert"
    work.mkdir(parents=True, exist_ok=True)
    images = ordered_images(folder, a.pattern)
    pdf = work / f"{out.stem}.pdf"
    build_pdf(images, pdf)
    md = run_marker(pdf, work)
    text = md.read_text(encoding="utf-8")
    n = len(_PAGINATE_RE.findall(text))
    if n != len(images):
        print(f"[경고] paginate 구분자 {n}개 ≠ 이미지 {len(images)}장 — 쪽 마커가 어긋날 수 있다")
    out.write_text(paginate_to_markers(text), encoding="utf-8")
    meta = md.with_name(md.stem + "_meta.json")
    if meta.exists():
        shutil.copy(meta, out.with_name(out.stem + "_meta.json"))
    print(f"완료: {out} ({out.stat().st_size/1e6:.1f}MB, 쪽 마커 {n})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
