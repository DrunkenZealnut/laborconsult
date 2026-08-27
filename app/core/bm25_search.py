"""BM25 키워드 검색 + Dense 벡터 검색 RRF 결합 모듈

Pinecone Dense 검색에 BM25 키워드 매칭을 결합하여
정확한 법조문 번호/용어 검색 시 recall을 향상시킨다.

- **프로덕션 토크나이저는 정규식이다** (konlpy 미설치 — 아래 토크나이저 절 참조)
- Mecab은 그것이 설치된 로컬 개발기에서만 동작하는 보조 경로
- Vercel serverless: 글로벌 변수로 cold start 시 1회만 로드
"""

from __future__ import annotations

import gc
import json
import logging
import re
import sys
import time
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

# ── BM25 인덱스 (글로벌 캐시) ────────────────────────────────────────────

_bm25_index = None       # rank_bm25.BM25Okapi | None
_bm25_corpus = None      # list[dict] — _KEEP_FIELDS만 보관(book_id 포함)
_bm25_loaded = False
_loaded_src: str | None = None   # 어느 코퍼스 파일을 읽었는지(/api/health 관측용)

_BM25_DATA_DIR = Path(__file__).parent.parent.parent / "data"
# gz(배포용 커밋 대상) 우선, raw json(로컬 빌드 산출물) 폴백 (DB-1)
# JSONL(신) 우선, JSON 배열(구) 폴백. **양쪽을 계속 지원한다** — 코드와 데이터의
# 배포 시점이 어긋날 수 있어서다(코드가 먼저 나가면 구 gz를, 데이터가 먼저 나가면
# 신 gz를 읽어야 한다). 구 포맷 지원 제거는 전환이 끝난 뒤 별도 커밋으로 한다.
BM25_CORPUS_PATHS = [_BM25_DATA_DIR / "bm25_corpus.jsonl.gz",
                     _BM25_DATA_DIR / "bm25_corpus.jsonl",
                     _BM25_DATA_DIR / "bm25_corpus.json.gz",
                     _BM25_DATA_DIR / "bm25_corpus.json"]

# 코퍼스에서 보관할 필드 — 원본 줄 dict를 그대로 담으면 스트리밍의 의미가 없다
# (같은 객체를 계속 들고 있게 된다). 검색 결과 반환에 쓰이는 것만 옮긴다.
# **build_bm25_corpus.py가 이 상수를 import한다** — 두 곳에서 손으로 선언하면
# 빌더가 필드를 추가해도 `_slim()`이 말없이 버려, Dense 히트에는 있고 BM25
# 히트에만 빈 값인 상태가 된다(경로 리뷰 M4). 회귀는 test_offline_units.py.
CORPUS_FIELDS = ("id", "text", "title", "section", "source_type", "book_id")
_KEEP_FIELDS = CORPUS_FIELDS
# 그중 반복이 큰 것만 인터닝한다(text는 문서마다 달라 공유될 일이 없다).
_INTERN_FIELDS = ("title", "section", "source_type", "book_id")
# 실측(60,174건 전체 로드 시 BM25Okapi 인덱스까지 프로세스 RSS 약 815MB, 2026-07-14).
# "여유"라 부를 수준은 아님 — Vercel 함수 메모리가 1GB라면 남는 건 ~185MB뿐이고,
# 여기 도달하기 전에 이 프로세스 다른 부분(FastAPI·다른 SDK 클라이언트·GraphRAG 등)도
# 메모리를 쓴다. 코퍼스가 커지면 이 상수와 실제 배포 메모리 한도를 함께 재검토할 것.
# 소프트 MemoryError는 app/core/rag.py::search_hybrid()의 broad except가 잡아
# Dense-only로 폴백하지만, OS 레벨 하드 OOM-kill은 코드로 방어 불가능하다.
#
# 후속 실측(2026-08-18, Vercel preview, 해설서 3권 체제 + 청크 신호 게이트 적용):
# 66,307건 로드 9.0초, OOM 없음. vercel.json은 legacy `builds` 블록이라 memory
# 키가 없어 기본 1024MB다. 로드 시간은 7.8초(2026-08-16, 게이트 이전 66,354건)에서
# 늘었고 콜드 스타트 첫 요청 지연에 그대로 얹힌다 — 건수가 줄었는데도 늘었다는 건
# 이 시간이 문서 수가 아니라 인스턴스 상태에 좌우된다는 뜻이므로, 회귀 판단의
# 기준선으로 쓰지 말 것.
#
# 후속 실측(2026-08-25, 로컬 macOS, 76,983건 — 훈령 1,763 적재 후):
#   인터닝 **이전**에는 gz 파싱 427MB → 인덱스 구축 **1,218MB**로 Vercel 기본
#   한도 1024MB의 **119%**였다. 문자열 인터닝을 넣어 **683MB(67%)** 로 내렸다
#   (load_bm25_corpus의 인터닝 주석 참조). 단계별 실측:
#
#     단계              인터닝 전 → 후
#     코퍼스 로드          437MB → 445MB
#     토큰화 피크          934MB → 536MB
#     BM25Okapi 구축     1,218MB → 683MB
#
#   로드 시간은 2.6초로 동일하고 검색 결과도 불변이다(같은 토큰 문자열을 공유할
#   뿐 값이 바뀌지 않는다).
#
#   ⚠️ 이 여유는 **코퍼스 증가로 다시 잠식된다** — 대략 문서 1만 건당 +90MB다.
#   소프트 MemoryError는 search_hybrid의 broad except가 Dense-only로 흡수하지만
#   그 경우 **하이브리드 검색이 조용히 반쪽이 되고**, OS 하드 OOM-kill은 방어 불가다.
#
# 최종 실측(2026-08-26, JSONL 스트리밍 전환 후): 로컬 macOS **약 410MB(40%)**, 로드 2.6초.
#
# ⚠️ **후속 실측(2026-08-27, tokenizer-quality 적용 후): macOS 446MB / 로드 3.4초.**
#   토크나이저가 정확해지면서 어절 캐시(약 42만 항목)와 토큰 수(+1.4%)가 얹혔다.
#   상한 550MB까지 남은 여유가 140MB → **97MB**로 줄었다(문서 1만 건당 +90MB
#   기준으로 약 1만 건분). **CI(Linux) 값은 아직 재측정되지 않았다** — 위 경고대로
#   판단은 Linux 값으로 해야 하는데 현재 기록된 370MB는 변경 **전** 값이다.
#
# ⚠️ **CI(Linux) 실측은 다르다** — 370MB(36%), 로드 **7.0초**, 그리고 구 배열 경로도
#   384MB뿐이다(로컬은 704MB). 즉 **플랫폼별 절대값·절감폭이 크게 다르다**:
#     macOS: 704 → 409MB (42% 절감)
#     Linux: 384 → 370MB (3.6% 절감)   ← 프로덕션이 Linux다
#   할당자·페이지 회수 정책 차이로 보인다. 판단 근거로는 **Linux 값을 쓸 것** —
#   "한도의 119%"라는 최초 진단도 macOS 측정이었고, Linux 기준으로는 그만큼
#   임박한 위험이 아니었을 수 있다. 다만 스트리밍이 더 낮다는 방향은 두 플랫폼에서
#   일치하고, 증가율을 낮추는 구조적 이점은 그대로다.
#   로드 시간 7.0초는 콜드 스타트 첫 요청에 그대로 얹힌다(개선 대상이 아니었다).
#   스트리밍이 배열 파싱의 이중 상주(코퍼스 dict + 토큰 리스트)를 없앤 결과다.
#   구 배열 폴백 경로는 여전히 약 700MB(69%)이므로 신 포맷 커밋이 전제다.
#   회귀는 test_bm25_memory.py(별도 프로세스, 상한 550MB, 초과 시 **실패**).
#   남은 완화 후보: text 미보관+fetch 보충 · 샤딩 · Vercel 메모리 상향
#   (대안별 실측은 docs/02-design/features/bm25-memory-scaling.design.md §1).
#
# BM25_MAX_DOCS의 의미가 **스트리밍 전환으로 바뀌었다**(2026-08-26).
#   · JSONL 경로: 루프 안에서 절단하므로 이 값이 **실제로 메모리를 제한한다.**
#   · 구 배열 경로(폴백): 여전히 json.load 이후 절단이라 피크를 줄이지 못한다.
# 즉 지금은 신 포맷에서만 유효한 상한이다.
BM25_MAX_DOCS = 100_000


