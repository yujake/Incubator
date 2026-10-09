# -*- coding: utf-8 -*-
"""S1q：正文重建 —— 定理库取原文逐字搬、序号重写、映射落 `dependencies`。

业主 `draft/97` §9.5 与 §7 的表把这件事的判据列出来了，但口径没写全；
`§16.1` 是施工前补写的定死版（四步 + 五条判据）。这里落的就是那四步：

| 步 | 做什么 | 为什么是这么定的 |
|---|---|---|
| ① 取原文逐字搬 | 被搬的 `statements.statement_full` 一字不改地进正文 | 逐字是回验的前提（`quoteverify` 的同一套纪律：改一个字就没法拿原文比） |
| ② 序号重写 | 论文自己那一套号（`"1.5"`）由论文给；台账里的 `label` 不许被改写 | §9.5 的 `label` 行：论文号是"人话标签"，台账标签是另一件事 |
| ③ 引用 `stmt:` | 正文那一处断言必须带 `stmt:<源号>` | `closing.PAPER_LEDGER_PREFIXES`（`stmt:`/`exp:`/`rel:`）是"论文承载本轮结果"那一位 |
| ④ 映射落 `dependencies` | 一条映射一行，字段组合见 §9.5 | "从哪份手稿的哪条断言来"要可复算 |

## 为什么是"检查器 + 写入器"而不是"一个生成正文的函数"

正文（`.tex`/markdown）是人/模型产物，本框架不替它排版；这一层能机器判的是
"搬进来的东西对不对得上台账"：逐字、引用、映射三条链必须闭环。
所以这里给出 `assign_paper_numbers`（②）、`move_theorem`（①③ 的形状）、
`map_theorem`（④ 的写入）与 `check_paper_ledger`（五条判据的唯一实现）。

## 五条判据（`check_paper_ledger`）

1. 逐字：搬进正文的片段与源行 `statement_full` 逐字相等（按引文口径归一后比）；
2. 引用在：论文的 `claims[].citations` 里必须有 `stmt:<源号>`；
3. 映射唯一：一个论文号恰好一条映射；两个不同 `stmt:` 映射到同一个论文号 ⇒ 红；
4. 不许悬空 / 不许多余：映射指向的论文号必须真的在正文里（`\ref` 悬空 ⇒ 红），
   正文里搬了而没有映射 ⇒ 红，映射了而正文里没有 ⇒ 红（两个方向都判：只判一个方向
   会让"映射表比正文多一行"这种事没人看得见）；
5. 两阶段引用：论文里出现 `doc:` 引用 ⇒ 红（论文不许引别的稿子，手稿之间才可以）。

三态：任何一路输入读不成 ⇒ `checked=False` + `reason`（"没查成"不是"没问题"）。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from . import schema as S
from . import textutil as T

#: 论文里出现这些前缀就算"引了别的稿子"（两阶段引用口径：论文不许引稿子）。
PAPER_FORBIDDEN_PREFIXES: tuple[str, ...] = ("doc",)


def assign_paper_numbers(statement_rows: Iterable[Mapping[str, Any]], *,
                         section: str = "1", start: int = 1) -> dict[str, str]:
    """给一组台账行分配论文号（② 序号重写）：`{"<stmt_id>": "<section>.<n>"}`。

    口径（定死，可复算）：

    - 顺序按 `stmt_id` 升序（不按调用方给的次序，也不按 `kind` ——
      否则同一次调用换个入参次序就会得到不同的论文号，那正是"不可复算"）；
    - 号形如 `"1.5"`（`section` 由调用方给：论文里那一节的号）；
    - 台账行的 `label` 一个字节都不改：论文号是论文这一侧的概念。

    `section` 传空 ⇒ 只用序号（`"5"`）。给的 `start` 是这一节里第一个号。
    """
    ids = sorted({str(r.get("stmt_id") or "") for r in statement_rows if str(r.get("stmt_id") or "")})
    out: dict[str, str] = {}
    for i, sid in enumerate(ids, start=int(start)):
        out[sid] = f"{section}.{i}" if str(section).strip() else str(i)
    return out


def move_theorem(statement_row: Mapping[str, Any], paper_number: str) -> dict[str, Any]:
    """把一条台账行做成"搬进正文"的形状（① 逐字 + ③ 引用 + ② 论文号）。

    返回 `{"stmt_id","paper_number","text","citation","ref","kind","label"}`：

    - `text` 是 `statement_full` 的逐字副本（这里只做"取出"，不做任何改写 ——
      任何规整都该发生在核对那一侧，而不是在搬运这一侧）；
    - `citation` = `"stmt:<源号>"`（正文里那一处断言必须带上它）；
    - `ref` = `"\\ref{thm:<论文号>}"`（正文的交叉引用记号，`check_paper_ledger`
      拿它判"悬空 `\\ref`"）。
    """
    sid = str(statement_row.get("stmt_id") or "")
    return {"stmt_id": sid,
            "paper_number": str(paper_number),
            "text": str(statement_row.get("statement_full") or ""),
            "citation": f"stmt:{sid}" if sid else "",
            "ref": f"\\ref{{thm:{paper_number}}}",
            "kind": str(statement_row.get("kind") or ""),
            "label": str(statement_row.get("label") or "")}


def dep_row_for_mapping(*, dep_id: str, statement_row: Mapping[str, Any],
                        paper_doc_id: str, claim_id: str, paper_number: str,
                        created_at: str, created_by: str = "agent-G",
                        found: bool = True) -> dict[str, Any]:
    """④ 映射那一行的字段组合（`draft/97` §9.5 逐格定死）。

    `used_by = "doc:<论文号>#<claim_id>"`：论文也是 `documents` 行，而这一格回答的是
    "论文里哪一处断言压在这条定理上"。`source_doc_id` / `source_claim_id` 记
    "这条定理原本出自哪份手稿的哪条断言"（台账行的 `doc_id` + 调用方给的 claim 号）——
    于是"搬进来的"与"原来的"两头都指得出来。

    【注意】 不许再给 `source_stmt_id`：`Dependency.validate` 的"四选一"是硬闸
    （被依赖的那一端最多给一个），而 §9.5 定死的那一端是手稿（`doc`）。
    这一点是实测撞出来的（第一版同时给了 `source_doc_id` 与 `source_stmt_id`，
    当场以"给两个就说不清这条边到底依赖谁"被拒）—— 也就是说
    "被搬的是哪一条 `statements` 行"由检查器那一侧的 `moved[]` 记着，
    而不是靠这一行多挂一个来源端。`found=False` 时落 `dangling`（被搬那条找不到了），
    并写清为什么（`Dependency.validate` 要求非空理由）。
    """
    return {"dep_id": str(dep_id),
            "used_by": f"doc:{paper_doc_id}#{claim_id}",
            "kind": str(statement_row.get("kind") or ""),
            "label": str(paper_number),
            "source_doc_id": str(statement_row.get("doc_id") or "") or None,
            "source_claim_id": str(claim_id or "") or None,
            "status": "closed" if found else "dangling",
            "status_reason": ("" if found else
                              "被搬的那条台账行找不到 ⇒ 这条映射落 dangling，不静默丢"
                              "（映射表少一行 = '搬进去的东西从哪来'不可复算）"),
            "created_at": created_at, "created_by": created_by}


def map_theorem(tx: Any, *, statement_row: Mapping[str, Any], paper_doc_id: str,
                claim_id: str, paper_number: str) -> dict[str, Any]:
    """在已开的事务里写一行映射（④）。号由唯一分配器给（不许手写 `dep_id`）。"""
    dep_id = tx.alloc_id(S.TABLES["dependencies"]["id_kind"])
    row = dep_row_for_mapping(dep_id=dep_id, statement_row=statement_row,
                              paper_doc_id=paper_doc_id, claim_id=claim_id,
                              paper_number=paper_number, created_at=S.now_iso())
    obj = S.row_from_dict("dependencies", row)
    obj.validate()
    data = obj.to_dict()
    tx.upsert("dependencies", data, note="paper_ledger:map")
    return data


# ---------------------------------------------------------------- 检查器（五条判据的唯一实现）


def _citations_of(paper: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for c in paper.get("claims") or []:
        if isinstance(c, Mapping):
            out.extend(str(x) for x in (c.get("citations") or []) if str(x).strip())
    return out


def check_paper_ledger(paper: Mapping[str, Any], moved: Sequence[Mapping[str, Any]],
                       statement_rows: Iterable[Mapping[str, Any]],
                       dep_rows: Iterable[Mapping[str, Any]],
                       *, refs: Iterable[str] = ()) -> dict[str, Any]:
    """论文与台账对不对得上（五条判据；三态）。

    `paper` 是 `documents` 那一行；`moved` 是正文里搬了的那些
    （`move_theorem(...)` 的形状）；`refs` 是正文里出现的交叉引用记号
    （缺省 ⇒ 从 `moved[i]["ref"]` 收；调用方可以给更全的一份）。
    返回 `{"checked", "problems", "reason", "counts"}`：`problems` 每项
    `{"code", "stmt_id"/"paper_number", "why"}`，空列表 = 全对得上。
    """
    out: dict[str, Any] = {"checked": False, "problems": [], "reason": "",
                           "counts": {"moved": 0, "mapped": 0, "citations": 0}}
    try:
        by_id = {str(r.get("stmt_id") or ""): dict(r) for r in statement_rows}
        deps = [dict(d) for d in dep_rows]
        cites = _citations_of(paper)
        moved_list = [dict(m) for m in moved]
        ref_set = {str(r) for r in refs} if refs else {str(m.get("ref") or "") for m in moved_list}
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报
        out["reason"] = f"输入读不成（{type(exc).__name__}: {exc}）"
        return out
    out["checked"] = True
    out["counts"] = {"moved": len(moved_list), "mapped": len(deps), "citations": len(cites)}
    problems: list[dict[str, Any]] = []
    # ⑤ 两阶段引用：论文里出现 doc: ⇒ 红（本批只用这条口径，不重开）
    for c in cites:
        prefix, _code = T.citation_ref_parts(c)
        if prefix in PAPER_FORBIDDEN_PREFIXES:
            problems.append({"code": "doc_reference_in_paper", "ref": str(c),
                             "why": ("论文里不许引别的稿子（两阶段引用口径）："
                                     "`doc:` 只在手稿之间可用")})
    # ① 逐字 + ② 引用在 + 3 映射唯一
    numbers: dict[str, str] = {}
    for m in moved_list:
        sid = str(m.get("stmt_id") or "")
        num = str(m.get("paper_number") or "")
        src = by_id.get(sid)
        if src is None:
            problems.append({"code": "moved_from_missing_row", "stmt_id": sid,
                             "why": f"正文里搬的 {sid!r} 在台账里找不到 ⇒ 逐字与出处都无从核"})
            continue
        want = T.normalize_for_quote(str(src.get("statement_full") or ""))
        got = T.normalize_for_quote(str(m.get("text") or ""))
        if want and got != want:
            problems.append({"code": "not_verbatim", "stmt_id": sid, "paper_number": num,
                             "why": ("搬进正文的片段与台账那一行不是逐字相等 ⇒ "
                                     "回验无从做起（逐字是回验的前提）")})
        if f"stmt:{sid}" not in cites:
            problems.append({"code": "missing_citation", "stmt_id": sid, "paper_number": num,
                             "why": (f"正文里那一处断言没有 `stmt:{sid}` 引用 ⇒ "
                                     "'搬进去的东西从哪来'不可复算")})
        numbers.setdefault(num, sid)
    # 3b 重号：两条映射行指向同一个论文号就是红（§9.5 的原话是"落两行指向同一个
    # `label` ⇒ 红"）—— 判的是映射行，不是"正文里那两条各写了什么号"：
    # 后者在同号时本来就看不出撞（两条各自的号字段都写着 `1.1`）。
    by_label: dict[str, set[str]] = {}
    for d in deps:
        if str(d.get("used_by") or "").startswith("doc:"):
            by_label.setdefault(str(d.get("label") or ""), set()).add(str(d.get("used_by") or ""))
    for num, users in by_label.items():
        if num and len(users) > 1:
            problems.append({"code": "duplicate_paper_number", "paper_number": num,
                             "why": (f"论文号 {num} 被 {len(users)} 条映射行共用了 "
                                     f"（{sorted(users)}）⇒ 两个不同的定理不许共用一个论文号")})
    # 4 映射：一对一（悬空 \ref / 缺映射 / 多余映射，两个方向都判）
    mapped_numbers = {str(d.get("label") or "") for d in deps
                      if str(d.get("used_by") or "").startswith("doc:")}
    for num, sid in numbers.items():
        if num not in mapped_numbers:
            problems.append({"code": "missing_mapping", "stmt_id": sid, "paper_number": num,
                             "why": (f"正文里搬了 {sid}（论文号 {num}）却没有映射行 ⇒ "
                                     "`dependencies` 里查不到这条搬运")})
    for num in sorted(mapped_numbers):
        if num and num not in numbers:
            problems.append({"code": "orphan_mapping", "paper_number": num,
                             "why": (f"映射行指着论文号 {num}，而正文里没有这一条 ⇒ "
                                     "映射表比正文多（这一半不判就永远没人看得见）")})
        if num and f"\\ref{{thm:{num}}}" not in ref_set:
            problems.append({"code": "dangling_ref", "paper_number": num,
                             "why": (f"映射行给了论文号 {num}，而正文的交叉引用里没有它 ⇒ "
                                     "`\\ref` 悬空")})
    out["problems"] = problems
    return out
