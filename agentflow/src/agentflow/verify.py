"""全局不变量校验。

为什么需要一个独立的校验器，而不是"相信写入路径是对的"：

- 写入路径只覆盖"正常流程"。而本系统的数据会被**两个智能体 + 可能的人工编辑**同时
  触碰，schema 级校验（`schema.validate`）只能保证"单行自洽"，管不了**跨表一致性**
  ——例如 `relations.lit_id` 指向的文献是否真的存在、`related_concepts` 是否与关系表
  一致、`processed=true` 的文献是否真的处理过。
- 校验器也是**自愈的入口**：`related_concepts` 若与派生结果不一致，报告里会给出
  "应该是多少"，可以直接据此修复，而不是靠人肉比对。

`verify` 分两级：默认只做静态检查（快，随时可跑）；`--deep` 会重新打开文献做引文复核
（慢，需要文件在本地）。`--deep` 报两类引文问题，分级不同：引文**找不到**
（`quote_not_found` / `quote_known_unverifiable`）与引文**逐字存在、但页码不在声明的
范围内**（`page_range_mismatch`，`E-11`）—— 后者的引文是真的，错的是页码标注，
所以是 warning，处置是改 `page_range` 而不是查幻觉。
"""

from __future__ import annotations

import re

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import dedup as D
from . import schema as S
from . import signatures as SIG
from . import textutil as T
from .agent_b import QUOTE_OUT_OF_DECLARED_RANGE as OUT_OF_DECLARED_RANGE
from .agent_e import declared_name_of_notes
from .formalgw import concluded_names
from .quoteverify import check_quote
from .store import MAX_ID, Store

#: 引用前缀的受控词表 —— `documents.*.claims[].citations` 里允许出现的那几档。
#:
#: `D10`：它此前只以字面量的形式各写两份（判据里一份 `("rel","lit","exp","eval")`、
#: 拒绝消息里一份 `"（应为 rel:/lit:/exp:）"`），而两份不等 —— 消息漏了 `eval:`，
#: 而 `eval:` 正是上面刚被单独判过的那一档。调用方按消息去改写法，会把一个
#: 合法的 `eval:` 引用当成非法。所以词表只留这一个来源，判据与消息都从它派生
#: （`FC-03`：同一件事不许有两份定义）。
#:
#: 下面那条导入期断言把词表与"逐档的判据分支"钉在一起：判据是
#: `elif kind == "rel" and ...` 这样逐档写的（引用形状由 `textutil.citation_ref_parts`
#: 给，这里只关心它落在哪一档），于是"词表里有、分支里没有"（或反过来）会直接炸，
#: 而不是让一条拒绝消息把人指向一个错的写法 —— `D10` 就是那样活了很久：
#: 没有任何一条既有断言会因为消息写错而变红。
CITATION_KINDS: tuple[str, ...] = ("rel", "lit", "exp", "eval", "doc", "stmt")
#: 逐档判据分支里各写了哪些 kind。它与 `CITATION_KINDS` 必须同轮改 ——
#: 这个常量是"分支那一侧"的声明，为的是让漂移在导入期就可见（见上面的断言）。
_BRANCH_KINDS: tuple[str, ...] = ("rel", "lit", "exp", "eval", "doc", "stmt")
assert set(CITATION_KINDS) == set(_BRANCH_KINDS), (
    f"CITATION_KINDS={sorted(CITATION_KINDS)} 与逐档判据分支 "
    f"{sorted(_BRANCH_KINDS)} 脱钩 —— 两边必须同轮改"
    "（改词表就要同时加/删一条 `elif kind == ...` 分支）"
)


@dataclass
class Issue:
    level: str  # error | warning
    table: str
    row_id: str | None
    code: str
    message: str

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "table": self.table,
            "row_id": self.row_id,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class VerifyReport:
    # `checked` 的值是三态的（`errors-5`）：整数 = 查了多少条；
    # None = 这一项没查成（例如计数器找不到对应的表）。
    # 缺键仍然只表示"这一类检查不适用于本次审计"，与 None 不是一回事。
    checked: dict[str, int | None] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    deep: bool = False

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "deep": self.deep,
            "checked": self.checked,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


def _id_contiguity(rows: list[dict], id_field: str) -> tuple[bool, list[str], int]:
    """检查 4 位 ID 是否从 0000 起连续无空洞。

    空洞本身**不是错误**（ID 只需唯一+单调），但值得报警告：它通常意味着
    "分配了 ID 却没建成行"，也就是某次事务中途出过问题。

    `D-R44`（第 44 轮新发现，判据四第 5 组的负控里撞出来的）：**非数字 ID 不许
    把审计器炸掉**。实测形态（`temp/g5-mp3.txt`）：库里有一行 `lit_id='raw-p3-97'`
    （裸写/迁移脚本造出来的坏行）时，旧实现 `int(ids[-1])` 直接抛
    `ValueError: invalid literal for int() with base 10: 'raw-p3-97'` ——
    `verify_all` 于是从"审计器"变成"崩溃点"：调用方拿到的是一次 Python 异常，
    而不是一条"这一行 ID 不合法"的 finding。三态纪律里"查了、结论是坏"与
    "没查成"必须分开，而**崩掉两者都不是**。
    现在：非数字 ID 被显式报出来（`missing` 里给出那些串），`maxid` 只取数字 ID 的
    最大值（一个数字 ID 都没有时为 -1，与"空表"同形 —— 那本身会由 schema 级判据接住）。
    """
    ids = sorted(str(r[id_field]) for r in rows if id_field in r)
    if not ids:
        return True, [], -1
    numeric = [i for i in ids if i.isdigit()]
    bad = sorted({i for i in ids if not i.isdigit()})
    if bad:
        # 有非法 ID ⇒ 这一条判据的结论是"坏"（不是"没查成"），并把它报出来。
        return False, bad, (max(int(i) for i in numeric) if numeric else -1)
    missing: list[str] = []
    for i in range(len(ids)):
        want = f"{i:04d}"
        if ids[i] != want:
            missing.append(want)
    return (not missing), missing, int(ids[-1])


