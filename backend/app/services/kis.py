from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings


PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
LIVE_BASE_URL = "https://openapi.koreainvestment.com:9443"
PAPER_WS_URL = "ws://ops.koreainvestment.com:31000"
LIVE_WS_URL = "ws://ops.koreainvestment.com:21000"
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)
RATE_LIMIT_MARKER = "EGW00201"
_REST_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}
_REST_LAST_REQUEST_AT: dict[tuple[str, str], float] = {}

TR_ID = {
    "paper": {
        "buy": "VTTC0802U",
        "sell": "VTTC0801U",
        "cancel": "VTTC0803U",
        "balance": "VTTC8434R",
        "order_inquiry": "VTTC8001R",
    },
    "live": {
        "buy": "TTTC0802U",
        "sell": "TTTC0801U",
        "cancel": "TTTC0803U",
        "balance": "TTTC8434R",
        "order_inquiry": "TTTC8001R",
    },
}


@dataclass(frozen=True)
class KisConfig:
    app_key: str
    app_secret: str
    account_no: str
    account_product_code: str = "01"
    mode: str = "paper"
    enable_orders: bool = True
    allow_live_orders: bool = False
    access_token: str | None = None
    access_token_expires_at: datetime | str | None = None
    on_token_issued: Callable[[str, datetime], Awaitable[None]] | None = None

    @property
    def base_url(self) -> str:
        return LIVE_BASE_URL if self.mode == "live" else PAPER_BASE_URL

    @property
    def websocket_url(self) -> str:
        return LIVE_WS_URL if self.mode == "live" else PAPER_WS_URL


