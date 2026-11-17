# -*- coding: utf-8 -*-
"""DOCGATE2 判据：DOCGATE1 实测交回的两条侧门（零签也能交论文）。

## 现场（`temp/docgate1/PROOF-third-path.txt`，真机口径的探针）

DOCGATE1 把成文门装到 `doc.build_document` 与 `doc.write_mapping`（同一实现
`researchbase.writing_gate`），但同一个工作区还有两条路绕过去：

```text
① table.create(table="documents", …)  零签 / 零地基 / 引用不存在的 stmt:000000 ⇒ ok=True
   （documents 不在 store.DIRECT_WRITE_REFUSED；那条 markdown 盘上根本不存在）
② fs.write('out/paper/main.tex')      零签 ⇒ ok=True 真落盘（论文正文这一层没有成文门）
```

## 这一组守什么

| 判据 | 造什么 | 期望 | 改前红在哪 |
|---|---|---|---|
| a | G 用 `table.create("documents")` 造一行（零签 / 零地基） | 受控拒 `direct_write_refused`、`documents` 0 行、拒信点名 `doc.build_document` / `doc.write_mapping` | 改前 `ok=True`、真写进去一行 |
| a′ | 不经工具层、直接开一笔 `tool:` 事务写 `documents` | 提交块同样拒（结构性那一半） | 改前落盘 |
| b | G 用 `fs.write` 写 `out/paper/main.tex`（零签 / 零地基） | 受控拒 `no_evidence_chain`（同一道 `writing_gate`）、盘上不多一个字节 | 改前 `ok=True`、真落盘 |
| b′ | G 用 `fs.move` 把 `notes/` 里的正文搬进 `out/paper/` | 受控拒、目标不在盘上、源还在 | 改前搬得进去（换一个写口就绕过 b） |
| c | 有 ≥1 条有效地基，或 ≥1 份签 | 两条正路（`fs.write` 正文 / `doc.build_document`）都放行 | ——（正控） |
| d | 非成文路径 | `fs.write('notes/x.md')`、`table.create("experiments")` 照旧 | ——（正控） |
| e | 把两道拒打桩关掉（`direct_write_refusal` 恒空 / `writing_gate` 恒放行） | a / b 必红（同一场景真写得进去） | 反真空 |
| f | `reports/<谁>-proof-<号>.md` 的新建档（F 写 b-proof、M 写 e-proof、没挂角色写 f-proof） | 保留表拒 `reserved_framework_artifact`（"只有框架能写"） | 改前这三条 `ok=True` |
| g | 正控：F 写 `notes/x.md`、E 写 `reports/e-num-*` | 照旧放行（不许扩成"谁都不许写"） | —— |
| h | 反真空：把保留表里那一行摘掉 | f 那批写入必须成功（"被拒"来自那一行） | —— |

## 为什么 c 的"两条路"是两条正路

`documents` 进 `store.DIRECT_WRITE_REFUSED` 是结构性的（与签/地基无关：这张表
由 `doc.build_document` 一处写，和 `statements` 由秘书一处写同形）—— 所以 c 的
"不许一刀切封死"判的是 `doc.build_document` / `doc.write_mapping` 这两条正路在
有料时照旧通行，以及 ② 的 `fs.write` 在有料时照旧通行；`table.create("documents")`
在所有档位都受控拒（a 格单独判，且 c 里再判一次"有料也不放宽"）。

判据只落临时工作区，不碰 `projects/*`。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import researchbase as RB
from agentflow import schema as S
from agentflow import store as store_mod
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import fs_tools as FT
from agentflow.tools import table_tools

#: 两个受控码：① 结构性直写拒（与 statements 同族）、② 成文门（与 doc.* 同族）。
DIRECT_KIND = store_mod.DIRECT_WRITE_REFUSED
GATE_KIND = "no_evidence_chain"

#: 保留表里"只有框架能写"那一档的两个字面量（`fs_tools` 的常量另由 f 的读数判据钉住；
#: 这里各写一次，是为了让这一份判据在那一档还没落地时也能跑出行为的红，
#: 而不是在收集期就 AttributeError）。
MANUSCRIPT_ONLY_ROLE = "+"
PROOF_SHAPE_RULE_KIND = "proofshape"

#: 真机 T2 前后那一刻（19:42:33 落文 / 19:43:40 第一份签）；夹具时间戳写死。
TS = "2026-11-17T19:42:33+08:00"

#: `PROOF-third-path.txt` ③ 那一行的形状（逐格照抄：它当时 `ok=True` 真落库了）。
DOCUMENT_ROW: dict = {
    "doc_id": "000099", "kind": "note", "title": "绕过成文门的一份手稿",
    "markdown_path": "documents/000099.md", "sections": [], "open_problems": [],
    "status": "draft", "review_rounds": 0, "revision": 1,
    "created_at": TS, "updated_at": TS, "created_by": "agent-G",
    "claims": [{"claim_id": "claim-1", "text": "两族闭式的坐标型推导在交叉验证下成立",
                "citations": ["stmt:000000"], "evidence_kind": "cross_check",
                "disclaimer": "数值交叉验证，不构成证明", "section": "1"}],
}

PAPER_BODY = "\\documentclass{article}\n\\begin{document}\n零签写的正文\n\\end{document}\n"


# ---------------------------------------------------------------- 夹具


def _ws(tmp_path: pathlib.Path) -> tuple[Store, object]:
    """一个真工作区：`data/`、`out/`、`reports/` 都在同一个根下（与真机同口径）。"""
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    (root / "reports").mkdir(parents=True, exist_ok=True)
    reg = build_registry(store=st, workspace_root=root).registry
    return st, reg


def _call(reg, role: str, tool: str, **params):
    """按某个角色的身份调一次（`calling_as` 与真机同一条挂点）。"""
    with calling_as("t-docgate2", role):
        return reg.call(tool, role=role, **params)


def _statement(st: Store, stmt_id: str, *, proof: str = "") -> None:
    """一行命题：`proof=""` = "只登记了个标题"（真机 35 行的形状）。"""
    stmt = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem", label=f"Theorem {stmt_id}",
        statement_text="命题短版", statement_full="若假设 A 成立，则结论 B 成立",
        proof_text=proof, quote_verified=None,
        quote_reason="还没校验：这一条没有可比的全文",
        evidence_kind="cross_check", status="active", created_at=TS)
    stmt.validate()
    with st.tx("statements", actor="test", note="stmt probe") as tx:
        tx.upsert("statements", stmt.to_dict(), note="stmt probe")


def _sign(st: Store, artifact_path: str = "reports/f-proof-000000.md",
          *, sha: str = "d" * 64) -> str:
    """按 `vsigns` 的签文件形状落一份签（`signed_table` 只认那两格）。"""
    d = st.root / "out" / "vsigns"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "vsign/1", "artifact_sha": sha, "artifact_path": artifact_path,
           "statement_id": "", "at": "2026-11-17T19:43:40", "verdict": "成立",
           "streak": 3, "need": 3, "ledger": "", "written_by": "secretary:F"}
    (d / f"{sha}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return sha


def _claims() -> list[dict]:
    return [{"text": "两族闭式的坐标型推导在交叉验证下成立", "citations": ["stmt:000000"],
             "evidence_kind": "cross_check", "section": "1",
             "disclaimer": "数值交叉验证，不构成证明"}]


def _build(reg):
    return _call(reg, "G", "doc.build_document", kind="note", title="研究手稿",
                 claims=_claims())


# ================================================================ a) 通用写口造 documents


def test_a_table_create_documents_is_refused_and_points_at_the_real_road(
        tmp_path: pathlib.Path) -> None:
    """a：零签 / 零地基 / 引用不存在的 `stmt:000000` ⇒ 通用写口受控拒、0 行、零落盘。"""
    st, reg = _ws(tmp_path)
    res = _call(reg, "G", "table.create", table="documents", row=dict(DOCUMENT_ROW))

    assert res.ok is False, ("改前这里 ok=True 并真写进去一行", res.data, res.meta)
    assert res.meta.get("kind") == DIRECT_KIND, res.meta
    msg = str(res.error or "")
    assert DIRECT_KIND in msg, msg
    # 拒信必须指向正路（不是只说"不许"）
    assert "doc.build_document" in msg, msg
    assert "doc.write_mapping" in msg, msg
    assert "table.delete" in msg, msg                  # 删除不受限，如实说
    # 一行都没写、盘上也不多一份 markdown
    assert st.rows("documents") == [], st.rows("documents")
    assert not (st.root / "documents" / "000099.md").exists()


def test_a_the_bare_tool_transaction_is_refused_too(tmp_path: pathlib.Path) -> None:
    """a′：绕过工具层、直接开一笔 `tool:` 事务写 documents ⇒ 提交块同样拒（结构性兜底）。"""
    st, _reg = _ws(tmp_path)
    with pytest.raises(ValueError) as caught:
        with st.tx("documents", actor="tool", note="tool:table.create:documents") as tx:
            tx.upsert("documents", {**{k: v for k, v in DOCUMENT_ROW.items() if k != "doc_id"},
                                    "doc_id": S.format_id(0)})
    assert DIRECT_KIND in str(caught.value), caught.value
    assert st.rows("documents") == []


def test_a_delete_is_still_open(tmp_path: pathlib.Path) -> None:
    """删除不算直写：`table.delete("documents")` 不被这道拒挡住（判据与 statements 同形）。"""
    st, reg = _ws(tmp_path)
    with st.tx("documents", actor="fixture") as tx:      # 正路之外的行由夹具直接铺
        tx.upsert("documents", {**{k: v for k, v in DOCUMENT_ROW.items() if k != "doc_id"},
                                "doc_id": S.format_id(0)})
    assert len(st.rows("documents")) == 1
    res = _call(reg, "G", "table.delete", table="documents", id="000000")
    assert res.ok is True, (res.error, res.meta)
    assert st.rows("documents") == []


# ================================================================ b) fs.write 写论文正文


def test_b_fs_write_of_the_paper_body_is_refused_with_the_same_gate(
        tmp_path: pathlib.Path) -> None:
    """b：零签 / 零地基 ⇒ `fs.write('out/paper/main.tex')` 受控拒（同一道 `writing_gate`）。"""
    st, reg = _ws(tmp_path)
    res = _call(reg, "G", "fs.write", path="out/paper/main.tex", content=PAPER_BODY)

    assert res.ok is False, ("改前这里 ok=True 并真落盘", res.data, res.meta)
    assert res.meta.get("kind") == GATE_KIND, res.meta
    msg = str(res.error or "")
    # 与 `doc.build_document` 同一句拒信：四项读数 + 可执行的下一步
    assert "签 0 份" in msg, msg
    assert "有效地基 0 条" in msg, msg
    assert "先拿签/先补地基，再来成文" in msg, msg
    assert "不许杜撰" in msg, msg
    assert not (st.root / "out" / "paper" / "main.tex").exists()


def test_b_moving_a_body_into_the_paper_dir_is_refused(tmp_path: pathlib.Path) -> None:
    """b′：先写到 `notes/`、再 `fs.move` 进 `out/paper/` —— 换一个写口也不许绕过成文门。"""
    st, reg = _ws(tmp_path)
    written = _call(reg, "G", "fs.write", path="notes/body.tex", content=PAPER_BODY)
    assert written.ok is True, (written.error, written.meta)

    moved = _call(reg, "G", "fs.move", src="notes/body.tex", dst="out/paper/main.tex")
    assert moved.ok is False, ("改前这里 ok=True：搬一次就把 b 绕过去了", moved.data, moved.meta)
    assert moved.meta.get("kind") == GATE_KIND, moved.meta
    assert not (st.root / "out" / "paper" / "main.tex").exists()
    assert (st.root / "notes" / "body.tex").is_file(), "被拒之后源文件不该消失"


def test_b2_the_paperwork_is_not_behind_the_gate(tmp_path: pathlib.Path) -> None:
    """b 的边界（业主 2026-11-17 的 paperwork-first 口径）：验收表与编译回执不进成文门。

    `budget.PAPERWORK_FIRST_RULE` 逐字是「预算余量低于阈值时，先把收工必需物落盘
    （`out/paper/ACCEPTANCE-CHECKS.json` 与 `out/review/REPORT.md`）……宁可少证一条，
    不许交不出验收表」。把这两份挡在成文门后面，会让"没写成论文"长成"交不出验收表"，
    而那恰好发生在预算见底的那种趟里。它们说的是读数，不是正文。
    """
    from agentflow import budget as BUD

    st, reg = _ws(tmp_path)
    checks = _call(reg, "M", "fs.write", path="out/paper/ACCEPTANCE-CHECKS.json",
                   content='{"checks": []}')
    assert checks.ok is True, ("收工必需物被成文门挡住了 —— 与 paperwork-first 口径相反",
                               checks.error, checks.meta)
    assert (st.root / "out" / "paper" / "ACCEPTANCE-CHECKS.json").is_file()
    assert "ACCEPTANCE-CHECKS.json" in BUD.PAPERWORK_FIRST_RULE, BUD.PAPERWORK_FIRST_RULE
    # 正文那一侧仍然拒（同一个目录里，`main.tex` 不是豁免）
    body = _call(reg, "M", "fs.write", path="out/paper/main.tex", content=PAPER_BODY)
    assert body.ok is False and body.meta.get("kind") == GATE_KIND, (body.data, body.meta)


# ================================================================ c) 正控：不许一刀切


def test_c_one_effective_base_opens_the_paper_body_and_the_real_road(
        tmp_path: pathlib.Path) -> None:
    """c（地基）：≥1 条有效地基 ⇒ `fs.write` 正文与 `doc.build_document` 都放行。"""
    st, reg = _ws(tmp_path)
    _statement(st, "000000", proof="Proof. 由定义直接得到。")

    body = _call(reg, "G", "fs.write", path="out/paper/main.tex", content=PAPER_BODY)
    assert body.ok is True, ("有地基却被封死 ⇒ 一刀切", body.error, body.meta)
    assert (st.root / "out" / "paper" / "main.tex").is_file()

    built = _build(reg)
    assert built.ok is True, (built.error, built.meta)
    assert len(st.rows("documents")) == 1, st.rows("documents")


def test_c_one_sign_opens_the_paper_body_too(tmp_path: pathlib.Path) -> None:
    """c（签）：≥1 份 V 签 ⇒ `fs.write` 正文照旧放行（即使一条有效地基都没有）。"""
    st, reg = _ws(tmp_path)
    _statement(st, "000000")                        # 地基 0 条
    (st.root / "reports" / "f-proof-000000.md").write_text(
        "# 证明\n\n推导……\n", encoding="utf-8")
    _sign(st)                                       # 但已经有一份签

    body = _call(reg, "G", "fs.write", path="out/paper/main.tex", content=PAPER_BODY)
    assert body.ok is True, (body.error, body.meta)
    assert (st.root / "out" / "paper" / "main.tex").is_file()

    rows = [{"kind": "theorem", "label": "Theorem 0.1", "env_no": 1,
             "ledger_id": "stmt:000000", "proof_no": 1, "file": "proofs/t1.md"}]
    paper = st.root / "projects" / "p1" / "out" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text(PAPER_BODY, encoding="utf-8")
    mapped = _call(reg, "G", "doc.write_mapping", project="projects/p1", rows=rows)
    assert mapped.meta.get("kind") != GATE_KIND, mapped.meta


def test_c_material_does_not_reopen_the_generic_table_port(tmp_path: pathlib.Path) -> None:
    """c 的另一半（结构性）：有料也不放宽 `table.create("documents")` —— 那张表只有一个写点。"""
    st, reg = _ws(tmp_path)
    _statement(st, "000000", proof="Proof. 由定义直接得到。")
    res = _call(reg, "G", "table.create", table="documents", row=dict(DOCUMENT_ROW))
    assert res.ok is False, res.data
    assert res.meta.get("kind") == DIRECT_KIND, res.meta
    assert st.rows("documents") == []


# ================================================================ d) 非成文路径


def test_d_non_paper_paths_are_untouched(tmp_path: pathlib.Path) -> None:
    """d：自由笔记与别的表一个字节都不受影响。"""
    st, reg = _ws(tmp_path)

    note = _call(reg, "G", "fs.write", path="notes/x.md", content="# 随手记\n")
    assert note.ok is True, (note.error, note.meta)
    assert (st.root / "notes" / "x.md").is_file()

    exp = _call(reg, "E", "table.create", table="experiments", row={
        "claim": "数值实验", "claim_key": "k", "method": "numeric",
        "result": "inconclusive", "negation_kind": "not_proved"})
    assert exp.ok is True, (exp.error, exp.meta)
    assert len(st.rows("experiments")) == 1
    # 拒信面本身只多了 documents 一格：别的表一个都没被误拒
    for table in ("experiments", "literature", "relations", "research_questions"):
        assert store_mod.direct_write_refusal(table) == "", table


# ================================================================ e) 反真空


def test_e_disabling_the_documents_refusal_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e（①）：把 `direct_write_refusal` 打桩成恒空 ⇒ 同一笔真的落一行（a 的拒就是它给的）。"""
    st, reg = _ws(tmp_path)
    monkeypatch.setattr(store_mod, "direct_write_refusal", lambda table: "")
    monkeypatch.setattr(table_tools._store_mod, "direct_write_refusal", lambda table: "")

    res = _call(reg, "G", "table.create", table="documents", row=dict(DOCUMENT_ROW))
    assert res.ok is True, ("闸关掉了却仍写不进去 ⇒ a 的拒不是这道闸给的", res.error, res.meta)
    assert len(st.rows("documents")) == 1, st.rows("documents")


