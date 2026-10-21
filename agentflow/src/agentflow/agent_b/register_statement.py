"""角色 B 的动作 `register_statement`（`draft/37` §46）：把一条命题登记进命题台账。
§44.4 的真机读数把"审阅并 polish 一篇外部论文"这条链的堵点定在动作表上：主控只能 `conductor.summon` 动作，而"把论文里的定理登记成 `statements` 行"原先只有工具（`table.create`，
A–D 都能调）—— `agent_b/` 里 `statements` 一个字都没有，所以即使 A 把文集登记好了（§46 的另一个动作），命题台账仍然建不起来， G 就没有可引的 `lit:`/命题依据，H 也没有可审的对象。
1. `statement_full`（含完整假设的命题正文）：省掉假设的命题会被下游当成无条件成立—— 那是 FC-23 在命题级的同一种病； 2. `proof_text`（逐字摘录）：`quote_verified` 的比对对象就是它，没
有它"引文回验"无从做起； 3. `source_lit_id`（`origin="external_lit"` 时）：出处必须真的存在 —— 本动作在写库前核一次 `literature` 表，引用一个不存在的 `lit_id` 直接拒（`kind="unknown_lit_id"`），
与 `doc.build_document` 的 `check_citations` 同一条纪律：坏引用不许进库。
第四个必填：出处（按来源分档，`draft/37` §68）`external_lit` 的命题要给非空的 `page_range`（`start` 或 `label` 至少一个）；`own_result` 的命题要给 `doc_id` 或非空
的 `line_range`（`start` / `label`）。为什么不是"有这一栏就行"：第十三趟主控传的是 `{"start": null, "end": null}` ——形状在场、内容是空的 —— 六条命题因此都落成了"看着有出处、
其实没有"的行，而审稿判据当场判它们缺页码，整条验收不及格。为什么按来源分档（人裁的甲档）：从文献里摘的命题才有"第几页"这件事，自有结果的出处是 `doc_id`/`line_range` —— 对后者要页码等于让它编一个数字。写入口与 
`reviewaccept._c_statements` 逐条对齐。
`quote_verified` 是三态：`True` 逐字通过 / `False` 比对不一致 / `None` 还没查。只要不是 `True` 就必须给 `quote_reason`（包括"还没查"），这条由 
`Statement.validate()`与这里的预检双保险 —— 预检存在的理由是把 `kind` 说清楚（调用方要能分辨"参数不对"与"还没查"）。
第五、第六个必填：逐字证明与 ID 形态（`draft/37` §87）上面那句"双保险"原先只保了一半：`origin="own_result"` 缺 `proof_text`、以及`doc_id`/`source_lit_id` 形态不对（写
成 `"doc:0000"`），都只由 `Statement.validate()`抛 `ValueError` —— 而它抛在事务里，调用方拿到的是一个异常，不是一条带 `kind` 的拒绝。T1 第 2 趟真机读数：这一动作被召唤 14 次，
6 次落"执行中异常"（就是这一路），另外 8 次返回了 `ok=False` 却被台账记成 `outcome=ok` —— 两种形态都不像"拒绝"。
于是这里补齐两级预检：`missing_proof_text` 与 `bad_id`。纪律与其余几级相同：要求写进模型看得见的形状（`specs/b.py`），也在写入口拦下并命名。`Statement.validate()` 仍然是第二道保险
（它保的是"绕开本动作的写库路径"）。
第七件：拒绝要自报"这是一次拒绝"（`draft/37` §88 的根因）返回 `ok=False` 还不够。主控的终态映射原先只看"handler 有没有返回 dict"，于是这一动作的 10 种拒绝全被记成 `outcome=ok`
—— T1 第 2 趟真机：8 次拒绝在台账上长得像 8 次成功，而 `statements` 是 0 行，整条链在这里静默停住。
所以下面每条拒绝都走 :func:`agentflow.refusals.refuse`：它带上受控的 `refusal_reason`（`invalid_params` —— 词表的定义正是"参数/前置条件不满足：这次调用本身不成立"）。不这
么写的话，终态只能落 `failed`（"执行了、没成功"），那会把"我参数给错了"与"代码崩了"重新混成一件事。
第八件：五元证据位随这一行一起落（`R3` 组 9 / EE-07）`draft/39` §3.14 起"这条命题算不算定理"由五位读数派生（`evidencebits.derive_grade`），而 `statements.bits` 这一
栏此前从来没有过产出方：真机读数 138 行命题、带 bits 0 行。于是所有消费方（收工门、状态报告、`closing` 的收工读数）读到的永远是"五位全空 ⇒ 猜想"，而盘上那 138 行到底是"确实只是猜想"还是"没人算过"，从数据面分
不出来。
现在在这一动作里把位算好、与命题那一行同一次事务写进去（`bits_of` 是纯函数，形状判据只用 `evidencebits`，不抄第二份口径）。
等级由 `derive_grade` 现算（盘上那一份只是缓存，判据不读它）；- 算不出（`bits_of` 自己抛了）⇒ 拒绝并如实记 `kind="bits_compute_failed"` ——不许写一个空 `bits`：空 `bits`
读出来是"五位全空"，与"我们没算"长得一模一样；- 形状不合规 ⇒ 拒绝并如实记 `kind="bad_bits"` + 逐条 `problems`，整笔不写。
`numeric`/`formal`（E）、`reviewed`（V）、`audited`（H）都不是 B 的读数，一律按"还没做"留空 —— 替别人签正是这套位要堵的洞（`evidencebits.BIT_OWNERS` 是那五位的
owner 表）。
第九件：一条定理可以有好几份证明（业主 2026-10-22 的多证明模型，S2 的写侧）
可选参数 `proofs`（JSON 数组，元素 `{proof_no, text}`）把"这条定理的证明有几份"一次交清：
`#p1` 落进既有的 `proof_text`（老字段、老写法逐字不变），`#p2` 及以上落进同一行的证明清单
（键就是 `verifications.PROOFS_KEY`，元素 `{proof_no, text, created_at}`）。不给 `proofs`
而只给 `proof_text` 的调用与今天完全一致（等价 `#p1`）。三条校验各有一条可读的拒绝理由
（`duplicate_proof_no` 重复的号 / `empty_proof_text` 空正文 / `bad_proof_no` 非法号），
且"一条坏 ⇒ 整笔不写"：清单先整份核完再交给秘书，挑掉坏的、写好的是"静默丢弃"的另一种形态。
证明号与清单形状的读写口径只此一处来源 `verifications`（`PROOFS_KEY` / `proof_list` /
`as_proof_no`）—— 自己再拆一份，就会造出"盘上是第 2 条、读出来是第 1 条"这种没有任何东西
会报的错。
第十件：外部证明的上下文定理必须"重锚 或 显式声明"（业主 2026-10-22：「转写是提示词侧
点一下就行……其它要严格」）`origin="external_lit"` 的命题在 `derived_from` 里点名的每一
条上下文定理，写库前都要在依赖图上找到下面两件里的一件：一条重锚边（kind=theorem 或相应
kind、status=closed、带 source_lit_id 或 source_stmt_id、page_range 非空、quote 逐字
非空，且指的是这个号），或者一条显式声明（status="external_unavailable"、
`status_reason` 以 `not_in_our_graph:` 开头并点名这个号）。两件都没有 ⇒ 整笔不写，拒信
逐条点出缺的是哪一件。三态：依赖图读不到 ⇒ 同样拒绝并说明"没查成"，绝不当成通过。
不新增状态词、不新增字段（`schema.py` 在禁改区）—— 这一档用的正是 `Dependency` 类
docstring 里 companion book [6, Thm. 6.5] 那个例子用的既有词表。
"""
from __future__ import annotations

