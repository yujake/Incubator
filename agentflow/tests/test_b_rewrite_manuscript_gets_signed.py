# -*- coding: utf-8 -*-
"""B 的改写有可签的载体：`reports/b-proof-<号>.md` + 收方秘书落块（业主 2026-11-04 裁定 A 甲）。

## 业主裁定（逐字）

    A 甲 —— B 的改写要有可签的载体：给 B 手稿签块（与 F/E 同形）

## 改前断在哪

B 改写在册证明时，正文与在册那一版不同 ⇒ 旧签 stale、台账也盖不住新正文。
B 的工具面没有文件写口 ⇒ 它拿不出"要被签的那一份稿"；V 的未在册入口只认
`reports/f-proof*.md`（E 那支只认 `reports/e-proof-*.md`）⇒ B 的正文没有一个
可以落签块的载体。结果是 `_self_authored_gate` / `_unsigned_proof_gate` 只能把
改写正文整笔拒掉（`self_authored_needs_v` / `proof_without_v_sign`），而 B 没有任何
可走的一步。

改后（本文件钉住的那条链）：
1. B 调显式落稿 `AgentB.land_manuscript`（工具壳 `own.land_manuscript` 由 T1
   那批接线）把改写后的正文落成 `reports/b-proof-<命题号>.md`
   （`## 命题` / `## 证明` / `## 依赖` 三节，与 F/E 同形）。
   2026-11-10（D1）之后登记不再顺手落稿：被闸拒的登记盘上零新增，想要载体就
   走这一步显式动作（旧写法是"登记被拒时顺手落一份"，本文件旧 a/c 钉的正是那个
   副作用 —— 已按 D1 改成钉显式动作，强度没降：仍然验三节 / 正文 sha / 签块 / 入库）；
2. B 派 V 审这一份稿（`verify.verify_proof` 带 `proof_manuscript` + `statement_id`）⇒
   三轮「成立」⇒ `vsigns.issue` ⇒ 收方秘书 `secretary:B` 把签块落回稿里；
3. B 再交一次 `own.register_statement`（带 `proof_manuscript`）⇒ 第 3 位翻真
   （`reviewed=true`）、canonical 换成改写后的正文（旧正文进 `proof_history`）。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 显式落稿 → V 三转 → 签块在稿（签名者=secretary:B）→ 入库成功且 reviewed=true | 改前没有显式落稿动作；旧断言钉的是"被拒登记顺手落的稿"（D1 副作用） |
| b | 没有签的手稿 ⇒ 入库仍被 `proof_without_v_sign` 拒（闸不许被绕） | 闸在改前就在；这一条是改后的负控（防止"给 B 开一条免签路"） |
| c | 反真空：把「B 手稿落签」那条摘掉（`SECRETARY_OF` 去掉 secretary:B）⇒ a 回到被拒 | 证明 a 的绿来自"收方秘书真的把块落进了稿"，不是来自别处认到一签 |

零模型调用：V 的审阅缝按剧本回答（`_ReviewSeam`），B 的登记不发模型请求。
"""
from __future__ import annotations

import contextlib
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import conductor as CND  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402

from test_agent_v_exhaustion_review import _v_secretary  # noqa: E402
from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam  # noqa: E402

FULL = "对任意正整数 n，R(3,4)=9。"
OLD_BODY = "1. 这是原来那一版证明（在册的 canonical 正文）。\n2. 结论成立。"
NEW_BODY = ("1. 先证上界：K_9 的任意二染色必含红色 K_3 或蓝色 K_4（穷举 2^36 个染色，"
            "按 canonical form 去掉对称性重数）。\n"
            "2. 再证下界：给出一个不含红色 K_3、也不含蓝色 K_4 的染色。\n"
            "3. 上下界相接 ⇒ R(3,4)=9。")


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


@contextlib.contextmanager
def _submitted_by_b():
    """这一趟 V 是 B 派出来的 ⇒ 收方 = `secretary:B`。"""
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-b-000001",
                        parent_role="B"):
        yield


def _b(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None)


