import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schema as S


def test_risk_levels():
    assert S.risk_level_from_flags([]) == S.RiskLevel.LOW
    assert S.risk_level_from_flags(["RSI>80"]) == S.RiskLevel.MEDIUM
    assert S.risk_level_from_flags(["RSI>80", "MA20乖離>15%"]) == S.RiskLevel.HIGH
    # 鎖停不計入風險等級
    assert S.risk_level_from_flags(["漲停鎖單"]) == S.RiskLevel.LOW
    assert S.risk_level_from_flags(["漲停鎖單", "融資3日>10%"]) == S.RiskLevel.MEDIUM


def test_opening_range():
    assert not S.opening_range_available(time(9, 10))
    assert not S.opening_range_available(time(9, 29))
    assert S.opening_range_available(time(9, 30))


def test_warmup():
    assert S.WARMUP_BARS[S.Horizon.SHORT] == 60
    assert S.WARMUP_BARS[S.Horizon.SWING] == 120
    assert S.WARMUP_BARS[S.Horizon.LONG] == 300


def test_datapoint_age_and_missing():
    now = datetime(2026, 10, 7, 2, 0, 0, tzinfo=timezone.utc)
    dp = S.DataPoint(48.6, "富果", S.SourceType.VENDOR, S.DataKind.RAW, as_of=now - timedelta(seconds=30))
    assert dp.age_seconds(now) == 30 and not dp.missing
    assert S.DataPoint(None, "yfinance", S.SourceType.THIRD_PARTY, S.DataKind.RAW).missing


def test_explain_is_not_win_rate():
    votes = [S.FamilyVote("趨勢", 1), S.FamilyVote("動能", 1), S.FamilyVote("量價", 0), S.FamilyVote("籌碼", None)]
    r = S.HorizonResult(S.Horizon.SHORT, S.Direction.LEAN_BULL, votes, S.RiskLevel.LOW, [], S.Actionability.OK)
    txt = r.explain()
    assert txt == "3 個有效家族中，2 個支持偏多、0 個支持偏空。"
    assert "%" not in txt


def test_naive_datetime_rejected():
    import pytest
    with pytest.raises(ValueError):
        S.DataPoint(1, "x", S.SourceType.INTERNAL, S.DataKind.CALC, as_of=datetime(2026, 10, 7, 10, 0))
    dp = S.DataPoint(1, "x", S.SourceType.INTERNAL, S.DataKind.CALC, as_of=datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        dp.age_seconds(datetime(2026, 10, 7, 10, 0))
