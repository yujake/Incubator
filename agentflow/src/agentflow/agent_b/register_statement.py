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

from pathlib import Path
from typing import Mapping, Sequence

from ._support import S
from ._support import _is_manuscript_rel, _norm_manuscript_rel
from .ingest_manuscript import _IngestManuscript
from .land_manuscript import _LandManuscript
from .. import depsection as _DS
from .. import evidencebits as _EB
from .. import manuscriptfamily as _MFAM  # 手稿族/号/后缀的唯一判定表（T2）
from .. import manuscriptintake as _MI   # 逐格提取与冲突矩阵的纯函数核（T1）
from .. import numericproof as _NP
from .. import quoteevidence as QE
from .. import refusals as _R
from .. import statementledger as SL   # 命题台账的查口（按号 / 按关键词，只读、零模型）
from .. import verifications as _VR
from .. import proofregistry as _PR
from ..refusals import refuse as _refuse

#: 一条命题一开始允许声明成的那几个 kind（业主 2026-10-22 裁定 B-2）。
#:
#: 裁定原文：「没有引文 / 自己编的命题必须从『猜想』注册」。于是
#: `origin="own_result"` + 没有 `source_lit_id` + `quote_verified` 不是 True 的那一笔，
#: 只允许以 `conjecture`（猜想）或 `concept`（概念行不参与等级链）登记；写成
#: theorem / lemma / proposition 一律受控拒绝 `must_start_as_conjecture`。
#:
#: 为什么是一张白名单而不是"拒掉 theorem/lemma/proposition"：等级链的词表会变
#: （加一个取值就是加一种"强于猜想"的说法），黑名单会在那种时候
#: 静默放行 —— 白名单不会。
CONJECTURE_START_KINDS: tuple[str, ...] = ("conjecture", "concept")

#: 「一次能给几条候选」的工程上限住在秘书那一侧（`secretary.PROPOSITION_VERDICT_CANDIDATES`）：
#: B 不再自建检索、也不再自己分批（2026-11-08 缺陷 ②：检索路只留秘书那一条）。
#: 这里一个字都不留 —— 留一个"B 的分批大小"等于把第二条检索路的骨架留在原处。


#: 派生列：调用方永远不许指定（设计 §2.5）。它们不在 `INGEST_CELLS` 里；
#: 单独列出来是为了"请求了派生列"能给出受控拒，而不是一句泛泛的参数错。
#: 理由：这些要么由秘书洗（`label`）、要么由签现算（`evidence_kind` / 等级）、
#: 要么是写口回执（号 / sha）—— 让调用方指定等于把"自报"重新引回来。
DERIVED_COLUMNS: tuple[str, ...] = (
    "label", "evidence_kind", "origin", "line_range", "doc_id", "bits",
    "proof_no", "proof_sha256", "proof_authors", "proof_history", "stmt_id",
)


def _should_promote_to_formal(rel: str) -> bool:
    """这一份稿该不该在"登记成功"那一刻转成 `reports/f-proof-<号>.md`。

    三种情形不转：已经是按号命名的正式稿（目标就是它自己）、B 的改写稿
    （`reports/b-proof-*` —— 那不是 F 的稿）、以及不认识的路径。

    2026-11-09（T2 收编，设计 3.2 附）：族判定改读 `manuscriptfamily.classify_manuscript`，
    不再手写前缀比较。行为逐字不变：

    - `reports/f-proof-plan-<计划号>.md` ⇒ 转（立项那一轮还没有命题号）；
    - `reports/f-proof-<号>.md` ⇒ 不转（已经是正式稿）；
    - `reports/{b,e}-proof-*` / `reports/e-num-*` ⇒ 不转（不是 F 的稿）；
    - `notes/…` ⇒ 转（作者的攻坚稿；`notes/` 里名字不像手稿的也照旧转）。
    """
    text = _norm_manuscript_rel(rel)
    if not text:
        return False
    reading = _MFAM.classify_manuscript(text)
    if reading.get("tier") == _MFAM.TIER_FAMILY:
        if reading.get("family") != "f-proof":
            return False
        return str(reading.get("id") or "").startswith("plan-")
    return text.startswith("notes/")


#: D 交稿只许递指针（业主 2026-11-08 逐字）：
#:
#: > 「D对命题台账只有只读权限，D向B提交要登记的命题时都是有证明或数值实验的
#: >   （即E和F的成果）…B侧做好适配（应该在手稿里找命题和数值实验程序，不录入其它内容）」
#:
#: 所以 D 这一侧只给三样指针：手稿工作区相对路径（`proof_manuscript`）、
#: 命题号 / 实验号、出处（`exp:<号>`）。命题正文、证明正文、`kind`、`evidence_kind`
#: 一律由 B 从那份稿里读（`_register_pointer_manuscript`）—— D 把它们抄进参数
#: 就是"把手稿内容转手一遍"，而转手的那一份没有任何东西保证它与稿逐字相同。
#:
#: 这一档的受控码。为什么它必须是一个可读的码而不是一句散文：调用方（D 的模型）
#: 要据此改参数，而 `ok=False` 会被终态映射记成 `refused / invalid_params`（`refusals.refuse`）。
D_POINTER_ONLY_REFUSAL = "d_gives_manuscript_pointers_only"

#: D 传了任何一个就算"递的是正文"的参数（名，人话名）—— 桩点就是这张表。
#:
#: 为什么按"非空"判、不按"传没传"判：`register_statement` 的形参有默认值
#: （`kind=""` / `origin=""` / `evidence_kind=""` …），Python 分不出"显式传了空串"
#: 与"没传"；而"传了空串"与"没传"在语义上是同一件事（都没有内容）。这条闸要拦的是
#: 有内容的那一份，所以判非空就够了，且不会把"显式给空"误判成违规。
_POINTER_ONLY_BODY_FIELDS: tuple[tuple[str, str], ...] = (
    ("statement_full", "命题正文"),
    ("statement_text", "命题短版"),
    ("proof_text", "证明正文"),
    ("proofs", "证明清单"),
    ("kind", "kind"),
    ("evidence_kind", "evidence_kind"),
    ("origin", "origin"),
    ("quote_reason", "引文理由"),
    ("label", "标签"),
    ("derived_from", "承重链"),
    ("doc_id", "doc_id"),
    ("source_lit_id", "来源文献"),
    ("page_range", "页码"),
    ("quote_verified", "引文回验"),
    ("quote_mode", "回验方式"),
    ("quote_span", "引文片段"),
    ("quote_call_sha256", "语义判定指纹"),
)


def _pointer_body_present(name: str, value: Any) -> bool:
    """这一格 D 有没有给出"正文类"的内容（见 `_POINTER_ONLY_BODY_FIELDS`）。"""
    if name in ("proofs", "derived_from"):
        return bool(list(value or ()))
    if name == "page_range":
        return bool(dict(value or {}))
    if name == "quote_verified":
        return value is not None
    return bool(str(value or "").strip())


def _caller_is_d() -> bool:
    """这一笔的发起方是不是 D（B 的直调上下文里 `current_caller_role()`；被 D 召唤时是父角色）。

    两个都要读：D 的代码（`write_report`）直接调 B 的方法时，挂点是"我是 D"；
    而 D 用 `summon` 派 B 时，B 自己的任务上下文里 `_caller_role()` 才是 D。
    """
    roles: set[str] = set()
    try:
        from ..conductor import current_caller_role

        roles.add(str(current_caller_role() or ""))
    except Exception:  # noqa: BLE001 —— 读不到挂点 = 没有挂点（不是"D 在调"）
        pass
    roles.add(str(_caller_role() or ""))
    return "D" in roles


def _pointer_manuscript_rel(value: Any) -> str:
    """`proof_manuscript` 是"手稿相对路径"时返回归一后的路径，否则空串。"""
    rel = _norm_manuscript_rel(value)
    return rel if _is_manuscript_rel(rel) else ""


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


def verbatim_vs_source(*, proof_text: Any = None, row: Mapping | None = None,
                       source_text: Any = "", source: str = "") -> dict:
    """这一份证明正文与来源手稿的证明正文是不是逐字一致 —— 信息格，不是门。

    ## 它为什么只能是读数（业主 2026-10-26 Q14）
    收录时把定理与证明"消化"成自然语言是我们的口径（见 `agent_skills` 里 B 的
    「消化」那一节），所以"与来源逐字一致"不可能同时是一道门：它一旦是门，消化本身
    就被判红。逐字只对文献引文要求（`quote_verified` 的比对对象是 `quote_span` 或
    原文那一段），对我们自己的证明不要求 —— 这一格把那个差别留在读数上。

    ## 来源取哪一段
    取 `depsection.proof_body_reading` 切出来的那一节（三态：`present` / `absent`），并
    同时认"整份手稿"这一种写法：有人交上来的就是整份稿（含抬头元信息与 `## 依赖` 表），那
    也是逐字一致 —— 两种都算 same，`matched` 说明对上了哪一段。拿整份手稿当唯一对象
    则会每一条都判"不是逐字"，那种恒假的读数比没有更坏。
    `source_state=absent`（来源稿没有 `## 证明`）⇒ 只剩"整份稿"那一支可比对，
    不拿 `## 依赖` 节的正文或整份全文冒充"证明正文那一节"（2026-11-09，D4）。

    ## 传参的两条路
    `proof_text=` 传这一笔刚交上来的正文；或者 `row=` 传在册那一行、由它读
    `proof_text` —— 两种读法算的是同一件事（判据只有这一处）。

    ## 三态
    `checked=False` = 这一笔没有可比对的来源正文（`same=None`，那是"没有对象"，
    不是"不一致"）；`checked=True` = 比过了，`same` 就是结论。它不拦任何写入。
    """
    text = (str(proof_text) if proof_text is not None
            else str((row or {}).get("proof_text") or ""))
    whole = str(source_text or "")
    reading = _DS.proof_body_reading(whole) if whole.strip() else {}
    src = str(reading.get("body") or "")
    out: dict = {"checked": False, "same": None, "matched": "", "source": str(source or ""),
                 "chars": len(text), "source_chars": len(src), "why": "",
                 #: 来源稿的 `## 证明` 三态（present / absent）。absent 时 `src` 是空串，
                 #: 不拿 `## 依赖` 或整份全文顶替；"整份稿"那一档由下面的第二支显式认。
                 "source_state": str(reading.get("state") or "")}
    if not whole.strip():
        out["why"] = ("这一笔没有可比对的来源正文（没有手稿、也不是从文献引文来的）⇒ "
                      "这一格是「没有对象」，不是「不一致」")
        return out
    out["checked"] = True
    if src.strip() and _same_manuscript_text(text, src):
        out["same"], out["matched"] = True, "proof_body"
    elif _same_manuscript_text(text, whole):
        out["same"], out["matched"] = True, "manuscript"
    else:
        out["same"] = False
    if out["same"]:
        out["why"] = ("与来源手稿逐字相同（只把换行归一，别的一字不改；对上的是 "
                      + ("证明正文那一节" if out["matched"] == "proof_body" else "整份手稿") + "）")
    elif out["source_state"] == _DS.PROOF_ABSENT:
        out["why"] = (f"来源稿里没有 `{_DS.SECTION_PROOF}` 那一节 ⇒ 没有「证明正文那一节」"
                      "可比对（不拿 `## 依赖` 或整份全文顶替），这一笔的正文只能与整份稿比；"
                      "两者不是逐字一致 —— 这不是缺陷：判据只有一条，改写过就要重派 V 签")
    else:
        out["why"] = ("与来源手稿的证明正文不是逐字一致（可能是消化后的自然语言）—— "
                      "这不是缺陷：判据只有一条，改写过就要重派 V 签")
    return out


def _rewrite_note(reading: Mapping) -> str:
    """正文被改写之后要说的那一句话（三个回报点共用一份文案）。

    口径（业主 2026-10-26 Q14）：改写过 ⇒ 旧签作废 ⇒ 派 V 重新签。这句话必须说清
    三件事，否则读的人会自己编一个解释：

    1. "这一签不算数"是读侧现算的结论（唯一判定口 `verifications.review_standing`，
       拿现行正文的 sha 与台账里盖在旧正文上的那一签比），不是框架把签删了 ——
       台账那一行不删、旧签仍可查，只是不再算数；
    2. 真实动作名与形参：`V.verify_proof` 的 `statement_id`（必填）+ `proof_no`
       （要审第几条证明；`#p1` 就是行上的 `proof_text`）；
    3. 没查成（`unreadable`）既不许读成"签过"，也不许读成"没签过"。
    """
    got = dict(reading or {})
    state = str(got.get("state") or "")
    call = ("`V.verify_proof`（`statement_id` 必填；要审第几条证明就带 "
            "`proof_no`；`proof_manuscript` 必须给 —— 在册也要给稿，V 只从稿的 "
            "`## 证明` 读正文、签块也落回稿，如 `reports/f-proof-<命题号>.md` / "
            "B 的改写稿 `reports/b-proof-<命题号>.md`）。")
    where = ("读数是读侧现算的（`verifications.review_standing`：拿现行正文的 sha 与"
             "台账里那一签比）；台账那一行不删、旧签仍然可查，只是不再算数。")
    if state == "signed":
        return "V 的签盖住的就是这一份正文（`review_standing=signed`）⇒ 不用重签。"
    if state == "stale":
        return ("正文被改写过 ⇒ 盖在旧正文上的那一签不算数"
                "（`review_standing=stale`）⇒ 派 V 重新签（建议：请重新拿 V 签）：" + call + where)
    if state == "rejected":
        return ("正文被改写过 ⇒ 现行这一份最近那一签的结论不是「成立」"
                "（`review_standing=rejected`）⇒ 建议：按 findings 改完再送，不要原样重送 —— "
                "改完派 V 重新签：" + call + where)
    if state == "unsigned":
        return ("这一份正文还没有 V 的签（`review_standing=unsigned`）"
                "⇒ 建议：请拿 V 签：" + call)
    return ("这一签现在算不算数没查成（`review_standing=unreadable`）⇒ 不当作签过、"
            "也不当作没签过：先让台账读得出来，再派 V 重新签：" + call)


def _canonical_rewrite_reading(attach: Mapping) -> dict:
    """`_attach_proofs` 里算好的那一格读数摊到返回值上（键名与读侧同一个）。"""
    reading = dict((attach or {}).get("review_standing") or {})
    if not reading:
        return {}
    return {"review_standing": reading,
            "resign_required": bool((attach or {}).get("resign_required"))}


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


def _needs_v_reason(*, sid: str, sha12: str, state: str, verification_id: str = "",
                    streak: int | None = None, need: int | None = None,
                    why: str = "") -> str:
    """`self_authored_needs_v` 那一句：事实 + `建议：` + 一条真的走得通的路（唯一落点）。

    ## 为什么按状态分四句（2026-11-02，业主裁定「一句原因 + 一句建议」）

    `_v_signature_for` 的 `state` 回答的正是"这一版正文现在欠什么"，而四种欠账的
    下一步不是同一件事，写成一句通用文案会把处置说错：

    - `stale`（签过旧版、正文改过）⇒「请重新拿 V 签」。改稿是正确动作，别把它读成
      "你错了"；路径必须写全（先用 `own.land_manuscript` 把这一版落成可签的稿，
      再送 V），因为改后的正文此刻还没上盘 —— 只说"送 V"的那一版照做会撞
      `proof_text_mismatch`（`agent_v/core.py` 的 `verify_proof`：参数给的正文必须与
      盘上那一份同 sha）。D1 之后登记不再顺手落稿，所以这一步要自己说。
    - `unsigned`（一次都没签过）⇒「请拿 V 签」，不说「重新」（还没有旧签可"重新"）。
    - `rejected`（同一份正文被判过「有毛病」）⇒「按 findings 改完再送」，不说「重签」：
      签的还是这份正文，重送一次结论不会变，说「重签」等于教人原样重送。
    - `holding`（签过、判成立、连续次数没到）⇒「再送 V 审够次数」，不必改稿、不必重交。

    ## 可达性

    四句里点名的每一步都在今天的面上（判据
    `tests/test_b_rewrite_without_v_sign_says_resign.py` 的 b 条走的是 f-稿那条等价路，
    D1 的落稿那一步由 `tests/test_b_refused_registration_writes_nothing.py` 的 f 条走）：
    落稿是 `AgentB.land_manuscript`（`own.land_manuscript` 的工具壳由 T1 那一批接线；
    本笔只交 B 本体动作）；`statement_full` / `proof_text` 是 `own.register_statement` 的
    真参数；`verify.verify_proof` 的 `statement_id` / `proof_no` 是 V 的真参数
    （`B → V` 边在 `capabilities.ALLOWED_EDGES` 里）；"连续 3 次"是
    `verifications.SIGN_STREAK_NEED`；签落 `out/vsigns/<被审正文的 sha>.json`
    （`vsigns.SIGNS_DIR`），`kind` 由签名那一笔自动抬（`_kind_upgrade_from_signature`）。
    """
    sid_txt = sid or "（无号）"
    head = f"这一版正文（proof_sha256={sha12}…）"
    #: D1（2026-11-10）：登记不再顺手落稿（被拒的登记盘上零新增）⇒ "先落稿"这一步
    #: 必须自己说清，不能假设盘上已经有这一版。落点是 B 改写稿的规范名。
    _land_step = (
        "① 先让 B 显式落稿（`AgentB.land_manuscript`；工具名 "
        "`own.land_manuscript` 的薄壳待 T1 那批接线，现在还没注册）"
        f"：把这一版落成 reports/b-proof-{sid_txt}.md（登记不再顺手落稿，"
        "被拒的登记盘上零新增）；")
    if state == "stale":
        return (
            f"{head}在 V 的台账里没有盖住它的「成立」签（在册 {sid_txt} 只签过另一版）"
            "⇒ 整笔不写。改稿是正确动作，建议：请重新拿 V 签 —— "
            + _land_step
            + f"② 派 V 用 verify.verify_proof(statement_id=\"{sid_txt}\", proof_no=1, "
            f"proof_manuscript=\"reports/b-proof-{sid_txt}.md\") 审这一份 "
            "（在册也要给稿：V 的正文只从「## 证明」读，签块也落回这份稿）；"
            "③ 签到位后带这份稿重交 own.register_statement（正文换进去，旧正文进 "
            "proof_history；签文件落在 out/vsigns/<新正文sha>.json，kind 自动抬成 theorem）。"
            "禁令：不给 proof_manuscript 的内联正文现在过不了 V"
            "（`proof_text_needs_a_manuscript`），不许拿别的命题的签来顶，"
            "也不许绕开 V 当定理用。")
    if state == "unsigned":
        return (
            f"{head}在 V 的台账里一次都没签过 ⇒ 整笔不写。"
            "建议：请拿 V 签 —— "
            + _land_step
            + f"② 派 V 用 verify.verify_proof(statement_id=\"{sid_txt}\", proof_no=1, "
            f"proof_manuscript=\"reports/b-proof-{sid_txt}.md\") 审这一份 "
            "（在册也要给稿：V 的正文只从「## 证明」读，签块也落回这份稿）；"
            "③ 签到位后把这份稿随 own.register_statement 交上来（带 proof_manuscript）。"
            "禁令：不给 proof_manuscript 的内联正文现在过不了 V"
            "（`proof_text_needs_a_manuscript`），不许绕开 V 直接当定理用。")
    if state == "rejected":
        return (
            f"{head}最近那一签的结论不是「成立」（{verification_id or '（没有号）'}）"
            "⇒ 整笔不写。建议：按 findings 改完再送，不要原样重送 —— 先把证明改好，"
            + _land_step
            + f"② 再派 V 用 verify.verify_proof(statement_id=\"{sid_txt}\", proof_no=1, "
            f"proof_manuscript=\"reports/b-proof-{sid_txt}.md\") 重审 "
            "（在册也要给稿：V 只从「## 证明」读正文、签块也只落回稿）。"
            "禁令：原样重送不会改变结论；不给稿的内联正文现在过不了 V"
            "（`proof_text_needs_a_manuscript`）。")
    if state == "holding":
        return (
            f"{head}的签还没到位（V 判过「成立」，但这一版正文上还没有签块）⇒ 整笔不写。"
            "建议：先让 B 显式落稿（`AgentB.land_manuscript`；`own.land_manuscript` "
            "工具面待 T1 接线）把这一版落成可签的稿（盘上还没有的话），"
            f"再派 V 用 verify.verify_proof(statement_id=\"{sid_txt}\", proof_no=1, "
            f"proof_manuscript=\"reports/b-proof-{sid_txt}.md\") 审这一份 "
            "（在册也要给稿：V 只从「## 证明」读正文、签块也只落回稿），"
            "签到位后签块由收方秘书落回稿 —— 不必改稿、不必再交登记。")
    return (
        f"{head}在 V 的台账里查不到能签住它的那一签，而这一格没查成 "
        f"（{why[:120] if why else '台账读不出来'}）⇒ 整笔不写。"
        "没查成不是「没签」，也不许当成签过；先把台账/读数修好再重判。")


#: 「没有签的证明不许进台账」这一闸的三态开关（业主 2026-11-02 的准入闸）。
#:
#: 取值：`strict`（「默认」，拒收无签的证明正文）/ `relaxed`（照改前收下，只用于
#: 历史夹具与"迁移未完成"的那一段）/ 认不出 ⇒ 按 `strict` 走（三态纪律：认不出
#: 不是"放行"）。
#:
#: 为什么要有这个开关而不是写死：这条闸是「门的强度变更」，它会让"以证明正文登记"
#: 的所有旧夹具都不再成立（实测 55 个测试文件写的是改前口径「无签也能入台账」）。
#: 判据要能同时跑两档，才跑得出反真空：把闸摘掉 ⇒ 那条"无签必须被拒"的判据必须红。
UNSIGNED_PROOF_INTAKE_ENV = "AGENTFLOW_UNSIGNED_PROOF_INTAKE"
UNSIGNED_PROOF_INTAKE_STATES: tuple[str, ...] = ("strict", "relaxed")


def unsigned_proof_intake_is_strict() -> bool:
    """这一闸现在是不是"拒"的那一档（默认是；认不出也按拒走）。"""
    import os

    raw = str(os.environ.get(UNSIGNED_PROOF_INTAKE_ENV) or "").strip().lower()
    return raw != "relaxed"


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
                "或者只给 proofs 里的 #p1（改在册命题的正文时只给 proof_text：`proofs` "
                "那一栏是给第 2 份及以后的证明用的，它不参与 canonical 覆盖）")
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
    return {"text": old, "sha": _PR.proof_sha(old), "at": S.now_iso(),
            "replaced_by": _PR.proof_sha(new)}


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

    ## 第 3 位那两张表：`fresh` 里有的必须带过来（2026-11-03，第 ② 处）
    `fresh` 不是"与签名无关的现算值"：调用方在它上面已经走过 `vsigns.bits_after_sign`
    （按这一笔要落盘的正文 sha 认签），所以它可能带着覆盖新正文的那一签
    （`reviewed_by_proof` / `reviewed_sha_by_proof` / `reviewed_by`）。改前这里只从
    `fresh` 取 `proof_process` / `proof_source`，等于把刚认到的那一签整份丢掉 ——
    盘上留下的还是"签旧稿"的那一套（或根本没有），而 `optimized=true` 却照着台账另判
    一次。87 的 000002 连 `reviewed_by_proof` 这一格都没有，就是这一句造成的。
    现在的口径：`fresh` 有哪几格就覆盖哪几格（它是"按现行正文重新判定后"的结果），
    `fresh` 没有的保留 `old` 的（旧签作为历史仍在，读侧按 sha 判 stale）——
    两边都不许清空即通过。
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
    # 第 3 位：这一笔按现行正文认到的签（`bits_after_sign` 的产物）要跟着正文一起落，
    # 不是"换正文顺手把旧的签擦掉"，也不是"留着旧的那一套就算签过"。
    for key in (_EB.REVIEWED_BY_PROOF_KEY, _EB.REVIEWED_SHA_BY_PROOF_KEY, "reviewed_by"):
        if key in fresh_ev:
            ev[key] = fresh_ev[key]
    if bool(new.get("reviewed")):
        out["reviewed"] = True
    out["evidence"] = ev
    return _EB.normalize_raw(out, origin=str(row.get("origin") or "own_result"),
                             kind=str(row.get("kind") or ""))


def _optimized_gate(bits: Mapping | None, *, proof_no: Any, proof_text: str) -> dict:
    """`optimized=true` 能不能打：判据只有一处（`evidencebits.optimized_signature`）。

    ## 为什么它必须是一个能被打桩的单点
    87 的漏洞是"`optimized=true` 能在没有签的情况下被打上"（8 条命题里 4 条有正文
    无签、却全被记成已优化）。所以这一笔要有一个唯一的判据点：核
    `reviewed_by_proof[证明号] is True` 且 `reviewed_sha_by_proof[证明号] ==
    proof_sha(现行正文)`。反真空判据把它打成恒 true ⇒ "无签的替换"必须当场又能打上
    true（见 `tests/test_optimized_requires_a_sign.py` 的 d）—— 打桩点就在这里，
    不在读侧、也不在调用方。
    """
    return _EB.optimized_signature(dict(bits or {}), proof_no, proof_text=proof_text)


def _optimized_reading(attach: Mapping) -> dict:
    """把 `_attach_proofs` 里算好的优化态读数摊到返回值上（键与写侧同一个）。

    只在换正文那一笔有话说：`optimized` 逐份、`optimized_blocked` 是被拦下的原因
    （空串 = 没被拦）。老写法（没有换正文）的返回值因此逐字不变。
    """
    got = dict(attach or {})
    if not got.get("optimized"):
        return {}
    return {"optimized": [dict(x) for x in (got.get("optimized") or [])],
            "optimized_blocked": str(got.get("optimized_blocked") or "")}


def _sign_filing_reading(store: Any, *, manuscript_path: Any,
                         manuscript_text: Any = "", statement_id: Any = "") -> dict:
    """收录回执的两格读数（2026-11-08）：稿上已签 / 已入台账。

    判据本体只有 `vsigns.sign_filing_reading` 一处；这一层只负责"回执不许因为读数
    失败而丢掉"（异常折成 `checked=False`，不带走这一笔登记）。
    """
    from .. import vsigns as _VS

    rel = str(manuscript_path or "").strip()
    try:
        return dict(_VS.sign_filing_reading(
            getattr(store, "root", ""), manuscript_path=rel,
            proof_text=("" if rel else str(manuscript_text or "")),
            statement_id=str(statement_id or ""), store=store))
    except Exception as exc:  # noqa: BLE001 —— 读数失败不许带走这一笔登记
        return {"checked": False, "state": "unreadable",
                "manuscript_signed": None, "filed": None,
                "why": f"两格读数没跑成（{type(exc).__name__}: {exc}）"}


def _manuscript_is_own(*, manuscript_text: Any = "", manuscript_path: Any = "",
                       stmt_id_now: Any = "", matched_by: Any = "") -> bool:
    """这一份稿是不是本行自己的（D1 的第二道：命中了也要问所有权）。

    判据只有三句：
    - 按证明正文认出来的（`matched_by == proof_body`）⇒ 是：那一份的 `## 证明`
      与这一笔交的正文逐行相同，不存在"借别人的正文"；
    - 本行还没在册（没有号）⇒ 不是：没有"本行"可比对，就不许拿任何号去猜
      （被引命题的号不是"本行"的）—— 改前 `stmt:000001` 就是这样把
      `stmt:000000` 的稿连正文带签一起读走的；
    - 本行在册 ⇒ 稿自己的号（稿头 `- 命题号：stmt:<号>`，没有再按号的文件名）
      必须等于本行号。稿头声明了别人号、或文件名是别人号，都不是自己的稿。

    ## 2026-11-05 业主裁定：D1 取严格版

    依赖面也是"这一份证明"的事实：被引命题稿里那张 `## 依赖` 表写的是它引了谁；
    把它按到新命题头上，台账里就会出现一条"我引了 X"而作者从未这么写的边。
    所以借正文、借签、借依赖面都不行；旧口径"历史形态的稿按既有语义放行"作废。

    这一格就是 D1 反真空的打桩点：把它打成恒真 ⇒ `stmt:000001` 又会把
    `stmt:000000` 的稿读成自己的（判据 a 立刻红）。
    """
    from .. import vsigns as _VS

    if str(matched_by or "") == _DS.MATCH_BY_PROOF_BODY:
        return True
    own = str(stmt_id_now or "").strip()
    if not own:
        return False
    declared = _DS.manuscript_statement_id(str(manuscript_text or ""))
    named = str(declared or "").strip() or str(
        _VS.manuscript_id_of(str(manuscript_path or "")) or "").strip()
    return bool(named) and named == own


def _manuscript_usable(probe: Mapping, *, stmt_id_now: Any) -> bool:
    """兜底读盘命中的那一份稿能不能用（读数 `source=disk` 的门）。"""
    got = dict(probe or {})
    return _manuscript_is_own(
        manuscript_text=got.get("text"), manuscript_path=got.get("path"),
        stmt_id_now=stmt_id_now, matched_by=got.get("matched_by"))


def _manuscript_belongs_to_a_cited_statement(*, declared_id: Any = "",
                                             derived_from: Any = (),
                                             proof_text: Any = "") -> bool:
    """这份稿的号是不是「被引命题」的号（而不是本笔要登记的新命题的号）。

    ## 为什么候选号要问这一句（2026-11-06 真退化）

    D 的携带单按命题号点名，而 B 新登记一条派生命题时，`derived_from` 与正文里的
    `stmt:` 引用会把「被引命题」的稿一并带进来（`read_carried_manuscript` 的候选
    就是这些号）。那些稿的号属于被引命题，不是这一笔将要发的号；把它当候选号，
    B 就会撞在被引命题自己头上（`stmt_id_taken`）—— D 携带 F 稿 → B 登记派生命题
    这条主链整笔拒。

    判据只有一句：稿名 / 稿头认出来的号在"这一笔引了谁"（`derived_from` ∪
    正文里的 `stmt:` 引用）里 ⇒ 它是被引命题的稿，不许当本笔的候选号。

    与"稿是不是本行的"（`_manuscript_is_own`）分工：那一格管正文 / 签 / 依赖面
    用不用这份稿；这一格管「号」。两格都不许让被引命题的稿说话。
    """
    declared = str(declared_id or "").strip()
    if not declared:
        return False
    cited = {str(x).strip() for x in (derived_from or ()) if str(x).strip()}
    cited.update(str(x) for x in _DS.stmt_refs(str(proof_text or "")))
    return declared in cited


#: 这一笔的调用方角色（`conductor.current_parent()` 的父角色；没挂点 ⇒ 空串）。
#:
#: 为什么读父角色而不是 `current_caller_role()`：那一个是"我是谁"（B 自己），
#: 而这里要判的是"谁派我来的" —— F 的命题必须先落手稿。
def _caller_role() -> str:
    try:
        from ..conductor import current_parent

        _pid, role = current_parent()
        return str(role or "")
    except Exception:  # noqa: BLE001 —— 读不到就当作"没有挂点"（不是"父是 F"）
        return ""


def _row_has_proof(row: Mapping | None) -> bool:
    """这一行到底有没有一份有正文的证明（canonical 或 #pN 任一）。

    为什么不能 `bool(proof_list(row))`：`proof_list` 对 canonical 空的行也可能给出
    一条 `(1, "")`（结构上有那一格、正文是空的）。e-num 普通数值档正是这个形态 ——
    用"清单非空"判会把"没有证明"读成"第 1 份证明"（缺陷 ③）。判据只认正文非空。
    """
    data = dict(row or {})
    if str(data.get("proof_text") or "").strip():
        return True
    return any(str(text or "").strip() for _no, text in _VR.proof_list(data))


def _same_search_reading(same: Mapping | None) -> dict:
    """同一命题检索的公开读数（去掉内部行缓存 `_row` 与整份判定内部表，其余原样带走）。

    `adjudication` 那一格里有候选的整行（`row`），它只给 `record_statement` 用；
    公开读数要的是判词 / 页数 / 候选数 / 关键词，不要把整行再抄一遍。
    """
    return {str(k): v for k, v in dict(same or {}).items()
            if not str(k).startswith("_") and str(k) != "adjudication"}


