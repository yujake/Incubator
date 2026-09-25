"""跨智能体交互的**冻结契约**（DESIGN-INTERACTIONS.md §1 I1–I7）。

为什么要有这个模块，而不是把逻辑分别写进 A/B/C/D
-------------------------------------------------

上一版最贵的教训有两个，都指向同一个解法：

1. **同一判据写在两处 ⇒ 必然漂移。** `RuleExtractor` 的 docstring 早就警告过
   "两个模块各持一套判据"。"矛盾"这个判据此前只活在 `agent_d` 里；I6 要求
   B 在写入期也问同一个问题。若 B 自己再写一份 `_negated`，那么"写入期认为不矛盾、
   事后 C 认为矛盾"会变成一个**没有报错**的静默分裂。
2. **共享存储 + 多智能体下，最容易死锁的地方是"在事务里调用别人"。**
   I6 的硬约束是：B 在提交事务内问 C "这条新关系与已有的是否矛盾"，
   而 C 要读图。如果 C 去查 store，就是**锁重入**（`filelock` 在同一进程内
   重入同一把锁会直接抛错，在别的实现里则是死锁）。

因此本模块的**全部**函数满足两条铁律：

- **不接收 `Store` / `Tx`，不开事务，不碰文件系统。**（`assert_store_free` 在导入时
  自检签名，防止后来者顺手加一个 `store=` 参数。）
- **纯函数**：同样的入参必得同样的出参，不读时间、不读随机数、不改入参。

各智能体对本模块的用法：

===========  ==========================================================
智能体        用到的契约
===========  ==========================================================
A            ``priority_rank`` / ``order_pending_requests``（I7 取任务）
             ``admit_search_request``（I7 配额闸门，在**调用方的** tx 内执行）
B            ``check_conflict``（I6 写入期闸门，纯函数）
             ``admit_reprocess_request``（I4 重抽取配额）
C            ``check_conflict`` / ``detect_contradictions``（对外**再导出**同一份实现）
             ``structural_duplicate_pairs``（I5 候选）
D            ``detect_contradictions`` / ``adjudicate_contradiction``（I2 闭环）
             ``evidence_relevance``（§3.2 证据就绪判据）
             ``find_equivalent_question``（§3.1 等价类）
===========  ==========================================================

"三态纪律"在本模块的落地
-------------------------

跨智能体返回的每个"空"都必须是三态，见 `DESIGN-INTERACTIONS.md` §3.4。
具体做法：**凡"没查"的情况下返回 `None` 的开关，都不给默认值**，
并且每个结果字典都带一个显式的 ``checked`` 布尔位：

- ``{"checked": False, "conflict": None}`` —— **没检查**（例如调用方没把已有关系传进来）
- ``{"checked": True,  "conflict": False}`` —— **检查过，不冲突**
- ``{"checked": True,  "conflict": True}``  —— **检查过，冲突**

禁止把前两者压成同一个 ``False``：那正是"静默失败比崩溃更危险"的经典形态。
"""

from __future__ import annotations

import inspect
import re
from typing import Any, Iterable, Mapping, Sequence

from . import schema as S

__all__ = [
    "DEFAULTS",
    "CONFLICT_SCOPE",
    "contains",
    "negated",
    "opposite_flags",
    "concept_pair_key",
    "detect_contradictions",
    "adjudicate_contradiction",
    "check_conflict",
    "structural_duplicate_pairs",
    "find_equivalent_question",
    "evidence_relevance",
    "priority_rank",
    "resolve_priority",
    "inflight_requests",
    "order_pending_requests",
    "admit_search_request",
    "admit_reprocess_request",
    "reprocess_counts",
    "next_prefixed_id",
    "assert_store_free",
]

# ---------------------------------------------------------------- 全局默认闸门

#: I2/I3/I4/I7 的所有上限。集中一处，便于"调闸门"时一眼看全。
#:
#: 为什么每个循环都必须有上限：I2 的矛盾闭环是"发现→提问→检索→消化→复核"，
#: 若裁决可以是"仍未解决"，那它天然是一个**不会自己停的循环**。
#: 没有上限的自治循环不是"更自主"，而是"会烧完预算且不给结论"。
DEFAULTS: dict[str, int] = {
    "max_inflight_requests": 20,  # I7 全局在途检索请求上限
    "max_rounds_per_contradiction": 2,  # I2 单条矛盾的追问轮数上限
    "max_contradiction_requests": 10,  # I2 全局矛盾检索请求上限
    "max_gap_requests_per_run": 3,  # I3 单次 gaps 最多直连多少条检索请求
    "max_reprocess_per_relation": 2,  # I4 同一关系最多被重抽取几次
    "question_jaccard_threshold": 0.6,  # §3.1 问题等价类的概念集 Jaccard 阈值
    "structural_duplicate_max_pairs": 200,  # I5 结构重复枚举上限（防 O(n^2) 爆炸）
}


# ---------------------------------------------------------------- 文本判据（唯一权威实现）

#: 一个根本不存在的研究问题。
#:
#: ⚠️ 中文标记**刻意只留"不"**：`"非"` / `"无"` 会命中术语本身
#: （"非交换环"、"无穷"），把"有否定"和"没否定"的两句话都判成带否定，
#: 于是矛盾判据 **永远不触发** —— 而矛盾恰恰是最有价值的发现。
#: 这种"看起来在检测、实际恒为假"的判据比没有判据更坏。
#: 术语级的对立（"可交换" vs "不可交换"）交给 :data:`OPPOSITE_PAIRS` 处理。
NEGATION_MARKERS: tuple[str, ...] = (
    "不", "并非", "未必",
    "not ", "no ", "never", "cannot", "does not", "is not", "without",
)

#: 明确的对立词组 ``(肯定式, 否定式)``。
#: 判定方式是"一句只说肯定式、另一句只说否定式"（见 :func:`detect_contradictions`），
#: 因此 "非交换环"（命中肯定式"交换"但不命中否定式"不交换"）不会误报。
OPPOSITE_PAIRS: tuple[tuple[str, str], ...] = (
    ("可以", "不能"),
    ("成立", "不成立"),
    ("可交换", "不可交换"),
    ("是", "不是"),
    ("abelian", "non-abelian"),
    ("commutative", "non-commutative"),
)


def contains(haystack: str, needle: str) -> bool:
    """按词边界包含判断（ASCII 词用边界，中文直接子串）。

    为什么统一走这里：所有"字面命中"判断都在同一个函数里，将来要调整口径
    （例如加词干化）只需要改一处，不会出现"这两条判据的匹配方式不一样"。
    """
    if not needle:
        return False
    if needle.isascii():
        return re.search(rf"(?<![A-Za-z]){re.escape(needle.strip())}(?![A-Za-z])", haystack, re.IGNORECASE) is not None
    return needle in haystack


def negated(text: str) -> bool:
    """文本里是否出现**否定标记**。

    ⚠️ ASCII 标记按**词边界**匹配。朴素的子串匹配会让 `"no "` 命中
    `"non-commutative"`、`"not "` 命中 `"note "`，于是"有否定"和"没否定"的两句话
    都被判成带否定，矛盾判据恒为假。见 :data:`NEGATION_MARKERS` 的说明。
    """
    return any(contains(text, m) for m in NEGATION_MARKERS)