from typing import Mapping

from ._support import S
from .. import evidencebits as _EB
from .. import verifications as _VR
from ..refusals import refuse as _refuse


def _normalize_proofs(raw: object, *, proof_text: str) -> tuple[list[dict], str, dict | None]:
    """校验并归一调用方交来的证明清单，返回 `(第 2 条以后的清单, #p1 的正文, 拒绝)`。

    三态（与这个模块其余几级预检同一条纪律：要求写进返回值里看得见的形状）：
    - 没给（`None` / 空数组）⇒ `([], proof_text, None)`，与今天逐字一致；
    - 不合规 ⇒ `([], "", 拒绝)`：整笔不写，理由指到第几项、错在哪；
    - 合规 ⇒ `(清单, canonical 正文, None)`；清单里只有 `#p2` 及以后（`#p1` 是行上那一格）。

    ## 为什么"一条坏"等于"整笔不写"
    `proofs` 是"这条定理的证明有哪几份"的声明。挑掉坏的那一条、把好的写进去，会在盘上留下
    一条"看起来交了三份、其实只有两份"的记录，而没有任何读数会说少了哪一份。业主口径是
    "不许静默丢弃某一条"，所以整份先核完再交给秘书。

    ## `#p1` 只有一个权威
    `#p1` 的正文就是行上的 `proof_text`（老写者只会写那一格）。清单里给了 `#p1`、同时
    `proof_text` 也非空而两者不同 ⇒ 拒绝（`proof_text_conflict`）：同一格两个权威，写谁
    都等于静默丢掉另一个。两者相同则照收（那是等价的两种写法）。

    ## `created_at` 在这里发
    每一份证明落行时带自己的 `created_at`：清单是追加式的，"第 2 份是什么时候来的"必须
    读得出来 —— 只留正文的话，两份证明的时间先后只能靠猜。
    """
    if raw is None or raw == []:
        return [], str(proof_text or ""), None
    if not isinstance(raw, (list, tuple)):
        return [], "", _refuse(
            "bad_proofs",
            "proofs 必须是 JSON 数组（元素形如 {\"proof_no\": 2, \"text\": \"...\"}），"
            f"收到 {type(raw).__name__} —— 一份证明一条，整份一起交")
    canon = str(proof_text or "")
    seen: dict[int, int] = {}
    entries: list[dict] = []
    for i, item in enumerate(raw):
        where = f"proofs[{i}]"
        if not isinstance(item, Mapping):
            return [], "", _refuse(
                "bad_proofs",
                f"{where} 必须是对象（形如 {{\"proof_no\": 2, \"text\": \"...\"}}），"
                f"收到 {type(item).__name__}：{item!r}")
        raw_no = item.get("proof_no", item.get("no"))
        no = _VR.as_proof_no(raw_no)
        if no < 1:
            return [], "", _refuse(
                "bad_proof_no",
                f"{where}.proof_no 必须是 >= 1 的整数（1 = canonical，缺省也是它），"
                f"收到 {raw_no!r} —— 认不出的号与小于 1 的号都不写：清单里一条都不能静默丢")
        if no in seen:
            return [], "", _refuse(
                "duplicate_proof_no",
                f"证明号 #{no} 在这一笔里出现了两次（proofs[{seen[no]}] 与 {where}）—— "
                "同一条定理的两份证明不许共用一个号（共号之后签名分不清签的是哪一份），"
                "整笔不写")
        text = item.get("text")
        if text is None:
            text = item.get("proof_text")
        text = str(text or "")
        if not text.strip():
            return [], "", _refuse(
                "empty_proof_text",
                f"{where}（#{no}）的 text 是空的 —— 空正文不是「还没写」，"
                "而是「这一条其实没交」；要么补上正文，要么把它从清单里去掉")
        if no == 1 and canon.strip() and canon.strip() != text.strip():
            return [], "", _refuse(
                "proof_text_conflict",
                "清单里 #p1 的正文与 proof_text 不是同一份 —— #p1 是行上 proof_text 的"
                "唯一权威，同一格两个权威写谁都是静默丢掉另一个。二选一：只给 proof_text，"
                "或者只给 proofs 里的 #p1")
        seen[no] = i
        if no == 1:
            canon = text
        entries.append({"proof_no": no, "text": text, "created_at": S.now_iso()})
    return [e for e in entries if int(e["proof_no"]) > 1], str(canon or ""), None


