from __future__ import annotations

import logging
from datetime import date

import httpx

from app.core.config import get_settings
from app.services.emailer import send_admin_email_result
from app.services.supabase_rest import SupabaseRest


logger = logging.getLogger(__name__)
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
REPORT_INSTRUCTIONS = """
너는 한국 주식 시장을 분석하는 스윙 트레이딩 리포트 작성자다.

너의 역할:
- 제공된 정량 데이터만 근거로 사용한다.
- 외부 뉴스, 루머, 재무정보, 공시 내용을 임의로 만들지 않는다.
- 매수 추천, 수익 보장, 확정적 상승 표현을 사용하지 않는다.
- 투자 판단은 독자 책임이라는 유의 문구를 포함한다.
- 블로그에 바로 올릴 수 있는 한국어 Markdown 형식으로 작성한다.
- 문체는 전문적이지만 일반 투자자도 이해할 수 있게 쓴다.
- 너무 짧게 요약하지 말고, 각 종목별로 판단 근거와 리스크를 구체적으로 설명한다.

작성 형식:

# 오늘의 스윙 후보 리포트

## 1. 시장 및 전략 요약
- 오늘 후보군이 어떤 성격인지 요약한다.
- 스윙 관점에서 변동성, 거래량, 추세 전환 신호가 있는지 설명한다.
- 단, 시장 전체 전망을 임의로 단정하지 않는다.

## 2. 핵심 후보 요약표
Markdown 표로 작성한다.

표 컬럼:
- 순위
- 종목명
- 코드
- 기업 개요
- 점수
- 진입가
- 손절가
- 1차 익절
- 2차 익절
- 최대 보유일
- 핵심 근거

## 3. 종목별 상세 분석

각 종목마다 아래 형식을 반복한다.

### 종목명 (종목코드)

#### 기업 개요
- 제공된 company_profile 데이터를 기반으로 어떤 시장에 속한 기업인지 설명한다.
- sector, industry, business_summary가 있으면 어떤 사업을 주력으로 하는지 설명한다.
- 제공 데이터가 부족하면 추측하지 말고 "제공 데이터 기준 확인 불가"라고 쓴다.

#### 핵심 요약
- 이 종목이 후보로 나온 핵심 이유를 2~3문장으로 설명한다.

#### 기술적 근거
- RSI 위치를 해석한다.
- 일목균형표 전환선/기준선 관계를 설명한다.
- 볼린저 밴드 폭과 확장률을 기반으로 변동성 확대 여부를 설명한다.
- 거래량/거래대금 배율을 기반으로 수급 확인 여부를 설명한다.
- 5일/20일 수익률과 시장 대비 상대강도를 설명한다.

#### 매매 계획
- 진입가는 관찰 기준 가격으로 설명한다.
- 손절가는 리스크 관리 기준으로 설명한다.
- 1차 익절, 2차 익절, 추적 손절의 역할을 설명한다.
- 권장 보유일과 최대 보유일을 설명한다.

#### 리스크 체크
- 손절폭이 큰지 작은지 평가한다.
- ATR 비율로 변동성 리스크를 설명한다.
- 갭 상승, 윗꼬리, 과열 가능성이 있으면 언급한다.
- 조건이 훼손될 경우 제외해야 한다고 설명한다.

#### 블로그용 한줄 코멘트
- 과장 없이 짧은 한 문장으로 정리한다.

## 4. 오늘의 관찰 포인트
- 어떤 가격대에서 관심을 가질 수 있는지 설명한다.
- 어떤 조건이면 매수를 피해야 하는지 설명한다.
- 스윙 전략상 분할 진입/분할 청산의 필요성을 설명한다.

## 5. 투자 유의사항
아래 문구를 반드시 포함한다.

본 리포트는 자동화된 정량 조건을 바탕으로 작성된 참고용 분석 자료입니다. 특정 종목의 매수 또는 매도를 권유하는 투자 자문이 아니며, 모든 투자 판단과 책임은 투자자 본인에게 있습니다. 주식 투자는 원금 손실 가능성이 있습니다.

추가 규칙:
- "무조건", "확실히", "급등", "대박", "보장" 같은 표현은 사용하지 않는다.
- "매수해야 한다" 대신 "관찰할 수 있다", "조건 충족 여부를 확인할 필요가 있다"라고 표현한다.
- 데이터가 없는 항목은 추측하지 말고 "제공 데이터 기준 확인 불가"라고 쓴다.
- 각 종목 분석은 최소 500자 이상으로 작성한다.
- 전체 리포트는 Markdown 형식으로만 출력한다.
""".strip()


