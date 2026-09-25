"""H 的工具：审校。

## 这个模块存在的最重要理由

审校者的判断也需要证据。

这是本项目上一阶段最刺痛的一条教训：评审方提出的一条「缺陷」
（「medium 置信度泄漏进了正文」）是错的，是实现方拿证据顶回来才纠正的。
如果审校记录可以只写「这里有问题」而不给依据，审校就会变成
另一种幻觉的来源 —— 而且因为审校者站在更高的位置，它更难被纠正。

因此：

1. `schema.ReviewFinding.evidence` 必填非空（写入时硬约束）；
2. 本模块的每个检查都给出 `evidence` 字段，内容是触发该发现的实际值
   （例如 `citations=[]`、`evidence_kind='cross_check' 且 disclaimer 为空`），
   而不是一句「看起来不对」；
3. H 只读：它提发现，不改稿。改稿由 G 做。这不是分工洁癖 ——
   若审校者能直接改，它就同时是「发现者」与「修正者」，
   于是「发现问题」与「掩盖问题」在结构上无法区分。

## 「H 只读」在本模块里的落地形态（两条，缺一不可）

- 默认注册面只读：`register()` 只注册 `review.scan_document`（`none`）
  与 `review.list_findings`（`read`）。会写盘的两个入口
  （`review.review_document` / `review.verify_fixes`，均为 `write_local`）
  必须显式 `include_writers=True` 才会被装配 —— 于是「H 的工具面」
  （默认装配结果）在结构上不含任何写工具。
- 它们是 H 的代理步骤，不是 H 的刀：这两个写工具的落点被钉死在
  `review_findings`（新增/改状态）与 `documents.status` 上，
  一个字都不改 `claims` / `knowledge tables`。改稿这件事在 H 侧根本没有入口。

## 判据只有一份（已修，历史见下）

`scan_document` 与 G 侧的 `doc_tools.scan_claim` 同词表（`schema.FINDING_KINDS`），
逐条检查项必须一致：引用是否为空、`evidence_kind` 是否合法、
`cross_check` 是否缺 disclaimer、正文是否过度声称、否定型断言的 `negation_kind`
是否合法/是否该有。

这里曾经是假的：本模块 docstring 声称"不另写一套检查"，而
`scan_document` 把 `scan_claim` 的检查复制了一份且已经漂移 ——
H 侧当时不检查非法 `evidence_kind`、不检查 `negation_kind` 是否在受控词表里、
也不检查"非否定断言却带了 negation_kind"。漂移的后果不是崩溃，而是
"G 认为合规、H 认为通过"这种没有任何报错的静默分裂。
现在这三条已在 `scan_document` 里补齐（与 `scan_claim` 同等级、同判据）。

本轮把根因也去掉了：字段级判据现在归 `claimanatomy`（`CLAIM_FIELDS` 是
唯一声明表），`doc_tools.scan_claim` 只是它的适配层。`scan_document` 仍保留
自己的循环，但它必须产出同一批 finding kind（`schema.FINDING_KINDS`），
且不许比 G 侧轻 —— 这一约束由 `tests/test_tools_audit_fixes.py` 的
双向对照用例钉住，由 `tests/test_gates.py` 的 G10/G14 用例补充。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from pathlib import Path

from .. import claimanatomy as CA
from .. import gates as G
from .. import schema as S
from .base import ToolRegistry, ToolSpec, fail, ok
from .doc_tools import OVERCLAIM_MARKERS, dependencies_for_doc, guard_result as _guard_result

#: H 审校；G 需要看到发现才能修订（看不到发现的 G 无法闭环）；
#: F/D 需要知道哪些结论还带着未闭合的发现。
_ROLES = ("H", "G", "F", "D")

#: 写盘入口的角色。刻意只挂 H：写发现是审校者的本职，而不是让作者替审校者记账。
_WRITER_ROLES = ("H",)

#: 默认值哨兵（沿用 `agent_d._UNSPECIFIED` 的用法）：
#: 不传 = 「自己去库里读依赖」；显式传 `None` = 「调用方没有依赖清单 ⇒ 没查」。
#: 「没查」与「查了、依赖都闭合」必须能分开（FC-01 三态纪律）。
_UNSPECIFIED: Any = object()

#: H 自己负责的 `claimanatomy` code（`scan_document` 的循环里已有对应检查）。
#:
#: 为什么需要这张"跳过表"而不是把所有 code 都交给 claimanatomy：
#: H 的发现带 `target` 与 `evidence`，措辞已被既有测试逐字钉住
#: （`test_agent_h.py` 的 `assert "citations" in f["evidence"]` 一类）。
#: 若让 claimanatomy 的码同时进入，同一条缺陷会被报两遍、且两遍的措辞不同 ——
#: 那不是"更严格"，那是让审校报告变成噪音。跳过表让两边的分工显式：
#: H 负责它原生就有的六组检查，claimanatomy 负责 H 原先根本没有的那些
#: （生命周期、降级规则、冻结/勘误、未声明字段）。
_H_OWN_CODES = frozenset(
    {
        "missing_field",       # 引用/否定分类缺失 —— H 的循环里各有一条
        "empty_required",      # citations 空 / disclaimer 缺失 —— H 的循环里各有一条
        "bad_enum",            # evidence_kind / negation_kind 非法 —— H 的循环里各有一条
        "bad_type",            # citations 含空元素 —— H 的循环里有一条
        "inconsistent_status", # 过度声称（措辞）—— H 的循环里有一条
    }
)

#: `claimanatomy` 的 code 里，只有 H 才判的那些 → H 的 finding kind。
#: 不在表里的 code 落到 `garbled`（"表述无法解析"），并在 message 里带上 code，
#: 于是"哪条判据触发"永远可查。
_H_FINDING_KIND_OF_CA_CODE: dict[str, str] = {
    "undeclared_field": "scope_drift",
    "duplicate_claim_id": "inconsistent_number",
    "checker_error": "garbled",
}


# ---------------------------------------------------------------- 纯函数判据


def scan_document(
    doc: Mapping[str, Any],
    *,
    dependencies: Sequence[Mapping[str, Any]] | None = None,
) -> dict:
    """对一份稿件做全量机械审校。纯函数，不碰存储。

    检查项（每一项都可判定，且都给出 evidence）：

    - `unsupported_claim` —— 断言无引用；
    - `overclaim` —— `evidence_kind != "proof"` 却出现证明性措辞，或
      `cross_check` 缺 disclaimer；
    - `missing_negation_kind` —— 否定型断言未分类；
    - `dangling_dep` —— 该稿件登记的依赖里有 `dangling` / `external_unavailable` 的
      （这是 FC-23 的落地：引用了拿不到的定理，必须是一条可见的发现，而不是
      藏在引文角标里）；
    - `inconsistent_number` —— 同一份稿件里同一个 claim_key 出现互相矛盾的数字
      （当前版本只检查「同一 claim_id 重复出现且 text 不同」，这是可判定的那一层）。

    本函数不判断数学对不对。 它判的是「稿件有没有把自己说清楚」：
    有没有引用、证据等级有没有被夸大、依赖有没有闭合。把这两件事分清，
    是审校可被信任的前提 —— 一个声称「我检查了证明」的自动审校器是危险的。

    三态：`dependencies=None` ⇒ `dep_check.checked=False`（没查），
    与「查了、依赖都闭合」（`checked=True, findings=[]`）严格区分。

    `verdict` 的受控词与分档顺序（必须与写入路径 `review_document` 完全一致）：

    | 条件 | verdict |
    |---|---|
    | 有 error 级发现 | `rejected` |
    | 无 error，但 `dep_check.checked is False` | `unverified`（不是 accepted） |
    | 无 error、依赖查过、有 warning | `accepted_with_warnings` |
    | 无 error、依赖查过、无 warning | `accepted` |

    为什么"没查依赖"要单独占一档：把它并进 `accepted` 会让"我们从未检查"
    伪装成"检查通过"；并进 `rejected` 又会把"没做"说成"做失败了"。
    """
    findings: list[dict] = []
    doc_id = str(doc.get("doc_id") or "?")
    claims = doc.get("claims") or []

    seen_ids: dict[str, str] = {}
    for i, c in enumerate(claims):
        if not isinstance(c, Mapping):
            findings.append(
                {
                    "kind": "garbled",
                    "level": "error",
                    "target": f"claims[{i}]",
                    "evidence": f"claims[{i}] 的类型是 {type(c).__name__}，不是对象",
                    "message": "断言必须是对象",
                }
            )
            continue
        cid = str(c.get("claim_id") or f"claims[{i}]")
        text = str(c.get("text") or "")
        cites = c.get("citations") or []
        ek = c.get("evidence_kind")

        # ---- 无引用
        if not cites:
            findings.append(
                {
                    "kind": "unsupported_claim",
                    "level": "error",
                    "target": cid,
                    "evidence": f"claim_id={cid} 的 citations={cites!r}（空）",
                    "message": "断言没有引用：数学断言的价值取决于它来自哪里",
                }
            )
        else:
            # 与 `doc_tools.scan_claim:205-214` 对齐：空元素/非字符串等于没有引用，
            # 但 `if not cites` 看不出来（[""] 是非空列表）。这条曾经只在 G 侧有。
            bad_cites = [x for x in cites if not isinstance(x, str) or not x.strip()]
            if bad_cites:
                findings.append(
                    {
                        "kind": "garbled",
                        "level": "error",
                        "target": cid,
                        "evidence": f"claim_id={cid} 的 citations={cites!r} 含空/非字符串元素：{bad_cites!r}",
                        "message": "引用里有空元素：空引用等于没有引用",
                    }
                )
        # ---- 证据等级是否合法（与 `doc_tools.scan_claim:217-224` 对齐）
        #
        # 这一条曾经只有 G 侧有：H 遇到非法的 `evidence_kind` 时会因为
        # `ek in S.EVIDENCE_KINDS` 这个守卫而直接跳过下面两组检查，
        # 于是一条把 evidence_kind 写成 "prooof" 的断言在 H 眼里是干净的。
        if ek not in S.EVIDENCE_KINDS:
            findings.append(
                {
                    "kind": "garbled",
                    "level": "error",
                    "target": cid,
                    "evidence": f"claim_id={cid} 的 evidence_kind={ek!r} 不在 {S.EVIDENCE_KINDS} 里",
                    "message": f"证据等级必须是 {S.EVIDENCE_KINDS} 之一",
                }
            )
        # ---- 过度声称
        if ek == "cross_check" and not str(c.get("disclaimer") or "").strip():
            findings.append(
                {
                    "kind": "overclaim",
                    "level": "error",
                    "target": cid,
                    "evidence": f"evidence_kind={ek!r} 且 disclaimer 为空",
                    "message": "数值交叉验证必须显式声明'不构成证明'",
                }
            )
        if ek in S.EVIDENCE_KINDS and ek != "proof":
            hit = [m for m in OVERCLAIM_MARKERS if m in text]
            if hit:
                findings.append(
                    {
                        "kind": "overclaim",
                        "level": "error",
                        "target": cid,
                        "evidence": f"evidence_kind={ek!r} 但正文含 {'、'.join(hit)}；正文摘要：{text[:80]!r}",
                        "message": "把交叉验证写成了证明",
                    }
                )
        # ---- 否定分类
        #
        # 证据里必须写出字段名与它的实际值：G 侧的同一条检查
        # （`claimanatomy` 的 2c 节）也把字段名写在 evidence 里，两边逐字对得上
        # 才可能被判据对照用例双向核对（`test_scan_document_checks_match_scan_claim_both_ways`）。
        if c.get("is_negative") is True and not c.get("negation_kind"):
            findings.append(
                {
                    "kind": "missing_negation_kind",
                    "level": "error",
                    "target": cid,
                    "evidence": (
                        f"is_negative=True 且 negation_kind={c.get('negation_kind')!r}"
                        "（字段 `negation_kind` 缺失/为空）"
                    ),
                    "message": "'未证明'与'已证否'必须分开",
                }
            )
        # ---- 与 G 侧判据对齐的两条
        #
        # "非否定断言却带了 negation_kind" 这条必须与 G 同级别（error）：
        # G 侧（`doc_tools.scan_claim` → `claimanatomy` 的 `bad_enum`）把它判成
        # `garbled/error`，而 H 侧此前判 `warning` —— 于是H 比 G 松：
        # G 拒绝的稿件在 H 那里照样通过（"G 认为违规、H 认为通过"的静默分裂，
        # 正是 INVENTORY 4.5#10 点名的那一类）。两边不一致时以更严的一侧为准：
        # 一条同时声称"不是否定型"又带否定分类的断言，它的否定计数一定是错的，
        # 那不是"提醒一下"就能放过的。
        if c.get("is_negative") is not True and c.get("negation_kind") is not None:
            findings.append(
                {
                    "kind": "garbled",
                    "level": "error",
                    "target": cid,
                    "evidence": (
                        f"is_negative={c.get('is_negative')!r}（不是否定型）"
                        f"却带了 negation_kind={c.get('negation_kind')!r}"
                    ),
                    "message": "非否定型断言带了否定分类：两轴矛盾，否定计数必然虚高",
                }
            )
        if c.get("negation_kind") is not None and c.get("negation_kind") not in S.NEGATION_KINDS:
            findings.append(
                {
                    "kind": "missing_negation_kind",
                    "level": "error",
                    "target": cid,
                    "evidence": (
                        f"claim_id={cid} 的 negation_kind={c.get('negation_kind')!r} "
                        f"不在 {S.NEGATION_KINDS} 里"
                    ),
                    "message": f"否定分类必须是 {S.NEGATION_KINDS} 之一",
                }
            )
        # ---- 重复 claim_id 且文本不同（可判定的"自相矛盾"）
        if cid in seen_ids and seen_ids[cid] != text:
            findings.append(
                {
                    "kind": "inconsistent_number",
                    "level": "error",
                    "target": cid,
                    "evidence": f"同一 claim_id={cid} 出现两次且 text 不同：{seen_ids[cid][:60]!r} vs {text[:60]!r}",
                    "message": "同一断言标识对应两段不同文字",
                }
            )
        seen_ids[cid] = text

    # ---- 生命周期与降级（`claimanatomy` 的判据，H 侧此前完全没有）
    #
    # 这一段是本轮新增的能力：`status`（生命周期轴）与 `allowed_use`（降级规则）
    # 是 `draft/17` §8.3 的两个字段，本框架此前表达不了"这条断言已作废"。
    # 判据不在这里重写 —— 它来自 `claimanatomy.validate_claim`，
    # 本段只做"翻译成 H 的 finding 形状"。
    #
    # 去重规则（避免同一条缺陷报两遍、且两边级别不同）：
    # `_H_OWN_CODES` 列出的 code 由上面 H 自己的循环负责（它带 H 要的
    # `target`/`evidence` 措辞，且已有测试逐字钉住），这里跳过。
    for i, c in enumerate(claims):
        if not isinstance(c, Mapping):
            continue
        spec = CA.validate_claim(c)
        fallback_cid = str(c.get("claim_id") or f"claims[{i}]")
        for issue in spec.issues:
            if issue.code in _H_OWN_CODES:
                continue
            if issue.level == "info":
                # 三态第三态不进发现表：`unknown_status_axis`（"这条断言
                # 没有 `status` 字段 ⇒ 生命周期轴判不了"）是数据质量信息，
                # 不是一条要 G 去改的缺陷。把它塞进 `review_findings` 会让
                # "干净稿件 = 0 条发现"这条判据永远不成立 —— 而那条判据是
                # 防误伤的基线（`test_review_accepts_a_clean_document`）。
                # 它由 `claimanatomy.ClaimSpec.decided=False` + `undecided_reason`
                # 单独表达，并由 `gates` 的门（G9/G10）如实登记"判不了"。
                continue
            findings.append(
                {
                    "kind": _H_FINDING_KIND_OF_CA_CODE.get(issue.code, "garbled"),
                    "level": issue.level,
                    "target": issue.claim_id if issue.claim_id not in ("", "?") else fallback_cid,
                    "evidence": f"字段 `{issue.field_name}`：{issue.evidence}",
                    "message": f"{issue.message}（判据出处：claimanatomy，code={issue.code}）",
                }
            )

    # ---- 依赖闭合（FC-23）
    if dependencies is None:
        dep_check = {
            "checked": False,
            "reason": "调用方未提供 dependencies ⇒ **没查依赖闭合**（不得读成'依赖都闭合'）",
            "open": [],
        }
    else:
        open_deps = [
            {
                "dep_id": str(d.get("dep_id") or ""),
                "status": str(d.get("status") or ""),
                "label": str(d.get("label") or ""),
                "status_reason": str(d.get("status_reason") or ""),
            }
            for d in dependencies
            if str(d.get("status") or "") in ("dangling", "external_unavailable")
        ]
        for d in open_deps:
            # 分级（FC-13）：`external_unavailable` 是"我们已经知道并记录了这个前提
            # 拿不到" —— 那是已知边界，不是谎报，所以是 warning。
            # 而 `dangling` 是"登记了一个依赖却既没闭合、也没说明为什么拿不到" —— 那是
            # 没交代，属于 error。把两者都报成 error 会把红灯训练成噪音。
            lvl = "warning" if d["status"] == "external_unavailable" else "error"
            findings.append(
                {
                    "kind": "dangling_dep",
                    "level": lvl,
                    "target": d["dep_id"],
                    "evidence": (
                        f"dep_id={d['dep_id']} status={d['status']!r} label={d['label']!r}；"
                        f"status_reason={d['status_reason'][:120]!r}"
                    ),
                    "message": (
                        "引用了外部结论但本项目拿不到来源（已知边界，需人确认前提）"
                        if d["status"] == "external_unavailable"
                        else "依赖悬空且没有说明原因"
                    ),
                }
            )
        dep_check = {"checked": True, "reason": f"检查了 {len(list(dependencies))} 条依赖", "open": open_deps}

    errors = [f for f in findings if f["level"] == "error"]
    warnings = [f for f in findings if f["level"] == "warning"]
    dep_checked = bool(dep_check.get("checked"))

    # ---- FC-10：三分档计数，禁止单一通过率。
    # "通过率 80%" 会掩盖"20% 是失败还是未检查"这个决定性差异。
    #
    # `verdict` 必须读 `dep_check["checked"]`（这是本函数曾经的真实缺陷）：
    # 只按 error/warning 分档时，`dependencies=None`（"调用方没给清单 ⇒ 没查"）
    # 会在同一个返回值里出现 `dep_check` 说"没查"、`verdict` 说"accepted" ——
    # 只看 `verdict` 或 `res.ok` 的调用方（AgentH、verify）就会把"依赖闭合从未检查"
    # 读成"稿件通过"。写入路径 `review_document` 从来不许这件事（见 `:429-438`），
    # 只读路径与它必须是同一口径 —— 否则审校的两个入口会对同一份稿件给出
    # 两个都"没有报错"的相反结论。
    #
    # 分档顺序：error 最重（有错就是 rejected，无论依赖查没查），
    # 其次"没查"（unverified —— 既不是通过也不是不通过），最后才是 warning/干净。
    if errors:
        verdict = "rejected"
    elif not dep_checked:
        verdict = "unverified"
    elif warnings:
        verdict = "accepted_with_warnings"
    else:
        verdict = "accepted"

    reason = (
        f"机械检查 error={len(errors)}、warning={len(warnings)}、info={len(findings) - len(errors) - len(warnings)}；"
        + (
            f"依赖闭合已检查（{dep_check.get('reason')}）"
            if dep_checked
            else f"依赖闭合**没查**（{dep_check.get('reason')}）⇒ 不能判 accepted"
        )
    )
    return {
        "checked": True,
        "doc_id": doc_id,
        "findings": findings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "info_count": len(findings) - len(errors) - len(warnings),
        "dep_check": dep_check,
        "verdict": verdict,
        # `reason` 与 verdict 必须一起给：只给一个受控词，调用方看不出
        # "unverified" 到底是"没查依赖"还是"还缺别的输入"。
        "reason": reason,
    }


# ---------------------------------------------------------------- 内部工具


def _doc_of(store: Any, doc_id: str) -> dict:
    row = next((r for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)), None)
    if row is None:
        raise ValueError(f"稿件 {doc_id} 不存在（documents 表里没有这一行）⇒ 不能审一份不存在的稿件")
    return dict(row)


def _resolve_deps(store: Any, doc_id: str, dependencies: Any) -> tuple[Any, bool]:
    """把 `dependencies` 参数解析成 (传给 scan_document 的值, 是否查过)。

    哨兵 / 显式 None 的区别就是三态纪律本身：
    「我自己去库里读了」（查过）与「调用方没给清单」（没查）不能混。
    """
    if dependencies is _UNSPECIFIED:
        return dependencies_for_doc(store.rows("dependencies"), doc_id), True
    if dependencies is None:
        return None, False
    return [dict(d) for d in dependencies], True


def _set_doc_status(store: Any, doc_id: str, target: str, *, actor: str) -> tuple[bool, str | None, str]:
    """只改 `documents` 行的 `status` 字段。返回 (是否写成, 错误, 当前状态)。

    ## 为什么只改 status，连 `updated_at` 都不碰

    "H 只读"必须有一个可核对的形式：调用前后逐字节比对 `documents.json`，
    变化点应当有且只有 status。顺手更新 `updated_at` 看起来无害，
    但它会让"H 到底动了什么"从"一眼看清"退化成"要逐字段 diff 才知道"。

    ## 为什么这个写会失败（而且必须如实报告）

    `Document.validate` 会在提交时校验整张 documents 表。若盘上这份稿件
    本身不合 schema（例如是手工改坏的、或旧版本写的），那么连"把它的状态改成
    in_review"都写不进去。这不是可以掩盖的细节：发现照样落库，状态更新失败
    这件事本身也要出现在返回值里，否则调用方会以为"审校流程正常结束了"。
    """
    cur = next(
        (str(r.get("status")) for r in store.rows("documents") if str(r.get("doc_id")) == str(doc_id)),
        "",
    )
    if cur == target:
        return True, None, cur
    try:
        with store.tx("documents", actor=actor, note=f"review status {cur}->{target}") as tx:
            row = tx.find("documents", doc_id=str(doc_id))
            if row is None:
                return False, f"稿件 {doc_id} 在事务内不存在", cur
            row["status"] = target
            tx.upsert("documents", row)
    except Exception as e:  # noqa: BLE001 - 见 docstring：失败必须被记录，不能被吞掉或上抛
        return False, f"{type(e).__name__}: {e}", cur
    return True, None, target


def _apply_finding_status(
    store: Any, changes: Sequence[Mapping[str, Any]], *, actor: str, note: str
) -> list[dict]:
    """批量改 finding 的 `status`（以及必要时补 `resolution_note`）。

    只允许改这两个字段：finding 的 `kind/level/target/evidence/message` 是
    H 当初的判断依据，重算时不许被改写 —— 否则"当初为什么这么判"就没有了。
    """
    done: list[dict] = []
    if not changes:
        return done
    with store.tx("review_findings", actor=actor, note=note) as tx:
        for ch in changes:
            row = tx.find("review_findings", finding_id=str(ch["finding_id"]))
            if row is None:
                continue
            if row.get("status") == ch["status"]:
                continue
            row["status"] = ch["status"]
            if ch.get("resolution_note"):
                row["resolution_note"] = str(ch["resolution_note"])
            tx.upsert("review_findings", row)
            done.append({"finding_id": row["finding_id"], "status": row["status"]})
    return done


def _dedup_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """去重键：`(kind, target, message)`（doc_id 在调用处限定）。"""
    return (str(row.get("kind")), str(row.get("target")), str(row.get("message")))


# ---------------------------------------------------------------- 审校（写发现）


def review_document(
    store: Any,
    doc_id: str,
    *,
    round_no: int | None = None,
    dependencies: Any = _UNSPECIFIED,
    actor: str = "agent-H",
) -> dict:
    """审一份稿件：把机械发现落成 `ReviewFinding` 行，并更新 `documents.status`。

    返回 ``{"doc_id","checked","round","new_findings","duplicate_skipped","reopened",
    "error_count","warning_count","info_count","dep_check","status","status_updated",
    "status_error","verdict","reason"}``。

    ## 三段式（为什么是三个事务而不是一个）

    1. 落发现（`review_findings`）：发现是审校的产出，必须落库 ——
       "发现了但没记下来"等于没发现。
    2. 重开谎报（`review_findings`）：G 把一条 finding 标成 `fixed` 之后，
       如果重跑检查仍然复现，这条 finding 会被重新打开。没有这一步，
       G 只要点一下"已修复"，审校就只看状态、成了盖章机。
    3. 改状态（`documents`，独立事务）：稿件可能本身不合 schema，
       于是这一步会失败。把它与落发现分开，失败时才不会连发现一起丢掉。

    ## 三态：`dependencies` 没查 ⇒ 不许判 accepted

    `dep_check.checked is False` 时 verdict 是 `"unverified"`，文档状态停在
    `in_review` —— 「依赖都闭合」这句话在没有查过的情况下不许说出口。
    """
    doc_id = str(doc_id)
    doc = _doc_of(store, doc_id)
    deps, _dep_provided = _resolve_deps(store, doc_id, dependencies)
    scan = scan_document(doc, dependencies=deps)

    existing = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]
    if round_no is None:
        # 轮次从"该稿件已有发现的最大轮次"往后走 —— 用库里的既有事实推，
        # 而不是用一个内存计数器：审校必须能被中断后接着跑。
        round_no = max((int(r.get("round") or 1) for r in existing), default=0) + 1
    round_no = int(round_no)
    if round_no < 1:
        raise ValueError("round_no 从 1 开始")

    seen = {_dedup_key(r) for r in existing}
    pending: list[dict] = []
    duplicate_skipped = 0
    for f in scan["findings"]:
        key = _dedup_key(f)
        if key in seen:
            duplicate_skipped += 1
            continue
        seen.add(key)
        pending.append(f)

    new_findings: list[dict] = []
    if pending:
        with store.tx(
            "review_findings", actor=actor, note=f"review_document doc:{doc_id} round {round_no}"
        ) as tx:
            for f in pending:
                row = S.ReviewFinding(
                    finding_id="",
                    doc_id=doc_id,
                    kind=str(f["kind"]),
                    level=str(f["level"]),
                    target=str(f["target"]),
                    # evidence 由 scan_document 给出（触发该发现的实际值）。
                    # 它绝不会是空的：schema.ReviewFinding.validate 会拒绝空 evidence，
                    # 这里也再核一次，让错误带上"是哪条检查没给证据"。
                    evidence=str(f["evidence"]),
                    message=str(f["message"]),
                    round=round_no,
                    suggestion=str(f.get("suggestion") or ""),
                    status="open",
                    resolution_note="",
                    created_at=S.now_iso(),
                    created_by=actor,
                )
                row.finding_id = tx.alloc_id("finding")
                row.validate()
                payload = row.to_dict()
                tx.upsert("review_findings", payload)
                new_findings.append(payload)

    # ---- 重开"标了 fixed 但其实还在"的发现（防止 G 用点状态的方式修好问题）
    current_keys = {_dedup_key(f) for f in scan["findings"]}
    reopened: list[dict] = []
    to_reopen = [
        r
        for r in existing
        if str(r.get("status")) == "fixed" and _dedup_key(r) in current_keys
    ]
    if to_reopen:
        _apply_finding_status(
            store,
            [
                {
                    "finding_id": r["finding_id"],
                    "status": "open",
                    "resolution_note": (
                        f"[round {round_no}] 重跑对应检查**仍然复现** ⇒ 之前的 fixed 不成立，重新打开"
                    ),
                }
                for r in to_reopen
            ],
            actor=actor,
            note=f"reopen doc:{doc_id}",
        )
        reopened = [{"finding_id": r["finding_id"], "kind": r.get("kind"), "target": r.get("target")} for r in to_reopen]

    dep_checked = bool(scan["dep_check"].get("checked"))
    if scan["error_count"]:
        verdict = "rejected"
    elif not dep_checked:
        # 「依赖闭合没查」不等于「依赖闭合」—— 不许在这个前提下判 accepted。
        verdict = "unverified"
    elif scan["warning_count"]:
        verdict = "accepted_with_warnings"
    else:
        verdict = "accepted"

    target_status = "accepted" if (scan["error_count"] == 0 and dep_checked) else "in_review"
    status_updated, status_error, status_now = _set_doc_status(store, doc_id, target_status, actor=actor)

    reason_bits = [
        f"机械检查发现 error={scan['error_count']}、warning={scan['warning_count']}、info={scan['info_count']}",
        (
            f"依赖闭合已检查（{scan['dep_check'].get('reason')}）"
            if dep_checked
            else f"依赖闭合**没查**（{scan['dep_check'].get('reason')}）⇒ 不能判 accepted"
        ),
        f"新增发现 {len(new_findings)} 条、与已有发现重复被跳过 {duplicate_skipped} 条",
    ]
    if reopened:
        reason_bits.append(f"重开 {len(reopened)} 条「标了 fixed 但重跑仍复现」的发现")
    if not status_updated:
        reason_bits.append(f"⚠️ 文档状态**未能更新**（{status_error}）—— 这通常因为盘上这份稿件本身不合 schema")

    return {
        "doc_id": doc_id,
        "checked": True,
        "round": round_no,
        "new_findings": new_findings,
        "duplicate_skipped": duplicate_skipped,
        "reopened": reopened,
        "error_count": scan["error_count"],
        "warning_count": scan["warning_count"],
        "info_count": scan["info_count"],
        "dep_check": scan["dep_check"],
        "status": status_now,
        "status_updated": status_updated,
        "status_error": status_error,
        "verdict": verdict,
        "reason": "；".join(reason_bits) + "。",
    }


# ---------------------------------------------------------------- 复审（判 fixed / open）


def verify_fixes(
    store: Any,
    doc_id: str,
    *,
    round_no: int,
    dependencies: Any = _UNSPECIFIED,
    max_review_rounds: int = 2,
    actor: str = "agent-H",
) -> dict:
    """复审：对上一轮的每条 finding 重跑对应检查，判定 `fixed` / 仍 `open`。

    返回 ``{"doc_id","round","resolved","still_open","unresolved_findings","verdict",
    "reason",...}``。

    ## 终止性（FC-18 的同族要求）

    `error` 级发现一直不修、且已经到 `max_review_rounds` ⇒ 文档状态置
    `unresolved_review`，并且必须把未解决的 finding 明确列出来
    （`unresolved_findings` 非空）。「跑了 N 轮还是红」如果只体现在一个状态字符串上，
    接手的人就无从知道到底卡在哪一条 —— 不许隐藏。

    ## 判定口径

    判据不是 G 自称修好了，而是"重跑检查还复现吗"：
    复现 ⇒ `open`（即使 G 已经把它标成 `fixed`，也会被重新打开）；
    不复现 ⇒ `fixed`。此外当前扫描里新出现的问题会以 `source="new_issue"`
    出现在 `still_open` 里（复审不是"只看旧账"）。
    """
    doc_id = str(doc_id)
    round_no = int(round_no)
    if round_no < 1:
        raise ValueError("round_no 从 1 开始")
    max_review_rounds = int(max_review_rounds)
    if max_review_rounds < 1:
        raise ValueError("max_review_rounds 至少为 1")

    doc = _doc_of(store, doc_id)
    deps, dep_checked = _resolve_deps(store, doc_id, dependencies)
    scan = scan_document(doc, dependencies=deps)
    current = {_dedup_key(f): f for f in scan["findings"]}
    findings = [dict(r) for r in store.rows("review_findings") if str(r.get("doc_id")) == doc_id]
    prev = [r for r in findings if int(r.get("round") or 1) < round_no]

    resolved: list[dict] = []
    still_open: list[dict] = []
    for r in prev:
        base = {
            "finding_id": r.get("finding_id"),
            "kind": r.get("kind"),
            "level": r.get("level"),
            "target": r.get("target"),
            "message": r.get("message"),
            "round": r.get("round"),
            "status": r.get("status"),
        }
        key = _dedup_key(r)
        if key in current:
            base["evidence"] = current[key].get("evidence")
            base["source"] = "prev_round"
            still_open.append(base)
        else:
            resolved.append(base)
    prev_keys = {_dedup_key(r) for r in prev}
    for key, f in current.items():
        if key in prev_keys:
            continue
        still_open.append(
            {
                "finding_id": None,
                "kind": f["kind"],
                "level": f["level"],
                "target": f["target"],
                "message": f["message"],
                "evidence": f.get("evidence"),
                "round": None,
                "status": "open",
                "source": "new_issue",
            }
        )

    # ---- 落状态：resolved ⇒ fixed；复现的旧账 ⇒ 重新打开（含"谎报修好")
    changes: list[dict] = []
    for item in resolved:
        changes.append(
            {
                "finding_id": item["finding_id"],
                "status": "fixed",
                "resolution_note": f"[round {round_no}] 重跑对应检查不再复现 ⇒ fixed",
            }
        )
    for item in still_open:
        if item.get("source") != "prev_round":
            continue
        if str(item.get("status")) != "fixed":
            continue
        changes.append(
            {
                "finding_id": item["finding_id"],
                "status": "open",
                "resolution_note": (
                    f"[round {round_no}] G 曾标为 fixed，但重跑对应检查**仍然复现** ⇒ 判定不成立，重新打开"
                ),
            }
        )
        item["status"] = "open"
        item["reopened"] = True
    finding_updates = _apply_finding_status(
        store, changes, actor=actor, note=f"verify_fixes doc:{doc_id} round {round_no}"
    )

    # ---- 判定（用"当前仍存在的 error"作准，而不是用 G 的自述）
    blocking = [
        f for f in still_open if str(f.get("level")) == "error" and str(f.get("status")) in ("open", "fixed")
    ]
    if not still_open:
        verdict = "accepted"
    elif blocking and round_no >= max_review_rounds:
        verdict = "unresolved_review"
    elif blocking:
        verdict = "revise_again"
    else:
        # 只剩 warning（已记录的已知边界）或已被人明确 wontfix 的项：
        # 它们仍然列在 still_open 里（不许隐藏），但不该把红灯训练成噪音（FC-13）。
        verdict = "accepted"

    target_status = {"accepted": "accepted", "revise_again": "in_review", "unresolved_review": "unresolved_review"}[
        verdict
    ]
    status_updated, status_error, status_now = _set_doc_status(store, doc_id, target_status, actor=actor)

    unresolved = [f for f in blocking]
    reason_bits = [
        f"第 {round_no} 轮复审（上限 max_review_rounds={max_review_rounds}）："
        f"上一轮 {len(prev)} 条发现里 resolved={len(resolved)}、仍复现={len(still_open) - len([f for f in still_open if f.get('source') == 'new_issue'])}",
        f"error 级未解决 {len(unresolved)} 条",
    ]
    if not dep_checked:
        reason_bits.append("⚠️ 依赖闭合**没查**（dependencies=None）⇒ 本轮结论不覆盖依赖闭合这一维")
    if verdict == "unresolved_review":
        reason_bits.append(
            "已达轮数上限且 error 级发现仍 open ⇒ 停止自动修订，交人复核（**未解决的发现已全部列出**，未隐藏）"
        )
    if not status_updated:
        reason_bits.append(f"⚠️ 文档状态**未能更新**（{status_error}）")

    return {
        "doc_id": doc_id,
        "round": round_no,
        "resolved": resolved,
        "still_open": still_open,
        "unresolved_findings": unresolved,
        "verdict": verdict,
        "reason": "；".join(reason_bits) + "。",
        "error_count": scan["error_count"],
        "warning_count": scan["warning_count"],
        "info_count": scan["info_count"],
        "dep_check": scan["dep_check"],
        "finding_updates": finding_updates,
        "status": status_now,
        "status_updated": status_updated,
        "status_error": status_error,
    }


# ---------------------------------------------------------------- 只读列举


def list_findings(
    store: Any,
    *,
    doc_id: str | None = None,
    status: str | None = None,
    level: str | None = None,
) -> dict:
    """只读列举审校发现。"""
    if status is not None and status not in S.FINDING_STATUSES:
        raise ValueError(f"status 必须是 {S.FINDING_STATUSES} 之一，收到 {status!r}")
    if level is not None and level not in S.FINDING_LEVELS:
        raise ValueError(f"level 必须是 {S.FINDING_LEVELS} 之一，收到 {level!r}")
    out: list[dict] = []
    for r in sorted(store.rows("review_findings"), key=lambda x: str(x.get("finding_id"))):
        if doc_id is not None and str(r.get("doc_id")) != str(doc_id):
            continue
        if status is not None and r.get("status") != status:
            continue
        if level is not None and r.get("level") != level:
            continue
        out.append(
            {
                "finding_id": r.get("finding_id"),
                "doc_id": r.get("doc_id"),
                "kind": r.get("kind"),
                "level": r.get("level"),
                "target": r.get("target"),
                "message": r.get("message"),
                "evidence": r.get("evidence"),
                "status": r.get("status"),
                "round": r.get("round"),
                "resolution_note": r.get("resolution_note"),
            }
        )
    return {"count": len(out), "findings": out}


# ---------------------------------------------------------------- 审校报告（G1–G15）

#: 审校报告默认落点（相对工作区）。沿用 `draft/17` §8.1 的目录树建议：
#: 报告与稿件分开放，且按被审对象命名，于是"这份报告审的是哪一版"靠文件名
#: 就能对上 —— 再加上报告头里的内容 hash，"行号失效"这件事才不可能悄悄发生。
DEFAULT_REPORT_SUBDIR = "reports"


def review_report(
    store: Any,
    doc_id: str,
    *,
    own_errors: Sequence[str] | None,
    out_path: Any = None,
    dependencies: Any = _UNSPECIFIED,
    run_evidence: Mapping[str, Any] | None = None,
    banned_words: Sequence[str] | None = None,
    claim_counts: Mapping[str, Any] | None = None,
    workspace_root: Any = None,    actor: str = "agent-H",
    round_no: int = 1,
) -> dict:
    """产出 G1–G15 的完整审校报告（markdown 落盘）—— §8.4 的落地入口。

    ## 三件被结构强制的事（缺一件就抛，见 `gates.gate_report`）

    1. 钉住被审版本 hash（G11）：报告头写 `revision_hash`
       （`claimanatomy.revision_hash`，算法逐字写进报告）。
    2. 『我这一轮犯的错』一节（G15）：`own_errors` 是必填参数；
       `None` ⇒ 抛（"没写"不等于"没犯错"），`[]` ⇒ 合法（显式声明零错误）。
    3. 零发现自证（G13）：每道报"零发现"的门都必须带"我用了什么过程、
       数出了什么数字" —— 由 `gates.GateResult` 的构造期校验保证，
       G13 再独立复核一遍。

    ## 它写哪里、写什么

    只写一个 markdown 文件（默认 `<workspace>/reports/<doc_id>-review.md`），
    不碰任何数据表、不碰 `claims`。这是 `AgentH` 落库代理的一个入口，
    因此它属于"能被显式拒绝的写工具"那一类（`include_writers=True` 才装配）。

    三态：`dependencies` 省略 = 从库里读该稿件的依赖（查过）；
    显式 `None` = 没查（`dep_check.checked=False`）。
    """
    if own_errors is None:
        raise ValueError(
            "审校报告必须包含『我这一轮犯的错』一节（`own_errors` 必填）。"
            "传空列表表示『本轮零自身错误』，但**必须由调用方显式写出来** —— "
            "若允许『没写』等于『没犯错』，这一节就会永远空着（§8.4 G15：缺失则退回）"
        )
    doc = _doc_of(store, doc_id)
    deps, deps_checked = _resolve_deps(store, str(doc_id), dependencies)

    root = Path(workspace_root).resolve() if workspace_root else Path(store.root).resolve()
    # 显式给了 `out_path` 就核边界（越界一律拒绝，不是"写到外面再警告"）；
    # 没给就用默认落点。`resolve()` 之后再 `relative_to()` 判断，
    # 而不是靠字符串 `..` 检查 —— 后者会被符号链接绕过。
    raw = str(out_path) if out_path else f"{DEFAULT_REPORT_SUBDIR}/{doc_id}-review.md"
    target = Path(raw)
    absolute = target if target.is_absolute() else (root / target)
    absolute = absolute.resolve()
    try:
        rel = absolute.relative_to(root)
    except ValueError as e:
        raise ValueError(
            f"审校报告的 out_path 越界：{raw!r} 不在工作区 {root} 内（{type(e).__name__}）。"
            "报告只允许写在工作区里 —— 这是沙箱边界，不是建议"
        ) from e

    ctx = G.GateContext.build(
        doc,
        dependencies=deps if deps_checked else None,
        files=None,
        workspace_root=root,
        run_evidence=run_evidence,
        findings=list(store.rows("review_findings")) if store is not None else None,
        claim_counts=claim_counts,
        banned_words=banned_words,
        own_errors=list(own_errors),
    )
    report = G.gate_report(ctx, own_errors=list(own_errors), reviewer=actor, round_no=round_no)
    markdown = G.render_review_report(report)
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_text(markdown, encoding="utf-8")
    return {
        "doc_id": str(doc_id),
        "round": int(round_no),
        "report_path": str(rel).replace("\\", "/"),
        "revision_hash": report["revision_hash"],
        "verdict": report["verdict"]["verdict"],
        "gates_total": report["gates_total"],
        "pass_count": report["verdict"]["pass"],
        "fail_count": report["verdict"]["fail"],
        "unknown_count": report["verdict"]["unknown"],
        "not_applicable_count": report["verdict"]["not_applicable"],
        "failed_gates": list(report["verdict"]["failed_gates"]),
        "unknown_gates": list(report["verdict"]["unknown_gates"]),
        "own_error_count": len(list(own_errors)),
        "markdown": markdown,
    }


# ---------------------------------------------------------------- 工具装配


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    include_writers: bool = False,
    actor: str = "agent-H",
    **_: Any,
) -> None:
    """装配审校工具。

    ## 为什么写工具默认不注册

    「H 的工具面必须全部 `side_effect in ("none","read")`」是结构约束，不是口号。
    默认注册面只有 `review.scan_document`（`none`）与 `review.list_findings`（`read`）；
    会写盘的两个入口必须由调用方显式 `include_writers=True` 才装配
    （`AgentH` 用它构造自己的"落库代理"，与它的自由工具箱分开）。
    默认把写工具塞进来，就等于承认这个约束只是写在文档里的愿望。
    """
    def _not_wired(**__: Any) -> Any:
        """未接线时显式失败（FC-08）：返回"没查"，绝不返回"没有发现"的空结果。"""
        return fail(
            "review 工具未接线（装配时未提供 store）⇒ **没查**，不是『没有发现』",
            kind="not_wired",
        )

    registry.register(
        ToolSpec(
            name="review.scan_document",
            summary="对一份稿件做全量机械审校（引用/证据等级/否定分类/依赖闭合），每条发现都带 evidence",
            params={
                "type": "object",
                "properties": {
                    "doc": {"type": "object"},
                    "dependencies": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["doc"],
                "additionalProperties": False,
            },
            # 省略 `dependencies` ⇒ 显式传 `None` ⇒ `dep_check.checked=False`，
            # 于是 `verdict` 是 `unverified`（不是 accepted）。
            # 这个工具没接 store（`side_effect="none"` 的只读工具不该去抢锁），
            # 因此"自己去库里读依赖"这条路径只在 `review_document` 里存在。
            handler=lambda doc, dependencies=_UNSPECIFIED: ok(
                scan_document(doc, dependencies=None if dependencies is _UNSPECIFIED else dependencies)
            ),
            side_effect="none",
            roles=_ROLES,
            returns=(
                "{'checked','doc_id','findings','error_count','warning_count','info_count',"
                "'dep_check','verdict','reason'}；verdict ∈ {rejected, unverified, "
                "accepted_with_warnings, accepted}，dep_check.checked=False 时**必为** unverified"
            ),
            tags=("review", "gate"),
        )
    )

    registry.register(
        ToolSpec(
            name="review.list_findings",
            summary="只读列举审校发现（可按稿件/状态/级别过滤），含每条发现的 evidence",
            params={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "status": {"type": "string", "enum": list(S.FINDING_STATUSES)},
                    "level": {"type": "string", "enum": list(S.FINDING_LEVELS)},
                },
                "additionalProperties": False,
            },
            handler=lambda doc_id=None, status=None, level=None: (
                _not_wired()
                if store is None
                else _guard_result(lambda: list_findings(store, doc_id=doc_id, status=status, level=level))
            ),
            side_effect="read",
            roles=_ROLES,
            returns="{'count','findings':[{'finding_id','doc_id','kind','level','target','message','evidence','status'}]}",
            tags=("review", "read"),
        )
    )

    if not include_writers:
        # 默认面到此为止：全部 none/read。写入口需要显式打开。
        return

    registry.register(
        ToolSpec(
            name="review.review_document",
            summary=(
                "审一份稿件：把机械发现落成 ReviewFinding（每条带 evidence），并更新文档状态；"
                "只写 review_findings 与 documents.status，不改 claims"
            ),
            params={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "round_no": {"type": "integer", "minimum": 1},
                    "dependencies": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["doc_id"],
                "additionalProperties": False,
            },
            handler=lambda **kw: (
                _not_wired()
                if store is None
                else _guard_result(lambda: review_document(store, actor=actor, **kw))
            ),
            side_effect="write_local",
            roles=_WRITER_ROLES,
            returns="{'doc_id','new_findings','duplicate_skipped','error_count','warning_count','verdict','status'}",
            tags=("review", "write"),
        )
    )

    registry.register(
        ToolSpec(
            name="review.verify_fixes",
            summary=(
                "复审：对上一轮每条 finding 重跑对应检查，判 fixed / 仍 open；"
                "到 max_review_rounds 仍红则置 unresolved_review 并**列出**未解决项"
            ),
            params={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "round_no": {"type": "integer", "minimum": 1},
                    "dependencies": {"type": "array", "items": {"type": "object"}},
                    "max_review_rounds": {"type": "integer", "minimum": 1},
                },
                "required": ["doc_id", "round_no"],
                "additionalProperties": False,
            },
            handler=lambda **kw: (
                _not_wired()
                if store is None
                else _guard_result(lambda: verify_fixes(store, actor=actor, **kw))
            ),
            side_effect="write_local",
            roles=_WRITER_ROLES,
            returns="{'doc_id','round','resolved','still_open','unresolved_findings','verdict'}",
            tags=("review", "write"),
        )
    )

    registry.register(
        ToolSpec(
            name="review.report",
            summary=(
                "产出 G1–G15 的完整审校报告（markdown 落盘）：报告头钉住被审版本 hash、"
                "每道门都带零发现自证数字、并强制包含『我这一轮犯的错』一节；"
                "只写一个报告文件，不碰任何数据表、不碰 claims"
            ),
            params={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "own_errors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "我这一轮犯的错（§8.4 G15）。必填：不写就是退回，空数组=显式声明零错误",
                    },
                    "out_path": {"type": "string", "description": "工作区内的相对路径；越界即拒绝"},
                    "round_no": {"type": "integer", "minimum": 1},
                    "dependencies": {"type": "array", "items": {"type": "object"}},
                    "banned_words": {"type": "array", "items": {"type": "string"}},
                    "run_evidence": {
                        "type": "object",
                        "description": (
                            "本轮的实跑记录（G8 可复跑门）："
                            "{'checked':true,'commands':[{'claim_id','command','output_tail'}]}。"
                            "**不传 ⇒ G8 判 unknown**（『本轮实跑过』无法判定），"
                            "绝不判 pass —— 把『没报错』读成『没问题』正是参考体例记录的教训"
                        ),
                    },
                    "claim_counts": {
                        "type": "object",
                        "description": "调用方声明的计数（G9 计数一致门）：declared_claim_count 等",
                    },
                },
                # `own_errors` 是 required：G15 的判据是"缺失则退回"，
                # 而"参数可省略"正是"缺失"在工具层的形态。
                "required": ["doc_id", "own_errors"],
                "additionalProperties": False,
            },
            handler=lambda **kw: (
                _not_wired()
                if store is None
                else _guard_result(lambda: review_report(store, actor=actor, **kw))
            ),
            side_effect="write_local",
            roles=_WRITER_ROLES,
            returns=(
                "{'doc_id','round','report_path','revision_hash','verdict','gates_total',"
                "'pass_count','fail_count','unknown_count','not_applicable_count',"
                "'failed_gates','unknown_gates','own_error_count','markdown'}"
            ),
            tags=("review", "write", "gate"),
        )
    )