class KisClient:
    def __init__(self, config: KisConfig):
        self.config = config
        self._access_token: str | None = config.access_token
        self._access_token_expires_at = parse_kis_datetime(config.access_token_expires_at)

    def _token_valid(self) -> bool:
        if not self._access_token or not self._access_token_expires_at:
            return False
        return self._access_token_expires_at > now_kst() + TOKEN_REFRESH_BUFFER

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        settings = get_settings()
        last_error: Exception | None = None
        max_attempts = 3
        for attempt in range(max_attempts):
            await self._throttle_rest_request(float(settings.kis_rest_min_interval_seconds))
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.request(
                    method,
                    f"{self.config.base_url}{path}",
                    headers=headers,
                    **kwargs,
                )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = response.text[:1000]
                if RATE_LIMIT_MARKER in body and attempt < max_attempts - 1:
                    last_error = RuntimeError(f"KIS HTTP error {response.status_code}: {body}")
                    await asyncio.sleep(float(settings.kis_rate_limit_retry_seconds) * (attempt + 1))
                    continue
                raise RuntimeError(f"KIS HTTP error {response.status_code}: {body}") from exc

            payload = response.json()
            if payload.get("rt_cd") not in {None, "0"}:
                message = f"KIS API error: {payload.get('msg_cd')} {payload.get('msg1')}"
                if payload.get("msg_cd") == RATE_LIMIT_MARKER and attempt < max_attempts - 1:
                    last_error = RuntimeError(message)
                    await asyncio.sleep(float(settings.kis_rate_limit_retry_seconds) * (attempt + 1))
                    continue
                raise RuntimeError(message)
            return payload
        if last_error:
            raise last_error
        raise RuntimeError("KIS request failed without response.")

    async def _throttle_rest_request(self, min_interval_seconds: float) -> None:
        key = (self.config.mode, self.config.app_key)
        lock = _REST_LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            last_at = _REST_LAST_REQUEST_AT.get(key, 0.0)
            wait_seconds = max(0.0, last_at + max(0.0, min_interval_seconds) - now)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            _REST_LAST_REQUEST_AT[key] = loop.time()

    async def issue_access_token(self) -> str:
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
        }
        data = await self._request("POST", "/oauth2/tokenP", json=payload)
        token = data.get("access_token")
        if not token:
            raise RuntimeError("KIS token response did not include access_token.")
        expires_at = token_expires_at(data)
        self._access_token = token
        self._access_token_expires_at = expires_at
        if self.config.on_token_issued:
            await self.config.on_token_issued(token, expires_at)
        return token

    async def access_token(self) -> str:
        if not self._token_valid():
            return await self.issue_access_token()
        return self._access_token

    async def hashkey(self, payload: dict[str, Any]) -> str:
        headers = {
            "content-type": "application/json",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
        }
        data = await self._request("POST", "/uapi/hashkey", headers=headers, json=payload)
        value = data.get("HASH")
        if not value:
            raise RuntimeError("KIS hashkey response did not include HASH.")
        return value

    async def approval_key(self) -> str:
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "secretkey": self.config.app_secret,
        }
        data = await self._request("POST", "/oauth2/Approval", json=payload)
        value = data.get("approval_key")
        if not value:
            raise RuntimeError("KIS approval response did not include approval_key.")
        return value

    async def auth_headers(self, tr_id: str, *, hashkey: str | None = None) -> dict[str, str]:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {await self.access_token()}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if hashkey:
            headers["hashkey"] = hashkey
        return headers

    async def get_current_price(self, code: str) -> dict[str, Any]:
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": code,
        }
        return await self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=await self.auth_headers("FHKST01010100"),
            params=params,
        )

    async def get_balance(self) -> dict[str, Any]:
        params = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "N",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        return await self._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=await self.auth_headers(TR_ID[self.config.mode]["balance"]),
            params=params,
        )

    async def inquire_daily_orders(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        code: str = "",
        order_no: str = "",
        ctx_area_fk100: str = "",
        ctx_area_nk100: str = "",
    ) -> dict[str, Any]:
        target_date = now_kst().date().strftime("%Y%m%d")
        params = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_product_code,
            "INQR_STRT_DT": start_date or target_date,
            "INQR_END_DT": end_date or target_date,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": code,
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": order_no,
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": ctx_area_fk100,
            "CTX_AREA_NK100": ctx_area_nk100,
        }
        return await self._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-ccnl",
            headers=await self.auth_headers(TR_ID[self.config.mode]["order_inquiry"]),
            params=params,
        )

    async def inquire_daily_orders_all(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        code: str = "",
        order_no: str = "",
        max_pages: int = 10,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {"output1": [], "output": []}
        ctx_fk = ""
        ctx_nk = ""
        pages = 0
        last_payload: dict[str, Any] = {}
        while pages < max(1, max_pages):
            payload = await self.inquire_daily_orders(
                start_date=start_date,
                end_date=end_date,
                code=code,
                order_no=order_no,
                ctx_area_fk100=ctx_fk,
                ctx_area_nk100=ctx_nk,
            )
            pages += 1
            last_payload = payload
            rows = parse_order_rows(payload)
            merged["output1"].extend(rows)

            output2 = payload.get("output2")
            cursor_source = output2[0] if isinstance(output2, list) and output2 else output2 if isinstance(output2, dict) else payload
            next_fk = str(_field(cursor_source or {}, "ctx_area_fk100", "CTX_AREA_FK100") or "")
            next_nk = str(_field(cursor_source or {}, "ctx_area_nk100", "CTX_AREA_NK100") or "")
            if not next_fk and not next_nk:
                break
            if next_fk == ctx_fk and next_nk == ctx_nk:
                break
            ctx_fk, ctx_nk = next_fk, next_nk

        merged.update(
            {
                "rt_cd": last_payload.get("rt_cd"),
                "msg_cd": last_payload.get("msg_cd"),
                "msg1": last_payload.get("msg1"),
                "pagination": {"pages": pages, "row_count": len(merged["output1"])},
            }
        )
        return merged

    async def place_cash_order(self, *, code: str, side: str, qty: int, price: int, order_type: str = "00") -> dict[str, Any]:
        if not self.config.enable_orders:
            raise RuntimeError("Order placement is disabled.")
        if self.config.mode == "live" and not self.config.allow_live_orders:
            raise RuntimeError("Live trading is disabled for this account or deployment.")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'.")
        if qty <= 0:
            raise ValueError("qty must be positive.")

        payload = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_product_code,
            "PDNO": code,
            "ORD_DVSN": order_type,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        return await self._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            headers=await self.auth_headers(TR_ID[self.config.mode][side], hashkey=await self.hashkey(payload)),
            json=payload,
        )

    async def buy_limit(self, code: str, qty: int, price: int) -> dict[str, Any]:
        return await self.place_cash_order(code=code, side="buy", qty=qty, price=price)

    async def sell_limit(self, code: str, qty: int, price: int) -> dict[str, Any]:
        return await self.place_cash_order(code=code, side="sell", qty=qty, price=price)

    async def sell_market(self, code: str, qty: int) -> dict[str, Any]:
        return await self.place_cash_order(code=code, side="sell", qty=qty, price=0, order_type="01")

    async def cancel_order(self, *, order_org_no: str, order_no: str, qty: int = 0, price: int = 0) -> dict[str, Any]:
        if not self.config.enable_orders:
            raise RuntimeError("Order cancellation is disabled.")
        if self.config.mode == "live" and not self.config.allow_live_orders:
            raise RuntimeError("Live trading is disabled for this account or deployment.")
        if not order_no:
            raise ValueError("order_no is required.")

        payload = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_product_code,
            "KRX_FWDG_ORD_ORGNO": order_org_no or "",
            "ORGN_ODNO": order_no,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": str(max(0, qty)),
            "ORD_UNPR": str(max(0, price)),
            "QTY_ALL_ORD_YN": "Y",
        }
        return await self._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-rvsecncl",
            headers=await self.auth_headers(TR_ID[self.config.mode]["cancel"], hashkey=await self.hashkey(payload)),
            json=payload,
        )


