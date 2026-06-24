"""AI 분석 엔진 - 전표 이상탐지 및 챗 기반 전표 생성 지원"""
import re
from datetime import datetime
# 호반건설 주요 계정과목 (챗 파싱용)
ACCOUNT_MASTER = {
    "4200209": "복리후생비(공사)", "4200201": "재료비(상품)", "4200205": "여비교통비(일반)",
    "4200206": "통신비(일반)", "4200207": "지급수수료(공사)", "4200208": "교육훈련비(일반)",
    "4200210": "소모품비(상품)", "4200211": "수도광열비(임대)",
    "2100303": "미지급금(일반)", "2100304": "미지급금(카드)", "1100401": "부가세대급금",
    "5010": "자재비", "5020": "노무비", "5030": "외주비", "5040": "경비",
    "5050": "산재보험료", "5060": "안전관리비", "5070": "장비사용료", "5080": "설계비",
    "1010": "현금", "1020": "보통예금",
}


# ──────────────────────────────────────────────
# 1. 전표 생성 AI - 챗 입력 → 전표 자동 생성
# ──────────────────────────────────────────────

# 자연어 → 전표 매핑 패턴
CHAT_PATTERNS = [
    {
        "keywords": ["자재", "구매", "구입", "매입"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "5010", "account_name": "자재비", "side": "debit"},
                {"account_code": "2010", "account_name": "외상매입금", "side": "credit"},
            ],
            "guide": "자재 구매 시 부가세 별도인 경우 부가세대급금 계정을 추가하세요."
        }
    },
    {
        "keywords": ["외주", "하도급", "협력업체"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "5030", "account_name": "외주비", "side": "debit"},
                {"account_code": "2010", "account_name": "외상매입금", "side": "credit"},
            ],
            "guide": "외주비 전표 시 하도급대금 지급기한(60일)을 확인하세요. 기성 검수확인서가 필요합니다."
        }
    },
    {
        "keywords": ["노무", "인건비", "급여", "일용직", "노임"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "5020", "account_name": "노무비", "side": "debit"},
                {"account_code": "2030", "account_name": "미지급금", "side": "credit"},
            ],
            "guide": "노무비는 직접노무비(현장인력)와 간접노무비를 구분 기재하세요. 일용직은 원천징수 3.3% 확인 필요."
        }
    },
    {
        "keywords": ["장비", "중장비", "크레인", "포클레인", "렌탈"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "5070", "account_name": "장비사용료", "side": "debit"},
                {"account_code": "2030", "account_name": "미지급금", "side": "credit"},
            ],
            "guide": "장비 렌탈 시 임대차계약서 첨부 필요. 자가장비는 감가상각비로 처리합니다."
        }
    },
    {
        "keywords": ["공사대금", "기성", "공사수익", "매출"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "1130", "account_name": "공사미수금", "side": "debit"},
                {"account_code": "4010", "account_name": "공사수익", "side": "credit"},
            ],
            "guide": "공사수익 인식 시 진행률 기준(투입법/산출법) 확인 필요. 기성청구서와 일치하는지 검증하세요."
        }
    },
    {
        "keywords": ["선수금", "계약금", "착수금"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "1020", "account_name": "보통예금", "side": "debit"},
                {"account_code": "2060", "account_name": "공사선수금", "side": "credit"},
            ],
            "guide": "공사 선수금은 공사 진행에 따라 수익으로 대체해야 합니다. 선수금 잔액을 정기적으로 검토하세요."
        }
    },
    {
        "keywords": ["출장", "교통", "여비"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "6040", "account_name": "여비교통비", "side": "debit"},
                {"account_code": "1010", "account_name": "현금", "side": "credit"},
            ],
            "guide": "출장비는 사전 승인서와 영수증을 첨부하세요. 법인카드 사용 시 카드전표로 처리합니다."
        }
    },
    {
        "keywords": ["접대", "식대", "회식"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "6120", "account_name": "접대비", "side": "debit"},
                {"account_code": "1020", "account_name": "보통예금", "side": "credit"},
            ],
            "guide": "접대비는 연간 한도(중소기업 3,600만원)를 초과하지 않도록 주의하세요. 1만원 초과 시 적격증빙 필수."
        }
    },
    {
        "keywords": ["보험", "산재", "고용보험"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "5050", "account_name": "산재보험료", "side": "debit"},
                {"account_code": "1020", "account_name": "보통예금", "side": "credit"},
            ],
            "guide": "건설업 산재보험료율은 공종별로 상이합니다. 노무비 대비 보험료율을 확인하세요."
        }
    },
    {
        "keywords": ["안전", "안전관리"],
        "template": {
            "doc_type": "일반전표",
            "lines": [
                {"account_code": "5060", "account_name": "안전관리비", "side": "debit"},
                {"account_code": "1020", "account_name": "보통예금", "side": "credit"},
            ],
            "guide": "안전관리비는 공사금액의 일정비율 이상 사용이 법적 의무입니다. 사용내역을 별도 관리하세요."
        }
    },
]

