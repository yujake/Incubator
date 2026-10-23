# -*- coding: utf-8 -*-
"""E 没有 Lean 侧：业主 2026-10-23 晚裁定「E 侧与 Lean 相关的工具和动作都该清干净」。

这一份接替 `test_e_lean_side_is_hard_off.py`。那一份守的是「写死关闭」（E 的动作面还在、
只是第一句拒绝）；裁定之后那个概念本身没了：E 的动作表里没有 `check_formal`、E 的工具面
里没有形式化那一族、E 的代码里没有 formal 的实现路径。所以这里判的是「没有」，不是
「关着」。

六条判据（对应施工单的 ①–⑥，每条都在用例 docstring 里写明改前红）：

| # | 判据 | 落点 |
|---|---|---|
| 1 | E 的动作表恰好四格，不含 `check_formal` | `specs/e.py::ACTIONS` / `capabilities.CAPABILITIES` |
| 2 | E 的工具面按名枚举：无 `verify.check_formal` / 无 `formal.*` / 无 `verify.detect_verifier` | `tools/verify_tools.py` 的 `roles` |
| 3 | `run_experiment(method="formal")` 受控拒绝，理由是「E 不做形式化」（新理由码） | `agent_e/run_experiment.py` |
| 3b | E 的渲染提示词里不出现「已停用 / 写死关闭 / formal_moved_to_l」，且 E 与「形式化」不同句 | `specs/e.py` 的文案 |
| 4 | 全仓代码没有那四个已删符号（`_record`+`_formal` / `lean_side`+`_reading` / `e_lean_side`+`_hard_off` / `E_LEAN_SIDE`+`_HARD_OFF`） | 四个符号的引用 |
| 5 | L 仍能形式化：三件工具 + 继承的 `_CheckFormal` + 真 lean 正控 | `agent_l/` 与 `tools/formal_tools.py` |
| 6 | 反真空：把 `check_formal` 加回 E 的动作表 ⇒ 判据 1 必红 | 尺子本身 |

## 判据 1 为什么读两处

`specs/e.py::ACTIONS` 是声明的真身，`capabilities.CAPABILITIES` 是派生出来的那张表
（`tests/test_capabilities_two_layer.py` 守着两层一致）。只读一处的话，「声明删了而派生
表没跟上」或反过来都会漏过去；两处都读，才是「E 的动作面」这件事的完整读数。

## 判据 4 的射程

扫的是代码根（`src` / `tests` / `scripts` / `tools` 下的 `*.py`）。四个符号在代码里出现
一次就说明还有一条活着的引用；文档（`docs/*.md`）里的历史叙述不在这条判据的射程内，
它们的清单单独交给业主（施工单要求「文档数字列清单」，本文件不改文档）。

## 零模型

全部用例只读本地代码、本地声明与本地检查器：不起模型、不花一分钱。
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as CAP
from agentflow import leanscope as LS
from agentflow import schema as S
from agentflow import settings as SET
from agentflow.agent_e import AgentE, ExperimentError
from agentflow.specs import action_table
from agentflow.specs import e as E_SPEC
from agentflow.store import Store
from agentflow.tools import build_registry

#: E 的动作面：裁定之后恰好这四格（顺序按 `specs/e.py` 的声明）。
EXPECTED_E_ACTIONS: tuple[str, ...] = (
    "run_experiment", "evidence_for", "list_experiments", "run_script_experiment",
)

#: 判据 3 要的那个新理由码（施工单：「理由不指向搬到 L，而是 E 不做形式化」）。
#: 这是判据自己钉的契约值；实现在 `agent_e/_support.py` 里以同一个字符串定义。
NO_FORMAL_REASON = "formal_not_in_e"

#: 判据 2 要排除的三族工具名（按名枚举，不靠数量）。
FORBIDDEN_TOOL_EXACT = ("verify.check_formal", "verify.detect_verifier")
FORBIDDEN_TOOL_PREFIX = ("formal.",)

#: 判据 4 的四个符号。拆成两段拼，是为了让本文件自己不出现在 grep 的命中里
#: （判据扫的是全部 `.py`，包括它的判据）。
_DEAD_SYMBOLS: tuple[str, ...] = (
    "_record" + "_formal",
    "lean_side" + "_reading",
    "e_lean_side" + "_hard_off",
    "E_LEAN_SIDE" + "_HARD_OFF",
)

#: 判据 3b 的尺子：这些词说的是「这一侧停用了」，裁定之后 E 的提示词里一句都不许有。
_DISABLED_MARKS: tuple[str, ...] = ("已停用", "写死关闭", "formal_moved_to_l")

#: 角色名 `E` 的记号（ASCII 词边界；`LEAN` / `Mathlib` / `E_LEAN` 里的 E 不算）。
E_TOKEN = re.compile(r"(?<![A-Za-z0-9_])E(?![A-Za-z0-9_])")
#: 角色名 `L` 的记号（判据 3 用它证明拒绝理由没有把活推给 L）。
L_TOKEN = re.compile(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])")
#: 「同句」的唯一切法：中文句末与换行（与 `test_lean_switch_points_at_l.py` 同一口径）。
SENT_SPLIT = re.compile(r"[。！？\n]")

#: 本机那一版真 Lean（与 `tests/test_l_faithfulness_is_measurable.py` 同一口径：
#: 套件把机器设置钉掉之后，只有绝对路径这一档还能起真检查器）。
LEAN = Path(r"D:\Incubator\_env\lean470\lean-4.7.0-windows\bin\lean.exe")
HAVE_LEAN = LEAN.is_file()


def _roles() -> tuple[str, ...]:
    """全部十一个格（十个可召唤角色 + 主控）。"""
    return tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)


def _registry():
    """开档的注册表（L 与 `formal.*` 在关档不存在，判据 2 要的是开档那一面）。"""
    return build_registry().registry


def _set_switch(on: bool) -> None:
    """改开关并清掉提示词层那个缓存（`leanscope` 自己每次现读）。"""
    import os

    os.environ[SET.ENV_LEAN_ENABLED] = "1" if on else "0"
    AP.reset_toolchain_readings()


@pytest.fixture()
def lean_on():
    """开档：判据 2 与 5 都要 L 存在，否则「L 仍能形式化」会退化成「L 不在」。"""
    import os

    before = os.environ.get(SET.ENV_LEAN_ENABLED)
    _set_switch(True)
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(SET.ENV_LEAN_ENABLED, None)
        else:
            os.environ[SET.ENV_LEAN_ENABLED] = before
        AP.reset_toolchain_readings()


def _agent(tmp_path: Path) -> tuple[AgentE, Store]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    return AgentE(st, workspace_root=ws), st


# ============================================================ 1. 动作表
def _action_face_problems(actions) -> list[str]:
    """判据 1 的尺子：这一张动作表是不是「恰好四格、没有 check_formal」。

    判据 6 用同一把尺子量一张被注入过的表（多回一格 `check_formal`）—— 这样
    「判据 1 真的量在这条路上」与「判据 1 不是照着实现抄的」两件事各有一条读数。
    """
    names = tuple(str(getattr(a, "action", "")) for a in actions)
    bad: list[str] = []
    if len(names) != len(EXPECTED_E_ACTIONS):
        bad.append(f"E 的动作表有 {len(names)} 格（应当是 {len(EXPECTED_E_ACTIONS)} 格）：{names}")
    if set(names) != set(EXPECTED_E_ACTIONS):
        extra = sorted(set(names) - set(EXPECTED_E_ACTIONS))
        missing = sorted(set(EXPECTED_E_ACTIONS) - set(names))
        bad.append(f"E 的动作表与预期集合不同：多 {extra} / 少 {missing}")
    if "check_formal" in names:
        bad.append("E 的动作表里还有 check_formal（这一整条该摘掉，不是写死关闭）")
    return bad


def test_1_the_action_face_is_exactly_four_actions() -> None:
    """判据 1：E 的动作表 == 4 个，不含 `check_formal`。

    改前红（2026-10-23 实测，改之前逐字）：
    `capabilities.CAPABILITIES["E"]` 读到五格
    `['run_experiment', 'check_formal', 'evidence_for', 'list_experiments', 'run_script_experiment']`
    —— `specs/e.py` 里 `ActionSpec("E", "check_formal", ...)` 那一整条还在，摘要是
    「已停用（本岗的 Lean 侧写死关闭）：…」，所以后面三条判据（动作数 / 集合 / 无 check_formal）
    全红。

    读两处：声明真身（`specs.action_table()`）与派生表（`CAP.actions_for`）。
    """
    declared = _action_face_problems(action_table()["E"])
    derived = _action_face_problems(CAP.actions_for("E"))
    assert declared == [], "声明真身（`specs/e.py::ACTIONS`）不干净：\n  " + "\n  ".join(declared)
    assert derived == [], "派生表（`capabilities.CAPABILITIES['E']`）不干净：\n  " + "\n  ".join(derived)


# ============================================================ 2. 工具面
def test_2_the_tool_face_has_no_lean_family(lean_on) -> None:
    """判据 2：E 的工具面按名枚举 —— 无 `verify.check_formal` / 无 `formal.*` / 无 `verify.detect_verifier`。

    改前红（2026-10-23 实测，改之前逐字）：
    `verify.detect_verifier` 的 `roles` 是 `_ROLES == ('E', 'F', 'G', 'H')` ⇒
    `for_role('E')` 的 17 件里第 10 件就是它；`verify.check_formal` 那时 `roles=()`
    （只是「不属于任何角色」），但仍然装配在注册表里 ⇒ `reg.names()` 里找得到它。

    三半反真空（缺一条这一条就可能只是「工具被整体删掉了」）：
    - E 没有被顺手削弱：`verify.run_experiment` / `verify.code_hash` 仍在 E 的面上；
    - 桥接层没有被删：`verify.detect_verifier` 仍在 F / G / H 的面上（它属 Lean 侧，但
      仍是那三家的读数入口），`verify.check_formal` 函数本体也还在（L 经它取原话）；
    - 形式化这条路没消失：L 的面上仍有三件 `formal.*`。
    """
    reg = _registry()
    names = [str(getattr(s, "name", "")) for s in reg.for_role("E")]
    bad = [n for n in names
           if n in FORBIDDEN_TOOL_EXACT or any(n.startswith(p) for p in FORBIDDEN_TOOL_PREFIX)]
    assert bad == [], f"E 的工具面上还有 Lean 侧的工具：{bad}（E 的整面 {names}）"
    assert "verify.check_formal" not in reg.names(), (
        "`verify.check_formal` 还装配在注册表里 —— 裁定要求这一件整条删掉，"
        "而不是把 `roles` 收成空集")

    assert {"verify.run_experiment", "verify.code_hash"} <= set(names), (
        f"E 的数值实验那一面被一起摘掉了（这一版只清 Lean 侧）：{names}")
    for role in ("F", "G", "H"):
        got = [str(getattr(s, "name", "")) for s in reg.for_role(role)]
        assert "verify.detect_verifier" in got, (
            f"{role} 的面上也没有 verify.detect_verifier 了 —— 它只是从 E 拿掉，"
            f"不是从全树删掉：{got}")
    l_names = [str(getattr(s, "name", "")) for s in reg.for_role("L")]
    for want in ("formal.formalize", "formal.check_formal", "formal.record"):
        assert want in l_names, f"L 的面上缺了 {want} ⇒ 形式化被整体摘掉了：{l_names}"


# ============================================================ 3. 受控拒绝
def test_3_a_formal_experiment_is_refused_as_not_e_job(tmp_path: Path) -> None:
    """判据 3：`E.run_experiment(method="formal")` ⇒ 受控拒绝，理由是「E 不做形式化」。

    改前红（2026-10-23 实测，改之前逐字）：那一条受控拒绝的理由是
    「E 的 Lean 侧已停用（写死关闭，不再看 toolchain.lean_enabled 开关）：形式化由 L 承担
    （…）。」+「（理由码 formal_moved_to_l）」—— 它把「为什么不能做」说成「搬到 L 去了」，
    而裁定要的是「E 不做形式化」。

    三条一起判：
    - 形态：`ExperimentError`（E 的既有受控拒绝类型），不是 `TypeError` / `KeyError`；
    - 理由：新理由码 `formal_not_in_e` 在，`formal_moved_to_l` 不在；
    - 主语：「E 不做形式化」这句话在，且理由里不出现角色名 `L`（不把活推给谁）；
    - 一行都不落：被拒绝的 formal 实验不许在台账上留半条记录。
    """
    e, st = _agent(tmp_path)
    ws = Path(st.root)
    lean_rel = "code/formal/probe.lean"
    p = ws / lean_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("theorem probe_no_e_formal : 1 + 1 = 2 := rfl\n", encoding="utf-8")

    with pytest.raises(ExperimentError) as ei:
        e.run_experiment("内核级命题：1+1=2", "no-e-formal", lean_rel, method="formal")
    msg = str(ei.value)

    assert NO_FORMAL_REASON in msg, f"受控理由码不是 {NO_FORMAL_REASON}：{msg!r}"
    assert "formal_moved_to_l" not in msg, (
        f"理由还写着 formal_moved_to_l（那是「搬到 L」那个旧理由码）：{msg!r}")
    assert "不做形式化" in msg, f"理由没有说清「E 不做形式化」：{msg!r}"
    assert not L_TOKEN.search(msg), (
        f"理由里出现了角色名 L（裁定要求理由是「E 不做形式化」，不是「搬到 L」）：{msg!r}")
    assert st.rows("experiments") == [], f"被拒绝的 formal 实验落了行：{st.rows('experiments')}"

    # 负控：数值那一支照常（清 Lean 侧不许把 E 整个关掉）
    num = ws / "code" / "num.py"
    num.write_text('print("REPRO_RESULT: {\\"result\\": \\"supports\\"}")\n', encoding="utf-8")
    got = e.run_experiment("数值命题", "no-e-formal-num", "code/num.py", method="numeric")
    assert got["recorded"] is True and got["result"] == "supports", got


# ============================================================ 3b. 提示词
def test_3b_the_e_prompt_never_mentions_a_disabled_lean_side(lean_on) -> None:
    """判据 3b：E 的渲染提示词（开 / 关两档）里没有「停用」那套说法。

    改前红（2026-10-23 实测，改之前逐字，开档那一份 E 的提示词）：
    - 动作面那一行：`- check_formal：已停用（本岗的 Lean 侧写死关闭）：调用一律回受控拒绝
      `formal_moved_to_l`，形式化由 L 承担。…`；
    - policy 第 2 条整段：「先看 TOOLCHAIN_FACTS 的第一行（`toolchain` 段的
      `lean_enabled`）：那一行说「Lean 形式化：已关闭」时 … 理由码 `lean_disabled` …」；
    - policy 第 9 条：「写 Lean 源码的写法口径不在这里（形式化那一岗是 L）…」。

    裁定之后 E 既没有那一支动作、也不再有「关」这个概念 ⇒ 这三处都必须消失。

    反真空两条：E 的提示词仍然足够长（不是被清成空壳），而且「形式化」这件事仍然有人认领
    —— 同一份渲染里 `形式化` 与 `L` 同句出现（指向 L，不是无人认领）。
    """
    reg = _registry()
    renders: dict[str, str] = {}
    for tier, on in (("开", True), ("关", False)):
        _set_switch(on)
        try:
            renders[tier] = AP.system_prompt("E", registry=reg)
        finally:
            pass
    _set_switch(True)
    AP.reset_toolchain_readings()

    problems: list[str] = []
    for tier, text in renders.items():
        assert len(text) > 3000, f"[{tier}] E 的渲染只有 {len(text)} 字符 ⇒ 这一条是真空的"
        for mark in _DISABLED_MARKS:
            if mark in text:
                problems.append(f"[{tier}] 还写着「{mark}」")
        for sent in SENT_SPLIT.split(text):
            s = sent.strip()
            if "形式化" in s and E_TOKEN.search(s):
                problems.append(f"[{tier}] 「E」与「形式化」仍在同一句：{s[:160]}")
    assert problems == [], "E 的提示词里还有 Lean 侧停用的说法 / E 与形式化同句：\n  " + "\n  ".join(problems)

    on_text = renders["开"]
    assert "形式化" in on_text, "E 的提示词里一个「形式化」都没有了 ⇒ 这一条可能是靠删光换来的"
    assert any("形式化" in s and L_TOKEN.search(s) for s in SENT_SPLIT.split(on_text)), (
        "E 的提示词里没有一句把形式化指向 L ⇒ 那一路成了无人认领")


# ============================================================ 4. 符号
def test_4_no_code_reference_to_the_deleted_symbols() -> None:
    """判据 4：全仓代码里没有那四个符号（grep 0 处）。

    改前红（2026-10-23 实测，改之前逐字）：`_record`+`_formal` 在 `agent_e/core.py` /
    `agent_e/run_experiment.py` / `agent_l/record.py` / `formalgw.py` 与四个测试文件里
    共 13 处；`lean_side`+`_reading` 6 处（全在 `agent_e/`）；`e_lean_side`+`_hard_off` /
    `E_LEAN_SIDE`+`_HARD_OFF` 各 18 处（含 `leanscope.py` 的 docstring 与 `tests/`）。

    扫代码根（`src` / `tests` / `scripts` / `tools`），不扫 `docs/*.md`：文档里的历史叙述
    由业主统一处理（施工单要求列清单），本判据管的是「还有没有活着的引用」。
    """
    root = Path(__file__).resolve().parents[1]
    hits: list[str] = []
    for top in ("src", "tests", "scripts", "tools"):
        for path in sorted((root / top).rglob("*.py")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:  # pragma: no cover - 读不到就不是「没有引用」，是没查成
                hits.append(f"{path}: 读不了（没查成，不算 0 处）")
                continue
            for no, line in enumerate(text.splitlines(), 1):
                for sym in _DEAD_SYMBOLS:
                    if sym in line:
                        rel = path.relative_to(root).as_posix()
                        hits.append(f"{rel}:{no}: {sym}")
    assert hits == [], (
        f"这些代码还在引用已删掉的符号（{len(hits)} 处）：\n  " + "\n  ".join(hits[:40]))


# ============================================================ 5. L 仍能形式化
def test_5_l_can_still_formalize(lean_on, tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 5：L 仍能形式化 —— 三件工具都在、继承的 `_CheckFormal` 还在、真 lean 正控 exit 0。

    这一条是「保住真身」的判据：删 E 的 Lean 侧不该碰到 L。它没有「改前红」——
    改前改后都必须是绿的（它防的正是「清理时顺手把 L 也删了」）。所以它的强度来自
    正控本身：真起一次 `lean`，要 `verified=True` 且 `exit_code=0`。

    本机没有 lean 时 skip（那一条会如实说「没查成」，不是「通过」）。
    """
    from agentflow import leantoolchain as LT
    from agentflow.agent_e.check_formal import _CheckFormal
    from agentflow.agent_l import AgentL

    reg = _registry()
    l_names = [str(getattr(s, "name", "")) for s in reg.for_role("L")]
    for want in ("formal.formalize", "formal.check_formal", "formal.record"):
        assert want in l_names, f"L 的面上缺了 {want}：{l_names}"
    assert issubclass(AgentL, _CheckFormal), (
        "L 不再继承 `_CheckFormal` 了 —— E 的 Lean 侧真身被一起删掉了，"
        "而裁定只许删 E 那一侧")

    if not HAVE_LEAN:
        pytest.skip(f"本机没有那一版真 Lean（{LEAN}）⇒ 没查成，不算通过")
    monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()

    ws = tmp_path / "lws"
    st = Store(ws)
    st.init()
    a = AgentL(st, workspace_root=ws)
    got = a.check_formal(
        "内核级命题：1+1=2",
        source="theorem probe_l_still_formalizes : 1 + 1 = 2 := rfl\n",
        declaration_name="probe_l_still_formalizes",
        imports=(),
    )
    assert got.get("reason") == "verified" and got.get("verified") is True, got
    assert got.get("exit_code") == 0, f"真 lean 的退出码应当是 0，收到 {got.get('exit_code')!r}"
    assert "does not depend on any axioms" in str(got.get("verifier_output") or ""), got
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


