# -*- coding: utf-8 -*-
"""判据：F 这一侧一条"把形式化交出去"的路都没有（业主 2026-10-27 收口）。

## 口径（照做，不再解释）

形式化只在「用户指定 ⇒ M 转交 B ⇒ B 判断成本后逐条派 L」这条链上发生（六步的真身是
`specs/b.py::PROOF_CHANNEL`）⇒ F 不发起、不排流水线、不立 formal 子目标、不把
`method="formal"` 传给任何人。

## 四条判据（对应施工单 a–d），外加一条 ① 的落点判据 e

| # | 守的那件事 | 改前读数 |
|---|---|---|
| a | `build_registry` 给 F 的工具面里，名字含 `lean` / `formal` 的必须为空 | 绿（本来就没有）；反真空靠同一把尺子在 L 那一面必须命中 |
| b | 渲染出的 F 提示词里不许出现「你可以形式化」这类承诺；形式化的边界句必须点名"由 B 决定" | 红：F 的 policy/boundary 里一句形式化都不提（读的人只能靠猜它能不能自己去做） |
| c | `create_plan` 收到 `method="formal"` ⇒ 这一笔拿不到任何形式化的执行路径 | 绿（`_deploy` 早已受控拒绝）；本判据只断言结果，不重复实现 |
| d | 反真空：往 F 的 policy 里塞一句「你可以自己跑 Lean 检查」⇒ b 必红 | 红（b 还不存在时它当然什么都抓不住） |
| e | `_deploy_e` 自己也不许把 `method="formal"` 往 E 传（绕过 `_deploy` 直接调这一层的那条路） | 红：改前是 `method=str(sg.get("method") or "numeric")`，子目标写什么就传什么 |

## 判据 b 的口径为什么落在"F 自己写的那几段"

渲染出来的 F 提示词里有六行含形式化那一档的记号，其中五行不是 F 的承诺：工具目录两行
（`verify.detect_verifier` / `verify.run_experiment` 的注册表摘要）、五个证据位两行
（`formal` 那一格的读法）、工具链读数一行（"要判断能不能跑形式化核验，先让框架跑一次
`agentflow doctor`"，主语是框架）。把它们一律判红，判据就会变成噪音，然后没人再看它。
所以承诺只在「主语是 F」时成立：F 自己写的那几段（duty / boundary / policy / stance /
local_notes）里，只要出现"你 + 能愿动词 + 形式化那一档"这串正向句式就是红；整份提示词
那一侧另按"同一行里有 `你`"再判一次。

反向那一半同样要判：F 的提示词必须有一句把决定权写清（"由 B"），否则读的人只会看到
"有个形式化那一档"，而不知道谁能开它 —— 那一条在改前是红的（一句都没有）。

## 零模型 / 零真机

只读注册表、渲染提示词、在 `tmp_path` 自建的工作区里建计划；不起子进程、不调模型。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow.agent_f import AgentF
from agentflow.store import Store
from agentflow.tools import build_registry

#: 名字里带这两截就算"形式化工具"（判据 a 的尺子，逐字按施工单写）。
FORMAL_NAME_MARKERS: tuple[str, ...] = ("lean", "formal")

#: 形式化那一档的记号（一个句子只要含其中之一，就在判据 b 的扫描面里）。
FORMAL_MARKS = re.compile(r"形式化|Lean|lean|检查器|check_formal|formal\.|`formal`")

#: 能愿动词（"你可以/你能/你有权自己"）。承诺的正向记号。
ABILITY = re.compile(r"可以|能|能够|有权|自行")

#: 否定的能愿形态：`不能` / `不可以` / `没能` 这类说的是"做不到"，不是承诺。
ABILITY_NEGATED = re.compile(r"(?:不|没|未|禁|无|难|岂)(?:可以|能|能够)")

#: 一句里怎么算"点名了由谁决定"（判据 b 的反向那一半）。
WHO_DECIDES = re.compile(r"(?:由|交给|归|问)\s*B|B\s*(?:判断|决定)")

#: 中文的句读（承诺按小句判：一句话里前后两半常常是两件事）。
CLAUSE_SPLIT = re.compile(r"[。；，、：\n]")


@pytest.fixture(scope="module")
def registry():
    """判据与真跑同一个注册表（提示词要描述的那份工具面必须与执行时那份是同一个）。"""
    return build_registry().registry


# ============================================================ 判据 a
def test_a_f_tool_surface_has_no_lean_or_formal_tool() -> None:
    """a：`build_registry` 给 F 的工具面里，名字含 `lean` / `formal` 的为空。

    反真空：同一把尺子在 L 的工具面上必须命中至少一件（`formal.formalize` 那一族）
    —— 否则"F 那一面是空的"可能只是因为尺子什么都没在扫。
    """
    from agentflow import leanscope

    face = {str(spec.name) for spec in build_registry().registry.for_role("F")}
    assert len(face) >= 30, (
        f"F 的工具面只有 {len(face)} 件 ⇒ 这张面不是真的，下面的筛选扫的是空集")
    hits = sorted(name for name in face
                  if any(m in name.lower() for m in FORMAL_NAME_MARKERS))
    assert hits == [], (
        f"F 的工具面上出现了形式化那一档的工具：{hits}"
        "（F 不发起形式化：那条链只在 用户指定 ⇒ M 转交 B ⇒ B 派 L 上）")

    if not leanscope.lean_on():
        pytest.skip("Lean 关着时 L 的工具面不存在 ⇒ 反真空那一半无从判（这一档由 "
                    "`test_l_is_isolated_when_lean_is_off.py` 守）")
    l_face = {str(spec.name) for spec in build_registry().registry.for_role("L")}
    l_hits = sorted(name for name in l_face
                    if any(m in name.lower() for m in FORMAL_NAME_MARKERS))
    assert l_hits, (
        f"同一把尺子在 L 的工具面（{sorted(l_face)}）上一件都命不中 ⇒ 判据 a 是空转的")


# ============================================================ 判据 b / d 的尺子
def _formal_lines(text: str) -> list[str]:
    """含形式化那一档记号的行（判据 b 的扫描面，逐行给出来便于定位）。"""
    return [line for line in str(text).splitlines() if FORMAL_MARKS.search(line)]


def _commitment_clauses(text: str, *, need_second_person: bool) -> list[str]:
    """这份文本里"F 自己可以去做形式化"的小句（空 = 一句都没有）。

    `need_second_person` 为真时只判含 `你` 的行 —— 工具目录与工具链读数那几行的主语
    不是 F（是注册表、是框架），把它们算成承诺就是误伤。
    """
    bad: list[str] = []
    for line in _formal_lines(text):
        if need_second_person and "你" not in line:
            continue
        for clause in CLAUSE_SPLIT.split(line):
            if not FORMAL_MARKS.search(clause):
                continue
            if not ABILITY.search(clause):
                continue
            if ABILITY_NEGATED.search(clause):
                continue
            bad.append(clause.strip())
    return bad


def _f_brief_text() -> str:
    """F 自己写的那几段（`specs/f.py::SPEC.brief` 的渲染源）。

    与 `agent_prompts.ROLE_BRIEFS["F"]` 同一份对象（那边就是从 specs 取的），
    所以这里读到的就是提示词里那几段。
    """
    brief = AP.ROLE_BRIEFS["F"]
    parts = [str(brief.duty), str(brief.signature_error), str(brief.deliverable),
             *[str(x) for x in brief.boundary], *[str(x) for x in brief.policy],
             *[str(x) for x in brief.stance]]
    return "\n".join(parts)


def _formal_problems(brief_text: str, prompt_text: str) -> list[str]:
    """判据 b 的尺子（正控与反真空共用同一份 —— 反真空要证明的正是"它在这种形态下必红"）。"""
    problems: list[str] = []
    for clause in _commitment_clauses(brief_text, need_second_person=False):
        problems.append(f"F 自己写的那几段里有一句是承诺（你可以去做形式化）：{clause!r}")
    for clause in _commitment_clauses(prompt_text, need_second_person=True):
        problems.append(f"渲染出的提示词里有一句把形式化说成 F 能做的事：{clause!r}")

    boundary = _formal_lines(brief_text)
    if not boundary:
        problems.append(
            "F 自己写的那几段里一句形式化都不提 ⇒ 读的人不知道这一档不在它身上、"
            "也不知道该由谁决定（边界句必须写清「由 B 决定」）")
    elif not any(WHO_DECIDES.search(line) for line in boundary):
        problems.append(
            "F 的那几句形式化边界句没有一句点名「由 B 决定」⇒ 边界是写给谁看的："
            + " ／ ".join(line.strip()[:60] for line in boundary))
    return problems


def test_b_the_rendered_prompt_makes_no_formal_promise(registry) -> None:
    """b：渲染出来的 F 提示词里没有「你可以形式化」这类承诺，且边界句点名由 B 决定。"""
    prompt = AP.system_prompt("F", registry=registry)
    problems = _formal_problems(_f_brief_text(), prompt)
    assert problems == [], "\n".join(problems)

    # 反真空：这条判据真的在读形式化那几行（不是一份什么都没扫到的文本）
    assert _formal_lines(prompt), "F 的提示词里一行形式化的字都没有 ⇒ 判据 b 扫的是空集"
    assert _formal_lines(_f_brief_text()), (
        "F 自己写的那几段里一行形式化都没有 ⇒ 边界句那半条是空的")


def test_d_putting_a_promise_back_turns_criterion_b_red(registry, monkeypatch) -> None:
    """d：往 F 的 policy 里塞一句「你可以自己跑 Lean 检查」⇒ b 必红（端到端渲染）。

    走的是真的渲染路径（`ROLE_BRIEFS["F"]` 换成塞了那一句的副本），不是对着一个字符串
    副本做同义反复 —— 这样"改的是 policy、判的是渲染出来的提示词"才是一件事。
    """
    import dataclasses

    clean = _formal_problems(_f_brief_text(), AP.system_prompt("F", registry=registry))
    assert clean == [], f"干净的那一份就有问题，下面的反真空证明不了什么：{clean}"

    brief = AP.ROLE_BRIEFS["F"]
    monkeypatch.setitem(AP.ROLE_BRIEFS, "F", dataclasses.replace(
        brief, policy=tuple(brief.policy) + ("你可以自己跑 Lean 检查",)))
    dirty_prompt = AP.system_prompt("F", registry=registry)
    assert "你可以自己跑 Lean 检查" in dirty_prompt, (
        "塞进去的那一句没有出现在渲染结果里 ⇒ 这条反真空没改到判据读的那份文本")

    problems = _formal_problems(_f_brief_text(), dirty_prompt)
    hits = [p for p in problems if "承诺" in p or "能做的事" in p]
    assert hits, (
        "往 F 的 policy 里塞了一句「你可以自己跑 Lean 检查」，判据 b 没点红："
        f"{problems}")
    assert any("你可以自己跑 Lean 检查" in p for p in hits), (
        f"判据 b 点红了，但红的不是那一句：{hits}")


# ============================================================ 判据 c
class _RecordingE:
    """替身 E：任何一次调用都记下来（判据 c / e 用它当"E 到底收到了什么"的读数）。

    刻意不抛异常：抛出去会被 `_deploy_e` 的"任何 E 侧失败都降级为 blocked"接住，
    于是"形式化被交出去了"会以 `experiment_failed` 的形状藏起来（那正是改前真机的读数）。
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_experiment(self, claim, claim_key, script_path, **kw):  # noqa: ANN001, ANN003
        self.calls.append({"claim": claim, "claim_key": claim_key,
                           "script_path": script_path, **kw})
        return {"experiment_id": "000000", "evidence_kind": "cross_check",
                "result": "（替身，不该被调到）"}

    def author_script(self, spec, *, sid=""):  # noqa: ANN001, ANN003
        self.calls.append({"author_script": sid, "spec": dict(spec or {})})
        return {"ok": False, "reason": "no_seam", "note": "（替身）"}


