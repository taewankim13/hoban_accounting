"""PwC Workspace Gemini API 기반 전표 어시스턴트 - 대화형 전표 생성/수정 지원"""
import os
import json
import re
import requests

# .env 파일에서 API 키 로드
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

ALPHA_API_KEY = os.environ.get("ALPHA_API_KEY", "")
API_URL = "https://workspace.kr.pwc.com/api/workspace/coding_agent/v1/chat/completions"
MODEL = "Gemini_3.1_Pro"
HAS_LLM = bool(ALPHA_API_KEY)

SYSTEM_PROMPT = """당신은 호반건설의 전표 생성을 돕는 AI 회계 어시스턴트입니다.

## 역할
- 사용자가 자연어로 전표 내용을 설명하면 계정과목, 차변/대변, 금액을 자동 생성합니다.
- 사용자가 기존 전표의 금액이나 계정을 수정하라고 하면 수정된 전표 데이터를 반환합니다.
- 영수증에서 추출된 데이터가 잘못되었다는 피드백을 받으면 수정합니다.

## 건설사 주요 계정과목
- 4200201: 재료비(상품), 4200205: 여비교통비(일반), 4200206: 통신비(일반)
- 4200207: 지급수수료(공사), 4200209: 복리후생비(공사), 4200210: 소모품비(상품)
- 2100303: 미지급금(일반), 2100304: 미지급금(카드), 1100401: 부가세대급금
- 자재비, 노무비, 외주비, 경비, 안전관리비, 장비사용료, 설계비

## 응답 규칙
1. 반드시 아래 JSON 형식으로 응답하세요.
2. message: 사용자에게 보여줄 한국어 안내 메시지
3. lines: 전표 항목 배열 (수정/생성 시). 수정이 아닌 일반 대화면 빈 배열.
4. guide: 관련 회계 가이드 (선택)
5. update_amount: 금액 수정 요청인 경우 true
6. description: 전표 적요

## 응답 JSON 형식
```json
{
  "message": "안내 메시지",
  "lines": [
    {"account_code": "코드", "account_name": "계정명", "debit_amount": 0, "credit_amount": 0, "side": "차변|대변"}
  ],
  "guide": "가이드 메시지 (선택)",
  "error_guides": ["자주 틀리는 오류 가이드 (선택)"],
  "doc_type": "전표유형",
  "description": "적요",
  "amount": 총금액(숫자)
}
```

## 주의사항
- 차변 합계와 대변 합계는 반드시 일치해야 합니다.
- 부가세가 포함된 금액이면 공급가액과 부가세를 분리하여 부가세대급금(1100401) 항목을 추가하세요.
- 금액 수정 요청 시, 기존 항목 구조를 유지하면서 금액만 변경하세요.
- JSON만 응답하세요. 다른 텍스트는 포함하지 마세요."""


def chat_with_gemini(messages: list, current_form: dict = None, api_key=None) -> dict:
    """PwC Workspace Gemini API로 대화형 전표 어시스턴트를 실행한다."""

    system = SYSTEM_PROMPT
    if current_form and current_form.get("lines"):
        system += f"\n\n## 현재 전표 폼 상태\n```json\n{json.dumps(current_form, ensure_ascii=False, indent=2)}\n```\n사용자가 수정을 요청하면 이 데이터를 기반으로 수정하세요."

    key = api_key or ALPHA_API_KEY
    if not key:
        return {"message": "API 키가 설정되지 않았습니다. 설정에서 Gemini API Key를 입력해주세요.", "error": "NO_API_KEY"}

    api_messages = [{"role": "system", "content": system}] + messages

    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": api_messages,
                "max_tokens": 2048,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        text = data["choices"][0]["message"]["content"].strip()

        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        if not text.startswith('{'):
            idx = text.find('{')
            if idx >= 0:
                text = text[idx:]

        result = json.loads(text)
        result["success"] = True
        result.setdefault("lines", [])
        result.setdefault("message", "")
        result.setdefault("guide", "")
        result.setdefault("error_guides", [])
        result.setdefault("doc_type", current_form.get("doc_type", "일반전표") if current_form else "일반전표")
        result.setdefault("description", current_form.get("description", "") if current_form else "")
        result.setdefault("amount", 0)

        if result["amount"] == 0 and result["lines"]:
            result["amount"] = sum(l.get("debit_amount", 0) for l in result["lines"])

        return result

    except json.JSONDecodeError:
        return {
            "success": True,
            "message": text if 'text' in dir() else "응답을 처리할 수 없습니다.",
            "lines": [],
            "guide": "",
            "error_guides": [],
            "doc_type": "일반전표",
            "description": "",
            "amount": 0,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"LLM 호출 오류: {str(e)}",
            "lines": [],
            "guide": "",
            "error_guides": [],
            "doc_type": "일반전표",
            "description": "",
            "amount": 0,
        }


