# -*- coding: utf-8 -*-
"""V 侧审查必须核实 F 报告的引用（业主 2026-10-26 裁定，两批合并后的口径）。

## 业主原话（唯一权威）
```
「V侧审查也应对F报告的引用进行核实（F引用可能非逐字，需要V自行判断）」
「正常写证明就是不会逐字的」
「proof_review级及以上才可引用」
```

## 这一组钉的是什么
改前 `verify.verify_proof` 只审"证明正文本身"（逐行查假设、步骤、缝），完全不看 F
记了哪些依赖 ⇒ F 可以引一条与所证无关的命题、把某条命强的话说弱/说强、或拿一条
`cross_check` 级的东西当依据，而 V 签字时看不见。改后：

1. V 的审查材料里有 F 对每条被引命题的说法（`dependencies` 那一档的
   `used_by` / `path_group` / `source_stmt_id` / 那一行的话）与被引命题的正文摘要
   —— 不是只给编号；
2. V 逐条给一档结论（`consistent` / `weaker` / `stronger` / `unrelated` /
   `inadmissible` / `unknown`），读数落进台账那一行的 `citation_checks`
   （`{stmt_id, verdict, quote_verbatim, note, in_material}`；`quote_verbatim` 只作信息、
   不参与判定；`in_material` 说明这一条是不是这一份证明登记的引用 —— 见文件末尾那两条
   "两个判定口必须同结论"的判据）；
3. 签字前置：有一条 `stronger` / `unrelated` / `inadmissible` / `unknown` ⇒ 不许签
   「成立」（结论改判 + 逐条点名）；`weaker` 可以签，但读数里点名"只用到了弱形式"；
4. 档位闸是事实不是判断：被引命题低于 `proof_review`（含空档）一律 `inadmissible`，
   允许集合从 `schema.EVIDENCE_KINDS` 现算（不写死字面量）。

## 判据与各自的"改前红"
| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 用法一致（措辞完全不同） | `consistent` 且照签 | 改前返回里没有 `citation_checks` 这一格（KeyError），而且 V 根本不看依赖面 |
| b 逐字引用但用法被夸大 | `stronger` 且签不成 | 改前照签「成立」（没有任何一处读被引命题） |
| c 引了一条无关命题 | `unrelated` 且签不成 | 同上 |
| d 反真空：核实打桩成恒 `consistent` | b / c 必红 | 打桩下 b / c 的断言正好取反（下面逐条断言"判据在打桩下不成立"） |
| e 引一条 `cross_check` 级的在册命题 | `inadmissible` 且签不成 | 改前只看用法，模型说"一致"就会放过 |
| f 反真空：档位闸打桩 | 恒放行 ⇒ e 必红；恒拒绝 ⇒ a 的正控必红 | 两端都打，证明"红"不是写死的 |

另加四条护栏（不属业主点名那五条，但同一条断链上的读数）：`weaker` 可签但点名、
`unknown` 不许签（结论仍是两态里的 `成立`，由引用闸挡住）、材料里有引用而 V 没给结论
按 `unknown`、另一份稿的依赖不进这一份稿的审查材料（依赖面按"被审的那一份稿"读，
不是按证明号从台账挑）；以及台账/读侧那两格的硬闸（`signs_bit3` 与 `bit3_payload`）。

全部 tmp 工作区、零模型调用（V 的模型缝用一个按剧本回答的替身，不花一分钱），
不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import sys
from types import SimpleNamespace
from typing import Any

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from _proof_manuscript_fixture import write_proof_manuscript

from agentflow import conductor as _CND
from agentflow import depsection as _DS
from agentflow import evidencebits as _EB
from agentflow import proofloc as PL
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as _VS
from agentflow.agent_b import AgentB
from agentflow.agent_v import AgentV
from agentflow.store import Store
from conftest import b_form_gate_ok  # noqa: E402

#: 被引命题（引理）与它的证明：V 先给它签过「成立」⇒ 它才够格是 `proof_review` 级。
LEMMA_FULL = "设 G 是有限 p-群且 p 整除 |G|。则 G 的中心 Z(G) 非平凡。"
LEMMA_PROOF = "1. 对 |G| 归纳。\n2. 取一个非平凡中心元。"
#: 正在被审的命题（主命题）与它的证明。
MAIN_FULL = "设 G 是阶为 p^2 的群（p 为素数）。则 G 是交换群。"
MAIN_PROOF = ("1. 由中心非平凡那一条（册子里的引理）取一个非平凡中心元 g。\n"
              "2. g 与所有元素交换 ⇒ G/Z(G) 循环。\n"
              "3. 循环商群 ⇒ G 交换。")
MAIN_PROOF_2 = ("另一条路线：\n1. 用类方程数共轭类。\n"
                "2. 由中心非平凡得中心至少 p 阶。\n3. 收尾。")
#: F 在依赖行上写的那句话（刻意与命题原文一个字都不同：正常写证明不会逐字）。
F_NOTE = "由中心非平凡那一条（就是这条引理）可知存在非平凡中心元"
F_QUOTE = "G 的中心 Z(G) 非平凡"


# ------------------------------------------------------------------ 夹具

class _Seam:
    """按剧本回答的替身模型缝（记录提示词，便于判"材料进没进审查材料"）。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def ask(self, prompt: str, **_kw: Any) -> Any:
        self.prompts.append(prompt)
        return SimpleNamespace(text=self.reply, problem="")



@pytest.fixture(autouse=True)
def _proof_kind_says_different(monkeypatch):
    """这一组量的是"V 核实 F 的引用"，不是"两份证明是不是同一套证法"。

    `709dd579` 把同种证明判定接进了收录主链（判不了 ⇒ `proof_kind_unjudged` ⇒ 不收录）。
    这组夹具里 `_register(..., proofs=[#p1, #p2])` 会走那条判定，而它没有装配判定面 ——
    于是第二份证明被拒、台账只剩一份，"另一条路径的依赖不进这一份的材料"这条就无从判起。
    这里给 `proof_kind` 一个明确的二态答案（`different`：两条路径是不同证法），
    其余 kind 原样透传真实现。断言一条没改。
    """
    from agentflow import secretary as _SEC
    real = _SEC.Secretary.judge

    def _judge(self, kind, *a, **kw):
        if str(kind) == "proof_kind":
            return {"checked": True, "decision": "different", "same_path": 0,
                    "reason": "", "basis": {}, "cost": {}}
        return real(self, kind, *a, **kw)

    monkeypatch.setattr(_SEC.Secretary, "judge", _judge)


def _ws(tmp_path: pathlib.Path) -> Store:
    store = Store(tmp_path / "ws")
    store.init()
    return store


