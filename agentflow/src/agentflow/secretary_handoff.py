# -*- coding: utf-8 -*-
"""秘书的交接稿与稿通道（从 secretary.py 的 U11 逐字搬出）。

我保证哪条不变式：执笔失败必须报错 —— 这是本文件唯一的非 fail-open 路径：稿子没拿到就是没拿到，不许静默退回一句「已交接」。

## 为什么它能单独成文件（依赖方向）

`secretary_handoff` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_handoff` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import manuscripts as MS
from . import proofloc as _PL
from . import statementledger as SL
import hashlib
import re

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    PROPOSITION_KINDS,
)

from .secretary_deps import (  # noqa: F401 — 这些名字由 secretary_deps 定义
    _assign_path_group_in_tx,
    _existing_path_group_in_tx,
    _note_path_material,
    _path_material_numbers,
    _stamp_path_number,
)

from .secretary_proofkind import (  # noqa: F401 — 这些名字由 secretary_proofkind 定义
    PROOF_KIND_UNJUDGED,
    PROOF_SAME_KIND,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    KIND_HANDOFF,
)

from .secretary_wash import (  # noqa: F401 — 这些名字由 secretary_wash 定义
    _dep_step_key,
    _stmt_edge_count,
)


class HandoffMixin:
    """交接稿与稿通道（从 secretary.py 搬出的混入类）。"""

    def handoff_add(self, *, to: str, summary: str, body: str, refs: Iterable[str] = (),
                    task_id: str = "", sid: str = "", note: str = "",
                    to_task_id: str = "", to_task_ids: Iterable[str] | None = None,
                    ) -> dict[str, Any]:
        """增：替本体执笔一行交接手稿（`manuscripts.write`）。

        这一格不许 fail-open：写失败必须报错留痕（`draft/55` §5.2）。
        静默放行的后果是"手稿缺行"，而缺行与"没交接"在账本上长得一样 ——
        那会让下一次"这条是不是已经交接过"判错。所以这里 `raise` 之后再留痕。

        `to_task_id` / `to_task_ids`（2026-10-26，Q2「发 / 收两栏要显示绝对编码」）：
        收件人的绝对编码，原样转发给 `manuscripts.write`。本方法不算它 ——
        解析只发生在 `agent_loop._do_handoff` 那一处（它手里已经有 `_handoff_address`
        解析出来的 `task_id`，广播面还有 `_callable_members` 给的子代理编号）；
        秘书在这里再算一次就是第二份解析，而两份解析漂了不会有任何东西会响。
        """
        try:
            rec = MS.write(self.root, sender=self.role, recipient=str(to).upper(),
                           summary=str(summary), body=str(body), refs=list(refs),
                           task_id=str(task_id), sid=str(sid), note=str(note),
                           to_task_id=str(to_task_id), to_task_ids=to_task_ids)
        except Exception as exc:
            self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                               reason="手稿执笔失败（这一格不许静默放行）",
                               basis=["draft/55 §5.2"], mid="", fail_open=False,
                               error=f"{type(exc).__name__}: {exc}",
                               target={"to": str(to)})
            raise
        self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                           reason="替本体执笔一行交接手稿（sender 仍是被服务的角色）",
                           basis=["draft/55 §4 归属与审计"], mid=str(rec.get("id") or ""),
                           target={"to": str(to)}, fail_open=False)
        return rec

    def handoff_revise(self, *, mid: str, summary: str = "", body: str = "",
                       task_id: str = "", reason: str = "", note: str = "") -> dict[str, Any]:
        """改：追加一条修订行（`manuscripts.revise`，旧行保留）。

        与 :meth:`handoff_add` 同一条纪律：写失败必须报错留痕。
        `task_id`（2026-10-08 晚补）：一实例一秘书之后，每一行都要能对回实例 ——
        真机读数（`draft/89` §3）是 1562 行里 593 行没有这一格，而它们正是走
        `agent_loop._do_handoff` 那条路的（形参本来就在 `handoff_add` / `manuscripts.revise`
        上，缺的是调用点不传）。
        """
        try:
            rec = MS.revise(self.root, mid=str(mid), summary=str(summary), body=str(body),
                            task_id=str(task_id),
                            reason=str(reason), note=str(note))
        except Exception as exc:
            self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                               reason="手稿订正失败（这一格不许静默放行）",
                               basis=["draft/55 §5.2"], mid=str(mid), fail_open=False,
                               error=f"{type(exc).__name__}: {exc}")
            raise
        self.note_decision(duty=1, kind=KIND_HANDOFF, decision="已执笔",
                           reason=f"追加修订行（订正 {mid}，旧行保留）",
                           basis=["draft/53 §2.1 改", "draft/55 §3.1"],
                           mid=str(rec.get("id") or ""), target={"revises": str(mid)})
        return rec

    def handoff_query(self, *, mid: str = "", to: str = "", sender: str = "",
                      refs: str = "", revises: str = "") -> list[dict[str, Any]]:
        """查：判"这条是不是重复委派 / 是不是已经交接过"（用户点名的"至少要能读 handoffs"）。

        纯只读；`revises` 非空时只回"订正过某一号"的那些行。
        """
        if revises:
            return MS.revisions_of(self.root, revises)
        if mid:
            got = MS.row_of(self.root, mid)
            return [got] if got else []
        out = MS.list_all(self.root, to=str(to), sender=str(sender), limit=50)
        if refs:
            out = [r for r in out if any(str(refs) in str(x) for x in (r.get("refs") or []))]
        return out

    def handoffs_digest(self, *, limit: int = 5) -> str:
        """一小段读数：最近几份交接（判重复时的起点，进提示词用）。"""
        return MS.digest(self.root, limit=limit)

    def wash_dependency_face(self, manuscript: Any, *,
                             statement_rows: Any = None) -> dict[str, Any]:
        """F 的秘书那一遍洗稿：只洗依赖面（命题号 / 那一节的格式），不改证明正文。

        业主 2026-10-26 晚的原话（逐字）：「F写证明时务必加依赖面命题号，且由F的秘书对
        无引用证明忘加空依赖面的补空，对有引用证明的命题号核实（即秘书帮它洗一遍）」
        「F的秘书工作的时候是F写好了，提交证明给V前」「秘书若核出问题，要提前打回并说明」。

        所以这一笔的位置是"F 写完、提交给 V 之前"（`agent_f/core.py` 的 proof 分支在
        `_proof_outlet` 之前调它）：洗过的那一份才是提交给 V、被 D 携带、被 B 读的稿。
        打回时这一轮不提交（不花 V 的那一次调用），`deps_refused_findings` 逐条给
        F 看：哪一行、引用原话、写的是哪个号、应该是什么、为什么、怎么改。

        实现全在 `depsection.wash_dependency_section`（解析与渲染的唯一实现也在那里）；
        本方法只负责两件事：读 `statements`（核实命题号要它），以及把"没 store / 读不到"
        如实折成 `checked=False` —— 不许把"没核成"当成"核过了"。
        """
        from . import depsection as _DS

        out: dict[str, Any] = {
            "checked": False, "washed": False, "text": str(manuscript or ""),
            "deps_section_filled": "", "deps_washing": [], "deps_refused": "",
            "deps_refused_findings": [], "reason": "",
            "actor": f"secretary-{self.role}", "rows": [], "section": {},
        }
        if self.store is None:
            out["reason"] = ("这一名秘书没有 store ⇒ 读不到 `statements`，命题号核不了"
                             "（不洗、也不假装洗过）：这一份先别提交给 V")
            return out
        rows = statement_rows
        if rows is None:
            try:
                rows = [dict(r) for r in self.store.rows("statements")]
            except Exception as exc:  # noqa: BLE001 —— 读不到就不许放行
                out["reason"] = (f"`statements` 读不出来（{type(exc).__name__}: {exc}）⇒ "
                                 "这一遍没核成（没核成不等于没问题）：这一份先别提交给 V")
                return out
        got = _DS.wash_dependency_section(str(manuscript or ""), statement_rows=rows)
        out.update(dict(got or {}))
        out["checked"] = True
        out["actor"] = f"secretary-{self.role}"
        return out

    def extract_manuscript(self, rel: Any, cells: Iterable[str]) -> dict[str, Any]:
        """从一份稿里按调用方指定的格读出来（纯读；不写盘、不写台账、不判签）。

        ## 为什么在秘书层（T1，设计 `_design_T123.md` §2.1 / §2.8）

        业主的形态是「自动录入是 B 秘书的一个工具，需 B 秘书指定录入位置和录入格后，
        从稿中提取内容录入」。于是"从稿里取内容"归秘书：B 本体只把位置 + 格传下来，
        不自己切节、不自己解析表格、不自己读稿头。真正的逐格解析在
        `manuscriptintake.extract_cells`（纯函数、零 I/O），本方法只做三件这一层才有的事：
        读盘、判族/目录、把稿头那几格一并读出来。

        ## 返回（键固定）

        `{checked, path, family, tier, manuscript_id, proof_no, name_proof_no,
        canonical, head_experiment_id,
        head_statement_text, head_label, declared_kind, sha256, proof_sha256,
        proof_state, cells, why, error}`。

        稿头不再有「证明号」那一格可读（产出侧废掉了 `pN`；路径号由收录事务分配），
        所以返回里没有 `head_proof_no` —— 「第几份」唯一来源是秘书在锁里分出来的号。

        - `cells` 是 `extract_cells` 的原样读数（每格 `present / absent / unreadable`）；
        - `proof_state` 是 `## 证明` 那一节的三态（缺节 ≠ 空节）；
        - `sha256` 是整份稿的字节 sha，`proof_sha256` 是 `## 证明` 正文的 sha
          （与签的对拍尺同一把：`proofregistry.proof_sha`）。

        ## 三态（不折平）

        读不到盘 / 不是文本 ⇒ `checked=False` + `why`（这是"没读到"，不是"稿里没有"）；
        路径不在手稿族（`legacy` / `bad_name` / `unrecognized`）照样给出 `cells`
        —— `preview` 要能看清历史档里有什么；能不能收录由调用方按 `tier` 拒，
        本方法不替它做那个决定。
        """
        from . import depsection as _DS
        from . import manuscriptfamily as _MFAM
        from . import manuscriptintake as _MI
        from . import proofregistry as _PR

        path = str(rel or "").strip().replace("\\", "/")
        shape = _MFAM.classify_manuscript(path)
        out: dict[str, Any] = {
            "checked": False, "path": path,
            "family": str(shape.get("family") or ""),
            "tier": str(shape.get("tier") or ""),
            "manuscript_id": str(shape.get("manuscript_id") or ""),
            "proof_no": int(shape.get("proof_no") or 0),
            "name_proof_no": int(shape.get("proof_no") or 0),
            "canonical": str(shape.get("canonical") or ""),
            "head_experiment_id": "", "head_statement_text": "",
            "head_label": "", "declared_kind": "",
            "sha256": "", "proof_sha256": "",
            "proof_state": _MI.EXTRACT_UNREADABLE,
            "cells": {}, "why": "", "error": {},
        }
        if not path:
            out.update(why="没有给手稿路径 ⇒ 没有可读的稿（不是「稿里没有这一节」）")
            return out
        try:
            text = (self.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out.update(why=f"读不到 `{path}`（{type(exc).__name__}: {exc}）",
                       error={"type": type(exc).__name__, "message": str(exc)})
            return out
        out["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        family = str(shape.get("family") or _MFAM.LEGACY_FAMILY)
        try:
            readings = _MI.extract_cells(text, family, list(cells))
        except ValueError as exc:
            out.update(why=f"这一笔要读的格不合法（{exc}）⇒ 一格都没读")
            return out
        out["cells"] = readings
        proof = readings.get("proof_text") or {}
        out["proof_state"] = str(proof.get("outcome") or _MI.EXTRACT_ABSENT)
        out["proof_sha256"] = str((proof.get("source") or {}).get("sha") or "")
        head = _manuscript_head_fields(text)
        out["head_experiment_id"] = str(head.get("实验号") or "").strip()
        out["head_statement_text"] = str(head.get("命题键") or "").strip()
        try:
            entry = dict(_PR.parse_entry(text) or {})
        except Exception:  # noqa: BLE001 —— 稿头读不出来就是没有登记元信息（不猜）
            entry = {}
        out["head_label"] = str(entry.get("label") or "").strip()
        from . import manuscriptkind as _MK

        declared = str(
            entry.get("kind")
            or head.get(_MK.mark_key(_MK.PROPOSITION_KIND_MARK))
            or head.get(_MK.mark_key(_MK.LEGACY_PROPOSITION_KIND_MARK))
            or "").strip().lower()
        out["declared_kind"] = declared if declared in PROPOSITION_KINDS else ""
        out["checked"] = True
        return out

    def record_manuscript_dependency_face(self, stmt_id: str, groups: Any, *,
                                          proof_no: int = 1,
                                          path_group: int = 0,
                                          note: str = "",
                                          manuscript: str = "",
                                          body_sha: str = "",
                                          reserve: bool = False,
                                          proof_text: str = "") -> dict[str, Any]:
        """收方读稿登记：把一份手稿的依赖段落成那条在册命题的 `dependencies` 行。

        ## 为什么需要这一格（业主 2026-10-26 晚：「D 到 B 没有路吗？加」）

        F 交稿时那一行是 F 自己落的（`_proof_outlet`），于是"这条命题的依赖面"
        从来没有第二个写者：D 只能派 B，不能把稿递给 B；B 那一笔登记也只会发生在
        "新建一条命题"的时候 —— 同一条命题再交一次就走 `duplicate` 早退，
        `dependencies` 一行都不落。这条通道补的正是那一格：命题行不动，只把
        手稿里那一节 `## 依赖` 的表格落成依赖边（B 是收方、秘书是写者）。

        ## 路径号（业主口径：归秘书，在这一笔事务里分配）
        `groups` 里那几格路径号是产出侧 / 调用方给的，一律不采信：这一笔的号由
        :func:`_assign_path_group_in_tx` 在同一把锁里分（同一命题已有 N 条 ⇒ N+1；
        同一份正文 sha / 同一份稿重复携带 ⇒ 沿用原号）。回执的 `path_group` 是这一笔
        用的号，`path_group_reading` 是分配函数的原样读数。`proof_no` 参数只为兼容
        旧调用面保留，一个字节都不参与定号（给了就在 `path_group_ignored` 里点名）。

        ## 两件事一起保证
        - 幂等：同一 `used_by` + 路径组 + 来源已经有一条依赖 ⇒ 不重复落（D 每趟都
          会携带一遍，重复落会让依赖表虚高）；读数里 `duplicates` 逐条说"哪几条已经在了"；
        - 判据不另写：解析在 `depsection`、来源在册/档位在 `B.register_statement`
          那一侧（它先把 `manuscript` 与 `gate_rows` 跑完才到这里），本方法只负责
          "把已经核过的步骤写进表"（`_resolve_write_steps` + `_write_dep_steps`）。
        """
        out: dict[str, Any] = {"checked": False, "stmt_id": str(stmt_id or ""),
                               "deps_written": 0, "path_groups": 0, "duplicates": [],
                               "refused": "", "reason": "", "tables": [],
                               "deps_dangling": [], "deps_unmappable": []}
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason="这一名秘书没有 store ⇒ 依赖面写不了")
            return out
        sid = str(stmt_id or "").strip()
        if not sid:
            out.update(refused="bad_statement_id", reason="没有命题号 ⇒ 依赖面挂不到任何一行")
            return out
        groups = [list(g) for g in (groups or []) if isinstance(g, (list, tuple))]
        if not groups and not reserve:
            out.update(checked=True, reason="这一份手稿的依赖段是空的（自足证明合法，不写边）")
            return out
        if not groups and reserve:
            # 只分号 / 只核对号、不写边（实现在 `_reserve_path_only`）。
            return self._reserve_path_only(
                sid=sid, note=note, manuscript=manuscript,
                body_sha=body_sha, path_group=path_group)
        _named_group = int(path_group or 0)
        # 优化线是"换已存在那条路径的正文"，不是新路径 ⇒ 不问同种证明那一问
        # （那一问决定的是"要不要新开一条路径"；拿它拦改写会把优化线堵死）。
        _gate = ({} if _named_group >= 1
                 else self._manuscript_dependency_refusal(sid=sid, proof_text=proof_text))
        if _gate:
            out.update(_gate)
            return out
        try:
            with self.store.tx("statements", "dependencies",
                               actor=f"secretary-{self.role}",
                               note=note or "record_manuscript_dependency_face") as tx:
                # 按号定位走查口（口径一）；事务快照传 `rows=`，锁内读失败仍照旧抛出。
                if not SL.by_id(rows=tx.rows("statements"), stmt_id=sid)["found"]:
                    out.update(refused="statement_missing",
                               reason=(f"台账里没有 stmt:{sid} ⇒ 依赖面挂不到任何一行"
                                       "（收方读稿登记的是在册命题的依赖面）"))
                    return out
                # ---- 路径号：这一笔的依赖面属于「第几条证明」，由秘书在锁里分 ----
                #
                # 只有在调用方给了这一份稿的身份（`manuscript` / `body_sha`）时才分号：
                # 没有身份就无法认"同一份正文已经在第几条路径上"，硬分号会把同一份稿的
                # 第二遍携带记成新路径（D3 的幂等就是这条）。没有身份 ⇒ 按材料给的号落
                # （老调用面 / 夹具的既定口径）。
                # 只请求依赖格（没读证明正文）时 `body_sha` 是空的 ⇒ 用这一行在册的
                # 正文补上：这一笔收的就是它那一份稿，不许因此另开一条路径。
                if not str(body_sha or "").strip():
                    from . import verifications as _VR_canon

                    _canon_row = SL.by_id(rows=tx.rows("statements"), stmt_id=sid)["row"]
                    _canon_text = str((_canon_row or {}).get("proof_text") or "")
                    if _canon_text.strip():
                        body_sha = _VR_canon.text_sha(_canon_text)
                _has_identity = bool(str(body_sha or "").strip()
                                     or str(manuscript or "").strip())
                if _named_group >= 1:
                    # 优化线：号不分配，只核对"第 n 条路径确实存在且对得上这一份稿"。
                    if not _has_identity:
                        out.update(refused="bad_path_identity",
                                   reason=("优化线要给已存在的路径号，也要给这一份稿的身份"
                                           "（`manuscript` / `body_sha`）：没有身份就核不了"
                                           "它是不是那条路径的稿"))
                        return out
                    _alloc = _existing_path_group_in_tx(
                        tx, root=self.root, statement_id=sid,
                        path_group=_named_group, manuscript=manuscript,
                        body_sha=body_sha)
                    if _alloc.get("refused"):
                        out.update(refused=str(_alloc.get("refused") or "path_group_refused"),
                                   reason=str(_alloc.get("reason") or ""))
                        return out
                    if not _alloc.get("checked"):
                        out.update(refused="path_group_unreadable",
                                   reason=("路径数读不出来 ⇒ 这一份的依赖面不落（不猜第几条）："
                                           + str(_alloc.get("why") or "未知原因")))
                        return out
                    group_no = int(_alloc.get("path_group") or _named_group)
                    _note_path_material(out, _path_material_numbers(groups),
                                        decided=group_no)
                    out["path_group"] = group_no
                    out["path_group_reading"] = dict(_alloc)
                elif _has_identity:
                    _alloc = _assign_path_group_in_tx(
                        tx, root=self.root, statement_id=sid,
                        manuscript=manuscript, body_sha=body_sha)
                    if not _alloc.get("checked"):
                        out.update(refused="path_group_unreadable",
                                   reason=("路径数读不出来 ⇒ 这一份的依赖面不落（不猜第几条）："
                                           + str(_alloc.get("why") or "未知原因")))
                        return out
                    group_no = int(_alloc.get("path_group") or 1)
                    # 材料（手稿依赖表第 4 列）与秘书定的号不一致 ⇒ 点名；号以秘书为准。
                    _note_path_material(out, _path_material_numbers(groups),
                                        decided=group_no)
                    out["path_group"] = group_no
                    out["path_group_reading"] = dict(_alloc)
                else:
                    group_no = int(proof_no or 1)
                    out["path_group"] = group_no
                    out["path_group_reading"] = {
                        "checked": False, "path_group": group_no,
                        "why": ("没有稿身份（`manuscript` / `body_sha` 都没给）"
                                "⇒ 按材料给的号落，不去认第几条")}
                if int(proof_no or 0) >= 1 and int(proof_no or 0) != group_no:
                    out["path_group_ignored"] = {
                        "given": int(proof_no), "by": "调用方",
                        "why": ("证明号 / 路径号由秘书在收录事务里分配"
                                "（`assign_path_group`）⇒ 调用方给的这个数不采信"),
                    }
                # ---- 「难以自证」的空号 ⇒ 整条替换（业主 2026-11-13 裁定）------------
                #
                # 位置在"号已经定下来、依赖边还没写"这一刻：替换要换的四样东西必须
                # 同一笔落，而号必须还是刚才在锁里分出来的那一个。返回 False ⇒ 这
                # 一行没有空号（照旧走下面的"追加 + 去重"那一路，行为逐字不变）。
                if self._fill_vacant_path_if_any(
                        tx, sid=sid, proof_text=proof_text, groups=groups,
                        out=out, manuscript=manuscript, group=group_no):
                    return out
                body = {"deps": groups, "proof_no": group_no}
                steps = self._resolve_write_steps(tx, body, out, groups)
                if steps is None:
                    return out
                # 号盖在已解析的步骤上：手稿依赖段那一路 `used_by` 尾巴与
                # `path_group` 同号（一份稿 = 一份证明 = 一条路径）。没有稿身份时
                # 不盖 —— 材料自己那几格就是这一笔要落的口径（幂等靠它们）。
                if _has_identity:
                    steps = _stamp_path_number(steps, path_group=group_no,
                                               proof_no=group_no)
                existing = set()
                for row in tx.rows("dependencies"):
                    existing.add(_dep_step_key(dict(row)))
                keep: list[dict[str, Any]] = []
                for step in steps:
                    key = _dep_step_key({
                        "used_by": _PL.used_by_of(
                            f"stmt:{sid}", int(step.get("proof_no") or group_no)),
                        "path_group": int(step.get("path_group") or group_no),
                        "kind": str(step.get("kind") or "theorem"),
                        "source_stmt_id": step.get("source_stmt_id"),
                        "source_lit_id": step.get("source_lit_id"),
                        "source_experiment_id": step.get("source_experiment_id"),
                        "source_doc_id": step.get("source_doc_id"),
                        "label": str(step.get("label") or ""),
                    })
                    if key in existing:
                        out["duplicates"].append({
                            "path_group": int(step.get("path_group") or group_no),
                            "label": str(step.get("label") or ""),
                            "why": "这一条依赖已经在表里（同一路径组、同一来源）⇒ 不重复落"})
                        continue
                    keep.append(step)
                if not keep:
                    out.update(checked=True, path_groups=len(groups),
                               reason="这一份手稿的依赖边都已经在表里（幂等：一条都没重复落）")
                    return out
                written = self._write_dep_steps(tx, keep, stmt_id=sid, body=body)
                out.update(checked=True, deps_written=int(written),
                           #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                           deps_stmt_edges=_stmt_edge_count(keep),
                           path_groups=len(groups), tables=["dependencies"])
        except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
            out.update(checked=False, refused="write_failed",
                       reason=f"依赖面落盘没成（{type(exc).__name__}: {exc}）⇒ 这一笔按'没写成'读")
        return out

    def _reserve_path_only(self, *, sid: str, note: str, manuscript: str,
                           body_sha: str, path_group: int) -> dict[str, Any]:
        """`record_manuscript_dependency_face` 的"只分号 / 只核对号"那一支（不写边）。

        `path_group=0` ⇒ 由秘书在锁里分配"第几条"（另一条路径 / canonical）；
        `path_group>=1` ⇒ 优化线：只核对这个号已存在且对得上这一份稿（不分配）。
        一个字节的依赖行都不写；号只进回执，后面的正文写口用它。
        """
        out: dict[str, Any] = {"checked": False, "stmt_id": sid, "deps_written": 0,
                               "path_groups": 0, "duplicates": [], "refused": "",
                               "reason": "", "tables": [], "deps_dangling": [],
                               "deps_unmappable": []}
        try:
            with self.store.tx("statements", "dependencies",
                               actor=f"secretary-{self.role}",
                               note=note or "record_manuscript_dependency_face:reserve") as tx:
                if not SL.by_id(rows=tx.rows("statements"), stmt_id=sid)["found"]:
                    out.update(refused="statement_missing",
                               reason=(f"台账里没有 stmt:{sid} ⇒ 路径号分不了"))
                    return out
                _named = int(path_group or 0)
                if _named >= 1:
                    _alloc = _existing_path_group_in_tx(
                        tx, root=self.root, statement_id=sid, path_group=_named,
                        manuscript=manuscript, body_sha=body_sha)
                else:
                    _alloc = _assign_path_group_in_tx(
                        tx, root=self.root, statement_id=sid,
                        manuscript=manuscript, body_sha=body_sha)
                if _alloc.get("refused"):
                    out.update(refused=str(_alloc.get("refused") or "path_group_refused"),
                               reason=str(_alloc.get("reason") or ""))
                    return out
                if not _alloc.get("checked"):
                    out.update(refused="path_group_unreadable",
                               reason=("路径数读不出来 ⇒ 这一笔不写（不猜第几条）："
                                       + str(_alloc.get("why") or "未知原因")))
                    return out
                out.update(checked=True, deps_written=0, path_groups=0,
                           path_group=int(_alloc.get("path_group") or _named or 1),
                           path_group_reading=dict(_alloc),
                           reason=(("这一笔没有请求依赖格 ⇒ 只核对已存在的路径号（不写边）"
                                    if _named else
                                    "这一笔没有请求依赖格 ⇒ 只分配路径号（不写边）")))
        except Exception as exc:  # noqa: BLE001 —— 分号失败必须回三态，不许半笔
            out.update(checked=False, refused="write_failed",
                       reason=(f"路径号没分成（{type(exc).__name__}: {exc}）"
                               " ⇒ 这一笔按'没写成'读"))
        return out

    def _manuscript_dependency_refusal(self, *, sid: str, proof_text: str) -> dict[str, Any]:
        """同种证明那一问（事务外先问，锁内只落）：same / 判不了 ⇒ 拒收读数。

        只在"这一份正文是新的"时问：同一份正文（sha 已在册）是幂等重交，不是另一套
        证法。判 same ⇒ 点名第 N 条路径；判不了 ⇒ fail-closed；different ⇒ 空字典
        （调用方继续分号、写边）。这是 apply 那条入口的分配点（仍是秘书的唯一实现）。
        """
        if not str(proof_text or "").strip():
            return {}
        from . import verifications as _VRkind

        got_row = SL.by_id(self.store, stmt_id=sid)
        if not (got_row.get("checked") and got_row.get("found")):
            return {}
        row_now = dict(got_row.get("row") or {})
        _known = {_VRkind.text_sha(str(t)) for _n, t in
                  _VRkind.proof_list(row_now) if str(t or "").strip()}
        if _VRkind.text_sha(str(proof_text)) in _known:
            return {}
        _kind = self._same_kind_hits(row_now, str(proof_text))
        _sim = float(_kind.get("similarity") or 0.0)
        if not _kind.get("checked"):
            return {"checked": False, "refused": PROOF_KIND_UNJUDGED,
                    "vacant_reading": dict(_kind.get("vacant_reading") or {}),
                    "reason": ("这一份证明与在册各路径是不是同种没判成"
                               "（没判成 ≠ 不同）⇒ 不收录、不新增路径："
                               + str(_kind.get("reason") or "判定面没给可用结论"))}
        if str(_kind.get("decision") or "") != "same":
            return {}
        _n = int(_kind.get("same_path") or 1)
        #: 三态读数进拒信：读不出来时要点名"没把任何一条当空号"（fail-closed 的样子
        #: 必须看得见 —— 否则"读不出来"与"查过了、没有空号"在回执里长得一样）。
        _vac = dict(_kind.get("vacant_reading") or {})
        _vac_note = ""
        if not _vac.get("checked"):
            _vac_note = ("（`bits.evidence.hard_to_prove_by_proof` 那一格读不出来 ⇒ "
                         "不把任何一条路径当空号，按普通「已有证明」处置："
                         + str(_vac.get("why") or "未知原因") + "）")
        return {"checked": False, "refused": PROOF_SAME_KIND,
                "same_kind_material": {"similarity": _sim},
                #: 空号那一格的三态读数（这一笔判成"同种"时它一定是"没有空号"或
                #: "读不出来"：读得出来且记着难以自证的路径根本不会进比较）。
                "vacant_reading": _vac,
                "reason": (f"这一份证明与 stmt:{sid} 的第 {_n} 条路径同种"
                           "（秘书的语义判定：两套证法是同一路，不是两条独立路径）"
                           "⇒ 不收录、不新增路径。材料读数（只作参考）：相似度 "
                           f"{_sim:.4f}。处置：换一条真正不同的证法再交，或本次不再提交"
                           + _vac_note)}


#: 稿头元信息行：`- <键>：<值>`（与 `manuscriptintake._HEAD_FIELD_RE` 同一形状）。
_MANUSCRIPT_HEAD_FIELD_RE = re.compile(r"^\s*-\s*(?P<key>[^：:]+?)\s*[：:]\s*(?P<value>.*?)\s*$")


def _manuscript_head_fields(text: Any) -> dict[str, str]:
    """稿头（第一个 `##` 之前）的 `- 键：值` ⇒ `{键: 值}`（只读；不猜、不去重语义）。

    为什么放在秘书层：`extract_manuscript` 要把稿头那几格（实验号 / 命题键 /
    命题类型）一并带给调用方，而"B 本体不自己读稿"这条边界不许在这里破例 —— 所以
    切稿头的实现只有这一处，键名的解释由调用方按用途读。
    """
    out: dict[str, str] = {}
    for line in str(text or "").split("\n"):
        if line.strip().startswith("##"):
            break
        matched = _MANUSCRIPT_HEAD_FIELD_RE.match(line)
        if not matched:
            continue
        key = matched.group("key").strip()
        if key and key not in out:
            out[key] = matched.group("value").strip()
    return out
