# -*- coding: utf-8 -*-
"""判据（S2 写侧）：一条定理可以有多条证明，每条证明各自有「审核通过」的签名。

## 这一份钉的是"写侧"的两处
1. `B.register_statement` 接受可选的 `proofs`（JSON 数组，元素 `{proof_no, text}`）：
   `#p1` 落进既有的 `proof_text`（老字段、老写法逐字不变），`#p2` 及以后落进同一行的
   证明清单（键就是 `verifications.PROOFS_KEY`，元素 `{proof_no, text, created_at}`）。
2. `verifications.record_verification` 的签名行记 `(stmt_id, proof_no, proof_sha256)`，
   并在同一次写里把「这一份证明的 reviewed」落进命题行的
   `bits.evidence.reviewed_by_proof`；`bits.reviewed` 仍是「任一份成立即为 True」的汇总位。

## 六条判据与它们各自的"改前红"
改前（HEAD `f481f24`）`register_statement` 没有 `proofs` 参数，所以 ②–⑥ 与 ① 的等价分支
在第一次调用就 `TypeError`（红在登记那一行）；① 的主断言（只给 `proof_text` 时行逐字节
不变）本来就是不许回归的护栏，改前也绿 —— 它红在同一份判据里的等价分支。

| 判据 | 它要证明的事 |
|---|---|
| ① 老写法逐字兼容 | 只给 `proof_text` 与 `proofs=[{proof_no:1,...}]` 落出逐字节相同的行（等价 #p1） |
| ② 多证明写入 | `proof_text` = #p1、清单里有 #p2、证明号唯一 |
| ③ 负控：重复的号 | 报错且不写半条（三态：要么全写、要么不写） |
| ④ 签名带对象 | 签 `(命题, #p2)` ⇒ 台账行 `stmt_id` 非空、`proof_no=2`、sha 是 #p2 的 |
| ⑤ 负控：不许借光 | 只签 #p1 ⇒ `#p2` 的 reviewed 读成 False，而命题级汇总仍是 True |
| ⑥ 哈希不是门锁 | 签完再改 `proof_text` ⇒ 写入成功，台账里仍是签名当时那个 sha |

全部 tmp 工作区、零模型调用（V 的签名路径在这里不经模型，直接调它的写入口），
不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑：
# "改前红"就是把 `git archive HEAD` 的旧文件铺到临时树里、再跑这一份）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store

STATEMENT = "设 G 是 3-正则群；则弦长函数不是常值。"
STATEMENT_TEXT = "弦长函数不是常值"
#: 自产命题的两件式（定理内容 + 证明过程）：`doc_id` 与 `quote_reason` 是本动作的硬要求
#: （`origin="own_result"` 的出处那一档在 `register_statement` 的预检里）。
OWN = {
    "statement_full": STATEMENT,
    "statement_text": STATEMENT_TEXT,
    "origin": "own_result",
    "doc_id": S.format_id(0),
    "quote_reason": "我方自产命题，没有外部引文要比对",
}
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n ≥ 3 得结论。"
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
_OK = {"verdict": "成立", "findings": []}


# ------------------------------------------------------------------ 小工具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _agent(store: Store) -> AgentB:
    """B 的真实现（零模型调用：这条路只碰秘书与 store）。"""
    return AgentB(store, extractor=None, extract_text=None, config={})


def _row(store: Store) -> dict:
    return dict(store.rows("statements")[0])


def _sign(store: Store, *, text: str = P1, proof_no: int = 1) -> dict:
    """V 的签名写入口（`verify_proof` 走的就是它；这里不经模型）。"""
    return VR.record_verification(
        store.root, statement_id=S.format_id(0), proof_text=text,
        verdict=dict(_OK), verifier="agent-V", store=store, proof_no=proof_no)


def _ledger(store: Store) -> list[dict]:
    """盘上的签名行（不是内存里那个 dict）。"""
    rows, problems = VR.list_verifications(store.root, statement_id=S.format_id(0),
                                           limit=None)
    assert problems == [], problems
    return rows


def _statement_upserts(store: Store) -> list[dict]:
    """`events.jsonl` 里 `statements` 的 upsert 事件（证明"一行都没写"用它）。"""
    out: list[dict] = []
    for line in store.events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if ev.get("op") == "upsert" and ev.get("table") == "statements":
            out.append(ev)
    return out


def _scrub(row: dict) -> dict:
    """去掉与"这一笔的内容"无关的两格（编号与时间戳），好做逐字节比较。"""
    out = dict(row)
    for key in ("stmt_id", "created_at"):
        out.pop(key, None)
    return out


# ============================================================ ① 老写法逐字兼容

def test_a_proof_text_only_call_is_byte_identical_to_a_one_proof_list(tmp_path):
    """① 老写法（只给 `proof_text`）与等价的 `proofs=[#p1]` 落出逐字节相同的行。

    两个工作区各登记一次同一条命题：#1 走老路（`proof_text`），#2 走新路
    （`proofs=[{"proof_no": 1, "text": 同]`）。除了编号与时间戳，两行必须逐字节相同 ——
    等价 `#p1` 的意思就是"新写法不许在那条老路上多写一个键、多改一个字"。
    """
    st_old, st_new = _ws(tmp_path / "old"), _ws(tmp_path / "new")
    out_old = _agent(st_old).register_statement(**OWN, proof_text=P1)
    out_new = _agent(st_new).register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1}])
    assert out_old["ok"] is True, out_old
    assert out_new["ok"] is True, out_new

    row_old, row_new = _row(st_old), _row(st_new)
    # 老路上不许冒出 `proofs` 键（只有 #p1 时不建清单：那一份就是 proof_text）。
    assert VR.PROOFS_KEY not in row_old, row_old.keys()
    assert row_old["proof_text"] == P1, row_old
    # 两行的键集都恰好是 schema 的字段（多一个键就是"新写法改动了老行"）。
    assert set(row_old) == set(S.Statement.__dataclass_fields__), sorted(row_old)
    assert set(row_new) == set(S.Statement.__dataclass_fields__), sorted(row_new)
    # 逐字节等价：同一份内容、同一组位、同一份正文。
    assert (json.dumps(_scrub(row_old), ensure_ascii=False, sort_keys=True)
            == json.dumps(_scrub(row_new), ensure_ascii=False, sort_keys=True)), (
        "只给 proof_text 与 proofs=[#p1] 必须落出同一行（等价 #p1）")
    # 返回值也不许多一格（老调用方读到的形状今天是什么样，明天还是）。
    assert "proofs" not in out_old and "proofs" not in out_new, (out_old, out_new)
    assert sorted(out_old) == sorted(out_new), (sorted(out_old), sorted(out_new))


# ============================================================ ② 多证明写入

def test_two_proofs_put_p1_in_proof_text_and_p2_in_the_list(tmp_path):
    """② `proofs=[{1,甲},{2,乙}]` ⇒ `proof_text`=甲、清单里有 `{2,乙}`、号唯一。"""
    st = _ws(tmp_path)
    out = _agent(st).register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])
    assert out["ok"] is True, out
    assert out["proofs"] == [{"proof_no": 2}], out

    row = _row(st)
    assert row["proof_text"] == P1, row
    listed = row[VR.PROOFS_KEY]
    assert [p["proof_no"] for p in listed] == [2], listed
    assert listed[0]["text"] == P2, listed
    assert str(listed[0].get("created_at") or "").strip(), listed

    # 证明号的读口径只走 `verifications.proof_list`（全仓唯一解析点）。
    assert [no for no, _ in VR.proof_list(row)] == [1, 2], VR.proof_list(row)
    assert VR.proof_text_of(row, 1) == P1 and VR.proof_text_of(row, 2) == P2
    nos = [int(p["proof_no"]) for p in listed]
    assert len(nos) == len(set(nos)) and min(nos) >= 1, nos
    # `#p1` 不进清单：同一格不许有两个权威。
    assert 1 not in nos, nos
    # 第 2 位（有证明）看的是"任何一份有正文"，而过程仍取 canonical 那一份。
    bits = row["bits"]
    assert bits["proof"] is True, bits
    assert bits["evidence"]["proof_process"] == P1, bits["evidence"]


# ============================================================ ③ 负控：一条坏 ⇒ 整笔不写

def test_a_duplicate_proof_no_refuses_the_whole_call(tmp_path):
    """③ `proofs` 里两条同号 ⇒ 报错且不写半条（三态：要么全写、要么不写）。

    同一条判据下再钉另外两档校验（空正文 / 非法号）：它们同样是"整笔不写"，
    且各自有自己的 `kind` —— 三条校验不许折成一句"参数不对"。
    """
    st = _ws(tmp_path / "dup")
    out = _agent(st).register_statement(
        **OWN, proofs=[{"proof_no": 2, "text": P1}, {"proof_no": 2, "text": P2}])
    assert out["ok"] is False and out["kind"] == "duplicate_proof_no", out
    assert "#2" in out["error"], out["error"]
    assert "整笔不写" in out["error"], out["error"]
    # 半条也不许落：内存、快照、事件日志三处都为空。
    assert st.rows("statements") == [], st.rows("statements")
    assert _statement_upserts(st) == [], _statement_upserts(st)
    snap = json.loads((st.data / "statements.json").read_text(encoding="utf-8"))
    assert snap["rows"] == [], snap

    for i, (bad, kind, needle) in enumerate((
            ([{"proof_no": 2, "text": "   "}], "empty_proof_text", "空的"),
            ([{"proof_no": 0, "text": P1}], "bad_proof_no", ">= 1"),
            ([{"proof_no": "abc", "text": P1}], "bad_proof_no", ">= 1"),
    )):
        st_bad = _ws(tmp_path / f"bad{i}")
        got = _agent(st_bad).register_statement(**OWN, proofs=bad)
        assert got["ok"] is False and got["kind"] == kind, (bad, got)
        assert needle in got["error"], got["error"]
        assert st_bad.rows("statements") == [], (bad, st_bad.rows("statements"))


# ============================================================ ④ 签名带对象

def test_signing_proof_two_records_the_object_in_the_signature_line(tmp_path):
    """④ 签 `(命题, proof_no=2)` ⇒ 台账行 `stmt_id` 非空、`proof_no=2`、sha 是 #p2 的。

    这一条钉的正是"真机把 `stmt_id` 写成了 None"那个缺口：签名行必须自己说清
    "我签的是哪条命题的哪一份证明的哪一版正文"，三者一个都不能缺。
    """
    st = _ws(tmp_path)
    _agent(st).register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])
    sid = _row(st)["stmt_id"]

    signed = _sign(st, text=P2, proof_no=2)
    assert signed["stmt_id"] == sid, signed
    assert signed["statement_id"] == sid, signed
    assert signed["proof_no"] == 2, signed
    assert signed["proof_sha256"] == VR.proof_sha(P2), signed
    assert signed["proof_sha256"] != VR.proof_sha(P1), "签的是 #p1 的正文就算错了"

    disk = _ledger(st)[-1]
    assert disk["stmt_id"] == sid and disk["statement_id"] == sid, disk
    assert disk["proof_no"] == 2, disk
    assert disk["proof_sha256"] == VR.proof_sha(P2), disk
    # 写回只翻被签的那一份（#p1 不是"被审过"，哪怕它排在前面）。
    wb = signed["statement_writeback"]
    assert wb["written"] is True and wb["rolled_back"] is False, wb
    assert wb["proof_no"] == 2 and wb["statement_id"] == sid, wb
    assert EB.reviewed_by_proof(_row(st)) == {1: False, 2: True}, _row(st)["bits"]


# ============================================================ ⑤ 负控：不许借光

def test_proof_two_does_not_borrow_proof_ones_signature(tmp_path):
    """⑤ 只签 #p1 ⇒ `#p2` 的 reviewed 为 False，而定理级 `bits.reviewed` 仍为 True。

    两层都要判：
    - 写侧的逐条表 `bits.evidence.reviewed_by_proof`（业主点名的那一格）；
    - 读侧的逐条读数（`statement_review_reading`）—— #p2 自成一档，档位不许被 #p1 抬起来。
    """
    st = _ws(tmp_path)
    _agent(st).register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])
    sid = _row(st)["stmt_id"]
    signed = _sign(st, text=P1, proof_no=1)
    wb = signed["statement_writeback"]
    assert wb["written"] is True and wb["proof_no"] == 1, wb

    bits = _row(st)["bits"]
    # 逐条表整表在（缺一格与"有、值为 False"读起来不一样）。
    per = bits["evidence"][EB.REVIEWED_BY_PROOF_KEY]
    assert per == {"1": True, "2": False}, per
    assert EB.reviewed_by_proof(_row(st)) == {1: True, 2: False}
    # 汇总位语义不变：任一份成立即为 True（#p1 成立）。
    assert bits["reviewed"] is True, bits
    assert bits["grade"] == "pre_theorem", bits
    # 顶层的键集仍由 `bits_shape_problems` 拥有：逐条表住在 evidence 里，不新增顶层键。
    assert EB.REVIEWED_BY_PROOF_KEY not in bits, sorted(bits)

    reading = VR.statement_review_reading(st.root, _row(st))
    assert reading["reviewed"] is True and reading["grade"] == "pre_theorem", reading
    p2 = next(p for p in reading["proofs"] if p["proof_no"] == 2)
    assert p2["reviewed"] is False and p2["state"] == "unsigned", p2
    assert p2["grade"] == "conjecture", "#p2 借了 #p1 的签"
    assert reading["proofs_unreviewed"] == [f"{sid}#p2"], reading


# ============================================================ ⑥ 哈希不是门锁

def test_editing_the_proof_after_signing_is_written_not_refused(tmp_path):
    """⑥ 签完再改 `proof_text` ⇒ 写入成功，台账里仍是签名当时那个 sha。

    这条钉的正是"哈希只做陈旧读数，不是授权凭证"：改稿是正常动作，
    任何写入路径都不许因为 sha 与当前 `proof_text` 不一致而拒收；`stale` 是读数，
    由读侧（`evidencebits.bits_from_row` 的 `_stale_review_cleared` 与
    `verifications.proof_review_gaps`）读出来。
    """
    st = _ws(tmp_path)
    # 先按弱档登记（`proof_review` 那一档在「还没有 V 那一签」时会被写入期闸当场拒收，
    # 那是它本来的职责）；签完再把档位升上去 —— 升档这一笔同时也改了 `proof_text`，
    # 于是它要穿过那道闸：写入期闸（`store._refuse_fake_proof_review`）读的是
    # `verifications.proof_review_gaps`，而 stale 不算"没有凭据"。
    # 登记走多证明那条路（`proofs=[#p1]`）：这一条与 ① 一样，钉的是"多证明写侧的
    # 那一笔本身不许因为签完之后又改稿而被拒"。
    out = _agent(st).register_statement(**OWN, proofs=[{"proof_no": 1, "text": P1}])
    assert out["ok"] is True, out
    signed = _sign(st, text=P1, proof_no=1)
    sha_at_sign = signed["proof_sha256"]
    assert sha_at_sign == VR.proof_sha(P1)

    edited = P1 + "\n3. 补上一步（这一句是签完之后才加的）。"
    row = _row(st)
    row["proof_text"] = edited
    row["evidence_kind"] = "proof_review"
    with st.tx("statements", actor="test", note="edit_after_sign") as tx:
        tx.upsert("statements", row, note="edit_after_sign")

    now = _row(st)
    assert now["proof_text"] == edited, now
    assert now["evidence_kind"] == "proof_review", now
    disk = _ledger(st)[-1]
    assert disk["proof_sha256"] == sha_at_sign, "台账那一行必须留在签名当时那一份上"
    assert disk["proof_sha256"] != VR.proof_sha(edited), disk
    # 写侧不回头改凭据（那是历史）；读侧据此判"签过、过期了"。
    by = now["bits"]["evidence"]["reviewed_by"]
    assert by["proof_sha256"] == sha_at_sign, by
    assert EB.bits_from_row(now)["reviewed"] is False, now["bits"]
    gap = VR.proof_review_gap(st.root, now)
    assert gap["state"] == "stale" and gap["ok"] is False, gap
    # stale 是"待复核"，不是"没有凭据"：写入期那道闸不许拿它当拒收理由。
    assert VR.proof_review_gaps(st.root, [now]) == [], "stale 不许被折成「没有凭据」"
    # 正控（防真空）：把正文改回去 ⇒ 那一签又盖住了现行这一份。
    row = _row(st)
    row["proof_text"] = P1
    with st.tx("statements", actor="test", note="edit_back") as tx:
        tx.upsert("statements", row, note="edit_back")
    assert EB.bits_from_row(_row(st))["reviewed"] is True, _row(st)["bits"]
    assert VR.proof_review_gap(st.root, _row(st))["ok"] is True
