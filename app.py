"""전표 이상탐지 FDS 웹 애플리케이션 - 호반건설 실제 데이터 기반"""
import os
import uuid
from datetime import datetime
from fastapi import FastAPI, Request, Depends, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from database import engine, get_db, Base
from models import JournalEntry, JournalLine, Project, Evidence, LinkedDocument, SavedRule, DEPARTMENTS, EMPLOYEES
from ai_engine import analyze_journal
from receipt_parser import parse_receipt_image
import json as _json

def load_balance_sides():
    """account_balance_side.json 로드: {계정코드: '차변'|'대변'}"""
    try:
        with open('account_balance_side.json', 'r', encoding='utf-8') as f:
            return _json.load(f)
    except:
        return {}

# DB 테이블 생성
Base.metadata.create_all(bind=engine)

app = FastAPI(title="호반건설 전표 이상탐지 FDS")

os.makedirs("static/css", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/uploads/evidences", exist_ok=True)
os.makedirs("static/uploads/linked_docs", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def startup():
    db = next(get_db())
    count = db.query(JournalEntry).count()
    if count == 0:
        # CSV 실제 데이터 임포트 (hoban_data_2 우선, 없으면 hoban_data_1)
        csv_path = "hoban_data_2.csv" if os.path.exists("hoban_data_2.csv") else "hoban_data_1.csv"
        if os.path.exists(csv_path):
            from import_csv import import_hoban_csv
            import_hoban_csv(csv_path)
            db2 = next(get_db())
            run_ai_analysis(db2)
            db2.close()
            print("[FDS] AI 분석 완료")
        else:
            print("[FDS] hoban_data_1.csv 파일이 없습니다")
    db.close()


def run_ai_analysis(db: Session):
    """모든 전표에 대해 룰 엔진 기반 AI 분석을 실행한다."""
    import collections
    from rule_engine import load_rules, apply_rules_to_journal

    rules = load_rules()
    journals = db.query(JournalEntry).options(
        joinedload(JournalEntry.lines),
        joinedload(JournalEntry.evidences),
        joinedload(JournalEntry.linked_docs),
    ).all()

    # 거래처별 최빈 계정 패턴 맵 빌드 (E015 룰용)
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

    # 중복 전표 맵 빌드 (E003 룰용)
    from collections import defaultdict
    dup_key_map = defaultdict(list)
    for j in journals:
        acct_set = frozenset((l.account_code, l.debit_amount, l.credit_amount) for l in j.lines)
        vendors = frozenset(l.vendor_name for l in j.lines if l.vendor_name)
        key = (j.doc_date, j.total_debit, acct_set, vendors)
        dup_key_map[key].append(j.doc_no)
    # doc_no → key 맵으로 변환
    dup_map = {}
    for key, doc_nos in dup_key_map.items():
        if len(doc_nos) >= 2:
            dup_map[key] = doc_nos

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
    db.commit()
    h = sum(1 for j in journals if j.ai_risk_level == "High")
    m = sum(1 for j in journals if j.ai_risk_level == "Medium")
    l = sum(1 for j in journals if j.ai_risk_level == "Low")
    ok = sum(1 for j in journals if j.ai_risk_level == "정상")
    print(f"[FDS] AI 분석 완료: {len(journals)}건 (H:{h} M:{m} L:{l} 정상:{ok})")


# ──────────────────────────────────
# 대시보드
# ──────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    total = db.query(JournalEntry).count()
    high = db.query(JournalEntry).filter(JournalEntry.ai_risk_level == "High").count()
    medium = db.query(JournalEntry).filter(JournalEntry.ai_risk_level == "Medium").count()
    low = db.query(JournalEntry).filter(JournalEntry.ai_risk_level == "Low").count()
    normal = db.query(JournalEntry).filter(JournalEntry.ai_risk_level == "정상").count()

    projects = db.query(Project).all()
    project_stats = []
    for p in projects:
        p_total = db.query(JournalEntry).filter(JournalEntry.project_id == p.id).count()
        p_high = db.query(JournalEntry).filter(JournalEntry.project_id == p.id, JournalEntry.ai_risk_level == "High").count()
        p_amount = db.query(func.coalesce(func.sum(JournalEntry.total_debit), 0)).filter(JournalEntry.project_id == p.id).scalar()
        if p_total > 0:
            project_stats.append({"code": p.code, "name": p.name, "total": p_total, "high": p_high, "amount": p_amount})

    # 전표유형별 통계
    doc_types = db.query(JournalEntry.doc_type, func.count()).group_by(JournalEntry.doc_type).all()
    type_stats = [{"name": t or "미분류", "count": c} for t, c in doc_types if c > 0]

    return templates.TemplateResponse(request, "home.html", {
        "total": total, "high": high, "medium": medium, "low": low, "normal": normal,
        "project_stats": sorted(project_stats, key=lambda x: x["total"], reverse=True),
        "type_stats": sorted(type_stats, key=lambda x: x["count"], reverse=True),
    })


# ──────────────────────────────────
# 전표 생성
# ──────────────────────────────────
@app.get("/create", response_class=HTMLResponse)
def create_page(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).filter(Project.status == "진행중").all()
    # 실제 데이터에서 계정 마스터 추출
    accounts_raw = db.query(JournalLine.account_code, JournalLine.account_name).distinct().all()
    accounts = {code: name for code, name in accounts_raw if code}
    return templates.TemplateResponse(request, "create.html", {
        "accounts": accounts,
        "departments": DEPARTMENTS,
        "employees": EMPLOYEES,
        "projects": projects,
    })


@app.post("/api/chat", response_class=JSONResponse)
async def chat_create(request: Request):
    """대화형 전표 어시스턴트 (Claude API 또는 로컬 파서)"""
    data = await request.json()
    message = data.get("message", "")
    history = data.get("history", [])
    current_form = data.get("current_form", None)

    from llm_chat import process_chat, HAS_CLAUDE
    result = process_chat(message, history, current_form)
    result["llm_mode"] = "claude" if HAS_CLAUDE else "local"
    return result


@app.post("/api/receipt", response_class=JSONResponse)
async def upload_receipt(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1] or ".jpg"
    saved_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join("static", "uploads", saved_name)
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)
    print(f"[OCR] 영수증 업로드: {file.filename} → {save_path} ({len(content)} bytes)")
    try:
        result = parse_receipt_image(save_path, file.filename)
        result["image_url"] = f"/static/uploads/{saved_name}"
        print(f"[OCR] 결과: mode={result.get('ocr_mode')}, amount={result.get('amount')}, vendor={result.get('vendor')}")
        return result
    except Exception as e:
        print(f"[OCR] 오류: {e}")
        return {"success": False, "error": str(e), "image_url": f"/static/uploads/{saved_name}"}


@app.post("/api/journal", response_class=JSONResponse)
async def create_journal(request: Request, db: Session = Depends(get_db)):
    request_data = await request.json()
    last = db.query(JournalEntry).order_by(JournalEntry.id.desc()).first()
    next_no = (last.id + 1) if last else 1

    entry = JournalEntry(
        doc_no=f"JE-2026-{next_no:04d}",
        doc_date=request_data.get("doc_date", datetime.now().strftime("%Y-%m-%d")),
        fiscal_year="2026",
        doc_type=request_data.get("doc_type", "수기전표"),
        category=request_data.get("category", ""),
        big_category=request_data.get("big_category", ""),
        description=request_data.get("description", ""),
        created_by=request_data.get("created_by", ""),
        department=request_data.get("department", ""),
        project_id=request_data.get("project_id") or None,
        receipt_image=request_data.get("receipt_image", None),
        ocr_date=request_data.get("ocr_date", None),
        ocr_vendor=request_data.get("ocr_vendor", None),
        ocr_amount=float(request_data["ocr_amount"]) if request_data.get("ocr_amount") else None,
        ocr_raw=request_data.get("ocr_raw", None),
        evidence_type=request_data.get("evidence_type", ""),
        status="제출",
        total_debit=0, total_credit=0,
    )

    for i, ld in enumerate(request_data.get("lines", [])):
        line = JournalLine(
            line_no=i + 1,
            side=ld.get("side", "차변" if float(ld.get("debit_amount", 0)) > 0 else "대변"),
            account_code=ld["account_code"],
            account_name=ld.get("account_name", ""),
            debit_amount=float(ld.get("debit_amount", 0)),
            credit_amount=float(ld.get("credit_amount", 0)),
            description=ld.get("description", ""),
            vendor_name=ld.get("vendor_name", ""),
            vendor_type=ld.get("vendor_type", ""),
        )
        entry.lines.append(line)

    entry.total_debit = sum(l.debit_amount for l in entry.lines)
    entry.total_credit = sum(l.credit_amount for l in entry.lines)

    db.add(entry)
    db.commit()
    db.refresh(entry)

    all_journals = db.query(JournalEntry).options(joinedload(JournalEntry.lines)).all()
    result = analyze_journal(entry, all_journals)
    entry.ai_risk_level = result["risk_level"]
    entry.ai_risk_score = result["risk_score"]
    entry.ai_error_codes = ",".join(result["error_codes"]) if result["error_codes"] else None
    entry.ai_reason = "\n".join(result["reasons"]) if result["reasons"] else None
    entry.ai_recommendation = "\n".join(result["recommendations"]) if result["recommendations"] else None
    entry.ai_analyzed_at = datetime.now()
    db.commit()

    return {"success": True, "doc_no": entry.doc_no, "ai_result": result}


# ──────────────────────────────────
# 전표 검토
# ──────────────────────────────────
@app.get("/review", response_class=HTMLResponse)
def review_page(request: Request, risk: str = None, project: str = None,
                doc_type: str = None, error_code: str = None,
                vendor_type: str = None, search: str = None,
                search_field: str = None,
                page: int = 1, db: Session = Depends(get_db)):
    per_page = 50
    query = db.query(JournalEntry).options(joinedload(JournalEntry.lines), joinedload(JournalEntry.project))

    if risk and risk != "all":
        query = query.filter(JournalEntry.ai_risk_level == risk)
    if project and project != "all":
        query = query.join(Project).filter(Project.code == project)
    if doc_type and doc_type != "all":
        query = query.filter(JournalEntry.doc_type == doc_type)
    if vendor_type and vendor_type != "all":
        query = query.join(JournalLine).filter(JournalLine.vendor_type == vendor_type).distinct()
    if search and search.strip():
        kw = f"%{search.strip()}%"
        sf = (search_field or "").strip()
        if sf == "doc_no":
            query = query.filter(JournalEntry.doc_no.like(kw))
        elif sf == "doc_date":
            query = query.filter(JournalEntry.doc_date.like(kw))
        elif sf == "doc_type":
            query = query.filter(JournalEntry.doc_type.like(kw))
        elif sf == "description":
            query = query.filter(JournalEntry.description.like(kw))
        elif sf == "created_by":
            query = query.filter(JournalEntry.created_by.like(kw))
        elif sf == "project":
            if not (project and project != "all"):
                query = query.outerjoin(Project, JournalEntry.project_id == Project.id)
            query = query.filter(Project.name.like(kw) | Project.code.like(kw))
        elif sf == "vendor":
            if not (vendor_type and vendor_type != "all"):
                query = query.join(JournalLine)
            query = query.filter(JournalLine.vendor_name.like(kw)).distinct()
        elif sf == "account":
            if not (vendor_type and vendor_type != "all"):
                query = query.join(JournalLine)
            query = query.filter(
                JournalLine.account_name.like(kw) | JournalLine.account_code.like(kw)
            ).distinct()
        else:
            if not (project and project != "all"):
                query = query.outerjoin(Project, JournalEntry.project_id == Project.id)
            query = query.outerjoin(JournalLine, JournalEntry.id == JournalLine.journal_id)
            query = query.filter(
                JournalEntry.doc_no.like(kw) |
                JournalEntry.doc_date.like(kw) |
                JournalEntry.description.like(kw) |
                JournalEntry.created_by.like(kw) |
                Project.name.like(kw) |
                JournalLine.account_name.like(kw) |
                JournalLine.vendor_name.like(kw)
            ).distinct()
    if error_code and error_code != "all":
        selected_codes = [c.strip() for c in error_code.split(',') if c.strip()]
        for code in selected_codes:
            query = query.filter(
                (JournalEntry.ai_error_codes == code) |
                (JournalEntry.ai_error_codes.like(code + ',%')) |
                (JournalEntry.ai_error_codes.like('%,' + code)) |
                (JournalEntry.ai_error_codes.like('%,' + code + ',%'))
            )

    total_filtered = query.count()
    journals = query.order_by(
        JournalEntry.ai_risk_score.desc().nullslast(),
        JournalEntry.id.desc()
    ).offset((page - 1) * per_page).limit(per_page).all()

    total = db.query(JournalEntry).count()
    high = db.query(JournalEntry).filter(JournalEntry.ai_risk_level == "High").count()
    medium = db.query(JournalEntry).filter(JournalEntry.ai_risk_level == "Medium").count()
    low = db.query(JournalEntry).filter(JournalEntry.ai_risk_level == "Low").count()
    projects = db.query(Project).all()
    doc_types = db.query(JournalEntry.doc_type).distinct().all()
    total_pages = (total_filtered + per_page - 1) // per_page

    # 이상사유별 건수 집계 (rules.json + ERROR_CODES 통합)
    from ai_engine import ERROR_CODES
    from rule_engine import load_rules
    all_rule_defs = load_rules()

    # ERROR_CODES + rules.json 통합
    error_names = {code: info["name"] for code, info in ERROR_CODES.items()}
    error_severity = {code: info["severity"].lower() for code, info in ERROR_CODES.items()}
    for r in all_rule_defs:
        error_names[r["id"]] = r["name"]
        error_severity[r["id"]] = r["severity"].lower()

    # 건수 집계 (정확한 코드 매칭)
    def count_exact_code(code):
        return db.query(JournalEntry).filter(
            (JournalEntry.ai_error_codes == code) |
            (JournalEntry.ai_error_codes.like(code + ',%')) |
            (JournalEntry.ai_error_codes.like('%,' + code)) |
            (JournalEntry.ai_error_codes.like('%,' + code + ',%'))
        ).count()

    error_stats = {}
    all_codes = set(list(ERROR_CODES.keys()) + [r["id"] for r in all_rule_defs])
    for code in sorted(all_codes):
        cnt = count_exact_code(code)
        if cnt > 0:
            name = error_names.get(code, code)
            sev = error_severity.get(code, "low")
            error_stats[code] = {"name": name, "count": cnt, "severity": sev.capitalize()}

    return templates.TemplateResponse(request, "review.html", {
        "journals": journals,
        "current_risk": risk or "all",
        "current_project": project or "all",
        "current_doc_type": doc_type or "all",
        "current_error_code": error_code or "all",
        "selected_error_codes": [c.strip() for c in (error_code or '').split(',') if c.strip() and c.strip() != 'all'],
        "current_vendor_type": vendor_type or "all",
        "current_search": search or "",
        "current_search_field": search_field or "all",
        "current_page": page,
        "total_pages": total_pages,
        "total_filtered": total_filtered,
        "total": total, "high": high, "medium": medium, "low": low,
        "projects": [p for p in projects],
        "doc_types": [dt[0] for dt in doc_types if dt[0]],
        "error_stats": error_stats,
        "error_names": error_names,
        "error_severity": error_severity,
    })


@app.get("/api/journal/{doc_no}", response_class=JSONResponse)
def get_journal(doc_no: str, db: Session = Depends(get_db)):
    journal = db.query(JournalEntry).options(
        joinedload(JournalEntry.lines), joinedload(JournalEntry.project),
        joinedload(JournalEntry.evidences), joinedload(JournalEntry.linked_docs)
    ).filter(JournalEntry.doc_no == doc_no).first()

    if not journal:
        return JSONResponse({"error": "전표를 찾을 수 없습니다."}, status_code=404)

    return {
        "doc_no": journal.doc_no,
        "doc_date": journal.doc_date,
        "fiscal_year": journal.fiscal_year,
        "doc_type": journal.doc_type,
        "category": journal.category,
        "big_category": journal.big_category,
        "mid_category": journal.mid_category,
        "description": journal.description,
        "description2": journal.description2,
        "created_by": journal.created_by,
        "input_datetime": journal.input_datetime,
        "department": journal.department,
        "biz_unit": journal.biz_unit,
        "cost_center": journal.cost_center,
        "project_code": journal.project.code if journal.project else None,
        "project_name": journal.project.name if journal.project else None,
        "status": journal.status,
        "total_debit": journal.total_debit,
        "total_credit": journal.total_credit,
        "receipt_image": journal.receipt_image,
        "ocr_date": journal.ocr_date,
        "ocr_vendor": journal.ocr_vendor,
        "ocr_amount": journal.ocr_amount,
        "evidence_type": journal.evidence_type,
        "evidence_date": journal.evidence_date,
        "draft_doc_no": journal.draft_doc_no,
        "ai_risk_level": journal.ai_risk_level,
        "ai_risk_score": journal.ai_risk_score,
        "ai_error_codes": journal.ai_error_codes.split(",") if journal.ai_error_codes else [],
        "ai_reason": journal.ai_reason,
        "ai_recommendation": journal.ai_recommendation,
        "lines": [
            {
                "line_no": l.line_no, "side": l.side,
                "account_code": l.account_code, "account_name": l.account_name,
                "debit_amount": l.debit_amount, "credit_amount": l.credit_amount,
                "description": l.description,
                "vendor_code": l.vendor_code, "vendor_type": l.vendor_type,
                "vendor_name": l.vendor_name, "biz_no": l.biz_no,
            }
            for l in sorted(journal.lines, key=lambda x: x.line_no)
        ],
        "evidences": [
            {
                "id": e.id, "seq_no": e.seq_no,
                "evidence_type": e.evidence_type,
                "file_name": e.file_name, "file_path": e.file_path,
                "file_ext": e.file_ext, "file_size": e.file_size,
                "parsed_data": _json.loads(e.parsed_data) if e.parsed_data else None,
                "created_at": e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else None,
            }
            for e in sorted(journal.evidences, key=lambda x: x.seq_no)
        ],
        "linked_docs": [
            {
                "id": d.id, "seq_no": d.seq_no,
                "doc_type": d.doc_type,
                "file_name": d.file_name, "file_path": d.file_path,
                "file_ext": d.file_ext, "file_size": d.file_size,
                "parsed_data": _json.loads(d.parsed_data) if d.parsed_data else None,
                "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else None,
            }
            for d in sorted(journal.linked_docs, key=lambda x: x.seq_no)
        ],
    }


@app.post("/api/journal/{doc_no}/reanalyze", response_class=JSONResponse)
def reanalyze_single_journal(doc_no: str, db: Session = Depends(get_db)):
    """단일 전표 재분석 (증빙/연결문서 업로드 후 호출)"""
    import collections
    from rule_engine import load_rules, apply_rules_to_journal

    journal = db.query(JournalEntry).options(
        joinedload(JournalEntry.lines),
        joinedload(JournalEntry.evidences),
        joinedload(JournalEntry.linked_docs),
    ).filter(JournalEntry.doc_no == doc_no).first()
    if not journal:
        return JSONResponse({"error": "전표를 찾을 수 없습니다."}, status_code=404)

    rules = load_rules()

    vendor_acct_counts = collections.defaultdict(lambda: collections.Counter())
    all_journals = db.query(JournalEntry).options(joinedload(JournalEntry.lines)).all()
    for j in all_journals:
        for line in j.lines:
            vname = (line.vendor_name or "").strip()
            acct = (line.account_code or "").strip()
            if vname and acct:
                vendor_acct_counts[vname][acct] += 1
    vendor_account_map = {}
    for vname, counter in vendor_acct_counts.items():
        most_common_acct, freq = counter.most_common(1)[0]
        acct_name = most_common_acct
        for j2 in all_journals:
            for line in j2.lines:
                if line.account_code == most_common_acct and line.account_name and line.account_name != most_common_acct:
                    acct_name = line.account_name
                    break
            if acct_name != most_common_acct:
                break
        vendor_account_map[vname] = (most_common_acct, acct_name, freq)

    dup_key_map = collections.defaultdict(list)
    for j in all_journals:
        acct_set = frozenset((l.account_code, l.debit_amount, l.credit_amount) for l in j.lines)
        vendors = frozenset(l.vendor_name for l in j.lines if l.vendor_name)
        key = (j.doc_date, j.total_debit, acct_set, vendors)
        dup_key_map[key].append(j.doc_no)
    dup_map = {k: v for k, v in dup_key_map.items() if len(v) >= 2}

    journal._vendor_account_map = vendor_account_map
    journal._duplicate_map = dup_map
    result = apply_rules_to_journal(journal, rules)

    journal.ai_risk_level = result["risk_level"]
    journal.ai_risk_score = result["risk_score"]
    journal.ai_error_codes = ",".join(result["error_codes"]) if result["error_codes"] else None
    journal.ai_reason = "\n".join(result["reasons"]) if result["reasons"] else None
    journal.ai_recommendation = "\n".join(result["recommendations"]) if result["recommendations"] else None
    journal.ai_analyzed_at = datetime.now()
    db.commit()

    return {
        "success": True,
        "risk_level": result["risk_level"],
        "risk_score": result["risk_score"],
        "error_codes": result["error_codes"],
        "reasons": result["reasons"],
    }


@app.post("/api/journal/{doc_no}/approve", response_class=JSONResponse)
def approve_journal(doc_no: str, db: Session = Depends(get_db)):
    journal = db.query(JournalEntry).filter(JournalEntry.doc_no == doc_no).first()
    if journal:
        journal.status = "검토완료"
        db.commit()
    return {"success": True, "status": "검토완료"}


@app.post("/api/ocr-reparse/{doc_no}", response_class=JSONResponse)
async def ocr_reparse(doc_no: str, db: Session = Depends(get_db)):
    """첨부 이미지를 LLM Vision으로 재분석"""
    journal = db.query(JournalEntry).filter(JournalEntry.doc_no == doc_no).first()
    if not journal or not journal.receipt_image:
        return JSONResponse({"error": "영수증이 첨부되지 않은 전표입니다."}, status_code=404)

    image_path = journal.receipt_image.lstrip("/")
    if not os.path.exists(image_path):
        return JSONResponse({"error": "이미지 파일을 찾을 수 없습니다."}, status_code=404)

    try:
        from llm_vision import analyze_receipt_with_llm, HAS_LLM_VISION
        if not HAS_LLM_VISION:
            return {"success": False, "error": "ALPHA_API_KEY가 설정되지 않았습니다."}

        result = analyze_receipt_with_llm(image_path)
        if result.get("success"):
            journal.ocr_date = result.get("date")
            journal.ocr_vendor = result.get("vendor")
            journal.ocr_amount = float(result.get("amount", 0)) if result.get("amount") else None
            journal.ocr_raw = result.get("raw_text")
            db.commit()
            return {"success": True, "parsed": result}
        else:
            return {"success": False, "error": result.get("error", "분석 실패")}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/check-balance-side", response_class=JSONResponse)
async def check_balance_side(request: Request):
    """전표 항목의 차대변 방향이 계정과목 잔액구분과 일치하는지 검증"""
    data = await request.json()
    lines = data.get("lines", [])
    bs = load_balance_sides()
    mismatches = []
    for i, line in enumerate(lines):
        code = str(line.get("account_code", "")).strip()
        name = line.get("account_name", "")
        debit = float(line.get("debit_amount", 0))
        credit = float(line.get("credit_amount", 0))
        expected = bs.get(code)
        if not expected or (debit == 0 and credit == 0):
            continue
        actual = "차변" if debit > 0 else "대변"
        if actual != expected:
            mismatches.append({
                "line_no": i + 1,
                "account_code": code,
                "account_name": name,
                "expected_side": expected,
                "actual_side": actual,
                "amount": debit if debit > 0 else credit,
            })
    return {"mismatches": mismatches}


@app.get("/api/side-mismatch-journals", response_class=JSONResponse)
def side_mismatch_journals(db: Session = Depends(get_db)):
    """차대변 불일치 전표 목록 반환"""
    bs = load_balance_sides()
    if not bs:
        return []
    journals = db.query(JournalEntry).options(
        joinedload(JournalEntry.lines), joinedload(JournalEntry.project)
    ).order_by(JournalEntry.ai_risk_score.desc().nullslast(), JournalEntry.id.desc()).all()

    results = []
    for j in journals:
        mismatches = []
        for line in j.lines:
            code = (line.account_code or "").strip()
            expected = bs.get(code)
            if not expected:
                continue
            if line.debit_amount and line.debit_amount > 0 and expected == "대변":
                mismatches.append({"line_no": line.line_no, "account_code": code,
                    "account_name": line.account_name, "expected": "대변", "actual": "차변",
                    "amount": line.debit_amount})
            elif line.credit_amount and line.credit_amount > 0 and expected == "차변":
                mismatches.append({"line_no": line.line_no, "account_code": code,
                    "account_name": line.account_name, "expected": "차변", "actual": "대변",
                    "amount": line.credit_amount})
        if mismatches:
            results.append({
                "doc_no": j.doc_no, "doc_date": j.doc_date,
                "description": j.description or "",
                "created_by": j.created_by or "",
                "total_debit": j.total_debit,
                "project_name": j.project.name if j.project else "",
                "risk_level": j.ai_risk_level,
                "risk_score": j.ai_risk_score,
                "mismatches": mismatches,
            })
    return results


@app.get("/api/ocr-check", response_class=JSONResponse)
def ocr_check_list(db: Session = Depends(get_db)):
    """OCR 파싱 데이터가 있는 전표 목록 + 불일치 여부"""
    journals = db.query(JournalEntry).options(joinedload(JournalEntry.lines)).filter(
        JournalEntry.receipt_image.isnot(None),
        JournalEntry.receipt_image != ''
    ).order_by(JournalEntry.id.desc()).all()

    results = []
    for j in journals:
        vendor_names = list(set(l.vendor_name for l in j.lines if l.vendor_name))
        mismatches = []

        # 일자 비교
        if j.ocr_date and j.doc_date:
            ocr_d = j.ocr_date.replace('-', '')
            doc_d = j.doc_date.replace('-', '')
            if ocr_d != doc_d:
                mismatches.append("일자")

        # 거래처 비교
        if j.ocr_vendor and vendor_names:
            ocr_v = j.ocr_vendor.strip()
            if not any(ocr_v in v or v in ocr_v for v in vendor_names):
                mismatches.append("거래처")

        # 금액 비교
        if j.ocr_amount and j.ocr_amount > 0:
            if abs(j.total_debit - j.ocr_amount) > 1 and abs(j.total_credit - j.ocr_amount) > 1:
                mismatches.append("금액")

        results.append({
            "doc_no": j.doc_no,
            "doc_date": j.doc_date,
            "total_debit": j.total_debit,
            "description": (j.description or "")[:50],
            "receipt_image": j.receipt_image,
            "vendor": vendor_names[0] if vendor_names else "",
            "ocr_date": j.ocr_date,
            "ocr_vendor": j.ocr_vendor,
            "ocr_amount": j.ocr_amount,
            "mismatches": mismatches,
            "status": "불일치" if mismatches else "일치",
        })

    return results


@app.post("/api/journal/{doc_no}/reject", response_class=JSONResponse)
def reject_journal(doc_no: str, db: Session = Depends(get_db)):
    journal = db.query(JournalEntry).filter(JournalEntry.doc_no == doc_no).first()
    if journal:
        journal.status = "반려"
        db.commit()
    return {"success": True, "status": "반려"}


@app.get("/api/projects", response_class=JSONResponse)
def get_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    return [{"id": p.id, "code": p.code, "name": p.name} for p in projects]


@app.get("/api/search/accounts", response_class=JSONResponse)
def search_accounts(q: str = "", db: Session = Depends(get_db)):
    """계정과목 검색 (코드 또는 이름)"""
    query = db.query(JournalLine.account_code, JournalLine.account_name).distinct()
    if q:
        query = query.filter(
            (JournalLine.account_code.contains(q)) | (JournalLine.account_name.contains(q))
        )
    results = query.limit(30).all()
    return [{"code": code, "name": name} for code, name in results if code]


@app.get("/api/search/vendors", response_class=JSONResponse)
def search_vendors(q: str = "", db: Session = Depends(get_db)):
    """거래처 검색 (코드 또는 이름, 유형 포함)"""
    VENDOR_TYPE_MAP = {"F": "법인", "P": "개인", "D": "부서", "S": "사원", "X": "기타", "B": "은행"}
    query = db.query(JournalLine.vendor_code, JournalLine.vendor_name, JournalLine.vendor_type).filter(
        JournalLine.vendor_name.isnot(None), JournalLine.vendor_name != ''
    ).distinct()
    if q:
        query = query.filter(
            (JournalLine.vendor_code.contains(q)) | (JournalLine.vendor_name.contains(q))
        )
    results = query.limit(30).all()
    return [{"code": code or "", "name": name, "type": vtype or "", "type_name": VENDOR_TYPE_MAP.get(vtype, vtype or "")} for code, name, vtype in results if name]


@app.get("/api/search/projects", response_class=JSONResponse)
def search_projects(q: str = "", db: Session = Depends(get_db)):
    """프로젝트 검색 (코드 또는 이름)"""
    query = db.query(Project)
    if q:
        query = query.filter((Project.code.contains(q)) | (Project.name.contains(q)))
    results = query.limit(30).all()
    return [{"id": p.id, "code": p.code, "name": p.name} for p in results]


# ──────────────────────────────────
# 룰 관리
# ──────────────────────────────────
@app.get("/rules", response_class=HTMLResponse)
def rules_page(request: Request, db: Session = Depends(get_db)):
    from rule_engine import load_rules
    rules = load_rules()
    categories = sorted(set(r.get("category", "기타") for r in rules))
    # 룰별 검출 건수 (정확한 코드 매칭)
    for r in rules:
        code = r["id"]
        cnt = db.query(JournalEntry).filter(
            (JournalEntry.ai_error_codes == code) |
            (JournalEntry.ai_error_codes.like(code + ',%')) |
            (JournalEntry.ai_error_codes.like('%,' + code)) |
            (JournalEntry.ai_error_codes.like('%,' + code + ',%'))
        ).count()
        r["hit_count"] = cnt
    return templates.TemplateResponse(request, "rules.html", {
        "rules": rules,
        "categories": categories,
    })


@app.get("/api/rules", response_class=JSONResponse)
def get_rules():
    from rule_engine import load_rules
    return load_rules()


@app.post("/api/rules", response_class=JSONResponse)
async def add_rule(request: Request):
    """새 룰 추가 (수동 입력)"""
    from rule_engine import load_rules, save_rules, get_next_rule_id
    rule_data = await request.json()
    rules = load_rules()
    rule_data["id"] = rule_data.get("id") or get_next_rule_id(rules)
    rule_data.setdefault("enabled", True)
    rule_data.setdefault("score", 0.15)
    rule_data.setdefault("category", "기타")
    rules.append(rule_data)
    save_rules(rules)
    reanalyze_status["rules_changed"] = True
    return {"success": True, "rule": rule_data}


@app.put("/api/rules/{rule_id}", response_class=JSONResponse)
async def update_rule(rule_id: str, request: Request):
    """룰 수정"""
    from rule_engine import load_rules, save_rules
    rule_data = await request.json()
    rules = load_rules()
    for i, r in enumerate(rules):
        if r["id"] == rule_id:
            rule_data["id"] = rule_id
            rules[i] = rule_data
            save_rules(rules)
            reanalyze_status["rules_changed"] = True
            return {"success": True, "rule": rule_data}
    return JSONResponse({"error": "룰을 찾을 수 없습니다."}, status_code=404)


@app.delete("/api/rules/{rule_id}", response_class=JSONResponse)
def delete_rule(rule_id: str):
    """룰 삭제"""
    from rule_engine import load_rules, save_rules
    rules = load_rules()
    rules = [r for r in rules if r["id"] != rule_id]
    save_rules(rules)
    reanalyze_status["rules_changed"] = True
    return {"success": True}


@app.post("/api/rules/parse-nl", response_class=JSONResponse)
async def parse_nl_rule(request: Request):
    """자연어 → 룰 변환"""
    from rule_engine import parse_natural_language_rule
    data = await request.json()
    text = data.get("text", "")
    result = parse_natural_language_rule(text)
    if result:
        return {"success": True, "rule": result}
    return {"success": False, "message": "룰을 생성할 수 없습니다. 조건을 더 구체적으로 입력해주세요."}


# ──────────────────────────────────
# 증빙자료 관리
# ──────────────────────────────────
ALLOWED_EVIDENCE_EXTS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
                         '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.hwp', '.hwpx',
                         '.zip', '.csv', '.txt'}
