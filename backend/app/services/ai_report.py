from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.services.company_profile import enrich_company_profile
from app.services.emailer import send_admin_email_result
from app.services.supabase_rest import SupabaseRest


logger = logging.getLogger(__name__)
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
INVESTMENT_NOTICE_TEXT = (
    "본 리포트는 자동화된 정량 조건을 바탕으로 작성된 참고용 분석 자료입니다. "
    "특정 종목의 매수 또는 매도를 권유하는 투자 자문이 아니며, "
    "모든 투자 판단과 책임은 투자자 본인에게 있습니다. 주식 투자는 원금 손실 가능성이 있습니다."
)
INVESTMENT_NOTICE_HTML = f'<p style="color:#d93025;">{INVESTMENT_NOTICE_TEXT}</p>'
HANJA_REPLACEMENTS = {
    "乖離": "괴리",
    "·": "/",
}
REPORT_INSTRUCTIONS = """
너는 한국 주식 시장을 분석하는 스윙 트레이딩 리포트 작성자다.

너의 역할:
- 제공된 정량 데이터만 근거로 사용한다.
- 외부 뉴스, 루머, 재무정보, 공시 내용을 임의로 만들지 않는다.
- 매수 추천, 수익 보장, 확정적 상승 표현을 사용하지 않는다.
- 투자 판단은 독자 책임이라는 유의 문구를 포함한다.
- 네이버 블로그에 바로 복사해 붙여넣을 수 있는 한국어 HTML 형식으로 작성한다.
- 문장 어미는 딱딱한 보고서체 대신 "~했습니다", "~볼 수 있습니다", "~확인했습니다"처럼 부드러운 설명체로 작성한다.
- 독자에게 말하듯 자연스럽게 설명하되, 과장된 홍보 문구는 쓰지 않는다.
- 시가총액은 제공된 축약 표기만 사용하고, 원 단위 숫자와 조/억 단위 해석을 한 문장에서 반복하지 않는다.
- 한자를 사용하지 않는다. 예: "乖離"가 아니라 "괴리" 또는 "이격"이라고 쓴다.
- 전문용어가 나오면 처음 등장하는 문단에서 괄호로 쉬운 설명을 붙인다. 예: RSI(최근 가격 상승/하락 압력을 숫자로 보여주는 지표), ATR(주가가 하루에 평균적으로 얼마나 흔들리는지 보는 변동성 지표), 일목균형표(추세 전환과 지지/저항을 함께 보는 보조지표), 볼린저 밴드(가격이 평균에서 얼마나 벌어졌는지 보는 변동성 지표).
- 각 섹션마다 숫자만 나열하지 말고 "이 값이 초보 투자자에게 어떤 의미인지"를 1~2문장으로 풀어서 설명한다.
- 너무 짧게 요약하지 말고, 각 종목별로 판단 근거와 리스크를 구체적으로 설명한다.
- 개별 기업 리포트는 전체 3,000자 이상으로 작성한다.
- 여러 종목 리포트는 종목별 분석을 최소 800자 이상으로 작성한다.
- 출력은 <article>, <h1>, <h2>, <h3>, <p>, <ul>, <li>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <strong>만 사용한다.
- 투자 유의 문구에 한해서만 <p style="color:#d93025;"> 형식을 사용할 수 있다.
- <html>, <head>, <body>, <script>, <style> 태그는 사용하지 않는다.
- ```html 같은 코드펜스나 설명 문장은 출력하지 않는다.
- 반드시 </article>로 끝낸다.

작성 형식:

<article>
<h1>{작성일} 스윙 후보 리포트</h1>

<h2>1. 시장 및 전략 요약</h2>
- 오늘 후보군이 어떤 성격인지 요약한다.
- 스윙 관점에서 변동성, 거래량, 추세 전환 신호가 있는지 설명한다.
- 단, 시장 전체 전망을 임의로 단정하지 않는다.

<h2>2. 핵심 후보 요약</h2>
표를 사용하지 말고 후보별 <h3>와 <ul><li> 구조로 작성한다.

각 후보에 포함할 항목:
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

<h2>3. 종목별 상세 분석</h2>

각 종목마다 아래 형식을 반복한다.

<h3>종목명 (종목코드)</h3>

<h3>기업 개요</h3>
- 제공된 company_profile 데이터를 기반으로 어떤 시장에 속한 기업인지 설명한다.
- sector, industry, business_summary가 있으면 어떤 사업을 주력으로 하는지 설명한다.
- 제공 데이터가 부족하면 추측하지 말고 "제공 데이터 기준 확인 불가"라고 쓴다.

<h3>핵심 요약</h3>
- 이 종목이 후보로 나온 핵심 이유를 2~3문장으로 설명한다.

<h3>기술적 근거</h3>
- RSI 위치를 해석한다.
- 일목균형표 전환선/기준선 관계를 설명한다.
- 볼린저 밴드 폭과 확장률을 기반으로 변동성 확대 여부를 설명한다.
- 거래량/거래대금 배율을 기반으로 수급 확인 여부를 설명한다.
- 5일/20일 수익률과 시장 대비 상대강도를 설명한다.

<h3>매매 계획</h3>
- 진입가는 관찰 기준 가격으로 설명한다.
- 손절가는 리스크 관리 기준으로 설명한다.
- 1차 익절, 2차 익절, 추적 손절의 역할을 설명한다.
- 권장 보유일과 최대 보유일을 설명한다.

<h3>리스크 체크</h3>
- 손절폭이 큰지 작은지 평가한다.
- ATR 비율로 변동성 리스크를 설명한다.
- 갭 상승, 윗꼬리, 과열 가능성이 있으면 언급한다.
- 조건이 훼손될 경우 제외해야 한다고 설명한다.

<h3>오늘의 한마디</h3>
- 과장 없이 짧은 한 문장으로 정리한다.

<h2>4. 오늘의 관찰 포인트</h2>
- 어떤 가격대에서 관심을 가질 수 있는지 설명한다.
- 어떤 조건이면 매수를 피해야 하는지 설명한다.
- 스윙 전략상 분할 진입/분할 청산의 필요성을 설명한다.

맨 하단에 항목 번호나 제목 없이 아래 문구를 빨간 글씨 문단으로 반드시 포함한다.
<p style="color:#d93025;">본 리포트는 자동화된 정량 조건을 바탕으로 작성된 참고용 분석 자료입니다. 특정 종목의 매수 또는 매도를 권유하는 투자 자문이 아니며, 모든 투자 판단과 책임은 투자자 본인에게 있습니다. 주식 투자는 원금 손실 가능성이 있습니다.</p>

추가 규칙:
- "무조건", "확실히", "급등", "대박", "보장" 같은 표현은 사용하지 않는다.
- "매수해야 한다" 대신 "관찰할 수 있다", "조건 충족 여부를 확인할 필요가 있다"라고 표현한다.
- 데이터가 없는 항목은 추측하지 말고 "제공 데이터 기준 확인 불가"라고 쓴다.
- 전문용어는 반드시 쉬운 해설을 함께 붙인다.
- 한자는 절대 사용하지 않는다.
- 입력 데이터의 영문 필드명이나 영문 사유 코드를 본문에 그대로 쓰지 않는다. 예: "Tenkan > Kijun", "Ichimoku cross", "BB expanding", "MA20 rising" 같은 표현은 절대 쓰지 말고 한국어 설명으로 바꿔 쓴다.
- 전체 리포트는 HTML fragment만 출력한다.
""".strip()

