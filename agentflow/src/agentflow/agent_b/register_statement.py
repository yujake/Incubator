"""角色 B 的动作 `register_statement`（`draft/37` §46）：把一条命题登记进命题台账。

## 为什么需要这个动作

§44.4 的真机读数把"审阅并 polish 一篇外部论文"这条链的堵点定在动作表上：
主控只能 `conductor.summon` 动作，而"把论文里的定理登记成 `statements` 行"原先只有
工具（`table.create`，A–D 都能调）—— `agent_b/` 里 `statements` 一个字都没有，
所以即使 A 把文集登记好了（§46 的另一个动作），命题台账仍然建不起来，
G 就没有可引的 `lit:`/命题依据，H 也没有可审的对象。

B 的边界里本来就写着"命题台账三件套缺一不可"（完整假设的正文 / 逐字证明摘录 / 出处），
这个动作就是那句话的执行面。

## 三个"必填"与它们各自防的是什么

1. `statement_full`（含完整假设的命题正文）：省掉假设的命题会被下游当成无条件成立
   —— 那是 FC-23 在命题级的同一种病；
2. `proof_text`（逐字摘录）：`quote_verified` 的比对对象就是它，没有它"引文回验"无从做起；
3. `source_lit_id`（`origin="external_lit"` 时）：出处必须真的存在 —— 本动作在写库前
 核一次 `literature` 表，引用一个不存在的 `lit_id` 直接拒（`kind="unknown_lit_id"`），
   与 `doc.build_document` 的 `check_citations` 同一条纪律：坏引用不许进库。

## 第四个必填：出处（按来源分档，`draft/37` §68）

`external_lit` 的命题要给非空的 `page_range`（`start` 或 `label` 至少一个）；
`own_result` 的命题要给 `doc_id` 或非空的 `line_range`（`start` / `label`）。
为什么不是"有这一栏就行"：第十三趟主控传的是 `{"start": null, "end": null}` ——
形状在场、内容是空的 —— 六条命题因此都落成了"看着有出处、其实没有"的行，
而审稿判据当场判它们缺页码，整条验收不及格。
为什么按来源分档（人裁的甲档）：从文献里摘的命题才有"第几页"这件事，
自有结果的出处是 `doc_id`/`line_range` —— 对后者要页码等于让它编一个数字。
写入口与 `reviewaccept._c_statements` 逐条对齐。

`quote_verified` 是三态：`True` 逐字通过 / `False` 比对不一致 / `None` 还没查。
只要不是 `True` 就必须给 `quote_reason`（包括"还没查"），这条由 `Statement.validate()`
与这里的预检双保险 —— 预检存在的理由是把 `kind` 说清楚（调用方要能分辨"参数不对"
与"还没查"）。

## 第五、第六个必填：逐字证明与 ID 形态（`draft/37` §87）

上面那句"双保险"原先只保了一半：`origin="own_result"` 缺 `proof_text`、以及
`doc_id`/`source_lit_id` 形态不对（写成 `"doc:0000"`），都只由 `Statement.validate()`
抛 `ValueError` —— 而它抛在事务里，调用方拿到的是一个异常，不是一条带 `kind` 的
拒绝。T1 第 2 趟真机读数：这一动作被召唤 14 次，6 次落"执行中异常"（就是这一路），
另外 8 次返回了 `ok=False` 却被台账记成 `outcome=ok` —— 两种形态都不像"拒绝"。

于是这里补齐两级预检：`missing_proof_text` 与 `bad_id`。
纪律与其余几级相同：要求写进模型看得见的形状（`specs/b.py`），也在写入口拦下并命名。
`Statement.validate()` 仍然是第二道保险（它保的是"绕开本动作的写库路径"）。

## 第七件：拒绝要自报"这是一次拒绝"（`draft/37` §88 的根因）

返回 `ok=False` 还不够。主控的终态映射原先只看"handler 有没有返回 dict"，
于是这一动作的 10 种拒绝全被记成 `outcome=ok` —— T1 第 2 趟真机：8 次拒绝
在台账上长得像 8 次成功，而 `statements` 是 0 行，整条链在这里静默停住。

所以下面每条拒绝都走 :func:`agentflow.refusals.refuse`：它带上受控的 `refusal_reason`
（`invalid_params` —— 词表的定义正是"参数/前置条件不满足：这次调用本身不成立"）。
不这么写的话，终态只能落 `failed`（"执行了、没成功"），那会把
"我参数给错了"与"代码崩了"重新混成一件事。

## 第八件：五元证据位随这一行一起落（`R3` 组 9 / EE-07）

`draft/39` §3.14 起"这条命题算不算定理"由五位读数派生（`evidencebits.derive_grade`），
而 `statements.bits` 这一栏此前从来没有过产出方：真机读数 138 行命题、带 bits 0 行。
于是所有消费方（收工门、状态报告、`closing` 的收工读数）读到的永远是"五位全空 ⇒ 猜想"，
而盘上那 138 行到底是"确实只是猜想"还是"没人算过"，从数据面分不出来。

现在在这一动作里把位算好、与命题那一行同一次事务写进去（`bits_of` 是纯函数，
形状判据只用 `evidencebits`，不抄第二份口径）。三态：

- 算得出 ⇒ 写；等级由 `derive_grade` 现算（盘上那一份只是缓存，判据不读它）；
- 算不出（`bits_of` 自己抛了）⇒ 拒绝并如实记 `kind="bits_compute_failed"` ——
  不许写一个空 `bits`：空 `bits` 读出来是"五位全空"，与"我们没算"长得一模一样；
- 形状不合规 ⇒ 拒绝并如实记 `kind="bad_bits"` + 逐条 `problems`，整笔不写。

谁签哪位：B 在登记这一刻能作证的只有第 2 位（有证明）与它的来源
（引用命题的凭据是文献代号；自产命题的凭据是证明摘录）。`numeric`/`formal`（E）、
`reviewed`（V）、`audited`（H）都不是 B 的读数，一律按"还没做"留空 —— 替别人签
正是这套位要堵的洞（`evidencebits.BIT_OWNERS` 是那五位的 owner 表）。
"""
from __future__ import annotations

