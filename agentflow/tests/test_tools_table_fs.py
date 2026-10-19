"""表 CRUD（`tools/table_tools.py`）与文件 CRUD（`tools/fs_tools.py`）的性质测试。

两条主线：
- 表：部分更新只覆盖 patch 里给的字段（含 `_` 开头的诊断字段），删被引用的行要
  点名引用者，主键不许改 —— 这三条都是"删除不可逆 / 引用静默悬空"的防线。
- 文件：一切路径先过沙箱闸门（越界、盘符、UNC、保留设备名一律拒绝且不真的去读），
  sha256 必须与本地复算一致，删目录必须显式 recursive。

## 2026-10-19 晚：样品的表换过一次（`projects/mp2` 的真机读数）

CRUD 的样品原先是 `statements`。现在那两张表（`statements` / `dependencies`）**不由
通用写口直写**：`store.direct_write_refusal` 会以 `direct_write_refused` 拒绝
`table.create` / `table.update`，正路只有 `Secretary.record_statement`（B 交内容、
秘书落盘）。真机形态见 `projects/mp2/sessions/mp2-7.jsonl` 第 94/97 行。

于是本文件的 CRUD 样品换成 `literature`（同样的 `create→get→update→delete` 语义，
同样的"未给字段必须保留"），而"删被引用的命题"那一档改用**正路**（秘书）铺数据 ——
保护的两个意图（部分更新、外键保护）一个字没变。野路被拒本文件也顺带钉一条
（`test_the_generic_write_tools_refuse_the_two_tables_the_secretary_owns`）。
"""

from __future__ import annotations

import hashlib

import pytest

from agentflow import schema as S
from agentflow.secretary import Secretary
from agentflow.tools import fs_tools, table_tools
from agentflow.tools.base import ToolRegistry


@pytest.fixture
def tables(store):
    """绑定了 store 的表工具注册表。"""
    reg = ToolRegistry(name="tables")
    # 绑定角色（`P-14`）：本文件要真的写表，所以取一个非只读角色
    # （`table.*` 的声明角色含 A；C/H 是只读角色，拿不到写工具）。
    reg.bound_role = "A"
    table_tools.register(reg, store=store)
    return reg


def _concept(reg, store, label: str) -> str:
    """铺一条概念行（`statements` 里 `kind="concept"`）—— 走**正路**：B 交、秘书落。

    为什么不再用 `table.create`：`statements` 已不由通用写口直写
    （`store.direct_write_refusal`），而那正是本文件要钉的新契约。
    """
    sec = Secretary("B", root=store.root, store=store)
    out = sec.record_statement({"kind": "concept", "label": label, "origin": "own_result",
                                "statement_full": f"{label}（夹具定义）"}, role="B")
    assert out["checked"] and out["created"], out
    return str(out["stmt_id"])


@pytest.fixture
def fs(store):
    """绑定了工作区根的沙箱文件工具注册表。"""
    reg = ToolRegistry(name="fs")
    reg.bound_role = "A"  # `P-14`：同上（`fs.*` 的声明角色是 A/B/C/D）
    fs_tools.register(reg, root=store.root)
    return reg


# ============================================================ 表：正面链路


def test_table_crud_roundtrip_preserves_untouched_fields(tables):
    """create→get→update→delete：未在 patch 里出现的字段（含 `_` 诊断字段）必须原样保留。

    样品是 `research_questions`（`statements` / `dependencies` 已不由通用写口直写，
    见模块 docstring；而 `literature` 没有 `created_at`/`updated_at`，那条时间戳判据
    就落不到它身上）：判据本身一个字没改 —— 部分更新只覆盖 patch 里给的字段。
    """
    created = tables.call(
        "table.create",
        table="research_questions",
        row={
            "question": "群为什么可交换？", "origin": "fixture",
            "priority": "high", "notes": "原始笔记", "gap_reason": "没查到",
            "_probe": "诊断字段",
        },
    )
    assert created.ok, created.error
    cid = created.data
    assert cid == S.format_id(0)

    got = tables.call("table.get", table="research_questions", id=cid)
    assert got.ok and got.meta["found"] is True
    assert got.data["notes"] == "原始笔记"

    upd = tables.call("table.update", table="research_questions", id=cid,
                      patch={"notes": "改过的笔记"})
    assert upd.ok, upd.error

    after = tables.call("table.get", table="research_questions", id=cid).data
    assert after["notes"] == "改过的笔记"
    assert after["question"] == "群为什么可交换？", "未在 patch 里的 question 被清掉了"
    assert after["gap_reason"] == "没查到", "未在 patch 里的 gap_reason 被清掉了"
    assert after["priority"] == "high", "未在 patch 里的 priority 被清掉了"
    assert after["_probe"] == "诊断字段", "`_` 开头的诊断字段被抹掉了"
    # 时间戳：建行时由 `_touch_timestamps` 自动补（本行刻意没给这两格）⇒ 非空即证。
    assert after["created_at"], "created_at 应当被自动补上"
    assert after["updated_at"], "updated_at 应当被自动补上"

    deleted = tables.call("table.delete", table="research_questions", id=cid)
    assert deleted.ok and deleted.data is True
    assert tables.call("table.get", table="research_questions", id=cid).meta["found"] is False