def client_from_credentials(
    credentials: dict[str, Any],
    *,
    enable_orders: bool = True,
    allow_live_orders: bool = False,
) -> KisClient:
    async def persist_access_token(access_token: str, expires_at: datetime) -> None:
        from app.services.broker_credentials import update_broker_access_token

        await update_broker_access_token(credentials.get("id"), access_token, expires_at)

    return KisClient(
        KisConfig(
            app_key=credentials["kis_app_key"],
            app_secret=credentials["kis_app_secret"],
            account_no=credentials["kis_account_no"],
            account_product_code=credentials.get("kis_account_product_code") or "01",
            mode=credentials.get("mode") or "paper",
            enable_orders=enable_orders,
            allow_live_orders=allow_live_orders,
            access_token=credentials.get("access_token"),
            access_token_expires_at=credentials.get("access_token_expires_at"),
            on_token_issued=persist_access_token if credentials.get("id") else None,
        )
    )


def now_kst() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def parse_kis_datetime(value: datetime | str | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.replace(" ", "T")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo(get_settings().timezone))
    return parsed.astimezone(ZoneInfo(get_settings().timezone))


def token_expires_at(payload: dict[str, Any]) -> datetime:
    explicit = parse_kis_datetime(payload.get("access_token_token_expired"))
    if explicit:
        return explicit
    expires_in = payload.get("expires_in")
    try:
        seconds = int(float(str(expires_in)))
    except (TypeError, ValueError):
        seconds = 23 * 60 * 60
    return now_kst() + timedelta(seconds=max(60, seconds))


def parse_current_price(payload: dict[str, Any]) -> int:
    output = payload.get("output", {})
    raw_value = output.get("stck_prpr") or output.get("STCK_PRPR") or "0"
    return int(float(str(raw_value).replace(",", "")))


