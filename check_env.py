#!/usr/bin/env python3
"""환경변수 검증 스크립트 — 배포 전 필수/선택 환경변수 확인.

값은 어떤 키도 출력하지 않는다(접두 8자 노출도 없다 — ai-gateway-oidc-migration 제약).
LLM_TRANSPORT=gateway면 필수 키는 PINECONE_API_KEY만이고, 제공자 키가 남아 있으면 '삭제 후보'로 표시한다
(Gateway 모드는 그 키를 읽지 않는다. Vercel env에서는 복귀 창이 끝난 뒤 사용자 승인으로 지운다).
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()
# config.py와 같은 파일을 읽는다 — 저장소 루트 기준 절대경로(cwd 상대경로면 다른 디렉터리에서 실행할 때 조용히 빠진다, Check BS8).
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.vercel.local"), override=False)

PROVIDER_KEYS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "COHERE_API_KEY"]
REQUIRED_DIRECT = ["OPENAI_API_KEY", "PINECONE_API_KEY", "ANTHROPIC_API_KEY"]
REQUIRED_GATEWAY = ["PINECONE_API_KEY"]
OPTIONAL = [
    "PINECONE_INDEX_NAME",
    "GEMINI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "LAW_API_KEY",
    "ADMIN_PASSWORD",
    "ADMIN_JWT_SECRET",
]
GATEWAY_TOKENS = ["VERCEL_OIDC_TOKEN", "AI_GATEWAY_API_KEY"]


def _set(key: str) -> bool:
    return bool((os.environ.get(key) or "").strip())


def main():
    transport = (os.environ.get("LLM_TRANSPORT") or "direct").strip().lower()
    if transport not in ("direct", "gateway"):
        transport = "direct"
    print(f"=== 환경변수 검증 (LLM_TRANSPORT={transport}) ===\n")
    ok = True

    required = REQUIRED_GATEWAY if transport == "gateway" else REQUIRED_DIRECT
    print("[필수]")
    for key in required:
        if _set(key):
            print(f"  O {key}: 설정됨")
        else:
            print(f"  X {key}: 미설정 (필수)")
            ok = False

    if transport == "gateway":
        print("\n[Gateway 인증] 프로덕션(Vercel 함수)은 요청 헤더 x-vercel-oidc-token으로 받는다 — 아래는 로컬·CI용")
        for key in GATEWAY_TOKENS:
            print(f"  {'O' if _set(key) else '-'} {key}: {'설정됨' if _set(key) else '미설정'}")
        if not any(_set(k) for k in GATEWAY_TOKENS):
            print("  ! 로컬 실행이면 `vercel env pull .env.vercel.local --environment development`(12시간 토큰)")
        print("\n[제공자 키 — Gateway 모드에서는 읽지 않는다]")
        for key in PROVIDER_KEYS:
            if _set(key):
                print(f"  ~ {key}: 설정됨 → 삭제 후보(복귀 창 뒤 사용자 승인으로 Vercel env에서만 제거, 제공자 측 키는 폐기 금지)")
            else:
                print(f"  - {key}: 미설정")

    print("\n[선택]")
    for key in OPTIONAL:
        print(f"  {'O' if _set(key) else '-'} {key}: {'설정됨' if _set(key) else '미설정 (선택)'}")

    print()
    if not ok:
        print("필수 환경변수가 누락되었습니다!")
        print("  .env 파일 또는 Vercel 환경변수를 확인하세요.")
        sys.exit(1)
    print("모든 필수 환경변수 확인 완료")


if __name__ == "__main__":
    main()
