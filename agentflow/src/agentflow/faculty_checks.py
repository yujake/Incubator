"""十项官能里"可机械判的那一半"：引用落地、猜想卫生、体例。

## 为什么每一项官能都要有"机械的那一半"

`draft/28` §180 把官能分成"代码保证 / 你自己把握"。高观点、敢创新、有品味今天偏后者，
但它们各自有一半是不需要模型就能判的，而这一半恰恰是最容易出错、也最贵的那一半：

- 高观点的机械半：引用落地。稿子说"概念 A 与 B 之间有关系"，那 A、B 必须真的在概念表里，
  那条关系必须真的在图里（或有一条路径）—— 否则"洞见"就是凭空的。这一步不需要任何模型。
- 敢创新的机械半：猜想卫生。提了猜想有没有给可检验形式、有没有对立面（negation）、
  有没有"提了就不管"（既没有实验也没有笔记）、声称被支持时那条实验是否真的存在。
  `schema.Conjecture.validate` 管的是单行内的硬约束；这一层管的是跨对象的那一半。
- 有品味的机械半：体例。标题层级、占位符（TODO/待填/×××）、免责声明常量是否逐字一致、
  空段落、以及"写了'证明'却没有任何证明引用"这类形态。

语义的那一半（"这个结构判断深刻不深刻"）在 `judges.py`，它带引用落地过滤与负控。
两半合起来才算"有判据"，单独任何一半都会漏掉一大类问题。
"""
from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any, Iterable, Mapping, Sequence

from . import conceptrows as CR   # 并表过渡期：探针夹具走这一处写口（老表在不在由它决定）

#: 过程记录号的前缀 → 表（取自 `schema.PROCESS_ID_PREFIXES` 的语义；这里只做"可归属"这一件事）。
PROCESS_ID_TABLES: dict[str, str] = {
    "r": "search_requests", "p": "reprocess_requests", "t": "tasks",
}
#: 过程号：`r-0001` 这种形态。它是可归属的（前缀就说明了表）。
PROCESS_ID_TOKEN = re.compile(r"\b(" + "|".join(PROCESS_ID_TABLES) + r")-(\d{4})\b")

#: 带表名的实体引用：`concepts/0001`、`experiments=0007`、`relations:0002`。
#: 表名必须来自 `schema.TABLES`（由 `_table_names()` 现取），不另写一份名单。
LABELED_ID = re.compile(
    r"\b([a-z_]+)\s*[/=:]\s*(\d{4})\b")

#: 占位符：写稿/整理阶段留下的"以后再说"。它们出现在交付物里就是缺陷。
PLACEHOLDERS: tuple[str, ...] = ("TODO", "FIXME", "待填", "待补", "×××", "XXX", "???", "……待")

#: 体例要求的标题：交付物应当以一个一级标题开头。
TITLE_LINE = re.compile(r"^#\s+\S", re.M)


def _rows(store: Any, table: str) -> list[dict]:
    """读一张表（读不出来就给空列表 —— 调用方据读数区分"没有"与"没查到"）。"""
    try:
        return list(store.rows(table))
    except Exception:
        return []


def _table_names() -> set[str]:
    """可归属的表名（现取，不另写名单）：`schema.TABLES` + 已并走的老表名。

    S1r 并表之后 `concepts` 不再是 `TABLES` 里的一张表，但文本里的
    `concepts/0001` 这种引用仍然在（稿件、报告、旧日志里到处是）⇒
    它必须被认出来并落到新家（`store._MOVED_TABLES` 是"并走"这件事的唯一
    定义点，名单不在这里抄第二份）。不认识它等于让这条引用从"引用落地"
    这道门里整段消失 —— 静默失效，而这一门正是"编造引用"的唯一机械防线。
    """
    from . import schema as S
    from .store import _MOVED_TABLES

    return set(S.TABLES) | set(_MOVED_TABLES)