def _f_with(store: Store, e: object) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root}, e=e)


def _formal_subgoal() -> dict:
    """一条形式化子目标（带 `script_path`：没有脚本时它根本走不到 E，判据就没有分辨力）。"""
    return {"sid": "s1", "text": "把这条命题形式化", "owner": "E", "method": "formal",
            "script_path": "probe.py",
            "testable": "判据夹具：这一步做完能一句话判它成立或不成立"}


def _write_probe(store: Store) -> None:
    """把子目标点名的那个脚本写到工作区里（否则"缺 script_path"会先一步挡掉分派）。"""
    path = Path(store.root) / "probe.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('print("REPRO_RESULT: {}")\n', encoding="utf-8", newline="\n")


def test_c_create_plan_with_a_formal_method_never_reaches_e(store: Store) -> None:
    """c：`create_plan` 收到 `method="formal"` ⇒ 这一笔拿不到任何形式化的执行路径。

    两种合法形态，按当天实现现算（不写死是哪一种）：

    * 整笔拒（`created is False` + 受控码）：一行都不写库；
    * 计划立住了，而那一格在 `_deploy` 落成"F 派不出去"的受控死路
      （`formal_edge_missing`）。

    两种形态都要满足同一件事：E 一次都没被调到，一条实验行都没有。
    """
    _write_probe(store)
    e = _RecordingE()
    f = _f_with(store, e)
    out = f.create_plan("难题：把这条命题形式化", "PK-FORMAL-C",
                        subgoals=[_formal_subgoal()])

    if out.get("created") is not True:
        assert out.get("ok") is False, f"不是创建成功、也不是受控拒绝：{out}"
        assert out.get("kind") or out.get("error"), f"拒绝没有自报理由：{out}"
        assert store.rows("attack_plans") == [], "整笔拒时一行都不许写库"
        assert e.calls == [], f"整笔拒的那一笔仍然调到了 E：{e.calls}"
        return

    pid = str(out["plan_id"])
    round_out = f.step(pid)
    assert e.calls == [], f"形式化子目标被派给了 E：{e.calls}"
    assert store.rows("experiments") == [], "形式化子目标落了一条实验行 ⇒ 它被当数值检查跑了"
    assert round_out["action"] == "dead_end", round_out.get("action")
    facts = round_out.get("formal_dispatch") or {}
    assert facts.get("code") == "formal_edge_missing", facts.get("code")
    assert facts.get("role") == "L", facts.get("role")
    assert facts.get("dispatchable_by"), (
        "读数没有点名'今天谁派得动'⇒ 调用方不知道下一条该找谁（反真空）")
    assert "数值检查" in str(round_out.get("reason") or ""), (
        "读数没有说清'不许退回 E 做数值检查'")


