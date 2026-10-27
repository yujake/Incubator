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
`unknown` 落"看不出来"、材料里有引用而 V 没给结论按 `unknown`、`#p2` 的依赖不进
`#p1` 的审查材料；以及台账/读侧那两格的硬闸（`signs_bit3` 与 `bit3_payload`）。

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

from agentflow import proofloc as PL
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_v import AgentV
from agentflow.store import Store

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
    b = AgentB(store, extractor=None, extract_text=None, config={})
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
    with store.tx("statements", actor="test", note="fixture:evidence_kind") as tx:
        tx.upsert("statements", row, note="fixture:evidence_kind")


def _cite(store: Store, *, citing: str, cited: str, note: str = F_NOTE,
          quote: str = "", proof_no: int = 1, path_group: int = 1,
          dep_id: str = "000001") -> None:
    """F 侧登记的那条依赖行（`used_by="stmt:<命题号>#pN"` + `path_group` + `source_stmt_id`）。

    F 那句话写在 `label` 上（`schema.Dependency` 的正名之一）：它是自然语言描述，
    不是逐字引文 —— 这正是本件要核的东西。
    """
    row = S.Dependency(
        dep_id=dep_id, used_by=PL.used_by_of(f"stmt:{citing}", proof_no),
        kind="lemma", label=note, source_stmt_id=cited, status="closed",
        quote=quote, path_group=path_group, created_at=S.now_iso(),
        created_by="agent-F",
    ).to_dict()
    with store.tx("dependencies", actor="test", note="fixture:dependency") as tx:
        tx.upsert("dependencies", row, note="fixture:dependency")


def _lemma(store: Store, *, evidence_kind: str = "proof_review") -> str:
    """造一条够格（或刻意不够格）被引的引理，返回它的命题号。"""
    sid = _register(store, full=LEMMA_FULL, proof=LEMMA_PROOF)
    if evidence_kind == "proof_review":
        signed = VR.record_verification(
            store.root, statement_id=sid, proof_text=LEMMA_PROOF,
            verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
            store=store, proof_no=1)
        assert signed.get("checked") is True, signed
    _set_evidence_kind(store, sid, evidence_kind)
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
    seam = _Seam(reply)
    return AgentV(store, workspace_root=store.root, llm=seam), seam


def _ledger_row(store: Store, sid: str) -> dict:
    rows, problems = VR.list_verifications(store.root, statement_id=sid, limit=None)
    assert problems == [], problems
    assert rows, f"命题 {sid} 的验证台账一行都没有"
    return dict(rows[-1])


#: 判据 b / c / e 的公共断言，抽成谓词是为了让反真空那一条能直接判"它在打桩下必红"。
def _blocked_by(out: dict, verdict: str) -> bool:
    """这条判据成立吗：读数里有 `verdict` 那一档、结论不是成立、且没签住第 3 位。"""
    checks = list(out.get("citation_checks") or [])
    return (bool(checks) and str(checks[0].get("verdict") or "") == verdict
            and str(out.get("verdict") or "") != "成立"
            and out.get("signed_bit3") is False)


