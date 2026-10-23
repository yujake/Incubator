# -*- coding: utf-8 -*-
"""命题的五元证据位与派生等级（`draft/39` §3.14，用户 2026-10-05 定）。

## 五个位（每一位都有明确的 owner，owner 是判据的一部分）

| # | 位 | owner | 成立时至少要写什么 |
|---|---|---|---|
| 1 | 数值验证 `numeric` | E | 四态：`verified` / `failed` / `na`（不适用，必须写理由）/ `pending`（还没做）；`verified`/`failed` 要记被哪个脚本测的（script + sha + 实验号） |
| 2 | 有证明 `proof` | F | 证明过程（逐步论证，每步引到的 id 在册） |
| 3 | 审过 `reviewed` | V（自己产出的命题）／引用（引用命题：凭据是文献代号） | 自己产出 ⇒ V 的三态结论；引用 ⇒ `lit:`/`known_lit_id` + 逐字核验 |
| 4 | 形式化通过 `formal` | E | 二维 `{证明号: 四态}`（一份证明一行）；任一路径 `verified` 即算过，而"验的是哪一条路径"逐条可读 |
| 5 | 正式审查 `audited` | H（G 申请） | H 的审校轮次与结论（H 只看证据是否确凿 + 引用是否得当，不读证明判数学） |

## 位与台账的映射（业主 2026-10-09：五元状态是哪张表在维护，要做好映射）

上面的表说的是"这一位属于谁"，`BIT_LEDGERS` 说的是"这一位去哪张表里查"：
`proof` 去 `statements.proof_text`（B 维护的那张表）、`numeric`/`formal` 去
`experiments`（`method` 要对得上）、`reviewed`/`audited` 去稿件上的 V/H 结论。
判据（`bit_evidence_gaps`）只做一件业主点名的事：位上说有，表里要查得到。

## 第 4 位是二维的（业主 2026-10-22 的裁定，逐字）

> 「一个定理有多种证明路径，lean 形式化需指明对哪个路径做了形式化验证，即五元判据有关
>   形式化的那一位也要改成二维列表。但关于一个定理的正确性，但凡任意一个路径通过核验，
>   它就是对的」

于是这一位有两层读法，两层都必须在（缺一层就会出现下面两种坏法之一）：

- 汇总（:func:`_bit_state`）：按 `BIT_STATES` 的顺序取最强那一档 —— 即"任一路径通过
  就算通过"（裁定的第二句）。等级派生只读这一层，定理的正确性判定就是它；
- 逐路径（:func:`formal_by_proof`）：`{证明号: 状态}`，一份证明一行。它是"这一位说的
  是哪一条路径"的唯一读法 —— 折成汇总就等于让 `#p2` 借 `#p1` 的光，而那正是多证明
  模型要堵的东西。

键只能是证明号（`proof_no`）：`path_id` 是 C 的显示名（`p<证明号>g<组号>`，见
`agent_c.path_shape`），同一份证明的路径会按组分裂成好几条 —— 拿它当键就是把"组"
混进"证明"里，于是读数里的路径数比证明数多，而没有任何东西会报。

写侧只写四态（见 `FORMAL_PATH_STATES` 的注释）；`stale` 是读侧产物。

## 等级机械派生（不许任何角色自报等级）

- 全空/false ⇒ 猜想；
- 第 1 位 `verified` ⇒ 强猜想（封顶：数值堆再多也不能变成定理 —— 用户口径"数值验证不构成证明"）；
- 第 2 位 + 第 3 位 ⇒ 预备定理级；
- 第 2 位 + 第 4 位（二维里任一路径 `verified`）⇒ 正式定理；
- 第 5 位 ⇒ 追加"已过正式审查"（并列，不覆盖）。

## 作废（`draft/39` §3.15/§3.18）

只有两种能作废：① 数值实验出真反例（四条判据同时成立）；② 理论构造出反例。
作废后五位读数全部作废（保留历史 + `refuted_by`），条目保留。
"审不出来 / 没人做 / 预算用尽 / 脚本报错"一律不许作废。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

#: 引文"通过"的两档（`schema.QUOTE_MODES` 的唯一来源就是它，这里只转发一次引用）。
from . import quoteevidence as _QE
from .schema import QUOTE_MODES

#: 引文状态的第五档（D1，2026-10-22 第二版）：说"通过"，而盘上拿不出可复核的区间。
#:
#: ## 为什么不折进已有的两档
#:
#: 折进 `unchecked`（"还没查"）：那会把"它说通过了、却指不出核的是哪一段"印成
#: "还没人查过"。两者欠的东西不同 —— 前者欠一次重核（把它降回 None 再查），
#: 后者欠一次回验。一个词盖住两件事，读的人就会去补一条不存在的工序。
#:
#: 折进 `verbatim`：那正是 D1 的现场。真机 `saxl-ws/data/statements.json`（2026-10-22
#: 修复前）13 行全是 `quote_verified=true` / `quote_mode=verbatim` / `quote_span=""`，
#: 而读侧把它们读成"逐字通过" —— 于是"核了哪一段、在第几页"这条读数在盘上根本不存在，
#: 而引用学分（`clean_statement_ids`）照发。
#:
#: ## 判据
#:
#: `quote_verified is True` 且 `quote_span` 为空 ⇒ 这一档（逐字与语义都一样：
#: 区间是"核的是哪一段"的唯一载子）；语义档另外还要求 `quote_call_sha256`
#: （"哪一次判的"）。两件都在 ⇒ 才回到 `QUOTE_MODES` 里那两档。
QUOTE_NO_EVIDENCE = "no_evidence"

#: 引文状态的全部取值（读侧的唯一词表；判据与报告都按它点名）。
#:
#: 刻意不进 `QUOTE_MODES`：那是"方式"的词表（逐字/语义），而这一档说的是
#: "没有证据"，它不是一种方式。混进同一个词表会让 `quote_explains_itself`
#: 把它读成"说清了怎么通过的"。
QUOTE_STATES: tuple[str, ...] = (*QUOTE_MODES, "mismatch", "unchecked", QUOTE_NO_EVIDENCE)

#: 第 1/4 位的四态（顺序就是"从没做到做到了"的强弱）。
BIT_STATES: tuple[str, ...] = ("pending", "na", "failed", "verified")
#: 派生等级（由弱到强；`audited` 是并列的追加档，不进这个序列）。
GRADES: tuple[str, ...] = ("conjecture", "strong_conjecture", "pre_theorem", "theorem")
#: 「不适用」那一档（`draft/97` §14.5）：概念行不参与等级链。
#: 刻意不在 `GRADES` 里：进了那条序列就会被排序、被算进"定理有几条"的计数，
#: 而"这个概念是猜想"这句话本身是错的（概念没有真值，只有良定义没良定义）。
GRADE_NOT_APPLICABLE = "not_applicable"
GRADE_LABELS: dict[str, str] = {
    "conjecture": "猜想",
    "strong_conjecture": "强猜想",
    "pre_theorem": "预备定理级",
    "theorem": "正式定理",
    GRADE_NOT_APPLICABLE: "不适用（概念行不参与等级）",
}
#: 五位的名字（对外读数、台账字段都用这一套）。
BIT_NAMES: tuple[str, ...] = ("numeric", "proof", "reviewed", "formal", "audited")
#: 每一位的 owner（引用命题的第 3 位 owner 是"引用"，不是 V）。
#:
#: 2026-10-23：第 4 位的 owner 从 E 改成 L。业主 2026-10-22 晚裁定「E 的 Lean 侧开关
#: 全写死成关闭」之后，`formal` 那一行只由 `formal.record` 落（`recorded_by="agent-L"`），
#: 而 E 的 formal 那一支一律回受控拒绝 `formal_moved_to_l` ⇒ 改前那句「formal 归 E 签」
#: 是假话（`agent_prompts.collab_fivebits_text` 会把它印进全部十一个角色的提示词）。
#: 第 1 位仍是 E：数值实验那一位确实归 E，那一句是真话、不许跟着改。
BIT_OWNERS: dict[str, str] = {
    "numeric": "E", "proof": "F", "reviewed": "V", "formal": "L", "audited": "H",
}

#: 第 4 位在本模块里的名字（二维那一格的读点不少，写成一个常量免得某处漏改）。
FORMAL_BIT = "formal"

#: 第 4 位逐路径的读侧取值：四态 + `stale`。
#:
#: `stale`（验过、但现行那一份证明已经不是当时那一份）只在读侧产生，写侧从不写它：
#: 写侧记下的是"哪一份正文的 sha256 被哪一次形式化验过"，读侧拿它与现行正文比
#: （:func:`_stale_formal_cleared`）。它是第三种状态，不许折进另外两档 ——
#: 折进 `pending` 会让"验过、过期了"与"没验过"长得一样；折进 `verified` 就是拿旧稿
#: 的结论给新稿背书。刻意不进 `BIT_STATES`：那是写侧的词表。
FORMAL_PATH_STATES: tuple[str, ...] = (*BIT_STATES, "stale")

#: 汇总（OR）时用的强弱顺序：`stale` 夹在 `pending` 与 `na` 之间。
#:
#: 为什么夹在这里：它比 `pending` 强（确实验过一次），比其余三档弱（那一次验的不是
#: 现在这一份）。`BIT_STATES` 的四个取值在这一条序列里的相对顺序逐字不变 ——
#: 所以"按 `BIT_STATES` 顺序取 max"对四态的行为与这一条改前逐字相同。
_BIT_OR_ORDER: tuple[str, ...] = ("pending", "stale", "na", "failed", "verified")


def _state(value: Any) -> str:
    """把一个位的取值规范化成四态之一；`None`/空 ⇒ `pending`（还没做）。

    只收标量。二维位（第 4 位）是 `{证明号: 状态}`，它落到这里会被 `str()` 成一个
    认不出的串、再静默折成 `pending`（改前正是这样：二维 dict 喂进来读成"还没做"，
    而盘上明明写着某个路径 verified）—— 所以这里对 Mapping 直接抛错，
    把"该走 :func:`_bit_state`"这件事变成一次响亮的失败，而不是一条假读数。
    """
    if isinstance(value, Mapping):
        raise ValueError(
            "这个位的取值是一个 Mapping（二维位：{证明号: 状态}）⇒ 它不是标量，"
            "不能用 _state 归一（那会静默折成 pending）；读数请走 _bit_state / "
            "formal_by_proof")
    text = str(value or "").strip().lower()
    if text in ("", "none", "null", "pending", "todo"):
        return "pending"
    if text in ("na", "n/a", "not_applicable"):
        return "na"
    if text in ("failed", "false", "no", "refuted", "refutes", "refute"):
        return "failed"
    if text in ("verified", "true", "yes", "passed", "supports"):
        return "verified"
    return "pending"


def _path_state(value: Any) -> str:
    """逐路径状态的归一：`stale` 原样保留，其余走 :func:`_state`。

    为什么 `stale` 不交给 `_state`：它是读侧的第四档（见 :data:`FORMAL_PATH_STATES`），
    而 `_state` 只认写侧的四态 —— 让它把 `stale` 折成 `pending` 就等于把
    "验过、过期了"读成"还没做"。
    """
    if str(value or "").strip().lower() == "stale":
        return "stale"
    return _state(value)


def _bit_value(value: Any) -> Any:
    """一个位的取值归一：字符串照旧（四态）；Mapping ⇒ 逐路径表（二维位）。

    形状刻意原样保留（标量仍是标量、二维仍是二维）：`bits["formal"]` 是盘上那一栏的
    逐字读数，把它统一成二维会让 62 行存量行在第一次读的时候就被当成"迁移过"，
    而迁移是要有写者、有凭据的（业主口径：零迁移）。
    """
    if isinstance(value, Mapping):
        return {str(key): _path_state(item) for key, item in value.items()}
    return _state(value)


def _bit_state(bits: Mapping[str, Any], name: str) -> str:
    """一个位现在的状态（唯一读口；标量与二维都从这里读）。

    判据只有一句：标量 ⇒ :func:`_state`；Mapping（二维位）⇒ 按 :data:`_BIT_OR_ORDER`
    取最强那一档，也就是"任一路径通过就算通过"（业主 2026-10-22 裁定的第二句）。
    空 Mapping 与"没有这一格"同档（`pending`）：一条路径都没写，就是还没做。

    为什么必须有一个唯一读口：二维 dict 落进 `_state` 会被静默折成 `pending`
    （`str({...})` 认不出），于是"某个路径 verified"与"还没做"在读数上长得一样，
    而等级永远派生不出定理。四个读点（`derive_grade` / `bit_problems` /
    `bit_evidence_gaps` / 收工门的等级现算）全部走这里。
    """
    raw = bits.get(name) if isinstance(bits, Mapping) else None
    if not isinstance(raw, Mapping):
        return _state(raw)
    states = [_path_state(item) for item in raw.values()]
    if not states:
        return "pending"
    return max(states, key=lambda item: _BIT_OR_ORDER.index(item)
               if item in _BIT_OR_ORDER else 0)


def bits_of(*, numeric: Any = None, numeric_evidence: Mapping[str, Any] | None = None,
            numeric_reason: str = "", proof: Any = None, proof_process: str = "",
            reviewed: Any = None, reviewed_by: Mapping[str, Any] | None = None,
            formal: Any = None, formal_evidence: Mapping[str, Any] | None = None,
            formal_reason: str = "", audited: Any = None,
            audited_by: Mapping[str, Any] | None = None, origin: str = "own_result",
            source_lit_id: str = "", quote_verified: Any = None,
            voided_by: Mapping[str, Any] | None = None,
            kind: str = "") -> dict[str, Any]:
    """把各方标下的读数组装成五元位（纯函数：不读盘、不写盘）。

    ## 引用命题那一条（`draft/39` §3.15 三）

    `origin=external_lit` 且引到一条逐字核过的来源（`quote_verified is True`）⇒
    第 2 位（有证明）与第 3 位（审过）直接为真，凭据是文献代号（不是 V 的走查）。
    引用来的命题因此最多到"预备定理级"（第 4 位要形式化，第 5 位要 G 申请 H 审）。
    """
    cited = bool(source_lit_id) and origin == "external_lit" and quote_verified is True
    bits: dict[str, Any] = {
        "numeric": _state(numeric),
        "proof": bool(proof) or cited or bool(proof_process.strip()),
        "reviewed": bool(reviewed) or cited,
        # 第 4 位可以是二维的（`{证明号: 状态}`）：形状原样保留，见 `_bit_value`。
        "formal": _bit_value(formal),
        "audited": bool(audited),
        "origin": str(origin or "own_result"),
        "evidence": {
            "numeric": dict(numeric_evidence or {}),
            "numeric_reason": str(numeric_reason or ""),
            "proof_process": str(proof_process or ""),
            # 第 2 位是怎么来的：`citation`（引用命题，凭据是文献代号）还是 `own`（我方证明过程）。
            # 这一栏必须显式落 —— 否则"引用命题的第 2 位"会被 `bit_problems` 当成
            # "自己写了证明却没写过程"而报缺陷（判据分不出两者等于两者被压成一件事）。
            "proof_source": "citation" if cited else ("own" if proof else ""),
            "reviewed_by": dict(reviewed_by or ({"evidence": f"lit:{source_lit_id}"} if cited else {})),
            "formal": dict(formal_evidence or {}),
            "formal_reason": str(formal_reason or ""),
            "audited_by": dict(audited_by or {}),
        },
        "voided_by": dict(voided_by or {}),
    }
    bits["grade"] = derive_grade(bits, kind=kind)
    bits["audited_badge"] = (bool(bits["audited"])
                             and bits["grade"] not in ("conjecture", GRADE_NOT_APPLICABLE))
    return bits


def quote_state(row: Mapping[str, Any]) -> str:
    """一条引文现在的状态（引文回验的唯一读口径，2026-10-14 业主裁定之后）。

    业主那句话：「回验不应该是十分呆板的逐字验证，而是保持语义相同即可」。
    于是"通过"这件事分两档，五个取值：

    - `"verbatim"`：逐字命中（`quoteverify.check_quote` 那一档，不花模型钱）；
    - `"semantic"`：语义相同（H 判的；允许改写、换记号、跨语言）；
    - `"mismatch"`：查过了、不一致（`quote_verified is False`）——语义档也救不了它：
      H 的判据是"引文与来源说同一件事"，"结论强于引文"照样落这一档；
    - `"unchecked"`：还没查（`None`），或者方式那一栏是认不出的词
      （词表外的值 ⇒ 说不出怎么通过的 ⇒ 按没查算）；
    - `"no_evidence"`：说通过了，而盘上拿不出可复核的区间（见 :data:`QUOTE_NO_EVIDENCE`）
      —— 逐字与语义两档都要求 `quote_span` 非空（语义还要 `quote_call_sha256`）。

    ## 空 `quote_mode` 那一条（历史事实，2026-10-22 起多一个前提）

    这一栏是 2026-10-14 才有的，在那之前 `quote_verified=True` 只可能来自
    `quoteverify.check_quote`（逐字那一档）—— 所以"空方式 + 有区间"按 `verbatim` 读，
    判据 `test_a_legacy_external_lit_row_keeps_its_citation_credit` 钉着这条读法。

    但"空方式"本身不再够：区间才是"核过"的证据。没有区间时，无论方式那一栏
    写着 `verbatim` 还是空着，读侧一律给 `no_evidence` —— 这不是追溯性降级，
    而是把一直缺的那一格补上：真机 13 行正是"空方式/verbatim + 空区间"，
    它们此前被读成逐字通过，于是引用学分（`clean_statement_ids`）与收工门的
    `quote_verified_rows` 都被这 13 行顶高。

    为什么读侧还要再判一次（写侧 `schema._normalize_quote_mode` 已经归一过）：盘上是
    JSON —— 手改的行、旧版本写的行、别的工具写的行都可能绕过构造器。这一条是"读的人
    永远看到自洽的一对（结论 + 证据）"的兜底，`bits_from_row` 与收工门都走它。
    """
    verified = row.get("quote_verified")
    if verified is None:
        return "unchecked"
    if verified is not True:
        return "mismatch"
    mode = str(row.get("quote_mode") or "")
    if mode != "" and mode not in QUOTE_MODES:
        return "unchecked"
    if not _QE.span_of(row):
        return QUOTE_NO_EVIDENCE
    if mode == "semantic" and not _QE.call_of(row):
        return QUOTE_NO_EVIDENCE
    return mode or "verbatim"


def quote_explains_itself(row: Mapping[str, Any]) -> bool:
    """这一行的"通过"有没有说清方式并拿得出位置（`quote_state` 落在两档里）。

    两件缺一不可：方式（`quote_mode` ∩ `QUOTE_MODES`）与位置（`quote_span` 非空，
    语义档还要 `quote_call_sha256`）。只有方式没有位置的行走 `no_evidence`
    —— 它的"通过"复现不出来，所以本函数给 `False`（引用学分因此不给它）。
    """
    return quote_state(row) in QUOTE_MODES


def bits_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """台账里的一行 ⇒ 五元位（唯一的读入口：判据、门、状态报告都走这里）。

    两条路：

    - 行里有 `bits` 记录（新写的行）⇒ 按四态/布尔重新规范化一遍再派生等级
      （等级永远现算，不信盘上存的等级 —— 存的那份只当缓存，判据不读它）；
    - 行里没有位记录（旧行）⇒ 一律按"五位全空"算，只有引用命题那一条例外
      （`origin=external_lit` + `quote_verified` ⇒ 第 2+3 位为真，凭据是文献代号）。

    为什么旧行要按全空算：`statements.status='proved'`、`evidence_kind='proof'` 这些
    都是自报的。五元位这套东西存在的理由就是"自报不算凭据"——若这里给旧行补一个
    尊重的读法，那套纪律当场破功（而且历史上正是那些自报字段把"数值支持"读成了"已证明"）。
    """
    raw = dict(row.get("bits") or {})
    origin = str(row.get("origin") or "own_result")
    kind = str(row.get("kind") or "")
    if not raw:
        return bits_of(origin=origin, source_lit_id=str(row.get("source_lit_id") or ""),
                       quote_verified=quote_explains_itself(row), kind=kind)
    bits = normalize_raw(raw, origin=origin, kind=kind,
                         voided_by=dict(raw.get("voided_by") or row.get("refuted_by") or {}))
    bits = _stale_review_cleared(bits, row, kind=kind)
    return _stale_formal_cleared(bits, row, kind=kind)


def _stale_formal_cleared(bits: dict[str, Any], row: Mapping[str, Any], *,
                          kind: str = "") -> dict[str, Any]:
    """第 4 位记的「验的是哪一份证明」与现行正文不是同一份 ⇒ 那条路径读成 stale。

    ## 为什么读侧要判这一条（与第 3 位同一条口径：哈希是读数，不是授权凭证）
    形式化验的是"这一份证明"（`:data:`FORMAL_BY_PROOF_KEY` 的凭据里记着那一份正文的
    `proof_sha256`）。此后 B 改稿是正常动作（不许拒写），而位还停在 `verified` 上 ——
    于是"某个路径验过"这个读数会过期。读侧的判据就一句：记下来的 sha 与它现在这一份
    不同 ⇒ 那条路径不是"验过"，而是"验过、过期了"（`stale`）。

    ## 边界（三态：判不了就不判）
    - 位是标量（老行 / 单路径且没记 sha）⇒ 什么都不做：没有逐路径的凭据可核；
    - 那一条路径没有 `proof_sha256`（手写的行 / 别的写者）⇒ 判不了，原样返回；
    - 那一份证明的正文取不到（行里没有 `proof_text`、清单里也没有那个号）⇒ 判不了；
    - 没有任何一条路径是 `verified` ⇒ 什么都不做（`failed` / `na` / `pending` 与
      "过的期"无关）。

    ## 只改那一条路径
    汇总位是"任一路径通过就算通过"（:func:`_bit_state`），所以只把过期的那条压成
    `stale`、别的路径一个字不动 —— 另一条路径验的可能就是现在这一份。
    """
    raw = bits.get(FORMAL_BIT)
    if not isinstance(raw, Mapping) or not raw:
        return bits
    per = formal_by_proof(bits)
    if "verified" not in per.values():
        return bits
    evidence = formal_evidence_by_proof(bits)
    if not evidence or not isinstance(row, Mapping) or "proof_text" not in row:
        return bits
    from . import verifications as _VR   # 惰性：证明号、正文与 sha 的口径各只有一处

    current = dict(_VR.proof_list(row))
    cleared: dict[str, str] | None = None
    for no, state in sorted(per.items()):
        if state != "verified":
            continue
        want = str((evidence.get(no) or {}).get("proof_sha256") or "")
        if not want:
            continue
        text = current.get(no)
        if text is None:
            continue
        if _VR.proof_sha(text) == want:
            continue
        if cleared is None:
            cleared = {str(key): _path_state(value) for key, value in raw.items()}
        cleared[str(no)] = "stale"
    if cleared is None:
        return bits
    out = dict(bits)
    out[FORMAL_BIT] = cleared
    out["grade"] = derive_grade(out, kind=kind)
    out["audited_badge"] = (bool(out.get("audited"))
                            and out["grade"] not in ("conjecture", GRADE_NOT_APPLICABLE))
    return out


def _stale_review_cleared(bits: dict[str, Any], row: Mapping[str, Any], *,
                          kind: str = "") -> dict[str, Any]:
    """第 3 位写的时候记了「签的是哪一份」而现行正文不是那一份 ⇒ 这一位读成没审过。

    ## 为什么读侧要判这一条（业主 2026-10-22 口径：哈希是读数，不是授权凭证）
    写侧把 `reviewed` 翻真时会把这一签盖住的那一份正文的 `proof_sha256` 连同证明号
    `proof_no` 记进 `evidence.reviewed_by`。此后正文可能又被改过（改稿是正常动作，
    不许因此拒写），而位还停在 `True` 上 —— 于是"审过"这个读数会过期。读侧的判据
    就一句：记下来的那份 sha 与它现在这一份不同 ⇒ 这一位现在不是"审过"，而是
    "签过、过期了"。
    ## 边界（三态：判不了就不判）
    - 位是假 ⇒ 什么都不做（没签过不是 stale）；
    - `reviewed_by` 里没有 `proof_sha256`（历史行 / 引用命题那条凭据是 `lit:` 代号）
      ⇒ 判不了，原样返回（不许把判不了的读成"过期"）；
    - 那一份证明的正文取不到（行里没有 `proof_text`，也没有对应证明号的清单项）
      ⇒ 判不了，原样返回。

    ## 多证明：汇总位是"任一条仍 in-sync"，不是"最近那一签仍 in-sync"
    `reviewed_by` 只有一格（它记的是最近那一签），只核它会让"签过 #p1、之后改了 #p2"
    这一类读成没审过 —— 而 #p1 那一签明明还盖着现在这一份。所以写侧另外落一张
    逐条证明的 sha 表（:data:`REVIEWED_SHA_BY_PROOF_KEY`），这里按 `proof_list`
    逐条核"这一份证明签过、而且签的就是现在这一份正文"，任一条成立 ⇒ 位仍成立；
    全部对不上 ⇒ 这一位过期（上面那三档"判不了"照旧原样返回）。
    """
    if not bits.get("reviewed"):
        return bits
    ev = dict(bits.get("evidence") or {})
    reviewed_by = dict(ev.get("reviewed_by") or {})
    want = str(reviewed_by.get("proof_sha256") or "")
    if not want:
        return bits
    from . import verifications as _VR   # 惰性：证明号与 sha 的口径各只有一处

    signed_sha = reviewed_sha_by_proof(bits)
    if signed_sha and "proof_text" in row:
        # 逐条核（`proof_list` 是"这条命题有哪几份证明"的唯一读法）
        current = dict(_VR.proof_list(row))
        for no in sorted(signed_sha):
            text = current.get(no)
            if text is None:
                continue
            if _VR.proof_sha(text) == signed_sha[no]:
                return bits          # 至少这一份还盖着现在这一份正文
        return _reviewed_cleared(bits, kind)
    proof_no = _VR.as_proof_no(reviewed_by.get("proof_no")) or 1
    text = _VR.proof_text_of(row, proof_no)
    if proof_no == 1 and "proof_text" not in row:
        return bits          # 部分调用方只喂 `bits`：没有正文可判
    got = _VR.proof_sha(text)
    if got == want:
        return bits
    return _reviewed_cleared(bits, kind)


def _reviewed_cleared(bits: dict[str, Any], kind: str) -> dict[str, Any]:
    """第 3 位读成"签过、过期了"之后的那一份读数（等级必须现算）。"""
    out = dict(bits)
    out["reviewed"] = False
    out["grade"] = derive_grade(out, kind=kind)
    out["audited_badge"] = (bool(out.get("audited"))
                            and out["grade"] not in ("conjecture", GRADE_NOT_APPLICABLE))
    return out


#: `bits` 这一栏里位本身之外允许出现的键（写台账时要经过 `bits_shape_problems`）。
BIT_META_KEYS: tuple[str, ...] = ("evidence", "voided_by", "origin", "grade", "audited_badge")

#: 逐条证明的第 3 位记在 `bits.evidence` 的这一格（写侧是 `verifications.sign_statement`）。
#:
#: 结构逐字是"证明号 ⇒ 布尔"：`{"1": true, "2": false}`。为什么住在 `evidence` 里而不是
#: `bits` 顶层：`bits` 的顶层键集由 :func:`bits_shape_problems` 拥有，未知键在写入期就会被
#: 拒收；`evidence` 是它明确留白的凭据口袋（`normalize_raw` 原样保留整份 dict），
#: 所以"不新增 schema 字段"与"把逐条读数放在这一栏"在这里是同一句话。
REVIEWED_BY_PROOF_KEY = "reviewed_by_proof"

#: 逐条证明「那一签盖住的是哪一份正文」：`{"1": "<sha256>", "2": ""}`。
#:
#: 为什么要第二张表：`reviewed_by` 只有一格（最近那一签），而汇总位 `bits.reviewed`
#: 的语义是"任一条证明 in-sync 即成立"。只拿最近那一签核 sha 时，签过 `#p1` 之后
#: 改了 `#p2`（或反过来）会让整条命题读成没审过 —— 那是一条承重读数被一格凭据压掉。
#: 空串 = 这一份签过、但没记下 sha（历史行）⇒ 读侧判不了，不拿它当依据。
REVIEWED_SHA_BY_PROOF_KEY = "reviewed_sha_by_proof"


