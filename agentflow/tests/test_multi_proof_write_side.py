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

import pytest

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

from conftest import seed_statement_row

STATEMENT = "设 G 是 3-正则群；则弦长函数不是常值。"
STATEMENT_TEXT = "弦长函数不是常值"
#: 自产命题的两件式（定理内容 + 证明过程）：`doc_id` 与 `quote_reason` 是本动作的硬要求
#: （`origin="own_result"` 的出处那一档在 `register_statement` 的预检里）。
#:
#: 2026-10-22（业主裁定 B-2「没有引文 / 自己编的命题必须从『猜想』注册」）：加了
#: `kind="conjecture"` —— 这一组测的是多证明清单的写侧（`proofs` 的号 / 正文 / 追加），
#: 与声明成哪一种 kind 无关，而自产且无出处的一笔从这一批起只许按猜想登记。
OWN = {
    "statement_full": STATEMENT,
    "statement_text": STATEMENT_TEXT,
    "origin": "own_result",
    "kind": "conjecture",
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
    """V 的一次审校（`verify_proof` 走的就是它；这里不经模型）= 台账一票，不翻位。

    业主 2026-10-29：同一份正文连续 3 次「成立」才发签（`SIGN_STREAK_NEED`）。
    票数按 `(命题号, 证明号)` 分组 ⇒ 下面 `_sign_n` 只给一份证明投票。
    """
    return VR.record_verification(
        store.root, statement_id=S.format_id(0), proof_text=text,
        verdict=dict(_OK), verifier="agent-V", store=store, proof_no=proof_no, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})


def _sign_n(store: Store, *, text: str = P1, proof_no: int = 1,
            n: int = VR.SIGN_STREAK_NEED) -> dict:
    """再给 `#proof_no` 投 `n` 票（同一份正文、同一证明号），返回最末那一票。

    每一步都断"连续读数按 +1 涨"与"没到门槛就不翻位、到了就翻"：
    这样"3 次之后才签"与"票按证明号各数各的"两件事在夹具上各自被量到。
    """
    last: dict = {}
    base: int | None = None
    for i in range(1, int(n) + 1):
        last = _sign(store, text=text, proof_no=proof_no)
        wb = dict(last.get("statement_writeback") or {})
        got = int(wb.get("streak") or 0)
        if base is None:
            base = got - 1
        assert got == base + i, (f"第 {i} 票的连续读数不对（这一批之前 {base} 票）", wb)
        need = int(wb.get("need") or VR.SIGN_STREAK_NEED)
        if got >= need:
            assert wb.get("written") is True, ("票数够了仍然没发签", wb)
        else:
            assert wb.get("written") is False, (f"第 {i} 票（{got}/{need}）就把第 3 位翻了", wb)
    return last


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
    """去掉与"这一笔的内容"无关的格子（编号与所有时间戳），好做逐字节比较。"""
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()
                    if k not in ("stmt_id", "created_at", "at", "updated_at")}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return clean(dict(row))


# ============================================================ ① 正文必须有手稿签

def _empty_then_sign(st: Store, *, text: str, manuscript: str) -> None:
    """先落一条没有正文的猜想行拿号，再按 `manuscript` 签这一份正文。"""
    made = _agent(st).register_statement(**OWN)
    assert made["ok"] is True, made
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            str(st.root), statement_id=str(made["stmt_id"]), proof_text=text,
            verdict=dict(_OK), verifier="agent-V", store=st, proof_no=1,
            manuscript=manuscript, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})


