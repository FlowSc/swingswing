from datetime import date, datetime
import logging
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.services.broker_credentials import get_broker_credentials
from app.services.backtest import finalize_backtest_state, prepare_backtest_state, process_backtest_chunk, run_shared_signal_backtest
from app.services.memberships import require_admin_access
from app.services.supabase_rest import SupabaseRest
from app.services.watcher import sort_signals_for_autotrading


router = APIRouter(tags=["trading"])
logger = logging.getLogger(__name__)


class SignalBlockIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


async def signal_blocks_by_date(trade_date: str) -> dict[str, dict]:
    try:
        rows = await SupabaseRest().select(
            "public_signal_blocks",
            filters={"trade_date": f"eq.{trade_date}"},
            limit=500,
        )
    except RuntimeError:
        logger.exception("Failed to load public signal blocks: trade_date=%s", trade_date)
        return {}
    return {str(row.get("code") or "").zfill(6): row for row in rows if row.get("code")}


def attach_signal_blocks(rows: list[dict], blocks: dict[str, dict]) -> list[dict]:
    enriched: list[dict] = []
    for row in rows:
        code = str(row.get("code") or "").zfill(6)
        block = blocks.get(code)
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        enriched.append(
            {
                **row,
                "auto_buy_blocked": bool(block),
                "auto_buy_block_reason": block.get("reason") if block else None,
                "auto_buy_blocked_at": block.get("created_at") if block else None,
                "raw": {
                    **raw,
                    "AutoBuyBlocked": bool(block),
                    "AutoBuyBlockReason": block.get("reason") if block else None,
                },
            }
        )
    return enriched