def reviewed_by_proof(row: Mapping[str, Any]) -> dict[int, bool]:
    """按证明看第 3 位：`{证明号: 有没有签}`（写侧签下的那张表）。

    ## 它回答什么、不回答什么
    这是"签名当时判过这一份"的逐条记录：只签了 `#p1` 而这条定理还有 `#p2` ⇒
    `{1: True, 2: False}`（`#p2` 不许借 `#p1` 的光）。它不回答"签的是不是现在这一份
    正文"：那件事只有 `verifications` 的台账能回答（`review_standing` 的
    signed / stale / rejected / unsigned），所以这一格也绝不拿 sha 去否决任何写入 ——
    哈希是读数，不是授权凭证。
    ## 入参与兼容
    收 statements 行（有 `bits` 键）或一份 `bits` dict（没有 `bits` 键、自己就是）。
    正位是 `bits.evidence.reviewed_by_proof`；若某一行把它写在 `bits` 顶层
    （手写或别的写者），这里也读。认不出的键跳过（它们不是证明号）；值按 `bool` 归一一遍
    （盘上是 JSON，可能是 `true` / `1` / `"true"`）。
    """
    outer = row if isinstance(row, Mapping) else {}
    bits = outer.get("bits") if isinstance(outer.get("bits"), Mapping) else outer
    pocket = bits.get(REVIEWED_BY_PROOF_KEY)
    if not isinstance(pocket, Mapping):
        pocket = dict(bits.get("evidence") or {}).get(REVIEWED_BY_PROOF_KEY)
    if not isinstance(pocket, Mapping):
        return {}
    from . import verifications as _VR   # 惰性：证明号的归一只有一处口径

    out: dict[int, bool] = {}
    for raw_no, value in pocket.items():
        no = _VR.as_proof_no(raw_no)
        if no < 1:
            continue
        out[no] = bool(value)
    return out


