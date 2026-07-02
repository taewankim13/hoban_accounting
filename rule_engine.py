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


def _evaluate_single_condition(journal, field, op, val, threshold, context):
    """단일 조건을 평가하여 True/False를 반환한다."""
    total_debit = context["total_debit"]
    total_credit = context["total_credit"]
    max_line = context["max_line"]
    doc_date = context["doc_date"]
    doc_type = context["doc_type"]

    def to_num(v, default=0):
        try: return float(v)
        except (TypeError, ValueError): return default

    if field == "balance":
        return abs(total_debit - total_credit) > to_num(threshold, 1)

    elif field == "max_line_amount":
        nval = to_num(val)
        if op == ">": return max_line > nval
        elif op == ">=": return max_line >= nval
        return False

    elif field in ("total_amount", "debit_amount"):
        nval = to_num(val)
        if op == ">": return total_debit > nval
        elif op == "<": return total_debit < nval and total_debit > 0
        elif op == ">=": return total_debit >= nval
        elif op == "<=": return total_debit <= nval
        elif op == "==": return total_debit == nval
        elif op == "!=": return total_debit != nval
        return False

    elif field == "is_weekend":
        return doc_date is not None and doc_date.weekday() >= 5

    elif field == "day_of_month":
        nval = int(to_num(val, 28))
        if doc_date:
            if op == ">=": return doc_date.day >= nval
            elif op == "<=": return doc_date.day <= nval
        return False

    elif field == "doc_type_contains":
        keywords = str(val).split(",")
        desc_text = (journal.description or "").strip()
        return any(kw.strip() in doc_type or kw.strip() in desc_text for kw in keywords)

    elif field == "doc_type_equals":
        return doc_type == str(val)

    elif field == "unclassified_high":
        if isinstance(val, dict):
            return (doc_type == val.get("doc_type", "미분류") and
                    total_debit > to_num(val.get("min_amount", 0)))
        return False

    elif field == "odd_amount":
        min_amt = to_num(threshold, 10000)
        for line in journal.lines:
            amt = line.debit_amount or line.credit_amount
            if amt > min_amt and amt % 10 != 0:
                return True
        return False

    elif field == "description_contains":
        desc = (journal.description or "").lower()
        keywords = str(val).lower().split(",")
        return any(kw.strip() in desc for kw in keywords)

    elif field == "account_code_contains":
        codes = {l.account_code for l in journal.lines}
        target_codes = str(val).split(",")
        return any(tc.strip() in codes for tc in target_codes)

    elif field == "account_name_contains":
        acct_names = [(l.account_name or "") for l in journal.lines]
        keywords = str(val).split(",")
        return any(kw.strip() in name for name in acct_names for kw in keywords if kw.strip())

    elif field == "vendor_name_contains":
        vendors = [l.vendor_name or "" for l in journal.lines]
        keywords = str(val).split(",")
        return any(kw.strip() in v for v in vendors for kw in keywords)

    elif field == "line_count":
        cnt = len(journal.lines)
        nval = int(to_num(val, 10))
        if op == ">": return cnt > nval
        elif op == ">=": return cnt >= nval
        elif op == "<": return cnt < nval
        return False

    elif field == "has_linked_doc":
        linked = getattr(journal, 'has_linked_doc', 'N') or 'N'
        if op == "==": return linked == str(val)
        elif op == "!=": return linked != str(val)
        return False

    elif field == "has_evidence":
        evs = getattr(journal, 'evidences', None)
        ev_count = len(evs) if evs else 0
        check_val = str(val)
        if op == "==":
            if check_val in ("Y", "y"): return ev_count > 0
            elif check_val in ("N", "n"): return ev_count == 0
        elif op == "!=":
            if check_val in ("Y", "y"): return ev_count == 0
            elif check_val in ("N", "n"): return ev_count > 0
        return False

    elif field == "duplicate":
        dup_map = getattr(journal, '_duplicate_map', None)
        if dup_map:
            acct_set = frozenset((l.account_code, l.debit_amount, l.credit_amount) for l in journal.lines)
            vendors = frozenset(l.vendor_name for l in journal.lines if l.vendor_name)
            key = (journal.doc_date, journal.total_debit, acct_set, vendors)
            if key in dup_map and len(dup_map[key]) >= 2:
                other_nos = [d for d in dup_map[key] if d != journal.doc_no]
                if other_nos:
                    journal._mismatch_detail = f"중복 의심 전표: {', '.join(other_nos[:3])} (동일 일자/금액/계정/거래처)"
                    return True
        return False

    elif field == "account_mismatch":
        category = getattr(journal, 'category', '') or ''
        big_cat = getattr(journal, 'big_category', '') or ''
        if category.strip() and big_cat.strip():
            cat = category.strip()
            big = big_cat.strip()
            if cat == '손익' and big in ('유동자산', '비유동자산', '유동부채', '비유동부채', '자본금'):
                return True
            elif cat == '자산' and big in ('매출원가', '매출', '영업외비용', '영업외수익'):
                return True
        desc_text = (journal.description or "").strip().lower()
        acct_names = set()
        for line in journal.lines:
            an = (line.account_name or "").lower()
            if an:
                acct_names.add(an)
        acct_str = " ".join(acct_names)
        desc_acct_pairs = [
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
            desc_matched = any(kw in desc_text for kw in desc_keywords)
            if desc_matched:
                acct_matched = any(kw in acct_str for kw in acct_keywords)
                if not acct_matched and acct_str:
                    journal._mismatch_detail = f"적요 '{desc_text[:30]}'에 해당하는 계정과목이 '{', '.join(acct_names)}'과 불일치"
                    return True
        return False

    elif field == "invalid_account_pair":
        debit_codes = [l.account_code[:2] for l in journal.lines if l.debit_amount > 0]
        credit_codes = [l.account_code[:2] for l in journal.lines if l.credit_amount > 0]
        for dc in debit_codes:
            for cc in credit_codes:
                if dc.startswith('4') and cc.startswith('3'):
                    return True
                elif dc.startswith('6') and cc.startswith('3'):
                    return True
        return False

    elif field == "off_hours":
        input_dt = getattr(journal, 'input_datetime', '') or ''
        if input_dt and ':' in input_dt:
            try:
                hour = int(input_dt.split(' ')[-1].split(':')[0])
                if hour < 7 or hour >= 22:
                    return True
            except (ValueError, IndexError):
                pass
        return False

    elif field == "revenue_expense_side_error":
        is_reversal = any(kw in doc_type for kw in ['역분개', '취소', '반대분개', '해약', '환불'])
        if not is_reversal:
            mismatch_lines = []
            for line in journal.lines:
                code = (line.account_code or "").strip()
                if not code: continue
                prefix2 = code[:2]
                acct_name = (line.account_name or code)
                if prefix2 in ('41', '43') and line.debit_amount > 0:
                    mismatch_lines.append(f"수익계정 '{acct_name}'({code})이 차변에 {line.debit_amount:,.0f}원 기표됨 (대변이 정상)")
                elif prefix2 in ('42', '44', '45') and line.credit_amount > 0:
                    mismatch_lines.append(f"비용계정 '{acct_name}'({code})이 대변에 {line.credit_amount:,.0f}원 기표됨 (차변이 정상)")
                elif prefix2 == '21' and line.debit_amount > 0:
                    mismatch_lines.append(f"부채계정 '{acct_name}'({code})이 차변에 {line.debit_amount:,.0f}원 기표됨 (대변이 정상)")
            if mismatch_lines:
                journal._mismatch_detail = "; ".join(mismatch_lines[:3])
                return True
        return False

    elif field == "personal_vendor_high":
        if isinstance(val, dict):
            target_type = val.get("vendor_type", "개인거래처")
            min_amt = to_num(val.get("min_amount", 10000000))
            for line in journal.lines:
                vt = (line.vendor_type or "").strip()
                amt = line.debit_amount or line.credit_amount
                if target_type in vt and amt > min_amt:
                    return True
        return False

    elif field == "empty_description":
        desc = (journal.description or "").strip()
        min_len = int(to_num(threshold, 5))
        return len(desc) < min_len

    elif field.startswith("evidence_") and field != "evidence_description_match":
        EVIDENCE_FIELD_LABELS = {
            "evidence_title": ["계약서 제목", "고지서구분"],
            "evidence_target": ["계약대상", "대상주소"],
            "evidence_vendor": ["계약자 상호", "거래처명"],
            "evidence_contract_amount": ["계약금액", "합계금액"],
            "evidence_rent": ["차임(월세)", "차임", "월세"],
            "evidence_monthly_charge": ["당월요금계"],
            "evidence_period": ["계약기간", "검침기간"],
            "evidence_base_month": ["기준년월"],
            "evidence_base_date": ["기준일자", "계약일자", "고지일자"],
        }
        target_labels = EVIDENCE_FIELD_LABELS.get(field)
        if not target_labels:
            return False
        evs = getattr(journal, 'evidences', None)
        if not evs:
            return False
        import json as _json

        ev_values = []
        for ev in evs:
            pd_raw = getattr(ev, 'parsed_data', None)
            if not pd_raw:
                continue
            try:
                pd = _json.loads(pd_raw) if isinstance(pd_raw, str) else pd_raw
            except:
                continue
            if not isinstance(pd, list):
                continue
            for item in pd:
                if isinstance(item, dict) and item.get("label") in target_labels and item.get("value"):
                    ev_values.append(item["value"])
        if not ev_values:
            return False

        journal_col = str(val) if val else "description"
        if journal_col == "description":
            j_val = journal.description or ""
        elif journal_col == "doc_date":
            j_val = journal.doc_date or ""
        elif journal_col == "doc_type":
            j_val = journal.doc_type or ""
        elif journal_col == "vendor_name":
            j_val = " ".join(getattr(l, 'vendor_name', '') or '' for l in getattr(journal, 'lines', []))
        elif journal_col == "account_name":
            j_val = " ".join(getattr(l, 'account_name', '') or '' for l in getattr(journal, 'lines', []))
        elif journal_col == "total_debit":
            j_val = float(journal.total_debit or 0)
        elif journal_col == "total_credit":
            j_val = float(journal.total_credit or 0)
        elif journal_col == "project_name":
            j_val = getattr(journal, 'project_name_raw', '') or ''
        elif journal_col == "created_by":
            j_val = journal.created_by or ""
        else:
            j_val = getattr(journal, journal_col, "") or ""

        ev_text = " ".join(ev_values)
        label_display = target_labels[0]

        def _extract_tokens(text):
            parts = re.split(r'[\s,\(\)\[\]\/\-·\.\:]+', str(text))
            return {p for p in parts if len(p) >= 2}

        if op in ("has_common_word", "no_common_word"):
            ev_tokens = _extract_tokens(ev_text)
            j_tokens = _extract_tokens(str(j_val))
            has_match = any(et in jt or jt in et for et in ev_tokens for jt in j_tokens)
            if op == "no_common_word":
                if not has_match:
                    journal._mismatch_detail = f"증빙 '{label_display}'과(와) 전표 '{journal_col}' 간 동일 단어 없음"
                    return True
                return False
            return has_match

        elif op in (">", ">=", "<", "<=", "==", "!="):
            try:
                ev_num = float(re.sub(r'[^\d.]', '', ev_values[0]))
                j_num = float(j_val) if isinstance(j_val, (int, float)) else float(re.sub(r'[^\d.]', '', str(j_val)))
            except (ValueError, IndexError):
                return False
            if op == ">": return ev_num > j_num
            if op == ">=": return ev_num >= j_num
            if op == "<": return ev_num < j_num
            if op == "<=": return ev_num <= j_num
            if op == "==": return ev_num == j_num
            if op == "!=": return ev_num != j_num

        elif op == "contains":
            return any(str(v) in str(j_val) or str(j_val) in str(v) for v in ev_values)

        return False

    elif field.startswith("linkeddoc_"):
        LINKED_DOC_FIELD_LABELS = {
            "linkeddoc_title": ["문서제목"],
            "linkeddoc_site": ["현장명"],
            "linkeddoc_current_amount": ["금회기성", "금회기성액"],
            "linkeddoc_contract_amount": ["계약금액", "도급금액"],
            "linkeddoc_orderer": ["발주처", "발주자", "발주기관"],
        }
        target_labels = LINKED_DOC_FIELD_LABELS.get(field)
        if not target_labels:
            return False
        docs = getattr(journal, 'linked_docs', None)
        if not docs:
            return False
        import json as _json

        doc_values = []
        for doc in docs:
            pd_raw = getattr(doc, 'parsed_data', None)
            if not pd_raw:
                continue
            try:
                pd = _json.loads(pd_raw) if isinstance(pd_raw, str) else pd_raw
            except:
                continue
            if not isinstance(pd, list):
                continue
            for item in pd:
                if isinstance(item, dict) and item.get("label") in target_labels and item.get("value"):
                    doc_values.append(item["value"])
        if not doc_values:
            return False

        journal_col = str(val) if val else "description"
        if journal_col == "description":
            j_val = journal.description or ""
        elif journal_col == "doc_date":
            j_val = journal.doc_date or ""
        elif journal_col == "doc_type":
            j_val = journal.doc_type or ""
        elif journal_col == "vendor_name":
            j_val = " ".join(getattr(l, 'vendor_name', '') or '' for l in getattr(journal, 'lines', []))
        elif journal_col == "account_name":
            j_val = " ".join(getattr(l, 'account_name', '') or '' for l in getattr(journal, 'lines', []))
        elif journal_col == "total_debit":
            j_val = float(journal.total_debit or 0)
        elif journal_col == "total_credit":
            j_val = float(journal.total_credit or 0)
        elif journal_col == "project_name":
            j_val = getattr(journal, 'project_name_raw', '') or ''
        elif journal_col == "created_by":
            j_val = journal.created_by or ""
        else:
            j_val = getattr(journal, journal_col, "") or ""

        doc_text = " ".join(doc_values)
        label_display = target_labels[0]

        def _extract_doc_tokens(text):
            parts = re.split(r'[\s,\(\)\[\]\/\-·\.\:]+', str(text))
            return {p for p in parts if len(p) >= 2}

        if op in ("has_common_word", "no_common_word"):
            doc_tokens = _extract_doc_tokens(doc_text)
            j_tokens = _extract_doc_tokens(str(j_val))
            has_match = any(dt in jt or jt in dt for dt in doc_tokens for jt in j_tokens)
            if op == "no_common_word":
                if not has_match:
                    journal._mismatch_detail = f"연결문서 '{label_display}'과(와) 전표 '{journal_col}' 간 동일 단어 없음"
                    return True
                return False
            return has_match

        elif op in (">", ">=", "<", "<=", "==", "!="):
            try:
                doc_num = float(re.sub(r'[^\d.]', '', doc_values[0]))
                j_num = float(j_val) if isinstance(j_val, (int, float)) else float(re.sub(r'[^\d.]', '', str(j_val)))
            except (ValueError, IndexError):
                return False
            if op == ">": return doc_num > j_num
            if op == ">=": return doc_num >= j_num
            if op == "<": return doc_num < j_num
            if op == "<=": return doc_num <= j_num
            if op == "==":
                if doc_num != j_num:
                    journal._mismatch_detail = f"연결문서 '{label_display}'({doc_num:,.0f}) ≠ 전표 '{journal_col}'({j_num:,.0f})"
                return doc_num == j_num
            if op == "!=":
                if doc_num != j_num:
                    journal._mismatch_detail = f"연결문서 '{label_display}'({doc_num:,.0f}) ≠ 전표 '{journal_col}'({j_num:,.0f})"
                return doc_num != j_num

        elif op == "contains":
            return any(str(v) in str(j_val) or str(j_val) in str(v) for v in doc_values)

        return False

    elif field == "evidence_description_match":
        evs = getattr(journal, 'evidences', None)
        if not evs:
            return False
        import json as _json
        target_labels = [s.strip() for s in str(val).split(",") if s.strip()] if val else ["계약대상", "계약자 상호"]
        desc_text = (journal.description or "").strip()
        if not desc_text:
            return False

        def extract_tokens(text):
            import re as _re
            parts = _re.split(r'[\s,\(\)\[\]\/\-·\.\:]+', text)
            return {p for p in parts if len(p) >= 2}

        desc_tokens = extract_tokens(desc_text)
        has_match = False
        for ev in evs:
            pd_raw = getattr(ev, 'parsed_data', None)
            if not pd_raw:
                continue
            try:
                pd = _json.loads(pd_raw) if isinstance(pd_raw, str) else pd_raw
            except:
                continue
            if not isinstance(pd, list):
                continue
            ev_text_parts = []
            for item in pd:
                if isinstance(item, dict) and item.get("label") in target_labels and item.get("value"):
                    ev_text_parts.append(item["value"])
            if not ev_text_parts:
                continue
            ev_tokens = set()
            for part in ev_text_parts:
                ev_tokens |= extract_tokens(part)
            for et in ev_tokens:
                if any(et in dt or dt in et for dt in desc_tokens):
                    has_match = True
                    break
            if has_match:
                break

        if op == "no_common_word":
            any_parsed = any(getattr(e, 'parsed_data', None) for e in evs)
            if any_parsed and not has_match:
                journal._mismatch_detail = f"증빙자료의 {', '.join(target_labels)}과(와) 적요 '{desc_text[:40]}' 간 동일 단어 없음 (연관성 없음)"
                return True
            return False
        elif op == "has_common_word":
            return has_match
        return False

    elif field == "account_pattern_mismatch":
        vmap = getattr(journal, '_vendor_account_map', None)
        if vmap:
            for line in journal.lines:
                vname = (line.vendor_name or "").strip()
                acct = (line.account_code or "").strip()
                if vname and acct and vname in vmap:
                    usual_acct, usual_name, freq = vmap[vname]
                    if acct != usual_acct and freq >= 3:
                        journal._mismatch_detail = f"거래처 '{vname}'의 통상 계정은 '{usual_acct}({usual_name})'이나, 이 전표에서는 '{acct}'로 기표됨 (과거 {freq}건 패턴)"
                        return True
        return False

    return False


def apply_rules_to_journal(journal, rules: list[dict] = None) -> dict:
    """룰 목록을 전표에 적용하여 탐지 결과를 반환한다. 다중 조건(conditions + logic) 지원."""
    if rules is None:
        rules = load_rules()

    errors = []
    risk_score = 0.0

    total_debit = sum(l.debit_amount for l in journal.lines)
    total_credit = sum(l.credit_amount for l in journal.lines)
    max_line = max((l.debit_amount for l in journal.lines), default=0)

    doc_date = None
    try:
        doc_date = datetime.strptime(journal.doc_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        pass

    doc_type = (journal.doc_type or "").strip()
    rules_map = {r["id"]: r for r in rules}
    context = {"total_debit": total_debit, "total_credit": total_credit,
               "max_line": max_line, "doc_date": doc_date, "doc_type": doc_type}

    for rule in rules:
        if not rule.get("enabled", True):
            continue

        triggered = False

        # 다중 조건 지원: conditions 배열이 있으면 사용, 없으면 단일 조건
        conditions = rule.get("conditions")
        if conditions and isinstance(conditions, list) and len(conditions) > 0:
            logic = rule.get("logic", "AND").upper()
            results = []
            for cond in conditions:
                c_field = cond.get("field", "")
                c_op = cond.get("operator", "")
                c_val = cond.get("value")
                c_threshold = cond.get("threshold")
                result = _evaluate_single_condition(journal, c_field, c_op, c_val, c_threshold, context)
                results.append(result)

            if logic == "OR":
                triggered = any(results)
            else:
                triggered = all(results)
        else:
            field = rule.get("field", "")
            op = rule.get("operator", "")
            val = rule.get("value")
            threshold = rule.get("threshold")
            triggered = _evaluate_single_condition(journal, field, op, val, threshold, context)

        if triggered:
            errors.append(rule["id"])
            risk_score += rule.get("score", 0.1)
            if hasattr(journal, '_mismatch_detail'):
                if not hasattr(journal, '_rule_details'):
                    journal._rule_details = {}
                journal._rule_details[rule["id"]] = journal._mismatch_detail
                del journal._mismatch_detail

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
            if hasattr(journal, '_rule_details') and code in journal._rule_details:
                detail = journal._rule_details[code]
            elif hasattr(journal, '_mismatch_detail') and r.get("field") in ("account_pattern_mismatch", "account_mismatch", "revenue_expense_side_error", "duplicate", "evidence_description_match"):
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
사용자의 자연어 설명을 분석하여 JSON 형식의 룰을 생성하세요.

## 사용 가능한 필드 (field) — 반드시 이 목록의 값만 사용

### 전표 헤더 필드
- total_amount: 전표 총 금액(차변합계). 연산자: >, >=, <, <=
- description_contains: 적요 텍스트에 키워드 포함 여부. 연산자: contains, value: "키워드" 또는 "키워드1,키워드2"
- doc_type_contains: 전표유형에 키워드 포함. 연산자: contains, value: "키워드"
- has_linked_doc: 연결문서 여부. 연산자: ==, value: "Y" 또는 "N"
- has_evidence: 증빙자료 여부. 연산자: ==, value: "Y" 또는 "N"
- empty_description: 적요 미입력(5자 미만). 연산자: ==, value: true

### 전표 항목(라인) 필드
- account_name_contains: 계정과목명에 키워드 포함(부분일치). 연산자: contains, value: "교육훈련비" 등
- account_code_contains: 계정코드 포함. 연산자: contains, value: "4100" 등
- vendor_name_contains: 거래처명에 키워드 포함. 연산자: contains, value: "키워드"
- max_line_amount: 단일 항목 최대 금액. 연산자: >, >=
- line_count: 전표 항목(라인) 수. 연산자: >, >=

### 시점 필드
- is_weekend: 주말(토/일) 기표 여부. 연산자: ==, value: true
- day_of_month: 전표일자의 '일'. 연산자: >=, <=, value: 28 등
- off_hours: 근무시간 외(7시 전/22시 후). 연산자: ==, value: true

### 증빙자료 분석 필드
- evidence_description_match: 증빙자료 파싱 데이터와 전표 적요 간 연관성 비교. 연산자: no_common_word(동일 단어 없음=연관성 없음), has_common_word(동일 단어 있음=연관성 있음). value: 비교할 증빙 필드명(쉼표구분, 예: "계약대상,계약자 상호")
- evidence_title: 증빙 제목과 전표 컬럼 비교. 연산자: has_common_word, no_common_word, contains. value: 비교 대상 전표 컬럼(description 등)
- evidence_contract_amount: 증빙 계약금과 전표 금액 비교. 연산자: ==, !=, >, <. value: 비교 대상 전표 컬럼(total_debit 등)
- evidence_monthly_charge: 증빙 당월요금계와 전표 금액 비교. 연산자: ==, !=, >, <. value: 비교 대상 전표 컬럼(total_debit 등)

### 연결문서 분석 필드
- linkeddoc_title: 연결문서 문서제목과 전표 컬럼 비교. 연산자: has_common_word, no_common_word, contains. value: 비교 대상 전표 컬럼(description 등)
- linkeddoc_site: 연결문서 현장명과 전표 현장명 비교. 연산자: has_common_word, no_common_word. value: 비교 대상 전표 컬럼(project_name 등)
- linkeddoc_current_amount: 연결문서 금회기성과 전표 금액 비교. 연산자: ==, !=, >, <. value: 비교 대상 전표 컬럼(total_debit 등)
- linkeddoc_contract_amount: 연결문서 계약금액과 전표 금액 비교. 연산자: ==, !=, >, <. value: 비교 대상 전표 컬럼(total_debit 등)
- linkeddoc_orderer: 연결문서 발주처와 전표 거래처 비교. 연산자: has_common_word, no_common_word, contains. value: 비교 대상 전표 컬럼(vendor_name 등)

### 특수 탐지 필드
- balance: 차대변 잔액(불일치 금액). 연산자: !=, value: 0
- duplicate: 중복 전표 탐지. 연산자: ==, value: true
- account_mismatch: 계정과목 착오. 연산자: ==, value: true
- revenue_expense_side_error: 수익/비용 차대변 오류. 연산자: ==, value: true
- account_pattern_mismatch: 반복거래 계정 이탈. 연산자: ==, value: true
- odd_amount: 단수 금액. 연산자: ==, value: true
- personal_vendor_high: 개인거래처 고액. 연산자: compound, value: {{"vendor_type":"P","min_amount":금액}}

## 사용 가능한 연산자: ">", ">=", "<", "<=", "==", "!=", "contains", "compound", "no_common_word", "has_common_word"
## 위험등급 (severity): "High", "Medium", "Low"
## 카테고리: "금액", "시점", "유형", "내용", "계정", "거래처", "정합성", "증빙", "중복", "기타"
## 점수: 0~1 (High=0.3~0.5, Medium=0.15~0.25, Low=0.05~0.1)
## 금액 변환: 만원→10000, 억→100000000

## 출력 형식
조건이 1개이면 단일 조건 형식:
{{"name":"룰 이름","description":"설명","field":"필드명","operator":"연산자","value":"값","severity":"등급","score":0.15,"category":"카테고리"}}

조건이 2개 이상이면 (예: "A이면서 B인 전표", "A이거나 B인 전표") 다중 조건 형식:
{{"name":"룰 이름","description":"설명","conditions":[{{"field":"필드1","operator":"연산자1","value":"값1"}},{{"field":"필드2","operator":"연산자2","value":"값2"}}],"logic":"AND","severity":"등급","score":0.15,"category":"카테고리"}}
- "이면서", "이고", "그리고", "동시에" → logic: "AND"
- "이거나", "또는" → logic: "OR"

## 중요 규칙
- 계정과목명 검색(교육훈련비, 복리후생비 등)은 반드시 field: "account_name_contains", operator: "contains" 사용
- 연결문서 유무는 반드시 field: "has_linked_doc", operator: "==", value: "Y" 또는 "N"
- 증빙자료 유무는 반드시 field: "has_evidence", operator: "==", value: "Y" 또는 "N"
- 반드시 JSON만 응답하세요. 설명이나 마크다운 없이 순수 JSON만 출력.

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

        raw = json.loads(content)

        # LLM이 비표준 형식을 반환할 경우 정규화
        # 예: {conditions: {match_criteria: [...]}} → {conditions: [...]}
        conds_obj = raw.get("conditions")
        if isinstance(conds_obj, dict):
            match_criteria = conds_obj.get("match_criteria", [])
            logic = conds_obj.get("logical_operator", "AND").upper()
            if logic not in ("AND", "OR"):
                logic = "AND"
            raw["conditions"] = match_criteria if isinstance(match_criteria, list) else []
            raw["logic"] = logic

        # 필드명/키명 정규화: LLM이 rule_name, severity_level 등 다른 이름을 쓸 수 있음
        result = {
            "name": raw.get("name") or raw.get("rule_name", ""),
            "description": raw.get("description", ""),
            "severity": raw.get("severity") or raw.get("severity_level", "Medium"),
            "score": raw.get("score", 0.15),
            "category": raw.get("category", "기타"),
            "enabled": True,
            "threshold": raw.get("threshold"),
        }
        # severity 정규화
        sev = str(result["severity"]).upper()
        if sev in ("HIGH", "H"): result["severity"] = "High"
        elif sev in ("LOW", "L"): result["severity"] = "Low"
        else: result["severity"] = "Medium"

        # 다중 조건
        conditions = raw.get("conditions")
        if isinstance(conditions, list) and len(conditions) >= 2:
            norm_conds = []
            for cond in conditions:
                f = cond.get("field", "")
                o = cond.get("operator", "==")
                v = cond.get("value", "")
                if isinstance(v, str) and v.replace(",", "").isdigit():
                    v = int(v.replace(",", ""))
                norm_conds.append({"field": f, "operator": o, "value": v})
            logic = raw.get("logic", "AND")
            if logic not in ("AND", "OR"):
                logic = "AND"
            result["conditions"] = norm_conds
            result["logic"] = logic
            result["field"] = "multi_condition"
            result["operator"] = logic
            result["value"] = f"{len(norm_conds)}개 조건"
            print(f"[룰빌더] LLM 다중조건: {result.get('name')} / {len(norm_conds)}개 조건 ({logic})")
        elif isinstance(conditions, list) and len(conditions) == 1:
            c = conditions[0]
            result["field"] = c.get("field", "")
            result["operator"] = c.get("operator", "==")
            result["value"] = c.get("value", "")
            print(f"[룰빌더] LLM 생성: {result.get('name')} / field={result.get('field')} / value={result.get('value')}")
        else:
            result["field"] = raw.get("field", "")
            result["operator"] = raw.get("operator", "==")
            result["value"] = raw.get("value", "")
            if isinstance(result["value"], str) and result["value"].replace(",", "").isdigit():
                result["value"] = int(result["value"].replace(",", ""))
            print(f"[룰빌더] LLM 생성: {result.get('name')} / field={result.get('field')} / value={result.get('value')}")

        # 유효성 검증: field가 비어있거나 알 수 없는 값이면 None 반환하여 로컬 폴백으로 넘기기
        known_fields = {
            "max_line_amount","total_amount","debit_amount","balance","is_weekend","day_of_month",
            "doc_type_contains","description_contains","account_code_contains",
            "account_name_contains","vendor_name_contains","line_count",
            "has_linked_doc","has_evidence","odd_amount","off_hours","empty_description",
            "personal_vendor_high","unclassified_high","duplicate","account_mismatch",
            "account_pattern_mismatch","revenue_expense_side_error","invalid_account_pair",
            "multi_condition","evidence_description_match",
            "evidence_title","evidence_target","evidence_vendor",
            "evidence_contract_amount","evidence_rent","evidence_monthly_charge",
            "evidence_period","evidence_base_month","evidence_base_date",
            "linkeddoc_title","linkeddoc_site","linkeddoc_current_amount",
            "linkeddoc_contract_amount","linkeddoc_orderer",
        }
        if result.get("conditions"):
            bad = any(c.get("field", "") not in known_fields for c in result["conditions"])
            if bad:
                print(f"[룰빌더] LLM 결과에 알 수 없는 필드 포함 → 로컬 폴백")
                return None
        elif not result.get("field") or result["field"] not in known_fields:
            print(f"[룰빌더] LLM 필드 '{result.get('field')}' 비어있거나 알 수 없음 → 로컬 폴백")
            return None

        return result

    except Exception as e:
        print(f"[룰빌더] LLM 실패: {e}")
        return None


def _parse_single_part(text: str) -> dict | None:
    """텍스트 조각 하나에서 단일 조건(field/operator/value)을 추출한다."""
    def extract_amount(s):
        m = re.search(r'(\d[\d,]*)\s*(만\s*원|억|원)?', s)
        if not m: return 0
        raw = int(m.group(1).replace(",", ""))
        unit = m.group(2) or ""
        if "만" in unit: return raw * 10000
        elif "억" in unit: return raw * 100000000
        return raw

    # 연결문서 여부
    if re.search(r'연결\s*문서.*(없|미첨부|누락|미등록|N)', text):
        return {"field": "has_linked_doc", "operator": "==", "value": "N"}
    if re.search(r'연결\s*문서.*(있|첨부|등록|Y)', text):
        return {"field": "has_linked_doc", "operator": "==", "value": "Y"}

    # 증빙자료 여부
    if re.search(r'증빙.*(없|미첨부|누락|미등록|N)', text):
        return {"field": "has_evidence", "operator": "==", "value": "N"}
    if re.search(r'증빙.*(있|첨부|등록|Y)', text):
        return {"field": "has_evidence", "operator": "==", "value": "Y"}

    # 계정과목명 포함
    m = re.search(r'계정\s*(?:과목)?(?:명)?[이가]?\s*["\']?([가-힣a-zA-Z0-9]+)["\']?\s*(?:인|이면|관련|포함|일\s*때)', text)
    if m:
        return {"field": "account_name_contains", "operator": "contains", "value": m.group(1)}
    m = re.search(r'["\']?([가-힣]+비|[가-힣]+료|[가-힣]+금)["\']?\s*(?:계정|과목|관련)', text)
    if m:
        return {"field": "account_name_contains", "operator": "contains", "value": m.group(1)}

    # NL_PATTERNS 매칭
    for pattern, field, operator in NL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            value = True
            if field in ("max_line_amount", "total_amount"):
                value = extract_amount(text)
                if value == 0: continue
            elif field == "day_of_month":
                dm = re.search(r'(\d+)일', text)
                value = int(dm.group(1)) if dm else 28
            elif field in ("doc_type_contains", "description_contains", "account_code_contains", "vendor_name_contains"):
                groups = match.groups()
                kw = groups[0] if groups else ""
                if not kw: kw = match.group(1) if match.lastindex and match.lastindex >= 1 else ""
                value = kw.strip()
            elif field == "line_count":
                value = int(match.group(1))
            elif field == "odd_amount":
                value = True
            return {"field": field, "operator": operator, "value": value}
    return None


def parse_natural_language_rule(text: str) -> dict | None:
    """자연어 설명을 파싱하여 룰 JSON 구조를 생성한다. LLM 우선, 로컬 폴백."""
    text = text.strip()

    # 1순위: LLM (Gemini)
    llm_result = parse_with_llm(text)
    if llm_result:
        return llm_result

    # 위험등급/점수/카테고리 추출
    severity = "Medium"
    if any(kw in text for kw in ["고위험", "높은", "심각", "긴급", "High"]): severity = "High"
    elif any(kw in text for kw in ["낮은", "참고", "Low", "경미"]): severity = "Low"
    score_match = re.search(r'점수[:\s]*(\d*\.?\d+)', text)
    score = float(score_match.group(1)) if score_match else (0.3 if severity == "High" else 0.15 if severity == "Medium" else 0.05)
    category = "기타"
    for kws, cat in [
        (["금액", "고액", "초과"], "금액"), (["주말", "월말", "시간", "시점"], "시점"),
        (["유형", "미분류", "해약"], "유형"), (["적요", "내용"], "내용"),
        (["계정", "과목"], "계정"), (["거래처"], "거래처"),
        (["중복", "반복"], "중복"), (["증빙", "연결문서"], "증빙"),
    ]:
        if any(kw in text for kw in kws): category = cat; break

    name = text[:30].strip() + ("..." if len(text) > 30 else "")

    # 2순위: AND/OR 복합 조건 로컬 파싱
    logic = "AND"
    parts = []
    if re.search(r'이거나|또는', text):
        logic = "OR"
        parts = re.split(r'이거나|또는', text)
    elif re.search(r'이면서|이고|그리고|동시에|면서', text):
        parts = re.split(r'이면서|이고|그리고|동시에|면서', text)

    if len(parts) >= 2:
        conditions = []
        for part in parts:
            cond = _parse_single_part(part.strip())
            if cond:
                conditions.append(cond)
        if len(conditions) >= 2:
            return {
                "name": name, "description": text, "severity": severity, "score": score,
                "enabled": True, "threshold": None, "category": category,
                "conditions": conditions, "logic": logic,
                "field": "multi_condition", "operator": logic,
                "value": f"{len(conditions)}개 조건",
            }

    # 3순위: 단일 조건
    cond = _parse_single_part(text)
    if cond:
        return {
            "name": name, "description": text, "severity": severity, "score": score,
            "enabled": True, "threshold": None, "category": category, **cond,
        }

    # 최종 폴백: 키워드 기반 적요 검색
    keywords = re.findall(r'[가-힣a-zA-Z]{2,}', text)
    if keywords:
        return {
            "name": name, "description": text, "severity": severity, "score": score,
            "enabled": True, "threshold": None, "category": "내용",
            "field": "description_contains", "operator": "contains",
            "value": ",".join(keywords[:3]),
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