# ── 한국어 토크나이저 (tokenizer-quality) ────────────────────────────────
#
# ⚠️ **프로덕션 경로는 정규식이다.** `konlpy`는 requirements.txt에 없고, konlpy의
#    Mecab은 파이썬 패키지만으로 부족하다(시스템 바이너리 mecab-ko + 사전
#    mecab-ko-dic 필요). @vercel/python 빌드에는 그 설치 단계가 없으므로
#    `_get_mecab()`은 배포본에서 **항상** ImportError로 떨어진다.
#    아래 정규식 경로가 지금까지 프로덕션의 유일한 토크나이저였다.
#
#    → **로컬에서 Mecab으로 잰 수치를 프로덕션 근거로 쓰지 말 것.** 두 경로는
#      서로 다른 토큰을 낸다. CI에는 konlpy가 없어 자동으로 정규식 경로를 잰다.
#      `eval_tokenizer.py`는 어느 경로를 쟀는지 항상 출력한다.
#
# 이 절의 규칙은 전부 코퍼스 76,983문서 전량 실측에서 나왔다. 설계 근거는
# `docs/02-design/features/tokenizer-quality.design.md`.

_mecab = None
_mecab_checked = False

# 절단 결과가 이 길이 미만이면 절단하지 않는다.
#
# ⚠️ **이 가드가 없으면 2음절 단어가 색인에서 통째로 사라진다.** `합의` → 조사
#    후보 `의` 절단 → `합`(1음절) → 최종 `len >= MIN_STEM` 필터가 폐기. 실측
#    16종 중 13종 소멸: 합의·근로·휴가·동의·협의·이의·임의·대가·차이·고의·
#    사이·별도·연도. `근로`와 `휴가`가 단독 등장 시 색인에 없었다.
#    긴 어절에서 절단돼 온 것(`근로를`→`근로`)만 살아남아 어휘 목록에는 보였고,
#    그래서 아무도 눈치채지 못했다. 회귀는 test_offline_units.py T-g.
#
# ⚠️ 최종 길이 필터를 없애는 것으로 대체하지 말 것 — 막아야 할 것은 **파편
#    생성**이지 파편 폐기가 아니다. 없애면 `합`·`근` 같은 1음절이 색인에 들어간다.
MIN_STEM = 2

