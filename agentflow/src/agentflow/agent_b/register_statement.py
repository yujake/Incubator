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
第十一件：B-2 与 B-3 两条拒收码的分工（业主 2026-10-22 两个裁定，同一批落地）
两条都管"自产的东西能不能一进门就叫定理"，但它们问的不是同一个问题，所以码是两条：

- `must_start_as_conjecture`（B-2）：「没有引文 / 自己编的命题必须从『猜想』注册」。
  判据：`origin="own_result"` + 没有 `source_lit_id` + `quote_verified` 不是 True
  + `kind` 不是 conjecture/concept ⇒ 整笔不写。它管的是入口：这一笔还没有任何
  外部出处，凭什么第一步就声明成 theorem / lemma / proposition。
- `self_authored_needs_v`（B-3）：「B 侧自己杜撰定理和证明时，也必须给 V 看才能落，
  否则就按瞎编处理」。判据见 `_self_authored_gate`：自产（或没有出处）的定理级
  命题，在 V 的台账里必须有一份盖住这一份正文的「成立」签。它管的是升级：
  这一笔已经交了证明，而"这份证明有人看过"是它与"瞎编"之间唯一的分界。

两条同时成立时优先报 `must_start_as_conjecture`：裁定 B-2 的入口判据比 B-3 的升级
判据更靠前（还没立成猜想的东西，谈不上升级）。V 已经签住的那一笔给 B-2 让路 ——
那一签本身就是"它先立过猜想、走过复核"的证据（`_self_authored_gate` 的 `signed`）。
第十二件：穷举证明的签字是 V 的、②③ 是 E 写的，B 不许自签（业主 2026-10-23 裁定与晚间的更正）
裁定逐字要点：「如果纯数值实验直接把整个命题证掉了，那也能拿 proof 标识，理由是穷举，
签名是对应的程序脚本……这些有关数值实验的都由 E 来签。若要入定理证明库，证明栏写
程序地址（相对于仓库）。」落点是两道闸，判据本体都在 `numericproof`：

- 入参闸（`proof_needs_third_party_signature`）：`origin="own_result"` +
  `evidence_kind="proof"` ⇒ 证明栏要么是程序脚本的相对路径、且台账里有一条 E 按穷举
  签下的 proof（`observations.e_signature` 里 `signed_by="E"` +
  `proof_reason="exhaustion"`），要么有一条 `method="formal"` 的 proof 实验。两样都没有
  ⇒ 整笔不写。改前 B 可以直接把自己的结果标成 proof，而没有任何一格会问"谁签的"。
- 上面那两道 V 闸的例外：证明栏是程序、且 E 已按穷举签过 ⇒ 这一条不需要 V 的签
  （V 对数值证据直接拒签）。不改这一处的后果是一条真的穷举证明永远进不了定理证明库：
  它既过不了 B-3，也拿不到 V 那一签。
