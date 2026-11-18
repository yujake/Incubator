"""F 的证明手稿：依赖段由 F 写在这里，依赖台账由 B 读稿登记。

口径：作者只写内容，登记由收方读稿产生（与 V 读 F 的手稿再签字同一个逻辑）。所以本文件
只做两件不写台账的事：

1. `AgentF.proof_manuscript(...)`：把这一轮的论证写成一份手稿文件。稿名只按 F 自己的
   稿号（`reports/f-proof-<稿号>.md`；一个稿号 = 一份文件 = 一份证明）。稿号由
   :mod:`agentflow.manuscriptids` 发（`data/counters.json` 的 `manuscript` 号段），
   不用命题号、也不用计划号 —— 命题号是 B 收录时现取的，计划号只管继续/放弃/更改。
   两份都含那一节固定格式的 `## 依赖`（三列必填，见 `agentflow.depsection.COLUMN_KEYS`；
   路径号不进稿，老盘带那一列的四列表仍读得回）。
2. `AgentF.preview_dependencies(...)`：只读预览 —— 拿一份手稿正文，按 B 那条判据
   （`depsection` 的解析 ＋ 引用档位门 ＋ 三态读数）算出"如果现在入库会怎样"，
   F 据此在自己这一侧先看见问题。它一行都不写盘。

为什么依赖段必须由 F 写在手稿里（而不是 F 直接写表）：真机 `dependencies` 全 0 行的根因
不是"没人想写"，而是"没人有入口"—— 唯一点名的依赖正路是 G 的 `doc.register_dependency`，
F 一件依赖写入口都没有；而秘书那条"从证明正文扫依赖"只认 `stmt:` / `lit:` / `exp:` /
`doc:` 前缀，真机的证明是中文散文（"由引理 2"）⇒ 扫出 0 条。处置不是"给 F 开一个写表的
工具"，而是把格式定死：作者在手稿里写清楚"我引了哪一条、用在哪一步、属于第几条证明"，
收方（B）照表登记。散文读不出来的东西，一张三列的表读得出来。

## 这一份手稿里有什么

```
# F 的证明手稿：<子目标>

- 计划：<plan_id> · 子目标：<sid>

## 命题
<命题正文>

## 证明
1. <这一步说了什么>（依据：stmt:000001）
2. ...

## 依赖
| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |
|---|---|---|---|
| 由定理甲，G 有 p 阶元 | stmt:000000 | 第 1 步 | 1 |
```
"""

from __future__ import annotations

from ._support import Any, Mapping, S, Sequence, _short

from pathlib import Path

from .. import depsection as _DS
from .. import evidencebits as _EB
from .. import manuscriptform as _MF
from .. import manuscriptids as _MID
from .. import statementledger as SL   # 命题台账的查口（按号 / 按关键词，只读、零模型）
from ..manuscriptform import (  # noqa: F401 —— 两族唯一实现在这里，本模块只转发
    carry_sign_block,
    formal_shape_problem,
)

#: 不在可引池里的在册行分三档（`citable_statements` 的计数口径，2026-11-10）。
#:
#: 为什么必须是三档而不是两档：`below` 那句话说的是"这一条能用、只是档位不够"，
#: 而概念行「没有档位这一说」（`not_applicable`）。改前两档分流把它塞进 `below`
#: ⇒ 提示词对模型说"另有 1 条的等级低于 pre_theorem（conjecture / strong_conjecture
#: 那一档）"，模型读成"库里有 1 条低档命题"，于是去想办法抬它的档（那条路不存在）。
BUCKET_BELOW = "below"
BUCKET_UNKNOWN = "unknown"
BUCKET_CONCEPT = "concept"


def _non_citable_bucket(grade: Any) -> str:
    """一条"不在可引池里"的在册行的分档 —— 唯一判据（`citable_statements` 读它）。

    三档的边界逐条：

    - 空串 ⇒ `BUCKET_UNKNOWN`（"判不了"不是"最弱一档"，fail-closed：也不许引）；
    - `evidencebits.GRADE_NOT_APPLICABLE` ⇒ `BUCKET_CONCEPT`（概念没有等级轴；
      它不是 conjecture / strong_conjecture，不许被算进"等级低"那一句）；
    - 其余（真等级，且低于门槛）⇒ `BUCKET_BELOW`。

    反真空：`tests/test_f_prompt_does_not_miscount_concepts_as_low_grade.py` 把本函数
    打桩成恒 `BUCKET_BELOW`（= 改前那一句 `else: below += 1`）⇒ 那条判据当场红。
    """
    text = str(grade or "").strip()
    if not text:
        return BUCKET_UNKNOWN
    if text == _EB.GRADE_NOT_APPLICABLE:
        return BUCKET_CONCEPT
    return BUCKET_BELOW


def _signed_row(row: Mapping[str, Any]) -> bool:
    """这一行是不是「已签」（`reviewed=true`）—— 从五元位的唯一读入口现算。

    概念没有等级轴，但良定义证明照样有第 3 位：`conceptrows.concept_bits` 只在
    `vsigns.sign_reading.state == "signed"` 时把它翻真。所以"已签概念"读的就是与
    "已签命题"同一个位，不另立一个布尔（另立一个就多一处会漂、而漂的方向是
    "看起来签过"）。位读不出来 ⇒ 假（fail-closed：判不了不是"已签"）。
    """
    try:
        return bool(_EB.bits_from_row(dict(row)).get("reviewed"))
    except Exception:  # noqa: BLE001 —— 判不了按"未签"读，不猜
        return False


def _notes_text(counts: Sequence[str], truncations: Sequence[str]) -> str:
    """读数末尾那一串："另有 …；另有 …；还有 N 条没列…"（空列表 ⇒ 空串）。

    两段分开拼：计数句前面都加"另有"（否则后一句会读成前一句的续写），而截断句
    自带"还有"（`CITABLE_STATEMENTS` 那一句是"没列出来"的读数，不是"另一类"）。
    """
    parts: list[str] = []
    if counts:
        parts.append("另有 " + "；另有 ".join(counts))
    parts.extend(truncations)
    return "；".join(parts)


