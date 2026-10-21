"""角色 D 的动作 `adjudicate`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。
"""
from __future__ import annotations

from ._support import Any, EvidenceError, IX, S, _digest

class _Adjudicate:
    def adjudicate(self, qid: str) -> dict:
        """矛盾裁决（I2 闭环的收敛点）。
        ====================  ===================  ==========================  ==================================verdict               status               contradiction_verdict       
        后续动作====================  ===================  ==========================  ==================================``resolved``
        ``answered``         ``resolved``                清空等待集；notes 写 winner 与 code``unresolved``        ``needs_evidence``   
        ``unresolved``              轮数 +1，并提交下一轮检索请求``new_contradiction`` ``needs_evidence``   ``new_contradiction``       为新的矛盾对新
        建一条问题；原问题轮数 +1``persistent``        ``answered``         ``persistent``              停止自动追问，交人复核
        ====================  ===================  ==========================  ==================================
        为什么 ``persistent`` 必须是 ``answered``：``schema.ResearchQuestion.validate``明确拒绝"声明 persistent 却还停在 open/researching"—— 那会让循环继
        续把它当活任务。同理，终局状态必须清空等待集，否则 ``verify`` 会报``stale_waiting``（"已完成却还挂着等待项"）。
        为什么 ``contradiction_rounds`` 只在"还要继续追问"时 +1：它的语义是"已经发起过几轮追问"。``resolved``/``persistent`` 是终局，再加一就会让"轮数 ≤ 上限"这条验收在最后一轮上假性失败。
        1. 单条矛盾最多 ``max_rounds_per_contradiction``（默认 2）轮 ——由 ``interactions.adjudicate_contradiction`` 的 ``rounds/max_rounds`` 判；
        2. 全局最多 ``max_contradiction_requests``（默认 10）条矛盾驱动的检索请求； 3. 任一条预算用尽时一律走 ``persistent``，不是 ``unresolved``—— 否则"还该继续"和"该停了"会
        被混为一谈，循环停不下来。另外 I7 的在途闸门（``admit_search_request``）拒绝时也走 ``persistent``：追问发不出去 = 这一轮事实上无法继续，硬撑成 ``unresolved`` 只会留下一个"说要继续、
        却什么都没提交"的假状态。
        只有 ``strength == "strong"`` 才允许自动追问证据的"对立强度"由 ``interactions.detect_contradictions`` 判定：
        - ``strong``（一方明确断言肯定式、另一方明确断言否定式）⇒ 允许追问；- ``weak``（只是否定标记出现与否不一致）⇒ 不追问，直接标 ``persistent``，``code="weak_only_signal"``（这是
        D 侧的策略码，不在``interactions.ADJUDICATION_CODES`` 里 —— 因为"该不该拿这条线索去问 A"是 D 的决策，不是判据本身的一部分；
        所有读（问题行、关系表、裁决）都在开事务之前完成：``adjudicate`` 会读 store，而 ``filelock`` 在同一进程内重入同一把锁会直接抛错。这条与 I6 给 B 的硬约束同源（"在事务里调用会去拿锁的东西"是最容易死锁的
        形态）。
        """
        qrow = next(
            (r for r in self.store.rows("research_questions") if str(r.get("question_id")) == str(qid)), None
        )
        if qrow is None:
            # `draft/39` §6.21（真机读数，p6g 那一趟 3 次）：这条拒信此前只说"不存在"，
            # 不告诉调用方库里有哪些 id —— 于是 D 只能硬猜下一个 qid（那 3 次就是这么来的）。
            # 拒信要能让人/模型当场改对：把在册的研究问题 id 一并回给它（最多列 12 条）。
            available = [str(r.get("question_id") or "") for r in self.store.rows("research_questions")]
            available = [q for q in available if q]
            raise EvidenceError(
                f"研究问题 {qid} 不存在。"
                + (f"在册的是：{available[:12]}" + ("…" if len(available) > 12 else "")
                   if available else
                   "这张表现在**一行都没有** ⇒ 先派 D.propose_question 立一个研究问题，"
                   "再回来裁决（不许对着空表反复试 id）")
            )
        if str(qrow.get("kind") or "gap") != "contradiction":
            return {
                "question_id": qid,
                "checked": False,
                "action": "not_a_contradiction",
                "reason": (
                    f"问题 {qid} 的 kind={qrow.get('kind')!r}，不是矛盾驱动问题 ⇒ "
                    "不做矛盾裁决（这是「没做」，不是「裁决过、没矛盾」）"
                ),
            }
        rel_ids = sorted({str(x) for x in (qrow.get("contradiction_relation_ids") or []) if x})
        if len(rel_ids) != 2:
            return {
                "question_id": qid,
                "checked": False,
                "action": "bad_row",
                "reason": f"contradiction_relation_ids 必须恰有 2 条，收到 {rel_ids!r} ⇒ 无法裁决（没做）",
            }

        # ---- 重新读这两条关系 + 同概念组的全部关系
        scope = self._contradiction_scope(rel_ids)
        observed = [self._local_relation_claim(r) for r in rel_ids]
        rounds = int(qrow.get("contradiction_rounds") or 0)
        mr = int(self.max_rounds_per_contradiction)
        verdict_info = dict(
            IX.adjudicate_contradiction(
                {"relation_ids": rel_ids}, scope_relations=scope, rounds=rounds, max_rounds=mr
            )
        )
        detected = IX.detect_contradictions(scope)
        this_pair = next((x for x in detected if set(x["relation_ids"]) == set(rel_ids)), None)
        #: 当前这对关系的对立强度。只有 strong 允许驱动状态变更与追问；
        #: [踩过] weak（"否定标记出现与否不一致"）的假阳性极高 —— 实测（`draft/12` §2）：
        #: 25 条真实关系里旧"字面矛盾"判据报出 6 条 `suspect`（24%），没有一条是真矛盾。
        #: 把 weak 也拿去问 A，等于用 A 的产能换一堆假问题，而 I7 的配额正是为保护产能而设的。
        pair_strength = str((this_pair or {}).get("strength") or "weak")
        if verdict_info.get("verdict") in ("unresolved", "new_contradiction") and pair_strength != "strong":
            verdict_info.update(
                {
                    "verdict": "persistent",
                    "code": "weak_only_signal",
                    "reason": (
                        f"{rel_ids[0]} 与 {rel_ids[1]} 目前只有**弱线索**（strength={pair_strength}："
                        "否定标记出现与否不一致，而非一方明确断言肯定式、另一方明确断言否定式）"
                        "⇒ 不自动追问，标 persistent 交人复核。"
                        "弱信号的假阳性极高，拿它驱动检索会把 A 的产能烧在假矛盾上"
                    ),
                }
            )
        budget = self._contradiction_budget()
        if verdict_info.get("verdict") == "unresolved" and budget["exhausted"]:
            # 全局配额用尽 ⇒ 必须走 persistent（"该停了"与"继续"不能混为一谈）
            verdict_info.update(
                {
                    "verdict": "persistent",
                    "code": "budget_exhausted",
                    "reason": (
                        f"{rel_ids[0]} 与 {rel_ids[1]} 仍对立，但**全局矛盾检索配额已用尽**"
                        f"（{budget['used']}/{budget['limit']}）⇒ 停止自动追问，交人复核。"
                        "这可能是真实的文献分歧（本身就有研究价值），而不是检索不足"
                    ),
                }
            )

        verdict = str(verdict_info.get("verdict"))
        result: dict[str, Any] = {
            "question_id": qid,
            "checked": True,
            "verdict": verdict,
            "code": verdict_info.get("code"),
            "reason": verdict_info.get("reason"),
            "winner_relation_id": verdict_info.get("winner_relation_id"),
            "rounds_before": rounds,
            "rounds_after": rounds,
            "status": qrow.get("status"),
            "action": "",
            "request_ids": [],
            "new_question_ids": [],
            "scope_relation_ids": [str(r.get("relation_id")) for r in scope],
            "observed": [
                {
                    "relation_id": o.get("relation_id"),
                    "found": o.get("found"),
                    "status": o.get("status"),
                    "statement": _digest(o.get("statement") or o.get("description"), 140),
                }
                for o in observed
            ],
            "budget": dict(budget),
            "c_wiring": dict(self.c_wiring),
        }

        #: 新冒出来的矛盾对。`adjudicate_contradiction` 给的 `new_relation_ids` 是
        #: 关系代号的并集，不足以还原"哪两条配成一对"；因此在同一范围上重新
        #: 检测一次，把涉及原关系的新配对取出来（判据仍是 interactions 的那一份）。
        #: 只取 strength=strong 的：弱线索不建问题（理由见 `_contradiction_candidates`）。
        new_pairs: list[list[str]] = []
        if verdict == "new_contradiction":
            new_pairs = [
                list(x["relation_ids"])
                for x in detected
                if str(x.get("strength")) == "strong"
                and set(x["relation_ids"]) != set(rel_ids)
                and ({rel_ids[0], rel_ids[1]} & set(x["relation_ids"]))
            ]

        now = self._stamp()
        with self.store.tx("search_requests", "research_questions", actor=self.actor, note=f"adjudicate:{qid}") as tx:
            row = tx.find("research_questions", question_id=qid)
            if row is None:
                result["checked"] = False
                result["reason"] = f"问题 {qid} 在事务内已不存在（被并发删除）⇒ 裁决未落盘"
                return result
            req_rows = tx.rows("search_requests")
            notes: list[str] = [
                f"[adjudicate] 第 {rounds + 1} 次裁决：verdict={verdict} code={verdict_info.get('code')}；"
                f"{_digest(verdict_info.get('reason'), 300)}"
            ]

            # ---- (1) new_contradiction：为新的矛盾对新建问题（同一事务）
            for pair in new_pairs:
                pair_ids = sorted({str(x) for x in pair})
                if len(pair_ids) != 2:
                    continue
                cids: list[str] = []
                for rid in pair_ids:
                    row_rel = next((r for r in scope if str(r.get("relation_id")) == rid), None)
                    if row_rel:
                        cids.extend(str(x) for x in (row_rel.get("concept_ids") or []) if x)
                cids = sorted(set(cids))
                # 这里刻意不用 §3.1 的 `find_equivalent_question`（"共享 ≥1 个
                # 关系代号即同一件事"）：矛盾问题的身份是那一对具体的表述
                # （`contradiction_relation_ids`）。用共享代号去判，(0002,0003) 与
                # (0002,0004) 会被判成同一个研究点而被合并 —— 可它们是两场不同的
                # 争议，而且轮数/预算的账会记到错误的那一场上。所以这里用
                # "同一对关系已经建过问题吗"这一个更严的判据。
                same = next(
                    (
                        r
                        for r in tx.rows("research_questions")
                        if str(r.get("kind")) == "contradiction"
                        and sorted(str(x) for x in (r.get("contradiction_relation_ids") or [])) == pair_ids
                    ),
                    None,
                )
                if same is not None:
                    other = tx.find("research_questions", question_id=str(same.get("question_id")))
                    if other is not None:
                        line = (
                            f"merged_origins: C:contradictions:{pair_ids[0]}+{pair_ids[1]}"
                            f"（裁决 {qid} 时再次发现同一对矛盾；同一对关系已建过问题，故不新建）"
                        )
                        if line not in (other.get("notes") or ""):
                            other["notes"] = ((other.get("notes") or "") + "\n" + line)[:20000]
                        other["updated_at"] = now
                        S.row_from_dict("research_questions", other).validate()
                        tx.upsert("research_questions", other, note="adjudicate_new_equiv")
                    notes.append(f"新矛盾对 {'+'.join(pair_ids)} 已有问题 {same.get('question_id')}，未新建")
                    continue
                nq = tx.alloc_id("question")
                # 防御：`counters` 落后于表时（手工建行、台账被人改过、外部脚本写入），
                # `alloc_id` 会发出已被占用的号，而 `tx.upsert` 是按主键替换 ——
                # 于是新建的问题会静默覆盖已有那一行（既不报重复 ID、也不报错，
                # 只是那条问题凭空消失）。手工插行在测试与救急脚本里都很常见，
                # 所以这里显式跳过已占用的号。（`ingest` 的建行路径有同样的隐患，
                # 本轮未改它 —— 见最终报告。）
                guard = 0
                while tx.find("research_questions", question_id=nq) is not None:
                    guard += 1
                    if guard > 10000:
                        raise EvidenceError(
                            "question 计数器与表严重不一致：连续 10000 个号都被占用，拒绝继续分配"
                        )
                    nq = tx.alloc_id("question")
                names = [self._concept_name(c) for c in cids] or [f"关系{pair_ids[0]}", f"关系{pair_ids[1]}"]
                new_row = S.ResearchQuestion(
                    question_id=nq,
                    question=(
                        f"关系 {pair_ids[0]} 与 {pair_ids[1]} 的陈述互相矛盾，需要判定哪一方成立"
                        f"（涉及概念：{'、'.join(names)}）"
                    ),
                    origin=f"C:contradictions:{pair_ids[0]}+{pair_ids[1]}",
                    related_concept_ids=S.sorted_unique(cids),
                    related_relation_ids=S.sorted_unique(pair_ids),
                    status="open",
                    priority="high",
                    kind="contradiction",
                    contradiction_relation_ids=S.sorted_unique(pair_ids),
                    notes=(
                        f"[adjudicate] 由问题 {qid} 的裁决（new_contradiction）派生："
                        f"复核 {rel_ids[0]} vs {rel_ids[1]} 时发现涉及它们的新矛盾对。"
                    ),
                    created_at=now,
                    updated_at=now,
                )
                new_row.validate()
                tx.upsert("research_questions", new_row.to_dict(), note=f"adjudicate_new:{qid}")
                result["new_question_ids"].append(nq)
                notes.append(f"新矛盾对 {'+'.join(pair_ids)} ⇒ 新建矛盾问题 {nq}（priority=high）")

            # ---- (2) 状态与轮数
            need_request = verdict in ("unresolved", "new_contradiction")
            refusal: str = ""
            if verdict == "resolved":
                row["status"] = "answered"
                row["contradiction_verdict"] = "resolved"
                row["waiting_request_ids"] = []  # 终局：等待集必须清空（否则 verify 报 stale_waiting）
                row["contradiction_request_ids"] = list(row.get("contradiction_request_ids") or [])
                notes.append(
                    f"争议解决（code={verdict_info.get('code')}）；胜出方 winner_relation_id="
                    f"{verdict_info.get('winner_relation_id')}"
                )
                result["action"] = "answered_resolved"
            elif verdict == "persistent":
                row["status"] = "answered"
                row["contradiction_verdict"] = "persistent"
                row["waiting_request_ids"] = []
                notes.append(
                    "**已停止自动追问，交人复核**；这可能是真实的文献分歧（本身有研究价值），"
                    "而不是检索不足（persistent）"
                )
                result["action"] = "answered_persistent"
            else:
                rounds_after = rounds + 1
                # I7 闸门：在途请求上限。拒绝 ⇒ 这一轮事实上无法继续 ⇒ persistent
                gate = IX.admit_search_request(
                    req_rows,
                    submitted_by="agent-D:contradiction",
                    explicit_priority="high",
                    for_question_id=qid,
                )
                if gate.get("admitted") and not budget["exhausted"]:
                    req_id = IX.next_prefixed_id(req_rows, "request_id", "r")
                    topic, desc = self._contradiction_request_text(row, observed, rounds_after, verdict_info)
                    new_req = S.SearchRequest(
                        request_id=req_id,
                        timestamp=now,
                        topic=topic,
                        mode="topical",
                        content_description=desc,
                        done=False,
                        submitted_by="agent-D:contradiction",
                        # 优先级取自闸门的裁决（它才是"定优先级"的唯一权威实现），
                        # 而不是在这里再写死一个 "high" —— 那是第二套判据的雏形。
                        priority=str(gate.get("priority") or "high"),
                        for_question_id=qid,
                        submit_note=(
                            f"I2 矛盾闭环第 {rounds_after} 轮追问（verdict={verdict}）；"
                            f"优先级依据：{gate.get('priority_why')}"
                        ),
                    )
                    new_req.validate()
                    # `tx.upsert` 会把它插进本事务的行列表；不要再手工 append
                    # 一次，否则同一事务里同一个 request_id 出现两行，提交时会以
                    # "search_requests 出现重复 ID" 炸掉（而错误信息完全不提这条来源）。
                    tx.upsert("search_requests", new_req.to_dict(), note=f"contradiction_round:{qid}")
                    row["contradiction_request_ids"] = S.sorted_unique(
                        list(row.get("contradiction_request_ids") or []) + [req_id]
                    )
                    row["waiting_request_ids"] = S.sorted_unique(
                        list(row.get("waiting_request_ids") or []) + [req_id]
                    )
                    row["status"] = "needs_evidence"  # schema 要求它与非空等待集同生同死
                    row["contradiction_verdict"] = verdict
                    row["contradiction_rounds"] = rounds_after
                    result["request_ids"].append(req_id)
                    result["rounds_after"] = rounds_after
                    notes.append(
                        f"{verdict}：已向 A 提交第 {rounds_after} 轮检索请求 {req_id}"
                        f"（priority={new_req.priority}，submitted_by=agent-D:contradiction，"
                        f"全局矛盾配额 {budget['used'] + 1}/{budget['limit']}）"
                    )
                    result["action"] = f"ask_again_{verdict}"
                else:
                    gate_blocked = not gate.get("admitted")
                    refusal = gate.get("reason") if gate_blocked else (
                        f"全局矛盾检索配额已用尽（{budget['used']}/{budget['limit']}）"
                    )
                    row["status"] = "answered"
                    row["contradiction_verdict"] = "persistent"
                    row["waiting_request_ids"] = []
                    notes.append(
                        f"**无法继续追问 ⇒ 标 persistent 交人复核**：{refusal}。"
                        "硬撑成 unresolved 只会留下一个『说要继续、却什么都没提交』的假状态。"
                    )
                    result["action"] = "answered_persistent"
                    result["verdict"] = "persistent"
                    # D 侧策略码（不在 interactions.ADJUDICATION_CODES 里）：说清是哪一道闸
                    # 挡住了追问 —— "在途请求满了"与"全局矛盾配额用尽"要人做的处置不同。
                    result["code"] = "inflight_limit" if gate_blocked else "budget_exhausted"
                    result["reason"] = refusal

            row["updated_at"] = now
            row["notes"] = ((row.get("notes") or "") + "\n" + "\n".join(notes))[:20000]
            S.row_from_dict("research_questions", row).validate()
            tx.upsert("research_questions", row, note=f"adjudicate:{verdict}")
            result["status"] = row.get("status")
            result["rounds_after"] = int(row.get("contradiction_rounds") or 0)
            result["verdict"] = str(row.get("contradiction_verdict") or result["verdict"])
            if refusal:
                result["reason"] = refusal

        self.last_adjudication = result
        return result
