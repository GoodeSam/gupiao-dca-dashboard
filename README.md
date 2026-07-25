# 定投看板 DCA Dashboard

模拟"每月首个交易日定投 1000 元人民币"(2021-01 至今)在若干股票/ETF 上的累计收益率,
静态页面发布于 GitHub Pages,数据由 GitHub Actions 每月自动更新。

## 口径(重要)

复权收盘价(价格总回报近似)、允许碎股、零费用;美元标的按当日(或最近可得)
USDCNY 汇率换算。**仅供研究,非投资建议,结果不可当作实盘预期。**

## 修改跟踪的股票

编辑 `config/tickers.json` 后 push;或在 Actions 页手动触发 `update-data` 工作流立即重算。

## 结构

- `dashboard/dca_lite.py` — 核心计算(TDD,黄金用例见 `tests/`)
- `dashboard/fetch_and_compute.py` — 拉数据(yfinance)→ 生成 `docs/data.json`
- `docs/` — GitHub Pages 站点(`index.html` + `data.json`)
- `.github/workflows/update-data.yml` — 每月 10 日自动重算(测试全绿才更新)

## 本地运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q          # 测试
.venv/bin/python -m dashboard.fetch_and_compute  # 重算数据
```
