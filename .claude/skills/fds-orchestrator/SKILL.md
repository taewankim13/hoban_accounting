---
name: fds-orchestrator
description: "호반건설 전표 이상탐지 FDS 시스템 전체를 조율하는 오케스트레이터. 데이터 임포트, 룰 엔진 분석, LLM OCR, 웹 UI를 통합 관리. 전표 분석, 이상탐지, 부정탐지, FDS 파이프라인 관련 작업 시 이 스킬을 사용. 후속: 결과 수정, 재실행, 룰 변경, 데이터 교체, 화면 수정, OCR 점검 시에도 이 스킬을 사용."
---

# FDS Orchestrator — 전표 이상탐지 시스템 통합 관리

호반건설 전표 이상탐지 FDS 시스템의 전체 워크플로우를 조율한다.

## 실행 모드: 에이전트 팀

## 시스템 구성

| 에이전트 | 역할 | 스킬 | 핵심 파일 |
|---------|------|------|---------|
| data-engineer | 데이터 임포트/매핑 | erp-data-pipeline | import_csv.py, models.py |
| anomaly-detector | 룰 엔진 이상탐지 | anomaly-detection | rule_engine.py, rules.json |
| llm-rag-engineer | LLM OCR/챗 | llm-rag-analysis | llm_vision.py, llm_chat.py, receipt_parser.py |
| integrator | 웹 UI/API | result-integration | app.py, templates/, static/ |

## 워크플로우

### Phase 0: 컨텍스트 확인
1. DB(fds.db) 존재 여부 확인
2. rules.json 현재 룰 수 확인
3. 실행 모드 결정: 초기/데이터 교체/룰 변경/화면 수정/부분 재실행

### Phase 1: 데이터 준비
1. CSV 파일 확인 (hoban_data_2.csv 우선)
2. import_csv.py로 임포트 (기존 삭제 → 재임포트)
3. account_master.json으로 계정명 매핑

### Phase 2: 룰 기반 분석
1. rules.json 로드 (18개 룰)
2. 거래처 패턴맵 + 중복 전표맵 빌드
3. 전표별 룰 적용 → 위험등급/점수/사유 산출
4. DB 업데이트

### Phase 3: 웹 서비스
1. FastAPI 서버 실행 (python app.py, port 8000)
2. 4개 화면 서빙 (대시보드/전표생성/전표검토/룰관리)

## 데이터 흐름

```
[CSV] → import_csv.py → [SQLite DB]
                              ↓
                     rule_engine.py (rules.json)
                              ↓
                     [위험등급 + 사유 저장]
                              ↓
                     app.py (FastAPI)
                     ├── 대시보드: 통계
                     ├── 전표 생성: LLM OCR + 챗
                     ├── 전표 검토: 필터 + 상세 + OCR 점검
                     └── 룰 관리: CRUD + 재분석
```

## 에러 핸들링
| 상황 | 전략 |
|------|------|
| CSV 임포트 실패 | 에러 메시지 출력, DB 미생성 |
| 룰 분석 중 타입 오류 | to_num() 안전 변환, 해당 룰만 스킵 |
| LLM API 타임아웃 | 120초, 실패 시 에러 반환 (시뮬레이션 폴백 없음) |
| 이미지 5MB+ | 자동 리사이즈 2000px JPEG |
| 포트 충돌 | taskkill /F /IM python.exe 후 재시작 |

## 실행 방법
```bash
taskkill /F /IM python.exe
cd "c:\Users\tkim199\Desktop\김태완\12.개발작업\hoban_fds"
python app.py
```
→ http://localhost:8000
