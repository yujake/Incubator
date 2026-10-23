# -*- coding: utf-8 -*-
"""形式化困难的受控汇报形态：L 向 B 汇报（`L → B`）与 B 向 D 升级（`B → D`）。

## 这个模块为什么存在（业主 2026-10-22 晚的最终协作面裁定，逐字）

> 「L 的协作面特别简单：只有 B 可以派 L，L 允许派 C 来梳理证明链，消费 B 的定理证明库，
>   可向 B 汇报形式化过程中遇到的困难、要求 B 完善证明并重新得到 V 签，
>   若缺陷严重，B 应通知 D 开展研究处理证明难点。」

裁定里的两句话是"递送"，它们必须有落点（板项或消息），不许只写日志。两边的落点
都是既有的 `agent_message` 收件箱（`agent_loop.send_message` 写、`read_messages` 读），
本模块只负责把"这一条汇报说的是什么"压成一个受控形态：

- 失败类型是受控词表 :data:`FAILURE_TYPES` 的四个取值之一 —— 自由文本没法被下游
  按类分派，而"漏了一步"与"命题本身不对"该做的事完全不同；
- 严重度 :data:`SEVERITIES` 只有两档：`normal`（B 改证明就够）与 `research`
  （路线本身可能不成立 ⇒ B 要通知 D 开展研究）。两档的分界是"B 判断"，本模块
  不替 B 判，但它把这一格钉成受控值，于是"没有 severity"与"severity 普通"分得开。

## 为什么"失败类型 → 建议补什么"也在这里

业主原话里有"要求 B 完善证明并重新得到 V 签"：汇报的内容必须能让 B 直接动手。
所以 `SUGGESTIONS` 是每一档的一句话建议（受控模板，`step` 会被填进去），
L 不能用一句"有点问题"把活退回给 B（那等于把定位工作也推回去）。

## 三态

`state` 三档（不许折平）：

- `reported` / `escalated`：留言真的写进了对方的收件箱（`msg_id` 可查）；
- `skipped`：这一档不该打扰对方（`severity` 不是 `research`，或没有可汇报的失败）；
- `refused`：受控拒绝（`invalid_params` / `no_collab_edge` / `no_session` /
  `inbox_write_failed`），一行都没写。

"没写成"绝不说成"已汇报"：`refused` 与 `reported` 在返回值里是两个 `state`，
不是一个布尔。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

#: 形式化失败的受控类型（业主裁定点名的四档，顺序即汇报的优先级）。
#:
#: - `unfaithful_step`：B 的 proof_text 里某一步在 Lean 源码里没有落点（含"多标了
#:   台账里没有的一步"这一档：那是编造落点，比漏一步更坏）；
#: - `missing_hypothesis`：这一趟为了接上证明补了一条原文没有显式写出的假设；
#: - `sorry_needed`：源码里出现 `sorry` / `admit`（含 `sorry` 的文件照样编译通过，
#:   那不是证明 —— 它说明这一步的证明还没做出来）；
#: - `statement_mismatch`：要形式化的那一条与台账对不上（不在册 / 没有正文 /
#:   没有证明 / claim 与正文不是同一句）。
FAILURE_TYPES: tuple[str, ...] = (
    "unfaithful_step",
    "missing_hypothesis",
    "sorry_needed",
    "statement_mismatch",
)

#: 严重度两档（`research` 才会打扰 D）。
SEVERITIES: tuple[str, ...] = ("normal", "research")

#: 每一档"建议 B 补什么"（`{step}` 会被换成受影响的步号；B 照着它动手）。
SUGGESTIONS: dict[str, str] = {
    "unfaithful_step": (
        "请把 proof_text 第 {step} 步展开成一条可独立引用的推理（现在这一句在 Lean 里"
        "找不到落点：缺的是一条中间引理或一条策略，不是换一个说法）"),
    "missing_hypothesis": (
        "请把第 {step} 步隐含的假设写进命题正文或证明的第 {step} 步（形式化时为它补了"
        "一条原文没有显式写出的假设 ⇒ 现在的写法比原文强）"),
    "sorry_needed": (
        "请把第 {step} 步真正证出来（形式化时这一步只能靠 sorry / admit 站住："
        "含 sorry 的文件照样编译通过，那不是证明）"),
    "statement_mismatch": (
        "请核对台账里这一条的正文与证明（要形式化的那一份与 statements 对不上："
        "要么按登记原文重交，要么把证明补进 proof_text）"),
}

#: 汇报的标题前缀（机器可识别的那一位：判据与审计按它捞）。
REPORT_SUBJECT = "形式化困难上报"

#: 研究请求的标题前缀（B → D）。
RESEARCH_SUBJECT = "研究请求"

#: 一条汇报的键集合（每条分支上都必须有这几格 —— 缺一格下游就读不到那一件事）。
REPORT_KEYS: tuple[str, ...] = (
    "statement_id",
    "statement_label",
    "failure_type",
    "step",
    "suggestion",
    "severity",
    "detail",
    "proof_chars",
    "dependency_steps",
)


def _int(value: Any) -> int:
    """把步号归一成非负整数（认不出 ⇒ 0 = "没有具体的步"）。"""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def suggestion_for(failure_type: str, step: int = 0) -> str:
    """这一档的建议（受控模板；步号 0 时说"受影响的那些步"）。"""
    template = SUGGESTIONS.get(str(failure_type or ""))
    if template is None:
        return ""
    where = str(int(step)) if int(step) > 0 else "受影响的那些"
    return template.format(step=where)


def payload(*, statement_id: str, failure_type: str, step: Any = 0,
            statement_label: str = "", suggestion: str = "",
            severity: str = "normal", detail: str = "",
            proof_chars: Any = 0, dependency_steps: Any = 0) -> dict[str, Any]:
    """一条汇报/研究请求的结构化正文（键集合固定 = :data:`REPORT_KEYS`）。"""
    step_no = _int(step)
    kind = str(failure_type or "")
    return {
        "statement_id": str(statement_id or ""),
        "statement_label": str(statement_label or ""),
        "failure_type": kind,
        "step": step_no,
        "suggestion": str(suggestion or "") or suggestion_for(kind, step_no),
        "severity": str(severity or "normal"),
        "detail": str(detail or ""),
        "proof_chars": _int(proof_chars),
        "dependency_steps": _int(dependency_steps),
    }


def violations(item: Mapping[str, Any]) -> list[str]:
    """一条汇报自己不成立的地方（空清单 = 可以递送）。"""
    bad: list[str] = []
    if not str(item.get("statement_id") or "").strip():
        bad.append("statement_id 是空的（汇报必须点名是哪一条命题）")
    if str(item.get("failure_type") or "") not in FAILURE_TYPES:
        bad.append(f"failure_type={item.get('failure_type')!r} 不在受控取值里"
                   f"（{list(FAILURE_TYPES)}）")
    if str(item.get("severity") or "normal") not in SEVERITIES:
        bad.append(f"severity={item.get('severity')!r} 不在受控取值里"
                   f"（{list(SEVERITIES)}）")
    if not str(item.get("suggestion") or "").strip():
        bad.append("suggestion 是空的（退回时必须说清要 B 补什么）")
    return bad


def issues(*, reason: str = "", coverage: Mapping[str, Any] | None = None,
           statement_reasons: Iterable[str] = ()) -> list[dict[str, Any]]:
    """这一次形式化的失败项（按 :data:`FAILURE_TYPES` 的优先级排序，可能为空）。

    `reason` 是 `formalize` 的受控理由码，`coverage` 是逐步对照的读数；
    `statement_reasons` 是"命题台账那一道闸"的拒绝理由码集合（由调用方从受控词表给，
    本模块不另抄一份台账口径）。
    """
    cov = dict(coverage or {})
    found: list[dict[str, Any]] = []
    mismatch = set(str(x) for x in statement_reasons)
    if str(reason or "") in mismatch:
        found.append({"failure_type": "statement_mismatch", "step": 0,
                      "detail": f"命题台账那一道闸拒了：{reason}"})
    sorry = [_int(x) for x in (cov.get("sorry_lines") or [])]
    if sorry:
        found.append({"failure_type": "sorry_needed", "step": sorry[0],
                      "detail": f"源码第 {sorry[0]} 行出现 sorry / admit"})
    unmapped = [_int(x) for x in (cov.get("unmapped") or [])]
    if unmapped:
        found.append({"failure_type": "unfaithful_step", "step": unmapped[0],
                      "detail": f"第 {unmapped[0]} 步在源码里找不到落点"
                                f"（未映射 {unmapped}）"})
    extra = [_int(x) for x in (cov.get("extra_steps") or [])]
    if extra:
        found.append({"failure_type": "unfaithful_step", "step": extra[0],
                      "detail": f"源码标了台账证明里没有的第 {extra[0]} 步"
                                f"（编造的落点 {extra}）"})
    added = [a for a in (cov.get("assumptions_added") or []) if isinstance(a, Mapping)]
    if added:
        owner = _int(added[0].get("proof_step"))
        found.append({"failure_type": "missing_hypothesis", "step": owner,
                      "detail": f"第 {owner} 步补了一条原文没有显式写出的假设："
                                f"{str(added[0].get('text') or '')[:120]}"})
    found.sort(key=lambda item: FAILURE_TYPES.index(item["failure_type"]))
    return found


def severity_for(failure_type: str) -> str:
    """L 对这一档的严重度建议（B 仍然自己判：`escalate_proof_research` 收的是 B 给的 severity）。

    口径：`statement_mismatch` 意味着"要形式化的那一条与台账对不上" —— 那有可能是
    这条证明的路线本身不成立（业主给的例子），所以 L 建议 `research`；其余三档
    都是"证明里缺一块"，B 补上就该够。
    """
    return "research" if str(failure_type or "") == "statement_mismatch" else "normal"


def report_subject(item: Mapping[str, Any]) -> str:
    """L → B 的标题（点名失败类型与命题号，收件箱摘要里一眼可读）。"""
    return (f"{REPORT_SUBJECT}（{item.get('failure_type')}）："
            f"{item.get('statement_id')}"
            + (f" 第 {item.get('step')} 步" if _int(item.get("step")) > 0 else ""))


def report_body(item: Mapping[str, Any]) -> str:
    """L → B 的正文（四件事逐条写清：哪一条、哪一档、哪一步、要 B 补什么）。"""
    label = str(item.get("statement_label") or "").strip()
    return "\n".join([
        f"命题：{item.get('statement_id')}" + (f"（{label}）" if label else ""),
        f"失败类型：{item.get('failure_type')}",
        f"具体哪一步：第 {item.get('step')} 步" if _int(item.get("step")) > 0 else "具体哪一步：整条（不是某一步）",
        f"要 B 补什么：{item.get('suggestion')}",
        f"读数：proof_text {item.get('proof_chars')} 字、依赖链 {item.get('dependency_steps')} 步；"
        f"L 建议的严重度 {item.get('severity')}",
        f"现象：{item.get('detail')}",
        "L 这一趟的结论是 unknown（不是「命题不成立」）：证明链路接不上，需要 B 完善后再过 V 的签。",
    ])


def research_subject(item: Mapping[str, Any]) -> str:
    """B → D 的标题（`研究请求` 是机器可识别的那一位）。"""
    return (f"{RESEARCH_SUBJECT}（{item.get('failure_type')}）："
            f"{item.get('statement_id')} 的证明难点")


def research_body(item: Mapping[str, Any]) -> str:
    """B → D 的正文：把 L 的汇报原样带过去，并写清要 D 做什么。"""
    label = str(item.get("statement_label") or "").strip()
    return "\n".join([
        f"命题：{item.get('statement_id')}" + (f"（{label}）" if label else ""),
        f"难点类型：{item.get('failure_type')}",
        f"卡在哪一步：第 {item.get('step')} 步" if _int(item.get("step")) > 0 else "卡在哪一步：整条路线",
        f"形式化给的读数：{item.get('detail')}",
        f"L 的建议（B 原样转达）：{item.get('suggestion')}",
        "B 的判断：这一条的缺陷在证明路线本身（不是补一块就够）⇒ 请 D 开展研究处理这个证明难点；"
        "研究有结论后按 B 的登记路径重交证明，再过 V 的签。",
    ])


# ---------------------------------------------------------------- 递送（唯一一份实现）


def session_identity(*, session_root: Any = "", sid: Any = "",
                     fallback_root: Any = "") -> tuple[str, str, str]:
    """这一条递送该落在哪个会话：`(根, 会话号, 问题)`。

    三档来源按优先级：调用方显式给的 → 运行期上下文（`conductor.current_session`，
    工具路径由 `calling_as` 挂上）→ 调用方的兜底根（`store.root`：`run-agent` 与
    `Conductor.summon` 那两条路上它与会话根是同一个目录）。

    根取不到时返回问题 `no_session` —— 那一条递送不成立（按缺省会话写等于把它丢进
    一个对方不会读的文件里），不许静默当成"已经汇报"。
    """
    root = str(session_root or "")
    csid = str(sid or "")
    if not root:
        try:
            from . import conductor as _CX

            got_root, got_sid = _CX.current_session()
            root = str(got_root or "")
            csid = csid or str(got_sid or "")
        except Exception:  # noqa: BLE001 —— 读不到上下文不是致命错：下面还有兜底根
            root = ""
    if not root:
        root = str(fallback_root or "")
    if not csid:
        try:
            from . import sessions as _SS

            csid = str(_SS.session_id())
        except Exception:  # noqa: BLE001 —— 会话号读不到就按缺省会话写
            csid = ""
    if not root:
        return "", csid, "no_session"
    return root, csid, ""


def deliver(*, sender: str, to: str, item: Mapping[str, Any], subject: str, body: str,
            extra_key: str, session_root: Any = "", sid: Any = "",
            fallback_root: Any = "") -> dict[str, Any]:
    """把一条汇报/研究请求投进对方的收件箱（`agent_loop.send_message` 是唯一落点）。

    返回的 `state` 三档（见模块 docstring）。投递前先过协作边那一道准入
    （`agent_loop.message_admission` 是唯一实现）：边不在就 `refused/no_collab_edge`，
    一行都不写 —— 于是"L 向 B 汇报"这件事绕不开"只有 B 可以派 L"那条边。
    """
    from . import agent_loop as _AL

    out: dict[str, Any] = {
        "attempted": True, "state": "refused", "reason": "", "why": "",
        "msg_id": "", "to": str(to or ""), "session_root": "", "sid": "",
        "payload": dict(item),
    }
    admission = _AL.message_admission(str(sender or ""), str(to or ""))
    if admission:
        out.update({"state": "refused", "reason": "no_collab_edge", "why": str(admission)})
        return out
    root, csid, problem = session_identity(session_root=session_root, sid=sid,
                                           fallback_root=fallback_root)
    out["session_root"] = root
    out["sid"] = csid
    if problem:
        out.update({"state": "refused", "reason": problem,
                    "why": "没有会话根 ⇒ 这一条递送会掉进一个对方不读的文件里，"
                           "一行都不写（不许把「没送出去」写成「已汇报」）"})
        return out
    msg_id, write_problem = _AL.send_message(
        Path(root), sender=str(sender or ""), to=str(to or ""),
        subject=str(subject or ""), body=str(body or ""), sid=(csid or None),
        extra={str(extra_key): dict(item)})
    if write_problem or not msg_id:
        out.update({"state": "refused", "reason": "inbox_write_failed",
                    "why": f"留言没写成（{write_problem or '没有 msg_id'}）⇒ 这不算已汇报"})
        return out
    out.update({"state": "reported", "reason": "", "why": "", "msg_id": str(msg_id)})
    return out


__all__ = [
    "FAILURE_TYPES",
    "REPORT_KEYS",
    "REPORT_SUBJECT",
    "RESEARCH_SUBJECT",
    "SEVERITIES",
    "SUGGESTIONS",
    "deliver",
    "issues",
    "payload",
    "report_body",
    "report_subject",
    "research_body",
    "research_subject",
    "session_identity",
    "severity_for",
    "suggestion_for",
    "violations",
]
