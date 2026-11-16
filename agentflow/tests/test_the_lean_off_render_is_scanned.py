# -*- coding: utf-8 -*-
"""判据（17A）：Lean 关档那一档的渲染提示词也要过同一套扫描。

## 为什么要有这一条（审计 AU1 表一 A3）

`tests/conftest.py:179` 把 `AGENTFLOW_LEAN_ENABLED` 钉成 `"1"`（套件基线 = Lean 开），
而产品缺省是关（`settings.DEFAULT_LEAN_ENABLED`）。于是凡"只在关档渲染"的文案，CI
里永远看不见 —— 13A 那一句就是：`specs/b.py` 的 `PROOF_CHANNEL_NO_LEAN` 把
"再请 V 用 `verify.verify_proof` 逐行走查"（工具名）换进 B 的提示词，而 B 该派的是
动作 `V.verify_proof`（同文件另一处写对了）。`tests/test_l_is_isolated_when_lean_is_off.py`
守的是"关档渲染里不许出现 L 这个名字"，不守"换进去的那一段里有没有别家工具名"。

这一组把关档当一等渲染档：每个角色 / 每个秘书的提示词都在关档渲染一遍，并做
16A 同一套扫描（`tests/_prompt_surface.py`），外加动作名与参数形状。

## 13A 尚未修（FC-27）—— 它现在是一条显式的待办登记

`specs/b.py` 在 FC-27 禁改区：本批只交补丁（`temp/CL2-fc27-b-policy.patch`），不
apply。所以关档扫描今天会且只会报出 `("B", "verify.verify_proof")` 一对；这一对
不放进豁免表（那是"设计如此"的位置，它不是），而是放进 `_PENDING_FC27`：

- 正控：关档扫出来的未登记对，恰好等于 `_PENDING_FC27`（多一对 ⇒ 新的关档漏网）；
- 反真空：把 13A 的原句塞进别的角色的关档提示词 ⇒ 同一扫描必须红（证明它是判据抓的，
  不是它恰好没被扫到）；
- 无腐烂：补丁 apply 之后这一对会消失 ⇒ 下面那条判据会红，并点名"删掉登记"。

## 判据（e / f 与动作名、参数形状）

- e 关档渲染跑得通：A–H / V / M 每格都有非空提示词；L 只抛受控拒绝 `RoleHidden`
  （理由 `lean_off`），不抛别的东西；
- f 13A 那句若未修，关档扫描必须红；并且它只在关档出现（开档的 B 提示词里没有它）；
- 动作名：每份关档提示词里的 `角色.动作` 都查得到 `find_action`；
- 参数形状：每份关档提示词里的 `工具(kw=…)` 调用形，kw 必须是该工具声明的参数。
"""
from __future__ import annotations

import contextlib
import pathlib
import re
import tempfile
from typing import Iterator

import pytest

from agentflow import agent_prompts as AP
from agentflow import leanscope as LS
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import settings as SET
from agentflow.store import Store
from agentflow.tools import build_registry

from conftest import restore_lean_baseline
from test_prompt_action_names_exist import unknown_actions, unknown_f_actions
import _prompt_surface as PS

#: 十一格（Lean 开时含 L；关档时 L 不存在，见 `_render_all`）。
ALL_ROLES: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: 13A 的待办登记：`specs/b.py` 的 `PROOF_CHANNEL_NO_LEAN` 里那句工具名。
#: 2026-11-16：补丁 `temp/CL2-fc27-b-policy.patch` 已 apply（`V.verify_proof` 动作名），
#: 关档扫描不再有这一对 ⇒ 登记清空，下面那条判据随之转成"守卫已修形态"。
_PENDING_FC27: dict[tuple[str, str], int] = {}

#: `工具(kw=…)` 的调用形（只认小写点分工具名；`F.status` 这类动作不在射程）。
_CALL = re.compile(
    r"(?<![A-Za-z0-9_.])([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)\s*\(([^()]*)\)")
_KW = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)\s*=")


