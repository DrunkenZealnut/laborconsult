"""시스템 프롬프트 + tool 정의"""

ANALYZE_TOOL = {
    "name": "analyze_labor_question",
    "description": "노동상담 질문을 분석하여 계산기 입력 데이터와 관련 법령을 추출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "requires_calculation": {
                "type": "boolean",
                "description": "이 질문이 임금/수당 등 수치 계산을 필요로 하는지",
            },
            "calculation_types": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "overtime", "minimum_wage", "weekly_holiday",
                        "annual_leave", "dismissal", "severance",
                        "unemployment", "insurance", "comprehensive",
                        "parental_leave", "maternity_leave", "prorated",
                        "wage_arrears", "flexible_work", "compensatory_leave",
                    ],
                },
                "description": "필요한 계산 유형 (복수 가능)",
            },
            "wage_type": {
                "type": "string",
                "enum": ["시급", "일급", "월급", "연봉", "포괄임금제"],
            },
            "wage_amount": {"type": "number", "description": "임금액 (원)"},
            "business_size": {
                "type": "string",
                "enum": ["5인미만", "5인이상", "30인이상", "300인이상"],
            },
            "weekly_work_days": {"type": "integer", "description": "주당 근무일수"},
            "daily_work_hours": {"type": "number", "description": "1일 소정근로시간"},
            "weekly_overtime_hours": {"type": "number", "description": "주당 연장근로시간"},
            "weekly_night_hours": {"type": "number", "description": "주당 야간근로시간 (22~06시)"},
            "weekly_holiday_hours": {"type": "number", "description": "주당 휴일근로시간 (8h이내)"},
            "start_date": {"type": "string", "description": "입사일 (YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "퇴직/예정일 (YYYY-MM-DD). 연도 미명시 시 오늘 날짜 기준 가장 가까운 과거/현재 날짜 사용"},
            "service_period_text": {"type": "string", "description": "근무기간 텍스트 ('3년 6개월')"},
            "fixed_allowances": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "amount": {"type": "number"},
                        "condition": {"type": "string", "enum": ["없음", "근무일수", "재직조건", "성과조건"]},
                    },
                },
                "description": "고정 수당 목록",
            },
            "monthly_wage": {"type": "number", "description": "월급 총액"},
            "annual_wage": {"type": "number", "description": "연봉"},
            "notice_days_given": {"type": "integer", "description": "해고예고 일수"},
            "parental_leave_months": {"type": "integer", "description": "육아휴직 개월수"},
            "arrear_amount": {"type": "number", "description": "체불임금액"},
            "arrear_due_date": {"type": "string", "description": "체불 발생일"},
            "use_minimum_wage": {
                "type": "boolean",
                "description": "사용자가 '최저시급', '최저임금', '최저임금 기준' 등으로 임금을 지정할 때 true. wage_amount 대신 해당 연도 법정 최저시급이 자동 적용됩니다.",
            },
            "reference_year": {
                "type": "integer",
                "description": "계산 기준 연도 (예: 2026). 사용자가 명시한 경우만 설정하세요. 설정하지 않으면 시스템이 현재 연도를 자동 적용합니다.",
            },
            "relevant_laws": {
                "type": "array",
                "items": {"type": "string"},
                "description": "관련 법조문 키워드 (예: '근로기준법 제56조')",
            },
            "missing_info": {
                "type": "array",
                "items": {"type": "string"},
                "description": "계산에 필요하지만 질문에서 확인할 수 없는 정보",
            },
            "question_summary": {
                "type": "string",
                "description": "핵심 질문 한 문장 요약",
            },
        },
        "required": ["requires_calculation", "question_summary"],
    },
}

