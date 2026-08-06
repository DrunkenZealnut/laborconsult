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
GEMINI_MODEL = "gemini-2.5-pro"
EXTRACT_MODEL = "claude-sonnet-5"


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
        index_name = os.getenv("PINECONE_INDEX_NAME", "semiconductor-lithography")
        pinecone_index = None
        try:
            pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
            pinecone_index = pc.Index(index_name)
        except Exception as exc:
            logging.warning(
                "Pinecone 초기화 실패 — 벡터 검색(RAG) 없이 동작합니다: %s", exc
            )

        claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        supabase = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None
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
