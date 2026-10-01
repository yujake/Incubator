"""角色 B 的动作 `decide_structural_duplicate`（`goal-7f5116c1` M6：从 `agent_b.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, I, Mapping, Sequence

class _DecideStructuralDuplicate:
    def decide_structural_duplicate(
        self,
        candidate: Mapping[str, Any] | None,
        *,
        concepts: Sequence[Mapping[str, Any]] | None = None,
        relations: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict:
        """I5：对 C 提出的"结构重复候选"给出合并或否决的决定（决定权在 B）。

        决策规则（保守；两路证据必须独立成立）
        ----------------------------------------
        1. 结构侧（由 B 自己复算，不采信候选里的结论）：候选必须恰是两个概念、
           两者都还是活节点（`merged_into` 为空），且两者之间没有直接关系 ——
           有直接关系说明它们已经被声明为两个不同的东西，"邻域相同"在这里是
           自然现象，合并会抹掉一条真实知识。
        2. 名字侧（第二路，独立于结构）：先要求 C 给的名字证据不是 `"none"`，
           再用 `dedup.find_concept` 的同一套规范化独立复核：去掉 A 之后，
           用 A 的名字/别名查判重索引，必须恰好查回 B；反向亦然。
           "恰好"很重要：若查回的是第三个概念，说明名字有歧义 ⇒ 不合并。

        两条都成立才 `merge`；否则 `reject`，并且必须给出能被反驳的理由
        （例如"邻域相同但规范化名字不同且无别名交集 ⇒ 结构等价 ≠ 同义"）。

        为什么这么保守：结构等价 ≠ 同义。"所有子群都同构的两个概念"完全可能
        连着同一批邻居。错误合并不可逆（度数、路径、问题溯源全被污染），
        而漏合并只是少省一点空间。

        survivor 的选取规则（确定性，不随机）
        -----------------------------------
        定义更长的一方存活；定义长度相同（含都为空）时取 `concept_id` 较小者。
        理由：survivor 的定义会留在图上，丢掉更完整的定义等于静默删知识；
        `concept_id` 是唯一稳定的全序，用它兜底保证"同一候选永远得到同一结论"
        （可复现、可审计，且不依赖表的物理顺序）。

        返回 ``{"verdict", "reason", "survivor_id", "merged_id", "evidence"}``。
        本方法只决定不落盘；执行合并用 :meth:`resolve_structural_duplicate`。
        """
        rows_c = list(concepts) if concepts is not None else self.store.rows("concepts")
        rows_r = list(relations) if relations is not None else self.store.rows("relations")
        cids = [str(x) for x in ((candidate or {}).get("concept_ids") or [])]

        def reject(why: str) -> dict:
            return {
                "verdict": "reject",
                "reason": why,
                "survivor_id": None,
                "merged_id": None,
                "evidence": {"concept_ids": cids, "candidate_proposal": (candidate or {}).get("proposal")},
            }

        if len(cids) != 2:
            return reject(f"候选必须**恰好两个**概念（I5 的结构重复是成对的），收到 {cids!r}")
        a_id, b_id = sorted(cids)
        if a_id == b_id:
            return reject(f"候选的两个概念代号相同（{a_id}）⇒ 这不是一对，拒绝")
        by_id = {str(c.get("concept_id")): c for c in rows_c}
        a, b = by_id.get(a_id), by_id.get(b_id)
        if a is None or b is None:
            return reject(f"候选里有概念不存在于概念表（{a_id if a is None else b_id}）⇒ 无法复核，拒绝")
        if a.get("merged_into") or b.get("merged_into"):
            return reject(
                f"{a_id}/{b_id} 中有一方已经是墓碑（merged_into 非空）⇒ 应把候选转到 survivor 上，不得二次合并"
            )
        for r in rows_r:
            rc = {str(x) for x in (r.get("concept_ids") or [])}
            if a_id in rc and b_id in rc:
                return reject(
                    f"{a_id} 与 {b_id} 之间存在直接关系 {r.get('relation_id')} ⇒ 它们**已被声明为"
                    "两个不同的东西**，此时'邻域相同'是自然的，**不得合并**"
                )
        name_ev = str((candidate or {}).get("name_evidence") or "none")
        if name_ev == "none":
            return reject(
                "邻域相同但规范化名字不同、也无别名交集 ⇒ **结构等价 ≠ 同义**"
                "（两个不同的概念完全可能连着同一批邻居）；只有一路证据，不得合并"
            )
        fwd = self._dedup_match(rows_c, exclude_id=a_id, name=str(a.get("name") or ""), aliases=a.get("aliases") or [])
        rev = self._dedup_match(rows_c, exclude_id=b_id, name=str(b.get("name") or ""), aliases=b.get("aliases") or [])
        got_fwd = str(fwd.get("concept_id")) if fwd else None
        got_rev = str(rev.get("concept_id")) if rev else None
        if got_fwd != b_id or got_rev != a_id:
            return reject(
                "名字侧独立复核未通过：用 dedup.find_concept（同一套规范化）在**去掉自身**的表上查，"
                f"{a_id} 的名字解析到 {got_fwd or '无命中'}（期望 {b_id}）、"
                f"{b_id} 的名字解析到 {got_rev or '无命中'}（期望 {a_id}）"
                "⇒ 名字证据不足或存在歧义（可能别名指向第三个概念），不得合并"
            )
        len_a = len(str(a.get("definition") or "").strip())
        len_b = len(str(b.get("definition") or "").strip())
        survivor, merged = (
            (a, b) if (len_a, -self._id_order(a_id)) >= (len_b, -self._id_order(b_id)) else (b, a)
        )
        survivor_id, merged_id = str(survivor["concept_id"]), str(merged["concept_id"])
        neigh = [str(x) for x in ((candidate or {}).get("neighbors") or [])]
        # `_NAME_EVIDENCE_TEXT` 是 C 侧同一份证据的人话说明：复用它，避免
        # "C 说这是别名证据、B 的报告却写成别的词"这种同一事实两种措辞。
        # 取不到时回退到代码本身（宁可少一句人话，也不许因为措辞表改名就炸）。
        why_name = getattr(I, "_NAME_EVIDENCE_TEXT", {}).get(name_ev, name_ev)
        reason = (
            "两路独立证据同时成立：① 结构等价（邻域完全相同"
            + (f"：{'、'.join(neigh)}" if neigh else "")
            + "，且两者之间无直接关系 —— 由 B 从关系表复算确认）；"
            f"② 名字侧证据「{why_name}」，且 B 用 dedup.find_concept 的同一套规范化独立复核双向命中。"
            f"按确定性规则（定义更长者存活，同长取 concept_id 较小者：{len_a} vs {len_b} 字符）"
            f"⇒ {survivor_id} 存活、{merged_id} 被吸收"
        )
        return {
            "verdict": "merge",
            "reason": reason,
            "survivor_id": survivor_id,
            "merged_id": merged_id,
            "evidence": {
                "concept_ids": [a_id, b_id],
                "name_evidence": name_ev,
                "candidate_proposal": (candidate or {}).get("proposal"),
                "detected_by": (candidate or {}).get("detected_by"),
                "definition_lengths": {a_id: len_a, b_id: len_b},
            },
        }