def _register(st: Store, *, kind: str, full: str, proof_text: str = "",
              manuscript: str = "", label: str = "R(3,4)=9",
              evidence_kind: str = "proof_review") -> dict:
    return _b(st).register_statement(
        origin="own_result", kind=kind, label=label, statement_full=full,
        statement_text="R(3,4)=9", proof_text=proof_text,
        proof_manuscript=manuscript, evidence_kind=evidence_kind,
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")


def _seed(st: Store) -> tuple[dict, str]:
    """先落一条在册命题（猜想、无证明正文）—— B 要改写的就是它。"""
    first = _register(st, kind="conjecture", full=FULL, proof_text="",
                      evidence_kind="heuristic")
    assert first.get("ok") is True, first
    sid = str(first.get("stmt_id") or "")
    assert sid
    # 把 canonical 正文铺成"旧版"（夹具直接铺行：改稿重签那一组同形）。
    row = dict(next(r for r in st.rows("statements") if str(r.get("stmt_id")) == sid))
    row["proof_text"] = OLD_BODY
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return first, sid


def _review(st: Store, rel: str, sid: str) -> dict:
    seam = _ReviewSeam([CLEAN_REPLY])
    v = AgentV(st, workspace_root=st.root, llm=seam, secretary=_v_secretary(st))
    with _submitted_by_b():
        got = v.verify_proof(statement_id=sid, proof_manuscript=rel)
    assert seam.asked() == int(VR.SIGN_STREAK_NEED), seam.asked()
    return got


def _manuscript_text(st: Store, rel: str) -> str:
    return (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")


# ============================================================ a 正控
def test_a_b_rewrite_gets_a_signed_manuscript_then_lands_reviewed(
        tmp_path: pathlib.Path) -> None:
    """a：显式落稿 → V 三转 → 签块在稿（secretary:B）→ 入库 reviewed=true。"""
    st = _ws(tmp_path)
    _first, sid = _seed(st)

    landed = _b(st).land_manuscript(
        statement_id=sid, statement_full=FULL, proof_text=NEW_BODY,
        label="R(3,4)=9", proof_no=1)
    assert landed.get("ok") is True, landed
    assert landed.get("written") is True, landed
    rel = str(landed.get("path") or "")
    assert rel == f"reports/b-proof-{sid}.md", landed
    assert landed.get("sha256") == VR.text_sha(NEW_BODY), landed
    assert pathlib.Path(st.root, rel).is_file(), (
        "显式落稿没有写出可签的载体", landed)
    text = _manuscript_text(st, rel)
    for heading in ("## 命题", "## 证明", "## 依赖"):
        assert heading in text, heading
    # 被签的就是 B 改写后的那一份正文。
    assert VS.manuscript_proof_body(text) == NEW_BODY, text[-800:]

    got = _review(st, rel, sid)
    assert got.get("checked") is True, got
    # 2026-11-05：B 的改写稿带上命题号送审 ⇒ 走在册那条路（`kind=""`），
    # 不再落到 `proof_unregistered_signed`（那一路的签 `statement_id=""`、台账自引）。
    assert got.get("kind") == "", got
    assert got.get("statement_id") == sid, got
    block = VS.manuscript_sign_reading(_manuscript_text(st, rel), manuscript_path=rel)
    assert block["found"] is True and block["signed"] is True, block
    assert block["signer"] == "secretary:B", block
    assert block["proof_sha256"] == VR.text_sha(NEW_BODY), block
    # 第 9 格 `手稿号` 认的是这份稿（`b-proof-<号>`），不是"未在册"。
    assert block["identity_state"] == "resolved", block
    assert block["manuscript_id"] == sid, block

    filed = _register(st, kind="theorem", full=FULL, proof_text=NEW_BODY,
                      manuscript=_manuscript_text(st, rel))
    assert filed.get("ok") is True, filed
    assert dict(filed.get("b_manuscript") or {}).get("signed") is True, filed
    row = dict(next(r for r in st.rows("statements") if str(r.get("stmt_id")) == sid))
    bits = dict(row.get("bits") or {})
    assert bits.get("reviewed") is True, bits
    assert str(row.get("proof_text") or "") == NEW_BODY, row.get("proof_text")
    assert row.get("proof_history"), "旧正文没有进 proof_history ⇒ 不是精准替换"


# ============================================================ b 无签仍拒
def test_b_an_unsigned_manuscript_is_still_refused_by_the_gate(
        tmp_path: pathlib.Path) -> None:
    """b：没有签的手稿 ⇒ 入库仍被 `proof_without_v_sign` 拒（闸不许被绕）。"""
    st = _ws(tmp_path)
    unsigned = ("# B 的改写手稿：R(3,4)=9\n\n\n"
                "## 命题\n\n" + FULL + "\n\n## 证明\n\n" + NEW_BODY + "\n\n"
                "## 依赖\n\n"
                "| 引用（B 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
                "|---|---|---|---|\n"
                "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
    got = _register(st, kind="conjecture", full=FULL, proof_text=NEW_BODY,
                    manuscript=unsigned)
    assert got.get("ok") is False, got
    assert got.get("kind") == "proof_without_v_sign", got
    assert not list(st.rows("statements")), "没有签的手稿绕过了入库闸"


# ============================================================ c 反真空
def test_c_without_the_b_secretary_the_rewrite_goes_back_to_refused(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：摘掉「B 手稿落签」那条（收方表里没有 secretary:B）⇒ a 回到被拒。"""
    st = _ws(tmp_path)
    _first, sid = _seed(st)
    monkeypatch.setattr(VS, "SECRETARY_OF", ("secretary:F", "secretary:E"))

    landed = _b(st).land_manuscript(
        statement_id=sid, statement_full=FULL, proof_text=NEW_BODY,
        label="R(3,4)=9", proof_no=1)
    assert landed.get("ok") is True, landed
    rel = str(landed.get("path") or "")
    assert rel == f"reports/b-proof-{sid}.md", landed
    assert pathlib.Path(st.root, rel).is_file(), landed

    # 收方秘书不在表里 ⇒ 签颁发了也落不了块（`not_a_secretary`）；V 的读数照实。
    seam = _ReviewSeam([CLEAN_REPLY])
    v = AgentV(st, workspace_root=st.root, llm=seam, secretary=_v_secretary(st))
    with _submitted_by_b():
        got = v.verify_proof(statement_id=sid, proof_manuscript=rel)
    assert got.get("checked") is True, got
    block = VS.manuscript_sign_reading(_manuscript_text(st, rel), manuscript_path=rel)
    assert block["found"] is False, block

    filed = _register(st, kind="theorem", full=FULL, proof_text=NEW_BODY,
                      manuscript=_manuscript_text(st, rel))
    assert filed.get("ok") is False, filed
    row = dict(next(r for r in st.rows("statements") if str(r.get("stmt_id")) == sid))
    assert str(row.get("proof_text") or "") == OLD_BODY, row.get("proof_text")
