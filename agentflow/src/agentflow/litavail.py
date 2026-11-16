# -*- coding: utf-8 -*-
"""「待录入文献列表」的可读性/质量判定与它的旁路台账（零 schema）。

## 为什么要有这一格（业主 2026-11-16 裁定 9 / 15 / 16）

业主原话：「加强 A 对待录入列表的审核」「是 A 侧原来就有的待录入文献列表的逐个自审
没做好」「A 侧需保证录入文献库的文献的质量」，并裁定加 `extract_failed` 一档：
「抽过但失败要有落点」。

现场读数（AH6 实测，`projects/lp-ball-2`，2026-11-16 07:32）：提交闸跑了，但它审的
证据只有 `relevance` —— 而那 12 条 relevance 是同一秒整批写死的；「能不能读到全文」
从来不是判据。于是 12 条入库里 10 条只有题录、2 条有字节但抽取两次都乱码，概念行 0 条。

所以这一格要回答的是 `relevance` 回答不了的第二个问题：这一条，A 到底拿到了什么？
四档（裁定 16 的 `extract_failed` 是新增的第四档，不是模型自拼的 `pdf_no_text`）：

    readable       可读全文（有字节、且抽得出可读文本）
    metadata_only  仅题录（只有书目元数据，没有本地字节）
    extract_failed 有字节但抽取失败（抽过、抽出来的不是可读文本 —— 含乱码与无文本层）
    unknown        未查（这一条还没审过可读性；"没查"不许折成"可读"）

## 为什么不加一列（零 schema，FC-27）

`lit_candidates` 的列在 `schema.py` —— 那是 FC-27 禁改区（加列＝改磁盘格式契约，要 2 名
reviewer 逐行走查）。而"这一条当时可不可读"是候选期的事实，不该变成 `literature` 的
持久契约的一部分。所以落点是本模块管的旁路台账：

    <工作区>/data/lit_availability.jsonl

一条一行（JSONL，追加写）：`{"slot","request_id","tier","note","at","actor","kind"}`。
槽位号是全局唯一的（`store.alloc_id("candidate")` 只增不复用），所以查表只需按 `slot`。

## 三态纪律在这里的形态

`unknown` 是有内容的读数（"这一条没审"），不是"没有这一格"。所以：
- 台账里没有记录 ⇒ 闸按 `unknown` 处理（`missing_availability`），不是按 `readable`；
- 台账读不出来（文件坏行）⇒ 该行记一条读数并跳过：不让"读坏了"变成"有一条记录"；
- `tier_of_literature` 的"有路径但盘上读不到字节"⇒ `unknown`（判不了，不是仅题录）。

## 谁能写

只有 A 的判定入口（`lit.admit` 的 `items[].availability` / `lit.stage_reject` 的
`availability`，落在 `tools/search_tools.py` 的 handler 里）写 `kind="availability"`。
机器侧另有一档 `tier_of_literature`（只读，给探针与报告用），它不从台账取数。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import litread

__all__ = [
    "ADMITTABLE_TIERS",
    "AVAILABILITY_TIERS",
    "EXTRACT_FAILED",
    "LEDGER_NAME",
    "METADATA_ONLY",
    "READABLE",
    "TIER_LABELS",
    "UNKNOWN",
    "describe_tier",
    "is_admissible",
    "availability_ledger_path",
    "locator_of",
    "read_records",
    "record_availability",
    "tier_of_literature",
    "tiers_by_slot",
]

#: 可读性判定的四档（受控词表；加一档必须同时加标签，且要过业主裁定）。
READABLE = "readable"
METADATA_ONLY = "metadata_only"
EXTRACT_FAILED = "extract_failed"
UNKNOWN = "unknown"
AVAILABILITY_TIERS: tuple[str, ...] = (READABLE, METADATA_ONLY, EXTRACT_FAILED, UNKNOWN)

#: 四档的中文标签（进报告的那一栏；与词表同文件、同顺序）。
TIER_LABELS: dict[str, str] = {
    READABLE: "可读全文",
    METADATA_ONLY: "仅题录",
    EXTRACT_FAILED: "有字节但抽取失败",
    UNKNOWN: "未查",
}

#: 允许进入 `literature` 的那两档（业主裁定 ③：`extract_failed` 与 `unknown` 不许入库）。
#:
#: `metadata_only` 在列的理由见 `docs/` 与本次交付的 ④ 判断：仅题录是诚实的第三态
#: （它指得出处、能被下游按 DOI 定位，只是没有正文），拦掉它会把"进了一条没有正文的记录"
#: 换成"这一篇连记录都没有" —— 后者更坏。前提是它必须指得出处（`locator_of` 非空）。
ADMITTABLE_TIERS: tuple[str, ...] = (READABLE, METADATA_ONLY)

#: 台账落在工作区的哪个相对路径（零 schema：它是文件，不是表）。
LEDGER_NAME = "lit_availability.jsonl"

#: 台账所在的目录（与 `data/` 下其它 JSON 台账同层）。
_LEDGER_DIR = "data"


def availability_ledger_path(root: Path | str) -> Path:
    """这一次工作区的旁路台账路径。"""
    return Path(root) / _LEDGER_DIR / LEDGER_NAME


def read_records(root: Path | str) -> list[dict]:
    """把台账读成一列记录（坏行跳过，不把"读坏了"折成"没有这一条"）。

    文件不存在 ⇒ 空清单（这是"还没审过任何一条"，与"读不到"不同：读不到会抛）。
    坏行（不是 JSON / 不是对象）跳过 —— 它们不构成"这一条审过"的证据；闸对没有记录的
    槽位一律按 `unknown` 处理，所以跳过的净效果是 fail-closed，不是 fail-open。
    """
    path = availability_ledger_path(root)
    if not path.is_file():
        return []
    out: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            got = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(got, dict):
            out.append(got)
    return out


def tiers_by_slot(root: Path | str) -> dict[str, str]:
    """`slot -> 最后一档` 的视图（后写的覆盖先写的；槽位号全局唯一）。

    只认四档词表里的取值：台账里手写进一个自造档（例如 `pdf_no_text`）不算"审过"，
    它按没有记录处理 —— 受理词表的只有这一处。
    """
    out: dict[str, str] = {}
    for rec in read_records(root):
        if str(rec.get("kind") or "availability") != "availability":
            continue
        slot = str(rec.get("slot") or "").strip()
        tier = str(rec.get("tier") or "").strip()
        if slot and tier in AVAILABILITY_TIERS:
            out[slot] = tier
    return out


def record_availability(root: Path | str, request_id: str, slot: str, tier: str, *,
                        note: str = "", actor: str = "agent-A") -> dict:
    """写一条可读性判定（追加；`tier` 必须是四档之一）。

    这是"这一条审过"的唯一写点。写成别的取值当场抛 `ValueError`：自造档在写侧就炸，
    而不是在报告里变成一行读不懂的字（模型自拼的 `pdf_no_text` 就是这样进不来的）。
    """
    tier_text = str(tier or "").strip()
    if tier_text not in AVAILABILITY_TIERS:
        raise ValueError(
            f"可读性判定必须是 {AVAILABILITY_TIERS} 之一，收到 {tier!r}。"
            "自己拼一档（例如 pdf_no_text）不算审过：报告与闸都只认这四档"
        )
    rec = {
        "kind": "availability",
        "request_id": str(request_id or "").strip(),
        "slot": str(slot or "").strip(),
        "tier": tier_text,
        "note": str(note or "").strip()[:400],
        "at": _now(),
        "actor": str(actor or ""),
    }
    path = availability_ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return rec


def _now() -> str:
    """时间戳（从 schema 取，不在本模块另写一份时钟口径）。"""
    from . import schema as S

    return S.now_iso()


def is_admissible(tier: str) -> bool:
    """这一档能不能进 `literature`（`extract_failed` / `unknown` 不能）。"""
    return str(tier or "") in ADMITTABLE_TIERS


def describe_tier(tier: str) -> str:
    """报告那一栏的写法：`仅题录（metadata_only）`；空值按 `未查（unknown）`。"""
    key = str(tier or "").strip()
    if key not in AVAILABILITY_TIERS:
        key = UNKNOWN
    return f"{TIER_LABELS[key]}（{key}）"


def locator_of(row: Mapping[str, Any]) -> str:
    """这一条指不指得出处：规范化 DOI 或 URL（仅题录可入库的前提）。

    为什么仅题录要这一条：它没有正文，唯一的价值就是"按这个号还能把它再取回来"。
    连号都没有的仅题录记录，既不能引用也不能重取 —— 那不是一条文献，是一条噪声。
    """
    doi = str(row.get("doi") or "").strip()
    if doi:
        return f"doi:{doi}"
    url = str(row.get("url") or "").strip()
    if url:
        return f"url:{url}"
    return ""


def tier_of_literature(row: Mapping[str, Any], root: Path | str) -> str:
    """机器侧这一条文献现在是什么档（只读；给探针/报告用，不是闸的证据）。

    判据（顺序即优先级）：
    1. 行上没有 `path` ⇒ `metadata_only`（只有书目元数据）；
    2. 有 `path` 但盘上读不到字节 ⇒ `unknown`（"路径写着"不等于"字节在"）；
    3. `download.fulltext == extract_failed` ⇒ `extract_failed`；
    4. `download.fulltext == no_text_layer` ⇒ `extract_failed`（有字节、抽不出文本，
       与"抽过但失败"对下游是同一件事：没有可读正文；要 OCR 才谈得上可读）；
    5. `download.fulltext == ok` ⇒ `readable`；
    6. 其余（有字节、还没抽过 ⇒ `None`）⇒ `unknown`（没查 ≠ 可读）。
    """
    rel = str(row.get("path") or "").strip()
    if not rel:
        return METADATA_ONLY
    resolved = litread.resolve_literature_path(
        Path(root), Path(root) / "library", rel)
    if not litread.bytes_on_disk(resolved.path):
        return UNKNOWN
    dl = row.get("download")
    fulltext = str((dict(dl) if isinstance(dl, Mapping) else {}).get("fulltext") or "")
    if fulltext == litread.FULLTEXT_EXTRACT_FAILED:
        return EXTRACT_FAILED
    if fulltext == litread.FULLTEXT_NO_TEXT_LAYER:
        return EXTRACT_FAILED
    if fulltext == litread.FULLTEXT_OK:
        return READABLE
    return UNKNOWN


def batch_tiers(records: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """把一列记录压成 `slot -> tier`（只认四档；`kind` 不是 availability 的记录不看）。"""
    out: dict[str, str] = {}
    for rec in records:
        if str(rec.get("kind") or "availability") != "availability":
            continue
        slot = str(rec.get("slot") or "").strip()
        tier = str(rec.get("tier") or "").strip()
        if slot and tier in AVAILABILITY_TIERS:
            out[slot] = tier
    return out


def missing_tiers(rows: Sequence[Mapping[str, Any]], tiers: Mapping[str, str]
                  ) -> list[str]:
    """这些行里还没有可读性判定的槽位（按槽位号排序）。

    闸的"每个候选都要有判定"这一条读它；`admit_all` 与 `lit.admit` 共用同一处。
    """
    out = [str(r.get("slot") or "") for r in rows
           if str(r.get("slot") or "") and str(r.get("slot") or "") not in tiers]
    out.sort()
    return out
