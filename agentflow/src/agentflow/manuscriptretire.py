# -*- coding: utf-8 -*-
"""「命题退休 ⇒ 它名下那份稿一并作废」的唯一判据（业主 2026-11-13 裁定）。

## 业主口径（逐字）

「一个命题通过规范性审查后拿到一个稿号，之后关于这个命题的内容就写在这个稿上，
就在这个稿号的稿上 edit。放弃命题时就是这个稿也一并作废。」
「每个角色分开口径，自己管自己，稿号跨角色可不一致，就和与命题号不一致一样。」

⇒ 三条由此落定：

1. 1:1 是每族各自的 1:1：F 的命题有一份 f-稿、E 有 e-稿、B 有 b-稿，三族稿号可以
   互不相同（正如稿号与命题号也不一致）。B 优化 = 改 B 自己那份 b-稿，
   「B 改不动 F 的稿」不是缺陷，是角色-族绑定（`manuscriptopen.ROLE_FAMILIES`）。
2. 命题「退休」（`abandoned` / `refuted`）⇒ 它名下那份稿一并作废。
3. 作废 = 只读（不可 edit）+ 收工门不再要它 + 不再算依据；
   稿文件留着（删/挪/换名全被写面拒：`manuscriptopen.foreign_refusal`）。

## 「哪几份稿属于这条命题」= 四个来源的并集

不新增格、不迁移老盘。四个来源各有各的覆盖面，缺一个就会漏：

| 源 | 覆盖 | 出处 |
|---|---|---|
| `statements.manuscript_id` | 最近一次收录的那份 | `agent_b/proof_receipt.py` |
| `statements.manuscripts`（`{路径号: 稿路径}`） | 逐路径记录 | `manuscriptpaths.PER_PATH_KEY` |
| `verifications[].manuscript` | 所有签行点过的稿 | `verifications.record_verification` 写的 `manuscript` |
| `line_range.label = "exp:<号>"`（第四源） | E 的普通数值稿 `work/E/e-num-<号>.md` | `exhaustionreport.experiment_id_of_manuscript` / `numeric_manuscript_relpath` |

## 第五源（2026-11-22 `A-0c-2` CONTRACT-DRESEARCH）：D 的研究稿

`manuscripts/D/RESEARCH.md` / `manuscripts/D/<qid>-research.md` 不属于任何命题 ——
它是 D 的交付正文（`documents.kind=research`，写侧 `agent_d.write_report`）。于是它
不进上面那张"稿↔命题"的表（1:1 只管三族证明稿），但它必须有一条回指：否则
"盘上有报告、台账里 0 行"（真机 45 次 `write_report` 的形态）在任何读数上都看不见。

第五源回答的是另一个问题："这一份文件在台账里有行吗" ——

* 有 `documents` 行（`kind=research`、`markdown_path` 指向它）⇒ 点名 `doc:<号>`；
* 没有 ⇒ 逐字说「没有台账行」（2026-11-22 之前写下的老文件就是这个形态：
  只落盘、不落表）。不按文件名反推：`000001-research.md` 这个形状不构成
  "它有一条台账行"的证据，猜文件名等于给台账造第二个真身；
* `documents` 读不出来 ⇒ `checked=False`（没查成 ≠ 没有行）。

前三源要求"稿↔命题"在某处被记过；第四源不要求 —— 它从命题行上已经记下的来路
（`exp:<号>`）反推稿路径，只在「反查」（`statement_of_manuscript`）里走，且只在前两源
都没命中时走，于是不会盖过任何一条真的登记记录。第四源另多一道"对应实验行"：稿钉的
`exp:<号>` 必须能在 `experiments` 台账里打开；打不开时明确报「没有对应实验行」，
不折成"不在册"、也不静默当成有（三态）。

为什么必须并第三源：同一路径号再收录一次时，`proof_receipt.write_proof_receipt` 会把
`manuscripts["1"]` 覆写成新的那一份（`per[str(no)] = rel`），旧的 f-稿就从行上消失了 ——
但 V 的那一签还留在 `verifications[].manuscript` 里。少了它，F 那份稿在"命题被作废"
之后仍会被读成可写、可要签。

## 第六源（2026-11-22 `A-0c-1` CONTRACT-ATTACKPATH）：F 的攻坚台账

F 的攻坚台账 `work/F/attack-<plan_id>.md`（2026-11-22 之前的落点 `reports/attack-*.md`）
也不属于任何命题 —— 它属于计划，而一条计划可能点过好几条命题。它的回指列是
`attack_plans.report_path`（2026-11-22 新加；此前台账里没有这一格 ⇒ "文件在盘上、
台账里没有"，`manuscriptretire` / `refvocab` / `closing` 都回指不到它）。

第六源同样只回答 "这一份文件在台账里有行吗"：

* 有行、且那一行的 `report_path` 就是它 ⇒ 回指成立（点名计划号）；
* 盘上有这份文件、而没有任何一行的 `report_path` 指向它 ⇒ 逐字
  「只有文件没有台账行」（真机 `lp-ball-6` 7 行 / 8 文件就是这个形态）；
* 有行、但 `report_path` 为空（2026-11-22 之前写下的老行）⇒ 逐字「行上没有记稿路径」。
  不按计划号反推 `attack-<plan_id>.md` 是否存在：真机两个方向都有不匹配
  （`dct-min2` 18 行 / 11 文件 —— 7 条计划一轮都没落稿），反推等于给台账造第二个真身；
* `attack_plans` 读不出来 ⇒ `checked=False`（没查成 ≠ 没有行）。

判定表只有一份（`refvocab.attack_ledger_verdict`）：按 store 读（本模块
:func:`attack_ledger_of`）与按文件读（`refvocab.attack_ledger_reading`）共用它，
于是两条读口不可能给出两个答案。

没有并把"某条命题退休"折成"整份台账作废"：一条计划可以先后点过好几条命题，
只要还有一条活着，整份台账就仍然在用。计划级的作废是 `attack_plans.status` 那个
裁定的职责，不该由"稿↔命题"这一路顺手折进来（`stmt_ids` / `retired_stmt_ids`
两格只如实给出它点过哪些命题、其中哪些已退休）。

## 三态

`checked=False` 只出现在「读不出来」（statements 台账 / 验证台账 / 实验台账读不成）——
"没查成"绝不折成"没退休"（那会让收工门与写面同时放行一个该拦的东西）。
"""
from __future__ import annotations