def test_the_generic_write_tools_refuse_the_two_tables_the_secretary_owns(tables):
    """野路受控拒绝：`statements` / `dependencies` 不许通用写口直写。

    真机形态（`projects/mp2/sessions/mp2-7.jsonl` 第 97 行）：B 拿不到
    `register_statement`，于是 `table.create(table="statements")` 手写
    `bits={}` + `evidence_kind="heuristic"` —— 秘书那四件活与五元位一件没跑。
    拒信必须逐字写出该走哪条路（模型据此能改），且**一行都不落**。
    """
    for table in ("statements", "dependencies"):
        made = tables.call("table.create", table=table,
                           row={"origin": "own_result", "kind": "theorem",
                                "statement_full": "手写的", "quote_reason": "尚未逐字校验"})
        assert made.ok is False, (table, made.ok)
        assert made.meta.get("kind") == "direct_write_refused", made.meta
        assert "Secretary.record_statement" in made.error, made.error
        assert "table.delete" in made.error, made.error   # 逐字写着哪条不受限
        upd = tables.call("table.update", table=table, id=S.format_id(0), patch={"label": "x"})
        assert upd.ok is False and upd.meta.get("kind") == "direct_write_refused", upd.meta
    assert tables.call("table.count", table="statements").data == 0
    assert tables.call("table.count", table="dependencies").data == 0


def test_table_create_autofills_request_id_and_derived_relation_fields(tables):
    """建行时派生字段（search_requests 的 r-NNNN、relations 的 concept_group_key）必须补齐。

    这一条断言被修正过（`"r-0000"` → `"r-0001"`）：原先它编码的是
    `table_tools` 自己的"取最小可用号"语义，而那与
    `interactions.next_prefixed_id`（CLI / C / D / F 都在用）冲突。

    改它是修正一条编码了错误行为的断言，不是放宽断言掩盖失败：
    最小可用号会复用已删行的号，而 `literature.source_request_ids` 与
    `research_questions.waiting_request_ids` 都长期引用 `r-NNNN` —— 号一旦被复用，
    溯源会静默指向另一条请求（静默错误指向，比崩溃危险）。
    `interactions.next_prefixed_id` 的 docstring 自己写着"删除中间行不会导致撞号"。
    现在取号只有一份实现，空表得 `r-0001`（max+1）。
    """
    req = tables.call("table.create", table="search_requests", row={"timestamp": "2026-01-01T00:00:00+00:00", "topic": "群", "mode": "broad"})
    assert req.ok and req.data == f"r-{S.format_id(1)}", req.error

    tables.call("table.create", table="literature", row={"title": "T", "type": "J", "summary": "s", "path": None, "processed": True})
    rel = tables.call(
        "table.create",
        table="relations",
        row={"concept_ids": ["0000", "0001"], "description": "描述", "lit_id": "0000", "quote": "q"},
    )
    assert rel.ok, rel.error
    assert rel.meta["row"]["concept_group_key"] == "0000|0001"
    assert rel.meta["row"]["dedup_key"], "dedup_key 是派生字段，必须被补齐"


def test_table_get_missing_row_is_ok_with_found_false(tables):
    """「没找到」是有效结论而不是错误：ok=True 且 meta.found=False。"""
    res = tables.call("table.get", table="literature", id="9999")
    assert res.ok is True
    assert res.data is None
    assert res.meta["found"] is False


# ============================================================ 表：负面


