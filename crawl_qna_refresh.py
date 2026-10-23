#!/usr/bin/env python3
"""Bounded, resumable Q&A refresh. Never writes to original folders or Pinecone."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import time
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from qna_ingestion import inventory, parse_listing, parse_live, public_manifest, render_markdown
from vector_ledger import atomic_write_json

KST = ZoneInfo("Asia/Seoul")

def now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")

def save(path: Path, value) -> None:
    atomic_write_json(str(path), value)

def refresh(*, run_dir: Path, baseline: dict, fetch, start_page: int, end_page: int,
            since: str, until: str, revisit_pending: bool) -> dict:
    if start_page < 1 or end_page < start_page:
        raise ValueError("invalid page interval")
    cutoff = datetime.fromisoformat(until)
    if cutoff.tzinfo is None:
        raise ValueError("cutoff requires timezone")
    run_dir.mkdir(parents=True, exist_ok=True)
    run_dir.chmod(0o700)
    for sub in ["documents", "records"]:
        (run_dir/sub).mkdir(exist_ok=True)
    state_path = run_dir/"state.json"
    identity = {"since": since, "until": until, "start_page": start_page,
                "end_page": end_page, "revisit_pending": revisit_pending}
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "identity": identity, "started_at": now(), "pages": {}, "posts": {}}
    if state["identity"] != identity:
        raise ValueError("resume settings differ; use a new run directory")
    targets = {}
    for page in range(start_page, end_page + 1):
        previous = state["pages"].get(str(page), {})
        if previous.get("status") != "ok":
            try:
                rows = parse_listing(fetch(f"https://www.nodong.kr/qna?page={page}"))
                previous = {"status": "ok", "rows": rows, "fetched_at": now()}
            except (ValueError, requests.RequestException) as exc:
                previous = {"status": "failed", "error": type(exc).__name__ + ": " + str(exc)[:160]}
            state["pages"][str(page)] = previous
            save(state_path, state)
        for row in previous.get("rows", []):
            posted = row["posted_at"]
            if not posted or since <= posted <= cutoff.date().isoformat():
                targets[row["post_id"]] = row
    if revisit_pending:
        for post_id, row in baseline.items():
            if row["status"] in {"unanswered", "conflict", "parse_error"}:
                targets.setdefault(post_id, row)
    # Freeze a complete target list before the first document fetch.
    save(run_dir/"targets.json", sorted(targets))
    for i, (post_id, target) in enumerate(targets.items(), 1):
        old_result = state["posts"].get(post_id, {})
        if old_result.get("status") in {"ok", "outside_cutoff"}:
            continue
        try:
            doc = parse_live(fetch(target["canonical_url"]), post_id, now())
            published = datetime.fromisoformat(doc["posted_datetime"]) if doc.get("posted_datetime") else None
            if doc["posted_at"] == cutoff.date().isoformat() and published is None:
                raise ValueError("publication_time_missing_at_cutoff")
            if (published and published > cutoff) or (doc["posted_at"] and doc["posted_at"] > cutoff.date().isoformat()):
                result = {"status": "outside_cutoff", "posted_at": doc["posted_at"]}
            else:
                old = baseline.get(post_id)
                change = ("new" if old is None else
                          "unchanged" if old["content_hash"] == doc["content_hash"] else "changed")
                doc.update(change=change, run_id=run_dir.name)
                # A crash between these writes is repaired by refetching the unfinished ID.
                md_path = run_dir/"documents"/f"{post_id}.md"
                md_tmp = md_path.with_suffix(".tmp")
                md_tmp.write_text(render_markdown(doc), encoding="utf-8")
                md_tmp.replace(md_path)
                doc.update(local_paths=[str(md_path.resolve())], selected_path=str(md_path.resolve()))
                save(run_dir/"records"/f"{post_id}.json", doc)
                result = {"status": "ok", "change": change, "content_hash": doc["content_hash"],
                          "posted_at": doc["posted_at"], "answer_status": doc["status"],
                          "new_answer": bool(doc["answers"]) and old is not None and old["status"] == "unanswered"}
        except (ValueError, requests.RequestException) as exc:
            result = {"status": "failed", "error": type(exc).__name__ + ": " + str(exc)[:160]}
        state["posts"][post_id] = result
        save(state_path, state)
        if i % 50 == 0 or i == len(targets):
            print(f"documents {i}/{len(targets)}", flush=True)
    counts = Counter(x.get("change") for x in state["posts"].values() if x["status"] == "ok")
    failed_ids = sorted(k for k, v in state["posts"].items() if v["status"] == "failed")
    failed_pages = [int(k) for k, v in state["pages"].items() if v["status"] != "ok"]
    dates = [v["posted_at"] for v in state["posts"].values() if v.get("posted_at")]
    visited = sorted(int(k) for k, v in state["pages"].items() if v["status"] == "ok")
    report = {
        **identity, "run_id": run_dir.name, "finished_at": now(),
        "visited_pages": visited, "failed_pages": failed_pages,
        "target_documents": len(targets), "new": counts["new"], "changed": counts["changed"],
        "unchanged": counts["unchanged"], "failed": len(failed_ids), "failed_ids": failed_ids,
        "unvisited_ids": sorted(set(targets) - set(state["posts"])),
        "latest_posted_at": max(dates, default=None),
        "new_answers": sum(v.get("new_answer", False) for v in state["posts"].values()),
        "date_unknown": sorted(k for k,v in state["posts"].items() if v["status"] == "ok" and not v.get("posted_at")),
        "still_unanswered": sum(v.get("answer_status") == "unanswered" for v in state["posts"].values()),
        "complete": not failed_pages and not failed_ids and not (set(targets) - set(state["posts"])),
        "coverage": "explicit page interval and selected legacy IDs; not the entire website",
    }
    save(run_dir/"report.json", report)
    return report

class PoliteFetcher:
    def __init__(self, delay: float = 1.0):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "laborconsult-qna-refresh/1.0"
        self.delay = max(delay, 0.5)
        response = self.session.get("https://www.nodong.kr/robots.txt", timeout=30)
        response.raise_for_status()
        self.robots = RobotFileParser()
        self.robots.parse(response.text.splitlines())
        self.last = time.monotonic()
    def __call__(self, url: str) -> str:
        if not self.robots.can_fetch(self.session.headers["User-Agent"], url):
            raise ValueError("robots_disallowed")
        time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        for attempt in range(3):
            try:
                response = self.session.get(url, timeout=30)
                self.last = time.monotonic()
                response.raise_for_status()
                return response.text
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** (attempt + 1))

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, action="append", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--since", default="2026-03-01")
    parser.add_argument("--until", default=None)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--revisit-pending", action="store_true")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    args.run_dir.chmod(0o700)
    baseline_path = args.run_dir/"baseline-manifest.json"
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text())
    else:
        baseline = inventory(args.source_dir)
        save(baseline_path, baseline)
    report = {"files": sum(len(v["local_paths"]) for v in baseline.values()),
              "unique_ids": len(baseline), "statuses": dict(Counter(v["status"] for v in baseline.values())),
              "date_unknown": sum(not v["posted_at"] for v in baseline.values()),
              "latest_posted_at": max((v["posted_at"] for v in baseline.values() if v["posted_at"]), default=None)}
    save(args.run_dir/"inventory-report.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if args.inventory_only:
        return 0
    old_state = args.run_dir/"state.json"
    until = args.until or (json.loads(old_state.read_text())["identity"]["until"] if old_state.exists() else now())
    result = refresh(run_dir=args.run_dir, baseline=baseline, fetch=PoliteFetcher(args.delay),
                     start_page=args.start_page, end_page=args.end_page, since=args.since,
                     until=until, revisit_pending=args.revisit_pending)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["complete"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