from typing import Any, Mapping

from . import errorstate as _ES

#: 哪些 `status` 算「退休」（该命题名下那份稿一并作废）。
#:
#: 只有这两档：`abandoned`（明确放弃）与错误那一档（今天的词是 `refuted`，词表补丁
#: 落地后是 `error` —— 词从 `errorstate.ERROR_WORDS` 现取，不在这里抄第二份）。
#: `superseded` 不在列：它是概念行的墓碑（"被后来的一条取代"），取代者还在，
#: 稿不该跟着作废；`disputed` 也不在列：争议未裁，稿还要继续改。
RETIRED_STATUSES: tuple[str, ...] = ("abandoned", *_ES.ERROR_WORDS)

#: 写面拒信的正文（与 `manuscriptfreeze` 的三句拒信同形：一句原因 + 一句指路）。
RETIRED_MANUSCRIPT_MESSAGE = (
    "这一份稿所属的命题已经退休（status={status}）⇒ 这份稿一并作废：只读，不再 edit"
    "（稿文件留着，不删不移 —— 它是那一条命题「曾经做到哪一步」的唯一证据）"
)


def status_is_retired(status: Any) -> bool:
    """这个 `status` 是不是「退休」（`abandoned` / 错误那一档）。"""
    return str(status or "").strip() in RETIRED_STATUSES


def _statement_rows(store: Any) -> tuple[dict[str, dict[str, Any]] | None, str]:
    """`statements` 的全部行（按号索引）；读不出来 ⇒ `(None, why)`。

    索引构造只有一处（`statementledger.index_by_id`），不在这里另写一份推导式。
    """
    if store is None:
        return None, "没有 store"
    try:
        from . import statementledger as _SL

        return _SL.index_by_id(store.rows("statements")), ""
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        return None, f"{type(exc).__name__}: {exc}"


def _verified_manuscripts(store: Any, statement_id: str) -> tuple[list[str], list[str]]:
    """这一条命题的签行点过的稿路径（第三源）：返回 `(路径列表, 读不出来的原因)`。

    读不出来不是"没有这一源"：调用方把它当"没查成"（fail-closed），否则
    F 那份稿会在命题退休之后仍然被读成可写。
    """
    root = str(getattr(store, "root", "") or "")
    if not root:
        return [], "没有工作区根 ⇒ 签行读不了"
    try:
        from . import verifications as _VR

        rows, _problems = _VR.list_verifications(root, statement_id=statement_id, limit=None)
    except Exception as exc:  # noqa: BLE001
        return [], f"验证台账读不出来（{type(exc).__name__}: {exc}）"
    out: list[str] = []
    for row in rows or ():
        rel = str(dict(row).get("manuscript") or "").strip().replace("\\", "/")
        if rel and rel not in out:
            out.append(rel)
    return out, ""