async def generate_daily_signal_report(signals: list[dict], trade_date: date) -> str | None:
    result = await generate_daily_signal_report_result(signals, trade_date)
    return result.get("report") if result.get("ok") else None


async def generate_daily_signal_report_result(signals: list[dict], trade_date: date) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        message = "OPENAI_API_KEY is not configured"
        logger.info("AI report skipped: %s", message)
        return {"ok": False, "stage": "openai_config", "error": message, "report": None}
    if not signals:
        return {"ok": False, "stage": "input", "error": "No signals provided", "report": None}

    top_n = max(1, min(int(settings.ai_report_top_n or 3), len(signals)))
    prompt = build_report_prompt(signals[:top_n], trade_date)
    payload = {
        "model": settings.ai_report_model,
        "instructions": REPORT_INSTRUCTIONS,
        "input": prompt,
        "max_output_tokens": 3500,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                OPENAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "stage": "openai",
                    "error": format_openai_error(response),
                    "report": None,
                }
            data = response.json()
    except httpx.TimeoutException as exc:
        logger.exception("AI report generation timed out")
        return {"ok": False, "stage": "openai", "error": f"OpenAI timeout: {repr(exc)}", "report": None}
    except httpx.RequestError as exc:
        logger.exception("AI report request failed")
        return {"ok": False, "stage": "openai", "error": f"OpenAI request error: {type(exc).__name__}: {repr(exc)}", "report": None}
    except Exception as exc:
        logger.exception("AI report generation failed")
        return {"ok": False, "stage": "openai", "error": f"OpenAI error: {type(exc).__name__}: {repr(exc)}", "report": None}

    text = data.get("output_text") or extract_output_text(data)
    if not text or not text.strip():
        return {"ok": False, "stage": "openai", "error": "OpenAI response did not contain output text", "report": None}
    return {"ok": True, "stage": "openai", "error": None, "report": text.strip()}


def format_openai_error(response: httpx.Response) -> str:
    body = response.text[:1500]
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = error.get("message") or body
            code = error.get("code") or error.get("type") or "unknown"
            return f"OpenAI HTTP {response.status_code} ({code}): {message}"
    except Exception:
        pass
    return f"OpenAI HTTP {response.status_code}: {body or response.reason_phrase}"


async def send_daily_signal_report(signals: list[dict], trade_date: date) -> bool:
    return (await create_daily_signal_report_result(signals, trade_date, report_type="daily"))["saved"]


async def send_daily_signal_report_result(signals: list[dict], trade_date: date) -> dict:
    report_result = await generate_daily_signal_report_result(signals, trade_date)
    if not report_result["ok"]:
        return {"sent": False, "stage": report_result["stage"], "error": report_result["error"]}
    report = report_result["report"]
    subject = f"[스윙봇] {trade_date.isoformat()} 상위 시그널 AI 리포트"
    email_result = await send_admin_email_result(subject, report)
    return {"sent": email_result["sent"], "stage": email_result["stage"], "error": email_result["error"]}


async def create_daily_signal_report_result(
    signals: list[dict],
    trade_date: date,
    *,
    report_type: str,
    code: str | None = None,
    name: str | None = None,
) -> dict:
    report_result = await generate_daily_signal_report_result(signals, trade_date)
    if not report_result["ok"]:
        return {"saved": False, "stage": report_result["stage"], "error": report_result["error"], "report_id": None}

    markdown = report_result["report"]
    title_name = name or ("상위 시그널" if report_type == "daily" else "개별 종목")
    title = f"{trade_date.isoformat()} {title_name} AI 리포트"
    rows = await SupabaseRest().upsert(
        "ai_reports",
        {
            "trade_date": trade_date.isoformat(),
            "report_type": report_type,
            "code": code or "ALL",
            "name": name,
            "title": title,
            "markdown": markdown,
            "raw": {
                "signals_count": len(signals),
                "model": get_settings().ai_report_model,
                "codes": [signal.get("Code") for signal in signals],
            },
        },
        on_conflict="trade_date,report_type,code",
    )
    row = rows[0] if rows else {}
    return {"saved": True, "stage": "db", "error": None, "report_id": row.get("id"), "title": row.get("title")}