def _declared_manuscript_kind(*, text: str = "", root: str = "") -> str:
    """手稿头 `- 证据种类：<kind>` 读出来的那一档（认不出 / 词表外 ⇒ 空串，不猜）。

    只认 `secretary.PROPOSITION_KINDS` 里的取值：手稿头是作者写的字节，不能让它
    随手发明一个新 kind 落进 `statements`（那等于绕开 kind 的语义）。
    """
    raw = str(text or "")
    rel = _norm_manuscript_rel(raw)
    if rel and _is_manuscript_rel(rel) and root:
        try:
            raw = (Path(str(root)) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""
    if not raw.strip():
        return ""
    try:
        from .. import proofregistry as _PR
        from ..secretary import PROPOSITION_KINDS

        kind = str(_PR.parse_entry(raw).get("kind") or "").strip().lower()
    except Exception:  # noqa: BLE001 —— 读不到就是没有声明（不猜）
        return ""
    return kind if kind in PROPOSITION_KINDS else ""


#: 这一笔的调用方角色（`conductor.current_parent()` 的父角色；没挂点 ⇒ 空串）。
#:
#: 为什么读父角色而不是 `current_caller_role()`：那一个是"我是谁"（B 自己），
#: 而这里要判的是"谁派我来的" —— F 的命题必须先落手稿。
def _caller_role() -> str:
    try:
        from ..conductor import current_parent

        _pid, role = current_parent()
        return str(role or "")
    except Exception:  # noqa: BLE001 —— 读不到就当作"没有挂点"（不是"父是 F"）
        return ""


class _RegisterStatement(_LandManuscript, _IngestManuscript):
    def _statement_bits(self, *, origin: str, lit_id: str, proof_text: str,
                        quote_verified: bool | None,
                        other_proofs: list[str] | None = None,
                        kind: str = "",
                        numeric_evidence: Mapping[str, Any] | None = None
                        ) -> tuple[dict, dict | None]:
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
                # 2026-11-08（普通数值绿色通道）：第 1 位由 E 那条实验的读数撑起来 ——
                # 凭据是实验号 + 程序路径（`bit_problems` 要求 `verified` 必须能指到
                # 哪条实验/哪个脚本）。它只把等级抬到 `strong_conjecture`（第 2 位仍空）。
                # 必须与 `schema.Statement.validate` 用的是同一个值：概念行的等级
                # （`not_applicable`）只有带上 kind 才算得出来，见上面那段说明。
                kind=kind,
                # 普通数值绿色通道：`numeric="verified"` 的凭据（实验号 + 程序路径）。
                numeric="verified" if numeric_evidence else None,
                numeric_evidence=numeric_evidence,
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

    # ---- 普通数值手稿的绿色通道（2026-11-08 业主三条裁定） ------------------------
    #
    # 业主逐字：「D侧普通数值实验也需写报告……D侧呈递时一样引用E侧手稿提交强猜想
    # （即有数值实验支持的猜想），B侧做好适配（应该在手稿里找命题和数值实验程序，
    # 不录入其它内容）」＋「专门给普通数值实验开绿色通道就行」＋「乙」（② 程序设计
    # 挪进 experiments.observations["design"]，证明栏只剩 ③）。
    #
    # 这条通道只认 E 的 `reports/e-num-<实验号>.md`（穷举档 `e-proof-*` 走原来那条
    # 第三方签字闸，不在这一条上）：
    #   · 命题：手稿 `## 命题` 那一节（不录 `## 数值结果` / 任何别的内容）；
    #   · 程序：`experiments.code_path` 那一格（手稿里只写"见实验行"，不抄一遍）；
    #   · `proof_text` 空着（业主明令）；
    #   · `evidence_kind` = `cross_check`（"有数值实验支持，不构成证明"；业主说的
    #     「普通数值档值」，受控词表里本来就有这一档）；
    #   · 等级由五元位现算：`numeric=verified`（凭据指到那条实验）⇒ `strong_conjecture`；
    #   · 不过 V（V 台账 0 行也能收）—— 这不是绕过闸，而是业主给这一档定的口径：
    #     它的承重证据是机器可核的实验行 + 程序路径 + 数值结果，不是一签。

    def _numeric_manuscript_channel(self, *, proof_manuscript: Any) -> dict[str, Any]:
        """这一笔递进来的是不是 E 的普通数值手稿；是 ⇒ 把该取的两样取出来。

        只认路径（`reports/e-num-<号>.md`）；认不出/读不到/实验行对不上 ⇒ `ok=False`
        并把原因逐条写进 `problems`（调用方据此走普通登记路，不把"没认出"当"不是"）。
        """
        from .. import exhaustionreport as _ER
        from .. import numericproof as _NP

        out: dict[str, Any] = {
            "checked": False, "ok": False, "path": "", "experiment_id": "",
            "code_path": "", "method": "", "statement": "", "result_text": "",
            "manuscript": {}, "problems": [],
            # 数值证据四元组的机器侧原料（2026-11-08：一个命题可以有多份实验）：
            # 只从实验行原样取，不在这里判它们够不够（那是 `bit_problems` 的事）。
            "observations": {}, "params": {}, "result": "", "counterexample": None,
            "experiment_row": {},
        }
        rel = str(proof_manuscript or "").strip().replace("\\", "/")
        if not rel or not _ER.is_numeric_manuscript_relpath(rel):
            return out
        out["checked"] = True
        out["path"] = rel
        root = getattr(self.store, "root", "")
        read = _ER.read_numeric_manuscript(root, rel)
        out["manuscript"] = read
        if not read.get("ok"):
            out["problems"] = [f"E 的普通数值手稿读不成：{p}"
                               for p in (read.get("problems") or [])] or [
                "E 的普通数值手稿读不成（没有理由）"]
            return out
        eid = _ER.experiment_id_of(rel)
        out["experiment_id"] = eid
        try:
            rows = [dict(r) for r in self.store.rows("experiments")]
        except Exception as exc:  # noqa: BLE001 —— 读不到实验台账 ⇒ 这一格没查成
            out["problems"] = [f"实验台账读不出来（{type(exc).__name__}: {exc}）⇒ "
                               "没查成（不是「没有那条实验」）"]
            return out
        row = next((r for r in rows
                    if str(r.get("experiment_id") or r.get("id") or "") == eid), None)
        if row is None:
            out["problems"] = [f"手稿点名的实验行 exp:{eid} 不在 experiments 台账里 ⇒ "
                               "这一份没有可核的数值结果（不许把它当手稿收）"]
            return out
        out["method"] = str(row.get("method") or "")
        out["observations"] = dict(row.get("observations") or {})
        out["params"] = dict(row.get("params") or {})
        out["result"] = str(row.get("result") or "")
        out["counterexample"] = row.get("counterexample")
        out["experiment_row"] = dict(row)
        if out["method"] == _NP.FORMAL_METHOD:
            out["problems"] = ["这一行是形式化实验（method=formal）⇒ 不归普通数值通道"
                               "（它的凭据是检查器输出，不是数值结果）"]
            return out
        code_path = str(row.get("code_path") or "").strip().replace("\\", "/")
        if not _NP.is_script_path(code_path):
            out["problems"] = [f"实验行 exp:{eid} 的 code_path 读不到程序路径"
                               f"（读到 {code_path!r}）⇒ 这一份没有可复跑的程序"]
            return out
        out["code_path"] = code_path
        parts = _ER.numeric_sections_of(read.get("text") or "")
        out["statement"] = str(parts.get("statement") or "").strip()
        out["result_text"] = str(parts.get("result") or "").strip()
        if not out["statement"]:
            out["problems"] = [f"手稿 `{_ER.NUMERIC_STATEMENT_HEADING}` 那一节是空的 ⇒ "
                               "这一份没有可登记的命题"]
            return out
        out["ok"] = True
        return out

    def _numeric_form_gate(self, *, full: str, kind: str = "conjecture",
                           label: str = "", task_id: str = "") -> dict[str, Any]:
        """普通数值通道收录那一刻的形态闸（一次调用，不是每条实验判一次）。

        判据本体只有一处：:meth:`secretary.Secretary.judge_proposition_form`（与 F / E
        同一道判定口）；本方法只做三件本层的事：① 把这条命题递过去；② 把"没判成"也写进
        形态台账（`role="B"`）；③ 折成 `submittable`（两态）。
        """
        out: dict[str, Any] = {
            "checked": False, "well_formed": False, "submittable": False,
            "conditions": "", "conclusion": "", "problems": [], "decision": "",
            "refused": "", "reason": "", "actor": "", "cached": False,
        }
        from ..secretary import (NOT_APPLICABLE_KINDS, PROPOSITION_FORM_REFUSED,
                                 append_proposition_form)

        root = str(getattr(self.store, "root", "") or "")

        def _note(reason: str) -> None:
            if not root:
                return
            try:
                append_proposition_form(
                    root, statement_full=str(full or ""), checked=False,
                    well_formed=False, conditions="", conclusion="",
                    problems=[str(reason)[:200]], decision="没判成",
                    refused=PROPOSITION_FORM_REFUSED, reason=str(reason),
                    label=str(label or ""), kind=str(kind or ""), stmt_id="",
                    role="B", task_id=task_id)
            except Exception as exc:  # noqa: BLE001 - 台账写不进去不改判定
                out["ledger_error"] = f"{type(exc).__name__}: {exc}"

        if str(kind or "").strip().lower() in NOT_APPLICABLE_KINDS:
            out.update(checked=True, well_formed=True, submittable=True,
                       reason=(f"kind={kind!r} 落在 concept/definition 那一档：它不是命题"))
            return out
        sec = self._statement_secretary()
        if sec is None:
            why = ("B 的秘书派生不出来"
                   f"（{getattr(self, 'secretary_problem', '未知原因')}）⇒ "
                   "这一问没判成：受控拒（没判成不等于没毛病）")
            out.update(refused=PROPOSITION_FORM_REFUSED, reason=why)
            _note(why)
            return out
        try:
            got = dict(sec.judge_proposition_form(
                statement_full=str(full or ""), label=str(label or ""),
                kind=str(kind or ""), proof_text="", task_id=task_id) or {})
        except Exception as exc:  # noqa: BLE001 —— 判定那一问炸了 = 没判成（受控拒）
            why = (f"形态判定调用失败（{type(exc).__name__}: {exc}）⇒ "
                   "没判成：受控拒（没判成不等于没毛病）")
            out.update(refused=PROPOSITION_FORM_REFUSED, reason=why,
                       problems=[str(exc)[:200]])
            _note(why)
            return out
        out.update(
            checked=bool(got.get("checked")), well_formed=bool(got.get("well_formed")),
            conditions=str(got.get("conditions") or ""),
            conclusion=str(got.get("conclusion") or ""),
            problems=[str(x) for x in (got.get("problems") or [])],
            decision=str(got.get("decision") or ""),
            actor=f"secretary-{getattr(sec, 'role', 'B')}",
            refused=str(got.get("refused") or ""),
            reason=str(got.get("reason") or ""),
            cached=bool(got.get("cached")))
        out["submittable"] = bool(out["checked"] and out["well_formed"])
        if not out["checked"]:
            out["refused"] = out["refused"] or PROPOSITION_FORM_REFUSED
            if not got.get("ledger"):
                _note(str(out.get("reason") or "没判成"))
        return out

    # ---- 同一命题检索：只留秘书那一条路（2026-11-08 缺陷 ②） -----------------------
    #
    # 业主逐字：「B秘书要学会在命题台账里按关键词搜索」「只有秘书查了一圈没查到一样的
    # 就注册新的，查到就更新那条命题的状态」。
    #
    # 检索只有一处实现：`Secretary.adjudicate_proposition`（秘书挑词 → 代码检索 → 判定）。
    # B 这一层不再自建关键词检索、也不再自己分批 —— 改前 `_numeric_same_candidates` 是
    # 第二条检索路，而判定那一侧只把前 4 条交给模型 ⇒ 第 5–20 条永不入眼却记成
    # "这批都不是"。现在 B 只做两件事：
    #   ① 逐字相同这一档（确定性事实，免模型）在这里直接给 found；
    #   ② 其余一律交给秘书那一条路：它自己挑词、自己检索、按页问到命中或页尽，并把
    #      页数 / 候选数 / 是否页尽写进读数（`pages_total` / `pages_judged` /
    #      `candidates_total` / `page_exhausted`）。
    # 三处共用：普通数值收录 / 证明收录（多证明路径）/ D 的指针收录。

    def _resolve_same_statement(self, *, full: str, label: str = "",
                                kind: str = "conjecture",
                                task_id: str = "") -> dict:
        """这一条待收命题是不是在册的某一条（检索与判定都归秘书那一处）。

        ## 为什么 B 不再自己检索（2026-11-08 缺陷 ②）
        改前这一格自己按关键词扫 `statements`（`_numeric_same_candidates`）、再按 20 条
        分批把候选递给判定那一趟；而判定那一趟只把前 4 条交给模型 ⇒ 第 5–20 条
        永不入眼却被记成"这批都不是"。业主的口径是「检索只是取候选，不参与判定」
        ＋「只留一条检索路」：检索与判定同住 `Secretary.adjudicate_proposition`，它自己
        分页（页大小 = 一次能给几条的工程上限），问到命中或页尽为止。

        ## 读数的承重项
        `pages_total` / `pages_judged` / `candidates_total` / `page_exhausted`：
        "看了几页 / 几个候选 / 是不是页尽"必须与判词一起看得见 —— 只写 `hits_total`
        时，"只看了 4 条就说都不是"与"20 条都看过"在读数上同形。

        ## 逐字相同那一档（确定性事实，免模型）
        规范化后全等 ⇒ 直接 found，不调模型（判据 c：模型调用 0 次）。这不是第二条
        检索路：它不生成候选，只回答"同一段正文是不是已经在册"。

        ## 三态（业主 2026-11-08）
        | 结局 | 返回 |
        |---|---|
        | 查到某一条 | `checked=True` + `found=<stmt_id>` + `_row`（那一行原文） |
        | 查过、没查到 | `checked=True` + `found=""` + `why`（候选 0 条 / 逐页判过都不同） |
        | 没查成 | `checked=False` + `refused=same_statement_unjudged` + `why`（整笔不写） |
        """
        from .. import propositionkey as _PK
        from .. import textutil as T
        from ..secretary import append_statement_same, PROPOSITION_KINDS

        out: dict = {
            "checked": False, "keyword_checked": False,
            "keywords": [], "hits_total": 0, "hits_named": [],
            "found": "", "why": "", "judged": False,
            "model_calls": 0, "problems": [], "refused": "",
            "candidates_total": 0, "pages_total": 0, "pages_judged": 0,
            "page_exhausted": False, "adjudication": {},
            "_row": {},
        }
        root = str(getattr(self.store, "root", "") or "")
        all_rows, problem, error = SL.rows_of(self.store)
        if problem:
            out.update(refused=_R.SAME_STATEMENT_UNJUDGED,
                       why=(f"statements 台账读不出来（{error.get('type') or '?'}: "
                            f"{error.get('message') or problem}）⇒ 没查成"))
            out["problems"] = [out["why"]]
            return out
        # 可检索 / 可并池只有一处实现（查口 `pool`）；kind 名单仍取自秘书那一份
        # `PROPOSITION_KINDS`（箱子里不复制名单）。
        eligible = SL.pool(all_rows, kinds=PROPOSITION_KINDS)
        # 台账里一条可检索的命题都没有 ⇒ "查过、0 条"（不花模型调用、也不要求判断面）。
        if not eligible:
            out.update(checked=True, keyword_checked=True, hits_total=0,
                       candidates_total=0, pages_total=0, pages_judged=0,
                       page_exhausted=True,
                       why=("查过：命题台账里没有可检索的 active 命题（候选 0 条）"
                            "⇒ 注册新的"))
            out["adjudication"] = {
                "checked": True, "attempted": False,
                "verdict": _PK.STATE_DIFFERENT, "same_as": "",
                "canonical_name": "", "route": "",
                "basis": "查过：没有可比的候选 ⇒ 不同",
                "reason": str(out["why"]), "reused": False, "cached": False,
                "statement_sha256": "", "seam_source": "",
                "keywords": [], "hits_total": 0, "hits_named": [],
                "judged": False, "candidates_total": 0, "pages_total": 0,
                "pages_judged": 0, "page_exhausted": True,
            }
            if root:
                try:
                    out["retrieval_ledger"] = append_statement_same(
                        root, stage="retrieval", statement_full=str(full or ""),
                        checked=True, keywords=[], hits_total=0,
                        why=str(out["why"]), label=label, kind=kind,
                        role="B", task_id=task_id)
                except Exception as exc:  # noqa: BLE001
                    out["ledger_error"] = f"{type(exc).__name__}: {exc}"
            return out
        # 逐字相同：确定性事实，免模型。比对口径只有一处（查口 `duplicate_hits`）。
        exact = (SL.duplicate_hits(eligible, text=full)["hits"] or [None])[0]
        if T.normalize(str(full or "")) and exact is not None:
            return self._same_statement_exact(
                exact=exact, full=full, label=label, kind=kind,
                task_id=task_id, root=root)
        sec = self._statement_secretary()
        if sec is None:
            out.update(refused=_R.SAME_STATEMENT_UNJUDGED,
                       why=("这一趟没有秘书 ⇒ 同一命题检索 / 判定没查成（不新注册）"
                            + (f"；{self.secretary_problem}"
                               if getattr(self, "secretary_problem", "") else "")))
            out["problems"] = [out["why"]]
            return out
        try:
            got = dict(sec.adjudicate_proposition(
                {"statement_full": str(full or ""), "label": label,
                 "kind": kind or "theorem"},
                note="secretary:statement_same", task_id=task_id) or {})
        except Exception as exc:  # noqa: BLE001 —— 判定这一问炸了 = 没判成
            out.update(refused=_R.SAME_STATEMENT_UNJUDGED,
                       why=(f"同一命题检索 / 判定调用失败（{type(exc).__name__}: "
                            f"{exc}）⇒ 没查成"))
            out["problems"] = [out["why"]]
            return out
        out["adjudication"] = got
        out["checked"] = bool(got.get("checked"))
        out["keyword_checked"] = bool(got.get("keyword_checked",
                                               got.get("keywords")))
        out["keywords"] = [str(x) for x in (got.get("keywords") or ())]
        out["hits_total"] = int(got.get("hits_total") or 0)
        out["hits_named"] = [dict(x) if isinstance(x, Mapping) else {"stmt_id": str(x)}
                             for x in (got.get("hits_named") or ())]
        out["judged"] = bool(got.get("judged"))
        out["candidates_total"] = int(got.get("candidates_total") or 0)
        out["pages_total"] = int(got.get("pages_total") or 0)
        out["pages_judged"] = int(got.get("pages_judged") or 0)
        out["page_exhausted"] = bool(got.get("page_exhausted"))
        out["why"] = str(got.get("reason") or got.get("why") or "")
        if bool(got.get("reused")):
            out["model_calls"] = 0
        else:
            out["model_calls"] = ((1 if out["keyword_checked"] else 0)
                                  + out["pages_judged"])
        if not out["checked"]:
            out.update(refused=_R.SAME_STATEMENT_UNJUDGED, found="", _row={})
            out["problems"] = [out["why"] or "同一命题判定没成"]
            # 判没成也要在盘上留一行（旧读数逐字不变）：`judge` 那一趟没给结论时
            # `checked=False`，读的人才分得清"查过、不是同一条"与"根本没判成"。
            if root:
                try:
                    out["judge_ledger"] = append_statement_same(
                        root, stage="judge", statement_full=str(full or ""),
                        checked=False, keywords=out["keywords"],
                        hits_total=out["hits_total"],
                        candidates=[str(h.get("stmt_id") or "")
                                    for h in out["hits_named"]],
                        found="", why=str(out["why"] or ""), label=label,
                        kind=kind, role="B", task_id=task_id)
                except Exception as exc:  # noqa: BLE001
                    out["ledger_error"] = f"{type(exc).__name__}: {exc}"
            return out
        if str(got.get("verdict") or "") == _PK.STATE_SAME:
            out["found"] = str(got.get("same_as") or "")
        if out["found"]:
            row: dict = {}
            for cand in (got.get("candidates") or ()):
                if (isinstance(cand, Mapping)
                        and str(cand.get("stmt_id") or "") == out["found"]):
                    row = dict(cand.get("row") or {})
                    break
            if not row:
                # 按号定位走查口（口径一）；`all_rows` 是这一层刚读的那一份快照。
                row = SL.by_id(rows=all_rows, stmt_id=out["found"])["row"]
            out["_row"] = row
            if not row:
                out.update(checked=False, refused=_R.SAME_STATEMENT_UNJUDGED,
                           found="", problems=["秘书判了同一条，而它的行读不回来"])
                out["why"] = "秘书判了同一条，而它在 statements 里的行读不回来 ⇒ 没查成"
                return out
        if root:
            try:
                out["judge_ledger"] = append_statement_same(
                    root, stage="judge", statement_full=str(full or ""),
                    checked=True, keywords=out["keywords"],
                    hits_total=out["hits_total"],
                    candidates=[str(h.get("stmt_id") or "")
                                for h in out["hits_named"]],
                    found=out["found"], why=str(out["why"]), label=label,
                    kind=kind, role="B", task_id=task_id)
            except Exception as exc:  # noqa: BLE001
                out["ledger_error"] = f"{type(exc).__name__}: {exc}"
        return out

    @staticmethod
    def _same_statement_exact(*, exact: Mapping, full: str, label: str,
                              kind: str, task_id: str, root: str) -> dict:
        """逐字相同那一档：规范化后全等 ⇒ 直接 found，不调模型。

        这不是第二条检索路：它不生成候选，只回答"同一段正文是不是已经在册"
        （判据 c：模型调用 0 次）。2026-11-08 从 `_resolve_same_statement` 拆出
        （只搬移）：那一格合起来 200 行出头 —— 体量基线是读数，不许为了它抬。
        """
        from .. import propositionkey as _PK
        from ..secretary import append_statement_same

        out: dict = {
            "checked": True, "keyword_checked": True, "hits_total": 1, "judged": False,
            "keywords": [], "hits_named": [], "found": "", "why": "",
            "model_calls": 0, "problems": [], "refused": "",
            "candidates_total": 1, "pages_total": 0, "pages_judged": 0,
            "page_exhausted": True, "adjudication": {}, "_row": {},
        }
        sid = str(exact.get("stmt_id") or "")
        out.update(
            hits_named=[{"stmt_id": sid, "hit_words": ["逐字相同"]}], found=sid,
            why=("候选的正文与待收命题逐字相同（规范化后全等）⇒ 同一条；"
                 "没调模型"))
        out["_row"] = dict(exact)
        out["adjudication"] = {
            "checked": True, "attempted": False, "verdict": _PK.STATE_SAME,
            "same_as": sid, "canonical_name": "", "route": "",
            "basis": "规范化后逐字相同（确定性事实）",
            "reason": str(out["why"]), "reused": False, "cached": False,
            "statement_sha256": "", "seam_source": "",
            "keywords": [], "hits_total": 1,
            "hits_named": list(out["hits_named"]), "judged": False,
            "candidates_total": 1, "pages_total": 0,
            "pages_judged": 0, "page_exhausted": True,
        }
        if root:
            try:
                out["judge_ledger"] = append_statement_same(
                    root, stage="judge", statement_full=str(full or ""),
                    checked=True, candidates=[sid], found=sid,
                    why=str(out["why"]), label=label, kind=kind,
                    role="B", task_id=task_id)
            except Exception as exc:  # noqa: BLE001
                out["ledger_error"] = f"{type(exc).__name__}: {exc}"
        return out

    @staticmethod
    def _same_statement_adjudication(same: Mapping) -> dict:
        """把"查一圈"的结果折成秘书同一性命中判定的形状（交给 `record_statement`）。

        ## 为什么不再自己拼一份判词（2026-11-08 缺陷 ②/④）
        改前这里把 `canonical_name` / `route` 写死成空串，于是
        `Secretary._record_statement_tx` 的洗名条件（`adj.checked ∧
        adj.canonical_name`）永假 ⇒ 脏标签原样落盘（审计探针 D）。现在检索与判定
        都归秘书那一处（`_resolve_same_statement` 调的是
        `Secretary.adjudicate_proposition`），它那一趟的 `canonical_name` /
        `route` 就是洗名的依据 —— 这里只把 `same_as` 折成既有写入链认的字段，
        其余原样带过去（同一个判据只有一个答案，不重新拼一份）。
        """
        from .. import propositionkey as _PK

        adj = dict(same.get("adjudication") or {})
        found = str(same.get("found") or "")
        why = str(same.get("why") or adj.get("reason") or "")
        verdict = str(adj.get("verdict") or "")
        if verdict not in (_PK.STATE_SAME, _PK.STATE_DIFFERENT):
            verdict = _PK.STATE_SAME if found else _PK.STATE_DIFFERENT
        seam = str(adj.get("seam_source")
                   or "agent_b.register_statement:same_statement")
        visibility = dict(adj.get("proposition_adjudication") or {})
        if not visibility:
            visibility = {"checked": bool(adj.get("checked")),
                          "attempted": bool(adj.get("attempted", True)),
                          "reason": why, "seam_source": seam}
        return {
            "checked": bool(adj.get("checked", True)),
            "verdict": verdict,
            "same_as": found,
            # 洗名与"这是哪一条"是同一趟判定的两个产物：照原样带过去。
            "canonical_name": str(adj.get("canonical_name") or ""),
            "route": str(adj.get("route") or ""),
            "condition": str(adj.get("condition") or ""),
            "conclusion": str(adj.get("conclusion") or ""),
            "basis": str(adj.get("basis") or why), "reason": why,
            "candidates": [{"stmt_id": str(c.get("stmt_id") or "")}
                           for c in (adj.get("candidates") or ())
                           if isinstance(c, Mapping)],
            "cost": dict(adj.get("cost")
                         or {"ledger": "",
                             "reason": "没发调用（沿用同一命题检索那一趟的结论）"}),
            "reused": bool(adj.get("reused")), "cached": bool(adj.get("cached")),
            "statement_sha256": str(adj.get("statement_sha256") or ""),
            "seam_source": seam,
            "attempted": bool(adj.get("attempted", True)),
            "keywords": [str(x) for x in (adj.get("keywords") or ())],
            "hits_total": int(adj.get("hits_total") or 0),
            "hits_named": [dict(x) if isinstance(x, Mapping)
                           else {"stmt_id": str(x)}
                           for x in (adj.get("hits_named") or ())],
            "judged": bool(adj.get("judged")),
            "candidates_total": int(adj.get("candidates_total") or 0),
            "pages_total": int(adj.get("pages_total") or 0),
            "pages_judged": int(adj.get("pages_judged") or 0),
            "page_exhausted": bool(adj.get("page_exhausted")),
            "proposition_adjudication": visibility,
        }

    @staticmethod
    def _numeric_four_tuple(green: Mapping) -> dict:
        """这一份实验的数值证据四元组（`schema.NUMERIC_EVIDENCE_KEYS`，键名固定）。

        只从实验行原样取：`script` = code_path；`range` = observations / params 里的
        range（没有就写 observations.grid 这一格）；`n_cases` 用
        `numericproof.CASE_COUNT_KEYS` 那几种写法（没有就写 observations.points）；
        `n_counterexamples` 优先取机器自报的条数，没有就按有没有 counterexample 记 0/1。
        不写序号 / 时间 / 第几份 —— 四元组本身就是内容寻址的键。
        """
        obs = dict(green.get("observations") or {})
        params = dict(green.get("params") or {})
        cases = _NP._case_count_of(obs, params)
        if cases is None:
            points = obs.get("points")
            cases = points if isinstance(points, int) and not isinstance(points, bool) else None
        ce = obs.get("n_counterexamples")
        if not isinstance(ce, int) or isinstance(ce, bool):
            ce = 1 if green.get("counterexample") else 0
        range_text = str(obs.get("range") or params.get("range")
                         or obs.get("grid") or "").strip()
        return {"script": str(green.get("code_path") or ""),
                "range": range_text,
                "n_cases": int(cases or 0),
                "n_counterexamples": int(ce)}

    def _numeric_entry(self, green: Mapping) -> dict:
        """流水里的一条数值证据：四元组 + 外侧的程序指纹与出处（不塞第五个键）。"""
        entry = dict(self._numeric_four_tuple(green))
        row = dict(green.get("experiment_row") or {})
        entry["code_hash"] = str(row.get("code_hash") or "")
        eid = str(green.get("experiment_id") or "")
        entry["exp"] = f"exp:{eid}" if eid else ""
        return entry

    @staticmethod
    def _same_numeric_program(left: Mapping, right: Mapping) -> bool:
        """两条数值证据是不是同一个数值程序（业主 2026-11-08 的唯一判据）。

        判据 = 脚本相对路径 + 它的 `code_hash`，两者都相同才算同一个程序。
        不用 `experiment_id`（那是"哪一次运行"），不用四元组内容（那是读数）。
        """
        return (str(left.get("script") or "") == str(right.get("script") or "")
                and str(left.get("code_hash") or "")
                == str(right.get("code_hash") or ""))

    def _merge_numeric_evidence(self, old: Mapping | None, green: Mapping) -> dict:
        """把这一份数值证据追加进流水（单位 = 一个数值程序，不是一次调用）。

        业主 2026-11-08：「数值实验录入就是一个纯追加的过程」＋「只判是不是一个
        数值程序」＋「如果同一个程序被重复提交，用后一次的替换前一次的」⇒
        同一个程序（脚本相对路径 + `code_hash` 都相同）再递一次，就地替换那条已有
        条目（读数换成后一次的，条数不变，旧读数不保留）；不是同一个程序就追加一条
        （哪怕四元组数值恰好相同）。不用 `experiment_id`、不用四元组内容做身份。

        一份数值证据 = `schema.NUMERIC_EVIDENCE_KEYS` 那四个键（键名固定，§8.3
        契约）；程序指纹与出处放在条目外侧（`code_hash` / `exp:<号>`），不往四元组
        里塞第五个键。已有条目一个字都不改；不排序；份数不影响等级（五元位现算）。
        指针格（`experiment_id` / `experiments` / `script`）保留，供
        `bit_evidence_gaps` 核"表里查得到"。
        """
        old_map = dict(old or {})
        entries: list[dict] = []
        for item in (old_map.get("entries") or []):
            if isinstance(item, Mapping):
                entry_old = {k: item.get(k) for k in S.NUMERIC_EVIDENCE_KEYS}
                entry_old["code_hash"] = str(item.get("code_hash") or "")
                entry_old["exp"] = str(item.get("exp") or item.get("experiment") or "")
                entries.append(entry_old)
        if not entries:
            # 旧行（单份、没有 entries）折成流水里的第一条：只取它真有的那几格。
            legacy = {k: old_map.get(k) for k in S.NUMERIC_EVIDENCE_KEYS
                      if old_map.get(k) not in (None, "")}
            if legacy:
                legacy["code_hash"] = str(old_map.get("code_hash") or "")
                eid_old = str(old_map.get("experiment_id") or "")
                legacy["exp"] = f"exp:{eid_old}" if eid_old else ""
                entries.append(legacy)
        eid = str(green.get("experiment_id") or "")
        entry = self._numeric_entry(green)
        # 同一个程序再次提交 ⇒ 就地替换那一条（读数换成后一次的，条数不变）；
        # 不是同一个程序 ⇒ 追加一条。业主 2026-11-08：「用后一次的替换前一次的」。
        matched = next((index for index, item in enumerate(entries)
                        if self._same_numeric_program(item, entry)), None)
        if matched is not None:
            entries[matched] = entry
        else:
            entries.append(entry)
        exp_ids = [str(x) for x in (old_map.get("experiments") or []) if str(x).strip()]
        if eid and eid not in exp_ids:
            exp_ids.append(eid)
        if not exp_ids and old_map.get("experiment_id"):
            exp_ids = [str(old_map.get("experiment_id") or "")]
        merged = dict(old_map)
        merged["entries"] = entries
        merged["experiments"] = exp_ids
        if eid:
            merged["experiment_id"] = eid
        merged["script"] = entry["script"] or str(old_map.get("script") or "")
        merged["code_hash"] = str(entry.get("code_hash") or "")
        merged["manuscript"] = str(green.get("path") or old_map.get("manuscript") or "")
        merged["manuscript_sha256"] = str(
            (green.get("manuscript") or {}).get("sha256")
            or old_map.get("manuscript_sha256") or "")
        #: 这一位能不能当"机器可核的证书"用（穷举 + V 签）—— 普通数值实验只抬到
        #: `strong_conjecture`，不许因为它和一份 V 签证明并在一行就把等级读成定理。
        #: 集合里只要有一份是签下的穷举，整位仍按证书读（业主：取已有证据里最高那档）。
        merged["certificate"] = bool(old_map.get("certificate")) or bool(
            _NP.is_signed_exhaustion(green.get("experiment_row") or {}))
        return merged

    def _numeric_evidence_payload(self, green: Mapping) -> dict:
        """新登记那一笔的数值证据（集合里先放一份四元组 + 指针）。"""
        return self._merge_numeric_evidence({}, green)

    def _update_numeric_evidence(self, *, row: Mapping, green: Mapping,
                                 same: Mapping) -> dict:
        """更新在册那一行的数值证据位（不新注册、不覆盖在册正文与既有 V 签 / formal 位）。

        业主 2026-11-08：「查到就更新那条命题的状态」。更新的只有第 1 位与它的凭据：
        `bits.numeric = verified`，凭据指到这一份手稿 + 这条实验；等级按五元位现算
        （第 2 位仍空 ⇒ strong_conjecture；已有证明 / V 签 / formal 位则保持更高的那一档）。
        在册正文一个字都不改：措辞差异只进读数（`proposition_matches_manuscript`）。
        """
        sid = str(row.get("stmt_id") or "")
        root = str(getattr(self.store, "root", "") or "")
        path = str(green.get("path") or "")
        before_bits = dict(row.get("bits") or {})
        before_numeric = dict((before_bits.get("evidence") or {}).get("numeric") or {})
        before_list = [x for x in (before_numeric.get("entries") or [])
                       if isinstance(x, Mapping)]
        before_entries = len(before_list)
        new_entry = self._numeric_entry(green)
        same_program = any(self._same_numeric_program(x, new_entry)
                           for x in before_list)
        evidence = self._merge_numeric_evidence(before_numeric, green)
        out: dict = {
            "ok": True, "stmt_id": sid, "new_row": False,
            "found": sid, "why": str(same.get("why") or ""),
            "searched": {k: same.get(k) for k in
                         ("keywords", "keyword_checked", "hits_total",
                          "hits_named", "judged", "model_calls")},
            "proposition_matches_manuscript": False,
            "numeric_channel": {
                "path": path,
                "experiment_id": str(green.get("experiment_id") or ""),
                "code_path": str(green.get("code_path") or ""),
                "evidence_kind": "cross_check",
                "proof_text": "(空着：普通数值档，业主明令)",
                "manuscript_sha256": evidence["manuscript_sha256"],
            },
        }
        kind_now = str(row.get("kind") or "")
        grade_before = _EB.derive_grade(before_bits, kind=kind_now)
        bits = dict(before_bits)
        bits["numeric"] = "verified"
        ev = dict(bits.get("evidence") or {})
        ev["numeric"] = dict(evidence)
        bits["evidence"] = ev
        grade = _EB.derive_grade(bits, kind=kind_now)
        bits["grade"] = grade
        bits["audited_badge"] = bool(bits.get("audited")) and grade not in (
            "conjecture", _EB.GRADE_NOT_APPLICABLE)
        problems = list(_EB.bits_shape_problems(bits, kind=kind_now))
        if problems:
            return _refuse("bad_bits",
                           "在册那一行的五位与新证据合起来不合规 ⇒ 整笔不写："
                           + "；".join(problems), problems=problems)
        store = getattr(self, "store", None)
        if store is None:
            return _refuse("secretary_unavailable",
                           "这一趟没有 store ⇒ 证据位写不进去（不许退回 B 自己写）")
        # ---- 2026-11-08（业主：「B 实际只有台账的只读权限，B 的任何所谓写台账的路实际上
        # 都由 B 的秘书洗过」）：这一笔不再由 B 开事务 —— 行变换交给秘书的
        # `land_statement`（它开事务、读现行行、判"改了哪几格"、写盘）。
        # `_transition` 拿到的 `found` 是事务内读的那一行：读—判—写仍在同一把锁里，
        # 与收口前逐字同序（收口前那一段 `tx.find` / 重算五位 / `tx.upsert` 原样搬进闭包）。
        sec = self._statement_secretary()
        if sec is None:
            return _refuse("secretary_unavailable",
                           "这一趟没有秘书 ⇒ 证据位写不进去（不许退回 B 自己写）"
                           + (f"；{self.secretary_problem}" if self.secretary_problem else ""))

        def _transition(found: Any) -> dict:
            if found is None:
                return {"write": False,
                        "result": _refuse("same_statement_missing",
                                          f"要更新的 stmt:{sid} 不在 statements 里 ⇒ 整笔不写"
                                          "（查到的那一行在写盘前消失了：不是静默新注册的理由）")}
            current = dict(found)
            merged = dict(current.get("bits") or {})
            merged["numeric"] = "verified"
            merged_ev = dict(merged.get("evidence") or {})
            merged_ev["numeric"] = self._merge_numeric_evidence(
                dict(merged_ev.get("numeric") or {}), green)
            merged["evidence"] = merged_ev
            merged_grade = _EB.derive_grade(merged, kind=str(current.get("kind") or ""))
            merged["grade"] = merged_grade
            merged["audited_badge"] = bool(merged.get("audited")) and merged_grade not in (
                "conjecture", _EB.GRADE_NOT_APPLICABLE)
            merged_problems = list(_EB.bits_shape_problems(
                merged, kind=str(current.get("kind") or "")))
            if merged_problems:
                return {"write": False,
                        "result": _refuse("bad_bits",
                                          "写盘前按现行行重算的五位不合规 ⇒ 整笔不写："
                                          + "；".join(merged_problems),
                                          problems=merged_problems)}
            current["bits"] = merged
            return {"write": True, "row": current, "result": out}

        try:
            landed = sec.land_statement(
                sid, _transition, op="numeric_evidence",
                note=f"agent_b.register_statement:numeric_evidence:{sid}")
        except Exception as exc:  # noqa: BLE001 —— 写盘失败 = 没写成（不是写成了一半）
            return _refuse("numeric_evidence_write_failed",
                           f"证据位写盘失败（{type(exc).__name__}: {exc}）⇒ 整笔不写",
                           stmt_id=sid)
        if not landed.get("checked"):
            # 秘书那一层拒了（改的格越界 / 行不在 / 没有秘书）：它的拒码原样往上回。
            return _refuse(str(landed.get("refused") or "numeric_evidence_write_failed"),
                           str(landed.get("reason") or "秘书没写这一笔"), stmt_id=sid)
        out = dict(landed.get("result") or out)
        if not landed.get("written"):
            # 这一笔没有要写的（收口前那一支是 `same_statement_missing` / `bad_bits`，
            # 它们自带 `ok=false` 的拒信体）⇒ 原样回它，不许补一个"写成了"。
            return out
        # 按号定位走查口（口径一）。这一格是"写成了之后的回读"，锁内 / 读侧失败都该
        # 照旧抛出（不是一个三态读数）：查口把异常收成 checked=False，这里翻回一次抛出。
        latest_got = SL.by_id(self.store, stmt_id=sid)
        if not latest_got["checked"]:
            _err = latest_got.get("error") or {}
            raise RuntimeError(f"`statements` 读不出来（{_err.get('type') or '?'}: "
                               f"{_err.get('message') or latest_got.get('reason') or '?'}）")
        latest = latest_got["row"]
        from .. import textutil as T
        same_text = bool(latest) and (
            T.normalize(str(latest.get("statement_full") or ""))
            == T.normalize(str(row.get("statement_full") or "")))
        out.update(
            row=latest,
            proposition_matches_manuscript=same_text,
            updated_statement={
                "stmt_id": sid, "written": True,
                "numeric": "verified", "grade": str(
                    _EB.bits_from_row(latest).get("grade") or grade),
                "grade_before": grade_before,
                "evidence": dict(evidence),
                "entries": [dict(x) for x in (evidence.get("entries") or [])],
                "entry_keys": list(S.NUMERIC_EVIDENCE_KEYS),
                "program": {"script": str(new_entry.get("script") or ""),
                            "code_hash": str(new_entry.get("code_hash") or "")},
                "same_program": bool(same_program),
                "replaced": bool(same_program),
                "appended": int(not same_program),
                "entries_before": before_entries,
                "entries_after": len(evidence.get("entries") or []),
                "entries_total": len(evidence.get("entries") or []),
                "experiments": list(evidence.get("experiments") or []),
                "manuscript": path,
                "experiment_id": str(green.get("experiment_id") or ""),
                "proposition_matches_manuscript": same_text,
            },
            note=("这一条与在册 stmt:" + sid + " 被秘书认定为同一条 ⇒ 不新注册；"
                  "只更新那一行的数值证据位（numeric=verified，凭据 "
                  f"{evidence['experiment_id']} / {evidence['script']}）；"
                  "在册正文一个字都没改"
                  + ("。" if same_text else
                     "（新交的措辞与在册正文不同，差异只在读数里，不覆盖在册正文）。")),
            # ---- 缺陷 ③②：普通数值档没有"证明"这一档 ------------------------------
            # e-num 的正文按业主口径留空 ⇒ 顶层不写 `proof_no`（0），并给显式
            # `has_proof=false`：改前这一档的读数被记成"第 1 份证明"，而
            # `bits.proof=false`、`proof_text=""` —— 三处互相打架。
            has_proof=False, proof_no=0, proof_sha256="",
        )
        return out

    def _attach_proofs(self, stmt_id: str, entries: list[dict],
                       canonical: str = "", bits: Mapping | None = None,
                       proof_no: Any = 1) -> dict:
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

        ## 换正文那一笔的两条硬口径（2026-11-03，87 真机暴露的漏洞）
        ① `optimized=true` 只能在"这一份正文已经有签、且那一签盖的就是它"时打
        （判据只在 `evidencebits.optimized_signature`，`_optimized_gate` 是它的打桩点）。
        不满足 ⇒ 整笔受控拒绝、`optimized_blocked` 说原因（`no_sign` / `sha_mismatch`），
        在册正文一个字都不动（不许"落个 false 然后照样换"）。
        ② 换正文这一笔不许把 `reviewed_by_proof` / `reviewed_sha_by_proof` 清掉：
        `_bits_after_canonical_write` 把这一笔按现行正文认到的签（`fresh` 里那几格）
        带过来，没认到的保留旧的（读侧按 sha 判 stale）—— 两边都不是"清空即通过"。

        ## 收录那一笔：第 2 位跟着正文一起翻（2026-11-06，真机 R-mk-infinite-92）
        板上 `b-register@<号>@<被签正文 sha>` 收口走的是秘书的"并进在册命题"支
        （`Secretary._merge_into_proposition`）：它只写 `proof_text`（canonical 从空
        补上 / 第 N 份证明进清单），不写 `bits`。改前这一格只在 `canonical_changed`
        时才合并位 ⇒ 收录完那一行是 `proof=false`，而 V 那一签只翻第 3 位 ⇒
        `reviewed=true ∧ proof=false ∧ grade=conjecture` 的自相矛盾（等级永远到不了
        `pre_theorem`）。现在那一支也调本函数（`register_statement` 的 `merged` 支），
        本格在"行上已有正文而第 2 位还没翻"时用
        `evidencebits.bits_after_proof_recorded` 把第 2 位翻真、把这一笔认到的第 3 位
        带过，并同一笔写顶层收录回执（`proof_no` / `proof_sha256`）—— 等级仍由
        `_grade_recomputed_from_signature` 现算（穷举通道照旧到 `theorem`）。
        """
        out: dict = {"written": False, "attached": [], "already": [],
                     "refused": "", "reason": "", "canonical_differs": False,
                     "canonical_written": False, "canonical_pending": False,
                     "canonical_history": [],
                     #: 换正文那一笔的优化态读数（逐份 + 被拦下的原因）。没换正文时是
                     #: 空列表 / 空串 —— 老返回形状因此逐字不变。
                     "optimized": [], "optimized_blocked": "",
                     #: 第 4 位这一笔同步过没有（见 `_bits_with_formal`）：它与
                     #: "写了什么"分开报，因为"没验过"与"验过没变化"都是 `False`，
                     #: 而两者该给调用方的话不同（前者不用再登记一次）。
                     "formal_synced": False, "formal_paths": {},
                     #: 2026-11-05（业主）：签成之后在同一笔里按现行签把 `evidence_kind`
                     #: 重算上去的读数（键存在 = 这一笔真升了；`{}` = 没动）。
                     #: 判据只有一处（`verifications._grade_recomputed_from_signature`，
                     #: 与签发那一笔共用），这一格只负责把它接在"正文落进那一行之后"。
                     "grade_recomputed": {},
                     #: 这一笔把第 2 位（有证明）翻上去没有：收录那一条路（秘书判同一条
                     #: ⇒ 并进在册那行）只写正文、不写 `bits`，这一格就是"补翻第 2 位"
                     #: 那一笔的读数（判据见 `evidencebits.bits_after_proof_recorded`）。
                     "proof_collected": False,
                     #: 这一笔把第 2 位补翻时合并出来的那整份位落盘了没有（第 3 位那几张
                     #: 表也跟着来）；"翻了"与"合并了"分开报：反真空把翻位那一步摘掉时，
                     #: 合并出来的那份位仍要落盘 —— 那才是现场的 `reviewed=true ∧
                     #: proof=false` 形状（判据 `test_b_register_collects_the_proof_bit` 的 b）。
                     "bits_synced": False,
                     #: 顶层收录回执：`{proof_no, proof_sha256}`（这一行现在这一份证明是
                     #: 哪一号、正文指纹是什么）。只在真写进去时出现。
                     "proof_receipt": {}}
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
        # ---- 2026-11-04（业主裁定：正文必须由手稿承载）：这一格也写 `proof_text` ----
        #
        # `_attach_proofs` 是 B 的写侧唯一一处直接改 `statements`（秘书的字段白名单里没有
        # `proofs`），所以它不能只靠 `Secretary.record_statement` 那道闸：新建 / 升档 /
        # 重复支的 canonical 覆盖、#p2 及以后的正文追加，最后都落在这一格里。判据与秘书
        # 那一处共用同一个函数（`proof_text_manuscript_sign_gate`），不另写一份。
        from ..secretary import proof_text_manuscript_sign_gate as _intake_gate

        _intake_targets: list[tuple[int, str]] = []
        if raw_want.strip():
            _intake_targets.append((1, raw_want))
        # #p2 及以后的正文由 `_unsigned_proof_gate` 在登记入口按份判签（它看得见
        # `proofs_listed`）；这一格只补 canonical —— 否则"先写 #p2、再让 V 签 #p2"
        # 这个两阶段次序会被闸反锁死（签 #p2 要求行里已有 #p2）。
        for _no, _text in _intake_targets:
            _got = _intake_gate(store, statement_id=stmt_id, proof_text=_text,
                                proof_no=_no, defer_without_sign=bool(bits))
            if _got.get("refused"):
                out["refused"] = str(_got.get("refused") or "")
                out["reason"] = str(_got.get("reason") or "")
                out["proof_text_gate"] = dict(_got)
                return out
        #: 第 4 位的台账（L 的 `record` 落的那张表）。在事务外先读好：它只被
        #: `_bits_with_formal` 用来算"这一位现在是什么"，不参与这一笔的内容判据。
        experiments = [dict(r) for r in store.rows("experiments")]
        # ---- 2026-11-08（业主：「B 实际只有台账的只读权限，B 的任何所谓写台账的路实际上
        # 都由 B 的秘书洗过」）：这一笔不再由 B 开事务 —— 行变换交给秘书的
        # `land_statement`（它开事务、读现行行、判"改了哪几格"、写盘）。
        # `_transition` 拿到的 `found_row` 是事务内读的那一行：下面的"读—判—写"仍在
        # 同一把锁里，与收口前逐字同序（原先 `with store.tx` 里那一段原样搬进闭包）。
        sec = self._statement_secretary()
        if sec is None:
            out["reason"] = ("这一趟没有秘书 ⇒ 证明清单 / 正文写不进去（写入侧是 B 的活，"
                             "落盘归秘书：`Secretary.land_statement`；不许退回 B 自己写）"
                             + (f"；{self.secretary_problem}" if self.secretary_problem else ""))
            out["canonical_pending"] = bool(want)
            return out

        def _transition(found_row: Any) -> dict:
            if found_row is None:
                if nothing_to_attach:
                    # 这一笔本来就不带东西（只为第 4 位同步而来），行不在就没什么可同步：
                    # 不编一句"清单无处可挂"（那会把"没东西可挂"说成"挂失败了"）。
                    return {"write": False, "result": out}
                out["reason"] = (f"`statements` 里没有 {stmt_id} ⇒ 证明清单无处可挂"
                                 "（行没落成，清单也就没有落点）")
                out["canonical_pending"] = bool(want)
                return {"write": False, "result": out}
            row = dict(found_row)
            have_raw = str(row.get("proof_text") or "")
            have_canon = have_raw.strip()
            # 逐字比，不按去空白比：只改了首尾空白的稿也是一次改稿，静默不写会让
            # 调用方以为交上去了，而盘上那一份的 sha 没变（签名也不会转 stale）。
            canonical_changed = bool(want) and raw_want != have_raw
            if canonical_changed:
                _abort = self._apply_canonical_proof(
                    row=row, out=out, raw_want=raw_want, stmt_id=stmt_id,
                    have_raw=have_raw, have_canon=have_canon, bits=bits, store=store)
                if _abort is not None:
                    return _abort
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
                    return {"write": False, "result": out}
                listed.append({"proof_no": no, "text": text,
                               "created_at": str(entry.get("created_at") or S.now_iso())})
                out["attached"].append(no)
                #: 新挂上来的一份证明 = 刚交来的机械录入那一版 ⇒ 优化态显式 `false`
                #: （不是缺格：缺格与 false 在第二阶段读起来是两件事，见
                #: `evidencebits.OPTIMIZED_STATES`）。翻真只发生在它被换正文那一笔。
                row["bits"] = _EB.with_optimized_flag(row.get("bits") or {}, no, False)
                out.setdefault("optimized", []).append(
                    {"proof_no": int(no), "optimized": False, "state": "fresh",
                     "why": "这一份刚挂上来（机械录入那一版），还没洗过"})
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
            # ---- 收录：正文已在行上 ⇒ 第 2 位与"收录回执"同一笔落下 ---------------
            #
            # 现场（`projects/R-mk-infinite-92` 的 `statements:000000`，2026-11-06）：
            # 板上 `b-register@000000@58cf…` 收口那一笔走的是秘书的"并进在册命题"支
            # （`Secretary._merge_into_proposition`：canonical 从空补上），它只写
            # `proof_text`；而改前这一格只在 `canonical_changed` 时才合并 `bits`
            # ⇒ 收录完这一行仍是 `proof=false` / `grade=conjecture`。V 那一签后来只能
            # 翻第 3 位（`_reviewed_statement_row`），于是盘上出现
            # `reviewed=true ∧ proof=false ∧ proof_text 非空` 的自相矛盾。
            #
            # 判据：这一行现在有正文（正本）⇒ 第 2 位为真（读数），第 3 位那几张表按
            # 这一笔认到的签带上；实现只有一处（`evidencebits.bits_after_proof_recorded`
            # ⇒ `normalize_raw` / `derive_grade`），这里不另算一份。
            # 顶层 `proof_no` / `proof_sha256` 是收录回执（这一行现在这一份证明是哪一号、
            # 正文指纹是什么），与第 2 位同一笔写、同一次读的正文现算 —— 不是第二份真值。
            _no_receipt = 1
            try:
                _no_receipt = int(_VR.as_proof_no(proof_no) or 0) or 1
            except (TypeError, ValueError):
                _no_receipt = 1
            _body_now = str(_VR.proof_text_of(row, _no_receipt) or "")
            #: 这一行现在真有一份正文（canonical 或 #pN）—— 回执、第 2 位、按签重算
            #: 都只在"有一份正文"时成立。E 的普通数值档（e-num）没有证明正文 ⇒ 恒假。
            _body_present = bool(_body_now.strip())
            #: 2026-11-08：两种"这一笔要把位带上去"的形态 ——
            #: ① 第 2 位还没翻（收录那一笔）；② 第 2 位已真、而这一笔刚认到第 3 位
            #: （V 签在稿上、B 收录时读到）。改前只认 ① ⇒ 后者永远停在 reviewed=false，
            #: 那正是"V 签了但 B 没收录"永远收不了口的原因。
            _needs_proof = not bool(dict(row.get("bits") or {}).get("proof"))
            _needs_review = (bool(dict(bits or {}).get("reviewed"))
                             and not bool(dict(row.get("bits") or {}).get("reviewed")))
            if (bits is not None and _body_present
                    and (_needs_proof or _needs_review)):
                _collected = _EB.bits_after_proof_recorded(
                    row.get("bits"), delivered=bits, proof_process=_body_now,
                    kind=str(row.get("kind") or ""))
                if _collected and _collected != dict(row.get("bits") or {}):
                    row["bits"] = _collected
                    out["bits_synced"] = True
                if bool(_collected.get("proof")):
                    out["proof_collected"] = True
            # ---- 收录回执（2026-11-08 缺陷 ③）：与"第 2 位这次翻没翻"解耦 -----------
            #
            # 改前回执写在第 2 位翻真那一支里 ⇒ 一条新建的"命题 + 证明"
            # （`bits.proof` 一开始就为真、`_needs_proof` 为假）永远拿不到回执：
            # 返回值说第 1 份，而 `statements` 顶层的 `proof_no` / `proof_sha256`
            # 一个字节都没写（盘上读 null）。现在只要这一行真有一份正文，就把它的号
            # 与现算的 sha 写到顶层；号只从这一笔的落点 `proof_no` 读，不猜。
            # e-num 那一档 `_body_present` 为假 ⇒ 顶层不写 —— 没有证明就不许读出
            # "第 1 份证明"。
            if _body_present:
                _want_sha = _PR.proof_sha(_body_now)
                if (str(row.get("proof_sha256") or "") != _want_sha
                        or int(row.get("proof_no") or 0) != int(_no_receipt)):
                    row["proof_no"] = int(_no_receipt)
                    row["proof_sha256"] = _want_sha
                    out["proof_receipt"] = {"proof_no": int(_no_receipt),
                                            "proof_sha256": _want_sha}
            # ---- 2026-11-05（业主）：签成之后就升档，不再等第二条命令 --------------
            #
            # 现场（`temp/rmk90-audit/REPORT-R-mk-infinite-90-20261105.md` §二.3 / A-1）：
            # 000014 / 000016 的 `register_statement:proofs` 把正文与 bits 写进来了，而
            # `evidence_kind` 停在 `heuristic` —— 升档要靠秘书 `record_statement:upgrade`
            # 再跑一次，而那一条没人跑（000015 / 000018 / 000019 连正文都没回填）。
            #
            # 位置：正文（canonical 覆盖 / 新挂的 #pN）已经写进 `row`、bits 也已经认过签
            # 之后，`tx.upsert` 之前。判据只有一处：`verifications.proof_review_gap`
            # （写入期闸 / 审计 / 收工门读的同一处），本格只调
            # `_grade_recomputed_from_signature` 那一个实现 —— 与签发那一笔共用，
            # 于是"签成之后就升档"在两条路上是同一件事，不会长出第二套口径。
            #
            # 三态（由那个函数保证）：没签 / 签的是旧版 ⇒ 不动（"没凭据"不是"不准升"）；
            # 已经是 proof / proof_review ⇒ 不动（幂等，不写第二个时间戳）；
            # 读不出来 ⇒ 不动且 `reading.checked=False`（"没查成"不是"不够格"）。
            _recomputed: dict = {}
            if _body_present:
                _recomputed = _VR._grade_recomputed_from_signature(
                    row, root=getattr(store, "root", ""), proof_no=_no_receipt)
            if _recomputed.get("reading"):
                row = dict(_recomputed.get("row") or row)
                # 读数必须落盘，不只是"算过"：这一格与 `sign_statement` 那一笔
                # （`verifications.py` 的 `new[GRADE_RECOMPUTED_KEY] = reading`）
                # 是同一件事的两个落点。改前这里只把 row 拷回来、丢掉了 reading 本身，
                # 于是"B 登记期按签重算等级"在返回值里说得清、在盘上查不到 ——
                # 而这条回执正是"这一档凭什么"的唯一可读凭据。
                row[_VR.GRADE_RECOMPUTED_KEY] = dict(_recomputed["reading"])
                out["grade_recomputed"] = dict(_recomputed.get("reading") or {})
            #: 三个"这一笔写什么"的来源全空 ⇒ 一个字都不写（`nothing_to_attach` 那一笔
            #: 也走这条判据：第 4 位同步出变化时 `formal_synced` 为真，于是它照样落盘）。
            if (not out["attached"] and not canonical_changed and not out["formal_synced"]
                    and not out["grade_recomputed"] and not out["proof_collected"]
                    and not out["bits_synced"] and not out["proof_receipt"]):
                return {"write": False, "result": out}
            if out["attached"]:
                row[_VR.PROOFS_KEY] = listed
            out["canonical_written"] = bool(canonical_changed)
            return {"write": True, "row": row, "result": out}

        landed = sec.land_statement(
            stmt_id, _transition, op="attach_proofs",
            note=f"agent_b.register_statement:proofs:{stmt_id}")
        if not landed.get("checked"):
            # 秘书那一层拒了这一笔（行不在 / 改的格越界）：如实回拒，不许当写过了。
            out["refused"] = str(landed.get("refused") or "statement_land_refused")
            out["reason"] = str(landed.get("reason") or "")
            return out
        if landed.get("written"):
            out["written"] = True
        return out

    def _apply_canonical_proof(self, *, row: dict[str, Any], out: dict[str, Any],
                               raw_want: str, stmt_id: str, have_raw: str,
                               have_canon: str, bits: Mapping | None,
                               store: Any) -> dict | None:
        """「换正文」那一段（`_transition` 的内层，只搬移）。

        2026-11-08 从 `_transition` 拆出：换正文之前先核签、换、认优化标记、判旧签不再
        算数是同一笔的四步，合起来 130 余行；拆出来之后 `_transition` 回到 200 行以内 ——
        体量基线是读数，不许为了它抬（业主口径：拆函数，不抬基线）。

        返回 None = 接着走（正文已在位）；返回一个 dict = 这一笔到此为止，调用方原样返回。
        """
        # ---- ① 换正文之前先核：这一份正文有没有签、那一签盖的是不是它 ----
        #
        # 业主 2026-11-03（87 真机暴露的漏洞）：「洗过的肯定能保证V签」
        # 「优化后拿V签，用有V签的优化后的证明精准替换原证明并将那条证明记为
        # 已优化」⇒ `optimized=true` 的前提是"这份替换进来的正文已经有签"。
        # 改前这一格拿 `_signature_covers`（只读 V 的台账）当判据，于是台账里
        # 有三次「成立」、而命题行上没有那一签时，true 照样被打上（87 的
        # 000001 / 000002 / 000004 / 000007）。判据现在只有一处：
        # `evidencebits.optimized_signature` —— 逐份表 `reviewed_by_proof`
        # 为真，且 `reviewed_sha_by_proof` 等于现在这一份正文的 sha。
        #
        # 不满足时正文也不换：一次"优化后的精准替换"若带不来签，那它就不是
        # 替换，只是把一份没签的稿盖掉在册那一份（那会让盘上多一份谁也追不到的
        # 正文）。读数给 `optimized_blocked`（no_sign / sha_mismatch），
        # 整笔受控拒绝 —— 不是静默落 false 然后照样换。
        #
        # 先按现行正文的 sha 再认一次签（第 ② 处的另一半）：主路在上面已经
        # 认过手稿块 / pending，这里补的是"V 曾对这份正文连判到发签、签文件在
        # 盘上"那一档（真机 87：正文换上来的时候签已经发过了）。判据仍是
        # `vsigns.bits_after_sign` 一处（sha 相符 + 连续次数 + 命题号相符），
        # 这一格只把它的结论带进这一笔的 bits。
        fresh_bits = dict(bits or {})
        try:
            from agentflow import vsigns as _VS

            _claimed, _sign_claim = _VS.bits_after_sign(
                fresh_bits, root=getattr(store, "root", ""),
                proof_text=raw_want, statement_id=str(stmt_id), proof_no=1,
                kind=str(row.get("kind") or ""), store=store)
            if _sign_claim.get("applied"):
                fresh_bits = _claimed
            out["sign_claim"] = {
                "checked": bool(_sign_claim.get("checked")),
                "found": bool(_sign_claim.get("found")),
                "applied": bool(_sign_claim.get("applied")),
                "artifact_sha": str(_sign_claim.get("artifact_sha") or ""),
                "why": str(_sign_claim.get("why") or "")}
        except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许折成"没签"
            out["sign_claim"] = {
                "checked": False, "found": False, "applied": False,
                "why": (f"认签那一格没查成（{type(exc).__name__}: {exc}）"
                        "⇒ 这一格不是「没有签」")}
        # ---- 第二次认签：签文件没认到、而台账里这一份已经签满 ----
        #
        # E 那条路（真机 87 同形）的签文件是"未在册"形态：`artifact_sha` 对得上、
        # 但 `statement_id` 是空的（签是在命题还没登记时发的、落盘那一刻还没绑号）。
        # 这时 `bits_after_sign` 按"同一段正文被别的命题复用不算签过"会拒认 ——
        # 而 V 的台账里这一份明明连判到发签。判据仍是唯一那一处
        # （`verifications.review_standing`）；这里只做"按现行正文重新判定后重写"
        # 那一步（业主 2026-11-03 的第 ② 处），只认 `state="signed"`：
        # `holding`（票数没到）不落这两格 —— 有签与"审过一票"是两件事。
        want_sha = _PR.proof_sha(raw_want)
        if str(_EB.reviewed_sha_by_proof(fresh_bits).get(1) or "") != want_sha:
            _standing_now = self._review_after_rewrite(
                getattr(store, "root", None), stmt_id=str(stmt_id),
                proof_text=raw_want)
            if str(_standing_now.get("state") or "") == "signed":
                from agentflow import vsigns as _VS

                fresh_bits = _VS.bits_with_review(
                    fresh_bits, proof_no=1, proof_sha256=want_sha,
                    kind=str(row.get("kind") or ""),
                    verification_id=str(_standing_now.get("verification_id") or ""),
                    evidence=(f"{_VR.VERIFICATIONS_DIR}/{stmt_id}.jsonl"))
                out["sign_claim"] = {
                    "checked": True, "found": True, "applied": True,
                    "artifact_sha": want_sha,
                    "why": ("台账里这一份已连续签满（`review_standing=signed`）⇒ "
                            "按现行正文重写 `reviewed_by_proof` / "
                            "`reviewed_sha_by_proof`（不是清空即通过）")}
        candidate = _bits_after_canonical_write(row, fresh_bits)
        gate = _optimized_gate(candidate, proof_no=1, proof_text=raw_want)
        out["optimized"] = [{
            "proof_no": 1,
            "optimized": bool(gate.get("optimized")),
            "state": ("true" if gate.get("optimized") else "false"),
            "blocked": str(gate.get("optimized_blocked") or ""),
            "why": str(gate.get("why") or ""),
        }]
        out["optimized_blocked"] = str(gate.get("optimized_blocked") or "")
        if not gate.get("optimized"):
            out["canonical_differs"] = True
            blocked = (out["optimized_blocked"]
                       or _EB.OPTIMIZED_BLOCKED_NO_SIGN)
            out["optimized"][0]["blocked"] = blocked
            out["refused"] = (
                "proof_without_v_sign"
                if blocked == _EB.OPTIMIZED_BLOCKED_NO_SIGN
                else "proof_sha_mismatch")
            out["reason"] = (
                "这一笔要换掉在册的 canonical 正文，而它没有资格被记成「已优化」："
                + str(gate.get("why") or "")
                + "。业主 2026-11-03 的口径是「优化后拿V签，用有V签的优化后的"
                "证明精准替换原证明」—— 没有签的正文不许盖掉在册那一份，也不许"
                "打 `optimized=true`。两条出路：① 让 V 先签这一份新正文"
                "（`V.verify_proof` 带 `statement_id` + `proof_no`，签到位后再来替换）；"
                "② 确实只是改稿、不是优化替换 ⇒ 仍要一份覆盖新正文的签"
                "（改稿要重签是既有口径）。盘上正文一个字都没动"
                "（`proof_text` 仍是旧那一份，`proof_history` 也没有多一条）。")
            return {"write": False, "result": out}
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
        # `candidate` 就是"换完正文之后这一行的 bits"（上面为判 gate 已经算过；
        # 纯函数，不读 proof_text），不再算第二遍。
        if candidate:
            row["bits"] = candidate
        # ---- 换正文 ⇒ 这一份的优化态（业主 2026-11-02 的两阶段录入） ----
        #
        # 口径（`draft/179` 二之一）：「洗过的肯定能保证V签。所以二阶段只用看是否
        # 优化过」。上面那道核已经判过"这一份有签、签的就是它" ⇒ 这里落 `true`；
        # 落盘的 true 与 `reviewed_by_proof` / `reviewed_sha_by_proof` 是同一笔
        # 事务写下去的（第 ② 处：那两张表不许被换正文这一笔清掉）。
        row["bits"] = _EB.with_optimized_flag(row.get("bits") or {}, 1, True)
        out["optimized_blocked"] = ""
        # ---- 改写过 ⇒ 旧签不算数（业主 2026-10-26 Q14 的唯一硬机制）。
        #
        # 判据不在这里：`verifications.review_standing` 是唯一判定口（它拿
        # 现行正文的 sha 与台账覆盖集比）。这一格只做两件写之外的事 —— 把结论
        # 读出来、把"派 V 重新签"写进返回值。读数不是"框架把签删了"：台账
        # 一行都不动，旧签仍可查，只是不再算数（读侧现算）。
        rewritten = self._review_after_rewrite(
            getattr(store, "root", None), stmt_id=str(stmt_id),
            proof_text=raw_want)
        out["review_standing"] = dict(rewritten)
        out["resign_required"] = bool(rewritten.get("resign_required"))
        out["rewrite_note"] = _rewrite_note(rewritten)
        return None

    @staticmethod
    def _unsigned_proof_gate(*, origin: str, lit_id: str, proof_text: str,
                             proofs_listed: Any, row: Mapping | None,
                             v_sign: Mapping, store: Any,
                             proof_no: Any = 1) -> dict:
        """这一笔要写进台账的证明正文，每一份都得有一份覆盖它的签（业主 2026-11-02）。

        ## 为什么闸设在这里、且不看 kind / 不看来源

        85 暴露的那条绕行不是"某一种来源漏了"，而是「闸的判据选错了轴」：
        `_self_authored_gate` 判的是 `kind`（猜想放行），F 那次闸判的是手稿来源
        （carried_by_D / disk），于是"进程内直交 + 声称是猜想 + 无签"这一组合整条穿过。
        业主的裁决是「机械录入那一版也必须有签（F 的签 或 文献编号）」——判据的真身是
        "「要写进去的那份正文有没有签」"，与它叫什么 kind、从哪条路来都无关。

        ## 判据（三档，不折平）

        - 这一笔没有要写的证明正文（正文与在册逐字相同 / 根本没给）⇒ `applicable=False`：
          不是"查过了、有签"，而是"这一笔没有内容要写"。D 的每一次交付都是这一档 ——
          它交的是在册那一行的正文，干的是读稿登记依赖面（那条路不能因此被堵死）。
        - 文献侧（`origin="external_lit"` 且有 `source_lit_id`）⇒ 免签：占位签就是
          文献编号（`draft/179` 二之二「假V签，但要允许进台账」）。
        - 其余 ⇒ 每一份要写的正文都要有覆盖它的签：唯一判据是
          `vsigns.sign_reading.state == "signed"`（`_signature_covers`）。D268 批 2
          起手稿块不再是旁路：块只是渲染视图，认签必须有可复算的凭据。缺一份就整笔拒。

        ## 为什么拒而不是"降档收下"

        业主原话：「不许再出现 proofs=0 绕行」。降档收下就是那条绕行换了个名字
        ——85 的 13 条正是"heuristic 收下、再进论文"来的。
        """
        out: dict = {"applicable": False, "refused": "", "reason": "", "reading": {}}
        now = dict(row or {})
        listed = {}
        for item in (now.get(_VR.PROOFS_KEY) or []):
            if isinstance(item, Mapping):
                try:
                    listed[int(item.get("proof_no") or 0)] = str(item.get("text") or "")
                except (TypeError, ValueError):
                    continue
        pending: list[tuple[int, str]] = []
        want = str(proof_text or "")
        #: 这一份正文该落在哪个证明号上：交付里给了号就以它为准（缺口 ①）。
        #: 认签记在 `reviewed_by_proof[证明号]` 上，免签那一门也必须对同一个号开，
        #: 否则 `#p2` 会拿 `#p1` 的签当通行证（两边的号分家是静默的）。
        try:
            want_no = int(proof_no or 1)
        except (TypeError, ValueError):
            want_no = 1
        if want.strip() and want != str(now.get("proof_text") or ""):
            pending.append((want_no, want))
        for entry in (proofs_listed or []):
            if not isinstance(entry, Mapping):
                continue
            try:
                no = int(entry.get("proof_no") or 0)
            except (TypeError, ValueError):
                continue
            text = str(entry.get("text") or "")
            if not text.strip():
                continue
            if listed.get(no) is None or listed.get(no) != text:
                pending.append((no, text))
        out["reading"] = {"applicable": bool(pending),
                          "origin": str(origin or ""),
                          "source_lit_id": str(lit_id or ""),
                          "proofs": [{"proof_no": int(no), "signed": False}
                                     for no, _ in pending],
                          "why": ""}
        if not pending:
            out["reading"]["why"] = ("这一笔没有要新写的证明正文（与在册逐字相同 / 没给）"
                                     "⇒ 这一格不适用")
            return out
        out["applicable"] = True
        if str(origin or "") == "external_lit" and str(lit_id or "").strip():
            out["reading"]["why"] = ("文献侧：V 签位填文献编号（占位签）⇒ 允许入台账，"
                                     "第二阶段再逐个优化重写拿真签")
            for one in out["reading"]["proofs"]:
                one["signed"] = True
                one["sign"] = "placeholder_lit"
            return out
        signed: dict[int, str] = {}
        if bool((v_sign or {}).get("applied")):
            # 手稿签块认下来的一签：它盖的就是这一笔交来的那一份正文（`bits_after_sign`
            # 按同一个证明号记账），所以免签只开给那一个号。
            signed[want_no] = "manuscript_sign_block"
        for no, text in pending:
            if no in signed:
                continue
            got = _RegisterStatement._signature_covers(
                store, stmt_id=str(now.get("stmt_id") or ""), proof_no=no, text=text)
            if got.get("signed"):
                signed[no] = "verification_ledger"
        for one in out["reading"]["proofs"]:
            one["signed"] = int(one["proof_no"]) in signed
            if one["signed"]:
                one["sign"] = signed[int(one["proof_no"])]
        missing = [int(no) for no, _ in pending if int(no) not in signed]
        if not missing:
            out["reading"]["why"] = "每一份要写的正文都有签覆盖（" + "、".join(
                f"#{no}:{how}" for no, how in sorted(signed.items())) + "）"
            return out
        out["refused"] = "proof_without_v_sign"
        no_list = "、".join(f"#{no}" for no in missing)
        out["reason"] = (
            f"这一笔要写进台账的证明正文里，{no_list} 没有一份覆盖它的 V 签 ⇒ 整笔不写。"
            "业主 2026-11-02 的口径是「机械录入那一版也必须有签（F 的签 或 文献编号），"
            "不许再出现 proofs=0 绕行」—— 判据是这份正文有没有签，与 kind（猜想不是"
            "免签通行证）、与来源（param / carried_by_D / disk / 进程内直交）都无关。"
            "三条出路：① F 先拿签（F 用 `summon` V 的 `verify.verify_proof`，"
            "带 `proof_manuscript`；签到位后签落回稿，再交来入库）；"
            "② B 自己把这一份送 V（`V.verify_proof` 带 `statement_id` + `proof_no`），"
            "拿到「成立」再交；③ 这一条是文献来的 ⇒ 按 `origin=\"external_lit\"` + "
            "`source_lit_id` 登记（V 签位填文献编号 = 占位签，允许入台账）。"
            "读数见 `proof_gate`（哪几份缺签、每份的出路）。")
        out["reading"]["why"] = out["reason"]
        out["reading"]["missing"] = missing
        return out

    @staticmethod
    def _proof_no_from_delivery(*, manuscript_text: str = "",
                                manuscript_carried: Mapping | None = None
                                ) -> tuple[int, str]:
        """这一笔交付说的"第几份证明" ⇒ `(号, 来源)`；两处都没有 ⇒ `(0, "fallback")`。

        ## 来源三档（写进读数，不许折平）
        - `crafted`：手稿稿头那一行 `- 证明号：N`（`depsection.manuscript_proof_no`）。
          作者自己写的号最权威 —— 它知道这一份是这条命题的第几条证明。
        - `carried`：D 的携带单第四列（`read_carried_manuscript` 命中的那一行）。
          D 转述作者写的号（或者按盘上事实填的号）。
        - `fallback`：两处都没有。调用方据此走回退口径（canonical 空则 #p1 /
          否则最大号 + 1），不在这里替它猜一个号。
        0 是"交付里没有号"的哨兵（与 `verifications.as_proof_no` 的 0 同一个意思）：
        读侧折成 1 会让"没写"与"写了第 1 份"分不开。
        """
        crafted = 0
        try:
            crafted = int(_DS.manuscript_proof_no(str(manuscript_text or "")) or 0)
        except (TypeError, ValueError):
            crafted = 0
        if crafted >= 1:
            return crafted, "crafted"
        try:
            carried = int((manuscript_carried or {}).get("proof_no") or 0)
        except (TypeError, ValueError):
            carried = 0
        if carried >= 1:
            return carried, "carried"
        return 0, "fallback"

    @staticmethod
    def _signature_covers(store: Any, *, stmt_id: str, proof_no: Any, text: str) -> dict:
        """这一份正文有没有一份覆盖它的 V 签（D268 批 2 起判据只有 `sign_reading`）。

        业主 2026-11-02 的两阶段录入把"洗过"与"有签"绑成一句话：「洗过的肯定能保证V签」。
        于是 `optimized=true` 这一格背后必须真有一签 —— 判据只认
        `vsigns.sign_reading.state == "signed"`（签文件必须可复算；手稿块只是视图）。
        这里只把结论翻成布尔 + 三态读数，不另写第二份判据。

        三态（不折平）：`signed` ⇒ true；其余（`holding` / `retry_report` /
        `unissued` / `stale` / `unbacked` / `borrowed` / `unsigned` / `unreadable`）
        ⇒ false，并给 `why`（拒收理由由调用方原话带回）。
        """
        out: dict = {"checked": False, "signed": False, "state": "unreadable",
                     "votes": 0, "need": 0, "why": ""}
        root = getattr(store, "root", None) if store is not None else None
        sid = str(stmt_id or "").strip()
        if root is None:
            out["why"] = "没有工作区根 ⇒ 这一格没查成（不当作签过）"
            return out
        from .. import vsigns as _VS

        try:
            # `sid` 可以为空（未在册）：那一档按正文 sha 找 pending 凭据
            # （`sign_reading` 的 `statement_id=""` 支），不要求先有号。
            got = dict(_VS.sign_reading(root, statement_id=sid, proof_text=text,
                                        proof_no=proof_no))
        except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许折成"没签过"
            out["why"] = f"签的读数没读成（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
            return out
        state = str(got.get("state") or "unsigned")
        out.update(checked=bool(got.get("checked")), state=state,
                   votes=int(got.get("votes") or 0), need=int(got.get("need") or 0),
                   why=str(got.get("why") or ""))
        out["signed"] = state == "signed"
        return out

    @staticmethod
    def _review_after_rewrite(root: Any, *, stmt_id: str, proof_text: str) -> dict:
        """正文被改写之后，那一签现在算不算数（唯一判定口：`verifications.review_standing`）。

        ## 为什么不在这里判 sha
        判据只有一处：`verifications.review_standing`（现行正文的 sha 与台账覆盖集的
        sha 比，`verifications.py` 里那条 `stale` 分支）。这一格只做两件事 —— 把结论
        翻成"要不要重签"，以及把"没查成"与"签过过期"分开。自己再比一次 sha 就是第二个
        判据；两处一旦漂，"这一签算不算"会同时有两个答案，而没有任何东西会报。

        ## `resign_required` 的三态（不折平）
        `signed` ⇒ False（V 的签盖的就是这一份）；`stale` / `rejected` / `unsigned`
        ⇒ True；`unreadable`（台账读不出来）⇒ True 且 `checked=False` —— 没查成不许
        读成"签过了"，与 `verifications` 那边"签没落地 ⇒ `re_sign_required`"同一条口径。

        ## 为什么这一格必须能被单独打桩
        "改写过 ⇒ 旧签作废"这条机制的唯一出口就是它（判据 e 把这里换成"已签"，
        b 必须当场红）。做成 `staticmethod` 就是为了让判据能在判定点上打桩，
        而不是去打"读侧算不算" —— 后者是既有链，不该被这一批改动碰到。
        """
        out: dict = {"checked": False, "state": "unreadable", "resign_required": True,
                     "verification_id": "", "proof_sha256": "",
                     "canonical_changed": True, "why": ""}
        sid = str(stmt_id or "").strip()
        if root is None or not sid:
            out["why"] = ("没有工作区根 / 没有命题号 ⇒ 查不到台账（这一格没查成，"
                          "既不当作签过、也不当作没签过）")
            return out
        try:
            got = dict(_VR.review_standing(root, statement_id=sid,
                                           proof_text=str(proof_text or ""),
                                           proof_no=1))
        except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许折成"没签过"
            out["why"] = (f"台账读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成")
            return out
        state = str(got.get("state") or "unreadable")
        out.update(checked=bool(got.get("checked")), state=state,
                   resign_required=state != "signed",
                   verification_id=str(got.get("verification_id") or ""),
                   proof_sha256=str(got.get("sha") or ""),
                   why=str(got.get("why") or ""))
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

    def _evidence_kind_on_disk(self, stmt_id: str) -> str:
        """回读那一行在盘上的 `evidence_kind`；读不到 ⇒ `"unknown"`。

        为什么必须回读（真机 82，2026-11-01 · A-4）：同一份内容再交一次、请求
        `evidence_kind="proof_review"`，而盘上那一行仍是 `heuristic`（没有 V 的连续签，
        升档没有发生）。改前 duplicate 分支把入参 `evidence_kind` 原样回给模型 ⇒
        两次回执都说 `proof_review`，模型以为档位升了，下一步去 `table.update` 改
        `quote_reason` 撞墙。回执要回答的是"盘上现在是什么档"，不是"你要什么档"；
        后者另起一格 `requested_evidence_kind`，两格同时在才读得出"要求过、没升成"。

        三态：读不到台账 / 没有这一行 / 那一格是空的 ⇒ `"unknown"`
        —— 拿请求值顶就是这次要修的那个谎。
        """
        sid = str(stmt_id or "")
        if not sid:
            return "unknown"
        # 按号定位走查口（口径一）；读不到台账不是"盘上就是这个值"（折成请求值就是撒谎）。
        got = SL.by_id(self.store, stmt_id=sid)
        if not got["checked"]:
            return "unknown"
        row = got["row"] if got["found"] else None
        kind = str((row or {}).get("evidence_kind") or "").strip()
        return kind or "unknown"

    def _register_statement_impl(
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
        # ---- 2026-11-08（业主三条裁定）：普通数值手稿的绿色通道 ----------------
        #
        # 只认 E 的 `reports/e-num-<实验号>.md`（其余路径 / 正文一律走原路）。认出来了：
        # 命题取手稿 `## 命题`（覆盖调用方传的 statement_full —— 业主：「在手稿里找命题」），
        # 证明正文空着（业主明令），档位固定成"有数值实验支持"。
        # 认出来但读不成 / 实验行对不上 ⇒ 受控拒（fail-closed，不退回"当成正文"）。
        _green = self._numeric_manuscript_channel(proof_manuscript=proof_manuscript)
        if _green.get("checked") and not _green.get("ok"):
            return _refuse(
                "numeric_manuscript_refused",
                "这一笔递的是 E 的普通数值手稿（`reports/e-num-<实验号>.md`），而它读不成："
                + "；".join(str(p) for p in (_green.get("problems") or []))
                + "。整笔不写：普通数值通道只从「手稿里的命题 + 实验行的 code_path」取内容，"
                "取不到就不许拿别的东西顶替",
                problems=list(_green.get("problems") or []),
                numeric_channel={"path": _green.get("path") or ""})
        if _green.get("ok"):
            _green_statement = str(_green.get("statement") or "").strip()
            if _green_statement:
                full = _green_statement
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
        if _green.get("ok") and origin != "own_result":
            return _refuse(
                "numeric_channel_needs_own_result",
                f"E 的普通数值手稿只能按 `origin=\"own_result\"` 登记（收到 {origin!r}）："
                "那一份是 E 自己跑出来的实验结果，不是文献里摘的 —— 按 external_lit 登记"
                "会把逐字引文那几道闸（page_range / quote_verified）套到一份数值读数上",
                numeric_channel={"path": _green.get("path") or ""})
        # ---- 2026-11-07（业主裁定 ②：lemma 那条死锁）：F 的手稿登记按内容落了
        # `- 证据种类：lemma` ⇒ B 收录已登记的同一条命题时照它落 kind。
        #
        # 为什么只在"已在册"那一档生效：首次登记受 B-2 管（自产、无出处、无签 ⇒
        # 必须从「猜想」注册，`_must_start_as_conjecture_refusal` 不许放宽）。升成
        # lemma 的那一步正是业主点名的"从猜想升成引理"：先立猜想、V 签之后按手稿头
        # 的声明升档。手稿头是 F 能表达"这是一条引理"的唯一既有落点（不新增参数面、
        # 不改动作声明）。
        if (origin == "own_result" and str(kind or "").strip() in ("", "theorem", "conjecture")
                and self._existing_statement_for(str(statement_full or "").strip()) is not None):
            declared = _declared_manuscript_kind(
                text=str(proof_manuscript or ""), root=str(self.store.root))
            if declared:
                kind_now = declared
        if _green.get("ok"):
            # 2026-11-08（业主改口径）：「普通数值实验不写 kind，一律写 conjecture」。
            # 所以这一档不看调用方声明了什么、也不拒收它：kind 直接落 conjecture。
            # 不留「你原来声明的是 theorem」这类读数 —— 那种读数会让声明继续在盘外
            # 活着，而台账上那一行永远只有 conjecture。等级由五元位现算
            # （numeric=verified ⇒ strong_conjecture）。
            kind_now = "conjecture"
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
        # 普通数值通道：`proof_text` 空着（业主明令），别的正文一律不录。
        # 调用方若还塞了 `proof_text` / `proofs`，丢掉但留痕（`dropped_content`）——
        # 静默丢掉会让"他以为交了什么"与"台账里有什么"分家。
        if _green.get("ok"):
            _dropped = []
            if str(proof_text or "").strip():
                _dropped.append("proof_text")
            if proofs:
                _dropped.append("proofs")
            if _dropped:
                _green["dropped_content"] = _dropped
            proof_text = ""
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
        manuscript_path = ""
        manuscript_text = str(proof_manuscript or "")
        # ---- `proof_manuscript` 也收「工作区相对路径」（2026-11-04，转正那一笔）----------
        #
        # 这一格在 V 的召唤参数里是路径（`verify_proof(proof_manuscript="notes/…")`），
        # 在这里历史上只当正文。同一格两个意思是真机形态分叉的根源：F 把
        # `notes/F-conj000000-proof.md` 交给 V（路径），B 这一侧没有人接得住它 ——
        # 于是"登记成功即改名"那条路一次都没走到（真机 `projects/paper-rewrite-big`：
        # F 的稿在 notes/、`reports/f-proof-*.md` 0 份）。
        #
        # 判据只看形状：单行、带 `/`、以 `.md` 结尾、落在 `notes/` 或 `reports/` 下。
        # 是路径就按盘上那一份读（读了之后 `manuscript_source` 仍是 `param` —— 这一笔的
        # 稿是调用方点名递上来的，只是它把地址给了，不是把正文粘了）；盘上没有 ⇒
        # 受控拒绝 `manuscript_missing`，绝不把路径字符串当正文继续走。
        param_manuscript_path = ""
        _raw_param = _norm_manuscript_rel(manuscript_text)
        if _is_manuscript_rel(_raw_param):
            if not (Path(getattr(self.store, "root", "") or ".") / _raw_param).is_file():
                return _refuse(
                    "manuscript_missing",
                    (f"`proof_manuscript` 给的是路径 `{_raw_param}`，而盘上没有这一份文件 ⇒ "
                     "整笔不写：路径与正文是两种写法，路径读不到时不许把它当正文继续。"
                     "处置：先让作者把稿落到工作区里，或改成把正文直接传进来。"),
                    manuscript_source=_DS.SOURCE_NONE, manuscript_path=_raw_param)
            try:
                manuscript_text = (Path(getattr(self.store, "root", "") or ".")
                                   / _raw_param).read_text(encoding="utf-8")
            except OSError as exc:
                return _refuse(
                    "manuscript_unreadable",
                    (f"`proof_manuscript` 点的 `{_raw_param}` 读不出来"
                     f"（{type(exc).__name__}: {exc}）⇒ 整笔不写（读不到的稿不能当没有）"),
                    manuscript_source=_DS.SOURCE_NONE, manuscript_path=_raw_param)
            param_manuscript_path = _raw_param
        #: 这一条命题是不是已经在册（按 `statement_full` 的规范化值，判据在
        #: `_existing_statement_for`）。为什么要在寻址之前算出来：D 的携带单是按
        #: 命题号点名的，而 B 在"命题已在册、这一笔只是把 D 的稿收进来"这一档上手里
        #: 唯一的号就是这个 —— 不把它喂进候选，携带单里的那一行永远对不上号
        #: （`read_carried_manuscript` 只剩"按正文 sha 撞"那一条路，而正文恰好也还没写）。
        redelivery = self._existing_statement_for(full)
        # ---- 2026-11-08（业主）：收录时按语义查一圈"是不是在册的同一条" -------------
        #
        # 判据只有一处（`_resolve_same_statement`：秘书挑关键词 -> 台账检索 -> 秘书认定），
        # 三处共用：普通数值收录 / 证明收录（多证明路径）/ D 的指针收录。
        # 逐字相同那一档由它直接给 found（免模型）；措辞不同的同一条由秘书在检索出来的
        # 候选里认。查到 ⇒ `redelivery` 就是那一行，下游走既有"在册"分支（`proofs`
        # 追加、proof_no 递增、签按 sha 认、等级现算都沿用既有实现）；没查到 ⇒ 新登记。
        # 有候选而没查成 ⇒ 受控拒（fail-closed，不新注册）。
        _same_search: dict = {}
        _same_adjudication: dict | None = None
        _same_applies = False
        if redelivery is None and not _green.get("ok") and param_manuscript_path:
            from ..secretary import _is_proposition_kind as _is_prop_kind
            _same_applies = bool(_is_prop_kind(kind_now))
        if _same_applies:
            _same_search = self._resolve_same_statement(
                full=full, label=label, kind=kind_now)
            if _same_search.get("refused"):
                return _refuse(
                    _R.SAME_STATEMENT_UNJUDGED,
                    "这一条要查「是不是在册的同一条命题」，而这一问没查成 => "
                    "受控拒、不新注册（没查成不等于「不是同一条」）："
                    + str(_same_search.get("why") or "")
                    + "。改法：确认秘书这一趟有判断面（模型缝 / 开关开着），"
                    "并确认 statements 台账读得出来",
                    same_statement=_same_search_reading(_same_search),
                    manuscript_source=_DS.SOURCE_NONE,
                    manuscript_path=param_manuscript_path)
            _found_row = dict(_same_search.get("_row") or {})
            if str(_same_search.get("found") or "") and _found_row:
                redelivery = _found_row
            _same_adjudication = self._same_statement_adjudication(_same_search)
        stmt_id_now = str((redelivery or {}).get("stmt_id") or "")
        # ---- D1（2026-11-05）：命中之后要问"这份稿是不是本行的" ---------------------
        #
        # 改前兜底读盘把 `derived_from`（承重链：这条证明引用了谁）与正文里的 `stmt:`
        # 引用也当成了稿的地址候选，命中就直接用 —— 真机走查 `walk-e2e` 的
        # `stmt:000001` 这么读到了 `reports/f-proof-000000.md`，把 P0 的论证当成自己的
        # `proof_text`（连 P0 的签一起借来）。候选表那一格只影响读数 `tried`（"按哪些号
        # 找过"）；用哪一份由下面两道判据决定：`_manuscript_usable`（兜底读盘命中）
        # 与 `_manuscript_is_own`（取正文那一段，见下）。
        probe_ids = _DS.candidate_statement_ids(
            derived_from=derived_from, proof_text=proof_text,
            # 手稿头那一行"命题号：stmt:<号>"：D 递过来的那一份稿用它自己的号
            # 去对携带单（`derived_from` 是承重链，不是这份稿自己的号）。
            # 在册那一行的号也进候选（2026-11-02）：D 的清单按号点名，而"已在册"这一档
            # 除了它没有别的号可用。
            extra=[_DS.manuscript_statement_id(manuscript_text), stmt_id_now])
        if manuscript_text.strip():
            # ---- D 的递交（2026-10-26 晚：「D 到 B 没有路吗？加」） -------------------
            #
            # 参数里给的这一份，如果正是 D 那份携带单里点了名、且 sha 与盘上那份相符
            # 的那一版 ⇒ 读数是 `carried_by_D`（D 带来并亲手递上来的）。
            # 这不是"猜谁调的"，判据是盘上那份报告里的三列表与这份正文逐字相符：
            # 携带单没有它、或 sha 对不上 ⇒ 照旧记 `param`（那是别的调用方直递的）。
            probe_carried = _DS.read_carried_manuscript(
                getattr(self.store, "root", ""), statement_ids=probe_ids,
                proof_text=proof_text)
            if (str(probe_carried.get("source") or "") == _DS.SOURCE_CARRIED
                    and _same_manuscript_text(probe_carried.get("text"), manuscript_text)):
                manuscript_source = _DS.SOURCE_CARRIED
                manuscript_carried = probe_carried
                manuscript_path = str(probe_carried.get("path") or "")
            else:
                manuscript_source = _DS.SOURCE_PARAM
            if param_manuscript_path:
                # 调用方点名的那一份稿：地址也要留在读数里（转正要用它）。
                manuscript_path = param_manuscript_path
        else:
            manuscript_carried = _DS.read_carried_manuscript(
                getattr(self.store, "root", ""), statement_ids=probe_ids,
                proof_text=proof_text)
            if str(manuscript_carried.get("source") or "") == _DS.SOURCE_CARRIED:
                manuscript_text = str(manuscript_carried.get("text") or "")
                manuscript_source = _DS.SOURCE_CARRIED
                manuscript_path = str(manuscript_carried.get("path") or "")
            elif bool(manuscript_carried.get("named")):
                # ---- 2026-11-02 业主：「B 按清单寻址；清单地址读不到就受控拒绝，
                #      不许换一条自己找的路」 ----
                #
                # 判据是"清单点了这一笔的名"（`named`），不是"盘上有没有一份看起来像的稿"：
                # 清单与盘不一致时，兜底读盘会把"照单收录"换成"猜一份稿"，而猜错的那一份
                # 会带着自己的依赖面与签块记到这一条命题头上（源与收方错配，读数却一切正常）。
                addressing = {
                    "checked": True, "mode": "auto",
                    "source": _DS.SOURCE_NONE, "hit": False,
                    "address": str(manuscript_carried.get("address") or ""),
                    "list_report": str(manuscript_carried.get("list_report") or ""),
                    "list_item": int(manuscript_carried.get("item") or 0),
                    "list_line": int(manuscript_carried.get("list_line") or 0),
                    "list_sha256": str(manuscript_carried.get("list_sha256") or ""),
                    "refusal": _DS.REFUSED_ADDRESS,
                    "reason": ("D 的携带单点了这一笔的号，而那个地址读不到："
                               + str(manuscript_carried.get("why") or "没有理由")),
                    "suggestion": ("让 D 重递一次研究手稿（清单里那一条的 `手稿路径` / `sha256` "
                                   "要与盘上那份 F 稿一致），并必须用 `proof_manuscript` 把这一份稿"
                                   "直接递进来（稿是必需的，不是可选项）；B 不自己去盘上另找一份。"),
                }
                return _refuse(
                    _DS.REFUSED_ADDRESS,
                    (f"二次寻址没成：{addressing['reason']} ⇒ 整笔不写"
                     "（清单是唯一寻址依据，换一条自己找的路就是猜）。"
                     f"建议：{addressing['suggestion']}"),
                    addressing=addressing,
                    manuscript_source=manuscript_source,
                    manuscript_path=str(manuscript_carried.get("address") or ""))
            else:
                # 2026-11-04：兜底读盘把这一笔的证明正文也交进去 —— 名字一路全 miss 时，
                # `read_manuscript` 会按 `## 证明` 逐行归一后的内容认 `f-proof-plan-*.md`
                # （87 的六份稿全叫计划名、按号命名的 0 份；详见 depsection 那一节）。
                manuscript_probe = _DS.read_manuscript(
                    getattr(self.store, "root", ""), statement_ids=probe_ids,
                    proof_text=proof_text)
                # ---- D1（2026-11-05）：命中之后还要问"这是不是这一条的稿" --------
                #
                # 候选表里有 `derived_from` / 正文引用（那是"试哪些名字"，读数要能说清），
                # 但用哪一份是另一道判据：号必须是本行的，或者它是按证明正文认出来的
                # （内容逐行相同 ⇒ 正文本来就是这一笔交的那一份，不存在"借别人的正文"）。
                # 改前缺这一道：`stmt:000001` 按 `derived_from=["000000"]` 读到了
                # `reports/f-proof-000000.md`（号不是本行），把 P0 的正文与签当成了自己的。
                #
                # 2026-11-05 业主裁定（D1 严格版）：依赖面也是"这一份证明"的事实 ——
                # 被引命题稿里那张 `## 依赖` 表写的是它引了谁，按到新命题头上就是一条
                # 作者从未写过的边。所以"这一笔自己带了正文"也不再放行读别人的依赖面：
                # 号不是本行的稿，一律不读（正文 / 签 / 依赖面三样都不借）。
                _hit_ok = _manuscript_usable(manuscript_probe,
                                             stmt_id_now=stmt_id_now)
                if (str(manuscript_probe.get("source") or "") == _DS.SOURCE_DISK
                        and not _hit_ok):
                    manuscript_probe = dict(
                        manuscript_probe, source=_DS.SOURCE_NONE, text="", path="",
                        why=("按名字命中的那一份稿不是这一条命题的（号不是本行）⇒ 不用它："
                             "`derived_from` / 正文引用是承重链，不是这份稿的地址。"
                             + str(manuscript_probe.get("why") or "")))
                if str(manuscript_probe.get("source") or "") == _DS.SOURCE_DISK:
                    manuscript_text = str(manuscript_probe.get("text") or "")
                    manuscript_source = _DS.SOURCE_DISK
                    manuscript_path = str(manuscript_probe.get("path") or "")
        #: 2026-11-02：二次寻址的读数（业主：「二次寻址做成自动工具，不要消耗 LLM 的 token」）。
        #: `mode` 三态 `auto` / `model` / `unknown`；本仓这条链上全程是纯函数 ⇒ `auto`，
        #: 没寻址（参数直递 / 三处都没有）⇒ 仍记 `auto` 且 `hit` 说清命中没有（"没查成"
        #: 只留给函数抛异常那一档，见下面的异常边缘）。`model` 这一档刻意留着：它一旦出现，
        #: 就是"某条路把寻址交给了模型"，读数要能把它抓出来。
        addressing = {
            "checked": True, "mode": "auto",
            "source": str(manuscript_source or _DS.SOURCE_NONE),
            "hit": bool(manuscript_text.strip()),
            "address": str(manuscript_path or ""),
            "list_report": str(manuscript_carried.get("list_report") or ""),
            "list_item": int(manuscript_carried.get("item") or 0),
            "list_line": int(manuscript_carried.get("list_line") or 0),
            "list_sha256": str(manuscript_carried.get("list_sha256") or ""),
            "refusal": "", "reason": "", "suggestion": "",
        }
        # ---- 证明号从交付里读（2026-11-04，缺口 ①） ---------------------------------
        #
        # 交付里有两处写"这是第几份证明"：手稿稿头那一行 `- 证明号：N`（作者自己写的，
        # 最权威）与 D 的携带单第四列（转述）。两处都没有 ⇒ 回退（canonical 空则 #p1 /
        # 否则最大号 + 1），并把"这一次用的是哪一来源"写进读数（`proof_no_source`）——
        # 不写的话，"读了"与"猜的"在盘上同形，而猜错的表现是静默的 #pN 错位。
        proof_no_delivery, proof_no_source = self._proof_no_from_delivery(
            manuscript_text=manuscript_text, manuscript_carried=manuscript_carried)
        #: 这一份正文该落在哪个证明号上（1 = canonical 那一格）。
        proof_no_placement = int(proof_no_delivery) if proof_no_delivery >= 1 else 1
        manuscript: dict = {}
        deps_groups: list[list[dict]] = []
        manuscript_refs: list[str] = []
        # ---- 这份稿是这条命题的稿吗（D7 的另一半，业主 2026-10-27） -----------------
        #
        # 真机读数（`projects/mp3-r2`，B 那一趟）：B 交的是 stmt:000008 的完整证明，而
        # 兜底读盘 / D 的携带单按证明正文里的 `stmt:` 引用找到的是别条命题的稿
        # （`reports/f-proof-000000.md`，头一行写着 `- 命题号：stmt:000000`）。改前那一支
        # 只管"同一条 statement_full 已在册"，不管"这份稿是谁的" ⇒ 它拿 000000 的稿给
        # 000008 做读稿登记，还把那份稿的依赖面记到 000008 头上（源与收方错配，而读数上
        # 一切正常：`manuscript_source` 只说是 carried_by_D / disk）。
        #
        # 判据用稿自己声明的那一行（`depsection.manuscript_statement_id`），不靠猜：
        #  - 声明了号、而号不是这一条 ⇒ 这份稿是别人的；
        #  - 没声明号（手写稿 / 框架渲染前的那一版）⇒ 不判所有权（`param` 直递是调用方
        #    明确递上来的，既有语义就是"这一笔用它"）。
        declared_owner = (_DS.manuscript_statement_id(manuscript_text)
                          if manuscript_text.strip() else "")
        manuscript_foreign = bool(declared_owner and stmt_id_now
                                  and declared_owner != stmt_id_now)
        # ---- 寻址来的稿正文落成 `proof_text`（2026-11-02，业主：「F侧实际上是D侧，
        #      F的东西都在D的手稿上记了一笔」） ------------------------------------
        #
        # 主路是 D 的携带单：B 按清单寻址（号 → 路径 → 文件 sha256）取到那份稿的正文。
        # 改前那份正文只进依赖面（`_receive_carried_manuscript` 写 `dependencies`，
        # 命题行一个字不动），于是"按稿收录"在盘上等于"读稿落依赖" —— 正文还得模型
        # 手工粘进 `proof_text`（真机 85 的 `000000`/`000007` 就是这样被改写的）。
        #
        # 这里只做一件事：调用方没给 `proof_text`、而寻址到了一个属于这一条的稿，
        # 就把稿里 `## 证明` 那一节当正文（`proof_text_source=manuscript`）。
        # 三点边界：① 调用方显式给了正文 ⇒ 一律以它为准（`param`）；
        # ② 稿是别人的（`manuscript_foreign`）⇒ 不取（那一档下面另有拒信）；
        # ③ 与在册那一行的正文相同 ⇒ 也算取过了（读数照给，写入由 `carries_write` 决定）。
        #
        # 2026-11-05（走查 D1）：还要问"这份稿是不是本行的"。调用方点名递上来的
        # （`param`）不算——那是"本笔给的 proof_manuscript"，允许；
        # 兜底读盘 / D 的携带单找来的，号必须是本行、或它是按证明正文认出来的。
        # 改前缺这一道：按 `derived_from` 读到的被引命题的稿被当成了这一条的稿，
        # `proof_text` 与第 3 位（签）一起借来（真机 `walk-e2e` 的 stmt:000001）。
        proof_text_source = "param" if str(proof_text or "").strip() else ""
        _body_owner_ok = (str(manuscript_source or "") == _DS.SOURCE_PARAM
                          or _manuscript_is_own(
                              manuscript_text=manuscript_text,
                              manuscript_path=manuscript_path,
                              stmt_id_now=stmt_id_now,
                              matched_by=manuscript_probe.get("matched_by")))
        #: 这份稿的 `## 证明` 三态读数（2026-11-09，D4）。
        #:
        #: 为什么单独立这一格：`proof_body` 改前缺节会退到 `## 依赖` 节、再退到整份
        #: 全文 ⇒ "没这一块"被读成"拿了别的块"。现在缺节 ⇒ `state=absent`、`body=""`：
        #: 这一笔的 `proof_text` 保持空（不拿依赖段 / 全文顶替），而"这份稿没有证明"
        #: 这件事进 `_deps_reading().manuscript_proof` 与顶层读数，调用方看得见。
        #: `unreadable` 不在这一格：文件读不出来时上面（param 路径 / 携带单 / 兜底
        #: 读盘）已经各自受控拒过 `manuscript_unreadable`，到不了这里。
        manuscript_proof: dict = (_DS.proof_body_reading(manuscript_text)
                                  if manuscript_text.strip() else {})
        if (not proof_text_source and manuscript_text.strip()
                and not manuscript_foreign and _body_owner_ok
                # 普通数值手稿没有 `## 证明` 那一节（`proof_body_reading` 会给 absent）——
                # 这一档的正文按业主口径空着，不许把「数值结果」当证明正文收进来。
                and not _green.get("ok")):
            from_manuscript = str(manuscript_proof.get("body") or "").strip()
            if from_manuscript:
                proof_text = from_manuscript
                proof_text_source = _DS.SOURCE_MANUSCRIPT
            # absent（或那一节是空的）⇒ `proof_text` 留空。这里刻意什么都不写：
            # "缺 `## 证明`"不是"证明正文为空"的另一种写法，它是没有这一块。
        #: 这一笔有没有"与在册那一行不一样"的东西要写（正文或证明清单）。有就绝不走
        #: "收方读稿登记：命题行不动"那条早退支路 —— 那条支路只负责"命题已经在册、
        #: 这一笔只是把 F 的稿交过来"，它一个字都不写正文；用它去接"改在册正文"这一笔，
        #: 形态就是真机那次"四个入口都不收"。
        carries_write = self._carries_canonical_write(
            proof_text=proof_text, proofs_listed=proofs_listed, row=redelivery)
        # ---- 2026-11-04（业主裁定 A 甲）：B 的改写要有可签的载体 --------------------
        #
        # 业主逐字：「A 甲 —— B 的改写要有可签的载体：给 B 手稿签块（与 F/E 同形）」。
        # B 改写在册正文时，正文与在册那一版不同 ⇒ 旧签 stale、台账也盖不住新正文；
        # 它需要一份自己的手稿（`reports/b-proof-<命题号>.md`，三节与 F/E 同形），
        # 由 B 派 V 审、收方秘书（`secretary:B`）落签块，B 再带这份稿入库。
        #
        # ---- D1（2026-11-10）：落稿不能在闸前 -------------------------------------
        #
        # 改前这里先调 `_land_b_manuscript` 把稿写下来，再往下过依赖面 / 自产签 /
        # 无签三道闸。后果是真机 98b 10:46:46 那笔：稿在（`reports/b-proof-000000.md`）、
        # 台账 `proof_text` 仍是空、`statements` 五行全 `conjecture` —— 被拒的登记在
        # 盘上留下了一份"看似正式的稿"。
        #
        # 为什么不能"拒了再删"：这条链在落稿点之前有二十来处受控拒绝（依赖段、档位、
        # 出处、自产签、无签……），每一处都要记得删；删除本身也会失败（占用 / 只读 /
        # 并发），删与写之间还有一个被收工门读到的窗口。而文件写不是事务资源：
        # `store.tx` 回滚不会删文件，塞进事务只会得到"回滚了但文件还在"的假一致。
        # ⇒ 顺序只能是"先把所有闸判完，再落稿"：被拒的登记一个字节都不写。
        #
        # 闸要看见"这一笔将要落的稿"（依赖段 / 证明段 / 页头），所以这里只算一份
        # 内存预览（`_preview_b_manuscript`：纯渲染、零写盘），真落稿在无签闸
        # 之后（见下面"闸全过了才落稿"那一段）。B 想要签载体就显式调
        # `own.land_manuscript`（`AgentB.land_manuscript`），不再由登记顺手造。
        b_manuscript: dict = {}
        _b_source_text = str(manuscript_text or "")
        _rewrite_body = bool(
            stmt_id_now and proof_no_placement == 1
            and str(proof_text or "").strip()
            and str(proof_text) != str((redelivery or {}).get("proof_text") or ""))
        if _rewrite_body:
            b_manuscript = self._preview_b_manuscript(
                statement_id=stmt_id_now, statement_full=full,
                proof_text=str(proof_text or ""), label=label,
                proof_no=proof_no_placement, source_manuscript=_b_source_text)
            # 预览是"将要落的稿"：闸看得见它；盘上没有这份文件（`preview=True`）。
            if not manuscript_text.strip() and b_manuscript.get("text"):
                manuscript_text = str(b_manuscript.get("text") or "")
                manuscript_source = _DS.SOURCE_DISK
                manuscript_path = str(b_manuscript.get("path") or "")
                manuscript_probe = {"checked": True, "source": _DS.SOURCE_DISK,
                                    "path": manuscript_path, "matched_by": "b_manuscript"}
        if manuscript_foreign and not carries_write:
            foreign_path = (str(manuscript_carried.get("path") or "")
                            or str(manuscript_probe.get("path") or ""))
            return _refuse(
                "manuscript_owner_mismatch",
                (f"这份稿属于 stmt:{declared_owner}，不是 stmt:{stmt_id_now} —— "
                 "它是按证明正文里的引用 / 携带单找到的，不是这条命题的稿。"
                 "拿它给这一条登记依赖面等于把别条命题的依赖记到这条头上，整笔不写。"
                 "要登记这一条的依赖面，请交这条命题自己的稿 —— 必须用 "
                 "`proof_manuscript` 把这条命题的手稿直接递进来（在册也要给稿；"
                 "内联正文现在过不了 V）；要改这一条的正文，请把 `proof_text` "
                 "一起交上来（那一笔走 canonical 覆盖，旧正文进 `proof_history`）。"),
                manuscript_source=manuscript_source,
                manuscript_path=foreign_path,
                manuscript_owner=declared_owner,
                stmt_id=stmt_id_now)
        #: 这一份稿是不是 F 的秘书洗过的那一版（业主 2026-10-26 晚：B 读到的必须是
        #: "秘书洗过"的版本，读数带 `manuscript_washed=true`）。那一行元信息由
        #: `agent_f` 在洗完之后盖进正文（`depsection.mark_washed`），跟着文件走 ——
        #: 于是"这份稿洗没洗过"在收方这里读得到，不靠调用方自述。
        manuscript_wash: dict = _DS.manuscript_wash_reading(manuscript_text) if (
            manuscript_text.strip()) else {"washed": False, "actor": "", "filled": "", "mark": ""}
        manuscript_washed = bool(manuscript_wash.get("washed"))
        #: 与来源是否逐字一致（信息格，不是门；业主 2026-10-26 Q14 的第 3 条）。
        #: 这一格只回答"改没改" —— 处置在签那一侧：改写过 ⇒ 旧签不算数 ⇒ 派 V 重新签
        #: （`_attach_proofs` 里那一段 `review_standing` / `resign_required`）。
        proof_vs_source = verbatim_vs_source(proof_text=proof_text,
                                             source_text=manuscript_text,
                                             source=manuscript_source)
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
        if manuscript_text.strip() and not manuscript_washed and not manuscript_foreign:
            if manuscript_source == _DS.SOURCE_CARRIED:
                wash_rel = str(manuscript_carried.get("path") or "")
            elif manuscript_source == _DS.SOURCE_DISK:
                wash_rel = str(manuscript_probe.get("path") or "")
            else:
                wash_rel = ""
            if _DS.needs_wash(wash_rel):
                return _refuse(
                    str(_DS.REFUSED_NOT_WASHED),
                    "这份手稿不是框架渲染的（缺洗稿元信息），请让 F 用 proof 动作重写",
                    manuscript_source=manuscript_source,
                    manuscript_path=wash_rel,
                    missing_mark=_DS.WASH_MARK.rstrip(),
                    # 2026-11-05（缺陷乙）：报文必须点名可执行的下一步。
                    # 改前那句话点的是 `proof` 动作，而 F 的动作表里没有它
                    # （`specs/f.py`：create_plan / step / status / list_plans）——
                    # 拿到拒信的调用方只能原地重交同一份稿，于是空转到
                    # `attack-000016`（15 轮）。下一步的形状与理由见
                    # `depsection.NOT_WASHED_NEXT_STEP`。
                    next_step=_DS.NOT_WASHED_NEXT_STEP,
                    next_action={"tool": "framework_summon", "role": "F",
                                 "action": "step",
                                 "params": {"plan_id": "<这一轮的计划号>"}},
                )
        #: 别条命题的稿（`manuscript_foreign`）在这里被整份跳过：不解析依赖段、不核档位、
        #: 不落边 —— 它的"依赖面"是别人的，落过来就是把别人的依据记到这条命题头上。
        #: 跳过之后也不进下面那条"交不出手稿"的拒绝：那一档拒的是"这一笔没有任何稿"，
        #: 而这里是"有一份稿、但不是这条命题的" —— 后者已经在上面的
        #: `manuscript_owner_mismatch` 那一支里分过档（带了正文 ⇒ 正文照写、这份稿不用；
        #: 没带正文 ⇒ 整笔拒并点名稿的主家）。
        if manuscript_text.strip() and not manuscript_foreign:
            manuscript = _DS.parse_dependency_section(manuscript_text)
            # 引用只在"证明正文"那一节里数（手稿开头的元信息不是引用）。
            # 普通数值手稿没有 `## 证明` 节：整份稿里的别的内容（审查意见 / 后续计划）
            # 一律不参与这一笔（业主：不录入其它内容）。
            #
            # 2026-11-09（D4）：`manuscript_proof` 的 absent 在这里不是错误 —— 这一格
            # 要的是 `## 依赖`（它自己那份解析在上一行，一个字没动）；证明正文缺节只让
            # "正文引了哪些号"这一读数为 0，不拿依赖段 / 整份全文去凑引用。
            # 于是 absent 时依赖面照常按表落边；"这份稿没有 `## 证明`"由
            # `_deps_reading().manuscript_proof` 如实报出（不许被读成"自足的证明"）。
            manuscript_refs = ([] if _green.get("ok")
                               else _DS.stmt_refs(str(manuscript_proof.get("body") or "")))
            if manuscript.get("refused"):
                # 逐条四元组（哪一行 / 想写什么 / 该是什么 / 怎么改）：读的人要照着改，
                # 而解析器那句话说的是"这一行为什么读不懂"，不是"该改成什么"。
                return _refuse(
                    str(_DS.REFUSED_SECTION), str(manuscript.get("reason") or ""),
                    problems=list(manuscript.get("problems") or []),
                    findings=_DS.section_problem_findings(manuscript_text, manuscript),
                    heading_line=int(manuscript.get("heading_line") or 0))
            if not manuscript.get("present") and manuscript_refs:
                shown = "、".join(f"stmt:{x}" for x in manuscript_refs[:3])
                more = f" 等 {len(manuscript_refs)} 条" if len(manuscript_refs) > 3 else ""
                findings = _DS.missing_section_findings(manuscript_text, manuscript_refs)
                return _refuse(
                    str(_DS.REFUSED_SECTION_MISSING),
                    "这份证明手稿里没有 `## 依赖` 那一节，而正文引用了 "
                    f"{len(manuscript_refs)} 条（{shown}{more}）⇒ "
                    + "；".join(str(f["detail"]) for f in findings),
                    refs_in_proof=list(manuscript_refs),
                    findings=findings,
                    manuscript_source=manuscript_source)
            if manuscript.get("present"):
                # 2026-11-05（缺陷甲）：表在、但 0 行数据，而正文点了在册号 ⇒ 表与正文
                # 对不上。改前这一笔照收（`present` 就算合格），依赖边 0 行而读数正常 ——
                # "正文里引了、表里没写"整份静默通过。判据本体只有一处
                # （`depsection.dependency_consistency_problem`），与 F 落稿前那道同源。
                #
                # 2026-11-06（业主口径的纠正）：正文里出现的 `stmt:` 号必须是"可引"的
                # —— 在册 ∧ 等级 ≥ `pre_theorem`（F 只可引用准定理级及以上）。不在册 /
                # 等级不够的号不是"待接的悬空边"，而是这一笔写错了（F 读不到它，不可能
                # 在引用它）⇒ 受控拒，拒信点名那个号。"在册"要真读台账，所以读
                # `statements` 提到这一判据之前；读不到 ⇒ 不许猜，整笔不写。
                stmt_rows, problem, error = SL.rows_of(self.store)
                if problem:
                    return _refuse(
                        str(_DS.REFUSED_LEVEL_UNREADABLE),
                        f"手稿的依赖段要核每条来源的档位、并判正文的引用在不在可引池里，"
                        f"而 `statements` 读不出来"
                        f"（{error.get('type') or '?'}: "
                        f"{error.get('message') or problem}）⇒ 整笔不写：读不到档位就不许放行")
                pool = _DS.citable_pool(stmt_rows)
                _code, _why = _DS.dependency_consistency_problem(
                    manuscript_text, known_ids=pool, statement_rows=stmt_rows)
                if _code:
                    return _refuse(
                        str(_code), str(_why),
                        refs_in_proof=list(manuscript_refs),
                        # 每一条异常各自一条六格（号 / 哪一行哪一步 / 类别 / 期望 / 实得 / 怎么改）；
                        # `error` 那句已经是同几条的人话，这里给机器读的形态。
                        findings=_DS.dependency_consistency_findings(
                            manuscript_text, known_ids=pool, statement_rows=stmt_rows),
                        manuscript_source=manuscript_source,
                        manuscript_path=manuscript_path)
                gate = _DS.gate_rows(manuscript.get("rows") or (), stmt_rows)
                if not gate.get("ok"):
                    return _refuse(
                        str(gate.get("refused") or _DS.REFUSED_LEVEL_TOO_LOW),
                        str(gate.get("reason") or ""),
                        findings=list(gate.get("findings") or []),
                        source_levels=dict(gate.get("levels") or {}),
                        required=sorted(_DS.CITATION_LEVELS))
                kinds = {str(r.get("stmt_id") or ""): _DS.dep_kind_of(str(r.get("kind") or ""))
                         for r in stmt_rows}
                deps_groups = _DS.deps_groups(manuscript.get("rows") or (), kinds)
        elif not manuscript_text.strip():
            # ---- 参数空、盘上也没有稿：不许静默跳过（2026-10-26，业主的裁定） ------
            #
            # 正文引用了可引命题（在册 ∧ 等级 ≥ pre_theorem）⇒ 这份证明的依赖面必须
            # 写在手稿里，而这一笔交不出手稿（参数空、约定路径也找不到）⇒ 整笔受控
            # 拒绝 `dependency_section_missing`。
            # 一条可引引用都没有 ⇒ `not_applicable`（自足的证明合法，不拒收），
            # 依赖面仍由秘书那条正文扫描的既有口径给读数。
            # 判"可引"要真读一次 `statements`：读不到就不许把"读不到"折成"没有引用"，
            # 也不能凭引用形状就拒（一条指向不存在号的引用不是这一档的事）。
            probe_refs = _DS.stmt_refs(proof_text)
            if probe_refs:
                try:
                    #: 这一格问的是"正文引了在册命题没有"（用于判"这一笔该不该带稿"），
                    #: 不是可引池：「在册但等级不够」由稿那一侧 / 秘书那一侧的受控拒点名，
                    #: 不在这里折成"缺稿"（缺的确实不是稿）。
                    #: 索引的构造只有一处（查口 `index_by_id`）；取数走唯一取数口。
                    #: 读不到时与改前同一档：按「正文里点到的号都算在册」走（理由另写）。
                    ids_rows, ids_problem, _ids_error = SL.rows_of(self.store)
                    known_ids = (set(probe_refs) if ids_problem
                                 else set(SL.index_by_id(ids_rows)))
                except Exception:  # noqa: BLE001 - 读不到就只按形状判，理由里写清
                    known_ids = set(probe_refs)
                on_ledger = [rid for rid in probe_refs if rid in known_ids]
                if on_ledger:
                    shown = "、".join(f"stmt:{x}" for x in on_ledger[:3])
                    more = f" 等 {len(on_ledger)} 条" if len(on_ledger) > 3 else ""
                    #: 每一条引用各自一条六格（号 / 在哪一步 / 类别 / 期望 / 实得 / 怎么改）。
                    findings = _DS.missing_section_findings(
                        proof_text, on_ledger,
                        got_extra="这一笔没有交出手稿（`proof_manuscript` 是空的）")
                    return _refuse(
                        str(_DS.REFUSED_SECTION_MISSING),
                        (f"这一笔的证明正文引用了 {len(on_ledger)} 条在册命题"
                         f"（{shown}{more}），而它没有交出手稿 ⇒ "
                         + "；".join(str(f["detail"]) for f in findings)
                         + "。三处都找过了：① 参数里没有；"
                         "② D 的研究报告里没有携带它（"
                         + str(manuscript_carried.get("why")
                               or "（D 的报告里没有那一节）") + "）；"
                         "③ 按约定路径去盘上找也没有（"
                         + str(manuscript_probe.get("why") or "（没有可定位的命题号）")
                         + "）—— 依赖面必须写进 F 的证明手稿（四列表，列固定），B 读稿登记；"
                         "让 D 把 F 那份稿一并带过来（或把正文传进 `proof_manuscript`）再交"),
                        refs_in_proof=list(on_ledger),
                        findings=findings,
                        manuscript_source=_DS.SOURCE_NONE,
                        manuscript_probe=dict(manuscript_probe),
                        manuscript_carried=dict(manuscript_carried))

        def _deps_reading(written_row: Mapping, *, extra_deps: int = 0) -> dict:
            """这一笔的依赖面三态读数（没有手稿 ⇒ 秘书那一份原样透出）。

            读数里多带几格（2026-10-26，死结 2 的读数面）：`manuscript_source` 说稿是从
            参数来的、D 带过来的、从盘上读的、还是没有；`manuscript_probe` 是兜底读盘查过的
            路径、`manuscript_carried` 是 D 那一侧查过的报告（三处逐条留痕，于是"没收到稿"
            与"收到了但那份稿没有依赖段"在读数上分不开这件事被修掉了）。

            ## `extra_deps`：把"正文写完之后才落的边"也算进来（2026-11-05 走查 D6）
            秘书那一笔返回的 `deps_missing` 是在它写完自己的边之后算的；而 B 的
            手稿依赖面（`_manuscript_deps_after_write`）是在那之后才落的（D7 的 A）。
            改前回执直接用秘书那一份 ⇒ 同一份返回里"刚写了 1 条"（`manuscript_deps`）
            与"一条依赖行都没有"（`deps_missing=missing`）互相打架。这一格把后落的那几条
            加进 `deps_written` 重算，读数才是"这一笔写完之后"的状态。
            """
            base = (dict(written_row.get("deps_missing") or {}) if not manuscript
                    else _DS.deps_missing_reading(
                        proof_text=proof_text,
                        deps_written=(int(written_row.get("deps_written") or 0)
                                      + int(extra_deps or 0)),
                        derived_from=manuscript_refs,
                        stmt_id=str(written_row.get("stmt_id") or ""),
                        # 2026-11-04（甲）：走手稿这一支时读数同样要带"这是第几份
                        # 证明"。不传就是 0，而回执里的 `proof_no=0` 会让模型以为
                        # 这一笔没记上号 —— 与"首登的回执说 proof_no=1"同一条判据。
                        proof_no=int(written_row.get("proof_no") or 0) or 1,
                        refs=len(manuscript_refs), section=manuscript))
            if int(extra_deps or 0) > 0 and not manuscript:
                # 没有手稿时读的是秘书那一份，同样要把后落的边补进去（否则
                # "刚写了一条"与 `state=missing` 仍然打架）。
                base["deps_written"] = (int(base.get("deps_written") or 0)
                                        + int(extra_deps or 0))
                if str(base.get("state") or "") in ("", "missing"):
                    base["state"] = "present"
                    base["why"] = (f"这一笔落了 {int(base['deps_written'])} 条依赖，"
                                   "依赖面建起来了（含正文写完之后补落的那几条）")
                    base["next_step"] = ""
            base["manuscript_source"] = manuscript_source
            #: 这份稿的 `## 证明` 三态（2026-11-09，D4）：`present` / `absent`；没有稿
            #: 时是空字典（不是 `absent` —— 没交稿与"稿里缺这一节"是两件事）。
            #: 缺节时 `proof_text` 留空、依赖面照旧，但"这一笔没有证明正文"在这里
            #: 有读数，不可能被读成"证明正文为空所以没问题"。
            if manuscript_proof:
                base["manuscript_proof"] = dict(manuscript_proof)
                base["proof_body_state"] = str(manuscript_proof.get("state") or "")
            #: 这一份稿是不是 F 的秘书洗过的那一版（跟着文件走的读数，见上面）。
            base["manuscript_washed"] = manuscript_washed
            #: 这份稿声明自己属于哪一条命题（稿头那一行 `- 命题号：stmt:NNNNNN`），
            #: 以及它是不是这一笔要写的那一条。两格都在，于是"稿是别人的"这件事在
            #: 读数里不可能被漏看（改前它根本不进读数，`manuscript_source` 只说来源）。
            base["manuscript_owner"] = declared_owner
            base["manuscript_owner_ok"] = not manuscript_foreign
            if manuscript_probe:
                base["manuscript_probe"] = dict(manuscript_probe)
            if manuscript_carried:
                # D 那一侧查过什么也留下来（携带单里有几条 / 为什么没对上），
                # 否则"主路没走到"与"主路走了但没找到"在读数上分不开。
                base["manuscript_carried"] = dict(manuscript_carried)
            # ---- 2026-11-05（缺陷 1c）：回执里那一行"依赖边 N 条（其中命题→命题 M 条）" --
            #
            # 为什么必须有两个数：87 真机的 3 条边全是文献来的（`source_stmt_id` 非空 0 行），
            # 只报 N=3 时"依赖面建起来了"与"一条命题→命题都没有"在回执上长得一模一样
            # （`temp/dep_probe/REPORT-dependency-surface.md` 第三节 B 表）。
            # N 是"这一笔写完之后"的边数；M 只有秘书知道（它落边时逐条数过）⇒ 从它那份
            # 返回值里读；缺格记 0（这一笔没有边，就没有"其中"可言）。
            total_edges = int(base.get("deps_written") or 0)
            from_stmt = int(written_row.get("deps_stmt_edges") or 0)
            base["deps_receipt"] = (f"依赖边 {total_edges} 条"
                                    f"（其中命题→命题 {from_stmt} 条）")
            #: 同一组数的机器读数（`deps_receipt` 是给人读的那一行，这一格给调用方读）。
            base["deps_stmt_edges"] = from_stmt
            if total_edges > 0:
                # `present` 那档的 why 也带上这两个数（读的人不必再去翻别的键）。
                base["why"] = (f"这一行落了 {total_edges} 条依赖"
                               f"（其中命题→命题 {from_stmt} 条），依赖面建起来了")
            return base

        def _deps_receipt(out_row: dict) -> dict:
            """把回执里那一行「依赖边 N 条（其中命题→命题 M 条）」补进 `out["note"]`。

            2026-11-05（缺陷 1c）：`_deps_reading` 已经把那一句放在 `deps_missing`
            的 `deps_receipt` 里；这一步只把它复述到人读的那一行 `note` 上（同一句，
            不另写一份口径）。取不到就一个字都不加 —— 不编一句"依赖边 0 条"给那些
            根本没有依赖面的出口（概念行 / 受控拒绝）。
            """
            line = str((out_row.get("deps_missing") or {}).get("deps_receipt") or "")
            if line:
                note_now = str(out_row.get("note") or "")
                out_row["note"] = f"{note_now}；{line}" if note_now else line
                out_row["deps_stmt_edges"] = int(
                    (out_row.get("deps_missing") or {}).get("deps_stmt_edges") or 0)
            return out_row

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
        #
        # ---- 为什么它不能接"改在册正文"这一笔（D7，业主 2026-10-27） ----------------
        #
        # 真机读数（`projects/mp3-r2`，13:17）：B 拿到 stmt:000008 的完整证明，要把截断的
        # 登记换掉。四个入口全部撞在这条支路上 —— 它返回 `ok:true / new_row:false /
        # note:「命题行不动」`，交来的 `proof_text` 与 `proofs` 一个字都没写，返回值里
        # 也没有任何一格说"正文没写"。于是 `proof_no` 恒 0、`proofs` 恒空。
        #
        # 所以这条支路只在"这一笔没有正文/清单要写"时接管（`carries_write`）：它本来就是
        # "D 递稿、B 读稿登记依赖面"的通道，不是"改正文"的通道。带了正文的那一笔交给下面的
        # `duplicate` 那一支（它已经会覆盖 canonical、旧正文进 `proof_history`、读侧转 stale），
        # 并且把这份稿的依赖面在那一笔之后补落（`_manuscript_deps_after_write`）。
        #: 这一笔是不是只想"读稿登记依赖面"（正文/清单都没变，证据档也没要求变强）。
        _wants_stronger_evidence = (
            str(evidence_kind or "") != str((redelivery or {}).get("evidence_kind") or ""))
        if (manuscript_text.strip() and not manuscript_foreign and not carries_write
                and not _wants_stronger_evidence
                # 普通数值通道要写的是五元位第 1 位（numeric=verified）+ 档位，
                # 这一支"命题行不动"的早退接不住它 ⇒ 交给下面的正常登记路。
                and not _green.get("ok")):
            if redelivery is not None:
                received = self._receive_carried_manuscript(
                    redelivery, deps_groups=deps_groups, manuscript=manuscript,
                    manuscript_refs=manuscript_refs, manuscript_source=manuscript_source,
                    manuscript_washed=manuscript_washed, manuscript_wash=manuscript_wash,
                    proofs=proofs_listed, proof_text=proof_text, deps_reading=_deps_reading,
                    proof_text_source=proof_text_source,
                    proof_vs_source=proof_vs_source)
                # ---- 2026-11-04：收方读稿登记这一支也要转正 ----------------------
                #
                # 这一支是"命题已经在册、这一趟只是把稿交过来"（F 先拿号、后交签过
                # 的稿就是它）。真机上"V 签过 ⇒ 转正"最常落在这一刻 —— 号已经在，
                # 稿也已经有签，缺的只是把 `notes/…` 复制成 `reports/f-proof-<号>.md`。
                promotion = self._promote_formal_manuscript(
                    stmt_id=str(redelivery.get("stmt_id") or ""),
                    rel=(manuscript_path or ""), text=manuscript_text,
                    source=str(manuscript_source or ""))
                if promotion:
                    received = {**received, "promoted_manuscript": promotion}
                return received

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
                           "（它是证据强度，不是来源；来源走 source_lit_id）")
        if _green.get("ok"):
            # 2026-11-08（业主：「专门给普通数值实验开绿色通道」）：这一档的档位由手稿族
            # 决定，不由调用方声明 —— 普通数值实验 = "有数值实验支持，不构成证明"。
            # 受控词表里本来就有这一档（`cross_check` 的定义逐字是这句），不新造值。
            evidence_kind = _NP.SUPPORTED_ONLY_KIND
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
        # 取数走查口的唯一取数口；读不到命题台账 ⇒ 那一格"没查成" ⇒ 拒（照旧：空清单）。
        stmt_rows, stmt_problem, _stmt_error = SL.rows_of(self.store)
        if stmt_problem:
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
                                             index_rows=self._report_index_rows(),
                                             # 2026-11-08：程序路径不住证明栏了，闸要按
                                             # `reports/e-proof-<号>.md` 那个名字钉到实验行
                                             # 才能读到 `code_path`。
                                             manuscript=manuscript_path)
        # ---- 2026-11-04（业主裁定 ⑥-1-b）：要写正文/依赖面的这一笔必须带稿 ----------
        #
        # 裁定：「闸要求本笔必须带 `proof_manuscript`，不靠台账签行反查」。
        # 反查会造出第二载体（同一份稿经两个入口进同一行依赖面），而"这一笔带没带稿"
        # 是调用方当场能验证的事实。位置在第三方签字闸之前：不带稿这一档连"要 proof
        # 的那份材料"都不完整，先说这一句；带了稿、只是没有第三方签 ⇒ 下一闸照旧咬住。
        # 文献侧的占位签（external_lit + source_lit_id）与概念行不在这一档。
        if (carries_write and not str(manuscript_text or "").strip()
                and kind_now != "concept"
                and not (str(origin) == "external_lit"
                         and str(source_lit_id or "").strip())):
            return _refuse(
                "proof_manuscript_required",
                ("这一笔要写证明正文 / 依赖面，却没有带 `proof_manuscript` ⇒ 整笔不写。"
                 "正文必须由一份稿承载：先落一份 `reports/f-proof-<命题号>.md`"
                 "（B 的改写稿是 `reports/b-proof-<命题号>.md`），三节 "
                 "`## 命题` / `## 证明` / `## 依赖` 写全，再把这一份稿原文传进 "
                 "`proof_manuscript`。签行里记过 `manuscript` 也不能替代这一格："
                 "这一笔带了哪份稿，必须是本笔当场说得出的。"))
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
        _all_missing = (" 这一笔还缺：" + "、".join(_missing)
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
                           "三态纪律：没通过要说为什么没通过，还没查也要说出来（不许留白）" + _all_missing)
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
        needs_proof = (str(origin) == "own_result" and not str(proof_text or "").strip()
                       # 普通数值通道有 E 的实验行撑着：它不欠一份证明正文（业主 2026-11-08）。
                       and not _green.get("ok"))
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
            if _green.get("ok"):
                # 普通数值通道的出处是那条实验行（`exp:<号>`），不是 doc_id / line_range：
                # 业主的模型里 D 交的是"E 的实验成果"，没有我方稿件可指 —— 这一格按
                # `origin_basis` 记成实验行，不拿一条编出来的页码顶替。
                pass
            elif not (str(doc_id or "").strip()
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
            statement_full=full, proof_text=str(proof_text or ""),
            # 2026-11-02：手稿签块也在这道闸的可见面上（业主：B 收录时从稿上读到签）。
            manuscript_text=str(manuscript_text or ""),
            manuscript_path=str(manuscript_path or ""))
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
                # ---- 2026-11-02（业主的责任路由）----
                #
                # 原话：「如果F侧产出证明而没有V签，这是F侧工作异常，B不该处理（润色）无签
                # 证明」「命题在册且缺失V签，这是B侧问题，M应让B处理」。
                # 两条分开落：
                #   · 册上还没有这一条、而这一笔是 F 的手稿（`manuscript_source` 不是 none）
                #     ⇒ F 侧异常：退回，明确"请 F 先拿 V 签"（谁产出谁送审），不润色；
                #   · 没有手稿来源（B 自己在登记一份正文）或册上已有这一条 ⇒ 走既有的
                #     两条拒信（B-2 / `self_authored_needs_v`），B 自己处理，不推给 F。
                source = str(manuscript_source or "").strip()
                if source in (_DS.SOURCE_CARRIED, _DS.SOURCE_DISK):
                    suggestion = ("请 F 先拿 V 签：F 用 `summon` V 的 `verify.verify_proof`"
                                  "（带 `proof_manuscript`）；签到位后由收方秘书 "
                                  "`vsigns.land(by=\"secretary:F\")` 把签落回稿，拿到签再把"
                                  "这一份交来入库（B 不改写无签的证明）")
                    return _refuse(
                        self.F_PROOF_UNSIGNED,
                        ("这一份证明是 F 产出的（手稿来源 " + source + "），而它没有 V 签 ⇒ "
                         "这是 F 侧的工作异常：B 不处理、不润色无签的证明，整笔退回。"
                         "建议：" + suggestion),
                        suggestion=suggestion,
                        manuscript_source=source,
                        stmt_id=str(stmt_id_now or ""))
                return _must_start_as_conjecture_refusal(kind_now=kind_now,
                                                         origin=str(origin))
            return _refuse(
                str(self_authored["refused"]),
                str(self_authored.get("reason") or "")
                + ("；这一笔的稿没有落盘（`reports/b-proof-"
                   f"{stmt_id_now or '<命题号>'}.md` 上没有新增文件）—— 被拒的登记"
                   "盘上零新增。改法：先走 B 的显式落稿（`AgentB.land_manuscript`；"
                   "`own.land_manuscript` 工具面待 T1 接线，现在还没注册），"
                   "派 V 审这一份（`verify.verify_proof` 带 "
                   "`proof_manuscript`），签块由收方秘书 `secretary:B` 落回稿，"
                   "再带这份稿重交 `own.register_statement`。"),
                manuscript_landed=False,
                b_manuscript={"preview": True, "written": False,
                              "path": str(b_manuscript.get("path") or ""),
                              "sha256": str(b_manuscript.get("sha256") or "")})

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

        # ---- 2026-11-08：普通数值通道的形态闸（收录那一刻判一次） --------------
        #
        # 业主：「B侧做好适配（应该在手稿里找命题和数值实验程序，不录入其它内容）」。
        # 手稿里取的"命题"有没有写清「从什么条件导出什么结论」，由 B 的秘书判一次 ——
        # 与 F / E 同一道判定口（`Secretary.judge_proposition_form`），不是每条实验判一次。
        # 判不过 / 没判成 ⇒ 受控拒，一个 statements 行都不落。
        if _green.get("ok"):
            _form = self._numeric_form_gate(full=full, kind=kind_now, label=label)
            _green["proposition_form"] = dict(_form)
            if not _form.get("submittable"):
                _why = str(_form.get("reason") or "").strip()
                _problems = [str(x) for x in (_form.get("problems") or []) if str(x).strip()]
                return _refuse(
                    "proposition_form_refused",
                    ("这条普通数值手稿里的命题形态闸没过 ⇒ 受控拒，不落 statements 行："
                     f"{_form.get('refused') or 'proposition_form_refused'}")
                    + (f"；{_why}" if _why else "")
                    + ("；逐条：" + "；".join(_problems) if _problems else "")
                    + "。把命题改成「设…则…」那样写清条件与结论，让 E 重落一份手稿再交；"
                    "形态判定读数已落 out/secretary/proposition_form.jsonl（role=B）",
                    problems=_problems,
                    numeric_channel={"path": _green.get("path") or "",
                                     "proposition_form": dict(_form)})
            # ---- 2026-11-08（业主）：普通数值收录先查一圈"是不是在册的同一条" ------
            #
            # 查到 ⇒ 更新那一行的数值证据位（不新注册，块丙）；没查到 ⇒ 照常登记新的。
            # 有候选而没查成 ⇒ 受控拒（fail-closed：没查成不等于「不是同一条」）。
            _same_search = self._resolve_same_statement(
                full=full, label=label, kind=kind_now)
            _green["same_statement"] = _same_search_reading(_same_search)
            if _same_search.get("refused"):
                return _refuse(
                    _R.SAME_STATEMENT_UNJUDGED,
                    "这条普通数值命题要查「是不是在册的同一条」，而这一问没查成 => "
                    "受控拒、不新注册（没查成不等于「不是同一条」）："
                    + str(_same_search.get("why") or "")
                    + "。改法：确认秘书这一趟有判断面（模型缝 / 开关开着），"
                    "并确认 statements 台账读得出来",
                    same_statement=_same_search_reading(_same_search),
                    problems=list(_same_search.get("problems") or []),
                    numeric_channel={"path": _green.get("path") or "",
                                     "same_statement": _same_search_reading(_same_search)})
            if str(_same_search.get("found") or ""):
                _row_found = dict(_same_search.get("_row") or {})
                if not _row_found:
                    return _refuse(
                        "same_statement_missing",
                        "秘书查到了在册的那一条，而它的行读不回来 ⇒ 整笔不写"
                        "（不许退化成新注册）",
                        same_statement=_same_search_reading(_same_search),
                        numeric_channel={"path": _green.get("path") or ""})
                return self._update_numeric_evidence(
                    row=_row_found, green=_green, same=_same_search)
            _same_adjudication = self._same_statement_adjudication(_same_search)

        # ---- 业主 2026-10-09：「B 不直接用增工具，秘书实际操作增、改、查工具，
        # B 纯粹负责消化理解」⇒ 上面那些是内容的判据（B 的判断），写盘这一段交给秘书。
        bits, bits_bad = self._statement_bits(
            origin=str(origin), lit_id=lit_id, proof_text=str(proof_text or ""),
            quote_verified=quote_verified,
            other_proofs=[str(e.get("text") or "") for e in proofs_listed],
            # 透传的是上面唯一一处派生出来的 `kind_now`（不是再算一次）：
            # 位里的等级、校验端的等级、落库那一行的 kind 必须是同一个字符串。
            kind=kind_now,
            # 普通数值通道：第 1 位的凭据 = 实验号 + 程序路径（足 `bit_problems` 的
            # "verified 必须能指到哪条实验/哪个脚本"），外加一份四元组的集合
            # （`entries`：一个命题可以有多份数值实验，内容寻址去重、不记次序）。
            numeric_evidence=(self._numeric_evidence_payload(_green)
                              if _green.get("ok") else None))
        if bits_bad is not None:
            return bits_bad
        # ---- 机械录入的默认态：这一笔交来的每一份证明都标 `optimized=false`（业主 2026-11-02）
        #
        # 两阶段录入的第一阶段是"机械性地录入完"（`draft/179` 一、二之一）：那一版还没洗过
        # ⇒ 这一格显式落 `false`，第二阶段只读它（「若为否……总之都要洗一遍」）。
        # 只补"还没记过的号"，已有的值一律不动（D 的每一次交付都会重交同一份内容，
        # 整表写会把别的证明"洗过"的事实擦掉）。翻真只发生在换正文那一笔（`_attach_proofs`）。
        bits = _EB.with_optimized_defaults(
            bits,
            # 这一笔要落盘的那一份正文的号：交付里给了号就以它为准（`#p1` 不再写死，
            # 否则 `#p2` 的机械录入态会记到 #p1 头上 —— 逐份表按号各记各的）。
            ([proof_no_placement] if str(proof_text or "").strip() else [])
            + [int(e.get("proof_no") or 0) for e in proofs_listed])
        # ---- 2026-11-04：号已经在册 ⇒ 先把攻坚稿转正，再认签 -------------------------
        #
        # 这一刻是"F 先拿号、V 在 `notes/…` 上签、F 把签过的稿交回 B"那条链的落点。
        # 必须在 `bits_after_sign` 之前转正：签块的第 9 格 `手稿号` 按稿路径现算，
        # `notes/…` 算不出号（`vsigns.manuscript_id_of` 返回空）⇒ B 的签块闸会判
        # `manuscript_id_missing`，那一签永远认不上（真机就是这么丢的）。
        # 转正之后从正式稿重读正文：块被搬过去时第 9 格已按新名重算成这个号。
        # 首次登记（`stmt_id_now` 为空）不走这一格：号是秘书在事务里现发的，转正只能在
        # 拿到号之后（见下面 `promotion` 那一笔）。
        pre_gate_promotion: dict = {}
        if (stmt_id_now and manuscript_text.strip()
                and _should_promote_to_formal(manuscript_path)):
            promotion = self._promote_formal_manuscript(
                stmt_id=stmt_id_now, rel=manuscript_path, text=manuscript_text,
                source=str(manuscript_source or ""))
            if promotion.get("promoted"):
                pre_gate_promotion = dict(promotion)
                _promoted_rel = str(promotion.get("path") or "")
                try:
                    manuscript_text = (Path(getattr(self.store, "root", "") or ".")
                                       / _promoted_rel).read_text(encoding="utf-8")
                except OSError as exc:  # noqa: BLE001 —— 转正了却读不回来：不许当没发生
                    return _refuse(
                        "promoted_manuscript_unreadable",
                        (f"攻坚稿已转成 `{_promoted_rel}`，而那一份读不出来"
                         f"（{type(exc).__name__}: {exc}）⇒ 整笔不写（读不回来就认不了签）"),
                        promoted_manuscript=dict(promotion))
                manuscript_path = _promoted_rel
                # 转正之后它是盘上那一份正式稿：签块认签与洗稿闸都按它读。
                manuscript_source = _DS.SOURCE_DISK
                manuscript_washed = bool(
                    _DS.manuscript_wash_reading(manuscript_text).get("washed"))
                manuscript_wash = _DS.manuscript_wash_reading(manuscript_text)
                # 转正搬的是同一份正文 ⇒ 重新读一次三态，让读数说的是"这一份稿"。
                manuscript_proof = _DS.proof_body_reading(manuscript_text)
        # ---- 业主 2026-11-01：B 收录时"认签"（第 3 位的第四源） -------------------
        #
        # 原话：「B 侧自己写的证明想要 V 签时一样是拿到 V 签，B 再录入。」
        # 于是 `out/vsigns/<artifact_sha>.json` 是 B 这一侧认得的那一份签：正文的 sha 对得上、
        # 连续次数够、而且这一份签属于「这一条命题」（同一段正文被别的命题复用不算签过），
        # 才把第 3 位写成已签。三态都在 `v_sign` 里（`checked` / `found` / `applied` / `why`），
        # 认不出来时 `bits` 一个字都不动 —— 没签过不是"把审过的擦掉"。
        try:
            from agentflow import vsigns as _VS

            bits, v_sign = _VS.bits_after_sign(
                bits, root=getattr(self.store, "root", ""),
                proof_text=str(proof_text or ""), statement_id=stmt_id_now,
                proof_no=proof_no_placement, kind=str(kind_now or ""),
                # 2026-11-02（业主：「V 签先放在 F 的手稿里，让 B 录入」）：
                # 收录时先读手稿里那一行签块（`vsigns.manuscript_sign_standing`）。
                manuscript_text=str(manuscript_text or ""),
                # 2026-11-02（业主：「B侧需寻址获得F侧证明及V签」）：签块的第 9 格
                # 手稿号要与它所处那份稿对得上；在册命题的集合从 store 现读（只读判据）。
                manuscript_path=str(manuscript_path or ""),
                store=self.store)
        except Exception as exc:  # noqa: BLE001 —— 认签那一格读不成不许带走整笔登记
            v_sign = {"checked": False, "found": False, "applied": False,
                      "artifact_sha": "",
                      "why": (f"认签那一格没查成（{type(exc).__name__}: {exc}）"
                              "⇒ 不是「没有签」")}
        # ---- 没有签的证明不许进台账（业主 2026-11-02；覆盖所有来源） ------------------
        #
        # 业主四条要求的第 5 条：「机械录入那一版也必须有签（F 的签 或 文献编号），
        # 不许再出现 proofs=0 绕行」。而今天的口子不止一条：
        #   · kind="conjecture" 让 _self_authored_gate 短路 ⇒ 无签照收（85 的 14/16 条）；
        #   · 闸只认 carried_by_D / disk 两种手稿来源，F 的进程内直交（param）不触发；
        #   · F 侧把 evidence_kind 现算成 heuristic 照交 ⇒ 无签进台账。
        # 这条闸按判据的真身写：看的是"这一笔要写进台账的证明正文有没有一份覆盖它的签"，
        # 不看 kind、不看来源、不看 evidence_kind。两条合法的免签路（业主原话）：
        # ① 文献侧的占位签：origin="external_lit" + source_lit_id（V 签位填文献编号）；
        # ② 已有一份真签覆盖这一份正文（在册台账，或手稿签块，sha 相符）。
        #
        # 判据本体在 `proofintake_unsigned_gate`（2026-11-02）。它默认是「闸」，
        # 由 `AGENTFLOW_UNSIGNED_PROOF_INTAKE` 三态控制（默认 strict = 拒），
        # 让"把闸摘掉 ⇒ 判据必须红"的反真空能被机器跑出来 —— 见那个函数的 docstring。
        if unsigned_proof_intake_is_strict():
            _pg = self._unsigned_proof_gate(
                origin=str(origin), lit_id=lit_id, proof_text=str(proof_text or ""),
                proofs_listed=proofs_listed, row=redelivery, v_sign=v_sign,
                proof_no=proof_no_placement, store=self.store)
            if _pg.get("refused"):
                # ---- 2026-11-05（D3）：拒信要带"认签那一格"的读数 ------------------
                #
                # 第二笔同正文 sha 的登记被 `already_claimed` 挡住时，拒码是
                # `proof_without_v_sign`；"为什么认不到签"（这一签已认给谁）原本只在
                # `bits_after_sign` 的返回值里，而那条路已经 return 了 —— 调用方只看到
                # 一句"没有一份覆盖它的 V 签"，会去重签（重签也只会被同一把锁挡住）。
                # 这里把认签读数（去掉逐字签块，留三态 + claim）随拒信带回去。
                _v_sign_reading = {k: v for k, v in dict(v_sign or {}).items()
                                   if k != "block"}
                return _refuse(
                    str(_pg["refused"]),
                    str(_pg.get("reason") or "")
                    + ("；这一笔的稿没有落盘（`reports/b-proof-"
                       f"{stmt_id_now or '<命题号>'}.md` 上没有新增文件）—— 被拒的登记"
                       "盘上零新增。改法：先走 B 的显式落稿（`AgentB.land_manuscript`；"
                       "`own.land_manuscript` 工具面待 T1 接线）→ "
                       "派 V 审这份稿 → 签到位后带这份稿重交登记。"),
                    proof_gate=dict(_pg.get("reading") or {}),
                    v_sign=_v_sign_reading,
                    manuscript_landed=False,
                    b_manuscript={"preview": True, "written": False,
                                  "path": str(b_manuscript.get("path") or ""),
                                  "sha256": str(b_manuscript.get("sha256") or "")})
        # ---- D1（2026-11-10）：闸全过了才落稿 -------------------------------------
        #
        # 顺序理由就是上面预览块那一段：文件写不是事务资源，而这条链在落稿点之前
        # 有二十来处受控拒绝。落在这里 ⇒ 依赖面闸 / 自产签闸 / 无签闸任一拒，盘上
        # 一个字节都不写；而过了全部内容/签闸的那一笔，正好在台账那一笔之前落稿。
        #
        # 边界：这里之后只剩"环境 / 写库"失败（没有秘书 / 写入期闸 / 秘书写失败）。
        # 那些不是"被拒的登记"——内容是闸接下来了的；它们的拒信带
        # `manuscript_landed=True`，不谎报"稿没落盘"。
        _manuscript_landed = False
        if _rewrite_body:
            b_manuscript = self._land_b_manuscript(
                statement_id=stmt_id_now, statement_full=full,
                proof_text=str(proof_text or ""), label=label,
                proof_no=proof_no_placement, source_manuscript=_b_source_text)
            _manuscript_landed = bool(
                b_manuscript.get("written") or b_manuscript.get("preserved"))
            if not _manuscript_landed and not _b_source_text.strip():
                # 只有"这一笔的手稿本来就靠落稿产生"（内联正文 / 无来源稿）时才把
                # 落稿失败读成整笔拒：调用方已经递了一份（盘上 / 参数）稿的那一档，
                # 登记能不能落不取决于 b-稿这一份改写载体（改前也是这个口径）。
                _land_problem = dict(b_manuscript.get("problem") or {})
                return _refuse(
                    str(_land_problem.get("kind") or "b_manuscript_not_landed"),
                    "这一笔过了全部内容/签闸，而 B 的改写稿没有落成"
                    f"（{str(b_manuscript.get('why') or '未说明原因')}）⇒ "
                    "台账整笔不写、稿也没有落盘。改法：确认 "
                    f"`reports/b-proof-{stmt_id_now}.md` 可写、且没有被另一版已签"
                    "正文占住；再重交这一笔（同一份正文重放是幂等的）",
                    b_manuscript=dict(b_manuscript),
                    manuscript_landed=False)
            if not _b_source_text.strip():
                # 本次手稿来自预览 ⇒ 用落盘后的最终字节（登记元信息已补上）替换。
                manuscript_text = str(b_manuscript.get("text") or "")
                manuscript_source = _DS.SOURCE_DISK
                manuscript_path = str(b_manuscript.get("path") or "")
                manuscript_probe = {"checked": True, "source": _DS.SOURCE_DISK,
                                    "path": manuscript_path,
                                    "matched_by": "b_manuscript"}
                manuscript_proof = _DS.proof_body_reading(manuscript_text)
                manuscript_wash = _DS.manuscript_wash_reading(manuscript_text)
                manuscript_washed = bool(manuscript_wash.get("washed"))
        sec = self._statement_secretary()
        if sec is None:
            return _refuse("secretary_unavailable",
                           "这一趟没有秘书 ⇒ 命题写不了（写入侧是 B 的活，但落盘归秘书："
                           "`Secretary.record_statement`。不许退回'B 自己写'那条后备路）"
                           + (f"；{self.secretary_problem}" if self.secretary_problem else ""),
                           manuscript_landed=_manuscript_landed)
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
        # ---- 手稿正文交给秘书（2026-11-04，缺口 ②）：升档那一支要读手稿签块 --------
        #
        # 秘书的 `_upgrade_evidence_kind` 判"这一条该不该升档"时，除了读签名台账，
        # 还要读手稿签块（E 那一签在"手稿签块 + pending 台账"里，台账读不到）。
        # B 是唯一手里有这份稿正文的人，所以把正文与地址一并递过去；秘书那一侧只读、
        # 不落盘（`_statement_from` 的白名单会忽略这两个键，它们不进 schema）。
        payload["manuscript_text"] = str(manuscript_text or "")
        payload["manuscript_path"] = str(manuscript_path or "")
        # ---- 证明号（缺口 ①）：交付里给了号才透传 --------------------------------
        #
        # 不给（`fallback`）时不传这一格：秘书那一支的 `_merge_target` 把
        # `body["proof_no"]` 当"合并稿要覆盖哪一份"的显式号 —— 回退不是显式号，
        # 传进去会让"回退"变成"指定覆盖 #p1"。回退口径由秘书自己算（canonical 空则
        # #p1 / 否则最大号 + 1）。
        if proof_no_delivery >= 1:
            payload["proof_no"] = int(proof_no_delivery)
            payload["proof_no_source"] = str(proof_no_source)
        # ---- 落点：交付说这一份是 #pN（N>1）⇒ 它进 `proofs` 清单，不进 canonical ----
        #
        # canonical（`proof_text`）只放 #p1；把第 2 份写进那一格会让 `proof_list` 读出
        # 两条 #p1（一条正文、一条空），而 `used_by` / 对应表 / V 的签全按号走。
        # 只在"这一笔没有另交清单"时拆分：清单里的号是调用方显式给的，两套号不许叠。
        attach_canonical = str(proof_text or "")
        attach_entries = [dict(e) for e in proofs_listed]
        if (proof_no_placement > 1 and attach_canonical.strip()
                and not attach_entries):
            attach_entries = [{"proof_no": int(proof_no_placement),
                               "text": attach_canonical,
                               "created_at": S.now_iso()}]
            attach_canonical = ""
        # ---- D2①（2026-11-05 走查）：先把正文写进那一行，再请求升档 ----------------
        #
        # 路径：`secretary.py` 的升档那一支（`_record_statement_tx`，改前在
        # `:7585` 先算档）拿盘上那一行组"要写的行"，而这一笔的正文还没写进去 ⇒
        # 写入期闸（`store._refuse_fake_proof_review`）看到 `proof_text` 是空的，
        # 整笔拒 `proof_review_without_evidence`。真机走查 `walk-e2e` 的 P0 那一趟
        # 就是它：`refused=write_failed`，而档位永远升不上去。
        #
        # 正确顺序与写入期闸的判据一致：闸核的是"这一行将要是"什么。所以先让
        # `_attach_proofs`（B 的写侧唯一一处直接改那一行的地方：正文 / `proof_history` /
        # 五元位 / 认签）把正文落到那一行，再让秘书在同一内容上请求升档 —— 此刻
        # 盘上那一行已经有正文，闸按它现算就能过。
        _have_ek = str((redelivery or {}).get("evidence_kind") or "")
        _stronger = (str(evidence_kind or "") in (_VR.PROOF_REVIEW_KIND, _VR.PROOF_KIND)
                     and str(evidence_kind or "") != _have_ek
                     and _have_ek in _VR.WEAKER_THAN_PROOF_REVIEW)
        pre_write: dict = {}
        if (redelivery is not None and _stronger
                and str(attach_canonical or "").strip()):
            # 这一笔的升档凭据在不在（纯读）。判据与秘书 `_upgrade_evidence_kind` 同口径：
            # 三路任一路命中即可 ——
            #   ① 在册台账 / `verifications/pending/` 那一签（`proof_review_gap`）；
            #   ②③ 手稿签块 / `bits.reviewed`（`_manuscript_upgrade_basis` 收拢）。
            # 改前这里只算了 ②③ ⇒ ① 有签的现场（F 的三票台账、E 的待认领一签）被读成
            # 「这一笔没有凭据」：正文与档位两笔都不请求，盘上停在 `cross_check` ——
            # D-34 ③⑤、F 的复用升档、以及"签完之后同一份内容再交一次"全撞这一格。
            # 判据刻意不看成"盘上那一行现在有没有正文"—— 那正是 D2 要修的顺序。
            from ..secretary import _manuscript_upgrade_basis as _upgrade_basis
            _basis = _upgrade_basis(
                root=getattr(self.store, "root", ""),
                manuscript_text=str(manuscript_text or ""),
                manuscript_path=str(manuscript_path or ""),
                proof_text=str(proof_text or ""), bits=bits)
            _probe_row = dict(redelivery or {})
            _probe_row["proof_text"] = str(attach_canonical or "")
            _probe_row["evidence_kind"] = str(evidence_kind or "")
            try:
                _upgrade_gap = dict(_VR.proof_review_gap(
                    getattr(self.store, "root", ""), _probe_row))
            except Exception:  # noqa: BLE001 —— 读不出来就当"这一路没有凭据"（保守）
                _upgrade_gap = {}
            #: 三路任一路命中：升档这一笔有凭据可交（秘书那一侧才可能升得动）。
            _signed = bool(_basis.get("signed")) or bool(_upgrade_gap.get("ok"))
            # 还要过写入期闸那一关（它核的是"这一行将要是"什么）：升档能不能落，
            # 取决于闸认不认这一份正文的签。闸不认（例如签只在 `out/vsigns/` 的签文件里、
            # 没有台账/待认领那一行）⇒ 预写正文也没有意义 —— 那一笔本来就只能落重复读数。
            _gate_ready = False
            if _signed:
                if str(evidence_kind or "") == _VR.PROOF_KIND:
                    _gate_ready = True
                else:
                    _gate_ready = bool(_upgrade_gap.get("ok"))
        else:
            _basis = {}
            _signed = False
        #: 这一笔请求的档位落不了（闸不会认这一份正文的签）⇒ 只登记正文，不请求升档。
        #: 读数 `upgrade_refused` 把"请求了什么 / 拒码 / 为什么"一起交出去 —— 于是
        #: `ok=true` 只代表"正文登记了"，绝不被读成"档位也升了"（D2 的"两件事不许糊成
        #: 一个 true"）。升档请求本身不发给秘书，是因为那一笔注定整笔被写入期闸拒；
        #: 把它发出去再把拒收折成 ok 就是改前那个谎。
        upgrade_skipped: dict = {}
        if (_stronger and not (_signed and _gate_ready)
                and str(attach_canonical or "").strip()):
            upgrade_skipped = {
                "requested_evidence_kind": str(evidence_kind or ""),
                "refused": _VR.CODE_WRITE,
                "why": ("这一笔的正文还没有能签住它的台账 / 待认领那一签"
                        "（写入期闸会整笔拒 `proof_review_without_evidence`）"
                        "⇒ 只登记正文、不请求升档；去让 V 对现行正文再签一次，"
                        "或如实按弱档读"),
            }
            payload["evidence_kind"] = _have_ek
        if _signed and _gate_ready:
            pre_write = self._attach_proofs(stmt_id_now, attach_entries,
                                            canonical=attach_canonical,
                                            bits=bits,
                                            proof_no=int(proof_no_placement))
            # 正文写不进去 ⇒ 升档这一笔也不用问了（闸只会拒）：照实回这一笔的拒码。
            if pre_write.get("refused"):
                return _refuse(str(pre_write.get("refused") or "proof_text_not_written"),
                               str(pre_write.get("reason") or ""),
                               stmt_id=stmt_id_now, upgraded=False,
                               manuscript_landed=_manuscript_landed,
                               requested_evidence_kind=str(evidence_kind or ""),
                               canonical_written=False,
                               **trunc_reading)
        # ---- D2（2026-11-05 走查）：新建档把稿名 / 稿头的号当候选号 ------------------
        #
        # 现象：B 按计数器发号、不认稿名/稿头的号 ⇒ 稿 000001、命题 000000 错位；
        # 第 4 步靠"新命题 stmt_id_now=''"使 owner 判据短路才过；第 5 步同一条命令被
        # `manuscript_owner_mismatch` 拒；收工扫盘按稿名开 `b-register@000001@…` 的义务
        # 永远关不上（`reconcile_registrations` left=1，而 `verify_all` 0 error —— 真空的绿）。
        #
        # 口径①（业主 2026-11-05 选定）：稿名优先（扫盘按稿名算号，读侧必须与它同键），
        # 稿名认不出再退到稿头那一行；只在这一笔「确实要新建」时当候选（在册那一档的号
        # 由在册行给，候选号不许改变它）。候选号被占 ⇒ 秘书受控拒绝 `stmt_id_taken`，
        # 不另发号（发号那一步在 `Secretary.record_statement` / `_record_statement_tx`）。
        candidate_stmt_id = ""
        candidate_source = ""
        #: 候选号只从"明确递进来的稿"取：`param`（调用方点名给 `proof_manuscript`）与
        #: `carried_by_D`（D 的携带单点了名、且 sha 与盘上那份相符）。「`disk` 兜底读盘
        #: 不算」：那一支可能捡到被引命题的稿（真机 `walk-e2e` 就是按 `derived_from` 读到
        #: 别条命题的 `reports/f-proof-<别人的号>.md`），拿它的稿名当新命题的候选号 =
        #: 把别人的号借来用；稿是不是本行的由 `_manuscript_is_own` 判，那一判据管正文，
        #: 这一格管号 —— 两条都不能让"捡来的稿"说话。
        _explicit_manuscript = str(manuscript_source or "") in (
            _DS.SOURCE_PARAM, _DS.SOURCE_CARRIED)
        if (not stmt_id_now and not manuscript_foreign and _explicit_manuscript
                and str(manuscript_text or "").strip()):
            from agentflow import vsigns as _VS_CAND

            _from_path = _VS_CAND.manuscript_id_of(str(manuscript_path or ""))
            _from_head = _DS.manuscript_statement_id(str(manuscript_text))
            # 被引命题的稿不是本笔的稿（2026-11-06）：`derived_from` / 正文的
            # `stmt:` 引用把它们的号带进来是正常的；拿那个号当候选号会撞在被引
            # 命题自己头上（`stmt_id_taken`），主链整笔拒（D 携带 F 稿 → B 登记）。
            _cited_manuscript = _manuscript_belongs_to_a_cited_statement(
                declared_id=(_from_path or _from_head),
                derived_from=derived_from, proof_text=proof_text)
            if not _cited_manuscript:
                if _from_path and S.is_valid_id(_from_path):
                    candidate_stmt_id, candidate_source = str(_from_path), "manuscript_name"
                elif _from_head and S.is_valid_id(_from_head):
                    candidate_stmt_id, candidate_source = str(_from_head), "manuscript_head"
        written = sec.record_statement(payload, role="B",
                                       candidate_id=candidate_stmt_id,
                                       adjudication=_same_adjudication)
        # ---- D2②：拒绝要看，不许把它读成成功 ------------------------------------
        #
        # 改前 `if written.get("upgraded") and not written.get("created")` 不看
        # `checked` / `refused`：秘书那一笔整笔被拒（`write_failed`，档位没升）之后，
        # B 继续 `_attach_proofs` 写正文并返回 `ok=true / upgraded=true`。
        # 现在：受控拒绝一律回 `ok=false` + 拒绝码，并分开说清正文写没写
        # （`canonical_written`）—— "正文进去了"与"档位升上去了"是两件事，不许糊成
        # 一个 true。
        if not written.get("checked") and str(written.get("refused") or ""):
            # 秘书交出来的状态读数要原样带回去（D-34 ⑤）：`unknown_lit_id` 的
            # 「表现在几行 / 现有哪些号」就在 `written` 里，改前这一格只回拒码与档位
            # 两格 ⇒ 模型拿到 `kind=unknown_lit_id` 却分不清「表是空的」与「号写错了」，
            # 于是换着号继续猜（真机 T1 第 8 趟：同一条拒了 20 次）。与下面
            # `not created` 那一支的 `extra` 同一个白名单，一处口径。
            refused_extra = {k: v for k, v in written.items()
                             if k in ("literature_rows", "available_lit_ids", "unresolved",
                                      "stmt_id_candidate")}
            return _refuse(str(written.get("refused") or "write_failed"),
                           str(written.get("reason") or "秘书没写这一笔"),
                           # D2：候选号被占（`stmt_id_taken`）时，拒信要点名是哪个号被占。
                           stmt_id=str(written.get("stmt_id") or stmt_id_now or ""),
                           manuscript_landed=_manuscript_landed,
                           upgraded=False,
                           requested_evidence_kind=str(evidence_kind or ""),
                           canonical_written=bool(pre_write.get("canonical_written")),
                           **refused_extra,
                           **({"canonical_history": list(pre_write.get("canonical_history") or [])}
                              if pre_write.get("canonical_written") else {}))
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
                   #: 2026-11-04：这一笔把攻坚稿转成正式稿了吗（有才带这一格）。
                **({"promoted_manuscript": dict(pre_gate_promotion)}
                   if pre_gate_promotion else {}),
                   #: 2026-11-04（业主裁定 A 甲）：B 的改写手稿读数（有就带上）。
                **({"b_manuscript": dict(b_manuscript)} if b_manuscript else {}),
                "self_authored_review": self._self_authored_reading(self_authored),
                   "source_lit_id": lit_id or None,
                   "quote_verified": quote_verified, "origin": origin,
                   "quote_mode": str(quote_mode or ""),
                   "evidence_kind": self._evidence_kind_on_disk(stmt_now),
                   "requested_evidence_kind": evidence_kind,
                   "matched_by": str(written.get("matched_by") or ""),
                   #: 2026-11-08：两格读数（稿上已签 / 已入台账）。
                   "sign_filing": _sign_filing_reading(
                       self.store, manuscript_path=manuscript_path,
                       manuscript_text=manuscript_text, statement_id=stmt_now),
                   #: 2026-11-08（业主）：语义查一圈的读数（查到的那一条走的是既有
                   #: "在册"分支 —— proofs 追加 / proof_no 递增 / 签按 sha 认都在里面）。
                   **({"searched": _same_search_reading(_same_search),
                       "found": str(_same_search.get("found") or ""),
                       "why": str(_same_search.get("why") or "")}
                      if _same_search else {}),
                   "similarity": float(written.get("similarity") or 0.0),
                   "proof_no": proof_no,
                   #: 这一次的号是哪来的（`crafted` / `carried` / `fallback`）——
                   #: "读了"与"猜的"在读数上必须分得开（缺口 ①）。
                   "proof_no_source": str(proof_no_source),
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
                   #: 这一笔的正文是从哪来的（2026-11-02）：`param`（调用方直递）/
                   #: `manuscript`（按 D 的携带单寻址到的那份稿的 `## 证明`）/ 空串（这一笔
                   #: 没有正文要写）。与 `manuscript_source` 分开读：那一格说稿从哪来，
                   #: 这一格说落进 `proof_text` 的是不是那份稿。
                   "proof_text_source": proof_text_source,
                   "addressing": dict(addressing),
                   "manuscript_washed": manuscript_washed,
                   "manuscript_wash": dict(manuscript_wash),
                   "proof_vs_source": dict(proof_vs_source),
                   "note": str(written.get("reason") or "")}
            _deps_receipt(out)
            #: 判档位那一趟读不完这条正文时的那三格（空字典 = 读得完；见
            #: `_text_truncation_reading`）：三条"没有新建行"的出口都要带上它 ——
            #: 这一笔交上来的正文超了上限这件事，与"有没有新建行"无关。
            out.update(trunc_reading)
            # ---- 收录签的那条路也走"写全"的那一支（真机 R-mk-infinite-92 的 000000）--
            #
            # 这一支（`written["merged"]`）是"命题先在册、正文后到"的收录路：板上
            # `b-register@<号>@<被签正文 sha>` 收口就走它。秘书那一笔只把正文写进在册行
            # （`Secretary._merge_into_proposition`），它不写 `bits`；改前到这里就 return，
            # 于是"正文在行上、V 的签在台账里"而 `bits.proof=false` —— 等级永远派生不出
            # 定理（现场那一行的 `reviewed=true ∧ proof=false ∧ grade=conjecture`）。
            #
            # 现在与"新建 / 升档"那两支共用 `_attach_proofs`：按盘上那一行的正文补翻第 2 位、
            # 带过这一笔认到的第 3 位、写顶层收录回执，并按现行签重算等级
            # （`_grade_recomputed`）。合并稿那一档（`merge=True`，正文换成了还没签的那一份）
            # 不在此列：那一笔要 V 重签，位不许替它说"签过"。
            if proof_no >= 1 and not written.get("merged_same_kind"):
                collect = self._attach_proofs(
                    stmt_now, [], canonical="", bits=bits, proof_no=int(proof_no))
                if collect.get("refused"):
                    out["bits_not_written"] = {
                        "refused": str(collect.get("refused") or ""),
                        "reason": str(collect.get("reason") or "")}
                if collect.get("written") or collect.get("proof_receipt"):
                    _row_got = SL.by_id(self.store, stmt_id=stmt_now)
                    if not _row_got["checked"]:
                        _err = _row_got.get("error") or {}
                        raise RuntimeError(
                            f"`statements` 读不出来（{_err.get('type') or '?'}: "
                            f"{_err.get('message') or _row_got.get('reason') or '?'}）")
                    out["row"] = (_row_got["row"] or out.get("row") or {})
                if collect.get("grade_recomputed"):
                    out["grade_recomputed"] = dict(collect.get("grade_recomputed") or {})
                if collect.get("proof_collected"):
                    out["proof_collected"] = True
                if collect.get("proof_receipt"):
                    receipt = dict(collect.get("proof_receipt") or {})
                    out["proof_receipt"] = receipt
                    out["proof_sha256"] = str(receipt.get("proof_sha256") or "")
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
            out["v_sign"] = dict(v_sign)
            #: 2026-11-02：二次寻址的读数（清单来源 / 地址 / 命中 / 模式 auto|model|unknown）。
            out["addressing"] = dict(addressing)
            return out
        if written.get("upgraded") and not written.get("created"):
            # 同一份内容再交一次、这一回带了 `proof_review` 的凭据 ⇒ 秘书「改那一行」
            # （不新建）。这是 `evidence_kind` 从弱档走到 `proof_review` 的唯一一条正路：
            # 通用写口 `table.update("statements")` 已被 `store.direct_write_refusal` 拒
            # （它能同时改 bits / proof_text / quote_verified，而没有任何东西核过那些字段）。
            # 对调用方来说这是"成功了"（那一行的档位变了），不是重复读数。
            #
            # `at_tier`（2026-11-04，甲）是同一支里的第二种成功：盘上那一行已经是
            # `proof`（穷举程序 + V 签在落签那一刻就定好的终态），秘书一个格都没改。
            # 这一笔仍要回 `ok=True`（东西在库里、就在它该在的那一档），但话不能说成
            # "档位改上去了"—— 那是另一件事。
            stmt_now = str(written.get("stmt_id") or "")
            at_tier = bool(written.get("at_tier"))
            #: 正文已经在 D2① 那一笔里写进这一行 ⇒ 不再写第二遍（同一份正文两个
            #: 写者），但那一次写的读数（正文 / 历史 / 认签 / 优化态）要照原样带回。
            attach = pre_write or self._attach_proofs(stmt_now, attach_entries,
                                                      canonical=attach_canonical,
                                                      bits=bits,
                                                      proof_no=int(proof_no_placement))
            # ---- 2026-11-08：已在终态档也要把"这一笔认到的签"落到行上 ----------
            #
            # V 只对手稿负责之后，签不再由 V 写 statements；B 的 at_tier 出口（同一条
            # 已在册、档位已是 proof）改前只改 evidence_kind，不看 bits ⇒ "V 签在稿上、
            # 册里位还是假"永远收不了口。这里按同一把尺（`_attach_proofs`）补写一次：
            # 只有这一笔真的认到了签（`v_sign.applied` / `bits.reviewed`）才写。
            _collected = {}
            try:
                _per = _EB.reviewed_by_proof(dict(written.get("row") or {}))
                _already = bool(_per.get(int(proof_no_placement),
                                         _per.get(str(int(proof_no_placement)), False)))
            except Exception:  # noqa: BLE001 —— 读不出现有位就按"没位"继续，写口自己会拒
                _already = False
            if (bool(v_sign.get("applied")) and bool(dict(bits or {}).get("reviewed"))
                    and not _already):
                _collected = self._attach_proofs(
                    stmt_now, [], canonical="", bits=bits,
                    proof_no=int(proof_no_placement))
                if _collected.get("row"):
                    written = {**dict(written), "row": dict(_collected.get("row") or {})}
            if attach.get("written"):
                _landed_got = SL.by_id(self.store, stmt_id=stmt_now)
                if not _landed_got["checked"]:
                    _err = _landed_got.get("error") or {}
                    raise RuntimeError(
                        f"`statements` 读不出来（{_err.get('type') or '?'}: "
                        f"{_err.get('message') or _landed_got.get('reason') or '?'}）")
                _landed_row = _landed_got["row"] or {}
            else:
                _landed_row = dict(written.get("row") or {})
            _landed_has_proof = _row_has_proof(_landed_row)
            out = {"ok": True, "stmt_id": stmt_now,
                   #: 2026-11-04：这一笔把攻坚稿转成正式稿了吗（有才带这一格）。
                **({"promoted_manuscript": dict(pre_gate_promotion)}
                   if pre_gate_promotion else {}),
                   #: 2026-11-04（业主裁定 A 甲）：B 的改写手稿读数（有就带上）。
                **({"b_manuscript": dict(b_manuscript)} if b_manuscript else {}),
                "self_authored_review": self._self_authored_reading(self_authored),
                   "source_lit_id": lit_id or None,
                   "quote_verified": quote_verified, "origin": origin,
                   "quote_mode": str(quote_mode or ""),
                   "evidence_kind": self._evidence_kind_on_disk(stmt_now),
                   "requested_evidence_kind": evidence_kind, "upgraded": True,
                   #: 2026-11-08：两格读数（稿上已签 / 已入台账）。
                   "sign_filing": _sign_filing_reading(
                       self.store, manuscript_path=manuscript_path,
                       manuscript_text=manuscript_text, statement_id=stmt_now),
                   #: 这一笔是不是"盘上已在终态档"（`升级` 与 `本来就在` 分开读）。
                   "at_tier": at_tier,
                   #: 这一支只改在册那一行，不新建（与 duplicate 那一支同一个读数键：
                   #: 调用方按它判"有没有多一行"，缺了会把"改档"读成"建了新行"）。
                   "new_row": False,
                   "has_proof": _landed_has_proof,
                   "proof_no": (int(_landed_row.get("proof_no") or 0)
                                if _landed_has_proof else 0),
                   "proof_sha256": (str(_landed_row.get("proof_sha256") or "")
                                    if _landed_has_proof else ""),
                   "proof_no_source": str(proof_no_source),
                   "row": dict(written.get("row") or {}),
                   #: 依赖面建起来没有（三态；见 `_deps_missing_reading`）。
                   "deps_missing": _deps_reading(written),
                   #: 稿是从参数来的、从盘上读的、还是没有（2026-10-26 的兜底读盘）。
                   "manuscript_source": manuscript_source,
                   #: 正文的来源（`param` / `manuscript` / 空串），口径见新建那一支。
                   "proof_text_source": proof_text_source,
                   "addressing": dict(addressing),
                   "manuscript_washed": manuscript_washed,
                   "manuscript_wash": dict(manuscript_wash),
                   "proof_vs_source": dict(proof_vs_source),
                   "changes": list(written.get("changes") or []),
                   "note": (("这一条没有新建行：同一条 statement_full 已在册，档位已经是 "
                             "`proof`（穷举程序 + V 签的终态）⇒ 这一笔没有新东西可写、"
                             "也不是重复登记"
                             f"（{written.get('reason') or ''}）。"
                             "内容面一个字没动。")
                            if at_tier else
                            ("这一条没有新建行：同一条 statement_full 已在册，而这一笔"
                             "带来的证据档更强（且有凭据）⇒ 秘书把那一条的档位改上去了"
                             f"（{written.get('reason') or ''}）。"
                             "内容面一个字没动；这一笔要改内容，就把差异写进 statement_full "
                             "重新交（正文按规范化比不同才会落新的一行）。"))}
            _deps_receipt(out)
            if at_tier:
                out["terminal_reading"] = dict(written.get("terminal_reading") or {})
            #: 正文超了判档位的读取上限 ⇒ 带上截断读数（见 `_text_truncation_reading`）。
            out.update(trunc_reading)
            #: 换正文那一笔的优化态读数（`optimized` / `optimized_blocked`）：没有换
            #: 正文时这两格不出现（老返回形状逐字不变）。
            out.update(_optimized_reading(attach))
            if proofs_listed:
                out.update(self._proofs_reading(attach))
                pd = self._write_attached_proof_deps(sec, stmt_now, proofs_listed, attach)
                if pd:
                    out["proof_deps"] = pd
            if attach.get("canonical_written"):
                out["canonical_written"] = True
                out["canonical_history"] = list(attach.get("canonical_history") or [])
                out.update(_canonical_rewrite_reading(attach))
                out["note"] += ("这一笔还覆盖了 canonical 正文（`proof_text`）：旧正文整段"
                                "留在行的 `proof_history` 里（sha / at / replaced_by 逐条"
                                "可查）；写入不因 sha 不符被拒。"
                                + str(attach.get("rewrite_note") or ""))
            if proofs_dropped:
                out["proofs_dropped"] = proofs_dropped
            if attach.get("refused"):
                # 升档已经发生（秘书那一笔改完了），所以这里不回滚、也不改 ok；
                # 但"清单没挂上"必须说出来 —— 静默忽略等于让调用方以为交上去了。
                out["note"] += ("这一笔带来的证明清单没有写进库："
                                + str(attach.get("reason") or "")
                                + "（档位那一笔已经落盘，这一格不回滚）")
            # 这一笔带了这条命题自己的手稿 ⇒ 它的依赖面在正文写完之后补落（D7 的 A）。
            md = self._manuscript_deps_after_write(sec, stmt_now, deps_groups)
            if md:
                out["manuscript_deps"] = md
                # ---- D6（2026-11-05 走查）：回执要读"写完之后"的依赖面 ----------
                #
                # `out["deps_missing"]` 是在上面用秘书那一份返回算的（那时这份稿的
                # 依赖边还没落）⇒ 同一份回执里"刚写了 1 条"与"一条依赖行都没有"
                # 互相打架。把后落的那几条加进去重算，读数才是这一笔写完的状态。
                out["deps_missing"] = _deps_reading(
                    written, extra_deps=int(md.get("deps_written") or 0))
            out["v_sign"] = dict(v_sign)
            #: 2026-11-02：二次寻址的读数（清单来源 / 地址 / 命中 / 模式 auto|model|unknown）。
            out["addressing"] = dict(addressing)
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
            #: D2① 已经写过正文的那一笔不写第二遍（读数照原样带回，见升档那一支）。
            attach = pre_write or self._attach_proofs(stmt_dup, attach_entries,
                                                      canonical=attach_canonical,
                                                      bits=bits,
                                                      proof_no=int(proof_no_placement))
            if attach.get("written"):
                _dup_got = SL.by_id(self.store, stmt_id=stmt_dup)
                if not _dup_got["checked"]:
                    _err = _dup_got.get("error") or {}
                    raise RuntimeError(
                        f"`statements` 读不出来（{_err.get('type') or '?'}: "
                        f"{_err.get('message') or _dup_got.get('reason') or '?'}）")
                _dup_row = _dup_got["row"] or {}
            else:
                _dup_row = dict(written.get("row") or {})
            _dup_has_proof = _row_has_proof(_dup_row)
            if attach.get("refused"):
                return _refuse(str(attach["refused"]), str(attach.get("reason") or ""),
                               stmt_id=stmt_dup,
                               **_optimized_reading(attach))
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
                       #: 2026-11-04：这一笔把攻坚稿转成正式稿了吗（有才带这一格）。
                    **({"promoted_manuscript": dict(pre_gate_promotion)}
                       if pre_gate_promotion else {}),
                    #: 2026-11-04（业主裁定 A 甲）：B 的改写手稿读数（有就带上）。
                    **({"b_manuscript": dict(b_manuscript)} if b_manuscript else {}),
                    #: 2026-11-04（业主裁定 A 甲）：B 的改写手稿读数（有就带上）。
                **({"b_manuscript": dict(b_manuscript)} if b_manuscript else {}),
                "self_authored_review": self._self_authored_reading(self_authored),
                       "source_lit_id": lit_id or None,
                       "quote_verified": quote_verified, "origin": origin,
                       "quote_mode": str(quote_mode or ""),
                       "evidence_kind": self._evidence_kind_on_disk(stmt_dup),
                       "requested_evidence_kind": evidence_kind, "new_row": False,
                       #: 2026-11-08：两格读数（稿上已签 / 已入台账）。
                       "sign_filing": _sign_filing_reading(
                           self.store, manuscript_path=manuscript_path,
                           manuscript_text=manuscript_text, statement_id=stmt_dup),
                       "has_proof": _dup_has_proof,
                       "proof_no": (int(_dup_row.get("proof_no") or 0)
                                    if _dup_has_proof else 0),
                       "proof_sha256": (str(_dup_row.get("proof_sha256") or "")
                                        if _dup_has_proof else ""),
                       "proof_no_source": str(proof_no_source),
                       #: 依赖面建起来没有（三态；见 `_deps_missing_reading`）。
                       "deps_missing": _deps_reading(written),
                       #: 稿是从参数来的、从盘上读的、还是没有（2026-10-26 的兜底读盘）。
                       "manuscript_source": manuscript_source,
                       #: 正文的来源（`param` / `manuscript` / 空串），口径见新建那一支。
                       "proof_text_source": proof_text_source,
                       "addressing": dict(addressing),
                       "manuscript_washed": manuscript_washed,
                       "manuscript_wash": dict(manuscript_wash),
                       "proof_vs_source": dict(proof_vs_source),
                       # 升档没发生时把"还差什么"一并带回（`proof_review_gap` 的原话在
                       # `written.reason` 里）：只说"重复读数"会让模型以为档位已经升上去了。
                       "note": ("这一条没有新建行（同一条命题已在册）。"
                                + (str(written.get("reason") or "")
                                   if str(written.get("reason") or "").strip() else ""))}
                _deps_receipt(out)
                #: 正文超了判档位的读取上限 ⇒ 带上截断读数（见 `_text_truncation_reading`）。
                out.update(trunc_reading)
                #: 换正文那一笔的优化态读数（逐份 + 被拦下的原因）。
                out.update(_optimized_reading(attach))
                if attach.get("canonical_written"):
                    out["canonical_written"] = True
                    out["canonical_history"] = list(attach.get("canonical_history") or [])
                    out.update(_canonical_rewrite_reading(attach))
                    out["note"] += (
                        "这一笔带来的 canonical 正文已经写进 `proof_text`：旧正文整段留在"
                        "行的 `proof_history` 里（每条 `{text, sha, at, replaced_by}`，"
                        "`sha` 能与签名台账的 `proof_sha256` 直接对上）；写入不因 sha 不符"
                        "被拒。" + str(attach.get("rewrite_note") or ""))
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
                # 这一笔带了这条命题自己的手稿 ⇒ 它的依赖面在正文写完之后补落（D7 的 A）。
                md = self._manuscript_deps_after_write(sec, stmt_dup, deps_groups)
                if md:
                    out["manuscript_deps"] = md
                    # ---- D6（2026-11-05 走查）：同升档那一支，读"写完之后"的依赖面。
                    out["deps_missing"] = _deps_reading(
                        written, extra_deps=int(md.get("deps_written") or 0))
                out["v_sign"] = dict(v_sign)
                #: 2026-11-02：二次寻址的读数（清单来源 / 地址 / 命中 / 模式 auto|model|unknown）。
                out["addressing"] = dict(addressing)
                if upgrade_skipped:
                    # D2：升档没有请求（闸不会认这一份的签）⇒ 这一格单独说清楚。
                    # `ok=true` 只代表正文登记了；`upgraded=false` + 拒码是另一件事。
                    out["upgraded"] = False
                    out["upgrade_refused"] = dict(upgrade_skipped)
                    out["note"] += (
                        "这一笔只登记了正文，没有请求升档："
                        f"请求的档位是 `{upgrade_skipped['requested_evidence_kind']}`，"
                        f"拒码 `{upgrade_skipped['refused']}`（{upgrade_skipped['why']}）。")
                return out
            if proofs_listed and not attach.get("already"):
                return _refuse("proofs_not_attached",
                               str(attach.get("reason") or "证明清单没挂上"),
                               stmt_id=stmt_dup,
                               evidence_kind=self._evidence_kind_on_disk(stmt_dup),
                               requested_evidence_kind=evidence_kind)
            # 对调用方来说这是"这一次没有新行"，必须说出来（`ok=False` + `kind`），
            # 并把既有那一条的号给它 —— 否则它只会看到"没写成"而不知道东西在哪。
            #
            # 拒信指一个本动作根本没有的参数，等于把模型送去撞 invalid_params —— 拒信要能把模型
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
                           stmt_id=stmt_dup,
                           # 档位回读（真机 82 · A-4）：回执说盘上的档，请求值另起一格。
                           # 这一格是"我要求升、但没升成"与"我本来就要弱档"的唯一分界。
                           evidence_kind=self._evidence_kind_on_disk(stmt_dup),
                           requested_evidence_kind=evidence_kind)
        if not written.get("checked") or not written.get("created"):
            extra = {k: v for k, v in written.items()
                     if k in ("literature_rows", "available_lit_ids", "unresolved")}
            return _refuse(str(written.get("refused") or "write_failed"),
                           str(written.get("reason") or "秘书没写这一笔"),
                           stmt_id=str(written.get("stmt_id") or ""), **extra)
        stmt_id = str(written["stmt_id"])
        #: 2026-11-04：登记成功（号已经有了）⇒ 把这一笔交来的那份稿转成按号命名的
        #: 正式稿（`reports/f-proof-<号>.md`）。判据本体在 `agent_f.manuscript`。
        promotion = self._promote_formal_manuscript(
            stmt_id=stmt_id, rel=(manuscript_path or ""), text=manuscript_text,
            source=str(manuscript_source or ""))
        data = dict(written.get("row") or {})
        attach = self._attach_proofs(stmt_id, attach_entries,
                                     canonical=attach_canonical,
                                     bits=bits,
                                     proof_no=int(proof_no_placement))
        if attach.get("refused"):
            # 换正文那一笔被拒（`optimized_blocked`：没有签 / 签的不是这一份）⇒ 不许当
            # 成功返回：盘上那一份 `proof_text` 一个字都没动，读数在 `_optimized_reading`。
            return _refuse(str(attach["refused"]), str(attach.get("reason") or ""),
                           stmt_id=stmt_id, **_optimized_reading(attach))
        if proofs_listed and not attach.get("written"):
            # 行已经由秘书落好了（#p1 在盘上），而清单没挂上 —— 不许当成功返回：
            # 调用方会以为"这条定理的第二份证明交上去了"。如实报，并给出 stmt_id。
            return _refuse("proofs_not_attached",
                           ("命题那一行已经落好了（stmt_id 见下），而证明清单没挂上："
                            + str(attach.get("reason") or "原因不明")
                            + " ⇒ 第 2 份及以后的证明没有写进库（不是写了一半，是那几条没写）"),
                           stmt_id=stmt_id)
        if attach.get("written"):
            _data_got = SL.by_id(self.store, stmt_id=stmt_id)
            if not _data_got["checked"]:
                _err = _data_got.get("error") or {}
                raise RuntimeError(f"`statements` 读不出来（{_err.get('type') or '?'}: "
                                   f"{_err.get('message') or _data_got.get('reason') or '?'}）")
            data = _data_got["row"] or data
        # ---- 2026-11-02（②）：「先有签、后登记」认到的那一签，拿到号之后回写台账行。
        #
        # 为什么落在这里：`vsigns.bits_after_sign` 在"新建"这一档只能按正文 sha 认签
        # （号是秘书在事务里现发的，此刻还没有），所以它交回来的 `claim` 里没有号。
        # 不回写的话，同一份正文登记两次就会认领两次 —— 两笔的 `statement_id` 不同，同一份
        # pending 签会同时被记在两条命题名下（`#p2` 不许借 `#p1` 的光，反方向同理）。
        # 回写的判据只有一处（`vsigns.bind_pending_claim`），这里只负责在"号有了、而且
        # 这一版 bits 真的跟着这一行落盘（`bits.reviewed` 为真）"时调它：dup / merge 那几支
        # 的 bits 不一定写进盘上那一行（`_attach_proofs` 只在 canonical 被覆盖时合并 bits），
        # 没落盘却回写 = 白占掉一份别人还能用的签。
        if dict(v_sign.get("claim") or {}) and bool(dict(data.get("bits") or {}).get("reviewed")):
            from agentflow import vsigns as _VS

            claim_now = dict(v_sign.get("claim") or {})
            bound = _VS.bind_pending_claim(getattr(self.store, "root", ""),
                                           claim=claim_now, statement_id=stmt_id)
            claim_now.update(bound=bool(bound.get("bound")),
                             bound_id=(stmt_id if bound.get("bound")
                                       else str(bound.get("bound_elsewhere") or "")),
                             bind=bound)
            v_sign = {**dict(v_sign), "claim": claim_now}
            if bound.get("bound"):
                v_sign["why"] = (str(v_sign.get("why") or "")
                                 + "；并已把 statement_id 回写到 pending 台账行"
                                   "（同一份正文只认领一次）")
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
        #: 正文被改写时的签读数（`_attach_proofs` 的 `canonical_changed` 那一格算的）：
        #: 只在真覆盖了 canonical 时出现 —— 老写法的返回值逐字不变。
        rewrite_reading = (_canonical_rewrite_reading(attach)
                           if attach.get("canonical_written") else {})
        rewrite_note = (str(attach.get("rewrite_note") or "")
                        if attach.get("canonical_written") else "")
        #: 换正文那一笔的优化态读数（逐份 + 被拦下的原因）。没有换正文时是空字典 ——
        #: 老写法的返回值逐字不变。
        optimized_reading = _optimized_reading(attach)
        #: 2026-11-05（缺陷 1c）：依赖面读数（三态）只算一次，回执那一行也从它取 ——
        #: 同一件事不许在 `deps_missing` 与 `note` 里各算一遍（两个口径迟早分家）。
        deps_reading_now = _deps_reading(written)
        deps_line = str(deps_reading_now.get("deps_receipt") or "")
        #: 2026-11-08（V 只对手稿负责）：收录回执带两格读数 —— 稿上已签 / 已入台账。
        sign_filing = _sign_filing_reading(
            self.store, manuscript_path=manuscript_path,
            manuscript_text=manuscript_text, statement_id=stmt_id)
        # ---- 缺陷 ③：这一行现在到底有没有一份证明（读数与盘上同一个判据） ----------
        # `has_proof` 是显式读数：e-num 那一档 `proof_text=""`、清单空 ⇒ false，
        # 顶层不写 `proof_no`（0）；有手稿正文的那一档 ⇒ true，号与 sha 由
        # `_attach_proofs` 的收录回执写进 statements 顶层。
        _row_proof_now = _row_has_proof(data)
        return {"ok": True, "stmt_id": stmt_id, "source_lit_id": lit_id or None,
                #: D2：这一笔的号是从稿名 / 稿头当候选来的（有才带这一格；见下候选号那一段）。
                **({"stmt_id_candidate": candidate_stmt_id,
                    "stmt_id_candidate_source": candidate_source}
                   if candidate_stmt_id else {}),
                **optimized_reading,
                #: 2026-11-04：这一笔有没有把稿转成按号命名的正式稿（有才带这一格）。
                **({"promoted_manuscript": dict(promotion)} if promotion else {}),
                #: B-3 的写侧读数：这一笔要不要 V 的签、有没有拿到（见 `_self_authored_gate`）。
                #: 2026-11-04（业主裁定 A 甲）：B 的改写手稿读数（有就带上）。
                **({"b_manuscript": dict(b_manuscript)} if b_manuscript else {}),
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
                #: 2026-11-08：收录时的两格读数（稿上已签 / 已入台账；四态在 `state`）。
                "sign_filing": dict(sign_filing),
                #: 2026-11-08：普通数值通道的读数（只在真走了那条通道时出现）。
                #: 手稿路径 / 实验号 / 程序路径 / 形态闸的判定 ——
                #: "为什么这一条没要 V 签"读的就是它。
                **({"numeric_channel": {
                    "path": str(_green.get("path") or ""),
                    "experiment_id": str(_green.get("experiment_id") or ""),
                    "code_path": str(_green.get("code_path") or ""),
                    "evidence_kind": evidence_kind,
                    "proof_text": "(空着：普通数值档，业主明令)",
                    "dropped_content": list(_green.get("dropped_content") or []),
                    "proposition_form": dict(_green.get("proposition_form") or {}),
                    "manuscript_sha256": str(
                        (_green.get("manuscript") or {}).get("sha256") or ""),
                }} if _green.get("ok") else {}),
                #: 2026-11-08（业主）：同一命题检索的读数（查到 / 没查到、关键词、命中）。
                #: 只有真查过一圈时才有这几格（老返回形状逐字不变）。
                **({"searched": _same_search_reading(_same_search),
                    "found": str(_same_search.get("found") or ""),
                    "why": str(_same_search.get("why") or ""),
                    "same_statement": _same_search_reading(_same_search)}
                   if _same_search else {}),
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
                #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                "deps_stmt_edges": int(written.get("deps_stmt_edges") or 0),
                "deps_dangling": list(written.get("deps_dangling") or []),
                "deps_unmappable": list(written.get("deps_unmappable") or []),
                #: 依赖面建起来没有（三态）：带证明正文而一条依赖都没落 ⇒ `state=missing`
                #: （改前这件事只活在 `deps_written=0` 里，没有任何一格会因此变红 ——
                #: 真机 sylow3 七条命题、依赖全表 0 行，就是静默过去的）。
                "deps_missing": deps_reading_now,
                #: 认签读数（只在真认到一签时出现：新建那一档的老返回形状逐字不变）：
                #: 键与另外三条"没有新建行"的出口同名（`v_sign`），三态都在读数里。
                **({"v_sign": dict(v_sign)} if v_sign.get("found") else {}),
                #: 稿是从参数来的、从盘上读的、还是没有（2026-10-26 的兜底读盘）：
                #: 这一格让"没人传参"与"B 按约定路径读到了"在读数上分得开。
                "manuscript_source": manuscript_source,
                #: 2026-11-04（业主裁定 A 甲）：这一笔有没有（以及怎么）落 B 的改写手稿。
                #: 只在真落了/真检查过时出现 —— 老返回形状逐字不变。
                **({"b_manuscript": dict(b_manuscript)} if b_manuscript else {}),
                #: 这一笔的正文是从哪来的（2026-11-02，D 侧是主路）：`param`（调用方直递）/
                #: `manuscript`（按 D 的携带单寻址到的那份稿的 `## 证明` 那一节）/ 空串。
                #: 与 `manuscript_source` 分开：那一格说稿从哪来，这一格说落进 `proof_text`
                #: 的是不是那份稿 —— 两者都缺时，正文只能靠调用方手工粘（真机 85 就是这样）。
                "proof_text_source": proof_text_source,
                "addressing": dict(addressing),
                "manuscript_washed": manuscript_washed,
                "manuscript_wash": dict(manuscript_wash),
                #: 与来源是否逐字一致（信息格，不是门）：`same=None` = 没有可比对的那一份。
                "proof_vs_source": dict(proof_vs_source),
                #: 证明号与它的来源（缺口 ①）：`crafted` / `carried` / `fallback` ——
                #: 回退也要说，否则"读了"与"猜的"在读数上分不开。
                #: 缺陷 ③：没有证明的那一档（e-num / 空证明）不写号（0），并把
                #: `has_proof=false` 显式给出 —— "第 1 份证明"只属于真有一份正文的行。
                "has_proof": _row_proof_now,
                "proof_no": (int(data.get("proof_no") or 0)
                             if _row_proof_now else 0),
                "proof_sha256": (str(data.get("proof_sha256") or "")
                                 if _row_proof_now else ""),
                "proof_no_source": str(proof_no_source),
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
                #: 秘书落下的 `proof_text` 与这一笔交来的不同），旧正文的留痕与那一签的
                #: 现行读数（`review_standing` / `resign_required`）一并给出来。
                **({"canonical_written": True,
                    "canonical_history": list(attach.get("canonical_history") or []),
                    **rewrite_reading}
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
                         + ("这一行缺 proof_text（自产命题没有证明）：它进去了，"
                            "但等级现算是『猜想』，`pending` 里挂着待办。"
                            if needs_proof else "")
                         + (f"概念行不带 proof_text：交来的 {proof_text_dropped!r} "
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
                            if attach.get("formal_synced") else "")
                         + rewrite_note + (f"；{deps_line}" if deps_line else ""))}

    # ------------------------------------------------- 收方读稿登记（D 携带来的那一份）
    #
    # 业主 2026-10-26 晚的原话：「D 到 B 没有路吗？加」+「把稿交给 B」。
    # 这一支是那条路在 B 侧的落点：D 的代码直接调 `B.register_statement(...)`，
    # 命题已经在册（F 落的行）⇒ 不新建、不重判档位，只把这一份手稿的依赖段落成边。

    # ---------------------------------------------------------------- 解耦壳（2026-11-07）
    #
    # 业主原话（逐字）：
    #   「要让注册命题和写证明两件事解耦，不然无法做到只一遍又一遍修改证明」
    #   「B的重写一样（只是B不用再注册命题，命题拿已经登记的待优化的）」
    #
    # 这一层只做两件事，原来的登记实现一个字都没动（`_register_statement_impl`）：
    #
    # 1. 调用方是 F ⇒ 受控拒 `f_proposition_must_be_a_manuscript`：F 的命题必须先
    #    落成手稿登记条目（`reports/f-proof-*.md`，过 F 秘书的形态闸），B 在 V 签之后
    #    按 sha 收录。F 直接用 `framework_summon` 派 B 登记这条路不再绕开那道闸。
    # 2. 已登记命题的新证明（命题正文逐字相同、而证明正文不同）⇒ 先把
    #    `reports/b-proof-<号>.md` 就地重写一版（`proofregistry`，`proof_no` 递增、
    #    正文 sha 重算、只换 `## 证明` 那一节），再交给原实现去挂那一份证明。
    #    ⇒ 「登记」只发生一次；之后每一版证明只换手稿，不新登记、不新增 statements 行。
    F_CALLER_REFUSED = "f_proposition_must_be_a_manuscript"

    def register_statement(self, *, statement_full: str = "",
                           source_lit_id: str = "",
                           proof_text: str = "",
                           proofs: list | None = None,
                           proof_manuscript: str = "",
                           kind: str = "",
                           label: str = "",
                           statement_text: str = "",
                           origin: str = "",
                           page_range: dict | None = None,
                           evidence_kind: str = "",
                           quote_verified: bool | None = None,
                           quote_reason: str = "",
                           quote_mode: str = "",
                           quote_span: str = "",
                           quote_call_sha256: str = "",
                           derived_from: list | None = None,
                           doc_id: str = "",
                           line_range: dict | None = None) -> dict:
        """B 的动作入口：F 的命题必须走手稿登记；已登记命题的证明重写只重写手稿。

        判据与读数见本类顶上那一段注释。参数面与 `_register_statement_impl` 逐字相同
        （动作声明面读的是这个方法）。

        ## 两种形态（2026-11-08）

        - 按手稿路径收录（D 那一侧只走这一种）：`statement_full` 空 + `proof_manuscript`
          是一份工作区相对路径 ⇒ 命题正文 / 证明正文 / `kind` / `evidence_kind` / 出处
          全部由 B 从那份稿里读（`_register_pointer_manuscript`）。调用方只递指针：
          稿路径 + 命题号/实验号 + 出处（`line_range={"label": "exp:<号>"}`）。
        - 正文登记（文献侧 / B 自己改写 / 历史调用）：沿用改前逐字一致的参数面。

        为什么 D 传正文就受控拒（业主 2026-11-08「D对命题台账只有只读权限」）：
        D 把稿里的内容抄进参数，等于让"登记的那一份"与"稿里的那一份"分成两个来源，
        而没有任何东西保证它们逐字相同；这一笔的承重证据是 E/F 的成果，那就只能由
        收方从成果里读。拒信逐字点名「只递指针」，并说清改法。
        """
        caller = _caller_role()
        if caller == "F":
            return _refuse(
                self.F_CALLER_REFUSED,
                ("F 交来的命题不能直接走 `B.register_statement`：请把它登记成手稿条目"
                 "（`reports/f-proof-<命题号>.md`，新命题会过 F 秘书的形态闸），"
                 "B 在 V 签之后按正文 sha 收录。这条派活路径不再绕开手稿登记"))
        rel = _pointer_manuscript_rel(proof_manuscript)
        if _caller_is_d():
            # 注意：`locals()` 必须在函数作用域里取（推导式有自己的作用域，
            # 在推导式里取到的是 `name` / `label` 那两个循环变量本身）。
            _args = dict(locals())
            carried = [label for name, label in _POINTER_ONLY_BODY_FIELDS
                       if _pointer_body_present(name, _args.get(name))]
            if carried:
                return _refuse(
                    D_POINTER_ONLY_REFUSAL,
                    ("D 交稿**只递指针**（业主 2026-11-08：D 对命题台账只有只读权限，"
                     "向 B 提交的每一条都要有 E / F 的成果背书）：这一笔还带着 "
                     + "、".join(carried)
                     + " —— 那些内容一律由 **B 从手稿里读**，D 不许另传（抄一遍就等于"
                     "给「登记的那一份」换了个来源）。改法：只给 `proof_manuscript=<手稿"
                     "工作区相对路径>`，再给命题号 / 实验号与出处（`exp:<号>`）；"
                     "命题正文、证明正文、kind、evidence_kind 与引文理由都由 B 从那份稿里读"))
            if not rel:
                return _refuse(
                    D_POINTER_ONLY_REFUSAL,
                    ("D 交稿**只递指针**：这一笔没有给手稿路径（`proof_manuscript` 读到 "
                     f"{str(proof_manuscript or '')[:60]!r}）⇒ 整笔不写。改法：只递指针 —— "
                     "`proof_manuscript` 给那份稿的工作区相对路径"
                     "（`reports/e-proof-<实验号>.md` / `reports/e-num-<实验号>.md` / "
                     "`reports/f-proof-*.md`），再给命题号 / 实验号与出处；"
                     "命题正文、证明正文、kind、evidence_kind 都由 B 从那份稿里读"))
        if rel and not str(statement_full or "").strip():
            # 2026-11-10（T1，设计 §2.8）：pointer 支改为委托
            # `ingest_manuscript(mode="register")` —— 提取、族表、逐格回执、两条不变量
            # 与两个新动作走同一份实现；`pointer` 读数由 ingest 原样带回（既有判据与
            # D 的直调都还读它）。
            return self.ingest_manuscript(
                manuscript=rel, mode="register", cells=(), conflict="refuse",
                reason="按手稿路径收录（D 只递指针）", provenance=line_range)
        got = self._register_statement_impl(
            statement_full=statement_full, source_lit_id=source_lit_id,
            proof_text=proof_text, proofs=proofs, proof_manuscript=proof_manuscript,
            kind=str(kind or "theorem"), label=label, statement_text=statement_text,
            origin=str(origin or "external_lit"),
            page_range=page_range, evidence_kind=str(evidence_kind or "cross_check"),
            quote_verified=quote_verified, quote_reason=quote_reason,
            quote_mode=quote_mode, quote_span=quote_span,
            quote_call_sha256=quote_call_sha256, derived_from=derived_from,
            doc_id=doc_id, line_range=line_range)
        return self._apply_declared_manuscript_kind(
            got, statement_full=statement_full, origin=str(origin or "external_lit"),
            kind=str(kind or "theorem"), proof_manuscript=proof_manuscript)

    def _register_pointer_manuscript(self, rel: str, *, provenance: Any = None,
                                     reading: Mapping | None = None
                                     ) -> tuple[dict, str, str]:
        """按手稿路径收录：把该登记的那几样全部从稿里读出来（D 只递了指针）。

        业主 2026-11-08 逐字：「D对命题台账只有只读权限，D向B提交要登记的命题时
        都是有证明或数值实验的（即E和F的成果）…B侧做好适配（应该在手稿里找命题和
        数值实验程序，不录入其它内容）」。

        ## 2026-11-10（T1 接线）：提取归秘书，本体不再自己读稿

        `reading` 由 `Secretary.extract_manuscript` 给出（`own.ingest_manuscript`
        `mode=register` 这条路会传进来）；不给时本方法自己向秘书要一份 —— 于是"切节 /
        读稿头 / 认三态"的实现全仓只有 `manuscriptintake` 一处；读不到照样按
        `manuscript_unreadable` 受控拒，不退化成"让调用方贴正文"。
        ## 读什么、从哪读（三族手稿各一条，判据只有这一处）

        | 这一格 | 从稿的哪儿读 |
        |---|---|
        | 命题正文 | `## 命题` 那一节（三族同形；E 的 `e-num-*` 也是它） |
        | 证明正文 | `## 证明` 那一节（`e-num-*` 没有这一节：普通数值档 `proof_text` 留空） |
        | `kind` | 稿头 `- 证据种类：<kind>`（认不出 / 词表外 ⇒ 按族取缺省：`e-proof` ⇒ theorem、其余 ⇒ conjecture） |
        | `evidence_kind` | 按族定：`e-proof` ⇒ `proof`（穷举证明，要 V 签）、`e-num` ⇒ `cross_check`（有数值实验支持）、F 的文字证明 ⇒ `heuristic` |
        | 出处 `line_range` | `e-*` ⇒ `exp:<实验号>`（稿头 / 路径名 / 调用方给的出处，三者同一处）；F ⇒ 稿的路径本身 |
        | 承重链 `derived_from` | 证明正文里的 `stmt:` 引用（与 `depsection.stmt_refs` 同一口径） |
        | `label` | F 的稿头 `- 标签：`；E 的取命题首行前 80 字 |

        返回 `(B 的登记结果, origin, kind)`；受控拒时 origin / kind 是空串。
        """
        from .. import depsection as _DS
        from .. import exhaustionreport as _ER

        numeric = _ER.is_numeric_manuscript_relpath(rel)
        if reading is None:
            sec = self._statement_secretary()
            if sec is None:
                return _refuse(
                    "secretary_unavailable",
                    "按手稿路径收录：这一趟没有秘书 ⇒ 读不了稿、也写不了台账"
                    + (f"（{self.secretary_problem}）"
                       if getattr(self, "secretary_problem", "") else ""), "", "")
            reading = sec.extract_manuscript(
                rel, ("statement_full", "proof_text"))
        if not reading.get("checked"):
            _why = str(reading.get("why") or f"读不到 `{rel}`")
            return _refuse(
                "manuscript_unreadable",
                f"按手稿路径收录：{_why} ⇒ 整笔不写"
                "（读不到的稿不能当成没有；也不能退回让调用方贴正文）"), "", ""
        cells = dict(reading.get("cells") or {})
        statement_cell = dict(cells.get("statement_full") or {})
        statement = str(statement_cell.get("value") or "").strip()
        if (statement_cell.get("outcome") != _MI.EXTRACT_PRESENT
                or not statement):
            return _refuse(
                "pointer_manuscript_missing_statement",
                f"按手稿路径收录：`{rel}` 里没有 `## 命题` 那一节 ⇒ 不知道要给 B 登记哪一条"
                "命题。这一格**由 B 从稿里读**，不许调用方在参数里另贴一段"), "", ""
        #: 这份稿的 `## 证明` 三态（2026-11-09，D4）：`present` / `absent`。
        #: 普通数值档（`e-num-*`）本来就没有这一节，`proof_text` 按业主口径强制空；
        #: 其余族缺节 ⇒ 受控拒（下面那一支），不许退回让调用方贴正文，也不许拿
        #: `## 依赖` / 整份全文顶替。
        _proof_state = str(reading.get("proof_state") or "")
        proof_cell = dict(cells.get("proof_text") or {})
        proof_text = ("" if numeric
                      else str(proof_cell.get("value") or "").strip("\n"))
        if not numeric and not proof_text.strip():
            _absent = _proof_state == _MI.EXTRACT_ABSENT
            return _refuse(
                "pointer_manuscript_missing_proof",
                (f"按手稿路径收录：`{rel}` 里没有 `{_DS.SECTION_PROOF}` 那一节 ⇒ "
                 "没有可登记的证明正文（缺节不等于「证明为空」：不拿 `## 依赖` 或整份"
                 "全文顶替）" if _absent else
                 f"按手稿路径收录：`{rel}` 里 `{_DS.SECTION_PROOF}` 那一节是空的 ⇒ "
                 "没有可登记的证明正文")
                + "。这一格**由 B 从稿里读**，不许调用方在参数里另贴一段",
                proof_body_state=_proof_state), "", ""
        # 2026-11-09（T2 收编，设计 3.2 第 2 处）：族判定只读 `manuscriptfamily.classify_manuscript`。
        # `notes/` 的手稿形名字读成 legacy（不可签、不可收录）；`reports/b-proof-*`
        # 不再落到 unrecognized，而是 b-proof 族（可签、可收录）。
        _family_reading = _MFAM.classify_manuscript(rel)
        _tier = str(_family_reading.get("tier") or "")
        if _tier == _MFAM.TIER_LEGACY:
            return _refuse(
                "manuscript_legacy_name",
                f"按手稿路径收录：`{rel}` 是历史档（{_family_reading.get('code')}）"
                f"⇒ 不可收录、也不可签。规范名是 "
                f"{_family_reading.get('canonical') or '（拼不出）'}；"
                "要收录请先把它落成规范名（`reports/<族>-<号>[-p<N>].md`）"), "", ""
        if _tier == _MFAM.TIER_BAD:
            return _refuse(
                _MFAM.CODE_BAD,
                f"按手稿路径收录：手稿名 {rel!r} 认不出号（{_family_reading.get('why')}）"
                " ⇒ 整笔不写。这一格不猜：认不出号的稿没有可签的载体"), "", ""
        _pointer_family = str(_family_reading.get("family") or "")
        if _pointer_family == "e-num":
            family, default_kind, evidence_kind = "e-num", "conjecture", "cross_check"
        elif _pointer_family == "e-proof":
            family, default_kind, evidence_kind = "e-proof", "theorem", "proof"
        elif _pointer_family == "f-proof":
            family, default_kind, evidence_kind = "f-proof", "conjecture", "heuristic"
        elif _pointer_family == "b-proof":
            # B 的改写稿：档位按签 / 台账现值（表的行为列），登记这一笔先按文字证明取缺省。
            family, default_kind, evidence_kind = "b-proof", "conjecture", "heuristic"
        else:
            return _refuse(
                "pointer_manuscript_unrecognized",
                f"按手稿路径收录：认不出 `{rel}` 是哪一族手稿（E 的 `reports/e-proof-*` / "
                "`reports/e-num-*`，F 的 `reports/f-proof-*`，B 的 `reports/b-proof-*`）"
                "⇒ 整笔不写。这一格不猜：认不出族的稿没有「该从哪一节读什么」的契约"), "", ""
        declared = str(reading.get("declared_kind") or "")
        prov_label = ""
        if isinstance(provenance, Mapping):
            prov_label = str(provenance.get("label") or "").strip()
        # ---- 这一份稿点名的是"哪一条命题"（B 自己从稿里读，不由调用方另传） --------
        #
        # 已在册的命题：稿头 `- 命题号：stmt:<号>`（F 的登记条目 / 按号命名的稿）或
        # 调用方给的出处标签 `stmt:<号>`。命中在册那一行 ⇒ 命题正文、短版与 label 取
        # 在册那一行（B 自己的台账）：这一笔是"给一条在册命题挂上这份证明"，
        # 不是"重新登记它的命题"—— 拿稿里那段去重会让同一命题因措辞漂移落成第二行。
        # 读数 `pointer.proposition_source` 说清正文取的是哪一处，`proposition_matches_manuscript`
        # 记稿里那一段与在册正文字面是否一致（不一致是读数，不是静默改写）。
        head_sid = str(reading.get("head_statement_id") or "").strip()
        if not head_sid and prov_label.startswith("stmt:"):
            head_sid = prov_label.split(":", 1)[-1].strip()
        row_now: dict | None = None
        if head_sid:
            # 按号定位走查口（口径一）；读不到台账 ⇒ 这一格没查成（不是不在册）。
            got = SL.by_id(self.store, stmt_id=head_sid)
            if not got["checked"]:
                err = got.get("error") or {}
                return _refuse(
                    "pointer_ledger_unreadable",
                    f"按手稿路径收录：稿头点名了在册命题 stmt:{head_sid}，而 `statements` "
                    f"台账读不出来（{err.get('type', '?')}: {err.get('message', '?')}）"
                    "⇒ 整笔不写（读不到 ≠ 不在册）", "", "")
            row_now = got["row"] if got["found"] else None
            if row_now is None:
                return _refuse(
                    "pointer_statement_missing",
                    f"按手稿路径收录：稿 `{rel}` 点名了 stmt:{head_sid}，而它在 `statements` "
                    "台账里找不到 ⇒ 整笔不写（B 不替它另发一个号：那会让稿头号与登记号错位）"), "", ""
        kind = declared or (str(row_now.get("kind") or "").strip() if row_now else "") \
            or default_kind
        if row_now is not None:
            proposition = str(row_now.get("statement_full") or statement)
            statement_text = str(row_now.get("statement_text") or "")
            label = str(row_now.get("label") or "")
            evidence_kind = str(row_now.get("evidence_kind") or evidence_kind)
            origin_now = str(row_now.get("origin") or "own_result")
            # 出处沿用这一行自己的（它是 B 上一笔登记时写的，不是这一笔的输入）。
            line_range = dict(row_now.get("line_range") or {}) or {"label": rel}
            doc_id = str(row_now.get("doc_id") or "")
        else:
            proposition = statement
            eid = str(_ER.experiment_id_of(rel) or "").strip()
            head_eid = str(reading.get("head_experiment_id") or "")
            if not eid and head_eid:
                eid = head_eid.split(":", 1)[-1].strip()
            if family in ("e-num", "e-proof"):
                label = (prov_label if prov_label.startswith(_ER.EVIDENCE_PREFIX)
                         else f"{_ER.EVIDENCE_PREFIX}{eid}" if eid else "")
                line_range = {"label": label or rel}
                doc_id = ""
            else:
                line_range = {"label": rel}
                doc_id = ""
            statement_text = str(reading.get("head_statement_text") or "")
            label = ((str(reading.get("head_label") or "").strip()
                      if family in ("f-proof", "b-proof") else "")
                     or " ".join(proposition.split())[:80])
            origin_now = "own_result"
        quote_reason = (
            f"手稿收录（D 只递指针）：命题正文、证明正文与档位全部逐字取自 `{rel}` —— "
            "引文面不适用（这份稿是我们自己产出的成果，不是文献里摘的）；"
            "V 的签（若有）在手稿块上"
            if not numeric else
            f"手稿收录（D 只递指针）：普通数值手稿 `{rel}` —— 命题逐字取自 `## 命题`，"
            "证明栏空着（业主 2026-11-08：普通数值档不写证明正文），程序在实验行的 "
            "`code_path`，引文面不适用")
        got = self._register_statement_impl(
            statement_full=proposition, statement_text=statement_text,
            proof_text=proof_text, proofs=None, proof_manuscript=rel,
            kind=kind, label=label, origin=origin_now,
            evidence_kind=evidence_kind, quote_verified=None,
            quote_reason=quote_reason,
            derived_from=[str(x) for x in (_DS.stmt_refs(proof_text) or ())],
            doc_id=doc_id, line_range=line_range)
        if isinstance(got, dict):
            got["pointer"] = {
                "path": rel,
                "statement_id": head_sid,
                "proposition_source": ("ledger" if row_now is not None else "manuscript"),
                "proposition_matches_manuscript": bool(
                    not row_now
                    or _same_manuscript_text(
                        str(row_now.get("statement_full") or ""), statement)),
                "d_gave_only_pointers": True,
            }
        return got, origin_now, kind

    def _apply_declared_manuscript_kind(self, got: dict, *, statement_full: str,
                                        origin: str, kind: str,
                                        proof_manuscript: str,
                                        declared_kind: str = "") -> dict:
        """已登记命题：手稿头声明了 `lemma` / `example` 而 V 的签已把等级抬到
        `pre_theorem` 以上 ⇒ 按那一档把 kind 升上去（只写 `kind` 这一格，走秘书的
        meta patch）。

        为什么必须等 V 的签：B-2 的纪律是"自产、无出处、无签 ⇒ 从猜想注册"，
        升成 lemma 是签之后的那一步；没有签就改 kind 等于自报（那正是 B-2 堵的）。
        这里只在 `derive_grade(bits)` 已经到 `pre_theorem` / `theorem` 时才落。

        `example`（业主 2026-11-07，protocol 第六节）走的是同一条升档路：它是
        给人看的标签，落稿 / 收 V 签 / 按五元位算等级与 lemma 一字不差；差别只在
        G 收进正文时用 `Example` 环境（`papermapping.ENV_TITLES`）。B 这一侧不另开分支。
        """
        out = dict(got) if isinstance(got, dict) else got
        if not isinstance(out, dict) or not out.get("ok"):
            return out
        if str(origin or "") != "own_result" or str(kind or "").strip() not in (
                "", "theorem", "conjecture"):
            return out
        # 2026-11-10（T1）：调用方（`own.ingest_manuscript`）已经把稿头那一格从
        # `Secretary.extract_manuscript` 的读数里拿到了 ⇒ 不再为同一格读一次盘。
        declared = str(declared_kind or "").strip() or _declared_manuscript_kind(
            text=str(proof_manuscript or ""), root=str(self.store.root))
        if declared not in ("lemma", "theorem", "example"):
            return out
        sid = str(out.get("stmt_id") or "")
        if not sid:
            return out
        _decl_got = SL.by_id(self.store, stmt_id=sid)
        if not _decl_got["checked"]:
            _err = _decl_got.get("error") or {}
            raise RuntimeError(f"`statements` 读不出来（{_err.get('type') or '?'}: "
                               f"{_err.get('message') or _decl_got.get('reason') or '?'}）")
        row = _decl_got["row"] or {}
        if not row or str(row.get("kind") or "") == declared:
            return out
        try:
            grade = _EB.derive_grade(dict(row.get("bits") or {}),
                                     kind=str(row.get("kind") or ""))
        except Exception:  # noqa: BLE001 - 算不出来 ⇒ 不升（没判成不是"够格"）
            return out
        if grade not in ("pre_theorem", "theorem"):
            return out
        sec = self._statement_secretary()
        if sec is None:
            return out
        amended = dict(sec.amend_statement_meta(
            sid, {"kind": declared}, role="B") or {})
        out["kind_upgraded_from_manuscript"] = {
            "from": str(row.get("kind") or ""), "to": declared,
            "grade": grade, "basis": str(amended.get("reason") or ""),
            "amended": bool(amended.get("amended")),
        }
        if amended.get("amended") and amended.get("row"):
            out["row"] = dict(amended["row"])
        return out

    def _land_rewrite_manuscript(self, row: Mapping, *, proof_text: str,
                                 proof_manuscript: str) -> dict:
        """把这一版 B 的证明落进 `reports/b-proof-<命题号>.md`（就地重写那一节）。"""
        from .. import manuscriptform as _MF
        from .. import proofregistry as _PR

        sid = str(row.get("stmt_id") or "")
        proposition = str(row.get("statement_full") or "")
        # 标签只在真有的时候写：`- 标签：` 是登记元信息，不是骨架行（缺就不写）
        label = str(row.get("label") or "")
        rows: list[dict] = []
        template = str(proof_manuscript or "")
        if _is_manuscript_rel(template):
            rel = _norm_manuscript_rel(template)
            try:
                template = (Path(str(self.store.root)) / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                template = ""
        if template:
            section = _DS.parse_dependency_section(template)
            if section.get("present") and not section.get("refused"):
                rows = [dict(x) for x in (section.get("rows") or [])]
        got = _PR.register_or_rewrite(
            self.store.root, family=_MF.FAMILY_B, label=label,
            proposition=proposition, proof_text=str(proof_text or ""),
            dependency_rows=rows, statement_id=sid, kind=str(row.get("kind") or ""),
            template=template, gate=self._declared_kind_gate())
        out = dict(got)
        out["text"] = ""
        target = str(got.get("manuscript_path") or "")
        if got.get("ok") and target:
            try:
                out["text"] = (Path(str(self.store.root)) / target).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                out.update(ok=False, refused="manuscript_unreadable",
                           why=f"重写稿读不回来（{type(exc).__name__}: {exc}）")
        return out

    def _declared_kind_gate(self):
        """B 的重写没有形态闸（业主：「B侧收录不拦」）；登记那一刻不判形态。"""
        return None

    def _manuscript_deps_after_write(self, sec: Any, stmt_id: str,
                                     deps_groups: list[list[dict]]) -> dict:
        """正文写进在册那一行之后，把这份稿的依赖面也落下去（D7 的 A 那一半）。

        为什么需要它：上面那条"收方读稿登记"早退支路在"这一笔带了正文/清单"时让路
        （正文优先），而它原本承担的"把 F 手稿的 `## 依赖` 段落成边"不能因此丢掉 ——
        否则 B 一次把"正文 + 手稿"交齐时，正文进去了、依赖面反而没了（改前是依赖面进去
        了、正文没了；两种都是一半）。

        只在"这一笔真的带了已核过的依赖组"时动手（`deps_groups` 空 ⇒ 返回空字典，
        调用方原样不动）。别条命题的稿在调用处就被挡掉了，这里不会再判一次所有权。
        """
        if not deps_groups:
            return {}
        written = dict(sec.record_manuscript_dependency_face(
            stmt_id, deps_groups, note="b.register_statement:canonical") or {})
        return {"deps_written": int(written.get("deps_written") or 0),
                "deps_duplicates": [dict(x) for x in (written.get("duplicates") or [])],
                "checked": bool(written.get("checked")),
                "refused": str(written.get("refused") or ""),
                "reason": str(written.get("reason") or "")}

    @staticmethod
    def _carries_canonical_write(*, proof_text: Any, proofs_listed: Any,
                                 row: Mapping | None = None) -> bool:
        """这一笔要写进盘的东西，与在册那一行不一样吗（正文或证明清单）。

        它只有一个用途：决定要不要走"收方读稿登记：命题行不动"那条早退支路。判据是
        "有没有新的东西要写"，不是"有没有传这个字段"—— 两个理由：

        1. 传了也一样的时候必须走老路。D 的交付动作（`agent_d.write_report`）会把在册
           那一行的 `proof_text` / `proofs` 原样再交一遍（它交的是"这一份稿"），那一笔
           要干的是"读稿登记依赖面"，不是改正文。改前若按"传了字段"判，D 的每一次交付
           都会被带进 B 的完整闸门链（出处 / 自产要签 / 猜想起步），于是真机上活着的
           那条 D → B 通道被这一改堵死（`test_the_delivery_really_hands_the_manuscript_to_b`
           当场变红）。
        2. 变了的时候绝不能被吞掉。这正是真机 D7 的形态：截断登记 + 完整证明。

        所以逐字比：`proof_text` 与在册那一行的 `proof_text` 不同 ⇒ 有活要干；证明清单
        里任何一份的正文与在册那一份不同（或还没在册）⇒ 有活要干。两样都没有 ⇒ 这一笔
        只是"把稿交过来"，交给早退支路。

        为什么独立成一个方法：判据要能被打桩。反真空那条判据把它打成恒 False ⇒
        "改在册命题正文"这一笔又会被早退支路吞掉（于是判据 a 的绿来自这条判据，而不是
        某个顺手写的分支）。
        """
        now = dict(row or {})
        want = str(proof_text or "")
        have = str(now.get("proof_text") or "")
        if want.strip() and want != have:
            return True
        listed = {}
        for item in (now.get(_VR.PROOFS_KEY) or []):
            if isinstance(item, Mapping):
                try:
                    listed[int(item.get("proof_no") or 0)] = str(item.get("text") or "")
                except (TypeError, ValueError):
                    continue
        for entry in (proofs_listed or []):
            if not isinstance(entry, Mapping):
                continue
            try:
                no = int(entry.get("proof_no") or 0)
            except (TypeError, ValueError):
                continue
            known = have if no == 1 else listed.get(no)
            if known is None or str(known) != str(entry.get("text") or ""):
                return True
        return False

    def _existing_statement_for(self, full: str) -> dict | None:
        """按 `statement_full` 的规范化值找在册那一行（"是不是同一条"的唯一判据在
        `textutil.normalize` —— 与秘书查重同一处口径，这里不另写一份比法）。

        读不到 `statements` 时返回 None（走正常那一支）：那是"没查成"，而这一支
        只在"确认已经在册"时才提前返回 —— 查不成时不许假装它在册。
        """
        from .. import textutil as T

        if not T.normalize(str(full or "")):
            return None
        # 取数走查口的唯一取数口；读不到 ⇒ 走正常那一支（不猜它在册）。
        rows, problem, _error = SL.rows_of(self.store)
        if problem:
            return None
        hits = SL.duplicate_hits(rows, text=full)["hits"]
        return hits[0] if hits else None

    def _promote_formal_manuscript(self, *, stmt_id: str, rel: str, text: str,
                                   source: str = "") -> dict:
        """登记拿到号之后，把盘上那一份稿转成 `reports/f-proof-<号>.md`（能转才转）。

        业主 2026-11-04 的口径是「登记成功（拿到命题号）就改名，签另算」。改前这一步
        只发生在 F 自己的 proof 档里（`publish_manuscript`，改的是它手上那一份）；
        盘上已经存在的攻坚稿（真机 `notes/F-conj000000-proof.md`）没有任何代码把它
        变成正式稿 ⇒ `reports/f-proof-*.md` 0 份。本方法就是那个缺口的外壳：判据本体
        只有一处（`agent_f.manuscript.promote_manuscript`），这里只回答"这一份要不要转"。

        不转的三种：没有地址（正文是直递的，B 不知道它落在哪）、已经是按号命名的
        正式稿、B 自己的改写稿（`reports/b-proof-*`）。转正失败不许让整笔登记
        回滚：命题行已经落了，转正是它的后续读数（`promoted_manuscript` 里如实报）。
        """
        rel_now = _norm_manuscript_rel(rel)
        if not rel_now or not _should_promote_to_formal(rel_now):
            return {}
        try:
            from ..agent_f.manuscript import promote_manuscript as _promote

            got = dict(_promote(
                getattr(self.store, "root", ""), statement_id=str(stmt_id),
                source=rel_now, text=str(text or ""),
                # 计划名那份稿是同一份稿的旧名（`rename` 语义）⇒ 转正后删旧名；
                # `notes/…` 是作者的草稿 ⇒ 留着（删掉不可逆）。
                delete_source=rel_now.startswith(
                    f"{_DS.MANUSCRIPT_DIR}/{_DS.MANUSCRIPT_PLAN_PREFIX}")))
        except Exception as exc:  # noqa: BLE001 —— 转正失败要留读数，不带走登记
            return {"promoted": False, "source": rel_now,
                    "problem": {"kind": "promotion_failed", "stage": "call",
                                "why": f"{type(exc).__name__}: {exc}"}}
        got["manuscript_source"] = str(source or "")
        return got

    def _receive_carried_manuscript(self, row: Mapping[str, Any], *, deps_groups: Any,
                                    manuscript: Mapping[str, Any],
                                    manuscript_refs: Sequence[str],
                                    manuscript_source: str, manuscript_washed: bool,
                                    manuscript_wash: Mapping[str, Any],
                                    proofs: Sequence[Mapping[str, Any]],
                                    proof_text: str,
                                    deps_reading: Any,
                                    proof_vs_source: Mapping[str, Any] | None = None,
                                    proof_text_source: str = "") -> dict:
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
                                "deps_written": int(written.get("deps_written") or 0),
                                #: 2026-11-05（缺陷 1c）：回执那一行要两个数，秘书那一份
                                #: 逐条数过"其中命题→命题几条"，这里原样透传。
                                "deps_stmt_edges": int(written.get("deps_stmt_edges") or 0)})
        received_proofs = [{"proof_no": int(e.get("proof_no") or 0)}
                           for e in (proofs or []) if isinstance(e, Mapping)]
        note = ("收方读稿登记：命题行不动（这条命题已经在册），只把这份手稿的依赖段落成 "
                "`dependencies`（收方 = B，执行者 = 秘书）")
        if written.get("duplicates"):
            note += (f"；这一遍有 {len(written['duplicates'])} 条已经在表里（幂等，没有重复落）")
        if written.get("deps_written"):
            note += f"；这一遍新落 {int(written['deps_written'])} 条依赖边"
        #: 2026-11-05（缺陷 1c）：回执里那一行逐字「依赖边 N 条（其中命题→命题 M 条）」。
        if reading.get("deps_receipt"):
            note += f"；{reading['deps_receipt']}"
        return {"ok": True, "stmt_id": stmt_id, "new_row": False, "received_manuscript": True,
                "manuscript_source": manuscript_source,
                #: 这一支不写正文（命题行不动）⇒ 正文来源是空串或"在册原样"。要给调用方
                #: "为什么没写"的读数：`carries_write` 判的是"有没有与在册不同的东西"。
                "proof_text_source": str(proof_text_source or ""),
                "manuscript_washed": bool(manuscript_washed),
                "manuscript_wash": dict(manuscript_wash),
                #: 与来源是否逐字一致（信息格，不是门）：这一支不改正文，读数照给。
                "proof_vs_source": dict(proof_vs_source or {}),
                "deps_written": int(written.get("deps_written") or 0),
                #: 其中"命题→命题"几条（2026-11-05 缺陷 1c：两个数分开读）。
                "deps_stmt_edges": int(written.get("deps_stmt_edges") or 0),
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
            # 索引的构造只有一处（查口 `index_by_id`）；这里只要号集合。
            # 取数走唯一取数口（三态：读不成不是空表）。
            stmt_rows, problem, error = SL.rows_of(store)
            if problem:
                raise RuntimeError(f"{error.get('type') or '?'}: "
                                   f"{error.get('message') or problem}")
            known = set(SL.index_by_id(stmt_rows))
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
    #: 2026-11-02（业主：「F 侧产出证明而没有 V 签，这是 F 侧工作异常，B 不该处理（润色）无签证明」）：
    #: 收到的是 F 的手稿、而它没有 V 签 ⇒ 退回、不润色，要求 F 先拿 V 签（谁产出谁送审）。
    F_PROOF_UNSIGNED = "f_proof_needs_v_sign_first"

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

    def _land_b_manuscript(self, *, statement_id: str, statement_full: str,
                           proof_text: str, label: str = "", proof_no: int = 1,
                           source_manuscript: str = "") -> dict:
        """把 B 的改写正文落成 `reports/b-proof-<命题号>.md`（可签的载体）。

        ## 为什么在 B 的动作里落盘（而不是让 B 自己写文件）

        B 的工具面没有文件写口（只有 `table.*` / `manuscripts.read|list` 这类）。而业主
        2026-11-04 的裁定 A 甲要的是「B 的改写要有可签的载体」⇒ 作者（B）交内容、
        框架落盘、V 审、收方秘书落签。渲染与三态判据全在 `agentflow.bmanuscript`：
        这里只把读数原样带回（`written` / `preserved` / `signed` / `problem`），
        并把"稿在哪"给调用方（拒信里要点名，B 下一次要按那个路径送审）。

        一个字节都不写的那几档（目标已签且是另一份正文 / 目标读不出来）不许折成
        "写成了"：签另算不是毁签。

        ## 页头三格从来源稿读出来传全（2026-11-05 走查 D4）
        改前这里只传 `label`，于是运行期落下来的 b-稿缺 `- 计划：`、缺洗稿行、还多
        一行 `- 标签：` —— 与 f-族不是同一个骨架。页头那几格只活在来源稿里，所以
        这里先把来源稿的页头读出来（`bmanuscript.header_reading`），把
        `plan_id` / `sid` / `wash_actor`（以及 `wash_filled` / 标题 / `- 标签：`）
        原样交给 `land_rewrite` ⇒ 两族除前缀与角色名外逐字相同。
        没有来源稿（B 只给内联正文）⇒ 沿用调用方的 `label`（老形状）。
        """
        from .. import bmanuscript as _BM

        out: dict = {"ok": False, "checked": True, "path": "", "written": False,
                     "preserved": False, "signed": False, "text": "",
                     "sha256": "", "proof_no": 0, "preview": False,
                     "why": "", "problem": {}}
        root = getattr(getattr(self, "store", None), "root", "") or ""
        if not root:
            out.update(checked=False,
                       why="这一趟没有 store ⇒ B 的改写手稿没有落点（不是「没有改写」）")
            return out
        head = _BM.header_reading(source_manuscript)
        from_source = bool(head.get("checked"))
        # ---- 2026-11-07（业主裁定 ③）：已登记命题的证明重写就地动那一块 ---------
        #
        # 业主原话（逐字）：「B的重写一样（只是B不用再注册命题，命题拿已经登记的待优化的）」
        # 「F侧反复修改一个命题的证明时要直接动那个命题所指手稿的 proof 板块」。
        # 目标稿已经存在 ⇒ 这一笔是同一命题的下一版证明：只换 `## 证明`（按 cites
        # 重渲 `## 依赖`），`proof_no` 递增、正文 sha256 重算，不新落第二个文件
        # （不出现 `b-proof-000041-v2.md` 这类新名）。
        from .. import proofregistry as _PR

        _target = _PR.entry_relpath(family="B", statement_id=statement_id)
        if _target and (Path(str(root)) / _target).is_file():
            landed = self._land_rewrite_manuscript(
                {"stmt_id": statement_id, "statement_full": statement_full,
                 "label": label, "kind": ""},
                proof_text=proof_text, proof_manuscript=source_manuscript)
            if landed.get("ok"):
                from .. import vsigns as _VS_READ

                _rel = str(landed.get("manuscript_path") or _target)
                _text = str(landed.get("text") or "")
                if not _text:
                    try:
                        _text = (Path(str(root)) / _rel).read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        _text = ""
                _block = _VS_READ.manuscript_sign_reading(_text, manuscript_path=_rel)
                out.update(ok=True, path=_rel,
                           written=bool(landed.get("written")),
                           preserved=bool(landed.get("preserved")
                                          or not bool(landed.get("written"))),
                           signed=bool(_block.get("found") and _block.get("signed")),
                           text=_text, why="", problem={},
                           proof_no=int(landed.get("proof_no") or 0),
                           sha256=str(landed.get("sha256")
                                      or _PR.proof_sha(str(proof_text or ""))))
                return out
            out.update(ok=False, checked=bool(landed.get("checked", True)),
                       written=False, preserved=False, signed=False,
                       path=str(landed.get("manuscript_path") or _target),
                       why=str(landed.get("why") or ""),
                       sha256=_PR.proof_sha(str(proof_text or "")),
                       problem={"kind": str(landed.get("refused") or ""),
                                "why": str(landed.get("why") or "")})
            return out
        try:
            got = _BM.land_rewrite(
                root, statement_id=statement_id,
                statement_full=statement_full, proof_text=proof_text,
                # 页头跟着来源稿走：来源有 `- 标签：` 才写那一行；标题用来源稿标题那一段。
                # 没有来源稿 ⇒ 两份都用调用方的 label（老调用方的形状逐字不变）。
                label=(str(head.get("label") or "") if from_source else str(label or "")),
                title=(str(head.get("title") or "") if from_source else str(label or "")),
                proof_no=proof_no,
                source_manuscript=source_manuscript,
                plan_id=str(head.get("plan_id") or ""),
                sid=str(head.get("sid") or ""),
                wash_actor=str(head.get("wash_actor") or ""),
                wash_filled=str(head.get("wash_filled") or ""))
        except Exception as exc:  # noqa: BLE001 —— 落稿失败要如实说，不许静默
            out.update(checked=False,
                       why=(f"B 的改写手稿没落成（{type(exc).__name__}: {exc}）⇒ "
                            "这一份没有可签的载体"))
            return out
        out.update({k: got.get(k) for k in ("path", "written", "preserved",
                                            "signed", "text", "why")})
        out["problem"] = dict(got.get("problem") or {})
        out["ok"] = bool(got.get("ok"))
        # 签尺（`proofregistry.proof_sha`）：这一版将来被 V 签时对拍的就是它。
        out["sha256"] = _PR.proof_sha(str(proof_text or ""))
        out["proof_no"] = int(got.get("proof_no") or proof_no or 0)
        # ---- 2026-11-07（A1）：第一份 b-稿也要成为「登记条目」 ---------------------
        #
        # `ack`：`bmanuscript.land_rewrite` 只落骨架（三节 + `- 证明号：`），没有
        # `- 正文sha：` / `- 命题指纹：` / `- 版本：`。于是下一轮再改写时，
        # `proofregistry` 读到的不是登记条目，会把同一命题重新登记一次
        # （`proof_no` 回到 1、版本历史从 1 重来）—— 这正是 A1 那条真缺陷在 B 侧的同一形态。
        # 骨架落成之后立刻过一遍登记入口（正文逐字不变，只补头部登记元信息），
        # 于是"同一份命题的后续每一版证明"都落成 `mode=rewritten`。
        if out.get("ok") and str(out.get("path") or ""):
            stamped = self._land_rewrite_manuscript(
                {"stmt_id": statement_id, "statement_full": statement_full,
                 "label": (str(head.get("label") or "") if from_source
                           else str(label or "")), "kind": ""},
                proof_text=proof_text, proof_manuscript=str(out.get("path") or ""))
            if stamped.get("ok"):
                _rel = str(stamped.get("manuscript_path") or out.get("path") or "")
                try:
                    _text = (Path(str(root)) / _rel).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    _text = str(out.get("text") or "")
                from .. import vsigns as _VS_STAMP

                _block = _VS_STAMP.manuscript_sign_reading(_text, manuscript_path=_rel)
                out.update(path=_rel, text=_text,
                           preserved=bool(stamped.get("preserved")),
                           signed=bool(_block.get("found") and _block.get("signed")),
                           proof_no=int(stamped.get("proof_no") or proof_no or 0),
                           sha256=str(stamped.get("sha256")
                                      or _PR.proof_sha(str(proof_text or ""))))
            else:
                out.update(ok=False,
                           why=("b-稿骨架写成了，而登记元信息没补上（"
                                + str(stamped.get("why") or "未知原因")
                                + "）⇒ 下一轮会把同一命题重新登记一次"))
        return out


    # ------------------------------------------------------------------ T1 收录
    #
    # 业主 2026-11-09 的目标形态（逐字）：「自动录入是 B 秘书的一个工具，需 B 秘书指定
    # 录入位置和录入格后，从稿中提取内容录入」。落成三个词：
    #   · 位置 = `target_stmt_id`（录到哪一条命题）+ `proof_no`（这一行的第几份证明）；
    #   · 格   = `cells`（闭集：statement_full / proof_text / dependencies / kind /
    #            numeric_evidence），派生列（label / bits / proof_no / sha …）永远不许指定；
    #   · 提取 = `Secretary.extract_manuscript` → `manuscriptintake.extract_cells`
    #            （B 本体不读稿）；回填仍是既有三个写口，不新开第四套。
    #
    # 两条硬不变量（设计 §2.4）在 `_ingest_invariant_problem` 一处机器可核：
    #   I1 `diff.filled_not_requested == []`（派生列不算"没请求就写"）；
    #   I2 每个 requested 格都有 outcome + reason。

    @staticmethod
    def _ingest_empty_envelope(rel: str, mode: str) -> dict:
        """`own.ingest_manuscript` 的返回骨架（键固定；失败路径也带同一组键）。"""
        return {
            "ok": False, "mode": str(mode or "apply"), "why": "",
            "manuscript": {"path": rel, "family": "", "tier": "",
                           "manuscript_id": "", "proof_no": 0, "sha256": "",
                           "proof_sha256": "", "proof_state": "",
                           "sign": {"found": False, "signed": False, "state": ""}},
            "target": {"stmt_id": "", "before": {}},
            "requested_cells": [], "cells": {},
            "diff": {"requested_not_filled": [], "filled_not_requested": []},
            "derived_write": [], "write": {"statements": False,
                                           "dependencies": False, "written": False},
            "refused": "", "reason": "",
        }

    @staticmethod
    def _ingest_invariant_problem(out: Mapping) -> str:
        """I1 / I2 的机器判据（空串 = 两条都成立）。

        为什么是一个独立函数：判据要能被单独喂一份"错读数"来证明它不是恒真
        （`tests/test_t1_ingest_manuscript_specifies_position_and_cells.py` 的 c 那条
        构造"填了没请求"）。工具自己的返回也必须过这一关 —— 把它当装饰的写法会让
        "请求格 vs 实填格"的对拍变成一句注释。
        """
        cells = dict(out.get("cells") or {})
        derived = {str(x) for x in (out.get("derived_write") or [])}
        filled = [name for name, one in cells.items()
                  if isinstance(one, Mapping)
                  and bool(one.get("requested") is False)
                  and str(one.get("outcome") or "") in ("filled", "unchanged")
                  and name not in derived]
        declared = [str(x) for x in ((out.get("diff") or {}).get("filled_not_requested") or [])]
        if filled or declared:
            return ("I1 不成立：这些格没有请求却被写了 " + "、".join(sorted(set(filled) | set(declared)))
                    + "（除派生列外，写口只许碰调用方点名的格）")
        for name in out.get("requested_cells") or []:
            one = cells.get(str(name))
            if not isinstance(one, Mapping):
                return f"I2 不成立：请求了 {name!r} 却没有任何 outcome"
            outcome = str(one.get("outcome") or "")
            if outcome not in ("filled", "unchanged", "refused", "kept", "not_applicable"):
                return f"I2 不成立：{name!r} 的 outcome 是 {outcome!r}"
            if outcome in ("refused", "kept", "not_applicable") and not str(
                    one.get("reason") or "").strip():
                return f"I2 不成立：{name!r} 是 {outcome} 却没有 reason"
        return ""

    def _ingest_fail(self, out: dict, code: str, why: str, **extra: Any) -> dict:
        """受控拒：保留已经读到的读数，只把 `ok/refused/reason` 翻掉。"""
        out = dict(out)
        out.update(ok=False, refused=str(code), reason=str(why), why=str(why))
        out.update(extra)
        return out

    @staticmethod
    def _ingest_requested_cells(cells: Any, mode: str) -> tuple[list[str], str, str]:
        """校验 `cells` 闭集 ⇒ `(请求格, 受控码, 人话)`（码空 = 过关）。"""
        from .. import manuscriptintake as _MI

        if isinstance(cells, (str, bytes)) or cells is None:
            return [], "bad_cells", '`cells` 要是格的序列（例如 ["proof_text"]），不是单个字符串'
        requested: list[str] = []
        for raw in cells:
            name = str(raw).strip()
            if name in DERIVED_COLUMNS:
                return [], "derived_cell_not_requestable", (
                    f"`{name}` 是派生列，调用方永远不能指定（设计 §2.5）："
                    "label 由秘书洗、evidence_kind / 等级由签现算、"
                    "bits / proof_no / proof_sha256 / proof_authors / stmt_id 是写口回执。"
                    f"可请求的格只有 {_MI.INGEST_CELLS}")
            if name not in _MI.INGEST_CELLS:
                return ([], "unknown_ingest_cell",
                        f"未知的收录格 {raw!r}：只有 {_MI.INGEST_CELLS}")
            if name not in requested:
                requested.append(name)
        if not requested and str(mode) != "register":
            return [], "bad_cells", "`cells` 不能是空的（至少请求一格）"
        return requested, "", ""

    @staticmethod
    def _ingest_proof_no(reading: Mapping, proof_no: Any) -> tuple[int, str, str]:
        """稿名与参数对证明号的读数 ⇒ `(第几份, 受控码, 人话)`。"""
        name_no = int(reading.get("name_proof_no") or 0)
        given_no: int | None = None
        if proof_no not in (None, ""):
            try:
                given_no = int(proof_no)
            except (TypeError, ValueError):
                given_no = 0
            if given_no < 1:
                return 0, "bad_proof_no", f"`proof_no` 要是 >=1 的整数（收到 {proof_no!r}）"
        if given_no is not None and name_no and given_no != name_no:
            return 0, "proof_no_mismatch", (
                f"稿名说这是 #p{name_no}，而 `proof_no` 参数说 #p{given_no} ⇒ 整笔不写"
                "（以哪一个为准由调用方先说清；工具不会自己挑一个）")
        return int(given_no or name_no or 1), "", ""

    def _ingest_target_row(self, out: dict, target: str,
                           if_match: str) -> tuple[dict | None, str, str]:
        """读在册那一行（apply/preview 的位置落点）并填 `out.target` 的 before 读数。"""
        got = SL.by_id(self.store, stmt_id=target)
        if not got["checked"]:
            err = got.get("error") or {}
            return None, "ledger_unreadable", (
                f"`statements` 读不出来（{err.get('type') or '?'}: "
                f"{err.get('message') or '?'}）⇒ 判不了这一笔有没有落点（读不到 ≠ 不在册）")
        row = dict(got["row"]) if got["found"] else None
        if row is None:
            return None, "statement_missing", (
                f"`statements` 里没有 stmt:{target} ⇒ 本工具不替它发号："
                "先 `own.register_statement` 拿号，再按位置回填")
        out["target"].update({
            "stmt_id": target,
            "before": {
                "proof_text_sha256": str(row.get("proof_sha256") or ""),
                "proof_no": int(row.get("proof_no") or 0),
                "kind": str(row.get("kind") or ""),
            },
        })
        if str(if_match or "").strip():
            current = str(row.get("proof_sha256") or "")
            if not current and str(row.get("proof_text") or ""):
                current = _PR.proof_sha(str(row.get("proof_text") or ""))
            if current != str(if_match).strip().lower():
                return None, "stale_target", (
                    f"`if_match_proof_sha256` 与盘上不符（盘上现在 "
                    f"{current[:12] + '…' if current else '没有正文'}）⇒ 不覆盖")
        return row, "", ""

    @staticmethod
    def _ingest_plan_cells(plan: Mapping, requested: Sequence[str]) -> dict[str, dict]:
        """把 `plan_cells` 的返回铺成"每个格都有 outcome"的公开读数。"""
        from .. import manuscriptintake as _MI

        cells_out: dict[str, dict] = {}
        for cell in _MI.INGEST_CELLS:
            if cell in (plan.get("cells") or {}):
                one = dict(plan["cells"][cell])
                one["requested"] = cell in requested
                cells_out[cell] = one
            elif cell in requested:
                cells_out[cell] = {
                    "requested": True, "writable": False,
                    "outcome": "refused", "code": "cell_not_extracted",
                    "reason": "这一格没有提取读数（契约：请求的每一格都要有 outcome）",
                    "source": {"section": _MI.SECTION_BY_CELL[cell], "lines": [], "sha": ""},
                }
            else:
                cells_out[cell] = {
                    "requested": False, "writable": False,
                    "outcome": "not_requested",
                    "source": {"section": _MI.SECTION_BY_CELL[cell], "lines": [], "sha": ""},
                }
        return cells_out

    @staticmethod
    def _ingest_family_reading(rel: str, mode: str, out: dict) -> tuple[str, str, str, str]:
        """判族 / 目录并把读数写进 `out` ⇒ `(族, tier, 受控码, 人话)`。"""
        from .. import manuscriptfamily as _MFAM

        shape = _MFAM.classify_manuscript(rel)
        tier = str(shape.get("tier") or "")
        family = str(shape.get("family") or "")
        out["manuscript"].update({
            "path": rel, "family": family, "tier": tier,
            "manuscript_id": str(shape.get("manuscript_id") or ""),
            "proof_no": int(shape.get("proof_no") or 0),
            "canonical": str(shape.get("canonical") or ""),
        })
        if tier == _MFAM.TIER_BAD:
            return family, tier, _MFAM.CODE_BAD, (
                f"手稿名 {rel!r} 认不出号（{shape.get('why')}）⇒ 整笔不读不写")
        if tier == _MFAM.TIER_UNRECOGNIZED:
            return family, tier, _MFAM.CODE_NOT_MANUSCRIPT, (
                f"`{rel}` 不在手稿族里（只收 `reports/` 下的 "
                "`f-proof-*` / `b-proof-*` / `e-proof-*` / `e-num-*`）")
        if tier == _MFAM.TIER_LEGACY and str(mode) != "preview":
            return family, tier, "manuscript_legacy_name", (
                f"`{rel}` 是历史档（{shape.get('code')}）⇒ 可列出、可 preview，"
                f"不可签、不可收录；规范名是 {shape.get('canonical') or '（拼不出）'}")
        return family, tier, "", ""


    @staticmethod
    def _ingest_diff(out: Mapping, requested: Sequence[str]) -> dict:
        """`diff` 的单一算点：请求格 vs 实填格（不信任任何一方的自报）。"""
        cells = dict(out.get("cells") or {})
        filled = sorted(name for name, one in cells.items()
                        if isinstance(one, Mapping)
                        and bool(one.get("requested"))
                        and str(one.get("outcome") or "") in ("filled", "unchanged"))
        not_filled = sorted(name for name in requested
                            if str((cells.get(name) or {}).get("outcome") or "")
                            not in ("filled", "unchanged"))
        stray = sorted(name for name, one in cells.items()
                       if isinstance(one, Mapping)
                       and not bool(one.get("requested"))
                       and str(one.get("outcome") or "") in ("filled", "unchanged"))
        _ = filled
        return {"requested_not_filled": not_filled, "filled_not_requested": stray}

    @staticmethod
    def _ingest_legacy_cells(reading: Mapping, requested: Sequence[str]) -> dict:
        """legacy 档的 preview 读数：值给出来，但每格都是"不可收录"（不写）。"""
        got = dict(reading.get("cells") or {})
        out: dict[str, dict] = {}
        for cell, one in got.items():
            base = dict(one)
            base.update(requested=True, writable=False,
                        outcome="not_applicable",
                        code="manuscript_legacy_name",
                        reason="历史档：可列出、可 preview，不可签、不可收录；"
                               "要收录先落成规范名")
            out[cell] = base
        for cell in requested:
            if cell not in out:
                out[cell] = {"requested": True, "writable": False,
                             "outcome": "not_applicable",
                             "code": "manuscript_legacy_name",
                             "reason": "历史档：这一格没有提取读数"}
        return out

    def _ingest_register(self, *, reading: Mapping, requested: Sequence[str],
                         out: dict, family: str, path: str,
                         provenance: Any = None) -> dict:
        """`mode=register`：把这份稿登记成新命题（继承 pointer 那条路的全部闸）。"""
        from .. import manuscriptfamily as _MFAM
        from .. import manuscriptintake as _MI

        got, origin, kind = self._register_pointer_manuscript(
            path, provenance=provenance, reading=reading)
        if not isinstance(got, dict):
            return self._ingest_fail(out, "registration_refused",
                                     "登记没有返回读数（不假装写成）")
        if not got.get("ok"):
            code = str(got.get("kind") or got.get("refused")
                       or "registration_refused")
            why = str(got.get("error") or got.get("reason")
                      or got.get("why") or "登记被拒 ⇒ 这一笔不写")
            out = self._ingest_fail(out, code, why)
            out["cells"] = {
                str(cell): {"requested": True, "writable": False,
                            "outcome": "refused", "code": code, "reason": why,
                            "source": {"section": _MI.SECTION_BY_CELL.get(str(cell), ""),
                                       "lines": [], "sha": ""}}
                for cell in requested}
            out["requested_cells"] = list(requested)
            out["diff"] = {"requested_not_filled": list(requested),
                           "filled_not_requested": []}
            return out
        # 签后升档与 pointer 老路同一条判据；稿头那一格用秘书给的那份读数（不再读盘）。
        got = self._apply_declared_manuscript_kind(
            got, statement_full="", origin=origin, kind=kind, proof_manuscript=path,
            declared_kind=str(reading.get("declared_kind") or ""))
        cells_read = dict(reading.get("cells") or {})
        cells_out: dict[str, dict] = {}
        for cell in _MI.INGEST_CELLS:
            if cell not in requested:
                cells_out[cell] = {"requested": False, "writable": False,
                                   "outcome": "not_requested",
                                   "source": {"section": _MI.SECTION_BY_CELL[cell],
                                              "lines": [], "sha": ""}}
                continue
            source = dict((cells_read.get(cell) or {}).get("source") or {})
            if cell == "numeric_evidence" and family != "e-num":
                outcome, note = "not_applicable", "这一族没有数值结果格"
            elif cell == "proof_text" and family == "e-num":
                outcome, note = "not_applicable", "普通数值档 `proof_text` 按业主口径留空"
            elif cell == "dependencies":
                dep = cells_read.get("dependencies") or {}
                outcome = ("filled" if dep.get("outcome") == _MI.EXTRACT_PRESENT
                           and (dep.get("rows") or [])
                           else "not_applicable")
                note = ("依赖段四列照写" if outcome == "filled"
                        else "稿里没有依赖行（自足证明合法）")
            else:
                outcome = "filled"
                note = "登记这一笔按稿回填"
            cells_out[cell] = {"requested": True, "writable": outcome == "filled",
                               "outcome": outcome, "reason": note,
                               "source": source,
                               "value": (cells_read.get(cell) or {}).get("value")}
        out.update(requested_cells=list(requested), cells=cells_out,
                   derived_write=list(_MFAM.derived_cells(family)),
                   ok=True, refused="", reason="")
        out["target"] = {"stmt_id": str(got.get("stmt_id") or ""), "before": {}}
        out["diff"] = self._ingest_diff(out, requested)
        problem = self._ingest_invariant_problem(out)
        if problem:
            return self._ingest_fail(out, "ingest_invariant_violated", problem)
        out["write"] = {"statements": True, "dependencies": False,
                        "written": True,
                        "sink": "record_statement（登记新命题）"}
        out["register"] = {
            "stmt_id": str(got.get("stmt_id") or ""),
            "new_row": bool(got.get("new_row", got.get("created"))),
            "origin": str(origin), "kind": str(kind),
            "pointer": dict(got.get("pointer") or {}),
            "kind_upgraded_from_manuscript": got.get(
                "kind_upgraded_from_manuscript") or {},
        }
        # 登记结果的全部老读数（ok / stmt_id / row / pointer / label_washed …）原样带回：
        # `own.register_statement` 的 pointer 支把它直接返回给模型与既有判据。
        result = dict(got)
        result.update(out)
        result["ok"] = True
        return result

    def _ingest_apply_proof(self, cells: dict, row: Mapping, want_no: int,
                            target: str) -> dict:
        """写 `proof_text` 那一格（签闸 → `_attach_proofs`），就地把回执写回 `cells`。"""
        text = str((cells.get("proof_text") or {}).get("value") or "")
        gate = self._unsigned_proof_gate(
            origin=str(row.get("origin") or ""),
            lit_id=str(row.get("source_lit_id") or ""),
            proof_text=(text if want_no == 1 else ""),
            proofs_listed=([{"proof_no": want_no, "text": text}]
                           if want_no >= 2 else None),
            row=row, v_sign={}, store=self.store, proof_no=want_no)
        if gate.get("refused"):
            return {"written": False, "code": str(gate["refused"]),
                    "why": str(gate.get("reason") or "")}
        attach = self._attach_proofs(
            target,
            entries=([{"proof_no": want_no, "text": text}]
                     if want_no >= 2 else []),
            canonical=(text if want_no == 1 else ""), proof_no=want_no)
        if attach.get("refused"):
            return {"written": False, "code": str(attach["refused"]),
                    "why": str(attach.get("reason") or "")}
        cells["proof_text"] = {**cells["proof_text"],
                               "written": bool(attach.get("written")),
                               "attached": list(attach.get("attached") or []),
                               "already": list(attach.get("already") or [])}
        return {"written": bool(attach.get("written")), "code": "", "why": ""}

    def _ingest_apply(self, *, reading: Mapping, row: Mapping, plan: Mapping,
                      out: dict, requested: Sequence[str], family: str,
                      want_no: int, target: str, path: str) -> dict:
        """`mode=apply`：逐格回填（先 statements，再 dependencies；部分写如实回执）。

        ## 为什么刻意不跑同一性判定（业主 2026-11-09 的形态）

        `target_stmt_id` 就是"录到哪一条"。`mode=apply` 再跑一次
        `adjudicate_proposition`，它可能把这一笔判成"与另一条在册命题同一条"，
        于是写口把正文并到调用方没点名的行上 —— 这正是 T1 要修的缺陷。
        判定只在 `mode=register`（决定"这是不是新命题"）那一趟跑，且只跑一次。
        """
        from .. import manuscriptintake as _MI

        cells = dict(out.get("cells") or {})
        # fail-closed：任何一格 refused ⇒ 整笔不写（preview 式返回，理由原样）。
        if not plan.get("ok"):
            out["write"] = {"statements": False, "dependencies": False,
                            "written": False,
                            "sink": "refused：一格被拒，整笔不写（fail-closed）"}
            return out
        sec = self._statement_secretary()
        if sec is None:
            return self._ingest_fail(
                out, "secretary_unavailable",
                "这一趟没有秘书 ⇒ 台账写不了（写库仍只走既有写口）")
        statements_written = False
        deps_written = False
        written_cells: list[str] = []

        def _cell_refused(cell: str, code: str, why: str) -> dict:
            one = dict(cells.get(cell) or {})
            one.update(requested=True, writable=False, outcome="refused",
                       code=str(code), reason=str(why))
            cells[cell] = one
            out["cells"] = cells
            out["diff"] = self._ingest_diff(out, requested)
            return self._ingest_fail(out, code, why,
                                     write={"statements": statements_written,
                                            "dependencies": deps_written,
                                            "written": bool(statements_written or deps_written),
                                            "sink": "apply：按格回填（部分写如实回执）"})

        # ---- 1) proof_text（签闸不松；#pN 逐份认签，不许借 #p1 的光）
        if str((cells.get("proof_text") or {}).get("outcome") or "") == "filled":
            got = self._ingest_apply_proof(cells, row, want_no, target)
            if got["code"]:
                return _cell_refused("proof_text", got["code"], got["why"])
            if got["written"]:
                statements_written = True
                written_cells.append("proof_text")

        # ---- 2) numeric_evidence（只 e-num；凭据仍从 experiments 那一行读）
        if str((cells.get("numeric_evidence") or {}).get("outcome") or "") == "filled":
            value = dict(cells["numeric_evidence"].get("value") or {})
            eid = str(value.get("experiment_id") or "")
            try:
                experiments = [dict(x) for x in self.store.rows("experiments")]
            except Exception as exc:  # noqa: BLE001 —— 读不到不许当成"没有实验"
                return _cell_refused(
                    "numeric_evidence", "experiment_ledger_unreadable",
                    f"`experiments` 读不出来（{type(exc).__name__}: {exc}）⇒ 凭据核不了")
            exp = next((x for x in experiments
                        if str(x.get("experiment_id") or "") == eid), None)
            if exp is None:
                return _cell_refused(
                    "numeric_evidence", "numeric_experiment_missing",
                    f"稿头的实验号 exp:{eid or '?'} 在 `experiments` 里找不到 ⇒ "
                    "普通数值档的凭据必须指到一条真的实验行")
            green = {
                "path": path, "experiment_id": eid,
                "code_path": str(exp.get("code_path") or ""),
                "method": str(value.get("method") or exp.get("method") or ""),
                "result": str(value.get("result") or exp.get("result") or ""),
                "observations": dict(exp.get("observations") or {}),
                "params": dict(exp.get("params") or {}),
                "counterexample": exp.get("counterexample"),
                "experiment_row": exp,
            }
            numeric = self._update_numeric_evidence(row=row, green=green, same={})
            if not numeric.get("ok"):
                return _cell_refused(
                    "numeric_evidence",
                    str(numeric.get("kind") or "numeric_evidence_write_failed"),
                    str(numeric.get("error") or numeric.get("reason") or ""))
            wrote = bool((numeric.get("updated_statement") or {}).get("written"))
            if wrote:
                statements_written = True
                written_cells.append("numeric_evidence")
            cells["numeric_evidence"] = {**cells["numeric_evidence"], "written": wrote}

        # ---- 3) kind（只升不降；升要签 —— 判据仍是 `_apply_declared_manuscript_kind`）
        if str((cells.get("kind") or {}).get("outcome") or "") == "filled":
            upgraded = self._apply_declared_manuscript_kind(
                {"ok": True, "stmt_id": target}, statement_full="",
                origin=str(row.get("origin") or ""), kind=str(row.get("kind") or ""),
                proof_manuscript=path,
                declared_kind=str(reading.get("declared_kind") or ""))
            one = dict(upgraded.get("kind_upgraded_from_manuscript") or {})
            if one.get("amended"):
                statements_written = True
                written_cells.append("kind")
                cells["kind"] = {**cells["kind"], "outcome": "filled",
                                 "written": True, "upgrade": one}
            else:
                cells["kind"] = {**cells["kind"], "outcome": "kept",
                                 "writable": False,
                                 "code": "kind_not_upgraded_without_sign",
                                 "reason": ("台账那一档不满足升档条件（签未到位 / "
                                            "稿头没声明更强的档）⇒ 这一格不写")}

        # ---- 4) dependencies（集合语义：追加 + 去重；永不删）
        if str((cells.get("dependencies") or {}).get("outcome") or "") == "filled":
            from .. import depsection as _DS

            one = dict(cells["dependencies"])
            rows = [dict(x) for x in (one.get("value") or [])]
            refs = [str(x) for x in (one.get("refs") or [])]
            stmt_rows, problem, error = SL.rows_of(self.store)
            if problem:
                return _cell_refused(
                    "dependencies", "ledger_unreadable",
                    f"`statements` 读不出来（{error.get('type') or '?'}: "
                    f"{error.get('message') or problem}）⇒ 判不了这些依赖能不能引")
            gate = _DS.gate_rows(rows, stmt_rows)
            if not gate.get("ok"):
                return _cell_refused("dependencies",
                                     str(gate.get("refused") or _DS.REFUSED_LEVEL_TOO_LOW),
                                     str(gate.get("reason") or ""))
            index = SL.index_by_id(stmt_rows)
            pool = _DS.citable_pool(stmt_rows)
            for ref in refs:
                if ref in pool:
                    continue
                got = _DS.uncitable_statement_finding(
                    ref, list(index.values()), where="证明正文")
                return _cell_refused(
                    "dependencies",
                    str((got or {}).get("kind") or _DS.REFUSED_UNKNOWN_SOURCE),
                    str((got or {}).get("detail")
                        or f"证明正文引了 stmt:{ref}，而它不在可引池里"))
            if not rows and refs:
                return _cell_refused(
                    "dependencies", _DS.REFUSED_TABLE_DISAGREES,
                    ("`## 依赖` 表是空的，而证明正文引了 "
                     + "、".join(f"stmt:{x}" for x in refs)
                     + " ⇒ 表与正文说的不是同一件事"))
            kinds = {str(x.get("stmt_id") or ""): _DS.dep_kind_of(str(x.get("kind") or ""))
                     for x in stmt_rows}
            groups = _DS.deps_groups(rows, kinds)
            written = dict(sec.record_manuscript_dependency_face(
                target, groups, proof_no=want_no,
                note=f"own.ingest_manuscript:dependencies:{target}") or {})
            if not written.get("checked"):
                return _cell_refused(
                    "dependencies",
                    str(written.get("refused") or "dependency_face_not_written"),
                    str(written.get("reason") or ""))
            if int(written.get("deps_written") or 0):
                deps_written = True
                written_cells.append("dependencies")
            cells["dependencies"] = {
                **one, "written": bool(int(written.get("deps_written") or 0)),
                "rows_written": int(written.get("deps_written") or 0),
                "duplicates": len(written.get("duplicates") or []),
                "path_groups": int(written.get("path_groups") or 0),
            }

        # ---- 5) statement_full：在册行只读（plan 不会给 filled；这里兜底并说清）
        if str((cells.get("statement_full") or {}).get("outcome") or "") == "filled":
            return _cell_refused(
                "statement_full", "cell_not_writable_on_existing_row",
                "在册行的命题正文只读：要改命题请重新走 `own.register_statement`"
                "（同一性判定/合并只在那条路上跑）")

        out["cells"] = cells
        out["diff"] = self._ingest_diff(out, requested)
        problem = self._ingest_invariant_problem(out)
        if problem:
            return self._ingest_fail(out, "ingest_invariant_violated", problem,
                                     write={"statements": statements_written,
                                            "dependencies": deps_written,
                                            "written": bool(statements_written or deps_written)})
        out["ok"] = True
        out["write"] = {"statements": statements_written,
                        "dependencies": deps_written,
                        "written": bool(statements_written or deps_written),
                        "cells": written_cells,
                        "sink": "land_statement:attach_proofs / amend_statement_meta / "
                                "record_manuscript_dependency_face"}
        out["reason"] = str(out.get("reason") or "逐格回填完成")
        return out

    def _preview_b_manuscript(self, *, statement_id: str, statement_full: str,
                              proof_text: str, label: str = "",
                              proof_no: int = 1,
                              source_manuscript: str = "") -> dict:
        """这一笔将要落的 B 手稿（纯渲染；一个字节都不写）。

        为什么需要它：D1 把落稿挪到闸后，而依赖面闸 / 自产签闸仍要看见"这一笔将要
        落的稿"（`## 依赖` 表 / `## 证明` 正文 / 页头）。拿"没有稿"去判会让依赖面闸
        静默跳过（= 放宽）。所以先算一份内存预览喂给闸；真落稿在无签闸之后。

        与 `_land_b_manuscript` 用同一套渲染（`bmanuscript.render`），差别只在：
        不 `commit`、不搬签、不补登记元信息；`path` 只是落点（`preview=True`）。
        """
        from .. import bmanuscript as _BM
        from .. import proofregistry as _PR

        head = _BM.header_reading(source_manuscript)
        from_source = bool(head.get("checked"))
        rows: list[dict] = []
        source = str(source_manuscript or "")
        if source.strip():
            section = _DS.parse_dependency_section(source)
            if section.get("present") and not section.get("refused"):
                rows = [dict(x) for x in (section.get("rows") or [])]
        text = _BM.render(
            statement_full=statement_full, proof_text=str(proof_text or ""),
            statement_id=statement_id,
            label=(str(head.get("label") or "") if from_source
                   else str(label or "")),
            title=(str(head.get("title") or "") if from_source
                   else str(label or "")),
            proof_no=proof_no,
            dependency_section=_DS.render_dependency_section(rows),
            plan_id=str(head.get("plan_id") or ""),
            sid=str(head.get("sid") or ""),
            wash_actor=str(head.get("wash_actor") or ""),
            wash_filled=str(head.get("wash_filled") or ""))
        return {"preview": True, "checked": True, "written": False,
                "preserved": False, "signed": False,
                "path": _PR.entry_relpath(family="B", statement_id=statement_id),
                "text": text,
                "sha256": _PR.proof_sha(str(proof_text or "")),
                "proof_no": int(proof_no or 0),
                "why": "内存预览：闸判完、过了才落盘", "problem": {}}

    def _v_signature_for(self, *, statement_full: str, proof_text: str,
                         manuscript_text: str = "",
                         manuscript_path: str = "") -> dict:
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
                     #: 这一版正文在 V 的台账里"欠什么"：`signed` / `stale`（改过）/
                     #: `unsigned`（没签过）/ `rejected`（判过有毛病）/ `holding`
                     #: （次数没到）/ `unreadable`（没查成）。拒信按它分句。
                     "state": "", "streak": 0, "need": 0,
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
        # 取数走查口的唯一取数口；读不到要如实说，不许当成通过。
        rows, problem, error = SL.rows_of(store)
        if problem:
            out["why"] = (f"没查成：statements 读不出来（{error.get('type') or '?'}: "
                          f"{error.get('message') or problem}）"
                          "⇒ 判不了这一条有没有 V 的签")
            return out
        sha = _PR.proof_sha(want)
        out["proof_sha256"] = sha
        # ---- 2026-11-02（业主：「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或
        #      命题收录时读到」）：手稿里那一行签块是最先看的一处 ----
        #
        # 为什么放在"按正文认台账里同一条命题"之前：第一次登记时册上根本没有同文的行
        # （`same` 为空），而业主要的那条路正是"签先在手稿里、B 收录时读到" ——
        # 放到后面就永远读不到第一次登记。判据不在这一层重写：读块、比正文 sha、
        # 看连续次数都在 `vsigns.manuscript_sign_standing`（与 pending / 侧文件同一把尺）。
        # 只有 `signed` 这一档在这里结案；其余档（rejected / stale / unsigned /
        # 读不成形）照旧落到下面的台账与 pending 两条来源 —— 不在这里提前下"没签"的结论。
        try:
            from agentflow import vsigns as _VS_BLOCK

            block = _VS_BLOCK.manuscript_sign_standing(
                str(manuscript_text or ""), proof_sha=sha,
                manuscript_path=str(manuscript_path or ""))
        except Exception as exc:  # noqa: BLE001 —— 块读不动 ⇒ 这一格没查成，不是"没有签"
            block = {"state": "", "checked": False,
                     "why": f"手稿签块读不出来（{type(exc).__name__}: {exc}）"}
        if str(block.get("state") or "") == "signed":
            out.update(signed=True, state="signed",
                       verification_id=str(block.get("ledger") or ""),
                       why=(f"手稿里的签块：{block.get('why')} —— B 收录时从稿上读到"
                            "（业主 2026-11-01：「随 B 侧将手稿中的定理或命题收录时读到」）"))
            return out
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
            # ---- 这一版正文"欠什么"：按它的 sha 在逐条读数里找同一份的那一格。
            #
            # 改前这里只找 `reviewed=True` 且 sha 相符的那一签；找不到就一律写成
            # "没有盖住这一份正文的「成立」签" —— 四种欠账（改过 / 没签过 / 判过有毛病 /
            # 次数没到）被折成同一句话，而它们的下一步完全不同（业主 2026-11-01：
            # 「其它拒都最好要回复一句原因，一句建议」）。所以这里把同一份的那一格
            # 原样带出来（`state`），拒信由 `_needs_v_reason` 按它分句。
            matched: dict = {}
            other: dict = {}
            for item in reading.get("proofs") or []:
                if str(item.get("proof_sha256") or "") != sha:
                    if bool(item.get("reviewed")) and not other:
                        other = dict(item)
                    continue
                matched = dict(item)
                if bool(item.get("reviewed")):
                    out.update(signed=True, stmt_id=sid, state="signed",
                               verification_id=str(item.get("verification_id") or ""),
                               why=(f"{item.get('verification_id')} 签「成立」、且 proof_sha256 "
                                    f"与这一份正文相符（verifications/{sid}.jsonl）"))
                    return out
            if matched:
                out.update(state=str(matched.get("state") or "unsigned"),
                           stmt_id=sid,
                           verification_id=str(matched.get("verification_id") or ""),
                           streak=int(matched.get("streak") or 0),
                           need=int(matched.get("need") or 0),
                           why=str(matched.get("why") or reading.get("why") or ""))
                continue
            if other or str(reading.get("state") or "") in (
                    "signed", "rejected", "holding", "stale"):
                # 在册那一版上有签，但盖的不是这一份 ⇒ 改稿（stale）。
                out.update(state="stale", stmt_id=sid,
                           verification_id=str(other.get("verification_id") or ""),
                           why=(f"在册的那一条（{sid}）的签盖的是另一版"
                                f"（{str(other.get('verification_id') or '（没有号）')}），"
                                f"这一版（sha {sha[:12]}…）还没有签"))
            else:
                out.update(state="unsigned", stmt_id=sid,
                           why=(f"在册的那一条（{sid}）一次都没签过"
                                f"（sha {sha[:12]}… 上没有「成立」签）"))
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
            out["state"] = "rejected"
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
                            statement_full: str, proof_text: str,
                            manuscript_text: str = "",
                            manuscript_path: str = "") -> dict:
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
        sig = self._v_signature_for(statement_full=statement_full,
                                    proof_text=proof_text,
                                    manuscript_text=manuscript_text,
                                    manuscript_path=manuscript_path)
        reading.update(
            checked=bool(sig.get("checked")),
            needs_v=True,
            signed=bool(sig.get("signed")),
            in_ledger=bool(sig.get("in_ledger")),
            stmt_id=str(sig.get("stmt_id") or ""),
            verification_id=str(sig.get("verification_id") or ""),
            proof_sha256=str(sig.get("proof_sha256") or ""),
            #: 这一版正文"欠什么"（signed / stale / unsigned / rejected / holding /
            #: unreadable）：拒信按它分四句，下一步不是同一件事（见 `_needs_v_reason`）。
            state=str(sig.get("state") or ""),
            streak=int(sig.get("streak") or 0),
            need=int(sig.get("need") or 0),
            why=str(sig.get("why") or ""))
        if sig.get("signed"):
            return {"needs_v": True, "refused": "", "reason": "", "reading": reading}
        reason = _needs_v_reason(
            sid=str(sig.get("stmt_id") or ""),
            sha12=str(sig.get("proof_sha256") or "")[:12],
            state=str(sig.get("state") or ""),
            verification_id=str(sig.get("verification_id") or ""),
            streak=int(sig.get("streak") or 0),
            need=int(sig.get("need") or 0),
            why=str(sig.get("why") or ""))
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