def _home_table(table: str) -> tuple[str, str]:
    """`表名 -> (它现在住哪张表, 必须匹配的 kind 或空串)`。

    并走的表返回新家；没并走的原样返回。读侧一律用这一处换算，
    于是"老名字能读、报告里也照旧写老名字"两件事同时成立。
    """
    from .store import _MOVED_TABLES

    meta = _MOVED_TABLES.get(table)
    if not meta:
        return table, ""
    return str(meta.get("into") or table), str(meta.get("kind") or "")


def _home_rows(store: Any, table: str) -> tuple[list[dict], str]:
    """按表名读行（并走的表走新家 + `kind` 过滤），返回 `(行, 读它的 id 字段所在的表)`。"""
    from . import schema as S

    home, kind = _home_table(table)
    if home not in S.TABLES:
        return [], home
    rows = _rows(store, home)
    if kind:
        rows = [r for r in rows if str(r.get("kind") or "") == kind]
    return rows, home


def ids_in(text: str) -> list[tuple[str, str, str]]:
    """文本里可归属的 id 引用：`[(完整 id, 表, 形态)]`（按出现顺序）。

    只认两种：带表名的实体引用（`concepts/0001`）与过程号（`r-0001`）。
    光秃秃的 `0001` 不认 —— 见模块顶部说明：猜归属比不判更坏。
    """
    out: list[tuple[str, str, str]] = []
    names = _table_names()
    for m in LABELED_ID.finditer(text or ""):
        if m.group(1) in names:
            out.append((m.group(2), m.group(1), "labeled"))
    for m in PROCESS_ID_TOKEN.finditer(text or ""):
        out.append((m.group(0), PROCESS_ID_TABLES[m.group(1)], "process"))
    return out


def unknown_ids(store: Any, text: str) -> dict[str, list[str]]:
    """按表分组列出"被引用但表里不存在"的 id（机械判据，不需要模型）。

    为什么它是高观点的第一道门：一段"深刻"的结构判断如果引用了一堆不存在的 id，
    它就不是洞见而是编造 —— 而这件事查表就能判，不该等到人读。
    """
    from . import schema as S

    bad: dict[str, list[str]] = {}
    cache: dict[str, set[str]] = {}
    for token, table, _form in ids_in(text):
        if table not in cache:
            rows, home = _home_rows(store, table)
            field = S.TABLES[home]["id_field"] if home in S.TABLES else ""
            cache[table] = ({str(r.get(field)) for r in rows} if field else set())
        if token not in cache[table]:
            bad.setdefault(table, [])
            if token not in bad[table]:
                bad[table].append(token)
    return bad


def relation_index(store: Any) -> tuple[dict[frozenset[str], str], dict[str, set[str]]]:
    """关系表 → `(无序概念对 → 关系说明, 邻接表)`。邻接表用于"有没有一条路径"。"""
    pairs: dict[frozenset[str], str] = {}
    adj: dict[str, set[str]] = {}
    for row in _rows(store, "relations"):
        ids = [str(x) for x in (row.get("concept_ids") or [])]
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                pairs.setdefault(frozenset({a, b}), str(row.get("description") or ""))
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
    return pairs, adj


def link_status(store: Any, a: str, b: str) -> tuple[str, str]:
    """两个概念之间是 `direct` / `path` / `none`，以及证据说明。"""
    pairs, adj = relation_index(store)
    if frozenset({a, b}) in pairs:
        return "direct", pairs[frozenset({a, b})]
    seen, queue = {a}, [a]
    while queue:
        cur = queue.pop(0)
        for nxt in adj.get(cur, ()):  # type: ignore[arg-type]
            if nxt == b:
                return "path", f"{a} … {b}（经 {cur}）"
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return "none", ""