# 자주 틀리는 오류 가이드
COMMON_ERRORS = {
    "5010": "자재비 ↔ 소모품비 혼동 주의. 현장 투입 자재는 자재비(5010), 사무용품은 소모품비(6170).",
    "5020": "노무비는 현장직 인건비만 해당. 본사 직원 급여는 급여(6010) 계정을 사용.",
    "5030": "외주비는 하도급 공사비만 해당. 용역비(컨설팅 등)는 지급수수료(6180)로 처리.",
    "5070": "장비사용료는 외부 렌탈만 해당. 자가보유 장비는 감가상각비(6080)로 처리.",
    "6120": "접대비 1만원 초과 시 적격증빙(세금계산서/카드) 필수. 미수취 시 손금불산입.",
    "1130": "공사미수금은 기성청구 기준. 미청구 공사는 미청구공사(별도계정) 사용.",
    "2060": "공사선수금은 진행률에 따라 공사수익으로 대체 필수. 장기 체류 잔액 주의.",
    "4010": "공사수익 인식 시점은 진행기준(K-IFRS) 준수. 완성기준 적용 불가.",
}


def parse_chat_input(message: str) -> dict:
    """챗 입력을 분석하여 전표 템플릿과 가이드를 반환한다."""
    message_lower = message.lower()

    # 금액 추출
    amount = 0
    amount_match = re.search(r'(\d[\d,]*)\s*(만\s*원|원)', message)
    if amount_match:
        raw = amount_match.group(1).replace(",", "")
        amount = int(raw)
        if "만" in amount_match.group(2):
            amount *= 10000

    # 패턴 매칭
    matched = None
    for pattern in CHAT_PATTERNS:
        for kw in pattern["keywords"]:
            if kw in message_lower:
                matched = pattern
                break
        if matched:
            break

    if not matched:
        return {
            "success": False,
            "message": "죄송합니다. 입력 내용을 분석할 수 없습니다. '자재 구매 500만원', '외주비 결제 1000만원' 등으로 입력해 주세요.",
            "suggestions": [
                "자재 구매 500만원",
                "외주비 결제 1,000만원",
                "노무비 지급 300만원",
                "공사대금 청구 5,000만원",
                "장비 렌탈비 200만원",
            ]
        }

    lines = []
    for line_tmpl in matched["template"]["lines"]:
        lines.append({
            "account_code": line_tmpl["account_code"],
            "account_name": line_tmpl["account_name"],
            "debit_amount": amount if line_tmpl["side"] == "debit" else 0,
            "credit_amount": amount if line_tmpl["side"] == "credit" else 0,
        })

    # 관련 오류 가이드 수집
    error_guides = []
    for line in lines:
        code = line["account_code"]
        if code in COMMON_ERRORS:
            error_guides.append(COMMON_ERRORS[code])

    return {
        "success": True,
        "doc_type": matched["template"]["doc_type"],
        "description": message,
        "lines": lines,
        "guide": matched["template"]["guide"],
        "error_guides": error_guides,
        "amount": amount,
    }


# ──────────────────────────────────────────────
# 2. 전표 검토 AI - 이상탐지 및 오류 분석
# ──────────────────────────────────────────────

