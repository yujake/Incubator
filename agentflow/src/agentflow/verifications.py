# -*- coding: utf-8 -*-
"""验证者（V）的证明级审校台账（`draft/39` §3.21 五，用户 2026-10-05 定案）。

五元证据位（§3.14）的第 3 位（"审过"）的 owner 是 V：一个 F 配一个验证者，它把 F 交回来的
证明按写成后的样子整体重读，做三件事（用户点名的 I12/I10/I17）：① I12 冷启动 —— 每次审校开
新会话，只给对象（证明全文）+ 只读查询面的读数，不给 F 的叙述、不给 store 句柄 ⇒ "独立性"
是结构性质而不是一句约定；② I10 硬禁令 + 同段依据 —— 逐条查（无条件前提 / 无依据的步骤 /
"易证、显然、trivial"这类缝 / 引用的命题是否干净），每条问题指到那一步并给理由；③ I17 整篇
重读 —— 把证明当一次输入整体读（"这些缝正是正确的事实变成错误证明的地方"），而不是只逐单元
核对。
## 落点与形态（与手稿同一形态：追加式 JSONL，不新增台账表）
`<工作区>/verifications/<命题号>.jsonl`：一行 = 一次审校，至少要有输入证明的 `sha256`、三态
结论、逐条 findings（每条带步号）、用了哪个只读面、验证者实例名；编号 `v-0001…` 按文件内顺序
发（与手稿编号、台账 id 同一套做法）。
## 三态纪律在这里的落法
`成立` / `有毛病` / `看不出来` 是对证明的三个结论；"检查器自己没跑成"（模型输出不是合法
JSON、字段缺、取值不在词表里）不是这三个之一 —— `record()` 在没有合法结论时抛
`VerificationError`，绝不写一行"看不出来"来冒充"审过了"。签"审过"（§3.21 五）：`verdict="成立"`
且 findings 里没有未解决的 `error` ⇒ `signs_bit3()`，`bit3_payload()` 给出五元位第 3 位那份
读数（`reviewed=True` + 凭据）。
## 「复核过的是哪一份」怎么记（业主 2026-10-22 口径，治那处结构性断链）
签名行记 `(stmt_id, proof_no, proof_sha256)`。`proof_no` 是证明号：`1` = canonical
（缺省，老数据不带它就等价于 `#p1`），`2, 3, …` 是同一条命题的其它证明（见 :data:`PROOFS_KEY`）。
每条证明各自有第 3 位（`reviewed`）：签的是"这一份的每一步站得住"，别的证明不许借光。
判定永远看那条证明现在这一份正文：它的现行 sha 有「成立」那一签 ⇒ `signed`；
签的是旧版 ⇒ `stale`（待复核，第 3 位不计）；被签过、结论不是「成立」⇒ `rejected`；
一次都没签 ⇒ `unsigned`。命题级的定理档 = 在 in-sync 的证明里取最高
（:func:`statement_grade`），一条 in-sync 都没有 ⇒ 猜想。
哈希只回答"这份稿在你签完之后有没有被改过"，它是读数，不是授权凭证：任何写入路径都不因
sha 不符而拒收（`proof_review_gaps` 明确把 `stale` 当成"待复核"这个读数，而不是"没有凭据"）。
签名落盘之后「同一次写」把那条证明的 `reviewed` 翻上去（:func:`sign_statement`）：
先追加台账那一行、再在 `statements` 的事务里改那一行；事务没成就把刚追加的那一行撤回。
逐条证明的第 3 位落在命题行的 `bits.evidence.reviewed_by_proof`（`{"1": true, "2": false}`），
而 `bits.reviewed` 仍是"任一份成立即为 True"的汇总位（老读者只认它）。汇总位要按"任一份
仍 in-sync"读，就必须知道每一签盖住的是哪一份正文 ⇒ 同一次写还落一张 `bits.evidence.
reviewed_sha_by_proof`（`{"1": "<sha256>", "2": ""}`，见 `evidencebits.REVIEWED_SHA_BY_PROOF_KEY`）。
## 老键与老行（兼容，不迁移）
签名行记的三格是 `stmt_id` / `proof_no` / `proof_sha256`。更早的真机行只有
`statement_id`（没有 `stmt_id`），更早的写法还可能把证明号写成 `rev`。读侧认这三对写法：
`stmt_id` 缺 ⇒ 读 `statement_id`；`proof_no` 缺 ⇒ 读 `rev`（见 :func:`proof_no_of`）；
两个都没有 ⇒ `#p1`（缺省证明号，见 `proofloc`）。写侧只写正名 —— 迁移要重写历史台账，
而兼容只需要一行读法，且不会把"谁在什么时候签的"改成"我们改写过它"。
## 引用核实（业主 2026-10-26：V 要核 F 的引用，而 F 的引用不是逐字引文）
F 在 `dependencies` 上登记"这一份证明用到哪条在册命题"（`used_by` / `path_group` /
`source_stmt_id` / 那一行的人话）。那是自然语言描述（"由引理 2"、"由 Sylow I 可知"），
不是逐字引文 ⇒ 只把编号交给 V 没有用，V 必须看到两样东西：F 是怎么说的、被引命题真正
说的是什么（:func:`citation_material` 把两边一起取出来，正文摘要一起进提示词）。
V 逐条给一档结论（:data:`CITATION_VERDICTS`：`consistent` / `weaker` / `stronger` /
`unrelated` / `inadmissible` / `unknown`），读数是 `citation_checks` 那四格
（:data:`CITATION_CHECK_KEYS`），随台账那一行落盘。签字前置（:func:`signs_bit3`）：
只要有一条 `stronger` / `unrelated` / `inadmissible` / `unknown`，这一签就不许落地
（:func:`citation_gate` 点名是哪一条、差在哪）；`weaker` 可以签，但读数里点名"只用到了
弱形式"；档位不够格（低于 `proof_review`，业主逐字「proof_review级及以上才可引用」）
是事实而不是判断，由 :func:`evidence_kind_admissible` 从 `schema.EVIDENCE_KINDS` 现算。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import jsonlfile as JF
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）
from . import statementbody as _SB  # 命题正文的唯一读口（被引命题的正文从这里取）
from . import textutil as T  # 引用解析的唯一实现（`citation_ref_parts`，`P-5`）
from .proofloc import DEFAULT_PROOF_NO  # canonical 证明号只有一个出处（`proofloc`）

#: 验证台账目录（工作区根下）。
VERIFICATIONS_DIR = "verifications"
#: 三态结论（顺序就是从"站不住"到"站得住"；`看不出来` 不是 `成立`）。
VERDICTS: tuple[str, ...] = ("有毛病", "看不出来", "成立")
#: findings 的级别（与 `schema.FINDING_LEVELS` 同词表）。
FINDING_LEVELS: tuple[str, ...] = ("error", "warning", "info")
#: 硬禁令的清单（I10 的最小形态）：命中这些短语的步骤必须被指出来。
#: 用户 2026-10-05 口径："F 禁止写'易证/显然/trivial/clearly/it is easy to see'"。
HARD_BAN_MARKERS: tuple[str, ...] = (
    "易证", "显然", "trivial", "clearly", "it is easy to see", "无须证明", "显然成立",
)
#: 一次审校至少要交代的四件事（缺一就不是"审过了"）。
REQUIRED_FIELDS: tuple[str, ...] = ("verdict", "statement_id", "proof_sha256")

#: 引用核实的档位结论（业主 2026-10-26 裁定，两批）。
#:
#: 口径逐字：「正常写证明就是不会逐字的」、「proof_review级及以上才可引用」。所以判据不是
#: "字面像不像"，而是"F 对这一条被引命题的用法成不成立、以及这一条够不够格被引" ——
#: 改写、压缩、换符号都合法，只要条件与结论没被换掉：
#:
#: - `consistent`：F 的用法与这条命题真正说的条件/结论一致（措辞当然可以不同）；
#: - `weaker`：F 只用到了它的弱形式（不等于错，是情报；可以签，但读数里点名）；
#: - `stronger`：F 用到的结论比命题本身更强（引用被夸大，或悄悄去掉了它要的假设）；
#: - `unrelated`：这条命题与这一步无关（引错了）；
#: - `inadmissible`：被引命题的档位低于 `proof_review`（`cross_check` / `heuristic` / 空）
#:   ⇒ 它不够格被当作依据引（不管用法一致不一致）；
#: - `unknown`：V 判不了（材料不足 / 被引命题不在册）；它不是 `consistent`。
CITATION_VERDICTS: tuple[str, ...] = (
    "consistent", "weaker", "stronger", "unrelated", "inadmissible", "unknown",
)
#: 能签「成立」的两档：弱形式不是错。`weaker` 会被点名，但它不挡签字。
CITATION_SIGNABLE: frozenset[str] = frozenset(("consistent", "weaker"))
#: 挡住「成立」的四档（逐条点名是哪一条、差在哪）。`unknown` 也在里面：判不了不是一致；
#: `inadmissible` 也在里面：档位不够不是"用法对不对"能救的。
CITATION_BLOCKING: frozenset[str] = frozenset(
    ("stronger", "unrelated", "inadmissible", "unknown"))
#: 一条核实读数落盘时的四格。`quote_verbatim` 只是信息（F 那句话是不是逐字抄的），
#: 它不参与判定 —— 业主裁定"逐字"不能当标准，写证明不会逐字引。
CITATION_CHECK_KEYS: tuple[str, ...] = ("stmt_id", "verdict", "quote_verbatim", "note")
#: 进 V 的审查材料的"被引命题正文摘要"长度上界（正文本身留在 `citations` 的全文格里）。
CITATION_DIGEST_CHARS = 600
#: 依赖行上"F 为什么这么引"那句话的候选键（按优先级取第一个非空；`note` 是正名，
#: 老写法把话写在 `label` / `quote` / `status_reason` 里，所以那几个也认）。
DEP_NOTE_KEYS: tuple[str, ...] = ("note", "label", "quote", "status_reason")

#: 被引命题的档位下限（业主 2026-10-26 逐字：「proof_review级及以上才可引用」）。
#:
#: 为什么只写这一档的名字、不写允许清单：`schema.EVIDENCE_KINDS` 是"从强到弱"排的
#: （`proof` / `proof_review` / `cross_check` / `heuristic`），所以允许集合是它的前缀
#: （:func:`admissible_evidence_kinds` 现算）。在同一处再抄一份字面量清单，等于给这条
#: 口径造第二个真身 —— 词表加一档（例如将来插一个"审过 + 机器部分核"）时，两边会分家，
#: 而没有任何东西会报。
CITATION_EVIDENCE_FLOOR = "proof_review"


def admissible_evidence_kinds() -> tuple[str, ...]:
    """够格被引的档位（按 `schema.EVIDENCE_KINDS` 的强弱顺序现算，不抄字面量）。

    词表读不到 / 里面没有下限那一档 ⇒ 返回空元组（"判不了"）：空集会让每一条引用都判
    `inadmissible`，那是可见的失败；反过来在词表坏掉时放行，就是"没查成"折成"通过"。
    """
    kinds = tuple(getattr(S, "EVIDENCE_KINDS", ()) or ())
    if CITATION_EVIDENCE_FLOOR not in kinds:
        return ()
    return kinds[: kinds.index(CITATION_EVIDENCE_FLOOR) + 1]


def evidence_kind_admissible(kind: Any) -> bool:
    """这一档够不够格被引（空串 —— 没有档位 —— 不够格）。"""
    return str(kind or "").strip() in admissible_evidence_kinds()


def dep_note(row: Mapping[str, Any]) -> tuple[str, str]:
    """依赖行上 F 写的那句话，返回 `(文本, 它出自哪个键)`（都空 ⇒ `("", "")`）。

    为什么认几个键而不是一个：`dependencies` 行的正名里没有 `note`（`schema.Dependency`
    是禁改区），F 侧的说明可能落在 `label`（人话标签）、`quote`（引文原话）或
    `status_reason`（为什么是那个状态）里。三处都读、并把出处键一起交出去，
    读的人才知道那句话是"标签"还是"引文原话"；只读一个键会让另一种写法静默丢掉。
    """
    for key in DEP_NOTE_KEYS:
        text = str(row.get(key) or "").strip()
        if text:
            return text, key
    return "", ""


def _digest(text: str, limit: int = CITATION_DIGEST_CHARS) -> str:
    """正文摘要（进提示词的那一份）：超长时截断并留一句"以下截断"。"""
    body = str(text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit].rstrip() + f"……（以下截断，全文共 {len(body)} 字）"


def citation_material(*, statement_id: str, proof_no: Any = None,
                      deps: Iterable[Mapping[str, Any]] = (),
                      statements: Iterable[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """V 的引用核实材料：这条命题第 `proof_no` 份证明登记的依赖行 + 每条被引命题的正文。

    一条被引命题（`source_stmt_id`）一项，同一命题在不同 `path_group` 下登记两次也合成
    一项（组号逐条列在 `path_groups` 里）：V 要对"这条被引命题"给一次结论，不是对
    "这一次引用"给一次。

    返回项（键集合固定，读的人不必猜）：
    `stmt_id`（被引命题号）/ `paths`（每个 `path_group` 一条，含 `dep_id` / `used_by` /
    `path_group` / `note` / `note_source` / `status` / `label` / `quote`）/
    `path_groups` / `dep_ids` / `statement_full`（被引命题正文，不在册 ⇒ 空串）/
    `statement_digest`（进提示词的摘要）/ `statement_missing` / `statement_label` /
    `evidence_kind`（被引命题现在的档位；不在册 ⇒ 空串）/ `admissible`（这一档够不够格
    被引，业主口径「proof_review级及以上才可引用」；判据 :func:`evidence_kind_admissible`）。

    三态：`statement_missing=True` 说的是"册子里没有这条命题"，不是"它没有正文" ——
    两者在读数上必须分得开（前者只判得了 `unknown`）。

    只收 `used_by` 指向本条命题、且证明号等于 `proof_no` 的依赖行：`#p2` 的依赖不进
    `#p1` 的审查材料（借光/串份是这一格要防的事）；`used_by` 的尾巴读不懂（`#pabc` 之类）
    也不静默折成 canonical，直接不算这一份的依赖（原串仍留在依赖台账里，由 C 那条链点名）。
    """
    from . import proofloc as _PL   # 依赖尾巴的唯一解析点

    sid = str(statement_id or "").strip()
    want = _read_proof_no(proof_no) or DEFAULT_PROOF_NO
    bodies = {str(r.get("stmt_id") or ""): r for r in statements}
    grouped: dict[str, dict[str, Any]] = {}
    for row in deps:
        head, no, problem = _PL.parse_used_by_checked(str(row.get("used_by") or ""))
        if problem:
            continue
        if str(head).strip() not in (f"stmt:{sid}", sid):
            continue
        if no != want:
            continue
        cited = str(row.get("source_stmt_id") or "").strip()
        if not cited:
            continue
        note, note_source = dep_note(row)
        item = grouped.setdefault(cited, {
            "stmt_id": cited, "paths": [], "path_groups": [], "dep_ids": [],
            "statement_full": "", "statement_digest": "", "statement_missing": False,
            "statement_label": "", "evidence_kind": "", "admissible": False,
        })
        group = int(row.get("path_group") or 1)
        item["paths"].append({
            "dep_id": str(row.get("dep_id") or ""),
            "used_by": str(row.get("used_by") or ""),
            "path_group": group,
            "note": note, "note_source": note_source,
            "status": str(row.get("status") or ""),
            "label": str(row.get("label") or ""),
            "quote": str(row.get("quote") or ""),
        })
        if group not in item["path_groups"]:
            item["path_groups"].append(group)
        if str(row.get("dep_id") or ""):
            item["dep_ids"].append(str(row.get("dep_id") or ""))
    out = list(grouped.values())
    for item in out:
        hit = bodies.get(item["stmt_id"])
        body = _SB.body_of(hit) if hit is not None else ""
        item["statement_full"] = body
        item["statement_digest"] = _digest(body) if hit is not None else ""
        item["statement_missing"] = hit is None
        item["statement_label"] = str((hit or {}).get("label") or "")
        item["evidence_kind"] = str((hit or {}).get("evidence_kind") or "")
        # 档位判据的缺省答案在这里算一次（`agent_v` 会用自己的缝再盖一次：
        # 那是可打桩的那一格，判据 b 的反真空就打在它上面）。
        item["admissible"] = evidence_kind_admissible(item["evidence_kind"])
        item["path_groups"] = sorted(item["path_groups"])
    out.sort(key=lambda it: (it["stmt_id"], it["path_groups"]))
    return out


def _citation_checks_raw(raw: Any) -> list[dict[str, Any]]:
    """把 V 输出里的 `citation_checks` 洗成规整的四格；形状不对 ⇒ 抛 `VerificationError`。

    它是"没查成"那一档：`verdict` 不在词表里 / `stmt_id` 不是命题号形态，
    都不是"这一条判成什么"，而是这一次输出不可解析 —— 不许折成 `unknown`
    （`unknown` 是一条诚实的结论，而坏输出不是）。
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise VerificationError("citation_checks 必须是数组（每条被引命题一项）")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, Mapping):
            raise VerificationError(f"citation_checks 第 {i} 项必须是对象")
        sid = str(item.get("stmt_id") or "").strip()
        if not S.is_valid_id(sid):
            raise VerificationError(
                f"citation_checks 第 {i} 项的 stmt_id 不是命题号形态（收到 {sid!r}）"
                f"：它必须是被引命题的 {S.ID_DIGITS} 位号（旧四位号仍可读）")
        verdict = str(item.get("verdict") or "").strip()
        if verdict not in CITATION_VERDICTS:
            raise VerificationError(
                f"citation_checks 第 {i} 项的 verdict 必须是 {CITATION_VERDICTS} 之一，"
                f"收到 {verdict!r}")
        flagged = item.get("quote_verbatim")
        if isinstance(flagged, str):
            verbatim = flagged.strip().lower() in ("1", "true", "yes", "y", "是", "逐字")
        else:
            verbatim = bool(flagged)
        out.append({
            "stmt_id": sid, "verdict": verdict, "quote_verbatim": verbatim,
            "note": str(item.get("note") or "").strip(),
        })
    return out