# 다글자 조사 — **긴 것을 먼저** 나열한다(최장일치). `으로`가 `으로써`보다 앞서면
# `으로`가 먼저 매치해 `써`가 남는다. 사건부호 화이트리스트(`다카`가 `다`보다 앞)와
# 같은 실패 클래스다.
JOSA_MULTI = ("으로써", "으로서", "에서는", "으로는", "에게는", "이라도", "만으로",
              "에서", "부터", "까지", "에게", "한테", "으로", "이나", "라도",
              "조차", "마저", "처럼", "보다", "이란", "라는", "에는", "에도")

# 끝글자별 버킷 — `w.endswith(j)`가 성립하려면 반드시 `w[-1] == j[-1]`이므로
# 끝글자로 후보를 좁혀도 **결과가 완전히 동일하다**(실측: 고유 어절 417,123건
# 전량에서 불일치 0). 23개 전수 순회 대비 평균 후보가 1~5개로 줄어 `_strip_josa`가
# 490ms → 100ms(**4.9배**)가 된다. 캐시 미스가 몰리는 콜드 스타트에서
# `_load_streaming` 시간의 약 15%에 해당해 NFR-1 예산에 직접 반영된다.
# **그룹 내 순서는 JOSA_MULTI 원래 순서를 유지해야 한다**(최장일치).
_JOSA_MULTI_BY_TAIL: dict[str, tuple[str, ...]] = {}
for _j in JOSA_MULTI:
    _JOSA_MULTI_BY_TAIL[_j[-1]] = _JOSA_MULTI_BY_TAIL.get(_j[-1], ()) + (_j,)

# 1글자 조사. 구 구현에는 `에`가 없어 `노동청에`/`노동청`이 다른 토큰이었다.
# `께`(높임 여격)는 상담 텍스트에 거의 없고 `께서`·`께는` 등 활용이 많아
# 단독 절단의 실익이 없다 — 의도적 제외다(Plan FR-3 대비 유일한 미채택).
JOSA_SINGLE = frozenset("은는이가을를의로도만와과에")

# 말끝 조사 절단을 금지할 도메인 실단어(40종).
#
# 구 구현은 어절 끝 한 글자가 조사 후보면 무조건 떼어내, 노동법 복합명사의
# 마지막 글자를 삼켰다(`연차휴가`→`연차휴`). 실측 분열률: 연차휴가 43% ·
# 연차유급휴가 46% · 출산전후휴가 51% · 회계년도 68%.
#
# ⚠️ **이 목록은 커레이션이고, 자동 발견되지 않는다.** 최초 27종은 "구 구현이
#    남긴 분열쌍"에서 뽑았는데 그것은 **편향된 표본**이었다 — 구 구현에서
#    문맥에 따라 원형이 살아남은 것만 보였기 때문이다. 독립 리뷰(2026-08-27)가
#    그 사각에서 13종을 더 찾았고, 그중 둘은 **다른 실단어와 병합**되고 있었다:
#      근로시간제도 → `근로시간제`(569회, 실재하는 별개 용어와 병합)
#      전문가       → `전문`(398회, 판례 `전문(全文)`과 병합)
#    나머지(생리휴가·배우자출산휴가·가족돌봄휴가·파견근로·단시간근로·기간제근로·
#    서면동의·부서명 5종)는 원형 카운트가 전부 **0**이었다 — 즉 코퍼스에 있는데
#    색인에는 없었다.
#    → 새 도메인 용어를 추가할 때는 `eval_tokenizer.py --discover`로 후보를
#      뽑아 **사람이 판단**할 것. 자동 탐지는 조사와 단어 끝글자를 구분할 수 없다.
#
# **STOPWORDS와 교집합이 없어야 한다** — 같은 탐지가 찾아낸 45종이 정반대 처방을
# 요구하는 두 부류로 나뉘기 때문이다(도메인 실단어는 보호, 연결어는 제거).
# 하나로 합치면 그 구분이 코드에서 사라진다. 회귀는 T-d.
PROTECTED_TERMS = frozenset("""
연차휴가 연차유급휴가 유급휴가 무급휴가 출산휴가 출산전후휴가 보상휴가
생리휴가 배우자출산휴가 가족돌봄휴가
연장근로 휴일근로 소정근로 야간근로 계속근로 초과근로
파견근로 단시간근로 기간제근로
서면합의 노사합의 서면동의 영업양도 회계연도 회계년도 전문가
퇴직연금제도 퇴직급여제도 퇴직금제도 근로시간제도
근로기준정책과 퇴직연금복지과 근로기준과 근로개선정책과 임금근로시간과 근로복지과
근로조건지도과 임금복지과 여성고용정책과 고용평등정책과
""".split())
# 행정 부서명 10종을 보호하는 이유는 **BM25 recall**이다. 코퍼스에 50종 6,266회가
# 있고 절단되면 `근로조건지도과`(147회) → `근로조건지도` → `근로조건지`로 이중
# 절단된다.
#
# ⚠️ 한때 이 자리에 "citation_validator.py가 `[부서명]과-NNNN`으로 검증하는
#    문자열과 같다"고 적혀 있었으나 **사실이 아니다**(독립 리뷰 2026-08-27).
#    `citation_validator.py`에는 `_tokenize_ko`·`bm25` 참조가 없고,
#    `_ADMIN_PATTERN`은 `hit["title"]`·`chunk_text`(원문 그대로)에 대해 돈다.
#    토크나이저 토큰을 보는 경로가 없다 — 인용 검증은 이 목록과 무관하다.