SIGNAL_REPORT_INSTRUCTIONS = """
너는 한국 주식 시장을 분석하는 스윙 트레이딩 개별 종목 리포트 작성자다.

너의 역할:
- 제공된 정량 데이터만 근거로 사용한다.
- 외부 뉴스, 루머, 재무정보, 공시 내용을 임의로 만들지 않는다.
- 매수 추천, 수익 보장, 확정적 상승 표현을 사용하지 않는다.
- 투자 판단은 독자 책임이라는 유의 문구를 포함한다.
- 네이버 블로그에 바로 복사해 붙여넣을 수 있는 한국어 HTML 형식으로 작성한다.
- 개별 기업 하나만 다루며, 다른 후보 비교표나 핵심 후보 요약표는 절대 작성하지 않는다.
- 문장 어미는 딱딱한 보고서체 대신 "~했습니다", "~볼 수 있습니다", "~확인했습니다"처럼 부드러운 설명체로 작성한다.
- 독자에게 말하듯 자연스럽게 설명하되, 과장된 홍보 문구는 쓰지 않는다.
- 시가총액은 제공된 축약 표기만 사용하고, 원 단위 숫자와 조/억 단위 해석을 한 문장에서 반복하지 않는다.
- 한자를 사용하지 않는다. 예: "乖離"가 아니라 "괴리" 또는 "이격"이라고 쓴다.
- 전문용어가 나오면 처음 등장하는 문단에서 괄호로 쉬운 설명을 붙인다. 예: RSI(최근 가격 상승/하락 압력을 숫자로 보여주는 지표), ATR(주가가 하루에 평균적으로 얼마나 흔들리는지 보는 변동성 지표), 일목균형표(추세 전환과 지지/저항을 함께 보는 보조지표), 볼린저 밴드(가격이 평균에서 얼마나 벌어졌는지 보는 변동성 지표).
- 각 섹션마다 숫자만 나열하지 말고 "이 값이 초보 투자자에게 어떤 의미인지"를 1~2문장으로 풀어서 설명한다.
- 전체 3,000자 이상으로 상세하게 작성한다.
- 출력은 <article>, <h1>, <h2>, <h3>, <p>, <ul>, <li>, <strong>만 사용한다.
- 투자 유의 문구에 한해서만 <p style="color:#d93025;"> 형식을 사용할 수 있다.
- <table>, <thead>, <tbody>, <tr>, <th>, <td>는 사용하지 않는다.
- <html>, <head>, <body>, <script>, <style> 태그는 사용하지 않는다.
- ```html 같은 코드펜스나 설명 문장은 출력하지 않는다.
- 반드시 </article>로 끝낸다.

작성 형식:

<article>
<h1>{작성일} 종목명 스윙 분석 리포트</h1>

<h2>1. 기업 개요</h2>
- 제공된 company_profile 데이터를 기반으로 어떤 시장에 속한 기업인지 설명한다.
- sector, industry, business_summary가 있으면 어떤 사업을 주력으로 하는지 설명한다.
- 제공 데이터가 부족하면 추측하지 말고 "제공 데이터 기준 확인 불가"라고 쓴다.

<h2>2. 스윙 후보로 포착된 이유</h2>
- 점수, RSI, 일목균형표, 볼린저 밴드, 거래량, 거래대금, 상대강도를 각각 해석한다.
- 단순 나열하지 말고 조건들이 서로 어떤 의미로 연결되는지 설명한다.

<h2>3. 기술적 분석</h2>
- RSI 위치를 해석한다.
- 일목균형표 전환선/기준선 관계와 돌파 이후 경과일을 설명한다.
- 볼린저 밴드 폭과 확장률을 기반으로 변동성 확대 여부를 설명한다.
- 5일/20일 수익률, 시장 대비 상대강도, MA20 거리, 52주 저점 대비 위치를 설명한다.

<h2>4. 거래량과 수급 확인</h2>
- 거래량 증가 배율과 거래대금 증가 배율을 설명한다.
- 거래대금 수준이 스윙 매매에 주는 의미를 설명한다.

<h2>5. 매매 시나리오</h2>
- 진입가는 관찰 기준 가격으로 설명한다.
- 손절가, 1차 익절, 2차 익절, 추적 손절의 역할을 설명한다.
- 최소 보유일, 권장 보유일, 최대 보유일을 설명한다.
- 조건 미충족 시 매수를 피해야 하는 기준을 설명한다.

<h2>6. 리스크 체크</h2>
- 손절폭, ATR 비율, 갭 상승, 윗꼬리, 과열 가능성을 설명한다.
- 조건이 훼손될 경우 제외해야 한다고 설명한다.

<h2>7. 오늘의 한마디</h2>
- 과장 없이 2~3문단으로 정리한다.

맨 하단에 항목 번호나 제목 없이 아래 문구를 빨간 글씨 문단으로 반드시 포함한다.
<p style="color:#d93025;">본 리포트는 자동화된 정량 조건을 바탕으로 작성된 참고용 분석 자료입니다. 특정 종목의 매수 또는 매도를 권유하는 투자 자문이 아니며, 모든 투자 판단과 책임은 투자자 본인에게 있습니다. 주식 투자는 원금 손실 가능성이 있습니다.</p>

추가 규칙:
- "무조건", "확실히", "급등", "대박", "보장" 같은 표현은 사용하지 않는다.
- "매수해야 한다" 대신 "관찰할 수 있다", "조건 충족 여부를 확인할 필요가 있다"라고 표현한다.
- 전문용어는 반드시 쉬운 해설을 함께 붙인다.
- 한자는 절대 사용하지 않는다.
- 입력 데이터의 영문 필드명이나 영문 사유 코드를 본문에 그대로 쓰지 않는다. 예: "Tenkan > Kijun", "Ichimoku cross", "BB expanding", "MA20 rising" 같은 표현은 절대 쓰지 말고 한국어 설명으로 바꿔 쓴다.
- 전체 리포트는 HTML fragment만 출력한다.
""".strip()