def test_a_proof_text_only_call_needs_a_manuscript_sign(tmp_path):
    """① 只有内联签的正文 ⇒ 拒；换一份手稿签 ⇒ 老写法与 `proofs=[#p1]` 逐字节相同。

    老判据断言"只给 `proof_text` 与 `proofs=[#p1]` 落出同一行"，那是内联老路本身。
    新判据先钉住"内联签不够"（正文要有审的是手稿的签），再在"有手稿签"的前提下
    保留原来那一半：两种 #p1 写法落出的行逐字节相同。
    2026-11-09（缺陷③）：正文覆盖 / 新建这一支也要写收录回执（`proof_no` /
    `proof_sha256`），且 sha 必须等于盘上那份正文的真实 sha、号等于该份的号。
    """
    # 负控：签是内联审出来的（台账行没有 `manuscript`）⇒ 整笔拒。
    st_bad = _ws(tmp_path / "inline")
    made = _agent(st_bad).register_statement(**OWN)
    assert made["ok"] is True, made
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            str(st_bad.root), statement_id=str(made["stmt_id"]), proof_text=P1,
            verdict=dict(_OK), verifier="agent-V", store=st_bad, proof_no=1, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    bad = _agent(st_bad).register_statement(**OWN, proof_text=P1)
    assert bad["ok"] is False, bad
    assert bad.get("kind") == "proof_text_needs_a_manuscript_sign", bad
    assert str(_row(st_bad).get("proof_text") or "") == "", _row(st_bad)

    # 正控：同一份正文，签的是手稿 ⇒ 两种 #p1 写法逐字节相同。
    st_old, st_new = _ws(tmp_path / "old"), _ws(tmp_path / "new")
    _empty_then_sign(st_old, text=P1, manuscript="reports/f-proof-000000.md")
    _empty_then_sign(st_new, text=P1, manuscript="reports/f-proof-000000.md")
    from agentflow import depsection as DS

    ms = ("# F 的证明手稿\n\n- 命题号：stmt:000000\n\n## 命题\n\n" + STATEMENT
          + "\n\n## 证明\n\n" + P1 + "\n\n" + DS.render_dependency_section([]))
    out_old = _agent(st_old).register_statement(**OWN, proof_text=P1,
                                                proof_manuscript=ms)
    out_new = _agent(st_new).register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1}], proof_manuscript=ms)
    assert out_old["ok"] is True, out_old
    assert out_new["ok"] is True, out_new

    row_old, row_new = _row(st_old), _row(st_new)
    assert VR.PROOFS_KEY not in row_old, row_old.keys()
    assert row_old["proof_text"] == P1, row_old
    # 新前提：登记前已有一份手稿签（`_empty_then_sign`）⇒ 这一笔按盘上凭据留两处痕：
    # - `_kind_upgrade`：`kind` 按第 3 位抬一次（conjecture → theorem）；
    # - `_grade_recomputed`：按现行签重算等级（2026-11-05 的登记期回填，
    #   `verifications._grade_recomputed_from_signature`）。
    # 两者都是"这一档是从盘上哪一签读出来的"，不是调用方自报；它们与"两种 #p1 写法
    # 是否等价"无关，所以从"只差内部留痕"的集合里各自排除，并逐格断言来路。
    # 2026-11-05：`_grade_recomputed` 的 `from` / `to` 是等级，历史档位由
    # `from_kind` / `to_kind` 反算给出；`evidence_kind` 只是历史列，登记期不再回填
    # （判定面读 `derive_grade`）。
    # 2026-11-06（真机 R-mk-infinite-92）：收录回执两格（`proof_no` / `proof_sha256`）——
    # 2026-11-09（缺陷③）起口径是"这一行真有正文的每一支都写"：新建 / 正文覆盖这一支
    # 也要有（第几份证明由 B 收录时决定；只在一支上写反而让两条等价写法落出不同的行）。
    # 它们不是 `schema.Statement` 的字段（改磁盘格式契约要人审），`_attach_proofs` 一直
    # 就以非 schema 键写这两格；这里沿用既有容忍度，所以从"只差内部留痕"的集合里排除。
    allowed = {"_kind_upgrade", VR.GRADE_RECOMPUTED_KEY, "proof_no", "proof_sha256"}
    assert set(row_old) - allowed == set(S.Statement.__dataclass_fields__), sorted(row_old)
    assert set(row_new) - allowed == set(S.Statement.__dataclass_fields__), sorted(row_new)
    for row, store in ((row_old, st_old), (row_new, st_new)):
        # 键的存在本身要有凭据面兜底：这一行确实被按签升到 `pre_theorem`。
        assert EB.derive_grade(EB.bits_from_row(row),
                               kind=str(row.get("kind") or "")) == "pre_theorem", row
        trace = dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {})
        assert trace.get("checked") is True, trace
        assert trace.get("to") == "pre_theorem", trace
        assert trace.get("to_kind") == VR.PROOF_REVIEW_KIND, trace
        assert trace.get("from") and trace.get("from") != trace.get("to"), trace
        assert trace.get("proof_no") == 1, trace
        # 2026-11-09（缺陷③）：收录回执（`proof_no` / `proof_sha256`）在"这一行真有
        # 正文"的每一支都写 —— 新建 / 正文覆盖这一支也要有（第几份证明由 B 收录时
        # 决定）；且 sha 必须是盘上那份正文的真实 sha、号必须等于该份的号，不是自报。
        # 它们不是 schema 字段（见上）。
        assert row.get("proof_no") == 1, sorted(row)
        assert str(row.get("proof_sha256") or "") == VR.text_sha(P1), (
            row.get("proof_sha256"), VR.text_sha(P1))
        assert str(row.get("proof_sha256") or "") == VR.text_sha(
            str(row.get("proof_text") or "")), row
        last = _ledger(store)[-1]
        assert trace.get("basis") == (
            f"verifications/{S.format_id(0)}.jsonl#{last['verification_id']}"), trace
    assert (json.dumps(_scrub(row_old), ensure_ascii=False, sort_keys=True)
            == json.dumps(_scrub(row_new), ensure_ascii=False, sort_keys=True)), (
        "有手稿签时，只给 proof_text 与 proofs=[#p1] 必须落出同一行（等价 #p1）")
    assert "proofs" not in out_old and "proofs" not in out_new, (out_old, out_new)
    assert sorted(out_old) == sorted(out_new), (sorted(out_old), sorted(out_new))


