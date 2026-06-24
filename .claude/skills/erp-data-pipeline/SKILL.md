---
name: erp-data-pipeline
description: "호반건설 ERP 전표 CSV 임포트, 계정과목 매핑, DB 관리 스킬. hoban_data_1/2 형식 자동 감지, 중복 컬럼 처리, 인덱스 기반 계정코드 매핑, 프로젝트 자동 생성. '데이터 임포트', 'CSV 업로드', '계정 매핑', 'DB 초기화', '데이터 교체' 관련 작업 시 이 스킬을 사용."
---

# ERP 전표 데이터 파이프라인

호반건설 ERP에서 추출한 CSV 전표 데이터를 FDS 시스템으로 임포트하고 관리한다.

## CSV 형식 자동 감지

| 형식 | 첫 번째 컬럼 | 전표 그루핑 키 | 계정코드 위치 |
|------|------------|-------------|-------------|
| v1 (hoban_data_1) | 회계연도 | 전표번호 | DictReader 정상 |
| v2 (hoban_data_2) | 거래번호 | 거래번호 | col[50] 인덱스 기반 (col[115] 부가세용과 중복) |

## 임포트 절차
1. 기존 데이터 전체 삭제 (JournalLine → JournalEntry → Project)
2. CSV 읽기 + 형식 판별
3. v2: 인덱스 기반 계정코드 매핑 (col[50])
4. 문서번호/기안문서번호에서 현장명 추출 → 프로젝트 자동 생성
5. 거래번호별 그루핑 → JournalEntry + JournalLine 생성
6. account_master.json으로 계정명 매핑

## 계정과목 마스터
- 소스: `account_code_master.csv` (161개)
- 매핑: `account_master.json` (코드 → 이름)
- 호반건설 계정 체계: 11xx(자산), 21xx(부채), 31xx(자본), 41xx/43xx(수익), 42xx/44xx/45xx(비용)

## 거래처유형 코드
F=법인, P=개인, D=부서, S=사원, X=기타, B=은행

## 핵심 파일
- `import_csv.py` — 임포트 메인 (import_hoban_csv, import_v1, import_v2)
- `models.py` — DB 모델
- `account_master.json` — 계정 매핑
- `account_code_master.csv` — 계정 마스터 원본