def reviewed_sha_by_proof(row: Mapping[str, Any]) -> dict[int, str]:
    """按证明看「那一签盖住的是哪一份正文」：`{证明号: sha256}`（写侧签下的第二张表）。

    ## 它回答什么
    与 :func:`reviewed_by_proof` 同一格口袋（`bits.evidence`）：那张表说"这一份签过"，
    这张表说"签的是这一份正文"。于是汇总位 `bits.reviewed` 能按"任一条仍 in-sync"
    读出来，而不是被 `reviewed_by` 里最近那一签压成一条。
    ## 边界
    空串 / 拿不出 sha 的条目直接跳过（历史行没这一格 ⇒ 返回空表，读侧退回老的单凭据
    判法，绝不把"判不了"读成"过期"）。键按证明号归一（与 `reviewed_by_proof` 同一口径）；
    收 statements 行或一份 `bits` dict 都可以。
    """
    outer = row if isinstance(row, Mapping) else {}
    bits = outer.get("bits") if isinstance(outer.get("bits"), Mapping) else outer
    pocket = bits.get(REVIEWED_SHA_BY_PROOF_KEY)
    if not isinstance(pocket, Mapping):
        pocket = dict(bits.get("evidence") or {}).get(REVIEWED_SHA_BY_PROOF_KEY)
    if not isinstance(pocket, Mapping):
        return {}
    from . import verifications as _VR   # 惰性：证明号的归一只有一处口径

    out: dict[int, str] = {}
    for raw_no, value in pocket.items():
        no = _VR.as_proof_no(raw_no)
        if no < 1:
            continue
        sha = str(value or "").strip()
        if sha:
            out[no] = sha
    return out


