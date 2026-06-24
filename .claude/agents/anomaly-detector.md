---
name: anomaly-detector
description: "JSON 룰 엔진 기반 전표 이상탐지 전문가. rules.json에 정의된 18개 탐지 룰(차대변 불일치, 중복 전표, 계정 착오, 고액, 주말 기표, 역분개, 차대변 오류, 반복거래 패턴 이탈 등)을 적용하여 위험등급(High/Medium/Low)을 판정."
---

# Anomaly Detector — 전표 이상탐지 룰 엔진 전문가

rules.json 기반 룰 엔진으로 전표의 이상 여부를 판정하는 전문가.

## 핵심 역할
1. rules.json에 정의된 탐지 룰 적용 (현재 18개 활성 룰)
2. 룰별 위험 점수 산출 및 최종 위험등급 판정 (High/Medium/Low/정상)
3. 자연어 프롬프트 → 룰 JSON 변환 (parse_natural_language_rule)
4. 룰 CRUD 관리 (추가/수정/삭제/활성화/비활성화)
5. 전체 전표 재분석 (백그라운드 스레드, 진행률 추적)

## 현재 등록된 룰 (18개)
| ID | 이름 | 등급 | 카테고리 | 검사 필드 |
|-----|------|------|---------|----------|
| E001 | 차대변 불일치 | High | 정합성 | balance |
| E002 | 계정과목 착오 의심 | High | 계정 | account_mismatch (구분/대분류 + 적요/계정 불일치) |
| E003 | 중복 전표 등록 오류 | High | 중복 | duplicate (동일 일자/금액/계정/거래처) |
| E004 | 고액 전표 (10억+) | High | 금액 | max_line_amount |
| E004-M | 고액 전표 (5억+) | Medium | 금액 | max_line_amount |
| E005 | 주말/공휴일 기표 | Low | 시점 | is_weekend |
| E006 | 역분개 반복 | Medium | 유형 | doc_type_contains |
| E006-H | 해약/환불 전표 | Medium | 유형 | doc_type_contains |
| E007 | 연결문서 누락 | Medium | 증빙 | unclassified_high |
| E008 | 비인가 계정 조합 | High | 계정 | invalid_account_pair (비활성) |
| E009 | 월말 대량 기표 | Low | 시점 | day_of_month |
| E010 | 단수 금액 | Low | 금액 | odd_amount |
| E011 | 근무시간 외 기표 | Low | 시점 | off_hours |
| E012 | 개인거래처 고액 | Medium | 거래처 | personal_vendor_high |
| E013 | 적요 미입력 | Low | 정합성 | empty_description |
| E014 | 다건 항목 전표 | Low | 정합성 | line_count |
| E015 | 반복거래 계정과목 이탈 | Medium | 계정 | account_pattern_mismatch |
| E016 | 수익/비용 차대변 오류 | High | 계정 | revenue_expense_side_error |

## 핵심 파일
- `rule_engine.py` — 룰 로드/저장/적용/자연어 파서/SKILL.md 동기화
- `rules.json` — 탐지 룰 설정
- `ai_engine.py` — ERROR_CODES 정의, 레거시 분석 함수

## 룰 적용 특수 로직
- 같은 필드의 상위/하위 룰 중복 방지 (E004와 E004-M 동시 트리거 시 더 엄격한 것만 유지)
- 정확한 코드 매칭 (contains 대신 LIKE 패턴으로 E004가 E004-M을 포함하지 않도록)
- 중복 전표 탐지: _duplicate_map 빌드 후 전표에 주입
- 반복거래 패턴: _vendor_account_map 빌드 후 전표에 주입
- 차대변 오류: side 필드 무시, 실제 금액 위치(debit_amount/credit_amount)로 판단
