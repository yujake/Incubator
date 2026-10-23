# -*- coding: utf-8 -*-
"""判据（端到端主线）：多证明模型 L1 → L9 一条线走完，每跨一环断言一次。

业主 2026-10-22：「把线路彻底接通，做全面的测试样例」。这一份就是那条主线的
「一条测试样例」：同一个 tmp 工作区里，从 B 交错两份证明开始，一路走到
论文包与网页读数，中途不换工作区、不复用别的文件的夹具。

## 九环与它们各自的判据（失败消息一律点名"哪一环断的"）

| 环 | 这一环要真的连上什么 |
|---|---|
| L1 写口 | `register_statement(proofs=[{1,甲},{2,乙}])` 落成 `proof_text`=甲 + 清单含 `#2` |
| L2 签名 | 签 `(命题, #p2)` ⇒ 台账行带 `stmt_id` / `proof_no` / `proof_sha256` |
| L3 位与等级 | 签完 ⇒ `bits.evidence.reviewed_by_proof` 两张都为 true；`bits.reviewed`=any；`statement_grade` 走 `derive_grade` |
| L4 依赖二维 | `used_by="stmt:#p2"` + `path_group 1/2` ⇒ `groups_of` 给 `{2: {1: […], 2: […]}}`；不带 `#pN` 等价 `#p1` |
| L5 链闭合 | `proof_chain` 对 `(proof_no, path_group)` 二维展开，payload 带 `proof_nos` / `best_proof_no` |
| L6 对应表 | 包内 `MAPPING.json` / `MAPPING.md` / 正文附录三份一致；每行带 `proof_no` 与包内相对 `file` |
| L7 收工读数 | R10 按 `(stmt_id, proof_no)` 计数，并给 `stale_ids` / `proofs_stale` / `proofs_unreviewed`；`mapping` 格三态 |
| L8 H 分档 | 11 个客观 `mapping_*` ⇒ blocker；5 个主观 kind ⇒ info |
| L9 只读面 | evidence / artifacts 面上命题行的 `bits.reviewed` 与 `by_task_id` 读得出来，且与 L3 一致 |

## 这一份能红在哪里（不是空转的证据）

每一步的断言都带当前读数：把任一环的接线拆掉（例如让 `_attach_proofs` 不落清单、
让 `groups_of` 压回一维、让 `_leg_reading` 把 `counted` 折成一条命题一行、
让 `mapping_reading` 不读附录），对应那一步的消息会点名那一环并给出当时的读数。
L7 的两档（`proofs_unreviewed` 与 `proofs_stale`）在同一个场景里前后各出现一次，
所以"两份证明都签过"与"其中一份改过稿"不会被读成同一件事。

## 一处已知的残余（本文件刻意不把它钉成断言）

`bits.evidence.reviewed_by` 只有一格（它记的是"最近那一签"是哪一份的）。因此
"#p2 签过之后又被改了正文"这一个状态下，`evidencebits.bits_from_row` 会把
命题级的 `reviewed` 读成假（它只核最近那一签盖住的那一份），而同一条命题的
`#p1` 其实仍然 in-sync。本文件在那一处只断言逐条读数与 R10（它们走的是
`statement_review_reading`，结论正确），不把 `bits_from_row` 的那个假钉成契约。
详见交付报告里「哪几环原来其实没连上」那一节。

全部 tmp 工作区、零模型调用（V 的签名路径直接调它的写入口，不经模型）。
"""
from __future__ import annotations

import json
import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import artifacts as ART
from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import papercompile as PC
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow import sessions as SS
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_c import AgentC
from agentflow.agent_c.proof_chain import _DepGraph
from agentflow.agent_g import AgentG
from agentflow.agent_h import mapping_judge as MJ
from agentflow.store import Store
from agentflow.webui import readers as RD

#: 命题 P（登记工作区里的第一条行，号由 store 发，实得 `000000`）。
SID = S.format_id(0)
#: 第二条命题（正文里第二个 theorem 环境用它，好让对应表每一行各有台账归属）。
QID = S.format_id(1)
#: 一条实验行（正文那个 experiment 环境用它）。
EID = S.format_id(0)
#: 两条文献（依赖的根）。
LIT_A = S.format_id(9)
LIT_B = S.format_id(8)

#: 证明 #p1（canonical，落 `proof_text`）。
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"
#: 证明 #p2（落同一行的证明清单）。
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
#: #p2 签完之后又被改出来的那一版（stale 那一档用它）。
P2_EDITED = P2 + "\n3. 补一步（这一句是签完之后才改的）。"

_OK = {"verdict": "成立", "findings": []}


# ------------------------------------------------------------------ 断言消息

def _broken(link: str, what: str, got: object = "") -> str:
    """断言失败时的消息：第一句就说清是哪一环断的、断在哪一句话上。

    `got` 是当时的读数（空串 = 这一条没有读数可带）。带读数不只是为了好读：
    同一个断言在"值不对"与"根本没读到"两种情况下给出同一句消息，会让排查从
    "差一个字符"变成"猜哪一格没接上"。
    """
    head = f"{link} 断了：{what}"
    return head if got == "" else f"{head}（读数：{got!r}）"


