# -*- coding: utf-8 -*-
"""缺陷分类与投票（纯读）。

2026-11-20（VERSPLIT2）：`v_defect.py` 是从 `verifications.py` 搬出的 13 块 / 458 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import datetime as _dt


def _findings_of(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """这一行的 findings 里形状可读的那几条（坏形状静默跳过 —— 读侧只做分类，不改历史）。"""
    raw = row.get("findings")
    if not isinstance(raw, (list, tuple)):
        return []
    return [one for one in raw if isinstance(one, Mapping)]


def _fault_kind_text(row: Mapping[str, Any]) -> str:
    """分类时要读的那段话：优先秘书的 `reason`，没有再退到 V 的 `why`。

    为什么先读秘书：98b 的 4 条程序性 fault 全部写在 `secretary_judge.reason` 里，
    行上的 findings 是空的（D3 §2.1：这不是"V 找到了程序性缺陷"，是秘书从"报告里没有
    出现某个句式"推出 fault）。读 `why` 只是兜底：老行没有 `reason` 时不要把整行读成
    "没有依据"，那会把它按 math 兜底（保守方向可接受，但读数会失真）。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    if isinstance(got, Mapping):
        reason = str(got.get("reason") or "").strip()
        if reason:
            return reason
    return str(row.get("why") or "").strip()


def _looks_like_report_gap(text: str) -> bool:
    """这句话是不是只在说「没有记录反例尝试」那一档（98b 的 4 条）。"""
    if "反例" not in text:
        return False
    return any(marker in text for marker in _REPORT_GAP_MARKERS)


def says_only_a_report_gap(text: str) -> bool:
    """写侧入口（D3 批 2）：这句话是不是只在说「没记录反例尝试」。

    为什么要有这一格公开的名字：业主 2026-11-09 裁定 ① 把这一档从 fault 判据里移出，
    而判据本体只有 :data:`_REPORT_GAP_MARKERS` 一处（98b 的 4 条逐字命中）。写侧
    （`agent_v/core.py` 的写行处）要用同一条判据做归类，不许另抄一张关键词表 ——
    两处各写一份，下一次改判据就会只改一处。读侧仍走
    :func:`fault_kind_of` 的 `legacy_shape` 那一支，两处共用这同一个谓词。
    """
    return _looks_like_report_gap(str(text or ""))


def _looks_like_self_declared(text: str) -> bool:
    """这句话是不是 V 自己说「我没逐行验证 / 我判不了」。"""
    return any(marker in text for marker in _SELF_DECLARED_MARKERS)


def _looks_like_style(text: str) -> bool:
    """这句话的依据是不是落在排版 / 术语 / 文风 / 价值判断上。"""
    return any(marker in text for marker in _STYLE_MARKERS)


def _has_math_evidence(row: Mapping[str, Any]) -> bool:
    """行上有没有数学证据：任一 `level=error` 的 finding，或 `defect_step` 非空。"""
    if row.get("defect_step") is not None:
        return True
    return any(str(one.get("level") or "") == "error" for one in _findings_of(row))


