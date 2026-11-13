# -*- coding: utf-8 -*-
"""判据：证明的两阶段录入（业主 2026-11-02 口径，draft/179 的「二之一」）。

## 这一份钉的七件事（每件都能单独红）

| # | 判据 | 它守的是哪句话 |
|---|---|---|
| ① | 首登就把那一份证明标成 optimized=false | 「加一格记录证明是否已优化，要匹配一命题多证明的设计（二维布尔）」 |
| ② | optimized 是三态：true / false / not_recorded | 缺格折成 false 会让存量 3134 行一次全变「等洗」 |
| ③ | 引用命题（external_lit 且逐字核过）不再把第 3 位读成已签 | 「V 签位填文献编号 = 假 V 签……汇总位不许把占位签读成已签」 |
| ④ | D 清单点名的那份稿，正文要落进 proof_text | 「F 侧实际上是 D 侧，F 的东西都在 D 的手稿上记了一笔」 |
| ⑤ | 同一份证明重交不算「同种证明」 | 22:03:20 那次 proofs=1 被 proof_same_kind 拒（相似度 1.0000） |
| ⑥ | 收工门按 optimized 加来源分三档 | unoptimized_from_f / unoptimized_from_lit / 读不出来那一档 |
| ⑦ | MAPPING 显示优化态与来源 | 论文对应表要看得出这一份是占位签还是等洗 |

## 为什么这些判据长这样

- ① 与 ② 钉的是写者与三态：格子的位置照 bits.evidence.reviewed_by_proof
  （evidencebits.py），不另造表；缺格与 false 必须分得开，否则「旧行」与「新录未洗」同形。
- ③ 钉的是假绿：bits_of 原先把 reviewed 写成 bool(reviewed) or cited，于是「文献编号顶
  第 3 位」被读成已签，等级直接 pre_theorem（真机 mp3 的 000000 到 000003 就是这样）。
  占位签的凭据仍留在 evidence.reviewed_by（lit:…），只是不许把汇总位翻真。
- ④ 钉的是主路：D 的携带单里点了名的那份稿，收方读稿那一支只写依赖边，命题行一个字不动
  ⇒ 正文只能靠模型手工粘。这一条要求「寻址到的正文落成 proof_text」。
- ⑤ 钉的是回执的谎：record_statement 的 create 分支把 proof_no 留成 0，B 据此以为
  「证明号是 0」，再拿 proofs=[#1] 去修，撞上「与在册 #1 同种（相似度 1.0）」。
- ⑥ 钉的是三档都要：把读不出的折成 from_f 就是把几千行旧行记成「F 刚产出」。

全部 tmp 工作区、零模型调用，不读写 projects/。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from conftest import add_literature, b_form_gate_ok, sync_counters, TS  # noqa: E402

from agentflow import closing  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import papermapping as PM  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402

STATEMENT = "设 G 是 3-正则群；则弦长函数不是常值。"
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n ≥ 3 得结论。"
OWN = {
    "statement_full": STATEMENT,
    "statement_text": "弦长函数不是常值",
    "origin": "own_result",
    "kind": "conjecture",
    "doc_id": S.format_id(0),
    "quote_reason": "我方自产命题，没有外部引文要比对",
}


# ------------------------------------------------------------------ 小工具

def _agent(store) -> AgentB:
    return b_form_gate_ok(AgentB(
        store, extractor=None, extract_text=None, config={}))


def _row(store, stmt_id: str = "") -> dict:
    rows = [dict(r) for r in store.rows("statements")]
    if stmt_id:
        return next(r for r in rows if str(r.get("stmt_id")) == stmt_id)
    return rows[0]


def _statement_row(**over) -> dict:
    """一条合法的 statements 行（bits 由调用方给全，便于构造三档来源）。"""
    body = {
        "stmt_id": S.format_id(0), "origin": "own_result", "kind": "conjecture",
        "label": "L", "statement_text": "短版", "statement_full": STATEMENT,
        "proof_text": P1, "status": "active", "created_at": TS, "created_by": "agent-B",
        "quote_verified": True, "quote_mode": "verbatim", "quote_span": "p1:norm[0:10]",
        "quote_reason": "逐字比对通过（夹具）",
        "bits": {}, "derived_from": [], "aliases": [],
    }
    body.update(over)
    return body


def _put(store, row: dict) -> dict:
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


# ============================================================ ① 首登：optimized=false

def test_a_fresh_intake_marks_its_only_proof_unoptimized(store, signed_v_handoffs):
    """① 机械录入一笔 ⇒ 那一份证明被显式标成未优化（不是「缺这一格」）。

    为什么必须显式：第二阶段只看这一格（「若为否……总之都要洗一遍」）。缺格与 false
    在盘上同形，会让「旧行」被读成「新录未洗」，于是收工门的三档数不出来。
    """
    out = _agent(store).register_statement(**OWN, proof_text=P1)
    assert out["ok"] is True, out

    row = _row(store)
    ev = dict(row["bits"].get("evidence") or {})
    assert ev.get(EB.OPTIMIZED_BY_PROOF_KEY) == {"1": False}, ev
    # 读口：只有「记过的那几份」在表里，读出来是布尔。
    assert EB.optimized_by_proof(row) == {1: False}
    # #p2 没这一份 ⇒ 不是 false，是「没有记录」（三态，见 ②）。
    assert EB.optimized_state(row, 2) == "not_recorded"
    # 逐份的「审过」表只该有 #1（准入闸要求的那一份签），不许「顺手」记上没签的 #2。
    # 2026-11-02 准入闸默认 strict：新命题要交证明正文就必然带着一份覆盖它的签，
    # 于是这张表里有 #1 是那一签的正常留痕（`reviewed_by_proof` 是签的落点）；
    # 改前这里断言"表是空的"，那是"无签也能入台账"的旧前提。判据的真身没变：
    # 没签过的那几份（#2）一个键都不许有。
    reviewed_by_proof = dict(dict(row["bits"].get("evidence") or {})
                             .get("reviewed_by_proof") or {})
    assert sorted(reviewed_by_proof) == ["1"], row["bits"]
    assert dict(out.get("v_sign") or {}).get("applied") is True, out.get("v_sign")


def test_the_optimized_flag_follows_one_proof_number_at_a_time(store, signed_v_handoffs):
    """① 的多证明那一半：一条命题两份证明 ⇒ 两格各记各的，互不借光。

    2026-11-02（准入闸 strict）之后这一笔的真实次序是两步：命题先入册（证明空着）、
    两份各自签过再交正文。`#p1` 因此走的是"换 canonical 正文"那一笔 ——
    `_attach_proofs` 明写着"翻真只发生在换正文那一笔" ⇒ 它是 True；`#p2` 是这次
    新挂上来的机械录入版 ⇒ False。判据的真身没变：两格各记各的（不是一格管两号）。
    """
    out = _agent(store).register_statement(
        **OWN, proofs=[{"proof_no": 1, "text": P1},
                       {"proof_no": 2, "text": "另一条路线：\n1. 先证引理。\n2. 收尾。"}])
    assert out["ok"] is True, out
    row = _row(store)
    assert EB.optimized_by_proof(row) == {1: True, 2: False}, row["bits"]["evidence"]


# ============================================================ ② 三态

def test_optimized_is_three_state_and_a_missing_cell_is_not_false(tmp_path):
    """② 三态：true / false / not_recorded；缺格不许被读成 false（也不许读成 true）。

    存量 3134 行 own_result 都没有这一格 —— 折成 false 会让收工门当场把整库记成
    「等洗」；折成 true 更坏（等于自报洗过）。
    """
    from agentflow.store import Store
    st = Store(tmp_path / "ws")
    st.init()
    # 旧行：bits 里根本没有这一格。
    _put(st, _statement_row(bits=EB.bits_of(origin="own_result", proof=True,
                                            proof_process=P1, kind="conjecture")))
    row = _row(st)
    assert EB.OPTIMIZED_BY_PROOF_KEY not in (row["bits"].get("evidence") or {})
    assert EB.optimized_state(row, 1) == "not_recorded"
    assert EB.optimized_by_proof(row) == {}

    # 两种记录过的那一档各读各的。
    #
    # 2026-11-03（87 的漏洞）：`optimized_state` 现在读的是"能不能声称已优化" ——
    # 记着 true 的那一份必须真有签、且那一签盖的是现在这一份正文（判据只在
    # `evidencebits.optimized_signature`）。所以这一格把 #2 的正文与它的签一起铺上：
    # 没有签的 true 是这次要挡的那一档，不该出现在"三态读得对"的夹具里。
    p2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
    bits = dict(row["bits"])
    ev = dict(bits.get("evidence") or {})
    ev[EB.OPTIMIZED_BY_PROOF_KEY] = {"1": False, "2": True}
    ev[EB.REVIEWED_BY_PROOF_KEY] = {"1": True, "2": True}
    ev[EB.REVIEWED_SHA_BY_PROOF_KEY] = {"1": VR.text_sha(P1), "2": VR.text_sha(p2)}
    bits["evidence"] = ev
    _put(st, dict(row,
                  proofs=[{"proof_no": 2, "text": p2, "created_at": TS}],
                  bits=EB.normalize_raw(bits, origin="own_result", kind="conjecture")))
    row2 = _row(st)
    assert EB.optimized_state(row2, 1) == "false"
    assert EB.optimized_state(row2, 2) == "true"
    assert EB.optimized_state(row2, 3) == "not_recorded"
    # 三态是一个受控词表（R011 的死取值普查认它）。
    assert set(EB.OPTIMIZED_STATES) == {"true", "false", "not_recorded"}

    # 反真空（与 87 同形）：把 #2 的签拆掉 ⇒ 盘上那一格仍是 true，而"能不能声称"
    # 变成 false + no_sign。没有这一条，上面的 true 可能来自"只读那一张表"。
    bare = dict(row2)
    assert EB.optimized_by_proof(bare) == {1: False, 2: True}
    bare_bits = dict(bare["bits"])
    bare_ev = dict(bare_bits.get("evidence") or {})
    bare_ev[EB.REVIEWED_BY_PROOF_KEY] = {"1": True}
    bare_bits["evidence"] = bare_ev
    bare["bits"] = EB.normalize_raw(bare_bits, origin="own_result", kind="conjecture")
    standing = EB.optimized_standing(bare, 2)
    assert standing["state"] == "false", standing
    assert standing["optimized_blocked"] == EB.OPTIMIZED_BLOCKED_NO_SIGN, standing


# ============================================================ ③ 占位签不翻汇总位

def test_a_cited_literature_row_is_not_read_as_signed(store):
    """③ 引用命题（文献编号顶第 3 位）⇒ bits.reviewed 仍是 False，等级不许到预告级。

    业主 2026-11-02：「文献侧第一趟录入时没有V签，是假V签，但要允许进台账」加
    「bits.reviewed 的汇总位不许把占位签读成已签」。
    凭据不许丢：evidence.reviewed_by 里仍写着 lit:<编号>（那是寻址与复核的依据）。
    """
    bits = EB.bits_of(origin="external_lit", source_lit_id="000004",
                      quote_verified=True, proof_process="", kind="theorem")
    assert bits["proof"] is True, bits          # 第 2 位仍按「引用」算有证明
    assert bits["reviewed"] is False, bits      # 第 3 位：占位签不算签
    ev = dict(bits.get("evidence") or {})
    assert str((ev.get("reviewed_by") or {}).get("evidence") or "") == "lit:000004", ev
    assert ev.get("reviewed_source") == "citation", ev
    # 等级：只有第 2 位 ⇒ 猜想（改前是 pre_theorem —— 那一档正是「假绿」）。
    assert bits["grade"] == "conjecture", bits

    # 正控的另一半：真签（V 走过的）仍然翻位。
    signed = EB.bits_of(origin="own_result", proof=True, proof_process=P1,
                        reviewed=True, kind="theorem")
    assert signed["reviewed"] is True, signed
    assert dict(signed.get("evidence") or {}).get("reviewed_source") == "v", signed


# ============================================================ ④ D 清单的正文落进 proof_text

def _write_manuscript(store, stmt_id: str, body: str) -> pathlib.Path:
    """按框架形态写一份 F 的证明手稿（带命题号与洗稿元信息），再写 D 的报告。"""
    text = (f"# F 的证明手稿：{STATEMENT}\n"
            f"\n- 命题号：stmt:{stmt_id}\n- 计划：000002 · 子目标：a\n"
            "\n## 命题\n\n" + STATEMENT + "\n"
            "\n## 证明\n\n" + body + "\n"
            "\n## 依赖\n\n"
            "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
            "|---|---|---|---|\n\n（自足证明，空表就是声明。）\n")
    text = DS.mark_washed(text, actor="secretary-F")
    rel = pathlib.Path("reports") / f"f-proof-{stmt_id}.md"
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    carried = DS.render_carried_section(
        [{"statement_id": stmt_id, "path": rel.as_posix(), "sha256": sha}])
    report = pathlib.Path(store.root) / "reports" / "000001-research.md"
    report.write_text("# 研究手稿\n\n" + carried, encoding="utf-8")
    return path


def test_the_carried_manuscript_body_lands_in_proof_text(store):
    """④ B 按 D 清单寻址拿到的稿正文，要落进 proof_text（proof_text_source=manuscript）。

    形态照真机：命题先登记（机械录入，证明还空着），D 的研究手稿随后带一张携带单
    （携带的证明手稿：命题号 → 手稿路径 → 文件 sha256）。这一笔没有 proof_text、
    也没有 proof_manuscript —— 正文只能从清单寻址来的那份稿里取。

    改前：carries_canonical_write 只比入参 proof_text（空）⇒ 判 False ⇒ 走
    「收方读稿登记」早退支路，命题行一个字不动（真机 85 的 13 条就是这样「收下但没写」）。
    """
    b = _agent(store)
    first = b.register_statement(**{**OWN, "proof_text": ""})
    assert first["ok"] is True, first
    sid = first["stmt_id"]
    assert not str(_row(store, sid).get("proof_text") or "").strip()

    body = "1. 取二维输入 z^(0)=(x,0)^T。\n2. 逐层复合得到结论。"
    _write_manuscript(store, sid, body)

    # 准入闸（2026-11-02 strict）：从稿里取出来的那一份正文也要先有签
    # （命题已在册 ⇒ 走该命题台账）。2026-11-03（87 的漏洞）之后"有签"不再只是
    # `_signature_covers` 的 `holding` 一档：换正文要打 `optimized=true`，而那一格
    # 要求 `reviewed_by_proof` / `reviewed_sha_by_proof` 真的在 —— 一票（holding）
    # 不落这两格，所以这里按发签门槛签满（`SIGN_STREAK_NEED` 次「成立」，并传
    # `store` 让签文件真的发出来）。
    from conftest import sign_for_the_gate

    sign_for_the_gate(store.root, statement_id=sid, proof_text=body, store=store)
    got = b.register_statement(**{**OWN, "proof_text": ""})
    assert got["ok"] is True, got
    assert got.get("proof_text_source") == "manuscript", got
    row = _row(store, sid)
    assert str(row.get("proof_text") or "").strip() == body, row.get("proof_text")
    # 落的是稿正文，不是整份稿（依赖与命题两节不许被粘进去）。
    assert "## 依赖" not in row["proof_text"], row["proof_text"]
    assert "## 命题" not in row["proof_text"], row["proof_text"]
    # 依赖面那一支照旧：读数在，且这一笔没有被当成「新建一行」。
    assert got.get("new_row") is False, got


# ============================================================ ⑤ 同一份正文重交

def test_resubmitting_the_same_proof_is_not_a_same_kind_refusal(
        store, signed_v_handoffs, tmp_path, monkeypatch):
    """⑤ 同一份正文重交 ⇒ 不新增证明号，也不许报 proof_same_kind。

    真机 22:03:20（projects/paper-rewrite-85/sessions/20261102.jsonl:2980）：
    B 为了把 proof_no 落成 1，拿 proofs=[{proof_no:1, text: 同一份正文}] 重交 ⇒
    「与 stmt:000012 的第 #1 份证明同种（相似度 1.0000 >= 阈值 0.80）」⇒ 整笔拒。
    同一份正文与自己同种不是「第二种证法」——那是同一条记录再交一次。

    ## 2026-11-04（件1 收口之后重判）：这一笔的「并」要模型说，而这一条没有缝

    改前这一段期望「更新在册 000000」。件1 之后「没查成 ⇒ 不并（词面相似度只排序、
    不决定并）」是业主裁定的正确行为，而本用例的两笔都没有提供模型缝
    （`_agent(store)` 造出来的秘书 `adjudication.checked=False`、`fail_closed=True`），
    这一对的确定性键又不同（`不是常值` / `不为常值`、`依赖` / `依赖于`）⇒
    fail-closed 只能落新行。所以「更新 000000」这条期望过时，改成钉
    「落新行 + 三态读数」；原意（同一份正文重交不许报 proof_same_kind、证明号不许
    多出第 2 号）一个字不改。

    但光改期望会把它改松（那就成了「fail-closed 什么都不并」的同谋）：同一条用例
    末尾另起一个工作区做正控 —— 输入一个字不改，只给一条「模型判 same」的缝 ⇒
    必须更新 000000、proof_no 仍是 1。
    """
    long_a = ("设 G 是 3-正则群，且 H 是 G 的子群；则弦长函数不是常值，"
              "且它的下界只依赖 G 的度数。")
    long_b = ("设 G 是 3-正则群，且 H 是 G 的子群；则弦长函数不为常值，"
              "且它的下界只依赖于 G 的度数。")
    own_a = {**OWN, "statement_full": long_a, "statement_text": "弦长函数不是常值"}
    own_b = {**OWN, "statement_full": long_b, "statement_text": "弦长函数不是常值"}

    # 夹具前提：这一对的确定性键不同（「键相同 ⇒ 仍并」那一档救不了它），而词面
    # 相似度 0.9651 ≥ 0.85 —— 改前正是这一档把它并成一行（改后的读数会点名这两个数）。
    from agentflow import propositionkey as PK

    assert PK.proposition_key(long_a) != PK.proposition_key(long_b), (
        "夹具前提：这一对的确定性键不同（所以只有词面相似度那一档会并）")
    verdict = PK.same_proposition(long_a, long_b)
    assert verdict["state"] == PK.STATE_SAME, verdict
    assert float(verdict["similarity"]) >= PK.SAME_PROPOSITION_JACCARD, verdict

    b = _agent(store)
    first = b.register_statement(**own_a, proof_text=P1)
    assert first["ok"] is True, first
    sid = first["stmt_id"]
    assert sid == S.format_id(0), first

    again = b.register_statement(**own_b, proofs=[{"proof_no": 1, "text": P1}])
    assert again["ok"] is True, again
    assert again.get("kind") != "proof_same_kind", again
    # 2026-11-04：没查成 ⇒ 不并。新落一行 `000001` —— 它不是「在册那一条的第 2 份
    # 证明」，而是「一条新命题的第 1 份证明」：证明号仍是 1，没有多出第 2 号。
    assert str(again.get("stmt_id") or "") == S.format_id(1), again
    assert int(again.get("proof_no") or 0) == 1, again
    # 读数：没查成不许折成「查过了、不同」，也不许折成「并进去了」。
    adj = dict(again.get("adjudication") or {})
    assert adj.get("checked") is False, adj
    assert adj.get("fail_closed") is True, adj
    why = str(adj.get("why_not_merged") or "")
    assert f"stmt:{sid}" in why, why
    assert "0.9651" in why, why          # 点名那一对的实际相似度（读的人才核得动）
    assert "不决定并" in why, why
    # 证明号没有因此多出来一条：两行各自只有 #1。
    assert [no for no, _ in VR.proof_list(_row(store, sid))] == [1], VR.proof_list(_row(store, sid))
    assert [no for no, _ in VR.proof_list(_row(store, S.format_id(1)))] == [1], (
        VR.proof_list(_row(store, S.format_id(1))))
    assert len(store.rows("statements")) == 2, store.rows("statements")

    # ================================================ 正控：给模型缝 ⇒ 必须更新 000000
    #
    # 同一笔输入（long_b + 同一份正文 P1），只多一条「模型判 same」的缝。打桩打的是
    # 判据入口 `adjudicate_proposition`（模型的结论在真机上就是从这一处返回的），
    # 不是兜底那一档。这一格要证明：fail-closed 关掉的只是「没查成」那一档，
    # 「查成了、判 same」仍然并得进在册那一条。
    from agentflow.secretary import MERGED_BY_ADJUDICATION, Secretary
    from agentflow.store import Store

    pos = Store(str(tmp_path / "model-same-ws"))
    pos.init()
    pos_b = b_form_gate_ok(AgentB(
        pos, extractor=None, extract_text=None, config={}))
    pos_first = pos_b.register_statement(**own_a, proof_text=P1)
    assert pos_first["ok"] is True, pos_first
    pos_sid = str(pos_first.get("stmt_id") or "")
    assert pos_sid == S.format_id(0), pos_first

    def _model_says_same(self, stmt_like, **_kw):
        return {"checked": True, "verdict": PK.STATE_SAME, "same_as": pos_sid,
                "basis": "打桩：条件组与结论组一致", "canonical_name": "", "route": "",
                "condition": "打桩：条件未读", "conclusion": "打桩：结论未读",
                "reason": "打桩：模型判 same", "candidates": [], "cost": {},
                "reused": False, "cached": False, "statement_sha256": "",
                "attempted": True, "seam_source": "打桩"}

    monkeypatch.setattr(Secretary, "adjudicate_proposition", _model_says_same)
    merged = pos_b.register_statement(**own_b, proofs=[{"proof_no": 1, "text": P1}])
    assert merged["ok"] is True, merged
    assert str(merged.get("stmt_id") or "") == pos_sid, merged
    assert merged.get("kind") != "proof_same_kind", merged
    assert int(merged.get("proof_no") or 0) == 1, merged
    assert merged.get("matched_by") == MERGED_BY_ADJUDICATION, merged
    pos_rows = [dict(r) for r in pos.rows("statements")]
    assert len(pos_rows) == 1, pos_rows
    assert [no for no, _ in VR.proof_list(pos_rows[0])] == [1], VR.proof_list(pos_rows[0])


def test_a_created_statement_reports_proof_no_one(store, signed_v_handoffs):
    """⑤ 的回执那一半：首登（只给 proof_text）的回执要说 proof_no=1。

    canonical 就是 #p1（verifications.proof_list 恒含 (1, proof_text)）。
    回执说 0 ⇒ 模型以为要修（真机就是因此去重交、撞 proof_same_kind 的）。
    """
    out = _agent(store).register_statement(**OWN, proof_text=P1)
    assert out["ok"] is True, out
    deps = dict(out.get("deps_missing") or {})
    assert int(deps.get("proof_no") or 0) == 1, deps


# ============================================================ ⑥ 收工门三档

def _lit_row(**over) -> dict:
    bits = EB.bits_of(origin="external_lit", source_lit_id="000004",
                      quote_verified=True, kind="theorem")
    body = _statement_row(origin="external_lit", source_lit_id="000004",
                          kind="theorem", proof_text="Theorem 1 (原文).", bits=bits)
    body.update(over)
    return body


def test_the_closing_gate_splits_unoptimized_by_source(store):
    """⑥ 收工门按 optimized 加来源分三档，且三档之和 == 逐条数。

    - unoptimized_from_f：proof_source == "own" 且 optimized 不是 true；
    - unoptimized_from_lit：proof_source == "citation"；
    - unoptimized_source_not_recorded：来源读不出来（存量那种）—— 不许折成 from_f。
    已优化的那一份不进任何一档。
    """
    add_literature(store, "000004")
    # A：F 侧刚产出（未洗）
    a = _statement_row(stmt_id=S.format_id(0),
                       bits=EB.bits_of(origin="own_result", proof=True,
                                       proof_process=P1, kind="conjecture"))
    # B：文献侧录入（占位签 = 文献编号，未优化）
    b = _lit_row(stmt_id=S.format_id(1))
    # C：来源读不出来（旧行：bits 为空）
    c = _statement_row(stmt_id=S.format_id(2), bits={}, proof_text="")
    sync_counters(store)
    _put(store, a)
    _put(store, b)
    _put(store, c)

    got = closing.statements_unoptimized_reading(store)
    assert got["checked"] is True, got
    assert int(got["scanned"]) == 3, got
    by = dict(got["by_class"] or {})
    assert sum(int(v) for v in by.values()) == 3, by
    assert by.get("unoptimized_from_f") == 1, by
    assert by.get("unoptimized_from_lit") == 1, by
    assert by.get("unoptimized_source_not_recorded") == 1, by
    classes = {str(r["stmt_id"]): str(r["class"]) for r in (got.get("rows") or [])}
    assert classes[S.format_id(0)] == "unoptimized_from_f", classes
    assert classes[S.format_id(1)] == "unoptimized_from_lit", classes
    assert classes[S.format_id(2)] == "unoptimized_source_not_recorded", classes

    # 正控：把 A 标成已优化 ⇒ 它退出这三档，逐条数减一。
    # 2026-11-03（87 的漏洞）：`optimized=true` 要真有签才作数（`optimized_state` 现在
    # 走 `optimized_standing`）⇒ 夹具把 A 那一份的签一起铺上，否则这一笔只是"记着
    # true、没有签"，收工门会（正确地）继续把它算成欠洗。
    row = _row(store, S.format_id(0))
    bits = dict(row["bits"])
    ev = dict(bits.get("evidence") or {})
    ev[EB.OPTIMIZED_BY_PROOF_KEY] = {"1": True}
    ev[EB.REVIEWED_BY_PROOF_KEY] = {"1": True}
    ev[EB.REVIEWED_SHA_BY_PROOF_KEY] = {"1": VR.text_sha(P1)}
    bits["evidence"] = ev
    _put(store, dict(row, bits=EB.normalize_raw(bits, origin="own_result",
                                               kind="conjecture")))
    assert EB.optimized_state(_row(store, S.format_id(0)), 1) == "true"
    again = closing.statements_unoptimized_reading(store)
    assert int(again["count"]) == 2, again
    assert S.format_id(0) not in {str(r["stmt_id"]) for r in again["rows"]}, again["rows"]


def test_the_closing_reading_says_when_it_could_not_be_read(store, monkeypatch):
    """⑥ 的三态：statements 读不出来 ⇒ checked=False（不是「一条都不欠洗」）。"""
    def _boom(*a, **k):
        raise RuntimeError("台账读不出来")
    monkeypatch.setattr(store, "rows", _boom)
    got = closing.statements_unoptimized_reading(store)
    assert got["checked"] is False, got
    assert "没查成" in str(got.get("reason") or ""), got


# ============================================================ ⑧ 准入闸：无签的证明正文

def _strict(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_UNSIGNED_PROOF_INTAKE", "strict")


def test_an_unsigned_proof_body_is_refused_on_every_source(store, monkeypatch):
    """⑧ 准入闸（业主 2026-11-02 第 5 条）：没有签的证明正文不许进台账，不看来源。

    这一条钉的是父批次点出的那条活口：`source=param`（F 的进程内直交）此前「放行」
    —— 85 的 13 条里 11 条至今无签，正是从这条路进来的。判据与 kind 无关
    （猜想不是免签通行证）、与来源无关（param / carried_by_D / disk 一样）。
    """
    _strict(monkeypatch)
    st = store
    out = _agent(st).register_statement(**OWN, proof_text=P1,
                                        proof_manuscript=P1)
    assert out["ok"] is False, out
    assert out["kind"] == "proof_without_v_sign", out
    # code + 原因 + 建议：三样都要能读到（模型据此改参数）。
    assert "没有一份覆盖它的 V 签" in str(out.get("error") or ""), out
    assert "verify.verify_proof" in str(out.get("error") or ""), out
    gate = dict(out.get("proof_gate") or {})
    assert gate.get("applicable") is True, gate
    assert gate.get("missing") == [1], gate
    assert gate.get("proofs") and gate["proofs"][0]["signed"] is False, gate
    # 整笔不写：一行都没有。
    assert st.rows("statements") == [], st.rows("statements")


def test_with_the_gate_removed_the_unsigned_body_goes_green(store, monkeypatch):
    """⑧ 的反真空：把闸摘掉（`relaxed`）⇒ 上一条那笔无签登记「会」写成。

    为什么必须有这一条（业主：反真空）：只断言"strict 下被拒"是不够的 —— 一个恒拒的
    闸也能让上一条绿。这一条把同一个夹具、同一份正文放到"闸摘掉"那一档，登记必须
    成功落行：两档的差别证明上一条的拒收确实来自这条闸，而不是别的闸顺手挡的。
    """
    monkeypatch.setenv("AGENTFLOW_UNSIGNED_PROOF_INTAKE", "relaxed")
    out = _agent(store).register_statement(**OWN, proof_text=P1, proof_manuscript=P1)
    assert out.get("ok") is True, out
    assert store.rows("statements"), "闸摘掉之后仍然一行都没写 ⇒ 反真空这一条自己失效了"


def test_the_literature_placeholder_sign_is_the_only_unsigned_door(store, monkeypatch):
    """⑧ 唯一的免签门：文献侧占位签（external_lit + 文献编号）仍然允许入台账。

    业主二之二：「文献侧第一趟录入时没有V签，是假V签，但要允许进台账」。
    这条与上一条是同一个闸的两侧 —— 只拒"没有签也没有文献编号"的那一类。
    """
    _strict(monkeypatch)
    add_literature(store, "000004")
    out = _agent(store).register_statement(
        statement_full="Theorem 1.1（文献原话）", origin="external_lit",
        kind="theorem", source_lit_id="000004",
        page_range={"start": 1, "end": 2},
        quote_verified=True, quote_mode="verbatim",
        quote_span="p1:norm[0:20]", quote_reason="逐字比对通过",
        proof_text="Proof. 原文的证明。")
    assert out["ok"] is True, out
    row = _row(store)
    # 免签入台账了，但第 3 位仍是假（占位签不是签）：这一格里 `enforce_quote_evidence`
    # 因为没有铺全文而把"说通过"降成未查，所以 reviewed 那条链在本夹具上只到
    # "未签"；占位签本身的单元判据在 ③（`bits_of` 那一层）。
    assert dict(row.get("bits") or {}).get("reviewed") is False, row["bits"]
    # 优化态：文献侧机械录入那一版 = 未优化（第二阶段要洗的就是它）。
    assert EB.optimized_by_proof(row) == {1: False}, row["bits"]


# ============================================================ ⑦ MAPPING 的优化态

def test_mapping_shows_the_optimized_state(store):
    """⑦ 论文对应表那一格：已优化 / 未优化 / 未记录 三档，按证明号读。

    2026-11-03（87 的漏洞）之后"已优化"要真有签（`optimized_state` →
    `optimized_standing`）：#2 的正文与它的签表一起铺上，否则那一格会（正确地）
    读成"记着 true、没有签"⇒ 未优化 —— 那就不是这一条要量的三档了。
    """
    p2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
    row = _statement_row(bits=EB.bits_of(origin="own_result", proof=True,
                                         proof_process=P1, kind="conjecture"))
    bits = dict(row["bits"])
    ev = dict(bits.get("evidence") or {})
    ev[EB.OPTIMIZED_BY_PROOF_KEY] = {"1": False, "2": True}
    ev[EB.REVIEWED_BY_PROOF_KEY] = {"1": True, "2": True}
    ev[EB.REVIEWED_SHA_BY_PROOF_KEY] = {"1": VR.text_sha(P1), "2": VR.text_sha(p2)}
    bits["evidence"] = ev
    _put(store, dict(row,
                     proofs=[{"proof_no": 2, "text": p2, "created_at": TS}],
                     bits=EB.normalize_raw(bits, origin="own_result",
                                           kind="conjecture")))

    ledger = _row(store)
    assert PM.optimized_cell(ledger, 1) == PM.OPTIMIZED_NO, PM.optimized_cell(ledger, 1)
    assert PM.optimized_cell(ledger, 2) == PM.OPTIMIZED_YES
    assert PM.optimized_cell(ledger, 3) == PM.OPTIMIZED_UNKNOWN
    # 读不到行 / 号认不出 ⇒ 未读到（三态，不折成「未优化」）。
    assert PM.optimized_cell(None, 1) == PM.LEDGER_CELL_UNREADABLE

    rows = [PM.Row(kind="theorem", label="主定理", env_no=1,
                   ledger_id=f"stmt:{S.format_id(0)}", proof_no=1, file="main.tex",
                   optimized=PM.OPTIMIZED_NO, proof_source="own")]
    text = PM.render_mapping_markdown(rows)
    assert PM.OPTIMIZED_FIELD in text, text
    assert PM.OPTIMIZED_NO in text, text