def _proof_of(reading: dict, proof_no: int) -> dict:
    """从逐条读数里取某一份证明那一条（缺了就当场失败并给出全表）。"""
    hit = [p for p in (reading.get("proofs") or []) if int(p["proof_no"]) == int(proof_no)]
    assert hit, _broken("L3", f"逐条读数里没有 #{proof_no} 这一份", reading.get("proofs"))
    return hit[0]


# ------------------------------------------------------------------ 工作区与小动作

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _row(store: Store, stmt_id: str = SID) -> dict:
    """盘上那一行（不是内存里的缓存）。"""
    ids = [r.get("stmt_id") for r in store.rows("statements")]
    hit = [r for r in store.rows("statements") if str(r.get("stmt_id")) == stmt_id]
    assert hit, _broken("L1", f"盘上读不到命题 {stmt_id}", ids)
    return dict(hit[0])


def _own(full: str, short: str) -> dict:
    """自产命题的必填件：`doc_id` + `quote_reason`（`origin="own_result"` 那一档）。

    2026-10-22（业主裁定 B-2「没有引文 / 自己编的命题必须从『猜想』注册」）：`kind` 写成
    `conjecture`。这一组测的是多证明的端到端链路（写口 → 签名 → 收工读数），升档由
    `evidencebits.derive_grade` 按五元位现算，与入口这一栏无关。
    """
    return {"statement_full": full, "statement_text": short, "origin": "own_result",
            "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对",
            "label": short}


def _sign(store: Store, *, text: str, proof_no: int, stmt_id: str = SID) -> dict:
    """V 的签名写入口（`V.verify_proof` 签的就是它；这里不经模型）。"""
    return VR.record_verification(store.root, statement_id=stmt_id, proof_text=text,
                                  verdict=dict(_OK), verifier="agent-V", store=store,
                                  proof_no=proof_no)


def _ledger(store: Store, stmt_id: str = SID) -> list[dict]:
    rows, problems = VR.list_verifications(store.root, statement_id=stmt_id, limit=None)
    assert problems == [], _broken("L2", "验证台账里有读不出来的行", problems)
    return rows


def _edit_proof(store: Store, *, proof_no: int, text: str, stmt_id: str = SID) -> dict:
    """改某一份证明的正文（改稿是正常写入：走 `store.tx`，不许被哈希拦下）。

    `#p1` 的正文是行上的 `proof_text`，`#p2` 及以后在 `proofs` 清单里 —— 两处
    各走各的格，改一份不许碰到另一份（这是"不动 #p1"那一句的落点）。
    """
    row = _row(store, stmt_id)
    if int(proof_no) == 1:
        row["proof_text"] = text
    else:
        entries = []
        found = False
        for entry in (row.get(VR.PROOFS_KEY) or []):
            item = dict(entry)
            if int(VR.proof_no_of(item)) == int(proof_no):
                item["text"] = text
                found = True
            entries.append(item)
        assert found, _broken("L1", f"证明清单里没有 #{proof_no} 可改", row.get(VR.PROOFS_KEY))
        row[VR.PROOFS_KEY] = entries
    with store.tx("statements", actor="test", note=f"edit_proof:{stmt_id}#p{proof_no}") as tx:
        tx.upsert("statements", row, note=f"edit_proof:{stmt_id}#p{proof_no}")
    return _row(store, stmt_id)


def _reading(store: Store, stmt_id: str = SID) -> dict:
    return VR.statement_review_reading(store.root, _row(store, stmt_id))


def _r10(store: Store) -> tuple[int, dict]:
    """收工读数 R10（`closing._leg_reading` 的 `reviewed_proof_rows`）与它的 detail。"""
    return CL._leg_reading(store, "reviewed_proof_rows", store.root)


def _put_lit(store: Store, lit_id: str) -> None:
    row = S.Literature(lit_id=lit_id, title=f"文献 {lit_id}", type="J", summary="夹具",
                       path=None, added_at=S.now_iso())
    row.validate()
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())


def _put_experiment(store: Store) -> None:
    row = S.Experiment(experiment_id=EID, claim="网格收敛性检查", claim_key="grid",
                       method="numeric", evidence_kind="cross_check",
                       result="inconclusive", negation_kind="not_proved",
                       code_path="scripts/run.py", code_hash="0123456789abcdef",
                       created_at=S.now_iso(), created_by="agent-E")
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())


# ------------------------------------------------------------------ 论文包

def _write_paper(project: pathlib.Path) -> pathlib.Path:
    """写 2 个 theorem 环境 + 1 个 experiment 环境（正文里每个环境各要一行对应表）。"""
    tex = PC.package_dir(project) / PC.TEX_NAME
    tex.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join([
        "\\documentclass{article}",
        "\\begin{document}",
        "\\section{主结果}",
        "\\begin{theorem}\\label{thm:chord}弦长函数不是常值。\\end{theorem}",
        "\\begin{theorem}\\label{thm:finite}有限群的阶有限。\\end{theorem}",
        "\\begin{experiment}\\label{exp:grid}网格收敛性检查。\\end{experiment}",
        "\\end{document}",
        "",
    ])
    tex.write_bytes(body.encode("utf-8"))
    return tex


