# ============================================================
#  Korea Investment Open API client
#  Defaults to paper trading. Real trading requires explicit config changes.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import requests


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


def load_env_file(path: Path | None = None) -> None:
    if path is None:
        path = Path(__file__).resolve().parent / "kis_config.local.env"
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


@dataclass(frozen=True)
class KisConfig:
    app_key: str
    app_secret: str
    account_no: str
    account_product_code: str = "01"
    env: str = "paper"
    enable_orders: bool = False

    @property
    def base_url(self) -> str:
        if self.env == "live":
            return LIVE_BASE_URL
        return PAPER_BASE_URL

    @property
    def account_prefix(self) -> str:
        return self.account_no


def load_config_from_env() -> KisConfig:
    load_env_file()

    app_key = os.getenv("KIS_APP_KEY", "").strip()
    app_secret = os.getenv("KIS_APP_SECRET", "").strip()
    account_no = os.getenv("KIS_ACCOUNT_NO", "").strip()
    account_product_code = os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01").strip()
    env = os.getenv("KIS_ENV", "paper").strip().lower()
    enable_orders = os.getenv("KIS_ENABLE_ORDERS", "false").strip().lower() == "true"

    if env not in {"paper", "live"}:
        raise ValueError("KIS_ENV must be either 'paper' or 'live'.")
    if not app_key or not app_secret:
        raise ValueError("KIS_APP_KEY and KIS_APP_SECRET are required.")
    if not account_no:
        raise ValueError("KIS_ACCOUNT_NO is required.")
    if env == "live" and not enable_orders:
        raise ValueError("Live trading is blocked unless KIS_ENABLE_ORDERS=true.")

    return KisConfig(
        app_key=app_key,
        app_secret=app_secret,
        account_no=account_no,
        account_product_code=account_product_code,
        env=env,
        enable_orders=enable_orders,
    )


class KisClient:
    def __init__(self, config: KisConfig):
        self.config = config
        self._access_token: str | None = None

    def _request(self, method: str, path: str, *, headers: dict[str, str] | None = None, **kwargs) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        response = requests.request(method, url, headers=headers, timeout=10, **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = response.text[:1000]
            raise RuntimeError(f"KIS HTTP error {response.status_code}: {body}") from exc
        payload = response.json()
        if payload.get("rt_cd") not in {None, "0"}:
            raise RuntimeError(f"KIS API error: {payload.get('msg_cd')} {payload.get('msg1')}")
        return payload

    def issue_access_token(self) -> str:
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
        }
        data = self._request("POST", "/oauth2/tokenP", json=payload)
        token = data.get("access_token")
        if not token:
            raise RuntimeError("KIS token response did not include access_token.")
        self._access_token = token
        return token

    @property
    def access_token(self) -> str:
        if not self._access_token:
            return self.issue_access_token()
        return self._access_token

    def hashkey(self, payload: dict[str, Any]) -> str:
        headers = {
            "content-type": "application/json",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
        }
        data = self._request("POST", "/uapi/hashkey", headers=headers, json=payload)
        value = data.get("HASH")
        if not value:
            raise RuntimeError("KIS hashkey response did not include HASH.")
        return value

    def auth_headers(self, tr_id: str, *, hashkey: str | None = None) -> dict[str, str]:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if hashkey:
            headers["hashkey"] = hashkey
        return headers

    def get_current_price(self, code: str) -> dict[str, Any]:
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": code,
        }
        headers = self.auth_headers("FHKST01010100")
        return self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=headers,
            params=params,
        )

    def get_balance(self) -> dict[str, Any]:
        params = {
            "CANO": self.config.account_prefix,
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
        headers = self.auth_headers(TR_ID[self.config.env]["balance"])
        return self._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=headers,
            params=params,
        )

    def place_cash_order(self, *, code: str, side: str, qty: int, price: int, order_type: str = "00") -> dict[str, Any]:
        if not self.config.enable_orders:
            raise RuntimeError("Order placement is disabled. Set KIS_ENABLE_ORDERS=true to enable paper orders.")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'.")
        if qty <= 0:
            raise ValueError("qty must be positive.")
        if price < 0:
            raise ValueError("price must be zero or positive.")

        payload = {
            "CANO": self.config.account_prefix,
            "ACNT_PRDT_CD": self.config.account_product_code,
            "PDNO": code,
            "ORD_DVSN": order_type,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        headers = self.auth_headers(TR_ID[self.config.env][side], hashkey=self.hashkey(payload))
        return self._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            headers=headers,
            json=payload,
        )

    def buy_limit(self, code: str, qty: int, price: int) -> dict[str, Any]:
        return self.place_cash_order(code=code, side="buy", qty=qty, price=price, order_type="00")

    def sell_limit(self, code: str, qty: int, price: int) -> dict[str, Any]:
        return self.place_cash_order(code=code, side="sell", qty=qty, price=price, order_type="00")


def main() -> None:
    client = KisClient(load_config_from_env())
    token = client.issue_access_token()
    print("KIS paper client is configured.")
    print(f"Environment: {client.config.env}")
    print(f"Orders enabled: {client.config.enable_orders}")
    print(f"Token prefix: {token[:10]}...")


if __name__ == "__main__":
    main()