def test_a2_without_the_receipt_write_the_new_row_has_no_proof_number(
        tmp_path, monkeypatch):
    """① 反真空：把"写收录回执"摘掉 ⇒ 新建 / 正文覆盖这一支的行上就没有两格（① 红）。

    打桩点取"写盘前那一格"（`Secretary.land_statement`）：它把 `transition` 交来的行
    原样写盘。这里把 `proof_no` / `proof_sha256` 从要写的那一行里拿掉 —— 正是缺陷③
    改前的形态。① 的"盘上两格与真实正文 sha 一致"因此不再成立（红），证明它的绿
    真的来自 `_attach_proofs` 那一笔写入。
    """
    import agentflow.secretary as SEC

    real = SEC.Secretary.land_statement

    def _strip(self, stmt_id, transition, **kwargs):
        def _inner(row):
            got = transition(row)
            if isinstance(got, dict) and isinstance(got.get("row"), dict):
                stripped = dict(got["row"])
                stripped.pop("proof_no", None)
                stripped.pop("proof_sha256", None)
                got = dict(got)
                got["row"] = stripped
            return got

        return real(self, stmt_id, _inner, **kwargs)

    monkeypatch.setattr(SEC.Secretary, "land_statement", _strip)
    st = _ws(tmp_path)
    _empty_then_sign(st, text=P1, manuscript="reports/f-proof-000000.md")
    from agentflow import depsection as DS

    ms = ("# F 的证明手稿\n\n- 命题号：stmt:000000\n\n## 命题\n\n" + STATEMENT
          + "\n\n## 证明\n\n" + P1 + "\n\n" + DS.render_dependency_section([]))
    out = _agent(st).register_statement(**OWN, proof_text=P1, proof_manuscript=ms)
    assert out["ok"] is True, out
    row = _row(st)
    assert row["proof_text"] == P1, row
    assert "proof_no" not in row, sorted(row)
    assert "proof_sha256" not in row, sorted(row)


# ============================================================ ② 多证明写入

@pytest.mark.usefixtures("signed_v_handoffs")
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


