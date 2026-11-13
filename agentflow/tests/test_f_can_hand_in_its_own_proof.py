# -*- coding: utf-8 -*-
"""判据：F 可以把写好的证明交进来（`attack.step(plan_id, product=…)`），框架替它落稿。

## 真机第三轮的通道断（2026-11-11，逐字证据）

    F 调了 5 次 `attack.step`：0 次 proof，全部 reduction（S1 → s1/s2/s3 → s1…），
    计划落 stalled。
    F 的 why 逐字：「探一次 attack.step 的完整参数表：证明正文该怎样交给它才能落成手稿」
                「找 F 落稿/送审那一份」「判断证明正文该写进哪一格」
    它的收工话：「数学内容写出来了，但没有拿到框架手稿，也没有 V 签」
    盘上：statements 0 / reports 4（3 份 attack 台账 + 1 份 21KB 手写草稿）/
         vsigns 0；那份草稿的头自己写着「本文件…不是框架手稿」。

根因：`attack.step` 的 schema 只有 `plan_id` 一格（`additionalProperties=False`）
⇒ F 没有"把证明正文交进来"的入口；那一轮的产物 kind 由框架内部的推理缝决定。

## 这一份钉什么

| # | 判据 | 读数 |
|---|---|---|
| a | 正控：`product={kind:"proof", steps:[…]}` ⇒ 过闸、落 `reports/f-proof-<稿号>.md`、三节齐、`## 依赖` 由框架按 `cites` 渲染、回 `manuscript_path` / `manuscript_id` | 稿在盘上、依赖段有一行、稿号是六位 |
| b | 反向①：`cites` 写了不可引的号 ⇒ 受控拒，逐条点名第几步 | 拒信里有 `第 2 步` 与那个号；盘上没有新稿 |
| c | 反向②：`kind=proof` 但某一步是空话（「易证 / 显然」）⇒ 受控拒 | 拒信里有 `steps[2]` / 「易证」/ 两条合法出口；盘上没有新稿 |
| d | 反向③：不给 `product` ⇒ 与今天逐字一致（老路读数不动） | 缺缝那一支的读数原样；新入口一次都没被走 |
| e | 反真空：把"用 F 交的那份"改回"永远用内层缝" ⇒ a 红 | 同一份 product 交进去不再落稿 |

口径边界：这一份只证明"入口在、且过既有闸"；它不碰 `PROOF_EXIT_CRITERIA`
（那是另一件事），也不放宽任何一条既有判据。零模型调用、零真机。
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from conftest import seed_statement_row                 # noqa: E402
from agentflow import capabilities as CAP              # noqa: E402
from agentflow import llmseam                          # noqa: E402
from agentflow.agent_f import AgentF                   # noqa: E402
from agentflow.store import Store                      # noqa: E402

PROBLEM = "证明：若 f_n→f μ-a.e. 且被可积 g 控制，则 ∫f_n dμ → ∫f dμ。"
SUBGOAL = "控制项 2g 可积，且 |f_n-f| ≤ 2g 在 X 上处处成立。"
TESTABLE = "手稿的 `## 证明` 里逐步给出依据（`cites` 或 `assumption: true`）。"
BUDGET = {"max_rounds": 6, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _f(st: Store) -> AgentF:
    return AgentF(st, config={"workspace_root": str(st.root)})


def _plan(f: AgentF, *, key: str = "pk-hand-in") -> str:
    made = f.create_plan(
        PROBLEM, key,
        subgoals=[{"sid": "S1", "text": SUBGOAL, "owner": "F", "testable": TESTABLE}],
        budget=dict(BUDGET))
    assert made.get("created") is True, made
    return str(made["plan_id"])


def _gate_ok(monkeypatch) -> None:
    """命题形态闸打桩成"判过、合格"（它不是这一份要测的那道闸）。

    真实的闸要一次秘书模型调用；而这一份测的是"入口 + 产物校验 + 落稿"，
    所以按 `tests/test_f_does_not_work_for_a_statement_number.py` 的同一手法，
    只把登记前的那一问换成一个确定的读数，其余全部走真实现。
    """
    def fake_gate(self, *, full, kind, body, label, task_id=""):  # noqa: ANN001, ARG001
        return {"checked": True, "well_formed": True, "submittable": True,
                "conditions": "夹具：设…", "conclusion": "夹具：则…",
                "problems": [], "decision": "夹具：形态合规",
                "refused": "", "reason": "夹具：形态合规"}

    monkeypatch.setattr(AgentF, "_proposition_form_gate", fake_gate)


def _no_seam(monkeypatch) -> None:
    """把 F 的推理缝钉成 None（老路那一支必须落在"缺缝"，而不是去打一个真模型）。"""
    monkeypatch.setitem(llmseam._ROLE_SEAMS, "F", None)


def _citable_statement(st: Store) -> dict:
    """铺一条够格（`pre_theorem`）的在册命题，给证据段当依赖来源。

    为什么必须够格：依赖面的洗稿（`depsection.wash_dependency_section`）读的是
    等级门槛 —— 一条 conjecture 级的行会让这一轮被打回重写（那是另一条判据），
    于是这一份就测不到"落稿成功"的读数了。`proof=true` + `reviewed=true`
    就是 `pre_theorem` 的那两格（`evidencebits.derive_grade`）。
    """
    return seed_statement_row(
        st, statement_full="引理：被可积函数 g 控制的可测函数列，控制项 2g 可积。",
        statement_text="2g 可积", kind="lemma", label="前提A",
        bits={
            "proof": True,
            "reviewed": True,
            "evidence": {
                # 五元位的两位真值都要带凭据（`evidencebits.bit_problems`）：
                # proof ⇒ 逐步论证的正文；reviewed ⇒ V 的三态结论。
                "proof_process": "夹具：第 1 步设 g 可积；第 2 步由控制函数得 |f_n-f| ≤ 2g。",
                "reviewed_by": {"verdict": "成立", "verification_id": "v-000001"},
            },
        })


def _proof_product(stmt_id: str) -> dict:
    return {
        "kind": "proof",
        "proposition": "设 g ≥ 0 可积、|f_n| ≤ g；则 ∫|f_n − f| → 0。",
        "label": "控制收敛（Fatou 路线）的一段",
        "steps": [
            {"text": "设 g ≥ 0 可积、|f_n| ≤ g（本步是前提）", "assumption": True},
            {"text": "由控制函数得 |f_n-f| ≤ 2g，且 2g 可积",
             "cites": [f"stmt:{stmt_id}"]},
            {"text": "对 2g-|f_n-f| 用 Fatou 引理得 limsup ∫|f_n-f| ≤ 0",
             "cites": [f"stmt:{stmt_id}"]},
        ],
    }


def _reports(st: Store) -> list[pathlib.Path]:
    root = pathlib.Path(st.root) / "reports"
    return sorted(root.glob("f-proof-*.md")) if root.is_dir() else []


# ================================================================== 参数面

def test_the_two_layers_advertise_the_same_product_shape(tmp_path: pathlib.Path) -> None:
    """动作表与工具 schema 是同一个形状（两处各写一份就会漂）。

    这一条是"入口存在"的机器读数：F 的题面读 `specs/f.py` 的动作表，工具层读
    `attack_tools` 的 schema —— 只在一处加 `product`，另一处就看不见它。
    """
    action = next(a for a in CAP.actions_for("F") if a.action == "step")
    action_product = (action.params.get("properties") or {}).get("product")
    assert action_product is not None, sorted((action.params.get("properties") or {}))
    tool = _f(_ws(tmp_path))
    tool_product = tool.tools.get("attack.step").params["properties"].get("product")
    assert action_product == tool_product
    assert action_product["additionalProperties"] is False
    assert action_product["required"] == ["kind"]
    assert action_product["properties"]["kind"]["enum"] == ["proof", "reduction"]
    steps = action_product["properties"]["steps"]
    assert steps["items"]["additionalProperties"] is False
    assert "cites" in steps["items"]["properties"]


# ================================================================== a 正控

def test_a_f_can_hand_in_a_proof_and_the_framework_lands_the_manuscript(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """a：交进来的证明过既有闸 ⇒ 落 `reports/f-proof-<稿号>.md`，三节齐、依赖段由框架渲染。

    这条读数就是真机缺的那一格：`manuscript_path` / `manuscript_id` 回得出来，
    稿在盘上、`## 依赖` 里有一行按 `cites` 渲染出来的依赖。
    """
    _gate_ok(monkeypatch)
    st = _ws(tmp_path)
    f = _f(st)
    row = _citable_statement(st)
    sid = str(row["stmt_id"])
    plan_id = _plan(f)

    res = f.tools.call("attack.step", plan_id=plan_id,
                       product=_proof_product(sid))
    assert res.ok, (res.meta.get("kind"), res.error)
    data = dict(res.data or {})
    assert data.get("action") == "proof", data
    assert data.get("outcome") == "progress", data

    mid = str(data.get("manuscript_id") or "")
    rel = str(data.get("manuscript_path") or "")
    assert re.fullmatch(r"[0-9]{6}", mid), (mid, data)
    assert rel == f"reports/f-proof-{mid}.md", (rel, data)
    path = pathlib.Path(st.root) / rel
    assert path.is_file(), f"稿没落盘：{rel}"

    text = path.read_text(encoding="utf-8")
    # 三节齐（缺一节就不是框架手稿；真机那份 21KB 草稿正是三节都没有）。
    assert "## 命题" in text and "## 证明" in text and "## 依赖" in text, text[:400]
    # `## 依赖` 由框架按 `cites` 渲染：表头 + 一条数据行，F 一个字都不用抄。
    # 2026-11-12 对齐：产出侧不再标注路径（「路径在产出侧也不标注了，这些都是 B 秘书的活」）
    # ⇒ 表头只有三列；路径号由 B 的秘书在收录时分配，不写进稿子。
    assert ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |") in text, text
    assert "路径号（第几条证明）" not in text, text
    # 依赖行的三格由框架填：引用原话 / 命题号 / 用在哪几步。
    assert re.search(rf"\| [^|]+ \| stmt:{sid} \| 第 [0-9、]+ 步 \|", text), text
    # 那一份交进来的 product 里根本没有 `## 依赖` 这个键（F 只给了 steps）。
    assert "## 依赖" not in _proof_product(sid)
    # 登记那一刻手上有稿（结构事实，不是时序运气）。
    assert data.get("manuscript_source") == "param", data


# ================================================================== b 反向①

def test_b_a_cite_that_is_not_on_the_ledger_is_refused_step_by_step(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b：`cites` 写了不可引的号 ⇒ 受控拒，逐条点名第几步，盘上不留稿。"""
    _gate_ok(monkeypatch)
    st = _ws(tmp_path)
    f = _f(st)
    _citable_statement(st)          # 有一条真在册的号，证明"不是完全没有号"
    plan_id = _plan(f)

    bad = {
        "kind": "proof",
        "proposition": "设 g ≥ 0 可积、|f_n| ≤ g；则 ∫|f_n − f| → 0。",
        "steps": [
            {"text": "设 g 可积（前提）", "assumption": True},
            {"text": "由控制收敛直接得结论", "cites": ["stmt:999999"]},
        ],
    }
    res = f.tools.call("attack.step", plan_id=plan_id, product=bad)
    assert res.ok, (res.meta.get("kind"), res.error)
    data = dict(res.data or {})
    assert data.get("action") == "no_change", data
    # 受控拒只把那一条子目标标成 blocked（卡点看得见），计划本身仍可接着攻。
    assert data.get("status") == "attacking", data
    detail = str(data.get("reason") or "")
    assert "第 2 步" in detail and "stmt:999999" in detail, detail
    assert "R-03" in detail or "伪造引用" in detail, detail
    assert "没有落稿" in detail, detail
    assert _reports(st) == [], _reports(st)

    plan_row = next(dict(r) for r in st.rows("attack_plans")
                    if str(r.get("plan_id")) == plan_id)
    blocked = plan_row["subgoals"][0]
    assert blocked.get("status") == "blocked", blocked
    assert "stmt:999999" in str(blocked.get("blocked_reason") or ""), blocked
    refusal = dict((plan_row.get("history") or [])[-1].get("refusal") or {})
    assert refusal.get("kind") == "handed_product_refused", refusal
    assert any("第 2 步" in str(p) and "stmt:999999" in str(p)
               for p in (refusal.get("problems") or [])), refusal


