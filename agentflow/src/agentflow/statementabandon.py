# -*- coding: utf-8 -*-
"""「放弃原命题」的标记与写入口：`abandoned@<ISO8601>@<理由>`。

业主 2026-11-01 逐字裁定：

> 「每个命题和证明的产出最终必须以V签收尾，拿不到V签就得一直改，或者放弃原命题」

于是"已登记的命题"只许落在两处：有 V 签，或明确放弃（带理由与时间）。
"明确"这个词在盘上要有载体，否则 `status="abandoned"` 只是换了一个字面量：
一条被标成放弃、却读不出为什么、也不知道什么时候放弃的命题，与"悬着"没有区别
（读的人既没法复核，也没法回答"这件事是几时被放下的"）。

本模块是这件事的唯一实现：`abandon_marker`（拼装）、`parse_abandon`（解析）、
`apply_abandonment`（写：改状态 + 落理由与时间 + 作废重送义务）。`schema` 的
数据面校验与 `closing` 的两格读数都从这里取，不各写一份。

## 为什么标记住在 `quote_reason`，而不是新加两列

同一张表的 `pending_definition`（`draft/93·续` D12 甲）已经用同一套手法把
"为什么空着、谁来补"写进 `quote_reason` 的受控标记（`concept:pending_search` /
`concept:self_authored`，唯一出处是 `migrate_concepts`），由 `schema.Statement.validate`
逐条核。这里照抄那一条纪律：不新增列（新增列就是改磁盘契约，属 FC-27 的
schema 迁移，能不做就不做），标记的写侧（`abandon_marker`）与读侧
（`parse_abandon`）只此一份实现，`schema` 与 `closing` 都从这里取 ——
两处各写一份正则，"什么算明确放弃"就会在两个出口长出两种答案。

## 形状与三态

`abandoned@2026-11-01T21:10:00+08:00@证明第 5 步补不出来，改不动了`

- 时间必须是 `datetime.fromisoformat` 认得的 ISO8601（带不带时区都行，带更好）；
- 理由非空；理由里允许再出现 `@`（只切前两刀），也允许中文与换行；
- `parse_abandon` 的三态：`checked=True` = 是一条可解析的放弃标记；
  `checked=False` + `why` = 不是（空、前缀不对、时间坏了、理由空）。
  `checked=False` 绝不是"没有放弃"——它说的是"这一行自称放弃，而拿不出理由与时间"，
  那种行在收工读数里按未签计（`statements_unsigned` 的
  `abandoned_without_reason` 那一类），而不是按"已放弃"放行。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

#: 标记前缀。它与 `schema.STATEMENT_STATUSES` 里的 `abandoned` 同源命名：
#: 状态那一格说"这一行放弃了"，这一格说"为什么、什么时候"。
ABANDON_MARKER = "abandoned@"

#: 字段分隔符：`<前缀><ISO8601><分隔符><理由>`。
ABANDON_SEP = "@"

# ---------------------------------------------------------------- 换号理由（业主 2026-11-07 裁定）
#
# 业主逐字（这是本节的验收标准）：
#
# > 「换号需给清理由：1.命题有实质数学错误；2.证明过程中遇到难以逾越的困难。
# >   对于1，需在换号理由中指出错误；对于2，需指出困难，并将原先证明中可取之处拆出落成引理。」
#
# 改前 `quote_reason` 里那段理由是自由文本：写一句"无干净依据"就能过
# （98 的真机读数：000040–000048 九条同一秒批量放弃，理由逐字都是同一句
# "verifications/ 下不存在 0000NN.jsonl"），而"同一 label 再登记一条"这件事
# 在盘上没有任何结构化读数（000049 → 000050：label 同为 `lem:cancel`、
# `line_range` 同为那份稿、"区别只是一处措辞"）。所以这一节把"理由"从一段散文
# 变成两档受控形状：每一档都要求指出业主原话里点名的那样东西。
#
# ## 为什么形状住在 `quote_reason` 里（与上面那段同一个理由）
#
# 不新增列 = 不改磁盘契约（新增列属 FC-27 的 schema 迁移）。所以结构化理由住进
# 理由正文那一格：`abandoned@<ISO8601>@<JSON>`。JSON 的键就是两档各自要求的那几格
# （`abandon_kind` / `abandon_basis` / `defect_ref` / `difficulty` / `salvaged`）。
# 历史行那一段自由文本照旧读得出来（`parse_abandon` 不变），只是它
# `parse_abandon_reason()["structured"]` 为假 —— 于是"这一行的换号理由齐不齐"
# 在盘上是一个可读的读数，而不是靠人去猜那段散文是什么意思。

#: 换号理由的四档。前两档是业主 2026-11-07 原话里的 1 与 2（F 侧注册/放弃闸的
#: `math_error` / `difficulty`）；后两档是同一句裁定同步到 **E 侧数值证明路线**
#: 时业主点名的两个理由（2026-11-07 第二刀，逐字）：
#:
#: > 「F侧的注册+放弃闸需同步到E侧的数值证明路线，只不过E侧放弃的理由为：
#: >   1.发现反例；2.枚举空间过于宏大以致难以在合理成本内实现。」
#:
#: 多一个"其它"就等于给自由文本留了后门（"作业规格不是命题"那一类暂无这一档，
#: 见 `docs/ROLE-GUIDE.md` 同批报告里的待裁项）。
ABANDON_KIND_MATH_ERROR = "math_error"
ABANDON_KIND_DIFFICULTY = "difficulty"
#: E 侧第一档：发现反例（必须给可核的 `experiment_id`，理由正文说清哪个参数组让它假）。
ABANDON_KIND_COUNTEREXAMPLE = "counterexample"
#: E 侧第二档：枚举空间过于宏大（必须给可核的 `space` 读数，理由正文说清为什么在合理
#: 成本内做不到）。
ABANDON_KIND_SPACE_TOO_LARGE = "space_too_large"
ABANDON_KINDS: tuple[str, ...] = (ABANDON_KIND_MATH_ERROR, ABANDON_KIND_DIFFICULTY,
                                  ABANDON_KIND_COUNTEREXAMPLE,
                                  ABANDON_KIND_SPACE_TOO_LARGE)

#: E 侧那两档（"数值证明路线"的两条放弃理由）。判定口与 F 那两档共用同一个
#: :func:`check_abandon_reason` —— 这里只给读数与措辞一个可引用的名字，不是第二份判定。
ABANDON_E_SIDE_KINDS: tuple[str, ...] = (ABANDON_KIND_COUNTEREXAMPLE,
                                         ABANDON_KIND_SPACE_TOO_LARGE)

#: 写口要认的那几个键（两个必填 + 各档按需）。工具声明与白名单都从这里取。
#:
#: `experiment_id` 是 counterexample 档的可核证据；`space` 是 space_too_large 档的
#: 可核读数（后者的字段名走 `numericproof._space_reading` 的既有那一套，不新造）。
ABANDON_PARAM_KEYS: tuple[str, ...] = ("abandon_kind", "abandon_basis", "defect_ref",
                                       "difficulty", "salvaged", "experiment_id",
                                       "space")

#: `salvaged` 里每一条引理的 `kind` 取值 —— 业主原话是"拆出落成引理"。
#:
#: `schema` 里没有 statements.kind 的词表（`schema.Statement.kind: str = "theorem"`，
#: 见 `schema.py:2363` —— 它是个自由字符串，schema 不校验取值）；可判真假的断言类
#: 那几档的真身在 `secretary.PROPOSITION_KINDS`（`secretary.py:1367`：
#: theorem / lemma / proposition / corollary / conjecture）。其中 `lemma` 就是
#: 业主说的"引理"，所以这里直接用它、不需要退到"最接近的一档"。
SALVAGED_KINDS: tuple[str, ...] = ("lemma",)

#: 一条 `defect_ref` 的形状：`verifications/<命题号>.jsonl#<验证号>`（业主给的样例
#: `verifications/<号>.jsonl#v-00000N`）。号必须是 6 位（本仓的 id 宽度）。
DEFECT_REF_RE = re.compile(r"^verifications/(\d{6})\.jsonl#(v-\d{6})$")

#: 语义判定那一问的受控码（`abandon_difficulty_not_genuine` 是业主 2026-11-07 点名的）。
ABANDON_DIFFICULTY_NOT_JUDGED = "abandon_difficulty_not_judged"
ABANDON_DIFFICULTY_NOT_GENUINE = "abandon_difficulty_not_genuine"
ABANDON_SALVAGED_NOT_FROM_PROOF = "abandon_salvaged_not_from_proof"


def abandon_exempt_kinds() -> tuple[str, ...]:
    """哪些 `kind` 明确不是命题、不归放弃闸管（真身 `secretary.NOT_APPLICABLE_KINDS`）。

    ## 为什么闸要改成 fail-closed（2026-11-07 审计 A3）
    改前判据是"`kind in PROPOSITION_KINDS` 才拦"：于是登记口收下的 `example` /
    `remark` / 空 kind（`record_statement` 对 kind 不设词表）一路放行 —— 只要把
    kind 写成一个词表外的值，自由文本放弃就绕过了整道闸。现在只放行明确非命题
    的那两档（`concept` / `definition`，业主 2026-11-07 的边界），其余一律当命题处理。

    独立成一个函数（而不是在各处写 `not in`）：放行面是一份可以单独打桩的判据，
    反真空用例要能把它改宽再看见负控变绿。
    """
    from . import secretary as _SEC

    return tuple(str(k) for k in _SEC.NOT_APPLICABLE_KINDS)


def is_abandon_exempt(kind: Any) -> bool:
    """这个 `kind` 是不是"明确非命题"（`concept` / `definition`）⇒ 不归放弃闸管。"""
    return str(kind or "").strip().lower() in abandon_exempt_kinds()


def abandon_proposition_kinds() -> tuple[str, ...]:
    """哪些 `kind` 算"命题"（读侧/报错文案用的正向词表）。

    真身是 `secretary.PROPOSITION_KINDS`（theorem / lemma / proposition /
    corollary / conjecture）：`schema` 对 `statements.kind` 没有词表
    （`Statement.kind` 是自由字符串，见 `schema.py:2363` 一带），"可判真假的断言类"
    只在这一处被定义过。

    ## 它与放行面的关系（2026-11-07 改）
    改前放弃闸用的是"`kind in abandon_proposition_kinds()` 才拦"，于是词表外的
    kind（`example` / `remark` / 空串）直接不拦。现在放行面才是判据：
    :func:`is_abandon_exempt` 只认 `concept` / `definition` 两档，其余（含认不出的）
    全按命题处理。这个函数因此只用于读数与措辞，不再被当作"要不要拦"的分界线。
    """
    from . import secretary as _SEC

    return tuple(str(k) for k in _SEC.PROPOSITION_KINDS)


def _step_pattern(step: int) -> re.Pattern[str]:
    """`<理由>` 里点名第 `step` 步的几种写法（中文与英文，空格可有可无）。"""
    n = int(step)
    return re.compile(
        rf"(?:第\s*{n}\s*步|步骤\s*{n}|step\s*{n}\b)", re.IGNORECASE)


def _salvaged_items(raw: Any) -> tuple[list[dict[str, str]], str]:
    """把 `salvaged` 归一成 `[{"label":…,"stmt_id":…}]`；形状不对 ⇒ `( [], why )`。"""
    if raw is None:
        return [], "没给 salvaged（这一档必须列出旧证明里可取之处拆成的引理）"
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
        return [], f"salvaged 必须是数组（每条给 label 与 stmt_id），收到 {type(raw).__name__}"
    out: list[dict[str, str]] = []
    for one in raw:
        if isinstance(one, str):
            text = one.strip()
            if not text:
                continue
            # 允许 `000051:lem:xxx` 这种一行写法（label 与号用冒号分开）。
            label, _, sid = text.partition(":")
            if not sid:
                return [], (f"salvaged 里有一条不是 「label:stmt_id」 形状：{text!r}"
                            "（也可以给对象 {label, stmt_id}）")
            out.append({"label": label.strip(), "stmt_id": sid.strip()})
            continue
        if not isinstance(one, Mapping):
            return [], f"salvaged 里有一条既不是字符串也不是对象：{one!r}"
        sid = str(one.get("stmt_id") or one.get("stmt") or "").strip()
        label = str(one.get("label") or "").strip()
        if not sid:
            return [], f"salvaged 里有一条没给 stmt_id：{dict(one)!r}"
        out.append({"label": label, "stmt_id": sid})
    if not out:
        return [], ("salvaged 是空的 ⇒ 受控拒绝（业主原话：将原先证明中可取之处"
                    "拆出落成引理 —— 一条都没有，等于没有可取的旧证明）")
    return out, ""


def _defect_row(store: Any, root: str, sid: str, vid: str) -> tuple[dict[str, Any] | None, str]:
    """按 `verifications/<号>.jsonl` + 验证号取那一行（台账的真身是文件）。"""
    try:
        from . import verifications as _VR

        rows, problems = _VR.list_verifications(root, statement_id=sid, limit=None)
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"，不是"没有这一条"
        return None, f"验证台账读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
    for row in rows:
        if str(row.get("verification_id") or "") == vid:
            return dict(row), ""
    extra = f"（台账坏行：{problems}）" if problems else ""
    return None, (f"`verifications/{sid}.jsonl` 里没有 {vid} 这一行{extra} ⇒ "
                  "引用了一行不存在的判词")


def _defect_refusal(store: Any, root: str, ref: str, basis: str, *,
                    statement_id: str = "",
                    statement: Mapping[str, Any] | None = None,
                    ) -> tuple[dict[str, Any], str, str]:
    """核一条 `defect_ref`：必须真的存在、判词是「有毛病」/轴为 `fault`、
    指向被放弃的这一条、且审的是它现在这一份正文。

    返回 `(detail, refused_code, why)`：成功时 `refused_code` 是空串。

    ## 2026-11-07 审计 C1 之后补的两条（业主「需在换号理由中指出错误」）
    改前只核「那一行存在并且判有毛病」：放弃 000001 时可以引用 000002 的判词
    （跨命题），也可以引用一条对旧正文的判词（改稿后它已经 stale）。两条都不是
    「指出这条命题的错误」。现在：
    - ref 里的命题号必须等于 `statement_id`（`abandon_defect_ref_other_statement`）；
    - 那一行的 `proof_sha256` 必须与现行证明正文（按那一行的 `proof_no` 取）
      的 sha 相同（`abandon_defect_ref_stale`）。没有 sha 的行同样按 stale 拒 ——
      "确认不了审的是哪一份"不许折成"审的就是这一份"。
    """
    m = DEFECT_REF_RE.match(str(ref or "").strip())
    if not m:
        return {}, "abandon_defect_ref_unreadable", (
            f"defect_ref 必须是 `verifications/<6 位命题号>.jsonl#v-<6 位验证号>` "
            f"（收到 {str(ref or '')!r}）")
    sid, vid = m.group(1), m.group(2)
    target = str(statement_id or "").strip()
    if not target:
        return {}, "abandon_target_missing", (
            "这一笔没给被放弃的命题号 ⇒ 没法把 defect_ref 绑到「这一条」上（不猜）")
    if sid != target:
        return {}, "abandon_defect_ref_other_statement", (
            f"{ref} 指的是命题 {sid} 的判词，而这一笔放弃的是 {target} —— "
            "「命题有实质数学错误」必须指出**这一条**自己的错误，不能引用另一条命题的")
    row, why = _defect_row(store, root, sid, vid)
    if row is None:
        return {}, "abandon_defect_ref_unreadable", why
    from . import verifications as _VR

    verdict = _VR.read_verdict(row)
    axis = _VR.secretary_axis(row)
    if not (verdict == "有毛病" or axis == "fault"):
        return {}, "abandon_defect_ref_not_fault", (
            f"{ref} 这一行的判词是 {verdict!r}、轴是 {axis!r} —— 它**不是**「有毛病」"
            "⇒ 不能拿它当「命题有实质数学错误」的依据")
    # ---- 陈旧判词（审计 C1）：审的是旧正文 ⇒ 不能拿来放弃现正文
    no = _VR.proof_no_of(row)
    current_text = _VR.proof_text_of(statement or {}, no)
    current_sha = _VR.proof_sha(current_text)
    row_sha = str(row.get("proof_sha256") or "").strip().lower()
    step = row.get("defect_step")
    detail: dict[str, Any] = {"defect_step": step if isinstance(step, int) else None,
                              "verdict": verdict, "axis": axis,
                              "verification": str(row.get("verification_id") or ""),
                              "proof_no": no,
                              "defect_proof_sha256": row_sha,
                              "current_proof_sha256": current_sha}
    if not row_sha:
        return detail, "abandon_defect_ref_stale", (
            f"{ref} 这一行没有 `proof_sha256` ⇒ 说不出它审的是哪一份正文（没查成不许"
            "折成「审的就是现在这一份」）")
    if row_sha != current_sha:
        return detail, "abandon_defect_ref_stale", (
            f"{ref} 审的是 sha256={row_sha[:12]}… 那一份，而命题 {target} 现行 "
            f"proof #{no} 的 sha256={current_sha[:12]}… ⇒ 这一行「有毛病」是对旧稿的，"
            "改稿之后它已经陈旧，不能拿来当「这一份证明有数学错误」的依据")
    if isinstance(step, int) and step >= 1:
        if not _step_pattern(step).search(str(basis or "")):
            return detail, "abandon_defect_step_mismatch", (
                f"{ref} 指出的缺陷在第 {step} 步，而 abandon_basis 里没有点名"
                f"「第 {step} 步」⇒ 读的人对不上「错在哪一步」（业主原话：需在换号理由中"
                "指出错误）")
    return detail, "", ""


def _experiment_rows(store: Any) -> tuple[dict[str, dict[str, Any]] | None, str]:
    """`experiments` 的全部行（按实验号索引）；读不出来 ⇒ `(None, why)`（三态）。"""
    if store is None:
        return None, "没有 store"
    try:
        return {str(r.get("experiment_id") or ""): dict(r)
                for r in store.rows("experiments")}, ""
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        return None, f"{type(exc).__name__}: {exc}"


def _counterexample_reading(row: Mapping[str, Any]) -> dict[str, Any]:
    """一行实验上的反例读数（`counterexample` 那一格，原样；没有就空）。"""
    raw = row.get("counterexample")
    if isinstance(raw, bool) or raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str):
        text = raw.strip()
        return {"text": text} if text else {}
    if isinstance(raw, (list, tuple)):
        return {"items": list(raw)} if raw else {}
    return {"value": raw}


def _experiment_claims(row: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    """这一行实验检验的是不是**被放弃的这一条**命题（不猜：认不出 ⇒ 不认作这一条）。

    两条认法，任一成立就算（与 B 收 E 的证据时"按正文 / 按 claim_key 认"同一族的宽松度）：
    1. `claim_key` 等于这条命题的 `label` 或 `stmt_id`（写侧自己绑的那一格）；
    2. 归一化之后 `claim` 与这条命题的正文互相包含（一长一短时两个方向都认）。
    """
    key = str(row.get("claim_key") or "").strip()
    label = str(target.get("label") or "").strip()
    sid = str(target.get("stmt_id") or "").strip()
    if key and key in (label, sid):
        return True
    claim = str(row.get("claim") or "").strip()
    body = str(target.get("statement_full") or target.get("statement_text") or "").strip()
    if not claim or not body:
        return False
    try:
        from . import textutil as _T

        claim, body = _T.normalize(claim), _T.normalize(body)
    except Exception:  # noqa: BLE001 —— 归一不了就逐字比（不猜更多）
        pass
    return bool(claim and body) and (claim in body or body in claim)


def _counterexample_refusal(store: Any, eid: str,
                            target: Mapping[str, Any],
                            ) -> tuple[dict[str, Any], str, str]:
    """核一条 counterexample 档的证据（业主 2026-11-07：E 侧放弃理由 1「发现反例」）。

    三条同时成立才算"可核的反例"（缺一条都拒，且逐条说清缺哪一条）：

    1. `experiment_id` 在 `experiments` 里真的有一行（读不出来 = 没查成，也拒）；
    2. 那一行**反驳了**这条命题：`result="refutes"`（schema 硬约束：它必须带非空
       `counterexample` 且 `negation_kind="disproved"`），或它带着非空 `counterexample`
       读数（历史行 / 别的写法）。只有 `supports` 一类 ⇒ 这不是反例；
    3. 那一行检验的是**被放弃的这一条**（`claim_key` / `claim` 认，见
       :func:`_experiment_claims`）—— "引用另一条命题的反例"不是这条命题有反例。

    返回 `(detail, refused_code, why)`。
    """
    rows, why = _experiment_rows(store)
    if rows is None:
        return {}, "abandon_experiments_unreadable", (
            f"`experiments` 读不出来（{why}）⇒ 反例那一格没查成（没查成不是通过）")
    row = rows.get(eid)
    if row is None:
        return {}, "abandon_counterexample_experiment_missing", (
            f"`experiments` 里没有 {eid} 这一行 ⇒ 引用了一行不存在的实验，"
            "拿不出「哪一个参数组让它假」的可核证据")
    reading = _counterexample_reading(row)
    result = str(row.get("result") or "")
    detail: dict[str, Any] = {
        "experiment_id": eid,
        "result": result,
        "negation_kind": str(row.get("negation_kind") or ""),
        "claim": str(row.get("claim") or "")[:400],
        "claim_key": str(row.get("claim_key") or ""),
        "counterexample": reading,
        "refutes": bool(result == "refutes" or reading),
        "claims_this_statement": bool(_experiment_claims(row, target)),
    }
    if result != "refutes" and not reading:
        return detail, "abandon_counterexample_not_refuting", (
            f"实验 {eid} 的 result={result!r}、也没有非空 counterexample 读数 ⇒ "
            "它没有反驳任何命题；「发现反例」这一档要的是一条**证否**的实验")
    if not detail["claims_this_statement"]:
        return detail, "abandon_counterexample_other_statement", (
            f"实验 {eid} 检验的是另一条断言（claim={str(row.get('claim') or '')[:80]!r}、"
            f"claim_key={str(row.get('claim_key') or '')!r}），不是被放弃的这一条 ⇒ "
            "「这条命题有反例」必须指到检验**这一条**的那次实验")
    return detail, "", ""


#: `space` 读数里认作"规模"的键（与 `numericproof` 的既有读口同源，不新造一套）。
#: 区间形态走 `numericproof._bound_dimensions`；枚举例数走 `numericproof._case_count_of`
#: （后者认的键就是 `numericproof.CASE_COUNT_KEYS`）。


def _has_enumeration_scale(mapping: Mapping[str, Any]) -> bool:
    """这一份空间读数里有没有"规模"（区间 / 枚举量）—— 没有就只是一段文字。

    "枚举空间过于宏大"必须是一个**可核的数字**（多少维、各维多大、一共多少例），
    否则"太大了"这种自由文本也能当理由。判据本体全部复用 `numericproof` 的既有读口：
    `_bound_dimensions`（`[lo, hi]` 形态的整数区间）与 `_case_count_of`（枚举例数）。
    """
    from . import numericproof as _NP

    try:
        bound_cases, _dims = _NP._bound_dimensions(dict(mapping))
    except Exception:  # noqa: BLE001 —— 读不出来就是"没有规模"
        bound_cases = None
    cases = _NP._case_count_of(dict(mapping))
    if bound_cases is not None or cases:
        return True
    for value in mapping.values():
        if isinstance(value, Mapping) and _has_enumeration_scale(value):
            return True
    return False


def _space_reading_of(raw: Any) -> tuple[dict[str, Any], str, str]:
    """把放弃理由里的 `space` 读成一份可核读数（E 侧放弃理由 2「枚举空间过于宏大」）。

    业主 2026-11-07（逐字）：「枚举空间过于宏大以致难以在合理成本内实现」。
    "宏大"必须是一个**读数**，不是一句形容词 —— 所以这一格只认结构化的空间数据，
    读口走 `numericproof._space_reading` 的既有字段（`search_bound` / `SPACE_KEYS`），
    这里不新造字段名、不另写一份读法。

    认两种形态（都来自盘上既有行）：
    - 直接给搜索空间对象（区间 `[lo, hi]` / `n_cases` 一类计数 / `SPACE_KEYS` 里的键）；
    - 给实验行那三格 `{"observations": …, "certificate": …, "search_bound": …}`。

    三态（业主：**读数读不到 ⇒ 受控拒，fail-closed**）：
    - `abandon_space_required`：这一格是空的；
    - `abandon_space_unreadable`：给的不是对象 / 对象里读不出任何空间读数；
    - `abandon_space_not_a_reading`：读出来的是一段文字（或没有任何规模数字）——
      "太大了"这种词面**不能**代替读数。

    返回 `(detail, refused_code, why)`；成功时 code 为空。
    """
    from . import numericproof as _NP

    if raw is None or raw == "" or raw == {} or raw == ():
        return {}, "abandon_space_required", (
            "space_too_large 这一档必须给 `space`（枚举参数与规模，取 "
            "`numericproof._space_reading` 的既有字段）—— 业主原话："
            "「枚举空间过于宏大以致难以在合理成本内实现」；「宏大」必须有读数")
    if isinstance(raw, (str, bytes)):
        return {}, "abandon_space_unreadable", (
            f"space 收到的是自由文本 {str(raw)[:60]!r} ⇒ 这不是读数："
            "「太大了」这类词面不能代替枚举参数与规模（要给对象：各维区间 / 枚举例数）")
    if not isinstance(raw, Mapping) or not raw:
        return {}, "abandon_space_unreadable", (
            f"space 必须是对象（收到 {type(raw).__name__}）—— 它是枚举参数与规模，"
            "不是一段散文")
    obs = raw.get("observations") if isinstance(raw.get("observations"), Mapping) else {}
    cert = raw.get("certificate") if isinstance(raw.get("certificate"), Mapping) else {}
    bound = raw.get("search_bound") if isinstance(raw.get("search_bound"), Mapping) else {}
    if obs or cert or bound:
        value, where = _NP._space_reading(dict(obs), dict(cert), dict(bound))
    else:
        # 直接给搜索空间对象：先按 observations 那一格读（`SPACE_KEYS` 的既有读口），
        # 读不到再把整份当 `search_bound` 读（同一份读口对非空 search_bound 原样返回）——
        # 两种形态都是 `numericproof._space_reading` 认的，不新造字段。
        value, where = _NP._space_reading(dict(raw), {}, {})
        if value is None:
            value, where = _NP._space_reading({}, {}, dict(raw))
    if value is None or value == "" or value == {} or value == []:
        return {}, "abandon_space_unreadable", (
            "space 里读不到搜索空间（`numericproof._space_reading` 的 "
            f"`search_bound` / {list(_NP.SPACE_KEYS)} 都没有可用值）⇒ 没查成不许折成"
            "「空间很大」")
    if isinstance(value, str):
        return {}, "abandon_space_not_a_reading", (
            f"space 读到的是一段文字（{value[:60]!r}）⇒ 它没有枚举参数、也没有规模；"
            "「枚举空间过于宏大」要的是可核的区间 / 枚举例数，不是一句形容词")
    if not isinstance(value, Mapping) or not _has_enumeration_scale(value):
        return {}, "abandon_space_not_a_reading", (
            "space 里没有任何规模读数（各维 `[lo, hi]` 区间或 "
            f"`{list(_NP.CASE_COUNT_KEYS)}` 一类的枚举例数）⇒ 读不出「多宏大」，"
            "不能拿词面代替读数")
    return {"space": dict(value), "space_where": where}, "", ""


def _parse_stamp(value: Any) -> datetime | None:
    """ISO8601 时间戳（读不出来 ⇒ `None`，不猜）。"""
    try:
        return datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _registered_before(created_at: Any, at: Any) -> tuple[bool, str]:
    """`created_at` 是否不晚于 `at`（README 口径：按 created_at 判，给读数不靠猜）。

    返回 `(ok, why)`。两个时间戳都读不出来、或一个带时区一个不带而补不齐 ⇒ 不成立
    （"确认不了它是不是这一次放弃之前就有的"不许折成"是"）。
    """
    made, ref = _parse_stamp(created_at), _parse_stamp(at)
    if made is None:
        return False, f"created_at 读不出来（{created_at!r}）"
    if ref is None:
        return False, f"放弃时间读不出来（{at!r}）"
    if (made.tzinfo is None) != (ref.tzinfo is None):
        tz = ref.tzinfo or made.tzinfo
        if made.tzinfo is None:
            made = made.replace(tzinfo=tz)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=tz)
    try:
        if made <= ref:
            return True, ""
        return False, f"created_at={str(created_at)!r} 晚于放弃时刻 {str(at)!r}"
    except TypeError as exc:  # noqa: BLE001 —— 两个时间戳不可比 ⇒ 没查成
        return False, f"两个时间戳不可比（{type(exc).__name__}: {exc}）"


def check_abandon_reason(store: Any, *, kind: Any, basis: Any, defect_ref: Any = "",
                         difficulty: Any = "", salvaged: Any = (),
                         experiment_id: Any = "", space: Any = None,
                         root: str = "", statement_id: Any = "",
                         at: Any = "", statement: Mapping[str, Any] | None = None,
                         difficulty_judge: Any = None,
                         judgment_required: bool = False) -> dict[str, Any]:
    """换号理由的唯一判据（四档）：返回 `{checked, refused, why, problems, …}`。

    这是业主 2026-11-07 那句裁定的机器落点。两个写口（`apply_abandonment` 与
    `Secretary.amend_statement_meta`）都只调它，不各写一份校验 —— 两处各写一份，
    "什么算给清了理由"就会在两个出口长出两种答案。

    ## 四档各自要求什么（2026-11-07 审计之后 + E 侧同步的完整版）
    | `abandon_kind` | 必须给 | 判据 |
    |---|---|---|
    | `math_error` | `defect_ref` + `abandon_basis` | `defect_ref` 里的命题号必须等于 `statement_id`；那一行必须真的存在、「有毛病」或轴为 `fault`；`proof_sha256` 必须与现行正文一致（陈旧 ⇒ 拒）；`abandon_basis` 必须点名 `defect_step` |
    | `difficulty` | `difficulty` + `salvaged` + `abandon_basis` | `salvaged` 非空；每条在册、`status=active`、引理类；不许指被放弃的这条自己；必须在这笔放弃之前就在册（按 `created_at`）；最后再过一次秘书语义判定（:func:`difficulty_judge`：这是不是真困难、难在哪，以及那几条引理是不是从旧证明里拆出来的） |
    | `counterexample` | `experiment_id` + `abandon_basis` | `experiment_id` 在 `experiments` 里真有一行；那一行 `result="refutes"` 或带非空 `counterexample` 读数；且它检验的是**这一条**命题（`claim_key` / `claim` 认，见 :func:`_experiment_claims`）。「发现反例」的证据是那一次实验，不是一句"我找到了反例" |
    | `space_too_large` | `space` + `abandon_basis` | `space` 必须是结构化读数（走 `numericproof._space_reading` 的既有字段），且读得出规模（`[lo, hi]` 区间或枚举例数）；读不到 / 只有文字 ⇒ 受控拒（fail-closed） |

    后两档是 **E 侧数值证明路线**的两条放弃理由（业主 2026-11-07 第二刀），判定口与
    前两档是同一个函数：这里不写第二份"像不像反例 / 空间大不大"的判据。

    ## `statement_id` / `at` 为什么是必填的
    审计 C1：改前的 `defect_ref` 没有 target，可以引用另一条命题的「有毛病」行，
    也可以引用一条对旧正文的判词。两件事都要"被放弃的那一条"才判得了，所以
    target 与放弃时刻都进判据。`statement` 给了就直接用它（写口手里有盘上那一行），
    不给就按 `statement_id` 从 `statements` 读。

    ## 语义判定（2026-11-07 审计 B1）
    `difficulty="做不动了"` 能过，是因为改前只查非空。现在 `difficulty_judge` 是一次
    秘书语义判定（`Secretary.judge_abandon_difficulty`，两态 fail-closed，不用字数/
    关键词阈值）；它同时判「那几条 salvaged 是不是从这条命题的旧证明里拆出来的」。
    - `judgment_required=True` 而没给判定面 ⇒ `abandon_difficulty_not_judged`（fail-closed）；
    - 判了但 `genuine=False` ⇒ `abandon_difficulty_not_genuine`；
    - 判了但 `salvaged_from_proof=False` ⇒ `abandon_salvaged_not_from_proof`。
    低层直调（`apply_abandonment` 没有秘书面）不传 `judgment_required`，结构判据照旧 ——
    生产的新放弃只经 `Secretary.amend_statement_meta` 那一口，那里一定传。
    E 侧那两档不看 `difficulty_judge`：它们的证据是"盘上那一行实验 / 那一份空间读数"，
    由本函数的确定性判据核，不另发一次语义判定。

    ## 三态
    `checked=True` = 理由齐；`checked=False` + `refused` = 受控拒绝（一个字节都不写）。
    这里没有"没查成"与"不合格"的折叠：读 `refused` 的具体码就知道缺哪一格。
    """
    out: dict[str, Any] = {
        "checked": False, "refused": "", "why": "", "problems": [],
        "abandon_kind": "", "abandon_basis": "", "defect_ref": "", "difficulty": "",
        "experiment_id": "", "space": {}, "salvaged": [], "detail": {},
    }
    got_kind = str(kind or "").strip()
    got_basis = str(basis or "").strip()
    if not got_kind and not got_basis:
        out.update(refused="abandon_reason_missing",
                   why=("放弃/换号必须给 `abandon_kind`（" + "/".join(ABANDON_KINDS) +
                        "）与 `abandon_basis`（理由正文）两格 —— 只写 status='abandoned' 的"
                        "自由文本理由不算给清了理由（业主 2026-11-07）"))
        return out
    if not got_kind:
        out.update(refused="abandon_reason_missing",
                   why=(f"`abandon_basis` 有了，而 `abandon_kind` 是空的 —— 它只许 "
                        f"{list(ABANDON_KINDS)}：不接受「是哪一档我自己看着办」"))
        return out
    if got_kind not in ABANDON_KINDS:
        out.update(refused="abandon_kind_not_allowed",
                   why=(f"abandon_kind 只许 {list(ABANDON_KINDS)} 之一（收到 {got_kind!r}）—— "
                        "词表外的档不接受：多一档就是给自由文本留后门"))
        return out
    if not got_basis:
        out.update(refused="abandon_reason_missing",
                   why=(f"`abandon_kind={got_kind}` 有了，而 `abandon_basis`（理由正文）是空的 "
                        "⇒ 读的人看不出错在哪 / 难在哪"))
        return out
    out.update(abandon_kind=got_kind, abandon_basis=got_basis)
    root_now = str(root or getattr(store, "root", "") or "")
    # ---- 目标命题（2026-11-07 审计 C1 / C10：判据要有"被放弃的那一条"）
    target_id = str(statement_id or "").strip()
    rows, read_why = _statement_rows(store)
    if rows is None:
        out.update(refused="abandon_statements_unreadable",
                   why=(f"`statements` 读不出来（{read_why}）⇒ 没法核被放弃的那一条"
                        "（没查成，不是通过）"))
        return out
    target = dict(statement) if isinstance(statement, Mapping) else rows.get(target_id)
    if target is None:
        if not target_id:
            out.update(refused="abandon_target_missing",
                       why=("这一笔没给被放弃的命题号 ⇒ defect_ref / salvaged 都没法绑到"
                            "「这一条」上（不猜）"))
        else:
            out.update(refused="abandon_unknown_statement",
                       why=f"命题 {target_id} 不在册 ⇒ 放弃一条不存在的命题（不新建行）")
        return out
    if not target_id:
        target_id = str(target.get("stmt_id") or "").strip()
    out["detail"]["statement_id"] = target_id
    if got_kind == ABANDON_KIND_MATH_ERROR:
        ref = str(defect_ref or "").strip()
        if not ref:
            out.update(refused="abandon_defect_ref_required",
                       why=("math_error 这一档必须给 `defect_ref`（形如 "
                             "`verifications/<号>.jsonl#v-00000N`）—— 业主原话："
                             "「需在换号理由中指出错误」，而指出错误要有可核的那一行"))
            return out
        detail, code, why = _defect_refusal(store, root_now, ref, got_basis,
                                            statement_id=target_id, statement=target)
        if code:
            out.update(refused=code, why=why, defect_ref=ref, detail={**out["detail"], **detail})
            return out
        out.update(defect_ref=ref, detail={**out["detail"], **detail})
        out.update(checked=True, why=f"math_error：理由引到 {ref}（判词「有毛病」）")
        return out
    # ---- counterexample 档（E 侧理由 1：发现反例）
    if got_kind == ABANDON_KIND_COUNTEREXAMPLE:
        eid = str(experiment_id or "").strip()
        if not eid:
            out.update(refused="abandon_counterexample_required",
                       why=("counterexample 这一档必须给 `experiment_id`（认一条**真的**实验行）"
                            "—— 业主原话：「发现反例」；反例的证据是那一次实验，"
                            "不是一句「我找到了反例」。空值不猜实验"))
            return out
        detail, code, why = _counterexample_refusal(store, eid, target)
        if code:
            out.update(refused=code, why=why, experiment_id=eid,
                       detail={**out["detail"], **detail})
            return out
        out.update(experiment_id=eid, detail={**out["detail"], **detail})
        out.update(checked=True,
                   why=(f"counterexample：理由引到实验 {eid}"
                        f"（result={detail.get('result')!r}，反例读数"
                        f"{'有' if detail.get('counterexample') else '在 result 上'}）"))
        return out
    # ---- space_too_large 档（E 侧理由 2：枚举空间过于宏大）
    if got_kind == ABANDON_KIND_SPACE_TOO_LARGE:
        got_space, code, why = _space_reading_of(space)
        if code:
            out.update(refused=code, why=why)
            return out
        out.update(space=dict(got_space.get("space") or {}),
                   detail={**out["detail"], **got_space})
        out.update(checked=True,
                   why=("space_too_large：理由带一份可核的空间读数（出处 "
                        f"{got_space.get('space_where') or '（未知）'}）"))
        return out
    # ---- difficulty 档
    diff = str(difficulty or "").strip()
    if not diff:
        out.update(refused="abandon_difficulty_required",
                   why=("difficulty 这一档必须给 `difficulty`（说清难在哪）—— 业主原话："
                        "「需指出困难」；只写一句「做不动了」不是指出困难"))
        return out
    out.update(difficulty=diff)
    items, why = _salvaged_items(salvaged)
    if why:
        out.update(refused="abandon_salvaged_missing", why=why)
        return out
    problems: list[str] = []
    kept: list[dict[str, str]] = []
    readings: list[dict[str, Any]] = []
    for one in items:
        sid = one["stmt_id"]
        row = rows.get(sid)
        if row is None:
            out.setdefault("problems", []).append(f"{sid}：不在册")
            out.update(refused="abandon_salvaged_not_registered",
                       why=(f"salvaged 里的 {sid} 不在 statements 里 ⇒ 引理必须是真的"
                            "登记过的那一条（受控拒绝，一个字节都不写）"))
            return out
        if sid == target_id:
            out.setdefault("problems", []).append(f"{sid}：指向被放弃的这条自己")
            out.update(refused="abandon_salvaged_self_reference",
                       why=(f"salvaged 里出现了被放弃的这条自己（{sid}）—— 一条正在被放弃的"
                            "命题不能同时充当「旧证明里拆出来的引理」"))
            return out
        status = str(row.get("status") or "")
        if status != "active":
            out.update(refused="abandon_salvaged_not_active",
                       why=(f"salvaged 里的 {sid} 状态是 {status!r}，不是 active ⇒ "
                            "拿一条已作废/已放弃的行当「可取之处」不是把旧证明拆成引理"))
            return out
        kind_now = str(row.get("kind") or "").strip().lower()
        if kind_now not in SALVAGED_KINDS:
            out.update(refused="abandon_salvaged_kind_not_lemma",
                       why=(f"salvaged 里的 {sid} 的 kind 是 {kind_now!r}，而这一档只认引理类 "
                            f"{list(SALVAGED_KINDS)}（业主原话：拆出落成引理）"))
            return out
        before, age_why = _registered_before(row.get("created_at"), at)
        if not before:
            out.update(refused="abandon_salvaged_after_the_abandonment",
                       why=(f"salvaged 里的 {sid} 不是在这笔放弃之前就在册的引理（{age_why}）"
                            " ⇒ 「原先证明中可取之处」必须是旧稿时期的东西，不许现造"))
            return out
        kept.append({"label": one["label"] or str(row.get("label") or ""), "stmt_id": sid})
        readings.append({"stmt_id": sid, "kind": kind_now,
                         "created_at": str(row.get("created_at") or ""),
                         "label": str(row.get("label") or ""),
                         "statement_full": str(row.get("statement_full") or "")})
    out["detail"]["salvaged_readings"] = readings
    # ---- 秘书语义判定（同一个调用同时判「真困难」与「从旧稿拆出」）
    if difficulty_judge is None:
        if judgment_required:
            out.update(refused=ABANDON_DIFFICULTY_NOT_JUDGED,
                       why=("difficulty 这一档要一次秘书语义判定（这是不是真困难、难在哪，"
                            "以及 salvaged 是不是从旧证明里拆出来的），而这一笔没有判定面 ⇒ "
                            "没判成按受控拒处理（不许折成「有理由」）"))
            return out
    else:
        verdict: dict[str, Any]
        try:
            got = difficulty_judge(statement=target, difficulty=diff,
                                   basis=got_basis, salvaged=list(readings))
            verdict = dict(got) if isinstance(got, Mapping) else {}
        except Exception as exc:  # noqa: BLE001 —— 判定炸了 = 没判成（fail-closed）
            verdict = {"checked": False,
                       "reason": f"难度判定调用失败（{type(exc).__name__}: {exc}）"}
        out["detail"]["difficulty_judgment"] = verdict
        if not verdict.get("checked"):
            out.update(refused=ABANDON_DIFFICULTY_NOT_JUDGED,
                       why=("难度语义判定没判成"
                            f"（{verdict.get('reason') or verdict.get('refused') or '没有判定面'}）"
                            " ⇒ 受控拒（「没判成」不许折成「有理由」）"))
            return out
        if not verdict.get("genuine"):
            out.update(refused=ABANDON_DIFFICULTY_NOT_GENUINE,
                       why=("秘书判定：这不是「难以逾越的困难」/没指出难在哪"
                            f"（{verdict.get('reason') or '；'.join(verdict.get('problems') or [])}）"
                            " ⇒ 受控拒"))
            return out
        if not verdict.get("salvaged_from_proof"):
            out.update(refused=ABANDON_SALVAGED_NOT_FROM_PROOF,
                       why=("秘书判定：salvaged 里那几条不是从这条命题的原证明里拆出来的"
                            f"（{verdict.get('reason') or '；'.join(verdict.get('problems') or [])}）"
                            " ⇒ 受控拒"))
            return out
    out.update(salvaged=kept, checked=True,
               why=(f"difficulty：指出困难 + 把旧证明可取之处拆成 {len(kept)} 条引理"
                    f"（{'、'.join(one['stmt_id'] for one in kept)}）"))
    return out


def _statement_rows(store: Any) -> tuple[dict[str, dict[str, Any]] | None, str]:
    """`statements` 的全部行（按号索引）；读不出来 ⇒ `(None, why)`（三态）。"""
    if store is None:
        return None, "没有 store"
    try:
        return {str(r.get("stmt_id") or ""): dict(r) for r in store.rows("statements")}, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def structured_reason(*, kind: str, basis: str, defect_ref: str = "",
                      difficulty: str = "", salvaged: Sequence[Mapping[str, str]] = (),
                      experiment_id: str = "", space: Mapping[str, Any] | None = None) -> str:
    """把各档理由拼成落盘那一段（`quote_reason` 里 `@` 之后的正文）。

    形状是 JSON（`ensure_ascii=False`、键排序）：它必须能被机器逐格读回
    （读数要按 `abandon_kind` 分组、要判"是否带证据"），而自由文本做不到这件事。
    人类可读的那一段是 `abandon_basis` 这一格本身 —— 它没有被压缩成标签。

    E 侧那两档各多一格可核证据：`experiment_id`（counterexample）与 `space`
    （space_too_large）。它们与 `defect_ref` 同一条纪律 —— 只有给了值才落键，
    历史行逐字不变。
    """
    payload: dict[str, Any] = {"abandon_kind": str(kind or ""),
                               "abandon_basis": str(basis or "").strip()}
    if str(defect_ref or "").strip():
        payload["defect_ref"] = str(defect_ref).strip()
    if str(difficulty or "").strip():
        payload["difficulty"] = str(difficulty).strip()
    if str(experiment_id or "").strip():
        payload["experiment_id"] = str(experiment_id).strip()
    if isinstance(space, Mapping) and space:
        payload["space"] = dict(space)
    items = [{"label": str(one.get("label") or ""), "stmt_id": str(one.get("stmt_id") or "")}
             for one in (salvaged or ())]
    if items:
        payload["salvaged"] = items
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=str)


def parse_abandon_reason(text: Any) -> dict[str, Any]:
    """读一条放弃标记里的结构化理由（读侧唯一实现）。

    返回 `{"checked", "structured", "abandon_kind", "abandon_basis", "defect_ref",
    "difficulty", "salvaged", "experiment_id", "space", "complete", "why"}`。
    三态与原模块同一条纪律：

    - `structured=False` ⇒ 这是历史行（`@` 之后是一段自由文本）：结构化的那几格
      一个都读不出来，`why` 说明"换号理由不齐" —— 它不是"没有理由"；
    - `structured=True` 而 `complete=False` ⇒ 形状能读、但那一档要求的格子缺了
      （例如 math_error 没有 `defect_ref`）⇒ `why` 点名缺哪一格；
    - `complete=True` ⇒ 那一档该有的都在。
    """
    out: dict[str, Any] = {
        "checked": False, "structured": False, "abandon_kind": "", "abandon_basis": "",
        "defect_ref": "", "difficulty": "", "salvaged": [], "experiment_id": "",
        "space": {}, "complete": False, "why": "", "at": "",
    }
    got = parse_abandon(text)
    if not got.get("checked"):
        out["why"] = str(got.get("why") or "不是一条可解析的放弃标记")
        return out
    out["checked"] = True
    out["at"] = str(got.get("at") or "")
    try:
        data = json.loads(str(got.get("reason") or ""))
    except (TypeError, ValueError):
        out["why"] = ("历史行：`@` 之后是一段自由文本，读不出 abandon_kind / abandon_basis"
                      " ⇒ 这一行的换号理由不齐（不是「没有理由」）")
        return out
    if not isinstance(data, Mapping):
        out["why"] = "历史行：`@` 之后的 JSON 不是对象 ⇒ 换号理由不齐"
        return out
    kind = str(data.get("abandon_kind") or "").strip()
    if kind not in ABANDON_KINDS:
        out["why"] = (f"`abandon_kind={kind!r}` 不在 {list(ABANDON_KINDS)} 里 ⇒ 换号理由不齐")
        return out
    out.update(structured=True, abandon_kind=kind,
               abandon_basis=str(data.get("abandon_basis") or "").strip(),
               defect_ref=str(data.get("defect_ref") or "").strip(),
               difficulty=str(data.get("difficulty") or "").strip(),
               experiment_id=str(data.get("experiment_id") or "").strip(),
               space=(dict(data.get("space")) if isinstance(data.get("space"), Mapping) else {}),
               salvaged=[dict(x) for x in (data.get("salvaged") or []) if isinstance(x, Mapping)])
    out["at"] = str(got.get("at") or "")
    if not out["abandon_basis"]:
        out["why"] = "结构化理由里没有 abandon_basis（理由正文）⇒ 换号理由不齐"
        return out
    if kind == ABANDON_KIND_MATH_ERROR and not out["defect_ref"]:
        out["why"] = "math_error 这一档缺 defect_ref ⇒ 换号理由不齐"
        return out
    if kind == ABANDON_KIND_DIFFICULTY and not (out["difficulty"] and out["salvaged"]):
        out["why"] = "difficulty 这一档缺 difficulty 或 salvaged ⇒ 换号理由不齐"
        return out
    if kind == ABANDON_KIND_COUNTEREXAMPLE and not out["experiment_id"]:
        out["why"] = "counterexample 这一档缺 experiment_id ⇒ 换号理由不齐"
        return out
    if kind == ABANDON_KIND_SPACE_TOO_LARGE and not out["space"]:
        out["why"] = "space_too_large 这一档缺 space（枚举参数与规模）⇒ 换号理由不齐"
        return out
    out.update(complete=True)
    return out


def relabel_events(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按 `label` 收"放弃/换号"这一件件事（读侧唯一实现，换号读数与登记读数共用）。

    一次 `abandoned` 就是一次"这一条被放下了"；同一个 label 下出现 N 次，就是这条
    定理名换号 N 次（98 的 `lem:cancel`：000049 与 000050 各一次 ⇒ 2 次）。
    不做阈值拦截（业主只要它显形）：这里只给读数，判不判门由调用方决定。

    返回 `{label: [{"stmt_id","at","kind","abandon_kind","has_evidence","structured",
    "complete","basis"}]}`。空 label 的行不进（没有定理名就没有"换号"这件事）。
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows or ():
        if str(row.get("status") or "") != "abandoned":
            continue
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        parsed = parse_abandon_reason(row.get("quote_reason"))
        out.setdefault(label, []).append({
            "stmt_id": str(row.get("stmt_id") or ""),
            "at": str(parsed.get("at") or ""),
            "kind": str(row.get("kind") or ""),
            "abandon_kind": str(parsed.get("abandon_kind") or ""),
            "structured": bool(parsed.get("structured")),
            "complete": bool(parsed.get("complete")),
            "has_evidence": bool(parsed.get("defect_ref")
                                 or parsed.get("experiment_id")
                                 or parsed.get("space")
                                 or (parsed.get("difficulty") and parsed.get("salvaged"))),
            "basis": _basis_digest(parsed),
        })
    return out


def _basis_digest(parsed: Mapping[str, Any], limit: int = 80) -> str:
    """理由正文的摘要（读数里给人看的那一截；不截断就整段进报告）。"""
    text = str(parsed.get("abandon_basis") or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= limit else text[:limit] + "…"


def abandon_marker(*, at: str, reason: str) -> str:
    """拼一条放弃标记（写侧唯一实现）。理由为空 ⇒ `ValueError`（不许静默丢理由）。

    为什么时间由调用方给而不是在这里取 `now()`：这一格要能被判据钉死
    （测试里两条一模一样的输入必须给出同一个字符串），"现在几点"的来源留在调用点。
    """
    got = str(reason or "").strip()
    if not got:
        raise ValueError(
            "放弃必须给理由：只写一个 status='abandoned' 等于把'为什么放下'记成一笔"
            "没人能接手的账（与 `quote_verified` 的三态纪律同一条）")
    stamp = str(at or "").strip()
    try:
        datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise ValueError(
            f"放弃标记的时间必须是 ISO8601（收到 {stamp!r}）：{exc}") from exc
    return f"{ABANDON_MARKER}{stamp}{ABANDON_SEP}{got}"


def parse_abandon(text: Any) -> dict[str, Any]:
    """读一条放弃标记（读侧唯一实现）：`{"checked","at","reason","why"}`。

    三态见模块 docstring：`checked=False` 说的是"这不是一条可解析的放弃标记"，
    不是"没有放弃"。
    """
    out: dict[str, Any] = {"checked": False, "at": "", "reason": "", "why": ""}
    raw = str(text or "").strip()
    if not raw:
        out["why"] = "`quote_reason` 是空的 ⇒ 拿不出理由与时间"
        return out
    if not raw.startswith(ABANDON_MARKER):
        out["why"] = (f"`quote_reason` 不以 {ABANDON_MARKER!r} 开头"
                      f"（收到 {raw[:40]!r}）⇒ 这不是一条放弃标记")
        return out
    rest = raw[len(ABANDON_MARKER):]
    stamp, sep, reason = rest.partition(ABANDON_SEP)
    stamp, reason = stamp.strip(), reason.strip()
    if not sep:
        out["why"] = (f"标记缺第二刀：要 `{ABANDON_MARKER}<ISO8601>{ABANDON_SEP}<理由>`，"
                      f"收到 {raw[:60]!r}")
        return out
    out["at"] = stamp
    try:
        datetime.fromisoformat(stamp)
    except ValueError:
        out["why"] = (f"标记里的时间不是 ISO8601（{stamp!r}）⇒ 读不出「什么时候放弃的」")
        return out
    if not reason:
        out["why"] = "标记里有时间没有理由 ⇒ 读不出「为什么放弃」"
        return out
    out.update(checked=True, reason=reason)
    return out


def _statement_of(row: Mapping[str, Any]) -> Any:
    """盘上那一行 ⇒ `schema.Statement`（`page_range` 是唯一需要还原的对象字段）。"""
    from . import schema as _S

    body = dict(row)
    pr = body.get("page_range")
    body["page_range"] = (_S.PageRange.from_dict(pr) if isinstance(pr, Mapping)
                          else _S.PageRange())
    return _S.Statement(**{k: v for k, v in body.items()
                           if k in _S.Statement.__dataclass_fields__})


def _replayed_marker(current: Mapping[str, Any], was: Mapping[str, Any], *,
                     reason: Any, abandon_kind: Any, abandon_basis: Any,
                     defect_ref: Any, difficulty: Any, salvaged: Any,
                     experiment_id: Any = "", space: Any = None) -> str:
    """这一笔若按"同一个标记原样重放"来读，会拼出哪一条标记（读不出来 ⇒ 空串）。

    幂等重放的口径必须逐字节比标记，而不是比调用方传了什么：`_abandon_reading`
    重放的是"标记里那段理由原文"（没有结构化那几格），而第一次写的是结构化 JSON ——
    两条路拼出来的必须是同一个字符串，否则"重放"会被误读成"改理由"。
    """
    try:
        at = str(was.get("at") or "")
        structured = any(str(x or "").strip() for x in
                         (abandon_kind, abandon_basis, defect_ref, difficulty,
                          experiment_id))
        if isinstance(space, Mapping) and space:
            structured = True
        if salvaged not in (None, "", (), [], {}):
            structured = True
        if not structured:
            return abandon_marker(at=at, reason=str(reason or ""))
        if isinstance(salvaged, (str, bytes)) or not isinstance(salvaged, Iterable):
            if salvaged not in (None, "", (), [], {}):
                return ""      # 形状认不出 ⇒ 不认作幂等（交给闸去拒/去认）
            items: list[dict[str, str]] = []
        else:
            items = []
            for one in salvaged:
                if isinstance(one, str):
                    label, _, sid = one.partition(":")
                    if not sid:
                        return ""
                    items.append({"label": label.strip(), "stmt_id": sid.strip()})
                elif isinstance(one, Mapping):
                    sid = str(one.get("stmt_id") or one.get("stmt") or "").strip()
                    if not sid:
                        return ""
                    items.append({"label": str(one.get("label") or ""), "stmt_id": sid})
                else:
                    return ""
        return abandon_marker(at=at, reason=structured_reason(
            kind=str(abandon_kind or ""), basis=str(abandon_basis or ""),
            defect_ref=str(defect_ref or ""), difficulty=str(difficulty or ""),
            salvaged=items, experiment_id=str(experiment_id or ""),
            space=(dict(space) if isinstance(space, Mapping) else None)))
    except Exception:  # noqa: BLE001 —— 拼不出来就不认幂等，交给后面的闸
        return ""


def apply_abandonment(store: Any, *, statement_id: str, reason: str, at: str = "",
                      actor: str = "secretary-B", abandon_kind: Any = "",
                      abandon_basis: Any = "", defect_ref: Any = "",
                      difficulty: Any = "", salvaged: Any = (),
                      experiment_id: Any = "", space: Any = None,
                      difficulty_judge: Any = None) -> dict[str, Any]:
    """把一条已登记命题标成 `abandoned`（写侧唯一实现：理由与时间一起落盘）。

    这是业主 2026-11-01 那句「拿不到V签就得一直改，或者放弃原命题」里
    "放弃"那一条的落地：它把命题从"还欠一个签"的集合里挪走，同时也把名下开着的
    重送义务作废（`vreceipts.close_resubmits_for`，`close="expired"`）—— 不一起办，
    "放弃"会被"名下还有未消的板项"反锁死（`retire_integrity`）。

    ## 2026-11-07（业主裁定）：放弃"可判真假的断言类"命题时必须给结构化理由
    业主逐字：「换号需给清理由：1.命题有实质数学错误；2.证明过程中遇到难以逾越的困难。
    对于1，需在换号理由中指出错误；对于2，需指出困难，并将原先证明中可取之处拆出落成引理。」
    同日第二刀（E 侧数值证明路线）：「只不过E侧放弃的理由为：1.发现反例；
    2.枚举空间过于宏大以致难以在合理成本内实现」⇒ 同一道闸多两档（`counterexample` /
    `space_too_large`，判据仍是 :func:`check_abandon_reason` 一处）。

    - 明确非命题的两档（`concept` / `definition`，真身
      `secretary.NOT_APPLICABLE_KINDS`）⇒ 不受这道闸管（概念没有"条件 ⇒ 结论"，
      谈不上"命题有数学错误"或"证明遇到困难"）：理由仍必须是可解析的放弃标记
      （`schema.Statement.validate` 那条老闸照旧）。
    - 其余一切 kind（含词表外的 `example` / `remark` / 空串）一律按命题处理
      （2026-11-07 审计 A3：改前"认不出的 kind 不拦"就是一条一行 patch 的绕行）。

    ## 已经把这一条标成 `abandoned` 的行：幂等重放放行，理由变了必须过闸
    历史行（98 里那批只有自由文本的行）必须还能被幂等重放（同一个标记原样重交 ⇒
    `already=True`，不写任何格），否则"先补理由、再关板项"这条路会被闸反锁死。
    但"已 abandoned"不是一张跳过判据的通行证（2026-11-07 审计 A4）：这一笔要把
    `quote_reason` 改成另一段文字 ⇒ 走与第一次放弃同一道闸；自由文本改写照旧
    `abandon_reason_missing`。要补理由，给全那五格（或一份完整的结构化标记）。

    返回 `{"checked","abandoned","already","stmt_id","at","reason","marker",
    "changes","refused","why","resubmits","row","form"}`。三态：

    - `checked=True`：写成了（`abandoned=True`），或本来就是这一档（`already=True`，幂等）；
    - `checked=False` + `refused`：不在册 / 没有 store / 理由空 / 标记拼不出来 /
      命题的换号理由不齐 ⇒ 一个字节都没写（受控拒绝，不是异常）；
    - 校验一律过 `schema.Statement.validate`（数据面唯一判据），这里不另立一份。
    """
    out: dict[str, Any] = {"checked": False, "abandoned": False, "already": False,
                           "stmt_id": str(statement_id or ""), "at": "", "reason": "",
                           "marker": "", "changes": [], "refused": "", "why": "",
                           "resubmits": {}, "row": {}, "form": {}}
    sid = str(statement_id or "").strip()
    if not sid:
        out.update(refused="abandon_missing_id",
                   why="没给命题号 ⇒ 不知道放弃哪一条（不猜）")
        return out
    if store is None:
        out.update(refused="store_unavailable",
                   why="这一层没有 store ⇒ 写不了（不是「已经放弃」）")
        return out
    # 时间由写侧盖：（缺省）取盘上的 now，不接受"没有时间"的放弃 ——
    # 业主这一条要求"带理由与时间"，把时间交给调用方去填是把它变成可选项。
    stamp = str(at or "").strip()
    if not stamp:
        from . import schema as _S

        stamp = _S.now_iso()
    try:
        current = next((dict(r) for r in store.rows("statements")
                        if str(r.get("stmt_id") or "") == sid), None)
    except Exception as exc:  # noqa: BLE001
        out.update(refused="statements_unreadable",
                   why=f"`statements` 读不出来（{type(exc).__name__}: {exc}）⇒ 没查成")
        return out
    if current is None:
        out.update(refused="abandon_unknown_statement",
                   why=f"命题 {sid} 不在册 ⇒ 放弃一条不存在的命题（不新建行）")
        return out
    already = str(current.get("status") or "") == "abandoned"
    existing_marker = str(current.get("quote_reason") or "")
    was = parse_abandon(existing_marker)
    if already and was.get("checked"):
        candidate = _replayed_marker(current, was, reason=reason,
                                     abandon_kind=abandon_kind, abandon_basis=abandon_basis,
                                     defect_ref=defect_ref, difficulty=difficulty,
                                     salvaged=salvaged, experiment_id=experiment_id,
                                     space=space)
        if candidate and candidate == existing_marker:
            out.update(checked=True, abandoned=True, already=True,
                       at=str(was.get("at") or ""), reason=str(was.get("reason") or ""),
                       marker=existing_marker,
                       row=current, why="这一条早就是 abandoned（幂等：不改任何格）")
            out["resubmits"] = close_resubmits(store, statement_id=sid,
                                               why="命题被明确放弃（幂等重放）")
            return out
    # ---- 新的一次放弃 / 改写理由：命题类必须过结构化理由那一关（业主 2026-11-07）----
    kind_now = str(current.get("kind") or "").strip().lower()
    if not is_abandon_exempt(kind_now):
        form = check_abandon_reason(store, kind=abandon_kind, basis=abandon_basis,
                                    defect_ref=defect_ref, difficulty=difficulty,
                                    salvaged=salvaged, experiment_id=experiment_id,
                                    space=space, statement_id=sid, at=stamp,
                                    statement=current, difficulty_judge=difficulty_judge,
                                    judgment_required=bool(difficulty_judge))
        out["form"] = dict(form)
        if not form.get("checked"):
            out.update(refused=str(form.get("refused") or "abandon_reason_missing"),
                       why=str(form.get("why") or "换号理由不齐 ⇒ 整笔不写"))
            return out
        reason = structured_reason(kind=str(form["abandon_kind"]),
                                   basis=str(form["abandon_basis"]),
                                   defect_ref=str(form.get("defect_ref") or ""),
                                   difficulty=str(form.get("difficulty") or ""),
                                   salvaged=form.get("salvaged") or (),
                                   experiment_id=str(form.get("experiment_id") or ""),
                                   space=form.get("space") or None)
    rewrite_at = stamp
    if already and was.get("checked") and str(was.get("at") or ""):
        rewrite_at = str(was.get("at"))       # 补理由不改"几时放下的"那一刻
    try:
        marker = abandon_marker(at=rewrite_at, reason=str(reason or ""))
    except ValueError as exc:
        out.update(refused="abandon_marker_invalid", why=str(exc))
        return out
    got = parse_abandon(marker)
    out.update(at=str(got.get("at") or ""), reason=str(got.get("reason") or ""),
               marker=marker)
    row = dict(current)
    row["status"] = "abandoned"
    row["quote_reason"] = marker
    try:
        stmt = _statement_of(row)
        stmt.validate()
    except ValueError as exc:
        out.update(refused="abandon_invalid_row", why=f"这一行过不了数据面校验：{exc}")
        return out
    from . import schema as _S

    data = stmt.to_dict()
    if not already:
        out["changes"] = [f"status: {current.get('status')} → abandoned",
                          f"quote_reason: {existing_marker[:40]!r} "
                          f"→ {marker[:60]!r}"]
    elif existing_marker != marker:
        out["changes"] = [f"quote_reason: {existing_marker[:40]!r} → {marker[:60]!r}"]
    try:
        with store.tx("statements", actor=str(actor or "secretary-B"),
                      note=f"statement:abandoned:{got.get('at')}") as tx:
            live = next((r for r in tx.rows("statements")
                         if str(r.get("stmt_id") or "") == sid), None)
            if live is None:
                out.update(refused="abandon_unknown_statement",
                           why=f"命题 {sid} 在写事务里不见了 ⇒ 整笔不写")
                return out
            tx.upsert("statements", data, note="statement:abandoned")
    except ValueError as exc:
        out.update(refused="abandon_write_refused", why=str(exc))
        return out
    except Exception as exc:  # noqa: BLE001
        out.update(refused="abandon_write_failed",
                   why=f"写不进去（{type(exc).__name__}: {exc}）⇒ 一行都没改")
        return out
    out.update(checked=True, abandoned=True, row=data,
               why=(f"命题 {sid} 已明确放弃（{got.get('at')}）：理由已随标记落盘，"
                    "名下开着的重送义务一并作废"))
    out["resubmits"] = close_resubmits(store, statement_id=sid,
                                       why=f"命题 {sid} 被明确放弃")
    return out


def close_resubmits(store: Any, *, statement_id: str, why: str) -> dict[str, Any]:
    """把一条命题名下的重送义务作废（`vreceipts` 的同一份实现，惰性引用避开环）。"""
    try:
        from . import vreceipts as _VRC

        return _VRC.close_resubmits_for(store, statement_id=str(statement_id), why=str(why))
    except Exception as exc:  # noqa: BLE001 —— 作废失败不许带走"放弃"这件事本身
        return {"checked": False, "closed": [], "problems": [f"{type(exc).__name__}: {exc}"],
                "reason": "重送项作废没跑成（放弃这一笔已经落盘）"}


