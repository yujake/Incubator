# -*- coding: utf-8 -*-
"""D10 的受控引用词表的规格那一半：前缀 → 目标、寻址形、号形（纯数据，零读盘）。

## 这个文件里有什么

- 三态/受控码词表（`STATE_*` / `CODE_*`）与三类目标（`KIND_*`）—— 调用方按码分支，
  不按 `why` 的措辞分支；
- :class:`RefSpec` 与唯一词表 `REF_NAMESPACES` / `REF_SPECS`（含"这一种怎么寻址、
  存在性按什么判"的逐行说明）；
- 号形：手稿族名与文件名正则、legacy 路径尾巴正则，以及"一个号有几种写法"
  （`_id_forms` / `_anchor_forms` / `_manuscript_from_name`）那一族 helper。

## 为什么与解析分开

`tools/repo_survey.py` 的软判据量「>800 行的 src 文件数」 ⇒ 处置是拆模块、不抬基线
（业主口径）。切法是"数据 vs 读它"：本文件只有表与号形，不解析引用、不读盘、不
import 任何 `agentflow` 模块；解析与存在性留在 :mod:`agentflow.refvocab`（它按名字
回引这里的表与 helper，`refvocab.parse_ref` 等公开名照旧可用）。

这份规格仍然是"一张表"的唯一落点 —— 一致性由 `tests/test_ref_vocabulary_is_one_table.py`
逐条对 `schema.CITATION_PREFIXES` 与 `manuscripts.OBJECT_REFS` 钉住。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

# ---------------------------------------------------------------- 状态与受控码

#: 形状成立、目标在盘上。
STATE_OK = "ok"
#: 形状成立、走的是 legacy 写法、目标在盘上。legacy 不是问题。
STATE_LEGACY_OK = "legacy_ok"
#: 查过了，目标确实不在。
STATE_MISSING = "missing"
#: 没查成（没有根 / 表不在 / 读不出来）。不是 missing。
STATE_UNCHECKED = "unchecked"
#: 形状不成立（前缀不认识 / 号形不对）。
STATE_BAD = "bad"
#: 一个裸稿号命中多个族（不猜）。
STATE_AMBIGUOUS = "ambiguous"

#: 受控码：调用方按它分支，不按 `why` 的措辞分支。
CODE_OK = ""
CODE_UNKNOWN_NAMESPACE = "ref_unknown_namespace"
CODE_BAD_ADDRESS = "ref_bad_address"
CODE_TARGET_MISSING = "ref_target_missing"
CODE_UNCHECKED = "ref_unchecked"
CODE_AMBIGUOUS = "ref_ambiguous_manuscript"

#: 三类目标：store 表 / 追加式账本 jsonl / `reports/` 文件族。
KIND_TABLE = "table"
KIND_LEDGER = "ledger"
KIND_FILE = "file"


@dataclass(frozen=True)
class RefSpec:
    """词表的一行：前缀 → 目标、寻址形、存在性判据。

    为什么用冻结的 dataclass：表是唯一真身，冻结之后"运行时改一格"这种漂移在结构上
    不可能发生；`id_field` 让"查哪一列"是显式的，而不是每处自己记得。
    """

    namespace: str
    #: `table` / `ledger` / `file`。
    kind: str
    #: 目标的人读名字（表名 / 账本路径 / 文件族），给回执与报错用。
    target: str
    #: 表行的主键列（`ledger`/`file` 为空串）。
    id_field: str
    #: 人读的寻址形（写进报错，教调用方怎么写）。
    address: str
    #: 目标部分的形状（正则的语义在 `parse_ref` 里逐类实现，不靠一条大正则硬拼）。
    id_pattern: str


#: 唯一词表。键就是前缀（不含冒号）。
#:
#: - 台账行：目标在 `data/<table>.json`，id 是 4-6 位十进制（新号 6 位，旧号 4 位读侧兼容）；
#: - 账本行：`manu` 在 `manuscripts/handoffs.jsonl`，`verif` 在 `verifications/<命题号>.jsonl`
#:   （pending 在 `verifications/pending/<sha>.jsonl`），行号用 `#` 锚；
#: - 文件族：`mss` 在 `reports/<family>-<id>.md`，family 是四族之一（`f-proof` 的号可为
#:   `plan-<数字>`）。
#:
#: 存在性判据（按 `kind`，实现只在 `ref_reading` 一处）：
#: - table：`data/<target>.json` 的 `rows[*][id_field]` 与目标号相等（4/6 位互认）；
#: - ledger + manu：`manuscripts/handoffs.jsonl` 的 `id` 与目标号相等；
#: - ledger + verif：`verifications/<target>.jsonl`（或 pending 路径）里
#:   `verification_id` 与 `#` 锚相等；
#: - file + mss：`reports/` 下存在 `<family>-<id>.md`。
#: 任何一种读不到（文件不在 / JSON 坏 / 有坏行且目标没找到）都落到 `unchecked`，
#: 不折成 `missing`。
REF_NAMESPACES: tuple[RefSpec, ...] = (
    RefSpec("stmt", KIND_TABLE, "statements", "stmt_id", "stmt:<4-6 位>", r"\d{4,6}"),
    RefSpec("exp", KIND_TABLE, "experiments", "experiment_id", "exp:<4-6 位>", r"\d{4,6}"),
    RefSpec("lit", KIND_TABLE, "literature", "lit_id", "lit:<4-6 位>", r"\d{4,6}"),
    RefSpec("rel", KIND_TABLE, "relations", "relation_id", "rel:<4-6 位>", r"\d{4,6}"),
    RefSpec("q", KIND_TABLE, "research_questions", "question_id", "q:<4-6 位>", r"\d{4,6}"),
    RefSpec("c", KIND_TABLE, "conjectures", "conjecture_id", "c:<4-6 位>", r"\d{4,6}"),
    RefSpec("doc", KIND_TABLE, "documents", "doc_id", "doc:<4-6 位>", r"\d{4,6}"),
    RefSpec("eval", KIND_TABLE, "eval_results", "eval_id", "eval:<4-6 位>", r"\d{4,6}"),
    RefSpec("manu", KIND_LEDGER, "manuscripts/handoffs.jsonl", "id",
            "manu:<4-6 位>", r"\d{4,6}"),
    RefSpec("verif", KIND_LEDGER, "verifications/<命题号>.jsonl", "verification_id",
            "verif:<命题号>#<v-id>（pending: verif:pending/<64hex>#<u-id>）",
            r"\d{4,6}|pending/[0-9a-f]{64}"),
    RefSpec("mss", KIND_FILE, "reports/<family>-<id>.md", "",
            "mss:<family>-<id>（family=f-proof/b-proof/e-proof/e-num）",
            r"(?:f-proof|b-proof|e-proof|e-num)-(?:\d{4,6}|plan-\d+)"),
)

#: 前缀 → 那一行（词表的查表面；`parse_ref` 只从这里取）。
REF_SPECS: Mapping[str, RefSpec] = MappingProxyType(
    {one.namespace: one for one in REF_NAMESPACES})

#: 四族手稿（与 `manuscriptfamily.FAMILY_ORDER` 同序；这里不 import 那个模块）。
_MANUSCRIPT_FAMILIES: tuple[str, ...] = ("f-proof", "b-proof", "e-proof", "e-num")

#: 手稿文件名：`<family>-<id>.md`（读侧兼容旧盘上的 `-pN` 尾巴）；`f-proof` 的 id
#: 可以是 `plan-<数字>`。
_MANUSCRIPT_NAME_RE: MappingProxyType = MappingProxyType({
    family: re.compile(
        (r"^(?P<id>\d{4,6}|plan-\d+)(?:-p[1-9]\d*)?$" if family == "f-proof"
         else r"^(?P<id>\d{4,6})$" if family == "e-num"
         else r"^(?P<id>\d{4,6})(?:-p[1-9]\d*)?$")
    )
    for family in _MANUSCRIPT_FAMILIES
})

#: legacy 里"路径后还有一截"的分隔（`reports/x.md#V签` / `reports/x.md「## 命题 1」…`）。
_PATH_TAIL_RE = re.compile(r"^(reports|notes)/([^\s（「：，；、]+?\.md)(.*)$")


def _text(value: Any) -> str:
    """任意值 ⇒ 去掉首尾空白的字符串（`None` ⇒ 空串）。"""
    return "" if value is None else str(value).strip()


def _pad6(value: str) -> str:
    """十进制号补到 6 位（`0001` / `1` ⇒ `000001`）；不是纯数字就原样返回。

    为什么只补位不剥前导零：读侧要同时认 4 位旧号与 6 位新号；补 6 位后再用
    `_id_forms` 把两种写法都试一遍，比在每处写"if len == 4"更不容易漏。
    """
    text = _text(value)
    return text.zfill(6) if text.isdigit() else text


def _id_forms(value: Any) -> set[str]:
    """一个编号的等价写法（`0001` / `000001` / `1` 都认）。

    为什么不是单一写法：盘上同时存在 4 位旧号与 6 位新号（`schema.is_valid_id`
    两种都收），而历史 refs 里两种写法都有；只做字面比较会把宽度差判成"目标不存在"。
    """
    raw = _text(value)
    out = {raw}
    if raw.isdigit():
        # 4 位 / 6 位两种宽度都试（旧账本里是 4 位，新号是 6 位）。
        # 注意补位要在"去掉前导零的数字"上做：`000002` 的 4 位写法是 `0002`，
        # 不是 `000002`.zfill(4)（那还是 6 位）。
        digits = str(int(raw))
        out.add(digits)
        out.add(digits.zfill(4))
        out.add(digits.zfill(6))
    return out


def _anchor_forms(value: Any) -> set[str]:
    """账本行号的等价写法：`v-0003` / `v-000003` / `v-3` 都认（`u-` 同理）。

    为什么不复用 `_id_forms`：行号带前缀（`v-` / `u-`），直接 zfill 会得到
    `v-0003`（长度算上前缀）；必须把前缀拆掉、只补数字部分。
    """
    text = _text(value)
    match = re.fullmatch(r"([vu])-(\d{1,6})", text)
    if match is None:
        return {text}
    return {f"{match.group(1)}-{one}" for one in _id_forms(match.group(2))}


def _looks_like_family(name: str) -> bool:
    """这个文件名是不是"像手稿族、但号形可能不对"（用于区分"坏手稿名"与"不是手稿"）。"""
    stem = _text(name)
    if stem.endswith(".md"):
        stem = stem[:-3]
    return any(stem.startswith(f"{family}-") for family in _MANUSCRIPT_FAMILIES)


def _manuscript_from_name(name: str) -> tuple[str, str]:
    """文件名 ⇒ `(family, id)`；认不出返回 `("", "")`（不猜）。

    只认规范名（`<family>-<号>.md`，`f-proof` 另有 `plan-<数字>`）。
    `-v2` 一类历史后缀刻意不认：一个稿号 = 一份文件 = 一份证明，别名会让
    `b-proof-000003-v2.md` 冒充 `b-proof-000003.md`。
    """
    stem = _text(name)
    if not stem.endswith(".md"):
        return "", ""
    stem = stem[:-3]
    for family in _MANUSCRIPT_FAMILIES:
        prefix = f"{family}-"
        if not stem.startswith(prefix):
            continue
        match = _MANUSCRIPT_NAME_RE[family].fullmatch(stem[len(prefix):])
        if match is not None:
            return family, str(match.group("id"))
        return "", ""
    return "", ""
