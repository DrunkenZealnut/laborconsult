"""NLRC 판정사례 번들 갱신 — odcloud API 전량 조회 후 data/nlrc_cases.json 재작성

사용법:
    python3 refresh_nlrc_cases.py   # ODCLOUD_API_KEY 필요 (.env)

신규 판정사례가 공개되면 주기적으로 실행 후 커밋한다.
런타임은 이 번들만 읽으므로(app/core/nlrc_cases.py::_load_bundle)
갱신하지 않아도 서비스는 기존 번들로 계속 동작한다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    api_key = os.getenv("ODCLOUD_API_KEY")
    if not api_key:
        print("ERROR: ODCLOUD_API_KEY not set")
        sys.exit(1)

    from app.core.nlrc_cases import _fetch_all_cases

    cases = _fetch_all_cases(api_key)
    if not cases:
        print("ERROR: odcloud 조회 결과 0건 — 기존 번들 유지")
        sys.exit(1)

    out_path = Path("data/nlrc_cases.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    print(f"NLRC bundle saved: {len(cases)} cases → {out_path}")


if __name__ == "__main__":
    main()
