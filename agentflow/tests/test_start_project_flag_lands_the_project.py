"""判据：`start --project <名字>` 的落点就是 `<projects-dir>/<名字>`（2026-11-14 事故）。

## 事故读数（业主 2026-11-14）

    agentflow incubate start --task "…" --project octa-rehearsed-r2 \
        --budget-usd 2.35 --mode research --subagents

真机跑起来之后：

- 数据落在「仓库根」 `agentflow/data/`（这个目录「被 git 跟踪」）⇒ 15 个 tracked
  文件被写脏，靠人肉 `git checkout` 还原；
- `projects/octa-rehearsed-r2/` 「没有被创建」（上一趟的 `projects/octahedron-20261113/`
  是那样建的）；
- `--dry-run --json` 的 `project` 字段是 `{}`（空对象）—— 这就是预兆：旗标收下了，
  但没接上。

## 为什么这属于实现缺陷，而不是用法问题

1. `--project` 的 help 逐字写着「项目名（落在 `<projects-dir>/<名字>`）」，没有任何
   "只对 `--mode project` 有效"的限制；`docs/USER-GUIDE.md` §1 也把它列在「要跑什么」
   那一组里，与 `--mode` 平级。
2. 设计意图就写在同一段代码里：`_spec_of_start` 的 auto 分支自己写着
   「不这么做的话，`--mode research --project p` 会把十角色循环跑在工作区根上、
   产物落在项目外面」—— 只是显式 `--mode research` 那一支在它「之前」就 `return` 了，
   而 `_target_workspace` 又按 `spec.mode` 把 role 那一档挡在门外。
3. 同一个入口的 auto 档（不写 `--mode`）对同名旗标是生效的：`--project P` 会落在
   `projects/P`。同一个旗标在同一个入口的两种写法下语义不同，是「实现」不一致。
4. 静默忽略比拒绝更坏：屏幕上没有一行说"`--project` 这一趟没生效"，于是用户按
   "它会落在项目里"去读后面所有输出，伤害直到 `git status` 才出现。

## 三条判据（红 → 绿）

| 判据 | 改前（红） | 改后（绿） |
|---|---|---|
| ① 试运行 JSON 的 `project` 非空且指向 `projects/<名字>` | `{}` | 项目卡 + `will_create` |
| ② 离线真起一次 ⇒ 数据落在 `projects/<名字>/data/` | 落在工作区根 | 落在项目里 |
| ③ 同一趟里「根 `data/` 逐字节不变」 | 15 个 tracked 文件被写脏 | 一个字节不变 |

第 ④ 条反真空（`test_without_the_project_wiring_...`）：把"落点接到 project"那一手
拆掉，②③ 必红 —— 它证明这两条不是恒真。
"""
from __future__ import annotations

import dataclasses
import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from agentflow import cli
from agentflow.llmseam import LlmSeam
from agentflow.tokenmeter import TokenMeter


class _ScriptedGateway:
    """照剧本回答的替身模型（与真模型同接口；`price=(0.0, 0.0)` ⇒ 不花钱）。"""

    spec = type("_Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw) -> object:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("_Reply", (), {"ok": True, "text": text, "tokens_in": 5, "tokens_out": 5,
                                   "error_detail": "", "error_kind": ""})()


def _fake_seam_factory(role: str, *, root: Path, sid: str | None, usd_budget: float | None,
                       store: object = None) -> LlmSeam:
    """离线假模型缝：M 一步收工（不召唤任何人），所以这一趟只写工作区与台账。"""
    gw = _ScriptedGateway([json.dumps({"final": "交付：完成", "evidence": []},
                                      ensure_ascii=False)])
    return LlmSeam(role=role, session_root=root, gateway=gw, price=(0.0, 0.0), sid=sid,
                   usd_budget=usd_budget,
                   meter=(TokenMeter(store) if store is not None else None))


def _digest_tree(path: Path) -> dict[str, str]:
    """目录里每个文件的 sha256（目录不在 ⇒ `{}`；用来证明"一个字节都没变"）。"""
    if not path.is_dir():
        return {}
    return {str(p.relative_to(path)).replace("\\", "/"):
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob("*")) if p.is_file()}