def opposite_flags(text: str) -> set[tuple[str, str]]:
    """文本命中的"对立词组"（返回 `(肯定式, 否定式)` 元组集合）。

    只按**肯定式**登记：术语本身（"非交换环"）会命中"交换"但不命中
    "不交换"，因此不会被误判成"带否定"。
    """
    return {(a, b) for a, b in OPPOSITE_PAIRS if contains(text, a)}


def concept_pair_key(concept_ids: Sequence[str]) -> str | None:
    """一对概念的规范键。少于 2 个概念返回 ``None``（**显式**表示"这不是一对"）。

    为什么不用行里已存的 `concept_group_key`：那是写入时的产物，历史数据可能缺失
    或不一致。由 `concept_ids` 现场推导才是唯一权威 —— 与 `RelationGraph` 的做法一致。
    """
    cids = sorted({str(c) for c in concept_ids if c})
    if len(cids) < 2:
        return None
    return "|".join(cids)


def _text_of(rel: Mapping[str, Any]) -> str:
    """关系的可判文本：优先 `statement`（抽取出的完整陈述），回退 `description`。"""
    return str(rel.get("statement") or rel.get("description") or "")


# ---------------------------------------------------------------- I2：矛盾检测

#: 检测矛盾时的"同一件事"范围。只比较**概念组完全相同**的关系：
#: 矛盾只可能发生在谈同一件事的两句话之间。
CONFLICT_SCOPE = "same_concept_group"


def detect_contradictions(relations: Sequence[Mapping[str, Any]]) -> list[dict]:
    """找出**互相矛盾**的两条关系。

    判定只用两条可核实的信号，且**两条必须同时成立**才算候选：

    1. 两条关系覆盖同一组概念（``concept_pair_key`` 相同）—— 矛盾只可能发生在
       谈同一件事的两句话之间；
    2. 它们的 ``statement``/``description`` 在"否定标记"或"对立词组"上**冲突**。

    为什么必须这么严：矛盾是**最有价值**的发现（说明文献之间存在真实分歧，
    正是值得研究的地方），但假矛盾会把 D 引向不存在的问题，比漏判更贵。
    所以这里宁可用"字面标记"这种笨办法，也不用"让模型判断语义"。

    ⚠️ **本函数不假装能判定一般语义矛盾。** 它只做可逐字核实的形态，
    并且这一点必须写在报告里 —— 把"字面检测"说成"语义分析"是过度声称。

    ## `strength`：为什么必须把两种信号分开（这是一次真实缺陷的修复）

    | strength | 触发形态 | 可信度 |
    |---|---|---|
    | ``strong`` | 一句**明确断言**肯定是 ``(肯定式)``，另一句**明确断言**了对应的 ``(否定式)``（如 "A 是 B" vs "A 不是 B"） | 高 —— 这是货真价实的对立 |
    | ``weak``   | 一句**出现**否定标记（"不"/"not "…），另一句**没出现** | **低 —— 大量假阳性** |

    这个区分来自一次实测：把 25 条真实论文关系（中文表述）过一遍本函数，
    ``weak`` 信号报了 6 条（24%），而它们**没有一条是矛盾**。根因有两个：

    - ``("是","不是")`` 这一对立词组里，"是"在中文里**无处不在**
      （"等号是公开问题"），于是"甲文有'是'、乙文连'是'都没有"被算成了对立；
    - 裸否定标记在自然语言里也不等于否定命题："**不必**用数值搜索"、"**No**
      numerical output is used as a proof" 都命中否定标记，但它们不是对立主张。

    24% 的报警率意味着 `status="suspect"` 这个标记**失去意义** —— 而
    "假报警比不校验更糟，因为它会训练人忽略告警"。所以：
    **只有 `strong` 允许驱动状态变更；`weak` 只作为线索记录**（见
    :func:`check_conflict` 的 ``conflict`` / ``weak_signals`` 分流）。

    旧实现还有一个真正的**逻辑错误**：条件写的是 ``only_a != only_b``，
    其中 ``only_x = 命中肯定式 and 未命中否定式``。这使得"**提到肯定式**"与
    "**压根没提这个词**"被判成两种对立态度 —— 而后者显然不是否定。
    现在改成"一方明确肯定 **且** 另一方明确否定"才算 strong。
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for i in range(len(relations)):
        for j in range(i + 1, len(relations)):
            a, b = relations[i], relations[j]
            # ⚠️ `concept_pair_key` 是**派生态**，不是输入。
            #
            # 曾经的写法是 `a.get("concept_pair_key")`，直接读行里的字段。这造成了一个
            # **完全静默**的失效：`relations` 表里存的字段名是 `concept_group_key`，
            # 于是对**直接从表里读出来的行**（C 的 `contradictions()`、任何脚本），
            # 本函数恒返回 `[]` —— 不报错、不告警，看起来就像"没有矛盾"。
            # 只有 agent_d 自己悄悄补过 `concept_pair_key` 的那条路径能正常工作。
            #
            # 这正是"缓存/派生态与真源不一致"的教科书形态：派生态一旦被当成输入，
            # 忘了算的那一方就会**静默拿到空结果**。修法是就地推导 ——
            # 与 `RelationGraph.group_counts` 的做法一致（"由 concept_ids 现场推导
            # 才是唯一权威"）。
            key_a = a.get("concept_pair_key") or concept_pair_key([str(c) for c in (a.get("concept_ids") or []) if c])
            key_b = b.get("concept_pair_key") or concept_pair_key([str(c) for c in (b.get("concept_ids") or []) if c])
            if key_a is None or key_a != key_b:
                continue
            if a.get("relation_id") == b.get("relation_id"):
                continue
            ta, tb = _text_of(a), _text_of(b)
            if not ta.strip() or not tb.strip():
                continue

            strong: list[str] = []
            weak: list[str] = []

            # ---- 信号 1（strong）：同一个对立词组，一方明确肯定、另一方明确否定
            for group in sorted(opposite_flags(ta) | opposite_flags(tb)):
                affirm, negform = group
                pos_a = contains(ta, affirm) and not contains(ta, negform)
                neg_a = contains(ta, negform)
                pos_b = contains(tb, affirm) and not contains(tb, negform)
                neg_b = contains(tb, negform)
                if (pos_a and neg_b) or (neg_a and pos_b):
                    strong.append(
                        f"对立表述（{a.get('relation_id')} 与 {b.get('relation_id')} 对「{affirm}／{negform}」"
                        "给出了相反的主张）"
                    )

            # ---- 信号 2（weak）：裸否定标记的出现与否不一致
            neg_a_mark, neg_b_mark = negated(ta), negated(tb)
            if neg_a_mark != neg_b_mark:
                weak.append(
                    f"否定标记出现与否不一致（{a.get('relation_id')} neg={neg_a_mark} / "
                    f"{b.get('relation_id')} neg={neg_b_mark}）—— **这只是线索，不是对立主张**"
                )

            if not strong and not weak:
                continue
            rk = tuple(sorted([str(a.get("relation_id")), str(b.get("relation_id"))]))
            if rk in seen:
                continue
            seen.add(rk)
            out.append(
                {
                    "relation_ids": list(rk),
                    "concept_pair_key": key_a,
                    "detection": "literal",
                    "scope": CONFLICT_SCOPE,
                    #: ``strong`` 才允许驱动状态变更；``weak`` 只是线索。
                    "strength": "strong" if strong else "weak",
                    "strong_signals": strong,
                    "weak_signals": weak,
                    #: 兼容字段：全部信号（strong 在前）。
                    "signals": strong + weak,
                    "a": {"relation_id": a.get("relation_id"), "lit_id": a.get("lit_id"), "statement": _digest(ta)},
                    "b": {"relation_id": b.get("relation_id"), "lit_id": b.get("lit_id"), "statement": _digest(tb)},
                }
            )
    return out


def _digest(text: Any, width: int = 200) -> str:
    """把长文本压成一行摘要（报告里要能读，又不能撑爆）。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"


