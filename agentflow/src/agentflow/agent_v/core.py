# -*- coding: utf-8 -*-
"""智能体 V：证明级验证（只读；`draft/39` §3.21 一/五/六 的用户定案）。
## 它是谁
H 是稿件级正式审查（五元位第 5 位）；V 是证明级验证（五元位第 3 位）。 V 做三件事（用户点名的 I12/I10/I17），三条都在这里落地：
1. I12 冷启动：每次审校只把"对象（证明全文）+ 只读读数"拼进提示词 ——拼提示词的函数（`verifications.cold_start_prompt`）只收字
符串，没有任何 store / conductor / registry 句柄参数，"独立性"因此是结构性质； 2. I10 硬禁令 + 同段依据：逐条查无条件前提 / 无
依据的步骤 / "易证、显然"这类缝 /引用到不干净的命题，每条问题指到那一步（落进 findings 的 `step` 字段）； 3. I17 整篇重读：证明是整体一次交
给它的输入，不是逐单元切开的碎片。
## 它只写一个文件，不写任何表
`read_only=True`、`write_set=frozenset()`（`specs/v.py`）。它唯一的产物是
`verifications/<命题号>.jsonl`（追加式，`verifications.record_verification` 发号）。所以它拿不到任何写工具
—— 这不是"约定只读"，是 `tools.base._role_surface`的结构性剥离（`tools.READ_ONLY_ROLES` 含 `"V"`）。
## 2026-10-22 补：签字要能到命题那一行上（2026-10-29 起由秘书落地）
`verify_proof` 调 `verifications.record_verification(..., store=self.store, flip=False)`：
它只把台账那一行落盘。把被签的那一份证明（`proof_no`）的 `reviewed` 翻上去是
`verifications.sign_statement` 的事，而它的唯一调用者是 V 的秘书
（`Secretary.decide_sign_issuance` 的落地那一步）。为什么必须由签名这条路径自己写：
此前第 3 位的唯一写者是 B 的 `register_statement`，而它按
`evidencebits.BIT_OWNERS` 不替 V 签字 ⇒ "V 签了、台账上写着成立"与"命题那一行的 reviewed 位"
之间没有连接，收工门 R10 恒 0。写回的结果在返回值 `review_write` 里（写没写成、为什么、
回滚了没有），失败不静默吞掉。
业主 2026-10-29 的口径：V 只产审稿意见；发不发签由 V 的秘书决定（连续 3 次 clean 才发），
所以 `verify_proof` 的返回值里 `signed_bit3` 读的是"秘书真的把位翻上去了没有"，
不是"台账里的票数够不够"。
## 2026-10-30 补：「连续 3 次」是谁在数（这一条改了调用形态）
业主口径逐字：「V 所谓连续 3 次『没问题』，是 V 判没问题后连续再判，不是 F 提交 3 次
V 过 3 次。毕竟没问题的判决没必要给 F。有毛病的要给 F 知道叫它改正。这块 V 秘书要做好」。
于是 `verify_proof` 一次调用会自己问模型（同一份正文、同一个 `proof_no`）：每一问都落一行
台账、都问一次秘书发不发；clean 那一档一个字都不发给 F。

## 2026-10-30 再补：连判只有两种终局（业主第二次裁定仍有效）
业主口径逐字：「连判里面如果判出一回秘书语义分析认为是『有毛病』的，
则直接打回了，连判终止」。于是这一趟的终局只有两种，上界动态等于门槛
（:func:`review_pass_bound`，`VR.SIGN_STREAK_NEED` 现读）：

1. 连续 `VR.SIGN_STREAK_NEED` 转 clean ⇒ 秘书发签；
2. 任一转判出 `fault`（有毛病）⇒ 立刻终止，这一转就是终局：台账那一行经秘书洗稿后由
   `agent_loop.v_rejections_digest` 与 `deliver_v_verdicts` 打回给 F；V 自己的结论不是
   「成立」那一档也立刻停（它本身就是打回）。

## 2026-10-30 三次补：秘书的语义判定只有两档（第三次裁定，本次唯一口径）
业主口径逐字：「不可能有判不了。你告诉我啥叫判不了？只要不是完全没毛病都叫有毛病」。
所以秘书的判定轴只有 `clean` / `fault`：拿不准、只挑出一处小记号问题、只说"我没逐行验证"
——统统算 `fault`。词表里也只有两格（`secretary.V_REPLY_VERDICTS`）：模型若仍答历史
那一格（"判不了"）或任何词表外的写法 ⇒ `judge()` 判"不采信" ⇒ `checked=False`（没查成），
不会被折成第三种结论。历史台账行里出现过的 `unsure` 只作历史兼容读（读得出、新判定不再
产生它）。

"没查成"不是判定（第 3 条）：秘书问不出来 / 模型输出不合法 / 台账写不进去 ⇒ 那是框架
失败：终止、`checked=False` + 明确 reason，不许当成 fault 打回、也不许说"次数没到"。
没有判断面（装配缺口）与"问过、没答上来"分开读：后者是框架失败（`reason` 以
`secretary_unjudged` 开头），前者是"这一趟没人能发这一签"（V 的审阅照算、台账照落）。

"循环跑完而既没签也没打回"不是一条终局：它只可能来自病态配置（门槛被改成 0 / 负数）
或秘书在次数够的那一转既不签也不判出问题 ⇒ 返回值报内部不一致（`checked=False` + 明确
`reason`），绝不写成"次数没到"。逐次读数在返回值的 `review_passes` 里（每项带
`terminal`：这一转是不是终局、是哪一种终局）。
## V 的结论只有两态（业主 2026-11-01 裁定）
业主逐字：「不应该有『看不出来』，『看不出来错』就是没毛病，没有『看不出来对』」。
`成立` / `有毛病` 是对证明的两态结论；"检查器自己没跑成"（没接线 / 输出不是合法 JSON /
字段缺 / 取值不在词表里）不是这两态之一。模型若回「看不出来 / 判不了 / 我无法判断」
这一族措辞，`verifications.parse_verdict` 一律折成 `成立`（它没有找到缺陷 ⇒ 按没毛病收），
`why` 里写明这么收的理由、`verdict_raw` 留住原话。
`verify_proof` 因此有两种失败形态，各自的读数分开：
- `checked=False, reason="judge_not_wired"`：没有模型缝，这次根本没看；-
`checked=False, reason="unparsable"`：看了、但拿回来的东西不是合法结论 ⇒ 不落台账行。
两者都不落台账（`verifications.record_verification` 在没有合法结论时抛`VerificationError`，
绝不写一行"没查成 / 看不出来"来冒充"审过了"）。穷举型证据缺材料同理：
`checked=False, reason="missing_material"`（缺哪一块进 `detail`），台账里也不留行。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping

from .. import schema as S   # 命题号形态的唯一来源（当前宽度 + 旧四位读侧兼容）
from .. import statementbody as _SB   # D2：命题正文的唯一读口
from .. import verifications as VR
from ..store import Store, StoreError

#: V 在台账里的默认实例名（`bit3_payload` 的 `reviewed_by.verifier` 就是它）。
DEFAULT_VERIFIER = "agent-V"

#: 工具层那条路要用的模型缝（与 F 的那一对是同一件事，单一来源在 `llmseam`）。
#:
#: 为什么需要它：`verify.verify_proof` 这条工具路径（M 派 `V.verify_proof` 时走的那条）
#: 拿不到 host 的装配上下文 —— 它只从 `verify_tools.register` 得到 store 与工作区根。
#: 不登记缝的话，"模型驱动那一趟"里的 V 会永远报 `judge_not_wired`，而那不是事实。
#: 默认 `None` = 没接线（环境里有 key 也不改变行为，与 `DEFAULT_LLM_LOOPS` 同一条纪律）。
#:
#: 逐角色的默认缝表在 `llmseam`（`set_role_seam` / `role_seam`）—— 那件事只实现一份，
#: 本文件只把角色 `"V"` 绑上去（下面两个下划线助手是纯绑定，没有自己的状态）。
#: 惰性 import 是必须的：`llmseam` 在 import 期会拉起 `agent_prompts` → `capabilities`
#: → 本模块，模块级 import 会成环。
def _v_role_seam() -> Any:
    from ..llmseam import role_seam

    return role_seam("V")


def _v_set_role_seam(llm: Any) -> None:
    from ..llmseam import set_role_seam

    return set_role_seam("V", llm)


#: `default_llm()` / `set_default_llm(llm)`：V 在工具层那条路上的缝。
default_llm = _v_role_seam
set_default_llm = _v_set_role_seam


class VerificationWiringError(RuntimeError):
    """这次审校没查成：没有模型缝，或拿回来的结论不合法。不是 `有毛病`。"""


#: 业主 2026-10-29：「temperature = 1.0（正常对话的数值）」——只给 V 的审阅调用。
#:
#: 为什么 V 用正常对话的温度而别的角色不动：V 的活是"读出这份证明站不站得住"，
#: 那是理解与判断，不是把同一句话复现三遍。而"可复现"这一条已经由连续 3 次
#: （`verifications.SIGN_STREAK_NEED`）＋ 秘书语义判定承担，不再靠把采样钉死。
#: 别的角色与秘书那一档仍是 `modelgw.DEFAULT_TEMPERATURE`（0.2），一个字节都没动。
REVIEW_TEMPERATURE = 1.0

#: 一次 `verify_proof` 最多替 F 连判几次：「动态等于门槛」（业主 2026-10-30 的两次裁定）。
#:
#: 改前这里是导入期定死的常量（`MAX_REVIEW_PASSES = int(VR.SIGN_STREAK_NEED)`），并按"上界
#: 与门槛是两个数"实现：门槛调高时判到上界就停、如实报"次数没到"。业主 2026-10-30 的第二次
#: 裁定逐字否掉了那个终局：「连判里面如果判出一回秘书语义分析认为是
#: 『有毛病』的，则直接打回了，连判终止」。于是上界与门槛是同一个数，而且「每趟现读」：
#: 循环跑满门槛时，clean 那一档必然已经攒够门槛票 ⇒ "要么签、要么打回"逻辑上必然命中
#: （跑完两头都没有 = 内部不一致，见 `verify_proof` 循环之后那一段）。
#:
#: 为什么不在导入期取一次就够：门槛是配置，默认参数/模块常量都是一次快照；快照与现读漂了
#: 之后，"判几次"会按旧门槛走、而"够不够发签"按新门槛判 —— 同一趟调用里两个数。
def review_pass_bound() -> int:
    """这一趟最多判几转 = 门槛现读（`verifications.SIGN_STREAK_NEED`）。"""
    return int(VR.SIGN_STREAK_NEED)


#: 第 2 次起的提问末尾追加的那一句（"第几次"只加在提问的尾巴上）。
#:
#: 为什么不写进 system 前缀：`llmseam` 的跨 run 前缀缓存按 system 命中，把次数写进
#: 去等于每一趟换一个前缀 —— 三次调用三次 miss，而这一批改动恰好把调用次数乘以三。
#: 写成"追加"还有一个好处：前 `len(prompt)` 个字节三趟逐字相同，判据可以拿它量。
REVIEW_PASS_NOTE = (
    "\n\n（这是同一份证明的第 {n} 次独立重读：只按这一次读到的东西下结论，"
    "不要因为上一次怎么判就跟着判。）")


def _read_only_facts(store: Any, statement_id: str) -> str:
    """只读读数（命题现状 + 文献/实验条数）—— I12 里"只读查询面"那一半。

    刻意只给事实性读数，不给任何人的叙述：V 的判断必须落在证明本身与册子上。
    读不到（表坏 / 无 store）就如实写"读不到"，不许当成"没有记录"。
    """
    lines: list[str] = []
    try:
        rows = list(store.rows("statements"))
    except (StoreError, AttributeError, TypeError) as exc:
        lines.append(f"- 命题台账读不到（{type(exc).__name__}: {exc}）⇒ 这一项没查成")
        rows = []
    hit = next((r for r in rows if str(r.get("stmt_id") or "") == str(statement_id)), None)
    if hit is None:
        lines.append(f"- 命题 {statement_id}：台账里没有这一行（**没登记 ≠ 不存在**）")
    else:
        lines.append(
            f"- 命题 {statement_id}：kind={hit.get('kind')!r} status={hit.get('status')!r} "
            f"evidence_kind={hit.get('evidence_kind')!r} "
            f"quote_verified={hit.get('quote_verified')!r}"
        )
    for table in ("literature", "experiments"):
        try:
            lines.append(f"- {table} 台账：{len(list(store.rows(table)))} 行")
        except (StoreError, AttributeError, TypeError) as exc:
            lines.append(f"- {table} 台账读不到（{type(exc).__name__}: {exc}）⇒ 这一项没查成")
    return "\n".join(lines)


def _citation_material(store: Any, statement_id: str, proof_no: int
                       ) -> tuple[list[dict[str, Any]], str]:
    """这条命题第 `proof_no` 份证明登记的依赖行 + 每条被引命题的正文（V 的引用核实材料）。

    为什么 V 要拿这一份东西（业主 2026-10-26）：F 的"引用"是自然语言描述（"由引理 2"
    "由 Sylow I 可知"），不是逐字引文 ⇒ 只把编号交给 V，它核不出"F 是不是这么用的"。
    所以两样一起给：F 在那条依赖行上写的话，与被引命题的正文摘要。

    三态（不许折平）：读得出来 ⇒ `(材料, "")`；依赖台账或命题台账读不出来 ⇒
    `([], 原因)` —— 后者不是"这一份证明没有引用"，而是这一档没查成（它挡住签字，
    见 `verifications.citation_gate` 的 `problem`）。
    """
    if store is None:
        return [], ""
    try:
        deps = list(store.rows("dependencies"))
    except (StoreError, AttributeError, TypeError) as exc:
        return [], f"dependencies 台账读不到（{type(exc).__name__}: {exc}）"
    try:
        stmts = list(store.rows("statements"))
    except (StoreError, AttributeError, TypeError) as exc:
        return [], f"statements 台账读不到（{type(exc).__name__}: {exc}）"
    return VR.citation_material(statement_id=statement_id, proof_no=proof_no,
                                deps=deps, statements=stmts), ""


def _signed_ledger_row(root: Any, statement_id: str, proof_no: int) -> dict[str, Any]:
    """这一份证明签住的那一行台账（读不到 / 没有 ⇒ 空 dict；只作读数回放用）。

    为什么要有它：已经签过的命题再被送来时，`verify_proof` 短接、不落新行，而那一签的
    逐条引用结论 / findings 只存在于"签住的那一行"上 —— 不回放，调用方拿到的手里会比
    真身更空（"核过、有一条 weaker"与"没有引用"在读数上长得一样）。
    判据本体仍是 `verifications.signed_rows`（"这一批里哪几行签住了"的唯一实现），
    这里只做"按证明号取最后那一行"。
    """
    try:
        rows, _bad = VR.list_verifications(root, statement_id=statement_id, limit=None)
    except (OSError, VR.VerificationError):
        # 台账读不出来 ⇒ 回放不了（不是"没有引用"）。调用方在 `detail` 里照实说。
        return {}
    one = [r for r in rows if VR.proof_no_of(r) == int(proof_no)]
    signed = VR.signed_rows(one)
    return dict(signed[-1]) if signed else {}


class AgentV:
    """验证者。三个 handler 与 `specs/v.py` 的 `handler_name` 逐字同名。

    `llm` 是一个"能回答一段提示词的模型缝"：给 `LlmSeam`（有 `.ask`）、
    给一个 client（有 `.complete`）、或给一个可调用对象都行。不给就是没接线 ——
    `verify_proof` 会如实报 `judge_not_wired`，绝不用确定性文本假装审过
    （审校是一件只有模型能做的事，没有它就没有结论）。
    """

    def __init__(self, store: Any, *, workspace_root: str | Path | None = None,
                 llm: Any = None, config: Mapping[str, Any] | None = None,
                 log: Callable[[str], None] | None = None,
                 secretary: Any = None) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        root = workspace_root or getattr(store, "root", None) or "."
        self.workspace_root = Path(root).resolve()
        self.llm = llm
        self.actor = str(self.cfg.get("actor") or DEFAULT_VERIFIER)
        self.log = log
        #: V 自己的秘书（业主 2026-10-29：发不发签由它持有）。
        #:
        #: 为什么它有一个构造形参：`agent_loop.run_role` 那条路在装配期就已经造好了一名
        #: 秘书（并按名册绑了实例）—— 那一条应当原样交进来，而不是在这里另造一个
        #: （两个对象 = 两本台账）。不给 ⇒ 由 :meth:`_secretary` 惰性装配：
        #: `draft/125` §三点名的"工具路径造不出秘书"那个缺口，落点就在这一处
        #: （工具层 `tools/verify_tools.py` 是 FC-27，不许改；`AgentV` 不是）。
        self.secretary = secretary
        #: 惰性装配只试一次（并且试过就要记住）："没缝"不是一个每签都要重试的错误，
        #: 而"没试过"与"试了没成"必须在读数上分得开。
        self._secretary_tried = secretary is not None
        #: 装配读数（懒装配失败/没缝时的那一句为什么；空串 = 没出问题或还没试）。
        self.secretary_problem = ""
        self.logs: list[str] = []

    # ------------------------------------------------------------------ 内部

    def _emit(self, message: str) -> None:
        self.logs.append(message)
        if self.log is not None:
            self.log(message)

    def _seam(self) -> Any:
        """这次审校用哪个模型缝：显式给的最优先，否则按角色现造一个。

        现造的那一个不抛：`LlmSeam.for_role` 在没有 key 时给出 `wired=False` 的缝，
        而 `ask` 会返回 `problem="judge_not_wired"` —— 三态纪律要的正是这个：
        "没接线"是一条读数，不是一次异常。
        """
        if self.llm is not None:
            return self.llm
        from ..llmseam import LlmSeam
        from ..tokenmeter import TokenMeter

        return LlmSeam.for_role("V", session_root=self.workspace_root,
                                meter=TokenMeter(self.store) if self.store is not None else None)

    def _ask(self, prompt: str) -> tuple[str, str]:
        """问一次模型。返回 `(文本, 失败原因)`；失败原因空 = 拿到了文本。"""
        seam = self._seam()
        if seam is None:
            return "", "judge_not_wired"
        try:
            if hasattr(seam, "ask"):
                # 业主 2026-10-29：V 的审阅调用按正常对话的温度问（`REVIEW_TEMPERATURE`
                # = 1.0）；别的角色没有这一格，仍是 `modelgw.DEFAULT_TEMPERATURE`（0.2）。
                call = seam.ask(prompt, task_id="", temperature=REVIEW_TEMPERATURE)
                problem = str(getattr(call, "problem", "") or "")
                text = str(getattr(call, "text", "") or "")
                if problem and not text:
                    return "", problem
                return text, ("" if text else "empty_reply")
            if hasattr(seam, "complete"):
                reply = seam.complete(prompt)
                if isinstance(reply, Mapping):
                    return str(reply.get("text") or reply.get("content") or ""), ""
                return str(reply or ""), ""
        except Exception as exc:  # noqa: BLE001 —— 缝的异常是"没查成"，不是"有毛病"
            return "", f"{type(exc).__name__}: {exc}"
        return "", "judge_not_wired"

    # ---------------------------------------------------- 秘书（业主 2026-10-29）

    def _secretary(self) -> Any:
        """这一趟的 V 秘书（没有 ⇒ `None`，理由在 `self.secretary_problem`）。

        ## 为什么装配点在这里（`draft/125` §三的那个缺口）
        V 走循环时 `agent_loop.run_role` 已经装配好秘书并交进来；V 走工具路径
        （M 派 `V.verify_proof`）时，工具层 `tools/verify_tools.py:_agent_v` 只拿得到
        store 与工作区根 —— 它造不出秘书，而它是 FC-27（禁改区），不许为了接线改它。
        所以装配落在 `AgentV` 自己这一层：它是被那一处构造的，不是禁改区。

        ## 没缝 ≠ 有问题
        `secretary.for_role_wired` 在设置里没有秘书那一档 key 时不装空缝
        （那会把"从来没有判断面"写成"试过了、没成"）⇒ 这里的秘书 `seam is None`，
        `judge` / `decide_sign_issuance` 会如实报 `checked=False`。业主口径：
        装配没接上时秘书判定必须报 `checked=False`，且不发签（`draft/125` §三）。
        """
        if self.secretary is not None:
            return self.secretary
        if self._secretary_tried:
            return None
        self._secretary_tried = True
        try:
            from .. import secretary as _SEC

            got = _SEC.for_role_wired("V", root=self.workspace_root, store=self.store)
        except Exception as exc:  # noqa: BLE001 —— 造不出来是"没有秘书"，不是"没问题"
            self.secretary_problem = (f"V 的秘书装配失败（{type(exc).__name__}: {exc}）⇒ "
                                      "这一趟没有秘书：判定与发签都按 checked=False 读")
            self._emit(f"verify_proof：{self.secretary_problem}")
            return None
        self.secretary = got
        if not str(getattr(got, "seam", "")):
            self.secretary_problem = (f"V 的秘书没有判断面（{got.model_source or '没有模型缝'}）"
                                      "⇒ 判定与发签按 checked=False 读（不是「没问题」）")
        return got

    def _judge_v_reply(self, reply: str, verdict: Mapping[str, Any],
                       no: int, *, statement_id: str = "") -> dict[str, Any]:
        """问秘书：V 这段回复有没有指出缺陷（业主 2026-10-29 的 B 段）。

        材料只给 V 的回复正文 + 这一签的 `verdict` / `defect_step`；不给 F 的证明
        （I12：V 的秘书读叙述本来就被 `may_read_narrative` 禁，这里不开那个口子）。

        轴只有两档（业主 2026-10-30 第三次裁定：「只要不是完全没毛病都叫有毛病」）：
        `clean` / `fault`。拿不准、只挑出一个小记号问题、只说"我没逐行验证"——都是 fault
        （`secretary.V_REPLY_AXIS` 只有两格：词表外的一律"不采信" ⇒ `checked=False`）。

        没有秘书 / 没判断面 ⇒ `checked=False` + `axis=""`：那是"没查成"，不是一种判定，
        更不是"没问题"（连续计数里既不算票、也不清零）。
        """
        sec = self._secretary()
        if sec is None:
            return {"checked": False, "axis": "", "unwired": True, "decision": "",
                    "reason": (self.secretary_problem
                               or "这一趟没有 V 的秘书 ⇒ 语义判定没查成（不是「没问题」）")}
        return sec.judge_v_reply(reply=str(reply or ""),
                                 verdict=str(verdict.get("verdict") or ""),
                                 defect_step=verdict.get("defect_step"),
                                 statement_id=str(statement_id or ""),
                                 proof_no=no,
                                 task_id=str(self.cfg.get("task_id") or ""))

    def _wash_v_reply(self, reply: str, verdict: Mapping[str, Any], no: int, *,
                      statement_id: str = "") -> dict[str, Any]:
        """问秘书：把这段意见洗成能转达给 F 的文本（业主 2026-10-29 的 C 段）。

        秘书不在场 ⇒ `checked=False, refused="secretary_unavailable"`，且不返回原文
        （`wash_v_reply` 的纪律：洗不出来就不输出原文）。
        """
        sec = self._secretary()
        if sec is None:
            return {"checked": False, "washed": False, "text": "", "findings": [],
                    "dropped": [], "refused": "secretary_unavailable",
                    "reason": (self.secretary_problem
                               or "这一趟没有 V 的秘书 ⇒ 洗不出来（不输出原文）")}
        return sec.wash_v_reply(reply=str(reply or ""),
                                verdict=str(verdict.get("verdict") or ""),
                                defect_step=verdict.get("defect_step"),
                                statement_id=str(statement_id or ""), proof_no=no,
                                task_id=str(self.cfg.get("task_id") or ""),
                                label=str(verdict.get("label") or ""))

    def _decide_sign_issuance(self, statement_id: str, proof_text: str, no: int,                              verdict: Mapping[str, Any], *,
                              row: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """问秘书：这一签发不发（业主 2026-10-29 的 A 段，追加口径：落盘也由它做）。

        `row` 是 `record_verification(flip=False)` 刚落下的台账那一行：秘书据此知道
        "这一签已经在台账上了"（连续次数不用再加一票），并在判发之后由它自己调
        `sign_statement(append_ledger=False)` 翻位。

        没有秘书 ⇒ `checked=False, issue=False, issued=False`：不放签。这一句是
        fail-closed 的那一半（`draft/125` §三：「装配没接上时，秘书判定必须报
        checked=False」；追加口径之后它是主路径：发签权在秘书手上，秘书不在场就等于
        不能发签）。
        """
        sec = self._secretary()
        if sec is None:
            return {"checked": False, "issue": False, "issued": False, "streak": 0,
                    "projected": 0, "need": VR.SIGN_STREAK_NEED, "streak_ok": False,
                    "decision": "", "writeback": {}, "landed": False,
                    "reason": (self.secretary_problem
                               or "这一趟没有 V 的秘书 ⇒ 没有人发这一签（不放签）")}
        return sec.decide_sign_issuance(statement_id=statement_id, proof_text=proof_text,
                                        proof_no=no, verdict=verdict, row=row,
                                        task_id=str(self.cfg.get("task_id") or ""))

    # ---------------------------------------------------- 引用核实（业主 2026-10-26）

    def _citation_admissibility(self, kind: str) -> bool:
        """被引命题的档位够不够格被引（逐字：「proof_review级及以上才可引用」）。

        为什么单独一个具名方法：这一格是"档位判据"的唯一落点，而它必须能被打桩 ——
        判据里的反真空就是把它打成恒放行 / 恒拒绝，看档位那两条是不是跟着红。
        真身只有一处（`verifications.evidence_kind_admissible`，允许集合按
        `schema.EVIDENCE_KINDS` 的强弱顺序现算），这里不抄第二份词表。
        """
        return VR.evidence_kind_admissible(kind)

    def _citation_checks(self, checks: list[dict[str, Any]],
                         material: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """引用核实的定稿：模型给的那几档只是原料（覆盖 / 档位 / 不在册在这里定）。

        同样是可打桩的一格：把它打成恒 `consistent`，负控（引错、引强）必须跟着红 ——
        否则那几条判据量的就不是"引用真的被核过"，而是"模型说了什么"。
        """
        return VR.reconcile_citation_checks(checks, material)

    # ------------------------------------------------------------------ 三个动作

    def verify_proof(self, statement_id: str, proof_text: str = "",
                     readonly_facts: str = "", proof_no: Any = 1,
                     **kw: Any) -> dict[str, Any]:
        """把一份证明整体重读一遍，落一行验证台账（`v-NNNN`）。

        ## 证明号与正文必须绑在一起（2026-10-22 审计第 2 条）

        `proof_no` 说"审的是第几份"，送进提示词的正文必须是那一份的正文：
        参数没给正文 ⇒ 取 `verifications.proof_text_of(该行, proof_no)`；参数给了正文 ⇒
        它必须与盘上那一份是同一份（sha 相同），否则拒（`proof_text_mismatch`）——
        记到 `#pN` 上会把 sha 与证明号错配。改前这里是 `if not text: text =
        hit["proof_text"]`：说"审 #p2"却把 #p1 的正文送进提示词，而 sha 记在 #p2 头上，
        于是"#p1 没被牵连"与"#p2 真的审过"两句话同时是假的。
        不给证明号 ⇒ canonical（`#p1`）；给了但认不出（`0` / `'abc'` / `2.0`）⇒
        `checked=False, reason="bad_proof_no"`（改前 `or 1` 静默折成 `#p1`：签错一份
        证明，台账上照样写着 `verdict=成立`）；命题的证明清单里没有 `#pN` ⇒
        `checked=False, reason="no_such_proof"`；那一份在、正文空 ⇒ `no_proof_text`。
        以上四条都不落台账行。

        ## 台账那一行有没有落地（2026-10-22 审计第 1 条）

        写位失败可能整笔回滚，而回滚（`verifications._rollback_append`）会把台账那一行
        一起抹掉。改前返回值只看 `verdict` ⇒ 台账 0 字节而返回说"签住了第 3 位"。
        现在只看 `record_verification` 返回行上的 `checked`：没落地 ⇒ 本方法
        `checked=False`、`signed_bit3=False`、`reason` 逐字写明"台账那一行被撤回 /
        没写成"，调用方据此知道必须重签（`review_write.re_sign_required`）。

        ## 键集合在三条返回路径上完全相同（与 `verify.evidence_for` 同一纪律）

        "没查成"（`checked=False`）不是工具失败（同 `verify.check_formal` 的`no_backend`：那是没查成，不是查了没过）⇒ 照样
        `ok` 返回、键一个不少，由 `checked` / `reason` 说出真相。少给键会让下游把"这一格没有读数"读成"这一格是零"。

        ## 一次调用里连判几次：只有两种终局（业主 2026-10-30 的两次裁定）

        "连续 3 次没问题"是 V 判完接着再判，不是 F 交三次。所以本方法自己问模型最多
        :func:`review_pass_bound` 次（= 门槛现读，同一份正文、同一个 `proof_no`），每一转
        各落一行台账、各问一次秘书。终局只有两种：签上了（连续 `need` 转 clean ⇒ 秘书发签）
        或打回了（任一转判出 fault / 结论不是成立 ⇒ 那一转就是终局，立刻停）。
        "跑完而两头都没有"报内部不一致（`checked=False`），不当成一条终局。
        逐次读数在返回值的 `review_passes` 里（每项给 `pass` / `axis` / `decision` /
        `streak` / `need` / `streak_ok` / `issue` / `issued` / `verdict` /
        `verification_id` / `terminal`），而 `secretary_judge` / `sign_issuance` 仍是
        "最后一转"那两格。

        ## 已经签过的命题不再送审（2026-10-31）

        命题行上这一份证明的第 3 位已经为真（`bits.reviewed=True`，逐条表里这一份也
        签着）⇒ 这一趟不进连判循环，直接返回：`checked=True`、`signed_bit3=True`、
        `review_passes=[]`、`reason="already_signed"`，台账一行都不落、模型一次都不问。
        为什么要有这一格：真机冒烟（工作区 `projects/abelian-smoke-20261030c`）上一条
        已经签过的命题又被送审了四趟，其中一趟被判成 fault，读侧把它当成"有毛病要打回"，
        F 于是被叫去改一份已经签过的证明（真机证据在 `draft/142` §四）。返回值里的
        引用核实与 findings 取"签住的那一行台账"的读数（这一趟没有新判，不许现造）；
        改稿之后签的那一份与现在这一份不是同一份正文 ⇒ 读侧把它读成过期，这一趟不短接、
        照常重审。
        """
        del kw  # 声明层没有别的参数；多给的键在这里不静默生效
        out: dict[str, Any] = {
            "checked": False,
        "kind": "",          # 三条返回路径键集合一致（没查成时空串）
            "statement_id": str(statement_id or "").strip(),
            "verification_id": "",
            "verdict": "",
            "defect_step": None,
            "findings": [],
            "unresolved_errors": 0,
            "proof_sha256": "",
            "proof_no": None,
            "proof_chars": 0,
            "signed_bit3": False,
            "reviewed_by": {},
            "bits": {},
            # 写回读数（`statement_writeback`）：成功支与"台账那行没落地"那一支都会给，
            # 而"没查成"那几条路径改前没有这一格 ⇒ 三条返回路径的键集合不同，
            # 声明只能二选一（要么模型看不见这一格，要么声明里多一格永远不出现的）。
            # 三态纪律取法：键在这里就存在，`{}` = 这一趟没有写回可报。
            "review_write": {},
            "ledger": "",
            "reason": "",
            "detail": "",
            # 穷举型证据会审那一档的四格（普通逐行走查路径上它们是空的，但键要在：
            # "这一格没有读数"与"这一格是空字符串"必须由键的存在区分开）。
            "exhaustion_review": {},
            "signer": "",
            "proof_authors": [],
            "report_path": "",
            "checks": [],
            "missing": [],
            # 引用核实那一档（业主 2026-10-26）：材料（被引命题 + 正文摘要）/ 逐条结论 /
            # 签字前置读数。三条返回路径键集合相同 ⇒ 它们必须在初值里就存在。
            "citations": [],
            "citation_checks": [],
            "citation_gate": VR.citation_gate([]),
            # 业主 2026-10-29 的两格：秘书语义判定（B 段，两档）与发签决定（A 段）。
            # 键无条件存在（"没判成"由 `checked=False` 说，不靠少给键来表达）。
            "secretary_judge": {},
            "sign_issuance": {},
            # 业主 2026-10-30：这一趟自己连判了几次、每一转的判定档与连续次数。
            # 同理无条件存在（一次都没判成时是空数组 —— "没判过"与"判了 0 转"不靠少给键分）。
            "review_passes": [],
        }
        sid = out["statement_id"]
        if not S.is_valid_id(sid):
            out["reason"] = "bad_statement_id"
            out["detail"] = (f"命题号必须是 {S.ID_DIGITS} 位十进制（旧数据里的 4 位号仍可读），"
                             f"收到 {statement_id!r}")
            return out
        # 证明号先判：没给（`None` 或缺省）⇒ canonical；给了但认不出 ⇒ 拒。
        # 改前 `proof_no=0` 一路被 `or 1` 折成 #p1，"号给错了"没有任何读数。
        try:
            no = VR.proof_no_strict(proof_no)
        except VR.VerificationError as exc:
            out["reason"] = "bad_proof_no"
            out["detail"] = f"{exc}；这一格没查成，台账里不留行"
            self._emit(f"verify_proof({sid})：{exc} —— 没查，不落台账行")
            return out
        out["proof_no"] = no
        text = str(proof_text or "")
        statement_full = ""
        if self.store is not None:
            try:
                hit = next((r for r in self.store.rows("statements")
                            if str(r.get("stmt_id") or "") == sid), None)
            except (StoreError, AttributeError, TypeError):
                hit = None
            if hit is None:
                # 「2026-10-17 补」（业主 2026-10-17 授权动禁改区；亲测抓到的缺口）：
                # 命题「不在册」时不许给 verdict。原实现接着用"（命题 … 的正文没读到）"
                # 当占位把证明审下去 ⇒ 返回 `checked=True` ＋ 一个 verdict，调用方读起来
                # 像"「命题与证明都审过了」"，而"这个命题在不在册"没有任何一处说过。
                # 按本模块「既有纪律」（`checked=False` ⇒ 「不落台账行」，见上面
                # `no_proof_text` / `problem` 两处）在这一格「拒判」并给出路。
                #
                # ---- D-34（2026-10-24）：但穷举型证据的那一签不许丢 ----
                #
                # r34b 的真机现场：`statements` 0 行，V 审完判「成立」，而
                # `record_verification` 要一个合法命题号才写得出台账 ⇒ 那一签没有落点，
                # 只能 escalation，结论丢了。业主的模型是"V 的签＝盖章"，盖章不该因为
                # "那一页还没装订进册"而作废 ⇒ 这一档改走 `verifications/pending/<sha>`：
                # 那一签按对象内容的 sha 落盘，B 登记之后按同一个 sha 认领
                # （`numericproof.latest_third_party_sign` 的第二路）。顺序于是不再重要。
                pending = self._review_without_statement(text=text, no=no)
                if pending is not None:
                    return self._finish_pending(out, statement_id=sid, no=no, got=pending)
                out["kind"] = "statement_missing"
                out["reason"] = "statement_missing"
                out["detail"] = (f"命题 {sid} 不在 statements 里 ⇒ **没审**"
                                 "（不是「审了、有毛病」）；台账里**不留行** —— "
                                 "留一行会把「没查成」冒充成「审过了」。"
                                 "先把这条命题登记了（B 的 register_statement）再来审。")
                self._emit(f"verify_proof({sid})：命题不在册 ⇒ 没审，不落台账行")
                return out
            statement_full = _SB.body_of(hit)
            # ---- 2026-10-23 晚（业主：「E 写的报告要能落下来，且 V 也要会审这种东西」）
            #
            # 穷举型证据（证明栏第 ① 段是一份数值实验程序）不按"逐行读证明文本"审：
            # 要审的是那份程序与 E 写的 ②③ 对不对得上（程序在不在、搜索空间的数在代码里
            # 有没有着落、剪枝/对称性有没有解释、边界写没写、结论是不是穷尽、形式化那一格
            # 填的类别对不对）。判据本体只有一处：`exhaustionreport.review`；这里只负责
            # 把它的三态结论翻成一次审校（落台账、`成立` 才签第 3 位）。
            #
            # 三态里最要紧的一档是「缺材料」：报告没落地（E 的 ②③ 没落成盘上那份读数）
            # 时不许判成立 —— 而业主 2026-11-01 的裁定把「看不出来」这一档整个取消了，
            # 所以缺材料落的是没查成（`checked=False` + `reason="missing_material"`）：
            # 台账里不留行，缺哪一块逐条进 `detail`。它既不是"找到了缺陷"（不许打回 F），
            # 也不是"没找到缺陷"（不许判成立）—— 材料补齐之后重新送审。
            from .. import exhaustionreport as _ER

            _exp_rows: list = []
            try:
                _exp_rows = list(self.store.rows("experiments"))
            except (StoreError, AttributeError, TypeError):
                _exp_rows = []
            if _ER.is_exhaustion_column(hit, _exp_rows):
                _reviewed = _ER.review(workspace_root=self.workspace_root,
                                       statement=hit, experiments=_exp_rows)
                out["kind"] = "numeric_evidence"
                out["exhaustion_review"] = dict(_reviewed)
                out["signer"] = str(_reviewed.get("signed_by") or "")
                out["proof_authors"] = list(_reviewed.get("proof_authors") or [])
                out["report_path"] = str(_reviewed.get("report_path") or "")
                self._emit(
                    f"verify_proof({sid})：穷举型证据会审 ⇒ {_reviewed.get('verdict')}"
                    f"（{len(_reviewed.get('checks') or [])} 项检查，"
                    f"缺材料 {_reviewed.get('missing') or []}）")
                _text_for_ledger = text or str(hit.get("proof_text") or "")
                # 业主 2026-10-29：穷举型证据这一路也走同一对秘书判定（B 段 / A 段）。
                # 这一路的"回复"没有模型原文（会审是机械的七项核对）⇒ 材料给的是
                # 会审自己的结论那一句，而不是 F 的证明正文（I12 同一条纪律）。
                _n_verdict = _ER.verdict_of(_reviewed)
                _missing = [str(m) for m in (_reviewed.get("missing") or [])]
                if str(_n_verdict.get("verdict") or "") == _ER.VERDICT_UNKNOWN:
                    # ---- 缺材料 ⇒ 没查成（业主 2026-11-01：不存在「看不出来」这一档）----
                    #
                    # 会审本身跑完了（七项逐项有读数），但盘上缺了该有的那一块：这既不是
                    # "找到了缺陷"（不许打回 F），也不是"没找到缺陷"（不许判成立）。
                    # 诚实的那一格只有"没查成"：`checked=False` + 明确 reason，台账里不留行
                    # （留一行会把"没查成"冒充成"审过了"）。缺哪一块逐条进 detail。
                    out["checked"] = False
                    out["reason"] = "missing_material"
                    out["detail"] = (
                        f"穷举型证据会审缺材料（{'; '.join(_missing) or '没点名'}）⇒ 这一格"
                        "**没查成**：既不判「成立」（缺材料不许判成立）、也不判「有毛病」"
                        "（没有找到缺陷，不许按缺陷打回 F），台账里不留行。"
                        "补上缺的那几块之后重新送审（会审的七项读数在 exhaustion_review 里）。")
                    self._emit(f"verify_proof({sid})：穷举会审缺材料 —— 没查成，不落台账行"
                               f"（{_missing}）")
                    return out
                # 业主 2026-10-29：穷举型证据这一路也走同一对秘书判定（B 段 / A 段）。
                # 这一路的"回复"没有模型原文（会审是机械的七项核对）⇒ 材料给的是
                # 会审自己的结论那一句，而不是 F 的证明正文（I12 同一条纪律）。
                _n_reply = (f"穷举型证据会审：结论 {_n_verdict.get('verdict')!r}"
                            f"（{len(_reviewed.get('checks') or [])} 项检查，"
                            f"缺材料 {_missing}）")
                _n_judge = self._judge_v_reply(_n_reply, _n_verdict, no, statement_id=sid)
                out["secretary_judge"] = dict(_n_judge)
                try:
                    _row = VR.record_verification(
                        self.workspace_root, statement_id=sid,
                        proof_text=_text_for_ledger,
                        verdict=_n_verdict, verifier=self.actor,
                        submission_id=str(self.cfg.get("submission_id") or ""),
                        store=self.store, proof_no=no,
                        # D-34：这一签审的对象是 E 那份报告（它的字节 sha256 与相对路径）。
                        # 记进台账之后，B 的入库闸就能"按对象内容找签"（B 的报告是目录，
                        # 索引里那四格写的就是这一份），于是"谁先谁后"不再重要。
                        object_sha256=str(_reviewed.get("report_sha256") or ""),
                        object_path=str(_reviewed.get("report_path") or ""),
                        secretary_judge=_n_judge,
                        # 业主 2026-10-29 追加口径：V 只落台账，翻位交给秘书。
                        flip=False)
                except (VR.VerificationError, OSError) as exc:
                    out["reason"] = "ledger_unwritable"
                    out["detail"] = (f"台账写不进去（{type(exc).__name__}: {exc}）⇒ "
                                     "这一格没查成（不落台账、不改位、必须重签）")
                    self._emit(f"verify_proof({sid})：台账写不进去 —— 会审没落地")
                    return out
                _n_word = str(_n_verdict.get("verdict") or "")
                _n_axis = str(_n_judge.get("axis") or "")
                _n_judged = bool(_n_judge.get("checked"))
                if _n_word == "成立" and _n_judged and _n_axis == "clean":
                    # 只有"判过了、没问题、结论成立"这一档才问"这一签发不发"。
                    _n_issuance = self._decide_sign_issuance(sid, _text_for_ledger, no,
                                                             _n_verdict, row=_row)
                else:
                    # 其余那一档一律不发签，读数由 `_terminal_issuance` 给（与逐行走查
                    # 那条链同一套判据：verdict 先行，其次 fault，最后才是没查成）。
                    _n_issuance = self._terminal_issuance(
                        sid, no, text=_text_for_ledger, row=_row,
                        judgment=_n_judge, verdict=_n_verdict)
                out["sign_issuance"] = dict(_n_issuance)
                if _n_word == "成立" and not _n_judged and not bool(_n_judge.get("unwired")):
                    # 秘书问不出来（这一问失败）⇒ 框架失败（业主 2026-10-30 第三次裁定
                    # 第 3 条）：终止 + checked=False + 明确 reason；不许当成 fault 打回，
                    # 也不许报"签住了"。装配缺口（unwired）不在这一支：那一档 V 的会审
                    # 确实做完了，只是没人能发这一签。
                    out["checked"] = False
                    out["reason"] = ("secretary_unjudged：会审这一转秘书问不出来"
                                     "（没查成，不是判定）")
                    out["detail"] = (
                        "穷举型证据的会审做完了、台账那一行也落了，但秘书的语义判定没查成"
                        f"（{str(_n_judge.get('reason') or '没有给理由')[:300]}）⇒ 这一签不发，"
                        "连判到此为止。处置：核对 V 的秘书装配与模型缝"
                        "（`secretary.for_role_wired(\"V\", ...)`），判定接上之后重签。"
                        "这一档不是「有毛病」——不许按缺陷打回 F。")
                    self._emit(f"verify_proof({sid})：会审这一转秘书没查成"
                               f"（{str(_n_judge.get('reason') or '没有给理由')[:120]}）")
                    return out
                return self._finish_numeric(out, statement_id=sid, no=no, row=_row,
                                            reviewed=_reviewed)
            # 正文只从"证明号指定的那一份"取（2026-10-22 审计第 2 条）：
            # 改前不看号，一律读 canonical ⇒ "审 #p2"拿的是 #p1 的正文。
            listed = {int(n) for n, _ in VR.proof_list(hit)}
            if no not in listed:
                out["reason"] = "no_such_proof"
                out["detail"] = (f"命题 {sid} 的证明清单里没有 #{no}"
                                 f"（有：{sorted(listed)}）⇒ 没审、台账里不留行；"
                                 "不许拿别的证明的正文顶替")
                self._emit(f"verify_proof({sid})：没有 #{no} 那一份证明 —— 没审，不落台账行")
                return out
            on_disk = VR.proof_text_of(hit, no)
            if not text:
                text = on_disk
            elif on_disk.strip() and VR.proof_sha(on_disk) != VR.proof_sha(text):
                # 给了正文、但那一份证明现在不是这一串字 ⇒ 拒。记到 #pN 上会让台账那一行
                # 的 `proof_sha256` 与它记的 `proof_no` 各说一件事（审计第 2 条的后半）。
                out["reason"] = "proof_text_mismatch"
                out["detail"] = (f"参数给的正文与命题 {sid} 上 #{no} 那一份不是同一份"
                                 f"（参数 sha {VR.proof_sha(text)[:12]}…，盘上 #{no} 的 sha "
                                 f"{VR.proof_sha(on_disk)[:12]}…）⇒ 拒绝：记到 #{no} 会把 sha "
                                 "与证明号错配；要么给那一份的正文，要么给对 proof_no")
                self._emit(f"verify_proof({sid})：正文与 #{no} 不符 —— 没审，不落台账行")
                return out
        if not text.strip():
            out["reason"] = "no_proof_text"
            out["detail"] = ("没有可审的证明全文（参数里没给，statements 里也没有）"
                             "⇒ 这一格没查成")
            return out

        # ---- 2026-10-31：已经签过的不再送审（真机 `projects/abelian-smoke-20261030c` 的 v9–v12）----
        #
        # 那 12 行台账全属同一份正文（同一个 `proof_sha256`）：v6–v8 三转 clean 之后第 3 位
        # 已经翻真（`statements[000001].bits.reviewed = True`），v9–v12 却还在被送审，其中
        # v10 被判成 fault ⇒ 读侧（`agent_loop.v_rejections_digest` → `deliver_v_verdicts`）
        # 把一条已经签过的证明当成"有毛病要打回"，F 于是被叫去改一份已经签过的稿
        # （真机证据在 `draft/142` §四）。
        #
        # 判据只有一句：命题行上这一份证明的第 3 位已经为真 ⇒ 这一趟没有可做的审校。
        # 三样读数由 `verifications.bit3_already_signed` 一路给（纯读命题行，不看台账）：
        # `checked=True`（这一格有结论）、`signed_bit3=True`（位真的在那儿）、
        # `review_passes=[]`（这一趟一转都没判）；台账一行都不落、模型一次都不问。
        #
        # 短接必须落在"读完 statements 行之后、进连判循环之前"：放进循环里会让第一转先花掉
        # 一次模型调用（正是真机 v9 那一行），放在读行之前则拿不到那个位。决定"签过没有"
        # 的那一问也不许读台账：台账能回答"这一签怎么来的"，但"这一位现在是不是真的"只有
        # 命题行能回答 —— 依据台账短接会让"先清掉那一位再重审"永远发生不了（台账是追加式
        # 文件，没有任何调用点会为了重审去改写它）。
        #
        # 没有 store 就没有命题行可读 ⇒ 判不了，照常审（重审是安全方向：多花一次模型调用，
        # 不会把已签的证明误当成没签）。
        if self.store is not None:
            already = VR.bit3_already_signed(hit, proof_no=no, proof_text=text)
            if bool(already.get("signed")):
                reviewed_by = dict(already.get("reviewed_by") or {})
                signed_id = str(reviewed_by.get("verification_id") or "")
                # 这一趟没有新判任何事，但"那一签当时读到了什么"必须照得出来：引用材料
                # （这一份证明的依赖行 + 被引命题正文摘要）现读，逐条引用结论 / findings /
                # 引用闸回放签住的那一行台账（`ledger` 指向它）。为什么必须回放：读者手上的
                # 返回值不许比真身更空 —— 空 `citation_checks` 会让"核过、有一条 weaker"
                # 与"没有引用"在读数上长得一样（那正是 `returns=` 那一格在治的病）。
                # 回放不是现造：来源只有盘上那一行，找不到就照实说找不到。
                signed_row = _signed_ledger_row(self.workspace_root, sid, no)
                citations, citations_problem = _citation_material(self.store, sid, no)
                for item in citations:
                    # 档位判据走可打桩的那一格（`_citation_admissibility`，与循环里同一处）。
                    item["admissible"] = bool(
                        self._citation_admissibility(item.get("evidence_kind") or ""))
                # 引用闸也是纯函数（`citation_gate`）：台账只在"这一档没查成"时存那一格
                # （`problem` 非空，见 `record_verification`），其余情况按行上的逐条结论现算
                # —— 两处读法必须与循环里那一趟相同，否则回放出来的闸与那一签当时的闸不同。
                replayed_checks = list(signed_row.get("citation_checks") or [])
                stored_gate = signed_row.get("citation_gate")
                if isinstance(stored_gate, Mapping) and stored_gate:
                    replayed_gate = dict(stored_gate)
                else:
                    replayed_gate = VR.citation_gate(
                        replayed_checks,
                        problem=str(citations_problem if not signed_row else ""))
                out.update({
                    "checked": True,
                    "signed_bit3": True,
                    # 位与凭据都从命题行读回来（这一趟没有新的一签，所以不许现造一份）。
                    "bits": dict(already.get("bits") or {}),
                    "reviewed_by": reviewed_by,
                    "verification_id": signed_id,
                    "verdict": str(signed_row.get("verdict") or reviewed_by.get("verdict") or ""),
                    "defect_step": signed_row.get("defect_step"),
                    "findings": list(signed_row.get("findings") or []),
                    "unresolved_errors": int(signed_row.get("unresolved_errors") or 0),
                    "proof_sha256": str(already.get("proof_sha256") or VR.proof_sha(text)),
                    "proof_chars": int(signed_row.get("proof_chars") or len(text)),
                    "citations": citations,
                    "citation_checks": replayed_checks,
                    "citation_gate": replayed_gate,
                    "ledger": (f"{VR.VERIFICATIONS_DIR}/{sid}.jsonl#{signed_id}"
                               if signed_id else ""),
                    # 这一趟一转都没判：读侧不许把它读成"判过、没问题"，也不许读成"没判过
                    # 所以还要再审"—— 短接这件事由 `reason` 说。
                    "review_passes": [],
                    "reason": "already_signed",
                    "detail": (f"命题 {sid} 的 {VR.proof_label(sid, no)} 第 3 位已经为真"
                               f"（签在 {signed_id or '（台账没记编号）'}）⇒ 这一趟没有可做的"
                               "审校：不再重复审、不落新台账行、不问模型。上面那些引用核实与"
                               "findings 是那一签留下的读数，不是这一趟新判的"
                               f"（台账那一行：{VR.VERIFICATIONS_DIR}/{sid}.jsonl"
                               f"#{signed_id or '?'}）。"
                               + ("这一趟的依赖台账读不出来，引用材料这一格没取成："
                                  f"{citations_problem}；" if citations_problem else "")
                               + ("台账里没找到那一签的原文 ⇒ 逐条引用结论与 findings "
                                  "取不到（那不是「核过、没有引用」）。"
                                  if signed_id and not signed_row else "")
                               # 引用闸那一句原话照旧带出来（挡签 / 弱形式 / 没查成都在
                               # 这一个人话里点名）—— 正常那一趟的 `detail` 就是它。
                               + (f"引用核实那一档的读数：{replayed_gate.get('why')}"
                                  if replayed_gate.get("why") else "")
                               + ("要重新审一份已经签过的证明，要么先改稿（签的是旧版正文时"
                                  "读侧会把它读成过期，这一趟就不会短接），要么先把那一位清掉。")),
                })
                self._emit(f"verify_proof({sid})：{VR.proof_label(sid, no)} 这一条已经签过了"
                           f"（第 3 位为真，签在 {signed_id or '（台账没记编号）'}）"
                           "—— 不再重复审，不落新台账行、不问模型")
                return out

        # ---- 引用核实的材料（业主 2026-10-26：V 要核 F 的引用，而 F 的引用不是逐字引文）----
        #
        # 这一份材料 = 这条命题第 `no` 份证明登记的依赖行（`used_by` / `path_group` /
        # `source_stmt_id` / F 写的那句话）+ 每条被引命题的正文摘要。不给编号了事：
        # 只给编号，V 核不出"F 是不是这么用的、这条够不够格被引"。
        # `citations_problem` 非空 = 台账读不出来（不是"没有引用"）：它挡住签字。
        #
        # 2026-10-30 起这一份材料是"三转共用"的：同一份正文、同一个证明号 ⇒ 依赖行与
        # 被引命题摘要不会因为"第几次读"而变。每一转各自去读一遍盘只会多三次 IO，
        # 还会让三转的审阅对象有可能不同 —— 那正好把"同一份证明的连续三次判断"
        # 悄悄变成"三份不同东西的判断"。
        citations, citations_problem = _citation_material(self.store, sid, no)
        for item in citations:
            # 档位判据走可打桩的那一格（`_citation_admissibility`），材料里存的是它的答案。
            item["admissible"] = bool(self._citation_admissibility(item.get("evidence_kind") or ""))
        out["citations"] = citations
        facts = str(readonly_facts or "") or (
            _read_only_facts(self.store, sid) if self.store is not None else "")
        prompt = VR.cold_start_prompt(statement_full or f"（命题 {sid} 的正文没读到）",
                                      text, readonly_facts=facts, citations=citations,
                                      citations_problem=citations_problem)

        # ---- 业主 2026-10-30 的两次裁定：一次调用里连着判，终局只有两种 ----
        #
        # 循环的每一转都是一次真的模型调用 + 一行台账 + 一次秘书判定，三件事一件都不许省：
        # 省了模型调用就成了"把同一份结论抄三遍"（那不是连续三次判断，是一次判断数三下）；
        # 省了台账行，连续次数就没有来源；省了秘书判定，就等于 V 自己发签（2026-10-29 已收回）。
        #
        # 停的两条（业主第二次裁定的逐字：「连判里面如果判出一回秘书
        # 语义分析认为是『有毛病』的，则直接打回了，连判终止」）：
        # ① 签上：秘书已经决定签发（`issue`）。"判了签发却没落盘"是装配问题，再判几转也变不
        #    出一张签 ⇒ 一并停，并让 `issued` 如实说没落地；
        # ② 打回：秘书判 fault（有毛病），或这一签的结论不是「成立」。
        #    那一转就是终局：缺陷已经点名，这一行的读数就是打回给 F 的那一条
        #    （fault 那一档随台账行带上洗过的转达）。
        #    不再多问一转 —— 多问等于"再给一次机会"，而业主的口径是"直接打回"。
        #
        # 上界动态等于门槛（`review_pass_bound()` 现读）：跑满门槛时 clean 那一档必然攒够
        # 门槛票，于是"要么签、要么打回"必然命中。跑完两头都没有 ⇒ 内部不一致（见下）。
        need = review_pass_bound()
        passes: list[dict[str, Any]] = []
        last: dict[str, Any] = {}
        #: 终局是哪一种："" = 循环跑完还没命中终局（= 内部不一致）/ signed / fault /
        #: verdict（V 自己的结论不是成立）/ gate（结论成立、但这一行自己签不住：
        #: 引用核实挡签或还有未解决的 error）/ unjudged（秘书这一问没查成）/
        #: ledger（台账那一行没落地）。
        stopped = ""
        stop_why = ""
        for pass_no in range(1, need + 1):
            once = self._review_pass(sid=sid, text=text, no=no, prompt=prompt,
                                     citations=citations,
                                     citations_problem=citations_problem,
                                     pass_no=pass_no)
            if not once.get("ok"):
                # 这一转没查成（没接线 / 结论不合法 / 台账写不进去）。已经读到的读数
                # 照改前的顺序摊回返回值：秘书判定与引用核实在改前也是先落再写的，
                # 于是"没查成"那几条路上它们照样读得出来。
                if once.get("judgment"):
                    out["secretary_judge"] = dict(once["judgment"])
                if once.get("gate"):
                    out["citation_gate"] = dict(once["gate"])
                    out["citation_checks"] = [
                        {key: c.get(key) for key in VR.CITATION_CHECK_KEYS}
                        for c in (once.get("checks") or [])]
                if once.get("wash"):
                    out["wash_v_reply"] = dict(once["wash"])
                if str(once.get("emit") or ""):
                    self._emit(str(once["emit"]))
                out["reason"] = str(once.get("reason") or "")
                out["detail"] = str(once.get("detail") or "")
                out["review_passes"] = passes
                return out
            last = once
            passes.append({
                "pass": pass_no,
                "axis": str(once["judgment"].get("axis") or ""),
                "decision": str(once["issuance"].get("decision") or ""),
                # `projected` 是"这一签落下去之后的连续次数"（秘书那一步已经按台账算过，
                # 这一转的票也在里面）⇒ 它就是这一转的 streak。打回那一档由
                # `_terminal_issuance` 按同一份台账现算（没查成那一档不算票、也不清零）。
                "streak": int(once["issuance"].get("projected") or 0),
                "need": int(once["issuance"].get("need") or VR.SIGN_STREAK_NEED),
                "streak_ok": bool(once["issuance"].get("streak_ok")),
                "issue": bool(once["issuance"].get("issue")),
                "issued": bool(once["issuance"].get("issued")),
                "verdict": str(once["row"].get("verdict") or ""),
                "verification_id": str(once["row"].get("verification_id") or ""),
                #: 这一转是不是终局、是哪一种（""=不是终局）。读侧不必再从"下一转还在不在"
                #: 反推"停在哪儿"，也不用把"打回"读成"次数没到"。
                "terminal": "",
            })
            out["review_passes"] = passes
            if once["row"].get("checked") is False:
                # 台账那一行没落地（追加失败 / 被撤回）⇒ 立刻停：再判几转也攒不出一票
                # （连续次数从台账派生）。收尾那一支会报 `ledger_row_lost`，不许报"签住了"。
                stopped = "ledger"
                passes[-1]["terminal"] = stopped
                stop_why = "台账那一行没落地（必须重签）"
                break
            if not VR.row_signable(once["row"]):
                # ---- 结论写「成立」，但这一行自己签不住（引用核实挡签 / 未解决的 error）----
                #
                # 2026-11-01 的两态裁定把这个终局露了出来：改前"引用判不了"被改判成第三态
                # `看不出来`，于是循环按"V 的结论不是成立"那一支停；现在结论仍是 `成立`
                # （它没找到缺陷），挡住这一签的是引用闸，而循环此前不读它 ⇒ 三转跑完既没签、
                # 也没打回，收尾报一条假的 `internal_inconsistency`。这一支补上那个终局：
                # 立刻停，由正常收尾路径如实报"结论成立、但这一签没落地，为什么"。
                stopped = "gate"
                passes[-1]["terminal"] = stopped
                stop_why = ("这一签的结论是「成立」，但它自己签不住"
                            f"（{VR.signing_gate_problem(once['row']) or '引用核实挡签'}"
                            f"；未解决 error {int(once['row'].get('unresolved_errors') or 0)} 条）"
                            "⇒ 不签第 3 位；连判到此为止（这不是有毛病，也不是没查成）")
                break
            if bool(once["issuance"].get("issue")):
                stopped = "signed"
                passes[-1]["terminal"] = stopped
                stop_why = ("签上了" if once["issuance"].get("issued")
                            else "秘书判了签发，但翻位没落成（落地是秘书的事）")
                break
            axis = str(once["judgment"].get("axis") or "")
            if str(once["row"].get("verdict") or "") != "成立":
                # V 自己的结论不是「成立」⇒ 本身就是一条打回，不依赖秘书那一问。
                # 它排在"秘书没查成"之前：V 已经判过的缺陷不许被改记成"没查成"。
                stopped = "verdict"
                passes[-1]["terminal"] = stopped
                stop_why = (f"这一签的结论是 {once['row'].get('verdict')!r}"
                            "（本身就是打回，立刻停）")
                break
            if axis == "fault":
                stopped = "fault"
                passes[-1]["terminal"] = stopped
                stop_why = "秘书判 fault（有毛病）：这一转就是终局，立刻打回 F"
                break
            if not bool(once["judgment"].get("checked")):
                # 秘书这一问没查成（没缝 / 没答上来 / 词表外）：那不是判定，更不是"有毛病"。
                # 立刻停，读数由收尾那一支分两档给（装配缺口 / 这一问失败）。
                stopped = "unjudged"
                passes[-1]["terminal"] = stopped
                stop_why = ("秘书这一转没判成（checked=False）：没查成，不是有毛病，"
                            "也不是没问题")
                break
        # 循环之后：这一趟的读数一律取"最后那一转"（前面的每一转都在 `review_passes` 里）。
        row = dict(last.get("row") or {})
        judgment = dict(last.get("judgment") or {})
        issuance = dict(last.get("issuance") or {})
        gate = dict(last.get("gate") or VR.citation_gate([]))
        out["secretary_judge"] = judgment
        out["sign_issuance"] = issuance
        out["citation_gate"] = gate
        out["citation_checks"] = [{key: c.get(key) for key in VR.CITATION_CHECK_KEYS}
                                  for c in (last.get("checks") or [])]
        if last.get("wash"):
            out["wash_v_reply"] = dict(last["wash"])
        if stopped == "":
            # 循环跑完而既没签也没打回 ⇒ 内部不一致，不是一条终局（业主 2026-10-30 否掉的
            # 就是"次数没到"这类收尾）。`checked=False` 是"没查成"，不是"审过了"。
            out["review_passes"] = passes
            out["reason"] = "internal_inconsistency：连判跑完既没签也没打回"
            out["detail"] = (
                f"门槛 {need} 次、这一趟判了 {len(passes)} 转，却既没有秘书发签、也没有任何"
                "一转被秘书判出毛病 ⇒ 这是一处内部不一致（不是一条合法的终局，"
                "也不是「再判几次就好」）。两种来路：① 门槛被改成 0 或负数（连判一转都跑不了）；"
                "② 秘书在连续次数已经够的那一转既不发签、也没判出问题（秘书那一侧的装配或"
                "判定异常）。处置：把门槛改回正整数，并核对 V 的秘书装配"
                "（`secretary.for_role_wired(\"V\", ...)`）之后重签。")
            self._emit(f"verify_proof({sid})：连判跑完既没签也没打回 —— 内部不一致"
                       f"（门槛 {need}，判了 {len(passes)} 转）")
            return out
        if stopped == "unjudged" and not bool(judgment.get("unwired")):
            # "秘书问不出来"那一档（业主 2026-10-30 第三次裁定第 3 条）：框架失败 ⇒
            # 整笔 `checked=False` + 明确 reason；不许当成 fault 打回，也不许说"次数没到"。
            # 与"没有判断面"（装配缺口）分开：那一档台账照落、顶层 checked 仍为真
            # （V 的审阅确实做完了），这里报的是"这一问没查成"。
            out["review_passes"] = passes
            out["checked"] = False
            out["signed_bit3"] = False
            out["bits"] = {}
            out["reason"] = ("secretary_unjudged：这一转秘书问不出来（没查成，"
                             "不是判定）")
            out["detail"] = (
                "V 的审阅这一转做完了、台账那一行也落了，但秘书的语义判定没查成"
                f"（{str(judgment.get('reason') or '没有给理由')[:300]}）⇒ 这一签不发，"
                "连判到此为止。处置：核对 V 的秘书装配与模型缝（"
                "`secretary.for_role_wired(\"V\", ...)`），判定接上之后重签。"
                "这一档不是「有毛病」——不许按缺陷打回 F，也不是「再判几转就好」。")
            self._emit(f"verify_proof({sid})：秘书这一转没查成（"
                       f"{str(judgment.get('reason') or '没有给理由')[:120]}）—— 没查成")
            return out
        self._emit(f"verify_proof({sid})：这一趟自己连判 {len(passes)} 次"
                   f"（停在：{stop_why}）")
        self._emit(f"verify_proof({sid})：秘书语义判定 "
                   f"{'checked' if judgment.get('checked') else 'checked=False'}"
                   f"（{judgment.get('axis') or '没判'}）"
                   f"；发签 {'发' if issuance.get('issue') else '不发'}"
                   f"（连续 {issuance.get('projected')}/{issuance.get('need')}）"
                   + (f"；翻位 {'成' if issuance.get('issued') else '没成'}"
                      if issuance.get("issue") else ""))
        writeback = dict(issuance.get("writeback") or row.get("statement_writeback") or {})
        if row.get("checked") is False:
            # 台账那一行没落地（被撤回 / 追加失败）：不许报"签住了第 3 位"。
            # 改前这里照样 `checked=True, signed_bit3=True`，而盘上 0 字节（审计第 1 条）。
            out.update({
                "checked": False,
                "review_write": writeback,
                "reason": f"ledger_row_lost：{row.get('reason') or '台账那一行没写成'}",
                "detail": (f"V 的结论是 {row.get('verdict')!r}，但台账那一行"
                           + ("被撤回" if writeback.get("rolled_back") else "没写成")
                           + " ⇒ 这一签没有落地、命题行的第 3 位也没改；"
                             "必须重签（重新走一次 verify.verify_proof），"
                             "不许把它当成「审过了」"),
            })
            self._emit(f"verify_proof({sid})：{out['reason']} —— 台账里没有这一签")
            return out
        payload = (VR.bit3_payload(row, streak=VR.consecutive_holds(
            self.workspace_root, sid, proof_no=no))
            if bool(issuance.get("issued")) else {})
        # 签成没成只看秘书落地那一步（`issued`），不看"台账票数够不够"（业主 2026-10-29）。
        # 票够而秘书没落（装配缺失 / 它判了不发 / 没判成）⇒ 位没有翻，返回值不许说签了；
        # 改前这里按连续读数合成了第 3 位，于是"没人发签"在返回值里长得像"已经签上"。
        bits: dict[str, Any] = {}
        try:
            from .. import evidencebits as EB

            bits = EB.bits_of(proof=text, **payload)
        except Exception as exc:  # noqa: BLE001 —— 合成失败不影响台账那一行（它已经落盘）
            self._emit(f"verify_proof({sid})：五元位合成失败（{type(exc).__name__}: {exc}）")
        self._emit(f"verify_proof({sid})：{row['verification_id']} verdict={row['verdict']} "
                   f"signed_bit3={bool(payload)}")
        if writeback and writeback.get("written"):
            self._emit(f"verify_proof({sid})：{VR.proof_label(sid, no)} 的 reviewed 已写回"
                       f"（grade={writeback.get('grade') or '（没算出等级）'}）")
        elif writeback and not writeback.get("written"):
            # 写位失败不许静默：台账那一行已经在盘上，而"位没翻上去"必须能读出来
            # （读侧按台账现算，所以它不是断链，但它是一处要修的失败）。
            self._emit(f"verify_proof({sid})：{VR.proof_label(sid, no)} 没写成 —— "
                       f"{writeback.get('reason') or ''}")
        out.update({
            "checked": True,
            "verification_id": row["verification_id"],
            "verdict": row["verdict"],
            "defect_step": row["defect_step"],
            "findings": row["findings"],
            "unresolved_errors": row["unresolved_errors"],
            "proof_sha256": row["proof_sha256"],
            "proof_no": row.get("proof_no"),
            "proof_chars": row["proof_chars"],
            "signed_bit3": bool(payload),
            "reviewed_by": dict(payload.get("reviewed_by") or {}),
            "bits": bits,
            "review_write": writeback,
            "ledger": f"verifications/{sid}.jsonl#{row['verification_id']}",
            # 台账那一行是这一档的正本：返回的 citation_checks 从盘上那一行读回来
            # （它已经过 `parse_verdict` 的同一套校验、只剩那四格）。
            "citation_checks": list(row.get("citation_checks") or []),
            "reason": f"{row['verification_id']}：{row['verdict']}"
                      + ("（签第 3 位）" if payload else "（不签第 3 位）")
                      + ("；秘书判定没查成（这一趟没有判断面）⇒ 这一签不发"
                         if stopped == "unjudged" else "")
                      + (f"；引用核实挡下 {len(gate.get('blocking') or [])} 条"
                         if gate.get("blocking") else ""),
            # 引用核实那一句原话（挡签时它点名哪一条、差在哪；只有弱形式时它点名那一条）。
            "detail": str(gate.get("why") or ""),
        })
        return out

    def _review_pass(self, *, sid: str, text: str, no: int, prompt: str,
                     citations: list[dict[str, Any]], citations_problem: str,
                     pass_no: int) -> dict[str, Any]:
        """一份证明的一次独立审阅（业主 2026-10-30 的"连续再判"里的那一转）。

        一转做五件事，一件都不许省：
        ① 真的问一次模型（第 2 转起在提问的末尾追加"第几次"，稳定前缀一个字不动）；
        ② 把回复解析成两态结论（不合法 ⇒ 这一格"没查成"，不落台账行；「看不出来」那一族
         措辞由 `verifications.parse_verdict` 折成「成立」）；
        ③ 引用核实的定稿与签字前置（与改前同一套判据，唯一实现在 `verifications`）；
        ④ 秘书的语义两档判定（B 段）＋ 判了 fault 时那一次洗稿（C 段）；
        ⑤ `record_verification(flip=False)` 落一行台账；clean 且结论是「成立」才问秘书
        发不发签（A 段），其余几档已经是终局 —— 由 `_terminal_issuance` 给一个 fail-closed
        的读数（见那个方法：这一签不许在"打回"的同一条路径上翻上位）。

        为什么这一转必须单独是一个方法：它要在 `verify_proof` 里被转三次，而"每一转都走
        同一套纪律"这件事只能有一个实现 —— 抄三遍必然漂（而漂的那一处正好会是
        "第 2 转忘了落台账"或"第 3 转跳过了秘书"）。

        返回 `{"ok": True, "row": 台账行, "judgment": 秘书判定, "wash": 洗稿读数,
        "issuance": 发签决定, "gate": 引用闸, "checks": 逐条引用结论}`；
        `ok=False` 那一支只带"没查成"的三样东西（`reason` / `detail` / `emit`），
        与改前逐字相同，另外把已经读到的 `judgment` / `gate` / `checks` / `wash` 带回去
        （改前那几条路上它们也是先落进返回值再报错的）。
        """
        asked = prompt if int(pass_no) <= 1 else prompt + REVIEW_PASS_NOTE.format(n=pass_no)
        reply, problem = self._ask(asked)
        if problem:
            return {"ok": False, "reason": problem,
                    "detail": ("这次审校没有拿到合法结论 ⇒ 台账里不留行"
                               "（留一行会把「没查成」冒充成「审过了」）"),
                    "emit": f"verify_proof({sid})：没查成（{problem}）—— 不落台账行"}
        try:
            verdict = VR.parse_verdict(reply)
        except VR.VerificationError as exc:
            return {"ok": False, "reason": "unparsable",
                    "detail": f"模型输出不是合法结论：{exc}",
                    "emit": f"verify_proof({sid})：结论不合法（{exc}）—— 不落台账行"}

        # ---- 引用核实的定稿与签字前置（业主 2026-10-26 两批裁定）----
        #
        # 三条判据在这里合成一个结论：① 每一条被引命题都要有结论（缺的按 unknown 算）；
        # ② 被引命题低于 `proof_review` ⇒ inadmissible（事实，不交给模型裁量）；
        # ③ 有一条挡签的档 ⇒ 结论从「成立」改判（stronger/unrelated/inadmissible →
        #    有毛病；只有 unknown ⇒ 结论不动（它没找到缺陷），由引用闸挡住这一签）。改判的
        #    每一条都落进 findings 并点名，
        #    于是"签不成"这件事在台账里逐字可读，而不是只在返回值里说一句。
        checks = self._citation_checks(list(verdict.get("citation_checks") or []), citations)
        gate = VR.citation_gate(checks, problem=citations_problem)
        verdict = VR.apply_citation_gate(dict(verdict, citation_checks=checks), gate)
        self._emit(f"verify_proof({sid})：引用核实 {len(checks)} 条，"
                   f"挡签 {len(gate.get('blocking') or [])} 条"
                   + (f"，弱形式 {len(gate.get('weaker') or [])} 条"
                      if gate.get("weaker") else "")
                   + ("；依赖台账读不到（这一档没查成）" if gate.get("problem") else ""))

        # ---- 业主 2026-10-29：V 不再自己发签 ----
        #
        # 追加口径逐字：「V 不再自己发签。V 只产出审稿意见；由 V 的秘书判定并落盘
        # （`Secretary.decide_sign_issuance` → 满足"连续 3 次 clean"才调
        # `verifications.sign_statement` 翻 `bits.evidence`）」。
        #
        # 于是这一转的顺序是三步，写盘的位置与改前不同：
        # ① 秘书判这段回复是哪一档（B 段；材料只给回复 + 这一签的 verdict/defect_step）；
        # ② `record_verification(flip=False)` 只落台账（正本先落，签这个事实不依赖任何人
        #    的决定；`statement_writeback.deferred_to == "secretary"`）；
        # ③ 秘书读连续次数 + 判"发不发"，判发就由它自己调 `sign_statement` 翻位。
        # 秘书不在场 / 没缝 / 没判成 ⇒ ②照落、③不翻 ⇒ 第 3 位保持空（fail-closed）。
        judgment = self._judge_v_reply(reply, verdict, no, statement_id=sid)
        # C 段：秘书判"有缺陷要指出"⇒ 立刻洗一遍，把洗过的文本随台账那一行落盘。
        # 为什么在落台账之前洗：台账是追加式文件，行写下去就不能改；洗过的转达文本
        # 必须与那一签一起落（`v_rejections_digest` 从那一格读给 F）。
        # 洗不出来 ⇒ 这一格不写（"没有这一格" = 没洗过，不许写空文本冒充洗过）。
        wash: dict[str, Any] = {}
        if str(judgment.get("axis") or "") == "fault":
            wash = self._wash_v_reply(reply, verdict, no, statement_id=sid)
        try:
            row = VR.record_verification(self.workspace_root, statement_id=sid, proof_text=text,
                                         verdict=verdict, verifier=self.actor,
                                         submission_id=str(self.cfg.get("submission_id") or ""),
                                         store=self.store, proof_no=no,
                                         # `problem` 非空（依赖台账读不出来）要随行落盘：
                                         # 否则读侧只看到空的 `citation_checks`，分不开
                                         # "没查成"与"核过、没有引用"。
                                         citation_gate=gate,
                                         # B 段：两档语义判定随台账那一行落盘。
                                         secretary_judge=judgment,
                                         # C 段：洗过的转达文本（只有真洗出来时才写）。
                                         washed_relay=wash,
                                         # A 段：发签权在秘书手上 ⇒ 这一次不翻位。
                                         flip=False)
        except (VR.VerificationError, OSError) as exc:
            # 台账写不进去（坏行 / 权限 / 磁盘 / 目录）⇒ 这是"没查成"，不是"签住了"。
            # 不接住它会让异常穿透到工具层，而那一层读不到"这一签没落地"这句话。
            self._emit(f"verify_proof({sid})：台账写不进去（{type(exc).__name__}: {exc}）—— 没查成")
            return {"ok": False, "reason": "ledger_unwritable",
                    "detail": (f"台账写不进去（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
                               "（不落台账、不改位、必须重签）"),
                    "emit": "", "judgment": judgment, "wash": wash,
                    "gate": gate, "checks": checks}
        axis = str(judgment.get("axis") or "")
        if (bool(judgment.get("checked")) and axis == "clean"
                and str(verdict.get("verdict") or "") == "成立"):
            # 只有"判过了、没问题、结论成立"这一档才问"这一签发不发"
            # （其余几档都是终局或没查成，见 `_terminal_issuance`）。
            issuance = self._decide_sign_issuance(sid, text, no, verdict, row=row)
        else:
            issuance = self._terminal_issuance(sid, no, text=text, row=row,
                                               judgment=judgment, verdict=verdict)
        return {"ok": True, "row": row, "judgment": judgment, "wash": wash,
                "issuance": issuance, "gate": gate, "checks": checks,
                "verdict": verdict}

    def _terminal_issuance(self, statement_id: str, proof_no: int, *, text: str,
                           row: Mapping[str, Any], judgment: Mapping[str, Any],
                           verdict: Mapping[str, Any]) -> dict[str, Any]:
        """这一转不是"判过了、没问题、成立"⇒ 不发签，读数逐字说清"为什么没签"。

        为什么不问 `decide_sign_issuance`：它读的是"连续次数够不够 + 是否同一份正文"。
        在这一转上那两条都可能已经满足（fault 之前攒的票还在），于是它会在"打回"的
        同一条路径上把第 3 位翻上去 —— 那一签与刚判出来的缺陷会同时成立，而业主的口径是
        这一转直接打回。所以这一格由 V 这一侧直接给一个 fail-closed 的读数：
        `issue=False`、`issued=False`（这一签没有发、也不该发）。

        `checked` 取秘书这一次判定自己的 `checked`：它判过（fault）⇒ True；
        它根本没判成（没有秘书 / 没缝 / 这一问没答上来）⇒ False ——"没查成"不许被读成
        "判过了"，更不许被读成"有毛病"。
        `streak` / `need` / `state` / `same_sha` 从台账现算（同一份读数来源，不另立判据）。
        """
        try:
            standing = VR.review_standing(self.workspace_root, statement_id=statement_id,
                                          proof_text=text, proof_no=proof_no)
        except Exception as exc:  # noqa: BLE001 —— 读不成是读数缺失，不是"发了签"
            self._emit(f"verify_proof({statement_id})：终局那一转的台账读数没读成"
                       f"（{type(exc).__name__}: {exc}）")
            standing = {}
        need = int(VR.SIGN_STREAK_NEED)
        streak = int(standing.get("streak") or 0)
        # 词表只有那一个来源（`secretary.SIGN_WITHHOLD`）：这里不抄第二份中文取值。
        from .. import secretary as _SEC

        axis = str(judgment.get("axis") or "")
        # 这一转凭什么不发签：verdict（结论不是成立）/ fault（有毛病）/ unjudged（没查成）。
        # 次序与 `verify_proof` 循环里那三个分支逐字同一套（一处改两处漂是不允许的）：
        # 「V 自己的结论不是成立」本身就是一条打回，不依赖秘书那一问 —— 不许因为秘书
        # 没查成，把一条 V 自己判过的缺陷改记成"没查成"。
        if str(verdict.get("verdict") or "") != "成立":
            kind = "verdict"
        elif axis == "fault":
            kind = "fault"
        else:
            kind = "unjudged"
        return {
            "checked": bool(judgment.get("checked")),
            "issue": False, "issued": False, "landed": False,
            "decision": _SEC.SIGN_WITHHOLD,
            "streak": streak, "need": need,
            "streak_ok": bool(streak >= need), "projected": streak,
            "same_sha": bool(str(standing.get("sha") or "")
                             and str(standing.get("sha")) == VR.proof_sha(text)),
            "state": str(standing.get("state") or ""),
            "reason": self._terminal_reason(kind=kind, judgment=judgment, verdict=verdict),
            "basis": [f"秘书判定 checked={bool(judgment.get('checked'))} "
                      f"axis={axis or '（没有轴）'}",
                      f"continuous={streak}/{need}",
                      f"row={row.get('verification_id') or '（没有编号）'}"],
            "reading": dict(standing), "cost": {}, "material": {},
            "writeback": {}, "statement_id": str(statement_id),
            "proof_no": int(proof_no),
        }

    def _terminal_reason(self, *, kind: str, judgment: Mapping[str, Any],
                         verdict: Mapping[str, Any]) -> str:
        """不发签那一转的 `sign_issuance.reason`：说清"为什么不签"，不说"次数没到"。

        三档分开写（`verdict` / `fault` / `unjudged` —— 读的人据此知道下一步该干什么）：fault = 有毛病（按缺陷改）、
        verdict = V 自己的结论不是成立（本身就是打回）、unjudged = 这一问没查成
        （框架失败：不是判定，也不许当成"有毛病"打回）。
        `kind` 由调用方按与循环同一套判据算好（`fault` / `verdict` / `unjudged`）。
        """
        if kind == "fault":
            return ("这一转秘书语义判定说「有毛病」（fault）⇒ 不发签；这一转就是终局："
                    "已按 fault 打回 F（错在第几步见洗过的转达与 findings）")
        if kind == "verdict":
            return (f"这一签的结论是 {str(verdict.get('verdict') or '（不是成立）')!r} ⇒ "
                    "不发签；这一转就是终局：这一份要打回 F 改正之后再送 V 重审")
        return ("这一转秘书没判成（checked=False）⇒ 不发签；这是框架失败（没查成），"
                "既不是「有毛病」，也不是「没问题」："
                f"{str(judgment.get('reason') or '没有给理由')[:200]}")

    def _review_without_statement(self, *, text: str, no: int) -> dict[str, Any] | None:
        """命题还没在册时的一次穷举型证据会审（D-34）；不归这一档 ⇒ `None`。

        为什么只接穷举型证据：那一档的会审是机械的（七项可核的事实：
        程序在不在、报告落没落、数字对不对得上……），不需要命题正文就能判 ——
        而普通逐行走查要"按写成后的样子整体重读"，缺了命题那一页就无从审
        （那一档仍按原样报 `statement_missing`）。

        返回 `{"reviewed": {...}, "row": {...}}`；台账写不进去时返回
        `{"reason": "ledger_unwritable", "detail": ...}`（这一格"没查成"，不是"签过了"）。
        """
        if not str(text or "").strip():
            return None
        from .. import exhaustionreport as _ER

        exp_rows: list = []
        try:
            if self.store is not None:
                exp_rows = list(self.store.rows("experiments"))
        except (StoreError, AttributeError, TypeError):
            exp_rows = []
        if not _ER.is_exhaustion_column({"proof_text": text}, exp_rows):
            return None
        reviewed = _ER.review(workspace_root=self.workspace_root,
                              statement={"proof_text": text}, experiments=exp_rows)
        try:
            row = VR.record_pending_sign(
                self.workspace_root, proof_text=text,
                verdict=_ER.verdict_of(reviewed), verifier=self.actor,
                object_sha256=str(reviewed.get("report_sha256") or ""),
                object_path=str(reviewed.get("report_path") or ""))
        except (VR.VerificationError, OSError) as exc:
            return {"reason": "ledger_unwritable",
                    "detail": (f"pending 台账写不进去（{type(exc).__name__}: {exc}）⇒ "
                               "这一格没查成（那一签没有落点，必须重签）")}
        self._emit(f"verify_proof(未在册)：穷举型证据会审 ⇒ {row.get('verdict')}"
                   f"（落 {VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/，按对象 sha 可认领）")
        return {"reviewed": reviewed, "row": row}

    def _finish_pending(self, out: dict[str, Any], *, statement_id: str, no: int,
                        got: Mapping[str, Any]) -> dict[str, Any]:
        """`_review_without_statement` 的收尾：把那一签的读数摊进返回值（键集不增不减）。

        `checked=True` 是诚实的：这一次审了、结论也在盘上（`verifications/pending/`）。
        `signed_bit3=False` 也是诚实的：第 3 位住在 `statements` 那一行上，而那一行还不存在 ——
        "盖章"与"入册"是两件事，B 登记之后按同一个 sha 认领，那一签才算落到位上。
        """
        if str(got.get("reason") or ""):
            out["reason"] = str(got.get("reason"))
            out["detail"] = str(got.get("detail") or "")
            return out
        row = dict(got.get("row") or {})
        reviewed = dict(got.get("reviewed") or {})
        out.update({
            "checked": True,
            "kind": "numeric_evidence_unregistered",
            "verification_id": str(row.get("verification_id") or ""),
            "verdict": str(row.get("verdict") or ""),
            "defect_step": row.get("defect_step"),
            "findings": list(row.get("findings") or []),
            "unresolved_errors": int(row.get("unresolved_errors") or 0),
            "proof_sha256": str(row.get("proof_sha256") or ""),
            "proof_no": no,
            "proof_chars": int(row.get("proof_chars") or 0),
            "signed_bit3": False,
            "exhaustion_review": reviewed,
            "signer": str(reviewed.get("signed_by") or ""),
            "proof_authors": list(reviewed.get("proof_authors") or []),
            "report_path": str(reviewed.get("report_path") or ""),
            "checks": list(reviewed.get("checks") or []),
            "missing": list(reviewed.get("missing") or []),
            "ledger": (f"{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/"
                       f"{str(row.get('object_sha256') or row.get('proof_sha256') or '')[:64]}"
                       f".jsonl#{row.get('verification_id') or '?'}"),
            "reason": (f"{row.get('verification_id')}：{row.get('verdict')}"
                       "（命题还没在册 ⇒ 这一签落在 pending，按对象 sha 可认领）"),
            "detail": (f"命题 {statement_id} 不在 statements 里：这一签没有地方翻第 3 位，"
                       "但它已经审过并按对象内容的 sha 落盘（"
                       f"`{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/`）—— "
                       "B 把这一条登记之后按同一个 sha 认领，结论不会丢；"
                       "不许把它当成「没审」"),
        })
        return out

    def _finish_numeric(self, out: dict[str, Any], *, statement_id: str, no: int,
                        row: Mapping[str, Any], reviewed: Mapping[str, Any]) -> dict[str, Any]:
        """穷举型证据会审的收尾：台账那一行落地没有、五元位、返回值。

        这一段与 `verify_proof` 的普通收尾是同一套纪律（只认 `row` 上的 `checked`）：
        台账没落地就不许报"签住了第 3 位"；`成立` 才签；`有毛病` / 历史行里的 `看不出来` 照样
        留一行（那是"看过、结论是没过/判不了"的证据）。
        """
        sid = statement_id
        # 翻位那一步在秘书那一侧（业主 2026-10-29 追加口径）：`row.statement_writeback`
        # 是 record_verification 的"deferred"读数，真正的写回在 `out["sign_issuance"]` 里。
        writeback = dict((out.get("sign_issuance") or {}).get("writeback")
                         or row.get("statement_writeback") or {})
        if row.get("checked") is False:
            out.update({
                "checked": False,
                "review_write": writeback,
                "reason": f"ledger_row_lost：{row.get('reason') or '台账那一行没写成'}",
                "detail": (f"V 的会审结论是 {row.get('verdict')!r}，但台账那一行没落地 ⇒ "
                           "这一签没有落地、命题行的第 3 位也没改；必须重签"),
            })
            self._emit(f"verify_proof({sid})：{out['reason']} —— 台账里没有这一签")
            return out
        payload = (VR.bit3_payload(row, streak=VR.consecutive_holds(
            self.workspace_root, sid, proof_no=no))
            if bool((out.get("sign_issuance") or {}).get("issued")) else {})
        # 与普通逐行走查那一支同一条纪律：签成没成只看秘书落地那一步（`issued`）。
        # 这一路改前也是"按连续读数合成第 3 位"，于是装配缺失时返回值说签了、盘上没翻。
        bits: dict[str, Any] = {}
        try:
            from .. import evidencebits as EB

            bits = EB.bits_of(proof=str(row.get("proof_text") or ""), **payload)
        except Exception as exc:  # noqa: BLE001 —— 合成失败不影响台账那一行（它已经落盘）
            self._emit(f"verify_proof({sid})：五元位合成失败（{type(exc).__name__}: {exc}）")
        self._emit(f"verify_proof({sid})：{row['verification_id']} verdict={row['verdict']} "
                   f"signed_bit3={bool(payload)}（穷举型证据会审）")
        if writeback and writeback.get("written"):
            self._emit(f"verify_proof({sid})：{VR.proof_label(sid, no)} 的 reviewed 已写回")
        out.update({
            "checked": True,
            "verification_id": row["verification_id"],
            "verdict": row["verdict"],
            "defect_step": row["defect_step"],
            "findings": row["findings"],
            "unresolved_errors": row["unresolved_errors"],
            "proof_sha256": row["proof_sha256"],
            "proof_no": row.get("proof_no"),
            "proof_chars": row["proof_chars"],
            "signed_bit3": bool(payload),
            "reviewed_by": dict(payload.get("reviewed_by") or {}),
            "bits": bits,
            "review_write": writeback,
            "ledger": f"verifications/{sid}.jsonl#{row['verification_id']}",
            "reason": f"{row['verification_id']}：{row['verdict']}"
                      + ("（签第 3 位）" if payload else "（不签第 3 位）"),
            "checks": list(reviewed.get("checks") or []),
            "missing": list(reviewed.get("missing") or []),
        })
        return out

    def list_verifications(self, statement_id: str = "", limit: Any = None, **kw: Any) -> dict[str, Any]:
        """列验证台账（可按命题过滤；`limit=None` = 全量，不是"零条"）。"""
        del kw
        lim = None if limit is None else max(0, int(limit))
        rows, problems = VR.list_verifications(self.workspace_root,
                                               statement_id=str(statement_id or "").strip(),
                                               limit=lim)
        return {
            "checked": True,
            "total": len(rows),
            "items": rows,
            "problems": list(problems),
            "truncated": bool(lim is not None and len(rows) > lim),
            "reason": f"共 {len(rows)} 行验证台账"
                      + (f"，坏行 {len(problems)} 条（照实列出，不静默跳过）" if problems else ""),
        }

    def read_proof(self, statement_id: str, **kw: Any) -> dict[str, Any]:
        """按命题号读回被审的那份证明全文 + 它的 sha256 + 最近一次结论。

        与 `verify_proof` 同一纪律：三条返回路径的键集合完全相同
        （"没读到"由 `source="none"` 与 `reason` 说，不靠少给键来表达）。
        """
        del kw
        sid = str(statement_id or "").strip()
        out: dict[str, Any] = {
            "checked": False, "statement_id": sid, "proof_text": "", "source": "none",
            "sha256": "", "proof_chars": 0, "verifications": 0,
            "last_verdict": None, "last_verification_id": None,
            "problems": [], "reason": "",
        }
        if not S.is_valid_id(sid):
            out["reason"] = (f"命题号必须是 {S.ID_DIGITS} 位十进制（旧数据里的 4 位号仍可读），"
                             f"收到 {statement_id!r}")
            return out
        text, source = "", "none"
        if self.store is not None:
            try:
                hit = next((r for r in self.store.rows("statements")
                            if str(r.get("stmt_id") or "") == sid), None)
            except (StoreError, AttributeError, TypeError):
                hit = None
            if hit is not None and str(hit.get("proof_text") or "").strip():
                text, source = str(hit.get("proof_text")), "statements.proof_text"
        rows, problems = VR.list_verifications(self.workspace_root, statement_id=sid, limit=None)
        last = rows[-1] if rows else None
        out.update({
            "checked": True,
            "proof_text": text,
            "source": source,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
            "proof_chars": len(text),
            "verifications": len(rows),
            "last_verdict": (last or {}).get("verdict"),
            "last_verification_id": (last or {}).get("verification_id"),
            "problems": list(problems),
            "reason": ("读到了证明全文" if text else
                       "台账里没有这个命题的证明全文（**没读到 ≠ 没有毛病**）"),
        })
        return out


class _ScriptedSeam:
    """自检用的替身缝：按调用次数返回事先写好的文本（只服务自检，不进产品路径）。"""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str, **_kw: Any) -> Any:
        """返回一个只有 `text` / `problem` 两个字段的替身结局。"""
        from types import SimpleNamespace

        self.prompts.append(prompt)
        text = self._replies.pop(0) if self._replies else ""
        return SimpleNamespace(text=text, problem="" if text else "judge_not_wired")


class _NoSecretary:
    """自检用的"没有秘书"替身：三件都如实报 `checked=False`（业主 2026-10-29）。

    为什么自检必须给它：`AgentV._secretary()` 会真的去装配一名秘书（工具路径那条缺口），
    而自检不该联网、也不该花钱。给了这个替身，"这一趟没有秘书"就是自检里的第一条读数
    —— 它同时是发签那条路径的反面（`signed_bit3` 必须为假）。
    """

    seam = ""
    model_source = "自检：这一趟没有秘书"

    def judge_v_reply(self, **_kw: Any) -> dict[str, Any]:
        """判定没查成（不是"没问题"）：没有轴（空串），不清零、也不计入。"""
        return {"checked": False, "axis": "", "unwired": True, "decision": "",
                "reason": "自检：没有秘书 ⇒ 判定没查成"}

    def decide_sign_issuance(self, **_kw: Any) -> dict[str, Any]:
        """没人发签 ⇒ 不签发。"""
        return {"checked": False, "issue": False, "issued": False, "streak": 0,
                "projected": 0, "need": VR.SIGN_STREAK_NEED, "streak_ok": False,
                "decision": "", "writeback": {}, "landed": False,
                "reason": "自检：没有秘书 ⇒ 没有人发这一签"}

    def wash_v_reply(self, **_kw: Any) -> dict[str, Any]:
        """洗不出来 ⇒ 不输出原文（自检不测洗稿，只核两态形状）。"""
        return {"checked": False, "washed": False, "text": "", "findings": [],
                "dropped": [], "refused": "secretary_unavailable",
                "reason": "自检：没有秘书"}


def selftest() -> int:
    """最小自检：冷启动的接口形态、两态、签位条件、追加式编号、没查成不落行。"""
    import tempfile

    checks: list[tuple[str, bool]] = []
    root = Path(tempfile.mkdtemp(prefix="agent_v_selftest_"))
    agent = AgentV(None, workspace_root=root, secretary=_NoSecretary(), llm=_ScriptedSeam([
        '{"verdict": "成立", "findings": []}',
        '{"verdict": "有毛病", "defect_step": 2, "findings": '
        '[{"level": "error", "step": 2, "kind": "无依据", "detail": "第 2 步没有依据"}]}',
        "我不确定",
    ]))
    checks.append(("构造成功", agent.actor == DEFAULT_VERIFIER))

    clean = agent.verify_proof("0007", proof_text="1. 由定义直接得到。")
    checks.append(("干净证明签成立", clean["checked"] and clean["verdict"] == "成立"))
    # 编号宽度「不许写死」：2026-10-14 业主裁定「所有四位编号改成六位」
    # （`schema.ID_DIGITS = 6`），发号点是 `verifications.next_verification_id`
    # 的 `f"v-{S.format_id(...)}"`；读侧仍认旧四位号（`schema.LEGACY_ID_PATTERN`）。
    # 旧断言把 `"v-0001"` 写死在两处 ⇒ 宽度一改它就红，而"红了"这件事没有任何
    # 东西看得见（自检只在手工敲命令时跑）。这是「断言过期」，不是行为退化：
    # 台账发的号是正确的六位（见下一条与 `tests/test_id_width.py`）。
    checks.append((f"编号从 v-{S.format_id(1)} 起（六位；旧四位号读侧兼容）",
                   clean["verification_id"] == f"v-{S.format_id(1)}"))
    # 业主 2026-10-29：V 只产意见，签由秘书发；而且连续 3 次成立才签。
    # 自检这一趟没有秘书 ⇒ 第 1 次成立既没有票数也没有人发签 ⇒ 第 3 位必须是空的。
    checks.append(("成立但第 1 次不签第 3 位（没有秘书、也没到第 3 票）",
                   clean["signed_bit3"] is False
                   and clean["sign_issuance"]["checked"] is False
                   and clean["sign_issuance"]["issue"] is False))
    # 第 3 位（审过）的 owner 是 V —— 这一格只能核静态那一半：
    # `evidencebits.BIT_OWNERS["reviewed"] == "V"`（位表里的 owner）。
    # "签名者是 V、凭据是本次这行"那一半要真的签成才看得到，自检没有秘书 ⇒ 不在这里核
    # （那一条在 `tests/test_v_sign_gate_streak.py` 的 a6/a8 里走真路径）。
    from .. import evidencebits as _EB

    checks.append(("五元位第 3 位 owner 是 V（位表那一格）",
                   _EB.BIT_OWNERS.get("reviewed") == "V"
                   and clean["reviewed_by"] == {}))

    bad = agent.verify_proof("0007", proof_text="1. 由定义直接得到。2. 易证。")
    checks.append(("有毛病指到那一步", bad["verdict"] == "有毛病" and bad["defect_step"] == 2))
    checks.append(("有毛病不签第 3 位", bad["signed_bit3"] is False
                   and bad["bits"].get("reviewed") is False))

    unparsable = agent.verify_proof("0007", proof_text="1. 随便写。")
    checks.append(("没查成不落行", unparsable["checked"] is False
                   and unparsable["reason"] == "unparsable"))

    rows = agent.list_verifications()
    checks.append(("追加式：两行（第三份没落）",
                   rows["checked"] and rows["total"] == 2))
    checks.append(("limit=None 是全量而不是零条", agent.list_verifications(limit=None)["total"] == 2))

    # I12 的接口形态：拼提示词的那一步只收字符串。
    import inspect as _inspect

    params = set(_inspect.signature(VR.cold_start_prompt).parameters)
    checks.append(("冷启动提示词没有句柄参数",
                   not (params & {"store", "conductor", "registry", "session_root"})))
    # 正控：提示词里真的有对象与硬禁令（否则上面那条"没有句柄"只是空集通过）。
    seam = _ScriptedSeam(['{"verdict": "看不出来", "findings": []}'])
    probe = AgentV(None, workspace_root=root, secretary=_NoSecretary(), llm=seam)
    probe.verify_proof("0008", proof_text="1. 显然成立。", readonly_facts="- 只读读数：0 行")
    sent = seam.prompts[0] if seam.prompts else ""
    checks.append(("提示词里带证明全文与硬禁令", "1. 显然成立。" in sent and "易证" in sent))
    checks.append(("提示词里带只读读数", "只读读数：0 行" in sent))
    # 业主 2026-11-01：回「看不出来」这一族 ⇒ 折成 `成立` 落行（它不是"没查成"），
    # 而"折出来的成立"照样不签第 3 位（没有秘书、也没有连续次数）。
    _probe_rows = probe.list_verifications("0008")["items"]
    checks.append(("回「看不出来」⇒ 折成成立并落行（why 说清为什么这么收）",
                   probe.list_verifications("0008")["total"] == 1
                   and bool(_probe_rows) and _probe_rows[0]["verdict"] == "成立"
                   and "没有找到缺陷" in str(_probe_rows[0].get("why") or "")
                   and _probe_rows[0].get("verdict_raw") == "看不出来"))
    checks.append(("折出来的成立同样不签第 3 位",
                   bool(_probe_rows) and VR.bit3_payload(_probe_rows[0]) == {}))

    noproof = AgentV(None, workspace_root=root, secretary=_NoSecretary(), llm=_ScriptedSeam([]))
    got = noproof.verify_proof("0007", proof_text="")
    checks.append(("没有证明全文就不问模型", got["checked"] is False
                   and got["reason"] == "no_proof_text"))
    bad_id = noproof.verify_proof("7", proof_text="x")
    # 标签写错过一次（"命题号必须 4 位"而 `schema.ID_DIGITS == 6`）：标签也是判据的
    # 一部分 —— 读者照着它去改数据，会得到"越改越不对"。所以除了 `reason` 码，
    # 这里还核一句「细节里报出的宽度」与 `schema.ID_DIGITS` 逐字一致。
    checks.append((f"命题号必须 {S.ID_DIGITS} 位（旧数据里的 4 位号仍可读）",
                   bad_id["reason"] == "bad_statement_id"
                   and f"{S.ID_DIGITS} 位" in bad_id["detail"]
                   and "4 位号仍可读" in bad_id["detail"]))
    # 反真空：上面那条只证明"坏号被拒"。若发号/收号两侧一起把六位号也拒了，
    # 它照样绿 ⇒ 这里正控地把一个「六位」命题号喂进去，必须被当成合法号。
    six_ok = noproof.verify_proof(S.format_id(7), proof_text="")
    checks.append((f"六位命题号被接受（{S.format_id(7)}；写侧的新形态）",
                   six_ok["reason"] == "no_proof_text"))

    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    passed = sum(1 for _, g in checks if g)
    # 汇总行与退出码同源（与 `agent_e` 的 F-4 同一纪律）：`[FAIL]` 是逐条读数，
    # 汇总行是可机械读出的那一个数；退出码只跟它走。
    print(f"  SELF-CHECK {'DONE' if passed == len(checks) else 'FAILED'}（agent_v）："
          f"{passed} 项通过 / {len(checks) - passed} 项失败")
    return 0 if passed == len(checks) else 1