def fault_kind_of(row: Mapping[str, Any]) -> dict[str, Any]:
    """这一行的缺陷类别（纯读；D3 批 1 的唯一入口）。

    → `{kind, cause, source, why, report_gap}`

    - `kind` ∈ :data:`FAULT_KIND_VALUES`，或 `""`（不是缺陷 / 明确的 clean）；
    - `cause` ∈ :data:`FAULT_CAUSES` 或 `""`；`report_gap` 只在这里出现，不在 kind 里；
    - `source` ∈ :data:`FAULT_KIND_SOURCES`；`""` = 老行且不是 fault 行；
    - `report_gap`：`secretary_judge.report_gap` 的原话（干净行上的报告质量读数；
      老行没有这一格 ⇒ 空串）；
    - `why`：人读的一句依据（它引哪一条判据、读了哪几个字段）。

    ## 判据（按 D3 §3.1；业主 2026-11-09 裁定 ① 的收口版）

    0. 先看 `secretary_judge` 里有没有 `fault_kind` 这个键（键在不在 = 新行 / 老行，
       不新增字段）：
       - 键在 + 值为空 ⇒ `kind=""`，`source="row"`：明确的 clean（可投票）；
       - 键在 + 值为四类之一 ⇒ 那一类，`source="row"`；
       - 键在 + 值是 `report_gap`（批 1 的旧写法）或 `procedural` 且
         `fault_cause="report_gap"` ⇒ 归到 `kind=""`、`cause="report_gap"`（它不是缺陷）；
       - 键在 + 值不认识 ⇒ 按 `math` 收（fail-closed：一个拼错的 kind 不许静默解锁）。
    1. 键不在 ⇒ 老行，走下面三档读侧推定（不写盘、不改历史）。
    2. 行上有数学证据（`level=error` 的 finding 或 `defect_step`）⇒ `math`，
       `source="legacy_math_evidence"`。这一条永远优先于下面几条：任何
       "procedural/style 带着步号"的行都被折回 math（只往更严的方向折，D3 §5.3）。
    3. 秘书的话只在说「没有记录反例构造尝试」⇒ `kind=""`、`cause="report_gap"`、
       `source="legacy_shape"`。业主 2026-11-09 裁定 ①：它不是缺陷（不锁 sha、不挡签）；
       `kind` 留空是刻意的——这样 `is_a_vote` 不会把它当"矛盾行"吞掉。
    4. 依据落在排版 / 术语 / 文风 / 价值判断 ⇒ `style`，`source="legacy_shape"`。
    5. V 自己说「我没逐行验证 / 我判不了」⇒ `procedural`，`source="legacy_shape"`，
       `cause="self_declared"`。
    6. 上面都不命中、但形状是「verdict=成立 + findings 空 + unresolved_errors=0」⇒
       `procedural`，`source="legacy_shape"`（D3 §5.3 的第 2 条：98b 那 4 行就是它）。
    7. 其余 ⇒ `math`，`source="legacy_default"`（保守兜底：说不清的老行继续锁）。

    ## 为什么 `contract` 只从显式 kind 来

    `contract`（缺 `## 证明` / 引用不可核 / sha 不符 / 稿名解析不出）在现行架构里
    不经秘书：它由 `citation_gate` / `row_signable` / 依赖审计这些机械闸分走
    （D3 §3.4）。一行台账的字段里没有"稿名解析不出"这种事实，读侧硬猜只会把
    数学行误判成契约行（那会静默解锁）。所以老行不推定 `contract`——它只来自新行
    显式写下的那一格（`source="row"`）。这与"旧行一律 math 兜底"同一条纪律。

    ## 为什么 `verdict` 只在旧行推定里读

    新行有 `fault_kind` 这一格（哪怕值为空）时，`verdict` 一个字节都不读
    （p247：V 的判词只是陈述）。旧行没有那一格，才用 `verdict=成立` 当
    "V 没指出缺陷"的形状证据；它不是轴。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    has_key = isinstance(got, Mapping) and "fault_kind" in got
    report_gap = (str(got.get("report_gap") or "").strip()
                  if isinstance(got, Mapping) else "")
    if has_key:
        explicit = str(got.get("fault_kind") or "").strip()
        if not explicit:
            # D3 批 2：clean 行也会带一格 `cause`（唯一取值 `report_gap`）—— 它回答
            # 「这条 clean 判决为什么报告写得薄」。它不参与投票（`is_a_vote` 只读
            # axis / kind / checked / row_signable），只让裁定 ① 的那一档在读数里可查。
            clean_cause = str(got.get("fault_cause") or "").strip()
            clean_cause = clean_cause if clean_cause in FAULT_CAUSES else ""
            return {
                "kind": "", "cause": clean_cause, "source": "row",
                "report_gap": report_gap,
                "why": ("行上显式写了 fault_kind='' ⇒ 明确的 clean（键在 = 新行；"
                        "不套用老行的形状规则）"
                        + (f"；cause={clean_cause}" if clean_cause else "")
                        + (f"；报告质量读数 report_gap={report_gap!r}" if report_gap else "")),
            }
        if explicit == "report_gap":
            # 批 1 的旧写法：report_gap 曾放在 kind 里。读到它按新口径归到 cause，
            # 不按"不认识的 kind"折成 math（那会把一条报告缺口锁成数学缺陷）。
            return {
                "kind": "", "cause": "report_gap", "source": "row",
                "report_gap": report_gap,
                "why": ("行上显式写着 fault_kind='report_gap'（批 1 旧写法）⇒ 按新口径"
                        "归到 cause=report_gap、kind 留空（它不是缺陷，可算票）"),
            }
        if explicit in FAULT_KIND_VALUES:
            cause = ""
            if explicit == "procedural":
                raw_cause = str(got.get("fault_cause") or "").strip()
                cause = raw_cause if raw_cause in FAULT_CAUSES else ""
                if cause == "report_gap":
                    return {
                        "kind": "", "cause": "report_gap", "source": "row",
                        "report_gap": report_gap,
                        "why": ("行上显式写着 procedural + cause=report_gap ⇒ 按新口径"
                                "归到 kind=''、cause=report_gap（它不是缺陷，可算票）"),
                    }
            # 只往更严的方向折：带数学证据的行不许被说成"不锁"的那几类。
            if explicit in ("procedural", "style") and _has_math_evidence(row):
                return {
                    "kind": "math", "cause": "", "source": "guard:carries_math_evidence",
                    "report_gap": report_gap,
                    "why": ("行上显式写着 "
                            f"{explicit}，但它同时带着数学证据（error finding 或 defect_step）"
                            " ⇒ 强制折回 math（护栏只许往更严的方向折）"),
                }
            return {
                "kind": explicit, "cause": cause, "source": "row",
                "report_gap": report_gap,
                "why": f"行上显式写了 fault_kind={explicit!r}（source=row）",
            }
        return {
            "kind": "math", "cause": "", "source": "row", "report_gap": report_gap,
            "why": (f"行上显式写了不认识的 fault_kind={explicit!r} ⇒ 按 math 收"
                    "（fail-closed：一个拼错的类别不许静默解锁）"),
        }

    axis = verifications.ledger_axis(row)
    if axis != "fault":
        return {
            "kind": "", "cause": "", "source": "", "report_gap": report_gap,
            "why": (f"这一行不是 fault 行（axis={axis or '空'}）⇒ 没有缺陷类别"
                    if axis else "这一行没有秘书轴（未判成 / 老行没有这一格）⇒ 没有缺陷类别"),
        }

    findings = _findings_of(row)
    if _has_math_evidence(row):
        step = row.get("defect_step")
        return {
            "kind": "math", "cause": "", "source": "legacy_math_evidence",
            "report_gap": report_gap,
            "why": (f"行上带数学证据（defect_step={step!r}，"
                    f"error finding={sum(1 for f in findings if str(f.get('level') or '') == 'error')} 条）"
                    " ⇒ math（证据在行上，不是形状推定）"),
        }

    text = _fault_kind_text(row)
    if _looks_like_report_gap(text):
        return {
            "kind": "", "cause": "report_gap", "source": "legacy_shape",
            "report_gap": report_gap,
            "why": ("秘书的话只在说「没有记录反例构造尝试」，行上没有数学证据 ⇒ "
                    "cause=report_gap、kind 留空（业主 2026-11-09 裁定 ①：不算缺陷，"
                    "不锁 sha、不挡签；kind 留空是为了让 clean 行照常算票）"),
        }
    if _looks_like_style(text):
        return {
            "kind": "style", "cause": "", "source": "legacy_shape",
            "report_gap": report_gap,
            "why": "依据落在排版/术语/文风/价值判断（不归 V 判的面）⇒ style",
        }
    if _looks_like_self_declared(text):
        return {
            "kind": "procedural", "cause": "self_declared", "source": "legacy_shape",
            "report_gap": report_gap,
            "why": "V 自己说「没逐行验证 / 判不了」⇒ procedural（它没有做出判定）",
        }
    if (str(row.get("verdict") or "").strip() == "成立"
            and not findings
            and int(row.get("unresolved_errors") or 0) == 0):
        return {
            "kind": "procedural", "cause": "", "source": "legacy_shape",
            "report_gap": report_gap,
            "why": ("verdict=成立 + findings 空 + unresolved_errors=0 ⇒ procedural"
                    "（legacy_shape：按 D3 §5.3 的行形状推定）"),
        }
    return {
        "kind": "math", "cause": "", "source": "legacy_default",
        "report_gap": report_gap,
        "why": ("既不显式带 fault_kind、也没有可判的形状 ⇒ math"
                "（legacy_default：保守兜底，继续锁 sha）"),
    }


def _mechanical_gate_of(row: Mapping[str, Any]) -> str:
    """`row_signable` 为假时，点名是哪一道机械闸挡的（只给 :func:`vote_reading` 的 `why`）。"""
    if int(row.get("unresolved_errors") or 0) != 0:
        return "unresolved_errors"
    if signing_gate_problem(row):
        return "citation_gate"
    if citation_blocks(row):
        return "citation_blocks"
    return "row_signable"


def vote_reading(row: Mapping[str, Any]) -> dict[str, Any]:
    """这一行为什么算 / 不算「clean 的那一票」（人读的读数；D3 §5.2）。

    → `{vote, why, axis, kind, cause, report_gap, checked, legacy, kind_source,
         review_call, review_pass, verification_id, at}`

    `why` ∈ `clean` / `no_judgement` / `axis_fault:<kind 或 cause>` /
    `clean_row_carries_fault_kind` / `mechanical_gate:<哪一道>`。

    判据顺序（任一条不成立即 False，fail-closed）：
      ① `secretary_judge.checked=True`（"问过、没判成"不是一票）；
      ② `ledger_axis(row) == "clean"`（fault / 空轴都不是一票）；
      ③ `fault_kind_of(row)["kind"] == ""`（clean 行带 fault_kind = 矛盾行，不采信；
         `cause="report_gap"` 不挡票：它不是缺陷，这正是业主裁定 ① 的落点）；
      ④ `row_signable(row)`（未解决 error / 依赖台账读不成 / 引用核实挡签 —— 机械闸）。

    刻意不做的事（与 D3 §5.2 逐字一致）：不读 `verdict`、不要求 `review_call`、
    不判"签没签"。分组（同一命题 / 证明号 / sha / review_call）与"是不是最近一趟"
    由调用方（D268 的 `sign_reading`）负责；本函数只回答"这一行自己"。

    `legacy` 是 :func:`_is_legacy_row`（没有 `review_call` / `review_pass` 的行）；
    它不是 `kind_source`：98b 的行有 `review_call`（所以 `legacy=False`），
    但没有 `fault_kind` 这一格（所以 `kind_source` 是 `legacy_*`）。两个"legacy"
    在这里指两件事，读数里分开给。
    """
    checked = secretary_judged(row)
    axis = verifications.ledger_axis(row)
    reading = verifications.fault_kind_of(row)
    kind = str(reading.get("kind") or "")
    cause = str(reading.get("cause") or "")
    out: dict[str, Any] = {
        "vote": False,
        "why": "",
        "axis": axis,
        "kind": kind,
        "cause": cause,
        "report_gap": str(reading.get("report_gap") or ""),
        "checked": checked,
        "legacy": _is_legacy_row(row),
        "kind_source": str(reading.get("source") or ""),
        "review_call": str(row.get("review_call") or ""),
        "review_pass": row.get("review_pass"),
        "verification_id": str(row.get("verification_id") or ""),
        "at": str(row.get("at") or ""),
    }
    if not checked:
        out["why"] = "no_judgement"
        return out
    if axis != "clean":
        if not axis:
            out["why"] = "no_judgement"
        else:
            out["why"] = f"axis_fault:{kind or cause or 'unknown'}"
        return out
    if kind:
        out["why"] = "clean_row_carries_fault_kind"
        return out
    if not row_signable(row):
        out["why"] = "mechanical_gate:" + _mechanical_gate_of(row)
        return out
    out["vote"] = True
    out["why"] = "clean"
    return out


def is_a_vote(row: Mapping[str, Any]) -> bool:
    """这一行算不算「clean 的那一票」—— D268 的 `sign_reading.votes` 只数它。

    唯一判据在 :func:`vote_reading`（本函数只是它的 `vote` 那一位），
    别处不许再写一遍 `secretary_judge.checked` / `ledger_axis` / `row_signable` 的组合。
    """
    return bool(vote_reading(row)["vote"])


def report_fix_list(root: str | Path, *, statement_id: str,
                    proof_no: int = 1) -> dict[str, Any]:
    """这一条证明上「报告层面的待改项」（纯读，零模型，不写盘；D3 §4.5）。

    → `{checked, items: [{kind, cause, verification_id, at, sha, addressee,
                           quote, requires_rewrite, attempts, last_at, why}], why}`

    ## 收什么、不收什么

    - 收：`fault_kind ∈ {procedural, style}` 的行 —— 程序性（V 自己说没逐行验证 /
      判不了）与文风（依据落在不归 V 判的面上）。这两类不是对证明的判断，待改的
      是 V 的报告，不是这份正文；
    - 不收：`math` / `contract` —— 那是"缺陷清单"，由 findings / 洗过的转达承载
      （业主 2026-11-09 裁定 ④：「若是 math/contract 的项，不进这张表」）；
    - 不收：`report_gap` 那一档（`kind=""`）—— 它已经是 clean 行上的质量读数，
      不是待改项（业主裁定 ①：它不是缺陷）。

    ## `attempts` 与 `last_at`（裁定 ④ 的落点）

    `attempts` = 同一份 sha 上第几趟程序性/文风退回（按台账行序数，1,2,3…）。
    不设趟数上限：反复重送是可见的（M/人据此决定要不要介入），而不是被一个阈值
    静默熔断。`last_at` 是同一份 sha 上最后一趟的时刻（每一条都带同一个值，
    读的人不必自己再扫一遍）。

    ## 三态

    台账读不成 / 命题号不合法 ⇒ `checked=False` + `why`（"没查成"不是"没有待改项"）。
    没有任何待改项 ⇒ `checked=True, items=[]`：那是一条有内容的读数。

    ## 谁读得到

    1. `obligations` 的重送项正文（送审者读到"不用改稿、可原样再送"）；
    2. M 的收工读数（"V 的报告连续 N 趟不合格"）；
    3. 召唤者下一次派 V 时写进 `task` 散文 —— 框架不自动塞进 V 的审阅材料
       （否则"3 次独立判定"会变成"看着上一轮的被点名处补作业"）。
    """
    sid = str(statement_id or "").strip()
    out: dict[str, Any] = {"checked": False, "items": [], "why": ""}
    if not sid:
        out["why"] = "没有命题号 ⇒ 读不到台账（不是「没有待改项」）"
        return out
    try:
        no = int(_read_proof_no(proof_no)) or 1
    except (TypeError, ValueError):
        no = 1
    try:
        rows, bad = list_verifications(root, statement_id=sid, limit=None)
    except Exception as exc:  # noqa: BLE001 —— 读不成是"没查成"，不是"没有待改项"
        out["why"] = f"台账读不成（{type(exc).__name__}: {exc}）⇒ 没查成"
        return out
    if bad:
        out["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 有读不出来的行（{bad[:3]}）⇒ 没查成"
        return out
    out["checked"] = True
    attempts: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    last: dict[str, str] = {}
    for row in rows:
        if proof_no_of(row) != no:
            continue
        reading = verifications.fault_kind_of(row)
        kind = str(reading.get("kind") or "")
        if kind not in ("procedural", "style"):
            continue
        sha = str(row.get("proof_sha256") or "")
        at = str(row.get("at") or "")
        attempts[sha] = attempts.get(sha, 0) + 1
        got = row.get(SECRETARY_JUDGE_KEY)
        quote = (str(got.get("reason") or "").strip()
                 if isinstance(got, Mapping) else "")
        items.append({
            "kind": kind,
            "cause": str(reading.get("cause") or ""),
            "verification_id": str(row.get("verification_id") or ""),
            "at": at,
            "sha": sha,
            #: 待改的是 V 的报告；板项收件人仍然是送审者（V 没有台账号）——
            #: 这一格是"该谁看"，不是"投给谁"（红线见 `obligations._recipient_now`）。
            "addressee": "V",
            "quote": quote,
            "requires_rewrite": False,
            "attempts": attempts[sha],
            "last_at": at,
            "why": str(reading.get("why") or ""),
        })
        #: 同一 sha 的"最后一趟"：随追加就地更新，不再回头扫一遍 items。
        last[sha] = at
    for one in items:
        one["last_at"] = last.get(str(one["sha"]), str(one["at"] or ""))
    out["items"] = items
    out["why"] = (f"{proof_label(sid, no)} 上有 {len(items)} 条报告层面的待改项"
                  if items else
                  f"{proof_label(sid, no)} 上没有报告层面的待改项（查过了）")
    return out


def defect_scope_of(row: Mapping[str, Any]) -> str:
    """这一行把缺陷归到哪一层：`statement` / `proof` / `style`；`""` = 没分类（CLAIM-INTEGRITY ②）。

    读 `secretary_judge.defect_scope` 那一格（写侧白名单在 `v_ledger_write.py`，
    词表本体在 `v_vocab.DEFECT_SCOPES`）。老行没有这一格 ⇒ 空串，不是"命题层"：
    重送闸只认「明确写下」的 `statement`（没判过不等于判成命题层）。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    if not isinstance(got, Mapping):
        return ""
    scope = str(got.get("defect_scope") or "").strip().lower()
    return scope if scope in DEFECT_SCOPES else ""


