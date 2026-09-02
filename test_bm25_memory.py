#!/usr/bin/env python3
"""BM25 로드 메모리 상한 + 검색 결과 동일성 회귀 (bm25-memory-scaling).

**왜 이 테스트가 있는가.** 메모리는 지금까지 *사람이 기억해서 재는 값*이었고,
그래서 RSS가 Vercel 한도의 **119%가 될 때까지 아무도 몰랐다**(2026-08-25 실측).
넘으면 소프트 `MemoryError`를 `search_hybrid`의 broad except가 Dense-only로
**조용히 흡수**해 하이브리드 검색이 반쪽이 되고, 하드 OOM-kill은 코드로 막을 수
없다. 어느 쪽도 로그에 "품질이 떨어졌다"고 남지 않는다.

⚠️ **실패했을 때 상한을 올리는 것이 기본 대응이 아니다.** 코퍼스가 늘어 넘었다면
그때가 다음 구조 개선(text 미보관 + Pinecone fetch 보충 · 샤딩 · Vercel 메모리
상향)을 검토할 시점이다. 각 대안의 실측 비교는
`docs/02-design/features/bm25-memory-scaling.design.md` §1에 있다.

실행: python3 test_bm25_memory.py
"""

from __future__ import annotations

import os
import sys
import json
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 로드 피크 RSS 상한(MB). 실측 400MB(JSONL 스트리밍, 76,983문서)에 여유를 둔 값.
# 한도 1024MB의 54%라 초과해도 즉시 위험하지는 않지만, 그 시점이 구조를 다시
# 볼 때다. 너무 빡빡하면 CI 환경 차이로 흔들리고, 너무 느슨하면 회귀를 못 잡는다.
RSS_LIMIT_MB = 550

# 검색 결과 동일성 확인용 쿼리. 6개 source_type이 고루 최상위에 오도록 골랐다.
IDENTITY_QUERIES = [
    "연차휴가 미사용 수당",
    "부당해고 구제신청",
    "주휴수당 지급 요건",
    "퇴직금 산정 평균임금",
    "직장 내 괴롭힘 판단 기준",
    "산업재해 요양급여",
    "근로계약서 미작성 벌칙",
    "임금체불 지연이자",
]

# ⚠️ **프로즌 기준값 파일을 쓰지 않는다.**
# 초안은 결과를 `data/bm25_baseline.json`에 얼려 대조했는데 두 가지가 어긋났다:
#   ① 그 파일은 전환 **후** 스냅샷이라 "값이 보존됐다"를 자체로 증명하지 못한다.
#   ② `search_bm25`는 안정 정렬이라 **동점의 순서가 코퍼스 인덱스 순서에 의존**하고,
#      코퍼스 순서는 Pinecone 페이지네이션 때문에 재빌드마다 달라진다. 즉 내용이
#      같아도 재빌드만으로 깨진다 — 실무 대응이 "기준값 삭제"가 되어 가드가 소멸한다.
# 대신 **같은 실행에서 신·구 포맷 두 경로를 서로 대조**한다. 코퍼스 버전과 무관하게
# "스트리밍 == 배열"을 검증하므로 이번 변경이 값을 보존하는지에 대한 직접 증거다.

# 별도 프로세스에서 실행할 측정 코드.
# ⚠️ `ru_maxrss`는 **프로세스 최대치**라 같은 프로세스에서 다른 테스트가 먼저
#    메모리를 쓰면 오염된다 — 반드시 하위 프로세스에서 재야 한다.
_PROBE = """
import sys, os, json, time, resource
sys.path.insert(0, {base!r})
os.chdir({base!r})
import app.core.bm25_search as B
from pathlib import Path
_only = {only!r}
if _only:                      # 특정 포맷 경로를 강제한다(등가성 대조용)
    B.BM25_CORPUS_PATHS = [Path(_only)]
t0 = time.perf_counter()
ok = B.load_bm25_corpus()
elapsed = time.perf_counter() - t0
_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
# ru_maxrss 단위는 **플랫폼마다 다르다** — macOS/BSD는 바이트, Linux는 킬로바이트.
# 고정 나눗셈을 쓰면 CI(ubuntu)에서 400MB가 0.39MB로 보고돼 **상한 검사가 절대
# 실패하지 않는다**(gap 분석 F1에서 실제로 그 상태였다). 이 테스트의 존재 이유가
# 사라지는 결함이라 분기를 없애지 말 것.
rss = _raw / (1024 ** 2) if sys.platform == "darwin" else _raw / 1024
results = {{q: [{{"id": h["id"], "score": h["score"]}}
                for h in B.search_bm25(q, top_k=5)]
            for q in {queries!r}}}
print(json.dumps({{"ok": ok, "docs": len(B._bm25_corpus or []),
                   "rss": round(rss, 1), "elapsed": round(elapsed, 2),
                   "results": results}}, ensure_ascii=False))
"""