#: 受控码：proof 档没有 `product.proposition`（2026-11-13，业主裁定 B 硬必填）。
PROPOSITION_MISSING = "proposition_missing"
#: 受控码：这一份稿的路径已经归另一个写者（E，2026-11-15：两个并行的 F 共用一个稿名）。
MANUSCRIPT_PATH_TAKEN = "manuscript_path_taken"
#: 受控码：占用判据没查成（登记读不出来 / 写不进去 / 没有写者身份）—— 判不了 ≠ 可以写。
MANUSCRIPT_OWNER_UNCHECKED = "manuscript_owner_unchecked"


def proposition_missing_why() -> str:
    """`proposition_missing` 的 fix 文案（拒信与三处兜底共读这一句）。

    业主给的逐字口径：「给 `product.proposition`（前提 → 结论）；子目标正文不是命题」。
    """
    return ("这一轮没有 `product.proposition` ⇒ 稿上 `## 命题` 没有可渲染的那段文字。"
            "给 `product.proposition`（那条定理的完整陈述：前提 → 结论）—— "
            "子目标正文不是命题（那是派给你的活）；改法说明 / 作业要求写进 `steps` 或 "
            "`label`。这一份稿一个字节都没写")


def proposition_text(proposition: Any) -> str:
    """`## 命题` 那一节的字节：只认 `product.proposition`（B 硬必填，没有回退算式）。

    ## 为什么没有回退（2026-11-13，W1 真机缺陷 + 业主裁定 B）

    改前 `## 命题` = 子目标正文 ＋「这一条的可检验形式：…」，而子目标正文是派给 F 的活
    （真机 `projects/octahedron-20261113` 的 `reports/f-proof-000002.md`：「按 V u-000005 的
    唯一缺陷修订第 7 步…其余八步一字不动；同一份稿就地重写后重送 V」）⇒ 那段作业话被写进
    `## 命题`、被 V 签、被 B 拒（B 按这一节登记 `statement_full`）。回退算式等于把病根留在
    数据形状里；B 硬必填把它从形状上掐掉：没有 `proposition` ⇒ 受控拒
    `proposition_missing`（`proposition_missing_why()` 是那句 fix 文案）。

    `testable` 从此只属于计划 / 子目标，不再进 `## 命题` 的渲染（它是验收口径，不是定理）。

    反真空：把任何一个调用点换回"子目标正文拼可检验形式"，
    `tests/test_f_proposition_comes_from_the_product.py::test_c_*` 当场红。
    """
    return str(proposition or "").strip()


def proof_body_text(product: Mapping[str, Any]) -> str:
    """`## 证明` 那一节的字节（唯一算式；渲染与写前闸都读它）。

    与 :func:`proposition_text` 同一条纪律：写进盘的那一段与形态闸看到的那一段必须由
    同一个函数给出。闸只判命题形态（`proof_text` 只进材料摘要的 `proof_chars`），
    但"闸看到的稿"与"写下的稿"是同一份的这件事，不该靠两处各拼一遍来保证。
    """
    steps = [s for s in (product.get("steps") or []) if isinstance(s, Mapping)]
    lines = []
    for i, step in enumerate(steps, 1):
        cites = [str(c) for c in (step.get("cites") or [])]
        suffix = f"（依据：{'、'.join(cites)}）" if cites else "（前提）"
        lines.append(f"{i}. {str(step.get('text') or '').strip()}{suffix}")
    return "\n".join(lines or ["（这一轮没有交出论证正文）"])