def overview_findings(store: Any, text: str, *, claimed_pairs: Sequence[Sequence[str]] = (),
                      ) -> dict[str, Any]:
    """高观点的机械半：引用落地 + 声称的概念对有没有图上的支撑。

    返回 `{"checked": True, "unknown_ids": {...}, "unsupported_pairs": [...], "problems": [...]}`。
    `claimed_pairs` 由调用方给（从稿件里抽出来的概念对），本函数只判"图里有没有这条边或路径"。
    """
    unknown = unknown_ids(store, text)
    unsupported: list[dict[str, str]] = []
    for pair in claimed_pairs:
        if len(pair) < 2:
            unsupported.append({"pair": "、".join(map(str, pair)), "status": "malformed"})
            continue
        status, why = link_status(store, str(pair[0]), str(pair[1]))
        if status == "none":
            unsupported.append({"pair": f"{pair[0]}↔{pair[1]}", "status": "none"})
    problems: list[str] = []
    if unknown:
        problems.append("引用了不存在的 id：" + "；".join(
            f"{t}: {'、'.join(v)}" for t, v in sorted(unknown.items())))
    if unsupported:
        problems.append("声称的概念对在图里没有边也没有路径：" + "；".join(
            x["pair"] for x in unsupported))
    return {"checked": True, "unknown_ids": unknown, "unsupported_pairs": unsupported,
            "problems": problems, "problem_count": len(problems)}


def conjecture_hygiene(store: Any) -> dict[str, Any]:
    """敢创新的机械半：猜想台账的跨对象卫生（单行约束由 `Conjecture.validate` 管）。

    四条（每条都对应一种"看起来创新、实际没落地"的形态）：
    1. `testable=True` 却没有 `negation_statement`：不可否证的形式化只是口号；
    2. `status=supported_not_proved` 而 `experiment_ids` 里那条实验不存在；
    3. 既没有实验、也没有笔记的"僵尸猜想"（提了就不管）；
    4. `promoted_to` 指向不存在的目标。
    """
    rows = _rows(store, "conjectures")
    exp_ids = {str(r.get("experiment_id")) for r in _rows(store, "experiments")}
    findings: list[dict[str, str]] = []
    for row in rows:
        cid = str(row.get("conjecture_id") or "?")
        if row.get("testable") and not str(row.get("negation_statement") or "").strip():
            findings.append({"conjecture_id": cid, "kind": "no_negation",
                             "detail": "testable=True 但没写对立面（negation_statement 为空）"})
        if str(row.get("status")) == "supported_not_proved":
            missing = [e for e in (row.get("experiment_ids") or []) if str(e) not in exp_ids]
            if missing:
                findings.append({"conjecture_id": cid, "kind": "missing_experiment",
                                 "detail": f"声称有支持，但实验不存在：{missing}"})
        if not (row.get("experiment_ids") or row.get("notes")):
            findings.append({"conjecture_id": cid, "kind": "zombie",
                             "detail": "没有实验也没有笔记：提了就不管"})
        if row.get("promoted_to") and str(row.get("promoted_to")) not in {
                str(r.get("conjecture_id")) for r in rows}:
            findings.append({"conjecture_id": cid, "kind": "bad_promotion",
                             "detail": f"promoted_to={row.get('promoted_to')} 指向不存在的猜想"})
    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    return {"checked": True, "conjectures": len(rows), "findings": findings,
            "by_kind": by_kind, "problem_count": len(findings)}