BLOG_STYLE_RULES = """
- 문체는 주식 초보자도 이해할 수 있게 쉽게 쓴다.
- 어려운 지표명보다 "그래서 지금 어떤 상태인지"를 먼저 설명한다.
- 한 문장은 가능하면 40자 안팎으로 짧게 쓴다.
- 숫자는 단순 나열하지 말고 "좋은 신호인지", "주의할 신호인지", "기다려야 하는 신호인지"로 풀어서 설명한다.
- RSI, ATR, 일목균형표, 볼린저 밴드, 상대강도 같은 용어는 단독으로 던지지 말고 반드시 쉬운 해석을 붙인다.
- "전환선", "기준선", "상대강도", "괴리", "변동성" 같은 말은 처음 나올 때 쉬운 말로 바꿔 설명한다.
- 문장 예시는 "단기 흐름은 살아 있지만, 가격이 이미 많이 올라 추격 매수는 조심할 구간입니다."처럼 쓴다.
- 손절과 익절은 "틀렸을 때 어디서 빠질지", "맞았을 때 어디서 나눠 팔지"라는 쉬운 표현으로 설명한다.
""".strip()

REPORT_STYLE_RULES = """
- 문체는 전문적이지만 일반 투자자도 이해할 수 있게 쓴다.
- 지표와 가격 기준을 명확히 쓰고, 해석은 과장 없이 차분하게 덧붙인다.
- 숫자는 생략하지 말고 리포트 판단 근거로 활용한다.
- 전문용어가 나오면 처음 등장하는 문단에서 괄호로 쉬운 설명을 붙인다.
""".strip()


