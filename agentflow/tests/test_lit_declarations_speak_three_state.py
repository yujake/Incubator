# -*- coding: utf-8 -*-
"""`lit.*` 的声明必须与三态口径同一套话（业主 2026-10-26 Q16；本单 T-a）。

Q16 把「待新增文献列表」收成三态（`pending` 待裁 / `admitted` 入库 / `rejected` 拒收），
两个历史档 `cleared` / `withdrawn` 在写侧不再产出、在读侧一律经 `litstage.fold_legacy`
折成 `rejected` + 受控理由码。提交闸长在 `litstage.admission_plan(require_judged=True)`。

handler 的 docstring 不进模型的视野：`tools/base.py` 的 `to_function_schema` 给的是
`description = summary + "\\n返回：" + returns`。所以 Q16 改在 `_h_lit_*` docstring 里的那些话
模型一个字都看不到 —— 本文件守的正是「模型读到的那一份」（装配后的 `ToolSpec`），不是源码注释。

## 这一份守的四条

| 判据 | 守的是 | 改前红的样子 |
|---|---|---|
| a `test_a_no_declaration_calls_it_five_states` | 声明里没有「五态」，也没有把 `cleared` / `withdrawn` 与三态并列成可选状态；历史档出现时必须写明读成 `rejected`（或写明它不是状态名） | `lit.stage_list` 的 summary 逐字「status 五态（pending/withdrawn/rejected/admitted/cleared）」 |
| b `test_b_admit_all_says_whole_batch_and_refuses_unjudged` | `lit.admit_all` 的 summary 说清「整批提交 / 没判完就拒」，不再说「一键迁移」 | 它的 summary 逐字以「一键迁移」开头，且只说「待审…的行一次性迁进」 |
| c `test_c_the_status_vocabulary_has_exactly_one_home` | 词表只在 `lit.stage_list` 一处出现（那一处指向常量 `litstage.CANDIDATE_DECISIONS`）；别的格再抄一份完整词表 ⇒ 红 | `lit.stage_list` 的 returns 又把 `counts` 的五值抄了一遍；且没有任何声明指向那个常量 |
| d `test_d_negative_control_old_wording_turns_a_b_and_c_red` | 反真空：把任一格改回旧措辞 ⇒ a 或 b 必红；往任一声明塞回五值串 ⇒ c 必红 | —— |

## 口径的三处取舍（写下来，免得后来的人把它改宽）

1. `status` 的 `enum` 是 `list(S.CANDIDATE_STATUSES)` —— 那是「指向常量」的合规形态，本文件
   不收窄它（收窄会改行为：按老名字查历史这条路就断了）。它落在 `lit.stage_list`，也就是
   词表唯一的家。
2. 「完整词表」按五个取值同时出现来判（词形边界匹配：`not_pending` 不算 `pending`）。
   三态里的两个以上出现在别的工具里也算抄词表 —— 那条判据只留一条出口：指向常量名。
3. 历史档被允许出现的两种写法：读成 `rejected`，或明说它不是状态名（返回键 `cleared[]`
   就是后者，它是个读数格）。除此之外的并列就是判据 a 要挡的分家。
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Mapping

import pytest

from agentflow.store import Store
from agentflow.tools import build_for_role
from agentflow.tools.base import ToolSpec

#: 三态（`litstage.CANDIDATE_DECISIONS` 的口径）。
THREE_STATES: tuple[str, ...] = ("pending", "admitted", "rejected")
#: 盘上读得进来、写侧不再产出的两个历史档（`schema.CANDIDATE_STATUSES` 容得下它们）。
LEGACY_STATES: tuple[str, ...] = ("cleared", "withdrawn")
#: 词表真身的常量名（判据 c 允的那一条出口：指向常量，而不是再抄一份）。
HOME_CONST: str = "litstage.CANDIDATE_DECISIONS"
#: 词表唯一的家（工具名）。
HOME_TOOL: str = "lit.stage_list"
#: 历史档出现时必须同时出现的一句（折成 rejected / 明说它不是状态名）。比对前会去掉反引号。
LEGACY_HONEST: tuple[str, ...] = ("读成 rejected", "不是状态名")


# ====================================================================== 声明读法


def _token(text: str, word: str) -> bool:
    """词形边界匹配：`not_pending` 里没有 `pending`（下划线是词内字符）。"""
    return re.search(rf"(?<![A-Za-z0-9_]){word}(?![A-Za-z0-9_])", text) is not None


def _states_in(text: str) -> set[str]:
    return {w for w in THREE_STATES + LEGACY_STATES if _token(text, w)}


def _param_units(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    """把 params 摊成逐格声明串：每个叶子 property 一格（含 `enum` 与 `description`）。

    为什么连 `enum` 一起读：模型看得到 `status` 的取值清单。把 `enum` 排除在判据外，
    「五态」就会从 params 这一格整条溜过去（文案不是声明面的全部，params 也是）。
    """
    out: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, Mapping):
            return
        props = node.get("properties")
        if isinstance(props, Mapping):
            for key, sub in props.items():
                walk(sub, f"{path}.{key}" if path else str(key))
            return
        if "items" in node:
            walk(node["items"], f"{path}[]")
            return
        if path:
            out.append((f"params.{path}",
                        json.dumps(dict(node), ensure_ascii=False, sort_keys=True)))

    walk(params, "")
    return out


def _units(spec: ToolSpec) -> list[tuple[str, str]]:
    """模型读得到的全部声明串（summary / returns / 逐参数格）。"""
    return ([("summary", spec.summary), ("returns", spec.returns or "")]
            + _param_units(dict(spec.params)))


def _plain(text: str) -> str:
    """去掉反引号后再做短语比对（源码里这些词是带反引号的）。"""
    return text.replace("`", "")


# ====================================================================== a 五态 / 历史档


def _five_state_violations(spec: ToolSpec) -> list[str]:
    """判据 a：不许「五态」，不许把历史档与三态并列成可选状态。"""
    bad: list[str] = []
    for where, text in _units(spec):
        if "五态" in text:
            bad.append(f"{spec.name} / {where} 仍写「五态」：{text!r}")
        if "pending/withdrawn/rejected/admitted/cleared" in text:
            bad.append(f"{spec.name} / {where} 仍逐字列着旧五值串：{text!r}")
        legacy = _states_in(text) & set(LEGACY_STATES)
        if legacy and not any(phrase in _plain(text) for phrase in LEGACY_HONEST):
            bad.append(
                f"{spec.name} / {where} 提到了历史档 {sorted(legacy)}，"
                f"却没写明「读成 rejected」（或「不是状态名」）：{text!r}"
            )
    return bad


def test_a_no_declaration_calls_it_five_states(lit_specs: Mapping[str, ToolSpec]) -> None:
    """a. 七个 `lit.*` 声明里没有「五态」，历史档只以「读成 rejected」的形态出现。"""
    bad: list[str] = []
    for name in sorted(lit_specs):
        bad += _five_state_violations(lit_specs[name])
    assert not bad, ("`lit.*` 的声明与三态口径分家了（模型读的就是这些串）：\n"
                     + "\n".join(bad))


# ====================================================================== b admit_all


#: 旧语义的三个抓手：一键迁移 / 只挑待审的行 / 报告两块。
OLD_ADMIT_ALL_PHRASES: tuple[str, ...] = ("一键迁移", "待审且过筛", "两块都要有")


def _admit_all_violations(spec: ToolSpec) -> list[str]:
    """判据 b：`lit.admit_all` 的 summary 说清「整批提交 + 没判完就拒」。"""
    bad: list[str] = []
    summary = spec.summary
    for phrase in OLD_ADMIT_ALL_PHRASES:
        if phrase in summary:
            bad.append(f"{spec.name} 的 summary 仍是旧语义（出现 {phrase!r}）：{summary!r}")
    if "整批" not in summary:
        bad.append(f"{spec.name} 的 summary 没说「整批提交」：{summary!r}")
    if not re.search(r"(还有.{0,4}没判|没判完|全部判完|判完)", summary):
        bad.append(f"{spec.name} 的 summary 没说「没判完就整批拒」：{summary!r}")
    if "待裁" not in summary:
        bad.append(f"{spec.name} 的 summary 没提报告/结算里的「待裁」那一档：{summary!r}")
    return bad


def test_b_admit_all_says_whole_batch_and_refuses_unjudged(
        lit_specs: Mapping[str, ToolSpec]) -> None:
    """b. `lit.admit_all` 不再是「一键迁移」：它是判完之后提交整批，没判完就整批拒。"""
    spec = lit_specs["lit.admit_all"]
    bad = _admit_all_violations(spec)
    assert not bad, "`lit.admit_all` 的声明还是 Q16 之前那句话：\n" + "\n".join(bad)


# ====================================================================== c 词表一处


def _vocab_tokens(text: str) -> set[str]:
    """这一格真正当词表在用的取值：历史档只有在写明「读成 rejected / 不是状态名」之后才不算。"""
    found = _states_in(text) & set(THREE_STATES)
    if any(phrase in _plain(text) for phrase in LEGACY_HONEST):
        return found
    return found | (_states_in(text) & set(LEGACY_STATES))


def _vocab_violations(lit_specs: Mapping[str, ToolSpec]) -> list[str]:
    """判据 c：完整词表只许在 `lit.stage_list`（指向常量名的那一处），别处抄一份就红。"""
    bad: list[str] = []
    home = lit_specs.get(HOME_TOOL)
    if home is None:
        return [f"工具面上没有 {HOME_TOOL} ⇒ 词表没有家"]
    if HOME_CONST not in _plain(home.summary):
        bad.append(f"{HOME_TOOL} 的 summary 没有指向常量 {HOME_CONST!r}（词表真身无处可指）")
    for word in THREE_STATES:
        if not _token(home.summary, word):
            bad.append(f"{HOME_TOOL} 的 summary 没写全三态（缺 {word!r}）")
    for name in sorted(lit_specs):
        if name == HOME_TOOL:
            continue
        for where, text in _units(lit_specs[name]):
            found = _vocab_tokens(text)
            if len(found) >= 2:
                bad.append(
                    f"{name} / {where} 又抄了一遍完整词表（{sorted(found)}）—— "
                    f"词表只留在 {HOME_TOOL}，这里请换成一个状态或指向 {HOME_CONST}"
                )
    return bad


def test_c_the_status_vocabulary_has_exactly_one_home(
        lit_specs: Mapping[str, ToolSpec]) -> None:
    """c. 词表只有一处真身：`lit.stage_list` 指向 `litstage.CANDIDATE_DECISIONS`。"""
    bad = _vocab_violations(lit_specs)
    assert not bad, "状态词表不止一处（抄了必然再次分家）：\n" + "\n".join(bad)


# ====================================================================== d 反真空


#: 改前逐字（2026-10-26 之前 `search_tools.py` 里的原文）：负控拿它当「旧措辞」。
OLD_STAGE_LIST_SUMMARY: str = (
    "查待新增列表：默认**只看当前委托**（列表按委托重置）；status 五态"
    "（pending/withdrawn/rejected/admitted/cleared），**撤掉的空槽位照样在列表里并带理由**。"
)
OLD_ADMIT_ALL_SUMMARY: str = (
    "**一键迁移**：本委托待审且过筛（重叠检查）的行一次性迁进 literature（≤10 条），"
    "然后结算清空本委托的列表（全终态、不物理删），并写委托报告 reports/lit-<request_id>.md"
    "（已入库 + 未入库含受控理由，两块都要有）。"
)
#: 往任一声明里塞回的五值串（判据 c 的反真空）。
FIVE_VALUE_COPY: str = "（status 五态：pending/withdrawn/rejected/admitted/cleared）"


def test_d_negative_control_old_wording_turns_a_b_and_c_red(
        lit_specs: Mapping[str, ToolSpec]) -> None:
    """d. 反真空：旧措辞喂回同一套判据 ⇒ a / b / c 各自必红。

    打的是本文件真用的那几个检查函数（`_five_state_violations` / `_admit_all_violations` /
    `_vocab_violations`），不是另写一份「会红的假判据」。所以它们绿，说明树上的声明真的干净；
    它们红，说明判据真的读到了那一格。
    """
    # ---- a：把 stage_list 的 summary 换回「五态」
    old = replace(lit_specs[HOME_TOOL], summary=OLD_STAGE_LIST_SUMMARY)
    a_bad = _five_state_violations(old)
    assert any("五态" in item for item in a_bad), (
        "把 stage_list 改回「五态」之后判据 a 没红 ⇒ a 是橡皮图章：" + repr(a_bad)
    )
    # ---- b：把 admit_all 的 summary 换回「一键迁移」
    old_all = replace(lit_specs["lit.admit_all"], summary=OLD_ADMIT_ALL_SUMMARY)
    b_bad = _admit_all_violations(old_all)
    assert any("一键迁移" in item for item in b_bad), (
        "把 admit_all 改回「一键迁移」之后判据 b 没红 ⇒ b 是橡皮图章：" + repr(b_bad)
    )
    # ---- c：往另一个工具塞回完整五值串
    polluted = dict(lit_specs)
    polluted["lit.admit"] = replace(lit_specs["lit.admit"],
                                    summary=FIVE_VALUE_COPY + lit_specs["lit.admit"].summary)
    c_bad = _vocab_violations(polluted)
    assert c_bad, "往 lit.admit 里塞回五值串之后判据 c 没红 ⇒ c 是橡皮图章"
    # ---- 而且这三条负控不许误伤真树：同一批函数在真实声明上必须是干净的
    assert not _five_state_violations(lit_specs[HOME_TOOL])
    assert not _vocab_violations(lit_specs)


# ====================================================================== 夹具


@pytest.fixture(scope="module")
def lit_specs(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, ToolSpec]:
    """装配 A 的工具面，取出 `lit.*` 七件的声明（真注册表，不是模块里的 `__tool_spec__`）。"""
    root = tmp_path_factory.mktemp("lit-declarations") / "ws"
    root.mkdir()
    store = Store(root)
    store.init()
    registry = build_for_role("A", store=store, workspace_root=store.root).registry
    return {spec.name: spec for spec in registry.for_role("A")
            if spec.name.startswith("lit.")}
