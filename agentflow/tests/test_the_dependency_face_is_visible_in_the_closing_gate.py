# -*- coding: utf-8 -*-
"""收工门必须看得见依赖面：`present / 自足 / 缺节 / 未读`（缺陷 1b）。

## 现场（`temp/dep_probe/REPORT-dependency-surface.md` 第 2 条 / 第 5 条）

`depsection.deps_missing_reading` 在 `refs<=0` 时一律给 `not_applicable`，把底层
`secretary._deps_missing_reading` 对"有正文零依赖"给的 `missing` 盖掉了；而收工门的
读数表里根本没有 dependency 这一行（源码自证在 `secretary.py` 那一段：「收工门不数
`dependencies`、读侧也没有一格问过这件事 ⇒ 依赖面 0 行是静默的」）。
于是**写 0 条依赖与写 5 条同价**：盘上 41 份证明手稿里 35 份是空表，一路静默。

## 口径（本文件逐条钉住，a–d 对应任务书的四条判据）

* a 一份 3000 字正文 + 空 `## 依赖` 表 ⇒ 那一格说「自足 1」，且**不判红**
  （不进 `status`、不产生 blocker、`machine_pass` 不变）；
* b 同一份稿**缺整节** ⇒ 那一格说「缺节 1」（格式没交，与自足分开算）；
* c 依赖 0 行而正文里有 `stmt:` 引用 ⇒ 必须报「说不一致」（这一形态可达：手写稿 /
  F 在正文里点名而没写 `cites`；盘上今天 0 份，见报告第三节 —— 所以它是判据而不是读数）；
* d 反真空：把「有正文零依赖」那一句读数摘掉 ⇒ a 的可见性断言红；而**它不许变成判红档**
  （自足仍然放行）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import closing as CL
from agentflow import schema as S
from agentflow.store import Store

TS = "2026-11-05T10:00:00+08:00"
SID = "000000"
#: 真机一份证明正文的量级（报告第 2 条：2700–6300 字）。
PROOF_CHARS = 3000
#: 那一节的四列表头（列名与 `depsection.COLUMN_KEYS` 逐字对齐）。
DEP_TABLE_HEAD = ("| 引用 | 命题号 | 用在哪一步 | 路径号 |\n"
                  "|---|---|---|---|\n")


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _body(extra: str = "") -> str:
    """一段 3000 字量级的证明正文（可选夹一条 `stmt:` 引用）。"""
    text = "归纳：基例成立。\n" + ("这一步由前一步直接推出。" * (PROOF_CHARS // 14))
    return (extra + text) if extra else text


def _statement(proof_text: str) -> dict:
    return {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "label": "引理 000000", "statement_text": "引理 000000 的陈述",
        "statement_full": "引理 000000 的陈述全文。", "proof_text": proof_text,
        "quote_reason": "我方自产命题", "evidence_kind": "heuristic",
        "status": "active", "bits": {}, "created_at": TS, "created_by": "test",
    }


def _ws(root: pathlib.Path, *, proof_text: str, manuscript: str | None) -> pathlib.Path:
    """statements 1 行 + `reports/f-proof-000000.md`（`None` = 不放这份稿）。"""
    root = pathlib.Path(root)
    Store(root).init(force=True)
    _dump(root / "data" / str(S.TABLES["statements"]["file"]),
          {"schema_version": 2, "rows": [_statement(proof_text)]})
    if manuscript is not None:
        path = root / "reports" / f"f-proof-{SID}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manuscript, encoding="utf-8")
    return root


def _manuscript(*, dep_section: bool = True, body: str = "", with_table: bool = False) -> str:
    """一份两节手稿：`## 证明` +（可选）`## 依赖` 那一节。

    `with_table=False` ⇒ 那一节在、表是空的（表头 + 分隔行，0 行）—— 这是"自足"的形态。
    """
    text = (f"# 证明手稿 f-proof-{SID}\n\n- 命题号：{SID}\n\n"
            "## 命题\n\n引理 000000 的陈述全文。\n\n"
            f"## 证明\n\n{body or _body()}\n")
    if dep_section:
        text += "\n## 依赖\n\n" + DEP_TABLE_HEAD
        if with_table:
            text += "| 由引理 1 | stmt:000001 | 第 2 步 | 1 |\n"
    return text


def _assert_the_cell_is_not_a_gate(rep) -> None:
    """这一格不判红：不进 `status`、不产生 blocker（"不拦门"的可执行判据）。

    不断言整份门 `machine_pass is True`：同一份现场里别的读数（例如
    `statements_unsigned`：这条命题还没 V 签）本来就带 blocker —— 那是另一件事，
    把它们混进来会让这条断言变成"别人的门也必须是绿的"，与这一格无关。
    """
    assert "dependency_face" not in rep.status, rep.status
    assert not [f for f in rep.findings
                if f.check == "dependency_face" and f.level == "blocker"], rep.to_dict()


# ============================================================ a 有正文、空表 = 自足
def test_a_a_body_with_an_empty_table_is_self_sufficient_and_not_red(tmp_path):
    """a：3000 字正文 + `## 依赖` 空表 ⇒ 「自足 1」，且门不因此判红。"""
    root = _ws(tmp_path / "ws", proof_text=_body(), manuscript=_manuscript())
    store = Store(root)

    got = CL.dependency_face_reading(store, root)
    assert got["checked"] is True, got
    assert got["self_sufficient"] == 1, got
    assert got["present"] == 0 and got["section_missing"] == 0, got
    assert "自足 1" in str(got["note"]), got["note"]

    rep = CL.check_closing(store, project_dir=str(root), checks=())
    cell = rep.readings["dependency_face"]
    assert cell["checked"] is True, cell
    assert cell["self_sufficient"] == 1, cell
    assert "依赖面：present 0 / 自足 1 / 缺节 0 / 未读 0" in str(cell["note"]), cell["note"]
    _assert_the_cell_is_not_a_gate(rep)


# ============================================================ b 缺整节 = 缺节
def test_b_the_same_manuscript_without_the_section_is_missing_not_self_sufficient(tmp_path):
    """b：同一份稿缺整节 ⇒ 「缺节 1」（与自足分开：这是格式没交）。"""
    root = _ws(tmp_path / "ws", proof_text=_body(),
               manuscript=_manuscript(dep_section=False))
    got = CL.dependency_face_reading(Store(root), root)
    assert got["checked"] is True, got
    assert got["section_missing"] == 1, got
    assert got["self_sufficient"] == 0, got
    assert "缺节 1" in str(got["note"]), got["note"]
    row = got["rows"][0]
    assert row["bucket"] == "section_missing", row
    assert "没有 `## 依赖` 那一节" in str(row["why"]), row["why"]


# ============================================================ c 说不一致（可达）
def test_c_zero_rows_but_a_stmt_reference_in_the_body_is_inconsistent(tmp_path):
    """c：依赖 0 行、正文里却有 `stmt:` 引用 ⇒ 报「说不一致」（可达，见 docstring）。

    可达性不是猜的：`depsection.parse_dependency_section` 只读那一节，正文里的
    `stmt:` 由 `stmt_refs` 单独扫 —— 两者没有任何东西比过（V 读稿时也不比）。
    手写稿、或 F 在正文里点名而没写 `cites`，就是这个形态。盘上今天 0 份
    （报告第三节），所以它此前从未被触发过；判据要它被看见。
    """
    root = _ws(tmp_path / "ws",
               proof_text=_body("由 stmt:000001 直接推出。\n"),
               manuscript=_manuscript(body=_body("由 stmt:000001 直接推出。\n")))
    got = CL.dependency_face_reading(Store(root), root)
    assert got["checked"] is True, got
    assert got["inconsistent"] == 1, got
    assert got["self_sufficient"] == 0, got
    assert "说不一致 1" in str(got["note"]), got["note"]
    row = got["rows"][0]
    assert row["bucket"] == "inconsistent", row
    assert "说不一致" in str(row["why"]), row["why"]

    rep = CL.check_closing(Store(root), project_dir=str(root), checks=())
    codes = [f.code for f in rep.findings if f.check == "dependency_face"]
    assert "dependency_face_inconsistent" in codes, codes
    # 仍然不判红：它是读数（warning），不是 blocker。
    _assert_the_cell_is_not_a_gate(rep)


# ============================================================ d 反真空 + 不判红
def test_d_the_self_sufficient_line_is_what_makes_it_visible(tmp_path):
    """d：a 的可见性挂在那句逐字的读数上 —— 摘掉它，a 的断言红；而它不许判红。

    这条同时钉两件事：①那句读数逐字存在（删掉它 ⇒ 本文件 a 与这条一起红）；
    ②它在 blocker 档之外（把它升级成 blocker ⇒ 这里的 `machine_pass is True` 红）。
    """
    root = _ws(tmp_path / "ws", proof_text=_body(), manuscript=_manuscript())
    got = CL.dependency_face_reading(Store(root), root)
    row = got["rows"][0]
    assert ("这一份有正文、0 条依赖边，作者在手稿里交了一张空的 `## 依赖` 表（声明自足）"
            in str(row["why"])), row["why"]
    assert row["edges"] == 0 and row["table_rows"] == 0 and row["refs"] == 0, row

    rep = CL.check_closing(Store(root), project_dir=str(root), checks=())
    # 读数里点名（不是只在内存里）
    assert "自足 1" in rep.summary(), rep.summary()
    _assert_the_cell_is_not_a_gate(rep)


# ============================================================ 读不到 ⇒ 未读（不是 0）
def test_e_a_manuscript_that_is_not_on_disk_is_unread_not_zero(tmp_path):
    """三态：有正文而 `reports/` 里没有这份稿 ⇒ 「未读 1」，不是「自足 0 / 缺节 0」。"""
    root = _ws(tmp_path / "ws", proof_text=_body(), manuscript=None)
    got = CL.dependency_face_reading(Store(root), root)
    assert got["checked"] is True, got
    assert got["unread"] == 1, got
    assert got["self_sufficient"] == 0 and got["section_missing"] == 0, got
    assert "未读 1" in str(got["note"]), got["note"]
    assert not got["rows"][0]["manuscript"], got["rows"][0]


def test_f_a_table_that_cannot_be_read_says_unread_not_zero(tmp_path):
    """三态（整格）：`dependencies` 读不出来 ⇒ `checked=False` + 「未读到」，计数是 None。"""
    root = _ws(tmp_path / "ws", proof_text=_body(), manuscript=_manuscript())
    store = Store(root)
    real = store.rows

    def _boom(table, *a, **kw):
        if table == "dependencies":
            raise RuntimeError("半截表")
        return real(table, *a, **kw)

    store.rows = _boom  # type: ignore[assignment]
    got = CL.dependency_face_reading(store, root)
    assert got["checked"] is False, got
    assert got["present"] is None and got["self_sufficient"] is None, got
    assert "未读到" in str(got["note"]), got["note"]

    rep = CL.check_closing(store, project_dir=str(root), checks=())
    cell = rep.readings["dependency_face"]
    assert cell["checked"] is False, cell
    assert "未读到" in str(cell["note"]), cell["note"]
    # 没查成是一条 warning（要看得见），不是 blocker（不判红）。
    _assert_the_cell_is_not_a_gate(rep)