@contextlib.contextmanager
def _lean(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> Iterator[tuple[pathlib.Path, object]]:
    """把 Lean 开关显式钉到某一档，造一份该档的注册表；收尾回套件基线。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1" if enabled else "0")
    AP.reset_toolchain_readings()
    try:
        root = pathlib.Path(tempfile.mkdtemp(prefix="cl2-lean-off-"))
        st = Store(root)
        st.init()
        reg = build_registry(store=st, workspace_root=str(root)).registry
        yield root, reg
    finally:
        restore_lean_baseline(monkeypatch)


def _render(role: str, root: pathlib.Path, registry: object) -> str:
    return AP.system_prompt(role, registry=registry, task="把这条链路走一遍",
                            workspace_root=str(root))


def _render_all(root: pathlib.Path, registry: object) -> dict[str, str]:
    """关档下逐角色渲染；L 必须是受控拒绝（返回的 dict 里不含它）。"""
    out: dict[str, str] = {}
    for role in ALL_ROLES:
        try:
            text = _render(role, root, registry)
        except LS.RoleHidden as exc:
            assert role == "L", f"{role} 在关档下被 RoleHidden 拒了：{exc}"
            assert "lean_off" in str(exc), f"L 的拒绝理由里没有 lean_off：{exc}"
            continue
        out[role] = text
    return out


def _param_problems(text: str, registry: object, role: str) -> list[str]:
    """这份提示词里每一个 `工具(kw=…)` 的 kw 都必须是该工具声明的参数。"""
    specs = {spec.name: spec for spec in registry.for_role(role)}
    out: list[str] = []
    for m in _CALL.finditer(text):
        tool, args = m.group(1), m.group(2)
        spec = specs.get(tool)
        if spec is None:
            continue           # 跨面提及由 16A 那一层判；这里只判本角色的调用形
        declared = set((spec.params.get("properties") or {}))
        for kw in _KW.findall(args):
            if kw not in declared:
                out.append(f"{role}: {tool}({kw}=…) 的 {kw} 不在声明里"
                           f"（声明：{sorted(declared)}）")
    return out


def test_e_every_role_renders_under_lean_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """e：关档下每格都能渲染；L 只抛 `RoleHidden`（理由 lean_off），不抛别的。"""
    with _lean(monkeypatch, False) as (root, reg):
        texts = _render_all(root, reg)
        assert set(texts) == set(ALL_ROLES) - {"L"}, sorted(texts)
        for role, text in texts.items():
            assert text.strip(), f"{role} 的关档提示词是空的"
        # 反真空：整批不是空的；且关档真的没装形式化工具（否则这一档没有区分度）
        assert sum(len(t) for t in texts.values()) > 200000
        names = {str(n) for n in reg.names()}
        assert not [n for n in names if n.startswith("formal.")], sorted(names)
    restore_lean_baseline(monkeypatch)


def test_f_the_lean_off_scan_is_the_same_criterion(monkeypatch: pytest.MonkeyPatch) -> None:
    """f：关档扫描（工具名 ↔ 面）—— 今天恰好只剩 13A 那一对，且它是显式待办。"""
    with _lean(monkeypatch, False) as (root, reg):
        texts = _render_all(root, reg)
        pending: dict[tuple[str, str], int] = {}
        problems: list[str] = []
        for role, text in texts.items():
            problems += PS.scan(role, text, reg, mode="off")
            for token in PS.foreign_tokens(text, reg, role):
                if (role, token) not in PS.EXEMPT:
                    pending[(role, token)] = text.count(token)
        assert pending == _PENDING_FC27, (
            "关档下未登记的跨面工具名与待办登记不一致："
            f"现场 {pending} / 登记 {_PENDING_FC27} ⇒ "
            "新出现的关档漏网要逐条判；补丁 apply 之后这一对会消失，届时应把 "
            "`_PENDING_FC27` 清空")
        assert len(problems) == len(pending), (
            f"关档扫描报了 {len(problems)} 条，其中未登记对 {len(pending)} 条：\n  - "
            + "\n  - ".join(problems))
        for (role, token), count in pending.items():
            assert any(token in one for one in problems), (role, token, problems)
            assert count == 1, (role, token, count)
    restore_lean_baseline(monkeypatch)


def test_f_the_unfixed_13a_sentence_is_lean_off_only(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """f 的反真空：13A 那句逐字还在、且只在关档；把它塞进别的角色 ⇒ 同一扫描红。"""
    from agentflow.specs import b as B_SPEC

    # 静态：这一句的工具名形态只在关档那一份里（开档那份写的是动作名）。
    # 修/未修必须与 `_PENDING_FC27` 同步：补丁 apply 之后把登记清空，这条判据
    # 自动从"守卫未修形态"转成"守卫已修形态"，不需要再改这段代码。
    assert "verify.verify_proof" not in B_SPEC.PROOF_CHANNEL
    assert ("verify.verify_proof" in B_SPEC.PROOF_CHANNEL_NO_LEAN) == bool(_PENDING_FC27), (
        "13A 的修/未修状态与 `_PENDING_FC27` 对不上：补丁 apply 之后请把登记清空")

    with _lean(monkeypatch, False) as (root, reg):
        texts = _render_all(root, reg)
        if _PENDING_FC27:
            assert "再请 V 用 `verify.verify_proof` 逐行走查" in texts["B"]
        else:
            assert "verify.verify_proof" not in texts["B"]
            assert "`V.verify_proof`" in texts["B"]
        poisoned = texts["A"] + "\n再请 V 用 `verify.verify_proof` 逐行走查。\n"
        assert any("verify.verify_proof" in one
                   for one in PS.scan("A", poisoned, reg, mode="off"))

    with _lean(monkeypatch, True) as (root, reg):
        on_text = _render("B", root, reg)
        assert "verify.verify_proof" not in on_text, "开档也出现工具名了（不是关档专属）"
        assert "`V.verify_proof`" in on_text, "开档那一版应当写的是动作名 V.verify_proof"
    restore_lean_baseline(monkeypatch)


def test_action_names_in_the_lean_off_prompts_exist(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """动作名：关档每份提示词里的 `角色.动作` 都必须查得到。"""
    with _lean(monkeypatch, False) as (root, reg):
        texts = _render_all(root, reg)
        bad = {role: unknown_actions(text) for role, text in texts.items()}
        bad = {role: names for role, names in bad.items() if names}
        assert bad == {}, f"关档提示词里点名了能力表里没有的动作：{bad}"
        # 反真空：扫描器抓得住改前那个名字（`F.attack.step` 是工具名，不是动作）
        assert unknown_f_actions("派 `F.attack.step` 去做") == ["attack.step"]
    restore_lean_baseline(monkeypatch)


def test_param_shapes_in_the_lean_off_prompts_match_the_declarations(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """参数形状：关档提示词里的 `工具(kw=…)`，kw 必须是该工具声明的参数。"""
    with _lean(monkeypatch, False) as (root, reg):
        texts = _render_all(root, reg)
        problems: list[str] = []
        for role, text in texts.items():
            problems += _param_problems(text, reg, role)
        assert not problems, (
            "关档提示词里的调用形用了未声明的参数：\n  - " + "\n  - ".join(problems))
        # 反真空：塞一个未声明的键进去 ⇒ 同一条判据必须红
        poisoned = texts["B"] + (
            "\n用 `conductor.void_items(item_ids=[\"t-0001\"], frobnicate=1)` 撤掉。\n")
        got = _param_problems(poisoned, reg, "B")
        assert any("frobnicate" in one for one in got), got
    restore_lean_baseline(monkeypatch)


def test_secretary_prompts_render_and_scan_under_lean_off(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """每秘书的提示词也要渲染并扫（9 类判词 + 形态闸头 + 洗 V 回复头）。"""
    with _lean(monkeypatch, False):
        texts = {f"judge:{kind}": SEC._judge_system(kind) for kind in SEC.JUDGE_VERDICTS}
        texts["proposition_form"] = SEC._proposition_form_system()
        texts["wash_v"] = SEC._wash_v_system()
        assert len(texts) == len(SEC.JUDGE_VERDICTS) + 2
        names = {str(n) for n in _registry_names()}
        groups = {n.split(".")[0] for n in names}
        problems: list[str] = []
        for label, text in texts.items():
            assert text.strip(), label
            for role, name in unknown_actions(text):
                problems.append(f"{label}: 动作 {role}.{name} 不在能力表里")
            for token in sorted(set(PS.TOOL_TOKEN.findall(text))):
                if token.split(".")[0] in groups and token not in names:
                    problems.append(f"{label}: {token} 像工具名但不在册（拼错了）")
        assert not problems, "秘书提示词里点名了不存在的工具/动作：\n  - " + "\n  - ".join(problems)


def test_l_is_hidden_only_by_the_shared_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """e 的反真空：L 的缺席由唯一判定入口决定 —— 把它改成不隐藏，L 必须渲得出来。"""
    with _lean(monkeypatch, False) as (root, reg):
        with pytest.raises(LS.RoleHidden):
            _render("L", root, reg)
        monkeypatch.setattr(LS, "is_hidden", lambda role: False)
        text = _render("L", root, reg)
        assert text.strip(), "把 is_hidden 改成恒 False 之后 L 的提示词仍然是空的"
    restore_lean_baseline(monkeypatch)


def _registry_names() -> list[str]:
    """秘书那一格用的注册表（关档；秘书没有工具面，这里只借"工具名全集"判拼写）。"""
    root = pathlib.Path(tempfile.mkdtemp(prefix="cl2-sec-"))
    st = Store(root)
    st.init()
    return [str(n) for n in build_registry(store=st, workspace_root=str(root)).registry.names()]
