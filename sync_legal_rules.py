#!/usr/bin/env python3
"""Read Pinecone changes; --persist saves pending candidates, never approvals."""
import argparse
import json
import os
import sys

from app.core.legal_updates import LegalUpdateService, topics
from app.core.legal_rule_store import PineconeEvidence, configured_store


def scan_topics(service, selected):
    results = []
    for topic in selected:
        try:
            results.append(service.scan(topic, "scheduled-scan"))
        except Exception:
            results.append({"topic": topic, "status": "failed", "new_count": 0})
    return results


def scan_exit_code(results):
    """부분 검색도 자동 감시가 완전하지 않았으므로 실패 신호로 처리한다."""
    return 1 if any(r["status"] in {"failed", "partial"} for r in results) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", choices=["all", *topics()], default="all")
    parser.add_argument("--persist", action="store_true", help="검토 대기 후보와 검색 이력만 저장")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv()
    from openai import OpenAI
    from pinecone import Pinecone
    from app.config import resolve_index_name
    try:
        evidence = PineconeEvidence(Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(resolve_index_name()),
                                    OpenAI(api_key=os.environ["OPENAI_API_KEY"]))
        selected = list(topics()) if args.topic == "all" else [args.topic]
        if args.persist:
            results = scan_topics(LegalUpdateService(configured_store(), evidence), selected)
        else:
            # Default is read-only: no Supabase credentials or writes are needed.
            results = []
            for topic in selected:
                try:
                    hits = evidence.search(f"{topics()[topic]} 법령 개정 시행일 고시 판례 행정해석")
                    status = ("partial" if getattr(hits, "partial", False)
                              else "completed" if hits else "empty")
                    results.append({"topic": topic, "status": status,
                                    "evidence_ids": [h["id"] for h in hits], "persisted": False})
                except Exception:
                    results.append({"topic": topic, "status": "failed", "persisted": False})
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return scan_exit_code(results)
    except Exception:
        print("법률 기준 검색 초기화 실패: 서버 환경변수와 저장소를 확인하세요", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