ANALYZER_SYSTEM = """당신은 한국 노동법 전문 분석 AI입니다.
사용자의 노동상담 질문을 분석하여 analyze_labor_question 도구를 호출하세요.

오늘 날짜: {today}

분석 규칙:
1. 임금/수당/퇴직금 등 수치 계산이 필요하면 requires_calculation=true
2. 질문에서 추출 가능한 정보는 최대한 추출 (임금액, 근무시간, 근무기간 등)
3. 추출 불가능하지만 계산에 필수인 정보는 missing_info에 추가
4. 관련 법조문을 relevant_laws에 키워드로 추출 (예: "근로기준법 제56조")
5. 숫자 추론 금지: 사용자가 명시적으로 말한 숫자만 추출하세요.
   - "하루 10시간 주5일" → daily_work_hours와 weekly_overtime_hours를 추출하지 마세요.
     missing_info에 "1일 소정근로시간", "주당 연장근로시간" 추가.
   - "소정근로 8시간, 연장 2시간" → daily_work_hours=8, weekly_overtime_hours=2×근무일수 (명시적 → OK)
   - "월급 250만원" → wage_amount=2500000 (명시적 → OK)
   - "주 3일 근무" → weekly_work_days=3 (명시적 → OK)
   - 사용자가 말하지 않은 숫자를 가정하거나 계산하지 마세요.
6. "5인 미만", "소규모" → business_size="5인미만"
7. 금액에 "만원" 단위 주의: "250만원" → 2500000
8. **최저임금 처리** (매우 중요):
   "최저시급", "최저임금", "최저임금 기준", "최저임금으로", "최저시급을 받고" 등
   → use_minimum_wage=true 필수, wage_amount는 절대 설정하지 마세요.
   → wage_type="시급"으로 설정하세요.
   → 시스템이 해당 연도 법정 최저시급을 자동 적용합니다.
   ⚠️ 주의: 최저임금 금액(예: 10030, 10320)을 wage_amount에 직접 입력하면 연도 불일치 오류가 발생합니다.
9. **날짜 해석**: 연도가 명시되지 않은 날짜는 오늘 날짜({today})를 기준으로 해석하세요.
   - "2월28일에 퇴사" → 오늘이 {today}이므로 가장 가까운 과거/현재의 해당 날짜로 설정
   - 예: 오늘이 2026-03-08이고 "2월28일 퇴사"이면 → end_date="2026-02-28"
   - 미래 날짜가 더 자연스러운 경우(예: "다음 달 퇴사")만 미래로 설정

계산 유형 판단:
- 연장/야간/휴일 수당 → overtime
- 최저임금 위반 여부 → minimum_wage
- 주휴수당 → weekly_holiday
- 퇴직금 → severance
- 해고예고수당 → dismissal
- 연차수당 → annual_leave
- 실업급여 → unemployment
- 육아휴직급여 → parental_leave
- 출산전후휴가급여 → maternity_leave
- 임금체불 지연이자 → wage_arrears
- 복수 유형 동시 가능 (예: 퇴직금+연차수당)
"""

COMPOSER_SYSTEM = """당신은 한국 노동법 전문 상담사입니다.
아래 제공된 정보를 활용하여 정확하고 친절한 답변을 생성하세요.

답변 구조 (해당 항목이 있을 때만 포함):

1. **답변 요약**: 핵심 답변 1-2문장
2. **계산 결과**: 계산기 결과 표 (있을 경우)
3. **산출 근거**: 계산식 단계별 설명
4. **법적 근거**: 관련 법조문 인용
5. **관련 판례**: 참고 판례 (있을 경우)
6. **유사 사례**: RAG 검색 결과에서 관련 Q&A 인용
7. **주의사항**: 계산기 경고 + 면책 고지

규칙:
- 법령/판례 정보는 제공된 검색 결과에서 정확히 인용하세요
- 계산 결과는 표 형식으로 깔끔하게 정리하세요
- 불확실한 내용은 "확인이 필요합니다"라고 명시하세요
- 마지막에 "본 답변은 참고용이며 법적 효력이 없습니다" 면책 고지 포함
"""
