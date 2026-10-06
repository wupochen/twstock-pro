# -*- coding: utf-8 -*-
"""Engine skeleton 測試。前三個是 GPT 指定的保護測試。"""
from datetime import time

import pytest

import engine as E
from schema import Actionability as A, Direction as D, FamilyVote as V, Horizon as H, MarketSession as S, RiskLevel as R

SHORT = E.FAMILIES[H.SHORT]  # 趨勢、動能、量價、法人籌碼
OK_BARS = E.TradeContext(market_session=S.CLOSED, completed_daily_bars=200)


def votes(fams, vals):
    return [V(f, v, "測試") for f, v in zip(fams, vals)]


# ── GPT 保護測試 ──────────────────────────────
def test_case_a_1711_locked_limit_up():
    """1711 2026-10-06：方向偏多／風險高／無法正常交易（漲停鎖單）。"""
    flags = E.risk_flags_from_values(rsi14=75.99, bias_ma20_pct=20.7, margin_3d_pct=18.9) + ["漲停鎖單"]
    ctx = E.TradeContext(market_session=S.OPEN, now_time=time(13, 20), locked_limit_up=True,
                         day_change_pct=9.95, completed_daily_bars=200)
    r = E.evaluate_horizon(H.SHORT, votes(SHORT, [1, 1, 1, 1]), flags, ctx)
    assert r.direction == D.BULL
    assert r.risk_level == R.HIGH
    assert "漲停鎖單" not in r.risk_flags          # 鎖單不算風險，交給可操作
    assert r.actionability == A.NOT_TRADABLE and "漲停鎖單" in r.action_reason


def test_case_b_missing_family_is_none_not_zero():
    """家族沒資料必須是 None，不能當 0（中性）。"""
    r = E.evaluate_horizon(H.SHORT, votes(SHORT[:3], [1, 1, 1]), ctx=OK_BARS)  # 法人籌碼沒給
    chip = next(v for v in r.votes if v.family == "法人籌碼")
    assert chip.vote is None
    assert r.explain() == "3 個有效家族中，3 個支持偏多、0 個支持偏空。"
    assert any("法人籌碼" in s for s in r.data_status)
    # None 與 0 結果必須不同
    with_none = E.evaluate_horizon(H.SHORT, votes(SHORT, [1, None, None, None]), ctx=OK_BARS)
    with_zero = E.evaluate_horizon(H.SHORT, votes(SHORT, [1, 0, 0, 0]), ctx=OK_BARS)
    assert with_none.direction == D.INSUFFICIENT
    assert with_zero.direction == D.LEAN_BULL


def test_case_c_strong_but_overheated_stays_bullish():
    """4 票偏多＋RSI 85＋乖離 18% → 方向仍是偏多，只有風險變高。"""
    flags = E.risk_flags_from_values(rsi14=85, bias_ma20_pct=18)
    r = E.evaluate_horizon(H.SHORT, votes(SHORT, [1, 1, 1, 1]), flags, OK_BARS)
    assert r.direction == D.BULL
    assert r.risk_level == R.HIGH
    assert r.actionability == A.OK


# ── 方向分級表 ───────────────────────────────
@pytest.mark.parametrize("net,valid,exp", [
    (3, 3, D.BULL), (2, 3, D.BULL), (1, 3, D.LEAN_BULL), (0, 3, D.NEUTRAL), (-1, 3, D.LEAN_BEAR), (-2, 3, D.BEAR),
    (4, 4, D.BULL), (3, 4, D.BULL), (2, 4, D.LEAN_BULL), (1, 5, D.LEAN_BULL), (0, 4, D.NEUTRAL),
    (-1, 4, D.LEAN_BEAR), (-2, 5, D.LEAN_BEAR), (-3, 4, D.BEAR), (-5, 5, D.BEAR),
])
def test_grade_table(net, valid, exp):
    assert E.grade_direction(net, valid) == exp


def test_min_valid_votes():
    assert E.MIN_VALID_VOTES == {3: 2, 4: 3, 5: 3}
    # 四家族只有 2 票（+2）→ 資料不足，不能判偏多
    r = E.evaluate_horizon(H.SHORT, votes(SHORT, [1, 1, None, None]), ctx=OK_BARS)
    assert r.direction == D.INSUFFICIENT and "至少要 3" in r.data_status[0]
    # 四家族 3 票 → 用三票表
    assert E.evaluate_horizon(H.SHORT, votes(SHORT, [1, 1, 0, None]), ctx=OK_BARS).direction == D.BULL
    # 當沖三家族 2 票可以判
    assert E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, 0, None]), ctx=dt_ctx()).direction == D.LEAN_BULL
    assert E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, None, None]), ctx=dt_ctx()).direction == D.INSUFFICIENT