#: 「命题层缺陷没改就重送」的受控码（`verify_proof` 的 `reason`，见 `agent_v/core.py`）。
REFUSED_STATEMENT_SCOPE = "statement_scope_fault_unamended"

#: 想查「命题改过没有」而命题台账读不出来（没查成 ≠ 改过了）。
REFUSED_SCOPE_LEDGER = "statement_scope_ledger_unreadable"

#: 算作「命题被 amend 过」的终态（`_statement_amend_history[i]["changes"]["status"]["to"]`）。
#:
#: 只有这三档在说「这条命题不再被当作成立地在册」：`abandoned`（放弃）、
#: `refuted`（判死）、`superseded`（被取代 —— 改对之后重新登记，旧的留作被替代）。
#: `disputed` 不在里面：它仍然断言着那句话（只是有争议），拿它解锁等于"点一下就能过"。
TERMINAL_AMEND_STATUSES: tuple[str, ...] = ("abandoned", "refuted", "superseded")

#: 算作「命题本身被改过」的那几格（正文 / 名字；未来写者若把它们记进 amend 历史也算）。
#:
#: `quote_reason` 不在里面 —— 它是一句注记，改注记不改变命题说的那句话。
#: `kind` 也不在：换个类名（`theorem`→`lemma`）命题一个字没变，拿它解锁等于把闸变成
#: 「改一格不痛不痒的就能过」（`amend_statement_meta` 的白名单里恰好有它）。
AMEND_CELLS: tuple[str, ...] = ("statement_full", "label")