def _score_bucket(score: float | None) -> str:
    value = float(score or 0)
    if value >= 18:
        return "18+"
    if value >= 15:
        return "15-17.99"
    if value >= 12:
        return "12-14.99"
    return "<12"


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def summarize_forward_buckets(rows: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(str(row.get("score_bucket") or "<12"), []).append(row)
    result: list[dict] = []
    for bucket in ["18+", "15-17.99", "12-14.99", "<12"]:
        items = buckets.get(bucket) or []
        if not items:
            continue
        summary = {"bucket": bucket, "count": len(items)}
        for horizon in (3, 5, 7, 15):
            returns = [float(item[f"return_{horizon}d_pct"]) for item in items if item.get(f"return_{horizon}d_pct") is not None]
            runups = [float(item[f"max_runup_{horizon}d_pct"]) for item in items if item.get(f"max_runup_{horizon}d_pct") is not None]
            drawdowns = [float(item[f"max_drawdown_{horizon}d_pct"]) for item in items if item.get(f"max_drawdown_{horizon}d_pct") is not None]
            summary[f"avg_return_{horizon}d_pct"] = _avg(returns)
            summary[f"win_rate_{horizon}d_pct"] = round(len([value for value in returns if value > 0]) / len(returns) * 100, 2) if returns else None
            summary[f"avg_runup_{horizon}d_pct"] = _avg(runups)
            summary[f"avg_drawdown_{horizon}d_pct"] = _avg(drawdowns)
        result.append(summary)
    return result


def reject_count_rows(scan: dict | None) -> list[dict]:
    result = scan.get("result") if isinstance(scan, dict) else {}
    counts = result.get("reject_counts") if isinstance(result, dict) else {}
    if not isinstance(counts, dict):
        return []
    return [
        {"reason_code": reason, "reason": translate_scan_reject_reason(reason), "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: int(item[1] or 0), reverse=True)
    ]


def translate_scan_reject_reason(reason: str) -> str:
    labels = {
        "data_short": "데이터 260거래일 미만",
        "excluded_name": "스팩/리츠/우선주성 이름 제외",
        "indicator_na": "지표 계산값 부족",
        "stale_market_data": "최신 캔들 날짜 불일치",
        "invalid_indicator": "주요 지표 비정상",
        "invalid_ohlc": "시가/고가/저가/종가 비정상",
        "invalid_volume_or_value": "거래량/거래대금 비정상",
        "price_too_low": "1,000원 미만",
        "trading_value_too_low": "20일 평균 거래대금 부족",
        "intraday_drop": "당일 -5% 이하 급락",
        "pullback_from_day_high": "당일 고점 대비 과도한 밀림",
        "ichimoku_filter": "일목 전환선/기준선 조건 미통과",
        "bb_expansion_filter": "볼린저 밴드폭 확장 부족",
        "rsi_filter": "RSI 조건 미통과",
        "volume_20d_too_low": "20일 평균 거래량 부족",
        "volume_ratio_too_low": "오늘 거래량이 5일 평균보다 낮음",
        "stop_pct_too_wide": "손절폭 10% 초과",
        "data_error": "데이터 조회/처리 오류",
    }
    return labels.get(reason, reason)


@router.get("/signals/today")
async def today_signals(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    today = datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()
    return await signals_by_date(today, user)


@router.get("/signals")
async def signals_by_date(
    trade_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    try:
        rows = await SupabaseRest().select(
            "shared_signals",
            filters={"trade_date": f"eq.{trade_date}"},
            order="score.desc",
            limit=300,
        )
        blocks = await signal_blocks_by_date(trade_date)
        return sort_signals_for_autotrading(attach_signal_blocks(rows, blocks))[:30]
    except Exception:
        logger.exception("Failed to load signals: trade_date=%s user_id=%s", trade_date, user.id)
        return []


@router.post("/signals/{trade_date}/{code}/auto-buy-block")
async def block_signal_auto_buy(
    payload: SignalBlockIn,
    trade_date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    code: str = Path(..., pattern=r"^\d{6}$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_admin_access(user.id, user.email)
    normalized_code = code.zfill(6)
    signals = await SupabaseRest().select(
        "shared_signals",
        filters={"trade_date": f"eq.{trade_date}", "code": f"eq.{normalized_code}"},
        limit=1,
    )
    if not signals:
        raise HTTPException(status_code=404, detail="Signal not found.")
    signal = signals[0]
    rows = await SupabaseRest().upsert(
        "public_signal_blocks",
        {
            "trade_date": trade_date,
            "code": normalized_code,
            "name": signal.get("name"),
            "reason": payload.reason or "관리자 매수 금지",
            "blocked_by": user.id,
            "updated_at": datetime.now(ZoneInfo(get_settings().timezone)).isoformat(),
        },
        on_conflict="trade_date,code",
    )
    return {"blocked": True, "signal": signal, "block": rows[0] if rows else None}


@router.delete("/signals/{trade_date}/{code}/auto-buy-block")
async def unblock_signal_auto_buy(
    trade_date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    code: str = Path(..., pattern=r"^\d{6}$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_admin_access(user.id, user.email)
    normalized_code = code.zfill(6)
    await SupabaseRest().delete(
        "public_signal_blocks",
        filters={"trade_date": f"eq.{trade_date}", "code": f"eq.{normalized_code}"},
    )
    return {"blocked": False, "trade_date": trade_date, "code": normalized_code}


@router.get("/signals/dates")
async def signal_dates(user: CurrentUser = Depends(get_current_user)) -> list[str]:
    try:
        rows = await SupabaseRest().select(
            "shared_signals",
            columns="trade_date",
            order="trade_date.desc",
            limit=30,
        )
    except Exception:
        logger.exception("Failed to load signal dates: user_id=%s", user.id)
        return []
    seen = set()
    dates: list[str] = []
    for row in rows:
        value = row.get("trade_date")
        if value and value not in seen:
            seen.add(value)
            dates.append(value)
    return dates


@router.get("/positions")
async def positions(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    try:
        credentials = await get_broker_credentials(user.id)
        filters = {"user_id": f"eq.{user.id}"}
        or_filter = None
        if credentials and credentials.get("id"):
            if (credentials.get("mode") or "paper") == "paper":
                or_filter = f"(broker_account_id.eq.{credentials['id']},broker_account_id.is.null)"
            else:
                filters["broker_account_id"] = f"eq.{credentials['id']}"
        return await SupabaseRest().select(
            "positions",
            filters=filters,
            or_filter=or_filter,
            order="created_at.desc",
            limit=100,
        )
    except Exception:
        logger.exception("Failed to load positions: user_id=%s", user.id)
        return []


@router.get("/trade-logs")
async def trade_logs(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    try:
        credentials = await get_broker_credentials(user.id)
        filters = {"user_id": f"eq.{user.id}"}
        or_filter = None
        if credentials and credentials.get("id"):
            if (credentials.get("mode") or "paper") == "paper":
                or_filter = f"(broker_account_id.eq.{credentials['id']},broker_account_id.is.null)"
            else:
                filters["broker_account_id"] = f"eq.{credentials['id']}"
        return await SupabaseRest().select(
            "trade_logs",
            filters=filters,
            or_filter=or_filter,
            order="created_at.desc",
            limit=100,
        )
    except Exception:
        logger.exception("Failed to load trade logs: user_id=%s", user.id)
        return []


@router.get("/trade-decisions")
async def trade_decisions(
    trade_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    credentials = await get_broker_credentials(user.id)
    target_date = trade_date or datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()
    filters = {"user_id": f"eq.{user.id}", "decision_date": f"eq.{target_date}"}
    or_filter = None
    if credentials and credentials.get("id"):
        if (credentials.get("mode") or "paper") == "paper":
            or_filter = f"(broker_account_id.eq.{credentials['id']},broker_account_id.is.null)"
        else:
            filters["broker_account_id"] = f"eq.{credentials['id']}"
    return await SupabaseRest().select(
        "trade_decision_logs",
        filters=filters,
        or_filter=or_filter,
        order="created_at.desc",
        limit=200,
    )


@router.get("/watcher-runs")
async def watcher_runs(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    try:
        credentials = await get_broker_credentials(user.id)
        filters = {"user_id": f"eq.{user.id}"}
        or_filter = None
        if credentials and credentials.get("id"):
            if (credentials.get("mode") or "paper") == "paper":
                or_filter = f"(broker_account_id.eq.{credentials['id']},broker_account_id.is.null)"
            else:
                filters["broker_account_id"] = f"eq.{credentials['id']}"
        return await SupabaseRest().select(
            "watcher_runs",
            filters=filters,
            or_filter=or_filter,
            order="created_at.desc",
            limit=100,
        )
    except Exception:
        logger.exception("Failed to load watcher runs: user_id=%s", user.id)
        return []


@router.get("/dashboard/daily")
async def daily_dashboard(user: CurrentUser = Depends(get_current_user)) -> dict:
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    start_at = datetime.combine(today, datetime.min.time(), tzinfo=ZoneInfo(settings.timezone)).isoformat()
    credentials = await get_broker_credentials(user.id)
    account_id = credentials.get("id") if credentials else None
    account_mode = (credentials.get("mode") or "paper") if credentials else "paper"
    position_filters = {"user_id": f"eq.{user.id}"}
    log_filters = {"user_id": f"eq.{user.id}", "created_at": f"gte.{start_at}"}
    decision_filters = {"user_id": f"eq.{user.id}", "decision_date": f"eq.{today.isoformat()}"}
    position_or_filter = None
    log_or_filter = None
    decision_or_filter = None
    if account_id:
        if account_mode == "paper":
            position_or_filter = f"(broker_account_id.eq.{account_id},broker_account_id.is.null)"
            log_or_filter = f"(broker_account_id.eq.{account_id},broker_account_id.is.null)"
            decision_or_filter = f"(broker_account_id.eq.{account_id},broker_account_id.is.null)"
        else:
            position_filters["broker_account_id"] = f"eq.{account_id}"
            log_filters["broker_account_id"] = f"eq.{account_id}"
            decision_filters["broker_account_id"] = f"eq.{account_id}"

    rest = SupabaseRest()
    signals = await rest.select("shared_signals", filters={"trade_date": f"eq.{today.isoformat()}"}, limit=100)
    positions = await rest.select("positions", filters=position_filters, or_filter=position_or_filter, limit=200)
    logs = await rest.select("trade_logs", filters=log_filters, or_filter=log_or_filter, limit=200)
    decisions = await rest.select("trade_decision_logs", filters=decision_filters, or_filter=decision_or_filter, limit=300)
    scans = await rest.select("scan_runs", order="created_at.desc", limit=1)
    return {
        "date": today.isoformat(),
        "signals_count": len(signals),
        "open_positions": len([row for row in positions if row.get("status") == "OPEN"]),
        "buy_count": len([row for row in logs if row.get("action") == "BUY"]),
        "sell_count": len([row for row in logs if row.get("action") == "SELL"]),
        "skip_count": len([row for row in decisions if row.get("decision") == "SKIP"]),
        "latest_scan": scans[0] if scans else None,
        "top_skip_reasons": summarize_reasons(decisions),
    }


@router.get("/diagnostics/daily")
async def daily_diagnostics(
    trade_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_admin_access(user.id, user.email)
    rest = SupabaseRest()
    scans = await rest.select(
        "scan_runs",
        filters={"trade_date": f"eq.{trade_date}"},
        order="created_at.desc",
        limit=1,
    )
    scan = scans[0] if scans else None
    signals = await rest.select(
        "shared_signals",
        filters={"trade_date": f"eq.{trade_date}"},
        order="score.desc",
        limit=300,
    )
    try:
        forward_rows = await rest.select(
            "signal_forward_returns",
            filters={"trade_date": f"eq.{trade_date}"},
            order="code.asc",
            limit=300,
        )
    except RuntimeError:
        logger.warning("Daily diagnostics forward returns unavailable; table may not be migrated.", exc_info=True)
        forward_rows = []
    signal_by_code = {str(row.get("code") or "").zfill(6): row for row in signals}
    enriched_forward: list[dict] = []
    for row in forward_rows:
        code = str(row.get("code") or "").zfill(6)
        signal = signal_by_code.get(code) or {}
        score = signal.get("score")
        raw = signal.get("raw") if isinstance(signal.get("raw"), dict) else {}
        enriched_forward.append(
            {
                **row,
                "code": code,
                "score": score,
                "score_bucket": _score_bucket(float(score or 0)),
                "stop_pct": raw.get("StopPct"),
                "rsi": raw.get("RSI14"),
                "volume_spike_ratio": raw.get("VolumeSpikeRatio"),
                "bb_expansion": raw.get("BBExpansion(%)"),
            }
        )
    return {
        "trade_date": trade_date,
        "scan": scan,
        "signals_count": len(signals),
        "forward_count": len(enriched_forward),
        "reject_counts": reject_count_rows(scan),
        "score_buckets": summarize_forward_buckets(enriched_forward),
        "forward_returns": enriched_forward,
    }


@router.get("/backtest/shared-signals")
async def backtest_shared_signals(
    days: int = Query(120, ge=30, le=730),
    max_signals: int = Query(200, ge=10, le=1000),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_admin_access(user.id, user.email)
    return await run_shared_signal_backtest(days=days, max_signals=max_signals)


@router.post("/backtest/historical/start")
async def start_historical_backtest(
    days: int = Query(120, ge=30, le=730),
    max_signals: int = Query(200, ge=10, le=1000),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_admin_access(user.id, user.email)
    state = clean_json(await prepare_backtest_state(days, max_signals))
    rows = await SupabaseRest().insert(
        "backtest_runs",
        {
            "requested_by": user.id,
            "status": "running",
            "source": state["source"],
            "strategy_key": state["strategy_key"],
            "strategy_version": state["strategy_version"],
            "days": days,
            "max_signals": max_signals,
            "start_date": state["start_date"],
            "end_date": state["end_date"],
            "universe_scope": state["universe_scope"],
            "processed_count": state["offset"],
            "total_count": state["total"],
            "candidates_count": len(state.get("candidates") or []),
            "result": state,
            "started_at": now_iso(),
        },
    )
    return backtest_run_to_job(rows[0])


@router.post("/backtest/historical/runs/{run_id}/step")
async def step_historical_backtest(
    run_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_admin_access(user.id, user.email)
    rows = await SupabaseRest().select("backtest_runs", filters={"id": f"eq.{run_id}", "requested_by": f"eq.{user.id}"}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    run = rows[0]
    if run["status"] == "completed":
        return backtest_run_to_job(run)

    try:
        state = await process_backtest_chunk(run.get("result") or {})
    except Exception as exc:
        patched = await SupabaseRest().patch(
            "backtest_runs",
            filters={"id": f"eq.{run_id}"},
            payload={"status": "failed", "error": str(exc), "result": run.get("result") or {}},
        )
        return backtest_run_to_job(patched[0])

    if state["done"]:
        try:
            summary = clean_json(await finalize_backtest_state(state))
            await replace_backtest_trades(run_id, summary.get("trades") or [])
            patched = await SupabaseRest().patch(
                "backtest_runs",
                filters={"id": f"eq.{run_id}"},
                payload={
                    "status": "completed",
                    "processed_count": state["offset"],
                    "total_count": state["total"],
                    "candidates_count": len(state.get("candidates") or []),
                    "tested_count": summary.get("signals_tested") or 0,
                    "result": clean_json(state),
                    "summary": summary,
                    "error": None,
                    "finished_at": now_iso(),
                },
            )
            return backtest_run_to_job(patched[0])
        except Exception as exc:
            patched = await SupabaseRest().patch(
                "backtest_runs",
                filters={"id": f"eq.{run_id}"},
                payload={
                    "status": "failed",
                    "processed_count": state["offset"],
                    "total_count": state["total"],
                    "candidates_count": len(state.get("candidates") or []),
                    "result": clean_json(state),
                    "error": str(exc),
                },
            )
            return backtest_run_to_job(patched[0])

    patched = await SupabaseRest().patch(
        "backtest_runs",
        filters={"id": f"eq.{run_id}"},
        payload={
            "status": "running",
            "processed_count": state["offset"],
            "total_count": state["total"],
            "candidates_count": len(state.get("candidates") or []),
            "result": clean_json(state),
            "error": None,
        },
    )
    return backtest_run_to_job(patched[0])


@router.get("/backtest/historical/jobs/{job_id}")
async def get_historical_backtest_job(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_admin_access(user.id, user.email)
    rows = await SupabaseRest().select("backtest_runs", filters={"id": f"eq.{job_id}", "requested_by": f"eq.{user.id}"}, limit=1)
    if not rows:
        return {"job_id": job_id, "status": "not_found", "progress": {}, "result": None, "error": "Backtest run not found."}
    return backtest_run_to_job(rows[0])


@router.get("/backtest/historical/runs")
async def list_historical_backtest_runs(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    await require_admin_access(user.id, user.email)
    rows = await SupabaseRest().select(
        "backtest_runs",
        columns="id,requested_by,status,source,strategy_key,strategy_version,days,max_signals,start_date,end_date,universe_scope,processed_count,total_count,candidates_count,tested_count,summary,error,created_at,started_at,finished_at",
        filters={"requested_by": f"eq.{user.id}"},
        order="created_at.desc",
        limit=30,
    )
    return [backtest_run_to_job(row) for row in rows]


@router.get("/backtest/historical/runs/{run_id}/trades")
async def list_historical_backtest_trades(
    run_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    await require_admin_access(user.id, user.email)
    rows = await SupabaseRest().select("backtest_runs", filters={"id": f"eq.{run_id}", "requested_by": f"eq.{user.id}"}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return await SupabaseRest().select(
        "backtest_trades",
        columns="trade_date,entry_date,code,name,score,entry,exit_price,return_pct,hold_days,exit_reason,tp1_done,tp2_done,remaining_qty_ratio,raw",
        filters={"backtest_run_id": f"eq.{run_id}"},
        order="return_pct.desc",
        limit=5000,
    )


def now_iso() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).isoformat()


def backtest_run_to_job(row: dict) -> dict:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    return {
        "job_id": str(row["id"]),
        "run_id": row["id"],
        "status": "running",
        **{key: row.get(key) for key in ("days", "max_signals", "source", "strategy_key", "strategy_version", "start_date", "end_date", "universe_scope", "error", "created_at", "started_at", "finished_at")},
        "status": row.get("status"),
        "progress": {
            "processed": row.get("processed_count") or 0,
            "total": row.get("total_count") or 0,
            "signals": row.get("candidates_count") or 0,
            "skipped": (row.get("result") or {}).get("skipped", 0) if isinstance(row.get("result"), dict) else 0,
            "tested": row.get("tested_count") or summary.get("signals_tested") or 0,
        },
        "result": summary if row.get("status") == "completed" else None,
    }


async def replace_backtest_trades(run_id: int, trades: list[dict]) -> None:
    await SupabaseRest().delete("backtest_trades", filters={"backtest_run_id": f"eq.{run_id}"})
    for trade in trades:
        await SupabaseRest().insert(
            "backtest_trades",
            {
                "backtest_run_id": run_id,
                "trade_date": trade.get("trade_date"),
                "entry_date": trade.get("entry_date"),
                "code": trade.get("code"),
                "name": trade.get("name"),
                "score": trade.get("score"),
                "entry": trade.get("entry"),
                "exit_price": trade.get("exit_price"),
                "return_pct": trade.get("return_pct"),
                "hold_days": trade.get("hold_days"),
                "exit_reason": trade.get("exit_reason"),
                "tp1_done": trade.get("tp1_done"),
                "tp2_done": trade.get("tp2_done"),
                "remaining_qty_ratio": trade.get("remaining_qty_ratio"),
                "raw": clean_json(trade),
            },
        )


def clean_json(value):
    if isinstance(value, dict):
        return {key: clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return clean_json(value.item())
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def summarize_reasons(rows: list[dict]) -> list[dict]:
    counts: dict[str, dict] = {}
    for row in rows:
        key = row.get("reason_code") or "Unknown"
        item = counts.setdefault(key, {"reason_code": key, "reason": row.get("reason") or key, "count": 0})
        item["count"] += 1
    return sorted(counts.values(), key=lambda item: item["count"], reverse=True)[:5]
