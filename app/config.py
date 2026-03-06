"""앱 설정 — 환경변수, API 클라이언트, Pinecone 인덱스"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone
import anthropic

load_dotenv()


@dataclass
class AppConfig:
    openai_client: OpenAI = None
    anthropic_client: anthropic.Anthropic = None
    pinecone_index: object = None
    namespace: str = "laborlaw"

    analyzer_model: str = "claude-sonnet-4-20250514"
    answer_model: str = "claude-sonnet-4-20250514"
    embed_model: str = "text-embedding-3-small"

    rag_top_k: int = 5
    legal_top_k: int = 5
    rag_threshold: float = 0.3

    @classmethod
    def from_env(cls) -> "AppConfig":
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        host = os.getenv("PINECONE_HOST")
        pinecone_index = pc.Index(host=host)
        namespace = os.getenv("PINECONE_NAMESPACE", "laborlaw")

        return cls(
            openai_client=openai_client,
            anthropic_client=anthropic_client,
            pinecone_index=pinecone_index,
            namespace=namespace,
        )