#: 逐条证明的第 4 位凭据记在 `bits.evidence` 里的这一格（写侧是 B 的登记那条路）。
#:
#: 结构是"证明号 ⇒ 那一份的凭据"：`{"1": {"checker": "lean4", "experiment_id": "0007",
#: "proof_sha256": "…", "path_source": "B"}, "2": {…}}`。与 `REVIEWED_BY_PROOF_KEY`
#: 同一族：`bits` 顶层只认位名与 `BIT_META_KEYS`，所以逐条凭据住在 `evidence` 这个
#: 明确留白的口袋里；`bits.evidence.formal` 仍然保留（它是"最近那一次"的单格载荷，
#: 老读者只认它），逐条的那一份在这张表里。
FORMAL_BY_PROOF_KEY = "formal_by_proof"


def formal_by_proof(row: Mapping[str, Any]) -> dict[int, str]:
    """按证明看第 4 位：`{证明号: 状态}`（二维位的唯一逐路径读法）。

    ## 它回答什么
    "哪一条路径被形式化验过、验成了什么"。状态取 :data:`FORMAL_PATH_STATES` 的五档
    （四态 + 读侧产生的 `stale`）。汇总位（:func:`_bit_state`）是它的 OR；两者都要，
    缺了逐条这一层就会让 `#p2` 借 `#p1` 的光。
    ## 标量位怎么读
    老行 / 单路径行把这一位写成标量（`"pending"` / `"verified"`）：那是 canonical 那一份
    证明的读数（`#p1`），所以读成 `{1: 那个四态}`。空 Mapping 读成 `{}`（一条路径都
    没写），不读成 `{1: "pending"}` —— "没有这一格"与"写了 #p1 还没做"是两件事。
    ## 键
    只认证明号（`verifications.as_proof_no` 归一）：认不出的键跳过。盘上 JSON 的键是
    字符串，所以 `{"1": …}` 与 `{1: …}` 在这里是同一件事。
    ## 过期判定（这里也做，不只是 `bits_from_row` 做）
    收一份完整的命题行（有 `bits` 键、也有 `proof_text`）时，先过一遍
    :func:`bits_from_row`：那一层会把"验的不是现在这一份正文"的通路压成 `stale`。
    这一格必须自己也判，否则任何直接调本函数的读者都会拿到一个"看起来还 verified"
    的旧读数 —— 同一个函数给两种答案，比多一个读口更坏。传进来的已经是一份 `bits`
    dict（没有 `bits` 键）时不重判（避免自递归，也避免把 `stale` 再折一次）。
    """
    outer = row if isinstance(row, Mapping) else {}
    bits = outer.get("bits") if isinstance(outer.get("bits"), Mapping) else outer
    if bits is not outer and "proof_text" in outer:
        bits = bits_from_row(outer)
    raw = bits.get(FORMAL_BIT)
    if not isinstance(raw, Mapping):
        return {1: _path_state(raw)}
    from . import verifications as _VR   # 惰性：证明号的归一只有一处口径

    out: dict[int, str] = {}
    for raw_no, value in raw.items():
        no = _VR.as_proof_no(raw_no)
        if no < 1:
            continue
        out[no] = _path_state(value)
    return out