def test_e_disabling_the_writing_gate_turns_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e（②）：把 `writing_gate` 打桩成恒放行 ⇒ 同一笔真的落盘（b 的拒就是它给的）。"""
    st, reg = _ws(tmp_path)
    monkeypatch.setattr(RB, "writing_gate", lambda *a, **k: {
        "checked": True, "refuse": False, "kind": "", "reason": "",
        "details": {}, "base": {}, "signing": {}})

    res = _call(reg, "G", "fs.write", path="out/paper/main.tex", content=PAPER_BODY)
    assert res.ok is True, ("闸关掉了却仍写不出来 ⇒ b 的拒不是这道闸给的", res.error, res.meta)
    assert (st.root / "out" / "paper" / "main.tex").read_text(encoding="utf-8") == PAPER_BODY


# ================================================================ f/g/h) 保留表：证明稿只有框架能写


#: 2026-11-17 那条口径（表里 2026-11-07 的原话）：「`reports/f-proof-*` 这一类落点
#: 只有框架能写」。这里逐条覆盖"角色表没登记到"的那几格（真机探针里它们 `ok=True`）。
ONLY_FRAMEWORK_CASES: tuple[tuple[str, str], ...] = (
    ("F", "reports/b-proof-000001.md"),      # F 的规则只认 f-proof / *-proof.md
    ("M", "reports/e-proof-000001.md"),      # M 的规则同上
    ("M", "reports/b-proof-000002.md"),
    ("F", "reports/e-proof-000002.md"),
    ("F", "reports/x-proof-000001.md"),      # 谁都不是的族：名字形状本身就不该手写
    ("G", "reports/x-proof-000002.md"),
)


@pytest.mark.parametrize("role,rel", ONLY_FRAMEWORK_CASES)
def test_f_a_proof_manuscript_name_is_written_by_the_framework_only(
        tmp_path: pathlib.Path, role: str, rel: str) -> None:
    """f：`reports/<谁>-proof-<号>.md` 的新建档 ⇒ 保留表拒（只有框架能写）。"""
    st, reg = _ws(tmp_path)
    res = _call(reg, role, "fs.write", path=rel, content="# 手写的证明稿\n")
    assert res.ok is False, (role, rel, res.data, res.meta)
    assert res.meta.get("kind") == FT.RESERVED_ARTIFACT_KIND, (role, rel, res.meta)
    assert not (st.root / rel).exists(), f"{role} 写 {rel} 被拒了却仍落盘"


def test_f_a_write_without_a_role_context_is_refused_too(tmp_path: pathlib.Path) -> None:
    """f（真机探针那一格）：没挂角色上下文（`calling_as` 不在）也不许手写证明稿。

    `PROOF-third-path.txt` 里 `fs.write 'reports/f-proof-000000.md'` 是 `ok=True` ——
    那一格正是"按角色分行"的保留表在"没有角色"时的缺口。
    """
    st, reg = _ws(tmp_path)
    scoped = reg.scoped_to("G")
    res = scoped.call("fs.write", path="reports/f-proof-000000.md", content="# 手写的证明稿\n")
    assert res.ok is False, ("没有角色上下文 ≠ 谁都可以写", res.data, res.meta)
    assert res.meta.get("kind") == FT.RESERVED_ARTIFACT_KIND, res.meta
    assert not (st.root / "reports" / "f-proof-000000.md").exists()


def test_g_positive_controls_for_the_proof_shape_rule(tmp_path: pathlib.Path) -> None:
    """g：保留表不许扩成"谁都不许写"：自由笔记 / 数值族 / 非 reports 目录照旧。"""
    st, reg = _ws(tmp_path)
    # F 的自由笔记（`notes/` 是 A/B 与产出侧的正常面）
    note = _call(reg, "F", "fs.write", path="notes/x.md", content="# 自由笔记\n")
    assert note.ok is True, (note.error, note.meta)
    # E 自己的普通数值族（不是 `-proof-` 形状）
    e_num = _call(reg, "E", "fs.write", path="reports/e-num-000001.md", content="## 数值结果\n")
    assert e_num.ok is True, (e_num.error, e_num.meta)
    # D 的研究手稿（既有交付物）
    research = _call(reg, "D", "fs.write", path="reports/RESEARCH.md", content="# 研究手稿\n")
    assert research.ok is True, (research.error, research.meta)
    for rel in ("notes/x.md", "reports/e-num-000001.md", "reports/RESEARCH.md"):
        assert (st.root / rel).is_file(), rel


def test_the_two_literals_are_the_module_constants() -> None:
    """读数：上面那两个本文件字面量与 `fs_tools` 的常量不许漂（表那一行的身份）。"""
    assert FT.MANUSCRIPT_ONLY_ROLE == MANUSCRIPT_ONLY_ROLE, (
        FT.MANUSCRIPT_ONLY_ROLE, MANUSCRIPT_ONLY_ROLE)
    assert FT.PROOF_SHAPE_RULE_KIND == PROOF_SHAPE_RULE_KIND, (
        FT.PROOF_SHAPE_RULE_KIND, PROOF_SHAPE_RULE_KIND)
    assert any(who == MANUSCRIPT_ONLY_ROLE and rule.startswith(PROOF_SHAPE_RULE_KIND + ":")
               for who, rule in FT.RESERVED_ARTIFACT_TABLE), (
        "保留表里没有那一行 ⇒ f/h 的绿来自别处")


def test_h_dropping_the_proof_shape_row_reopens_the_write(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """h：反真空 —— 把保留表里那一行摘掉 ⇒ f 那批写入必须成功。"""
    rows = [row for row in FT.RESERVED_ARTIFACT_TABLE
            if not (row[0] == MANUSCRIPT_ONLY_ROLE
                    and row[1].startswith(PROOF_SHAPE_RULE_KIND + ":"))]
    assert len(rows) == len(FT.RESERVED_ARTIFACT_TABLE) - 1, (
        "那一行没找齐（摘了 {} 行）⇒ 这条反真空在核一个空集".format(
            len(FT.RESERVED_ARTIFACT_TABLE) - len(rows)))
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", tuple(rows))

    st, reg = _ws(tmp_path)
    for role, rel in ONLY_FRAMEWORK_CASES:
        res = _call(reg, role, "fs.write", path=rel, content="# 改前状态：写得进去\n")
        assert res.ok is True, (role, rel, "那一行被摘掉了却还是拒 ⇒ f 的绿不来自它", res.meta)
        assert (st.root / rel).is_file(), (role, rel)