class _Manuscript:
    """F 的证明手稿（依赖段 ＋ 只读预览）＋ 提示词里那份"可引用的在册命题"。"""
    #: 手稿落点（工作区相对）：与 `_Core.REPORT_DIR` 同一个目录（`reports/`）。
    MANUSCRIPT_DIR = "reports"
    #: 依赖段里"引用（F 的原话）"那一格最多占多少字（超出截断，并写明截断了）。
    QUOTE_CHARS = 80
    #: 一条在册命题在提示词里最多占多少字（超出截断，并写明截断了）。
    STATEMENT_ITEM_CHARS = 160
    #: 提示词里最多列几条"可引用的在册命题"（超出只报条数，不静默截断）。
    CITABLE_STATEMENTS = 20

    # ---------------------------------------------------------------- 读侧

    def statement_rows(self) -> tuple[list[dict[str, Any]], str]:
        """把 `statements` 读成行列表，并如实带回读不成的那一句（空列表 + 非空 why）。

        绝不用 `[]` 冒充"台账里一条命题都没有" —— 那是两件事。
        """
        # 取数走查口的唯一取数口（三态：读不到 ≠ 台账里一条命题都没有）。
        rows, problem, error = SL.rows_of(self.store)
        if problem:
            return [], (f"{error.get('type') or '?'}: "
                        f"{error.get('message') or problem}")
        return rows, ""

    def citable_statements(self) -> tuple[list[str], list[str], str]:
        """B 已收录、这一轮写证明时可读可引的命题 ⇒ `(提示词行, 可引 id, 说明)`。

        业主的裁定是"写证明时允许读 B 侧已收录的定理" —— 读得到的前提是提示词里有它们。
        改前提示词只列子目标自己攒的那几条证据，模型根本不知道台账里有哪些命题可引，
        于是"引用在册定理"这件事在真机里没有发生的机会。

        列入的条件与 B 读稿时那一条判据同源（`depsection.citation_level_allowed`）：
        只有等级 `pre_theorem` 及以上的才既读得到又引得成（2026-11-05 起门槛读等级，
        不再读 `statements.evidence_kind` 那一列历史）。低于该档的、等级算不出来的
        只报条数并说清"引用它们会被受控拒绝" —— 不列出来，是因为"能引"与"列在这里"
        必须是同一件事（两份清单漂开，模型就会照着引一条注定被拒的）。

        ## 已签概念：可读，但不可引（2026-11-11 补）

        概念不在可引池里（`kind=concept` ⇒ `derive_grade` 短路成 `not_applicable`：
        它没有等级轴），但它可以是「已签」的 —— V 签过它的良定义证明 ⇒ `reviewed=true`。
        改前这一档只报"另有 N 条概念"：F 看得到条数、看不到是哪一条，签过的概念在 F
        眼里等于不存在。现在把已签概念逐条列出来（`stmt:<号>` + `kind=concept` +
        label + 一句正文，截断沿用 `STATEMENT_ITEM_CHARS`），并逐条写明"可读但不可引
        （可引门只放命题）"；未签概念仍只报条数（不列 id、不列正文）—— 两侧都不静默
        消失。概念不进 `ids`：可引清单与可读面是两张表，混一张就会让模型照着引一条
        注定被拒的号。

        计数口径不变：两份清单各自受 `CITABLE_STATEMENTS` 上限约束（这一节只服务一个
        读数面，不另立第二个体量常数），超出上限的那一句必须带"还有 N 条没列"。
        """
        rows, unreadable = self.statement_rows()
        if unreadable:
            return [], [], (f"（`statements` 这一次读不出来：{unreadable} ⇒ 本轮没有可引的"
                            "在册命题可列；那是「读不到」，不是「台账里没有」）")
        #: 可引池只有一处定义（`depsection.citable_pool` = 在册 ∧ 等级 ≥ pre_theorem）：
        #: 提示词里列的这几条与 B / V 收稿时允许引的那一批同一个判据。两份各算
        #: 一份的形态是"提示词里列了、交上去却被拒"（或反过来），而那种漂没有读数。
        pool = _DS.citable_pool(rows)
        usable = [r for r in rows if str(r.get("status") or "") == "active"]
        usable.sort(key=lambda r: str(r.get("stmt_id") or ""))
        eligible: list[dict[str, Any]] = []
        signed_concepts: list[dict[str, Any]] = []
        below = 0
        unknown_level = 0
        unsigned_concepts = 0
        for row in usable:
            if str(row.get("stmt_id") or "") in pool:
                eligible.append(row)
                continue
            bucket = _non_citable_bucket(_DS.statement_grade(row))
            if bucket == BUCKET_CONCEPT:
                # 概念行不是"等级低"，是「没有等级轴」：`evidencebits.derive_grade` 对
                # `kind="concept"` 短路成 `not_applicable`，它既不是 conjecture 也不是
                # strong_conjecture。改前这一档被算进 `below`，于是提示词说"这 1 条的
                # 等级低于 pre_theorem（conjecture / strong_conjecture 那一档）"——
                # 读这句话的人得到的结论是"这条能用但等级不够"，而实际是一条概念。
                #
                # 已签的那一条要列出来（改前只报条数 ⇒ 签过的概念在 F 眼里不可见）；
                # 未签的仍只报条数：没有签的正文不许混进"可读面"。
                if _signed_row(row):
                    signed_concepts.append(row)
                else:
                    unsigned_concepts += 1
            elif bucket == BUCKET_UNKNOWN:
                unknown_level += 1
            else:
                below += 1
        lines: list[str] = []
        ids: list[str] = []
        listed = eligible[: self.CITABLE_STATEMENTS]
        for row in listed:
            sid = str(row.get("stmt_id") or "")
            kind = str(row.get("kind") or "")
            label = " ".join(str(row.get("label") or row.get("statement_text") or "").split())
            grade = _DS.statement_grade(row)
            line = (f"stmt:{sid}（kind={kind or '（没写）'}，label={label or '（没有标签）'}，"
                    f"grade={grade or '（算不出来）'}）")
            if len(line) > self.STATEMENT_ITEM_CHARS:
                line = _short(line, self.STATEMENT_ITEM_CHARS)
            lines.append(line)
            ids.append(f"stmt:{sid}")
        counts: list[str] = []
        if below:
            counts.append(f"{below} 条的等级低于 {_DS.CITATION_MIN_LEVEL}（conjecture / "
                          "strong_conjecture 那一档）—— 引用它们会被受控拒绝")
        if unsigned_concepts:
            # 单列一句、且明说"不是档位不够"：这句是给模型读的，它必须先知道概念不在
            # 等级轴上，才不会被诱导去"把它引上来让它够格"（那条路今天不存在）。
            # "未签"两个字必须在：已签的另有清单，这一句只剩未签的那一批 —— 不写清
            # 就会读成"概念全都在这里、一条也没漏"。
            counts.append(f"{unsigned_concepts} 条概念（未签：`reviewed=false`，只报条数、"
                          "不列 id 也不列正文；`kind=concept`，不参与可引等级："
                          "概念没有等级轴，不是“档位不够”）")
        if unknown_level:
            counts.append(f"{unknown_level} 条的等级算不出来 —— 也不许引（读不到就不放行）")
        truncations: list[str] = []
        if len(eligible) > len(listed):
            truncations.append(f"还有 {len(eligible) - len(listed)} 条够格但没列"
                               f"（这一块只列前 {self.CITABLE_STATEMENTS} 条）")
        # ---- 已签概念：列出来，但只进"可读面"，不进 `ids`
        shown_concepts = signed_concepts[: self.CITABLE_STATEMENTS]
        if shown_concepts:
            # 先说清这一批是什么：混在可引命题里而不加这句，模型会照着引（而那是注定
            # 被拒的）。"可引门只放命题"是原因，"可以读"是它能做的事。
            lines.append("以下概念已签（`reviewed=true`），可读但不可引：可引门只放"
                         "命题（概念没有等级轴，不在可引池里）—— 读得到，但写进 `cites` "
                         "会被拒。")
            for row in shown_concepts:
                sid = str(row.get("stmt_id") or "")
                label = " ".join(str(row.get("label") or "").split())
                body = " ".join(str(row.get("statement_text")
                                    or row.get("statement_full") or "").split())
                line = (f"stmt:{sid}（kind=concept，label={label or '（没有标签）'}；"
                        f"可读但不可引：可引门只放命题）—— 正文：{body or '（没有正文）'}")
                if len(line) > self.STATEMENT_ITEM_CHARS:
                    line = _short(line, self.STATEMENT_ITEM_CHARS)
                lines.append(line)
        if len(signed_concepts) > len(shown_concepts):
            truncations.append(f"还有 {len(signed_concepts) - len(shown_concepts)} 条已签概念没列"
                               f"（这一块只列前 {self.CITABLE_STATEMENTS} 条）")
        text = _notes_text(counts, truncations)
        note = f"（{text}）" if text else ""
        if not eligible:
            empty = ("（台账里现在没有一条站到 "
                     f"{_DS.CITATION_MIN_LEVEL} 级及以上的在册命题 ⇒ 这一轮不许引 `stmt:`；"
                     "要声明前提就把那一步写成 `assumption: true`")
            return lines, ids, empty + (f"；{text}" if text else "") + "）"
        return lines, ids, note

    # ---------------------------------------------------------------- 写手稿

    def dependency_rows(self, product: Mapping[str, Any]) -> list[dict[str, Any]]:
        """这一轮产物里点名的 `stmt:` 引用 ⇒ 依赖段的数据行（一条引用一行）。

        口径与判据都不在这里另写：能进这一份手稿的引用已经在 `_foreign_cites` 与
        `_evidence_digest` 那一层核过（只许引在册 id），本函数只负责"把 F 的原话、
        命题号、用在哪一步、第几条证明"这四格摆出来。
        """
        rows: list[dict[str, Any]] = []
        steps = [s for s in (product.get("steps") or []) if isinstance(s, Mapping)]
        seen: dict[str, int] = {}
        for i, step in enumerate(steps, 1):
            for cite in (step.get("cites") or []):
                text = str(cite).strip()
                if not text.startswith("stmt:"):
                    continue
                bare = text[5:].split("#", 1)[0].strip()
                if not bare:
                    continue
                if bare in seen:
                    # 同一条命题在几步里都引了：依赖边是一条（一条引用一行），
                    # 但"用在哪几步"必须写全 —— 少一步就是"这条边挂错了位置"。
                    rows[seen[bare]]["steps"].append(i)
                    continue
                seen[bare] = len(rows)
                rows.append({
                    "stmt_id": bare,
                    "quote": _short(" ".join(str(step.get("text") or "").split()),
                                    self.QUOTE_CHARS),
                    "steps": [i],
                    "path_group": 1,
                })
        for row in rows:
            row["step"] = "第 " + "、".join(str(n) for n in row.pop("steps")) + " 步"
        return rows

    @staticmethod
    def render_dependency_section(rows: Sequence[Mapping[str, Any]]) -> str:
        """这一节固定格式的表格（转发到 `depsection.render_dependency_section`）。

        「渲染出来的这一份，解析器必须读得回同一批行」由
        `tests/test_dependency_face_is_read_from_f_manuscript.py::test_the_policy_example_is_the_format_the_parser_accepts`
        钉住。实现本体在 `depsection`（解析与渲染必须同一个人写），本方法只转发 ——
        原来这里另写了一份一模一样的渲染，已在 2026-11-04 的统一里删掉。
        """
        return _DS.render_dependency_section(rows)

    def proof_manuscript(self, product: Mapping[str, Any], *, sg: Mapping[str, Any],
                         plan: Mapping[str, Any], label: str = "", proof_no: int = 1,
                         manuscript_id: str = "",
                         ) -> dict[str, Any]:
        """把这一轮的论证写成手稿文件并返回读数（写盘失败不许静默）。

        返回 `{"ok", "path", "text", "rows", "preview", "why", "named_by"}`：`rows` 是依赖段里的
        数据行，`preview` 是"这份手稿交给 B 会怎样"的只读预览（`preview_dependencies`），
        `text` 是整份手稿（调用方可以直接把它交给 B 入库，不必再读盘）。

        ## 写盘之前的命题形态闸不在这里（2026-11-13，W1 真机缺陷）

        真机 `projects/octahedron-20261113`：F 的稿 `reports/f-proof-000002.md` 的 `## 命题`
        是修订说明，F 自己的秘书判过、判的是"不是命题"（台账 12:28:39 那一行
        `checked=True / well_formed=False`），可稿还是落了盘、V 还是签了、B 收录时拒 ——
        签了却永远入不了台账。

        根因是位置：改前这道闸只在 `proofregistry.register_or_rewrite`（登记那一步）跑，
        而手稿在那一步之前已经由本方法写进盘（先写稿、后登记的既有次序）。修法是把同一道
        闸挪到本方法的调用之前（`_Core._proposition_form_precheck`，唯一生产调用点是
        `_apply_round` 的 proof 档）。

        为什么不把闸塞进本方法：本方法是手稿写口，生产之外还有直调（测试 / 内部复用）；
        把"要不要过闸"塞进写口会让直调也凭空多一次模型调用。判据本体仍然只有一处
        （`Secretary.judge_proposition_form`），位置只有一处（调用之前），写口本身只写。

        ## 命名（2026-11-10 业主裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号」）

        稿名只由手稿号决定：`reports/f-proof-<稿号>.md`。命题号是 B 收录时现取的，
        计划号只管继续/放弃/更改 —— 两者都不进稿名。
        `manuscript_id` 由调用方给（同一份稿改稿给同一个号）；不给 ⇒ 向
        :func:`manuscriptids.next_manuscript_id` 要一个新号（绝不覆盖盘上已有的稿）。
        `named_by` 恒为 `"manuscript"`，读的人不必猜。

        ## `-pN` 与 `- 证明号：` 在写侧退役（业主 2026-11-11）

        「一个稿号就相当于是该稿的文件名，不再细分 version 几」⇒ 新写的稿不带 `-pN`
        后缀、稿头也没有 `- 证明号：` 那一行。`proof_no` 形参保留只为旧调用点不必改
        签名，它不参与命名、不参与渲染、也不进返回值。老盘 `reports/f-proof-<号>-p2.md`
        仍能分类 / 读 / 认签，重写它时 `proofregistry._legacy_proof_no_of` 沿用文件名
        里的 N（不改老稿的身份）。

        ## 2026-11-04（业主裁定）：渲染与落盘只剩一份实现
        页头与三节的拼法在 `manuscriptform.render_proof_manuscript`（与 B 的改写稿同
        一段代码），写盘事务在 `manuscriptform.commit_manuscript`。本方法只做两件 F 特有
        的事：把 `steps[]` 拼成证明正文、把读数换成 F 的调用方要的形状。
        """
        sid = str(sg.get("sid") or "")
        plan_id = str(plan.get("plan_id") or "")
        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        ident = self._refresh_identity()          # K1/K2：写稿前补一次实例身份
        mid = str(manuscript_id or "").strip()
        if not mid:
            # 没有给号 ⇒ 这是另一份稿（新稿）：向号源要一个，不猜、不借别人的号。
            # `owner=self.actor`：顺手把发出去的号登记给我，同一路径被别的写者占着时
            # 号源会跳过它（"自动分号"那一半，E）。
            mid = _MID.next_manuscript_id(root, owner=str(self.actor or ""), role="F",
                                          task_id=str(ident.get("task_id") or ""), identity=ident)
        elif not _MID.is_manuscript_id(mid):
            return {"ok": False, "path": "", "text": "", "rows": [], "preview": {},
                    "named_by": "manuscript", "preserved": False, "manuscript_id": mid,
                    "why": (f"手稿号 {mid!r} 不是六位号 ⇒ 这一份稿不落盘"
                            "（稿号由 `manuscriptids.next_manuscript_id` 发）")}
        rows = self.dependency_rows(product)
        # 标题要的是子目标原串（它是这一轮的活的名），`## 命题` 只认 `product.proposition`。
        sg_text = str(sg.get("text") or "")
        #: 这一段就是稿上 `## 命题` 那一节的字节（只认 `product.proposition`，B 硬必填；
        #: 见模块级 `proposition_text`）。形态闸判的也必须是这一段。
        proposition = proposition_text(product.get("proposition"))
        #: `## 证明` 那一节的字节（唯一算式，见模块级 `proof_body_text`）。
        proof_text = proof_body_text(product)
        text = _MF.render_proof_manuscript(
            _MF.FAMILY_F, title=sg_text,
            proposition=proposition,
            proof_text=proof_text,
            dependency_rows=rows, plan_id=plan_id, sid=sid,
            label=label)
        # 一个稿号 = 一份文件：落点只按稿号拼（`proof_no` 不再进名字，业主 2026-11-11）。
        rel = self.manuscript_path(mid)
        if not rel:
            return {"ok": False, "path": "", "text": "", "rows": [], "preview": {},
                    "named_by": "manuscript", "preserved": False, "manuscript_id": mid,
                    "why": f"手稿号 {mid!r} 拼不出规范路径 ⇒ 这一份稿不落盘"}
        if not proposition:
            # ---- 2026-11-13（业主裁定 B）：没有命题就没有可渲染的 `## 命题` -----------
            # 写口这一层也拒（fail-closed）：正常路径由 `_proposition_form_precheck` 在
            # 更早一步拒，这里是直调 `proof_manuscript` 的兜底，一个字节都不写。
            # 次序：已拿签那一档先判（下一段）—— 冻结是"这一份只读"这个更具体的事实，
            # 缺命题只是"这一版没给够"，不该抢它的拒信。
            _missing = {"ok": False, "path": rel, "text": "", "rows": [], "preview": {},
                        "named_by": "manuscript", "preserved": False, "written": False,
                        "manuscript_id": mid, "refused": PROPOSITION_MISSING,
                        "kind": PROPOSITION_MISSING, "proposition": "",
                        "why": proposition_missing_why()}
        else:
            _missing = {}
        # ---- 2026-11-11（业主裁定 ②）：已拿签的那一份只读 -------------------------
        #
        # 这是 F 的手稿写口：`attack.step(product=…)` 与 `proof_manuscript` 直调都
        # 走这里。同一子目标会沿用同一个稿号（`_resolve_manuscript_id`）⇒ 那一份稿已经
        # 拿签时，这一笔就是"改一份只读的稿"：一个字节都不写，受控拒（拒信与 `fs.*`
        # 那一侧同源：`manuscriptfreeze` 一处判据）。
        from .. import manuscriptfreeze as _FZ

        _frozen = _FZ.freeze_reading(root, rel)
        if _frozen.get("frozen"):
            return {"ok": False, "path": rel, "text": "", "rows": [], "preview": {},
                    "named_by": "manuscript", "preserved": False,
                    "manuscript_id": mid, "refused": _FZ.MANUSCRIPT_FROZEN,
                    "kind": _FZ.MANUSCRIPT_FROZEN, "freeze": dict(_frozen),
                    "why": str(_frozen.get("message") or "")}
        if _missing:
            # 没拿签、又没给命题 ⇒ 这一版没有可渲染的 `## 命题`：受控拒 `proposition_missing`。
            return _missing
        # ---- A1：这一份"预写"不许擦掉已经登记的那一条 ------------------------------
        #
        # 生产路径的次序是"先写稿、后登记"（死结 1 的修法），而登记条目就住在同一个
        # 规范路径上（`reports/f-proof-<稿号>.md`）⇒ 每一轮
        # `commit_manuscript` 都会把上一轮写进去的登记元信息（`- 正文sha：` / 命题指纹 /
        # `- 版本：`）连同 `- 标签：` 一起覆盖掉，于是 `register_or_rewrite` 每轮都读成
        # "新命题"（实测 3 轮 `modes=[registered×3]`、形态闸 3 次、`proof_no=[1,1,1]`）。
        # 解耦要成立，这一笔就不能动登记条目：稿在手上（`text` 照给），盘上那一份留给
        # `register_or_rewrite` 去就地重写 `## 证明`。
        kept = self._registered_entry_text(root, rel)
        if kept is not None and not proposition:
            # 重写证明那一档不动 `## 命题`（盘上那一份的命题正文照旧）⇒ 缺 `proposition`
            # 不是错：`text` 用盘上那一份，别拿一份"命题为空"的渲染结果当读数。
            text = kept
        preview = self.preview_dependencies(text)
        if kept is not None:
            # K5：重写支也核占用（改前直接 preserved=True，三个非属主实例重写过同一份稿）。
            _claim = _MID.claim_for_write(root, rel, owner=str(self.actor or ""), role="F",
                                          task_id=str(ident.get("task_id") or ""), identity=ident)
            _refusal = _MID.claim_refusal(
                _claim, rel, path_taken=MANUSCRIPT_PATH_TAKEN,
                unchecked=MANUSCRIPT_OWNER_UNCHECKED)
            if _refusal:
                return {"ok": False, "path": rel, "text": "", "rows": [], "preview": {},
                        "named_by": "manuscript", "preserved": False, "written": False,
                        "manuscript_id": mid, **_refusal}
            got = {"ok": True, "checked": True, "path": rel, "written": False,
                   "preserved": True, "text": kept, "why": ""}
        else:
            # E（2026-11-15）：同一份稿不许两个写者共用一个文件名。走到这一格时 `mid`
            # 已是点名要写的那一份 ⇒ 受控拒（不悄悄换号，否则送审 / 收录会指到另一份）。
            _claim = _MID.claim_for_write(root, rel, owner=str(self.actor or ""), role="F",
                                          task_id=str(ident.get("task_id") or ""), identity=ident)
            _refusal = _MID.claim_refusal(
                _claim, rel, path_taken=MANUSCRIPT_PATH_TAKEN,
                unchecked=MANUSCRIPT_OWNER_UNCHECKED)
            if _refusal:
                return {"ok": False, "path": rel, "text": "", "rows": [], "preview": {},
                        "named_by": "manuscript", "preserved": False, "written": False,
                        "manuscript_id": mid, **_refusal}
            got = _MF.commit_manuscript(
                root, family=_MF.FAMILY_F, text=text, manuscript_id=mid,
                retitle="none", dependency_rows=rows,
                producer=str(self.actor or ""),
                instance=str(ident.get("instance") or ""),
                task_id=str(ident.get("task_id") or ""))
        out = {"ok": bool(got.get("ok")), "path": rel, "text": text, "rows": rows,
               "preview": preview, "named_by": "manuscript",
               "manuscript_id": mid,
               "preserved": bool(got.get("preserved")),
               "why": str(got.get("why") or "")}
        if not got.get("ok"):
            # 写盘那一格失败时保留 F 原来那句"依赖面这一趟只能靠 B 读正文"的读数。
            out["why"] = str(got.get("why") or "") or out["why"]
        return out

    def publish_manuscript(self, manuscript: Mapping[str, Any], *,
                           manuscript_id: str = "",
                           ) -> dict[str, Any]:
        """停用改名：收录拿到命题号之后，稿名一个字都不动（业主 2026-11-10 裁定）。

        裁定逐字：「F 的稿自己维护一套号源，不依赖命题号和计划号。停掉错误的口径。」
        旧口径是「登记成功（拿到命题号）就改名」——它把两个号绑死：稿名从
        `f-proof-plan-<计划号>.md` 变成 `f-proof-<命题号>.md`，于是同一份稿在收录前后
        是两个名字，签块第 9 格、D 的携带单、按号找稿的读方全都要跟着搬。
        现在的口径：稿号是稿号，`reports/f-proof-<稿号>.md` 从写到收录始终是同一个
        名字；命题号由 B 收录时现取，只落在 `statements` 那一行上（记 `manuscript_id`）。

        `published` 恒为 `False`（这一笔没有改名）；`why` 把原因写死，读的人不必猜。

        ## 签名里没有 `statement_id`（2026-11-10 第二刀，业主裁定）

        「对于 F 侧，在实现方面彻底通畅后，撤去所有有关对某个给定命题号进行攻坚或
        写证明的逻辑。」改名这一笔此前还留着 `statement_id="",` 当"兼容形参"——
        它一个字都不参与命名，却把「按命题号写稿」这条接口留在原地（读签名的人会以为
        有这个输入）。这一刀把它删掉：这一层收不到命题号，也就命名不出按号的名字。
        判据：`tests/test_f_does_not_work_for_a_statement_number.py`。
        """
        out = dict(manuscript)
        out["renamed_from"] = ""
        out["published"] = False
        out["retitled"] = False
        out["sign_moved"] = False
        out["sign_step"] = {"checked": False, "found": False, "sha_match": None,
                            "moved": False, "candidates": [], "why": ""}
        out["publish_problem"] = {}
        out["name_changed"] = False
        out["why"] = (
            "稿号是稿号：收录拿到命题号不改稿名 —— 这一份仍是 "
            f"`{str(manuscript.get('path') or '') or '（未给路径）'}`；"
            "命题号只落在 `statements` 行上（行上记 `manuscript_id`），与稿名无关")
        return out

    # -------------------------------------------------------------- 登记条目保护（A1）

    @staticmethod
    def _registered_entry_text(root: Any, rel: str) -> str | None:
        """`rel` 上是不是已经有一条登记条目（是 ⇒ 它的正文；不是 ⇒ None）。

        判据只用一处：`proofregistry.parse_entry(...)["checked"]`（有正文 sha /
        命题指纹 / 版本记录）。手写稿写一行 `- 标签：` 不算（A3 的同一条判据）——
        所以这里不会"因为盘上有个同名文件"就不写稿，只保护真的登记条目。
        """
        if not rel:
            return None
        path = Path(str(root or "")) / rel
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        try:
            from .. import proofregistry as _PR

            return text if _PR.parse_entry(text).get("checked") else None
        except Exception:  # noqa: BLE001 —— 读不出来就按"不是在册"处理（不猜）
            return None

    # -------------------------------------------------------------- 只读预览

    def preview_dependencies(self, manuscript: str) -> dict[str, Any]:
        """只读预览：一份手稿交给 B 入库时，依赖面会变成什么样（一行都不写盘）。

        三态纪律都落在这里：
        - 段里某行读不懂 ⇒ `checked=True` ＋ `ok=False` ＋ `refused`（带行号与列名）；
        - 手稿没有依赖段 ⇒ `ok=False` ＋ `refused=dependency_section_missing`，
          而证明正文里有 `stmt:` 引用时 `deps_missing.state="missing"`（反静默 0 行）；
        - 段里的来源档位不够 / 读不到 ⇒ 与 B 那条判据同一个受控码（`depsection.gate_rows`）。
        """
        text = str(manuscript or "")
        section = _DS.parse_dependency_section(text)
        #: 引用只在"证明正文"那一节里数（手稿开头的元信息不是引用，见
        #: `depsection.proof_body` 的注释）—— 数进来会让 `refs` 与 `derived_from` 都虚高。
        #: 2026-11-09（D4）：缺 `## 证明` ⇒ `proof_body=""`（不回退到依赖段 / 全文），
        #: 这一格只做预览 ⇒ 不拒、`refs=0`，但 `proof_body_state` 如实说"没有这一节"。
        proof_reading = _DS.proof_body_reading(text)
        body = str(proof_reading.get("body") or "")
        out: dict[str, Any] = {"checked": True, "ok": False, "refused": "", "reason": "",
                              "section": section, "rows": section.get("rows") or [],
                              "levels": {}, "would_write": 0, "deps_missing": {},
                              "proof_body_state": str(proof_reading.get("state") or "")}
        refs = _DS.stmt_refs(body)
        # 这一格在下面每一支里都要给，四个入参有四个是同一个（正文 / refs / 段）：
        # 只把"写了多少行"留成参数，五处调用共用这一处拼法。
        def _deps_missing(written: int) -> dict[str, Any]:
            return _DS.deps_missing_reading(
                proof_text=body, deps_written=written, derived_from=refs,
                refs=len(refs), section=section)

        if section.get("refused"):
            out.update(refused=str(section.get("refused")),
                       reason=str(section.get("reason") or ""))
            out["deps_missing"] = _deps_missing(0)
            return out
        if not section.get("present"):
            if refs:
                out.update(refused=str(_DS.REFUSED_SECTION_MISSING),
                           reason=_MF.detail(_MF.DEPENDENCY_SECTION_MISSING,
                                             refs=len(refs)))
            else:
                out["reason"] = (f"手稿里没有 `{_DS.SECTION_HEADING}` 这一节，正文也没有引用任何"
                                 "在册命题 ⇒ 依赖面这一格不适用（B 不会因此拒收：自足的证明合法）")
            out["deps_missing"] = _deps_missing(0)
            return out
        rows = section.get("rows") or []
        # 2026-11-05（缺陷甲）：表在、但 0 行数据而正文点了在册号 ⇒ 预览就必须说"会退"。
        # 改前预览与 B 的登记入口都只看 `present`，于是"交出去会不会被退"这一格会亮 ok。
        #
        # 2026-11-06（业主口径的纠正）：正文里的号必须是"可引"的（在册 ∧ 等级
        # ≥ pre_theorem）；不在册 / 等级不够的号 ⇒ 这一笔写错了（F 读不到它），
        # 预览就报受控拒，拒信点名那个号。可引池只有一处定义（`citable_pool`），
        # 与提示词那份清单、B 的登记入口、V 的依赖面审计同源。
        stmt_rows, problem, error = SL.rows_of(self.store)
        if problem:
            out.update(refused=str(_DS.REFUSED_LEVEL_UNREADABLE),
                       reason=(f"预览要核每条来源的档位、并判正文的引用在不在可引池里，"
                               f"而 `statements` 读不出来"
                               f"（{error.get('type') or '?'}: "
                               f"{error.get('message') or problem}）⇒ 这次预览没查成"))
            return out
        _code, _why = _DS.dependency_consistency_problem(
            text, known_ids=_DS.citable_pool(stmt_rows), statement_rows=stmt_rows)
        if _code:
            out.update(refused=str(_code), reason=str(_why))
            out["deps_missing"] = _deps_missing(0)
            return out
        gate = _DS.gate_rows(rows, stmt_rows)
        out["levels"] = dict(gate.get("levels") or {})
        if not gate.get("ok"):
            out.update(refused=str(gate.get("refused") or ""),
                       reason=str(gate.get("reason") or ""))
            out["deps_missing"] = _deps_missing(0)
            return out
        out.update(ok=True, would_write=len(rows))
        out["deps_missing"] = _deps_missing(len(rows))
        return out

    def promote_manuscript(self, source: str, *, manuscript_id: str = "",
                           text: str = "",
                           delete_source: bool = False,
                           write_dependencies: Any = None) -> dict[str, Any]:
        """把盘上已经存在的一份攻坚稿转成 `reports/f-proof-<稿号>.md`（实现见模块级函数）。

        这是 `publish_manuscript` 的盘上稿入口：这一件读盘上那一份（`notes/…`），
        把它搬到F 自己的稿号下（没给号 ⇒ 向号源要一个）；签块跟着搬、第 9 格手稿号
        按新名重算、形状不对就受控拒绝 —— 判据本体只有一处
        （`manuscriptform.promote_formal`）。签名里没有 `statement_id`
        （2026-11-10 第二刀）：转正不是"按命题号改名"，它按稿号落。
        """
        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        return promote_manuscript(root, manuscript_id=manuscript_id, source=source,
                                  text=text, delete_source=delete_source,
                                  store=self.store,
                                  write_dependencies=write_dependencies)

    def manuscript_path(self, manuscript_id: str = "", *,
                        proof_no: int = 1) -> str:
        """这一份手稿的落点（工作区相对）—— 与 `proof_manuscript` 写的是同一处。

        只按 F 自己的稿号命名：`reports/f-proof-<稿号>.md`。命题号与计划号都不参与
        命名（业主 2026-11-10 裁定）；号形不对 ⇒ 空串（受控，不拼一个看起来像号的路径）。

        `proof_no>=2` 只保留给老盘读/重写兼容（`reports/f-proof-<号>-p2.md` 那一族
        仍在盘上，按原后缀找得到它）；F 的新写路径不传它、也不产生 `-pN`（业主
        2026-11-11：「一个稿号就相当于是该稿的文件名，不再细分 version 几」）。
        """
        return _MID.canonical_rel(manuscript_id, proof_no, legacy=True)

    def rewrite_manuscript_proposition(self, *, manuscript: str, proposition: str,
                                       label: str = "", kind: str = "conjecture",
                                       task_id: str = "") -> dict:
        """把一份「未入册」手稿的 `## 命题` 原位换成新陈述（受控写口；W2·甲）。

        ## 这是什么、不是什么

        - 是「已经签了、但命题节写错」那一档的「兜底写口」：只换 `## 命题` 与稿头的
          命题指纹，`## 证明` 一个字节不动 ⇒ 签盖的正文 sha 不变 ⇒ 不用重签；
        - 不是主路径：主路径是写稿那一刻的形态闸（`proofregistry:666`），那一关
          已经把"命题节写成作业话"挡在落盘之前；
        - 不是动作：F 的动作面没有新增参数（冻结面），这个方法由 F 的维修路径直接调；
          三条边界与全部读数在 `propositionrewrite.rewrite_proposition`（唯一实现）。

        ## 边界（缺一不许，判据在那边）

        ① 命题已进 `statements` ⇒ 受控拒（走重新登记）；② 改前 / 改后必须判成"同一条
        命题"（`Secretary.judge_same_proposition`，两态，判不了 ⇒ 拒）；③ 只走受控写口，
        不在冻结面上开洞（`## 证明` 的 sha 落盘前先核一次）。

        参数：`manuscript` 是工作区相对路径；`proposition` 是新那一节正文（不是"改法说明"）；
        `label` / `kind` 只进同一性判定的材料与台账读数。
        """
        from .. import propositionrewrite as _PRW

        root = self.cfg.get("workspace_root") or getattr(self.store, "root", "") or "."
        got = _PRW.rewrite_proposition(
            store=self.store, root=root, manuscript=manuscript,
            proposition=proposition, secretary=self._secretary(),
            label=label, kind=kind, task_id=task_id)
        got = dict(got)
        got["agent"] = "F"
        return got



