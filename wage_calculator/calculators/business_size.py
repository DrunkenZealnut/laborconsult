"""
상시근로자 수 산정 계산기 (근로기준법 시행령 제7조의2)

법적 근거:
- 근로기준법 제11조 (적용 범위)
- 근로기준법 시행령 제7조의2 (상시 사용하는 근로자 수의 산정)

핵심 공식:
  상시근로자 수 = 법 적용 사유 발생일 전 1개월간 연인원 / 같은 기간 가동일수

포함: 통상·기간제·단시간·일용(출근일만)·교대(비번일 포함)·외국인·휴직자·결근자·징계자
제외: 휴직대체자, 해외현지법인, 파견근로자, 외부용역, 대표자/비근로자, 동거친족만 사업장의 친족

법 적용 기준 미달일수가 산정기간의 1/2 미만이면 법 적용 사업장으로 봄
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..base import BaseCalculatorResult
from ..constants import DEFAULT_NON_OPERATING_WEEKDAYS, LABOR_LAW_BY_SIZE
from ..models import BusinessSize, WorkerType, WorkerEntry, BusinessSizeInput

# 연인원 집계에서 항상 제외되는 WorkerType
_EXCLUDED_TYPES = {
    WorkerType.OVERSEAS_LOCAL,
    WorkerType.DISPATCHED,
    WorkerType.OUTSOURCED,
    WorkerType.OWNER,
}


@dataclass
class BusinessSizeResult(BaseCalculatorResult):
    """상시근로자 수 산정 결과"""
    regular_worker_count: float = 0.0
    business_size: BusinessSize = BusinessSize.UNDER_5
    calculation_period_start: str = ""
    calculation_period_end: str = ""
    operating_days: int = 0
    total_headcount: int = 0
    daily_counts: dict = field(default_factory=dict)
    included_workers: list = field(default_factory=list)
    excluded_workers: list = field(default_factory=list)
    below_threshold_days: int = 0
    above_threshold_days: int = 0
    is_law_applicable: bool = False
    multi_threshold: dict = field(default_factory=dict)
    applicable_laws: list = field(default_factory=list)
    not_applicable_laws: list = field(default_factory=list)


def calc_business_size(bsi: BusinessSizeInput) -> BusinessSizeResult:
    """
    상시근로자 수 산정 (근로기준법 시행령 제7조의2)

    독립 함수: WageInput 없이 BusinessSizeInput만으로 동작.
    """
    warnings = []
    formulas = []
    legal = [
        "근로기준법 제11조 (적용 범위)",
        "근로기준법 시행령 제7조의2 (상시 사용하는 근로자 수의 산정)",
    ]

    # 입력 검증: event_date
    if not bsi.event_date:
        warnings.append("사유 발생일 미입력 — 오늘 날짜를 사용합니다")
        event_dt = date.today()
    else:
        event_dt = _parse_date(bsi.event_date)

    # 빈 근로자 목록 + 간편 입력도 없음
    if not bsi.workers and bsi.daily_headcount is None:
        return BusinessSizeResult(
            regular_worker_count=0.0,
            business_size=BusinessSize.UNDER_5,
            calculation_period_start="",
            calculation_period_end="",
            operating_days=0,
            total_headcount=0,
            daily_counts={},
            included_workers=[],
            excluded_workers=[],
            below_threshold_days=0,
            above_threshold_days=0,
            is_law_applicable=False,
            breakdown={"판정 결과": "근로자 없음 — 5인 미만"},
            formulas=["[상시근로자 수] 근로자 0명 → 5인 미만"],
            legal_basis=legal,
            warnings=["근로자 명단이 비어 있습니다"],
        )

    # 1. 산정기간 결정
    period_start, period_end = _calc_period(event_dt)

    # 2. 가동일수 집계
    non_op_dates = None
    if bsi.non_operating_days is not None:
        non_op_dates = [_parse_date(d) for d in bsi.non_operating_days]
    operating_dates, op_count = _calc_operating_days(period_start, period_end, non_op_dates)

    if op_count == 0:
        warnings.append("가동일수가 0일입니다 — 산정 불가")
        return BusinessSizeResult(
            regular_worker_count=0.0,
            business_size=BusinessSize.UNDER_5,
            calculation_period_start=period_start.isoformat(),
            calculation_period_end=period_end.isoformat(),
            operating_days=0,
            total_headcount=0,
            daily_counts={},
            included_workers=[],
            excluded_workers=[],
            below_threshold_days=0,
            above_threshold_days=0,
            is_law_applicable=False,
            breakdown={"판정 결과": "가동일수 0일 — 산정 불가"},
            formulas=[],
            legal_basis=legal,
            warnings=warnings,
        )

    # 3. 일별 근로자 수 집계
    operating_set = set(operating_dates)
    if bsi.daily_headcount is not None:
        # 간편 입력 모드: daily_headcount 직접 사용
        daily_counts = {}
        for d_str, count in bsi.daily_headcount.items():
            d = _parse_date(d_str)
            if period_start <= d <= period_end and d in operating_set:
                daily_counts[d.isoformat()] = count
        if not daily_counts:
            warnings.append("간편 입력 데이터 중 산정기간 내 가동일이 없습니다")
            daily_counts = {d.isoformat(): 0 for d in operating_dates}
        included, excluded = [], []
        op_count = len(daily_counts)
    else:
        # 기존 로직: workers 기반 일별 집계
        daily_counts, included, excluded = _count_daily_workers(
            operating_dates, bsi.workers, bsi.is_family_only_business, warnings,
        )

    # 4. 연인원 ÷ 가동일수
    total_headcount = sum(daily_counts.values())
    regular_count = round(total_headcount / op_count, 2)

    # 5. BusinessSize 결정
    biz_size = _determine_size(regular_count)

    # 6. 미달일수 1/2 판정 (5인 기준)
    below, above, is_applicable = _check_threshold(daily_counts, op_count)

    # 7. 다중 threshold 판정
    multi_threshold = _check_multi_threshold(daily_counts, op_count)

    # 8. 규모별 적용법률
    laws = _get_applicable_laws(regular_count)

    # 계산식
    formulas.append(
        f"[상시근로자 수] 연인원({total_headcount}명) / 가동일수({op_count}일) = {regular_count}명"
    )
    formulas.append(
        f"[판정] {regular_count}명 {'<' if regular_count < 5 else '>='} 5인 → {biz_size.value}"
    )
    formulas.append(
        f"[법 적용] 5인 미만 일수({below}일) {'<' if is_applicable else '>='} "
        f"가동일수의 1/2({op_count / 2:.1f}일) → {'적용' if is_applicable else '미적용'}"
    )

    # 포함/제외 요약
    included_summary = _summarize_workers(included)
    excluded_summary = _summarize_workers(excluded)

    period_days = (period_end - period_start).days + 1
    breakdown = {
        "산정기간": f"{period_start.isoformat()} ~ {period_end.isoformat()} ({period_days}일)",
        "가동일수": f"{op_count}일",
        "연인원 합계": f"{total_headcount}명",
        "상시근로자 수": f"{total_headcount} / {op_count} = {regular_count}명",
        "판정 결과": f"{biz_size.value}",
        "5인 미만 일수": f"{below}일 / {op_count}일 ({below / op_count * 100:.1f}%)",
        "법 적용 여부": f"{'적용' if is_applicable else '미적용'} "
                      f"(미달일수 {'<' if is_applicable else '>='} 산정기간의 1/2)",
        "규모별 기준 판정": {
            f"{t}인 기준": {
                "미달일수": f"{b}일",
                "충족일수": f"{a}일",
                "법 적용": "적용" if app else "미적용",
            }
            for t, (b, a, app) in multi_threshold.items()
        },
        "적용 노동법": laws["적용"],
        "미적용 노동법": laws["미적용"],
        "포함 근로자": included_summary,
        "제외 근로자": excluded_summary,
    }

    return BusinessSizeResult(
        regular_worker_count=regular_count,
        business_size=biz_size,
        calculation_period_start=period_start.isoformat(),
        calculation_period_end=period_end.isoformat(),
        operating_days=op_count,
        total_headcount=total_headcount,
        daily_counts=daily_counts,
        included_workers=included,
        excluded_workers=excluded,
        below_threshold_days=below,
        above_threshold_days=above,
        is_law_applicable=is_applicable,
        multi_threshold=multi_threshold,
        applicable_laws=laws["적용"],
        not_applicable_laws=laws["미적용"],
        breakdown=breakdown,
        formulas=formulas,
        legal_basis=legal,
        warnings=warnings,
    )


# ── 내부 함수 ──────────────────────────────────────────────────────────────


def _parse_date(s: str) -> date:
    """YYYY-MM-DD 문자열 → date"""
    parts = s.strip().replace(".", "-").split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def _calc_period(event_date: date) -> tuple[date, date]:
    """
    산정기간 결정: event_date 전 역일상 1개월

    period_end = event_date - 1일
    period_start = event_date에서 1개월 전 같은 일 (월말 보정)
    """
    period_end = event_date - timedelta(days=1)

    # 1개월 전 계산 (월말 보정)
    year = event_date.year
    month = event_date.month - 1
    if month < 1:
        month = 12
        year -= 1
    day = event_date.day
    max_day = calendar.monthrange(year, month)[1]
    if day > max_day:
        day = max_day
    period_start = date(year, month, day)

    return period_start, period_end


def _calc_operating_days(
    period_start: date,
    period_end: date,
    non_operating_days: list[date] | None,
) -> tuple[list[date], int]:
    """가동일수 집계"""
    operating = []
    current = period_start
    while current <= period_end:
        if non_operating_days is not None:
            # 명시적 비가동일 제외
            if current not in non_operating_days:
                operating.append(current)
        else:
            # 기본: 토·일 제외
            if current.weekday() not in DEFAULT_NON_OPERATING_WEEKDAYS:
                operating.append(current)
        current += timedelta(days=1)

    return operating, len(operating)


def _should_include_worker(
    worker: WorkerEntry,
    target_date: date,
    is_family_only: bool,
    has_non_family_worker: bool,
) -> tuple[bool, str]:
    """특정 날짜에 해당 근로자를 연인원에 포함할지 판별"""
    # 1. start_date 누락
    if not worker.start_date:
        return False, "근로계약 효력발생일 미입력"

    start = _parse_date(worker.start_date)

    # 근로계약 효력기간 확인
    if target_date < start:
        return False, "근로계약 효력 발생 전"

    if worker.end_date:
        end = _parse_date(worker.end_date)
        if target_date > end:
            return False, "퇴직일 이후"

    # 2. 휴직대체자 → 제외
    if worker.is_leave_replacement:
        return False, "휴직대체자 (중복 산정 방지)"

    # 3. 제외 유형: 해외현지법인, 파견, 용역, 대표자
    if worker.worker_type == WorkerType.OVERSEAS_LOCAL:
        return False, "해외 현지법인 소속 (별개 법인격)"
    if worker.worker_type == WorkerType.DISPATCHED:
        return False, "파견근로자 (파견사업주 소속, 파견법 제2조)"
    if worker.worker_type == WorkerType.OUTSOURCED:
        return False, "외부용역 (도급업체 소속, 고용관계 없음)"
    if worker.worker_type == WorkerType.OWNER:
        return False, "대표자/비근로자 (근로기준법상 근로자 아님)"

    # 4. 동거친족만 사업장 + 가족근로자
    if is_family_only and worker.worker_type == WorkerType.FAMILY and not has_non_family_worker:
        return False, "동거친족만 사업장의 친족 (근기법 미적용)"

    # 5. 특정요일 출근자 → 해당 요일에만 포함
    if worker.specific_work_days is not None:
        if target_date.weekday() not in worker.specific_work_days:
            return False, "특정요일 출근자 — 해당 요일 아님"

    # 6. 일용직 → actual_work_dates 기반 판별
    if worker.worker_type == WorkerType.DAILY:
        if worker.actual_work_dates is not None:
            if target_date.isoformat() not in worker.actual_work_dates:
                return False, "일용직 — 해당일 미출근"
            return True, "일용직 — 출근일"
        # actual_work_dates 미입력 시: 매일 포함 (하위호환)
        return True, "일용직 — 출근일 정보 미입력 (매일 포함 처리)"

    # 7. 나머지 (통상/기간제/단시간/교대/외국인/가족/휴직자/결근자 등) → 포함
    if worker.is_on_leave:
        return True, "고용관계 유지 (휴직/휴가/결근/징계)"
    if worker.worker_type == WorkerType.SHIFT:
        return True, "사회통념상 상시근무 (교대근무, 비번일 포함)"
    if worker.worker_type == WorkerType.FOREIGN:
        return True, "고용관계 기준 (국적 불문)"
    if worker.worker_type == WorkerType.FAMILY:
        return True, "가족근로자 (지휘감독 하 임금 근로)"

    return True, "고용관계 유지"


def _count_daily_workers(
    operating_dates: list[date],
    workers: list[WorkerEntry],
    is_family_only: bool,
    warnings: list[str],
) -> tuple[dict, list, list]:
    """일별 근로자 수 집계"""
    # 비가족 근로자 존재 여부 판별 (제외 유형 필터)
    has_non_family = any(
        w.worker_type != WorkerType.FAMILY
        for w in workers
        if not w.is_leave_replacement and w.worker_type not in _EXCLUDED_TYPES
    )

    # 근로자별 산입일수 추적
    worker_days: dict[int, dict] = {}  # worker index → {"days": count, "reason": str}
    excluded_set: dict[int, str] = {}

    daily_counts: dict[str, int] = {}

    for d in operating_dates:
        day_str = d.isoformat()
        count = 0
        for i, w in enumerate(workers):
            included, reason = _should_include_worker(w, d, is_family_only, has_non_family)
            if included:
                count += 1
                if i not in worker_days:
                    worker_days[i] = {"days": 0, "reason": reason}
                worker_days[i]["days"] += 1
            else:
                if i not in excluded_set and i not in worker_days:
                    # 기록: 한 번도 포함되지 않은 근로자만 제외 목록에
                    excluded_set[i] = reason

        daily_counts[day_str] = count

    # start_date 누락 경고
    for i, w in enumerate(workers):
        if not w.start_date:
            warnings.append(
                f"근로자 '{w.name or f'#{i+1}'}': 효력발생일 미입력으로 제외"
            )

    # 일용직 actual_work_dates 미입력 경고
    for i, w in enumerate(workers):
        if w.worker_type == WorkerType.DAILY and w.actual_work_dates is None and w.start_date:
            warnings.append(
                f"근로자 '{w.name or f'#{i+1}'}': 일용직 실제 출근일(actual_work_dates) "
                f"미입력으로 매 가동일 포함 처리"
            )

    # 포함 근로자 내역
    included_list = []
    for i, info in worker_days.items():
        w = workers[i]
        included_list.append({
            "name": w.name or f"근로자#{i+1}",
            "worker_type": w.worker_type.value,
            "days_counted": info["days"],
            "reason": info["reason"],
        })

    # 제외 근로자 내역 (전체 기간 동안 한 번도 포함 안 된 근로자)
    excluded_list = []
    for i, reason in excluded_set.items():
        w = workers[i]
        excluded_list.append({
            "name": w.name or f"근로자#{i+1}",
            "worker_type": w.worker_type.value,
            "reason": reason,
        })

    return daily_counts, included_list, excluded_list


def _determine_size(regular_count: float) -> BusinessSize:
    """상시근로자 수 → BusinessSize enum 결정"""
    if regular_count < 5:
        return BusinessSize.UNDER_5
    if regular_count < 10:
        return BusinessSize.OVER_5
    if regular_count < 30:
        return BusinessSize.OVER_10
    if regular_count < 300:
        return BusinessSize.OVER_30
    return BusinessSize.OVER_300


def _check_threshold(
    daily_counts: dict[str, int],
    operating_days: int,
    threshold: int = 5,
) -> tuple[int, int, bool]:
    """
    법 적용 기준 미달일수 1/2 판정 (시행령 제7조의2 제2항 제1호)

    미달일수 < (가동일수 / 2) → 법 적용 (True)
    """
    below = sum(1 for c in daily_counts.values() if c < threshold)
    above = operating_days - below
    is_applicable = below < (operating_days / 2)
    return below, above, is_applicable


def _check_multi_threshold(
    daily_counts: dict[str, int],
    operating_days: int,
) -> dict[int, tuple[int, int, bool]]:
    """5인/10인/30인 기준 각각에 대한 미달일수 1/2 판정"""
    return {
        t: _check_threshold(daily_counts, operating_days, t)
        for t in (5, 10, 30)
    }


def _get_applicable_laws(regular_count: float) -> dict[str, list[str]]:
    """상시근로자 수 기반 적용/미적용 노동법 안내"""
    applicable = []
    not_applicable = []

    for threshold in sorted(LABOR_LAW_BY_SIZE.keys()):
        laws = LABOR_LAW_BY_SIZE[threshold]
        if regular_count >= threshold:
            applicable.extend(laws.get("적용", []))
        else:
            not_applicable.extend(laws.get("적용", []))

    return {"적용": applicable, "미적용": not_applicable}


def _summarize_workers(worker_list: list[dict]) -> str:
    """근로자 목록을 유형별 요약 문자열로 변환"""
    if not worker_list:
        return "없음"
    from collections import Counter
    type_counts = Counter(w["worker_type"] for w in worker_list)
    parts = [f"{t} {c}" for t, c in type_counts.items()]
    return f"{len(worker_list)}명 ({', '.join(parts)})"
