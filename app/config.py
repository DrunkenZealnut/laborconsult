"""앱 설정 — 환경변수에서 API 클라이언트 초기화"""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone
import anthropic
from supabase import create_client, Client as SupabaseClient

load_dotenv()

EMBED_MODEL = "text-embedding-3-small"
CLAUDE_MODEL = "claude-sonnet-5"
# OPENAI_CHAT_MODEL만 환경변수로 오버라이드 가능 — 모델 A/B 비교 및 무배포 롤백용.
# CLAUDE_MODEL/EXTRACT_MODEL은 상수로 고정한다: 셸 프로필에 낡은 CLAUDE_MODEL이
# export되어 있는 개발 환경에서 존재하지 않는 모델로 덮여 404가 나기 때문.
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "o3")
# 2026-08-06 실측: gemini-2.5-pro는 404("no longer available to new users")를 반환해
# 3순위 폴백(답변 생성·인용 교정 2순위)이 통째로 죽어 있었다. 폴백 계측이 없어
# 아무도 몰랐던 사각지대다(llm-fallback-hardening G7). gemini-pro-latest는 별칭이라
# 모델 EOL을 자동 추종하므로 같은 사고가 재발하지 않는다.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-pro-latest")
EXTRACT_MODEL = "claude-sonnet-5"

# ── LLM 타임아웃·재시도 예산 (llm-fallback-hardening FR-04) ───────────────────
# 원칙: 재시도보다 벤더 전환이 빠르고 안전하다 — 동일 벤더 재시도는 같은 장애를
# 다시 만나지만, 전환은 다른 결과를 만든다. 그래서 임계경로는 retries=0이다.
#
# ⚠️ 값 변경 시 docs/02-design/features/llm-fallback-hardening.design.md §3.4
#    예산표를 함께 갱신할 것. 최악 누적이 두 상한을 동시에 만족해야 한다:
#      - vercel.json maxDuration 300초 (초과 시 함수 강제 종료)
#      - public/index.html SEND_TIMEOUT_MS 60초 (무이벤트 구간이 넘으면 브라우저 abort)
CONNECT_TIMEOUT = 5.0
ANSWER_READ_TIMEOUT = float(os.getenv("ANSWER_READ_TIMEOUT", "20"))
# 재시도 상한 1로 클램프한다. 하트비트는 **벤더 전환 시점에만** 나가므로 한 벤더가
# 소비하는 시간이 그대로 무이벤트 구간이 된다: retries=1이면 2×25초=50초로 프론트
# idle 60초 안에 들어오지만, retries=2면 75초가 되어 폴백 도달 전에 브라우저가
# abort한다. 비상 완화 여지는 남기되 규약이 깨지는 값은 받지 않는다.
ANSWER_MAX_RETRIES = max(0, min(1, int(os.getenv("ANSWER_MAX_RETRIES", "0"))))
# 답변 생성 토큰 한도. citation_validator의 교정 한도와 묶여 있다 — 한쪽만 낮추면
# 교정 결과가 0.7 길이 가드에 걸려 통째로 폐기되고 환각 판례가 그대로 남는다.
ANSWER_MAX_TOKENS = 8192

INTENT_TIMEOUT = 12.0           # analyze_intent (임계경로, DB-6에서 도입)
INTENT_FALLBACK_TIMEOUT = 10.0  # OpenAI 교차벤더 폴백 (실측 2.7초)
EXTRACT_TIMEOUT = 10.0          # _extract_params 레거시 경로
CRITICAL_MAX_RETRIES = 0        # analyzer/extract/decomposer/self_rag 공통

# 의도분석 교차벤더 폴백 (FR-05). 비추론 모델을 기본값으로 둔다 — o3·gpt-5.x 계열은
# reasoning 토큰이 max_completion_tokens를 잠식해 tool_call이 빈 채로 끊길 수 있다.
INTENT_FALLBACK_ENABLED = os.getenv("INTENT_FALLBACK_ENABLED", "true").lower() != "false"
INTENT_FALLBACK_MODEL = os.getenv("INTENT_FALLBACK_MODEL", "gpt-4.1")
INTENT_FALLBACK_MAX_TOKENS = 4096

