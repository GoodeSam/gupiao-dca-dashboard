"""拉取价格与汇率,运行定投模拟,生成 docs/data.json 供网页读取。

用法:python -m dashboard.fetch_and_compute
数据口径:yfinance auto_adjust 复权价(价格总回报近似);USDCNY 用 "CNY=X"。
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

from dashboard.dca_lite import run_dca

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "tickers.json"
OUT = ROOT / "docs" / "data.json"

SUPPORTED_CURRENCIES = {"CNY", "USD"}
# 最新数据点距今超过此天数视为上游数据陈旧,放弃本次更新以免覆盖旧产物
# (需容纳 A 股国庆最长休市 + 周末)
MAX_STALE_DAYS = 14
# 汇率序列比投资起点提前取一段,保证首个买入日能向前回溯到可得值
FX_LOOKBACK = timedelta(days=45)


def validate_config(cfg: dict) -> tuple[date, float]:
    monthly = float(cfg["monthly_cny"])
    if not (math.isfinite(monthly) and monthly > 0):
        raise ValueError(f"monthly_cny must be positive and finite, got {monthly}")
    bad = {t["currency"] for t in cfg["tickers"]} - SUPPORTED_CURRENCIES
    if bad:
        raise ValueError(f"unsupported currencies {bad}; supported: {SUPPORTED_CURRENCIES}")
    return date.fromisoformat(cfg["start"]), monthly


def daily_closes(symbol: str, start: str, today: date) -> dict[date, float]:
    df = yf.Ticker(symbol).history(start=start, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"no price data for {symbol}")
    closes = {ts.date(): float(c) for ts, c in df["Close"].items()
              if c == c and math.isfinite(c) and c > 0}
    if not closes:
        raise RuntimeError(f"no valid closes for {symbol}")
    age = (today - max(closes)).days
    if age > MAX_STALE_DAYS:
        raise RuntimeError(
            f"{symbol} data is stale: latest {max(closes)} is {age} days old — "
            f"aborting so the previous data.json is kept")
    return closes


def fmt_pct(v: float | None) -> str:
    return f"{v:+.1%}" if v is not None else "N/A"


def stock_payload(t: dict, r, monthly: float) -> dict:
    return {
        "symbol": t["symbol"],
        "name": t["name"],
        "currency": t["currency"],
        "months": len(r.buys),
        "invested": round(r.invested, 2),
        "value_cny": round(r.value_cny, 2),
        "cum_return": round(r.cum_return, 6),
        "xirr": round(r.xirr, 6) if r.xirr is not None else None,
        "as_of": r.as_of.isoformat() if r.as_of else None,
        "series": [[d.isoformat(), round(v, 2)] for d, v in r.series],
        "invested_series": [
            [b.trade_date.isoformat(), monthly * (i + 1)]
            for i, b in enumerate(r.buys)
        ],
    }


def atomic_write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def main() -> None:
    cfg = json.loads(CONFIG.read_text())
    start, monthly = validate_config(cfg)
    today = date.today()

    fx = None
    if any(t["currency"] == "USD" for t in cfg["tickers"]):
        fx = daily_closes("CNY=X", (start - FX_LOOKBACK).isoformat(), today)

    # 从起点当月的 1 号开始拉价格:即使 start 配在月中,也能识别该月真实的
    # 首个交易日(此时按约定整月跳过,而不是把月中某日误当月首交易日)
    price_start = start.replace(day=1).isoformat()

    stocks = []
    for t in cfg["tickers"]:
        prices = daily_closes(t["symbol"], price_start, today)
        use_fx = fx if t["currency"] == "USD" else None
        r = run_dca(prices, monthly, start, today, fx=use_fx)
        stocks.append(stock_payload(t, r, monthly))
        print(f"{t['symbol']:>10}  months={len(r.buys)}  "
              f"cum={fmt_pct(r.cum_return)}  xirr={fmt_pct(r.xirr)}")

    OUT.parent.mkdir(exist_ok=True)
    atomic_write_json(OUT, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": {"monthly_cny": monthly, "start": cfg["start"],
                   "rule": "每月首个交易日按当日复权收盘价买入"},
        "stocks": stocks,
    })
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
