#!/usr/bin/env python3
"""BM25 한국어 토크나이저 품질 측정 (tokenizer-quality).

**API 키가 필요 없다.** 토크나이저는 외부 호출 없이 전량 측정이 가능한 몇 안 되는
영역이고, 이 결함이 오래 살아남은 이유가 바로 측정 수단의 부재였다.

사용법:
  python3 eval_tokenizer.py            # 전체 리포트
  python3 eval_tokenizer.py --check    # 임계 위반 시 exit 1 (CI용, M4 제외)
  python3 eval_tokenizer.py --full     # M4 포함 (BM25 전량 색인)
  python3 eval_tokenizer.py --discover # 보호어 후보 나열(사람이 판단)

실측 비용(macOS, 76,983문서): --check 약 5초 / --check --full 약 9초·460MB.

설계: docs/02-design/features/tokenizer-quality.design.md §8

⚠️ **어느 토크나이저 경로를 쟀는지 반드시 확인할 것.** konlpy가 설치된 로컬
   개발기에서는 Mecab 경로가 돌아 프로덕션(정규식)과 다른 수치가 나온다.
   이 스크립트는 매 실행 시 경로를 출력한다. CI에는 konlpy가 없다.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.bm25_search import (  # noqa: E402
    BM25_CORPUS_PATHS,
    BM25_MAX_DOCS,
    JOSA_SINGLE,
    _SPLIT_RE,
    PROTECTED_TERMS,
    STOPWORDS,
    _get_mecab,
    _tokenize_ko,
)

EVAL_QUERIES = Path("data/eval_retrieval_queries.json")

# ── 임계 (design §8) ────────────────────────────────────────────────────
# C0(구 토크나이저) 실측값을 괄호에 남긴다 — 개선 폭이 사라지면 드러나야 한다.
THRESHOLDS = {
    # M1 — **존재 단언이지 비율이 아니다.**
    #
    # ⚠️ 원래 M1은 "최대 분열률 < 7%"였는데, 그 지표는 **자신이 막으려던 회귀에서
    #    값이 거꾸로 내려갔다**(독립 리뷰 2026-08-27, 20,000문서로 직접 재현):
    #
    #        PROTECTED_TERMS 채움 → M1 3.75%  PASS
    #        PROTECTED_TERMS 비움 → M1 0.00%  PASS  ← 회귀인데 더 좋은 점수
    #
    #    분열률 탐지식은 원형과 절단형이 **둘 다 어휘에 있을 때만** 후보로 삼는다.
    #    그런데 `_strip_josa`는 문맥 독립적으로 일관되게 자르므로, 보호가 없으면
    #    원형이 어휘에서 통째로 사라져 후보 집합에서 탈락한다. 즉 분열률은
    #    **"분열"을 재는데 이 구현의 실패 모드는 "전면 절단"이다.**
    #
    #    구 구현에서는 절단이 문맥 의존적(`(?=\s|$)`)이라 분열이 지문으로 남았는데,
    #    그 지문을 없앤 것이 바로 이번 변경이다. 임계 7%의 근거로 적었던
    #    "보호 실패 시 43%·68%"도 구 구현 수치였다 — 새 구현에서는 0%다.
    #
    # → 지표는 **증상**(분열)이 아니라 **불변식**(보호어는 어휘에 존재한다)으로
    #   세운다. 보호어 전종의 어휘 카운트가 0이면 실패다. 분열률은 M1b로
    #   남겨 두되 게이팅하지 않는다(정보용).
    "M1": ("어휘에서 사라진 보호어", 0, "종", 40),
    "M2": ("주제어 절단", 0, "건", 3),
    "M3": ("불용어 잔존율", 1.0, "%", 5.7),
    # M5 — 주의 둘. 둘 다 실제로 오판을 만들었다.
    #
    # ① **양쪽 다 리스트 생성까지만** 재야 공정하다. 신 경로에만
    #    `Counter.update()`를 포함해 재면 1.94x가 나오는데 그건 Counter 비용이다.
    #
    # ② **이 배수는 인터프리터에 민감하다** — 구 경로는 C 레벨 정규식이고 신 경로는
    #    파이썬 레벨 루프라, 3.12+ 특수화 인터프리터의 수혜가 신 경로에만 간다.
    #    실측(각 버전 내에서는 안정적, 2회 반복):
    #        Python 3.11 → 1.91 / 1.93x  (NFC 가드 추가 후 1.99x)
    #        Python 3.14 → 1.44 / 1.48x
    #    **CI는 3.12라 값을 모른다.** 3.11 최악값 1.99x에 임계를 2.0x로 두면
    #    한 톨 차이로 깨지고, 그렇게 흔들리는 게이트는 곧 무시되거나 꺼진다.
    #    2.5x는 "토크나이저가 비정상적으로 느려졌는가"라는 **거친 경보**로서의
    #    역할은 유지하면서 인터프리터·환경 변동을 흡수한다.
    #
    # ⚠️ **이것은 NFR-1의 게이트가 아니다.** NFR-1(콜드 스타트 +50% 이내)의 근거는
    #    `load_bm25_corpus()` 왕복이고, 실제 로드는 gzip 해제·json 파싱·인터닝을
    #    함께 하므로 토크나이저 비중이 희석된다 — 실측 3.25s → 3.7~4.2s(**1.14~1.28x**).
    #    그 수치는 test_bm25_memory.py가 CI에서 출력한다(RSS는 실패시키고
    #    시간은 출력만 한다 — 러너 성능 편차가 커서 시간 게이트는 흔들린다).
    "M5": ("토큰화 시간 배수", 2.50, "x", 1.00),
    # M6 — 어휘 규모. 게이팅이 없으면 326,235로 회귀해도 --check가 통과한다
    # (설계 §8은 CI 대상에 M6을 포함했는데 구현에서 빠져 있었다 — 갭 G4).
    "M6": ("고유토큰", 300_000, "개", 326_235),
    # M7 임계 근거(실측): 정상(어미→조사) 4,045회 vs 역전(조사→어미) 72,048회.
    # 15,000은 두 값 사이에 넉넉히 있어 순서 역전을 확실히 잡는다.
    "M7": ("'…하/되' 잔재", 15_000, "회", 72_048),
}
M4_THRESHOLD = 85.0     # 핵심어 포함률 % (높을수록 좋음 — 다른 지표와 방향 반대)
M4_OLD = 74.5           # C0(구 토크나이저) 실측

# M2의 검사 대상은 `PROTECTED_TERMS`를 **그대로 쓴다.**
#
# 한때 `TOPIC_TERMS`라는 별도 목록이 있었으나 항상 `PROTECTED_TERMS`의
# 부분집합이었고, 손으로 동기화해야 하는 두 번째 한국어 목록일 뿐이었다.
# 실제로 한 번 어긋나 **최초 10종이 전부 이미 보호된 것들이라 미보호 도메인어를
# 아무도 검사하지 않는** 사각을 만들었다(독립 리뷰 2026-08-27).
# `m2_topic_preserved`의 `term in q` 가드가 "질의에 없는 용어는 무해하게 스킵"을
# 보장하므로 40종 전량을 그대로 넘겨도 안전하고 커버리지는 더 넓다.

# M4 — 고정 질의 × 핵심어. top-20 안에 핵심어를 문자열로 포함한 문서 비율.
M4_QUERIES = [
    ("회사가 연차휴가 사용촉진을 했는데도 안 쓰면 수당을 못 받나요?", "연차휴가"),
    ("출산전후휴가 90일을 나눠서 사용할 수 있나요?", "출산전후휴가"),
    ("육아기 근로시간 단축을 쓰면 연차휴가 일수는 어떻게 계산하나요?", "연차휴가"),
    ("연장근로수당 대신 보상휴가를 주는 제도는 어떻게 운영하나요?", "보상휴가"),
    ("휴일근로 가산수당은 어떻게 계산하나요?", "휴일근로"),
    ("노사 서면합의 없이 유연근무제를 할 수 있나요?", "서면합의"),
    ("소정근로시간은 어떻게 정하나요?", "소정근로"),
    ("야간근로 수당 지급 기준", "야간근로"),
    ("퇴직금 중간정산 합의가 유효한가요?", "합의"),
    ("근로 제공 의무가 없는 날", "근로"),
]


def _load_corpus_texts() -> list[str]:
    """코퍼스 원문 로드.

    **경로 탐색과 문서 상한을 `bm25_search`와 공유한다** — 여기서 `.jsonl.gz`만
    하드코딩하면 (a) 구 포맷만 배포된 상태에서 프로덕션은 정상인데 이 스크립트만
    죽고, (b) `BM25_MAX_DOCS` 미적용으로 **프로덕션과 다른 문서 집합**을 재게 된다.
    """
    path = next((p for p in BM25_CORPUS_PATHS if p.exists()), None)
    if path is None:
        print(f"ERROR: 코퍼스 없음({BM25_CORPUS_PATHS[0]}) — "
              f"build_bm25_corpus.py 실행 또는 gz 커밋 확인")
        sys.exit(2)
    opener = gzip.open if path.name.endswith(".gz") else open
    texts: list[str] = []
    with opener(path, "rt", encoding="utf-8") as f:
        if path.name.endswith((".jsonl", ".jsonl.gz")):
            for line in f:
                line = line.strip()
                if line:
                    texts.append(json.loads(line).get("text", ""))
                    if len(texts) >= BM25_MAX_DOCS:
                        break
        else:
            texts = [d.get("text", "") for d in json.load(f)[:BM25_MAX_DOCS]]
    if path.name != BM25_CORPUS_PATHS[0].name:
        print(f"  ⚠️ 구 포맷({path.name})을 읽었다 — 갱신이 멈춘 코퍼스일 수 있다")
    return texts


def _tokenize_corpus(texts: list[str]) -> tuple[collections.Counter, list, float]:
    """전량 토큰화 **1회** → (어휘 카운터, 문서별 토큰 리스트, 소요 시간).

    ⚠️ **토큰 리스트를 함께 돌려주는 것이 핵심이다.** 예전에는 `_build_vocab`·
    `_time_ratio`·`m4_keyword_rate`가 각자 캐시를 새로 만들어 76,983문서를
    **3~4회** 다시 토큰화했다 — 실측 5.96초로 `--check --full` 전체(8.66초)의
    약 42%가 순수 중복이었다. 한 번 만든 결과를 넘겨 쓰면 그만큼이 사라진다.
    """
    vocab: collections.Counter = collections.Counter()
    tokens: list[list[str]] = []
    cache: dict = {}
    t0 = time.monotonic()
    for t in texts:
        tok = _tokenize_ko(t, cache)
        tokens.append(tok)
        vocab.update(tok)
    return vocab, tokens, time.monotonic() - t0


def _legacy_tokenize_factory():
    """구 토크나이저 재현 — M5의 분모. 이 파일 안에 **의도적으로 복제**한다.

    구현을 교체하고 나면 배수를 잴 기준이 사라진다. 고정된 과거 값이므로
    `app/core/bm25_search.py`와 동기화할 필요가 없다.
    """
    import re
    a = re.compile(r"(?:에서|부터|까지|에게)(?=\s|$)")
    b = re.compile(r"[은는이가을를의로도만와과](?=\s|$)")
    c = re.compile(r"[^\w\s]")

    def legacy(t: str) -> list[str]:
        s = b.sub("", a.sub("", t))
        return [x for x in c.sub(" ", s).split() if len(x) >= 2]
    return legacy


def _legacy_time(texts: list[str]) -> float:
    """M5의 분모 — 구 토크나이저 전량 소요 시간.

    ⚠️ **신 경로와 정확히 같은 일만 하도록 재야 한다.** 신 경로에만
    `Counter.update()`를 포함해 재면 1.94x가 나오는데, 이는 토크나이저가 아니라
    Counter 비용을 잰 것이다(실제로 그렇게 재서 임계 위반으로 오판했다).
    그래서 여기도 `_tokenize_corpus`도 **리스트 생성까지만** 잰다
    (`_tokenize_corpus`의 Counter 갱신은 타이머 안에 있지만 양쪽 모두
    무시 가능한 수준이고, 분자 쪽에만 얹히므로 판정을 보수적으로 만든다).
    """
    legacy = _legacy_tokenize_factory()
    t0 = time.monotonic()
    for t in texts:
        legacy(t)
    return time.monotonic() - t0


def m1_missing_protected(vocab: collections.Counter) -> tuple[int, list]:
    """M1 — 어휘에서 **사라진** 보호어 종수. 0이어야 한다.

    불변식: `PROTECTED_TERMS`의 각 항목은 색인 어휘에 존재한다.
    보호가 풀리면 그 항목은 절단형으로만 남아 카운트가 0이 된다 — 비율과 달리
    이 판정은 실패 방향으로 단조롭다(THRESHOLDS의 M1 주석 참조).

    전제: 40종 전부가 코퍼스에 실제로 등장한다(실측 최소 카운트 283, `퇴직금제도`).
    보호어를 추가할 때는 그 항목이 코퍼스에 있는지 먼저 확인할 것 — 없는 단어를
    넣으면 이 지표가 영구히 실패한다.
    """
    missing = sorted(t for t in PROTECTED_TERMS if vocab[t] == 0)
    return len(missing), missing


def m1b_split_rate(vocab: collections.Counter) -> tuple[float, list]:
    """M1b — 분열률(정보용, **게이팅하지 않는다**).

    ⚠️ 이 값은 회귀 판정에 쓸 수 없다. 보호가 풀리면 원형이 어휘에서 사라져
    후보 집합에서 탈락하므로 값이 **내려간다**(M1 주석의 실측 참조).
    남겨 두는 이유는 잔여 분열의 구성을 눈으로 보기 위해서다 — 현재 상위는
    `근로복지과`↔`근로복지`처럼 **둘 다 진짜 단어**인 경우다.
    """
    rows = []
    for w, c in vocab.items():
        if len(w) >= 3 and c >= 200 and w[-1] in JOSA_SINGLE and w[:-1] in vocab:
            trunc = vocab[w[:-1]]
            rows.append((w, c, trunc, trunc / (c + trunc) * 100))
    rows.sort(key=lambda r: -r[3])
    return (rows[0][3] if rows else 0.0), rows


def discover_candidates(texts: list[str], vocab: collections.Counter,
                        min_count: int = 30) -> list[tuple[str, int]]:
    """`--discover` — 보호어 후보를 뽑아 **사람에게 보여준다.**

    자동 판정은 원리적으로 불가능하다 — `근로자가`의 `가`(조사)와 `연차휴가`의
    `가`(단어의 일부)는 문자열만으로 구분되지 않는다. 그래서 이 함수는 결정하지
    않고 **후보만** 낸다: 원문에 어절로 자주 나오는데 색인 어휘에는 없는 3음절
    이상 문자열. 대부분은 정상 절단(조사)이고, 그중 도메인 용어를 사람이 고른다.
    """
    eojeols: collections.Counter = collections.Counter()
    for t in texts:
        eojeols.update(w for w in _SPLIT_RE.split(t) if len(w) >= 3)
    out = [(w, c) for w, c in eojeols.items()
           if c >= min_count and vocab[w] == 0 and w[-1] in JOSA_SINGLE]
    out.sort(key=lambda x: -x[1])
    return out


def m2_topic_preserved() -> tuple[int, list]:
    """M2 — 평가셋 질의에서 주제어가 **절단되는** 건수.

    ⚠️ 판정은 완전일치가 아니라 **포함**이어야 한다. `연장근로수당`은 정당한
    단일 토큰이고 `연장근로`를 온전히 담고 있다 — 완전일치로 보면 이것이
    "주제어 소실"로 잡혀 오판한다(실제로 그렇게 재서 2건이 나왔다).
    잡아야 하는 것은 `연차휴가` → `연차휴`처럼 **글자가 깎인** 경우다.
    """
    if not EVAL_QUERIES.exists():
        # **조용히 통과시키지 않는다** — CI 게이트에 무음 통과 경로를 두면
        # 파일이 사라진 날부터 M2가 영원히 0건을 보고한다.
        raise FileNotFoundError(
            f"{EVAL_QUERIES} 없음 — M2를 측정할 수 없다(무음 통과 금지)")
    raw = json.loads(EVAL_QUERIES.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("queries", [])
    bad = []
    for it in items:
        q = it.get("query") if isinstance(it, dict) else it
        if not q:
            continue
        toks = _tokenize_ko(q)
        for term in PROTECTED_TERMS:
            if term in q and not any(term in t for t in toks):
                bad.append((q, term, toks[:6]))
    return len(bad), bad


def m3_stopword_rate(vocab: collections.Counter) -> float:
    total = sum(vocab.values())
    return sum(vocab[w] for w in STOPWORDS) / total * 100 if total else 0.0


def m7_residue(vocab: collections.Counter) -> int:
    """어미 절단 실패의 지문 — `…하`/`…되`로 끝나는 3음절 이상 토큰."""
    return sum(c for w, c in vocab.items()
               if len(w) >= 3 and w.endswith(("하", "되")))


def m4_keyword_rate(texts: list[str], tokens: list) -> tuple[float, list]:
    """M4 — BM25 전량 색인 후 top-20 핵심어 포함률.

    `tokens`는 `_tokenize_corpus`가 이미 만든 것을 받는다(재토큰화 금지).
    """
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        print("  ⚠️ rank_bm25 미설치 — M4 건너뜀")
        return -1.0, []
    idx = BM25Okapi(tokens)
    rows, hit_sum = [], 0
    for q, key in M4_QUERIES:
        scores = idx.get_scores(_tokenize_ko(q))
        top = sorted(range(len(scores)), key=lambda i: -scores[i])[:20]
        hit = sum(1 for i in top if key in texts[i])
        hit_sum += hit
        rows.append((key, hit))
    return hit_sum / (len(M4_QUERIES) * 20) * 100, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="임계 위반 시 exit 1")
    ap.add_argument("--full", action="store_true", help="M4 포함(느림)")
    ap.add_argument("--discover", action="store_true",
                    help="보호어 후보 나열(사람이 판단)")
    args = ap.parse_args()

    path = "Mecab(⚠️ 프로덕션 아님)" if _get_mecab() is not None else "정규식(프로덕션 동일)"
    print(f"토크나이저 경로: {path}")
    print(f"사전: 보호어 {len(PROTECTED_TERMS)}종 / 불용어 {len(STOPWORDS)}종 "
          f"/ 교집합 {len(PROTECTED_TERMS & STOPWORDS)}종")

    texts = _load_corpus_texts()
    vocab, tokens, elapsed = _tokenize_corpus(texts)
    base = _legacy_time(texts)
    total = sum(vocab.values())
    print(f"\n코퍼스 {len(texts):,}문서 / 총토큰 {total:,} / 고유토큰 {len(vocab):,}")
    print(f"토큰화 {elapsed:.2f}s (구 {base:.2f}s)")

    m1, m1_missing = m1_missing_protected(vocab)
    m1b, m1b_rows = m1b_split_rate(vocab)
    m2, m2_rows = m2_topic_preserved()
    results = {
        "M1": m1,
        "M2": m2,
        "M3": m3_stopword_rate(vocab),
        "M5": elapsed / base if base else 0.0,
        "M6": len(vocab),
        "M7": m7_residue(vocab),
    }

    # THRESHOLDS에만 있고 results에 없으면 KeyError로 요란하게 죽지만, 반대는
    # **조용하다** — 아래 루프가 THRESHOLDS만 순회하므로 검사도 출력도 안 된다.
    # 측정 도구가 자기 안에 조용한 실패를 갖는 것은 이 사이클의 주제와 정면 충돌한다.
    assert set(THRESHOLDS) == set(results), \
        f"THRESHOLDS↔results 키 불일치: {set(THRESHOLDS) ^ set(results)}"

    print(f"\n{'지표':<22} {'실측':>12} {'임계':>10} {'구값':>10}  판정")
    print("-" * 68)
    failed = []
    for mid, (name, thr, unit, old) in THRESHOLDS.items():
        val = results[mid]
        ok = val <= thr
        if not ok:
            failed.append(f"{mid} {name}: {val:,.2f}{unit} > {thr}{unit}")
        oldtxt = f"{old:,.2f}{unit}" if old is not None else "—"
        print(f"{mid} {name:<18} {val:>11,.2f}{unit:<1} {thr:>9,.2f}{unit:<1} "
              f"{oldtxt:>10}  {'✅' if ok else '❌'}")

    if m1_missing:
        print(f"\n[M1 사라진 보호어] {m1_missing}")
    if m1b_rows:
        print(f"\n[M1b 분열 상위 5 — 정보용, 게이팅 안 함] 최대 {m1b:.2f}%")
        for w, c, t, r in m1b_rows[:5]:
            print(f"   {w}({c:,}) ↔ {w[:-1]}({t:,})  분열률 {r:.2f}%")
    if m2_rows:
        print("\n[M2 주제어 절단]")
        for q, term, toks in m2_rows:
            print(f"   {term!r} 소실 — {q[:40]}… → {toks}")

    print(f"\n[최빈 토큰 20] (불용어 후보 관찰용 — '경우'류는 의도적 보류)")
    print("   " + ", ".join(f"{w}({c // 1000}k)" for w, c in vocab.most_common(20)))

    if args.discover:
        cands = discover_candidates(texts, vocab)
        print(f"\n[보호어 후보 상위 40] — 원문 어절로 30회 이상인데 색인에 없는 것")
        print("   ⚠️ 대부분은 정상 절단(조사)이다. 도메인 용어만 골라 "
              "PROTECTED_TERMS와 TOPIC_TERMS에 **함께** 넣을 것.")
        for w, c in cands[:40]:
            print(f"   {w:<18} {c:>6,}  → 현재 색인형 {_tokenize_ko(w)}")

    if args.full:
        print("\n[M4] BM25 전량 색인 중…")
        m4, m4_rows = m4_keyword_rate(texts, tokens)
        if m4 >= 0:
            for key, hit in m4_rows:
                print(f"   {key:<10} {hit:2}/20")
            ok = m4 >= M4_THRESHOLD
            print(f"M4 핵심어 포함률 {m4:.1f}% (임계 ≥{M4_THRESHOLD}%, 구값 {M4_OLD}%)"
                  f"  {'✅' if ok else '❌'}")
            if not ok:
                failed.append(f"M4 핵심어 포함률: {m4:.1f}% < {M4_THRESHOLD}%")

    if failed:
        print("\n❌ 임계 위반:")
        for f in failed:
            print(f"   - {f}")
        return 1 if args.check else 0
    print("\n✅ 전 지표 임계 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
