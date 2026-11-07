# -*- coding: utf-8 -*-
"""E 侧的第二道闸：数值证明型命题落库之前的「命题形态闸」（业主 2026-11-07 第二刀）。

业主原话（逐字，这就是本模块的验收标准）：

> 「F侧的注册+放弃闸需同步到E侧的数值证明路线」

F 侧那半是「命题登记时需过 F 秘书闸，审查命题描述是否规范，是否明确了从什么条件导出
什么结论」。同步到 E 侧之后，判的对象与判据一字不改 —— 仍然是
:meth:`secretary.Secretary.judge_proposition_form` 那一次判定（本模块**不写第二份**
形态判据），只是调用方从 F 的手稿登记换成了 E 的数值证明路线。

## 闸装在哪（E 侧的「登记/收录之前」）

E 把一条 conjecture 收成 `evidence_kind="proof"` 的凭据，落点是
`experiments` 那一行（`numericproof.sign_experiment` 现算档位）。所以闸必须在
**那一行写盘之前**：`AgentE.run_experiment` 在算完 `wants_numeric_proof`、还没开
`store.tx` 的时候问一次；不过 ⇒ 受控拒，一个字节都不写（实验行、原始输出、
②③ 报告、e-proof 手稿都不落）。

## 三态（与 F 侧同一套纪律）

- `submittable=True`：判定做了、`well_formed=True` ⇒ 放行；
- `submittable=False` + `checked=True, well_formed=False`：判过了、不合格 ⇒ 受控拒；
- `submittable=False` + `checked=False`：没判成（没有秘书 / 没缝 / 超时 / 坏 JSON /
  词表外 / 判定那一问自己抛了）⇒ 同样受控拒（**没判成不许折成没毛病**）。

三档都要落进 `out/secretary/proposition_form.jsonl`（`role="E"`）——
否则"这一趟没跑过闸"与"跑过了、都合格"在收工读数上不可分。
"""
from __future__ import annotations

from typing import Any

#: 构造参数里"调用方没给秘书"用的哨兵：给了（哪怕是 `None`）就不再自己派生。
_UNSET = object()


