"""判据：一步给多条调用是能力，不是错误动作（D-65）。

业主口径（逐字，唯一权威）：
「multi_call为什么还在错误计数？自动拆分做好了吗」
「修，且不再认为multi_call有问题」

## 这一条修的是什么

改前 `errorstats.ERROR_CATEGORIES` 里有一类 `multi_call`，含义逐字是"一步给了多条调用、
被拆开逐条执行"，而它和 `multi_call_executed_calls` 都算进 `total` / `role_total`。
真机 `projects/sylow3` 的一次数：148 条"错误动作"里，122 条是这两类
（38 个被拆分的步 + 84 条拆出来的调用），同期真错误只有 26 条。
也就是说"系统按设计把一步拆成几条"被记成了"出错了" —— 那是把正常行为记成错误。

改后：`multi_call` 这个类目名整个删掉（不是改名留着），拆分的两个数搬进过程读数表
（`PROCESS_CATEGORIES` 的 `steps_split` / `multi_call_executed_calls`），
既不进 `by_role`、也不进 `total` / `role_total`；多调用这一族只留三档真失败
（`multi_call_discarded` / `multi_call_unexecuted` / `multi_call_out_of_limit`），
三档全 0 才是绿。为什么删而不是降级留在同一张表里：留在错误表里就得靠每个调用点
记得"这一类不计错"，而那种纪律一定会漏，漏了不会有任何地方报错（分桶现在由
`_bump` 按类目决定，过程读数在结构上进不了 `total`）。

## 五条判据（每条都写了"改前红"在哪）

a) 一步 3 条调用且三条都执行 ⇒ 错误动作总数不因这一步增加（`total` 仍是 0）、
   `steps_split` +1、`multi_call_executed_calls` +3。
   改前红：`total` 是 4（1 个 `multi_call` + 3 条 `multi_call_executed_calls`）。
b) 丢 1 条（这一条解码不出来）⇒ `multi_call_discarded` +1，且这一类才进错误总数；
   另两档（没执行成 / 超上限）各进各的桶、三档互斥。
   改前红：这三个类目都不存在，丢的那条只留在逐条记录里，一处都不计。
c) 负控：单调用的一步 ⇒ `steps_split` 不增、错误总数不增、盘上一条逐条记录都没有。
   改前红：`steps_split` 这个名字都不存在（`ErrorStats` 没有 `process` 这一格）。
d) 反真空：把"拆分成功"打桩成"未拆分" ⇒ a 必红。两个方向各打一次桩
   （生产侧 `SD.catch_step_request` 只回第一条 / 读侧 `ES._is_split_step` 恒假）——
   只打一个方向的话，"读数到底跟着哪一侧走"这件事仍然没人钉。
   改前红：改前 `_assert_a` 在第一个 `total == 0` 上就红（那时 total 是 4），而桩打完之后
   逐条记录仍然在盘上 ⇒ d 自己那句"拆出来的三条不在了"当场红。
e) 类目表自洽：`multi_call` 不在 `ERROR_CATEGORIES`；三个新类目在码表里、`primary_code`
   认得它们；`steps_split` / `multi_call_executed_calls` 不在任何错误总数里
   （拿过程读数去问 `category_total` 会抛，不是回 0）；两张表不相交、合起来是 `ALL_CATEGORIES`。
   改前红：`multi_call` 就在错误表里，且 `primary_code("…已按顺序逐条…")` 返回错误类目。

判据里的模型是桩（按脚本回原生 `tool_calls`），全程离线、零花销。
"""
from __future__ import annotations

import json
import pathlib
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

SID = "d65"
#: 只读夹具读到的内容（它出现在结果里 ⇒ "这一条真的执行了"可核）。
SENTINEL = "SENTINEL-D65-三条都真的执行了"


# ---------------------------------------------------------------- 夹具（桩网关，不联网）


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


def _three_reads() -> dict:
    """一步 3 条只读调用（三条都合法、都会真的执行）。"""
    return {"tool_calls": [
        _call("fs_read", {"path": "data/sentinel.txt", "why": "读它"}, "c1"),
        _call("conductor_ledger", {"view": "stats"}, "c2"),
        _call("conductor_state", {}, "c3"),
    ]}


