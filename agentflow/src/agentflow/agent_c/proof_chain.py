# -*- coding: utf-8 -*-
"""角色 C 的动作 `proof_chain`：一条成果的最短证明依赖链（业主 2026-10-09）。

> 「想想C怎么找最短依赖链？总归得在记录定理和证明时同样把依赖写清，直到找到最根上的>  依赖（某文献或某无前提依赖的自证定理）为止」> 「B走乙。由于B这边出了多依赖写
法，C的分析需要做适配」> 「别名按乙，毕竟定理也可能有别名」

设计（`draft/97` §12.2 / §14.4d / §15.0）：

- 图：节点 = `statements`（定理/定义/引理/命题/概念）+ `experiments` + `literature`；边 = `dependencies`
（有向：`used_by` → 被依赖的那一端）；- 坏尾巴：`used_by` 里的 `#pN` 读不懂（`#pabc` / `#p0` / 多段 …）时那条边不进索引（不折成
`#p1`，也不折成任何证明号），原串落在 payload 的 `bad_used_by` 并给一条 warning —— 不留痕的
话它会静默消失：链照样 `ok=True`，而一条承重边不在任何一组里；- 组与证明：一条 `used_by` 的依赖图里，同一 `(证明号, path_group)` 内的多条边 = AND
（都要走到根）；不同 `(证明号, path_group)` = OR（任一条走到根即算到根）；不同
`proof_no` 也是 OR。这条规则在每一层都成立（业主 2026-10-22 批准改语义：改前它只在
顶层成立，子命题那一层退化成"全都要"）。读数给每个 `(证明号, 组)` 一条链并挑最短的
那一条（`best_proof_no` / `best_group`）；- 长度：`length` 报这条候选路径的最短可行分支
（组内取最长的边、分支间取最短的分支）；只有全不可行时才报"最深的那条已走前缀"并在
`why` 里写明没有可行分支；- 根只有三种：`lit:`（真实论文，正文里可照引）、无前提自证定理（没有边 +
`evidence_kind="proof"`）、概念（`kind="concept"` 且有定义 —— 2026-10-21 之前要求 
`proof_text == "concept:primitive"`，那个哨兵正是 mp3 那 1143 条污染行的来源，现在按"定义在不在"判，历史行带哨兵照旧是根）。
"没有边又没有证明证据" ⇒ 依赖没写（`unknown`），不是根；- 边界：环 / 超 `max_depth` / 悬空边 / 依赖没写，都按"哪条分支、为什么不可行"
逐条进那一组的 `failures`（`blocking` 说明它是不是那一组不可行的原因；备选分支断了
不影响另一条走到根），`cycle` / `truncated` 只描述真正挡住这条路的那些；跨组汇总按节点
去重（多写一组路径不许把"牵动多少节点"吹大）；- 坏尾巴（`used_by` 的 `#pN` 读不懂）且
没有可用分支 ⇒ 这一趟没查成（`unknown` + `ok=False` + `closed=False`），不许读成
"已经是根"；- 别名：`target` 允许给别名 ⇒ 读数里写 `matched_by: "label" | "alias"`。- 形状（业主 2026-10-22）：payload 另带 `path_shapes` 一列 —— 每条候选路径
（`(证明号, 组)` 一行）的跳数 / 大步骤数 / 无依赖跳变 / 旁挂节点 / 承重边 /
同目标还有几条别的路径（口径逐条写在 `path_shape.py`）。这一列只摆形状、不给分数：
"哪一条更自然"由模型判（`agent_skills.py` 里 C 那一岗的「最自然路径」）。- 前沿（业主 2026-10-22 第二批）：
`max_depth` 是"一批能往回搜多深"，不是"这条路最多几跳"。所以因深度用尽而停下的
那几个节点必须如实交出来：payload 另带 `frontier` / `frontier_checked` /
`frontier_note` 三格，每条给 `{node, from, via_dep_id, proof_no, path_group,
depth_reached, why, next_hint}`，`why` 只取 `depth_limit`。下一批把 `target` 换成
`frontier` 里的节点接着搜，两批的形状交给 `path_shape.join_segments` 核对接缝
（那是核对材料，不是"框架替模型拼链"）。没有前沿时给空列表而不是省略这一格；
三态（没有前沿 / 有前沿 / 没查成）由 `frontier_checked` 分开。
"""
from __future__ import annotations
from pathlib import Path

import json

from ._support import Any, Mapping, S, Sequence, _cfg_int, tool  # noqa: F401
# 依赖的 `used_by` 尾巴（`#pN`）只有一个解析点（`proofloc`）：两份解析意味着
# "台账上是第 2 条证明、读出来是第 1 条"这种错没有任何东西会报（业主 2026-10-22）。
from .. import proofloc as _PL  # noqa: E402
# 历史概念行上那个哨兵（唯一出处是 `migrate_concepts.PRIMITIVE_PROOF`）。
# 读侧仍认它（不动历史）：迁移折出来的老概念、以及 2026-10-21 之前写进来的那些行，
# `proof_text` 就是这一个值。而「写入侧」已经不再写它
# （`conceptrows.concept_statement` 那一格永远是空的）—— 所以新概念"是不是根"
# 改按"定义在不在"判。
from ..migrate_concepts import PRIMITIVE_PROOF as CONCEPT_PRIMITIVE_MARKER  # noqa: E402
# 候选路径的"形状"读数（业主 2026-10-22）：只在这一层之上补形状，改不动
# 下面任何一个 OR / AND 判据（`_or_holds` / `_and_length` 那一族一个字都不碰）。
from .path_shape import path_shapes  # noqa: E402

#: 走到根就算完的两种 `kind`（第三种是 `lit:` 行本身，见 `_DepGraph.is_root`）。
_PROOF_KINDS = ("proof",)


def _split_used_by(used_by: str) -> tuple[str, int, str]:
    """把一条依赖的 `used_by` 拆成 `(命题侧键, 证明号, problem)`，先按前缀分流。

    为什么分流必须在调 `proofloc` 之前（2026-10-22 审计的三条硬约束之一）：
    `doc:` 前缀的 `used_by` 也用 `#`（`doc:0001#claim-3`，见
    `tools.doc_tools.dependencies_for_doc` 的归属判据）—— 那个尾巴是 claim 号、
    不是证明号。不分流就把 `#claim-3` 送进 `proofloc`，于是一条正常的 claim 引用
    被记成"坏尾巴"（`problem` 非空），而坏尾巴的读法是"按 canonical 读" ——
    读数看着没变，台账里已经悄悄多了一类假缺陷。

    `problem` 非空 = 尾巴是坏的（`#p0` / `#pabc` / 多段 …），此时按 canonical（第 1 条）
    读，并把坏尾巴原文交回调用方留痕 —— 绝不抛：读侧拿不到答案比"读成 canonical 并留痕"更坏。
    """
    text = str(used_by or "")
    if text.startswith("doc:"):
        return text, _PL.DEFAULT_PROOF_NO, ""
    head, number, problem = _PL.parse_used_by_checked(text)
    return head, number, problem


def _bad_tail_warnings(graph: "_DepGraph") -> list[str]:
    """坏尾巴的留痕：一条 warning 点名它们不在依赖索引里（原串见 `payload.bad_used_by`）。

    为什么必须有这一条：坏尾巴那条边的索引键是原样串（`000000#pabc`），而
    `groups_of("000000")` 只查得到命题号那一层 —— 于是那条边不会出现在任何一组路径里。
    没有留痕时，一条承重边"消失了"和"本来就没有这条边"在读侧长得一模一样
    （链照样 `ok=True`、没有 warning），而前者会让一条没闭合的证明读成闭合的。
    """
    bad = list(graph.bad_used_by)
    if not bad:
        return []
    shown = "、".join(bad[:3])
    more = "" if len(bad) <= 3 else f" 等 {len(bad)} 条"
    return [f"有 {len(bad)} 条依赖的 `used_by` 尾巴读不懂（{shown}{more}）"
            "⇒ 这些边没有进依赖索引（不会出现在任何一组路径里，也没有被折成 `#p1`）；"
            "原串逐条见 payload 的 `bad_used_by`"]


def _shape_keys(checked: bool, rows: Sequence[Mapping[str, Any]] = (),
                note: str = "", frontier: Sequence[Mapping[str, Any]] = (),
                frontier_note: str = "") -> dict[str, Any]:
    """形状与前沿那几格（`path_shapes*` / `frontier*`）的落法只有这一处。

    为什么要一个函数：五个返回点各写一份字面量，迟早会有一处漏掉 `checked`
    —— 那时"没算成"与"没有候选路径"在同一份 payload 上长得一样，
    而下游读到的是一句口吻确定的"就这么几条"。

    前沿那三格（`frontier` / `frontier_checked` / `frontier_note`）同理：三态
    （没有前沿 / 有前沿 / 没查成）不许折平 —— `frontier=[]` 本身只是"没有"，
    要有 `frontier_checked` 才分得开它是不是"没查"。
    """
    if not checked and not frontier_note:
        frontier_note = f"前沿没算成：{str(note or '这一趟没查成')}"
    return {"path_shapes": [dict(r) for r in rows],
            "path_shapes_checked": bool(checked),
            "path_shapes_note": str(note or ""),
            "frontier": [dict(f) for f in frontier],
            "frontier_checked": bool(checked),
            "frontier_note": str(frontier_note or "")}


# ------------------------------------------------------------------ 组合规则
#
# 依赖图的语义（业主 2026-10-22 批准改语义后的唯一真身）：
#   · 同一个 (证明号, path_group) 内的多条边 = AND（都要走到根）；
#   · 不同 (证明号, path_group) = OR（任一条走到根即算到根）；
#   · 不同 proof_no 也是 OR。
# "到根" = 存在一条 (证明号, path_group) 分支，其组内每条边都到根。
#
# 为什么把这两条规则抬到模块级而不是内联在 `_grow` 里：判据要能把它们
# monkeypatch 成相反的规则，用来证明"顶层与子层用的是同一条规则"不是 docstring 里的
# 一句话（反真空）。内联的 any / all 没法被替换，那种判据只会是空的。


def _or_holds(viables: Sequence[bool]) -> bool:
    """分支之间取 OR：任一条分支可行 ⇒ 这个节点可行。"""
    return any(viables)


def _or_length(lengths: Sequence[int]) -> int:
    """分支之间取 OR：长度取最短那条分支（"最短依赖链"的口径）。"""
    return min(lengths)


def _and_holds(viables: Sequence[bool]) -> bool:
    """同一 (证明号, path_group) 内的多条边取 AND：每条边都要可行。"""
    return all(viables)


def _and_length(lengths: Sequence[int]) -> int:
    """AND 的长度取组内最长的那条边（组里最深的那个前提决定这条路的长度）。"""
    return max(lengths)


class _ProofChain:
    def proof_chain(self, target: str, *, max_depth: int = 6, k: int = 1,
                    weights: Mapping[str, float] | None = None):
        """`target` 的最短证明依赖链（按 `path_group` 分组；返回每组一条 + 挑最短那组）。

        三态（本题最要紧的一处）：读不成不是"没有依赖" ——
        `statements` / `dependencies` 读不出来 ⇒ `ok_=False` + 说清读不成什么；
        没有任何依赖边、而且也不满足"根"的三个条件 ⇒ 那一项进 `unwritten`
        （"依赖没写"），不是"到根了"。
        """
        max_depth = max(1, int(max_depth))
        k = max(1, int(k))
        warnings: list[str] = []
        try:
            stmts = [dict(r) for r in self.store.rows("statements")]
            deps = [dict(r) for r in self.store.rows("dependencies")]
            exps = [dict(r) for r in self.store.rows("experiments")]
            lits = [dict(r) for r in self.store.rows("literature")]
        except Exception as exc:  # noqa: BLE001 —— 读不成 ⇒ 明说，不许当成"没有依赖"
            return self._report(
                "proof_chain", str(target), {"max_depth": max_depth, "k": k},
                summary=(f"依赖图读不成（{type(exc).__name__}: {exc}）⇒ 这一趟没查成"
                         "（不是『这条成果没有依赖』）"),
                payload={"checked": False, "target": str(target), "groups": [],
                         "best_group": None, "groups_total": 0,
                         **_shape_keys(False, (), "依赖图没读成 ⇒ 形状没算成"
                                                    "（不是『没有候选路径』）")},
                ok_=False, error=f"{type(exc).__name__}: {exc}")

        # ---- 目标解析（号 / 别名）—— 业主："别名按乙，毕竟定理也可能有别名"
        node, matched_by = self._resolve_target(str(target), stmts)
        if node is None:
            return self._report(
                "proof_chain", str(target), {"max_depth": max_depth, "k": k},
                summary=(f"{target!r} 在 statements 里找不到（号与别名都试过）⇒ 这一趟没查成"
                         "（不是『它没有依赖』）"),
                payload={"checked": False, "target": str(target), "groups": [],
                         "best_group": None, "groups_total": 0,
                         "matched_by": "",
                         **_shape_keys(False, (), "目标找不到 ⇒ 形状没算成"
                                                   "（不是『没有候选路径』）")},
                ok_=False, error="target_not_found")

        graph = _DepGraph(stmts=stmts, deps=deps, exps=exps, lits=lits,
                          root=getattr(getattr(self, "store", None), "root", None))
        # 坏尾巴留痕（2026-10-22）：读不懂的 `used_by` 尾巴不进 `groups_of`，于是那条边
        # 不在任何一组里 —— 必须在读数里点名它，否则它静默消失。
        warnings.extend(_bad_tail_warnings(graph))
        # 二维展开：每个 `(证明号, 组号)` 是一条候选路径。证明号那一维是"第几条证明"，
        # 组号那一维是"第几条路径"（语义未改：组内 AND / 组间 OR）。
        by_proof = graph.groups_of(node["stmt_id"])
        proof_nos = sorted(by_proof)
        groups_out: list[dict[str, Any]] = []
        for proof_no, by_group in sorted(by_proof.items()):
            for group, edges in sorted(by_group.items()):
                got = graph.walk(node["stmt_id"], group=group, proof_no=proof_no,
                                 edges=edges, max_depth=max_depth)
                groups_out.append(got)
        # 并列（长度相同）按"证明号、组号"升序取前 k 组；`groups_total` 报全部组数
        # （不假装只有 k 组）。单条证明时顺序与改前逐字相同（证明号恒为 1）。
        ranked = sorted(groups_out,
                        key=lambda g: (g["length"] if g["reached"] else 10 ** 6,
                                       g.get("proof_no") or 1, g["group"]))
        best = ranked[0] if ranked and ranked[0]["reached"] else None
        if any(g.get("cycle") for g in groups_out):
            warnings.append("有 " + str(sum(1 for g in groups_out if g.get("cycle")))
                            + " 组依赖里出现环 ⇒ 那一组跳过（不牵连别的组）")
        if any(not g["reached"] for g in groups_out):
            warnings.append("有 " + str(sum(1 for g in groups_out if not g["reached"]))
                            + " 组没走到根（悬空边 / 超深度 / 依赖没写，逐组见 payload）")
        truncated = any(g.get("truncated") for g in groups_out)
        # 「2026-10-17」：「无依赖的 target 自己也要判一次根」 ——
        # 原实现只 walk 依赖组 ⇒ 一条"无前提自证定理/原始概念"被读成
        # "0 组可选路径，没有一组走到根"，而按本仓口径它「本来就是根」（链闭合）。
        target_is_root, target_why = graph.is_root(f"stmt:{node['stmt_id']}")
        bad_used = list(graph.bad_used_by)
        label = node.get("label") or node["stmt_id"]
        # 候选路径的形状读数（业主 2026-10-22）：每条候选路径一行，摆形状、不打分。
        # 它只在 `groups_out` 之上算，改不动上面任何一条 AND / OR 判据。
        shapes = path_shapes(graph, node["stmt_id"], groups_out, max_depth=max_depth)
        # 形状与前沿都走 `.get`：这一层只消费 `path_shapes` 的读数，不许假定它一定
        # 带全那几格 —— 判据里那个"只给最短那条"的替身（反真空）就只交 rows。
        # 没交 `frontier` 那一格时按"没交前沿读数"落（`frontier_checked=False`）：
        # 少了这一格不许被读成"查过了、没有前沿"（那是三态被折平）。
        shape_keys = _shape_keys(bool(shapes.get("checked")) and "frontier" in shapes,
                                 shapes.get("rows") or [],
                                 shapes.get("note") or "",
                                 shapes.get("frontier") or [],
                                 shapes.get("frontier_note") or "")
        if not groups_out and bad_used:
            # 三态（2026-10-22 审计缺陷 11）：坏尾巴是唯一那条依赖时，改前这里读成
            # "没有依赖 ⇒ 已经是根 ⇒ 闭合"。事实是"那条依赖读不懂" —— 既不能说它到根了，
            # 也不能说它没有依赖。没有可用分支 + 读不懂 ⇒ unknown（读数与 ok 一起降级）。
            return self._report(
                "proof_chain", str(target), {"max_depth": max_depth, "k": k},
                summary=(f"{label}：依赖读不懂（{len(bad_used)} 条 `used_by` 尾巴解析不了，"
                         "逐条见 payload 的 `bad_used_by`）⇒ 这一趟没查成（unknown）"),
                payload={"checked": True, "unknown": True, "target": str(target),
                         "matched_by": matched_by, "groups": [], "best_group": None,
                         "groups_total": 0, "best_proof_no": None, "proof_nos": [],
                         "closed": False, "roots": [],
                         "bad_used_by": bad_used,
                         **_shape_keys(False, (), "依赖读不懂（坏尾巴）⇒ 形状没算成"
                                                   "（这一趟没查成）"),
                         "node": {"stmt_id": node["stmt_id"], "kind": node.get("kind"),
                                  "label": node.get("label")}},
                ok_=False, error="dependency_unreadable",
                warnings=_bad_tail_warnings(graph),
            )
        if not groups_out:
            if target_is_root:
                summary = (f"{node.get('label') or node['stmt_id']}：**已经是根**"
                           "（无依赖；按口径：文献／原始概念／有 proof 证据／**经审核的自证定理**）"
                           "⇒ 这一条链**闭合**")
                return self._report(
                    "proof_chain", str(target), {"max_depth": max_depth, "k": k},
                    summary=summary,
                    payload={"checked": True, "target": str(target), "matched_by": matched_by,
                             "groups": [], "best_group": None, "groups_total": 0,
                             "best_proof_no": None, "proof_nos": [],
                             "closed": True, "roots": [node["stmt_id"]],
                             "bad_used_by": list(graph.bad_used_by),
                             **shape_keys,
                             "node": {"stmt_id": node["stmt_id"], "kind": node.get("kind"),
                                      "label": node.get("label")}},
                    warnings=_bad_tail_warnings(graph),
                )
            return self._report(
                "proof_chain", str(target), {"max_depth": max_depth, "k": k},
                summary=(f"{node.get('label') or node['stmt_id']}：没有任何依赖边，而且它"
                         f"**不满足根的条件**（{target_why}）⇒ 依赖没写，不是『到根了』"),
                payload={"checked": True, "target": str(target), "matched_by": matched_by,
                         "groups": [], "best_group": None, "groups_total": 0,
                         "best_proof_no": None, "proof_nos": [],
                         "closed": False, "roots": [], "unwritten": [node["stmt_id"]],
                         "bad_used_by": list(graph.bad_used_by),
                         **shape_keys,
                         "why": target_why},
                ok_=False, error="unwritten_dependencies",
                warnings=_bad_tail_warnings(graph),
            )
        if best is None:
            if bad_used:
                where = (f"全都没有可行分支，而且有 {len(bad_used)} 条 `used_by` 尾巴读不懂"
                         " ⇒ 这一趟没查成（unknown）")
            else:
                where = ("没有一组走到根（没有可行分支；哪条分支、为什么，逐条见 payload "
                         "里每一组的 `failures`）")
        elif len(proof_nos) > 1:
            where = (f"最短是第 {best.get('proof_no') or 1} 条证明的第 {best['group']} 组"
                     f"（{best['length']} 跳）")
        else:
            where = f"最短是第 {best['group']} 组（{best['length']} 跳）"
        summary = (f"{label}："
                   f"{len(groups_out)} 组可选路径，{where}")
        payload = {
            "checked": True, "target": str(target), "matched_by": matched_by,
            "node": {"stmt_id": node["stmt_id"], "kind": node.get("kind"),
                     "label": node.get("label")},
            "groups": groups_out, "groups_total": len(groups_out),
            "best_group": best["group"] if best else None,
            "best_proof_no": (best.get("proof_no") or 1) if best else None,
            # 三态：`closed` 只在一组可行分支真的走到根时为 True；`unknown` 是
            # "读不懂的边还在，答案不成立"（坏尾巴 + 没有可用分支）。
            "closed": best is not None,
            "unknown": best is None and bool(bad_used),
            #: 这条命题的依赖按哪几条证明分的（升序；老数据恒为 `[1]`）
            "proof_nos": proof_nos,
            # 读不懂的 `used_by` 尾巴原串（这些边没有进索引、也没折成任何证明号）
            "bad_used_by": bad_used,
            # 跨组汇总按节点去重（多写一组路径不许把规模读数吹大）
            "unique_nodes": len({h["node"] for g in groups_out for h in g["hops"]}),
            "truncated": truncated,
            # 形状读数（2026-10-22）：每条候选路径一行 —— 跳数 / 大步骤数 /
            # 无依赖跳变 / 旁挂节点 / 承重边 / 同目标还有几条别的路径。
            # 读哪一条"更自然"由模型判，这里不给分数。
            **shape_keys,
        }
        return self._report(
            "proof_chain", str(target),
            {"max_depth": max_depth, "k": k, "weights": dict(weights or {})},
            summary=summary, payload=payload, warnings=warnings, truncated=truncated,
            ok_=not (best is None and bool(bad_used)),
            error="dependency_unreadable" if (best is None and bool(bad_used)) else None)

    # ------------------------------------------------------------ 内部

    def _resolve_target(self, target: str, stmts: Sequence[Mapping[str, Any]]):
        """号优先、别名兜底；返回 `(行, matched_by)`（找不到 ⇒ `(None, "")`）。

        `target` 认两种写法：裸号（`0008`）与带前缀（`stmt:0008`）。带前缀那一支
        是 2026-10-22 第二批补的：`frontier` 交出来的 `node` 就是 `stmt:0008` 这种写法
        （它与 `path_shapes` 的 `start`、`support_edges` 的 `from`/`to` 同一种口径），
        而技能文本写着"下一批把 `target` 换成前沿节点" —— 那一支读不动时，模型照着
        读数做就会得到"目标找不到"，而这条链本来是接得上的。
        """
        t = str(target or "").strip()
        if not t:
            return None, ""
        # `stmt:` 是 5 个字符（s-t-m-t-:）。改前写的是 `t[4:]`，于是 `stmt:0008`
        # 被切成 `:0008` —— 带前缀的目标一律找不到，而"找不到"与"没有依赖"在读数里
        # 长得不一样，却都让下一批接不上。
        bare = t[5:] if t.startswith("stmt:") else t
        for row in stmts:
            if str(row.get("stmt_id") or "") == bare:
                return dict(row), "label" if not t.startswith("stmt:") else "stmt_id"
        from .. import textutil as T

        want = T.normalize(bare)
        for row in stmts:
            if T.normalize(str(row.get("label") or "")) == want:
                return dict(row), "label"
        for row in stmts:
            if any(T.normalize(str(a)) == want for a in (row.get("aliases") or [])):
                return dict(row), "alias"
        return None, ""


class _DepGraph:
    """依赖图（只读快照）：按 `path_group` 分组、递归走到根。"""

    def __init__(self, *, stmts, deps, exps, lits, root: Any = None) -> None:
        self.root = root
        self.stmts = {str(r.get("stmt_id") or ""): dict(r) for r in stmts}
        self.exps = {str(r.get("exp_id") or ""): dict(r) for r in exps}
        self.lits = {str(r.get("lit_id") or ""): dict(r) for r in lits}
        #: 边索引：使用点 → 证明号 → `path_group` → 边。两层键都是这台机器的口径：
        #: 第一层是"这条命题的第几条证明"（`#pN`，不带尾巴 = canonical #p1），
        #: 第二层是"第几条路径"（`path_group`）。
        self.edges: dict[str, dict[int, dict[int, list[dict[str, Any]]]]] = {}
        #: 读不懂的 `used_by` 尾巴（`#pabc` / `#p0` / 多段 …）的原串，按出现顺序去重。
        #: 这些边的索引键是原样串 ⇒ `groups_of(命题号)` 查不到它们（索引口径不变：
        #: 坏尾巴不折成 `#p1`）；留这一格是为了让它们"消失"变成一条可读的读数。
        self.bad_used_by: list[str] = []
        for d in deps:
            used = str(d.get("used_by") or "")
            if not used:
                continue
            # `used_by` 的两种写法都要认：`stmt:0007`（台账里推荐的那种）与裸号 `0007`
            # —— 索引一律按裸号存，查询也按裸号查（一处口径，不分叉）。
            head, proof_no, problem = _split_used_by(used)
            if problem and used not in self.bad_used_by:
                self.bad_used_by.append(used)
            key = head[5:] if head.startswith("stmt:") else head
            try:
                group = int(d.get("path_group") or 1)
            except (TypeError, ValueError):
                group = 1
            for slot in (key,) if key == head else (key, head):
                by_proof = self.edges.setdefault(slot, {})
                by_group = by_proof.setdefault(proof_no, {})
                by_group.setdefault(group, []).append(dict(d))

    def groups_of(self, used_by: str) -> dict[int, dict[int, list[dict[str, Any]]]]:
        """某一个使用点的边：先按证明号分组，再按 `path_group` 分组（二维）。

        第一维（`proof_no`）：一条命题可以有几条证明（`used_by="stmt:0004#p2"`），
        每条证明各自有一份依赖。这里不跨证明合并 —— `#p1` 的第 1 组与 `#p2` 的第 1 组
        是两条不同的路径；合并等于让一份证明借另一份证明的依赖，而"借光"正是这套模型
        最要紧的那条负控。
        第二维（`path_group`）：语义一个字没改 —— 组内 AND（都要走通）、组间 OR（任一到根）。

        `used_by` 的两种写法（`stmt:0007` 与裸号 `0007`）都认 —— 索引里两种都挂了，
        这里再兜一次，免得调用方传了另一种写法就静默拿到空组（"没查到"与"没有依赖"
        必须分得开）。
        """
        key = str(used_by or "")
        bare = key[5:] if key.startswith("stmt:") else key
        # 与索引侧同一个"择一"口径（两种写法挂了同一批边：先按裸号查，查不到才用原样键）
        # —— 两边都取再合并会把同一条边数两遍（那是"规模读数被吹大"的另一种形态）。
        found = self.edges.get(bare) or self.edges.get(key) or {}
        return {no: {group: list(edges) for group, edges in by_group.items()}
                for no, by_group in found.items()}

    def target_of(self, dep: Mapping[str, Any]) -> tuple[str, str]:
        """一条边的被依赖端 ⇒ `(节点号, 种类)`（`stmt:` / `exp:` / `lit:` / `doc:` / `""`）。"""
        if str(dep.get("source_stmt_id") or ""):
            return f"stmt:{dep['source_stmt_id']}", "stmt"
        if str(dep.get("source_experiment_id") or ""):
            return f"exp:{dep['source_experiment_id']}", "exp"
        if str(dep.get("source_lit_id") or ""):
            return f"lit:{dep['source_lit_id']}", "lit"
        if str(dep.get("source_doc_id") or ""):
            return f"doc:{dep['source_doc_id']}", "doc"
        return "", ""

    def _verified_ok(self, stmt_id: str) -> bool:
        """这条命题的「审核台账」里有没有"成立"。

        台账是 `verifications/<命题号>.jsonl`（V 每次审核追加一行，见
        `agentflow/verifications.py`）。读不到 ⇒ 「False」（"没读到"不等于"审过了"）；
        解析不动 ⇒ 也在 False 这一侧 —— 三态纪律：宁可说"没审核"，也不许放一条
        没审过的命题进定理库当根。
        """
        root = getattr(self, "root", None) or getattr(getattr(self, "store", None), "root", None)
        if not root:
            return False
        path = Path(root) / "verifications" / f"{stmt_id}.jsonl"
        if not path.is_file():
            return False
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if "成立" in str(row.get("verdict") or ""):
                    return True
        except Exception:  # noqa: BLE001 - 读/解析不动 ⇒ 不当成"审过了"
            return False
        return False

    def is_root(self, node: str) -> tuple[bool, str]:
        """是不是根（三种之一）；`(False, why)` 里的 `why` 是没到根的原因。"""
        kind, _, bare = node.partition(":")
        if kind == "lit":
            return (True, "") if bare in self.lits else (False, "文献不在册")
        if kind != "stmt":
            return False, f"{kind} 不是可走到根的节点（手稿不入链）"
        row = self.stmts.get(bare)
        if row is None:
            return False, "被依赖的那条命题不在册"
        if not self.groups_of(bare):
            if str(row.get("kind") or "") == "concept":
                # 概念是「定义性的根」（2026-10-21，本批缺陷一的读侧）：它的"证明"那一格
                # 本来就不该有东西。此前这里要求 `proof_text == "concept:primitive"`
                # 才算根 —— 那个哨兵正是 mp3 那 1143 条污染行的来源（写入侧现已不写它），
                # 于是新写的概念会「不再是根」，经概念的依赖链一律读成"依赖没写"。
                # 现在的口径与写入侧一致：概念行有定义 ⇒ 根；历史行带哨兵 ⇒ 照旧是根
                # （不动历史）；定义还没到的待补行（`pending_definition`）⇒ 不是根，
                # 理由说明"定义还没到"，而不是"缺证明"。
                if (str(row.get("proof_text") or "") == CONCEPT_PRIMITIVE_MARKER
                        or str(row.get("statement_full") or "").strip()):
                    return True, ""
                return False, "概念的定义还没到（pending_definition）⇒ 这一条还不是根"
            if str(row.get("evidence_kind") or "") in _PROOF_KINDS:
                return True, ""
            # 「2026-10-17 业主口径」：*"自证定理在审核后要能进定理证明库"* ⇒
            # 一条 `own_result` 的命题，只要「审核台账里记着"成立"」，它就已经是
            # 本库里的「已证定理」 ⇒ 它「可以当根」（后面的定理能引它）。
            # 没审核过的同形命题「不许」当根（三态不许折平）。
            if str(row.get("origin") or "") == "own_result" and self._verified_ok(bare):
                return True, ""
            return False, "依赖没写（没有边，也没有 proof 证据；也不是经审核的自证定理）"
        return False, ""

    def walk(self, start: str, *, group: int, edges, max_depth: int,
             proof_no: int = _PL.DEFAULT_PROOF_NO) -> dict[str, Any]:
        """从 `start` 沿这一条 `(证明号, path_group)` 候选路径走到根 ⇒ 这一组的读数。

        语义（"组内 AND / 组间 OR"在每一层都成立，不只顶层）：

        - 同一条 `(证明号, path_group)` 内的多条边 = AND：每条都要走到根；
        - 不同的 `(证明号, path_group)` = OR：任一条走到根就算到根；
        - 到根 = 存在一条分支，其组内每条边都到根。

        `length` 的口径：这条候选路径的最短可行分支长度 —— 组内取最长的边（AND）、
        分支间取最短的分支（OR）。整条候选路径都不可行时才报"最深的那条已走前缀"，
        并在 `why` 里写明没有可行分支：那个数字不是一条可行的链，不许被当成链长
        （改前它读的是"所有分支里最深的那条"，于是一条 2 跳的链会被报成 3 跳）。

        失败逐条带出（`failures`）：每一条不可行分支一棵
        `{node, proof_no, path_group, status, why, blocking}`。`blocking` 说的是
        "它是不是这条候选路径不可行的原因" —— 备选分支断了不影响另一条走到根，那种
        失败留在读数里，但不许把整条路读成没到根（2026-10-22 审计缺陷 1）。
        """
        hops: list[dict[str, Any]] = []
        unwritten: list[str] = []
        failures: list[dict[str, Any]] = []

        # 环判据按"节点号"比：`proof_chain` 传进来的是裸号（`0001`），而每一条边
        # 的被依赖端是 `stmt:0001` 这种带前缀的写法。两边不归一，环就看不见 ——
        # 一条绕回自己的路径会从"另一条分支"逃出去，读成到根了（判据当场抓住过）。
        start_node = start if ":" in start else f"stmt:{start}"

        def _note_failure(node: str, *, via_proof: int, via_group: int,
                          status: str, why: str) -> None:
            """记一条"哪条分支、为什么不可行"（`blocking` 在最后统一落）。"""
            failures.append({"node": node, "proof_no": via_proof,
                             "path_group": via_group, "status": status, "why": why})

        def _grow(node: str, depth: int, path: Sequence[str],
                  via_proof: int = _PL.DEFAULT_PROOF_NO,
                  via_group: int = _PL.DEFAULT_PROOF_NO) -> tuple[bool, int, dict[str, Any]]:
            """`node` 还能不能走到根 ⇒ `(可行, 这条分支的长度, 说明)`。

            `via_proof` / `via_group` 是"从这个节点被走到的那一层 `(证明号, 组)`"：结构性
            的那几跳（超深度 / 环 / 依赖没写）挂在它们上面。这三样不再用全局 flag 表达 ——
            每个分支把"为什么不可行"带回去，由父层按 AND / OR 组合（改前是一个全局
            `reached`，于是子命题层退化成"任一条分支断了就整组断"）。
            """
            if depth > max_depth:
                hops.append({"node": node, "via_dep_id": "", "path_group": via_group,
                             "proof_no": via_proof, "kind": "", "status": "depth",
                             "why": "超过 max_depth"})
                _note_failure(node, via_proof=via_proof, via_group=via_group,
                              status="depth", why=f"超过 max_depth（{max_depth}）")
                return False, 0, {"status": "depth", "why": "超过 max_depth"}
            ok, why = self.is_root(node)
            if ok:
                return True, 0, {"status": "root", "why": ""}
            if node in path:
                hops.append({"node": node, "via_dep_id": "", "path_group": via_group,
                             "proof_no": via_proof, "kind": "", "status": "cycle",
                             "why": "依赖里出现环"})
                _note_failure(node, via_proof=via_proof, via_group=via_group,
                              status="cycle", why="依赖里出现环")
                return False, 0, {"status": "cycle", "why": "依赖里出现环"}
            sub = self.groups_of(node)
            if not sub:
                unwritten.append(node)
                hops.append({"node": node, "via_dep_id": "", "path_group": via_group,
                             "proof_no": via_proof, "kind": "", "status": "unwritten",
                             "why": why})
                _note_failure(node, via_proof=via_proof, via_group=via_group,
                              status="unwritten", why=why)
                return False, 0, {"status": "unwritten", "why": why}
            # 子命题那一层的二维展开：一条分支 = 一个 `(证明号, path_group)`。
            # 分支之间取 OR（任一条到根即算到根）；改前这里是"全走一遍、任一失败即
            # 整组失败"，顶层与子层因此不是同一条规则。
            branches: list[dict[str, Any]] = []
            for sub_no in sorted(sub):
                for sub_group in sorted(sub[sub_no]):
                    viable, length, detail = _along(
                        node, depth, path, sub_group=sub_group,
                        edges=sub[sub_no][sub_group], via_proof=sub_no)
                    branches.append({"proof_no": sub_no, "path_group": sub_group,
                                     "viable": viable, "length": length,
                                     "why": detail.get("why", "")})
            if _or_holds([item["viable"] for item in branches]):
                viable_lengths = [item["length"] for item in branches if item["viable"]]
                return (True, _or_length(viable_lengths),
                        {"status": "branch", "why": "", "branches": branches})
            return (False, max(item["length"] for item in branches),
                    {"status": "branch", "why": "没有可行分支", "branches": branches})

        def _along(node: str, depth: int, path: Sequence[str], *, sub_group: int,
                   edges: Sequence[Mapping[str, Any]],
                   via_proof: int) -> tuple[bool, int, dict[str, Any]]:
            """同一个 `(证明号, path_group)` 内的多条边 ⇒ AND：每条都要走到根。

            组内 AND 与分支间 OR 是两次不同的组合：这里只做组内那一层（`_and_holds` /
            `_and_length`），分支之间的选择在 `_grow` 里做（`_or_holds` / `_or_length`）。
            """
            flags: list[bool] = []
            lengths: list[int] = []
            whys: list[str] = []
            for dep in edges:
                tgt, kind = self.target_of(dep)
                status = str(dep.get("status") or "")
                hops.append({"node": tgt or node,
                             "via_dep_id": str(dep.get("dep_id") or ""),
                             "path_group": sub_group, "proof_no": via_proof,
                             "kind": kind, "status": status,
                             "why": str(dep.get("status_reason") or "")})
                if status == "dangling":
                    flags.append(False)
                    lengths.append(1)
                    whys.append(f"{tgt or node} 悬空")
                    _note_failure(tgt or node, via_proof=via_proof, via_group=sub_group,
                                  status="dangling",
                                  why=str(dep.get("status_reason") or "这条边悬空"))
                    continue
                if not tgt:
                    flags.append(False)
                    lengths.append(1)
                    whys.append("这条边没有指向任何节点")
                    _note_failure(node, via_proof=via_proof, via_group=sub_group,
                                  status="no_target",
                                  why="这条边没有指向任何节点（三个 source_* 都是空的）")
                    continue
                viable, length, _detail = _grow(tgt, depth + 1, list(path) + [node],
                                                via_proof=via_proof,
                                                via_group=sub_group)
                flags.append(viable)
                lengths.append(1 + length)
            if not flags:
                return True, 0, {"status": "empty", "why": ""}
            return (_and_holds(flags), _and_length(lengths),
                    {"status": "edge", "why": "；".join(whys)})

        viable, length, _detail = _along(start_node, 0, [start_node], sub_group=group,
                                         edges=list(edges), via_proof=proof_no)
        for item in failures:
            item["blocking"] = not viable
        return {"group": group, "proof_no": proof_no, "hops": hops,
                "length": int(length), "reached": bool(viable),
                "truncated": any(item["status"] == "depth" and item["blocking"]
                                 for item in failures),
                "cycle": any(item["status"] == "cycle" and item["blocking"]
                             for item in failures),
                "unwritten": unwritten,
                "failures": failures,
                "why": "" if viable else self._why_not_viable(failures),
                "leaves": sorted({h["node"] for h in hops
                                  if h["status"] not in ("dangling", "depth")})}

    @staticmethod
    def _why_not_viable(failures: Sequence[Mapping[str, Any]]) -> str:
        """把"哪条分支、为什么不可行"拼成一句话（那一组读数与 summary 都用它）。"""
        parts: list[str] = []
        for item in failures:
            if not item.get("blocking"):
                continue
            text = (f"第 {item['proof_no']} 条证明 · 第 {item['path_group']} 组 · "
                    f"{item['node']}：{item['why']}")
            if text not in parts:
                parts.append(text)
        if not parts:
            return "没有可行分支（这一组里没有边）"
        return "没有可行分支：" + "；".join(parts)
