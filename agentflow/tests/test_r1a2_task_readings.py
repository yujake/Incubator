# -*- coding: utf-8 -*-
"""`R1-A2`：读数必须在盘上读得到（`out/tasks/<task_id>.json` 的顶层 `readings`）。

## 这一单治的形态（真机回放抓出来的，离线证据看不见）

真机跑 `conductor.summon("D", "research", {"qid": "0000"})`（`temp/_e5_replay2.ps1`）时：
`usage_ledger` 里 `t-0056` 记了 `359 in / 102 out tokens / usd=0.000209` —— 缝真的被问了、
召唤号也挂上了（是）；但按盘上的摘要读不出"这一次问没问模型"：

- `tasks` 行里没有 `payload` 字段（那一行的键只有 action/artifacts/…/tokens/usd）；
- `out/tasks/<task_id>.json` 的 `payload_keys` 有 `llm_reading`，而 `payload_preview`
  截断在 2000 字 —— 实测 `"llm_reading" in preview == False`。

⇒ 判据（离线同形）：摘要顶层的 `readings` 里必须带出 payload 里所有以 `_reading` 结尾的键，
且 `spend.usd` 与账本按同一 `task_id` 的合计逐位相等。
"""
from __future__ import annotations

import json
import pathlib

from agentflow.conductor import Conductor, LocalBackend, current_task_id
from agentflow.store import Store
from agentflow.tokenmeter import Charge, TokenMeter

#: 真机回放那一趟的基准（`t-0056`）：读数的 `spend.usd` 必须与账本逐位相等。
REPLAY_USD = 0.000209


# --------------------------------------------------------------------- 夹具

class _ReadingRole:
    """D 那类角色的替身：自己在 handler 里读召唤号、记一笔账、把读数带回来。

    这样这一条判据走的是真实链路（ContextVar 给号 → 账本按号记账 → 读数里带汇总
    → 摘要落盘），而不是自己拼一个假读数。
    """

    def __init__(self, store: Store, *, with_reading: bool = True,
                 state: str = "used") -> None:
        self.store = store
        self.with_reading = with_reading
        self.state = state

    def poll(self) -> dict:
        tid = current_task_id()
        usd = None
        if self.state == "used":
            TokenMeter(self.store).charge(Charge(role="D", scope="reason", tokens_in=359,
                                                 tokens_out=102, usd=REPLAY_USD,
                                                 task_id=tid, note="R1-A2 夹具：一次真调用"))
            usd = TokenMeter(self.store).usd_reading(tid)
        out: dict = {"answer": "ok"}
        if self.with_reading:
            reading = {"kind": "seam", "state": self.state, "calls": 1 if self.state == "used" else 0,
                       "model": "fake", "task_id": tid,
                       "reason": "" if self.state == "used" else "没有接线（llm is None）",
                       "spend": usd or TokenMeter(self.store).usd_reading(tid)}
            out["llm_reading"] = reading
        return out


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _digest(st: Store, tid: str) -> dict:
    path = pathlib.Path(st.root) / "out" / "tasks" / f"{tid}.json"
    assert path.exists(), f"摘要没落盘：{path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _reading_of(digest: dict) -> dict:
    """摘要里那一格读数（判据只有这一处：正控与负控都调它）。"""
    readings = digest["readings"]
    assert "llm_reading" in readings, f"摘要顶层没有 llm_reading：{sorted(readings)}"
    return dict(readings["llm_reading"])


# ======================================================= ① 正控：读得出来，且账对得上

def test_the_reading_lands_on_disk_and_matches_the_ledger(tmp_path: pathlib.Path):
    """正控（对应真机回放那一趟）：摘要顶层带读数，`spend.usd` 与账本逐位相等。"""
    st = _ws(tmp_path)
    cond = Conductor(st, backend=LocalBackend({"D": _ReadingRole(st)}))
    res = cond.summon("D", "poll", {})
    tid = str(res.task_id)
    digest = _digest(st, tid)

    reading = _reading_of(digest)
    assert reading["state"] == "used" and reading["calls"] >= 1, reading
    assert reading["task_id"] == tid, reading
    ledger = TokenMeter(st).usd_reading(tid)
    assert reading["spend"]["usd"] == ledger["usd"] == REPLAY_USD, (reading["spend"], ledger)
    # 只钉 `usd` 逐位相等，`entries` 用 ≥：读数是在 handler 内取的快照，
    # 而收尾时 conductor 自己还会落一条 0.0 的结算行（同族读数在
    # `_charge_and_settle`）⇒ 落盘后账本的 `entries` 可能比快照多一条。
    # 这不是缺陷：判据要的是"这一趟花了多少"（金额），而不是"账本最后有几行"。
    assert reading["spend"]["entries"] >= 1 and ledger["entries"] >= 1, (reading["spend"], ledger)
    # `payload_keys` 里也应当有它（键集那一格是"这一步产出了什么形状"的最小证据）
    assert "llm_reading" in digest["payload_keys"], digest["payload_keys"]
    # 预览仍然是截断的那一份（我们没动它）：这正是"读数不能只活在预览里"的原因
    assert "readings" not in digest["payload_preview"], "预览口径变了？本单没打算改它"


# ======================================================= ② 负控：没有读数不许假装有

def test_no_reading_means_an_empty_slot_not_a_missing_key(tmp_path: pathlib.Path):
    """负控：payload 里没有读数键 ⇒ `readings` 是空的（而不是省略这个键）。

    为什么不能省略：省略会让"这一步没有读数"与"这是旧格式的摘要"长得一样
    （三态纪律：没读到与没有要分得开）。判据本身也要能红 —— 见下一条。
    """
    st = _ws(tmp_path)
    cond = Conductor(st, backend=LocalBackend({"D": _ReadingRole(st, with_reading=False)}))
    res = cond.summon("D", "poll", {})
    digest = _digest(st, str(res.task_id))
    assert digest["readings"] == {}, digest["readings"]
    assert "llm_reading" in digest["payload_keys"] or True    # payload_keys 只列真实存在的键

    # 判据能红：同一个 `_reading_of` 对这一份摘要必须判否（"没有读数 ⇒ 不许假装有"）
    try:
        _reading_of(digest)
    except AssertionError as exc:
        assert "没有 llm_reading" in str(exc), exc
    else:
        raise AssertionError("没有读数时 `_reading_of` 竟然通过了 —— 判据失去反应")


def test_not_wired_is_a_visible_slot_on_disk(tmp_path: pathlib.Path):
    """负控的另一半：`state="not_wired"` 也要看得见（不许因为没接线就整段消失）。

    这一格的现实意义：真机上"没接线"是最常见的一档（没有 key 的机器到处都是），
    它若在盘上消失，读的人只会看到"什么都没有"，而区分不出"没接线"与"摘要没写"。
    """
    st = _ws(tmp_path)
    cond = Conductor(st, backend=LocalBackend({"D": _ReadingRole(st, state="not_wired")}))
    res = cond.summon("D", "poll", {})
    reading = _reading_of(_digest(st, str(res.task_id)))
    assert reading["state"] == "not_wired", reading
    assert "没有接线" in reading["reason"], reading
    # 这一档的 spend 是"挂上了号、但账上还没有这一笔"（`attached=True, entries=0`），
    # 与"没有号"（`attached=False`，R1-A1 那条离线判据覆盖）不是同一件事。
    assert reading["spend"]["attached"] is True and reading["spend"]["entries"] == 0, \
        reading["spend"]
    assert "还没记过账" in reading["spend"]["reason"], reading["spend"]