# ============================================================ 6. 反真空
def test_6_putting_check_formal_back_turns_criterion_1_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 6：把 `check_formal` 加回 E 的动作表 ⇒ 判据 1 必红（同一把尺子）。

    怎么加回：`specs.action_table()` 每次调用都从 `specs.<角色>.SPEC.actions` 现取，所以
    把 `specs.e.SPEC` 换成一个「多回一格 `check_formal`」的副本就够了 —— 那正是改前
    那一版声明本身（`ActionSpec("E", "check_formal", ...)`）。

    为什么必须有这一条：判据 1 判的是「表里有几格、集合是什么」。如果它读的是一份
    抄下来的常量、或者那段代码根本没被走到，它照样会绿；只有「把真身改回改前那一版
    之后它变红」才能证明那把尺子真的量在这条路上。
    """
    from agentflow.agentspec import ActionSpec, _S, _obj

    # 正控：现在的真身 ⇒ 同一把尺子是绿的
    assert _action_face_problems(action_table()["E"]) == [], (
        "正控失败：E 的动作表本来就不干净")

    fake = ActionSpec(
        "E", "check_formal",
        "（反真空夹具：改前那一格的摘要）",
        _obj({"claim": _S}),
        "dict（checked=False + reason 表示『没法做』）",
        side_effect="read", handler_name="check_formal", external="exec",
    )
    injected = dataclasses.replace(E_SPEC.SPEC, actions=tuple(E_SPEC.ACTIONS) + (fake,))
    monkeypatch.setattr(E_SPEC, "SPEC", injected, raising=True)

    problems = _action_face_problems(action_table()["E"])
    assert problems, "把 check_formal 加回动作表之后判据 1 居然还是绿的 ⇒ 那把尺子是真空的"
    assert any("check_formal" in p for p in problems), problems