def test_half_rule_and_required_family():
    long = E.FAMILIES[H.LONG]   # 5 族，必要：獲利、成長
    ctx = E.TradeContext(completed_daily_bars=400)
    # 5 族只有 2 族有資料 → 少於一半
    r = E.evaluate_horizon(H.LONG, votes(long, [1, 1, None, None, None]), ctx=ctx)
    assert r.direction == D.INSUFFICIENT
    # 有 4 族資料但缺必要的「獲利」→ 資料不足
    r = E.evaluate_horizon(H.LONG, votes(long, [1, None, 1, 1, 1]), ctx=ctx)
    assert r.direction == D.INSUFFICIENT and "獲利" in r.data_status[0]
    # 估值、財務可缺
    r = E.evaluate_horizon(H.LONG, votes(long, [1, 1, 1, None, None]), ctx=ctx)
    assert r.direction == D.BULL  # 3 有效票、淨 3


def test_warmup_bars():
    r = E.evaluate_horizon(H.SWING, votes(E.FAMILIES[H.SWING], [1, 1, 1, 1]),
                           ctx=E.TradeContext(completed_daily_bars=119))
    assert r.direction == D.INSUFFICIENT and "120" in r.data_status[0]
    r = E.evaluate_horizon(H.SWING, votes(E.FAMILIES[H.SWING], [1, 1, 1, 1]),
                           ctx=E.TradeContext(completed_daily_bars=120))
    assert r.direction == D.BULL


def test_vote_validation():
    with pytest.raises(ValueError):
        E.evaluate_horizon(H.SHORT, [V("KD", 1)], ctx=OK_BARS)          # 未定義家族
    with pytest.raises(ValueError):
        E.evaluate_horizon(H.SHORT, [V("趨勢", 2)], ctx=OK_BARS)        # 票值錯誤
    with pytest.raises(ValueError):
        E.evaluate_horizon(H.SHORT, [V("趨勢", 1), V("趨勢", -1)], ctx=OK_BARS)


# ── 風險 ─────────────────────────────────────
def test_risk_levels_and_thresholds():
    assert E.evaluate_horizon(H.SHORT, votes(SHORT, [1, 0, 0, 0]), [], OK_BARS).risk_level == R.LOW
    assert E.risk_flags_from_values(rsi14=80, bias_ma20_pct=15, margin_3d_pct=10) == []  # 門檻是「大於」
    assert len(E.risk_flags_from_values(rsi14=80.1)) == 1
    assert E.risk_flags_from_values(bias_ma20_pct=-16) == ["MA20 負乖離 -16.0%"]   # 往下乖離也算，保留正負
    assert E.risk_flags_from_values(bias_ma20_pct=18) == ["MA20 正乖離 +18.0%"]
    assert E.risk_flags_from_values(None, None, None) == []           # 沒資料不產生旗標
    lvl, only = E.evaluate_risk(["RSI 85 過熱", "暫停交易"])
    assert lvl == R.MEDIUM and only == ["RSI 85 過熱"]


def test_risk_never_changes_direction():
    v = votes(SHORT, [1, 1, 1, 1])
    a = E.evaluate_horizon(H.SHORT, v, [], OK_BARS)
    b = E.evaluate_horizon(H.SHORT, v, ["x1", "x2", "x3"], OK_BARS)
    assert a.direction == b.direction == D.BULL and b.risk_level == R.HIGH


# ── 可操作 ───────────────────────────────────
DT = E.FAMILIES[H.DAYTRADE]


def dt_ctx(**kw):
    base = dict(market_session=S.OPEN, now_time=time(10, 0), data_age_seconds=5, daytrade_eligible=True)
    base.update(kw)
    return E.TradeContext(**base)


def test_daytrade_market_session():
    r = E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, 1, 1]), ctx=dt_ctx(market_session=S.CLOSED, data_age_seconds=3600))
    assert r.actionability == A.MARKET_CLOSED          # 收盤後不是「資料過期」
    r = E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, 1, 1]), ctx=dt_ctx(market_session=S.HALTED))
    assert r.actionability == A.NOT_TRADABLE and r.action_reason == "暫停交易"