async def generate_daily_signal_report(signals: list[dict], trade_date: date) -> str | None:
    result = await generate_daily_signal_report_result(signals, trade_date, report_type="daily")
    return result.get("report") if result.get("ok") else None


async def generate_daily_signal_report_result(signals: list[dict], trade_date: date, report_type: str = "daily") -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        message = "OPENAI_API_KEY is not configured"
        logger.info("AI report skipped: %s", message)
        return {"ok": False, "stage": "openai_config", "error": message, "report": None}
    if not signals:
        return {"ok": False, "stage": "input", "error": "No signals provided", "report": None}

    base_type = base_report_type(report_type)
    top_n = 1 if base_type == "signal" else max(1, min(int(settings.ai_report_top_n or 3), len(signals)))
    prompt = build_report_prompt(signals[:top_n], trade_date, report_type=report_type)
    payload = {
        "model": settings.ai_report_model,
        "instructions": report_instructions(report_type),
        "input": prompt,
        "max_output_tokens": 12000,
    }

    try:
        timeout = httpx.Timeout(240, connect=20)
        async with httpx.AsyncClient(timeout=timeout) as client:
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
            incomplete_error = get_incomplete_response_error(data)
            if incomplete_error:
                return {
                    "ok": False,
                    "stage": "openai_incomplete",
                    "error": incomplete_error,
                    "report": None,
                }
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
    cleaned = strip_code_fence(text) if text else ""
    if not cleaned:
        return {"ok": False, "stage": "openai", "error": "OpenAI response did not contain output text", "report": None}
    if not cleaned.endswith("</article>"):
        return {
            "ok": False,
            "stage": "openai_incomplete",
            "error": "OpenAI response did not end with </article>. Report was not saved because the output may be truncated.",
            "report": None,
        }
    return {"ok": True, "stage": "openai", "error": None, "report": clean_html_report(cleaned)}


def get_incomplete_response_error(data: dict) -> str | None:
    status = data.get("status")
    if status != "incomplete":
        return None
    details = data.get("incomplete_details") if isinstance(data.get("incomplete_details"), dict) else {}
    reason = details.get("reason") or "unknown"
    return f"OpenAI response incomplete: {reason}. Report was not saved because the output may be truncated."


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


