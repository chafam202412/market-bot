"""스냅샷으로 차트 PNG를 만든다. 한글 폰트 문제를 피하려고 라벨은 영문."""
import datetime as dt
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

KST = dt.timezone(dt.timedelta(hours=9))
OUT = Path("charts")

INDICES = [("S&P500", "S&P 500", "#2563eb"),
           ("NASDAQ", "Nasdaq", "#dc2626"),
           ("DOW", "Dow", "#16a34a")]

SECTORS = [("SMH", "Semis"), ("XLK", "Tech"), ("XLF", "Financials"),
           ("XLE", "Energy"), ("RUSSELL2000", "Small cap")]

PLUS, MINUS = "#d32f2f", "#1565c0"


def style_axes(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#cccccc")
    ax.spines["bottom"].set_color("#cccccc")
    ax.tick_params(colors="#555555", labelsize=9)
    ax.grid(axis="y", color="#eeeeee", linewidth=0.8)
    ax.set_axisbelow(True)


def intraday(snaps, path: Path) -> bool:
    if len(snaps) < 3:
        print("[chart] 스냅샷 3건 미만 - 장중 차트 생략")
        return False

    times = [dt.datetime.fromisoformat(s["ts_kst"]) for s in snaps]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)

    drawn = False
    for key, label, color in INDICES:
        ys = []
        for s in snaps:
            d = s["data"].get(key, {})
            ys.append(d.get("chg_pct"))
        if all(y is None for y in ys):
            continue
        xs = [t for t, y in zip(times, ys) if y is not None]
        vs = [y for y in ys if y is not None]
        ax.plot(xs, vs, marker="o", markersize=3, linewidth=2, label=label, color=color)
        ax.annotate(f"{vs[-1]:+.2f}%", (xs[-1], vs[-1]), textcoords="offset points",
                    xytext=(6, 0), fontsize=9, color=color, va="center")
        drawn = True

    if not drawn:
        plt.close(fig)
        return False

    ax.axhline(0, color="#999999", linewidth=1, linestyle="--")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_ylabel("Change from prev close (%)", fontsize=9, color="#555555")
    ax.set_title("US indices during the session (KST)", fontsize=12, pad=12)
    ax.legend(frameon=False, fontsize=9, loc="best")
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"[chart] {path}")
    return True


def sectors(snaps, path: Path) -> bool:
    last = snaps[-1]["data"]
    items = []
    for key, label in SECTORS:
        v = last.get(key, {}).get("chg_pct")
        if v is not None:
            items.append((label, v))
    if not items:
        return False

    items.sort(key=lambda x: x[1])
    labels = [i[0] for i in items]
    vals = [i[1] for i in items]
    colors = [PLUS if v >= 0 else MINUS for v in vals]

    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    bars = ax.barh(labels, vals, color=colors, height=0.6)
    for bar, v in zip(bars, vals):
        off = 0.06 if v >= 0 else -0.06
        ax.text(v + off, bar.get_y() + bar.get_height() / 2, f"{v:+.2f}%",
                va="center", ha="left" if v >= 0 else "right",
                fontsize=9, color=PLUS if v >= 0 else MINUS)

    ax.axvline(0, color="#999999", linewidth=1)
    ax.set_title("Sector performance", fontsize=12, pad=12)
    lim = max(abs(min(vals)), abs(max(vals))) * 1.35 + 0.1
    ax.set_xlim(-lim, lim)
    ax.set_xticks([])
    style_axes(ax)
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"[chart] {path}")
    return True


def main():
    files = sorted(Path("snapshots").glob("*.jsonl"))
    if not files:
        print("스냅샷 없음")
        return
    src = files[-1]
    snaps = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not snaps:
        return

    OUT.mkdir(exist_ok=True)
    stem = src.stem
    intraday(snaps, OUT / f"{stem}-intraday.png")
    sectors(snaps, OUT / f"{stem}-sector.png")


if __name__ == "__main__":
    main()
