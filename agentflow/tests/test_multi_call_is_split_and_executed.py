"""拆分口径的判据：一步给 N 条调用 ⇒ 接住、拆分、逐条执行、逐条记账、逐条计步。

## 这一条修的是什么（业主原话，逐字）

「multi_call 应该让系统自动整理拆分」；实现方式「智能体要做动作时系统先接住请求，
拆分，分条执行」。

改前（D-35 方案 B）：解析层取 `tool_call_list[0]`，其余丢弃，循环那边只补一句 warn
点名被丢的那几条。盘上读到的是"模型请求了 N 条、框架只做了第 1 条"。真机上
（`projects/r34d` + `projects/cube2`）共 50 个多调用步、被丢弃 69 条，全部是只读 ——
那 69 条一个字节都没执行，而模型以为它们生效了。

改后：`stepdispatch.catch_step_request` 把一步接住、按原顺序拆成有序条目，
循环按条目逐条执行（每条 = 一步，走完整的准入 / 预算 / 参数校验），逐条记账，
最后把一句汇总（第 k 条 / 工具名 / 结果一句话 + 一句可执行建议）交回模型。

## 十二条判据（每条都写了"改前红"在哪）

1. 一步 2 条只读 ⇒ 两条都真的执行，事件流里逐条可查；
2. 一步 [写, 读] ⇒ 顺序保持、写先落、读后看到写的结果；
3. 一步 [合法, 越权] ⇒ 合法那条成功、越权那条如实被拒，两者 outcome 分开记；
4. 预算只够第一条 ⇒ 第二条标"因预算未执行"，不假装执行（且仍计步）；
5. 反真空：把拆分打桩回"只跑第一条" ⇒ 判据 1 必红；
6. 统计：同一夹具下 `multi_call` 记 1（一个多调用步）、`multi_call_executed_calls` 记 2；
7. 接住层是唯一入口：把它打桩成"只返回第一条" ⇒ 判据 1 必红（证明循环真的走它）；
8. 单条与多条走同一个函数：单条也经过 `catch_step_request`，且单条行为与改前逐字相同；
9. 对十一个角色都成立（同一夹具逐角色跑一遍），且层里一个角色名都没有；
10. 没有旁路：执行器的直接调用点只有一处、条目的构造点只有 `stepdispatch` 一处；
11. 一步 2 条 ⇒ 步数 +2（改前红：+1），两条 step 序号连续、能回溯到同一回合；
12. 反真空：把步号递增打桩成"每回合只 +1" ⇒ 判据 11 必红。

## 计数口径（业主要看的那三个数）

- 步数 = 拆分后的条目数：`run.steps` / 会话里的 `agent_step.index` / `agent_run_end.steps`
  都按条目递增（一条 = 一步），未执行的那条也计步（标 `not_executed=true`）；
- 回合数 = 模型调用次数（一个回合一次 `llm_call`）—— 与步数分开，"2 条调用的回合"是 1 个回合、2 步；
- 调用条数 = 拆出来的条目数（逐条记录 `agent_step_call`，`multi_call_executed_calls` 数真的执行了的那些）。

判据里的模型是桩（按脚本回原生 `tool_calls` 或文本），全程离线、零花销。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

from agentflow import errorstats as ES
from agentflow import llmseam as LL
from agentflow import modelgw as MG
from agentflow import sessions as SS
from agentflow import stepdispatch as SD
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "split"
#: 只读夹具读到的内容（它出现在结果里 ⇒ "这一条真的执行了"可核）。
SENTINEL = "SENTINEL-SPLIT-只读夹具读到的内容"
#: 写那一条写进去的内容（读那一条要看得见它 ⇒ 顺序真的是"写先、读后"）。
WRITTEN = "P2-写先读后"
#: 十一个角色（A–H 与主控、验证者、形式化者）。
ROLES = ("A", "B", "C", "D", "E", "F", "G", "H", "M", "V", "L")
#: `stepdispatch` 的目录（"没有旁路"与"层里没有角色名"两条扫的就是它）。
SRC = pathlib.Path(LL.__file__).resolve().parent


class _StubGateway:
    """按脚本回原生 `tool_calls` 的替身网关（不联网、零花销）。"""

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.prompts: list[str] = []
        self.spec = MG.ModelSpec(model="stub-model", api_key="x", base_url="http://stub")

    def complete(self, prompt: str, *, scope: str, system: Any = None, max_tokens: Any = None,
                 tools: Any = None, tool_choice: str = "auto") -> MG.ModelReply:
        self.prompts.append(prompt)
        item = self.script.pop(0) if self.script else {"tool_calls": []}
        return MG.ModelReply(ok=True, text=str(item.get("text") or ""),
                             tool_calls=tuple(item.get("tool_calls") or ()),
                             tokens_in=1, tokens_out=1, model="stub-model", scope=scope)


def _call(name: str, args: dict, cid: str) -> dict:
    return {"id": cid, "name": name, "arguments": json.dumps(args, ensure_ascii=False)}


def _reads() -> dict:
    """一步两条只读调用（同一份文件的两种读法：读内容 + 看 stat）。"""
    return {"tool_calls": [
        _call("fs_read", {"path": "data/sentinel.txt", "why": "读它"}, "c1"),
        _call("fs_stat", {"path": "data/sentinel.txt"}, "c2"),
    ]}


def _write_then_read() -> dict:
    """一步 [写, 读]：读那一条必须看得见刚写进去的内容（顺序不可换）。"""
    return {"tool_calls": [
        _call("fs_write", {"path": "data/probe.txt", "content": WRITTEN}, "c1"),
        _call("fs_read", {"path": "data/probe.txt"}, "c2"),
    ]}


def _legal_then_forbidden() -> dict:
    """一步 [合法, 越权]：读是合法的；C 召唤 B 不在边表里（边表在层之下判）。"""
    return {"tool_calls": [
        _call("fs_read", {"path": "data/sentinel.txt", "why": "读它"}, "c1"),
        _call("framework_summon", {"role": "B", "task": "越权的一条"}, "c2"),
    ]}


def _final(text: str = "做完了") -> dict:
    return {"tool_calls": [_call("framework_final", {"final": text, "evidence": []}, "c9")]}


def _wired(tmp_path: pathlib.Path, script: list[dict], *, role: str = "M",
           price: tuple[float, float] = (0.0, 0.0),
           usd_budget: float | None = None) -> tuple[Any, Any, Any, _StubGateway, Any, pathlib.Path]:
    root = tmp_path / f"ws-{role}"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "sentinel.txt").write_text(SENTINEL, encoding="utf-8")
    st = Store(root)
    st.init()
    gw = _StubGateway(script)
    seam = LlmSeam(role=role, session_root=root, gateway=gw, price=price,
                   usd_budget=usd_budget, sid=SID)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=lambda r: seam, max_steps=6, store=st, sid=SID)
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=root)
    backend.registry = built.registry
    assert "fs.read" in built.registry.names(), built.skipped
    return st, cond, built.registry, gw, seam, root


def _run(tmp_path: pathlib.Path, script: list[dict], *, role: str = "M",
         price: tuple[float, float] = (0.0, 0.0), usd_budget: float | None = None):
    st, cond, registry, gw, seam, root = _wired(
        tmp_path, script, role=role, price=price, usd_budget=usd_budget)
    run = run_role(role, "把 sentinel 读出来", store=st, registry=registry, conductor=cond,
                   seam=seam, workspace_root=str(root), sid=SID, max_steps=6, from_env=False)
    return run, gw, root


def _events(root: pathlib.Path) -> list[dict]:
    events, problems = SS.read_session(root, sid=SID)
    assert not problems, problems
    return events


def _call_records(root: pathlib.Path) -> list[dict]:
    """事件流里逐条记录（`agent_step_call`）—— 拆分口径的"逐条可查"落在这里。"""
    return [e for e in _events(root) if str(e.get("kind") or "") == SD.STEP_CALL_EVENT]


def _summary_of(run: Any) -> str:
    """这一步的汇总（挂在回合最后一条的 warn 上）。"""
    for s in run.steps:
        text = str(s.result.get("warn") or "")
        if "条调用，已按顺序逐条" in text:
            return text
    return ""


def _check_two_reads(run: Any, gw: _StubGateway, root: pathlib.Path) -> None:
    """判据 1 的正身（判据 5 / 7 把它当成"必红"的那份断言）。"""
    # 两条都真的执行了：两步 tool + 一步 final（改前只有一步 tool：第 2 条被丢弃）
    assert [s.shape for s in run.steps] == ["tool", "tool", "final"], run.to_dict()
    first, second = run.steps[0], run.steps[1]
    assert first.result.get("ok") is True and first.result.get("tool") == "fs.read", first.result
    assert second.result.get("ok") is True and second.result.get("tool") == "fs.stat", second.result
    # 第一条真读到了内容（不是"看起来执行了"）
    assert SENTINEL in str(first.result), first.result
    # 逐条记录：第几条 / 工具名 / ok / 耗时 / usd，各一条
    recs = _call_records(root)
    assert [r["call_index"] for r in recs] == [0, 1], recs
    assert [r["tool"] for r in recs] == ["fs.read", "fs.stat"], recs
    assert [r["ok"] for r in recs] == [True, True], recs
    assert [r["not_executed"] for r in recs] == [False, False], recs
    for r in recs:
        assert isinstance(r.get("elapsed_ms"), int) and r["elapsed_ms"] >= 0, r
        assert r.get("usd") == 0.0, r          # 只读工具不花模型钱（这一格是增量，不是 None）
        assert r.get("calls") == 2, r
    # 汇总：第 k 条 / 工具名 / 结果一句话 + 一句可执行建议（模型据此少发并列调用）
    summary = _summary_of(run)
    assert "这一步给了 2 条调用，已按顺序逐条" in summary, summary
    assert "第 1 条 fs.read 成功" in summary and "第 2 条 fs.stat 成功" in summary, summary
    assert "下一步请只发一条调用" in summary, summary


# ---------------------------------------------------------------- ① 两条只读都执行


def test_two_read_only_calls_are_both_executed(tmp_path: pathlib.Path):
    """① 一步 2 条只读调用 ⇒ 两条都真的执行，事件流里逐条可查。

    改前红：第 2 条在解析层就被丢掉 —— `run.steps` 只有 `["tool", "final"]`、
    `_call_records` 一条都没有（改前根本没有逐条记录）、汇总里写的是"只执行第 1 条"。
    所以 `[s.shape for s in run.steps] == ["tool", "tool", "final"]` 先红。
    """
    run, gw, root = _run(tmp_path, [_reads(), _final("读完了")])
    _check_two_reads(run, gw, root)
    assert run.stop_reason == "final", run.to_dict()


# ---------------------------------------------------------------- ② 写先、读后


def test_write_then_read_keeps_order_and_the_read_sees_the_write(tmp_path: pathlib.Path):
    """② 一步 [写, 读] ⇒ 顺序保持、写先落、读后看到写的结果。

    改前红：写那一条是第 1 条、它会执行，但读那一条被丢弃 —— 读的结果根本不存在，
    于是"读看到写的内容"与"两条逐条记录"两条断言必红。
    """
    run, _gw, root = _run(tmp_path, [_write_then_read(), _final("写完了")])
    assert [s.shape for s in run.steps] == ["tool", "tool", "final"], run.to_dict()
    assert [s.result.get("tool") for s in run.steps[:2]] == ["fs.write", "fs.read"], run.to_dict()
    # 顺序：写的步号在前、读的步号在后（同一条路径上顺序执行，没有重排）
    assert run.steps[0].index < run.steps[1].index, run.to_dict()
    # 写真的落了盘
    assert (root / "data" / "probe.txt").read_text(encoding="utf-8") == WRITTEN
    # 读看到的就是刚写进去的那一份（顺序换了这条必红）
    assert WRITTEN in str(run.steps[1].result), run.steps[1].result
    recs = _call_records(root)
    assert [r["tool"] for r in recs] == ["fs.write", "fs.read"], recs
    assert all(r["ok"] for r in recs), recs


# ---------------------------------------------------------------- ③ 一条被拒不作废整步


def test_a_forbidden_call_does_not_cancel_the_legal_one(tmp_path: pathlib.Path):
    """③ 一步 [合法, 越权] ⇒ 合法那条成功、越权那条如实被拒，两者 outcome 分开记。

    改前红：越权那条被丢弃、盘上只剩"只执行第 1 条"，于是"两者 outcome 分开记"
    （`[True, False]` 与"被拒：…不在策略允许的边里"）无处可读。
    """
    run, _gw, root = _run(tmp_path, [_legal_then_forbidden(), _final("做完了")], role="C")
    assert [s.shape for s in run.steps] == ["tool", "summon", "final"], run.to_dict()
    legal, refused = run.steps[0], run.steps[1]
    # 合法那条：真的执行了
    assert legal.result.get("ok") is True and legal.result.get("tool") == "fs.read", legal.result
    # 越权那条：如实被拒（边表在拆分层之下判，不是解码层）
    assert refused.result.get("ok") is False, refused.result
    assert str(refused.result.get("outcome") or "") == "refused", refused.result
    assert "forbidden_edge" in json.dumps(refused.result, ensure_ascii=False), refused.result
    # 一步没被整步作废：两条各自的记录都在，ok 分开
    recs = _call_records(root)
    assert [r["ok"] for r in recs] == [True, False], recs
    assert [r["not_executed"] for r in recs] == [False, False], recs
    summary = _summary_of(run)
    assert "第 1 条 fs.read 成功" in summary, summary
    assert "被拒" in summary and "不在策略允许的边里" in summary, summary


# ---------------------------------------------------------------- ④ 预算只够第一条


def test_budget_for_one_call_only_marks_the_second_not_executed(tmp_path: pathlib.Path):
    """④ 预算只够第一条 ⇒ 第二条标"因预算未执行"，不许假装执行（且照样计步）。

    构造：单价 1 美元/百万 token 且每次调用 1+1 token ⇒ 一次调用 2 美元 > 上限 1 美元。
    于是第一条执行完、准备第二条时预算已经超了。
    改前红：第二条被丢弃，盘上根本没有"因预算未执行"这句话，`multi_call` 也不再叫
    "多调用步"（改前记的是被丢弃的条数）。
    """
    run, _gw, root = _run(tmp_path, [_reads(), _final("读完了")],
                          price=(1_000_000.0, 1_000_000.0), usd_budget=1.0)
    assert run.stop_reason == "budget", run.to_dict()
    # 第一条真的执行了
    assert run.steps[0].result.get("ok") is True, run.steps[0].result
    assert run.steps[0].result.get("tool") == "fs.read", run.steps[0].result
    # 第二条：计步（占第二个步号）但标未执行，理由如实
    second = run.steps[1]
    assert second.index == 1, [s.index for s in run.steps]
    assert second.result.get("not_executed") is True, second.result
    assert second.result.get("ok") is False, second.result
    assert "因预算未执行" in json.dumps(second.result, ensure_ascii=False), second.result
    # 事件流里同样可查：这条记录 ok=False、not_executed=True、reason=budget
    recs = _call_records(root)
    assert [r["call_index"] for r in recs] == [0, 1], recs
    assert recs[0]["ok"] is True and recs[0]["not_executed"] is False, recs[0]
    assert recs[1]["ok"] is False and recs[1]["not_executed"] is True, recs[1]
    assert recs[1]["reason"] == SD.NOT_EXECUTED_BUDGET, recs[1]
    # 第二条真的没有被执行（stat 的结果不存在）
    assert all("fs.stat" not in json.dumps(r.get("outcome") or "", ensure_ascii=False)
               for r in recs if r["call_index"] == 1), recs


# ---------------------------------------------------------------- ⑤ 反真空（判据 1）


def test_the_split_is_not_vacuous(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """⑤ 反真空：把拆分打桩回"只跑第一条" ⇒ 判据 1 必红。

    如果判据 1 在"只跑第一条"的桩下也绿，那它证明的不是"两条都执行了"，
    而是别的什么（例如"这一步根本没被检查"）。
    """
    real = SD.catch_step_request

    def _only_first(request: SD.StepRequest, *, decode: Any) -> SD.StepDispatch:
        got = real(request, decode=decode)
        return SD.StepDispatch(items=got.items[:1], turn_index=got.turn_index,
                               requested=len(got.items[:1]))

    monkeypatch.setattr(SD, "catch_step_request", _only_first)
    run, gw, root = _run(tmp_path, [_reads(), _final("读完了")])
    with pytest.raises(AssertionError):
        _check_two_reads(run, gw, root)
    # 桩确实把第 2 条挡掉了（不是"判据莫名其妙红了"）
    assert [s.shape for s in run.steps] == ["tool", "final"], run.to_dict()


# ---------------------------------------------------------------- ⑥ 统计口径


def test_the_two_counters_are_step_count_and_call_count(tmp_path: pathlib.Path):
    """⑥ 统计：同一夹具下 `multi_call` 记 1（一个多调用步）、`multi_call_executed_calls` 记 2。

    改前红：`multi_call` 记的是"被丢弃的并列调用数"（这一套夹具下是 1），
    而 `multi_call_executed_calls` 这个类目根本不存在。
    """
    _run(tmp_path, [_reads(), _final("读完了")])
    stats = ES.error_action_stats(tmp_path / "ws-M")
    assert stats.checked is True, stats.as_dict()
    # 一个多调用步（不是"两步"、也不是"被丢的 1 条"）
    assert stats.category_total("multi_call") == 1, stats.as_dict()
    # 拆出来的调用：两条都真的执行了
    assert stats.category_total("multi_call_executed_calls") == 2, stats.as_dict()
    assert stats.count("M", "multi_call") == 1, stats.as_dict()
    assert stats.count("M", "multi_call_executed_calls") == 2, stats.as_dict()
    text = "\n".join(ES.render_text(stats))
    assert "multi_call_executed_calls" in text, text


# ---------------------------------------------------------------- ⑦ 接住层是唯一入口


def test_the_catch_entry_is_the_only_way_in(tmp_path: pathlib.Path,
                                            monkeypatch: pytest.MonkeyPatch):
    """⑦ 接住层是唯一入口：把它打桩成"只返回第一条" ⇒ 判据 1 必红（循环真的走它）。

    这一条与 ⑤ 的差别：⑤ 证明"拆分这一层是承重的"，⑦ 证明"承重的那一层就是
    循环实际调用的那个函数"（桩打在模块属性上，循环通过 `SD.catch_step_request` 取它；
    若循环自己另有一支，桩打不上，判据 1 就不会红）。
    """
    real = SD.catch_step_request
    seen: list[tuple[int, int, int]] = []

    def _only_first(request: SD.StepRequest, *, decode: Any) -> SD.StepDispatch:
        got = real(request, decode=decode)
        seen.append((int(request.turn_index), int(request.first_step), got.requested))
        return SD.StepDispatch(items=got.items[:1], turn_index=got.turn_index, requested=1)

    monkeypatch.setattr(SD, "catch_step_request", _only_first)
    run, gw, root = _run(tmp_path, [_reads(), _final("读完了")])
    with pytest.raises(AssertionError):
        _check_two_reads(run, gw, root)
    # 循环真的走了这个入口：两个回合各一次，且它看到的是"2 条"
    assert [c[0] for c in seen] == [0, 1], seen
    assert [c[2] for c in seen] == [2, 1], seen
    # 源码面：本文件里对它的调用点只有一处
    text = (SRC / "agent_loop.py").read_text(encoding="utf-8")
    assert text.count("SD.catch_step_request(") == 1, "循环里有多处接住调用点"


# ---------------------------------------------------------------- ⑧ 单条与多条同一个函数


def test_the_single_path_and_the_multi_path_are_one(tmp_path: pathlib.Path,
                                                    monkeypatch: pytest.MonkeyPatch):
    """⑧ 单条也经过 `catch_step_request`，且单条行为与改前逐字相同（负控）。

    "拆一条 = 一条"：统一入口不许把单条语义改掉 ——
    步形状/步号/结果键集/消息序列都与改前一致，且不落逐条记录（那一格只属于多调用步）。
    """
    real = SD.catch_step_request
    seen: list[tuple[int, int]] = []

    def _spy(request: SD.StepRequest, *, decode: Any) -> SD.StepDispatch:
        got = real(request, decode=decode)
        seen.append((int(request.turn_index), got.requested))
        return got

    monkeypatch.setattr(SD, "catch_step_request", _spy)
    run, gw, root = _run(tmp_path, [
        {"tool_calls": [_call("fs_read", {"path": "data/sentinel.txt", "why": "读它"}, "c1")]},
        _final("读完了"),
    ])
    # 两个回合都经过入口（单条也走同一条路）
    assert seen == [(0, 1), (1, 1)], seen
    # 单条行为与改前逐字相同
    assert [s.shape for s in run.steps] == ["tool", "final"], run.to_dict()
    assert [s.index for s in run.steps] == [0, 1], run.to_dict()
    first = run.steps[0]
    assert first.result.get("ok") is True and first.result.get("tool") == "fs.read", first.result
    assert "multi_call" not in first.result and "warn" not in first.result, first.result
    assert run.stop_reason == "final", run.to_dict()
    # 单条不落逐条记录（"逐条"这件事只对拆开的回合成立）
    assert _call_records(root) == []
    # 消息序列：开场 user + 这一步那一对（收工那一步与改前一样不进消息序列）
    assert [m.get("role") for m in run.messages] == [
        "user", "assistant", "tool"], run.messages


# ---------------------------------------------------------------- ⑨ 十一个角色


@pytest.mark.parametrize("role", ROLES)
def test_every_role_gets_the_same_split(tmp_path: pathlib.Path, role: str):
    """⑨ 对十一个角色都成立：同一夹具逐角色跑一遍，两条都执行、逐条记账。

    层是角色无关的公共层 —— 准入差异由角色面与边表在层之下判。
    改前红：每个角色的第 2 条都会被丢弃（与角色无关，因为丢弃发生在解析层）。
    """
    run, _gw, root = _run(tmp_path, [_reads(), _final("读完了")], role=role)
    assert [s.shape for s in run.steps] == ["tool", "tool", "final"], (role, run.to_dict())
    assert all(s.result.get("ok") is True for s in run.steps[:2]), (role, run.to_dict())
    recs = _call_records(root)
    assert [r["tool"] for r in recs] == ["fs.read", "fs.stat"], (role, recs)
    assert [r["calls"] for r in recs] == [2, 2], (role, recs)
    # 层里一个角色名都没有（源码扫一遍：单引号或双引号里的单个角色大写字母）
    layer = (SRC / "stepdispatch.py").read_text(encoding="utf-8")
    assert re.findall(r"[\"']([A-HMVL])[\"']", layer) == [], "stepdispatch 里出现了角色名"


# ---------------------------------------------------------------- ⑩ 没有旁路


def test_there_is_no_bypass_around_the_catch_layer():
    """⑩ 没有旁路：执行步的路径只有一处调用点，条目的构造点只有 `stepdispatch` 一处。

    能防住什么：以后有人"顺手"在循环里再写一支（例如再取一次 `tool_call_list[0]`
    或直接调 `self._execute(...)`），这条判据当场红 —— 因为第二处调用点会让计数变 2。
    它守的是"拆分只有一个落点"这件事本身，而不是某一段文案。
    """
    files = {p.name: p.read_text(encoding="utf-8") for p in SRC.glob("*.py")}
    # 执行器：全仓只有一处直接调用（循环里那条，由拆分出来的条目驱动）
    assert sum(t.count("self._execute(") for t in files.values()) == 1, (
        "执行器出现了第二个直接调用点（旁路）")
    # 接住层：全仓只有一处调用点
    assert sum(t.count("SD.catch_step_request(") for t in files.values()) == 1, (
        "接住层出现了第二个调用点")
    # 条目的构造点：只有 stepdispatch 一处（别处自己造条目 = 绕过拆分口径）
    makers = [name for name, t in files.items() if "StepItem(" in t]
    assert makers == ["stepdispatch.py"], makers
    # 旧口径不许回来（"只执行第一条"那支的名字）
    assert "_multi_call_warning" not in files["agent_loop.py"], "旧的多调用分支回来了"
    # 反真空：这两个符号确实在（否则上面的计数是"扫了个空"）
    assert "def _execute(" in files["agent_loop.py"]
    assert "def catch_step_request(" in files["stepdispatch.py"]


# ---------------------------------------------------------------- ⑪ 步数按拆分后的条目


def test_steps_are_counted_per_split_item(tmp_path: pathlib.Path):
    """⑪ 一步 2 条只读调用 ⇒ 步数 +2（改前红：+1），两条 step 序号连续、回溯同一回合。

    步数 = 拆分后的条目数；回合数 = 模型调用次数。两者分开算：
    这个夹具是 1 个多调用回合 + 1 个收工回合 = 2 次模型调用，而步数是 3 步。
    """
    run, _gw, root = _run(tmp_path, [_reads(), _final("读完了")])
    assert [s.shape for s in run.steps] == ["tool", "tool", "final"], run.to_dict()
    assert [s.index for s in run.steps] == [0, 1, 2], [s.index for s in run.steps]
    # 两条溯得回同一个回合（turn_index 相同），且是同一次模型调用
    first, second = run.steps[0].result.get("multi_call"), run.steps[1].result.get("multi_call")
    assert first and second, run.to_dict()
    assert first["turn_index"] == second["turn_index"] == 0, (first, second)
    assert [first["call_index"], second["call_index"]] == [0, 1], (first, second)
    # 逐条记录的 index 与 step 序号一致（出错时能精确指到第几步）
    recs = _call_records(root)
    assert [r["index"] for r in recs] == [0, 1], recs
    assert [r["turn_index"] for r in recs] == [0, 0], recs
    # 回合数 != 步数：2 次模型调用、3 步
    llm_calls = [e for e in _events(root) if str(e.get("kind") or "") == "llm_call"]
    assert len(llm_calls) == 2, len(llm_calls)
    assert len(run.steps) == 3, len(run.steps)


# ---------------------------------------------------------------- ⑫ 反真空（判据 11）


def test_the_step_increment_is_load_bearing(tmp_path: pathlib.Path,
                                            monkeypatch: pytest.MonkeyPatch):
    """⑫ 反真空：把"每条 +1 个步号"打桩成"每回合只 +1" ⇒ 判据 11 必红。

    步数按拆分后的条目记：`stepdispatch.step_index_of(first_step, call_index)` 是这件事
    唯一的实现处。把它打桩成"只回回合起点的步号"（就是改前"一个回合 = 一步"的口径），
    拆出来的两条会拿到同一个步号，于是"步数按条目记"在读数上消失。
    """
    monkeypatch.setattr(SD, "step_index_of", lambda first_step, call_index: int(first_step))
    run, _gw, _root = _run(tmp_path, [_reads(), _final("读完了")])
    with pytest.raises(AssertionError):
        assert [s.index for s in run.steps] == [0, 1, 2], [s.index for s in run.steps]
    # 桩确实让步号重了（不是判据莫名红了）
    assert len(set(s.index for s in run.steps)) < len(run.steps), [s.index for s in run.steps]
