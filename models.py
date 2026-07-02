"""전표 데이터 모델 - 호반건설 실제 전표 스키마 기반"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class SavedRule(Base):
    """탐지 룰 (DB 영속 저장)"""
    __tablename__ = "saved_rules"

    rule_id = Column(String(20), primary_key=True)
    rule_json = Column(Text, nullable=False)


class Project(Base):
    """건설 프로젝트 (현장)"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, index=True)
    name = Column(String(100))
    location = Column(String(100), nullable=True)
    client = Column(String(100), nullable=True)
    contract_amount = Column(Float, default=0)
    start_date = Column(String(10), nullable=True)
    end_date = Column(String(10), nullable=True)
    status = Column(String(20), default="진행중")
    manager = Column(String(50), nullable=True)

    journals = relationship("JournalEntry", back_populates="project")


class JournalEntry(Base):
    """전표 헤더"""
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    doc_no = Column(String(50), unique=True, index=True)       # 전표번호
    doc_date = Column(String(10))                               # 전표일자 (YYYYMMDD or YYYY-MM-DD)
    fiscal_year = Column(String(4), nullable=True)              # 회계연도
    doc_month = Column(String(2), nullable=True)                # 전표월
    doc_type = Column(String(50), nullable=True)                # 전표유형
    category = Column(String(20), nullable=True)                # 구분 (손익/부채/자산/자본)
    big_category = Column(String(30), nullable=True)            # 대분류
    mid_category = Column(String(30), nullable=True)            # 중분류
    small_category = Column(String(30), nullable=True)          # 소분류
    description = Column(String(500))                           # 적요
    description2 = Column(String(500), nullable=True)           # 적요2
    created_by = Column(String(50))                             # 입력자
    input_datetime = Column(String(30), nullable=True)          # 입력일시
    modified_datetime = Column(String(30), nullable=True)       # 최종수정일시
    department = Column(String(50), nullable=True)              # 손익부서명
    department_code = Column(String(20), nullable=True)         # 손익부서코드
    biz_unit = Column(String(50), nullable=True)                # 사업부구분명
    biz_unit_code = Column(String(20), nullable=True)           # 사업부구분코드
    cost_center = Column(String(50), nullable=True)             # 코스트센터명
    cost_center_code = Column(String(20), nullable=True)        # 코스트센터코드
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    project_code_raw = Column(String(50), nullable=True)        # 프로젝트코드 (원본)
    project_name_raw = Column(String(100), nullable=True)       # 프로젝트명 (원본)
    status = Column(String(20), default="제출")
    total_debit = Column(Float, default=0)
    total_credit = Column(Float, default=0)
    receipt_image = Column(String(300), nullable=True)
    # OCR 파싱 결과 저장 (세금계산서/영수증 업로드 시)
    ocr_date = Column(String(10), nullable=True)           # OCR 추출 일자
    ocr_vendor = Column(String(100), nullable=True)        # OCR 추출 거래처
    ocr_amount = Column(Float, nullable=True)              # OCR 추출 금액
    ocr_raw = Column(Text, nullable=True)                  # OCR 원본 텍스트/메타
    created_at = Column(DateTime, default=datetime.now)

    # 추가 필드
    designation_no = Column(String(50), nullable=True)          # 지정번호
    object_key = Column(String(100), nullable=True)             # 오브젝트키
    payment_condition = Column(String(100), nullable=True)      # 지급조건내역
    evidence_type = Column(String(50), nullable=True)           # 증빙구분
    evidence_date = Column(String(10), nullable=True)           # 증빙일자
    ref_doc_no = Column(String(100), nullable=True)             # 참고문서번호
    func_area = Column(String(50), nullable=True)               # 기능영역명
    func_area_code = Column(String(20), nullable=True)          # 기능영역코드
    draft_doc_no = Column(String(100), nullable=True)           # 기안문서번호
    settlement_date = Column(String(10), nullable=True)         # 반제일

    has_linked_doc = Column(String(1), default="N")           # 연결문서 여부 (Y/N)

    # AI 분석 결과
    ai_risk_level = Column(String(10), nullable=True)
    ai_risk_score = Column(Float, nullable=True)
    ai_error_codes = Column(String(200), nullable=True)
    ai_reason = Column(Text, nullable=True)
    ai_recommendation = Column(Text, nullable=True)
    ai_analyzed_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="journals")
    lines = relationship("JournalLine", back_populates="journal", cascade="all, delete-orphan")
    evidences = relationship("Evidence", back_populates="journal", cascade="all, delete-orphan")
    linked_docs = relationship("LinkedDocument", back_populates="journal", cascade="all, delete-orphan")


