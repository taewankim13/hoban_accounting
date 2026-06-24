"""영수증/세금계산서 이미지에서 정보를 추출하는 OCR 파서.
실제 운영 환경에서는 Tesseract OCR 또는 클라우드 OCR API를 사용하지만,
PoC에서는 파일명과 간단한 규칙 기반으로 시뮬레이션한다.
Tesseract가 설치되어 있으면 실제 OCR을 수행한다.
"""
import re
import os
import random


def try_tesseract_ocr(image_path: str) -> str | None:
    """Tesseract OCR로 이미지에서 텍스트를 추출한다. 설치되지 않으면 None 반환."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang='kor+eng')
        return text
    except Exception:
        return None


def parse_receipt_image(image_path: str, filename: str = "") -> dict:
    """영수증/세금계산서 이미지를 분석하여 전표 정보를 추출한다."""

    # 1. LLM Vision API 우선 (Gemini)
    try:
        from llm_vision import analyze_receipt_with_llm, map_to_account, HAS_LLM_VISION
        if HAS_LLM_VISION:
            llm_result = analyze_receipt_with_llm(image_path)
            if llm_result.get("success"):
                acct = map_to_account(llm_result)
                return {
                    "success": True,
                    "ocr_mode": "llm_vision",
                    "amount": llm_result.get("amount", 0),
                    "supply_amount": llm_result.get("supply_amount", 0),
                    "tax_amount": llm_result.get("tax_amount", 0),
                    "vendor": llm_result.get("vendor", ""),
                    "biz_no": llm_result.get("biz_no", ""),
                    "date": llm_result.get("date", ""),
                    "items": llm_result.get("items", []),
                    "doc_type": llm_result.get("doc_type", ""),
                    "buyer": llm_result.get("buyer", ""),
                    "suggested_account": acct["suggested_account"],
                    "suggested_account_name": acct["suggested_account_name"],
                    "suggested_credit_account": acct["suggested_credit_account"],
                    "description": acct["description"],
                    "lines": acct["lines"],
                    "raw_text": llm_result.get("raw_text", ""),
                }
            else:
                # LLM 호출은 성공했지만 파싱 실패
                error_msg = llm_result.get("error", "LLM 분석 실패")
                print(f"[OCR] LLM Vision 파싱 실패: {error_msg}")
                return {"success": False, "ocr_mode": "llm_vision", "error": error_msg, "amount": 0, "vendor": "", "date": ""}
    except Exception as e:
        print(f"[OCR] LLM Vision 예외: {e}")

    # 2. Tesseract OCR 시도
    ocr_text = try_tesseract_ocr(image_path)
    if ocr_text and len(ocr_text.strip()) > 20:
        return parse_ocr_text(ocr_text)

    # 3. LLM도 Tesseract도 없으면 에러 반환 (시뮬레이션 금지)
    return {"success": False, "ocr_mode": "none", "error": "이미지를 분석할 수 없습니다. LLM API 또는 Tesseract OCR이 필요합니다.", "amount": 0, "vendor": "", "date": ""}


def parse_ocr_text(text: str) -> dict:
    """OCR 텍스트에서 금액, 업종, 날짜 등을 추출한다."""
    result = {
        "success": True,
        "ocr_mode": "tesseract",
        "amount": 0,
        "vendor": "",
        "date": "",
        "items": "",
        "doc_type": "일반전표",
        "suggested_account": "",
        "suggested_account_name": "",
        "description": "",
        "raw_text": text[:500],
    }

    # 금액 추출 (합계, 총액, 공급가액 등)
    amount_patterns = [
        r'합\s*계\s*[:\s]*([0-9,]+)',
        r'총\s*액\s*[:\s]*([0-9,]+)',
        r'공급가액\s*[:\s]*([0-9,]+)',
        r'결제\s*금액\s*[:\s]*([0-9,]+)',
        r'총\s*금액\s*[:\s]*([0-9,]+)',
        r'(\d{1,3}(?:,\d{3})+)\s*원',
    ]
    for pattern in amount_patterns:
        match = re.search(pattern, text)
        if match:
            result["amount"] = int(match.group(1).replace(",", ""))
            break

    # 날짜 추출
    date_patterns = [
        r'(\d{4})[./-](\d{1,2})[./-](\d{1,2})',
        r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            y, m, d = match.groups()
            result["date"] = f"{y}-{int(m):02d}-{int(d):02d}"
            break

    # 업종/품목 키워드로 계정 추정
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["철근", "시멘트", "레미콘", "자재", "건축자재", "배관"]):
        result["suggested_account"] = "5010"
        result["suggested_account_name"] = "자재비"
    elif any(kw in text_lower for kw in ["주유", "경유", "휘발유", "가솔린"]):
        result["suggested_account"] = "5040"
        result["suggested_account_name"] = "경비"
    elif any(kw in text_lower for kw in ["식당", "음식", "식사", "점심", "저녁"]):
        result["suggested_account"] = "6030"
        result["suggested_account_name"] = "복리후생비"
    elif any(kw in text_lower for kw in ["택시", "교통", "주차", "톨게이트", "기차", "ktx"]):
        result["suggested_account"] = "6040"
        result["suggested_account_name"] = "여비교통비"
    elif any(kw in text_lower for kw in ["사무용품", "복사", "프린터", "토너"]):
        result["suggested_account"] = "6170"
        result["suggested_account_name"] = "소모품비"
    elif any(kw in text_lower for kw in ["렌탈", "임대", "장비", "크레인", "포클레인"]):
        result["suggested_account"] = "5070"
        result["suggested_account_name"] = "장비사용료"
    elif any(kw in text_lower for kw in ["세금계산서", "공급가액"]):
        result["suggested_account"] = "5010"
        result["suggested_account_name"] = "자재비"
    else:
        result["suggested_account"] = "5040"
        result["suggested_account_name"] = "경비"

    # 상호명 추출 (첫 번째 줄 또는 '상호' 키워드 후)
    vendor_match = re.search(r'상\s*호\s*[:\s]*(.+)', text)
    if vendor_match:
        result["vendor"] = vendor_match.group(1).strip()[:30]
    else:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if lines:
            result["vendor"] = lines[0][:30]

    result["description"] = f"{result['vendor']} - {result['suggested_account_name']}"

    return result


def simulate_receipt_parse(filename: str) -> dict:
    """파일명 기반으로 영수증 정보를 시뮬레이션한다 (PoC용)."""
    filename_lower = filename.lower()

    # 파일명에서 키워드 매칭
    if any(kw in filename_lower for kw in ["자재", "철근", "시멘트", "레미콘", "건자재"]):
        return _mock_result("자재비", "5010", "2010", "건자재 구매", random.randint(50, 500) * 10000)
    elif any(kw in filename_lower for kw in ["주유", "기름", "경유"]):
        return _mock_result("경비", "5040", "1020", "차량 주유비", random.randint(5, 20) * 10000)
    elif any(kw in filename_lower for kw in ["식대", "식사", "점심", "회식"]):
        return _mock_result("복리후생비", "6030", "1020", "직원 식대", random.randint(5, 30) * 10000)
    elif any(kw in filename_lower for kw in ["택시", "교통", "주차"]):
        return _mock_result("여비교통비", "6040", "1010", "교통비", random.randint(1, 10) * 10000)
    elif any(kw in filename_lower for kw in ["장비", "렌탈", "크레인"]):
        return _mock_result("장비사용료", "5070", "2030", "장비 렌탈료", random.randint(100, 500) * 10000)
    elif any(kw in filename_lower for kw in ["세금계산서", "invoice", "tax"]):
        return _mock_result("외주비", "5030", "2010", "외주 용역비", random.randint(300, 2000) * 10000)
    else:
        # 기본: 경비 처리
        return _mock_result("경비", "5040", "1020", "영수증 기반 경비", random.randint(3, 50) * 10000)


def _mock_result(account_name, debit_code, credit_code, desc, amount):
    return {
        "success": True,
        "ocr_mode": "simulation",
        "amount": amount,
        "vendor": "거래처(OCR 추출 예정)",
        "date": "",
        "items": desc,
        "doc_type": "일반전표",
        "suggested_account": debit_code,
        "suggested_account_name": account_name,
        "suggested_credit_account": credit_code,
        "description": desc,
        "raw_text": f"[시뮬레이션] 파일명 기반 추정: {desc} {amount:,}원",
    }
