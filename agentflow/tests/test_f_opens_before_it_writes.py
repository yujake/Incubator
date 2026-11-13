# -*- coding: utf-8 -*-
"""F 的开稿次序（2026-11-13 业主裁定 · 统一四步的 F 接线）。

业主口径（逐字）：

> 「统一 B、E、F 注册稿和写稿的流程：写命题 → 命题形式过审 → 拿稿号 → 写稿
> （稿允许慢慢 edit，不必一次成稿）」

## 这个文件钉什么（F 这一族）

| 编号 | 判据 | 用例 |
|---|---|---|
| a | 命题形状不合格 ⇒ 受控拒、号源一个字节都没动、盘上零字节（「先发号后过闸」改掉） | `test_a_*` |
| b | 形状合格 ⇒ 写正文那一刻盘上已经有骨架（命题逐字在、`## 证明` 还空） | `test_b_*` |
| c | 第一次登记只补头部元信息、不改正文；第二轮重写证明才换 `## 证明` | `test_c_*` |
| d | 拒信分两档：盘上没有稿 ⇒ `manuscript_path=""`；有稿未登记 ⇒ 如实指它 + `draft=True` | `test_d_*` |

## 为什么 b 要看「写正文那一刻」

改前：闸 → 发号 → `proof_manuscript` 一次写整份（命题 + 证明 + 依赖）。所以「骨架」
在盘上存在的唯一证据是"正文写口被调用时它已经在"。把 `proof_manuscript` 包一层探针
读盘，这一格就能把次序钉住；反过来，如果谁把 `_open_manuscript` 挪到正文之后，b 会红
（那一刻盘上什么都没有）。
"""
from __future__ import annotations

import pathlib

from agentflow import manuscriptids as MID
from agentflow import manuscriptopen as MO
from agentflow import proofregistry as PR
from agentflow.agent_f import AgentF
from agentflow.store import Store

STMT = "设 f 在 [0,1] 上连续；则 f 在 [0,1] 上一致连续。"
NOTE = "按 V u-000005 的唯一缺陷修订第 7 步：其余八步一字不动，重送 V。"
TS = "2026-11-13T10:00:00+08:00"