class _NumericProofFormGate:
    """`AgentE` 的形态闸 mixin（与 `_RunExperiment` 同一层：`core.AgentE` 同时混入）。"""

    #: 由 `AgentE.__init__` 写入（`secretary=` 显式给了才有这一格）；
    #: 没有这一格 ⇒ :meth:`_e_secretary` 惰性派生 `secretary:E`。
    e_secretary: Any = _UNSET

    def _e_secretary(self) -> Any:
        """E 自己的秘书；拿不到就 `None`（调用方必须 fail-closed）。

        与 F 的 `_secretary` 同一条取舍：派生失败不抛（那是环境问题），但"没有秘书"
        会让这一问**没判成**并如实写进形态台账 —— "没判成"绝不许写成"判过了"。
        """
        got = getattr(self, "e_secretary", _UNSET)
        if got is not _UNSET:
            return got
        try:
            from ..secretary import for_role_wired

            root = (getattr(self, "workspace_root", None)
                    or getattr(self.store, "root", "") or ".")
            self.e_secretary = for_role_wired("E", root=root, store=self.store)
        except Exception as exc:  # noqa: BLE001 —— 派生失败 ⇒ 这一格关闭，但不许静默
            self.e_secretary_problem = f"{type(exc).__name__}: {exc}"
            self.e_secretary = None
        return self.e_secretary

    def _proposition_form_gate(self, *, full: str, kind: str = "conjecture",
                               label: str = "", proof_text: str = "",
                               task_id: str = "") -> dict[str, Any]:
        """数值证明型命题落库之前过一道形态闸（E 侧唯一调用点）。

        判据本体只有一处：:meth:`secretary.Secretary.judge_proposition_form`
        （与 F 的手稿登记闸同一个判定口）。本方法只做三件本层的事：
        ① 把这条命题的正文 / 种类 / 标签递过去；② 把"没判成"也写进形态台账；
        ③ 把判定折成 `submittable`（两态：能登记 / 受控拒）。
        """
        out: dict[str, Any] = {
            "checked": False, "well_formed": False, "submittable": False,
            "conditions": "", "conclusion": "", "problems": [], "decision": "",
            "refused": "", "reason": "", "actor": "", "cached": False,
        }
        try:
            from ..secretary import (NOT_APPLICABLE_KINDS, PROPOSITION_FORM_REFUSED,
                                     append_proposition_form)
        except Exception as exc:  # noqa: BLE001 —— 模块拿不到就是"没判成"（fail-closed）
            out.update(refused="proposition_form_unavailable",
                       reason=f"形态闸那一格没接上（{type(exc).__name__}: {exc}）⇒ 没判成")
            return out

        root = str(getattr(self, "workspace_root", "") or getattr(self.store, "root", "") or "")

        def _note(reason: str) -> None:
            """把"没判成"也写进形态台账（写不进去只影响读数，不改受控拒的结论）。"""
            if not root:
                return
            try:
                append_proposition_form(
                    root, statement_full=str(full or ""), checked=False,
                    well_formed=False, conditions="", conclusion="",
                    problems=[str(reason)[:200]], decision="没判成",
                    refused=PROPOSITION_FORM_REFUSED, reason=str(reason),
                    label=str(label or ""), kind=str(kind or ""), stmt_id="",
                    role="E", task_id=task_id)
            except Exception as exc:  # noqa: BLE001 - 台账写不进去要看得见，不改判定
                out["ledger_error"] = f"{type(exc).__name__}: {exc}"

        if str(kind or "").strip().lower() in NOT_APPLICABLE_KINDS:
            out.update(checked=True, well_formed=True, submittable=True,
                       reason=(f"kind={kind!r} 落在 concept/definition 那一档：它不是命题"
                               "（没有「条件 → 结论」）⇒ 不受这道闸管"))
            return out
        sec = self._e_secretary()
        if sec is None:
            why = ("E 的秘书派生不出来"
                   f"（{getattr(self, 'e_secretary_problem', '未知原因')}）⇒ "
                   "这一问没判成：受控拒（没判成不等于没毛病）")
            out.update(refused=PROPOSITION_FORM_REFUSED, reason=why)
            _note(why)
            return out
        try:
            got = dict(sec.judge_proposition_form(
                statement_full=str(full or ""), label=str(label or ""),
                kind=str(kind or ""), proof_text=str(proof_text or ""),
                task_id=task_id) or {})
        except Exception as exc:  # noqa: BLE001 —— 判定那一问炸了 = 没判成（受控拒）
            why = (f"形态判定调用失败（{type(exc).__name__}: {exc}）⇒ "
                   "没判成：受控拒（没判成不等于没毛病）")
            out.update(checked=False, well_formed=False, submittable=False,
                       refused=PROPOSITION_FORM_REFUSED, reason=why,
                       problems=[str(exc)[:200]])
            _note(why)
            return out
        out.update(
            checked=bool(got.get("checked")), well_formed=bool(got.get("well_formed")),
            conditions=str(got.get("conditions") or ""),
            conclusion=str(got.get("conclusion") or ""),
            problems=[str(x) for x in (got.get("problems") or [])],
            decision=str(got.get("decision") or ""),
            actor=f"secretary-{getattr(sec, 'role', 'E')}",
            refused=str(got.get("refused") or ""),
            reason=str(got.get("reason") or ""),
            cached=bool(got.get("cached")))
        out["submittable"] = bool(out["checked"] and out["well_formed"])
        if not out["checked"]:
            out["refused"] = out["refused"] or PROPOSITION_FORM_REFUSED
            if not got.get("ledger"):
                # 秘书那一层没写成台账（例如没有 store / 判定前就早退了）⇒ 补一条"没判成"。
                _note(str(out.get("reason") or "没判成"))
        return out
