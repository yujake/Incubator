# -*- coding: utf-8 -*-
"""业主 2026-10-22 晚裁定：E 的 Lean 侧写死关闭，其它角色关于「E 做形式化」的记忆清除。

裁定原文（逐字）：「E 的 Lean 侧开关全写死成关闭，防止测试 L 行为时发生错乱。
当 L 的能力和协作能力彻底被证实后再删 E 的 Lean 侧原始设计。其它角色关于 E 的
Lean 侧记忆可以全面清除。」

五条判据（每条都有改前红，逐条写在用例的 docstring 里）：

| # | 判据 | 这一档的落点 |
|---|---|---|
| 1 | 任何角色（含 E）的工具面里都没有 `verify.check_formal` | `tools/verify_tools.py` 的 `roles` |
| 2 | E 的动作面里 formal 那一支 ⇒ 受控拒绝，码 `formal_moved_to_l`（不抛栈） | `agent_e/run_experiment.py` / `agent_e/core.py` |
| 3 | 十一格渲染提示词里「E」与「形式化」同句出现次数 = 0 | `specs/*.py` 与 `agent_prompts.py` 的文案 |
| 4 | 开关开 / 关两档下 E 的 Lean 侧行为逐字相同（不再受开关影响） | `agent_e/_support.py` 的写死判据 |
| 5 | 反真空：把 E 的 formal 支恢复 ⇒ 判据 2 必红 | 尺子本身 |
| 2b | 反真空（`draft/146` D30）：把拒绝体退回改前九格 ⇒ 判据 2 必红 | `agent_e/core.py::_formal_refusal` |

## 「写死关闭」落在哪两处，以及为什么不删代码

- 工具面：`verify.check_formal` 的 `roles` 从 `('E','F','G')` 收成 `()`。工具仍然
  装配在注册表里（`reg.get('verify.check_formal')` 拿得到、函数级复用照旧，
  `agent_l._CheckFormalL` 就是继承 E 那一份实现），但它不属于任何角色 ——
  于是谁的 `for_role` 里都没有它；
- 动作面：`AgentE.run_experiment(method='formal')` 与 `AgentE.check_formal` 在第一句
  就给出受控拒绝 `formal_moved_to_l`，判据是 `agent_e._support.E_LEAN_SIDE_HARD_OFF`
  —— 模块里的一个字面量 `True`，没有环境变量、没有设置文件键能改它。判据 5 直接改
  那个字面量来证明判据 2 不是真空的。

业主的口径是「代码先不删（等 L 被证实后再删）」：所以 `_record_formal` /
`_CheckFormal` 这两个实现体一个字都没动，删掉的只是「E 被授予这条路」这件事。

## 判据 3 的「同句」怎么切

切法只有一处：中文句末（`。！？`）与换行。角色名 `E` 按 ASCII 词边界匹配 ——
`LEAN` / `LEAN_ENABLED` / `DEP` 里的 E 不算，`E 的` / `（E）` / `找 E` 算。
不按「含形式化三个字」一刀切，是因为「形式化」在中文里还有一个与 Lean 无关的用法
（把问题精确地形式化），而那一类句子本来就不该被这条判据管。

## 判据 4 的射程是「行为」，不是「提示词逐字」

E 的提示词里仍有指向 L 的句子（「形式化那一岗是 L」），而 L 在开关关着时不存在
（`leanscope.is_hidden`）⇒ 那段文字必须跟着开关变，否则关着时会把模型指向一个
这一档根本不存在的角色。所以 4 判的是行为：同一句话、同一个理由码、同一个键集合。

## 零模型

全部用例只读代码与本地开关：不起模型、不花一分钱、不写工作区以外的任何东西。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow import settings as SET
from agentflow.agent_e import FORMAL_REASONS, AgentE, ExperimentError
from agentflow.agent_e import _support as SUP
from agentflow.store import Store
from agentflow.tools import build_registry

#: 那个「E 的 Lean 侧已停用」的受控拒绝码（裁定要的是一个新码，不是 `lean_disabled`：
#: 后者在今天的语义是「用户把开关关掉了」，而这条路是写死的、与用户设置无关）。
CODE = "formal_moved_to_l"

#: 角色名的记号。边界按 ASCII 词字符算，所以 `LEAN` / `Mathlib` / `E_LEAN` 里的 E 不算。
E_TOKEN = re.compile(r"(?<![A-Za-z0-9_])E(?![A-Za-z0-9_])")

#: 角色名 `L` 的记号（判据 3 的反真空用它：形式化那一路必须仍然点着 L）。
L_TOKEN = re.compile(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])")

#: 「同句」的唯一切法：中文句末与换行（`；` 不算 —— 它常把「这件事归谁」与
#: 「怎么做」连在一句里，而那正是这条判据要看的形态）。
SENT_SPLIT = re.compile(r"[。！？\n]")

#: 受控拒绝的十二个键（`E-12(a)` 的键集合契约九格 + `draft/146` D30 那三格，
#: 判据 2 的「不抛栈」那一半按它核）。
#:
#: 2026-10-23（D29/D30）：这里原来是九格 —— 那条旧断言记录的是改前缺陷形态：拒绝体里
#: 没有 `refused` / `refusal_reason` / `status`，于是派发层（`conductor._end_from_payload`）
#: 把一次受控拒绝读成 `done/ok`。补上这三格之后尺子必须同步加宽；负控
#: `test_2b_the_nine_key_body_turns_criterion_2_red` 把 `agent_e/core.py` 那处修复退回去，
#: 本尺子当场红 —— 所以"十二格"读的是契约，不是照着实现抄下来的。
REFUSAL_KEYS = ("checked", "verified", "claim", "reason", "detail",
                "verifier_output", "missing_imports", "verifier_status", "exit_code",
                "refused", "refusal_reason", "status")


def _roles() -> tuple[str, ...]:
    """全部十一个格（十个可召唤角色 + 主控）。"""
    return tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)


def _registry():
    return build_registry().registry


def _set_switch(on: bool) -> None:
    """改开关并清掉提示词层那个缓存（`leanscope` 自己不缓存）。"""
    import os

    os.environ[SET.ENV_LEAN_ENABLED] = "1" if on else "0"
    AP.reset_toolchain_readings()


@pytest.fixture(autouse=True)
def _restore_the_switch_at_the_end(monkeypatch: pytest.MonkeyPatch):
    """本文件有一条用例直接改环境变量（不走 `monkeypatch`）⇒ 结束时按原值放回。

    为什么必须有这一条：开关读数是"环境变量 > 设置文件 > 缺省"的梯子，而提示词层还
    给它加了一个 `lru_cache`。一条用例把环境变量改成 `0` 之后如果留着，后面所有文件的
    渲染都会在"Lean 关"那一档跑 —— 那不是彼此的判据坏了，而是这一条漏了还原。
    （判据 4 的两档切换必须真的改环境变量：`leanscope` 每一次调用都现读它。）
    """
    import os

    before = os.environ.get(SET.ENV_LEAN_ENABLED)
    yield
    if before is None:
        os.environ.pop(SET.ENV_LEAN_ENABLED, None)
    else:
        os.environ[SET.ENV_LEAN_ENABLED] = before
    AP.reset_toolchain_readings()


def _agent(tmp_path: Path, name: str = "ws") -> tuple[AgentE, Store]:
    ws = tmp_path / name
    st = Store(ws)
    st.init()
    return AgentE(st, workspace_root=ws), st


def _lean_file(tmp_path: Path, name: str = "ws") -> str:
    """写一份看起来像样的 .lean 产物，返回工作区相对路径。

    必须在 `Store.init()` 之后调用：`init` 对「非空又不是工作区」的目录是拒绝的
    （那道守卫是对的 —— 这里不改它，只是把顺序写对）。
    """
    rel = "code/formal/probe.lean"
    p = tmp_path / name / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("theorem probe_hard_off : 1 + 1 = 2 := rfl\n", encoding="utf-8")
    return rel


# ============================================================ 1. 工具面
def test_1_no_role_surface_holds_verify_check_formal(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 1：任何角色（含 E）的工具面里都没有 `verify.check_formal`。

    改前红（2026-10-22 实测，改之前逐字）：`verify.check_formal` 的 `roles` 是
    `('E', 'F', 'G')` ⇒ `for_role('E')` / `for_role('F')` / `for_role('G')` 三张面上
    都有它，`reg.get('verify.check_formal').roles == ('E', 'F', 'G')`。

    反真空两半（缺一条这一条就可能只是「工具被整体删掉了」）：
    - 代码没删：`reg.get('verify.check_formal')` 仍然拿得到（函数级复用照旧）；
    - 形式化这条路没消失：L 的面上仍然有 `formal.formalize` / `formal.check_formal`；
    - E 没被顺手削弱：`verify.run_experiment` 仍在 E 的面上。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    AP.reset_toolchain_readings()
    reg = _registry()

    holders = {}
    for role in _roles():
        names = [str(getattr(s, "name", "")) for s in reg.for_role(role)]
        if "verify.check_formal" in names:
            holders[role] = names
    assert holders == {}, (
        "这些角色的工具面上还有 `verify.check_formal`（E 的 Lean 侧已写死关闭，"
        f"这一件不该再发给任何人）：{sorted(holders)}")

    spec = reg.get("verify.check_formal")
    assert spec is not None, "工具被整体删掉了 —— 业主的口径是「代码先不删，只写死关闭」"
    assert tuple(spec.roles) == (), f"roles 必须收成空元组（不属于任何角色），收到 {spec.roles!r}"

    l_names = [str(getattr(s, "name", "")) for s in reg.for_role("L")]
    assert "formal.formalize" in l_names and "formal.check_formal" in l_names, (
        f"L 的面上缺了形式化入口 ⇒ 这条路被整体摘掉了（不是「搬去 L」）：{l_names}")
    e_names = [str(getattr(s, "name", "")) for s in reg.for_role("E")]
    assert "verify.run_experiment" in e_names, (
        f"E 的数值实验也被一起摘掉了（这一版只关 Lean 侧）：{e_names}")


# ============================================================ 2. 动作面
def _action_face_signature(tmp_path: Path) -> dict:
    """E 动作面里 formal 那一支的拒绝形状（判据 2 与 5 共用的那把尺子）。

    两格都取：`run_experiment(method='formal')` 与 `check_formal(...)`。
    抛栈在这里是「没有拿到受控拒绝」的同义词：受控形态只有两种 ——
    `ExperimentError`（动作的既有拒绝类型）与十二格 dict（查询类动作的回执：
    工具层那九格 + `draft/146` D30 的 `refused` / `refusal_reason` / `status`）。
    """
    e, st = _agent(tmp_path)
    rel = _lean_file(tmp_path)
    out: dict = {}
    try:
        e.run_experiment("内核级命题：1+1=2", "hard-off-probe", rel, method="formal")
    except ExperimentError as exc:                      # 受控拒绝（不抛栈）
        out["run_experiment"] = ("controlled", type(exc).__name__, str(exc))
    except Exception as exc:                            # noqa: BLE001 - 未受控 = 判据要红
        out["run_experiment"] = ("uncontrolled", type(exc).__name__, str(exc))
    else:
        out["run_experiment"] = ("returned", "", "")

    got = e.check_formal("内核级命题：1+1=2", source="theorem t : True := trivial", name="t")
    out["check_formal"] = dict(got)
    out["rows_after"] = len(st.rows("experiments"))
    return out


def _formal_problems(sig: dict) -> list[str]:
    """把「这一支有没有被写死关掉」判成一组人话（空列表 = 关上了）。

    2026-10-23（D29/D30）：这里核的键集合从九格加宽到十二格 —— 旧断言记录的是改前
    缺陷形态（拒绝体缺 `refused` / `refusal_reason` / `status`，派发层于是把这次拒绝
    读成 `done/ok`）。反真空见 :func:`test_2b_the_nine_key_body_turns_criterion_2_red`。
    """
    bad: list[str] = []
    state, kind, msg = sig["run_experiment"]
    if state != "controlled":
        bad.append(f"run_experiment(method='formal') 没有给出受控拒绝：{state} / {kind}: {msg[:120]}")
    if CODE not in msg:
        bad.append(f"run_experiment 的拒绝码不是 {CODE}：{msg[:160]}")
    if kind != "ExperimentError":
        bad.append(f"受控类型不是 ExperimentError（收到 {kind}）")
    got = sig["check_formal"]
    if set(got) != set(REFUSAL_KEYS):
        bad.append(f"check_formal 的键集合变了：{tuple(got)}")
    if got.get("reason") != CODE:
        bad.append(f"check_formal 的受控理由不是 {CODE}：{got.get('reason')!r}")
    if got.get("checked") is not False:
        bad.append(f"check_formal 的 checked 必须是 False（没查成），收到 {got.get('checked')!r}")
    if got.get("verified") is not None:
        bad.append(f"check_formal 的 verified 必须是 None（不冒充没通过），收到 {got.get('verified')!r}")
    if sig["rows_after"] != 0:
        bad.append(f"被拒绝的 formal 实验落了 {sig['rows_after']} 行（一行都不许落）")
    return bad


def test_2_e_formal_action_is_a_controlled_refusal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 2：E 的动作面里 formal 那一支 ⇒ 受控拒绝，码 = `formal_moved_to_l`（不抛栈）。

    改前红（2026-10-22 实测，改之前逐字）：开关开着（套件钉的就是这一档）时
    `AgentE.run_experiment(..., method='formal')` 不拒绝 —— 它真的走到
    `_record_formal`，于是「E 能被派去做形式化」这件事在这一档是成立的；
    `AgentE.check_formal(...)` 则返回检查器的真实结论（无后端时 `no_backend`，
    有后端时 `verified` / `compile_error`），两个值都不是 `formal_moved_to_l`。

    「不抛栈」的判据是形态：拿到的必须是 `ExperimentError`（E 的既有受控拒绝类型）
    或十二格回执 dict，而不是 `KeyError` / `TypeError` / `AttributeError` 这类
    未受控的崩溃（`_formal_problems` 把这两档分开判）。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    AP.reset_toolchain_readings()
    monkeypatch.setattr(SUP, "E_LEAN_SIDE_HARD_OFF", True, raising=True)
    problems = _formal_problems(_action_face_signature(tmp_path))
    assert problems == [], "E 的 formal 那一支没有被写死关闭：\n  " + "\n  ".join(problems)
    assert CODE in FORMAL_REASONS, (
        f"受控理由码 {CODE} 不在 agent_e.FORMAL_REASONS 里 ⇒ 它成了词表外的野码：{FORMAL_REASONS}")


def _old_nine_key_refusal(self, claim, reason, detail):  # noqa: ANN001 - 与真方法同签名
    """改前那一版拒绝体（`draft/146` D30 之前逐字：只有工具层那九格）。"""
    return {
        "checked": False, "verified": None, "claim": claim, "reason": reason,
        "detail": detail, "verifier_output": "", "missing_imports": [],
        "verifier_status": "", "exit_code": None,
    }


def test_2b_the_nine_key_body_turns_criterion_2_red(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（`draft/146` D30，2026-10-23）：把 E 的拒绝体退回改前那九格 ⇒ 判据 2 必红。

    为什么必须有这一条：判据 2 现在比较的是十二格。没有负控的话，"十二格"可以是
    照着实现抄下来的（尺子随实现漂），于是那条判据只剩同义反复。这里把
    `agent_e/core.py::_formal_refusal` 换回九格（就是改前缺陷形态：派发层读不到
    `refused` / `refusal_reason` / `status` ⇒ 一次受控拒绝被记成 `done/ok`），
    `_formal_problems` 必须报出「键集合变了」—— 于是它读的是修复本身。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    AP.reset_toolchain_readings()
    monkeypatch.setattr(SUP, "E_LEAN_SIDE_HARD_OFF", True, raising=True)
    owner = next(cls for cls in AgentE.__mro__ if "_formal_refusal" in vars(cls))
    monkeypatch.setattr(owner, "_formal_refusal", _old_nine_key_refusal, raising=True)

    problems = _formal_problems(_action_face_signature(tmp_path))
    assert problems, "退回九格之后判据 2 居然还是绿的 ⇒ 那把尺子是真空的"
    assert any("键集合变了" in p for p in problems), problems


# ============================================================ 3. 提示词
def _same_sentence_pairs(text: str) -> list[str]:
    """这一份渲染文本里「E」与「形式化」同句出现的那几句（判据 3 的单角色尺子）。"""
    out: list[str] = []
    for sent in SENT_SPLIT.split(text):
        s = sent.strip()
        if "形式化" in s and E_TOKEN.search(s):
            out.append(s)
    return out


def test_3_no_cell_pairs_e_with_formalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 3：全部十一格的渲染提示词里，「E」与「形式化」同句出现次数 = 0。

    改前红（2026-10-22 实测，逐字）：

    - D / F / G / H / M 五格的伙伴表：`- E：数值实验与攻坚：把一条断言变成可复现的
      实验或反例（形式化那一岗是 L）；它交付：…`（五处，来自 E 的 `duty`）；
    - E 自己的第一句：`你是 E 号角色，职责是：数值实验与攻坚：…（形式化那一岗是 L）`；
    - G / H / M 各一句：`这两步都在 L 那一岗（2026-10-22 起形式化只由 L 做；
      E 那一岗是实验与反例）：`；
    - H 的官能注解：`- 手：…再按性质找 A（引文）/ E（实验）核实、或走形式化那一岗
      （形式化那一岗是 L），或请 G 修订`；
    - M 的派活纪律：`…派 E 做纯数值就是把这条要求降级了（形式化那一岗是 L）`；
    - M 的研究链八环：`…（去派签位的人：数值 E、形式化 L、证明 F、审过 V、正式审查 H；…）`。

    合计 12 处（D=1 / E=1 / F=1 / G=2 / H=3 / M=4），A / B / C / V / L 五格本来就是 0。

    反真空两条：这一档「形式化」的总出现次数仍然很多（不是靠删光这两个字换来的），
    且其中相当一部分句子点着 L（形式化那一路没有变成无人认领）。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    AP.reset_toolchain_readings()
    reg = _registry()

    offenders: list[str] = []
    for role in _roles():
        text = AP.system_prompt(role, registry=reg)
        assert len(text) > 3000, f"{role} 的渲染文本只有 {len(text)} 字符 ⇒ 这一条是真空的"
        for sent in _same_sentence_pairs(text):
            offenders.append(f"{role}: {sent[:200]}")
    assert offenders == [], (
        f"这些句子把「E」与「形式化」写在同一句里（共 {len(offenders)} 处）：\n  "
        + "\n  ".join(offenders))

    formal_total = sum(AP.system_prompt(r, registry=reg).count("形式化") for r in _roles())
    assert formal_total >= 60, (
        f"十一格加起来只剩 {formal_total} 处「形式化」⇒ 这一条可能是靠删光换来的")
    paired_with_l = 0
    for role in _roles():
        for sent in SENT_SPLIT.split(AP.system_prompt(role, registry=reg)):
            if "形式化" in sent and L_TOKEN.search(sent):
                paired_with_l += 1
    assert paired_with_l >= 30, (
        f"只有 {paired_with_l} 句「形式化」点着 L ⇒ 形式化那一路成了无人认领")


# ============================================================ 4. 行为不随开关变
def _lean_side_fingerprint(tmp_path: Path, name: str) -> dict:
    """E 的 Lean 侧在这两档下的行为指纹（逐字可比）。"""
    e, st = _agent(tmp_path, name)
    rel = _lean_file(tmp_path, name)
    fp: dict = {}
    try:
        e.run_experiment("内核级命题：1+1=2", "fingerprint", rel, method="formal")
    except ExperimentError as exc:
        fp["run_experiment"] = ("ExperimentError", str(exc))
    except Exception as exc:                            # noqa: BLE001 - 两档都不许出这一支
        fp["run_experiment"] = ("uncontrolled", f"{type(exc).__name__}: {exc}")
    else:
        fp["run_experiment"] = ("returned", "")
    fp["check_formal"] = json.dumps(
        e.check_formal("内核级命题：1+1=2", source="theorem t : True := trivial", name="t"),
        ensure_ascii=False, sort_keys=True)
    # 负控：数值那条路两档都要照常（关 Lean 侧不许把 E 整个关掉）
    num = tmp_path / name / "code" / "num.py"
    num.parent.mkdir(parents=True, exist_ok=True)
    num.write_text('print("REPRO_RESULT: {\\"result\\": \\"supports\\"}")\n',
                   encoding="utf-8")
    got = e.run_experiment("数值命题", "fingerprint-num", "code/num.py", method="numeric")
    fp["numeric"] = (got["recorded"], got["result"], got["evidence_kind"])
    fp["rows"] = len(st.rows("experiments"))
    return fp


def test_4_e_lean_side_is_the_same_in_both_switch_positions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 4：开关开 / 关两档下，E 的 Lean 侧行为逐字相同（写死关闭 ⇒ 不再受开关影响）。

    改前红（2026-10-22 实测，逐字）：开关关着时 `run_experiment(method='formal')`
    抛的是「本会话的 Lean 形式化已关闭（`toolchain.lean_enabled=false` …）」，
    `check_formal` 回 `reason='lean_disabled'`；开关开着时前者根本不拒、后者回
    检查器结论 ⇒ 两档的指纹不同（这一条判据在改前是红的，且红的原因正是裁定要治的病：
    「测 L 的时候，E 那一侧的行为跟着开关跳」）。

    负控（同一个用例里）：`method='numeric'` 两档都必须照常跑通 —— 关掉 Lean 侧
    不等于把 E 关掉，否则这一条会退化成「E 死了，所以两档一样」。
    """
    monkeypatch.setattr(SUP, "E_LEAN_SIDE_HARD_OFF", True, raising=True)

    _set_switch(True)
    on = _lean_side_fingerprint(tmp_path, "ws_on")
    _set_switch(False)
    off = _lean_side_fingerprint(tmp_path, "ws_off")
    _set_switch(True)          # 还原成套件钉的那一档
    AP.reset_toolchain_readings()

    differing = {k: (on.get(k), off.get(k)) for k in on if on.get(k) != off.get(k)}
    assert differing == {}, (
        "E 的 Lean 侧行为还跟着开关变（写死关闭之后两档必须逐字相同）：\n  "
        + json.dumps(differing, ensure_ascii=False, indent=1)[:2000])
    # 反真空：两档都真的走到了「受控拒绝」，而不是两档都空转
    assert on["run_experiment"][0] == "ExperimentError", on["run_experiment"]
    assert CODE in on["run_experiment"][1], on["run_experiment"][1][:200]
    assert on["numeric"][0] is True and off["numeric"][0] is True, (on["numeric"], off["numeric"])
    assert "lean_disabled" not in on["run_experiment"][1], (
        "写死关闭之后不许再报 lean_disabled（那是「用户关掉了开关」的意思）")