def test_a_later_proof_is_appended_and_an_existing_one_is_never_overwritten(tmp_path):
    """③ 的同族（既有行这一侧）—— 期望反转（准入闸变严：无签不再可写）。

    改前：后补的证明追加成功、同号不同正文 ⇒ `proof_no_taken`、canonical 改版 ⇒
    写入成功（旧正文进 `proof_history`）。
    改后（2026-11-02 准入闸 strict）：这一笔要写的每一份正文都要有覆盖它的 V 签，
    而"补 #pN / 改版"的新正文一份签都没有 ⇒ 三笔都读 `proof_without_v_sign`
    （整笔不写）。盘上原样、台账不增行两条断言保留。

    现场按历史形态铺行（`#p1`+`#p2` 已在册、还没有签）—— strict 下"有证明、无签"
    经 `register_statement` 造不出来，而这一条测的是写入被拒之后盘上有没有变。
    """
    st = _ws(tmp_path)
    b = _agent(st)
    seeded = seed_statement_row(
        st, proof_text=P1, statement_full=OWN["statement_full"],
        statement_text=OWN["statement_text"], kind="conjecture",
        label="弦长函数不是常值", origin="own_result", doc_id=S.format_id(0),
        quote_reason=OWN["quote_reason"],
        proofs=[{"proof_no": 2, "text": P2, "created_at": S.now_iso()}],
        bits=EB.with_optimized_defaults(
            EB.bits_of(origin="own_result", proof=True, proof_process=P1,
                       kind="conjecture"), [1, 2]))
    sid = str(seeded["stmt_id"])
    before = _row(st)
    assert [no for no, _ in VR.proof_list(before)] == [1, 2], VR.proof_list(before)

    P3 = "第三条路线：\n1. 用对偶。\n2. 收尾。"
    more = b.register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 3, "text": P3}])
    assert more["ok"] is False and more["kind"] in (
        "proof_manuscript_required", "proof_without_v_sign"), more
    assert [no for no, _ in VR.proof_list(_row(st))] == [1, 2], (
        "整笔被拒之后盘上的证明清单变了", VR.proof_list(_row(st)))

    taken = b.register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1},
                       {"proof_no": 2, "text": P2 + "\n（换了一个版本）"}])
    assert taken["ok"] is False and taken["kind"] in (
        "proof_manuscript_required", "proof_without_v_sign"), taken
    assert VR.proof_text_of(_row(st), 2) == P2, "既有 #p2 的正文不许被覆盖"

    canon = b.register_statement(**OWN, proof_text=P1 + "\n（换了一个版本）")
    assert canon["ok"] is False and canon["kind"] in (
        "proof_manuscript_required", "proof_without_v_sign"), canon
    row_now = _row(st)
    assert row_now["proof_text"] == P1, row_now["proof_text"]
    assert not (row_now.get("proof_history") or []), row_now.get("proof_history")
    # 盘上原样 + 台账不增行（三笔都整笔不写）。
    assert row_now == before, (row_now, before)
    assert _ledger(st) == [], _ledger(st)


# ============================================================ ④ 签名带对象
@pytest.mark.usefixtures("signed_v_handoffs")
def test_signing_proof_two_records_the_object_in_the_signature_line(tmp_path):
    """④ 签 `(命题, proof_no=2)` 三票 ⇒ 台账行 `stmt_id` 非空、`proof_no=2`、sha 是 #p2 的。

    这一条钉的正是"真机把 `stmt_id` 写成了 None"那个缺口：签名行必须自己说清
    "我签的是哪条命题的哪一份证明的哪一版正文"，三者一个都不能缺。票数按证明号分组
    （业主 2026-10-29），所以 #p2 要自己凑够 3 票才翻位。
    """
    st = _ws(tmp_path)
    _agent(st).register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])
    sid = _row(st)["stmt_id"]
    # 2026-11-03（87 的漏洞）：入场那笔的 #p1 是"签过才写得进来"的（准入闸），所以
    # 它现在会带着自己的签（`reviewed_by_proof` 里为真）。这一条要量的不是"#p1 没签"，
    # 而是"这一笔写回只翻被签的那一份" —— 于是先记下 #p1 的原值，签完 #p2 之后
    # #p1 必须一个字都没变，而 #p2 从假翻真。
    before = EB.reviewed_by_proof(_row(st))
    assert before.get(2) is not True, before

    signed = _sign_n(st, text=P2, proof_no=2)
    assert signed["stmt_id"] == sid, signed
    assert signed["statement_id"] == sid, signed
    assert signed["proof_no"] == 2, signed
    assert signed["proof_sha256"] == VR.text_sha(P2), signed
    assert signed["proof_sha256"] != VR.text_sha(P1), "签的是 #p1 的正文就算错了"

    disk = _ledger(st)[-1]
    assert disk["stmt_id"] == sid and disk["statement_id"] == sid, disk
    assert disk["proof_no"] == 2, disk
    assert disk["proof_sha256"] == VR.text_sha(P2), disk
    # 写回只翻被签的那一份：#p1 的原值原样保留（它排在前面也不借光、也不被顺手改掉）。
    wb = signed["statement_writeback"]
    assert wb["written"] is True and wb["rolled_back"] is False, wb
    assert wb["proof_no"] == 2 and wb["statement_id"] == sid, wb
    after = EB.reviewed_by_proof(_row(st))
    assert after == {1: True, 2: True}, (after, _row(st)["bits"])
    assert after.get(1) == before.get(1), ("#p1 被这一笔顺手改了", before, after)


