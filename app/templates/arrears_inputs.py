"""체불이자 입력. 원금 충당·법정 제외 자격은 질문의 확인된 사실만 전달한다."""
_PAYMENTS = {
    'type':'array','description':'채권별 부분 변제. 입금 총액을 원금 충당액으로 추정하지 않음',
    'items':{'type':'object','properties':{
        'date':{'type':'string','description':'실제 변제일 YYYY-MM-DD'},
        'principal_amount':{'type':'number','description':'비용·이자 충당과 구분하여 확인된 원금 충당액'},
        'interest_amount':{'type':'number','description':'같은 지급에서 확인된 이자 충당액. 이자 지급 없음이 명시된 경우 0, 미확인은 생략(청구 합계 보류)'},
        'allocation_confirmed':{'type':'boolean','description':'원금 충당액·채권 귀속이 확인됐을 때만 true'},
    },'required':['date','principal_amount','allocation_confirmed']},
}
_EXCLUSIONS = {
    'type':'array','description':'연20% 법정 적용 제외 구간. 단순 자금난·소송 제기만으로 인정하지 않음',
    'items':{'type':'object','properties':{
        'start_date':{'type':'string','description':'제외 시작일 YYYY-MM-DD 포함'},
        'end_date':{'type':'string','description':'제외 종료일 YYYY-MM-DD 포함'},
        'reason':{'type':'string','enum':['natural_disaster','insolvency','statutory_funding_constraint',
                                        'reasonable_legal_dispute','equivalent']},
        'eligible':{'type':'boolean','description':'제37조·시행령18조 해당 자격이 확인된 경우만 true'},
    },'required':['start_date','end_date','reason','eligible']},
}
ARREARS_PROPERTIES = {
    'arrear_amount':{'type':'number','description':'지연이자를 계산할 확정 원금. 채권 목록과 중복 입력 금지'},
    'arrear_due_date':{'type':'string','description':'원래 정기지급일 YYYY-MM-DD. 체불 첫날(다음 날)과 구분'},
    'arrear_calc_date':{'type':'string','description':'이자를 계산할 마지막 날 YYYY-MM-DD 포함. 질문에 명시된 경우 반드시 전달'},
    'is_post_retirement_arrear':{'type':'boolean','description':'퇴직했다는 사실만. 14일 경과나 연20%를 뜻하지 않음'},
    'arrear_claim_kind':{'type':'string','enum':['regular_wage','retirement_lump_sum','other_rate'],
                        'description':'정기지급 임금/퇴직급여 일시금/판결·약정·DC 부담금 등 별도 이율'},
    'arrear_retirement_effective_date':{'type':'string','description':'퇴직 효력일 YYYY-MM-DD, 마지막 재직일 다음 날 0시. 날짜 의미 미확인이면 생략'},
    'arrear_last_employed_date':{'type':'string','description':'마지막 재직일 YYYY-MM-DD. 퇴직 효력일과 구분'},
    'debtor_is_merchant':{'type':'boolean','description':'채무가 상행위로 생겼으면 true, 민사채무 확인이면 false. 사업주라는 이유만으로 추정 금지'},
    'arrear_deadline_holidays':{'type':'array','items':{'type':'string'},
                              'description':'퇴직 지급기간 말일 조정에 필요한 확인된 법정·대체공휴일 날짜. 미확인은 생략, 없다고 확인된 경우만 빈 배열'},
    'arrear_payments':_PAYMENTS,
    'arrear_exclusions':_EXCLUSIONS,
    'arrear_claims':{'type':'array','description':'복수 확정 채권. 단일 원금·지급기일·변제 필드와 중복 금지',
        'items':{'type':'object','properties':{
            'id':{'type':'string','description':'중복되지 않는 채권 식별자'},
            'amount':{'type':'number','description':'해당 채권의 확정 원금'},
            'due_date':{'type':'string','description':'해당 채권 원래 지급기일 YYYY-MM-DD'},
            'claim_kind':{'type':'string','enum':['regular_wage','retirement_lump_sum','other_rate']},
            'payments':_PAYMENTS,'exclusions':_EXCLUSIONS,
        },'required':['id','amount','claim_kind']}},
}
