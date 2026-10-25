# -*- coding: utf-8 -*-
"""兜底审计：B 读到的稿必须是框架渲染的那一版（缺洗稿元信息 ⇒ 受控拒绝）。

## 为什么要这一条（三件里的第三件）

`fs.write` / `fs.edit` 那一侧已经受控拒绝（`reserved_framework_artifact`），但
"换个名字绕过"永远有路：手写一份、别的工具落一份、人往盘上放一份。收方（B）是
最后一处能判断"这份稿是不是框架渲染的"的地方 —— 判据就在正文里那一行
`- 依赖面洗稿：`（`depsection.WASH_MARK`，由 F 的秘书在提交前 `mark_washed` 盖进正文）。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 盘上那份缺元信息 | 整笔受控拒绝 `manuscript_not_washed` 并点名"请让 F 用 proof 动作重写" | 改前照收，`manuscript_washed=False` 只是读数 |
| b 框架渲染的那一份 | 盖了元信息 ⇒ 照收（正控：别把正常路径弄坏） | —— |
| c 反真空 | 把洗稿元信息那一行打桩成"看不见" ⇒ b 必红 | —— |

不扩大：参数直递（`param`）那一档不在这里判 —— B 拿不到它的落点，"猜它是谁写的"
不是判据；这里只判"约定的 `reports/f-proof-*.md` 且没盖过章"。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store

THEOREM_A = S.format_id(0)
KIND = "manuscript_not_washed"
MESSAGE = "这份手稿不是框架渲染的（缺洗稿元信息），请让 F 用 proof 动作重写"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _add_statement(store: Store, stmt_id: str) -> dict:
    """写一条在册命题（`proof_review` 档：不升档的话 B 会因为档位不够而拒，那是另一条闸）。"""
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=f"命题 {stmt_id} 的证明正文（判据夹具）。",
        evidence_kind="heuristic", status="active", quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B")
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    signed = VR.record_verification(
        store.root, statement_id=stmt_id,
        proof_text=f"命题 {stmt_id} 的证明正文（判据夹具）。",
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
        store=store, proof_no=1)
    assert signed.get("checked") is True, signed
    got = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == stmt_id)
    got["evidence_kind"] = "proof_review"
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", got)
    return got


#: 一份"手写"的稿：有 `## 依赖` 四列表、但没有 `- 依赖面洗稿：` 那一行。
_HANDWRITTEN = (
    "# 证明手稿（手写）\n"
    "\n"
    f"- 命题号：stmt:{THEOREM_A}\n"
    "\n"
    + DS.SECTION_PROOF + "\n"
    "\n"
    f"1. 由在册定理直接得到第一步（依据：stmt:{THEOREM_A}）。\n"
    "2. 由第 1 步得结论。\n"
    "\n"
    + DS.SECTION_HEADING + "\n"
    "\n"
    "| 引用 | 命题号 | 用在哪一步 | 路径号 |\n"
    "|---|---|---|---|\n"
    f"| 由在册定理 | stmt:{THEOREM_A} | 第 1 步 | 1 |\n"
)


def _register(store: Store):
    b = AgentB(store, extractor=None, extract_text=None, config={})
    return b.register_statement(
        statement_full="引理：由在册定理推出结论（B 读稿的判据夹具）。",
        statement_text="由在册定理推出结论",
        proof_text=f"1. 由在册定理直接得到（依据：stmt:{THEOREM_A}）。",
        derived_from=[THEOREM_A], origin="own_result", kind="conjecture",
        quote_reason="我方自产命题（判据夹具）", doc_id=THEOREM_A,
        # 手稿走"盘上那一份"这条路（与真机兜底读盘同一个入口）
        proof_manuscript="")


def test_a_handwritten_manuscript_is_refused_by_name(tmp_path: pathlib.Path) -> None:
    """a 判据：盘上那份 `reports/f-proof-*.md` 缺洗稿元信息 ⇒ 整笔拒 + 点名。

    改前红：改前 B 照收（`ok=True`），`manuscript_washed=False` 只是一条读数 ——
    于是"手写的稿"与"框架渲染的稿"在下游长得一样，依赖面照样按手写那张表登记。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    rel = DS.manuscript_relpath(statement_id=THEOREM_A)
    (pathlib.Path(store.root) / rel).parent.mkdir(parents=True, exist_ok=True)
    (pathlib.Path(store.root) / rel).write_text(_HANDWRITTEN, encoding="utf-8")

    got = _register(store)
    assert got.get("ok") is False, got
    assert got.get("kind") == KIND, got
    assert MESSAGE == str(got.get("error") or "").strip(), got
    assert got.get("manuscript_path") == rel, got
    # 整笔不写：拒绝那一支不许顺手登记一行命题或落依赖边
    assert [r for r in store.rows("statements")
            if str(r.get("label") or "").startswith("引理")] == [], store.rows("statements")
    assert store.rows("dependencies") == [], store.rows("dependencies")


def test_the_framework_rendered_one_is_accepted(tmp_path: pathlib.Path) -> None:
    """b 判据（正控）：盖了 `- 依赖面洗稿：` 那一行 ⇒ 照收，依赖边真落。"""
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    rel = DS.manuscript_relpath(statement_id=THEOREM_A)
    washed = DS.mark_washed(_HANDWRITTEN, actor="secretary-F", filled="")
    (pathlib.Path(store.root) / rel).parent.mkdir(parents=True, exist_ok=True)
    (pathlib.Path(store.root) / rel).write_text(washed, encoding="utf-8")

    got = _register(store)
    assert got.get("ok") is True, got
    assert got.get("manuscript_source") == DS.SOURCE_DISK, got
    assert got.get("manuscript_washed") is True, got
    assert int(got.get("deps_written") or 0) >= 1, got


def test_stubbing_the_wash_mark_reading_out_turns_b_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c 判据（反真空）：把"读那一行元信息"打桩成永远读不到 ⇒ b 必红。

    证明 b 的绿来自"框架真的盖了章"，而不是来自"文件在盘上就放行"。
    """
    monkeypatch.setattr(DS, "manuscript_wash_reading",
                        lambda text: {"washed": False, "actor": "", "filled": "", "mark": ""})
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    rel = DS.manuscript_relpath(statement_id=THEOREM_A)
    washed = DS.mark_washed(_HANDWRITTEN, actor="secretary-F", filled="")
    (pathlib.Path(store.root) / rel).parent.mkdir(parents=True, exist_ok=True)
    (pathlib.Path(store.root) / rel).write_text(washed, encoding="utf-8")

    got = _register(store)
    assert got.get("ok") is False and got.get("kind") == KIND, (
        "元信息读不出来时居然还是收下了 ⇒ b 那条判据是真空的", got)
