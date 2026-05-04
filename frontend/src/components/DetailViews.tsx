import type { AiReportStatus } from "../api";
import type { DetailSelection } from "../types";
import {
  asRecord,
  buildSignalAnalysis,
  buildStopLossExplanation,
  buildTakeProfitExplanation,
  formatCell,
  formatDateTime,
  formatMarketCap,
  formatOrderPolicy,
  formatPct,
  formatPercentFromEntry,
  formatPlanPct,
  hasCompletedReport,
  isCoreUniverseSignal,
  isPassed,
  translateBacktestStatus,
  translateCloudType,
  translateCoreUniverse,
  translateReason,
  translateReasons,
} from "../utils/dashboard";
import { DetailSection, MiniTable } from "./DashboardParts";

export function DetailOverlay({
  detail,
  isScanAdmin,
  pending,
  onSendSignalReport,
  onSendSignalBlogReport,
  onDownloadSignalReport,
  onDownloadSignalBlogReport,
  onDownloadReportStatus,
  onDownloadBacktestTrades,
  onForceLiquidatePosition,
  aiReports,
  onClose,
}: {
  detail: DetailSelection;
  isScanAdmin: boolean;
  pending: string | null;
  onSendSignalReport: (row: Record<string, unknown>) => void;
  onSendSignalBlogReport: (row: Record<string, unknown>) => void;
  onDownloadSignalReport: (row: Record<string, unknown>) => void;
  onDownloadSignalBlogReport: (row: Record<string, unknown>) => void;
  onDownloadReportStatus: (row: Record<string, unknown>) => void;
  onDownloadBacktestTrades: (row: Record<string, unknown>) => void;
  onForceLiquidatePosition: (row: Record<string, unknown>) => void;
  aiReports: AiReportStatus[];
  onClose: () => void;
}) {
  const detailLabel =
    detail.kind === "signal" ? "시그널 상세"
      : detail.kind === "log" ? "매매 로그 상세"
        : detail.kind === "decision" ? "매수 제외 상세"
          : detail.kind === "watcher" ? "와쳐 실행 상세"
            : detail.kind === "account" ? "계좌 상세"
              : detail.kind === "report" ? "AI 리포트 상세"
                : detail.kind === "backtest" ? "백테스트 상세"
            : "포지션 상세";
  return (
    <div className="overlay-backdrop" onClick={onClose}>
      <aside className="detail-popover" onClick={(event) => event.stopPropagation()}>
        <div className="detail-head">
          <div>
            <span>{detailLabel}</span>
            <h2>{detail.title}</h2>
          </div>
          <button className="ghost small" onClick={onClose}>닫기</button>
        </div>
        {detail.kind === "signal" && (
          <SignalDetail
            row={detail.row}
            isScanAdmin={isScanAdmin}
            pending={pending === "signalReport"}
            downloadPending={pending === "signalReportDownload"}
            reportCompleted={hasCompletedReport(aiReports, "signal", String(detail.row.code || "").padStart(6, "0"))}
            blogReportCompleted={hasCompletedReport(aiReports, "signal_blog", String(detail.row.code || "").padStart(6, "0"))}
            onSendReport={() => onSendSignalReport(detail.row)}
            onSendBlogReport={() => onSendSignalBlogReport(detail.row)}
            onDownloadReport={() => onDownloadSignalReport(detail.row)}
            onDownloadBlogReport={() => onDownloadSignalBlogReport(detail.row)}
          />
        )}
        {detail.kind === "log" && <TradeLogDetail row={detail.row} />}
        {detail.kind === "position" && (
          <PositionDetail
            row={detail.row}
            pending={pending === "forceLiquidate"}
            onForceLiquidate={() => onForceLiquidatePosition(detail.row)}
          />
        )}
        {detail.kind === "account" && <AccountDetail row={detail.row} />}
        {detail.kind === "decision" && <DecisionDetail row={detail.row} />}
        {detail.kind === "watcher" && <WatcherRunDetail row={detail.row} />}
        {detail.kind === "backtest" && (
          <BacktestRunDetail
            row={detail.row}
            pending={pending === "backtestExport"}
            onDownloadTrades={() => onDownloadBacktestTrades(detail.row)}
          />
        )}
        {detail.kind === "report" && (
          <ReportStatusDetail
            row={detail.row}
            pending={pending === "reportDownload" || pending === "signalReportDownload"}
            onDownload={() => onDownloadReportStatus(detail.row)}
          />
        )}
      </aside>
    </div>
  );
}