def build_report_prompt(signals: list[dict], trade_date: date) -> str:
    selected = [select_report_input_fields(signal, index) for index, signal in enumerate(signals, start=1)]
    sections = [
        f"작성일: {trade_date.isoformat()}",
        "아래 데이터는 오늘 스윙봇 상위 점수 종목에서 리포트 작성에 필요한 필드만 선별한 값이다.",
        "필드 설명:",
        "- company_profile: 시장, 섹터, 업종, 사업요약, 시가총액 등 기업 개요 정보",
        "- score: 스캐너 종합 점수",
        "- entry_price: 관찰 기준 진입가",
        "- stop_loss: 손절 기준가",
        "- take_profit_1, take_profit_2: 분할 익절 기준가",
        "- trailing_stop: 익절 후 잔여 수량 방어 기준가",
        "- rsi14: RSI 14일 값",
        "- tenkan, kijun: 일목균형표 전환선/기준선",
        "- bb_width_pct, bb_expansion_pct: 볼린저 밴드 폭과 확장률",
        "- volume_spike_ratio, trading_value_spike_ratio: 거래량/거래대금 증가 배율",
        "- relative_strength_20d_pct: 시장 대비 20일 상대강도",
        "- atr_pct: 가격 대비 ATR 변동성",
        "- risk_pct, stop_pct: 리스크/손절폭",
        "- gap_pct, upper_shadow_ratio: 갭 상승과 윗꼬리 리스크",
        "- reasons: 스캐너가 점수를 부여한 핵심 근거",
        "",
    ]
    for item in selected:
        sections.append(format_signal_for_prompt(item))
    return "\n".join(sections)


def select_report_input_fields(signal: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "name": signal.get("Name"),
        "code": signal.get("Code"),
        "company_profile": normalize_company_profile(signal.get("CompanyProfile")),
        "score": signal.get("Score"),
        "entry_price": signal.get("Entry"),
        "stop_loss": signal.get("StopLoss"),
        "take_profit_1": signal.get("TakeProfit1"),
        "take_profit_2": signal.get("TakeProfit2"),
        "trailing_stop": signal.get("TrailingStop"),
        "hold_min_days": signal.get("HoldMinDays"),
        "hold_preferred_days": signal.get("HoldPreferredDays"),
        "hold_max_days": signal.get("HoldMaxDays"),
        "rsi14": signal.get("RSI14"),
        "tenkan": signal.get("Tenkan"),
        "kijun": signal.get("Kijun"),
        "days_after_ichimoku_cross": signal.get("DaysAfterIchimokuCross"),
        "distance_to_kijun_pct": signal.get("DistanceToKijun(%)"),
        "bb_upper": signal.get("BBUpper"),
        "bb_lower": signal.get("BBLower"),
        "bb_width_pct": signal.get("BBWidth(%)"),
        "bb_expansion_pct": signal.get("BBExpansion(%)"),
        "volume_spike_ratio": signal.get("VolumeSpikeRatio"),
        "trading_value_spike_ratio": signal.get("TradingValueSpikeRatio"),
        "trading_value_20d": signal.get("TradingValue20D"),
        "ret_5d_pct": signal.get("Ret_5D(%)"),
        "ret_20d_pct": signal.get("Ret_20D(%)"),
        "market_ret_20d_pct": signal.get("MarketRet_20D(%)"),
        "relative_strength_20d_pct": signal.get("RelativeStrength_20D(%)"),
        "atr14": signal.get("ATR14"),
        "atr_pct": signal.get("ATR(%)"),
        "risk_pct": signal.get("RiskPct"),
        "stop_pct": signal.get("StopPct"),
        "gap_pct": signal.get("Gap(%)"),
        "upper_shadow_ratio": signal.get("UpperShadowRatio"),
        "distance_to_ma20_pct": signal.get("DistanceToMA20(%)"),
        "distance_from_52w_low_pct": signal.get("DistanceFrom52WLow(%)"),
        "universe": signal.get("Universe"),
        "market_filter": signal.get("MarketFilter"),
        "reasons": signal.get("Reasons"),
    }


def format_signal_for_prompt(signal: dict) -> str:
    lines = [f"## 후보 {signal['rank']}: {signal.get('name')} ({signal.get('code')})"]
    for key, value in signal.items():
        if key == "rank":
            continue
        lines.append(f"- {key}: {format_prompt_value(value)}")
    return "\n".join(lines)


def format_prompt_value(value: object) -> object:
    if value is None or value == "":
        return "제공 데이터 기준 확인 불가"
    return value


def normalize_company_profile(value: object) -> dict:
    profile = value if isinstance(value, dict) else {}
    return {
        "market": profile.get("market") or "제공 데이터 기준 확인 불가",
        "sector": profile.get("sector") or "제공 데이터 기준 확인 불가",
        "industry": profile.get("industry") or "제공 데이터 기준 확인 불가",
        "business_summary": profile.get("business_summary") or "제공 데이터 기준 확인 불가",
        "market_cap": profile.get("market_cap") or "제공 데이터 기준 확인 불가",
    }


def extract_output_text(data: dict) -> str:
    chunks: list[str] = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks)