def _register(store: Store, *, full: str, proof: str, proofs: list[dict] | None = None) -> str:
    """用 B 的动作登记一条在册命题（出处齐、可追溯；与既有夹具同一形态）。"""
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", {
            "lit_id": "000000", "title": "探针文献", "summary": "s", "year": "2022",
            "doi": "", "type": "J", "path": "", "processed": True, "source_request_ids": [],
            "download": {"status": "ok"},
        })
    b = b_form_gate_ok(AgentB(
        store, extractor=None, extract_text=None, config={}))
    kwargs: dict[str, Any] = dict(
        origin="external_lit", statement_full=full, kind="theorem",
        source_lit_id="000000", page_range={"start": 1},
        quote_verified=False, quote_reason="探针：引文还没查",
    )
    if proofs:
        kwargs["proofs"] = proofs
    else:
        kwargs["proof_text"] = proof
    got = b.register_statement(**kwargs)
    row = got if isinstance(got, dict) else got.to_dict()
    assert row.get("ok"), row
    return str(row.get("stmt_id") or "")


def _set_evidence_kind(store: Store, sid: str, kind: str) -> None:
    """把一条命题的 `evidence_kind` 设成判据要的那一档。

    `proof_review` 有写入期闸（`store._refuse_fake_proof_review` 读
    `verifications.proof_review_gap`）⇒ 调用方必须先把那一签落好，否则这里会被拒 ——
    这正好是"档位不是随便写的"那条既有纪律，夹具不绕过它。
    """
    row = next(r for r in store.rows("statements") if str(r.get("stmt_id") or "") == sid)
    row = dict(row)
    row["evidence_kind"] = kind
    # 2026-11-05：判定面读等级。夹具把"被引命题够格"这件事落进五元位（proof 位），
    # 不再只改历史列 —— 只改列的话现算等级仍是 conjecture，新门槛会拒它（这正是
    # 本次改造要的行为，夹具必须按新规则造行）。
    bits = dict(row.get("bits") or {})
    if kind in ("proof", "proof_review"):
        bits["proof"] = True
        ev = dict(bits.get("evidence") or {})
        if not str(ev.get("proof_process") or "").strip():
            ev["proof_process"] = str(row.get("proof_text") or "（夹具：证明正文）")
        bits["evidence"] = ev
    bits["grade"] = _EB.derive_grade(bits, kind=str(row.get("kind") or ""))
    row["bits"] = bits
    with store.tx("statements", actor="test", note="fixture:evidence_kind") as tx:
        tx.upsert("statements", row, note="fixture:evidence_kind")


def _cite(store: Store, *, citing: str, cited: str, note: str = F_NOTE,
          quote: str = "", proof_no: int = 1, path_group: int = 1,
          dep_id: str = "000001") -> None:
    """F 侧登记的那条依赖行（`used_by="stmt:<命题号>#pN"` + `path_group` + `source_stmt_id`）。

    F 那句话写在 `label` 上（`schema.Dependency` 的正名之一）：它是自然语言描述，
    不是逐字引文 —— 这正是本件要核的东西。

    2026-11-08：V 只读手稿，所以依赖还要写进被审的那份手稿的 `## 依赖` 表；
    台账那一行照旧写（B 收录时仍读它），但 V 这一侧不再读它。
    """
    row = S.Dependency(
        dep_id=dep_id, used_by=PL.used_by_of(f"stmt:{citing}", proof_no),
        kind="lemma", label=note, source_stmt_id=cited, status="closed",
        quote=quote, path_group=path_group, created_at=S.now_iso(),
        created_by="agent-F",
    ).to_dict()
    with store.tx("dependencies", actor="test", note="fixture:dependency") as tx:
        tx.upsert("dependencies", row, note="fixture:dependency")
    _PENDING_CITES.setdefault(str(store.root), []).append({
        "_proof_no": int(proof_no), "quote": note, "stmt_id": cited,
        "step": 1, "path_group": int(path_group)})


#: 每张手稿（按证明号）要带进 `## 依赖` 的那些行（`_cite` 登记、`_three` 消费）。
_PENDING_CITES: dict[str, list[dict]] = {}


def _write_named_manuscript(store: Store, main: str, manuscript_id: str,
                            proof: str, deps_rows: list[dict]) -> tuple[str, str]:
    """按稿号落一份新形式稿：`reports/f-proof-<稿号>.md`，返回 `(路径, 全文)`。

    新身份（2026-11-12 业主口径）：一份稿 = 一个稿号 = 一份证明 = 一条路径 ⇒ 名字里
    没有 `-pN`、稿头没有「证明号」、`## 依赖` 只有三列（路径号由 B 的秘书收录时分配，
    不进稿）。两份稿各一个稿号，所以这里显式落盘，不靠夹具的缺省号。
    """
    rel = f"reports/f-proof-{manuscript_id}.md"
    text = ("# 证明手稿（夹具）\n\n"
            f"- 命题号：stmt:{main}\n\n"
            f"## 命题\n\n{MAIN_FULL}\n\n"
            f"## 证明\n\n{proof}\n\n"
            + _DS.render_dependency_section(deps_rows))
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel, text


def _point_row_at_manuscript(store: Store, sid: str, manuscript_id: str) -> None:
    """把命题行上的 `manuscript_id` 指到某一份稿（B 收录那一笔写的就是这一格）。

    V 认"这一份稿是不是这条命题的稿"只读这一格（`agent_v/core.py` 的
    `_registered_manuscript_body`）；两条路径各一份稿时，被审的是哪一份就由它说。
    """
    row = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id") or "") == sid)
    row["manuscript_id"] = str(manuscript_id)
    with store.tx("statements", actor="test", note="fixture:manuscript_id") as tx:
        tx.upsert("statements", row, note="fixture:manuscript_id")


def _lemma(store: Store, *, evidence_kind: str = "proof_review") -> str:
    """造一条够格（或刻意不够格）被引的引理，返回它的命题号。

    2026-10-29 之后"签住"要连续 `SIGN_STREAK_NEED` 次「成立」（第 1、2 次只落台账、
    不翻位）：这一条引理要够 `proof_review` 级被引，所以这里签够次数（改前只签一次）。

    2026-11-08（V 只对手稿负责）：可引资格从引理自己的手稿签块读 —— 所以够格那
    一档还要把一份按号命名的稿落在盘上、并在稿上盖一块 3/3 的 V 签；不够格那一档
    留一份没有签的稿（读得到正文、读不到签）。
    """
    sid = _register(store, full=LEMMA_FULL, proof=LEMMA_PROOF)
    if evidence_kind == "proof_review":
        signed: dict = {}
        for _i in range(VR.SIGN_STREAK_NEED):
            signed = VR.record_verification(
                store.root, statement_id=sid, proof_text=LEMMA_PROOF,
                verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
                store=store, proof_no=1,
                #: p247：轴只由秘书给；夹具给 clean（不是由 `verdict` 字面推）。
                secretary_judge={"checked": True, "axis": "clean",
                                 "decision": "没问题", "reason": "夹具：clean"})
        assert signed.get("checked") is True, signed
        assert signed["statement_writeback"]["written"] is True, signed["statement_writeback"]
    _set_evidence_kind(store, sid, evidence_kind)
    rel = write_proof_manuscript(store.root, sid, LEMMA_PROOF,
                                 statement_full=LEMMA_FULL)
    if evidence_kind == "proof_review":
        raw = (pathlib.Path(store.root) / rel).read_text(encoding="utf-8")
        stamped = _VS.stamp_manuscript_sign(
            raw, proof_sha=VR.text_sha(LEMMA_PROOF), streak=3, need=3,
            verdict="成立", signer="secretary:F", at=S.now_iso(),
            ledger=f"verifications/{sid}.jsonl#v-000001",
            statement_id=sid, manuscript_id=sid)
        (pathlib.Path(store.root) / rel).write_text(stamped, encoding="utf-8")
    return sid


