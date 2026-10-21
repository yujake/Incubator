"""角色 A 的动作 `search_literature`（`goal-7f5116c1` M6：从 `agent_a.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Iterable, S
from ..refusals import refuse

class _SearchLiterature:
    def search_literature(self, *, topic: str, mode: str = "precise",
                          description: str = "",
                          providers: Iterable[str] | None = None) -> dict:
        """按主题现查一次：入队（过 I7 准入闸门）→ 领跑 → 把候选与来源交回召唤方。
        为什么需要它（2026-09-30；用户口径："A 的文献检索必须要通关"）：`run_once` / `run` 参数里没有主题，召唤方没办法告诉 A 要查什么（实测 G 唤起 
        `A.run_once` 落 `refused/not_wired`）。本动作不绕过既有闸门：走 `submit` 同一条入队路径（`interactions.admit_search_request`
        的 I7 准入 +`SearchRequest.validate` + 同一个取号口径），随后仍由 `run_once` 在既有领取/租约/退避/判重/下载链路上跑。默认 mode 是
        `precise` 而不是 `topical`：语义是"给我这条命题的来源"而不是领域全景（实测 `topical` 15 条对题 1/15、`precise` 8 条对题 7/8，差
        别在 `keyword_hit` 后置过滤）。三态落点：准入被拒 ⇒ `admitted=False` + 原因、零写入；零命中 ⇒ `outcome="no_results"`（有效
        结论）；搜索失败 ⇒ `outcome="search_failed"` + `errors`（不许当"没有这篇"）；题面抽不出英文关键词 ⇒ 入队前返回 
        `outcome="query_not_applicable"` + `kind="query_not_applicable_cjk"`、零写入。`providers=[…]` 也是三
        态（`None` / 合法源名 / 不认识的源名，后者 `kind="unknown_provider"`），名字落进 `SearchRequest.providers`、领取侧按行上
        的名字检索、跨源合并走 `MultiProvider`。三处"调用本身不成立"走 :func:`agentflow.refusals.refuse`（`draft/37` §88），三
        态纪律见:mod:`agentflow.refusals` 的模块说明。
        """
        topic = str(topic or "").strip()
        if not topic:
            return refuse("bad_topic", "topic 不能为空（空主题让检索无从构造）")
        mode = str(mode or "topical")
        if mode not in S.SEARCH_MODES:
            return refuse("bad_mode", f"mode 必须是 {S.SEARCH_MODES} 之一，收到 {mode!r}")

        # ---- `providers`：把"问哪几个源"定下来（第三态在这里分开）
        #
        # 归一化只做三件事：转字符串、去空白、按出现次序去重。刻意不排序 ——
        # 次序是合并口径的一部分（先到的源先填字段），排序等于静默改口径。
        wanted: list[str] | None = None
        if providers is not None:
            wanted = []
            for raw_name in providers:
                name = str(raw_name or "").strip()
                if name and name not in wanted:
                    wanted.append(name)
            wired = self._wired_provider_names()
            if not wanted:
                return refuse(
                    "bad_providers",
                    "providers 是空列表：要么不给这个参数（按角色级接线查），"
                    "要么至少给一个源名。给空列表既不是按角色配置、也不是一个可用源，"
                    "只会让'这一次到底问了谁'变得没法读。",
                    available=wired,
                )
            unknown = [n for n in wanted if n not in wired]
            if unknown:
                return refuse(
                    "unknown_provider",
                    f"不认识的源名 {unknown}；可用源是 {wired}。"
                    "这一档如实拒绝而不是忽略：忽略会让'我要问这几个源'静默变成"
                    "'只问了其中一个'，而调用方从读数上看不出差别。",
                    available=wired,
                    providers_requested=wanted,
                    unknown=unknown,
                )

        if not self.providers:
            # 「没接线」必须与「查了但没命中」分开：这一档零写入，
            # 调用方据此知道要先去配检索后端，而不是以为这个主题没有文献。
            return refuse("no_provider",
                          "A 没有接任何检索后端（providers 为空）⇒ 这次检索没查成",
                          topic=topic, mode=mode)

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

        admitted = self._enqueue_search(topic, mode, desc, providers=wanted)
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
        # 逐源读数只取"领到自己那条请求"的那一轮：队列里有更早的请求时，
        # 这个动作会先替它跑完（那些轮次的源不属于这一问），把几轮的读数混在
        # 一起会读成"这一次问了所有的源"。其余轮次的读数照旧逐轮留在 `rounds[]`。
        own_round = next((r for r in rounds if r.get("request_id") == rid), None)
        own_sources = list((own_round or {}).get("sources") or [])
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
            # ---- 这一次问了谁（三态读数，键名与形状照工具面的同名读数）
            #
            # `providers_requested` 是"这一行点名了哪些源"（第一态为 None，
            # 不是空数组 —— 空数组会与"点名了、但一个都没接上"同形）。
            "providers_requested": list(row.get("providers") or []) or None,
            # 角色级接线上有哪些源：第一态靠它回答"这一次用的是哪些源"。
            "role_providers": self._wired_provider_names(),
            # 逐源三态（`delivered` / `refused` / 上游 `failed`）与条数。
            "sources": own_sources,
            # 这些读数取自哪一轮（`None` = 自己那条没被领到，`sources` 因此为空）。
            "sources_round": (own_round or {}).get("request_id"),
            # 成本按"这一次动作真的跑了几轮"汇总（每一轮都付了出网的钱）。
            "cost": {
                "provider_calls": sum(int((r.get("cost") or {}).get("provider_calls") or 0)
                                      for r in rounds),
                "elapsed_s": round(sum(float((r.get("cost") or {}).get("elapsed_s") or 0.0)
                                       for r in rounds), 3),
            },
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
                "`sources[]` 是这一行点名的那些源的逐源三态，取自 `sources_round` "
                "那一轮；没点名源时它是空的（那说明这次按角色级接线查，"
                "接线上的源名见 `role_providers`）。"
            ),
        }