def _amend_cells(entry: Mapping[str, Any]) -> list[str]:
    """一条 amend 历史记录算不算「命题被改过」；算就返回命中的那几格（纯函数）。

    两档任一即算：
    - `status` 改成 :data:`TERMINAL_AMEND_STATUSES` 之一（这条命题不再在册）；
    - `statement_full` / `label` 变了（命题那句话本身变了）。
    """
    changes = entry.get("changes")
    if not isinstance(changes, Mapping):
        return []
    hit: list[str] = []
    status = changes.get("status")
    if isinstance(status, Mapping):
        to = str(status.get("to") or "").strip()
        if to in TERMINAL_AMEND_STATUSES:
            hit.append(f"status→{to}")
    for cell in AMEND_CELLS:
        if cell in changes:
            hit.append(str(cell))
    return hit


def _iso_after(later: Any, earlier: Any) -> bool:
    """`later` 是不是严格晚于 `earlier`（ISO-8601，带不带时区都行，但两边要一致）。

    任何一边读不出来 / 一边有时区一边没有 ⇒ False：算不出先后就不许当"判定之后"。
    这是 fail-closed 的方向（那会让闸保持闭合），不是"没查成"的读数。
    """
    try:
        a = _dt.datetime.fromisoformat(str(later))
        b = _dt.datetime.fromisoformat(str(earlier))
    except (TypeError, ValueError):
        return False
    if (a.tzinfo is None) != (b.tzinfo is None):
        return False
    return a > b