def _reply(verdict: str = "成立", *, checks: list[dict] | None = None,
           why: str = "", defect_step: int | None = None,
           findings: list[dict] | None = None) -> str:
    return json.dumps({
        "verdict": verdict, "defect_step": defect_step, "why": why,
        "findings": list(findings or []), "citation_checks": list(checks or []),
    }, ensure_ascii=False)


def _check(sid: str, verdict: str, *, note: str = "", verbatim: bool = False) -> dict:
    return {"stmt_id": sid, "verdict": verdict, "quote_verbatim": verbatim, "note": note}


def _v(store: Store, reply: str) -> tuple[AgentV, _Seam]:
    """V + 它的秘书（两人都在场才签得住，业主 2026-10-29 的追加口径）。"""
    seam = _Seam(reply)
    return AgentV(store, workspace_root=store.root, llm=seam,
                  secretary=_v_secretary(store)), seam


def _v_secretary(store: Store):
    """V 的秘书替身：判 clean、判签发（离线缝；夹具与 `test_v_sign_gate_streak` 同源）。"""
    from agentflow import secretary as SEC

    from test_v_sign_gate_streak import _Seam as _GateSeam
    from test_v_sign_gate_streak import _axis

    seam = _GateSeam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    return SEC.Secretary("V", root=store.root, store=store, seam=seam,
                         enable_model=True)


def _three(agent: AgentV, main: str, **kw: Any) -> dict:
    """连审 `SIGN_STREAK_NEED` 次、返回最后一次的返回值。

    2026-11-04（业主裁定 甲）：在册命题送审必须带手稿 ⇒ 这一格给被审的那一份正文落
    一份按号命名的稿（`## 证明` 与 `proof_text` 逐字一致），再带 `proof_manuscript`
    送审。判据一个字没改：签要落在稿上。

    2026-11-08（V 只对手稿负责）：依赖面也从稿的 `## 依赖` 读 —— `_cite` 登记的那些行
    按证明号铺进这份稿；再挂一个真实送审的 parent（落块只能由收方秘书做）。

    2026-11-12（两份稿 = 两条路径）：`manuscript=` 给了就审那一份现成的稿，不再按
    表示号的 `proof_no` 另写一份 —— 被审的是哪一份由稿本身回答，`-pN` 与稿头证明号
    已从产出侧退役。
    """
    text = str(kw.get("proof_text") or "")
    no = int(kw.get("proof_no") or 1)
    given = str(kw.pop("manuscript", "") or "")
    if given:
        kw["proof_manuscript"] = given
    elif text.strip():
        cites = [row for row in _PENDING_CITES.get(str(agent.workspace_root), [])
                 if int(row.get("_proof_no") or 1) == no]
        if cites:
            # F 的框架手稿里，依赖表并不是"另一份清单"：正文那一步也带着 `stmt:` 引用。
            # 夹具的证明是一段散文，这里按同一形状把引用补进第一个编号步 —— 于是
            # 依赖面六项里 ④⑤（表与正文一致 / 步号）读的是同一件事，判据量的仍是
            # 引用核实（语义），不是"夹具没写 cites"。
            import re as _re

            refs = "、".join(f"stmt:{row['stmt_id']}" for row in cites)
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if _re.match(r"^\d+\s*[.、)]\s*", line.strip()):
                    lines[i] = line.rstrip() + f"（依据：{refs}）"
                    break
            text = "\n".join(lines)
        kw["proof_text"] = text
        kw["proof_manuscript"] = write_proof_manuscript(
            agent.workspace_root, main, text,
            statement_full=str(kw.pop("statement_full", "") or MAIN_FULL),
            deps_rows=cites)
    out: dict = {}
    with _CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                         parent_role="F"):
        for _i in range(VR.SIGN_STREAK_NEED):
            out = agent.verify_proof(main, **kw)
    return out


def _ledger_row(store: Store, sid: str) -> dict:
    rows, problems = VR.list_verifications(store.root, statement_id=sid, limit=None)
    assert problems == [], problems
    assert rows, f"命题 {sid} 的验证台账一行都没有"
    return dict(rows[-1])


#: 判据 b / c / e 的公共断言，抽成谓词是为了让反真空那一条能直接判"它在打桩下必红"。
def _blocked_by(out: dict, verdict: str) -> bool:
    """这条判据成立吗：引用闸的挡签清单里有 `verdict` 那一档、这一签没落地、且没造出第三态。

    2026-11-01（两态裁定）之后判法变了、但没有放宽：改前看"结论被改判成 `看不出来`"，
    现在第三态不存在 —— `unknown` 那一档让结论仍停在 `成立`（V 没找到缺陷），挡住这一签
    的是引用闸。所以这里判的是三件更具体的事：闸点名了那一档、位没翻、且读数里不是
    `看不出来`（那一档不许再出现）。
    """
    gate = dict(out.get("citation_gate") or {})
    blocking = [str(e.get("verdict") or "") for e in (gate.get("blocking") or [])]
    return (verdict in blocking
            and out.get("signed_bit3") is False
            and str(out.get("verdict") or "") != "看不出来")


def _signed(out: dict) -> bool:
    """正控那条判据成立吗：结论成立、签落在稿上、台账里也读得到同一档。

    2026-11-08 之后"签住"的落点是稿上的九格块（`review_write.manuscript_signed`）；
    命题行的第 3 位归 B 收录时认领（`signed_bit3` 恒 False）。
    """
    return (str(out.get("verdict") or "") == "成立"
            and bool(dict(out.get("review_write") or {}).get("manuscript_signed"))
            and out.get("signed_bit3") is False
            and out.get("checked") is True)


# ============================================================ a 用法一致（措辞不同）

