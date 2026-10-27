# -*- coding: utf-8 -*-
"""判据（G4）：停机开关也要能杀程序 —— 优雅停是提醒，强停是强杀。

业主原话（唯一权威，逐字）：

    停机开关也要能杀程序（优雅停是提醒，强停是强杀）

背景（真机读数）：昨晚机器上跑出 15 个野 python 进程（智能体起的"研究程序"），停机开关
只让代理收工 —— 那些程序继续跑、把 CPU 打满。

## 改前红在哪（逐条对得上下面六条）

- `stopctl.stop_programs` 不存在（第 1/2/3/4/5/6 条 `AttributeError`）；
- `agent_loop._user_stop_reason` 判定"该停"之后直接返回理由码，程序那一侧一个字节都
  没碰过 —— 于是第 7 条（整趟集成）红：开关落下后那 1 个程序照跑；
- `stopctl.consume_stop` 的历史行只有"停了哪一趟"，没有"这一停对程序做了什么"。

## 六条判据 + 一条集成

a) `test_a_force_kills_both_programs_and_names_them`：强停 ⇒ 两个 pid 真的没了、程序行
   `killed`、读数逐项点名两个；
b) `test_b_graceful_stop_reminds_then_names_it_without_killing`（不理会）与
   `test_b2_graceful_stop_lets_a_cooperating_program_finish_itself`（合作）：
   优雅停先提醒、宽限内绝不 SIGKILL，超时只点名"宽限内没退出"；
c) `test_c_graceful_stop_does_not_misfire_on_a_program_that_exits_by_itself`：1 秒自己
   退出的程序按自己的 `exited` 收口，读数不写"被停杀掉"；
d) `test_d_a_second_force_is_reported_as_already_exited`：同一趟投两次强停 ⇒ 第二次
   `already_exited`、不报错；
e) `test_e_an_unreadable_program_ledger_says_so_and_the_stop_still_works`：把
   `clock.programs` 打桩成抛 ⇒ 停机照旧生效，读数写"没查成"，不写"没有在跑的程序"；
f) `test_f_the_force_branch_is_what_kills_them`（反真空）：把"动手"那一步打桩掉 ⇒ a 必红。

## 两条集成（判据之外的接线，缺了它们上面六条可能只是"函数好用"）

- `test_the_running_loop_kills_programs_and_the_audit_carries_the_reading`：开关落到已经
  起好的程序上 ⇒ 跑着的那一趟在循环头把它们杀掉，读数进 `run.notes` 与
  `runs/stop-history.jsonl` 的那一笔审计（`programs` 那一格）；
- `test_the_masters_stop_tool_kills_programs_too`：M 调 `conductor.stop(force=true)` ⇒
  程序也被收掉（工具那条路不许绕开 G4）。

## 这一单真的起了进程（纪律）

每个夹具都在 `finally` 里 terminate -> kill -> wait；子进程另有一条自保：父进程一死
stdin 就 EOF，它自己退出（不靠父进程收尸）。绝不留一个睡着的进程。
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import subprocess
import sys
from typing import Any, Iterator

import pytest

from agentflow import clock as C
from agentflow import stopctl
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

#: 判据里的"研究程序"：`ready` 之后等三档之一
#:
#: - `ignore`：睡到 stdin EOF 或 120 秒（不理会任何提醒）；
#: - `cooperate`：每 0.05 秒看一次停机开关；看见就写标记（带它自己的时间戳）并
#:   用自己的退出码 42 退出 —— 这就是"被提醒之后自己收尾"的证据：强杀不会留下标记；
#: - `short`：1 秒后自己退出（退出码 0），用来钉"优雅停不许误杀自己会退的程序"。
#:
#: stdin 那条线程是防孤儿：父进程一死 stdin 就 EOF，子进程自己退出。
CHILD_SRC = r"""
import json, os, sys, threading, time
mode, mark, switch = sys.argv[1], sys.argv[2], sys.argv[3]
def watch_stdin():
    try:
        while True:
            if not sys.stdin.readline():
                break
    except Exception:
        pass
    os._exit(41)
