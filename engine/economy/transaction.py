"""Transaction Layer（v0.4.1 §7, §8, §60, §61, §62）。

统一资源交易接口：所有跨主体资源变化（trade / migration / group_share /
protest / work / investment）必须通过这里。提供 reserve/commit/release 的
预扣-结算-回滚三态，保证：
  - 一次行为只 commit once（§60）
  - 失败 rollback，禁止「交易失败但资源已扣」（§60）
  - 纯转移守恒，不凭空制造资源（§61）
  - 所有变化可记录（§62）
"""

from __future__ import annotations

from typing import Optional


def _actor_id(a) -> str:
    # 注意：不能写 getattr(a, "id", str(a)) —— str(a) 会被提前求值，
    # 每次都走 dataclass __repr__（格式化全部字段），是实测热点。
    aid = getattr(a, "id", None)
    return aid if aid is not None else str(a)


def can_afford(a, resource: str, amount: float) -> bool:
    """检查 available 是否足够（§8）。"""
    return a.resources.available(resource) >= amount


def reserve(a, resource: str, amount: float) -> bool:
    """预扣资源（行为执行前锁定成本）。不足返回 False（§8, §60）。"""
    return a.resources.reserve(resource, amount)


def commit(a, resource: str, amount: float, ledger=None, reason: str = "", tick: int = 0) -> None:
    """结算（行为执行成功后，§60 commit once）。"""
    a.resources.commit(resource, amount)
    if ledger is not None:
        ledger.record(source=_actor_id(a), target=None, resource=resource,
                      amount=-amount, reason=reason, tick=tick)


def release(a, resource: str, amount: float) -> None:
    """回滚（交易/行为失败时恢复，§60）。"""
    a.resources.release(resource, amount)


def transfer(src, dst, resource: str, amount: float,
             ledger=None, reason: str = "", tick: int = 0) -> bool:
    """跨主体资源转移（守恒 §61）：src 扣减、dst 增加，总量不变。"""
    if amount <= 0:
        return True
    if src.resources.available(resource) < amount:
        return False
    src.resources.add(resource, -amount)
    dst.resources.add(resource, amount)
    if ledger is not None:
        ledger.record(source=_actor_id(src), target=_actor_id(dst), resource=resource,
                      amount=amount, reason=reason, tick=tick)
    return True


class ResourceLedger:
    """资源流水账（§62）：记录 source/target/resource/amount/reason/tick。"""

    def __init__(self, max_entries: int = 2000) -> None:
        self.entries: list[dict] = []
        self.max_entries = max_entries

    def record(self, source: Optional[str], target: Optional[str],
               resource: str, amount: float, reason: str, tick: int) -> None:
        self.entries.append({
            "source": source,
            "target": target,
            "resource": resource,
            "amount": round(amount, 4),
            "reason": reason,
            "tick": tick,
        })
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]

    def recent(self, n: int = 100) -> list[dict]:
        return self.entries[-n:]

    def total_flow(self, resource: str) -> float:
        """该资源在账本中的净流量（应为 ≈0，纯转移守恒）。"""
        return sum(e["amount"] for e in self.entries if e["resource"] == resource)
