"""Feedback public endpoint and protected aggregate reporting."""
import logging
import os
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from app.core.answer_feedback import submit

logger=logging.getLogger(__name__)

class FeedbackRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token:str=Field(max_length=4096,min_length=1)
    session_id:str=Field(max_length=200,min_length=1)
    kind:Literal['exposure','vote']
    positive:StrictBool|None=None
    reason:Literal['legal_calculation_error','unclear','missing_answer','other']|None=None

def build_router(require_admin,config_factory,secret,rate_limit):
    router=APIRouter()
    @router.post('/api/answer-feedback')
    def feedback(body:FeedbackRequest,request:Request):
        if os.getenv('QA_QUALITY_ENABLED','').lower()!='true':
            raise HTTPException(503,'현재 의견을 저장할 수 없습니다.')
        wait=rate_limit(request)
        if wait:
            raise HTTPException(429,'잠시 후 다시 시도해주세요.',headers={'Retry-After':str(wait)})
        config=config_factory()
        if not config.supabase:
            raise HTTPException(503,'현재 의견을 저장할 수 없습니다.')
        try:
            return submit(config.supabase,secret,body.token,body.session_id,body.kind,body.positive,body.reason)
        except ValueError:
            raise HTTPException(400,'해당 답변의 의견을 확인할 수 없습니다.') from None
        except Exception as exc:
            message=str(exc)
            if 'FEEDBACK_RATE' in message:
                raise HTTPException(429,'잠시 후 다시 시도해주세요.',headers={'Retry-After':'10'}) from None
            if any(code in message for code in ['FEEDBACK_OWNER','FEEDBACK_INVALID','FEEDBACK_NOT_EXPOSED','FEEDBACK_VERSION']):
                raise HTTPException(400,'해당 답변의 의견을 확인할 수 없습니다.') from None
            logger.warning('Feedback write failed: %s',type(exc).__name__)
            raise HTTPException(503,'현재 의견을 저장할 수 없습니다.') from None

    @router.get('/api/admin/qa-quality')
    def quality(days:int=Query(default=30,ge=1,le=365),admin=Depends(require_admin)):
        config=config_factory()
        if not config.supabase:
            raise HTTPException(503,'집계를 불러올 수 없습니다.')
        try:
            return config.supabase.schema('laborconsult').rpc('qa_quality_summary',{'p_days':days}).execute().data
        except Exception as exc:
            logger.warning('QA summary failed: %s',type(exc).__name__)
            raise HTTPException(503,'집계를 불러올 수 없습니다.') from None
    return router