def style_findings(text: str, *, require_disclaimer: bool = False,
                   disclaimer: str = "") -> dict[str, Any]:
    """有品味的机械半：体例（不需要模型的那一半）。

    查四类：一级标题缺失、占位符、空标题下的空段落、以及"要求带免责声明却没逐字带上"。
    "结论强度是否超过引文"这类语义判据不在这里（它归 `review_tools` 与 `judges.py`）。
    """
    body = text or ""
    findings: list[dict[str, str]] = []
    if not TITLE_LINE.search(body):
        findings.append({"kind": "no_title", "detail": "交付物没有一级标题（`# 标题`）"})
    for token in PLACEHOLDERS:
        if token in body:
            findings.append({"kind": "placeholder", "detail": f"正文里还留着占位符 {token!r}"})
    for m in re.finditer(r"^#+\s+\S.*\n(\s*\n)+(?=#|\Z)", body, re.M):
        head = m.group(0).strip().splitlines()[0]
        findings.append({"kind": "empty_section", "detail": f"空段落：{head}"})
    if require_disclaimer:
        if not disclaimer:
            findings.append({"kind": "disclaimer_missing",
                             "detail": "要求带免责声明，但调用方没有给出应当逐字匹配的常量"})
        elif disclaimer not in body:
            findings.append({"kind": "disclaimer_mismatch",
                             "detail": "免责声明与约定常量逐字不一致"})
    return {"checked": True, "chars": len(body), "findings": findings,
            "problem_count": len(findings)}


#: 卡点词表：结论里出现这些词，才算"说了卡在哪"。
#:
#: 刻意不收"没有""不足""问题"这类词：它们恰恰出现在这一格要拦的话术里 ——
#: 实测（2026-09-29）：`"已全部核对完成，没有发现问题"` 里含"没有"，
#: 于是"只核对了"被读成"点名了卡点"，判据直接失效。词表只留指向具体缺失的词。
BLOCKER_WORDS: tuple[str, ...] = ("缺", "未接线", "没接线", "预算", "无法", "卡在",
                                  "卡点", "需要补", "待补", "尚无", "尚未")

#: 数据面表（判定"库变了没有"时只看这些；台账与用量账不算产出）。
#: S1r 并表之后 `concepts` 那一格换成 `statements`（概念行住它里面）：
#: 老名字留在名单里会让 `snapshot_counts` 把"并走"读成"这张表没有产出"，
#: 而 `statements` 不进名单则"写了命题/概念"这件事在推进判据里看不见。
DATA_TABLES: tuple[str, ...] = (
    "search_requests", "literature", "statements", "relations", "research_questions",
    "conjectures", "analysis_reports", "reprocess_requests", "experiments",
    "attack_plans", "documents", "dependencies", "review_findings",
)


def snapshot_counts(store: Any) -> dict[str, int]:
    """数据面各表的行数（判定"这一步到底动了什么"用的基线）。"""
    return {t: len(_rows(store, t)) for t in DATA_TABLES}


def progress_findings(before: Mapping[str, int], after: Mapping[str, int], *,
                      final: str, steps: int = 0) -> dict[str, Any]:
    """这次运行是'推进'、'明说卡点'、还是'只核对'。

    这是"脑子"的机械半：推进的标志必须落在库上（有人真的写了行），
    否则就得在结论里点名卡在哪。"查了一圈然后说完成了"两者都不满足 ⇒ checked_only。
    """
    delta = {t: int(after.get(t, 0)) - int(before.get(t, 0)) for t in DATA_TABLES}
    changed = {t: v for t, v in delta.items() if v}
    text = final or ""
    blockers = [w for w in BLOCKER_WORDS if w in text]
    if changed:
        verdict = "advanced"
    elif blockers:
        verdict = "blocked_named"
    else:
        verdict = "checked_only"
    findings: list[str] = []
    if verdict == "checked_only":
        findings.append("既没有写下任何一行数据，也没有在结论里点名卡在哪 ⇒ 只核对了")
    if verdict == "advanced" and not text.strip():
        findings.append("写了数据但没有给结论：读的人不知道这一步推进到哪里")
    return {"checked": True, "verdict": verdict, "delta": changed, "blockers": blockers,
            "steps": int(steps), "findings": findings, "problem_count": len(findings)}