def statement_scope_gate(root: Any, *, statement_id: Any, store: Any = None) -> dict[str, Any]:
    """重送闸：上一次判的是「缺陷在命题层」而命题没改过 ⇒ 这一趟不许重送（CLAIM-INTEGRITY ②）。

    ## 它挡的是什么形状（真机 lp-ball-18 的 000060）

    V 对某一条命题判「有毛病」，`findings` 里给的是「命题本身」的反例（把命题打掉了）。
    B 没有改命题，而是把稿里的命题句改写成一条更弱的命题（把 k=1 也算进"对角方向"），
    再拿改过的证明重送 —— 于是 V 的下一趟审的是一条台账上没有的命题，而
    `contradictions` 那一格只看 `dependencies.status` / `statements.status` / 稿件状态，
    不查"证明证明的是不是台账上那一条"，门照样亮绿。

    结构上的事实是：命题正文在在册行上是只读的（`manuscriptintake._plan_statement`
    的 `CODE_STATEMENT_LOCKED`、`STATEMENT_META_PATCH_KEYS` 的三种格都不含正文）。
    所以"改弱命题"只能发生在稿里，台账那一行原封不动 —— 这一格就是问：
    最后一次把缺陷归到命题层的判定之后，台账那一行有没有被真改过。

    ## 判据（三条，任一成立即放行）

    1. 台账里没有「轴 fault 且 `defect_scope=statement`」的行 ⇒ 闸不适用（老行 / 判的是证明层）；
    2. 那条判定之后有更新的判定把它撤回 / 降级了：后续任一行的轴是 `clean`，
       或 `defect_scope ∈ {proof, style}`（V 自己说缺陷不在命题层）⇒ 放行；
    3. 那条判定之后，命题行的 `_statement_amend_history` 多了一条改「命题本身」的记录
       （`_amend_cells`：`status` 改成 abandoned / refuted / superseded，或正文 / 名字变了）⇒ 放行。

    其余 ⇒ `blocked=True` + 受控码 `statement_scope_fault_unamended`（不问模型、不落台账行）。

    ## 三态（不折平）

    - 台账读不出来 / 命题行读不出来 ⇒ `checked=False` + 受控码 `...ledger_unreadable`，
      而且仍然 `blocked=True`：「没查成」不等于「改过了」（这一档只有工作区坏了才走到）；
    - 查成了、闸不适用 ⇒ `checked=True, blocked=False`；
    - 查成了、该挡 ⇒ `checked=True, blocked=True`。

    ## 这一层机器判不了什么（写进报告，别当成判据）

    "稿里的命题句与台账那一句是不是同一条"—— 本闸不判这个（那需要语义比对，
    而真机那次的弱化句与原文是"看起来很像"的一段话）。本闸只判结构：
    「命题层缺陷之后，台账那一行有没有被改过」。判漏仍然可能：
    若 V 的秘书把命题层缺陷归成了 `proof`，闸就不开。这一条的强度取决于
    `defect_scope` 那一格判得准不准，不取决于这里。
    """
    sid = str(statement_id or "").strip()
    out: dict[str, Any] = {
        "checked": False, "blocked": False, "refused": "", "why": "",
        "statement_id": sid, "rows": 0, "problems": [],
        "trigger": {}, "retraction": {}, "amend": {},
    }
    if not sid:
        out.update(checked=True, why="没有命题号 ⇒ 没有可比的判定（未在册那一支不设这道闸）")
        return out
    try:
        rows, bad = list_verifications(root, statement_id=sid, limit=None)
    except Exception as exc:  # noqa: BLE001 —— 读不成 = 没查成（下面按 fail-closed 挡）
        out.update(why=f"V 的台账读不出来（{type(exc).__name__}: {exc}）⇒ 没查成",
                   refused=REFUSED_SCOPE_LEDGER, blocked=True)
        return out
    rows = [dict(r) for r in (rows or []) if isinstance(r, Mapping)]
    out["rows"] = len(rows)
    out["problems"] = [str(b) for b in (bad or [])]
    #: 最后一次「判 fault 且缺陷在命题层」的那一行（台账是追加式的，序 = 时间序）。
    at = -1
    for i, row in enumerate(rows):
        if (verifications.ledger_axis(row) == "fault"
                and defect_scope_of(row) == "statement"):
            at = i
    if at < 0:
        out.update(checked=True,
                   why=("台账里没有「判 fault 且 defect_scope=statement」的行 ⇒ "
                        "这道闸不适用（判的是证明层 / 老行没这一格）"))
        return out
    trigger = rows[at]
    out["trigger"] = {
        "verification_id": str(trigger.get("verification_id") or ""),
        "at": str(trigger.get("at") or ""),
        "defect_step": trigger.get("defect_step"),
        "proof_sha256": str(trigger.get("proof_sha256") or ""),
        "detail": str((trigger.get(SECRETARY_JUDGE_KEY) or {}).get("reason") or "")
        if isinstance(trigger.get(SECRETARY_JUDGE_KEY), Mapping) else "",
    }
    # ---- ② 后续判定撤回 / 降级（V 自己说缺陷不在命题层）
    for row in rows[at + 1:]:
        axis = verifications.ledger_axis(row)
        scope = defect_scope_of(row)
        if axis == "clean" or scope in ("proof", "style"):
            out.update(checked=True, retraction={
                "verification_id": str(row.get("verification_id") or ""),
                "at": str(row.get("at") or ""), "axis": axis, "defect_scope": scope,
            }, why=(f"那条命题层判定（{out['trigger']['verification_id'] or '?'}）之后，"
                    f"V 又在 {str(row.get('verification_id') or '?')} 判了 "
                    f"{axis or '（无轴）'} / scope={scope or '（未分类）'} ⇒ 归类已撤回 / 降级"))
            return out
    # ---- ③ 命题行在这条判定之后被真改过（`_statement_amend_history`）
    try:
        got = statementledger.by_id(store, stmt_id=sid)
    except Exception as exc:  # noqa: BLE001 —— 读不成 = 没查成（fail-closed 挡）
        out.update(why=(f"命题台账读不出来（{type(exc).__name__}: {exc}）⇒ "
                        "不知道命题改过没有（没查成 ≠ 改过了）"),
                   refused=REFUSED_SCOPE_LEDGER, blocked=True)
        return out
    if not got.get("checked"):
        out.update(why=(f"命题台账读不出来（{got.get('reason') or got.get('why') or '未知原因'}）"
                        "⇒ 不知道命题改过没有（没查成 ≠ 改过了）"),
                   refused=REFUSED_SCOPE_LEDGER, blocked=True)
        return out
    if not got.get("found"):
        # 判定过、而现在这一行不在册（被删 / 换号）⇒ 不再是"同一条命题的重送"。
        out.update(checked=True,
                   why=(f"台账里已经按号读不到 stmt:{sid}（这一行不在册了）⇒ "
                        "没有可 amend 的那一行，也没有可重送的命题"))
        return out
    row_now = dict(got.get("row") or {})
    history = [h for h in (row_now.get("_statement_amend_history") or [])
               if isinstance(h, Mapping)]
    amend_after: list[dict[str, Any]] = []
    for entry in history:
        if not _iso_after(entry.get("at"), out["trigger"]["at"]):
            continue
        cells = _amend_cells(entry)
        if cells:
            amend_after.append({"at": str(entry.get("at") or ""),
                                "by": str(entry.get("by") or ""),
                                "cells": cells})
    out["amend"] = {"history": len(history), "after": amend_after}
    if amend_after:
        out.update(checked=True,
                   why=(f"那条命题层判定（{out['trigger']['verification_id'] or '?'}，"
                        f"{out['trigger']['at']}）之后，命题行被改过（"
                        + "；".join(f"{one['at']} 改 {'/'.join(one['cells'])}"
                                    for one in amend_after[:3])
                        + "）⇒ 放行"))
        return out
    out.update(checked=True, blocked=True, refused=REFUSED_STATEMENT_SCOPE,
               why=(f"V 上一次把缺陷归到了命题层（{out['trigger']['verification_id'] or '?'}，"
                    f"{out['trigger']['at']}）：命题本身不成立 / 表述错 —— 改证明改不掉它。"
                    f"而那条判定之后，这条命题的 `_statement_amend_history` 没有新增一条"
                    f"改命题本身的记录（status→{list(TERMINAL_AMEND_STATUSES)} 或 "
                    f"{list(AMEND_CELLS)} 任一；现有 {len(history)} 条）。"
                    "所以这一趟重送受控拒：不问模型、不落台账行、不签发。"
                    "出路二选一：(i) 先把命题改了再重送 —— 按正确表述重述并重新登记"
                    "（在册行的命题正文是只读的；改正文只能「放弃旧的 + 登记新的」，"
                    "而只改证明正文、命题原文一字不动地重送，正是这条闸要挡的形状）；"
                    "(ii) 让 V 收回归类 —— V 后续判定的 `defect_scope` 写成 proof / style"
                    "（或判 clean）即视为撤回。"))
    return out


def banned_markers_in(proof_text: str) -> list[str]:
    """这份证明里命中了哪些硬禁令短语（I10 的机械那一半，可离线复算）。"""
    text = str(proof_text or "")
    return [m for m in HARD_BAN_MARKERS if m in text]


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from . import statementledger  # 命题台账的取数口（`statement_scope_gate` 读 amend 留痕）
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    DEFECT_SCOPES,
    FAULT_CAUSES,
    FAULT_KIND_VALUES,
    HARD_BAN_MARKERS,
    SECRETARY_JUDGE_KEY,
    VERIFICATIONS_DIR,
    _REPORT_GAP_MARKERS,
    _SELF_DECLARED_MARKERS,
    _STYLE_MARKERS,
)
from .v_citation import (  # noqa: F401 — 实现在 v_citation.py
    citation_blocks,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    _read_proof_no,
    proof_label,
    proof_no_of,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    _is_legacy_row,
    list_verifications,
    row_signable,
    secretary_judged,
    signing_gate_problem,
)
