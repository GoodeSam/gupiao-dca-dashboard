"""定投看板的核心计算(价格总回报近似口径,见 ASSUMPTIONS §10)。

与 src/dca_backtest 的账本引擎不同,这里是轻量近似:复权价单层、允许碎股、
零费用,float 精度。结论性研究以账本引擎为准;本模块只服务网页看板。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pyxirr import xirr as _xirr


def first_trading_days(trading_dates: list[date], start: date, end: date) -> list[date]:
    """在 [start, end] 内,取每个自然月的第一个交易日;当月无数据则跳过该月。"""
    out: dict[tuple[int, int], date] = {}
    for d in trading_dates:
        if not (start <= d <= end):
            continue
        key = (d.year, d.month)
        if key not in out or d < out[key]:
            out[key] = d
    return [out[k] for k in sorted(out)]


def fx_lookup(fx: dict[date, float], d: date) -> float:
    """取 d 当日汇率;当日缺失则向前回溯最近可得值。早于首个已知日期则报错。"""
    if d in fx:
        return fx[d]
    prior = [k for k in fx if k < d]
    if not prior:
        raise KeyError(f"no FX rate on or before {d}")
    return fx[max(prior)]


@dataclass(frozen=True)
class Buy:
    trade_date: date
    price: float          # 标的本币价格
    fx_rate: float        # 当日 CNY/本币;人民币标的为 1.0
    shares: float


@dataclass
class DcaResult:
    buys: list[Buy] = field(default_factory=list)
    invested: float = 0.0
    shares: float = 0.0
    value_cny: float = 0.0
    cum_return: float = 0.0
    xirr: float | None = None
    series: list[tuple[date, float]] = field(default_factory=list)  # 每次买入后的市值(CNY)
    as_of: date | None = None


def run_dca(
    prices: dict[date, float],
    monthly_cny: float,
    start: date,
    end: date,
    fx: dict[date, float] | None = None,
) -> DcaResult:
    """按 [start, end] 内每月首个交易日定投 monthly_cny 元;
    估值日取价格序列的最后一天(实际使用中即最新交易日)。"""
    r = DcaResult()
    schedule = first_trading_days(sorted(prices), start, end)
    for d in schedule:
        rate = fx_lookup(fx, d) if fx else 1.0
        shares = monthly_cny / rate / prices[d]
        r.buys.append(Buy(d, prices[d], rate, shares))
        r.shares += shares
        r.invested += monthly_cny
        r.series.append((d, r.shares * prices[d] * rate))

    if not r.buys:
        return r

    r.as_of = max(prices)
    last_rate = fx_lookup(fx, r.as_of) if fx else 1.0
    r.value_cny = r.shares * prices[r.as_of] * last_rate
    r.cum_return = r.value_cny / r.invested - 1

    flows = [(b.trade_date, -monthly_cny) for b in r.buys]
    flows.append((r.as_of, r.value_cny))
    r.xirr = _xirr(flows)
    return r
