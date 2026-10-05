# -*- coding: utf-8 -*-
"""E 的实验子进程也装进作业对象（`draft/39` §3.21 五 I13 的真路径那一半）。

## 真机读数逼出来的这一条

实验脚本自己会起子进程（并行枚举、调用外部求解器），而停机时框架只 `_kill_child(proc)`
直接子进程 —— 那些孙子照旧跑（历史读数：包装进程被杀之后 python 子进程又跑了 12 分钟）。
`agent_e/core.py::_run_script` 现在把这条子进程装进作业对象（`assign_tree`），停机/超时时
先宽限再收，最后 `close(job)` ⇒ 关句柄就由 OS 收掉整棵传递树，不依赖 `taskkill` 能不能成功。

这一组钉三件事：

1. 停机那一路：脚本起了孙进程 ⇒ 叫停之后孙进程也没了，读数里 `process_tree="job"`；
2. 正常收工那一路：脚本自己起过孙进程并退出 ⇒ `close(job)` 把残留一并收掉（不留孤儿）；
3. 负控：作业对象用不了时读数如实写 `process_tree="kill_child"`（这条改动"只增不减"的证据）。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import threading
import time

import pytest

from agentflow import jobobject as JB
from agentflow.agent_e import AgentE
from agentflow.store import Store

pytestmark = pytest.mark.skipif(not JB.available(),
                                reason=f"作业对象用不了：{JB.unavailable_reason()}")

#: 一个"会自己起子进程"的实验脚本：孙进程把自己的 pid 写进工作区，然后两边都睡。
_SPAWNS = """
import pathlib, subprocess, sys, time
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
out = pathlib.Path("out"); out.mkdir(parents=True, exist_ok=True)
(out / "grandchild.pid").write_text(str(p.pid), encoding="utf-8")
print("REPRO_RESULT: " + '{"result": "inconclusive"}')
time.sleep(120)
"""


def _prepare(tmp_path: pathlib.Path) -> tuple[AgentE, pathlib.Path, pathlib.Path]:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    script = ws / "code" / "spawns.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_SPAWNS, encoding="utf-8")
    e = AgentE(st, config={"workspace_root": str(ws)}, workspace_root=ws)
    return e, ws, script


def _grandchild_pid(ws: pathlib.Path) -> int:
    f = ws / "out" / "grandchild.pid"
    for _ in range(100):
        if f.is_file() and f.read_text(encoding="utf-8").strip().isdigit():
            return int(f.read_text(encoding="utf-8").strip())
        time.sleep(0.2)
    return 0


def test_stopping_an_experiment_reaps_the_whole_tree(tmp_path: pathlib.Path):
    """停机那一路：叫停 ⇒ 实验脚本和它起的孙进程都被收掉，读数里记 `process_tree=job`。"""
    e, ws, script = _prepare(tmp_path)
    stop = ws / ".agentflow-stop"

    def later() -> None:
        time.sleep(1.5)
        stop.write_text("{}", encoding="utf-8")

    threading.Thread(target=later, daemon=True).start()
    got = e._run_script(script, timeout=60)
    grandchild = _grandchild_pid(ws)
    assert grandchild, "夹具失败：脚本没把孙进程的 pid 写出来"
    assert got.get("stopped_by_user") is True, got
    assert got.get("process_tree") == "job", got
    for _ in range(40):
        if not JB._alive(grandchild):
            break
        time.sleep(0.2)
    assert not JB._alive(grandchild), f"叫停之后孙进程 {grandchild} 还活着（I13 没生效）"


def test_a_finished_experiment_leaves_no_stragglers(tmp_path: pathlib.Path):
    """正常收工那一路：脚本自己起过子进程而脚本先退出 ⇒ `close(job)` 把残留一并收掉。"""
    e, ws, _script = _prepare(tmp_path)
    quick = ws / "code" / "quick.py"
    quick.write_text(
        "import subprocess, sys, time\n"
        # 孙进程不继承 stdout/stderr：继承的话父进程退出后管道仍然开着，
        # `communicate()` 会一直等到孙进程结束（那会让这一条读成"超时"而不是"跑完了"）
        # —— 这也是一条真机教训：起子进程时要显式给它 DEVNULL，否则停机会被拖住。
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],\n"
        "                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "print(p.pid)\n",                       # 孙进程的 pid 打到 stdout
        encoding="utf-8")
    got = e._run_script(quick, timeout=60)
    assert got.get("exit_code") == 0, got
    assert got.get("process_tree") == "job", got
    pid = int([ln for ln in str(got.get("stdout") or "").splitlines() if ln.strip().isdigit()][-1])
    for _ in range(40):
        if not JB._alive(pid):
            break
        time.sleep(0.2)
    assert not JB._alive(pid), f"脚本自己起的子进程 {pid} 成了孤儿"


def test_the_reading_says_which_route_was_used(tmp_path: pathlib.Path, monkeypatch):
    """负控：作业对象用不了 ⇒ 读数如实写 `kill_child`（"这条改动只增不减"的证据）。"""
    e, ws, _script = _prepare(tmp_path)
    monkeypatch.setattr(JB, "available", lambda: False)
    ok = ws / "code" / "ok.py"
    ok.write_text("print('done')\n", encoding="utf-8")
    got = e._run_script(ok, timeout=60)
    assert got.get("exit_code") == 0, got
    assert got.get("process_tree") == "kill_child", got
