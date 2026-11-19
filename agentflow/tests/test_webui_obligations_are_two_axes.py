"""判据（对齐第 ⑥ 项）：三族义务的收件人读数 —— 收件实例与父台账号是两条轴。

## 为什么要有这一条

板项行有两种收件地址（`conductor.open_item` 的两格）：

- `parent_task_id`：父台账号 —— 名册收件箱（`open_items_of`）按它分；
- `instance`：收件实例 —— `obligations.recipient_reading` 判出来的落点，
  `Conductor.open_items_for(role, instance)` 按它取件。

父为空、只带收件实例的项**不挂在任何人的收件箱上**：真机 lp-ball 的两条
`b-register@` 至今如此（`parent_task_id=None`），页面上一条都看不见。
`/api/obligations` 就是把这两条轴分开摆出来的只读面，三族分别是
`b-register` / `v-resubmit` / `b-awake`（前缀逐字来自 `obligations` 三个常量）。

## 判据

- 三族的开项数 / 没人收（两轴都空）/ 已叫醒（b-register 的 `b-awake@` 行）逐条对；
- `item_state=done` 的项不许再出现（收口了就不是义务）；
- 非板项（`kind` 为空）不进来；
- `recipient_instance` 逐字是行上的 `instance`，`parent_task_id` 逐字是行上的父；
  `addressed` 三档（instance / parent / unowned）；
- 表不在盘上 ⇒ `not_applicable`（不是"没有义务"）；表读不出来 ⇒ `unreadable`；
- 页面：`components/Obligations.tsx` 读这两条轴，且**没有** post（网页不销号）。

反真空（两条负控）：把一条项标成 done ⇒ 它从计数里消失；给一条 unowned 的项填上
父台账号 ⇒ 它不再算"没人收"。
"""
from __future__ import annotations

import json
import pathlib
import re

from agentflow import obligations as OB
from agentflow import schema as S
from agentflow.webui import readers as RD

REPO = pathlib.Path(__file__).resolve().parents[1]
UI = REPO / "ui" / "src"
PANEL = UI / "components" / "Obligations.tsx"
LIVE = UI / "pages" / "Live.tsx"


def _task(task_id: str, key: str, *, kind: str = "notice", instance: str = "",
          parent: str = "", state: str = "queued", role: str = "B") -> dict:
    return {"task_id": task_id, "kind": kind, "role": role, "action": "notice",
            "status": "pending", "item_state": state, "item_close": "",
            "input_key": key, "instance": instance, "parent_task_id": parent,
            "started_at": "2026-11-19T00:00:00+08:00", "detail": f"{key} 的正文"}


def _ws(tmp_path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "tasks.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": rows}, ensure_ascii=False),
        encoding="utf-8")
    return tmp_path


def test_the_three_families_and_their_recipients(tmp_path: pathlib.Path) -> None:
    """正控：三族计数 / 没人收 / 叫醒行 / 两条轴逐条对。"""
    sha = "a" * 64
    other = "b" * 64
    rows = [
        _task("t-1", OB.register_key("000001", sha), instance="B1"),
        _task("t-2", OB.register_key("000003", other)),          # 两轴都空 ⇒ unowned
        _task("t-3", OB.register_wake_key("000001#p1", sha), state="done"),
        _task("t-4", OB.resubmit_key("000002", sha), parent="t-000009", role="V"),
        _task("t-5", OB.register_key("000004", sha), state="done"),  # 已收口
        _task("t-6", "irrelevant-key"),                          # 非板项
        {"task_id": "t-7", "kind": "", "role": "B", "status": "done"},  # 代理行
    ]
    root = _ws(tmp_path, rows)
    face = RD.obligations_face(root)
    assert face["tri"] == "computed", face
    counts = face["counts"]
    assert counts["b-register"] == {"open": 2, "unowned": 1, "summoned": 0}, counts
    assert counts["v-resubmit"] == {"open": 1, "unowned": 0, "summoned": 0}, counts
    assert counts["b-awake"] == {"open": 0, "unowned": 0, "summoned": 0}, counts
    by_key = {r["key"]: r for r in face["rows"]}
    assert by_key[OB.register_key("000001", sha)]["recipient_instance"] == "B1", by_key
    assert by_key[OB.register_key("000001", sha)]["addressed"] == "instance"
    assert by_key[OB.register_key("000003", other)]["addressed"] == "unowned"
    assert by_key[OB.resubmit_key("000002", sha)]["parent_task_id"] == "t-000009"
    assert by_key[OB.resubmit_key("000002", sha)]["addressed"] == "parent"
    assert OB.register_key("000004", sha) not in by_key, "已收口的项还在 rows 里"
    assert "irrelevant-key" not in by_key, "非三族的键进了义务表"
    assert face["addressing"]["by_instance"] == {"B1": 1}, face["addressing"]
    # `by_role` 是「没有收件实例」的那些（角色地址）：`open_items_for` 对它们照样取得到
    # （`instance == ""` 且 `role` 相等）—— 所以 unowned 那一条也在这一栏里。
    assert face["addressing"]["by_role"] == {"B": 1, "V": 1}, face["addressing"]
    assert face["addressing"]["unowned"] == 1, face["addressing"]
    rule = face["recipient_rule"]
    assert "instance" in rule and "parent_task_id" in rule, rule