def _parse_int_field(output: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = output.get(key)
        if value not in {None, ""}:
            return int(float(str(value).replace(",", "")))
    return 0


def parse_quote(payload: dict[str, Any]) -> dict[str, int]:
    output = payload.get("output", {})
    vi_code = str(
        _field(
            output,
            "vi_cls_code",
            "VI_CLS_CODE",
            "vi_kind_code",
            "VI_KIND_CODE",
            "vi_knd_code",
            "VI_KND_CODE",
        )
        or ""
    ).strip()
    return {
        "current_price": _parse_int_field(output, "stck_prpr", "STCK_PRPR"),
        "ask_price": _parse_int_field(output, "askp1", "ASKP1", "stck_askp1", "STCK_ASKP1", "askp", "ASKP"),
        "bid_price": _parse_int_field(output, "bidp1", "BIDP1", "stck_bidp1", "STCK_BIDP1", "bidp", "BIDP"),
        "day_high": _parse_int_field(output, "stck_hgpr", "STCK_HGPR"),
        "day_low": _parse_int_field(output, "stck_lwpr", "STCK_LWPR"),
        "accumulated_volume": _parse_int_field(output, "acml_vol", "ACML_VOL"),
        "vi_active": 1 if vi_code and vi_code not in {"0", "00", "N", "n"} else 0,
    }


def parse_order_identifiers(payload: dict[str, Any]) -> dict[str, str | None]:
    output = payload.get("output") or {}
    return {
        "order_org_no": output.get("KRX_FWDG_ORD_ORGNO") or output.get("krx_fwdg_ord_orgno"),
        "order_no": output.get("ODNO") or output.get("odno"),
        "order_time": output.get("ORD_TMD") or output.get("ord_tmd"),
    }


def _field(output: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = output.get(key)
        if value not in {None, ""}:
            return value
    return None


def parse_order_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    output = payload.get("output1") or payload.get("output") or []
    if isinstance(output, dict):
        return [output]
    return output if isinstance(output, list) else []


def find_order_execution(
    payload: dict[str, Any],
    *,
    order_no: str | None = None,
    code: str | None = None,
) -> dict[str, Any] | None:
    normalized_code = str(code or "").zfill(6) if code else ""
    for row in parse_order_rows(payload):
        row_order_no = str(_field(row, "odno", "ODNO") or "")
        row_code = str(_field(row, "pdno", "PDNO") or "").zfill(6)
        if order_no and row_order_no != str(order_no):
            continue
        if normalized_code and row_code and row_code != normalized_code:
            continue

        ordered_qty = _parse_int_field(row, "ord_qty", "ORD_QTY")
        filled_qty = _parse_int_field(row, "tot_ccld_qty", "TOT_CCLD_QTY", "ccld_qty", "CCLD_QTY")
        remaining_qty = _parse_int_field(row, "rmn_qty", "RMN_QTY")
        avg_price = _parse_int_field(row, "avg_prvs", "AVG_PRVS", "avg_prvs_pric", "AVG_PRVS_PRIC")
        if avg_price <= 0 and filled_qty > 0:
            total_filled_amount = _parse_int_field(row, "tot_ccld_amt", "TOT_CCLD_AMT")
            avg_price = int(total_filled_amount / filled_qty) if total_filled_amount > 0 else 0

        if ordered_qty > 0 and remaining_qty <= 0 and filled_qty <= 0:
            remaining_qty = ordered_qty

        return {
            "order_no": row_order_no or order_no,
            "code": row_code or normalized_code,
            "ordered_qty": ordered_qty,
            "filled_qty": filled_qty,
            "remaining_qty": remaining_qty,
            "avg_price": avg_price,
            "fully_filled": filled_qty > 0 and remaining_qty == 0,
            "partially_filled": filled_qty > 0 and remaining_qty > 0,
            "raw": row,
        }
    return None


def extract_cash(balance: dict[str, Any]) -> int:
    return extract_orderable_cash(balance)


def extract_orderable_cash(balance: dict[str, Any]) -> int:
    output2 = balance.get("output2", [])
    if not output2:
        return 10_000_000
    row = output2[0] if isinstance(output2, list) else output2
    raw_value = (
        row.get("ord_psbl_cash")
        or row.get("ORD_PSBL_CASH")
        or row.get("ord_psbl_cash_amt")
        or row.get("ORD_PSBL_CASH_AMT")
        or row.get("dnca_tot_amt")
        or row.get("DNCA_TOT_AMT")
        or "0"
    )
    try:
        return int(float(str(raw_value).replace(",", "")))
    except ValueError:
        return 10_000_000


def extract_total_equity(balance: dict[str, Any]) -> int:
    output2 = balance.get("output2", [])
    if not output2:
        return 10_000_000
    row = output2[0] if isinstance(output2, list) else output2
    raw_value = row.get("tot_evlu_amt") or row.get("TOT_EVLU_AMT") or row.get("dnca_tot_amt") or row.get("DNCA_TOT_AMT") or "0"
    try:
        return max(int(float(str(raw_value).replace(",", ""))), 1)
    except ValueError:
        return 10_000_000


def _parse_balance_number(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return 0.0


def extract_unrealized_pnl(balance: dict[str, Any]) -> int:
    total = 0.0
    for item in balance.get("output1", []):
        direct = _parse_balance_number(item, "evlu_pfls_amt", "EVLU_PFLS_AMT")
        if direct:
            total += direct
            continue
        qty = _parse_balance_number(item, "hldg_qty", "HLDG_QTY")
        avg_price = _parse_balance_number(item, "pchs_avg_pric", "PCHS_AVG_PRIC")
        current_price = _parse_balance_number(item, "prpr", "PRPR", "now_pric", "NOW_PRIC")
        if qty > 0 and avg_price > 0 and current_price > 0:
            total += (current_price - avg_price) * qty
    return int(total)


def kis_holding_codes(balance: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for item in balance.get("output1", []):
        code = item.get("pdno") or item.get("PDNO")
        qty = item.get("hldg_qty") or item.get("HLDG_QTY") or "0"
        try:
            qty_value = int(float(str(qty).replace(",", "")))
        except ValueError:
            qty_value = 0
        if code and qty_value > 0:
            codes.add(str(code).zfill(6))
    return codes


def parse_holdings(balance: dict[str, Any]) -> dict[str, dict[str, Any]]:
    holdings: dict[str, dict[str, Any]] = {}
    for item in balance.get("output1", []):
        code = item.get("pdno") or item.get("PDNO")
        if not code:
            continue
        qty = _parse_int_field(item, "hldg_qty", "HLDG_QTY")
        if qty <= 0:
            continue
        normalized_code = str(code).zfill(6)
        holdings[normalized_code] = {
            "code": normalized_code,
            "name": item.get("prdt_name") or item.get("PRDT_NAME"),
            "qty": qty,
            "avg_price": _parse_int_field(item, "pchs_avg_pric", "PCHS_AVG_PRIC"),
            "current_price": _parse_int_field(item, "prpr", "PRPR", "stck_prpr", "STCK_PRPR"),
            "raw": item,
        }
    return holdings