# ---------------------------------------------------------------- 转正（攻坚稿 → 正式稿）
#
# 业主口径（2026-11-10）：「F 的稿自己维护一套号源，不依赖命题号和计划号。」
# `publish_manuscript` 不再改名；盘上已经存在的一份稿（`notes/F-conj000000-proof.md`
# 一类，F 自己 `fs.write` 写的攻坚稿）要变成正式稿时，搬到F 自己的稿号下：
# `reports/f-proof-<稿号>.md`（没给号 ⇒ 向 `manuscriptids` 要一个，绝不覆盖别人的稿）。
#
# 2026-11-04（业主裁定）：转正实现只有一份（`manuscriptform.promote_formal`），F 与 B
# 两族由 `family=` 参数区分 —— 本模块这一个只做转发。

#: 转正只收工作区相对路径里的这两种根：`notes/`（草稿本，攻坚手稿）与 `reports/`
#: （正式落点）。唯一的实现在 `manuscriptform`。
PROMOTE_SOURCE_ROOTS: tuple[str, ...] = _MF.PROMOTE_SOURCE_ROOTS


def promote_manuscript(root: Any, *, manuscript_id: str = "", source: str = "",
                       text: str = "", delete_source: bool = False,
                       store: Any = None,
                       write_dependencies: Any = None) -> dict[str, Any]:
    """把盘上已经存在的一份稿转成 `reports/f-proof-<稿号>.md`（转发，判据只在一处）。

    `manuscript_id` 是F 自己的稿号；不给 ⇒ 向 :func:`manuscriptids.next_manuscript_id`
    要一个新号（转正是"这份草稿第一次拿到正式稿号"，不是"按命题号改名"）。
    签名里没有 `statement_id`（2026-11-10 第二刀，业主裁定）：这一层收不到命题号，
    于是"按命题号转正"在结构上不可能。

    返回 `{promoted, path, source, renamed_from, retitled, sign_moved, sign_step,
    problem, source_kept, why, manuscript_id}`；`problem` 是受控读数
    （`kind`/`stage`/`why`）。实现本体在 :func:`manuscriptform.promote_formal`。
    """
    mid = str(manuscript_id or "").strip()
    if not mid:
        mid = _MID.next_manuscript_id(root)
    return _MF.promote_formal(
        root, family=_MF.FAMILY_F, manuscript_id=mid, source=source,
        text=text, delete_source=delete_source, store=store,
        write_dependencies=write_dependencies)