def _check_1(rep, store):
    """`verify_all` 的第 1 段（行 162–265）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- schema 级（逐表逐行）
    for table in S.TABLES:
        doc = store.read(table)
        rep.checked[table] = len(doc.get("rows") or [])
        try:
            S.validate_table(table, doc)
        except ValueError as e:
            rep.issues.append(Issue("error", table, None, "schema_invalid", str(e)))

    requests = store.rows("search_requests")
    literature = store.rows("literature")
    concepts = store.rows("concepts")
    relations = store.rows("relations")

    lit_by_id = {r["lit_id"]: r for r in literature}
    con_by_id = {r["concept_id"]: r for r in concepts}
    rel_by_id = {r["relation_id"]: r for r in relations}

    # ---- ID 唯一性与连续性
    #
    # ⚠️ **"哪些表属于 4 位编号空间"必须从 schema 推导，不许写死表名。**
    #
    # 这里原先只写了 `if table == "search_requests": continue`。新增
    # `reprocess_requests`（ID 形如 `p-NNNN`）之后，`_id_contiguity` 会对它做
    # `int("p-0001")` ⇒ **verify 自己崩掉**，而崩掉的原因与"库里有没有问题"
    # 完全无关。这类"写死一张名单"的缺陷在本项目里已经出现过三次
    # （roles 字符串、sync_counters 的 kind 列表、现在这里）。
    # 判据只有一个：**这个表的 id_field 是否被 ID_COUNTERS 覆盖**。
    counter_fields = set(S.ID_COUNTERS.values())
    for table, spec in S.TABLES.items():
        rows = store.rows(table)
        idf = spec["id_field"]
        ids = [r.get(idf) for r in rows]
        dupes = {i for i in ids if ids.count(i) > 1}
        for d in sorted(dupes):
            rep.issues.append(Issue("error", table, d, "duplicate_id", f"{idf}={d} 重复出现"))
        if idf not in counter_fields:
            continue  # 非 4 位编号空间（`r-NNNN` / `p-NNNN` 这类过程记录）
        contiguous, missing, maxid = _id_contiguity(rows, idf)
        if not contiguous:
            rep.issues.append(
                Issue(
                    "warning",
                    table,
                    None,
                    "id_gap",
                    f"{idf} 不连续，缺 {missing[:8]}{'…' if len(missing) > 8 else ''}；"
                    "通常是某次事务分配了 ID 但未建成行（无害，但值得查）",
                )
            )

    # ---- counters 与已用 ID 的一致性
    counters = (store.read("counters") or {}).get("counters", {}) or {}
    rep.checked["counters"] = len(counters)
    for kind, field in S.ID_COUNTERS.items():
        # 从 ID_COUNTERS 反查表名，而不是写死一张映射 —— 否则每新增一张表都要改这里，
        # 忘了改就会在 verify 里 KeyError（新增 research_questions/analysis_reports 时正是如此）。
        table = next((t for t, sp in S.TABLES.items() if sp["id_field"] == field), None)
        if table is None:
            # `errors-5`：这里原先直接 continue，既不记 Issue 也不写 checked，
            # 于是"这个计数器没查成"与"查过、没问题"在报告里完全同形
            # （checked 里缺一个键不等于有问题，ok 也照样是 True）。
            # 审计器最不该有的形态就是"悄悄少查一项而仍然报通过"：
            # 将来某次 schema 改名只改了 ID_COUNTERS，这条路径就会安静地
            # 让整个计数器检查消失。所以这里显式写三态里的"没查成"这一档，
            # 并记一条 issue。级别取 warning 而不是 error：它本身不是数据坏了，
            # 是"这次审计有一项没做" —— 但它必须出现在报告里。
            # 与上面那处 `idf not in counter_fields` 的跳过区分开：那里的跳过
            # 是判据的一部分（非 4 位编号空间本就不该做连续性检查），
            # 这里的跳过是失败。
            rep.checked[kind] = None
            rep.issues.append(
                Issue(
                    "warning",
                    "counters",
                    kind,
                    "counter_table_missing",
                    f"计数器 {kind}（id_field={field}）在 schema.TABLES 里找不到对应的表 "
                    f"⇒ 这一项没查成（不是查过没问题）：无法核对计数器与已用 ID 是否一致。"
                    "处理：确认 ID_COUNTERS 与 TABLES 是否已被同时改过。",
                )
            )
            continue
        # `D-R44`：这里也必须容忍非法 ID。旧实现 `int(r[field])` 会把
        # "库里有一行 ID 不成形态"变成一次 `ValueError` 崩溃 —— 而 `verify_all`
        # 是审计器，它该把这件事**报出来**（`_id_contiguity` 已经会报），
        # 不该自己炸。非数字 ID 在这里被跳过（已经由上面那条 `id_gap` 记账）。
        used = [int(r[field]) for r in store.rows(table)
                if field in r and str(r[field]).isdigit()]
        want = (max(used) + 1) if used else 0
        got = int(counters.get(kind, 0))
        if got < want:
            rep.issues.append(
                Issue(
                    "error",
                    "counters",
                    kind,
                    "counter_behind",
                    f"{kind} 计数器为 {got}，但表里已用到 {want - 1}；继续分配会**撞号**。"
                    "处理：把 counters.json 的该值改为 max(已用)+1，或 `agentflow rebuild`。",
                )
            )
        if got > MAX_ID + 1:
            rep.issues.append(Issue("error", "counters", kind, "counter_overflow", f"{kind} 计数器 {got} 超出 4 位空间"))

    return con_by_id, concepts, lit_by_id, literature, rel_by_id, relations, requests




def _check_2(rep, lit_by_id, literature, requests, store):
    """`verify_all` 的第 2 段（行 267–335）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- 请求 ↔ 文献 双向可追溯
    for r in requests:
        rid = r.get("request_id")
        for lid in r.get("result_lit_ids") or []:
            if lid not in lit_by_id:
                rep.issues.append(
                    Issue("error", "search_requests", rid, "dangling_lit_ref",
                          f"result_lit_ids 含不存在的文献 {lid}")
                )
        # ⚠️ **这条检查必须与 schema 的规则一致，否则它就是一个假警报源。**
        #
        # 原实现是"`done=true` 且既无 `result_lit_ids` 也无 `last_error` ⇒ error"。
        # 但 `outcome="no_results"`（搜索正常执行、确实没有命中）**本来就是一个
        # 有效的终局**：它没有文献、也没有错误，而 `schema.SearchRequest.validate`
        # 明确允许这种组合（见 `SEARCH_OUTCOMES` 的说明："no_results —— 搜索正常
        # 执行但确实没有命中（这是一个**有效结论**）"）。
        #
        # 后果实测：一条 `outcome="no_results"` 的请求（A 在无检索后端时如实登记）
        # 让 `verify` 报 error —— 而"假报警比不校验更糟，因为它会训练人忽略告警"。
        # 这正是 FC-11（校验器与写入方必须共享同一份规则）的教科书形态。
        #
        # 修法：**只在 schema 判不出语义的那一种情况下报**——`outcome` 缺失
        # （历史数据）且既无文献也无错误，此时"跑过了"与"空转"确实无法区分。
        # 其余情形交由 `schema.SearchRequest.validate` 负责（它在写表时已经跑过）。
        if r.get("done") and r.get("outcome") is None \
                and not (r.get("result_lit_ids") or r.get("last_error")):
            rep.issues.append(
                Issue("error", "search_requests", rid, "done_without_result",
                      "done=true、outcome 缺失、且既无 result_lit_ids 也无 last_error —— "
                      "无法判断是真的搜索过还是空转。请补 outcome（ok/no_results/search_failed/gave_up）")
            )
    for l in literature:
        lid = l.get("lit_id")
        for rid in l.get("source_request_ids") or []:
            if not any(x.get("request_id") == rid for x in requests):
                rep.issues.append(
                    Issue("warning", "literature", lid, "unknown_request_ref",
                          f"source_request_ids 指向未知请求 {rid}")
                )
        # ---- 命中校验（`draft/37` §2 R1b + §16 P2 的 A 行）：**下错了的那一篇不许被消化**。
        #
        # 为什么这条必须是 error 而不是 warning：真机实测（2026-10-01）里 A 把 Brown 1971
        # 下成了 2022 年另一篇 CLT 论文 —— 登记成功、下载成功、569,776 字节的真 PDF，
        # **没有任何地方报出来**，于是下游会拿一篇无关文献去建概念与命题。
        # 这是"静默登记成找到"的形态，与 FC-23 那一族同源（把不是自己的东西当成自己的）。
        #
        # 分级：`mismatch` + 已消化 ⇒ error（必须撤）；`partial` + 已消化 ⇒ warning
        # （同一篇、元数据有出入，值得看一眼但不必然错）。
        if str(l.get("matched") or "") == "mismatch" and l.get("processed"):
            rep.issues.append(Issue(
                "error", "literature", lid, "mismatch_literature_processed",
                f"文献 {lid} 的命中校验结论是 matched='mismatch'（检索回来的不是派活时点名的"
                "那一篇），却已经被 processed ⇒ 下游会拿一篇无关文献建概念与命题。"
                "要么重新检索到对的那一篇，要么把这一行的 processed 撤回去（§2 R1b："
                "mismatch 不许进 processed）",
            ))
        elif str(l.get("matched") or "") == "partial" and l.get("processed"):
            rep.issues.append(Issue(
                "warning", "literature", lid, "partial_match_processed",
                f"文献 {lid} 的 matched='partial'（同一篇但元数据有出入）且已被消化："
                "确认了是同一篇就把它改成 exact，不是就按 mismatch 处理 —— 别让它停在中间态",
            ))

    # ---- 文献：文件是否真的在
    for l in literature:
        lid = l.get("lit_id")
        p = l.get("path")
        dl = l.get("download") or {}
        if p:
            try:
                ap = store.library_path(p)
            except Exception as e:
                rep.issues.append(Issue("error", "literature", lid, "path_escape", str(e)))
                continue
            if ap is None or not ap.exists():
                rep.issues.append(
                    Issue("error", "literature", lid, "file_missing",
                          f"表里登记了 path={p} 但文件不存在（B 会跳过它）")
                )
        elif dl.get("status") == "ok":
            rep.issues.append(
                Issue("warning", "literature", lid, "ok_without_path",
                      "download.status=ok 但没有 path，元数据与实际不一致")
            )
        elif dl.get("status") == "content_mismatch":
            # 缺陷 #8 的契约：检测到内容类型不符时，**字节必须留作证据**。
            # 丢了文件就再也无法回答"对方到底返回了什么"，而那个答案正是修复的依据。
            rep.issues.append(
                Issue("warning", "literature", lid, "mismatch_without_evidence",
                      "download.status=content_mismatch 但没有 path —— 证据字节没被保留，"
                      "事后无法核查对方返回了什么（缺陷 #8 的契约要求保留）")
            )




def _check_3(rep, con_by_id, lit_by_id, rel_by_id, relations):
    """`verify_all` 的第 3 段（行 337–402）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- 关系
    for r in relations:
        rid = r.get("relation_id")
        cids = r.get("concept_ids") or []
        if len(cids) < 2:
            rep.issues.append(Issue("error", "relations", rid, "too_few_concepts", f"概念组只有 {len(cids)} 个"))
        if cids != sorted(set(cids)):
            rep.issues.append(Issue("error", "relations", rid, "unsorted_concepts", f"concept_ids 未升序去重：{cids}"))
        for c in cids:
            if c not in con_by_id:
                rep.issues.append(Issue("error", "relations", rid, "dangling_concept", f"引用了不存在的概念 {c}"))
        if r.get("concept_group_key") != T.concept_group_key(cids):
            rep.issues.append(
                Issue("error", "relations", rid, "stale_group_key",
                      f"concept_group_key={r.get('concept_group_key')!r} 与 concept_ids 派生的 "
                      f"{T.concept_group_key(cids)!r} 不一致（判重会失效）")
            )
        lid = r.get("lit_id")
        if lid not in lit_by_id:
            rep.issues.append(Issue("error", "relations", rid, "dangling_lit", f"引用了不存在的文献 {lid}"))
        else:
            # 需求的因果顺序：只有处理过的文献才可能产出关系
            if not lit_by_id[lid].get("processed"):
                rep.issues.append(
                    Issue("error", "relations", rid, "lit_not_processed",
                          f"文献 {lid} 的 processed=false，但它已经有了关系（违反 §2.4 的写入顺序）")
                )
        if r.get("duplicate_of") and r["duplicate_of"] not in rel_by_id:
            rep.issues.append(Issue("warning", "relations", rid, "dangling_duplicate_of",
                                    f"duplicate_of 指向不存在的关系 {r['duplicate_of']}"))
        pr = r.get("page_range") or {}
        if pr.get("start") is not None and pr.get("end") is not None and pr["start"] > pr["end"]:
            rep.issues.append(Issue("error", "relations", rid, "bad_page_range", f"页码 start>end：{pr}"))

    # ---- 关系去重自检：同一概念组内不应存在两条 quote_normalized 相同的 active 关系
    by_group: dict[str, list[dict]] = {}
    for r in relations:
        if r.get("status") == "rejected":
            continue
        by_group.setdefault(r.get("concept_group_key", ""), []).append(r)
    for gk, rows in by_group.items():
        seen: dict[str, str] = {}
        for r in rows:
            q = r.get("quote_normalized") or T.normalize_for_quote(r.get("quote", ""))
            if not q:
                continue
            if q in seen:
                rep.issues.append(
                    Issue("error", "relations", r.get("relation_id"), "duplicate_quote",
                          f"与 {seen[q]} 在同一概念组 {gk} 内有完全相同的引文（判重漏了）")
                )
            else:
                seen[q] = r.get("relation_id")
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                qa = a.get("quote_normalized") or T.normalize_for_quote(a.get("quote", ""))
                qb = b.get("quote_normalized") or T.normalize_for_quote(b.get("quote", ""))
                if not qa or not qb or qa == qb:
                    continue
                s = T.similarity(qa, qb)
                if s >= 0.92:
                    rep.issues.append(
                        Issue("warning", "relations", b.get("relation_id"), "near_duplicate",
                              f"与 {a.get('relation_id')} 相似度 {s:.3f} ≥ 0.92 却都被标为 "
                              f"{b.get('status')}/{a.get('status')}（判重阈值配置可能被改动）")
                    )




def _check_4(rep, con_by_id, concepts, lit_by_id, rel_by_id, relations, requests, store):
    """`verify_all` 的第 4 段（行 404–467）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- 概念：related_concepts 是否与关系表派生结果一致
    for c in concepts:
        cid = c.get("concept_id")
        related = c.get("related_concepts") or []
        if related != sorted(set(related)):
            rep.issues.append(Issue("error", "concepts", cid, "unsorted_related", f"related_concepts 未升序去重：{related}"))
        if cid in related:
            rep.issues.append(Issue("error", "concepts", cid, "self_related", "related_concepts 含自身"))
        for r in related:
            if r not in con_by_id:
                rep.issues.append(Issue("error", "concepts", cid, "dangling_related", f"related_concepts 含不存在的概念 {r}"))
        want = D.derive_related_concepts(cid, relations, include_suspect=True)
        if related != want:
            rep.issues.append(
                Issue(
                    "warning",
                    "concepts",
                    cid,
                    "related_drift",
                    f"related_concepts 与关系表派生结果不一致：表中 {related}，应为 {want}。"
                    "可用 `agentflow repair --related` 整体重算修复。",
                )
            )

    # ---- C/D 新增表的代号外键（DESIGN-TOOLS.md §8.4）
    # 这两张表全靠 4 位代号互相引用（`origin`、`related_*_ids`、`waiting_request_ids`）。
    # 代号引错是静默的：报告照样生成，只是溯源到不存在的东西。所以必须在校验器里拦住。
    questions = store.rows("research_questions")
    reports = store.rows("analysis_reports")
    req_ids = {r.get("request_id") for r in requests}

    for q in questions:
        qid = q.get("question_id")
        for cid in q.get("related_concept_ids") or []:
            if cid not in con_by_id:
                rep.issues.append(Issue("error", "research_questions", qid, "dangling_concept_ref",
                                        f"related_concept_ids 含不存在的概念 {cid}"))
        for rid in q.get("related_relation_ids") or []:
            if rid not in rel_by_id:
                rep.issues.append(Issue("error", "research_questions", qid, "dangling_relation_ref",
                                        f"related_relation_ids 含不存在的关系 {rid}"))
        for lid in q.get("evidence_lit_ids") or []:
            if lid not in lit_by_id:
                rep.issues.append(Issue("error", "research_questions", qid, "dangling_lit_ref",
                                        f"evidence_lit_ids 含不存在的文献 {lid}"))
        for rid in q.get("waiting_request_ids") or []:
            if rid not in req_ids:
                rep.issues.append(Issue("error", "research_questions", qid, "dangling_request_ref",
                                        f"waiting_request_ids 含不存在的请求 {rid}"))
        # 状态与等待集的一致性（schema 只保证"needs_evidence 必须有等待集"，
        # 这里反向检查"已完成的问题不该还挂着等待项"）
        if q.get("status") in ("answered", "dropped") and q.get("waiting_request_ids"):
            rep.issues.append(Issue("warning", "research_questions", qid, "stale_waiting",
                                    f"status={q.get('status')} 却仍挂着 waiting_request_ids="
                                    f"{q.get('waiting_request_ids')}（应清空，否则 poll 会永远等下去）"))

    for ar in reports:
        arid = ar.get("report_id")
        mp = ar.get("markdown_path")
        if mp:
            p = store.root / mp
            if not p.exists():
                rep.issues.append(Issue("warning", "analysis_reports", arid, "report_file_missing",
                                        f"登记了 markdown_path={mp} 但文件不存在"))

    return questions, req_ids