# 색인에서 제외할 상용구·연결어·2음절 문법형·질의 어미(51종).
#
# 상담 크롤러가 붙이는 정형 인사말/서명이 총토큰의 5.6%를 차지했다("안녕하세요…
# 한국노총 부천상담소입니다… 권익향상을 위해 노력하고… 성원과 관심… 좋은
# 하루되시기 바랍니다"). 고빈도라 IDF가 낮아 오매칭을 직접 유발하진 않지만,
# 상담 문서만 일률적으로 doc_len을 부풀려 **BM25 길이 정규화**로 해설서·판례
# 대비 점수가 깎인다.
#
# ⚠️ `경우`(74k)·`해당`(24k)은 **일부러 넣지 않았다.** 고빈도지만 법률 문언의
#    명사이고 IDF가 이미 억제하고 있다. 오제거의 대가는 회수 불능이다.
#
# ⚠️ **2음절 관형형·활용형은 `MIN_STEM`이 새로 들여보낸다**(독립 리뷰 2026-08-27).
#    구 구현은 `있는 `→`는` 절단→`있`(1자)→폐기했는데, `MIN_STEM=2`는 2음절의
#    절단 자체를 막으므로 그대로 색인된다. 실측 `있는`이 **53,000회로 3번째
#    최빈 토큰**이었다. STOPWORDS를 넣은 명분이 "상용구가 doc_len을 부풀려 BM25
#    길이 정규화를 왜곡한다"였는데 이 부작용은 **같은 해를 반대 방향으로** 만들고,
#    조문체 문장에 편중된다. 그래서 순수 문법형만 골라 아래 4번째 줄에 넣었다
#    (`대한`·`위해`·`따라`·`대해`는 명사가 아니라 용언 활용형이다 — 초기 분류가
#    틀렸었다). `경우`·`해당`과 달리 이들은 단독으로 문서를 구별하지 못한다.
STOPWORDS = frozenset("""
안녕하세요 한국노총 노동OK 부천상담소입니다 바랍니다 하루되시기 권익향상 성원
관심 노동환경개선 노력하고 저희 있습니다 없습니다 합니다 입니다 드립니다 감사합니다
것으로 것으 것이므로 것이므 하지만 실제로 하더라도 하더라 원칙적으로
있으므로 있으므 없으므로 없으므 하므로 아니므로 있지만 중심으로
있는 많은 좋은 또는 대한 위해 따라 대해
없는 같은 다른 아닌 같이 이런 모든 여러
되나요 있나요 하나요 인가요 어떻게 어떤 얼마나 갑자기
""".split())
# `관심`(16,055)·`노동환경개선`(16,021)은 `권익향상`·`성원`이 들어간 **바로 그
# 서명 블록의 나머지 절반**인데 최초 목록에서 빠져 있었다(각 문서의 20.9%).
#
# ⚠️ **"어간 닫힌집합 + 관형형 어미" 규칙으로 일반화하려다 기각했다.** 언뜻
#    `있/없/많/같/다르` 같은 어간 목록 하나로 `있는`·`없는`·`같은`을 한꺼번에
#    잡을 수 있어 보이지만, 어간 첫 글자 매칭은 **대명사+조사까지 끌어온다** —
#    실측 `저는`(5,843)·`이는`(5,042)·`아는`(102)·`다는`(82)이 같은 규칙에
#    걸린다. 이들은 관형형이 아니라 전혀 다른 현상이고, 지우면 `저`·`이`가
#    소실된다. 안전한 일반화가 아니므로 **실측 고빈도만 명시 열거**한다
#    (없는 8,895 · 같은 7,375 · 다른 6,716 · 아닌 5,157 · 같이 4,525 ·
#     이런 2,184 · 모든 2,053 · 여러 1,297 = 총토큰의 0.7%).
#    `적은`(612)은 "적다(few)"와 "적다(write)"가 겹쳐 **일부러 뺐다.**

# 명사+하다/되다 활용 어미 — **긴 것 먼저**(최장일치).
#
# 이 부류로 한정하는 이유: 어간이 이미 코퍼스에 명사로 존재하므로 절단 결과가
# 실재하는 단어임이 보장된다. 일반 용언 어미까지 넓히면 오변환(무관한 단어가
# 한 토큰으로 수렴)이 생기는데, 오변환은 미변환보다 비싸다(colloquial_map과
# 같은 원칙). `지급해야`·`지급하여야`·`지급한다`·`지급합니다`·`지급하는`이
# 전부 `지급`으로 수렴한다.
ENDINGS = ("하여야한다", "하여야하는", "하였습니다", "되었습니다", "하겠습니다",
           "드립니다", "하여야", "해야하는", "했습니다", "합니다", "습니다",
           "됩니다", "하여", "해야", "한다", "된다", "하는", "되는", "했다",
           "됐다", "하고", "되고", "하며", "되며", "하면", "되면", "하기", "되기")
