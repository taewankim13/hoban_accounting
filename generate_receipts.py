"""가짜 세금계산서, 영수증, 인보이스 이미지를 생성한다."""
import os
import random
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta

OUTPUT_DIR = "static/uploads"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 폰트 설정 (Windows 기본 폰트 사용)
def get_font(size):
    font_paths = [
        "C:/Windows/Fonts/malgun.ttf",      # 맑은 고딕
        "C:/Windows/Fonts/gulim.ttc",        # 굴림
        "C:/Windows/Fonts/batang.ttc",       # 바탕
        "C:/Windows/Fonts/arial.ttf",        # Arial
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()

FONT_TITLE = get_font(28)
FONT_HEADER = get_font(20)
FONT_BODY = get_font(16)
FONT_SMALL = get_font(13)
FONT_LABEL = get_font(14)

# 색상
WHITE = (255, 255, 255)
BLACK = (30, 30, 30)
DARK_GRAY = (87, 85, 83)
LIGHT_GRAY = (200, 200, 200)
ORANGE = (238, 117, 0)
BLUE = (30, 80, 160)
RED = (200, 30, 30)
BG_CREAM = (252, 250, 245)
BG_LIGHT_BLUE = (240, 245, 255)
BG_LIGHT_GREEN = (242, 252, 242)

# 거래처 목록
VENDORS = [
    ("(주)대한철강", "123-45-67890", "서울 강서구 공항대로 123"),
    ("성진건자재", "234-56-78901", "경기 화성시 동탄대로 456"),
    ("한국레미콘(주)", "345-67-89012", "인천 남동구 논현로 789"),
    ("삼성전기설비", "456-78-90123", "서울 송파구 올림픽로 321"),
    ("현대중장비렌탈", "567-89-01234", "경기 용인시 처인구 백옥대로 55"),
    ("(주)동부시멘트", "678-90-12345", "충남 보령시 대천로 100"),
    ("금성도장공업", "789-01-23456", "경기 안산시 단원구 목내로 88"),
    ("우리안전(주)", "890-12-34567", "서울 영등포구 여의대로 200"),
    ("대우설계엔지니어링", "901-23-45678", "서울 강남구 테헤란로 150"),
    ("호반건설(주)", "111-22-33333", "서울 서초구 서초대로 74길 14"),
]

ITEMS_BY_TYPE = {
    "자재": [("철근 SD400 D25", "ton", 850000), ("시멘트 포틀랜드", "포", 6500), ("레미콘 25-24-15", "m3", 72000), ("배관자재 일식", "식", 1500000), ("합판 12mm", "매", 18000)],
    "외주": [("철근 가공 및 조립", "식", 15000000), ("전기 배관 공사", "식", 8000000), ("도장 공사", "식", 5000000), ("타일 시공", "식", 12000000), ("방수 공사", "식", 7000000)],
    "장비": [("타워크레인 렌탈", "월", 8000000), ("포클레인 0.7m3", "일", 350000), ("펌프카 36m", "회", 550000), ("덤프트럭 15톤", "일", 280000)],
    "경비": [("현장 경유", "L", 1650), ("사무용품", "식", 150000), ("현장 식대", "식", 8000), ("안전용품", "식", 500000)],
    "노무": [("현장 일용직 노무", "인/일", 180000), ("특수공 기능직", "인/일", 250000), ("보통인부", "인/일", 150000)],
}


def draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """둥근 모서리 사각형"""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def generate_tax_invoice(idx, vendor_info, items, amount, date_str, doc_no):
    """세금계산서 이미지 생성"""
    W, H = 700, 900
    img = Image.new("RGB", (W, H), BG_LIGHT_BLUE)
    d = ImageDraw.Draw(img)

    # 상단 헤더
    d.rectangle([0, 0, W, 70], fill=BLUE)
    d.text((W//2, 35), "전 자 세 금 계 산 서", fill=WHITE, font=FONT_TITLE, anchor="mm")

    # 승인번호
    approval_no = f"{random.randint(20260501, 20260531)}-{random.randint(41000000, 41999999)}-{random.randint(10000000, 99999999)}"
    d.text((20, 80), f"승인번호: {approval_no}", fill=DARK_GRAY, font=FONT_SMALL)
    d.text((W-20, 80), f"작성일자: {date_str}", fill=DARK_GRAY, font=FONT_SMALL, anchor="ra")

    # 공급자 / 공급받는자 박스
    y = 105
    d.rectangle([20, y, W//2-10, y+180], outline=BLUE, width=2)
    d.rectangle([20, y, W//2-10, y+30], fill=(220, 230, 245))
    d.text((W//4-5, y+15), "공 급 자", fill=BLUE, font=FONT_LABEL, anchor="mm")

    d.rectangle([W//2+10, y, W-20, y+180], outline=BLUE, width=2)
    d.rectangle([W//2+10, y, W-20, y+30], fill=(220, 230, 245))
    d.text((W*3//4+5, y+15), "공 급 받 는 자", fill=BLUE, font=FONT_LABEL, anchor="mm")

    vendor_name, vendor_biz, vendor_addr = vendor_info
    d.text((30, y+40), f"사업자번호: {vendor_biz}", fill=BLACK, font=FONT_SMALL)
    d.text((30, y+60), f"상    호: {vendor_name}", fill=BLACK, font=FONT_SMALL)
    d.text((30, y+80), f"대 표 자: {'김' + vendor_name[3] if len(vendor_name) > 3 else '김대표'}", fill=BLACK, font=FONT_SMALL)
    d.text((30, y+100), f"주    소: {vendor_addr[:18]}", fill=BLACK, font=FONT_SMALL)
    d.text((30, y+120), f"업    태: 제조, 건설", fill=BLACK, font=FONT_SMALL)
    d.text((30, y+140), f"종    목: {vendor_name[2:4] if len(vendor_name) > 3 else '건자재'}", fill=BLACK, font=FONT_SMALL)

    d.text((W//2+20, y+40), f"사업자번호: 111-22-33333", fill=BLACK, font=FONT_SMALL)
    d.text((W//2+20, y+60), f"상    호: 호반건설(주)", fill=BLACK, font=FONT_SMALL)
    d.text((W//2+20, y+80), f"대 표 자: 김상열", fill=BLACK, font=FONT_SMALL)
    d.text((W//2+20, y+100), f"주    소: 서울 서초구", fill=BLACK, font=FONT_SMALL)
    d.text((W//2+20, y+120), f"업    태: 건설업", fill=BLACK, font=FONT_SMALL)
    d.text((W//2+20, y+140), f"종    목: 종합건설", fill=BLACK, font=FONT_SMALL)

    # 금액 요약
    y = 300
    supply = int(amount / 1.1)
    tax = amount - supply
    d.rectangle([20, y, W-20, y+40], fill=(220, 230, 245), outline=BLUE, width=1)
    d.text((30, y+10), f"공급가액:  {supply:>15,}원", fill=BLACK, font=FONT_BODY)
    d.text((W//2+20, y+10), f"세    액:  {tax:>15,}원", fill=BLACK, font=FONT_BODY)

    d.rectangle([20, y+40, W-20, y+70], outline=BLUE, width=1)
    d.text((30, y+48), f"합 계 금 액:  {amount:>20,}원", fill=RED, font=FONT_HEADER)

    # 품목 테이블
    y = 390
    cols = [20, 50, 280, 360, 440, 540, W-20]
    headers = ["No", "품    목", "규격", "수량", "단가", "공급가액"]
    d.rectangle([20, y, W-20, y+30], fill=(220, 230, 245), outline=BLUE, width=1)
    for i, h in enumerate(headers):
        d.text((cols[i]+5, y+8), h, fill=BLUE, font=FONT_SMALL)

    for row_i, (item_name, unit, unit_price) in enumerate(items[:5]):
        ry = y + 30 + row_i * 28
        qty = random.randint(1, 20)
        line_amt = qty * unit_price
        d.rectangle([20, ry, W-20, ry+28], outline=LIGHT_GRAY, width=1)
        d.text((cols[0]+5, ry+6), str(row_i+1), fill=BLACK, font=FONT_SMALL)
        d.text((cols[1]+5, ry+6), item_name[:12], fill=BLACK, font=FONT_SMALL)
        d.text((cols[2]+5, ry+6), unit, fill=BLACK, font=FONT_SMALL)
        d.text((cols[3]+5, ry+6), str(qty), fill=BLACK, font=FONT_SMALL)
        d.text((cols[4]+5, ry+6), f"{unit_price:,}", fill=BLACK, font=FONT_SMALL)
        d.text((cols[5]+5, ry+6), f"{line_amt:,}", fill=BLACK, font=FONT_SMALL)

    # 하단 비고
    y = 680
    d.rectangle([20, y, W-20, y+50], outline=BLUE, width=1)
    d.text((30, y+5), f"비고: 전표번호 {doc_no}", fill=DARK_GRAY, font=FONT_SMALL)
    d.text((30, y+25), f"     현장 납품 완료 확인", fill=DARK_GRAY, font=FONT_SMALL)

    # 인감 영역 (빨간 원)
    cx, cy = W-80, y+25
    d.ellipse([cx-25, cy-25, cx+25, cy+25], outline=RED, width=2)
    d.text((cx, cy), "인", fill=RED, font=FONT_HEADER, anchor="mm")

    # 하단 안내
    d.text((W//2, H-30), "이 전자세금계산서는 국세청에 전송되었습니다", fill=DARK_GRAY, font=FONT_SMALL, anchor="mm")

    fname = f"tax_invoice_{idx:03d}.png"
    img.save(os.path.join(OUTPUT_DIR, fname), quality=95)
    return f"/static/uploads/{fname}"


def generate_receipt(idx, vendor_info, item_desc, amount, date_str, doc_no):
    """간이영수증 / 카드전표 이미지 생성"""
    W, H = 400, 600
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    vendor_name, vendor_biz, vendor_addr = vendor_info
    is_card = random.choice([True, False])

    # 상단
    d.rectangle([0, 0, W, 55], fill=DARK_GRAY)
    title = "신용카드 매출전표" if is_card else "현 금 영 수 증"
    d.text((W//2, 28), title, fill=WHITE, font=FONT_HEADER, anchor="mm")

    y = 70
    d.text((W//2, y), vendor_name, fill=BLACK, font=FONT_HEADER, anchor="mm")
    y += 28
    d.text((W//2, y), f"사업자번호: {vendor_biz}", fill=DARK_GRAY, font=FONT_SMALL, anchor="mm")
    y += 20
    d.text((W//2, y), vendor_addr[:20], fill=DARK_GRAY, font=FONT_SMALL, anchor="mm")
    y += 20
    d.text((W//2, y), f"TEL: 02-{random.randint(1000,9999)}-{random.randint(1000,9999)}", fill=DARK_GRAY, font=FONT_SMALL, anchor="mm")

    y += 30
    d.line([(20, y), (W-20, y)], fill=LIGHT_GRAY, width=2)

    y += 15
    d.text((20, y), f"일시: {date_str}  {random.randint(9,18):02d}:{random.randint(0,59):02d}", fill=BLACK, font=FONT_LABEL)
    y += 25

    if is_card:
        card_no = f"{random.randint(4000,5999)}-****-****-{random.randint(1000,9999)}"
        d.text((20, y), f"카드: {card_no}", fill=BLACK, font=FONT_LABEL)
        y += 22
        d.text((20, y), f"승인: {random.randint(10000000,99999999)}", fill=BLACK, font=FONT_LABEL)
        y += 25

    d.line([(20, y), (W-20, y)], fill=LIGHT_GRAY, width=1)
    y += 10

    # 품목
    d.text((20, y), "품 목", fill=DARK_GRAY, font=FONT_LABEL)
    d.text((W-20, y), "금 액", fill=DARK_GRAY, font=FONT_LABEL, anchor="ra")
    y += 25

    # 2~4 품목 랜덤
    n_items = random.randint(1, 3)
    remaining = amount
    for i in range(n_items):
        if i == n_items - 1:
            line_amt = remaining
        else:
            line_amt = random.randint(int(amount * 0.2), int(amount * 0.5))
            remaining -= line_amt

        d.text((20, y), f"{item_desc[:15]}{' ' + str(i+1) if n_items > 1 else ''}", fill=BLACK, font=FONT_BODY)
        d.text((W-20, y), f"{line_amt:,}", fill=BLACK, font=FONT_BODY, anchor="ra")
        y += 24

    y += 10
    d.line([(20, y), (W-20, y)], fill=BLACK, width=2)
    y += 15

    # 합계
    supply = int(amount / 1.1)
    tax = amount - supply
    d.text((20, y), "공급가액", fill=DARK_GRAY, font=FONT_LABEL)
    d.text((W-20, y), f"{supply:,}원", fill=BLACK, font=FONT_LABEL, anchor="ra")
    y += 22
    d.text((20, y), "부 가 세", fill=DARK_GRAY, font=FONT_LABEL)
    d.text((W-20, y), f"{tax:,}원", fill=BLACK, font=FONT_LABEL, anchor="ra")
    y += 25
    d.line([(20, y), (W-20, y)], fill=ORANGE, width=3)
    y += 12
    d.text((20, y), "합    계", fill=BLACK, font=FONT_HEADER)
    d.text((W-20, y), f"{amount:,}원", fill=ORANGE, font=FONT_HEADER, anchor="ra")

    y += 45
    d.line([(20, y), (W-20, y)], fill=LIGHT_GRAY, width=1)
    y += 15
    d.text((W//2, y), f"전표번호: {doc_no}", fill=DARK_GRAY, font=FONT_SMALL, anchor="mm")
    y += 20
    d.text((W//2, y), "감사합니다", fill=DARK_GRAY, font=FONT_LABEL, anchor="mm")

    fname = f"receipt_{idx:03d}.png"
    img.save(os.path.join(OUTPUT_DIR, fname), quality=95)
    return f"/static/uploads/{fname}"


def generate_invoice(idx, vendor_info, items, amount, date_str, doc_no):
    """거래명세서 이미지 생성"""
    W, H = 700, 800
    img = Image.new("RGB", (W, H), BG_CREAM)
    d = ImageDraw.Draw(img)

    vendor_name, vendor_biz, vendor_addr = vendor_info

    # 상단
    d.rectangle([0, 0, W, 60], fill=ORANGE)
    d.text((W//2, 30), "거  래  명  세  서", fill=WHITE, font=FONT_TITLE, anchor="mm")

    y = 80
    d.text((20, y), f"No. INV-{date_str.replace('-','')}-{idx:03d}", fill=DARK_GRAY, font=FONT_SMALL)
    d.text((W-20, y), f"거래일자: {date_str}", fill=DARK_GRAY, font=FONT_SMALL, anchor="ra")

    # 수신/발신
    y = 110
    d.rectangle([20, y, W-20, y+80], outline=ORANGE, width=2)
    d.text((30, y+10), f"수  신: 호반건설(주)", fill=BLACK, font=FONT_BODY)
    d.text((30, y+32), f"발  신: {vendor_name}", fill=BLACK, font=FONT_BODY)
    d.text((30, y+54), f"사업자번호: {vendor_biz}  /  {vendor_addr[:20]}", fill=DARK_GRAY, font=FONT_SMALL)

    # 품목 테이블
    y = 210
    cols = [20, 55, 320, 400, 480, 580, W-20]
    headers = ["No", "품    명", "규격", "수량", "단가", "금액"]
    d.rectangle([20, y, W-20, y+28], fill=ORANGE)
    for i, h in enumerate(headers):
        d.text((cols[i]+5, y+6), h, fill=WHITE, font=FONT_SMALL)

    total_amt = 0
    for row_i, (item_name, unit, unit_price) in enumerate(items[:6]):
        ry = y + 28 + row_i * 26
        qty = random.randint(1, 30)
        line_amt = qty * unit_price
        total_amt += line_amt
        bg = WHITE if row_i % 2 == 0 else (248, 246, 242)
        d.rectangle([20, ry, W-20, ry+26], fill=bg, outline=LIGHT_GRAY, width=1)
        d.text((cols[0]+5, ry+5), str(row_i+1), fill=BLACK, font=FONT_SMALL)
        d.text((cols[1]+5, ry+5), item_name[:14], fill=BLACK, font=FONT_SMALL)
        d.text((cols[2]+5, ry+5), unit, fill=BLACK, font=FONT_SMALL)
        d.text((cols[3]+5, ry+5), str(qty), fill=BLACK, font=FONT_SMALL)
        d.text((cols[4]+5, ry+5), f"{unit_price:,}", fill=BLACK, font=FONT_SMALL)
        d.text((cols[5]+5, ry+5), f"{line_amt:,}", fill=BLACK, font=FONT_SMALL)

    # 합계
    y_total = y + 28 + min(len(items), 6) * 26 + 10
    d.rectangle([20, y_total, W-20, y_total+40], fill=(255, 245, 230), outline=ORANGE, width=2)
    d.text((30, y_total+10), f"합 계 금 액:    {amount:>20,} 원  (부가세 포함)", fill=ORANGE, font=FONT_HEADER)

    # 비고
    y_note = y_total + 60
    d.rectangle([20, y_note, W-20, y_note+50], outline=LIGHT_GRAY, width=1)
    d.text((30, y_note+8), f"비고: 전표번호 {doc_no}", fill=DARK_GRAY, font=FONT_SMALL)
    d.text((30, y_note+28), f"     현장 납품 검수 완료 / 하자보증기간: 1년", fill=DARK_GRAY, font=FONT_SMALL)

    # 인감
    cx, cy = W-70, y_note+90
    d.ellipse([cx-28, cy-28, cx+28, cy+28], outline=RED, width=2)
    d.text((cx, cy-8), vendor_name[:2], fill=RED, font=FONT_SMALL, anchor="mm")
    d.text((cx, cy+10), "인", fill=RED, font=FONT_SMALL, anchor="mm")

    d.text((W//2, H-25), "본 거래명세서는 상기와 같이 거래하였음을 확인합니다.", fill=DARK_GRAY, font=FONT_SMALL, anchor="mm")

    fname = f"invoice_{idx:03d}.png"
    img.save(os.path.join(OUTPUT_DIR, fname), quality=95)
    return f"/static/uploads/{fname}"


def generate_all_receipts(entries_info):
    """전표 목록에 대해 다양한 증빙 이미지를 생성하고 경로 리스트를 반환한다."""
    results = {}
    random.seed(123)

    for i, info in enumerate(entries_info):
        doc_no = info["doc_no"]
        amount = info["amount"]
        date_str = info["date"]
        desc = info["description"]
        doc_type = info.get("doc_type", "일반전표")

        vendor = random.choice(VENDORS)

        # 거래 유형에 따라 증빙 종류 결정
        if any(kw in desc for kw in ["자재", "시멘트", "레미콘", "철근", "배관"]):
            items = ITEMS_BY_TYPE["자재"]
            if amount > 10_000_000:
                path = generate_tax_invoice(i, vendor, items, amount, date_str, doc_no)
            else:
                path = generate_receipt(i, vendor, desc, amount, date_str, doc_no)
        elif any(kw in desc for kw in ["외주", "도장", "전기", "시공"]):
            items = ITEMS_BY_TYPE["외주"]
            doc_choice = random.choice(["tax", "invoice"])
            if doc_choice == "tax":
                path = generate_tax_invoice(i, vendor, items, amount, date_str, doc_no)
            else:
                path = generate_invoice(i, vendor, items, amount, date_str, doc_no)
        elif any(kw in desc for kw in ["장비", "렌탈", "크레인", "포클레인"]):
            items = ITEMS_BY_TYPE["장비"]
            path = generate_invoice(i, vendor, items, amount, date_str, doc_no)
        elif any(kw in desc for kw in ["노무", "일용"]):
            items = ITEMS_BY_TYPE["노무"]
            path = generate_tax_invoice(i, vendor, items, amount, date_str, doc_no)
        elif any(kw in desc for kw in ["급여", "복리", "여비", "교통", "소모", "통신", "임차", "수도", "보험", "접대"]):
            path = generate_receipt(i, vendor, desc, amount, date_str, doc_no)
        elif any(kw in desc for kw in ["공사수익", "선수금", "기성"]):
            items = ITEMS_BY_TYPE["외주"]
            path = generate_tax_invoice(i, vendor, items, amount, date_str, doc_no)
        elif any(kw in desc for kw in ["매입금", "미지급금"]):
            items = ITEMS_BY_TYPE["자재"]
            path = generate_invoice(i, vendor, items, amount, date_str, doc_no)
        elif any(kw in desc for kw in ["안전", "산재"]):
            path = generate_receipt(i, vendor, desc, amount, date_str, doc_no)
        elif any(kw in desc for kw in ["설계"]):
            items = ITEMS_BY_TYPE["외주"]
            path = generate_invoice(i, vendor, items, amount, date_str, doc_no)
        else:
            # 기본: 영수증
            path = generate_receipt(i, vendor, desc, amount, date_str, doc_no)

        results[doc_no] = path

    return results


if __name__ == "__main__":
    # 테스트 실행
    test_entries = [
        {"doc_no": "JE-2026-0001", "amount": 5000000, "date": "2026-05-10", "description": "자재 구매 - 철근"},
        {"doc_no": "JE-2026-0002", "amount": 15000000, "date": "2026-05-12", "description": "외주비 - 전기 배관"},
        {"doc_no": "JE-2026-0003", "amount": 350000, "date": "2026-05-15", "description": "여비교통비"},
    ]
    paths = generate_all_receipts(test_entries)
    for doc_no, path in paths.items():
        print(f"{doc_no}: {path}")
    print(f"\n총 {len(paths)}건 생성 완료")
