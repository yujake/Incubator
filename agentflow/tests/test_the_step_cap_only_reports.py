"""判据：步数上限不作硬标准、不设机器闸，超限只上报（业主 2026-10-10 裁定 12-K）。
逐字：「步数上限不做为硬标准，不设机器闸，但向父代理报告步数超限行为，由父代理决定继续放行还是刹停」。
## 四条判据（分别钉四件事）
1. 循环里没有步数闸：`AgentLoop._step_counter` 是无限的（"不设机器闸"这句话
就落在它身上，所以判据直接打在它身上，而不是打在注释上）；
2. 跨过阈值 ⇒ 落一条上报，而循环照常继续（父代理不动作 ⇒ 继续跑，直到模型自己 final）；
3. 收件人分得清：子代理的超限上报真的发到了父代理（一条 `agent_message`），
而顶趟（`depth == 1`，上面没有人）不发 —— 两边一起判，"总是发"与"从不发"都过不了；
4. 反真空：源码里不再有"因步数收工"那一支，也不再对模型说"这是最后一步 / 最多 N 步"
（那两句是硬闸的口吻：循环不再因步数收工时，它们从真的变成谎话，而模型读到谎话会自己把活截断）。
## 为什么第 2、3 条要用"跑一趟"来判
阈值是声明，"跨过它之后还在跑"与"报到了谁那里"都是行为 ——只判声明的话，把 `max_steps` 改成"只上报"而循环仍在 `range(start, max_steps)` 里打转、或者把上报发给一个没人读的收件人，
这两件事都看不出来。
## 第 3 条为什么要单独一条
写这条上报时的第一版条件用的是 `summoned_by != S.CONDUCTOR_ROLE`，而 `run_role` 给顶趟的 `summoned_by` 填的正是
`S.CONDUCTOR_ROLE`（`agent_loop.py` 里`summoned_by = S.CONDUCTOR_ROLE if role == S.CONDUCTOR_ROLE else ""`）
⇒那一版的实际效果是"被主控召唤的子代理永远不报"（孩子与顶层用 `summoned_by` 分不开）。两头的判据（孩子收得到 / 顶趟不给自己发）就是为这一格的错法准备的。
"""

from __future__ import annotations

import pathlib

import test_agent_loop as TAL

from agentflow import agent_loop as AL
from agentflow import sessions as SS
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam
from test_loop_liveness import _reply

#: 报告阈值（判据用的小值：跑一趟 5 步就能跨过去）。
THRESHOLD = 3

#: 工作区里那几份"给循环读的材料"（内容各不相同 ⇒ 每一步都读到新东西）。
BAIT_COUNT = 5


def test_the_step_counter_is_unbounded() -> None:
    """正控（核心）：步号计数器不设上限 —— 这就是"不设机器闸"的落点。"""
    counter = AL.AgentLoop._step_counter(None, 0)  # type: ignore[arg-type] —— 它不用 self
    got = [next(counter) for _ in range(50)]
    assert got == list(range(50)), got
    # 再要 50 个也必须给得出来（`range(start, max_steps)` 会在这里 StopIteration）。
    more = [next(counter) for _ in range(50)]
    assert more[0] == 50 and more[-1] == 99, (more[0], more[-1])


def test_no_leftover_step_gate_in_the_source() -> None:
    """反真空：源码里不许留着"因步数收工"那一支与那两句硬闸口吻的提示词。"""
    src = pathlib.Path(AL.__file__).read_text(encoding="utf-8")
    assert 'stop_reason = "max_steps"' not in src, "还有一支把步数当收工理由"
    assert 'stop_reason in ("max_steps"' not in src, "终态理由表里还留着死取值"
    # 这两条钉的是赋值/分支本身（含那半句字面量），不是"这个词出现过"——
    # 否则一句"改前这里是 X"的诚实注释会把判据判红（本项目踩过的形态）。
    assert 'tail = ("这是最后一步' not in src, "还对模型说'这是最后一步'（硬闸口吻）"
    assert '"（最多 {self.max_steps} 步）"' not in src, "还对模型说'最多 N 步'（硬闸口吻）"
    # 正控对照：`max_steps` 这个参数还在（它现在的身份是报告阈值）—— 不许顺手删干净。
    assert "max_steps" in src, "报告阈值本身被删掉了？它应当留着，只是不再判停"


