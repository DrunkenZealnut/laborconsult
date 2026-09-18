"""Candidate lifecycle. Search creates pending documents; only humans approve values."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import urlparse
from uuid import uuid4

from wage_calculator.legal_rules import PARAMETERS, iso_date, validate_value


class RuleError(ValueError):
    pass


class EvidenceError(RuleError):
    pass


class Conflict(RuleError):
    pass


OFFICIAL_HOSTS = ("law.go.kr", "moel.go.kr", "scourt.go.kr", "work24.go.kr",
                  "ei.go.kr", "nps.or.kr", "nhis.or.kr", "comwel.or.kr", "nts.go.kr")
SOURCE_TYPES = {"law", "statute", "regulation", "interpretation", "precedent"}
PROPOSAL_FIELDS = {"topic", "kind", "key", "value", "effective_from", "effective_to",
                   "evidence_id", "quote", "citation", "note"}


def now():
    return datetime.now(timezone.utc).isoformat()


def topics():
    from wage_calculator.facade.registry import CALC_TYPES
    return dict(CALC_TYPES)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def event_record(record):
    """이력에 담을 레코드 요약. **근거 원문(text)은 복제하지 않는다.**

    전량 보관은 이력 크기를 `revision 수 × 문서 크기`로 키워 registry의 8MB 문제를
    이력 쪽에서 되풀이한다. 원문은 `evidence_id + sha256`으로 고정되므로 Pinecone에서
    되짚을 수 있고, 승인 게이트도 그 해시로 변경을 판정한다.
    """
    evidence = record.get("evidence") or {}
    summary = {k: record.get(k) for k in
               ("id", "topic", "kind", "key", "value", "effective_from", "effective_to",
                "status", "citation", "quote", "note", "review_note",
                "created_by", "approved_by", "approved_at", "updated_at", "origin")}
    summary["evidence"] = {k: evidence.get(k) for k in
                           ("id", "sha256", "source_type", "title", "url", "official_url",
                            "date", "retrieved_at")}
    return summary


def evidence_snapshot(raw):
    if raw.get("namespace") != "laborlaw-v2":
        raise EvidenceError("법적 근거는 laborlaw-v2에서 조회해야 합니다")
    text = raw.get("text") or raw.get("chunk_text") or ""
    if not isinstance(text, str) or not text.strip() or len(text) > 50000:
        raise EvidenceError("조회된 근거 본문이 없거나 허용 크기를 초과합니다")
    result = {k: str(raw.get(k) or "") for k in
              ("id", "namespace", "source_type", "title", "url", "official_url", "date")}
    if not result["id"]:
        raise EvidenceError("Pinecone 문서 ID가 없습니다")
    result["text"] = text
    result["sha256"] = fingerprint(result)
    result["retrieved_at"] = now()
    return result


def official_evidence(evidence):
    if evidence.get("source_type") not in SOURCE_TYPES:
        raise EvidenceError("법령·판례·행정해석·고시 원문만 승인 근거로 사용할 수 있습니다")
    url = urlparse(evidence.get("official_url") or evidence.get("url", ""))
    host = (url.hostname or "").lower()
    if url.scheme != "https" or url.username or url.password or not any(
        host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS
    ):
        raise EvidenceError("Pinecone 메타데이터에 공식 원문 HTTPS 주소가 필요합니다")


def checked_proposal(payload, evidence):
    if not isinstance(payload, dict) or set(payload) - PROPOSAL_FIELDS:
        raise RuleError("허용되지 않은 입력 필드입니다")
    if not isinstance(payload.get("topic"), str) or payload.get("topic") not in topics():
        raise RuleError("알 수 없는 계산 유형입니다")
    if not isinstance(payload.get("kind"), str) or payload.get("kind") not in {"parameter", "legal_review"}:
        raise RuleError("기준 변경 또는 법률 검토 유형을 선택하세요")
    for name, limit in (("quote", 10000), ("citation", 500), ("note", 2000)):
        if not isinstance(payload.get(name, ""), str) or len(payload.get(name, "")) > limit:
            raise RuleError(f"{name} 길이/형식을 확인하세요")
    quote = payload.get("quote", "").strip()
    if quote and quote not in evidence["text"]:
        raise RuleError("인용구절이 Pinecone 원문에 존재하지 않습니다")
    if payload["kind"] == "parameter":
        try:
            validate_value(payload.get("key"), payload.get("value"))
            start = iso_date(payload.get("effective_from"))
            end = iso_date(payload["effective_to"]) if payload.get("effective_to") else None
            if end and end <= start:
                raise ValueError("종료일은 시행일 이후여야 합니다(종료일 제외)")
        except (TypeError, ValueError) as exc:
            raise RuleError(str(exc)) from exc
        if payload["topic"] not in PARAMETERS[payload["key"]]["topics"]:
            raise RuleError("선택한 계산기와 기준 키가 연결되지 않습니다")
        if len(quote) < 8 or not payload.get("citation", "").strip():
            raise RuleError("정확한 인용구절(8자 이상)과 조문·고시 번호가 필요합니다")
    elif payload.get("key") or payload.get("value") is not None:
        raise RuleError("법률 검토 후보에는 실행할 기준 값을 지정할 수 없습니다")
    result = {k: deepcopy(payload.get(k)) for k in PROPOSAL_FIELDS}
    for name in ("quote", "citation", "note", "key"):
        result[name] = payload.get(name, "")
    return result


class LegalUpdateService:
    def __init__(self, store, evidence):
        self.store = store
        self.evidence = evidence

    def _load(self, expected):
        revision, document = self.store.load()
        if type(expected) is not int or expected != revision:
            raise Conflict("다른 변경이 저장되었습니다. 새로고침 후 다시 검토하세요")
        return revision, document

    def _fetch(self, vector_id):
        if not isinstance(vector_id, str) or not vector_id.strip() or len(vector_id) > 512:
            raise EvidenceError("유효한 Pinecone 문서 ID가 필요합니다")
        return evidence_snapshot(self.evidence.fetch(vector_id))

    @staticmethod
    def _find(document, record_id):
        for record in document["records"]:
            if record["id"] == record_id:
                return record
        raise RuleError("변경 후보를 찾을 수 없습니다")

    def create(self, payload, expected_revision, actor):
        revision, document = self._load(expected_revision)
        evidence = self._fetch(payload.get("evidence_id"))
        values = checked_proposal(payload, evidence)
        record = dict(values, id=str(uuid4()), status="pending", evidence=evidence,
                      created_at=now(), updated_at=now(), created_by=actor, origin="manual")
        document["records"].append(record)
        self.store.save(revision, document, actor, {"type": "create", "id": record["id"]},
                        {"records": [event_record(record)]})
        return record

    def edit(self, record_id, payload, expected_revision, actor):
        revision, document = self._load(expected_revision)
        record = self._find(document, record_id)
        if record["status"] != "pending":
            raise RuleError("검토 대기 후보만 수정할 수 있습니다. 새 버전으로 등록하세요")
        evidence = self._fetch(payload.get("evidence_id"))
        values = checked_proposal(payload, evidence)
        record.update(values, evidence=evidence, updated_at=now())
        self.store.save(revision, document, actor, {"type": "edit", "id": record_id},
                        {"records": [event_record(record)]})
        return record

    def transition(self, record_id, action, expected_revision, actor, note):
        revision, document = self._load(expected_revision)
        record = self._find(document, record_id)
        if not isinstance(note, str) or not 4 <= len(note.strip()) <= 2000:
            raise RuleError("검토/변경 사유를 4~2000자로 입력하세요")
        transitions = {"approve": ("pending", "approved"), "reject": ("pending", "rejected"),
                       "reviewed": ("pending", "reviewed"), "revoke": ("approved", "revoked")}
        if action not in transitions or record["status"] != transitions[action][0]:
            raise RuleError("현재 상태에서 허용되지 않는 처리입니다")
        if action == "approve":
            if record["kind"] != "parameter":
                raise RuleError("산식·자격 변경은 코드 수정과 회귀검증이 필요합니다")
            fresh = self._fetch(record["evidence_id"])
            if fresh["sha256"] != record["evidence"]["sha256"]:
                raise EvidenceError("등록 이후 근거가 변경되었습니다. 후보를 수정해 다시 검토하세요")
            official_evidence(fresh)
            checked_proposal({k: record.get(k) for k in PROPOSAL_FIELDS}, fresh)
            for other in document["records"]:
                if other["status"] == "approved" and other.get("key") == record["key"]:
                    if ((not other.get("effective_to") or record["effective_from"] < other["effective_to"])
                            and (not record.get("effective_to") or other["effective_from"] < record["effective_to"])):
                        raise RuleError("승인된 기준의 시행기간과 중복됩니다. 기존 버전을 확인하세요")
            record["approved_at"] = now()
            record["approved_by"] = actor
        if action == "reviewed" and record["kind"] != "legal_review":
            raise RuleError("수치 기준은 승인 또는 반려로 처리하세요")
        record.update(status=transitions[action][1], review_note=note.strip(), updated_at=now())
        self.store.save(revision, document, actor,
                        {"type": action, "id": record_id, "note": note.strip()},
                        {"records": [event_record(record)]})
        return record

    def scan(self, topic, actor):
        if topic not in topics():
            raise RuleError("알 수 없는 계산 유형입니다")
        query = f"{topics()[topic]} 법령 개정 시행일 고시 판례 행정해석 {datetime.now(timezone.utc).year}"
        # Search happens once, before the short CAS retry loop; no duplicate network cost.
        try:
            search_result = self.evidence.search(query)
            hits = [evidence_snapshot(hit) for hit in search_result]
            status = ("partial" if getattr(search_result, "partial", False)
                      else "completed" if hits else "empty")
        except Exception:
            hits, status = [], "failed"
        scan = {"id": str(uuid4()), "topic": topic, "query": query, "status": status,
                "searched_at": now(), "hit_count": len(hits), "new_count": 0}
        for attempt in range(3):
            revision, document = self.store.load()
            seen = {r.get("discovery_key") for r in document["records"]}
            fresh_keys = set()
            scan["new_count"] = 0
            for evidence in hits:
                discovery_key = fingerprint([topic, evidence["id"], evidence["sha256"]])
                if discovery_key in seen:
                    continue
                seen.add(discovery_key)
                fresh_keys.add(discovery_key)
                document["records"].append({
                    "id": str(uuid4()), "topic": topic, "kind": "legal_review", "key": "", "value": None,
                    "effective_from": None, "effective_to": None, "evidence_id": evidence["id"],
                    "quote": "", "citation": "", "note": "자동 검색 후보: 실제 개정 여부와 적용범위 검토 필요",
                    "evidence": evidence, "status": "pending", "origin": "scan",
                    "discovery_key": discovery_key, "created_at": now(), "updated_at": now(), "created_by": actor,
                })
                scan["new_count"] += 1
            document["scans"] = (document.get("scans", []) + [scan])[-200:]
            try:
                self.store.save(revision, document, actor, {"type": "scan", **scan},
                                {"records": [event_record(r) for r in document["records"]
                                             if r.get("discovery_key") in fresh_keys]})
                return scan
            except Conflict:
                if attempt == 2:
                    raise
