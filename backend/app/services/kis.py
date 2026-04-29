from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
LIVE_BASE_URL = "https://openapi.koreainvestment.com:9443"

TR_ID = {
    "paper": {
        "buy": "VTTC0802U",
        "sell": "VTTC0801U",
        "balance": "VTTC8434R",
    },
    "live": {
        "buy": "TTTC0802U",
        "sell": "TTTC0801U",
        "balance": "TTTC8434R",
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

    @property
    def base_url(self) -> str:
        return LIVE_BASE_URL if self.mode == "live" else PAPER_BASE_URL


class KisClient:
    def __init__(self, config: KisConfig):
        self.config = config
        self._access_token: str | None = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
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
            raise RuntimeError(f"KIS HTTP error {response.status_code}: {body}") from exc

        payload = response.json()
        if payload.get("rt_cd") not in {None, "0"}:
            raise RuntimeError(f"KIS API error: {payload.get('msg_cd')} {payload.get('msg1')}")
        return payload

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
        self._access_token = token
        return token

    async def access_token(self) -> str:
        if not self._access_token:
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


def client_from_credentials(
    credentials: dict[str, Any],
    *,
    enable_orders: bool = True,
    allow_live_orders: bool = False,
) -> KisClient:
    return KisClient(
        KisConfig(
            app_key=credentials["kis_app_key"],
            app_secret=credentials["kis_app_secret"],
            account_no=credentials["kis_account_no"],
            account_product_code=credentials.get("kis_account_product_code") or "01",
            mode=credentials.get("mode") or "paper",
            enable_orders=enable_orders,
            allow_live_orders=allow_live_orders,
        )
    )


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
    return {
        "current_price": _parse_int_field(output, "stck_prpr", "STCK_PRPR"),
        "day_high": _parse_int_field(output, "stck_hgpr", "STCK_HGPR"),
        "day_low": _parse_int_field(output, "stck_lwpr", "STCK_LWPR"),
        "accumulated_volume": _parse_int_field(output, "acml_vol", "ACML_VOL"),
    }


def extract_cash(balance: dict[str, Any]) -> int:
    output2 = balance.get("output2", [])
    if not output2:
        return 10_000_000
    raw_value = output2[0].get("dnca_tot_amt") or output2[0].get("ord_psbl_cash") or "0"
    try:
        return int(float(str(raw_value).replace(",", "")))
    except ValueError:
        return 10_000_000


def extract_total_equity(balance: dict[str, Any]) -> int:
    output2 = balance.get("output2", [])
    if not output2:
        return 10_000_000
    raw_value = output2[0].get("tot_evlu_amt") or output2[0].get("dnca_tot_amt") or "0"
    try:
        return max(int(float(str(raw_value).replace(",", ""))), 1)
    except ValueError:
        return 10_000_000


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