# ---------------------------------------------------------------- I2：矛盾裁决

#: 裁决词表与理由代码的对应。理由代码是**机器可判定**的（测试与统计靠它），
#: `reason` 是人话。两者必须同时给出 —— 只有人话则无法断言，只有代码则人看不懂。
#:
#: ⚠️ **本词表只覆盖"关系层"的理由**（由 :func:`adjudicate_contradiction` 产出）。
#: 调用方（D）在实现闭环时还会产生**策略层**的码，那些**不属于**本词表，
#: 例如：
#:   - ``weak_only_signal``  —— 只剩 weak 线索 ⇒ 直接判 persistent，不再追问
#:     （策略：矛盾是最强信号，但弱线索不是；继续追问只会烧 A 的产能）
#:   - ``inflight_limit``    —— I7 的在途配额挡住了这一轮的追问请求
#:   - ``budget_exhausted``  —— 全局矛盾请求配额用尽（与"单条轮数用尽"不同）
#: 把它们分开写清楚是为了让"这条矛盾为什么停了"在报告里可复核：
#: **关系层说"还对立"，策略层说"但我们不追了"，这是两句不同的话。**
ADJUDICATION_CODES = (
    "side_removed",  # 一方已不在关系表 / 已非 active ⇒ 争议自然消失
    "side_superseded",  # 一方被判重（duplicate_of 非空）⇒ 由另一方代表
    "no_longer_conflicting",  # 两条都还在，但文本不再对立（重抽取改了陈述）
    "still_conflicting",  # 仍然对立
    "budget_exhausted",  # 仍然对立，但追问轮数用尽
    "new_conflict",  # 原有那条已解决/未决，但冒出了涉及同一条关系的新矛盾
)

#: **策略层**的理由码（由调用方 D 产出，不由本模块产出）。
#: 单列出来，是为了让"本词表里没有它"成为一个显式事实，而不是一个疏漏。
ADJUDICATION_POLICY_CODES = (
    "weak_only_signal",  # 只剩 weak 线索 ⇒ 判 persistent，不再追问
    "inflight_limit",  # I7 在途配额挡住了追问
    "quota_exhausted",  # 全局矛盾请求配额用尽
)


def adjudicate_contradiction(
    original: Mapping[str, Any],
    *,
    scope_relations: Sequence[Mapping[str, Any]],
    rounds: int = 0,
    max_rounds: int | None = None,
) -> dict:
    """对一条矛盾做**复核裁决**（I2 闭环的收敛点）。

    入参
    ----
    original
        一条 :func:`detect_contradictions` 产出的记录（至少要有 ``relation_ids``）。
    scope_relations
        **重新读到的**关系集合。必须包含原来的两条（或显式地不包含 —— 那就是
        "一方已被删除/合并"的证据）。调用方负责给全，本函数不做范围推导。
    rounds
        这条矛盾**已经追问过**几轮（0 表示还没追问过）。
    max_rounds
        轮数上限；``None`` 取 :data:`DEFAULTS`。

    返回
    ----
    ``{"verdict", "code", "reason", "winner_relation_id", "new_relation_ids",
       "checked", "rounds", "rounds_after"}``

    裁决四选一（见 `schema.CONTRADICTION_VERDICTS`）：

    - ``resolved``            —— 争议消失，并指出**哪一方胜出**（或"双方都不再有效"）
    - ``unresolved``          —— 仍然对立，且**还有追问预算** ⇒ 值得再来一轮
    - ``new_contradiction``   —— 冒出涉及原关系的新矛盾（这是**新信息**，不是重复）
    - ``persistent``          —— 仍然对立但预算已尽 ⇒ **停止追问，交给人看**

    ``persistent`` 与 ``unresolved`` 必须分开，否则"该停了"和"继续"会被混为一谈，
    循环要么停不下来，要么在还有信息时过早放弃。

    判定顺序（**这个顺序本身是设计**，不是实现细节）：

    1. 一方消失 / 非 active / 已判重 ⇒ ``resolved``（代码 ``side_removed`` /
       ``side_superseded``）。理由：图里只剩一方，"矛盾"在结构上已不存在。
    2. 两条都还在，但重新检测后不再对立 ⇒ ``resolved``（``no_longer_conflicting``）。
       这是**最有价值的一种解决**：新证据让人把其中一条的陈述改对了。
    3. 仍然对立：
       a. 若出现涉及原关系**的新**矛盾对 ⇒ ``new_contradiction``（新信息优先）；
       b. 否则若 ``rounds >= max_rounds`` ⇒ ``persistent``；
       c. 否则 ⇒ ``unresolved``。
    """
    rel_ids = [str(x) for x in (original.get("relation_ids") or [])]
    if len(rel_ids) != 2:
        raise ValueError(f"矛盾记录必须恰有 2 个 relation_ids，收到 {rel_ids!r}")
    a_id, b_id = rel_ids
    mr = DEFAULTS["max_rounds_per_contradiction"] if max_rounds is None else int(max_rounds)

    by_id: dict[str, Mapping[str, Any]] = {}
    for r in scope_relations:
        rid = r.get("relation_id")
        if rid is not None:
            by_id[str(rid)] = r

    def _alive(rid: str) -> tuple[bool, str]:
        row = by_id.get(rid)
        if row is None:
            return False, "side_removed"
        if str(row.get("status") or "active") != "active":
            return False, "side_removed"
        if row.get("duplicate_of"):
            return False, "side_superseded"
        return True, ""

    alive_a, code_a = _alive(a_id)
    alive_b, code_b = _alive(b_id)

    def _pack(verdict: str, code: str, reason: str, winner: str | None = None, new_ids: Sequence[str] = ()) -> dict:
        return {
            "checked": True,
            "verdict": verdict,
            "code": code,
            "reason": reason,
            "winner_relation_id": winner,
            "new_relation_ids": sorted({str(x) for x in new_ids}),
            "rounds": int(rounds),
            "rounds_after": int(rounds) + 1,
        }

    if not alive_a and not alive_b:
        return _pack(
            "resolved", "side_removed",
            f"争议双方（{a_id}、{b_id}）都已不在有效关系里 —— 该矛盾在图上已不存在",
        )
    if not alive_a or not alive_b:
        loser, code = (a_id, code_a) if not alive_a else (b_id, code_b)
        winner = b_id if not alive_a else a_id
        why = "已从关系表消失或不再 active" if code == "side_removed" else "已判重（duplicate_of 非空）"
        return _pack(
            "resolved", code,
            f"一方（{loser}）{why} ⇒ 由另一方（{winner}）代表该概念组的结论",
            winner=winner,
        )

    now = detect_contradictions(scope_relations)
    still = any(set(x["relation_ids"]) == {a_id, b_id} for x in now)
    new_pairs = [
        x for x in now
        if set(x["relation_ids"]) != {a_id, b_id} and ({a_id, b_id} & set(x["relation_ids"]))
    ]

    if not still:
        return _pack(
            "resolved", "no_longer_conflicting",
            f"{a_id} 与 {b_id} 的陈述在重新读取后不再对立（很可能是定向重抽取改写了其中一条）",
        )

    if new_pairs:
        new_ids = sorted({i for x in new_pairs for i in x["relation_ids"]})
        return _pack(
            "new_contradiction", "new_conflict",
            f"{a_id} 与 {b_id} 仍对立，且新证据引入了涉及它们的新矛盾：{'、'.join(new_ids)}",
            new_ids=new_ids,
        )

    if int(rounds) >= mr:
        return _pack(
            "persistent", "budget_exhausted",
            f"{a_id} 与 {b_id} 已追问 {rounds} 轮（上限 {mr}）仍对立 ⇒ 停止自动追问，交人复核。"
            "这可能是**真实的文献分歧**（本身就有研究价值），而不是检索不足",
        )
    return _pack(
        "unresolved", "still_conflicting",
        f"{a_id} 与 {b_id} 仍对立，尚有追问预算（已 {rounds}/{mr} 轮）",
    )


