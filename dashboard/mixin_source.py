"""Mixin 网络资产(如李笑来的 BOX 指数基金)的历史价格源。

b.watch 只有现价,历史价用 Mixin 公开接口逐月取:
GET https://api.mixin.one/network/ticker?asset={id}&offset={ISO时间} → 当时的 price_usd。

加密资产全年无休,约定"每月首个交易日"= 每月 1 号。历史月首点写入
data/mixin_{symbol}.json 缓存(随仓库提交,兼作数据快照),每次运行只补缺失月份;
"今天"的估值点每次实时获取,只存在于返回值,不进缓存。

缓存格式 v2:{"asset_id": "...", "prices": {"YYYY-MM-DD": float}}。
asset_id 是缓存身份:配置里换了 asset_id、或缓存是无身份的旧扁平格式,
都会使缓存整体作废重拉(月首点数量级很小),防止新旧资产价格混成一条序列。

已知接受的局限:ticker 接口不返回报价自身的时间戳,今天的报价即视为今天的
估值(与请求 offset 同刻),无法做二次新鲜度校验;上市前月份没有"确定无数据"
标记,每次运行会重试这些月份(每月一次、量级极小)。
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import date
from pathlib import Path

import requests

TICKER_URL = "https://api.mixin.one/network/ticker"
RETRIES = 3
RETRY_BACKOFF_S = 1.5


def _month_firsts(start: date, end: date) -> list[date]:
    firsts = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        firsts.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return firsts


def _valid_price(v) -> bool:
    # bool 是 int 的子类,True 会伪装成 1.0,必须显式排除
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v > 0)


def load_cache(text: str | None, asset_id: str) -> dict[date, float]:
    """解析并校验缓存文本;身份不符、结构损坏、非法条目一律丢弃(宁可重拉)。

    只保留每月 1 号的点——旧版本曾把"今天"也写进缓存,月中残留点若被当成
    月首交易日会造成错误买入日,这里在加载时统一清洗。
    """
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    # 只认 v2 格式;旧扁平格式没有资产身份,盲目迁移会把旧数据永久盖上
    # 新 asset_id 的戳,宁可作废重拉(月首点数量级很小)
    if (not isinstance(raw, dict) or raw.get("asset_id") != asset_id
            or not isinstance(raw.get("prices"), dict)):
        return {}
    entries = raw["prices"]
    out: dict[date, float] = {}
    for k, v in entries.items():
        try:
            d = date.fromisoformat(k)
        except (TypeError, ValueError):
            continue
        if d.day == 1 and _valid_price(v):
            out[d] = float(v)
    return out


def _save_cache(cache_path: Path, asset_id: str, prices: dict[date, float]) -> None:
    payload = {"asset_id": asset_id,
               "prices": {d.isoformat(): p for d, p in sorted(prices.items())}}
    tmp = cache_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    os.replace(tmp, cache_path)


def _price_at(session: requests.Session, asset_id: str, d: date) -> float | None:
    """取 d 日价格;瞬时故障重试;响应结构异常时报带上下文的错误。"""
    last_err: Exception | None = None
    for attempt in range(RETRIES):
        try:
            resp = session.get(TICKER_URL, timeout=20,
                               params={"asset": asset_id,
                                       "offset": f"{d.isoformat()}T00:00:00Z"})
            resp.raise_for_status()
            price = float(resp.json()["data"]["price_usd"])
            return price if _valid_price(price) else None
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            last_err = e
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))
    raise RuntimeError(f"mixin ticker failed for {asset_id} @ {d}: {last_err}")


def mixin_prices(asset_id: str, symbol: str, start: date, today: date,
                 cache_dir: Path) -> dict[date, float]:
    """返回 {日期: USD 价格}:起点当月 1 号起的每月 1 号 + 今天(估值点)。"""
    if start > today:
        raise ValueError(f"start {start} is after today {today}")

    cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / f"mixin_{symbol}.json"
    raw_text = cache_path.read_text() if cache_path.exists() else None
    cache = load_cache(raw_text, asset_id)

    session = requests.Session()
    # 旧扁平格式或清洗掉过条目时,即使没有新增月份也要重写成 v2 格式
    dirty = raw_text is not None and '"prices"' not in raw_text
    for d in _month_firsts(start.replace(day=1), today):
        if d not in cache:
            price = _price_at(session, asset_id, d)
            if price is not None:  # 上市前月份无有效价 → 留空,该月自然跳过
                cache[d] = price
                dirty = True
            time.sleep(0.2)  # 对公共接口保持礼貌
    if dirty:
        _save_cache(cache_path, asset_id, cache)  # 先落盘:取现价失败不丢回填进度

    price_today = cache.get(today) if today.day == 1 else None  # 1 号当天复用月首点
    if price_today is None:
        price_today = _price_at(session, asset_id, today)
    if price_today is None:
        raise RuntimeError(f"no current price for {symbol} ({asset_id})")

    result = {d: p for d, p in cache.items() if start.replace(day=1) <= d <= today}
    result[today] = price_today
    return result
