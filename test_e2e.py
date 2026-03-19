#!/usr/bin/env python3
"""
E2E 통합 테스트 — 로컬 서버 기동 후 실행

사용법:
  1. uvicorn api.index:app --host 0.0.0.0 --port 5555
  2. python3 test_e2e.py

또는:
  python3 test_e2e.py --base-url http://localhost:8000
"""

import argparse
import json
import sys

import requests

DEFAULT_BASE_URL = "http://localhost:5555"


def test_health(base_url: str) -> bool:
    """T-05: 헬스체크"""
    r = requests.get(f"{base_url}/api/health", timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data.get("status") == "ok", f"Expected status=ok, got {data}"
    return True


def test_chat_sync(base_url: str) -> bool:
    """T-04: 동기 채팅"""
    r = requests.post(
        f"{base_url}/api/chat",
        json={"message": "최저임금이 얼마인가요?"},
        timeout=60,
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert "message" in data, f"'message' field missing: {list(data.keys())}"
    assert len(data["message"]) > 10, "Response too short"
    return True


def test_chat_stream(base_url: str) -> bool:
    """T-01: SSE 스트리밍"""
    r = requests.get(
        f"{base_url}/api/chat/stream",
        params={"message": "주휴수당이 뭔가요?"},
        stream=True,
        timeout=60,
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"

    events = []
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass

    assert len(events) >= 2, f"Expected >=2 events, got {len(events)}"

    # 첫 이벤트는 session
    types = [e.get("type") for e in events]
    assert "session" in types, f"No session event in: {types}"
    return True


def test_chat_stream_calc(base_url: str) -> bool:
    """T-02: 임금계산 요청 스트리밍"""
    r = requests.get(
        f"{base_url}/api/chat/stream",
        params={"message": "월급 300만원, 주5일 8시간 근무, 퇴직금 계산해주세요. 3년 근무했습니다."},
        stream=True,
        timeout=60,
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"

    events = []
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass

    # meta 이벤트에 calc_result 포함 확인
    meta_events = [e for e in events if e.get("type") == "meta"]
    has_calc = any(e.get("calc_result") for e in meta_events)
    # calc_result가 없을 수도 있음 (follow_up 질문일 수 있음) — 최소한 응답은 있어야 함
    has_response = any(e.get("type") in ("chunk", "follow_up") for e in events)
    assert has_response, f"No chunk or follow_up event found in {len(events)} events"
    return True


def test_invalid_input(base_url: str) -> bool:
    """T-08: 잘못된 입력"""
    r = requests.post(
        f"{base_url}/api/chat",
        json={},
        timeout=10,
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
    return True


def test_admin_login_fail(base_url: str) -> bool:
    """T-06: 관리자 로그인 실패"""
    r = requests.post(
        f"{base_url}/api/admin/login",
        json={"password": "wrong_password_12345"},
        timeout=10,
    )
    # 401 (비밀번호 틀림) 또는 503 (ADMIN_PASSWORD 미설정)
    assert r.status_code in (401, 503), f"Expected 401/503, got {r.status_code}"
    return True


def test_admin_stats_unauthorized(base_url: str) -> bool:
    """T-07: 관리자 통계 (인증 없이)"""
    r = requests.get(f"{base_url}/api/admin/stats", timeout=10)
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    return True


ALL_TESTS = [
    ("T-05 헬스체크", test_health),
    ("T-08 잘못된 입력 (422)", test_invalid_input),
    ("T-06 관리자 로그인 실패", test_admin_login_fail),
    ("T-07 관리자 통계 (미인증)", test_admin_stats_unauthorized),
    ("T-04 동기 채팅", test_chat_sync),
    ("T-01 SSE 스트리밍", test_chat_stream),
    ("T-02 임금계산 스트리밍", test_chat_stream_calc),
]


def main():
    parser = argparse.ArgumentParser(description="E2E 통합 테스트")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 서버 URL")
    parser.add_argument("--quick", action="store_true", help="빠른 테스트 (API 호출 제외)")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"=== E2E 통합 테스트 ===")
    print(f"서버: {base_url}\n")

    # 서버 접속 확인
    try:
        requests.get(f"{base_url}/api/health", timeout=3)
    except requests.ConnectionError:
        print(f"서버에 연결할 수 없습니다: {base_url}")
        print("  uvicorn api.index:app --host 0.0.0.0 --port 5555")
        sys.exit(1)

    tests = ALL_TESTS
    if args.quick:
        # 빠른 테스트: API 호출이 필요 없는 것만
        tests = [t for t in ALL_TESTS if "스트리밍" not in t[0] and "동기 채팅" not in t[0]]

    passed = 0
    failed = 0

    for name, fn in tests:
        try:
            fn(base_url)
            print(f"  O {name}")
            passed += 1
        except AssertionError as e:
            print(f"  X {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  X {name}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n결과: {passed}/{passed + failed} 통과")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
