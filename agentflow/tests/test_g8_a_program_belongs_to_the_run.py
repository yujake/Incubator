"""G8（业主 2026-10-27 裁定）：程序计时器的归属必须跟着"这一趟 run"走。

## 这一批防的是什么（真机读数）

`projects/mp3-r4/out/clock/state.json` 的 `tm-000001`：`note="toolchain._version_of"`、
`purpose="问 lean 的版本（等它回话）"`、`task_id="" role=""` —— 它是
`AgentLoop.run` 拼提示词那一步（`agent_loop.py:6740-6741`）起的，而 `calling_as`
只包 `registry.call`（`agent_loop.py:9616`）⇒ 装配期起程序取不到号。
后果不是"少一格读数"：`is_my_program`（`clock.py:2539`）把空归属一律判成
"不是我的" ⇒ `program.stop` 对整族落点结构性不可停。

## 判据与施工单逐条对应

- a) 装配期起的程序有号（复刻真机那条 `toolchain._version_of` 路径）；
- b) 工具路径逐字节不变（`calling_as` 那一路的值一个字都不改）；
- c) 线程对照：新线程不带 `copy_context()` ⇒ 空；带了 ⇒ 有号；
- d) AST 判据：新起线程必须带 `copy_context()`（不许再造出同形的空归属）；
- e) 反真空：`run_as` 打桩成空 ⇒ a 必须红；
- f) 错归属那一档：召唤线程用 `copy_context()` 起，父的 `calling_as` 会一起进去；
  子代理装配期起的程序必须记在子名下（`run_as` 赢），不许记成父的。
"""
from __future__ import annotations

import ast
import contextlib
import contextvars
import json
import threading
from pathlib import Path

import pytest

from agentflow import clock as C
from agentflow import toolchain as TB
from agentflow.conductor import calling_as

SRC = Path(__file__).resolve().parents[1] / "src" / "agentflow"


# ---------------------------------------------------------------- 夹具


@pytest.fixture()
def ws(tmp_path):
    """一个干净的工作区（时间账落在 `<ws>/out/clock/state.json`）。"""
    w = tmp_path / "ws"
    (w / "out" / "clock").mkdir(parents=True, exist_ok=True)
    C.reset_books()
    C.reset_programs()
    yield w
    C.reset_books()
    C.reset_programs()


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class _FakeSubprocess:
    """把 `_version_of` 里那一次 `subprocess.run` 换成不 spawn 的替身。"""

    calls: list[list[str]] = []

    def run(self, argv, **kwargs):  # noqa: ANN001, ARG002
        _FakeSubprocess.calls.append([str(a) for a in argv])
        return _FakeCompleted(0, "Lean (version 4.7.0, commit abc, Release)", "")


def _rows(ws: Path) -> list[dict]:
    path = ws / "out" / "clock" / "state.json"
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("timers") or [])


def _row_by_note(ws: Path, note: str) -> dict:
    rows = [r for r in _rows(ws) if str(r.get("note")) == note]
    assert rows, f"没有 note={note!r} 的落盘行（取证时真机就是这一格）"
    return rows[-1]


def _probe_lean(ws: Path, monkeypatch) -> None:
    """走真落点：`toolchain.probe_checkers` → `_version_of` → `clock.program_span`。

    不 spawn：`resolve_checker` 给出一个假路径，`subprocess` 换成替身
    （真机那一次 `where="toolchain._version_of"` 与这里逐字节同一条链）。
    """
    monkeypatch.setattr(
        TB, "resolve_checker",
        lambda name, env=None: {
            "name": name, "path": "C:/fake/lean.EXE" if name == "lean" else "",
            "source": "path" if name == "lean" else "", "problem": "", "looked": "PATH"})
    monkeypatch.setattr(TB, "subprocess", _FakeSubprocess())
    monkeypatch.setattr(C, "current_workspace", lambda: str(ws))
    TB.probe_checkers()


def _span(ws: Path, note: str) -> str:
    """起一条程序计时器（不 spawn），返回落盘那一行的 `task_id`。"""
    with C.program_span(program="lean.exe", argv=["lean.exe", "--version"],
                        workspace=str(ws), where=note, purpose="G8 判据") as span:
        assert span.timer is not None, "探针本身没登记上（判据坏了，不是实现坏了）"
    return str(_row_by_note(ws, note).get("task_id") or "")


