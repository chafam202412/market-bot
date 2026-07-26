"""미국 시장 스냅샷 수집 (KST 00:00~06:30 구간에서 30분마다 실행)."""
import datetime as dt
import json
from pathlib import Path

import pandas as pd
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
    "XLK": "XLK",
    "XLF": "XLF",
    "XLE": "XLE",
    "SMH": "SMH",
}


def _pack(series: pd.Series) -> dict:
    last, prev = float(series.iloc[-1]), float(series.iloc[-2])
    return {
        "last": round(last, 4),
        "prev_close": round(prev, 4),
        "chg_pct": round((last / prev - 1) * 100, 3),
    }


def fetch_all() -> dict:
    symbols = list(TICKERS.values())
    close = pd.DataFrame()
    try:
        df = yf.download(
            symbols, period="7d", interval="1d",
            progress=False, auto_adjust=False, threads=False,
        )
        if not df.empty:
            close = df["Close"]
    except Exception as exc:
        print(f"[batch] download failed: {type(exc).__name__}: {exc}")

    out = {}
    for name, sym in TICKERS.items():
        s = None
        if sym in getattr(close, "columns", []):
            s = close[sym].dropna()

        if s is None or len(s) < 2:  # 개별 재시도
            try:
                s = yf.Ticker(sym).history(period="7d", interval="1d")["Close"].dropna()
            except Exception as exc:
                out[name] = {"error": f"{type(exc).__name__}: {exc}"[:150]}
                continue

        if s is None or len(s) < 2:
            out[name] = {"error": "no data returned"}
            continue

        out[name] = _pack(s)
    return out


def main() -> None:
    now_kst = dt.datetime.now(dt.timezone.utc).astimezone(KST)
    data = fetch_all()

    ok = sum(1 for v in data.values() if v.get("last") is not None)
    print(f"\n=== {ok}/{len(data)} tickers OK ===")
    for k, v in data.items():
        if "error" in v:
            print(f"  FAIL {k}: {v['error']}")
        else:
            print(f"  {k}: {v['last']} ({v['chg_pct']:+.2f}%)")

    path = Path("snapshots") / f"{now_kst:%Y-%m-%d}.jsonl"
    path.parent.mkdir(exist_ok=True)
    rec = {"ts_kst": now_kst.isoformat(timespec="minutes"), "data": data}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\nwritten: {path}")


if __name__ == "__main__":
    main()
