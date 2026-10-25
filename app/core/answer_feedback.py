"""Private, session-bound feedback; no conversation text is duplicated."""
from __future__ import annotations

import hmac
import time
import uuid
import jwt

REASONS = frozenset({"legal_calculation_error", "unclear", "missing_answer", "other"})
TTL = 14 * 24 * 3600


def issue_token(secret, conversation_id, session_id, versions, *, now=None):
    if not secret or not session_id:
        raise ValueError("feedback signing unavailable")
    conversation_id = str(uuid.UUID(conversation_id))
    at = int(time.time() if now is None else now)
    return jwt.encode({"aud": "answer-feedback", "sub": conversation_id,
                       "sid": session_id, "versions": versions,
                       "iat": at, "exp": at + TTL}, secret, algorithm="HS256")


def verify_token(secret, token, session_id, *, now=None):
    try:
        if not secret or not isinstance(token, str) or len(token) > 4096:
            raise ValueError("invalid feedback token")
        claims = jwt.decode(token, secret, algorithms=["HS256"], audience="answer-feedback",
                            options={"verify_exp": False, "verify_iat": False,
                                     "require": ["sub", "sid", "versions", "exp", "iat"]})
        at = int(time.time() if now is None else now)
        uuid.UUID(claims["sub"])
        if not hmac.compare_digest(claims["sid"], session_id):
            raise ValueError("wrong session")
        if not claims["iat"] <= at < claims["exp"] or claims["exp"] - claims["iat"] > TTL:
            raise ValueError("expired feedback token")
        if not isinstance(claims["versions"], dict):
            raise ValueError("invalid versions")
        return claims
    except (jwt.InvalidTokenError, TypeError, KeyError, ValueError) as exc:
        raise ValueError("invalid feedback token") from exc


def validate_submission(kind, positive, reason):
    if kind == "exposure" and positive is None and reason is None:
        return
    if kind != "vote" or type(positive) is not bool:
        raise ValueError("invalid feedback")
    if (positive and reason is not None) or (not positive and reason not in REASONS):
        raise ValueError("invalid feedback reason")


def submit(client, secret, token, session_id, kind, positive, reason, *, now=None):
    claims = verify_token(secret, token, session_id, now=now)
    validate_submission(kind, positive, reason)
    result = client.schema("laborconsult").rpc("qa_feedback_record", {
        "p_conversation_id": claims["sub"], "p_session_id": session_id,
        "p_kind": kind, "p_positive": positive, "p_reason": reason,
        "p_versions": claims["versions"],
    }).execute()
    return result.data