#: 判据"结论有没有强于它挂的证据"的机械半只有一份实现：`claimanatomy.validate_claim`
#: 的 `overclaim`（`evidence_kind != proof` 而正文出现 `OVERCLAIM_MARKERS`）。
#:
#: 这一层不再另立词表 —— 第一版我写了 `STRENGTH_WORDS = ("证明","定理",…)`，
#: 测试当场抓到两个误报（`服从中心极限定理` 是定理的名字、`不构成证明` 是明说不是证明），
#: 而更要紧的是：`claimanatomy` 早就有这条判据（且它的词表由
#: `doc_tools.OVERCLAIM_MARKERS` 唯一提供，还有测试钉住两边是同一个对象）。
#: 于是这里的职责改成"把那份判据的结论翻译成 faculty 视图"，而不是再判一次。
#:
#: `draft/39` §3.8（2026-10-05）之后这条判据有了自己的 code（`overclaim` = 第 6 族）：
#: 族号要能直接印在拒信里，而它此前与"status × evidence_kind 交叉"共用
#: `inconsistent_status` ⇒ 两族在拒信里长得一样。旧 code 仍留在表里（旧行/旧调用点）。
CLAIM_STRENGTH_CODES: tuple[str, ...] = ("overclaim", "inconsistent_status")


def claim_strength_findings(claims: Sequence[Mapping[str, Any]], *,
                            codes: Sequence[str] = CLAIM_STRENGTH_CODES,
                            ) -> dict[str, Any]:
    """逐条比对"这条断言说了多强"与"它挂的证据等级"（能思辨的机械半）。

    返回 `{"checked", "verdict", "total", "overclaimed", "missing_evidence", "findings"}`：
    - `overclaimed`：`claimanatomy` 判成 `inconsistent_status` 的那些断言（逐条带 code/message）；
    - `missing_evidence`：连 `evidence_kind` 都没有的断言 —— 它不是"没问题"，是"判不了"，
      两栏分开报（三态纪律）。

    判不了"这句话到底证明了没有"（那是语义半 `judges.claims.conclusion_strength` 的事），
    也不自己判"证据等级够不够"（那是 `claimanatomy` 的事）。
    """
    from . import claimanatomy as CA

    over: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for i, claim in enumerate(claims or ()):
        cid = str(claim.get("claim_id") or f"#{i + 1}")
        if not str(claim.get("evidence_kind") or "").strip():
            missing.append({"claim_id": cid, "why": "没有证据等级 ⇒ 这一条判不了"})
            continue
        try:
            issues = CA.validate_claim(claim).issues
        except Exception as exc:  # noqa: BLE001 —— 判不了就如实说判不了，不许静默放过
            missing.append({"claim_id": cid, "why": f"校验没跑成：{type(exc).__name__}: {exc}"})
            continue
        hit = [iss for iss in issues if getattr(iss, "code", "") in codes]
        if hit:
            over.append({"claim_id": cid, "evidence_kind": str(claim.get("evidence_kind")),
                         "codes": [iss.code for iss in hit],
                         "messages": [iss.message for iss in hit]})
    total = sum(1 for _ in (claims or ()))
    if over:
        verdict = "overclaimed"
    elif missing:
        verdict = "unjudgeable"
    else:
        verdict = "within_evidence"
    findings = [f"{o['claim_id']}：{msg}" for o in over for msg in o["messages"]]
    findings += [f"{m['claim_id']}：{m['why']}" for m in missing]
    return {"checked": True, "verdict": verdict, "total": total, "overclaimed": over,
            "missing_evidence": missing, "findings": findings,
            "problem_count": len(findings),
            # 判据出处：`draft/39` §3.8 之后这条是第 6 族（`overclaim`）。
            # 旧名（`inconsistent_status`）仍被 `CLAIM_STRENGTH_CODES` 认，
            # 但"出处"这一栏只写现在这一个 —— 两族共用一个名字正是这次要修的东西。
            "criterion_source": f"claimanatomy.{CLAIM_STRENGTH_CODES[0]}"}