def test_daytrade_freshness_and_cutoff():
    assert E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, 1, 1]), ctx=dt_ctx(data_age_seconds=61)).actionability == A.INSUFFICIENT
    assert E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, 1, 1]), ctx=dt_ctx(data_age_seconds=None)).actionability == A.INSUFFICIENT
    assert E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, 1, 1]), ctx=dt_ctx(data_age_seconds=60)).actionability == A.OK
    r = E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, 1, 1]), ctx=dt_ctx(now_time=time(13, 0)))
    assert r.actionability == A.NO_NEW_ENTRY and "13:00" in r.action_reason
    assert A.NO_NEW_ENTRY.value == "不宜新進場"
    assert E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, 1, 1]), ctx=dt_ctx(daytrade_eligible=False)).actionability == A.NO_DAYTRADE


def test_opening_range_none_before_0930():
    """09:30 前「盤中趨勢」(開盤區間) 投 None；另外兩族有資料仍可判斷。"""
    r = E.evaluate_horizon(H.DAYTRADE, votes(DT, [1, None, 1]), ctx=dt_ctx(now_time=time(9, 10)))
    assert r.direction == D.BULL and r.votes[1].vote is None


def test_no_chase_only_when_bullish():
    ctx = E.TradeContext(market_session=S.OPEN, day_change_pct=8.0, completed_daily_bars=200)
    assert E.evaluate_horizon(H.SHORT, votes(SHORT, [1, 1, 1, 0]), ctx=ctx).actionability == A.NO_CHASE
    assert E.evaluate_horizon(H.SHORT, votes(SHORT, [0, 0, 0, 0]), ctx=ctx).actionability == A.OK


def test_locked_down_has_priority():
    ctx = E.TradeContext(locked_limit_down=True, completed_daily_bars=200)
    r = E.evaluate_horizon(H.SHORT, votes(SHORT, [-1, -1, -1, -1]), ["跌停鎖單"], ctx)
    assert r.direction == D.BEAR and r.actionability == A.NOT_TRADABLE and r.risk_level == R.LOW


# ── 商品類型 ─────────────────────────────────
def test_asset_types():
    ctx = E.TradeContext(completed_daily_bars=400)
    unk = E.evaluate_horizon(H.LONG, [], ctx=ctx, asset_type="UNKNOWN")
    assert unk.direction == D.INSUFFICIENT and unk.action_reason == "商品類型未確認"   # 不知道 ≠ 不適用
    bond = E.evaluate_horizon(H.LONG, [], ctx=ctx, asset_type="ETF", asset_subtype="BOND")
    assert bond.direction == D.NOT_APPLICABLE and "尚未支援" in bond.action_reason
    # ETF 長線缺折溢價不會整個資料不足（必要只有指數趨勢）
    fam = E.FAMILIES_LONG_ETF
    r = E.evaluate_horizon(H.LONG, [V("指數趨勢", 1), V("規模", 1), V("流動性", 0)], ctx=ctx, asset_type="ETF", asset_subtype="EQUITY")
    assert r.direction == D.BULL
    r = E.evaluate_horizon(H.LONG, [V("折溢價", 0), V("規模", 1), V("流動性", 1)], ctx=ctx, asset_type="ETF", asset_subtype="EQUITY")
    assert r.direction == D.INSUFFICIENT and "指數趨勢" in r.data_status[0]
    etf = E.evaluate_horizon(H.LONG, votes(E.FAMILIES_LONG_ETF, [1, 1, 0, 0]), ctx=ctx, asset_type="ETF", asset_subtype="EQUITY")
    assert etf.direction == D.LEAN_BULL
    # 只靠代號推測（OTHER）無法確認是股票型 → 長線尚未支援
    assert E.evaluate_horizon(H.LONG, [], ctx=ctx, asset_type="ETF", asset_subtype="OTHER").direction == D.NOT_APPLICABLE
    # 短線、波段 ETF 照常
    assert E.evaluate_horizon(H.SHORT, votes(SHORT, [1, 1, 0, 0]), ctx=ctx, asset_type="ETF", asset_subtype="BOND").direction == D.LEAN_BULL
    with pytest.raises(ValueError):  # ETF 不能用個股的「獲利」家族
        E.evaluate_horizon(H.LONG, [V("獲利", 1)], ctx=ctx, asset_type="ETF", asset_subtype="EQUITY")


def test_explain_has_no_percent_and_version():
    r = E.evaluate_horizon(H.SHORT, votes(SHORT, [1, 1, 0, -1]), ctx=OK_BARS)
    assert "%" not in r.explain() and r.explain() == "4 個有效家族中，2 個支持偏多、1 個支持偏空。"
    assert r.rule_version == E.RULE_VERSION
    assert r.supports and r.against
