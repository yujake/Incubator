"""判据（对齐第 ②、⑧ 项）：实例身份与归属上屏 —— 每一格都能在后端找到出处。

## 两格

- `tasks.instance`（`identity.py` 的规范实例标签）：两个同角色实例一起干活时，只有
  这一列分得开谁是谁（改前页面只有「角色」，两个 F 都是 F）。
- `statements.created_by` → 读侧 `by_role` / `by_role_source`：这一行是谁写的。
  `by_role_source` 必须一起显示 —— 「盘上真记了」与「从一个邻近字段推出来的」在
  读的人眼里长得一样，而那正是这一格最容易变假话的地方。

## 判据

- 数据：一个带 `instance="F1"` / `seen_step=3` 的 tasks 行 ⇒ `/api/artifacts` 的
  `tasks[]` 逐字带这两格；一个 `created_by="agent-F-F1"` 的 statements 行 ⇒
  `/api/evidence` 的 `statements[]` 的 `by_role` 逐字等于它、`by_role_source` 是
  `created_by`；
- 类型：`TaskRow` / `StatementRow` 的声明里有这三格（单一来源 `readers.ts_fields()`）；
- 页面：Artifacts 的 tasks 表读 `instance` 与 `seen_step`，Evidence 的命题表把
  `by_role` / `by_role_source` 放进详情 / tooltip（2026-11-20 业主裁定：provenance
  不占主表列），空值写「—」而不是编一个角色名。

反真空：把 tasks 行的 `instance` 拿掉（空串）⇒ 页面那一列的渲染分支是「—」，
不是"角色名顶上去"；把 `created_by` 拿掉 ⇒ `by_role_source` 必须变化（不是永远
`created_by`）；把 Evidence 的详情读数拿掉 ⇒  authorship 判据必红。
"""
from __future__ import annotations

import json
import pathlib
import re

from agentflow import schema as S
from agentflow.webui import readers as RD

REPO = pathlib.Path(__file__).resolve().parents[1]
UI = REPO / "ui" / "src"
ARTIFACTS_TSX = UI / "pages" / "Artifacts.tsx"
EVIDENCE_TSX = UI / "pages" / "Evidence.tsx"
LEDGER_TS = UI / "statementLedger.ts"


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    task = {"task_id": "t-000001", "role": "F", "instance": "F1", "status": "running",
            "action": "prove", "kind": "", "seen_step": 3, "usd": 0.5,
            "started_at": "2026-11-19T00:00:00+08:00", "outcome": "ok"}
    stmt = {"stmt_id": "000001", "label": "x", "kind": "theorem", "status": "active",
            "created_by": "agent-F-F1", "created_at": "2026-11-19T00:00:00+08:00"}
    (tmp_path / "data" / "tasks.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": [task]}, ensure_ascii=False),
        encoding="utf-8")
    (tmp_path / "data" / "statements.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": [stmt]}, ensure_ascii=False),
        encoding="utf-8")
    return tmp_path


def test_the_instance_and_the_authorship_reach_the_face(tmp_path: pathlib.Path) -> None:
    """数据：instance / seen_step / created_by 三格逐字到读模型。"""
    root = _workspace(tmp_path)
    art = RD.artifacts_face(root)
    row = art["tasks"][0]
    assert row["instance"] == "F1", row
    assert row["seen_step"] == 3, row
    ev = RD.evidence_chain(root)
    stmt = ev["statements"][0]
    assert stmt["by_role"] == "agent-F-F1", stmt
    assert stmt["by_role_source"] == "created_by", stmt
    # 类型那一侧：这三格必须在声明里（前端才读得到，契约 C 也据此对齐）。
    fields = RD.ts_fields()
    for name in ("instance", "seen_step"):
        assert name in fields["TaskRow"], (name, fields["TaskRow"])
    for name in ("by_role", "by_role_source"):
        assert name in fields["StatementRow"], (name, fields["StatementRow"])


def test_a_row_without_an_instance_is_not_given_the_role_name(
        tmp_path: pathlib.Path) -> None:
    """负控（反真空）：instance 空 ⇒ 页面那一支写「—」，不拿 role 顶上去。"""
    root = _workspace(tmp_path)
    rows = json.loads((root / "data" / "tasks.json").read_text(encoding="utf-8"))
    rows["rows"][0]["instance"] = ""
    (root / "data" / "tasks.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    art = RD.artifacts_face(root)
    assert art["tasks"][0]["instance"] == "", art["tasks"][0]
    source = ARTIFACTS_TSX.read_text(encoding="utf-8")
    # 页面对空串的处置必须是「没有实例身份」，不是回落到角色名。
    assert "没有实例身份" in source, "页面没有写「没有实例身份」这一支"
    assert "r.role" not in _column_region(source, '"instance"'), "实例列回落到角色名"


def _column_region(source: str, needle: str) -> str:
    at = source.find(needle)
    if at < 0:
        return ""
    return source[at:at + 500]


def _page_problems(source: str, *, which: str) -> list[str]:
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    problems: list[str] = []
    if which == "artifacts":
        for needle in ('key: "instance"', 'key: "seen_step"'):
            if needle not in code:
                problems.append(f"Artifacts 的任务表没有 `{needle}`")
    else:
        # 2026-11-20（LEDGERUI ③）：provenance 不占主表列 —— 但「谁写的、来源是哪一格」
        # 仍必须在详情里读得到，所以判据从"有一列"改成"详情函数读了这两格，且主表没有那一列"。
        if 'key: "by_role"' in code:
            problems.append("Evidence 的命题表又把 provenance 摆回主表列了（应在详情里）")
        if "provenanceText(" not in code:
            problems.append("Evidence 的命题表没有 provenance 的详情读数")
        detail = LEDGER_TS.read_text(encoding="utf-8")
        for needle in ("row.by_role", "row.by_role_source"):
            if needle not in detail:
                problems.append(f"命题台账的详情没有读 `{needle}`")
    return problems


def test_the_pages_show_the_instance_and_the_author() -> None:
    """页面：实例列还在；命题表的 provenance 在详情里，并且负控必红。"""
    art = ARTIFACTS_TSX.read_text(encoding="utf-8")
    ev = EVIDENCE_TSX.read_text(encoding="utf-8")
    assert _page_problems(art, which="artifacts") == [], _page_problems(art, which="artifacts")
    assert _page_problems(ev, which="evidence") == [], _page_problems(ev, which="evidence")
    doctored = art.replace('key: "instance"', 'key: "role"', 1)
    assert _page_problems(doctored, which="artifacts"), "删掉实例列之后判据仍然绿"
    # 反真空：把命题表那一段详情读数拿掉 ⇒  authorship 判据必须报。
    stripped = ev.replace("provenanceText(", "cell(")
    assert _page_problems(stripped, which="evidence"), (
        "拿走 provenance 详情之后， authorship 判据仍然绿")
