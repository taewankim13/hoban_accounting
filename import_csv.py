"""호반건설 실제 CSV 전표 데이터를 DB에 임포트한다. hoban_data_1 / hoban_data_2 형식 모두 지원."""
import csv
import collections
import os
import re
from datetime import datetime
from database import engine, SessionLocal, Base
from models import JournalEntry, JournalLine, Project, Evidence, LinkedDocument


def detect_format(header: list[str]) -> str:
    """CSV 헤더를 보고 데이터 형식을 판별한다."""
    col0 = header[0].strip().replace('\ufeff', '')
    if col0 == '회계연도':
        return 'v1'
    elif col0 == '거래번호':
        return 'v2'
    raise ValueError(f"알 수 없는 CSV 형식: 첫 번째 컬럼이 '{col0}'입니다.")


def fmt_date(raw: str) -> str:
    """YYYYMMDD → YYYY-MM-DD 변환"""
    raw = raw.strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def extract_site_name(text: str) -> str | None:
    """문서번호/기안문서번호에서 현장명을 추출한다."""
    if not text or text == 'NULL':
        return None
    text = text.strip()
    if '-' in text:
        name = text.split('-')[0].strip()
        if name and len(name) >= 2:
            return name
    return None


def safe(val, default=''):
    """NULL 문자열을 빈 문자열로 변환"""
    if val is None:
        return default
    v = str(val).strip()
    return default if v == 'NULL' or v == '' else v


