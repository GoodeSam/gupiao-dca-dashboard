"""dashboard/dca_lite.py 的黄金用例——全部手工可验算。

口径(与 ASSUMPTIONS §10 一致):价格总回报近似(复权价)、允许碎股、零费用;
每月首个交易日以当日价格买入固定 1000 元人民币;美股先按当日(或最近可得)
USDCNY 汇率把人民币换成美元再买入。
"""
from datetime import date

import pytest

from dashboard.dca_lite import first_trading_days, fx_lookup, run_dca


# ---------- 日程:每月首个交易日 ----------

TRADING_DATES = [
    date(2021, 1, 4), date(2021, 1, 5),
    date(2021, 2, 1), date(2021, 2, 2),
    date(2021, 3, 2),
]


def test_first_trading_day_per_month():
    got = first_trading_days(TRADING_DATES, date(2021, 1, 1), date(2021, 3, 31))
    assert got == [date(2021, 1, 4), date(2021, 2, 1), date(2021, 3, 2)]


def test_month_without_data_is_skipped():
    dates = [date(2021, 1, 4), date(2021, 3, 2)]  # 2 月停牌/未上市
    got = first_trading_days(dates, date(2021, 1, 1), date(2021, 3, 31))
    assert got == [date(2021, 1, 4), date(2021, 3, 2)]


def test_range_bounds_are_respected():
    got = first_trading_days(TRADING_DATES, date(2021, 2, 1), date(2021, 2, 28))
    assert got == [date(2021, 2, 1)]


# ---------- 汇率:精确命中或向前回溯 ----------

FX = {date(2021, 1, 4): 6.5, date(2021, 1, 6): 6.4}


def test_fx_exact_date():
    assert fx_lookup(FX, date(2021, 1, 4)) == 6.5


def test_fx_falls_back_to_most_recent_prior():
    assert fx_lookup(FX, date(2021, 1, 5)) == 6.5
    assert fx_lookup(FX, date(2021, 1, 7)) == 6.4


def test_fx_before_first_known_raises():
    with pytest.raises(KeyError):
        fx_lookup(FX, date(2021, 1, 3))


# ---------- 黄金用例 1:人民币标的,无汇率 ----------

def test_golden_cny_two_months():
    """1 月 4 日价 10 元买 1000 元 → 100 份;2 月 1 日价 20 元 → 50 份。
    期末价 20 元:市值 150×20=3000,投入 2000,累计收益率 50%。"""
    prices = {date(2021, 1, 4): 10.0, date(2021, 2, 1): 20.0}
    r = run_dca(prices, monthly_cny=1000.0,
                start=date(2021, 1, 1), end=date(2021, 2, 28))
    assert r.invested == pytest.approx(2000.0)
    assert r.shares == pytest.approx(150.0)
    assert r.value_cny == pytest.approx(3000.0)
    assert r.cum_return == pytest.approx(0.5)
    assert len(r.buys) == 2


# ---------- 黄金用例 2:美元标的,含汇率换算 ----------

def test_golden_usd_with_fx():
    """1 月 4 日:汇率 6.25,1000 元=160 美元,价 100 → 1.6 股;
    2 月 1 日:汇率 6.40,1000 元=156.25 美元,价 100 → 1.5625 股。
    期末价 100、汇率 6.40:市值 3.1625×100×6.4 = 2024 元;投入 2000,收益率 1.2%。"""
    prices = {date(2021, 1, 4): 100.0, date(2021, 2, 1): 100.0}
    fx = {date(2021, 1, 4): 6.25, date(2021, 2, 1): 6.40}
    r = run_dca(prices, monthly_cny=1000.0,
                start=date(2021, 1, 1), end=date(2021, 2, 28), fx=fx)
    assert r.shares == pytest.approx(3.1625)
    assert r.value_cny == pytest.approx(2024.0)
    assert r.cum_return == pytest.approx(0.012)


# ---------- 市值序列与 XIRR 现金流装配 ----------

def test_series_tracks_value_after_each_buy():
    prices = {date(2021, 1, 4): 10.0, date(2021, 2, 1): 20.0}
    r = run_dca(prices, monthly_cny=1000.0,
                start=date(2021, 1, 1), end=date(2021, 2, 28))
    # 买入后即时市值:1 月 100×10=1000;2 月 150×20=3000
    assert r.series == [
        (date(2021, 1, 4), pytest.approx(1000.0)),
        (date(2021, 2, 1), pytest.approx(3000.0)),
    ]


def test_xirr_known_answer():
    """单笔:期初投 1000,一年后(365 天)值 1100 → XIRR 恰为 10%。"""
    prices = {date(2021, 1, 1): 10.0, date(2022, 1, 1): 11.0}
    r = run_dca(prices, monthly_cny=1000.0,
                start=date(2021, 1, 1), end=date(2021, 1, 31))
    # 只有 1 月一笔买入;期末用最后可得价 11 估值
    assert r.invested == pytest.approx(1000.0)
    assert r.value_cny == pytest.approx(1100.0)
    assert r.xirr == pytest.approx(0.10, abs=1e-4)