def _check_5(rep, lit_by_id, questions, store):
    """`verify_all` 的第 5 段（行 469–580）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- E/F/G/H 新增表的交叉引用（同样是"悬空引用"检查的一部分）
    #
    # 为什么每个新表都要在这里过一遍：`schema.py` 的行校验只能保证**本行内部**自洽
    # （字段非空、枚举合法、交叉字段一致），它**看不到别的表**。
    # "这个 lit_id 真的存在吗"这种问题只有在这里才可能被发现 —— 而它正是
    # "依赖集不闭合"的技术形态。
    experiments = store.rows("experiments")
    plans = store.rows("attack_plans")
    documents = store.rows("documents")
    dependencies = store.rows("dependencies")
    findings = store.rows("review_findings")

    exp_by_id = {r["experiment_id"]: r for r in experiments}
    doc_by_id = {r["doc_id"]: r for r in documents}
    # FC-24：稿件可以引评测结果，所以它的索引要在稿件检查之前就绪
    eval_by_id = {r["eval_id"]: r for r in store.rows("eval_results")}
    q_id_set = {q.get("question_id") for q in questions}

    for e in experiments:
        eid = e.get("experiment_id")
        qid = e.get("for_question_id")
        if qid and qid not in q_id_set:
            rep.issues.append(Issue("error", "experiments", eid, "dangling_question_ref",
                                    f"for_question_id 指向不存在的研究问题 {qid}"))
        # FC-22 的**第二道**闸：schema 已在写入时拒绝"计算类称 proof"，
        # 这里再核一遍表里的存量数据（历史数据、手工改过的数据都在射程内）。
        if e.get("evidence_kind") == "proof" and e.get("method") != "formal":
            rep.issues.append(Issue("error", "experiments", eid, "evidence_kind_overclaim",
                                    f"method={e.get('method')!r} 却记录 evidence_kind='proof'。"
                                    "数值/符号/穷举都只是交叉验证，不构成证明（FC-22）"))
        if e.get("code_path") and not str(e.get("code_hash") or "").strip():
            rep.issues.append(Issue("error", "experiments", eid, "unhashed_experiment_code",
                                    "有 code_path 却没有 code_hash：这样的'可复现'只是口号"
                                    "（脚本一改，记录就指向了另一段代码）"))
        if e.get("result") == "refutes" and not e.get("counterexample"):
            rep.issues.append(Issue("error", "experiments", eid, "refutation_without_counterexample",
                                    "result='refutes' 但没给 counterexample ⇒ '证否'不可复核"))

    plan_ids = {r["plan_id"] for r in plans}
    for pl in plans:
        pid = pl.get("plan_id")
        qid = pl.get("for_question_id")
        if qid and qid not in q_id_set:
            rep.issues.append(Issue("error", "attack_plans", pid, "dangling_question_ref",
                                    f"for_question_id 指向不存在的研究问题 {qid}"))
        ppid = pl.get("parent_plan_id")
        if ppid and ppid not in plan_ids:
            rep.issues.append(Issue("error", "attack_plans", pid, "dangling_plan_ref",
                                    f"parent_plan_id 指向不存在的计划 {ppid}"))
        # 子目标引用的实验必须真的存在 —— "有数值支持"这句话必须可核对
        for sg in pl.get("subgoals") or []:
            for xid in list(sg.get("experiment_ids") or []) + list(sg.get("proof_experiment_ids") or []):
                if str(xid) not in exp_by_id:
                    rep.issues.append(Issue("error", "attack_plans", pid, "dangling_experiment_ref",
                                            f"子目标 {sg.get('sid')} 引用了不存在的实验 {xid}"))
        if pl.get("status") == "stalled" and not str(pl.get("best_partial") or "").strip():
            rep.issues.append(Issue("error", "attack_plans", pid, "stalled_without_partial",
                                    "stalled 却没写 best_partial：攻坚停下来了却什么都不交出去"))

    # ---- I12 / FC-23：**依赖闭合检查**（本块是 verify 里最"数学"的一条）
    #
    # 数学上把引用的定理当成自己的定理，会**静默放大结论的适用范围**。
    # 下面这条检查把"我们依赖了一个拿不到的外部结论"变成一条**可查询的事实**，
    # 而不是藏在引文角标里。
    dep_ok = 0
    #: `refuted` / `disputed` 的条数（`draft/37` §16 P1 加的两档）。
    #: 单独记一个读数而不是并进 `dep_ok`：它俩不是"没闭合"，而是"引用本身有问题"，
    #: 处置方向相反（补来源 / 撤结论）。并进同一个数会让两种局面在读数上同形。
    dep_refuted_disputed = 0
    for d in dependencies:
        did = d.get("dep_id")
        used_by = str(d.get("used_by") or "")
        st = str(d.get("status") or "")
        if st == "closed":
            lid, xeid = d.get("source_lit_id"), d.get("source_experiment_id")
            sdid = str(d.get("source_doc_id") or "")
            scid = str(d.get("source_claim_id") or "")
            if lid and lid not in lit_by_id:
                rep.issues.append(Issue("error", "dependencies", did, "dangling_dep",
                                        f"status='closed' 但 source_lit_id={lid} 不在文献表里 ⇒ 空头支票"))
            elif xeid and xeid not in exp_by_id:
                rep.issues.append(Issue("error", "dependencies", did, "dangling_dep",
                                        f"status='closed' 但 source_experiment_id={xeid} 不在实验表里 ⇒ 空头支票"))
            elif sdid and sdid not in doc_by_id:
                # 内部来源（`draft/30` §T4-A）：引用我们自己的一篇稿子
                rep.issues.append(Issue("error", "dependencies", did, "dangling_dep",
                                        f"status='closed' 但 source_doc_id={sdid} 不在稿件表里 ⇒ 空头支票"))
            elif sdid and scid and scid not in {
                    str(cl.get("claim_id")) for cl in (doc_by_id[sdid].get("claims") or [])
                    if isinstance(cl, dict)}:
                rep.issues.append(Issue("error", "dependencies", did, "dangling_dep",
                                        f"status='closed' 但 source_claim_id={scid} 不在稿件 "
                                        f"{sdid} 的断言里 ⇒ 空头支票"))
            elif sdid and str(doc_by_id[sdid].get("status") or "") != "accepted":
                rep.issues.append(Issue(
                    "error", "dependencies", did, "internal_dep_not_accepted",
                    f"内部来源稿件 {sdid} 的 status={doc_by_id[sdid].get('status')!r}（不是 accepted）"
                    "⇒ 依赖了一条**没审过**的内部断言。内部引用成立的前提是那一版被审过",
                ))
            else:
                dep_ok += 1
        elif st == "external_unavailable":
            # ⚠️ 分级（FC-13）：这是"我们**已经知道并记录**了这个前提拿不到" ——
            # 属于**已知边界**，不是谎报 ⇒ warning。
            # 报成 error 会把红灯训练成噪音，于是真正的 error 也会被忽略。
            rep.issues.append(Issue(
                "warning", "dependencies", did, "dangling_dep_external",
                f"{used_by} 依赖的「{str(d.get('label') or '')[:80]}」在本项目可得范围之外："
                f"{str(d.get('status_reason') or '')[:160]}。"
                "**引用该结论时必须一并声明这一前提**",
            ))
        elif st == "dangling":
            rep.issues.append(Issue("error", "dependencies", did, "dangling_dep",
                                    f"{used_by} 的依赖「{str(d.get('label') or '')[:80]}」悬空且未闭合。"
                                    "要么补上来源（closed），要么说明为什么拿不到（external_unavailable）"))
        elif st == "refuted":
            # `draft/37` §9 的落点：**被证否的前提撑不起任何东西**。
            # 报 error 而不是 warning：它不是"已知边界"，而是"压在它上面的结论现在
            # 都不能算数了"，必须有人去撤（或改成 disputed 并送裁决）。
            rep.issues.append(Issue(
                "error", "dependencies", did, "refuted_dependency_in_use",
                f"{used_by} 依赖的「{str(d.get('label') or '')[:80]}」已被证否："
                f"{str(d.get('status_reason') or '')[:160]}。"
                "压在它上面的结论必须一起降档或撤回（§9：如果错的是文献，"
                "那么以它为据的结论就不能再算数）",
            ))
        elif st == "disputed":
            # 与 `external_unavailable` 同级（warning）：这是"我们**已经记录**了
            # 这里有争议、尚未裁决"，属于已知边界而不是谎报。§16 P3 的收工门会
            # 把未裁决的 disputed 当成拦路条件 —— 那是**交付**的口径，比 verify 更严；
            # 两处不同是刻意的：verify 说"账记得对"，收工门说"这样还不能交"。
            rep.issues.append(Issue(
                "warning", "dependencies", did, "disputed_dependency_in_use",
                f"{used_by} 依赖的「{str(d.get('label') or '')[:80]}」有争议、尚未裁决："
                f"{str(d.get('status_reason') or '')[:160]}。"
                "在裁决之前，引用它的结论必须带上这个保留（§8/§9 的矛盾闭环）",
            ))
        if st in ("refuted", "disputed"):
            dep_refuted_disputed += 1
    rep.checked["dependencies_closed"] = dep_ok
    rep.checked["dependencies_refuted_or_disputed"] = dep_refuted_disputed

    return dependencies, doc_by_id, documents, eval_by_id, exp_by_id, experiments, findings




def _check_6(rep, dependencies, documents, exp_by_id, experiments):
    """`verify_all` 的第 6 段（行 582–716）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- **依赖的缺陷继承**（来自对本地先例 Danus 的观摩）
    #
    # Danus 的收束点是"让**前提不干净**沿着依赖链传播下去"。我们已经有
    # `dependencies` 表了，缺的只是**让它在前提变脏时说话**。三条检查：
    #
    # 1. `proof` 级断言引用的实验本身不是 `proof` 级 ⇒ error。
    #    这是"证据等级被偷偷升级"的机械形态：断言的等级不能强于它的依据。
    # 2. `status="closed"` 的依赖指向一条 `inconclusive` 的实验 ⇒ error。
    #    "closed" 的意思是"这条依赖有支撑"；一条没跑出结论的实验不是支撑。
    # 3. `proof` 级断言挂在一条**未闭合**（`dangling`/`external_unavailable`）的依赖上 ⇒ error。
    #    这是最要紧的一条：整套框架允许"引用一个拿不到的外部定理"，但**必须限制它的后果** ——
    #    拿不到的前提撑不起 `proof` 级的主张。（若挂的是 `cross_check` 级断言，维持原来的 warning。）
    weaker: list[tuple[str, str, str, str]] = []  # (docid, cid, expid, exp_kind)
    for doc in documents:
        docid = str(doc.get("doc_id") or "")
        for c in doc.get("claims") or []:
            if c.get("evidence_kind") != "proof":
                continue
            cid = str(c.get("claim_id") or "")
            for x in c.get("citations") or []:
                # 引用解析的**唯一实现**在 `textutil.citation_ref_parts`（`P-5`：
                # 这里曾经内联着第二份 `partition(":")` + `split("#")`）。
                kind, ref = T.citation_ref_parts(x)
                if kind != "exp":
                    continue
                e = exp_by_id.get(ref)
                if e is not None and str(e.get("evidence_kind")) != "proof":
                    weaker.append((docid, cid, ref, str(e.get("evidence_kind"))))
    for docid, cid, expid, exp_kind in weaker:
        rep.issues.append(Issue(
            "error", "documents", docid, "proof_claim_rests_on_weaker_evidence",
            f"断言 {cid} 声称 evidence_kind='proof'，但它引用的实验 {expid} 只有 "
            f"evidence_kind={exp_kind!r} ⇒ **断言不能强于它的依据**（FC-22）",
        ))

    # ---- `E-2`（人裁 = verify 侧事后加严，观测时刻 2026-09-26 20:5x）
    #
    # 背景：proof 只锚在**自报字段**上 —— 手写一行 `method='formal'` +
    # `evidence_kind='proof'` + 任意 `verifier_output` 就能进库，而 `verify` 与 gates
    # 都不会响（重审实测，登记为 `draft/28` 的 `E-2`）。
    # 所有者裁定走 (b)：**在 verify 里事后加严**（不动 schema、不做迁移）。
    #
    # 两条硬检查（都 fail-closed，报 error）：
    #   1. proof 级实验行的 `verifier_output` 里必须有绑在被检查声明名上的
    #      结构化诊断（`R2-AN-2`，见下面的实现与它的注释）。
    #   2. proof 级 claim 不能只引 `lit:` —— 它必须至少引一条 `exp:`。
    #      （"引了 exp: 但那条实验较弱"由上面那条 `weaker` 判据负责，两条互补。）
    #
    # ## 判据 1 为什么从"子串"改成"绑名诊断"（`R2-AN-2`，2026-09-27）
    #
    # 旧判据是 `verifier_subject_key in verifier_output`，两个方向都不严：
    # ① 太宽：`claim_key='L'` 是 `'Lean4: no goals'` 的子串 ⇒ 一条完全自报的 proof 不报；
    #    名字只出现在一句与结论无关的告警里（`unused variable 'foo'`）也算"检查器管过它"；
    # ② 太窄（更危险）：把判据绑到 `claim_key` 上本身就是错的 —— 生产路径上 `claim_key` 与
    #    Lean 声明名可以合法地不同（`tests/test_agent_e_formal_path.py` 的正控：
    #    `claim_key='probe-eq'` 而 Lean 声明是 `probe_eq`，Lean 标识符不许带连字符）。
    #    所以判据绑定的是检查器实际检查的那个声明名，它写在 `notes` 里
    #    （写入点：`agent_e` 的 `_declared_name_note`，读法：`declared_name_of_notes`），
    #    读不到时才退回 `verifier_subject_key`（"本行声称检查器管的就是它"）。
    #    命名诊断的读法只有一处实现：`formalgw.concluded_names`（`FC-03`）。
    #    写入期（`formalgw.check_lean` 的 `nm in blob`）比这里宽是刻意的，
    #    不是判据漂移：写入期要保"真跑过检查器"，审计期要保"依据能被读出来"。
    #
    # ## 这条判据的证据上界（`R2b-AN-2-A`，2026-09-27 如实登记）
    #
    # 上面那个"被检查的声明名"取自 `notes` —— 一个可写的自由文本字段，
    # 而本判据不校验 `notes` 里的名字等于本行的 `claim_key` / `verifier_subject_key`
    # （后两者由 `schema.Experiment.validate` 强制相等，前者没有任何约束）。
    # 所以这条判据能到的一层是"这条 proof 行的依据可以被读出来"，
    # 不是"这条依据就是本行命题的"：手工改写 `notes` 里那一段声明名
    # （写成另一条输出里真有的名字），可以让一条 claim 与另一命题的 proof 行
    # 一起通过本判据。`R2b` 的 F 段夹具就是这个形态的实测。
    #
    # 为什么不补一条交叉判据（例如要求 `verifier_subject_key` 也出现在输出里）：
    # 生产路径上"被检查的声明名"与 `claim_key` 可以合法地毫不相干 ——
    # `agent_f.py` 把子目标的 `name` 直接传给 E（`:874`），而 `claim_key` 可能是
    # `problem_key#sid`（`:864`）；`.lean` 文件名同样可以与命题名无关
    # （`agent_e.py` 的 `str(name or path.stem)`）。那种合规行会被判成"自报"，
    # 正是 §41.1 记过的"判据过窄 ⇒ 红掉合规输入"（那一族已经犯过 12 次）。
    # 要真把这一层补上，得先在写入期把"声明名"与"本行命题"的对应关系
    # 变成受约束的事实（那要改 schema 与工具层的参数面），不是审计侧能单方面加的。
    # 因此这里不改判据，只把上界写清楚：不许再把这条判据读成"绑死了声明名"。
    selfreported: list[tuple[str, str, str, str]] = []
    for e in experiments:
        if str(e.get("evidence_kind")) != "proof":
            continue
        eid = str(e.get("experiment_id") or "")
        key = str(e.get("verifier_subject_key") or "").strip()
        out_text = str(e.get("verifier_output") or "")
        # 被检查的声明名：优先 `notes` 里那一段（写入期的事实），
        # 读不到（历史行 / 手工行）才退回本行自己声称的 `verifier_subject_key`。
        nm = declared_name_of_notes(e.get("notes")) or key
        if not key or nm not in concluded_names(out_text):
            selfreported.append((eid, key, nm, out_text[:80]))
    for eid, key, nm, out_head in selfreported:
        rep.issues.append(Issue(
            "error", "experiments", eid, "selfreported_proof",
            f"实验 {eid} 声称 evidence_kind='proof'，但 `verifier_output` 里没有**绑在** "
            f"被检查声明名 {nm!r} 上的检查器诊断（本行 `verifier_subject_key={key!r}`；"
            f"要的是 `'<声明名>' does not depend on any axioms` 或 "
            f"`'<声明名>' depends on axioms: [...]`；输出开头：{out_head!r}）"
            "⇒ **这条 proof 是自报的**：没有任何检查器对这条命题给出过结论。"
            "处置：拿 `formalgw`/真检查器重跑一次，把它的原始输出写回 `verifier_output`；"
            "若本来就只是断言，就把 `evidence_kind` 改成它真实的等级"
            "（`E-2`/`R2-AN-2`，FC-22：断言不能强于它的依据）。",
        ))

    no_exp_ref: list[tuple[str, str]] = []
    for doc in documents:
        docid = str(doc.get("doc_id") or "")
        for c in doc.get("claims") or []:
            if c.get("evidence_kind") != "proof":
                continue
            kinds = {T.citation_ref_parts(x)[0] for x in (c.get("citations") or [])}
            if "exp" not in kinds:
                no_exp_ref.append((docid, str(c.get("claim_id") or "")))
    for docid, cid in no_exp_ref:
        rep.issues.append(Issue(
            "error", "documents", docid, "proof_claim_without_formal_experiment",
            f"断言 {cid} 声称 evidence_kind='proof'，却**一条 `exp:` 引用都没有** ⇒ "
            "没有任何形式化实验参与过这条断言（`E-2`，与 `doc_tools.check_proofs` 的写入期"
            "判据同口径，差别只是这一条事后也对**历史行**生效）。",
        ))

    for d in dependencies:
        if str(d.get("status")) != "closed":
            continue
        did = d.get("dep_id")
        xeid = d.get("source_experiment_id")
        if xeid and str(exp_by_id.get(str(xeid), {}).get("result")) == "inconclusive":
            rep.issues.append(Issue(
                "error", "dependencies", did, "closed_dep_on_inconclusive_experiment",
                f"标为 closed 的依赖指向实验 {xeid}，而该实验的结果是 inconclusive ⇒ "
                "没有结论的实验不能作为已闭合的支撑",
            ))