# `$` 앵커가 있어 `search()`의 최左 매치가 곧 최장 접미사다 — **여기서는 나열
# 순서가 결과에 영향이 없다**(순서를 뒤집어 13개 입력 대조, 차이 0). 순서가
# 실제로 중요한 곳은 반복 루프로 도는 `JOSA_MULTI`뿐이다. `re.escape`는 지금
# 메타문자가 없어도 걸어 둔다 — 나중에 `(`가 든 어미가 추가되면 조용히 깨진다.
_ENDING_RE = re.compile("(?:" + "|".join(map(re.escape, ENDINGS)) + ")$")

# 어절 분할 — **조사 절단 '전에'** 구두점을 경계로 소진한다.
#
# 구 구현은 구두점 치환이 조사 절단 뒤에 있어, 룩어헤드 `(?=\s|$)`가 구두점을
# 보지 못했다. 그 결과 `근로자와,` → `근로자와`(조사 잔류)가 되어 **같은 단어가
# 문맥에 따라 3가지로 토큰화**됐다(공백 뒤 `연차휴`, 조사 뒤 `연차휴가`,
# 구두점 뒤 `연차휴가`). 먼저 분할하면 모든 조사가 어절 끝에 오므로 룩어헤드
# 자체가 불필요해진다.
_SPLIT_RE = re.compile(r"[^0-9A-Za-z가-힣]+")

_CACHE_MISS = object()


def _get_mecab():
    """Mecab 인스턴스 lazy loading (1회만 시도).

    프로덕션에서는 항상 None이다(모듈 상단 경고 참조).
    """
    global _mecab, _mecab_checked
    if _mecab_checked:
        return _mecab
    _mecab_checked = True
    try:
        from konlpy.tag import Mecab
        _mecab = Mecab()
        logger.info("Mecab 형태소 분석기 로드 완료 — "
                    "프로덕션(정규식)과 다른 토큰을 냅니다")
    except Exception as e:
        logger.info("Mecab 미사용 (정규식 경로 — 프로덕션과 동일): %s", e)
        _mecab = None
    return _mecab


def _norm_ending(w: str) -> str:
    """④ 명사+하다/되다 활용 어미 정규화."""
    m = _ENDING_RE.search(w)
    if m and m.start() >= MIN_STEM:
        return w[:m.start()]
    return w


def _strip_josa(w: str) -> str:
    """⑤ 조사를 한 단위씩 **반복** 절단. 매 회차 보호어를 먼저 검사한다.

    지켜야 할 것 셋 — 전부 프로토타입에서 실제로 깨뜨려 본 것이다:

    1. **반복이어야 한다.** 조사는 중첩된다(`에는`·`으로는`·`에서의`·`만으로`).
       구 구현의 "2글자 1회 + 1글자 1회"는 `경우에는` → `경우에`에서 멈췄다
       (그래서 `경우에`가 어휘에 16,180회 있었다).

    2. **보호어 검사가 루프 안에 있어야 한다.** 최적화로 단일 탐욕 정규식
       `(?:...|[은는이가...])+$`을 썼더니 `연차휴가를`이 `가를`을 한꺼번에
       매치해 `연차휴`가 됐다 — 원형에서만 검사하면 중간 결과(`연차휴가`)가
       보호받지 못한다. 같은 정규식은 `근로를`에서 `로를`을 매치해 어간 가드에
       걸려 **아무것도 절단하지 않는** 반대 방향 오류도 냈다.

    3. **다글자 조사는 긴 것부터**(JOSA_MULTI 주석 참조).
    """
    while len(w) > MIN_STEM and w not in PROTECTED_TERMS:
        for j in _JOSA_MULTI_BY_TAIL.get(w[-1], ()):    # 끝글자 버킷 = 전수와 동치
            if w.endswith(j) and len(w) - len(j) >= MIN_STEM:
                w = w[:-len(j)]
                break
        else:
            if w[-1] in JOSA_SINGLE and len(w) - 1 >= MIN_STEM:
                w = w[:-1]
                continue
            break
    return w


def _reduce_eojeol(w: str) -> str | None:
    """어절 1개 → 색인 토큰 1개(제외 시 None). ③~⑦단계.

    ⚠️ **④어미가 ⑤조사보다 먼저다. 순서를 뒤집지 말 것.**
       한국어 어미(`-는`)와 조사(`는`)는 표기가 겹친다. 조사를 먼저 처리하면
       `지급하는`의 `는`이 조사로 오인돼 떨어지고, 남은 `지급하`는 어떤 어미
       패턴에도 매치되지 않아 그대로 색인된다. 잔재 토큰이 약 18배로 늘고 시간은
       동일하다 — 순서만 바꾸는 무비용 개선이다. 회귀는 T-h.
       **실측치의 단일 출처는 `eval_tokenizer.py`의 M7 임계 주석이다**
       (설계 문서 §2.2는 세는 문자 집합이 달라 값이 다르다).

    ⚠️ 불용어 검사가 **두 번**인 것도 의도다. 원형 기준(`안녕하세요`)과 절단 후
       기준(`경우에는`→`경우`)이 둘 다 필요하고, 한쪽만 두면 나머지가 샌다.
    """
    if len(w) < MIN_STEM or w in STOPWORDS:      # ③ 불용어 1차(원형)
        return None
    w = _strip_josa(_norm_ending(w))             # ④ 어미 → ⑤ 조사
    if len(w) < MIN_STEM or w in STOPWORDS:      # ⑥ 불용어 2차 + ⑦ 길이
        return None
    return w