def _one_read() -> dict:
    """一步 1 条调用（负控：这一步不该被算成"被拆分"）。"""
    return {"tool_calls": [_call("fs_read", {"path": "data/sentinel.txt", "why": "读它"}, "c1")]}


def _read_then_a_call_that_decodes_to_nothing() -> dict:
    """一步 [合法, 解码不出]：第 2 条点了一个没广告过的函数 ⇒ 它被丢掉。"""
    return {"tool_calls": [
        _call("fs_read", {"path": "data/sentinel.txt", "why": "读它"}, "c1"),
        _call("fs_read_nonexistent", {"path": "data/sentinel.txt"}, "c2"),
    ]}


def _final(text: str = "做完了") -> dict:
    return {"tool_calls": [_call("framework_final", {"final": text, "evidence": []}, "c9")]}


def _wired(tmp_path: pathlib.Path, script: list[dict]) -> tuple[Any, Any, Any, Any, pathlib.Path]:
    root = tmp_path / "ws-M"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "sentinel.txt").write_text(SENTINEL, encoding="utf-8")
    st = Store(root)
    st.init()
    gw = _StubGateway(script)
    seam = LlmSeam(role="M", session_root=root, gateway=gw, price=(0.0, 0.0), sid=SID)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=root,
                         seam_factory=lambda role: seam, max_steps=6, store=st, sid=SID)
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=root)
    backend.registry = built.registry
    assert "fs.read" in built.registry.names(), built.skipped
    return st, cond, built.registry, seam, root


def _run(tmp_path: pathlib.Path, script: list[dict]) -> tuple[Any, pathlib.Path]:
    """跑一趟主控（全程离线），返回（那一趟的读数, 工作区根）。"""
    st, cond, registry, seam, root = _wired(tmp_path, script)
    run = run_role("M", "把 sentinel 读出来", store=st, registry=registry, conductor=cond,
                   seam=seam, workspace_root=str(root), sid=SID, max_steps=6, from_env=False)
    return run, root


def _events(root: pathlib.Path) -> list[dict]:
    records, problems = SS.read_session(root, sid=SID)
    assert not problems, problems
    return records


def _call_records(root: pathlib.Path) -> list[dict]:
    """逐条记录（`agent_step_call`）—— 拆分口径的"逐条可查"落在这里。"""
    return [e for e in _events(root) if str(e.get("kind") or "") == SD.STEP_CALL_EVENT]


def _stats(root: pathlib.Path) -> ES.ErrorStats:
    stats = ES.error_action_stats(root)
    assert stats.checked is True, stats.as_dict()
    return stats


#: 多调用这一族的三档真失败（拆分的失败长在这三类上，不是"被拆分"本身）。
REAL_FAILURES = ("multi_call_discarded", "multi_call_unexecuted", "multi_call_out_of_limit")


# ---------------------------------------------------------------- a) 拆分不进错误总数


def _assert_a(root: pathlib.Path) -> ES.ErrorStats:
    """a 的正身（d 把它当成"必红"的那一份断言）。"""
    stats = _stats(root)
    # 错误动作总数不因这一步增加：整个工作区一条错误都没有
    assert stats.total == 0, stats.as_dict()
    assert stats.by_role == {} and stats.role_total == {}, stats.as_dict()
    # 拆分这两格是过程读数：一步 +1、三条调用 +3
    assert stats.process_category_total("steps_split") == 1, stats.as_dict()
    assert stats.process_category_total("multi_call_executed_calls") == 3, stats.as_dict()
    assert stats.process_count("M", "steps_split") == 1, stats.as_dict()
    assert stats.process_count("M", "multi_call_executed_calls") == 3, stats.as_dict()
    # 三档真失败全 0（绿）：它们才是"拆分出事"的读数
    for cat in REAL_FAILURES:
        assert stats.category_total(cat) == 0, stats.as_dict()
    # 错误表里不该有任何 multi_call 这一族的东西
    assert not [c for c in stats.categories() if c.startswith("multi_call")], stats.categories()
    # 人读那一份：拆分是单独一栏，并且明说"不是错误"
    text = "\n".join(ES.render_text(stats))
    assert "拆分读数" in text and "不是错误" in text, text
    assert "steps_split" in text and "multi_call_executed_calls" in text, text
    # 机器读那一份：total 与 process 是两组键，谁也不含谁
    payload = stats.as_dict()
    assert payload["total"] == 0, payload
    assert payload["process"]["steps_split"] == 1, payload
    assert payload["process"]["multi_call_executed_calls"] == 3, payload
    assert "multi_call" not in payload["process"], payload
    return stats