def test_a_consistent_use_signs_even_though_the_words_differ(tmp_path: pathlib.Path) -> None:
    """判据 a：F 用一条命题、用法与它说的条件/结论一致（措辞完全不同）⇒ 可签。

    三件事一起判：① 读数里有 `citation_checks` 这一格且判 `consistent`；② 照签第 3 位；
    ③ 审查材料里真有"F 的说法 + 被引命题正文"（只给编号的话，V 核不出是不是这么用的）。

    改前红：改前 `verify_proof` 的返回里根本没有 `citation_checks`（这一格不存在），
    `out["citation_checks"]` 当场 KeyError；而且它把证明正文审完就直接签字，
    依赖面上写了什么一个字都不读。
    """
    store = _ws(tmp_path)
    lemma = _lemma(store)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
    _cite(store, citing=main, cited=lemma, note=F_NOTE)
    agent, seam = _v(store, _reply(checks=[_check(lemma, "consistent",
                                                note="F 只用它的'中心非平凡'那一句，与原命题一致")]))

    out = _three(agent, main, proof_text=MAIN_PROOF)
    assert out["citations"], "依赖面登记了一条引用，审查材料却空着（只给编号也不行，这里要的是材料）"
    assert [c["stmt_id"] for c in out["citation_checks"]] == [lemma]
    assert out["citation_checks"][0]["verdict"] == "consistent"
    assert out["citation_checks"][0]["quote_verbatim"] is False
    assert out["citation_gate"]["ok"] is True and out["citation_gate"]["blocking"] == []
    assert _signed(out), out

    # ③ 材料两样都在：F 那句话与被引命题的正文（不是只给编号）。
    assert seam.prompts, "没有真的问过模型"
    prompt = seam.prompts[0]
    assert "## 引用核实" in prompt, "提示词里没有引用核实那一节"
    assert lemma in prompt, "被引命题的编号没进审查材料"
    assert LEMMA_FULL in prompt, "被引命题的正文没进审查材料（只给编号核不出来）"
    assert F_NOTE in prompt, "F 的说法没进审查材料（那是要核的那一半）"
    assert "proof_review" in prompt and "够格被引" in prompt, prompt[-2000:]

    # 台账那一行落了 `citation_checks` 那五格（形状逐字判）。
    disk = _ledger_row(store, main)
    assert disk["citation_checks"] == [{
        "stmt_id": lemma, "verdict": "consistent", "quote_verbatim": False,
        "note": "F 只用它的'中心非平凡'那一句，与原命题一致", "in_material": True}]
    assert set(disk["citation_checks"][0]) == set(VR.CITATION_CHECK_KEYS)
    assert VR.signs_bit3(disk, streak=VR.SIGN_STREAK_NEED) is True
    assert VR.bit3_payload(disk, streak=VR.SIGN_STREAK_NEED).get("reviewed") is True


# ============================================================ b 逐字但用法被夸大

def test_a_verbatim_quote_used_more_strongly_cannot_sign(tmp_path: pathlib.Path) -> None:
    """判据 b：措辞逐字、但 F 用到的结论比命题本身更强 ⇒ `stronger` 且签不成成立。

    这一条正是业主那句「正常写证明就是不会逐字的」的反面钉子：逐字（`quote_verbatim`
    为真）不是通行证 —— 它只作信息记，判定看的是用法。改前 V 照签「成立」。
    """
    store = _ws(tmp_path)
    lemma = _lemma(store)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
    _cite(store, citing=main, cited=lemma, note="照抄：G 的中心 Z(G) 非平凡", quote=F_QUOTE)
    agent, _seam = _v(store, _reply(checks=[
        _check(lemma, "stronger", verbatim=True,
               note="命题只说'非平凡'，F 当成'中心含 p 阶元'用了（更强）")]))

    out = _three(agent, main, proof_text=MAIN_PROOF)
    assert _blocked_by(out, "stronger"), out
    assert out["citation_checks"][0]["quote_verbatim"] is True, "逐字这一格只是信息，但它要如实记"
    assert int(out["unresolved_errors"]) >= 1, "挡签的引用核实必须落成 error finding"
    kinds = [f.get("kind") for f in out["findings"]]
    assert "citation_stronger" in kinds, out["findings"]
    assert any(lemma in str(f.get("detail") or "") for f in out["findings"]), (
        "挡签的 finding 必须点名是哪一条被引命题", out["findings"])
    assert lemma in out["detail"], "返回的 detail 要写清差在哪（受控拒绝的点名）"

    disk = _ledger_row(store, main)
    assert disk["verdict"] != "成立", disk
    assert VR.signs_bit3(disk) is False and VR.bit3_payload(disk) == {}
    # 结论改判成「有毛病」：这是缺陷（F 要改引用），不是"看不出来"。
    assert disk["verdict"] == "有毛病", disk


# ============================================================ c 引了一条无关命题

def test_an_unrelated_citation_cannot_sign(tmp_path: pathlib.Path) -> None:
    """判据 c：引了一条在册但与这一步无关的命题 ⇒ `unrelated` 且签不成成立。"""
    store = _ws(tmp_path)
    lemma = _lemma(store)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
    _cite(store, citing=main, cited=lemma,
          note="由正则群的分类定理（其实这里要的是中心非平凡，不是正则性）")
    agent, _seam = _v(store, _reply(checks=[
        _check(lemma, "unrelated", note="这条命题讲中心非平凡，F 用它替'正则性'那一步，两者无关")]))

    out = _three(agent, main, proof_text=MAIN_PROOF)
    assert _blocked_by(out, "unrelated"), out
    assert out["citation_gate"]["ok"] is False
    assert [e["stmt_id"] for e in out["citation_gate"]["blocking"]] == [lemma]
    disk = _ledger_row(store, main)
    assert disk["verdict"] == "有毛病" and VR.signs_bit3(disk) is False


# ============================================================ d 反真空（恒 consistent）

