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
    metadata_only  仅题录（试过一次抽取也没拿到可读文本，只剩书目元数据）
    extract_failed 有字节但抽取失败（抽过、抽出来的不是可读文本 —— 含乱码与无文本层）
    unknown        未查（这一条还没审过可读性；"没查"不许折成"可读"）

    2026-11-16 业主裁定（AR1）把 `metadata_only` 从"零读可入"改为"必须有一次读取尝试的
    回执"：它不再是"我没查"，而是"我试过，拿不到可读字节"。判据在
    `litstage._read_evidence_gate`：没有 `extract_failed` 那条回执就按 `no_read_evidence`
    整批拒并逐槽点名 —— 档位本身保留（VC1 的 P0-1 靠这条收紧解决，而不是删档）。

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

抽读回执（`data/lit_reads.jsonl`）是另一份事实、另一个写点：只有真正做抽读的
`text.extract` 写 `kind="read"`（`record_read`）。它记的是"这一份正文被抽出来过"，
不是"谁说他读了"；`check_read` 再把它与 `fs.read` 的观察台账对起来，回答
"这一条到底读没读"。两份台账分成两个文件，是为了不让"它说可读"与"它抽过"混成一行。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import litread

__all__ = [
    "ADMITTABLE_TIERS",
    "AVAILABILITY_TIERS",
    "EXTRACT_FAILED",
    "LEDGER_NAME",
    "METADATA_ONLY",
    "MIN_BODY_BEYOND_ABSTRACT",
    "NOT_ADMITTABLE_REASONS",
    "READABLE",
    "READ_LEDGER_NAME",
    "TIER_LABELS",
    "UNKNOWN",
    "body_beyond_abstract",
    "candidate_digest",
    "check_read",
    "content_assertion",
    "content_read",
    "describe_tier",
    "is_admissible",
    "availability_ledger_path",
    "locator_of",
    "not_admittable_reason",
    "read_ledger_path",
    "read_receipts",
    "receipts_by_slot",
    "read_records",
    "record_availability",
    "record_read",
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

#: 允许进入 `literature` 的那一档（业主 2026-11-20 裁定，逐字：
#: 「读内容才能判东西，这样的话保证通过的肯定有内容，且能保证质量」）。
#:
#: 改前这里是 `(READABLE, METADATA_ONLY)`：仅题录（试过一次、拿不到可读文本）也能入库。
#: 那条口径让 lp-ball-13 的 12 条"只有题录、没有正文"的候选照样判收 —— 通过的东西里
#: 一半没有内容。现在 `metadata_only` 只是"没有正文"的诚实读数，不再是一张入库券：
#: 它只能留在候选列表里（写清为什么没读到），判收要走 `readable` + 抽读证据。
ADMITTABLE_TIERS: tuple[str, ...] = (READABLE,)

#: 没有正文时，拒信里用的受控理由码（与 `availability_bad[].code` 同一套）。
#:
#: 为什么分三档而不是一句"没有正文"：下一步不同 ——
#:   no_fulltext    连一次抽读都没有过（先下载 / 先 `text.extract`）；
#:   extract_failed 试过、抽不出可读文本（只能判拒或换来源）；
#:   metadata_only  试过、只剩题录（同上，它不是入库券）。
#: `metadata_only` 这一档的理由码由 `not_admittable_reason` 按"有没有抽取尝试"现算。
NOT_ADMITTABLE_REASONS: dict[str, str] = {
    METADATA_ONLY: "no_fulltext",
    EXTRACT_FAILED: "extract_failed",
    UNKNOWN: "no_fulltext",
}

#: 「读了正文」与「只读了摘要」之间那条线（字符数）。
#:
#: 摘要不算读了内容（业主 2026-11-20 裁定 ②）：把摘要当正文抽出来、`fs.read` 一遍，
#: 机器读数上会显得"读过"。所以抽出来的文本里，除了摘要之外至少还要有这么多字，
#: 才算读到了正文。500 的依据：真论文的正文比摘要长一个量级；而"摘要 + 一段
#: 参考文献/页眉"这类假正文通常只多出几十个字。
MIN_BODY_BEYOND_ABSTRACT: int = 500

#: 台账落在工作区的哪个相对路径（零 schema：它是文件，不是表）。
LEDGER_NAME = "lit_availability.jsonl"

#: 「抽读回执」台账的落点：一次真的抽读（`text.extract`）在这里留一行。
#:
#: 为什么它与可读性判定分成两个文件：可读性那一行是 A 的判断（`tier` 是它报的），
#: 抽读这一行是机器的事实（这一份文件被哪个角色、在什么时候、抽出了多少字、指纹是什么）。
#: 两份事实混在一个文件里，读的人就分不清"它说可读"与"它抽过"—— 而后者才是判据。
READ_LEDGER_NAME = "lit_reads.jsonl"

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
                        note: str = "", actor: str = "agent-A",
                        relevance: str = "", read: Mapping[str, Any] | None = None,
                        content_read: bool | None = None) -> dict:
    """写一条可读性判定（追加；`tier` 必须是四档之一）。

    这是"这一条审过"的唯一写点。写成别的取值当场抛 `ValueError`：自造档在写侧就炸，
    而不是在报告里变成一行读不懂的字（模型自拼的 `pdf_no_text` 就是这样进不来的）。

    `relevance` 与 `read` 是这一条判断的读数（业主裁定 3：逐条要落成
    "质量如何、相关度如何、入不入库、为什么"）：前者的真身是候选行的 `relevance`
    （回读时抄一份到这里，report / 闸不必再回表拼），后者是抽读回执的摘要
    （字数 / 指纹 / 抽读件路径 / 它读的是哪一版）。两格都只是读数，不参与"档位合不合法"。

    `content_read` 是 2026-11-20 业主裁定 ③ 新加的读数：这一条到底读没读到正文
    （`litavail.content_read` 现算 —— 抽读成功、非空、且不是只有摘要）。`None` 表示
    调用方没算（老调用点），此时按 `tier == readable` 记一个保守的 `False`：
    "没算过"不许冒充"读过"。
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
        "relevance": str(relevance or "").strip()[:400],
        "read": _read_digest(read),
        "content_read": bool(content_read) if content_read is not None else False,
        "at": _now(),
        "actor": str(actor or ""),
    }
    path = availability_ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return rec


def _read_digest(rec: Mapping[str, Any] | None) -> dict | None:
    """抽读回执里进"判断读数"的那几格（没有回执 ⇒ `None`，不是空字典）。"""
    if not rec:
        return None
    keys = ("tier", "chars", "sha256", "text", "text_abs", "text_version", "source", "at")
    return {k: rec.get(k) for k in keys}


# --------------------------------------------------------------------------- 抽读回执


def read_ledger_path(root: Path | str) -> Path:
    """这一次工作区的抽读回执台账路径。"""
    return Path(root) / _LEDGER_DIR / READ_LEDGER_NAME


def read_receipts(root: Path | str) -> list[dict]:
    """把抽读回执读成一列（坏行跳过：它不构成"这一条读过"的证据）。"""
    path = read_ledger_path(root)
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
        if isinstance(got, dict) and str(got.get("kind") or "") == "read":
            out.append(got)
    return out


def receipts_by_slot(root: Path | str) -> dict[str, dict]:
    """`slot -> 最后一次抽读回执`（后写的覆盖先写的；槽位号全局唯一）。"""
    out: dict[str, dict] = {}
    for rec in read_receipts(root):
        slot = str(rec.get("slot") or "").strip()
        if slot:
            out[slot] = rec
    return out


def candidate_digest(row: Mapping[str, Any] | None) -> dict | None:
    """抽读回执里"这一条候选是谁"的三格（读写两侧共用同一把尺子）。

    为什么要它：`slot` 只证明"这一次抽读记在哪个槽上"，不证明"抽的是这一条候选"。
    写侧从候选行抄这三格进回执，读侧（`check_read` 的 `expected`）拿候选行再核一遍，
    于是"拿另一条候选的回执来冒充"会在闸上被逐槽点名（`other_candidate`），
    而不是因为槽位号碰巧对上就放行。
    """
    if not row:
        return None
    return {
        "request_id": str(row.get("request_id") or ""),
        "title": str(row.get("title") or ""),
        "doi": str(row.get("doi") or ""),
    }


def record_read(root: Path | str, request_id: str, slot: str, tier: str, *,
                source: str = "", text: str = "", text_abs: str = "",
                text_version: str = "", chars: int = 0, sha256: str = "",
                quality: Mapping[str, Any] | None = None, note: str = "",
                candidate: Mapping[str, Any] | None = None,
                actor: str = "agent-A") -> dict:
    """写一条抽读回执（追加）。`tier` 只认 `ok` / `extract_failed` 两档。

    ## 为什么写点只在 `text.extract` 的 handler 里

    这一行回答的是"这一份正文真的被抽出来过吗"，不是"谁说他读了"。所以它必须由
    做抽读的那件工具写：模型可以自报 `availability=readable`，但它没法凭空造出
    一条带 `sha256` / `chars` / 抽读件版本的回执 —— 抽读没发生，就没有那份文件，
    也就没有版本可写。判据（`check_read`）随后核的是"回执在 + 回执绑的是这一条候选 +
    抽读件还是那一版 + `fs.read` 观察台账里有它"。

    `candidate` 是候选行的身份三格（`candidate_digest`）：候选期抽读
    （`lit_id="cand:<槽位>"`）必须带上，`readable` 那一档的闸要按它核"读的是不是这一条"。

    过期抽读件（同一槽位再抽一次）由后写的覆盖先写的：`receipts_by_slot` 取最后一条，
    于是"上次抽成功、这次抽失败"会如实变成 `extract_failed`，不会被旧成功掩盖。
    """
    tier_text = str(tier or "").strip()
    if tier_text not in (litread.FULLTEXT_OK, litread.FULLTEXT_EXTRACT_FAILED):
        raise ValueError(
            f"抽读回执的 tier 只能是 {litread.FULLTEXT_OK!r} / "
            f"{litread.FULLTEXT_EXTRACT_FAILED!r}，收到 {tier!r}"
        )
    rec = {
        "kind": "read",
        "request_id": str(request_id or "").strip(),
        "slot": str(slot or "").strip(),
        "tier": tier_text,
        "source": str(source or "").strip(),
        "text": str(text or "").strip(),
        "text_abs": str(text_abs or "").strip(),
        "text_version": str(text_version or "").strip(),
        "chars": int(chars or 0),
        "sha256": str(sha256 or "").strip(),
        "quality": dict(quality or {}),
        "note": str(note or "").strip()[:400],
        "candidate": candidate_digest(candidate),
        "at": _now(),
        "actor": str(actor or ""),
    }
    path = read_ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return rec


def _binding_problem(slot: str, receipt: Mapping[str, Any],
                     expected: Mapping[str, Any] | None) -> tuple[str, str]:
    """回执绑的是不是这一条候选的抽读件；返回 `("", "")` = 绑得上。

    两步（业主 2026-11-16 裁定 3 的 P1-4：`readable` 读的必须是这一份候选的抽读件）：

    1. 回执里记的候选身份三格（委托 / 题名 / DOI）必须与候选行逐格相同 ——
       没记（旧版回执 / 手工伪造）按"绑不上"处理，不是按"默认这一条"；
    2. 抽读件必须是候选期给这个槽写的那一份（`cand-<槽位>.txt`）——
       "另一条候选的 `.txt`"即使内容可读，也不是这一条读过的证据。
    """
    if expected is None:
        return ("", "")
    got = receipt.get("candidate")
    if not isinstance(got, Mapping):
        return ("unbound", "抽读回执没记候选身份（这一版回执不绑候选，不能证明读的是这一条）")
    for key, label in (("request_id", "委托"), ("title", "题名"), ("doi", "DOI")):
        if str(got.get(key) or "") != str(expected.get(key) or ""):
            return ("other_candidate",
                    f"抽读回执不是给这一条候选的（{label} 对不上：回执 "
                    f"{got.get(key)!r} / 候选 {expected.get(key)!r}）")
    name = Path(str(receipt.get("text") or receipt.get("text_abs") or "")).stem
    if name != f"cand-{slot}":
        return ("other_text",
                f"抽读件 {name!r} 不是这一条候选的抽读件（候选期该落 cand-{slot}.txt）")
    return ("", "")


def check_read(root: Path | str, slot: str,
               receipt: Mapping[str, Any] | None = None, *,
               expected: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """这一条到底读没读：返回 `(state, why)`；`state == "ok"` 才算读过。

    判据分四步，缺一不可（三态：没抽 / 抽了没读 / 读了）：

    1. 抽读回执在，且那一档是 `ok`（`extract_failed` 是"抽过但失败"，不是读过）；
    2. 回执绑的是这一条候选（`expected` 给了才核：身份三格 + `cand-<槽>.txt`）——
       同一份回执换个槽位号、或读的是另一条候选的抽读件，都不算；
    3. 抽读件还在盘上、且还是回执写下的那一版（版本令牌取 `fs_observation.version_of`，
       与 `fs.read` 登记的是同一把尺子）—— 抽完又被改写/删掉，读的就不是现在这一份；
    4. `fs.read` 的观察台账里有这一份同一版本的读（owner 是当前 `(角色, 委托)`）——
       抽读是机器做的，读是 A 做的；少了这一步，"抽了"会被当成"读了"。

    `receipt` 可以显式给（闸一次读出全部槽位的回执，避免每槽重读文件）；不给就现查。
    `expected` 是候选行的身份三格（`candidate_digest`）：`readable` 那一档必须给，
    `metadata_only` 那一档不核身份（它证明的是"试过一次、拿不到可读文本"，不是"读过"）。
    返回的 `why` 是拒信里逐条点名用的那句话（不是"没读"三个字）。
    """
    r = dict(receipt) if receipt is not None else receipts_by_slot(root).get(str(slot or ""))
    if not r:
        return ("no_extract", "没有抽读记录（这一条没抽过正文）")
    if str(r.get("tier") or "") == litread.FULLTEXT_EXTRACT_FAILED:
        return ("extract_failed",
                f"抽过但失败（{r.get('note') or '抽出来的不是可读文本'}）")
    if str(r.get("tier") or "") != litread.FULLTEXT_OK:
        return ("no_extract", f"抽读回执的档位不成立（{r.get('tier')!r}）")
    if int(r.get("chars") or 0) <= 0:
        return ("empty_text", "抽读回执说 0 字（没有抽到正文）")
    text_abs = str(r.get("text_abs") or "").strip()
    version = str(r.get("text_version") or "").strip()
    if not text_abs or not version:
        return ("no_text", "抽读回执里没有抽读件的路径/版本（这一条判不了）")
    bound, why = _binding_problem(str(slot or ""), r, expected)
    if bound:
        return (bound, why)
    from . import fs_observation as OBS

    if OBS.version_of_path(Path(text_abs)) != version:
        return ("text_changed", "抽读件在抽完之后被改过/删掉了（读的不是现在这一份）")
    obs = OBS.observed_gate().get(OBS.current_owner(), text_abs)
    if obs is None or obs.kind != OBS.OBS_PRESENT:
        return ("not_read", "抽过但没读（没有用 `fs.read` 读过那份 .txt）")
    if obs.version != version:
        return ("read_stale", "`fs.read` 读到的是另一版正文（抽读件后来变过）")
    return ("ok", "")


def _now() -> str:
    """时间戳（从 schema 取，不在本模块另写一份时钟口径）。"""
    from . import schema as S

    return S.now_iso()


def is_admissible(tier: str) -> bool:
    """这一档能不能进 `literature`（现在只有 `readable` 能；见 `ADMITTABLE_TIERS`）。"""
    return str(tier or "") in ADMITTABLE_TIERS


def not_admittable_reason(tier: str, *, attempted: bool = False) -> str:
    """这一档不许入库时，拒信里给出的受控理由码（三档，见 `NOT_ADMITTABLE_REASONS`）。

    `attempted=True` 表示抽读回执是一条 `extract_failed`（试过、拿不到可读文本）——
    此时 `metadata_only` 的理由码从 `no_fulltext` 变成 `metadata_only`：两者下一步
    不同（前者去下载/去抽，后者换来源或判拒）。
    """
    key = str(tier or "")
    if key == METADATA_ONLY:
        return "metadata_only" if attempted else "no_fulltext"
    return NOT_ADMITTABLE_REASONS.get(key, "no_fulltext")


#: `relevance` / `new_content` 里出现这些词或数字（年份除外）就算"内容性断言"。
#:
#: 业主 2026-11-20 裁定 ③：`content_read=false` 而 relevance 写了具体结果 / 定理名 /
#: 数值 ⇒ 必红。这里只收机器判得出来、且不容易误伤的那三类：
#:   ① 数学名词（定理 / 引理 / 命题 / 证明 / 不等式 / 估计 … 与它们的英文）；
#:   ② 小数（`0.5` / `1.25`）—— 裸整数不算：它可能是条目标号、年份、卷号；
#:   ③ 显式的公式记号（`≥` / `≤` / `=` / `<` / `>` 后面接数字或字母）。
_CONTENT_WORDS = re.compile(
    r"(定理|引理|命题|推论|证明|公式|不等式|估计|渐近|常数|界"
    r"|theorem|lemma|proposition|corollary|proof|inequality|estimate|asymptotic|bound)",
    re.IGNORECASE,
)
_FORMULA = re.compile(r"[≥≤=<>]\s*[A-Za-z0-9]")
_DECIMAL = re.compile(r"(?<![\w.])\d+\.\d+(?![\w.])")


def content_assertion(text: str) -> str:
    """这一句里有没有"具体结果/定理名/数值"那种内容性断言；返回命中的那一段（没有 ⇒ 空串）。

    刻意不判"相关性"这种模糊的话：`与本次检索相关（题名）` 不算内容性断言 —— 它是
    "这一条为什么进候选"的理由，摘要/题名就够写。只有写了正文里才拿得到的东西
    （定理名、不等式、具体小数）才算。裸整数与四位数年份刻意不算：前者常是条目标号，
    后者只说明"哪一年"。
    """
    raw = str(text or "")
    if not raw.strip():
        return ""
    hit = _CONTENT_WORDS.search(raw)
    if hit:
        return hit.group(0)
    hit = _FORMULA.search(raw)
    if hit:
        return hit.group(0)
    hit = _DECIMAL.search(raw)
    if hit:
        return hit.group(0)
    return ""


def _squash(text: str) -> str:
    """去掉空白之后的文本（摘要与正文的长度比较用同一把尺子）。"""
    return re.sub(r"\s+", "", str(text or ""))


def body_beyond_abstract(text: str, summary: str) -> int:
    """抽出来的文本里，除摘要之外还有多少字（业主裁定 ②：摘要不算读内容）。

    判定：摘要在正文里出现 ⇒ 正文减掉那一段的长度；正文里找不到摘要（摘要被裁剪过、
    或 provider 给的摘要与正文措辞不同）⇒ 整段正文都算"摘要之外"——这一档不虚高：
    真只抽到摘要时它通常就是摘要本身，`body_beyond_abstract` 接近 0。
    """
    body = _squash(text)
    abstract = _squash(summary)
    if not abstract:
        return len(body)
    cut = body.find(abstract)
    if cut < 0:
        return len(body)
    return len(body) - len(abstract)


def _receipt_body(root: Path | str, receipt: Mapping[str, Any] | None) -> str:
    """抽读回执指向的那份正文（读不到 ⇒ 空串：读不到正文不是"读过了"）。"""
    if not receipt:
        return ""
    for key in ("text_abs", "text"):
        raw = str(receipt.get(key) or "").strip()
        if not raw:
            continue
        target = Path(raw)
        if not target.is_absolute():
            target = Path(root) / target
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def content_read(root: Path | str, slot: str, row: Mapping[str, Any], *,
                 tier: str = "", receipt: Mapping[str, Any] | None = None
                 ) -> tuple[bool, str]:
    """这一条算不算「读了正文」：返回 `(content_read, why)`（`why` 为空 = 读了）。

    四步（缺一不可，与业主 2026-11-20 裁定 ①②③ 一一对应）：

    1. A 报的档位必须是 `readable`（仅题录 / 抽取失败 / 未查都不算 —— 没有正文）；
    2. 抽读证据过 `check_read`（抽读回执 + 候选身份 + 抽读件版本 + `fs.read` 观察台账）；
    3. 抽出来的文本非空（`check_read` 已核 `chars > 0`，这里再核文件真读得出来）；
    4. 除了摘要之外还有 `MIN_BODY_BEYOND_ABSTRACT` 字以上（摘要不算"读内容"）。

    `content_read=false` 是读数，不是"判不了"：它带着 `why`，拒信与报告都写它。
    """
    text_tier = str(tier or "").strip()
    if not text_tier:
        text_tier = tiers_by_slot(root).get(str(slot or ""), "")
    body = ""
    if receipt is None:
        receipt = receipts_by_slot(root).get(str(slot or ""))
    attempted = bool(receipt) and str(receipt.get("tier") or "") == litread.FULLTEXT_EXTRACT_FAILED
    if text_tier != READABLE:
        return False, not_admittable_reason(text_tier, attempted=attempted)
    state, why = check_read(root, str(slot or ""), receipt,
                            expected=candidate_digest(row))
    if state != "ok":
        return False, state if not why else f"{state}: {why}"
    body = _receipt_body(root, receipt)
    if not body.strip():
        return False, "empty_text: 抽读件读不出正文"
    beyond = body_beyond_abstract(body, str(row.get("summary") or ""))
    if beyond < MIN_BODY_BEYOND_ABSTRACT:
        return (False, f"abstract_only: 抽出来的正文只比摘要多 {beyond} 字"
                       f"（< {MIN_BODY_BEYOND_ABSTRACT}；摘要不算读内容）")
    return True, ""


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


def missing_tiers(rows: Sequence[Mapping[str, Any]], tiers: Mapping[str, str]
                  ) -> list[str]:
    """这些行里还没有可读性判定的槽位（按槽位号排序）。

    闸的"每个候选都要有判定"这一条读它；`admit_all` 与 `lit.admit` 共用同一处。
    """
    out = [str(r.get("slot") or "") for r in rows
           if str(r.get("slot") or "") and str(r.get("slot") or "") not in tiers]
    out.sort()
    return out
