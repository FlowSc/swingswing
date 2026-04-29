from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.schemas.bot import BotControlIn, BotControlOut, WatchTickIn
from app.services.broker_credentials import get_broker_credentials, get_decrypted_broker_credentials, set_bot_enabled
from app.services.scanner import finalize_chunked_scan, prepare_chunked_scan_state, process_scan_chunk
from app.services.supabase_rest import SupabaseRest
from app.services.watcher import run_watch_tick_for_user


router = APIRouter(prefix="/bot", tags=["bot"])


def require_scan_admin(user: CurrentUser) -> None:
    settings = get_settings()
    if (user.email or "").lower() != settings.scan_admin_email.lower():
        raise HTTPException(status_code=403, detail="Only scan admin can run signal scans")


def now_iso() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).isoformat()


@router.post("/control", response_model=BotControlOut)
async def control_bot(
    payload: BotControlIn,
    user: CurrentUser = Depends(get_current_user),
) -> BotControlOut:
    row = await set_bot_enabled(user.id, payload.enabled)
    return BotControlOut(user_id=row["user_id"], enabled=row["enabled"])


@router.post("/scan")
async def scan(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    require_scan_admin(user)
    state = await prepare_chunked_scan_state()
    rows = await SupabaseRest().insert(
        "scan_runs",
        {
            "requested_by": user.id,
            "status": "running",
            "trade_date": state["trade_date"],
            "result": state,
            "started_at": now_iso(),
        },
    )
    scan_run = rows[0]
    scan_run_id = scan_run["id"]
    return {
        "queued": True,
        "scan_run_id": scan_run_id,
        "offset": state["offset"],
        "total": state["total"],
        "message": "Signal scan initialized. Continue with scan step API.",
    }


@router.post("/scan-runs/{scan_run_id}/step")
async def scan_step(scan_run_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    require_scan_admin(user)
    rows = await SupabaseRest().select("scan_runs", filters={"id": f"eq.{scan_run_id}"}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="Scan run not found")
    scan_run = rows[0]
    if scan_run["status"] == "completed":
        return scan_run
    if scan_run["status"] == "failed":
        raise HTTPException(status_code=400, detail=scan_run.get("error") or "Scan run failed")

    try:
        state = await process_scan_chunk(scan_run.get("result") or {})
    except Exception as exc:
        await SupabaseRest().patch(
            "scan_runs",
            filters={"id": f"eq.{scan_run_id}"},
            payload={"status": "failed", "error": str(exc), "finished_at": now_iso()},
        )
        raise
    if state["done"]:
        try:
            credentials = await get_broker_credentials(user.id)
            telegram_chat_id = credentials.get("telegram_chat_id") if credentials else None
            final_result = await finalize_chunked_scan(user.id, state, telegram_chat_id)
            patched = await SupabaseRest().patch(
                "scan_runs",
                filters={"id": f"eq.{scan_run_id}"},
                payload={
                    "status": "completed",
                    "trade_date": final_result["trade_date"],
                    "signals_count": final_result["signals"],
                    "shared_saved": final_result["shared_saved"],
                    "result": {**state, "final": final_result},
                    "finished_at": now_iso(),
                },
            )
            return patched[0]
        except Exception as exc:
            await SupabaseRest().patch(
                "scan_runs",
                filters={"id": f"eq.{scan_run_id}"},
                payload={"status": "failed", "error": str(exc), "finished_at": now_iso()},
            )
            raise

    patched = await SupabaseRest().patch(
        "scan_runs",
        filters={"id": f"eq.{scan_run_id}"},
        payload={
            "status": "running",
            "signals_count": len(state.get("candidates") or []),
            "result": state,
        },
    )
    return patched[0]


@router.get("/scan-runs/latest")
async def latest_scan_run(user: CurrentUser = Depends(get_current_user)) -> dict | None:
    rows = await SupabaseRest().select("scan_runs", order="created_at.desc", limit=1)
    return rows[0] if rows else None


@router.post("/watch-tick")
async def watch_tick(
    payload: WatchTickIn,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    credentials = await get_decrypted_broker_credentials(user.id)
    return await run_watch_tick_for_user(credentials, test_mode=payload.test_mode, dry_run=payload.dry_run)
