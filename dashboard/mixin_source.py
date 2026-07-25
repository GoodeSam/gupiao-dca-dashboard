"""Mixin 网络资产(如李笑来的 BOX 指数基金)的历史价格源。

b.watch 只有现价,历史价用 Mixin 公开接口逐月取:
GET https://api.mixin.one/network/ticker?asset={id}&offset={ISO时间} → 当时的 price_usd。

加密资产全年无休,约定"每月首个交易日"= 每月 1 号。已取过的历史点写入
data/mixin_{symbol}.json 缓存(随仓库提交,兼作数据快照),每次运行只补缺失月份。
"""
from __future__ import annotations

import json
import math
import time
from datetime import date
from pathlib import Path

import requests

TICKER_URL = "https://api.mixin.one/network/ticker"


def _month_firsts(start: date, end: date) -> list[date]:
    firsts = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        firsts.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return firsts


def _price_at(asset_id: str, d: date) -> float | None:
    resp = requests.get(TICKER_URL, timeout=20,
                        params={"asset": asset_id, "offset": f"{d.isoformat()}T00:00:00Z"})
    resp.raise_for_status()
    price = float(resp.json()["data"]["price_usd"])
    return price if math.isfinite(price) and price > 0 else None


def mixin_prices(asset_id: str, symbol: str, start: date, today: date,
                 cache_dir: Path) -> dict[date, float]:
    """返回 {日期: USD 价格}:起点当月 1 号起的每月 1 号 + 今天(估值点)。"""
    cache_path = cache_dir / f"mixin_{symbol}.json"
    cache: dict[str, float] = (
        json.loads(cache_path.read_text()) if cache_path.exists() else {}
    )

    wanted = _month_firsts(start.replace(day=1), today)
    for d in wanted:
        if d.isoformat() not in cache:
            price = _price_at(asset_id, d)
            if price is not None:  # 上市前的月份返回 0/无效 → 留空,该月自然跳过
                cache[d.isoformat()] = price
            time.sleep(0.2)  # 对公共接口保持礼貌

    price_today = _price_at(asset_id, today)
    if price_today is None:
        raise RuntimeError(f"no current price for {symbol} ({asset_id})")
    cache[today.isoformat()] = price_today

    cache_dir.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(dict(sorted(cache.items())), indent=1))

    return {date.fromisoformat(k): v for k, v in cache.items()
            if start.replace(day=1) <= date.fromisoformat(k) <= today}
