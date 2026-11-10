# -*- coding: utf-8 -*-
"""命题台账的索引：代码侧一次建好（本次唤醒缓存一次），不进上下文、只读。

## 它是什么、不是什么（业主 2026-11-10 的口径，逐字见 `draft/181`）

业主逐字：「C 的建树不是全建，是选定一个节点（一个命题或概念，按需求主动查找现选）后
上下按某层数（它自行决定）展开其父（依赖谁）和子(谁在引用它)，建立局部树，且可按需拼接
扩张。一次建成是代码侧帮它把数据收集整理好，查是按需读取按需展开树的信息进入它的上下文」。

所以这里的"一次建成"不是全图，是索引：

- 节点表：`stmt_id → {kind, status, grade, label, statement_full, proof_no}`；
- 正邻接（依赖面）：`source_stmt_id → [(used_by, 依赖行读数)]`；
- 反邻接（被引面）：`used_by → [(source_stmt_id, 依赖行读数)]`；
- 外部根（`doc:` / `relation:` / `experiment:` 那一族，以及 `source_lit_id` /
  `source_experiment_id` / `source_doc_id` 三种来源）不建节点，只作为边的读数。

它不写盘、不开事务、不发模型调用：`from_store` 只经 `statementledger.rows_of` 读两张表
（`statements` / `dependencies`），之后全部是内存读。要事务内的快照时把 `tx` 当 `store`
传进来即可（同一个 `rows(table)` 协议），读数里 `source` 记的是哪一种。

## 为什么树在代码侧算、而"读进上下文"是 C 自己按需触发的

上下文成本由 C 的展开决定，而不是由台账规模决定。索引住在进程内存里（一个持有者对象，
支持外部传入已建好的索引），一次唤醒内只建一次；`ledger.expand` 只把这一次要的那棵
局部树交回，其余一律不出内存。`ledger.resolve` 只交候选节点（五格），不交树。

## 概念平权（业主 2026-11-10 追加口径，逐字）

「概念只是命题台账里的一个标签，处理方式和命题平权」⇒ 概念行就是 `statements` 里
`kind=concept` 的那一行，就是普通节点：同一套 `resolve` / `expand` / 同一组字段。
本模块不读 `relations` 表、不借概念图、不为概念开任何特例分支。若某个概念节点今天
没有入边 / 出边（因为命题不引概念），就如实给空并说明原因 ——「台账里没有命题依赖它」
不等于「它没有关系」。

## 依赖面：全路径 + 按证明路径分组（业主 2026-11-10 追加口径）

每个被查到的节点的 `dependency_face` 是全路径（一路向上到根），并按
`(证明号, path_group)` 分组：同一条证明里的依赖一组，`#p2` 那份另起一组。
组内保留"引在哪一步"（`used_at`：依赖行自带的 `label` / `quote`，见 `_edge_reading`）
与到根的链；某一组走不到根 ⇒ `status="broken"` + `break_at` 指出断在哪，
不许悄悄少给几层。根有三种：文献 / 实验 / 本仓另一份稿（`source_` 三种来源），
以及"没有依赖边"的命题（无前提自证定理）或概念（原始概念）。

## 有界（照 `graph_tools.PathSearchResult` 的老形态）

深度 / 节点数 / 字符数三样都有上限；触界时 `truncated=True` 并给 `reasons`，
`budget_used` 逐格记用了多少。依赖面另有自己的两道安全界（`MAX_FACE_DEPTH` /
`MAX_FACE_CHAINS`），触界同样如实标在那一组上。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import evidencebits as EB
from . import proofloc as PL
from . import schema as S
from . import statementledger as SL
from . import verifications as VR

#: `expand` 的深度上限（层数由 C 决定，但必须有顶：再深就该换根 / 拼接，而不是一次拉穿）。
MAX_DEPTH = 6
#: 一次 `expand` 最多交回多少个节点（含选定节点本身）。
MAX_NODES = 120
#: 一次 `expand` 最多交回多少字符（按节点读数的 JSON 长度现算）。
MAX_CHARS = 40_000
#: 依赖面向上走的安全深度（防环、防异常深的台账把一次调用拖死）。
MAX_FACE_DEPTH = 64
#: 每条依赖路径组最多列几条到根的链（组内分支多时按确定顺序截断并标 truncated）。
MAX_FACE_CHAINS = 12

#: 展开方向（`both` = 父与子都展开，业主写的默认）。
DIRECTIONS: tuple[str, ...] = ("up", "down", "both")

#: 依赖行的 `used_by` 里不是命题的那几族（外部根读数：不建节点）。
EXTERNAL_CITER_PREFIXES: tuple[str, ...] = (
    "doc:", "relation:", "experiment:", "lit:", "exp:", "mss:")

#: 依赖行四选一来源里"就是根"的那三种 ⇒ 根的种类（业主：根 = 文献 / 无前提自证定理 / 原始概念，
#: 另加实验与本仓另一份稿：它们是依赖账里的合法终点，不能读成断链）。
SOURCE_ROOT_KINDS: tuple[tuple[str, str], ...] = (
    ("source_lit_id", "literature"),
    ("source_experiment_id", "experiment"),
    ("source_doc_id", "document"),
)

#: `proof_no` 缺省（老行不带尾巴 ⇒ 第 1 条证明）。与 `proofloc.DEFAULT_PROOF_NO` 同值，
#: 这里不另立一份口径：直接用 `PL.DEFAULT_PROOF_NO`，只在本模块里留一个可读别名。
DEFAULT_PROOF_NO = PL.DEFAULT_PROOF_NO


class LedgerIndexError(RuntimeError):
    """台账读不出来（不是"表里没有"）：索引建不成，调用方据此 fail-closed。"""


# ---------------------------------------------------------------- 行 → 读数


def _grade_of(row: Mapping[str, Any]) -> str:
    """一条台账行的等级：五元位现算（概念行 ⇒ `not_applicable`，如实给）。"""
    return EB.derive_grade(dict(row.get("bits") or {}), kind=str(row.get("kind") or ""))


def _source_root(row: Mapping[str, Any]) -> dict[str, Any]:
    """依赖行的"被依赖的那一端"是不是一个根（是 ⇒ 给根读数；不是 ⇒ 空 dict）。

    四选一里只有 `source_stmt_id` 不是根（还要继续向上走）；另外三种都是终点。
    四格全空 = 这条依赖没有闭合（`dangling` / `external_unavailable`）⇒ 空 dict，
    由调用方按断链处理（那正是"走不到根"那一档）。
    """
    for field, kind in SOURCE_ROOT_KINDS:
        value = str(row.get(field) or "").strip()
        if value:
            return {"kind": kind, "id": value, "field": field,
                    "label": str(row.get("label") or "")}
    return {}


def _edge_reading(row: Mapping[str, Any]) -> dict[str, Any]:
    """一条依赖行 ⇒ 一个边的读数（键恒定，缺的格给空值）。

    ## "用在哪一步"是哪一格（如实说明，不猜）

    `dependencies` 表没有独立的步号列：B 从手稿依赖段录入时，那一步的原文落在
    `quote`（引用），人话标签落在 `label`（"由引理 2" / "路径 1 第一步"）。
    所以这一格叫 `used_at`，取 `label` 原文；`quote` 另给一格原文。
    两者都空 ⇒ `used_at=""`，并置 `used_at_known=False` —— 不凭空编号
    （编一个"第 1 步"比留空更坏：读的人会当成台账里真有这一格）。
    """
    used_by = str(row.get("used_by") or "")
    head, proof_no, problem = PL.parse_used_by_checked(used_by)
    citer_kind = head.split(":", 1)[0].strip() if ":" in head else ""
    #: 引用方命题号：只有干净尾巴的 `stmt:` 那一类才有（`doc:` / `relation:` /
    #: `experiment:` 是外部根，留空串 —— 不许把 `doc:0001` 的 `0001` 冒充成命题）。
    citer_stmt_id = (head.split(":", 1)[-1].strip()
                     if (citer_kind == "stmt" and not problem) else "")
    label = str(row.get("label") or "")
    quote = str(row.get("quote") or "")
    return {
        "dep_id": str(row.get("dep_id") or ""),
        "used_by": used_by,
        "used_by_head": head,
        "used_by_problem": problem,
        "citer_kind": citer_kind,
        "citer_stmt_id": citer_stmt_id,
        "external_citer": bool(citer_kind and citer_kind + ":" in EXTERNAL_CITER_PREFIXES),
        "path_no": int(proof_no),
        "path_group": int(row.get("path_group") or 1),
        "kind": str(row.get("kind") or ""),
        "label": label,
        "quote": quote,
        #: 见函数 docstring：这不是新抄一份真相，而是把台账里那两格原文摆到"用在哪一步"这一格上。
        "used_at": label or quote,
        "used_at_known": bool(label or quote),
        "status": str(row.get("status") or ""),
        "status_reason": str(row.get("status_reason") or ""),
        "source_stmt_id": str(row.get("source_stmt_id") or ""),
        "source_root": _source_root(row),
        "created_at": str(row.get("created_at") or ""),
    }


def _group_label(key: tuple[int, int]) -> str:
    """`(证明号, path_group)` ⇒ 人读的组名（`#p1` / `#p2·g3`）。"""
    proof_no, path_group = key
    tail = f"#p{proof_no}"
    return tail if int(path_group) <= 1 else f"{tail}·g{path_group}"


def _edge_sort_key(edge: Mapping[str, Any]) -> tuple:
    return (int(edge["path_no"]), int(edge["path_group"]),
            str(edge["used_by"]), str(edge["dep_id"]))


# ---------------------------------------------------------------- 索引


class LedgerIndex:
    """命题台账的只读索引（节点表 + 双向邻接 + 外部根读数）。

    构造只走 `from_store` / `from_rows`，两者都是纯读。实例建好之后所有读法都是内存读
    （`node` / `up_edges` / `down_edges` / `resolve` / `expand`）。
    """

    def __init__(self, *, nodes: dict[str, dict], rows: list[dict],
                 by_source: dict[str, list[dict]], by_user: dict[str, list[dict]],
                 statement_rows_total: int = 0, dependency_rows_total: int = 0,
                 root: str = "", source: str = "") -> None:
        self.nodes: dict[str, dict] = nodes
        #: 台账行副本（`resolve` 的关键字那条口径要交给 `statementledger` 用同一把尺）。
        self.rows: list[dict] = rows
        #: 正邻接：`source_stmt_id`（被依赖方）→ 以它为被依赖方的依赖边（谁在引用它）。
        self.by_source: dict[str, list[dict]] = by_source
        #: 反邻接：`used_by` 的头部（引用方）→ 它依赖的边（它依赖谁）。
        self.by_user: dict[str, list[dict]] = by_user
        self.statement_rows_total = int(statement_rows_total)
        self.dependency_rows_total = int(dependency_rows_total)
        self.root = str(root)
        self.source = str(source)

    # ------------------------------------------------------------ 建索引

    @classmethod
    def from_store(cls, store: Any) -> "LedgerIndex":
        """从 store（或事务里的 tx）读两张表 ⇒ 索引（只读、一次）。

        读不出来 ⇒ `LedgerIndexError`（"没查成"不是"台账里没有"：
        建索引这一层不许把 I/O 故障折成一张空索引 —— 那会让 C 读到"没有这个号"）。
        """
        statement_rows, problem, _error = SL.rows_of(store)
        if problem:
            raise LedgerIndexError(problem)
        dependency_rows, problem, _error = SL.rows_of(
            store, table=SL.TABLE_DEPENDENCIES)
        if problem:
            raise LedgerIndexError(problem)
        return cls.from_rows(
            statement_rows, dependency_rows,
            root=str(getattr(store, "root", "") or ""),
            source=type(store).__name__,
        )

    @classmethod
    def from_rows(cls, statement_rows: Iterable[Mapping[str, Any]] | None,
                  dependency_rows: Iterable[Mapping[str, Any]] | None, *,
                  root: str = "", source: str = "") -> "LedgerIndex":
        """从已读出来的两批行建索引（事务快照 / 测试夹具走这一条）。"""
        rows = [dict(r) for r in (statement_rows or ()) if isinstance(r, Mapping)]
        nodes: dict[str, dict] = {}
        for row in rows:
            sid = str(row.get("stmt_id") or "").strip()
            if not sid:
                continue
            kind = str(row.get("kind") or "")
            proof_nos = [int(no) for no, _text in VR.proof_list(dict(row))]
            nodes[sid] = {
                "stmt_id": sid,
                "kind": kind,
                "status": str(row.get("status") or ""),
                "grade": _grade_of(row),
                "label": str(row.get("label") or ""),
                "statement_full": str(row.get("statement_full") or ""),
                #: 这条命题现在挂着的证明号（`#p1` 恒在；多证明时升序）。
                "proof_no": int(proof_nos[0]) if proof_nos else DEFAULT_PROOF_NO,
                "proof_nos": proof_nos,
            }
        by_source: dict[str, list[dict]] = {}
        by_user: dict[str, list[dict]] = {}
        deps_total = 0
        for row in (dict(r) for r in (dependency_rows or ()) if isinstance(r, Mapping)):
            deps_total += 1
            edge = _edge_reading(row)
            if edge["source_stmt_id"]:
                by_source.setdefault(edge["source_stmt_id"], []).append(edge)
            if edge["citer_stmt_id"]:
                by_user.setdefault(edge["citer_stmt_id"], []).append(edge)
        for bucket in (by_source, by_user):
            for _key, edges in bucket.items():
                edges.sort(key=_edge_sort_key)
        return cls(nodes=nodes, rows=rows, by_source=by_source, by_user=by_user,
                   statement_rows_total=len(rows), dependency_rows_total=deps_total,
                   root=str(root or ""), source=str(source or ""))

    # ------------------------------------------------------------ 读数（索引层）

    def summary(self) -> dict[str, Any]:
        """索引规模（诊断用；不是给 C 看的全图）。"""
        return {
            "root": self.root,
            "node_count": len(self.nodes),
            "statement_rows": self.statement_rows_total,
            "dependency_rows": self.dependency_rows_total,
            "sourced_edges": sum(len(v) for v in self.by_source.values()),
            "cited_edges": sum(len(v) for v in self.by_user.values()),
            "external_citers": sum(
                1 for edges in self.by_source.values() for e in edges
                if e["external_citer"]),
        }

    def normalize_stmt_id(self, value: Any) -> str:
        """把一个"号"（`stmt:000123` / `000123` / `123`）归一成台账里的号。

        只做两件事：去掉 `stmt:` / `concept:` 前缀与首尾引号，然后先按原文找；
        找不到且是十进制数字时补零到 `schema.ID_DIGITS` 位再找一次（旧数据里的
        4 位号与"少写前导零"是同一条命题）。不做任何 `kind` 过滤 —— 概念平权。
        """
        text = str(value or "").strip().strip("`'\"“”《》").strip()
        for prefix in ("stmt:", "concept:"):
            if text.lower().startswith(prefix):
                text = text[len(prefix):].strip()
                break
        if text in self.nodes:
            return text
        if text.isdigit():
            padded = text.zfill(int(S.ID_DIGITS))
            if padded in self.nodes:
                return padded
        return text

    def node(self, stmt_id: Any) -> dict | None:
        """按号取节点读数（没有 ⇒ None）。"""
        return self.nodes.get(self.normalize_stmt_id(stmt_id))

    def up_edges(self, stmt_id: Any) -> list[dict]:
        """它依赖谁（依赖面）：以它为引用方的那些依赖边（升序）。"""
        return list(self.by_user.get(self.normalize_stmt_id(stmt_id), ()))

    def down_edges(self, stmt_id: Any) -> list[dict]:
        """谁引用它（被引面）：以它为被依赖方的那些依赖边（升序）。"""
        return list(self.by_source.get(self.normalize_stmt_id(stmt_id), ()))

    # ------------------------------------------------------------ resolve

    def resolve(self, query: Any) -> dict[str, Any]:
        """把一次"选根"查询 ⇒ 候选节点列表（不是树）。

        三条口径（业主 2026-11-10 的 4.1）：

        - 按号：`stmt:000123` / `000123` / `123`（概念号同形 —— 概念就是台账里的一行）；
        - 按标签 / 关键字：走既有检索口径 `statementledger.by_keywords`
          （`label` / `statement_full` 经 `textutil.normalize` 包含任一关键词），
          不另写一套；
        - 找不到 ⇒ 明白说"没有这个号 / 没有命中"，不返回空列表了事。

        返回的每条候选只有五格：`stmt_id` / `kind` / `status` / `grade` / `label`。
        不含证明正文（也不含 `statement_full`：选根这一趟不需要命题全文）。
        """
        raw = str(query or "").strip().strip("`'\"“”《》").strip()
        out: dict[str, Any] = {
            "query": raw, "checked": False, "mode": "", "found": None,
            "hits_total": 0, "scanned": 0, "candidates": [],
            "why": "", "reason": "",
        }
        if not raw:
            why = ("没给要查的东西 ⇒ 这一问不成立（不是「台账里没有这个号」）："
                   "给命题号（`stmt:000123` / `000123`）或标签 / 关键字")
            out.update(why=why, reason=why)
            return out
        body = raw
        for prefix in ("stmt:", "concept:"):
            if body.lower().startswith(prefix):
                body = body[len(prefix):].strip()
                break
        if body.isdigit():
            got = SL.by_id(rows=self.rows, stmt_id=body)
            out.update(mode=SL.MODE_ID, scanned=int(got["scanned"]),
                       checked=bool(got["checked"]))
            if not got["checked"]:
                out.update(why=str(got["why"]), reason=str(got["reason"]))
                return out
            if got["found"]:
                candidates = [self._candidate(got["row"])]
                out.update(found=True, hits_total=1, candidates=candidates,
                           why=f"按号命中 stmt:{got['row'].get('stmt_id')}（主键逐字相等）")
                return out
            # 4 位旧号 / 少写前导零：同一套"按号"口径的补零读法（不猜种类）。
            padded = body.zfill(int(S.ID_DIGITS))
            if padded != body:
                again = SL.by_id(rows=self.rows, stmt_id=padded)
                if again["checked"] and again["found"]:
                    out.update(found=True, hits_total=1,
                               candidates=[self._candidate(again["row"])],
                               why=(f"按号命中 stmt:{again['row'].get('stmt_id')}"
                                    f"（把 {body} 补零成 {padded} 后命中）"))
                    return out
            out.update(found=False, hits_total=0, candidates=[],
                       why=(f"台账里没有编号 {body} 这一行"
                            f"（在 {out['scanned']} 行里按主键逐字比过；"
                            "这是确定性事实，不是「可能漏了」）"))
            return out
        got_kw = SL.by_keywords(rows=self.rows, keywords=[raw], text_chars=0)
        out.update(mode=SL.MODE_KEYWORDS, scanned=int(got_kw["scanned"]),
                   checked=bool(got_kw["checked"]))
        if not got_kw["checked"]:
            out.update(why=str(got_kw["why"]), reason=str(got_kw["reason"]))
            return out
        candidates = [self._candidate(hit["row"]) for hit in got_kw["hits"]
                      if isinstance(hit.get("row"), Mapping)]
        out.update(found=bool(candidates), hits_total=len(candidates),
                   candidates=candidates,
                   why=(f"按标签 / 关键字「{raw}」命中 {len(candidates)} 条"
                        if candidates else
                        f"按标签 / 关键字「{raw}」命中 0 条（那是「这批词没命中」，"
                        "不是「台账里没有」—— 换一个词或按号查）"))
        return out

    @staticmethod
    def _candidate(row: Mapping[str, Any]) -> dict[str, Any]:
        """一条候选（五格；不含证明正文）。"""
        return {
            "stmt_id": str(row.get("stmt_id") or ""),
            "kind": str(row.get("kind") or ""),
            "status": str(row.get("status") or ""),
            "grade": _grade_of(row),
            "label": str(row.get("label") or ""),
        }

    # ------------------------------------------------------------ 依赖面（全路径 + 分组）

    def dependency_face(self, stmt_id: Any, *,
                        max_chains: int = MAX_FACE_CHAINS,
                        max_depth: int = MAX_FACE_DEPTH) -> dict[str, Any]:
        """一条命题的依赖面：向上到根的全路径，按 `(证明号, path_group)` 分组。

        组内每条链回答三件事：路上经过哪几条命题（`chain`）、每一跳引在哪一步
        （`steps[i].used_at`）、终点是不是根（`root`）；走不到根 ⇒ `status="broken"`
        + `break_at`（断在哪条边、为什么）。不许静默少给几层。
        """
        sid = self.normalize_stmt_id(stmt_id)
        out: dict[str, Any] = {
            "checked": True, "groups": [], "root_kind": "", "root": {},
            "truncated": False, "reasons": [], "why": "",
        }
        node = self.nodes.get(sid)
        if node is None:
            out.update(checked=False,
                       why="台账里没有这一条 ⇒ 依赖面没查成（不是「它没有依赖」）")
            return out
        edges = self.up_edges(sid)
        if not edges:
            is_concept = str(node.get("kind") or "") == "concept"
            root_kind = "primitive_concept" if is_concept else "no_premise"
            out.update(root_kind=root_kind,
                       root={"kind": root_kind, "id": f"stmt:{sid}",
                             "label": node.get("label", "")},
                       why=("台账里没有一条依赖边指向它（概念行）⇒ 按原始概念读；"
                            "「没有边」不等于「它没有关系」—— 命题不引概念时这一面就是空的。"
                            if is_concept else
                            "台账里没有一条依赖边指向它 ⇒ 按无前提（自足）读；"
                            "但「没有依赖边」不等于「证明没用别人」—— 依赖面是录入时写下的。"))
            return out
        grouped: dict[tuple[int, int], list[dict]] = {}
        for edge in edges:
            grouped.setdefault((int(edge["path_no"]), int(edge["path_group"])),
                               []).append(edge)
        for key in sorted(grouped):
            group = {
                "group": _group_label(key), "proof_no": key[0], "path_group": key[1],
                "edges": [self._edge_view(e) for e in grouped[key]],
                "chains": [], "broken": False, "truncated": False, "reasons": [],
                "why": "",
            }
            for edge in grouped[key]:
                self._walk_up(edge, path=[f"stmt:{sid}"], steps=[], group=group,
                              max_chains=max_chains, max_depth=max_depth, depth=0,
                              seen={sid})
            group["broken"] = any(c["status"] != "ok" for c in group["chains"])
            group["truncated"] = bool(group["reasons"])
            if group["broken"]:
                group["why"] = "这一组里至少有一条链走不到根（见 chains 里的 break_at）"
            else:
                group["why"] = f"这一组 {len(group['chains'])} 条链都走到了根"
            if group["truncated"]:
                out["truncated"] = True
                out["reasons"].extend(f"{group['group']}:{r}" for r in group["reasons"])
            out["groups"].append(group)
        broken_groups = [g["group"] for g in out["groups"] if g["broken"]]
        out["why"] = (f"按证明路径分 {len(out['groups'])} 组"
                      + (f"；走不到根的组：{'、'.join(broken_groups)}" if broken_groups else
                         "；每组都到了根"))
        return out

    def _walk_up(self, edge: Mapping[str, Any], *, path: list[str], steps: list[dict],
                 group: dict[str, Any], max_chains: int, max_depth: int, depth: int,
                 seen: set[str]) -> None:
        """从一条"向上"的边继续走到根（深度优先；每个终点记一条链）。"""
        step = {
            "from": path[-1], "to": (f"stmt:{edge['source_stmt_id']}"
                                     if edge["source_stmt_id"] else
                                     str(edge["source_root"].get("id") or "")),
            "dep_id": edge["dep_id"], "path_no": edge["path_no"],
            "path_group": edge["path_group"], "used_at": edge["used_at"],
            "used_at_known": edge["used_at_known"], "status": edge["status"],
        }
        chain_steps = [*steps, step]
        if len(group["chains"]) >= max_chains:
            if "chain_budget" not in group["reasons"]:
                group["reasons"].append("chain_budget")
            return
        target = str(edge["source_stmt_id"] or "")
        if not target:
            root = dict(edge["source_root"])
            if root:
                group["chains"].append(self._chain(path, chain_steps, root=root,
                                                   status="ok", break_at={}))
            else:
                group["chains"].append(self._chain(
                    path, chain_steps, root={}, status="broken",
                    break_at={"node": path[-1], "dep_id": edge["dep_id"],
                              "status": edge["status"],
                              "why": (f"这条依赖没有闭合（status={edge['status'] or '?'}）"
                                      f"，四选一来源一个都没给 ⇒ 走不到根"
                                      + (f"；理由：{edge['status_reason']}"
                                         if edge["status_reason"] else ""))}))
            return
        if target in seen:
            group["chains"].append(self._chain(
                path, chain_steps, root={}, status="broken",
                break_at={"node": path[-1], "dep_id": edge["dep_id"],
                          "why": f"依赖链成环：stmt:{target} 已经在来路上 ⇒ 走不到根"}))
            return
        if depth + 1 > max_depth:
            if "depth_budget" not in group["reasons"]:
                group["reasons"].append("depth_budget")
            group["chains"].append(self._chain(
                path, chain_steps, root={}, status="broken",
                break_at={"node": path[-1], "dep_id": edge["dep_id"],
                          "why": f"向上超过 {max_depth} 层还没到根 ⇒ 判不了终点"}))
            return
        target_node = self.nodes.get(target)
        if target_node is None:
            group["chains"].append(self._chain(
                path, chain_steps, root={}, status="broken",
                break_at={"node": path[-1], "dep_id": edge["dep_id"],
                          "why": (f"依赖指向 stmt:{target}，但台账里没有这一行 "
                                  "⇒ 断在不在册的那一端")}))
            return
        next_edges = self.up_edges(target)
        if not next_edges:
            is_concept = str(target_node.get("kind") or "") == "concept"
            root_kind = "primitive_concept" if is_concept else "no_premise"
            group["chains"].append(self._chain(
                path + [f"stmt:{target}"], chain_steps,
                root={"kind": root_kind, "id": f"stmt:{target}",
                      "label": target_node.get("label", "")},
                status="ok", break_at={}))
            return
        for nxt in next_edges:
            self._walk_up(nxt, path=path + [f"stmt:{target}"], steps=chain_steps,
                          group=group, max_chains=max_chains, max_depth=max_depth,
                          depth=depth + 1, seen=seen | {target})

    @staticmethod
    def _chain(path: list[str], steps: list[dict], *, root: Mapping[str, Any],
               status: str, break_at: Mapping[str, Any]) -> dict[str, Any]:
        return {"chain": list(path), "steps": [dict(s) for s in steps],
                "root": dict(root), "status": status, "break_at": dict(break_at)}

    @staticmethod
    def _edge_view(edge: Mapping[str, Any]) -> dict[str, Any]:
        """依赖面 / 被引面里每条边的读数（键恒定）。"""
        return {
            "dep_id": edge["dep_id"], "used_by": edge["used_by"],
            "used_by_head": edge["used_by_head"],
            "citer_stmt_id": edge["citer_stmt_id"],
            "citer_kind": edge["citer_kind"],
            "external_citer": bool(edge["external_citer"]),
            "proof_no": int(edge["path_no"]), "path_group": edge["path_group"],
            "kind": edge["kind"], "label": edge["label"],
            "source_stmt_id": edge["source_stmt_id"],
            "source_root": dict(edge["source_root"]),
            "used_at": edge["used_at"], "used_at_known": bool(edge["used_at_known"]),
            "status": edge["status"],
        }

    # ------------------------------------------------------------ 被引面（一层）

    def cited_face(self, stmt_id: Any) -> dict[str, Any]:
        """谁引用它 —— 只给一层（直接引用者），含每条边的路径号 / 用在哪一步。"""
        sid = self.normalize_stmt_id(stmt_id)
        out: dict[str, Any] = {
            "checked": True, "citations": [], "count": 0, "external": 0,
            "by_status": {}, "truncated": False, "reasons": [], "why": "",
        }
        if sid not in self.nodes:
            out.update(checked=False,
                       why="台账里没有这一条 ⇒ 被引面没查成（不是「没人引它」）")
            return out
        citations = [self._edge_view(e) for e in self.by_source.get(sid, ())]
        out["citations"] = citations
        out["count"] = len(citations)
        out["external"] = sum(1 for c in citations if c["external_citer"])
        by_status: dict[str, int] = {}
        for one in citations:
            by_status[str(one["status"])] = by_status.get(str(one["status"]), 0) + 1
        out["by_status"] = by_status
        out["why"] = (f"直接引用它（一层）的有 {len(citations)} 条依赖边"
                      if citations else
                      "台账里没有一条依赖边以它为被引方 ⇒ 0 条被引"
                      "（这是「查过、没人引」，不是「没查成」；"
                      "「台账里没有命题依赖它」不等于「它没有关系」）")
        return out

    # ------------------------------------------------------------ expand（局部树）

    def expand(self, node: Any, depth: int, direction: str = "both", *,
               max_nodes: int = MAX_NODES,
               max_chars: int = MAX_CHARS) -> dict[str, Any]:
        """从 `node` 起按 `depth` 层上下展开 ⇒ 局部树（层数由调用方决定、必填）。

        返回形状（业主 2026-11-10 的 4.2）：

            {nodes, edges, frontier, truncated, reasons, budget_used,
             added_nodes, already_known, ...}

        每个节点带七样：相对选定节点的关系（方向 / 距离 / 经由的链）、命题号、
        命题类别（`kind` 原文）、命题内容（`statement_full`，不含证明）、等级、
        依赖面（全路径 + 按证明路径分组）、被引面（一层）。

        无句柄、但增量：同一个 `(根, node, depth, direction)` 的第二次调用只交
        新增节点（`nodes` 里不再出现上一趟给过的），并在 `added_nodes` /
        `already_known` 里把两批分开；同一问反复调不会把同一批字段再塞一遍上下文。
        """
        sid = self.normalize_stmt_id(node)
        root_node = self.nodes.get(sid)
        base: dict[str, Any] = {
            "checked": False, "node": sid, "depth": int(depth), "direction": direction,
            "nodes": [], "edges": [], "frontier": [],
            "truncated": False, "reasons": [],
            "budget_used": {"nodes": 0, "added": 0, "edges": 0, "chars": 0,
                            "node_budget": int(max_nodes),
                            "char_budget": int(max_chars), "depth_max": int(depth)},
            "added_nodes": [], "already_known": [], "why": "",
        }
        if root_node is None:
            base["why"] = (f"台账里没有 {sid or '（空号）'} 这一条 ⇒ 展不开"
                           "（不是「它没有关系」）；先用 `ledger.resolve` 选一个真存在的根")
            base["reasons"] = ["node_not_found"]
            return base
        direction = str(direction or "both")
        max_depth = max(0, int(depth))
        max_nodes = max(1, int(max_nodes))
        max_chars = max(1, int(max_chars))

        # ---- BFS（按层推进；方向决定取哪一侧的邻接）
        relations: dict[str, dict[str, Any]] = {
            sid: {"direction": "root", "distance": 0, "via": [], "via_text": "（选定节点）"}}
        visited: list[str] = [sid]
        expanded: set[str] = set()
        edges_out: list[dict[str, Any]] = []
        chars = 0
        reasons: list[str] = []
        truncated = False

        queue: list[tuple[str, int]] = [(sid, 0)]
        while queue:
            current, distance = queue.pop(0)
            expanded.add(current)
            for nxt, edge, kind in self._neighbors(current, direction):
                edge_view = self._tree_edge(current, nxt, edge, kind)
                if all(e["dep_id"] != edge_view["dep_id"] or e["dir"] != edge_view["dir"]
                       or e["from"] != edge_view["from"] for e in edges_out):
                    edges_out.append(edge_view)
                if not edge_view["to_is_statement"]:
                    continue                     # 外部根：只作为边的读数
                target = str(edge_view["to_id"])
                if target in relations:
                    continue
                if distance + 1 > max_depth:
                    continue
                if len(visited) >= max_nodes:
                    if "node_budget" not in reasons:
                        reasons.append("node_budget")
                    truncated = True
                    continue
                relations[target] = {
                    "direction": "up" if kind == "up" else "down",
                    "distance": distance + 1,
                    "via": [*relations[current]["via"], _tree_step(edge_view)],
                    "via_text": self._via_text(relations[current], edge_view),
                }
                visited.append(target)
                queue.append((target, distance + 1))

        # ---- 逐节点装配读数（字符预算在装配时逐条核）
        nodes_out: list[dict[str, Any]] = []
        for sid_i in visited:
            reading = self._read_node(sid_i, relations[sid_i])
            size = len(json.dumps(reading, ensure_ascii=False))
            if chars + size > max_chars and nodes_out:
                if "char_budget" not in reasons:
                    reasons.append("char_budget")
                truncated = True
                break
            chars += size
            nodes_out.append(reading)

        # 边只连交回的那批节点（外部根例外：它们没有节点、本身就是边的读数）。
        # 预算/深度截到边界上的那些目标不进 `nodes`，只由 `frontier` 交接。
        delivered = {r["stmt_id"] for r in nodes_out}
        edges_out = [e for e in edges_out
                     if (not e["to_is_statement"]) or e["to_id"] in delivered]

        known = _delivered_get(self.root, sid, max_depth, direction)
        added = [r["stmt_id"] for r in nodes_out if r["stmt_id"] not in known]
        already = [{"stmt_id": r["stmt_id"], "kind": r["kind"],
                    "status": r["status"], "label": r["label"]}
                   for r in nodes_out if r["stmt_id"] in known]
        if known:
            # 增量：上一趟给过的节点不再重复交字段（身份 / 类别 / 状态 / 标签四格足够接上），
            # 边也只留与新增节点相连的那些（到旧节点的接缝保留，免得"接不上"）。
            added_set = set(added)
            nodes_out = [r for r in nodes_out if r["stmt_id"] in added_set]
            # 边跟着"新交付的节点"走：外部根没有节点，它挂在哪条边上就由那条边的
            # 展开方带出来；展开方没新增 ⇒ 这条外部读数也不该再塞一遍。
            edges_out = [e for e in edges_out
                         if e["to_id"] in added_set
                         or e["from"].split(":")[-1] in added_set]
        _delivered_add(self.root, sid, max_depth, direction, set(visited))

        frontier = self._frontier(visited, expanded, relations, direction, max_depth)
        base.update(
            checked=True, nodes=nodes_out, edges=edges_out,
            frontier=frontier, truncated=truncated, reasons=reasons,
            budget_used={"nodes": len(visited), "added": len(added),
                         "edges": len(edges_out), "chars": chars,
                         "node_budget": max_nodes, "char_budget": max_chars,
                         "depth_max": max_depth},
            added_nodes=added, already_known=already,
            why=(f"从 stmt:{sid} 起按 {direction} 展开 {max_depth} 层："
                 f"这一趟新增 {len(added)} 个节点"
                 + (f"，另有 {len(already)} 个上一趟已经给过（不重复塞）"
                    if already else "")),
        )
        return base

    # ------------------------------------------------------------ expand 的零件

    def _neighbors(self, sid: str, direction: str) -> list[tuple[str, dict, str]]:
        """`(目标, 边, 方向)` 列表；外部根也给（`目标` 为空串）。"""
        out: list[tuple[str, dict, str]] = []
        if direction in ("up", "both"):
            for edge in self.up_edges(sid):
                out.append((str(edge["source_stmt_id"] or ""), edge, "up"))
        if direction in ("down", "both"):
            for edge in self.down_edges(sid):
                out.append((str(edge["citer_stmt_id"] or ""), edge, "down"))
        return out

    @staticmethod
    def _tree_edge(current: str, nxt: str, edge: Mapping[str, Any],
                   kind: str) -> dict[str, Any]:
        """局部树的一条边（`from` = 展开的那一方，`to` = 走到的那一方）。

        外部根（`doc:` / `relation:` / `experiment:` 那一族，或 `source_lit_id` 那三种来源）
        没有目标节点：`to` 给它的外部号、`to_is_statement=False`，节点表里不建它。
        """
        external = not nxt
        if not external:
            target = f"stmt:{nxt}"
        elif kind == "down":
            target = str(edge["used_by_head"])
        else:
            target = str(edge["source_root"].get("id") or "")
        if kind == "up" and external:
            external_root = dict(edge["source_root"])
        elif external:
            external_root = {"kind": "external_usage", "id": target, "field": "used_by"}
        else:
            external_root = {}
        return {
            "from": f"stmt:{current}", "to": target, "to_id": (nxt if not external else target),
            "dir": "up" if kind == "up" else "down",
            "dep_id": edge["dep_id"], "path_no": edge["path_no"],
            "path_group": edge["path_group"], "used_at": edge["used_at"],
            "used_at_known": bool(edge["used_at_known"]),
            "status": edge["status"],
            "to_is_statement": not external,
            "external_root": external_root,
        }

    @staticmethod
    def _via_text(previous: Mapping[str, Any], edge: Mapping[str, Any]) -> str:
        """`relation.via_text` 的一行：从选定节点到这一条，逐跳写明方向与用在哪一步。"""
        arrow = "↑" if edge["dir"] == "up" else "↓"
        where = f"，用在哪一步：{edge['used_at']}" if edge["used_at"] else ""
        return (f"{previous['via_text']} {arrow} {edge['to']} "
                f"（{edge['dir']} · #p{edge['path_no']}{where}）")

    def _read_node(self, sid: str, relation: Mapping[str, Any]) -> dict[str, Any]:
        """一个节点的完整读数（七样，业主逐条点名）。"""
        node = self.nodes.get(sid) or {}
        return {
            "stmt_id": sid,
            "kind": str(node.get("kind") or ""),
            "status": str(node.get("status") or ""),
            "grade": str(node.get("grade") or EB.GRADE_NOT_APPLICABLE),
            "label": str(node.get("label") or ""),
            "statement_full": str(node.get("statement_full") or ""),
            "proof_no": int(node.get("proof_no") or DEFAULT_PROOF_NO),
            "proof_nos": list(node.get("proof_nos") or []),
            #: 1) 相对选定节点的关系：方向 / 相距几层 / 经由哪条边（链）
            "relation": {"direction": str(relation.get("direction") or ""),
                         "distance": int(relation.get("distance") or 0),
                         "via": [dict(one) for one in (relation.get("via") or [])],
                         "via_text": str(relation.get("via_text") or "")},
            #: 5) 依赖面：全路径 + 按证明路径分组
            "dependency_face": self.dependency_face(sid),
            #: 6) 被引面：只给一层（直接引用者）
            "cited_face": self.cited_face(sid),
        }

    def _frontier(self, visited: Sequence[str], expanded: set[str],
                  relations: Mapping[str, Mapping[str, Any]], direction: str,
                  max_depth: int) -> list[dict[str, Any]]:
        """边界节点 =「还能再展开」的接口（C 对其中任何一个再 expand 一次就接上）。

        两档都算：① 走到 `depth` 层、还有下一层的；② 因节点 / 字符预算没来得及展开的。
        """
        out: list[dict[str, Any]] = []
        for sid in visited:
            rel = relations.get(sid) or {}
            beyond = int(rel.get("distance") or 0) >= max_depth
            if sid in expanded and not beyond:
                continue
            can: list[str] = []
            if direction in ("up", "both"):
                if any(str(e["source_stmt_id"] or "") and
                       str(e["source_stmt_id"]) not in relations
                       for e in self.up_edges(sid)):
                    can.append("up")
            if direction in ("down", "both"):
                if any(str(e["citer_stmt_id"] or "") and
                       str(e["citer_stmt_id"]) not in relations
                       for e in self.down_edges(sid)):
                    can.append("down")
            if not can:
                continue
            node = self.nodes.get(sid) or {}
            out.append({"stmt_id": sid, "kind": str(node.get("kind") or ""),
                        "label": str(node.get("label") or ""),
                        "distance": int(rel.get("distance") or 0),
                        "directions": can})
        return out


# ---------------------------------------------------------------- 进程内缓存 / 增量账


#: 进程内按工作区根缓存一次（业主：本次唤醒缓存一次，不进上下文）。键是根路径字符串
#: 加上来源标记（store / tx 的读数不同，别把两种快照混成一个）。
_INDEX_CACHE: dict[tuple[str, str], LedgerIndex] = {}

#: 同一问（根 + 节点 + 层数 + 方向）已经交付过的节点号：无句柄的"增量"就靠这本账。
_DELIVERED: dict[tuple[str, str, int, str], set[str]] = {}


def cached_from_store(store: Any) -> LedgerIndex:
    """按 `store.root` 进程内缓存一次（没有 root 就不缓存，照建不误）。"""
    root = str(getattr(store, "root", "") or "")
    key = (root, type(store).__name__)
    if root and key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    index = LedgerIndex.from_store(store)
    if root:
        _INDEX_CACHE[key] = index
    return index


def reset_index_cache() -> None:
    """清掉进程内缓存（测试 / 长驻进程要重读台账时用；这不是"顺手写盘"）。

    名字刻意不叫 `clear_cache`：那个名字在 `webui/facecache.py` 已有一份独立实现，
    同名会被 lint R003 读成"同一判据的两份实现"。
    """
    _INDEX_CACHE.clear()
    _DELIVERED.clear()


def _delivered_key(root: str, sid: str, depth: int, direction: str) -> tuple:
    return (str(root or ""), str(sid), int(depth), str(direction))


def _delivered_get(root: str, sid: str, depth: int, direction: str) -> set[str]:
    return set(_DELIVERED.get(_delivered_key(root, sid, depth, direction), set()))


def _delivered_add(root: str, sid: str, depth: int, direction: str,
                   seen: Iterable[str]) -> None:
    _DELIVERED.setdefault(_delivered_key(root, sid, depth, direction), set()).update(
        str(one) for one in seen)


def _tree_step(edge: Mapping[str, Any]) -> dict[str, Any]:
    """`relation.via` 里的一跳（从哪到哪、经由哪条边、用在哪一步）。"""
    return {"dir": str(edge["dir"]), "from": str(edge["from"]), "to": str(edge["to"]),
            "dep_id": str(edge["dep_id"]), "path_no": int(edge["path_no"]),
            "path_group": int(edge["path_group"]),
            "used_at": str(edge["used_at"])}


class LedgerHolder:
    """工具的索引持有者（与 `_GraphHolder` 同形：一个可变的闭包捕获对象）。

    为什么要有它：`ledger.resolve` / `ledger.expand` 是跨调用共享同一份索引的
    （"一次建好、多次查询"），而工具层的 handler 只收得到自己的参数。同时它支持
    外部传入已建好的索引（测试与编排层要给一份事务快照时最常用）。
    """

    def __init__(self, index: Any = None, store: Any = None) -> None:
        self.store = store
        self._index: LedgerIndex | None = index if isinstance(index, LedgerIndex) else None
        self._factory = index if callable(index) and not isinstance(index, LedgerIndex) else None

    def get(self, *, build_if_missing: bool = True) -> LedgerIndex:
        if self._index is not None:
            return self._index
        if self._factory is not None:
            self._index = self._factory()
            return self._index
        if build_if_missing and self.store is not None:
            self._index = cached_from_store(self.store)
            return self._index
        raise LedgerIndexError(
            "台账索引尚未构建，且没有可用的 store。"
            "请先调 register(store=...) / 传入已建的 LedgerIndex。")

    def set(self, index: LedgerIndex) -> None:
        self._index = index
