# -*- coding: utf-8 -*-
"""`R1-A1`（E5 给 D 接 LLM，A 线那一半）：D 的模型对象只认两类 + 三态读数 + 四条负控。

## 这一批治的两个缺陷（改前读数见 `temp/_r1a1_status_probe.py`）

1. 接口名字对不上：`_llm_refine` 原先写
   `self.llm.complete(prompt) if hasattr(self.llm, "complete") else self.llm(prompt)`，
   而标准缝 `llmseam.LlmSeam` 既没有 `complete` 也不可调用 ⇒ 拿到缝必然抛
   `TypeError: 'LlmSeam' object is not callable`，被 `_compose` 的 `except` 兜住
   ⇒ `llm_used` 恒为 `False`（"缝接上了、话说不通"，且没有判据会红）。
2. 三态被折叠：`llm_used=False` 同时表示"没接线"与"接了但这次失败"。
   现在每一次调用都留一格 `{kind,state,reason,model,calls,task_id}`。

判据分四组，对应需求单的四条负控；每组都能单独红（`_rank_min` 与 `invented_facts`
两条硬规则的负控在第三、四组）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow.agent_d import AgentD
from agentflow.agent_d._support import (KIND_CLIENT, KIND_SEAM, STATE_FAILED,  # noqa: F401
                                        STATE_NOT_WIRED, STATE_USED,
                                        invented_facts, model_kind)
from agentflow.llmseam import LlmSeam
from agentflow.store import Store


# --------------------------------------------------------------------- 替身

class _Reply:
    """模型回复的替身（缝那一层只读这几个字段）。"""

    def __init__(self, text: str = "", *, ok: bool = True, detail: str = "") -> None:
        self.ok = ok
        self.text = text
        self.tokens_in = 3
        self.tokens_out = 5
        self.error_detail = detail
        self.tool_calls: tuple = ()


class _Gateway:
    """假网关：按剧本回答（`raise_exc` / `reply` 二选一；记下被问过的提示词）。"""

    class spec:
        model = "fake-d-model"

    def __init__(self, *, reply: str = "", raise_exc: BaseException | None = None) -> None:
        self.reply = reply
        self.raise_exc = raise_exc
        self.prompts: list[str] = []

    def complete(self, prompt, *, scope="", system=None, max_tokens=None, tools=None):
        self.prompts.append(str(prompt))
        if self.raise_exc is not None:
            raise self.raise_exc
        return _Reply(self.reply)


class _BareClient:
    """裸 client（有 `.complete`）：D 认得的另一类对象。"""

    model_name = "bare-client"

    def __init__(self, reply: str = "", *, raise_exc: BaseException | None = None) -> None:
        self.reply = reply
        self.raise_exc = raise_exc
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.reply


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _seam(st: Store, *, reply: str = "", raise_exc: BaseException | None = None,
          wired: bool = True) -> tuple[LlmSeam, _Gateway]:
    gw = _Gateway(reply=reply, raise_exc=raise_exc)
    seam = LlmSeam(role="D", session_root=pathlib.Path(st.root),
                   gateway=(gw if wired else None), sid="r1a1")
    return seam, gw


EV = {
    "question": "群与环之间有没有已知的等价链？",
    "claims": [
        {"relation_id": "0000", "lit_id": "0001", "quote": "An abelian group is a group.",
         "description": "阿贝尔群的定义", "quote_verified": True, "status": "active"},
    ],
}
VERDICT = {"confidence": "low", "criteria": [{"id": "C1", "detail": "证据少"}], "hits": {},
           "degree": 1, "verified_count": 1, "contradictions": []}


def _good_json(confidence: str = "low", analysis: str = "模型写的分析（引 rel:0000）") -> str:
    return json.dumps({"analysis": analysis, "conclusion": "结论（低）",
                       "suggestions": ["再查一轮"], "confidence": confidence},
                      ensure_ascii=False)


def _compose(d: AgentD) -> tuple[tuple, dict]:
    out = d._compose(dict(EV), dict(VERDICT))
    return out, dict(getattr(d, "last_llm_reading", {}) or {})


# ======================================================= ① 接口：缝必须真的被调用

def test_a_seam_is_recognised_and_actually_called(tmp_path: pathlib.Path):
    """负控①（改前必红）：给 D 一个标准缝 ⇒ 必须走 `ask_json` 拿到结果。

    改前：`TypeError: 'LlmSeam' object is not callable`（读数：状态探针 (b) 那一行），
    `llm_used=False`、且没有任何判据会红。
    改后：`llm_used=True`、缝真的被问过一次、读数 `kind=seam / state=used`。
    """
    st = _ws(tmp_path)
    seam, gw = _seam(st, reply=_good_json())
    d = AgentD(st, config={}, llm=seam)

    assert model_kind(seam) == KIND_SEAM, "标准缝必须被认成 seam（判据只有一处）"
    (analysis, conclusion, suggestions, llm_used), reading = _compose(d)
    assert llm_used is True, reading
    assert reading["kind"] == KIND_SEAM and reading["state"] == STATE_USED, reading
    assert reading["model"] == "fake-d-model" and reading["calls"] == 1, reading
    assert seam.spend.calls == 1, "缝那一层必须真的发过一次（不是我们自己假装用了）"
    assert len(gw.prompts) == 1 and "relation_id" in gw.prompts[0], "提示词要带上证据包"
    assert analysis and conclusion, (analysis, conclusion)


def test_a_bare_client_still_works(tmp_path: pathlib.Path):
    """另一类对象（裸 client，有 `.complete`）必须照旧能用 —— 修接口不许只修一半。"""
    st = _ws(tmp_path)
    client = _BareClient(_good_json())
    d = AgentD(st, config={}, llm=client)
    assert model_kind(client) == KIND_CLIENT
    (_, _, _, llm_used), reading = _compose(d)
    assert llm_used is True and client.calls == 1, (reading, client.calls)
    assert reading["kind"] == KIND_CLIENT and reading["state"] == STATE_USED, reading


def test_an_object_that_is_neither_says_so_instead_of_guessing(tmp_path: pathlib.Path):
    """第三种 `hasattr` 猜法不许再有：认不出的对象要如实报，不许当成"没接线"。"""
    st = _ws(tmp_path)

    class _Weird:
        pass

    d = AgentD(st, config={}, llm=_Weird())
    (_, _, _, llm_used), reading = _compose(d)
    assert llm_used is False and reading["state"] == "unknown_object", reading
    assert "认不出" in reading["reason"], reading


# ======================================================= ② 四种失败各留各的原因

def test_not_wired_is_not_folded_into_failed(tmp_path: pathlib.Path):
    """三态①：没接线的缝 ⇒ `state=not_wired`（不是 `failed`）。

    改前这一档也被同一句 `TypeError` 吃掉：连"没接线"这个语义都读不出来。
    """
    st = _ws(tmp_path)
    seam, _ = _seam(st, wired=False)          # 有缝、没 key
    d = AgentD(st, config={}, llm=seam)
    (_, _, _, llm_used), reading = _compose(d)
    assert llm_used is False, reading
    assert reading["state"] == STATE_NOT_WIRED, reading
    assert "judge_not_wired" in reading["reason"], reading

    d2 = AgentD(st, config={}, llm=None)      # 连缝都没有
    (_, _, _, used2), reading2 = _compose(d2)
    assert used2 is False and reading2["state"] == STATE_NOT_WIRED, reading2


def test_the_four_failure_modes_each_leave_their_own_reason(tmp_path: pathlib.Path):
    """三态②：四种失败各自的原因都要读得到，且都回退到确定性那一档。

    四种：缝抛异常 / 超时 / 回坏 JSON / 空回复。改前它们与"没接线"长得一样
    （都是一句 `llm_used=False`，原因只留在内存的 `last_tool_errors` 里）。

    注意"空回复"落的是 `judge_bad_json`（缝自己的词表：`ok=True` 但文本为空 ⇒ 解析不出
    对象），而它的 detail 逐字写着"LLM 返回为空" —— 于是这两档仍然分得开。
    """
    st = _ws(tmp_path)
    cases = [
        ("抛异常", dict(raise_exc=RuntimeError("boom-d")), "judge_failed", "boom-d"),
        ("超时", dict(raise_exc=TimeoutError("slow")), "judge_timeout", "slow"),
        ("坏 JSON", dict(reply="这不是 JSON，只是一段散文"), "judge_bad_json", "这不是 JSON"),
        ("空回复", dict(reply=""), "judge_bad_json", "返回为空"),
    ]
    seen: list[str] = []
    for name, kw, expect, needle in cases:
        seam, _ = _seam(st, **kw)
        d = AgentD(st, config={}, llm=seam)
        (analysis, conclusion, _, llm_used), reading = _compose(d)
        assert llm_used is False, (name, reading)
        assert reading["state"] == STATE_FAILED, (name, reading)
        assert expect in reading["reason"], (name, reading)
        assert needle in reading["reason"], (name, reading)
        # 回退到确定性：分析里必须出现确定性那一档的判据行（证据量那一句）
        assert "证据量" in analysis, (name, analysis[:120])
        seen.append(reading["reason"])
    assert len(set(seen)) == len(cases), f"四种失败的原因不许压成一句：{seen}"


def test_a_failing_bare_client_also_leaves_a_reason(tmp_path: pathlib.Path):
    """裸 client 那一路的失败同样要留原因（不许只有缝那一半修好了）。"""
    st = _ws(tmp_path)
    d = AgentD(st, config={}, llm=_BareClient(raise_exc=RuntimeError("client down")))
    (_, _, _, llm_used), reading = _compose(d)
    assert llm_used is False and reading["state"] == STATE_FAILED, reading
    assert "client down" in reading["reason"], reading


# ======================================================= ③ 成功注入 + 置信度兜底

def test_success_cannot_raise_the_confidence_above_the_deterministic_rank(
        tmp_path: pathlib.Path):
    """负控③：模型回 `high` 而确定性档是 `low` ⇒ 必须仍是 `low`（`_rank_min` 兜底）。

    这条与接口那条是两件事：接口修好后模型能说话了，而"不许把置信度拔高"
    仍然由代码兜底（不依赖模型守规矩）。
    """
    st = _ws(tmp_path)
    seam, _ = _seam(st, reply=_good_json(confidence="high"))
    d = AgentD(st, config={}, llm=seam)
    (_, conclusion, _, llm_used), reading = _compose(d)
    assert llm_used is True and reading["state"] == STATE_USED, reading
    assert reading.get("confidence_clamped") is True, reading
    assert "低" in conclusion, conclusion
    assert any("拔高" in str(e.get("error")) for e in d.last_tool_errors), d.last_tool_errors


# ======================================================= ④ 不许引入新事实

def test_an_invented_reference_discards_the_whole_refinement(tmp_path: pathlib.Path):
    """负控④：模型引了证据包里没有的 `rel:` ⇒ 整份丢弃本次精修并如实记原因。

    两类都查：台账引用（`rel:` / `lit:`）与 `「…」` 里的"逐字引文"
    （引文必须真的是某条证据引文的连续子串 —— 提示词里那条硬规则的代码化）。
    """
    st = _ws(tmp_path)
    # (a) 台账引用：`rel:9999` 不在证据包里
    seam, _ = _seam(st, reply=_good_json(analysis="见 rel:9999 与 rel:0000"))
    d = AgentD(st, config={}, llm=seam)
    (analysis, _, _, llm_used), reading = _compose(d)
    assert llm_used is False, reading
    assert reading["state"] == STATE_FAILED and "llm_invented_facts" in reading["reason"], reading
    assert "rel:9999" in reading["reason"], reading
    assert "证据量" in analysis, "被丢弃时应当回退到确定性那一档"
    # (b) 逐字引文：模型自己编了一句「…」
    seam2, _ = _seam(st, reply=_good_json(
        analysis="原文说「这是一句证据包里根本没有的引文内容」"))
    d2 = AgentD(st, config={}, llm=seam2)
    (_, _, _, used2), reading2 = _compose(d2)
    assert used2 is False and "llm_invented_facts" in reading2["reason"], reading2
    # (c) 反负控：引的是证据包里真有的那些 ⇒ 不许误杀
    seam3, _ = _seam(st, reply=_good_json(
        analysis="见 rel:0000；原文「An abelian group is a group.」"))
    d3 = AgentD(st, config={}, llm=seam3)
    (_, _, _, used3), reading3 = _compose(d3)
    assert used3 is True and reading3["state"] == STATE_USED, reading3


def test_invented_facts_reads_the_evidence_pack_not_a_word_list():
    """判据本身的负控（纯函数）：证据包里有的编号/引文不报，没有的才报。"""
    known_ids, known_lits = ["0000"], ["0001"]
    known_quotes = ["An abelian group is a group."]
    assert invented_facts("引 rel:0000 与 lit:0001，原文「An abelian group is a group.」",
                          known_relation_ids=known_ids, known_lit_ids=known_lits,
                          known_quotes=known_quotes) == []
    got = invented_facts("引 rel:0007 与 lit:0009，原文「完全不是原文的一句话内容」",
                         known_relation_ids=known_ids, known_lit_ids=known_lits,
                         known_quotes=known_quotes)
    assert got == ["lit:0009", "rel:0007", "「完全不是原文的一句话内容…」"], got


# ======================================================= ⑤ 召唤号与花销（P-09 的键）

def test_the_summon_number_is_reported_and_never_faked(tmp_path: pathlib.Path):
    """`llm_task_id`（P-09 的挂点）：号在 ⇒ 读数带号且账本按号读；号不在 ⇒ 如实说"没号"。

    三态（需求单第 3 条）—— 这三档必须分得开：

    | 情形 | `attached` | `usd` |
    |---|---|---|
    | 没号（装配层没把召唤号递下来） | `False` | `None`（"这笔钱没有挂点"） |
    | 有号、账上一条都没有 | `True` | `0.0`（"挂上了但还没记过账"） |
    | 有号、有账 | `True` | 汇总 |

    粒度维持召唤级（以 `task_id` 为键，与 `tokenmeter.usd_reading` 同一算式），
    同一个召唤内多次调用由 `calls` 标注（"这一次召唤内调用了几次"）。
    """
    from agentflow.tokenmeter import Charge, TokenMeter

    # (a) 没号
    st = _ws(tmp_path)
    seam, _ = _seam(st, reply=_good_json())
    d0 = AgentD(st, config={}, llm=seam)
    (_, _, _, used0), r0 = _compose(d0)
    assert used0 is True and r0["task_id"] == "", r0
    assert r0["spend"]["attached"] is False and r0["spend"]["usd"] is None, r0["spend"]
    assert "没有挂点" in r0["spend"]["reason"], r0["spend"]

    # (b) 有号、账上有一笔 ⇒ 汇总跟着号走（这一笔钱真的被读出来）
    st2 = _ws(tmp_path / "b")
    TokenMeter(st2).charge(Charge(role="D", scope="reason", tokens_in=10, tokens_out=5,
                                  usd=0.375, task_id="t-0042", note="D 的一次召唤"))
    seam2, _ = _seam(st2, reply=_good_json())
    d1 = AgentD(st2, config={"llm_task_id": "t-0042"}, llm=seam2)
    (_, _, _, used1), r1 = _compose(d1)
    assert used1 is True and r1["task_id"] == "t-0042", r1
    assert r1["spend"]["attached"] is True and r1["spend"]["usd"] == 0.375, r1["spend"]
    assert r1["spend"]["entries"] == 1 and r1["calls"] == 1, r1

    # (c) 有号、账上一条都没有 ⇒ 0.0 但 attached=True（与"没号"分得开）
    st3 = _ws(tmp_path / "c")
    seam3, _ = _seam(st3, reply=_good_json())
    d2 = AgentD(st3, config={"llm_task_id": "t-9999"}, llm=seam3)
    (_, _, _, _), r2 = _compose(d2)
    assert r2["spend"]["attached"] is True and r2["spend"]["usd"] == 0.0, r2["spend"]
    assert "还没记过账" in r2["spend"]["reason"], r2["spend"]


def test_d_has_no_way_to_guess_the_number_today(tmp_path: pathlib.Path):
    """不在召唤里 ⇒ 空串（空串 = 没挂点，不是零号）。

    `R1-A1-a` 已把"当前召唤号"那一支 ContextVar 落在 `conductor.py`（与取消令牌同构），
    但它只在召唤内部 set ⇒ 离线夹具/裸构造读到的仍是空串。真要拿号，
    走 `conductor.summon(...)` 那一条路（`⑥` 那两条判据钉的就是它）。
    """
    from agentflow.agent_d._support import current_summon_task_id

    assert current_summon_task_id() == "", "不在召唤里 ⇒ 空串（不是零号）"
    st = _ws(tmp_path)
    seam, _ = _seam(st, reply=_good_json())
    d = AgentD(st, config={}, llm=seam)
    assert d.llm_task_id == "" and d._summon_task_id() == "", d.llm_task_id


# ======================================================= ⑥ 召唤号：并发负控与复位

def test_two_concurrent_summons_each_see_their_own_task_id(tmp_path: pathlib.Path):
    """负控（裁定 1.2）：并发两次召唤 ⇒ 两次读到的号各自正确，且用完复位。

    为什么必须并发测：`LocalBackend.resolve(role)` 按角色缓存实例 ⇒ 两个召唤共用同一个
    对象；号若挂在实例属性上会互相覆盖（读出来的成本挂到别人的单子上）。
    两支线程在 handler 里同刻会合（`Barrier`），确保真的重叠。
    """
    import threading

    from agentflow.conductor import Conductor, LocalBackend, current_task_id

    st = _ws(tmp_path)
    barrier = threading.Barrier(2, timeout=20)

    class _Probe:
        def poll(self) -> dict:
            barrier.wait()                       # 同刻并发（不重叠就会超时报错）
            return {"seen": current_task_id()}

    cond = Conductor(st, backend=LocalBackend({"D": _Probe()}))
    got: dict[int, tuple] = {}

    def run(i: int) -> None:
        res = cond.summon("D", "poll", {})
        got[i] = (str(res.task_id or ""), str((res.payload or {}).get("seen") or ""))

    threads = [threading.Thread(target=run, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 2, got
    for i, (tid, seen) in got.items():
        assert tid, (i, got)
        assert seen == tid, f"第 {i} 支召唤读到的号不是自己的：{got}"
    assert got[0][0] != got[1][0], f"两次召唤应当是两条台账行：{got}"
    assert current_task_id() == "", "调用结束必须复位（finally），否则会漏给下一次调用"


def test_the_summon_number_is_reset_even_when_the_handler_raises(tmp_path: pathlib.Path):
    """负控（裁定 1.2 的另一半）：handler 抛异常时号也要复位（`finally` 那一处）。"""
    from agentflow.conductor import Conductor, LocalBackend, current_task_id

    st = _ws(tmp_path)

    class _Boom:
        def poll(self) -> dict:
            assert current_task_id(), "进 handler 时号必须在（否则这条负控失去对象）"
            raise RuntimeError("boom-in-handler")

    cond = Conductor(st, backend=LocalBackend({"D": _Boom()}))
    cond.summon("D", "poll", {})                 # 异常被收成 failed（不是让调用方崩）
    assert current_task_id() == "", "异常路径也必须复位"


# ======================================================= ⑦ register_conjecture（裁定 2）

def test_register_conjecture_polishes_but_never_writes_the_model_words(
        tmp_path: pathlib.Path):
    """裁定 2：`register_conjecture` 按同一形态接模型 —— 复述进读数，绝不进库。

    现算它才是当前树里 D 的真主力（191 次召唤 / 29 条会话行）⇒ 纳入"在用"。
    硬约束：登记与否、字段取什么值仍是确定性判定；模型只把已有产物写得更通顺。
    """
    st = _ws(tmp_path)
    seam, gw = _seam(st, reply=json.dumps({"restatement": "这条猜想说的是 n≥3 的那个族非空",
                                           "next_check": "先做 n=3 的枚举"},
                                          ensure_ascii=False))
    d = AgentD(st, config={}, llm=seam)
    out = d.register_conjecture(statement="n≥3 时该族非空。", origin="gap",
                                testable=_TESTABLE)
    reading = dict(out["llm_reading"])
    assert reading["state"] == "used" and reading["calls"] == 1, reading
    assert reading["restatement"] and reading["next_check"], reading
    assert reading["spend"]["attached"] is False, reading["spend"]     # 没号 ⇒ 没挂点
    assert len(gw.prompts) == 1, "缝必须真的被问过一次"
    # 模型的话不进库：那一行里既没有 restatement，statement 也还是调用方给的那句
    row = st.rows("conjectures")[0]
    assert "restatement" not in row and "next_check" not in row, row
    assert "该族非空" in str(row.get("statement") or ""), row


#: `register_conjecture` 的必填可检验形式（三个键都要给，见 `specs/d.py` 的声明）。
_TESTABLE = {"parameters": "n 的取值范围", "criterion": "枚举 n=3 的最小情形",
             "falsified_by": "找到一个 n≥3 的反例"}


def test_register_conjecture_still_registers_when_the_model_fails(tmp_path: pathlib.Path):
    """fail-open：模型失败（异常）⇒ 库照写，读数如实说是哪一种失败。"""
    st = _ws(tmp_path)
    seam, _ = _seam(st, raise_exc=RuntimeError("llm down"))
    d = AgentD(st, config={}, llm=seam)
    out = d.register_conjecture(statement="n≥3 时该族非空。", origin="gap",
                                testable=_TESTABLE)
    assert st.rows("conjectures"), "登记是确定性判定：模型失败也必须已经落库"
    reading = dict(out["llm_reading"])
    assert reading["state"] == "failed" and "llm down" in reading["reason"], reading
    assert "restatement" not in reading, reading


def test_register_conjecture_discards_a_restatement_that_invents_a_reference(
        tmp_path: pathlib.Path):
    """同一形态的另一半：复述里引了这条猜想依据里没有的编号 ⇒ 丢弃那段产出。"""
    st = _ws(tmp_path)
    seam, _ = _seam(st, reply=json.dumps({"restatement": "见 lit:9999 的实验",
                                          "next_check": "照 lit:9999 做"},
                                         ensure_ascii=False))
    d = AgentD(st, config={}, llm=seam)
    out = d.register_conjecture(statement="n≥3 时该族非空。", origin="gap",
                                testable=_TESTABLE)
    assert st.rows("conjectures"), "登记本身不受影响"
    reading = dict(out["llm_reading"])
    assert reading["state"] == "failed" and "llm_invented_facts" in reading["reason"], reading
    assert "restatement" not in reading, "编的那段不许留在读数里"