from ._support import S
from .. import evidencebits as _EB
from ..refusals import refuse as _refuse


def _normalize_range(raw: object, *, what: str) -> tuple[dict, str]:
    """把 `page_range` / `line_range` 归一化，返回 `(归一后的字典, 拒绝理由)`。

    ## 为什么必须有这一级（`draft/83` §7 的 D71，T1 第 18 趟真机读数）

    真机：主控派 `B.register_statement` 登记 Kuchment 那一条时，把页码写成了
    字符串（`{"start": "343", "end": "414"}`）。它在库里一路走到
    `S.PageRange.from_dict(...)`，而 `PageRange.__post_init__` 直接拿两个值比大小
    （`self.start < 1` / `self.start > self.end`）⇒ `TypeError: '<' not supported
    between instances of 'str' and 'int'` 从动作里抛出去，
    台账上那一行落成 `failed`（"执行了、没成功"），而不是一条能读懂的拒绝
    —— 于是"参数类型写错了"与"代码崩了"又被混成一件事（这一条与本节其余七级预检
    是同一条纪律：要求写进模型看得见的形状，也在写入口拦下并命名）。

    口径（三态，不猜）：

    - `int` / 纯数字串（`"343"`）⇒ 归一成 `int`；
    - `None` / 空串 ⇒ 保持"不知道"（篇幅与行号的"未知"是合法状态，由 `label` 表达）；
    - 其余（`"343-414"` / `"p.343"` / 浮点 / 列表 / 布尔）⇒ 拒绝并说明收件格式。
      布尔刻意不收：`True` 会被 `int()` 读成 1，悄悄造出一个页码。
    - 形状不是对象 ⇒ 拒绝（`dict("abc")` 会抛，那是同一类崩溃）。

    范围本身的合法性（`>=1`、`start <= end`）在这里也先判一遍：留到 `schema` 里判
    就是"从事务里抛 `ValueError`"，调用方拿不到可读的 `kind`。
    """
    if raw is None or raw == "":
        return {}, ""
    if not isinstance(raw, dict):
        return {}, (f"{what} 必须是对象（例如 {{\"start\": 343, \"end\": 414}} 或 "
                    f"{{\"label\": \"全文未分页\"}}），收到 {type(raw).__name__}：{raw!r}")
    out: dict = {}
    for field in ("start", "end"):
        if field not in raw:
            continue
        value = raw[field]
        if value is None or value == "":
            out[field] = None
            continue
        if isinstance(value, bool):
            return {}, (f"{what}.{field} 收到布尔 {value!r} —— 页码要的是整数或纯数字串，"
                        f"布尔会被读成 1/0 而悄悄造出一个页码")
        if isinstance(value, int):
            out[field] = value
            continue
        text = str(value).strip()
        if text.isdigit():
            out[field] = int(text)
            continue
        return {}, (f"{what}.{field} 必须是整数或纯数字串（如 343 或 \"343\"），"
                    f"收到 {value!r} —— 形如 \"343-414\" / \"p.343\" 的写法请拆成 start/end，"
                    f"或者只给 {what}.label 保留原始书写形态")
    if "label" in raw and raw.get("label"):
        out["label"] = str(raw["label"])
    start, end = out.get("start"), out.get("end")
    for name, value in (("start", start), ("end", end)):
        if isinstance(value, int) and value < 1:
            return {}, f"{what}.{name} 页码必须 >= 1，收到 {value}"
    if isinstance(start, int) and isinstance(end, int) and start > end:
        return {}, f"{what}.start({start}) 不能大于 {what}.end({end})"
    return out, ""


