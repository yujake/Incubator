# -*- coding: utf-8 -*-
"""ROLECLEAN-2 判据：C / E / F / G 四岗的旧路残留与废案死代码。

## 这一份守的是什么

业主 2026-11-20 的指令：「派多人查修各角色存在的旧路（或废案死代码）残留问题，
并在修好后做提示词对齐」。本文件是 C / E / F / G 四岗能机械判的那几格
（残下来的语义项与"为什么不修"逐条写在 `agentflow/temp/roleclean2/` 的报告里）：

| # | 守的那件事 | 改前为什么红 |
|---|---|---|
| ① | F 的签通道词表里没有永不产出的取值 | `vsign.py` 还留着三条路时代的 `CHANNEL_MANUSCRIPT` / `CHANNEL_LEDGER`，它们零引用、也从不被赋给 `out["channel"]` |
| ② | F 的「稿身份前缀」只有一个活定义 | `pending.py` 还留着一份零引用的 `MANUSCRIPT_OUTPUT_PREFIX = "mss:"`，而真正的记号写入读 `agent_f/submission.py` 的同名常量 |
| ③ | E 的收工两族从角色-族表现读，不在本模块另写一份 | `agent_e/autosubmit.py` 把 `("e-proof", "e-num")` 又写了一遍（`manuscriptopen.ROLE_FAMILIES["E"]` 已经是唯一真身） |
| ④ | C 的写集说明与写集本身一致 | `agent_c/core.py` 的 `_submit_gap_requests` 还写着「在登记落地之前，静态写集与这里的实际行为是不一致的」，而 `specs/c.py` 的写集早已含 `search_requests` |
| ⑤ | F 的 `_proof_outlet` 说明不再声称「交给 B 的登记正路」 | 实现只落 F 自己的手稿登记（`proofregistry.register_or_rewrite`），`statements` 由 B 在 V 签之后收录；同文件的 `_hand_proof` 已经写明「不再交给 B 登记」 |
| ⑥ | F 的写集注释不再写着「F 把命题正文与证明全文交给 B」 | `F -> B` 直连边 2026-11-07 已裁掉（F 只向上走 D）；同一份 spec 的 policy 已改成「交稿向上走 D / 经 D 携带给 B / B 读稿登记」 |

## 形态：纯检查函数 + 正控 + 负控

每一条的检查函数都吃一份语料（现读的模块属性 / 源码文本）并吐问题清单；
正控断言今天的树干净，负控把改前那一份喂进同一个函数、断言它必红 ——
只断言"今天没有那句话"无法区分"真修了"与"那句话被删光了"。
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from agentflow import manuscriptopen as MO
from agentflow.agent_e import autosubmit as EAuto
from agentflow.agent_f import vsign as FVS

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "agentflow"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return "".join(str(text).split())


# ============================================================ ① F 的签通道词表
def dead_channel_problems(constants: set[str], produced: set[str]) -> list[str]:
    """词表里登记了、而代码从不产出的签通道（空列表 = 没有死取值）。"""
    retired = sorted(constants - produced)
    if not retired:
        return []
    return [f"[①] F 的签通道词表里有不产出的取值：{retired} —— "
            "`vsign.delivery_reading` 只会把 `out['channel']` 赋成它真读到的来源，"
            "留着旧的三条路取值会让读的人以为还有那两条通道"]


def produced_channels(source: str) -> set[str]:
    """从源码里现算「哪些 `CHANNEL_*` 真的会被赋给 `out['channel']`」。"""
    tree = ast.parse(source)
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Subscript)
                   and isinstance(getattr(t, "slice", None), ast.Constant)
                   and t.slice.value == "channel" for t in node.targets):
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Name) and sub.id.startswith("CHANNEL_"):
                out.add(sub.id)
    return out


def declared_channel_constants(source: str) -> set[str]:
    tree = ast.parse(source)
    return {t.id for node in tree.body
            if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Name) and t.id.startswith("CHANNEL_")}


def test_1_the_sign_channel_vocabulary_has_no_dead_value() -> None:
    source = _read("agent_f/vsign.py")
    problems = dead_channel_problems(declared_channel_constants(source),
                                     produced_channels(source))
    assert not problems, "\n".join(problems)
    # 反真空：这一格真的扫到了东西（扫不到时"没有死取值"是假绿）
    assert declared_channel_constants(source) >= {"CHANNEL_ON_SHELF", "CHANNEL_PENDING"}
    assert produced_channels(source) >= {"CHANNEL_ON_SHELF", "CHANNEL_PENDING"}


def test_1_negative_control_the_retired_channels_are_caught() -> None:
    """负控：把改前那两个取值塞回词表 ⇒ 同一个检查函数必须点红。"""
    source = _read("agent_f/vsign.py")
    dead = {"CHANNEL_MANUSCRIPT", "CHANNEL_LEDGER"}
    problems = dead_channel_problems(declared_channel_constants(source) | dead,
                                     produced_channels(source))
    assert problems and all(any(d in p for d in dead) for p in problems), problems


# ============================================================ ② F 的稿身份前缀
def duplicate_prefix_problems(constants: dict[str, str], *, live: str) -> list[str]:
    """登记成 `mss:` 的模块级常量：只要有零引用的那一份，就是第二份死真值。"""
    out: list[str] = []
    for name, value in sorted(constants.items()):
        if value == "mss:" and name != live:
            out.append(f"[②] `{name}` 也写着 {value!r}，而活的那一份是 `{live}` ⇒ "
                       "第三份字面量；删掉零引用的那一份")
    return out


def test_2_the_manuscript_prefix_has_no_dead_third_copy() -> None:
    pending = _read("agent_f/pending.py")
    tree = ast.parse(pending)
    constants = {
        t.id: node.value.value
        for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Name)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }
    assert "MANUSCRIPT_OUTPUT_PREFIX" not in constants, (
        "[②] `agent_f/pending.py` 仍有 `MANUSCRIPT_OUTPUT_PREFIX` —— 它零引用，"
        "而 `agent_f/submission.py::SUBMISSION_PREFIX` 才是写记号那一侧的真身")
    live = __import__("agentflow.agent_f.submission", fromlist=["SUBMISSION_PREFIX"])
    assert live.SUBMISSION_PREFIX == "mss:"
    assert duplicate_prefix_problems(
        {"SUBMISSION_PREFIX": live.SUBMISSION_PREFIX}, live="SUBMISSION_PREFIX") == []


def test_2_negative_control_a_dead_third_copy_is_caught() -> None:
    problems = duplicate_prefix_problems(
        {"SUBMISSION_PREFIX": "mss:", "MANUSCRIPT_OUTPUT_PREFIX": "mss:"},
        live="SUBMISSION_PREFIX")
    assert problems and "MANUSCRIPT_OUTPUT_PREFIX" in problems[0], problems


# ============================================================ ③ E 的两族现读
def second_copy_problems(source: str, families: tuple[str, ...]) -> list[str]:
    """源码里把 `families` 逐字写成元组字面量的地方（空列表 = 只有角色-族表那一份）。"""
    tree = ast.parse(source)
    haystack = {str(f) for f in families}
    out: list[str] = []
    for node in tree.body:
        value = getattr(node, "value", None)
        if not isinstance(value, (ast.Tuple, ast.List)):
            continue
        items = {e.value for e in value.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if items == haystack:
            targets = [t.id for t in getattr(node, "targets", ())
                       if isinstance(t, ast.Name)]
            out.append(f"[③] 又写了一份族表字面量 {sorted(items)}（{targets}）—— "
                       "`manuscriptopen.ROLE_FAMILIES` 是唯一真身，现读它")
    return out


def test_3_e_autosubmit_reads_the_families_from_the_role_table() -> None:
    assert EAuto.FAMILIES_E == MO.families_of("E")
    source = _read("agent_e/autosubmit.py")
    assert not second_copy_problems(source, MO.families_of("E")), (
        "\n".join(second_copy_problems(source, MO.families_of("E"))))


def test_3_negative_control_a_literal_second_copy_is_caught() -> None:
    fake = 'FAMILIES_X = ("e-proof", "e-num")\n'
    problems = second_copy_problems(fake, MO.families_of("E"))
    assert problems and "FAMILIES_X" in problems[0], problems


# ============================================================ ④ C 的写集说明
_C_STALE = "在登记落地之前"


def c_write_set_comment_problems(source: str, write_set: set[str]) -> list[str]:
    out: list[str] = []
    if _C_STALE in source:
        out.append(f"[④] C 的写集说明仍写着「{_C_STALE}」—— 静态写集与写路径已经一致"
                   "（`search_requests` 就在写集里），这句话是旧状态")
    if "search_requests" not in write_set:
        out.append("[④] `specs/c.py` 的写集里没有 `search_requests` ⇒ 说明那一半"
                   "（受控例外）没有被登记，先补写集再改文案")
    return out


def test_4_c_does_not_claim_its_write_set_is_unregistered() -> None:
    from agentflow.specs import c as SC

    problems = c_write_set_comment_problems(_read("agent_c/core.py"), set(SC.SPEC.write_set))
    assert not problems, "\n".join(problems)


def test_4_negative_control_the_old_sentence_is_caught() -> None:
    problems = c_write_set_comment_problems(
        "在登记落地之前，静态写集与这里的实际行为是不一致的", {"search_requests"})
    assert problems and _C_STALE in problems[0], problems


# ============================================================ ⑤ F 的 outlet 说明
_OUTLET_STALE = "交给 B 的登记正路"


def proof_outlet_doc_problems(source: str) -> list[str]:
    """`_proof_outlet` 的 docstring 不许再把这条写口说成"交给 B 登记"。"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_proof_outlet":
            doc = ast.get_docstring(node) or ""
            if _OUTLET_STALE in doc:
                return [f"[⑤] `_proof_outlet` 的说明仍写着「{_OUTLET_STALE}」—— 它只落 F "
                        "自己的手稿登记（`proofregistry`），`statements` 由 B 在 V 签之后收录"]
            return []
    return ["[⑤] 扫不到 `_proof_outlet` ⇒ 这一条判据失效（不是通过）"]