# ---------------------------------------------------------------- I6：写入期一致性闸门

def check_conflict(
    draft_relation: Mapping[str, Any],
    *,
    existing_relations: Sequence[Mapping[str, Any]] | None,
) -> dict:
    """写入期闸门：**这条待写入的关系与图中已有的关系是否矛盾？**（I6）

    ⚠️ **签名里没有 `store`，这是硬约束，不是风格问题。**

    B 在**自己的事务内**调用本函数。若这里去查 store，`filelock` 会在同一进程内
    重入同一把锁 —— 轻则抛错，重则死锁。共享存储 + 多智能体架构里，
    "在事务里调用别人、别人又去拿锁"是**最容易死锁**的形态，所以必须从签名上写死。
    调用方（B）负责把已有关系**读好传进来**。

    参数
    ----
    existing_relations
        **必须显式传**，可以是空列表，但**不能省略**（没有默认值）。
        传 ``None`` 的语义是"我这次没有能力检查" ⇒ 返回 ``checked=False``。
        这正是三态纪律：**"没检查"绝不允许被读成"检查过、不冲突"**。

    返回
    ----
    ``{"checked", "conflict", "conflicts_with", "reason", "method", "scope", "compared"}``

    - ``checked=False, conflict=None`` —— 没检查（`existing_relations is None`）
    - ``checked=True,  conflict=False`` —— 检查过，范围内没有矛盾
    - ``checked=True,  conflict=True``  —— 检查过，发现矛盾，`conflicts_with` 给出对方 ID

    与 :func:`detect_contradictions` 的关系
    ---------------------------------------
    本函数**复用同一份字面判据**，不另写一套。做法是给草稿补上
    ``concept_pair_key`` 后与范围内的已有关系一起送进 :func:`detect_contradictions`。
    这样"写入期认为不矛盾、事后 C 认为矛盾"这种静默分裂在结构上不可能发生。

    范围（``scope``）：只比较**概念组完全相同**的已有关系。为什么不比较"概念组有交集"的？
    因为那样 "A 是 B"（组 {A,B}）会与 "A 不是 C"（组 {A,C}）被判为矛盾 —— 假矛盾
    比漏判更贵（见 :func:`detect_contradictions` 的说明）。
    """
    if draft_relation is None:
        return {
            "checked": False, "conflict": None, "conflicts_with": [],
            "reason": "草稿为空，未做检查", "method": None, "scope": CONFLICT_SCOPE, "compared": 0, "strength": None,
        }
    if existing_relations is None:
        return {
            "checked": False, "conflict": None, "conflicts_with": [],
            "reason": (
                "调用方未提供已有关系（existing_relations=None）⇒ **没检查**。"
                "注意：这与'检查过、不冲突'是两回事，不得混用"
            ),
            "method": None, "scope": CONFLICT_SCOPE, "compared": 0, "strength": None,
        }

    cids = [str(c) for c in (draft_relation.get("concept_ids") or []) if c]
    key = draft_relation.get("concept_pair_key") or concept_pair_key(cids)
    if key is None:
        return {
            "checked": False, "conflict": None, "conflicts_with": [],
            "reason": "草稿的概念代号组少于 2 个概念，无法确定比较范围 ⇒ 没检查",
            "method": None, "scope": CONFLICT_SCOPE, "compared": 0, "strength": None,
        }
    if not _text_of(draft_relation).strip():
        return {
            "checked": False, "conflict": None, "conflicts_with": [],
            "reason": "草稿没有 statement/description，无可判文本 ⇒ 没检查（不是'不冲突'）",
            "method": None, "scope": CONFLICT_SCOPE, "compared": 0, "strength": None,
        }

    draft = dict(draft_relation)
    draft["concept_pair_key"] = key
    # 草稿还没有 relation_id 时给它一个**不可能与真实 ID 冲突**的占位符，
    # 否则 detect_contradictions 里的 `a.get("relation_id") == b.get("relation_id")`
    # 会因为两边都是 None 而**静默跳过** —— 那会让闸门恒不报冲突。
    draft["relation_id"] = str(draft.get("relation_id") or "")
    if not draft["relation_id"]:
        draft["relation_id"] = "<draft>"

    scope: list[Mapping[str, Any]] = []
    for r in existing_relations:
        rk = r.get("concept_pair_key") or concept_pair_key([str(c) for c in (r.get("concept_ids") or []) if c])
        if rk != key:
            continue
        row = dict(r)
        row["concept_pair_key"] = rk
        scope.append(row)

    found = detect_contradictions(scope + [draft])
    hits: list[dict] = []
    weak_hits: list[dict] = []
    for x in found:
        if draft["relation_id"] not in x["relation_ids"]:
            continue
        other = [i for i in x["relation_ids"] if i != draft["relation_id"]]
        item = {
            "relation_id": other[0] if other else "",
            "strength": x.get("strength"),
            "signals": list(x.get("signals") or []),
            "strong_signals": list(x.get("strong_signals") or []),
            "weak_signals": list(x.get("weak_signals") or []),
        }
        (hits if x.get("strength") == "strong" else weak_hits).append(item)

    # ⚠️ `conflict=True` **只由 strong 信号驱动**。
    #
    # 为什么：I6 的后果是 `status="suspect"`。若让 weak 信号（"否定词出现与否不一致"）
    # 也能置这个状态，实测会有 ~24% 的关系被打上 suspect —— 那时这个标记
    # 就不再指示任何东西，而"假报警比不校验更糟，因为它会训练人忽略告警"。
    # weak 信号并不丢弃：它们进 `weak_signals`，供 C/D 当作**线索**继续查。
    if hits:
        return {
            "checked": True,
            "conflict": True,
            "strength": "strong",
            "conflicts_with": sorted({h["relation_id"] for h in hits if h["relation_id"]}),
            "reason": "；".join(s for h in hits for s in h["strong_signals"]),
            "method": "literal",
            "scope": CONFLICT_SCOPE,
            "compared": len(scope),
            "hits": hits,
            "weak_signals": weak_hits,
        }
    return {
        "checked": True,
        "conflict": False,
        "strength": "none" if not weak_hits else "weak_only",
        "conflicts_with": [],
        "reason": (
            f"在 {len(scope)} 条同概念组的已有关系里未发现与草稿**明确对立**的表述"
            + (
                f"；但有 {len(weak_hits)} 条弱线索（否定词出现与否不一致），它们**不构成矛盾判定**，"
                "只作为线索交给 C/D 继续查"
                if weak_hits
                else ""
            )
            + "（注意：只做了字面判据，不代表语义上一定相容）"
        ),
        "method": "literal",
        "scope": CONFLICT_SCOPE,
        "compared": len(scope),
        "hits": [],
        "weak_signals": weak_hits,
    }


