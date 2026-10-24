# -*- coding: utf-8 -*-
"""D-44：`documents` 行是中间产物，它自己的 sha 必须按盘上那份文件的字节现算。

现场（r34d 逐字读数）：那一行的 `content_sha256=872b9305…`，而它
`markdown_path=documents/000000.md` 的原样 sha 是 `2ca5ad0d…` —— 各种规范化都不相等
（cube2 同样）。也就是说：这一行记的那个 sha 不是它指向的那份文件的 sha。

业主裁定（唯一权威，逐字）：「只对论文负责是正确的，documents等都是中间产物」。

两条判据（都在改前红）：

- ⑤ 写一条 `documents` 行 ⇒ 记下的那个 sha == 盘上 `markdown_path` 的 sha256；
- ⑥ 文件后来被改过 ⇒ 读侧能报"中间产物内容已变"，且只作读数、不进任何门
  （同一个工作区在改文件前后跑 `verify_all`，issue 集合逐字相同）。

## 为什么那个 sha 没写进 `content_sha256`（这也是本文件第二条断言的理由）

`content_sha256` 不是"这个文件的 sha"，它是"这一版内容"的规范哈希
（`signatures.content_sha256_of`：`kind/title/sections/claims/open_problems` 五个字段的
规范 JSON）。两件事在结构上不可能相等，而且把文件 sha 塞进那一格会让两套判据同时失效：

1. `verify.py` 的 `content_hash_mismatch` 会拿行里的值与 `SIG.content_sha256_of(doc)`
   重算比对 —— 文件 sha 永远对不上 ⇒ 每一行稿件都会报 error（那是 FC-27 禁改区）；
2. 签名台账与 `doc:@hash` 内部引用钉的也是它 —— 改了口径等于说"盘上所有历史哈希都不再成立"。

而且"文件字节"本身不是内容的函数（实测 r34d 那一份）：

- `render_markdown` 会把 `status` / 审校轮次画进文件，而 H 审完只改 status ⇒
  同一份内容、状态一翻，盘上那份文件的 sha 就换了；
- `Path.write_text` 在 Windows 上把 `\\n` 翻成 `\\r\\n` ⇒ 同一份内容在两个平台上
  是两个字节串。

所以本次落的是"中间产物自己的 sha"，记在写这一行的那笔事务里（事件流的一条
`info`：`doc_tools.ARTIFACT_EVENT`），由读侧 `document_artifact_readings` 核对。
它只用于人工追溯，不作任何收工门判据 —— ⑥ 的第二半就是这条口径的判据。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentflow import artifacts as A
from agentflow import signatures as SIG
from agentflow.store import Store
from agentflow.tools import doc_tools as DT
from agentflow.verify import verify_all

from conftest import add_literature

CLAIM = {
    "claim_id": "claim-1",
    "section": "主要结果",
    "text": "谱落在区间内。",
    "evidence_kind": "cross_check",
    "citations": ["lit:0000"],
    "is_negative": False,
    "negation_kind": None,
    "disclaimer": "数值交叉验证，不构成证明",
}


def _build(store: Store) -> dict:
    """经真实的写侧落一份稿件（这一条判据打的正是那个写入点）。"""
    add_literature(store, "0000", title="探针文献", processed=True)
    return DT.build_document(
        store,
        kind="paper",
        title="探针稿",
        claims=[dict(CLAIM)],
        sections=[{"heading": "主要结果", "body": "谱落在区间内。"}],
        open_problems=[],
        actor="agent-G",
    )


def _file_of(store: Store, row: dict) -> Path:
    return store.root / str(row["markdown_path"])


# ============================================================ ⑤ 写这条行时现算


def test_writing_a_documents_row_records_the_sha_of_the_file_on_disk(store: Store):
    """⑤ 写一条 `documents` 行 ⇒ 记下的 sha == 盘上 `markdown_path` 的 sha256。

    改前为什么红：改前没有任何地方记过"中间产物自己的 sha" ——
    读侧只能拿 `content_sha256` 去比，而它与文件字节在结构上不可能相等
    （见本文件开头那段：r34d 的 872b9305… 对 2ca5ad0d…）。本用例要求的是

        记下的值 == `sha256(盘上那份文件的字节)`

    并且这个值必须从文件本身算出来（用例直接读盘重算，不读实现里的中间变量）。
    """
    row = _build(store)
    path = _file_of(store, row)
    assert path.is_file(), "夹具前提：写侧真的把 markdown 落盘了"
    on_disk = hashlib.sha256(path.read_bytes()).hexdigest()

    readings = DT.document_artifact_readings(store)
    assert readings["checked"] is True, readings
    mine = [r for r in readings["rows"] if r["doc_id"] == row["doc_id"]]
    assert len(mine) == 1, readings
    got = mine[0]
    assert got["status"] == "ok", got
    assert got["markdown_path"] == str(row["markdown_path"]).replace("\\", "/")
    assert got["sha256_recorded"] == on_disk, (
        f"写这一行时记的 sha 是 {got['sha256_recorded'][:16]}…，"
        f"盘上那份是 {on_disk[:16]}… —— 中间产物自己的 sha 对不上"
    )
    assert got["sha256_now"] == on_disk
    assert got["bytes_now"] == path.stat().st_size == len(path.read_bytes())
    # 唯一口径：与 `artifacts.sha256_of`（字节级，不做任何归一化）逐字相同
    assert got["sha256_recorded"] == A.sha256_of(path)

    # ---- 说明格：`content_sha256` 仍然是"这一版内容"的规范哈希（不是文件 sha）。
    # 这一条是故意的，理由见本文件开头：把文件 sha 塞进那一格会让
    # `verify.content_hash_mismatch` 与整条签名链同时失效。这里把它写成断言，
    # 是为了让"两个哈希各自是什么"在读代码时就能被看见，而不是留给下一个人再发现一次。
    assert row["content_sha256"] == SIG.content_sha256_of(row)
    assert row["content_sha256"] != on_disk, (
        "内容哈希与文件字节哈希本来就该是两个值：前者钉'这一版内容'，后者钉'这一份产物'"
    )
    # 状态一翻（H 审完只改 status）⇒ 文件字节会变、内容哈希不变 —— 这正是两者不能合并的实测理由
    row2 = dict(row)
    row2["status"] = "accepted"
    assert SIG.content_sha256_of(row2) == SIG.content_sha256_of(row)


# ============================================================ ⑥ 读侧报"已变"，且不进任何门


def test_a_changed_file_is_reported_as_changed_and_it_gates_nothing(store: Store):
    """⑥ 文件后来被改过 ⇒ 读侧能报"中间产物内容已变"（只作读数，不进任何门）。

    改前为什么红：没有基线就无从谈"变过" —— 改前读侧能拿到的只有 `content_sha256`，
    而它与文件字节本来就不相等（r34d 现场）⇒ 它既报不出"变了"，也报不出"没变"。

    第二半（不进任何门）用"改文件前后 `verify_all` 的 issue 集合逐字相同"来判：
    中间产物的 sha 若进了门，改一次文件的字节就会在门上报出一条新东西。
    """
    row = _build(store)
    path = _file_of(store, row)
    before_issues = sorted((i.code, i.table, i.row_id) for i in verify_all(store).issues)
    before = DT.document_artifact_readings(store)
    assert [r["status"] for r in before["rows"]] == ["ok"], before

    # ---- 有人（或某条流程）改了这份中间产物：内容真的换了一段
    original = path.read_bytes()
    path.write_bytes(original + "\n<!-- 事后被人追加了一行 -->\n".encode("utf-8"))

    after = DT.document_artifact_readings(store)
    got = after["rows"][0]
    assert got["status"] == "changed", got
    assert "中间产物内容已变" in got["reason"]
    assert got["sha256_recorded"] == hashlib.sha256(original).hexdigest()
    assert got["sha256_now"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert got["sha256_now"] != got["sha256_recorded"]

    # ---- 只作读数：门上的读数一个字节都不变
    after_issues = sorted((i.code, i.table, i.row_id) for i in verify_all(store).issues)
    assert after_issues == before_issues, (
        "改了中间产物之后 `verify` 报出了新东西 ⇒ 它已经进了门（业主裁定：只作读数）"
    )
    # 读数的形状本身也说明它不是判据：没有 pass/fail、没有 verdict 之类的词
    assert set(after) == {"checked", "reason", "rows"}
    assert "verdict" not in got and "pass" not in got and "fail" not in got

    # ---- 第三态：没记过 sha 的行报 `unrecorded`（判不了），不与"没变过"折平
    path.write_bytes(original)
    with store.tx("documents", actor="test", note="夹具：造一条改写之前写的行") as tx:
        legacy = dict(row)
        legacy["doc_id"] = "9999"
        tx.upsert("documents", legacy)
    rows = {r["doc_id"]: r for r in DT.document_artifact_readings(store)["rows"]}
    assert rows["9999"]["status"] == "unrecorded"
    assert "判不了" in rows["9999"]["reason"]