def _normalize_range(raw: object, *, what: str) -> tuple[dict, str]:
    """把 `page_range` / `line_range` 归一化，返回 `(归一后的字典, 拒绝理由)`。
    ## 为什么必须有这一级（`draft/83` §7 的 D71，T1 第 18 趟真机读数）
    真机：主控派 `B.register_statement` 登记 Kuchment 那一条时，把页码写成了字符串（`{"start": "343", "end": "414"}`）。它在库里一路走
    到`S.PageRange.from_dict(...)`，而 `PageRange.__post_init__` 直接拿两个值比大小（`self.start < 1` / 
    `self.start > self.end`）⇒ `TypeError: '<' not supported between instances of 'str' and 'int'` 从动作里
    抛出去，台账上那一行落成 `failed`（"执行了、没成功"），而不是一条能读懂的拒绝—— 于是"参数类型写错了"与"代码崩了"又被混成一件事（这一条与本节其余七级预检是同一条纪律：要求写进模型
    看得见的形状，也在写入口拦下并命名）。
    - `int` / 纯数字串（`"343"`）⇒ 归一成 `int`；- `None` / 空串 ⇒ 保持"不知道"（篇幅与行号的"未知"是合法状态，由 `label` 表达）；- 其余（`"343-414"`
    / `"p.343"` / 浮点 / 列表 / 布尔）⇒ 拒绝并说明收件格式。布尔刻意不收：`True` 会被 `int()` 读成 1，悄悄造出一个页码。- 形状不是对象 ⇒ 拒绝（`dict("abc")`
    会抛，那是同一类崩溃）。
    范围本身的合法性（`>=1`、`start <= end`）在这里也先判一遍：留到 `schema` 里判就是"从事务里抛 `ValueError`"，调用方拿不到可读的 `kind`。
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
                        quote_verified: bool | None,
                        other_proofs: list[str] | None = None) -> tuple[dict, dict | None]:
        """按 `evidencebits` 现算五元位，返回 `(bits, 拒绝)`；拒绝非空 ⇒ 整笔不写。

        三态见模块 docstring 的"第八件"。这里只做两件事：「算」（`bits_of`）与
        「关形状」（`bits_shape_problems`）。判据本体一个字都不在这里写 ——
        两份口径一旦分家，"没做过"与"做过没通过"就会在某一处被压平，而门照样亮绿。

        为什么自产命题的 `proof` 要看 `origin`：`proof_text` 那一栏对 `external_lit`
        是"从原文摘下来的逐字摘录"，它本身不构成我方的证明过程。若不分来源就把它
        当成第 2 位，一条引文回验没过（`quote_verified=False`）的外部命题会被记成"有证明"，等级也从
        猜想抬到预备定理级 —— 而那正是这套位要堵的那类自报。

        `other_proofs` 是证明清单里第 2 份以后的正文（多证明模型）。第 2 位是行级的
        "这条命题有没有证明"，所以它看的是"任何一份有正文"，而 `proof_process` 仍然优先
        取 canonical 那一份（老字段的读数不变）；只有 canonical 空、别的份有正文时才拿
        第一份顶上 —— 否则一条"证明在 #p2 里"的命题会被记成"没有证明"。
        """
        own = str(origin) == "own_result"
        texts = [str(t or "") for t in ([proof_text] + list(other_proofs or []))]
        texts = [t for t in texts if t.strip()]
        try:
            bits = _EB.bits_of(
                origin=origin,
                source_lit_id=lit_id,
                quote_verified=quote_verified,
                proof=bool(texts) and own,
                proof_process=(texts[0] if own and texts else ""),
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

    def _attach_proofs(self, stmt_id: str, entries: list[dict],
                       canonical: str = "") -> dict:
        """把证明清单挂到既有那一行（同一把 `statements` 锁里读-改-写）。

        为什么不能交给秘书：秘书的白名单（`Secretary._statement_from`）只认 `Statement` 的
        字段，`proofs` 不在 schema 里（业主口径：不加 schema 字段），所以它到不了盘上。
        这一格因此是 B 的写侧里唯一一处"直接改那一行"的地方，改动面严格限定为：
        往行 JSON 的 `proofs` 键追加条目，其余键原样保留。

        三态：`written=True` 表示清单真的多了一条以上；`already` 是"号在册、正文逐字相同"
        （重复交同一份证明不算失败，也不改写既有的 `created_at`）；`refused` 是"号在册、
        正文不同"—— 整笔不写（不许静默覆盖既有的一条证明：那是把一份已经存在的证明换掉，
        而签名可能仍然挂在其上）。

        `canonical` 是这一笔带来的 #p1 正文（`proof_text`）。行已经在册时它若与盘上那一份
        不同，同样整笔不写并把 `canonical_differs` 置真：那等于要把 canonical 那一份换掉，
        而 V 的签名正挂在它上面 —— 静默忽略（看起来"交上去了"）比拒绝更坏。
        """
        out: dict = {"written": False, "attached": [], "already": [],
                     "refused": "", "reason": "", "canonical_differs": False}
        if not entries and not str(canonical or "").strip():
            return out
        store = getattr(self, "store", None)
        if store is None:
            out["reason"] = ("这一趟没有 store ⇒ 证明清单挂不上去（第 1 份已由秘书落行，"
                             "第 2 份起无处可写）")
            return out
        with store.tx("statements", actor=str(getattr(self, "actor", "agent-B") or "agent-B"),
                      note=f"agent_b.register_statement:proofs:{stmt_id}") as tx:
            found = tx.find("statements", stmt_id=stmt_id)
            if found is None:
                out["reason"] = (f"`statements` 里没有 {stmt_id} ⇒ 证明清单无处可挂"
                                 "（行没落成，清单也就没有落点）")
                return out
            row = dict(found)
            want = str(canonical or "").strip()
            have_canon = str(row.get("proof_text") or "").strip()
            if want and have_canon and want != have_canon:
                out["canonical_differs"] = True
                out["refused"] = "proof_text_taken"
                out["reason"] = (
                    "这一条命题已在册，而这一笔交来的 #p1（proof_text）与盘上那一份正文"
                    "不同 ⇒ 整笔不写：canonical 只有一份，覆盖它等于把 V 挂在上面的签名"
                    "一起作废（而这里没有任何东西核过那一签）。要换 canonical 那一份："
                    "另起一个证明号，或者先由人处置旧的那一份与它的签名")
                return out
            have = {no: text for no, text in _VR.proof_list(row)}
            listed = [dict(p) if isinstance(p, Mapping) else p
                      for p in (row.get(_VR.PROOFS_KEY) or [])]
            for entry in entries:
                no = int(entry["proof_no"])
                text = str(entry["text"])
                if no in have:
                    if str(have[no]).strip() == text.strip():
                        out["already"].append(no)
                        continue
                    out["refused"] = "proof_no_taken"
                    out["reason"] = (
                        f"#{no} 已经在这条命题的证明清单里，而这一笔交来的正文与它不同 ⇒ "
                        "整笔不写（覆盖既有的一条证明等于把它换掉，而签名可能还挂在它上面）。"
                        "确实要换这一份：另起一个证明号，或者先由人把旧的那一条与它的签名"
                        "一并处置")
                    return out
                listed.append({"proof_no": no, "text": text,
                               "created_at": str(entry.get("created_at") or S.now_iso())})
                out["attached"].append(no)
            if not out["attached"]:
                return out
            row[_VR.PROOFS_KEY] = listed
            tx.upsert("statements", row,
                      note=f"agent_b.register_statement:proofs:{stmt_id}")
            out["written"] = True
        return out

    @staticmethod
    def _proofs_reading(attach: Mapping) -> dict:
        """把 `_attach_proofs` 的读数翻成返回值里那几格（谁挂上了、谁本来就在册）。"""
        return {
            "proofs": [{"proof_no": int(n)} for n in (attach.get("attached") or [])],
            "proofs_already": [int(n) for n in (attach.get("already") or [])],
            "proofs_refused": str(attach.get("refused") or ""),
        }

    def register_statement(
        self,
        *,
        statement_full: str,
        source_lit_id: str = "",
        proof_text: str = "",
        #: 多证明（业主 2026-10-22）：`[{proof_no, text}, ...]`。#p1 落 `proof_text`，
        #: #p2 及以后落同一行的 `proofs` 清单；不给就与今天逐字一致（等价 #p1）。
        proofs: list | None = None,
        kind: str = "theorem",
        label: str = "",
        statement_text: str = "",
        origin: str = "external_lit",
        page_range: dict | None = None,
        evidence_kind: str = "cross_check",
        quote_verified: bool | None = None,
        quote_reason: str = "",
        #: 这条引文是「怎么」回验通过的（`schema.QUOTE_MODES`：`verbatim` 逐字命中 /
        #: `semantic` 语义相同 —— 业主 2026-10-14：「回验……保持语义相同即可」）。
        #: 不给就按历史行读（`True` ⇒ 逐字那一档），但「新写方应当说清方式」。
        quote_mode: str = "",
        #: 语义那一档的「证据」（业主 2026-10-14：「语义那一档必须留证据」）：
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
        # ---- 概念行的两处口径（2026-10-21，本批缺陷一的写入侧） --------------------
        #
        # 真机读数（`projects/mp3/data/statements.json`）：1143 条概念行、「1142 条带
        # `source_lit_id`」（术语确实出自文献），而 `origin` 一律 `own_result` ——
        # 文献里来的术语被记成了"我们自己的结果"；同时每一条都带着
        # `proof_text="concept:primitive"`，把"有没有证明"的读数全顶高。
        #
        # 两件事各有一个出口，都不许静默：
        # ② `origin`：概念行走「受控集合」，`own_result` 在这条动作上直接拒 ——
        #    这条动作没有"声明自己造"的参数（`specs/b.py` 的声明面是冻结的），
        #    所以"确实是自己定义的新概念"走秘书载荷的 `self_authored` 那一档，
        #    而不是在这里把文献术语标成自己的结果；
        # ① `proof_text`：概念行不许带它 ⇒ 不写，但把"丢了什么"写进返回值（留痕）。
        proof_text_dropped = ""
        proofs_dropped: list = []
        if str(kind or "").strip() == "concept":
            if origin == "own_result":
                return _refuse(
                    "concept_origin_refused",
                    "概念行的 origin 不许是 own_result：文献里来的术语是 "
                    "`external_lit`（给 `source_lit_id` + `page_range`）—— "
                    "真机 mp3 有 1142 条带文献出处的术语被错标成了 own_result，"
                    "于是报告把它们读成“我们自己的结果”。确实是我们自己定义的新概念"
                    "走秘书载荷的 `self_authored` 那一档（那是显式声明，不是默认值）")
            if str(proof_text or "").strip():
                proof_text_dropped = str(proof_text)[:120]
                proof_text = ""
            if proofs:
                # 与 `proof_text` 同一条口径：概念不参与等级链，也没有"证明"这一档。
                # 丢掉但不静默 —— 交来的清单原文进返回值（调用方要能看出自己交错了）。
                proofs_dropped = [dict(p) if isinstance(p, Mapping) else p
                                  for p in (proofs or [])]
                proofs = None
        # 第九件（多证明）：清单先整份核完，再把 #p1 的正文接进 `proof_text`。
        # 位置在这里而不是更靠后：`needs_proof` / 第 2 位 / 秘书载荷都读 `proof_text`，
        # 三处必须是同一份正文（"#p1 在清单里"与"#p1 在 proof_text 里"不许有两种读数）。
        proofs_listed, proof_text, proofs_bad = _normalize_proofs(proofs, proof_text=proof_text)
        if proofs_bad is not None:
            return proofs_bad
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
        # ---- 2026-10-16（亲测 B 时加的）：「把缺的出处字段一次说齐」 --------------
        # 这一格原本是"一次只点名一条"（实测要走 bad_origin → missing_quote_reason →
        # missing_page_range 「三轮」才凑齐）。业主口径："真实智能体也会在这里困惑并
        # 浪费 token" ⇒ 保留每条的 kind 与原文案不动，只在拒信里补一行「整份清单」。
        _page_now = dict(page_norm)
        _missing: list[str] = []
        if str(origin) == "external_lit" and not str(source_lit_id or "").strip():
            _missing.append("source_lit_id")
        if quote_verified is not True and not str(quote_reason or "").strip():
            _missing.append("quote_reason")
        if str(origin) == "external_lit" and not (
                _page_now.get("start") or str(_page_now.get("label") or "").strip()):
            _missing.append("page_range")
        if str(origin) == "own_result" and not (
                str(doc_id or "").strip()
                or dict(line_norm).get("start")
                or str(dict(line_norm).get("label") or "").strip()):
            _missing.append("doc_id/line_range")
        _all_missing = (" **这一笔还缺**：" + "、".join(_missing)
                        + " —— 一次给齐就不用再来回问。") if _missing else ""
        lit_id = str(source_lit_id or "").strip()
        if origin == "external_lit" and not lit_id:
            return _refuse("missing_source",
                           "origin='external_lit' 时必须给 source_lit_id —— "
                           "从文献摘的命题必须有出处（没有出处的摘录就是二手结论）" + _all_missing)
        if quote_verified is not True and not str(quote_reason or "").strip():
            # 这一条不按 origin 放宽（本轮试过：被 `test_action_surface_matches_acceptance`
            # 那条"每一级缺失都被拒"的梯子当场判红）：三态纪律管的是"盘上那一格不许留白"，
            # `own_result` 也一样有"我为什么还没核"可以说（没核 / 没有第二份文本可比 /
            # 证明在 proof_text 里……）。业主 §14.11 的两件式契约管的是内容
            # （定理内容 + 证明过程），不是把三态纪律免掉。
            return _refuse("missing_quote_reason",
                           "quote_verified 不是 True 时必须给 quote_reason —— "
                           "三态纪律：没通过要说为什么没通过，**还没查**也要说出来（不许留白）" + _all_missing)
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
                               "审稿判据会判这一行缺出处页码" + _all_missing)
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
                               "审稿判据会判这一行缺出处页码" + _all_missing)
        elif str(origin) == "own_result":
            line = dict(line_norm)
            if not (str(doc_id or "").strip()
                    or line.get("start") or str(line.get("label") or "").strip()):
                return _refuse("missing_own_source",
                               "origin='own_result' 时必须给我们自己的出处："
                               "`doc_id`（我方稿件那一行的 id）或 `line_range`"
                               "（start / label 至少一个）—— 自有结果的出处不是"
                               "「文献第几页」，那一栏要它等于让它编一个数字" + _all_missing)
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
        # 定义（当前宽度六位；旧四位读侧兼容），这里在写库前用同一个谓词核，拒绝时带上 `kind` ——
        # "写成 doc:0000" 于是是一条可读的拒绝，而不是事务里抛出的 `ValueError`。
        for _what, _value in (("source_lit_id", lit_id),
                              ("doc_id", str(doc_id or "").strip())):
            if _value and not S.is_valid_id(_value):
                return _refuse("bad_id",
                               f"{_what} 必须是 {S.ID_DIGITS} 位十进制字符串（如 \"{S.format_id(0)}\"；"
                               f"旧数据里的 4 位号仍可读），"
                               f"收到 {_value!r} —— 形态由 schema.require_id 定义，"
                               "本动作在写库前用同一个谓词核，整笔不写")

        # ---- 严格规矩 B（业主 2026-10-22）：外部命题的上下文定理必须重锚或显式声明。
        # 判据在 `_context_theorem_gaps`（读面只有 dependencies / statements 两张表）；
        # 这里只做一件事：两件都没有 ⇒ 整笔不写，并把"缺的是哪一件"说清。
        # 只对 `origin="external_lit"` 生效：自产命题的上下文走 `derived_from` 的承重链，
        # 那一侧的口径在 `closing` 的收工门；这条规矩问的是"抄来的东西靠什么站着"。
        # `derived_from` 空 ⇒ 这一笔没点名任何上下文定理，这里没有可判的东西（不静默：
        # 一条都不点名的命题在读数上就是"没有声明过上下文"，而它不是这条判据的输入）。
        _refs = S.sorted_unique(list(derived_from or []))
        if str(origin) == "external_lit" and _refs:
            _gaps, _why_not = self._context_theorem_gaps(_refs)
            if _why_not:
                return _refuse("context_graph_unreadable", _why_not)
            if _gaps:
                _detail = "；".join(
                    f"{g['ref']}（{'在命题台账里' if g['in_ledger'] else '连命题台账里都没有这一条'}）"
                    for g in _gaps)
                return _refuse(
                    "context_theorem_not_anchored",
                    "这一笔点名了上下文定理（`derived_from`），而依赖图上它们既没有重锚边、"
                    f"也没有显式声明 ⇒ 整笔不写。缺的是这两件里的一件：{_detail}。"
                    "① 重锚边：用 `doc.register_dependency` 登记一条 kind=theorem（或相应 "
                    "kind）、status=closed、带 source_lit_id 或 source_stmt_id、page_range "
                    "非空、quote 逐字非空的边，并在 label（或 status_reason）里点这个号；"
                    "② 或者显式声明它不在我们的依赖图内：登记一条 "
                    "status=\"external_unavailable\"、`status_reason` 以 "
                    "`not_in_our_graph:` 开头并点名这个号的边。"
                    "两条都不给，'没处理'就会被下游读成'处理过了'"
                    "（既有词表没有第二个能表达这件事的档，而新增状态词要改 schema.py，"
                    "那是禁改区）")

        # ---- 业主 2026-10-09：「B 不直接用增工具，秘书实际操作增、改、查工具，
        # B 纯粹负责消化理解」⇒ 上面那些是内容的判据（B 的判断），写盘这一段交给秘书。
        bits, bits_bad = self._statement_bits(
            origin=str(origin), lit_id=lit_id, proof_text=str(proof_text or ""),
            quote_verified=quote_verified,
            other_proofs=[str(e.get("text") or "") for e in proofs_listed])
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
        if written.get("upgraded") and not written.get("created"):
            # 同一份内容再交一次、这一回带了 `proof_review` 的凭据 ⇒ 秘书「改那一行」
            # （不新建）。这是 `evidence_kind` 从弱档走到 `proof_review` 的唯一一条正路：
            # 通用写口 `table.update("statements")` 已被 `store.direct_write_refusal` 拒
            # （它能同时改 bits / proof_text / quote_verified，而没有任何东西核过那些字段）。
            # 对调用方来说这是"成功了"（那一行的档位变了），不是重复读数。
            stmt_now = str(written.get("stmt_id") or "")
            attach = self._attach_proofs(stmt_now, proofs_listed,
                                         canonical=str(proof_text or ""))
            out = {"ok": True, "stmt_id": stmt_now,
                   "source_lit_id": lit_id or None,
                   "quote_verified": quote_verified, "origin": origin,
                   "quote_mode": str(quote_mode or ""),
                   "evidence_kind": evidence_kind, "upgraded": True,
                   "row": dict(written.get("row") or {}),
                   "changes": list(written.get("changes") or []),
                   "note": ("这一条**没有新建行**：同一条 statement_full 已在册，而这一笔"
                            "带来的证据档更强（且有凭据）⇒ 秘书把那一条的档位改上去了"
                            f"（{written.get('reason') or ''}）。"
                            "内容面一个字没动；要改内容请另起一条（force_new）并写清为什么。")}
            if proofs_listed:
                out.update(self._proofs_reading(attach))
            if proofs_dropped:
                out["proofs_dropped"] = proofs_dropped
            if attach.get("refused"):
                # 升档已经发生（秘书那一笔改完了），所以这里不回滚、也不改 ok；
                # 但"清单没挂上"必须说出来 —— 静默忽略等于让调用方以为交上去了。
                out["note"] += ("这一笔带来的证明清单没有写进库："
                                + str(attach.get("reason") or "")
                                + "（档位那一笔已经落盘，这一格不回滚）")
            return out
        if written.get("duplicate") and not written.get("created"):
            # 秘书查重的读数（业主 2026-10-09：「秘书实际操作增、改、查工具」）：
            # 同一条 `statement_full`（按 `textutil.normalize` 比）已在册 ⇒ 不新建行。
            #
            # 多证明模型下这条分支多了一个合法用途：这条定理已经在册，而这一笔带来的是
            # 它的一条新证明（#p2 及以后）⇒ 行不新建，证明挂到既有那一行上。
            stmt_dup = str(written.get("stmt_id") or "")
            attach = self._attach_proofs(stmt_dup, proofs_listed,
                                         canonical=str(proof_text or ""))
            if attach.get("refused"):
                return _refuse(str(attach["refused"]), str(attach.get("reason") or ""),
                               stmt_id=stmt_dup)
            if attach.get("written"):
                out = {"ok": True, "stmt_id": stmt_dup,
                       "source_lit_id": lit_id or None,
                       "quote_verified": quote_verified, "origin": origin,
                       "quote_mode": str(quote_mode or ""),
                       "evidence_kind": evidence_kind, "new_row": False,
                       "note": ("这一条**没有新建行**（同一条命题已在册），但这一笔带来的"
                                "证明挂上去了：清单是追加式的，#p1 仍是那一行原来的 "
                                "`proof_text`。")}
                out.update(self._proofs_reading(attach))
                return out
            if proofs_listed and not attach.get("already"):
                return _refuse("proofs_not_attached",
                               str(attach.get("reason") or "证明清单没挂上"),
                               stmt_id=stmt_dup)
            # 对调用方来说这是"这一次没有新行"，必须说出来（`ok=False` + `kind`），
            # 并把既有那一条的号给它 —— 否则它只会看到"没写成"而不知道东西在哪。
            return _refuse("duplicate_statement",
                           "同一条命题（按规范化后的 statement_full 比）已在册 ⇒ "
                           "秘书查重后没有新建行；要引用它请用返回的 stmt_id，"
                           "确实要另起一条才走 `force_new`（本动作不暴露它）"
                           + ("；这一笔带来的证明清单里每一条都已经在册且逐字相同"
                              "（没有重复登记，也没有覆盖任何一份证明）"
                              if attach.get("already") else ""),
                           stmt_id=stmt_dup)
        if not written.get("checked") or not written.get("created"):
            extra = {k: v for k, v in written.items()
                     if k in ("literature_rows", "available_lit_ids", "unresolved")}
            return _refuse(str(written.get("refused") or "write_failed"),
                           str(written.get("reason") or "秘书没写这一笔"),
                           stmt_id=str(written.get("stmt_id") or ""), **extra)
        stmt_id = str(written["stmt_id"])
        data = dict(written.get("row") or {})
        attach = self._attach_proofs(stmt_id, proofs_listed,
                                     canonical=str(proof_text or ""))
        if proofs_listed and not attach.get("written"):
            # 行已经由秘书落好了（#p1 在盘上），而清单没挂上 —— 不许当成功返回：
            # 调用方会以为"这条定理的第二份证明交上去了"。如实报，并给出 stmt_id。
            return _refuse("proofs_not_attached",
                           ("命题那一行已经落好了（stmt_id 见下），而证明清单没挂上："
                            + str(attach.get("reason") or "原因不明")
                            + " ⇒ 第 2 份及以后的证明没有写进库（不是写了一半，是那几条没写）"),
                           stmt_id=stmt_id)
        if attach.get("written"):
            data = next((dict(r) for r in self.store.rows("statements")
                         if str(r.get("stmt_id") or "") == stmt_id), data)
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
                #: 概念行带进来的 `proof_text` 被丢掉了（本批缺陷一的写入侧）：
                #: 空串 = 没丢过。「留痕」是必须的 —— 静默丢会让调用方以为
                #: "概念也能带证明"，下一次还这么交。
                "proof_text_dropped": proof_text_dropped,
                #: 概念行带进来的证明清单（同上：丢掉但留痕）。
                "proofs_dropped": proofs_dropped,
                #: 这一笔挂到行上的多证明（#p2 及以后）：空列表 = 没交清单。
                #: 只在真交了清单时才出现这一个键 —— 老写法（只给 proof_text）
                #: 的返回值因此与今天逐字相同。
                **({"proofs": [{"proof_no": int(e["proof_no"])} for e in proofs_listed]}
                   if proofs_listed else {}),
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
                            if needs_proof else "")
                         + (f"概念行**不带** proof_text：交来的 {proof_text_dropped!r} "
                            "没有写进库（概念不参与等级链，要补的是定义，不是证明）。"
                            if proof_text_dropped else "")
                         + ("这一笔还给这条定理挂了多证明（"
                            + "、".join(f"#{int(e['proof_no'])}"
                                       for e in proofs_listed)
                            + "）：#p1 是行上的 `proof_text`，其余进行的 "
                            f"`{_VR.PROOFS_KEY}` 清单（追加式，各带 `created_at`）。"
                            "每一份的第 3 位（审过）各自独立，由 V 逐份签 —— "
                            "登记不等于审过。"
                            if proofs_listed else ""))}

    # ---------------------------------------------------------------- 规矩 B
    #
    # 严格规矩 B（业主 2026-10-22：「转写是提示词侧点一下就行……其它要严格」）：
    # 外部证明的上下文定理必须"重锚 或 显式声明"。判据在下面三格，调用点在
    # `register_statement` 的第六级之后（写库前的最后一道预检）。
    #
    # 为什么"上下文定理"读的是 `derived_from`：那一格的 schema 语义逐字就是
    # "这条命题用到了哪些别的命题（本表内的 stmt_id）"，而且它已经在 B 的动作参数面上
    # （`specs/b.py` 是禁改区，加不了新参数）。命题正文里扫出来的引用不在这里判：
    # 那一半由秘书的 `_scan_proof_deps` 自己落成依赖边（`label` 就是那一条引用），
    # 而 B 手里没有任何一格能按"每一条引用"给出页码与逐字引文 —— 硬按它判会把所有
    # 带引用的历史命题都判红，却指不出一条能补的路。
    #: 上下文定理的"重锚边"认哪几种 kind。数据集 / 实验 / 先前工作不算上下文定理：
    #: 它们的依据面是另一回事，混进来会让这条判据退化成"任何一条依赖都算"。
    _CONTEXT_EDGE_KINDS = ("theorem", "lemma", "proposition", "definition")

    #: "这个引用不在我们的依赖图内"的受控理由码前缀。用既有词表表达：
    #: `Dependency.status="external_unavailable"` + 自由文本 `status_reason` 以它开头
    #: （`Dependency` 的类 docstring 里 companion book [6, Thm. 6.5] 那个例子用的就是
    #: 这一档）。刻意不新增状态词、不新增字段 —— `schema.py` 在禁改区。
    _NOT_IN_GRAPH_PREFIX = "not_in_our_graph:"

    @staticmethod
    def _names_token(text: str, key: str) -> bool:
        """`text` 里有没有一个"整号"形态的 `key`（左右两侧都不是数字）。

        为什么不直接 `key in text`：`0004` 是 `000042` 的子串。用子串判会把一条
        属别人的声明算成这一条的，而那种错在读数上完全看不见（声明还在，只是指的
        不是它）。
        """
        if not text or not key:
            return False
        start = 0
        while True:
            at = text.find(key, start)
            if at < 0:
                return False
            before = text[at - 1] if at > 0 else ""
            after_at = at + len(key)
            after = text[after_at] if after_at < len(text) else ""
            if not before.isdigit() and not after.isdigit():
                return True
            start = at + 1

    def _context_ref_handled(self, ref: str, deps: list) -> bool:
        """这一个上下文定理号有没有"重锚边"或"显式声明"（两件里的一件即算处理过）。"""
        for row in deps:
            status = str(row.get("status") or "")
            reason = str(row.get("status_reason") or "")
            label = str(row.get("label") or "")
            if status == "external_unavailable":
                if (reason.startswith(self._NOT_IN_GRAPH_PREFIX)
                        and (self._names_token(reason, ref)
                             or self._names_token(label, ref))):
                    return True
                continue
            if status != "closed":
                continue
            if str(row.get("kind") or "") not in self._CONTEXT_EDGE_KINDS:
                continue
            if not (str(row.get("source_lit_id") or "")
                    or str(row.get("source_stmt_id") or "")):
                continue
            page = row.get("page_range")
            if isinstance(page, Mapping):
                has_page = (bool(page.get("start"))
                            or bool(str(page.get("label") or "").strip()))
            else:
                has_page = bool(str(page or "").strip())
            if not has_page or not str(row.get("quote") or "").strip():
                continue
            if str(row.get("source_stmt_id") or "") == ref:
                return True
            if self._names_token(label, ref) or self._names_token(reason, ref):
                return True
        return False

    def _context_theorem_gaps(self, refs: list) -> tuple[list, str]:
        """规矩 B 的读侧判定：逐条判"重锚"还是"显式声明"，返回 `(缺的清单, 没查成的理由)`。

        ## 判什么（业主 2026-10-22）
        `origin="external_lit"` 的命题在 `derived_from` 里点名它用到的上下文定理。
        对每一个号，依赖图上必须有下面两件里的一件：
          1. 重锚边：`dependencies` 里一条 `kind` 属于 `_CONTEXT_EDGE_KINDS`、
             `status="closed"`、带 `source_lit_id` 或 `source_stmt_id`、`page_range`
             非空、`quote` 非空的边，且那条边指的就是这个号（`source_stmt_id` 等于它，
             或者 label / status_reason 里点了它的名）。这就是"这条上下文定理落在哪
             一页、原文哪一句" —— 只写"依赖 stmt:000007"不算重锚。
          2. 显式声明：一条 `status="external_unavailable"` 且 `status_reason` 以
             `not_in_our_graph:` 开头、并点名那个号的边 —— "这条引用不在我们的依赖图内"。
        两件都没有 ⇒ 那个号进"缺的"列表，调用方据此拒绝落库。

        `used_by` 不参与判定：这条边要在这个命题落库之前写好，而它的号那时还没分配
        （`stmt:<号>` 还不存在）。所以判据读的是 source 那一端（`source_stmt_id` /
        `source_lit_id`）与页码、引文，以及 label / status_reason 里点没点这个号。

        ## 三态（未处理绝不静默等于处理过了）
        返回 `([], "")` = 查了、每一条都处理过了；`(缺的清单, "")` = 查了、有点名的号
        两件都没有；`([], 理由)` = 没查成（表读不出来 / 这一趟没有 store），它不等于通过。

        ## 有界：读面只有本工作区的两张表
        `store.rows("dependencies")` 与 `store.rows("statements")`。不新开模块、不跨
        工作区、不读事件流 —— 这条判据要能在任何一次登记里跑完。
        """
        store = getattr(self, "store", None)
        if store is None:
            return [], ("没查成：这一趟没有 store，读不到本工作区的 dependencies / "
                        "statements ⇒ 判不了上下文定理有没有重锚或声明（不许当成通过）")
        try:
            deps = [dict(r) for r in store.rows("dependencies")]
            known = {str(r.get("stmt_id") or "") for r in store.rows("statements")}
        except Exception as exc:  # noqa: BLE001 —— 读不到要如实说，不许当成通过
            return [], (f"没查成：dependencies / statements 读不出来"
                        f"（{type(exc).__name__}: {exc}）⇒ 拒绝落库。三态纪律：'读不到'"
                        "不是'都处理过了'，也不是'一个引用都没有'")
        missing: list = []
        for ref in refs:
            key = str(ref or "").strip()
            if not key:
                continue
            if self._context_ref_handled(key, deps):
                continue
            missing.append({"ref": key, "in_ledger": key in known})
        return missing, ""
