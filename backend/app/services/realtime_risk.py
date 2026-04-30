from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import websockets

from app.core.config import get_settings


logger = logging.getLogger(__name__)
EXECUTION_TR_ID = "H0STCNT0"
ORDERBOOK_TR_ID = "H0STASP0"


@dataclass
class RealtimeRiskResult:
    ok: bool
    reason: str
    strength: float | None = None
    bid_ask_ratio: float | None = None
    spread_pct: float | None = None
    samples: int = 0
    raw: dict[str, Any] | None = None


def _float(value: str | int | float | None) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _subscribe_payload(approval_key: str, tr_id: str, code: str) -> str:
    return json.dumps(
        {
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": "1",
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": tr_id,
                    "tr_key": code,
                }
            },
        },
        ensure_ascii=False,
    )


def _parse_realtime_message(message: str) -> tuple[str | None, list[str]]:
    if not message or message.startswith("{"):
        return None, []
    parts = message.split("|")
    if len(parts) < 4:
        return None, []
    return parts[1], parts[3].split("^")


def _parse_execution_strength(fields: list[str]) -> float | None:
    # KIS execution payloads include many numeric fields and field positions may change by API revision.
    # Prefer the known 체결강도 neighborhood, then fall back to a conservative numeric search.
    for index in (18, 19, 20):
        if index < len(fields):
            value = _float(fields[index])
            if value is not None and 0 < value < 500:
                return value
    candidates = [_float(item) for item in fields[12:30]]
    candidates = [value for value in candidates if value is not None and 0 < value < 500]
    return candidates[0] if candidates else None


def _parse_execution_price(fields: list[str]) -> int | None:
    if len(fields) > 2:
        value = _float(fields[2])
        if value is not None and value > 0:
            return int(value)
    for item in fields[2:8]:
        value = _float(item)
        if value is not None and value > 100:
            return int(value)
    return None


def _parse_orderbook(fields: list[str]) -> tuple[float | None, float | None]:
    if len(fields) < 43:
        return None, None
    ask_price = _float(fields[3])
    bid_price = _float(fields[13])
    ask_quantities = [_float(item) or 0 for item in fields[23:33]]
    bid_quantities = [_float(item) or 0 for item in fields[33:43]]
    ask_total = sum(ask_quantities)
    bid_total = sum(bid_quantities)
    bid_ask_ratio = bid_total / ask_total if ask_total > 0 else None
    spread_pct = None
    if ask_price and bid_price and ask_price > 0 and bid_price > 0:
        mid = (ask_price + bid_price) / 2
        spread_pct = (ask_price - bid_price) / mid if mid > 0 else None
    return bid_ask_ratio, spread_pct


async def collect_realtime_prices(client: Any, codes: list[str], duration_seconds: float) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    approval_key = await client.approval_key()
    normalized_codes = [str(code).zfill(6) for code in codes]
    prices: dict[str, dict[str, Any]] = {}
    try:
        async with websockets.connect(client.config.websocket_url, ping_interval=20, close_timeout=1) as websocket:
            for code in normalized_codes:
                await websocket.send(_subscribe_payload(approval_key, EXECUTION_TR_ID, code))
            deadline = asyncio.get_running_loop().time() + max(1.0, duration_seconds)
            while asyncio.get_running_loop().time() < deadline:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=max(0.1, deadline - asyncio.get_running_loop().time()))
                except asyncio.TimeoutError:
                    break
                if not isinstance(message, str):
                    continue
                tr_id, fields = _parse_realtime_message(message)
                if tr_id != EXECUTION_TR_ID or not fields:
                    continue
                code = str(fields[0] if fields else "").zfill(6)
                if code not in normalized_codes:
                    continue
                price = _parse_execution_price(fields)
                if not price:
                    continue
                prices[code] = {
                    "current_price": price,
                    "ask_price": 0,
                    "bid_price": price,
                    "day_high": price,
                    "day_low": price,
                    "accumulated_volume": 0,
                    "vi_active": 0,
                    "price_source": "websocket_execution",
                    "received_at": asyncio.get_running_loop().time(),
                }
    except Exception as exc:
        logger.warning("Realtime position price collection failed: codes=%s error=%s", normalized_codes, exc)
    return prices


async def check_realtime_entry_risk(client: Any, code: str, strategy: dict) -> RealtimeRiskResult:
    if not strategy.get("use_realtime_liquidity_filter", True):
        return RealtimeRiskResult(ok=True, reason="disabled")

    timeout = float(get_settings().kis_realtime_filter_timeout_seconds)
    min_strength = float(strategy.get("min_realtime_strength") or 0)
    min_bid_ask_ratio = float(strategy.get("min_bid_ask_ratio") or 0)
    max_spread_pct = float(strategy.get("max_realtime_spread_pct") or 1)
    approval_key = await client.approval_key()
    strength: float | None = None
    bid_ask_ratio: float | None = None
    spread_pct: float | None = None
    samples = 0

    try:
        async with websockets.connect(client.config.websocket_url, ping_interval=None, close_timeout=1) as websocket:
            await websocket.send(_subscribe_payload(approval_key, EXECUTION_TR_ID, code))
            await websocket.send(_subscribe_payload(approval_key, ORDERBOOK_TR_ID, code))
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=max(0.1, deadline - asyncio.get_running_loop().time()))
                except asyncio.TimeoutError:
                    break
                if not isinstance(message, str):
                    continue
                tr_id, fields = _parse_realtime_message(message)
                if not tr_id:
                    continue
                if tr_id == EXECUTION_TR_ID:
                    parsed_strength = _parse_execution_strength(fields)
                    if parsed_strength is not None:
                        strength = parsed_strength
                        samples += 1
                elif tr_id == ORDERBOOK_TR_ID:
                    parsed_ratio, parsed_spread = _parse_orderbook(fields)
                    bid_ask_ratio = parsed_ratio if parsed_ratio is not None else bid_ask_ratio
                    spread_pct = parsed_spread if parsed_spread is not None else spread_pct
                    samples += 1
                if samples >= 2 and (strength is not None or bid_ask_ratio is not None):
                    break
    except Exception as exc:
        logger.warning("Realtime liquidity filter failed: code=%s error=%s", code, exc)
        return RealtimeRiskResult(ok=True, reason="realtime_check_failed", samples=samples, raw={"error": str(exc)})

    raw = {
        "min_strength": min_strength,
        "min_bid_ask_ratio": min_bid_ask_ratio,
        "max_spread_pct": max_spread_pct,
    }
    if strength is not None and strength < min_strength:
        return RealtimeRiskResult(False, "realtime_strength_weak", strength, bid_ask_ratio, spread_pct, samples, raw)
    if bid_ask_ratio is not None and bid_ask_ratio < min_bid_ask_ratio:
        return RealtimeRiskResult(False, "realtime_bid_depth_weak", strength, bid_ask_ratio, spread_pct, samples, raw)
    if spread_pct is not None and spread_pct > max_spread_pct:
        return RealtimeRiskResult(False, "realtime_spread_wide", strength, bid_ask_ratio, spread_pct, samples, raw)
    return RealtimeRiskResult(True, "passed", strength, bid_ask_ratio, spread_pct, samples, raw)