def _tokenize_ko(text: str, cache: dict | None = None) -> list[str]:
    """한국어 토크나이저.

    Args:
        text: 대상 문자열
        cache: 어절→토큰 메모이제이션 dict. **로드 스코프로만 쓸 것**
               (`_load_streaming`이 소유하고 BM25 인덱스 구축 전에 해제한다).
               전역 캐시로 두면 질의마다 항목이 누적돼 무한히 자라고, 질의는
               어절 10개 남짓이라 이득도 없다.

    코퍼스 측과 질의 측이 **이 함수 하나**를 공유한다. 두 경로가 갈라지면
    색인과 질의의 토큰이 어긋나 검색이 조용히 죽는다 — 회귀는 T-e.
    """
    mecab = _get_mecab()

    if mecab is not None:
        try:
            pos_tags = mecab.pos(text)
            # 불용어는 Mecab 경로에도 적용한다 — 두 경로를 조금이라도 붙여 둔다.
            tokens = [
                word for word, tag in pos_tags
                if tag.startswith(("NNG", "NNP", "VV", "VA"))
                and len(word) >= MIN_STEM and word not in STOPWORDS
            ]
            if tokens:
                return tokens
        except Exception:
            pass  # Mecab 실패 → 정규식 경로

    # ⓪ NFC 정규화 — `_SPLIT_RE`의 `가-힣`은 **NFD(자모 분해) 문자열에 절대
    #    매치되지 않는다.** NFD 입력은 어절이 통째로 버려져 `[]`가 나온다(실측).
    #    웹 경로는 `abuse_guard.validate_message`가 NFC를 걸어 주지만
    #    `chatbot.py`·eval·benchmark·LLM 분해 쿼리에는 정규화가 없다 —
    #    거기서 NFD가 들어오면 검색이 조용히 0건이 된다. macOS 파일명이 NFD인
    #    것과 같은 함정 계열이다(CLAUDE.md의 post_id 사고 참조).
    #    `is_normalized` 선검사로 이미 NFC인 경우를 건너뛴다(실측 +2%).
    if not text.isascii() and not unicodedata.is_normalized("NFC", text):
        text = unicodedata.normalize("NFC", text)

    out: list[str] = []
    for eojeol in _SPLIT_RE.split(text):         # ① 어절 분할
        if cache is None:
            tok = _reduce_eojeol(eojeol)
        else:                                    # ② 캐시 조회
            tok = cache.get(eojeol, _CACHE_MISS)
            if tok is _CACHE_MISS:
                tok = _reduce_eojeol(eojeol)
                cache[eojeol] = tok
        if tok is not None:
            out.append(tok)
    return out


# ── BM25 코퍼스 로드 ─────────────────────────────────────────────────────

def _slim(doc: dict) -> dict:
    """원본 줄 dict → 보관용 dict.

    **원본을 그대로 담지 않는 것이 핵심**이다 — 그대로 append하면 파싱된 객체를
    계속 참조하게 되어 스트리밍의 이득이 사라진다. 검색 결과 반환에 쓰이는
    필드만 새 dict로 옮기고, 반복이 큰 것은 인터닝한다.
    """
    out = {}
    for key in _KEEP_FIELDS:
        val = doc.get(key)
        if val is None:
            continue
        if key in _INTERN_FIELDS and isinstance(val, str):
            val = sys.intern(val)
        out[key] = val
    return out


