# -*- coding: utf-8 -*-
"""L 的协作面按业主 2026-10-22 晚的最终裁定接线（七条判据，每条都写明改前红）。

## 裁定原文（逐字，照做，不扩大也不缩小）

> 「L 的协作面特别简单：只有 B 可以派 L，L 允许派 C 来梳理证明链，消费 B 的定理证明库，
>   可向 B 汇报形式化过程中遇到的困难、要求 B 完善证明并重新得到 V 签，
>   若缺陷严重，B 应通知 D 开展研究处理证明难点。」

## 七条判据与它们各自"改前红"的形态（改前 = 本文件加进来时的那棵树）

| # | 判据 | 改前红（实测原文见交付回报） |
|---|---|---|
| 1 | 边表：B→L 唯一入边；L→C 唯一出边；L 无其它出边；无其它角色→L；M 不含 L | `edges["B"]` 是 `{C,H,V}`（没有 L）、`edges["L"]` 是空集、L 在 `NON_SUMMONABLE` 里 ⇒ 三条断言当场红 |
| 2 | 开关关：上述四条边与 L 全部不可见（角色表 / 工具面 / 名册 / 提示词 0 处） | 现象同上："开关关着时 L 本来就不存在"这一条改前是绿的（那时它压根没有边），所以这一条真正红的是它的正控那一半（开关开着时 B→L 必须通） |
| 3 | L 读 B 的库：12 步 proof ⇒ `b_library` 读数齐全；不存在的编号 ⇒ 拒且不写盘 | 改前返回值里没有 `b_library` 这一格 ⇒ `KeyError` / 断言红；`coverage` 里也没有 |
| 4 | L→B 汇报：造一次"漏一步"的形式化失败 ⇒ B 的收件箱里出现一条汇报（含 stmt_id 与失败类型） | 改前 `formalize` 的失败只落在返回值里，一条消息都没有 ⇒ B 的收件箱是空的 |
| 5 | B 重做后重新过 V：B 覆盖 canonical ⇒ `proof_history` 有旧文 ⇒ 再跑 V 的 `verify_proof` ⇒ 签更新 | 改前这条链的每一格都已有（B/V 那两件是既有机制），本文件把它当成"接线之后仍然成立"的正控；它红的方式是接线改坏了（例如 B 的写路径被收紧成只增不改） |
| 6 | B→D 升级走模型真能走的那条路（`summon` 形状派 D）：边在、D 可召唤、`policy.check` 放行 B→D 且 B 的越权边照旧 `forbidden_edge`；改前那个 `AgentB.escalate_proof_research` 程序入口已退场（它不在动作表里 ⇒ 模型照它调只会 `unknown_action`） | 两条腿：改前红的是"已退场"那半（改前 `hasattr(AgentB, "escalate_proof_research")` 为真、模块在盘上 ⇒ 断言当场红）；正控那半（边 / 召唤面 / 闸）改前就绿，它守的是"迁移没有把路一起删掉" |
| 7 | 反真空：把"只有 B 能派 L"的判据 monkeypatch 成恒真 ⇒ 判据 1 必红 | 若判据 1 只在一张好表上成立，它可能在读一句恒真的话；把判据替换成恒过之后它必须变红 |

## 零模型

全部用例只调确定性代码（`AgentL` / `AgentB` / `AgentV` 与 `agent_loop` 的留言面），
零次模型请求。真 Lean 不是必需的：判据 3/4 只读"库"与"汇报"，形式化结论本身
在开关关着时按既有口径是 `unknown`（这一格由 `test_l_is_isolated_when_lean_is_off.py` 守）。

## 临时文件

工作区都在 pytest 的 `tmp_path` 下（`.lean` / `steps.jsonl` / 会话 jsonl 随 tmp 一起清掉）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import agent_loop as AL
from agentflow import capabilities as C
from agentflow import schema as S

#: 被形式化的那条命题（B 登记的原文）。
CLAIM = "forall n : Nat, n + 0 = n"
#: 命题台账里那一行的编号与标题。
STMT_ID = "000001"
LABEL = "加零不改变自然数"
#: 会话号（留言落点用它；不由环境变量决定，判据才可复现）。
SID = "t"

#: 本机那一版真 Lean（绝对路径；PATH 上的 lean 可能是另一个东西）。
#: 真 Lean 的落点：`AGENTFLOW_LEAN_BIN` 优先、没设才退回本机那一版 —— 取值点只有一处
#: （`tests/conftest.py` 的 `lean_path()`；本文件不再写第二份绝对路径）。
from conftest import lean_path, restore_lean_baseline

LEAN = lean_path()

#: 面向模型/用户的"其余角色"（判"无其它角色→L"时逐条数）。
OTHER_ROLES = tuple(role for role in S.ROLES if role != "L") + (S.CONDUCTOR_ROLE,)

#: 十二步的证明链（空行分段 ⇒ `split_proof_steps` 切出 12 步）。
LINKS = 11


# ============================================================ 夹具与小工具


def _lean_env(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    """把 Lean 开关钉到某一档（关着时不起子进程，判据因此是零成本的）。"""
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1" if on else "0")
    if on and LEAN.is_file():
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _proof_text(steps: int = LINKS + 1) -> str:
    """`steps` 步的证明链（一步一段，步号写在正文里）。"""
    parts = []
    for k in range(1, steps + 1):
        if k == 1:
            parts.append("第 1 步：由定义把 n + 0 展开成 n。")
        else:
            parts.append(f"第 {k} 步：把第 {k - 1} 步的结论代入一次并化简。")
    return "\n\n".join(parts)


def _source(mapped: int = LINKS + 1) -> str:
    """Lean 源码：`-- step k` 标出前 `mapped` 步的落点（第 mapped+1 步之后没有标记）。"""
    lines = [
        "import Init.Data.Nat.Basic",
        "",
        "namespace LProbe",
        "",
        "/-- 加零不改变自然数。 -/",
        "theorem add_zero_probe (n : Nat) : n + 0 = n := rfl",
    ]
    for k in range(1, mapped + 1):
        lines.append(f"-- step {k}")
    lines += ["", "end LProbe", ""]
    return "\n".join(lines)


def _workspace(tmp_path: pathlib.Path, *, steps: int = LINKS + 1) -> tuple[object, pathlib.Path, str]:
    """建一个工作区 + 一条 B 登记的命题（`proof_text` 是 `steps` 步的证明链）。"""
    from agentflow.store import Store

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    proof = _proof_text(steps)
    with st.tx("statements", actor="agent-B") as tx:
        tx.upsert("statements", {
            "stmt_id": STMT_ID,
            "label": LABEL,
            "statement": CLAIM,
            "statement_full": CLAIM,
            "proof_text": proof,
            "evidence_kind": "heuristic",
            "status": "active",
# 2026-11-17（语义纠正）：`derived_from` / `source_lit_id` 是可选信息（`origin` 只是状态：自产/引用）；这一份夹具不测来路。
            "origin": "own_result", "derived_from": ["999999"],
            "quote_reason": "自产命题（这一组判据不涉及外部原文）",
        }, note="probe:statement")
    return st, ws, proof


def _agent_l(st: object, ws: pathlib.Path):
    """L 的真实现（零模型；会话落点显式给，留言判据才可复现）。"""
    from agentflow.agent_l import AgentL

    return AgentL(st, workspace_root=ws,
                  config={"session_root": str(ws), "sid": SID})


def _agent_b(st: object, ws: pathlib.Path):
    """B 的真实现（零模型调用：这条路只碰 store 与会话）。"""
    from agentflow.agent_b import AgentB

    return AgentB(st, extractor=None, extract_text=None,
                  config={"session_root": str(ws), "sid": SID})


class _Seam:
    """照剧本回答的替身模型缝（V 要一个"模型"，这里给一份写死的结论）。"""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str, **_kw: object) -> object:
        from types import SimpleNamespace

        self.prompts.append(prompt)
        text = self.replies.pop(0) if self.replies else ""
        return SimpleNamespace(text=text, problem="" if text else "judge_not_wired")


def _verdict_json(verdict: str, *, step: int = 0) -> str:
    """V 的结论（`有毛病` 必须带 findings，见 `verifications.parse_verdict`）。"""
    if verdict == "成立":
        return json.dumps({"verdict": "成立", "findings": []}, ensure_ascii=False)
    return json.dumps({
        "verdict": verdict,
        "defect_step": step,
        "findings": [{"level": "error", "step": step, "kind": "缺一步",
                      "detail": f"第 {step} 步没有依据"}],
    }, ensure_ascii=False)


def _inbox(ws: pathlib.Path, role: str) -> list[dict]:
    """某个角色的收件箱（`agent_loop.read_messages` 是收件箱的唯一读法）。"""
    msgs, problems = AL.read_messages(ws, role, sid=SID)
    assert problems == [], problems
    return [dict(m) for m in msgs]


class _SecCall:
    """`llmseam.SeamCall` 的替身：`Secretary.judge()` 只读 ok / problem / detail。"""

    ok = True
    problem = ""
    detail = ""


class _SecSeam:
    """V 的秘书那一档的离线替身缝（只答两件事：V 的回复没问题 / 这一签发）。

    2026-10-29 口径：签由 V 的秘书判、也由它落盘。没有这条缝时 `signed_bit3` 恒为假
    —— 那是装配缺失，不是"这条链断了"。
    """

    wired = True

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict, _SecCall]:
        from agentflow import secretary as SEC

        kind = note.split(":", 1)[-1]
        if kind == "sign_issuance":
            doc = {"decision": SEC.SIGN_ISSUE, "reason": "夹具：三次成立都干净 ⇒ 发签",
                   "basis": ["夹具"]}
        else:
            doc = {"decision": SEC.V_REPLY_CLEAN, "reason": "夹具：照规则判 clean",
                   "basis": ["夹具"]}
        return dict(doc), _SecCall()


def _v_agent(st: object, ws: pathlib.Path, replies: list[str]):
    """V 和它的秘书（V 的结论走 `_Seam` 的剧本，秘书那一档走 `_SecSeam`；零模型钱）。"""
    from agentflow import secretary as SEC
    from agentflow.agent_v import AgentV

    sec = SEC.Secretary("V", root=ws, store=st, seam=_SecSeam(), enable_model=True)
    return AgentV(st, workspace_root=ws, llm=_Seam(replies), secretary=sec)


def _reviews_until_signed(agent: object, sid: str, text: str) -> list[dict]:
    """同一份正文审到发签门槛，返回那一趟的返回（这一趟里就已经签上了）。

    2026-10-29 口径：同一份正文（同 `proof_sha256`）必须连续 `SIGN_STREAK_NEED` 次
    「成立」且秘书判定通过才落签；第 1、2 次只落台账。2026-10-30 起这几次发生在
    同一次调用的多转里（业主口径：V 判没问题后连续再判，不是 F 交三次）⇒
    "前几转不签、最后一转才签"这条正控改从 `review_passes` 的逐转读数里读，
    判据的对手方（改前是一次成立就签）没变。
    """
    from agentflow import verifications as VR

    need = int(VR.SIGN_STREAK_NEED)
    got = agent.verify_proof(sid, proof_text=text)
    assert got.get("checked") is True, got
    passes = got.get("review_passes") or []
    assert len(passes) == need, (
        f"这一趟自己连判了 {len(passes)} 转（门槛 {need} 转）⇒ "
        f"「连续再判」没接上，或者上界与门槛漂了：{passes}")
    assert [p.get("issued") for p in passes] == [False] * (need - 1) + [True], (
        f"逐转的发签读数是 {[p.get('issued') for p in passes]} —— 2026-10-29 口径："
        f"同一份正文连续 {need} 次「成立」且秘书判定通过才发签（前几转只落台账）")
    assert got.get("signed_bit3") is True, (
        f"最后一转应当签上第 3 位；读到的发签决定：{got.get('sign_issuance')}", got)
    return [got]


# ============================================================ 1. 边表就是裁定说的那一个面
#: 反真空用的坏表：A → L（裁定说只有 B 可以派 L）。
_BAD_EDGES = {role: frozenset(targets) for role, targets in C.ALLOWED_EDGES.items()}
_BAD_EDGES["A"] = frozenset(set(_BAD_EDGES.get("A") or ()) | {"L"})


def _edge_violations(edges: dict) -> list[str]:
    """「B→L 唯一入口 + L→C 唯一出边」的判据本体（纯函数：反真空那一条替换的正是它）。

    返回违反项（空清单 = 边表就是裁定说的那一个面）。刻意做成纯函数，是因为
    判据 7 要把它 monkeypatch 成恒真，再看判据 1 会不会红。
    """
    bad: list[str] = []
    inbound = sorted(role for role, targets in edges.items() if "L" in (targets or ()))
    if inbound != ["B"]:
        bad.append(f"指向 L 的入边不是只有 B：{inbound}")
    allowed_l = frozenset(edges.get("L") or ())
    if allowed_l != frozenset({"C"}):
        bad.append(f"L 的出边不是恰好一条 C：{sorted(allowed_l)}")
    for role in OTHER_ROLES:
        if role in ("B", "L"):
            continue
        if "L" in (edges.get(role) or ()):
            bad.append(f"{role} 的出边里出现了 L（裁定：只有 B 可以派 L）")
    if "L" in (edges.get(S.CONDUCTOR_ROLE) or ()):
        bad.append("M 的出边里出现了 L（主控不许直连 L）")
    extra = sorted(allowed_l - {"C"})
    if extra:
        bad.append(f"L 派了 C 之外的角色：{extra}")
    return bad


def test_one_b_can_cast_l_and_l_can_only_cast_c() -> None:
    """判据 1：边表就是裁定说的那一个面（B→L 唯一、L→C 唯一、M 不含 L）。

    改前红：`edges["B"]` 是 `{C,H,V}`（没有 L）、`edges["L"]` 是空集 ⇒ 下面
    第一组断言当场红。
    """
    edges = C.ALLOWED_EDGES
    assert sum(len(v) for v in edges.values()) >= 30, (
        f"边表几乎是空的 ⇒ 下面的断言会变成真空：{ {k: len(v) for k, v in edges.items()} }")
    assert _edge_violations(edges) == [], _edge_violations(edges)
    # 逐条写出来（读者不看判据函数也知道裁定说了什么）
    assert "L" in edges["B"], f"B 的出边里没有 L：{sorted(edges['B'])}"
    assert edges["L"] == frozenset({"C"}), f"L 的出边：{sorted(edges['L'])}"
    for role in OTHER_ROLES:
        if role in ("B", "L"):
            continue
        assert "L" not in edges[role], f"{role} 的出边里出现了 L：{sorted(edges[role])}"
    assert "L" not in edges[S.CONDUCTOR_ROLE], (
        f"M 的出边里出现了 L：{sorted(edges[S.CONDUCTOR_ROLE])}")
    assert "L" not in C.NON_SUMMONABLE, f"L 还在不可召唤名单里：{sorted(C.NON_SUMMONABLE)}"
    # 反真空：判据函数在一张坏表上必须报出违反项（否则它在读一句恒真的话）
    assert _edge_violations(_BAD_EDGES) != [], (
        "A→L 的坏表上判据函数也全绿 ⇒ 判据 1 是真空的")


def test_one_two_the_entry_works_only_through_the_policy_gate(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 1 的第二半：这件事在闸门上是真的（B 通、M 及其余角色一律 forbidden_edge）。

    改前红：`B → L` 拿到 `forbidden_edge`（`edges["B"]` 没有 L），下面第一句就红。
    """
    from agentflow import policy as P
    from agentflow.agentspec import builtin_registry

    _lean_env(monkeypatch, True)
    pol = P.Policy()
    assert "L" in builtin_registry().summonable_roles(), (
        f"L 不在可召唤名单里：{builtin_registry().summonable_roles()}")
    assert P.check(pol, P.Decision(frm="B", to="L", action="", depth=2)) is None, (
        "B → L 这条唯一入口在闸门上不通")
    assert P.check(pol, P.Decision(frm="L", to="C", action="", depth=3)) is None, (
        "L → C 这条出边在闸门上不通")
    for frm in OTHER_ROLES:
        if frm in ("B", "L"):
            continue
        got = P.check(pol, P.Decision(frm=frm, to="L", action="", depth=2))
        assert got is not None, f"{frm} → L 居然通了"
        assert got.reason == "forbidden_edge", (frm, got.reason, got.detail)
    # L 除 C 之外一条也派不动（逐条）
    for to in OTHER_ROLES:
        if to in ("C", "L"):
            continue
        got = P.check(pol, P.Decision(frm="L", to=to, action="", depth=3))
        assert got is not None and got.reason == "forbidden_edge", (to, got)


