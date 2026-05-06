from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.schemas.broker import BrokerAccountOut, BrokerCredentialIn, BrokerCredentialOut, BrokerStatusOut, KisAccountOut, KisHoldingOut, TelegramSettingsIn
from app.services.broker_credentials import (
    get_broker_credentials,
    get_decrypted_broker_credentials,
    list_broker_accounts,
    save_broker_credentials,
    save_telegram_settings,
    set_active_broker_account,
)
from app.services.kis import client_from_credentials, extract_cash, extract_orderable_cash, extract_psbl_order_cash, extract_total_equity
from app.services.memberships import require_live_trading_access


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


def telegram_configured(row: dict) -> bool:
    return bool(row.get("telegram_configured") or (row.get("telegram_bot_token_enc") and row.get("telegram_chat_id")))


def account_out(row: dict) -> BrokerCredentialOut:
    settings = get_settings()
    return BrokerCredentialOut(
        id=row.get("id"),
        user_id=row["user_id"],
        label=row.get("label"),
        kis_account_no=row["kis_account_no"],
        kis_account_product_code=row.get("kis_account_product_code") or "01",
        mode=row.get("mode") or "paper",
        telegram_configured=telegram_configured(row),
        telegram_chat_id=row.get("telegram_chat_id"),
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
            telegram_configured=False,
            server_live_trading_allowed=settings.allow_live_trading,
        )
    return BrokerStatusOut(
        configured=True,
        id=row.get("id"),
        label=row.get("label"),
        mode=row.get("mode"),
        account_no=row.get("kis_account_no"),
        account_product_code=row.get("kis_account_product_code"),
        telegram_configured=telegram_configured(row),
        telegram_chat_id=row.get("telegram_chat_id"),
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
    if payload.mode not in {"paper", "live"}:
        raise HTTPException(status_code=400, detail="Invalid KIS account mode.")
    if payload.mode == "live":
        await require_live_trading_access(user.id, user.email)
    row = await save_broker_credentials(user.id, payload)
    return account_out(row)


@router.put("/telegram", response_model=BrokerCredentialOut)
async def save_telegram(
    payload: TelegramSettingsIn,
    user: CurrentUser = Depends(get_current_user),
) -> BrokerCredentialOut:
    row = await save_telegram_settings(user.id, payload)
    return account_out(row)


@router.post("/kis/accounts/{account_id}/activate", response_model=BrokerAccountOut)
async def activate_kis_account(
    account_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> BrokerAccountOut:
    accounts = await list_broker_accounts(user.id)
    target = next((account for account in accounts if account.get("id") == account_id), None)
    if target and target.get("mode") == "live":
        await require_live_trading_access(user.id, user.email)
    row = await set_active_broker_account(user.id, account_id)
    return BrokerAccountOut(**account_out(row).model_dump())


@router.get("/kis/account", response_model=KisAccountOut)
async def get_kis_account(user: CurrentUser = Depends(get_current_user)) -> KisAccountOut:
    credentials = await get_decrypted_broker_credentials(user.id)
    if (credentials.get("mode") or "paper") == "live":
        await require_live_trading_access(user.id, user.email)
    client = client_from_credentials(credentials, enable_orders=False)
    account = f"{credentials['kis_account_no']}-{credentials.get('kis_account_product_code') or '01'}"
    mode = credentials.get("mode") or "paper"

    try:
        balance = await client.get_balance()
        try:
            orderable_cash = extract_psbl_order_cash(await client.inquire_psbl_order())
        except Exception:
            orderable_cash = extract_orderable_cash(balance)
        holdings = [parse_holding(item) for item in balance.get("output1", [])]
        holdings = [item for item in holdings if item.qty > 0]
        return KisAccountOut(
            ok=True,
            account=account,
            mode=mode,
            cash=extract_cash(balance),
            orderable_cash=orderable_cash,
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
