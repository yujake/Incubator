# -*- coding: utf-8 -*-
"""`literature.path` 只有一个坐标系：相对 `library/`（2026-11-05，M4 补写入闸）。

## 修的是什么（`1703d44f` 已查清，逐字）
`schema.py:434-438` 的注释逐字写着「path 必须是 `library/` 下的相对路径」，而代码只查
`startswith("/")` / `":" in p` / `".." in p.split("/")` —— 注释承诺了一句它没做的事。
于是 B 用 `table.update` 把 `library/000001/…txt`（比库根多一层）原样写了进去；抽取器按
`library` 基准拼成 `library/library/000001/…` ⇒ `file_missing`。真机证据：
`literature[000001].path`、`last_mine_error=file_missing:…\\library\\library\\000001\\…`。
同族先例：`search_tools._lit_file` 的 docstring 记着 paper-rewrite-78 的同一事故（4 行被
改写成 `downloads/lit-*.pdf`）。

## 两道闸、各管一半（判据本体不重复）
1. 形状（`schema.literature_path_problem`，唯一实现）：`library/` 前缀 = 把库根又写了
   一遍 ⇒ 明确拒，且拒信说清这一格该怎么写。它只判形状、不判盘 —— `validate()` 手上没有
   工作区根，而且它也在 `Store.rebuild()` 重放历史时被调用（读历史不是改历史）。
2. 落地（`table_tools._literature_path_refusal`，需要 `Store`）：写侧只拒"路径存在但
   不是普通文件"这一档（目录/其它）。"文件不在"不拒 —— 那是可修的状态，由审计期
   `verify.file_missing` 与 B 的 `last_mine_error` 点名（`relations.dangling_concept` 同一条
   口径：存在性不归写侧管），写侧拒它会误伤"先写行、后补字节"的正路。
3. 归一化（`table_tools._normalize_literature_path`，只有一条规则）：剥掉多余的
   `library/` 前缀，改动记在 `meta.normalized` 上。其余形状（`downloads/x.pdf` 是 workspace
   坐标系、`../x` / 盘符是非法形状）一个字节不碰：猜多了会把另一个合法坐标系也改掉。

## 这一条不放宽什么
`library/library/…` 只剥一层 ⇒ 剩下的 `library/…` 仍被形状闸拒（不递归猜）；
`000000/x.txt` 且文件在 ⇒ 一个字节不动（`meta.normalized == []`）。

## 反真空（没有它，绿只是"今天恰好"）
- 摘掉形状闸（`schema.literature_path_problem` 恒返回 None）⇒ (a) 的"必须拒"变红；
- 摘掉归一步（`table_tools._normalize_literature_path` 恒返回 False）⇒ (b) 变红
  —— 而且红在形状闸的拒信上，说明两层都真的在干活。
"""
from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow.tools import table_tools
from agentflow.tools.base import ToolRegistry
from agentflow.verify import verify_all

from conftest import write_library_file

#: 夹具文献号（六位契约）。
LIT = "000000"
#: 库里的那一份正文（相对 `library/` 的规范形态）。
REL = "000000/paper.txt"
#: 真机事故那一形态：比库根多一层。
BAD = "library/000000/paper.txt"


@pytest.fixture
def tables(store):
    """绑定了 store 的表工具注册表（非只读角色 ⇒ 拿得到写口）。"""
    reg = ToolRegistry(name="tables")
    reg.bound_role = "A"
    table_tools.register(reg, store=store)
    return reg


def _row(path):
    return {"title": "T", "type": "J", "summary": "s", "path": path}


def _lit(path):
    return S.Literature(lit_id=LIT, title="T", type="J", summary="", path=path)


def _disk(store) -> list[dict]:
    """盘上那一份 `literature`（读快照，不是工具的返回值）。"""
    return [dict(r) for r in store.rows("literature")]


def _schema_error(path: str | None) -> str | None:
    """把 (a) 的断言抽成可复用的一格：形状闸对这条 path 的拒信（合法 ⇒ None）。"""
    try:
        _lit(path).validate()
    except ValueError as e:
        return str(e)
    return None


# ============================================================ a 形状闸：受控拒
def test_a_a_library_prefixed_path_is_refused_and_the_message_says_how_to_write_it():
    """(a) 带 `library/` 前缀 ⇒ 受控拒；拒信点名"不要带 library/ 前缀"并给出正确写法。

    改前红：`_lit(BAD).validate()` 一声不响地通过 —— 那就是 B 把多一层写进盘的入口。
    三处断言缺一不可：拒了 / 点名了那条规则 / 说清了该怎么写（只拒不说，模型只能再猜）。
    """
    err = _schema_error(BAD)
    assert err is not None, "改前形态：libary/ 前缀被静默放行（这就是缺陷）"
    assert "不要带 library/ 前缀" in err, err
    # 报错文本必须给出可直接照抄的形态（不是"请改成相对路径"这种要再猜一句的话）
    assert "000000/paper.txt" in err, err


def test_a_the_commit_gate_refuses_it_too_and_nothing_lands(store):
    """(a) 闸在落盘那一刻也成立：绕过工具直接拼一行 ⇒ 提交处 ValueError，半个字节不落。

    为什么这一条必须独立存在：`table_tools` 的归一步会把前缀剥掉（那是给模型的手用的），
    所以"形状闸真的在闸"这件事只有这条"不走工具"的路能证明。
    """
    with pytest.raises(ValueError, match="不要带 library/ 前缀"):
        with store.tx("literature", actor="test", note="M4 形状闸负控") as tx:
            tx.upsert("literature", _lit(BAD).to_dict(), note="M4 形状闸负控")
    assert _disk(store) == [], "被拒的行不许有半个字节落盘"