def _check_7(rep, dependencies, doc_by_id, documents, eval_by_id, exp_by_id, lit_by_id, rel_by_id, relations,
             stmt_by_id):
    """`verify_all` 的第 7 段（行 718–864）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    #: 哪些依赖状态会让压在它上面的 `proof` 级断言变成违规，以及各自的理由码。
    #:
    #: 为什么要分开三个理由码（而不是一个 `proof_claim_on_bad_dependency`）：
    #: 本仓的代码就是**处置把手** —— `dangling`/`external_unavailable` 要做的是
    #: "去把来源补齐"，`refuted` 要做的是"把结论撤下来或降档"，`disputed` 要做的是
    #: "送裁决"。三件事的接手人都不一样（前者 G、中者 D+G、后者人）。合并成一个码，
    #: 台账上就只剩一句"有个问题"，而"谁去做、做什么"必须靠读 message 才猜得出来。
    unusable_dep_reasons: dict[str, tuple[str, str]] = {
        "dangling": ("proof_claim_with_unclosed_dependency", "未闭合"),
        "external_unavailable": ("proof_claim_with_unclosed_dependency", "在本项目可得范围之外"),
        "refuted": ("proof_claim_on_refuted_dependency", "已被证否"),
        "disputed": ("proof_claim_on_disputed_dependency", "有争议、尚未裁决"),
    }
    for d in dependencies:
        st = str(d.get("status"))
        if st not in unusable_dep_reasons:
            continue
        code, why = unusable_dep_reasons[st]
        used_by = str(d.get("used_by") or "")
        kind, _, ref = used_by.partition(":")
        if kind != "doc":
            continue
        docid, _, cid = ref.partition("#")
        doc = doc_by_id.get(docid)
        if doc is None or not cid:
            continue
        claim = next((c for c in doc.get("claims") or [] if str(c.get("claim_id")) == cid), None)
        if claim is None:
            continue
        if claim.get("evidence_kind") == "proof":
            rep.issues.append(Issue(
                "error", "dependencies", d.get("dep_id"), code,
                f"断言 {docid}#{cid} 声称 evidence_kind='proof'，却挂在一条{why}的依赖上"
                f"（「{str(d.get('label') or '')[:60]}」，status={st}）⇒ "
                "**拿不到 / 不算数的前提撑不起 proof 级的主张**。要么把该断言的等级降为 "
                "cross_check，要么补上可得的来源，要么先裁决这条依赖。",
            ))

    # ---- 稿件断言的可追溯性（FC-02）
    #
    # ⚠️ 这里除了"引用存不存在"，还要查**被引用的东西现在还算不算数**。
    #
    # 这一条来自对本地先例 Danus 的观摩：它有明确的**撤回（retraction）语义**，
    # 并强调"撤回会级联"、"没有 revoke 动作时要把撤回面向上暴露"。
    # 我们此前只有 `duplicate_of` / `status="rejected"` 这类**行级**状态，
    # 却**没有一条检查**去问"引用了它的那些结论还站得住吗" ——
    # 于是"关系被判重否决"与"稿件还在拿它当依据"可以长期共存而**没有任何报错**。
    # 这就是撤回不级联的形态：知识被撤回了，依赖它的结论却静默地留在那里。
    rejected_by_id: dict[str, dict] = {}
    suspect_ids: set[str] = set()
    for r in relations:
        rid = str(r.get("relation_id") or "")
        if not rid:
            continue
        st = str(r.get("status") or "active")
        if st == "rejected" or r.get("duplicate_of"):
            rejected_by_id[rid] = r
        elif st == "suspect":
            suspect_ids.add(rid)

    for doc in documents:
        docid = doc.get("doc_id")
        # ---- 行内自洽：`content_sha256` 是"审的是这一版"的锚（`draft/30` §T4-A）。
        # 它由写侧（G）算一次，这里**重算**比对 —— 存的哈希是一句声称，重算才是判据。
        stored_hash = str(doc.get("content_sha256") or "")
        if stored_hash:
            want_hash = SIG.content_sha256_of(doc)
            if stored_hash.lower() != want_hash:
                rep.issues.append(Issue(
                    "error", "documents", docid, "content_hash_mismatch",
                    f"content_sha256 与重算不符（存 {stored_hash[:16]}… / 算 {want_hash[:16]}…）"
                    "⇒「审批/引用钉的是这一版」这句话不成立。内容改过就必须重算（G 的 revise 会做）",
                ))
        for c in doc.get("claims") or []:
            cid = str(c.get("claim_id") or "")
            cites = c.get("citations") or []
            if not cites:
                rep.issues.append(Issue("error", "documents", docid, "unsupported_claim",
                                        f"断言 {cid} 没有 citations（无引用的断言不允许进入稿件）"))
                continue
            for x in cites:
                # 唯一实现在 `textutil.citation_ref_parts`（`P-5`）。与
                # `doc_tools.citation_ref_parts` 是**同一个函数**：两边不可能再给出
                # 不同答案（否则"G 认为合法"与"verify 认为悬空"会静默分家）。
                kind, ref = T.citation_ref_parts(x)
                if kind == "rel" and ref not in rel_by_id:
                    rep.issues.append(Issue("error", "documents", docid, "dangling_citation",
                                            f"断言 {cid} 引用了不存在的关系 {ref}"))
                elif kind == "lit" and ref not in lit_by_id:
                    rep.issues.append(Issue("error", "documents", docid, "dangling_citation",
                                            f"断言 {cid} 引用了不存在的文献 {ref}"))
                elif kind == "exp" and ref not in exp_by_id:
                    rep.issues.append(Issue("error", "documents", docid, "dangling_citation",
                                            f"断言 {cid} 引用了不存在的实验 {ref}"))
                elif kind == "eval" and ref not in eval_by_id:
                    rep.issues.append(Issue("error", "documents", docid, "dangling_citation",
                                            f"断言 {cid} 引用了不存在的评测结果 {ref}"))
                elif kind == "stmt" and ref not in stmt_by_id:
                    # `E1/R-03`（`draft/49` §E1 方案 A，所有者授权主控代改）：`stmt:` 与
                    # 其余几档**同权** —— 加进词表就必须同时有一条真检查它的分支，
                    # 否则它变成"既不 warn 也没人查"的一类，那正是裁定时否掉方案 B 的
                    # 理由（逐字："不校验就等于不设防"）。
                    rep.issues.append(Issue("error", "documents", docid, "dangling_citation",
                                            f"断言 {cid} 引用了不存在的命题 {ref}"))
                elif kind == "doc":
                    # 内部引用（`draft/30` §T4-A）：`doc:<稿件>#<断言>@<哈希前 16 位>`。
                    # 三段都要真：稿件在、那条断言在、且**钉的哈希就是目标稿件当前这一版**。
                    parts = SIG.parse_doc_ref(str(x))
                    if parts is None:
                        rep.issues.append(Issue(
                            "error", "documents", docid, "dangling_doc_citation",
                            f"断言 {cid} 的内部引用 {x!r} 形状不对："
                            "应为 doc:<稿件>#<断言>@<内容哈希前 16 位>",
                        ))
                    else:
                        tdoc_id, tclaim_id, thash = parts
                        tdoc = doc_by_id.get(tdoc_id)
                        tclaims = {str(cl.get("claim_id")) for cl in (tdoc.get("claims") or [])
                                   if isinstance(cl, dict)} if tdoc else set()
                        if tdoc is None or tclaim_id not in tclaims:
                            rep.issues.append(Issue(
                                "error", "documents", docid, "dangling_doc_citation",
                                f"断言 {cid} 引用了不存在内部断言 {tdoc_id}#{tclaim_id}",
                            ))
                        elif str(tdoc.get("status") or "") != "accepted":
                            rep.issues.append(Issue(
                                "error", "documents", docid, "internal_citation_not_accepted",
                                f"断言 {cid} 引用的内部断言 {tdoc_id}#{tclaim_id} 所在稿件"
                                f"status={tdoc.get('status')!r}（不是 accepted）⇒ "
                                "引文图不能把没审过的稿子当来源（`draft/29` §8.5 第 1 条）",
                            ))
                        elif not thash or thash != SIG.content_sha256_of(tdoc)[:SIG.REF_HASH_LEN]:
                            # 比的是**重算出来的当前内容哈希**，不是行里存的那个字段：
                            # 内容改了而存字段没刷时，旧引用照样必须失效（存字段的问题
                            # 另有 `content_hash_mismatch` 单独报）。改一字节即失效，
                            # 说的就是这条。
                            rep.issues.append(Issue(
                                "error", "documents", docid, "internal_citation_stale",
                                f"断言 {cid} 引用 {tdoc_id}#{tclaim_id} 时钉的是 {thash or '(没钉哈希)'}，"
                                f"而该稿件当前内容是 "
                                f"{SIG.content_sha256_of(tdoc)[:SIG.REF_HASH_LEN]}"
                                " ⇒ 改稿之后旧引用失效（不许静默沿用）",
                            ))
                elif kind not in CITATION_KINDS:
                    # `D10`：消息里的词表从上面那个判据元组派生，不许再写一遍字面量 ——
                    # 两处各写一份时实测漏了 `eval:`（而它上一行刚被单独检查过）。
                    rep.issues.append(Issue("warning", "documents", docid, "unknown_citation_kind",
                                            f"断言 {cid} 的引用 {x!r} 前缀无法识别"
                                            f"（应为 {'/'.join(k + ':' for k in CITATION_KINDS)}）"))
                # ---- **撤回级联**：引用了已被否决的关系 ⇒ 结论失去依据
                if kind == "rel" and ref in rejected_by_id:
                    row = rejected_by_id[ref]
                    why = (f"判重（duplicate_of={row.get('duplicate_of')}）"
                           if row.get("duplicate_of") else "status='rejected'")
                    rep.issues.append(Issue(
                        "error", "documents", docid, "citation_to_retracted_relation",
                        f"断言 {cid} 引用了已被否决的关系 {ref}（{why}）⇒ "
                        "该结论的依据已被撤回。**撤回必须级联**：请改引幸存关系，或删掉这条断言。"
                        "（Danus 的做法是把撤回面向上暴露；我们在这里把它变成一条 error）",
                    ))
                elif kind == "rel" and ref in suspect_ids:
                    rep.issues.append(Issue(
                        "warning", "documents", docid, "citation_to_suspect_relation",
                        f"断言 {cid} 引用的关系 {ref} 处于 status='suspect'（依据可疑，未判定）⇒ "
                        "该结论目前只有**未经确认**的依据",
                    ))
            if c.get("evidence_kind") == "cross_check" and not str(c.get("disclaimer") or "").strip():
                rep.issues.append(Issue("error", "documents", docid, "overclaim",
                                        f"断言 {cid} 是 cross_check 却没有 disclaimer（FC-22）"))

    return rejected_by_id




def _check_8(rep, doc_by_id, findings, questions, rejected_by_id, store):
    """`verify_all` 的第 8 段（行 866–986）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- 研究问题的依据是否也已被撤回（同一类级联，作用在 D 的台账上）
    for q in questions:
        qid = q.get("question_id")
        stale = sorted(str(r) for r in (q.get("related_relation_ids") or []) if str(r) in rejected_by_id)
        if stale:
            rep.issues.append(Issue(
                "warning", "research_questions", qid, "question_based_on_retracted_relation",
                f"该问题的 related_relation_ids 含已被否决的关系 {stale} ⇒ "
                "研究可能建立在已撤回的依据上（需人工确认是否降级/关闭该问题）",
            ))

    # ---- 审校发现（H）
    for f in findings:
        fid = f.get("finding_id")
        doc_row = doc_by_id.get(str(f.get("doc_id")))
        if doc_row is None:
            rep.issues.append(Issue("error", "review_findings", fid, "dangling_doc_ref",
                                    f"finding 指向不存在的稿件 {f.get('doc_id')}"))
        if not str(f.get("evidence") or "").strip():
            rep.issues.append(Issue("error", "review_findings", fid, "finding_without_evidence",
                                    "审校发现没有 evidence —— 审校者的判断也需要证据"))
        if doc_row is not None and str(doc_row.get("status") or "") == "accepted" \
                and str(f.get("level")) == "error" \
                and str(f.get("status")) not in ("fixed", "wontfix", "disputed"):
            rep.issues.append(Issue("error", "review_findings", fid, "accepted_with_open_error",
                                    "稿件已被 accepted，但它还有未处置的 error 级发现"))

    # ---- 主控编队 / 花销 / 评测口径（`tasks` / `usage_ledger` / `eval_results`）
    #
    # 口径（主控 2026-10-06 自查要求）：这里是**台账全量**读，**不是委托计数** ——
    # 下面四条判据（父任务悬空 / 深度不连续 / 缺 input_key / 离线仍 running）
    # 与 usage 对账（`dangling_usage_task` / `usage_task_total_mismatch`）问的都是
    # "台账自己一致吗"。所以**顶趟行**（`role=<本体>`、`action="run"`、`called_by="user"`、
    # `depth=1`、`parent_task_id=None`、`input_key="top:…"`）在这里是一行**合法**记录：
    # 它不触发上面任何一条（父为 None、深度无父、input_key 非空、status=done），
    # 也不进任何 `checked[...]` 计数（本函数没有任何"tasks 行数"读数）。
    # ⇒ **不排除、不改口径**；数"派了几跳"的地方在 `reviewaccept._c_hops`
    # （那里已按 `called_by != "user"` 排除顶趟行，并留 `excluded_top_run_rows` 读数）。
    tasks = store.rows("tasks")
    usage = store.rows("usage_ledger")
    # ---- 幂等键的唯一性（"同一笔账被记了两次"的**唯一**自动防线）
    #
    # 为什么必须新增而不是复用 duplicate_id：重复记账的**两行 usage_id 不同**，
    # 所以按主键数重复永远不响；而 tasks.tokens 与账本汇总是**一起**虚高的，
    # 所以 usage_task_total_mismatch 也不响 —— 它们仍然"相等"，只是相等的是错的数。
    seen_idem: dict[str, str] = {}
    for u in usage:
        k = str(u.get("idem_key") or "").strip()
        if not k:
            continue
        if k in seen_idem:
            rep.issues.append(Issue(
                "error", "usage_ledger", u.get("usage_id"), "duplicate_idem_key",
                f"幂等键 {k} 出现两次（{seen_idem[k]} 与 {u.get('usage_id')}）⇒ "
                "同一笔账被记了两次，花销与预算翻倍",
            ))
        else:
            seen_idem[k] = str(u.get("usage_id"))
    evals = store.rows("eval_results")

    task_by_id = {str(r.get("task_id")): r for r in tasks}
    for r in tasks:
        tid = r.get("task_id")
        pid = r.get("parent_task_id")
        # 父任务必须存在 —— 否则"深度"这条链断了，而深度是判循环与判越权的依据
        if pid is not None and str(pid) not in task_by_id:
            rep.issues.append(Issue("error", "tasks", tid, "dangling_parent_task",
                                    f"parent_task_id={pid} 不在 tasks 表里 ⇒ 召唤链断了"
                                    "（深度/循环判据都依赖这条链）"))
        elif pid is not None:
            p = task_by_id[str(pid)]
            if int(r.get("depth") or 0) != int(p.get("depth") or 0) + 1:
                rep.issues.append(Issue("error", "tasks", tid, "task_depth_discontinuous",
                                        f"depth={r.get('depth')} 但父任务 {pid} 的 depth="
                                        f"{p.get('depth')} ⇒ 子任务深度必须恰为父+1（FC-18 ③）"))
        # 判重键为空 ⇒ 循环检测对它无效
        if not str(r.get("input_key") or "").strip():
            rep.issues.append(Issue("warning", "tasks", tid, "task_without_input_key",
                                    "input_key 为空 ⇒ 这条召唤**无法参与循环检测**"
                                    "（同一 (role, action, input_key) 出现在祖先链上才算循环）"))
        # 僵尸：verify 是离线跑的，所以任何仍在 running 的行都是"没有 end 的 start"
        if str(r.get("status")) == "running":
            rep.issues.append(Issue("warning", "tasks", tid, "task_still_running",
                                    f"status=running（started_at={r.get('started_at')}）—— "
                                    "离线校验时它是一条**没有 end 的 start**。可能是崩溃残留；"
                                    "本项目**不自动续跑**（重跑一个可能已经写了半张表的任务更危险），"
                                    "由人决定是弃掉还是重发"))
        # artifacts 的判据**不在这里**：它是 `capabilities.audit_task_ledger` 的
        # "唯一实现"（那一份的 docstring 逐字这么写）。这里转发过去取它的判定结果，
        # 而不是再写一份 —— 实测过漂移的代价：R-47 的产出摘要（文件路径）先在
        # `verify.py` 这份副本里被认下，`audit_task_ledger` 那份仍在报，于是
        # `verify_all` 干净、`Conductor.verify_tasks()` 报 61 条（`draft/28` §161 的 R-58）。
        from . import capabilities as _C

        for issue in _C.audit_task_ledger([r], store=store):
            if issue.code in ("unknown_artifact_kind", "dangling_task_artifact"):
                rep.issues.append(Issue(issue.level, "tasks", tid, issue.code, issue.message))

    usage_by_task: dict[str, int] = {}
    for u in usage:
        uid = u.get("usage_id")
        tk = u.get("task_id")
        if tk is not None and str(tk) not in task_by_id:
            rep.issues.append(Issue("error", "usage_ledger", uid, "dangling_usage_task",
                                    f"task_id={tk} 不在 tasks 表里 ⇒ 这笔花销挂不到任何一次召唤上"))
        if tk is not None:
            usage_by_task[str(tk)] = usage_by_task.get(str(tk), 0) + int(u.get("tokens_total") or 0)
    for tk, total in sorted(usage_by_task.items()):
        declared = int((task_by_id.get(tk) or {}).get("tokens") or 0)
        if declared != total:
            rep.issues.append(Issue(
                "warning", "tasks", tk, "usage_task_total_mismatch",
                f"tasks.tokens={declared} 与 usage_ledger 汇总的 {total} 不一致 ⇒ "
                "两处对同一次召唤的花销给出了不同的数字（预算判断会按哪一份？）",
            ))
    rep.checked["usage_tokens_total"] = sum(int(u.get("tokens_total") or 0) for u in usage)

    # 同一口径下的同一个数字不该有两个值
    eval_key: dict[tuple, list[dict]] = {}
    for e in evals:
        k = (str(e.get("claim_key")), str(e.get("benchmark")), str(e.get("benchmark_version")),
             str(e.get("split")), int(e.get("k") or 0))
        eval_key.setdefault(k, []).append(e)
    for k, rows in sorted(eval_key.items()):
        vals = {float(r.get("value") or 0.0) for r in rows}
        if len(vals) > 1:
            rep.issues.append(Issue(
                "error", "eval_results", rows[0].get("eval_id"), "eval_duplicate_conflicting",
                f"同一口径 {k} 下出现了互相冲突的值 {sorted(vals)} ⇒ "
                "口径相同却给出不同的数字，至少有一条是错的（FC-24：口径就是数字的一部分）",
            ))