def test_stubbing_the_check_to_always_consistent_would_make_b_and_c_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 d（反真空）：把"引用核实"打桩成恒 `consistent` ⇒ 判据 b / c 必红。

    打桩之后 b（用法被夸大）与 c（引错）都会变成"一致"并且照签 —— 也就是说，b / c 那两条
    断言量的是"核实真的做了"，不是"模型说了什么"。这一条直接断言"b / c 在此打桩下不成立"
    （`_blocked_by` 返回 False），而 b / c 那两个测试断言它返回 True。

    为什么打在 `_citation_checks` 上：它是"模型给的原料 ⇒ 定稿"那一步的唯一落点
    （覆盖 / 档位 / 不在册都在那里定）。把它换成恒 consistent，等于把整个核实拆了。
    """
    def _always_consistent(self, checks, material):
        return [{"stmt_id": item["stmt_id"], "verdict": "consistent", "quote_verbatim": False,
                 "note": "打桩：恒一致"} for item in material]

    monkeypatch.setattr(AgentV, "_citation_checks", _always_consistent)

    for want, note in (("stronger", "照抄但当成更强用了"), ("unrelated", "引错了一条")):
        store = _ws(tmp_path / want)
        lemma = _lemma(store)
        main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
        _cite(store, citing=main, cited=lemma, note=note)
        agent, _seam = _v(store, _reply(checks=[_check(lemma, want, note="模型其实说了 " + want)]))
        out = _three(agent, main, proof_text=MAIN_PROOF)

        assert out["citation_checks"][0]["verdict"] == "consistent", (
            "打桩没生效 ⇒ 这一条判据什么也没证明", out["citation_checks"])
        assert out["citation_checks"][0]["note"] == "打桩：恒一致"
        # 判据 b / c 在这里必红：它们断言的是"结论不是成立、而且没签住"。
        assert _blocked_by(out, want) is False, "打桩下判据 b / c 竟然还成立 ⇒ 它们量的不是核实"
        assert _signed(out) is True, (
            "打桩下应当照签「成立」（这正是 b / c 会红的原因）；若不是，说明还另有闸在挡，"
            "那么 b / c 就不是靠核实变红的")


# ============================================================ e 档位不够格被引

def test_a_cross_check_citation_is_inadmissible_and_cannot_sign(tmp_path: pathlib.Path) -> None:
    """判据 e：引一条 `cross_check` 级的在册命题 ⇒ `inadmissible` 且签不成成立。

    业主逐字「proof_review级及以上才可引用」。这一档是事实、不是判断：模型就算说
    "用法一致"，也要被改判 `inadmissible`（那一句原文会附在 note 里，读的人看得见
    为什么模型与定稿不一样）。

    改前红：改前只看"用法一致不一致"，模型说 consistent 就一路签下去 ——
    一条 `cross_check` 的东西可以当依据引，而没有任何一处会报。
    """
    store = _ws(tmp_path)
    lemma = _lemma(store, evidence_kind="cross_check")
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
    _cite(store, citing=main, cited=lemma, note="由那条数值交叉验证过的引理可知……")
    agent, seam = _v(store, _reply(checks=[
        _check(lemma, "consistent", note="用法与原文一致（模型原话）")]))

    out = _three(agent, main, proof_text=MAIN_PROOF)
    # 2026-11-08：可引资格从"被引命题自己的手稿上有没有 V 签"读。这一档的稿没有签
    # ⇒ 等级读不出来（空）、不够格；模型说"一致"也照样被改判 inadmissible。
    assert out["citations"][0]["manuscript_missing"] is False, out["citations"]
    assert out["citations"][0]["grade"] == "", out["citations"]
    assert out["citations"][0]["admissible"] is False
    assert _blocked_by(out, "inadmissible"), out
    assert "pre_theorem" in out["citation_checks"][0]["note"], out["citation_checks"]
    assert "不够格" in seam.prompts[0], "提示词里要教这条档位口径（否则模型无从判）"
    disk = _ledger_row(store, main)
    assert disk["verdict"] == "有毛病" and VR.signs_bit3(disk) is False


# ============================================================ f 反真空（档位闸两端）

def test_stubbing_the_floor_gate_moves_both_directions(tmp_path: pathlib.Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 f（反真空，两端都打）：档位闸恒放行 ⇒ e 必红；恒拒绝 ⇒ a 的正控必红。

    这一条守的是"档位是从 `schema.EVIDENCE_KINDS` 现算的"这句话：
    - 恒放行：`cross_check` 会被当成够格，模型说一致就签了 ⇒ e 的断言红；
    - 恒拒绝：`proof_review` 也会被判不够格 ⇒ a 的"用法一致可签"红。
    任一端失效（桩打不进去 / 判据不读这一格），下面都会当场报出来。
    """
    def _store_fixture(tag: str, kind: str) -> tuple[Store, str, str]:
        store = _ws(tmp_path / tag)
        lemma = _lemma(store, evidence_kind=kind)
        main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
        _cite(store, citing=main, cited=lemma, note=F_NOTE)
        return store, main, lemma

    # ---- ① 恒放行：e 必红
    monkeypatch.setattr(AgentV, "_citation_admissibility", lambda self, kind: True)
    store, main, lemma = _store_fixture("permit", "cross_check")
    agent, _seam = _v(store, _reply(checks=[_check(lemma, "consistent", note="用法一致")]))
    out = _three(agent, main, proof_text=MAIN_PROOF)
    assert out["citations"][0]["admissible"] is True, "打桩没生效"
    assert _blocked_by(out, "inadmissible") is False, "档位闸恒放行下 e 竟然还成立 ⇒ 它量的不是档位"
    assert _signed(out) is True
    monkeypatch.undo()

    # ---- ② 恒拒绝：a 的正控必红
    monkeypatch.setattr(AgentV, "_citation_admissibility", lambda self, kind: False)
    store, main, lemma = _store_fixture("deny", "proof_review")
    agent, _seam = _v(store, _reply(checks=[_check(lemma, "consistent", note="用法一致")]))
    out = _three(agent, main, proof_text=MAIN_PROOF)
    assert out["citations"][0]["admissible"] is False, "打桩没生效"
    assert _signed(out) is False, "档位闸恒拒绝下 a 的正控竟然还签住了 ⇒ 它量的不是档位"
    assert _blocked_by(out, "inadmissible") is True


# ============================================================ 护栏：weaker 可签但点名

def test_a_weaker_use_still_signs_but_is_named_in_the_readings(tmp_path: pathlib.Path) -> None:
    """护栏（正控）：只用弱形式不算错 —— 可签，但读数里点名"只用到弱形式"。

    业主口径逐字：`weaker` ⇒ 可以签，但读数里点名。所以这一条同时判两半：
    签住了，而且"弱"这件事在 findings / citation_gate / detail 三处都读得到。
    如果改法把"非一致"一律当错（把 weaker 也挡掉），这一条会红。
    """
    store = _ws(tmp_path)
    lemma = _lemma(store)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
    _cite(store, citing=main, cited=lemma, note="只需要'非平凡'那一半，用不到 p 阶元那一半")
    agent, _seam = _v(store, _reply(checks=[
        _check(lemma, "weaker", note="F 只要'中心非平凡'，命题其实更强 —— 只用到了弱形式")]))

    out = _three(agent, main, proof_text=MAIN_PROOF)
    assert _signed(out), out
    assert out["citation_checks"][0]["verdict"] == "weaker"
    assert out["citation_gate"]["weaker"] and out["citation_gate"]["ok"] is True, out["citation_gate"]
    kinds = [f.get("kind") for f in out["findings"]]
    assert "citation_weaker" in kinds, out["findings"]
    assert "弱形式" in out["detail"], "读数里要点名'这一步只用到它的弱形式'"
    assert "弱形式" in str(out["reason"]) or "弱形式" in str(out["detail"])


# ============================================================ 护栏：unknown 挡住签

