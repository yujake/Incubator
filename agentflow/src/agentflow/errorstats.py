# -*- coding: utf-8 -*-
"""按角色统计「错误动作计数」的只读测试工具。

## 这个量回答什么

业主口径（逐字）：「做一个统计量作为测试工具：对每种角色，统计"错误动作计数"
（注意是按照每种角色来记），包括所有被各种判据拦下或被秘书拦下的行为，细分多类计数。」

它只读盘上已有的记录（事件流 / 会话记录），一份都不写：不建表、不改行、不追加事件、
不落报告文件。人看 `python -m agentflow stats errors --root <工作区>`，
程序看 `error_action_stats(target).as_dict()`。

## 三个口径（不写下来，这个数就没有可比性）

1. 谁是"错的那一方"（角色归属）。事件流里一条 `tasks` 行的 `role` 是"被召唤的角色"、
   `called_by` 是"发起这次召唤的角色"。越权/禁边是发起方把这条边派错了，算发起方的错；
   而"这条边被拒"这件事记在被召唤的那一行上。真机现场（`projects/r34d`，`t-000019`）：
   `role=B`、`called_by=G`，拒信逐字是 "G → B 不在策略允许的边里"。所以归属按码分流：
   - `CALLER_ATTRIBUTED_CODES`（召唤期结构判据，产出见 `policy.check`）⇒ 记 `called_by`；
   - 其余（写入期判据 / 判据层 / 角色自己的回执）⇒ 记 `role`；
   - 会话记录 `agent_step` / `llm_call` ⇒ 记记录里的 `role`；
   - 代唤请示（`agent_message` 的 `请代唤`）⇒ 记记录里的 `from`。
   为什么必须显式写：若一律把 `role` 当 actor，"G 派 B 被拒"这件事就记到 B 头上 ——
   而"一方的错不算到另一方头上"正是判据 `tests/test_error_action_stats.py` 钉的第一条。

2. 一条记录只算一次（主码规则）。同一条记录里常常命中好几个码（工具结果既有
   `参数错误：` 又有 `缺少必填参数`；一条被拒的召唤行 detail 里可能同时出现
   `forbidden_edge` 与写入期判据的原话）。取值规则只有一条：类目表里靠前的类目优先，
   同类目里字数长的码优先（同长按 `CODE_TABLE` 的顺序）。于是判据是确定的：
   一条记录只给它的角色增加 1，且只加在一个类目上。
   为什么不是纯按字数：`refusal_reason=invalid_params`（粗：这次调用不成立）与 detail 里的
   `行校验失败`（细：写库那一刻被 schema 拦住）会同时命中，纯按字数会永远让粗码赢，
   写入期判据那一类就收不到数。为什么同类目里要看字数：`judge_not_wired` 含 `not_wired`，
   取长的那个才记得准（两者本来同类目，只影响 `sources.hits` 里记下的码名）。

3. 三态。`checked=True` 才谈得上"几个"；读不到就是 `unknown`，不折成 0：
   - 工作区不存在 / `data/events.jsonl` 不存在或读不明白 ⇒ `checked=False`；
   - `sessions/` 存在但一个文件都读不明白 ⇒ `checked=False`；
   - `sessions/` 根本不存在 ⇒ 这是"这个工作区没有会话记录"的正常形态，按 0 读
     （`checked=True`，与 `statusreport._rows` 把"读不到"和"是 0 行"分开同一个理由）。
   "空工作区 ⇒ 全 0 且 checked=True"是正控：0 不是 unknown。

## 数据源（三处，都是盘上已有的记录）

- `data/events.jsonl`：`tasks` 表的事件，取每个 `task_id` 的最后一行（后写覆盖先写，
  与 `Store.rebuild` 的重放口径一致）。拒绝落在 `outcome=refused` + `refusal_reason` 上。
- `sessions/*.jsonl`：
  - `llm_call` 的 `problem`（判据层的 `judge_bad_json` / `judge_bad_args` /
    `judge_no_reply:*` / `judge_failed:*`）；
  - `agent_step` 的 `result.error` 与 `result.warn`（工具层与收工门的拒信原话；`warn` 里
    那句"条工具调用，只执行第 1 条"就是 D-35 的读数，判据 `tests/test_d35_multi_call_takes_first.py`）；
  - `agent_message` 的 `subject`（`请代唤` = 越权被拒之后的转投）。
  刻意不读 `payload`：那是模型自己写的原话，"提到一个码"不等于"撞上那个码"。
  也刻意不读 `runs/*.json`：它与 `agent_step` 是同一批步的两份落盘，两份都读会把同一步
  算两次（真机核查：`runs/B-*.json` 与 `sessions/*.jsonl` 的 `agent_step` 逐条对应）。

## 码 → 类目这张表从哪来

`CODE_TABLE` 每行是（码, 类目, 出处）。出处逐条去代码里 grep 过，写的是定义或产出那一
行的 `file:line`。判据 `tests/test_error_action_stats.py` 会扫源码断言表里每个码真的出现
在 `src/agentflow/` 的某个文件里（扫的时候排除本文件，否则这张表会自己证明自己）。
类目本身逐类写过一行含义（`ERROR_CATEGORIES`）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import schema as S

#: 没有记下角色时用的名字。空串不许静默并进某个角色（那会把一个未知算到已知头上）。
UNKNOWN_ROLE = "（未记角色）"

#: 类目表（顺序即优先级：主码同长时按它取）。每类一行含义，逐类来自仓库里真实存在的拒绝形态。
ERROR_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("forbidden_edge",
     "越权/禁边：这条召唤边不在 ALLOWED_EDGES 里（含 Lean 关着时的隐藏角色、不可召唤的主控）"),
    ("not_in_roster",
     "名册外的对象：按角色名发给一个不在自己名册里的人（只有父与子能通话）"),
    ("unknown_tool",
     "名字不存在：工具面没有这件工具 / 该角色没有这个动作 / 角色名不存在"),
    ("direct_write",
     "写库野路：绕开正路直写 statements / dependencies / lit_candidates（通用写口被拒）"),
    ("readonly_role_write",
     "只读角色拿写工具：调用期角色判据拒绝这次调用（权限面，不是参数问题）"),
    ("not_wired",
     "没接线：该角色的该动作尚未接线（框架欠的东西，不是模型做错的事）"),
    ("capacity_refused",
     "配额/时限拒绝：深度、扇出、并发、预算、墙钟截止、同链重复（policy 的六条容量判据）"),
    ("schema_invalid",
     "写入期 schema 校验失败：行不满足表契约（行校验失败，写库那一刻被拒）"),
    ("param_invalid",
     "参数不合法：必填缺失 / 类型或枚举不对（工具层参数门；必填缺失是其中最常见的一档）"),
    ("duplicate_conflict",
     "重复/幂等冲突：同一件东西已经在库或已登记过（duplicate_* 一族）"),
    ("controlled_refusal",
     "受控拒绝：秘书与各动作以受控理由码拒收（refused 那一档，理由可枚举、可统计）"),
    ("judge_bad_json",
     "判据层：模型回的不是合法 JSON（坏形状，不是坏参数）"),
    ("judge_bad_args",
     "判据层：模型给的参数写坏了（与坏 JSON 分开计，纠正话术不同）"),
    ("judge_no_reply",
     "判据层：没拿到可用的回复（超时 / 输出预算被思考吃光 / judge_no_reply:<kind>）"),
    ("judge_failed",
     "判据层：判据本身失败（judge_failed:<kind>，如网络断；不是模型的错，但要看得见）"),
    ("multi_call",
     "一步给了多条工具调用而只执行第 1 条（D-35 取第一条，其余丢弃并点名）"),
    ("unreadable",
     "读不明白：台账/回执/上下文图读不出来或解析失败（不许读成 0 的那一档）"),
    ("closing_blocked",
     "收工门拦下：mapping_not_written / run_evidence_unbacked / quote_verified_without_span"),
    ("paper_mapping_gap",
     "论文对应表的逐行缺口（mapping_* 一族：孤立行、引文定位缺、文件缺、程序缺…）"),
    ("relay_after_refusal",
     "流程层：被禁边拒掉之后发起的代唤请示（转投，不是重试同一条边）"),
)

#: 召唤期结构判据：这些码说的是"发起方把这次召唤派错了"，所以记 called_by 而不是被召唤的
#: 那个角色。成员口径 = `policy.check` 在派出之前就下结论的那六条 + 角色/动作存在性
#: （`policy.check_action`）与非召唤目标。`not_wired` 不在其中：那是被召唤角色自己的动作缺口。
CALLER_ATTRIBUTED_CODES: frozenset[str] = frozenset({
    "forbidden_edge", "unknown_role", "unknown_action", "not_in_roster",
    "depth_exceeded", "fanout_exceeded", "concurrency_exceeded",
    "budget_exceeded", "deadline_exceeded", "cycle_detected",
})

#: 码 → 类目 → 出处（file:line）。出处是"这个码在哪定义 / 在哪产出"，逐条 grep 出来的。
CODE_TABLE: tuple[tuple[str, str, str], ...] = (
    # ---- 结构性拒绝
    ("forbidden_edge", "forbidden_edge",
     "src/agentflow/schema.py:2497（词表）/ src/agentflow/policy.py:408,421,430,455（产出）"),
    ("not_in_roster", "not_in_roster",
     "src/agentflow/agent_loop.py:2754（roster_probe 的受控拒绝码）"),
    ("不在你的名册里", "not_in_roster",
     "src/agentflow/agent_loop.py:2755（roster_probe 的拒信原文）"),
    ("unknown_tool", "unknown_tool", "src/agentflow/tools/base.py:1132（kind）"),
    ("没有名为", "unknown_tool", "src/agentflow/tools/base.py:802（ToolError 原文）"),
    ("unknown_action", "unknown_tool",
     "src/agentflow/schema.py:2496（词表）/ src/agentflow/policy.py:306,313（产出）"),
    ("unknown_role", "unknown_tool",
     "src/agentflow/schema.py:2495（词表）/ src/agentflow/policy.py:302,433（产出）"),
    ("direct_write_refused", "direct_write", "src/agentflow/store.py:248（DIRECT_WRITE_REFUSED）"),
    ("role_denied", "readonly_role_write",
     "src/agentflow/tools/base.py:1173,1178（call 的调用期角色判据）"),
    ("not_wired", "not_wired",
     "src/agentflow/schema.py:2505（词表）/ src/agentflow/conductor.py:3185（产出）"),
    ("depth_exceeded", "capacity_refused", "src/agentflow/schema.py:2499 / src/agentflow/policy.py:463"),
    ("fanout_exceeded", "capacity_refused", "src/agentflow/schema.py:2500 / src/agentflow/policy.py:502"),
    ("concurrency_exceeded", "capacity_refused",
     "src/agentflow/schema.py:2501 / src/agentflow/policy.py:513"),
    ("budget_exceeded", "capacity_refused",
     "src/agentflow/schema.py:2502 / src/agentflow/policy.py:521,537,540"),
    ("deadline_exceeded", "capacity_refused",
     "src/agentflow/schema.py:2503 / src/agentflow/policy.py:548"),
    ("cycle_detected", "capacity_refused", "src/agentflow/schema.py:2504 / src/agentflow/policy.py:474"),
    # ---- 写入期判据
    ("行校验失败", "schema_invalid", "src/agentflow/tools/table_tools.py:116,120（ToolError 原文）"),
    ("缺少必填参数", "param_invalid", "src/agentflow/tools/base.py:395（ParamError 原文）"),
    ("参数错误：", "param_invalid", "src/agentflow/tools/base.py:1214（ToolResult.fail 原文）"),
    ("param_error", "param_invalid", "src/agentflow/tools/base.py:1187,1233（kind）"),
    ("missing_source", "param_invalid", "src/agentflow/tools/register_statement.py:821"),
    ("missing_own_source", "param_invalid", "src/agentflow/tools/register_statement.py:870"),
    ("missing_quote_reason", "param_invalid", "src/agentflow/tools/register_statement.py:830"),
    ("missing_page_range", "param_invalid", "src/agentflow/tools/register_statement.py:845,860"),
    ("duplicate_doi", "duplicate_conflict",
     "src/agentflow/schema.py:128,144（词表）/ src/agentflow/litstage.py:637（产出）"),
    ("duplicate_statement", "duplicate_conflict", "src/agentflow/tools/register_statement.py:1181"),
    ("duplicate_paper_number", "duplicate_conflict", "src/agentflow/paperledger.py:205"),
    ("duplicate_claim_id", "duplicate_conflict", "src/agentflow/claimanatomy.py:1717,1728"),
    ("duplicate_id", "duplicate_conflict", "src/agentflow/verify.py:219"),
    ("invalid_params", "controlled_refusal", "src/agentflow/schema.py:2498（词表）/ src/agentflow/refusals.py:38"),
    ("bad_statement", "controlled_refusal", "src/agentflow/tools/register_statement.py:704"),
    ("bad_origin", "controlled_refusal", "src/agentflow/tools/register_statement.py:710"),
    ("bad_evidence_kind", "controlled_refusal", "src/agentflow/tools/register_statement.py:762"),
    ("bad_id", "controlled_refusal", "src/agentflow/tools/register_statement.py:929"),
    ("bad_line_range", "controlled_refusal", "src/agentflow/tools/register_statement.py:759"),
    ("bad_page_range", "controlled_refusal", "src/agentflow/tools/register_statement.py:756"),
    ("proofs_not_attached", "controlled_refusal",
     "src/agentflow/tools/register_statement.py:1176,1208"),
    ("proof_needs_third_party_signature", "controlled_refusal",
     "src/agentflow/tools/register_statement.py:798"),
    ("canonical_not_written", "controlled_refusal", "src/agentflow/tools/register_statement.py:1130"),
    ("secretary_unavailable", "controlled_refusal", "src/agentflow/tools/register_statement.py:1052"),
    # ---- 判据层
    ("judge_bad_json", "judge_bad_json", "src/agentflow/judge.py:67,206,208（problem 码）"),
    ("judge_bad_args", "judge_bad_args", "src/agentflow/agent_loop.py:4455,8142"),
    ("judge_no_reply:", "judge_no_reply", "src/agentflow/agent_loop.py:15,805（带后缀那一族）"),
    ("judge_timeout", "judge_no_reply", "src/agentflow/agent_loop.py:808（_NO_REPLY_NAMED）"),
    ("judge_output_limit", "judge_no_reply", "src/agentflow/agent_loop.py:808,837"),
    ("judge_failed:", "judge_failed", "src/agentflow/agent_loop.py:1135（真机 judge_failed:ModelReplyNotOk）"),
    ("judge_not_wired", "not_wired", "src/agentflow/judge.py:14（没接线那一档）"),
    ("条工具调用，只执行第 1 条", "multi_call", "src/agentflow/agent_loop.py:517（_multi_call_warning）"),
    ("run_evidence_unreadable", "unreadable", "src/agentflow/closing.py:1082（RUN_EVIDENCE_UNREADABLE_CODE）"),
    ("context_graph_unreadable", "unreadable", "src/agentflow/tools/register_statement.py:946"),
    # ---- 流程层
    ("mapping_not_written", "closing_blocked", "src/agentflow/closing.py:3738（MAPPING_NOT_WRITTEN_CODE）"),
    ("run_evidence_unbacked", "closing_blocked", "src/agentflow/closing.py:1079（RUN_EVIDENCE_UNBACKED_CODE）"),
    ("quote_verified_without_span", "closing_blocked", "src/agentflow/closing.py:5560（收工门 quote_evidence 格）"),
    ("mapping_orphan", "paper_mapping_gap", "src/agentflow/papermapping.py:303"),
    ("mapping_file_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:303"),
    ("mapping_unresolvable", "paper_mapping_gap", "src/agentflow/papermapping.py:303,839"),
    ("mapping_citation_loc_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:308,1245"),
    ("mapping_citation_file_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:308,1286"),
    ("mapping_proof_program_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:324"),
    ("mapping_package_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:324"),
    ("mapping_lean_missing", "paper_mapping_gap", "src/agentflow/papermapping.py:335,1330"),
    ("请代唤", "relay_after_refusal", "src/agentflow/agent_loop.py:81（RELAY_SUBJECT）"),
)

#: 码 → 类目（由 `CODE_TABLE` 派生，只有这一处真身）。
CODE_TO_CATEGORY: dict[str, str] = {code: cat for code, cat, _ in CODE_TABLE}

#: 码 → 出处（file:line，人读用）。
CODE_PROVENANCE: dict[str, str] = {code: where for code, _cat, where in CODE_TABLE}

_CATEGORY_INDEX: dict[str, int] = {cat: i for i, (cat, _why) in enumerate(ERROR_CATEGORIES)}
_CODE_INDEX: dict[str, int] = {code: i for i, (code, _c, _w) in enumerate(CODE_TABLE)}

#: 匹配顺序：类目表顺序优先，同类目里字数长的先试。这就是主码规则的唯一实现。
#:
#: 为什么类目顺序优先而不是纯按字数：一条被拒的行常常同时带着两层码 ——
#: `refusal_reason=invalid_params`（粗：这次调用不成立）与 detail 里的
#: `行校验失败`（细：写库那一刻被 schema 拦住）。纯按字数会让 `invalid_params`
#: （14 字）压过 `行校验失败`（5 字），于是写入期判据那一类永远收不到数。
#: 类目顺序把结构性判据排在前面（根因先看），同类目里再让长码胜出 ——
#: 于是 `judge_not_wired` 不会被 `not_wired` 抢先（两者同类目，长的那个更准）。
_MATCH_ORDER: tuple[tuple[str, str], ...] = tuple(
    (code, cat)
    for code, cat, _where in sorted(
        CODE_TABLE,
        key=lambda t: (_CATEGORY_INDEX[t[1]], -len(t[0]), _CODE_INDEX[t[0]]))
)

#: 事件流里带拒绝语义的两档 `tasks.outcome`。
_REFUSAL_OUTCOME = "refused"
_FAILED_OUTCOME = "failed"


# ---------------------------------------------------------------- 主码


def primary_code(*texts: Any) -> tuple[str, str] | None:
    """这段文字命中的主码：(码, 类目)。没有命中 ⇒ None。

    口径见模块 docstring 第 2 条：字数最长的命中码胜出，同长按类目表顺序。
    `texts` 里空值与非字符串一律先折成空串，于是"字段缺失"与"字段是空串"同形 ——
    这两件事在统计上本来就该同形（都等于"这条记录没留下这句话"）。
    """
    blob = " ".join(str(t) for t in texts if t)
    if not blob:
        return None
    for code, cat in _MATCH_ORDER:
        if code in blob:
            return (code, cat)
    return None


# ---------------------------------------------------------------- 结果形状


@dataclass(frozen=True)
class ErrorStats:
    """按角色的错误动作计数。`by_role[role][category]` 就是业主问的那张表。

    三态三件套（`checked` / `state` / `reason`）与计数并排返回，而不是藏在异常里：
    读不到事件流时 `total` 是 0 但 `checked=False`，于是"0 次错误"与"没读到"不会
    被同一个数字表示。`sources` 是逐源的读数，人排查时先看它。
    """

    by_role: dict[str, dict[str, int]] = field(default_factory=dict)
    role_total: dict[str, int] = field(default_factory=dict)
    total: int = 0
    checked: bool = False
    state: str = "unknown"
    reason: str = ""
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def count(self, role: str, category: str) -> int:
        return int(self.by_role.get(role, {}).get(category, 0))

    def category_total(self, category: str) -> int:
        return sum(int(c.get(category, 0)) for c in self.by_role.values())

    def categories(self) -> dict[str, int]:
        """类目 → 全角色合计（按 `ERROR_CATEGORIES` 的顺序，只留非 0 的）。"""
        out: dict[str, int] = {}
        for cat, _why in ERROR_CATEGORIES:
            n = self.category_total(cat)
            if n:
                out[cat] = n
        return out

    def as_dict(self) -> dict[str, Any]:
        """机器可读形态（CLI 的 `--json` 直接印它）。"""
        return {
            "by_role": {r: dict(sorted(c.items())) for r, c in sorted(self.by_role.items())},
            "role_total": dict(sorted(self.role_total.items())),
            "total": int(self.total),
            "checked": bool(self.checked),
            "state": self.state,
            "reason": self.reason,
            "sources": {k: dict(v) for k, v in self.sources.items()},
        }


# ---------------------------------------------------------------- 读盘（只读）


def _resolve_target(target: Any) -> tuple[Path, Any]:
    """`target` 可以是工作区根路径，也可以是 `Store`（用它自己的 `root`）。"""
    if hasattr(target, "read_events") and hasattr(target, "root"):
        root = Path(str(getattr(target, "root") or "."))
        return (root, target)
    return (Path(str(target)), None)


def _read_events(root: Path, store: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读事件流。返回（事件列表, 读数）。读不到 ⇒ 读数里 `checked=False` 且给出原因。"""
    reading: dict[str, Any] = {"checked": False, "events": 0, "bad_lines": 0,
                              "table": "tasks", "reason": ""}
    if store is not None:
        try:
            rows = [dict(e) for e in store.read_events()]
        except Exception as e:  # noqa: BLE001 读不到与"是 0 条"必须分得开
            reading["reason"] = f"事件流读不到（{type(e).__name__}: {e}）"
            return ([], reading)
        reading.update(checked=True, events=len(rows), reason="")
        return (rows, reading)

    path = root / "data" / "events.jsonl"
    if not root.exists() or not root.is_dir():
        reading["reason"] = f"工作区不存在：{root}"
        return ([], reading)
    if not path.exists():
        reading["reason"] = f"事件流不存在：{path}"
        return ([], reading)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        reading["reason"] = f"事件流读不到（{type(e).__name__}: {e}）"
        return ([], reading)
    rows = []
    bad = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    reading.update(checked=True, events=len(rows), bad_lines=bad,
                   reason="" if rows or not bad else "事件流每一行都读不明白")
    if not rows and bad:
        reading["checked"] = False
    return (rows, reading)


