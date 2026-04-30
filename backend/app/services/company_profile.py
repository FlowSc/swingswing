from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import FinanceDataReader as fdr
import pandas as pd


logger = logging.getLogger(__name__)
UNKNOWN = "제공 데이터 기준 확인 불가"
SECTOR_KEYWORDS = (
    ("반도체", ("반도체", "전자부품", "디스플레이", "웨이퍼", "PCB", "LED", "센서", "장비")),
    ("전기전자", ("전자", "전기", "가전", "배터리", "2차전지", "축전지", "전지", "전선", "케이블")),
    ("자동차", ("자동차", "차량", "모빌리티", "타이어", "자동차부품", "부품 제조")),
    ("기계/조선", ("기계", "조선", "선박", "플랜트", "중공업", "엔진", "건설기계", "공작기계")),
    ("화학/소재", ("화학", "석유", "정유", "소재", "필름", "수지", "플라스틱", "고무", "도료", "페인트")),
    ("철강/금속", ("철강", "금속", "비철", "알루미늄", "구리", "동", "스테인리스")),
    ("바이오/헬스케어", ("바이오", "제약", "의약", "의료", "헬스케어", "진단", "병원", "치료제")),
    ("음식료", ("음식료", "식품", "사료", "축산", "수산", "음료", "주류", "제과", "라면")),
    ("유통/소비재", ("유통", "소매", "백화점", "홈쇼핑", "화장품", "의류", "패션", "생활용품")),
    ("건설/건자재", ("건설", "건축", "시멘트", "레미콘", "건자재", "토목", "부동산")),
    ("방산/보안", ("방산", "방위", "보안", "감시", "CCTV", "항공우주", "무기")),
    ("IT/소프트웨어", ("소프트웨어", "IT", "인터넷", "플랫폼", "게임", "클라우드", "데이터")),
    ("통신/미디어", ("통신", "방송", "미디어", "콘텐츠", "광고", "엔터테인먼트", "영화", "드라마")),
    ("금융", ("금융", "은행", "증권", "보험", "카드", "캐피탈", "자산운용")),
    ("운송/물류", ("운송", "물류", "해운", "항공", "택배", "창고", "항만")),
    ("에너지/유틸리티", ("전력", "가스", "에너지", "발전", "태양광", "풍력", "수소", "LNG")),
    ("지주/복합기업", ("지주", "홀딩스", "복합기업")),
)


def optional_text(row: pd.Series | dict[str, Any], columns: tuple[str, ...]) -> str | None:
    for column in columns:
        if column not in row:
            continue
        value = row[column]
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        if text and text != UNKNOWN:
            return text
    return None


def optional_int(row: pd.Series | dict[str, Any], columns: tuple[str, ...]) -> int | None:
    for column in columns:
        if column not in row:
            continue
        value = row[column]
        try:
            if pd.isna(value):
                continue
            return int(float(str(value).replace(",", "")))
        except (TypeError, ValueError):
            continue
    return None


def infer_sector(*values: str | None) -> str | None:
    text = " ".join(value for value in values if value and value != UNKNOWN)
    if not text:
        return None
    normalized = text.lower()
    for sector, keywords in SECTOR_KEYWORDS:
        if any(keyword.lower() in normalized for keyword in keywords):
            return sector
    return None


def company_profile_from_row(row: pd.Series | dict[str, Any], universe: str | None = None) -> dict:
    industry = optional_text(row, ("Industry", "산업", "업종명", "Dept", "주요제품", "Products", "MainProduct"))
    business_summary = optional_text(
        row,
        ("BusinessSummary", "Summary", "사업내용", "Description", "주요제품", "Products", "MainProduct"),
    )
    sector = optional_text(row, ("Sector", "섹터", "SectorName", "업종대분류")) or infer_sector(industry, business_summary)
    return {
        "market": optional_text(row, ("Market", "시장구분", "MarketName")) or universe or UNKNOWN,
        "sector": sector or UNKNOWN,
        "industry": industry or UNKNOWN,
        "business_summary": business_summary or industry or UNKNOWN,
        "market_cap": optional_int(row, ("Marcap", "MarketCap", "시가총액")),
        "shares": optional_int(row, ("Stocks", "Shares", "상장주식수")),
    }


def has_meaningful_company_profile(profile: dict | None) -> bool:
    if not profile:
        return False
    return any(profile.get(key) not in {None, "", UNKNOWN} for key in ("sector", "industry", "business_summary"))


def merge_company_profiles(base: dict | None, extra: dict | None) -> dict:
    merged = dict(base or {})
    for key, value in (extra or {}).items():
        if value in {None, "", UNKNOWN}:
            continue
        if merged.get(key) in {None, "", UNKNOWN}:
            merged[key] = value
    if merged.get("sector") in {None, "", UNKNOWN}:
        merged["sector"] = infer_sector(merged.get("industry"), merged.get("business_summary")) or UNKNOWN
    return merged


@lru_cache(maxsize=1)
def load_krx_description_profiles() -> dict[str, dict]:
    try:
        frame = fdr.StockListing("KRX-DESC")
    except Exception as exc:
        logger.warning("Failed to load KRX-DESC company profiles: %s", exc)
        return {}
    if frame is None or frame.empty:
        return {}
    if "Code" not in frame.columns and "Symbol" in frame.columns:
        frame["Code"] = frame["Symbol"]
    if "Code" not in frame.columns:
        return {}

    frame["Code"] = frame["Code"].astype(str).str.zfill(6)
    profiles = {
        row["Code"]: company_profile_from_row(row)
        for _, row in frame.iterrows()
        if row.get("Code")
    }
    logger.warning("Loaded KRX-DESC company profiles: %s symbols", len(profiles))
    return profiles


def enrich_company_profile(code: str | None, profile: dict | None) -> dict:
    if not code:
        return profile or {}
    normalized_code = str(code).zfill(6)
    description_profile = load_krx_description_profiles().get(normalized_code)
    return merge_company_profiles(profile, description_profile)
