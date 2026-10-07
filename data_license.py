# -*- coding: utf-8 -*-
"""資料授權閘門（distribution_status）：這筆資料能不能顯示給「網站擁有者以外的人」。

背景（2026-10-07）：富果使用規範寫明「將交易資訊…傳送予第三人，應負違約及侵權之相關民、刑事責任」，
且不得出售、出租、轉讓、再授權交易資訊。yfinance 資料源（Yahoo）亦以個人、非商業用途為原則。
在拿到書面授權前，所有行情來源一律不得對外顯示。

規則集中在這裡，UI 不得各自判斷：輸出前一律呼叫 can_display(來源, 觀看者範圍)。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


class DistributionStatus(str, Enum):
    INTERNAL_ONLY = "INTERNAL_ONLY"              # 只限網站擁有者本人（開發、診斷、驗證）
    EXTERNAL_ALLOWED = "EXTERNAL_ALLOWED"        # 已取得書面授權，可顯示給其他使用者
    LICENSE_UNCONFIRMED = "LICENSE_UNCONFIRMED"  # 授權未確認：視同只限本人
    BLOCKED = "BLOCKED"                          # 任何人都不顯示


class ViewerScope(str, Enum):
    OWNER = "OWNER"        # 網站擁有者本人
    EXTERNAL = "EXTERNAL"  # 其他登入使用者、匿名訪客


# 改成 EXTERNAL_ALLOWED 之前，必須有資料商的書面回覆並記錄在 LICENSE_NOTES
SOURCE_DISTRIBUTION: Dict[str, DistributionStatus] = {
    "Fugle": DistributionStatus.LICENSE_UNCONFIRMED,
    "yfinance": DistributionStatus.INTERNAL_ONLY,
    "FinMind": DistributionStatus.LICENSE_UNCONFIRMED,
    "TWSE": DistributionStatus.LICENSE_UNCONFIRMED,
    "TPEx": DistributionStatus.LICENSE_UNCONFIRMED,
    "Shioaji": DistributionStatus.LICENSE_UNCONFIRMED,
}

LICENSE_NOTES: Dict[str, str] = {
    "Fugle": "使用規範禁止傳送予第三人；已請使用者詢問企業／多人展示授權（2026-10-07）",
    "yfinance": "非官方套件；Yahoo 資料以個人、非商業用途為原則；只作內部驗證",
    "FinMind": "授權條款未查",
    "TWSE": "官方資料不等於可再散布；需逐資料集確認",
    "TPEx": "官方資料不等於可再散布；需逐資料集確認",
    "Shioaji": "券商下單用 API；交易所「不得傳送予第三人」規範同樣適用；未接入",
}


def status_of(source_name: str) -> DistributionStatus:
    """沒登記的來源一律當作 BLOCKED（寧可擋錯，不可漏放）。"""
    return SOURCE_DISTRIBUTION.get(source_name, DistributionStatus.BLOCKED)


def can_display(source_name: str, viewer: ViewerScope) -> bool:
    st = status_of(source_name)
    if st == DistributionStatus.BLOCKED:
        return False
    if viewer == ViewerScope.OWNER:
        return True
    return st == DistributionStatus.EXTERNAL_ALLOWED


def blocked_message(source_name: str) -> str:
    return f"這項資料（{source_name}）目前尚未取得對外顯示授權，只有網站擁有者可以看到。"


# ── 顯示守門（以資料區塊為最小封鎖單位）──────────────────────────
@dataclass
class BlockRecord:
    """被擋下的紀錄（給後台查「為什麼某頁沒有行情」）。"""
    section: str
    blocked_source: str
    distribution_status: str
    viewer_scope: str
    feature: str
    timestamp: datetime
    reason: str


class BlockAudit:
    def __init__(self, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc), limit: int = 500):
        self._now, self._limit = now, limit
        self.records: List[BlockRecord] = []

    def add(self, section: str, source: str, viewer: ViewerScope, feature: str) -> BlockRecord:
        r = BlockRecord(section, source, status_of(source).value, viewer.value, feature, self._now(),
                        blocked_message(source))
        self.records.append(r)
        del self.records[:-self._limit]
        return r


def filter_displayable_sections(sections: Iterable[Any], viewer: ViewerScope, feature: str = "",
                                audit: Optional[BlockAudit] = None) -> Tuple[List[Any], List[Tuple[Any, str]]]:
    """每個資料區塊（需有 name、source_name）各自判斷：可顯示的放第一個清單，
    被擋的放第二個清單並附白話原因。不會因為一個區塊未授權就把整頁合法資料都封掉。"""
    shown, blocked = [], []
    for sec in sections:
        if can_display(sec.source_name, viewer):
            shown.append(sec)
        else:
            blocked.append((sec, blocked_message(sec.source_name)))
            if audit is not None:
                audit.add(getattr(sec, "name", "?"), sec.source_name, viewer, feature)
    return shown, blocked
