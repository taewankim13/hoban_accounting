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


PDF_EXTS = {'.pdf'}
IMG_PARSE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif'}
ALL_PARSEABLE_EXTS = IMG_PARSE_EXTS | PDF_EXTS


def pdf_to_image_path(pdf_path: str) -> str | None:
    """PDF 첫 페이지를 PNG 이미지로 변환하여 임시 파일 경로를 반환한다."""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return None
        page = doc[0]
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        out_path = pdf_path.rsplit('.', 1)[0] + '_page1.png'
        pix.save(out_path)
        doc.close()
        print(f"[증빙파싱] PDF→PNG 변환: {out_path} ({pix.width}x{pix.height})")
        return out_path
    except Exception as e:
        print(f"[증빙파싱] PDF 변환 실패: {e}")
        return None


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


EVIDENCE_PARSE_PROMPTS = {
    "계약서": """이 이미지는 계약서 문서입니다. 이미지에서 다음 기본 항목을 추출하세요.

기본 항목 (반드시 포함):
1. 계약서 제목 - 계약서의 제목 또는 명칭
2. 계약서명 - 계약자들의 서명/날인 여부 (서명완료/미서명)
3. 계약일자 - 계약 체결일 (YYYY-MM-DD 형식)
4. 계약기간 - 계약 유효 기간 (시작일 ~ 종료일)
5. 계약금액 - 계약 총 금액 (원 단위, 숫자만)
6. 계약대상 - 계약의 대상 (공사명, 용역명, 물품명 등)
7. 계약자 상호 - 계약 당사자들의 상호/회사명 (발주자, 수급자 등)

추가 항목 (이미지에서 발견되는 경우 자유롭게 추가):
예: 납품장소, 하자보증기간, 지체상금률, 계약보증금, 선급금, 공급가액, 부가세, 대금지급조건, 특약사항 등

규칙:
- 기본 항목 중 이미지에서 확인할 수 없는 항목은 값을 빈 문자열("")로 남기세요
- 추가 항목은 이미지에서 확인된 것만 포함하세요
- 금액은 숫자만 입력하세요 (예: 50000000)

반드시 아래 JSON 배열 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요:
[
  {"label": "계약서 제목", "value": ""},
  {"label": "계약서명", "value": ""},
  {"label": "계약일자", "value": ""},
  {"label": "계약기간", "value": ""},
  {"label": "계약금액", "value": ""},
  {"label": "계약대상", "value": ""},
  {"label": "계약자 상호", "value": ""}
]""",
    "공과금 고지서": """이 이미지는 공과금 고지서(전기요금, 가스요금, 수도요금 등)입니다.
이미지에서 다음 항목을 추출하세요.

기본 항목 (반드시 포함):
1. 고지서구분 - 전기/가스/수도/난방/통신 등 고지서 종류
2. 대상주소 - 요금 부과 대상 주소 (건물명, 동호수 포함)
3. 기준년월 - 요금 산정 기준 년월 (YYYY-MM 형식)
4. 기준일자 - 검침일자 또는 고지일자 (YYYY-MM-DD 형식)
5. 거래처명 - 공급사 상호 (한국전력공사, 한국가스공사, 수도사업소 등)
6. 거래처코드 - 공급사 사업자번호 또는 고객번호
7. 공급가액 - 공급가액 (원 단위, 숫자만)
8. 부가세액 - 부가가치세 (원 단위, 숫자만)
9. 합계금액 - 총 납부금액 (원 단위, 숫자만)
10. 당월요금계 - 당월 사용 요금 합계 (원 단위, 숫자만)

추가 항목 (이미지에서 발견되는 경우 자유롭게 추가):
예: 사용량, 납부기한, 고객번호, 전월지침, 당월지침, 검침기간, 연체가산금, 기본요금, 사용요금, 전력산업기반기금, 환경개선부담금, TV수신료 등

규칙:
- 기본 항목 중 이미지에서 확인할 수 없는 항목은 값을 빈 문자열("")로 남기세요
- 추가 항목은 이미지에서 확인된 것만 포함하세요
- 금액은 숫자만 입력하세요 (예: 1234560)

반드시 아래 JSON 배열 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요:
[
  {"label": "고지서구분", "value": ""},
  {"label": "대상주소", "value": ""},
  {"label": "기준년월", "value": ""},
  {"label": "기준일자", "value": ""},
  {"label": "거래처명", "value": ""},
  {"label": "거래처코드", "value": ""},
  {"label": "공급가액", "value": ""},
  {"label": "부가세액", "value": ""},
  {"label": "합계금액", "value": ""},
  {"label": "당월요금계", "value": ""}
]""",
}

PARSEABLE_EVIDENCE_TYPES = set(EVIDENCE_PARSE_PROMPTS.keys())


def parse_evidence_document(image_path: str, evidence_type: str) -> dict:
    """증빙 문서를 LLM Vision으로 파싱하여 구조화된 데이터를 추출한다. 이미지 및 PDF 지원."""
    if not HAS_LLM_VISION:
        return {"success": False, "error": "ALPHA_API_KEY가 설정되지 않았습니다."}

    if evidence_type not in EVIDENCE_PARSE_PROMPTS:
        return {"success": False, "error": f"파싱을 지원하지 않는 증빙 유형입니다: {evidence_type}"}

    converted_path = None
    try:
        prompt = EVIDENCE_PARSE_PROMPTS[evidence_type]

        ext = os.path.splitext(image_path)[1].lower()
        actual_path = image_path
        if ext in PDF_EXTS:
            converted_path = pdf_to_image_path(image_path)
            if not converted_path:
                return {"success": False, "error": "PDF 변환에 실패했습니다."}
            actual_path = converted_path

        img_base64, mime = resize_and_encode_image(actual_path)

        payload = {
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_base64}"}}
                ]
            }],
            "max_tokens": 4096,
        }

        headers = {
            "Authorization": f"Bearer {ALPHA_API_KEY}",
            "Content-Type": "application/json",
        }

        response = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()

        result = response.json()
        text = (result["choices"][0]["message"].get("content") or "").strip()

        if not text:
            return {"success": False, "error": "LLM 응답이 비어있습니다."}

        # JSON 배열 추출
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        if not text.startswith('['):
            idx = text.find('[')
            if idx >= 0:
                text = text[idx:]
            last_bracket = text.rfind(']')
            if last_bracket >= 0:
                text = text[:last_bracket + 1]

        fields = json.loads(text)

        if not isinstance(fields, list):
            return {"success": False, "error": "LLM 응답 형식이 올바르지 않습니다."}

        # 각 항목이 {label, value} 형식인지 검증
        validated = []
        for item in fields:
            if isinstance(item, dict) and "label" in item:
                validated.append({
                    "label": str(item.get("label", "")),
                    "value": str(item.get("value", ""))
                })

        print(f"[증빙파싱] {evidence_type} 파싱 완료: {len(validated)}개 항목 추출")
        return {"success": True, "fields": validated, "evidence_type": evidence_type}

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"API 호출 오류: {str(e)}"}
    except json.JSONDecodeError:
        return {"success": False, "error": "LLM 응답 JSON 파싱 실패"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if converted_path and os.path.exists(converted_path):
            os.remove(converted_path)


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