def manuscripts_of_statement(store: Any, statement_id: Any) -> dict[str, Any]:
    """这一条命题名下的稿（三个来源的并集，去重保序）。

    返回 `{checked, found, statement_id, status, manuscripts, sources, problems, why}`。
    - `manuscripts`：工作区相对路径列表（源里的路径原样，统一 `/` 分隔）；
    - `sources`：`{路径: [来源名...]}`（`manuscript_id` / `manuscripts` / `verifications`），
      让读的人看得出"这一份是哪一格给出的"；
    - `checked=False`：命题台账或验证台账读不出来（没查成 ≠ 没有稿）。
    """
    sid = str(statement_id or "").strip()
    out: dict[str, Any] = {"checked": False, "found": False, "statement_id": sid,
                           "status": "", "manuscripts": [], "sources": {},
                           "problems": [], "why": ""}
    if not sid:
        out.update(checked=True, why="没给命题号 ⇒ 没有可查的稿（不是「没有稿」）")
        return out
    rows, why = _statement_rows(store)
    if rows is None:
        out["why"] = f"`statements` 读不出来（{why}）⇒ 这一格没查成"
        return out
    row = rows.get(sid)
    if row is None:
        out.update(checked=True, why=f"命题 {sid} 不在册 ⇒ 没有名下稿可查")
        return out
    out.update(found=True, status=str(row.get("status") or ""))
    sources: dict[str, list[str]] = {}

    def _add(rel: Any, source: str) -> None:
        text = str(rel or "").strip().replace("\\", "/")
        if not text:
            return
        sources.setdefault(text, [])
        if source not in sources[text]:
            sources[text].append(source)

    _add(row.get("manuscript_id") or "", "manuscript_id")
    raw = row.get("manuscripts")
    if isinstance(raw, Mapping):
        for _group, rel in raw.items():
            _add(rel, "manuscripts")
    elif raw is not None:
        out["problems"].append(f"`manuscripts` 不是映射（{type(raw).__name__}）⇒ 逐路径那一源没读成")
    verified, vwhy = _verified_manuscripts(store, sid)
    if vwhy:
        out["problems"].append(vwhy)
    for rel in verified:
        _add(rel, "verifications")
    # `manuscript_id` 是裸号（`000003`）时不能当路径用（写面的每处判据都按
    # `reports/<前缀><号>.md` 认）；它是路径时照旧留在清单里。两种形态都留在
    # `manuscript_id` 那一格里，读的人不必猜。
    bare = str(row.get("manuscript_id") or "").strip()
    if bare and "/" not in bare and "\\" not in bare and bare in sources:
        sources.pop(bare, None)
    out["manuscripts"] = list(sources)
    out["sources"] = sources
    out["manuscript_id"] = bare
    out["checked"] = True
    if not out["manuscripts"] and not out["problems"]:
        out["why"] = (f"命题 {sid} 名下没有任何一份稿（三源都空）—— 这不代表它没有稿，"
                      "而是「稿与命题的对应关系从来没被记过」")
    return out


def _exp_id_of(row: Mapping[str, Any]) -> str:
    """命题行上记的「它来自哪一条实验」（`line_range.label = "exp:<号>"`；没有 ⇒ 空串）。

    E 的数值稿按实验号命名（`work/E/e-num-<实验号>.md`，族人一册、见
    `agent_skills` 的「手稿从哪来」那张表）。这一格只把那一枚写好了的号读回来，
    不猜任何路径 —— 猜路径等于给"稿↔命题"造第二个真身。前缀从
    `exhaustionreport.EVIDENCE_PREFIX` 现取，不在这里写第二份 `"exp:"`。
    """
    from . import exhaustionreport as _ER

    line_range = row.get("line_range")
    label = str(line_range.get("label") or "") if isinstance(line_range, Mapping) else ""
    prefix = _ER.EVIDENCE_PREFIX
    return label[len(prefix):].strip() if label.startswith(prefix) else ""


def _numeric_exp_of(store: Any, rel: Any) -> str:
    """E 的普通数值稿 ⇒ 它钉的那条实验号（`""` = 不是这一族 ⇒ 第四源不适用）。

    「钉哪条实验」只有两个读口，都在 `exhaustionreport`（目录 / 前缀由
    `manuscriptfamily.DIR_OF` 派生，这里不写 `work/E` 或 `e-num-` 的字面量）：
    - 稿头 `- 实验号：exp:<号>` 优先（2026-11-11 之后 E 的稿号独立，新稿名字里是
      E 自己的稿号，实验号只在稿头）；
    - 稿头读不到（稿不在盘上 / 老盘手写）⇒ 名字里的号（老盘稿名里的号就是实验号）。
    落点形态先由 `is_numeric_manuscript_relpath` 判：只认 `work/E/e-num-<号>.md`。
    """
    from . import exhaustionreport as _ER

    text = str(rel or "").strip().replace("\\", "/")
    if not text or not _ER.is_numeric_manuscript_relpath(text):
        return ""
    root = str(getattr(store, "root", "") or "")
    return _ER.experiment_id_of_manuscript(root or None, text)


