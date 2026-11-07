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
# 改前 `quote_reason` 里那段理由是**自由文本**：写一句"无干净依据"就能过
# （98 的真机读数：000040–000048 九条同一秒批量放弃，理由逐字都是同一句
# "verifications/ 下不存在 0000NN.jsonl"），而"同一 label 再登记一条"这件事
# 在盘上没有任何结构化读数（000049 → 000050：label 同为 `lem:cancel`、
# `line_range` 同为那份稿、"区别只是一处措辞"）。所以这一节把"理由"从一段散文
# 变成**两档受控形状**：每一档都要求指出业主原话里点名的那样东西。
#
# ## 为什么形状住在 `quote_reason` 里（与上面那段同一个理由）
#
# 不新增列 = 不改磁盘契约（新增列属 FC-27 的 schema 迁移）。所以结构化理由住进
# 理由正文那一格：`abandoned@<ISO8601>@<JSON>`。JSON 的键就是两档各自要求的那几格
# （`abandon_kind` / `abandon_basis` / `defect_ref` / `difficulty` / `salvaged`）。
# 历史行那一段自由文本照旧读得出来（`parse_abandon` 不变），只是它
# `parse_abandon_reason()["structured"]` 为假 —— 于是"这一行的换号理由齐不齐"
# 在盘上是一个可读的读数，而不是靠人去猜那段散文是什么意思。

#: 换号理由的**两档**（业主原话里的 1 与 2）。只许这两个值：
#: 多一个"其它"就等于给自由文本留了后门（"作业规格不是命题"那一类暂无这一档，
#: 见 `docs/ROLE-GUIDE.md` 同批报告里的待裁项）。
ABANDON_KIND_MATH_ERROR = "math_error"
ABANDON_KIND_DIFFICULTY = "difficulty"
ABANDON_KINDS: tuple[str, ...] = (ABANDON_KIND_MATH_ERROR, ABANDON_KIND_DIFFICULTY)

#: 写口要认的那五个键（两个必填 + 三个按档必填）。工具声明与白名单都从这里取。
ABANDON_PARAM_KEYS: tuple[str, ...] = ("abandon_kind", "abandon_basis", "defect_ref",
                                       "difficulty", "salvaged")

#: `salvaged` 里每一条引理的 `kind` 取值 —— 业主原话是"拆出落成**引理**"。
#:
#: `schema` 里没有 statements.kind 的词表（`schema.Statement.kind: str = "theorem"`，
#: 见 `schema.py:2363` —— 它是个自由字符串，schema 不校验取值）；可判真假的断言类
#: 那几档的真身在 `secretary.PROPOSITION_KINDS`（`secretary.py:1367`：
#: theorem / lemma / proposition / corollary / conjecture）。其中 `lemma` **就是**
#: 业主说的"引理"，所以这里直接用它、不需要退到"最接近的一档"。
SALVAGED_KINDS: tuple[str, ...] = ("lemma",)

#: 一条 `defect_ref` 的形状：`verifications/<命题号>.jsonl#<验证号>`（业主给的样例
#: `verifications/<号>.jsonl#v-00000N`）。号必须是 6 位（本仓的 id 宽度）。
DEFECT_REF_RE = re.compile(r"^verifications/(\d{6})\.jsonl#(v-\d{6})$")