threading.Thread(target=watch_stdin, daemon=True).start()
sys.stdout.write("ready\n")
sys.stdout.flush()
t0 = time.time()
while time.time() - t0 < 120:
    if mode == "short" and (time.time() - t0) >= 1.0:
        os._exit(0)
    if mode == "cooperate" and os.path.exists(switch):
        with open(mark, "w", encoding="utf-8") as fh:
            json.dump({"at": time.time(), "saw": "stop_switch"}, fh, ensure_ascii=False)
        os._exit(42)
    time.sleep(0.05)
os._exit(0)
"""


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    Store(ws).init()
    return ws


def _spawn(ws: pathlib.Path, mode: str, tag: str) -> subprocess.Popen:
    """起一个"研究程序"（stdin 管道留着，父进程一死它就自己退）。"""
    mark = str(ws / f"{tag}.mark.json")
    return subprocess.Popen(
        [sys.executable, "-u", "-c", CHILD_SRC, mode, mark, str(ws / ".agentflow-stop")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")


def _ready(proc: subprocess.Popen) -> None:
    """等子进程说 ready（它已经在跑，才登记 pid —— 与真机同一条次序）。"""
    line = (proc.stdout.readline() if proc.stdout else "").strip()
    assert line == "ready", f"子进程没起来（读到 {line!r}）"


def _reap(proc: subprocess.Popen) -> None:
    """收尸：先 terminate、再 kill、再 wait（绝不留睡着的进程）。"""
    try:
        if proc.stdin:
            with contextlib.suppress(Exception):
                proc.stdin.close()
        if proc.poll() is None:
            with contextlib.suppress(Exception):
                proc.terminate()
                proc.wait(timeout=3)
            if proc.poll() is None:
                with contextlib.suppress(Exception):
                    proc.kill()
                    proc.wait(timeout=3)
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()


@contextlib.contextmanager
def _programs(ws: pathlib.Path, specs: "list[tuple[str, str]]",
              *, task_id: str = "") -> Iterator[list[dict[str, Any]]]:
    """起一批"研究程序"并各登记一条 `kind="program"` 的计时器；退出时全部收尸。"""
    procs: list[subprocess.Popen] = []
    rows: list[dict[str, Any]] = []
    try:
        for index, (mode, tag) in enumerate(specs):
            proc = _spawn(ws, mode, tag)
            procs.append(proc)
            _ready(proc)
            timer = C.start_program(ws, program="python",
                                    argv=[sys.executable, "-c", CHILD_SRC],
                                    where="tests.g4_stop_kills_programs",
                                    purpose=f"判据里的研究程序 {tag}",
                                    task_id=(task_id or f"t-g4-{index}"), role="E")
            C.attach_program_pid(ws, timer.timer_id, proc.pid)
            rows.append({"proc": proc, "timer_id": timer.timer_id, "pid": proc.pid})
        yield rows
    finally:
        for proc in procs:
            _reap(proc)


def _row(ws: pathlib.Path, timer_id: str) -> dict[str, Any]:
    """读账上那一行程序计时器（读不到就是判据自己坏了，不许静默）。"""
    for row in C.programs(ws)["rows"]:
        if str(row.get("timer_id")) == str(timer_id):
            return dict(row)
    raise AssertionError(f"账上没有 {timer_id} 这一行：{[r.get('timer_id') for r in C.programs(ws)['rows']]}")


def _entry(reading: dict[str, Any], timer_id: str) -> dict[str, Any]:
    for entry in reading.get("programs") or ():
        if str(entry.get("timer_id")) == str(timer_id):
            return dict(entry)
    raise AssertionError(f"读数里没有 {timer_id} 这一条：{reading.get('programs')}")


# ---------------------------------------------------------------- a) 强停：真的杀
def test_a_force_kills_both_programs_and_names_them(tmp_path: pathlib.Path):
    """a) 起 2 个"睡 60 秒"的程序 + 投 force ⇒ 两个 pid 真的没了、程序行 killed、点名两个。

    改前：停机只让代理收工，程序照跑（本判据改前红在 `stop_programs` 不存在）。
    """
    ws = _ws(tmp_path)
    with _programs(ws, [("ignore", "force-a"), ("ignore", "force-b")]) as rows:
        stopctl.request_stop(ws, reason="user", by="user", force=True)
        got = stopctl.stop_programs(ws, force=True, why="user")

        assert got["checked"] is True, got
        assert got["killed"] == 2, got["programs"]
        for row in rows:
            assert stopctl.alive(int(row["pid"])) is False, f"pid {row['pid']} 还活着（强停没杀掉）"
            assert _entry(got, row["timer_id"])["status"] == "killed", got["programs"]
            line = _row(ws, row["timer_id"])
            assert line["state"] == "fired" and line["outcome"] == "killed", line
        notice = str(got["notice"])
        assert "强停杀了 2 个程序" in notice, notice
        for row in rows:
            assert f"pid {row['pid']}" in notice, f"读数没点名 pid {row['pid']}：{notice}"


# ---------------------------------------------------------------- b) 优雅停：提醒 + 宽限
def test_b_graceful_stop_reminds_then_names_it_without_killing(tmp_path: pathlib.Path):
    """b) 起 1 个"睡 60 秒"且不理会的程序 + 投 stop ⇒ 宽限后点名"仍在跑"，绝不杀。

    "不许在宽限内被 SIGKILL 掉"的证据：宽限窗口结束时它还活着（`alive is True`），
    账上那一行仍然是 `pending`（优雅停不改行 —— 收口归等它的那一趟）。
    """
    ws = _ws(tmp_path)
    with _programs(ws, [("ignore", "grace-ignore")]) as rows:
        row = rows[0]
        stopctl.request_stop(ws, reason="user", by="user")
        got = stopctl.stop_programs(ws, force=False, grace_sec=1.0)

        assert got["checked"] is True, got
        assert got["killed"] == 0, "优雅停一上来就强杀了（那会丢掉跑了一半的结果文件）"
        assert got["still_running"] == 1, got["programs"]
        assert stopctl.alive(int(row["pid"])) is True, "宽限内它被杀了（优雅停不许强杀）"
        entry = _entry(got, row["timer_id"])
        assert entry["status"] == "still_running", entry
        assert "宽限内没退出" in str(entry["note"]), entry
        # 提醒那一刀有没有真的发出去：读数必须给答案（Windows 上没有可发的请停信号，
        # 那一档的"优雅"由宽限窗口承担 —— 见 clock._terminate_pid 的实测）。
        assert isinstance(entry["knife"].get("sent"), bool), entry["knife"]
        notice = str(got["notice"])
        assert "宽限内没退出" in notice and "没杀它们" in notice, notice
        assert f"pid {row['pid']}" in notice, notice
        assert _row(ws, row["timer_id"])["state"] == "pending", "优雅停不许替等它的那一趟收口"


def test_b2_graceful_stop_lets_a_cooperating_program_finish_itself(tmp_path: pathlib.Path):
    """b2) 合作的程序：看见开关就写标记、用自己的退出码 42 退出（证明不是被 kill 的）。

    证据三样：① 它自己写的时间戳标记；② 它自己的退出码 42（kill 会留下 1/-9 那一类）；
    ③ 读数写"在宽限内自己退出了"且 `killed == 0`。
    """
    ws = _ws(tmp_path)
    with _programs(ws, [("cooperate", "grace-coop")]) as rows:
        row = rows[0]
        proc: subprocess.Popen = row["proc"]
        stopctl.request_stop(ws, reason="user", by="user")
        got = stopctl.stop_programs(ws, force=False, grace_sec=3.0)

        assert got["killed"] == 0, got["programs"]
        entry = _entry(got, row["timer_id"])
        assert entry["status"] == "exited_in_grace", entry
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        assert proc.returncode == 42, f"它没走自己的收尾（退出码 {proc.returncode}）"
        mark = ws / "grace-coop.mark.json"
        assert mark.is_file(), "它没留下自己写的时间戳（那就不是'被提醒之后自己收尾'）"
        payload = json.loads(mark.read_text(encoding="utf-8"))
        assert payload.get("saw") == "stop_switch" and payload.get("at"), payload
        assert "自己退出了" in str(got["notice"]), got["notice"]


# ---------------------------------------------------------------- c) 优雅停不许误杀
def test_c_graceful_stop_does_not_misfire_on_a_program_that_exits_by_itself(
        tmp_path: pathlib.Path):
    """c) 1 秒就退出的程序 + 投 stop ⇒ 按自己的 `exited` 收口，读数不写"被停杀掉"。"""
    ws = _ws(tmp_path)
    with _programs(ws, [("short", "grace-short")]) as rows:
        row = rows[0]
        proc: subprocess.Popen = row["proc"]
        stopctl.request_stop(ws, reason="user", by="user")
        got = stopctl.stop_programs(ws, force=False, grace_sec=3.0)

        assert got["killed"] == 0, got["programs"]
        notice = str(got["notice"])
        assert "强停杀了" not in notice and "被停杀掉" not in notice, notice
        # 优雅停不替等它的那一趟收口：那一行还是 pending，由"等它的那一趟"按自己的
        # 结局收口 —— 这里就扮演那一趟（与 program_span 出作用域时同一动作）。
        assert _row(ws, row["timer_id"])["state"] == "pending"
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        assert proc.returncode == 0, f"它自己退出的码应该是 0，读到 {proc.returncode}"
        C.finish_program(ws, row["timer_id"], outcome="exited", exit_code=0)
        line = _row(ws, row["timer_id"])
        assert line["state"] == "fired" and line["outcome"] == "exited", line


# ---------------------------------------------------------------- d) 幂等
def test_d_a_second_force_is_reported_as_already_exited(tmp_path: pathlib.Path):
    """d) 同一趟里投两次 force ⇒ 第二次 `already_exited`，不报错。"""
    ws = _ws(tmp_path)
    with _programs(ws, [("ignore", "idem-a"), ("ignore", "idem-b")]) as rows:
        stopctl.request_stop(ws, reason="user", by="user", force=True)
        first = stopctl.stop_programs(ws, force=True, why="user")
        assert first["killed"] == 2, first["programs"]

        second = stopctl.stop_programs(ws, force=True, why="user")
        assert second["checked"] is True, second
        assert second["killed"] == 0, second["programs"]
        for row in rows:
            entry = _entry(second, row["timer_id"])
            assert entry["status"] == "already_exited", entry
            assert "不是又杀成一次" in str(entry["note"]), entry
            assert stopctl.alive(int(row["pid"])) is False


# ---------------------------------------------------------------- e) 读不成
def test_e_an_unreadable_program_ledger_says_so_and_the_stop_still_works(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """e) `clock.programs` 抛 ⇒ 停机照旧生效（代理收工）+ 读数写"程序状态没查成"。"""
    ws = _ws(tmp_path)

    def _boom(*_a: Any, **_k: Any):
        raise RuntimeError("簿记坏了（判据故意打桩）")

    monkeypatch.setattr(C, "programs", _boom)
    got = stopctl.stop_programs(ws, force=True, why="user")
    assert got["checked"] is False, got
    notice = str(got["notice"])
    assert "没查成" in notice, notice
    assert "没有在跑的程序" not in notice, f"把'没查成'折成了'没有在跑的程序'：{notice}"

    # 停机本身照旧生效：开关在盘上 ⇒ 这一趟第 0 步收工（`stop_reason` 仍是既有那一档）。
    stopctl.request_stop(ws, reason="user", by="user", force=True)
    run, gateway = _run_loop(ws)
    assert run.stop_reason == "force_stop", run.to_dict()
    assert any("没查成" in str(n) for n in run.notes), run.notes
    assert gateway["prompts"] == 0, "开关在跑之前就落了 ⇒ 一次模型调用都不该有"


# ---------------------------------------------------------------- f) 反真空
def test_f_the_force_branch_is_what_kills_them(tmp_path: pathlib.Path,
                                               monkeypatch: pytest.MonkeyPatch):
    """f) 把"强停杀程序"那一步打桩掉 ⇒ a 必红（程序还在跑）。

    这不是另一条判据，而是 a 的反真空控制：它钉住"程序真的没了"这个结论来自
    `_program_knife(force=True)` 这一步，而不是别处顺手做的。打桩之后两件事同时成立：
    ① a 的"pid 真的没了"必红（两个进程都还活着）；② 读数也不许跟着打桩说谎 ——
    它照实把它们记成 `failed`（"强停没能收掉"），不因为刀说"杀掉了"就写 `killed`。
    """
    ws = _ws(tmp_path)
    with _programs(ws, [("ignore", "vacuum-a"), ("ignore", "vacuum-b")]) as rows:
        monkeypatch.setattr(stopctl, "_program_knife",
                            lambda pid, *, force: {"killed": True, "sent": False,
                                                   "via": "stub", "why": ""})
        stopctl.request_stop(ws, reason="user", by="user", force=True)
        got = stopctl.stop_programs(ws, force=True, why="user", wait_sec=0.3)
        alive = [stopctl.alive(int(row["pid"])) for row in rows]
        assert alive == [True, True], "反真空控制失效了：打桩掉动手那一步，进程竟然真的没了"
        assert got["killed"] == 0, got["programs"]
        assert got["failed"] == 2, got["programs"]
        assert "强停没能收掉 2 个" in str(got["notice"]), got["notice"]


# ---------------------------------------------------------------- 集成：真的走到循环头
FINISH = json.dumps({"final": "收工"}, ensure_ascii=False)


class _Scripted:
    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        return type("Reply", (), {"ok": True, "text": FINISH, "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()


def _run_loop(ws: pathlib.Path):
    """跑一趟 M（零模型钱：开关在跑之前就落，第 0 步就收工）。"""
    st = Store(ws)
    gw = _Scripted()
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda role: LlmSeam(role=role, session_root=ws,
                                                           gateway=gw, price=(0.0, 0.0), sid="s"),
                         max_steps=5, store=st, sid="s")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    backend.registry = reg
    run = run_role("M", "用户强停", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role="M", session_root=ws, gateway=gw, price=(0.0, 0.0), sid="s"),
                   session_root=ws, workspace_root=str(ws), sid="s", max_steps=5,
                   from_env=False, stop_file=str(ws / ".agentflow-stop"))
    return run, {"prompts": len(gw.prompts)}


def test_the_running_loop_kills_programs_and_the_audit_carries_the_reading(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """集成：开关落到已经起好的程序上 ⇒ 循环头那一趟把它们杀掉，读数进 notes 与审计。"""
    ws = _ws(tmp_path)
    with _programs(ws, [("ignore", "loop-a")]) as rows:
        row = rows[0]
        stopctl.request_stop(ws, reason="user", by="user", force=True)
        run, _gw = _run_loop(ws)

        assert run.stop_reason == "force_stop", run.to_dict()
        assert stopctl.alive(int(row["pid"])) is False, "开关落下了，程序还在跑（G4 改前就是这个形态）"
        assert any("强停杀了 1 个程序" in str(n) for n in run.notes), run.notes
        history = stopctl.stop_history(ws)
        assert history, "停机那一笔审计没落"
        carried = history[-1].get("programs") or {}
        assert carried.get("killed") == 1, history[-1]
        assert carried.get("force") is True, history[-1]


# ---------------------------------------------------------------- 集成：M 的停机工具
STOP_TOOL_CALL = json.dumps({"tool": "conductor.stop", "args": {"force": True},
                             "why": "业主强停"}, ensure_ascii=False)


class _ToolScripted(_Scripted):
    def __init__(self, replies: "list[str]") -> None:
        super().__init__()
        self.replies = list(replies)

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()


def test_the_masters_stop_tool_kills_programs_too(tmp_path: pathlib.Path):
    """集成：M 调 `conductor.stop(force=true)` ⇒ 程序也被收掉（工具那条路不许绕开 G4）。"""
    ws = _ws(tmp_path)
    with _programs(ws, [("ignore", "tool-a")]) as rows:
        row = rows[0]
        st = Store(ws)
        gw = _ToolScripted([STOP_TOOL_CALL, FINISH])
        backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                             seam_factory=lambda role: LlmSeam(role=role, session_root=ws,
                                                               gateway=gw, price=(0.0, 0.0), sid="s"),
                             max_steps=5, store=st, sid="s")
        cond = Conductor(st, backend=backend)
        backend.conductor = cond
        reg = build_registry(store=st, conductor=cond).registry
        backend.registry = reg
        run_role("M", "业主强停", store=st, registry=reg, conductor=cond,
                 seam=LlmSeam(role="M", session_root=ws, gateway=gw, price=(0.0, 0.0), sid="s"),
                 session_root=ws, workspace_root=str(ws), sid="s", max_steps=5, from_env=False)
        assert stopctl.alive(int(row["pid"])) is False, (
            "M 的停机工具绕开了程序那一半：程序还在跑")
        assert _row(ws, row["timer_id"])["outcome"] == "killed"