# ============================================================ 5. 反真空
def test_5_restoring_the_formal_branch_turns_criterion_2_red(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 5：把 E 的 formal 支恢复 ⇒ 判据 2 必红（同一把尺子，不许另写一份）。

    怎么恢复：`agent_e._support.E_LEAN_SIDE_HARD_OFF` 是唯一判据，把它改成 `False`
    就等于把「E 能被派去做形式化」这件事放回来。此时
    `run_experiment(method='formal')` 不再给 `formal_moved_to_l`、
    `check_formal` 回到检查器那条路 ⇒ `_formal_problems` 必须报出问题。

    为什么必须有一条这样的负控：判据 2 判的是「拒绝码等于某个值」。如果那段代码
    根本没被执行（例如守卫被别处短路了、或尺子读错了键），它照样会绿；只有
    「把守卫拆掉之后它变红」才能证明那把尺子真的量在这条路上。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    AP.reset_toolchain_readings()

    monkeypatch.setattr(SUP, "E_LEAN_SIDE_HARD_OFF", True, raising=True)
    assert _formal_problems(_action_face_signature(tmp_path / "closed")) == [], (
        "正控失败：写死关闭的那一档本来就没关上")

    monkeypatch.setattr(SUP, "E_LEAN_SIDE_HARD_OFF", False, raising=True)
    problems = _formal_problems(_action_face_signature(tmp_path / "open"))
    assert problems, (
        "把 E 的 formal 支恢复之后判据 2 居然还是绿的 ⇒ 那把尺子是真空的")
    assert any(CODE in p for p in problems), (
        f"恢复之后报出来的问题里没有一条提到 {CODE}：{problems}")
