# -*- coding: utf-8 -*-
"""秘书的档位落行（一个路径一行，从 secretary.py 的 U25 后半逐字搬出）。

我保证哪条不变式：没号或没路径号时不落行，但要在 `unrecorded` 里留一条 —— 「没记」与「没号可记」必须分得开，否则档位读数会静默地少几行。

## 为什么它能单独成文件（依赖方向）

它只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from typing import Mapping

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    NONTRIVIALITY_UNJUDGED,
)

from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    nontriviality_path,
)

from .secretary_tier_judge import (  # noqa: F401 — 这些名字由 secretary_tier_judge 定义
    NONTRIVIALITY_NOT_APPLICABLE_BASIS,
)

from .secretary_tier_ledger import (  # noqa: F401 — 这些名字由 secretary_tier_ledger 定义
    _judged_body_sha,
    _nontriviality_index,
    _row_path_group,
    append_nontriviality,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    _nontriviality_level,
    nontriviality_label,
)


class TierRecordMixin:
    """档位落行（一个路径一行）（从 secretary.py 搬出的混入类）。"""

    def record_nontriviality(self, reading: Mapping[str, Any], *, stmt_id: str,
                             path_group: int = 0, statement_full: str = "",
                             landed_body_sha256: str = "",
                             judged_body_sha256: str = "") -> dict[str, Any]:
        """把判过的读数落进旁支台账（"判/落拆段"的落这一半，NT2）。

        ## 落的条件（业主口径的两条，缺一不落）

        | 条件 | 拿不到时的处置 |
        |---|---|
        | `stmt_id` 非空 | `tri="unrecorded"` + 原因；决定台账留一行（钱花了，"判过"要可见） |
        | 路径级读数：`path_group >= 1` | 同上 —— 没有路径号就没法"一个路径一行"，落一行假的比不落更坏 |

        `applicable=false`（概念行）是唯一允许 `path_group=0` 的一档：它不参与命题级
        min（业主口径 ⑦：概念行的档位是 statement-scope 的"不适用"，不是一条路径）。

        ## 幂等（业主口径 B）

        同一 `(stmt_id, path_group)` 且 `judged_body_sha256` 相同 ⇒ 沿用已有读数、
        不追加一行（重复提交同一份稿不把 append-only 台账撑大）。正文变了才追加：
        逐路径"最后一行胜"（允许该路径降档/升档），命题级由读侧再取 min（永不回升）。

        ## 两枚 sha

        - `judged_body_sha256`：判的材料（命题 + 空行 + 证明，见 :func:`_judged_body_sha`）；
        - `landed_body_sha256`：落盘那一行的 `statement_full`。
        判的材料与落盘正文分开记，复核的人才能回答"判的是哪一版"。
        """
        root = getattr(self, "root", None)
        if root is None:
            return {"recorded": False, "tri": "unrecorded", "level": None, "label": "",
                    "stmt_id": str(stmt_id or ""), "path_group": int(path_group or 0),
                    "reason": "这一名秘书没有工作区根 ⇒ 判过的档位没落（不是没判）"}
        got = dict(reading or {})
        sid = str(stmt_id or "").strip()
        no = int(path_group or 0)
        applicable = bool(got.get("applicable", True))
        level = _nontriviality_level(got.get("nontriviality"))
        tri_in = str(got.get("nontriviality_tri") or "")
        if applicable and (level is None or tri_in == "unjudged"):
            # 判档本身没查成：盘上不该多一条 `nontriviality: null` 的行冒充"判过了"。
            return {"recorded": False, "tri": "unjudged", "level": None, "label": "",
                    "stmt_id": sid, "path_group": no,
                    "reason": str(got.get("reason") or "判档没查成 ⇒ 没有可落的档位行")}
        if not sid:
            return self._unrecorded_nontriviality(
                "这一笔没拿到 stmt_id ⇒ 不落档位行（判过的读数留在决定台账里）",
                stmt_id="", path_group=no)
        if applicable and no < 1:
            return self._unrecorded_nontriviality(
                "这一笔没拿到 path_group（>=1）⇒ 不落档位行（判过的读数留在决定台账里）",
                stmt_id=sid, path_group=no)
        sha = str(judged_body_sha256 or "")
        if not sha:
            sha = _judged_body_sha(statement_full, str(got.get("proof_text") or ""))
        prior = self._last_nontriviality_row(sid, no)
        if prior is not None and str(prior.get("judged_body_sha256") or "") == sha:
            return {"recorded": False, "tri": tri_in or "computed",
                    "level": level, "label": nontriviality_label(level),
                    "stmt_id": sid, "path_group": no, "reused": True,
                    "reason": ("同一 (stmt_id, path_group) 且判的是同一份正文 ⇒ "
                               "沿用已有读数，不追加一行")}
        try:
            append_nontriviality(
                root, statement_full=(statement_full
                                      or str(got.get("statement_full") or "")),
                level=level,
                basis=str(got.get("nontriviality_basis")
                          or got.get("basis") or "")[:900],
                role=str(self.role or ""), task_id=str(self.task_id or ""),
                stmt_id=sid,
                effort=(got.get("effort") if isinstance(got.get("effort"), Mapping)
                        else {}),
                text_truncated=bool(got.get("text_truncated")),
                applicable=applicable, path_group=no, judged_body_sha256=sha,
                landed_body_sha256=str(landed_body_sha256 or ""))
        except Exception as exc:  # noqa: BLE001 - 落盘失败要说出来，不许静默
            return {"recorded": False, "tri": f"unrecorded:{type(exc).__name__}",
                    "level": level, "label": nontriviality_label(level),
                    "stmt_id": sid, "path_group": no,
                    "reason": f"落盘失败：{type(exc).__name__}: {exc}"}
        return {"recorded": True,
                "tri": ("not_applicable" if not applicable else "computed"),
                "level": level, "label": nontriviality_label(level),
                "stmt_id": sid, "path_group": no, "reason": ""}

    def _last_nontriviality_row(self, stmt_id: str, path_group: int) -> dict[str, Any] | None:
        """同一 `(stmt_id, path_group)` 的最后一行（幂等判据读它，不另建索引）。"""
        root = getattr(self, "root", None)
        want = str(stmt_id or "").strip()
        if root is None or not want:
            return None
        path = nontriviality_path(root)
        if not path.is_file():
            return None
        by_id, _by_sha, why = _nontriviality_index(path)
        if why:
            return None
        rows = [r for r in (by_id.get(want) or [])
                if _row_path_group(r) == int(path_group or 0)]
        return dict(rows[-1]) if rows else None

    def _unrecorded_nontriviality(self, reason: str, *, stmt_id: str = "",
                                  path_group: int = 0) -> dict[str, Any]:
        """判过、但这一笔拿不到落行所需的两件号 ⇒ 不落，并在决定台账留一行。

        为什么决定台账也要落：这一趟的模型调用已经花掉了。盘上一条档位行都没有而
        决定台账也没有，读的人就分不清"没判"与"判了没法落"（真机的 4 条孤儿行正是
        后者，而它们连一句话都没留下）。`basis=["unrecorded"]` 是这一档的可检索标记。
        """
        reason = str(reason)[:900]
        try:
            self.note_decision(
                duty=2, decision="判过未落", reason=reason, basis=["unrecorded"],
                target={"nontriviality": str(stmt_id or ""),
                        "path_group": int(path_group or 0)},
                after="判过的读数不落档位台账（缺号）；决定台账留这一行", fail_open=True)
        except Exception:  # noqa: BLE001 - 留痕失败不许带走返回值
            pass
        return {"recorded": False, "tri": "unrecorded", "level": None, "label": "",
                "stmt_id": str(stmt_id or ""), "path_group": int(path_group or 0),
                "reason": reason}

    def not_applicable_nontriviality(self, *, statement_full: str, kind: str = "",
                                     task_id: str = "", stmt_id: str = "",
                                     record: bool = True) -> dict[str, Any]:
        """概念 / 定义行的档位读数：`不适用`（`level=None` + 台账里 `applicable=False`）。

        ## 号（2026-10-26，D16）
        落行带 `stmt_id`（概念行在 `write_concept_row` 里已经有号）；幂等比对仍按正文
        （同一段定义只落一行），但那一行与命题行的关系靠号，不靠文本。

        ## 为什么它不是"未判"（2026-10-26，业主的口径）
        "未判"说的是"该判而没判"（没缝 / 超时 / 缺证明正文 / 正文被截断），它的处置是
        "下次再判一次"；"不适用"说的是"这一问对它不成立"——概念行没有证明正文，四项力气
        读数一项都取不到，再判一次也不会有别的结论。两件事折成同一个词，读的人就会把
        "结构上不需要判"读成"漏判了"（真机 mp3-r3：30 条概念行的非平凡度一条记录都没有，
        而读侧对"没有记录"与"不需要记录"都只印一个"未判"）。

        ## 落什么
        台账那一行：`nontriviality: null` + `label: ""` +
        `basis: "不适用：概念行没有证明正文，不做力气判档"` + `applicable: false`。
        最后那一格是给读侧的判据：:func:`nontriviality_of` 据它把 `tri` 读成
        `not_applicable`（而不是 `unknown`），于是页面能把两个词分开印。

        ## 为什么空正文也照落这一行
        `judge_statement` 对 0 字命题是受控拒绝（不落台账），因为那说明"调用方给错了栏"。
        概念行不同：待补定义的概念（`pending_definition`）本来就有一段空正文，而它的
        "不适用"与定义到没到无关（有没有定义，它都没有证明）。所以这一支按正文 sha 落行，
        空正文的 sha 与所有待补概念共用那一行 —— 它们读出来的词也确实一样。

        ## 幂等（同一段正文只落一行）
        这一档的结论不随时间变（"有没有证明正文"是结构事实），所以已经落过的那一段
        正文不再追加：台账是 append-only，同一句话抄第二遍只会让它变长而不增加任何读数
        （而 `nontriviality_of` 是逐行扫的，长度就是页面一次请求的代价）。
        反过来，这一段正文还没有那一行时照落 —— 存量概念行（改前直写进来的那些）
        因此会在它下一次经秘书那一笔时被补上这一格，不需要一次全库迁移。

        ## 判/落拆段（NT2）：`record`
        B 的收录动作在写台账之前先判一次（`record=False`，零调用、零写盘）；
        等号拿到了再由 `write_concept_row` 那一笔调这里（`record=True`），按号幂等落行。
        """
        out: dict[str, Any] = {
            "checked": True, "decision": "", "applicable": False,
            "basis": [NONTRIVIALITY_NOT_APPLICABLE_BASIS],
            "reason": (f"kind={kind or '（空）'!r} 没有证明正文 ⇒ 判档这一格不适用"
                       "（不是「判不了」：它是结构上不需要判，不是该判而没判）"),
            "nontriviality": NONTRIVIALITY_UNJUDGED, "label": "",
            "nontriviality_tri": "not_applicable",
            "nontriviality_basis": NONTRIVIALITY_NOT_APPLICABLE_BASIS,
            "effort": {}, "effort_score": 0, "text_truncated": False,
            "cost": {"ledger": "", "reason": "没发调用（概念行没有证明正文 ⇒ 判档不适用）"},
        }
        if not record:
            out["recorded"] = False
            out["record_reason"] = ("判/落拆段：这一趟只判；等 write_concept_row 拿到号"
                                    "之后才落那一行")
            return out
        root = getattr(self, "root", None)
        if root is None:
            return out
        got = self.record_nontriviality(out, stmt_id=stmt_id, path_group=0,
                                       statement_full=statement_full,
                                       judged_body_sha256=_judged_body_sha(statement_full))
        out["recorded"] = bool(got.get("recorded"))
        out["record_reason"] = str(got.get("reason") or "")
        if got.get("tri") == "unrecorded":
            out["nontriviality_tri"] = "unrecorded"
        return out