def _experiment_ids(store: Any) -> tuple[set[str] | None, str]:
    """`experiments` 台账里的实验号集合；读不出来 ⇒ `(None, why)`（没查成 ≠ 没有）。"""
    if store is None:
        return None, "没有 store"
    try:
        return {str(r.get("experiment_id") or "").strip() for r in store.rows("experiments")}, ""
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        return None, f"{type(exc).__name__}: {exc}"


def _document_rows(store: Any) -> tuple[list[dict[str, Any]] | None, str]:
    """`documents` 的全部行；读不出来 ⇒ `(None, why)`（没查成 ≠ 没有这一行）。"""
    if store is None:
        return None, "没有 store"
    try:
        return [dict(r) for r in store.rows("documents")], ""
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        return None, f"{type(exc).__name__}: {exc}"


def _reports_layout_of(rel: Any) -> str:
    """这份路径属于 D 研究稿的哪一代落点：`"current"` / `"legacy"` / `""`（不适用）。

    目录与"报告叫什么"的唯一真身在 `depsection`（`D_REPORT_DIR` / `D_REPORT_DIRS_LEGACY` /
    `D_REPORT_NAMES` / `D_WORKING_SUFFIX`），这里只做归类，不写第二份字面量：

    * 当前落点（`manuscripts/D/`）：那个目录里只住 D 的报告 ⇒ 任何文件都算；
    * 旧布局（`manuscripts/G/` 与 `reports/`）：同一个目录里还住着 G 的论文稿与退役的
      F 证明稿，所以必须同时看名字（`RESEARCH.md` / `*-research.md`）—— 那只是
      "这一句读数要不要说话"的归类，不是"它属于哪一行台账"的推断（后者只读台账）。
    """
    from . import depsection as _DS

    text = str(rel or "").strip().replace("\\", "/")
    if not text:
        return ""
    name = text.rsplit("/", 1)[-1]
    if text.startswith(f"{_DS.D_REPORT_DIR}/"):
        return "current"
    names = tuple(_DS.D_REPORT_NAMES)
    for one in _DS.D_REPORT_DIRS_LEGACY:
        if not one:
            continue
        if text.startswith(f"{one}/") and (name in names or name.endswith(_DS.D_WORKING_SUFFIX)):
            return "legacy"
    return ""


def research_report_reading(store: Any, rel: Any) -> dict[str, Any]:
    """一份 D 研究稿在 `documents` 里的回指（第五源，2026-11-22 `A-0c-2`）。

    返回 `{checked, applies, layout, found, rel, doc_id, doc_ids, kind, why}`：

    * `layout`：`"current"`（`manuscripts/D/`）/ `"legacy"`（旧布局 `manuscripts/G/` 或
      `reports/`）/ `""`（不是 D 的报告）—— 它是"第五源要不要说话"那一格，与"有没有行"
      分开（不说话的稿不该被读成"查过了、没有行"）；
    * `found=True` ⇒ 至少一行 `documents`（`kind=research`、`markdown_path` 指向它），
      `doc_id` 是第一行（一个稿号 = 一份文件；多于一行要报，见 `doc_ids`）。这一格只读
      台账，不管这份文件在哪个目录 —— 台账里有行就是有行；
    * `found=False` + `checked=True` ⇒ 没有台账行（查过了）：2026-11-22 之前
      `write_report` 只落盘，老文件就是这个形态。判据里逐字含「没有台账行」，不许静默；
    * `checked=False` ⇒ `documents` 读不出来（没查成，不折成"没有行"）。

    ## 为什么不按文件名反推

    `000001-research.md` 这个形状不构成"它有一条台账行"的证据。按名字认领等于给
    台账造第二个真身：D 用 `out_path` 传过任意落点（`closedform-research.md` 之类），
    而"名字像"与"台账里记过"是两件事。
    """
    text = str(rel or "").strip().replace("\\", "/")
    layout = _reports_layout_of(text)
    out: dict[str, Any] = {"checked": False, "applies": bool(layout), "layout": layout,
                           "found": False, "rel": text, "doc_id": "", "doc_ids": [],
                           "kind": "", "why": ""}
    if not text:
        out.update(checked=True, why="没给稿路径 ⇒ 第五源不适用（不是「没有台账行」）")
        return out
    try:
        from . import schema as _S

        kind_want = str(_S.RESEARCH_DOC_KIND)
    except Exception:  # noqa: BLE001 —— 词表读不到就用读侧唯一的那个名字（下面会照实报 why）
        kind_want = "research"
    rows, why = _document_rows(store)
    if rows is None:
        out["why"] = f"`documents` 读不出来（{why}）⇒ 这一格没查成（不是「没有台账行」）"
        return out
    hits = [str(r.get("doc_id") or "") for r in rows
            if str(r.get("kind") or "") == kind_want
            and str(r.get("markdown_path") or "").strip().replace("\\", "/") == text]
    out.update(checked=True, doc_ids=hits, found=bool(hits),
               doc_id=hits[0] if hits else "", kind=kind_want)
    if hits:
        out["why"] = (f"这一份是 D 的研究稿：`documents` 里有它的一行（`doc:{hits[0]}`，"
                      f"kind={kind_want}）—— 它不属于任何命题（1:1 只管三族证明稿）"
                      + (f"；另有 {len(hits) - 1} 行也指向同一份文件（一个稿号=一份文件，"
                         "这多出来的行要人来处置）" if len(hits) > 1 else ""))
    elif layout == "current":
        out["why"] = (f"没有台账行：`{text}` 在盘上，而 `documents` 里没有一行"
                      f"（kind={kind_want}）的 `markdown_path` 指向它 —— 2026-11-22 之前的"
                      "老文件就是这个形态（`write_report` 只落盘、不落表）；"
                      "本判据不按文件名反推「它属于哪一行」")
    elif layout == "legacy":
        out["why"] = (f"没有台账行：`{text}` 是旧布局（角色分目录之前）的 D 研究稿，"
                      "而 `documents` 里没有一行指向它 —— 旧布局不迁移（业主 2026-11-22 "
                      "裁定：旧工作区不必兼容），它也从来没进过台账；"
                      "本判据不按文件名反推「它属于哪一行」")
    else:
        out["why"] = (f"`{text}` 不在 D 研究稿的落点里（当前 `depsection.D_REPORT_DIR` / "
                      "旧布局 + 报告名形）⇒ 第五源对它不说话（不是「没有台账行」）")
    return out