def _mapping_rows() -> list[PM.Row]:
    """对应表的四行：`P#p1` / `P#p2` 各一行（同一条定理的两份证明各占一行），
    另外两个环境各一行。`file` 一律是论文包内的相对路径。"""
    return [
        PM.Row(kind="theorem", label="thm:chord", env_no=1, ledger_id=f"stmt:{SID}",
               proof_no=1, file="proofs/p1.md",
               citation_loc_reason="我方自产命题，没有外部引文"),
        PM.Row(kind="theorem", label="thm:chord", env_no=1, ledger_id=f"stmt:{SID}#p2",
               proof_no=2, file="proofs/p2.md",
               citation_loc_reason="我方自产命题，没有外部引文"),
        PM.Row(kind="theorem", label="thm:finite", env_no=2, ledger_id=f"stmt:{QID}",
               proof_no=1, file="proofs/q.md",
               citation_loc_reason="我方自产命题，没有外部引文"),
        PM.Row(kind="experiment", label="exp:grid", env_no=1, ledger_id=f"exp:{EID}",
               proof_no=1, file="proofs/e.md",
               citation_loc_reason="我方实验，没有引文位置"),
    ]


def _write_proof_files(project: pathlib.Path) -> None:
    pkg = PC.package_dir(project)
    (pkg / "proofs").mkdir(parents=True, exist_ok=True)
    for name, text in (("p1", P1), ("p2", P2), ("q", "显然。"), ("e", "网格收敛性检查")):
        (pkg / "proofs" / f"{name}.md").write_bytes((text + "\n").encode("utf-8"))


def _build_paper(project: pathlib.Path, store: Store) -> dict:
    """正文 + 四行对应表 ⇒ 一次写口出三份（json / md / 附录），再读回来。"""
    _write_paper(project)
    _write_proof_files(project)
    PM.write_package(project, _mapping_rows())
    return PM.mapping_reading(project, workspace_root=store.root)


def _appendix_is_in_the_tex(tex_path: pathlib.Path) -> bool:
    """正文里有没有把附录印进去（`\\input{mapping-appendix}`，或整段内联）。"""
    text = tex_path.read_text(encoding="utf-8") if tex_path.is_file() else ""
    return PM.APPENDIX_INPUT in text or PM.APPENDIX_BEGIN in text


# ============================================================ 主线