# ============================================================ ⑤ 负控：不许借光

def test_proof_two_does_not_borrow_proof_ones_signature(tmp_path):
    """⑤ 只签 #p1 ⇒ `#p2` 的 reviewed 为 False，而定理级 `bits.reviewed` 仍为 True。

    期望反转（准入闸变严：无签不再可写）：首登带一份无签的 `#p2` ⇒ 整笔
    `proof_without_v_sign`，盘上零行、台账零行（改前：`ok=True`，两条证明一起落盘）。
    要读"不借光"的那一行，现场按历史形态铺行（真机多证明行同形）。

    两层都要判：
    - 写侧的逐条表 `bits.evidence.reviewed_by_proof`（业主点名的那一格）；
    - 读侧的逐条读数（`statement_review_reading`）—— #p2 自成一档，档位不许被 #p1 抬起来。

    负控再加一层（业主 2026-10-29）：#p1 只投 1 票时它自己也不算签上（连续 3 次才发签），
    而 #p2 从头到尾一张票都没有 —— 借光这一条在"一票"与"三票"两种票数下都要成立。
    """
    st = _ws(tmp_path)
    refused = _agent(st).register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])
    assert refused.get("ok") is False, refused
    # 2026-11-04：首登不带 `proof_manuscript` ⇒ 先撞"必须带稿"这一档；
    # 带稿而没有 #p2 的手稿签 ⇒ `proof_without_v_sign`。两档都不落盘，
    # 这一条要判的"无签的 #p2 写不进去"两档都成立。
    assert refused.get("kind") in ("proof_manuscript_required",
                                   "proof_without_v_sign"), refused
    assert st.rows("statements") == [], "整笔被拒之后盘上多了行"
    assert _ledger(st) == [], "整笔被拒之后台账多了行"

    seeded = seed_statement_row(
        st, proof_text=P1, statement_full=OWN["statement_full"],
        statement_text=OWN["statement_text"], kind="conjecture",
        label="弦长函数不是常值", origin="own_result", doc_id=S.format_id(0),
        quote_reason=OWN["quote_reason"],
        proofs=[{"proof_no": 2, "text": P2, "created_at": S.now_iso()}],
        bits=EB.with_optimized_defaults(
            EB.bits_of(origin="own_result", proof=True, proof_process=P1,
                       kind="conjecture"), [1, 2]))
    sid = str(seeded["stmt_id"])
    one = _sign(st, text=P1, proof_no=1)
    assert dict(one.get("statement_writeback") or {}).get("written") is False, one
    assert EB.reviewed_by_proof(_row(st)) == {}, (
        "一票就把逐条表写成签上了（连续 3 次才发签）", _row(st)["bits"])
    assert EB.bits_from_row(_row(st))["reviewed"] is False, _row(st)["bits"]

    signed = _sign_n(st, text=P1, proof_no=1)
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
    # #p1 的 4 票（先 1 票、再 3 票）是自己的，不许算到 #p2 头上（逐条连续读数各数各的）。
    p1 = next(p for p in reading["proofs"] if p["proof_no"] == 1)
    assert p1["streak"] == 4 and p1["streak_ok"] is True, p1
    assert p2["streak"] == 0 and p2["streak_ok"] is False, p2


# ============================================================ ⑥ 哈希不是门锁

@pytest.mark.usefixtures("signed_v_handoffs")
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
    signed = _sign_n(st, text=P1, proof_no=1)
    sha_at_sign = signed["proof_sha256"]
    assert sha_at_sign == VR.text_sha(P1)

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
    assert disk["proof_sha256"] != VR.text_sha(edited), disk
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