def test_delete_concept_referenced_by_relation_names_the_referrer(tables, store):
    """删被关系引用的概念必须被拒，且错误里点名"是谁在引用"。

    概念行并表之后住在 `statements` 里（`kind="concept"`）—— 名字与这条判据的
    保护意图都不变（静默删掉被引用的行会让 verify 报 `dangling_*`，而那时
    "原来是谁引用的"已经查不出来了），变的只是行现在落在哪张表。
    概念行**走正路**铺（B 交内容、秘书落盘）：`table.create("statements")` 已受控拒绝。
    """
    _concept(tables, store, "群")
    _concept(tables, store, "阿贝尔群")
    tables.call("table.create", table="literature", row={"title": "T", "type": "J", "summary": "s", "path": None, "processed": True})
    rel = tables.call(
        "table.create",
        table="relations",
        row={"concept_ids": [S.format_id(0), S.format_id(1)], "description": "描述", "lit_id": S.format_id(0), "quote": "q"},
    )
    assert rel.ok, rel.error

    res = tables.call("table.delete", table="statements", id=S.format_id(0))
    assert res.ok is False
    assert res.meta["kind"] == "referenced"
    assert "relations" in res.error and rel.data in res.error, res.error
    refs = res.meta["references"]
    assert any(r["table"] == "relations" and r["row_id"] == rel.data for r in refs)
    # 被拒之后行必须还在（宁可误拒也不能误删）
    assert tables.call("table.get", table="statements", id=S.format_id(0)).meta["found"] is True


def test_delete_literature_referenced_by_request_result_lit_ids_is_refused(tables):
    """删被 search_requests.result_lit_ids 引用的文献同样被拒，并点名那张表。"""
    lit = tables.call("table.create", table="literature", row={"title": "T", "type": "J", "summary": "s", "path": None, "processed": True})
    assert lit.ok and lit.data == S.format_id(0), lit.error
    req = tables.call("table.create", table="search_requests", row={"timestamp": "2026-01-01T00:00:00+00:00", "topic": "t", "mode": "broad"})
    # 取号已统一到 `interactions.next_prefixed_id`（max+1）：空表得 r-0001，不再是 r-0000。
    # 理由同 `test_table_create_autofills_request_id_and_derived_relation_fields`。
    assert req.ok and req.data == f"r-{S.format_id(1)}", req.error
    upd = tables.call("table.update", table="search_requests", id=f"r-{S.format_id(1)}", patch={"done": True, "outcome": "ok", "result_lit_ids": [S.format_id(0)]})
    assert upd.ok, upd.error

    res = tables.call("table.delete", table="literature", id=S.format_id(0))
    assert res.ok is False
    assert res.meta["kind"] == "referenced"
    assert "search_requests" in res.error, res.error
    assert f"r-{S.format_id(1)}" in res.error, res.error
    assert tables.call("table.get", table="literature", id=S.format_id(0)).meta["found"] is True


def test_table_update_refuses_primary_key_change(tables):
    """主键是外键的锚点：update 不许改主键（否则一次调用就造出一片悬空引用）。

    样品是 `literature`（`statements` 已不由通用写口直写，见模块 docstring）。
    """
    tables.call("table.create", table="literature",
                row={"title": "T", "type": "J", "summary": "s", "path": None})
    res = tables.call("table.update", table="literature", id=S.format_id(0),
                      patch={"lit_id": S.format_id(9)})
    assert res.ok is False
    assert res.meta["kind"] == "primary_key_change"
    assert "不允许修改主键" in res.error
    assert tables.call("table.get", table="literature", id=S.format_id(0)).meta["found"] is True


def test_table_update_rejects_unknown_field_and_empty_patch(tables):
    """拼错的字段名必须报错而不是静默忽略；空 patch 也要拒（它只会改 updated_at）。"""
    tables.call("table.create", table="literature",
                row={"title": "T", "type": "J", "summary": "s", "path": None})
    bad = tables.call("table.update", table="literature", id=S.format_id(0),
                      patch={"nmae": "拼错"})
    assert bad.ok is False and bad.meta["kind"] == "validation"
    empty = tables.call("table.update", table="literature", id=S.format_id(0), patch={})
    assert empty.ok is False and empty.meta["kind"] == "param_error"


def test_table_delete_of_unreferenced_relation_is_allowed(tables, store):
    """relations 不在硬拒绝名单里：删它放行（§1.1：危险等级可接受）。

    概念行走正路铺（`_concept`）：`table.create("statements")` 已受控拒绝。
    """
    _concept(tables, store, "群")
    _concept(tables, store, "阿贝尔群")
    tables.call("table.create", table="literature", row={"title": "T", "type": "J", "summary": "s", "path": None, "processed": True})
    tables.call("table.create", table="relations", row={"concept_ids": [S.format_id(0), S.format_id(1)], "description": "d", "lit_id": S.format_id(0)})
    res = tables.call("table.delete", table="relations", id=S.format_id(0))
    assert res.ok and res.data is True
    assert tables.call("table.delete", table="relations", id=S.format_id(0)).data is False


