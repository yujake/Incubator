"""角色 D 的动作 `register_conjecture`（`goal-7f5116c1` M6：从 `agent_d.py` 拆出来，逐字未改）。

拆出来的判据：一动作一文件与「方法真住在那里」由 `tests/test_agent_split_is_one_action_one_file.py` 钉住；「搬移逐字」那半是一次性证明（`temp/_m6_verify_verbatim.py`），不是常驻判据。R1-A1 起本动作接了模型精修（产出只进读数，登记语义不变）⇒ 它不再逐字；同族其余动作仍逐字。
"""
from __future__ import annotations

from ._support import (Any, EvidenceError, KIND_CLIENT, STATE_FAILED, STATE_USED, json,
                       invented_facts, model_json_call, spend_reading)

class _RegisterConjecture:
    def register_conjecture(self, **params: Any) -> dict:
        """登记或更新一条猜想（转发 `conjecture.register_conjecture`；依据 `draft/31` P7 第 4 张表）。

        ## 为什么失败要抛，而不是像 `_call` 那样返回 `None`

        D 的读路径（`_call`）把失败吃掉是合理的：一次查不到不该中断整轮研究，
        原因落在 `self.last_tool_errors` 里。但写路径不一样：返回 `None` 会让
        `Conductor._end_from_payload` 记成 `outcome="ok"` 而 `payload=None` ——
        台账上看起来"这一步做成了"，而库里一行都没有。这正是本项目最忌的形态
        （"假装跑通并返回空"）。所以这里把失败原样抛出去，让终态是 `failed`。

        ## 三态

        `conjecture_id` 给了但库里没有 ⇒ 抛（不许静默新建一条重复的猜想）。
        `None` = 调用方没提这个字段 ⇒ 保留库里已有的值（更新语义见 `conjecture_tools`）。

        ## 模型接在哪（`R1-A1` 裁定 2：按 `research` 那条同一形态）

        `register_conjecture` 是当前树里 D 的真主力（现算 191 次召唤 / 29 条会话行），
        所以它也在"在用动作"里，接法与 `research` 逐条同形：

        - 模型只做把已有的确定性产物写得更通顺/更完整（给这条猜想写一句"可检验性复述"
          与一条"下一步怎么验"的建议）；
        - 登记与否、字段取什么值仍是确定性判定 —— 模型的产出不进库
          （它只进返回值里的 `llm_reading`，随这一趟的读数出去；要引它，人/M 自己读）；
        - 三态读数（`kind/state/reason/model/calls/task_id/spend`）与 `invented_facts`
          校验同样适用：模型若引用了这条猜想所依据的台账里没有的编号 ⇒ 丢弃这段产出；
        - 失败（没接线/超时/坏 JSON/空回复）⇒ fail-open：库照写，读数如实说是哪一种。

        为什么不让模型的话进库：那几个字段过了 schema 校验、是知识库的一部分，
        而"模型写得更通顺"没有资格改一条被登记的知识（这与 `_rank_min` 同一条纪律：
        模型可以帮忙措辞，但不能改变事实面）。
        """
        res = self.tools.call("conjecture.register_conjecture", **params)
        if not res.ok:
            # 失败同时进 `last_tool_errors`（报告里的审计一节读它）与异常，
            # 两条路都要：前者让"这一轮 D 犯过什么错"可查，后者保证终态是 failed。
            self.last_tool_errors.append(
                {"tool": "conjecture.register_conjecture", "error": res.error,
                 "kind": res.meta.get("kind")}
            )
            raise EvidenceError(
                f"conjecture.register_conjecture 失败（kind={res.meta.get('kind')}）：{res.error}"
            )
        out = dict(res.data)
        # 登记已经完成（上面那一步），下面是"把已有产物写得更通顺"那一半：
        # 它的产出只进读数，绝不回写 `out`。
        out["llm_reading"] = self._conjecture_reading(out)
        return out

    def _conjecture_reading(self, row: dict) -> dict:
        """给一条刚登记的猜想写"可检验性复述 + 下一步怎么验"（只进读数，不进库）。"""
        reading: dict[str, Any] = {"kind": "none", "state": "not_wired", "calls": 0,
                                   "reason": "没有接线（llm is None）", "model": "",
                                   "task_id": "", "spend": {}}
        if self.llm is None:
            return reading
        prompt = json.dumps({
            "task": ("下面这条猜想已经登记好了。**不要**改它的 statement/status 等字段，"
                     "只写两句：(1) 把它的可检验性用一句话复述清楚；(2) 下一步怎么验。"
                     "只能引用给出的编号，不得引入外部事实。"),
            "conjecture": {"statement": row.get("statement"), "origin": row.get("origin"),
                           "status": row.get("status"), "form": row.get("form"),
                           "testable": row.get("testable"), "grade": row.get("grade")},
            "known_refs": {"experiment_ids": row.get("experiment_ids") or [],
                           "known_lit_id": row.get("known_lit_id")},
            "output_format": {"restatement": "字符串", "next_check": "字符串"},
        }, ensure_ascii=False, default=str)
        payload, text, got = model_json_call(self.llm, prompt, task_id=self._summon_task_id(),
                                             note="D.register_conjecture 的可检验性复述")
        got["task_id"] = self._summon_task_id()
        got["spend"] = spend_reading(self.store, got["task_id"])
        if payload is None and text.strip() and got.get("kind") == KIND_CLIENT:
            # 裸 client 回了散文：仍按旧口径收下（它没有 `problem` 词表），但不进库。
            got["state"] = STATE_USED
            got["restatement"] = text.strip()
            self.last_llm_reading = dict(got)
            return got
        if payload is None:
            self.last_llm_reading = dict(got)
            if got.get("state") == STATE_FAILED:
                self.last_tool_errors.append(
                    {"tool": "llm", "error": f"猜想的复述没写成（{got.get('reason')}）"})
            return got
        blob = "\n".join([str(payload.get("restatement") or ""),
                          str(payload.get("next_check") or "")])
        bad = invented_facts(blob,
                             known_lit_ids=[str(row.get("known_lit_id") or "")],
                             known_relation_ids=())
        if bad:
            got["state"] = STATE_FAILED
            got["reason"] = f"llm_invented_facts: {bad}"
            self.last_tool_errors.append(
                {"tool": "llm", "error": f"猜想的复述引了不存在的编号，已丢弃：{bad}"})
            self.last_llm_reading = dict(got)
            return got
        got["restatement"] = str(payload.get("restatement") or "")
        got["next_check"] = str(payload.get("next_check") or "")
        self.last_llm_reading = dict(got)
        return got