def _run(argv: list[str]) -> tuple[int, str, str]:
    """跑一次 `cli.main(["start", *argv])`，收回 (退出码, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["start", *argv])
    except SystemExit as exc:
        code = int(exc.code or 0)
    return int(code), out.getvalue(), err.getvalue()


def _research_argv(root: Path, project: str) -> list[str]:
    """事故命令的离线形态（`--mode research` 就是那条命令；`--subagents` 是它的缺省）。"""
    return ["start", "--mode", "research", "--project", project, "--root", str(root),
            "--task", "把这件事办掉", "--max-steps", "3"]


# ============================================================ ① 试运行 JSON
def test_the_dry_run_json_points_at_the_named_project(tmp_path: Path) -> None:
    """①：`start --mode research --project P --dry-run --json` 的 `project` 非空且指向 P。"""
    ws = tmp_path / "ws"
    code, out, err = _run(["--task", "t", "--project", "p1", "--root", str(ws),
                           "--mode", "research", "--dry-run", "--json"])
    assert code == 0, (code, out, err)
    doc = json.loads(out)
    assert doc["project"], f"`project` 还是空对象：{doc}"
    assert doc["project"]["name"] == "p1", doc
    assert Path(doc["project"]["path"]) == ws / "projects" / "p1", doc
    assert Path(doc["workspace"]) == ws / "projects" / "p1", doc
    # 预检仍然一个字节都不写（C1 的承诺不许因为这一修而让步）
    assert not (ws / "projects" / "p1").exists(), "试运行把项目文件夹建出来了"


# ============================================================ ②③ 离线真起一趟
def test_the_offline_research_run_writes_into_the_project_not_the_root(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """②③：假模型缝真跑一次 ⇒ 数据落进 `projects/<名字>/data/`，根 `data/` 逐字节不变。"""
    monkeypatch.setattr(cli, "_agent_seam_factory", _fake_seam_factory)
    ws = tmp_path / "ws"
    root_data = ws / "data"
    root_data.mkdir(parents=True)
    # 根 `data/` 是"被 git 跟踪的那一份"的替身：任何一字节的改动都要被看见。
    (root_data / "tasks.json").write_bytes(b'{"tracked": true}\n')
    (root_data / "counters.json").write_bytes(b'{"tracked": "counter"}\n')
    before = _digest_tree(root_data)
    assert before, "反真空：根的 data/ 没造出来，这一条就失去了对象"

    code = cli.main(_research_argv(ws, "p2"))
    assert code == 0, f"离线研究循环没跑通（退出码 {code}）"

    project = ws / "projects" / "p2"
    assert (project / "data" / "tasks.json").is_file(), list(ws.rglob("*"))
    assert (project / "data" / "counters.json").is_file(), list(project.rglob("*"))
    # 运行记录也跟落点走（此前它从进程命令行 `--root` 猜，会写进外层工作区）
    assert list((project / "runs").glob("cache-active-*.json")), list(project.rglob("*"))
    assert _digest_tree(root_data) == before, "根 data/ 被写脏了 —— 这正是 2026-11-14 的伤害面"


# ============================================================ ④ 反真空
def test_without_the_project_wiring_the_same_run_would_dirty_the_root(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 反真空：把"落点接到 project"那一手拆掉 ⇒ 同一趟就写进根 `data/`（②③ 必红）。

    这不是在测替身，而是证明 ②③ 的红/绿「只由那一手决定」：`_spec_of_start` 若不把
    `args.root` 指到项目、也不把 `project_name` 带进 `RunSpec`，落点就退回工作区根
    —— 业主 2026-11-14 看到的就是这个状态的机器读数。
    """
    monkeypatch.setattr(cli, "_agent_seam_factory", _fake_seam_factory)
    real = cli._spec_of_start
    ws = tmp_path / "ws"

    def _unwired(args):
        spec, problem = real(args)
        if spec is None:
            return spec, problem
        args.root = str(ws)  # 拆掉"args.root = 项目路径"那一手
        return dataclasses.replace(spec, root=None, project_name=None), problem

    monkeypatch.setattr(cli, "_spec_of_start", _unwired)
    root_data = ws / "data"
    root_data.mkdir(parents=True)
    (root_data / "tasks.json").write_bytes(b'{"tracked": true}\n')
    before = _digest_tree(root_data)

    # 退出码不重要（这一趟的收工门会因为那份假的根台账记 final_refused）—— 这一条
    # 问的是"字节写到哪去了"，不是"这一趟跑得漂亮"。
    cli.main(_research_argv(ws, "p2"))
    assert not (ws / "projects" / "p2" / "data" / "tasks.json").is_file(), \
        "拆掉落点接线之后仍然落进了项目 —— 说明 ② 不是被那一手决定的（判据真空）"
    assert _digest_tree(root_data) != before, \
        "拆掉落点接线之后根 data/ 竟然没变 —— 说明 ③ 抓不到这类写（判据真空）"


