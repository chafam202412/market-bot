"""미국 시장 30분 스냅샷 수집 (KST 00:00~06:00 구간에서 실행)."""
import datetime as dt
import json
from pathlib import Path

import yfinance as yf

KST = dt.timezone(dt.timedelta(hours=9))

TICKERS = {
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DOW": "^DJI",
    "RUSSELL2000": "^RUT",
    "VIX": "^VIX",
    "US5Y": "^FVX",
    "US10Y": "^TNX",
    "US30Y": "^TYX",
    "DXY": "DX-Y.NYB",
    "USDKRW": "KRW=X",
    "WTI": "CL=F",
    "GOLD": "GC=F",
    "BTC": "BTC-USD",
    # 섹터 ETF (해석용)
    "XLK": "XLK",
    "XLF": "XLF",
    "XLE": "XLE",
    "SMH": "SMH",
}
# 참고: 2년물(^UST2YR)은 yfinance에 없음. 필요하면 FRED DGS2를 별도 호출할 것.


def snapshot() -> dict:
    out = {}
    for name, tk in TICKERS.items():
        try:
            fi = yf.Ticker(tk).fast_info
            last = fi.get("last_price")
            prev = fi.get("previous_close")
            out[name] = {
                "last": round(float(last), 4) if last else None,
                "prev_close": round(float(prev), 4) if prev else None,
                "chg_pct": round((float(last) / float(prev) - 1) * 100, 3)
                if last and prev
                else None,
            }
        except Exception as exc:  # 개별 티커 실패가 전체를 죽이지 않도록
            out[name] = {"error": str(exc)[:120]}
    return out


def main() -> None:
    now_kst = dt.datetime.now(dt.timezone.utc).astimezone(KST)
    path = Path("snapshots") / f"{now_kst:%Y-%m-%d}.jsonl"
    path.parent.mkdir(exist_ok=True)
    rec = {"ts_kst": now_kst.isoformat(timespec="minutes"), "data": snapshot()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"snapshot written: {path} @ {rec['ts_kst']}")


if __name__ == "__main__":
    main()
