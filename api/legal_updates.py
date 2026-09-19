"""Admin-only routes. Dependency factories keep credentials out of browser responses."""
from contextlib import contextmanager
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.legal_updates import Conflict, RuleError, topics
from app.core.legal_rule_store import rules_enabled
from wage_calculator.legal_rules import PARAMETERS


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=0)
    payload: dict


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=0)
    note: str = Field(min_length=4, max_length=2000)


class Scan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(max_length=80)


@contextmanager
def api_errors():
    try:
        yield
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuleError as exc:
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logging.getLogger(__name__).exception("법률 기준 관리 요청 실패")
        raise HTTPException(503, "법률 기준 서비스에 연결할 수 없습니다") from exc


def actor(admin):
    return "admin-session:" + str(admin.get("jti") or "shared")[:100]


def listing(document):
    """목록 응답에서 근거 **원문**을 뺀다.

    registry 상한이 8MB인데 후보마다 최대 50,000자의 Pinecone 원문이 들어 있어,
    그대로 내보내면 후보가 쌓일수록 서버리스 응답 한도를 넘어 관리 화면이 통째로
    멈춘다. 원문은 후보를 선택할 때 상세 엔드포인트로 한 건씩 가져온다.
    """
    records = []
    for record in document.get("records", []):
        evidence = dict(record.get("evidence") or {})
        evidence["text_length"] = len(evidence.pop("text", "") or "")
        records.append(dict(record, evidence=evidence))
    return {"records": records, "scans": document.get("scans", [])}


def build_legal_router(require_admin, service_factory):
    router = APIRouter(prefix="/api/admin/legal-rules", tags=["legal-rules"])

    @router.get("")
    def state(admin=Depends(require_admin)):
        with api_errors():
            revision, document = service_factory().store.load()
            return {"revision": revision, **listing(document), "parameters": PARAMETERS,
                    "topics": topics(), "enabled": rules_enabled()}

    @router.get("/candidates/{record_id}")
    def candidate(record_id: str, admin=Depends(require_admin)):
        """저장된 근거 원문까지 포함한 단건. 목록에서 뺀 text를 여기서 돌려준다."""
        with api_errors():
            service = service_factory()
            _, document = service.store.load()
            return {"record": service._find(document, record_id)}

    @router.get("/events")
    def events(admin=Depends(require_admin)):
        with api_errors():
            return {"events": service_factory().store.events()}

    @router.get("/evidence")
    def evidence(id: str = Query(min_length=1, max_length=512), admin=Depends(require_admin)):
        with api_errors():
            return {"evidence": service_factory()._fetch(id)}

    @router.post("/scan")
    def scan(body: Scan, admin=Depends(require_admin)):
        with api_errors():
            return service_factory().scan(body.topic, actor(admin))

    @router.post("/candidates")
    def create(body: Mutation, admin=Depends(require_admin)):
        with api_errors():
            return {"record": service_factory().create(body.payload, body.revision, actor(admin))}

    @router.put("/candidates/{record_id}")
    def edit(record_id: str, body: Mutation, admin=Depends(require_admin)):
        with api_errors():
            return {"record": service_factory().edit(record_id, body.payload, body.revision, actor(admin))}

    @router.post("/candidates/{record_id}/{action}")
    def transition(record_id: str, action: str, body: Decision, admin=Depends(require_admin)):
        with api_errors():
            return {"record": service_factory().transition(record_id, action, body.revision,
                                                          actor(admin), body.note)}

    return router
