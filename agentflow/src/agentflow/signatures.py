"""稿件内容的规范哈希（依据 `draft/30` §T4-A；`draft/29` §8.5 第 2 条）。

## 为什么需要它

"审批通过"必须是对某一个版本的审批。今天 `Document` 没有内容哈希 ⇒
"审批过的版本"与"被引用的版本"可以静默变成两版（本仓最忌的静默失效形态）。
这一层提供那个唯一的哈希算法，供两侧共用：

- 写侧（G）：落稿 / 改稿时算一次，写进 `documents.content_sha256`；
- 读侧（`verify`）：重算一遍与行里的值比对（`content_hash_mismatch`），
  并核对 `doc:<doc>#<claim>@<hash>` 这种引用钉的是不是当前这一版。

两份实现必然漂移 —— 所以算法只在这里定义一次。

## 口径（逐字，改它等于改"什么算同一版"）

只覆盖内容五个字段：`kind / title / sections / claims / open_problems`；
不含 `status` / `review_rounds` / `markdown_path` / `created_at` / `updated_at` /
`revision` / `content_sha256` 自己 —— 它们是生命周期与呈现，不是内容。
把它们算进去会让"审一次"因为一次状态迁移而失效，那是把两种变化混成一种。

序列化：`json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`
（UTF-8 编码后取 sha256 小写十六进制）。`ensure_ascii=False` 是刻意的：
中文标题必须按原字符入哈希，而不是按 `\\uXXXX` 转义。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

#: 参与内容哈希的字段（顺序无关：序列化时 `sort_keys=True`）。
CANONICAL_FIELDS: tuple[str, ...] = ("kind", "title", "sections", "claims", "open_problems")

#: 三个**列表**字段：缺字段与空列表必须算同一版。
#:
#: 实测踩到的坑（`T4-A` 第一批）：夹具/调用方给的字典常常没有 `sections` 键，
#: 而落库后的行是 `[]` —— 若把"缺键"读成 `None`，同一份内容就有两种哈希，
#: `content_hash_mismatch` 会在**完全干净**的库上开火
#: （实测：`test_fully_clean_workspace_has_no_errors` 就是这样红的）。
LIST_FIELDS: tuple[str, ...] = ("sections", "claims", "open_problems")

#: 引用里钉的哈希长度（`doc:<doc>#<claim>@<前 16 位>`）。
REF_HASH_LEN = 16


def _canonical_bytes(row: Mapping[str, Any]) -> bytes:
    """把稿件的内容序列化成规范字节串（键排序、无多余空白、非 ASCII 原样）。

    列表字段用 `row.get(k) or []` 归一：缺键、`None`、空列表三者在**内容**上
    是同一件事（"这篇稿子没有那一节"），不许因为写法不同而算出两个哈希。
    """
    payload: dict[str, Any] = {k: row.get(k) for k in CANONICAL_FIELDS}
    for k in LIST_FIELDS:
        payload[k] = payload.get(k) or []
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return text.encode("utf-8")


def content_sha256_of(row: Mapping[str, Any]) -> str:
    """稿件内容的规范哈希（小写十六进制，64 位）。"""
    return hashlib.sha256(_canonical_bytes(row)).hexdigest()


def claims_hash_of(row: Mapping[str, Any]) -> str:
    """只覆盖 `claims` 的哈希（单条断言级签名用；`draft/29` §8.8.2 的 `claims_hash`）。"""
    text = json.dumps(row.get("claims") or [], sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ref_hash_of(row: Mapping[str, Any]) -> str:
    """引用里钉的那一段哈希（`content_sha256` 的前 `REF_HASH_LEN` 位）。"""
    return content_sha256_of(row)[:REF_HASH_LEN]


def doc_ref(doc_id: str, claim_id: str, row: Mapping[str, Any]) -> str:
    """构造一条内部引用：`doc:<doc_id>#<claim_id>@<前 16 位>`。"""
    return f"doc:{doc_id}#{claim_id}@{ref_hash_of(row)}"


def parse_doc_ref(ref: str) -> tuple[str, str, str] | None:
    """拆内部引用；不是 `doc:` 形状时返回 `None`（不抛 —— 调用方要能把它当"另一档"）。

    形状：`doc:<doc_id>#<claim_id>@<hash>`；`@` 之后可缺省（缺省 = 没钉版本，
    那种引用由调用方判成 `internal_citation_stale` 或直接拒，取决于它的口径 —— 本函数只拆）。
    """
    if not ref.startswith("doc:"):
        return None
    body = ref[4:]
    head, _, rev = body.partition("@")
    doc_id, _, claim_id = head.partition("#")
    if not doc_id or not claim_id:
        return None
    return doc_id, claim_id, rev


def selftest() -> int:
    """自检：同一内容不同键序 ⇒ 同哈希；改一个字节 ⇒ 变；中文按原字符入哈希。"""
    a = {"kind": "paper", "title": "谱的界", "sections": [], "claims": [], "open_problems": []}
    b = {"open_problems": [], "claims": [], "sections": [], "title": "谱的界", "kind": "paper"}
    if content_sha256_of(a) != content_sha256_of(b):
        print("[fail] 键序不同的同一内容必须同哈希")
        return 1
    if content_sha256_of(a) == content_sha256_of({**a, "title": "谱的界!"}):
        print("[fail] 改一个字节必须换哈希")
        return 1
    if content_sha256_of({**a, "status": "accepted"}) != content_sha256_of(a):
        print("[fail] status 不参与内容哈希（生命周期不是内容）")
        return 1
    if len(content_sha256_of(a)) != 64 or ref_hash_of(a) != content_sha256_of(a)[:REF_HASH_LEN]:
        print("[fail] 哈希长度或引用段口径不对")
        return 1
    ref = doc_ref("0001", "C1", a)
    if parse_doc_ref(ref) != ("0001", "C1", ref_hash_of(a)):
        print("[fail] doc_ref 与 parse_doc_ref 不自洽")
        return 1
    if parse_doc_ref("lit:0003#p.4") is not None or parse_doc_ref("doc:0001") is not None:
        print("[fail] 非 doc: 形状或缺 claim 时必须返回 None")
        return 1
    print("SELF-CHECK DONE")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(selftest())