def _prepare_bait(root: pathlib.Path) -> None:
    """在工作区里铺几份内容各不相同的文件（给循环读）。

    为什么要内容不同：S-D 那道判停（同调用 + 同读数）会在第 5 步收工，而本判据要看的是
    "步数不再判停"，所以剧本必须不踩到那道判停 —— 否则判据测的是另一件事。

    为什么在 `_wired` 之后铺：工作区根的"外来目录守卫"（`draft/28` §136.3 事故 B）
    会把 `out/` 当成别人的东西而拒绝 `init` —— 顺序反了就先撞上那道守卫，
    这一格测的就不是步数了。
    """
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    for i in range(BAIT_COUNT):
        (out / f"bait{i}.txt").write_text(f"第 {i} 份材料\n", encoding="utf-8", newline="")


def _reads() -> list[str]:
    """几条各不相同的读调用（工具同名、路径不同 ⇒ 不构成"同一个调用"）。"""
    return [_reply({"tool": "fs.read", "args": {"path": f"out/bait{i}.txt"},
                    "why": f"读第 {i} 份材料"}) for i in range(BAIT_COUNT)]


def _top_run(tmp_path: pathlib.Path, sid: str = "test-run"):
    """跑一趟顶趟（角色 M，`depth == 1`）：5 步读料 + 一条 final。"""
    st, cond, registry, gw, root = TAL._wired(
        tmp_path, {"M": _reads() + [_reply({"final": "跑够了", "evidence": []})]},
        max_steps=THRESHOLD)
    _prepare_bait(root)
    run = run_role("M", "把材料读一遍再收工", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="M", session_root=root, gateway=gw["M"], price=(0.0, 0.0),
                                sid=sid), workspace_root=str(root), sid=sid, from_env=False,
                   max_steps=THRESHOLD)
    return run, root


def test_crossing_the_threshold_reports_and_keeps_running(tmp_path: pathlib.Path) -> None:
    """正控：顶趟跨过阈值 ⇒ 有一条上报，循环继续跑到模型自己 final（不因步数收工）。"""
    run, root = _top_run(tmp_path)

    # ① 步数不再是收工理由：跨过阈值（3）以后照跑到第 5 步，收工理由是模型自己给的 final。
    assert len(run.steps) >= BAIT_COUNT, run.to_dict()
    assert run.stop_reason == "final", (run.stop_reason, run.to_dict())
    # ② 上报落了盘：一条 `agent_note`，正文里点明"步数超限报告"并带上阈值读数。
    events, problems = SS.read_session(root, "test-run")
    assert not problems, problems
    reports = [e for e in events
               if e.get("kind") == "agent_note" and "步数超限报告" in str(e.get("note") or "")]
    assert reports, [e.get("kind") for e in events]
    first = reports[0]
    assert first["threshold"] == THRESHOLD and first["steps_used"] >= THRESHOLD, first
    assert "花销" in first["note"], first["note"]
    # ③ 顶趟不给自己发消息（`depth == 1`，上面没有人）：负控的一半。
    assert not [e for e in events if e.get("kind") == "agent_message"
                and "步数超限" in str(e.get("subject") or "")], "顶趟给自己发了超限留言？"


def test_a_child_reports_to_its_parent(tmp_path: pathlib.Path) -> None:
    """正控（收件人）：子代理跨过阈值 ⇒ 父代理真的收到一条留言，而且不是广播。"""
    st, cond, registry, gw, root = TAL._wired(
        tmp_path, {"H": _reads() + [_reply({"final": "看完了", "evidence": []})]},
        max_steps=THRESHOLD)
    _prepare_bait(root)
    run = run_role("H", "把材料看一遍", store=st, registry=registry, conductor=cond,
                   seam=LlmSeam(role="H", session_root=root, gateway=gw["H"], price=(0.0, 0.0),
                                sid="test-child"), workspace_root=str(root), sid="test-child",
                   from_env=False, max_steps=THRESHOLD)
    assert run.stop_reason == "final", run.to_dict()

    events, problems = SS.read_session(root, "test-child")
    assert not problems, problems
    sent = [e for e in events if e.get("kind") == "agent_message"
            and "步数超限" in str(e.get("subject") or "")]
    assert sent, "子代理超限了却没报到父那里（`depth` 那一支判错了？）"
    assert sent[0]["from"] == "H", sent[0]
    # 收件人：H 这一趟是 `run_role` 直接发起的顶行（台账里 `by="user"`，没有父行），
    # 于是 `_resolve_parent` 走第三条分支"落回主控"—— 子代理的上级就是主控 M。
    # 这一格钉的是"那个 `to` 真的是一个角色、且是它上面那一级"，不是"随便发给谁"。
    assert sent[0]["to"] == "M", sent[0]
    # 负控：不是广播（收件人是一个具体角色，不是 ALL / 所有人）。
    assert sent[0]["to"] not in ("ALL", "所有", ""), sent[0]
