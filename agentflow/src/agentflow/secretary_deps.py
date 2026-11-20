# -*- coding: utf-8 -*-
"""秘书的依赖面（不少一环，从 secretary.py 的 U23 逐字搬出）。

我保证哪条不变式：依赖少一环不许静默；路径号只在锁内分配（先分配再判断，等于给一条不存在的路发号）。

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

from . import proofloc as _PL
from . import schema as S
from . import statementledger as SL
from typing import Mapping

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    STATEMENT_WRITE_TABLES,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    DEPS_MISSING_ABSENT,
    DEPS_MISSING_NOT_APPLICABLE,
    DEPS_MISSING_PRESENT,
)

from .secretary_wash import (  # noqa: F401 — 这些名字由 secretary_wash 定义
    STEP_SOURCE_KEYS,
    _dep_label,
    _dep_ref,
    _stmt_edge_count,
)


class DepsMixin:
    """依赖面（不少一环）（从 secretary.py 搬出的混入类）。"""

    #: 扫出来的引用前缀 ⇒ `(STEP_SOURCE_KEYS` 里那一步的键名, `kind` 缺省)。
    #: 键名而不是来源字段名：`_resolve_dep_steps` 读的是 `st.get(key)`
    #: （`lit_id` / `stmt_id` / `experiment_id` / `doc_id`），来源字段名是它再翻译过去的。
    #:
    #: `rel` / `eval` 刻意不在表里：`Dependency` 的"四选一"（`STEP_SOURCE_KEYS`）
    #: 里没有指向关系表/评测表的格子 ⇒ 它们进 `deps_unmappable` 读数并点名，
    #: 不许静默丢（丢掉一条引用 = 依赖图静默少一环，而那正是 FC-23 那个病的成因）。
    _SCAN_SOURCE: dict[str, tuple[str, str]] = {
        "stmt": ("stmt_id", "theorem"),
        "exp": ("experiment_id", "experiment"),
        "lit": ("lit_id", "theorem"),
        "doc": ("doc_id", "theorem"),
    }

    def _scan_proof_deps(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """从"定理内容 + 证明过程"里扫出依赖（B 只交这两样）。

        ## 路径分组（`Dependency.path_group`）：载荷给了显式的 `proof_paths`（多段可选证明，B 自己分的段）⇒
        每段一组，下标从 1 起（组内 AND / 组间 OR）；载荷给了 `proofs`（多证明清单）
        ⇒ 一份证明一组，组下标就是它在清单里的位次，并且这一组的每一步都带上它的
        `proof_no`（于是 `used_by` 落成 `stmt:<号>#pN`，第 2 份及以后的依赖面不再与 #p1 混在一起）。
        两样都没给 ⇒ 把 `statement_full` + `proof_text` 当一段（全归第 1 组）—— 刻意"不猜"：
        不按空行、不按"证明一/证明二"这种字样去猜 B 想分几段。
        ## 三态（`state`）：
        | 取值 | 什么时候 | 为什么必须分开 |
        |---|---|---|
        | `from_proof` | 扫到了至少一条在册引用 | 这是"扫到了" |
        | `none_in_proof` | 证明过程给了（键在）、一条引用也没有 | 这是"扫了、确实是空的" |
        | `unknown` | 证明过程这一格根本没给、也没扫到引用 | 这是"没扫成" —— 与"空"折平就等于把"B 没交证明过程"读成"这条定理不依赖任何东西" |
        扫的范围是定理内容 + 证明过程两张脸（"证明过程/定理内容里出现的引用"），去重按 `(前缀, 代号)`
        （`lit:0003#p.4` 与 `lit:0003` 是同一条）。
        """
        from . import textutil as T   # 惰性：引用扫描的唯一实现

        raw_paths = body.get("proof_paths")
        #: 一条路径 = `(proof_no, 要扫的正文)`；`proof_no=0` 表示"这一笔没说它是第几份证明"，
        #: 于是 `_write_dep_steps` 照旧按 `body["proof_no"]`（缺省 canonical）落 `used_by`。
        #:
        #: 多证明清单排在 `proof_paths` 之前：`proofs` 是"这条定理有几份证明"的声明面，
        #: 而 `proof_paths` 是"某一份证明里有几条可选路径"的声明面 —— 两者都给时，
        #: 一份证明一组比"整份证明被切成几段"更不容易把依赖挂错证明号。
        proof_plan = self._proof_dep_plan(body)
        #: 单段扫描的路径号（2026-11-11 收尾批）：B 逐份 inline 登记时把分配出来的
        #: 路径号放在 `body["path_group"]` 里（② 那一支也调 `assign_path_group`），
        #: 这一档没有 `proofs` / `proof_paths` 可分组 ⇒ 段落下标恒为 1，只能用这个号。
        #: 没有这一格 ⇒ 0（老路逐字不变：按段落下标，第 1 组 = 1）。
        _single_group = 0
        if proof_plan:
            paths = [text for _no, text in proof_plan]
        elif isinstance(raw_paths, (list, tuple)) and raw_paths:
            proof_plan = [(0, str(p or "")) for p in raw_paths]
            paths = [text for _no, text in proof_plan]
        else:
            try:
                _single_group = int(body.get("path_group") or 0)
            except (TypeError, ValueError):
                _single_group = 0
            proof_plan = [(0, str(body.get("statement_full") or "") + "\n"
                           + str(body.get("proof_text") or ""))]
            paths = [text for _no, text in proof_plan]
        groups: list[list[dict[str, Any]]] = []
        unmappable: list[dict[str, str]] = []
        seen_unmappable: set[str] = set()
        found = 0
        for gi, (plan_no, text) in enumerate(proof_plan, 1):
            steps: list[dict[str, Any]] = []
            for ref in T.find_citations(text):
                found += 1
                mapping = self._SCAN_SOURCE.get(ref["prefix"])
                if mapping is None:
                    # 在册、但没有承载格（`rel:` / `eval:`）⇒ 点名，不静默丢
                    if ref["raw"] not in seen_unmappable:
                        seen_unmappable.add(ref["raw"])
                        unmappable.append({
                            "ref": ref["raw"], "table": ref["table"],
                            "why": (f"`{ref['prefix']}:` 在册（指向 {ref['table']}），但 "
                                    "`Dependency` 没有指向这张表的来源格 ⇒ 这条引用落不进依赖边，"
                                    "列在这里点名（不许静默丢）")})
                    continue
                field, dep_kind = mapping
                #: 路径组：多证明清单那一档里"一份证明 = 一条可选路径"，于是组号就是
                #: 证明号（第 2 份证明的依赖落在 `path_group=2`）；老写法（没有 `proofs`）
                #: 仍按段落下标，`proof_paths` 的第 N 段就是第 N 组 —— 老读数逐字不变。
                #: 单段而 B 分配了路径号（`body["path_group"]`）⇒ 用那个号（② 的那一支）。
                group_no = int(plan_no) if plan_no >= 1 else (
                    int(_single_group) if int(_single_group) >= 1 else gi)
                step = {"kind": dep_kind, "label": ref["raw"], "code": ref["code"],
                        "table": ref["table"], field: ref["code"], "path_group": group_no,
                        "_from": "proof_scan"}
                if plan_no >= 1:
                    # 这一组属于第几份证明：`_write_dep_steps` 据此落
                    # `used_by="stmt:<号>#pN"`（第 1 份不加尾巴，老写法逐字不变）。
                    step["proof_no"] = int(plan_no)
                steps.append(step)
            if steps:
                groups.append(steps)
        if found:
            state = "from_proof"
        elif "proof_text" in body or body.get("proofs"):
            state = "none_in_proof"
        else:
            state = "unknown"
        return {"state": state, "groups": groups, "unmappable": unmappable,
                "paths": len(paths), "refs": found}

    @staticmethod
    def _proof_dep_plan(body: Mapping[str, Any]) -> list[tuple[int, str]]:
        """多证明载荷 ⇒ "一份证明一组"的扫描计划（`[(proof_no, 正文)]`，按证明号升序）。

        为什么要这一格：第 2 份及以后的证明正文原先根本不进扫描（`_scan_proof_deps` 只看
        `statement_full` + `proof_text`），于是 `proofs=[#p1,#p2,#p3]` 交上去之后
        依赖面只有 #p1 那一条 —— 第 2、3 份证明引用的东西静默不进依赖图，
        而 `used_by="stmt:#pN"` 也就一次都没被写出来过（真机 sylow3 正是这个读数：
        `proof_no` 全 1、依赖 0 行）。

        三态：
        - 载荷没有 `proofs`（或不是列表 / 空）⇒ 空列表 = "这一笔不是多证明"，
          调用方照老路把整份 `statement_full + proof_text` 当一段（老读数逐字不变）；
        - `proofs` 里有条目而 `proof_text` 非空 ⇒ #p1 用 `proof_text` 的正文
          （它是 canonical 的唯一权威），其余按清单里的号与正文；
        - 条目认不出证明号 / 正文为空 ⇒ 跳过那一条（不猜它是第几份；`B.register_statement`
          的预检已经会整笔拒收，这里只是不让脏载荷把扫描带崩）。
        """
        raw = body.get("proofs")
        if not isinstance(raw, (list, tuple)) or not raw:
            return []
        plan: dict[int, str] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            try:
                no = int(item.get("proof_no") or 0)
            except (TypeError, ValueError):
                continue
            text = str(item.get("text") or item.get("proof_text") or "")
            if no < 1 or not text.strip():
                continue
            plan[no] = text
        if not plan:
            return []
        canon = str(body.get("proof_text") or "")
        if canon.strip():
            plan[1] = canon
        return [(no, plan[no]) for no in sorted(plan)]

    def _resolve_write_steps(self, tx: Any, body: Mapping[str, Any],
                             out: dict[str, Any], groups: list[list[dict[str, Any]]]
                             ) -> list[dict[str, Any]] | None:
        """把依赖组解析成可落盘的步骤；判不了就返回 `None`（调用方据此整笔不写）。

        从 :meth:`_record_statement_tx` 里拆出来是因为有两个调用点：
        "新建一条命题"与"并进已有命题的第 N 份证明"。两处必须用同一套判据 ——
        各写一份的形态是"两条路径对同一条悬空依赖给出两种处置"，而那种漂移没有
        任何读数会响（与 `_resolve_dep_steps` 的注释同一条理由）。

        ## 命题这一档：不可引 ⇒ 受控拒

        正文里点一个不可引的号（不在册 / 等级 < `pre_theorem`）不是"待接的
        悬空边"：「F 应该无法读到尚未在册的命题」「F 只可引用准定理级及以上的命题」
        ⇒ F 读不到它，不可能在引用它，所以这种正文只可能是这一笔写错了。
        判据与 F 的可引池、B 的登记入口同源（`depsection.citable_pool` /
        `uncitable_statement_problem`）；拒信逐字点名那个号。

        三态：`None` = 拒（命题不可引 / 显式给的依赖指着不在册的号）；列表 = 可写
        （"非命题"来源的悬空边落 `dangling` 并点名，扫不动的进 `deps_unmappable`）。

        ## 仍然保留 dangling 的只有"非命题来源"这一档

        文献 / 实验 / 文档这三种来源的号不在册时，边照旧落 `dangling` 并点名：
        它们不是"F 读不到的命题"，那条口径没有覆盖它们；把它们
        也改成整笔拒会顺手改掉 G 契约里那一档（`body["deps"]` 直给的那条路本来
        就更严：它整笔不写）。命题来源不走这条 —— 它在上面的 `blocked` 那一支就拒了。
        """
        steps, missing = _resolve_dep_steps(groups, tx)
        #: 可引判据的唯一定义在 `depsection`（与 F 的提示词清单、B 的登记入口同源）。
        from . import depsection as _DS
        try:
            ledger = [dict(r) for r in tx.rows("statements")]
        except Exception:  # noqa: BLE001 —— 读不到台账就不许判"可引"
            out.update(refused=str(_DS.REFUSED_LEVEL_UNREADABLE),
                       reason=("依赖的这一批来源要判可引，而 `statements` 读不出来 ⇒ "
                               "整笔不写：读不到台账就不许把一条引不成的号记成依赖"))
            return None
        blocked: list[dict[str, Any]] = []
        for stp in steps:
            sid = str(stp.get("source_stmt_id") or "").strip()
            if not sid:
                continue
            _code, _why = _DS.uncitable_statement_problem(
                sid, ledger, where="依赖步骤里")
            if _code:
                blocked.append({"path_group": int(stp.get("path_group") or 1),
                                "step": dict(stp), "code": _code, "why": _why})
        for m in missing:
            _stp = dict(m.get("step") or {})
            _sid = str(_stp.get("stmt_id") or "").strip()
            if not _sid or "表里没有" not in str(m.get("why") or ""):
                continue
            _code, _why = _DS.uncitable_statement_problem(
                _sid, ledger, where="依赖步骤里")
            if _code:
                blocked.append(dict(m, code=_code, why=_why))
        if blocked:
            first = blocked[0]
            out.update(refused=str(first.get("code") or ""),
                       reason=str(first.get("why") or ""),
                       unresolved=blocked)
            return None
        if missing and body.get("deps"):
            # 显式给的依赖指着不在册的号 ⇒ 整笔不写（G 那一族的契约）
            out.update(refused="unresolved_dependency",
                       reason=("依赖里有一条指着不在册的 id ⇒ 整笔不写（不许留一条挂空号的"
                               "依赖：那正是'依赖图静默少一环'的成因）"),
                       unresolved=missing)
            return None
        if not missing:
            return steps
        # 走到这里的 `missing` 只剩"非命题来源"这一类（文献 / 实验 / 文档的号不在册）：
        # 业主 §14.11 乙 的处置是"那条边落 `dangling` 并在读数里点名，不整笔拒"。
        # 命题这一档不在其中 —— 它在上面 `blocked` 那一支已经受控拒了（2026-11-06）。
        #
        # 两档必须分开（`_resolve_dep_steps` 的 `why` 把它们区分开）：
        # "表里没有这个号" ⇒ 落一条 `dangling` 边；"这一步本身不合法"
        # （来源不是四选一 / kind 不在词表里）⇒ 不落边，但进 `deps_unmappable`
        # 点名 —— 把后者也写成 `dangling` 会造出一条形状就不对的依赖行，
        # 而"写一条坏行"比"少写一条并点名"更坏。
        kept = list(steps)
        for m in missing:
            stp = dict(m.get("step") or {})
            why = str(m.get("why") or "")
            if "表里没有" in why:
                stp["status"] = "dangling"
                # 来源要从键名翻到字段名：`_resolve_dep_steps` 成功那一路
                # 已经翻过了（它返回的 step 带 `source_*`），而走 `missing` 这一路的
                # step 是输入的副本（只有 `stmt_id` 这种键名）⇒ 不翻的话
                # 悬空边会落成"四选一个来源都没有"的行（实测抓到：`source_stmt_id=None`）。
                for _key, _field, _table, _idf, _dkind in STEP_SOURCE_KEYS:
                    if str(stp.get(_key) or "").strip():
                        stp[_field] = str(stp[_key]).strip()
                        break
                # `Dependency.validate` 的硬要求：`status="dangling"` 必须写
                # `status_reason`（"只标状态不说原因 = 记了一笔没人能接手"）。
                stp["status_reason"] = (
                    f"证明文本里引用了 {stp.get('label') or stp.get('code')}，"
                    f"而{why} ⇒ 这条依赖边留着并标 `dangling`（不整笔拒、也不丢掉它："
                    "丢掉等于依赖图静默少一环）；等那一行进库之后由下一次核对闭合")
                kept.append(stp)
                out["deps_dangling"].append(
                    {"ref": _dep_ref(stp),
                     "path_group": int(m.get("path_group") or 1), "why": why})
            else:
                out["deps_unmappable"].append({
                    "ref": str(stp.get("label") or stp.get("code") or ""),
                    "path_group": int(m.get("path_group") or 1),
                    "why": f"扫出来的这一步落不了：{why}"})
        return kept

    def _write_dep_steps(self, tx: Any, steps: Iterable[Mapping[str, Any]], *,
                         stmt_id: str, body: Mapping[str, Any]) -> int:
        """把解析好的步骤写成 `dependencies` 行，返回写了几条。

        多证明模型（业主 2026-10-22）：这条命题的依赖属于它的第几条证明。载荷没写
        ⇒ canonical（第 1 条）⇒ 生成出来的 `used_by` 与改前逐字相同
        （`proofloc.used_by_of` 对第 1 条不写 `#pN` 尾巴）。
        `path_group` 由扫描那一格给：老写法下它是"第几条路径"（`proof_paths` 的段落下标），
        多证明清单下它是"第几份证明"（组内 AND / 组间 OR 的语义不变：几份证明就是几条
        可选的路径）。
        """
        count = 0
        for step in steps:
            dep_id = tx.alloc_id(S.TABLES["dependencies"]["id_kind"])
            # 两个数各管一件事，不许混：
            #   · `proof_no` ⇒ `used_by` 的 `#pN` 尾巴（"这一条依赖出自哪一份证明正文"）
            #   · `path_group` ⇒ 那一列（"同一份证明里的第几条可选路径"，组内 AND / 组间 OR）
            # 手稿依赖段那一路两者同值（`deps_groups` 已赋同样的数）；证明正文里分段扫出来
            # 的那一路，`path_group` 1/2… 而 `proof_no` 仍是 1 —— 那是正常形态，不是错位。
            proof_no = step.get("proof_no") or body.get("proof_no") or _PL.DEFAULT_PROOF_NO
            try:
                proof_no = int(proof_no)
            except (TypeError, ValueError):
                proof_no = _PL.DEFAULT_PROOF_NO
            if proof_no < _PL.DEFAULT_PROOF_NO:
                proof_no = _PL.DEFAULT_PROOF_NO
            group_raw = step.get("path_group")
            try:
                path_group = int(group_raw) if group_raw not in (None, "") else proof_no
            except (TypeError, ValueError):
                path_group = proof_no
            if path_group < _PL.DEFAULT_PROOF_NO:
                path_group = _PL.DEFAULT_PROOF_NO
            dep = S.Dependency(
                dep_id=dep_id,
                used_by=_PL.used_by_of(f"stmt:{stmt_id}", proof_no),
                kind=str(step.get("kind") or "theorem"),
                label=str(step.get("label") or "") or _dep_label(step),
                source_lit_id=step.get("source_lit_id"),
                source_experiment_id=step.get("source_experiment_id"),
                source_stmt_id=step.get("source_stmt_id"),
                source_doc_id=step.get("source_doc_id"),
                quote=str(step.get("quote") or ""),
                status=str(step.get("status") or "closed"),
                # `status != "closed"` 时 `Dependency.validate` 要求非空理由
                # （扫出来的悬空引用在 `_resolve_write_steps` 里已经写好了这一格）。
                status_reason=str(step.get("status_reason") or ""),
                page_range=S.PageRange(),
                path_group=path_group,
                created_at=S.now_iso(), created_by=f"secretary-{self.role}")
            dep.validate()
            tx.upsert("dependencies", dep.to_dict(), note="record_statement:dependency")
            count += 1
        return count

    def record_proof_deps(self, stmt_id: str,
                          entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """把"已经挂到某条命题上的第 N 份证明"的依赖写成 `dependencies` 行。

        ## 为什么需要第二个入口（同一个写入方，同一套判据）
        `record_statement` 只看得见这一笔交上来的 `proof_text`（#p1）。第 2 份及以后的
        证明是 `B.register_statement` 在 `_attach_proofs` 里挂到既有行上的，那一笔只动
        `statements`（B 的写集里没有 `dependencies`）⇒ 那几份证明引用的东西原先一条都
        不进依赖图，`used_by="stmt:#pN"` 因此一次都没被写出来过（真机 sylow3：
        依赖 0 行、`proof_no` 全 1）。这一格是那条路的补写口：判据（扫引用 / 悬空边点名 /
        "四选一"来源）全部复用 `_scan_proof_deps` 与 `_resolve_write_steps`，一行都没有
        另写一份 —— 两条路上"同一条悬空引用怎么处置"必须是同一个答案。

        三态（不进依赖表的两种原因分开）：
        - `checked=True` ＋ `deps_written>0` ⇒ 写成了；
        - `checked=True` ＋ `deps_written=0` ⇒ 扫了，这几份证明确实没有在册引用
          （自足证明合法，读数在 `deps_missing` 里）；
        - `checked=False` ⇒ 没写（没有 store / 依赖指着不在册的号 / 落盘失败），`reason` 说清。
        """
        out: dict[str, Any] = {"checked": False, "stmt_id": str(stmt_id or ""),
                               "deps_written": 0, "path_groups": 0, "proof_nos": [],
                               "deps_dangling": [], "deps_unmappable": [],
                               "deps_missing": {}, "refused": "", "reason": ""}
        proofs = []
        for item in (entries or ()):
            if not isinstance(item, Mapping):
                continue
            try:
                no = int(item.get("proof_no") or 0)
            except (TypeError, ValueError):
                continue
            text = str(item.get("text") or item.get("proof_text") or "")
            if no < 1 or not text.strip():
                continue
            proofs.append({"proof_no": no, "text": text})
        out["proof_nos"] = [int(e["proof_no"]) for e in proofs]
        if not proofs:
            out.update(checked=False,
                       reason="没有可扫的证明正文（第 2 份及以后的证明清单是空的）")
            return out
        if self.store is None:
            out.update(refused="secretary_unavailable",
                       reason="这一名秘书没有 store ⇒ 依赖写不了")
            return out
        body = {"proofs": proofs}
        scan = self._scan_proof_deps(body)
        out["deps_unmappable"] = list(scan["unmappable"])
        out["path_groups"] = len(scan["groups"])
        try:
            with self.store.tx(*STATEMENT_WRITE_TABLES, actor=f"secretary-{self.role}",
                               note="record_proof_deps") as tx:
                if not SL.by_id(rows=tx.rows("statements"),
                                stmt_id=out["stmt_id"])["found"]:
                    out.update(refused="unknown_statement",
                               reason=(f"`statements` 里没有 {out['stmt_id']} ⇒ 这几份证明的"
                                       "依赖没有落点（清单挂不上时也没有行可挂）"))
                    return out
                steps = self._resolve_write_steps(tx, body, out, scan["groups"])
                if steps is None:
                    return out
                out["deps_written"] = self._write_dep_steps(tx, steps, stmt_id=out["stmt_id"],
                                                            body=body)
                #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                out["deps_stmt_edges"] = _stmt_edge_count(steps)
        except Exception as exc:  # noqa: BLE001 —— 落盘失败必须回三态，不许半笔
            out.update(checked=False, refused="write_failed",
                       reason=f"依赖落盘没成（{type(exc).__name__}: {exc}）⇒ 这一笔按'没写成'读")
            return out
        out["checked"] = True
        out["deps_missing"] = _deps_missing_reading(
            proof_text="\n".join(str(e["text"]) for e in proofs),
            deps_written=int(out["deps_written"] or 0),
            stmt_id=out["stmt_id"], proof_no=int(proofs[0]["proof_no"]),
            scan={"refs": int(scan.get("refs") or 0)})
        return out


def _assign_path_group_in_tx(tx: Any, *, root: Any, statement_id: str,
                             manuscript: str = "", body_sha: str = "") -> dict:
    """在事务内分配「第几条证明路径」（业主口径：路径号归 B 的秘书）。

    唯一实现是 :func:`manuscriptpaths.assign_path_group`（同一命题已有 N 条 ⇒ N+1；
    同一份正文 sha / 同一份稿重复收录 ⇒ 沿用）。这里只做两件事：把它接到事务快照
    上（`store=tx` ⇒ 读的是这一笔锁里的 `dependencies`，不是锁外的另一份快照），
    并把读数原样回传。

    为什么必须传 `tx` 而不是 `self.store`：分配与写盘要在同一把锁里。传 store 时
    `path_reading` 读的是 `store.rows(...)`（锁外的缓存快照），两个并发收录会各自
    看到"N 条" ⇒ 都开 N+1（开两个同号路径）。传 `tx` 时读的是本事务的快照，
    且本事务已经持有 `statements` + `dependencies` 的锁。
    """
    from . import manuscriptsubmission as _MSUB

    sid = str(statement_id or "").strip()
    rel = str(manuscript or "").strip().replace("\\", "/")
    if not sid:
        return {"checked": False, "path_group": 1, "existing": False, "count": 0,
                "statement_id": "", "manuscript": rel, "body_sha": str(body_sha or ""),
                "paths": [], "problems": [],
                "why": "没有命题号 ⇒ 路径号分不了（新命题那一档由收录方给号后再分）"}
    got = dict(_MSUB.assign_path_group(
        store=tx, root=root, statement_id=sid, manuscript=rel,
        body_sha=str(body_sha or "")) or {})
    got.setdefault("statement_id", sid)
    got.setdefault("manuscript", rel)
    got.setdefault("body_sha", str(body_sha or ""))
    return got


def _existing_path_group_in_tx(tx: Any, *, root: Any, statement_id: str,
                               path_group: int, manuscript: str = "",
                               body_sha: str = "") -> dict:
    """核对「调用方点名的第 n 条路径」是不是已存在、且对得上这一份稿。

    优化线（业主 2026-11-12：「换正文只允许优化这条线去换。优化线需指明命题号和
    路径。」）显式带 `(命题号, 路径号)`；这一格不分配号，只在事务里核对：
    第 n 条路径不在册 ⇒ `path_not_found`；这一份稿已经绑在别的路径上 ⇒
    `path_mismatch`；对得上才把号回给调用方。号仍归秘书（这里没有分配动作）。

    三态：`checked=False` ⇒ 路径记录读不出来（不是「没有这条路径」）；`refused`
    非空 ⇒ 受控拒、一个字节都不写；`basis` 说明这一份稿是靠什么对上的
    （`path_manuscript` / `path_body_sha` / `signed_carrier`）。
    """
    from . import manuscriptpaths as _MP
    from . import verifications as _VR

    n = int(path_group or 0)
    sid = str(statement_id or "").strip()
    rel = str(manuscript or "").strip().replace("\\", "/")
    sha = str(body_sha or "").strip().lower()
    out: dict[str, Any] = {"checked": False, "path_group": n, "existing": False,
                           "basis": "", "paths": [], "refused": "", "reason": "",
                           "why": ""}
    if n < 1:
        out.update(refused="bad_path_group",
                   reason=f"路径号必须是正整数（收到 {path_group!r}）")
        return out
    if not sid:
        out.update(refused="bad_statement_id", reason="没有命题号 ⇒ 路径核对不了")
        return out
    reading = _MP.path_reading(tx, root, statement_id=sid)
    out["paths"] = [dict(one) for one in (reading.get("paths") or ())]
    if not reading.get("checked"):
        out.update(refused="path_group_unreadable",
                   reason=("路径记录读不出来 ⇒ 核不了第几条（不猜）："
                           + str(reading.get("why") or "未知原因")))
        return out
    hit = next((one for one in out["paths"]
                if int((one or {}).get("path_group") or 0) == n), None)
    if hit is None:
        out.update(checked=True,
                   refused="path_not_found",
                   reason=(f"第 {n} 条路径还没在册（路径号只能指已存在的路径；"
                           "新路径由秘书在收录事务里分配）"))
        return out
    out.update(checked=True, existing=True)
    # 路径身份不写稿头（业主：「路径在产出侧也不标注」），稿里也没有命题号
    # （业主 2026-11-13：「稿里没有命题号，任何稿里都没有命题号」）⇒ "这份稿属于
    # 哪条命题"只由逐路径记录与同号签行回答（下面两支），不读稿头。
    hit_rel = str(hit.get("manuscript") or "").strip().replace("\\", "/")
    hit_sha = str(hit.get("body_sha") or "").strip().lower()
    if rel and hit_rel and hit_rel == rel:
        out.update(basis="path_manuscript",
                   why=f"第 {n} 条路径的稿记录点名 `{rel}`")
        return out
    if sha and hit_sha and hit_sha == sha:
        out.update(basis="path_body_sha",
                   why=f"第 {n} 条路径的正文 sha 就是这一份")
        return out
    # ---- 第一轮优化：路径记录还指着 F/E 的源稿；这一份是新落的 B 改写稿 --------
    #
    # 路径身份不写稿头（业主：「路径在产出侧也不标注」），逐路径记录要等收录成功才
    # 绑上新稿。所以第一轮只能核对两件事：这一份稿的签行已经在（优化线要求先拿签）、
    # 且它没有被绑到别的路径上。第二轮起 `path_manuscript` 那一档会命中。
    try:
        rows, _bad = _VR.list_verifications(root, statement_id=sid, limit=None)
    except Exception:  # noqa: BLE001 —— 读不到签行就按"对不上"受控拒（不猜）
        rows = []
    bound_elsewhere = 0
    signed_here = False
    for one in rows or ():
        doc = dict(one or {})
        rec = str(doc.get("manuscript") or doc.get("object_path") or "").strip().replace("\\", "/")
        row_sha = str(doc.get("proof_sha256") or "").strip().lower()
        try:
            row_group = int(doc.get("path_group") or 0)
        except (TypeError, ValueError):
            row_group = 0
        if rel and rec == rel:
            if row_group >= 1 and row_group != n:
                bound_elsewhere = row_group
            if sha and row_sha == sha:
                signed_here = True
        elif sha and row_sha == sha and row_group >= 1 and row_group != n:
            bound_elsewhere = row_group
    if bound_elsewhere:
        out.update(refused="path_mismatch",
                   reason=(f"这一份稿已经绑在第 {bound_elsewhere} 条路径上，"
                           f"不是第 {n} 条 ⇒ 不改写"))
        return out
    if signed_here:
        out.update(basis="signed_carrier",
                   why=(f"第 {n} 条路径在册；这一份稿是它有签的改写载体"
                        "（逐路径记录要等这一笔收录成功后才绑上新稿）"))
        return out
    out.update(refused="path_mismatch",
               reason=(f"第 {n} 条路径的稿记录是 `{hit_rel or '（没有稿）'}`"
                       f"（正文 sha {hit_sha[:12] or '无'}…），而这一份是 "
                       f"`{rel or '（没有稿）'}`（{sha[:12] or '无'}…）⇒ 对不上。"
                       "这一份稿要先拿 V 签，再按它自己那条路径回填"))
    return out


def _path_material_numbers(groups: Any) -> list[int]:
    """依赖组里"材料说这是第几条路径"的那几个号（手稿依赖表第 4 列 / 显式给的组号）。

    它们只是材料：产出侧 / 调用方可以写，但最终号由秘书在收录事务里分配。两者
    不一致时由调用方把读数记进 `path_group_material`（"材料说 X、秘书定为 Y"），
    不静默丢掉材料那一份说法。
    """
    seen: set[int] = set()
    for group in (groups or ()):
        for step in (group or ()):
            try:
                no = int(step.get("path_group") or 0)
            except (TypeError, ValueError):
                continue
            if no >= 1:
                seen.add(no)
    return sorted(seen)


def _note_path_material(out: dict, material: list[int], *, decided: int) -> None:
    """材料号与秘书定的号不一致 ⇒ 在回执里点名（读的人要看得出"谁说了算"）。"""
    if not material or all(int(x) == int(decided) for x in material):
        return
    out["path_group_material"] = {
        "material": [int(x) for x in material],
        "secretary": int(decided),
        "why": (f"材料说 {[int(x) for x in material]}、秘书定为 {int(decided)}"
                "（最终号以秘书分配为准；材料只作参考）"),
    }


def _stamp_path_number(steps: Any, *, path_group: int, proof_no: int,
                       single_group: bool = True) -> list[dict]:
    """把秘书分到的号盖到已解析的依赖步骤上（返回新列表，不改调用方那份载荷）。

    两格各管一件事（`_write_dep_steps` 的同一口径）：
    - `proof_no` ⇒ `used_by` 的 `#pN` 尾巴 = "这条依赖出自第几份证明正文"；
    - `path_group` ⇒ 那一列 = "同一份证明里的第几条可选路径"。

    什么时候盖 `path_group`：只有"这一份稿 = 这一条路径"（`single_group`）时才盖。
    载荷显式交了二维 `deps`（外层 = 可选路径、内层 = 一步）时，那几个组号是调用方
    对"一份证明里有几条可选路径"的声明，不是"第几份证明" —— 盖成分配号会把两条
    可选路径并成一条（`test_b_hands_content_to_the_secretary` 钉住它）。同理，
    证明正文里分段扫出来的那一路（`_from="proof_scan"`）保留段落下标（1/2…）。
    """
    out: list[dict] = []
    for step in (steps or ()):
        one = dict(step)
        if single_group:
            one["proof_no"] = int(proof_no)
            if str(step.get("_from") or "") != "proof_scan":
                one["path_group"] = int(path_group)
        out.append(one)
    return out


def _deps_missing_reading(*, proof_text: Any, deps_written: int,
                          derived_from: Any = (), stmt_id: str = "",
                          proof_no: int = 0, scan: Mapping[str, Any] | None = None) -> dict:
    """这一行"带证明正文、却一条依赖都没落"时的三态读数（`state` 只有三档）。

    为什么需要这一格（真机 sylow3，2026-10-24）：七条命题各自带 2700 到 6300 字的证明，
    而 `dependencies` 全表 0 行 —— 证明里写的是中文散文式的"引理 1 / 引理 4"，
    引用扫描只认 `stmt:` / `lit:` / `exp:` / `doc:` 四种前缀，于是一条都扫不出来，
    `deps_state="none_in_proof"`、`deps_written=0`。这两个读数都只活在这一次调用的
    返回值里，收工门不数 `dependencies`、读侧也没有一格问过这件事 ⇒ 依赖面 0 行
    是静默的，C 的"按依赖面追几条不同证明路径"因此无从谈起。

    三态（不猜）：
    :data:`DEPS_MISSING_PRESENT` —— 落了至少一条依赖，依赖面建起来了；
    :data:`DEPS_MISSING_ABSENT` —— 带证明正文而零依赖。两条子因分开写：
        `derived_from` 非空 ⇒ 依赖信息其实在盘上的另一处（命题行的 `derived_from`），
        只是没落成 `dependencies` 行；`derived_from` 也空 ⇒ 证明正文里确实没有一条
        在册引用（自足证明合法，但读的人要能看出"扫了、确实是空"）；
    :data:`DEPS_MISSING_NOT_APPLICABLE` —— 这一行没有证明正文（概念行 / 还没写证明），
        依赖面这一格不适用。
    """
    text = str(proof_text or "")
    chars = len(text.strip())
    derived = [str(x) for x in (derived_from or ())]
    refs = int((scan or {}).get("refs") or 0)
    out: dict[str, Any] = {
        "state": DEPS_MISSING_NOT_APPLICABLE,
        "stmt_id": str(stmt_id or ""),
        "proof_no": int(proof_no or 0),
        "proof_chars": chars,
        "deps_written": int(deps_written or 0),
        "scanned_refs": refs,
        #: 依赖信息的另一处落点（命题行的 `derived_from`）：它非空而依赖表 0 行，
        #: 就是"信息在盘上、依赖面没建起来"的那一档。
        "derived_from": derived,
        "why": "",
        "next_step": "",
    }
    if chars <= 0:
        out["why"] = ("这一行没有证明正文（概念行 / 还没写证明）⇒ 依赖面这一格不适用"
                      "（既不是「缺依赖」，也不是「依赖为零」）")
        return out
    if int(deps_written or 0) > 0:
        out["state"] = DEPS_MISSING_PRESENT
        out["why"] = f"这一行落了 {int(deps_written)} 条依赖，依赖面建起来了"
        return out
    out["state"] = DEPS_MISSING_ABSENT
    if derived:
        out["why"] = (
            f"这一行有 {chars} 字证明正文，却一条 `dependencies` 行都没有；"
            f"而它的 `derived_from` 点名了 {derived} —— 依赖信息在盘上的另一处，"
            "没有落成依赖边（依赖表里读不到，按依赖面追证明路径的人就看不到）")
        out["next_step"] = (
            "把这些号写成依赖边：`B.register_statement` 交 `derived_from` 的同时"
            "把证明里的引用写成 `stmt:NNNNNN`（扫描只认带前缀的写法），"
            "或由 G 走 `doc.register_dependency` 逐条登记")
    else:
        out["why"] = (
            f"这一行有 {chars} 字证明正文，而引用扫描一条在册引用都没扫到"
            f"（扫了 {refs} 条）⇒ 依赖表 0 行。自足的证明合法，但「扫了、确实是空」"
            "与「没扫」必须分开读：`deps_state` 给的就是这个三态")
        out["next_step"] = (
            "如果这份证明其实引用了在册的命题 / 文献 / 实验，请把引用写成带前缀的样子"
            "（`stmt:` / `lit:` / `exp:` / `doc:`）再交一次，或在证明正文里逐条点名；"
            "如果它确实自足，这一格就是如实的「零依赖」")
    return out


def _resolve_dep_steps(groups: Iterable[Iterable[Mapping[str, Any]]],
                       tx: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把二维列表解析成可落盘的一步一行（只读：解析完再决定写不写）。

    返回 `(steps, missing)`：`steps` 每项带 `path_group`（外层下标，从 1 起）与那一个来源字段；
    `missing` 是"这一步落不了"的那些（给出为什么），非空 ⇒ 调用方整笔不写。
    三态：`missing` 不是空的时候，不许退化成"少写一条边就算了" ——
    依赖图上少一环没有任何地方会报错（这正是 `draft/97` §13.3 要堵的形态）。
    """
    steps: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for gi, grp in enumerate(groups, start=1):
        for st in grp:
            #: 组号：这一步自己带了 `path_group` 就用它（多证明清单那一档里
            #: "一份证明 = 一条可选路径"，组号就是证明号）；没带就用它在二维列表里
            #: 的位置 —— 老写法（`deps` / `proof_paths`）的读数因此逐字不变。
            try:
                group_no = int(st.get("path_group") or 0) or gi
            except (TypeError, ValueError):
                group_no = gi
            found = [(key, field, table, idf, dkind)
                     for key, field, table, idf, dkind in STEP_SOURCE_KEYS
                     if str(st.get(key) or "").strip()]
            if len(found) != 1:
                missing.append({"path_group": group_no, "step": dict(st),
                                "why": ("一步依赖必须恰好给一个来源（stmt_id / "
                                        "experiment_id / lit_id / doc_id 四选一）")})
                continue
            key, field, table, idf, dkind = found[0]
            sid = str(st[key]).strip()
            if tx.find(table, **{idf: sid}) is None:
                missing.append({"path_group": group_no, "step": dict(st),
                                "why": f"{table} 表里没有 {idf}={sid!r}"})
                continue
            kind = str(st.get("kind") or dkind)
            if kind not in S.DEP_KINDS:
                missing.append({"path_group": group_no, "step": dict(st),
                                "why": f"kind 必须是 {S.DEP_KINDS} 之一，收到 {kind!r}"})
                continue
            step = {"path_group": group_no, "kind": kind, "label": str(st.get("label") or ""),
                    "quote": str(st.get("quote") or ""),
                    #: 这一步从哪来：`proof_scan` = 证明正文里扫出来的（一份证明里的
                    #: 第几条可选路径），其余 = 手稿依赖段 / 调用方显式给的（一份稿 =
                    #: 一条路径）。收录时按这条痕迹决定"路径号盖哪一格"。
                    "_from": str(st.get("_from") or "")}
            #: 这一步属于第几份证明（多证明清单那一档才会带）：不往这里搬的话，
            #: `_write_dep_steps` 只能按 `body["proof_no"]` 落 `used_by`，
            #: 于是 #p2 / #p3 的依赖会全被记到 #p1 名下（依赖面又混成一维）。
            try:
                step_no = int(st.get("proof_no") or 0)
            except (TypeError, ValueError):
                step_no = 0
            if step_no >= 1:
                step["proof_no"] = step_no
            step[field] = sid
            steps.append(step)
    return steps, missing