ERROR_CODES = {
    "E001": {"name": "차대변 불일치", "severity": "High",
             "desc": "차변 합계와 대변 합계가 일치하지 않습니다."},
    "E002": {"name": "계정과목 착오", "severity": "High",
             "desc": "구분과 계정 대분류가 불일치합니다."},
    "E003": {"name": "중복 전표 등록 오류", "severity": "High",
             "desc": "동일 일자/금액/계정/거래처 조합으로 전표가 중복 생성되었습니다."},
    "E004": {"name": "금액 이상", "severity": "High",
             "desc": "통상적인 거래 금액 범위를 크게 초과합니다."},
    "E004-M": {"name": "고액 전표(5억+)", "severity": "Medium",
               "desc": "5억원을 초과하는 고액 전표입니다."},
    "E005": {"name": "주말/공휴일 기표", "severity": "Low",
             "desc": "주말 또는 공휴일에 기표된 전표입니다."},
    "E006": {"name": "역분개 반복", "severity": "Medium",
             "desc": "역분개, 취소, 반대분개가 포함된 전표입니다."},
    "E006-H": {"name": "해약/환불", "severity": "Medium",
               "desc": "해약 또는 환불이 포함된 특이 전표입니다."},
    "E007": {"name": "연결문서 누락", "severity": "Medium",
             "desc": "미분류 고액 전표로, 증빙서류 미첨부 가능성이 있습니다."},
    "E008": {"name": "비인가 계정 조합", "severity": "High",
             "desc": "차변/대변 계정 조합이 회계기준에 맞지 않습니다."},
    "E009": {"name": "월말 대량 기표", "severity": "Low",
             "desc": "월말(28일 이후)에 기표되어 결산 조정 가능성이 있습니다."},
    "E010": {"name": "단수 금액", "severity": "Low",
             "desc": "금액이 정상적인 거래 단위가 아닙니다 (1원 단위)."},
    "E011": {"name": "근무시간 외 기표", "severity": "Low",
             "desc": "오전 7시 이전 또는 오후 10시 이후에 입력된 전표입니다."},
    "E012": {"name": "개인거래처 고액", "severity": "Medium",
             "desc": "개인거래처 대상 1천만원 초과 거래입니다."},
    "E013": {"name": "적요 미입력", "severity": "Low",
             "desc": "적요(거래 설명)가 비어있거나 너무 짧습니다."},
    "E014": {"name": "다건 항목", "severity": "Low",
             "desc": "전표 항목이 10개 이상인 복잡한 전표입니다."},
    "E015": {"name": "반복거래 계정 이탈", "severity": "Medium",
             "desc": "동일 거래처의 반복 거래에서 통상 사용하던 계정과 다른 계정으로 기표되었습니다."},
    "E016": {"name": "수익/비용 차대변 오류", "severity": "High",
             "desc": "수익계정이 차변에 또는 비용계정이 대변에 기표되었습니다."},
}

# 유효한 계정 조합 (차변-대변)
VALID_ACCOUNT_PAIRS = {
    ("5010", "2010"), ("5010", "1020"), ("5010", "1010"),  # 자재비
    ("5020", "2030"), ("5020", "1020"),                    # 노무비
    ("5030", "2010"), ("5030", "1020"), ("5030", "2030"),  # 외주비
    ("5040", "2030"), ("5040", "1020"),                    # 경비
    ("5050", "1020"),                                      # 산재보험료
    ("5060", "1020"), ("5060", "2030"),                    # 안전관리비
    ("5070", "2030"), ("5070", "1020"),                    # 장비사용료
    ("5080", "2030"), ("5080", "1020"),                    # 설계비
    ("6010", "2030"), ("6010", "1020"),                    # 급여
    ("6020", "2130"),                                      # 퇴직급여
    ("6030", "2030"), ("6030", "1020"),                    # 복리후생비
    ("6040", "1010"), ("6040", "1020"),                    # 여비교통비
    ("6050", "2030"), ("6050", "1020"),                    # 통신비
    ("6060", "2030"), ("6060", "1020"),                    # 수도광열비
    ("6070", "2030"), ("6070", "1020"),                    # 세금과공과
    ("6080", "1320"), ("6080", "1330"), ("6080", "1340"),  # 감가상각비
    ("6090", "2030"), ("6090", "1020"),                    # 임차료
    ("6100", "2030"), ("6100", "1020"),                    # 수선비
    ("6110", "2030"), ("6110", "1020"),                    # 보험료
    ("6120", "1020"), ("6120", "1010"),                    # 접대비
    ("6130", "2030"), ("6130", "1020"),                    # 광고선전비
    ("6170", "1020"), ("6170", "1010"),                    # 소모품비
    ("6180", "2030"), ("6180", "1020"),                    # 지급수수료
    ("1130", "4010"),                                      # 공사미수금-공사수익
    ("1020", "2060"),                                      # 보통예금-공사선수금
    ("1020", "1130"),                                      # 보통예금-공사미수금 (회수)
    ("2010", "1020"), ("2030", "1020"),                    # 매입금/미지급금 지급
    ("1150", "1020"),                                      # 선급금
    ("1020", "2090"), ("2090", "1020"),                    # 차입금
}


