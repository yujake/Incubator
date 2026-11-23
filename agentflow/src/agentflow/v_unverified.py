# -*- coding: utf-8 -*-
"""未审命题（在册 / pending 两路）。

2026-11-20（VERSPLIT2）：`v_unverified.py` 是从 `verifications.py` 搬出的 2 块 / 226 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。

2026-11-22（VREADFIX）：这条读口改前只按 `history.statement_id` 查签、不区分来源
⇒ 把文献引来的定理（`origin="external_lit"`）当成"F 交了论证、没人签"。真机 lp-ball-15
的收工读数 C6 = `plan_progress_rows`、`got=3`、`state=unknown`，理由逐字点名
`stmt:000125`；而那一行是 `origin=external_lit`、凭据 `lit:000005`、`quote_verified=true`
（`data/statements.json`），它欠的是引文核验，不是 V 的签。现在按
:func:`_needs_signature` 把"我方要升档的命题"与"文献引来的命题"分开：只有前者进
「未签」计数；来源读不出来一律按前者处理（fail-closed ⇒ 仍是 `unknown`，绝不 `pass`）。
取证与判据见 `tests/test_external_lit_is_not_an_unsigned_proposition.py`。
"""

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import jsonlfile as JF


def _claimed_pending_by_statement(
        root: str | Path) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """已认领的 pending 行按命题号分组（"哪些行算已认领"仍只由 :func:`_claimed_pending_rows` 定）。

    为什么要这一层：:func:`unverified_statement_refs` 按号逐条问"这一条有没有签"，而
    `_claimed_pending_rows` 一次就把整个 `verifications/pending/` 读完 ⇒ 一份 plan 的
    `history` 点名几十条时，逐条调用会把同一个目录读几十遍。判据口径一个字不在这里：
    未认领的行（两个号都空）上面那一口自己就不会交出来。
    """
    rows, problems = verifications._claimed_pending_rows(root)
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
        if sid:
            out.setdefault(sid, []).append(row)
    return out, problems


# ---------------------------------------------------------------- 谁需要签（2026-11-22 VREADFIX）
#
# `attack_plans.history` 里的 `statement_id` 有两条来路，而它们欠的东西不是同一件：
#
# - `own_result`（我方提出）：F 交的那一份论证要升到 `pre_theorem` / `theorem`，唯一的路
#   是 V 的签（`evidencebits.derive_grade`：第 2 位 ∧ 第 3 位 ⇒ `pre_theorem`）⇒ 这一条
#   进「未签」计数；
# - `external_lit`（文献里摘的）：凭据是引文（`quote_verified` + `quote_mode` + `span` +
#   `source_lit_id`；第 2 位 `proof_source="citation"`），第 3 位上的文献代号是占位签
#   （读侧 `evidencebits._citation_review_cleared` 把它降成假）⇒ 按设计最多读到「猜想」，
#   要升档得先逐个优化重写、变成我方那一路再拿签（`evidencebits.bits_of` 的 docstring）。
#   所以 V 的签不是它该补的东西，它也不该把「攻」那一格拖成 `unknown`。
#
# 三态不折平：来源读不出来（`statements` 不在盘上 / 坏 JSON / 这一号在表里查不到）⇒
# 判不了 ⇒ 按「我方命题」处理（fail-closed ⇒ 仍是 missing ⇒ 仍是 `unknown`，绝不 `pass`）。
# 这就是 :func:`_needs_signature` 只在读到了 `origin="external_lit"` 那一行时才返回
# `False` 的原因。