def _load_streaming(corpus_path) -> tuple[list[dict], list[list[str]]]:
    """코퍼스를 읽어 (보관용 문서 목록, 토큰 리스트)를 만든다.

    **JSONL이면 한 줄씩 처리해 원본 dict를 즉시 놓아준다.** 배열(구 포맷)은
    `json.load()`가 전체를 파싱할 수밖에 없어 피크가 높다 — 폴백 경로다.

    실측(76,983문서, 인터닝 포함):
      배열 일괄  692MB / 2.7초
      JSONL 스트리밍  415MB / 2.8초   ← Vercel 1024MB의 41%

    토큰 인터닝은 **여기서도 반드시 유지**한다. 토큰의 94.1%가 중복이라
    (549만 → 고유 32.6만) 인터닝이 없으면 스트리밍을 해도 한도를 넘는다.
    회귀 `test_offline_units.py::test_bm25_interning`이 고정한다.

    **어절 캐시(tokenizer-quality)** — 정확한 토큰화는 어절마다 파이썬 레벨
    반복이 필요해 구 구현(텍스트 전체에 정규식 sub 2회 = C 레벨)보다 느리다.
    토큰의 94.1%가 중복이라는 같은 사실이 어절 수준에도 성립하므로, `어절 →
    토큰|None` dict 하나로 대부분을 조회 1회로 만든다(캐시 항목 약 42만).

    ⚠️ **배수를 인용할 때 무엇을 잰 값인지 밝힐 것.** 토크나이저 순수 배수는
    인터프리터에 민감하다(3.11 ≈1.9x, 3.14 ≈1.46x — eval_tokenizer.py M5 주석).
    NFR-1(콜드 스타트)의 근거는 그 배수가 아니라 **`load_bm25_corpus()` 왕복
    실측 3.25s → 4.17s(1.28x, Python 3.11)** 다. 캐시가 없으면 이 왕복이
    1.5배 이상으로 벌어진다.

    캐시는 이 함수가 소유하고 반환 전에 해제한다 — 호출부의 `BM25Okapi` 구축이
    RSS 피크이므로 **피크와 겹치지 않는다.**
    """
    import gzip

    opener = (gzip.open if str(corpus_path).endswith(".gz") else open)
    corpus: list[dict] = []
    tokenized: list[list[str]] = []
    tok_cache: dict[str, str | None] = {}
    is_jsonl = corpus_path.name.endswith((".jsonl", ".jsonl.gz"))

    def _ingest(doc: dict) -> None:
        """두 분기(JSONL·배열)가 공유하는 적재부. 루프 제어만 서로 다르다."""
        tokenized.append([sys.intern(w)
                          for w in _tokenize_ko(doc.get("text", ""), tok_cache)])
        corpus.append(_slim(doc))

    try:
        with opener(corpus_path, "rt", encoding="utf-8") as f:
            if is_jsonl:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    if len(corpus) >= BM25_MAX_DOCS:
                        # 코퍼스는 네임스페이스 순차 수집이라 파일 **뒷부분이 qa**다
                        # (build_bm25_corpus.py의 NS 순서). 상한에 걸리면 무작위가
                        # 아니라 최대 코퍼스인 Q&A의 꼬리가 통째로 잘린다 — Dense가
                        # 받쳐주므로 증상이 "특정 주제만 BM25 미도달"로만 나타난다.
                        logger.warning("BM25_MAX_DOCS(%d) 도달 — 코퍼스 뒷부분이 "
                                       "잘렸습니다(주로 qa 네임스페이스)", BM25_MAX_DOCS)
                        break            # 스트리밍이라 이 상한이 실제 메모리를 제한한다
                    try:
                        doc = json.loads(line)
                    except json.JSONDecodeError as e:
                        # **전량 중단이 옳다** — 줄 단위 skip은 "부분 데이터가 정상으로
                        # 보이는" 실패를 만든다(빌더에 급감 가드가 있는 이유와 같다).
                        # 다만 어디서 깨졌는지는 남겨야 진단이 가능하다.
                        raise ValueError(
                            f"{corpus_path.name} {lineno}번째 줄 파싱 실패 "
                            f"(그때까지 {len(corpus)}건 읽음): {e}") from e
                    _ingest(doc)
            else:
                # 구 포맷 — 전체 파싱이 불가피하다. 파싱본을 빨리 놓아주려고
                # 순회하며 옮긴 뒤 원본을 해제한다(피크는 낮아지지 않는다).
                #
                # ⚠️ 빌더는 더 이상 이 포맷을 쓰지 않는다 — 여기 진입했다는 것은
                # 신 포맷이 배포본에 없다는 뜻이고, 그 파일은 **갱신이 멈춘 코퍼스**일
                # 수 있다(law-version-drift와 같은 실패 클래스: 낡은 데이터를 조용히
                # 계속 쓴다). 메모리도 약 300MB 높다.
                logger.warning("BM25: 구 배열 포맷(%s) 사용 — 갱신이 멈춘 코퍼스일 수 "
                               "있고 메모리 피크가 약 300MB 높습니다. "
                               "bm25_corpus.jsonl.gz 커밋을 확인하세요.", corpus_path.name)
                raw = json.load(f)
                for doc in raw[:BM25_MAX_DOCS]:
                    _ingest(doc)
                del raw
                gc.collect()
    finally:
        # 캐시는 여기서 놓아준다 — 호출부의 BM25Okapi 구축이 RSS 피크이므로
        # 그 전에 해제해야 피크에 더해지지 않는다.
        #
        # **`finally`인 이유**: 줄 파싱 실패(`raise ValueError`) 경로에서도 42만
        # 항목을 놓아야 한다. 예외는 호출부의 broad except까지 traceback으로 이
        # 프레임을 붙들고 가므로, 정상 반환 직전에만 두면 그 구간 내내 캐시가
        # 살아 있다. `_ingest` 클로저가 참조하므로 `del`이 아니라 `clear()`다.
        tok_cache.clear()
        gc.collect()
    return corpus, tokenized


