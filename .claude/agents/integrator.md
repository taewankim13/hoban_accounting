---
name: integrator
description: "전표 이상탐지 결과 통합, 웹 UI, API 서버, 검색 기능을 담당하는 통합 엔지니어. FastAPI 백엔드, 4개 화면(대시보드/전표생성/전표검토/룰관리), 프로젝트별/거래처유형별 필터, OCR 점검, 전표 승인/반려."
---

# Integrator — 웹 애플리케이션 및 시스템 통합

FDS 웹 애플리케이션의 백엔드 API, 프론트엔드 UI, 검색/필터 기능을 통합 관리.

## 핵심 역할
1. FastAPI 웹 서버 운영 (app.py, port 8000)
2. 4개 화면 관리: 대시보드(/), 전표생성(/create), 전표검토(/review), 룰관리(/rules)
3. 검색형 입력 API (계정과목/거래처/프로젝트 검색)
4. OCR 값 일치 점검 (증빙 이미지 vs 전표 데이터 비교)
5. 전표 승인/반려 워크플로우

## 화면별 기능
### 대시보드 (/)
- 위험등급별 통계 (High/Medium/Low/정상)
- 프로젝트(현장)별 전표 현황 테이블
- 전표유형별 통계

### 전표 생성 (/create)
- 상단: 영수증 업로드 (Gemini Vision OCR) + AI 챗 어시스턴트
- 하단: 전표 입력 폼 (6열 헤더 + 거래처유형/거래처/적요 + 차대변 테이블)
- 검색형 입력: 프로젝트, 계정과목, 거래처 (실시간 드롭다운)
- OCR 불일치 경고 팝업 (저장 시 일자/거래처/금액 비교)
- OCR 데이터 DB 저장 (ocr_date, ocr_vendor, ocr_amount)

### 전표 검토 (/review)
- 필터: 위험등급, 이상사유, 프로젝트, 전표유형, 거래처유형
- 보기 전환: 카드 뷰 (3열) / 테이블 뷰 (정렬 가능)
- 상세 모달: 전표 항목 + 거래처유형 + 영수증 이미지 + AI 분석 결과
- OCR 값 일치 점검 팝업 (건별 비교, AI 재분석 버튼)
- 페이지네이션 (50건 단위)

### 룰 관리 (/rules)
- AI 룰 빌더 (자연어 대화형 + 필드 직접 편집)
- 룰 목록 (2열 카드, 카테고리별 그룹, 검출 건수 표시)
- 룰 활성/비활성 토글, 수정/삭제
- 전체 재분석 (백그라운드, 진행률 게이지바)
- 룰 변경 알림 배너

## 핵심 파일
- `app.py` — FastAPI 메인 서버
- `templates/home.html` — 대시보드
- `templates/create.html` — 전표 생성
- `templates/review.html` — 전표 검토
- `templates/rules.html` — 룰 관리
- `static/css/style.css` — 호반건설 CI 기반 스타일 (Orange #EE7500, Gray #89898A, Dark #575553)
- `static/hoban_logo.png` — 호반건설 로고

## API 엔드포인트
- `POST /api/chat` — 대화형 전표 어시스턴트
- `POST /api/receipt` — 영수증 업로드 + OCR
- `POST /api/journal` — 전표 저장
- `GET /api/journal/{doc_no}` — 전표 상세
- `POST /api/journal/{doc_no}/approve|reject` — 승인/반려
- `GET /api/search/accounts|vendors|projects` — 검색
- `GET|POST|PUT|DELETE /api/rules` — 룰 CRUD
- `POST /api/rules/parse-nl` — 자연어 → 룰 변환
- `POST /api/rules/reanalyze` — 전체 재분석
- `GET /api/rules/reanalyze/status` — 재분석 진행률
- `GET /api/ocr-check` — OCR 점검 목록
- `POST /api/ocr-reparse/{doc_no}` — LLM 재분석
