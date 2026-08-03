"""3년치 주가·환율·금리 차트를 한 줄(3분할)로 그린다. 최근 1개월은 회색 음영."""
import datetime as dt
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

OUT = Path("charts")
YEARS = 3
SHADE_DAYS = 30

C1, C2 = "#2563eb", "#dc2626"      # 좌축 / 우축
C3 = "#0f766e"                      # 단일축
GRID, TICK, SHADE = "#eeeeee", "#555555", "#e2e8f0"

PANELS = [
    {"title": "Equity indices (3Y)",
     "left": ("^GSPC", "S&P 500", C1),
     "right": ("^IXIC", "Nasdaq", C2)},
    {"title": "FX (3Y)",
     "left": ("DX-Y.NYB", "Dollar index", C1),
     "right": ("KRW=X", "USD/KRW", C2)},
    {"title": "US 10Y Treasury yield (3Y)",
     "left": ("^TNX", "10Y yield (%)", C3),
     "right": None},
]


def download(tickers: list[str]) -> pd.DataFrame:
    df = yf.download(tickers, period=f"{YEARS}y", interval="1d",
                     progress=False, auto_adjust=False, threads=False)
    if df.empty:
        return pd.DataFrame()
    close = df["Close"]
    return close.to_frame() if isinstance(close, pd.Series) else close


def series(close: pd.DataFrame, ticker: str) -> pd.Series | None:
    if ticker not in getattr(close, "columns", []):
        try:
            s = yf.Ticker(ticker).history(period=f"{YEARS}y")["Close"]
        except Exception:
            return None
    else:
        s = close[ticker]
    s = s.dropna()
    if len(s) < 30:
        return None
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    return s


def style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#cccccc")
    ax.spines["bottom"].set_color("#cccccc")
    ax.tick_params(colors=TICK, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def draw(path: Path) -> bool:
    tickers = []
    for p in PANELS:
        tickers.append(p["left"][0])
        if p["right"]:
            tickers.append(p["right"][0])
    close = download(tickers)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), dpi=140)
    drawn = 0

    for ax, panel in zip(axes, PANELS):
        tk, label, color = panel["left"]
        s = series(close, tk)
        if s is None:
            ax.set_visible(False)
            continue

        ax.plot(s.index, s.values, linewidth=1.6, color=color, label=label)
        ax.set_ylabel(label, fontsize=9, color=color)
        ax.tick_params(axis="y", labelcolor=color)
        style(ax)

        # 최근 1개월 음영
        end = s.index.max()
        ax.axvspan(end - pd.Timedelta(days=SHADE_DAYS), end,
                   color=SHADE, alpha=0.75, zorder=0)

        handles = [ax.lines[-1]]
        if panel["right"]:
            tk2, label2, color2 = panel["right"]
            s2 = series(close, tk2)
            if s2 is not None:
                ax2 = ax.twinx()
                ax2.plot(s2.index, s2.values, linewidth=1.6, color=color2, label=label2)
                ax2.set_ylabel(label2, fontsize=9, color=color2)
                ax2.tick_params(axis="y", labelcolor=color2, labelsize=8)
                for side in ("top", "left"):
                    ax2.spines[side].set_visible(False)
                ax2.spines["right"].set_color("#cccccc")
                handles.append(ax2.lines[-1])

        ax.set_title(panel["title"], fontsize=11, pad=10)
        ax.legend(handles, [h.get_label() for h in handles],
                  frameon=False, fontsize=8, loc="upper left")
        drawn += 1

    if not drawn:
        plt.close(fig)
        print("[chart] 데이터를 받지 못해 차트를 만들지 않았습니다")
        return False

    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"[chart] {path} ({drawn}/3 패널)")
    return True


def main():
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    draw(OUT / f"{today:%Y-%m-%d}-overview.png")


if __name__ == "__main__":
    main()