def test_a_a_split_step_does_not_add_to_the_error_total(tmp_path: pathlib.Path) -> None:
    """a) 一步 3 条调用、三条都执行 ⇒ 错误总数不增；`steps_split` +1、拆出的调用 +3。

    改前红：`total` 会是 4（1 个 `multi_call` + 3 条 `multi_call_executed_calls`），
    而 `process_category_total("steps_split")` 连这个名字都没有。
    """
    run, root = _run(tmp_path, [_three_reads(), _final("读完了")])
    assert [s.shape for s in run.steps] == ["tool", "tool", "tool", "final"], run.to_dict()
    # 三条都真的执行了（拆分真的做了 —— 否则下面的读数就是在数一件没发生的事）
    recs = _call_records(root)
    assert [r["call_index"] for r in recs] == [0, 1, 2], recs
    assert [r["ok"] for r in recs] == [True, True, True], recs
    _assert_a(root)


# ---------------------------------------------------------------- b) 真失败才算错


def _call_record(role: str, index: int, *, outcome: str, reason: str,
                 call_index: int = 0, calls: int = 3) -> dict:
    """一条 `agent_step_call`（键集与 `agent_loop._land_step_call` 逐字一致）。"""
    return {
        "kind": SD.STEP_CALL_EVENT, "role": role, "index": index, "turn_index": 1,
        "call_index": call_index, "calls": calls, "shape": "tool", "tool": "fs.read",
        "ok": False, "outcome": outcome, "not_executed": True, "reason": reason,
        "elapsed_ms": 0, "usd": None,
    }


def _write_sessions(root: pathlib.Path, records: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "events.jsonl").write_text("", encoding="utf-8")
    folder = root / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "s1.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")


def test_b_the_three_real_failures_are_the_only_things_that_count(
        tmp_path: pathlib.Path) -> None:
    """b) 丢 1 条 ⇒ `multi_call_discarded` +1，且这一类才进错误总数；另两档各进各的桶。

    两半：一半是逐条记录的三种结局原话（三档互斥、一档一条），另一半是真机跑一趟
    "第 2 条解码不出来" —— 证明第一半的那些原话不是编的，是生产侧真的写下来的。
    改前红：这三个类目都不存在（`category_total` 连名字都没有），丢的那条一处都不计。
    """
    # ---- 前半：三条逐条记录，三种结局，各进各的桶
    ws = tmp_path / "ws-three"
    _write_sessions(ws, [
        _call_record("M", 0, outcome="未执行（解码不出：模型调用了一个没广告过的函数 'x'）",
                     reason="decode"),
        _call_record("M", 1, outcome="因本回合已收工未执行", reason="finished", call_index=1),
        _call_record("M", 2, outcome="因预算未执行", reason="budget", call_index=2),
    ])
    stats = ES.error_action_stats(ws)
    assert stats.checked is True, stats.as_dict()
    assert stats.category_total("multi_call_discarded") == 1, stats.as_dict()
    assert stats.category_total("multi_call_unexecuted") == 1, stats.as_dict()
    assert stats.category_total("multi_call_out_of_limit") == 1, stats.as_dict()
    # 三档互斥：一条记录只进一个桶（否则"丢了几条"这个数会与"没执行几条"重叠）
    assert stats.by_role["M"] == {"multi_call_discarded": 1, "multi_call_unexecuted": 1,
                                  "multi_call_out_of_limit": 1}, stats.by_role
    # 这一类才进错误总数（三档都在 total 里）
    assert stats.total == 3, stats.as_dict()
    assert sum(stats.role_total.values()) == stats.total, stats.as_dict()
    for cat in REAL_FAILURES:
        assert cat in stats.categories(), stats.categories()
    # 过程读数一格都没有（这三条都没执行）
    assert stats.process_categories() == {}, stats.process_categories()

    # ---- 后半：真机一趟 —— 第 2 条点了一个没广告过的函数 ⇒ 它被丢掉
    run, root = _run(tmp_path, [_read_then_a_call_that_decodes_to_nothing(), _final("改对了")])
    recs = _call_records(root)
    assert [r["call_index"] for r in recs] == [0, 1], recs
    assert [r["not_executed"] for r in recs] == [False, True], recs
    assert recs[1]["reason"] == "decode", recs[1]
    assert "解码不出" in str(recs[1]["outcome"]), recs[1]
    live = _stats(root)
    assert live.category_total("multi_call_discarded") == 1, live.as_dict()
    assert live.category_total("multi_call_unexecuted") == 0, live.as_dict()
    assert live.category_total("multi_call_out_of_limit") == 0, live.as_dict()
    # 它进错误总数（不是被挡在 total 之外）
    assert "multi_call_discarded" in live.categories(), live.categories()
    # 同一趟里那条 invalid 步另有它自己的类目（两件事分开记，互不吞并）
    assert live.total == (live.category_total("multi_call_discarded")
                          + live.category_total("judge_bad_json")), live.as_dict()
    assert live.category_total("judge_bad_json") == 1, live.as_dict()
    # 拆分这两格仍然是过程读数：一步被拆开、一条真的执行了
    assert live.process_category_total("steps_split") == 1, live.as_dict()
    assert live.process_category_total("multi_call_executed_calls") == 1, live.as_dict()