def load_bm25_corpus() -> bool:
    """BM25 코퍼스 로드 (서버 시작 시 1회).

    포맷: `data/bm25_corpus.jsonl.gz` (한 줄 = 문서 1건, 신)
          `data/bm25_corpus.json.gz`  (JSON 배열, 구 — 폴백. 피크가 약 300MB 높다)
    문서: {"id", "text", "title", "section", "source_type", "book_id"?}

    Returns:
        True if loaded successfully, False otherwise
    """
    global _bm25_index, _bm25_corpus, _bm25_loaded, _loaded_src

    if _bm25_loaded:
        return _bm25_index is not None

    _bm25_loaded = True

    corpus_path = next((p for p in BM25_CORPUS_PATHS if p.exists()), None)
    if corpus_path is None:
        # **warning 이상이어야 한다.** 코퍼스 미커밋은 프로덕션이 조용히
        # Dense-only로 떨어지는 가장 흔한 원인이고, 이 로그가 유일한 신호다.
        logger.warning("BM25 corpus not found: %s — 하이브리드 검색이 "
                       "Dense-only로 동작합니다(gz 커밋 누락 확인)",
                       BM25_CORPUS_PATHS[0])
        return False

    try:
        from rank_bm25 import BM25Okapi

        start = time.monotonic()
        _bm25_corpus, tokenized = _load_streaming(corpus_path)

        _bm25_index = BM25Okapi(tokenized)
        # BM25Okapi는 doc_freqs·idf·doc_len만 보관하고 원본 토큰 리스트를 참조하지
        # 않는다 — 명시 해제로 피크 이후 상주 메모리를 낮춘다.
        del tokenized
        gc.collect()

        elapsed = (time.monotonic() - start) * 1000
        # **어느 파일을 읽었는지 남긴다.** 신·구 포맷의 로그가 같으면 "고쳤다고
        # 믿는데 프로덕션은 구 경로(700MB)"가 아무 신호 없이 성립한다(경로 리뷰 H2).
        _loaded_src = corpus_path.name
        logger.info("BM25 loaded: %d docs, %.0fms, src=%s",
                    len(_bm25_corpus), elapsed, corpus_path.name)
        return True

    except ImportError:
        logger.warning("rank_bm25 not installed — BM25 disabled")
        return False
    except Exception as e:
        # **코퍼스를 반드시 놓아준다.** _bm25_corpus는 인덱스 구축 **전**에 채워지므로,
        # BM25Okapi가 MemoryError로 죽으면 쓸모없는 코퍼스 400MB가 프로세스 수명 내내
        # 남는다 — 메모리가 모자라 실패한 상황에서 메모리를 붙들어 이후 요청
        # (FastAPI·Pinecone·GraphRAG)의 OOM 위험을 키운다(경로 리뷰 M7).
        _bm25_corpus = None
        _bm25_index = None
        gc.collect()
        logger.warning("BM25 load failed: %s", e)
        return False


# ── BM25 검색 ────────────────────────────────────────────────────────────

def search_bm25(query: str, top_k: int = 10) -> list[dict]:
    """BM25 키워드 검색.

    Args:
        query: 검색 쿼리 텍스트
        top_k: 최대 반환 건수

    Returns:
        [{id, title, section, content, source_type, score, search_type}, ...]
    """
    if _bm25_index is None or _bm25_corpus is None:
        return []

    tokens = _tokenize_ko(query)
    if not tokens:
        return []

    scores = _bm25_index.get_scores(tokens)

    # 상위 top_k 인덱스 추출 (numpy 없이 순수 Python)
    indexed_scores = [(i, s) for i, s in enumerate(scores) if s > 0]
    indexed_scores.sort(key=lambda x: x[1], reverse=True)
    top_indices = indexed_scores[:top_k]

    results = []
    for idx, score in top_indices:
        doc = _bm25_corpus[idx]
        results.append({
            "id": doc["id"],
            "title": doc.get("title", ""),
            "section": doc.get("section", ""),
            "content": doc.get("text", ""),
            "source_type": doc.get("source_type", ""),
            "book_id": doc.get("book_id", ""),   # 해설서 인용 가드(G4) 키
            "score": round(float(score), 4),
            "search_type": "bm25",
        })

    logger.info("BM25 검색: query=%r, %d건", query[:40], len(results))
    return results


# ── Reciprocal Rank Fusion (RRF) ─────────────────────────────────────────

RRF_K = 60  # 표준 RRF 상수


def rrf_merge_ranked_lists(result_lists: list[list[dict]], top_k: int = 10) -> list[dict]:
    """여러 쿼리의 BM25 결과를 순위 기반으로 병합 (DB-8).

    멀티쿼리 분해 이점이 단일 문자열 결합 검색에서 상실되던 문제 해소 —
    쿼리별 검색 결과를 RRF로 결합한다.
    """
    scores: dict[str, float] = {}
    hit_map: dict[str, dict] = {}
    for hits in result_lists:
        for rank, hit in enumerate(hits):
            doc_id = hit["id"]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
            if doc_id not in hit_map:
                hit_map[doc_id] = hit
    ordered = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [hit_map[doc_id] for doc_id in ordered[:top_k]]


def reciprocal_rank_fusion(
    dense_hits: list[dict],
    bm25_hits: list[dict],
    alpha: float = 0.5,
    top_k: int = 15,
) -> list[dict]:
    """Dense + BM25 결과를 RRF로 결합.

    Args:
        dense_hits: Pinecone Dense 검색 결과
        bm25_hits: BM25 키워드 검색 결과
        alpha: Dense 가중치 (0.0=BM25 only, 1.0=Dense only, 0.5=균등)
        top_k: 반환할 최대 건수

    Returns:
        RRF 점수 기준 정렬된 결합 결과
    """
    rrf_scores: dict[str, float] = {}
    hit_map: dict[str, dict] = {}

    # Dense 점수
    for rank, hit in enumerate(dense_hits):
        doc_id = hit["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + alpha / (RRF_K + rank + 1)
        if doc_id not in hit_map:
            hit_map[doc_id] = hit

    # BM25 점수
    for rank, hit in enumerate(bm25_hits):
        doc_id = hit["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + (1 - alpha) / (RRF_K + rank + 1)
        if doc_id not in hit_map:
            hit_map[doc_id] = hit

    # RRF 점수 내림차순 정렬
    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)

    results = []
    for doc_id in sorted_ids[:top_k]:
        hit = hit_map[doc_id].copy()
        hit["rrf_score"] = round(rrf_scores[doc_id], 6)
        results.append(hit)

    logger.info(
        "RRF fusion: Dense %d + BM25 %d → %d (alpha=%.1f)",
        len(dense_hits), len(bm25_hits), len(results), alpha,
    )
    return results
