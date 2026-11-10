# -*- coding: utf-8 -*-
"""「先签后收录」那一签，在收录那一笔里就该把 kind 升上去（p283，2026-11-11）。

## 现场（业主在最终 HEAD 上亲跑，只读）

```
B 收录后：proof_len=114、reviewed=true、grade=pre_theorem、proof_no=1、sha 对
但 kind 仍是 conjecture（不是 theorem）
```

对照：旧路（V 拿 statement_id 在册签）同一份稿 ⇒ `kind=theorem`。

## 根因

`_attach_proofs` 的 kind 升档（`_kind_upgrade_from_evidence`）在两处都传
`allow_pending=False`：2026-10-24 / 2026-11-10 的裁定「pending 只够过准入闸、不够升
kind」。那条裁定管的是“命题还没在册时” V 审的那一签（pending 行上还没有号，升档
留痕指不出"这条命题的哪一签"）。认领（`vsigns.bind_pending_claim` 把 `statement_id`
回写进 pending 台账行）之后，这一签已经绑在这条命题上：来路仍是 pending 文件，
但它就是本条命题自己的签 —— 继续按 pending 挡，等于让「先签后收录」这条主路永远
升不了档。

## 判据（a 正控 + b/c 反向 + d 反真空）

| # | 造什么 | 期望 |
|---|---|---|
| a | 稿号立项 → 未在册签 → B 收录（现取命题号） | `kind=theorem`、`grade=pre_theorem`、`reviewed=true`、`manuscript_id` 在行上、兜底稿 `f-proof-<命题号>.md` 不出现 |
| b | 只是 pending（没认领）⇒ 收录一份同正文 | `kind` 仍 `conjecture`（旧射程不变） |
| c | 认领后把凭据删掉再重写 | 降回 `conjecture`（不是"一升不降"） |
| d | 反真空：把「认领后按本条签评」改回「仍按 pending 评」 | a 红（kind 停在 conjecture） |

## 不碰真机

本文件只碰 `tmp_path` 下的临时工作区；模型面用 `SameStatementStub`（只替"是不是同
一条"那一问，检索 / 判据 / 落盘全是真实现）。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as _DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

from _same_statement_stub import SameStatementStub  # noqa: E402
from conftest import seed_statement_row  # noqa: E402

FULL = "对任意整数 n≥0：1^3 + 2^3 + … + n^3 = (n(n+1)/2)^2。"
LABEL = "sum-of-cubes-closed-form"
PROOF = ("对 n 作归纳。基例 n = 0：左边为空和 0，右边为 (0·1/2)^2 = 0，成立。"
         "归纳步：设 Σ_{k=1}^{n} k^3 = (n(n+1)/2)^2，则 "
         "Σ_{k=1}^{n+1} k^3 = (n+1)^3 + (n(n+1)/2)^2 = "
         "(n+1)^2 · (4(n+1) + n^2)/4 = (n+1)^2(n+2)^2/4 = ((n+1)(n+2)/2)^2，成立。")

#: F 自己的稿号（与命题号是两个号段 —— 新口径的关键）。
MANUSCRIPT_ID = "000007"


# ------------------------------------------------------------------ 夹具

def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _b(store: Store) -> AgentB:
    """按生产同形接一名秘书（只把"是不是同一条"那一问换成离线替身）。"""
    return AgentB(store, extractor=None, extract_text=None, config={},
                  secretary=Secretary("B", root=store.root, store=store,
                                      seam=SameStatementStub(), enable_model=True))


def _put(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _manuscript(*, manuscript_id: str = MANUSCRIPT_ID) -> tuple[str, str]:
    """F 的稿（稿头不点名命题号：这一份还没有号）—— 返回 `(相对路径, 全文)`。"""
    rel = f"reports/f-proof-{manuscript_id}.md"
    text = ("# 证明手稿（夹具：先签后收录）\n\n"
            "- 命题号：stmt:（待登记）\n"
            "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
            f"## 命题\n\n{FULL}\n\n"
            f"## 证明\n\n{PROOF}\n\n"
            + _DS.render_dependency_section([]))
    return rel, text


def _pending_sign(st: Store, *, rel: str) -> dict:
    """V 在命题还没在册时审的那一签（真写口：`record_pending_sign`）。"""
    return VR.record_pending_sign(
        str(st.root), proof_text=PROOF,
        verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path=rel,
        secretary_judge={"checked": True, "axis": "clean",
                         "decision": "没问题", "reason": "夹具：秘书判 clean"})


def _pending_rows(st: Store) -> list[dict]:
    base = pathlib.Path(st.root) / "verifications" / "pending"
    if not base.is_dir():
        return []
    return [json.loads(line) for p in sorted(base.glob("*.jsonl"))
            for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _row(st: Store, sid: str) -> dict:
    hit = [dict(r) for r in st.rows("statements") if str(r.get("stmt_id") or "") == sid]
    assert hit, f"盘上读不到命题 {sid}"
    return hit[0]


def _register_first_signed(tmp_path: pathlib.Path) -> dict:
    """a 的现场：稿号立项 → 未在册签 → B 收录（现取命题号）。"""
    st = _store(tmp_path)
    rel, text = _manuscript()
    _put(st, rel, text)
    signed = _pending_sign(st, rel=rel)
    filed = _b(st).register_statement(
        statement_full=FULL, statement_text=LABEL, label=LABEL,
        origin="own_result", kind="conjecture", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对",
        proof_text=PROOF, proof_manuscript=rel)
    sid = str(filed.get("stmt_id") or "")
    return {"store": st, "rel": rel, "sid": sid, "filed": filed,
            "signed": signed, "row": _row(st, sid)}


# ============================================================ a 正控

def test_a_the_sign_before_registration_lifts_the_kind_in_the_collection_write(
        tmp_path: pathlib.Path) -> None:
    """a：稿号立项 → 未在册签 → 收录 ⇒ 同一笔里 `kind=theorem`（改前红：conjecture）。"""
    got = _register_first_signed(tmp_path)
    st, sid, row = got["store"], got["sid"], got["row"]

    assert got["filed"].get("ok") is True, got["filed"]
    assert sid and sid != MANUSCRIPT_ID, (sid, MANUSCRIPT_ID)   # 稿号 ≠ 命题号
    # 四个格（业主亲跑的四格读数，一处不改）。
    assert row["manuscript_id"] == MANUSCRIPT_ID, row
    assert len(str(row.get("proof_text") or "")) == len(PROOF), row
    bits = dict(row.get("bits") or {})
    assert bits.get("reviewed") is True, row
    assert bits.get("grade") == "pre_theorem", row
    # 这一格是缺陷本体：改前它是 conjecture。
    assert row["kind"] == "theorem", row
    trace = dict(row.get("_kind_upgrade") or {})
    assert trace.get("from") == "conjecture" and trace.get("to") == "theorem", trace
    assert "pending" in str(trace.get("basis") or ""), trace

    # 认领：pending 行上回写了这一条的号（同一份正文只认领一次）。
    claim = [r for r in _pending_rows(st)
             if str(r.get("verification_id") or "") ==
             str(dict(got["signed"]).get("verification_id") or "")]
    assert claim and claim[0].get("statement_id") == sid, claim

    # 兜底稿不出现：稿名是稿号，不许再生成一份按命题号命名的 `f-proof-<sid>.md`。
    fallback = pathlib.Path(st.root) / "reports" / f"f-proof-{sid}.md"
    assert not fallback.exists(), f"收录兜底写出了 {fallback.name}"

    # 收录回执把这次升档说出来（不是只在盘上发生）。
    assert dict(got["filed"].get("kind_upgraded") or {}).get("to") == "theorem", got["filed"]


# ============================================================ b 反向①

def test_b_a_pending_sign_that_is_not_claimed_still_does_not_lift_the_kind(
        tmp_path: pathlib.Path) -> None:
    """b：只是 pending（没认领）⇒ 收录一份同正文，`kind` 仍 `conjecture`（旧射程不变）。

    造法：一条已登记、已有证明正文的猜想行 + 一份“没有认领”的 pending 签（行上
    `statement_id` 仍是空的），再走 `ingest_manuscript(mode="apply")` 收录同一份正文。
    旧裁定管的就是这一档：pending 只够过准入闸，不够升 kind。
    """
    st = _store(tmp_path)
    seeded = seed_statement_row(
        st, proof_text=PROOF, statement_full=FULL, statement_text=LABEL,
        kind="conjecture", label=LABEL, origin="own_result",
        evidence_kind="heuristic", manuscript_id=MANUSCRIPT_ID,
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=PROOF,
                        kind="conjecture"))
    sid = str(seeded["stmt_id"])
    rel, text = _manuscript()
    _put(st, rel, text)
    _pending_sign(st, rel=rel)
    pending = _pending_rows(st)
    assert pending and not str(pending[0].get("statement_id") or ""), pending

    ing = _b(st).ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                                   cells=["proof_text"], mode="apply")
    assert ing.get("ok") is True, ing
    row = _row(st, sid)
    assert str(row.get("kind") or "conjecture") == "conjecture", row
    assert "_kind_upgrade" not in row, row
    # 没认领的 pending 在来路上仍是 pending（不是"没查成"）。
    gap = VR.proof_review_gap(st.root, row)
    assert gap.get("checked") is True and gap.get("pending") is True, gap
    read = EB.kind_following_grade(row, root=st.root, allow_pending=False)
    assert read.get("state") == "held" and read.get("kind") == "conjecture", read


# ============================================================ c 反向②

def test_c_deleting_the_claimed_credential_lowers_the_kind_on_the_next_write(
        tmp_path: pathlib.Path) -> None:
    """c：认领后把凭据删掉再重写 ⇒ 降回 `conjecture`（不是"一升不降"）。

    先量"凭据还在时重写"—— 那一笔必须保持 theorem（升档不是靠一次性的副作用）；
    再把已认领的 pending 台账删掉，同一条 apply 必须按现行事实把 kind 落回原档。
    """
    got = _register_first_signed(tmp_path)
    st, sid, rel = got["store"], got["sid"], got["rel"]
    assert got["row"]["kind"] == "theorem", got["row"]

    # 凭据还在：重写一次，kind 不动（只读现行事实，不是"升了就锁死"）。
    again = _b(st).ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                                     cells=["proof_text"], mode="apply")
    assert again.get("ok") is True, again
    assert _row(st, sid)["kind"] == "theorem", _row(st, sid)

    # 删掉凭据（已认领的 pending 台账行）再重写。
    pending_dir = pathlib.Path(st.root) / "verifications" / "pending"
    removed = list(pending_dir.glob("*.jsonl"))
    assert removed, "夹具里没有 pending 台账可删"
    for path in removed:
        path.unlink()
    ing = _b(st).ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                                   cells=["proof_text"], mode="apply")
    assert ing.get("ok") is True, ing
    row = _row(st, sid)
    assert row["kind"] == "conjecture", row
    trace = dict(row.get("_kind_upgrade") or {})
    assert trace.get("downgraded") is True, trace
    assert trace.get("to") == "conjecture" and trace.get("from") == "theorem", trace
    # 降档是"按现行事实读"：那一条签不在盘上了，来路读数也不许再说 signed。
    gap = VR.proof_review_gap(st.root, row)
    assert gap.get("ok") is False, gap


# ============================================================ d 反真空

def test_d_anti_vacuum_treating_the_claimed_sign_as_pending_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d 反真空：把「认领后按本条签评」改回「仍按 pending 评」⇒ a 红。

    打桩只改"来路"这一格（`_gap_from_pending` 把已认领的那一签仍报成 pending），
    判据 / 落盘 / 认领全走真实现。a 的升档必须当场消失 —— 否则 a 的绿灯不是由
    这一条修出来的（反真空）。
    """
    real = VR._gap_from_pending

    def _still_pending(out, checks, got, *, statement_id, manuscript_id=""):
        read = real(out, checks, got, statement_id=statement_id,
                    manuscript_id=manuscript_id)
        read["pending"] = True
        read["claimed"] = False
        return read

    monkeypatch.setattr(VR, "_gap_from_pending", _still_pending)
    got = _register_first_signed(tmp_path)
    assert got["filed"].get("ok") is True, got["filed"]
    assert str(got["row"].get("kind") or "conjecture") == "conjecture", got["row"]
    assert "_kind_upgrade" not in got["row"], got["row"]