def trace_findings(store: Any, pairs: Sequence[Sequence[str]], *, text: str = "",
                   ) -> dict[str, Any]:
    """矛盾的溯源机械半：每一对矛盾引用的材料必须存在，且文内至少点名一份。

    `pairs` 是 `[(表名, id), ...]`（例如 `[("literature", "0001"), ("experiments", "0003")]`）。
    返回 `{"checked": True, "verdict": "traced"|"untraced"|"dangling", ...}`。

    它判不了"读得忠不忠实"（那是 `quoteverify` 与语义判据的事），
    但它能判"有没有真的去读"—— 这一步不需要模型，而且是"追本溯源"这句话的最小落地。
    """
    from . import schema as S

    dangling: list[str] = []
    for pair in pairs:
        if len(pair) < 2:
            dangling.append("（形态不合法：" + "、".join(map(str, pair)) + "）")
            continue
        table, ident = str(pair[0]), str(pair[1])
        rows, home = _home_rows(store, table)
        if home not in S.TABLES:
            dangling.append(f"{table}/{ident}（没有这张表）")
            continue
        field = S.TABLES[home]["id_field"]
        if ident not in {str(r.get(field)) for r in rows}:
            dangling.append(f"{table}/{ident}")
    named = [f"{t_}/{i}" for t_, i in ((str(p[0]), str(p[1])) for p in pairs if len(p) >= 2)
             if str(i) in (text or "")]
    if dangling:
        verdict = "dangling"
    elif named or not text:
        verdict = "traced"
    else:
        verdict = "untraced"
    findings: list[str] = []
    if dangling:
        findings.append("引用的材料不存在或表名不认识：" + "、".join(dangling))
    if verdict == "untraced":
        findings.append("文内没有点名任何一份被追溯的材料：追本溯源至少要说清读了哪一份")
    return {"checked": True, "verdict": verdict, "pairs": len(list(pairs)),
            "dangling": dangling, "named": named, "findings": findings,
            "problem_count": len(findings)}


