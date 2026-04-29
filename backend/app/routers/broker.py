from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.schemas.broker import BrokerAccountOut, BrokerCredentialIn, BrokerCredentialOut, BrokerStatusOut, BrokerTestOut, KisAccountOut, KisHoldingOut
from app.services.broker_credentials import (
    get_broker_credentials,
    get_decrypted_broker_credentials,
    list_broker_accounts,
    save_broker_credentials,
    set_active_broker_account,
)
from app.services.kis import client_from_credentials, extract_cash, extract_total_equity, parse_current_price
from app.services.telegram import send_telegram_message


router = APIRouter(prefix="/broker", tags=["broker"])


def _to_int(value) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def _to_float(value) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def parse_holding(item: dict) -> KisHoldingOut:
    code = str(item.get("pdno") or item.get("PDNO") or "").zfill(6)
    return KisHoldingOut(
        code=code,
        name=item.get("prdt_name") or item.get("PRDT_NAME"),
        qty=_to_int(item.get("hldg_qty") or item.get("HLDG_QTY")) or 0,
        avg_price=_to_int(item.get("pchs_avg_pric") or item.get("PCHS_AVG_PRIC")),
        current_price=_to_int(item.get("prpr") or item.get("PRPR")),
        evaluation_amount=_to_int(item.get("evlu_amt") or item.get("EVLU_AMT")),
        profit_loss=_to_int(item.get("evlu_pfls_amt") or item.get("EVLU_PFLS_AMT")),
        profit_loss_rate=_to_float(item.get("evlu_pfls_rt") or item.get("EVLU_PFLS_RT")),
    )


def account_out(row: dict) -> BrokerCredentialOut:
    settings = get_settings()
    return BrokerCredentialOut(
        id=row.get("id"),
        user_id=row["user_id"],
        label=row.get("label"),
        kis_account_no=row["kis_account_no"],
        kis_account_product_code=row.get("kis_account_product_code") or "01",
        mode=row.get("mode") or "paper",
        telegram_configured=bool(settings.telegram_bot_token and (settings.telegram_chat_id or row.get("telegram_chat_id"))),
        enabled=row.get("enabled", True),
        live_order_enabled=row.get("live_order_enabled", False),
        server_live_trading_allowed=settings.allow_live_trading,
        is_active=row.get("is_active", True),
    )


@router.get("/kis/status", response_model=BrokerStatusOut)
async def broker_status(user: CurrentUser = Depends(get_current_user)) -> BrokerStatusOut:
    row = await get_broker_credentials(user.id)
    settings = get_settings()
    if not row:
        return BrokerStatusOut(
            configured=False,
            telegram_configured=bool(settings.telegram_bot_token and settings.telegram_chat_id),
            server_live_trading_allowed=settings.allow_live_trading,
        )
    return BrokerStatusOut(
        configured=True,
        id=row.get("id"),
        label=row.get("label"),
        mode=row.get("mode"),
        account_no=row.get("kis_account_no"),
        account_product_code=row.get("kis_account_product_code"),
        telegram_configured=bool(settings.telegram_bot_token and (settings.telegram_chat_id or row.get("telegram_chat_id"))),
        enabled=row.get("enabled", False),
        live_order_enabled=row.get("live_order_enabled", False),
        server_live_trading_allowed=settings.allow_live_trading,
        is_active=row.get("is_active", True),
    )


@router.get("/kis/accounts", response_model=list[BrokerAccountOut])
async def broker_accounts(user: CurrentUser = Depends(get_current_user)) -> list[BrokerAccountOut]:
    return [BrokerAccountOut(**account_out(account).model_dump()) for account in await list_broker_accounts(user.id)]


@router.post("/kis", response_model=BrokerCredentialOut)
async def save_kis_credentials(
    payload: BrokerCredentialIn,
    user: CurrentUser = Depends(get_current_user),
) -> BrokerCredentialOut:
    row = await save_broker_credentials(user.id, payload)
    return account_out(row)


@router.post("/kis/accounts/{account_id}/activate", response_model=BrokerAccountOut)
async def activate_kis_account(
    account_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> BrokerAccountOut:
    row = await set_active_broker_account(user.id, account_id)
    return BrokerAccountOut(**account_out(row).model_dump())


@router.post("/kis/test", response_model=BrokerTestOut)
async def test_kis_connection(user: CurrentUser = Depends(get_current_user)) -> BrokerTestOut:
    credentials = await get_decrypted_broker_credentials(user.id)
    client = client_from_credentials(credentials, enable_orders=False)

    account = f"{credentials['kis_account_no']}-{credentials.get('kis_account_product_code') or '01'}"
    mode = credentials.get("mode") or "paper"

    try:
        token = await client.access_token()
        quote = await client.get_current_price("005930")
        quote_price = parse_current_price(quote)
        balance = await client.get_balance()
        holdings = balance.get("output1", [])
        cash = extract_cash(balance)
        total_equity = extract_total_equity(balance)
    except Exception as exc:
        return BrokerTestOut(
            ok=False,
            error=str(exc),
            token_ok=False,
            quote_ok=False,
            balance_ok=False,
            telegram_ok=False,
            account=account,
            mode=mode,
            quote_code="005930",
        )

    telegram_ok = False
    if get_settings().telegram_chat_id or credentials.get("telegram_chat_id"):
        telegram_ok = await send_telegram_message(
            credentials.get("telegram_chat_id"),
            "KIS paper connection test passed.",
        )

    return BrokerTestOut(
        ok=True,
        token_ok=bool(token),
        quote_ok=quote_price > 0,
        balance_ok=True,
        telegram_ok=telegram_ok,
        account=account,
        mode=mode,
        quote_code="005930",
        quote_price=quote_price,
        holdings_count=len(holdings),
        cash=cash,
        total_equity=total_equity,
    )


@router.get("/kis/account", response_model=KisAccountOut)
async def get_kis_account(user: CurrentUser = Depends(get_current_user)) -> KisAccountOut:
    credentials = await get_decrypted_broker_credentials(user.id)
    client = client_from_credentials(credentials, enable_orders=False)
    account = f"{credentials['kis_account_no']}-{credentials.get('kis_account_product_code') or '01'}"
    mode = credentials.get("mode") or "paper"

    try:
        balance = await client.get_balance()
        holdings = [parse_holding(item) for item in balance.get("output1", [])]
        holdings = [item for item in holdings if item.qty > 0]
        return KisAccountOut(
            ok=True,
            account=account,
            mode=mode,
            cash=extract_cash(balance),
            total_equity=extract_total_equity(balance),
            holdings_count=len(holdings),
            holdings=holdings,
        )
    except Exception as exc:
        return KisAccountOut(
            ok=False,
            error=str(exc),
            account=account,
            mode=mode,
        )