# ---------------------------------------------------------------- I5：结构重复概念

def structural_duplicate_pairs(
    concepts: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
    *,
    max_pairs: int | None = None,
) -> list[dict]:
    """找出**结构上等价**的概念对（I5 候选，由 C 提出、B 决定）。

    结构等价的定义（**两条都要满足**）：

    1. 邻域完全相同（``neighbors(a) == neighbors(b)``，不含彼此）；
    2. 两者之间**没有**直接关系。

    为什么要第 2 条：若 a、b 之间已有关系（例如 "a ≅ b"），那它们**已经被声明为
    两个不同的东西**，此时邻域相同是自然的，合并会抹掉一条真实知识。

    为什么要邻域非空：否则所有孤立概念两两"邻域相同（都是空集）"，
    会产生 O(n²) 个纯噪声候选。

    ⚠️ **结构等价 ≠ 同义**。两个不同的概念完全可能都连着同一批邻居。
    因此本函数**只提出候选**，并且额外给出 ``name_evidence``：

    - ``"same_normalized_name"`` / ``"alias"`` —— 名字侧也有证据 ⇒ ``proposal="merge"``
    - ``"none"`` —— 只有结构证据 ⇒ ``proposal="review"``，
      且 ``reason`` 里写明"**不得据此合并**"。合并决定权在 B，B 必须给理由。

    这个"只有结构证据就不给 merge 建议"的设计是刻意的：I5 的验收里有一条
    **负控**——"邻域相同但显然不同的概念"必须被 **B 拒绝**。若本函数在这里
    就把 ``proposal`` 给了 ``merge``，负控就只能靠 B 的自觉，而自觉不是可判定的。
    """
    mp = DEFAULTS["structural_duplicate_max_pairs"] if max_pairs is None else int(max_pairs)
    # ---- 邻域
    adj: dict[str, set[str]] = {}
    shared_rels: dict[str, set[str]] = {}
    for c in concepts:
        cid = str(c.get("concept_id") or "")
        if cid:
            adj.setdefault(cid, set())
            shared_rels.setdefault(cid, set())
    for r in relations:
        rid = str(r.get("relation_id") or "")
        cids = sorted({str(x) for x in (r.get("concept_ids") or []) if x})
        if len(cids) < 2:
            continue
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                x, y = cids[i], cids[j]
                adj.setdefault(x, set()).add(y)
                adj.setdefault(y, set()).add(x)
        for cid in cids:
            shared_rels.setdefault(cid, set()).add(rid)

    by_id = {str(c.get("concept_id")): c for c in concepts if c.get("concept_id")}
    ids = sorted(by_id)
    out: list[dict] = []
    truncated = False
    for i in range(len(ids)):
        if truncated:
            break
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            na, nb = adj.get(a, set()), adj.get(b, set())
            if not na:
                continue  # 孤立概念不参与（见 docstring）
            # ⚠️ **"两者已有直接关系"必须在邻域比较之前判**。
            #
            # 这一行原先写在 `na != nb` **之后**，于是它**永远不执行**：
            # 无向图的邻接表由"每条关系的概念两两展开"建立、不含自环，
            # 所以 `na == nb ∧ b ∈ na` ⇒ `b ∈ nb` ⇒ b 有自环，矛盾。
            # 也就是说"有直接关系"这个情形**已经被 `na != nb` 排除了**，
            # 那行 `continue` 只是看起来在起作用 —— 而"看起来在起作用的死代码"
            # 会让后来者以为负控靠它，从而在重构时把真正的防线拆掉。
            # 现在把它提到前面：它**可达**，而且它正是 `na != nb` 成立的原因，
            # 于是代码与 docstring 的第 2 条要求一一对应。
            if b in na or a in nb:
                continue  # 已被声明为两个不同的东西 ⇒ 合并会抹掉一条真实知识
            if na != nb:
                continue
            name_ev = _name_evidence(by_id.get(a, {}), by_id.get(b, {}))
            common_rels = sorted(shared_rels.get(a, set()) & shared_rels.get(b, set()))
            out.append(
                {
                    "concept_ids": [a, b],
                    "concept_names": [str(by_id[a].get("name") or ""), str(by_id[b].get("name") or "")],
                    "neighborhood_size": len(na),
                    "neighbors": sorted(na),
                    "neighbor_names": [str((by_id.get(n) or {}).get("name") or f"(未知 {n})") for n in sorted(na)],
                    "shared_relation_ids": common_rels,
                    "name_evidence": name_ev,
                    "proposal": "merge" if name_ev != "none" else "review",
                    "reason": (
                        f"邻域完全相同（{len(na)} 个共同邻居："
                        f"{'、'.join(str((by_id.get(n) or {}).get('name') or n) for n in sorted(na))}），"
                        f"且两者之间无直接关系"
                        + (
                            f"；名字侧证据：{_NAME_EVIDENCE_TEXT[name_ev]}"
                            if name_ev != "none"
                            else "；**但名字规范化后不同、也无别名交集 ⇒ 只有结构证据，不得据此合并**"
                            "（结构等价 ≠ 同义：两个不同的概念完全可能连着同一批邻居）"
                        )
                    ),
                    "detected_by": "agent-C",
                }
            )
            if len(out) >= mp:
                truncated = True
                break
    if truncated:
        # 截断必须**说出来**，否则"只找到这些"与"还有但没枚举"无法区分。
        for item in out:
            item["truncated"] = True
        out.append(
            {
                "concept_ids": [],
                "truncated": True,
                "proposal": "review",
                "reason": f"结构重复枚举触及 max_pairs={mp} 被截断：**不能据此断言'没有更多结构重复'**",
                "detected_by": "agent-C",
                "is_truncation_notice": True,
            }
        )
    return out