IMG_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif'}


@app.post("/api/evidence/parse-document", response_class=JSONResponse)
async def parse_evidence_document_api(file: UploadFile = File(...),
                                       request: Request = None):
    """증빙 문서 이미지/PDF를 LLM으로 파싱하여 구조화된 데이터 추출"""
    params = request.query_params if request else {}
    evidence_type = params.get("evidence_type", "")

    ext = os.path.splitext(file.filename)[1].lower()
    parseable_exts = IMG_EXTS | {'.pdf'}
    if ext not in parseable_exts:
        return {"success": False, "error": "이미지 또는 PDF 파일만 파싱할 수 있습니다."}

    # 임시 파일 저장
    saved_name = f"parse_{uuid.uuid4().hex[:8]}{ext}"
    save_path = os.path.join("static", "uploads", "evidences", saved_name)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    try:
        import asyncio
        from llm_vision import parse_evidence_document, PARSEABLE_EVIDENCE_TYPES
        if evidence_type not in PARSEABLE_EVIDENCE_TYPES:
            return {"success": False, "error": f"파싱을 지원하지 않는 증빙 유형입니다: {evidence_type}"}

        result = await asyncio.to_thread(parse_evidence_document, save_path, evidence_type)
        return result
    except Exception as e:
        print(f"[증빙파싱API] 오류: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)


@app.post("/api/evidence/parse-linked-doc", response_class=JSONResponse)
async def parse_linked_doc_api(file: UploadFile = File(...)):
    """연결문서 이미지/PDF를 LLM으로 파싱"""
    ext = os.path.splitext(file.filename)[1].lower()
    parseable_exts = IMG_EXTS | {'.pdf'}
    if ext not in parseable_exts:
        return {"success": False, "error": "이미지 또는 PDF 파일만 파싱할 수 있습니다."}

    saved_name = f"parse_ld_{uuid.uuid4().hex[:8]}{ext}"
    save_path = os.path.join("static", "uploads", "linked_docs", saved_name)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    try:
        import asyncio
        from llm_vision import parse_linked_document
        result = await asyncio.to_thread(parse_linked_document, save_path)
        return result
    except Exception as e:
        print(f"[연결문서파싱API] 오류: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)


@app.post("/api/evidence/{doc_no}", response_class=JSONResponse)
async def upload_evidence(doc_no: str, file: UploadFile = File(...),
                          request: Request = None, db: Session = Depends(get_db)):
    """증빙자료 업로드"""
    try:
        journal = db.query(JournalEntry).filter(JournalEntry.doc_no == doc_no).first()
        if not journal:
            return JSONResponse({"error": "전표를 찾을 수 없습니다."}, status_code=404)

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EVIDENCE_EXTS:
            return JSONResponse({"error": f"허용되지 않는 파일 형식입니다: {ext}"}, status_code=400)

        max_seq = db.query(func.coalesce(func.max(Evidence.seq_no), 0)).filter(
            Evidence.journal_id == journal.id).scalar()
        next_seq = max_seq + 1

        saved_name = f"{doc_no}_{next_seq}_{uuid.uuid4().hex[:8]}{ext}"
        save_path = os.path.join("static", "uploads", "evidences", saved_name)
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        params = request.query_params if request else {}
        ev_type = params.get("evidence_type", "기타")
        parsed_data_str = params.get("parsed_data", None)

        if not parsed_data_str:
            form = await request.form()
            parsed_data_str = form.get("parsed_data", None)
            if form.get("evidence_type"):
                ev_type = form.get("evidence_type")

        if (ext in IMG_EXTS or ext == '.pdf') and not parsed_data_str:
            try:
                import asyncio
                from llm_vision import parse_evidence_document, PARSEABLE_EVIDENCE_TYPES
                if ev_type in PARSEABLE_EVIDENCE_TYPES:
                    parse_result = await asyncio.to_thread(parse_evidence_document, save_path, ev_type)
                    if parse_result.get("success"):
                        parsed_data_str = _json.dumps(parse_result["fields"], ensure_ascii=False)
                    else:
                        print(f"[증빙파싱] 자동 파싱 실패: {parse_result.get('error')}")
            except Exception as e:
                print(f"[증빙파싱] 자동 파싱 예외: {e}")

        evidence = Evidence(
            journal_id=journal.id,
            seq_no=next_seq,
            evidence_type=ev_type,
            file_name=file.filename,
            file_path=f"/static/uploads/evidences/{saved_name}",
            file_ext=ext,
            file_size=len(content),
            parsed_data=parsed_data_str,
        )
        db.add(evidence)
        db.commit()
        db.refresh(evidence)

        return {
            "success": True,
            "evidence": {
                "id": evidence.id, "seq_no": evidence.seq_no,
                "evidence_type": evidence.evidence_type,
                "file_name": evidence.file_name, "file_path": evidence.file_path,
                "file_ext": evidence.file_ext, "file_size": evidence.file_size,
                "parsed_data": _json.loads(evidence.parsed_data) if evidence.parsed_data else None,
                "created_at": evidence.created_at.strftime("%Y-%m-%d %H:%M") if evidence.created_at else None,
            }
        }
    except Exception as e:
        print(f"[증빙업로드] 오류: {e}")
        return JSONResponse({"success": False, "error": f"업로드 처리 중 오류: {str(e)}"}, status_code=500)


@app.get("/api/evidence/{doc_no}", response_class=JSONResponse)
def list_evidences(doc_no: str, db: Session = Depends(get_db)):
    """증빙자료 목록 조회"""
    journal = db.query(JournalEntry).filter(JournalEntry.doc_no == doc_no).first()
    if not journal:
        return JSONResponse({"error": "전표를 찾을 수 없습니다."}, status_code=404)

    evidences = db.query(Evidence).filter(Evidence.journal_id == journal.id).order_by(Evidence.seq_no).all()
    return [
        {
            "id": e.id, "seq_no": e.seq_no,
            "evidence_type": e.evidence_type,
            "file_name": e.file_name, "file_path": e.file_path,
            "file_ext": e.file_ext, "file_size": e.file_size,
            "parsed_data": _json.loads(e.parsed_data) if e.parsed_data else None,
            "created_at": e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else None,
        }
        for e in evidences
    ]


@app.delete("/api/evidence/{evidence_id}", response_class=JSONResponse)
def delete_evidence(evidence_id: int, db: Session = Depends(get_db)):
    """증빙자료 삭제"""
    evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not evidence:
        return JSONResponse({"error": "증빙자료를 찾을 수 없습니다."}, status_code=404)

    # 파일 삭제
    file_path = evidence.file_path.lstrip("/")
    if os.path.exists(file_path):
        os.remove(file_path)

    db.delete(evidence)
    db.commit()
    return {"success": True}


@app.post("/api/evidence/{evidence_id}/reparse", response_class=JSONResponse)
async def reparse_evidence(evidence_id: int, db: Session = Depends(get_db)):
    """증빙자료 AI 재파싱"""
    evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not evidence:
        return JSONResponse({"error": "증빙자료를 찾을 수 없습니다."}, status_code=404)

    file_path = evidence.file_path.lstrip("/")
    if not os.path.exists(file_path):
        return {"success": False, "error": "파일을 찾을 수 없습니다."}

    try:
        import asyncio
        from llm_vision import parse_evidence_document, PARSEABLE_EVIDENCE_TYPES
        ev_type = evidence.evidence_type or ""
        if ev_type not in PARSEABLE_EVIDENCE_TYPES:
            return {"success": False, "error": f"파싱을 지원하지 않는 유형입니다: {ev_type}"}

        result = await asyncio.to_thread(parse_evidence_document, file_path, ev_type)
        if result.get("success") and result.get("fields"):
            evidence.parsed_data = _json.dumps(result["fields"], ensure_ascii=False)
            db.commit()
            return {"success": True, "fields_count": len(result["fields"])}
        else:
            return {"success": False, "error": result.get("error", "파싱 실패")}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ──────────────────────────────────
# 연결문서 관리
# ──────────────────────────────────
ALLOWED_DOC_EXTS = ALLOWED_EVIDENCE_EXTS

@app.post("/api/linked-doc/{doc_no}", response_class=JSONResponse)
async def upload_linked_doc(doc_no: str, file: UploadFile = File(...),
                            request: Request = None, db: Session = Depends(get_db)):
    """연결문서 업로드"""
    journal = db.query(JournalEntry).filter(JournalEntry.doc_no == doc_no).first()
    if not journal:
        return JSONResponse({"error": "전표를 찾을 수 없습니다."}, status_code=404)

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_DOC_EXTS:
        return JSONResponse({"error": f"허용되지 않는 파일 형식입니다: {ext}"}, status_code=400)

    max_seq = db.query(func.coalesce(func.max(LinkedDocument.seq_no), 0)).filter(
        LinkedDocument.journal_id == journal.id).scalar()
    next_seq = max_seq + 1

    saved_name = f"{doc_no}_LD{next_seq}_{uuid.uuid4().hex[:8]}{ext}"
    save_path = os.path.join("static", "uploads", "linked_docs", saved_name)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    params = request.query_params if request else {}
    d_type = params.get("doc_type", "기타")

    # 이미지/PDF면 LLM 파싱 시도
    parsed_data_str = None
    parsed_data_param = params.get("parsed_data", "")
    IMG_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif'}
    if parsed_data_param:
        parsed_data_str = parsed_data_param
    elif ext in IMG_EXTS or ext == '.pdf':
        try:
            from llm_vision import parse_linked_document
            parse_result = parse_linked_document(save_path)
            if parse_result.get("success") and parse_result.get("fields"):
                import json as _json2
                parsed_data_str = _json2.dumps(parse_result["fields"], ensure_ascii=False)
                print(f"[연결문서] 자동 파싱 완료: {len(parse_result['fields'])}개 항목")
        except Exception as e:
            print(f"[연결문서] 파싱 오류 (무시): {e}")

    linked_doc = LinkedDocument(
        journal_id=journal.id,
        seq_no=next_seq,
        doc_type=d_type,
        file_name=file.filename,
        file_path=f"/static/uploads/linked_docs/{saved_name}",
        file_ext=ext,
        file_size=len(content),
        parsed_data=parsed_data_str,
    )
    db.add(linked_doc)
    journal.has_linked_doc = "Y"
    db.commit()
    db.refresh(linked_doc)

    import json as _json3
    return {
        "success": True,
        "linked_doc": {
            "id": linked_doc.id, "seq_no": linked_doc.seq_no,
            "doc_type": linked_doc.doc_type,
            "file_name": linked_doc.file_name, "file_path": linked_doc.file_path,
            "file_ext": linked_doc.file_ext, "file_size": linked_doc.file_size,
            "parsed_data": _json3.loads(linked_doc.parsed_data) if linked_doc.parsed_data else None,
            "created_at": linked_doc.created_at.strftime("%Y-%m-%d %H:%M") if linked_doc.created_at else None,
        }
    }


@app.get("/api/linked-doc/{doc_no}", response_class=JSONResponse)
def list_linked_docs(doc_no: str, db: Session = Depends(get_db)):
    """연결문서 목록 조회"""
    journal = db.query(JournalEntry).filter(JournalEntry.doc_no == doc_no).first()
    if not journal:
        return JSONResponse({"error": "전표를 찾을 수 없습니다."}, status_code=404)

    docs = db.query(LinkedDocument).filter(LinkedDocument.journal_id == journal.id).order_by(LinkedDocument.seq_no).all()
    return [
        {
            "id": d.id, "seq_no": d.seq_no,
            "doc_type": d.doc_type,
            "file_name": d.file_name, "file_path": d.file_path,
            "file_ext": d.file_ext, "file_size": d.file_size,
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else None,
        }
        for d in docs
    ]


@app.delete("/api/linked-doc/{linked_doc_id}", response_class=JSONResponse)
def delete_linked_doc(linked_doc_id: int, db: Session = Depends(get_db)):
    """연결문서 삭제"""
    doc = db.query(LinkedDocument).filter(LinkedDocument.id == linked_doc_id).first()
    if not doc:
        return JSONResponse({"error": "연결문서를 찾을 수 없습니다."}, status_code=404)

    journal_id = doc.journal_id
    file_path = doc.file_path.lstrip("/")
    if os.path.exists(file_path):
        os.remove(file_path)

    db.delete(doc)
    db.flush()

    remaining = db.query(LinkedDocument).filter(LinkedDocument.journal_id == journal_id).count()
    journal = db.query(JournalEntry).filter(JournalEntry.id == journal_id).first()
    if journal:
        journal.has_linked_doc = "Y" if remaining > 0 else "N"

    db.commit()
    return {"success": True}


import threading
reanalyze_status = {"running": False, "progress": 0, "total": 0, "done": False, "result": None, "rules_changed": False}

@app.post("/api/rules/reanalyze", response_class=JSONResponse)
def reanalyze_with_rules():
    """현재 룰로 전체 전표 재분석 (백그라운드 실행)"""
    if reanalyze_status["running"]:
        return {"success": False, "message": "이미 재분석이 진행 중입니다."}

    reanalyze_status.update({"running": True, "progress": 0, "total": 0, "done": False, "result": None})

    def run_reanalysis():
        from rule_engine import load_rules, apply_rules_to_journal
        import collections
        db = next(get_db())
        try:
            rules = load_rules()
            journals = db.query(JournalEntry).options(
                joinedload(JournalEntry.lines),
                joinedload(JournalEntry.evidences),
                joinedload(JournalEntry.linked_docs),
            ).all()
            reanalyze_status.update({"total": len(journals)})

            # 거래처별 최빈 계정코드 패턴 맵 빌드 (account_pattern_mismatch 룰용)
            vendor_acct_counts = collections.defaultdict(lambda: collections.Counter())
            for j in journals:
                for line in j.lines:
                    vname = (line.vendor_name or "").strip()
                    acct = (line.account_code or "").strip()
                    if vname and acct:
                        vendor_acct_counts[vname][acct] += 1
            # {거래처명: (최빈계정코드, 계정명, 빈도)}
            vendor_account_map = {}
            for vname, counter in vendor_acct_counts.items():
                most_common_acct, freq = counter.most_common(1)[0]
                # 계정명 찾기
                acct_name = most_common_acct
                for j in journals:
                    for line in j.lines:
                        if line.account_code == most_common_acct and line.account_name and line.account_name != most_common_acct:
                            acct_name = line.account_name
                            break
                    if acct_name != most_common_acct:
                        break
                vendor_account_map[vname] = (most_common_acct, acct_name, freq)

            # 중복 전표 맵 빌드
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
                reanalyze_status["progress"] = i + 1
                if (i + 1) % 200 == 0:
                    db.commit()
            db.commit()
            high = sum(1 for j in journals if j.ai_risk_level == "High")
            med = sum(1 for j in journals if j.ai_risk_level == "Medium")
            low = sum(1 for j in journals if j.ai_risk_level == "Low")
            ok = sum(1 for j in journals if j.ai_risk_level == "정상")
            reanalyze_status.update({"running": False, "done": True, "rules_changed": False,
                "result": {"total": len(journals), "high": high, "medium": med, "low": low, "normal": ok}})
        except Exception as e:
            reanalyze_status.update({"running": False, "done": True, "result": {"error": str(e)}})
        finally:
            db.close()

    threading.Thread(target=run_reanalysis, daemon=True).start()
    return {"success": True, "message": "재분석을 시작합니다."}


@app.get("/api/rules/reanalyze/status", response_class=JSONResponse)
def reanalyze_progress():
    """재분석 진행률 조회"""
    pct = int(reanalyze_status["progress"] / max(reanalyze_status["total"], 1) * 100) if reanalyze_status["total"] > 0 else 0
    return {
        "running": reanalyze_status["running"],
        "progress": reanalyze_status["progress"],
        "total": reanalyze_status["total"],
        "percent": pct,
        "done": reanalyze_status["done"],
        "result": reanalyze_status["result"],
        "rules_changed": reanalyze_status["rules_changed"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
