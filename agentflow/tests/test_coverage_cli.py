"""`cli.py` 里三个零测试公开函数的判据测试（等级 1 写路径 ×2 + 等级 2 判据 ×1）。

## 为什么这三个函数值得补（它们不是"实现细节"）

| 函数 | 判据 | 为什么命中等级 |
|---|---|---|
| `cmd_submit` | 取号唯一 + 输入不合法 ⇒ 整批不写 | 写 `search_requests`（等级 1） |
| `cmd_repair` | 没有显式目标就一行都不写（并表后 `--related` 受控退役、同样一行不写） | 写 `statements`（等级 1） |
| `cmd_verify` | 默认就能当门用（有 error ⇒ 退出码 1） | 返回 verdict 的退出码（等级 2） |

三条判据各自都对应一次真实踩过的坑（写在各函数的 docstring 里），
所以断言必须打在"它为什么拒绝"上。

## 为什么用 `SimpleNamespace` 而不是跑 argparse

`cmd_*` 的入参是 argparse 的 `Namespace`。跑真实 `main()` 会连带跑整个 CLI
（含 `Store.init` 与配置读盘），失败时无法区分"是子命令的判据错了"还是
"是 argparse 层错了"。这里直接构造 `Namespace`，把被测对象缩到那一个函数。
`argparse` 层本身另有 `test_core_audit_abc_cli.py` 守着（它测的是 `--role` 的 choices）。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentflow import cli, schema as S
from agentflow.store import Store

from conftest import TS, add_concept, add_literature, add_relation, read_data_bytes, sync_counters


# ============================================================ 夹具


def _args(**over: object) -> SimpleNamespace:
    """CLI 子命令的最小参数集。缺的键由各用例补。"""
    base = {"root": None, "json": False, "strict": False, "deep": False, "config": None,
            "related": False, "file": None, "topic": None, "mode": None, "content": None, "by": "cli-test"}
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def ws(tmp_path: Path) -> Store:
    """一个已 init 的空工作区。"""
    st = Store(tmp_path / "ws")
    st.init()
    return st


# ============================================================ cmd_submit（等级 1）


def test_cmd_submit_accepts_valid_batch_and_uses_the_single_id_allocator(ws: Store):
    """正向：合法输入 ⇒ 退出码 0，且号由 `next_prefixed_id` 的 `max+1` 口径发放。

    为什么断言"跳过中间号"而不是"发了 r-0001/r-0002"：
    这正是那个函数 docstring 记的缺陷 —— 旧实现按 `len(rows)+i+1` 发号，
    表里只有 `r-0001`/`r-0003` 时它会发 `r-0002`，与"max+1"口径分家。
    预先塞一个 `r-0005` 就能把两种实现区分开：正确实现发 `r-0006`，
    计数式实现发 `r-0002`。只断言"发了两个号"两条实现都能过。
    """
    from conftest import add_request

    add_request(ws, "r-0005")
    assert cli.cmd_submit(_args(root=ws.root, topic="群论", mode=S.SEARCH_MODES[0], content="")) == 0
    ids = sorted(r["request_id"] for r in ws.rows("search_requests"))
    assert ids == ["r-0005", "r-0006"], ids


def test_cmd_submit_rejects_invalid_input_with_exit_2_and_writes_nothing(ws: Store):
    """负控：非法 `mode` ⇒ 退出码 2 且整批未写入。

    "整批"是无条件量：一个批量提交里第 2 条不合法时，第 1 条也不许落库。
    只断言退出码会漏掉"写了一半"这种最坏的形态。
    """
    bad = S.SEARCH_MODES[0] + "-not-a-mode"
    f = ws.root / "batch.json"
    f.write_text(json.dumps([
        {"topic": "合法的第一条", "mode": S.SEARCH_MODES[0]},
        {"topic": "非法的第二条", "mode": bad},
    ], ensure_ascii=False), encoding="utf-8")
    assert cli.cmd_submit(_args(root=ws.root, file=str(f))) == 2
    assert ws.rows("search_requests") == [], "第 1 条被写进去了 ⇒ 事务不是整批原子的"


def test_cmd_submit_rejects_unreadable_manifest_with_exit_2(ws: Store):
    """负控（三态纪律）：读不到清单（没做）与清单不合法（做了发现问题）分开报。

    两者都必须退出码 2，但原因不同：`FileNotFoundError` 是"没查成"，
    非法 mode 是"查了、发现了问题"。合并不了会让人去查错误的方向。
    """
    assert cli.cmd_submit(_args(root=ws.root, file=str(ws.root / "nope.json"))) == 2
    assert cli.cmd_submit(_args(root=ws.root, file=None, topic=None, mode=None)) == 2
    assert ws.rows("search_requests") == []


def test_cmd_submit_rejects_non_array_manifest(ws: Store):
    """负控：清单不是数组（而是对象且没有 `rows`）⇒ 退出码 2，不落库。"""
    f = ws.root / "obj.json"
    f.write_text(json.dumps({"totally": "wrong"}), encoding="utf-8")
    assert cli.cmd_submit(_args(root=ws.root, file=str(f))) == 2
    assert ws.rows("search_requests") == []


# ============================================================ cmd_repair（等级 1）


def test_cmd_repair_related_exits_2_with_a_pointer_and_writes_nothing(ws: Store, capsys):
    """正向（并表之后的新口径）：显式 `--related` ⇒ 受控退出 2 + 指路，且一行都不写。

    `related_concepts` 是老表专有的一列；并表之后"哪个概念与哪个相关"由 `relations`
    表现算（`dedup.derive_related_concepts` 仍是唯一实现）⇒ 没有可重算的落点。
    所以命令改成受控退出 + 指路，而不是让 `tx("concepts")` 抛一句"未知表"
    （读的人拿到那句话不知道下一步该做什么）。

    保护意图一字不变（改前这条断言的是"退出码 0，且真的按派生规则重算了"）：
    这个开关必须响亮地说出自己退役了、并指到真能回答那个问题的入口；
    它既不许静默变成 no-op（声明了却不起作用），也不许在盘上留下一个字节。
    """
    add_literature(ws, "0000", path="0000/s.txt")
    add_literature(ws, "0001", path="0001/s.txt")
    add_concept(ws, "0000", "group", related_concepts=[])   # 故意空着
    add_concept(ws, "0001", "abelian group", related_concepts=[])
    add_relation(ws, "0000", ["0000", "0001"], "0000", quote="q", quote_verified=True)
    sync_counters(ws)
    before = read_data_bytes(ws)

    assert cli.cmd_repair(_args(root=ws.root, related=True)) == 2
    err = capsys.readouterr().err
    assert "并表退役" in err and "relations" in err, err
    # 指路必须指到真能回答"图与关系偏没偏"的那个入口（派生真相在 `relations`）
    assert "agentflow verify" in err and "related_drift" in err, err
    assert "agentflow rebuild" in err, err
    assert read_data_bytes(ws) == before, "受控退出却动了盘：一个字节都不许改"


def test_cmd_repair_rejects_missing_related_flag_and_writes_nothing(ws: Store, capsys):
    """负控：不带 `--related` ⇒ 退出码 2，且 `data/` 下逐字节未变。

    为什么这条是这份文件里最重要的一条：`--related` 曾经是一个被忽略的开关
    （docstring 逐字：函数体从不读 `args.related`，于是"不带参数跑一次"也会重写表）。
    "调用方以为自己在做只读检查，实际上知识表已经被改了"。
    所以断言必须同时覆盖退出码与磁盘未变两件事。
    """
    add_literature(ws, "0000", path="0000/s.txt")
    add_concept(ws, "0000", "group", related_concepts=[])
    sync_counters(ws)
    before = read_data_bytes(ws)

    assert cli.cmd_repair(_args(root=ws.root, related=False)) == 2
    assert "--related" in capsys.readouterr().err
    assert read_data_bytes(ws) == before, "不带 --related 却改了知识表"


# ============================================================ cmd_verify（等级 2）


def test_cmd_verify_accepts_clean_store_with_exit_0(ws: Store):
    """正向：自洽的最小数据集 ⇒ 退出码 0（`--strict` 下也无警告）。

    这里借用 `conftest.clean_store` 的构造（它被 docstring 声明为
    "verify 应当零错误零警告"）。它是那份契约的第二处消费者 ——
    若 clean_store 的构造漂了，本断言会与 `test_verify.py` 一起红。
    """
    _fill_clean_dataset(ws)
    assert cli.cmd_verify(_args(root=ws.root, strict=True)) == 0


def test_cmd_verify_rejects_dirty_store_with_exit_1(ws: Store):
    """负控：库确实有 error 时，默认（非 `--strict`）也必须返回非零。

    为什么这条是负控而不是"又一条正向"：docstring 逐字记着
    "原先只有 `--strict` 才返回非零 ⇒ `agentflow verify` 在库确实有 error 时
    退出码仍是 0"。若不显式断言默认档的行为，把 `args.strict` 的短路写回去
    照样能通过一份只测 `--strict` 的测试。
    """
    # 造一个必然报错的状态：一条引用了不存在文献的关系。
    add_concept(ws, "0000", "group")
    add_concept(ws, "0001", "abelian group")
    add_relation(ws, "0000", ["0000", "0001"], "9999", quote="q", quote_verified=None)
    sync_counters(ws)
    assert cli.cmd_verify(_args(root=ws.root, strict=False)) == 1
    assert cli.cmd_verify(_args(root=ws.root, strict=True)) == 1


def test_cmd_verify_json_flag_does_not_change_the_verdict(ws: Store):
    """负控（防误伤）：`--json` 只改呈现，不改判定。

    三态纪律的近亲：呈现层与判定层必须是同一份结论的两个视图。
    一个把 `--json` 分支写成"总是 0"的实现能通过只测默认输出的测试。
    """
    add_concept(ws, "0000", "group")
    add_concept(ws, "0001", "abelian group")
    add_relation(ws, "0000", ["0000", "0001"], "9999", quote="q", quote_verified=None)
    sync_counters(ws)
    assert cli.cmd_verify(_args(root=ws.root, json=True)) == 1


# ============================================================ 辅助


def _fill_clean_dataset(st: Store) -> None:
    """把 `st` 填成 `conftest.clean_store` 的那份自洽数据集。

    为什么不直接 import `conftest.clean_store`：它是 fixture（要 `tmp_path`），
    而本文件已经有自己的 `ws` fixture。这里复用它的构造语义，
    但把行写进同一个 `ws` —— 于是"verify 零错误"这条契约在本文件里也成立。

    字段值全部从 `schema` 取（§5.3），不写死 mode/type 字面量。
    """
    from conftest import write_library_file, add_request

    write_library_file(st, "0000/source.txt",
                       "An abelian group is a group in which the commutative law holds.")
    add_request(st, "r-0001", done=True, result_lit_ids=["0000"])
    add_literature(st, "0000", title="Commutativity in abelian groups", path="0000/source.txt",
                   processed=True, source_request_ids=["r-0001"],
                   dedup_key="doi:10.1000/demo.abelian", doi="10.1000/demo.abelian", year=1930,
                   download={"status": "ok", "http_status": 200, "bytes": 62,
                             "sha256": "0" * 64, "error": None})
    add_concept(st, "0000", "group", related_concepts=["0001"])
    add_concept(st, "0001", "abelian group", related_concepts=["0000"])
    add_relation(st, "0000", ["0000", "0001"], "0000",
                 quote="An abelian group is a group in which the commutative law holds.",
                 group_key="0000|0001", quote_verified=True)
    sync_counters(st)