_NAME_EVIDENCE_TEXT = {
    "same_normalized_name": "规范化名字完全相同",
    "alias": "一方的名字出现在另一方的别名里",
    "none": "无名字证据",
}


def _name_evidence(a: Mapping[str, Any], b: Mapping[str, Any]) -> str:
    """名字侧的独立证据。**只用名字，不看结构** —— 两路证据必须独立才有意义。

    规范化走 :func:`textutil.normalize`（= `dedup.find_concept` 用的同一个），
    理由同本模块顶部：**同一判据不能有两份实现**。若这里自己写一套小写化规则，
    就会出现"B 的判重认为两个概念同名、C 的结构重复候选认为不同名"的静默分裂。
    """
    from . import textutil as T

    def _forms(row: Mapping[str, Any]) -> set[str]:
        out = {str(row.get("normalized_name") or "") or T.normalize(str(row.get("name") or ""))}
        out |= {T.normalize(str(x)) for x in (row.get("aliases") or [])}
        out.discard("")
        return out

    fa, fb = _forms(a), _forms(b)
    na = str(a.get("normalized_name") or "") or T.normalize(str(a.get("name") or ""))
    nb = str(b.get("normalized_name") or "") or T.normalize(str(b.get("name") or ""))
    if na and na == nb:
        return "same_normalized_name"
    if fa & fb:
        return "alias"
    return "none"


# ---------------------------------------------------------------- §3.1 问题等价类

def find_equivalent_question(
    existing_questions: Sequence[Mapping[str, Any]],
    *,
    concept_ids: Sequence[str],
    relation_ids: Sequence[str],
    jaccard_threshold: float | None = None,
) -> dict | None:
    """在已有问题里找一个**与候选问题等价**的，避免同一件事被研究两次（§3.1）。

    等价判据（满足其一即可）：

    - **共享 ≥1 个关系代号** —— 关系代号是"引用了哪条知识"，共享即同一件事。
      这是主判据，因为它是**精确**的。
    - **概念集合的 Jaccard ≥ 阈值**（默认 0.6）—— 兜底，覆盖"同一批概念、
      但报告里引用的关系条目不同"的情况。

    返回 ``{"matched": True, "question_id", "by", "detail", "similarity"}``
    或 ``{"matched": False, "by": None, ...}``（**检查过、没有**，不是"没检查"）。

    为什么需要它：上一版 D 的 `ingest` 只按 `(kind, 排序后的 rel_ids)` 去重，
    于是**同一份报告里两条不同链条支持同一个研究点**时会生成两个问题。
    （实测 4 条问题里只有 2 条是不同的。）去重键太窄，等价类才够。
    """
    thr = DEFAULTS["question_jaccard_threshold"] if jaccard_threshold is None else float(jaccard_threshold)
    want_rels = {str(x) for x in relation_ids if x}
    want_cs = {str(x) for x in concept_ids if x}
    best: dict | None = None
    for q in existing_questions:
        qrels = {str(x) for x in (q.get("related_relation_ids") or []) if x}
        qcs = {str(x) for x in (q.get("related_concept_ids") or []) if x}
        shared = sorted(want_rels & qrels)
        if shared:
            cand = {
                "matched": True,
                "question_id": str(q.get("question_id") or ""),
                "by": "shared_relation_ids",
                "detail": f"与已有问题共享关系代号 {'、'.join(shared)}",
                "similarity": 1.0,
                "shared": shared,
                "existing_status": str(q.get("status") or ""),
                "existing_question": str(q.get("question") or ""),
            }
            return cand
        union = want_cs | qcs
        jac = (len(want_cs & qcs) / len(union)) if union else 0.0
        if want_cs and jac >= thr:
            cand = {
                "matched": True,
                "question_id": str(q.get("question_id") or ""),
                "by": "concept_jaccard",
                "detail": f"概念集合 Jaccard={jac:.2f} ≥ 阈值 {thr:.2f}",
                "similarity": round(jac, 4),
                "shared": sorted(want_cs & qcs),
                "existing_status": str(q.get("status") or ""),
                "existing_question": str(q.get("question") or ""),
            }
            if best is None or cand["similarity"] > best["similarity"]:
                best = cand
    if best is not None:
        return best
    return {
        "matched": False,
        "question_id": None,
        "by": None,
        "detail": (
            f"已检查 {len(existing_questions)} 个已有问题，无共享关系代号，"
            f"概念集 Jaccard 均 < {thr:.2f} ⇒ 这是一个**新的**研究点"
        ),
        "similarity": 0.0,
        "shared": [],
    }


# ---------------------------------------------------------------- §3.2 证据就绪判据

def evidence_relevance(
    question: Mapping[str, Any],
    *,
    new_relations: Sequence[Mapping[str, Any]] | None,
) -> dict:
    """新到的证据**是否真的回答了那个问题**（§3.2）。

    上一版 `poll` 的判据是"请求 done 且其文献都 processed"。那只说明
    "**消化完了**"，不说明"这些新证据真的回答了那个问题"。后果是：一个查不到
    东西的问题会**反复**触发同一件事的检索，把 A 的产能烧在同一个空洞上。

    本函数只做**可判定的**那一层：新落库的关系里，有没有任何一条落在该问题的
    `related_concept_ids` 上？

    - ``new_relations=None`` ⇒ ``checked=False``（**没查**，不是"不相关"）
    - 有落点 ⇒ ``relevant``，给出 `relevant_relation_ids` / `relevant_lit_ids`
    - 无落点 ⇒ ``irrelevant``，并给出 `advice="lower_priority"`

    ⚠️ **它不判定"是否足够回答"** —— 那是语义问题，本函数不声称能判。
    它只回答"这批新证据与这个问题有没有交集"，而这一层恰恰是能判定的那一层。
    """
    if new_relations is None:
        return {
            "checked": False,
            "relevance": None,
            "relevant_relation_ids": [],
            "relevant_lit_ids": [],
            "advice": "none",
            "reason": "未提供新关系（new_relations=None）⇒ **没查**，不得读成'不相关'",
        }
    want = {str(x) for x in (question.get("related_concept_ids") or []) if x}
    rel_ids: list[str] = []
    lit_ids: set[str] = set()
    for r in new_relations:
        cids = {str(x) for x in (r.get("concept_ids") or []) if x}
        hit = want & cids
        if not hit and str(r.get("lit_id") or "") and str(r.get("lit_id")) in {
            str(x) for x in (question.get("evidence_lit_ids") or [])
        }:
            # 该文献已被认定是这个问题的证据来源 ⇒ 它的新关系也算相关
            hit = cids
        if not hit:
            continue
        rid = str(r.get("relation_id") or "")
        if rid:
            rel_ids.append(rid)
        lid = str(r.get("lit_id") or "")
        if lid:
            lit_ids.add(lid)
    rel_ids = sorted(set(rel_ids))
    if rel_ids:
        return {
            "checked": True,
            "relevance": "relevant",
            "relevant_relation_ids": rel_ids,
            "relevant_lit_ids": sorted(lit_ids),
            "advice": "proceed",
            "reason": (
                f"新关系里有 {len(rel_ids)} 条落在该问题的概念集上"
                f"（{'、'.join(rel_ids)}）⇒ 证据与问题相关，可以进入研究"
            ),
        }
    return {
        "checked": True,
        "relevance": "irrelevant",
        "relevant_relation_ids": [],
        "relevant_lit_ids": [],
        "advice": "lower_priority",
        "reason": (
            f"新到 {len(new_relations)} 条关系，但**没有一条**落在该问题的概念集"
            f"（{'、'.join(sorted(want)) or '空'}）上 ⇒ 这批证据与该问题无关。"
            "应降低该问题优先级，避免反复检索同一个空洞"
        ),
    }


