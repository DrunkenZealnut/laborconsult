#!/usr/bin/env python3
"""환경변수 검증 스크립트 — 배포 전 필수/선택 환경변수 확인"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

REQUIRED = ["OPENAI_API_KEY", "PINECONE_API_KEY", "ANTHROPIC_API_KEY"]
OPTIONAL = [
    "PINECONE_INDEX_NAME",
    "GEMINI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "LAW_API_KEY",
    "ADMIN_PASSWORD",
    "ADMIN_JWT_SECRET",
]


def main():
    print("=== 환경변수 검증 ===\n")
    ok = True

    print("[필수]")
    for key in REQUIRED:
        val = os.environ.get(key, "")
        if not val:
            print(f"  X {key}: 미설정 (필수)")
            ok = False
        else:
            print(f"  O {key}: 설정됨 ({val[:8]}...)")

    print("\n[선택]")
    for key in OPTIONAL:
        val = os.environ.get(key, "")
        if val:
            print(f"  O {key}: 설정됨")
        else:
            print(f"  - {key}: 미설정 (선택)")

    print()
    if not ok:
        print("필수 환경변수가 누락되었습니다!")
        print("  .env 파일 또는 Vercel 환경변수를 확인하세요.")
        sys.exit(1)
    else:
        print("모든 필수 환경변수 확인 완료")


if __name__ == "__main__":
    main()
