"""拉取价格与汇率,运行定投模拟,生成 docs/data.json 供网页读取。

用法:python -m dashboard.fetch_and_compute
数据口径:yfinance auto_adjust 复权价(价格总回报近似);USDCNY 用 "CNY=X"。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import yfinance as yf

from dashboard.dca_lite import run_dca

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "tickers.json"
OUT = ROOT / "docs" / "data.json"


def daily_closes(symbol: str, start: str) -> dict[date, float]:
    df = yf.Ticker(symbol).history(start=start, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"no price data for {symbol}")
    return {ts.date(): float(c) for ts, c in df["Close"].items() if c == c}  # 过滤 NaN


def main() -> None:
    cfg = json.loads(CONFIG.read_text())
    start = date.fromisoformat(cfg["start"])
    monthly = float(cfg["monthly_cny"])
    today = date.today()

    # 汇率提前取一段,保证首个买入日能向前回溯到可得值
    fx = daily_closes("CNY=X", "2020-12-01")

    stocks = []
    for t in cfg["tickers"]:
        prices = daily_closes(t["symbol"], cfg["start"])
        use_fx = fx if t["currency"] == "USD" else None
        r = run_dca(prices, monthly, start, today, fx=use_fx)
        stocks.append({
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
        })
        print(f"{t['symbol']:>10}  months={len(r.buys)}  "
              f"cum={r.cum_return:+.1%}  xirr={r.xirr:+.1%}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": {"monthly_cny": monthly, "start": cfg["start"],
                   "rule": "每月首个交易日按当日复权收盘价买入"},
        "stocks": stocks,
    }, ensure_ascii=False, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