def _run_probe(only: str | None = None) -> dict:
    """하위 프로세스에서 BM25를 로드해 RSS·시간·검색 결과를 잰다.

    `only`를 주면 그 코퍼스 파일만 쓰도록 강제한다 — 신·구 포맷 등가성 대조용.
    """
    code = _PROBE.format(base=BASE_DIR, queries=IDENTITY_QUERIES, only=only)
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise AssertionError(f"BM25 로드 프로브 실패:\n{proc.stderr[-800:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail=None) -> None:
        if cond:
            print(f"  ✅ {name}")
        else:
            failures.append(name)
            print(f"  ❌ {name}" + (f"  {detail}" if detail is not None else ""))

    print("\n[BM25 메모리]")
    probe = _run_probe()

    check("로드 성공", probe["ok"], probe)
    check(f"문서 수 > 0 ({probe['docs']:,})", probe["docs"] > 0)
    if not (probe["ok"] and probe["docs"]):
        # 로드가 안 됐으면 이후 검사는 의미가 없다 — 0건을 "동일"이라 통과시키면
        # 최악이다(초안이 그 상태였다).
        print("\n실패: BM25 로드 자체가 되지 않아 이후 검증을 건너뜁니다.")
        print("      (.venv 활성화 여부와 rank_bm25 설치를 확인하세요)")
        return 1

    check(
        f"로드 피크 RSS {probe['rss']:.0f}MB ≤ {RSS_LIMIT_MB}MB "
        f"(Vercel 1024MB의 {probe['rss'] / 1024 * 100:.0f}%)",
        probe["rss"] <= RSS_LIMIT_MB,
        "상한을 올리기 전에 design §1의 대안을 먼저 검토할 것",
    )
    # 단위 위생 검사 — 플랫폼별 ru_maxrss 단위(바이트 vs KB)를 잘못 환산하면
    # CI에서 400MB가 0.4MB로 보고돼 **상한 검사가 절대 실패하지 않는다**.
    # 실제로 그 상태였고 두 리뷰가 독립적으로 같은 결함을 찾았다.
    check(f"RSS 값이 합리적 범위 (50MB < {probe['rss']:.0f}MB < 3000MB)",
          50 < probe["rss"] < 3000,
          "단위 환산 오류 의심 — ru_maxrss는 macOS 바이트 / Linux KB")
    # 시간은 **경고만** 한다 — CI 러너 성능 편차로 간헐 실패하면 상한을 올리게 되고
    # 그러면 관측 목적 자체가 사라진다.
    if probe["elapsed"] > 8.0:
        print(f"  ⚠️  로드 {probe['elapsed']:.1f}초 (콜드 스타트에 그대로 얹힌다)")
    else:
        print(f"  ✅ 로드 시간 {probe['elapsed']:.1f}초")

    # ── 신·구 포맷 등가성 대조는 종결됨(2026-09-02) ──────────────────────
    # 전환기 검증("스트리밍이 값을 보존한다")은 PR #60 이후 CI에서 성공을
    # 반복했고, 주해Ⅲ 증분 재빌드로 두 파일이 다른 코퍼스가 되는 시점에
    # 이 블록의 원 주석이 지시한 종결 절차대로 구 파일(bm25_corpus.json.gz,
    # 20MB)과 대조 검사를 **함께** 제거했다. 로더의 구 포맷 폴백 경로는
    # 남아 있다(bm25_search — 외부 사본 대비 무해).

    print()
    if failures:
        print(f"실패 {len(failures)}건: {failures}")
        return 1
    print("✅ BM25 메모리 테스트 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