# ================================================================== c 反向②

def test_c_a_half_written_step_is_refused_with_the_validator_words(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：`kind=proof` 但某一步是空话（「易证」）⇒ 受控拒，带回校验器原话。"""
    _gate_ok(monkeypatch)
    st = _ws(tmp_path)
    f = _f(st)
    row = _citable_statement(st)
    plan_id = _plan(f)

    bad = {
        "kind": "proof",
        "steps": [
            {"text": "设 g 可积（前提）", "assumption": True},
            {"text": "易证结论成立", "cites": [f"stmt:{row['stmt_id']}"]},
        ],
    }
    res = f.tools.call("attack.step", plan_id=plan_id, product=bad)
    assert res.ok, (res.meta.get("kind"), res.error)
    data = dict(res.data or {})
    assert data.get("action") == "no_change", data
    detail = str(data.get("reason") or "")
    assert "steps[2]" in detail, detail
    assert "易证" in detail and "合法出口" in detail, detail
    assert _reports(st) == [], _reports(st)


# ================================================================== d 反向③

def _reading(d: dict) -> dict:
    """老路读数的可比那几格（计划号 / 轮次 / 路径这类随夹具变的键不进比较）。"""
    return {k: d.get(k) for k in ("action", "outcome", "status", "sid", "reason")}


def test_d_without_product_the_old_path_is_untouched(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d：不给 `product` ⇒ 与今天逐字一致（老路读数不动，新入口一次都没被走）。"""
    _no_seam(monkeypatch)
    st = _ws(tmp_path)
    f = _f(st)
    _plan(f, key="pk-old-1")

    def must_not_be_called(self, handed, sg, *, plan, owner):  # noqa: ANN001, ARG001
        raise AssertionError("没给 product，却走进了交进来的那一支 ⇒ 老路被替换了")

    monkeypatch.setattr(AgentF, "_handed_product_round", must_not_be_called)
    plan_id = next(str(r["plan_id"]) for r in st.rows("attack_plans")
                   if str(r.get("problem_key")) == "pk-old-1")

    omitted = dict(f.tools.call("attack.step", plan_id=plan_id).data or {})
    assert omitted.get("action") == "no_change", omitted
    assert "缺缝" in str(omitted.get("reason") or ""), omitted
    assert _reports(st) == [], _reports(st)

    # 显式 `product=None` 与"根本不给"必须给出同一份读数（缺省值透明的机器读数）。
    st2 = _ws(tmp_path / "second")
    f2 = _f(st2)
    _plan(f2, key="pk-old-2")
    plan2 = next(str(r["plan_id"]) for r in st2.rows("attack_plans"))
    explicit = dict(f2.tools.call("attack.step", plan_id=plan2, product=None).data or {})
    assert _reading(explicit) == _reading(omitted), (explicit, omitted)
    assert _reports(st2) == [], _reports(st2)


# ================================================================== e 反真空

def test_e_always_using_the_inner_seam_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """e：把"用 F 交的那份"改回"永远用内层缝" ⇒ a 红（不是"入口在不在都能绿"）。

    这一条是 a 的反真空：同一份 product 交进去，只要分支退回老路，稿就不会落盘、
    `manuscript_path` / `manuscript_id` 也回不来 —— 于是 a 那几格读数当场消失。
    """
    _gate_ok(monkeypatch)
    st = _ws(tmp_path)
    f = _f(st)
    row = _citable_statement(st)
    plan_id = _plan(f)

    def always_seam(self, handed, sg, *, plan, owner):  # noqa: ANN001, ARG001
        return self._seam_missing_round(sg, plan=plan)

    monkeypatch.setattr(AgentF, "_handed_product_round", always_seam)
    res = f.tools.call("attack.step", plan_id=plan_id,
                       product=_proof_product(str(row["stmt_id"])))
    assert res.ok, (res.meta.get("kind"), res.error)
    data = dict(res.data or {})
    assert data.get("action") == "no_change", data
    assert not data.get("manuscript_path"), data
    assert not data.get("manuscript_id"), data
    assert _reports(st) == [], _reports(st)
    assert "缺缝" in str(data.get("reason") or ""), data