def chat_with_local(message: str, current_form: dict = None) -> dict:
    """로컬 규칙 기반 파서 (API 키 없을 때 폴백). 대화 컨텍스트를 이해하는 강화 버전."""

    msg = message.strip()
    msg_lower = msg.lower()

    # ── 1. 금액 수정 요청 감지 ──
    amount_correction = re.search(
        r'(?:총액|합계|금액)[은는이가]?\s*(\d[\d,]*)\s*(만\s*원|원|억)?', msg
    )
    if not amount_correction:
        amount_correction = re.search(
            r'(\d[\d,]*)\s*(만\s*원|원|억)?\s*(?:으로|로)\s*(?:수정|변경|바꿔)', msg
        )

    # 숫자만 있는 입력도 금액 수정으로 처리
    only_number = re.match(r'^[\d,]+\s*(만\s*원|원|억)?$', msg.strip())
    if only_number:
        amount_correction = only_number

    if amount_correction or any(kw in msg_lower for kw in ['틀렸', '수정', '변경', '바꿔', '고쳐', '잘못', 'total', 'amount', '총액', '합계', '금액']):
        # 금액 추출
        new_amount = 0
        amt_match = re.search(r'(\d[\d,]*)\s*(만\s*원|원|억)?', msg)
        if amt_match:
            raw = int(amt_match.group(1).replace(",", ""))
            unit = amt_match.group(2) or ""
            if "만" in unit:
                new_amount = raw * 10000
            elif "억" in unit:
                new_amount = raw * 100000000
            else:
                new_amount = raw

        if new_amount > 0 and current_form and current_form.get("lines"):
            updated_lines = []
            for line in current_form["lines"]:
                new_line = dict(line)
                if line.get("debit_amount", 0) > 0:
                    new_line["debit_amount"] = new_amount
                    new_line["credit_amount"] = 0
                elif line.get("credit_amount", 0) > 0:
                    new_line["credit_amount"] = new_amount
                    new_line["debit_amount"] = 0
                updated_lines.append(new_line)

            return {
                "success": True,
                "message": f"금액을 {new_amount:,}원으로 수정했습니다.",
                "lines": updated_lines,
                "guide": "차변과 대변 합계가 일치하는지 확인하세요.",
                "error_guides": [],
                "doc_type": current_form.get("doc_type", "일반전표"),
                "description": current_form.get("description", ""),
                "amount": new_amount,
            }
        elif new_amount > 0:
            return {
                "success": True,
                "message": f"금액 {new_amount:,}원을 확인했습니다. 먼저 거래 내용(예: '자재 구매')을 입력해주세요.",
                "lines": [],
                "guide": "",
                "error_guides": [],
                "doc_type": "일반전표",
                "description": "",
                "amount": new_amount,
            }
        else:
            return {
                "success": True,
                "message": "수정할 금액을 알려주세요. 예: '총액은 1,155만원이야' 또는 '500만원으로 변경해줘'",
                "lines": current_form.get("lines", []) if current_form else [],
                "guide": "",
                "error_guides": [],
                "doc_type": current_form.get("doc_type", "일반전표") if current_form else "일반전표",
                "description": current_form.get("description", "") if current_form else "",
                "amount": 0,
            }

    # ── 2. 계정 변경 요청 ──
    if any(kw in msg_lower for kw in ['계정', '과목', '항목']):
        acct_match = re.search(r'(\d{5,7})', msg)
        if acct_match and current_form and current_form.get("lines"):
            new_code = acct_match.group(1)
            updated_lines = list(current_form["lines"])
            if updated_lines:
                updated_lines[0]["account_code"] = new_code
            return {
                "success": True,
                "message": f"첫 번째 항목의 계정코드를 {new_code}로 변경했습니다.",
                "lines": updated_lines,
                "guide": "계정코드가 올바른지 확인하세요.",
                "error_guides": [],
                "doc_type": current_form.get("doc_type", "일반전표"),
                "description": current_form.get("description", ""),
                "amount": sum(l.get("debit_amount", 0) for l in updated_lines),
            }

    # ── 3. 부가세 분리 요청 ──
    if any(kw in msg_lower for kw in ['부가세', 'vat', '세금', '공급가']):
        if current_form and current_form.get("lines"):
            lines = current_form["lines"]
            total = sum(l.get("debit_amount", 0) for l in lines)
            if total > 0:
                supply = int(total / 1.1)
                vat = total - supply
                updated_lines = []
                for line in lines:
                    if line.get("debit_amount", 0) > 0:
                        new_line = dict(line)
                        new_line["debit_amount"] = supply
                        updated_lines.append(new_line)
                updated_lines.append({
                    "account_code": "1100401",
                    "account_name": "부가세대급금",
                    "debit_amount": vat,
                    "credit_amount": 0,
                    "side": "차변",
                })
                for line in lines:
                    if line.get("credit_amount", 0) > 0:
                        updated_lines.append(dict(line))

                return {
                    "success": True,
                    "message": f"부가세를 분리했습니다. 공급가액: {supply:,}원, 부가세: {vat:,}원",
                    "lines": updated_lines,
                    "guide": "부가세 별도 거래인 경우 세금계산서를 확인하세요.",
                    "error_guides": [],
                    "doc_type": current_form.get("doc_type", "일반전표"),
                    "description": current_form.get("description", ""),
                    "amount": total,
                }

    # ── 4. 기본 전표 생성 (기존 parse_chat_input 로직) ──
    from ai_engine import parse_chat_input
    import json as _json
    try:
        with open('account_master.json', 'r', encoding='utf-8') as _f:
            _acct = _json.load(_f)
    except:
        _acct = {}
    result = parse_chat_input(msg)

    if not result.get("success"):
        result["message"] = (
            "입력을 이해하지 못했습니다. 아래와 같이 입력해 보세요:\n\n"
            "- 전표 생성: '자재 구매 500만원', '외주비 1000만원'\n"
            "- 금액 수정: '총액은 1,155만원이야', '500만원으로 변경해줘'\n"
            "- 부가세 분리: '부가세 분리해줘'\n"
            "- 계정 변경: '계정을 4200201로 바꿔줘'"
        )
        result["success"] = True

    return result


def process_chat(message: str, history: list = None, current_form: dict = None, api_key=None) -> dict:
    """챗 메시지를 처리한다. Gemini API가 있으면 사용, 없으면 로컬 파서."""

    if api_key or HAS_LLM:
        messages = []
        for h in (history or []):
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})
        return chat_with_gemini(messages, current_form, api_key=api_key)
    else:
        return chat_with_local(message, current_form)
