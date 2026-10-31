"""叫醒不许复制一个自己：目标正在跑 ⇒ 不另起同号循环（业主 2026-10-29）。

来由（实测，不是设想）：把兜底表接进 `run()` 之后，`test_timers_and_handoff_semantics`
超时挂死 —— 兜底表是在这一趟循环里被打掉的，这时 `wake_on_lifeline` 又去
`resume_dispatched`，于是同号起了第二个循环，两个自己互相喂事件。

三条判据：
  s1 目标正在跑 ⇒ 不叫（`started=False`，理由点名"它自己在跑"）
  s2 静默未销号 ⇒ 照旧叫（s1 不许把所有情况一起挡掉）
  s3 已销号 ⇒ 仍然叫不醒（P4 的边界不许被 s1 掩盖）
"""
from __future__ import annotations

import inspect
import pathlib

from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

TS = "2026-01-01T00:00:00+00:00"


def _ws(tmp_path: pathlib.Path) -> dict:
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    calls: list[tuple[str, dict]] = []

    def _runner(tid: str, **kw):
        calls.append((tid, dict(kw)))
        return {"started": True}

    cond.resume_runner = _runner
    owner = str(cond.open_top_level_run("M", "夹具：别叫我自己"))
    return {"root": root, "cond": cond, "owner": owner, "calls": calls}


def _child(cond: Conductor, parent: str, *, status: str) -> str:
    row = {"role": "D", "action": "write_report", "called_by": "M",
           "parent_task_id": parent, "depth": 2, "input_key": f"自我唤醒:{status}",
           "status": status, "outcome": ("ok" if status == "done" else None),
           "ended_at": (TS if status == "done" else None),
           "started_at": TS, "detail": "夹具子代理"}
    return str(cond._write_new_row(row, note="fixture:selfwake"))


def _fixture_problems(env: dict, child: str) -> list[str]:
    """反真空：s3 的"已销号"必须由真 `Secretary` 给出，不许退化成 dict 替身。

    `draft/145` §5：替身是 `{号: 理由}` 这个 Mapping —— 不收 `owner`、`bad` 恒 `[]`、
    `retired_names` 连 callable 都不是。它让 `wake_on_lifeline` 走最宽的 Mapping
    分支，于是适配层的签名试探与 `(rows, bad)` 解包一步都没走过。这一格把它们点出来：
    对象是 `Secretary`、读口要 `owner`、回 `(rows, bad)` 且行是生产者的 8 格。
    """
    problems: list[str] = []
    sec = env["cond"].secretary
    if not isinstance(sec, Secretary):
        return [f"夹具退化成替身了：{type(sec).__name__}（必须是真 Secretary；"
                "dict 替身只走 Mapping 分支，绕开签名与 (rows, bad) 两道适配）"]
    try:
        sig = inspect.signature(type(sec).retired_names)
    except (TypeError, ValueError) as exc:
        return [f"夹具的读口不是方法（{type(exc).__name__}: {exc}）"]
    params = list(sig.parameters.values())
    if [p.name for p in params] != ["self", "owner"]:
        problems.append(f"夹具读口的签名该是 (self, owner)，实际 "
                        f"({', '.join(p.name for p in params)})")
    elif params[1].default is not inspect.Parameter.empty:
        problems.append(f"夹具读口的 owner 不许有默认值：{params[1]!r}")
    got = sec.retired_names(str(env["owner"]))
    if not (isinstance(got, tuple) and len(got) == 2):
        return problems + [f"夹具的读口该回 (rows, bad) 二元组，实际 "
                           f"{type(got).__name__}: {got!r}"]
    rows, bad = got
    if not isinstance(rows, list) or not isinstance(bad, list):
        return problems + [f"(rows, bad) 该都是 list，实际 "
                           f"{type(rows).__name__} / {type(bad).__name__}"]
    mine = [r for r in rows if str((r or {}).get("task_id") or "") == str(child)]
    if not mine:
        return problems + [f"夹具自己没成立：销号名单里没有 {child}（rows={rows!r}）"]
    wanted = {"owner", "name", "task_id", "role", "at", "reason", "branch", "seq"}
    if set(mine[0]) != wanted:
        problems.append(f"夹具的销号行键集不对：多 {sorted(set(mine[0]) - wanted)}、"
                        f"少 {sorted(wanted - set(mine[0]))}")
    if str(mine[0].get("name") or "") == str(mine[0].get("task_id") or ""):
        problems.append("夹具的销号行 name 与 task_id 同值 —— 这是 Mapping 分支"
                        "（`{号: 理由}`）的形状；真生产者写的是名册名（如 D1）")
    return problems


def test_s1_a_running_agent_is_not_resumed(tmp_path: pathlib.Path) -> None:
    """目标正在跑 ⇒ 不许再起一个同号循环（那会造出两个自己）。"""
    env = _ws(tmp_path)
    child = _child(env["cond"], str(env["owner"]), status="running")
    got = env["cond"].wake_on_lifeline(child)
    assert got.get("started") is False, got
    assert env["calls"] == [], env["calls"]
    assert "在跑" in str(got.get("reason") or ""), got


def test_s2_a_silent_agent_is_still_resumed(tmp_path: pathlib.Path) -> None:
    """静默未销号 ⇒ 照旧要被叫起来（s1 不许把所有情况一起挡掉）。"""
    env = _ws(tmp_path)
    child = _child(env["cond"], str(env["owner"]), status="done")
    got = env["cond"].wake_on_lifeline(child)
    assert got.get("started") is True, got
    assert env["calls"] and env["calls"][0][0] == child, env["calls"]


def test_s3_a_retired_agent_is_still_deaf(tmp_path: pathlib.Path) -> None:
    """已销号 ⇒ 叫不醒（P4 的边界不许被 s1 掩盖）。"""
    env = _ws(tmp_path)
    child = _child(env["cond"], str(env["owner"]), status="done")
    env["cond"].secretary = type("S", (), {"retired_names": {child: "已销号"}})()
    problems = _fixture_problems(env, child)
    assert problems == [], problems
    got = env["cond"].wake_on_lifeline(child)
    assert got.get("started") is False, got
    assert "叫不醒" in str(got.get("reason") or ""), got
