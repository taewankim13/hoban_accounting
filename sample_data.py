"""PoC용 샘플 전표 100건 생성 (정상 70건 + 이상 30건)"""
import random
from datetime import datetime, timedelta
from models import JournalEntry, JournalLine, Project, ACCOUNT_MASTER, EMPLOYEES, PROJECTS


def init_projects(db):
    """프로젝트 마스터 데이터를 생성한다."""
    projects = []
    for p in PROJECTS:
        proj = Project(**p)
        db.add(proj)
        projects.append(proj)
    db.commit()
    return projects


def generate_sample_data(db):
    """샘플 전표 100건을 생성한다."""
    # 프로젝트 초기화
    projects = init_projects(db)
    # 현장 프로젝트 (본사 공통 제외)
    site_projects = [p for p in projects if p.code != "PJ-COMMON"]
    common_project = [p for p in projects if p.code == "PJ-COMMON"][0]

    random.seed(42)
    base_date = datetime(2026, 5, 1)
    doc_counter = 1

    entries = []

    # ── 정상 전표 70건 ──
    normal_patterns = [
        # (적요, 차변계정, 대변계정, 금액범위, 전표유형)
        ("자재 구매 - 철근", "5010", "2010", (500_000, 50_000_000), "일반전표"),
        ("자재 구매 - 시멘트", "5010", "2010", (300_000, 30_000_000), "일반전표"),
        ("자재 구매 - 레미콘", "5010", "2010", (1_000_000, 80_000_000), "일반전표"),
        ("외주비 - 철근 시공", "5030", "2010", (5_000_000, 90_000_000), "일반전표"),
        ("외주비 - 전기 배관", "5030", "2010", (3_000_000, 50_000_000), "일반전표"),
        ("외주비 - 도장 공사", "5030", "2010", (2_000_000, 30_000_000), "일반전표"),
        ("노무비 지급 - 현장직", "5020", "2030", (2_000_000, 40_000_000), "일반전표"),
        ("노무비 지급 - 일용직", "5020", "1020", (500_000, 10_000_000), "일반전표"),
        ("장비 렌탈료 - 타워크레인", "5070", "2030", (3_000_000, 20_000_000), "일반전표"),
        ("장비 렌탈료 - 포클레인", "5070", "2030", (1_000_000, 8_000_000), "일반전표"),
        ("안전관리비 지출", "5060", "1020", (500_000, 5_000_000), "일반전표"),
        ("산재보험료 납부", "5050", "1020", (1_000_000, 10_000_000), "일반전표"),
        ("설계용역비", "5080", "2030", (5_000_000, 50_000_000), "일반전표"),
        ("공사수익 인식", "1130", "4010", (50_000_000, 500_000_000), "일반전표"),
        ("공사 선수금 수령", "1020", "2060", (10_000_000, 200_000_000), "일반전표"),
        ("급여 지급", "6010", "1020", (3_000_000, 15_000_000), "일반전표"),
        ("복리후생비", "6030", "1020", (100_000, 3_000_000), "일반전표"),
        ("여비교통비", "6040", "1010", (50_000, 500_000), "일반전표"),
        ("소모품 구입", "6170", "1020", (10_000, 500_000), "일반전표"),
        ("통신비 납부", "6050", "1020", (50_000, 300_000), "일반전표"),
        ("임차료 지급", "6090", "1020", (1_000_000, 10_000_000), "일반전표"),
        ("수도광열비", "6060", "1020", (100_000, 2_000_000), "일반전표"),
        ("보험료 납부", "6110", "1020", (500_000, 5_000_000), "일반전표"),
        ("매입금 지급", "2010", "1020", (1_000_000, 80_000_000), "일반전표"),
    ]

    for i in range(70):
        pattern = random.choice(normal_patterns)
        desc, debit_acct, credit_acct, (min_amt, max_amt), doc_type = pattern

        amount = round(random.randint(min_amt, max_amt), -3)  # 천원 단위 반올림
        date = base_date + timedelta(days=random.randint(0, 30))
        # 주말 피하기 (정상 전표)
        while date.weekday() >= 5:
            date += timedelta(days=1)

        emp_name, emp_dept = random.choice(EMPLOYEES)
        # 공사원가(5xxx)는 현장 프로젝트, 판관비(6xxx)는 본사 공통
        if debit_acct.startswith("5") or debit_acct in ("1130",):
            proj = random.choice(site_projects)
        else:
            proj = random.choice([common_project] + site_projects)

        entry = JournalEntry(
            doc_no=f"JE-2026-{doc_counter:04d}",
            doc_date=date.strftime("%Y-%m-%d"),
            doc_type=doc_type,
            description=desc,
            created_by=emp_name,
            department=emp_dept,
            project_id=proj.id,
            status="제출",
            total_debit=amount,
            total_credit=amount,
        )
        entry.lines = [
            JournalLine(
                line_no=1,
                account_code=debit_acct,
                account_name=ACCOUNT_MASTER.get(debit_acct, ""),
                debit_amount=amount,
                credit_amount=0,
                description=desc,
            ),
            JournalLine(
                line_no=2,
                account_code=credit_acct,
                account_name=ACCOUNT_MASTER.get(credit_acct, ""),
                debit_amount=0,
                credit_amount=amount,
                description=desc,
            ),
        ]
        entries.append(entry)
        doc_counter += 1

    # ── 이상 전표 30건 ──

    # E001: 차대변 불일치 (5건)
    for i in range(5):
        amount = round(random.randint(1_000_000, 50_000_000), -3)
        diff = random.choice([1000, -1000, 5000, -5000, 100])
        date = base_date + timedelta(days=random.randint(0, 30))
        emp_name, emp_dept = random.choice(EMPLOYEES)

        entry = JournalEntry(
            doc_no=f"JE-2026-{doc_counter:04d}",
            doc_date=date.strftime("%Y-%m-%d"),
            doc_type="일반전표",
            description="자재 구매 - 배관자재",
            created_by=emp_name,
            department=emp_dept,
            status="제출",
            total_debit=amount,
            total_credit=amount + diff,
        )
        entry.lines = [
            JournalLine(line_no=1, account_code="5010", account_name="자재비",
                        debit_amount=amount, credit_amount=0, description="자재 구매"),
            JournalLine(line_no=2, account_code="2010", account_name="외상매입금",
                        debit_amount=0, credit_amount=amount + diff, description="자재 구매"),
        ]
        entries.append(entry)
        doc_counter += 1

    # E004: 고액 이상 전표 (5건)
    for i in range(5):
        amount = random.randint(150_000_000, 900_000_000)
        date = base_date + timedelta(days=random.randint(0, 30))
        emp_name, emp_dept = random.choice(EMPLOYEES)

        entry = JournalEntry(
            doc_no=f"JE-2026-{doc_counter:04d}",
            doc_date=date.strftime("%Y-%m-%d"),
            doc_type="수기전표",
            description="특별 외주비 정산",
            created_by=emp_name,
            department=emp_dept,
            status="제출",
            total_debit=amount,
            total_credit=amount,
        )
        entry.lines = [
            JournalLine(line_no=1, account_code="5030", account_name="외주비",
                        debit_amount=amount, credit_amount=0, description="특별 외주비"),
            JournalLine(line_no=2, account_code="2010", account_name="외상매입금",
                        debit_amount=0, credit_amount=amount, description="특별 외주비"),
        ]
        entries.append(entry)
        doc_counter += 1

    # E005: 주말 기표 (3건)
    for i in range(3):
        amount = round(random.randint(1_000_000, 30_000_000), -3)
        date = base_date + timedelta(days=random.randint(0, 30))
        # 강제로 주말로 설정
        while date.weekday() < 5:
            date += timedelta(days=1)
        emp_name, emp_dept = random.choice(EMPLOYEES)

        entry = JournalEntry(
            doc_no=f"JE-2026-{doc_counter:04d}",
            doc_date=date.strftime("%Y-%m-%d"),
            doc_type="일반전표",
            description="긴급 자재 구매",
            created_by=emp_name,
            department=emp_dept,
            status="제출",
            total_debit=amount,
            total_credit=amount,
        )
        entry.lines = [
            JournalLine(line_no=1, account_code="5010", account_name="자재비",
                        debit_amount=amount, credit_amount=0, description="긴급 자재"),
            JournalLine(line_no=2, account_code="1020", account_name="보통예금",
                        debit_amount=0, credit_amount=amount, description="긴급 자재"),
        ]
        entries.append(entry)
        doc_counter += 1

    # E008: 비인가 계정 조합 (5건) - 부적절한 차대변 매칭
    invalid_pairs = [
        ("6120", "1310", "접대비를 토지로 기표", "접대비 계정 오류"),
        ("5020", "4010", "노무비를 공사수익으로 상계", "노무비-수익 부적절 상계"),
        ("6010", "1130", "급여를 공사미수금으로 기표", "급여 계정 착오"),
        ("5010", "3030", "자재비를 이익잉여금으로 기표", "자재비 상대계정 오류"),
        ("6040", "2130", "여비교통비를 퇴직급여충당부채로 기표", "여비교통비 계정 착오"),
    ]
    for debit_acct, credit_acct, desc, summary in invalid_pairs:
        amount = round(random.randint(500_000, 10_000_000), -3)
        date = base_date + timedelta(days=random.randint(0, 30))
        emp_name, emp_dept = random.choice(EMPLOYEES)

        entry = JournalEntry(
            doc_no=f"JE-2026-{doc_counter:04d}",
            doc_date=date.strftime("%Y-%m-%d"),
            doc_type="수기전표",
            description=desc,
            created_by=emp_name,
            department=emp_dept,
            status="제출",
            total_debit=amount,
            total_credit=amount,
        )
        entry.lines = [
            JournalLine(line_no=1, account_code=debit_acct,
                        account_name=ACCOUNT_MASTER.get(debit_acct, debit_acct),
                        debit_amount=amount, credit_amount=0, description=summary),
            JournalLine(line_no=2, account_code=credit_acct,
                        account_name=ACCOUNT_MASTER.get(credit_acct, credit_acct),
                        debit_amount=0, credit_amount=amount, description=summary),
        ]
        entries.append(entry)
        doc_counter += 1

    # E003: 중복 전표 (4건 = 2쌍)
    for pair_idx in range(2):
        amount = round(random.randint(5_000_000, 30_000_000), -3)
        date = base_date + timedelta(days=random.randint(0, 15))
        emp_name, emp_dept = random.choice(EMPLOYEES)
        desc = f"외주비 지급 - {'도장공사' if pair_idx == 0 else '전기공사'}"

        for dup in range(2):
            entry = JournalEntry(
                doc_no=f"JE-2026-{doc_counter:04d}",
                doc_date=date.strftime("%Y-%m-%d"),
                doc_type="일반전표",
                description=desc,
                created_by=emp_name,
                department=emp_dept,
                status="제출",
                total_debit=amount,
                total_credit=amount,
            )
            entry.lines = [
                JournalLine(line_no=1, account_code="5030", account_name="외주비",
                            debit_amount=amount, credit_amount=0, description=desc),
                JournalLine(line_no=2, account_code="2010", account_name="외상매입금",
                            debit_amount=0, credit_amount=amount, description=desc),
            ]
            entries.append(entry)
            doc_counter += 1

    # E006: 역분개 전표 (3건)
    for i in range(3):
        amount = round(random.randint(1_000_000, 20_000_000), -3)
        date = base_date + timedelta(days=random.randint(15, 30))
        emp_name, emp_dept = random.choice(EMPLOYEES)

        entry = JournalEntry(
            doc_no=f"JE-2026-{doc_counter:04d}",
            doc_date=date.strftime("%Y-%m-%d"),
            doc_type="역분개전표",
            description=f"역분개 - 자재비 수정 ({i+1}차)",
            created_by=emp_name,
            department=emp_dept,
            status="제출",
            total_debit=amount,
            total_credit=amount,
        )
        entry.lines = [
            JournalLine(line_no=1, account_code="2010", account_name="외상매입금",
                        debit_amount=amount, credit_amount=0, description="역분개"),
            JournalLine(line_no=2, account_code="5010", account_name="자재비",
                        debit_amount=0, credit_amount=amount, description="역분개"),
        ]
        entries.append(entry)
        doc_counter += 1

    # E010: 단수 금액 (1건)
    entry = JournalEntry(
        doc_no=f"JE-2026-{doc_counter:04d}",
        doc_date=(base_date + timedelta(days=10)).strftime("%Y-%m-%d"),
        doc_type="일반전표",
        description="소모품 구입",
        created_by="김건설",
        department="공사1팀",
        status="제출",
        total_debit=1_234_567,
        total_credit=1_234_567,
    )
    entry.lines = [
        JournalLine(line_no=1, account_code="6170", account_name="소모품비",
                    debit_amount=1_234_567, credit_amount=0, description="소모품"),
        JournalLine(line_no=2, account_code="1020", account_name="보통예금",
                    debit_amount=0, credit_amount=1_234_567, description="소모품"),
    ]
    entries.append(entry)
    doc_counter += 1

    # E009: 월말 대량 기표 (2건)
    for i in range(2):
        amount = round(random.randint(5_000_000, 80_000_000), -3)
        date = datetime(2026, 5, 31)
        emp_name, emp_dept = random.choice(EMPLOYEES)

        entry = JournalEntry(
            doc_no=f"JE-2026-{doc_counter:04d}",
            doc_date=date.strftime("%Y-%m-%d"),
            doc_type="결산전표",
            description=f"월말 결산 조정 ({i+1})",
            created_by=emp_name,
            department="재무회계팀",
            status="제출",
            total_debit=amount,
            total_credit=amount,
        )
        entry.lines = [
            JournalLine(line_no=1, account_code="5040", account_name="경비",
                        debit_amount=amount, credit_amount=0, description="결산 조정"),
            JournalLine(line_no=2, account_code="2030", account_name="미지급금",
                        debit_amount=0, credit_amount=amount, description="결산 조정"),
        ]
        entries.append(entry)
        doc_counter += 1

    # 프로젝트 미할당 이상 전표에 랜덤 프로젝트 할당
    for entry in entries:
        if entry.project_id is None:
            entry.project_id = random.choice(site_projects).id
        db.add(entry)
    db.commit()

    # 증빙 이미지 생성 및 첨부
    try:
        from generate_receipts import generate_all_receipts
        entries_info = [
            {"doc_no": e.doc_no, "amount": int(e.total_debit), "date": e.doc_date, "description": e.description, "doc_type": e.doc_type}
            for e in entries
        ]
        receipt_paths = generate_all_receipts(entries_info)
        for entry in entries:
            if entry.doc_no in receipt_paths:
                entry.receipt_image = receipt_paths[entry.doc_no]
        db.commit()
        print(f"[FDS] 증빙 이미지 {len(receipt_paths)}건 생성 및 첨부 완료")
    except Exception as e:
        print(f"[FDS] 증빙 이미지 생성 건너뜀: {e}")

    return len(entries)