def _statement_rows_by_id(
        root: str | Path) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    """`<工作区>/data/statements.json` 的 `stmt_id -> 行`（只读；三态读数随行返回）。

    为什么读盘而不是让调用方传 `store`：这个读口的调用点是收工门
    （`closing._proof_review_backlog`），而收工门有"运行外"的出口（`agentflow closing`）
    —— 那里没有 store，只有工作区目录（与 `papermapping.read_ledger_tables` 同一条理由）。

    读数三态（`checked`）：只有 `True` 才算"知道每一条是从哪来的"。`False` 时 `why` 说清
    缺的是哪一份文件/哪一处读不动 ⇒ 调用方按"我方命题"处理（见 :func:`_needs_signature`），
    不是当成"一条都不欠签"。文件在、但某个命题号不在表里，是"这一号查不到"（另一格
    读数），不是"整张表读不动"。
    """
    out: dict[str, Any] = {"checked": False, "path": "", "rows": 0, "why": ""}
    if not str(root or "").strip():
        out["why"] = ("没给工作区根 ⇒ 读不到 `data/statements.json`"
                      "（这些命题的 `origin` 判不了 ⇒ 按我方命题处理）")
        return {}, out
    # 表文件名只由 `schema.TABLES` 定（不在这里抄第二份字面量）。
    from . import schema as S   # 惰性：本模块在 import 期处在环里，定义全跑完再取

    name = str((S.TABLES.get("statements") or {}).get("file") or "statements.json")
    path = Path(root) / "data" / name
    out["path"] = str(path)
    if not path.is_file():
        out["why"] = (f"`{path}` 不在盘上 ⇒ 这些命题的 `origin` 判不了"
                      "（按我方命题处理：仍要求签）")
        return {}, out
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        out["why"] = (f"`{path}` 读不出来（{type(exc).__name__}: {exc}）⇒ `origin` 判不了"
                      "（按我方命题处理：仍要求签）")
        return {}, out
    rows: Any = doc.get("rows") if isinstance(doc, Mapping) else doc
    if isinstance(rows, Mapping):
        rows = list(rows.values())
    if not isinstance(rows, list):
        out["why"] = (f"`{path}` 里没有 rows 数组 ⇒ `origin` 判不了"
                      "（按我方命题处理：仍要求签）")
        return {}, out
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
        if sid:
            by_id[sid] = row
    out.update(checked=True, rows=len(by_id))
    return by_id, out