# ============================================================ 2. 开关关着时全部不可见


def test_two_lean_off_hides_all_four_edges_and_the_role_itself(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 2：开关关 ⇒ 那四条边与 L 全部不可见（角色表 / 工具面 / 名册 / 提示词 0 处）。

    改前红：这一条的正控（开关开着时 B→L 必须通）在改前是红的 —— 那时边表里没有 L，
    "关着时不可见"在一张没有这条边的表上恒真（真空）。

    反真空：先在开着那一档断言 B→L 通、L 在自己的工具面上，再把开关关掉断言同一条边
    当场不通 —— 否则"关着时看不见"可能只是"这条边根本不存在"。
    """
    from agentflow import agent_prompts as AP
    from agentflow import leanscope as LS
    from agentflow import policy as P
    from agentflow.agentspec import builtin_registry
    from agentflow.tools import build_registry
    from agentflow.tools import conductor_tools as CT

    # ---- 正控：开着时这条边必须在（否则"关着时看不见"是真空）
    _lean_env(monkeypatch, True)
    try:
        pol = P.Policy()
        assert P.check(pol, P.Decision(frm="B", to="L", action="", depth=2)) is None, (
            "开关开着时 B → L 都不通 ⇒ 判据 2 读的不是这条边")
        on_reg = build_registry()
        on_names = {spec.name for spec in on_reg.registry.for_role("L")}
        assert "formal.formalize" in on_names, f"开着时 L 的工具面是空的：{sorted(on_names)}"

        # ---- 关掉
        _lean_env(monkeypatch, False)
        assert LS.is_hidden("L") is True
        reg = builtin_registry()
        assert "L" not in reg.roles(), f"角色表里还有 L：{reg.roles()}"
        assert "L" not in reg.summonable_roles(), reg.summonable_roles()
        # 四条边：B→L / L→C / 其余→L / M→L 一律不可见
        for frm, to in (("B", "L"), ("L", "C"), ("M", "L"), ("D", "L")):
            got = P.check(pol, P.Decision(frm=frm, to=to, action="", depth=2))
            assert got is not None, f"{frm} → {to} 在开关关着时仍然通"
            assert got.reason == "forbidden_edge", (frm, to, got.reason)
            assert "lean" in got.detail, (frm, to, got.detail)
        # 工具面：formal.* 一件都不装配，L 自己那面是空的
        build = build_registry()
        assembled = set(build.registry.names())
        assert not sorted(x for x in assembled if str(x).startswith("formal.")), (
            f"形式化工具仍然装配了：{sorted(x for x in assembled if str(x).startswith('formal.'))}")
        assert build.registry.for_role("L") == [], "关着时 L 的工具面不是空的"
        # 名册：接线态读数里没有 L
        from agentflow.host import _Builder

        assert "L" not in sorted(_Builder().status()), sorted(_Builder().status())
        # 提示词：其余角色 0 处提到 L；按名取 L 的入口受控拒绝（理由 lean_off）
        import re

        role_name = re.compile(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])")
        for role in OTHER_ROLES:
            text = AP.system_prompt(role, registry=build.registry)
            hits = role_name.findall(text)
            assert not hits, f"{role} 的提示词里出现了 {len(hits)} 处 L 这个角色名"
        res = CT.conductor_role_spec(None, "L")
        assert res.ok is False, res
        assert str((res.meta or {}).get("reason") or "") == "lean_off", res.meta
    finally:
        # 这一条以"关"收尾：不显式回基线，关档读数会留给后面渲染提示词的用例。
        restore_lean_baseline(monkeypatch)


# ============================================================ 3. 消费 B 的定理证明库


def test_three_l_reads_b_library_and_refuses_without_it(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 3：`b_library` 读数齐全；取不到 B 的库 ⇒ 拒（`statement_not_found`）、不写盘。

    改前红：返回值里没有 `b_library` 这一格（`KeyError`），`coverage` 里也没有。

    反真空：`proof_chars` 与 `dependency_steps` 分别对着真证明链数与真字数比，
    并把"不写盘"做成前后目录清单相等（不是"我没看见新文件"）。
    """
    _lean_env(monkeypatch, False)
    st, ws, proof = _workspace(tmp_path)
    agent = _agent_l(st, ws)

    data = agent.formalize(CLAIM, source=_source(LINKS + 1), statement_id=STMT_ID)
    lib = dict(data.get("b_library") or {})
    assert lib.get("stmt_id") == STMT_ID, lib
    assert lib.get("label") == LABEL, lib
    assert lib.get("found") is True, lib
    assert int(lib.get("proof_chars") or 0) == len(proof), (lib, len(proof))
    assert int(lib.get("dependency_steps") or 0) == LINKS + 1, lib
    assert dict(data.get("coverage") or {}).get("b_library") == lib, (
        data.get("coverage"))

    # ---- 取不到 B 的库：拒、不写一个字节、不起检查器
    seen_before = sorted(p.name for p in (ws / "code" / "formal").glob("*")) \
        if (ws / "code" / "formal").is_dir() else []

    def _boom(*_a: object, **_k: object) -> dict:
        raise AssertionError("取不到 B 的库时不许可起检查器")

    monkeypatch.setattr(type(agent), "check_formal", _boom)
    missing = agent.formalize(CLAIM, source=_source(LINKS + 1), statement_id="999999")
    assert missing.get("refused") is True, missing
    assert missing.get("reason") == "statement_not_found", missing.get("reason")
    seen_after = sorted(p.name for p in (ws / "code" / "formal").glob("*")) \
        if (ws / "code" / "formal").is_dir() else []
    assert seen_after == seen_before, (seen_before, seen_after)
    assert dict(missing.get("b_library") or {}).get("found") is False, missing.get("b_library")


# ============================================================ 4. L → B 汇报困难


def test_four_a_missing_step_is_reported_to_b(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 4：造一次"漏一步"的形式化失败 ⇒ B 的收件箱里出现一条汇报。

    改前红：`formalize` 的失败只落在返回值里（`coverage.unmapped`），一条消息都没有
    ⇒ `read_messages(ws, "B")` 是空的。

    落点与形态（三样都要）：收件箱里真有一条 `agent_message`（不是日志）；正文点名
    `stmt_id` 与失败类型、第几步、建议 B 补什么；投递本身走的是协作边
    （把 B→L 这条边摘掉，`message_admission` 当场不成立 —— 汇报绕不开边表）。
    """
    _lean_env(monkeypatch, False)
    st, ws, _proof = _workspace(tmp_path)
    agent = _agent_l(st, ws)

    data = agent.formalize(CLAIM, source=_source(LINKS), statement_id=STMT_ID)
    cov = dict(data.get("coverage") or {})
    assert cov.get("unmapped") == [LINKS + 1], cov
    report = dict(data.get("report") or {})
    assert report.get("state") == "reported", (report, data.get("reason"))
    payload = dict(report.get("payload") or {})
    assert payload.get("statement_id") == STMT_ID, payload
    assert payload.get("failure_type") == "unfaithful_step", payload
    assert int(payload.get("step") or 0) == LINKS + 1, payload
    assert str(payload.get("suggestion") or "").strip(), payload

    inbox = [m for m in _inbox(ws, "B") if str(m.get("from")) == "L"]
    assert inbox, "B 的收件箱里没有 L 的汇报"
    hit = inbox[-1]
    body = json.dumps(hit, ensure_ascii=False)
    assert STMT_ID in body, body
    assert "unfaithful_step" in body, body
    assert f"第 {LINKS + 1} 步" in body, body
    assert dict(hit.get("formal_failure") or {}).get("failure_type") == "unfaithful_step", hit
    assert str(hit.get("msg_id") or ""), hit

    # ---- 这条汇报绕不开边表：摘掉 B→L，私聊当场不成立
    assert AL.message_admission("L", "B") == "", AL.message_admission("L", "B")
    patched = {role: (values - {"L"} if role == "B" else values)
               for role, values in C.ALLOWED_EDGES.items()}
    monkeypatch.setattr(C, "ALLOWED_EDGES", patched)
    assert AL.message_admission("L", "B") != "", (
        "没有 B→L 这条边，L 仍然能私聊 B ⇒ 这条汇报绕开了协作面")


# ============================================================ 5. B 重做后重新过 V


def _own_statement() -> dict:
    """B 登记一条自产命题时那几格（`register_statement` 的硬要求）。

    `kind="conjecture"` 是刻意：业主 2026-10-22 的裁定 B-2（「没有引文 / 自己编的
    命题必须从『猜想』注册」）要求自产、无出处、没有引文回验的命题以猜想进门；
    写成 theorem 会受控拒绝 `must_start_as_conjecture`（那是另一条既有判据，不是
    本文件在判的事）。等级由五元位现算，V 签过之后它自己会抬 —— 不需要在这里声明。
    """
    return {
        "statement_full": CLAIM,
        "statement_text": CLAIM,
        "origin": "own_result", "derived_from": ["999999"],
        "doc_id": S.format_id(0),
        "quote_reason": "我方自产命题，没有外部引文要比对",
        "kind": "conjecture",
        "label": LABEL,
    }


def test_five_b_rewrites_the_proof_and_v_signs_again(tmp_path: pathlib.Path) -> None:
    """判据 5：V 先审新稿拿签（签块落稿）→ B 再收录 ⇒ 旧正文进 `proof_history`。

    2026-11-02 业主把次序定成「V 签先放在手稿里，让 B 录入」（`draft/179`）之后，
    改前的 `B 登记 → V 判 → B 改稿` 这条环在 strict 下不可达：改稿那一笔没有签就被
    准入闸整笔拒。现在的形态：V 连判三转、签块盖回稿（稿名按这一条命题的号命名，
    第 9 格手稿号才映射得回来）⇒ B 拿着「稿里正文 + 手稿签块」收录。

    反真空：签块盖的必须是新稿那一份（sha 与连续次数都对得上，不是"有块就算"）；
    旧台账那一签盖的是旧正文 ⇒ 新正文上仍读 stale（旧签不借光）；两次签的正文
    sha 必须不同（否则上面那些"新签"可能只是旧签换了张皮）。

    2026-10-29 口径：同一份正文要连续 `SIGN_STREAK_NEED` 次「成立」才算签；这一趟的
    逐转读数由 `review_passes` 给出（不是同一份正文反复送三次）。
    """
    from agentflow import depsection as _DS
    from agentflow import evidencebits as EB
    from agentflow import verifications as VR
    from agentflow import vsigns as VS
    from agentflow.store import Store

    from conftest import seed_statement_row

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    b = _agent_b(st, ws)
    old = _proof_text(LINKS)          # 漏一步的稿子（L 刚报回来的那一份）
    # 旧稿是"已在册、还没有 V 签"的历史形态（真机 own_result 行就是这么来的）：
    # strict 下无签正文经 `register_statement` 写不进去 ⇒ 夹具直接铺行，判据不变。
    seeded = seed_statement_row(
        st, proof_text=old, statement_full=CLAIM, statement_text=CLAIM,
        kind="conjecture", label=LABEL, origin="own_result", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_reason="我方自产命题，没有外部引文要比对",
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=old,
                        kind="conjecture"))
    sid = str(seeded.get("stmt_id") or "")
    assert sid, seeded

    bad_replies = [_verdict_json("有毛病", step=LINKS + 1)] * int(VR.SIGN_STREAK_NEED)
    v = _v_agent(st, ws, bad_replies)
    # 2026-11-04（甲）：在册命题送审必须带手稿。旧稿先落成按号命名的那一份
    # （空依赖表也是声明）；下一段再把同一路径改写成新稿，走"改稿重签"。
    man_rel = _DS.manuscript_relpath(statement_id=sid)
    assert man_rel, sid
    old_man = ("# F 的证明手稿：加零不改变自然数\n\n"
               f"## 命题\n\n{CLAIM}\n\n"
               f"## 证明\n\n{old}\n\n" + _DS.render_dependency_section([]))
    (ws / man_rel).parent.mkdir(parents=True, exist_ok=True)
    (ws / man_rel).write_text(old_man, encoding="utf-8")
    signed1 = v.verify_proof(sid, proof_manuscript=man_rel)
    assert signed1.get("checked") is True, signed1
    assert signed1.get("verdict") == "有毛病", signed1

    # ---- 新稿先过 V：一次调用连判三转（3 转「成立」⇒ 签块盖回手稿）
    new = _proof_text(LINKS + 1)
    assert man_rel, sid
    man_text = ("# F 的证明手稿：加零不改变自然数\n\n"
                "- 计划：0000 · 子目标：s1\n\n"
                f"## 命题\n\n{CLAIM}\n\n"
                f"## 证明\n\n{new}\n\n"
                "## 依赖\n\n"
                "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
                "|---|---|---|---|\n"
                "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
    man_path = ws / man_rel
    man_path.parent.mkdir(parents=True, exist_ok=True)
    man_path.write_text(man_text, encoding="utf-8")

    v2 = _v_agent(st, ws, [_verdict_json("成立")] * int(VR.SIGN_STREAK_NEED))
    # 2026-11-03 件一：未在册正判的块由收方秘书落 —— 先挂上"V 由 F 派出来"的身份。
    from agentflow import conductor as CND

    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        signed2 = v2.verify_proof(proof_manuscript=man_rel)
    assert signed2.get("checked") is True, signed2
    assert signed2.get("kind") == "proof_unregistered_signed", signed2
    assert signed2.get("verdict") == "成立", signed2
    passes = signed2.get("review_passes") or []
    assert [p.get("pass") for p in passes] == [1, 2, 3], passes
    block = VS.manuscript_sign_standing(man_path.read_text(encoding="utf-8"),
                                        proof_sha=VR.text_sha(new))
    assert block.get("state") == "signed", block
    assert (block.get("streak"), block.get("need")) == (3, 3), block
    assert block.get("proof_sha256") != str(signed1.get("proof_sha256") or ""), (
        block.get("proof_sha256"), signed1.get("proof_sha256"))

    # ---- B 收录：正文取自稿里那一份，签由手稿签块认下
    second = b.register_statement(**_own_statement(), proof_text=new,
                                  proof_manuscript=man_path.read_text(encoding="utf-8"))
    assert second.get("ok") is True, second
    assert second.get("canonical_written") is True, second
    row = next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == sid)
    history = [dict(h) for h in (row.get("proof_history") or [])]
    assert [str(h.get("text") or "") for h in history] == [old], history

    # 旧台账那一签盖的是旧正文 ⇒ 新正文上读 stale；新签在手稿签块里（不在台账）。
    standing = VR.review_standing(ws, statement_id=sid, proof_text=new, proof_no=1)
    assert standing.get("state") == "stale", standing
    assert standing.get("in_sync") is False, standing
    block_now = VS.manuscript_sign_standing(man_path.read_text(encoding="utf-8"),
                                            proof_sha=VR.text_sha(new))
    assert block_now.get("state") == "signed", block_now


# ============================================================ 6. B → D 升级


def test_six_the_upgrade_to_d_is_the_summon_path(tmp_path: pathlib.Path) -> None:
    """判据 6：B→D 升级走 `summon` 形状派 D —— 模型真能走的那条路。

    ## 为什么这一格在 2026-11-20 换了被测对象（PROOFCHAN，不是放宽判据）

    改前这一格调的是 `AgentB.escalate_proof_research`：它不在 `specs/b.py` 的
    `ACTIONS` 里 ⇒ `CAPABILITIES["B"]` 里没有它 ⇒ 模型照它调只会拿到 `unknown_action`
    （2026-11-05 审计② 第 ⑪ 条就是为此把提示词锚从它改到 `summon` 的）；它
    src 里 0 个调用方，只有测试在调。钉一个谁也走不到的入口，绿了也证明不了
    "升级这条路存在"。所以这一格改钉模型侧真走的那条路，强度按三件分开摆：

    - 正控（改前就绿，迁移必须保住）：B 的出边里有 D；D 不在 `NON_SUMMONABLE`
      里；`policy.check` 对 B→D 放行 —— 三条缺一条，召唤 D 就派不出去；
    - 仍然绕不开边表：同一条闸对 B→F / B→G 照旧 `forbidden_edge`（改前那条
      "递送绕不开边表"盯的是 `message_admission`，现在 `Conductor.summon` 第 [4] 步
      读的就是 `policy.check`，钉同一条闸的召唤面）；
    - 改前红（退场那半）：`AgentB` 上不许再有这个入口、模块不许再在盘上。

    提示词那一处的负控（"普通缺陷不进 D 的收件箱"）在
    `tests/test_l_report_and_seam_matrix.py` 的 D11 里逐字钉着。
    """
    from agentflow import policy as P
    from agentflow.tools import build_registry

    # ---- 正控：升级这条路在结构上真的存在（边 / 召唤面 / 闸三层）
    from agentflow import policy as P
    from agentflow.agentspec import builtin_registry

    assert "D" in C.ALLOWED_EDGES["B"], sorted(C.ALLOWED_EDGES["B"])
    assert "D" not in C.NON_SUMMONABLE, (
        f"D 在不可召唤名单里 ⇒ 边在也派不动它：{sorted(C.NON_SUMMONABLE)}")
    assert "D" in builtin_registry().summonable_roles(), (
        builtin_registry().summonable_roles())
    assert "summon" in AL.SHAPES, AL.SHAPES
    allowed = P.check(P.Policy(), P.Decision(frm="B", to="D", action=""))
    assert allowed is None, (
        f"B 派 D 被闸拒了（{getattr(allowed, 'reason', '')}）⇒ 升级这条路整条不存在")

    # ---- 绕不开边表：同一条闸，B 的越权边照旧拒
    for outside in ("F", "G"):
        refused = P.check(P.Policy(), P.Decision(frm="B", to=outside, action=""))
        assert refused is not None, f"B 派 {outside} 竟然放行了"
        assert refused.reason == "forbidden_edge", (outside, refused.reason)
        assert refused.limit == "edge", (outside, refused.limit, refused.limit)
    assert "F" not in C.ALLOWED_EDGES["B"] and "G" not in C.ALLOWED_EDGES["B"]

    # ---- 改前红：那个只活在测试里的程序入口已退场（改前这里 `hasattr` 为真 ⇒ 红）
    from agentflow.agent_b import AgentB

    assert not hasattr(AgentB, "escalate_proof_research"), (
        "`AgentB` 上又出现了这个入口 —— 它不在 `ACTIONS` 里，模型调到它在循环里只会拿到 "
        "`unknown_action`；要让 B 能调它就必须先进动作表（那是改权限面，不是改测试）")
    import importlib.util

    assert importlib.util.find_spec("agentflow.agent_b.proof_research") is None, (
        "`agentflow.agent_b.proof_research` 又回到盘上了 ⇒ 旧路复活")


def test_six_two_the_upgrade_edge_is_exactly_one(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 6 的第二半：为了这一条升级只加了一条边（B→D），没有别的。

    改前红：`edges["B"]` 是 `{C,H,V}` ⇒ 第一句红。

    末段那一条（受控拒绝一行都不写）迁移到仍然活着的那个入口上：改前它调
    `escalate_proof_research(severity="research", failure_type="不认识的类型")`，现在
    同一份受控形态（`proofreport` 的 `payload` + `violations`）由 L 的 `report_to_b`
    走 —— 那一条是活的（`formalize` 的失败分支真的调它），闸与词表是同一份。
    """
    assert "D" in C.ALLOWED_EDGES["B"], sorted(C.ALLOWED_EDGES["B"])
    assert C.ALLOWED_EDGES["B"] == frozenset({"C", "D", "H", "L", "V"}), (
        sorted(C.ALLOWED_EDGES["B"]))
    assert C.ALLOWED_EDGES["D"] == frozenset({"A", "B", "C", "E", "F"}), (
        sorted(C.ALLOWED_EDGES["D"]))
    # 负控：受控拒绝那一档一行都不写（词表外失败类型 ⇒ `invalid_params`，收件箱不动）
    from agentflow.store import Store

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    agent = _agent_l(st, ws)
    b_inbox_before = len(_inbox(ws, "B"))
    refused = agent.report_to_b(statement_id=STMT_ID, failure_type="不认识的类型",
                                severity="research")
    assert refused.get("state") == "refused", refused
    assert refused.get("reason") == "invalid_params", refused
    assert len(_inbox(ws, "B")) == b_inbox_before, "受控拒绝也写了东西"


# ============================================================ 7. 反真空


def test_seven_the_criterion_is_not_vacuous(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 7：把"只有 B 能派 L"的判据 monkeypatch 成恒真 ⇒ 判据 1 必须红。

    这一条守的是"判据 1 到底在判什么"：如果它只在一张好表上成立，把判据本体替换成
    恒过之后它照样绿 —— 那它读的不是边表，而是一句恒真的话。
    """
    import sys

    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "_edge_violations", lambda edges: [])
    with pytest.raises(AssertionError):
        mod.test_one_b_can_cast_l_and_l_can_only_cast_c()