class _RegisterStatement:
    def _statement_bits(self, *, origin: str, lit_id: str, proof_text: str,
                        quote_verified: bool | None) -> tuple[dict, dict | None]:
        """按 `evidencebits` 现算五元位，返回 `(bits, 拒绝)`；拒绝非空 ⇒ 整笔不写。

        三态见模块 docstring 的"第八件"。这里只做两件事：「算」（`bits_of`）与
        「关形状」（`bits_shape_problems`）。判据本体一个字都不在这里写 ——
        两份口径一旦分家，"没做过"与"做过没通过"就会在某一处被压平，而门照样亮绿。

        为什么自产命题的 `proof` 要看 `origin`：`proof_text` 那一栏对 `external_lit`
        是"从原文摘下来的逐字摘录"，它本身不构成我方的证明过程。若不分来源就把它
        当成第 2 位，一条引文回验没过（`quote_verified=False`）的外部命题会被记成"有证明"，等级也从
        猜想抬到预备定理级 —— 而那正是这套位要堵的那类自报。
        """
        own = str(origin) == "own_result"
        text = str(proof_text or "")
        try:
            bits = _EB.bits_of(
                origin=origin,
                source_lit_id=lit_id,
                quote_verified=quote_verified,
                proof=bool(text.strip()) and own,
                proof_process=text if own else "",
            )
            problems = list(_EB.bits_shape_problems(bits))
        except Exception as exc:  # noqa: BLE001 - 算不出来要如实记，不许折成空 bits
            return {}, _refuse(
                "bits_compute_failed",
                f"五元位算不出来（{type(exc).__name__}: {exc}）⇒ 整笔不写。"
                "这一档与『形状不合规』分开命名：前者是判据自己坏了（要修代码），"
                "后者是这一行的输入拼错了（要改参数）—— 处置不同，读数就必须能分辨")
        if problems:
            return {}, _refuse(
                "bad_bits",
                "五元位形状不合规（判据取自 evidencebits.bits_shape_problems）⇒ 整笔不写："
                + "；".join(problems),
                problems=problems)
        return bits, None

    def register_statement(
        self,
        *,
        statement_full: str,
        source_lit_id: str = "",
        proof_text: str = "",
        kind: str = "theorem",
        label: str = "",
        statement_text: str = "",
        origin: str = "external_lit",
        page_range: dict | None = None,
        evidence_kind: str = "cross_check",
        quote_verified: bool | None = None,
        quote_reason: str = "",
        #: 这条引文是**怎么**回验通过的（`schema.QUOTE_MODES`：`verbatim` 逐字命中 /
        #: `semantic` 语义相同 —— 业主 2026-10-14：「回验……保持语义相同即可」）。
        #: 不给就按历史行读（`True` ⇒ 逐字那一档），但**新写方应当说清方式**。
        quote_mode: str = "",
        #: 语义那一档的**证据**（业主 2026-10-14：「语义那一档必须留证据」）：
        #: `quote_span` 是来源里那一段逐字正文，`quote_call_sha256` 是那次语义判定的
        #: 调用记录（H 的 `judge_quote_semantics` 回执里 `call.prompt_sha256`）。
        #: 标了 `quote_mode="semantic"` 而缺这两样 ⇒ `Statement.validate()` 当场拒。
        quote_span: str = "",
        quote_call_sha256: str = "",
        derived_from: list | None = None,
        doc_id: str = "",
        line_range: dict | None = None,
    ) -> dict:
        """登记一条命题，返回 `{"ok": True, "stmt_id": ..., "row": {...}}`；不合规就零写入。"""
        full = str(statement_full or "").strip()
        if not full and str(kind or "").strip() != "concept":
            # 命题没有"内容待补"这一档：省掉假设的命题会被下游当成无条件成立。
            # 概念有（业主 `draft/97` §14.13 逐字：「抽不到定义的概念就让A去网上搜，
            # 写入时定义内容留空，等A返回后写入」）⇒ 空定义的概念要落行并带待补标记，
            # 而不是在这里被拒。这一档此前也拒，于是"定义还没抽到"这件事在 B 的动作里
            # 根本走不通（只有直接调秘书那条路能落）—— 而 §15.4 最常见的场景
            # （B 消化 A 查回来的论文时撞到生僻定义）走的正是这个动作。
            return _refuse("bad_statement",
                           "statement_full 不能为空 —— 只有短版（statement_text）不算数："
                           "省掉假设的命题会被下游当成无条件成立"
                           "（`kind=\"concept\"` 除外：定义抽不到时留空 + 待补标记，见 draft/97 §14.13）")
        origin = str(origin or "external_lit")
        if origin not in S.STATEMENT_ORIGINS:
            return _refuse("bad_origin",
                           f"origin 必须是 {S.STATEMENT_ORIGINS} 之一，收到 {origin!r}")
        # 第九级（`draft/83` §7 的 D71）：出处页码/行号的类型在写库前归一。
        # 真机读数（T1 第 18 趟）：`{"start": "343", "end": "414"}` 一路走到
        # `PageRange.__post_init__` 的比大小，`TypeError` 从动作里抛出去。
        page_norm, page_bad = _normalize_range(page_range, what="page_range")
        if page_bad:
            return _refuse("bad_page_range", page_bad)
        line_norm, line_bad = _normalize_range(line_range, what="line_range")
        if line_bad:
            return _refuse("bad_line_range", line_bad)
        evidence_kind = str(evidence_kind or "heuristic")
        if evidence_kind not in S.EVIDENCE_KINDS:
            return _refuse("bad_evidence_kind",
                           f"evidence_kind 必须是 {S.EVIDENCE_KINDS} 之一，收到 {evidence_kind!r}"
                           "（它是证据**强度**，不是来源；来源走 source_lit_id）")
        lit_id = str(source_lit_id or "").strip()
        if origin == "external_lit" and not lit_id:
            return _refuse("missing_source",
                           "origin='external_lit' 时必须给 source_lit_id —— "
                           "从文献摘的命题必须有出处（没有出处的摘录就是二手结论）")
        if quote_verified is not True and not str(quote_reason or "").strip():
            # 这一条不按 origin 放宽（本轮试过：被 `test_action_surface_matches_acceptance`
            # 那条"每一级缺失都被拒"的梯子当场判红）：三态纪律管的是"盘上那一格不许留白"，
            # `own_result` 也一样有"我为什么还没核"可以说（没核 / 没有第二份文本可比 /
            # 证明在 proof_text 里……）。业主 §14.11 的两件式契约管的是内容
            # （定理内容 + 证明过程），不是把三态纪律免掉。
            return _refuse("missing_quote_reason",
                           "quote_verified 不是 True 时必须给 quote_reason —— "
                           "三态纪律：没通过要说为什么没通过，**还没查**也要说出来（不许留白）")
        # 出处：「填了形状不算填了内容」（`draft/37` §68 的第十二/十三趟真机读数），
        # 而"出处是哪一栏"按来源分档（§68 人裁的甲档，与审稿判据逐条对齐）。
        #
        # 实测（第十三趟）：主控给六条 `external_lit` 命题传了
        # `page_range={"start": null, "end": null}` —— 字段在场、内容是空的 ——
        # 于是这一行在台账上"有出处"，而审稿判据（`reviewaccept._c_statements`）
        # 当场报"缺 page_range（页码）"，整条验收因此不及格。
        # 写入口与判据必须说同一件事：判据要求的东西，写入口在「进库之前」就要拦
        # （否则台账里会长期躺着一批"看着有、其实没有"的行，只有走完整审稿流程的人才会发现）。
        if origin == "external_lit":
            page = dict(page_norm)
            if not (page.get("start") or str(page.get("label") or "").strip()):
                return _refuse("missing_page_range",
                               "origin='external_lit' 时必须给出处页码："
                               "`page_range` 要么给 start（可带 end），要么给 label"
                               "（例如「全文未分页」「附录 A」）—— 只传 "
                               "`{\"start\": null, \"end\": null}` 等于没给，"
                               "审稿判据会判这一行缺出处页码")
        #: 这一笔是不是"自产命题但证明还没做完"（F-05 的待办那一档）。
        #: 必须在两个分支之外先给默认值：它下面要在返回值里用到，而
        #: `external_lit` 那一支不会走到 `own_result` 那一支里 —— 第一版把赋值写在
        #: 分支里，于是所有 `external_lit` 登记都在返回值那一行 `NameError`
        #: （`tasks` 落 `failed`）。判据：`tests/test_intake_actions.py` 的四跳链。
        needs_proof = (str(origin) == "own_result" and not str(proof_text or "").strip())
        if str(origin) == "external_lit":
            page = dict(page_norm)
            if not (page.get("start") or str(page.get("label") or "").strip()):
                return _refuse("missing_page_range",
                               "origin='external_lit' 时必须给出处页码："
                               "`page_range` 要么给 start（可带 end），要么给 label"
                               "（例如「全文未分页」「附录 A」）—— 只传 "
                               "`{\"start\": null, \"end\": null}` 等于没给，"
                               "审稿判据会判这一行缺出处页码")
        elif str(origin) == "own_result":
            line = dict(line_norm)
            if not (str(doc_id or "").strip()
                    or line.get("start") or str(line.get("label") or "").strip()):
                return _refuse("missing_own_source",
                               "origin='own_result' 时必须给我们自己的出处："
                               "`doc_id`（我方稿件那一行的 id）或 `line_range`"
                               "（start / label 至少一个）—— 自有结果的出处不是"
                               "「文献第几页」，那一栏要它等于让它编一个数字")
            # 第五级（§87）：自产命题的证明。
            #
            # F-05（主控裁定，2026-10-06）改的这一格：以前这里 `_refuse`，于是
            # "证明还没做完"这一档永远进不了库，也就永远没有一条待办能被
            # 秘书消费（`draft/53:181` 的消费端要的是"摆出来"，不是"拦住"）。
            # 现在不拦：落库 + 按既有字段如实标记 ——
            #   `proof_text` 留空（它确实没有）、`quote_verified=None` +
            #   `quote_reason` 写明"证明还没做完"，等级由 `evidencebits.derive_grade`
            #   现算（缺 proof 位 ⇒ "猜想"，不是证明级）。
            #
            # 硬顺序（主控点名）：本改动必须排在 B 删掉 `schema.Statement.validate`
            # 里那条 `own_result` raise 之后 —— 否则这一笔会在事务里抛
            # `ValueError`，比"写库前预检拒绝"更坏（拒绝是受控的，抛异常不是）。
            if needs_proof and not str(quote_reason or "").strip():
            # 三态那一栏必须自己说清"为什么还没有"：只留一个空字段等于把
            # "没查"记成一笔没人能接手的账（与上面 `missing_quote_reason` 同一条纪律，
                # 差别只在"这里不再拒收，而是替它把理由写实"）。
                quote_reason = "证明还没做完 / 未核到 ⇒ 这一行按待办挂着（等级现算是『猜想』）"

        # 第六级（§87）：ID 形态。`source_lit_id`/`doc_id` 的形态由 `schema.require_id`
        # 定义（4 位十进制），这里在写库前用同一个谓词核，拒绝时带上 `kind` ——
        # "写成 doc:0000" 于是是一条可读的拒绝，而不是事务里抛出的 `ValueError`。
        for _what, _value in (("source_lit_id", lit_id),
                              ("doc_id", str(doc_id or "").strip())):
            if _value and not S.is_valid_id(_value):
                return _refuse("bad_id",
                               f"{_what} 必须是 4 位十进制字符串（如 \"0000\"），"
                               f"收到 {_value!r} —— 形态由 schema.require_id 定义，"
                               "本动作在写库前用同一个谓词核，整笔不写")

        # ---- 业主 2026-10-09：「B 不直接用增工具，秘书实际操作增、改、查工具，
        # B 纯粹负责消化理解」⇒ 上面那些是内容的判据（B 的判断），写盘这一段交给秘书。
        bits, bits_bad = self._statement_bits(
            origin=str(origin), lit_id=lit_id, proof_text=str(proof_text or ""),
            quote_verified=quote_verified)
        if bits_bad is not None:
            return bits_bad
        sec = self._statement_secretary()
        if sec is None:
            return _refuse("secretary_unavailable",
                           "这一趟没有秘书 ⇒ 命题写不了（写入侧是 B 的活，但落盘归秘书："
                           "`Secretary.record_statement`。不许退回'B 自己写'那条后备路）"
                           + (f"；{self.secretary_problem}" if self.secretary_problem else ""))
        payload = {
            "origin": origin, "kind": str(kind or "theorem"), "label": str(label or ""),
            "statement_text": str(statement_text or ""), "statement_full": full,
            "proof_text": str(proof_text or ""), "source_lit_id": lit_id,
            "page_range": dict(page_norm), "quote_verified": quote_verified,
            "quote_mode": str(quote_mode or ""),
            "quote_reason": str(quote_reason or ""), "evidence_kind": evidence_kind,
            "quote_span": str(quote_span or ""),
            "quote_call_sha256": str(quote_call_sha256 or ""),
            "derived_from": S.sorted_unique(list(derived_from or [])),
            "doc_id": str(doc_id or ""), "line_range": dict(line_norm), "bits": bits,
        }
        written = sec.record_statement(payload, role="B")
        if written.get("duplicate") and not written.get("created"):
            # 秘书查重的读数（业主 2026-10-09：「秘书实际操作增、改、查工具」）：
            # 同一条 `statement_full`（按 `textutil.normalize` 比）已在册 ⇒ 不新建行。
            # 对调用方来说这是"这一次没有新行"，必须说出来（`ok=False` + `kind`），
            # 并把既有那一条的号给它 —— 否则它只会看到"没写成"而不知道东西在哪。
            return _refuse("duplicate_statement",
                           "同一条命题（按规范化后的 statement_full 比）已在册 ⇒ "
                           "秘书查重后没有新建行；要引用它请用返回的 stmt_id，"
                           "确实要另起一条才走 `force_new`（本动作不暴露它）",
                           stmt_id=str(written.get("stmt_id") or ""))
        if not written.get("checked") or not written.get("created"):
            extra = {k: v for k, v in written.items()
                     if k in ("literature_rows", "available_lit_ids", "unresolved")}
            return _refuse(str(written.get("refused") or "write_failed"),
                           str(written.get("reason") or "秘书没写这一笔"),
                           stmt_id=str(written.get("stmt_id") or ""), **extra)
        stmt_id = str(written["stmt_id"])
        data = dict(written.get("row") or {})
        # 定义待补那一档要看得见（`draft/97` §15.4 的补法优先级）：
        # 抽不到定义 ⇒ ①先问直接父（它手里有原文，就地能给）→ ②A 上网搜 → ③B 自撰。
        # 这里只把"要给谁"写进读数（载体那一步在循环那一层：它才知道自己的父是谁）。
        pending_defs = ([{"kind": "pending_definition", "table": "statements", "id": stmt_id,
                          "missing": "statement_full", "who": "direct_parent",
                          "why": ("抽不到定义 ⇒ 先问直接父（最常见：父就是 A，原文在它手里）；"
                                  "父也办不了才轮到 A 上网搜或 B 自撰基本概念")}]
                        if (str(data.get("status") or "") == "pending_definition"
                            or int(written.get("pending_concepts") or 0)) else [])
        return {"ok": True, "stmt_id": stmt_id, "source_lit_id": lit_id or None,
                "quote_verified": quote_verified, "origin": origin,
                "quote_mode": str(quote_mode or ""),
                "evidence_kind": evidence_kind, "row": data,
                "deps_state": str(written.get("deps_state") or ""),
                "deps_written": int(written.get("deps_written") or 0),
                "deps_dangling": list(written.get("deps_dangling") or []),
                "deps_unmappable": list(written.get("deps_unmappable") or []),
                "pending_definitions": pending_defs,
                # F-05：缺证明这一档不再拒收，但绝不静默接受 ——
                # 它在返回值里明写成一条待办（秘书的 `pending_inbox` 从既有标记
                # 也能扫到它；这里再给一次是为了让调用方当场就知道）。
                "pending": ([{"kind": "missing_proof", "table": "statements",
                              "id": stmt_id, "missing": "proof_text", "who": "F",
                              "why": "自产命题没有证明 ⇒ 等级现算是『猜想』"}]
                            if needs_proof else []),
                "note": ("登记 ≠ 核对：quote_verified 是三态（True/False/None），"
                         "它不是 True 时下游必须按 `quote_reason` 读，不许当成通过。"
                         "五元位已随这一行落库（现算等级 "
                         f"{bits.get('grade')}；第 2 位来源 "
                         f"{bits.get('evidence', {}).get('proof_source') or '（空）'}）——"
                         "等级不许自报，判据永远现算。"
                         "这一笔由秘书落盘（洗格式 / 拿编号 / 查重 / 改表四件一起做完），"
                         f"表格 {written.get('tables')}、路径组 {written.get('path_groups')}。"
                         + ("这一行**缺 proof_text**（自产命题没有证明）：它进去了，"
                            "但等级现算是『猜想』，`pending` 里挂着待办。"
                            if needs_proof else ""))}
