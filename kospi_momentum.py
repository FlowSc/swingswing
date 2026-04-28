# ============================================================
#  코스피 모멘텀 스크리닝 (12-1 모멘텀 전략)
#  실행 방법:
#  - 일반 실행: python kospi_momentum.py
#  - 배포용 EXE: 빌드된 실행 파일 더블클릭
# ============================================================

try:
    import FinanceDataReader as fdr
    import pandas as pd
    import openpyxl  # noqa: F401
except ImportError as exc:
    print("필수 패키지가 설치되어 있지 않습니다.")
    print("다음 명령으로 설치한 뒤 다시 실행하세요:")
    print("  python -m pip install finance-datareader pandas openpyxl")
    raise SystemExit(1) from exc

from datetime import datetime, timedelta
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# ★ 설정값 (여기만 바꾸면 됩니다)
# ============================================================
TOP_N          = 30      # 결과 상위 몇 개 출력할지
MOMENTUM_TOP   = 0.80    # 상위 몇 % (0.80 = 상위 20%)
RET_1M_MIN     = -10     # 1개월 수익률 최솟값 (과매도 제외)
RET_1M_MAX     = 30      # 1개월 수익률 최댓값 (과매수 제외)
MIN_VOLUME     = 10000   # 최소 평균 거래량 (유동성 필터)
SAVE_EXCEL     = True    # 엑셀 저장 여부
# ============================================================

def get_momentum(code, name, today):
    try:
        start = (today - timedelta(days=400)).strftime('%Y-%m-%d')
        df = fdr.DataReader(code, start=start)

        if df is None or len(df) < 60:
            return None

        price_now = df['Close'].iloc[-1]
        price_1m  = df['Close'].iloc[-21] if len(df) >= 21 else None
        price_12m = df['Close'].iloc[-252] if len(df) >= 252 else df['Close'].iloc[0]

        if price_1m is None or price_1m == 0 or price_12m == 0:
            return None

        ret_1m    = (price_now - price_1m) / price_1m * 100
        ret_12_1m = (price_1m - price_12m) / price_12m * 100
        avg_vol   = df['Volume'].iloc[-20:].mean()

        return {
            'Code':          code,
            'Name':          name,
            'Price':         int(price_now),
            'Ret_1M(%)':     round(ret_1m, 2),
            'Ret_12_1M(%)':  round(ret_12_1m, 2),
            'AvgVolume':     int(avg_vol)
        }
    except:
        return None


def main():
    today = datetime.today()
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    print("=" * 60)
    print("  📈 코스피 모멘텀 스크리닝 시작")
    print(f"  기준일: {today.strftime('%Y-%m-%d')}")
    print("=" * 60)

    # 1. 종목 리스트
    print("\n① 코스피 전 종목 리스트 불러오는 중...")
    kospi = fdr.StockListing('KOSPI')
    print(f"   → 총 {len(kospi)}개 종목")

    # 2. 모멘텀 계산
    print("\n② 모멘텀 계산 중 (10~20분 소요)...")
    results = []
    total = len(kospi)

    for i, row in kospi.iterrows():
        result = get_momentum(row['Code'], row['Name'], today)
        if result:
            results.append(result)

        if (i + 1) % 100 == 0:
            pct = round((i + 1) / total * 100, 1)
            print(f"   진행: {i+1}/{total} ({pct}%) | 수집: {len(results)}개")

    df = pd.DataFrame(results).dropna()
    print(f"\n   → 데이터 수집 완료: {len(df)}개 종목")

    # 3. 필터링
    print("\n③ 모멘텀 필터 적용 중...")
    threshold = df['Ret_12_1M(%)'].quantile(MOMENTUM_TOP)
    print(f"   12-1M 수익률 상위 {int((1-MOMENTUM_TOP)*100)}% 기준값: {round(threshold,1)}%")

    df_filtered = df[
        (df['Ret_12_1M(%)'] >= threshold) &
        (df['Ret_1M(%)']    >= RET_1M_MIN) &
        (df['Ret_1M(%)']    <= RET_1M_MAX) &
        (df['AvgVolume']    >= MIN_VOLUME)
    ].sort_values('Ret_12_1M(%)', ascending=False).reset_index(drop=True)

    print(f"   → 필터 통과 종목: {len(df_filtered)}개")

    # 4. 결과 출력
    print()
    print("=" * 65)
    print(f"  📊 모멘텀 상위 {TOP_N} 종목")
    print("=" * 65)
    print(f"{'순위':<4} {'코드':<8} {'종목명':<18} {'현재가':>9} {'12-1M%':>8} {'1M%':>7}")
    print("-" * 65)

    for i, row in df_filtered.head(TOP_N).iterrows():
        print(
            f"{i+1:<4} {row['Code']:<8} {row['Name']:<18} "
            f"{row['Price']:>9,} "
            f"{row['Ret_12_1M(%)']:>7.1f}% "
            f"{row['Ret_1M(%)']:>6.1f}%"
        )

    print("=" * 65)
    print("  ⚠️  투자 참고용입니다. 최종 판단은 본인이 직접 하세요.")
    print("=" * 65)

    # 5. 엑셀 저장
    if SAVE_EXCEL:
        filename = output_dir / f"kospi_momentum_{today.strftime('%Y%m%d')}.xlsx"
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df_filtered.to_excel(writer, sheet_name='모멘텀_전체', index=False)
            df_filtered.head(TOP_N).to_excel(writer, sheet_name=f'TOP{TOP_N}', index=False)
        print(f"\n✅ 엑셀 저장 완료: {filename}")

if __name__ == "__main__":
    main()