export function SignalDetail({
  row,
  isScanAdmin,
  pending,
  downloadPending,
  reportCompleted,
  blogReportCompleted,
  onSendReport,
  onSendBlogReport,
  onDownloadReport,
  onDownloadBlogReport,
}: {
  row: Record<string, unknown>;
  isScanAdmin: boolean;
  pending: boolean;
  downloadPending: boolean;
  reportCompleted: boolean;
  blogReportCompleted: boolean;
  onSendReport: () => void;
  onSendBlogReport: () => void;
  onDownloadReport: () => void;
  onDownloadBlogReport: () => void;
}) {
  const raw = asRecord(row.raw);
  const companyProfile = asRecord(raw.CompanyProfile);
  const code = String(row.code || "").padStart(6, "0");
  const naverUrl = `https://stock.naver.com/domestic/stock/${code}/price`;
  const analysis = buildSignalAnalysis(row);
  return (
    <div className="detail-grid">
      <a className="naver-link" href={naverUrl} target="_blank" rel="noreferrer">
        네이버 증권으로 가기
      </a>
      {isScanAdmin && (
        <>
          <button className="primary detail-action" type="button" disabled={pending} onClick={onSendReport}>
            {pending ? "개별 리포트 생성 요청 중..." : "이 기업 AI 리포트 생성 요청"}
          </button>
          <button className="detail-action" type="button" disabled={pending} onClick={onSendBlogReport}>
            {pending ? "블로그 글 생성 요청 중..." : "이 기업 블로그 글 생성 요청"}
          </button>
          {reportCompleted && (
            <button className="detail-action" type="button" disabled={downloadPending} onClick={onDownloadReport}>
              {downloadPending ? "리포트 확인 중..." : "개별 리포트 다운로드"}
            </button>
          )}
          {blogReportCompleted && (
            <button className="detail-action" type="button" disabled={downloadPending} onClick={onDownloadBlogReport}>
              {downloadPending ? "블로그 글 확인 중..." : "개별 블로그 글 다운로드"}
            </button>
          )}
        </>
      )}
      <section className="signal-analysis-card">
        <div className="signal-analysis-head">
          <span className={`analysis-badge ${analysis.suitability.tone}`}>
            자동매매 적합도 {analysis.suitability.label} · {analysis.suitability.score}점
          </span>
          <p>{analysis.suitability.reason}</p>
        </div>
        <h3>한 줄 요약</h3>
        <p>{analysis.summary}</p>
      </section>
      <section className="signal-analysis-grid">
        <AnalysisBlock title="선정 근거" items={analysis.selectionReasons} />
        <AnalysisBlock title="매수 관찰 포인트" items={analysis.entryGuide} />
        <AnalysisBlock title="손절/익절 운영" items={analysis.exitGuide} />
      </section>
      <section className="signal-risk-grid">
        {analysis.riskChecks.map((item) => (
          <div className={`risk-card ${item.tone}`} key={item.label}>
            <strong>{item.label}</strong>
            <p>{item.text}</p>
          </div>
        ))}
      </section>
      <DetailSection title="기업 개요" items={[
        ["시장", companyProfile.market || raw.Universe],
        ["섹터", companyProfile.sector],
        ["업종", companyProfile.industry],
        ["사업 요약", companyProfile.business_summary],
        ["시가총액", formatMarketCap(companyProfile.market_cap)],
      ]} />
      <DetailSection title="매매 계획" items={[
        ["매수가", row.entry],
        ["손절가", row.stop_loss],
        ["손절률", formatPercentFromEntry(row.stop_loss, row.entry)],
        ["1차 익절가", row.take_profit_1],
        ["1차 익절률", formatPercentFromEntry(row.take_profit_1, row.entry)],
        ["2차 익절가", row.take_profit_2],
        ["2차 익절률", formatPercentFromEntry(row.take_profit_2, row.entry)],
        ["추적 손절가", row.trailing_stop],
        ["추적 손절률", formatPercentFromEntry(row.trailing_stop, row.entry)],
        ["손절 산출 근거", buildStopLossExplanation(row, raw)],
        ["익절 산출 근거", buildTakeProfitExplanation(row)],
        ["권장 보유", `${formatCell(raw.HoldMinDays)}-${formatCell(raw.HoldPreferredDays)}일`],
        ["최대 보유", `${formatCell(raw.HoldMaxDays)}일`],
        ["매입 허용 시간", "14:30-15:20"],
      ]} />
      <DetailSection title="진입 근거" items={[
        ["점수", row.score],
        ["자동매매지수", analysis.suitability.score],
        ["사유", translateReasons(raw.Reasons)],
        ["RSI14", raw.RSI14],
        ["일목 전환선", raw.Tenkan],
        ["일목 기준선", raw.Kijun],
        ["구름 상단", raw.CloudUpper],
        ["구름 하단", raw.CloudLower],
        ["구름 상태", translateCloudType(raw.CloudType)],
        ["구름 상단 이격", `${formatCell(raw["DistanceToCloudUpper(%)"])}%`],
        ["패턴", raw.SignalPatterns],
        ["일목 돌파 후 경과일", raw.DaysAfterIchimokuCross],
        ["BB 폭", raw["BBWidth(%)"]],
        ["BB 확장", raw["BBExpansion(%)"]],
        ["거래량 배율", raw.VolumeSpikeRatio],
        ["거래대금 배율", raw.TradingValueSpikeRatio],
        ["상대강도 20D", `${formatCell(raw["RelativeStrength_20D(%)"])}%`],
      ]} />
      <DetailSection title="리스크/시장" items={[
        ["손절폭", `${formatCell(raw["StopPct"] ?? raw.StopPct)}%`],
        ["리스크", `${formatCell(raw.RiskPct)}%`],
        ["ATR", raw.ATR14],
        ["ATR 비율", `${formatCell(raw["ATR(%)"])}%`],
        ["갭", `${formatCell(raw["Gap(%)"])}%`],
        ["윗꼬리 비율", raw.UpperShadowRatio],
        ["20일 거래대금", raw.TradingValue20D],
        ["시장 필터", `${formatCell(raw.MarketFilter)} / ${isPassed(raw.MarketFilterPassed) ? "통과" : "미통과"}`],
        ["유니버스", raw.Universe],
        ["핵심군", isCoreUniverseSignal(raw) ? translateCoreUniverse(raw.CoreUniverseType) : "해당 없음"],
        ["5일 수익률", `${formatCell(raw["Ret_5D(%)"])}%`],
        ["20일 수익률", `${formatCell(raw["Ret_20D(%)"])}%`],
        ["시장 20일 수익률", `${formatCell(raw["MarketRet_20D(%)"])}%`],
      ]} />
    </div>
  );
}

function AnalysisBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="analysis-block">
      <h3>{title}</h3>
      <ul>
        {items.filter(Boolean).map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}
      </ul>
    </div>
  );
}

export function TradeLogDetail({ row }: { row: Record<string, unknown> }) {
  const raw = asRecord(row.raw);
  const exitPlan = asRecord(raw.exit_plan);
  const quote = asRecord(raw.quote);
  const realtime = asRecord(raw.realtime);
  return (
    <div className="detail-grid">
      <DetailSection title="체결 정보" items={[
        ["구분", row.action_ko],
        ["종목", `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["수량", row.qty],
        ["가격", row.price],
        ["시간", formatDateTime(row.created_at)],
        ["사유", row.reason_ko],
        ["원본 코드", raw.reason_code],
      ]} />
      <DetailSection title="언제 팔 건지" items={[
        ["매수가", exitPlan.entry_price],
        ["손절", exitPlan.stop_loss],
        ["손절률", formatPlanPct(exitPlan.stop_loss_pct) || formatPercentFromEntry(exitPlan.stop_loss, exitPlan.entry_price)],
        ["1차 익절", exitPlan.take_profit_1],
        ["1차 익절률", formatPlanPct(exitPlan.take_profit_1_pct) || formatPercentFromEntry(exitPlan.take_profit_1, exitPlan.entry_price)],
        ["2차 익절", exitPlan.take_profit_2],
        ["2차 익절률", formatPlanPct(exitPlan.take_profit_2_pct) || formatPercentFromEntry(exitPlan.take_profit_2, exitPlan.entry_price)],
        ["추적 손절", exitPlan.trailing_stop],
        ["추적 손절률", formatPlanPct(exitPlan.trailing_stop_pct) || formatPercentFromEntry(exitPlan.trailing_stop, exitPlan.entry_price)],
        ["권장 보유", `${formatCell(exitPlan.hold_min_days)}-${formatCell(exitPlan.hold_preferred_days)}일`],
        ["최대 보유", `${formatCell(exitPlan.hold_max_days)}일`],
        ["매입 시간", exitPlan.planned_entry_window || "14:30-15:20"],
        ["관리 시간", exitPlan.planned_manage_window || "09:00-15:20"],
      ]} />
      <DetailSection title="장중 확인값" items={[
        ["현재가", quote.current_price],
        ["당일 고가", quote.day_high],
        ["당일 저가", quote.day_low],
        ["누적 거래량", quote.accumulated_volume],
        ["VI 발동", Number(quote.vi_active || 0) > 0 ? "예" : "아니오"],
        ["주문 정책", formatOrderPolicy(raw.order_policy)],
        ["주문 응답", raw.order ? "저장됨" : "-"],
      ]} />
      <DetailSection title="실시간 호가/체결" items={[
        ["체결강도", realtime.strength],
        ["매수/매도 잔량비", realtime.bid_ask_ratio],
        ["호가 스프레드", realtime.spread_pct],
        ["샘플 수", realtime.samples],
        ["판단", realtime.reason],
      ]} />
    </div>
  );
}

export function AccountDetail({ row }: { row: Record<string, unknown> }) {
  const rowType = String(row.row_type || "");
  const holdings = Array.isArray(row.holdings) ? row.holdings : [];
  if (rowType === "summary") {
    return (
      <div className="detail-grid">
        <DetailSection title="계좌 요약" items={[
          ["계좌", row.account],
          ["예수금", `${formatCell(row.cash)}원`],
          ["총평가", `${formatCell(row.total_equity)}원`],
          ["보유 종목 수", `${formatCell(row.holdings_count)}종목`],
        ]} />
        <DetailSection title="보유 종목 요약" items={[
          ["보유 종목", holdings.length > 0 ? holdings.map((item) => {
            const holding = asRecord(item);
            return `${formatCell(holding.name || holding.code)} ${formatCell(holding.qty)}주`;
          }).join(" / ") : "보유 종목 없음"],
        ]} />
      </div>
    );
  }

  const avgPrice = Number(row.avg_price || 0);
  const currentPrice = Number(row.current_price || 0);
  const qty = Number(row.qty || 0);
  const evaluationAmount = Number(row.evaluation_amount || currentPrice * qty || 0);
  const investedAmount = avgPrice * qty;
  return (
    <div className="detail-grid">
      <DetailSection title="보유 종목" items={[
        ["계좌", row.account],
        ["종목", `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["보유 수량", `${formatCell(row.qty)}주`],
        ["평균 매입가", `${formatCell(row.avg_price)}원`],
        ["현재가", `${formatCell(row.current_price)}원`],
        ["평가금액", `${formatCell(evaluationAmount)}원`],
        ["매입금액", `${formatCell(investedAmount)}원`],
      ]} />
      <DetailSection title="손익" items={[
        ["평가손익", `${formatCell(row.profit_loss)}원`],
        ["손익률", `${formatCell(row.profit_loss_rate)}%`],
        ["주당 손익", `${formatCell(currentPrice - avgPrice)}원`],
      ]} />
      <DetailSection title="확인 포인트" items={[
        ["자동매매 DB 포지션", "KIS 계좌 잔고 기준 정보입니다. 자동매매 포지션 상세는 포지션 메뉴에서 확인합니다."],
        ["가격 기준", "KIS 계좌 조회 시점의 현재가/평가금액 기준입니다."],
      ]} />
    </div>
  );
}

export function ReportStatusDetail({
  row,
  pending,
  onDownload,
}: {
  row: Record<string, unknown>;
  pending: boolean;
  onDownload: () => void;
}) {
  const completed = row.status === "completed";
  return (
    <div className="detail-grid">
      {completed && (
        <button className="primary detail-action" type="button" disabled={pending} onClick={onDownload}>
          {pending ? "다운로드 확인 중..." : "완료된 리포트 다운로드"}
        </button>
      )}
      <DetailSection title="리포트 상태" items={[
        ["종류", row.report_kind_ko],
        ["상태", row.status_ko],
        ["날짜", row.trade_date],
        ["종목", row.code === "ALL" ? "종합 리포트" : `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["제목", row.title],
        ["생성 요청", formatDateTime(row.created_at)],
        ["시작", formatDateTime(row.started_at)],
        ["완료", formatDateTime(row.finished_at)],
        ["오류", row.error],
      ]} />
      {!completed && (
        <DetailSection title="다운로드 안내" items={[
          ["상태", "완료된 리포트만 다운로드할 수 있습니다."],
        ]} />
      )}
    </div>
  );
}

export function PositionDetail({
  row,
  pending,
  onForceLiquidate,
}: {
  row: Record<string, unknown>;
  pending: boolean;
  onForceLiquidate: () => void;
}) {
  const raw = asRecord(row.raw);
  const isOpen = String(row.status || "").toUpperCase() === "OPEN" && Number(row.remaining_qty || 0) > 0;
  return (
    <div className="detail-grid">
      {isOpen && (
        <button className="danger detail-action" type="button" disabled={pending} onClick={onForceLiquidate}>
          {pending ? "강제 청산 주문 중..." : "이 종목 시장가 강제 청산"}
        </button>
      )}
      <DetailSection title="보유 정보" items={[
        ["종목", `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["매수일", row.entry_date],
        ["매수가", row.entry_price],
        ["총수량", row.qty],
        ["잔여수량", row.remaining_qty],
        ["상태", row.status],
      ]} />
      <DetailSection title="청산 계획" items={[
        ["손절", row.stop_loss],
        ["손절률", formatPercentFromEntry(row.stop_loss, row.entry_price)],
        ["1차 익절", row.take_profit_1],
        ["1차 익절률", formatPercentFromEntry(row.take_profit_1, row.entry_price)],
        ["2차 익절", row.take_profit_2],
        ["2차 익절률", formatPercentFromEntry(row.take_profit_2, row.entry_price)],
        ["추적 손절", row.trailing_stop],
        ["추적 손절률", formatPercentFromEntry(row.trailing_stop, row.entry_price)],
        ["최대 보유", `${formatCell(raw.HoldMaxDays)}일`],
        ["1차 익절 완료", row.take_profit_1_done ? "예" : "아니오"],
        ["2차 익절 완료", row.take_profit_2_done ? "예" : "아니오"],
      ]} />
    </div>
  );
}

export function DecisionDetail({ row }: { row: Record<string, unknown> }) {
  const raw = asRecord(row.raw);
  const quote = asRecord(raw.quote);
  const realtime = asRecord(raw.realtime);
  const sizing = asRecord(raw.sizing);
  const strategy = asRecord(raw.strategy);
  return (
    <div className="detail-grid">
      <DetailSection title="제외 판단" items={[
        ["종목", `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["판단일", row.decision_date],
        ["점수", row.score],
        ["현재가", row.price],
        ["제외 사유", row.reason],
        ["사유 코드", row.reason_code],
        ["기록 시간", formatDateTime(row.created_at)],
      ]} />
      <DetailSection title="장중 값" items={[
        ["현재가", quote.current_price],
        ["당일 고가", quote.day_high],
        ["당일 저가", quote.day_low],
        ["누적 거래량", quote.accumulated_volume],
        ["VI 발동", Number(quote.vi_active || 0) > 0 ? "예" : "아니오"],
        ["호가 기준", quote.price_source],
      ]} />
      <DetailSection title="실시간 호가/체결" items={[
        ["체결강도", realtime.strength],
        ["매수/매도 잔량비", realtime.bid_ask_ratio],
        ["호가 스프레드", realtime.spread_pct],
        ["샘플 수", realtime.samples],
        ["판단", realtime.reason],
      ]} />
      <DetailSection title="전략/수량 조건" items={[
        ["최소 점수", strategy.min_score],
        ["진입가 하단 배율", strategy.min_entry_discount],
        ["진입가 상단 배율", strategy.max_entry_premium],
        ["고점 이탈 허용", strategy.max_pullback_from_day_high],
        ["계산 수량", sizing.qty],
        ["주문 가능금액", sizing.available_cash],
        ["리스크 기준 수량", sizing.risk_qty],
      ]} />
    </div>
  );
}

export function WatcherRunDetail({ row }: { row: Record<string, unknown> }) {
  const raw = asRecord(row.raw);
  const strategy = asRecord(raw.strategy);
  const actions = Array.isArray(raw.actions) ? raw.actions : [];
  return (
    <div className="detail-grid">
      <DetailSection title="실행 요약" items={[
        ["실행 시간", row.created_at],
        ["계좌 구분", row.mode],
        ["주문 허용", row.orders_allowed_ko],
        ["매수 시간대", row.entry_window_open ? "열림" : "아님"],
        ["관리 시간대", row.manage_window_open ? "열림" : "아님"],
        ["스킵 사유", row.skip_reason_ko],
        ["실행 단계", raw.stage],
        ["오류", raw.error],
      ]} />
      <DetailSection title="매수 가능 상태" items={[
        ["예수금", row.cash],
        ["총평가금", row.total_equity],
        ["시그널 수", row.signals_count],
        ["DB 포지션", row.open_positions_count],
        ["KIS 보유종목", row.kis_holdings_count],
        ["미체결 주문", row.pending_orders_count],
        ["오늘 진입 종목", row.today_entry_count],
        ["오늘 미체결 매수", row.today_pending_buy_count],
        ["오늘 손절 차단 종목", raw.today_stopped_out_count],
        ["오늘 기준선 이탈 차단 종목", raw.today_kijun_exit_count],
        ["오늘 남은 신규 슬롯", row.remaining_daily_slots],
        ["하루 실현손실", raw.daily_realized_loss],
        ["하루 손실 한도금액", raw.daily_loss_limit_amount],
        ["미실현 손익", raw.unrealized_pnl],
        ["미실현 손실", raw.unrealized_loss],
        ["미실현 손실 한도금액", raw.unrealized_loss_limit_amount],
        ["코스피 당일 수익률", raw.market_intraday_return_pct === undefined || raw.market_intraday_return_pct === null ? "-" : formatPct(Number(raw.market_intraday_return_pct))],
        ["보유 가능 슬롯", row.available_slots],
        ["금액 기준 슬롯", row.affordable_slots],
        ["오늘 신규 가능 슬롯", row.daily_slots],
      ]} />
      <DetailSection title="실행 결과" items={[
        ["전체 액션", row.action_count],
        ["매수 주문", row.buy_order_count],
        ["매도 주문", row.sell_order_count],
        ["쿨다운 스킵", row.cooldown_skip_count],
        ["액션 상세", actions.map((item) => {
          const action = asRecord(item);
          return `${formatCell(action.action)} ${formatCell(action.name || action.code)} ${formatCell(action.qty)}주 @ ${formatCell(action.price)}`;
        }).join(" / ")],
      ]} />
      <DetailSection title="전략 설정" items={[
        ["최소 점수", strategy.min_score],
        ["최대 보유 종목", strategy.max_open_positions],
        ["하루 신규 매수", strategy.max_new_positions_per_day],
        ["종목당 비중", strategy.position_capital_pct],
        ["최소 주문금액", strategy.min_order_amount],
        ["하루 손실 제한", strategy.use_daily_loss_limit ? formatPct(Number(strategy.daily_loss_limit_pct || 0)) : "미사용"],
        ["미실현손실 제한", strategy.use_unrealized_loss_limit ? formatPct(Number(strategy.unrealized_loss_limit_pct || 0)) : "미사용"],
        ["시장 급락 차단", strategy.use_market_crash_filter ? formatPct(Number(strategy.market_crash_limit_pct || 0)) : "미사용"],
        ["세금/수수료율", formatPct(Number(strategy.commission_tax_pct || 0))],
        ["실시간 필터", strategy.use_realtime_liquidity_filter ? "사용" : "미사용"],
        ["당일 손절 재매수 금지", strategy.use_stoploss_reentry_block ? "사용" : "미사용"],
        ["기준선 이탈 재매수 금지", strategy.use_kijun_reentry_block ? "사용" : "미사용"],
        ["VI 매수 차단", strategy.use_vi_filter ? "사용" : "미사용"],
        ["최소 체결강도", strategy.min_realtime_strength],
        ["최소 매수/매도 잔량비", strategy.min_bid_ask_ratio],
        ["최대 호가 스프레드", strategy.max_realtime_spread_pct],
      ]} />
    </div>
  );
}

export function BacktestRunDetail({
  row,
  pending,
  onDownloadTrades,
}: {
  row: Record<string, unknown>;
  pending: boolean;
  onDownloadTrades: () => void;
}) {
  const progress = asRecord(row.progress);
  const result = asRecord(row.result);
  const trades = Array.isArray(result.trades) ? result.trades.map((item) => asRecord(item)) : [];
  const tradesByReturn = [...trades].sort((left, right) => Number(right.return_pct || 0) - Number(left.return_pct || 0));
  const topProfitTrades = tradesByReturn.slice(0, 5);
  const topLossTrades = [...tradesByReturn].reverse().slice(0, 5);
  const tested = result.signals_tested ?? progress.tested;
  const generated = result.generated_signals ?? progress.signals;
  const tradeRows = (items: Record<string, unknown>[]) => items.map((trade) => ({
    date: trade.trade_date,
    code: trade.code,
    name: trade.name,
    score: trade.score,
    entry: trade.entry,
    exit: trade.exit_price,
    return_pct: trade.return_pct === undefined ? "-" : `${formatCell(trade.return_pct)}%`,
    hold_days: trade.hold_days,
    reason: translateReason(trade.exit_reason),
    tp: `${trade.tp1_done ? "1차Y" : "1차N"} / ${trade.tp2_done ? "2차Y" : "2차N"}`,
    remain: trade.remaining_qty_ratio,
  }));
  const tradeColumns = ["date", "code", "name", "score", "entry", "exit", "return_pct", "hold_days", "reason", "tp", "remain"];
  return (
    <div className="detail-grid">
      <button className="primary detail-action" type="button" disabled={pending || row.status !== "completed"} onClick={onDownloadTrades}>
        {pending ? "CSV 생성 중..." : "전체 거래 엑셀용 CSV 다운로드"}
      </button>
      <DetailSection title="실행 정보" items={[
        ["실행 ID", row.run_id || row.job_id],
        ["상태", translateBacktestStatus(row.status)],
        ["기간", `${formatCell(row.start_date)} - ${formatCell(row.end_date)}`],
        ["검증 범위", `${formatCell(row.days)}일`],
        ["최대 검증 시그널", row.max_signals],
        ["전략", `${formatCell(row.strategy_key)} / ${formatCell(row.strategy_version)}`],
        ["유니버스", row.universe_scope],
        ["생성 시간", formatDateTime(row.created_at)],
        ["완료 시간", formatDateTime(row.finished_at || row.completed_at)],
        ["오류", row.error],
      ]} />
      <DetailSection title="진행 상태" items={[
        ["처리 종목", `${formatCell(progress.processed)}/${formatCell(progress.total)}`],
        ["누적 후보", generated],
        ["검증 거래", tested],
        ["스킵", progress.skipped],
      ]} />
      <DetailSection title="성과 요약" items={[
        ["승률", result.win_rate === undefined ? "-" : `${formatCell(result.win_rate)}%`],
        ["평균 수익률", result.avg_return_pct === undefined ? "-" : `${formatCell(result.avg_return_pct)}%`],
        ["평균 수익", result.avg_win_pct === undefined ? "-" : `${formatCell(result.avg_win_pct)}%`],
        ["평균 손실", result.avg_loss_pct === undefined ? "-" : `${formatCell(result.avg_loss_pct)}%`],
        ["최고 수익", result.best_return_pct === undefined ? "-" : `${formatCell(result.best_return_pct)}%`],
        ["최악 손실", result.worst_return_pct === undefined ? "-" : `${formatCell(result.worst_return_pct)}%`],
        ["평균 보유일", result.avg_hold_days === undefined ? "-" : `${formatCell(result.avg_hold_days)}일`],
        ["승/패", `${formatCell(result.win_count)} / ${formatCell(result.loss_count)}`],
      ]} />
      <section className="detail-section">
        <h3>수익률 TOP 5</h3>
        <MiniTable
          rows={tradeRows(topProfitTrades)}
          columns={tradeColumns}
          emptyLabel="수익 거래 없음"
        />
      </section>
      <section className="detail-section">
        <h3>최악 수익률 TOP 5</h3>
        <MiniTable
          rows={tradeRows(topLossTrades)}
          columns={tradeColumns}
          emptyLabel="손실 거래 없음"
        />
      </section>
      <section className="detail-section">
        <h3>거래 샘플</h3>
        <MiniTable
          rows={tradeRows(trades.slice(0, 20))}
          columns={tradeColumns}
          emptyLabel="완료된 거래 샘플 없음"
        />
      </section>
    </div>
  );
}