def clean_html_report(text: str) -> str:
    stripped = strip_code_fence(text)
    stripped = replace_disallowed_hanja(stripped)
    stripped = ensure_investment_notice(stripped)
    return stripped


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def ensure_investment_notice(html: str) -> str:
    if INVESTMENT_NOTICE_TEXT in html:
        return html
    if html.endswith("</article>"):
        return html.removesuffix("</article>").rstrip() + f"\n\n{INVESTMENT_NOTICE_HTML}\n</article>"
    return html.rstrip() + f"\n\n{INVESTMENT_NOTICE_HTML}"


def replace_disallowed_hanja(html: str) -> str:
    cleaned = html
    for hanja, korean in HANJA_REPLACEMENTS.items():
        cleaned = cleaned.replace(hanja, korean)
    return cleaned


async def send_daily_signal_report(signals: list[dict], trade_date: date) -> int:
    return int((await queue_daily_ai_reports(signals, trade_date))["queued"])


async def queue_daily_ai_reports(signals: list[dict], trade_date: date) -> dict:
    if not signals:
        return {"queued": 0, "daily_report_id": None, "individual_reports": 0}

    settings = get_settings()
    top_n = max(1, min(int(settings.ai_report_top_n or 3), len(signals)))
    queued = 0
    daily = await queue_ai_report(signals, trade_date, report_type="daily")
    if daily["queued"]:
        queued += 1

    for signal in signals[:top_n]:
        result = await queue_ai_report(
            [signal],
            trade_date,
            report_type="signal",
            code=signal.get("Code"),
            name=signal.get("Name"),
        )
        if result["queued"]:
            queued += 1

    logger.warning("AI report queue completed: trade_date=%s queued=%s top_n=%s", trade_date, queued, top_n)
    return {"queued": queued, "daily_report_id": daily.get("report_id"), "individual_reports": top_n}


async def send_daily_signal_report_result(signals: list[dict], trade_date: date) -> dict:
    report_result = await generate_daily_signal_report_result(signals, trade_date, report_type="daily")
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
    report_result = await generate_daily_signal_report_result(signals, trade_date, report_type=report_type)
    if not report_result["ok"]:
        return {"saved": False, "stage": report_result["stage"], "error": report_result["error"], "report_id": None}

    html = report_result["report"]
    base_type = base_report_type(report_type)
    style_name = "블로그 글" if report_style(report_type) == "blog" else "AI 리포트"
    title_name = name or ("상위 시그널" if base_type == "daily" else "개별 종목")
    title = f"{trade_date.isoformat()} {title_name} {style_name}"
    rows = await SupabaseRest().upsert(
        "ai_reports",
        {
            "trade_date": trade_date.isoformat(),
            "report_type": report_type,
            "code": code or "ALL",
            "name": name,
            "title": title,
            "status": "completed",
            "markdown": "",
            "html": html,
            "error": None,
            "raw": {
                "signals_count": len(signals),
                "model": get_settings().ai_report_model,
                "codes": [signal.get("Code") for signal in signals],
                "content_format": "html",
            },
            "finished_at": now_iso(),
        },
        on_conflict="trade_date,report_type,code",
    )
    row = rows[0] if rows else {}
    return {"saved": True, "stage": "db", "error": None, "report_id": row.get("id"), "title": row.get("title")}


async def queue_ai_report(
    signals: list[dict],
    trade_date: date,
    *,
    report_type: str,
    code: str | None = None,
    name: str | None = None,
) -> dict:
    base_type = base_report_type(report_type)
    style_name = "블로그 글" if report_style(report_type) == "blog" else "AI 리포트"
    title_name = name or ("상위 시그널" if base_type == "daily" else "개별 종목")
    title = f"{trade_date.isoformat()} {title_name} {style_name}"
    rows = await SupabaseRest().upsert(
        "ai_reports",
        {
            "trade_date": trade_date.isoformat(),
            "report_type": report_type,
            "code": code or "ALL",
            "name": name,
            "title": title,
            "status": "queued",
            "markdown": "",
            "html": "",
            "error": None,
            "started_at": None,
            "finished_at": None,
            "raw": {
                "signals": signals,
                "signals_count": len(signals),
                "model": get_settings().ai_report_model,
                "codes": [signal.get("Code") for signal in signals],
                "content_format": "html",
            },
        },
        on_conflict="trade_date,report_type,code",
    )
    row = rows[0] if rows else {}
    return {"queued": True, "stage": "queued", "error": None, "report_id": row.get("id"), "title": row.get("title")}