class Evidence(Base):
    """증빙자료"""
    __tablename__ = "evidences"

    id = Column(Integer, primary_key=True, index=True)
    journal_id = Column(Integer, ForeignKey("journal_entries.id"), index=True)
    seq_no = Column(Integer)                                     # 증빙목록번호 (순번)
    evidence_type = Column(String(50))                           # 증빙자료 구분 (세금계산서/영수증/계약서/거래명세서/기타)
    file_name = Column(String(300))                              # 원본 파일명
    file_path = Column(String(500))                              # 저장 경로
    file_ext = Column(String(20))                                # 확장자 (.pdf, .jpg, .png 등)
    file_size = Column(Integer, default=0)                       # 파일 크기 (bytes)
    parsed_data = Column(Text, nullable=True)                    # JSON: LLM 파싱 결과 [{label, value}, ...]
    created_at = Column(DateTime, default=datetime.now)

    journal = relationship("JournalEntry", back_populates="evidences")


class LinkedDocument(Base):
    """연결문서"""
    __tablename__ = "linked_documents"

    id = Column(Integer, primary_key=True, index=True)
    journal_id = Column(Integer, ForeignKey("journal_entries.id"), index=True)
    seq_no = Column(Integer)                                     # 연결문서목록번호 (순번)
    doc_type = Column(String(50))                                # 연결문서 구분 (기안서/계약서/검수확인서/품의서/발주서/기타)
    file_name = Column(String(300))                              # 원본 파일명
    file_path = Column(String(500))                              # 저장 경로
    file_ext = Column(String(20))                                # 확장자
    file_size = Column(Integer, default=0)                       # 파일 크기 (bytes)
    parsed_data = Column(Text, nullable=True)                    # JSON: LLM 파싱 결과 [{label, value}, ...]
    created_at = Column(DateTime, default=datetime.now)

    journal = relationship("JournalEntry", back_populates="linked_docs")


class JournalLine(Base):
    """전표 항목 (차변/대변)"""
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True, index=True)
    journal_id = Column(Integer, ForeignKey("journal_entries.id"))
    line_no = Column(Integer)                                    # 전표일련번호
    side = Column(String(10))                                    # 차대구분 (차변/대변)
    account_code = Column(String(20))                            # 계정코드
    account_name = Column(String(50))                            # 계정과목명
    debit_amount = Column(Float, default=0)                      # 차변금액
    credit_amount = Column(Float, default=0)                     # 대변금액
    description = Column(String(500), nullable=True)             # 적요
    vendor_code = Column(String(30), nullable=True)              # 거래처코드
    vendor_type = Column(String(20), nullable=True)              # 거래처구분
    vendor_name = Column(String(100), nullable=True)             # 상호
    biz_no = Column(String(20), nullable=True)                   # 사업자번호
    cost_center = Column(String(20), nullable=True)              # 코스트센터코드

    journal = relationship("JournalEntry", back_populates="lines")


# 건설사 부서
DEPARTMENTS = [
    "경영관리부", "재무회계팀", "공사1팀", "공사2팀", "공사3팀",
    "설계팀", "안전환경팀", "구매조달팀", "영업팀", "인사총무팀",
]

# 직원 목록
EMPLOYEES = [
    ("김건설", "공사1팀"), ("이현장", "공사2팀"), ("박안전", "안전환경팀"),
    ("최설계", "설계팀"), ("정구매", "구매조달팀"), ("한재무", "재무회계팀"),
    ("오관리", "경영관리부"), ("강영업", "영업팀"), ("조인사", "인사총무팀"),
    ("윤공사", "공사3팀"), ("임회계", "재무회계팀"), ("서총무", "인사총무팀"),
]

# 프로젝트 마스터
PROJECTS = [
    {"code": "PJ-COMMON", "name": "본사 공통", "location": "서울 본사", "client": "-", "contract_amount": 0, "start_date": "2024-01-01", "end_date": "2030-12-31", "manager": "오관리"},
]
