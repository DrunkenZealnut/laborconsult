"""질문 쟁점에 해당하는 검증된 공식 근거를 검색 순위와 독립적으로 전달한다.

원문·작성 설명을 구분하고, 실제 렌더된 자료만 인용/출처 목록에 반환한다.
자료 추가는 JSON의 출처·판본·원문 해시 검토를 먼저 거쳐야 한다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parents[2] / 'data' / 'consultation_evidence'
_SOURCE_TYPES = {'law': 'law_article', 'precedent': 'precedent',
                 'regulation': 'regulation', 'interpretation': 'interpretation',
                 'official_guidance': 'interpretation'}


@dataclass
class EvidenceSelection:
    text: str = ''
    hits: list[dict] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def evidence_groups() -> tuple[dict, ...]:
    groups = []
    for path in sorted(DATA_DIR.glob('*.json')):
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
            for group in document['groups']:
                groups.append(dict(group, reviewed_at=document['as_of']))
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning('상담 근거 파일 로드 실패: %s', path.name, exc_info=True)
    return tuple(groups)


def _matches(group: dict, query: str) -> bool:
    patterns = group.get('patterns') or []
    return (any(re.search(pattern, query) for pattern in patterns)
            and all(re.search(pattern, query) for pattern in group.get('all_patterns', [])))


def _source_hit(source: dict, today: str) -> dict | None:
    """미래 판본·출처/원문 증거가 없는 자료는 전달하지 않는다."""
    effective = source.get('effective_date')
    if effective and (date.fromisoformat(effective).isoformat() > today):
        return None
    url = source.get('official_url', '')
    parsed = urlparse(url)
    provenance = source.get('provenance') or {}
    if (parsed.scheme != 'https' or not parsed.hostname
            or not source.get('content') or not source.get('title')
            or not source.get('id') or source.get('source_type') not in _SOURCE_TYPES
            or not re.fullmatch(r'[0-9a-f]{64}', provenance.get('sha256', ''))):
        return None
    if source.get('source_type') == 'official_guidance':
        if source.get('content_kind') != 'authored_summary' or not source.get('rights_basis'):
            return None
    return dict(source, source_type=_SOURCE_TYPES[source['source_type']],
                chunk_text=source['content'], url=url, origin='official_evidence')


def select_evidence(query: str, *, as_of: str | None = None,
                    max_chars: int = 12000, groups: tuple[dict, ...] | None = None) -> EvidenceSelection:
    """자료/그룹을 절단하지 않고 예산 안에서 선택한다. 생략한 자료는 인용하지 않는다."""
    today = as_of or datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    date.fromisoformat(today)
    result = EvidenceSelection()
    if not query or max_chars <= 0:
        return result
    seen = set()
    blocks = []
    for group in evidence_groups() if groups is None else groups:
        name = group.get('id', '')
        try:
            if not _matches(group, query):
                continue
            reviewed_at = group.get('reviewed_at', '')
            if not reviewed_at or date.fromisoformat(reviewed_at).isoformat() > today:
                result.omitted.append(name)
                continue
            sources = group.get('sources') or []
            hits = [_source_hit(source, today) for source in sources]
            # 적용 설명을 뒷받침하는 자료 중 하나라도 불완전하면 그룹 전체를 생략한다.
            if not hits or any(hit is None for hit in hits):
                result.omitted.append(name)
                continue
            unique = []
            pending = set(seen)
            for hit in hits:
                if hit['id'] not in pending:
                    unique.append(hit)
                    pending.add(hit['id'])
            parts = [f'[질문 쟁점의 공식 근거 — 확인 기준일 {reviewed_at}]',
                     '적용 설명(작성 요약): ' + group.get('guidance', '')]
            for hit in unique:
                kind = '공식 안내의 사실 요약(원문 인용 아님)' if hit.get('content_kind') == 'authored_summary' else '공식 원문'
                decision = ''
                if hit.get('case_no') and hit.get('date_kind') == 'decision_date':
                    decision = f"사건번호: {hit['case_no']} / 재판일: {hit['effective_date']}\n"
                parts.append(f"[{kind}] {hit['title']} / {hit.get('section', '')}\n"
                             f"출처: {hit['url']}\n{decision}{hit['chunk_text']}")
            block = '\n\n'.join(parts)
            candidate = '\n\n'.join(blocks + [block])
            # 생략 고지 공간을 미리 남긴다. 내용·기간의 중간 절단은 하지 않는다.
            if len(candidate) + 120 > max_chars:
                result.omitted.append(name)
                continue
            blocks.append(block)
            result.hits.extend(unique)
            result.groups.append(name)
            seen = pending
        except (ValueError, TypeError, KeyError, re.error):
            logger.warning('상담 근거 그룹 처리 실패: %s', name, exc_info=True)
            result.omitted.append(name)
    result.text = '\n\n'.join(blocks)
    if result.omitted and max_chars >= 120:
        result.text += '\n[일부 쟁점 근거는 판본·자료 검증 또는 길이 제한으로 생략되었습니다. 없는 근거를 추정하지 마세요.]'
    return result


_NAKED_CHANGE = re.compile(
    r'(?<![\d.,])\d+(?:[.,]\d+)*\s*(?:정도|가량|쯤|씩)?\s*'
    r'(?:적게|덜|삭감|감액|깎|많이|더\s*(?:받|주))')
_MONEY_CONTEXT = re.compile(r'급여|월급|연봉|시급|임금|일급|주급|금액')
_OTHER_MEASURE = re.compile(r'근로시간|근무시간|시간|근무일|일수|인원|거리|횟수')


def question_fact_notes(query: str) -> str:
    """금액 문맥의 단위 없는 변동량을 그대로 확인한다. 만원 등 단위를 생성하지 않는다."""
    if not _MONEY_CONTEXT.search(query or ''):
        return ''
    mentions = []
    for match in _NAKED_CHANGE.finditer(query):
        context = query[max(0, match.start() - 100):match.start()]
        money = list(_MONEY_CONTEXT.finditer(context))
        other = list(_OTHER_MEASURE.finditer(context))
        if not money or (other and other[-1].end() > money[-1].end()):
            continue
        mention = match.group(0).strip()
        if mention not in mentions:
            mentions.append(mention)
        if len(mentions) == 3:
            break
    if not mentions:
        return ''
    quoted = ', '.join(f'「{mention}」' for mention in mentions)
    return (f'[질문 사실 확인]\n{quoted}에는 통화 단위가 없습니다. 단위를 확인할 사항으로 적고, '
            '원·만원·퍼센트나 월급/연봉의 차액이라고 임의로 확정하지 마세요. 사용자 표현을 그대로 보존하세요.')