def attack_ledger_of(store: Any, *, rel: Any = "", plan_id: Any = "") -> dict[str, Any]:
    """一条攻坚计划名下那份台账（`work/F/attack-<plan_id>.md`）在台账里的回指（第六源）。

    2026-11-22 `A-0c-1`（CONTRACT-ATTACKPATH，`draft/201`）。这一族不属于任何命题
    （它是 F 的攻坚过程台账，一条计划可能点过好几条命题），所以它不进上面那张
    "稿↔命题"的 1:1 表；它回答的是另一个问题："这一份文件在 `attack_plans` 里有行吗"。

    返回 `{checked, applies, found, state, rel, plan_id, row_path, on_disk,
    stmt_ids, retired_stmt_ids, why}`：

    * `applies`：这条路径（或这个计划号）是不是攻坚台账那一族 —— "第六源要不要说话"
      与"有没有行"分开（不说话的路径不该被读成"查过了、没有行"）；
    * `found=True` ⇒ 台账行的 `report_path` 就指向它（回指成立）；
    * `found=False` + `checked=True` ⇒ 查过了没有，且 `why` 逐字分开三种：只有文件没有
      台账行（盘上有、行上没记）、行上 `report_path` 为空（老行，不猜）、行上记的是另一份；
    * `checked=False` ⇒ `attack_plans` 读不出来（没查成，不折成"没有行"）。

    ## 判据不在这里：`refvocab.attack_ledger_verdict` 是唯一一份

    这一格只负责"按 store 读台账"（本模块的既有读口），"怎么判"由
    :func:`agentflow.refvocab.attack_ledger_verdict` 给 —— 另一侧（按文件读）是
    `refvocab.attack_ledger_reading`。同一张判定表两处共用，于是"按 store 问"与
    "按文件问"不可能给出两个答案。

    ## `stmt_ids` 是事实，不是撤回

    `history[*].statement_id` 里出现过的命题号原样给出（外加 `retired_stmt_ids`）。
    不把"某一条命题退休"折成"整份台账作废"：一条计划可能先后点过好几条命题，
    只要还有一条活着，整份台账就仍然在用；"计划级的作废"是另一个裁定（要它，得先写
    `attack_plans.status=abandoned` 的判据），不该由这一路顺手折进来。
    """
    from . import attackledger as _AL

    out: dict[str, Any] = {"checked": False, "applies": False, "found": False,
                           "state": _AL.STATE_UNCHECKED, "code": _AL.CODE_UNCHECKED,
                           "rel": "", "plan_id": "", "row_path": "", "on_disk": "",
                           "stmt_ids": [], "retired_stmt_ids": [], "why": ""}
    # 先做识别（纯函数，零 I/O）：它同时给出归一化后的 rel 与计划号。
    parsed = _AL.attack_ledger_verdict(rel=rel, plan_id=plan_id)
    if parsed["state"] == _AL.STATE_BAD:
        return {**out, **parsed}
    text = str(parsed["rel"] or "")
    pid = str(parsed["plan_id"] or "")
    out.update(applies=True, rel=text, plan_id=pid)
    if store is None:
        out["why"] = "没有 store ⇒ `attack_plans` 读不了（没查成）"
        return out
    try:
        rows = [dict(r) for r in store.rows("attack_plans")]
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        out["why"] = f"`attack_plans` 读不出来（{type(exc).__name__}: {exc}）⇒ 没查成"
        return out
    row = next((r for r in rows if str(r.get("plan_id") or "") == pid), None)
    if row is None:
        out.update(checked=True)
        out["why"] = (
            f"没有台账行：`attack_plans` 里没有计划 {pid} 这一行"
            "（本判据不按文件名反推它是哪条计划的）")
        return out
    row_path = str(row.get("report_path") or "").strip().replace("\\", "/")
    on_disk = ""
    if text:
        root = str(getattr(store, "root", "") or "")
        try:
            from pathlib import Path as _Path

            if root and (_Path(root) / text).is_file():
                on_disk = text
        except OSError:
            on_disk = ""
    verdict = _AL.attack_ledger_verdict(rel=text, plan_id=pid,
                                        row_path=row_path, on_disk=on_disk)
    out.update(verdict, checked=True, applies=True)
    # 它点过哪些命题（事实）：`history[*].statement_id` 是 F 在那一轮自己写下的来路。
    hits: list[str] = []
    for h in (row.get("history") or []):
        if isinstance(h, Mapping):
            sid = str(h.get("statement_id") or "").strip()
            if sid and sid not in hits:
                hits.append(sid)
    out["stmt_ids"] = hits
    if hits:
        try:
            srows = {str(r.get("stmt_id") or ""): dict(r) for r in store.rows("statements")}
        except Exception:  # noqa: BLE001 —— 退休态读不出来就只给"点过哪些"这一半
            srows = {}
        out["retired_stmt_ids"] = [
            sid for sid in hits if status_is_retired((srows.get(sid) or {}).get("status"))]
    return out


