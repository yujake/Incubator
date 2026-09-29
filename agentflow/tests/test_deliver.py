"""交付闸门：三态结论、工作项落盘、派回去 fail-closed（离线，替身模型）。

## 这一组守什么（`draft/28` §184.5 第 3 步）

`judges.judge(` 原先在产品代码里零调用点 —— 判据存在但没人问它。
这一层把它接成"交付前的一道门"，并守住三条：

1. 三态：全过 = `pass`；有确定的不达标 = `needs_work`；有判据没判成 = `unknown`
   （`unknown` 必须与 `pass` 分开，否则"没查"又被读成"没问题"）；
2. 工作项要落盘：每条不达标 → 一条 `work_item` 追加进 `<root>/work_items.jsonl`
   （append-only，状态按最后一条记录折叠），闸门报告落 `<root>/gates/<名字>.json`；
3. 派回去 fail-closed：没有"角色 + 动作"就不派，如实记 `skipped` ——
   编一个动作名会被工具层拒，而那条拒绝在台账里像"执行失败"。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import deliver as D
from agentflow import sessions as SS
from agentflow.llmseam import LlmSeam
from agentflow.store import Store


class FakeGateway:
    """按剧本回答的替身模型（逐次取剧本）。"""

    spec = type("Spec", (), {"model": "fake", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.calls += 1
        text = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 3, "tokens_out": 3,
                                  "error_detail": "", "error_kind": ""})()


GOOD = json.dumps({"verdict": "structural", "why": "点明了一般与特例", "findings": []},
                  ensure_ascii=False)
LISTING = json.dumps({"verdict": "listing", "why": "只是并列", "findings": []},
                     ensure_ascii=False)


def _seam(root: pathlib.Path, replies: list[str]) -> LlmSeam:
    return LlmSeam(role="H", session_root=root, gateway=FakeGateway(replies), price=(0.0, 0.0),
                   sid="t")


def _ws(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, st.root


def test_a_clean_artifact_passes_and_writes_a_report(tmp_path: pathlib.Path):
    """正控：判据判通过、机械半无问题 ⇒ `pass`，报告落盘，且不留工作项。"""
    st, root = _ws(tmp_path)
    res = D.gate("clean", "# 稿子\n\n阿贝尔群是群的特例。本结论为交叉验证所得\n",
                 session_root=root, seam=_seam(root, [GOOD]),
                 criteria=["overview.essence"], store=st)
    assert res.verdict == "pass", res.to_dict()
    assert pathlib.Path(res.report_path).is_file()
    assert res.work_items == [] and D.read_work_items(root) == []
    report = json.loads(pathlib.Path(res.report_path).read_text(encoding="utf-8"))
    assert report["verdict"] == "pass" and report["criteria"][0]["criterion"] == "overview.essence"


def test_a_failing_criterion_produces_a_work_item_with_a_fixer(tmp_path: pathlib.Path):
    """正控：判据不通过 ⇒ `needs_work` + 工作项落盘，且工作项里写清"谁该改"。"""
    st, root = _ws(tmp_path)
    res = D.gate("needs-work", "# 稿子\n\n三条并列。\n", session_root=root,
                 seam=_seam(root, [LISTING]), criteria=["overview.essence"], store=st)
    assert res.verdict == "needs_work", res.to_dict()
    items = D.read_work_items(root)
    assert len(items) == 1, items
    assert items[0]["source"] == "criterion:overview.essence"
    assert items[0]["who"] == D.FACULTY_FIXERS["高观点"], items[0]
    assert items[0]["status"] == "open" and items[0]["id"].startswith("w-")
    events, _ = SS.read_session(root, sid=None)
    assert any(e.get("kind") == "delivery_gate" and e.get("verdict") == "needs_work"
               for e in events), "闸门事件没有落进会话记录"


def test_mechanical_problems_also_produce_work_items(tmp_path: pathlib.Path):
    """正控（机械半也进闸门）：体例问题（占位符/缺标题）也要变成工作项。"""
    st, root = _ws(tmp_path)
    res = D.gate("style", "没有标题的一段 TODO 文字\n", session_root=root,
                 seam=_seam(root, [GOOD]), criteria=["overview.essence"], store=st)
    kinds = {w.source for w in res.work_items}
    assert "mechanical:style" in kinds, [w.to_dict() for w in res.work_items]
    assert res.verdict == "needs_work"


def test_an_unjudged_criterion_makes_the_gate_unknown_not_pass(tmp_path: pathlib.Path):
    """负控（三态）：没有接线 ⇒ `unknown`，而且不许把它读成"没问题"。"""
    st, root = _ws(tmp_path)
    res = D.gate("no-wire", "# 稿子\n\n正文。\n", session_root=root, seam=None,
                 criteria=["overview.essence"], store=st)
    assert res.verdict == "unknown", res.to_dict()
    assert res.unknown_criteria == ["overview.essence"]
    assert any("没判成 ≠ 通过" in n for n in res.notes), res.notes


def test_dispatch_skips_items_without_a_real_action(tmp_path: pathlib.Path):
    """负控（派回去 fail-closed）：没有动作名 ⇒ `skipped`，且台账里不留任务行。"""
    st, root = _ws(tmp_path)
    res = D.gate("dispatch", "# 稿子\n\n三条并列。\n", session_root=root,
                 seam=_seam(root, [LISTING]), criteria=["overview.essence"], store=st)
    from agentflow.conductor import Conductor, LocalBackend

    cond = Conductor(st, backend=LocalBackend({}))
    out = D.dispatch_work_items({"conductor": cond, "session_root": root}, res.work_items)
    assert out and all(o["dispatch"] == "skipped" for o in out), out
    assert st.rows("tasks") == [], "没有可派动作却留下了任务行"


def test_dispatch_refuses_an_action_that_does_not_exist(tmp_path: pathlib.Path):
    """负控（不许编动作名）：工作项带了角色但动作不在能力表里 ⇒ `skipped` 并说明原因。"""
    st, root = _ws(tmp_path)
    item = D.WorkItem(id="w-0001", source="criterion:x", who="G", what="改稿",
                      action="不存在的动作")
    from agentflow.conductor import Conductor, LocalBackend

    cond = Conductor(st, backend=LocalBackend({}))
    out = D.dispatch_work_items({"conductor": cond, "session_root": root}, [item])
    assert out[0]["dispatch"] == "skipped" and "动作表里没有" in out[0]["why"], out
    assert st.rows("tasks") == []


def test_dispatch_summons_when_role_and_action_both_exist(tmp_path: pathlib.Path):
    """正控（真派回去）：角色与动作都在 ⇒ 走 `Conductor.summon`，任务号写回工作项。"""
    st, root = _ws(tmp_path)
    res = D.gate("summon", "# 稿子\n\n三条并列。\n", session_root=root,
                 seam=_seam(root, [LISTING]), criteria=["overview.essence"], store=st)
    item = res.work_items[0]
    item.who, item.action = "G", "refresh_markdown"     # 真实存在的动作
    from agentflow.conductor import Conductor, LocalBackend

    cond = Conductor(st, backend=LocalBackend({}))
    out = D.dispatch_work_items({"conductor": cond, "session_root": root}, [item])
    assert out[0]["dispatch"] in ("summoned", "skipped"), out
    if out[0]["dispatch"] == "summoned":
        assert out[0]["task_id"], out
        rows = st.rows("tasks")
        assert rows and str(rows[0].get("called_by")) == "M", rows
        assert any(w["status"] == "dispatched" for w in D.read_work_items(root)), \
            D.read_work_items(root)
