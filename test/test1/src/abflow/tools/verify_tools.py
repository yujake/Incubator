"""E 的工具：**数值实验与形式化验证**。

## 这一层要解决的根本问题

数学里"算对了"与"证完了"是天壤之别。一个能跑数值实验的系统，最大的危险
不是算错，而是把**算对了**说成**证明了** —— 因为这两句话在自然语言里
只差几个字，而在数学上是两个世界。

因此本模块的所有产出都强制带 :data:`abflow.schema.EVIDENCE_KINDS` 等级，
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
  导入**去调 `abflow.agent_e`，而不是在这里再写一份。理由同 `agent_d` 对
  `interactions` 的委托：同一份判据写在两处必然漂移，而漂移是**静默**的
  —— "工具写进去的记录"与"AgentE 写进去的记录"字段口径不同，没有任何地方会报错。
- `evidence_for` / `list_experiments` 是纯查询，直接在这里实现，`AgentE` 转发过来。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import schema as S
from .base import ParamError, ToolResult, ToolRegistry, ToolSpec, fail, ok

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

    返回 ``{"available": [...], "checked": True/False, "reason": str}``。
    **`checked=False` 只表示"探测本身没做成"**（例如 PATH 不可读），
    `available=[]` 才是"探测了，确实没有"。两者不能合并。
    """
    import shutil
    import subprocess

    out: list[dict] = []
    for name, cmd in _VERIFIER_CANDIDATES:
        exe = shutil.which(name)
        if not exe:
            continue
        ver = ""
        try:
            r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=10)
            ver = (r.stdout or r.stderr or "").strip().splitlines()[0] if (r.stdout or r.stderr) else ""
        except Exception as e:  # noqa: BLE001
            ver = f"(版本探测失败：{type(e).__name__}: {e})"
        out.append({"name": name, "path": exe, "version": ver})
    return {
        "checked": True,
        "available": out,
        "available_names": [x["name"] for x in out],
        "reason": (
            f"探测到 {len(out)} 个证明检查器：{'、'.join(x['name'] for x in out)}"
            if out
            else "探测完成：环境里**没有**任何受支持的证明检查器 ⇒ 本环境无法产出 proof 级证据"
        ),
    }


def check_formal(claim: str, *, script_path: str | None = None) -> ToolResult:
    """把一条命题交给形式化检查器。

    ⚠️ **没后端时返回的是"没做"，不是"没过"**：
    ``ok=True, checked=False, reason="no_backend"``。调用方据此必须把
    实验的 `evidence_kind` 保持在 `cross_check`/`heuristic`，绝不允许升到 `proof`。
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
    if not script_path:
        return ok(
            {
                "checked": False,
                "verified": None,
                "claim": claim,
                "reason": "no_script",
                "detail": (
                    "环境里有检查器，但调用方没有给出待检查的形式化脚本（script_path）"
                    "⇒ 没做验证"
                ),
                "verifier_output": "",
            }
        )
    return fail(
        f"形式化检查器的实际调用尚未接线（探测到 {det['available_names']}，"
        f"脚本 {script_path}）。本工具**不会**在没有真正跑过的情况下返回 verified=True",
        kind="not_implemented",
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
        return {
            "checked": False,
            "experiments": [],
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
            handler=lambda path: ok({"path": path, "code_hash": code_hash(_resolve(path))}),
            side_effect="read",
            roles=_ROLES,
            returns="{'path': str, 'code_hash': str}",
            tags=("experiment", "reproducibility"),
        )
    )

    registry.register(
        ToolSpec(
            name="verify.detect_verifier",
            summary="探测环境里可用的证明检查器（Lean/Coq/Isabelle）。返回的是事实，不是猜测",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: ok(detect_verifier()),
            side_effect="none",
            roles=_ROLES,
            returns="{'checked', 'available': [...], 'reason'}",
            tags=("experiment", "formal"),
        )
    )

    registry.register(
        ToolSpec(
            name="verify.check_formal",
            summary="把命题交给形式化检查器核验；无后端时返回 checked=False/no_backend（不是'验证失败'）",
            params={
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "script_path": {"type": "string"},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
            handler=lambda claim, script_path=None: check_formal(claim, script_path=script_path),
            side_effect="read",
            roles=_ROLES,
            returns="{'checked', 'verified', 'reason', 'verifier_output'}",
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
                or ok(
                    _agent_for(store, root).run_experiment(
                        claim,
                        claim_key,
                        script_path,
                        params=params,
                        method=method,
                        for_question_id=for_question_id,
                        timeout=timeout,
                    )
                )
            ),
            side_effect="write_local",
            roles=_ROLES_WRITE,  # H 只读：不能拥有"跑实验并落库"的能力
            returns="{experiment_id, recorded, result, evidence_kind, negation_kind, exit_code, reason}",
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
                or ok(evidence_for(store, claim_key, for_question_id=for_question_id))
            ),
            side_effect="read",
            roles=_ROLES,
            returns="{checked, experiments, best_evidence_kind, proved, reason}",
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
                or ok(list_experiments(store, claim_key=claim_key, limit=limit))
            ),
            side_effect="read",
            roles=_ROLES,
            returns="{checked, total, returned, truncated, experiments}",
            tags=("experiment",),
        )
    )
