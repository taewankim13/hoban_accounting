"""LLM Vision API 연동 - 세금계산서/영수증 이미지 분석
PwC Workspace Gemini API (OpenAI-compatible) 사용
"""
import os
import json
import base64
import requests

# .env 파일에서 API 키 로드
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

ALPHA_API_KEY = os.environ.get("ALPHA_API_KEY", "")
API_URL = "https://workspace.kr.pwc.com/api/workspace/coding_agent/v1/chat/completions"
MODEL = "Gemini_3.1_Pro"

HAS_LLM_VISION = bool(ALPHA_API_KEY)

PARSE_PROMPT = """이 이미지는 세금계산서, 영수증, 거래명세서, 또는 카드전표입니다.
이미지에서 다음 정보를 추출하여 반드시 JSON 형식으로만 응답하세요.

추출 항목:
1. date: 작성일자 또는 거래일자 (YYYY-MM-DD 형식)
2. vendor: 공급자(거래처) 상호명
3. biz_no: 공급자 사업자번호
4. amount: 합계금액 (숫자만, 원 단위)
5. supply_amount: 공급가액 (숫자만)
6. tax_amount: 부가세액 (숫자만)
7. items: 품목 목록 (배열, 각 항목은 {name, qty, unit_price, amount})
8. doc_type: 문서 유형 (세금계산서/영수증/거래명세서/카드전표 중 하나)
9. buyer: 공급받는자 상호명

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요:
{"date":"","vendor":"","biz_no":"","amount":0,"supply_amount":0,"tax_amount":0,"items":[],"doc_type":"","buyer":""}
"""


def resize_and_encode_image(image_path: str, max_size_bytes: int = 1_500_000) -> tuple[str, str]:
    """이미지를 리사이즈하고 base64로 인코딩한다. (max_size_bytes 이하로 압축)"""
    file_size = os.path.getsize(image_path)

    # 이미 작은 파일은 그대로
    if file_size <= max_size_bytes:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(image_path)[1].lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "image/png")
        return b64, mime

    # 큰 파일은 리사이즈
    try:
        from PIL import Image
        import io
        img = Image.open(image_path)

        # RGBA → RGB 변환 (JPEG 저장용)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # 긴 변이 2000px 이하로 축소
        max_dim = 2000
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        # JPEG로 압축 (품질 조절)
        for quality in [85, 70, 55]:
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality)
            if buf.tell() <= max_size_bytes:
                break
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("utf-8")
        print(f"[OCR] 이미지 리사이즈: {file_size:,} → {buf.tell():,} bytes ({img.size})")
        return b64, "image/jpeg"
    except Exception as e:
        print(f"[OCR] 리사이즈 실패, 원본 사용: {e}")
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return b64, "image/png"


def analyze_receipt_with_llm(image_path: str) -> dict:
    """LLM Vision API로 세금계산서/영수증 이미지를 분석한다."""
    if not HAS_LLM_VISION:
        return {"success": False, "error": "ALPHA_API_KEY가 설정되지 않았습니다. .env 파일에 ALPHA_API_KEY=xxx를 추가하세요."}

    try:
        img_base64, mime = resize_and_encode_image(image_path)

        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PARSE_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_base64}"}}
                    ]
                }
            ],
            "max_tokens": 4096,
        }

        headers = {
            "Authorization": f"Bearer {ALPHA_API_KEY}",
            "Content-Type": "application/json",
        }

        response = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()

        result = response.json()
        msg = result["choices"][0]["message"]
        text = (msg.get("content") or "").strip()

        if not text:
            return {"success": False, "error": "LLM 응답에 content가 비어있습니다.", "ocr_mode": "llm_vision"}

        # JSON 추출
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        if not text.startswith('{'):
            idx = text.find('{')
            if idx >= 0:
                text = text[idx:]
            # 마지막 } 까지만
            last_brace = text.rfind('}')
            if last_brace >= 0:
                text = text[:last_brace + 1]

        parsed = json.loads(text)

        return {
            "success": True,
            "ocr_mode": "llm_vision",
            "date": parsed.get("date", ""),
            "vendor": parsed.get("vendor", ""),
            "biz_no": parsed.get("biz_no", ""),
            "amount": int(float(parsed.get("amount", 0))),
            "supply_amount": int(float(parsed.get("supply_amount", 0))),
            "tax_amount": int(float(parsed.get("tax_amount", 0))),
            "items": parsed.get("items", []),
            "doc_type": parsed.get("doc_type", ""),
            "buyer": parsed.get("buyer", ""),
            "raw_text": text,
        }

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"API 호출 오류: {str(e)}", "ocr_mode": "llm_vision"}
    except json.JSONDecodeError:
        return {"success": False, "error": "LLM 응답 파싱 실패", "ocr_mode": "llm_vision", "raw_text": text if 'text' in dir() else ""}
    except Exception as e:
        return {"success": False, "error": str(e), "ocr_mode": "llm_vision"}


