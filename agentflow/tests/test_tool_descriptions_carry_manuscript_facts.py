# -*- coding: utf-8 -*-
"""工具面：`verify.verify_proof` 的只读读数说手稿事实；`verify.run_experiment` 认两类手稿。

## 改前为什么红

- `verify.verify_proof.params.readonly_facts` 的说明仍是「命题现状 / 台账条数」——
  V 现在只对手稿负责（`agent_v.core._manuscript_facts` 给的正是命题正文 / 证明 / 依赖 /
  签块四样），那句说明是模型在 function-calling 面上唯一会读到的一格；
- `verify.run_experiment` 的说明（`summary`）0 处提到 E 的两类手稿，
  而模型要靠摘要决定"这份稿要不要送 V"。

## 判据（存在性 + 反真空）

| # | 对象 | 必须读到 | 反真空 |
|---|---|---|---|
| a | `verify.verify_proof.params.readonly_facts.description` | 命题正文 / 证明 / 依赖 / 签块 | 塞回「台账条数」⇒ 红 |
| b | `verify.run_experiment.summary` | `e-proof` / `e-num` / 普通数值 / 不需 V 签 | 换回改前那句摘要 ⇒ 红 |
| c | 被从 summary 挪走的那句话没丢 | `cross_check` / `inconclusive` 在参数面 | 挖掉 `claim` 的说明 ⇒ 红 |

零模型调用、零网络，临时工作区。
"""
from __future__ import annotations

import pathlib
import tempfile

from agentflow.store import Store
from agentflow.tools import ROLES, build_registry

#: `readonly_facts` 说明必须点到的四样手稿事实。
MANUSCRIPT_FACTS: tuple[str, ...] = ("命题正文", "证明", "依赖", "签块")

#: 两类 E 手稿在 `run_experiment` 摘要里必须点到的记号（含"普通数值不需 V 签"）。
TWO_MANUSCRIPTS: tuple[str, ...] = ("e-proof", "e-num", "普通数值", "不需 V 签")


def _registry():
    ws = pathlib.Path(tempfile.mkdtemp(prefix="p262-toolface-")) / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return build_registry(store=st, workspace_root=ws, roles=tuple(ROLES),
                          strict=True).registry


def _readonly_facts_desc(registry) -> str:
    spec = registry.get("verify.verify_proof")
    assert spec is not None, "工具面里没有 verify.verify_proof"
    return str(((spec.params or {}).get("properties") or {})
               .get("readonly_facts", {}).get("description") or "")


def _run_experiment_summary(registry) -> str:
    spec = registry.get("verify.run_experiment")
    assert spec is not None, "工具面里没有 verify.run_experiment"
    return str(spec.summary or "")


def _readonly_problems(text: str) -> list[str]:
    missing = [x for x in MANUSCRIPT_FACTS if x not in text]
    bad = [f"readonly_facts 说明没有点手稿事实：缺 {missing}"] if missing else []
    if "台账条数" in text or "命题现状" in text:
        bad.append(f"readonly_facts 说明还写着旧口径（命题现状 / 台账条数）：{text}")
    return bad


def _summary_problems(text: str) -> list[str]:
    missing = [x for x in TWO_MANUSCRIPTS if x not in text]
    return [f"run_experiment 摘要没有写清两类手稿：缺 {missing}（{text}）"] if missing else []


def test_a_readonly_facts_names_the_manuscript_facts() -> None:
    """a：只读读数是手稿事实，不是命题台账。"""
    text = _readonly_facts_desc(_registry())
    assert text, "readonly_facts 的说明是空的 ⇒ 模型面上这一格什么都没教"
    assert _readonly_problems(text) == [], "\n".join(_readonly_problems(text))


def test_a_putting_the_old_ledger_wording_back_makes_it_red() -> None:
    """a 反真空：把那句旧说明塞回去 ⇒ 同一个算式必须当场报。"""
    old = "只读读数（命题现状 / 台账条数）"
    hit = _readonly_problems(old)
    assert hit and any("台账条数" in x for x in hit), hit


def test_b_run_experiment_names_both_manuscript_families() -> None:
    """b：摘要里 e-proof（穷举、要 V 签）与 e-num（普通数值、不需 V 签）都在。"""
    text = _run_experiment_summary(_registry())
    assert text, "run_experiment 的摘要是空的"
    assert _summary_problems(text) == [], "\n".join(_summary_problems(text))


def test_b_reverting_to_the_old_summary_makes_it_red() -> None:
    """b 反真空：换回改前那句摘要（只字不提两类手稿）⇒ 红。"""
    old = ("跑工作区内脚本并登记一条 Experiment 行。自报 `evidence_kind='proof'` "
           "降级为 `cross_check`；崩溃记 `inconclusive`。")
    hit = _summary_problems(old)
    assert hit and any("e-proof" in x for x in hit), hit


def test_c_the_moved_sentence_is_still_visible_in_the_param_face() -> None:
    """c：从摘要挪走的那句「降级 / 崩溃」还在参数面（模型仍看得见）。"""
    spec = _registry().get("verify.run_experiment")
    claim = ((spec.params or {}).get("properties") or {}).get("claim") or {}
    desc = str(claim.get("description") or "")
    missing = [x for x in ("cross_check", "inconclusive") if x not in desc]
    assert not missing, (missing, desc)
    # 反真空：把这两个记号挖掉 ⇒ 同一个算式必须看见。
    stripped = desc.replace("cross_check", "").replace("inconclusive", "")
    assert [x for x in ("cross_check", "inconclusive") if x not in stripped] == [
        "cross_check", "inconclusive"]