# ============================================================ 用不上的旗标
def test_a_flag_this_mode_cannot_use_is_refused_by_name(tmp_path: Path) -> None:
    """`--mode research` 收下 `--out`（只对 topic 有用）⇒ 退出码 2 并点名，不是静默跑。"""
    ws = tmp_path / "ws"
    code, out, err = _run(["--task", "t", "--mode", "research", "--out", str(tmp_path / "o"),
                           "--root", str(ws), "--dry-run"])
    text = out + err
    assert code == 2, (code, text)
    assert "--out" in text and "--mode topic" in text, text
    assert "静默忽略" in text, text
    assert not ws.exists() or not list(ws.rglob("*")), f"拒收之后还写了字节：{list(ws.rglob('*'))}"


def test_the_same_flag_is_still_accepted_in_the_mode_that_uses_it(tmp_path: Path) -> None:
    """反面（反真空）：同一个 `--out` 在 `--mode topic` 下照旧能用 —— 拒收不是一刀切。"""
    ws = tmp_path / "ws"
    code, out, err = _run(["--task", "t", "--mode", "topic", "--out", str(tmp_path / "o"),
                           "--root", str(ws), "--dry-run", "--json"])
    assert code == 0, (code, out, err)
    assert json.loads(out)["mode"] == "topic"


# ============================================================ auto 的 research 推断
def _workspace(path: Path, tasks: list[dict]) -> None:
    """造一个"已初始化的工作区"：`classify` 认 `data/counters.json`，台账是 `data/tasks.json`。"""
    (path / "data").mkdir(parents=True)
    (path / "data" / "counters.json").write_text('{"schema_version": 2, "counters": {}}',
                                                 encoding="utf-8")
    (path / "data" / "tasks.json").write_text(
        json.dumps({"schema_version": 2, "rows": tasks}, ensure_ascii=False), encoding="utf-8")


def test_auto_infers_research_from_the_real_ledger_file(tmp_path: Path) -> None:
    """`--mode auto` 的 research 那一档读的是 `data/tasks.json`（表的真身），不是 `.jsonl`。

    改前 `_has_ledger` 读 `data/tasks.jsonl` —— 那个名字在任何工作区里都不存在（`Store`
    写的是 `tasks.json`，`empty_table()` 的形状是 `{"schema_version", "rows"}`），于是
    这一格恒为"没有台账"，一个已经有 109 行台账的项目会被当成 warm 只跑一趟主题。
    这一条钉两半：有行 ⇒ research；没有行 ⇒ 仍然是 warm 的项目那一档。
    """
    ws = tmp_path / "ws"
    _workspace(ws / "projects" / "used", [{"task_id": "t-000001"}])
    _workspace(ws / "projects" / "fresh", [])
    code, out, err = _run(["--task", "t", "--project", "used", "--root", str(ws),
                           "--dry-run", "--json"])
    assert code == 0, (code, out, err)
    doc = json.loads(out)
    assert doc["mode"] == "role", doc
    assert Path(doc["workspace"]) == ws / "projects" / "used", doc

    code, out, err = _run(["--task", "t", "--project", "fresh", "--root", str(ws),
                           "--dry-run", "--json"])
    assert code == 0, (code, out, err)
    assert json.loads(out)["mode"] == "project", out