def map_to_account(parsed: dict) -> dict:
    """LLM 파싱 결과를 전표 입력용 데이터로 변환한다."""
    doc_type = parsed.get("doc_type", "")
    amount = parsed.get("amount", 0)
    supply = parsed.get("supply_amount", 0)
    tax = parsed.get("tax_amount", 0)

    # 계정 추정
    account_master = {}
    try:
        with open("account_master.json", "r", encoding="utf-8") as f:
            account_master = json.load(f)
    except:
        pass

    # 기본 계정 매핑
    suggested_debit = "4200120"  # 지급수수료(일반)
    suggested_debit_name = account_master.get(suggested_debit, "지급수수료(일반)")
    suggested_credit = "2100303"  # 미지급금(일반)

    # 품목 키워드로 계정 추정
    items_text = " ".join(i.get("name", "") for i in parsed.get("items", [])).lower()
    vendor = (parsed.get("vendor", "") or "").lower()
    all_text = items_text + " " + vendor

    if any(kw in all_text for kw in ["자재", "철근", "시멘트", "레미콘", "건자재", "배관"]):
        suggested_debit = "4200101"
        suggested_debit_name = account_master.get(suggested_debit, "재료비(일반)")
    elif any(kw in all_text for kw in ["임대", "임차", "월세", "숙소"]):
        suggested_debit = "4200113"
        suggested_debit_name = account_master.get(suggested_debit, "임차료(일반)")
    elif any(kw in all_text for kw in ["식대", "음식", "식사", "급식"]):
        suggested_debit = "4200109"
        suggested_debit_name = account_master.get(suggested_debit, "복리후생비(일반)")
    elif any(kw in all_text for kw in ["교통", "택시", "주차", "톨게이트"]):
        suggested_debit = "4200110"
        suggested_debit_name = account_master.get(suggested_debit, "여비교통비(일반)")
    elif any(kw in all_text for kw in ["통신", "전화", "인터넷"]):
        suggested_debit = "4200133"
        suggested_debit_name = account_master.get(suggested_debit, "통신비(일반)")
    elif any(kw in all_text for kw in ["소모품", "사무용품", "복사"]):
        suggested_debit = "4200128"
        suggested_debit_name = account_master.get(suggested_debit, "소모품비(일반)")

    # 부가세 분리 여부
    lines = []
    if tax > 0 and supply > 0:
        lines = [
            {"account_code": suggested_debit, "account_name": suggested_debit_name, "debit_amount": supply, "credit_amount": 0, "side": "차변"},
            {"account_code": "1112800", "account_name": account_master.get("1112800", "부가세대급금"), "debit_amount": tax, "credit_amount": 0, "side": "차변"},
            {"account_code": suggested_credit, "account_name": account_master.get(suggested_credit, "미지급금(일반)"), "debit_amount": 0, "credit_amount": amount, "side": "대변"},
        ]
    else:
        lines = [
            {"account_code": suggested_debit, "account_name": suggested_debit_name, "debit_amount": amount, "credit_amount": 0, "side": "차변"},
            {"account_code": suggested_credit, "account_name": account_master.get(suggested_credit, "미지급금(일반)"), "debit_amount": 0, "credit_amount": amount, "side": "대변"},
        ]

    return {
        "lines": lines,
        "suggested_account": suggested_debit,
        "suggested_account_name": suggested_debit_name,
        "suggested_credit_account": suggested_credit,
        "description": f"{parsed.get('vendor', '')} - {suggested_debit_name}",
    }