"""
from __future__ import annotations

from typing import Mapping, Sequence

from ._support import S
from .. import depsection as _DS
from .. import evidencebits as _EB
from .. import numericproof as _NP
from .. import quoteevidence as QE
from .. import refusals as _R
from .. import verifications as _VR
from ..refusals import refuse as _refuse

#: 一条命题一开始允许声明成的那几个 kind（业主 2026-10-22 裁定 B-2）。
#:
#: 裁定原文：「没有引文 / 自己编的命题必须从『猜想』注册」。于是
#: `origin="own_result"` + 没有 `source_lit_id` + `quote_verified` 不是 True 的那一笔，
#: 只允许以 `conjecture`（猜想）或 `concept`（概念行不参与等级链）登记；写成
#: theorem / lemma / proposition 一律受控拒绝 `must_start_as_conjecture`。
#:
#: 为什么是一张白名单而不是"拒掉 theorem/lemma/proposition"：等级链的词表会变
#: （`schema.KINDS` 加一个取值就是加一种"强于猜想"的说法），黑名单会在那种时候
#: 静默放行 —— 白名单不会。
CONJECTURE_START_KINDS: tuple[str, ...] = ("conjecture", "concept")


def _same_manuscript_text(left: Any, right: Any) -> bool:
    """两份手稿正文是不是同一版（只把换行归一，别的一字不改）。

    为什么要有它：`read_carried_manuscript` 读的是字节解码（保留 `\\r\\n`），
    而调用方多半用 `Path.read_text` 读（通用换行已折成 `\\n`）—— 直接比字符串会
    在 Windows 上永远不相等，而那种不相等恰好把"D 递的就是携带单上那一份"误判成
    "别的调用方直递的"（读数从 `carried_by_D` 退成 `param`，没有任何东西会报）。
    """
    def _n(value: Any) -> str:
        return str(value or "").replace("\r\n", "\n").strip()

    return _n(left) == _n(right)

#: B-2 的拒收码（写侧与读侧共用这一个字面量，免得两处措辞分家）。
#:
#: 与 `_self_authored_gate` 的 `self_authored_needs_v` 分工逐字见模块 docstring
#: 的"第十一件"：前者管入口（还不许叫定理），后者管升级（交了证明但没人看过）。
MUST_START_AS_CONJECTURE = "must_start_as_conjecture"


def _must_start_as_conjecture_refusal(*, kind_now: str, origin: str) -> dict:
    """B-2 的那一条拒收（两处调用点共用一份文案：`_self_authored_gate` 之前与之后）。

    为什么两处都要：B-3 的闸（自产定理级要先过 V）与 B-2 这一条覆盖同一类输入
    （自产、无出处、定理级、没有 V 的签）。裁定 B-2 管的是"它一开始可以叫什么"，
    比 B-3 的"能不能升成定理"更靠前 ⇒ 这一档的拒收码用 B-2 的那个；而 B-3 的
    `self_authored_needs_v` 仍然管它自己的射程（例如这一笔自称引文回验通过、
    而 B-2 的三件不成立时）。
    """
    return _refuse(
        MUST_START_AS_CONJECTURE,
        "这一笔是 origin='own_result'、没有 source_lit_id、quote_verified 也不是 true "
        "⇒ 没有引文 / 自己编的命题必须从「猜想」注册（业主 2026-10-22 裁定 B-2），"
        f"不能一进门就声明成 {kind_now!r}。两条正路（都不必改这一行的内容）："
        "① 把 kind 改成 \"conjecture\" 再交一次（升档不用你报：等级由 "
        "evidencebits.derive_grade 按五元位现算 —— 有证明过程且 V 签过就自己抬）；"
        "② 走猜想登记那条路：D 的 register_conjecture 动作（工具面 "
        "`conjecture.register_conjecture`）先把这条立成猜想，再拿证据回来。"
        "如果你本来就有外部出处：给 source_lit_id + page_range 并按 "
        "origin='external_lit' 重交。",
        statement_kind=kind_now, declared_origin=str(origin))


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
                _R.EMPTY_PROOF_TEXT,
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


def _text_truncation_reading(*, statement_full: str, proof_text: str,
                             proofs: list | None) -> dict:
    """这一笔的正文有没有超出"判档位那一趟"能读的上限 ⇒ 空字典 或 一份截断读数。

    ## 为什么截断读数落在写侧（业主 2026-10-24 裁定 B2 的第 2 条）
    真机读数（sylow4）：一条正文 8375 字，判档位那一趟的材料在 4000 字处被切断，
    而材料里一个字都没说"被切了" ⇒ 模型给出"证明截断，无法定档"，台账落成
    `nontriviality: null` + basis "材料不足"。这就是把"我们没给它看全"记成了"它给的材料不够"。
    现在判档位那一侧自己会报 `text_truncated`（`secretary.material_truncation`），
    写侧这一格回答另一个问题：这一笔交上来的正文，本身有没有超过判档位读的上限 ——
    超了的话，档位判不了是输入不完整，而修法是"把正文拆段 / 压到上限内再登记"，
    不是"再补点材料试试"。

    判据只有一条：正文（`proof_text` + `proofs` 里的每一份；都没有时退回
    `statement_full` 里那一段证明）超过 `secretary.PROOF_BODY_CAP` 字。
    没超 ⇒ 空字典（老返回值逐字不变）；超了 ⇒ 三格：`text_truncated` /
    `text_truncated_note` / `tier_material`。

    ## 为什么上限从 `secretary` 现读，而不是在这里再写一个 20000
    两个数一漂，就会出现"写侧说没超、判档位那侧已经截了"的读数分裂 ——
    而那种分裂没有任何一格会红。上限的真身只有一处（`secretary.PROOF_BODY_CAP`）。
    """
    from .. import secretary as _SEC

    pieces = [str(proof_text or "")]
    for item in (proofs or []):
        if isinstance(item, Mapping):
            pieces.append(str(item.get("text") or item.get("proof_text") or ""))
    joined = "\n\n".join(piece for piece in pieces if piece.strip())
    if not joined.strip():
        # 证明没交在这一栏：判档位那一趟读的是 statement_full 里的证明小节
        # （`secretary._looks_like_a_proof` 是同一处判据，这里只问"它会不会被读"）。
        whole = str(statement_full or "")
        joined = whole if _SEC._looks_like_a_proof(whole) else ""
    if not joined.strip():
        return {}
    chars = len(joined)
    cap = int(_SEC.PROOF_BODY_CAP)
    if chars <= cap:
        return {}
    return {
        "text_truncated": True,
        "text_truncated_note": (
            f"这一条正文在 {cap} 字处被截断（正文共 {chars} 字，判档位读的上限是 {cap} 字）"
            "—— 档位判不了是因为输入不完整，不是因为材料不足；"
            "修法是把正文拆成分节的多条命题，或先压到上限之内再登记"),
        "tier_material": {"chars": chars, "cap": cap, "over_by": chars - cap},
    }


def _canonical_history_entry(old_text: str, new_text: str) -> dict:
    """被覆盖的旧 canonical 正文留痕的那一条（`proof_history` 列表的元素）。

    形状逐字是 `{"text": 旧正文, "sha": 旧正文 sha256, "at": 覆盖时刻,
    "replaced_by": 新正文 sha256}`：`sha` 让这一条能被签名台账里的 `proof_sha256`
    直接对上（"签的是这一版"），`replaced_by` 让"被哪一版换掉的"不必去别处查。
    时间只做记录，不参与判据（时序判据在台账行序上）。
    """
    old = str(old_text)
    new = str(new_text)
    return {"text": old, "sha": _VR.proof_sha(old), "at": S.now_iso(),
            "replaced_by": _VR.proof_sha(new)}


#: 第 4 位（形式化通过）从 L 的台账同步进命题那一行（D28 的写侧）。
#:
#: 业主 2026-10-22 的裁定（逐字）：「一个定理有多种证明路径，lean 形式化需指明对哪个路径
#: 做了形式化验证，即五元判据有关形式化的那一位也要改成二维列表。但关于一个定理的正确性，
#: 但凡任意一个路径通过核验，它就是对的」。
#:
#: ## 为什么写者是 B 的这一条路
#: L 的写集只有 `experiments`（`specs/l.py::SPEC.write_set`）：它登记"我验了哪一份证明、
#: 检查器说了什么"，但它不许碰 `statements`。第 4 位住在 `statements.bits` 里，所以
#: 把"验过"翻译成"这一位是什么"必须由能写那一行的角色做 —— 与第 3 位同一条规矩
#: （V 签台账，位由同一笔写落），只是这一位的那一笔落在 B 的登记里。
#:
#: ## 它读什么、写什么
#: 读 `experiments`（`evidencebits.formal_ledger_reading` 是唯一派生点：只认绑到这条
#: 命题的 `method="formal"` 行），写出两格：
#:
#: - `bits.formal`：二维 `{证明号: 状态}`，把这条命题在册的每一条证明都列出来
#:   （没验过的写 `pending`）—— 整表写，与第 3 位的 `reviewed_by_proof` 同一个理由：
#:   缺一格要靠调用方记得"缺省是 pending"，而写出来是直接读出来的结论；
#: - `bits.evidence.formal_by_proof`：逐条凭据（checker / experiment_id / proof_sha256 /
#:   path_id / path_source），外加单格的 `bits.evidence.formal`（老读者只认它）。
#:
#: 号不在册的读数不落位（那条实验绑到了一条不存在的证明上）。台账里一条读数都没有时
#: 原样返回（不改已有那一位）：没验过不等于"把以前验过的擦掉"。
def _bits_with_formal(bits: Mapping | None, row: Mapping,
                      experiments: list[Mapping]) -> dict:
    """`(bits, 读数)` 里的第二格换成"把台账里的第 4 位同步进去"之后的那一份。"""
    out: dict = dict(bits or {})
    reading = _EB.formal_ledger_reading(row, experiments)
    registered = {no for no, _text in _VR.proof_list(row)}
    states: dict[str, str] = {}
    payloads: dict[str, dict] = {}
    for no, item in reading.items():
        if no not in registered:
            continue
        states[str(no)] = str(item.get("state") or "pending")
        payloads[str(no)] = dict(item.get("payload") or {})
    if not states:
        return {"changed": False, "bits": out, "paths": {},
                "note": ("L 的台账里没有绑到这条命题、且号在册的形式化读数 ⇒ "
                         "第 4 位一个字不动（没验过不是「把验过的擦掉」）")}
    # 整表写：在册的每一条证明都列出来，没读数的那几条是 `pending`。
    full = {str(no): "pending" for no in sorted(registered)}
    full.update(states)
    ev = dict(out.get("evidence") or {})
    ev[_EB.FORMAL_BY_PROOF_KEY] = payloads
    # 单格那一份（老形态）取第一条 verified，没有就取最小的号 —— 它只是"最近那一次"
    # 的读数，逐条判定一律读 `formal_by_proof`。
    order = sorted(payloads)
    pick = next((no for no in order if states.get(no) == "verified"), order[0] if order else "")
    if pick:
        ev["formal"] = dict(payloads[pick])
    out[_EB.FORMAL_BIT] = full
    out["evidence"] = ev
    merged = _EB.normalize_raw(out, origin=str(row.get("origin") or "own_result"),
                               kind=str(row.get("kind") or ""))
    changed = (dict(bits or {}).get(_EB.FORMAL_BIT) != merged.get(_EB.FORMAL_BIT)
               or dict((bits or {}).get("evidence") or {}).get(_EB.FORMAL_BY_PROOF_KEY)
               != merged.get("evidence", {}).get(_EB.FORMAL_BY_PROOF_KEY)
               or dict(bits or {}).get("grade") != merged.get("grade"))
    return {"changed": bool(changed), "bits": merged, "paths": dict(full), "note": ""}


def _bits_after_canonical_write(row: Mapping, fresh: Mapping | None) -> dict:
    """canonical 正文被覆盖之后那一行的 `bits`：只同步第 2 位与它的正文。

    不能整份换成 `fresh`：`fresh` 是这一笔登记时现算的（第 3 位按"没审过"留空），
    而盘上那一行可能已经带着 V 的签名凭据（`reviewed_by` / `reviewed_by_proof` /
    `reviewed_sha_by_proof`）。整份换掉等于把"签过旧稿"这件事一起抹掉，读侧就只剩
    "没签过"，"签的是旧稿"这一档读数（stale）反而看不见了。

    所以这里只动两格：第 2 位换成这一笔的读数，证据里的 `proof_process` 与
    `proof_source` 换成这一笔的正文来源；签名那几格原样保留，由读侧的
    `evidencebits._stale_review_cleared` 按"记下来的 sha 与现行正文不符"判过期。
    """
    old = dict(row.get("bits") or {})
    new = dict(fresh or {})
    if not old:
        return new
    if not new:
        return old
    out = dict(old)
    out["proof"] = bool(new.get("proof"))
    ev = dict(old.get("evidence") or {})
    fresh_ev = dict(new.get("evidence") or {})
    ev["proof_process"] = str(fresh_ev.get("proof_process") or "")
    ev["proof_source"] = str(fresh_ev.get("proof_source") or "")
    out["evidence"] = ev
    return _EB.normalize_raw(out, origin=str(row.get("origin") or "own_result"),
                             kind=str(row.get("kind") or ""))


class _RegisterStatement:
    def _statement_bits(self, *, origin: str, lit_id: str, proof_text: str,
                        quote_verified: bool | None,
                        other_proofs: list[str] | None = None,
                        kind: str = "") -> tuple[dict, dict | None]:
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

        ## `kind` 为什么必须传进来（写作侧与校验侧必须是同一个值）

        `evidencebits.derive_grade` 对 `kind="concept"` 有一条短路：概念不参与等级链，
        等级现算成 `not_applicable`（`draft/97` 的并表口径）。而落盘那一关由
        `schema.Statement.validate` 走 `evidencebits.bits_shape_problems(self.bits,
        kind=self.kind)` —— 它一定带着这一行的 `kind` 去重算等级，并把"存下的等级与
        现算的等级不一致"当成自报而拒收。

        所以这一格不传 `kind` 的后果不是"等级算得粗一点"，而是：概念行在这里算出
        `grade="conjecture"`，校验端按 `kind="concept"` 重算出 `not_applicable`，
        两者一比就判"bits.grade 写的是 'conjecture'，按五位现算是 'not_applicable'"
        ⇒ 任何 `kind=concept` 的登记 100% 被拒。真机读数（r34d 的两次连续尝试）逐字
        就是这句话，而 B 随后被逼去用通用写口 `table.create` 直写 statements（被
        `store.direct_write_refusal` 拒），那 5 条 `direct_write` 里有 1 条的根因在这里。

        传 `kind` 之后，"写进去的那个等级"与"校验端现算的那个等级"是同一个函数用同一个
        `kind` 算出来的，不可能分家；别的 kind 的派生结果与不传时逐字相同（`derive_grade`
        只在 `concept` 那一支看 `kind`）。本地这道形状关也一并带上 `kind` —— 两处必须
        同口径，否则这里放过的行会在事务里被校验端拒掉，而拒绝点离调用方更远。
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
                # 必须与 `schema.Statement.validate` 用的是同一个值：概念行的等级
                # （`not_applicable`）只有带上 kind 才算得出来，见上面那段说明。
                kind=kind,
            )
            problems = list(_EB.bits_shape_problems(bits, kind=kind))
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
                       canonical: str = "", bits: Mapping | None = None) -> dict:
        """把证明清单与 canonical 正文写回既有那一行（同一把 `statements` 锁）。

        为什么不能交给秘书：秘书的白名单（`Secretary._statement_from`）只认 `Statement` 的
        字段，`proofs` 不在 schema 里（业主口径：不加 schema 字段），所以它到不了盘上。
        这一格因此是 B 的写侧里唯一一处"直接改那一行"的地方。

        ## canonical 正文可以覆盖（2026-10-22 审计后的口径）
        改前这里把"与盘上不同"当成拒收理由（`proof_text_taken`），理由是覆盖它等于把 V
        挂在上面的签名一起作废。那条口径与"任何写入路径都不因 sha 不符拒收"相反：签名是
        读数，不是门锁。改稿是正常动作，代价只是那一签从 `signed` 变成 `stale`（待复核），
        由读侧 `verifications.review_standing` 现算，不是拒写。

        旧正文不许静默丢：覆盖之前先把旧正文整段记进行 JSON 的 `proof_history` 列表，
        每条逐字是 `{"text": 旧正文, "sha": 旧正文字节 sha256, "at": 覆盖时刻,
        "replaced_by": 新正文字节 sha256}`。读的人因此能回答"这一版之前是哪一版、被哪一版
        换掉的"，而不需要去别处找归档。

        ## 清单仍不覆盖
        #p2 及以后是追加式的：同号不同正文仍整笔不写（`proof_no_taken`）。那是"一份已经
        存在的证明被换掉"，与 canonical 这一格（同一份证明的改稿）不是同一件事。

        ## 三态与返回值
        `written=True` 表示这一笔真的落盘了（挂了新证明，或覆盖了 canonical）；
        `already` 是"号在册、正文逐字相同"；`canonical_written` 是"canonical 真被覆盖"；
        `canonical_pending` 是"这一笔要写 canonical，但没有可写的 store / 行" —— 调用方
        据此给 `canonical_not_written`，不许折成 `duplicate_statement`（那会让正文静默消失）。
        """
        out: dict = {"written": False, "attached": [], "already": [],
                     "refused": "", "reason": "", "canonical_differs": False,
                     "canonical_written": False, "canonical_pending": False,
                     "canonical_history": [],
                     #: 第 4 位这一笔同步过没有（见 `_bits_with_formal`）：它与
                     #: "写了什么"分开报，因为"没验过"与"验过没变化"都是 `False`，
                     #: 而两者该给调用方的话不同（前者不用再登记一次）。
                     "formal_synced": False, "formal_paths": {}}
        want = str(canonical or "").strip()
        #: 这一笔交来的东西（证明清单 `entries` / canonical 正文 `want`）两样都没有。
        #:
        #: ## 两样都没有不等于"没有活要干"（D-2）
        #: 第 4 位（形式化）不是从这一笔的入参算出来的，是从 L 的 `experiments` 台账同步
        #: 进盘上那一行的 `proof_text` / `proofs` 的。于是一条 `proof_text` 空、证明
        #: 只挂在 `proofs` 列表里的命题，L 验过之后再登记一次（什么都不带）正是它进第 4 位
        #: 的那一笔；改前这里直接 `return out`，那一笔在到达 `_bits_with_formal` 之前就结束
        #: 了 ⇒ 验过的形式化永远进不了第 4 位，而且不报错（"没验过"与"验过了但没同步"在
        #: 读数上同形）。所以这里只记一个标记、不早退：后面照常走一次 `_bits_with_formal`，
        #: 有变化就写回（`formal_synced=True`），没变化则一个字都不写 —— "不写新行、不动
        #: canonical"这两条保持不变。
        nothing_to_attach = not entries and not want
        # ---- 0 字证明：受控拒绝（业主 2026-10-24 裁定 B2 的第 1 条）
        #
        # 这一格是"声明了第 N 份证明、而它的正文是空的"。`_normalize_proofs` 已经在
        # 入口拦过一遍，但这一格是第二道写入口（多证明的追加、合并稿的顺位接续都经过
        # 它），所以判据要在这里再问一次 —— 两个写入口只拦一个，等于"清单从另一条路
        # 进来时静默写一条空证明"。拒绝码与入口同一个（`refusals.EMPTY_PROOF_TEXT`）：
        # 同一件事在两处必须说同一个词。
        #
        # 注意不拦"整笔一条证明都没交"：自产命题的"证明还没做完"是合法登记态
        # （F-05 的待办那一档，见 `needs_proof` 那一段），拦掉它等于把那条路堵死。
        for _entry in (entries or []):
            if not isinstance(_entry, Mapping):
                continue
            if str(_entry.get("text") or "").strip():
                continue
            _no = int(_entry.get("proof_no") or 0)
            out["refused"] = _R.EMPTY_PROOF_TEXT
            out["reason"] = (
                f"证明清单里的 #{_no or '?'} 正文是空的 —— 空正文不是「还没写」，"
                "而是「这一份其实没交」；整笔不写（要么补上正文，要么把这一份从清单里"
                "去掉）。已经落盘的那几份一个字都不动")
            return out
        #: 写进 `proof_text` 的是调用方交来的原样正文（`raw_want`），不是比较用的
        #: `want`（去掉了首尾空白）：`bits.evidence.proof_process` 记的是原样正文，
        #: 写一份去空白的进盘就会让"正文的 sha"与"位里记的正文"分家。
        raw_want = str(canonical or "")
        store = getattr(self, "store", None)
        if store is None:
            if nothing_to_attach:
                # 没有要挂的东西、也没有 store：第 4 位同步要写盘，这里做不了；而这一笔
                # 本来就不写任何东西（不编一句"清单挂不上去"挡在上面那条路上）。
                return out
            out["reason"] = ("这一趟没有 store ⇒ 证明清单挂不上去（第 1 份已由秘书落行，"
                             "第 2 份起无处可写）")
            out["canonical_pending"] = bool(want)
            return out
        #: 第 4 位的台账（L 的 `record` 落的那张表）。在事务外先读好：它只被
        #: `_bits_with_formal` 用来算"这一位现在是什么"，不参与这一笔的内容判据。
        experiments = [dict(r) for r in store.rows("experiments")]
        with store.tx("statements", actor=str(getattr(self, "actor", "agent-B") or "agent-B"),
                      note=f"agent_b.register_statement:proofs:{stmt_id}") as tx:
            found = tx.find("statements", stmt_id=stmt_id)
            if found is None:
                if nothing_to_attach:
                    # 这一笔本来就不带东西（只为第 4 位同步而来），行不在就没什么可同步：
                    # 不编一句"清单无处可挂"（那会把"没东西可挂"说成"挂失败了"）。
                    return out
                out["reason"] = (f"`statements` 里没有 {stmt_id} ⇒ 证明清单无处可挂"
                                 "（行没落成，清单也就没有落点）")
                out["canonical_pending"] = bool(want)
                return out
            row = dict(found)
            have_raw = str(row.get("proof_text") or "")
            have_canon = have_raw.strip()
            # 逐字比，不按去空白比：只改了首尾空白的稿也是一次改稿，静默不写会让
            # 调用方以为交上去了，而盘上那一份的 sha 没变（签名也不会转 stale）。
            canonical_changed = bool(want) and raw_want != have_raw
            if canonical_changed:
                if have_canon:
                    # 旧正文先留痕，再换：顺序反了就会出现"新正文已落、旧正文已经丢了"
                    # 的窗口（事务失败时内存里那一份改动的可见性没法靠调用方保证）。
                    raw_history = row.get("proof_history")
                    history = ([dict(h) if isinstance(h, Mapping) else h
                                for h in raw_history]
                               if isinstance(raw_history, (list, tuple)) else [])
                    entry = _canonical_history_entry(have_raw, raw_want)
                    history.append(entry)
                    out["canonical_history"].append(dict(entry))
                    out["canonical_differs"] = True
                    row["proof_history"] = history
                row["proof_text"] = raw_want
                merged = _bits_after_canonical_write(row, bits)
                if merged:
                    row["bits"] = merged
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
            # ---- 第 4 位（形式化，二维）从 L 的 experiments 台账同步（D28 的写侧）。
            #
            # 位置在"挂证明"之后：证明清单变了，这一位在册的路径也就变了。这一笔只
            # 有在这里才读得到最终的 `proof_text` / `proofs`（canonical 可能刚被覆盖）。
            synced = _bits_with_formal(row.get("bits"), row, experiments)
            if synced.get("changed"):
                row["bits"] = synced["bits"]
                out["formal_synced"] = True
                out["formal_paths"] = dict(synced.get("paths") or {})
                # ---- D-37（2026-10-24 真机 cube）：kind 跟着证据升。
                #
                # 为什么落在这一格：`kind` 的判据读的是第 4 位的逐条读数，而那一格刚刚才
                # 变（第 4 位是 L 的台账同步进来的，B 只做这一笔写字）。等下一次登记再改，
                # "L 验过了、行上还叫猜想"就多留一个来回 —— cube 那条老行正是这么留下来的。
                # 判据只有一处：`evidencebits.kind_following_grade`（与秘书那一支、与读侧
                # 共用一个函数）；这里只改 `kind` 与留痕，`bits` 用的是上面刚同步好的那一份。
                kind_read = _EB.kind_following_grade(
                    row, root=getattr(store, "root", None))
                if str(kind_read.get("state") or "") == "upgraded":
                    before_kind = str(row.get("kind") or "")
                    target = str(kind_read.get("kind") or "")
                    if target in _EB.KIND_UPGRADE_TARGETS and target != before_kind:
                        row["kind"] = target
                        row["_kind_upgrade"] = {
                            "from": before_kind, "to": target,
                            "basis": str(kind_read.get("basis") or ""),
                            "grade": str(kind_read.get("grade") or ""),
                            "by": str(getattr(self, "actor", "agent-B") or "agent-B"),
                            "at": S.now_iso(),
                        }
                        out["kind_upgraded"] = dict(row["_kind_upgrade"])
            #: 三个"这一笔写什么"的来源全空 ⇒ 一个字都不写（`nothing_to_attach` 那一笔
            #: 也走这条判据：第 4 位同步出变化时 `formal_synced` 为真，于是它照样落盘）。
            if not out["attached"] and not canonical_changed and not out["formal_synced"]:
                return out
            if out["attached"]:
                row[_VR.PROOFS_KEY] = listed
            tx.upsert("statements", row,
                      note=f"agent_b.register_statement:proofs:{stmt_id}")
            out["written"] = True
            out["canonical_written"] = bool(canonical_changed)
        return out

    @staticmethod
    def _proofs_reading(attach: Mapping) -> dict:
        """把 `_attach_proofs` 的读数翻成返回值里那几格（谁挂上了、谁本来就在册）。"""
        return {
            "proofs": [{"proof_no": int(n)} for n in (attach.get("attached") or [])],
            "proofs_already": [int(n) for n in (attach.get("already") or [])],
            "proofs_refused": str(attach.get("refused") or ""),
        }

    def _write_attached_proof_deps(self, sec: Any, stmt_id: str, entries: list[dict],
                                   attach: Mapping) -> dict:
        """把这一笔真挂上去的那几份证明的依赖落成 `used_by="stmt:#pN"`。

        为什么落在这一格：`_attach_proofs` 只写 `statements`（B 的写集里没有
        `dependencies`，那两张表由秘书代写）。第 2 份及以后的证明正文因此原先根本不进
        引用扫描 —— 挂上去了，它们引用的东西一条都不在依赖图里，而返回值里也没有任何
        一格说这件事。这里把"刚挂上的那几份"交给秘书的同一个写口
        （`Secretary.record_proof_deps`）补写，读数原样回给调用方。

        只补这一笔真挂上去的（`attach["attached"]`）：已经在册的那几份不重复扫，
        否则同一条依赖会被写第二遍（`dependencies` 是追加式，一次调用一条）。
        """
        attached = {int(n) for n in (attach.get("attached") or [])}
        want = [dict(e) for e in entries if int(e.get("proof_no") or 0) in attached]
        if not want or sec is None or not str(stmt_id or "").strip():
            return {}
        try:
            return dict(sec.record_proof_deps(str(stmt_id), want))
        except Exception as exc:  # noqa: BLE001 —— 补写失败要说出来，不许当成写过了
            return {"checked": False, "stmt_id": str(stmt_id),
                    "reason": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------ D1：写侧真比对
    def _quote_doc(self, lit_id: str) -> tuple[object | None, str]:
        """把 `source_lit_id` 那一篇重新打开当可比对的文档 ⇒ `(doc, 取不到的理由)`。

        ## 为什么必须真的把全文取出来
        D1 的第二版现场（2026-10-22）：这一格此前传的是 `doc=None`（旧注释自认
        "这一趟没有文档可查"），而 `quoteevidence.locate_span` 只在 doc 非空时才跑
        ⇒ 一次比对都没有发生，"逐字回验通过"全是模型自报的（真机 13 行全是 true +
        空 span）。所以这一格改为：按 `lit_id` 找到 literature 那一行，重新打开它。

        ## 打开它只有一处实现
        `_Core._load_doc_for` 已经是"把一篇文献重新读成 doc、读不成给出可读原因"的唯一
        落点（reprocess 那条链也走它：路径非法 / 文件不在 / 抽取失败 / 无文本层要试 OCR，
        四档各有各的话）。这里只做"按 lit_id 找行"这一件本层的事，读文件的规则一个字都
        不重写 —— 第二份实现会让"这篇有没有全文"在两处读成两个答案。

        三态：读不成返回 `None` + 理由，调用方据此落 unknown（不是 false：没读到不等于
        原文里没有）。理由必须点名是哪一篇的哪一档，否则读的人只会去重试。
        """
        lid = str(lit_id or "").strip()
        if not lid:
            return None, ("这一行没有 source_lit_id（外部命题没有出处，就没有可比对的全文；"
                          "自产命题的出处是我方稿件，不走这一条）")
        store = getattr(self, "store", None)
        if store is None:
            return None, "这一趟没有 store（读不到 literature 表）"
        try:
            rows = [dict(r) for r in store.rows("literature")]
        except Exception as exc:  # noqa: BLE001 —— 读不到要如实说，不许当成"没有全文"
            return None, f"literature 表读不出来（{type(exc).__name__}: {exc}）"
        row = next((r for r in rows if str(r.get("lit_id") or "") == lid), None)
        if row is None:
            return None, f"literature 表里没有 {lid} 这一行（出处在库里查不到）"
        load = getattr(self, "_load_doc_for", None)
        if not callable(load):
            return None, ("这一趟的 B 没有 `_load_doc_for`（读全文的唯一实现），"
                          "所以拿不到这一篇的文档 ⇒ 一次比对都没发生")
        doc, why = load(row)
        if doc is None:
            return None, f"文献 {lid} 的全文读不了：{why or '原因不明'}"
        if not list(getattr(doc, "pages", None) or []):
            return None, f"文献 {lid} 抽出来是 0 页（没有可比的文本）"
        return doc, ""

    @staticmethod
    def _quote_probe(doc: object | None, *, quote_span: str,
                     proof_text: str) -> tuple[str, int, str]:
        """选出"真要核的那一段" ⇒ `(片段, 页码提示, 读数说明)`。

        优先 `quote_span` 指向的片段。这一栏两种写法都要认：

        - 逐字档的定位（`p{页}:norm[起:止]`）⇒ 拿文档切一次，切出来的那段就是"该核的
          那一段"，页码那么来的命中页提示；
        - 语义档的原文（H 判时对着的那一段）⇒ 切不出来（格式认不出），就把这一栏本身
          当片段核 —— 认不出定位格式不等于"这一栏是垃圾"。

        都没有 ⇒ 用 `proof_text`（模块 docstring 第 2 条：它是逐字摘录，也是
        `quote_verified` 原本的比对对象）。三者都空 ⇒ 空串（调用方据此降 unknown）。
        """
        span = str(quote_span or "").strip()
        if span:
            slab, page = QE.span_slice(doc, span)
            if slab:
                return slab, int(page or 0), f"按 quote_span {span} 取到的那一段"
            return span, 0, "quote_span 本身（认不出定位格式，按原文片段核）"
        text = str(proof_text or "")
        if text.strip():
            return text, 0, "proof_text"
        return "", 0, "没有可比的那一段（quote_span 与 proof_text 都是空的）"

    def register_statement(
        self,
        *,
        statement_full: str,
        source_lit_id: str = "",
        proof_text: str = "",
        #: 多证明（业主 2026-10-22）：`[{proof_no, text}, ...]`。#p1 落 `proof_text`，
        #: #p2 及以后落同一行的 `proofs` 清单；不给就与今天逐字一致（等价 #p1）。
        proofs: list | None = None,
        #: F 的证明手稿正文（业主 2026-10-24 最终形态：「作者写内容、收方读稿登记」）。
        #: 手稿里那一节 `## 依赖` 的四列表由 B 读出来落 `dependencies` —— F 自己不写台账。
        #: 不给 ⇒ 与改前逐字一致（依赖面仍由秘书的正文扫描那条老路决定）。
        proof_manuscript: str = "",
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
        #:
        #: D1（2026-10-22）起这两栏还有第二层用法：逐字档把 `quote_span` 写成定位
        #: （`p{页}:norm[起:止]`，见 `quoteevidence.SPAN_SCHEME`），写侧会拿它指向的
        #: 片段（或 `proof_text`）去这一篇的全文里真比对，落盘的区间是重算出来的那个
        #: （自报的区间只是线索）。核不出区间 ⇒ 这一笔降成 unknown，理由说清为什么要补。
        quote_span: str = "",
        quote_call_sha256: str = "",
        derived_from: list | None = None,
        doc_id: str = "",
        line_range: dict | None = None,
    ) -> dict:
        """登记一条命题，返回 `{"ok": True, "stmt_id": ..., "row": {...}}`；不合规就零写入。"""
        full = str(statement_full or "").strip()
        #: 这一笔的 `kind` 只在这里派生一次（B-2 的判据与落库用的必须是同一个值）。
        #:
        #: 为什么强调"只一处"：改前这个缺省值在动作里出现过两遍 —— 概念行那一支写
        #: `str(kind or "").strip() == "concept"`，载荷那一格写 `str(kind or "theorem")`。
        #: 两处各算一次，谁加一个 `.strip()` 或改一次缺省值，"判据读的那个 kind"与
        #: "落库的那个 kind"就会分家 —— 而它们分家的形态是静默的：判据放过的行，
        #: 落下去以后换了个 kind，没有任何读数会说这两者不是同一个。
        kind_now = str(kind or "theorem").strip()
        if not full and kind_now != "concept":
            # 命题没有"内容待补"这一档：省掉假设的命题会被下游当成无条件成立。
            # 概念有（业主 `draft/97` §14.13 逐字：「抽不到定义的概念就让A去网上搜，
            # 写入时定义内容留空，等A返回后写入」）⇒ 空定义的概念要落行并带待补标记，
            # 而不是在这里被拒。这一档此前也拒，于是"定义还没抽到"这件事在 B 的动作里
            # 根本走不通（只有直接调秘书那条路能落）—— 而 §15.4 最常见的场景
            # （B 消化 A 查回来的论文时撞到生僻定义）走的正是这个动作。
            #
            # 2026-10-24（业主裁定 B2 的第 1 条）：受控码改成 `empty_statement_text`。
            # 为什么不继续用 `bad_statement`：那一句拒信把"只有短版"与"0 字"混在一档里，
            # 而"0 字"是另一件事 —— 它连可判的对象都没有（判档位那一趟也会拒它，
            # 见 `secretary.judge_statement` 的同一条受控码），所以两者的读数要分得开。
            return _refuse(_R.EMPTY_STATEMENT_TEXT,
                           "statement_full 不能为空 —— 只有短版（statement_text）不算数："
                           "省掉假设的命题会被下游当成无条件成立；0 字正文连"
                           "非平凡性档位都没法判（四项力气读数一项都取不到）"
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
        if kind_now == "concept":
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
        # 判档位那一趟能不能读完这条正文（B2 的第 2 条）：空字典 = 读得完。
        # 位置在这里：证明清单刚归一完，`proof_text` 已经是最终那一份（#p1 已接进来）。
        trunc_reading = _text_truncation_reading(statement_full=full, proof_text=proof_text,
                                                 proofs=proofs_listed)
        # ---- 手稿的依赖段（业主 2026-10-24 最终形态） ---------------------------------
        #
        # 业主原话（逐字）：「依赖面登记是否是F在其手稿中写好，D的研究手稿引用F的证明手稿给B
        # 入库时，B侧读到F手稿处的依赖面，按此入库的？（即和V签一个逻辑）」「改」。
        # ⇒ 作者（F）只在手稿里写内容，登记由收方（B）读稿产生；F 不写 `dependencies`。
        #
        # 三条判据与处置（实现全在 `agentflow.depsection`，这里只做"读到就核、核不住就整笔拒"）：
        #   ① 手稿里没有 `## 依赖` 这一节、而证明正文（`## 证明` 那一节）里点了 `stmt:` 引用 ⇒
        #      整笔受控拒绝 `dependency_section_missing`（业主 2026-10-24 的裁定：依赖面就在
        #      手稿里、B 按它入库；正文引了却交不出那一节 = 这份手稿不合格，补上再来）。
        #      只报一句 `deps_missing` 就照常入库，等于给"不写依赖段"留一条最省事的路；
        #   ② 有段而某行读不懂（缺列 / 列数不对 / 命题号形状不对 / 路径号不是正整数）⇒
        #      整笔受控拒绝 `dependency_section_unreadable` 并点明第几行、缺哪一列；
        #   ③ 段里的来源不在册 / 不可用 / 档位低于 `proof_review` / 档位读不到 ⇒ 整笔受控拒绝
        #      （档位判据从等级序现算，见 `depsection.citation_levels`）。
        # 一条 `stmt:` 引用都没有（自足的证明）⇒ 不拒、也不记 missing：读数是 `not_applicable`。
        #
        # ---- 兜底读盘（2026-10-26，死结 2 的修法） ---------------------------------
        #
        # 真机读数（sylow5/sylow6）：`proof_manuscript` 这一格从来没有人传过值 —— 它是可选
        # 参数，而 B 的提示词只印必填参数（实测这一格在 B 的段里出现 0 次）⇒ 就算 F 写了
        # 手稿，也没有任何代码把它读出来递进这一笔登记，`dependencies` 于是恒 0 行。
        #
        # 业主 2026-10-26 把传递路径定成三段（原话「是通过D传吗」）：
        #   ① `param`：调用方（D 派 B 那一笔的 args / 直调）把正文递进来了，最优先；
        #   ② `carried_by_D`：D 交研究手稿给 B 入库时把它一并带上（D 的报告里有
        #      「携带的证明手稿」那一节，`depsection.read_carried_manuscript` 读它）——
        #      这是主路：携带者 D、收方 B；
        #   ③ `disk`：前两处都没有（历史调用 / 直调），按约定路径去盘上找 F 的稿
        #      （两种名都认：`reports/f-proof-<命题号>.md` 与 `reports/f-proof-plan-<plan>.md`）。
        # 三处都没有时按下面那一条（有引用就整笔拒收）处置。
        # 读数写清稿是从哪来的（`manuscript_source=param|carried_by_D|disk|none`）。
        manuscript_source = _DS.SOURCE_NONE
        manuscript_probe: dict = {}
        manuscript_carried: dict = {}
        manuscript_text = str(proof_manuscript or "")
        probe_ids = _DS.candidate_statement_ids(
            derived_from=derived_from, proof_text=proof_text,
            # 手稿头那一行"命题号：stmt:<号>"：D 递过来的那一份稿用它自己的号
            # 去对携带单（`derived_from` 是承重链，不是这份稿自己的号）。
            extra=[_DS.manuscript_statement_id(manuscript_text)])
        if manuscript_text.strip():
            # ---- D 的递交（2026-10-26 晚：「D 到 B 没有路吗？加」） -------------------
            #
            # 参数里给的这一份，如果正是 D 那份携带单里点了名、且 sha 与盘上那份相符
            # 的那一版 ⇒ 读数是 `carried_by_D`（D 带来并亲手递上来的）。
            # 这不是"猜谁调的"，判据是盘上那份报告里的三列表与这份正文逐字相符：
            # 携带单没有它、或 sha 对不上 ⇒ 照旧记 `param`（那是别的调用方直递的）。
            probe_carried = _DS.read_carried_manuscript(
                getattr(self.store, "root", ""), statement_ids=probe_ids)
            if (str(probe_carried.get("source") or "") == _DS.SOURCE_CARRIED
                    and _same_manuscript_text(probe_carried.get("text"), manuscript_text)):
                manuscript_source = _DS.SOURCE_CARRIED
                manuscript_carried = probe_carried
            else:
                manuscript_source = _DS.SOURCE_PARAM
        else:
            manuscript_carried = _DS.read_carried_manuscript(
                getattr(self.store, "root", ""), statement_ids=probe_ids)
            if str(manuscript_carried.get("source") or "") == _DS.SOURCE_CARRIED:
                manuscript_text = str(manuscript_carried.get("text") or "")
                manuscript_source = _DS.SOURCE_CARRIED
            else:
                manuscript_probe = _DS.read_manuscript(
                    getattr(self.store, "root", ""), statement_ids=probe_ids)
                if str(manuscript_probe.get("source") or "") == _DS.SOURCE_DISK:
                    manuscript_text = str(manuscript_probe.get("text") or "")
                    manuscript_source = _DS.SOURCE_DISK
        manuscript: dict = {}
        deps_groups: list[list[dict]] = []
        manuscript_refs: list[str] = []
        #: 这一份稿是不是 F 的秘书洗过的那一版（业主 2026-10-26 晚：B 读到的必须是
        #: "秘书洗过"的版本，读数带 `manuscript_washed=true`）。那一行元信息由
        #: `agent_f` 在洗完之后盖进正文（`depsection.mark_washed`），跟着文件走 ——
        #: 于是"这份稿洗没洗过"在收方这里读得到，不靠调用方自述。
        manuscript_wash: dict = _DS.manuscript_wash_reading(manuscript_text) if (
            manuscript_text.strip()) else {"washed": False, "actor": "", "filled": "", "mark": ""}
        manuscript_washed = bool(manuscript_wash.get("washed"))
        # ---- 兜底审计（2026-10-27）：盘上那份稿不是框架渲染的 ---------------------
        #
        # 为什么这一条必须存在：上面那一整条链（F 的 proof 动作渲染 `## 依赖` → 秘书洗稿
        # 并盖元信息 → D 携带 → B 读稿）的有效性，全部压在"这份稿是框架写出来的"上。
        # 而改前的真机形态是模型直接 `fs.write` 写一份自由格式的 `reports/f-proof-*.md`
        # —— 它有文件名、有正文，于是下游每一处都"读到了"，只是没有四列依赖表、
        # 也没有洗稿元信息：`dependencies` 于是 0 行，而读数上一切正常。
        # `fs.write`/`fs.edit` 那一侧已经受控拒绝（`reserved_framework_artifact`），
        # 但"换个名字绕过"永远有路（手写、别的工具、人放一份到盘上）⇒ 收方这里再挡一次。
        #
        # 判据的形状（三态，不折平）：稿是从盘上（`disk`）或 D 携带（`carried_by_D`）来的、
        # 路径是约定的 `reports/f-proof-*.md`、而正文里没有 `- 依赖面洗稿：` 那一行 ⇒
        # 这一份不是框架渲染的，整笔受控拒绝并点名让 F 重写。
        # 参数直递（`param`）那一档不在这里判：B 拿不到它的落点，"猜它是谁写的"不是判据。
        if manuscript_text.strip() and not manuscript_washed:
            if manuscript_source == _DS.SOURCE_CARRIED:
                wash_rel = str(manuscript_carried.get("path") or "")
            elif manuscript_source == _DS.SOURCE_DISK:
                wash_rel = str(manuscript_probe.get("path") or "")
            else:
                wash_rel = ""
            if _DS.is_framework_manuscript(wash_rel):
                return _refuse(
                    str(_DS.REFUSED_NOT_WASHED),
                    "这份手稿不是框架渲染的（缺洗稿元信息），请让 F 用 proof 动作重写",
                    manuscript_source=manuscript_source,
                    manuscript_path=wash_rel,
                    missing_mark=_DS.WASH_MARK.rstrip())
        if manuscript_text.strip():
            manuscript = _DS.parse_dependency_section(manuscript_text)
            # 引用只在"证明正文"那一节里数（手稿开头的元信息不是引用）。
            manuscript_refs = _DS.stmt_refs(_DS.proof_body(manuscript_text))
            if manuscript.get("refused"):
                return _refuse(
                    str(_DS.REFUSED_SECTION), str(manuscript.get("reason") or ""),
                    problems=list(manuscript.get("problems") or []),
                    heading_line=int(manuscript.get("heading_line") or 0))
            if not manuscript.get("present") and manuscript_refs:
                shown = "、".join(f"stmt:{x}" for x in manuscript_refs[:3])
                more = f" 等 {len(manuscript_refs)} 条" if len(manuscript_refs) > 3 else ""
                return _refuse(
                    str(_DS.REFUSED_SECTION_MISSING),
                    f"这份证明手稿里没有 `## 依赖` 那一节，而正文引用了 {shown}{more} —— "
                    "依赖面必须写进手稿（四列表，列固定），B 按它入库；补上那一节再交",
                    refs_in_proof=list(manuscript_refs),
                    manuscript_source=manuscript_source)
            if manuscript.get("present"):
                try:
                    stmt_rows = [dict(r) for r in self.store.rows("statements")]
                except Exception as exc:  # noqa: BLE001 —— 读不到就不许放行
                    return _refuse(
                        str(_DS.REFUSED_LEVEL_UNREADABLE),
                        f"手稿的依赖段要核每条来源的档位，而 `statements` 读不出来"
                        f"（{type(exc).__name__}: {exc}）⇒ 整笔不写：读不到档位就不许放行")
                gate = _DS.gate_rows(manuscript.get("rows") or (), stmt_rows)
                if not gate.get("ok"):
                    return _refuse(
                        str(gate.get("refused") or _DS.REFUSED_LEVEL_TOO_LOW),
                        str(gate.get("reason") or ""),
                        source_levels=dict(gate.get("levels") or {}),
                        required=sorted(_DS.CITATION_LEVELS))
                kinds = {str(r.get("stmt_id") or ""): _DS.dep_kind_of(str(r.get("kind") or ""))
                         for r in stmt_rows}
                deps_groups = _DS.deps_groups(manuscript.get("rows") or (), kinds)
        else:
            # ---- 参数空、盘上也没有稿：不许静默跳过（2026-10-26，业主的裁定） ------
            #
            # 正文引用了在册命题 ⇒ 这份证明的依赖面必须写在手稿里，而这一笔交不出手稿
            # （参数空、约定路径也找不到）⇒ 整笔受控拒绝 `dependency_section_missing`。
            # 一条在册引用都没有 ⇒ `not_applicable`（自足的证明合法，不拒收），
            # 依赖面仍由秘书那条正文扫描的既有口径给读数。
            # 判"在册"要真读一次 `statements`：读不到就不许把"读不到"折成"没有引用"，
            # 也不能凭引用形状就拒（一条指向不存在号的引用不是这一档的事）。
            probe_refs = _DS.stmt_refs(proof_text)
            if probe_refs:
                try:
                    known_ids = {str(r.get("stmt_id") or "") for r in self.store.rows("statements")}
                except Exception:  # noqa: BLE001 - 读不到就只按形状判，理由里写清
                    known_ids = set(probe_refs)
                on_ledger = [rid for rid in probe_refs if rid in known_ids]
                if on_ledger:
                    shown = "、".join(f"stmt:{x}" for x in on_ledger[:3])
                    more = f" 等 {len(on_ledger)} 条" if len(on_ledger) > 3 else ""
                    return _refuse(
                        str(_DS.REFUSED_SECTION_MISSING),
                        (f"这一笔的证明正文引用了在册命题 {shown}{more}，而它没有交出手稿"
                         "（`proof_manuscript` 是空的）。三处都找过了："
                         "① 参数里没有；"
                         "② D 的研究报告里没有携带它（" + str(manuscript_carried.get("why")
                                                              or "（D 的报告里没有那一节）")
                         + "）；"
                         "③ 按约定路径去盘上找也没有（"
                         + str(manuscript_probe.get("why") or "（没有可定位的命题号）")
                         + "）—— 依赖面必须写进 F 的证明手稿（四列表，列固定），B 读稿登记；"
                         "让 D 把 F 那份稿一并带过来（或把正文传进 `proof_manuscript`）再交"),
                        refs_in_proof=list(on_ledger),
                        manuscript_source=_DS.SOURCE_NONE,
                        manuscript_probe=dict(manuscript_probe),
                        manuscript_carried=dict(manuscript_carried))

        def _deps_reading(written_row: Mapping) -> dict:
            """这一笔的依赖面三态读数（没有手稿 ⇒ 秘书那一份原样透出）。

            读数里多带几格（2026-10-26，死结 2 的读数面）：`manuscript_source` 说稿是从
            参数来的、D 带过来的、从盘上读的、还是没有；`manuscript_probe` 是兜底读盘查过的
            路径、`manuscript_carried` 是 D 那一侧查过的报告（三处逐条留痕，于是"没收到稿"
            与"收到了但那份稿没有依赖段"在读数上分不开这件事被修掉了）。
            """
            base = (dict(written_row.get("deps_missing") or {}) if not manuscript
                    else _DS.deps_missing_reading(
                        proof_text=proof_text,
                        deps_written=int(written_row.get("deps_written") or 0),
                        derived_from=manuscript_refs,
                        stmt_id=str(written_row.get("stmt_id") or ""),
                        refs=len(manuscript_refs), section=manuscript))
            base["manuscript_source"] = manuscript_source
            #: 这一份稿是不是 F 的秘书洗过的那一版（跟着文件走的读数，见上面）。
            base["manuscript_washed"] = manuscript_washed
            if manuscript_probe:
                base["manuscript_probe"] = dict(manuscript_probe)
            if manuscript_carried:
                # D 那一侧查过什么也留下来（携带单里有几条 / 为什么没对上），
                # 否则"主路没走到"与"主路走了但没找到"在读数上分不开。
                base["manuscript_carried"] = dict(manuscript_carried)
            return base

        # ---- 收方读稿登记（业主 2026-10-26 晚：「D 到 B 没有路吗？加」） --------------
        #
        # 这一笔可能是"同一条命题再交一次"：F 已经把它落成 `statements` 一行，而这一趟
        # D 把 F 的证明手稿一并递过来了。收方要做的是读稿落依赖面，不是再新建一行、
        # 也不是再判一次那条命题的档位 —— 所以这一支在 B-2/B-3 之前提前返回：
        # 命题行一个字不动，只走秘书那一笔 `dependencies`（B 仍是写者，秘书仍是执行者）。
        #
        # 判据没有绕过：手稿的依赖段已经由上面那一块解析并逐条核过（缺节、读不懂、
        # 来源不在册、档位不够 `proof_review` 各有一档受控拒绝），本支只负责
        # "把核过的段落成边"。没有这一支时，同一条命题的第二次递交走 `duplicate` 早退
        # ⇒ `dependencies` 一行都不落，而这正是"F 写了稿、D 带了稿、依赖面还是 0 行"的成因。
        if manuscript_text.strip():
            redelivery = self._existing_statement_for(full)
            if redelivery is not None:
                return self._receive_carried_manuscript(
                    redelivery, deps_groups=deps_groups, manuscript=manuscript,
                    manuscript_refs=manuscript_refs, manuscript_source=manuscript_source,
                    manuscript_washed=manuscript_washed, manuscript_wash=manuscript_wash,
                    proofs=proofs_listed, proof_text=proof_text, deps_reading=_deps_reading)

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
        # ---- 2026-10-23（业主裁定「都由 E 来签」→ 晚间更正「签字仍然由 V 签」）：B 不许自签 proof
        #
        # `proof` 这一档从这一天起有两个入口：形式化（检查器/L 那一支）与穷举
        # （E 按 `numericproof` 的穷尽证据签、证明栏写程序脚本）。两样都不是 B 能给的，
        # 所以本动作在写入前核一次台账：我方结果（`origin="own_result"`）要 proof，
        # 就必须指得到一条真的第三方签名。判据只有一处（`numericproof.filing_problems`），
        # 这里只把它的结论翻成一条带 `kind` 的拒绝 —— 拒信逐条写清缺什么、怎么补。
        exp_rows = []
        try:
            exp_rows = list(self.store.rows("experiments"))
        except Exception:  # noqa: BLE001 —— 读不到台账不等于"没有签名"；见下
            # 读不到实验台账时不能放行（那会把"查不了"折成"查过了没问题"）：
            # 交给 `filing_problems` 的空清单分支 ⇒ 拒，理由里会写"台账里没有对应实验"。
            exp_rows = []
        stmt_rows = []
        try:
            stmt_rows = list(self.store.rows("statements"))
        except Exception:  # noqa: BLE001 —— 同上：读不到命题台账 ⇒ 那一格"没查成"⇒ 拒
            stmt_rows = []
        _sign_problems = _NP.filing_problems(origin=origin, evidence_kind=evidence_kind,
                                             proof_text=proof_text, experiments=exp_rows,
                                             # 第三方签字（V 的会审签名）要按命题读台账：
                                             # 根 + 在册的那条命题（按正文认号，与
                                             # `_v_signature_for` 同一个认法）。
                                             # 缺任何一件 ⇒ 那一格"没查成" ⇒ 闸照旧拒。
                                             root=getattr(self.store, "root", None),
                                             statements=stmt_rows,
                                             statement_full=full,
                                             # D-34：D 报告的目录行（论文对应表）。
                                             # 读不到 ⇒ 空清单 ⇒ 索引那一路取不到对象，
                                             # 闸按"目录里没有这一条"拒（不是放行）。
                                             index_rows=self._report_index_rows())
        if _sign_problems:
            return _refuse("proof_needs_third_party_signature", "；".join(_sign_problems))
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

        # ---- 业主 2026-10-22 的 B-3（后半）：自产的定理级命题要先过 V。
        #
        # 位置为什么在这里：来源 / 正文 / 证明清单 / 三态都定稿了（上面那几级会把
        # `needs_proof` 的 `quote_reason` 写实），而任何写入都还没发生 —— 闸要么
        # 放行、要么零写入。判定顺序（与 B-2「无引文的必须从猜想注册」共存）：
        # 概念短路 → 猜想放行 → 自产要签 → 有签放行。逐字写在 `_self_authored_gate`。
        self_authored = self._self_authored_gate(
            # `kind` 传的是上面那唯一一处派生出来的值（不是再算一次 `str(kind or "theorem")`）：
            # 闸判的那个 kind 与落库的那个 kind 必须是同一个字符串，否则"判据放过了、
            # 落下去的却是另一个 kind"这件事在读数上完全看不见。
            origin=str(origin), kind=kind_now, lit_id=lit_id,
            statement_full=full, proof_text=str(proof_text or ""))
        if self_authored.get("refused"):
            # 两条裁定的分工按"阶段"分，拒收码也跟着阶段走（同一件事的两种说法：
            # 一个说"你一开始就不该叫定理"，一个说"现在欠的是 V 的一签"）：
            #   - 册上还没有同一条命题 ⇒ 这是首次登记 ⇒ B-2 的码 `must_start_as_conjecture`
            #     （另一路已落地的那张白名单；`_must_start_as_conjecture_refusal` 是它的文案）；
            #   - 册上已经有同一条命题（先立成猜想、现在来声明定理级）⇒ 这正是业主
            #     B-3 点名的"从猜想升成 theorem/lemma 的那一步" ⇒ `self_authored_needs_v`：
            #     此刻缺的不是"换个 kind"，是 V 的那一签。
            _b2_hits = (str(origin) == "own_result" and not lit_id
                        and quote_verified is not True
                        and kind_now not in CONJECTURE_START_KINDS)
            if _b2_hits and not bool((self_authored.get("reading") or {}).get("in_ledger")):
                return _must_start_as_conjecture_refusal(kind_now=kind_now,
                                                         origin=str(origin))
            return _refuse(str(self_authored["refused"]),
                           str(self_authored.get("reason") or ""))

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

        # ---- D1（2026-10-22，第二版）：写侧断言 —— 说"逐字通过"就必须当场核一次。
        #
        # 真机读数（`saxl-ws/data/statements.json`，修复前）：13 条命题全写着
        # `quote_verified=true` / `quote_mode=verbatim`，而 `quote_span` /
        # `quote_reason` / `quote_call_sha256` 三栏全空。追下去是这一格的写法问题：
        # 断言里传的是 `doc=None`（旧注释自认"这一趟没有文档可查"），而
        # `quoteevidence.locate_span` 只在 doc 非空时跑 ⇒ 一次比对都没发生，
        # "逐字回验通过"只是模型自报的入参。
        #
        # 现在这一格真的去核，三件事：
        # ① 给了 `source_lit_id` ⇒ 把那一篇的全文取出来当 doc（`_quote_doc`）；
        # ② `quote=` 传真要核的那一段 —— 优先 `quote_span` 指向的片段，否则
        #    `proof_text`（`_quote_probe`）；
        # ③ 交给 `enforce_quote_evidence`（区间只由 `locate_span` 产出）：
        #    算得出区间 ⇒ 落 True + 区间；有全文而整份里都没有那一段 ⇒ 落 False
        #    （查过、不一致）；没有可比的全文 ⇒ 降 unknown + 可操作理由；
        #    语义档缺区间或调用指纹 ⇒ 整笔不写（具名拒绝）。
        #
        # 位置为什么在这里：三态定稿在上一格（`needs_proof` 会把自产命题的
        # `quote_reason` 写实），而五元位要按定稿后的 `quote_verified` 现算 ——
        # 断言必须排在 `_statement_bits` 之前，否则位会把一句"通过了"当真。
        #
        # 只有"说通过"才去读全文：没有这一句就没有东西要核，而重新打开一篇文献
        # （可能还要 OCR）是这一笔最重的 I/O —— 不该为一次注定要写 unknown 的登记付它。
        if quote_verified is True:
            _quote_doc, _quote_doc_problem = self._quote_doc(lit_id)
        else:
            _quote_doc, _quote_doc_problem = None, ""
        _probe_quote, _probe_page, _probe_note = self._quote_probe(
            _quote_doc, quote_span=quote_span, proof_text=str(proof_text or ""))
        evidence, evidence_reading = QE.enforce_quote_evidence(
            {"quote_verified": quote_verified, "quote_mode": quote_mode,
             "quote_span": quote_span, "quote_call_sha256": quote_call_sha256,
             "quote_reason": quote_reason},
            quote=_probe_quote, doc=_quote_doc, page_range=page_norm,
            field="statements.proof_text", doc_problem=_quote_doc_problem,
            hint_page=_probe_page, note=_probe_note)
        if not evidence_reading.get("ok"):
            # 拒绝码跟着判据走：`no_source_without_backing`（B-4）与其余几档分开命名 ——
            # 前者是"理由里承认了没有来源可核、却没有我方手稿的背书"，后者是"该给的
            # 证据栏没给齐"。两种欠账的处置不同（补背书 / 补 span 或理由），读数就必须
            # 能分辨，否则调用方只会看到同一个 `quote_evidence_missing` 然后再试一次。
            return _refuse(str(evidence_reading.get("code") or "quote_evidence_missing"),
                           str(evidence_reading.get("why") or "") + _all_missing)
        quote_verified = evidence["quote_verified"]
        quote_mode = str(evidence["quote_mode"])
        quote_span = str(evidence["quote_span"])
        quote_call_sha256 = str(evidence["quote_call_sha256"])
        quote_reason = str(evidence["quote_reason"])

        # ---- B-2（业主 2026-10-22 裁定 D18）：没有引文 / 自己编的命题必须从"猜想"注册。
        #
        # 判据三件一齐成立才算这一档：`origin="own_result"`（是我们自己的）+ 没有
        # `source_lit_id`（没有外部出处）+ `quote_verified` 不是 True（没有一条回验
        # 通过的引文）。这时它凭什么一进门就叫 theorem / lemma / proposition？等级是
        # 五元位现算的（`evidencebits`），但 `kind` 是声明：一条还没被任何证据撑起来的
        # 声明按强档登记，下游（G 写正文、H 审校、收工门）读到的就是一句"这是定理"，
        # 而没有任何一格会说它的门第先于证据。
        #
        # 位置为什么排在 `enforce_quote_evidence` 之后：判据读的必须是定稿后的三相值 ——
        # 那种"模型说 true、其实查不成"的行会被降成 None，它在证据面与 None 是同一件事，
        # 按入参判就会放过它。
        #
        # `concept` 在这一档之外：概念行不参与等级链（见 `evidencebits.derive_grade` 的
        # 短路那一支），它没有"强于猜想"这回事。V 已经签住的那些行也让路（共存口径见
        # 上面 B-3 那一闸的注释：那一签本身就是"它先立过猜想、走过复核"的证据）。
        if (str(origin) == "own_result" and not lit_id
                and quote_verified is not True
                and kind_now not in CONJECTURE_START_KINDS
                # 2026-10-23：穷举证明的那一档让路 —— 它一进门就能叫定理，凭的是 E 的签名
                # 与那份程序（业主：「纯数值实验直接把整个命题证掉了，那也能拿 proof 标识」），
                # 而不是"先立猜想、等 V 的签"。判据与 `_self_authored_gate` 那一条同源。
                and self._e_signed_exhaustion(proof_text) is None
                and not bool((self_authored.get("reading") or {}).get("signed"))):
            return _must_start_as_conjecture_refusal(kind_now=kind_now,
                                                     origin=str(origin))

        # ---- 业主 2026-10-09：「B 不直接用增工具，秘书实际操作增、改、查工具，
        # B 纯粹负责消化理解」⇒ 上面那些是内容的判据（B 的判断），写盘这一段交给秘书。
        bits, bits_bad = self._statement_bits(
            origin=str(origin), lit_id=lit_id, proof_text=str(proof_text or ""),
            quote_verified=quote_verified,
            other_proofs=[str(e.get("text") or "") for e in proofs_listed],
            # 透传的是上面唯一一处派生出来的 `kind_now`（不是再算一次）：
            # 位里的等级、校验端的等级、落库那一行的 kind 必须是同一个字符串。
            kind=kind_now)
        if bits_bad is not None:
            return bits_bad
        sec = self._statement_secretary()
        if sec is None:
            return _refuse("secretary_unavailable",
                           "这一趟没有秘书 ⇒ 命题写不了（写入侧是 B 的活，但落盘归秘书："
                           "`Secretary.record_statement`。不许退回'B 自己写'那条后备路）"
                           + (f"；{self.secretary_problem}" if self.secretary_problem else ""))
        payload = {
            "origin": origin, "kind": kind_now, "label": str(label or ""),
            "statement_text": str(statement_text or ""), "statement_full": full,
            "proof_text": str(proof_text or ""), "source_lit_id": lit_id,
            "page_range": dict(page_norm), "quote_verified": quote_verified,
            "quote_mode": str(quote_mode or ""),
            "quote_reason": str(quote_reason or ""), "evidence_kind": evidence_kind,
            "quote_span": str(quote_span or ""),
            "quote_call_sha256": str(quote_call_sha256 or ""),
            "derived_from": S.sorted_unique(list(derived_from or [])),
            "doc_id": str(doc_id or ""), "line_range": dict(line_norm), "bits": bits,
            # 手稿依赖段读出来的边（外层 = 路径组）。空列表 = 这一笔没有手稿依赖段，
            # 秘书照旧走它那条正文扫描（老路一个字不改）。
            "deps": [list(g) for g in deps_groups],
        }
        written = sec.record_statement(payload, role="B")
        if written.get("merged") and not written.get("created"):
            # 2026-10-24（业主：表述几乎相同的定理要认出是同一个；证明方式几乎相同的视为
            # 同种证明，可选各取所长混合成一份、重拿 V 签）：秘书把这一笔判成了"已有命题"。
            # 两种去向，都由秘书落盘（证明清单 / 依赖 / 合并稿的覆盖都在那一笔事务里）：
            #   - 第 N 份证明（`proof_no` >= 1、`merged_same_kind` 为假）⇒ 这里不再
            #     调 `_attach_proofs`：秘书已经把它写进 `proofs`（或 canonical 那一格），
            #     再写一遍就是"同一份证明两个写者"；
            #   - 同种证明的合并稿（`merged_same_kind` 为真）⇒ 秘书把它作为那一份证明的
            #     新版本，旧正文已进 `proof_history`，且要求 V 重签（`resign_required`）。
            # 两种都不动 canonical 那一格以外的任何正文 —— 改 canonical 的只有合并那一档，
            # 而它由秘书在事务里做（含留痕），不在这里补一刀。
            stmt_now = str(written.get("stmt_id") or "")
            proof_no = int(written.get("proof_no") or 0)
            out = {"ok": True, "stmt_id": stmt_now, "new_row": False, "merged": True,
                   "merged_into": str(written.get("merged_into") or stmt_now),
                   "self_authored_review": self._self_authored_reading(self_authored),
                   "source_lit_id": lit_id or None,
                   "quote_verified": quote_verified, "origin": origin,
                   "quote_mode": str(quote_mode or ""),
                   "evidence_kind": evidence_kind,
                   "matched_by": str(written.get("matched_by") or ""),
                   "similarity": float(written.get("similarity") or 0.0),
                   "proof_no": proof_no,
                   "duplicate_reading": bool(written.get("duplicate")),
                   # ---- 命题同一性那一趟判定的读数（业主 2026-10-24：「让秘书洗定理名，
                   # 让秘书判」）。四样都要透出来，否则调用方看不见"这一条被并进去了"
                   # 与"凭什么并的"：`adjudication`（三态 + 判词 + 是否沿用缓存）、
                   # `canonical_name`（洗过的定理名）、`label_washed`（原标签 → 定理名）、
                   # `proof_route`（标签里被洗掉的那条路线 —— 它落在第 N 份证明上，没有丢）。
                   "adjudication": dict(written.get("adjudication") or {}),
                   "canonical_name": str(written.get("canonical_name") or ""),
                   "label_washed": dict(written.get("label_washed") or {}),
                   "proof_route": str(written.get("proof_route") or ""),
                   "row": dict(written.get("row") or {}),
                   #: 秘书那一笔把依赖面建起来没有（三态；见 `_deps_missing_reading`）。
                   "deps_missing": _deps_reading(written),
                   #: 稿是从参数来的、从盘上读的、还是没有（2026-10-26 的兜底读盘）。
                   "manuscript_source": manuscript_source,
                   "manuscript_washed": manuscript_washed,
                   "manuscript_wash": dict(manuscript_wash),
                   "note": str(written.get("reason") or "")}
            #: 判档位那一趟读不完这条正文时的那三格（空字典 = 读得完；见
            #: `_text_truncation_reading`）：三条"没有新建行"的出口都要带上它 ——
            #: 这一笔交上来的正文超了上限这件事，与"有没有新建行"无关。
            out.update(trunc_reading)
            if proof_no >= 1:
                out["proofs"] = [{"proof_no": proof_no}]
            if written.get("merged_same_kind"):
                out["merged_same_kind"] = True
                out["resign_required"] = True
                out["reviewed"] = bool(written.get("reviewed"))
                out["proof_standing"] = dict(written.get("proof_standing") or {})
                out["proof_history"] = list(written.get("proof_history") or [])
            elif proofs_listed:
                # 调用方这一笔还带了 `proofs` 里的第 2 份及以后（多证明清单）。秘书只把
                # `proof_text`（清单里的 #p1）判成了第 N 份证明，所以剩下的按顺位接在它
                # 后面 —— 不接就是静默丢掉"这一笔交上来的另外几份证明"。
                base_no = int(written.get("proof_no") or 0)
                extra = [{"proof_no": base_no + offset,
                          "text": str(entry.get("text") or ""),
                          "created_at": str(entry.get("created_at") or "")}
                         for offset, entry in enumerate(proofs_listed, 1)]
                more = self._attach_proofs(stmt_now, extra, canonical="", bits=bits)
                attached_more = [int(n) for n in (more.get("attached") or [])]
                if attached_more:
                    listed = [{"proof_no": base_no}] if base_no >= 1 else []
                    listed.extend({"proof_no": n} for n in attached_more)
                    out["proofs"] = listed
                    out["note"] += (
                        "这一笔还带来 "
                        + "、".join(f"#{n}" for n in attached_more)
                        + "（清单里的第 2 份及以后），按顺位接在第 "
                        + f"{base_no} 份之后。")
                if more.get("refused") or (not attached_more and more.get("reason")):
                    out["proofs_not_attached"] = {
                        "refused": str(more.get("refused") or ""),
                        "reason": str(more.get("reason") or ""),
                        "already": [int(n) for n in (more.get("already") or [])]}
            if proofs_dropped:
                out["proofs_dropped"] = proofs_dropped
            return out
        if written.get("upgraded") and not written.get("created"):
            # 同一份内容再交一次、这一回带了 `proof_review` 的凭据 ⇒ 秘书「改那一行」
            # （不新建）。这是 `evidence_kind` 从弱档走到 `proof_review` 的唯一一条正路：
            # 通用写口 `table.update("statements")` 已被 `store.direct_write_refusal` 拒
            # （它能同时改 bits / proof_text / quote_verified，而没有任何东西核过那些字段）。
            # 对调用方来说这是"成功了"（那一行的档位变了），不是重复读数。
            stmt_now = str(written.get("stmt_id") or "")
            attach = self._attach_proofs(stmt_now, proofs_listed,
                                         canonical=str(proof_text or ""),
                                         bits=bits)
            out = {"ok": True, "stmt_id": stmt_now,
                   "self_authored_review": self._self_authored_reading(self_authored),
                   "source_lit_id": lit_id or None,
                   "quote_verified": quote_verified, "origin": origin,
                   "quote_mode": str(quote_mode or ""),
                   "evidence_kind": evidence_kind, "upgraded": True,
                   "row": dict(written.get("row") or {}),
                   #: 依赖面建起来没有（三态；见 `_deps_missing_reading`）。
                   "deps_missing": _deps_reading(written),
                   #: 稿是从参数来的、从盘上读的、还是没有（2026-10-26 的兜底读盘）。
                   "manuscript_source": manuscript_source,
                   "manuscript_washed": manuscript_washed,
                   "manuscript_wash": dict(manuscript_wash),
                   "changes": list(written.get("changes") or []),
                   "note": ("这一条没有新建行：同一条 statement_full 已在册，而这一笔"
                            "带来的证据档更强（且有凭据）⇒ 秘书把那一条的档位改上去了"
                            f"（{written.get('reason') or ''}）。"
                            "内容面一个字没动；这一笔要改内容，就把差异写进 statement_full "
                            "重新交（正文按规范化比不同才会落新的一行）。")}
            #: 正文超了判档位的读取上限 ⇒ 带上截断读数（见 `_text_truncation_reading`）。
            out.update(trunc_reading)
            if proofs_listed:
                out.update(self._proofs_reading(attach))
                pd = self._write_attached_proof_deps(sec, stmt_now, proofs_listed, attach)
                if pd:
                    out["proof_deps"] = pd
            if attach.get("canonical_written"):
                out["canonical_written"] = True
                out["canonical_history"] = list(attach.get("canonical_history") or [])
                out["note"] += ("这一笔还覆盖了 canonical 正文（`proof_text`）：旧正文整段"
                                "留在行的 `proof_history` 里（sha / at / replaced_by 逐条"
                                "可查）；盖在旧正文上的那一签读侧转 `stale`（待复核），"
                                "写入不因 sha 不符被拒。")
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
            #
            # 2026-10-22 审计后这条分支还要接住第三种合法用途：这一笔带来的是 canonical
            # 正文（`proof_text`），既可能是"登记时还没有证明、现在补上了"，也可能是
            # 改稿。两者都要真写进去；后者还负责把旧正文留进 `proof_history`。
            stmt_dup = str(written.get("stmt_id") or "")
            attach = self._attach_proofs(stmt_dup, proofs_listed,
                                         canonical=str(proof_text or ""),
                                         bits=bits)
            if attach.get("refused"):
                return _refuse(str(attach["refused"]), str(attach.get("reason") or ""),
                               stmt_id=stmt_dup)
            if attach.get("canonical_pending"):
                # 这一笔要写 canonical 而写不进去（没有 store / 行不在）⇒ 必须给一条
                # 明确的拒绝码。折成 duplicate_statement 会让"正文一行没落"看起来
                # 像"这条定理早就登记过了"，而正文去哪了没有任何一格说得出来。
                return _refuse("canonical_not_written",
                               ("这一笔带来的 canonical 正文没有写进库："
                                + str(attach.get("reason") or "没有可写的行")
                                + " ⇒ 盘上那一份 `proof_text` 没有被改动。"
                                "这不是「重复登记」：正文确实交上来了，只是落点不可用"),
                               stmt_id=stmt_dup)
            if attach.get("written"):
                out = {"ok": True, "stmt_id": stmt_dup,
                       "self_authored_review": self._self_authored_reading(self_authored),
                       "source_lit_id": lit_id or None,
                       "quote_verified": quote_verified, "origin": origin,
                       "quote_mode": str(quote_mode or ""),
                       "evidence_kind": evidence_kind, "new_row": False,
                       #: 依赖面建起来没有（三态；见 `_deps_missing_reading`）。
                       "deps_missing": _deps_reading(written),
                       #: 稿是从参数来的、从盘上读的、还是没有（2026-10-26 的兜底读盘）。
                       "manuscript_source": manuscript_source,
                       "manuscript_washed": manuscript_washed,
                       "manuscript_wash": dict(manuscript_wash),
                       "note": ("这一条没有新建行（同一条命题已在册）。")}
                #: 正文超了判档位的读取上限 ⇒ 带上截断读数（见 `_text_truncation_reading`）。
                out.update(trunc_reading)
                if attach.get("canonical_written"):
                    out["canonical_written"] = True
                    out["canonical_history"] = list(attach.get("canonical_history") or [])
                    out["note"] += (
                        "这一笔带来的 canonical 正文已经写进 `proof_text`：旧正文整段留在"
                        "行的 `proof_history` 里（每条 `{text, sha, at, replaced_by}`，"
                        "`sha` 能与签名台账的 `proof_sha256` 直接对上）；盖在旧正文上的"
                        "那一签读侧转 `stale`（待复核），写入不因 sha 不符被拒。")
                if proofs_listed:
                    out["note"] += ("这一笔带来的证明清单也挂上去了：清单是追加式的，"
                                    "#p1 是行上的 `proof_text`，其余在 "
                                    f"`{_VR.PROOFS_KEY}` 里。")
                if attach.get("formal_synced"):
                    # 第 4 位（二维）这一笔真的变了：说清它现在是哪几条路径、各是什么。
                    # 这是 D28 的可见面 —— 改前这一位没有任何写者，L 验过之后再登记
                    # 一次也不会让它变。
                    out["formal_paths"] = dict(attach.get("formal_paths") or {})
                    out["note"] += (
                        "第 4 位（形式化通过）按 L 的 `experiments` 台账同步了："
                        f"逐条证明的状态 {out['formal_paths']}（键是证明号；"
                        "汇总按任一路径通过就算通过，逐条路径各自独立）。")
                if attach.get("kind_upgraded"):
                    # D-37：这一笔让 `kind` 跟着证据升了 —— 依据与落点一起报出来，
                    # 静默改名与静默不改名同样是坏（读的人要知道它现在为什么叫定理）。
                    trace = dict(attach["kind_upgraded"])
                    out["kind_upgrade"] = trace
                    out["note"] += (
                        f"`kind` 也跟着证据升了：{trace.get('from') or '（空）'} → "
                        f"{trace.get('to')}（依据：{trace.get('basis') or ''}）。")
                out.update(self._proofs_reading(attach))
                if proofs_listed:
                    # 刚挂上去的那几份证明的依赖面：不补这一笔，它们引用的东西一条都
                    # 不进依赖图（返回里也读不到），而"这条定理有几条不同的证明路径"
                    # 在依赖面上就永远只有 #p1 一条。
                    pd = self._write_attached_proof_deps(sec, stmt_dup, proofs_listed, attach)
                    if pd:
                        out["proof_deps"] = pd
                return out
            if proofs_listed and not attach.get("already"):
                return _refuse("proofs_not_attached",
                               str(attach.get("reason") or "证明清单没挂上"),
                               stmt_id=stmt_dup)
            # 对调用方来说这是"这一次没有新行"，必须说出来（`ok=False` + `kind`），
            # 并把既有那一条的号给它 —— 否则它只会看到"没写成"而不知道东西在哪。
            #
            # 2026-10-26：这段拒信改前写着"确实要另起一条才走 `force_new`（本动作不暴露它）"。
            # 指一个本动作根本没有的参数，等于把模型送去撞 invalid_params —— 拒信要能把模型
            # 指回正路，指的必须是这条动作上真有的做法：同一条命题的第 2 份及以后的证明走
            # `proofs=[{proof_no: N, text: …}]`；确实是另一条命题就把差异写进
            # `statement_full`（正文按规范化比不同才会落新的一行）。
            return _refuse("duplicate_statement",
                           "同一条命题（按规范化后的 statement_full 比）已在册 ⇒ "
                           "秘书查重后没有新建行；要引用它请用返回的 stmt_id。"
                           "同一命题的第 2 份及以后的证明走 `proofs=[{proof_no: N, text: …}]`"
                           "（`#p1` 是行上的 `proof_text`）；确实是另一条命题就把差异写进 "
                           "`statement_full` —— 正文按规范化比不同才会落新的一行。"
                           "这条动作的参数表就是上面出现的这几个，别给别的名字"
                           # D-37：秘书那一支留下的"还差什么"（`kind` 没升成、
                           # 档位没升成）必须转到这里来 —— 折成一句"重复登记"会把
                           # "再去拿一份证据"说成"不用再交一次"。
                           + (str(written.get("reason") or "")
                              if str(written.get("reason") or "").strip() else "")
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
                                     canonical=str(proof_text or ""),
                                     bits=bits)
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
        #: 刚挂上去的那几份证明（#p2 及以后）的依赖面：秘书那一条正路只扫 `proof_text`
        #: （#p1），这里把它补上 —— 一行都没有补的时候返回空字典（老返回值逐字不变）。
        proof_deps = self._write_attached_proof_deps(sec, stmt_id, proofs_listed, attach)
        #: note 里报的那一档等级以盘上那一行为准：这一笔可能把第 4 位（形式化，二维）
        #: 同步进去了，而 `bits` 是同步之前算的。
        written_grade = str(bits.get("grade") or "")
        if attach.get("formal_synced"):
            written_grade = str(_EB.bits_from_row(data).get("grade") or written_grade)
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
                #: B-3 的写侧读数：这一笔要不要 V 的签、有没有拿到（见 `_self_authored_gate`）。
                "self_authored_review": self._self_authored_reading(self_authored),
                "quote_verified": quote_verified, "origin": origin,
                "quote_mode": str(quote_mode or ""),
                #: 判档位那一趟读不完这条正文时的那三格（空字典 = 读得完；见
                #: `_text_truncation_reading`）。业主口径：截断要显式报，不许记成"材料不足"。
                **trunc_reading,
                "quote_span": str(quote_span or ""),
                #: 写侧断言（D1）的读数：`action` 只有 `keep` 与 `downgrade` 两档
                #: （`refuse` 那一档走 `_refuse` 返回，到不了这里）。降档必须看得见 ——
                #: 静默把一句"通过了"改成 unknown 与静默放过它同样是坏。
                "quote_evidence": evidence_reading,
                "evidence_kind": evidence_kind, "row": data,
                #: 命题同一性那一趟判定的读数（业主 2026-10-24：「让秘书洗定理名，让秘书
                #: 判」）：三态 + 判词 + 洗过的定理名 + "原标签 → 定理名" + 标签里被洗掉的
                #: 那条路线（它落在第 1 份证明上，没有丢）。判 different / unknown 时
                #: `adjudication.verdict` 就是那个结论，`basis` 是"凭什么是它"。
                "adjudication": dict(written.get("adjudication") or {}),
                "canonical_name": str(written.get("canonical_name") or ""),
                "label_washed": dict(written.get("label_washed") or {}),
                "proof_route": str(written.get("proof_route") or ""),
                "deps_state": str(written.get("deps_state") or ""),
                "deps_written": int(written.get("deps_written") or 0),
                "deps_dangling": list(written.get("deps_dangling") or []),
                "deps_unmappable": list(written.get("deps_unmappable") or []),
                #: 依赖面建起来没有（三态）：带证明正文而一条依赖都没落 ⇒ `state=missing`
                #: （改前这件事只活在 `deps_written=0` 里，没有任何一格会因此变红 ——
                #: 真机 sylow3 七条命题、依赖全表 0 行，就是静默过去的）。
                "deps_missing": _deps_reading(written),
                #: 稿是从参数来的、从盘上读的、还是没有（2026-10-26 的兜底读盘）：
                #: 这一格让"没人传参"与"B 按约定路径读到了"在读数上分得开。
                "manuscript_source": manuscript_source,
                "manuscript_washed": manuscript_washed,
                "manuscript_wash": dict(manuscript_wash),
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
                #: 第 2 份及以后那几份证明的依赖面（刚挂上去的那几份才扫）：只在真写了
                #: 这一格时出现 —— 老写法的返回值逐字不变。
                **({"proof_deps": dict(proof_deps)} if proof_deps else {}),
                #: canonical 正文在"新建行"这一支上被 `_attach_proofs` 覆盖时（少见：
                #: 秘书落下的 `proof_text` 与这一笔交来的不同），旧正文的留痕也一并给出来。
                **({"canonical_written": True,
                    "canonical_history": list(attach.get("canonical_history") or [])}
                   if attach.get("canonical_written") else {}),
                #: D-37：这一笔让 `kind` 跟着证据升了（依据逐字在里面）。只在真升时出现。
                **({"kind_upgrade": dict(attach["kind_upgraded"])}
                   if attach.get("kind_upgraded") else {}),
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
                         f"{written_grade}；第 2 位来源 "
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
                            if proofs_listed else "")
                         + ("第 4 位（形式化通过）按 L 的 `experiments` 台账同步了："
                            f"逐条证明的状态 {attach.get('formal_paths')}"
                            "（键是证明号；汇总按任一路径通过就算通过）。"
                            if attach.get("formal_synced") else ""))}

    # ------------------------------------------------- 收方读稿登记（D 携带来的那一份）
    #
    # 业主 2026-10-26 晚的原话：「D 到 B 没有路吗？加」+「把稿交给 B」。
    # 这一支是那条路在 B 侧的落点：D 的代码直接调 `B.register_statement(...)`，
    # 命题已经在册（F 落的行）⇒ 不新建、不重判档位，只把这一份手稿的依赖段落成边。

    def _existing_statement_for(self, full: str) -> dict | None:
        """按 `statement_full` 的规范化值找在册那一行（"是不是同一条"的唯一判据在
        `textutil.normalize` —— 与秘书查重同一处口径，这里不另写一份比法）。

        读不到 `statements` 时返回 None（走正常那一支）：那是"没查成"，而这一支
        只在"确认已经在册"时才提前返回 —— 查不成时不许假装它在册。
        """
        from .. import textutil as T

        key = T.normalize(str(full or ""))
        if not key:
            return None
        try:
            rows = [dict(r) for r in self.store.rows("statements")]
        except Exception:  # noqa: BLE001 —— 读不到 ⇒ 走正常那一支（不猜它在册）
            return None
        for row in rows:
            if T.normalize(str(row.get("statement_full") or "")) == key:
                return row
        return None

    def _receive_carried_manuscript(self, row: Mapping[str, Any], *, deps_groups: Any,
                                    manuscript: Mapping[str, Any],
                                    manuscript_refs: Sequence[str],
                                    manuscript_source: str, manuscript_washed: bool,
                                    manuscript_wash: Mapping[str, Any],
                                    proofs: Sequence[Mapping[str, Any]],
                                    proof_text: str,
                                    deps_reading: Any) -> dict:
        """收下 D 递来的那一份稿：命题行不动，只把依赖面写进 `dependencies`。

        `deps_groups` 是上面那块已经解析并逐条核过档位的步骤（外层 = 路径组）；
        写盘走秘书（`record_manuscript_dependency_face`，B 是写者、秘书是执行者），
        幂等（同一路径组、同一来源已经在表里就不再落）。
        """
        stmt_id = str(row.get("stmt_id") or "")
        sec = self._statement_secretary()
        if sec is None:
            return _refuse("secretary_unavailable",
                           "这一趟没有秘书 ⇒ 收下的稿写不进依赖面（不许退回'B 自己写'）："
                           + (f"{self.secretary_problem}" if self.secretary_problem else ""))
        written = dict(sec.record_manuscript_dependency_face(
            stmt_id, deps_groups, note="b.receive_carried_manuscript") or {})
        if not written.get("checked"):
            return _refuse(str(written.get("refused") or "dependency_face_not_written"),
                           str(written.get("reason") or ""))
        reading = deps_reading({"stmt_id": stmt_id,
                                "deps_written": int(written.get("deps_written") or 0)})
        received_proofs = [{"proof_no": int(e.get("proof_no") or 0)}
                           for e in (proofs or []) if isinstance(e, Mapping)]
        note = ("收方读稿登记：命题行不动（这条命题已经在册），只把这份手稿的依赖段落成 "
                "`dependencies`（收方 = B，执行者 = 秘书）")
        if written.get("duplicates"):
            note += (f"；这一遍有 {len(written['duplicates'])} 条已经在表里（幂等，没有重复落）")
        if written.get("deps_written"):
            note += f"；这一遍新落 {int(written['deps_written'])} 条依赖边"
        return {"ok": True, "stmt_id": stmt_id, "new_row": False, "received_manuscript": True,
                "manuscript_source": manuscript_source,
                "manuscript_washed": bool(manuscript_washed),
                "manuscript_wash": dict(manuscript_wash),
                "deps_written": int(written.get("deps_written") or 0),
                "deps_duplicates": [dict(x) for x in (written.get("duplicates") or [])],
                #: 依赖面建起来没有（三态；与新建那一支同一份读数实现）。
                "deps_missing": reading,
                "proofs_received": received_proofs,
                "refs_in_proof": list(manuscript_refs),
                "row": dict(row), "note": note}

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

    # ---------------------------------------------------------------- 业主 B-3（2026-10-22）
    #
    # 裁定逐字：「B 侧自己杜撰定理与证明时，也必须给 V 看才能落库，否则按瞎编处理。」
    #
    # 为什么落在写入口而不是收工门：收工门 R10 是事后读数（它只把结论记成 rejected），
    # 运行期零后果 —— 一条自己编的「定理」在盘上照样 status=active、grade=conjecture，
    # 而下游（G 的正文、H 的审稿、D 的手稿）读的是那一行。闸必须在「进库之前」。
    #
    # 与 B-2（「无引文的必须从猜想注册」）的分工写在一处（判定顺序）：
    #   1. `kind="concept"` ⇒ 概念行先短路（来源分档那一套在更上面）；
    #   2. `kind="conjecture"` ⇒ 猜想放行（猜想本来就要先落库才审得动：V 只审在册的命题）；
    #   3. `origin=own_result` 或 `source_lit_id` 空 ⇒ 判「杜撰」，要 V 的签；
    #   4. 有签 ⇒ 放行（读数进返回值）；没有 ⇒ `self_authored_needs_v`。
    # 于是「从猜想升成 theorem/lemma 的那一步」才是要签的那一步，而「按猜想注册」不受阻。

    #: 不受这条闸管束的两种 kind：猜想（先落库才审得动）与概念（不走等级链）。
    _NON_THEOREM_KINDS: tuple[str, ...] = ("conjecture", "concept")

    #: 这条闸的受控拒绝码（调用方据它分辨「参数不对」与「还欠 V 一签」）。
    SELF_AUTHORED_NEEDS_V = "self_authored_needs_v"

    def _report_index_rows(self) -> list[dict]:
        """D 报告的目录行（论文对应表那几行；读不到 ⇒ 空清单，不猜）。

        ## 为什么要读它（业主 2026-10-23 夜的模型，D-34）

        「D 侧报告的多半是新成果，B 基本都是从 D 的报告看到定理（命题），经索引看 F 侧证明
        或 E 侧报告，并核实 V 签，然后 B 拿着这些注册定理（命题）入库」——
        于是"顺索引取对象"是 B 的入库里一个正常的步骤，不是可选的附加校验。
        索引的落点与列义只有一份（`papermapping` 的那张表 + `numericproof.INDEX_*`），
        这里只做一次读。

        三态：读不到（没有 `MAPPING.json` / 坏 json）⇒ 空清单 —— 调用方（`filing_problems`）
        把它读成"目录里没有这一条"，于是索引那一路取不到对象、闸照旧拒。
        这不是把"没查成"折成"通过"：折的方向是拒。
        """
        store = getattr(self, "store", None)
        root = getattr(store, "root", None) if store is not None else None
        if root is None:
            # 三态：读不到工作区根 ⇒ 空清单，折向「拒」（不是「没有这一条」）
            return []
        try:
            from .. import papermapping as _PM
        except Exception:  # noqa: BLE001 —— 那一侧读不到就是"没有目录"
            return []
        try:
            return list(_PM.index_rows(root))
        except Exception:  # noqa: BLE001 —— 坏 json / 读不出来 ⇒ 同上
            return []

    def _v_signature_for(self, *, statement_full: str, proof_text: str) -> dict:
        """这一条自产命题有没有「V 签成立、且盖的正是这一份正文」的签（纯读）。

        ## 判据只有一处
        `verifications.statement_review_reading`（与收工门 R10、`closing` 的收工读数
        同一个函数）：它逐条证明回答「现在这一份正文最近那一签是什么」。这里只做两件
        事 —— 先按正文认出「同一条命题在册的那一行」，再在它的逐条读数里找
        `reviewed=True` 且 `proof_sha256` 等于这一份正文的那些。

        ## 为什么按正文认命题（而不是按编号）
        `register_statement` 在写库之前没有号（号是秘书在事务里现发的），而 V 只审在册
        的命题（`AgentV.verify_proof` 对不在册的命题直接 `statement_missing`）。所以
        「这一条有没有签」只能问「册上那条同文的命题有没有签」—— 按号问的话，第一次
        登记永远问不到，闸就变成了不可能通过的死闸。

        ## 不许借光
        sha 必须与这一份正文相符：别的命题的签、同一命题另一份证明的签、盖在改稿前
        旧版上的签，一律不算（`statement_review_reading` 的 `stale` 那一档正是这个）。

        ## 三态
        `checked=False` = 没查成（没有 store / 表读不出来 / 台账读不出来）——
        它不等于「没有签」，而调用方对两者的处理都是「不许落成定理级」，但拒信不同。
        """
        from .. import statementbody as _SB
        from .. import textutil as _T
        from .. import verifications as VR

        out: dict = {"checked": False, "signed": False, "stmt_id": "",
                     "verification_id": "", "proof_sha256": "", "in_ledger": False,
                     "why": ""}
        store = getattr(self, "store", None)
        if store is None:
            out["why"] = ("没查成：这一趟没有 store，读不到本工作区的 statements / "
                          "verifications ⇒ 判不了这一条有没有 V 的签（不许当成签过）")
            return out
        want = str(proof_text or "")
        if not want.strip():
            out.update(checked=True,
                       why=("这一条没有证明正文 ⇒ 不可能有盖住它的签："
                            "V 审的是证明，不是命题标题"))
            return out
        root = getattr(store, "root", None)
        key = _T.normalize(statement_full)
        try:
            rows = [dict(r) for r in store.rows("statements")]
        except Exception as exc:  # noqa: BLE001 —— 读不到要如实说，不许当成通过
            out["why"] = (f"没查成：statements 读不出来（{type(exc).__name__}: {exc}）"
                          "⇒ 判不了这一条有没有 V 的签")
            return out
        sha = VR.proof_sha(want)
        out["proof_sha256"] = sha
        same = [r for r in rows
                if str(r.get("kind") or "") != "concept"
                and _T.normalize(_SB.body_of(r)) == key]
        out["in_ledger"] = bool(same)
        if not same:
            out.update(checked=True,
                       why=("命题台账里没有同一条命题 ⇒ 它还没登记过，V 也就没处签它："
                            "先按猜想注册（kind=\"conjecture\"），再把它交给 V"))
            return out
        out["checked"] = True
        for row in same:
            sid = str(row.get("stmt_id") or "")
            try:
                reading = VR.statement_review_reading(root, row)
            except Exception as exc:  # noqa: BLE001
                out.update(checked=False,
                           why=(f"{sid} 的第 3 位读数没读成（{type(exc).__name__}: {exc}）"
                                "⇒ 没查成，不是「没有签」"))
                continue
            if not reading.get("checked"):
                out.update(checked=False,
                           why=(f"{sid} 的验证台账读不出来 ⇒ 第 3 位没查成"
                                f"（{str(reading.get('why') or '')[:160]}）"))
                continue
            for item in reading.get("proofs") or []:
                if not bool(item.get("reviewed")):
                    continue
                if str(item.get("proof_sha256") or "") != sha:
                    continue
                out.update(signed=True, stmt_id=sid,
                           verification_id=str(item.get("verification_id") or ""),
                           why=(f"{item.get('verification_id')} 签「成立」、且 proof_sha256 "
                                f"与这一份正文相符（verifications/{sid}.jsonl）"))
                return out
            out["why"] = (f"在册的那一条（{sid}）没有盖住这一份正文的「成立」签："
                          f"{str(reading.get('why') or '')[:200]}")
        # ---- D-34：命题登记之前审的那一签不丢（按内容 sha 认领）
        #
        # r34b 的真机现场：`statements` 0 行时 V 审完只能报 `statement_missing`，那一签
        # 没有落点。现在它落在 `verifications/pending/<sha>.jsonl`；命题后来登记上了，
        # 而"先签后登记"与"先登记后签"必须是同一件事 ⇒ 这一格按这一份正文的 sha
        # 去 pending 里认领。认不到就还是没签（`out["why"]` 里已经写着为什么）。
        try:
            pending = VR.pending_sign(getattr(self.store, "root", None) or "",
                                      proof_shas=(sha,))
        except Exception as exc:  # noqa: BLE001 —— pending 读不动 ⇒ 没查成，不是"没有签"
            out.update(checked=False,
                       why=(f"`verifications/{VR.PENDING_DIR_NAME}/` 读不出来"
                            f"（{type(exc).__name__}: {exc}）⇒ 第 3 位没查成"))
            return out
        if pending.get("found") and str(pending.get("verdict") or "") == "成立":
            out.update(signed=True,
                       stmt_id=str(out.get("stmt_id") or ""),
                       verification_id=str(pending.get("ledger") or "").split("#")[-1],
                       why=(f"{pending.get('ledger')} 是命题还没在册时 V 审的那一签"
                            f"（verdict={pending.get('verdict')!r}）—— 按这一份正文的 sha "
                            "认领到，于是「先签后登记」与「先登记后签」是同一件事"))
            return out
        if pending.get("found"):
            out["why"] = (f"命题还没在册时 V 审过这一份，但那一签的结论是 "
                          f"{pending.get('verdict')!r}（不是「成立」）⇒ 这一条仍没有签住")
        return out

    def _e_signed_exhaustion(self, proof_text: Any) -> dict | None:
        """这条命题的证明栏是不是「一条 E 已按穷举签下的 proof」的程序路径。

        2026-10-23 业主裁定（逐字要点）：「这些有关数值实验的都由 E 来签」→ 随后更正为
        「签字仍然由 V 签（不是 E）。E 是 ②③ 的原作者，但签名主体是 V」；「若要入定理
        证明库，证明栏写程序地址（相对于仓库）」。⇒ 这一类命题的第三方签名是 V 的那一签
        （材料是 E 写的那一份程序 + ②③），不是 V 的逐行走查（逐行走查对数值证据不适用，
        见 `numericproof.verifier_problems`）。
        本方法只做一次查表，判据本体在 `numericproof.find_signed_exhaustion_for_column`。
        """
        rows: list = []
        try:
            rows = list(self.store.rows("experiments"))
        except Exception:  # noqa: BLE001 —— 读不到台账就是"没有这一签"（不许当成有）
            rows = []
        return _NP.find_signed_exhaustion_for_column(rows, proof_text)

    def _self_authored_gate(self, *, origin: str, kind: str, lit_id: str,
                            statement_full: str, proof_text: str) -> dict:
        """业主 B-3 的写侧闸：自产的定理级命题要么有 V 的签，要么受控拒绝。

        返回 `{"needs_v": bool, "refused": str, "reason": str, "reading": {...}}`：
        - `needs_v=False` + `refused=""` ⇒ 这一条不在闸的射程里（概念 / 猜想 / 有文献出处），
          `reading` 里写清为什么（别让调用方以为「查了、通过了」）；
        - `needs_v=True` + `refused=""` ⇒ 在射程里、而且真有一份 V 的签（正控）；
        - `needs_v=True` + `refused=self_authored_needs_v` ⇒ 在射程里、没有签（拒收）。

        「杜撰」的判定口径逐字来自裁定：`origin="own_result"`（我方自产）或
        `source_lit_id` 空。后者在本动作里与前者等价（`external_lit` 缺出处更上面就被
        拒了），但两件都判 —— 判据要读的是「有没有出处」，不是「调用方有没有声明」。

        ## 与 B-2（「无引文的必须从猜想注册」）的判定顺序（六档，逐条如此）

        两条裁定覆盖同一类输入（自产 / 无出处 / 定理级 / 没有 V 的签），所以顺序就是
        口径本身。按下面的次序判，先命中哪一档就按哪一档处置：

        1. `kind="concept"` ⇒ 概念行短路（概念不参与等级链，
           `evidencebits.derive_grade` 对它短路）；
        2. `kind="conjecture"` ⇒ 这一闸不管，猜想照常注册（猜想本来就要先落库才审得动：
           V 的 `verify_proof` 对不在册的命题直接报 `statement_missing`）；
        3. 自产（`origin="own_result"` 或 `source_lit_id` 空）+ 定理级 + 册上还没有
           同一条命题 ⇒ 这一档的拒收码用 B-2 的那个 `must_start_as_conjecture`
           （调用点在 `register_statement` 里：B-2 的白名单与拒信函数先返回）；
        4. 同上、但册上已经有同一条命题（先立成猜想、现在来声明 theorem / lemma）⇒
           `self_authored_needs_v`：这一刻缺的不是「换个 kind」，是 V 的那一签；
        5. 有 V 的「成立」签、且 `proof_sha256` 与这一份正文相符 ⇒ 两闸都放行，
           B-2 那道无状态的闸也一并让路（判据是 `reviewed` 为真且 sha 相符）；
        6. `origin="external_lit"` 且 `source_lit_id` 非空 ⇒ 不在射程（那不是我们杜撰的）。

        一句话：猜想注册不受阻；「从猜想升成定理」的那一步才要 V 签，而这一步的拒收码
        就是 `self_authored_needs_v`。第 3 与第 4 档的分界是「册上有没有同一条命题」
        （`_v_signature_for` 的 `in_ledger`），不是 `kind` 的另一种写法 —— 同一个
        theorem 在「首次登记」和「升档」两个阶段欠的东西不一样。
        """
        kind_now = str(kind or "theorem").strip()
        reading: dict = {"checked": True, "needs_v": False, "signed": False,
                         "in_ledger": False,
                         "kind": kind_now, "origin": str(origin or ""),
                         "source_lit_id": str(lit_id or ""), "stmt_id": "",
                         "verification_id": "", "why": ""}
        if kind_now in self._NON_THEOREM_KINDS:
            reading["why"] = (
                f"kind={kind_now!r} 不在这一条闸的射程里："
                + ("猜想本来就要先落库才审得动（V 只审在册的命题）⇒ 按猜想注册不受阻，"
                   "从猜想升成 theorem/lemma 的那一步才要 V 的签"
                   if kind_now == "conjecture" else
                   "概念不走等级链（`evidencebits.derive_grade` 对它短路）"))
            return {"needs_v": False, "refused": "", "reason": "", "reading": reading}
        self_authored = (str(origin) == "own_result") or not str(lit_id or "").strip()
        if not self_authored:
            reading["why"] = ("有文献出处（origin=external_lit 且 source_lit_id 非空）⇒ "
                              "这一条不是我们杜撰的，闸不拦它")
            return {"needs_v": False, "refused": "", "reason": "", "reading": reading}
        # 2026-10-23（业主裁定）：数值证据的签名主体是 V、②③ 的作者是 E。证明栏写程序路径、
        # 且台账里有一条对应的穷举证明 ⇒ 这一条的第三方签名已经在盘上了，不要再向它要 V 的
        # 逐行走查 —— 逐行走查对数值证据本来就不适用（`numericproof.verifier_problems`），
        # 两条闸叠在一起会让一条真的穷举证明永远进不了定理证明库。
        if self._e_signed_exhaustion(proof_text) is not None:
            reading.update(
                checked=True, needs_v=False, signed=True,
                why=(f"这一份的证明栏是程序 {str(proof_text or '')[:60]!r}，台账里有它对应的 "
                     "穷举证明（signed_by=V、proof_authors 含 E、proof_reason=exhaustion）⇒ "
                     "数值证据由 V 签、②③ 由 E 写，不需要 V 的逐行走查"))
            return {"needs_v": False, "refused": "", "reason": "", "reading": reading}
        sig = self._v_signature_for(statement_full=statement_full, proof_text=proof_text)
        reading.update(
            checked=bool(sig.get("checked")),
            needs_v=True,
            signed=bool(sig.get("signed")),
            in_ledger=bool(sig.get("in_ledger")),
            stmt_id=str(sig.get("stmt_id") or ""),
            verification_id=str(sig.get("verification_id") or ""),
            proof_sha256=str(sig.get("proof_sha256") or ""),
            why=str(sig.get("why") or ""))
        if sig.get("signed"):
            return {"needs_v": True, "refused": "", "reason": "", "reading": reading}
        reason = (
            f"自产的定理级命题（kind={kind_now!r}、origin={str(origin)!r}、"
            f"source_lit_id={str(lit_id or '')!r}）在 V 的台账里没有一份「成立」的签盖住"
            f"这一份正文（proof_sha256={str(sig.get('proof_sha256') or '')[:12]}…）⇒ 整笔不写"
            f"（业主 2026-10-22 B-3：「B 侧自己杜撰定理与证明时，也必须给 V 看才能落库，"
            f"否则按瞎编处理」）。查的结果：{str(sig.get('why') or '（没有读数）')}。"
            "两条路都不堵：① 按猜想注册：把 kind 改成 \"conjecture\"（证明正文照交）—— "
            "猜想不受这条闸管，落库之后它才审得动；② 先送 V：唤起 V 的 `verify.verify_proof` "
            "走查这一份，V 签「成立」之后把同一份内容再交一次、kind 改回定理级"
            "（档位给 evidence_kind=\"proof_review\"），那时这条闸会放行。"
            "不许拿别的命题的签来顶（sha 必须与这一份正文相符），也不许绕开 V 直接当定理用。")
        return {"needs_v": True, "refused": self.SELF_AUTHORED_NEEDS_V,
                "reason": reason, "reading": reading}

    def _self_authored_reading(self, gate: Mapping) -> dict:
        """把闸的读数摊成返回值里的一格（`self_authored_review`）。

        为什么成功路径也要给：这一笔能落库，可能因为「它不在射程里」（猜想 / 有出处），
        也可能因为「它真有一份 V 的签」。两种情况在盘上长得不一样，而调用方（B 自己的
        下一轮）需要知道自己是哪一种 —— 只给一个 `ok=True` 就等于让它去猜。
        """
        got = dict(gate or {})
        return {"needs_v": bool(got.get("needs_v")),
                "signed": bool((got.get("reading") or {}).get("signed")),
                "in_ledger": bool((got.get("reading") or {}).get("in_ledger")),
                "checked": bool((got.get("reading") or {}).get("checked")),
                "verification_id": str((got.get("reading") or {}).get("verification_id") or ""),
                "why": str((got.get("reading") or {}).get("why") or "")}