# ============================================================ 文件：正面链路


def test_fs_write_read_stat_search_move_delete_chain(fs):
    """write→read→stat(sha256 复算)→search→move→delete 全链路，内容与哈希都要对得上。"""
    body = "line one: hello\nline two: world\nline three: hello again\n"
    w = fs.call("fs.write", path="notes/a.txt", content=body)
    assert w.ok and w.data["created"] is True
    assert w.data["bytes"] == len(body.encode("utf-8"))

    r = fs.call("fs.read", path="notes/a.txt")
    assert r.ok and r.data == body
    assert r.meta["truncated"] is False and r.meta["encoding"].startswith("utf-8")

    st = fs.call("fs.stat", path="notes/a.txt")
    expect = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert st.ok and st.data["sha256"] == expect, "sha256 与本地复算不一致"
    assert st.data["is_file"] is True and st.data["size"] == len(body.encode("utf-8"))
    assert st.data["exists"] is True

    s = fs.call("fs.search", pattern="hello", path="notes")
    assert s.ok and s.data["total"] == 2
    assert s.data["matches"][0]["path"] == "notes/a.txt"
    assert s.data["lines"][0].startswith("notes/a.txt:1: ")

    mv = fs.call("fs.move", src="notes/a.txt", dst="notes/b.txt")
    assert mv.ok, mv.error
    assert fs.call("fs.stat", path="notes/a.txt").data["exists"] is False
    assert fs.call("fs.read", path="notes/b.txt").data == body

    d = fs.call("fs.delete", path="notes/b.txt")
    assert d.ok and d.data is True
    assert fs.call("fs.stat", path="notes/b.txt").data["exists"] is False


def test_fs_write_defaults_to_no_overwrite(fs):
    """默认不覆盖已有文件（覆盖不可逆），必须显式 overwrite=True。"""
    fs.call("fs.write", path="dup.txt", content="1")
    again = fs.call("fs.write", path="dup.txt", content="2")
    assert again.ok is False and again.meta["kind"] == "exists"
    assert fs.call("fs.read", path="dup.txt").data == "1"
    over = fs.call("fs.write", path="dup.txt", content="2", overwrite=True)
    assert over.ok and over.data["created"] is False
    assert fs.call("fs.read", path="dup.txt").data == "2"


# ============================================================ 文件：负面（沙箱）


@pytest.mark.parametrize(
    "bad_path",
    [
        "../../etc/passwd",
        "..\\..\\windows\\win.ini",
        "../secret.txt",
        "C:\\Windows\\win.ini",
        "D:/data/x.txt",
        "/etc/shadow",
        "\\\\server\\share\\x.txt",
        "\\\\?\\C:\\Windows\\win.ini",
        "NUL",
        "aux.txt",
        "a:b",
        "CON ",
    ],
)
def test_fs_read_rejects_escaping_and_device_paths(fs, bad_path):
    """越界/盘符/UNC/设备名一律 ok=False，且绝不能真的读到工作区外的内容。"""
    res = fs.call("fs.read", path=bad_path)
    assert res.ok is False, f"{bad_path} 竟然被放行了"
    assert res.data is None
    assert res.meta.get("kind") == "path_denied"
    assert res.error


def test_fs_read_escaping_path_really_does_not_touch_outside_file(fs, store, tmp_path):
    """把机密文件放在工作区外，越界读取既失败也不得把内容带回来。"""
    secret = tmp_path / "secret.txt"
    secret.write_text("OUTSIDE-SECRET-CONTENT", encoding="utf-8")
    assert secret.exists()
    res = fs.call("fs.read", path="../secret.txt")
    assert res.ok is False
    assert "OUTSIDE-SECRET-CONTENT" not in str(res.to_dict())
    assert store.root != tmp_path  # 前提：沙箱根确实在工作区之外的那一层


def test_fs_write_outside_workspace_is_refused_and_writes_nothing(fs, tmp_path):
    """越界写入必须被拒，且磁盘上不得出现任何新文件。"""
    res = fs.call("fs.write", path="..\\escape.txt", content="x")
    assert res.ok is False and res.meta.get("kind") == "path_denied"
    assert not (tmp_path / "escape.txt").exists()