def _read_sessions(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读会话记录。目录不在 ⇒ 按"这个工作区没有会话记录"读（0 条，checked）。"""
    reading: dict[str, Any] = {"checked": False, "files": 0, "records": 0,
                               "bad_lines": 0, "unreadable_files": [], "reason": ""}
    if not root.exists() or not root.is_dir():
        reading["reason"] = f"工作区不存在：{root}"
        return ([], reading)
    folder = root / "sessions"
    if not folder.is_dir():
        reading.update(checked=True, reason="没有 sessions 目录（按 0 条读）")
        return ([], reading)
    paths = sorted(p for p in folder.glob("*.jsonl") if p.is_file())
    if not paths:
        reading.update(checked=True, reason="sessions 目录里没有 .jsonl")
        return ([], reading)
    records: list[dict[str, Any]] = []
    bad = 0
    broken: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            broken.append(path.name)
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(obj, dict):
                records.append(obj)
            else:
                bad += 1
    readable = len(paths) - len(broken)
    reading.update(files=readable, records=len(records), bad_lines=bad,
                   unreadable_files=broken,
                   checked=readable > 0,
                   reason="" if readable else "sessions 目录里每个文件都读不明白")
    return (records, reading)


def _latest_task_rows(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """事件流里 `tasks` 表每个 `task_id` 的最后一行（后写覆盖先写）。"""
    latest: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        if str(event.get("table") or "") != "tasks":
            continue
        if str(event.get("op") or "") not in ("upsert", "append"):
            continue
        row = event.get("row")
        if not isinstance(row, Mapping):
            continue
        tid = str(row.get("task_id") or "")
        if not tid:
            continue
        if tid not in latest:
            order.append(tid)
        latest[tid] = dict(row)
    return [latest[tid] for tid in order]


def _role_name(value: Any) -> str:
    name = str(value or "").strip()
    return name or UNKNOWN_ROLE


def _known_role(value: Any) -> bool:
    name = str(value or "").strip()
    return bool(name) and (name in S.ROLES or name == S.CONDUCTOR_ROLE)


def _step_text(record: Mapping[str, Any]) -> tuple[str, str]:
    """一条 `agent_step` 的拒信原话：(整段可扫的文字, 模型自己写的 payload 名字)。

    只取 `result.error` / `result.warn` / `problem`，不取 `payload`（见模块 docstring）。
    """
    parts: list[str] = []
    problem = record.get("problem")
    if problem:
        parts.append(str(problem))
    result = record.get("result")
    if isinstance(result, Mapping):
        for key in ("error", "warn", "problem", "kind"):
            value = result.get(key)
            if value:
                parts.append(str(value))
    elif isinstance(result, str):
        parts.append(result)
    return (" ".join(parts), "")


# ---------------------------------------------------------------- 核心函数


def error_action_stats(target: Any) -> ErrorStats:
    """按角色统计错误动作计数。`target` 可以是工作区根路径，也可以是 `Store`。

    纯读：不写库、不写盘、不建目录、不加锁（`Store.read_events` 本身只读文件）。
    三态见模块 docstring 第 3 条：读不到 ⇒ `checked=False` / `state="unknown"`，
    不把"没读到"折成 0。
    """
    root, store = _resolve_target(target)
    events, ev_reading = _read_events(root, store)
    records, ss_reading = _read_sessions(root)

    counts: dict[str, dict[str, int]] = {}
    hits: dict[str, dict[str, int]] = {}

    def _bump(role: str, code: str, cat: str) -> None:
        slot = counts.setdefault(role, {}).setdefault(cat, 0)
        counts[role][cat] = slot + 1
        hits.setdefault(role, {}).setdefault(code, 0)
        hits[role][code] = hits[role][code] + 1

    # ---- 事件流：tasks 行的拒绝与失败
    if ev_reading.get("checked"):
        for row in _latest_task_rows(events):
            outcome = str(row.get("outcome") or "")
            if outcome not in (_REFUSAL_OUTCOME, _FAILED_OUTCOME):
                continue
            found = primary_code(row.get("refusal_reason"), row.get("error"), row.get("detail"))
            if found is None:
                # 被拒但理由码不在码表里（历史行 / 新码没登记）：不猜一个类目出来，
                # 也不静默丢掉 —— 记进 `sources.events.unclassified`，人读的呈现里会点名。
                # 这条纪律与"没读到不许折成 0"同族：没见过的东西不许编，但必须看得见。
                if outcome == _REFUSAL_OUTCOME:
                    ev_reading["unclassified"] = int(ev_reading.get("unclassified") or 0) + 1
                continue
            code, cat = found
            if code in CALLER_ATTRIBUTED_CODES and _known_role(row.get("called_by")):
                role = _role_name(row.get("called_by"))
            else:
                role = _role_name(row.get("role"))
            _bump(role, code, cat)

    # ---- 会话记录：判据层的 problem、工具层的拒信、代唤请示
    if ss_reading.get("checked"):
        for record in records:
            kind = str(record.get("kind") or "")
            role = _role_name(record.get("role"))
            if kind == "llm_call":
                found = primary_code(record.get("problem"), record.get("detail"))
                if found is not None:
                    _bump(role, *found)
                continue
            if kind == "agent_step":
                text, _ = _step_text(record)
                found = primary_code(text)
                if found is not None:
                    _bump(role, *found)
                continue
            if kind == "agent_message":
                subject = str(record.get("subject") or "")
                found = primary_code(subject)
                if found is not None and CODE_TO_CATEGORY.get(found[0]) == "relay_after_refusal":
                    _bump(_role_name(record.get("from")), *found)
                continue

    role_total = {role: sum(cats.values()) for role, cats in counts.items()}
    total = sum(role_total.values())

    checked = bool(ev_reading.get("checked")) and bool(ss_reading.get("checked"))
    reasons: list[str] = []
    if not ev_reading.get("checked"):
        reasons.append(str(ev_reading.get("reason") or "事件流读不到"))
    if not ss_reading.get("checked"):
        reasons.append(str(ss_reading.get("reason") or "会话记录读不到"))
    sources = {
        "events": ev_reading,
        "sessions": ss_reading,
        "hits": {"checked": checked, "codes": {r: dict(sorted(c.items())) for r, c in sorted(hits.items())}},
    }
    return ErrorStats(
        by_role={r: dict(sorted(c.items())) for r, c in sorted(counts.items())},
        role_total=dict(sorted(role_total.items())),
        total=total,
        checked=checked,
        state="checked" if checked else "unknown",
        reason="；".join(reasons),
        sources=sources,
    )


# ---------------------------------------------------------------- 人读的呈现


def _shown_width(text: str) -> int:
    """显示宽度（CJK 占两格）。表格对齐只靠它，靠 `len` 会把中文表头错开一格。"""
    shown = 0
    for ch in text:
        shown += 2 if ord(ch) > 0x2E7F else 1
    return shown


def _pad(text: str, width: int) -> str:
    """按显示宽度补空格。"""
    return text + " " * max(0, width - _shown_width(text))


def render_text(stats: ErrorStats) -> list[str]:
    """渲染成"角色 × 类目"小表 ＋ 合计 ＋ 类目释义。CLI 与非 CLI 调用共用这一份。"""
    lines: list[str] = []
    events = stats.sources.get("events") or {}
    sessions = stats.sources.get("sessions") or {}
    lines.append("错误动作计数（按角色 × 类目；只读，零模型调用）")
    lines.append(f"三态    checked={stats.checked}  state={stats.state}")
    if stats.reason:
        lines.append(f"原因    {stats.reason}")
    lines.append(
        "读数    事件流 {ev} 条（{evbad} 行读不明白）/ 会话记录 {ss} 条（{files} 个文件，"
        "{ssbad} 行读不明白）".format(
            ev=events.get("events", 0), evbad=events.get("bad_lines", 0),
            ss=sessions.get("records", 0), files=sessions.get("files", 0),
            ssbad=sessions.get("bad_lines", 0)))
    if not stats.checked:
        lines.append("")
        lines.append("没有读到该读的东西 ⇒ 这里的 0 不是『没有错误动作』，是『没查成』。")
    unclassified = int(events.get("unclassified") or 0)
    if unclassified:
        lines.append(f"未归类  {unclassified} 条被拒的理由码不在码表里（未计入任何类目；"
                     "要收进来就把它登记进 CODE_TABLE）")

    cats = list(stats.categories().items())
    if not cats:
        lines.append("")
        lines.append("按角色 × 类目：全 0（三类判据一条都没命中）" if stats.checked
                     else "按角色 × 类目：无可报读数")
        return lines

    head = ["角色"] + [cat for cat, _n in cats] + ["合计"]
    rows: list[list[str]] = []
    for role in sorted(stats.role_total):
        rows.append([role] + [str(stats.count(role, cat)) for cat, _n in cats]
                    + [str(stats.role_total.get(role, 0))])
    rows.append(["合计"] + [str(n) for _cat, n in cats] + [str(stats.total)])

    widths = [max(_shown_width(head[i]), *(_shown_width(r[i]) for r in rows))
              for i in range(len(head))]
    widths = [max(w, 4) for w in widths]
    lines.append("")
    lines.append("  ".join(_pad(head[i], widths[i]) for i in range(len(head))).rstrip())
    lines.append("  ".join("-" * widths[i] for i in range(len(head))))
    for row in rows:
        lines.append("  ".join(_pad(row[i], widths[i]) for i in range(len(head))).rstrip())

    lines.append("")
    lines.append("类目释义：")
    meanings = dict(ERROR_CATEGORIES)
    for cat, _n in cats:
        lines.append(f"  {cat}: {meanings.get(cat, '')}")
    lines.append("")
    lines.append("口径：角色归属见 errorstats 模块 docstring（召唤期结构判据记 called_by）；"
                 "一条记录只算一次，主码 = 类目表靠前的类目优先、同类目里长码优先。")
    return lines


def stats_json(stats: ErrorStats) -> str:
    """机器可读一行（`--json` 用）。"""
    return json.dumps(stats.as_dict(), ensure_ascii=False, indent=2)