def _sign_scope(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """一条命题在「要不要 V 签」这件事上的三格读数：来源 / 现算等级 / 凭据类型。

    只给读数与 `why`，不决定红绿（决定在 :func:`_needs_signature`）：

    - `origin`：`schema.STATEMENT_ORIGINS` 里那两档之一（读不到就是空串）；
    - `grade`：`evidencebits.derive_grade` 现算（盘上存的那一份只当缓存，不当真值）。
      文献引来的行按设计读到「猜想」：第 2 位是引文（`proof_source="citation"`），第 3 位
      的文献代号是占位签、读侧降成假 —— 这是口径，不是缺陷；
    - `credential`：第 2 位是怎么来的（`citation` = 引文 / `own` = 我方证明过程），
      以及 `reviewed_source`（`citation` = 占位签 / `v` = 真签）。
    """
    scope: dict[str, Any] = {"origin": "", "grade": "", "credential": "",
                             "reviewed_source": "", "source_lit_id": "",
                             "quote_state": "", "status": "", "why": ""}
    if not isinstance(row, Mapping):
        scope["why"] = "这一号在 `statements` 里查不到 ⇒ 来源判不了（按我方命题处理）"
        return scope
    scope["origin"] = str(row.get("origin") or "").strip()
    scope["status"] = str(row.get("status") or "")
    scope["source_lit_id"] = str(row.get("source_lit_id") or "")
    try:
        from . import evidencebits as EB   # 惰性：等级/引文状态的唯一来源

        bits = EB.bits_from_row(dict(row))
        evidence = dict(bits.get("evidence") or {})
        scope["grade"] = str(EB.derive_grade(bits, kind=str(row.get("kind") or "")))
        scope["credential"] = str(evidence.get("proof_source") or "")
        scope["reviewed_source"] = str(evidence.get("reviewed_source") or "")
        scope["quote_state"] = str(EB.quote_state(row))
    except Exception as exc:  # noqa: BLE001 —— 算不出来是"没查成"，不是"没有凭据"
        scope["why"] = (f"这一行的五元位/等级现算不出来（{type(exc).__name__}: {exc}）"
                        "⇒ 等级与凭据类型这两格没查成")
    return scope


def _needs_signature(row: Mapping[str, Any] | None) -> bool:
    """这一条命题是不是「我方提出、要升到 `pre_theorem`/`theorem` ⇒ 得有人签」的那一档。

    ## 判据只有一条：来源（`origin`）

    本仓的 `schema.STATEMENT_ORIGINS` 只有两档：

    - `external_lit`：文献引来的 ⇒ 不需要 V 签。它的凭据是引文（`quote_verified` 那一
      套），要升档得先重写（`evidencebits.bits_of` 的 docstring：引用来的命题因此最多到
      猜想）。把它算进"未签"＝要求 V 去签一条他不是作者、也没有稿要审的命题；
    - `own_result`（以及空/认不出的值）：我方提出 ⇒ 需要 V 签。

    ## 为什么不用"看等级"

    等级是派生读数（`evidencebits.derive_grade`），它回答"这条命题现在有多强"，不回答
    "它欠不欠一道工序"。用等级反推会把两件事折起来：一条已经拿到签的 `own_result`（等级
    `pre_theorem`）不欠签，但一条同样等级、签却是过期签的命题仍要重签 —— 那件事由
    `verifications` 的在册/pending 两路判（本函数的下游），不由等级判。

    ## fail-closed

    读不到这一行（`None`：`statements` 不在盘上 / 坏 JSON / 这一号不在表里）⇒ 判不了
    ⇒ 返回 `True`（按我方命题处理 ⇒ 仍是 missing ⇒ 收工门仍是 `unknown`，绝不 `pass`）。

    ## 反真空

    这是"谁欠签"的唯一判据，也是可打桩的那一处：把它打桩成恒 `True`（= 改前"只按号
    查签、不分来源"的口径）⇒ 文献定理立刻又被算成未签，判据
    `tests/test_external_lit_is_not_an_unsigned_proposition.py::test_c_*` 必须回红。
    """
    if not isinstance(row, Mapping):
        return True
    return str(row.get("origin") or "").strip() != "external_lit"


def _excluded_why(scope: Mapping[str, Any]) -> str:
    """文献引来的那一行"为什么不进未签计数"的一句话（指回盘上的凭据）。"""
    lit = str(scope.get("source_lit_id") or "")
    return (
        "这一条是文献引来的（`origin=external_lit`"
        + (f"，`source_lit_id=lit:{lit}`" if lit else "")
        + f"，第 2 位凭据类型={scope.get('credential') or '（未记）'}"
        f"、第 3 位凭据={scope.get('reviewed_source') or '（未记）'}"
        f"、引文状态={scope.get('quote_state') or '（未记）'}"
        f"、现算等级={scope.get('grade') or '（未算出）'}）⇒ 不是「我方待签命题」，"
        "不进入「未签」计数：V 的签不是它该补的东西（它要升档得先重写、变成我方那一路"
        "再拿签），引文核没核过由 `quote_verified` 那一档读")


def _pending_sign_of(root: str | Path, sid: str,
                     claimed_rows: list[dict[str, Any]],
                     stacks: list[tuple[Path, list[dict[str, Any]]]],
                     ) -> tuple[dict[str, Any], str, str, bool]:
    """认领给这一条命题的那一叠 pending 里，「那一签」是哪一行、签不签得住。

    取哪一行与读口① `pending_sign` 同一个实现（2026-11-20 READUNIFY）：改前本读口
    取 `claimed_rows[-1]`（已认领行的尾行），而读口①认已发签锚在的那一行 ⇒ 同一份盘
    一个说"有签"、一个说"没签"（lp-ball-10 的 stmt:000015：锚 u-000024 / 尾行
    u-000025 没轴）。现在两处都交 :func:`verifications._pending_sign_row` 定
    「锚行 / 尾行」，V2FIX 的两路并读结构（在册台账 或 已认领的 pending）一个字没动。

    取整叠而不是只取已认领的行：同一份正文后来那一转即使还没认领，它也仍是这一签之后
    的那一转（lp-ball-12 000071 的 u-000045 判 fault，未认领）。叠里认给别的命题的行
    不进来（不许借光），未认领的行算这一叠的。

    返回 `(tail, pending_row, pending_state, pending_ok)`：那一签的行、它的
    `verification_id`、三态档名、以及它签不签得住。没有已认领行时四格全空
    （`pending_ok=False`）—— 那一档不是"签住了"，是"没有这一路"。
    """
    if not claimed_rows:
        return {}, "", "", False
    last_claimed = claimed_rows[-1]
    want_sha = str(last_claimed.get("proof_sha256") or "")
    pile = [r for r in _pending_stack_of_row(last_claimed, stacks=stacks)
            if str(r.get("proof_sha256") or "") == want_sha
            and _pending_claim_of(r) in ("", sid)]
    picked = verifications._pending_sign_row(root, rows=pile, sha=want_sha)
    tail = dict(picked.get("row") or {})
    return (tail, str(tail.get("verification_id") or ""),
            str(picked.get("state") or ""), bool(picked.get("signable")))


def _missing_why(sid: str, path: Path, claimed_rows: list[dict[str, Any]],
                 pending_row: str, tail: Mapping[str, Any]) -> str:
    """这一条有行（或一行都没有）却没进计数时的那一句理由 —— 三档各自说清是哪一档。

    有已认领的 pending 行而那一行签不住 / 在册台账是空文件 / 两边都没有行：三种都不是
    "有人审过"。这一句就是那个区分（"有行"不等于"签住了"），逐句指回盘上的凭据。
    """
    if claimed_rows:
        # 轴是行局部谓词的第一条（`row_signable` 先问秘书轴）：轴不是 clean 时
        # 挡住它的就是轴本身；`_bit3_blockers` 只列机械闸，这时它会落到兜底句。
        blocked = (_bit3_blockers(tail) if verifications.ledger_axis(tail) == "clean"
                   else str(axis_reading(tail).get("why") or ""))
        return (
            f"`{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/` 里有 "
            f"{len(claimed_rows)} 行认领给 stmt:{sid}，但"
            f"{pending_row or '那一行'} 签不住"
            f"（verdict={read_verdict(tail)!r}；{blocked}）⇒ 仍算 missing："
            "认领只回写号、不改判词，「有行」不等于「签住了」")
    if path.is_file():
        return f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 是空文件 ⇒ 一次审校都没落过"
    return (f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 不在盘上，"
            f"`{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/` 里也没有认领给它的行 "
            "⇒ 这一条命题一次审校都没落过")


def unverified_statement_refs(root: str | Path,
                              plans: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """攻坚计划的 `history` 里点名了哪些 `statement_id`、而 `verifications` 两路都没有对应的行。

    只数「我方提出」的那一档（`origin="external_lit"` 不进本计数，见下面「谁的签」一节）。

    ## 为什么这一条落在「攻」那一格（2026-10-19，接 V 的回路的收工侧）
    F 的论证由 B 登记成 `statements` 一行、拿到 `statement_id` 之后，那一号进 `attack_plans.history`（`agent_f/step.py`
    的 P3-6 落点），M 在 `attack.status` 里看得见；但看得见不等于有人审 —— 那一栏可以一直是
    "F 交了、没人签"而收工门照样绿（「攻」只问计划推进了没有）。这一条把两件事接上：history 里
    有 `statement_id` ⇒ `verifications` 里必须有它的一行（`verify_proof` 的产物）；没有 ⇒
    `closing._check_acceptance` 记 `unknown`（不是 `pass`）——"没签"与"签了"必须分得开
    （"我方提出"这一限定见下面「谁的签」一节）。
    三态：`checked=False` ⇒ 没查成（读不到 `verifications/` 目录或坏行），不是"一条都没缺"；
    `missing` 逐条给 `plan_id` / `round` / `statement_id` / `why`。`signed` 是"那一行签住了第 3 位"
    （`signs_bit3`），不决定红绿（由 `missing` 定），留着是因为"有行但没签"与"有行且签了"是两种不同状态（`有毛病` 也是一条"有对应行"）。

    ## 第二路：命题还没在册时签的那一签（2026-11-20，V2FIX）

    本仓的主路是「先签后收录」：V 在命题还没号时审、签落
    `verifications/pending/<载体 sha>.jsonl`（:func:`record_pending_sign`）；B 收录拿到号之后
    只在那一行上回写 `statement_id`（:func:`_claimed_pending_rows` 的口径：不搬文件）。
    改前这一格只问 `verification_ledger_path(...).is_file()` ⇒ 只要某计划 `history` 带
    `statement_id`、而签住在 pending，`missing` 就有它 ⇒ 收工门「攻」那一格掉 `unknown`
    （lp-ball-10 / lp-ball-12 的现场，理由逐字「`verifications` 里没有它们对应的行」）。
    现在两路并读：在册台账或已认领给这一条命题的 pending 行，任一路有一行就算
    "有人审过它"。在册台账那一档的口径与改前逐字相同（pending 只作 `pending_rows` 读数）。

    ## 谁的签（2026-11-22，VREADFIX）

    `history.statement_id` 点名的是"哪一条命题"，不是"哪一条我方命题"。改前这一格
    只按号查签、不看来源 ⇒ 文献引来的定理（`origin="external_lit"`，凭据是引文）被算成
    "F 交了论证、没人签"，`missing` 非空 ⇒ 「攻」那一格 `unknown`。真机 lp-ball-15 的
    C6（`plan_progress_rows`、`got=3`）就是这么掉的：点名的 `stmt:000125` 是
    `external_lit`、凭据 `lit:000005`、`quote_verified=true`，它欠的是引文核验，不是 V 的签。

    现在每一条先问 :func:`_needs_signature`（判据只有 `origin` 一条）：
    `external_lit` ⇒ 不进 `missing`、不进「未签」计数（读数留在 `refs[*].scope` 与
    `excluded` 里，指回盘上的凭据：`source_lit_id` / `proof_source` / `reviewed_source` /
    `quote_state` / 现算 `grade`）；`own_result` ⇒ 照旧两路并读。来源读不出来（`statements`
    不在盘上 / 坏 JSON / 这一号查不到）⇒ 判不了 ⇒ 按我方命题处理（仍是 `missing`、
    仍是 `unknown`，绝不 `pass`）。

    这不是把 `unknown` 折成 `pass`：被分出去的那一档有盘上写明的凭据类型（引文）作依据，
    而"判不了"那一档仍然落在 `unknown`。三态一位没少。

    不放宽的两档（三态不折平）：

    - 未认领的 pending 行（`statement_id` / `stmt_id` 两个都空）不属于任何命题 ——
      它只说明"V 审过某一份还没号的载体"，不能替任意一条命题背书；
    - 已认领、但尾行签不住（:func:`row_signable` 为假：`有毛病` / 未解决 error /
      引用核实挡签 / 没判成）的那一叠也不算：认领只回写号、不改判词。判据与
      `numericproof.exhaustion_backing` 的第二路同一条 —— 不是只看 `verdict` 那个词。

    在册台账读不动（坏行）⇒ `checked=False`；第二路读不动、且真有一条命题是「第二路
    判成 missing」的 ⇒ 同样 `checked=False`（不许折成 pass）。反过来，一本不承重的
    pending 台账读不动（每条点名的命题都在在册台账里 / 已认领的 pending 就签得住）
    不该把整格「攻」记成 `unknown`。
    """
    refs: list[dict[str, Any]] = []
    problems: list[str] = []
    #: 第二路的索引（按命题号分组）。惰性读：一份 plan 的 history 里一条 `statement_id`
    #: 都没有时，这一格不该因为"pending 目录里有坏行"就记 `unknown`。
    claimed_by: dict[str, list[dict[str, Any]]] = {}
    claimed_read = False
    #: 第二路要看的「叠」：`_claimed_pending_rows` 只交已认领的行，而"这一签之后又有
    #: 哪几转"要看整份 pending 台账（2026-11-20 READUNIFY）。与认领索引同一次惰性读。
    stacks: list[tuple[Path, list[dict[str, Any]]]] = []
    #: 第二路的坏行先单独收着：只有真有一条命题是「第二路判成 missing」的（在册台账
    #: 没有它的行、已认领的 pending 又签不住）时它才是承重的 —— 否则一本与本次提问
    #: 无关的 pending 台账读不动，不该把整格「攻」记成 `unknown`。
    pending_bad: list[str] = []
    fallback_missing = False
    #: `statements` 的 `stmt_id -> 行`（判"这一条欠不欠签"要它的 `origin`）。惰性读：
    #: history 里一条 `statement_id` 都没有时，这一格不该因为"表读不动"就记 `unknown`。
    statements_by_id: dict[str, Mapping[str, Any]] = {}
    statements_read = False
    statements_reading: dict[str, Any] = {
        "checked": None, "path": "", "rows": 0,
        "why": "plan 的 `history` 里没有 `statement_id` ⇒ 这一格没读 `statements`（不适用）",
    }
    for plan in plans:
        if not isinstance(plan, Mapping):
            continue
        for entry in (plan.get("history") or []):
            if not isinstance(entry, Mapping):
                continue
            sid = str(entry.get("statement_id") or "").strip()
            if not sid:
                continue
            # ---- 这一条欠不欠签：只由它的 `origin` 定（2026-11-22 VREADFIX）。
            # 惰性读一次整表：一份 plan 点名几十条时不该读几十遍。
            if not statements_read:
                statements_by_id, statements_reading = _statement_rows_by_id(root)
                statements_read = True
            stmt_row = statements_by_id.get(sid)
            needs_sign = _needs_signature(stmt_row)
            scope = _sign_scope(stmt_row)
            ref: dict[str, Any] = {
                "plan_id": str(plan.get("plan_id") or ""),
                "round": entry.get("round"),
                "statement_id": sid, "rows": None, "signed": None, "why": "",
                #: 这一条进不进「未签」计数（决定 `missing`；见 :func:`_needs_signature`）。
                "needs_sign": needs_sign,
                #: 三格读数（`origin` / 现算 `grade` / 凭据类型）；不决定红绿。
                "origin": scope.get("origin") or "",
                "scope": scope,
                "origin_checked": statements_reading.get("checked"),
            }
            try:
                path = verification_ledger_path(root, sid)
            except VerificationError as exc:
                ref["why"] = f"命题号 {sid!r} 不是编号形态（{exc}）⇒ 查不到它那一份台账"
                refs.append(ref)
                continue
            ledger_rows: list[Mapping[str, Any]] = []
            if path.is_file():
                ledger_rows, bad = JF.read_jsonl(path)
                if bad:
                    problems.extend(f"{VERIFICATIONS_DIR}/{sid}.jsonl: {b}" for b in bad)
                    ref["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 有读不出来的行：{bad[:3]}"
                    refs.append(ref)
                    continue
            # ---- 第二路：已认领给这一条命题的 pending 行（先签后收录的正常形态）。
            if not claimed_read:
                got_claimed, got_bad = _claimed_pending_by_statement(root)
                claimed_by.update(got_claimed)
                pending_bad.extend(got_bad)
                stacks, _stack_bad = _pending_ledgers(root)
                claimed_read = True
            claimed_rows = claimed_by.get(sid) or []
            # ---- 取哪一行：与读口① `pending_sign` 同一个实现（见 `_pending_sign_of`）----
            tail, pending_row, pending_state, pending_ok = _pending_sign_of(
                root, sid, claimed_rows, stacks)
            counted = list(ledger_rows) if ledger_rows else (list(claimed_rows) if pending_ok else [])
            ref["rows"] = len(counted)
            ref["signed"] = bool(signed_rows(counted)) if counted else False
            #: 读数（不决定红绿）：认领给这一条命题的 pending 行有几条、那一处取的
            #: 「那一签」是哪一行（`pending_row`）、它签不签得住、三态是哪一档。
            ref["pending_rows"] = len(claimed_rows)
            ref["pending_signable"] = pending_ok
            ref["pending_row"] = pending_row
            ref["pending_state"] = pending_state
            if not counted:
                ref["why"] = _missing_why(sid, path, claimed_rows, pending_row, tail)
            if not needs_sign:
                # 文献引来的那一档：不论有没有台账行，都不进「未签」计数。
                # `why` 换成分流的理由（台账读数仍在 rows/signed/pending_* 里）——
                # 留一句"一次审校都没落过"会让读的人以为这里欠一道签。
                ref["why"] = _excluded_why(scope)
            refs.append(ref)
            if needs_sign and not counted and not ledger_rows:
                # 这一条答案是由第二路给的（而且是"没有"）⇒ 第二路的坏行可能藏着
                # 一份签得住的那一叠，必须记"没查成"而不是"确实没有"。
                # `needs_sign=False` 的那一档不承重：它本来就不过 second route 的账。
                fallback_missing = True
    if fallback_missing:
        problems.extend(pending_bad)
    needing = [r for r in refs if r.get("needs_sign")]
    missing = [r for r in needing if not r.get("rows")]
    excluded = [r for r in refs if not r.get("needs_sign")]
    return {
        "checked": not problems,
        "problems": problems,
        "refs": refs,
        "missing": missing,
        #: 读数（不决定红绿）：点名了几条、其中几条真的欠签（`missing` 只从这里出）。
        "total": len(refs),
        "needs_signature_total": len(needing),
        #: 被分出去的那一档（文献引来的）：逐条带 `plan_id` / `round` / `statement_id`
        #: 与三格读数，读的人能拿 `source_lit_id` 回盘上核。
        "excluded": [{"plan_id": r.get("plan_id"), "round": r.get("round"),
                      "statement_id": r.get("statement_id"),
                      "origin": r.get("origin"), "scope": r.get("scope"),
                      "why": r.get("why")} for r in excluded],
        #: `statements` 那一读的三态（`checked=None` = 没有 `statement_id`，不适用；
        #: `checked=False` = 读不出来，此时每一号都按我方命题处理）。
        "statements": statements_reading,
        "note": ("plan 的 `history` 里有 `statement_id` ⇒ 只有我方提出（`origin=own_result`）"
                 "或来源判不了（`statements` 读不到 / 这一号查不到）的那一档才欠签："
                 "`verifications/<命题号>.jsonl` 里"
                 "必须有它的一行，或 `verifications/pending/` 里有一行认领给它且签得住"
                 "（先签后收录的正常形态；派 V 的 `verify.verify_proof` 就会落）。"
                 "文献引来的那一档（`origin=external_lit`）凭据是引文、不进本计数"
                 "（见 `excluded`；判据 `_needs_signature`）。`missing` 非空 ⇒ "
                 "「攻（攻坚推进）」那一格记 `unknown`（不是 `pass`）；`signed` 只是读数："
                 "「有行但没签」由审计期那一档（`proof_review_without_verification`）点名"),
    }


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    PENDING_DIR_NAME,
    VERIFICATIONS_DIR,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    VerificationError,
    verification_ledger_path,
)
from .v_pending_read import (  # noqa: F401 — 实现在 v_pending_read.py
    _pending_claim_of,
    _pending_ledgers,
    _pending_stack_of_row,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    axis_reading,
    read_verdict,
)
from .v_streak import (  # noqa: F401 — 实现在 v_streak.py
    signed_rows,
)
from .v_gap_read import (  # noqa: F401 — 实现在 v_gap_read.py
    _bit3_blockers,
)