def import_hoban_csv(csv_path: str):
    """CSV 파일을 읽어 DB에 임포트한다."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # 기존 데이터 전체 삭제
    db.query(Evidence).delete()
    db.query(LinkedDocument).delete()
    db.query(JournalLine).delete()
    db.query(JournalEntry).delete()
    db.query(Project).delete()
    db.commit()
    print("[임포트] 기존 데이터 삭제 완료")

    # CSV 읽기
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"[임포트] CSV 읽기 완료: {len(rows)}행")

    # 형식 판별
    header = list(rows[0].keys())
    fmt = detect_format(header)
    print(f"[임포트] 데이터 형식: {fmt}")

    if fmt == 'v1':
        import_v1(db, rows)
    elif fmt == 'v2':
        import_v2(db, rows)

    db.close()


def load_account_master():
    """account_master.json에서 계정과목 매핑을 로드한다."""
    import json as _json
    try:
        with open('account_master.json', 'r', encoding='utf-8') as f:
            return _json.load(f)
    except:
        return {}


def import_v2(db, rows):
    """hoban_data_2.csv 형식 임포트 (거래번호 기반)"""
    acct_master = load_account_master()

    # 중복 컬럼명 문제 해결: 인덱스 기반으로 올바른 계정코드/계정과목명 읽기
    # DictReader는 중복 컬럼의 마지막 값을 사용하므로, 첫 번째 계정코드/계정과목명을 인덱스로 추출
    acct_code_fix = {}
    acct_name_fix = {}
    try:
        csv_path_candidates = ['hoban_data_4.csv', 'hoban_data_3.csv', 'hoban_data_2.csv']
        for cp in csv_path_candidates:
            if os.path.exists(cp):
                import csv as _csv
                with open(cp, 'r', encoding='utf-8-sig') as _f:
                    reader = _csv.reader(_f)
                    header = next(reader)
                    acct_idx = None
                    acct_name_idx = None
                    slip_idx = None
                    for i, h in enumerate(header):
                        if h.strip() == '계정코드' and acct_idx is None:
                            acct_idx = i
                        if h.strip() == '계정과목명' and acct_name_idx is None:
                            acct_name_idx = i
                        if h.strip() == '전표번호' and slip_idx is None:
                            slip_idx = i
                    if acct_idx is not None and slip_idx is not None:
                        for data_row in reader:
                            if len(data_row) > max(acct_idx, slip_idx):
                                slip_no = data_row[slip_idx].strip()
                                acct_code = data_row[acct_idx].strip()
                                if slip_no and acct_code and acct_code != 'NULL':
                                    acct_code_fix[slip_no] = acct_code
                                if acct_name_idx is not None and len(data_row) > acct_name_idx:
                                    acct_name = data_row[acct_name_idx].strip()
                                    if slip_no and acct_name and acct_name != 'NULL':
                                        acct_name_fix[slip_no] = acct_name
                        print(f"[임포트] 계정코드 인덱스 매핑: {len(acct_code_fix)}건 (col[{acct_idx}])")
                        if acct_name_idx is not None:
                            print(f"[임포트] 계정과목명 인덱스 매핑: {len(acct_name_fix)}건 (col[{acct_name_idx}])")
                break
    except Exception as e:
        print(f"[임포트] 계정코드 매핑 실패: {e}")

    # 거래번호별 그루핑
    grouped = collections.OrderedDict()
    for row in rows:
        doc_no = safe(row.get('거래번호'))
        if not doc_no:
            continue
        if doc_no not in grouped:
            grouped[doc_no] = []
        grouped[doc_no].append(row)
    print(f"[임포트] 전표 {len(grouped)}건 식별")

    # 문서번호에서 현장명 추출 → 프로젝트 생성
    site_names = set()
    for row in rows:
        site = extract_site_name(safe(row.get('문서번호')))
        if site:
            site_names.add(site)

    common_proj = Project(code="PJ-COMMON", name="본사 공통", location="서울 본사", status="진행중")
    db.add(common_proj)
    db.flush()

    project_map = {}
    for i, site in enumerate(sorted(site_names)):
        proj = Project(code=f"PJ-{i+1:03d}", name=site, status="진행중")
        db.add(proj)
        db.flush()
        project_map[site] = proj
    db.commit()
    print(f"[임포트] 프로젝트 {len(project_map)+1}건 생성")

    # 전표 임포트
    count = 0
    for doc_no, line_rows in grouped.items():
        first = line_rows[0]

        # 프로젝트 매핑
        project_id = common_proj.id
        site = extract_site_name(safe(first.get('문서번호')))
        if site and site in project_map:
            project_id = project_map[site].id

        # 금액 집계
        total_debit = 0
        total_credit = 0
        for lr in line_rows:
            side = safe(lr.get('차대구분'))
            amt = float(safe(lr.get('회계금액'), '0') or 0)
            if side == 'D':
                total_debit += amt
            elif side == 'C':
                total_credit += amt

        # 승인 상태 매핑
        approval = safe(first.get('승인여부'))
        reject_state = safe(first.get('반려상태(1 정상, 2 반려, 3 수정완료)'))
        if reject_state == '2':
            status = '반려'
        elif approval == 'Y':
            status = '검토완료'
        else:
            status = '제출'

        # 전표유형 매핑
        raw_type = safe(first.get('전표유형(대체전표)'))
        doc_type_map = {'C': '대체전표', 'T': '이체전표', 'P': '매입전표', 'S': '매출전표', 'R': '입금전표', 'J': '출금전표'}
        doc_type = doc_type_map.get(raw_type, raw_type or '미분류')

        # 입력일자
        input_date_raw = safe(first.get('입력일자'))
        input_datetime = ''
        if input_date_raw:
            try:
                # Excel serial date 또는 날짜 문자열
                if '.' in input_date_raw and len(input_date_raw) < 15:
                    pass  # serial number, skip
                else:
                    input_datetime = input_date_raw
            except:
                pass

        entry = JournalEntry(
            doc_no=doc_no,
            doc_date=fmt_date(safe(first.get('회계일자'), '')),
            fiscal_year='2026',
            doc_month=fmt_date(safe(first.get('회계일자'), ''))[:7].split('-')[-1] if safe(first.get('회계일자')) else '',
            doc_type=doc_type,
            category='',
            big_category='',
            description=(safe(first.get('적요', '')) or safe(first.get('비고', '')))[:500],
            created_by=safe(first.get('입력자')),
            input_datetime=input_datetime,
            modified_datetime=safe(first.get('수정일자')),
            department=safe(first.get('귀속부서')),
            department_code=safe(first.get('귀속부서')),
            biz_unit=safe(first.get('발행부서')),
            project_id=project_id,
            project_code_raw='',
            project_name_raw=safe(first.get('문서번호')),
            status=status,
            designation_no=safe(first.get('합병번호')),
            evidence_type=safe(first.get('징빙미비구분')),
            evidence_date=fmt_date(safe(first.get('발행일자'), '')),
            draft_doc_no=safe(first.get('문서번호')),
            total_debit=total_debit,
            total_credit=total_credit,
        )

        for lr in line_rows:
            side_raw = safe(lr.get('차대구분'))
            side = '차변' if side_raw == 'D' else '대변' if side_raw == 'C' else side_raw
            amt = float(safe(lr.get('회계금액'), '0') or 0)

            # 계정코드/과목명: 전표번호 기반 인덱스 매핑 우선, DictReader 폴백
            slip_no = safe(lr.get('전표번호'))
            raw_acct = acct_code_fix.get(slip_no, '') or safe(lr.get('계정코드'))
            raw_acct_name = acct_name_fix.get(slip_no, '') or acct_master.get(raw_acct, raw_acct)

            line_desc = safe(lr.get('적요', '')) or safe(lr.get('비고', ''))

            line = JournalLine(
                line_no=int(safe(lr.get('전표조회순서'), '0') or 0),
                side=side,
                account_code=raw_acct,
                account_name=raw_acct_name,
                debit_amount=amt if side_raw == 'D' else 0,
                credit_amount=amt if side_raw == 'C' else 0,
                description=line_desc[:500],
                vendor_code=safe(lr.get('거래처코드')),
                vendor_type=safe(lr.get('거래처유형')),
                vendor_name=safe(lr.get('거래처명칭')),
                biz_no='',
            )
            entry.lines.append(line)

        db.add(entry)
        count += 1
        if count % 500 == 0:
            db.commit()
            print(f"[임포트] {count}/{len(grouped)} 진행중...")

    db.commit()
    print(f"[임포트] 전표 {count}건 임포트 완료")
    return count


def import_v1(db, rows):
    """hoban_data_1.csv 형식 임포트 (회계연도 기반) - 기존 로직"""

    grouped = collections.OrderedDict()
    for row in rows:
        doc_no = row["전표번호"].strip()
        if doc_no not in grouped:
            grouped[doc_no] = []
        grouped[doc_no].append(row)
    print(f"[임포트] 전표 {len(grouped)}건 식별")

    site_names = set()
    for row in rows:
        site = extract_site_name(safe(row.get('기안문서번호')))
        if site:
            site_names.add(site)

    common_proj = Project(code="PJ-COMMON", name="본사 공통", location="서울 본사", status="진행중")
    db.add(common_proj)
    db.flush()

    project_map = {}
    for i, site in enumerate(sorted(site_names)):
        proj = Project(code=f"PJ-{i+1:03d}", name=site, status="진행중")
        db.add(proj)
        db.flush()
        project_map[site] = proj
    db.commit()
    print(f"[임포트] 프로젝트 {len(project_map)+1}건 생성")

    count = 0
    for doc_no, line_rows in grouped.items():
        first = line_rows[0]

        raw_date = first["전표일자"].strip()
        doc_date = fmt_date(raw_date)

        project_id = common_proj.id
        site = extract_site_name(safe(first.get('기안문서번호')))
        if site and site in project_map:
            project_id = project_map[site].id

        entry = JournalEntry(
            doc_no=doc_no,
            doc_date=doc_date,
            fiscal_year=safe(first.get("회계연도")),
            doc_month=safe(first.get("전표월")),
            doc_type=safe(first.get("전표유형")),
            category=safe(first.get("구분")),
            big_category=safe(first.get("대분류")),
            mid_category=safe(first.get("중분류")),
            small_category=safe(first.get("소분류")),
            description=safe(first.get("적요"))[:500],
            description2=safe(first.get("적요2"))[:500] or None,
            created_by=safe(first.get("입력자")),
            input_datetime=safe(first.get("입력일시")),
            modified_datetime=safe(first.get("최종수정일시")),
            department=safe(first.get("손익부서명")) or None,
            department_code=safe(first.get("손익부서코드")) or None,
            biz_unit=safe(first.get("사업부구분명")) or None,
            biz_unit_code=safe(first.get("사업부구분코드")) or None,
            cost_center=safe(first.get("코스트센터명")) or None,
            cost_center_code=safe(first.get("코스트센터코드")) or None,
            project_id=project_id,
            project_code_raw=safe(first.get("프로젝트코드")) or None,
            project_name_raw=safe(first.get("프로젝트명")) or None,
            status="제출",
            designation_no=safe(first.get("지정번호")) or None,
            object_key=safe(first.get("오브젝트키")) or None,
            evidence_type=safe(first.get("증빙구분")) or None,
            evidence_date=safe(first.get("증빙일자")) or None,
            draft_doc_no=safe(first.get("기안문서번호")) or None,
            func_area=safe(first.get("기능영역명")) or None,
            total_debit=0, total_credit=0,
        )

        for lr in line_rows:
            debit = float(safe(lr.get("차변금액"), '0') or 0)
            credit = float(safe(lr.get("대변금액"), '0') or 0)
            line = JournalLine(
                line_no=int(safe(lr.get("전표일련번호"), '0') or 0),
                side=safe(lr.get("차대구분")),
                account_code=safe(lr.get("계정코드")),
                account_name=safe(lr.get("계정과목명")),
                debit_amount=debit,
                credit_amount=credit,
                description=safe(lr.get("적요"))[:500],
                vendor_code=safe(lr.get("거래처코드")) or None,
                vendor_type=safe(lr.get("거래처구분")) or None,
                vendor_name=safe(lr.get("상호")) or None,
                biz_no=safe(lr.get("사업자번호")) or None,
            )
            entry.lines.append(line)

        entry.total_debit = sum(l.debit_amount for l in entry.lines)
        entry.total_credit = sum(l.credit_amount for l in entry.lines)

        db.add(entry)
        count += 1
        if count % 500 == 0:
            db.commit()
            print(f"[임포트] {count}/{len(grouped)} 진행중...")

    db.commit()
    print(f"[임포트] 전표 {count}건 임포트 완료")
    return count


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "hoban_data_4.csv"
    import_hoban_csv(path)
