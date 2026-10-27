# -*- coding: utf-8 -*-
"""并表过渡期：概念行的唯一读写口（S1r 的"两处同号合并"那一层）。

背景（`draft/97` §10.3 / §15.2）：`concepts` 要并进 `statements`（`kind="concept"`），
而这是一次动磁盘格式的迁移（`SCHEMA_VERSION 1→2`、`TABLES` 删表），属于
`AGENTS.md` 里"错误不可逆"的那一类。所以中间必须有一层过渡，让读侧可以一个一个搬：

- 写：新标准（`statements`）先写，老表（`concepts`）照旧镜像一份 —— 于是老读侧
  立刻看得到新写进来的概念，而新读侧（C 的依赖链、verify 的命题台账）也看得到；
- 读：合成一个视图（同一个号两边都有 ⇒ 新标准优先），于是读侧只用这一个口；
- 最后：迁移那一笔删掉老表、这一层的镜像与折叠随之退役（那时 `legacy_present`
  报 `False`，视图只剩 `statements`）。

## 契约（四条，改这一层的人必须一起守）

1. 一个身份一个号：过渡期写进去的概念行，`statements.stmt_id` 与老的
   `concepts.concept_id` 是同一个号。没有这一条，"两处同号合并"就无从谈起
   （读者会把同一个概念数两遍，或把两边的号当成两个概念）。
   迁移历史数据时号会重发（`migrate_concepts.plan_migration`）—— 那是另一条路：
   那一次之后老表不再存在，也就不存在"同号"这件事。
2. 新标准优先：同一个号两边都有 ⇒ 返回 `statements` 那一份（`via="statements"`）；
   只有老表有 ⇒ 就地把老字段折成新形状（`via="legacy"`，逐行可读，不是"大概等价"）。
3. 三态：老表读不成 / 新表读不成 ⇒ `checked=False` + `reason`，不许折成
   "只有一边"。`counts` 里 `statements` / `legacy` / `merged` / `legacy_only` 四个数
   分开给 —— "两边都有"与"只有一边"是不同的读数（前者说明镜像在工作，
   后者说明还有老写侧没搬完）。
4. 写经秘书（2026-10-26，D14）：这一层不再自己 `tx.upsert("statements", …)`，
   而是调 `Secretary.write_concept_row`（见 :func:`_concept_secretary`）。
   五元位、洗名（`wash_working_name`）、概念同一性（`propositionkey.same_concept`）
   三件事因此与秘书那条路是同一份实现 —— 这一层里不许出现第二份。
   为什么这条必须是契约而不是一句说明：真机 `projects/mp3-r3` 的 30 条概念行
   正是"绕过了它"的形态（`created_by=agent-B`、`bits` 空、非平凡度无记录），
   而盘上一切正常。

## 为什么镜像不用自己发号（一个容易被忽略的细节）

镜像行的号沿用命题那个号（契约 1），所以老表的 `concept` 计数器不会跟着前进。
这不是漏洞：`Tx.alloc_id` 在发号时会跳过"已声明事务表里已被占用的号"
（`store.Tx.alloc_id` 的 docstring 逐字写着这条自愈），而 B 的写侧声明 `concepts`
⇒ 它下一次发号会自然跳过镜像占掉的那些号。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from . import schema as S
from . import textutil as T
from .migrate_concepts import PENDING_SEARCH, fold_concepts

#: 过渡期还在盘上的老表名（迁移那一笔之后它从 `TABLES` 里消失）。
LEGACY_TABLE = "concepts"

#: 概念行允许的 `origin`（受控集合，唯一出处 = 这一处）。
#:
#: 口径逐字来自业主 2026-10-21（mp3 那批的验收词）：
#:
#: > 来自文献的 ⇒ `external_lit`；自己造的 ⇒ `own_result`；
#: > 概念行的 origin 不许是 `own_result`（除非它确实是自己定义的新概念）
#:
#: 真机读数（`projects/mp3/data/statements.json`，2026-10-21 现算）：1143 条概念行、
#: 其中 1142 条带 `source_lit_id`（术语确实出自文献），而 `origin` 一律是
#: `own_result` —— 于是"文献里来的术语"在报告里被读成"我们自己的结果"。
#: 根因在 `concept_statement` 把 `origin="own_result"` 写死（本批缺陷一）。
CONCEPT_ORIGINS: tuple[str, ...] = ("external_lit", "own_result")

#: 一轮之内新建概念的上限（业主 2026-10-21：「概念应按轮限量，一轮几十条以内」）。
#:
#: 为什么是 30（可自证）：
#:
#: - 真机读数：mp3 的一轮消化灌进 1143 条概念（19 篇文献 × 每篇几十个关系名），
#:   于是"每轮产出新事实"这条读数被一次水漫金山顶平 —— 一轮 1143 与一轮 3 条
#:   在多轮趋势上长得一样；
#: - 业主给的口径是"一轮几十条以内"：30 落在"几十"的下半区，既容得下一篇文献的
#:   显式概念草稿（真机里通常 < 30），又让配额确实咬得住；
#: - 它是每轮（`B.run` 一次 / 一次 `run_once` / 秘书的一笔）的总量，不是"每篇"：
#:   按篇限量挡不住"篇数多"那种水漫（19 篇 × 30 = 570 仍然过大）。
CONCEPTS_PER_ROUND_MAX = 30


def concept_origin_problem(*, origin: str, source_lit_id: str = "",
                           self_authored: bool = False) -> str:
    """概念行的 `origin` 口径 ⇒ 空串 = 放行，否则一句可读的拒信。唯一实现。

    三条判据（每一条都对着 mp3 那个真形态）：

    1. `origin` 必须在 :data:`CONCEPT_ORIGINS` 里（受控集合，不猜拼错的写法）；
    2. `external_lit`（文献里来的）必须给 `source_lit_id` —— 没有出处的"文献术语"
       与"我们自己造的"在数据面上就分不开了；
    3. `own_result`（我们自己造的）必须显式声明 `self_authored=True`：
       它不是默认值。默认值才是 mp3 那 1142 条错标的来源 ——
       "没声明"与"确实是新概念"必须分得开，否则这条判据永远拦不住沉默的错标。

    不判"定义有没有"：定义空着是 `pending_definition` 那一档（`D12` 甲允许），
    与 origin 是两件事（把两件事折平会让待补的概念写不进去）。
    """
    o = str(origin or "").strip()
    lit = str(source_lit_id or "").strip()
    if o not in CONCEPT_ORIGINS:
        return (f"概念行的 origin 必须是 {CONCEPT_ORIGINS} 之一，收到 {origin!r} ——"
                "来自文献的写 external_lit（并给 source_lit_id），"
                "自己定义的新概念写 own_result（并显式声明 self_authored=True）")
    if o == "external_lit":
        if not lit:
            return ("概念行声明 origin='external_lit' 却没给 source_lit_id ——"
                    "从文献来的术语必须说清是哪一篇（没有出处就无从回验，"
                    "也与'我们自己造的'在数据面上分不开）")
        return ""
    if not self_authored:
        return ("概念行的 origin 不许是 own_result：文献里来的术语是 external_lit"
                "（给 source_lit_id）。确实是我们自己定义的新概念才允许 own_result，"
                "且必须**显式**声明 self_authored=True —— 默认值不是证明"
                "（真机 mp3：1142 条带文献出处的术语被标成了 own_result）")
    if lit:
        return (f"声明了 self_authored=True 却给了 source_lit_id={lit!r} —— 自相矛盾："
                "定义来自文献就不是我们自己造的新概念（那种情况写 external_lit）")
    return ""


def resolve_concept_origin(*, origin: str = "", source_lit_id: str = "",
                           self_authored: bool = False) -> str:
    """没显式给 `origin` 时按数据推断（只在没给的时候，不覆盖调用方的声明）。

    推断规则（两条，与 :func:`concept_origin_problem` 同一口径）：

    - 有 `source_lit_id` ⇒ `external_lit`（这个术语是从那篇文献抽出来的）；
    - 没有出处 ⇒ `own_result`（定义就在这一行上，是我们自己写的）。

    推断出来的 `own_result` 视为"自己定义的新概念"（定义正文就在同一行），
    所以调用方不必再传 `self_authored`；而显式写 `origin="own_result"`
    就必须传它 —— 一句话：默认推断可以沉默，主动声明必须负责。
    """
    o = str(origin or "").strip()
    if o:
        return o
    if str(source_lit_id or "").strip():
        return "external_lit"
    return "own_result"


@dataclass
class ConceptQuota:
    """一轮之内"新建概念"的配额（业主 2026-10-21：「每轮几十条以内」）。

    ## 为什么配额要是一个对象，而不是一个整数常量

    "谁被拒了、拒了几条、剩下多少"必须跟着读数一起走。一个整数常量只能回答
    "超了没有"，回答不了"这一轮到底写了多少、被挡的是哪几条"——而"被挡的是哪几条"
    正是`不许静默丢弃`在数据面上的形态。

    ## 三种结局（都不许静默）

    | 结局 | `admit()` | 读数 |
    |---|---|---|
    | 还有余量 | `True`（`written += 1`） | — |
    | 配额用完 | `False`（名字进 `refused`） | `reading()` 里 `limit` / `written` / `refused` / `why` |

    `reading()["why"]` 就是业主点名的那个读数："这一轮概念配额用完，剩下的下一轮或
    写进报告"。已经写进去的一条都不回滚（"已写的保留"：配额是写入闸，
    不是事务回滚 —— 回滚会把这一轮的真产出一起抹掉）。
    """

    limit: int = CONCEPTS_PER_ROUND_MAX
    written: int = 0
    refused: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(int(self.limit) - int(self.written), 0)

    @property
    def exhausted(self) -> bool:
        return int(self.written) >= int(self.limit)

    def admit(self, name: str = "") -> bool:
        """放行一条新建概念；配额用完 ⇒ 记名字、返回 `False`（调用方必须留读数）。"""
        if self.exhausted:
            self.refused.append(str(name or ""))
            return False
        self.written += 1
        return True

    def reading(self) -> dict[str, Any]:
        """这一轮配额的读数（没被拒时也照给，`refused` 为空）。"""
        out: dict[str, Any] = {
            "limit": int(self.limit),
            "written": int(self.written),
            "refused": list(self.refused),
            "refused_count": len(self.refused),
            "why": "",
        }
        if self.refused:
            out["why"] = (
                f"这一轮概念配额用完（上限 {int(self.limit)} 条，已写 {int(self.written)} 条）⇒"
                f" 超出的 {len(self.refused)} 条被**受控拒绝**（{self.refused[:8]}），"
                "已经写进去的一条都没有回滚；剩下的下一轮再写，或者写进报告 ——"
                "不许静默丢弃（静默丢弃会让'每轮产出新事实'这条读数看起来一直正常）")
        return out

#: `_to_legacy` 给"墓碑"投影出的哨兵值：非空（读侧据此跳过它），且绝不是一个合法 id
#: （`schema.is_valid_id` 为假 ⇒ 谁把它当号用都会当场看出不对，而不是去找一个不存在的概念）。
SUPERSEDED_INTO = "superseded"

#: `draft/97` §15.4 的①档标记：问直接父（最常见的场景里父就是 A —— 原文在它手里，
#: 就地就能给定义，不用惊动 M、也不用真的再上网搜）。
#:
#: 为什么它是一个行内标记而不是一列/一张表：它与 `pending_search` / `self_authored`
#: 是同一件事的三个取值（"这个定义最后由谁来补"），而"定义到底到了没有"由
#: `statement_full` 是否为空单独回答 —— 两件事折平就会把"已经问了父"读成"定义有了"。
ASK_PARENT = "concept:ask_parent"


def definition_supply(store: Any) -> dict[str, Any]:
    """概念行的定义来源逐档计数（`draft/97` §14.13 / §15.4：三档不许折平）。

    业主 2026-10-09 的两句口径合成这一格：

    > 「抽不到定义的概念就让A去网上搜，写入时定义内容留空，等A返回后写入；如果概念很基础，
    >  是数学基本概念，允许B自己写定义（我们相信LLM的智力）」
    > 「最常见的定义不明极可能是A查论文要B消化时遇到生僻定义，这时和父代理A交流即可」

    返回 `{"checked", "rows", "from_lit", "self_authored", "ask_parent",
    "pending_search", "waiting_ask_parent", "unmarked_empty", "reason"}`：

    | 桶 | 什么时候 |
    |---|---|
    | `from_lit` | 定义在，且有 `source_lit_id`（从某篇文献抽到） |
    | `ask_parent` | 定义在，理由里带着"父给的"这一档 |
    | `self_authored` | 定义在，没有外部来源（B 自撰：基本概念） |
    | `pending_search` | 定义不在，理由里写着等 A 搜（`concept:pending_search`） |
    | `waiting_ask_parent` | 定义不在，已经向父发出请求（`concept:ask_parent`） |
    | `unmarked_empty` | 定义不在、也没有任何待补标记 —— 这就是历史那 94 条的病根，它必须恒为 0 |

    两个半区（"定义到了"与"还没到"）分开报：把 `ask_parent` 折进"定义有了"会让
    "已经问了父"读成"父已经给了"。`checked=False` 时每个桶都是 0，但 `reason` 说清为什么
    （"没查成"不是"全是 0"）。
    """
    out: dict[str, Any] = {"checked": False, "rows": 0, "from_lit": 0, "self_authored": 0,
                           "ask_parent": 0, "pending_search": 0, "waiting_ask_parent": 0,
                           "unmarked_empty": 0, "reason": ""}
    try:
        rows = [dict(r) for r in store.rows("statements")
                if str(r.get("kind") or "") == "concept"]
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报
        out["reason"] = f"statements 读不成（{type(exc).__name__}: {exc}）"
        return out
    out["rows"] = len(rows)
    out["checked"] = True
    for r in rows:
        reason = str(r.get("quote_reason") or "")
        defined = bool(str(r.get("statement_full") or "").strip())
        if defined:
            if str(r.get("source_lit_id") or "").strip():
                out["from_lit"] += 1
            elif ASK_PARENT in reason:
                out["ask_parent"] += 1
            else:
                out["self_authored"] += 1
        elif ASK_PARENT in reason:
            out["waiting_ask_parent"] += 1
        elif PENDING_SEARCH in reason:
            out["pending_search"] += 1
        else:
            out["unmarked_empty"] += 1
    return out


def legacy_present(store: Any) -> dict[str, Any]:
    """过渡期还作不作数（`present` = 老表还在 `TABLES` 里），以及盘上还剩什么。

    四种状态都要分得开：

    | `TABLES` 里 | 盘上 | 返回 |
    |---|---|---|
    | 有 | 有/没有 | `checked=True, present=True`（过渡期：写侧要镜像；文件还没建是常态） |
    | 没有 | 有 | `checked=True, present=False, stale_file=True` —— 迁移之后留下的老文件（必须点名：它装着没搬完的数据） |
    | 没有 | 没有 | `checked=True, present=False`（迁移干净了） |
    | 任意 | 读不成 | `checked=False` + `reason`（"没查成"不是"没有"） |

    为什么 `present` 判的是"表还在不在 schema 里"而不是"文件在不在"：
    镜像这件事的依据是这一版代码还认不认老表。拿文件判会把"新工作区还没写过概念"
    读成"过渡期结束了"，于是那些工作区里新概念不被镜像、老读侧看不到它 ——
    而两种情形在文件系统上长得一样（都没有那个文件）。
    文件在不在是另一个读数（`file`），没有它，迁移之后那份残留就没人看得见。
    """
    registered = LEGACY_TABLE in S.TABLES
    if not hasattr(store, "data"):
        return {"checked": False, "present": registered, "file": False, "stale_file": False,
                "reason": "这个 store 没有 data 目录句柄 ⇒ 盘上还剩什么判不了"}
    path = store.data / (S.TABLES[LEGACY_TABLE]["file"] if registered else "concepts.json")
    try:
        exists = path.is_file()
    except OSError as exc:  # noqa: BLE001 —— 读不成 ≠ 没有
        return {"checked": False, "present": registered, "file": False, "stale_file": False,
                "reason": f"看不了 {path.name}（{type(exc).__name__}: {exc}）"}
    stale = bool(exists and not registered)
    return {"checked": True, "present": registered, "file": bool(exists), "stale_file": stale,
            "reason": ("老表已退役而文件还在（迁移留下的老文件，里面可能还有没搬完的行）"
                       if stale else "")}


def _from_legacy(row: Mapping[str, Any]) -> dict[str, Any]:
    """老表一行 ⇒ 新标准形状的一行（号不变，这是过渡期的契约 1）。

    复用迁移内核 `fold_concepts`（同一个折叠口径），只把"发号"那一步钉成"原号"：
    预演与迁移那一条路会重发号（避免与既有命题撞号），而过渡期的镜像本来就是
    "同一个身份两个落点" ⇒ 号必须相同。
    """
    old_id = str(row.get("concept_id") or "")
    folded = fold_concepts([dict(row)], alloc=lambda: old_id)
    out = dict(folded["rows"][0])
    out["via"] = "legacy"
    # `related_concepts` 是老表专有的一格（迁移内核刻意丢掉它：并表之后那件事由
    # `relations` 表管）。但过渡期的老字段名投影要忠实（`verify` 的
    # `related_drift` 判据与 `agentflow repair --related` 都靠它）⇒ 在这里带过来，
    # 并记明它是"过渡期的一格"，不是新标准的一部分。
    out["related_concepts"] = list(row.get("related_concepts") or [])
    out["legacy_related"] = True   # "这一格有权威值"（判据据此分档，见 `view` 的 docstring）
    # 墓碑（`merged_into`）必须带过来：它是"这一行不是活节点"的唯一机器可读标记，
    # 而读侧（`dedup.find_concept` / `decide_structural_duplicate`）判的正是这一格的真值性。
    # 丢弃它等于把墓碑重新变成活节点 —— 新知识会挂到幽灵节点上、survivor 永远接不到
    # （实测抓到，见 `_to_legacy` 的 docstring 与 `draft/97` §13.2l）。
    if str(row.get("merged_into") or ""):
        out["merged_into"] = str(row["merged_into"])
        out["status"] = "superseded"   # 与 `sync_from_legacy` 的墓碑映射同一档
    return out


def concept_statement(*, stmt_id: str, label: str, definition: str = "", aliases: Iterable[str] = (),
                      source_lit_id: str = "", proof_text: str = "", doc_id: str = "",
                      actor: str = "agent-B", origin: str = "",
                      self_authored: bool = False) -> Any:
    """一条概念 ⇒ 一行 `Statement`（并表之后概念的落点，新标准的唯一构造口）。

    两档（`D12` 甲）：定义在 ⇒ `active`；定义还没抽到 ⇒ `pending_definition`
    + `quote_reason` 里的待补标记（`concept:pending_search`：等 A 检索回来，
    或基本概念由 B 自撰）。不许落成 `active` + 空定义，也不许干脆不落。

    ## 概念行不带 `proof_text`（本批缺陷一的写入侧）

    真机读数（`projects/mp3/data/statements.json`）：1143 条概念行，每一条都带
    `proof_text="concept:primitive"` —— 于是任何"有没有证明"的读数（
    `proof_review_gap` 的 `proof_text` 非空判据、收工门的 `reviewed` 档、
    `prose_reviewed_statements`）都被虚高。那个值不是证明，是一个哨兵：
    它当初是为了表达"这是一个原始概念、没有良定义性证明可写"，而表达式本该是
    "`proof_text` 留空 + 这个概念不参与等级链"（`evidencebits.derive_grade` 对
    `kind="concept"` 本来就短路成 `not_applicable`）。

    所以这一格现在永远写空：调用方传了 `proof_text` 就是传错了词，当场拒绝
    （`ValueError`，消息里写清原因），而不是悄悄丢掉 —— 静默丢会让调用方以为
    "概念也能带证明"。历史行一个字不动（本批的边界：只堵写入侧）。

    ## `origin` 按来源分档（本批缺陷一的第二处）

    口径与判据在 :func:`concept_origin_problem` / :func:`resolve_concept_origin`：
    有 `source_lit_id` ⇒ `external_lit`；没有 ⇒ `own_result`（定义就在这一行上）。
    显式声明 `own_result` 必须带 `self_authored=True`。
    """
    definition = str(definition or "")
    # 概念行不许带证明文本（唯一口径在这里，别的写口都经过本函数）。
    if str(proof_text or "").strip():
        raise ValueError(
            "概念行不该带证明文本：`proof_text` 是“这段证明被逐行审阅过”的比对对象，"
            "而概念不参与等级链（`evidencebits.derive_grade` 对 kind='concept' 短路）。"
            f"收到的 proof_text={str(proof_text)[:60]!r} —— 概念行请留空；"
            "要表达“这是原始概念”，落的是 `kind='concept'` + 空 proof_text，"
            "而不是往里塞一个哨兵（真机 mp3：1143 条概念行全带 `concept:primitive`，"
            "把“有没有证明”的读数全顶高了）")
    explicit = bool(str(origin or "").strip())
    resolved = resolve_concept_origin(origin=origin, source_lit_id=source_lit_id,
                                      self_authored=self_authored)
    # 推断出来的 own_result（没有出处 ⇒ 定义就在这一行上）视为"自己定义的概念"；
    # 显式声明 own_result 则必须由调用方自己带 self_authored（见 resolve 的 docstring）。
    effective_self_authored = bool(self_authored) or (resolved == "own_result" and not explicit)
    problem = concept_origin_problem(origin=resolved, source_lit_id=source_lit_id,
                                     self_authored=effective_self_authored)
    if problem:
        raise ValueError(problem)
    pending = not definition.strip()
    if pending:
        reason = (f"概念 {label!r} 的定义还没抽到（D12 甲）：{PENDING_SEARCH} —— "
                  "由直接父/A 检索回来，或基本概念由 B 自撰；定义到了就改回 active 并清掉"
                  "这一标记。概念没有'证明'这一档 ⇒ `proof_text` 留空")
    else:
        reason = ("概念行没有'证明'这一档（不参与等级链）⇒ `proof_text` 留空；定义来自 "
                  + (f"lit:{source_lit_id}" if source_lit_id else "B 的消化（没有外部来源，"
                     "按自己定义的新概念记）"))
    return S.Statement(
        stmt_id=stmt_id, origin=resolved, kind="concept", label=str(label or ""),
        statement_text=definition, statement_full=definition,
        proof_text="", source_lit_id=str(source_lit_id or "") or None,
        quote_verified=None, quote_reason=reason, evidence_kind="heuristic",
        aliases=[str(a) for a in (aliases or []) if str(a).strip()],
        status=("pending_definition" if pending else "active"),
        doc_id=str(doc_id or "") or None, created_at=S.now_iso(), created_by=actor)


#: 过渡投影认得的字段（老名字 ⇒ 新标准的哪一格）。`shape="legacy"` 用它把视图
#: 反向投影回老字段名，好让读侧一次只搬一件事（先换读口，再逐处改字段名）。
LEGACY_VIEW_FIELDS: dict[str, str] = {
    "concept_id": "stmt_id",
    "name": "label",
    "definition": "statement_full",
    "normalized_name": "",      # 老表里可能有、新标准里没有 ⇒ 现算（见 `_to_legacy`）
    "related_concepts": "",     # 那件事由 `relations` 表管（并表之后更明确）
    "definition_source_lit_id": "source_lit_id",
    "merged_into": "",          # 新标准里用 `status="superseded"` + `quote_reason` 表达
}


def _to_legacy(row: Mapping[str, Any]) -> dict[str, Any]:
    """新标准形状的一行 ⇒ 老字段名的一行（过渡投影；只做名字映射，不改内容）。

    两条边界必须显式：

    - `normalized_name` 现算（`textutil.normalize(label)`）——老表那一格实测
      640/2233 条与现算不符（`pipeline.py` 当年把原始名字写了进去），投影里跟现算走，
      与 `migrate_concepts` 的"读侧现算、丢弃那一格"同一口径；
    - `related_concepts` 给 `[]`（并表之后那件事由 `relations` 表管）；
    - `merged_into`：新标准里没有这一列，墓碑用 `status="superseded"` 表达 ⇒
      这一格按 `status` 投影出一个非空哨兵（`SUPERSEDED_INTO`），不是编一个目标号
      （目标号在新标准里没有机器可读的落点，只有 `quote_reason` 里那句话）；
      老表那一档（`row["merged_into"]` 真的有值）原样带过来。
      为什么必须给非空：读侧判"这一行是不是活节点"读的正是这一格的真值性 ——
      `dedup.find_concept` 是 `if row.get("merged_into"): continue`，
      `agent_b.decide_structural_duplicate` 是 `if a.get("merged_into") or b.get("merged_into")`。
      投影恒给 `None` 会把墓碑重新变成活节点：新来的同名概念命中幽灵节点、
      survivor 永远接不到新知识，而盘上一切正常（实测抓到：让被合并方在
      `statements.json` 里排在前面，`find_concept(view_rows, "abelian group")`
      返回墓碑而不是 survivor）。
    """
    out: dict[str, Any] = {}
    for legacy_name, new_name in LEGACY_VIEW_FIELDS.items():
        if new_name:
            out[legacy_name] = row.get(new_name)
    out["normalized_name"] = T.normalize(str(row.get("label") or ""))
    # `related_concepts`：老表那一档原样带过来（它是真的数据，判据要拿它比派生结果）；
    # 新标准那一档没有这一格 ⇒ 空列表，而判据据 `via` 分辨"表里写着空"与"这一版没这一格"
    # （`verify._check_4` 那一档）。两件事折平会造出假红。
    out["related_concepts"] = list(row.get("related_concepts") or [])
    out["legacy_related"] = bool(row.get("legacy_related"))  # 见 `_from_legacy`
    superseded = str(row.get("status") or "") == "superseded"
    out["merged_into"] = (str(row["merged_into"]) if str(row.get("merged_into") or "")
                          else (SUPERSEDED_INTO if superseded else None))
    out["aliases"] = list(row.get("aliases") or [])
    out["status"] = row.get("status")
    out["via"] = row.get("via")
    return out


def view(store: Any, *, shape: str = "statement") -> dict[str, Any]:
    """概念行的合成视图（新标准形状 + 逐行 `via` + 四个计数）。

    返回 `{"checked", "rows", "counts", "legacy", "reason"}`：
    `counts` = `{"statements", "legacy", "merged", "legacy_only", "definition_only_in_legacy"}`。
    最后那一个是"新标准那一行还空着定义、而老行有"的条数 —— 它不自动合并
    （新标准优先），但必须可见：那是"两边不同步"的读数，不是可以顺手抹平的差异。

    `shape="legacy"`（2026-10-09 加）：把每一行反向投影回老字段名
    （`concept_id`/`name`/`definition`…，见 `LEGACY_VIEW_FIELDS`）。它的用途只有一个 ——
    让读侧一次只搬一件事：先换读口（`store.rows("concepts")` ⇒ `view(…)[ "rows"]`），
    再逐处把字段名改成新标准。两件事一起做的话，红的时候分不清是"读口换错了"
    还是"字段名换错了"，而这两类错的处置完全不同。
    投影是单向的（老名字 ⇒ 新标准的那一格；新标准独有的 `bits`/`doc_id` 不丢，
    它们照旧在新名字下带着），所以它不会把视图变成"第二份老表"。
    """
    out: dict[str, Any] = {"checked": False, "rows": [], "legacy": {}, "reason": "",
                           "shape": str(shape or "statement"),
                           "counts": {"statements": 0, "legacy": 0, "merged": 0,
                                      "legacy_only": 0, "definition_only_in_legacy": 0}}
    try:
        stmt_rows = [dict(r) for r in store.rows("statements") if str(r.get("kind") or "") == "concept"]
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报（不是"没有概念"）
        out["reason"] = f"statements 读不成（{type(exc).__name__}: {exc}）"
        return out

    legacy = legacy_present(store)
    out["legacy"] = legacy
    if not legacy.get("checked"):
        out["reason"] = str(legacy.get("reason") or "老表在不在判不了")
        return out
    if legacy.get("stale_file"):
        out["reason"] = str(legacy.get("reason") or "")
    legacy_rows: list[dict[str, Any]] = []
    if legacy.get("present"):
        try:
            legacy_rows = [dict(r) for r in store.rows(LEGACY_TABLE)]
        except Exception as exc:  # noqa: BLE001 —— 老表读不成 ⇒ 三态里的"没查成"
            out["reason"] = f"老表读不成（{type(exc).__name__}: {exc}）⇒ 视图不完整"
            return out
    return _merge_rows(out, stmt_rows=stmt_rows, legacy_rows=legacy_rows)


def view_tx(tx: Any, *, shape: str = "statement") -> dict[str, Any]:
    """`view()` 的事务内形态：读己之写（同一笔事务里刚写的概念立刻看得见）。

    为什么必须与 `view()` 分开：事务里的读有"读己之写"的语义，而 `view()` 走的是
    `store.rows`（无锁快照，读不到本事务尚未提交的行）。B 的 `_apply_merge` 正是
    "读概念行 → 改写 → 写回"三件事在同一笔里（`tx.rows("concepts")`）——
    换成 `store.rows` 会让它读到上一次提交的版本，于是合并/别名同步落空，
    而盘上看起来一切正常（这一笔写完了，只是基于旧值）。

    两边的口径（合并、同号去重、`via`、计数、投影）必须同一份实现 ——
    所以这里只负责"从哪读"，合并那一段调 `_merge_rows`。
    """
    out: dict[str, Any] = {"checked": False, "rows": [], "legacy": {}, "reason": "",
                           "shape": str(shape or "statement"), "in_tx": True,
                           "counts": {"statements": 0, "legacy": 0, "merged": 0,
                                      "legacy_only": 0, "definition_only_in_legacy": 0}}
    try:
        stmt_rows = [dict(r) for r in tx.rows("statements")
                     if str(r.get("kind") or "") == "concept"]
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报
        out["reason"] = f"事务里的 statements 读不成（{type(exc).__name__}: {exc}）"
        return out
    present = LEGACY_TABLE in S.TABLES
    out["legacy"] = {"checked": True, "present": present, "file": None, "stale_file": False,
                     "reason": ""}
    legacy_rows: list[dict[str, Any]] = []
    if present:
        try:
            legacy_rows = [dict(r) for r in tx.rows(LEGACY_TABLE)]
        except Exception as exc:  # noqa: BLE001 —— 老表读不成 ⇒ 三态里的"没查成"
            out["reason"] = f"事务里的老表读不成（{type(exc).__name__}: {exc}）⇒ 视图不完整"
            return out
    return _merge_rows(out, stmt_rows=stmt_rows, legacy_rows=legacy_rows)


def _merge_rows(out: dict[str, Any], *, stmt_rows: list[dict[str, Any]],
                legacy_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """合成的唯一实现（`view` 与 `view_tx` 都走这里：两边口径分家会造两种真相）。"""
    by_id: dict[str, dict[str, Any]] = {}
    for row in stmt_rows:
        row = dict(row)
        row["via"] = "statements"
        by_id[str(row.get("stmt_id") or "")] = row
    out["counts"]["statements"] = len(by_id)
    out["counts"]["legacy"] = len(legacy_rows)
    for lrow in legacy_rows:
        folded = _from_legacy(lrow)
        key = str(folded.get("stmt_id") or "")
        if key in by_id:
            out["counts"]["merged"] += 1
            # 两边都有 ⇒ 新标准优先，但老表专有的那一格要带过来：
            # `related_concepts` 只有老表有（新标准里那件事由 `relations` 表管），
            # 而 `verify` 的 drift 判据要拿它比派生结果 —— 不带上它，一行"两边都有"的
            # 概念就会逃过 `related_drift`（新标准那一侧根本没有这一格）。
            # `legacy_related=True` 是"这一格有权威值"的显式标记（判据据它分辨，
            # 而不是据 `via`：`via` 说的是"这一行以谁为准"，不是"哪些格有值"）。
            by_id[key]["related_concepts"] = list(folded.get("related_concepts") or [])
            by_id[key]["legacy_related"] = True
            if (not str(by_id[key].get("statement_full") or "").strip()
                    and str(folded.get("statement_full") or "").strip()):
                out["counts"]["definition_only_in_legacy"] += 1
            continue
        by_id[key] = folded
        out["counts"]["legacy_only"] += 1
    out["checked"] = True
    rows = list(by_id.values())
    out["rows"] = [_to_legacy(r) for r in rows] if out["shape"] == "legacy" else rows
    return out


def push_counters(tx: Any, used_id: str) -> None:
    """把 `stmt` 与 `concept` 两个计数器都抬到 `used_id` 之后（只抬，不烧号）。

    为什么必须有这一格（实测抓到的一条真缺陷）：过渡期是"同一个号写在两张表里"，
    而两张表各有自己的计数器。B 的 pipeline 从 `concept` 计数器发号 ⇒ 写入 `statements`
    的那些镜像行会让 `stmt` 计数器落在后面（`verify` 的 `counter_behind` 当场报
    "stmt 计数器为 0，但表里已用到 3；继续分配会撞号"）；反过来，秘书那条路从 `stmt`
    发号 ⇒ `concept` 计数器落在后面。两个方向都要补。

    第一版是错的，记在这里（`test_demo_end_to_end` 的"零问题"判据当场抓出来）：
    它用"多调一次 `alloc_id` 把计数器顶上去"来修 —— 那会烧掉一个没建行的号，
    同一张表于是出现 `id_gap`（"分配了 ID 但未建成行"）。正确形状是
    `Tx.raise_counter_to(kind, used_id)`：把计数器设到 `max(used)+1`，一个号都不烧。
    """
    text = str(used_id or "")
    if not text.isdigit():
        return
    for kind in ("stmt", "concept"):
        try:
            tx.raise_counter_to(kind, text)
        except Exception:  # noqa: BLE001 —— 抬不动不影响这一笔已经写好的行
            continue


def tables_for_concept_write(*extra: str) -> tuple[str, ...]:
    """写一条概念要声明哪些表：`statements` + （老表还在时）`concepts` + 调用方给的。

    为什么要有这一格（它是"落刀不牵连夹具"的关键）：`Store.tx` 对未知表会拒，
    所以凡是"声明了 `concepts`"的地方在落刀之后都会当场报错 —— 实测这样的地方有
    29 处（`temp/_s1r_flip_inventory.py` 的 `tx_declare`：src 13 + tests 45 处里的
    去重文件数）。让调用方改成 `store.tx(*CR.tables_for_concept_write("relations"), …)`
    之后，老表在不在由这一处判断，夹具与测试在落刀前后都不用改一个字。
    """
    base = ["statements", *[str(x) for x in extra if str(x)]]
    if LEGACY_TABLE in S.TABLES:
        base.append(LEGACY_TABLE)
    return tuple(dict.fromkeys(base))


def upsert_legacy_shaped(tx: Any, row: Mapping[str, Any], *,
                         actor: str = "agent-B", note: str = "legacy_shaped") -> dict[str, Any] | None:
    """一条老形状的概念行 ⇒ 新标准写一份（老表还在时顺带镜像，同一个号）。

    这一格是给夹具、探针与自检用的（生产的写侧有自己的秘书那一套）：
    它们手里拿的是 `{"concept_id": …, "name": …, "definition": …}` 这种字典，
    而落刀之后"老表"不存在了 —— 让它们走这一处，含义就变成
    "写一条概念（哪张表由过渡层决定）"，于是它们在落笔前后行为不变。

    三态：老行没有 `concept_id` ⇒ 返回 `None`（不猜号）；
    老表还在 ⇒ 先写老表那一份（夹具的既有断言照旧成立）再同步新标准；
    老表已退役 ⇒ 只写新标准。
    """
    cid = str(row.get("concept_id") or "")
    if not cid:
        return None
    if LEGACY_TABLE in S.TABLES:
        tx.upsert(LEGACY_TABLE, dict(row), note=note)
    return sync_from_legacy(tx, row, actor=actor)


def mirror_gaps(store: Any) -> dict[str, Any]:
    """过渡期的镜像完整性读数：哪一号只在一张表里有（三态 + 逐号点名）。

    为什么必须有这一格：过渡期的"读侧走视图"能成立，靠的是两面都在 ——
    B 的 pipeline 里那几处 `tx.rows("concepts")`（查重、别名合并、related 重算）
    读的仍是老表；只要"新标准写进来的概念都被镜像了"，那些读就仍然看得全。
    反过来说：任何一处写侧忘了镜像，那一批概念就会在 pipeline 的查重里消失
    （静默漏判、可能重复建概念），而盘上看起来一切正常（两边行数都"有增长"）。

    这正是"写侧那几处 `tx.rows` 可以留到落刀那一笔再改"的前提 ——
    所以它是一个判据，不是一句注释：`statements_only` 非空 ⇒ 要么补镜像，
    要么把那一处写侧搬过来。

    返回 `{"checked", "statements_only", "legacy_only", "merged", "transition_over", "reason"}`。
    `transition_over=True`（S1r 落刀之后加的那一档）说的是"老表既不在 schema 里、
    盘上也没有老文件"⇒ 没有"另一侧"，缺口不成立、三个集合都为空 —— 不这样分档的话
    新标准里每一条概念都会被读成"缺镜像"。

    注意这里读的是两张表的原始行（不是合并视图）：合并视图里"两边都有"的那一行
    只带 `via="statements"`，从它看不出老表那一份在不在 —— 而这一格问的正是
    "老表那一份在不在"。
    """
    out: dict[str, Any] = {"checked": False, "statements_only": [], "legacy_only": [],
                           "merged": [], "transition_over": False, "reason": ""}
    try:
        stmt_ids = {str(r.get("stmt_id") or "") for r in store.rows("statements")
                    if str(r.get("kind") or "") == "concept"}
    except Exception as exc:  # noqa: BLE001 —— 读不成要如实报
        out["reason"] = f"statements 读不成（{type(exc).__name__}: {exc}）"
        return out
    state = legacy_present(store)
    if not state.get("checked"):
        out["reason"] = str(state.get("reason") or "老表在不在判不了 ⇒ 镜像完整性判不了")
        return out
    if not state.get("present") and not state.get("stale_file"):
        # 并表那一笔之后：老表既不在 schema 里、盘上也没有那份文件 ⇒ 没有"另一侧"，
        # 于是"缺口"这件事根本不成立。不加这一档的话，新标准里每一条概念都会被读成
        # "缺镜像"（`statements_only` = 全体）—— 一个永不消失的假告警，而假告警的
        # 代价是"这一格从此没人看"。
        # `stale_file` 那一支不走这里：老文件还在盘上（可能装着没搬完的行）⇒
        # 那不是"过渡结束"，是"还有一份没搬"，照旧按缺口报。
        out["checked"] = True
        out["transition_over"] = True
        out["reason"] = ("并表那一笔已经落刀（老表不在 schema 里、盘上也没有老文件）"
                         "⇒ 没有'另一侧'，镜像完整性这一格不再适用")
        return out
    legacy_ids: set[str] = set()
    if state.get("present"):
        try:
            legacy_ids = {str(r.get("concept_id") or "") for r in store.rows(LEGACY_TABLE)}
        except Exception as exc:  # noqa: BLE001
            out["reason"] = f"老表读不成（{type(exc).__name__}: {exc}）⇒ 镜像完整性判不了"
            return out
    out["statements_only"] = sorted(stmt_ids - legacy_ids)
    out["legacy_only"] = sorted(legacy_ids - stmt_ids)
    out["merged"] = sorted(stmt_ids & legacy_ids)
    out["checked"] = True
    return out


def write_concept(tx: Any, *, stmt_id: str, label: str, definition: str = "",
                  aliases: Iterable[str] = (), source_lit_id: str = "", proof_text: str = "",
                  doc_id: str = "", actor: str = "agent-B", mirror: bool = False,
                  origin: str = "", self_authored: bool = False,
                  out: dict[str, Any] | None = None) -> dict[str, Any]:
    """在已开的事务里写一条概念行（经秘书那一笔：新标准那一行 + 可选的老表镜像）。

    为什么要有"事务内"这一档：B 的写入是一笔事务（命题 + 概念 + 依赖一起落，
    `Secretary.record_statement`），而 `upsert` 自己开事务 —— 事务不能嵌套
    （文件锁不可重入）。所以把"写哪两张表、怎么写"收成这一格，
    `upsert`（单独写一条概念）与秘书那一笔都调它，口径只有一处。

    2026-10-26（D14）：这一格不再自己 `tx.upsert("statements", …)`，而是调
    `Secretary.write_concept_row`（见 :func:`_concept_secretary` 的 docstring：
    真机 mp3-r3 的 30 条概念行 `bits` 空、`created_by=agent-B`，就是绕过了它）。
    于是五元位、洗名、概念同一性三件事与秘书那条路是同一份实现，`conceptrows`
    里一份判据都不留。

    `origin` / `self_authored` 原样交给秘书那一层（口径在 :func:`concept_statement`，
    这里不抄第二份）。`proof_text` 保留在签名里只为兼容既有调用点并让那句拒绝留在
    唯一一处：概念行不许带它，传了非空值 ⇒ `ValueError`（本批缺陷一）。

    `mirror=True` 只在老表还在 schema 里时才有意义（落刀之后那张表不存在，
    硬写会以"未知表"整笔失败）⇒ 判断收在秘书那一格（与 `upsert` /
    `upsert_legacy_shaped` 同一口径，调用方不必知道过渡到哪一步了）。
    事务的表声明仍然由调用方负责：要镜像时得声明 `LEGACY_TABLE`，
    统一走 `tables_for_concept_write(...)`。

    `out` 是可选读数口（秘书那一笔把 `label_washed` 与 `concept_identity` 写进去）：
    判词必须能被调用方与判据读到 —— "这一笔问了同一性、判的是哪一个"不该只活在返回值
    那个行 dict 里（那里没有它的一格）。
    """
    return _concept_secretary(tx).write_concept_row(
        tx, stmt_id=stmt_id, label=label, definition=definition, aliases=aliases,
        source_lit_id=source_lit_id, doc_id=doc_id, origin=origin,
        self_authored=self_authored, mirror=mirror, proof_text=proof_text, out=out)


def _concept_secretary(tx: Any) -> Any:
    """这一笔概念写要经的那名秘书（`Secretary.write_concept_row` 的唯一入口）。

    ## 为什么这一层不再自己写 `statements`（2026-10-26，D14）
    真机读数（`projects/mp3-r3`，36 行 statements）：30 条概念行全部
    `created_by=agent-B`、`bits` 空、非平凡度一条记录都没有 —— 因为这一层的三处
    `tx.upsert("statements", …)` 绕过了秘书那一笔。秘书那一笔要做的三件事
    （五元位 / 洗名 `wash_working_name` / 概念同一性 `propositionkey.same_concept`）
    于是全都没跑，而盘上看起来"行都在"（同一批里秘书落的那一条 theorem 有 `bits`，
    正路是好的，坏的是这三个写口）。

    所以写这一格收回秘书：`conceptrows` 里不再有第二份同一性或洗名实现 ——
    判据住在 `Secretary._same_concept_candidate` 与 `secretary.wash_working_name`。

    ## 角色从哪来（`created_by` 必须记真实作者）
    `created_by` 不许折成一个常量：写侧的身份从 `tx.actor`（`agent-B` / `agent-D`…）
    读出来，认不出才是 B（概念行是 B 的写集）。`tx` 是我们唯一拿得到的东西，
    而 `Tx` 只给 `_store` —— 所以这里用 `getattr(tx, "_store", None)` 取根，
    拿不到就退成 `store=None`（秘书照旧能算五元位与同一性，只是不落旁支台账）。

    ## 为什么显式写 `seam=None`（而不是留空）
    这一名秘书从不对命题判词：概念这一档的同一性是确定性的（`propositionkey.same_concept`，
    零模型调用），非平凡度是"不适用"（`NOT_APPLICABLE_KINDS`，同样零调用）。
    所以这里刻意不装缝 —— 装了缝反而让"零调用"变成一句口头承诺而不是结构事实
    （判据 `tests/test_one_concept_is_one_row.py` 与
    `tests/test_concept_rows_have_no_tier.py` 的 (c) 都钉着它）。
    写明 `seam=None` 是给装配面那道护栏看的（`test_no_construction_site_forgets_the_seam_again`）：
    每一处装配点都必须说清"这一名秘书有没有判断面"，而这一处说的是"不需要"。
    将来谁把判命题的活挂到这一名秘书下面，`judge` 会当场报"没有装配模型缝"（可见地失败，
    不是静默退回机械判据）。
    """
    from . import secretary as SEC   # 惰性：不让并表过渡层与秘书互相 choke 在 import 期

    store = getattr(tx, "_store", None)
    root = getattr(store, "root", "") or ""
    actor = str(getattr(tx, "actor", "") or "").strip()
    role = actor.rsplit("-", 1)[-1].upper() if "-" in actor else ""
    if not (len(role) == 1 and role.isalpha()):
        role = "B"
    return SEC.for_role(role, root=root, store=store, seam=None)


def _apply_merge_tombstone(row: dict[str, Any], legacy_row: Mapping[str, Any]) -> None:
    """把老表的墓碑（`merged_into`）落到新标准那一行上：`superseded` + 理由。

    新标准里没有 `merged_into` 这一列，但有语义等价的一档 `superseded`
    （"被后来的一条取代"，且在 `STATEMENT_UNUSABLE_STATUSES` 里 ⇒ 下游不许再当依据）。
    不映射的话，一次真的合并会在新标准那一边完全看不见 —— C 的依赖链与收工门会继续
    把被合并的那条当可用命题，而盘上没有任何地方会响。
    """
    into = str(legacy_row.get("merged_into") or "")
    if not into:
        return
    if into == SUPERSEDED_INTO:
        # 投影的哨兵被原样送了回来（`_to_legacy` 的输出当输入用）⇒ 状态对上了就到此为止：
        # 再写一次理由只会把 `quote_reason` 改成"已并入 superseded"这种没人看得懂的话，
        # 而真相（并入的是哪一条）已经写在那一格里了。
        row["status"] = "superseded"
        return
    why = str(legacy_row.get("merge_reason") or "").strip()
    row["status"] = "superseded"
    row["quote_reason"] = (f"已并入 {into}（同步自老表的 merged_into）"
                           + (f"；{why}" if why else ""))


def sync_from_legacy(tx: Any, legacy_row: Mapping[str, Any], *,
                     actor: str = "agent-B") -> dict[str, Any] | None:
    """把一条老表行同步成新标准那一行（同号）—— 写侧搬运的通用一格。

    为什么需要它（这是过渡期最容易漏的一格）：B 的 pipeline 里有好几处是"改一条老行"
    （合并别名、重算 `related_concepts`、结构重复合并），而不是"新建一条"。只把"新建"
    改成两处同号，那些改动就只落在老表上 ⇒ 新标准那一份悄悄过期，而盘上看起来
    一切正常（两边都有那一行，只是内容不同了）。

    口径（三态）：

    - 老行没有 `concept_id` ⇒ 返回 `None`（调用方点名；不猜号）；
    - 新标准里已有同号行 ⇒ 只更新"从老表推得出来的那几格"
      （`label` / `statement_full` / `aliases` / `source_lit_id`），并保留新标准独有的
      那些（`proof_text` 的良定义性证明、`doc_id`、`bits`、`created_at`、`created_by`）
      —— 那些信息老表里根本没有；定义从"没有"变成"有" ⇒ 状态从 `pending_definition`
      回到 `active`（`D12` 甲说的"定义到了就改回 active 并清掉标记"就是这一支）；
    - 新标准里没有 ⇒ 建一条（空定义自动落待补档）。

    返回写进新标准的那一行 dict（调用方可以拿去当读数）。

    2026-10-26（D14）：这两支（新建 / 改既有）都不再自己 `tx.upsert("statements", …)`，
    而是调 `Secretary.write_concept_row` —— 五元位、洗名、概念同一性三件事因此与秘书
    那条路是同一份实现。这一层只保留"过渡语义"：同号（契约 1）、老表墓碑
    （`merged_into` ⇒ `superseded`）、以及定义到达/清空时那两格状态迁移
    （算好 `status` / `quote_reason` 传进去，由秘书那一格写进同一行）。
    `actor` 只为兼容既有调用点留在签名里：写侧身份现在由秘书从 `tx.actor` 读
    （见 :func:`_concept_secretary`），`created_by` 因此记的是"谁经这一笔写的"。
    """
    cid = str(legacy_row.get("concept_id") or "")
    if not cid:
        return None
    label = str(legacy_row.get("name") or "")
    definition = str(legacy_row.get("definition") or "")
    aliases = [str(a) for a in (legacy_row.get("aliases") or []) if str(a).strip()]
    source_lit = str(legacy_row.get("definition_source_lit_id") or "")
    secretary = _concept_secretary(tx)
    existing = tx.find("statements", stmt_id=cid)
    if existing is None:
        # 老表的墓碑在新标准里也要立起来（第一次同步就碰到一条已经被合并的老行是常事：
        # 迁移历史数据时全是这种）⇒ 先算出那两格，再交给秘书那一笔写。
        tomb: dict[str, Any] = {}
        _apply_merge_tombstone(tomb, legacy_row)
        return secretary.write_concept_row(
            tx, stmt_id=cid, label=label, definition=definition, aliases=aliases,
            source_lit_id=source_lit, status=str(tomb.get("status") or ""),
            quote_reason=str(tomb.get("quote_reason") or ""))
    # 改既有那一行：只动"从老表推得出来的那几格"，新标准独有的那几格由秘书那一格
    # 原样保留（`existing` 传进去，它只改 label / 正文 / aliases / source_lit）。
    status = ""
    quote_reason = ""
    merge_into = str(legacy_row.get("merged_into") or "")
    if merge_into:
        # 老表的墓碑（`merged_into`）在新标准里没有同名列，但有语义等价的一档：
        # `superseded`（"被后来的一条取代"）。不映射的话，一次真的合并会在新标准那一边
        # 完全看不见 —— 下游（C 的链、收工门）会继续把被合并的那条当可用命题。
        tomb = {"status": str(existing.get("status") or ""),
                "quote_reason": str(existing.get("quote_reason") or "")}
        _apply_merge_tombstone(tomb, legacy_row)
        status = str(tomb.get("status") or "")
        quote_reason = str(tomb.get("quote_reason") or "")
    elif definition.strip():
        if str(existing.get("status") or "") == "pending_definition":
            status = "active"
            quote_reason = ("定义已到（同步自老表）⇒ 回到 active；"
                            + str(existing.get("quote_reason") or ""))
    elif str(existing.get("status") or "") == "active":
        # 反向：老表把定义清空了 ⇒ 新标准那一行不能继续假装有定义
        status = "pending_definition"
        quote_reason = f"定义被清空（同步自老表）⇒ 回到 {PENDING_SEARCH}"
    return secretary.write_concept_row(
        tx, stmt_id=cid, label=label, definition=definition, aliases=aliases,
        source_lit_id=source_lit, existing=existing,
        status=status, quote_reason=quote_reason)


def upsert(store: Any, *, label: str, definition: str = "", stmt_id: str = "",
           aliases: Iterable[str] = (), source_lit_id: str = "", proof_text: str = "",
           doc_id: str = "", actor: str = "agent-B") -> dict[str, Any]:
    """写一条概念行：新标准先写，老表照旧镜像（同号）。

    返回 `{"checked", "stmt_id", "mirrored", "tables", "reason"}`。
    老表已退役（`legacy_present` 报 `present=False`）时只写新标准 —— 那一支不是
    "降级"，而是迁移之后的正态；但老文件还在盘上（`stale_file`）时必须在返回值里
    读得到（它装着没搬完的数据）。
    """
    name = str(label or "").strip()
    if not name:
        return {"checked": False, "stmt_id": "", "mirrored": False, "tables": [],
                "reason": "一条概念至少要有 label（名字）—— 没有名字的行谁也认不出它"}
    legacy = legacy_present(store)
    if not legacy.get("checked"):
        return {"checked": False, "stmt_id": "", "mirrored": False, "tables": [],
                "reason": f"老表在不在判不了 ⇒ 这一笔不写（{legacy.get('reason')}）"}
    tables = ["statements"] + ([LEGACY_TABLE] if legacy.get("present") else [])
    try:
        with store.tx(*tables, actor=actor, note="concept_upsert") as tx:
            sid = str(stmt_id or "").strip() or tx.alloc_id(S.TABLES["statements"]["id_kind"])
            write_concept(tx, stmt_id=sid, label=name, definition=definition, aliases=aliases,
                          source_lit_id=source_lit_id, proof_text=proof_text, doc_id=doc_id,
                          actor=actor, mirror=bool(legacy.get("present")))
    except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
        return {"checked": False, "stmt_id": "", "mirrored": False, "tables": [],
                "reason": f"落盘没成（{type(exc).__name__}: {exc}）⇒ 这一笔按'没写成'读"}
    return {"checked": True, "stmt_id": sid, "mirrored": bool(legacy.get("present")),
            "tables": tables, "reason": str(legacy.get("reason") or "")}
