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
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store
from _credential_fixture import issue_credential

THEOREM_A = S.format_id(0)
KIND = "manuscript_not_washed"
MESSAGE = "这份手稿不是框架渲染的（缺洗稿元信息），请让 F 用 proof 动作重写"


def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _add_statement(store: Store, stmt_id: str) -> dict:
    """写一条在册命题（等级到 `pre_theorem`：不升档的话 B 会因为档位不够而拒，那是另一条闸）。

    ## 为什么是五元位、不是 `evidence_kind`（2026-11-05 口径：等级是唯一的轴）
    可引门槛读的是 `depsection.statement_grade`（由 `evidencebits.derive_grade` 从五元位
    现算），`evidence_kind` 只是历史列。改前这一笔只把 `evidence_kind` 改成 `proof_review`
    而 `bits` 留空 ⇒ 现算等级仍是 `conjecture`，引用门如实拒它（那正是旧断言钉旧词表的
    地方）。所以第 2 位（`proof`）要随这一行的正文一起落；第 3 位由下面三次「成立」签
    写回翻真 —— 两件合起来才是 `pre_theorem`。

    ## 为什么要签 3 次（业主 2026-10-29 定稿的口径）
    V 的签不再"一次成立就签"：同一份证明、同一版正文（同 `proof_sha256`）要连续 3 次
    给出「成立」且秘书判定通过，才轮到 V 的秘书落签（`verifications.sign_statement`）。
    第 1、2 次只落台账、`bits.evidence` 不翻位，而 `evidence_kind="proof_review"` 的
    写入期闸（`store._refuse_fake_proof_review`）读的正是那份凭据 ⇒ 只签一次会让这一份
    夹具在 `tx.upsert` 上被整笔拒收。所以这里签够次数，并先断"1 次不签"（新规矩的正控）。
    """
    proof = f"命题 {stmt_id} 的证明正文（判据夹具）。"
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=proof,
        evidence_kind="heuristic", status="active", quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=proof,
                        kind="theorem"),
        created_at=S.now_iso(), created_by="agent-B")
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    signed: dict = {}
    for wanted in (1, 2, 3):
        signed = VR.record_verification(
            store.root, statement_id=stmt_id, proof_text=proof,
            verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
            store=store, proof_no=1, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
        holds = VR.consecutive_holds(store.root, stmt_id)
        assert holds["checked"] is True and int(holds["streak"]) == wanted, holds
        writeback = dict(signed.get("statement_writeback") or {})
        if wanted < VR.SIGN_STREAK_NEED:
            assert writeback.get("written") is False, (
                f"连续 {wanted} 次「成立」就翻了第 3 位 ⇒ 2026-10-29 的口径没生效", writeback)
    assert signed.get("checked") is True, signed
    assert dict(signed.get("statement_writeback") or {}).get("written") is True, signed
    got = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == stmt_id)
    # 档位只由等级反算（历史列）：`proof ∧ reviewed` ⇒ `pre_theorem` ⇒ `proof_review`。
    got["evidence_kind"] = EB.kind_from_bits(got.get("bits") or {}, kind="theorem")
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", got)
    return got


#: 一份"手写"的稿：有 `## 依赖` 三列表、但没有 `- 依赖面洗稿：` 那一行。
#: 这一笔要写进台账的那一份正文（稿里的 `## 证明` 与它逐字相同 ⇒ 签块盖住两处）。
OWN_PROOF = f"1. 由在册定理直接得到（依据：stmt:{THEOREM_A}）。"


#: 稿头声明的是本行自己的号（D1 严格版：兜底读盘只认自己的按号稿）。
def _handwritten(sid: str) -> str:
    return (
        "# 证明手稿（手写）\n"
        "\n"
        "\n"
        + DS.SECTION_PROOF + "\n"
        "\n"
        + OWN_PROOF + "\n"
        "\n"
        + DS.SECTION_HEADING + "\n"
        "\n"
        "| 引用 | 命题号 | 用在哪一步 | 路径号 |\n"
        "|---|---|---|---|\n"
        f"| 由在册定理 | stmt:{THEOREM_A} | 第 1 步 | 1 |\n"
    )


#: 这一条要被登记的新命题（先落成猜想拿号，再交它的按号稿）。
TARGET_FULL = "引理：由在册定理推出结论（B 读稿的判据夹具）。"
TARGET_TEXT = "由在册定理推出结论"


def _agent(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None, config={})


def _seed_target(store: Store) -> str:
    """先把这一条落成"没有正文"的猜想行（拿到号）—— 稿要按这一条的号命名。

    2026-11-05 业主裁定（D1 严格版）：兜底读盘只认"本行自己的稿"。这几条判据量的是
    洗稿闸，不是寻址；所以先把本行的号拿到，再把它自己的 `reports/f-proof-<本行号>.md`
    放上盘 —— 于是命中的是"自己的按号稿"，（洗稿闸照旧是这一条判据要量的那一道）。
    """
    got = _agent(store).register_statement(
        statement_full=TARGET_FULL, statement_text=TARGET_TEXT,
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
        proof_text="", origin="own_result", derived_from=["999999"], kind="conjecture",
        quote_reason="我方自产命题（判据夹具）", doc_id=THEOREM_A)
    assert got.get("ok") is True, got
    return str(got["stmt_id"])


