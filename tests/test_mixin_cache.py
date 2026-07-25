"""mixin_source.load_cache 的黄金用例——缓存身份与清洗规则。"""
import json
from datetime import date

from dashboard.mixin_source import load_cache

AID = "f5ef6b5d-cc5a-3d90-b2c0-a2fd386e7a3c"


def test_v2_roundtrip():
    text = json.dumps({"asset_id": AID, "prices": {"2021-10-01": 5.52, "2021-11-01": 6.1}})
    assert load_cache(text, AID) == {date(2021, 10, 1): 5.52, date(2021, 11, 1): 6.1}


def test_asset_id_mismatch_discards_everything():
    """换了 asset_id 必须整体作废,防止新旧资产价格混成一条序列。"""
    text = json.dumps({"asset_id": "other-asset", "prices": {"2021-10-01": 5.52}})
    assert load_cache(text, AID) == {}


def test_legacy_flat_format_rejected():
    """旧版扁平格式没有资产身份,必须整体作废重拉,不做盲目迁移。"""
    text = json.dumps({"2021-10-01": 5.52, "2026-07-25": 6.68})
    assert load_cache(text, AID) == {}


def test_mid_month_points_dropped():
    """月中残留点(旧版曾缓存'今天')必须清洗,防止被当成月首交易日。"""
    text = json.dumps({"asset_id": AID, "prices": {
        "2021-10-01": 5.52, "2026-07-25": 6.68}})
    assert load_cache(text, AID) == {date(2021, 10, 1): 5.52}


def test_invalid_entries_dropped():
    text = json.dumps({"asset_id": AID, "prices": {
        "2021-10-01": 5.52, "not-a-date": 1.0, "2021-11-01": 0,
        "2021-12-01": -3, "2022-01-01": "oops", "2022-02-01": True}})
    assert load_cache(text, AID) == {date(2021, 10, 1): 5.52}


def test_corrupt_or_empty_text():
    assert load_cache(None, AID) == {}
    assert load_cache("", AID) == {}
    assert load_cache("{not json", AID) == {}
    assert load_cache(json.dumps([1, 2]), AID) == {}