def test_5_f_proof_outlet_does_not_claim_it_hands_to_b() -> None:
    problems = proof_outlet_doc_problems(_read("agent_f/core.py"))
    assert not problems, "\n".join(problems)


def test_5_negative_control_the_old_outlet_doc_is_caught() -> None:
    fake = ('def _proof_outlet(self):\n'
            '    """把这一轮的 proof 交给 B 的登记正路（P3-6 的第一半）。"""\n')
    problems = proof_outlet_doc_problems(fake)
    assert problems and _OUTLET_STALE in problems[0], problems


# ============================================================ ⑥ F 的写集注释
_SPEC_F_STALE = "F 把命题正文与证明全文交给 B"


def spec_f_comment_problems(source: str) -> list[str]:
    out: list[str] = []
    if _SPEC_F_STALE in source:
        out.append(f"[⑥] `specs/f.py` 仍写着「{_SPEC_F_STALE}」—— 2026-11-07 裁掉 `F -> B` "
                   "直连边之后，F 只向上走 D（D 携带给 B、B 读稿登记）")
    if "交稿向上走 D" not in source:
        out.append("[⑥] `specs/f.py` 里读不到「交稿向上走 D」⇒ 新路那一半不在，"
                   "改旧注释之前先确认 policy 还写着现行链路")
    return out


def test_6_f_spec_comment_matches_the_handoff_chain() -> None:
    problems = spec_f_comment_problems(_read("specs/f.py"))
    assert not problems, "\n".join(problems)


def test_6_negative_control_the_direct_to_b_sentence_is_caught() -> None:
    problems = spec_f_comment_problems(
        "交稿向上走 D；" + _SPEC_F_STALE + "，由 B 登记。")
    assert problems and _SPEC_F_STALE in problems[0], problems


# ============================================================ 反真空：导入面还在
def test_zz_the_live_surfaces_are_importable() -> None:
    """这一份判据扫的是活模块；模块搬走时上面几条会变成"扫不到"而不是"干净"。"""
    from agentflow.agent_c import AgentC  # noqa: F401
    from agentflow.agent_e import AgentE  # noqa: F401
    from agentflow.agent_f import AgentF  # noqa: F401
    from agentflow.agent_g import AgentG  # noqa: F401
    from agentflow.specs import c as _c, e as _e, f as _f, g as _g  # noqa: F401

    assert re.search(r"\bCHANNEL_", _read("agent_f/vsign.py"))
