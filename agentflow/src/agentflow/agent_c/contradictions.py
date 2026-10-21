"""角色 C 的动作 `contradictions`（`goal-7f5116c1` M6：从 `agent_c.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import SERVICE_MAX_CONTRADICTIONS, Sequence, _cfg_int, _service_int, interactions

class _Contradictions:
    def contradictions(self, *, relation_ids: Sequence[str] | None = None, limit: int | None = None) -> dict:
        """矛盾检查（同步、只读、有界），判据全部来自 `interactions`。
        返回----``{"checked", "scope", "scanned", "contradictions", "strong_count", "weak_count","strong_relation_id_pairs", "truncated", "limit", "method": "literal","method_note", "reason"}``
        `contradictions` 里每一项保留 `interactions` 给的 `strength`（`strong` = 明确对立主张；`weak` = 仅否定词出现
        与否不一致）。两者必须分开看：实测里 `weak` 的假阳性极高，把它当矛盾呈现会让 D 去追一个不存在的问题。
        范围：给了 `relation_ids` 就用这些（I2 的"只复核这两个具体的关系"靠它 ——重跑整个分析既慢又会引入与本次复核无关的噪音），否则用全部关系。
        `method_note` 必须存在且诚实：本方法只做可逐字核实的形态，它不声称能判定一般语义矛盾；而且字面判据本身还分两档（`strong` / `weak`，见 
        `interactions.detect_contradictions`）：只有 `strong`（一方明确肯定、另一方明确否定同一对立词组）才够格当研究线索，`weak`
        （仅否定词出现与否不一致）在真实数据上假阳性极高。把"字面检测"说成"语义分析"、或把 `weak` 线索说成"发现了矛盾"，都会让 D 去追一个不存在的问题。
        自己不实现任何判据：全部委托 `interactions.detect_contradictions`。
        传进去的是原始表行（图快照里的副本），不预先注入 `concept_pair_key`：那个派生字段由 `interactions` 就地推导 —— 这避免了"忘了算派生态
        ⇒ 静默拿到空结果"这类失效（见 `interactions.concept_pair_key` 的说明）。
        """
        g = self._g()
        checked, why = self._service_checkable(g)
        lim = max(1, _cfg_int(self.cfg, "service_max_contradictions", SERVICE_MAX_CONTRADICTIONS))
        if limit is not None:
            lim = max(1, min(_service_int(limit, name="limit", default=lim), lim))
        meta = {
            "method": "literal",
            "method_note": (
                "只做字面判据，不声称能判定一般语义矛盾。且字面判据分两档："
                "strong（明确对立主张）才可作为研究线索；"
                "weak（仅否定词出现与否不一致）在实测中假阳性极高，仅供参考。"
            ),
            "limit": lim,
        }
        if not checked:
            return {**meta, "checked": False, "scope": "none", "scanned": 0,
                    "contradictions": [], "strong_count": 0, "weak_count": 0,
                    "strong_relation_id_pairs": [], "truncated": False,
                    "missing_relation_ids": [], "reason": why}

        missing: list[str] = []
        if relation_ids is None:
            scope = "all_relations"
            rows = list(g.relations)
        else:
            scope = "given_relation_ids"
            wanted = [str(x) for x in relation_ids]
            rows = [g.relation_by_id[r] for r in wanted if r in g.relation_by_id]
            missing = sorted({r for r in wanted if r not in g.relation_by_id})
            if not rows:
                return {
                    **meta, "checked": False, "scope": scope, "scanned": 0, "contradictions": [],
                    "strong_count": 0, "weak_count": 0, "strong_relation_id_pairs": [],
                    "truncated": False, "missing_relation_ids": missing,
                    "reason": (
                        f"给定的 relation_ids（{wanted or '空'}）**一条都不在关系表里** ⇒ 没检查。"
                        "这与'检查过、不矛盾'完全不同：后者才能作为结论使用"
                    ),
                }

        # 传进去的是原始表行，不预先注入 `concept_pair_key`。
        #
        # 曾经这里是"C 自己补一个派生字段再传进去"（因为 `relations` 表存的字段名是
        # `concept_group_key`，而 `detect_contradictions` 只读 `concept_pair_key`）。
        # 那是一个完全静默的失效形态：任何忘了补这一步的调用路径都会恒得到 `[]`
        # —— 不报错、不告警，看起来就像"没有矛盾"（实测同一批 25 条真实关系，
        # 直接传表行得 0 条，补过字段得 8 条）。
        # 现在 `interactions.detect_contradictions` 由 `concept_ids` 就地推导该字段，
        # 调用方只传真源。派生字段由唯一权威实现算 —— 这避免了
        # "忘了算派生态 ⇒ 静默拿到空结果"这类失效，也避免了第二份推导规则。
        prepared = list(rows)
        found = interactions.detect_contradictions(prepared)
        truncated = len(found) > lim
        kept = found[:lim]
        # `strength` 由 interactions 判定，这里只做分开统计，不改判据、不改强度。
        # 为什么必须在返回值里分档：下游（D 的追问、人的复核）要能一眼看出
        # "这条是真对立"还是"这条只是否定词不一致"。混在一起报，就等于
        # 把 24% 假阳性的线索当成矛盾 —— 那会让 `status=suspect` 这个标记失去意义。
        strong = [x for x in kept if str(x.get("strength") or "") == "strong"]
        weak = [x for x in kept if str(x.get("strength") or "") != "strong"]
        reason = (
            f"范围={scope}，扫描 {len(prepared)} 条关系，命中 {len(found)} 对字面候选"
            f"（strong {sum(1 for x in found if str(x.get('strength')) == 'strong')} 对、"
            f"weak {sum(1 for x in found if str(x.get('strength')) != 'strong')} 对）"
        )
        if truncated:
            reason += f"；⚠️ 仅返回前 {lim} 对（truncated=True）：**不能据此说'只有这些矛盾'**"
        if missing:
            reason += f"；给定的 {'、'.join(missing)} 不在关系表里，未被扫描（**没查**，不是'不矛盾'）"
        if weak:
            reason += (
                f"；其中 {len(weak)} 条是 weak（仅否定词出现与否不一致），"
                "**实测假阳性极高，不得当作矛盾呈现**，只能作为继续查的线索"
            )
        if not found:
            reason += (
                "。注意这个结论的强度：它只说明'在可逐字核实的形态下没有发现矛盾'，"
                "**不等于'文献之间没有分歧'**（一般语义矛盾本方法判定不了）"
            )
        return {
            **meta,
            "checked": True,
            "scope": scope,
            "scanned": len(prepared),
            "contradictions": kept,
            "strong_count": len(strong),
            "weak_count": len(weak),
            "strong_relation_id_pairs": [list(x["relation_ids"]) for x in strong],
            "truncated": truncated,
            "missing_relation_ids": missing,
            "reason": reason,
        }