def _check_9(rep, documents, questions, req_ids, store):
    """`verify_all` 的第 9 段（行 988–1073）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- FC-24 的**渲染层 gate**：报告里的数字必须能追到一条带完整口径的评测结果
    #
    # 为什么这条检查必须有：FC-24 的判据②是"缺任一字段的数字**不得进入对外报告**"。
    # 而 `EvalResult.validate` 只能在**登记时**保证字段齐全 —— 它管不到
    # **正文里写了一个数字却没引用任何评测记录**这种情况。
    # 而后者才是真正会流出去的形态：报告里一句"pass@1 达到 97%"，
    # 读者无法知道那是 LLM judge 分、还是端到端精确值、还是别人论文的数字。
    #
    # 同一个 miniF2F 数字可以是四件完全不同的事，同对模型在两口径下差 13–30 个百分点
    # （`08-…md` §A.5.5）。**所以"没带口径的数字"与"没有出处的断言"是同一类错误。**
    #
    # 判据写成"出现了基准数字的形态 **且** 没有任何 `eval:` 引用" ⇒ warning。
    # 分级为 warning 而不是 error：正则识别"基准数字"必然有假阳性
    # （正文里的年份、章节号、页码都可能是数字），所以它交付的是**指针**，
    # 而不是缺陷判定 —— 与 linter 的 R006 同一取舍。
    _bench_number = re.compile(r"(pass@\s*\d+|\d+(?:\.\d+)?\s*%|\bSOTA\b|\bstate[- ]of[- ]the[- ]art\b)")
    for doc in documents:
        docid = doc.get("doc_id")
        for c in doc.get("claims") or []:
            cid = str(c.get("claim_id") or "")
            text = str(c.get("text") or "")
            m = _bench_number.search(text)
            if not m:
                continue
            kinds = {T.citation_ref_parts(x)[0] for x in (c.get("citations") or [])}
            if "eval" in kinds:
                continue
            rep.issues.append(Issue(
                "warning", "documents", docid, "number_without_eval_scope",
                f"断言 {cid} 的正文里出现了基准数字「{m.group(0)}」，但它**没有引用任何 "
                "`eval:` 评测记录** ⇒ 这个数字的口径（基准/版本/切分/k/去污染/来源）无法追溯。"
                "FC-24：**口径不是补充说明，口径就是那个数字的一部分**。"
                "请补一条 `eval:<id>` 引用，或改写这句话去掉数字",
            ))

    # ---- FC-05：每个数组字段都必须声明是"集合"还是"序列"
    import dataclasses as _dc

    for table, spec in S.TABLES.items():
        row_cls = spec["row"]
        declared = S.array_kinds(table)
        for f in _dc.fields(row_cls):
            if f.type in ("list[str]", "list[dict]", "list[Any]") or str(f.type).startswith("list["):
                if f.name not in declared:
                    rep.issues.append(Issue(
                        "error", table, None, "undeclared_array_field",
                        f"字段 {table}.{f.name} 是数组但没在 schema.ARRAY_FIELD_KINDS 里声明"
                        "是 set 还是 seq。未声明的数组会被默认当成集合 ⇒ **顺序被静默破坏**"
                        "（FC-05 的由来正是'跳序被升序不变量吃掉'）",
                    ))

    # ---- D 的提问台账（模块私有文件，不在 schema 里）
    # `tools/research_tools.py` 刻意把"本问题已经问过 A 什么"记在
    # `data/research_request_ledger.json` 而不是 schema 表里（避免牵动 LOCK_ORDER/rebuild）。
    # 代价是它**不能从 events.jsonl 重建**。既然接受了这个代价，就必须让它**可观测**：
    # 否则台账与主表一旦漂移，D 会重复提问或永远等不到，而没有任何地方会报错。
    ledger_path = store.data / "research_request_ledger.json"
    if ledger_path.exists():
        try:
            led = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            rep.issues.append(Issue("error", "research_request_ledger", None, "ledger_corrupt",
                                    f"台账不是合法 JSON（{e}）；注意它**无法从 events.jsonl 重建**，"
                                    "只能人工修复或删除（删除会退化为'可能重复提问一次'）"))
            led = None
        if isinstance(led, dict):
            q_by_id = {q["question_id"]: q for q in questions}
            for i, row in enumerate(led.get("rows") or []):
                if not isinstance(row, dict):
                    rep.issues.append(Issue("error", "research_request_ledger", None, "ledger_bad_row",
                                            f"第 {i} 行不是对象"))
                    continue
                qid = row.get("question_id")
                if qid and qid not in q_by_id:
                    rep.issues.append(Issue("error", "research_request_ledger", qid, "ledger_dangling_question",
                                            f"台账引用了不存在的研究问题 {qid}"))
                for rid in row.get("request_ids") or row.get("waiting_request_ids") or []:
                    if rid not in req_ids:
                        rep.issues.append(Issue("error", "research_request_ledger", qid, "ledger_dangling_request",
                                                f"台账引用了不存在的请求 {rid}"))
                # 台账说"还在等"，主表却说这个问题的等待集是空的 → 两者漂移
                if row.get("open") and qid in q_by_id:
                    if not q_by_id[qid].get("waiting_request_ids"):
                        rep.issues.append(Issue("warning", "research_request_ledger", qid, "ledger_drift",
                                                "台账认为该问题仍有未完成提问，但 research_questions."
                                                "waiting_request_ids 为空 —— 两者已漂移，D 的去重判断会失准"))




def _check_10(rep, allow_fulltext_quote_fallback, deep, extract_text, lit_by_id, quote_widen, relations, store):
    """`verify_all` 的第 10 段（行 1075–1144）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- 深度：重新打开文献复核引文
    if deep:
        if extract_text is None:
            rep.issues.append(Issue("warning", "relations", None, "deep_unavailable",
                                    "要求 --deep 但未提供 extract_text，跳过引文复核"))
        else:
            doc_cache: dict[str, Any] = {}
            for r in relations:
                rid = r.get("relation_id")
                lid = r.get("lit_id")
                if lid not in lit_by_id:
                    continue
                if lid not in doc_cache:
                    ap = store.library_path(lit_by_id[lid].get("path"))
                    try:
                        doc_cache[lid] = extract_text(ap) if ap and ap.exists() else None
                    except Exception as e:
                        doc_cache[lid] = None
                        rep.issues.append(Issue("warning", "literature", lid, "reextract_failed", str(e)))
                doc = doc_cache[lid]
                if doc is None:
                    continue
                pr = S.PageRange.from_dict(r.get("page_range"))
                chk = check_quote(
                    doc,
                    r.get("quote", ""),
                    pr,
                    widen=quote_widen,
                    allow_fulltext_fallback=allow_fulltext_quote_fallback,
                )
                stored = r.get("quote_verified")
                if chk.verified is not stored:
                    rep.issues.append(
                        Issue("warning", "relations", rid, "quote_state_changed",
                              f"重算引文校验为 {chk.verified}（{chk.reason}），表中记录为 {stored}")
                    )
                if chk.reason == OUT_OF_DECLARED_RANGE:
                    # `E-11`：引文逐字存在、但落在声明的页码范围之外（±widen 内命中）。
                    # 修法前这里一声不响：`chk.verified` 是 True，与表里的 True 相同 ⇒
                    # 上面那条 `quote_state_changed` 不触发；下面那条 `verified is False` 也不触发。
                    # 于是"全部引文逐字可达"这条判据在所有页码都记错时照样通过。
                    #
                    # 加这一条是加严（`verify.py` 是 auth-audit 禁改区，只许加不允许放宽）：
                    # 不删任何既有判据、不改任何既有分级，只多报一个此前无人看见的形态。
                    # 定级 warning（不是 error）：引文本身是真的，错的是页码标注 ——
                    # "这条引文不存在"（error）与"页码写错了"（warning）处置不同。
                    rep.issues.append(Issue(
                        "warning", "relations", rid, "page_range_mismatch",
                        f"引文逐字存在，但不在关系声明的页码范围（{pr.label or pr}）内："
                        f"实际命中第 {chk.matched_page} 页（窗口 {chk.window!r}）。"
                        f"引文 {str(r.get('quote') or '')[:80]!r}…"
                        " ⇒ '逐字可达'是真的，但页码标注是错的：按声明页码去复核的人"
                        "会翻到一页空文，而那条路径上没有任何别的检查会提醒他（`E-11`）。"
                        "处置：把 `page_range` 改成实际命中页，或改写引文。",
                    ))
                if chk.verified is False:
                    # 区分"表里已经承认这条引文不可核实"与"表里说能核实、实际找不到"：
                    #  - 表里 `quote_verified=False` → 这是一个**已知并被记录**的缺陷，
                    #    重算只是**确认**它，不该升级成 error（否则任何刻意保留坏样本的数据集
                    #    都会永远 verify 失败，而 error 应当是"需要动手修的不一致"）。
                    #  - 表里 `quote_verified=True` → 表与现实矛盾，这才是 error（上面那条
                    #    `quote_state_changed` 已经报了，这里再补一条更明确的原因）。
                    level = "warning" if stored is False else "error"
                    code = "quote_known_unverifiable" if stored is False else "quote_not_found"
                    rep.issues.append(
                        Issue(level, "relations", rid, code,
                              f"引文在文献 {lid} 的声明页范围（{pr.label or pr}）内找不到："
                              f"{r.get('quote', '')[:80]!r}…"
                              + ("（表里已记录 quote_verified=false，属已知并承认的缺陷）" if stored is False else ""))
                    )