class _Sec:
    """F 的秘书替身：形态判定 + 依赖面洗稿两问（别的路径不碰）。"""

    role = "F"

    def __init__(self, *, well_formed: bool = True) -> None:
        self.well_formed = bool(well_formed)
        self.form_calls = 0
        self.wash_calls = 0

    def judge_proposition_form(self, **_kw):
        self.form_calls += 1
        return {"checked": True, "well_formed": self.well_formed,
                "conditions": "设 f 连续" if self.well_formed else "",
                "conclusion": "则 f 一致连续" if self.well_formed else "",
                "problems": [] if self.well_formed
                else ["结论不是可判真假的数学断言，而是流程要求"],
                "decision": "夹具", "refused": "" if self.well_formed
                else "proposition_form_refused", "reason": "夹具", "cached": False}

    def wash_dependency_face(self, text: str, **_kw):
        self.wash_calls += 1
        return {"checked": True, "text": str(text), "actor": self.role,
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _agent(st: Store, sec: _Sec) -> AgentF:
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0001"})
    f.f_secretary = sec
    return f


def _plan() -> dict:
    sg = {"sid": "S4", "text": STMT, "owner": "F", "status": "in_progress",
          "testable": "", "evidence_ids": [], "experiment_ids": [],
          "blocked_reason": "", "attempts": 0, "negation_kind": None}
    return {"plan_id": "0001", "problem": "夹具", "problem_key": "PK-OPEN",
            "rounds": 0, "history": [], "status": "open", "depth": 0,
            "best_partial": "", "created_at": TS, "updated_at": TS,
            "budget": {"max_rounds": 4, "max_parallel_subgoals": 2,
                       "max_persist_attempts": 2, "max_depth": 1},
            "subgoals": [sg]}


def _product(proposition: str, *, tag: str = "v1", manuscript_id: str = "") -> dict:
    out = {"product": "proof", "proposition": proposition, "strategy": "按定义",
           "why_strategy": "直接证", "self_assessment": "这一条做完了",
           "steps": [{"n": 1, "text": f"取 δ=ε 逐点验证（{tag}）",
                      "cites": [], "assumption": True},
                     {"n": 2, "text": f"三角不等式收口（{tag}）",
                      "cites": [], "assumption": False}]}
    if manuscript_id:
        out["manuscript_id"] = manuscript_id
    return out


def _round(f: AgentF, product: dict) -> dict:
    plan = _plan()
    return f._apply_round(product, plan["subgoals"][0], plan=plan, owner="F")


def _files(st: Store) -> list[pathlib.Path]:
    base = pathlib.Path(st.root) / "reports"
    return sorted(base.glob("f-proof-*.md")) if base.is_dir() else []


def _section(text: str, name: str) -> str:
    _head, sections = PR.split_sections(text)
    return next((body for got, body in sections if got == name), "")


# ---------------------------------------------------------------- a：闸在前
def test_a_the_gate_runs_before_the_id_is_issued(tmp_path: pathlib.Path) -> None:
    """形状不合格 ⇒ 拒、零字节、号源一个字节都不动（改前：先发号后过闸，号被吃掉）。"""
    st = _ws(tmp_path)
    sec = _Sec(well_formed=False)
    out = _round(_agent(st, sec), _product(NOTE))

    assert out.get("outcome") == "no_change", out
    refusal = dict(out.get("refusal") or {})
    assert refusal.get("kind") == "proposition_form_refused", out
    assert out.get("manuscript_path") == "" and out.get("manuscript") == "", out
    assert _files(st) == [], "闸判不过 ⇒ 盘上零字节"
    assert MID.peek_manuscript_counter(st.root) == 0, "闸判不过 ⇒ 号源一个字节都不动"
    assert len(list(st.rows("statements"))) == 0
    assert sec.form_calls == 1, "闸只问一次"


# ---------------------------------------------------------------- b：骨架在正文之前
def test_b_the_skeleton_is_on_disk_before_the_proof_is_written(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """写正文那一刻：盘上已经有骨架（`## 命题` 逐字在、`## 证明` 还空）。"""
    st = _ws(tmp_path)
    seen: dict[str, object] = {}

    real = AgentF.proof_manuscript

    def _spy(self, product, **kw):  # noqa: ANN001, ANN003 - 探针
        base = pathlib.Path(self.store.root) / "reports"
        files = sorted(base.glob("f-proof-*.md")) if base.is_dir() else []
        seen["names"] = [p.name for p in files]
        seen["text"] = files[0].read_text(encoding="utf-8") if files else ""
        return real(self, product, **kw)

    monkeypatch.setattr(AgentF, "proof_manuscript", _spy)
    out = _round(_agent(st, _Sec()), _product(STMT, tag="v1"))

    assert seen["names"] == ["f-proof-000000.md"], (
        "写正文之前必须先有骨架（开稿口在正文写口之前）", seen["names"])
    skeleton = str(seen["text"])
    assert _section(skeleton, "命题").strip() == STMT, skeleton
    assert _section(skeleton, "证明").strip() == "", "那一刻 `## 证明` 还是空的"
    # 这一轮写完之后：正文进去了、登记条目也在（登记只加头元信息）
    assert out.get("outcome") == "progress", out
    rel = str(out.get("manuscript_path") or "")
    assert rel == "reports/f-proof-000000.md", out
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    assert "取 δ=ε 逐点验证（v1）" in _section(text, "证明")
    assert PR.parse_entry(text).get("checked") is True, "第一次登记要落条目"
    assert out.get("proof_mode") == "registered", out


# ---------------------------------------------------------------- c：登记不重渲正文
def test_c_registration_adds_only_head_metadata_then_rewrite_replaces_the_proof(
        tmp_path: pathlib.Path) -> None:
    """第一轮登记不重渲正文；第二轮（同一稿号）才是重写 `## 证明` 那一节。"""
    st = _ws(tmp_path)
    f = _agent(st, _Sec())
    first = _round(f, _product(STMT, tag="v1"))
    rel = str(first.get("manuscript_path") or "")
    assert rel and first.get("proof_mode") == "registered", first
    text1 = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    prop1 = _section(text1, "命题")
    proof1 = _section(text1, "证明")
    assert prop1.strip() == STMT
    assert "v1" in proof1

    # 第二轮：同一稿号（history 里记着那一份）⇒ 只换证明，不换号、不重新过闸
    plan = _plan()
    plan["history"] = [{"sid": "S4", "manuscript_path": rel}]
    second = f._apply_round(_product(STMT, tag="v2"), plan["subgoals"][0],
                            plan=plan, owner="F")
    assert second.get("manuscript_id") == first.get("manuscript_id"), (
        "改证明不换稿号", (first.get("manuscript_id"), second.get("manuscript_id")))
    assert second.get("proof_mode") == "rewritten", second
    text2 = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    assert _section(text2, "命题") == prop1, "重写证明不许动 `## 命题` 一个字节"
    assert "v2" in _section(text2, "证明"), "重写这一档换的是 `## 证明`"
    assert len(_files(st)) == 1, "一个稿号一份文件"


# ---------------------------------------------------------------- d：拒信两档
def test_d_a_leftover_draft_is_named_in_the_refusal(tmp_path: pathlib.Path) -> None:
    """盘上有一份未登记的骨架 ⇒ 拒信如实指它（`draft=True`），不说「一个字节都没写」。"""
    st = _ws(tmp_path)
    root = pathlib.Path(st.root)
    draft = MO.open_manuscript(root, role="F", family="f-proof", proposition=STMT,
                              judge=lambda **_kw: {"checked": True, "well_formed": True,
                                                   "conditions": "设 f 连续",
                                                   "conclusion": "则 f 一致连续",
                                                   "problems": [], "decision": "夹具",
                                                   "refused": "", "reason": "夹具",
                                                   "cached": False})
    assert draft["ok"] and (root / draft["path"]).is_file()
    out = _round(_agent(st, _Sec(well_formed=False)),
                 _product(NOTE, manuscript_id=draft["manuscript_id"]))
    refusal = dict(out.get("refusal") or {})
    assert refusal.get("kind") == "proposition_form_refused", out
    assert out.get("manuscript_path") == draft["path"], out
    assert out.get("draft") is True and out.get("manuscript_source") == "draft", out
    assert refusal.get("on_disk") is True, out
    assert "骨架还在" in str(out.get("detail") or ""), out.get("detail")
    # 骨架本身一个字节都没被这一轮动过（命题仍是原来那段）
    text = (root / draft["path"]).read_text(encoding="utf-8")
    assert _section(text, "命题").strip() == STMT
