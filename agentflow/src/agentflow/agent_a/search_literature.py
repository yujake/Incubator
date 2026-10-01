"""角色 A 的动作 `search_literature`（`goal-7f5116c1` M6：从 `agent_a.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import S

class _SearchLiterature:
    def search_literature(self, *, topic: str, mode: str = "precise",
                          description: str = "") -> dict:
        """按主题现查一次：入队（过 I7 准入闸门）→ 领跑 → 把候选与来源交回召唤方。

        ## 为什么需要这个动作（2026-09-30；用户口径："A 的文献检索必须要通关"）

        A 原有的两个动作（`run_once` / `run`）的参数里没有主题 —— 它们只认
        "队列里已经有什么"。而队列今天只有三处能写：CLI `submit`、D 的
        `research.submit_gap`（还要求先有一条研究问题）、C 的 gap 分支。
        于是"角色缺文献证据 ⇒ 唤起 A"这条路上，召唤方没有办法告诉 A 要查什么：
        它只能唤一个对着空队列空转的 A（实测：G 唤起 `A.run_once`，落
        `refused/not_wired`；即使接上线，队列空时也只会得到 `no_pending_request`）。
        这个动作补的就是那一句"去查这个主题"，并且不绕过任何既有闸门：
        它走的是与 `submit` 同一条入队路径（`interactions.admit_search_request` 的
        I7 准入 + `SearchRequest.validate` + 同一个取号口径），随后仍由 `run_once`
        在既有的领取/租约/退避/判重/下载链路上跑。

        ## 默认 mode 为什么是 `precise` 而不是 `topical`（2026-09-30 实测）

        这个动作的语义是"给我这条命题的来源"，不是"给我这个领域的全景"。
        实测（同一个 topic，真机打 OpenAlex，`temp/live-a-search-*.txt` 与
        `temp/_probe_openalex_mode.py` 的读数）：

        | mode | 回来 | 对题 |
        |---|---|---|
        | `topical`（原默认） | 15 条 | 1/15（异常扩散 / 分子演化速率 / 神经形态自旋电子学…） |
        | `precise` | 8 条 | 7/8（The extremal process of BBM、Poissonian statistics…） |

        差别在 `precise` 那一档带 `keyword_hit` 后置过滤，而 `topical` 把长题面拆成
        词袋去打全文检索 —— 词袋越长，OpenAlex 的相关度排序越差。
        要"领域全景"就显式传 `mode="broad"` / `"topical"`；默认这一档服务的是
        "缺哪条证据就去找哪一条"。

        ## 三态纪律的落点（这是它与"返回一个空列表"的分界）

        - 准入被拒（在途请求已达上限）：`admitted=False` + 原因，零写入；
        - 查了但零命中：`outcome="no_results"`（有效结论，不是错误）；
        - 搜索失败：`outcome="search_failed"` + `errors`（这条请求没结束，
          会按既有退避规则重试，不许当"没有这篇文献"）；
        - 领到的是队列里更早的那条：`claimed_request_id != request_id` 如实报出来，
          绝不把它冒充成"你这条的结果"；
        - 这一问发不出去（题面里抽不出英文关键词）：入队之前就返回
          `outcome="query_not_applicable"` + `kind="query_not_applicable_cjk"`，
          零写入 —— 不许留一条注定查不动的请求在队列里（那会让调用方读成"检索失败"）。
        """
        topic = str(topic or "").strip()
        if not topic:
            return {"ok": False, "kind": "bad_topic",
                    "error": "topic 不能为空（空主题让检索无从构造）"}
        mode = str(mode or "topical")
        if mode not in S.SEARCH_MODES:
            return {"ok": False, "kind": "bad_mode",
                    "error": f"mode 必须是 {S.SEARCH_MODES} 之一，收到 {mode!r}"}
        if not self.providers:
            # 「没接线」必须与「查了但没命中」分开：这一档零写入，
            # 调用方据此知道要先去配检索后端，而不是以为这个主题没有文献。
            return {"ok": False, "kind": "no_provider", "topic": topic, "mode": mode,
                    "error": "A 没有接任何检索后端（providers 为空）⇒ 这次检索没查成"}

        desc = str(description or "").strip()
        if mode == "precise" and not desc:
            # `schema.SearchRequest.validate` 里有一条禁改区判据：
            # precise 必须带 `content_description`。不改它（那是磁盘格式契约），
            # 这里用题面本身兜底 —— 实测两种给法（空描述 / 题面当描述）
            # 在 OpenAlex 上都是 8 条里 7 条对题，所以这一兜底不损失质量。
            desc = topic

        # ---- 入队之前先问一句"这一问发得出去吗"（2026-09-30 加）
        #
        # 判据取自 providers 的公开函数 `query_applicability` —— 不在本文件里
        # 另写一份"题面里有没有英文关键词"（两套判据必然漂移，而漂移的表现是
        # "一边说能查、一边不发"）。用的正是 provider 将要用的那一对
        # `(topic, 清洗后的 description)`，所以这里判"不适用"⇒ provider 那边一定也不适用。
        #
        # 为什么必须在入队之前判：`providers` 对抽不出英文关键词的题面是 fail-closed
        # （抛 `query_not_applicable_cjk`），而这条请求一旦入队，`run_once` 会把它当
        # "搜索失败"处理 —— 试满 `max_attempts` 次、每次留下退避租约，最后落
        # `search_failed`。对调用方来说，那读起来像"检索出问题了"，而真相是
        # "这一问根本没发出去"。两件事必须分开（三态纪律），而且这一档零写入。
        from .. import providers as P

        decision = P.query_applicability(topic, self._query_description(topic, desc))
        if not decision.applicable:
            return {
                "ok": True, "admitted": False, "request_id": None,
                "topic": topic, "mode": mode,
                "outcome": "query_not_applicable",
                "kind": getattr(decision, "state", "") or "query_not_applicable",
                "reason": str(getattr(decision, "refusal_reason", "")),
                "note": (
                    "这一问**没有发给上游**（第三态：没问，不是「查了、没有」，"
                    "也不是「检索失败」）。A 的检索后端以英文文献为主：把 `topic` 换成"
                    "带英文关键词的检索式，或把英文检索式写进 `description`，再唤起一次。"
                ),
            }

        admitted = self._enqueue_search(topic, mode, desc)
        if not admitted.get("admitted"):
            return {"ok": True, "admitted": False, "topic": topic, "mode": mode,
                    "request_id": None, "outcome": "rejected_by_gate",
                    "reason": admitted.get("reason"), "gate": admitted}

        rid = str(admitted["request_id"])
        rounds: list[dict] = []
        claimed_ids: list[str] = []
        for _ in range(max(1, int(self.search_max_rounds))):
            res = self.run_once()
            rounds.append(res.to_dict())
            if res.request_id:
                claimed_ids.append(str(res.request_id))
            row = self._request_row(rid)
            if row is not None and (row.get("done") or row.get("outcome")):
                break
            if res.request_id is None:
                break                      # 没有可领的了（原因见 skipped_reason）
        row = self._request_row(rid) or {}
        lit_ids = [str(x) for x in (row.get("result_lit_ids") or [])]
        return {
            "ok": True,
            "admitted": True,
            "request_id": rid,
            "topic": topic,
            "mode": mode,
            "done": bool(row.get("done")),
            "outcome": row.get("outcome"),
            # 本轮依次领到过哪些请求。故意给全表而不是只给最后一条：
            # 队列里有更早的请求时，这个动作会先替它跑完再跑自己那条 ——
            # 只报最后一条会让调用方以为"我这条一直没被处理"（实测踩过：
            # 第一版报 `claimed_request_id`，而它等于自己那条，读者据此以为
            # "队列里没有别人"）。`claimed_own` 才是"我这条被跑到了没有"。
            "claimed_request_ids": claimed_ids,
            "claimed_own": rid in claimed_ids,
            "result_lit_ids": lit_ids,
            "literature": self._literature_brief(lit_ids),
            # 实际进查询串的那份描述（非 ASCII 会被丢，见 `_query_description`）。
            # 给出来是为了"我写了描述但结果不对"这类问题能在读数上直接看出来。
            "query_description": self._query_description(topic, desc),
            "registered": sum(int(r.get("registered") or 0) for r in rounds),
            "duplicated": sum(int(r.get("duplicated") or 0) for r in rounds),
            "downloaded": sum(int(r.get("downloaded") or 0) for r in rounds),
            "download_failed": sum(int(r.get("download_failed") or 0) for r in rounds),
            "attempts": int(row.get("attempts") or 0),
            "last_error": row.get("last_error"),
            "queue_pending": rounds[0].get("queue_pending") if rounds else 0,
            "rounds": rounds,
            "note": (
                "这一条已经入队并跑过；`outcome=no_results` 是有效结论（查了、没有），"
                "`search_failed` 不是结论（这条请求还没结束，会按退避规则重试）。"
            ),
        }