def _check_11(rep, documents, store):
    """`verify_all` 的第 11 段（行 1146–1203）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    # ---- 签名台账（`draft/30` §T4-B）：`accepted` 的稿件必须有**可核的**签名
    #
    # 台账是文件（`DOC-SIGNATURES.jsonl`），不进 `schema.TABLES`（`draft/29` §8.8.7）。
    # 三态纪律在这块的具体形态：账"读不出来"（坏行/断链）与"没有这条签名"是两件事，
    # 前者报 `signature_ledger_corrupt`，后者报 `accepted_without_signature`。
    sig_root = Path(getattr(store, "root", "."))
    sig_records, sig_bad_lines = SIG.read_ledger(SIG.ledger_path(sig_root))
    for bad in sig_bad_lines:
        rep.issues.append(Issue("error", "documents", None, SIG.CODE_LEDGER_CORRUPT,
                                f"签名台账读不出来：{bad}"))
    for broken in SIG.chain_problems(sig_records):
        rep.issues.append(Issue("error", "documents", None, SIG.CODE_LEDGER_CORRUPT,
                                f"签名台账链断了：{broken}"))
    sig_checked = 0
    #: 签名判据只对 `SIG.SIGNABLE_STATUSES` 的稿件成立 ⇒ "查了几行"数的就是**这些**行。
    #: 不写死 `"accepted"`：那个字面量的唯一落点现在是 `signatures.SIGNABLE_STATUSES`
    #: （两处各写一份就会分叉 —— 而分叉的症状是读数说"查了 N 行"而判据一行没查）。
    #: E-07（`draft/52` D5）之后它是**元组**（`accepted` + `revised`）：`revised` 那份
    #: 稿子的签名钉着改之前那一版，正是最该被看见的形态。
    sig_rows_checked = 0
    missing_statuses = [s for s in SIG.SIGNABLE_STATUSES if s not in S.DOC_STATUSES]
    if missing_statuses:
        # 词表分叉的**当场上报**：否则 `SIGNABLE_STATUSES` 一旦拼错，签名判据会一份稿件
        # 都不查，而 `checked` 里那个 0 看起来与"全部干净"逐字一样（P16 族的真空通过）。
        rep.issues.append(Issue(
            "error", "documents", None, "signable_status_not_in_doc_statuses",
            f"`signatures.SIGNABLE_STATUSES={SIG.SIGNABLE_STATUSES!r}` 里的 "
            f"{missing_statuses} 不在 `schema.DOC_STATUSES` "
            f"{S.DOC_STATUSES} ⇒ 签名判据会**一份稿件都不查**，而读数看起来是「零问题」。"
            "两处词表分叉必须当场吵，不许静默零查。",
        ))
    for d in documents:
        if str(d.get("status") or "") in SIG.SIGNABLE_STATUSES:
            sig_rows_checked += 1
        for code, msg in SIG.signature_problems(sig_root, d, sig_records):
            rep.issues.append(Issue("error", "documents", d.get("doc_id"), code, msg))
            sig_checked += 1
    # ---- `R-38`（`draft/28` §150.5）：这一格的**名字**必须说实话
    #
    # 原来叫 `checked["signatures"]`，值却是"**签名问题的条数**"（`sig_checked` 只在
    # 发现问题时 `+= 1`），而同一个 `checked` 字典里相邻的计数全是"查了几行" ——
    # 同一个字典两种语义 ⇒ `0` 会被读成"没有稿件查过签名"（真相恰好相反：
    # 0 是"查过、干净"）。现在拆成两个各自说清自己的键：
    #   - `signature_problems`：问题条数（0 = 干净）；
    #   - `accepted_documents_checked`：签名判据真正看过的行数（0 = **没查**，不是干净）。
    # 旧键**删掉**而不是留别名：留一个名字错的别名，`checked.get("signatures", 0)` 的
    # 读者照样会读错；删掉会让它当场 `KeyError` —— 吵，但不静默。
    rep.checked["signature_problems"] = sig_checked
    rep.checked["accepted_documents_checked"] = sig_rows_checked

    # ---- 猜想：它引用的东西必须真的存在（依据 `draft/30` §T1 第 7 处触点）
    #
    # schema 管一行内可判的条件（`Conjecture.validate`：proposed 要有 testable、
    # refuted 要有反例实验……）；这一层管跨对象的那半边：那些代号指的东西在不在。
    # 分工的理由：schema 不该去查别的表（它没有 store），而 verify 查得到。
    exp_by_id = {str(r.get("experiment_id")): r for r in store.rows("experiments")}
    doc_by_id = {str(r.get("doc_id")): r for r in store.rows("documents")}
    #: 已闭合依赖的证据侧实验号（`draft/30` §T2 ② 的第二跳要用）。算一次，不在循环里重扫。
    closed_dep_exps = {str(d.get("source_experiment_id") or "")
                       for d in store.rows("dependencies")
                       if str(d.get("status")) == "closed"
                       and str(d.get("source_experiment_id") or "")}

    return closed_dep_exps, doc_by_id, exp_by_id




def _check_12(rep, closed_dep_exps, doc_by_id, exp_by_id, lit_by_id, store):
    """`verify_all` 的第 12 段（行 1204–1317）。

    由 `temp/_t5_split.py` 逐字搬移而来：判据一条没改，只是换了个位置。
    入参 / 出参见该脚本的 dry-run 输出；出参是为了保持原来 for 循环变量的
    泄漏语义（后面的段确实读到了它们）。
    """
    for c in store.rows("conjectures"):
        cid = str(c.get("conjecture_id"))
        refs = [str(x) for x in (c.get("experiment_ids") or []) if x]
        for key in ("proof_experiment_id", "counterexample_experiment_id"):
            val = str(c.get(key) or "")
            if val:
                refs.append(val)
        for eid in refs:
            if eid not in exp_by_id:
                rep.issues.append(Issue("error", "conjectures", cid, "dangling_experiment",
                                        f"猜想引用的实验 {eid!r} 不存在"))
        lit = str(c.get("known_lit_id") or "")
        if lit and lit not in lit_by_id:
            rep.issues.append(Issue("error", "conjectures", cid, "dangling_lit",
                                    f"known_in_literature 指的文献 {lit!r} 不存在"))
        if str(c.get("status")) == "promoted":
            target = c.get("promoted_to") or {}
            want = str(target.get("id") or "")
            doc_id, _, claim_id = want.partition("#")
            doc = doc_by_id.get(doc_id)
            if doc is None:
                rep.issues.append(Issue("error", "conjectures", cid, "promotion_target_missing",
                                        f"promoted_to 指的稿件 {doc_id!r} 不存在（升格落空）"))
            elif claim_id:
                claim_ids = {str(cl.get("claim_id")) for cl in (doc.get("claims") or [])
                             if isinstance(cl, dict)}
                if claim_id not in claim_ids:
                    rep.issues.append(Issue("error", "conjectures", cid, "promotion_target_missing",
                                            f"promoted_to 指的断言 {claim_id!r} 不在稿件 "
                                            f"{doc_id!r} 里（升格落空）"))

        # ---- T2：状态配不配**它自己举出的**证据（依据 `draft/30` §T2）
        #
        # 三态纪律在这里的形态：状态是**结论**、不是**声明**。T1 判"代号在不在"，
        # 这一段判"这个结论有没有它自称的那件证据撑着"。
        # 缺行的情况（`eid not in exp_by_id`）由上面的 `dangling_experiment` 报，这里不重复报。
        status = str(c.get("status") or "")
        exp_ids = [str(x) for x in (c.get("experiment_ids") or []) if x]
        listed = [exp_by_id[e] for e in exp_ids if e in exp_by_id]

        proof_id = str(c.get("proof_experiment_id") or "")
        proof = exp_by_id.get(proof_id) if proof_id else None
        if status == "proved":
            # FC-22 同族：计算类永远拿不到 proof（method 必须是 formal 且 evidence_kind 是 proof，
            # 而且 verifier_output 非空 —— 空输出等于没跑过检查器）。
            why: list[str] = []
            if not proof_id:
                why.append("没有 proof_experiment_id（proved 必须挂一个形式化实验）")
            elif proof is None:
                pass  # 行不存在 ⇒ 上面的 `dangling_experiment` 已报，这里不重复
            else:
                if str(proof.get("method")) != "formal":
                    why.append(f"method={proof.get('method')!r}（应 formal）")
                if str(proof.get("evidence_kind")) != "proof":
                    why.append(f"evidence_kind={proof.get('evidence_kind')!r}（应 proof）")
                if not str(proof.get("verifier_output") or "").strip():
                    why.append("verifier_output 为空（没跑过检查器）")
            if why:
                rep.issues.append(Issue(
                    "error", "conjectures", cid, "proved_without_formal_proof",
                    f"status=proved 但证明不成立：{'；'.join(why)}"))

        if status == "promoted":
            target = c.get("promoted_to") or {}
            want = str(target.get("id") or "")
            doc_id, _, claim_id = want.partition("#")
            doc = doc_by_id.get(doc_id)
            claim = None
            if doc is not None and claim_id:
                claim = next((cl for cl in (doc.get("claims") or [])
                              if isinstance(cl, dict) and str(cl.get("claim_id")) == claim_id), None)
            # 第一跳（猜想→断言）不成立时由上面的 `promotion_target_missing` 报，这里只查第二跳。
            if claim is not None:
                cites = [str(x) for x in (claim.get("citations") or [])]
                bad2: list[str] = []
                if not proof_id:
                    bad2.append("猜想没有 proof_experiment_id")
                if str(claim.get("evidence_kind")) != "proof":
                    bad2.append(f"升格断言的 evidence_kind={claim.get('evidence_kind')!r}（应 proof）")
                if proof_id and f"exp:{proof_id}" not in cites:
                    bad2.append(f"升格断言的 citations 里没有 {'exp:' + proof_id!r}")
                if proof_id and proof_id not in closed_dep_exps:
                    bad2.append(f"没有 status=closed 且 source_experiment_id={proof_id!r} 的依赖")
                if bad2:
                    rep.issues.append(Issue(
                        "error", "conjectures", cid, "promoted_without_closed_dep",
                        f"status=promoted 但升格链断在第二跳：{'；'.join(bad2)}"))

        if status == "refuted":
            ce_id = str(c.get("counterexample_experiment_id") or "")
            ce = exp_by_id.get(ce_id) if ce_id else None
            if not ce_id:
                rep.issues.append(Issue(
                    "error", "conjectures", cid, "refuted_without_counterexample",
                    "status=refuted 却没有任何 counterexample_experiment_id（被否证必须有反例）"))
            elif ce is not None and str(ce.get("result")) != "refutes":
                rep.issues.append(Issue(
                    "error", "conjectures", cid, "refuted_without_counterexample",
                    f"status=refuted 但反例实验 {ce_id!r} 的 result={ce.get('result')!r}"
                    "（inconclusive 不得转 refuted：没查成 ≠ 查过了、被否证）"))

        if status == "supported_not_proved" and not any(
                str(r.get("result")) == "supports" for r in listed):
            rep.issues.append(Issue(
                "error", "conjectures", cid, "supported_without_support",
                f"status=supported_not_proved 但 experiment_ids={exp_ids!r} 里没有 result='supports' 的实验"))

        if status in ("proved", "promoted", "supported_not_proved"):
            refuters = sorted(e for e in exp_ids
                              if e in exp_by_id and str(exp_by_id[e].get("result")) == "refutes")
            if refuters:
                rep.issues.append(Issue(
                    "error", "conjectures", cid, "status_conflicts_with_experiment",
                    f"status={status!r} 自称成功，而 experiment_ids 里的 {refuters!r} 的 result='refutes'"))


def _check_13(rep, store) -> None:
    """`verify_all` 的第 13 段：命题台账（`statements`）的不变量（`draft/37` §16 P1）。

    这一段的四条判据，各守一种**已经在真机上出现过**的病：

    1. **出处必须存在**（`dangling_lit_ref` / `dangling_doc_ref`）：一条"从文献里摘的"
       命题指着一篇不存在的文献 —— 逐字回验就没有第二份文本，而报告照样印。
       这与 `dangling_dep` 同族，只是发生在命题级。
    2. **`derived_from` 引用完整性**（`dangling_stmt_ref`）：承重链上少一环，
       "这条结论靠什么站着"就答不出来（`draft/37` §4 的依赖图读数就是被这种缺口污染的）。
    3. **`proof` 级命题不许压在不可用的命题上**（`proof_stmt_on_unusable_stmt`）：
       这是 §8/§9 的矛盾闭环在**命题级**的落点，与依赖级的
       `proof_claim_on_refuted_dependency` 成对。`refuted` / `superseded` 报 error
       （结论必须撤或降档），`disputed` 报 warning（等裁决）。
    4. **`active` 的文献命题却没逐字回验**（`active_stmt_quote_unverified`，warning）：
       "B 的唯一自动幻觉防线"就是逐字回验（见 `quoteverify` 的 docstring）。
       它降为 warning 而不是 error，理由与 `external_unavailable` 那条一致：
       这是**已知未做**、不是谎报；但它在报告里必须看得见。
    """
    statements = store.rows("statements")
    stmt_by_id = {str(s.get("stmt_id")): s for s in statements}
    lit_ids = {str(x.get("lit_id")) for x in store.rows("literature")}
    doc_ids = {str(x.get("doc_id")) for x in store.rows("documents")}

    usable = 0
    for s in statements:
        sid = str(s.get("stmt_id") or "")
        lid = str(s.get("source_lit_id") or "")
        if lid and lid not in lit_ids:
            rep.issues.append(Issue(
                "error", "statements", sid, "dangling_lit_ref",
                f"命题的 source_lit_id={lid} 不在文献表里 ⇒ 逐字回验没有可比对的文本，"
                "而这条命题照样会被下游当成依据",
            ))
        docid = str(s.get("doc_id") or "")
        if docid and docid not in doc_ids:
            rep.issues.append(Issue(
                "error", "statements", sid, "dangling_doc_ref",
                f"命题的 doc_id={docid} 不在稿件表里（自产结果落在哪份稿子上说不清）",
            ))
        for dep in s.get("derived_from") or []:
            if str(dep) not in stmt_by_id:
                rep.issues.append(Issue(
                    "error", "statements", sid, "dangling_stmt_ref",
                    f"derived_from 里的 {str(dep)!r} 不是一条存在的命题 ⇒ "
                    "承重链上少了一环，'这条结论靠什么站着'就答不出来",
                ))
        if str(s.get("evidence_kind") or "") == "proof":
            for dep in s.get("derived_from") or []:
                row = stmt_by_id.get(str(dep))
                if row is None:
                    continue  # 上面已按 dangling_stmt_ref 报过，这里不重复
                dst = str(row.get("status") or "")
                if dst not in S.STATEMENT_UNUSABLE_STATUSES:
                    continue
                level = "warning" if dst == "disputed" else "error"
                rep.issues.append(Issue(
                    level, "statements", sid, "proof_stmt_on_unusable_stmt",
                    f"命题 {sid} 声称 evidence_kind='proof'，却建立在 {str(dep)} 上，"
                    f"而它的 status={dst!r}（不可用作依据）⇒ "
                    "要么把这条命题降为 cross_check，要么先解决被引用的那一条"
                    "（§8/§9：矛盾与错文献都要落到'压在它上面的结论怎么办'）",
                ))
        if (str(s.get("status") or "") == "active"
                and str(s.get("origin") or "") == "external_lit"
                and s.get("quote_verified") is not True):
            rep.issues.append(Issue(
                "warning", "statements", sid, "active_stmt_quote_unverified",
                f"命题 {sid} 是 active 的文献命题，但 quote_verified={s.get('quote_verified')!r}"
                f"（{str(s.get('quote_reason') or '没说为什么')[:120]}）⇒ "
                "逐字回验是 B 那条路上唯一的自动幻觉防线；没做就要在报告里标明",
            ))
        if str(s.get("status") or "") == "active":
            usable += 1
    rep.checked["statements_usable"] = usable


def verify_all(
    store: Store,
    *,
    deep: bool = False,
    extract_text: Any = None,
    quote_widen: int = 1,
    allow_fulltext_quote_fallback: bool = False,
) -> VerifyReport:
    """校验全局不变量。

    `quote_widen` / `allow_fulltext_quote_fallback` **必须与 agent_b 用的一致**，
    否则 `--deep` 会按一套比写入时更严的规则重算，把"写入时合规"的引文报成
    `quote_not_found` —— 那是**假报警**，比不校验更糟，因为它会训练人忽略告警。
    调用方（CLI）负责从同一份配置里取这两个值。
    """
    rep = VerifyReport(deep=deep)

    con_by_id, concepts, lit_by_id, literature, rel_by_id, relations, requests = _check_1(rep, store)
    _check_2(rep, lit_by_id, literature, requests, store)
    _check_3(rep, con_by_id, lit_by_id, rel_by_id, relations)
    questions, req_ids = _check_4(rep, con_by_id, concepts, lit_by_id, rel_by_id, relations, requests, store)
    dependencies, doc_by_id, documents, eval_by_id, exp_by_id, experiments, findings = _check_5(rep, lit_by_id, questions, store)
    _check_6(rep, dependencies, documents, exp_by_id, experiments)
    # `E1/R-03`（方案 A）：`stmt:` 与其余几档同权 ⇒ 这里也要把命题表交给第 7 段，
    # 否则 `elif kind == "stmt"` 那条分支拿到的是未定义的名字（导入期不会红、运行期才炸）。
    stmt_by_id = {str(r.get("stmt_id")): r for r in store.rows("statements")}
    rejected_by_id = _check_7(rep, dependencies, doc_by_id, documents, eval_by_id, exp_by_id, lit_by_id, rel_by_id, relations,
                              stmt_by_id)
    _check_8(rep, doc_by_id, findings, questions, rejected_by_id, store)
    _check_9(rep, documents, questions, req_ids, store)
    _check_10(rep, allow_fulltext_quote_fallback, deep, extract_text, lit_by_id, quote_widen, relations, store)
    closed_dep_exps, doc_by_id, exp_by_id = _check_11(rep, documents, store)
    _check_12(rep, closed_dep_exps, doc_by_id, exp_by_id, lit_by_id, store)
    _check_13(rep, store)
    return rep
