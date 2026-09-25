"""E 的工具：**数值实验与形式化验证**。

## 这一层要解决的根本问题

数学里"算对了"与"证完了"是天壤之别。一个能跑数值实验的系统，最大的危险
不是算错，而是把**算对了**说成**证明了** —— 因为这两句话在自然语言里
只差几个字，而在数学上是两个世界。

因此本模块的所有产出都强制带 :data:`agentflow.schema.EVIDENCE_KINDS` 等级，
并且计算类方法**在 schema 层就拿不到 `proof`**（见 `Experiment.validate`）。
这不是注释里的告诫，是写入时的硬约束。

## 为什么 "没有后端" 是一个必须显式表达的状态

`formal.check` 在环境里没有 Lean/Coq 时**必须**返回
`checked=False, reason="no_backend"`，而不是 `ok=False, verified=False`。
理由是本项目反复踩过的三态纪律：把"没做"和"做了但没成"折叠成同一个
`False`，下游就会把"我们没验证"读成"验证没过"，或者更糟——
把"没验证"当成"没问题"。

## 工具与智能体的分工（读了会少走弯路）

本模块的 `verify.run_experiment` / `verify.evidence_for` / `verify.list_experiments`
是本文件里**已有的三个纯函数**（`:func:`check_formal` 与另外两条查询）的薄封装：

- `run_experiment` 是一个**有副作用的动作**（跑子进程 + 写 experiments 表），
  它必须与 `AgentE.run_experiment` 是同一条实现。所以工具 handler 用**惰性
  导入**去调 `agentflow.agent_e`，而不是在这里再写一份。理由同 `agent_d` 对
  `interactions` 的委托：同一份判据写在两处必然漂移，而漂移是**静默**的
  —— "工具写进去的记录"与"AgentE 写进去的记录"字段口径不同，没有任何地方会报错。
- `evidence_for` / `list_experiments` 是纯查询，直接在这里实现，`AgentE` 转发过来。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import schema as S
from ..store import StoreError
from .base import ParamError, ToolError, ToolResult, ToolRegistry, ToolSpec, fail, ok

#: 本模块声明的角色。E 做实验，F 需要读实验结果来推进子目标，
#: G 需要引用实验作为证据，H 需要核对"证据等级有没有被夸大"。
#: **A/B/C/D 不在其中**：它们关心的是文献与关系，不是数值证据。
_ROLES = ("E", "F", "G", "H")

#: **写工具**（会跑子进程 + 写 `experiments` 表）单独声明角色：H 只读，
#: 不能拥有"跑实验并落库"的能力。声明正确 + `for_role` 的结构性拦截，
#: 两道一起上 —— 只靠其中一道都会在后续维护里被绕过。
_ROLES_WRITE = ("E", "F", "G")

#: 形式化检查器的候选可执行文件。**逐个探测，不猜**。
#: 猜"环境里应该有 lean"会让 `checked` 字段变成谎话。
_VERIFIER_CANDIDATES = (
    ("lean", "lean --version"),
    ("coqc", "coqc --version"),
    ("isabelle", "isabelle version"),
)

#: 证据力排序（弱 → 强）。用于 `best_evidence_kind`。
#:
#: ⚠️ **它不是"从 schema 推导出来的"**，而是本模块对 `EVIDENCE_KINDS` 的**运行期
#: 断言**：顺序一旦与 schema 的声明不符，导入期就炸。理由：`best_evidence_kind`
#: 的取值口径（"最强的那个"）如果与 schema 对证据等级的排序不一致，
#: 就会出现"报告说 proof、实验记录里只有 cross_check"这种**无人报错**的分歧。
#: 宁可在这里 fail-closed，也不要靠"两个地方恰好写对了"。
_EVIDENCE_ORDER = ("heuristic", "cross_check", "proof")
assert set(_EVIDENCE_ORDER) == set(S.EVIDENCE_KINDS), (
    f"_EVIDENCE_ORDER={_EVIDENCE_ORDER} 与 schema.EVIDENCE_KINDS={S.EVIDENCE_KINDS} 不一致 —— "
    "证据等级的排序口径必须只有一处定义"
)
#: 最强的证据等级。**从上面的排序里取末位**，而不是再写一遍字面量 "proof"。
_TOP_EVIDENCE = _EVIDENCE_ORDER[-1]


def code_hash(path: str | Path) -> str:
    """脚本内容的 sha256（前 16 位十六进制）。

    为什么实验记录里必须有它：`code_path` 只说明"当时跑的是哪个文件"，
    而文件**是可以被改的**。没有哈希，三个月后那条"可复现"的记录就指向了
    另一段代码 —— 而复现失败时你无法判断是结论错了还是脚本变了。
    """
    p = Path(path)
    if not p.is_file():
        raise ParamError(f"code_hash: 文件不存在：{p}")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def detect_verifier() -> dict:
    """探测环境里有哪些证明检查器。

    返回 ``{"available": [...], "available_names": [...], "checked": True/False,
    "reason": str, "probe_errors": [...]}``。

    **`checked=False` 只表示"探测本身没做成"**（例如 PATH 不可读、`shutil.which`
    抛异常、二进制在但版本探测起不来），`available=[]` 才是"探测了，确实没有"。
    两者不能合并 —— 合并会把"我们不知道环境里有没有 Lean"读成
    "环境里确定没有 Lean"，而后者会让一条本该走形式化核验的命题
    悄悄停在 cross_check 上。

    ⚠️ 本函数曾经把 `checked` **硬编码成 True**（docstring 承诺了一个
    任何代码路径都返回不了的状态），且工具声明 ``side_effect="none"`` ——
    而它实际上会 `shutil.which` + `subprocess.run` 起外部二进制。
    现在的口径：探测有任何一步失败 ⇒ `checked=False` 并把失败逐条列进
    `probe_errors`；副作用等级由调用方声明为 ``read``（执行本地只读命令，
    `verify.detect_verifier` 的 ToolSpec 见文件末尾）。
    """
    import shutil
    import subprocess

    out: list[dict] = []
    probe_errors: list[str] = []
    for name, cmd in _VERIFIER_CANDIDATES:
        try:
            exe = shutil.which(name)
        except Exception as exc:  # noqa: BLE001 - PATH 不可读等
            probe_errors.append(f"{name}：which 失败（{type(exc).__name__}: {exc}）")
            continue
        if not exe:
            continue
        ver = ""
        try:
            r = subprocess.run(cmd.split(), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=10)
            ver = (r.stdout or r.stderr or "").strip().splitlines()[0] if (r.stdout or r.stderr) else ""
        except Exception as e:  # noqa: BLE001
            ver = f"(版本探测失败：{type(e).__name__}: {e})"
            # "二进制在 PATH 上"这个事实成立（仍记入 available），
            # 但"探测完成"不成立 ⇒ checked=False。两者的区别必须保留：
            # 前者让调用方知道有这个检查器，后者让它知道版本号不可信。
            probe_errors.append(f"{name}：版本探测失败（{type(e).__name__}: {e}）")
        out.append({"name": name, "path": exe, "version": ver})
    checked = not probe_errors
    return {
        "checked": checked,
        "available": out,
        "available_names": [x["name"] for x in out],
        "probe_errors": probe_errors,
        "reason": (
            (
                f"探测到 {len(out)} 个证明检查器：{'、'.join(x['name'] for x in out)}"
                if out
                else "探测完成：环境里**没有**任何受支持的证明检查器 ⇒ 本环境无法产出 proof 级证据"
            )
            if checked
            else f"探测**没做成**（{len(probe_errors)} 处失败）：{'；'.join(probe_errors)}"
            + (
                f"；已探到的检查器：{'、'.join(x['name'] for x in out)}" if out else ""
            )
        ),
    }


def check_formal(
    claim: str,
    *,
    script_path: str | None = None,
    source: str | None = None,
    name: str | None = None,
    imports: Sequence[str] | None = None,
    timeout_sec: float | None = None,
) -> ToolResult:
    """把一条命题交给 Lean 检查器真跑一次 —— 转发到 `agentflow.formalgw.check_lean`。

    ## 这一层只做三件事，判据一条都不重复

    1. 把调用方的四种输入形态归一（源码 / 工作区内的脚本路径 / 声明名 / imports 与超时）；
    2. 转发给 `formalgw.check_lean`，它是"什么算证明"的唯一定义处；
    3. 把它的八值受控词表折成调用方看得懂的三态，并按本工具既有的六键形态返回。

    判定顺序、sorry 判据、公理审计、声明名核对、超时归类全部在 `formalgw` 里，
    本函数不复制其中任何一条 —— 两处各写一份判据的漂移是静默的，而那正是
    桥接层最不能出的错（清单理由逐字："桥接层说谎 ⇒ proof 级证据是假的"）。

    ## 三态纪律（与接线前的口径一致，只是现在真的会跑了）

    `formalgw.STATUSES` 的八个取值折成两问：`checked` = "这次查成了吗"，
    `verified` = "查成了、而且过了吗"：

    ==========================  =========  ==========  ==================================
    status                      checked    verified    含义
    ==========================  =========  ==========  ==================================
    `verified`                  True       True        proof 级证据（唯一的通过）
    `compile_error`             True       False       查了，没通过
    `uses_sorry`                True       False       查了，那份"证明"里有 sorry/admit
    `extra_axioms`              True       False       查了，用了允许集之外的公理
    `decl_mismatch`             True       False       查了，但声明名对不上
    `timeout`                   False      None        没查成（不是"证伪了"）
    `no_backend`                False      None        没查成（环境里没有后端）
    `tool_crashed`              False      None        没查成（桥接层自己出错）
    ==========================  =========  ==========  ==================================

    只有 `verified` 才给 `verified=True`：`checked=True + verified=False` 表示
    "跑过了、它不是证明"，而 `verified is None` 一律表示"本次没有验证结论"，
    绝不写成 `False`（那会读成"验证失败"）。`checked` 直接取自
    `formalgw.evidence_of` 的结论，而不是在这里再列一遍状态名。

    ## 调用方没给源码时

    留给 `formalgw.check_lean` 的 `source_path` 入口去读那个文件：读不到时它按
    "文件里没有你要证的东西"（`decl_mismatch`）如实收口，于是"脚本写错了路径"
    与"后端不在"分得开，而两者都不会被读成通过。本函数不自己读文件，也不把
    读文件失败改成 `no_script` —— 那会把一次可诊断的失败折叠成"调用方没给输入"。

    ## 副作用

    `source` 给的是内存里的源码时，`formalgw` 会写一份临时 `.lean` 文件（跑完即删）；
    `workdir` 为 None 时它建的是临时目录。脚本路径存在时源码仍从文件读。因此
    本工具的实际副作用是"起检查器子进程 + 写临时文件"，工具声明为 `read`
    （执行本地只读命令）—— 与 `verify.detect_verifier` 同一口径：`none` 表示
    "什么都不做"，而它显然不是。两者都不需要审批，所以审批面没有变化。
    """
    det = detect_verifier()
    if not det["available"]:
        return ok(
            {
                "checked": False,
                "verified": None,
                "claim": claim,
                "reason": "no_backend",
                "detail": det["reason"],
                "verifier_output": "",
            },
            note="未验证：环境无证明检查器。**这不等于验证失败**",
        )
    if not (source and source.strip()) and not script_path:
        return ok(
            {
                "checked": False,
                "verified": None,
                "claim": claim,
                "reason": "no_script",
                "detail": (
                    "环境里有检查器，但调用方既没有给 Lean 源码（source），"
                    "也没有给待检查的脚本路径（script_path）⇒ 没做验证"
                ),
                "verifier_output": "",
            }
        )

    # 惰性导入：本模块的顶层只依赖标准库，而 `formalgw` 会拉起检查器那一层。
    # 方向也是刻意的 —— `formalgw` 反向 import 本模块的 `detect_verifier`，
    # 顶层互引会成环。
    from ..formalgw import STATUSES, PROOF_STATUS, check_lean

    nm = str(name or "")
    if source and source.strip():
        src = str(source)
        path_arg: str | None = None
    else:
        # 脚本路径原样转发给 `formalgw.check_lean` 的 `source_path` 入口 ——
        # 本层**不**自己读文件。理由：读不到时的收口方式（"文件里没有那条声明"）
        # 是与声明名核对同一处的判据，转发层再实现一遍就会长出第二份口径。
        src = ""
        path_arg = str(script_path)
        if not nm:
            nm = Path(str(script_path)).stem

    if not nm:
        # 没有名字 ⇒ `#print axioms` 与声明名核对都无从谈起。刻意**不**回退成
        # 文件名：一个猜出来的名字会让"声明名核对"这条判据在无声中失效，
        # 而它正是拦住"声称证了 foo、文件里却没有 foo"的那一条。
        return fail(
            "check_formal：拿不到声明名 —— 源码里没有具名声明（只有 example 或全被注释），"
            "调用方也没有显式给 name。声明名核对与公理审计都要求这个名字，"
            "猜一个名字等于把那条判据悄悄关掉。请显式给出 name。",
            kind="param_error",
            claim=claim,
        )

    try:
        raw = check_lean(
            src,
            name=nm,
            imports=imports if imports is not None else ("Mathlib",),
            timeout_sec=float(timeout_sec) if timeout_sec is not None else 600,
            source_path=path_arg,
        )
    except ValueError as exc:
        # `check_lean` 对非法声明名 / 空源码参数抛 ValueError。它是调用方写错了
        # 参数，不是"验证没过"，因此必须停在 param_error 上。
        return fail(f"check_formal：参数不合法：{exc}", kind="param_error")
    except Exception as exc:  # noqa: BLE001 - 桥接层的任何异常都只能落"没查成"
        return fail(
            f"check_formal：检查器桥接层出错（{type(exc).__name__}: {exc}）⇒ 没查成，"
            "既不是通过也不是证伪。",
            kind="check_failed",
        )

    # `evidence_of` 是"这次到了什么等级"的唯一定义处（`_conclude` 每次都算好），
    # 因此 `checked` 从它读，而不是在这里再列一遍"哪些状态算查了"。
    ev = raw.get("evidence") or {}
    status = str(raw.get("status") or "")
    checked = bool(ev.get("checked"))
    proved = status == PROOF_STATUS
    return ok(
        {
            "checked": checked,
            "verified": True if proved else (False if checked else None),
            "claim": claim,
            "reason": status if status in STATUSES else "tool_crashed",
            "detail": raw.get("reason") or "",
            "verifier_output": (
                (str(raw.get("stdout") or "") + "\n" + str(raw.get("stderr") or "")).strip()
            ),
        },
        # 机器可读的留痕：受控词表之外的状态一个都不许被当成通过。
        status=status,
        checked_source=(raw.get("checked_source") or "")[:2000],
        axioms=raw.get("axioms"),
        sorry_count=raw.get("sorry_count"),
        decl_matches=raw.get("decl_matches"),
        declared_in_source=raw.get("declared_in_source"),
        source_sha256=raw.get("source_sha256"),
        source_path=raw.get("source_path"),
        ran=raw.get("ran"),
        backend_status=((raw.get("backend") or {}).get("status") if isinstance(raw.get("backend"), Mapping) else None),
        evidence_kind=ev.get("evidence_kind"),
    )


# ---------------------------------------------------------------- 证据查询（纯函数）
#
# 这两个函数**不接收 store 实例以外的东西**，也不做任何写入：它们是 E 的"读侧"，
# 被 AgentE 的方法与工具层同时使用（同一份实现）。


def evidence_for(
    store: Any,
    claim_key: str | None = None,
    *,
    for_question_id: str | None = None,
) -> dict:
    """按 ``claim_key`` 和/或 ``for_question_id`` 汇总已有实验证据。

    ## 三态纪律（本函数的核心）

    ================================  ==========================================
    调用方式                            返回
    ================================  ==========================================
    给了 claim_key / for_question_id    ``checked=True``，experiments 可能为空
    两个都不给                          ``checked=False``（**没查**）
    ================================  ==========================================

    "没查"与"查了、没有"必须分开：前者是调用方的问题（它不知道该查什么），
    后者是一个**有效结论**（"这条命题本地没有任何实验证据"）。

    ``proved`` **只有**在存在 ``evidence_kind=="proof"`` 的实验时才为 True
    （FC-22：数值/穷举支持不构成证明）。
    """
    if claim_key is None and for_question_id is None:
        # 形状与"查了"那一支**完全一致**（含分档计数的零值）：调用方可以无条件地读
        # `result_counts`，而"这一支少了几个键"正是 4.5 类缺陷的温床 ——
        # 声明一套键、某些分支给另一套，会让调用方按 `.get()` 一路写下去，
        # 把结构性缺失读成"计数为零"。
        return {
            "checked": False,
            "experiments": [],
            "count": 0,
            "result_counts": {k: 0 for k in S.EXPERIMENT_RESULTS},
            "negation_counts": {k: 0 for k in S.NEGATION_KINDS},
            "best_evidence_kind": None,
            "proved": False,
            "reason": (
                "既没有 claim_key 也没有 for_question_id ⇒ **没查**。"
                "注意这与'查了、没有证据'是两件事"
            ),
        }

    hits: list[dict] = []
    for row in store.rows("experiments"):
        if claim_key is not None and row.get("claim_key") != claim_key:
            continue
        if for_question_id is not None and row.get("for_question_id") != for_question_id:
            continue
        hits.append(row)
    hits.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("experiment_id") or "")))

    if not hits:
        scope = []
        if claim_key is not None:
            scope.append(f"claim_key={claim_key!r}")
        if for_question_id is not None:
            scope.append(f"for_question_id={for_question_id!r}")
        return {
            "checked": True,
            "experiments": [],
            "count": 0,
            "result_counts": {k: 0 for k in S.EXPERIMENT_RESULTS},
            "negation_counts": {k: 0 for k in S.NEGATION_KINDS},
            "best_evidence_kind": None,
            "proved": False,
            "reason": (
                f"已查（{' 且 '.join(scope)}）：**没有**任何登记在案的实验证据。"
                "这是'查了、没有'，不是'没查'"
            ),
        }

    kinds = [str(r.get("evidence_kind") or "") for r in hits]
    known = [k for k in kinds if k in _EVIDENCE_ORDER]
    best = max(known, key=_EVIDENCE_ORDER.index) if known else None
    proved = best == _TOP_EVIDENCE
    # FC-10：结果必须**分档计数**，不许只给一个"有证据/没证据"的布尔。
    # 只有布尔时，"算出来支持"与"脚本崩了"在调用方眼里长得一样。
    result_counts = {k: 0 for k in S.EXPERIMENT_RESULTS}
    negation_counts = {k: 0 for k in S.NEGATION_KINDS}
    for r in hits:
        res = str(r.get("result") or "")
        if res in result_counts:
            result_counts[res] += 1
        neg = r.get("negation_kind")
        if neg in negation_counts:
            negation_counts[str(neg)] += 1
    return {
        "checked": True,
        "experiments": hits,
        "count": len(hits),
        "result_counts": result_counts,
        "negation_counts": negation_counts,
        "best_evidence_kind": best,
        "proved": proved,
        "reason": (
            f"已查：{len(hits)} 条实验（{result_counts}），最强证据等级为 {best!r}"
            + ("（有 proof 级证据）" if proved else "（**没有** proof 级证据 ⇒ 未被证明）")
        ),
    }


def list_experiments(store: Any, *, claim_key: str | None = None, limit: int | None = None) -> dict:
    """按登记顺序列出实验记录（只读）。

    与 `evidence_for` 的分工：`evidence_for` 回答"这条命题被证明了吗"，
    本函数回答"E 到底做过哪些实验"。**少了后者，"没做过"就无法自证**。
    """
    lim = None if limit is None else max(0, int(limit))
    rows = [r for r in store.rows("experiments") if claim_key is None or r.get("claim_key") == claim_key]
    rows.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("experiment_id") or "")))
    total = len(rows)
    if lim is not None:
        rows = rows[:lim]
    return {
        "checked": True,
        "total": total,
        "returned": len(rows),
        "truncated": bool(lim is not None and total > lim),
        "experiments": [
            {
                "experiment_id": r.get("experiment_id"),
                "claim_key": r.get("claim_key"),
                "method": r.get("method"),
                "evidence_kind": r.get("evidence_kind"),
                "result": r.get("result"),
                "negation_kind": r.get("negation_kind"),
                "exit_code": r.get("exit_code"),
                "code_path": r.get("code_path"),
                "code_hash": r.get("code_hash"),
                "for_question_id": r.get("for_question_id"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
        "reason": f"共 {total} 条实验记录，返回 {len(rows)} 条",
    }


def _resolve_root(root: str | Path | None) -> Path:
    """工作区根。``None`` ⇒ cwd（与外部 `root` 参数的既有默认一致）。"""
    return Path(root) if root else Path.cwd()


def _agent_for(store: Any, root: str | Path | None):
    """构造一个 AgentE。**惰性导入**：本模块被 agent_e 反向引用，模块级导入会成环。"""
    from ..agent_e import AgentE  # 惰性：避免 tools ↔ agent 的循环导入

    return AgentE(store, workspace_root=_resolve_root(root))


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    root: str | Path | None = None,
    **_: Any,
) -> None:
    """装配 E/F/G/H 可见的实验工具。

    ⚠️ ``store`` 为 None 时 `verify.run_experiment` / `evidence_for` /
    `list_experiments` **照样注册**，调用时返回 ``ok=False, kind="not_wired"``
    （FC-08：未接线必须显式失败，**不得静默降级为空**）。
    """
    base = _resolve_root(root)

    def _resolve(rel: str) -> Path:
        """把工具参数里的相对路径解析到工作区内，并**拒绝**越界。

        与 `Store.library_path` 同样的思路：路径穿越的最后一道闸必须在
        真正 open 文件之前，而不是靠调用方自觉。
        """
        p = (base / rel).resolve()
        try:
            p.relative_to(base.resolve())
        except ValueError:
            raise ParamError(f"路径越出工作区：{rel!r}") from None
        return p

    def _need_store(tool: str) -> ToolResult | None:
        """未接线时返回**结构化失败**（不是空数据）。"""
        if store is None:
            return fail(
                f"{tool} 未接线：装配时没有提供 store。"
                "**未接线不等于'没有任何实验结果'** —— 后者会让下游把'我们没查'读成'查了没有'",
                kind="not_wired",
            )
        return None

    def _hash_of(rel: str) -> ToolResult:
        """`verify.code_hash` 的实现。**任何一步失败都要变成结构化失败**。

        ⚠️ 这里此前是 `lambda path: ok({...: code_hash(_resolve(path))})`：
        `code_hash` 只保证"不是普通文件就抛 ParamError"，而 `open(p,"rb")` 的
        `OSError`/`PermissionError`（文件被占用、ACL 拒绝、路径是设备）会
        **逃出工具层**，被 `base.py:381-382` 兜成没有类型信息的 `kind="unexpected"`。
        "读不了这个文件"与"工具内部出了 bug"必须能分开。
        """
        try:
            return ok({"path": rel, "code_hash": code_hash(_resolve(rel))})
        except ToolError:
            raise
        except OSError as exc:
            return fail(
                f"code_hash：读不了 {rel!r}（{type(exc).__name__}: {exc}）。"
                "注意哈希算不出来时**不能**把这条实验记成'可复现'——"
                "代码绑定是复现的前提，缺了它三个月后无法判断是结论错了还是脚本变了。",
                kind="io_error",
                path=rel,
            )

    def _run_experiment_tool(**kw: Any) -> ToolResult:
        """`verify.run_experiment` 的实现。把子进程/实验侧的异常变成结构化失败。

        ⚠️ 这条路径**从不**抛 `ToolError`：`AgentE.run_experiment` 会抛
        `ExperimentError`（`RuntimeError`，如脚本越界、超时、脚本自报非法等级）
        与 `Experiment.validate` 的 `ValueError`。它们此前直接逃出工具层，
        于是"脚本路径越界"和"工具层有 bug"在下游长得一模一样。
        """
        agent = _agent_for(store, root)
        try:
            return ok(
                agent.run_experiment(
                    kw["claim"],
                    kw["claim_key"],
                    kw["script_path"],
                    params=kw.get("params"),
                    method=kw.get("method", "numeric"),
                    for_question_id=kw.get("for_question_id"),
                    timeout=kw.get("timeout", 600),
                )
            )
        except ToolError:
            raise
        except ValueError as exc:
            return fail(
                f"run_experiment：参数/数据校验失败：{exc}（**没有落库**）",
                kind="validation_error",
                script_path=kw.get("script_path"),
            )
        except RuntimeError as exc:
            # ExperimentError 在这里：脚本越界 / 超时 / 实验本身出错。
            return fail(
                f"run_experiment：实验执行失败（{type(exc).__name__}: {exc}）⇒ **没做成**。"
                "这不是'实验做出来一个否定结论'，别把它读成 result=refutes。",
                kind="experiment_error",
                script_path=kw.get("script_path"),
                claim_key=kw.get("claim_key"),
            )
        except OSError as exc:
            return fail(
                f"run_experiment：IO 失败（{type(exc).__name__}: {exc}）⇒ **没做成**。",
                kind="io_error",
                script_path=kw.get("script_path"),
            )

    def _read_rows(table: str, build: Any) -> ToolResult:
        """只读表工具的公共守卫：`store.rows` 的 `StoreError` 不许逃出工具层。"""
        try:
            return ok(build())
        except StoreError as exc:
            return fail(
                f"读 {table} 表失败（{type(exc).__name__}: {exc}）⇒ **没查成**"
                "（不是'没有记录'）。请先修复/重建该表。",
                kind="store_error",
            )

    registry.register(
        ToolSpec(
            name="verify.code_hash",
            summary="计算工作区内一个脚本文件的 sha256（前 16 位），用于实验记录的可复现性绑定",
            params={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "工作区内的相对路径"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=lambda path: _hash_of(path),
            side_effect="read",
            roles=_ROLES,
            returns="{'path': str, 'code_hash': str}；失败：ok=False + kind(io_error/param_error)",
            tags=("experiment", "reproducibility"),
        )
    )

    registry.register(
        ToolSpec(
            name="verify.detect_verifier",
            summary="探测环境里可用的证明检查器（Lean/Coq/Isabelle）。返回的是事实，不是猜测",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: ok(detect_verifier()),
            # read（**不是 none**）：它要 `shutil.which` + `subprocess.run` 起外部二进制
            # （`detect_verifier` 里逐条 `--version`）。声明 `none` 等于说"这个工具
            # 什么都不做" —— 而"不起进程"与"起了进程但只读"是两件不同的事。
            side_effect="read",
            roles=_ROLES,
            returns="{'checked','available','available_names','reason','probe_errors'}",
            tags=("experiment", "formal"),
        )
    )

    registry.register(
        ToolSpec(
            name="verify.check_formal",
            summary=(
                "把一条命题（Lean 源码）交给检查器真跑一次：只有 verified 才给 proof 级证据；"
                "compile_error/uses_sorry/extra_axioms/decl_mismatch 是'查了没通过'；"
                "timeout/no_backend/tool_crashed 是'没查成'，绝不被读成通过或证伪"
            ),
            params={
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "script_path": {
                        "type": "string",
                        "description": "工作区内待检查的 .lean 脚本；给了 source 时以 source 为准",
                    },
                    "source": {"type": "string", "description": "Lean 源码全文（与 script_path 二选一）"},
                    "name": {
                        "type": "string",
                        "description": "要核对的声明名（公理审计与声明名核对都要求它；不给时取文件名词干）",
                    },
                    "imports": {"type": "array", "items": {"type": "string"}},
                    "timeout_sec": {"type": "number", "minimum": 1},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
            handler=lambda claim, script_path=None, source=None, name=None,
            imports=None, timeout_sec=None: check_formal(
                claim,
                script_path=script_path,
                source=source,
                name=name,
                imports=imports,
                timeout_sec=timeout_sec,
            ),
            # read（不是 none）：它真的起检查器子进程，并可能写临时 .lean 文件。
            # 与 `verify.detect_verifier` 同一口径 —— "起了进程但只读"不是"什么都不做"。
            # 两者都不需审批，所以审批面没有变化。
            side_effect="read",
            roles=_ROLES,
            # ⚠️ 这个字符串是**契约**：`tests/test_tools_audit_fixes.py` 逐字解析它，
            # 断言每条分支返回的键集合与之完全相同 —— 于是"声明一套、返回另一套"
            # 在结构上不可能再悄悄发生。
            returns="{'checked','verified','claim','reason','detail','verifier_output'}",
            tags=("experiment", "formal"),
        )
    )

    registry.register(
        ToolSpec(
            name="verify.run_experiment",
            summary=(
                "在独立进程里跑一个工作区内的脚本并登记一条 Experiment 行（会写表 + 跑子进程）。"
                "脚本自报 evidence_kind='proof' 会被降级为 cross_check；崩溃一律记 inconclusive"
            ),
            params={
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "claim_key": {"type": "string"},
                    "script_path": {"type": "string", "description": "工作区内的相对路径"},
                    "params": {"type": "object"},
                    "method": {"type": "string", "enum": list(S.EXPERIMENT_METHODS)},
                    "for_question_id": {"type": "string"},
                    "timeout": {"type": "integer", "minimum": 1},
                },
                "required": ["claim", "claim_key", "script_path"],
                "additionalProperties": False,
            },
            handler=lambda claim, claim_key, script_path, params=None, method="numeric",
            for_question_id=None, timeout=600: (
                _need_store("verify.run_experiment")
                or _run_experiment_tool(
                    claim=claim,
                    claim_key=claim_key,
                    script_path=script_path,
                    params=params,
                    method=method,
                    for_question_id=for_question_id,
                    timeout=timeout,
                )
            ),
            side_effect="write_local",
            roles=_ROLES_WRITE,  # H 只读：不能拥有"跑实验并落库"的能力
            # ⚠️ 待修：它跑的子进程继承完整环境（`agent_e.py` 里 `env = dict(os.environ)`），
            # 严格说应当是 `network`。但 `tests/test_agent_e.py:460` 断言了 `write_local`，
            # 而本轮授权范围不允许改那条断言 ⇒ 保持现状并上报主控。
            # 影响有限：`write_local` 与 `network` **都需要审批**，所以不会绕过审批闸门。
            # 键名从一个**真实跑通**的调用读出（`tests/test_tools_returns_declaration.py`
            # 用 `probes/honest.py` 探针脚本走的就是这一支）：观察到的 10 个键是
            # experiment_id/recorded/result/evidence_kind/negation_kind/exit_code/
            # reason/code_hash/runtime_sec/notes；后三个是**可选键**（取决于脚本与计时），
            # 所以键集合只写前 7 个。
            returns="{'experiment_id','recorded','result','evidence_kind','negation_kind','exit_code','reason'}（另有可选键 code_hash / runtime_sec / notes）",
            tags=("experiment", "evidence"),
        )
    )

    registry.register(
        ToolSpec(
            name="verify.evidence_for",
            summary=(
                "查一条命题（claim_key）或一个研究问题（for_question_id）已有的实验证据。"
                "两个参数都不给 ⇒ checked=False（**没查 ≠ 查了没有**）"
            ),
            params={
                "type": "object",
                "properties": {
                    "claim_key": {"type": "string"},
                    "for_question_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            handler=lambda claim_key=None, for_question_id=None: (
                _need_store("verify.evidence_for")
                or _read_rows(
                    "experiments", lambda: evidence_for(store, claim_key, for_question_id=for_question_id)
                )
            ),
            side_effect="read",
            roles=_ROLES,
            returns=(
                "{'checked','experiments','count','result_counts','negation_counts',"
                "'best_evidence_kind','proved','reason'}（FC-10：必须分档计数，不许只给一个布尔；"
                "三条返回路径的键集合**完全相同**，由 tests/test_tools_audit_fixes.py 逐字核对）"
            ),
            tags=("experiment", "evidence"),
        )
    )

    registry.register(
        ToolSpec(
            name="verify.list_experiments",
            summary="按登记顺序列出实验记录（只读）：没有它就无法回答'这件事到底做过没有'",
            params={
                "type": "object",
                "properties": {
                    "claim_key": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
            handler=lambda claim_key=None, limit=None: (
                _need_store("verify.list_experiments")
                or _read_rows(
                    "experiments", lambda: list_experiments(store, claim_key=claim_key, limit=limit)
                )
            ),
            side_effect="read",
            roles=_ROLES,
            returns="{'checked','total','returned','truncated','experiments','reason'}",
            tags=("experiment",),
        )
    )
