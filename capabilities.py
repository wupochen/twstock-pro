# -*- coding: utf-8 -*-
"""功能開關中心：先做好、但要等方案或授權到位才打開的功能。

每項功能分三層，不混在一起：
- available：技術上有沒有可用的資料提供者／通道（例：方案有沒有排行端點）
- allowed：授權上可不可以給這位觀看者看（接 data_license）
- enabled：available 且 allowed，且服務目前在線
reason 用白話寫出「為什麼關著」，UI 直接顯示，不自己判斷。

預設設定＝目前實況：富果免費方案（無 snapshot、WebSocket 5 訂閱）、沒有 Shioaji、所有來源授權未確認。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional

from data_license import ViewerScope, can_display


class Feature(str, Enum):
    INTRADAY_RANKING = "盤中即時排行"
    FAST_STREAMING = "多格即時推送更新"
    MULTI_USER_DISPLAY = "開放其他使用者觀看"


# 每格依畫面需要的推送頻道（一格可能不只一個訂閱）
CHANNELS_PER_VIEW: Dict[str, List[str]] = {
    "rt": ["trades"],                 # 即時走勢
    "ob": ["books"],                  # 五檔
    "k1": ["candles"], "k5": ["candles"], "k15": ["candles"],
    "ta": [],                         # 日K（不需推送）
    "chip": [],                       # 籌碼（盤後）
}


@dataclass
class ProviderConfig:
    """目前擁有的資料方案（設定值；換方案只改這裡）。"""
    fugle_plan: str = "basic"                  # basic／developer／advanced
    shioaji_enabled: bool = False
    stream_subscription_limit: Optional[int] = None   # None＝依方案預設
    stream_online: bool = False                # 推送服務目前是否在線（實際連線後才會 True）

    def ranking_providers(self) -> List[str]:
        out = []
        if self.fugle_plan in ("developer", "advanced"):
            out.append("Fugle")
        if self.shioaji_enabled:
            out.append("Shioaji")
        return out

    def subscription_limit(self) -> int:
        if self.stream_subscription_limit is not None:
            return self.stream_subscription_limit
        base = {"basic": 5, "developer": 300, "advanced": 2000}.get(self.fugle_plan, 0)
        return base + (200 if self.shioaji_enabled else 0)

    def stream_providers(self) -> List[str]:
        out = ["Fugle"] if self.fugle_plan in ("basic", "developer", "advanced") else []
        if self.shioaji_enabled:
            out.append("Shioaji")
        return out


@dataclass
class CapabilityState:
    feature: Feature
    available: bool
    allowed: bool
    enabled: bool
    reason: str = ""
    detail: Dict[str, object] = field(default_factory=dict)


def required_subscriptions(views: Iterable[str]) -> int:
    """依每格實際畫面算訂閱數（不是格數）。未知畫面視為需要 1 個。"""
    return sum(len(CHANNELS_PER_VIEW.get(v, ["?"])) for v in views)


def _allowed(sources: Iterable[str], viewer: ViewerScope) -> Optional[str]:
    """回傳第一個不允許的來源；全部允許回 None。"""
    for s in sources:
        if not can_display(s, viewer):
            return s
    return None


def intraday_ranking(cfg: ProviderConfig, viewer: ViewerScope) -> CapabilityState:
    provs = cfg.ranking_providers()
    if not provs:
        return CapabilityState(Feature.INTRADAY_RANKING, False, False, False,
                               "目前行情方案未開放排行榜資料")
    blocked = _allowed(provs[:1], viewer)
    if blocked:
        return CapabilityState(Feature.INTRADAY_RANKING, True, False, False,
                               f"排行資料（{blocked}）尚未取得對外顯示授權", {"provider": provs[0]})
    return CapabilityState(Feature.INTRADAY_RANKING, True, True, True, "", {"provider": provs[0]})


def fast_streaming(cfg: ProviderConfig, views: List[str], viewer: ViewerScope) -> CapabilityState:
    need, limit = required_subscriptions(views), cfg.subscription_limit()
    provs = cfg.stream_providers()
    if not provs or need > limit:
        return CapabilityState(Feature.FAST_STREAMING, False, False, False,
                               f"目前方案推送額度 {limit}，這個版面需要 {need}，改用定時更新",
                               {"need": need, "limit": limit})
    blocked = _allowed(provs[:1], viewer)
    if blocked:
        return CapabilityState(Feature.FAST_STREAMING, True, False, False,
                               f"即時行情（{blocked}）尚未取得對外顯示授權", {"need": need, "limit": limit})
    if not cfg.stream_online:
        return CapabilityState(Feature.FAST_STREAMING, True, True, False, "推送服務目前未連線，改用定時更新",
                               {"need": need, "limit": limit})
    return CapabilityState(Feature.FAST_STREAMING, True, True, True, "", {"need": need, "limit": limit})


def multi_user_display(rendered_sources: Iterable[str]) -> CapabilityState:
    """看「這次實際要顯示的來源」，不是頁面程式可能用到的所有來源。"""
    srcs = list(rendered_sources)
    blocked = _allowed(srcs, ViewerScope.EXTERNAL)
    if blocked:
        return CapabilityState(Feature.MULTI_USER_DISPLAY, True, False, False,
                               f"其中的「{blocked}」資料尚未取得對外顯示授權", {"blocked_source": blocked})
    return CapabilityState(Feature.MULTI_USER_DISPLAY, True, True, True)
