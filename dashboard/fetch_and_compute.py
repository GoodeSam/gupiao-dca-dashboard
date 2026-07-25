"""拉取价格与汇率,运行定投模拟,生成 docs/data.json 供网页读取。

用法:python -m dashboard.fetch_and_compute
数据口径:yfinance auto_adjust 复权价(价格总回报近似);
汇率:USDCNY 用 "CNY=X",HKDCNY 用 "HKDCNY=X"。
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

from dashboard.dca_lite import run_dca
from dashboard.mixin_source import mixin_prices

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "tickers.json"
OUT = ROOT / "docs" / "data.json"

FX_SYMBOLS = {"USD": "CNY=X", "HKD": "HKDCNY=X"}  # 币种 → yfinance 汇率代码(CNY/本币)
SUPPORTED_CURRENCIES = {"CNY"} | set(FX_SYMBOLS)
# 最新数据点距今超过此天数视为上游数据陈旧(需容纳 A 股国庆最长休市 + 周末)
MAX_STALE_DAYS = 14
# 汇率序列比最早起投日提前取一段,保证首个买入日能向前回溯到可得值
FX_LOOKBACK = timedelta(days=45)


def ticker_start(t: dict, cfg: dict) -> date:
    return date.fromisoformat(t.get("start", cfg["start"]))


def validate_config(cfg: dict) -> float:
    monthly = float(cfg["monthly_cny"])
    if not (math.isfinite(monthly) and monthly > 0):
        raise ValueError(f"monthly_cny must be positive and finite, got {monthly}")
    bad = {t["currency"] for t in cfg["tickers"]} - SUPPORTED_CURRENCIES
    if bad:
        raise ValueError(f"unsupported currencies {bad}; supported: {SUPPORTED_CURRENCIES}")
    for t in cfg["tickers"]:
        ticker_start(t, cfg)  # 起投日必须是合法 ISO 日期
    return monthly


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
            f"{symbol} data is stale: latest {max(closes)} is {age} days old")
    return closes


def fmt_pct(v: float | None) -> str:
    return f"{v:+.1%}" if v is not None else "N/A"


def stock_payload(t: dict, r, monthly: float, start: date) -> dict:
    return {
        "symbol": t["symbol"],
        "name": t["name"],
        "currency": t["currency"],
        "start": start.isoformat(),
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
    monthly = validate_config(cfg)
    today = date.today()
    earliest = min(ticker_start(t, cfg) for t in cfg["tickers"])

    # 只拉实际用到的币种的汇率;汇率是共享基础设施,失败则整体失败
    fx: dict[str, dict[date, float]] = {}
    for ccy in {t["currency"] for t in cfg["tickers"]} & set(FX_SYMBOLS):
        fx[ccy] = daily_closes(FX_SYMBOLS[ccy], (earliest - FX_LOOKBACK).isoformat(), today)

    stocks, failed = [], []
    for t in cfg["tickers"]:
        start = ticker_start(t, cfg)
        # 从起投当月 1 号拉价格:即使 start 配在月中,也能识别该月真实的首个
        # 交易日(此时按约定整月跳过,而不是把月中某日误当月首交易日)
        try:
            if t.get("source") == "mixin":
                prices = mixin_prices(t["asset_id"], t["symbol"], start, today,
                                      ROOT / "data")
            else:
                prices = daily_closes(t["symbol"], start.replace(day=1).isoformat(), today)
            r = run_dca(prices, monthly, start, today, fx=fx.get(t["currency"]))
            stocks.append(stock_payload(t, r, monthly, start))
            print(f"{t['symbol']:>10}  months={len(r.buys)}  "
                  f"cum={fmt_pct(r.cum_return)}  xirr={fmt_pct(r.xirr)}")
        except Exception as e:  # 单标的失败不拖垮整体,记入 failed 供页面展示
            failed.append({"symbol": t["symbol"], "name": t["name"], "error": str(e)})
            print(f"{t['symbol']:>10}  FAILED: {e}")

    if not stocks:
        raise RuntimeError("all tickers failed — refusing to overwrite data.json")

    OUT.parent.mkdir(exist_ok=True)
    atomic_write_json(OUT, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": {"monthly_cny": monthly, "start": cfg["start"],
                   "rule": "每月首个交易日按当日复权收盘价买入"},
        "stocks": stocks,
        "failed": failed,
    })
    print(f"wrote {OUT} ({len(stocks)} ok, {len(failed)} failed)")


if __name__ == "__main__":
    main()