# ---------------------------------------------------------------- c) 负控：单调用的一步


def test_c_a_single_call_step_is_not_a_split(tmp_path: pathlib.Path) -> None:
    """c) 负控：单调用的一步 ⇒ `steps_split` 不增、错误总数不增、盘上没有逐条记录。

    改前红：`steps_split` 这个名字不存在（`ErrorStats` 没有 `process` 这一格）。
    """
    run, root = _run(tmp_path, [_one_read(), _final("读完了")])
    assert [s.shape for s in run.steps] == ["tool", "final"], run.to_dict()
    # 单条那一路根本不落逐条记录（`dispatch.multi` 为假）：拆分这件事没发生
    assert _call_records(root) == [], _call_records(root)
    stats = _stats(root)
    assert stats.process_categories() == {}, stats.as_dict()
    assert stats.total == 0, stats.as_dict()
    assert stats.by_role == {}, stats.as_dict()


# ---------------------------------------------------------------- d) 反真空


def test_d_the_split_reading_is_load_bearing(tmp_path: pathlib.Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 反真空：把"拆分成功"打桩成"未拆分" ⇒ a 必红（两个方向各打一次桩）。

    第一个方向打生产侧（`SD.catch_step_request` 只回第一条）：证明 a 的读数跟着
    真的发生了的拆分走，不是跟着某个常量走。
    第二个方向打读侧（`ES._is_split_step` 恒假）：证明 a 数的就是那个结构字段，
    换成"没拆过"的读数它就必红。
    """
    # ---- 方向一：生产侧只跑第一条
    real = SD.catch_step_request

    def _only_first(request: SD.StepRequest, *, decode: Any) -> SD.StepDispatch:
        got = real(request, decode=decode)
        return SD.StepDispatch(items=got.items[:1], turn_index=got.turn_index, requested=1)

    monkeypatch.setattr(SD, "catch_step_request", _only_first)
    _first_run, root = _run(tmp_path / "by-producer", [_three_reads(), _final("读完了")])
    with pytest.raises(AssertionError):
        _assert_a(root)
    # 拆出来的那三条不在了 ⇒ 拆分的读数也不该在
    assert _call_records(root) == [], _call_records(root)
    assert _stats(root).process_categories() == {}, _stats(root).as_dict()
    monkeypatch.undo()

    # ---- 方向二：读侧把"这一步被拆分"认成没拆分
    _run2, root2 = _run(tmp_path / "by-reader", [_three_reads(), _final("读完了")])
    assert _stats(root2).process_category_total("steps_split") == 1      # 桩打之前是 1
    monkeypatch.setattr(ES, "_is_split_step", lambda record: False)
    with pytest.raises(AssertionError):
        _assert_a(root2)
    assert _stats(root2).process_category_total("steps_split") == 0, _stats(root2).as_dict()
    # 其余两格不受影响：读侧这一个桩只该打掉"被拆分的步数"
    assert _stats(root2).process_category_total("multi_call_executed_calls") == 3


# ---------------------------------------------------------------- e) 类目表自洽


def test_e_the_category_tables_are_self_consistent(tmp_path: pathlib.Path) -> None:
    """e) `multi_call` 不在错误表；三个新类目在码表里且 `primary_code` 认得；两表不相交。

    改前红：`multi_call` 就在 `ERROR_CATEGORIES` 里，且 `primary_code` 把拆分那句汇总
    读成一个错误类目。
    """
    err_names = [cat for cat, _why in ES.ERROR_CATEGORIES]
    proc_names = [cat for cat, _why in ES.PROCESS_CATEGORIES]
    # `multi_call` 这个名字整个不在错误表里（删掉，不是改名留着）
    assert "multi_call" not in err_names, err_names
    assert "multi_call" not in ES.ERROR_CATEGORY_NAMES
    # 拆分那两个读数是过程读数，不是错误类目
    assert {"steps_split", "multi_call_executed_calls"} <= ES.PROCESS_CATEGORY_NAMES
    assert not ({"steps_split", "multi_call_executed_calls"} & ES.ERROR_CATEGORY_NAMES)
    # 两张表不相交，合起来就是 ALL_CATEGORIES（没有第三张表偷偷存在）
    assert not (set(err_names) & set(proc_names)), (err_names, proc_names)
    assert ES.ALL_CATEGORIES == ES.ERROR_CATEGORIES + ES.PROCESS_CATEGORIES
    assert ES.ERROR_CATEGORY_NAMES == frozenset(err_names)
    assert ES.PROCESS_CATEGORY_NAMES == frozenset(proc_names)
    # 三个新类目：在受控词表（CODE_TABLE）里，且 primary_code 认得它们
    for cat in REAL_FAILURES:
        assert cat in ES.ERROR_CATEGORY_NAMES, cat
        codes = [code for code, k, _where in ES.CODE_TABLE if k == cat]
        assert codes, f"{cat} 在码表里一个码都没有"
        assert all(c in ES.CODE_PROVENANCE for c in codes), codes
    assert ES.primary_code("未执行（解码不出：模型调用了一个没广告过的函数 'x'）") == (
        "未执行（解码不出", "multi_call_discarded")
    assert ES.primary_code("因本回合已收工未执行") == (
        "因本回合已收工未执行", "multi_call_unexecuted")
    assert ES.primary_code("因预算未执行") == ("因预算未执行", "multi_call_out_of_limit")
    # 拆分那句汇总不再是一个错误码（改前：它命中的类目叫 multi_call）
    assert ES.primary_code("这一步给了 3 条调用，已按顺序逐条：第 1 条 fs.read 成功") is None
    # 结构字段名那个码指向的是过程读数（不是错误）
    marker = ES.primary_code("multi_call")
    assert marker is not None and marker[1] in ES.PROCESS_CATEGORY_NAMES, marker

    # 拿过程读数去问"错误总数"会抛，而不是回 0（0 会把"口径错用"读成"这一类没有"）
    stats = ES.ErrorStats(
        by_role={"M": {"param_invalid": 1}}, role_total={"M": 1}, total=1,
        process={"M": {"steps_split": 5, "multi_call_executed_calls": 9}},
        checked=True, state="checked")
    assert stats.category_total("param_invalid") == 1
    assert stats.categories() == {"param_invalid": 1}, stats.categories()
    assert stats.total == 1
    for cat in ("steps_split", "multi_call_executed_calls"):
        with pytest.raises(ValueError):
            stats.category_total(cat)
        with pytest.raises(ValueError):
            stats.count("M", cat)
    # 过程读数照旧读得出来，且不在错误那一组键里
    assert stats.process_category_total("steps_split") == 5
    assert stats.process_category_total("multi_call_executed_calls") == 9
    assert stats.process_categories() == {"steps_split": 5, "multi_call_executed_calls": 9}
    payload = stats.as_dict()
    assert payload["by_role"] == {"M": {"param_invalid": 1}}, payload
    assert payload["total"] == 1, payload
    assert payload["process"] == {"steps_split": 5, "multi_call_executed_calls": 9}, payload
    assert payload["process_by_role"] == {
        "M": {"multi_call_executed_calls": 9, "steps_split": 5}}, payload
    # 人读那一份：错误表里没有 multi_call 这一族，拆分单独一栏
    text = "\n".join(ES.render_text(stats))
    assert "multi_call" not in text.split("拆分读数")[0], text
    assert "拆分读数" in text, text
