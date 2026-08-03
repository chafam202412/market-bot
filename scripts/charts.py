"""주식·채권 차트를 각각 그린다. 3년치, 최근 1개월 회색 음영."""
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

INK = "#1e293b"
MUTED = "#94a3b8"
GRID = "#f1f5f9"
SHADE = "#e2e8f0"
BLUE = "#1e40af"
RED = "#b91c1c"
TEAL = "#0f766e"

FIGSIZE = (10, 3.6)
DPI = 150


def download(tickers):
    df = yf.download(tickers, period=f"{YEARS}y", interval="1d",
                     progress=False, auto_adjust=False, threads=False)
    if df.empty:
        return pd.DataFrame()
    close = df["Close"]
    return close.to_frame() if isinstance(close, pd.Series) else close


def series(close, ticker):
    if ticker in getattr(close, "columns", []):
        s = close[ticker]
    else:
        try:
            s = yf.Ticker(ticker).history(period=f"{YEARS}y")["Close"]
        except Exception:
            return None
    s = s.dropna()
    if len(s) < 30:
        return None
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    return s


def base_axes(ax):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#e2e8f0")
    ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 7)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y.%m"))
    ax.margins(x=0.01)


def shade_recent(ax, end):
    ax.axvspan(end - pd.Timedelta(days=SHADE_DAYS), end,
               color=SHADE, alpha=0.7, zorder=0, linewidth=0)


def stamp(ax, text, color, row=0):
    """좌측 상단에 현재값을 표시한다. 선과 겹치지 않는다."""
    ax.text(0.004, 1.10 - row * 0.13, text, transform=ax.transAxes,
            fontsize=10.5, color=color, fontweight="bold",
            va="top", ha="left")


def endpoint_dot(ax, s, color):
    ax.scatter([s.index[-1]], [float(s.iloc[-1])], s=20, color=color,
               zorder=5, clip_on=False)


def equity(close, path):
    a = series(close, "^GSPC")
    b = series(close, "^IXIC")
    if a is None:
        return False

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    shade_recent(ax, a.index.max())
    ax.plot(a.index, a.values, linewidth=1.5, color=BLUE, solid_capstyle="round")
    ax.fill_between(a.index, a.values, a.values.min(), color=BLUE, alpha=0.05)
    endpoint_dot(ax, a, BLUE)
    stamp(ax, f"S&P 500  {float(a.iloc[-1]):,.2f}", BLUE, 0)
    base_axes(ax)
    ax.tick_params(axis="y", labelcolor=BLUE)

    if b is not None:
        ax2 = ax.twinx()
        ax2.plot(b.index, b.values, linewidth=1.5, color=RED, solid_capstyle="round")
        endpoint_dot(ax2, b, RED)
        stamp(ax, f"NASDAQ  {float(b.iloc[-1]):,.2f}", RED, 1)
        for side in ("top", "left", "right"):
            ax2.spines[side].set_visible(False)
        ax2.tick_params(colors=RED, labelsize=8.5, length=0)
        ax2.grid(False)
        ax2.margins(x=0.01)

    fig.subplots_adjust(top=0.80, bottom=0.14, left=0.07, right=0.93)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"[chart] {path}")
    return True


def bond(close, path):
    s = series(close, "^TNX")
    if s is None:
        return False

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    shade_recent(ax, s.index.max())
    ax.plot(s.index, s.values, linewidth=1.5, color=TEAL, solid_capstyle="round")
    ax.fill_between(s.index, s.values, s.values.min(), color=TEAL, alpha=0.06)
    endpoint_dot(ax, s, TEAL)
    stamp(ax, f"US 10Y  {float(s.iloc[-1]):.3f}%", TEAL, 0)
    base_axes(ax)
    ax.tick_params(axis="y", labelcolor=TEAL)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.1f}%")

    fig.subplots_adjust(top=0.80, bottom=0.14, left=0.07, right=0.93)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"[chart] {path}")
    return True


def main():
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    OUT.mkdir(exist_ok=True)
    close = download(["^GSPC", "^IXIC", "^TNX"])
    equity(close, OUT / f"{today:%Y-%m-%d}-equity.png")
    bond(close, OUT / f"{today:%Y-%m-%d}-bond.png")


if __name__ == "__main__":
    main()
