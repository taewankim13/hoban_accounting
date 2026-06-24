"""룰 엔진 - JSON 룰 파일 기반 이상탐지 + 자연어 → 룰 변환"""
import json
import os
import re
from datetime import datetime

RULES_PATH = "rules.json"
SKILL_PATH = os.path.join(".claude", "skills", "anomaly-detection", "SKILL.md")


def load_rules() -> list[dict]:
    """rules.json에서 룰 목록을 로드한다."""
    if not os.path.exists(RULES_PATH):
        return []
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_rules(rules: list[dict]):
    """룰 목록을 rules.json에 저장하고 SKILL.md에도 반영한다."""
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    sync_to_skill_md(rules)


def get_next_rule_id(rules: list[dict]) -> str:
    """다음 사용 가능한 룰 ID를 반환한다."""
    existing = set()
    for r in rules:
        m = re.match(r'E(\d+)', r["id"])
        if m:
            existing.add(int(m.group(1)))
    # 커스텀 룰은 C001부터
    customs = set()
    for r in rules:
        m = re.match(r'C(\d+)', r["id"])
        if m:
            customs.add(int(m.group(1)))
    next_num = max(customs, default=0) + 1
    return f"C{next_num:03d}"


def apply_rules_to_journal(journal, rules: list[dict] = None) -> dict:
    """룰 목록을 전표에 적용하여 탐지 결과를 반환한다."""
    if rules is None:
        rules = load_rules()

    errors = []
    risk_score = 0.0

    total_debit = sum(l.debit_amount for l in journal.lines)
    total_credit = sum(l.credit_amount for l in journal.lines)
    max_line = max((l.debit_amount for l in journal.lines), default=0)

    # 날짜 파싱
    doc_date = None
    try:
        doc_date = datetime.strptime(journal.doc_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        pass

    doc_type = (journal.doc_type or "").strip()
    rules_map = {r["id"]: r for r in rules}

    for rule in rules:
        if not rule.get("enabled", True):
            continue

        triggered = False
        field = rule.get("field", "")
        op = rule.get("operator", "")
        val = rule.get("value")
        threshold = rule.get("threshold")

        # 숫자 비교 필드는 val을 숫자로 변환
        def to_num(v, default=0):
            try: return float(v)
            except (TypeError, ValueError): return default

        if field == "balance":
            triggered = abs(total_debit - total_credit) > to_num(threshold, 1)

        elif field == "max_line_amount":
            nval = to_num(val)
            if op == ">":
                triggered = max_line > nval
            elif op == ">=":
                triggered = max_line >= nval

        elif field == "total_amount":
            nval = to_num(val)
            if op == ">":
                triggered = total_debit > nval
            elif op == "<":
                triggered = total_debit < nval and total_debit > 0
            elif op == ">=":
                triggered = total_debit >= nval

        elif field == "is_weekend":
            if doc_date:
                triggered = doc_date.weekday() >= 5

        elif field == "day_of_month":
            nval = int(to_num(val, 28))
            if doc_date:
                if op == ">=":
                    triggered = doc_date.day >= nval
                elif op == "<=":
                    triggered = doc_date.day <= nval

        elif field == "doc_type_contains":
            keywords = str(val).split(",")
            # 전표유형 + 적요 모두 확인
            desc_text = (journal.description or "").strip()
            triggered = any(kw.strip() in doc_type or kw.strip() in desc_text for kw in keywords)

        elif field == "doc_type_equals":
            triggered = doc_type == str(val)

        elif field == "unclassified_high":
            if isinstance(val, dict):
                triggered = (doc_type == val.get("doc_type", "미분류") and
                             total_debit > to_num(val.get("min_amount", 0)))

        elif field == "odd_amount":
            min_amt = to_num(threshold, 10000)
            for line in journal.lines:
                amt = line.debit_amount or line.credit_amount
                if amt > min_amt and amt % 10 != 0:
                    triggered = True
                    break

        elif field == "description_contains":
            desc = (journal.description or "").lower()
            keywords = str(val).lower().split(",")
            triggered = any(kw.strip() in desc for kw in keywords)

        elif field == "account_code_contains":
            codes = {l.account_code for l in journal.lines}
            target_codes = str(val).split(",")
            triggered = any(tc.strip() in codes for tc in target_codes)

        elif field == "vendor_name_contains":
            vendors = [l.vendor_name or "" for l in journal.lines]
            keywords = str(val).split(",")
            triggered = any(kw.strip() in v for v in vendors for kw in keywords)

        elif field == "line_count":
            cnt = len(journal.lines)
            nval = int(to_num(val, 10))
            if op == ">":
                triggered = cnt > nval
            elif op == ">=":
                triggered = cnt >= nval
            elif op == "<":
                triggered = cnt < nval

        elif field == "duplicate":
            # 동일 일자 + 동일 금액 + 동일 계정/금액 세트 + 동일 거래처의 전표가 2건 이상
            dup_map = getattr(journal, '_duplicate_map', None)
            if dup_map:
                acct_set = frozenset((l.account_code, l.debit_amount, l.credit_amount) for l in journal.lines)
                vendors = frozenset(l.vendor_name for l in journal.lines if l.vendor_name)
                key = (journal.doc_date, journal.total_debit, acct_set, vendors)
                if key in dup_map and len(dup_map[key]) >= 2:
                    other_nos = [d for d in dup_map[key] if d != journal.doc_no]
                    if other_nos:
                        triggered = True
                        journal._mismatch_detail = f"중복 의심 전표: {', '.join(other_nos[:3])} (동일 일자/금액/계정/거래처)"

        elif field == "account_mismatch":
            # 1) 구분(손익/자산/부채)과 계정 대분류 간 불일치 검사
            category = getattr(journal, 'category', '') or ''
            big_cat = getattr(journal, 'big_category', '') or ''
            if category.strip() and big_cat.strip():
                cat = category.strip()
                big = big_cat.strip()
                if cat == '손익' and big in ('유동자산', '비유동자산', '유동부채', '비유동부채', '자본금'):
                    triggered = True
                elif cat == '자산' and big in ('매출원가', '매출', '영업외비용', '영업외수익'):
                    triggered = True

            # 2) 적요와 계정과목 간 불일치 검사
            # 적요에 특정 키워드가 있는데 관련 없는 계정으로 기표된 경우
            if not triggered:
                desc_text = (journal.description or "").strip().lower()
                acct_names = set()
                for line in journal.lines:
                    an = (line.account_name or "").lower()
                    if an:
                        acct_names.add(an)
                acct_str = " ".join(acct_names)

                # (적요 키워드 → 기대 계정 키워드) 매핑
                desc_acct_pairs = [
                    # 적요에 이 단어가 있으면 → 계정명에 이 중 하나가 있어야 정상
                    (["임차", "월세", "임대료", "숙소"], ["임차", "임대"]),
                    (["교통", "택시", "주차", "톨게이트", "기차", "ktx"], ["여비", "교통", "차량"]),
                    (["식대", "식비", "중식", "석식", "회식"], ["복리후생", "접대", "회의"]),
                    (["통신", "전화", "인터넷", "휴대폰"], ["통신"]),
                    (["교육", "연수", "세미나", "학원"], ["교육"]),
                    (["보험", "산재", "고용보험"], ["보험", "산재"]),
                    (["수선", "수리", "보수", "정비"], ["수선", "수리"]),
                    (["광고", "홍보", "마케팅", "배너"], ["광고"]),
                    (["기부", "후원", "찬조"], ["기부", "접대"]),
                    (["인건비", "급여", "상여", "퇴직"], ["노무", "급여", "인건"]),
                    (["관리비", "공용관리"], ["지급수수료", "관리"]),
                    (["소모품", "사무용품", "복사용지"], ["소모품"]),
                    (["주유", "경유", "휘발유", "유류"], ["차량", "유지"]),
                ]

                for desc_keywords, acct_keywords in desc_acct_pairs:
                    # 적요에 키워드가 포함되어 있는가?
                    desc_matched = any(kw in desc_text for kw in desc_keywords)
                    if desc_matched:
                        # 계정명에 관련 키워드가 하나라도 있는가?
                        acct_matched = any(kw in acct_str for kw in acct_keywords)
                        if not acct_matched and acct_str:
                            triggered = True
                            journal._mismatch_detail = f"적요 '{desc_text[:30]}'에 해당하는 계정과목이 '{', '.join(acct_names)}'과 불일치"
                            break

        elif field == "invalid_account_pair":
            # 비인가 계정 조합 (비활성 기본값이지만 활성화 시 동작)
            debit_codes = [l.account_code[:2] for l in journal.lines if l.debit_amount > 0]
            credit_codes = [l.account_code[:2] for l in journal.lines if l.credit_amount > 0]
            # 비용(4x,5x,6x) ↔ 자본(3x) 직접 상계 등 부적절 조합
            for dc in debit_codes:
                for cc in credit_codes:
                    if dc.startswith('4') and cc.startswith('3'):
                        triggered = True
                    elif dc.startswith('6') and cc.startswith('3'):
                        triggered = True

        elif field == "off_hours":
            # 입력일시에서 시간 추출
            input_dt = getattr(journal, 'input_datetime', '') or ''
            if input_dt and ':' in input_dt:
                try:
                    hour = int(input_dt.split(' ')[-1].split(':')[0])
                    if hour < 7 or hour >= 22:
                        triggered = True
                except (ValueError, IndexError):
                    pass

        elif field == "revenue_expense_side_error":
            # 수익계정(41xx,43xx)은 대변(credit)에만, 비용계정(42xx,44xx,45xx)은 차변(debit)에만 있어야 정상
            # 판단 기준: side 필드가 아닌 실제 금액이 들어간 위치 (debit_amount > 0 → 차변, credit_amount > 0 → 대변)
            # (역분개/취소 전표는 제외)
            is_reversal = any(kw in doc_type for kw in ['역분개', '취소', '반대분개', '해약', '환불'])
            if not is_reversal:
                mismatch_lines = []
                for line in journal.lines:
                    code = (line.account_code or "").strip()
                    if not code:
                        continue
                    prefix2 = code[:2]
                    acct_name = (line.account_name or code)

                    # 수익계정(41xx, 43xx)이 차변(debit)에 금액이 있음 → 비정상
                    if prefix2 in ('41', '43') and line.debit_amount > 0:
                        mismatch_lines.append(f"수익계정 '{acct_name}'({code})이 차변에 {line.debit_amount:,.0f}원 기표됨 (대변이 정상)")

                    # 비용계정(42xx, 44xx, 45xx)이 대변(credit)에 금액이 있음 → 비정상
                    elif prefix2 in ('42', '44', '45') and line.credit_amount > 0:
                        mismatch_lines.append(f"비용계정 '{acct_name}'({code})이 대변에 {line.credit_amount:,.0f}원 기표됨 (차변이 정상)")

                    # 부채계정(21xx)이 차변(debit)에 금액이 있음 → 비정상 (상환 제외)
                    elif prefix2 == '21' and line.debit_amount > 0:
                        mismatch_lines.append(f"부채계정 '{acct_name}'({code})이 차변에 {line.debit_amount:,.0f}원 기표됨 (대변이 정상)")

                    # 자산계정(11xx,13xx)이 대변(credit)에 금액이 있음 → 비정상 (감소 제외하면 일반적으로 차변)
                    # 자산은 증감이 양쪽 다 가능하므로 제외

                if mismatch_lines:
                    triggered = True
                    journal._mismatch_detail = "; ".join(mismatch_lines[:3])

        elif field == "personal_vendor_high":
            # 개인거래처 + 고액
            if isinstance(val, dict):
                target_type = val.get("vendor_type", "개인거래처")
                min_amt = to_num(val.get("min_amount", 10000000))
                for line in journal.lines:
                    vt = (line.vendor_type or "").strip()
                    amt = line.debit_amount or line.credit_amount
                    if target_type in vt and amt > min_amt:
                        triggered = True
                        break

        elif field == "empty_description":
            desc = (journal.description or "").strip()
            min_len = int(to_num(threshold, 5))
            triggered = len(desc) < min_len

        elif field == "account_pattern_mismatch":
            # 동일 거래처의 과거 패턴과 계정과목 불일치 탐지
            # _vendor_account_map이 전달되었을 때만 동작
            vmap = getattr(journal, '_vendor_account_map', None)
            if vmap:
                for line in journal.lines:
                    vname = (line.vendor_name or "").strip()
                    acct = (line.account_code or "").strip()
                    if vname and acct and vname in vmap:
                        usual_acct, usual_name, freq = vmap[vname]
                        if acct != usual_acct and freq >= 3:
                            # 3회 이상 반복된 패턴과 다른 계정 사용
                            triggered = True
                            # 상세 정보를 journal에 임시 저장
                            journal._mismatch_detail = f"거래처 '{vname}'의 통상 계정은 '{usual_acct}({usual_name})'이나, 이 전표에서는 '{acct}'로 기표됨 (과거 {freq}건 패턴)"
                            break

        if triggered:
            errors.append(rule["id"])
            risk_score += rule.get("score", 0.1)

    # 중복 제거
    errors = list(dict.fromkeys(errors))

    # 같은 필드의 상위/하위 룰 중복 제거 (더 엄격한 것만 유지)
    # 예: E004(10억)과 E004-M(5억)이 둘 다 있으면 E004만 유지
    field_hits = {}
    for eid in errors:
        r = rules_map.get(eid, {})
        f = r.get("field", "")
        s = r.get("score", 0)
        if f and f in field_hits:
            # 같은 필드에서 점수가 더 높은(더 엄격한) 룰만 유지
            prev_id, prev_score = field_hits[f]
            if s > prev_score:
                errors = [e for e in errors if e != prev_id]
                risk_score -= prev_score
                field_hits[f] = (eid, s)
            else:
                errors = [e for e in errors if e != eid]
                risk_score -= s
        elif f:
            field_hits[f] = (eid, s)
    risk_score = min(risk_score, 1.0)

    if risk_score >= 0.8:
        risk_level = "High"
    elif risk_score >= 0.3:
        risk_level = "Medium"
    elif errors:
        risk_level = "Low"
    else:
        risk_level = "정상"

    # 사유/권고 생성
    reasons = []
    recommendations = []
    for code in errors:
        r = rules_map.get(code)
        if r:
            detail = r['description']
            # 패턴 이탈/계정 불일치/차대변 오류 상세 정보
            if hasattr(journal, '_mismatch_detail') and r.get("field") in ("account_pattern_mismatch", "account_mismatch", "revenue_expense_side_error", "duplicate"):
                detail = getattr(journal, '_mismatch_detail', detail)
            reasons.append(f"[{code}] {r['name']}: {detail}")
            recommendations.append(f"{r['name']} - 해당 전표를 검토하세요.")

    return {
        "risk_level": risk_level,
        "risk_score": round(risk_score, 2),
        "error_codes": errors,
        "reasons": reasons,
        "recommendations": recommendations,
    }


# ──────────────────────────────────────
# 자연어 → 룰 변환
# ──────────────────────────────────────

NL_PATTERNS = [
    # 금액 관련
    (r'금액[이가]?\s*(\d[\d,]*)\s*(만\s*원|원|억)?\s*(이상|초과|넘[으는])', "max_line_amount", ">"),
    (r'(\d[\d,]*)\s*(만\s*원|원|억)?\s*(이상|초과)[인의]?\s*(전표|거래)', "max_line_amount", ">"),
    (r'총\s*금액[이가]?\s*(\d[\d,]*)\s*(만\s*원|원|억)?\s*(이상|초과)', "total_amount", ">"),
    # 시점 관련
    (r'주말|토요일|일요일|공휴일', "is_weekend", "=="),
    (r'월말|월\s*말|28일\s*이후|29일\s*이후|30일\s*이후', "day_of_month", ">="),
    (r'월초|월\s*초|1일~5일|5일\s*이내', "day_of_month", "<="),
    # 유형 관련
    (r'(해약|환불|역분개|취소)', "doc_type_contains", "contains"),
    (r'미분류\s*전표', "doc_type_equals", "=="),
    # 적요 관련
    (r'적요[에서]?\s*["\']?(.+?)["\']?\s*(포함|포함[된하])', "description_contains", "contains"),
    # 계정 관련
    (r'계정[이가]?\s*["\']?(.+?)["\']?\s*(포함|인\s*전표)', "account_code_contains", "contains"),
    # 거래처
    (r'거래처[가이]?\s*["\']?(.+?)["\']?\s*(포함|인\s*전표)', "vendor_name_contains", "contains"),
    # 항목 수
    (r'항목[이가]?\s*(\d+)\s*개?\s*(이상|초과)', "line_count", ">"),
    # 단수
    (r'단수\s*금액|1원\s*단위|원단위', "odd_amount", "=="),
]


def parse_with_llm(text: str) -> dict | None:
    """Gemini API로 자연어를 룰 JSON으로 변환한다."""
    import os
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    api_key = os.environ.get("ALPHA_API_KEY", "")
    if not api_key:
        return None

    try:
        import requests
        prompt = f"""당신은 전표 이상탐지 룰 생성 전문가입니다.
사용자의 자연어 설명을 분석하여 아래 JSON 형식의 룰을 생성하세요.

## 사용 가능한 필드 (field)
- max_line_amount: 최대 항목 금액 비교
- total_amount: 전표 총 금액 비교
- balance: 차대변 잔액 비교
- is_weekend: 주말 여부 (value: true)
- day_of_month: 일자 비교 (예: 28 이상이면 월말)
- doc_type_contains: 전표유형 키워드 포함 (value: "키워드1,키워드2")
- description_contains: 적요 키워드 포함 (value: "키워드1,키워드2")
- account_code_contains: 계정코드 포함 (value: "코드1,코드2")
- vendor_name_contains: 거래처명 포함 (value: "키워드1,키워드2")
- line_count: 전표 항목 수 비교
- odd_amount: 단수 금액 여부 (value: true)
- personal_vendor_high: 개인거래처 고액 (value: {{"vendor_type":"P","min_amount":금액}})
  - vendor_type: F=법인, P=개인, D=부서, S=사원, X=기타, B=은행
- unclassified_high: 미분류 고액 (value: {{"doc_type":"미분류","min_amount":금액}})
- off_hours: 근무시간 외 (value: true)
- empty_description: 적요 미입력 (value: true)
- revenue_expense_side_error: 수익/비용 차대변 오류 (value: true)
- account_pattern_mismatch: 반복거래 계정 이탈 (value: true)
- duplicate: 중복 전표 (value: true)
- account_mismatch: 계정과목 착오 (value: true)

## 사용 가능한 연산자 (operator)
- ">": 초과, ">=": 이상, "<": 미만, "<=": 이하, "==": 일치, "!=": 불일치, "contains": 포함, "compound": 복합 조건

## 위험등급 (severity): "High", "Medium", "Low"
## 카테고리 (category): "금액", "시점", "유형", "내용", "계정", "거래처", "정합성", "증빙", "중복", "기타"

## 점수 (score): 0~1 (High=0.3~0.5, Medium=0.15~0.25, Low=0.05~0.1)

## 금액 변환: 만원→10000, 억→100000000

## 반드시 아래 JSON 형식으로만 응답하세요:
{{"name":"룰 이름","description":"상세 설명","field":"필드명","operator":"연산자","value":"값","threshold":null,"severity":"등급","score":0.15,"category":"카테고리"}}

사용자 입력: {text}"""

        res = requests.post(
            "https://workspace.kr.pwc.com/api/workspace/coding_agent/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "Gemini_3.1_Pro", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024},
            timeout=30,
        )
        res.raise_for_status()
        content = res.json()["choices"][0]["message"].get("content", "").strip()

        if not content:
            # content가 비어있으면 (finish_reason: length 등) 재시도
            res2 = requests.post(
                "https://workspace.kr.pwc.com/api/workspace/coding_agent/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "Gemini_3.1_Pro", "messages": [{"role": "user", "content": f"다음 전표 이상탐지 룰을 JSON으로 만들어줘. 반드시 JSON만 응답해: {text}"}], "max_tokens": 2048},
                timeout=30,
            )
            content = res2.json()["choices"][0]["message"].get("content", "").strip()
            if not content:
                return None

        # JSON 추출
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        if not content.startswith('{'):
            idx = content.find('{')
            if idx >= 0:
                content = content[idx:]
        last = content.rfind('}')
        if last >= 0:
            content = content[:last + 1]

        result = json.loads(content)
        result.setdefault("enabled", True)
        result.setdefault("threshold", None)

        # value가 문자열 숫자면 변환
        if isinstance(result.get("value"), str) and result["value"].replace(",", "").isdigit():
            result["value"] = int(result["value"].replace(",", ""))

        print(f"[룰빌더] LLM 생성: {result.get('name')} / field={result.get('field')} / value={result.get('value')}")
        return result

    except Exception as e:
        print(f"[룰빌더] LLM 실패: {e}")
        return None


def parse_natural_language_rule(text: str) -> dict | None:
    """자연어 설명을 파싱하여 룰 JSON 구조를 생성한다. LLM 우선, 로컬 폴백."""
    text = text.strip()

    # 1순위: LLM (Gemini)
    llm_result = parse_with_llm(text)
    if llm_result:
        return llm_result

    # 금액 추출 헬퍼
    def extract_amount(s):
        m = re.search(r'(\d[\d,]*)\s*(만\s*원|억|원)?', s)
        if not m:
            return 0
        raw = int(m.group(1).replace(",", ""))
        unit = m.group(2) or ""
        if "만" in unit:
            return raw * 10000
        elif "억" in unit:
            return raw * 100000000
        return raw

    # 위험등급 추출
    severity = "Medium"
    if any(kw in text for kw in ["고위험", "높은", "심각", "긴급", "High"]):
        severity = "High"
    elif any(kw in text for kw in ["낮은", "참고", "Low", "경미"]):
        severity = "Low"

    # 점수 추출
    score_match = re.search(r'점수[:\s]*(\d*\.?\d+)', text)
    score = float(score_match.group(1)) if score_match else (0.3 if severity == "High" else 0.15 if severity == "Medium" else 0.05)

    # 카테고리 추출
    category = "기타"
    if any(kw in text for kw in ["금액", "고액", "초과", "이상"]):
        category = "금액"
    elif any(kw in text for kw in ["주말", "월말", "시간", "시점", "일자"]):
        category = "시점"
    elif any(kw in text for kw in ["유형", "미분류", "해약", "환불"]):
        category = "유형"
    elif any(kw in text for kw in ["적요", "내용"]):
        category = "내용"
    elif any(kw in text for kw in ["계정", "과목"]):
        category = "계정"
    elif any(kw in text for kw in ["거래처"]):
        category = "거래처"
    elif any(kw in text for kw in ["중복", "반복"]):
        category = "중복"
    elif any(kw in text for kw in ["단수", "원단위"]):
        category = "금액"

    for pattern, field, operator in NL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            value = True
            threshold = None

            if field in ("max_line_amount", "total_amount"):
                value = extract_amount(text)
                if value == 0:
                    continue

            elif field == "day_of_month":
                day_match = re.search(r'(\d+)일', text)
                value = int(day_match.group(1)) if day_match else 28

            elif field in ("doc_type_contains", "description_contains", "account_code_contains", "vendor_name_contains"):
                # 키워드 추출
                groups = match.groups()
                keywords = groups[0] if groups else ""
                if not keywords:
                    keywords = match.group(1) if match.lastindex and match.lastindex >= 1 else ""
                value = keywords.strip()

            elif field == "line_count":
                value = int(match.group(1))

            elif field == "odd_amount":
                value = True
                threshold = extract_amount(text) or 10000

            elif field == "is_weekend":
                value = True

            # 룰 이름 생성
            name = text[:30].strip()
            if len(text) > 30:
                name = name + "..."

            return {
                "name": name,
                "description": text,
                "severity": severity,
                "score": score,
                "enabled": True,
                "field": field,
                "operator": operator,
                "value": value,
                "threshold": threshold,
                "category": category,
            }

    # 매칭 실패 시 키워드 기반 적요 검색 룰로 폴백
    keywords = re.findall(r'[가-힣a-zA-Z]{2,}', text)
    if keywords:
        kw_str = ",".join(keywords[:3])
        return {
            "name": text[:30].strip(),
            "description": text,
            "severity": severity,
            "score": score,
            "enabled": True,
            "field": "description_contains",
            "operator": "contains",
            "value": kw_str,
            "threshold": None,
            "category": "내용",
        }

    return None


# ──────────────────────────────────────
# SKILL.md 동기화
# ──────────────────────────────────────

def sync_to_skill_md(rules: list[dict]):
    """현재 룰 목록을 SKILL.md에 반영한다."""
    yaml_lines = ["rules:"]
    for r in rules:
        status = "활성" if r.get("enabled", True) else "비활성"
        yaml_lines.append(f'  - id: {r["id"]}')
        yaml_lines.append(f'    name: "{r["name"]}"')
        yaml_lines.append(f'    field: "{r.get("field", "")}"')
        yaml_lines.append(f'    operator: "{r.get("operator", "")}"')
        yaml_lines.append(f'    value: {json.dumps(r.get("value"), ensure_ascii=False)}')
        yaml_lines.append(f'    severity: "{r["severity"]}"')
        yaml_lines.append(f'    score: {r.get("score", 0.1)}')
        yaml_lines.append(f'    category: "{r.get("category", "기타")}"')
        yaml_lines.append(f'    status: "{status}"')
        yaml_lines.append(f'    description: "{r["description"]}"')
        yaml_lines.append(f'')

    yaml_block = "\n".join(yaml_lines)

    # SKILL.md 읽기
    if not os.path.exists(SKILL_PATH):
        return

    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # ```yaml ... ``` 블록 교체
    pattern = r'(### 룰 설정 구조 \(YAML\)\s*\n```yaml\n)(.*?)(```)'
    replacement = f'### 룰 설정 구조 (YAML)\n```yaml\n{yaml_block}\n```'

    if re.search(pattern, content, re.DOTALL):
        new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    else:
        # 블록이 없으면 룰 기반 탐지 섹션 뒤에 추가
        new_content = content

    with open(SKILL_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