def selftest() -> int:
    """自检：三个机械半各自能抓到一种缺陷，且干净样本不被误报。"""
    import tempfile

    from .store import Store

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        st = Store(PurePath(td) / "ws")
        st.init()
        with st.tx(*CR.tables_for_concept_write("relations", "conjectures", "experiments"),
                   actor="probe") as tx:
            CR.upsert_legacy_shaped(tx, {"concept_id": "0001", "name": "群", "definition": "d",
                                   "created_at": "2026-01-01T00:00:00+00:00",
                                   "updated_at": "2026-01-01T00:00:00+00:00"})
            CR.upsert_legacy_shaped(tx, {"concept_id": "0002", "name": "阿贝尔群", "definition": "d",
                                   "created_at": "2026-01-01T00:00:00+00:00",
                                   "updated_at": "2026-01-01T00:00:00+00:00"})
            tx.upsert("relations", {"relation_id": "0001", "concept_ids": ["0001", "0002"],
                                    "description": "阿贝尔群是群", "lit_id": "0001",
                                    "quote": "q", "page_range": {"start": 1, "end": 1},
                                    "created_at": "2026-01-01T00:00:00+00:00",
                                    "updated_at": "2026-01-01T00:00:00+00:00"})
            tx.upsert("conjectures", {"conjecture_id": "0001", "statement": "有限群都循环",
                                      "negation_statement": "", "form": "universal",
                                      "testable": True, "origin": "gap", "status": "proposed",
                                      "created_at": "2026-01-01T00:00:00+00:00",
                                      "updated_at": "2026-01-01T00:00:00+00:00",
                                      "created_by": "D"})

        # 高观点：引用落地（负控：一个不存在的 id）+ 声称的对没有边（负控）+ 干净样本
        bad = overview_findings(st, "见 concepts/0001 与 concepts/9999，另有 relations/0001 支撑",
                                claimed_pairs=[["0001", "0002"]])
        if "concepts" not in bad["unknown_ids"] or "9999" not in bad["unknown_ids"]["concepts"]:
            problems.append(f"不存在的概念 id 没被抓到：{bad['unknown_ids']}")
        if bad["unsupported_pairs"]:
            problems.append(f"有边的对不该被判 unsupported：{bad['unsupported_pairs']}")
        rev = overview_findings(st, "干净", claimed_pairs=[["0002", "0001"]])
        if rev["unsupported_pairs"]:
            problems.append("同一条边（反向）应判 direct")
        lonely = overview_findings(st, "干净", claimed_pairs=[["0002", "0404"]])
        if not lonely["unsupported_pairs"]:
            problems.append("没有边的对没有被判 unsupported")
        # 过程号：不存在的 t-9999 也要被抓到（它可归属到 tasks 表）
        proc = overview_findings(st, "见 tasks/9999 与 t-9999", claimed_pairs=[])
        if "tasks" not in proc["unknown_ids"]:
            problems.append(f"过程号没被抓到：{proc['unknown_ids']}")

        # 敢创新：猜想卫生（testable 无对立面 + 僵尸）
        hyg = conjecture_hygiene(st)
        kinds = {f["kind"] for f in hyg["findings"]}
        if "no_negation" not in kinds or "zombie" not in kinds:
            problems.append(f"猜想卫生没抓到该抓的：{sorted(kinds)}")

        # 有品味：体例（负控：缺标题 + 占位符）
        style = style_findings("这是一段没有标题的文字，TODO 还没写", require_disclaimer=True,
                               disclaimer="本结论为交叉验证所得")
        skinds = {f["kind"] for f in style["findings"]}
        for want in ("no_title", "placeholder", "disclaimer_mismatch"):
            if want not in skinds:
                problems.append(f"体例检查漏了 {want}：{sorted(skinds)}")
        clean = style_findings("# 标题\n\n正文。\n", require_disclaimer=True,
                               disclaimer="本结论为交叉验证所得"
                               ).__class__  # 只取类型，避免我在这里写一个假样本
        del clean
        ok_style = style_findings("# 标题\n\n正文。本结论为交叉验证所得\n", require_disclaimer=True,
                                  disclaimer="本结论为交叉验证所得")
        if ok_style["problem_count"]:
            problems.append(f"干净样本被误报：{ok_style['findings']}")

        # 脑子：推进 / 明说卡点 / 只核对
        base = snapshot_counts(st)
        adv = progress_findings(base, {**base, "statements": base["statements"] + 1},
                                final="写了两个概念", steps=2)
        if adv["verdict"] != "advanced":
            problems.append(f"写了行却没判 advanced：{adv}")
        blk = progress_findings(base, base, final="卡在缺一条引理，需要补证据", steps=3)
        if blk["verdict"] != "blocked_named":
            problems.append(f"点名了卡点却没判 blocked_named：{blk}")
        only = progress_findings(base, base, final="已全部核对完成", steps=4)
        if only["verdict"] != "checked_only" or not only["findings"]:
            problems.append(f"只核对没被抓到：{only}")

        # 能思辨：溯源（存在的材料 + 文内点名 / 点名了不存在的东西 / 什么都没点名）
        traced = trace_findings(st, [("concepts", "0001"), ("relations", "0001")],
                                text="见 concepts/0001 的原始定义")
        if traced["verdict"] != "traced":
            problems.append(f"溯源正控没通过：{traced}")
        dangling = trace_findings(st, [("concepts", "0404")], text="见 concepts/0404")
        if dangling["verdict"] != "dangling":
            problems.append(f"引到不存在的材料没被抓到：{dangling}")
        untraced = trace_findings(st, [("concepts", "0001")], text="我查过了，不一致")
        if untraced["verdict"] != "untraced":
            problems.append(f"没点名材料没被抓到：{untraced}")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（引用落地 / 猜想卫生 / 体例 / 推进与卡点；各有一条负控与一条干净样本）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())
