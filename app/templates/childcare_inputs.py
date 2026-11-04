"""육아급여 분석 입력. 질문에 없는 자격·사용 이력은 생성하지 않는다."""

CHILDCARE_PROPERTIES = {}
for _kind,_fields in {
    'boolean': {
        'childcare_example':'날짜 없는 현행 제도 예시 요청인 경우만 true. 실제 사용·정산 질문의 날짜 누락을 예시로 바꾸지 않음',
        'is_second_parent':'두 번째 육아휴직 사용자라는 명시 사실. 특례 자격을 뜻하지 않음',
        'parental_same_child':'양쪽 부모가 같은 자녀에 대해 사용함이 명시된 경우',
        'parental_single_parent_eligible':'한부모가족지원법상 한부모 자격 확인. 단순히 혼자 양육한다는 말로 추정하지 않음',
        'parental_disabled_child_eligible':'법령상 장애아동 부모 연장 자격이 명시된 경우',
        'childcare_spouse_risk_eligible':'임신 중 배우자의 법정 유산·조산 등 위험 요건이 명시된 경우',
        'parental_other_parent_spouse_risk_eligible':'상대 부모가 임신 배우자 돌봄으로 사용하는 경우의 법정 위험 요건',
        'short_parental_reason_eligible':'단기 육아휴직 법정 사유(자녀 기관 휴원·휴교·방학·질병 등)가 확인된 경우',
        'short_parental_used_this_year':'해당 연도 단기 육아휴직을 이미 사용했는지. 미기재는 생략',
    },
    'integer': {
        'parental_leave_months':'이번 계산 대상 휴직 개월 수. 과거 사용 개월 수와 분리',
        'parental_prior_months':'계산 대상 이전 동일 자녀에 대한 기존 사용의 완전한 개월 수. 미기재 추정 금지',
        'parental_prior_days':'기존 사용의 1개월 미만 잔여 일수. 개월 수로 반올림 금지',
        'parental_other_parent_months':'같은 자녀에 대한 상대 부모 실제 사용 개월 수. 예정과 실제 구분',
        'childcare_child_age':'각 개시일 현재 자녀 만 나이. 생년월일이 있으면 생년월일을 전달',
        'childcare_child_grade':'각 개시일 현재 자녀 초등 학년',
        'childcare_insured_days':'개시일 전 고용보험 피보험 단위기간 일수. 재직일수·가입 개월 수로 추정 금지',
        'reduced_months':'이번 계산 대상 육아기 단축 개월 수',
        'reduced_prior_months':'같은 자녀 기존 육아기 단축 사용 개월 수',
    },
    'number': {
        'reduced_weekly_hours_before':'단축 전 주 소정근로시간. 일 단축시간으로 추정 금지',
        'reduced_weekly_hours_after':'단축 후 주 소정근로시간. 15~35시간 범위',
        'reduced_unused_parental_months':'기본 12개월의 육아휴직 중 미사용 개월 수. 추가 6개월 제외',
        'childcare_employer_monthly_payment':'휴직·단축 기간 사업주가 지급하는 월 금액. 일부월에는 월 환산 금액임이 명시된 경우만. 미지급이 명시되면 0',
        'reduced_offset_monthly_ordinary_wage':'단축급여 감액 기준인 단축 직전월 또는 인상 후 해당 기간의 월 통상임금. 질문에 명시된 경우만',
        'reduced_work_hours_per_day':'하루 단축시간. 주 소정시간을 대체하지 않음',
    },
    'string': {
        'parental_leave_start':'이번 휴직 실제 개시일 YYYY-MM-DD. 입사일과 구분, 오늘로 추정 금지',
        'parental_first_leave_start':'분할 재사용 시 동일 자녀에 대한 최초 육아휴직 개시일. 현재 재사용 시작일과 구분',
        'parental_leave_end':'이번 휴직 마지막 날 YYYY-MM-DD(포함)',
        'parental_other_parent_start':'상대 부모의 같은 자녀 육아휴직 개시일 YYYY-MM-DD',
        'childcare_child_birth_date':'자녀 생년월일 YYYY-MM-DD',
        'reduced_start':'육아기 단축 실제 개시일 YYYY-MM-DD. 휴직 시작일과 별도. 예: 2026년 10월 한 달 전체 사용은 2026-10-01~2026-10-31을 뜻함',
        'reduced_end':'육아기 단축 마지막 날 YYYY-MM-DD(포함)',
    },
}.items():
    CHILDCARE_PROPERTIES.update({k:{'type':_kind,'description':v} for k,v in _fields.items()})
CHILDCARE_PROPERTIES.update({
    'parental_scheme':{'type':'string','enum':['general','six_plus_six','single_parent'],
                       'description':'요청한 급여 유형. 두 번째 사용자라는 사실만으로 6+6 선택 금지'},
    'childcare_reason':{'type':'string','enum':['child','pregnant_self','pregnant_spouse'],
                        'description':'자녀 양육/임신 중 본인 모성보호/법정 위험 임신 배우자 돌봄'},
    'parental_first_leave_reason':{'type':'string','enum':['child','pregnant_self','pregnant_spouse'],
                                  'description':'본인 최초 사용 사유. 재사용 사유와 다르면 별도 전달'},
    'parental_other_parent_reason':{'type':'string','enum':['child','pregnant_self','pregnant_spouse'],
                                   'description':'상대 부모 최초 사용 사유. 상대가 출산 전 모성보호 휴직했는지 별도 구분'},
})
for _key,_label in [('parental_leave_periods','본인 휴직'),('parental_other_parent_periods','상대 부모 휴직'),('reduced_periods','육아기 단축')]:
    CHILDCARE_PROPERTIES[_key]={
        'type':'array','description':_label+' 실제 사용 구간 목록. 단일 시작·종료 필드와 중복 입력 금지',
        'items':{'type':'object','properties':{
            'start_date':{'type':'string','description':'시작일 YYYY-MM-DD'},
            'end_date':{'type':'string','description':'종료일 YYYY-MM-DD 포함'},
            'kind':{'type':'string','enum':['regular','short'],'description':'short는 법정 7/14일 단기 육아휴직만'},
            'reason':{'type':'string','enum':['child','pregnant_self','pregnant_spouse'],
                      'description':'이 구간 개시 사유. 임신 중 사용 뒤 출생 후 재사용이면 각각 구분'},
            'employer_monthly_payment':{'type':'number','description':'해당 구간의 사업주 지급 월 환산액. 미확인 생략'},
            'offset_monthly_ordinary_wage':{'type':'number','description':'해당 단축 구간의 감액 기준 월 통상임금'},
        },'required':['start_date','end_date']},
    }