def test_the_multi_proof_line_is_connected_end_to_end(tmp_path: pathlib.Path) -> None:
    """一条主线走完 L1 → L9：每跨一环断言一次，失败消息点名那一环。

    场景（与业主那张单子逐条对应）：
    1. 命题 P 有两条证明（`#p1` 甲、`#p2` 乙）；
    2. 先只签 `#p1` ⇒ R10 = 1（定理级按命题去重）、`proofs_unreviewed` 含 `P#p2`；
    3. 再签 `#p2` ⇒ 两条都 signed、逐条表两张都为 true；
    4. `#p2` 的依赖有两组可选路径（组内 AND）⇒ 依赖读侧是二维的、链读到多条候选；
    5. 改 `#p2` 正文（不动 `#p1`）⇒ `#p2` 读 stale、`#p1` 仍 signed、R10 仍 1；
    6. 生成论文包 ⇒ 三份一致、mapping 格 pass；
    7. `#p2` 改回签名时那一份 ⇒ 又读 signed（不许要求重签）。
    """
    st = _ws(tmp_path)
    b = AgentB(st, extractor=None, extract_text=None, config={})

    # ------------------------------------------------------------ L1 写口
    out = b.register_statement(
        **_own("设 G 是 3-正则群；则弦长函数不是常值。", "弦长函数不是常值"),
        proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])
    assert out.get("ok") is True, _broken("L1", "两条证明一次交不进去", out)
    assert out.get("stmt_id") == SID, _broken("L1", "落下来的命题号不是工作区里那一条", out)
    row = _row(st)
    assert row["proof_text"] == P1, _broken(
        "L1", "`proof_text` 不是 #p1 的正文（canonical 那一格被 #p2 顶了）", row.get("proof_text"))
    listed = row.get(VR.PROOFS_KEY)
    assert isinstance(listed, list) and [int(p["proof_no"]) for p in listed] == [2], _broken(
        "L1", "证明清单里没有 #2（或 #1 也被塞进清单：同一格两个权威）", listed)
    assert listed[0].get("text") == P2, _broken("L1", "清单里 #2 的正文不是乙", listed[0])
    assert [no for no, _ in VR.proof_list(row)] == [1, 2], _broken(
        "L1", "证明号读口径（`verifications.proof_list`）读不出 #1 与 #2", VR.proof_list(row))

    # 第二条命题 + 一条实验行：论文包要"每个环境一行"，它们各要一条台账行。
    q = b.register_statement(**_own("设 H 是有限群；则 H 的阶有限。", "有限群的阶有限"),
                             proof_text="显然。")
    assert q.get("ok") is True and q.get("stmt_id") == QID, _broken(
        "L1", "第二条命题没落成 000001", q)
    _put_experiment(st)

    # ------------------------------------------------------------ L2 签名
    signed1 = _sign(st, text=P1, proof_no=1)
    assert signed1.get("proof_no") == 1, _broken("L2", "签 #p1 的签名行没记证明号", signed1)
    assert signed1.get("stmt_id") == SID and signed1.get("statement_id") == SID, _broken(
        "L2", "签名行上的 `stmt_id` 不是被审的那条命题", signed1)
    assert signed1.get("proof_sha256") == VR.proof_sha(P1), _broken(
        "L2", "签名行上的 sha 不是 #p1 那一份的", signed1.get("proof_sha256"))
    disk = _ledger(st)[-1]
    assert (disk.get("stmt_id"), disk.get("proof_no")) == (SID, 1), _broken(
        "L2", "盘上那一行不是 (命题, #p1)", disk)
    assert disk.get("proof_sha256") == VR.proof_sha(P1), _broken(
        "L2", "盘上那一行的 sha 与签名时那一份不符", disk.get("proof_sha256"))

    # 借光负控（与 L3 同一处）：只签 #p1 不许把 #p2 读成审过，而 #p1 那一条自己
    # 必须到 pre_theorem（等级的唯一入口是 `derive_grade`）。
    bits_now = _row(st)["bits"]
    per = EB.reviewed_by_proof(_row(st))
    assert per == {1: True, 2: False}, _broken(
        "L3", "只签 #p1 时逐条表不是 {1: True, 2: False}（#p2 借了光）", per)
    assert bits_now.get("reviewed") is True, _broken(
        "L3", "汇总位 `bits.reviewed` 不是「任一份成立即为 True」", bits_now.get("reviewed"))
    assert per.get(2) is not True, _broken("L3", "逐条表把没签的 #p2 记成了已签", per)
    assert bits_now.get("grade") == "pre_theorem", _broken(
        "L3", "只签 #p1 时这一行没到 pre_theorem（`derive_grade` 现算）", bits_now.get("grade"))
    partial = _reading(st)
    assert _proof_of(partial, 1)["grade"] == "pre_theorem", _broken(
        "L3", "签过的 #p1 自己那一档没到 pre_theorem", _proof_of(partial, 1))
    assert _proof_of(partial, 2)["grade"] == "conjecture", _broken(
        "L3", "#p2 自己的档位被 #p1 的签抬起来了", _proof_of(partial, 2))

    # ------------------------------------------------------------ L7 第一档：只签了 #p1
    n1, det1 = _r10(st)
    assert n1 == 1, _broken("L7", "只签 #p1 时 R10 不是 1（定理级按命题去重）", (n1, det1.get("counted")))
    assert [(c.get("stmt_id"), c.get("proof_no")) for c in (det1.get("counted") or [])] == [(SID, 1)], (
        _broken("L7", "R10 的计数键不是 `(stmt_id, proof_no)`", det1.get("counted")))
    assert det1.get("counted_statements") == 1 and det1.get("counted_total") == 1, _broken(
        "L7", "定理级汇总数与逐条证明数在这一步应当都是 1", det1)
    assert det1.get("proofs_unreviewed") == [f"{SID}#p2"], _broken(
        "L7", "`proofs_unreviewed` 里没有 P#p2（没签的那一份没被点名）", det1.get("proofs_unreviewed"))
    assert det1.get("proofs_stale") == [], _broken(
        "L7", "一次都没签的 #p2 被记成了 stale（两档折平了）", det1.get("proofs_stale"))

    # ------------------------------------------------------------ L2 签 #p2 + L3 位与等级
    signed2 = _sign(st, text=P2, proof_no=2)
    assert signed2.get("proof_no") == 2, _broken("L2", "签 #p2 的签名行没记证明号", signed2)
    assert signed2.get("proof_sha256") == VR.proof_sha(P2), _broken(
        "L2", "签 #p2 时记下的 sha 不是乙那一份的", signed2.get("proof_sha256"))
    wb = signed2.get("statement_writeback") or {}
    assert wb.get("written") is True and wb.get("rolled_back") is False, _broken(
        "L2", "签 #p2 之后第 3 位没有写回（或写回失败）", wb)
    assert wb.get("proof_no") == 2, _broken("L2", "写回的不是 #p2 那一格", wb)
    ledger_pairs = [(r.get("stmt_id"), r.get("proof_no")) for r in _ledger(st)]
    assert (SID, 1) in ledger_pairs and (SID, 2) in ledger_pairs, _broken(
        "L2", "台账里不是两条证明各一行", ledger_pairs)

    row = _row(st)
    bits = row["bits"]
    pocket = (bits.get("evidence") or {}).get(EB.REVIEWED_BY_PROOF_KEY)
    assert pocket == {"1": True, "2": True}, _broken(
        "L3", "`bits.evidence.reviewed_by_proof` 不是两张都 true", pocket)
    assert EB.reviewed_by_proof(row) == {1: True, 2: True}, _broken(
        "L3", "逐条表的读口径与写进去的那一格不一致", EB.reviewed_by_proof(row))
    assert bits.get("reviewed") is True, _broken("L3", "汇总位不是 any", bits.get("reviewed"))
    assert bits.get("grade") == "pre_theorem", _broken(
        "L3", "有证明过程 + 审过 ⇒ 现算等级应当是 pre_theorem", bits.get("grade"))

    reading = _reading(st)
    assert reading.get("reviewed") is True, _broken("L3", "命题级读数不是「至少一条 in-sync」", reading)
    assert _proof_of(reading, 1)["state"] == "signed", _broken("L3", "#p1 不是 signed", reading["proofs"])
    assert _proof_of(reading, 2)["state"] == "signed", _broken("L3", "#p2 不是 signed", reading["proofs"])
    assert _proof_of(reading, 2)["grade"] == "pre_theorem", _broken(
        "L3", "#p2 自己那一档没到 pre_theorem", _proof_of(reading, 2))
    # 定理级等级 = 在 in-sync 的证明里取最高（唯一入口 `derive_grade`）。
    grade = VR.statement_grade(st.root, row)
    assert grade == reading["grade"] == "pre_theorem", _broken(
        "L3", "`statement_grade` 与逐条读数的汇总档不一致", (grade, reading.get("grade")))
    assert grade == EB.derive_grade({**EB.bits_from_row(row), "reviewed": True}, kind="theorem"), _broken(
        "L3", "定理级等级不是 `derive_grade` 现算出来的", grade)

    # ------------------------------------------------------------ L7 两档之间：都签过
    n2, det2 = _r10(st)
    assert n2 == 1, _broken("L7", "两条证明都签过之后 R10 不是 1（按命题去重）", n2)
    assert det2.get("counted_total") == 2, _broken(
        "L7", "逐条证明数不是 2（两条签过的证明各占一条）", det2.get("counted_total"))
    assert det2.get("counted_statements") == 1, _broken(
        "L7", "定理级汇总数被两份证明吹成了 2", det2.get("counted_statements"))
    assert det2.get("proofs_unreviewed") == [] and det2.get("proofs_stale") == [], _broken(
        "L7", "两条都签过之后还有未审/待复核的证明",
        (det2.get("proofs_unreviewed"), det2.get("proofs_stale")))

    # ------------------------------------------------------------ L4 依赖二维
    _put_lit(st, LIT_A)
    _put_lit(st, LIT_B)
    g = AgentG(st)
    # #p1 那一条证明：一条边指到 Q（Q 再指到文献 ⇒ 两跳，比 #p2 那两条长）。
    g.register_dependency(used_by=f"stmt:{SID}", proof_no=1, kind="theorem",
                          label="经由有限群那条命题", source_stmt_id=QID, path_group=1,
                          status="closed")
    g.register_dependency(used_by=f"stmt:{QID}", kind="prior_art", label="文献 9",
                          source_lit_id=LIT_A, path_group=1, status="closed")
    # #p2 那一条证明：组 1 两条边（组内 AND），组 2 一条边（组间 OR）。
    g.register_dependency(used_by=f"stmt:{SID}", proof_no=2, kind="prior_art", label="前提甲",
                          source_lit_id=LIT_A, path_group=1, status="closed")
    g.register_dependency(used_by=f"stmt:{SID}", proof_no=2, kind="prior_art", label="前提乙",
                          source_lit_id=LIT_B, path_group=1, status="closed")
    g.register_dependency(used_by=f"stmt:{SID}", proof_no=2, kind="prior_art", label="备选路径",
                          source_lit_id=LIT_B, path_group=2, status="closed")

    dep_rows = [dict(r) for r in st.rows("dependencies")]
    tails = sorted({str(r.get("used_by")) for r in dep_rows})
    assert f"stmt:{SID}#p2" in tails, _broken(
        "L4", "写侧没有把证明号落到 `used_by` 的尾巴上（`stmt:#p2` 不见了）", tails)
    assert f"stmt:{SID}" in tails, _broken(
        "L4", "不带 `#pN` 的那一条依赖没落成 canonical 写法", tails)

    graph = _DepGraph(stmts=[dict(r) for r in st.rows("statements")], deps=dep_rows,
                      exps=[dict(r) for r in st.rows("experiments")],
                      lits=[dict(r) for r in st.rows("literature")])
    two_d = graph.groups_of(SID)
    assert sorted(two_d) == [1, 2], _broken(
        "L4", "`groups_of` 第一层不是证明号（改前那一维读不到 #p2）", sorted(two_d))
    assert sorted(two_d[2]) == [1, 2], _broken("L4", "`#p2` 的路径组不是 {1, 2}", sorted(two_d[2]))
    assert len(two_d[2][1]) == 2 and len(two_d[2][2]) == 1, _broken(
        "L4", "组内 AND 的边数不对（组 1 应当两条、组 2 一条）",
        {grp: len(edges) for grp, edges in two_d[2].items()})
    assert sorted(two_d[1]) == [1] and len(two_d[1][1]) == 1, _broken(
        "L4", "不带 `#pN` 的那条边没有落在 #p1 的组 1 上",
        {k: len(v) for k, v in two_d[1].items()})
    # 证明号那一维不许串门：`#p2` 的边不许出现在第 1 条证明下。
    assert [d.get("label") for d in two_d[1][1]] == ["经由有限群那条命题"], _broken(
        "L4", "#p1 的组 1 里混进了别的证明的边", two_d[1][1])

    # ------------------------------------------------------------ L5 链闭合
    rep = AgentC(st).proof_chain(SID, k=2)
    assert rep.ok is True, _broken("L5", "`proof_chain` 没读成", rep.error)
    payload = rep.payload
    assert payload.get("proof_nos") == [1, 2], _broken(
        "L5", "payload 的 `proof_nos` 不是 [1, 2]", payload.get("proof_nos"))
    assert payload.get("groups_total") == 3, _broken(
        "L5", "二维展开之后应当是 3 条候选路径（#p1 一条 + #p2 两条）", payload.get("groups_total"))
    got_pairs = sorted((int(x["proof_no"]), int(x["group"])) for x in payload["groups"])
    assert got_pairs == [(1, 1), (2, 1), (2, 2)], _broken(
        "L5", "每条候选路径的 `(proof_no, path_group)` 不是 {(1,1),(2,1),(2,2)}", got_pairs)
    lengths = {(int(x["proof_no"]), int(x["group"])): int(x["length"]) for x in payload["groups"]}
    assert lengths == {(1, 1): 2, (2, 1): 1, (2, 2): 1}, _broken(
        "L5", "各条路径的长度不是 (1,1)=2 / (2,1)=1 / (2,2)=1（组内 AND 会把组 1 读成两跳）",
        lengths)
    assert all(x["reached"] for x in payload["groups"]), _broken(
        "L5", "有候选路径没走到根（链没闭合）",
        [(x["proof_no"], x["group"], x["reached"]) for x in payload["groups"]])
    assert payload.get("best_proof_no") == 2 and payload.get("best_group") == 1, _broken(
        "L5", "最短那一条不是第 2 条证明的第 1 组",
        (payload.get("best_proof_no"), payload.get("best_group")))
    # 每一跳都自己带着"第几条证明"（否则二维只是把总长写进 payload 一个数）。
    assert {int(h["proof_no"]) for x in payload["groups"] for h in x["hops"]} == {1, 2}, _broken(
        "L5", "有跳的 `proof_no` 落在两条证明之外（或缺失）",
        [(h.get("node"), h.get("proof_no")) for x in payload["groups"] for h in x["hops"]])
    # 单条证明的命题：读数退化成改前形状（证明号恒为 1）。
    q_chain = AgentC(st).proof_chain(QID, k=1)
    assert q_chain.ok is True and q_chain.payload.get("proof_nos") == [1], _broken(
        "L5", "只有一条证明的命题读出了别的证明号", q_chain.payload.get("proof_nos"))
    assert q_chain.payload.get("best_proof_no") == 1, _broken(
        "L5", "单证明命题的 `best_proof_no` 不是 1", q_chain.payload.get("best_proof_no"))

    # ------------------------------------------------------------ 改 #p2 正文 ⇒ L7 stale 一档
    before_bits = _row(st)["bits"]
    after = _edit_proof(st, proof_no=2, text=P2_EDITED)
    assert after.get("proof_text") == P1, _broken(
        "L1", "改 #p2 时把 #p1 的正文也改了", after.get("proof_text"))
    assert VR.proof_text_of(after, 2) == P2_EDITED, _broken(
        "L1", "改 #p2 没落到那一份证明上", VR.proof_text_of(after, 2))
    assert after.get("bits") == before_bits, _broken(
        "L3", "改稿这一笔把位也改了（写侧不许回头改凭据）", after.get("bits"))

    reading2 = _reading(st)
    assert _proof_of(reading2, 2)["state"] == "stale", _broken(
        "L7", "改过正文的 #p2 没有读成 stale", _proof_of(reading2, 2))
    assert _proof_of(reading2, 1)["state"] == "signed", _broken(
        "L7", "没被改过的 #p1 跟着 #p2 一起变成非 signed 了", _proof_of(reading2, 1))
    assert reading2.get("reviewed") is True, _broken(
        "L7", "命题级读数不是「还有一条 in-sync 的证明」", reading2.get("reviewed"))
    assert reading2.get("proofs_stale") == [f"{SID}#p2"], _broken(
        "L7", "`proofs_stale` 里没有 P#p2", reading2.get("proofs_stale"))
    assert reading2.get("proofs_unreviewed") == [], _broken(
        "L7", "签过但过期的 #p2 被记成了「还没审」", reading2.get("proofs_unreviewed"))
    # 台账那一行是历史：它仍留在签名当时那一份上。
    assert _ledger(st)[-1].get("proof_sha256") == VR.proof_sha(P2), _broken(
        "L2", "改稿之后台账那一行的 sha 跟着变了（历史被改写）", _ledger(st)[-1])

    n3, det3 = _r10(st)
    assert n3 == 1, _broken("L7", "改 #p2 之后 R10 不是 1（#p1 仍签着）", (n3, det3.get("counted")))
    assert [(c.get("stmt_id"), c.get("proof_no")) for c in (det3.get("counted") or [])] == [(SID, 1)], (
        _broken("L7", "R10 把待复核的 #p2 仍算进了计数", det3.get("counted")))
    assert det3.get("proofs_stale") == [f"{SID}#p2"], _broken(
        "L7", "R10 的 `proofs_stale` 没有点名 P#p2", det3.get("proofs_stale"))
    assert det3.get("proofs_unreviewed") == [], _broken(
        "L7", "R10 把 stale 折进了 unreviewed", det3.get("proofs_unreviewed"))

    # ------------------------------------------------------------ L6 对应表 + L7 mapping 格
    project = st.root / "proj"
    mapping = _build_paper(project, st)
    assert mapping.get("state") == "pass", _broken(
        "L6", "论文包与对应表没判成 pass", (mapping.get("state"), mapping.get("problems")))
    assert mapping.get("problems") == [], _broken("L6", "pass 却有 problems", mapping.get("problems"))
    assert mapping.get("rows") == 4 and mapping.get("envs") == 3, _broken(
        "L6", "行数/环境数不对（4 行对应 2 个 theorem + 1 个 experiment）",
        (mapping.get("rows"), mapping.get("envs")))
    assert mapping.get("md_state") == "present" and mapping.get("appendix_state") == "present", _broken(
        "L6", "人读那一份或正文附录没对上 json",
        (mapping.get("md_state"), mapping.get("appendix_state")))

    pkg = PC.package_dir(project)
    json_path = pkg / PM.MAPPING_JSON_NAME
    md_path = pkg / PM.MAPPING_MD_NAME
    frag = pkg / PM.APPENDIX_FILE_NAME
    rows_out = PM.parse_rows(json.loads(json_path.read_text(encoding="utf-8")))[0]
    # 三份一致：md 与附录都必须等于同一批行渲染出来的那两份（逐字）。
    assert md_path.read_text(encoding="utf-8") == PM.render_mapping_markdown(rows_out), _broken(
        "L6", "MAPPING.md 不是由盘上 json 渲染出来的那一份（手抄/漂移）")
    frag_text = frag.read_text(encoding="utf-8")
    assert frag_text.strip() == PM.render_appendix(rows_out).strip(), _broken(
        "L6", "正文附录不是由盘上 json 渲染出来的那一份（手抄/漂移）")
    assert _appendix_is_in_the_tex(pkg / PC.TEX_NAME), _broken(
        "L6", "正文没把附录印进去（没有 `\\input{mapping-appendix}`）")
    # 每行都带 proof_no 与包内相对 file，且 P#p1 / P#p2 各占一行。
    for item in rows_out:
        assert int(item.proof_no) >= 1, _broken("L6", "有一行没带 proof_no", item)
        assert item.file and not pathlib.PurePosixPath(item.file).is_absolute(), _broken(
            "L6", "有一行的 file 不是包内相对路径", item.file)
        assert (pkg / item.file).is_file(), _broken("L6", "有一行的 file 在包里不存在", item.file)
    pairs = [(item.label, int(item.proof_no)) for item in rows_out if item.kind == "theorem"]
    assert pairs.count(("thm:chord", 1)) == 1 and pairs.count(("thm:chord", 2)) == 1, _broken(
        "L6", "同一条定理的两份证明没有各占一行", pairs)
    keys = PM.appendix_row_keys(frag_text)
    assert len(keys) == 4, _broken("L6", "附录里可机器读的行数不是 4", keys)
    proof_cells = [line.split("|")[4] for line in frag_text.splitlines()
                   if line.strip().startswith(PM.APPENDIX_ROW_PREFIX.strip())]
    assert sorted(proof_cells) == ["1", "1", "1", "2"], _broken(
        "L6", "附录每一行的证明号一列不是 [1, 1, 1, 2]", proof_cells)

    closing = CL.ClosingReport()
    CL._check_mapping(closing, str(project), st)
    cell = closing.readings["mapping"]
    assert cell.get("state") == "pass", _broken(
        "L7", "收工读数里 mapping 格不是 pass", (cell.get("state"), cell.get("reason")))
    assert cell.get("blockers") == 0 and closing.findings == [], _broken(
        "L7", "mapping 格 pass 却挂着 blocker", [(f.code, f.level) for f in closing.findings])

    # ------------------------------------------------------------ L8 H 分档
    # 20 = 四类客观 kind + 引文两格 + 人读那份两格 + 论文侧三条 + Lean 那两格四条
    # （业主 2026-10-22 追加：有 Lean 产出时 `lean_file` / `lean_target` 必填）
    # + 数值实验定理五条（业主 2026-10-23，E-1：证明栏是程序、两块读数与出处都得核）。
    assert len(MJ.BLOCKING_KINDS) == 20, _broken(
        "L8", "客观档不是 20 个 kind", MJ.BLOCKING_KINDS)
    assert set(MJ.BLOCKING_KINDS) == set(PM.ALL_PROBLEM_KINDS), _broken(
        "L8", "客观档与 papermapping 会产出的 kind 不一致",
        sorted(set(PM.ALL_PROBLEM_KINDS) ^ set(MJ.BLOCKING_KINDS)))
    assert len(MJ.SUBJECTIVE_KINDS) == 5, _broken("L8", "主观档不是 5 个 kind", MJ.SUBJECTIVE_KINDS)
    assert all(MJ.level_of(k) == MJ.LEVEL_BLOCKER for k in MJ.BLOCKING_KINDS), _broken(
        "L8", "客观档里有不是 blocker 的", {k: MJ.level_of(k) for k in MJ.BLOCKING_KINDS})
    assert all(MJ.level_of(k) == MJ.LEVEL_INFO for k in MJ.SUBJECTIVE_KINDS), _broken(
        "L8", "主观档里有不是 info 的", {k: MJ.level_of(k) for k in MJ.SUBJECTIVE_KINDS})
    # 端到端那一半：把一行指到包里不存在的文件 ⇒ 客观 kind 必须落成 blocker 的 Finding。
    moved = pkg / "proofs" / "p2.md"
    saved = moved.read_bytes()
    moved.unlink()
    try:
        broken_reading = PM.mapping_reading(project, workspace_root=st.root)
        assert broken_reading.get("state") == "fail", _broken(
            "L8", "少一份 file 时对应表没判成 fail", broken_reading.get("state"))
        broken_closing = CL.ClosingReport()
        CL._check_mapping(broken_closing, str(project), st)
        blockers = [(f.code, f.level) for f in broken_closing.findings]
        assert ("mapping_file_missing", MJ.LEVEL_BLOCKER) in blockers, _broken(
            "L8", "客观 kind 没落成 blocker 的 Finding", blockers)
    finally:
        moved.write_bytes(saved)
    assert PM.mapping_reading(project, workspace_root=st.root).get("state") == "pass", _broken(
        "L8", "把 file 放回去之后没有回到 pass（正控失败）")

    # ------------------------------------------------------------ L7 + L3：改回签名时那一份
    _edit_proof(st, proof_no=2, text=P2)
    reading3 = _reading(st)
    assert _proof_of(reading3, 2)["state"] == "signed", _broken(
        "L7", "把 #p2 改回签名时那一份之后仍不是 signed（要求重签了）", _proof_of(reading3, 2))
    assert reading3.get("proofs_stale") == [], _broken(
        "L7", "改回去之后 `proofs_stale` 还挂着 P#p2", reading3.get("proofs_stale"))
    assert reading3.get("reviewed") is True and reading3.get("grade") == "pre_theorem", _broken(
        "L7", "改回去之后命题级读数没回到 pre_theorem", reading3)
    assert _ledger(st)[-1].get("verification_id") == signed2.get("verification_id"), _broken(
        "L2", "改回正文时又签了一次（台账多了一行）",
        [r.get("verification_id") for r in _ledger(st)])
    n4, det4 = _r10(st)
    assert n4 == 1 and det4.get("counted_total") == 2, _broken(
        "L7", "改回去之后 R10 没回到 1 条命题 / 2 条证明", (n4, det4.get("counted_total")))
    assert det4.get("proofs_stale") == [] and det4.get("proofs_unreviewed") == [], _broken(
        "L7", "改回去之后 R10 仍挂着 stale/unreviewed",
        (det4.get("proofs_stale"), det4.get("proofs_unreviewed")))
    # 论文包不受正文改动影响（S2 那条判据在同一场景里再核一次）。
    assert PM.mapping_reading(project, workspace_root=st.root).get("state") == "pass", _broken(
        "L6", "改回证明正文之后论文包那一格掉了（正文排版与 proof_text 无关）")

    # ------------------------------------------------------------ L9 只读面
    art_file = pkg / "proofs" / "e.md"
    art_entry = ART.record(st.root, path=art_file, producer="agent-G", note="实验正文")
    # 写一段会话事件：命题号与产物路径都带着编号，`by_task_id` 才有东西可反查。
    _event, problem = SS.append(st.root, {
        "kind": "agent_step", "task_id": "t-e2e-l9",
        "note": f"写了 stmt:{SID}，并把证明落到 {art_entry.get('path')}"}, sid="e2e")
    assert problem == "", _broken("L9", "会话事件没写成（只读面就没有可反查的编号）", problem)

    face = RD.evidence_chain(st.root, st)
    assert face.get("tri") == RD.TRI_COMPUTED, _broken(
        "L9", "证据面没读成 computed", (face.get("tri"), face.get("reason")))
    rows_face = {str(r.get("stmt_id")): r for r in (face.get("statements") or [])}
    assert SID in rows_face, _broken("L9", "命题行没出现在证据面上", sorted(rows_face))
    face_row = rows_face[SID]
    assert isinstance(face_row.get("bits"), dict), _broken(
        "L9", "证据面上的命题行没有 bits 这一格（reviewed 就读不出来）",
        type(face_row.get("bits")).__name__)
    assert face_row["bits"].get("reviewed") is True, _broken(
        "L9", "证据面上的 reviewed 与 L3 的汇总位不一致", face_row["bits"].get("reviewed"))
    assert face_row["bits"].get("reviewed") == _reading(st).get("reviewed"), _broken(
        "L9", "证据面读到的 reviewed 与逐条读数的汇总位不一致",
        (face_row["bits"], _reading(st).get("reviewed")))
    assert EB.reviewed_by_proof(face_row) == {1: True, 2: True}, _broken(
        "L9", "证据面上读不出逐条证明那一张表", EB.reviewed_by_proof(face_row))
    assert face_row.get("by_task_id") == "t-e2e-l9", _broken(
        "L9", "命题行的 by_task_id 没反查到那一趟", face_row.get("by_task_id"))
    assert face_row.get("by_task_id_tri") == "event", _broken(
        "L9", "命题行的 by_task_id 三态不是 event", face_row.get("by_task_id_tri"))
    q_row = rows_face.get(QID) or {}
    assert q_row.get("by_task_id") == "" and q_row.get("by_task_id_tri") == "missing", _broken(
        "L9", "没有事件提到的那条命题应当落在 missing（不是 not_applicable）",
        (q_row.get("by_task_id"), q_row.get("by_task_id_tri")))
    face_art = RD.artifacts_face(st.root, st)
    art_path = str(art_entry.get("path") or "")
    art_rows = [r for r in (face_art.get("ledger") or []) if str(r.get("path")) == art_path]
    assert art_rows, _broken("L9", "产物面读不到刚登记的那一条",
                             [(r.get("path"), r.get("by_task_id"))
                              for r in (face_art.get("ledger") or [])])
    assert art_rows[0].get("by_task_id") == "t-e2e-l9", _broken(
        "L9", "产物行的 by_task_id 没反查到那一趟", art_rows[0].get("by_task_id"))
    assert art_rows[0].get("by_task_id_tri") == "event", _broken(
        "L9", "产物行的 by_task_id 三态不是 event", art_rows[0].get("by_task_id_tri"))