def _signed(out: dict) -> bool:
    """正控那条判据成立吗：结论成立、签住第 3 位、台账里也读得到同一档。"""
    return (str(out.get("verdict") or "") == "成立" and out.get("signed_bit3") is True
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

    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
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
    assert VR.signs_bit3(disk) is True and VR.bit3_payload(disk).get("reviewed") is True


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

    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
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

    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
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
        out = agent.verify_proof(main, proof_text=MAIN_PROOF)

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

    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
    assert out["citations"][0]["evidence_kind"] == "cross_check", out["citations"]
    assert out["citations"][0]["admissible"] is False
    assert _blocked_by(out, "inadmissible"), out
    assert "cross_check" in out["citation_checks"][0]["note"], (
        "挡签的点名要写清它现在是什么档", out["citation_checks"])
    assert "proof_review" in out["citation_checks"][0]["note"]
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
    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
    assert out["citations"][0]["admissible"] is True, "打桩没生效"
    assert _blocked_by(out, "inadmissible") is False, "档位闸恒放行下 e 竟然还成立 ⇒ 它量的不是档位"
    assert _signed(out) is True
    monkeypatch.undo()

    # ---- ② 恒拒绝：a 的正控必红
    monkeypatch.setattr(AgentV, "_citation_admissibility", lambda self, kind: False)
    store, main, lemma = _store_fixture("deny", "proof_review")
    agent, _seam = _v(store, _reply(checks=[_check(lemma, "consistent", note="用法一致")]))
    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
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

    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
    assert _signed(out), out
    assert out["citation_checks"][0]["verdict"] == "weaker"
    assert out["citation_gate"]["weaker"] and out["citation_gate"]["ok"] is True, out["citation_gate"]
    kinds = [f.get("kind") for f in out["findings"]]
    assert "citation_weaker" in kinds, out["findings"]
    assert "弱形式" in out["detail"], "读数里要点名'这一步只用到它的弱形式'"
    assert "弱形式" in str(out["reason"]) or "弱形式" in str(out["detail"])


# ============================================================ 护栏：unknown 落未定

def test_an_unknown_citation_lands_as_undetermined_and_does_not_sign(
        tmp_path: pathlib.Path) -> None:
    """护栏：V 自己说判不了（`unknown`）⇒ 不许签成立，但"未定"要落进台账。

    「可以落未定」的落法：结论改成存量三态里的 `看不出来`（它不是成立，也不是"没查成"），
    台账照样有那一行 —— 判不了是一条结论，不是一次没查成。
    """
    store = _ws(tmp_path)
    lemma = _lemma(store)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF)
    _cite(store, citing=main, cited=lemma, note="由那条引理（正文读起来像是讲别的）")
    agent, _seam = _v(store, _reply(checks=[
        _check(lemma, "unknown", note="那句话在这一步的上下文里读不出确定含义，判不了")]))

    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
    assert out["checked"] is True, "判不了也要落台账（它不是没查成）"
    assert out["verdict"] == "看不出来" and out["signed_bit3"] is False, out
    assert _ledger_row(store, main)["verdict"] == "看不出来"


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

    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
    assert out["citations"][0]["statement_missing"] is True, out["citations"]
    assert out["citation_checks"][0]["verdict"] == "unknown", out["citation_checks"]
    assert "不在册" in out["citation_checks"][0]["note"]
    assert out["signed_bit3"] is False, out
    assert "只能判 unknown" in seam.prompts[0]


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

    out = agent.verify_proof(main, proof_text=MAIN_PROOF)
    assert out["citation_checks"][0]["verdict"] == "unknown", out["citation_checks"]
    assert "没有对这条被引命题给出结论" in out["citation_checks"][0]["note"]
    assert out["signed_bit3"] is False and _blocked_by(out, "unknown"), out


# ============================================================ 护栏：证明号不串份

def test_dependencies_of_another_proof_do_not_enter_this_proofs_material(
        tmp_path: pathlib.Path) -> None:
    """护栏：`#p2` 的依赖不进 `#p1` 的审查材料（"这一份证明登记的依赖行"要逐份读）。

    两半都判：审 `#p1` 时材料是空的（那条边属于 #p2）；审 `#p2` 时材料里才有它。
    把两半折平（例如不按证明号过滤）这一条会红。
    """
    store = _ws(tmp_path)
    lemma = _lemma(store)
    main = _register(store, full=MAIN_FULL, proof=MAIN_PROOF,
                     proofs=[{"proof_no": 1, "text": MAIN_PROOF},
                             {"proof_no": 2, "text": MAIN_PROOF_2}])
    _cite(store, citing=main, cited=lemma, note="第二条路线才用到这条引理", proof_no=2)

    agent, _seam = _v(store, _reply(checks=[]))
    out1 = agent.verify_proof(main, proof_text=MAIN_PROOF, proof_no=1)
    assert out1["citations"] == [], "把 #p2 的依赖塞进了 #p1 的材料（串份）"
    assert out1["signed_bit3"] is True, out1

    agent2, seam2 = _v(store, _reply(checks=[_check(lemma, "consistent", note="用法一致")]))
    out2 = agent2.verify_proof(main, proof_text=MAIN_PROOF_2, proof_no=2)
    assert [c["stmt_id"] for c in out2["citations"]] == [lemma], out2["citations"]
    assert out2["proof_no"] == 2 and out2["signed_bit3"] is True, out2
    assert LEMMA_FULL in seam2.prompts[0]


# ============================================================ 护栏：读侧硬闸