# ============================================================ b 归一化：剥一层
def test_b_create_strips_the_redundant_prefix_and_names_the_edit(tables, store):
    """(b) `library/000000/paper.txt` 经 `table.create` ⇒ 落盘 `000000/paper.txt`，读数点名。"""
    write_library_file(store, REL, "全文正文")
    res = tables.call("table.create", table="literature", row=_row(BAD))
    assert res.ok, res.error
    # ① 读数点名是哪一格被改过（不是静默改我输入）
    assert res.meta.get("normalized") == ["path"], res.meta
    # ② meta.row 是实际落盘的那一份
    assert res.meta["row"]["path"] == REL, res.meta["row"]["path"]
    # ③ 盘上那一份也是
    assert _disk(store)[0]["path"] == REL


def test_b_update_strips_it_too(tables, store):
    """(b) 同一个判据管两个写口：`table.update` 写带前缀的 path 也剥一层、也点名。"""
    write_library_file(store, REL, "全文正文")
    made = tables.call("table.create", table="literature", row=_row(None))
    assert made.ok, made.error
    upd = tables.call("table.update", table="literature", id=made.data,
                      patch={"path": BAD})
    assert upd.ok, upd.error
    assert upd.meta.get("normalized") == ["path"], upd.meta
    assert _disk(store)[0]["path"] == REL


# ============================================================ c 文件在不在
def test_c_a_path_to_a_missing_file_is_accepted_and_the_audit_names_it(tables, store):
    """(c) 口径：文件不在不拒（也不是"置 None"—— 那会把"该去哪找"这条证据抹掉）。

    既有语义是"存在性归审计期"（同 `relations.dangling_concept`）。这一条同时钉两件事：
    写侧照收（不是不查，是查完放行）、审计期照旧点名 —— "有人管"这句话是有落点的。
    """
    res = tables.call("table.create", table="literature", row=_row("000000/not-there.pdf"))
    assert res.ok, res.error
    assert _disk(store)[0]["path"] == "000000/not-there.pdf", "不许把它悄悄置成 None"
    codes = {(i.table, i.row_id, i.code) for i in verify_all(store).issues}
    assert ("literature", LIT, "file_missing") in codes, sorted(codes)


def test_c_a_path_that_points_at_a_directory_is_refused(tables, store):
    """(c) 另一半：路径存在但不是普通文件 ⇒ 写侧就拒（它不是"状态"，是下游谁都读不懂的形状）。"""
    (store.library / LIT).mkdir(parents=True, exist_ok=True)
    res = tables.call("table.create", table="literature", row=_row(LIT))
    assert res.ok is False, res
    assert "不是普通文件" in str(res.error), res.error
    assert _disk(store) == [], "被拒的行不许有半个字节落盘"


# ============================================================ d 正常形状不误伤
def test_d_the_canonical_shape_passes_untouched(tables, store):
    """(d) `000000/paper.txt` 且文件在 ⇒ 照旧通过，且 `meta.normalized` 是空列表（不是 None）。"""
    write_library_file(store, REL, "全文正文")
    res = tables.call("table.create", table="literature", row=_row(REL))
    assert res.ok, res.error
    assert res.meta.get("normalized") == [], res.meta
    assert _disk(store)[0]["path"] == REL


# ============================================================ 边界：只剥一层、不猜别的形状
def test_the_normalizer_strips_exactly_one_layer_and_leaves_other_coordinates_alone(tables, store):
    """归一化的边界：`library/library/x` 只剩一层、仍被形状闸拒（不递归猜）；
    `downloads/x.pdf`（workspace 坐标系）一个字节不碰 —— 猜多了就是另一条口径变更。"""
    write_library_file(store, REL, "全文正文")
    # 剥一层之后是 `library/000000/paper.txt`：不递归剥 ⇒ 形状闸拒
    res = tables.call("table.create", table="literature",
                      row=_row("library/" + BAD))
    assert res.ok is False, res
    assert "不要带 library/ 前缀" in str(res.error), res.error
    # 另一个合法坐标系：原样写、不进读数
    made = tables.call("table.create", table="literature", row=_row("downloads/x.pdf"))
    assert made.ok, made.error
    assert made.meta.get("normalized") == [], made.meta
    assert _disk(store)[0]["path"] == "downloads/x.pdf"


# ============================================================ e 反真空
def test_negative_control_removing_the_shape_gate_makes_a_green(monkeypatch: pytest.MonkeyPatch):
    """反真空 ①：把形状闸摘掉 ⇒ (a) 的 `err is not None` 当场变红（这里演一遍那个失败）。

    打的是 `schema.literature_path_problem`（形状判据的唯一实现）。没有这一条，
    (a) 证明的只是"今天恰好被拒"，不证明"拒是这道闸干的"。
    """
    monkeypatch.setattr(S, "literature_path_problem", lambda _p: None)
    assert _schema_error(BAD) is None, "摘掉闸之后仍被拒 ⇒ (a) 不是靠这道闸成立的"


def test_negative_control_removing_the_normalizer_makes_b_red(tables, store,
                                                              monkeypatch: pytest.MonkeyPatch):
    """反真空 ②：把归一步摘掉 ⇒ (b) 变红，而且红在形状闸的拒信上（两层都在干活）。"""
    monkeypatch.setattr(table_tools, "_normalize_literature_path", lambda _table, _data: False)
    write_library_file(store, REL, "全文正文")
    res = tables.call("table.create", table="literature", row=_row(BAD))
    assert res.ok is False, res
    assert "不要带 library/ 前缀" in str(res.error), res.error
    assert _disk(store) == []
