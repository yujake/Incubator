"""判据：逐工具超时是协作式的，超时结果逐字节相同（裁定 13甲 / 12-D / 12-E / 12-G）。

## 这一组守六件事

1. 正控（机制真的接上了）：一个声明了 0.05 秒的工具跑到截止就停在检查点上
   （它自己那条 3 秒的兜底循环没跑完），循环把结果换成 DSH 形状的超时结果，
   而侧信道落下了"实际用了多久"与"工具看了信号"这两个读数。
2. 不机械杀进程（12-D 逐字「甲，不机械杀进程」）：工具是自己看到截止才停的 ——
   判据读的是"它停在检查点上"（`state == observed`），不是"进程没了"。
   反过来说：没有检查点的那一档（`pending`）不许被替换成超时结果 ——
   到点了而工具没看，如实记 `deadline_passed_unobserved`，那是三态里的一档。
3. 逐字节相同（12-E）：同一个超时调用连着来，结果读数一个字都不差
   ⇒ 判停那一道（S-D）照常累加 —— 所以第五次照样以 `no_progress_limit` 收工。
   这一条是这一组里最贵的一条：它把"超时"从"每次都算新事实"拉回"没有新事实"。
4. 负控：没在表里的工具一个字节都不变（没有 `tool_timeout` 事件、结果就是正常结果）。
5. 嵌套正控（DSH `timeoutOf` 的作用域）：外层钟先响 ⇒ 内层不许把自己的超时
   报成"我超时了"，而外层那一层要认下来。
6. 三态 + 反真空：限时"读不到"（overrides 坏了）不许当成 0；表里声明的每一件
   都必须在注册表里真的存在；声明的集合必须等于 `external in (egress, exec)` 那一批
   （多一件少一件都要有人看见），而 `pending` 那一档要出现在读数里而不是只报一个数。
"""

from __future__ import annotations

import pathlib
import time

import pytest

import test_agent_loop as TAL
from agentflow import agent_loop as AL
from agentflow import sessions as SS
from agentflow import tool_timeout as TT
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam
from agentflow.tools import build_registry
from agentflow.tools.base import tool

#: 被声明成"会看截止"的那两件（判据自己装表，不去动真表里那些秒级的值）。
SHORT_SEC = 0.05
#: 兜底循环的上限：远大于截止（3 秒 vs 0.05 秒）⇒ "它停在检查点上"这句话才有分辨力。
BAILOUT_SEC = 3.0


def _slow_tool() -> object:
    """一个会看截止的工具：每一小步先问"到点了吗"，到点就抛。"""

    @tool("demo.slow", "跑到截止就停（判据用）",
          {"type": "object", "properties": {}, "additionalProperties": False},
          side_effect="read", roles=("M",), returns="睡到截止")
    def slow() -> dict:
        until = time.monotonic() + BAILOUT_SEC
        while time.monotonic() < until:
            TT.raise_if_timed_out()
            time.sleep(0.002)
        return {"bailed_out": True}

    return slow


def _declare(monkeypatch: pytest.MonkeyPatch, name: str, code: str) -> None:
    """往真表里插一格（判据自己装，跑完 monkeypatch 会自动撤掉）。"""
    monkeypatch.setitem(TT.TIMEOUT_TABLE, name,
                        TT.TimeoutDecl(SHORT_SEC, code, "handler", "判据装的一格"))