def formal_evidence_by_proof(row: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    """按证明看第 4 位的凭据：`{证明号: {checker / experiment_id / proof_sha256 / …}}`。

    两处来源，按优先级：

    1. `bits.evidence.formal_by_proof`（写侧逐条落的那张表，:data:`FORMAL_BY_PROOF_KEY`）；
    2. `bits.evidence.formal`（单格载荷，老形态）⇒ 它说的是 canonical 那一份，读成 `{1: …}`。

    第 2 条为什么必须留着：`bits.evidence.formal` 是这一格改前唯一的落点（`bits_of`
    的 `formal_evidence` 参数写的就是它），历史行与手写行都只有它。丢掉它等于让所有
    历史行的 `formal=verified` 变成"没有凭据"（判据会当场报错，而错的是读侧）。
    空载荷与"没有这一格"同档：返回空表，由 `bit_problems` 决定该不该报。
    """
    outer = row if isinstance(row, Mapping) else {}
    bits = outer.get("bits") if isinstance(outer.get("bits"), Mapping) else outer
    ev = dict(bits.get("evidence") or {})
    from . import verifications as _VR   # 惰性：与 `formal_by_proof` 同一处口径

    out: dict[int, dict[str, Any]] = {}
    pocket = ev.get(FORMAL_BY_PROOF_KEY)
    if isinstance(pocket, Mapping):
        for raw_no, value in pocket.items():
            no = _VR.as_proof_no(raw_no)
            if no < 1 or not isinstance(value, Mapping):
                continue
            out[no] = dict(value)
    if out:
        return out
    flat = ev.get(FORMAL_BIT)
    if not isinstance(flat, Mapping) or not flat:
        return {}
    # `bits.evidence.formal` 自己也可能是二维的（`bits_of(formal_evidence={证明号: 载荷})`
    # 原样把它写进去）：全部键都是证明号、值都是对象时按逐条读；否则按单格载荷读，
    # 那是 canonical 那一份（`#p1`）。两件都认，是为了不让"凭据写在哪一格"决定它读不读得出来。
    per: dict[int, dict[str, Any]] = {}
    for raw_no, value in flat.items():
        no = _VR.as_proof_no(raw_no)
        if no < 1 or not isinstance(value, Mapping):
            return {1: dict(flat)}
        per[no] = dict(value)
    return per or {1: dict(flat)}


def normalize_raw(raw: Mapping[str, Any], *, origin: str = "own_result",
                  voided_by: Mapping[str, Any] | None = None,
                  kind: str = "") -> dict[str, Any]:
    """盘上那一栏 `bits` ⇒ 规范化的五位（布尔/四态都归一，等级现算）。

    读与写共用这一份：`bits_from_row`（读）与 `bits_shape_problems`（写之前把形状关）
    若各归一一次，就会出现"写进去判合规、读出来是另一个意思"的分家。

    第 4 位走 :func:`_bit_value`（标量仍是四态、二维仍是逐路径表）：它不是"一个状态"，
    它是"每个证明号一个状态"—— 把它统一压成一档，改前那条"二维 dict 被静默读成
    pending"的路就会在这一格里复活。
    """
    bits: dict[str, Any] = {
        "numeric": _state(raw.get("numeric")),
        "proof": bool(raw.get("proof")),
        "reviewed": bool(raw.get("reviewed")),
        "formal": _bit_value(raw.get("formal")),
        "audited": bool(raw.get("audited")),
        "origin": origin,
        "evidence": dict(raw.get("evidence") or {}),
        "voided_by": dict(voided_by if voided_by is not None else (raw.get("voided_by") or {})),
    }
    bits["grade"] = derive_grade(bits, kind=kind)
    bits["audited_badge"] = (bool(bits["audited"])
                             and bits["grade"] not in ("conjecture", GRADE_NOT_APPLICABLE))
    return bits


def bits_shape_problems(raw: Mapping[str, Any] | None, *,
                        kind: str = "") -> list[str]:
    """写台账之前把 `bits` 那一栏的形状关（未知键 / 自报等级与现算不一致 / 位自身不合规）。

    为什么连"自报的等级"也要管：判据从不读盘上那个等级（`bits_from_row` 永远现算），
    于是存一个与现算不符的等级不会改变任何结论 —— 它只会让读盘的人（包括模型自己）
    看到两个数。这种"看起来是读数、其实谁都不读"的字段正是本仓最忌的形态，所以在写入期
    直接拒掉：等级可以留着当缓存，但必须与现算逐字相同。
    """
    if not raw:
        return []
    if not isinstance(raw, Mapping):
        return ["bits 必须是对象（五位：numeric/proof/reviewed/formal/audited）"]
    problems: list[str] = []
    unknown = sorted(set(raw) - set(BIT_NAMES) - set(BIT_META_KEYS))
    if unknown:
        problems.append(
            f"bits 里有不认识的键 {unknown}：位的名字只有 {list(BIT_NAMES)}"
            f"（另加 {'/'.join(BIT_META_KEYS)}）—— 拼错的键会被静默忽略，"
            "于是它与「这一位还没填」长得一模一样")
    bits = normalize_raw(raw, origin=str(raw.get("origin") or "own_result"), kind=kind)
    formal_raw = raw.get(FORMAL_BIT)
    if isinstance(formal_raw, Mapping):
        from . import verifications as _VR   # 惰性：证明号的归一只有一处口径

        bad_keys = sorted(str(key) for key in formal_raw if _VR.as_proof_no(key) < 1)
        if bad_keys:
            problems.append(
                f"bits.formal 是二维的（{{证明号: 状态}}），而有键不是证明号：{bad_keys}"
                " —— 键只能是证明号（1、2、3 …）；`path_id` 是 C 的显示名，"
                "混进来会把「组」当成「证明」，路径数会凭空变多而没有东西报")
        read_only = sorted(str(key) for key, value in formal_raw.items()
                           if str(value or "").strip().lower() == "stale")
        if read_only:
            problems.append(
                f"bits.formal 里写了 {read_only} 的 `stale` —— 它不是写侧的词表"
                f"（写侧只写 {list(BIT_STATES)}）：`stale` 由读侧按「记下来的"
                " proof_sha256 与现行正文不符」现算（`_stale_formal_cleared`），"
                "写进盘上就等于让一份旧稿的结论自己给自己背书")
    claimed = raw.get("grade")
    if claimed is not None and str(claimed) != bits["grade"]:
        problems.append(
            f"bits.grade 写的是 {claimed!r}，按五位现算是 {bits['grade']!r} —— "
            "等级不许自报（判据永远现算）：要么删掉这个键，要么让它等于现算值")
    problems.extend(bit_problems(bits))
    return problems


def derive_grade(bits: Mapping[str, Any], *, kind: str = "") -> str:
    """五元位 ⇒ 等级（唯一的等级来源；任何角色自报的等级都不认）。

    第 1 位只做一件事：把"猜想"抬成"强猜想"——封顶就在这一条：
    数值验证再多、再强，也到不了"定理"（用户口径：数值验证不构成证明）。

    `kind="concept"` 短路（`draft/97` §14.5，业主 2026-10-09「concept 表真并进
    statements……proof 里就证这个概念为什么是良定义的」）：概念不参与这条链。
    它没有证据位（`bits={}`），若照常派生，现算结果是最弱那一档 ——
    于是并表之后每条概念都会被读成"猜想"，而"猜想"在报告里是一句关于真值的话，
    概念根本没有真值可言（它只有"良定义没良定义"）。所以这一档单独给一个值
    （`GRADE_NOT_APPLICABLE`），它不在 `GRADES` 里 —— 不参与排序、不算进定理计数。
    """
    if str(kind or "") == "concept":
        return GRADE_NOT_APPLICABLE
    if bits.get("voided_by"):
        return "conjecture"          # 作废之后等级清零（历史留在 voided_by 里）
    has_proof = bool(bits.get("proof"))
    reviewed = bool(bits.get("reviewed"))
    # 第 4 位是二维的：这里读的是汇总（任一路径通过即通过，业主 2026-10-22 裁定的第二句）。
    # 逐条路径各自的等级由 `verifications.statement_review_reading` 的 `proofs[*]` 给 ——
    # 函数级只回答"这条命题到不到定理"，不回答"是哪一条路径撑起来的"。
    formal = _bit_state(bits, FORMAL_BIT) == "verified"
    if has_proof and formal:
        return "theorem"
    if has_proof and reviewed:
        return "pre_theorem"
    if _bit_state(bits, "numeric") == "verified":
        return "strong_conjecture"
    return "conjecture"


#: D-37（2026-10-24）：`kind` 能跟着证据走的起点与终点。
#:
#: 只允许"猜想 → theorem / lemma"这一个方向：`conjecture`（以及空串这个历史形态）
#: 是唯一可以往上抬的声明，`theorem` / `lemma` 是唯一两个可以落下的名字。别的声明
#: （`proposition` / `definition` / `concept` …）一个字都不动 —— 那是作者写下的判断，
#: 读侧没有资格替它改（业主口径：不要覆盖 author 明确写下的更强 kind）。
KIND_UPGRADABLE_FROM: tuple[str, ...] = ("conjecture", "")
KIND_UPGRADE_TARGETS: tuple[str, ...] = ("theorem", "lemma")


def kind_following_grade(row: Mapping[str, Any], *, root: Any = None,
                         requested: str = "") -> dict[str, Any]:
    """一条命题的 `kind` 该不该跟着证据升（D-37 的唯一口径：写侧的两个落点共用它）。

    （它是纯读函数，所以任何读的人 —— 报告、探针、判据 —— 都能调它问"按盘上的证据，
    这一行现在该叫什么"，而调它本身不会改盘。写侧只有两处落点：秘书的升档那一支、
    B 同步第 4 位那一支。）

    ## 现场（2026-10-24 真机 `cube-ws` 抓到，只读取数）
    `statements 000000`：`kind="conjecture"`、`evidence_kind="proof_review"`、
    `bits.grade="theorem"`（proof=true / reviewed=true / formal={"1": "verified"}），
    `verifications/000000.jsonl#v-000001` 判「成立」且 `proof_sha256` 与现行正文相符
    （`experiments 000001` 是 Lean 4.7.0 + Mathlib 真编译，exit 0）。
    ⇒ 证据链齐全、等级现算也已经是 `theorem`，而行上的 `kind` 仍写着"猜想"。
    读的人（G 写稿 / H 审校 / 收工门）读 `kind` 那一格，于是"这是定理"这句话在盘上
    不存在 —— 等级与名字分家。

    ## 判据（三件，按顺序判）
    1. 起点只认 `conjecture`（:data:`KIND_UPGRADABLE_FROM`）⇒ 别的 kind 一律
       `not_applicable`：作者写下的更强声明不许被这一格改掉；
    2. 升档依据必须是盘上读得出来的那一行，两条路各算一条依据：
       a. `verifications/<命题号>.jsonl` 里有一条盖住现行正文、判「成立」的签
          （判据本体在 `verifications.proof_review_gap`，这里只取它的结论；
          D-34 的"命题还没在册时审的那一签"也由它认领）；
       b. `bits.evidence.formal_by_proof[证明号] == "verified"`（第 4 位逐条里
          真有一条 `verified`；`stale` 不算 —— 那是"验过旧稿"）；
       两条都没有 ⇒ `state="held"`，`shortfall` 逐条写清还差什么；
    3. 落下的名字取 `requested`（提交方声明的那个，只在 `theorem` / `lemma` 之间选），
       没给就是 `theorem`。

    ## 为什么"只有形式化 verified、没有 V 的签"也落到 `theorem`（③ 的取舍，备查）
    `derive_grade` 的现算口径是：第 2 位 + 第 3 位 ⇒ `pre_theorem`；第 2 位 + 第 4 位
    任一路径 `verified` ⇒ `theorem`。V 的签与形式化通过是两条并列的独立凭据
    （第 3 位 vs 第 4 位），而名字只有一个 ⇒ 两条依据都落到 `theorem`：
    - V 签成立 + 证明 ⇒ `theorem`（等级现算是 `pre_theorem`，但那一签就是"这份证明站得住"
      的结论，名字不该比它低一档）；
    - 只有形式化 `verified`、没有 V 的签 ⇒ 也是 `theorem`，不是 lemma、也不是仍停在
      conjecture：`derive_grade` 对"证明 + 任一路径形式化通过"本来就现算 `theorem`，
      把它降成 `lemma` 会造出第二个等级口径（同一个 `bits` 在两处读出两个档）。
      V 的签不是"能不能叫定理"的必要条件，它是第 3 位那条独立凭据；一条 Lean 真编译过的
      证明已经是定理。这是本判据对 ③ 的答案。

    ## 纯读（历史不追溯）
    这个函数一个字节都不写：不改行、不改 `bits`、不补台账、不新建事件。它只回答
    "按盘上现有的证据，这一行现在该叫什么"。改名由写侧的落点各自完成（秘书的升档
    那一支、B 同步第 4 位那一支），两边都调这一个函数 ⇒ 口径只有一份。所以一条证据
    齐全、`kind` 仍写着"猜想"的历史行读一次不会被静默改写：读它只给出
    `state="upgraded"` 与依据，改不改由下一次写（同一份内容再交一次）决定。

    ## 三态
    | state | 含义 |
    |---|---|
    | `upgraded` | 证据够：`kind` 是升上去的那一个，`basis` 写着凭什么 |
    | `held` | 证据不够：`kind` 保持 `conjecture`，`shortfall` 写清还差什么 |
    | `not_applicable` | 行上的 kind 不是猜想（概念 / 已经写强了）⇒ 不覆写 |
    | `unreadable` | 五元位算不出来 ⇒ 升不升判不了（没判成不是"已经升了"） |

    返回键：`checked` / `state` / `kind` / `declared` / `grade` / `basis` /
    `shortfall` / `why` / `statement_id`。`basis` 是给读的人复算的那一句
    （形如 `verifications/000000.jsonl#v-000001 判成立` 或
    `bits.evidence.formal_by_proof[1]=verified`）。

    `root` 是工作区根（读 `verifications/` 台账用）。不给 ⇒ 那一签这一格
    没查成（`shortfall` 里写明"没查成"，不许折成"没签"）；形式化那一条依据
    不读盘，所以它照样能判。
    """
    outer = row if isinstance(row, Mapping) else {}
    declared = str(outer.get("kind") or "").strip()
    sid = str(outer.get("stmt_id") or outer.get("statement_id") or "")
    out: dict[str, Any] = {
        "checked": True, "state": "held", "declared": declared,
        "kind": declared or "conjecture", "grade": "", "basis": "",
        "shortfall": "", "why": "", "statement_id": sid,
    }
    if declared not in KIND_UPGRADABLE_FROM:
        out.update(
            state="not_applicable", kind=declared,
            why=(f"行上的 kind={declared!r} 不是这一格能抬的起点（只抬 conjecture）⇒ "
                 "作者写下的那个名字一个字不动"))
        return out
    try:
        bits = bits_from_row(dict(outer))
        grade = derive_grade(bits, kind=declared)
    except Exception as exc:  # noqa: BLE001 - 算不出来要如实说，不许当成"升了"
        why = (f"五元位算不出来（{type(exc).__name__}: {exc}）⇒ 该不该升判不了"
               "（没判成不是「已经升了」）")
        out.update(checked=False, state="unreadable", kind="conjecture",
                   shortfall=why, why=why)
        return out
    out["grade"] = grade
    if bits.get("voided_by"):
        out.update(shortfall=("这一行已经作废（`bits.voided_by` 非空）⇒ 等级清零，"
                              "kind 不抬：作废的命题不许再叫定理"))
        out["why"] = out["shortfall"]
        return out
    if not bool(bits.get("proof")):
        out.update(shortfall=("第 2 位（proof）还是空的：没有证明过程，V 的签与形式化"
                              "都无从谈起（升档要看这两条凭据里的一条）"))
        out["why"] = out["shortfall"]
        return out
    basis: list[str] = []
    missing: list[str] = []
    sig = _signature_basis(outer, root)
    if sig.get("signed"):
        witness = str(sig.get("ledger") or "")
        vid = str(sig.get("verification_id") or "")
        if vid:
            witness = f"{witness}#{vid}"
        basis.append(f"{witness or 'verifications/（台账）'} 判成立")
    elif not sig.get("checked"):
        missing.append("V 的那一签这一格没查成（没给 root / 台账读不出来）—— "
                       "没查成不是「没签」，补齐 root 再判")
    else:
        missing.append("V 的一签（`verifications/<命题号>.jsonl` 里没有盖住现行正文、"
                       "判「成立」的签）")
    formal_no = _first_verified_path(bits)
    if formal_no:
        basis.append(f"bits.evidence.formal_by_proof[{formal_no}]=verified")
    else:
        missing.append("形式化（`bits.evidence.formal_by_proof` 里没有任何一条 verified）")
    if not basis:
        out.update(shortfall="；".join(missing))
        out["why"] = ("证据不够 ⇒ kind 保持 conjecture（三态：不许折成「已经升了」）："
                      + out["shortfall"])
        return out
    target = "lemma" if str(requested or "").strip() == "lemma" else "theorem"
    if target not in KIND_UPGRADE_TARGETS:          # pragma: no cover - 防御性：目标词表只有两档
        target = "theorem"
    basis_text = "；".join(basis)
    out.update(state="upgraded", kind=target, basis=basis_text,
               why=(f"证据齐 ⇒ kind 跟着等级升：{declared or '（空）'} → {target}"
                    f"（依据：{basis_text}；五元位现算等级 {grade}）"))
    return out


def _first_verified_path(row: Mapping[str, Any]) -> int:
    """第 4 位里第一条 `verified` 的证明号（没有 ⇒ 0）。

    只认 `formal_by_proof` 的逐条读数：`stale`（验过旧稿）与 `pending` / `na` / `failed`
    都不算依据 —— 拿一条"验的不是现在这一份"的读数给名字背书，正是第 4 位那套纪律要堵的。
    """
    per = formal_by_proof(row)
    for no in sorted(per):
        if per[no] == "verified":
            return int(no)
    return 0


def _signature_basis(row: Mapping[str, Any], root: Any) -> dict[str, Any]:
    """V 那一签的读数（`verifications.proof_review_gap` 的结论，纯读）。

    三态：`checked=False` 有两种来路 —— 没给 `root`（这一趟读不到台账）与台账读不出来；
    两种都不许折成"没签"（那会让"没查成"变成一次降级判定）。`signed=True` 只在
    `proof_review_gap` 判 `ok` 时成立（那一签盖住现行正文、判「成立」）。
    """
    if root is None:
        return {"checked": False, "signed": False, "ledger": "",
                "verification_id": "", "why": "这一趟没有工作区根 ⇒ 台账读不了"}
    try:
        from . import verifications as _VR   # 惰性：签名台账的口径只有一处
        gap = _VR.proof_review_gap(root, row)
    except Exception as exc:  # noqa: BLE001 - 台账读不了 ⇒ 没查成（不许当成没签）
        return {"checked": False, "signed": False, "ledger": "",
                "verification_id": "",
                "why": f"`verifications` 台账读不出来（{type(exc).__name__}: {exc}）"}
    return {"checked": bool(gap.get("checked")),
            "signed": bool(gap.get("ok")),
            "ledger": str(gap.get("ledger") or ""),
            "verification_id": str(gap.get("verification_id") or ""),
            "state": str(gap.get("state") or ""),
            "why": str(gap.get("why") or "")}


def bit_problems(bits: Mapping[str, Any]) -> list[str]:
    """五元位自身的完备性问题（空列表 = 合规）。

    三态纪律：`na`（不适用）与 `failed`（做了没通过）都必须写理由/原文；
    `verified` 必须带能复跑的凭据，而且凭据要指名道姓：

    - 第 1 位（数值验证）⇒ 要写清是哪条实验/哪个脚本测的（`experiments` 或 `script`）；
    - 第 4 位（形式化通过）⇒ 要写清是哪个检查器（`checker`）。

    为什么凭据要写到这么细（E3 迁移重放挖出来的，`draft/39` §6.2 五）：p6e 那一趟真的跑过
    两条 `method=formal` 实验，而没有任何命题指向它们 ⇒ "形式化做过"在位上是不可见的。
    位的凭据里若不写"是哪一次实验/哪一个检查器"，同一件事会以"看起来做过"与"查不出来"
    两种形态并存，而这两种在报告里长得一样。

    第 4 位是二维的：状态读汇总（任一路径通过即通过），凭据读逐条 —— 所以
    `formal=verified` 的凭据可以落在 `bits.evidence.formal`（单格，老形态）或
    `bits.evidence.formal_by_proof`（逐条）里，两处都认。
    """
    problems: list[str] = []
    ev = dict(bits.get("evidence") or {})
    formal_per = formal_evidence_by_proof(bits) if isinstance(bits.get(FORMAL_BIT), Mapping) else {}
    for name, key in (("numeric", "numeric"), ("formal", "formal")):
        state = _bit_state(bits, name)
        carried = ev.get(key) or (formal_per if name == "formal" else None)
        if state == "na" and not str(ev.get(f"{key}_reason") or "").strip():
            problems.append(f"{name}=na 必须写理由（为什么这条命题不适合{'数值验证' if name == 'numeric' else '形式化'}）")
        if state == "failed" and not (str(ev.get(f"{key}_reason") or "").strip()
                                      or carried):
            problems.append(f"{name}=failed 必须带原文（脚本/检查器输出）")
        if state == "verified" and not carried:
            problems.append(f"{name}=verified 必须带凭据（脚本 + sha，或检查器输出）")
    if _bit_state(bits, "numeric") == "verified":
        num = dict(ev.get("numeric") or {})
        # 只在"有凭据但凭据没指针"时报这一条：凭据为空时上面那条已经点过名了，
        # 同一件事报两次会让"改哪里"变得不清楚（一条缺陷只留一条可行动的话）。
        if num and not (num.get("experiments") or num.get("experiment_id")
                        or num.get("script") or num.get("scripts")):
            problems.append("numeric=verified 必须写明是哪条实验/哪个脚本测的"
                            "（experiments / experiment_id / script）—— 没有指针的凭据复跑不了")
    if _bit_state(bits, FORMAL_BIT) == "verified":
        # 逐条读：一条路径说 verified，就要有它自己那一格凭据（不许拿别条路径的顶）。
        # 单格形态（老行）读成 `{1: …}`（见 `formal_evidence_by_proof`），所以老行的
        # 行为与改前逐字相同。
        checked = [dict(item) for item in formal_per.values()] or [
            dict(ev.get("formal") or {})]
        for payload in checked:
            if payload and not str(payload.get("checker") or "").strip():
                problems.append("formal=verified 必须写明是哪个检查器（checker：lean4 / coq / isabelle…）")
                break
    if (bits.get("proof") and not str(ev.get("proof_process") or "").strip()
            and ev.get("proof_source") != "citation"):
        problems.append("proof=true 必须带证明过程（逐步论证）")
    if bits.get("reviewed") and not ev.get("reviewed_by"):
        problems.append("reviewed=true 必须带凭据（自己产出 ⇒ V 的三态结论；引用 ⇒ 文献代号）")
    if bits.get("audited") and not ev.get("audited_by"):
        problems.append("audited=true 必须带 H 的审校轮次与结论")
    return problems


#: 五元位 ⇒ 哪张表在维护它（业主 2026-10-09：「再确认一条命题的五元状态是哪张表在维护，
#: 要做好映射（如果五元状态里说有证明，证明应该在 B 维护的表里可查）」）。
#:
#: 每一格四件事：`owner`（谁签的字）/ `ledger`（去哪张表的哪个字段查）/ `pointer`
#: （位里写的那个可追查凭据字段）/ `criteria`（位说 `verified` 时，台账里必须查得到什么）。
#:
#: 为什么要有这张表：位是读数，表是凭据。只说"这一位是 verified"而不说
#: "去哪张表里能查到它"，五元状态就会退化成自报 —— 而"自报不算凭据"正是这套位存在的理由
#: （见 `bits_from_row` 的 docstring）。映射写在这里而不是散在判据里，是为了让
#: "哪一位归哪张表"只有一个出处：`verify.py` 的第 13 段按这张表派判据。
#:
#: 第五位（正式审查）与第三位（审过）的凭据是按稿件钉的（V/H 的审校结论落在稿件上），
#: 所以它们的 `ledger` 是 `documents` 而非命题表：命题这一级只看得见 `doc_id`，
#: "doc_id 存不存在"由 `verify` 的 `dangling_doc_ref` 守。这一格刻意不产生命题级判据 ——
#: 命题没有 `doc_id` 时那一档判不了，报一条假的 error 比不报更糟（会训练人忽略告警）。
BIT_LEDGERS: dict[str, dict[str, str]] = {
    "numeric": {
        "owner": "E",
        "ledger": "experiments（method='numeric'）",
        "pointer": "bits.evidence.numeric 里的 experiment_id / experiments / script",
        "criteria": "位说 verified ⇒ 指针指的那条实验行必须在 experiments 表里，且 method='numeric'",
    },
    "proof": {
        "owner": "F",
        "ledger": "statements.proof_text（B 维护的那张表）",
        "pointer": "命题自己那一行（同表内查，不需要跨表指针）",
        "criteria": "位说 true ⇒ 同行的 proof_text 非空（证明过程逐步可读）；"
                    "引用命题例外（凭据是文献代号 + 逐字核验）",
    },
    "reviewed": {
        "owner": "V",
        "ledger": "documents（V 的审校结论，按稿件钉）",
        "pointer": "doc_id",
        "criteria": "位说 true ⇒ V 的结论挂在稿件上 ⇒ 命题级只查 doc_id 在不在册"
                    "（由 dangling_doc_ref 守）；没有 doc_id ⇒ 判不了，不报",
    },
    "formal": {
        # 2026-10-23：owner 与 `BIT_OWNERS` 那一格同步改成 L（两处必须逐位一致，
        # 判据 `test_the_five_bits_name_their_table` 按位比对它们）。渲染点先读这一栏，
        # 所以「把 E 改成 L」这件事真正的落点在这里；`BIT_OWNERS` 是位表的读数那一栏。
        "owner": "L",
        "ledger": "experiments（method='formal'）",
        "pointer": "bits.formal 的证明号键 + bits.evidence.formal_by_proof[证明号] 里的 "
                   "experiment_id / checker；单格形态读 bits.evidence.formal",
        # 逐路径口径（业主 2026-10-22：「要指明对哪个路径做了形式化验证」）：这一位
        # 一格管一条证明，凭据也按那一条查。汇总那一层（`_bit_state` 的 OR）只回答
        # "这条命题算不算通过"，它不提供凭据 —— 所以 criteria 必须按路径写。
        "criteria": "第 4 位是二维的（{证明号: 状态}）：某个证明号说 verified ⇒ "
                    "那一格凭据（experiment_id / checker）指的实验行必须在 experiments 表里，"
                    "且 method='formal'；汇总按任一路径通过就算通过（等级派生读汇总），"
                    "逐条路径各自独立、不许互相借光",
    },
    "audited": {
        "owner": "H",
        "ledger": "documents（H 的审校轮次与结论，按稿件钉；G 申请）",
        "pointer": "doc_id",
        "criteria": "同第 3 位：命题级判不了，只查稿件在不在册",
    },
}


def bit_ledger(bit: str) -> dict[str, str]:
    """取某一位的台账映射（未知位 ⇒ 空 dict，调用方按"没查成"处理，不按"查过了没问题"）。"""
    return dict(BIT_LEDGERS.get(str(bit), {}))


def formal_ledger_reading(row: Mapping[str, Any], experiments: Iterable[Mapping[str, Any]]
                          ) -> dict[int, dict[str, Any]]:
    """从 `experiments` 台账读第 4 位（写侧唯一的派生点：B 的登记那条路用它）。

    ## 为什么写侧要一个派生函数（D28）
    改前这一位没有任何写者：`bits_of` 把它留成 `pending`，而 L 的 `record` 只写
    `experiments` 那一行（L 的写集里没有 `statements`，那是对的）—— 于是第 4 位恒
    `pending`、等级 `theorem` 从未可达。这一格就是"L 验过什么"与"命题那一行说第 4 位
    是什么"之间的唯一连接：它只读台账，不写任何东西，写盘由 B 的那一笔登记完成
    （规矩与第 3 位一致：位与台账同一次写、逐条落、L 自己不碰 `statements`）。

    ## 判据（一条实验行怎么变成一条路径的状态）
    - 只认 `method="formal"` 且绑到这条命题上的行（`params.statement_id` /
      `observations.statement_id` / `claim_key="stmt:<命题号>"` 三处任一）；
    - 证明号取那一行的 `proof_no`（`observations` 优先，`params` 次之），没写就是
      `#p1`（老行的读法与 `prooflib` 一致）；
    - 状态只认两种：`evidence_kind="proof"`（检查器说通过）⇒ `verified`；
      `tri_state="checked_failed"`（检查器说了不通过）⇒ `failed`。
      其余（unknown：超时 / 没有后端 / 自检不过）一律不写 —— 那是"没查成"，
      写成 `failed` 就把"命题可疑"与"我们没验"折成一件事；
    - 同一路径有多行时后写的盖前面的（台账是追加式的，后一行是更新的读数）。

    ## 返回值
    `{证明号: {"state": …, "payload": {…}}}`，只含台账里真有读数的那几条路径。
    `payload` 是那一格的凭据（checker / experiment_id / proof_sha256 / path_id /
    path_source / code_path / code_hash / tri_state / recorded_by），
    落点是 `bits.evidence.formal_by_proof[证明号]`（见 :data:`FORMAL_BY_PROOF_KEY`）。
    `payload.proof_sha256` 是"这次形式化验的是哪一份证明正文"的指纹：读侧拿它与现行正文
    比，不符就是 `stale`（见 :func:`_stale_formal_cleared`）。
    """
    sid = str(row.get("stmt_id") or row.get("id") or "").strip()
    if not sid:
        return {}
    try:
        from .agent_l._support import STATEMENT_CLAIM_KEY_PREFIX as _PREFIX   # 惰性：口径只有一处
    except Exception:   # noqa: BLE001 - 读不到词表就按正名比（拒写比猜错好，见下面的三道绑定点）
        _PREFIX = "stmt:"
    wanted = f"{_PREFIX}{sid}"
    from . import verifications as _VR   # 惰性：证明号的归一只有一处口径

    found: dict[int, dict[str, Any]] = {}
    for experiment in experiments:
        if not isinstance(experiment, Mapping):
            continue
        if str(experiment.get("method") or "") != "formal":
            continue
        obs = dict(experiment.get("observations") or {})
        params = dict(experiment.get("params") or {})
        bound = {str(obs.get("statement_id") or ""), str(params.get("statement_id") or ""),
                 str(experiment.get("claim_key") or ""),
                 str(experiment.get("verifier_subject_key") or "")}
        if sid not in bound and wanted not in bound:
            continue
        no = _VR.as_proof_no(obs.get("proof_no") or params.get("proof_no")) or 1
        if str(experiment.get("evidence_kind") or "") == "proof":
            state = "verified"
        elif str(obs.get("tri_state") or "") == "checked_failed":
            state = "failed"
        else:
            continue
        found[no] = {
            "state": state,
            "payload": {
                "checker": str(obs.get("checker") or params.get("checker") or ""),
                "experiment_id": str(experiment.get("experiment_id") or ""),
                "proof_no": no,
                "proof_sha256": str(obs.get("proof_sha256")
                                    or params.get("proof_sha256") or ""),
                "path_id": str(obs.get("path_id") or params.get("path_id") or ""),
                "path_source": str(obs.get("path_source")
                                   or params.get("path_source") or ""),
                "code_path": str(experiment.get("code_path") or ""),
                "code_hash": str(experiment.get("code_hash") or ""),
                "tri_state": str(obs.get("tri_state") or ""),
                "recorded_by": str(obs.get("recorded_by") or ""),
                "verified": state == "verified",
            },
        }
    return found


def bit_evidence_gaps(row: Mapping[str, Any], *,
                      experiments: Iterable[Mapping[str, Any]] = (),
                      ) -> list[dict[str, str]]:
    """五元位与它们各自的台账对不对得上（空列表 = 位说的都能在表里查到）。

    只判跨表的那一半（"位说有证明 ⇒ 证明在 B 的表里可查"）：位自身的形状
    （`na` 要理由、`verified` 要凭据）由 `bit_problems` 判，这里不重复。

    三条判据，各守一种病：

    1. `proof` 位为真而 `statements.proof_text` 空（`bits_proof_without_evidence`，error）：
       位上说"有证明"，去 B 维护的那张表里却查不到证明过程 —— 这正是业主点名的形态。
       引用命题（`evidence.proof_source == 'citation'`）不在此列：它的凭据是文献代号
       ＋逐字核验，证明过程在别人的文献里，不在我们的台账里。
    2. 指针指的实验行不存在（`bits_evidence_pointer_dangling`，error）：位里的凭据
       指名道姓写了 `experiment_id`，而 experiments 表里没有这一行 ⇒ 这条凭据复跑不了，
       且"复跑不了"与"跑过"在报告里长得一样。
    3. 指针指的实验行存在但 `method` 不是这一位该有的（`bits_evidence_method_mismatch`，
       warning）：拿一条数值实验当形式化凭据（或反之）—— 三态纪律里这是"查了别的东西"
       而不是"没查"，所以看得见但不拦门。

    边界（三态）：没有指针时不报（`bit_problems` 已经报过"凭据要指名道姓"，
    同一件事报两次会让"改哪里"变得不清楚）；experiments 表读不到时由调用方给空序列，
    此时指针行必然"不存在" —— 所以调用方必须先确认表读到了再判第 2/3 条。

    ## 第 4 位是二维的（逐条路径各自核）
    第 4 位说 `verified` 的是某一条证明（`{证明号: 状态}`）：凭据也要按那一条读
    （`bits.evidence.formal_by_proof[证明号]`），否则一条路径的 `experiment_id` 会被
    拿去给另一条路径背书。汇总那一层（:func:`_bit_state`）只决定"这一位算不算通过"，
    它不提供凭据 —— 所以这一格按路径逐条判，理由串里点名是哪个号。
    """
    bits = bits_from_row(row)
    ev = dict(bits.get("evidence") or {})
    by_exp = {str(e.get("experiment_id") or ""): e for e in experiments}
    gaps: list[dict[str, str]] = []

    if bits.get("proof"):
        text = str(row.get("proof_text") or "").strip()
        cited = str(ev.get("proof_source") or "") == "citation"
        if not text and not cited:
            gaps.append({
                "bit": "proof", "level": "error", "code": "bits_proof_without_evidence",
                "reason": ("第 2 位（有证明）为真，而 statements.proof_text 是空的 ⇒ "
                           "去 B 维护的那张表里查不到证明过程（位上说有、表里没有）；"
                           "要么把证明过程写进 proof_text，要么把这一位降下来"),
            })

    #: 每一位要核的 `(凭据载荷, 路径标签)` 清单：第 1 位一格，第 4 位逐路径。
    formal_evidence = formal_evidence_by_proof(bits)
    formal_states = formal_by_proof(bits) if isinstance(bits.get(FORMAL_BIT), Mapping) else {}
    payloads: list[tuple[str, str, str, dict[str, Any]]] = [
        ("numeric", "numeric", "numeric", dict(ev.get("numeric") or {}))]
    for no in sorted(formal_states):
        if formal_states[no] != "verified":
            continue
        payloads.append(("formal", "formal", f"#{no}", dict(formal_evidence.get(no) or {})))
    if not formal_states:
        payloads.append(("formal", "formal", "formal", dict(ev.get("formal") or {})))

    for bit, method, where, payload in payloads:
        if _bit_state(bits, bit) != "verified":
            continue
        # 指针可能写成单个号（`experiment_id`）或一列号（`experiments`）—— 两种都要认，
        # 而且列要摊平：把整列 `str()` 成一个号，报出来的就是一条查不到的假指针
        # （"0001,0002" 这种号永远不会在表里，负控会以"表里没有"的形态假绿）。
        raw: list[Any] = []
        for cand in (payload.get("experiment_id"), payload.get("experiments"),
                     payload.get("experiment_ids")):
            if isinstance(cand, (list, tuple, set)):
                raw.extend(cand)
            elif str(cand or "").strip():
                raw.append(cand)
        ids = [x for x in dict.fromkeys(str(v) for v in raw) if x]
        for eid in ids:
            hit = by_exp.get(eid)
            if hit is None:
                gaps.append({
                    "bit": bit, "level": "error", "code": "bits_evidence_pointer_dangling",
                    "reason": (f"第 {'1' if bit == 'numeric' else '4'} 位为 verified，凭据指向实验 "
                               f"{eid!r}，而 experiments 表里没有这一行 ⇒ 这条凭据复跑不了"
                               "（台账映射：" + BIT_LEDGERS[bit]["ledger"] + "）"),
                })
                continue
            got = str(hit.get("method") or "")
            if got and got != method:
                gaps.append({
                    "bit": bit, "level": "warning", "code": "bits_evidence_method_mismatch",
                    "reason": (f"第 {'1' if bit == 'numeric' else '4'} 位为 verified，凭据指的实验 "
                               f"{eid!r} 的 method={got!r}（这一位要 method={method!r}）⇒ "
                               "等于拿另一类证据当这一位的凭据"),
                })
    return gaps


def clean_statement_ids(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """I4（`draft/39` §3.21 二）：哪些命题算"干净"的引用对象（引用它不必重验）。

    两类进干净集合，各有明确凭据：

    1. 我方命题：五位派生出「预备定理级」或「正式定理」（第 2 位 + 第 3/4 位）——
       它的证明过程与被审记录都在册，引用它只需如实呈现，不重验；
    2. 引用命题（`origin=external_lit` 且 `quote_verified is True`）：凭据是文献代号 +
       逐字核过的那一份原文 —— 这正是 I4 说的"来源已验证过的，如实呈现、不重验"。

    返回 `{"clean": [...], "reasons": {id: 理由}}`：理由逐条留下（"为什么它能被信"可复核），
    而不在集合里的就是"引用它要小心"的（还在猜想 / 已作废 / 没逐字核过）。
    """
    clean: list[str] = []
    reasons: dict[str, str] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("id") or "")
        if not sid:
            continue
        bits = bits_from_row(row)
        if bits.get("voided_by"):
            reasons[sid] = "已作废（不能作为依据）"
            continue
        if str(bits.get("origin") or "") == "external_lit":
            state = quote_state(row)
            if state in QUOTE_MODES:
                clean.append(sid)
                how = "逐字核过" if state == "verbatim" else "语义核过（H 判：与来源说同一件事）"
                reasons[sid] = f"引用命题：{how}（凭据 lit:{row.get('source_lit_id')}）"
            elif state == QUOTE_NO_EVIDENCE:
                # D1：说通了不算数，盘上要指得出"核的是哪一段"。这一档不给学分 ——
                # 它的"通过"没有位置，复核的人无从下手（真机那 13 行就是这一档）。
                # 两件证据各说一句：逐字档只欠区间，语义档还欠"哪一次判的"。
                reasons[sid] = ("引用命题自称通过，而盘上拿不出可复核的证据（quote_span 为空"
                                "说不出核了哪一段、在第几页；语义档还要求 quote_call_sha256"
                                "说出是哪一次判的）⇒ 不许当依据（D1：证据不在盘上就等于没核）")
            else:
                reasons[sid] = ("引用命题但没核过（逐字与语义两档都没有）"
                                "⇒ 不许当依据（I4 的边界）")
            continue
        if str(row.get("kind") or "") == "concept":
            # 概念行不参与等级（`draft/97` §14.5）⇒ 它当然不在"干净引用对象"里，
            # 但理由必须说对：不是"等级太低"，而是"它不是一条有真值的断言"。
            reasons[sid] = ("概念行（不参与等级）：引用概念要引它的定义，"
                            "而不是把它当定理用")
            continue
        if str(bits.get("grade") or "") in ("pre_theorem", "theorem"):
            clean.append(sid)
            reasons[sid] = (f"我方命题：{GRADE_LABELS.get(str(bits.get('grade')))}"
                            "（第 2 位 + 第 3/4 位）")
        else:
            reasons[sid] = (f"等级只有「{GRADE_LABELS.get(str(bits.get('grade')))}」"
                            "⇒ 引用它要小心")
    return {"clean": clean, "reasons": reasons}


def cascade_void(rows: Iterable[Mapping[str, Any]], *, root: str,
                 reason: str = "") -> dict[str, Any]:
    """I1（级联作废）：一条命题作废 ⇒ 依赖它的那些证明的五位读数一并失效。

    依赖边取自 `derived_from`（本表内的 `stmt_id` 列表：这条命题用到了哪些别的命题）。
    闭包按"谁引用了作废者"逐层扩（A 作废 ⇒ 引 A 的 B 作废 ⇒ 引 B 的 C 作废…），
    每一行的 `voided_by` 里记着 `kind="cascade"` 与根（是谁引起的），
    于是"这一条为什么作废"永远能追到那个数值反例或构造。

    三态与边界：

    - 环（A 引 B、B 引 A）不许把判据卡死：已访问集合挡住，环本身记进 `cycles` 读数；
    - 找不到的引用（引了一条不在册的 id）记进 `missing`，不影响闭包继续
      （悬空引用是另一个缺陷，由别处报）；
    - 根自己那条由调用方按 §3.18 的四条判据先作废（这里不重复判）。

    返回 `{"dependents": [...], "voided_by": {id: 载荷}, "cycles": [...], "missing": [...]}`。
    """
    root_id = str(root or "").strip()
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("id") or "")
        if sid:
            by_id[sid] = row
    if root_id not in by_id:
        return {"dependents": [], "voided_by": {}, "cycles": [], "missing": [root_id],
                "note": "根命题不在这一批行里 ⇒ 级联判不了（没查成，不是「没有依赖」）"}
    importers: dict[str, list[str]] = {}
    missing: list[str] = []
    for sid, row in by_id.items():
        for dep in (row.get("derived_from") or []):
            dep_id = str(dep)
            if dep_id not in by_id:
                missing.append(f"{sid}→{dep_id}")
                continue
            importers.setdefault(dep_id, []).append(sid)
    dependents: list[str] = []
    voided_by: dict[str, Any] = {}
    cycles: list[str] = []
    seen = {root_id}

    def walk(node: str, path: tuple[str, ...], *, depth: int) -> None:
        """按"谁引用了它"往下走；只有回到当前路径上的祖先才算环。

        为什么用路径而不是"已访问"判环（第一版就错在这里）：菱形依赖
        （A←B、A←C、B←D、C←D）里 D 会被访问两次，而它不是环 ——
        用"已访问"会把菱形误报成环。真环的判据是"这条边指回当前这条路径上的某个节点"。
        """
        if depth > 200:                                    # pragma: no cover - 防御性上限
            return
        for imp in importers.get(node, []):
            if imp in path:
                cycles.append(f"{imp}↔{node}")
                continue
            if imp in seen:
                continue
            seen.add(imp)
            dependents.append(imp)
            voided_by[imp] = {"kind": "cascade", "root": root_id, "via": node,
                              "reason": str(reason or
                                            f"依赖的 {node} 已作废 ⇒ 五位一并失效")}
            walk(imp, path + (imp,), depth=depth + 1)

    walk(root_id, (root_id,), depth=0)
    return {"dependents": dependents, "voided_by": voided_by,
            "cycles": sorted(set(cycles)), "missing": sorted(set(missing))}