# ============================================================ 判据 e（① 的落点）
def test_e_deploy_e_never_forwards_a_formal_method(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：`_deploy_e` 自己也不许把 `method="formal"` 往 E 传。

    这一条判的是旁路：直接调 `_deploy_e`（不经过 `_deploy` 的那一刻），并把
    `_is_formal_subgoal` 打桩成恒 False —— 于是改前那一句
    `method=str(sg.get("method") or "numeric")` 会把 formal 原样交给 E，而改后
    只传 `E_METHODS` 里的取值（formal 连"被传下去"都不会发生）。
    """
    from agentflow.agent_f import core as FC

    e = _RecordingE()
    f = _f_with(store, e)
    monkeypatch.setattr(FC, "_is_formal_subgoal", lambda sg: False)

    sg = dict(_formal_subgoal(), script_path="proofs/probe.py")
    plan = {"problem_key": "PK-FORMAL-E", "for_question_id": None}
    f._deploy_e(sg, plan=plan)  # noqa: SLF001 - 打桩点就是被测的那一层

    assert e.calls, "替身 E 一次都没被调到 ⇒ 这条判据没走到要判的那一格"
    sent = e.calls[0]
    assert sent.get("method") != "formal", (
        "`_deploy_e` 把 method='formal' 交给 E 了 —— F 侧不许有这条路")
    allowed = tuple(str(m) for m in S.EXPERIMENT_METHODS if str(m) != "formal")
    assert "method" not in sent or sent["method"] in allowed, (
        f"`_deploy_e` 传了一个不该传的方法：{sent.get('method')!r}")