def analyze_journal(journal, all_journals=None) -> dict:
    """전표를 분석하여 오류 여부를 판정한다. 호반건설 실제 계정체계 기반."""
    errors = []
    risk_score = 0.0

    total_debit = sum(l.debit_amount for l in journal.lines)
    total_credit = sum(l.credit_amount for l in journal.lines)

    # --- E001: 차대변 불일치 ---
    if abs(total_debit - total_credit) > 1:
        errors.append("E001")
        risk_score += 0.5

    # --- E004: 고액 전표 (10억 초과 - 건설사 기준) ---
    max_line = max((l.debit_amount for l in journal.lines), default=0)
    if max_line > 1_000_000_000:
        errors.append("E004")
        risk_score += 0.3
    elif max_line > 500_000_000:
        errors.append("E004")
        risk_score += 0.15

    # --- E005: 주말 기표 ---
    try:
        doc_date = datetime.strptime(journal.doc_date, "%Y-%m-%d")
        if doc_date.weekday() >= 5:
            errors.append("E005")
            risk_score += 0.1
    except (ValueError, TypeError):
        pass

    # --- E006: 해약/환불 전표 (특이 유형) ---
    doc_type = (journal.doc_type or "").strip()
    if "해약" in doc_type or "환불" in doc_type:
        errors.append("E006")
        risk_score += 0.2

    # --- E007: 미분류 전표 중 고액 ---
    if doc_type == "미분류" and total_debit > 50_000_000:
        errors.append("E007")
        risk_score += 0.15

    # --- E009: 월말 기표 (결산 조정 가능성) ---
    try:
        doc_date = datetime.strptime(journal.doc_date, "%Y-%m-%d")
        if doc_date.day >= 28:
            errors.append("E009")
            risk_score += 0.05
    except (ValueError, TypeError):
        pass

    # --- E010: 단수 금액 (1원 단위 비정상) ---
    for line in journal.lines:
        amt = line.debit_amount or line.credit_amount
        if amt > 10000 and amt % 10 != 0:
            errors.append("E010")
            risk_score += 0.05
            break

    # --- 추가: 동일 계정/금액 반복 (중복 의심) ---
    if all_journals:
        for other in (all_journals or []):
            if other.id == journal.id:
                continue
            if (other.doc_date == journal.doc_date and
                abs(other.total_debit - total_debit) < 1 and total_debit > 0):
                other_codes = {l.account_code for l in other.lines}
                journal_codes = {l.account_code for l in journal.lines}
                if other_codes == journal_codes:
                    errors.append("E003")
                    risk_score += 0.2
                    break

    # 중복 제거
    errors = list(dict.fromkeys(errors))

    # 위험 등급 결정
    risk_score = min(risk_score, 1.0)
    if risk_score >= 0.5:
        risk_level = "High"
    elif risk_score >= 0.2:
        risk_level = "Medium"
    elif errors:
        risk_level = "Low"
    else:
        risk_level = "정상"

    # 사유 생성
    reasons = []
    recommendations = []
    for code in errors:
        info = ERROR_CODES[code]
        reasons.append(f"[{code}] {info['name']}: {info['desc']}")
        # 권고 사항
        if code == "E001":
            diff = abs(total_debit - total_credit)
            recommendations.append(f"차변({total_debit:,.0f}원)과 대변({total_credit:,.0f}원)의 차이 {diff:,.0f}원을 확인하고 누락된 항목을 추가하세요.")
        elif code == "E002":
            recommendations.append("계정과목 마스터를 확인하고 올바른 계정코드로 수정하세요.")
        elif code == "E003":
            recommendations.append("동일 거래가 이중으로 기표되었는지 확인하고, 중복인 경우 하나를 삭제하세요.")
        elif code == "E004":
            recommendations.append("고액 전표(1억원 초과)입니다. 부서장 승인 및 증빙서류를 확인하세요.")
        elif code == "E005":
            recommendations.append("주말 기표 전표입니다. 긴급 사유가 있는지 확인하세요.")
        elif code == "E006":
            recommendations.append("역분개 사유를 확인하고, 원전표와 대조하세요.")
        elif code == "E007":
            recommendations.append("세금계산서, 계약서 등 증빙서류를 첨부하세요.")
        elif code == "E008":
            recommendations.append("차변/대변 계정 조합이 회계기준에 맞는지 확인하세요. 올바른 상대계정을 사용하세요.")
        elif code == "E009":
            recommendations.append("월말 집중 기표입니다. 결산 조정 목적이 아닌지 확인하세요.")
        elif code == "E010":
            recommendations.append("금액의 원단위를 확인하세요. 실제 거래 금액과 일치하는지 검증 필요.")

    return {
        "risk_level": risk_level,
        "risk_score": round(risk_score, 2),
        "error_codes": errors,
        "reasons": reasons,
        "recommendations": recommendations,
    }