def test_an_unknown_citation_lands_as_undetermined_and_does_not_sign(
        tmp_path: pathlib.Path) -> None:
    """护栏：V 自己说判不了（`unknown`）⇒ 不许签成立，而台账照样落这一行。

    （名字里的 `undetermined` 是历史名：2026-11-01 之后这一档不是一个结论词，
    见 `docs/DEVELOPMENT-SPEC.md` §16.7 对这条判据的登记。改的是判据本体，靶子没变：
    "判不了的那一条不许换成一签"。）

    p247：`verdict` 只是 V 写下的陈述（这一条里写的是 `成立`），引用闸不改写它；但这一档
    是「没查成」，不是「没问题」：那一条 `unknown` 同时是一条 error
    （`unresolved_errors > 0`）并进 `citation_blocks` ⇒ `row_signable` 为假（轴再 clean
    也签不住）⇒ 这一签不签发。不存在第三个结论词；「判不了也要落台账」这件事一个字没动。
    """
    store = _ws(tmp_path)
    lemma = _lemma(store)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
    _cite(store, citing=main, cited=lemma, note="由那条引理（正文读起来像是讲别的）")
    agent, _seam = _v(store, _reply(checks=[
        _check(lemma, "unknown", note="那句话在这一步的上下文里读不出确定含义，判不了")]))

    out = _three(agent, main, proof_text=MAIN_PROOF)
    assert out["checked"] is True, "判不了也要落台账（它不是没查成）"
    assert out["verdict"] == "成立", out
    assert out["verdict"] not in ("看不出来",), "第三态又冒出来了" + str(out["verdict"])
    assert out["citation_checks"][0]["verdict"] == "unknown", out["citation_checks"]
    assert out["signed_bit3"] is False, out
    row = _ledger_row(store, main)
    assert row["verdict"] == "成立", row
    assert int(row["unresolved_errors"]) >= 1, row
    assert VR.row_signable(row) is False, "判不了的那一条没有挡住这一签"
    assert VR.citation_blocks(row), row


# ============================================================ 护栏：引用指向不在册命题

def test_a_citation_to_a_missing_proposition_cannot_be_called_consistent(
        tmp_path: pathlib.Path) -> None:
    """护栏：依赖行指向一条不在册的命题 ⇒ 一律 `unknown`（不许判"一致"）。

    写侧（`agent_f.dependency.record_dependency` 的 `source_not_registered`）已经先拒了
    这种引用；这一条守的是"依赖行已经在盘上、而那条命题后来不在册 / 是手写的行"这一档 ——
    V 读不到那条命题的正文，就没有资格说"F 用得对"。
    """
    store = _ws(tmp_path)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
    _cite(store, citing=main, cited="999999", note="由那条引理（册子里其实没有它）")
    agent, seam = _v(store, _reply(checks=[
        _check("999999", "consistent", note="模型说一致（它也没见过这条命题）")]))

    out = _three(agent, main, proof_text=MAIN_PROOF)
    # 2026-11-08：V 只读手稿 ⇒ 读不到"这一条有没有在册"，能说的是"盘上没有它的稿"。
    # 这一档照样挡住：`manuscript_missing` 是读数，改判 inadmissible 是判据。
    assert out["citations"][0]["manuscript_missing"] is True, out["citations"]
    assert out["citations"][0]["statement_missing"] is False, (
        "V 不读册，却声称'不在册' ⇒ 读了一句它没查过的话")
    assert out["citation_checks"][0]["verdict"] == "inadmissible", out["citation_checks"]
    assert "不够格" in out["citation_checks"][0]["note"]
    assert out["signed_bit3"] is False, out
    assert "判 inadmissible" in seam.prompts[0]


# ============================================================ 护栏：缺一条按 unknown

def test_a_cited_proposition_without_a_verdict_is_unknown_and_cannot_sign(
        tmp_path: pathlib.Path) -> None:
    """护栏（反真空）：材料里有引用、V 一条结论都没给 ⇒ 补 `unknown` 且不许签。

    "没给结论"与"判了一致"是两件事。若这一格按空列表放行，那么"核实"这一档可以靠
    什么都不说绕过去 —— 打桩那一类判据就会变成摆设。
    """
    store = _ws(tmp_path)
    lemma = _lemma(store)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
    _cite(store, citing=main, cited=lemma, note=F_NOTE)
    agent, _seam = _v(store, _reply(checks=[]))

    out = _three(agent, main, proof_text=MAIN_PROOF)
    assert out["citation_checks"][0]["verdict"] == "unknown", out["citation_checks"]
    assert "没有对这条被引命题给出结论" in out["citation_checks"][0]["note"]
    assert out["signed_bit3"] is False and _blocked_by(out, "unknown"), out


# ============================================================ 护栏：另一份稿不串份

#: 同一命题的两条路径 = 两份稿、各一个稿号（一个稿号 = 一份文件 = 一份证明）。
MID_ONE = "000123"
MID_TWO = "000124"


def _second_proof(lemma: str) -> str:
    """第二条路径的证明正文：带 `stmt:<引理>`，与它那份稿的 `## 依赖` 表对得上。"""
    return MAIN_PROOF_2.replace(
        "1. 用类方程数共轭类。", f"1. 用类方程数共轭类（依据：stmt:{lemma}）。")


def _two_paths(base: pathlib.Path) -> dict[str, Any]:
    """造"同一命题的两条路径"：两份稿（各一个稿号），各带自己的 `## 依赖` 表。

    - 稿 000123：第 1 条路径，依赖表是空的（自足）；
    - 稿 000124：第 2 条路径，依赖表里有一条 `stmt:<引理>`。

    台账里也照 B 收录的形态写一行（`used_by=...#p2` + `path_group=2`）—— V 不该读它；
    两半断言之所以有意义，正因为那条依赖在别处（另一份稿 + 台账）都真实存在。
    """
    store = _ws(base)
    lemma = _lemma(store)
    second = _second_proof(lemma)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF,
                     proofs=[{"proof_no": 1, "text": MAIN_PROOF},
                             {"proof_no": 2, "text": second}])
    _cite(store, citing=main, cited=lemma, note="第二条路线才用到这条引理",
          proof_no=2, path_group=2)
    rel1, _text1 = _write_named_manuscript(store, main, MID_ONE, MAIN_PROOF, [])
    rel2, _text2 = _write_named_manuscript(store, main, MID_TWO, second, [
        {"quote": "第二条路线才用到这条引理", "stmt_id": lemma, "step": 1}])
    return {"store": store, "main": main, "lemma": lemma, "second": second,
            "rel1": rel1, "rel2": rel2}