def test_the_wake_row_is_counted_and_then_unmarked(tmp_path: pathlib.Path) -> None:
    """正控 + 反真空：b-awake 行在 ⇒ summoned+1；标成 done ⇒ 不再算叫醒。"""
    sha = "c" * 64
    key = OB.register_key("000010", sha)
    wake = OB.register_wake_key("000010#p1", sha)
    rows = [_task("t-1", key), _task("t-2", wake)]
    face = RD.obligations_face(_ws(tmp_path, rows))
    assert face["counts"]["b-register"]["summoned"] == 1, face["counts"]
    assert face["rows"][0]["wake_task_id"] == "t-2", face["rows"][0]
    # 负控：叫醒行收口 ⇒ 计数退回 0（不是永远 1）。
    rows[1]["item_state"] = "done"
    face2 = RD.obligations_face(_ws(tmp_path, rows))
    assert face2["counts"]["b-register"]["summoned"] == 0, face2["counts"]
    # 负控：给 unowned 那条填上父台账号 ⇒ 不再算"没人收"。
    rows[0]["parent_task_id"] = "t-000001"
    face3 = RD.obligations_face(_ws(tmp_path, rows))
    assert face3["counts"]["b-register"]["unowned"] == 0, face3["counts"]
    assert face3["rows"][0]["addressed"] == "parent", face3["rows"][0]


def test_missing_table_is_not_applicable_not_zero(tmp_path: pathlib.Path) -> None:
    """三态：表不在 ⇒ not_applicable（还没开过项），不是"三族都是 0 条"。"""
    face = RD.obligations_face(tmp_path)
    assert face["tri"] == "not_applicable", face["tri"]
    assert "还没有这张表" in face["reason"], face["reason"]
    assert face["families"] == [] and face["rows"] == [], face


def _panel_problems(text: str) -> list[str]:
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    problems: list[str] = []
    for needle in ("getObligations", "recipient_instance", "parent_task_id",
                   "unowned", "addressed"):
        if needle not in code:
            problems.append(f"Obligations 面板没有读 `{needle}`")
    if re.search(r"\bpost[A-Z]\w*\(", code):
        problems.append("义务面板里有写调用 —— 网页不许销号")
    return problems


def test_the_live_page_shows_the_obligations_panel() -> None:
    """页面：在飞页挂上义务面板；面板读两条轴且没有写调用。"""
    panel = PANEL.read_text(encoding="utf-8")
    assert _panel_problems(panel) == [], _panel_problems(panel)
    live = LIVE.read_text(encoding="utf-8")
    assert "ObligationsPanel" in live, "在飞页没有挂义务面板"
    # 负控：面板里出现一次写调用 ⇒ 必须报。
    assert _panel_problems(panel + "\npostStop({});\n"), "写调用负控没红"