def statement_of_manuscript(store: Any, *, rel: Any = "",
                            manuscript_id: Any = "",
                            sign_rows: bool = True) -> dict[str, Any]:
    """反查：这一份稿属于哪一条命题（唯一实现；反查的源与正查同一个并集）。

    返回 `{checked, found, stmt_id, status, retired, rel, why}`。
    三态：`checked=False` ⇒ 台账读不出来（没查成）；`found=False` ⇒ 查过了、四个来源都不
    指向任何一行（未在册的稿，例如 F 交上来还没被 B 收录的那一份）—— 那一档不是"没问题"，
    只是本判据对它不说话（plan 级那边另有门）。

    `sign_rows=False` 收窄到收录记录那两源（`statements.manuscript_id` 与
    `statements.manuscripts`），不读签行那一源。为什么有人要收窄：问"这一份稿收进了
    哪一行"（`obligations.registration_gap` 的「必须收录」义务）时，签行回答的是
    "谁签过它"—— 一份稿可以先被签在 A 上、后来收进 B，拿签行认领会把义务引到错的行。
    默认 `True` 让既有调用方（退休判据那几源）一个字节都不变。

    ## 第四源（2026-11-19 FIX186-C；2026-11-22 落点迁移）：由命题反查它的稿

    前三源都要求"稿↔命题"在某处被记过。新行现在由 `register_statement` 同笔写
    `manuscript_id` / `manuscripts`；存量行（lp-ball-11 的 `stmt:000006`）没有这两格，
    但命题行上记着来路：`line_range.label = "exp:<号>"` ⇒ E 的数值稿就是
    `work/E/e-num-<号>.md`（目录 / 前缀从 `manuscriptfamily.DIR_OF` 派生；稿钉的实验号由
    `exhaustionreport.experiment_id_of_manuscript` 读：稿头优先、名字兜底）。

    这一源只在前两源都没命中时走（签行那一源在它之后），于是它不会盖过任何一条真的
    登记记录。它另多一道"对应实验行"：稿钉的 `exp:<号>` 必须能在 `experiments` 台账里
    打开 ——
    - 台账读不出来 ⇒ `checked=False`（没查成，不折成"不在册"）；
    - 台账里没有那一行 ⇒ `found=False` + 明确「没有对应实验行」（不静默当成有）；
    - 有那一行、但没有命题行的 `line_range.label` 指向它 ⇒ `found=False` + 明确
      「没有命题回指」。
    """
    text = str(rel or "").strip().replace("\\", "/")
    mid = str(manuscript_id or "").strip()
    out: dict[str, Any] = {"checked": False, "found": False, "stmt_id": "", "status": "",
                           "retired": False, "rel": text, "why": "",
                           #: 第五源（D 研究稿的回指）：`documents` 里那一行的号 / 是否查成。
                           #: 与"属于哪条命题"分开：研究稿不属于任何命题，它属于 `documents`。
                           "doc_id": "", "doc_kind": "", "doc_checked": False}
    if not text and not mid:
        out.update(checked=True, why="没给稿路径 / 稿号 ⇒ 反查不了（不是「不属于任何命题」）")
        return out
    rows, why = _statement_rows(store)
    if rows is None:
        out["why"] = f"`statements` 读不出来（{why}）⇒ 这一格没查成"
        return out
    hits: list[str] = []
    for sid, row in sorted(rows.items()):
        if text and str(row.get("manuscript_id") or "").strip() == text:
            hits.append(sid)
            continue
        if mid and str(row.get("manuscript_id") or "").strip() == mid:
            hits.append(sid)
            continue
        per = row.get("manuscripts")
        if text and isinstance(per, Mapping) and text in {
                str(v or "").strip().replace("\\", "/") for v in per.values()}:
            hits.append(sid)
    numeric_why = ""
    numeric_unchecked = ""
    if not hits and text:
        # 第四源：由命题反查（`exp:<号>` ⇒ E 的普通数值稿）。稿钉的实验号由
        # `exhaustionreport` 读（稿头优先、名字兜底），落点目录 / 前缀从
        # `manuscriptfamily.DIR_OF` 派生 —— 这里不写 `work/E` / `e-num-` 的字面量。
        from . import exhaustionreport as _ER

        exp = _numeric_exp_of(store, text)
        if exp:
            exp_ids, ex_why = _experiment_ids(store)
            if exp_ids is None:
                numeric_unchecked = (
                    f"{text} 钉的是 {_ER.EVIDENCE_PREFIX}{exp}，但 `experiments` 台账读不出来"
                    f"（{ex_why}）⇒ 有没有对应实验行这一格没查成")
            elif exp not in exp_ids:
                numeric_why = (
                    f"{text} 钉的是 {_ER.EVIDENCE_PREFIX}{exp}，而 `experiments` 台账里没有"
                    "这一行 ⇒ 没有对应实验行（不把这当成「有」）")
            else:
                for sid, row in sorted(rows.items()):
                    if _exp_id_of(row) == exp:
                        hits.append(sid)
                if not hits:
                    numeric_why = (
                        f"{text} 有对应实验行 {_ER.EVIDENCE_PREFIX}{exp}，但 `statements` 里"
                        "没有一行的 `line_range.label` 指向它 ⇒ 这一份稿还没有命题回指"
                        "（本判据对它不说话）")
    if not hits and text and sign_rows:
        # 第三源（签行）单独查：它按命题逐条读，成本高，只在前面几源都没命中时走。
        for sid, _row in sorted(rows.items()):
            verified, _vwhy = _verified_manuscripts(store, sid)
            if text in verified:
                hits.append(sid)
    if not hits:
        # ---- 第六源（攻坚台账，A-0c-1）：它也不属于任何命题，但"台账里有没有这一行"
        # 必须说出来。位置在第五源之前：这一族的路径（`work/F/attack-*.md`，历史
        # `reports/attack-*.md`）不在 `manuscripts/D/` 下，第五源的 `applies` 对它恒
        # False ⇒ 两条不会抢；先问它只是让"这是哪一族"先定下来。
        #
        # 注意 `found` 仍为 False：这一格的契约是"这份稿属于哪一条命题"，而攻坚台账
        # 属于计划不属于命题（一条计划可能点过好几条命题）。台账那一侧的结论在
        # `attack_plan_id` / `attack_report_path` / `attack_stmt_ids` 三格与 `why` 里。
        six = attack_ledger_of(store, rel=text)
        if six.get("applies"):
            out["attack_plan_id"] = str(six.get("plan_id") or "")
            out["attack_report_path"] = str(six.get("row_path") or "")
            out["attack_stmt_ids"] = list(six.get("stmt_ids") or [])
            out.update(checked=bool(six.get("checked")), why=str(six.get("why") or ""))
            return out
        # ---- 第五源（D 的研究稿）：它不属于任何命题，但"有没有台账行"必须说出来。
        #
        # 位置在四源全空之后、`numeric_unchecked` 之前：D 的稿不在 `work/E/`，第四源对它
        # 不说话，所以这里不会被那条"没查成"抢走；而四源都没命中时若它是 D 的报告，
        # 拿"本判据对它不说话"作答等于把"有行 / 没行"这件真事藏起来（真机 45 次
        # `write_report` 的形态就是这么静默过去的）。
        five = research_report_reading(store, text)
        out["doc_id"] = str(five.get("doc_id") or "")
        out["doc_kind"] = str(five.get("kind") or "")
        out["doc_checked"] = bool(five.get("checked"))
        if five.get("found"):
            out.update(checked=True, why=str(five.get("why") or ""))
            return out
        if numeric_unchecked:
            out["why"] = numeric_unchecked
            return out
        base = numeric_why or (
            f"四源里没有一行指向 {text or mid!r} ⇒ 这一份稿不在册（本判据对它不说话）")
        if five.get("applies") and not numeric_why:
            # 查过了 ⇒ 那两句都是读数；没查成 ⇒ 第三态（不折成"没有台账行"）。
            base = (f"{five.get('why')}；四源里也没有一行指向它（它不属于任何命题）"
                    if five.get("checked") else
                    f"第五源没查成（{five.get('why')}）；{base}")
        out.update(checked=True, why=base)
        return out
    if len(hits) > 1:
        out["why"] = (f"{text or mid!r} 同时被 {len(hits)} 条命题指向（{hits}）—— "
                      "1:1 的判据被破了（同一份稿只能属于一条命题），本判据按第一行读，"
                      "但这件事本身要报")
    sid = hits[0]
    row = rows[sid]
    out.update(checked=True, found=True, stmt_id=sid,
               status=str(row.get("status") or ""),
               retired=status_is_retired(row.get("status")))
    return out


