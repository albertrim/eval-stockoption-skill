"""업종 태그 분류 — 네이버·KRX·38 업종명과 주요제품 텍스트를 키워드로 매핑."""
from __future__ import annotations

import csv
from pathlib import Path

TAGS = ["it_saas", "ai_data", "bio_health", "beauty", "ecommerce_platform",
        "fintech", "content_game", "hardware_semi", "industrial", "other"]

TAG_LABEL = {
    "it_saas": "IT·소프트웨어", "ai_data": "AI·데이터", "bio_health": "바이오·헬스케어",
    "beauty": "화장품·뷰티", "ecommerce_platform": "이커머스·플랫폼", "fintech": "핀테크·금융",
    "content_game": "콘텐츠·게임", "hardware_semi": "하드웨어·반도체",
    "industrial": "제조·산업재", "other": "기타",
}

# 네이버 업종명(GICS 계열)이 가장 깨끗해서 먼저 본다. 그다음 표준산업분류 키워드.
GICS = {
    "생물공학": "bio_health", "제약": "bio_health", "건강관리기술": "bio_health",
    "건강관리업체및서비스": "bio_health", "생명과학도구및서비스": "bio_health",
    "건강관리장비와용품": "bio_health",
    "화장품": "beauty", "개인생활용품": "beauty",
    "IT서비스": "it_saas", "소프트웨어": "it_saas", "인터넷서비스": "it_saas",
    "반도체와반도체장비": "hardware_semi", "전자장비와기기": "hardware_semi",
    "디스플레이패널": "hardware_semi", "디스플레이장비및부품": "hardware_semi",
    "전자제품": "hardware_semi", "통신장비": "hardware_semi", "컴퓨터와주변기기": "hardware_semi",
    "전기제품": "hardware_semi",
    "인터넷과카탈로그소매": "ecommerce_platform", "백화점및일반상점": "ecommerce_platform",
    "판매업체": "ecommerce_platform", "무역회사와판매업체": "ecommerce_platform",
    "게임엔터테인먼트": "content_game", "방송과엔터테인먼트": "content_game",
    "영화와엔터테인먼트": "content_game", "미디어": "content_game", "광고": "content_game",
    "출판": "content_game", "교육서비스": "content_game",
    "은행": "fintech", "증권": "fintech", "보험": "fintech", "창업투자": "fintech",
    "기타금융": "fintech", "카드": "fintech",
}

# 앞선 규칙이 이긴다. 좁은 태그를 먼저 둔다.
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("beauty", ("화장품", "뷰티", "코스메", "미용")),
    ("bio_health", ("의약", "바이오", "제약", "생물학적", "의료용", "진단", "헬스케어",
                    "의료기기", "치료", "백신", "임상", "신약", "생명과학", "생물공학",
                    "의학 및 약학", "의료, 정밀", "건강관리")),
    ("content_game", ("게임", "웹툰", "콘텐츠", "방송 및 영상", "영상 및 음향",
                      "엔터테인먼트", "광고", "출판", "학원", "교육")),
    ("fintech", ("금융", "보험", "결제", "핀테크", "여신", "자산운용", "증권")),
    ("ecommerce_platform", ("전자상거래", "무점포", "소매 중개", "커머스", "통신판매",
                            "상품 종합 도매", "카탈로그소매")),
    ("ai_data", ("인공지능", "자율주행", "머신러닝", "빅데이터", "데이터베이스",
                 "컴퓨터비전", "로봇")),
    ("hardware_semi", ("반도체", "전자부품", "디스플레이", "통신 및 방송 장비", "이차전지",
                       "축전지", "광학", "센서", "웨이퍼", "인쇄회로")),
    ("it_saas", ("소프트웨어", "시스템 통합", "정보서비스", "컴퓨터 프로그래밍",
                 "솔루션", "포털", "클라우드", "보안", "응용")),
    ("industrial", ("연구개발업", "제조업", "기계", "장비", "화학", "금속", "건설",
                    "자동차", "항공", "조선", "섬유", "의복", "식료품", "부품", "유틸리티",
                    "운송", "물류", "도매", "소매")),
]


def load_overrides(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r["code"].strip(): r["sector_tag"].strip()
                for r in csv.DictReader(f) if r.get("code") and r.get("sector_tag")}


def classify(industry_naver: str | None, *texts: str | None) -> str:
    """네이버 GICS 업종명 → 표준산업분류 키워드 순으로 태그를 정한다."""
    if industry_naver:
        key = industry_naver.replace(" ", "")
        if key in GICS:
            return GICS[key]
        for name, tag in GICS.items():
            if name in key:
                return tag
    blob = " ".join(t for t in (industry_naver, *texts) if t).lower()
    if not blob.strip():
        return "other"
    for tag, keys in RULES:
        if any(k.lower() in blob for k in keys):
            return tag
    return "other"
