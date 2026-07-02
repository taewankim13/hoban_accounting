"""컨테이너 시작 시 DB 초기화 + CSV 임포트 + 룰 분석 자동 실행"""
import os
from database import engine, SessionLocal, Base
from models import JournalEntry

def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    count = db.query(JournalEntry).count()
    db.close()
    return count

def run():
    count = init_db()
    if count > 0:
        print(f"[startup] DB에 이미 {count}건의 전표가 있습니다. 임포트 생략.")
        return

    csv_path = "hoban_data_2.csv"
    if not os.path.exists(csv_path):
        print(f"[startup] {csv_path} 파일이 없습니다. 임포트 생략.")
        return

    print("[startup] DB가 비어있습니다. CSV 임포트를 시작합니다...")
    from import_csv import import_hoban_csv
    import_hoban_csv(csv_path)

    print("[startup] 룰 엔진 분석을 시작합니다...")
    from rule_engine import load_rules, apply_rules_to_journal
    from sqlalchemy.orm import joinedload
    from datetime import datetime
    import collections

    db = SessionLocal()
    rules = load_rules()
    journals = db.query(JournalEntry).options(
        joinedload(JournalEntry.lines),
    ).all()

    vendor_acct_counts = collections.defaultdict(lambda: collections.Counter())
    for j in journals:
        for line in j.lines:
            vname = (line.vendor_name or "").strip()
            acct = (line.account_code or "").strip()
            if vname and acct:
                vendor_acct_counts[vname][acct] += 1
    vendor_account_map = {}
    for vname, counter in vendor_acct_counts.items():
        most_common_acct, freq = counter.most_common(1)[0]
        acct_name = most_common_acct
        for j in journals:
            for line in j.lines:
                if line.account_code == most_common_acct and line.account_name and line.account_name != most_common_acct:
                    acct_name = line.account_name
                    break
            if acct_name != most_common_acct:
                break
        vendor_account_map[vname] = (most_common_acct, acct_name, freq)

    dup_key_map = collections.defaultdict(list)
    for j in journals:
        acct_set = frozenset((l.account_code, l.debit_amount, l.credit_amount) for l in j.lines)
        vendors = frozenset(l.vendor_name for l in j.lines if l.vendor_name)
        key = (j.doc_date, j.total_debit, acct_set, vendors)
        dup_key_map[key].append(j.doc_no)
    dup_map = {k: v for k, v in dup_key_map.items() if len(v) >= 2}

    for i, journal in enumerate(journals):
        journal._vendor_account_map = vendor_account_map
        journal._duplicate_map = dup_map
        result = apply_rules_to_journal(journal, rules)
        journal.ai_risk_level = result["risk_level"]
        journal.ai_risk_score = result["risk_score"]
        journal.ai_error_codes = ",".join(result["error_codes"]) if result["error_codes"] else None
        journal.ai_reason = "\n".join(result["reasons"]) if result["reasons"] else None
        journal.ai_recommendation = "\n".join(result["recommendations"]) if result["recommendations"] else None
        journal.ai_analyzed_at = datetime.now()
        if (i + 1) % 500 == 0:
            db.commit()
            print(f"[startup] 분석 진행: {i+1}/{len(journals)}")

    db.commit()
    db.close()

    high = sum(1 for j in journals if j.ai_risk_level == "High")
    med = sum(1 for j in journals if j.ai_risk_level == "Medium")
    low = sum(1 for j in journals if j.ai_risk_level == "Low")
    ok = sum(1 for j in journals if j.ai_risk_level == "정상")
    print(f"[startup] 분석 완료: {len(journals)}건 (High:{high} Medium:{med} Low:{low} 정상:{ok})")

if __name__ == "__main__":
    run()
