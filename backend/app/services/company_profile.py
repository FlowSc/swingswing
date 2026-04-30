from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import FinanceDataReader as fdr
import pandas as pd


logger = logging.getLogger(__name__)
UNKNOWN = "제공 데이터 기준 확인 불가"


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


def company_profile_from_row(row: pd.Series | dict[str, Any], universe: str | None = None) -> dict:
    industry = optional_text(row, ("Industry", "산업", "업종명", "Dept", "주요제품", "Products", "MainProduct"))
    return {
        "market": optional_text(row, ("Market", "시장구분", "MarketName")) or universe or UNKNOWN,
        "sector": optional_text(row, ("Sector", "섹터", "업종", "업종명", "SectorName")) or UNKNOWN,
        "industry": industry or UNKNOWN,
        "business_summary": optional_text(
            row,
            ("BusinessSummary", "Summary", "사업내용", "Description", "주요제품", "Products", "MainProduct"),
        )
        or industry
        or UNKNOWN,
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