def test_the_allowed_level_set_is_computed_from_the_shared_evidence_order() -> None:
    """护栏：允许集合是从"证据力序"现算的，不是抄的一份字面量。

    两处对账：① 它必须等于 `schema.EVIDENCE_KINDS` 从 `proof_review` 那一位切到最强端
    （业主的「proof_review级及以上」逐字）；② 它必须与 `verify_tools._EVIDENCE_ORDER`
    （本仓唯一的证据力序声明，弱到强）切出来的是同一集合 —— 两处漂开就是"报告说够格、
    判据说不够"，而那种错没有任何东西会红。词表里没有门槛那一档 ⇒ 空集（fail-closed：
    空集会让每一条引用都判 inadmissible，那是可见的失败，不是静默放行）。
    """
    from agentflow.tools.verify_tools import _EVIDENCE_ORDER

    kinds = tuple(S.EVIDENCE_KINDS)
    floor = VR.CITATION_EVIDENCE_FLOOR
    assert floor in kinds and floor in _EVIDENCE_ORDER, (kinds, _EVIDENCE_ORDER)
    # ① schema 的声明序（强到弱）：门槛那一位切到最强端。
    expected = set(kinds[: kinds.index(floor) + 1])
    # ② 证据力序（弱到强）：门槛那一位切到最强端。
    ordered = set(_EVIDENCE_ORDER[_EVIDENCE_ORDER.index(floor):])
    live = set(VR.admissible_evidence_kinds())
    assert live == expected == ordered, (sorted(live), sorted(expected), sorted(ordered))
    assert live == {"proof", "proof_review"}, sorted(live)
    # 反方向：低于门槛的三档一个都不许进（空串也算"读不到档位"）。
    for kind in ("cross_check", "heuristic", ""):
        assert VR.evidence_kind_admissible(kind) is False, kind


def test_signs_bit3_refuses_a_row_whose_citation_check_blocks() -> None:
    """护栏：台账那一行的硬闸（`signs_bit3` / `bit3_payload`）也认引用核实。

    为什么要这一条：写路径上的改判只挡住"V 自己这一趟"；台账是追加式文件，手写一行
    `verdict=成立` 与 V 自己判了成立，在读者眼里没有区别 ⇒ 读侧必须有同一道闸。
    这不是第二份判据：它读的就是 `citation_checks` 那一格、词表就是 `CITATION_BLOCKING`。
    """
    base = {"statement_id": "000001", "verdict": "成立", "unresolved_errors": 0}
    for verdict in sorted(VR.CITATION_BLOCKING):
        row = dict(base, citation_checks=[{"stmt_id": "000002", "verdict": verdict,
                                           "quote_verbatim": False, "note": "x"}])
        assert VR.signs_bit3(row) is False, verdict
        assert VR.bit3_payload(row) == {}, verdict
    for verdict in sorted(VR.CITATION_SIGNABLE):
        row = dict(base, citation_checks=[{"stmt_id": "000002", "verdict": verdict,
                                           "quote_verbatim": True, "note": "x"}])
        assert VR.signs_bit3(row) is True, verdict
    # 历史行（没有这一格）照旧：老台账的读数逐字不变。
    assert VR.signs_bit3(dict(base)) is True


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
    VR.record_verification(tmp_path, statement_id="000009", proof_text=text,
                           verdict=merged, citation_gate=gate)
    rows, problems = VR.list_verifications(tmp_path, statement_id="000009", limit=None)
    assert problems == [], problems
    disk = dict(rows[-1])
    # ② 承重格落盘了：材料内 True、材料外 False。
    assert [c["in_material"] for c in disk["citation_checks"]] == [True, False], disk
    assert set(disk["citation_checks"][0]) == set(VR.CITATION_CHECK_KEYS)
    # ③ 两个口同结论。
    assert VR.citation_blocks(disk) == [], VR.citation_blocks(disk)
    assert VR.signs_bit3(disk) is gate["ok"] is True
    assert VR.review_standing(tmp_path, statement_id="000009",
                              proof_text=text)["state"] == "signed"


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
           "citation_checks": [dict(c) for c in checks]}
    assert VR.signs_bit3(row) is True

    stripped = dict(row, citation_checks=[
        {k: v for k, v in c.items() if k != "in_material"} for c in row["citation_checks"]])
    # 分家的形态：闸说可以签（它在 reconciled 那批条目上算的），读侧说签不住。
    assert VR.signs_bit3(stripped) is False, "去掉 in_material 之后判据没红 ⇒ 这一格不是承重的"
    # 同一批条目若从一开始就没有这一格，两个口都会判挡（fail-closed）——
    # 分家只发生在"闸按 reconciled 算、读侧按落盘算"这一种形态上。
    assert VR.citation_gate(stripped["citation_checks"])["ok"] is False
    # 老行缺键按"材料内"读 ⇒ 阻挡条目照旧挡签。
    old = {"stmt_id": "000009", "verdict": "成立", "unresolved_errors": 0,
           "citation_checks": [{"stmt_id": "000002", "verdict": "stronger",
                                "quote_verbatim": False, "note": "x"}]}
    assert VR.citation_blocks(old) != []
    assert VR.signs_bit3(old) is False