# ---------------------------------------------------------------- a) 装配期有号


def test_a_assembly_time_program_carries_the_run_id(ws, monkeypatch):
    """装配期起的程序记在这一趟 run 名下（真机那个空号形状的反面）。"""
    with C.run_as("t-000001", "M"):
        _probe_lean(ws, monkeypatch)
    row = _row_by_note(ws, "toolchain._version_of")
    assert (row["task_id"], row["role"]) == ("t-000001", "M"), (
        "装配期起的程序仍然没有归属 —— `run_as` 没挂上，或 `_calling_identity` 没读它")


# ---------------------------------------------------------------- b) 工具路径不变


def test_b_the_tool_path_is_byte_identical(ws, monkeypatch):
    """工具路径（只有 `calling_as`）逐字节不变；run 里两者同号时也还是那个号。"""
    with calling_as("t-000900", "M"):          # 今天的样子：只有 calling_as
        _probe_lean(ws, monkeypatch)
    assert _row_by_note(ws, "toolchain._version_of")["task_id"] == "t-000900"

    with C.run_as("t-000777", "M"), calling_as("t-000777", "M"):   # 工具调用发生在 run 里
        _probe_lean(ws, monkeypatch)
    row = _row_by_note(ws, "toolchain._version_of")
    assert (row["task_id"], row["role"]) == ("t-000777", "M")


# ---------------------------------------------------------------- c) 线程对照


def test_c_a_plain_thread_loses_it_and_copy_context_keeps_it(ws):
    """同一段代码、同一条路径，差别只在起线程时有没有把执行上下文带过去。"""
    got: dict[str, str] = {}
    err: list[BaseException] = []

    def body(tag: str) -> None:
        try:
            got[tag] = _span(ws, f"g8.c.{tag}")
        except BaseException as exc:  # noqa: BLE001 - 线程里的异常要带回主线程
            err.append(exc)

    with C.run_as("t-000002", "A"):
        th = threading.Thread(target=body, args=("plain",), daemon=True)
        th.start()
        th.join(timeout=60)
        assert not th.is_alive(), "线程 60 秒没退（判据不许留活线程）"

        ctx = contextvars.copy_context()
        th2 = threading.Thread(target=ctx.run, args=(body, "ctx"), daemon=True)
        th2.start()
        th2.join(timeout=60)
        assert not th2.is_alive(), "线程 60 秒没退（判据不许留活线程）"

    assert not err, f"线程里抛了：{err!r}"
    assert got["plain"] == "", "新线程不带 copy_context() 竟然拿到了号 ⇒ ContextVar 语义变了"
    assert got["ctx"] == "t-000002", "带了 copy_context() 却没拿到号"


# ---------------------------------------------------------------- d) AST 判据


#: 允许"起线程但不带执行上下文"的落点，逐条登记（与 `clock.PROGRAM_ALLOWED_RAW` 同一档纪律）。
#:
#: 键是 `(仓内相对路径, 所在函数)`；值写"为什么这一处不需要"。
#: 空 why = 没想过（不许这么写）。
_THREAD_ALLOWLIST: dict[tuple[str, str], str] = {
    ("cli.py", "_with_watch"): (
        "`--watch` 那一下起的是 webui 的 serve_forever：它不跑 agent 循环（循环在主线 "
        "`_dispatch` 里），请求处理器按 request 里的 root 自己解析工作区。"
        "**这条豁免有条件**：将来若让网页线程直接跑 agent 动作（读 ContextVar 那种），"
        "这一格必须改成带 copy_context()，否则就是 G8 那个空归属的另一条来路"),
}

_SPAWN_ATTRS = ("Thread", "ThreadPoolExecutor")


