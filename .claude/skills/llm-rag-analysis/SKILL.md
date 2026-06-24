---
name: llm-rag-analysis
description: "PwC Gemini 3.1 Pro Vision API로 영수증/세금계산서 이미지를 분석하여 금액, 거래처, 일자, 부가세를 추출하고, 대화형 챗으로 전표를 생성/수정하는 스킬. 'LLM', '영수증 인식', 'OCR', 'Gemini', '이미지 분석', '챗 어시스턴트', '전표 수정', '금액 수정' 관련 작업 시 이 스킬을 사용."
---

# LLM + Vision 기반 문서 분석 및 대화형 어시스턴트

PwC Workspace Gemini 3.1 Pro API를 활용한 영수증 OCR 분석과 대화형 전표 생성/수정.

## 영수증 OCR 파이프라인

```
이미지 업로드
    ↓
[1순위] Gemini Vision API (llm_vision.py)
    ↓ 이미지 리사이즈 (>1.5MB → 2000px JPEG 압축)
    ↓ 프롬프트: 일자/거래처/금액/공급가/부가세/품목 추출
    ↓ JSON 파싱 + 계정과목 추정
    ↓ (실패 시)
[2순위] Tesseract OCR → 정규식 파싱
    ↓ (실패 시)
에러 반환 (시뮬레이션 폴백 제거)
```

## API 설정
- **URL**: https://workspace.kr.pwc.com/api/workspace/coding_agent/v1/chat/completions
- **모델**: Gemini_3.1_Pro
- **인증**: .env → ALPHA_API_KEY
- **max_tokens**: 4096 (2048에서 증가 — content 잘림 방지)
- **타임아웃**: 120초
- **이미지 제한**: 1.5MB (초과 시 자동 리사이즈)

## OCR 추출 JSON
```json
{"date":"", "vendor":"", "biz_no":"", "amount":0, "supply_amount":0, "tax_amount":0, "items":[], "doc_type":"", "buyer":""}
```

## 부가세 분리 자동화
supply_amount + tax_amount가 있으면 3라인 자동 생성:
1. 비용계정 (공급가액) — 차변
2. 부가세대급금 1112800 (세액) — 차변
3. 미지급금 2100303 (합계) — 대변

## 대화형 어시스턴트 (llm_chat.py)
- Claude API 연결 시: 실제 LLM 대화
- 로컬 파서: 금액 수정, 부가세 분리, 계정 변경, 전표 생성
- 대화 컨텍스트 10개 유지, 현재 폼 상태 참조

## OCR 불일치 점검
- 전표 생성 시: 저장 직전 OCR값 vs 입력값 비교 경고 팝업
- 전표 검토 시: [OCR 값 일치 점검] 버튼 → 건별 비교 모달 + [AI 재분석] 버튼

## 핵심 파일
- `llm_vision.py` — Gemini Vision API, 이미지 리사이즈, 계정 추정
- `llm_chat.py` — 대화형 어시스턴트
- `receipt_parser.py` — OCR 파싱 총괄
- `.env` — ALPHA_API_KEY
