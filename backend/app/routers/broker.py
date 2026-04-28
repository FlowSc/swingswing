from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.schemas.broker import BrokerCredentialIn, BrokerCredentialOut, BrokerStatusOut
from app.services.broker_credentials import get_broker_credentials, save_broker_credentials


router = APIRouter(prefix="/broker", tags=["broker"])


@router.get("/kis/status", response_model=BrokerStatusOut)
async def broker_status(user: CurrentUser = Depends(get_current_user)) -> BrokerStatusOut:
    row = await get_broker_credentials(user.id)
    if not row:
        return BrokerStatusOut(configured=False)
    return BrokerStatusOut(
        configured=True,
        mode=row.get("mode"),
        account_no=row.get("kis_account_no"),
        account_product_code=row.get("kis_account_product_code"),
        telegram_chat_id=row.get("telegram_chat_id"),
        enabled=row.get("enabled", False),
    )


@router.post("/kis", response_model=BrokerCredentialOut)
async def save_kis_credentials(
    payload: BrokerCredentialIn,
    user: CurrentUser = Depends(get_current_user),
) -> BrokerCredentialOut:
    row = await save_broker_credentials(user.id, payload)
    return BrokerCredentialOut(
        user_id=row["user_id"],
        kis_account_no=row["kis_account_no"],
        kis_account_product_code=row["kis_account_product_code"],
        mode=row["mode"],
        telegram_chat_id=row.get("telegram_chat_id"),
        enabled=row.get("enabled", True),
    )