def apply_cascade(rows: Iterable[Mapping[str, Any]], *, root: str,
                  reason: str = "") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按 `cascade_void` 的结果把行改好（返回 `(改后的行, 读数)`）—— 调用方负责落库。

    只改 `bits.voided_by`（等级由 `derive_grade` 现算 ⇒ 自动回到"猜想"），
    其余字段一个字不动：作废是"读数失效"，不是"把条目删掉或改写内容"。
    """
    got = cascade_void(rows, root=root, reason=reason)
    out: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        sid = str(row.get("stmt_id") or row.get("id") or "")
        mark = got["voided_by"].get(sid)
        if mark:
            bits = dict(row.get("bits") or {})
            bits["voided_by"] = mark
            row["bits"] = bits
        out.append(row)
    return out, got


#: 作废需要的四条（`draft/39` §3.18）：缺一条都不许作废。
VOID_CONDITIONS: tuple[str, ...] = (
    "script_exit_ok", "structured_verdict", "counterexample_present", "counterexample_valid",
)


def void_refusal(experiment: Mapping[str, Any] | None, *,
                 verdict: str = "", counterexample_valid: Any = None) -> str:
    """能不能用这条实验作废命题？返回拒绝理由（空串 = 允许作废）。

    四条同时成立才允许：① 脚本正常退出；② 脚本自己给出结构化结论；
    ③ 反例非空且可复现（脚本 + sha + 参数齐全）；④ 反例确实是这条命题的反例。
    """
    e = dict(experiment or {})
    if e.get("exit_code") not in (0, "0"):
        return "脚本没有正常退出（超时/崩溃 ⇒ inconclusive，不许作废）"
    # 结论要来自脚本自己：台账行里记了 `result` 就以它为准（调用方转述的 `verdict`
    # 只在这一行没记结论时才用）—— 否则"人说 refutes、行说 inconclusive"会被放行。
    stated = _state(e.get("result")) if e.get("result") else _state(verdict)
    if stated != "failed":
        return "脚本没有给出 refutes 的结构化结论（不是它说的，不算）"
    if not e.get("counterexample"):
        return "反例为空 ⇒ 不许作废（脚本报错与命题为假必须分得开）"
    if not (e.get("code_path") and e.get("code_hash")):
        return "反例不可复现（缺 code_path / code_hash）"
    if counterexample_valid is not True:
        return "反例是否成立没有结论（要 D 给'成立/有毛病/看不出来'里的一个）"
    return ""


def void(experiment: Mapping[str, Any], *, verdict: str = "", counterexample_valid: Any = None,
         construction: str = "") -> dict[str, Any]:
    """作废一个命题：返回 `voided_by` 载荷（调用方把它写进台账；五位读数一并作废、条目保留）。"""
    if construction.strip():
        return {"kind": "construction", "construction": construction.strip()}
    reason = void_refusal(experiment, verdict=verdict, counterexample_valid=counterexample_valid)
    if reason:
        raise ValueError(f"不许作废：{reason}")
    e = dict(experiment)
    return {"kind": "numeric_counterexample", "experiment_id": e.get("experiment_id"),
            "script": e.get("code_path"), "sha": e.get("code_hash"),
            "counterexample": e.get("counterexample")}
