# -*- coding: utf-8 -*-
"""角色 L 的动作 `record`：把一次形式化检查登记成一行 `experiments`（`method="formal"`）。

## 这一格补的是什么缝

业主 2026-10-22 的第二句施工单（逐字）：

「L 的形式化产出今天进不了证据链：它写了 `.lean`、跑了检查器、也说对了三态，
可是台账里一行都没有 —— 于是 `evidence_kind="proof"` 这一档在本框架里永远
只能由 E 产生，而 E 的形式化面是从前那一条路。」

所以这一格只做一件事：把"这次真的跑过的形式化检查"写成 `experiments` 表的一行。

## 它与 `formalize` 的分工（为什么两格而不是一格）

`formalize` 的产物是盘上的文件（`code/formal/<名>.lean` + sha256 + 检查器原话）；
`record` 的产物是台账里的一行。分成两个动作的理由是它们失败得不一样：

- `formalize` 可以写盘成功而检查器不在（结论 unknown）—— 那时文件是真的，行不该有；
- `record` 会自己现跑一次检查器（见下），于是它可以独立于 `formalize` 被调用，
  也可以接在 `formalize` 之后复核同一份文件。

把两者合成一格会让"写没写盘"与"登记没登记"这两个读数互相遮蔽，而它们正是业主
点名要看的两件事。

## 为什么它自己现跑一次，而不是信调用方口述的读数

参数里有 `status` / `verified` / `checker` / `verifier_output` 四格 —— 它们是
调用方看到的读数，本动作不信它们：

1. 自己再跑一次检查器（走 `check_formal`，即"自检闸 + 桥接层"这条唯一实现）；
2. 调用方那四格只用于对账：与现跑值不一致 ⇒ 受控拒绝 `reading_mismatch`，
   一个字节都不写。

`checker` 那一格的口径（`draft/146` D27，2026-10-23）：记下来 + 比版本号。
此前它收下来既不比也不记（这一格是死的，而模块说"四格都用于对账" —— 声明与实现
分家）。现在它进 `observations.checker_claimed`，并与现跑的真名 + 版本并排；
写了版本号而对不上 ⇒ 拒收（那是"另一台机器"的读数），只写泛称（`lean`）不拒。
为什么用"记进 observations + 对账"而不是"从形参表里删掉"：那一格是业主施工单
逐字要求的调用契约（`status/verified/checker/output_sha256`），删掉等于把契约改窄；
而留下来不记账，就是这一格今天的形态 —— 一个收下来就扔的参数最容易骗过评审。

为什么不是"直接信"：`experiments.evidence_kind="proof"` 是整条证据链里最强的一档，
它的全部价值来自"那句话是检查器说的，不是某个模型/某段脚本说的"。允许调用方把
`verified=True` 与一段现编的 `verifier_output` 交进来，这一档就成了可随手搬运的标签
（`schema.Experiment` 的硬约束 2 / 2b 拦的是"没有输出"与"输出绑错命题"，拦不出
"这段输出到底跑没跑过"）。对账这一步是这一格唯一能加在 schema 上面的东西。

为什么不干脆不要那四格：业主的施工单逐字要求这一行动带 `status/verified/checker/
output_sha256` —— 那四格是读数，必须出现在调用契约里；本动作的做法是
"收下来、对账、写进去的是现跑的那一份"。给的与跑的一致时，两者逐字相同。

## 它绝不碰 `statements`（"形式化 ≠ 审过"）

`record` 的写集只有 `experiments`（`specs/l.py::SPEC.write_set`），结构化地
改不了任何命题行。所以"一次机器核过的形式化"不会让某条命题升档：

- `statements.evidence_kind="proof_review"` 仍然只能由"V 那一签"支撑
  （`verify.py` 的 `proof_review_without_verification` 是 error 级的判据本体）；
- 本动作的返回值里带 `statement_evidence_kind_before` / `statement_evidence_kind_after`
  两格 —— 它们是同一行写前写后的读数，逐字相等是这个动作的不变量，
  而它是机器可判的（判据：`tests/test_l_collab_and_secretary.py`）。

## 三态与落库口径（与 E 的 `_run_formal` 逐条同源）

`experiments` 那一行的 `result` / `evidence_kind` / `negation_kind` / `exit_code`
按检查器的三态映射（同一套映射，不是第二份口径）：

| 检查器 | `evidence_kind` | `result` | `negation_kind` |
|---|---|---|---|
| `verified` | `proof` | `supports` | `not_proved` |
| 查了没通过（`compile_error` 等） | `heuristic` | `inconclusive` | `not_proved` |
| 没查成（`timeout` / 无后端 / 自检不过） | `heuristic` | `inconclusive` | `not_searched_here` / `no_local_evidence` |

映射本体在 `agent_e._support` 与 `agent_e/core.py::_record_formal` 里，本模块
不抄第二份：它直接调 `build_experiment`（同一个装配函数），只把"这一行属于
哪条命题、哪一版源码"这几格换成 L 自己的读数。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..agent_e._support import (
    _NO_EVIDENCE_KIND,
    _declared_name_note,
    _digest,
    build_experiment,
)
from .. import statementbody as SB
from .. import verifications as _VR   # 正文 sha 与证明清单的口径各只有一处
from ._support import (
    RECORD_REASONS,
    STATEMENT_CLAIM_KEY_PREFIX,
    ExperimentError,
    one_line,
    sha256_of_bytes,
)
from .formalize import PATH_SOURCES, _checker_name, _path_choice, declaration_name_in

#: 本动作的返回值键集合（每一条分支上都成立：键集合随分支变，判据就会在缺的那条上失效）。
_RECORD_KEYS: tuple[str, ...] = (
    "recorded", "experiment_id", "statement_id", "method", "claim", "claim_key",
    "status", "verified", "checker", "output_sha256", "code_hash", "path",
    "evidence_kind", "result", "negation_kind", "exit_code", "verifier_output",
    "statement_evidence_kind_before", "statement_evidence_kind_after",
    "verification_required", "detail", "problems", "reason",
    # 2026-10-22 晚（业主裁定：形式化那一位要指明路径）：这一行验的是哪一份证明、
    # 那份正文的指纹、以及"这个号是谁选的"。四格都随返回值给出 —— 它们是
    # `experiments.observations` 里同一批字段的读数面。
    "proof_no", "path_id", "proof_sha256", "path_source",
    # `draft/146` D27（2026-10-23）：受控拒绝要能被派发层认出来。
    # 此前拒绝只写在 `recorded=False` + `reason` 里，而那两格 `_end_from_payload`
    # 一个都不读 ⇒ 一次"框架正确地说了不"在 `tasks.outcome` 上落成 `ok`（三档同形）。
    # 所以拒绝那一支必须自报 `refused=True` + 受控的 `refusal_reason`（与
    # `formalize` 的拒绝同形：`refused` 是第三态位，不是 `unknown`）。
    "refused", "refusal_reason",
)


def _record_shape(**fields: Any) -> dict[str, Any]:
    """把一条分支收成固定键集合（缺的键给缺省值，一个都不少）。"""
    out: dict[str, Any] = {key: None for key in _RECORD_KEYS}
    out.update({
        "recorded": False, "experiment_id": "", "statement_id": "",
        "method": "formal", "claim": "", "claim_key": "",
        "status": "unknown", "verified": None, "checker": "", "output_sha256": "",
        "code_hash": "", "path": "", "evidence_kind": "", "result": "",
        "negation_kind": "", "exit_code": None, "verifier_output": "",
        "statement_evidence_kind_before": "", "statement_evidence_kind_after": "",
        "verification_required": True, "detail": "", "problems": [], "reason": "",
        "proof_no": 0, "path_id": "", "proof_sha256": "", "path_source": "",
        "refused": False, "refusal_reason": None,
    })
    out.update(fields)
    return out


class _Record:
    """`record` 这一格（见模块 docstring）。"""

    def record(
        self,
        statement_id: str,
        code_path: str,
        *,
        declaration_name: str | None = None,
        proof_no: Any = None,
        path_id: str = "",
        path_source: str = "",
        imports: Sequence[str] | None = None,
        timeout_sec: float | None = None,
        status: str | None = None,
        verified: bool | None = None,
        checker: str | None = None,
        verifier_output: str | None = None,
        exit_code: int | None = None,
        for_question_id: str | None = None,
        notes: str = "",
    ) -> dict:
        """把"命题 `statement_id` × 文件 `code_path`"这一次形式化检查登记成一行实验。

        前两个位置参数是绑定（哪条命题、哪份产物），其余是读数与对账项。
        返回值的键集合见 :data:`_RECORD_KEYS`（每一条分支上都成立）。

        ## 这一行绑的是"哪一份证明"（业主 2026-10-22：「要指明对哪个路径做了形式化验证」）
        `proof_no` 是这一趟验的那一份证明（`#p1` 是行上的 `proof_text`，`#p2` 起在
        `proofs` 清单里）。规矩与 `formalize` 逐条相同：号不在册 ⇒ `proof_path_not_found`；
        多路径没给号 ⇒ `proof_path_unspecified`，一行都不写；只有一份证明时缺省就是它。
        落进这一行的四格（`observations` 与 `params` 各一份）：
        `proof_no` / `path_id`（C 的显示名，只做标记、不当键）/ `proof_sha256`
        （这一份正文的指纹：读侧拿它与现行正文比，不符就是"验过、过期了"）/
        `path_source`（谁选的这条路径：`B` / `C` / `L`；空 = 没交代）。
        "谁选的"（`path_source`）与"谁验的"（`observations.recorded_by` = L）是两格，
        不许合成一格：把 B 指定的路径记成"L 自己选的"，读数就再也追不回是谁的判断。
        """
        sid = str(statement_id or "").strip()
        rel = str(code_path or "").strip()
        wanted_source = str(path_source or "").strip()
        if wanted_source and wanted_source not in PATH_SOURCES:
            # 走同一个受控拒绝口（`refused=True` + `refusal_reason` 是派发层认的那两格，
            # 见 `draft/146` D27）：这一支不许自己拼一个 `_record_shape`。
            return self._record_refuse(
                "bad_path_source",
                (f"path_source={path_source!r} 不在受控取值里（{list(PATH_SOURCES)}；"
                 "空 = 没交代）⇒ 这一行不登记：它记的是「谁选的路径」，"
                 "编一个来源等于把别人的判断写成自己的"),
                statement_id=sid, path=rel)
        # ---- 1. 命题行：必须存在、必须有正文（没有正文就没有"被形式化的那条命题"）
        row, problem = self._statement_row(sid)
        if row is None:
            return self._record_refuse(
                "statement_not_found", problem, statement_id=sid, path=rel)
        claim = SB.body_of(row)
        if not claim:
            return self._record_refuse(
                "statement_body_empty",
                f"命题 {sid} 没有正文（`{SB.BODY_FIELD}` 与 `{SB.TEXT_FIELD}` 都是空的）"
                "⇒ 没有可形式化的那一句话，这一行不登记",
                statement_id=sid, path=rel)
        before = str(row.get("evidence_kind") or "")
        claim_key = f"{STATEMENT_CLAIM_KEY_PREFIX}{sid}"
        # ---- 1b. 这一行绑的是哪一份证明（与 `formalize` 同一套判据，同一处实现）
        #
        # 位置在写盘之前：号不在册 / 多路径未给号都在这里受控拒绝，一个字节都不写。
        chosen = _path_choice({"ok": True, "statement_id": sid, "row": dict(row)},
                             proof_no=proof_no)
        if not chosen.get("ok"):
            return self._record_refuse(
                str(chosen["reason"]), str(chosen["detail"]), statement_id=sid,
                claim=claim, claim_key=claim_key, path=rel)
        path_number = int(chosen["proof_no"])
        proof_text_now = str(chosen.get("proof_text") or "")
        #: 这一份正文的指纹：读侧拿它与现行正文比（不符 ⇒ 那条路径 stale）。
        proof_sha256 = _VR.proof_sha(proof_text_now)
        # ---- 2. 产物：必须在工作区里、必须是 `.lean`
        try:
            target = self._resolve(rel)
        except ExperimentError as exc:
            return self._record_refuse(
                "path_outside_workspace", str(exc), statement_id=sid, claim=claim,
                claim_key=claim_key, path=rel)
        if not rel.lower().endswith(".lean"):
            return self._record_refuse(
                "artifact_not_lean",
                f"产物 {rel!r} 不是 .lean 源文件 —— `method='formal'` 的输入只能是"
                "检查器能读的形式化源码；数值脚本请走 E 的 `run_experiment`",
                statement_id=sid, claim=claim, claim_key=claim_key, path=rel)
        # ---- 2a. 产物文件名与证明号必须对得上（`formalize` 的命名约定是同一件事）
        #
        # `#p1` 的产物是 `code/formal/<声明名>.lean`，`#p2` 起是 `...__p<n>.lean`
        # （见 `agent_l/formalize.py` 的落盘名）。这一条判据守的是"登记进去的那份源码
        # 到底是不是这条路径的"：`#p2` 配一份 `#p1` 的文件时，检查器验的是另一份源码，
        # 而台账上会写着"第 2 条路径 verified" —— 那条读数没有任何东西能反驳。
        if path_number > 1 and not Path(rel).stem.endswith(f"__p{path_number}"):
            return self._record_refuse(
                "proof_path_artifact_mismatch",
                (f"这一行绑的是第 {path_number} 份证明，而产物 {rel!r} 的文件名不带 "
                 f"`__p{path_number}`（`formalize` 的约定：`#p1` = `<声明名>.lean`，"
                 f"`#p2` 起 = `<声明名>__p<n>.lean`）⇒ 检查器验的是另一份源码，"
                 "这一行不登记：号与产物不许对不上"),
                statement_id=sid, claim=claim, claim_key=claim_key, path=rel)
        try:
            payload = target.read_bytes()
        except OSError as exc:
            return self._record_refuse(
                "tool_failed",
                f"读不了 {rel}（{type(exc).__name__}: {exc}）⇒ 这一行不登记",
                statement_id=sid, claim=claim, claim_key=claim_key, path=rel)
        code_hash = sha256_of_bytes(payload)
        # ---- 2b. 交给检查器的名字：与 `formalize` 同一套解析（短名自动升级成限定名）
        #
        # 为什么必须走同一处：桥接层会往源码尾部追加一条 `#print axioms <名字>`，而
        # Lean 4 里 `namespace LProbe` 之内的定理在文件作用域叫 `LProbe.<短名>` ——
        # 只给短名时检查器报 `unknown constant`，于是一条真定理被记成
        # `compile_error`（真机读数，2026-10-22；`formalize` 的 docstring 逐字登记过）。
        # 这里直接调那两个函数，不抄第二份解析：两处各解析一次就会出现
        # "formalize 说 verified、record 说 compile_error"这种没人会去查的漂移。
        source_text = payload.decode("utf-8", errors="replace")
        given_name = str(declaration_name or "").strip()
        checker_name = _checker_name(given_name, declaration_name_in(source_text))
        # ---- 3. 现跑一次检查器（唯一实现：自检闸 + 桥接层）
        t0 = time.monotonic()
        data = dict(self.check_formal(
            claim, script_path=rel, declaration_name=checker_name or None,
            imports=imports, timeout_sec=timeout_sec,
        ))
        runtime_sec = round(time.monotonic() - t0, 4)
        fresh_status = str(data.get("status") or "unknown")
        fresh_verified = data.get("verified") is True
        output = str(data.get("verifier_output") or "").strip()
        checker_label = _checker_label(data)
        # ---- 4. 对账：调用方口述的读数只许"往弱里说"，不许比检查器更强
        #
        # 为什么不是"逐字相等"：`formalize` 的 `status` 是综合结论（检查器原话叠加
        # 忠实复述的 coverage 读数，见 `specs/l.py` 的动作摘要），而本动作现跑的是
        # `check_formal`（检查器原话那一层）。覆盖不全时 `formalize` 如实说 unknown，
        # 而检查器可能说 verified —— 那是降档，正是三态纪律要求的那件事
        # （业主口径：「覆盖率 < 100% ⇒ 结论只能是 unknown（不是 verified）」）。
        # 所以对账的判据是单向的：声称得比检查器强 ⇒ 拒绝；声称得更弱 ⇒ 收下，
        # 并且这一行按更弱的那一档落（那条不变量在这里，不在调用方的自觉里）。
        mismatch = _readings_mismatch(
            given_status=status, given_verified=verified,
            given_output=verifier_output, given_exit=exit_code,
            given_checker=checker, fresh_checker=checker_label,
            fresh_status=fresh_status, fresh_verified=fresh_verified,
            fresh_output=output, fresh_exit=data.get("exit_code"))
        if mismatch:
            return self._record_refuse(
                "reading_mismatch",
                f"{mismatch} ⇒ 这一行不登记（登记的只能是检查器刚说的那一份；"
                "调用方的读数比它更强时，写进去的会是别人的话）",
                statement_id=sid, claim=claim, claim_key=claim_key, path=rel,
                status=fresh_status, verified=fresh_verified,
                checker=checker_label, verifier_output=output, code_hash=code_hash,
                output_sha256=sha256_of_bytes(output.encode("utf-8")),
                statement_evidence_kind_before=before,
                statement_evidence_kind_after=before)
        composite = str(status or fresh_status)
        # 这一行的证据档 = 检查器说 verified 且 调用方没有把它降档。
        # 只取其中一个都会漏掉一类谎：只看检查器 ⇒ coverage 0% 也能记 proof；
        # 只看调用方 ⇒ 现编一个 verified 就能记 proof。
        effective_verified = fresh_verified and composite == "verified"
        # ---- 5. 三态 → 证据形状（与 E 的 `_record_formal` 同一套映射，不抄第二份）
        #
        # 映射按检查器那一层算（`tri_state` 是桥接层的三态，不是综合结论）：
        # 那是 `agent_e/core.py::_record_formal` 的口径，同一个 `experiments` 行在
        # E 与 L 名下必须同形。综合结论只降档：检查器说 verified 而综合不是
        # verified 时，这一行的 evidence_kind 退回 `heuristic`、result 记
        # `inconclusive`，并在 observations 里逐字留下 `downgraded` 的理由。
        derived, _neg = _formal_derived(data, fresh_status, fresh_verified, output)
        if fresh_verified and not effective_verified:
            derived.update({"result": "inconclusive", "evidence_kind": _NO_EVIDENCE_KIND})
        obs = derived["observations"]
        obs.update({
            "status": composite,
            "checker_status": fresh_status,
            "verified": effective_verified,
            "checker_verified": fresh_verified,
            "status_source": "caller" if status not in (None, "") else "checker",
            "downgraded": bool(fresh_verified and not effective_verified),
            "checker": checker_label,
            # `draft/146` D27：调用方口述的那台检查器记下来（不是默默丢掉）。
            # 与 `checker`（现跑那一台的真名 + 版本）并排放，读的人一眼看得出
            # "它自称跑在哪台机器上、实际跑在哪台"。空串 = 调用方没声明（不是撒谎）。
            "checker_claimed": str(checker or ""),
            "output_sha256": sha256_of_bytes(output.encode("utf-8")),
            "statement_id": sid,
            "statement_evidence_kind": before,
            "declaration_name": checker_name,
            "code_hash": code_hash,
            "recorded_by": self.actor,
            # ---- 路径四格（业主 2026-10-22：「要指明对哪个路径做了形式化验证」）。
            # `proof_sha256` 是"这次形式化验的是哪一份正文"的指纹：B 的登记那条路
            # （`register_statement`）把它抄进 `bits.evidence.formal_by_proof[证明号]`，
            # 读侧拿它与现行正文比 —— 不符就是"验过、过期了"（stale），不是"验过"。
            "proof_no": path_number,
            "path_id": str(path_id or ""),
            "proof_sha256": proof_sha256,
            "path_source": wanted_source,
        })
        note_lines = [
            f"[formal] 检查器原样状态 {str(data.get('verifier_status') or '')!r}"
            f"（L 的受控理由 {str(data.get('reason') or '')!r}）；"
            + (_declared_name_note(checker_name) if checker_name else ""),
            f"[formal] 绑定命题 {sid}（claim_key={claim_key}）；产物 {rel}"
            f"（sha256 前 16 位 {code_hash[:16]}）",
            (f"[formal] 这一行绑的是第 {path_number} 份证明（这一份正文 sha256 前 12 位 "
             f"{proof_sha256[:12]}；路径来源 {wanted_source or '没交代'}；"
             f"path_id={str(path_id or '（空）')}）—— 号不在册的证明不会被记到 #p1 头上"),
            (f"[formal] 检查器说 verified，而综合结论是 {composite!r} ⇒ 按综合结论落"
             "（覆盖不全的忠实复述不许记成 proof）"
             if fresh_verified and not effective_verified else
             ("[formal] ⇒ 本次是 proof 级证据（检查器说的，且综合结论没有被降档）"
              if effective_verified else
              f"[formal] ⇒ 本次不是 proof：三态={composite}"
              f"（{one_line(data.get('reason') or '')}）⇒ 一行都不标成 proof")),
            "[formal] 这次登记不动 `statements`：形式化 ≠ 审过。"
            f"那一行的证据档仍是 {before or '（空）'}，升档仍然要 V 的那一签",
        ]
        if str(notes or "").strip():
            note_lines.append(f"[formal] 调用方附注：{one_line(notes)}")
        derived["notes"] = list(derived.get("notes") or []) + note_lines
        exit_code_value = (0 if effective_verified else
                           int(data["exit_code"]) if isinstance(data.get("exit_code"), int)
                           else None)
        with self.store.tx("experiments", actor=self.actor, note="l.record") as tx:
            eid = tx.alloc_id("experiment")
            built = build_experiment(
                eid, claim, claim_key,
                method="formal",
                code_path=rel,
                code_hash=code_hash,
                derived=derived,
                exit_code=exit_code_value,
                runtime_sec=runtime_sec,
                params={"checker": checker_label, "statement_id": sid,
                        "declaration_name": checker_name,
                        # 路径四格在这里各有一份：`observations` 是读数面、`params` 是
                        # 复跑面（B 的登记那条路两处都认，见 `evidencebits.formal_ledger_reading`）。
                        "proof_no": path_number, "path_id": str(path_id or ""),
                        "proof_sha256": proof_sha256, "path_source": wanted_source},
                artifact_paths=(rel,),
                for_question_id=for_question_id,
                verifier_output=output,
                verifier_subject_key=claim_key if output else "",
                created_by=self.actor,
            )
            tx.upsert("experiments", built.to_dict(), note=f"formal:{claim_key}")
        after_row, _ = self._statement_row(sid)
        after = str((after_row or {}).get("evidence_kind") or "")
        self._log("formal.record wrote", **{"experiment_id": eid, "statement_id": sid,
                                           "status": composite,
                                           "evidence_kind": built.evidence_kind})
        return _record_shape(
            recorded=True, experiment_id=eid, statement_id=sid, claim=claim,
            claim_key=claim_key, status=composite, verified=effective_verified,
            checker=checker_label, verifier_output=output,
            output_sha256=str(obs["output_sha256"]), code_hash=code_hash, path=rel,
            evidence_kind=built.evidence_kind, result=built.result,
            negation_kind=built.negation_kind, exit_code=exit_code_value,
            statement_evidence_kind_before=before, statement_evidence_kind_after=after,
            verification_required=True, reason=str(data.get("reason") or ""),
            proof_no=path_number, path_id=str(path_id or ""),
            proof_sha256=proof_sha256, path_source=wanted_source,
            detail=one_line("这一行已落 experiments（method=formal）；"
                            f"检查器 status={fresh_status!r}，综合 status={composite!r}；"
                            f"命题档位写前 {before or '（空）'} / 写后 {after or '（空）'}；"
                            f"绑第 {path_number} 份证明（正文 sha256 前 12 位 "
                            f"{proof_sha256[:12]}）"),
        )

    # ------------------------------------------------------------ 内部
    def _statement_row(self, sid: str) -> tuple[Mapping[str, Any] | None, str]:
        """按号取一条 `statements` 行：`(行, 没有时的人话)`。

        为什么用"读一次全表再线性找"：`Store.rows` 是既有的唯一读法，
        这里不新造一个按主键查的入口（多一个读法就多一处能漂的口径）。
        """
        if not sid:
            return None, "没给 statement_id ⇒ 登记不了（这一行必须绑定到台账里的一条命题）"
        try:
            rows = self.store.rows("statements")
        except Exception as exc:  # noqa: BLE001
            return None, (f"读不了 statements（{type(exc).__name__}: {exc}）"
                          "⇒ 没查成，不是『没有这条命题』")
        for row in rows:
            if str(row.get("stmt_id") or "") == sid:
                return row, ""
        return None, (f"台账里没有编号为 {sid!r} 的命题 ⇒ 不登记"
                      "（形式化实验行必须绑定到一条已经登记过的命题）")

    def _record_refuse(self, reason: str, detail: str, **fields: Any) -> dict:
        """受控拒绝（固定键集合 + `recorded=False` + `refused=True` + 一行原因）。

        `refused` / `refusal_reason` 是给派发层看的（`draft/146` D27）：`record` 的
        六条拒绝理由码（`statement_not_found` / `reading_mismatch` / …）是这一格的细一档，
        不在 `schema.REFUSAL_REASONS` 里；行上落 `invalid_params`（词表定义正是"参数 /
        前置条件不满足：这次调用本身不成立"），细一档留在 `reason` 与 `detail` 里。
        """
        assert reason in RECORD_REASONS or reason in (
            "path_outside_workspace", "tool_failed",
            "declaration_name_needed"), (
            f"record 的理由码 {reason!r} 不在受控词表里 —— 拒绝也是一种结论，它的名字必须登记")
        one = one_line(detail)
        return _record_shape(recorded=False, reason=reason, detail=one,
                             problems=[one] if one else [],
                             refused=True, refusal_reason="invalid_params", **fields)


def _checker_label(data: Mapping[str, Any]) -> str:
    """检查器的名字 + 版本（`lean 4.7.0`）；读不到版本时只写名字。"""
    face = data.get("lean") if isinstance(data.get("lean"), Mapping) else {}
    version = str((face or {}).get("version") or "").strip()
    return f"lean {version}".strip()


#: 版本号出现在"检查器标签"里的形态（`lean 4.7.0` / `Lean 4.7.0-rc1` ⇒ `4.7.0`）。
_VERSION_IN_LABEL = re.compile(r"\d+(?:\.\d+)+")


def _checker_version_of(label: Any) -> str:
    """检查器标签里的版本号（读不到给空串）。

    为什么要剥出版本号再比（`draft/146` D27 的口径）：`lean 4.7.0` 与 `Lean 4.7.0`
    是同一台机器，逐字比会把一次合法调用判成不一致；而 `Lean 3.0.0` 与 `4.7.0`
    是两台机器，不比就允许调用方把"另一台机器的读数"贴到这一行上。
    """
    found = _VERSION_IN_LABEL.search(str(label or ""))
    return found.group(0) if found else ""


def _readings_mismatch(*, given_status: Any, given_verified: Any, given_output: Any,
                       given_exit: Any, given_checker: Any, fresh_checker: str,
                       fresh_status: str, fresh_verified: bool,
                       fresh_output: str, fresh_exit: Any) -> str:
    """调用方口述的读数里那些"比检查器更强"的声称（空串 = 没有 / 只是更弱）。

    判据是单向的（见 `record` 第 4 步的长注释）：

    - 声称 `verified` / `verified=True` / `exit_code=0`，而现跑不是 ⇒ 不一致（拒绝）；
    - 声称 `failed`，而现跑不是 failed ⇒ 不一致（拒绝：那是在替检查器说"不行"）；
    - 声称 `unknown` / `verified=False` ⇒ 永远允许（降档是三态纪律要的那件事）；
    - 给了 `verifier_output` 而它与现跑的那段不是同一段 ⇒ 不一致（拒绝：那是一段
      来路不明的话，而 `evidence_kind="proof"` 的全部价值就在"这句话是检查器说的"）。

    `checker` 的判据（`draft/146` D27，2026-10-23 补）：比版本号，不比写法。
    此前这里明写"checker 刻意不比"，于是那个形参收下来既不比也不记（那一格是死的）。
    现在的口径是三条：

    - 没给（空）⇒ 不比，也不拒：它是可选读数，缺席不是谎；
    - 给了但没有版本号（`lean` / `Lean checker`）⇒ 不比：那是泛称，不是更强的声称；
    - 给了版本号而现跑那一台读得到版本且不同 ⇒ 不一致（拒收：这一行写进去的会是
      "另一台机器"的读数，而 `params["checker"]` 与调用方口述从此分家、台账上看不出来）。
      现跑版本读不到（`checker_label` 只有名字）时也不拒 —— 那是"没读成"，不是"不一致"。
    """
    if str(given_status or "") == "verified" and not fresh_verified:
        return f"调用方说 status='verified'，现跑是 {fresh_status!r}"
    if str(given_status or "") == "failed" and fresh_status != "failed":
        return f"调用方说 status='failed'，现跑是 {fresh_status!r}"
    if given_verified is True and not fresh_verified:
        return f"调用方说 verified=True，现跑是 {fresh_verified!r}"
    if given_output not in (None, ""):
        if " ".join(str(given_output).split()) != " ".join(fresh_output.split()):
            return "调用方给的 verifier_output 与现跑得到的检查器原话不是同一段"
    if given_exit is not None and int(given_exit) == 0 and fresh_exit is not None \
            and int(fresh_exit) != 0:
        return f"调用方说 exit_code=0，现跑是 {fresh_exit!r}"
    claimed_version = _checker_version_of(given_checker)
    actual_version = _checker_version_of(fresh_checker)
    if claimed_version and actual_version and claimed_version != actual_version:
        return (f"调用方说检查器是 {str(given_checker)!r}（版本 {claimed_version}），"
                f"而现跑那一台是 {fresh_checker!r}（版本 {actual_version}）")
    return ""


def _formal_derived(data: Mapping[str, Any], status: str, verified: bool,
                    output: str) -> tuple[dict[str, Any], str]:
    """三态 → `build_experiment` 要的那几格（与 E 的 `_record_formal` 同一套映射）。

    为什么这一段必须与 E 逐条同源：`experiments` 那一行是跨角色共享的证据面，
    同一个检查器状态在 E 与 L 名下写成两种形状，下游（`verify` 的审计、
    `closing` 的收工门、论文的证据分档统计）就会把同一件事读成两件事。
    所以这里不新写映射规则：它按 `agent_e/core.py::_record_formal` 的三条分支
    落地（`verified` / `checked_failed` / `not_checked`），差异只有"这一行绑定的是命题号"。
    """
    if verified:
        tri_state = "verified"
    elif data.get("checked") is True:
        tri_state = "checked_failed"
    else:
        tri_state = "not_checked"
    if tri_state in ("verified", "checked_failed"):
        negation_kind = "not_proved"
    elif status in ("timeout", "tool_crashed"):
        negation_kind = "no_local_evidence"
    else:
        negation_kind = "not_searched_here"
    derived: dict[str, Any] = {
        "result": "supports" if verified else "inconclusive",
        "evidence_kind": "proof" if verified else _NO_EVIDENCE_KIND,
        "negation_kind": negation_kind,
        "observations": {
            "verifier_status": str(data.get("verifier_status") or ""),
            "formal_reason": str(data.get("reason") or ""),
            "checked": data.get("checked"),
            "tri_state": tri_state,
            "missing_imports": [str(x) for x in (data.get("missing_imports") or [])],
            "lean_version": str((data.get("lean") or {}).get("version") or ""),
        },
        "counterexample": None,
        "notes": [f"[formal] 检查器原话：{_digest(output, 400)}"] if output else [],
    }
    return derived, negation_kind


__all__ = ["_Record"]
