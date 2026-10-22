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
## 2026-10-22 补：签字要能到命题那一行上
`verify_proof` 签完之后调 `verifications.record_verification(..., store=self.store)`：它先把
台账那一行落盘，再在同一个 `statements` 事务里把被签的那一份证明（`proof_no`）的
`reviewed` 翻上去（凭据换成这一签的 `verification_id` / `proof_sha256` / `proof_no`）。
为什么必须由签名这条路径自己写：此前第 3 位的唯一写者是 B 的 `register_statement`，而它按
`evidencebits.BIT_OWNERS` 不替 V 签字 ⇒ "V 签了、台账上写着成立"与"命题那一行的 reviewed 位"
之间没有连接，收工门 R10 恒 0。写回的结果在返回值 `review_write` 里（写没写成、为什么、
回滚了没有），失败不静默吞掉。
## 三态纪律在这里的落法（这一层最容易出错的地方）
`成立` / `有毛病` / `看不出来` 是对证明的三个结论；"检查器自己没跑成"（没接线 / 输出不是合法 JSON / 字段缺 / 取值不在词表里）不是这三个之一。
`verify_proof` 因此有两种失败形态，各自的读数分开：
- `checked=False, reason="judge_not_wired"`：没有模型缝，这次根本没看；- 
`checked=False, reason="unparsable"`：看了、但拿回来的东西不是合法结论 ⇒ 不落台账行。
两者都不落台账（`verifications.record_verification` 在没有合法结论时抛`VerificationError`，绝不写一行"看不出来"来冒
充"审过了"）。
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


class AgentV:
    """验证者。三个 handler 与 `specs/v.py` 的 `handler_name` 逐字同名。

    `llm` 是一个"能回答一段提示词的模型缝"：给 `LlmSeam`（有 `.ask`）、
    给一个 client（有 `.complete`）、或给一个可调用对象都行。不给就是没接线 ——
    `verify_proof` 会如实报 `judge_not_wired`，绝不用确定性文本假装审过
    （审校是一件只有模型能做的事，没有它就没有结论）。
    """

    def __init__(self, store: Any, *, workspace_root: str | Path | None = None,
                 llm: Any = None, config: Mapping[str, Any] | None = None,
                 log: Callable[[str], None] | None = None) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        root = workspace_root or getattr(store, "root", None) or "."
        self.workspace_root = Path(root).resolve()
        self.llm = llm
        self.actor = str(self.cfg.get("actor") or DEFAULT_VERIFIER)
        self.log = log
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
                call = seam.ask(prompt, task_id="")
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
            "ledger": "",
            "reason": "",
            "detail": "",
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
                out["kind"] = "statement_missing"
                out["reason"] = "statement_missing"
                out["detail"] = (f"命题 {sid} 不在 statements 里 ⇒ **没审**"
                                 "（不是「审了、有毛病」）；台账里**不留行** —— "
                                 "留一行会把「没查成」冒充成「审过了」。"
                                 "先把这条命题登记了（B 的 register_statement）再来审。")
                self._emit(f"verify_proof({sid})：命题不在册 ⇒ 没审，不落台账行")
                return out
            statement_full = _SB.body_of(hit)
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

        facts = str(readonly_facts or "") or (
            _read_only_facts(self.store, sid) if self.store is not None else "")
        prompt = VR.cold_start_prompt(statement_full or f"（命题 {sid} 的正文没读到）",
                                      text, readonly_facts=facts)
        reply, problem = self._ask(prompt)
        if problem:
            self._emit(f"verify_proof({sid})：没查成（{problem}）—— 不落台账行")
            out["reason"] = problem
            out["detail"] = ("这次审校没有拿到合法结论 ⇒ 台账里**不留行**"
                             "（留一行'看不出来'会把'没查成'冒充成'审过了'）")
            return out
        try:
            verdict = VR.parse_verdict(reply)
        except VR.VerificationError as exc:
            self._emit(f"verify_proof({sid})：结论不合法（{exc}）—— 不落台账行")
            out["reason"] = "unparsable"
            out["detail"] = f"模型输出不是合法结论：{exc}"
            return out

        try:
            row = VR.record_verification(self.workspace_root, statement_id=sid, proof_text=text,
                                         verdict=verdict, verifier=self.actor,
                                         submission_id=str(self.cfg.get("submission_id") or ""),
                                         store=self.store, proof_no=no)
        except (VR.VerificationError, OSError) as exc:
            # 台账写不进去（坏行 / 权限 / 磁盘 / 目录）⇒ 这是"没查成"，不是"签住了"。
            # 不接住它会让异常穿透到工具层，而那一层读不到"这一签没落地"这句话。
            self._emit(f"verify_proof({sid})：台账写不进去（{type(exc).__name__}: {exc}）—— 没查成")
            out["reason"] = "ledger_unwritable"
            out["detail"] = (f"台账写不进去（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
                             "（不落台账、不改位、必须重签）")
            return out
        writeback = dict(row.get("statement_writeback") or {})
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
        payload = VR.bit3_payload(row)
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
            "reason": f"{row['verification_id']}：{row['verdict']}"
                      + ("（签第 3 位）" if payload else "（不签第 3 位）"),
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


def selftest() -> int:
    """最小自检：冷启动的接口形态、三态、签位条件、追加式编号、没查成不落行。"""
    import tempfile

    checks: list[tuple[str, bool]] = []
    root = Path(tempfile.mkdtemp(prefix="agent_v_selftest_"))
    agent = AgentV(None, workspace_root=root, llm=_ScriptedSeam([
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
    checks.append(("成立才签第 3 位", clean["signed_bit3"] is True))
    # 第 3 位（审过）的 owner 是 V —— 这句话有两半，都要核：
    #   ① 静态那一半：`evidencebits.BIT_OWNERS["reviewed"] == "V"`（位表里的 owner）；
    #   ② 实际那一半：这一行签名的是 V（`reviewed_by.verifier`）且凭据就是
    #      本次发的那个号（`reviewed_by.verification_id`，不再写死四位）。
    from .. import evidencebits as _EB

    checks.append(("五元位第 3 位 owner 是 V（位表 owner=V，且签名者与凭据都是本次这行）",
                   _EB.BIT_OWNERS.get("reviewed") == "V"
                   and bool(clean["bits"].get("reviewed"))
                   and clean["reviewed_by"].get("verifier") == DEFAULT_VERIFIER
                   and clean["reviewed_by"].get("verification_id") == clean["verification_id"]))

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
    probe = AgentV(None, workspace_root=root, llm=seam)
    probe.verify_proof("0008", proof_text="1. 显然成立。", readonly_facts="- 只读读数：0 行")
    sent = seam.prompts[0] if seam.prompts else ""
    checks.append(("提示词里带证明全文与硬禁令", "1. 显然成立。" in sent and "易证" in sent))
    checks.append(("提示词里带只读读数", "只读读数：0 行" in sent))
    # `看不出来` 是对证明的结论（落行），与"没查成"（不落行）必须分开。
    checks.append(("看不出来落行但不签",
                   probe.list_verifications("0008")["total"] == 1
                   and VR.bit3_payload(probe.list_verifications("0008")["items"][0]) == {}))

    noproof = AgentV(None, workspace_root=root, llm=_ScriptedSeam([]))
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
