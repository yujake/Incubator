# -*- coding: utf-8 -*-
"""命题台账的索引：代码侧一次建好（本次唤醒缓存一次），不进上下文、只读。

## 它是什么、不是什么（业主口径）

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
局部树交回，其余一律不出内存。`ledger.resolve` 只交候选节点（五格 + 档位读数），不交树。

## 概念平权（业主追加口径，逐字）

「概念只是命题台账里的一个标签，处理方式和命题平权」⇒ 概念行就是 `statements` 里
`kind=concept` 的那一行，就是普通节点：同一套 `resolve` / `expand` / 同一组字段。
本模块不读 `relations` 表、不借概念图、不为概念开任何特例分支。若某个概念节点今天
没有入边 / 出边（因为命题不引概念），就如实给空并说明原因 ——「台账里没有命题依赖它」
不等于「它没有关系」。

## 依赖面：全路径 + 按路径分组（业主追加口径）

每个被查到的节点的 `dependency_face` 是全路径（一路向上到根），并按
`(path_no, path_group)` 分组：同一个路径号的依赖一组，`#p2` 那一组另起一组。
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

from collections.abc import Iterable, Mapping
from typing import Any

from . import evidencebits as EB
from . import proofloc as PL
from . import schema as S
from . import secretary_tier_ledger as TL
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

#: `proof_no` 缺省（老行不带尾巴 ⇒ 路径号 1）。与 `proofloc.DEFAULT_PROOF_NO` 同值，
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
    """`(path_no, path_group)` ⇒ 人读的组名（`#p1` / `#p2·g3`）。"""
    proof_no, path_group = key
    tail = f"#p{proof_no}"
    return tail if int(path_group) <= 1 else f"{tail}·g{path_group}"


def _edge_sort_key(edge: Mapping[str, Any]) -> tuple:
    return (int(edge["path_no"]), int(edge["path_group"]),
            str(edge["used_by"]), str(edge["dep_id"]))


def _strip_id_prefix(text: str) -> str:
    """去掉号前面的 `stmt:` / `concept:` 前缀（两种读法共用这一处口径）。"""
    for prefix in ("stmt:", "concept:"):
        if text.lower().startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _nontriviality_reading(root: str, stmt_id: str,
                           statement_full: str = "") -> dict[str, Any]:
    """一个节点的非平凡度档位（逐证明路径；读口只有 `secretary_tier_ledger` 一处）。

    为什么节点读数里要有这一格（业主 2026-11-27）：「C 能读台账，就应该能读到逐命题
    逐证明路径的非平凡度档位」。C 写"为什么接受这一处高难度证明"这条理由时，手上必须
    有档位读数可引；而档位不是"每命题一档"，身份是 `(stmt_id, path_group)` —— 所以
    这一格是 `paths` 字典（键 = 路径号），不是单个 `level`。

    ## 折叠只在这里做一次（`FC-03`：不许有第二份折叠口径）

    档位值一律经 `secretary_tier_ledger.nontriviality_of`（那是唯一折叠实现：
    路径级 = 该路径最后一行、命题级 = 各路径历史最小值、版本闸 `checked` / `text_drift` /
    `needs_rejudge`）。本函数只把它折成的 `paths[]` 摊成"键 = 路径号"的字典，并加一格
    `state` 说明那一条路径现在能不能当读数用 —— 不解析台账、不重算档。

    ## 三态（不许折平）

    - 台账读不成（文件读不出 / 不是 UTF-8）⇒ `checked=False` + `why`、`paths` 空：
      那是"没查成"；它与"查过了、这条命题还没有档位行"（`checked=True`、`paths` 空）
      是两件事；
    - 没有工作区根 ⇒ 同样 `checked=False`（`why` 说清是缺根，不是缺行）；
    - 某条路径没判 / 要重判 ⇒ 那一条的 `level` 是 `None`、`state` 点明是
      `unjudged` 还是 `needs_rejudge`；不许读成某档（旧档只在 `nontriviality_of` 的
      `needs_rejudge_detail` 里可见，这里不复制）。

    只读：不开事务、不写盘、不缓存档位值（每次现读 `nontriviality_rows`，
    台账一变就读到新值 —— 把档位抄进别处当第二真源，就是两份口径漂开的起点）。
    """
    out: dict[str, Any] = {"checked": False, "why": "", "paths": {}}
    want = str(stmt_id or "").strip()
    if not str(root or "").strip():
        out["why"] = "没有工作区根 ⇒ 档位台账读不到（不是「这条命题没有档位」）"
        return out
    if not want:
        out["why"] = "没给命题号 ⇒ 这一问不成立（不是「这条命题没有档位」）"
        return out
    try:
        rows = TL.nontriviality_rows(str(root), stmt_id=want)
    except Exception as exc:  # noqa: BLE001 — 读口抛了就必须说"读不到"，不许静默空表
        out["why"] = f"档位台账读口抛了（{type(exc).__name__}: {exc}）"
        return out
    if not rows.get("checked"):
        out["why"] = str(rows.get("why") or "档位台账读不到")
        return out
    out["checked"] = True
    folded = TL.nontriviality_of(str(root), str(statement_full or ""), stmt_id=want)
    out["why"] = str(folded.get("reason") or "")
    for one in folded.get("paths") or ():
        if not isinstance(one, Mapping):
            continue
        try:
            no = str(max(1, int(one.get("path_group") or 1)))
        except (TypeError, ValueError):
            no = "1"
        level = one.get("level")
        version = str(one.get("version") or "")
        out["paths"][no] = {
            "level": None if level is None else int(level),
            "label": str(one.get("label") or ""),
            "version": version,
            # `state` 只做"这一条路径现在能不能当读数用"的分类，不引入新取值：
            # 要重判 / 没判 / 其余照抄版本闸的原话（checked / text_drift / unchecked…）。
            "state": ("needs_rejudge" if version == TL.NT_VERSION_NEEDS_REJUDGE
                      else ("unjudged" if level is None else version)),
        }
    return out


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
            proof_nos = [int(no) for no, _text in VR.proof_list(row)]
            nodes[sid] = {
                "stmt_id": sid,
                "kind": kind,
                "status": str(row.get("status") or ""),
                "grade": _grade_of(row),
                "label": str(row.get("label") or ""),
                "statement_full": str(row.get("statement_full") or ""),
                #: 这一条命题的非平凡度档位（逐证明路径，键 = `path_group`）。
                #: 读不到 ⇒ `{"checked": False, "paths": {}, "why": …}` —— 与"没有档位行"
                #: （`checked=True`、`paths` 空）分得开。见 `_nontriviality_reading`。
                "nontriviality": _nontriviality_reading(
                    str(root or ""), sid, str(row.get("statement_full") or "")),
                #: 这条命题现在挂着的路径号（`#p1` 恒在；多条路径时升序）。
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
        text = _strip_id_prefix(str(value or "").strip().strip("`'\"“”《》").strip())
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

        三条口径：

        - 按号：`stmt:000123` / `000123` / `123`（概念号同形 —— 概念就是台账里的一行）；
        - 按标签 / 关键字：走既有检索口径 `statementledger.by_keywords`
          （`label` / `statement_full` 经 `textutil.normalize` 包含任一关键词），
          不另写一套；
        - 找不到 ⇒ 明白说"没有这个号 / 没有命中"，不返回空列表了事。

        返回的每条候选是五格加一格档位读数：`stmt_id` / `kind` / `status` / `grade` /
        `label` / `nontriviality`。不含证明正文（也不含 `statement_full`：选根这一趟
        不需要命题全文）。`nontriviality` 与节点读数里那一格同源
        （`_nontriviality_reading`：逐证明路径、读不到即 `checked=False`）——
        选根时就该看得出"这一条难不难"。
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
        body = _strip_id_prefix(raw)
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

    def _candidate(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """一条候选（五格 + 档位读数；仍不含证明正文）。"""
        sid = str(row.get("stmt_id") or "")
        return {
            "stmt_id": sid,
            "kind": str(row.get("kind") or ""),
            "status": str(row.get("status") or ""),
            "grade": _grade_of(row),
            "label": str(row.get("label") or ""),
            #: 与节点读数同一格（`_nontriviality_reading`）：选根时就能看出"这一条难不难"，
            #: 不必先展开才知道。三态同源：读不到 ⇒ `checked=False`。
            "nontriviality": _nontriviality_reading(
                self.root, sid, str(row.get("statement_full") or "")),
        }

    # ------------------------------------------------------------ 依赖面 / 被引面 / 展开（转发）
    #
    # 这三面的实现住在 `ledgerface.py`（同一份索引的第一人称读法）。这里只保留方法名，
    # 因为 `ledger_tools` 与判据按 `LedgerIndex.expand` 取对象；转发不复制行为。

    def dependency_face(self, stmt_id: Any, *,
                        max_chains: int = MAX_FACE_CHAINS,
                        max_depth: int = MAX_FACE_DEPTH) -> dict[str, Any]:
        """转发到 `ledgerface.dependency_face`（依赖面的唯一实现）。"""
        return _LF.dependency_face(self, stmt_id, max_chains=max_chains,
                                   max_depth=max_depth)

    def cited_face(self, stmt_id: Any) -> dict[str, Any]:
        """转发到 `ledgerface.cited_face`（被引面的唯一实现）。"""
        return _LF.cited_face(self, stmt_id)

    def expand(self, node: Any, depth: int, direction: str = "both", *,
               max_nodes: int = MAX_NODES,
               max_chars: int = MAX_CHARS) -> dict[str, Any]:
        """转发到 `ledgerface.expand`（局部树展开的唯一实现）。"""
        return _LF.expand(self, node, depth, direction,
                          max_nodes=max_nodes, max_chars=max_chars)

    def _read_node(self, sid: str, relation: Any) -> dict[str, Any]:
        """转发到 `ledgerface._read_node`（节点读数的唯一实现）。

        保留成方法而不是只在 `ledgerface` 里留函数：`expand` 装配每个节点时按
        `index._read_node(...)` 取（判据就是打桩这一格），路径与拆分前一致。
        """
        return _LF._read_node(self, sid, relation)

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


def _delivered_key(root: str, sid: str, depth: int, direction: str) -> tuple:
    return (str(root or ""), str(sid), int(depth), str(direction))


def _delivered_get(root: str, sid: str, depth: int, direction: str) -> set[str]:
    return set(_DELIVERED.get(_delivered_key(root, sid, depth, direction), set()))


def _delivered_add(root: str, sid: str, depth: int, direction: str,
                   seen: Iterable[str]) -> None:
    _DELIVERED.setdefault(_delivered_key(root, sid, depth, direction), set()).update(
        str(one) for one in seen)


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


# 依赖面 / 被引面 / 局部树那三面的实现在 `ledgerface`（从本模块拆出）；这里在模块末尾回引，
# 于是 `LedgerIndex` 的方法面不变，而 `ledgerface` 顶部 import 本模块时名字都已定义。
from . import ledgerface as _LF  # noqa: E402