def _thread_sites() -> list[tuple[str, int, str, bool]]:
    """扫出全部"新起线程"的调用点：`(相对路径, 行号, 所在函数, 那个函数里有没有 copy_context())`。

    判据按所在函数算，不按整个文件：一个文件里"这一处带了、那一处没带"正是要抓的形态。
    """
    out: list[tuple[str, int, str, bool]] = []
    for path in sorted(SRC.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in _SPAWN_ATTRS):
                continue
            holder: ast.AST | None = node
            scope: ast.AST | None = None
            while holder is not None:
                if isinstance(holder, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope = holder
                    break
                holder = parents.get(holder)
            qual = f"{scope.name}" if scope is not None else "<module>"
            seg = ast.get_source_segment(source, scope) if scope is not None else source
            has_ctx = "copy_context" in (seg or "")
            out.append((path.relative_to(SRC).as_posix(), int(node.lineno), qual, has_ctx))
    return out


def test_d_every_new_thread_carries_the_context_or_is_registered():
    """新起线程必须带 `copy_context()`；不带就得在这张表里登记 why。"""
    sites = _thread_sites()
    # 反真空：扫不到任何一点 ⇒ 判据坏了（不是"没有线程"）
    assert len(sites) >= 4, f"只扫到 {len(sites)} 处起线程的调用，判据的覆盖面坏了"

    seen: set[tuple[str, str]] = set()
    problems: list[str] = []
    for rel, line, qual, has_ctx in sites:
        if has_ctx:
            continue
        if (rel, qual) in _THREAD_ALLOWLIST:
            seen.add((rel, qual))
            continue
        problems.append(f"{rel}:{line} 在 {qual}() 起线程，但那个函数里没有 copy_context()")
    assert not problems, (
        "有线程没带执行上下文（会造出与 G8 同形的空归属）：\n" + "\n".join(problems))

    dead = set(_THREAD_ALLOWLIST) - seen
    assert not dead, f"豁免表里这些条目已经对不上任何落点（表在腐烂）：{sorted(dead)}"
    for key, why in _THREAD_ALLOWLIST.items():
        assert str(why).strip(), f"豁免 {key} 没写 why"


# ---------------------------------------------------------------- e) 反真空


def test_e_stubbing_run_as_makes_a_go_red(ws, monkeypatch):
    """反真空：`run_as` 打桩成空 ⇒ 同一条路径必须回到空号（否则 a 是假绿）。"""
    monkeypatch.setattr(C, "run_as", lambda *a, **k: contextlib.nullcontext())
    with C.run_as("t-000001", "M"):
        _probe_lean(ws, monkeypatch)
    row = _row_by_note(ws, "toolchain._version_of")
    assert (row["task_id"], row["role"]) == ("", ""), (
        "把 run_as 打桩成空之后仍然有号 ⇒ 那个号不是 run_as 给的，a 条是假绿")


# ---------------------------------------------------------------- f) 错归属那一档


def test_f_run_as_wins_over_the_parent_calling_as_copied_into_a_child_thread(ws):
    """召唤线程用 `copy_context()` 起（`conductor.py:6152`），父的 `calling_as` 一起进去。

    这一条钉的是"错归属"那一档（比空归属更危险：它会放行 program.stop）：
    子代理装配期起的程序必须记在子名下，不是父的。
    """
    got: dict[str, tuple[str, str]] = {}
    err: list[BaseException] = []

    def child() -> None:
        try:
            # ① 刚进线程：继承来的就是父的号（这是事实，docstring 里写着）
            got["inherited"] = C._calling_identity()  # noqa: SLF001 - 判据读的就是这一格
            with C.run_as("t-000090", "D"):
                got["in_run"] = C._calling_identity()  # noqa: SLF001
                _span(ws, "g8.f.child")
        except BaseException as exc:  # noqa: BLE001
            err.append(exc)

    with calling_as("t-000001", "M"):
        ctx = contextvars.copy_context()
        th = threading.Thread(target=ctx.run, args=(child,), daemon=True)
        th.start()
        th.join(timeout=60)
        assert not th.is_alive(), "线程 60 秒没退（判据不许留活线程）"

    assert not err, f"子线程里抛了：{err!r}"
    assert got["inherited"] == ("t-000001", "M"), (
        "copy_context 没把父的 calling_as 带进去 —— 那这一条就没在测它想测的东西")
    assert got["in_run"] == ("t-000090", "D"), "run_as 没赢过继承来的 calling_as"
    assert _row_by_note(ws, "g8.f.child")["task_id"] == "t-000090", (
        "子代理装配期起的程序被记成了父的号（错归属：program.stop 会放行）")