def _register(store: Store):
    b = _agent(store)
    proof = f"1. 由在册定理直接得到（依据：stmt:{THEOREM_A}）。"
    return b.register_statement(
        statement_full=TARGET_FULL,
        statement_text=TARGET_TEXT,
        proof_text=proof,
        derived_from=[THEOREM_A], origin="own_result", kind="conjecture",
        quote_reason="我方自产命题（判据夹具）", doc_id=THEOREM_A,
        # 手稿走"盘上那一份"这条路（与真机兜底读盘同一个入口）
        proof_manuscript="")


def _stamp_own_manuscript(store: Store, *, sid: str, rel: str) -> None:
    """这一条已经在册 ⇒ 签要落在它自己的那份稿上（签块盖住正文 sha）。

    2026-11-05（D1 严格版）之后，稿是本行自己的按号稿；已有号的那一档认签走
    "手稿签块"（`bits_after_sign` 的第 1 来源），不再是"未在册先落 pending"那一档。

    2026-11-10（T1 收口）：D268 批 2 之后签只认 `vsigns.sign_reading` 的可复算凭据；
    三行台账 + 一块签块 = `unissued`（够票、没有 `out/vsigns/<sha>.json`）。这里改用
    批 2 自己那份夹具（`_credential_fixture.issue_credential`：三票同源 + `vsigns.issue`），
    再把块盖上去当视图。改的是夹具，不是断言：这一步本来就是"V 签过这一版"的替身。
    """
    proof = f"1. 由在册定理直接得到（依据：stmt:{THEOREM_A}）。"
    path = pathlib.Path(store.root) / rel
    text = path.read_text(encoding="utf-8")
    signed = issue_credential(store.root, proof_text=proof, statement_id=sid,
                              manuscript=rel, proof_no=1)
    ledger = str(dict(signed.get("sign") or {}).get("ledger") or "")
    path.write_text(VS.stamp_manuscript_sign(
        text, proof_sha=VR.text_sha(proof), streak=VR.SIGN_STREAK_NEED,
        need=VR.SIGN_STREAK_NEED, verdict="成立", at="2026-11-05T12:00:00+08:00",
        ledger=ledger, statement_id=sid,
        manuscript_id=VS.manuscript_id_of(rel)), encoding="utf-8")


def test_a_handwritten_manuscript_is_refused_by_name(tmp_path: pathlib.Path) -> None:
    """a 判据：盘上那份 `reports/f-proof-*.md` 缺洗稿元信息 ⇒ 整笔拒 + 点名。

    改前红：改前 B 照收（`ok=True`），`manuscript_washed=False` 只是一条读数 ——
    于是"手写的稿"与"框架渲染的稿"在下游长得一样，依赖面照样按手写那张表登记。
    """
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    sid = _seed_target(store)
    rel = DS.manuscript_relpath(statement_id=sid)
    (pathlib.Path(store.root) / rel).parent.mkdir(parents=True, exist_ok=True)
    (pathlib.Path(store.root) / rel).write_text(_handwritten(sid), encoding="utf-8")

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
    sid = _seed_target(store)
    rel = DS.manuscript_relpath(statement_id=sid)
    washed = DS.mark_washed(_handwritten(sid), actor="secretary-F", filled="")
    (pathlib.Path(store.root) / rel).parent.mkdir(parents=True, exist_ok=True)
    (pathlib.Path(store.root) / rel).write_text(washed, encoding="utf-8")
    _stamp_own_manuscript(store, sid=sid, rel=rel)

    got = _register(store)
    assert got.get("ok") is True, got
    assert got.get("manuscript_source") == DS.SOURCE_DISK, got
    assert got.get("manuscript_washed") is True, got
    # 依赖边真落（这一笔是"在册 + 补正文"那一支 ⇒ 边在 `manuscript_deps` 里；
    # 老写法（新建那一支）读的是 `deps_written`。两处都认，判的是"边上有没有"）。
    deps = [dict(r) for r in store.rows("dependencies")
            if str(r.get("used_by")) == f"stmt:{sid}"]
    assert len(deps) >= 1, (got, deps)
    written = got.get("deps_written")
    if written is None:
        written = (got.get("manuscript_deps") or {}).get("deps_written")
    assert int(written or 0) >= 1, got


def test_stubbing_the_wash_mark_reading_out_turns_b_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c 判据（反真空）：把"读那一行元信息"打桩成永远读不到 ⇒ b 必红。

    证明 b 的绿来自"框架真的盖了章"，而不是来自"文件在盘上就放行"。
    """
    monkeypatch.setattr(DS, "manuscript_wash_reading",
                        lambda text: {"washed": False, "actor": "", "filled": "", "mark": ""})
    store = _ws(tmp_path)
    _add_statement(store, THEOREM_A)
    sid = _seed_target(store)
    rel = DS.manuscript_relpath(statement_id=sid)
    washed = DS.mark_washed(_handwritten(sid), actor="secretary-F", filled="")
    (pathlib.Path(store.root) / rel).parent.mkdir(parents=True, exist_ok=True)
    (pathlib.Path(store.root) / rel).write_text(washed, encoding="utf-8")
    _stamp_own_manuscript(store, sid=sid, rel=rel)

    got = _register(store)
    assert got.get("ok") is False and got.get("kind") == KIND, (
        "元信息读不出来时居然还是收下了 ⇒ b 那条判据是真空的", got)
