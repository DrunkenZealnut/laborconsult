"""Persistent storage and read-only Pinecone evidence adapters."""
import json
import os

from app.core.legal_updates import Conflict, EvidenceError, RuleError


class EvidenceSearchResult(list):
    """검색 결과와 공식 원문 보조 조회의 완전성을 함께 전달한다."""
    def __init__(self, values=(), *, partial=False):
        super().__init__(values)
        self.partial = partial


class SupabaseRuleStore:
    def __init__(self, client):
        if client is None:
            raise RuleError("법률 기준 저장소가 설정되지 않았습니다")
        # SUPABASE_SCHEMA를 일부러 무시한다 — `supabase_legal_rules.sql`이 두 테이블과
        # 저장 RPC를 `laborconsult.`로 못박아 만들므로, 접속 스키마가 무엇이든 여기가
        # 유일한 소재지다. 환경변수를 따르면 존재하지 않는 스키마를 가리키거나
        # (공유 프로젝트에서) 남의 동명 테이블에 닿는다.
        self.db = client.schema("laborconsult")

    def load(self):
        # 한 상담 턴은 registry를 1회만 읽는다 — 계산기 경로(facade)와 사실 블록
        # (`pipeline._build_approved_facts`)은 `calc_result` 유무로 갈리는 배타 분기다.
        # 캐시를 두면 관리자 쓰기 직전 읽기가 낡을 위험만 생기므로 두지 않는다.
        rows = self.db.table("legal_rule_registry").select("revision,document").eq("id", 1).execute().data
        if not rows:
            raise RuleError("법률 기준 스키마를 먼저 적용하세요")
        return rows[0]["revision"], rows[0]["document"]

    def save(self, revision, document, actor, action, payload):
        if len(json.dumps(document, ensure_ascii=False, allow_nan=False).encode()) > 8_000_000:
            raise RuleError("법률 기준 저장 한도(8MB)에 도달했습니다. 후보 정리/보관이 필요합니다")
        try:
            result = self.db.rpc("legal_rules_save", {
                "expected_revision": revision, "new_document": document,
                "event_actor": actor, "event_action": action, "event_payload": payload,
            }).execute()
        except Exception as exc:
            if getattr(exc, "code", None) == "40001" or "LEGAL_RULE_REVISION_CONFLICT" in str(exc):
                raise Conflict("다른 변경이 저장되었습니다. 새로고침 후 다시 검토하세요") from exc
            raise RuleError("법률 기준 저장에 실패했습니다") from exc
        return result.data

    def events(self, limit=100):
        return self.db.table("legal_rule_events").select(
            "revision,actor,action,created_at"
        ).order("revision", desc=True).limit(min(limit, 100)).execute().data


class PineconeEvidence:
    """No RAG/counsel fallback; fetched metadata always comes from laborlaw-v2."""
    def __init__(self, index, openai_client, embed_model="text-embedding-3-small"):
        self.index = index
        self.openai = openai_client
        self.embed_model = embed_model

    @staticmethod
    def _document(vector_id, metadata):
        return {"id": vector_id, "namespace": "laborlaw-v2",
                **{k: metadata.get(k, "") for k in
                   ("source_type", "title", "url", "official_url", "date")},
                "text": metadata.get("chunk_text") or metadata.get("text") or ""}

    def fetch(self, vector_id):
        if self.index is None:
            raise EvidenceError("Pinecone 연결이 필요합니다")
        try:
            response = self.index.fetch(ids=[vector_id], namespace="laborlaw-v2", timeout=15)
            vectors = response.vectors if hasattr(response, "vectors") else response["vectors"]
            vector = vectors.get(vector_id)
            if vector is None:
                raise EvidenceError("Pinecone에서 해당 근거를 찾지 못했습니다")
            meta = vector.metadata if hasattr(vector, "metadata") else vector.get("metadata", {})
            return self._document(vector_id, meta)
        except EvidenceError:
            raise
        except Exception as exc:
            raise EvidenceError("Pinecone 근거 재조회에 실패했습니다") from exc

    _TYPES = ["law", "statute", "regulation", "interpretation", "precedent"]

    def _query(self, embedding, top_k, extra_filter=None):
        response = self.index.query(
            namespace="laborlaw-v2", vector=embedding, top_k=top_k, include_metadata=True,
            filter={"source_type": {"$in": self._TYPES}, **(extra_filter or {})},
            timeout=15,
        )
        matches = response.matches if hasattr(response, "matches") else response["matches"]
        return [self._document(m.id, m.metadata) if hasattr(m, "id")
                else self._document(m["id"], m.get("metadata", {})) for m in matches]

    def search(self, query):
        """일반 검색 + **공식 원문 전용 검색**을 합친다.

        승인 게이트를 통과할 수 있는 것은 `official_url` 이 공식 호스트인 문서뿐인데,
        그 수가 코퍼스 전체에 비해 압도적으로 적다(2026-09-18 기준 17벡터 대 수만 벡터).
        일반 검색 한 번으로는 top_k 8 안에 한 건도 못 들어 **자동 검색이 승인 가능한
        후보를 영영 만들지 못했다**(실측: 24건 전부 거절). 공식 전용 조회를 따로 돌려
        앞에 붙인다 — 조용한 실패를 막는 구조적 장치이므로 지우지 말 것.
        """
        if self.index is None:
            raise EvidenceError("Pinecone 연결이 필요합니다")
        embedding = self.openai.with_options(timeout=10, max_retries=0).embeddings.create(
            model=self.embed_model, input=query).data[0].embedding
        general = self._query(embedding, 8)
        # 공식 전용 조회는 **뒤에** 둔다 — 실패해도 일반 검색 결과는 살린다.
        partial = False
        try:
            official = self._query(embedding, 4, {"official": True})
        except Exception:
            official = []
            partial = True
        seen, merged = set(), []
        for doc in official + general:
            if doc["id"] in seen:
                continue
            seen.add(doc["id"])
            merged.append(doc)
        return EvidenceSearchResult(merged, partial=partial)


def rules_enabled():
    return os.getenv("LEGAL_RULES_ENABLED", "false").strip().lower() == "true"


# 클라이언트 생성은 httpx 세션·인증 헤더 구성을 매번 새로 하므로 요청마다 만들지 않는다.
# 자격증명이 바뀌면 옛 클라이언트를 남기지 않도록 통째로 교체한다.
_clients: dict = {}


def configured_store():
    from app.core.storage import make_supabase_client
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise RuleError("법률 기준 관리용 서버 service-role 키가 설정되지 않았습니다")
    cache_key = (os.getenv("SUPABASE_URL") or "", key, os.getenv("SUPABASE_SCHEMA") or "")
    client = _clients.get(cache_key)
    if client is None:
        client = make_supabase_client(key=key)
        if client is not None:
            _clients.clear()
            _clients[cache_key] = client
    return SupabaseRuleStore(client)