def retire_reading(store: Any, rel: Any) -> dict[str, Any]:
    """这一份稿现在能不能写：`retired=True` ⇒ 只读（命题已退休，稿一并作废）。

    与 `manuscriptfreeze.freeze_reading` 的分工：冻结回答"拿签之后别改"，这一格回答
    "命题已经退休了，这份稿随它作废"。两件事必须分开读（一份已签的稿可以所属命题还活着；
    一份未签的稿也可以所属命题已退休）。
    """
    out: dict[str, Any] = {"checked": False, "retired": False, "stmt_id": "", "status": "",
                           "rel": str(rel or ""), "why": "", "message": ""}
    got = statement_of_manuscript(store, rel=rel)
    out.update(checked=bool(got.get("checked")), stmt_id=str(got.get("stmt_id") or ""),
               status=str(got.get("status") or ""), retired=bool(got.get("retired")),
               why=str(got.get("why") or ""))
    if out["retired"]:
        out["message"] = RETIRED_MANUSCRIPT_MESSAGE.format(status=out["status"])
    return out


def flow_reading(store: Any, *, rel: Any = "", manuscript_id: Any = "") -> dict[str, Any]:
    """这一份稿「还要不要继续走」（收工门与写面共用的那一个读数）。

    `retired` = 所属命题 `abandoned` / `refuted`（稿一并作废）；`hard_to_prove` =
    所属命题的优化栏记着「难以自证」（不欠签，但也不算已优化）。
    两件事分开给：写面只认前者（退休才不可 edit），收工门两个都不再要签。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "retired": False,
                           "hard_to_prove": {}, "stmt_id": "", "status": "",
                           "row": {}, "why": "",
                           #: 三态读数（FIX186-A）：原始 `status` 保留作审计，判据只读它。
                           #: 唯一入口是 `lifecycle.state_of_manuscript`（放弃压过完工；
                           #: 没签且没退休 ⇒ 活跃；读不出来 ⇒ 空串，不折成活跃）。
                           "lifecycle_state": ""}
    got = statement_of_manuscript(store, rel=rel, manuscript_id=manuscript_id)
    out.update(checked=bool(got.get("checked")), found=bool(got.get("found")),
               retired=bool(got.get("retired")), stmt_id=str(got.get("stmt_id") or ""),
               status=str(got.get("status") or ""), why=str(got.get("why") or ""))
    if str(rel or "").strip():
        from . import lifecycle as _LC

        out["lifecycle_state"] = str(_LC.state_of_manuscript(store, rel).get("state") or "")
    if not out["found"]:
        return out
    try:
        from . import evidencebits as _EB

        rows = {str(r.get("stmt_id") or ""): dict(r) for r in store.rows("statements")}
        row = rows.get(out["stmt_id"]) or {}
        out["row"] = dict(row)
        out["hard_to_prove"] = dict(_EB.hard_to_prove_by_proof(row))
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        out.update(checked=False, why=f"优化栏读不出来（{type(exc).__name__}: {exc}）")
    return out