def test_fs_delete_refuses_workspace_root(fs):
    """删工作区根等于删掉整个项目的数据，必须无条件拒绝。"""
    res = fs.call("fs.delete", path=".", recursive=True)
    assert res.ok is False
    assert res.meta.get("kind") == "refuse_root"
    assert res.data is None


def test_fs_delete_nonempty_directory_requires_recursive(fs):
    """删非空目录必须先显式 recursive=True：默认只删文件，避免一次笔误删掉整棵树。"""
    fs.call("fs.write", path="reports/a.md", content="a")
    fs.call("fs.write", path="reports/b.md", content="b")

    refused = fs.call("fs.delete", path="reports")
    assert refused.ok is False
    assert refused.meta.get("kind") == "is_dir"
    assert "recursive" in refused.error
    assert fs.call("fs.stat", path="reports/a.md").data["exists"] is True

    ok = fs.call("fs.delete", path="reports", recursive=True)
    assert ok.ok and ok.data is True
    assert fs.call("fs.stat", path="reports").data["exists"] is False


def test_fs_read_refuses_binary_and_directory(fs, store):
    """二进制与目录都不能当文本读（乱码会被下游当成内容）。"""
    fs.call("fs.write", path="notes/x.txt", content="text")
    # 直接把 NUL 字节塞进工作区文件（不走工具的 content 参数），再验证读时的二进制嗅探
    (store.root / "blob.bin").write_bytes(b"\x00\x01\x02\xff\xfe" * 50)
    res = fs.call("fs.read", path="blob.bin")
    assert res.ok is False and res.meta["kind"] == "binary"
    assert res.data is None
    assert fs.call("fs.read", path="notes").ok is False


def test_fs_read_pages_by_lines_and_says_where_to_continue(fs):
    """分段读：给 `start_line`/`max_lines` 就只拿那一段，并给出下一步的起点。

    这是真机实测（2026-09-30）逼出来的：E 拿 17849 字节的台账，连续 14 步重读同一个开头，
    因为观测层每次都把它截到 1200 字，而没有任何办法读后面的部分。
    """
    body = "".join(f"L{i}\n" for i in range(1, 31))
    fs.call("fs.write", path="ledger.md", content=body)
    got = fs.call("fs.read", path="ledger.md", start_line=11, max_lines=5)
    assert got.ok and got.data == "L11\nL12\nL13\nL14\nL15\n", repr(got.data)
    assert got.meta["start_line"] == 11 and got.meta["lines_read"] == 5
    assert got.meta["total_lines"] == 30 and got.meta["windowed"] is True
    assert got.meta["next_line"] == 16, got.meta
    assert "start_line=16" in got.meta["note"], got.meta["note"]


def test_fs_read_paging_ends_with_next_line_none_at_eof(fs):
    """读到尾必须给 `next_line=None`（三态：没读完 / 读完了 / 没查 —— 不许混）。"""
    fs.call("fs.write", path="ledger.md", content="".join(f"L{i}\n" for i in range(1, 31)))
    tail = fs.call("fs.read", path="ledger.md", start_line=29, max_lines=5)
    assert tail.data == "L29\nL30\n", repr(tail.data)
    assert tail.meta["next_line"] is None, tail.meta
    # 起点越过文件尾：空窗口要如实说是空的，不能说成"文件是空的"。
    over = fs.call("fs.read", path="ledger.md", start_line=99)
    assert over.ok and over.data == ""
    assert over.meta["next_line"] is None and over.meta["lines_read"] == 0
    assert "是空的" in over.meta["note"], over.meta["note"]


def test_fs_read_without_paging_args_is_unchanged_and_marks_byte_truncation(fs):
    """不给分段参数时行为与从前一致（整段），字节超限仍如实标注。"""
    fs.call("fs.write", path="ledger.md", content="".join(f"L{i}\n" for i in range(1, 31)))
    whole = fs.call("fs.read", path="ledger.md")
    assert whole.meta["windowed"] is False and whole.meta["truncated"] is False
    assert whole.data.count("\n") == 30 and whole.meta["next_line"] is None
    cut = fs.call("fs.read", path="ledger.md", max_bytes=6)
    assert cut.data == "L1\nL2\n" and cut.meta["truncated"] is True
    assert cut.meta["total_bytes"] > cut.meta["bytes_read"]
    # 字节截断时"共 N 行"只能算已读窗口内的，措辞必须说出来。
    assert "已读窗口内" in cut.meta["note"], cut.meta["note"]