# ---------------------------------------------------------------- I7：优先级与配额

def priority_rank(priority: Any) -> int:
    """优先级的可比较次序。未知/缺失一律落到 ``low`` —— 宁可排后面，不要插队。"""
    return S.PRIORITY_RANK.get(str(priority or ""), S.PRIORITY_RANK["low"])


def resolve_priority(submitted_by: str, explicit: Any = None) -> tuple[str, str]:
    """定优先级。返回 ``(priority, why)``。

    规则：显式给出的优先（校验合法后直接用）；否则查
    `schema.SUBMITTER_DEFAULT_PRIORITY`；再否则 ``low``。
    **返回 ``why`` 是刻意的**：让"为什么这条排前面"在日志里可查，
    而不是一个没人知道来源的字段值。
    """
    if explicit is not None:
        p = str(explicit)
        if p in S.PRIORITIES:
            return p, f"由提交方显式指定为 {p}"
        return S.SUBMITTER_DEFAULT_PRIORITY.get(submitted_by, "low"), (
            f"提交方指定的优先级 {explicit!r} 非法（应为 {S.PRIORITIES}）⇒ 回退到默认"
        )
    if submitted_by in S.SUBMITTER_DEFAULT_PRIORITY:
        return S.SUBMITTER_DEFAULT_PRIORITY[submitted_by], f"按提交方 {submitted_by} 的默认优先级"
    return "low", f"提交方 {submitted_by} 未登记默认优先级 ⇒ 落到 low（不让陌生来源插队）"


def inflight_requests(rows: Sequence[Mapping[str, Any]]) -> list[dict]:
    """"在途"的定义：``done`` 为假。**只有这一个口径。**

    为什么必须写成一个函数：一旦 A 的配额计算和 D 的"我还在等几件事"用了
    不同口径（比如一边把 `outcome=gave_up` 也算在途），配额就会静默失准。
    """
    return [dict(r) for r in rows if not r.get("done")]


def order_pending_requests(
    rows: Sequence[Mapping[str, Any]],
    *,
    now: str | None = None,
) -> list[dict]:
    """把待办检索请求排成 A 应取的顺序（I7）。

    排序键：``(优先级次序, 是否"有人正持有有效租约", 提交时间, request_id)``。

    ## 第二档的精确语义（曾与文档不一致，已按实现改正）

    第二档是 **"现在能不能立刻取走"**（0）还是 **"有人正持有有效租约"**（1）。
    **空租约与已过期租约都算"能立刻取走"**，落在同一个桶里，由后面的
    timestamp / request_id 决定先后。

    为什么不做成"已过期的排在全新之前"：A 的 `_claim` **本来就会跳过**
    "有人正持有有效租约"的行，所以那一档对 A 的实际取任务顺序没有影响；
    而把空租约与已过期拆成两个桶，会与 A 的**退避租约**机制打架 ——
    失败重试时 A 只留一个未来的 `lease_until`、把 `claimed_by` 置空，
    那时的行在语义上就是"可以再取"，把它排到全新任务后面会让退避机制
    以另一种方式复活。**当前实现保证的是"死掉的租约不会被饿死"**，
    这是设计真正担心的事；"过期优先于全新"则不是（详见 A 子任务的实测报告）。

    - **优先级次序**优先 —— 这是 I7 的全部意义。
    - 其次是"可立刻取走"先于"有人正持有有效租约"。
    - 再次是提交时间（同级 FIFO，需求里明说）。
    - 最后用 request_id 兜底，保证**全序**（否则排序不稳定，"先 high 后 medium"
      这类断言会随机失败）。

    ``now`` 只在测试里显式传入；生产路径用 `store.lease_expired` 的同一判据 ——
    这里为避免引入时间依赖，把"租约是否过期"作为**调用方已算好的布尔**读入：
    行里若有 ``_lease_expired`` 键就用它，否则按 `lease_until` 是否为空判断
    （空租约 = 无人持有 = 可立刻取走）。
    """
    from .store import lease_expired  # 只借这一个纯函数，不碰 Store 实例

    def key(r: Mapping[str, Any]) -> tuple:
        exp = r.get("_lease_expired")
        if exp is None:
            lu = r.get("lease_until")
            exp = True if not lu else bool(lease_expired(str(lu)))
        return (
            priority_rank(r.get("priority")),
            0 if exp else 1,
            str(r.get("timestamp") or ""),
            str(r.get("request_id") or ""),
        )

    return sorted((dict(r) for r in rows if not r.get("done")), key=key)


def admit_search_request(
    existing_rows: Sequence[Mapping[str, Any]],
    *,
    submitted_by: str,
    explicit_priority: Any = None,
    for_question_id: str | None = None,
    max_inflight: int | None = None,
) -> dict:
    """I7 的**准入闸门**（在调用方的 tx 内执行，自己不加锁）。

    做两件事：定优先级 + 拒绝超额。

    为什么要**拒绝**而不是"无限排队"：队列无上限时，提交方（尤其是循环里的 D）
    永远不会感到压力，于是"知识不足就提问"会退化成"每轮都问"，
    而 A 的产能是固定的 —— 结果是**所有**请求都变慢，包括最关键的那条矛盾。
    显式拒绝会把压力**传导回提交方**，让它决定"这条到底值不值得问"。

    返回 ``{"admitted", "reason", "priority", "priority_why", "inflight", "limit"}``。
    ``admitted=False`` 时**不产生任何写入**（调用方据此跳过）。
    """
    limit = DEFAULTS["max_inflight_requests"] if max_inflight is None else int(max_inflight)
    inflight = inflight_requests(existing_rows)
    prio, why = resolve_priority(submitted_by, explicit_priority)
    if len(inflight) >= limit:
        return {
            "admitted": False,
            "reason": (
                f"在途检索请求已达上限 {len(inflight)}/{limit} ⇒ **拒绝新请求**"
                "（而不是无限排队：无上限的队列会让最关键的那条矛盾也一起变慢）"
            ),
            "priority": prio,
            "priority_why": why,
            "inflight": len(inflight),
            "limit": limit,
            "for_question_id": for_question_id,
        }
    return {
        "admitted": True,
        "reason": f"在途 {len(inflight)}/{limit}，允许提交",
        "priority": prio,
        "priority_why": why,
        "inflight": len(inflight),
        "limit": limit,
        "for_question_id": for_question_id,
    }


