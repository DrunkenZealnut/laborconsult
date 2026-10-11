"""교차벤더 LLM 어댑터 헬퍼 (llm-fallback-hardening FR-05)

Anthropic tool_use 규약으로 작성된 도구 스펙을 OpenAI function calling으로 번역하고,
멀티모달 content를 평문으로 평탄화한다. 호출 자체는 `llm_gateway`가 한다.

이 모듈이 별도로 존재하는 이유는 순환 import다 — `pipeline.py`가 `analyzer.py`를
import하므로, analyzer가 pipeline의 헬퍼(`_flatten_content` 등)를 가져오면 순환이
된다. 양쪽이 함께 의존할 수 있는 하위 모듈에 둔다.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def flatten_content(content) -> str:
    """멀티모달 content 블록을 평문으로 평탄화.

    Anthropic messages의 content는 문자열이거나 블록 리스트다. OpenAI Chat
    Completions로 넘길 때는 평문이어야 하므로 텍스트 블록만 남긴다.

    ⚠️ `pipeline._flatten_content`와 **의도적으로 다르다** — 그쪽은 이미지 탈락을
    사용자에게 알리는 안내 문구를 주입하지만, 이 함수는 조용히 탈락시킨다.
    의도분석은 사용자에게 보여줄 답변이 아니라 구조화 추출 입력이므로 안내 문구가
    들어가면 추출 대상 텍스트를 오염시킨다. 두 함수를 하나로 합치지 말 것.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(p for p in parts if p)


def anthropic_tool_to_openai(tool: dict) -> dict:
    """Anthropic tool 스펙 → OpenAI function 스펙.

    JSON Schema 본문(`input_schema`)은 양쪽이 호환되므로 **무수정 재사용**한다.
    스키마를 복제하지 않는 것이 요점이다 — 복제하면 필드가 추가될 때 한쪽만
    갱신되어 두 벤더의 추출 결과가 조용히 달라진다.
    """
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }
