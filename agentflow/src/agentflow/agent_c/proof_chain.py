# -*- coding: utf-8 -*-
"""角色 C 的动作 `proof_chain`：一条成果的最短证明依赖链（业主 2026-10-09）。

> 「想想C怎么找最短依赖链？总归得在记录定理和证明时同样把依赖写清，直到找到最根上的>  依赖（某文献或某无前提依赖的自证定理）为止」> 「B走乙。由于B这边出了多依赖写
法，C的分析需要做适配」> 「别名按乙，毕竟定理也可能有别名」

设计（`draft/97` §12.2 / §14.4d / §15.0）：

- 图：节点 = `statements`（定理/定义/引理/命题/概念）+ `experiments` + `literature`；边 = `dependencies`
（有向：`used_by` → 被依赖的那一端）；- 组：同一 `used_by` + 同一 `path_group` = 一条路径（组内 AND：都要）；不同组 = 可选
路径（组间 OR：任一） ⇒ 结果给每组一条链并挑最短那组（`best_group`）；- 根只有三种：`lit:`（真实论文，正文里可照引）、无前提自证定理（没有边 +
`evidence_kind="proof"`）、概念（`kind="concept"` 且有定义 —— 2026-10-21 之前要求 
`proof_text == "concept:primitive"`，那个哨兵正是 mp3 那 1143 条污染行的来源，现在按"定义在不在"判，历史行带哨兵照旧是根）。
"没有边又没有证明证据" ⇒ 依赖没写（`unknown`），不是根；- 边界：环 ⇒ 那一组报 `cycle` 并跳过（不牵连别的组）；`dangling` 边 ⇒ 那一
组不完整；超 `max_depth` ⇒ `truncated=True`（给已走到的前缀）；跨组汇总按节点去重（多写一组路径不许把"牵动多少节点"吹大）；- 别名：
`target` 允许给别名 ⇒ 读数里写 `matched_by: "label" | "alias"`。
"""
from __future__ import annotations
from pathlib import Path

import json

from ._support import Any, Mapping, S, Sequence, _cfg_int, tool  # noqa: F401
# 历史概念行上那个哨兵（唯一出处是 `migrate_concepts.PRIMITIVE_PROOF`）。
# 读侧仍认它（不动历史）：迁移折出来的老概念、以及 2026-10-21 之前写进来的那些行，
# `proof_text` 就是这一个值。而「写入侧」已经不再写它
# （`conceptrows.concept_statement` 那一格永远是空的）—— 所以新概念"是不是根"
# 改按"定义在不在"判。
from ..migrate_concepts import PRIMITIVE_PROOF as CONCEPT_PRIMITIVE_MARKER  # noqa: E402

#: 走到根就算完的两种 `kind`（第三种是 `lit:` 行本身，见 `_DepGraph.is_root`）。
_PROOF_KINDS = ("proof",)


class _ProofChain:
    def proof_chain(self, target: str, *, max_depth: int = 4, k: int = 1,
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
                         "best_group": None, "groups_total": 0},
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
                         "matched_by": ""},
                ok_=False, error="target_not_found")

        graph = _DepGraph(stmts=stmts, deps=deps, exps=exps, lits=lits,
                          root=getattr(getattr(self, "store", None), "root", None))
        groups_out: list[dict[str, Any]] = []
        for group, edges in sorted(graph.groups_of(node["stmt_id"]).items()):
            got = graph.walk(node["stmt_id"], group=group, edges=edges,
                             max_depth=max_depth)
            groups_out.append(got)
        # 并列（长度相同）按组号升序取前 k 组；`groups_total` 报全部组数（不假装只有 k 组）
        ranked = sorted(groups_out, key=lambda g: (g["length"] if g["reached"] else 10 ** 6,
                                                   g["group"]))
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
                             "closed": True, "roots": [node["stmt_id"]],
                             "node": {"stmt_id": node["stmt_id"], "kind": node.get("kind"),
                                      "label": node.get("label")}},
                )
            return self._report(
                "proof_chain", str(target), {"max_depth": max_depth, "k": k},
                summary=(f"{node.get('label') or node['stmt_id']}：没有任何依赖边，而且它"
                         f"**不满足根的条件**（{target_why}）⇒ 依赖没写，不是『到根了』"),
                payload={"checked": True, "target": str(target), "matched_by": matched_by,
                         "groups": [], "best_group": None, "groups_total": 0,
                         "closed": False, "roots": [], "unwritten": [node["stmt_id"]],
                         "why": target_why},
                ok_=False, error="unwritten_dependencies",
            )
        summary = (f"{node.get('label') or node['stmt_id']}："
                   f"{len(groups_out)} 组可选路径，"
                   + (f"最短是第 {best['group']} 组（{best['length']} 跳）" if best
                      else "没有一组走到根（见 warnings）"))
        payload = {
            "checked": True, "target": str(target), "matched_by": matched_by,
            "node": {"stmt_id": node["stmt_id"], "kind": node.get("kind"),
                     "label": node.get("label")},
            "groups": groups_out, "groups_total": len(groups_out),
            "best_group": best["group"] if best else None,
            # 跨组汇总按节点去重（多写一组路径不许把规模读数吹大）
            "unique_nodes": len({h["node"] for g in groups_out for h in g["hops"]}),
            "truncated": truncated,
        }
        return self._report(
            "proof_chain", str(target),
            {"max_depth": max_depth, "k": k, "weights": dict(weights or {})},
            summary=summary, payload=payload, warnings=warnings, truncated=truncated)

    # ------------------------------------------------------------ 内部

    def _resolve_target(self, target: str, stmts: Sequence[Mapping[str, Any]]):
        """号优先、别名兜底；返回 `(行, matched_by)`（找不到 ⇒ `(None, "")`）。"""
        t = str(target or "").strip()
        if not t:
            return None, ""
        bare = t[4:] if t.startswith("stmt:") else t
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
        self.edges: dict[str, list[dict[str, Any]]] = {}
        for d in deps:
            used = str(d.get("used_by") or "")
            if not used:
                continue
            # `used_by` 的两种写法都要认：`stmt:0007`（台账里推荐的那种）与裸号 `0007`
            # —— 索引一律按裸号存，查询也按裸号查（一处口径，不分叉）。
            key = used[5:] if used.startswith("stmt:") else used
            self.edges.setdefault(key, []).append(dict(d))
            if key != used:
                self.edges.setdefault(used, []).append(dict(d))

    def groups_of(self, used_by: str) -> dict[int, list[dict[str, Any]]]:
        """某一个使用点的边按 `path_group` 分组（组内 AND、组间"任一成立即到根"）。

        `used_by` 的两种写法（`stmt:0007` 与裸号 `0007`）都认 —— 索引里两种都挂了，
        这里再兜一次，免得调用方传了另一种写法就静默拿到空组（"没查到"与"没有依赖"
        必须分得开）。
        """
        out: dict[int, list[dict[str, Any]]] = {}
        key = str(used_by or "")
        bare = key[5:] if key.startswith("stmt:") else key
        for d in (self.edges.get(bare, []) or self.edges.get(key, [])):
            try:
                g = int(d.get("path_group") or 1)
            except (TypeError, ValueError):
                g = 1
            out.setdefault(g, []).append(d)
        return out

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

    def walk(self, start: str, *, group: int, edges, max_depth: int) -> dict[str, Any]:
        """从 `start` 沿这一组的边走到根；组内 AND：每条边都要走到根才算到。

        `length`（这一条路径的长度）= 链上最深的跳数（1 + 子节点那条链的长度）——
        不是"这一层的边数"（那是第一步的宽度，会把长链读成短链，与"最短依赖链"的
        口径直接冲突；判据当场抓出来过）。
        """
        hops: list[dict[str, Any]] = []
        reached = True
        truncated = False
        cycle = False
        unwritten: list[str] = []

        def _grow(node: str, depth: int, path: Sequence[str]) -> int:
            """返回 `node` 到根还有几跳（本身是根 ⇒ 0）。`depth` 只用于超深判定。"""
            nonlocal reached, truncated, cycle
            if depth > max_depth:
                truncated, reached = True, False
                hops.append({"node": node, "via_dep_id": "", "path_group": group,
                             "kind": "", "status": "depth", "why": "超过 max_depth"})
                return 0
            ok, why = self.is_root(node)
            if ok:
                return 0
            if node in path:
                cycle = True
                reached = False
                hops.append({"node": node, "via_dep_id": "", "path_group": group,
                             "kind": "", "status": "cycle", "why": "依赖里出现环"})
                return 0
            sub = self.groups_of(node)
            if not sub:
                reached = False
                unwritten.append(node)
                hops.append({"node": node, "via_dep_id": "", "path_group": group,
                             "kind": "", "status": "unwritten", "why": why})
                return 0
            best = 0
            for g in sorted(sub):
                for dep in sub[g]:
                    tgt, kind = self.target_of(dep)
                    status = str(dep.get("status") or "")
                    hops.append({"node": tgt or node, "via_dep_id": str(dep.get("dep_id") or ""),
                                 "path_group": g, "kind": kind, "status": status,
                                 "why": str(dep.get("status_reason") or "")})
                    if not tgt or status == "dangling":
                        reached = False
                        continue
                    best = max(best, 1 + _grow(tgt, depth + 1, list(path) + [node]))
            return best

        deepest = 0
        for dep in edges:
            tgt, kind = self.target_of(dep)
            status = str(dep.get("status") or "")
            hops.append({"node": tgt or start, "via_dep_id": str(dep.get("dep_id") or ""),
                         "path_group": group, "kind": kind, "status": status,
                         "why": str(dep.get("status_reason") or "")})
            if not tgt:
                reached = False
                continue
            if status == "dangling":
                reached = False
                continue
            deepest = max(deepest, 1 + _grow(tgt, 1, [start]))
        return {"group": group, "hops": hops,
                "length": deepest, "reached": bool(reached),
                "truncated": truncated, "cycle": cycle,
                "unwritten": unwritten,
                "leaves": sorted({h["node"] for h in hops
                                  if h["status"] not in ("dangling", "depth")})}