def _reply(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def _wire(tmp_path: pathlib.Path, replies: list[str], *, max_steps: int = 8):
    st, cond, registry, gw, root = TAL._wired(tmp_path, {"M": replies}, max_steps=max_steps)
    registry.register_function(_slow_tool())
    return st, cond, registry, gw, root


def _run(st, cond, registry, gw, root, *, sid: str = "t-sf"):
    return run_role("M", "测一测超时", store=st, registry=registry, conductor=cond,
                    seam=LlmSeam(role="M", session_root=root, gateway=gw["M"],
                                 price=(0.0, 0.0), sid=sid),
                    workspace_root=str(root), sid=sid, from_env=False)


def _timeout_events(root: pathlib.Path, sid: str = "t-sf") -> list[dict]:
    events, problems = SS.read_session(root, sid=sid)
    assert not problems, problems
    return [e for e in events if e.get("kind") == "tool_timeout"]


CALL_SLOW = {"tool": "demo.slow", "args": {}, "why": "试一次超时"}


def test_a_declared_tool_stops_at_the_deadline(tmp_path: pathlib.Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（机制）：declared 的工具跑到截止 ⇒ 停在检查点上 + 结果被换成超时结果。

    三样一起判：结果（DSH 形状）/ 侧信道（停了多久、看没看信号）/ "它真的是自己停的"
    （耗时远小于兜底上限 ⇒ 不是等它自己跑完再补一句"你超时了"）。
    """
    _declare(monkeypatch, "demo.slow", "DEMO_TIMEOUT")
    st, cond, registry, gw, root = _wire(tmp_path, [_reply(CALL_SLOW)] * 1
                                        + [_reply({"final": "收工"})])
    run = _run(st, cond, registry, gw, root)
    assert run.stop_reason == "final", run.to_dict()

    step = run.steps[0]
    assert step.result["ok"] is False, step.result
    assert step.result["error"] == "Error: tool call timed out after 50ms", step.result
    assert step.result["meta"]["error_code"] == TT.TOOL_TIMEOUT, step.result["meta"]
    assert step.result["meta"]["error_name"] == TT.TIMEOUT_ERROR_NAME, step.result["meta"]
    # 结果里没有耗时（裁定 12-E）：耗时的唯一落点是侧信道。
    assert "elapsed" not in str(step.result), step.result

    evs = _timeout_events(root)
    assert len(evs) == 1, evs
    ev = evs[0]
    assert ev["tool"] == "demo.slow" and ev["code"] == "DEMO_TIMEOUT", ev
    assert ev["state"] == TT.OBSERVED, ev
    assert ev["timeout_ms"] == 50.0, ev
    # "自己停在检查点上"的读数：远小于兜底那 3 秒。
    assert 0.0 < ev["elapsed_ms"] < BAILOUT_SEC * 1000 * 0.5, ev


def test_no_checkpoint_means_no_substitution(tmp_path: pathlib.Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（三态里最要紧的一档）：到点了而工具没看信号 ⇒ 不许替换成超时结果。

    这一条挡的形态是"假装拦住了"：`pending` 那一档的处理函数还没接检查点，
    它跑完之后结果照收，只在侧信道留一句"到点了但没看"。
    """
    _declare(monkeypatch, "demo.unwatched", "UNWATCHED_TIMEOUT")
    # 剧本在接线期就给（替身模型是 `_wire` 按它建的；事后传给 `_run` 是无效的 ——
    # 第一版就是这么写的，于是循环拿到一份空剧本、判成 `bad_json_limit`）。
    st, cond, registry, gw, root = _wire(tmp_path, [
        _reply({"tool": "demo.unwatched", "args": {}, "why": "看看它看不看截止"}),
        _reply({"final": "收工"})])

    @tool("demo.unwatched", "不看截止（判据用）",
          {"type": "object", "properties": {}, "additionalProperties": False},
          side_effect="read", roles=("M",), returns="照常返回")
    def unwatched() -> dict:
        time.sleep(SHORT_SEC * 3)       # 睡过截止，但一次都不问
        return {"done": True}

    registry.register_function(unwatched)
    run = _run(st, cond, registry, gw, root)
    assert run.stop_reason == "final", run.to_dict()
    step = run.steps[0]
    assert step.result["ok"] is True, step.result      # 结果照收（没假装拦住）
    assert step.result["data"] == {"done": True}, step.result
    evs = _timeout_events(root)
    assert len(evs) == 1 and evs[0]["state"] == TT.UNOBSERVED, evs
    assert "没拦住" in evs[0]["note"], evs[0]


def test_two_timeouts_are_byte_identical_and_still_trip_the_stop(tmp_path: pathlib.Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（裁定 12-E 的核心）：两次超时的结果逐字节相同 ⇒ 判停照常累加。

    为什么这是最贵的一条：结果里若带上"这次等了多久"，两次超时就是两个不同的读数，
    S-D 那道判停（同调用 + 同读数连着 5 次）永远不会触发，模型可以无限循环在一个
    超时调用上。这里一次跑 5 遍同一个超时调用，断言它以 `no_progress_limit` 收工。
    """
    _declare(monkeypatch, "demo.slow", "DEMO_TIMEOUT")
    st, cond, registry, gw, root = _wire(tmp_path, [_reply(CALL_SLOW)] * 6, max_steps=30)
    run = _run(st, cond, registry, gw, root)

    # 结果本身逐字节相同：摘掉 S-D 那条"没有新事实"提醒那一格再比 —— 提醒刻意会变
    # （它正是"这一步没有新事实"这个读数的一部分），而超时那一份结果一个字都不许变。
    cores = [{k: v for k, v in s.result.items() if k != "框架提醒"}
             for s in run.steps if s.shape == "tool" and s.result.get("ok") is False]
    assert len(cores) >= 5, run.to_dict()
    assert len({AL._call_reading(c) for c in cores}) == 1, \
        "两次超时的读数不一样 ⇒ 判停永远不会触发"
    assert run.stop_reason == "no_progress_limit", run.stop_reason
    assert run.dead_loop_stopped is True, run.to_dict()
    # 侧信道里那两份耗时是两次不同的读数（结果相同、读数不同，两者都要有）。
    evs = _timeout_events(root)
    assert len(evs) >= 5, evs
    assert all(e["state"] == TT.OBSERVED for e in evs), evs


def test_an_undeclared_tool_is_untouched(tmp_path: pathlib.Path) -> None:
    """负控：没在表里的工具一个字节都不变（不装钟、不落事件）。"""
    st, cond, registry, gw, root = _wire(tmp_path, [
        _reply({"tool": "fs.write", "args": {"path": "out/x.txt", "content": "hi"},
                "why": "写一个文件"}), _reply({"final": "收工"})])
    run = _run(st, cond, registry, gw, root)
    assert run.stop_reason == "final", run.to_dict()
    assert run.steps[0].result["ok"] is True, run.steps[0].result
    assert _timeout_events(root) == [], "没声明的工具不该落超时事件"
    assert TT.lookup("fs.write") is None


def test_an_outer_deadline_owns_the_shorter_fuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """嵌套正控（DSH `timeoutOf` 的作用域）：外层钟先响 ⇒ 内层不许报自己的超时。

    逐字理由（`dsh-timeout/lib/index.js:73-80`）：不这样判，嵌套时内层会把自己的超时
    误读成"我超时了"，于是同一个到点被报两次（外层一次、内层一次）。
    """
    _declare(monkeypatch, "demo.outer", "OUTER_TIMEOUT")
    _declare(monkeypatch, "demo.inner", "INNER_TIMEOUT")
    caught: list[Exception] = []
    inner_code = ""

    with TT.tool_deadline("demo.outer") as outer:
        time.sleep(SHORT_SEC * 2)              # 把外层那口钟睡过去
        with TT.tool_deadline("demo.inner") as inner:
            time.sleep(SHORT_SEC * 2)          # 内层自己也到点
            try:
                TT.raise_if_timed_out()
            except TT.ToolTimedOut as exc:
                caught.append(exc)
                inner_code = exc.reason.code
    assert caught and isinstance(caught[0], TT.ToolTimedOut), caught
    assert inner_code == "INNER_TIMEOUT", inner_code
    assert inner.state == TT.OBSERVED, inner.run
    # 内层：外层钟先响 ⇒ 这一跳读作上游取消，不许替换结果。
    assert inner.observed_timed_out is False, inner.run
    # 外层：抛上来的那个 code 是内层的 ⇒ 外层不许把它认成"我的信号被看到了"
    # （那正是 `timeoutOf` 要挡的双报）。外层那口钟确实响了、而没人看它自己的信号
    # ⇒ 如实读作"到点了但没看"，所以它也不替换结果。
    assert outer.state == TT.UNOBSERVED, outer.run
    assert outer.observed_timed_out is False, outer.run
    # 两条单位级判据（同一件事的另一半）：别人的 code 认不出自己，自己的 code 认得出。
    foreign = type("C", (), {"reason": TT.TimeoutReason("INNER_TIMEOUT", 50.0)})()
    assert TT.timeout_of(foreign, "OUTER_TIMEOUT") is None
    assert TT.timeout_of(foreign, "INNER_TIMEOUT") is not None
    assert TT.timeout_of(foreign) is not None       # 不给 code 时是粗问


def test_the_table_matches_the_egress_and_exec_tools() -> None:
    """反真空（表与真实工具面对齐）：声明的集合等于 `external in (egress, exec)`。

    为什么要一条判据守它：这张表是"谁会被限时"的唯一真身 —— 新加一个出网/起子进程的工具
    而没人看这张表，那一件就永远不会被限时，而没有任何东西会红（本仓反复踩的形态）。
    """
    reg = build_registry().registry
    want = {n for n in reg.names()
            if str(getattr(reg.get(n), "external", "")) in ("egress", "exec")}
    got = set(TT.TIMEOUT_TABLE)
    assert got == want, {"表里有而工具面没有": sorted(got - want),
                         "工具面有而表里没有": sorted(want - got)}
    reading = TT.table_reading()
    assert reading["count"] == len(got), reading
    # `pending` 那一档必须列出来（只报一个数的话，"谁还挂着"要人去读源码）。
    assert sorted(reading["pending"] + reading["with_checkpoint"]) == sorted(got), reading
    assert "search.literature" in reading["with_checkpoint"], reading
    # 检查点真的在源码里（声明的 `handler` 那一格不许只在表里写着）。
    src = pathlib.Path(__import__("agentflow.tools.search_tools", fromlist=["x"]).__file__)
    assert "raise_if_timed_out()" in src.read_text(encoding="utf-8"), "检查点没写进处理函数"


def test_the_declared_seconds_have_three_states() -> None:
    """三态：声明了 / 没声明 / 读不到 —— 后者不许被折成 0（0 是"立刻超时"）。

    施工单逐字要求："限时读不到（配置缺）时不许当 0"。这一条把三种状态分三个断言钉住。
    """
    sec, state = TT.declared_seconds("search.literature")
    assert (sec, state) == (120.0, "declared"), (sec, state)
    assert TT.declared_seconds("fs.read") == (None, "undeclared")
    assert TT.declared_seconds("search.literature", overrides=["不是映射"]) == (None, "unknown")
    assert TT.declared_seconds("search.literature", overrides={"search.literature": 0}) == \
        (None, "unknown"), "0 被当成有效限时 ⇒ 每一次调用都会立刻'超时'"
    assert TT.declared_seconds("search.literature", overrides={"search.literature": "abc"}) == \
        (None, "unknown")
    # 装表期校验（DSH `:29` 逐字文案）：0 与负数都不是"关掉超时"的公开哨兵。
    with pytest.raises(ValueError, match="positive finite number"):
        TT.assert_timer_delay(0, 'tool "x" timeoutMs')
    with pytest.raises(ValueError, match="positive finite number"):
        TT.clamp_timeout(0, 30.0, 60.0)
    assert TT.clamp_timeout(None, 30.0, 60.0) == 30.0
    assert TT.clamp_timeout(90.0, 30.0, 60.0) == 60.0