def test_dependencies_of_another_manuscript_do_not_enter_this_manuscripts_material(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """护栏：另一份稿的依赖不进这一份稿的审查材料（依赖面按"被审的那一份稿"读）。

    新身份（2026-11-12 业主口径）：一份稿 = 一个稿号 = 一份证明 = 一条路径；
    稿名不再带 `-pN`、稿头不再有「证明号」、`## 依赖` 表只有三列（没有「路径号」）。
    所以"这是第几条证明"不再由稿里/表里的某个号回答 —— 它由这一份稿本身（稿号 /
    稿路径）回答，路径号由 B 的秘书在收录时分配。

    两半都判（同一命题的两份稿，各一个稿号，各带自己的 `## 依赖` 表）：
    - 审稿 000123 时材料是空的：那条边写在 000124 那份稿的 `## 依赖` 里；
    - 审稿 000124 时材料里才有它。
    反向真空：把"按被审的那份稿取依赖"打桩成"一律取 000124 的依赖" ⇒ 前一半必红
    （审 000123 时也会看见那条引理）。

    改前红（2026-11-12 实测）：用例还按证明号造数据（一份稿 + 台账 `#p2` 依赖行 +
    `proof_no=2`），而 V 的材料早已改从被审那份稿的 `## 依赖` 表读 ⇒ 那份稿的表里
    没有这条引用，`out2["citations"] == []`。
    """
    # ---- 反向真空：把"按稿取依赖"打桩成"不挑"（恒取 000124 那份） ---------------
    fixed = _two_paths(tmp_path / "fixed")
    real_parse = _DS.parse_dependency_section
    second_reading = real_parse(
        (pathlib.Path(fixed["store"].root) / fixed["rel2"]).read_text(encoding="utf-8"))

    def _always_the_second_manuscript(text: str) -> dict:
        """不挑被审的是哪一份，恒返回第二份稿的依赖段（"折平"的桩）。"""
        return second_reading if str(text or "").strip() else real_parse(text)

    monkeypatch.setattr(_DS, "parse_dependency_section", _always_the_second_manuscript)
    _point_row_at_manuscript(fixed["store"], fixed["main"], MID_ONE)
    fixed_agent, _fixed_seam = _v(fixed["store"], _reply(checks=[]))
    out_stub = _three(fixed_agent, fixed["main"], proof_text=MAIN_PROOF,
                      manuscript=fixed["rel1"])
    assert [c["stmt_id"] for c in out_stub["citations"]] == [fixed["lemma"]], (
        "打桩之后审 000123 仍然看不到 000124 的依赖 ⇒ 打桩没生效，"
        "「按稿挑依赖」这句话没有被这条用例量到", out_stub["citations"])
    monkeypatch.undo()

    # ---- 正控：V 从被审的那份稿读依赖 ------------------------------------------
    picked = _two_paths(tmp_path / "picked")
    store, main, lemma = picked["store"], picked["main"], picked["lemma"]
    _point_row_at_manuscript(store, main, MID_ONE)

    agent, _seam = _v(store, _reply(checks=[]))
    out1 = _three(agent, main, proof_text=MAIN_PROOF, manuscript=picked["rel1"])
    assert out1["citations"] == [], (
        "把另一份稿（000124）的依赖塞进了这一份（000123）的材料"
        f"（按证明号/按台账挑）：{out1['citations']}")
    assert out1["signed_bit3"] is False, out1
    assert out1["review_write"].get("manuscript_signed") is True, out1["review_write"]
    assert _ledger_row(store, main).get("manuscript") == picked["rel1"], (
        "台账那一行没记被审的是哪一份稿", _ledger_row(store, main))

    # B 收录第二份稿时把行上的稿号指到它（被审的换成另一份稿）。
    _point_row_at_manuscript(store, main, MID_TWO)
    agent2, seam2 = _v(store, _reply(checks=[_check(lemma, "consistent", note="用法一致")]))
    out2 = _three(agent2, main, proof_text=picked["second"], manuscript=picked["rel2"])
    assert [c["stmt_id"] for c in out2["citations"]] == [lemma], out2["citations"]
    # 2026-11-11/12：`proof_no` 从 V 的读数退役 ⇒ "审的是哪一份"由稿本身回答，
    # 台账那一行的 `manuscript` 记的就是被审的稿。
    disk = _ledger_row(store, main)
    assert disk.get("manuscript") == picked["rel2"], disk
    assert out2["signed_bit3"] is False, out2
    assert out2["review_write"].get("manuscript_signed") is True, out2["review_write"]
    assert LEMMA_FULL in seam2.prompts[0]


# ============================================================ 护栏：读侧硬闸

def test_the_allowed_level_set_is_computed_from_the_shared_evidence_order() -> None:
    """护栏：允许集合是从等级序现算的，不是抄的一份字面量（2026-11-05 改口径）。

    三处对账：① 它必须等于 `depsection.CITATION_LEVELS`（门槛的唯一定义）；
    ② 它必须等于 `evidencebits.GRADES` 从 `CITATION_MIN_LEVEL` 切到最强端；③ 门槛
    常量在 `verifications` 里必须是对 `depsection` 的引用，不是第二份字面量。
    词表里没有门槛那一档 ⇒ 空集（fail-closed：空集会让每一条引用都判 inadmissible，
    那是可见的失败，不是静默放行）。
    """
    from agentflow import depsection as _DS
    from agentflow import evidencebits as _Eb

    floor = VR.CITATION_EVIDENCE_FLOOR
    assert floor == _DS.CITATION_MIN_LEVEL == "pre_theorem", floor
    assert floor in _Eb.GRADES, (floor, _Eb.GRADES)
    # ① 唯一定义切出来的集合。
    expected = set(_DS.CITATION_LEVELS)
    # ② 等级序（弱到强）门槛那一位切到最强端。
    ordered = set(_Eb.GRADES[_Eb.GRADES.index(floor):])
    live = set(VR.admissible_evidence_kinds())
    assert live == expected == ordered, (sorted(live), sorted(expected), sorted(ordered))
    assert live == {"pre_theorem", "theorem"}, sorted(live)
    # 反方向：低于门槛的两级一个都不许进（空串也算"读不到等级"）。
    for grade in ("conjecture", "strong_conjecture", ""):
        assert VR.citation_grade_admissible(grade) is False, grade
    # 历史档位的兼容口只做换算，不另设门槛：proof_review → pre_theorem（够格），
    # cross_check → strong_conjecture（不够格）。
    assert VR.evidence_kind_admissible("proof_review") is True
    assert VR.evidence_kind_admissible("cross_check") is False


def test_signs_bit3_refuses_a_row_whose_citation_check_blocks() -> None:
    """护栏：台账那一行的硬闸（`signs_bit3` / `bit3_payload`）也认引用核实。

    为什么要这一条：写路径上的改判只挡住"V 自己这一趟"；台账是追加式文件，手写一行
    `verdict=成立` 与 V 自己判了成立，在读者眼里没有区别 ⇒ 读侧必须有同一道闸。
    这不是第二份判据：它读的就是 `citation_checks` 那一格、词表就是 `CITATION_BLOCKING`。
    """
    base = {"statement_id": "000001", "verdict": "成立", "unresolved_errors": 0,
            "secretary_judge": {"checked": True, "axis": "clean"}}
    for verdict in sorted(VR.CITATION_BLOCKING):
        row = dict(base, citation_checks=[{"stmt_id": "000002", "verdict": verdict,
                                           "quote_verbatim": False, "note": "x"}])
        assert VR.signs_bit3(row) is False, verdict
        assert VR.bit3_payload(row) == {}, verdict
    for verdict in sorted(VR.CITATION_SIGNABLE):
        row = dict(base, citation_checks=[{"stmt_id": "000002", "verdict": verdict,
                                           "quote_verbatim": True, "note": "x"}])
        assert VR.signs_bit3(row, streak=VR.SIGN_STREAK_NEED) is True, verdict
    # 历史行（没有这一格）照旧：老台账的读数逐字不变。
    assert VR.signs_bit3(dict(base), streak=VR.SIGN_STREAK_NEED) is True


# ============================================================ 两个判定口必须同结论（2026-10-27）
#
# 改前的形态：`citation_gate` 明确不拿"材料之外的那几条"挡签（它们不是这一份证明
# 登记的引用），而 `signs_bit3` 读的是同一个 `citation_checks` 却没有这一句；
# 更要命的是 `in_material` 只是内存里的临时格，落盘时被洗掉 ⇒ 落盘再读回来，
# `signs_bit3` 把材料外的那条也算成挡签。后果实测：V 判「成立」、闸也说 ok 的一签，
# 读回来是 `rejected`，理由是"verdict='成立' ⇒ 结论不是成立"（自相矛盾，且写的人无从修）。

def _two_gates_fixture() -> tuple[list[dict], list[dict]]:
    """(V 给的原始 checks, 依赖台账材料)：材料内一条 `consistent`，材料外一条 `stronger`。"""
    inside = "000001"
    outside = "000777"
    raw = [{"stmt_id": inside, "verdict": "consistent", "quote_verbatim": False, "note": ""},
           {"stmt_id": outside, "verdict": "stronger", "quote_verbatim": False,
            "note": "这条引用被夸大"}]
    material = [{"stmt_id": inside, "evidence_kind": "proof", "admissible": True}]
    return raw, material


def test_the_citation_gate_and_signs_bit3_reach_the_same_verdict_after_disk(
        tmp_path: pathlib.Path) -> None:
    """正控：同一份行内容，`citation_gate` 与 `signs_bit3` 逐格同结论（含落盘往返）。

    判据是三件事一起判：
    ① `citation_gate(reconciled).ok` 为真（材料外那条不挡签）；
    ② 落盘那一行仍然带着 `in_material`（材料外那条是 `False`）—— 它是判据的承重格；
    ③ `signs_bit3(落盘那一行)` 与 ① 同结论，且 `review_standing` 读回 `signed`。

    改前红：③ 为假（`signs_bit3` 把材料外那条算成挡签），`review_standing` 读回
    `rejected`，`why` 里写着"verdict='成立' ⇒ 结论不是成立"。
    """
    raw, material = _two_gates_fixture()
    checks = VR.reconcile_citation_checks(raw, material)
    gate = VR.citation_gate(checks)
    assert gate["ok"] is True, gate
    merged = VR.apply_citation_gate(
        {"verdict": "成立", "findings": [], "citation_checks": checks}, gate)
    assert merged["verdict"] == "成立", merged

    text = "证明：由命题 000001 立得。"
    # 三次「成立」才签住（业主 2026-10-29）；第 1、2 次只落台账 ⇒ 读侧读到 holding。
    for _i in range(VR.SIGN_STREAK_NEED):
        VR.record_verification(tmp_path, statement_id="000009", proof_text=text,
                               verdict=merged, citation_gate=gate,
                               secretary_judge={"checked": True, "axis": "clean",
                                                "decision": "没问题", "reason": "夹具"})
    rows, problems = VR.list_verifications(tmp_path, statement_id="000009", limit=None)
    assert problems == [], problems
    disk = dict(rows[-1])
    # ② 承重格落盘了：材料内 True、材料外 False。
    assert [c["in_material"] for c in disk["citation_checks"]] == [True, False], disk
    assert set(disk["citation_checks"][0]) == set(VR.CITATION_CHECK_KEYS)
    # ③ 两个口同结论。
    assert VR.citation_blocks(disk) == [], VR.citation_blocks(disk)
    assert VR.signs_bit3(disk, streak=VR.SIGN_STREAK_NEED) is gate["ok"] is True
    standing = VR.review_standing(tmp_path, statement_id="000009", proof_text=text)
    assert standing["state"] == "signed", standing
    assert standing["streak"] == VR.SIGN_STREAK_NEED, standing


def test_dropping_in_material_from_the_ledger_row_makes_that_agreement_red() -> None:
    """反真空：把 `in_material` 从落盘键里去掉 ⇒ 两个判定口分家（判据必红）。

    这一条证明"这一格是承重的"，不是装饰：同一行、同一批 `citation_checks`，
    只是少了 `in_material`，闸（在 reconciled 那批条目上算出 `ok=True`）与读侧
    （`signs_bit3` 看落盘那一行）就给出相反结论 —— 那正是改前的现场。

    同时钉住"老行缺键按材料内读"：没有这一格的材料内阻挡条目照样挡签
    （`in_material` 的缺省不许往放行的方向走）。
    """
    raw, material = _two_gates_fixture()
    checks = VR.reconcile_citation_checks(raw, material)
    gate = VR.citation_gate(checks)
    assert gate["ok"] is True, gate

    row = {"stmt_id": "000009", "verdict": "成立", "unresolved_errors": 0,
           "secretary_judge": {"checked": True, "axis": "clean"},
           "citation_checks": [dict(c) for c in checks]}
    assert VR.signs_bit3(row, streak=VR.SIGN_STREAK_NEED) is True

    stripped = dict(row, citation_checks=[
        {k: v for k, v in c.items() if k != "in_material"} for c in row["citation_checks"]])
    # 分家的形态：闸说可以签（它在 reconciled 那批条目上算的），读侧说签不住。
    assert VR.signs_bit3(stripped) is False, "去掉 in_material 之后判据没红 ⇒ 这一格不是承重的"
    # 同一批条目若从一开始就没有这一格，两个口都会判挡（fail-closed）——
    # 分家只发生在"闸按 reconciled 算、读侧按落盘算"这一种形态上。
    assert VR.citation_gate(stripped["citation_checks"])["ok"] is False
    # 老行缺键按"材料内"读 ⇒ 阻挡条目照旧挡签。
    old = {"stmt_id": "000009", "verdict": "成立", "unresolved_errors": 0,
           "secretary_judge": {"checked": True, "axis": "clean"},
           "citation_checks": [{"stmt_id": "000002", "verdict": "stronger",
                                "quote_verbatim": False, "note": "x"}]}
    assert VR.citation_blocks(old) != []
    assert VR.signs_bit3(old) is False