async def process_queued_ai_reports(limit: int = 1) -> list[dict]:
    rows = await SupabaseRest().select(
        "ai_reports",
        filters={"status": "eq.queued"},
        order="created_at.asc",
        limit=limit,
    )
    results: list[dict] = []
    for row in rows:
        results.append(await process_ai_report_row(row))
    return results


async def process_ai_report_row(row: dict) -> dict:
    rest = SupabaseRest()
    report_id = row["id"]
    started_at = now_iso()
    claimed = await rest.patch(
        "ai_reports",
        filters={"id": f"eq.{report_id}", "status": "eq.queued"},
        payload={"status": "running", "started_at": started_at, "error": None},
    )
    if not claimed:
        return {"id": report_id, "status": "skipped", "error": "Already claimed"}

    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    signals = raw.get("signals") if isinstance(raw.get("signals"), list) else []
    trade_date = date.fromisoformat(row["trade_date"])
    report_type = row.get("report_type") or "daily"
    report_result = await generate_daily_signal_report_result(signals, trade_date, report_type=report_type)
    if not report_result["ok"]:
        await rest.patch(
            "ai_reports",
            filters={"id": f"eq.{report_id}"},
            payload={
                "status": "failed",
                "error": report_result["error"],
                "finished_at": now_iso(),
            },
        )
        return {"id": report_id, "status": "failed", "error": report_result["error"]}

    await rest.patch(
        "ai_reports",
        filters={"id": f"eq.{report_id}"},
        payload={
            "status": "completed",
            "markdown": "",
            "html": report_result["report"],
            "error": None,
            "finished_at": now_iso(),
        },
    )
    return {"id": report_id, "status": "completed", "error": None}


def now_iso() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).isoformat()


def base_report_type(report_type: str) -> str:
    return "signal" if report_type.startswith("signal") else "daily"


def report_style(report_type: str) -> str:
    return "blog" if report_type.endswith("_blog") else "report"


def stored_report_type(report_type: str, style: str = "report") -> str:
    base = base_report_type(report_type)
    return f"{base}_blog" if style == "blog" else base


def report_instructions(report_type: str) -> str:
    base = SIGNAL_REPORT_INSTRUCTIONS if base_report_type(report_type) == "signal" else REPORT_INSTRUCTIONS
    style_rules = BLOG_STYLE_RULES if report_style(report_type) == "blog" else REPORT_STYLE_RULES
    return f"{base}\n\n리포트 스타일 규칙:\n{style_rules}"


def build_report_prompt(signals: list[dict], trade_date: date, report_type: str = "daily") -> str:
    selected = [select_report_input_fields(signal, index) for index, signal in enumerate(signals, start=1)]
    trade_date_text = trade_date.isoformat()
    title_line = build_report_title_line(selected, trade_date_text, report_type)
    sections = [
        f"작성일: {trade_date_text}",
        title_line,
        "아래 데이터는 해당 거래일의 스윙봇 상위 점수 종목에서 리포트 작성에 필요한 필드만 선별한 값이다.",
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
        "- reasons_ko: 스캐너가 점수를 부여한 핵심 근거를 한국어로 번역한 값",
        "",
    ]
    for item in selected:
        sections.append(format_signal_for_prompt(item))
    return "\n".join(sections)


def build_report_title_line(signals: list[dict], trade_date_text: str, report_type: str) -> str:
    if base_report_type(report_type) == "signal" and signals:
        name = signals[0].get("name") or "개별 종목"
        code = signals[0].get("code") or ""
        return f"리포트 제목은 반드시 <h1>{trade_date_text} {name}({code}) 스윙 분석 리포트</h1>로 작성한다."
    return f"리포트 제목은 반드시 <h1>{trade_date_text} 스윙 후보 리포트</h1>로 작성한다."


