"""Admin-only routes. Dependency factories keep credentials out of browser responses."""
from contextlib import contextmanager
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.legal_updates import Conflict, RuleError, current_parameters, topics
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
                    "topics": topics(), "enabled": rules_enabled(),
                    "current": current_parameters(document)}

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

    @router.get("/documents")
    def documents(admin=Depends(require_admin)):
        """승인 근거로 쓸 수 있는 공식 원문 전량. 벡터 ID 손입력을 대체한다.

        실패해도 관리 화면은 ID 직접 입력으로 계속 쓸 수 있어야 하므로, 여기서만
        예외를 목록 없는 정상 응답으로 바꾼다(422로 올리면 화면이 멈춘다).
        """
        try:
            documents = service_factory().evidence.catalog()
        except Exception as exc:
            logging.getLogger(__name__).warning("공식 원문 목록 조회 실패: %s", exc)
            return {"documents": [],
                    "detail": "공식 원문 목록을 불러오지 못했습니다. 문서 ID를 직접 입력하세요."}
        # 조회 실패 / 적재 0건 / 상한 절단은 화면에서 구분돼야 한다. 셋 다 "빈 드롭다운"으로
        # 보이면 관리자가 없는 원인을 찾는다.
        detail = None
        if getattr(documents, "truncated", False):
            logging.getLogger(__name__).warning("공식 원문 목록이 상한에서 잘렸습니다: %d건", len(documents))
            detail = f"공식 원문이 많아 {len(documents)}건만 표시합니다. 나머지는 문서 ID를 직접 입력하세요."
        elif not documents:
            detail = "적재된 공식 원문이 없습니다. fetch_official_rules → pinecone_upload_official_rules 를 먼저 실행하세요."
        return {"documents": list(documents), **({"detail": detail} if detail else {})}

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