# 인용 교정 단계 전체 예산 (FR-07). 벤더 3곳 × 동적 타임아웃이 누적되면
# maxDuration을 위협하므로 단계 데드라인으로 자른다.
#
# 교정은 동기 호출이라 **단계 내부에서는 하트비트를 낼 수 없다** — 시작 직전 ping
# 하나가 전부다. 따라서 이 값이 곧 무이벤트 구간의 상한이고, 프론트 idle 60초보다
# 확실히 낮아야 한다. 45초는 15초 마진. 하트비트를 낼 수 있게 교정 단계를
# 제너레이터로 바꾸기 전까지는 이 값을 60 이상으로 올리지 말 것.
CITATION_STAGE_BUDGET = min(45.0, float(os.getenv("CITATION_STAGE_BUDGET", "45")))

# Pinecone 인덱스명 단일 출처 (DB-3) — 업로드·조회·테스트 스크립트가 모두 이 값을 공유한다.
# 프로덕션 env(PINECONE_INDEX_NAME) 실값과 일치 확인 완료(R-1) — 레거시 인덱스명 그대로 유지.
DEFAULT_PINECONE_INDEX = "semiconductor-lithography"


def resolve_index_name() -> str:
    return os.getenv("PINECONE_INDEX_NAME", DEFAULT_PINECONE_INDEX)


@dataclass
class AppConfig:
    openai_client: OpenAI
    pinecone_index: object | None
    claude_client: anthropic.Anthropic
    gemini_api_key: str | None = None
    supabase: SupabaseClient | None = None
    law_api_key: str | None = None
    odcloud_api_key: str | None = None
    cohere_api_key: str | None = None
    analyzer_model: str = EXTRACT_MODEL
    embed_model: str = EMBED_MODEL

    @property
    def anthropic_client(self) -> anthropic.Anthropic:
        """analyzer.py 호환용 alias"""
        return self.claude_client

    _REQUIRED_KEYS = ["OPENAI_API_KEY", "PINECONE_API_KEY", "ANTHROPIC_API_KEY"]

    @classmethod
    def from_env(cls) -> "AppConfig":
        missing = [k for k in cls._REQUIRED_KEYS if not os.environ.get(k)]
        if missing:
            raise EnvironmentError(
                f"필수 환경변수가 설정되지 않았습니다: {', '.join(missing)}\n"
                f".env 파일 또는 Vercel 환경변수를 확인하세요."
            )
        openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

        # Pinecone 인덱스 초기화 — 실패해도 챗봇은 계속 동작(RAG만 비활성화).
        # rag.py가 pinecone_index=None 및 쿼리 실패를 graceful하게 처리하므로,
        # 무효 키/Pinecone 장애 시에도 계산기·법령 API·LLM 답변은 정상 제공된다.
        index_name = resolve_index_name()
        pinecone_index = None
        try:
            pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
            pinecone_index = pc.Index(index_name)
            logging.info("Pinecone index=%s", index_name)
        except Exception as exc:
            logging.warning(
                "Pinecone 초기화 실패 (index=%s) — 벡터 검색(RAG) 없이 동작합니다: %s",
                index_name, exc,
            )

        claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        # 접속 생성은 storage.make_supabase_client 단일 경로 — 스키마 옵션이
        # 빠지면 public 으로 새고 그 실패가 조용하다(2026-08-13 board_posts 사고).
        from app.core.storage import make_supabase_client
        supabase = make_supabase_client()
        law_api_key = os.getenv("LAW_API_KEY")
        odcloud_api_key = os.getenv("ODCLOUD_API_KEY")
        cohere_api_key = os.getenv("COHERE_API_KEY")
        return cls(
            openai_client=openai_client,
            pinecone_index=pinecone_index,
            claude_client=claude_client,
            gemini_api_key=gemini_api_key,
            supabase=supabase,
            law_api_key=law_api_key,
            odcloud_api_key=odcloud_api_key,
            cohere_api_key=cohere_api_key,
        )