def select_report_input_fields(signal: dict, rank: int) -> dict:
    code = signal.get("Code")
    company_profile = enrich_company_profile(code, normalize_company_profile(signal.get("CompanyProfile")))
    return {
        "rank": rank,
        "name": signal.get("Name"),
        "code": code,
        "company_profile": normalize_company_profile(company_profile),
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
        "market_filter": translate_market_filter(signal.get("MarketFilter"), signal.get("MarketFilterPassed")),
        "reasons_ko": translate_signal_reasons(signal.get("Reasons")),
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


def translate_market_filter(value: object, passed: object = None) -> str:
    label = "코스피 지수가 5일 이동평균선 위에 있는지 확인하는 시장 필터"
    if passed is True:
        return f"{label}: 통과"
    if passed is False:
        return f"{label}: 미통과"
    return label if value else "제공 데이터 기준 확인 불가"


def translate_signal_reasons(reasons: object) -> str:
    value = str(reasons or "")
    if not value:
        return "제공 데이터 기준 확인 불가"
    reason_map = {
        "MA20 > MA60": "20일 이동평균선이 60일 이동평균선 위에 있음",
        "MA20 rising": "20일 이동평균선이 상승 중",
        "Tenkan > Kijun": "일목균형표 전환선이 기준선 위에 있음",
        "Ichimoku cross": "최근 전환선이 기준선을 상향 돌파",
        "Bullish close": "전일 대비 상승 마감",
        "Near Kijun": "현재가가 일목 기준선 근처에 있음",
        "RSI rebound zone": "RSI가 반등 초입으로 볼 수 있는 구간",
        "5D momentum ok": "최근 5거래일 흐름이 과도하지 않음",
        "20D momentum ok": "최근 20거래일 상승 흐름이 유효 범위 안에 있음",
        "BB expanding": "볼린저 밴드 폭이 확대 중",
        "Enough trading value": "20일 평균 거래대금이 기준 이상",
        "Volume spike": "거래량이 최근 평균보다 증가",
        "Strong volume spike": "거래량이 강하게 증가",
        "KOSPI above MA5": "코스피 지수가 5일 이동평균선 위에 있음",
        "KOSPI_TOP1000": "KOSPI1000 핵심군 해당",
        "KOSPI_TOP500": "KOSPI1000 핵심군 해당",
        "KOSDAQ150": "KOSDAQ150 핵심군 해당",
        "Market relative strength": "시장 대비 20일 상대강도 우위",
        "Trading value spike": "거래대금이 최근 평균보다 증가",
        "ATR in swing range": "ATR 변동성이 스윙 매매 가능 범위",
        "Bull cloud pullback support": "양운 위 눌림목 지지 패턴",
        "Bear cloud breakout pressure": "음운 돌파 직전 수급 패턴",
        "Gap up penalty": "갭 상승 부담 감점",
        "Upper shadow penalty": "윗꼬리 부담 감점",
        "ATR too high": "ATR 변동성 과다 감점",
    }
    translated = [reason_map.get(item.strip(), item.strip()) for item in value.split(",") if item.strip()]
    return ", ".join(translated) if translated else "제공 데이터 기준 확인 불가"


def normalize_company_profile(value: object) -> dict:
    profile = value if isinstance(value, dict) else {}
    return {
        "market": profile.get("market") or "제공 데이터 기준 확인 불가",
        "sector": profile.get("sector") or "제공 데이터 기준 확인 불가",
        "industry": profile.get("industry") or "제공 데이터 기준 확인 불가",
        "business_summary": profile.get("business_summary") or "제공 데이터 기준 확인 불가",
        "market_cap": format_market_cap(profile.get("market_cap")),
    }


def format_market_cap(value: object) -> str:
    if value in {None, "", "제공 데이터 기준 확인 불가"}:
        return "제공 데이터 기준 확인 불가"
    try:
        numeric = int(float(str(value).replace(",", "").replace("원", "").strip()))
    except (TypeError, ValueError):
        return str(value)
    if numeric <= 0:
        return "제공 데이터 기준 확인 불가"
    trillion = numeric // 1_000_000_000_000
    hundred_million = round((numeric % 1_000_000_000_000) / 100_000_000)
    if trillion and hundred_million:
        return f"{trillion}조 {hundred_million:,}억 원"
    if trillion:
        return f"{trillion}조 원"
    return f"{round(numeric / 100_000_000):,}억 원"


def extract_output_text(data: dict) -> str:
    chunks: list[str] = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks)