def abandon_proposition_kinds() -> tuple[str, ...]:
    """哪些 `kind` 算"命题"（这道闸只管它们）。真身是 `secretary.PROPOSITION_KINDS`。

    ## 为什么是它、不是 `schema` 里另立一张表
    `schema` 对 `statements.kind` 没有词表（`Statement.kind` 是自由字符串，见
    `schema.py:2363` 一带），所以"可判真假的断言类"这件事只在一处被定义过：
    `secretary.PROPOSITION_KINDS`（`secretary.py:1367`）= theorem / lemma /
    proposition / corollary / conjecture。它同时也是"参不参与同一命题判定"的判据
    （`_is_proposition_kind`）—— 同一个概念两处各写一张表就会漂。

    `concept` / `definition` 不在其中（`secretary.NOT_APPLICABLE_KINDS`，
    `secretary.py:235`）：概念行没有"条件 ⇒ 结论"，也就谈不上"命题本身有数学错误"
    或"证明遇到的困难" ⇒ **放弃 concept 不该被这道闸拦**（业主 2026-11-07 的边界）。
    认不出的 kind 一律**不拦**：闸只对"确定是命题"的那几档生效，免得把将来的新
    kind 一刀切挡死（那是"装错位置"的同一种病）。
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


def _defect_refusal(store: Any, root: str, ref: str,
                    basis: str) -> tuple[dict[str, Any], str, str]:
    """核一条 `defect_ref`：必须真的存在、且判词是「有毛病」或轴为 `fault`。

    返回 `(detail, refused_code, why)`：成功时 `refused_code` 是空串。
    """
    m = DEFECT_REF_RE.match(str(ref or "").strip())
    if not m:
        return {}, "abandon_defect_ref_unreadable", (
            f"defect_ref 必须是 `verifications/<6 位命题号>.jsonl#v-<6 位验证号>` "
            f"（收到 {str(ref or '')!r}）")
    sid, vid = m.group(1), m.group(2)
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
    step = row.get("defect_step")
    detail: dict[str, Any] = {"defect_step": step if isinstance(step, int) else None,
                              "verdict": verdict, "axis": axis,
                              "verification": str(row.get("verification_id") or "")}
    if isinstance(step, int) and step >= 1:
        if not _step_pattern(step).search(str(basis or "")):
            return detail, "abandon_defect_step_mismatch", (
                f"{ref} 指出的缺陷在第 {step} 步，而 abandon_basis 里没有点名"
                f"「第 {step} 步」⇒ 读的人对不上「错在哪一步」（业主原话：需在换号理由中"
                "指出错误）")
    return detail, "", ""


def check_abandon_reason(store: Any, *, kind: Any, basis: Any, defect_ref: Any = "",
                         difficulty: Any = "", salvaged: Any = (),
                         root: str = "") -> dict[str, Any]:
    """换号理由的**唯一判据**（两档）：返回 `{checked, refused, why, problems, …}`。

    这是业主 2026-11-07 那句裁定的机器落点。两个写口（`apply_abandonment` 与
    `Secretary.amend_statement_meta`）都只调它，不各写一份校验 —— 两处各写一份，
    "什么算给清了理由"就会在两个出口长出两种答案。

    ## 两档各自要求什么
    | `abandon_kind` | 必须给 | 判据 |
    |---|---|---|
    | `math_error` | `defect_ref` + `abandon_basis` | `defect_ref` 那一行必须**真的存在**、其判词是「有毛病」或轴为 `fault`；`abandon_basis` 必须点名那一行的 `defect_step`（"错在第几步"） |
    | `difficulty` | `difficulty` + `salvaged` + `abandon_basis` | `salvaged` 非空；每条 `stmt_id` 必须真的在册、`status=active`、`kind` 属于引理类（:data:`SALVAGED_KINDS`） |

    ## 三态
    `checked=True` = 理由齐；`checked=False` + `refused` = 受控拒绝（一个字节都不写）。
    这里没有"没查成"与"不合格"的折叠：读 `refused` 的具体码就知道缺哪一格。
    """
    out: dict[str, Any] = {
        "checked": False, "refused": "", "why": "", "problems": [],
        "abandon_kind": "", "abandon_basis": "", "defect_ref": "", "difficulty": "",
        "salvaged": [], "detail": {},
    }
    got_kind = str(kind or "").strip()
    got_basis = str(basis or "").strip()
    if not got_kind and not got_basis:
        out.update(refused="abandon_reason_missing",
                   why=("放弃/换号必须给 `abandon_kind`（math_error 或 difficulty）与 "
                        "`abandon_basis`（理由正文）两格 —— 只写 status='abandoned' 的"
                        "自由文本理由不算给清了理由（业主 2026-11-07）"))
        return out
    if not got_kind:
        out.update(refused="abandon_reason_missing",
                   why=(f"`abandon_basis` 有了，而 `abandon_kind` 是空的 —— 它只许两个值 "
                        f"{list(ABANDON_KINDS)}：不接受「是哪一档我自己看着办」"))
        return out
    if got_kind not in ABANDON_KINDS:
        out.update(refused="abandon_kind_not_allowed",
                   why=(f"abandon_kind 只许 {list(ABANDON_KINDS)} 之一（收到 {got_kind!r}）—— "
                        "第三档不接受：业主只裁了两档，多一档就是给自由文本留后门"))
        return out
    if not got_basis:
        out.update(refused="abandon_reason_missing",
                   why=(f"`abandon_kind={got_kind}` 有了，而 `abandon_basis`（理由正文）是空的 "
                        "⇒ 读的人看不出错在哪 / 难在哪"))
        return out
    out.update(abandon_kind=got_kind, abandon_basis=got_basis)
    root_now = str(root or getattr(store, "root", "") or "")
    if got_kind == ABANDON_KIND_MATH_ERROR:
        ref = str(defect_ref or "").strip()
        if not ref:
            out.update(refused="abandon_defect_ref_required",
                       why=("math_error 这一档必须给 `defect_ref`（形如 "
                             "`verifications/<号>.jsonl#v-00000N`）—— 业主原话："
                             "「需在换号理由中指出错误」，而指出错误要有可核的那一行"))
            return out
        detail, code, why = _defect_refusal(store, root_now, ref, got_basis)
        if code:
            out.update(refused=code, why=why, defect_ref=ref, detail=detail)
            return out
        out.update(defect_ref=ref, detail=detail)
        out.update(checked=True, why=f"math_error：理由引到 {ref}（判词「有毛病」）")
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
    rows, read_why = _statement_rows(store)
    if rows is None:
        out.update(refused="abandon_salvaged_not_registered",
                   why=f"`statements` 读不出来（{read_why}）⇒ 没法核 salvaged 里那几条在不在册")
        return out
    problems: list[str] = []
    kept: list[dict[str, str]] = []
    for one in items:
        sid = one["stmt_id"]
        row = rows.get(sid)
        if row is None:
            out.setdefault("problems", []).append(f"{sid}：不在册")
            out.update(refused="abandon_salvaged_not_registered",
                       why=(f"salvaged 里的 {sid} 不在 statements 里 ⇒ 引理必须是真的"
                            "登记过的那一条（受控拒绝，一个字节都不写）"))
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
        kept.append({"label": one["label"] or str(row.get("label") or ""), "stmt_id": sid})
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
                      difficulty: str = "", salvaged: Sequence[Mapping[str, str]] = ()) -> str:
    """把两档理由拼成落盘那一段（`quote_reason` 里 `@` 之后的正文）。

    形状是 JSON（`ensure_ascii=False`、键排序）：它必须能被机器逐格读回
    （读数要按 `abandon_kind` 分组、要判"是否带证据"），而自由文本做不到这件事。
    人类可读的那一段是 `abandon_basis` 这一格本身 —— 它没有被压缩成标签。
    """
    payload: dict[str, Any] = {"abandon_kind": str(kind or ""),
                               "abandon_basis": str(basis or "").strip()}
    if str(defect_ref or "").strip():
        payload["defect_ref"] = str(defect_ref).strip()
    if str(difficulty or "").strip():
        payload["difficulty"] = str(difficulty).strip()
    items = [{"label": str(one.get("label") or ""), "stmt_id": str(one.get("stmt_id") or "")}
             for one in (salvaged or ())]
    if items:
        payload["salvaged"] = items
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_abandon_reason(text: Any) -> dict[str, Any]:
    """读一条放弃标记里的**结构化理由**（读侧唯一实现）。

    返回 `{"checked", "structured", "abandon_kind", "abandon_basis", "defect_ref",
    "difficulty", "salvaged", "complete", "why"}`。三态与原模块同一条纪律：

    - `structured=False` ⇒ 这是历史行（`@` 之后是一段自由文本）：结构化的那几格
      一个都读不出来，`why` 说明"换号理由不齐" —— 它**不是**"没有理由"；
    - `structured=True` 而 `complete=False` ⇒ 形状能读、但那一档要求的格子缺了
      （例如 math_error 没有 `defect_ref`）⇒ `why` 点名缺哪一格；
    - `complete=True` ⇒ 那一档该有的都在。
    """
    out: dict[str, Any] = {
        "checked": False, "structured": False, "abandon_kind": "", "abandon_basis": "",
        "defect_ref": "", "difficulty": "", "salvaged": [], "complete": False, "why": "",
        "at": "",
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
    out.update(complete=True)
    return out


def relabel_events(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按 `label` 收"放弃/换号"这一件件事（读侧唯一实现，换号读数与登记读数共用）。

    一次 `abandoned` 就是一次"这一条被放下了"；同一个 label 下出现 N 次，就是这条
    定理名换号 N 次（98 的 `lem:cancel`：000049 与 000050 各一次 ⇒ 2 次）。
    **不做阈值拦截**（业主只要它显形）：这里只给读数，判不判门由调用方决定。

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


def apply_abandonment(store: Any, *, statement_id: str, reason: str, at: str = "",
                      actor: str = "secretary-B", abandon_kind: Any = "",
                      abandon_basis: Any = "", defect_ref: Any = "",
                      difficulty: Any = "", salvaged: Any = ()) -> dict[str, Any]:
    """把一条已登记命题标成 `abandoned`（写侧唯一实现：理由与时间一起落盘）。

    这是业主 2026-11-01 那句「拿不到V签就得一直改，或者放弃原命题」里
    "放弃"那一条的落地：它把命题从"还欠一个签"的集合里挪走，同时也把名下开着的
    重送义务作废（`vreceipts.close_resubmits_for`，`close="expired"`）—— 不一起办，
    "放弃"会被"名下还有未消的板项"反锁死（`retire_integrity`）。

    ## 2026-11-07（业主裁定）：放弃"可判真假的断言类"命题时必须给结构化理由
    业主逐字：「换号需给清理由：1.命题有实质数学错误；2.证明过程中遇到难以逾越的困难。
    对于1，需在换号理由中指出错误；对于2，需指出困难，并将原先证明中可取之处拆出落成引理。」

    - `kind ∈ secretary.PROPOSITION_KINDS`（theorem / lemma / proposition / corollary /
      conjecture）⇒ 必须给 `abandon_kind` + `abandon_basis`（math_error 再要
      `defect_ref`，difficulty 再要 `difficulty` + `salvaged`），判据是
      :func:`check_abandon_reason`；**不齐 ⇒ 受控拒绝，一个字节都不写**。
    - `concept` / `definition` / 认不出的 kind ⇒ **不受这道闸管**（概念不是命题，
      谈不上"命题有数学错误"或"证明遇到困难"）：理由仍必须是可解析的放弃标记
      （`schema.Statement.validate` 那条老闸照旧）。

    ## 已经把这一条标成 `abandoned` 的行（幂等重放）不走新闸
    重放不是一次新的换号：历史行（98 里那批只有自由文本的行）必须还能被幂等重放，
    否则"先补理由、再关板项"这条路会被闸反锁死。要**补**理由，走
    `Secretary.amend_statement_meta`（它会把新理由写进 `quote_reason`）。

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
    if str(current.get("status") or "") == "abandoned":
        was = parse_abandon(current.get("quote_reason"))
        if was.get("checked"):
            out.update(checked=True, abandoned=True, already=True,
                       at=str(was.get("at") or ""), reason=str(was.get("reason") or ""),
                       marker=str(current.get("quote_reason") or ""),
                       row=current, why="这一条早就是 abandoned（幂等：不改任何格）")
            out["resubmits"] = close_resubmits(store, statement_id=sid,
                                               why="命题被明确放弃（幂等重放）")
            return out
    # ---- 新的一次放弃：命题类必须过结构化理由那一关（业主 2026-11-07）----
    kind_now = str(current.get("kind") or "").strip().lower()
    if kind_now in abandon_proposition_kinds():
        form = check_abandon_reason(store, kind=abandon_kind, basis=abandon_basis,
                                    defect_ref=defect_ref, difficulty=difficulty,
                                    salvaged=salvaged)
        out["form"] = dict(form)
        if not form.get("checked"):
            out.update(refused=str(form.get("refused") or "abandon_reason_missing"),
                       why=str(form.get("why") or "换号理由不齐 ⇒ 整笔不写"))
            return out
        reason = structured_reason(kind=str(form["abandon_kind"]),
                                   basis=str(form["abandon_basis"]),
                                   defect_ref=str(form.get("defect_ref") or ""),
                                   difficulty=str(form.get("difficulty") or ""),
                                   salvaged=form.get("salvaged") or ())
    try:
        marker = abandon_marker(at=stamp, reason=str(reason or ""))
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
    if str(current.get("status") or "") != "abandoned":
        out["changes"] = [f"status: {current.get('status')} → abandoned",
                          f"quote_reason: {str(current.get('quote_reason') or '')[:40]!r} "
                          f"→ {marker[:60]!r}"]
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