def reconcile_citation_checks(checks: Sequence[Mapping[str, Any]],
                             material: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把 V 给的那几条结论与"材料里有哪几条被引命题"对齐（缺一条就按 `unknown` 算）。

    四条规矩，都是三态纪律在这一格上的落法：
    - 材料里每一条被引命题都必须有一条结论；V 没给 ⇒ 补一条 `unknown`
      （note 写明"没有给出结论"）。判不了与没判是两件事，但两者都不能签「成立」；
    - 被引命题的档位不够格（`evidence_kind` 低于 `proof_review`，含空串）⇒ 一律改判
      `inadmissible`，不管 V 判的是"用法一致"还是别的。这一档是事实而不是判断：
      业主口径逐字「proof_review级及以上才可引用」，所以它不交给模型自由裁量（模型说
      `consistent` 也照样改判，原文附在 note 里）。判据本体是
      :func:`evidence_kind_admissible`（禁止词表从 `schema.EVIDENCE_KINDS` 现算）；
    - 被引命题不在册（`statement_missing`）⇒ 若 V 写了 `consistent` / `weaker`，
      改判 `unknown`（它读不到的那条命题，判不了"一致"；这一格不许凭印象签字）；
    - V 多给的（材料里没有那条被引命题）仍然交回去，但标 `in_material=False`：
      它不是这一份证明登记的引用，不计入挡不挡签字（挡签字只认材料里的那几条）。
    """
    by_id: dict[str, dict[str, Any]] = {}
    for chk in checks:
        row = {key: chk.get(key) for key in CITATION_CHECK_KEYS}
        row["stmt_id"] = str(row.get("stmt_id") or "").strip()
        row["verdict"] = str(row.get("verdict") or "unknown").strip()
        row["quote_verbatim"] = bool(row.get("quote_verbatim"))
        row["note"] = str(row.get("note") or "").strip()
        by_id.setdefault(row["stmt_id"], row)
    out: list[dict[str, Any]] = []
    for item in material:
        sid = str(item.get("stmt_id") or "")
        got = by_id.pop(sid, None)
        if got is None:
            got = {"stmt_id": sid, "verdict": "unknown", "quote_verbatim": False,
                   "note": "V 没有对这条被引命题给出结论（材料里有它）"}
        kind = str(item.get("evidence_kind") or "")
        # 先判"这一条在不在册"（它比档位更根本：不在册的命题连档位都没有），
        # 再判档位 —— 两档都是挡签的，但点名要说清是哪一种。
        if bool(item.get("statement_missing")) and got["verdict"] in CITATION_SIGNABLE:
            got = dict(got, verdict="unknown",
                       note=(f"被引命题 {sid} 不在册 ⇒ 判不了「一致」"
                             f"（V 原文：{got['note'] or '（无）'}）"))
        admitted = item.get("admissible")
        if admitted is None:
            admitted = evidence_kind_admissible(kind)
        if not bool(item.get("statement_missing")) and not admitted:
            tail = f"（V 原文：{got['note']}）" if got["note"] else ""
            got = dict(got, verdict="inadmissible",
                       note=(f"被引命题 {sid} 现在只是 {kind or '（空：没有档位）'}，"
                             f"够不上 {CITATION_EVIDENCE_FLOOR} 级 ⇒ 不够格被引{tail}"))
        out.append(dict(got, in_material=True))
    for sid, got in by_id.items():
        out.append(dict(got, in_material=False))
    return out


def citation_gate(checks: Sequence[Mapping[str, Any]], *, problem: str = "") -> dict[str, Any]:
    """引用核实的签字前置读数（纯函数）：能不能签「成立」，被哪一条挡住。

    返回 `ok` / `blocking` / `weaker` / `problem` / `why`。`blocking` 与 `weaker` 里每项
    是 `{stmt_id, verdict, note}`（点名用）。`problem` 非空是"这一档没查成"（依赖台账
    读不出来）—— 它与"核过、没有引用"必须分开，所以它也挡住签字。
    """
    blocking: list[dict[str, Any]] = []
    weaker: list[dict[str, Any]] = []
    for chk in checks:
        # 材料之外的那几条（V 多给的）不计入签字前置：它们不是这一份证明登记的引用。
        if chk.get("in_material") is False:
            continue
        verdict = str(chk.get("verdict") or "")
        entry = {"stmt_id": str(chk.get("stmt_id") or ""), "verdict": verdict,
                 "note": str(chk.get("note") or "")}
        if verdict in CITATION_BLOCKING:
            blocking.append(entry)
        elif verdict in CITATION_SIGNABLE and verdict != "consistent":
            weaker.append(entry)
    why = ""
    if problem:
        why = (f"引用核实没查成（{problem}）⇒ 这一份不能判「成立」"
               "（没查成不是「核过、一致」）")
    elif blocking:
        shown = "；".join(
            f"{e['stmt_id'] or '（没有号）'} 判 {e['verdict']}"
            + (f"（{e['note']}）" if e["note"] else "")
            for e in blocking)
        why = (f"引用核实挡下了「成立」：{shown} —— "
               "stronger 是引用被夸大、unrelated 是引错了、"
               f"inadmissible 是被引命题的档位低于 {CITATION_EVIDENCE_FLOOR}（不够格被引）、"
               "unknown 是判不了，四档都不许签")
    elif weaker:
        shown = "；".join(
            f"{e['stmt_id'] or '（没有号）'}" + (f"（{e['note']}）" if e["note"] else "")
            for e in weaker)
        why = (f"引用核实通过，但有 {len(weaker)} 条只用到了弱形式：{shown} —— "
               "弱形式不是错，记下来给读的人一句情报")
    return {"ok": not blocking and not problem, "blocking": blocking, "weaker": weaker,
            "problem": str(problem or ""), "why": why}


def citation_blocks(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """这一签里挡住「成立」的引用核实条目（空列表 = 没有被挡）。

    `signs_bit3` 用它：台账那一行写着 `成立`、而引用核实里有一条 `stronger` /
    `unrelated` / `unknown` ⇒ 这一签不许落地。硬闸放在这里（而不是只放在写路径上），
    因为"手写一条成立行"与"V 自己判了成立"在读者眼里没有区别。
    """
    checks = row.get("citation_checks")
    if not isinstance(checks, (list, tuple)):
        return []
    return [{"stmt_id": str(c.get("stmt_id") or ""), "verdict": str(c.get("verdict") or ""),
             "note": str(c.get("note") or "")}
            for c in checks if isinstance(c, Mapping)
            and str(c.get("verdict") or "") in CITATION_BLOCKING]


def apply_citation_gate(verdict: Mapping[str, Any],
                        gate: Mapping[str, Any]) -> dict[str, Any]:
    """把引用核实的结论并进 V 的结论（纯函数：`parse_verdict` 的形态进、同一形态出）。

    三档处置（业主 2026-10-26 的签字前置）：
    - 有 `stronger` / `unrelated` / `inadmissible` ⇒ 不许判「成立」：结论改判「有毛病」，
      逐条 error 落进 findings（点明哪一条被引命题、差在哪）。这就是受控拒绝：这一签
      签不成，而"为什么签不成"在台账里逐字可读；
    - 只有 `unknown` ⇒ 改判「看不出来」（判不了不是一致，也不是"有毛病"：它是一条
      诚实的未定）；
    - 只有 `weaker` ⇒ 结论不动（可签），但加一条 info 把"这一步只用到弱形式"记下来；
    - `gate["problem"]` 非空（依赖台账读不出来 ⇒ 这一档没查成）⇒ 与挡签同档：结论
      从「成立」改判「看不出来」（`blocking` 里有实档才改「有毛病」）。它是"没查成"，
      不是"没有引用"：改前只看 `blocking`，于是 `problem` 非空 + `citation_checks`
      空时这一签照样判「成立」—— 那正是把"没查成"折成"没有引用"。

    改判时 `defect_step` 保留模型给的那一步（它可能仍是承重步）；模型没给就留 `None` ——
    这一档的缺陷是按"被引命题"定位的，不是按步号定位的（`parse_verdict` 因此允许
    "有毛病 + 有挡签的引用核实 + 没有步号"这一种组合）。
    """
    out = {
        "verdict": str(verdict.get("verdict") or ""),
        "defect_step": verdict.get("defect_step"),
        "quote": str(verdict.get("quote") or ""),
        "why": str(verdict.get("why") or ""),
        "findings": [dict(f) for f in (verdict.get("findings") or [])],
        "unresolved_errors": 0,
        "citation_checks": [dict(c) for c in (verdict.get("citation_checks") or [])],
    }
    blocking = list(gate.get("blocking") or [])
    defect = [e for e in blocking if str(e.get("verdict") or "") != "unknown"]
    for entry in blocking:
        kind = f"citation_{entry.get('verdict') or 'unknown'}"
        tail = f"：{entry['note']}" if entry.get("note") else ""
        sid = entry.get("stmt_id") or "（没有号）"
        verdict_text = str(entry.get("verdict") or "")
        if verdict_text == "unknown":
            detail = (f"引用核实：被引命题 {sid} 判不了（unknown）{tail}"
                      "；判不了不是一致 ⇒ 这一份不能判「成立」")
        elif verdict_text == "inadmissible":
            detail = (f"引用核实：被引命题 {sid} 的档位够不上 {CITATION_EVIDENCE_FLOOR}{tail}"
                      "；档位不够格是事实，与原文一致不一致无关 ⇒ 这一份不能判「成立」")
        else:
            detail = (f"引用核实：被引命题 {sid} 判 {verdict_text}"
                      f"{tail or '：V 没有写理由'}"
                      "；这一条使这一份不能判「成立」")
        out["findings"].append({"level": "error", "step": None, "kind": kind,
                                "detail": detail})
    for entry in (gate.get("weaker") or []):
        tail = f"（{entry['note']}）" if entry.get("note") else ""
        out["findings"].append({
            "level": "info", "step": None, "kind": "citation_weaker",
            "detail": (f"引用核实：这一步只用到了被引命题 "
                       f"{entry.get('stmt_id') or '（没有号）'} 的弱形式{tail}"
                       "；不等于错，但读的人要知道它没有被用满"),
        })
    if (blocking or gate.get("problem")) and out["verdict"] == "成立":
        out["verdict"] = "有毛病" if defect else "看不出来"
        if out["verdict"] == "看不出来":
            out["defect_step"] = None
    if blocking or gate.get("problem"):
        gate_why = str(gate.get("why") or "")
        if gate_why:
            out["why"] = (out["why"] + "；" + gate_why) if out["why"] else gate_why
    out["unresolved_errors"] = sum(1 for f in out["findings"] if f.get("level") == "error")
    return out


class VerificationError(ValueError):
    """这次审校没查成（不是"有毛病"）：输出不合法、字段缺、取值不在词表里。"""


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def verifications_dir(root: str | Path) -> Path:
    """验证台账目录（工作区根下的 `verifications/`；只算路径，不建目录）。"""
    return Path(root) / VERIFICATIONS_DIR


def verification_ledger_path(root: str | Path, statement_id: str) -> Path:
    """一个命题一份台账：`verifications/<命题号>.jsonl`。

    命题号的形态判据只有一处：`schema.is_valid_id`（当前宽度六位，旧数据四位读侧兼容）——
    2026-10-14 之前这里自己写死了"恰好 4 位"，宽度一改就会把新号当场拒掉。
    """
    sid = str(statement_id or "").strip()
    if not S.is_valid_id(sid):
        raise VerificationError(
            f"命题号必须是 {S.ID_DIGITS} 位十进制字符串（旧数据里的 4 位号仍可读），"
            f"收到 {statement_id!r}")
    return verifications_dir(root) / f"{sid}.jsonl"


#: 「命题还没在册时审的那一签」落在哪：`verifications/pending/<sha>.jsonl`（D-34）。
#:
#: 为什么单独一个子目录（而不是塞进 `verifications/` 顶层）：顶层那一层是"每个命题一份台账"，
#: `list_verifications` 与收工门 R10 都按顶层 `*.jsonl` 逐个命题读 —— 混进一份没有命题号的
#: 台账会让那些读法把一行"还不属于任何命题"的签算到某个命题头上。子目录不进那条 glob，
#: 而认领它的入口只有一个：:func:`pending_sign`（按对象内容的 sha）。
PENDING_DIR_NAME = "pending"
#: pending 台账里那一行的编号前缀（`u-NNNNNN`：u = 未登记）。
PENDING_PREFIX = "u-"


def pending_dir(root: str | Path) -> Path:
    """pending 台账的目录（只算路径，不建目录）。"""
    return verifications_dir(root) / PENDING_DIR_NAME


def pending_ledger_path(root: str | Path, key: str) -> Path:
    """一份 pending 台账：`verifications/pending/<内容 sha>.jsonl`（按对象内容分文件）。"""
    text = str(key or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise VerificationError(
            "pending 台账的文件名必须是 64 位十六进制的 sha256（按对象内容分文件），"
            f"收到 {key!r}")
    return pending_dir(root) / f"{text}.jsonl"


def record_pending_sign(root: str | Path, *, proof_text: str, verdict: Mapping[str, Any],
                        verifier: str = "V", object_sha256: Any = "",
                        object_path: Any = "") -> dict[str, Any]:
    """把"命题还没在册时"的一次审校落进 pending 台账，返回那一行。

    为什么要这一格（D-34，r34b 的真机现场）：V 审完判「成立」，而 `statements` 是 0 行 ——
    `record_verification` 要一个合法命题号才写得出 `verifications/<号>.jsonl`，于是那一签
    没有落点，结论只能 escalation 掉。结论丢了不是"没审"，是"审了没处记"。

    落点按对象内容的 sha 分文件：`object_sha256`（那份报告 / 证明文件的字节 sha256）给了
    就用它，没给就退到证明正文的 sha（`proof_sha256`）。两个 sha 都写进行里，所以 B 后来
    认领时按哪一个都找得到（"顺序不再重要"）。

    结论一样要过 `parse_verdict`（`有毛病` 必须给 `defect_step`）：坏结论不许落盘。
    引用核实那一格（`citation_checks`）随同一行落盘，形状与 `record_verification` 逐格相同。
    """
    checked = parse_verdict(json.dumps({"verdict": verdict.get("verdict"),
                                        "defect_step": verdict.get("defect_step"),
                                        "quote": verdict.get("quote", ""),
                                        "why": verdict.get("why", ""),
                                        "findings": list(verdict.get("findings") or []),
                                        "citation_checks": list(verdict.get("citation_checks") or [])},
                                       ensure_ascii=False, default=str))
    text = str(proof_text or "")
    sha = proof_sha(text)
    obj = str(object_sha256 or "").strip().lower()
    key = obj or sha
    path = pending_ledger_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, problems = JF.read_jsonl(path)
    if problems:
        raise VerificationError(f"pending 台账有读不出来的行：{problems[:3]}")
    row = {
        "verification_id": f"{PENDING_PREFIX}{S.format_id(len(rows) + 1)}",
        # 没有命题号是这一档的定义（命题还没在册）：两个键都留空串而不是缺键 ——
        # 读的人要能分辨"这一行不属于任何命题"与"这一行是旧格式、没有这个键"。
        "statement_id": "", "stmt_id": "",
        "proof_no": int(DEFAULT_PROOF_NO),
        "verifier": str(verifier or "V"), "verdict": checked["verdict"],
        "defect_step": checked["defect_step"], "quote": checked["quote"],
        "why": checked["why"], "findings": checked["findings"],
        "unresolved_errors": checked["unresolved_errors"],
        "citation_checks": list(checked.get("citation_checks") or []),
        "proof_sha256": sha, "proof_chars": len(text),
        #: 对象（盘上那一份报告 / 证明文件）的字节 sha256 与相对路径：认领时按它。
        "object_sha256": obj, "object_path": str(object_path or "").strip().replace("\\", "/"),
        "round": len(rows) + 1, "used_faces": [], "submission_id": "",
        "landed": "pending", "at": _now_iso(),
    }
    _append_verification(path, row)
    return row


def pending_rows(root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """pending 台账的全部行（按落盘顺序；坏行照实报出，不静默跳过）。"""
    base = pending_dir(root)
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    if not base.is_dir():
        return out, problems
    for file in sorted(base.glob("*.jsonl")):
        rows, bad = JF.read_jsonl(file)
        problems.extend(f"{PENDING_DIR_NAME}/{file.name}: {b}" for b in bad)
        out.extend(rows)
    return out, problems


def pending_sign(root: str | Path, *, object_sha256: Any = "",
                 proof_shas: Sequence[str] = ()) -> dict[str, Any]:
    """按对象内容的 sha 认领 pending 台账里的那一签（最近一次审校说了算）。

    返回 `{"found","verdict","proof_sha256","object_sha256","ledger","why"}`。
    `found=False` 只表示"pending 里没有盖住这一份的签"，不是"没查成"；
    读不出来时才抛 `VerificationError`（三态：没查成不许折成没有签）。
    """
    out: dict[str, Any] = {"found": False, "verdict": "", "proof_sha256": "",
                           "object_sha256": "", "ledger": "", "why": ""}
    obj = str(object_sha256 or "").strip().lower()
    wants = {str(s or "").strip().lower() for s in (proof_shas or ()) if str(s or "").strip()}
    rows, problems = pending_rows(root)
    if problems:
        raise VerificationError("；".join(problems[:3]))
    hit: dict[str, Any] | None = None
    for row in rows:
        got_obj = str(row.get("object_sha256") or "").strip().lower()
        got_proof = str(row.get("proof_sha256") or "").strip().lower()
        if obj:
            if got_obj != obj:
                continue
        elif wants:
            if got_proof not in wants:
                continue
        else:
            continue
        hit = row
    if hit is None:
        where = (f"对象 sha256 {obj[:12]}…" if obj else f"证明正文 sha {sorted(wants)[:1]}")
        out["why"] = (f"`{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/` 里没有盖住这一份"
                      f"（{where}）的签 —— 命题还没在册时 V 也没审过它")
        return out
    out.update(found=True, verdict=str(hit.get("verdict") or ""),
               proof_sha256=str(hit.get("proof_sha256") or ""),
               object_sha256=str(hit.get("object_sha256") or ""),
               ledger=(f"{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/"
                       f"{str(hit.get('object_sha256') or hit.get('proof_sha256') or '')[:64]}"
                       f".jsonl#{hit.get('verification_id') or '?'}"))
    out["why"] = (f"{out['ledger']} 是按对象内容 sha 认领到的那一签，"
                  f"verdict={out['verdict']!r}")
    return out


def citations_block(citations: Sequence[Mapping[str, Any]],
                    problem: str = "") -> str:
    """引用核实那一节怎么印进提示词（纯字符串拼装，只有材料、没有句柄）。

    业主 2026-10-26：F 的"引用"是自然语言描述，不是逐字引文 ⇒ 光给编号没有用，
    V 要看到"F 是怎么说的"与"被引命题真正说的"两样东西才能判它成不成立。
    所以每一条都印三样：F 那句话（含它出自依赖行哪个键）、被引命题正文摘要、
    被引命题现在的档位（够不够格被引）。
    """
    lines: list[str] = ["## 引用核实（F 在依赖面登记的引用；逐条核 F 是不是这么用的）"]
    if problem:
        lines.append(f"- 依赖台账读不出来（{problem}）⇒ 这一档没查成：没有材料就不能判"
                     "「一致」，判不了就写 unknown（它挡住「成立」）。")
    if not citations:
        if not problem:
            lines.append("- 这一份证明没有登记任何被引命题（`dependencies` 里没有指向本条命题"
                         "这一份证明的 `stmt:` 依赖）⇒ `citation_checks` 给空数组。")
        else:
            lines.append("- 材料读不到时不许说「这一份证明没有引用」：那是把「没查成」说成"
                         "「核过、没有引用」。")
        return "\n".join(lines)
    lines.append(f"- 登记了 {len(citations)} 条被引命题。每一条都要给一档结论："
                 "少给一条就按 unknown 算，而 unknown 挡住「成立」。")
    for i, item in enumerate(citations, 1):
        sid = str(item.get("stmt_id") or "")
        groups = "、".join(str(g) for g in (item.get("path_groups") or [])) or "1"
        lines.append("")
        lines.append(f"### {i}. {sid}（路径组 {groups}）")
        if item.get("statement_missing"):
            lines.append("- 册子里没有这条命题（不在册）⇒ 只能判 unknown，不许判一致。")
        else:
            kind = str(item.get("evidence_kind") or "")
            if item.get("admissible"):
                lines.append(f"- 它现在的档位：`{kind}`（够格被引）")
            else:
                lines.append(
                    f"- 它现在的档位：`{kind or '（空：没有档位）'}`，"
                    f"够不上 `{CITATION_EVIDENCE_FLOOR}` 级 ⇒ 不够格被引："
                    "这一条要判 inadmissible（不管原文一致不一致）。")
            lines.append(f"- 被引命题正文：{item.get('statement_digest') or '（正文为空）'}")
        for path in (item.get("paths") or []):
            note = str(path.get("note") or "")
            where = str(path.get("note_source") or "")
            lines.append(
                f"- F 的说法（路径组 {path.get('path_group')}，依赖行 "
                f"{path.get('dep_id') or '?'} 的 `{where or '（没有话）'}`）："
                f"{note or '（F 没有写为什么引它）'}")
            quote = str(path.get("quote") or "")
            # 引文原话单独印一次，但若 F 那句话里已经含着它（写侧常把 quote 拼进 label，
            # 例如"手稿依赖段（第 4 行）：由引理 2"）就不再重复一遍。
            if quote and quote not in note:
                lines.append(f"- 依赖行上的引文原话：{quote}")
            status = str(path.get("status") or "")
            if status:
                lines.append(f"- 这条依赖的状态：{status}")
    return "\n".join(lines)


def cold_start_prompt(statement_full: str, proof_text: str,
                      *, readonly_facts: str = "",
                      citations: Sequence[Mapping[str, Any]] = (),
                      citations_problem: str = "") -> str:
    """V 的冷启动提示词（纯函数：只有对象 + 只读读数，没有 F 的叙述、没有 store 句柄）。

    为什么把"提示词怎么拼"做成纯函数而不是塞进角色循环里：I12 是一个结构性质 ——
    "给它的上下文里有没有 F 的叙述 / 有没有 store 句柄"必须能被判据直接断言
    （`tests/test_verifier_role.py` 就是这么判的）。塞进循环里之后，它只能靠"读代码相信"。

    `readonly_facts` 是已经渲染好的只读读数（命题/文献/实验台账的摘要，由调用方
    从只读查询面取好传进来）—— 传字符串而不是传 store，是为了让"它能碰什么"在接口上
    就固定下来。

    `citations` 是引用核实的材料（`citation_material` 的返回）：F 对每条被引命题的说法
    与被引命题的正文摘要一起进来。它仍然只是一串字符串（没有 store 句柄），
    但它是 F 的叙述 —— 所以接口上多这一格是刻意的：V 要核 F 的引用，就必须看到 F 的
    说法，这是 `draft/39` 里"不给作者叙述"那条纪律的一处有边界的例外（只给被引命题的
    依赖行，不给整份证明的作者解释）。
    """
    # 开关读数（读不懂按"关"算：与 settings 的 fail-closed 同向）
    try:
        from .settings import lean_enabled as _le

        _lean_on = bool(_le()[0])
    except Exception:  # noqa: BLE001
        _lean_on = False
    return (
        "你是验证者（V）。你这一次只做一件事：把下面这份证明**按写成后的样子**整体重读一遍，"
        "判断它站不站得住。\n\n"
        "你不写、不改证明；不判这命题值不值得做；不做稿件级正式审查。\n\n"
        "## 硬禁令（命中哪一条就指到那一步）\n"
        "- 无条件前提（结论要的前提没写出来）；\n"
        "- 无依据的步骤（既没引到在册的 id，也没有同段内的推导）；\n"
        f"- 缝：{'、'.join(HARD_BAN_MARKERS)} 这类「跳过去」的措辞；\n"
        "- 引用到一条**不干净**的命题（还是猜想 / 已作废 / 只是 assumption）。\n\n"
        "## 只读读数（你只能看这些；没有 store 句柄，也不给你作者的任何解释）\n"
        f"{readonly_facts.strip() or '（调用方没有附只读读数）'}\n\n"
        "## 命题（含完整假设）\n"
        f"{str(statement_full or '').strip() or '（空）'}\n\n"
        "## 证明全文\n"
        f"{str(proof_text or '').strip() or '（空）'}\n\n"
        f"{citations_block(citations, citations_problem)}\n\n"
        "## 只输出一个 JSON 对象（不要解释文字、不要代码围栏）\n"
        '{"verdict": "成立|有毛病|看不出来", "defect_step": <整数或 null>, '
        '"quote": "<命中的原话，逐字>", "why": "<一句话理由>", '
        '"findings": [{"level": "error|warning|info", "step": <整数或 null>, '
        '"kind": "<短语>", "detail": "<指到那一步的说明>"}], '
        '"citation_checks": [{"stmt_id": "<被引命题号>", '
        '"verdict": "consistent|weaker|stronger|unrelated|inadmissible|unknown", '
        '"quote_verbatim": <true 或 false>, "note": "<一句话依据：一致在哪 / 差在哪>"}]}\n'
        "- `defect_step`：有毛病时**必须**给出那一步的编号（从 1 起数，按证明里的步骤顺序）；\n"
        "- `看不出来`：信息不足、无法判断时的诚实结论 —— 它不是 `成立`；\n"
        "- 没有毛病才写 `成立`（空 findings 或只有 info/warning）。\n"
        # ---- 引用核实那一档的口径（业主 2026-10-26 两批裁定，逐字见 CITATION_VERDICTS）
        "\n## 引用核实怎么判（正常写证明就是不会逐字的；判据不是字面像不像）\n"
        "- `consistent`：F 的用法与这条命题真正说的条件/结论一致（改写、压缩、换符号都行）；\n"
        "- `weaker`：F 只用到了它的弱形式 —— 不等于错，是情报；这一档可以判成立，"
        "但 note 要写清只用到哪一部分；\n"
        "- `stronger`：F 用到的结论比命题本身更强（把结论说强了、或悄悄去掉了它要的假设）；\n"
        "- `unrelated`：这条命题与这一步无关（引错了）；\n"
        f"- `inadmissible`：被引命题的档位低于 `{CITATION_EVIDENCE_FLOOR}`（"
        "`cross_check` / `heuristic` / 空）⇒ 不够格被当作依据引，不管用法一致不一致；\n"
        "- `unknown`：材料不足判不了（不在册 / 正文读不到）—— 它不是 `consistent`。\n"
        "- `quote_verbatim` 只当信息记（F 那句话是不是逐字抄的），它不影响结论、也不影响签字。\n"
        "- 有一条 `stronger` / `unrelated` / `inadmissible` / `unknown` ⇒ 这一份不许判 `成立`"
        "（你写成成立也会被改判）；只有全部 `consistent` / `weaker` 才签得成。\n"
        # 2026-10-17（Lean 审计 S3）：这是 V 的真实入口（`agent_v/core.py` 用它，
        # 而 `system_prompt("V")` 全仓没有生产路径渲染）⇒ 开关与"成立≠proof"必须写在这里，
        # 否则 V 在 Lean 开着/关着时行为完全一样，而 H 会把它签的第 3 位当凭据。
        #
        # 2026-10-23 晚（业主：「E 写的报告要能落下来，且 V 也要会审这种东西，加 E 派 V 的边」）：
        # 这里此前写的是「evidence_kind=proof 只由 verify.check_formal 的检查器输出产生；
        # 要 proof 就请 M 派 E 走 formal 那条路」—— 那句话现在是假话（穷举证据也能拿 proof，
        # 而签字的人正是 V），它会让 V 把 E 交来的穷举证明读成"不归我审"，或者反过来去要
        # 一份自然语言证明。所以改成两类 proof 并列，并把穷举那一档的入口写在这里。
        "\n## 你这个「成立」是什么强度：两类 proof 并列\n"
        f"- 本会话 Lean 形式化：{'**已开启**' if _lean_on else '**已关闭**'}；\n"
        "- `proof` 级证据有两类，并列、不分高低：\n"
        "  ① Lean 形式化 —— 凭据是 `formal.check_formal` 的检查器原话；\n"
        "  ② 穷举 —— 凭据是 E 写的那份程序 + ②③，签字的人是你（见下面那一档）；\n"
        # 2026-10-24：判据 long 期望这一句「不构成 `proof`」—— 它的意思是"
        # 你这一次逐行走查的「成立」本身不是 proof 级凭据：proof 档要那两类里的某一份"
        # （检查器原话 / 穷举那份程序），你这一签是给它们背书的，不是替代它们。
        "- 要说清强度：你这一次的「成立」**本身不构成 `proof`** —— 它是对上面两类里某一份的背书；"
        "`proof` 级证据仍然要那一份凭据（检查器原话，或穷举那份程序 + ②③）。\n"
        "- 所以别在理由里写「已形式化验证」（那是第 ① 类的说法）；穷举那一类你要写的是"
        "「穷尽性与会审七项已核」。\n"
        "\n## 穷举型证据会审（证明栏第 ① 段是程序、且不是 `.lean` 时走这一档）\n"
        "- 你的入口是七项机械会审，一条一项、逐条给读数：① 程序地址在不在盘上、读不读得出来；"
        "② 报告落盘且三块齐（`out/experiments/<实验号>/exhaustion.md`）；"
        "③ 搜索空间的数字与代码里的循环/参数一致；④ 对称性/剪枝的理由成不成立；"
        "⑤ 边界覆盖写没写、数字对不对得上；⑥ 结论是穷尽而不是抽样；"
        "⑦ 形式化那一格填的类别对不对（数值定理填数值程序、理论定理填 `.lean`）。\n"
        "- 结论落在三格：`exhaustion_review`（整份会审读数）/ `checks`（七项逐项 ok）/ "
        "`missing`（缺哪一块材料）。\n"
        "- 这一档里的 `看不出来` 是缺材料（报告没落地、实验行没有、②③ 缺一块），不是"
        "「没查成」：点名缺哪一块即可，但不许判 `成立` —— 缺材料的诚实结论就是看不出来。\n"
        "- 七项全过才签 `成立`；这一签是「对数值证据的背书」，不是「你逐行读过一份"
        "自然语言证明」。\n"
    )


def proof_sha(proof_text: str) -> str:
    """被审证明的 sha256（钉住"审的是哪一份"；与台账 id 的指纹口径同一套）。"""
    return hashlib.sha256(str(proof_text or "").encode("utf-8")).hexdigest()


#: 一条证明（或一条命题）相对「它现在这一份正文」的五种读数（唯一口径在
#: :func:`review_standing` / :func:`statement_review_reading`）。
#:
#: 顺序是"从查清了到没查成"：`signed`（现行版有「成立」那一签）/ `stale`（签的是旧版，
#: 待复核）/ `rejected`（现行版被签过，结论不是「成立」）/ `unsigned`（一次都没签）/
#: `unreadable`（台账读不出来 / 证明号认不出 —— 没查成，不是通过、也不是没签过）。
#:
#: 为什么 stale 与 rejected 必须分开（三态纪律）：前者是"签过、但签的不是现在这一份"，
#: 后者是"签的就是这一份、结论是没过"。把两者折成同一个"不算"会让"改完稿还没送审"
#: 与"审过了、没过"在读数上长得一样，而处置完全不同（前者重派 V，后者改证明）。
REVIEW_STATES: tuple[str, ...] = ("signed", "stale", "rejected", "unsigned", "unreadable")

#: 多证明模型的落点（业主 2026-10-22：不加 schema 字段）。
#:
#: 一条命题可以有几份证明：canonical 是 `#p1`，它的正文就是行上既有的 `proof_text`
#: （老写者只会写那一格，所以它必须继续是 `#p1` 的权威正文）；其余证明落在行 JSON
#: 里一个额外的键 `proofs`：`[{"proof_no": 2, "proof_text": "..."}, ...]`。
#: `schema.row_from_dict` 只取它认识的键（"未知字段会被忽略"），所以盘上多这一个键
#: 不需要动 `schema` —— 而"证明清单"本身是数据，不是磁盘格式契约的新字段。
PROOFS_KEY = "proofs"


def as_proof_no(value: Any) -> int:
    """把一个证明号归一成正整数（`2` / `"2"` / `"p2"` / `"#p2"` / `"stmt:000004#p2"` 都认）；认不出 ⇒ 0。

    0 表示"这不是一个证明号"。写入口用它把调用方给的 `proof_no` 归一，读侧用它判
    "这一格有没有写证明号"；两处用同一个函数，免得一边认 `p2` 一边不认。
    带 `#pN` 尾巴的写法交给 `proofloc`（全仓拆这个尾巴的唯一解析点，业主 2026-10-22）：
    两份解析意味着"台账上是第 2 条、读出来是第 1 条"这种错没有任何东西会报。
    """
    text = str(value or "").strip()
    # 只带前缀的写法（`"#p2"`）先去掉那颗 `#`：`proofloc` 把"没有命题号的 `#p2`"判成坏尾巴
    # （它是在 `used_by` 上判的，那里确实没有命题号），而本函数的入参允许这种简写。
    if text.startswith("#") and "#" not in text[1:]:
        text = text[1:]
    if "#p" in text:
        from . import proofloc as _PL   # 惰性：`proofloc` 只被这一处与依赖读侧用到

        _head, no, problem = _PL.parse_used_by_checked(text)
        # 坏尾巴（`#p0` / `#p` / `#pabc` / 多段 …）不是"第 1 条证明"：`parse_used_by` 会把它们
        # 静默折成 canonical（它是给"读侧照读"用的），而这里的返回值是给调用方判
        # "这一格到底有没有写证明号"用的 —— 折成 1 会让"这不是一个证明号"读成"这就是 #p1"。
        # 0 是本函数唯一的"不是证明号"取值（调用方一律按 `or 1` 兜底 canonical）。
        return 0 if problem else no
    text = text.lstrip("#").lstrip("pP")
    try:
        got = int(text)
    except (TypeError, ValueError):
        return 0
    return got if got >= 1 else 0


def proof_no_strict(value: Any) -> int:
    """写侧收调用方给的证明号：认不出就抛 `VerificationError`（不静默折成 `#p1`）。

    与 :func:`proof_no_of` 的分界（2026-10-22 审计第 3 条）：`proof_no_of` 是读侧的
    "这一行属于哪一份证明"，拿不到答案就按 canonical 读（读侧折平只会让读数粗，
    不会让某一份证明凭空多一签）；本函数是写侧的"调用方说要签哪一份"，拿不到答案
    必须拒绝 —— 改前两处写口都写 `as_proof_no(x) or 1`，于是 `proof_no=0`
    （"这不是一个证明号"的哨兵）被静默折成 `#p1`：调用方说"签 #p2"，台账上记的是
    `proof_no=1`，而 `verdict=成立` 一个字节不少，两份证明的第 3 位读出来是反的。

    `None` 不是"认不出"，是"没给"（缺省 canonical，见 `proofloc`）。
    调用方要区分"没给参数"与"给了但认不出"，靠的就是传 `None` 与传一个坏值的差别。
    """
    if value is None:
        return DEFAULT_PROOF_NO
    got = as_proof_no(value)
    if got >= 1:
        return got
    raise VerificationError(
        f"证明号认不出：收到 {value!r}（合法写法是 1、2、3 … 或 '2' / 'p2' / '#p2'）"
        "⇒ 拒绝：不落台账、不改任何一位（按 #p1 记会让这一签挂到别的证明头上）")


#: 证明号在行上的键名。`proof_no` 是正名；`rev` 是更早的写法。
#:
#: 为什么读侧认两个名字、而不是做一次迁移：台账是追加式文件（`verifications/*.jsonl`），
#: 改键名只能重写历史行 —— 那会把"谁在什么时候签的"改成"我们改写过它"。兼容的代价是
#: 一行读法，迁移的代价是不可逆的审计记录。`no` 是清单项里更短的那个旧别名。
PROOF_NO_KEYS: tuple[str, ...] = ("proof_no", "rev", "no")


def proof_no_of(row: Mapping[str, Any]) -> int:
    """这一行（签名行 / 证明清单项 / 任何带证明号的 dict）记的证明号；没写 ⇒ canonical（1）。

    0（"这不是一个证明号"）不出现在返回值里：调用方问的是"这一行属于哪一份证明"，
    而答案永远有一个 —— 没写就是 `#p1`（老数据的读法，业主 2026-10-22 口径：
    不带 `#pN` / 不带 `proof_no` 的老数据，读数与行为逐字不变，证明号缺省 1）。
    认不出的值同样按 1 读：读侧拿不到答案，比读成 canonical 更坏（`as_proof_no` 的
    0 留给"判这一格有没有写号"那一档用）。
    """
    for key in PROOF_NO_KEYS:
        value = row.get(key)
        if str(value or "").strip():
            got = as_proof_no(value)
            if got >= 1:
                return got
    return DEFAULT_PROOF_NO


def _read_proof_no(value: Any) -> int:
    """读侧收一个"要看哪一份证明"的号：没给 ⇒ canonical（1）；给了但认不出 ⇒ 0。

    ## 三档不许折平（业主 2026-10-22 裁定）
    - :func:`proof_no_of` 问的是"这一行属于哪一份证明"—— 答案永远有一个（老行没写就是
      `#p1`），所以它把认不出的值也读成 1；
    - :func:`proof_no_strict` 是写侧"调用方说要签哪一份"—— 认不出就抛错，一个字节都不写；
    - 本函数是读侧的"调用方点名要看哪一份"—— 它必须能回答"没有这一份"：字段/参数缺失
      才是 canonical，给了但认不出就是 0，不许折成 `#p1`。

    改前三处读口都写 `as_proof_no(x) or 1`：于是 `'abc'` / `0` / `2.0` 这类"这不是一个
    证明号"的值被静默读成 canonical —— 读数里看不出"号给错了"，而 `proof_text_of` 还会
    把 `#p1` 的正文端出来当作"你要的那一份"。折平在这里不是"读数粗一点"，是张冠李戴。

    空串与 `None` 同一档（都算"没写"）：老行可能把这一格写成空串，它与"键不存在"在读侧
    没有区别（`proof_no_of` 也是这么读的，见那里的 `if str(value or "").strip()`）。
    """
    if value is None or not str(value).strip():
        return DEFAULT_PROOF_NO
    return as_proof_no(value)


def proof_list(row: Mapping[str, Any]) -> list[tuple[int, str]]:
    """这条命题的证明清单 `[(proof_no, 正文), ...]`，`#p1` 恒在且排第一。

    两处来源（与 `PROOFS_KEY` 的注释同一口径）：
    - `#p1`（canonical）：行上的 `proof_text` —— 老写者（B / F / 秘书）只会写那一格，
      所以它必须继续是 canonical 的权威正文；
    - `#p2` 及以上：行 JSON 的 `proofs` 清单里，每项 `{"proof_no": n, "proof_text": …}`。
      清单里若也写了 1 号，读侧以 `proof_text` 为准（同一格不许有两个权威）。
    没有清单的旧行 ⇒ 只有一条 `(1, proof_text)`，读数与改前逐字相同。
    """
    out: list[tuple[int, str]] = [(1, str(row.get("proof_text") or ""))]
    raw = row.get(PROOFS_KEY)
    if not isinstance(raw, (list, tuple)):
        return out
    seen = {1}
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        no = proof_no_of(entry)
        if no <= 1 or no in seen:
            continue
        seen.add(no)
        out.append((no, str(entry.get("proof_text") or entry.get("text") or "")))
    return sorted(out, key=lambda item: item[0])


def proof_text_of(row: Mapping[str, Any], proof_no: int = 1) -> str:
    """这条命题的某一份证明现在长什么样（找不到那一份 ⇒ 空串）。

    证明号走 :func:`_read_proof_no`：没给 ⇒ `#p1`；给了但认不出（`'abc'` / `0` …）⇒
    空串，不端出 `#p1` 的正文。改前是 `as_proof_no(proof_no) or 1`，于是
    `proof_text_of(row, 'abc')` 读到的就是 canonical 那一份 —— 一个坏号得到的答案与
    "我要 #p1"逐字相同，而调用方无从分辨。
    """
    want = _read_proof_no(proof_no)
    if want < 1:
        return ""
    for no, text in proof_list(row):
        if no == want:
            return text
    return ""


def proof_label(statement_id: str, proof_no: int = 1) -> str:
    """读数里的写法：`000004#p2`（不带 `#pN` 的老写法等价于 `#p1`）。

    证明号认不出时写法里点名（`000004#p？（证明号认不出：'abc'）`），不折成 `#p1`：
    这个串会进 `why` / `detail` / 逐条计数项（`proofs_unreviewed` 等），折平会让一条
    坏号以 canonical 的身份出现在读数里，读的人只会看到"#p1 怎么样"，看不到"号给错了"。
    """
    sid = str(statement_id or "")
    no = _read_proof_no(proof_no)
    if no < 1:
        return f"{sid}#p？（证明号认不出：{proof_no!r}）"
    return f"{sid}#p{no}"


def parse_verdict(text: str) -> dict[str, Any]:
    """把 V 的那一句输出解析成一次审校的结论；不合法 ⇒ 抛 `VerificationError`（没查成）。

    "没查成"与"看不出来"必须分开：前者是检查器的问题（重试/修提示词），
    后者是对证明的结论（诚实地说判不了）。把两者折平，会让一次模型抽风
    在台账上留下"V 看过这份证明，结论是看不出来"——那是一条假证据。

    ## 引用核实那一格（业主 2026-10-26 裁定）
    输出里的 `citation_checks` 一并洗成 :data:`CITATION_CHECK_KEYS` 那四格并放进结论，
    于是它随台账那一行落盘（"签字的读数"里有这一格）。形状不对（`verdict` 不在词表里 /
    `stmt_id` 不是命题号形态）是"没查成"：抛错，不静默丢、也不折成 `unknown`。

    `有毛病` 的步号要求在这里放宽一格（不是放宽成"可以不说"）：若结论里有一条挡住签字的
    引用核实（`stronger` / `unrelated` / `unknown`），缺陷是按"被引命题"定位的，可以没有
    步号 —— 那条 error 的 `detail` 里点了名，那才是这一档的落点。
    """
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?|```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    body = raw[start:end + 1] if (start >= 0 and end > start) else raw
    try:
        got = json.loads(body)
    except ValueError as exc:
        raise VerificationError(f"V 的输出不是合法 JSON（{type(exc).__name__}: {exc}）") from exc
    if not isinstance(got, Mapping):
        raise VerificationError("V 的输出必须是对象")
    verdict = str(got.get("verdict") or "").strip()
    if verdict not in VERDICTS:
        raise VerificationError(f"verdict 必须是 {VERDICTS} 之一，收到 {verdict!r}")
    findings: list[dict[str, Any]] = []
    for item in (got.get("findings") or []):
        if not isinstance(item, Mapping):
            raise VerificationError("findings 的每一项都必须是对象")
        level = str(item.get("level") or "").strip()
        if level not in FINDING_LEVELS:
            raise VerificationError(f"finding.level 必须是 {FINDING_LEVELS} 之一，收到 {level!r}")
        findings.append({"level": level, "step": item.get("step"),
                         "kind": str(item.get("kind") or "").strip(),
                         "detail": str(item.get("detail") or "").strip()})
    defect_step = got.get("defect_step")
    if defect_step is not None and not isinstance(defect_step, int):
        raise VerificationError("defect_step 必须是整数或 null")
    checks = _citation_checks_raw(got.get("citation_checks"))
    blamed = [c for c in checks if c["verdict"] in CITATION_BLOCKING]
    if verdict == "有毛病" and defect_step is None and not blamed:
        raise VerificationError(
            "verdict='有毛病' 必须给 defect_step（指到那一步）—— 只说'有毛病'"
            "等于把改哪儿留给作者猜（唯一例外：有一条挡住签字的引用核实，缺陷按被引命题定位）"
        )
    return {"verdict": verdict, "defect_step": defect_step,
            "quote": str(got.get("quote") or "").strip(),
            "why": str(got.get("why") or "").strip(), "findings": findings,
            "citation_checks": checks,
            "unresolved_errors": sum(1 for f in findings if f["level"] == "error")}


def next_verification_id(root: str | Path, statement_id: str) -> str:
    """这个命题的验证台账里的下一个编号（`v-` + 当前宽度；宽度见 `schema.format_id`）。

    为什么从 `record_verification` 里抽出来一处具名函数（2026-10-14 改宽度那一笔）：
    它是发号点，而"每个发号点都发当前宽度"这条判据要能逐个真发一次 ——
    发号逻辑埋在写函数中间时，判据只能靠"读一遍代码"来假装检查过。
    """
    path = verification_ledger_path(root, statement_id)
    rows, _problems = JF.read_jsonl(path) if path.is_file() else ([], [])
    return f"v-{S.format_id(len(rows) + 1)}"


def record_verification(root: str | Path, *, statement_id: str, proof_text: str, verdict: Mapping[str, Any],
           verifier: str = "V", round_no: int | None = None,
           used_faces: Iterable[str] = (), submission_id: str = "",
           store: Any = None, proof_no: Any = None,
           object_sha256: Any = "", object_path: Any = "",
           citation_gate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """把一次审校写进这个命题的台账（追加一行），返回那一行。

    编号 `v-NNNN` 由脚本按文件内顺序发（`draft/39` §3.21 五：与手稿编号、台账 id 同一套）。
    写之前把结论再规范化一遍（`parse_verdict` 的同一套校验）—— 调用方绕开解析直接
    构造一个 dict 时，坏结论会在写入期被挡住，而不是等到下游读它的时候。

    ## 这一行记什么（2026-10-22 补上右边的三格）
    `(stmt_id, proof_no, proof_sha256)`：`stmt_id` 是被审的那条命题（与 `statement_id`
    同值，两个键都写是为了不让读的人去猜哪个才是号）；`proof_no` 是被审的那一份证明
    （缺省 1 = canonical，见 :data:`PROOFS_KEY`）；`proof_sha256` 是这一份正文的指纹。
    三者合起来回答"复核过的是哪一份"。

    ## 证明号的两种来路必须分开（2026-10-22 审计第 3 条）
    `proof_no=None` = 没给参数 ⇒ canonical（`#p1`）；给了但 :func:`as_proof_no` 认不出
    （`0` / `'abc'` / `2.0` / `'#p0'` …）⇒ :func:`proof_no_strict` 抛
    `VerificationError`，一个字节都不写。改前这里写 `as_proof_no(proof_no) or 1`：
    调用方说"签 #p2"、号给成了 0，台账上记成 `proof_no=1` 且 `verdict=成立` —— 签错
    一份证明，而盘上没有任何一格会报。

    ## `store` 给了就顺手把那条证明的第 3 位翻上去（业主 2026-10-22：同一次写）
    给了 `store` 且这一签签得住第 3 位（`signs_bit3`）⇒ 追加台账之后立刻调
    :func:`sign_statement`，在同一个 `statements` 事务里把那条证明的 `reviewed` 置真并把
    `reviewed_by` 换成这一签的凭据（含 `proof_no` 与 `proof_sha256`）。返回值里多一格
    `statement_writeback`（写没写成、为什么、回滚了没有、追加落在哪一态）—— 台账那一行
    是权威记录，位是它的缓存；写位失败不回滚签名（签名确实发生过），但必须如实报出来。
    不给 `store` ⇒ 只追加台账（老行为，夹具与自检走这条）。

    ## 返回行上的三格：这一签到底有没有落地（2026-10-22 审计第 1 条）
    `checked` / `re_sign_required` / `reason`：撤回（`_rollback_append`）发生在
    :func:`sign_statement` 内部，调用方只看返回值。改前撤回之后返回行仍然是那一份
    `verdict=成立` 的记录 ⇒ V 的 `verify_proof` 照报"签住了第 3 位"，而台账是 0 字节。
    现在撤回或追加失败 ⇒ `checked=False`、`re_sign_required=True`、`reason` 逐字写明
    "台账那一行被撤回 / 没写成"。

    ## `citation_gate`：只在"这一档没查成"时写（2026-10-27）
    `problem` 非空（依赖台账读不出来）⇒ 行上多一格 `citation_gate`
    （`ok` / `problem` / `why` 三个读数）。为什么必须落盘：那时 `citation_checks` 常常
    是空数组，而空数组什么都不挡 —— 读侧的硬闸（:func:`signs_bit3`）要能分开
    "没查成"与"核过、没有引用"。查成了的行不写这一格（老行因此逐字节不变）。
    """
    # 证明号先判：坏号在写任何东西之前就拒（不落台账、不改位）。
    no = proof_no_strict(proof_no)
    checked = parse_verdict(json.dumps({"verdict": verdict.get("verdict"),
                                        "defect_step": verdict.get("defect_step"),
                                        "quote": verdict.get("quote", ""),
                                        "why": verdict.get("why", ""),
                                        "findings": list(verdict.get("findings") or []),
                                        # 引用核实那一格也要过同一套校验：调用方绕开
                                        # `parse_verdict` 直接构造 dict 时，坏档位同样被挡在
                                        # 写入期（否则它会以"没有这一格"的样子落盘）。
                                        "citation_checks": list(verdict.get("citation_checks") or [])},
                                       ensure_ascii=False, default=str))
    path = verification_ledger_path(root, statement_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, problems = JF.read_jsonl(path)
    if problems:
        raise VerificationError(f"这个命题的验证台账有读不出来的行：{problems[:3]}")
    vid = next_verification_id(root, statement_id)
    sha = proof_sha(proof_text)
    row = {
        "verification_id": vid,
        # 两个键同值：`statement_id` 是历史名（老行只有它），`stmt_id` 是"被审的命题"的
        # 那一个名字（业主 2026-10-22 点名要它）。只写一个会让按另一个键读的人读到 None，
        # 而"读到 None"与"这一签不属于任何命题"在读数上长得一样。
        "statement_id": str(statement_id), "stmt_id": str(statement_id),
        #: 被审的是哪一份证明（1 = canonical，#p1）。老行没有这一格 ⇒ 读侧按 1 算。
        "proof_no": no,
        "verifier": str(verifier or "V"), "verdict": checked["verdict"],
        "defect_step": checked["defect_step"], "quote": checked["quote"],
        "why": checked["why"], "findings": checked["findings"],
        "unresolved_errors": checked["unresolved_errors"],
        #: 引用核实（业主 2026-10-26）：`[{stmt_id, verdict, quote_verbatim, note}]`。
        #: 每一行都写这一个键（空列表 = "这一签核过、没有被引命题要核"，与历史行
        #: "没有这一格"在读侧分得开：老行没有它，新行有它、可以是空的）。
        "citation_checks": list(checked.get("citation_checks") or []),
        "proof_sha256": sha,
        "proof_chars": len(str(proof_text or "")),
        "round": int(round_no) if round_no is not None else len(rows) + 1,
        "used_faces": [str(x) for x in used_faces],
        "submission_id": str(submission_id or ""),
        "at": _now_iso(),
    }
    #: D-34：这一签审的对象（盘上那份报告 / 证明文件）的字节 sha256 与相对路径。
    #: 只在调用方真的知道时写（条件写入，老行因此逐字节不变），读侧按它认领
    #: "命题登记之前审的那一签"（`numericproof.latest_third_party_sign` 的第二路）。
    if str(object_sha256 or "").strip():
        row["object_sha256"] = str(object_sha256).strip().lower()
        row["object_path"] = str(object_path or "").strip().replace("\\", "/")
    #: 引用核实那一档的判据本行（`citation_gate` 的五格）。只在"这一档没查成"
    #: （`problem` 非空）时写：那时 `citation_checks` 往往是空数组（没有条目可核），
    #: 而空数组什么都不挡 —— 没有这一格，读侧（`signs_bit3`）就分不开"没查成"与
    #: "核过、没有引用"。查成了的行一个字都不多写（老行因此逐字节不变）。
    gate_problem = ""
    if isinstance(citation_gate, Mapping):
        gate_problem = str(citation_gate.get("problem") or "").strip()
    if gate_problem:
        row["citation_gate"] = {"ok": False, "problem": gate_problem,
                                "why": str(citation_gate.get("why") or "")}
    if store is None:
        _append_verification(path, row)
        return row
    if not signs_bit3(row):
        # 签不住的结论也要落台账（它是"看过、结论是没过"的证据），但它不翻任何位。
        # 追加由本函数做（`sign_statement` 在这一支只回一句理由、不碰台账）⇒ 由本函数
        # 把追加落在哪一态写回 `statement_writeback`（2026-10-22 审计第 5 条：那一格
        # 此前只有"-written 前的 -1"一个哨兵兼任两义，"签名确实发生过"可能是在说谎）。
        append_state = "not_attempted"
        append_problem = ""
        try:
            _append_verification(path, row)
            append_state = "appended"
        except OSError as exc:
            append_state = "failed"
            append_problem = f"{type(exc).__name__}: {exc}"
        writeback = sign_statement(store, row=row, proof_text=proof_text,
                                   path=path, proof_no=no)
        writeback["append_state"] = append_state
        if append_state == "failed":
            writeback.update(
                written=False, re_sign_required=True,
                reason=(f"签名那一行没写成（{append_problem}）⇒ 这一签没有落地（必须重签）；"
                        + str(writeback.get("reason") or "")))
        row["statement_writeback"] = writeback
        _mark_landed(row, writeback)
        return row
    writeback = sign_statement(store, row=row, proof_text=proof_text,
                               path=path, proof_no=no)
    row["statement_writeback"] = writeback
    _mark_landed(row, writeback)
    return row


def _mark_landed(row: dict[str, Any], writeback: Mapping[str, Any]) -> None:
    """把"这一签有没有真的落地"写进返回行（`checked` / `re_sign_required` / `reason`）。

    判据只认 `writeback` 自己报的两格：`append_state == "appended"`（台账那一行真追加了）
    且没有 `rolled_back`（它没被撤回）。只看 `verdict` 会把"被撤回的那一签"读成"签住了"，
    而台账盘上是 0 字节 —— 这正是本批审计第 1 条的读数（`checked=True verdict='成立'
    signed_bit3=True` 而台账字节数 0）。
    """
    landed = (str(writeback.get("append_state") or "") == "appended"
              and not writeback.get("rolled_back"))
    row["checked"] = bool(landed)
    row["re_sign_required"] = bool(writeback.get("re_sign_required"))
    if landed:
        row["reason"] = ""
        return
    head = "台账那一行被撤回" if writeback.get("rolled_back") else "台账那一行没写成"
    row["reason"] = (f"{head}：这一签没有落地（必须重签）；位没有改成 reviewed="
                     f"{bool(writeback.get('written'))}；写回原话："
                     f"{str(writeback.get('reason') or '')}")


def list_verifications(root: str | Path, *, statement_id: str = "",
             limit: int | None = 50) -> tuple[list[dict[str, Any]], list[str]]:
    """列验证台账（可按命题过滤）；返回 `(行, 坏行说明)` —— 坏行照实报出，不静默跳过。

    ## `limit=None` 与 `limit=0` 必须分开（V1，`draft/44` J-14）

    实现此前写的是 `out[-limit:]`，而 `-0 == 0` ⇒ `limit=0` 恰好等于全量。
    那是一个靠运算符巧合成立的语义：调用方写 `limit=0`（"不要行"）会拿到全部行，
    而没有任何报错。三态纪律在分页上同样成立 —— "要零条"与"要全部"是两件事。

      - `limit=None` ⇒ 全量（"我要看完整本台账"）；
      - `limit=0`   ⇒ 零条（空表）；
      - `limit=n>0` ⇒ 末尾 n 条（按 (命题号, 编号) 排序后取尾部）。
    """
    base = verifications_dir(root)
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    files = ([verification_ledger_path(root, statement_id)] if statement_id
             else sorted(base.glob("*.jsonl")) if base.is_dir() else [])
    for p in files:
        rows, bad = JF.read_jsonl(p)
        problems.extend(f"{p.name}: {b}" for b in bad)
        out.extend(rows)
    out.sort(key=lambda r: (str(r.get("statement_id") or ""), str(r.get("verification_id") or "")))
    if limit is None:
        return out, problems
    return out[-max(0, int(limit)):] if int(limit) > 0 else [], problems


def ledger_reading(root: str | Path, *, store: Any = None) -> dict[str, Any]:
    """验证台账的"真身"读数：文件是正本，同名的数据表从来不存在（一处真身）。

    ## 为什么需要这一格（真机 sylow3，2026-10-24 的缺口二）
    V 的产物是工作区里 `verifications/<命题号>.jsonl` 的那些行（`schema.TABLES` 里
    没有 `verifications` 这张表：`store.rows("verifications")` 直接抛「未知表」）。
    于是一次运行结束时盘上有 `verifications/000000.jsonl` ... `000006.jsonl` 七份、
    十四行签，而按"数据表"那一面看（`data/` 目录里没有 `verifications.json`）是 0 行。
    两处口径从来没有被任何一格对起来过：文件面是 7 份、表面是 0 行，收工门、对应表、
    证据面各读各的一边 ⇒ 读的人只会看到"没有签"。

    这一格把这件事写成一次可机器读的读数，三态（不猜）：
    - `source`：这一档的正本永远是 `verifications/*.jsonl`（文件）。同名数据表
      `is_store_table=False`，`rows=None`（不是 0 —— "这张表不存在"与"表是空的"是两件事）。
    - `mirror`：如果盘上真有 `data/verifications.json`（派生副本 / 别人拷进去的），
      就逐条按 `verification_id` 对账；`agrees` 只有 `True` / `False` / `None` 三档，
      `None` = 没有副本可对（"没查"不是"对上了"）。
    - `problems` 非空 ⇒ 两面分家，`why` 说清差在哪几条。

    返回（键集合固定，读的人不必猜）：
    `checked` / `source` / `files` / `file_names` / `rows` / `signed` /
    `signed_statements` / `table` / `mirror` / `agrees` / `problems` / `why` / `next_step`。
    """
    root_p = Path(str(root))
    out: dict[str, Any] = {
        "checked": False,
        "source": f"{VERIFICATIONS_DIR}/*.jsonl",
        "files": 0,
        "file_names": [],
        "rows": 0,
        "signed": 0,
        "signed_statements": [],
        "table": {"name": VERIFICATIONS_DIR, "is_store_table": False, "rows": None,
                  "why": ""},
        "mirror": {"path": f"data/{VERIFICATIONS_DIR}.json", "present": False,
                   "rows": None, "agrees": None},
        "agrees": None,
        "problems": [],
        "why": "",
        "next_step": "",
    }
    # ---- 文件面（正本）
    base = verifications_dir(root_p)
    if not base.is_dir():
        out["why"] = (f"`{VERIFICATIONS_DIR}/` 不在盘上 ⇒ 这个工作区还没有一次签过"
                      "（这是「零签」，不是「读不到」：目录在不在与行读不读得出来是两件事）")
        out["next_step"] = "派 V 走 `verify.verify_proof`（产物就是那个目录下的一行）"
        _ledger_table_state(out, store)
        return out
    rows, bad = list_verifications(root_p, limit=None)
    out["checked"] = True
    out["file_names"] = sorted(p.name for p in base.glob("*.jsonl"))
    out["files"] = len(out["file_names"])
    out["rows"] = len(rows)
    signed = [r for r in rows if signs_bit3(r)]
    out["signed"] = len(signed)
    out["signed_statements"] = sorted({_statement_id_of(r) for r in signed if _statement_id_of(r)})
    out["problems"] = list(bad)
    # ---- 表面：同名 store 表存不存在（"不存在"不许折成"0 行"）
    _ledger_table_state(out, store)
    # ---- 派生副本（如果有）
    mirror = dict(out["mirror"])
    mirror["rows"], mirror["present"] = _ledger_mirror_rows(root_p)
    if mirror["present"] and isinstance(mirror["rows"], list):
        want = {str(r.get("verification_id") or "") for r in rows}
        have = {str(r.get("verification_id") or "") for r in mirror["rows"]}
        mirror["count"] = len(mirror["rows"])
        if want == have:
            mirror["agrees"] = True
        else:
            mirror["agrees"] = False
            mirror["missing_ids"] = sorted(want - have)
            mirror["extra_ids"] = sorted(have - want)
            out["problems"].append(
                f"`data/{VERIFICATIONS_DIR}.json` 与文件台账分家：文件 {len(want)} 条、"
                f"表 {len(have)} 条（文件有表没有的是 {mirror['missing_ids'][:6]}、"
                f"表有文件没有的是 {mirror['extra_ids'][:6]}）")
        out["agrees"] = mirror["agrees"]
    elif mirror["present"]:
        mirror["agrees"] = None
        out["problems"].append(
            f"`data/{VERIFICATIONS_DIR}.json` 在盘上但读不出来 ⇒ 这一面没查成"
            f"（{mirror.get('why') or '格式不认'}）")
    out["mirror"] = mirror
    if out["files"] and out["signed"] == 0:
        out["problems"].append(
            f"`{VERIFICATIONS_DIR}/` 有 {out['files']} 份台账、{out['rows']} 行，"
            "而没有一行签「成立」⇒ 审过但一次都没签住（这是读数，不是读不到）")
    if not out["problems"]:
        out["why"] = (f"文件台账 {out['files']} 份、{out['rows']} 行，"
                      f"其中签「成立」且无未解决 error 的 {out['signed']} 行"
                      f"（覆盖 {len(out['signed_statements'])} 条命题）")
        if not out["table"]["is_store_table"]:
            # 表面那一格不是「0 行」，而是「这张表不存在」：读的人要能从这一格直接知道
            # 该去读文件（改前这一步没有任何落点，于是「表 0 行」被当成了「没有签」）。
            out["why"] += "；" + str(out["table"]["why"])
    out["next_step"] = (
        "读验证台账只走这一个口（`verifications.list_verifications` / 本函数）："
        f"正本是 `{VERIFICATIONS_DIR}/<命题号>.jsonl`；要找「表」的那个人应当读"
        "`rows` / `signed` 这两格，而不是去找一张不存在的 `verifications` 表")
    return out


def _statement_id_of(row: Mapping[str, Any]) -> str:
    """一行签名属于哪条命题（正名 `stmt_id`，老行读 `statement_id`）。"""
    return str(row.get("stmt_id") or row.get("statement_id") or "")


def _ledger_table_state(out: dict[str, Any], store: Any) -> None:
    """同名数据表那一面的三态：它不是 store 表（`rows=None`），不是「0 行」。"""
    table = dict(out.get("table") or {})
    in_schema = False
    try:  # 只在拿得到 schema 时判；拿不到就如实说没查成
        in_schema = VERIFICATIONS_DIR in S.TABLES
    except Exception:  # noqa: BLE001 - 读不到 schema 时按"不在表里"继续，理由写在 why 里
        in_schema = False
    table["is_store_table"] = bool(in_schema)
    if in_schema:
        table["why"] = f"`{VERIFICATIONS_DIR}` 是 store 表 ⇒ 读表即可（与文件对账）"
        if store is not None:
            try:
                table["rows"] = len(list(store.rows(VERIFICATIONS_DIR)))
            except Exception as exc:  # noqa: BLE001 - 读不到表就是"没查成"
                table["why"] += f"；但这一次没读出来（{type(exc).__name__}: {exc}）"
        out["table"] = table
        return
    table["rows"] = None
    table["why"] = (
        f"`{VERIFICATIONS_DIR}` 不是一张 store 表（`schema.TABLES` 里没有它）⇒ "
        f"`store.rows(\"{VERIFICATIONS_DIR}\")` 只会抛「未知表」，"
        f"按表读的那一面永远读到 0 行；正本是工作区里的 `{VERIFICATIONS_DIR}/"
        "<命题号>.jsonl`。这一格给的就是「表不存在」（`rows=None`），"
        "而不是「表是空的」（那会是 0）")
    out["table"] = table


def _ledger_mirror_rows(root_p: Path) -> tuple[Any, bool]:
    """盘上有没有 `data/verifications.json`（派生副本）；有就把它读成行列表。"""
    path = root_p / "data" / f"{VERIFICATIONS_DIR}.json"
    if not path.is_file():
        return None, False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 读不出来如实交给调用方
        return {"why": f"{type(exc).__name__}: {exc}"}, True
    rows = doc.get("rows") if isinstance(doc, Mapping) else doc
    if not isinstance(rows, list):
        return {"why": "文件里没有 rows 数组"}, True
    return [dict(r) for r in rows if isinstance(r, Mapping)], True


def read_verification(root: str | Path, verification_id: str) -> dict[str, Any] | None:
    """按编号取一行（编号在同一命题的文件内唯一；跨文件重号 ⇒ 返回第一个并带 `ambiguous`）。"""
    want = str(verification_id or "").strip()
    rows, _problems = list_verifications(root, limit=None)
    hit = [r for r in rows if str(r.get("verification_id")) == want]
    if not hit:
        return None
    if len(hit) > 1:
        got = dict(hit[0])
        got["ambiguous"] = len(hit)
        return got
    return hit[0]


def signing_gate_problem(row: Mapping[str, Any]) -> str:
    """台账那一行记下的"引用核实没查成"那一档（空串 = 没记，或记的是查成了）。

    为什么单独一格：`problem`（依赖台账读不出来）不是 `citation_checks` 里的任何一档
    —— 它是"这一档没查成"，而空数组只说明"没有条目可核"。两者折平之后，"没查成"就
    长成了"没有引用"（那一版 `signs_bit3` 只读 `citation_checks`，于是这种行照样签）。
    历史行没有 `citation_gate` 这一格 ⇒ 空串，读数逐字不变。
    """
    gate = row.get("citation_gate")
    if not isinstance(gate, Mapping):
        return ""
    return str(gate.get("problem") or "").strip()


def signs_bit3(row: Mapping[str, Any]) -> bool:
    """这一行能不能签五元位第 3 位（§3.21 五：`成立` 且没有未解决的 error）。

    再加一条（业主 2026-10-26）：引用核实里只要有一条挡住签字的档（`stronger` /
    `unrelated` / `inadmissible` / `unknown`），这一签就不许落地。硬闸放在这里而不是只
    放在写路径上，是因为"读者眼里的成立"由这一格读出来 —— 手写一条成立行与 V 自己判了
    成立没有区别，两者都得过同一道闸。历史行没有 `citation_checks` 这一格 ⇒ 不受影响。

    同一道闸也认 `citation_gate.problem`（`:func:`signing_gate_problem`）：台账里记着
    "依赖台账读不出来"的行，哪怕 `citation_checks` 是空数组（空数组什么都不挡），也不许
    签 —— "没查成"与"核过、没有引用"必须分开。
    """
    if str(row.get("verdict") or "") != "成立":
        return False
    if int(row.get("unresolved_errors") or 0) != 0:
        return False
    if signing_gate_problem(row):
        return False
    return not citation_blocks(row)


def bit3_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """把一行审校翻成五元位第 3 位那份读数（交给 `evidencebits.bits_of`）。

    签不了（`有毛病` / `看不出来` / 有未解决 error）⇒ 返回 `{}`（第 3 位保持空）——
    这不是"忘了写"，是"没签"。

    凭据里带 `proof_no` 与 `proof_sha256`（2026-10-22）：读侧要拿它们回答"位上说审过的
    那一份，还是不是现在这一份"（`evidencebits.bits_from_row` 与收工门的 R10 都读这两格）。
    """
    if not signs_bit3(row):
        return {}
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    return {
        "reviewed": True,
        "reviewed_by": {
            "verifier": str(row.get("verifier") or "V"),
            "verification_id": str(row.get("verification_id") or ""),
            "round": row.get("round"),
            "verdict": str(row.get("verdict") or ""),
            "evidence": f"verifications/{sid}.jsonl#"
                        f"{row.get('verification_id')}",
            "findings": list(row.get("findings") or []),
            "proof_no": proof_no_of(row),
            "proof_sha256": str(row.get("proof_sha256") or ""),
        },
    }


def _verification_line(row: Mapping[str, Any]) -> str:
    """台账的一行怎么落盘（唯一实现：追加与撤回都拿它算字节）。"""
    return json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) + "\n"


def _append_verification(path: Path, row: Mapping[str, Any]) -> int:
    """追加一行，返回追加前的文件字节数（撤回时按它截断）。"""
    line = _verification_line(row).encode("utf-8")
    before = path.stat().st_size if path.exists() else 0
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line.decode("utf-8"))
    return before


def _rollback_append(path: Path, before: int, row: Mapping[str, Any]) -> bool:
    """把刚追加的那一行撤掉（只撤我们自己的那一行）；撤不动 ⇒ False。

    判据是"文件尾逐字等于我们写的那一行"：文件尾若已经变成别人的行，截断会
    删掉别人的记录 —— 那种情况下宁可留着我们这一行（它确实发生过），也不动别人的。
    """
    want = _verification_line(row).encode("utf-8")
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if data[before:] != want:
        return False
    try:
        with path.open("r+b") as fh:
            fh.truncate(before)
        return True
    except OSError:
        return False


def _reviewed_statement_row(found: Mapping[str, Any], verification_row: Mapping[str, Any],
                           *, proof_text: str, proof_no: int = 1) -> dict[str, Any]:
    """命题那一行改成"那一份证明的第 3 位已签"的样子。

    只动四处：那一份证明的 `reviewed`（#p1 = `bits.reviewed` 的汇总位；#p2+ 另外把
    `proofs` 清单里对应项标上）、逐条证明的那张表
    （`bits.evidence.reviewed_by_proof = {"1": true, "2": false, ...}`）、逐条证明的
    "那一签盖住哪一份正文"那张表（`bits.evidence.reviewed_sha_by_proof`）与凭据
    `reviewed_by`；别的一格不碰。等级必须现算
    （`evidencebits.normalize_raw` 的唯一入口）：盘上那份 `grade` 只是缓存，写下去的
    必须与现算逐字相同，否则提交期 `bits_shape_problems` 会拒收这一笔。

    ## 逐条表为什么必须整表写，而不是只写被签的那一格
    业主的负控是"签了 #p1、#p2 读成 False"。只写 `{"1": true}` 的话，`#p2` 是"表里
    没有这一格"——而"没有"与"有、值为 False"在读侧长得不一样：前者要靠调用方记得
    缺省是 False，后者是直接读出来的结论。所以这里把 `proof_list` 里每一份都列出来，
    被签的那一份为 True，其余按原来的值（没有再按 False）。汇总位
    `bits.reviewed` 的语义不变：任一份为 True 即 True。

    ## 第二张表为什么也整表写（sha 那一格）
    汇总位要回答"还有没有一份证明仍盖着现在这一份正文"。`reviewed_by` 只留最近那一签，
    只核它会让"签过 #p1、之后改了 #p2"读成没审过。所以逐条记下每一签的 sha：被签的
    那一份换成这一签的 `proof_sha256`，其余保留原值（没有就写空串 = 这一份判不了）。
    """
    from . import evidencebits as _EB   # 惰性：只在真写这一行时需要（不新增模块级依赖边）

    new = dict(found)
    # 证明号已经在 `sign_statement` 判过（`proof_no_strict`：没给 ⇒ canonical，给了坏值 ⇒
    # 拒）；这里再走一遍同一个函数是防"将来有人直接调本函数"时把 0 静默折成 #p1。
    no = proof_no_strict(proof_no)
    payload = bit3_payload(verification_row)
    reviewed_by = dict(payload.get("reviewed_by") or {})
    bits = dict(new.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    # 逐条表整表写（含未签的那几份为 False）：`#p2` 不许借 `#p1` 的光。
    per = {str(n): bool(v) for n, v in
           (_EB.reviewed_by_proof(new) or {}).items()}
    per = {str(n): bool(per.get(str(n), False)) for n, _ in proof_list(new)}
    per[str(no)] = True
    ev[_EB.REVIEWED_BY_PROOF_KEY] = per
    # 逐条证明的"那一签盖住的是哪一份正文"：`{证明号: sha256}`（没签过 / 判不了的写空串）。
    # 汇总位按"任一条仍 in-sync ⇒ True"读，靠的就是这一格（见 `_stale_review_cleared`）。
    sha_by_proof = {str(n): str(v) for n, v in
                    (_EB.reviewed_sha_by_proof(new) or {}).items()}
    sha_by_proof = {str(n): str(sha_by_proof.get(str(n), "")) for n, _ in proof_list(new)}
    sha_by_proof[str(no)] = str(verification_row.get("proof_sha256") or "")
    ev[_EB.REVIEWED_SHA_BY_PROOF_KEY] = sha_by_proof
    # 命题那一行的 `bits.reviewed` 是"这条命题至少有一份证明被审过"的汇总位（老读者
    # 只认它）；真正的凭据按证明记：`reviewed_by` 里带 `proof_no` 与 `proof_sha256`，
    # 于是"这一位说的是哪一份"不再靠猜。
    ev["reviewed_by"] = reviewed_by
    bits["reviewed"] = any(per.values())
    bits["evidence"] = ev
    new["bits"] = _EB.normalize_raw(bits, origin=str(new.get("origin") or "own_result"),
                                    kind=str(new.get("kind") or ""))
    if no > 1:
        entries = [dict(p) if isinstance(p, Mapping) else p
                   for p in (new.get(PROOFS_KEY) or [])]
        for p in entries:
            if isinstance(p, dict) and proof_no_of(p) == no:
                p["reviewed"] = True
                p["reviewed_by"] = dict(reviewed_by)
        new[PROOFS_KEY] = entries
    return new


def _kind_upgrade_from_signature(row: Mapping[str, Any], *, root: str | Path,
                                 verifier: str) -> dict[str, Any]:
    """V 判「成立」之后，按证据位把这一行的 `kind` 现算一遍（D-69）。

    ## 为什么它在签名这一笔里（断链在哪）
    D-37 已经有"kind 该不该跟着证据升"的唯一判据（`evidencebits.kind_following_grade`，
    纯读），但它的两个写侧落点都不在"V 签字"这条路上：
    `secretary._promote_governance` 只在"同一份内容再交一次"时才跑，
    `agent_b.register_statement` 的那一格只在第 4 位（形式化）同步出变化时才跑。
    于是真机 sylow3 那种形态 —— V 的台账里判「成立」、`bits.evidence.reviewed_by_proof`
    是 `{"1": true}`，而 `statements` 那一行的 `kind` 仍是 `conjecture` —— 没有任何一步会
    去改它：读的人（G 写稿 / H 审校 / 收工门）读 `kind`，于是"这是定理"这句话在盘上
    不存在，论文却已经把它排成 lemma / theorem。

    这一格就是那条断链的补口：台账那一行刚追加进 `verifications/<命题号>.jsonl`
    （同一个事务里），`kind_following_grade` 现在读得到那一签，于是把它放在
    `_reviewed_statement_row` 之后、`tx.upsert` 之前 —— 位与档位同一笔事务落盘。

    ## 只抬 `kind`，不碰 `evidence_kind`
    `evidence_kind` 的抬档已经有一条正路（秘书那一支，凭据是同一个
    `verifications.proof_review_gap`），而 `kind` 那一格没有任何一条正路会在签字之后
    到达。两件事各修一处，不再造第二份 `evidence_kind` 口径。

    ## 三态（判不了就不抬）
    只有 `kind_following_grade` 说 `state="upgraded"` 时才改那一格：`held`（凭据不够）
    与 `unreadable`（五元位算不出来）都原样返回 —— "没判成"绝不折成"已经升了"。
    这一笔也绝不降档：起点只认 `conjecture`（`KIND_UPGRADABLE_FROM`），别的 kind 一个字不动。

    返回 `{"row", "kind_upgrade", "note"}`：`row` 是（可能）改过 `kind` 的那一行，
    `kind_upgrade` 是与秘书那一支同形的留痕（`from` / `to` / `basis` / `grade` /
    `by` / `at`），`note` 是给返回读数看的那一句「因 V 判成立而抬档：…（依据 …）」。
    """
    from . import evidencebits as _EB   # 惰性：与 `_reviewed_statement_row` 同一条纪律

    out: dict[str, Any] = {"row": dict(row), "kind_upgrade": {}, "note": ""}
    read = _EB.kind_following_grade(out["row"], root=root)
    if str(read.get("state") or "") != "upgraded":
        return out
    target = str(read.get("kind") or "")
    before = str(out["row"].get("kind") or "")
    if target not in _EB.KIND_UPGRADE_TARGETS or target == before:
        return out
    basis = str(read.get("basis") or "")
    out["row"]["kind"] = target
    out["row"]["_kind_upgrade"] = {
        "from": before, "to": target, "basis": basis,
        "grade": str(read.get("grade") or ""),
        "by": str(verifier or "verifier-V"), "at": S.now_iso(),
    }
    out["kind_upgrade"] = dict(out["row"]["_kind_upgrade"])
    out["note"] = (f"因 V 判成立而抬档：{before or '（空）'}→{target}"
                   f"（依据 {basis or '台账里那一签'}）")
    return out


def sign_statement(store: Any, *, row: Mapping[str, Any], proof_text: str,
                   path: Path | None = None, proof_no: Any = None) -> dict[str, Any]:
    """把一签写回 `statements` 那一行里那一条证明的第 3 位（与台账同一次写）。

    ## 这一格为什么原来永远是 False
    第 3 位的唯一写者是 B 的 `register_statement`，而它按设计不替 V 签字（`BIT_OWNERS`：
    第 3 位的 owner 是 V）；V 自己的写口（本模块的 `record_verification`）当时只写台账
    那个文件，从来不碰 `statements`。于是"V 真的签了、台账上写着成立"与"命题那一行
    的 `reviewed` 位"之间没有连接：收工门的 R10 读位 ⇒ 恒 0。这一格就是那条断链的补口。

    ## 不借光（多证明模型）
    签名只翻被签的那一份（`proof_no`）的 `reviewed`；别的证明一个字不动。
    `proof_no > 1` 而命题行的证明清单里没有那一份 ⇒ 只落台账、不翻位（没有可翻的
    那一条证明），理由串写清 —— 不许把凭据记到 #p1 头上。

    ## 证明号：没给与给了坏值必须分开（2026-10-22 审计第 3 条）
    `proof_no=None` = 没给 ⇒ 按这一行自己记的那一格（老行只有 `rev` 时由
    :func:`proof_no_of` 按正名读，兼容、不迁移）；给了但 :func:`proof_no_strict` 认不出
    ⇒ 不追加台账、不改位，`reason` 点名"证明号认不出"。改前写的是
    `as_proof_no(proof_no) or proof_no_of(row)`：0 被折成这一行自己的号，
    于是"号给错了"与"号没给"在台账上长得一模一样。

    ## 顺序与回滚（为什么不是纯原子事务）
    台账是追加式文件、`statements` 是快照 JSON，两者不可能进同一个事务。所以取这个顺序：
    ① 在 `statements` 的事务里（事务已持有该表锁 ⇒ 并发签同一行时"读-改-写"是原子的）
       先追加台账那一行；② 改内存里那一行（那条证明的 `reviewed=True` + 凭据换成本签）；
    ③ 提交。提交失败 ⇒ 把刚追加的那一行撤回（只撤我们自己的那一行），整笔"没发生"；
    撤回不了 ⇒ 留着台账行并如实报"位没写成"—— 签名确实发生过，抹掉它比留一条
    "位没跟上"更坏；而读侧（`review_standing`）按台账现算，所以断链不会因此复现。

    ## `before = -1` 不再兼任两义（2026-10-22 审计第 5 条）
    改前 `before` 既是"追加前的字节数"又是"到底试没试过追加"：追加本身失败时它还是 -1，
    于是理由串照样写"台账那一行留着（签名确实发生过）"—— 而盘上一个字节都没有。
    现在追加落在哪一态由 `append_state` 单独记（`not_attempted` / `appended` / `failed`），
    理由串据此分三句；`re_sign_required` 说清调用方是不是必须重签（只有"没落地"才要）。

    返回键：`written` / `reason` / `rolled_back` / `grade` / `statement_id` / `proof_no` /
    `proof_sha256` / `append_state` / `re_sign_required` / `kind_upgrade` / `upgrade_note`。
    `written=False` 的四种来路各有
    理由串：签不住第 3 位（不改位）、命题不在册或那一份证明不在（没有可写的行）、
    追加失败（连台账那一行都没写）、事务失败（附回滚结果）。

    ## D-69：同一笔事务里把 `kind` 跟着这一签抬上去
    见 :func:`_kind_upgrade_from_signature`。它只改 `kind` 那一格（起点只认 `conjecture`），
    判不了就一个字节都不动；抬了的时候 `kind_upgrade` / `upgrade_note` 两格把依据
    （`verifications/<命题号>.jsonl#v-…`）写出来，读的人不用去翻台账才知道凭什么。
    """
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    # 证明号：调用方给的那个（`proof_no`）；没给就按这一行自己记的那一格 —— 老行只有
    # `rev` 时由 `proof_no_of` 按正名读（兼容，不迁移）。
    out: dict[str, Any] = {
        "written": False, "reason": "", "rolled_back": False, "grade": "",
        "statement_id": sid, "proof_no": None,
        "proof_sha256": str(row.get("proof_sha256") or ""),
        #: 台账那一行落在哪一态（三态，不许折平）：
        #: `not_attempted` = 这一支根本不追加（签不住第 3 位 / 号认不出）；
        #: `appended` = 真追加了一行（撤回与否另看 `rolled_back`）；`failed` = 追加本身失败。
        "append_state": "not_attempted",
        #: 调用方是不是必须重签：只有"这一签没有落在台账上"（追加失败 / 已撤回）才为真。
        "re_sign_required": False,
        #: D-69：这一签有没有把 `kind` 抬上去（形状与秘书那一支的 `_kind_upgrade` 相同）：
        #: `{}` = 没抬（起点不是 conjecture / 凭据不够 / 位算不出来），那三档都不改盘。
        "kind_upgrade": {},
        #: 抬档的读数原话（「因 V 判成立而抬档：conjecture→theorem（依据 …）」）；
        #: 没抬时是空串。它不写进 `reason`：`reason` 只留"这一签没落成"的那几档。
        "upgrade_note": "",
    }
    try:
        no = proof_no_of(row) if proof_no is None else proof_no_strict(proof_no)
    except VerificationError as exc:
        out.update(re_sign_required=True,
                   reason=(f"{exc}；第 3 位一个字没动，台账里也没有这一签"))
        return out
    out["proof_no"] = no
    if not signs_bit3(row):
        out["reason"] = ("这一签签不住第 3 位（verdict 不是「成立」，或有未解决的 error）"
                         "⇒ 位不动：没签住的字不该改任何读数")
        return out
    ledger = path or verification_ledger_path(store.root, sid)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    append_state = "not_attempted"
    #: 追加前的字节数（只有 `append_state == "appended"` 时才有意义，撤回按它截断）。
    before = -1
    try:
        with store.tx("statements", actor=f"verifier-{row.get('verifier') or 'V'}",
                      note=f"verify.sign:{sid}#p{no}") as tx:
            found = tx.find("statements", stmt_id=sid)
            try:
                before = _append_verification(ledger, row)
            except OSError:
                # 追加本身失败：记下这一态再往外抛（理由串要据此说"整笔没发生"，
                # 不许说"签名确实发生过"）。
                append_state = "failed"
                raise
            append_state = "appended"
            out["append_state"] = append_state
            if found is None:
                out["reason"] = (f"`statements` 里没有命题 {sid} ⇒ 只落了台账（签名）那一行，"
                                 "第 3 位没有可写的行")
                return out
            if no > 1 and no not in {n for n, _ in proof_list(found)}:
                out["reason"] = (f"命题 {sid} 的证明清单里没有 #{no}（`{PROOFS_KEY}` 那一条）"
                                 "⇒ 只落了台账那一行；第 3 位不翻（不许把这一签记到 #p1 头上）")
                return out
            new = _reviewed_statement_row(found, row, proof_text=proof_text, proof_no=no)
            # ---- D-69：V 判「成立」⇒ 同一笔事务里按证据位把 `kind` 现算一遍。
            #
            # 位置在"位已经翻上去"之后、`tx.upsert` 之前：台账那一行刚追加进
            # `verifications/<号>.jsonl`，`kind_following_grade` 现在读得到那一签；
            # 判不了（`held` / `unreadable`）就原样不动（三态：不抬，也不降）。
            upgraded = _kind_upgrade_from_signature(
                new, root=getattr(store, "root", ""), verifier=f"verifier-{no}")
            new = upgraded["row"]
            tx.upsert("statements", new, note=f"verify.sign:{sid}#p{no}")
            out.update(written=True, grade=str((new.get("bits") or {}).get("grade") or ""),
                       kind_upgrade=dict(upgraded["kind_upgrade"]),
                       upgrade_note=str(upgraded["note"]))
    except Exception as exc:  # noqa: BLE001 - 写位失败要如实报（签名那一行可能已经在盘上了）
        rolled = (_rollback_append(ledger, before, row)
                  if append_state == "appended" and before >= 0 else False)
        if append_state == "failed":
            reason = (f"台账那一行也没写成（{type(exc).__name__}: {exc}）⇒ 第 3 位没写成，"
                      "整笔没发生（可以重试；必须重签）")
        elif rolled:
            reason = (f"第 3 位没写成（{type(exc).__name__}: {exc}）；"
                      "台账那一行已撤回（整笔没发生，可以重试）⇒ 必须重签")
        elif append_state == "appended":
            reason = (f"第 3 位没写成（{type(exc).__name__}: {exc}）；"
                      "台账那一行留着（签名确实发生过）；读侧按台账现算，不按这一位")
        else:
            # 连追加都没走到（例如事务加锁失败）：台账里没有这一签，整笔没发生。
            reason = (f"第 3 位没写成（{type(exc).__name__}: {exc}）；"
                      "台账那一行没有追加（整笔没发生）⇒ 必须重签")
        out.update(
            written=False, rolled_back=bool(rolled), append_state=append_state,
            re_sign_required=(not rolled and append_state != "appended"),
            reason=reason)
    return out


def _superseded_reading(row: Mapping[str, Any]) -> dict[str, Any]:
    """一条被更近的签盖过去的旧签（`review_standing` 的 `superseded` 元素）。

    它回答"这一份正文以前还被谁签过、签的是哪一版、结论是什么"：旧签仍然可见，
    但判定只看最近那一签（:func:`review_standing`）。字段刻意只留定位用的几格，
    正文与 findings 不回放 —— 那些在台账文件里逐字可查，读数层不复制历史。
    """
    return {
        "verification_id": str(row.get("verification_id") or ""),
        "verdict": str(row.get("verdict") or ""),
        "round": row.get("round"),
        "at": str(row.get("at") or ""),
        "proof_no": proof_no_of(row),
        "proof_sha256": str(row.get("proof_sha256") or ""),
        "signed_bit3": signs_bit3(row),
        "unresolved_errors": int(row.get("unresolved_errors") or 0),
        "why": str(row.get("why") or "")[:200],
    }


def review_standing(root: str | Path, *, statement_id: str, proof_text: str,
                    proof_no: int = 1) -> dict[str, Any]:
    """一条证明的第 3 位相对「它现在这一份正文」的读数（唯一判定口，纯读）。

    ## 判据（业主 2026-10-22 多证明模型）
    只看 `proof_no` 这一份证明的现行正文的 sha：同一份正文上按台账行序取最近那一签，
    它签住了 ⇒ `signed`；最近那一签的结论不是「成立」⇒ `rejected`；签的是旧版 ⇒
    `stale`（R10 不计，单列 `proofs_stale`）；这一份一次都没签 ⇒ `unsigned`（哪怕同一条
    命题的别的证明签过 —— 不许借光）；台账读不出来 ⇒ `unreadable`（没查成，不是通过）。
    更早的签不改判定，只进 `superseded`（仍可见：id / verdict / 那一签盖住的 sha）。

    ## 最近一签为什么必须能否决（2026-10-22 审计的第 3 条）
    改前先挑出有「成立」的那几签再取最后一条，于是"先成立、后改判有毛病"永远读回
    `signed`：后一次否决投不出去，旧的那一签被当成了免死金牌。改后同一份正文的覆盖集里
    只有最后那一签说了算；更早的签降为历史读数。
    "旧签名是历史，不是否决票"仍然成立，但它的方向被限定为：旧版上的结论（包括
    「有毛病」）不否决现行这一份上的「成立」那一签（哈希只回答"这份稿在你签完之后有没有
    被改过"）；反过来，同一份正文上更新的否决必须盖过更早的成立。

    ## 哈希在这里的角色：读数，不是授权
    `stale` 与 `rejected` 都不拦任何写入（见 :func:`proof_review_gaps`），它们只让第 3 位
    不计入、并各自有一个可读的理由。返回键：`checked` / `state` / `ok` / `in_sync` /
    `ledger_present` / `statement_id` / `proof_no` / `sha` / `verification_id` / `verdict` /
    `round` / `unresolved_errors` / `rows`（这条命题的台账总行数）/ `proof_rows`（本份
    证明的行数）/ `superseded` / `superseded_total` / `problems` / `ledger` / `why`。

    ## 证明号认不出 ⇒ `unreadable`，不折成 `#p1`（2026-10-22 收尾）
    `proof_no` 问的是"要看哪一份证明"，所以没给（`None` / 空串）才是 canonical；给了但
    :func:`as_proof_no` 认不出（`0` / `'abc'` / `2.0`）⇒ 返回 `checked=False`、
    `state="unreadable"`、`proof_no=0`，`why` 逐字点名"证明号认不出"。改前是
    `as_proof_no(proof_no) or 1`：一个坏号拿到的是 `#p1` 的读数，而读的人看不出号给错了
    （同样的折平还在 :func:`proof_text_of` / :func:`proof_label` 里，三处一起改的）。
    这一档是"没查成"（问的是哪一份都没有答案），不是"查过了、没签过"。
    """
    sid = str(statement_id or "").strip()
    no = _read_proof_no(proof_no)
    sha = proof_sha(proof_text)
    out: dict[str, Any] = {
        "checked": False, "state": "unsigned", "ok": False, "in_sync": None,
        "ledger_present": False, "statement_id": sid, "proof_no": no, "sha": sha,
        "verification_id": "", "verdict": "", "round": None,
        "unresolved_errors": 0, "rows": 0, "proof_rows": 0, "problems": [],
        "superseded": [], "superseded_total": 0,
        "ledger": "", "why": "",
    }
    if no < 1:
        # 证明号认不出 ⇒ "问的是哪一份"没有答案。这是"没查成"，不是"没签过"（三态纪律），
        # 也不许悄悄按 canonical 读：改前 `as_proof_no(proof_no) or 1` 会把它读成 `#p1`，
        # 于是"号给错了"的读数与"我要 #p1"逐字相同。
        out.update(
            checked=False, state="unreadable",
            why=(f"证明号认不出：收到 {proof_no!r}（合法写法是 1、2、3 … 或 "
                 "'2' / 'p2' / '#p2'）⇒ 不知道问的是哪一份证明，这一格**没查成**"
                 "（不是「没签过」，也不是「签过过期」）；读侧不把它折成 canonical（#p1）"))
        return out
    if not sid:
        out.update(checked=True, why="没有命题号 ⇒ 查不到台账（不是没签过）")
        return out
    try:
        path = verification_ledger_path(root, sid)
    except VerificationError as exc:
        out.update(checked=True, why=f"命题号 {sid!r} 不是编号形态（{exc}）⇒ 查不到台账")
        return out
    out["ledger"] = f"{VERIFICATIONS_DIR}/{sid}.jsonl"
    out["ledger_present"] = path.is_file()
    if not out["ledger_present"]:
        out.update(checked=True,
                   why=f"`{out['ledger']}` 不在盘上 ⇒ 一次审校都没有（不是签过过期）")
        return out
    rows, problems = JF.read_jsonl(path)
    out["rows"] = len(rows)
    out["problems"] = list(problems)
    if problems:
        out.update(state="unreadable",
                   why=(f"`{out['ledger']}` 有读不出来的行（{problems[:3]}）⇒ "
                        "第 3 位没查成（不是「没签过」，也不是「签过过期」）"))
        return out
    out["checked"] = True
    if not str(proof_text or "").strip():
        # 空正文不是"签过过期"：没有被审的对象，「签没签过」这件事无从谈起。
        out.update(why=(f"{proof_label(sid, no)} 的正文是空的 ⇒ 没有被审的那一份，"
                        "这一格既不是「签过」也不是「签过过期」"))
        return out
    mine = [r for r in rows if proof_no_of(r) == no]
    out["proof_rows"] = len(mine)
    if not mine:
        out.update(why=(f"`{out['ledger']}` 里没有 #{no} 这一份证明的签"
                        "（别的证明签过也不算 —— 不许借光）"))
        return out
    covering = [r for r in mine if str(r.get("proof_sha256") or "") == sha]
    # ---- 最近一签的判据（2026-10-22 审计后）：同一份正文上按台账行序取最后那一签。
    #
    # 改前这里先挑 `signed`（有「成立」的签）再取它的最后一条，于是"先成立、后改判有毛病"
    # 永远读成 signed —— 后一次否决投不出去，旧的那一签被当成了免死金牌。改后：在同一份
    # 正文的覆盖集里，最后那一签说了算；更早的签只留在 `superseded` 里可见，不参与判定。
    # 签名行本身是追加式的（台账不改历史），所以"最近"就是读出来的行序（`at` / `round`
    # 只做展示；时钟回拨不会把判定翻回去）。
    chosen = covering[-1] if covering else mine[-1]
    cut = next((i for i, r in enumerate(mine) if r is chosen), len(mine) - 1)
    superseded = mine[:cut]
    out.update({
        "verification_id": str(chosen.get("verification_id") or ""),
        "verdict": str(chosen.get("verdict") or ""),
        "round": chosen.get("round"),
        "unresolved_errors": int(chosen.get("unresolved_errors") or 0),
        #: 被这一签盖过去的旧签（仍可见、不参与判定）：按台账行序，逐条给 id / verdict /
        #: 那一签盖住的 sha。它是"旧签降为历史"的唯一读数格。
        "superseded": [_superseded_reading(r) for r in superseded],
        "superseded_total": len(superseded),
    })
    if covering and signs_bit3(chosen):
        out.update(state="signed", ok=True, in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）最近一签是"
                        f"「成立」：{out['verification_id']}（{out['ledger']}）"
                        + (f"；更早的 {len(superseded)} 签已降为历史"
                           "（见 superseded，不参与判定）" if superseded else "")))
        return out
    if covering:
        out.update(state="rejected", in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）最近一签是 "
                        f"{out['verification_id']}：verdict={out['verdict']!r}、"
                        f"unresolved_errors={out['unresolved_errors']} ⇒ 复核过、结论不是"
                        f"「成立」（why：{str(chosen.get('why') or '')[:120]}）"
                        + (f"；更早的 {len(superseded)} 签已降为历史（见 superseded），"
                           "不能把它翻回「成立」" if superseded else "")))
        return out
    out.update(state="stale", in_sync=False,
               why=(f"`{out['ledger']}` 里 {proof_label(sid, no)} 有 {len(mine)} 签，"
                    f"但没有一签盖住它现在这一份：最近一签 {out['verification_id']} 签的是"
                    f"另一版（台账 sha256={str(chosen.get('proof_sha256') or '')[:12]}…，"
                    f"现行这一份={sha[:12]}…）⇒ 待复核（stale）：第 3 位不计，"
                    "等 V 对现在这一份重签"))
    return out


def statement_review_reading(root: str | Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """一条命题在「多证明」模型下的第 3 位读数（纯读，逐条证明分开）。

    ## 为什么命题级读数不能只有一个布尔
    多证明模型（业主 2026-10-22）里，每条证明各自有第 3 位：`#p1` 签过不等于 `#p2`
    签过（不许借光），`#p2` 签过也不等于 `#p1` 签过。命题级要回答的是"这条定理有没有
    一份被审过的证明"，所以它是逐条读数的汇总，而逐条读数各自独立。

    返回键：
    - `proofs`: `[{proof_no, state, ok, in_sync, reviewed, grade, formal,
      proof_sha256, verification_id, why}]`（每条证明一条，按 `proof_no` 升序）；
      其中 `formal` 是这一条证明自己的第 4 位（`{证明号: 状态}` 里的那一格，
      四态 + 读侧产生的 `stale`）：`#p1` 形式化通过不等于 `#p2` 形式化通过，
      所以它必须逐条给，并且与 `grade` 成对读；
    - `reviewed`: 命题级 —— 至少一条证明 `signed`（定理档取"最高"就落在这一格）；
    - `grade`: 逐条证明各自的档里最高的那一档（`_highest_grade`）：一条 in-sync 都没有
      ⇒ `conjecture`；两条各缺一半（一条有形式化、另一条有签名）⇒ 不许凑出定理
      （借光由逐条派生挡掉，见 `proofs[*]["grade"]`）；
    - `state`: 命题级五态（有 signed 就 `signed`；否则有 stale 就 `stale`；否则有
      rejected 就 `rejected`；否则 `unsigned`；有 unreadable 且没别的 ⇒ `unreadable`）；
    - `proofs_unreviewed` / `proofs_stale` / `proofs_rejected`: 逐条证明的编号写法
      （`000004#p2`），不许折进"没有证明"：它们是两条独立读数；
    - `proofs_superseded`: 被更近的签盖过去的旧签（写法 `000004#p1:v-000001`）；
      它们仍可见，但不参与判定（最近一签说了算）；
    - 概念行：`reviewed=False` / `grade=not_applicable` 短路，不产出上面那些计数项；
    - `checked` / `ledger_present` / `problems` / `why`。
    """
    from . import evidencebits as _EB   # 惰性：等级的唯一入口
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    kind = str(row.get("kind") or "")
    bits = _EB.bits_from_row(row)
    if kind == "concept":
        # ---- 概念行短路（2026-10-22 审计的第 5 条） -----------------------------
        #
        # 改前这里照样去读台账，然后把每条的 state 写成 unsigned、grade 写成
        # not_applicable，却没有把 `ok` 一起压掉：只要概念行的 proof_text 撞上一次
        # 「成立」的签，`reviewed = any(e["ok"])` 就把它抬成 `reviewed=True`、
        # `state='signed'`，而同一条读数的 `proofs[0]` 写着 `unsigned`、
        # `grade='not_applicable'` —— 一条读数自己跟自己矛盾，R10 也跟着把它算进去。
        # 概念不参与等级链（`derive_grade` 对 concept 短路），所以这一格整份是
        # "不适用"：reviewed 恒 False、grade 恒 not_applicable，也不产出
        # `proofs_unreviewed` / `proofs_stale` / `proofs_rejected` 这些计数项
        # （它们会让"概念"被当成"没签过的证明"灌进读数）。
        entries = [{
            "proof_no": no, "label": proof_label(sid, no),
            "state": "unsigned", "ok": False, "in_sync": None,
            "reviewed": False, "grade": _EB.GRADE_NOT_APPLICABLE,
            "proof_sha256": proof_sha(text), "verification_id": "",
            "superseded": [],
            "why": ("概念行不参与等级链（`evidencebits.derive_grade` 对 "
                    "kind='concept' 短路成 not_applicable）⇒ 这一格对它不适用，"
                    "既不算审过，也不算没审过"),
        } for no, text in proof_list(row)]
        return {
            "checked": True,
            "ledger_present": False,
            "statement_id": sid,
            "proofs": entries,
            "state": "unsigned",
            "reviewed": False,
            "grade": _EB.GRADE_NOT_APPLICABLE,
            "proofs_unreviewed": [],
            "proofs_stale": [],
            "proofs_rejected": [],
            "proofs_superseded": [],
            "superseded_total": 0,
            "problems": [],
            "why": (f"{sid or '（没有编号）'} 是概念行（kind='concept'）：概念不参与"
                    "等级链，没有「审过的证明」这一档 ⇒ reviewed=False、"
                    "grade=not_applicable，也不计入 R10"),
        }
    entries: list[dict[str, Any]] = []
    unreviewed: list[str] = []
    stale: list[str] = []
    rejected: list[str] = []
    superseded_labels: list[str] = []
    problems: list[str] = []
    ledger_present = False
    #: 第 4 位（形式化）在逐条证明上的读数：`{证明号: 状态}`。汇总那一层是 OR
    #: （业主 2026-10-22：「但凡任意一个路径通过核验，它就是对的」），而逐条这一层是
    #: "哪一条路径验过" —— 两条都要：只读汇总会让 `#p2` 借 `#p1` 的光。
    formal_states = _EB.formal_by_proof(bits)
    for no, text in proof_list(row):
        st = review_standing(root, statement_id=sid, proof_text=text, proof_no=no)
        ledger_present = ledger_present or bool(st.get("ledger_present"))
        problems.extend(str(p) for p in (st.get("problems") or []))
        per = dict(bits)
        per["reviewed"] = bool(st.get("ok"))
        # 逐条证明的第 4 位：只有这一条自己被验过才算（不许拿别条的顶）。
        per[_EB.FORMAL_BIT] = formal_states.get(no, "pending")
        grade = _EB.derive_grade(per, kind=kind)
        state = str(st.get("state") or "unsigned")
        old = [dict(x) for x in (st.get("superseded") or [])]
        for item in old:
            superseded_labels.append(
                f"{proof_label(sid, no)}:{str(item.get('verification_id') or '?')}")
        entries.append({
            "proof_no": no, "label": proof_label(sid, no), "state": state,
            "ok": bool(st.get("ok")), "in_sync": st.get("in_sync"),
            "reviewed": bool(st.get("ok")), "grade": grade,
            #: 这一条证明自己的第 4 位（`evidencebits.FORMAL_PATH_STATES` 的取值：
            #: 四态 + 读侧产生的 `stale`）。它与 `grade` 成对："这条证明到什么档"
            #: 只有这两格合起来才说得清（#p1 形式化通过、#p2 没验 ⇒ 两条各自的档不同）。
            "formal": per[_EB.FORMAL_BIT],
            "proof_sha256": str(st.get("sha") or ""),
            "verification_id": str(st.get("verification_id") or ""),
            #: 被最近那一签盖过去的旧签（仍可见、不参与判定）。`review_standing`
            #: 的同一格原样下传，逐条证明分开。
            "superseded": old,
            "why": str(st.get("why") or ""),
        })
        if state == "unsigned":
            unreviewed.append(proof_label(sid, no))
        elif state == "stale":
            stale.append(proof_label(sid, no))
        elif state == "rejected":
            rejected.append(proof_label(sid, no))
    reviewed = any(e["ok"] for e in entries)
    states = [e["state"] for e in entries]
    if reviewed:
        state = "signed"
    elif "stale" in states:
        state = "stale"
    elif "rejected" in states:
        state = "rejected"
    elif "unreadable" in states:
        state = "unreadable"
    else:
        state = "unsigned"
    out_bits = dict(bits)
    out_bits["reviewed"] = reviewed
    #: 命题级的档 = 逐条证明里最高的那一档（`draft/39` §3.14 的"在 in-sync 的证明里取最高"）。
    #:
    #: 改前这里先把第 3 位取 OR、第 4 位取 OR，再派生一次：多证明模型下那会让
    #: `#p1` 的形式化通过 + `#p2` 的 V 签名凑出一档 —— 两条各缺一半，凑出来的档
    #: 谁也没有（借光）。现在每一档都由一条证明自己撑起来，命题级只是取最高的那条。
    grade = _highest_grade([str(e.get("grade") or "") for e in entries])
    if not grade:
        grade = _EB.derive_grade(out_bits, kind=kind)
    why = ""
    if not reviewed:
        if state == "stale":
            why = (f"{sid} 的证明都签过旧版（或签过但没盖住现在这一份）"
                   f"（stale：{'、'.join(stale)}）⇒ 一条 in-sync 的签名都没有")
        elif state == "rejected":
            why = (f"{sid} 的证明现在这一份被签过、结论不是「成立」"
                   f"（rejected：{'、'.join(rejected)}）")
        elif state == "unreadable":
            why = f"{sid} 的验证台账读不出来 ⇒ 第 3 位没查成（不是「没签过」）"
        else:
            why = (f"{sid} 的证明一次都没签（{'、'.join(unreviewed) or '没有证明'}）"
                   "⇒ 第 3 位是没签过，不是签过过期")
    return {
        "checked": not problems,
        "ledger_present": ledger_present,
        "statement_id": sid,
        "proofs": entries,
        "state": state,
        "reviewed": reviewed,
        "grade": grade,
        "proofs_unreviewed": unreviewed,
        "proofs_stale": stale,
        "proofs_rejected": rejected,
        #: 被更近的签盖过去的旧签（写法 `000004#p1:v-000001`）：它们仍在台账里、
        #: 仍读得出来，但不参与命题级判定（最近一签说了算，见 `review_standing`）。
        "proofs_superseded": superseded_labels,
        "superseded_total": len(superseded_labels),
        "problems": problems,
        "why": why,
    }


def _highest_grade(grades: Sequence[str]) -> str:
    """几条证明各自的档 ⇒ 命题级那一档（`GRADES` 里最靠后的那个）。

    空清单 / 只有认不出的取值 ⇒ 空串（调用方退回"按汇总位现算"那一条路，不猜）。
    `not_applicable`（概念行）不在 `GRADES` 里，所以它到不了这里：概念行在
    `statement_review_reading` 里是短路的一支。
    """
    from . import evidencebits as _EB   # 惰性：与 `statement_review_reading` 同一处依赖

    known = [str(g) for g in grades if str(g) in _EB.GRADES]
    if not known:
        return ""
    return max(known, key=_EB.GRADES.index)


def statement_grade(root: str | Path, row: Mapping[str, Any]) -> str:
    """这条命题的定理档（多证明模型里"在 in-sync 的证明里取最高"的唯一落点）。

    实现就是 :func:`statement_review_reading` 的 `grade`：`proof` 位是行级共用的，
    `reviewed` 取"至少一条证明 signed"（等价于"在 in-sync 的证明里取最高"：一条 in-sync
    都没有 ⇒ `conjecture`）。判据本体仍是 `evidencebits.derive_grade`，这里只喂给它
    汇总后的第 3 位。
    """
    return str(statement_review_reading(root, row).get("grade") or "")


def banned_markers_in(proof_text: str) -> list[str]:
    """这份证明里命中了哪些硬禁令短语（I10 的机械那一半，可离线复算）。"""
    text = str(proof_text or "")
    return [m for m in HARD_BAN_MARKERS if m in text]


#: `proof_review` 这一档的凭据判据码（2026-10-19，堵「假 proof_review」）。
#:
#: 两个码各有落点，不许合成一个（一个是写入期拒收，一个是审计期点名 ——
#: 同一句话在两个出口上的读者不同：写者要"改哪里"，审计要"存量有多少"）：
#:
#: - `CODE_WRITE`：写入期闸（`store.tx` 提交时）—— 当场拒收，一行都不写；
#: - `CODE_AUDIT`：审计期档（`verify._check_13`）—— error 级点名，存量照读。
CODE_WRITE = "proof_review_without_evidence"
CODE_AUDIT = "proof_review_without_verification"

#: `proof_review` 这一档在 `statements.evidence_kind` 里的取值（口径见 `schema.EVIDENCE_KINDS`）。
PROOF_REVIEW_KIND = "proof_review"


def _pending_signed(root: str | Path, proof_text: Any) -> dict[str, Any] | None:
    """命题还没在册时 V 审的那一签（按这一份正文的 sha 认领）；没有 ⇒ `None`。

    D-34：`verifications/pending/<sha>.jsonl` 里的那一行是真的审过（七项机械会审），
    只是当时没有命题号可挂。它是"先签后登记"那一半的证据面，所以在
    :func:`proof_review_gap` 里与"这一条命题台账里的那一签"同等看待 —— 判据仍然只有
    这一处（`signs_bit3`：成立且没有未解决 error）。
    """
    text = str(proof_text or "")
    if not text.strip():
        return None
    try:
        got = pending_sign(root, proof_shas=(proof_sha(text),))
    except VerificationError:
        return None
    if not got.get("found"):
        return None
    return got


def _gap_from_pending(out: dict[str, Any], checks: list[dict[str, Any]],
                      got: Mapping[str, Any], *, statement_id: str) -> dict[str, Any]:
    """:func:`_pending_signed` 认到那一签之后，把 `proof_review_gap` 的读数摊开。

    判据与"台账那一路"同一条（`signs_bit3`）：`成立` 且没有未解决 error 才算签住。
    """
    row_ok = (str(got.get("verdict") or "") == "成立")
    out["ledger"] = str(got.get("ledger") or "")
    out["verification_id"] = str(out["ledger"]).split("#")[-1]
    out["verdict"] = str(got.get("verdict") or "")
    out["rows"] = 1
    out["sha_matches"] = True
    out["checked"] = True
    checks[1].update(ok=bool(row_ok),
                     detail=(f"{out['ledger']}（命题还没在册时审的那一签）"
                             if row_ok else f"{out['ledger']}：结论不是「成立」"))
    checks[2].update(ok=bool(row_ok),
                     detail=("按这一份正文的 sha 认领到（待登记的那一签）"
                             if row_ok else "签的不是这一份"))
    if not row_ok:
        out["state"] = "rejected"
        out["why"] = (f"命题 {statement_id} 的证明在 pending 台账里那一签是 "
                      f"{out['verdict']!r}（要「成立」）⇒ 复核过、结论不是成立")
        return out
    out["state"] = "signed"
    out["ok"] = True
    out["why"] = (f"命题 {statement_id} 的凭据在 `{out['ledger']}`：V 在命题还没在册时"
                  "审过这一份并判「成立」，按这一份正文的 sha 认领到"
                  "（「先签后登记」与「先登记后签」是同一件事）")
    return out


def proof_review_gap(root: str | Path, row: Mapping[str, Any],
                     proof_no: Any = None) -> dict[str, Any]:
    """一条 `evidence_kind="proof_review"` 的命题有没有凭据 —— 纯读，不写任何东西。

    判据逐字来自 `schema.EVIDENCE_KINDS` 上面那段定义（2026-10-19 之前它只是注释，没有代码
    强制）：`proof_review` —— 证明经逐行审阅（`statements` 表的 `proof_text` 非空 + V 的
    `verifications` 里那一条签「成立」）。三条都要成立（缺哪条就报哪条，`why` 里说清）：
    1. `proof_text` 非空 —— 没有被审的那份证明，"审过"无从谈起；
    2. `verifications/<命题号>.jsonl` 里有一条盖住现行这一份正文的签（判定只走
       `review_standing`：那一份证明现在的 sha 有 `signs_bit3` 的签）；
    3. 那一签带着这一份正文的 `proof_sha256` —— 哈希回答"这份稿在你签完之后有没有被改过"。
    2026-10-22 口径（业主）：第 3 条是读数，不是授权凭证。所以 `ok=False` 有两种完全
    不同的来路，`state` 把它们分开：`stale`（签的是旧版 ⇒ 待复核）与 `rejected`
    （签的就是这一份、结论不是「成立」）。写入期闸只拒后者与"一次都没签"，见
    :func:`proof_review_gaps` —— "正文改过了"不许成为拒收理由。
    三态：读不到台账 / 坏行 ⇒ `ok=False` 且 `checked=False`（没查成，不是"通过"）；台账
    读得出、只是`一次都没签` ⇒ `checked=True`（查过了，结论是没凭据）。

    ## 任一份证明签住即放行（2026-10-22 审计最危险的一批，第 1 条）
    `evidence_kind` 是命题级的声明，而多证明模型里每一条证明各自有第 3 位
    （见 :func:`statement_review_reading`）⇒ 命题级凭据的判据是"至少一份证明 signed"。
    改前这里写死 `review_standing(..., proof_no=1)`：只认 canonical 那一份，于是
    `#p1` 未签、`#p2` 已成立的存量 `proof_review` 行既写不进去（闸整笔拒收），
    拒收之后撤回又抹掉台账那一行（同一批审计的两半）。
    逐条那一侧仍然分开：`state` / `proof_no` / `verification_id` / `sha_matches` / `why`
    说的是"当前这一份"（`proof_no` 参数；没给就按这一行自己记的号、没有就 canonical），
    于是拒信仍指得出是哪一份证明缺凭据，而不是一句"这一行不行"。

    返回键：`ok` / `checked` / `why` / `state` / `proof_no` / `statement_id` /
    `verification_id` / `verdict` / `round` / `unresolved_errors` / `sha_matches` /
    `ledger` / `rows` / `problems` / `checklist`；`checklist` 是逐项过关读数
    （`[{"item", "ok", "detail"}]`，三条与上面一一对应），只为拒信存在（业主 2026-10-19 的口径：
    "拒收消息要让人/模型一眼看出该补哪一项"），不参与判据 —— 写错只改可读性。
    """
    sid = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
    out: dict[str, Any] = {
        "ok": False, "checked": False, "why": "", "statement_id": sid,
        "verification_id": "", "verdict": "", "round": None,
        "sha_matches": None, "ledger": "", "rows": 0, "problems": [],
        #: 现行这一份的读数（`REVIEW_STATES`）与证明号：`ok` 只在 `signed` 时为真。
        #: `state="stale"` 是"签过、但签的是旧版"—— 它是待复核这个读数，不是"没签过"。
        "state": "", "proof_no": None,
    }
    checks: list[dict[str, Any]] = [
        {"item": "proof_text 非空（有被审的那份证明）", "ok": False, "detail": "还没判到"},
        {"item": f"`verifications/<命题号>.jsonl` 里有签「成立」的那一行"
                 f"（verdict=成立 且 unresolved_errors=0）", "ok": False, "detail": "还没判到"},
        {"item": "那一行的 `proof_sha256` 等于现在这一版 `proof_text` 的 sha256",
         "ok": False, "detail": "还没判到"},
    ]
    out["checklist"] = checks
    # ---- 概念行：永远不算"有证明"（2026-10-21，本批缺陷一的读侧）
    #
    # 真机读数（`projects/mp3/data/statements.json`）：1143 条概念行每一条
    # 都带 `proof_text`（值是一个哨兵 `concept:primitive`）。于是"这一行有没有证明"
    # 的读数被顶高：`prose_reviewed_statements` 数的是"`proof_text` 非空且 V 签了
    # 成立"，一条概念行只要撞上一次签名就能进那一格；而 `proof_review_gap` 也只问
    # `proof_text` 非空 —— 它会把概念行当成"有一条被审过的证明"的候选。
    #
    # 判据只有一句：概念不参与等级链（`draft/97` §14.5，
    # `evidencebits.derive_grade` 对 `kind="concept"` 短路成 `not_applicable`），
    # 所以它既没有"证明"这一档，也不可能"有证明"。两档要分开说：
    # 带 `proof_text` 是写入侧的污染（要点名，让存量看得见），
    # 不带是正常（这一格对它不适用 —— 不是"缺证明"）。
    if str(row.get("kind") or "") == "concept":
        out["checked"] = True
        text_concept = str(row.get("proof_text") or "")
        if text_concept.strip():
            checks[0].update(ok=False, detail=f"{len(text_concept)} 字（概念行不该有）")
            checks[1]["detail"] = "概念行没有'证明'这一档，不适用"
            checks[2]["detail"] = "同上"
            out["why"] = (f"概念行不该带证明文本：命题 {sid or '（没有编号）'} 是 "
                          f"kind='concept'，而它的 `proof_text` 非空"
                          f"（{text_concept[:40]!r}）⇒ 概念不参与等级链，"
                          "`proof_text` 对它不是证明，而是一个哨兵；"
                          "任何'有没有证明'的读数都会被它顶高。"
                          "写入侧已经堵住（`conceptrows.concept_statement` 不写这一格），"
                          "这一条是存量行的点名：把这一格清空（定义/待补标记都在别的字段里）")
        else:
            checks[0]["detail"] = "概念行没有 proof_text（正常：概念不参与等级链）"
            checks[1]["detail"] = "概念行没有'证明'这一档，不适用"
            checks[2]["detail"] = "同上"
            out["why"] = (f"命题 {sid or '（没有编号）'} 是概念行（kind='concept'）："
                          "概念没有'证明'这一档（不参与等级链）⇒ 这一格对它**不适用**，"
                          "不许读成'有证明'，也不许读成'缺证明'")
        return out
    text = str(row.get("proof_text") or "")
    if not text.strip():
        out["checked"] = True
        checks[0]["detail"] = "空"
        checks[1]["detail"] = "没有被审的对象，不适用"
        checks[2]["detail"] = "没有被审的对象，不适用"
        out["why"] = (f"命题 {sid or '（没有编号）'} 的 evidence_kind="
                      f"{PROOF_REVIEW_KIND!r}，而 `proof_text` 是空的 ⇒ "
                      "没有被审的那份证明，「逐行审阅过」这句话就没有对象。"
                      "要么把证明过程写进 proof_text，要么把这一档降成 heuristic")
        return out
    checks[0].update(ok=True, detail=f"{len(text)} 字")
    if not S.is_valid_id(sid):
        checks[1]["detail"] = "命题号不是编号形态，查不到台账"
        checks[2]["detail"] = "同上"
        out["why"] = (f"命题号 {sid!r} 不是编号形态（{S.ID_DIGITS} 位，旧四位仍可读）⇒ "
                      f"`verifications/` 里查不到它，凭据无从核起")
        return out
    path = verification_ledger_path(root, sid)
    out["ledger"] = f"{VERIFICATIONS_DIR}/{sid}.jsonl"
    if not path.is_file():
        pending = _pending_signed(root, text)
        if pending is not None:
            return _gap_from_pending(out, checks, pending, statement_id=sid)
        out["checked"] = True
        checks[1]["detail"] = f"`{out['ledger']}` 不在盘上（一次审校都没有）"
        checks[2]["detail"] = "没有那一行，无从比"
        out["why"] = (f"命题 {sid} 声称 evidence_kind={PROOF_REVIEW_KIND!r}，而 "
                      f"`{out['ledger']}` 不在盘上 ⇒ **一次审校都没有**。"
                      "这一档要求 V 的 `verifications` 里那一条签「成立」（且审的是现在"
                      "这一版）—— 没有它，这一行就只是「自称被审过」。"
                      f"两条出口：① 派 V 去 `verify_proof(stmt:{sid})`；"
                      "② 把 evidence_kind 降成 heuristic")
        return out
    rows, problems = JF.read_jsonl(path)
    out["rows"] = len(rows)
    out["problems"] = list(problems)
    if problems:
        checks[1]["detail"] = f"台账有读不出来的行：{problems[:3]}（没查成）"
        checks[2]["detail"] = "同上"
        out["why"] = (f"`{out['ledger']}` 有读不出来的行（{problems[:3]}）⇒ "
                      "凭据**没查成**（不是「查过、没问题」）")
        return out
    if not rows:
        pending = _pending_signed(root, text)
        if pending is not None:
            return _gap_from_pending(out, checks, pending, statement_id=sid)
        out["checked"] = True
        checks[1]["detail"] = "台账是空文件"
        checks[2]["detail"] = "同上"
        out["why"] = (f"`{out['ledger']}` 是空文件 ⇒ 一次审校都没落过"
                      "（「有这个文件」不等于「审过」）")
        return out

    # ---- 判定分两个口（2026-10-22 审计第 1 条 + 多证明模型收口）
    #
    # 命题级（`ok`）：`evidence_kind` 是命题级的声明，而每一条证明各自有第 3 位 ⇒
    # "任一份证明 signed 即放行"（`statement_review_reading` 的 `reviewed`）。
    # 逐条级（`state` / `proof_no` / `verification_id` / `sha_matches` / `why`）：
    # 说的是"当前这一份"（`proof_no`，缺省按这一行自己记的号，再缺省 canonical）。
    #
    # 为什么不能只留一个口：只留命题级，拒信就说不清是哪一份缺凭据（读的人只能猜）；
    # 只留逐条级（改前就是 `review_standing(..., proof_no=1)`），"#p1 未签、#p2 已签"
    # 的存量行会被写入期闸整笔拒收，而拒收之后撤回把台账那一行也抹掉 —— 同一批审计
    # 的第 1 条正是这个形态：`checked=True verdict='成立' signed_bit3=True` 而台账 0 字节。
    reading = statement_review_reading(root, row)
    no = proof_no_of(row) if proof_no is None else as_proof_no(proof_no)
    if no < 1:
        no = DEFAULT_PROOF_NO
    entries = [p for p in (reading.get("proofs") or []) if isinstance(p, Mapping)]
    by_no = {as_proof_no(p.get("proof_no")): p for p in entries}
    current = by_no.get(no) or by_no.get(DEFAULT_PROOF_NO) or {}
    signed_entry = next((p for p in entries if p.get("ok")), {})
    stale_entry = next((p for p in entries if str(p.get("state") or "") == "stale"), {})
    checked = bool(reading.get("checked"))
    if checked and signed_entry:
        chosen, state = signed_entry, "signed"
    elif checked and stale_entry:
        chosen, state = stale_entry, "stale"
    else:
        chosen, state = current, str(current.get("state") or "unsigned")
    chosen_no = as_proof_no(chosen.get("proof_no")) or no
    # 台账那一签的细节（verdict / round / unresolved_errors）只有 `review_standing` 的
    # 返回里有，逐条读数只带定位用的几格 ⇒ 对"被选中的那一份"再读一次（纯读，不写）。
    span = (review_standing(root, statement_id=sid,
                            proof_text=proof_text_of(row, chosen_no), proof_no=chosen_no)
            if checked else {})
    out.update({
        "checked": checked,
        "state": state,
        "proof_no": chosen_no,
        "sha_matches": chosen.get("in_sync"),
        "verification_id": str(chosen.get("verification_id") or ""),
        "verdict": str(span.get("verdict") or ""),
        "round": span.get("round"),
        # 给拒收消息用（"这一签是 verdict=X、unresolved_errors=N"）：读数，
        # 不参与判据 —— 判据只看 `signs_bit3`（一处口径）。
        "unresolved_errors": int(span.get("unresolved_errors") or 0),
    })
    if state == "signed" and checked:
        checks[1].update(ok=True, detail=f"{out['verification_id']}：{out['verdict'] or '成立'}")
        checks[2].update(ok=True, detail=(
            f"{proof_label(sid, chosen_no)} 的现行正文 sha "
            f"{str(chosen.get('proof_sha256') or '')[:12]}… 与台账那一行相符"))
        out["ok"] = True
        out["why"] = (
            f"命题 {sid} 的 evidence_kind={PROOF_REVIEW_KIND!r} 有凭据（每份证明各自有第 3 位，"
            f"任一份 signed 即算）：{str(chosen.get('why') or '')}")
        return out
    if state == "rejected":
        checks[1]["detail"] = (f"现行这一版被签过：{out['verification_id']} "
                               f"verdict={out['verdict']!r}、"
                               f"unresolved_errors={out['unresolved_errors']}")
        checks[2]["detail"] = "签的就是现行这一版，但结论不是「成立」"
        out["why"] = (
            f"命题 {sid} 的 evidence_kind={PROOF_REVIEW_KIND!r}，而 `{out['ledger']}` 里"
            f"{proof_label(sid, chosen_no)} 现在这一份上那一签是 {out['verification_id']}："
            f"verdict={out['verdict']!r}、unresolved_errors={out['unresolved_errors']}"
            f"（why：{str(chosen.get('why') or '')[:120]}）⇒ 复核过、结论不是「成立」。"
            "这一档要的正是「成立」那一签；改好证明再派 V 走一遍，或者如实降档")
        return out
    if state == "stale":
        checks[1]["detail"] = (f"{proof_label(sid, chosen_no)} 签过，但没有一签盖住现在这一份"
                               f"（最近一签 {out['verification_id']}）")
        checks[2]["detail"] = "签的是另一版，无从比"
        out["why"] = str(chosen.get("why") or "")
        return out
    if state == "unsigned":
        # 台账读得出、只是这一份（以及别的证明）一次都没签 ⇒ 查过了，结论是"没凭据"。
        # 改前这一支掉进最后那段，被报成 checked=False「台账读不出来（没查成）」——
        # 把"查过了、没签过"与"没查成"折成同一个读数（审计第 4 条）。
        checks[1]["detail"] = (f"`{out['ledger']}` 里没有 {proof_label(sid, chosen_no)} 这一份"
                               "证明的签（一次都没签）")
        checks[2]["detail"] = "没有那一行，无从比"
        out["checked"] = checked
        out["why"] = str(chosen.get("why") or
                         f"`{out['ledger']}` 里没有这一份证明的签 ⇒ 一次都没签")
        return out
    checks[1]["detail"] = "台账读不出来（没查成）"
    checks[2]["detail"] = "同上"
    out["checked"] = False
    out["why"] = str(chosen.get("why") or "台账没查成（不是「没签过」）")
    return out


#: 比 `proof_review` 更弱的证据档（降档告警用；顺序 = 由弱到强里的两档）。
WEAKER_THAN_PROOF_REVIEW: tuple[str, ...] = ("heuristic", "cross_check")


def weaker_than_evidence_gaps(root: str | Path,
                              rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """一组 `statements` 行里够格 `proof_review` 却登记成更弱档的那些 —— 纯读。

    ## 这条读数在说什么（2026-10-19，接 `proof_review_gap` 的反方向）
    `proof_review_gap` 管"自称审过、其实没签"（虚报）；这里是它的镜像：凭据齐全、档位却写低了
    （`heuristic` / `cross_check`）。真机形态（`projects/mp2` 的 `stmt:000003`）：`proof_text`
    1909 字、`verifications/000003.jsonl` 里 `v-000001` 签「成立」、`proof_sha256` 与现行正文
    相符 ⇒ 按 `schema.EVIDENCE_KINDS` 的定义这条就是 `proof_review`，而盘上落的是 `heuristic`。
    它不是虚报，所以不是 error：降档是安全方向，可以是有意的选择；但它必须是看得见的选择，不是
    默认值 —— 长期把强结果写成弱档，论文的强度声明会系统性偏低，而没有任何读数会指出这一点。
    判据只三条（与 `proof_review_gap` 同一处口径）：
    1. `evidence_kind` 在 :data:`WEAKER_THAN_PROOF_REVIEW` 里；
    2. `proof_text` 非空（没有证明就谈不上"这份证明被审过"）；
    3. `proof_review_gap(...)` 判 `ok=True`（把那一行按 `proof_review` 重判一遍：V 最近一签是
       「成立」且 `proof_sha256` 等于现行正文）。
    概念行（`kind="concept"`）跳过：概念不参与等级链（`evidencebits.derive_grade` 的 `not_applicable`）。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        ek = str(row.get("evidence_kind") or "")
        if ek not in WEAKER_THAN_PROOF_REVIEW:
            continue
        if str(row.get("kind") or "") == "concept":
            continue
        if not str(row.get("proof_text") or "").strip():
            continue
        probe = dict(row)
        probe["evidence_kind"] = PROOF_REVIEW_KIND
        gap = proof_review_gap(root, probe)
        if not gap.get("ok"):
            continue
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        out.append({
            "statement_id": sid,
            "evidence_kind": ek,
            "verification_id": gap.get("verification_id") or "",
            "ledger": gap.get("ledger") or "",
            "why": (f"命题 {sid} 登记成 evidence_kind={ek!r}，而它的凭据已经够 "
                    f"`proof_review`：`proof_text` 非空、`{gap.get('ledger') or ''}` 里 "
                    f"{gap.get('verification_id')} 签「成立」、`proof_sha256` 与现行正文相符"
                    "（判据与 `proof_review` 写入期那道闸同一处）。"
                    "降档是安全方向，所以这是 warning、不是 error；但它必须是有意的："
                    "要么把这一行升成 `proof_review`（判据已够格，写入不会被拒），"
                    "要么在报告里写清为什么故意留弱档。"),
        })
    return out


def proof_review_gaps(root: str | Path, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """一组 `statements` 行里凭据不够的那些 `proof_review`（空列表 = 都够）。

    只挑 `evidence_kind == "proof_review"` 的行去核（其它档不归这条判据管：
    `proof` 由 `evidencebits.bit_evidence_gaps` 核，`cross_check`/`heuristic` 只需声明）。

    ## 哪些算"凭据不够"（业主 2026-10-22 口径改了半边）
    这一份的调用者是写入期闸（`store._refuse_fake_proof_review`）与审计期档
    （`verify._check_13`），所以"不够"的判据就是"该不该拒收/点名"：
    - `unsigned`（一次「成立」都没有）/ `unreadable`（台账读不出来）⇒ 不够，照旧；
    - `rejected`（现行这一版被签过、结论不是「成立」）⇒ 不够，照旧；
    - `stale`（签过、但签的是旧版）⇒ 不再算"没有凭据"。哈希是读数不是授权凭证：
      "正文改过了"是正常动作，任何写入路径都不许因为它被拒收。这一档现在是待复核
      这个读数（收工门 R10 的 `stale_ids`），不是"没签过"。
    - 任一证明 `signed` ⇒ 够（`proof_review_gap` 的命题级判据）：多证明模型里每份证明
      各自有第 3 位，"#p1 未签、#p2 已成立"这一形态不许整笔拒收 —— 它是本批审计
      第 1 条的存量形态（真机 mp1 的 10 条 `proof_review`）。逐条的不合格仍由
      `proof_review_gap` 的 `state` / `why` 读出来，只是不升级成"整笔不写"。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("evidence_kind") or "") != PROOF_REVIEW_KIND:
            continue
        gap = proof_review_gap(root, row)
        if gap["ok"] or gap.get("state") == "stale":
            continue
        out.append(gap)
    return out


def unverified_statement_refs(root: str | Path,
                              plans: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """攻坚计划的 `history` 里点名了哪些 `statement_id`、而 `verifications` 里没有对应行。

    ## 为什么这一条落在「攻」那一格（2026-10-19，接 V 的回路的收工侧）
    F 把论证落成 `statements` 一行后，`statement_id` 进 `attack_plans.history`（`agent_f/step.py`
    的 P3-6 落点），M 在 `attack.status` 里看得见；但看得见不等于有人审 —— 那一栏可以一直是
    "F 交了、没人签"而收工门照样绿（「攻」只问计划推进了没有）。这一条把两件事接上：history 里
    有 `statement_id` ⇒ `verifications` 里必须有它的一行（`verify_proof` 的产物）；没有 ⇒
    `closing._check_acceptance` 记 `unknown`（不是 `pass`）——"没签"与"签了"必须分得开。
    三态：`checked=False` ⇒ 没查成（读不到 `verifications/` 目录或坏行），不是"一条都没缺"；
    `missing` 逐条给 `plan_id` / `round` / `statement_id` / `why`。`signed` 是"那一行签住了第 3 位"
    （`signs_bit3`），不决定红绿（由 `missing` 定），留着是因为"有行但没签"与"有行且签了"是两种不同状态（`有毛病` 也是一条"有对应行"）。
    """
    refs: list[dict[str, Any]] = []
    problems: list[str] = []
    for plan in plans:
        if not isinstance(plan, Mapping):
            continue
        for entry in (plan.get("history") or []):
            if not isinstance(entry, Mapping):
                continue
            sid = str(entry.get("statement_id") or "").strip()
            if not sid:
                continue
            ref: dict[str, Any] = {
                "plan_id": str(plan.get("plan_id") or ""),
                "round": entry.get("round"),
                "statement_id": sid, "rows": None, "signed": None, "why": "",
            }
            try:
                path = verification_ledger_path(root, sid)
            except VerificationError as exc:
                ref["why"] = f"命题号 {sid!r} 不是编号形态（{exc}）⇒ 查不到它那一份台账"
                refs.append(ref)
                continue
            if not path.is_file():
                ref["rows"] = 0
                ref["signed"] = False
                ref["why"] = (f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 不在盘上 ⇒ "
                              "这一条命题**一次审校都没落过**")
                refs.append(ref)
                continue
            rows, bad = JF.read_jsonl(path)
            if bad:
                problems.extend(f"{VERIFICATIONS_DIR}/{sid}.jsonl: {b}" for b in bad)
                ref["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 有读不出来的行：{bad[:3]}"
                refs.append(ref)
                continue
            ref["rows"] = len(rows)
            ref["signed"] = any(signs_bit3(r) for r in rows)
            if not rows:
                ref["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 是空文件 ⇒ 一次审校都没落过"
            refs.append(ref)
    missing = [r for r in refs if not r.get("rows")]
    return {
        "checked": not problems,
        "problems": problems,
        "refs": refs,
        "missing": missing,
        "total": len(refs),
        "note": ("plan 的 `history` 里有 `statement_id` ⇒ `verifications/<命题号>.jsonl` 里"
                 "必须有它的一行（派 V 的 `verify.verify_proof` 就会落）。`missing` 非空 ⇒ "
                 "「攻（攻坚推进）」那一格记 `unknown`（不是 `pass`）；`signed` 只是读数："
                 "「有行但没签」由审计期那一档（`proof_review_without_verification`）点名"),
    }


# ============================================================ 断言与所引证据：方向 / 同一份证据复用
#
# 这一节是 `specs/g.py` policy[7]（「引用一个与断言相反的证据行，比没有引用更坏」）
# 与 policy[9]（「同一份证据不能当第二份用」）两条义务的机械判据本体。
#
# 为什么落在 `verifications`（而不是在 `verify._check_7` 里直接写一份）：
# 同一条口径在写入期（`doc_tools.check_proofs`，2026-10-13 起就有一条"引否证当支撑"）
# 与审计期（`verify._check_7`）各读一次 —— 两处各写一份判据必然漂移，而漂移的形态是
# "写入期拦下的，审计期照样说没问题"（FC-03 禁止的形态）。落法与
# `weaker_than_evidence_gaps` 同源：判据本体只此一份，两个出口都调它。

#: `experiments.result` 里"方向"只有两档有值；`inconclusive` 没有方向。
#: 真身是 `schema.EXPERIMENT_RESULTS`，这里只把"相反"那一个取值点名。
REFUTES = "refutes"
#: `negation_kind` 里"已证否"那一档（受控词表真身是 `schema.NEGATION_KINDS`）。
DISPROVED = "disproved"


def opposite_direction_evidence(claim: Mapping[str, Any],
                                experiment: Mapping[str, Any]) -> dict[str, Any] | None:
    """这条断言引用这条实验时，方向是不是反的 —— 判据本体（纯读，`None` = 不反）。

    ## 判的是什么（可机械化的那一半）
    一条实验行自己的结论是 `result="refutes"`（连同 `negation_kind="disproved"`，这是
    `schema.Experiment.validate` 强制的），意思是"它检验的那条命题被证否了"。一条正文断言
    把它列进 `citations` 当支撑时，台账上必须能读出"这条断言正是在说「我们证否了它」"——
    机械读法就是 `is_negative=True` 且 `negation_kind="disproved"`（`doc_tools.check_proofs`
    2026-10-13 的口径，真机现场：`projects/p6t2-research-20261012b` 的 claim-2 把 `exp:0002`
    （`result="refutes"`）列进 `citations` 当支撑，一路写库）。判据只需要两个字段：证据行的
    `result` / `negation_kind`，断言的 `is_negative` / `negation_kind` —— 都在 schema 里。
    ## 哪一半判不了（如实登记，不硬造）
    反方向的那一支 —— 断言登记成"已证否"、却引一条 `result="supports"` 的实验 —— 不归本判据管：
    `supports` 是相对于实验行自己的 `claim` 说的，而一条否定型断言（例如「不存在这样的图」）完全
    可能由一条 `supports` 的实验支持；更常见的是 `supports` 只是 `cross_check`（数值支持）。要判
    它，必须让实验行声明"它检验的命题相对于这条正文断言的正负极性"（例如 `tests_claim_id` +
    `direction` 两格），那是 schema 改动，不是审计侧能单方面补的。同理，`result="refutes"` 引一条
    正面断言也只有在"实验检验的就是这条断言所说的命题"时才是真相反 —— 本判据把"引用关系"当成
    那个链接（与写入期、收工门同一口径）。
    ## 返回值：不反 ⇒ `None`；反 ⇒ 一个 dict（`experiment_id` / `result` / 断言侧字段 / `why`），写入期与审计期各自决定怎么呈现（`problem` / `Issue`），判定本身不重复。
    """
    if str(experiment.get("result") or "") != REFUTES:
        return None
    if bool(claim.get("is_negative")) and str(claim.get("negation_kind") or "") == DISPROVED:
        return None
    eid = str(experiment.get("experiment_id") or "")
    return {
        "experiment_id": eid,
        "result": REFUTES,
        "claim_is_negative": bool(claim.get("is_negative")),
        "claim_negation_kind": str(claim.get("negation_kind") or ""),
        "why": (
            f"它引了 {('exp:' + eid) if eid else '这条实验'} 当支撑，而那条实验自己的结论是 "
            f"`result={REFUTES!r}`（否证）⇒ 一条否证被当成支撑用了。"
            "要么把这条断言改成否定型并写 `is_negative=True` + "
            f"`negation_kind={DISPROVED!r}`（「我们证否了它」），"
            "要么换一条真正支持它的证据；只在正文里解释「那只是脚本内部判据的问题」不算数 —— "
            "台账上它仍然是 refutes。"
        ),
    }


def _freeze(value: Any) -> Any:
    """把 `observations.data` 变成可比较的规范形（dict 的键序不参与同一性）。"""
    if isinstance(value, Mapping):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def evidence_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """一条实验行的"证据身份"：同一份读数只该算一份证据。

    ## 为什么身份不能只是 `experiment_id`
    真机读数（`draft/39` §6.27 的 D39，T2 第 9 趟 `p6k`）：一个脚本被派了 9 次，claim 分别是
    W(2)/W(3)/W(4)…，每次都打印逐字相同的 `data`（30 顶点 / 度 3）—— 始终是同一个图。台账上于是
    有 9 条 `result="supports"`，手稿把它们当 9 份独立证据引：同一份读数被当成了九份。这 9 条的
    `experiment_id` 各不相同，所以"按 `experiment_id` 判重"看不见它。
    ## 身份的定义（与 E 写入期那条 note 同一处）：有 `observations.data`（非空）⇒ 同脚本
    （`code_hash`）+ 同 `data` 即同一份证据（`code_hash` 为空也照比：历史行没有哈希时，"同 data" 仍是唯一可比的读数）；没有 `data` ⇒ 退回
    `experiment_id`（同一行被引两次是同一份证据；两行都没有 data 时不合并 —— 那会靠猜）。
    此前它只在 `agent_e.run_experiment._reused_evidence_note` 里，现在两边都读这一个函数（FC-03：同一件事不许有两份定义）。
    """
    obs = row.get("observations")
    data = dict(obs.get("data") or {}) if isinstance(obs, Mapping) else {}
    if data:
        return ("data", str(row.get("code_hash") or ""), _freeze(data))
    return ("row", str(row.get("experiment_id") or ""))


def one_evidence_used_twice(documents: Iterable[Mapping[str, Any]],
                            experiments: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """同一份证据被同一份稿件里的两条不同断言当独立证据用 —— 纯读。

    ## 判据（一条）：把每份稿件的 `claims[].citations` 里的 `exp:` 引用按 :func:
    `evidence_identity` 归组；同一组里出现 ≥ 2 个不同的 `claim_id` ⇒ 报一条。
    为什么 warning 不是 error（与 `opposite_direction_evidence` 的 error 不同）：同一份证据被两条
    断言引用可以是正当的（定理与推论、综述复述同一条读数、两条表述压在同一次计算上）。台账分不出
    "两条独立支撑"与"一份支撑被数了两遍"，所以它必须是看得见的读数，不是硬拦（会红掉合规稿件），
    而完全不说又正是 D39 的形态。处置写进 `why`：是复现就在正文与实验行 `notes` 里说清。
    ## 范围只在一份稿件内：跨稿件复用同一份证据是正常的（综述与论文引同一条实验）；判据只在
    同一份 `documents` 行内部比较 —— 返回值 `[{doc_id, claim_ids, experiment_ids, why}]`；
    空列表 = 不报（正常形态）。
    """
    exp_by_id: dict[str, Mapping[str, Any]] = {}
    for row in experiments:
        if not isinstance(row, Mapping):
            continue
        eid = str(row.get("experiment_id") or "")
        if eid:
            exp_by_id[eid] = row
    out: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, Mapping):
            continue
        doc_id = str(doc.get("doc_id") or "")
        groups: dict[tuple[Any, ...], dict[str, list[str]]] = {}
        for claim in doc.get("claims") or []:
            if not isinstance(claim, Mapping):
                continue
            cid = str(claim.get("claim_id") or "")
            if not cid:
                continue
            for cite in claim.get("citations") or []:
                kind, ref = T.citation_ref_parts(cite)
                if kind != "exp":
                    continue
                row = exp_by_id.get(ref)
                if row is None:
                    continue          # 悬空引用由 `dangling_citation` 报，不在这里重复
                group = groups.setdefault(evidence_identity(row),
                                          {"claim_ids": [], "experiment_ids": []})
                if cid not in group["claim_ids"]:
                    group["claim_ids"].append(cid)
                if ref not in group["experiment_ids"]:
                    group["experiment_ids"].append(ref)
        for group in groups.values():
            claim_ids = sorted(group["claim_ids"])
            if len(claim_ids) < 2:
                continue
            experiment_ids = sorted(group["experiment_ids"])
            evidence = " / ".join(f"exp:{eid}" for eid in experiment_ids)
            if len(experiment_ids) == 1:
                same = f"同一条实验行（{evidence}）"
            else:
                same = (f"{evidence} 是同脚本 + 同 `data` 的两次运行"
                        "（`observations.data` 逐字相同）")
            out.append({
                "doc_id": doc_id,
                "claim_ids": claim_ids,
                "experiment_ids": experiment_ids,
                "why": (
                    f"稿件 {doc_id} 的断言 {'、'.join(claim_ids)} 都把 {evidence} 当独立证据用，"
                    f"而它是同一份证据（{same}）⇒ 一条证据被算成了两份。"
                    "若这是复现（同一个对象被核了两次），请在正文与实验行的 `notes` 里"
                    "说清「这不是第二份独立证据」；否则换一条真正独立的证据。"
                ),
            })
    return out


def selftest() -> int:
    """最小自检：冷启动提示词只有对象、三态可判、签位条件、追加式编号。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="verifications_selftest_"))
    checks: list[tuple[str, bool]] = []
    prompt = cold_start_prompt("设 G 是群，则 c(G) ≤ 1。", "1. 由定义直接得到。",
                               readonly_facts="- stmt:0007 现状：猜想（第 2 位空）")
    checks.append(("提示词带命题与证明", "c(G) ≤ 1" in prompt and "由定义直接得到" in prompt))
    checks.append(("提示词带硬禁令", "易证" in prompt and "无依据的步骤" in prompt))
    # I12（冷启动）在这一层的判据是接口：拼提示词的函数只收字符串，
    # 没有任何 store / conductor / registry / session_root 参数 —— 于是"不给句柄"
    # 是结构性质，而不是"约定只读"（提示词里出现"没有 store 句柄"这几个字是说明，
    # 不是句柄本身；按子串判会把说明误判成句柄）。
    import inspect as _inspect

    params = set(_inspect.signature(cold_start_prompt).parameters)
    checks.append(("接口上没有句柄参数",
                   not (params & {"store", "conductor", "registry", "session_root"})))
    bad = parse_verdict('{"verdict": "有毛病", "defect_step": 2, "findings": '
                        '[{"level": "error", "step": 2, "kind": "无依据", "detail": "第 2 步"}]}')
    checks.append(("三态解析", bad["verdict"] == "有毛病" and bad["defect_step"] == 2))
    row = record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=bad)
    # 编号宽度不许写死（2026-10-14 业主裁定：4 位 → 6 位）：发号点是
    # `next_verification_id` 的 `f"v-{S.format_id(...)}"`，所以断言也从
    # `schema` 取形态。旧写法写死 `"v-0001"`，宽度一改这条自检就红 ——
    # 那是断言过期（`v-0001` 这一格属于旧四位号），不是发号器坏了。
    checks.append((f"编号从 v-{S.format_id(1)} 起（六位；旧四位号读侧兼容）",
                   row["verification_id"] == f"v-{S.format_id(1)}"))
    checks.append(("有毛病不签第 3 位", bit3_payload(row) == {}))
    good = parse_verdict('{"verdict": "成立", "findings": []}')
    ok_row = record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=good)
    checks.append(("成立才签第 3 位", bit3_payload(ok_row).get("reviewed") is True))
    checks.append(("追加式（两行）", len(list_verifications(root, limit=None)[0]) == 2))
    checks.append(("limit=0 是零条、limit=None 才是全量",
                   list_verifications(root, limit=0)[0] == []
                   and len(list_verifications(root, limit=None)[0]) == 2))
    try:
        parse_verdict("我不确定")
        unparsable = False
    except VerificationError:
        unparsable = True
    checks.append(("没查成抛错（不冒充看不出来）", unparsable))
    for name, good_ in checks:
        print(f"  [{'PASS' if good_ else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())
