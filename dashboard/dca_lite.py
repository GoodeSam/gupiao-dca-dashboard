"""定投看板的核心计算。

口径(见本仓库 README「口径」一节):复权价单层(价格总回报近似)、允许碎股、
零费用、float 精度。结果仅供研究展示,不构成可执行记账。
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date

from pyxirr import xirr as _xirr


def first_trading_days(trading_dates: list[date], start: date, end: date) -> list[date]:
    """取每个自然月的第一个交易日,再过滤到 [start, end]。

    月首交易日落在 start 之前的月份被整月跳过(而不是顺延到月中某日买入),
    保证任何买入日都是"当月第一个交易日"。当月无数据同样跳过。
    """
    firsts: dict[tuple[int, int], date] = {}
    for d in trading_dates:
        key = (d.year, d.month)
        if key not in firsts or d < firsts[key]:
            firsts[key] = d
    return [firsts[k] for k in sorted(firsts) if start <= firsts[k] <= end]


class _FxSeries:
    """排序一次、二分查找的汇率序列;拒绝空映射。"""

    def __init__(self, fx: dict[date, float]):
        if not fx:
            raise KeyError("FX mapping is empty")
        self.fx = fx
        self.keys = sorted(fx)

    def at(self, d: date) -> float:
        """取 d 当日汇率;当日缺失则向前回溯最近可得值。早于首个已知日期则报错。"""
        rate = self.fx.get(d)
        if rate is None:
            i = bisect_right(self.keys, d)
            if i == 0:
                raise KeyError(f"no FX rate on or before {d}")
            rate = self.fx[self.keys[i - 1]]
        if not (math.isfinite(rate) and rate > 0):
            raise ValueError(f"invalid FX rate {rate} for {d}")
        return rate


def fx_lookup(fx: dict[date, float], d: date) -> float:
    """便捷函数:等价于 _FxSeries(fx).at(d)。批量查找请复用 _FxSeries。"""
    return _FxSeries(fx).at(d)


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


def _checked_price(prices: dict[date, float], d: date) -> float:
    p = prices[d]
    if not (math.isfinite(p) and p > 0):
        raise ValueError(f"invalid price {p} on {d}")
    return p


def run_dca(
    prices: dict[date, float],
    monthly_cny: float,
    start: date,
    end: date,
    fx: dict[date, float] | None = None,
) -> DcaResult:
    """按 [start, end] 内每月首个交易日定投 monthly_cny 元;
    估值日取价格序列的最后一天(实际使用中即最新交易日)。

    fx 传 None 表示人民币标的(不换算);传映射(哪怕不完整)则每次买入
    都必须能查到当日或此前的汇率,查不到即报错——绝不静默按 1:1 计价。
    """
    if not (math.isfinite(monthly_cny) and monthly_cny > 0):
        raise ValueError(f"monthly_cny must be positive and finite, got {monthly_cny}")

    fxs = _FxSeries(fx) if fx is not None else None
    r = DcaResult()
    for d in first_trading_days(sorted(prices), start, end):
        rate = fxs.at(d) if fxs else 1.0
        price = _checked_price(prices, d)
        shares = monthly_cny / rate / price
        r.buys.append(Buy(d, price, rate, shares))
        r.shares += shares
        r.invested += monthly_cny
        r.series.append((d, r.shares * price * rate))

    if not r.buys:
        return r

    r.as_of = max(prices)
    last_rate = fxs.at(r.as_of) if fxs else 1.0
    r.value_cny = r.shares * _checked_price(prices, r.as_of) * last_rate
    r.cum_return = r.value_cny / r.invested - 1

    flows = [(b.trade_date, -monthly_cny) for b in r.buys]
    flows.append((r.as_of, r.value_cny))
    # 现金流不足两个不同日期时 XIRR 无定义(同日一进一出对任意利率都成立)
    if len({d for d, _ in flows}) >= 2:
        r.xirr = _xirr(flows)
    return r