def reprocess_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """每个关系已被**受理**（pending + done）的重抽取次数。

    ⚠️ **被拒的（``status="rejected"``）不计入**：否则闸门会用"我拒绝过"
    来证明"我做过了"，拒绝两次之后一个**从未被处理过**的关系就再也进不来了。
    这是"计数口径"必须写清楚的典型例子。
    """
    out: dict[str, int] = {}
    for r in rows:
        if str(r.get("status") or "") == "rejected":
            continue
        for rid in r.get("relation_ids") or []:
            k = str(rid)
            out[k] = out.get(k, 0) + 1
    return out


def admit_reprocess_request(
    existing_rows: Sequence[Mapping[str, Any]],
    *,
    relation_ids: Sequence[str],
    reason: str,
    max_per_relation: int | None = None,
) -> dict:
    """I4 的准入闸门：同一关系最多被重抽取 ``max_per_relation`` 次。

    为什么必须有：重抽取会**改数据**。没有上限时，"引文不可核实"这个信号
    会让 B 反复回同一页做同一件事 —— 每轮都失败、每轮都重来，
    而每次都会写一行新记录。上限把"无效努力"变成一次明确的拒绝。

    ## 调用口径（**必须遵守，否则上限会静默减半**）

    1. ``existing_rows`` 是 ``reprocess_requests`` 表的**当前全部行**。
    2. **调用方必须先排除"正在受理的那一行"**：`reprocess_counts` 的口径是
       `pending + done`，而 B 是在请求**已经在表里**时才复核配额 ——
       不排除自身就会把同一次受理数两次，于是 `max_per_relation=2` 实际只允许 1 次。
       这不会报任何错，只会让上限悄悄变成一半。
    3. **顺序前提**：提交方必须**先调本闸门、再插入请求行**。
       若反过来（先插请求再申请），该行已经计入 `reprocess_counts`，语义就变了。
    """
    lim = DEFAULTS["max_reprocess_per_relation"] if max_per_relation is None else int(max_per_relation)
    rids = sorted({str(x) for x in relation_ids if x})
    if not rids:
        return {"admitted": False, "reason": "relation_ids 为空 ⇒ **无目标的重抽取会退化成全量重抽**，拒绝", "blocked": []}
    if reason not in S.REPROCESS_REASONS:
        return {"admitted": False, "reason": f"reason 必须是 {S.REPROCESS_REASONS} 之一，收到 {reason!r}", "blocked": []}
    counts = reprocess_counts(existing_rows)
    blocked = [r for r in rids if counts.get(r, 0) >= lim]
    if blocked:
        return {
            "admitted": False,
            "reason": (
                f"关系 {'、'.join(blocked)} 的重抽取次数已达上限 {lim} ⇒ 拒绝"
                "（反复重做同一件失败的事只会产生更多无效记录，不产生信息）"
            ),
            "blocked": blocked,
            "counts": counts,
        }
    return {"admitted": True, "reason": f"未超上限 {lim}", "blocked": [], "counts": counts}


def next_prefixed_id(rows: Sequence[Mapping[str, Any]], field: str, prefix: str) -> str:
    """生成 ``<prefix>-NNNN`` 形式的 ID（用于 ``r-`` / ``p-`` 这类非 4 位空间）。

    与 4 位 ID 空间分开：``search_requests`` / ``reprocess_requests`` 是
    **过程记录**（可以很多），而概念/关系/文献是**知识实体**（4 位够用且要短）。
    混用会让 4 位空间被过程记录吃掉。

    取 ``max+1`` 并跳过已占用的号 —— 不记录计数器，因此**删除中间行不会导致撞号**。

    ## ⚠️ `prefix` **不带**连接号（文档与实现曾经不一致）

    曾经的 docstring 写"生成 ``<prefix>-NNNN``"，读起来像是**要把连接号一起传**。
    按那个读法传 ``prefix="r-"`` 会得到 ``"r--0001"`` —— 而它**能通过
    `SearchRequest.validate`**（那里只查非空），于是**静默落库**；
    更糟的是下一轮 `startswith("r-")`/数字解析匹配不上，取号永远从 1 重来，
    直到与已有行撞号。这是一次真实的"文档与实现对不上"（与 `Tx.mark_dirty`
    曾经那次同族）。

    现在：docstring 说清 `prefix="r"`，并且**在这里 fail-closed 拒绝含分隔符的前缀** ——
    与其让一个写错的参数静默产生坏 ID，不如当场炸。
    """
    if not prefix or not prefix.isalnum():
        raise ValueError(
            f"prefix 必须是纯字母数字（不带连接号，例如 'r' / 'p'），收到 {prefix!r}。"
            "历史上这里接受过 'r-' 并产出 'r--0001'，而它能通过 schema 校验静默落库"
        )
    n = 0
    for r in rows:
        v = str(r.get(field) or "")
        if v.startswith(prefix + "-") and v[len(prefix) + 1 :].isdigit():
            n = max(n, int(v[len(prefix) + 1 :]))
    used = {str(r.get(field) or "") for r in rows}
    n += 1
    while f"{prefix}-{n:04d}" in used:
        n += 1
    return f"{prefix}-{n:04d}"


# ---------------------------------------------------------------- 导入期自检

def assert_store_free(*funcs: Any) -> None:
    """断言给定函数（默认本模块全部公开函数）**签名里没有 store/tx**。

    为什么要在导入期做：I6 的死锁约束是"B 在事务内调用 C 的纯函数"。
    这条约束最容易在**后续维护**里被破坏 —— 有人为了图方便加一个
    ``store=None`` 参数，于是三年后某次调用就在事务里重入了锁。
    把它变成导入期断言，破坏者会在**第一次 import 时**就炸掉，而不是在
    生产环境里偶发死锁。

    ⚠️ 例外：:func:`order_pending_requests` 内部 `from .store import lease_expired`
    只是为了复用**同一个**租约判据（纯函数，无锁）。它不接收 Store 实例，
    因此不违反本约束 —— 约束针对的是"接收 Store/Tx 并去拿锁"。
    """
    targets = funcs or tuple(
        globals()[name] for name in __all__ if callable(globals().get(name))
    )
    bad: list[str] = []
    for fn in targets:
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):  # pragma: no cover - 内建函数没有签名
            continue
        for pname in sig.parameters:
            if pname.lower() in ("store", "tx", "st"):
                bad.append(f"{getattr(fn, '__name__', fn)}({pname})")
    if bad:
        raise AssertionError(
            "interactions 模块的函数不得接收 Store/Tx（I6 要求它们是无锁纯函数，"
            "否则 B 在自己的事务内调用会造成锁重入/死锁）：" + "、".join(bad)
        )


assert_store_free()
