## 하네스: 전표 이상탐지 AI 파이프라인 (FDS)

**목표:** 사내 구축형 LLM 기반 실시간 전표 이상탐지 및 지능형 감사 파이프라인 구축

**트리거:** 전표 분석, 이상탐지, 부정탐지, FDS 파이프라인 관련 작업 요청 시 `fds-orchestrator` 스킬을 사용하라. 단순 질문은 직접 응답 가능.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-06-10 | 초기 구성 | 전체 | 하네스 신규 구축 |
| 2026-06-24 | 에이전트 4개 업데이트 | agents/ 전체 | 실제 구현 시스템에 맞게 역할/파일/스키마 반영 |
| 2026-06-24 | 스킬 5개 업데이트 | skills/ 전체 | 18개 탐지 룰, Gemini Vision OCR, 웹 UI 4개 화면, 검색/필터 기능 반영 |
| 2026-06-24 | anomaly-detection 스킬 전면 갱신 | skills/anomaly-detection | 18개 룰 상세 목록, 특수 로직(중복방지/정확매칭/외부맵) 문서화 |
| 2026-06-24 | llm-rag-analysis 스킬 전면 갱신 | skills/llm-rag-analysis | Gemini Vision API 설정, 이미지 리사이즈, OCR 불일치 점검, 대화형 챗 문서화 |
| 2026-06-24 | result-integration 스킬 전면 갱신 | skills/result-integration | 4개 화면 상세, API 엔드포인트, 필터/정렬/페이지네이션 문서화 |
| 2026-06-24 | fds-orchestrator 스킬 전면 갱신 | skills/fds-orchestrator | 전체 워크플로우, 데이터 흐름, 에러 핸들링 업데이트 |
