# -*- coding: utf-8 -*-
"""V 签的侧文件：一稿一签（`out/vsigns/<artifact_sha>.json`）+ 派生归档（`out/vsigns/issued.json`）。

## 这一层解决的是什么断链

业主 2026-11-01 的口径（逐字）：

```text
「有毛病」是给提供证明的一方看的，具体信息是叫它们优化证明，只有连续三次审核通过这才叫 V 签。
「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或命题收录时读到。B 侧自己写的证明想要 V
签时一样是拿到 V 签，B 再录入。」
```

改前「签」这个事实只活在两处：`statements.bits.reviewed`（行内一个布尔）与
`verifications/<命题号>.jsonl` 的尾部连续数（行序）。两处都「按命题号」索引 ——
所以「这一份稿拿到签了没有」这个问题，B 拿着手稿（`reports/f-proof-<号>.md`）问不出来，
带着稿去哪里也带不走。这一层就是那条断链的补口：把签落成「按被签正文的 sha 命名」的
一份侧文件，谁拿到正文谁就能问「它签过没有」。

## 三个对象与它们的从属关系（本模块的纲）

| 对象 | 落点 | 它是什么 | 谁能拿它下结论 |
|---|---|---|---|
| 台账行 | `verifications/<命题号>.jsonl` | 「正本」：这一签是怎么来的（逐转 verdict / 缺陷步 / 洗过的转达） | 门、`review_standing`、`closing` 的 R10 |
| 签 | `out/vsigns/<artifact_sha>.json` | 「证据」：这一份正文连续 `need` 次「成立」的那一刻留的档 | B 收录时认它；门核它 |
| 归档 | `out/vsigns/issued.json` | 「派生索引」：V 侧"我发过哪些签"的一眼清单 | 「谁都不许拿它下结论」 |

> 「归档是派生且自动的 ⇒ 它永远不该是任何判据的依据。」
> B 收录时只读 `<sha>.json`；门只读逐份签文件与台账；`issued.json` 只给人看。
> 这样即使归档坏了，也不会有一个"结论"跟着坏 —— 归档失败只会让 `index_drift` 报一条
> 漏记（可重建），不会让任何一条命题的判定改口。

## `artifact_sha` 是哪一把 sha（这一格必须钉死）

`:data:`ARTIFACT_SHA_RULE`：「`verifications.proof_sha(proof_text)`」 —— 与台账行的
`proof_sha256`、连续计数的清零键（`verifications._hold_run_lengths` 的
`one = str(row.get("proof_sha256") or "")`）「逐字同一个值」。

为什么不是"盘上那份 `.md` 的字节 sha"（`numericproof.object_sha256` 那种）：
三连今天就是按正文 sha 数的，换一把尺就是两套门槛；而手稿 `.md` 还带表头与 `## 依赖`
那一节，它的字节 sha 与 `proof_sha256` 「恒不相等」 ⇒ 拿它当键的签永远对不上门槛，
"签过"会退化成永远读不到。文件只是容器，被审的是那一段正文。

## `passes` 不是全文（别让后来人误会）

签里逐条留的是 `{verification_id, at, proof_sha256, why}`：`why` 是 V 那一转自己写的
结论理由（台账行上的逐字原文），「全文在台账」（`verifications/<命题号>.jsonl#<vid>`）。
要落 V 的回复原文得给台账行加一格 `reply_text`（另批）：那会把台账从"读数账"变成"全文账"，
与本模块无关，所以这里只在 `source_note` 里写明去哪读。

## 历史签无法留档，也不许回填（α 口径）

本模块上线之前，全仓已有 「66 行 `bits.reviewed=true` / 11 个工作区」，而 `out/vsigns/`
是 0 个。那些签没有 `at`、没有三转读数 —— 「补一份就是伪造 `at`」，正是
:func:`index_drift` 的「伪造痕迹」那一条要抓的形态。所以：

- 判据的作用域按「`out/vsigns/` 目录存在」划：不存在 ⇒ :func:`index_drift` 报
  `tri="not_applicable"`（「不红，也不假装通过」）；
- 本模块「没有任何回填入口」，也刻意不提供。老工作区从下一条签起才进这条判据。

## `archived_at` 为什么是派生值而不是墙钟（与提案的一处偏离）

提案写「`archived_at` 早于签文件时间 ⇒ 红」。这里把它定成「派生值 = 签文件里的 `at`」，
判据随之收紧成「「必须相等」」。理由是判据①自身的约束：`issued.json` 必须与
「从 `out/vsigns/*.json` 全量重建」「逐格相等、且重建两次字节相同」（照
`sessions.rebuild_run_index` 的纪律，`cli.py` 逐字要求"同一条命令跑两次字节相同"）——
墙钟时间戳永远重建不出来。改成派生值之后，手补一条、改一个字节、改一个 `archived_at`
都会被「重建不一致 / 伪造痕迹」抓住，比"早于"更严。

## 归档失败：不回滚，但绝不静默

一次发签 = 两个动作，顺序固定：「先写 `<sha>.json`（证据），再更新 `issued.json`（归档）」。

- `<sha>.json` 写失败 ⇒ 整笔失败（那时"签没落地"，与 `sign_statement` 原本的
  `written=False` 同一档，索引一个字都不动）；
- `issued.json` 写失败 ⇒ 「不回滚」：位已经翻在 `statements` 里（同一事务），而
  删掉刚写好的签文件是"抹掉发生过的事"（与 append-only 纪律相反）。失败落成三处可见：
  `write_sign` 返回里的 `archive_error`、`out/vsigns/.archive-errors.jsonl` 的一行、
  以及 :func:`index_drift` 的「漏记」——「可重建、可核对、不静默」。

## 这一层不写任何表

`out/vsigns/` 是产物，不是表（先例：`exhaustionreport.REPORT_DIR = "out/experiments"`、
`index/run-index.json`）。`store` 只扫 `data/`（`store.py` 的 `self.data = root / "data"`），
所以这里落文件不碰任何表；也刻意「不登记进 `ARTIFACTS.jsonl`」（那份台账把"登记过、
盘上被改过"读成 `changed ⇒ unknown`，而 `issued.json` 每次发签都要改 ⇒ 只会制造
收工门的常态化 `unknown`）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

#: 签与归档的落点（工作区相对）。与 `out/experiments`、`out/review` 同一条约定：
#: 产物住 `out/`，表住 `data/`。
SIGNS_DIR = "out/vsigns"
#: 派生归档的名字（与逐份签文件同目录：`out/vsigns/issued.json`）。
INDEX_NAME = "issued.json"
#: 归档失败的那一条 appended 记录（点开头 = 机器产物，不给人当签读）。
ERRORS_NAME = ".archive-errors.jsonl"

#: 签文件的 schema 名（与 `issued.json` 分开：两份东西两个版本号）。
SIGN_SCHEMA = "vsign/1"
INDEX_SCHEMA = "vsigns-issued/1"

#: 归档项里「谁写的」那一格的唯一合法取值。任何别的值 ⇒ 有人手改过（:func:`index_drift` 判红）。
ARCHIVED_BY = "agentflow.vsigns.archive"

#: 写签者那一格的两个取值：秘书落地那条路（`append_ledger=False`）与直调写入口
#: （`record_verification(flip=True)` 的兼容门 / 夹具）。两者都真实发生过，
#: 所以分开记 —— 把直调也写成 `secretary` 会让"这张签是谁发的"变成一句假话。
WRITTEN_BY_SECRETARY = "secretary"
WRITTEN_BY_DIRECT = "sign_statement(direct)"

#: `artifact_sha` 的口径（一句话版，给读的人与判据看）。
ARTIFACT_SHA_RULE = (
    "`artifact_sha` = `verifications.proof_sha(proof_text)`，与台账行的 `proof_sha256`、"
    "连续计数的清零键同一个值；不是盘上那份 `.md` 的字节 sha")

#: 为什么 `passes` 里没有全文（判据与后来人都要读到这一句）。
PASSES_SOURCE_NOTE = (
    "passes 是逐转的读数（verification_id / at / proof_sha256 / why，"
    "另带 review_call 与 review_pass：同一 review_call 才是同一次送审的那几转，跨趟不拼票）；"
    "V 的回复全文不在本文件里 —— 去 verifications/<命题号>.jsonl#<verification_id> 读")

#: 归档项的键集合（顺序无关：落盘时 `sort_keys=True`）。多一格少一格都会让
#: 「重建 == 盘上」这条判据失去意义，所以它是常量而不是各写一遍。
ENTRY_KEYS: tuple[str, ...] = (
    "artifact_sha", "artifact_path", "verdict", "at", "streak", "need",
    "statement_id", "archived_by", "archived_at",
)

_HEX = frozenset("0123456789abcdef")


class VsignError(ValueError):
    """这一格的材料不成立（坏 sha / 坏 JSON / 不可重写的旧签）。"""


# ---------------------------------------------------------------- 路径（只算，不建）

def signs_dir(root: Any) -> Path:
    """签的目录（工作区根下的 `out/vsigns/`；只算路径，不建目录）。"""
    return Path(str(root)) / SIGNS_DIR


def index_path(root: Any) -> Path:
    """派生归档的落点（`out/vsigns/issued.json`）。"""
    return signs_dir(root) / INDEX_NAME


def errors_path(root: Any) -> Path:
    """归档失败的 appended 记录（`out/vsigns/.archive-errors.jsonl`）。"""
    return signs_dir(root) / ERRORS_NAME


def _sha_key(value: Any) -> str:
    """把 `artifact_sha` 归一成 64 位小写十六进制；认不出就抛（不静默换个名字落盘）。

    判据照抄 `verifications.pending_ledger_path`（那一层已经为"按内容 sha 分文件"
    立过同一条守卫）：文件名一旦能随便起，"按 sha 命名"就退化成"随便一个名字"。
    """
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in _HEX for ch in text):
        raise VsignError(
            "签的文件名必须是 64 位十六进制的 sha256（`artifact_sha` = 被签正文的 sha），"
            f"收到 {value!r}")
    return text


def sign_path(root: Any, artifact_sha: Any) -> Path:
    """一份签：`out/vsigns/<artifact_sha>.json`（一稿一签）。"""
    return signs_dir(root) / f"{_sha_key(artifact_sha)}.json"


def rel(path: Path, root: Any) -> str:
    """路径 ⇒ 工作区相对、正斜杠分隔（读数里一律用这一种写法）。"""
    try:
        return str(Path(path).relative_to(Path(str(root)))).replace("\\", "/")
    except (ValueError, OSError):
        return str(path).replace("\\", "/")


# ---------------------------------------------------------------- 落盘（原子，唯一实现）

def _dump(doc: Mapping[str, Any]) -> str:
    """一份 JSON 的字节形态（`sort_keys` + `indent=2` + 尾部换行 ⇒ 重建可逐字节比较）。"""
    return json.dumps(dict(doc), ensure_ascii=False, sort_keys=True, indent=2,
                      default=str) + "\n"


def _write_atomic(path: Path, doc: Mapping[str, Any]) -> None:
    """先写临时文件再 `os.replace`（读的人不该看见半份 JSON）。

    与 `sessions.rebuild_run_index` 同一做法、同一理由（那一层是"派生索引 + 原子写"的
    既有先例，本模块不另发明一套）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_dump(doc))
    os.replace(tmp, path)


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    """读一份 JSON 对象 ⇒ `(doc, 问题)`；读不成 / 不是对象 ⇒ `(None, 原因)`。"""
    if not path.is_file():
        return None, f"`{path.name}` 不在盘上"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"`{path.name}` 读不出来（{type(exc).__name__}: {exc}）"
    if not isinstance(doc, dict):
        return None, f"`{path.name}` 不是一个 JSON 对象（读到 {type(doc).__name__}）"
    return doc, ""


# ---------------------------------------------------------------- 读一份签

def sign_of(root: Any, artifact_sha: Any) -> dict[str, Any]:
    """这一份正文签过没有（纯读；B 收录时认签的唯一读口）。

    返回键：`checked`（查成了没有，三态的第一条）/ `found` / `path`（工作区相对）/
    `sign`（那一份签的全文，没有就是 `{}`）/ `artifact_sha` / `problems` / `why`。

    `checked=False` 只出现在"sha 认不出"那一档（材料坏了，不是"没签过"）；
    文件不在盘上是 `checked=True, found=False` —— 两者在读数里必须分得开
    （三态纪律：没查成绝不折成"没有"）。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "path": "", "sign": {},
                           "artifact_sha": "", "problems": [], "why": ""}
    try:
        key = _sha_key(artifact_sha)
    except VsignError as exc:
        out["why"] = f"{exc} ⇒ 这一格没查成（不是「没签过」）"
        return out
    out.update(checked=True, artifact_sha=key, path=f"{SIGNS_DIR}/{key}.json")
    doc, problem = _read_json(sign_path(root, key))
    if doc is None:
        out["why"] = (f"`{out['path']}` 不在盘上 ⇒ 这一份正文没有签"
                      if "不在盘上" in problem else problem)
        return out
    out.update(found=True, sign=doc)
    got = str(doc.get("artifact_sha") or "").strip().lower()
    if got != key:
        # 文件名叫 A、里面写 B ⇒ 这份签说不清自己签的是谁（读到就要点名，不静默采信）。
        out["problems"].append(
            f"签文件的名字是 {key[:12]}…，里面的 artifact_sha 是 "
            f"{got[:12] or '（空）'}… ⇒ 这份签对不上自己的文件名")
    if str(doc.get("verdict") or "") != "成立":
        out["problems"].append(
            f"签文件里的 verdict 是 {str(doc.get('verdict') or '（空）')!r}（签只能是「成立」）")
    out["why"] = ("签在盘上" if not out["problems"] else "；".join(out["problems"]))
    return out


# ---------------------------------------------------------------- 归档（派生 + 可重建）

def _entry_of(sign: Mapping[str, Any]) -> dict[str, Any]:
    """一份签 ⇒ 归档里那一项（「纯派生」：只读签文件，不吃任何外部状态）。

    `archived_at` 取签文件的 `at`（见模块 docstring 那一节：墙钟时间戳重建不出来，
    而判据①要求重建逐字节相同）。
    """
    at = str(sign.get("at") or "")
    return {
        "artifact_sha": str(sign.get("artifact_sha") or "").strip().lower(),
        "artifact_path": str(sign.get("artifact_path") or ""),
        "verdict": str(sign.get("verdict") or ""),
        "at": at,
        "streak": int(sign.get("streak") or 0),
        "need": int(sign.get("need") or 0),
        "statement_id": str(sign.get("statement_id") or ""),
        "archived_by": ARCHIVED_BY,
        "archived_at": at,
    }


def _sorted_entries(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """归档项的固定顺序：`at` 升序，同 `at` 再按 `artifact_sha` 升序。

    顺序必须写死并进判据：`sort_keys=True` 只管对象里的键，管不了数组的顺序 ——
    没有这条规则，"重建两次字节相同"就只是碰巧。
    """
    rows = [dict(e) for e in entries]
    rows.sort(key=lambda e: (str(e.get("at") or ""), str(e.get("artifact_sha") or "")))
    return rows


def compute_index(root: Any) -> dict[str, Any]:
    """从 `out/vsigns/*.json` 现算一份归档（「不写盘」）。

    返回 `{schema, updated_at, signs, problems, count}`：`updated_at` 也取派生值
    （最后一签的 `at`，没有签就是空串）——墙钟会让重建不可比。
    """
    out: dict[str, Any] = {"schema": INDEX_SCHEMA, "updated_at": "", "signs": [],
                           "problems": [], "count": 0}
    d = signs_dir(root)
    files = sorted(p for p in d.glob("*.json")) if d.is_dir() else []
    entries: list[dict[str, Any]] = []
    for path in files:
        if path.name == INDEX_NAME:
            # 归档自己不是签：`*.json` 的 glob 会把它扫进来，必须按名字排掉
            # （否则重建会把归档当成一份签，然后自己引用自己）。
            continue
        doc, problem = _read_json(path)
        if doc is None:
            out["problems"].append(f"{path.name}：{problem}")
            continue
        got = _sha_key(doc.get("artifact_sha") or "") if doc.get("artifact_sha") else ""
        if not got or f"{got}.json" != path.name:
            out["problems"].append(
                f"{path.name}：里面的 artifact_sha 对不上文件名（"
                f"{str(doc.get('artifact_sha') or '（空）')[:12]}…）⇒ 这一份不进归档")
            continue
        entries.append(_entry_of(doc))
    out["signs"] = _sorted_entries(entries)
    out["count"] = len(out["signs"])
    out["updated_at"] = str(out["signs"][-1]["at"]) if out["signs"] else ""
    return out


def index_body(doc: Mapping[str, Any]) -> dict[str, Any]:
    """归档的"正文"部分（`schema` / `updated_at` / `signs`）—— 落盘与对账只认这三格。

    为什么要单独一格：`compute_index` 还带 `problems` / `count`（那是读数，不是归档的
    一部分）；不把两者分开，「盘上 == 重建」这条判据会因为读数键而永远不等。
    """
    return {"schema": str(doc.get("schema") or INDEX_SCHEMA),
            "updated_at": str(doc.get("updated_at") or ""),
            "signs": [dict(e) for e in (doc.get("signs") or []) if isinstance(e, Mapping)]}


def rebuild_index(root: Any) -> dict[str, Any]:
    """现算并原子落一份归档（幂等：同一批签文件重建两次字节相同；永不抛）。"""
    doc = compute_index(root)
    body = index_body(doc)
    try:
        _write_atomic(index_path(root), body)
    except OSError as exc:
        return {"rebuilt": False, "path": rel(index_path(root), root),
                "index": body, "error": f"{type(exc).__name__}: {exc}",
                "problems": list(doc.get("problems") or [])}
    return {"rebuilt": True, "path": rel(index_path(root), root), "index": body,
            "error": "", "problems": list(doc.get("problems") or [])}


def load_index(root: Any) -> tuple[dict[str, Any] | None, str]:
    """读盘上那份归档 ⇒ `(doc, 问题)`。"""
    return _read_json(index_path(root))


def _note_archive_error(root: Any, *, artifact_sha: str, error: str) -> str:
    """归档失败的那一行（append-only；失败也不许静默）。返回写没写成的那一句。"""
    path = errors_path(root)
    rec = {"at": _now_iso(), "artifact_sha": str(artifact_sha or ""), "error": str(error or "")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True,
                                default=str) + "\n")
    except OSError as exc:
        return f"归档失败、连 `.archive-errors.jsonl` 都没写成（{type(exc).__name__}: {exc}）"
    return "归档失败，已记进 out/vsigns/.archive-errors.jsonl"


def archive(root: Any, sign: Mapping[str, Any]) -> dict[str, Any]:
    """把一份签并进归档（原子整份替换；返回三态读数）。

    返回 `{ok, count, path, error, problems}`：`ok=False` 时 `error` 非空，调用方必须
    把它带进返回值（`write_sign` 的 `archive_error`）——这条路径「不回滚签」，
    理由见模块 docstring。
    """
    out: dict[str, Any] = {"ok": False, "count": 0, "path": rel(index_path(root), root),
                           "error": "", "problems": []}
    doc, problem = load_index(root)
    if doc is None and index_path(root).is_file():
        # 归档在盘上却读不出来：不拿一份坏文件当底（那会把"读不成"折成"空归档"，
        # 于是下一次写入把别人的条目全抹掉）。这里按"重建"处理并保留问题读数。
        out["problems"].append(f"{problem} ⇒ 按签文件重建后再写")
        doc = None
    entries = [dict(e) for e in ((doc or {}).get("signs") or []) if isinstance(e, Mapping)]
    fresh = _entry_of(sign)
    entries = [e for e in entries
               if str(e.get("artifact_sha") or "") != fresh["artifact_sha"]]
    entries.append(fresh)
    body = {"schema": INDEX_SCHEMA,
            "updated_at": str(_sorted_entries(entries)[-1].get("at") or "")
            if entries else "",
            "signs": _sorted_entries(entries)}
    try:
        _write_atomic(index_path(root), body)
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["problems"].append(_note_archive_error(
            root, artifact_sha=fresh["artifact_sha"], error=out["error"]))
        return out
    out.update(ok=True, count=len(body["signs"]))
    return out


def manuscript_proof_body(text: str) -> str:
    """手稿里「被签的那一段正文」（`## 证明` 那一节，去掉小节自带的首尾空行）。

    为什么需要这一格：`depsection.proof_body` 取的是 markdown 小节正文，首尾各带一个
    `\\n`；而 F 交给 B 登记的 `proof_text` 是逐行 join 出来的那一串（没有首尾空行）。
    签的 sha 按"登记时那一份正文"算（`ARTIFACT_SHA_RULE`）⇒ 两边必须先归一到同一串，
    否则签块里的 sha 与 B 登记时算的 sha 永远差一个换行，签永远认不上 ——
    而这条链上的每一处都"看起来成功了"。
    """
    from . import depsection as _DS

    return str(_DS.proof_body(text) or "").strip("\n")


# ---------------------------------------------------------------- 手稿里的签块
#
# 业主 2026-11-01（逐字，本模块开头已经引过一次）：「V 签不直接进台账，进手稿，随 B 侧
# 将手稿中的定理或命题收录时读到。」当时这一层把签落成了侧文件（`out/vsigns/<sha>.json`），
# 理由写在模块开头（"B 拿着手稿问不出来"）。2026-11-02 业主再明确一次：签要先放在 F 的
# 手稿里，B 收录时从手稿里读到 ⇒ 这一节就是那条落点。
#
# 为什么照 `depsection.WASH_MARK` 的样子做（一行元信息 + 写/读一对）：手稿已经有一行
# 机器可读的元信息（`- 依赖面洗稿：`），B 已经在读它（`manuscript_wash_reading`）。
# 再发明一种块格式只会让"手稿里哪些行是机器写的"变成第二个约定。
#
# 位置与幂等：插在 `- 计划：` 那一行之后（与洗稿那一行同一个位置），写之前先删掉旧的
# 同一行 —— 同一份手稿重签只留一行。
#:
#: 手稿里签块的固定前缀（写与读共用这一处；B 侧也按它读）。
SIGN_MARK = "- V 签："

#: 签块里那几格的键（顺序即写法；读侧按 `；` 与 `=` 拆）。
SIGN_BLOCK_KEYS: tuple[str, ...] = ("已签", "判词", "连续", "正文sha", "时间",
                                    "签名者", "台账", "命题号")

#: 签文件里 `manuscript_write` 那一格的三态（写侧；2026-11-02）。
#:
#: 为什么要有这一格：`write_sign` 把签块盖进手稿这一步发生在签文件落盘「之后」，
#: 而它的结果此前只活在返回值里 —— 签文件里没有这一格。真机 84 的两份签文件
#: （`a6fa76d2` / `dcb988fa`）因此读出来是 `null`，而 `reports/f-proof-000000.md`
#: 里明明有 `- V 签：` 块（台账指向 `verifications/000000.jsonl#v-000010`，正是
#: `write_sign` 顺手盖的那一版）。读数与实际脱节，将来排查会照 `null` 去找。
#:
#: 三态不许折成 `null`：写成功要能看出"落在哪一份稿、第几行、块里是什么"，
#: 失败要能看出"为什么"，没尝试（这一签没有手稿落点）要明说"未尝试"。
MANUSCRIPT_WRITE_STATES: tuple[str, ...] = ("written", "failed", "not_attempted")

#: 读侧多出的第四档：旧版签文件「没有记」这一格（不是"没写"，是"没记录"）。
#: 84 那两份就落在这一档 —— 它们不是"未尝试"，而是"当时没把结果落进文件"。
MANUSCRIPT_WRITE_UNRECORDED = "unrecorded"


def render_manuscript_sign(*, proof_sha: Any, streak: Any, need: Any,
                           verdict: str = "成立", signer: str = "V", at: str = "",
                           ledger: str = "", statement_id: str = "",
                           signed: bool = True) -> str:
    """渲染那一行签块（纯字符串；判据在 :func:`stamp_manuscript_sign`）。

    `signed=False` 写的是"审过了、没过"那一档：同一行、同一个落点，`已签=false` +
    真实判词。为什么不过了就什么都不写：业主 2026-11-01「「有毛病」是给提供证明的一方
    看的，具体信息是叫它们优化证明」⇒ 没过也要在稿上留下"哪一步、什么判词"，
    否则 F 手里只剩一句口头转达。
    """
    sha = str(proof_sha or "").strip().lower()
    return (f"{SIGN_MARK}已签={'true' if signed else 'false'}；"
            f"判词={str(verdict or '成立')}；"
            f"连续={int(streak or 0)}/{int(need or 0)}；正文sha={sha}；"
            f"时间={str(at or '')}；签名者={str(signer or 'V')}；"
            f"台账={str(ledger or '')}；命题号={str(statement_id or '未在册')}")


def stamp_manuscript_sign(text: str, *, proof_sha: Any, streak: Any, need: Any,
                          verdict: str = "成立", signer: str = "V", at: str = "",
                          ledger: str = "", statement_id: str = "",
                          signed: bool = True) -> str:
    """把手稿正文里那一行签块写成这一签（纯函数、幂等）。

    先删掉旧的同一行再插到 `- 计划：` 之后：手稿是替换式写的（`publish_manuscript`
    改名 / `mark_washed` 插行都会整文件重写），同一份稿上只该有一行签块。
    找不到 `- 计划：` 时插在第 3 行之前（与 `mark_washed` 的兜底位置同一处）。
    """
    raw = str(text or "").replace("\r\n", "\n")
    lines = [ln for ln in raw.split("\n") if not ln.strip().startswith(SIGN_MARK)]
    mark = render_manuscript_sign(
        proof_sha=proof_sha, streak=streak, need=need, verdict=verdict,
        signer=signer, at=at, ledger=ledger, statement_id=statement_id,
        signed=signed)
    at_i = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("- 计划："):
            at_i = i + 1
            break
    else:
        at_i = min(2, len(lines))
    lines.insert(at_i, mark)
    return "\n".join(lines)


def manuscript_sign_reading(text: str) -> dict[str, Any]:
    """读手稿里那一行签块（纯读；没有就是 `found=False`，不是"没签"）。

    返回键：`found` / `signed` / `verdict` / `streak` / `need` / `proof_sha256` /
    `at` / `signer` / `ledger` / `statement_id` / `mark` / `problem`。
    三态纪律：块在但读不成形（坏行 / 缺 `正文sha`）⇒ `found=True, signed=False`，
    并在 `problem` 里说缺什么 —— 不许折成"没有签"。
    """
    out: dict[str, Any] = {"found": False, "signed": False, "verdict": "", "streak": 0,
                           "need": 0, "proof_sha256": "", "at": "", "signer": "",
                           "ledger": "", "statement_id": "", "mark": "", "problem": ""}
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line.startswith(SIGN_MARK):
            continue
        out["mark"] = line
        body = line[len(SIGN_MARK):]
        cells: dict[str, str] = {}
        for cell in body.split("；"):
            if "=" in cell:
                k, v = cell.split("=", 1)
                cells[k.strip()] = v.strip()
        out["found"] = True
        out["signed"] = str(cells.get("已签") or "").lower() == "true"
        out["verdict"] = str(cells.get("判词") or "")
        out["at"] = str(cells.get("时间") or "")
        out["signer"] = str(cells.get("签名者") or "")
        out["ledger"] = str(cells.get("台账") or "")
        out["statement_id"] = str(cells.get("命题号") or "")
        if out["statement_id"] in ("未在册", ""):
            out["statement_id"] = ""
        out["proof_sha256"] = str(cells.get("正文sha") or "").strip().lower()
        run = str(cells.get("连续") or "")
        if "/" in run:
            left, right = run.split("/", 1)
            try:
                out["streak"] = int(left)
                out["need"] = int(right)
            except (TypeError, ValueError):
                out["problem"] = f"签块里的「连续」读不出数字：{run!r}"
        else:
            out["problem"] = f"签块里没有「连续」，读到 {run!r}"
        if len(out["proof_sha256"]) != 64:
            out["problem"] = (f"签块里的「正文sha」不是 64 位十六进制："
                              f"{out['proof_sha256']!r}")
        return out
    return out


def _sign_block_line(text: str) -> int:
    """签块在正文里的行号（1 起；没有 ⇒ 0）。写侧用它报"落在哪一行"。"""
    for no, raw in enumerate(str(text or "").replace("\r\n", "\n").split("\n"), 1):
        if raw.strip().startswith(SIGN_MARK):
            return no
    return 0


def manuscript_write_reading(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """读一份签文件里的 `manuscript_write` 那一格（四档，永不回 `None`）。

    为什么读侧要单独有一个函数：这一格是 2026-11-02 才进签文件的，盘上已经有
    旧版签文件（84 的两份 `a6fa76d2` / `dcb988fa` 就是）。旧文件没有这一格时，
    诚实的读法是 :data:`MANUSCRIPT_WRITE_UNRECORDED`（"当时没有记录"），
    「不是」 `None`（读的人会以为"没写"），也不是 `not_attempted`（那是另一种事实）。

    返回键：`state` / `written` / `idempotent` / `missing` / `path` / `line` /
    `why` / `reading`。`state` 只取三态词表 + `unrecorded`；读到不认识的词
    同样落 `unrecorded` 并说清读到的是什么（不静默把它读成成功）。
    """
    out: dict[str, Any] = {"state": MANUSCRIPT_WRITE_UNRECORDED,
                           "written": False, "idempotent": False, "missing": False,
                           "path": "", "line": 0, "why": "", "reading": {}}
    if not isinstance(doc, Mapping):
        out["why"] = "签文件没读成 ⇒ 这一格没查成（不是「没写」）"
        return out
    got = doc.get("manuscript_write")
    if not isinstance(got, Mapping):
        out["why"] = ("这份签文件没有 `manuscript_write` 那一格（旧版只把结果留在"
                      "返回值里）⇒ 这一格没记录，不是「没写」")
        return out
    for key in ("written", "idempotent", "missing", "path", "line", "why", "reading"):
        if key in got:
            out[key] = got[key]
    state = str(got.get("state") or "")
    if state not in (*MANUSCRIPT_WRITE_STATES, MANUSCRIPT_WRITE_UNRECORDED):
        out["state"] = MANUSCRIPT_WRITE_UNRECORDED
        out["why"] = (f"签文件里的 `manuscript_write.state` 是 {state!r}，"
                      "不在三态词表里 ⇒ 这一格没记录")
        return out
    out["state"] = state
    return out


def manuscript_sign_standing(text: str, *, proof_sha: Any = "") -> dict[str, Any]:
    """签块相对"现在这一份正文"的读数（`signed` / `stale` / `rejected` / `unsigned`）。

    判据（与 `bits_after_sign` 同一把尺，不另立）：
    - 没有块 ⇒ `unsigned`（"这一份还没签"，不是"查不成"）；
    - 块在、`已签=true`、`连续>=require`、且块里的 `正文sha` == 这一份正文的 sha
      ⇒ `signed`；sha 不符 ⇒ `stale`（签完之后正文改过）；
    - 块在但 `已签=false`（判词不是成立）⇒ `rejected`。
    """
    got = manuscript_sign_reading(text)
    out = {**got, "state": "unsigned", "checked": True,
           "sha_matches": None, "why": ""}
    if not got.get("found"):
        out["why"] = "手稿里没有 V 签块（这一份还没签）"
        return out
    if got.get("problem"):
        out.update(checked=False, state="unsigned",
                   why=f"签块读不成形（{got['problem']}）⇒ 这一格没查成，不是「没签」")
        return out
    want = str(proof_sha or "").strip().lower()
    out["sha_matches"] = (not want) or (got.get("proof_sha256") == want)
    if not got.get("signed"):
        out.update(state="rejected",
                   why=(f"手稿里的签块是「{got.get('verdict') or '（空）'}」"
                        "⇒ 审过了、没过，按缺陷改稿后再送"))
        return out
    if not out["sha_matches"]:
        out.update(state="stale",
                   why=(f"手稿里的签盖的是另一版（{got.get('proof_sha256')[:12]}… ≠ "
                        f"{want[:12]}…）⇒ 签完之后正文改过，要重签"))
        return out
    if int(got.get("streak") or 0) < int(got.get("need") or 0):
        out.update(state="unsigned",
                   why=(f"签块里的连续读数是 {got.get('streak')}/{got.get('need')}"
                        " ⇒ 未达门槛，不算签"))
        return out
    out.update(state="signed",
               why=(f"手稿里的签块：连续 {got.get('streak')}/{got.get('need')} 成立、"
                    f"正文 sha 相符（签于 {got.get('at') or '（没有时间）'}）"))
    return out


def write_manuscript_sign(root: Any, manuscript_path: Any, *,
                          proof_sha: Any, streak: Any, need: Any,
                          verdict: str = "成立", signer: str = "V", at: str = "",
                          ledger: str = "", statement_id: str = "",
                          signed: bool = True) -> dict[str, Any]:
    """把签块盖进那一份手稿（唯一写手稿签块的入口；三态读数）。

    为什么加这一格：`write_sign` 只写侧文件；未在册那一档（`verify_proof` 的
    `proof_manuscript` 入口）连侧文件都没有，签只落在手稿里 ⇒ 写口必须有一个
    不经过侧文件的形态。两处共用 :func:`stamp_manuscript_sign`，所以块逐字相同。

    返回键：`state` / `written` / `idempotent` / `missing` / `path` / `line` /
    `why` / `reading`。`state` 只取 :data:`MANUSCRIPT_WRITE_STATES` 里的三个词：

    - `written`：块在稿里（`idempotent=True` 表示本来就在、没重写）；
    - `failed`：有手稿落点、但没写进去（`why` 说为什么；`missing=True` 是稿不在盘上）；
    - `not_attempted`：没有手稿路径（这一签本来就只写侧文件，不是"写失败"）。

    `line` 是签块在正文里的行号（1 起；没写成 ⇒ 0）—— `write_sign` 会把它和
    `path` 一起落进签文件的 `manuscript_write` 那一格（见 :func:`manuscript_write_reading`）。
    """
    out: dict[str, Any] = {"state": "not_attempted", "written": False,
                           "idempotent": False, "missing": False,
                           "path": "", "line": 0, "why": "", "reading": {}}
    rel = str(manuscript_path or "").strip().replace("\\", "/")
    out["path"] = rel
    if not rel:
        out["why"] = "没有手稿路径 ⇒ 签块没地方写（这一格未尝试，不是失败）"
        return out
    path = Path(str(root or "")) / rel
    try:
        old = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        out.update(state="failed", missing=not path.exists(),
                   why=(f"手稿读不出来（{type(exc).__name__}: {exc}）⇒ 签块没写成"
                        if path.exists() else
                        f"`{rel}` 不在盘上 ⇒ 签块没写成（未在册送审要指向 F 的那一份手稿）"))
        return out
    new = stamp_manuscript_sign(old, proof_sha=proof_sha, streak=streak, need=need,
                                verdict=verdict, signer=signer, at=at,
                                ledger=ledger, statement_id=statement_id,
                                signed=signed)
    out["reading"] = manuscript_sign_reading(new)
    out["line"] = _sign_block_line(new)
    if new == old:
        out.update(state="written", written=True, idempotent=True,
                   why="签块已经在那一份手稿里（幂等：没重写）")
        return out
    tmp = path.with_name(path.name + ".sign.tmp")
    try:
        tmp.write_text(new, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        out["state"] = "failed"
        out["why"] = f"签块没写进手稿（{type(exc).__name__}: {exc}）"
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            # 清临时文件失败不许带走"这一笔没写成"这件事：残留的 `.sign.tmp`
            # 只是手稿旁边多一个文件，下一次写块会用一个新临时名再写。
            pass
        return out
    out.update(state="written", written=True,
               why=f"签块写进 `{rel}` 第 {out['line']} 行"
                   f"（连续 {int(streak or 0)}/{int(need or 0)}）")
    return out


def _stamp_block_after_sign(root: Any, doc: Mapping[str, Any]) -> dict[str, Any]:
    """`write_sign` 之后顺手把签块盖进它记下的那一份手稿（best-effort，不带走这一签）。

    为什么不在这失败时回滚：签文件已经在盘上（证据），手稿块是"随稿走的那一份"；
    写块失败要留读数（返回里的 `manuscript_write`），不许让"签已经发了"这件事消失。
    """
    rel = str(doc.get("artifact_path") or "").strip()
    if not rel:
        return {"state": "not_attempted", "written": False, "idempotent": False,
                "missing": False, "path": "", "line": 0,
                "why": "这一签没有手稿落点（`artifact_path` 是空的）⇒ 只写侧文件"
                       "（未尝试，不是失败）",
                "reading": {}}
    return write_manuscript_sign(
        root, rel, proof_sha=doc.get("artifact_sha"), streak=doc.get("streak"),
        need=doc.get("need"), verdict=str(doc.get("verdict") or "成立"),
        signer="V", at=str(doc.get("at") or ""),
        ledger=str(doc.get("ledger") or ""),
        statement_id=str(doc.get("statement_id") or ""))


# ---------------------------------------------------------------- 写一份签

def write_sign(root: Any, *, artifact_sha: Any, streak: int, need: int,
               artifact_path: str = "", ledger: str = "", statement_id: str = "",
               proof_no: int = 1, passes: Sequence[Mapping[str, Any]] = (),
               objections: Sequence[Mapping[str, Any]] = (), at: str = "",
               written_by: str = WRITTEN_BY_SECRETARY) -> dict[str, Any]:
    """落一份签，再更新归档（顺序固定；返回三态读数）。

    ## 门槛也在这里再判一次（不允许绕过 `signs_bit3` 直接写签）
    `streak < need` ⇒ 「一个字节都不写」（`written=False` + 理由）。理由：本函数是
    "写签"的唯一入口，若它只看调用方说的 `written=True`，那 `sign_statement` 那一侧的
    连续闸一旦泄漏，盘上就会出现"一次成立也有一份签"——而那正是这一笔要堵的形态。

    ## 一稿一签（已存在就不许覆盖）
    同一份正文只该有一个签。已存在且逐字相同 ⇒ `idempotent`（不重写，但仍补一次归档：
    上一次归档失败的话，这一次顺手修好）；已存在而内容不同 ⇒ `conflict`，「不写、不覆盖」，
    理由串说清哪一格不同 —— 覆盖会把"先签了后来又不认"这段历史抹掉。

    返回键：`written` / `idempotent` / `conflict` / `path` / `archive_error` /
    `archive_count` / `reason` / `sign` / `manuscript_write` /
    `manuscript_write_recorded`。

    ## 2026-11-02：签块同时盖进手稿（业主：「V 签不直接进台账，进手稿」）

    侧文件写成功之后，按 `doc["artifact_path"]`（`verifications._vsign_payload` 已经按
    `depsection.manuscript_relpaths` 定位好的那一份）把同一份签盖进手稿 —— 块长什么样、
    幂等与解析全在 :func:`stamp_manuscript_sign` / :func:`manuscript_sign_reading`。
    写块失败不回滚侧文件（签已经发了这件事不许消失），读数落 `manuscript_write`。

    ## 2026-11-02 晚：这一笔的读数也落进签文件本身（修 84 的 `null`）

    改前签文件里没有 `manuscript_write`：84 的两份签文件读出来是 `null`，而
    `reports/f-proof-000000.md` 里已经有块（台账指向 `verifications/000000.jsonl#v-000010`，
    正是本函数顺手盖的那一版）—— 读数与实际脱节，将来排查会照 `null` 去找。
    现在新写成的签文件会带一格 `manuscript_write`（三态：`written` / `failed` /
    `not_attempted`，形状见 :func:`manuscript_write_reading`；带上 `path` 与 `line`）。
    已在盘上的签文件仍然"不重写"（一稿一签）：旧文件没有这一格时，读侧落
    `unrecorded`，不补写、不冒充。
    """
    out: dict[str, Any] = {"written": False, "idempotent": False, "conflict": False,
                           "path": "", "archive_error": "", "archive_count": 0,
                           "reason": "", "sign": {},
                           #: 手稿签块那一笔的读数（2026-11-02）：`state` / `written` /
                           #: `idempotent` / `missing` / `path` / `line` / `why` / `reading`。
                           #: 它是一个独立的落点：侧文件是证据、手稿块是"随稿走的那一份"，
                           #: 任一失败都各自可见。
                           "manuscript_write": {},
                           #: 这一格有没有落进签文件本身（新签才可能为真；旧签不重写）。
                           "manuscript_write_recorded": False,
                           #: 这一笔被"未达门槛"拒掉（与"文件写不成"分开：前者是两道守卫
                           #: 不一致时的读数，后者是整笔失败）。
                           "refused_below_need": False}
    try:
        key = _sha_key(artifact_sha)
    except VsignError as exc:
        out["reason"] = f"{exc} ⇒ 不写签"
        return out
    if int(streak) < int(need):
        out.update(refused_below_need=True,
                   reason=(f"连续「成立」{int(streak)}/{int(need)} 次 ⇒ 一个字节都不写："
                           "未达门槛就没有签（业主：只有连续三次审核通过这才叫 V 签）"))
        return out
    doc: dict[str, Any] = {
        "schema": SIGN_SCHEMA,
        "artifact_sha": key,
        "artifact_path": str(artifact_path or ""),
        "artifact_sha_rule": ARTIFACT_SHA_RULE,
        "ledger": str(ledger or ""),
        "statement_id": str(statement_id or ""),
        "proof_no": int(proof_no or 1),
        "verdict": "成立",
        "streak": int(streak), "need": int(need),
        # 逐转读数（「不是全文」：全文在台账，见 source_note）。
        "passes": [dict(p) for p in (passes or ())],
        "objections": [dict(o) for o in (objections or ())],
        "source_note": PASSES_SOURCE_NOTE,
        "at": str(at or ""),
        "written_by": str(written_by or WRITTEN_BY_SECRETARY),
    }
    path = sign_path(root, key)
    out["path"] = rel(path, root)
    out["sign"] = doc
    if path.is_file():
        old, problem = _read_json(path)
        old_key = str((old or {}).get("artifact_sha") or "").strip().lower()
        if old is not None and old_key == key:
            # 同一份正文只有一个签（一稿一签）：已经在了就是 `idempotent`，「不重写」。
            #
            # 为什么不比内容、也不覆盖：签是"第 need 次成立那一刻"的档，第 need+1 次
            # 成立不改它（那几转只进台账）；而内容逐字比较会因为 `at`/`passes` 随下一次
            # 复查而变，把一次正常的复查读成"冲突"（实测：第 4 转会把这一笔变成整笔回滚）。
            # 冲突只留给"这一份文件不是这一份正文的签"（坏 JSON / 里面写着别的 sha）——
            # 那一档绝不覆盖：可疑的文件要人看，不许工具悄悄修好它。
            doc = old
            out["sign"] = doc
            out.update(idempotent=True,
                       reason=(f"`{out['path']}` 已经在盘上（签于 "
                               f"{str(doc.get('at') or '（没有 at）')}）⇒ 不重写：一稿一签"))
        else:
            out.update(conflict=True,
                       reason=(f"`{out['path']}` 已经在盘上，但它不是这一份正文的签"
                               f"（{problem or '文件里的 artifact_sha 与文件名不同'}）⇒ "
                               "不覆盖：可疑的签要人看，不许工具悄悄修好它"))
            return out
    else:
        try:
            _write_atomic(path, doc)
        except OSError as exc:
            out["reason"] = (f"签文件没写成（{type(exc).__name__}: {exc}）⇒ 这一签没落地"
                             "（归档一个字都不动）")
            return out
        out.update(written=True, reason="签已落盘")
    got = archive(root, doc)
    out["archive_count"] = int(got.get("count") or 0)
    if not got.get("ok"):
        out["archive_error"] = str(got.get("error") or "归档没写成")
        out["reason"] = (f"{out['reason']}；但归档没更新：{out['archive_error']}"
                         "（签文件是证据，已在盘上；归档可由 rebuild 补）")
    # ---- 2026-11-02（业主：「V 签不直接进台账，进手稿」）：同一份签盖进手稿 -----
    # 侧文件与手稿块是同一签的两个落点（同一把 sha、同一组读数）。写块失败不回滚侧文件：
    # 签已经发了这件事不许因为"稿没写成"而消失，读数写进 `manuscript_write.why`。
    out["manuscript_write"] = _stamp_block_after_sign(root, doc)
    _mw = out["manuscript_write"]
    if not _mw.get("written"):
        # 三态在收场那句话里也要分得开：没有手稿落点是"未尝试"，不是"写失败"。
        _word = "未尝试" if str(_mw.get("state") or "") == "not_attempted" else "没写成"
        out["reason"] = f"{out['reason']}；手稿签块{_word}：{_mw.get('why')}"
    # ---- 2026-11-02 晚：把这一笔的真实结果落进签文件 -------------------------
    # 只补这次新写成的签文件：已在盘上的签仍然"一稿一签、不重写"（那条纪律比
    # "把旧文件的空格补上"更重要 —— 旧文件缺这一格时读侧落 `unrecorded`）。
    # 顺序放在盖章之后：签文件先落盘是"签已经发了"的证据，写块失败也不回滚它。
    if out["written"]:
        try:
            current, problem = _read_json(path)
            if current is None:
                out["reason"] = (f"{out['reason']}；手稿签块读数没写进签文件"
                                 f"（{problem}）")
            else:
                current["manuscript_write"] = out["manuscript_write"]
                _write_atomic(path, current)
                out["sign"] = current
                out["manuscript_write_recorded"] = True
        except OSError as exc:
            out["reason"] = (f"{out['reason']}；手稿签块读数没写进签文件"
                             f"（{type(exc).__name__}: {exc}）")
    return out


# ---------------------------------------------------------------- 归档与逐份签对账

def index_drift(root: Any) -> dict[str, Any]:
    """归档 vs 逐份签文件对账 ⇒ `{checked, tri, drift, count, index, reason}`。

    三态照抄 `sessions.reconcile_run_index`（同一套词表，不发明第四套）：

    | `tri` | 什么时候 |
    |---|---|
    | `computed` | 目录在、归档读得出 ⇒ 逐条比对（`drift` 可能非空） |
    | `unreadable` | 目录在，而归档不在盘上 / 读不出来 ⇒ 这一档不是"零处不一致" |
    | `not_applicable` | 没有 `out/vsigns/` ⇒ 这个工作区还没有签（合法初态，「不红」） |

    四条判据的落点全在 `drift` 里（顺序固定，读的人照着改）：

    1. 「重建不一致」：盘上那份与 :func:`compute_index` 的现算结果不是逐格相等；
    2. 「漏记」：`<sha>.json` 在盘上而归档里没有这一条（归档失败 / 有人删了一行）；
    3. 「虚记」：归档里有而 `<sha>.json` 不在盘上（手补 / 签文件被删）；
    4. 「伪造痕迹」：`archived_by != ARCHIVED_BY`，或 `archived_at != 签文件的 at`。
    """
    out: dict[str, Any] = {"checked": False, "tri": "unreadable", "drift": [],
                           "count": 0, "index": {}, "reason": ""}
    d = signs_dir(root)
    if not d.is_dir():
        out.update(checked=True, tri="not_applicable",
                   reason=(f"`{SIGNS_DIR}/` 不在盘上 ⇒ 这个工作区还没有签过"
                           "（合法初态：不是「归档对上了」，是没有源）"))
        return out
    computed = compute_index(root)
    out["count"] = int(computed.get("count") or 0)
    doc, problem = load_index(root)
    drift: list[str] = []
    drift.extend(f"签文件读不出：{p}" for p in (computed.get("problems") or []))
    if doc is None:
        out.update(checked=False, tri="unreadable", drift=drift,
                   reason=(f"{problem} ⇒ 有 {out['count']} 份签文件而归档读不出来，"
                           "这一格「没查成」（不是「归档一致」）"))
        return out
    out.update(checked=True, tri="computed", index=doc)
    stored = {str(e.get("artifact_sha") or ""): dict(e)
              for e in (doc.get("signs") or []) if isinstance(e, Mapping)}
    want = {str(e.get("artifact_sha") or ""): dict(e) for e in (computed.get("signs") or [])}
    for sha in sorted(set(want) - set(stored)):
        drift.append(f"漏记：`{SIGNS_DIR}/{sha}.json` 在盘上，而 `{INDEX_NAME}` 里没有这一条")
    for sha in sorted(set(stored) - set(want)):
        drift.append(f"虚记：`{INDEX_NAME}` 里有 `{sha}`，而 `{SIGNS_DIR}/{sha}.json` 不在盘上")
    for sha in sorted(set(stored) & set(want)):
        got, exp = stored[sha], want[sha]
        if got != exp:
            keys = sorted(k for k in set(got) | set(exp) if got.get(k) != exp.get(k))
            drift.append(f"重建不一致：归档项 {sha[:12]}… 与从签文件现算的结果不同"
                         f"（{', '.join(keys[:6])}）")
        if str(got.get("archived_by") or "") != ARCHIVED_BY:
            drift.append(f"伪造痕迹：{sha[:12]}… 的 `archived_by` 是 "
                         f"{str(got.get('archived_by') or '（空）')!r}，"
                         f"不是发签工具标识 {ARCHIVED_BY!r} ⇒ 这一条是被人补进去的")
        if str(got.get("archived_at") or "") != str(got.get("at") or ""):
            drift.append(f"伪造痕迹：{sha[:12]}… 的 `archived_at` "
                         f"{str(got.get('archived_at') or '（空）')!r} 不是派生值"
                         f"（应等于签文件的 at {str(got.get('at') or '（空）')!r}）")
    if list((doc.get("signs") or [])) != list(computed.get("signs") or []):
        # 顺序 / 条数 / 逐格都算在"重建一致"这一条里：数组顺序也是判据的一部分。
        if not any(x.startswith(("漏记", "虚记", "重建不一致", "伪造痕迹")) for x in drift):
            drift.append(f"重建不一致：`{INDEX_NAME}` 与现算结果的顺序或条数不同")
    out["drift"] = drift
    out["reason"] = "" if not drift else "归档与逐份签文件对不上，见 drift（逐条）"
    return out


# ---------------------------------------------------------------- 回执读口（不落文件）

def _ledger_rows(root: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """全部顶层台账行（`verifications/*.jsonl`；`pending/` 那一层不在这一档）。

    为什么不用 `list_verifications`：那是"按命题号"的读口，一个号一次读盘；
    "全局打回了几条"要一次读完全部账 —— 两处各写一遍遍历就会漂（这是本模块唯一的遍历）。
    """
    from . import jsonlfile as _JF
    from . import verifications as _VR

    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    d = _VR.verifications_dir(root)
    if not d.is_dir():
        return rows, problems
    for path in sorted(d.glob("*.jsonl")):
        got, bad = _JF.read_jsonl(path)
        problems.extend(f"{path.name}: {b}" for b in bad)
        for row in got:
            if isinstance(row, Mapping):
                rows.append(dict(row))
    return rows, problems


def _fault_rows(root: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """台账里所有「有毛病」那一档的行（两档都算：V 自己判的、秘书判 fault 的）。

    判据不在这里：轴由 `verifications.secretary_axis` / `read_verdict` 给
    （`:func:`verdict_axis` 只是把两处拼成一个词，供本模块的读侧用）。
    """
    from . import verifications as _VR

    rows, problems = _ledger_rows(root)
    out = [r for r in rows if verdict_axis(r)]
    return out, problems


def verdict_axis(row: Mapping[str, Any]) -> str:
    """这一行算不算一次「有毛病」（`verdict` / `secretary_fault` / 空串）。

    两档合起来才是"要交回 F 改"的全集（与 `agent_loop.v_rejections_digest` 同一口径）：
    - `verdict`：V 自己的结论写的就是「有毛病」；
    - `secretary_fault`：V 写「成立」而秘书读出来它指出了缺陷。
    老台账行上没有秘书轴（`secretary_axis` 读成空串）⇒ 只按结论词判。

    「次序不能反」：先看结论词。一行既写着「有毛病」、秘书也判了 fault 时它是 `verdict`
    （81 的 8 条都是这一档）—— 反过来读会把"V 自己判的打回"说成"秘书在他没问题的话里
    读出缺陷"，而交付那一侧的措辞正是按这一格分的。
    """
    from . import verifications as _VR

    if _VR.read_verdict(row) == "有毛病":
        return "verdict"
    if _VR.secretary_axis(row) == "fault":
        return "secretary_fault"
    return ""


def defect_steps(row: Mapping[str, Any]) -> list[int]:
    """这一行点名的缺陷步（`defect_step` + 每条 finding 的 `step`，去重升序）。"""
    steps: set[int] = set()
    defect = row.get("defect_step")
    if isinstance(defect, int):
        steps.add(int(defect))
    for f in (row.get("findings") or []):
        if isinstance(f, Mapping) and isinstance(f.get("step"), int):
            steps.add(int(f["step"]))
    return sorted(steps)


def receipt_of(root: Any, artifact_sha: Any) -> dict[str, Any]:
    """一份「有毛病」回执（「从台账现算，不落文件」）。

    为什么回执不落文件（业主 2026-11-01 裁定采纳 A）：`defect_step` / `findings` /
    `why` / `washed_relay` / `proof_sha256` 今天全在台账那一行上 —— 再抄一份就是
    可漂的第二副本，而且历史那 8 条永远补不出 `at`。所以"回执"= 台账的一个读视图。

    返回 `{checked, found, artifact_sha, rows, defects, verdict, at, why}`：
    `rows` 是同一份正文上的全部回执行（「按台账行序」，同一 sha 可以判多次 ——
    81 的 000000 就判了两次），`defects` 是最近那一次逐条展开的缺陷。
    """
    from . import verifications as _VR

    out: dict[str, Any] = {"checked": False, "found": False, "artifact_sha": "",
                           "rows": [], "defects": [], "verdict": "", "at": "", "why": ""}
    try:
        key = _sha_key(artifact_sha)
    except VsignError as exc:
        out["why"] = f"{exc} ⇒ 这一格没查成"
        return out
    out.update(checked=True, artifact_sha=key)
    rows, problems = _fault_rows(root)
    mine = [r for r in rows if str(r.get("proof_sha256") or "") == key]
    out["rows"] = [{k: r.get(k) for k in ("verification_id", "stmt_id", "proof_no",
                                          "verdict", "defect_step", "unresolved_errors",
                                          "at")}
                   | {"axis": verdict_axis(r)} for r in mine]
    if not mine:
        out["why"] = ("台账里没有这一份正文的「有毛病」那一签 ⇒ 没有回执"
                      + (f"（{problems[:2]}）" if problems else ""))
        return out
    last = mine[-1]
    out.update(found=True, verdict=str(_VR.read_verdict(last) or ""),
               at=str(last.get("at") or ""))
    out["defects"] = [{"step": step, "text": _defect_text(last, step)}
                      for step in defect_steps(last)]
    out["why"] = (f"台账里有 {len(mine)} 条这一份正文的「有毛病」（最近一签 "
                  f"{str(last.get('verification_id') or '')}）")
    return out


def _defect_text(row: Mapping[str, Any], step: int) -> str:
    """某一步的缺陷原文：先取那一步的 finding，没有就取洗过的转达里那一段。"""
    for f in (row.get("findings") or []):
        if isinstance(f, Mapping) and f.get("step") == step:
            text = str(f.get("detail") or "").strip()
            if text:
                return text
    relay = str((row.get("washed_relay") or {}).get("text") or "").strip()
    if relay:
        return relay
    return str(row.get("why") or "").strip()


# ---------------------------------------------------------------- 送达读口（不落文件）

def _board_items(store: Any) -> tuple[dict[str, dict[str, Any]], str]:
    """`tasks` 里全部「V 判决」板项 ⇒ `{input_key: row}`（读不成 ⇒ `(空, 原因)`）。"""
    if store is None:
        return {}, "没有 store ⇒ 板项这一格没查成（不是「没送达」）"
    try:
        rows = [dict(r) for r in store.rows("tasks")]
    except Exception as exc:  # noqa: BLE001 —— 读不成是「没查成」，不是「没送达」
        return {}, f"`tasks` 读不出来（{type(exc).__name__}: {exc}）"
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("input_key") or "")
        if key.startswith("v-verdict@"):
            out[key] = row
    return out, ""


def _mailbox_times(root: Any) -> dict[str, str]:
    """`agent_mailbox` 事件里"某一板项被读进哪一步、什么时候" ⇒ `{item_id: at}`。

    唯一来路是会话文件（`agent_loop.record_mailbox_delivery` 落的那一条），
    本模块不复制第二份 —— 读不出来就返回空表（调用方把 `delivered_at` 留空，
    并在 `problems` 里说一句"时刻没读到"，绝不编一个时间）。
    """
    times: dict[str, str] = {}
    base = Path(str(root)) / "sessions"
    if not base.is_dir():
        return times
    for path in sorted(base.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or '"agent_mailbox"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if str(rec.get("kind") or "") != "agent_mailbox":
                        continue
                    at = str(rec.get("at") or "")
                    for item in (rec.get("item_ids") or []):
                        times.setdefault(str(item), at)
        except OSError:
            continue
    return times


def delivery_of(root: Any, store: Any, *, label: str, verification_id: str,
                mailbox: Mapping[str, str] | None = None) -> dict[str, Any]:
    """一条判决送达了没有（三档：`delivered` / `dispatched_only` / `not_dispatched`）。

    判据（缺一不可，全部是盘上已有的读数，不新增写点）：

    - 交付：`tasks` 里有一条 `input_key = v-verdict@<label>@<vid>@<收件人>` 的板项
      （改前投的那一批没有收件人后缀 `v-verdict@<label>@<vid>`，照样认 ——
      读旧盘的口径不许因为键加了收件人就把 81 的 4 条读成"没投"。业主 2026-11-01）；
    - 读取：那一行 `item_close == "acked"`（`v-verdict@` 在
      `conductor.ACK_REQUIRED_ITEM_PREFIXES` 里 ⇒ 不会"渲染即收口"，`acked` 只能是
      收件人自己 ack 过的），并读 `seen_by` / `seen_step`；
    - 时刻：`agent_mailbox` 事件的 `at`（读不到就留空并在 `problems` 里说）。
    """
    key = f"v-verdict@{label}@{verification_id}"
    out: dict[str, Any] = {"state": "not_dispatched", "input_key": key,
                           "delivered_to": "", "delivered_at": "", "read_by": "",
                           "read_step": None, "item_task_id": "", "problems": []}
    items, problem = _board_items(store)
    if problem:
        out["problems"].append(problem)
    row = items.get(key) or {}
    if not row:
        # 带收件人后缀的新键（同一 label@vid 可能有多个收件人；取第一个可读的，
        # 排序只为"同一份盘读两次得同一个答案"，不是裁决谁更该收）。
        for one_key in sorted(items):
            if one_key.startswith(key + "@"):
                row = items[one_key]
                out["input_key"] = one_key
                break
    if not row:
        return out
    out["item_task_id"] = str(row.get("task_id") or "")
    out["delivered_to"] = str(row.get("role") or "")
    out["read_by"] = str(row.get("seen_by") or "")
    step = row.get("seen_step")
    out["read_step"] = int(step) if isinstance(step, int) else None
    acked = str(row.get("item_close") or "") == "acked"
    out["state"] = "delivered" if acked else "dispatched_only"
    if acked:
        box = mailbox if mailbox is not None else _mailbox_times(root)
        out["delivered_at"] = str(box.get(out["item_task_id"]) or "")
        if not out["delivered_at"]:
            out["problems"].append(
                "送达了，但 `agent_mailbox` 事件里读不到读它的时刻 ⇒ delivered_at 留空"
                "（不编时间）")
    return out


def receipt_digest(root: Any, store: Any = None, *, limit: int = 8,
                   times: bool = True) -> dict[str, Any]:
    """全局「V 打回 + 送达」读数（M 侧的一眼清单；数据源只有台账 + tasks + 会话事件）。

    返回：`checked` / `receipts`（回执行数）/ `statements`（涉及的命题数）/
    `delivered` / `dispatched` / `not_dispatched` / `undelivered` / `undelivered_ids` /
    `steps`（缺陷步分布）/ `rows`（前 `limit` 条，含 label / state / delivered_to /
    delivered_at）/ `problems` / `reason`。

    `dispatched` 与 `delivered` 是两个数（业主 2026-11-01 裁定）：
    `dispatched` = 板项在（不管读没读）；`delivered` = 收件人真的读过并 ack 了。
    折成一个"未送达"会让"没人投"与"投了没人读"在读数上同形 —— 81 之前那一版正是
    这么读的（8 条全算"未送达"里挑，`dispatched_only` 那一档被讲成了"没送到"）。
    `undelivered` 保留旧口径（`receipts - delivered`），供既有读者（收工门 / M 的
    `global_v_rejections_text`）逐字不变。

    三态：台账读不成 ⇒ `checked=False`（「不是」"没有打回"）；`store=None` ⇒ 送达那一
    半没查成（`delivery_checked=False`），但回执数照样给。
    """
    from . import verifications as _VR

    out: dict[str, Any] = {"checked": False, "delivery_checked": False, "receipts": 0,
                           "statements": 0, "delivered": 0, "undelivered": 0,
                           "dispatched": 0, "not_dispatched": 0,
                           "submitter_is_not_author": 0, "author_not_recorded": 0,
                           "undelivered_ids": [], "steps": {}, "rows": [],
                           "problems": [], "reason": ""}
    rows, problems = _fault_rows(root)
    out["problems"] = list(problems)
    if problems and not rows:
        out["reason"] = (f"台账读不出来（{problems[:2]}）⇒ 这一格没查成"
                         "（不是「一条都没打回」）")
        return out
    out["checked"] = True
    if not rows:
        out["reason"] = "台账里没有「有毛病」那一档的签 ⇒ 一条打回都没有（查过了）"
        return out
    out["receipts"] = len(rows)
    out["statements"] = len({str(r.get("stmt_id") or r.get("statement_id") or "")
                             for r in rows})
    steps: dict[str, int] = {}
    for row in rows:
        for step in defect_steps(row):
            steps[str(step)] = steps.get(str(step), 0) + 1
    out["steps"] = dict(sorted(steps.items(), key=lambda kv: int(kv[0])))
    mailbox = _mailbox_times(root) if times else {}
    items, item_problem = _board_items(store)
    out["delivery_checked"] = not item_problem
    if item_problem:
        out["problems"].append(item_problem + " ⇒ 送达那一半没查成")
    detail: list[dict[str, Any]] = []
    # 167：作者 / 送审者这一格（业主 2026-11-01「谁写证明谁送审」）。
    # 用惰性 import：`vreceipts` 的读口又会调回本函数，模块级 import 会成环。
    try:
        from . import vreceipts as _VRC

        box = _VRC.outbox_index(root)
    except Exception:  # noqa: BLE001 —— 读不成是"作者/送审者这一格没查成"
        _VRC, box = None, {}
        out["problems"].append("outbox 读不出来 ⇒ 作者/送审者这一格没查成")
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        no = int(_VR.as_proof_no(row.get("proof_no")) or 1)
        label = f"{sid}#p{no}"
        vid = str(row.get("verification_id") or "")
        one = delivery_of(root, store, label=label, verification_id=vid, mailbox=mailbox)
        rec = dict(box.get((label, vid)) or {})
        author = _VRC.statement_author_of(store, label) if _VRC is not None else {
            "checked": False, "author": "", "source": "", "reason": "outbox 读不成"}
        submitter_role = str(rec.get("submitter_role") or one["delivered_to"] or "")
        author_role = str(author.get("author") or "")
        if author.get("checked"):
            not_author = bool(author_role and submitter_role
                              and author_role != submitter_role)
            author_unknown = False
        else:
            not_author, author_unknown = None, True
        detail.append({
            "artifact_sha": str(row.get("proof_sha256") or ""),
            "label": label, "verification_id": vid,
            "axis": verdict_axis(row), "at": str(row.get("at") or ""),
            "defect_steps": defect_steps(row), "state": one["state"],
            "delivered_to": one["delivered_to"], "delivered_at": one["delivered_at"],
            "read_by": one["read_by"], "read_step": one["read_step"],
            # 送审者 / 作者 / 替人送审那一档（可见，不是路由：回执仍投送审者）
            "submitter": str(rec.get("submitter") or ""),
            "submitter_role": submitter_role,
            "author": author_role,
            "author_source": str(author.get("source") or ""),
            "submitter_is_not_author": not_author,
            "author_not_recorded": author_unknown,
        })
    out["delivered"] = sum(1 for d in detail if d["state"] == "delivered")
    out["dispatched"] = sum(1 for d in detail if d["state"] != "not_dispatched")
    out["not_dispatched"] = int(out["receipts"]) - int(out["dispatched"])
    out["undelivered"] = int(out["receipts"]) - int(out["delivered"])
    # 「替人送审」按 error 级别单独计数；作者未记录是另一档（不是"没问题"）。
    out["submitter_is_not_author"] = sum(1 for d in detail
                                         if d["submitter_is_not_author"] is True)
    out["author_not_recorded"] = sum(1 for d in detail if d["author_not_recorded"])
    out["undelivered_ids"] = [f"{d['label']}@{d['verification_id']}" for d in detail
                              if d["state"] != "delivered"]
    out["rows"] = detail[:max(1, int(limit))]
    out["reason"] = (f"「有毛病」{out['receipts']} 条（{out['statements']} 条命题）；"
                     f"已投出 {out['dispatched']} 条（其中已送达 {out['delivered']} 条）、"
                     f"未投出 {out['not_dispatched']} 条、未送达 {out['undelivered']} 条"
                     + (f"；替人送审 {out['submitter_is_not_author']} 条（error）"
                        if out["submitter_is_not_author"] else "")
                     + (f"；作者未记录 {out['author_not_recorded']} 条"
                        if out["author_not_recorded"] else "")
                     + ("；送达那一半没查成" if item_problem else ""))
    return out


def undelivered_reading(root: Any, store: Any = None) -> dict[str, Any]:
    """只要"没送到"的那几条（M 侧巡查 / 收工前检查用；形状与 :func:`receipt_digest` 同源）。"""
    got = receipt_digest(root, store, limit=10_000)
    keep = [r for r in (got.get("rows") or []) if r.get("state") != "delivered"]
    return {"checked": bool(got.get("checked")), "count": len(keep), "rows": keep,
            "reason": str(got.get("reason") or "")}


# ---------------------------------------------------------------- 门读数

def backed_reading(root: Any, rows: Iterable[Mapping[str, Any]],
                   store: Any = None) -> dict[str, Any]:
    """门那一格：「哪些命题的"签"在盘上有侧文件、哪些没有、哪些签没有对应的命题」。

    β 口径（"这份签被哪些 statement 用了"）在这里现算，「不进归档」：
    `used_by` 是 `{artifact_sha: [命题号…]}`，由命题行的 `proof_text` 现算 ——
    归档一旦记它，B 每次登记都要回写归档（多一个写点），而"谁用了这份签"本来就是
    命题表的事实，不是签的事实。

    三态：没有 `out/vsigns/` ⇒ `tri="not_applicable"`（「这一档不红」：66 行历史签
    补不出侧文件，补就是伪造 `at` —— 见模块 docstring 的 α 口径）；
    目录在而签文件读不出 ⇒ `tri="unreadable"` + `problems`。

    返回 `{checked, tri, signed, backed, without_sign, used_by, orphan_signs,
    problems, reason}`：
    - `signed`：命题行现算第 3 位为真的命题号（`evidencebits.bits_from_row`，不看盘上缓存）；
    - `backed`：其中"这一份正文的签文件真的在盘上"的那些；
    - `without_sign`：`signed` 里没有侧文件的那些（「读数，不是红」：历史签 / 直调写的签）；
    - `orphan_signs`：签文件在、而盘上没有任何命题的正文 sha 等于它（「这一档可以红」）。
    """
    from . import evidencebits as _EB
    from . import verifications as _VR

    out: dict[str, Any] = {"checked": False, "tri": "unreadable", "signed": [],
                           "backed": [], "without_sign": [], "used_by": {},
                           "orphan_signs": [], "problems": [], "reason": ""}
    signed: list[str] = []
    used_by: dict[str, list[str]] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        if not sid or str(row.get("kind") or "") == "concept":
            continue
        try:
            bits = _EB.bits_from_row(dict(row))
        except Exception:  # noqa: BLE001 —— 位算不出来是"这一条没查成"，不影响别的行
            continue
        sha = ""
        try:
            sha = _VR.proof_sha(str(row.get("proof_text") or ""))
        except Exception:  # noqa: BLE001
            sha = ""
        if sha:
            used_by.setdefault(sha, []).append(sid)
        if bits.get("reviewed"):
            signed.append(sid)
    out["signed"] = signed
    out["used_by"] = {k: sorted(set(v)) for k, v in sorted(used_by.items())}
    d = signs_dir(root)
    files = sorted(p for p in d.glob("*.json") if p.name != INDEX_NAME) if d.is_dir() else []
    if not d.is_dir():
        out.update(checked=True, tri="not_applicable",
                   reason=(f"`{SIGNS_DIR}/` 不在盘上 ⇒ 这个工作区还没有签的侧文件"
                           "（历史签补不出侧文件，不补；这一档不红）"))
        return out
    on_disk: dict[str, dict[str, Any]] = {}
    for path in files:
        doc, problem = _read_json(path)
        if doc is None:
            out["problems"].append(f"{path.name}：{problem}")
            continue
        on_disk[path.stem.lower()] = doc
    out["checked"] = not out["problems"]
    out["tri"] = "computed" if out["checked"] else "unreadable"
    # 命题行现在的正文 sha ⇒ 哪些签文件有主（`used_by` 已经算好，这里只反向查）。
    backed: list[str] = []
    for sid in signed:
        sha = next((s for s, ids in out["used_by"].items() if sid in ids), "")
        if sha and sha in on_disk and str(on_disk[sha].get("statement_id") or "") == sid:
            backed.append(sid)
    out["backed"] = backed
    out["without_sign"] = [sid for sid in signed if sid not in backed]
    out["orphan_signs"] = sorted(sha for sha in on_disk
                                 if sha not in out["used_by"])
    total = len(on_disk)
    out["reason"] = (f"签的侧文件 {total} 份；命题行现算第 3 位为真 {len(signed)} 条，"
                     f"其中 {len(backed)} 条有对应签文件、{len(out['without_sign'])} 条没有"
                     "（历史签 / 直调写的签，不补）；"
                     f"没有主的签文件 {len(out['orphan_signs'])} 份")
    return out


# ---------------------------------------------------------------- 签 → 五元位（B 收录时用）

def bits_after_sign(bits: Mapping[str, Any], *, root: Any, proof_text: str,
                    statement_id: str = "", proof_no: Any = 1,
                    kind: str = "", manuscript_text: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    """B 收录时"认签"：有一份对得上这一份正文的签 ⇒ 把第 3 位写成已签。

    返回 `(bits, reading)`。`reading` 是这一步的读数（「三态」）：
    `{checked, found, applied, artifact_sha, why}` —— `found=False` 时 `bits` 原样返回
    （一个字节都不动：没签过不是"把审过的擦掉"）。

    ## 为什么要 B 这一笔（而不是只靠 `sign_statement`）
    业主 2026-11-01：「B 侧自己写的证明想要 V 签时一样是拿到 V 签，B 再录入」。
    B 重登记（改稿 / 换证明清单）时那一行的 `bits` 是「现算」的，如果只有
    `sign_statement` 那一侧会写位，B 这一笔就会把"签过"重新算成"没签过"。
    这一格就是"认签"的那一步：「它只能把位从假改真，且只在这一份正文本身有签时」。

    ## 它凭什么敢写（三道都不许少）
    1. 签文件里的 `artifact_sha` == `proof_sha(proof_text)`（同一把尺，见 :data:`ARTIFACT_SHA_RULE`）；
    2. 签文件里的 `streak >= need`（门槛在签文件里也留着，读侧再判一次）；
    3. 给了 `statement_id` 时，签文件里的 `statement_id` 必须与它相同 ——
       「同一段正文被另一条命题复用不算签过」（那是借光，`#p2` 不许借 `#p1` 的老纪律）。

    ## `statement_id` 为空 = 正在新建一条命题（2026-11-02 改）
    改前这一档直接放弃认签（"新建的那一条不可能已经签过"），于是「先有签、后登记」
    永远认不到：V 在命题还没在册时审的那一签落在 `verifications/pending/<sha>.jsonl`
    （D-34 的落点），而 B 一登记就把它漏掉 —— 同一份正文，先签后登记与先登记后签
    成了两件事。同一条纪律在 `AgentB._v_signature_for` 里早就按正文 sha 去 pending
    认领了，两处必须同一把尺。

    所以空号这一档改走 pending 认领（:func:`_claim_pending_sign`）：按
    「正文 sha + 未在册」认一签，判据与 V 那条 pending 台账同一把尺
    （`verifications.row_signable`）。认领之后回写 `statement_id`（登记拿到号之后由
    `register_statement` 调 :func:`bind_pending_claim`）—— 那就是"同一份正文只认领一次"
    的锁：第二笔同文登记看到台账行已经绑了号，就不再认。

    ## 返回的 `claim`（只在 pending 认领这一档出现）
    `{ledger, verification_id, proof_sha256, object_sha256, bound_id, bound}`：
    `bound_id` 非空 = 这一签早被别的命题认过（`bound=True`，这一笔不认）；
    空 = 这一笔刚认下、等登记回写。老返回形状不变（`claim` 只在 pending 这一档出现）。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "applied": False,
                           "artifact_sha": "", "why": ""}
    if not str(proof_text or "").strip():
        out["checked"] = True
        out["why"] = "没有正文 ⇒ 认不了签（签是盖在正文上的，签不了空串）"
        return dict(bits), out
    from . import verifications as _VR

    sha = _VR.proof_sha(str(proof_text))
    # ---- 2026-11-02（业主：「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或命题
    #      收录时读到」）：手稿里那一行签块是 B 收录时的第一来源 ----
    #
    # 判据不在 B 那一侧重写：读块、比 sha、看连续次数全在 `manuscript_sign_standing`
    # 一处（与侧文件/pending 同一把尺：`streak >= need` 且正文 sha 相符）。
    # 块说 signed ⇒ 认；块说 rejected / stale ⇒ 不认（理由带走，`found=True` 让读的人
    # 分得清"没有块"与"有块但不能认"）。没有块 ⇒ 落到下面既有的两条来源。
    if str(manuscript_text or "").strip():
        try:
            no = int(_VR.as_proof_no(proof_no) or 1)
        except (TypeError, ValueError):
            no = 1
        block = manuscript_sign_standing(str(manuscript_text), proof_sha=sha)
        out.update(checked=bool(block.get("checked")),
                   found=bool(block.get("found")), artifact_sha=sha,
                   why=str(block.get("why") or ""), block=dict(block))
        if str(block.get("state") or "") == "signed":
            new = _apply_review_to_bits(
                bits, verification_id="", evidence=str(block.get("ledger") or ""),
                findings=[], verdict="成立", proof_no=no, sha=sha,
                kind=str(kind or ""))
            out["applied"] = True
            out["why"] = (f"手稿里的签块：连续 {block.get('streak')}/{block.get('need')}"
                          f" 成立且正文 sha 相符（签于 {block.get('at') or '（没有时间）'}）"
                          " ⇒ 第 3 位按手稿里的签写")
            return new, out
        if str(block.get("state") or "") in ("rejected", "stale"):
            return dict(bits), out
    if not str(statement_id or "").strip():
        return _claim_pending_sign(bits, root=root, sha=sha, proof_no=proof_no,
                                   kind=kind, out=out)
    try:
        no = int(_VR.as_proof_no(proof_no) or 1)
    except (TypeError, ValueError):
        no = 1
    got = sign_of(root, sha)
    out.update(checked=bool(got.get("checked")), found=bool(got.get("found")),
               artifact_sha=sha, why=str(got.get("why") or ""))
    if not got.get("found"):
        return dict(bits), out
    sign = dict(got.get("sign") or {})
    if str(sign.get("statement_id") or "") != str(statement_id):
        out["why"] = (f"这一份正文的签属于 stmt:{str(sign.get('statement_id') or '（空）')}，"
                      f"不是 stmt:{statement_id} ⇒ 不认（同一段正文被别的命题复用不算签过）")
        return dict(bits), out
    if int(sign.get("streak") or 0) < int(sign.get("need") or 0):
        out["why"] = (f"签文件里的连续读数是 {sign.get('streak')}/{sign.get('need')}"
                      " ⇒ 未达门槛，不认")
        return dict(bits), out
    passes = [dict(p) for p in (sign.get("passes") or []) if isinstance(p, Mapping)]
    last = passes[-1] if passes else {}
    new = _apply_review_to_bits(
        bits, verification_id=str(last.get("verification_id") or ""),
        evidence=str(sign.get("ledger") or ""), findings=[],
        verdict="成立", proof_no=no, sha=sha, kind=str(kind or ""))
    out["applied"] = True
    out["why"] = (f"这一份正文有签（连续 {sign.get('streak')}/{sign.get('need')} 次成立，"
                  f"签于 {str(sign.get('at') or '')}）⇒ 第 3 位按签写")
    return new, out


def _apply_review_to_bits(bits: Mapping[str, Any], *, verification_id: str,
                          evidence: str, findings: Sequence[Mapping[str, Any]],
                          verdict: str, proof_no: int, sha: str,
                          kind: str) -> dict[str, Any]:
    """把"这一份正文审过了"写进五元位第 3 位（两个来源共用这一份实现：签文件 / pending）。

    为什么不各写一遍：签文件与 pending 台账是同一件事的两个落点（业主 2026-10-27
    收口的那条纪律："同一份证据、两个落点、同一套判定"）。各写一遍，两边的
    `reviewed_by` / 逐条表形状迟早分家 —— 读侧（`evidencebits` / 收工门 R10）
    读到的就会是两套东西。
    """
    from . import evidencebits as _EBmod

    new = dict(bits)
    ev = dict(new.get("evidence") or {})
    ev["reviewed_by"] = {
        "verifier": "V",
        "verification_id": str(verification_id or ""),
        "round": None,
        "verdict": str(verdict or "成立"),
        "evidence": str(evidence or ""),
        "findings": [dict(f) for f in (findings or ()) if isinstance(f, Mapping)],
        "proof_no": int(proof_no),
        "proof_sha256": str(sha or ""),
    }
    # 逐条表整表写（与 `_reviewed_statement_row` 同一个形状：`#p2` 不许借 `#p1` 的光）。
    per = {str(n): bool(v) for n, v in
           (_EBmod.reviewed_by_proof(dict(bits)) or {}).items()}
    per[str(int(proof_no))] = True
    ev[_EBmod.REVIEWED_BY_PROOF_KEY] = per
    sha_by = {str(n): str(v) for n, v in
              (_EBmod.reviewed_sha_by_proof(dict(bits)) or {}).items()}
    sha_by[str(int(proof_no))] = str(sha or "")
    ev[_EBmod.REVIEWED_SHA_BY_PROOF_KEY] = sha_by
    new["reviewed"] = True
    new["evidence"] = ev
    return _EBmod.normalize_raw(new, origin=str(new.get("origin") or "own_result"),
                                kind=str(kind or ""))


def _claim_pending_sign(bits: Mapping[str, Any], *, root: Any, sha: str,
                        proof_no: Any, kind: str,
                        out: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """`statement_id` 为空（正在新建命题）时，按正文 sha 去 pending 台账认那一签。

    判据与 V 那条 pending 台账同一把尺（`verifications.row_signable`：结论「成立」、
    没有未解决的 error、引用核实不挡；连续次数这一档在 pending 这条路上结构上不存在，
    理由见 `verifications._gap_from_pending`）。四个结局都写进 `out["why"]`，拒绝折平。
    """
    from . import verifications as _VR

    out["artifact_sha"] = str(sha or "")
    try:
        got = _VR.pending_sign(root, proof_shas=(str(sha or ""),))
    except Exception as exc:  # noqa: BLE001 —— pending 读不动 ⇒ 没查成，不是"没有签"
        out.update(checked=False,
                   why=(f"`verifications/{_VR.PENDING_DIR_NAME}/` 读不出来"
                        f"（{type(exc).__name__}: {exc}）⇒ 认签这一格没查成（不是「没有签」）"))
        return dict(bits), out
    out["checked"] = True
    if not got.get("found"):
        out["why"] = (f"`verifications/{_VR.PENDING_DIR_NAME}/` 里没有盖住这一份正文的签"
                      "（它是新建的，V 也没在它登记之前审过）⇒ 第 3 位保持假")
        return dict(bits), out
    row = dict(got.get("row") or {})
    out["found"] = True
    ledger = str(got.get("ledger") or "")
    claim = {"ledger": ledger,
             "verification_id": str(ledger).split("#")[-1],
             "proof_sha256": str(got.get("proof_sha256") or sha or ""),
             "object_sha256": str(got.get("object_sha256") or ""),
             "bound_id": "", "bound": False}
    bound = str(row.get("stmt_id") or row.get("statement_id") or "")
    if bound:
        claim.update(bound_id=bound, bound=True)
        out["claim"] = claim
        out["why"] = (f"{ledger} 这一签已经认给 stmt:{bound} ⇒ 不再认领"
                      "（同一份正文只认领一次；改稿请重签，登记不产生第二份签）")
        return dict(bits), out
    if not _VR.row_signable(row):
        out["why"] = ("命题还没在册时 V 审过这一份，但那一签签不住"
                      f"（结论 {_VR.read_verdict(row)!r}、未解决 error "
                      f"{int(row.get('unresolved_errors') or 0)} 条、引用核实那一格见台账）"
                      " ⇒ 不认（与 V 那条 pending 台账同一把尺：签不住的不许签第 3 位）")
        return dict(bits), out
    try:
        no = int(_VR.as_proof_no(proof_no) or 1)
    except (TypeError, ValueError):
        no = 1
    new = _apply_review_to_bits(
        bits, verification_id=claim["verification_id"], evidence=ledger,
        findings=list(row.get("findings") or ()),
        verdict=_VR.read_verdict(row), proof_no=no,
        sha=str(row.get("proof_sha256") or sha or ""), kind=str(kind or ""))
    out["claim"] = claim
    out["applied"] = True
    out["why"] = (f"{ledger} 是命题还没在册时 V 审的那一签"
                  f"（verdict={got.get('verdict')!r}）⇒ 按这一份正文的 sha 认领、"
                  "第 3 位按签写；登记拿到号之后回写 statement_id（同一份正文只认领一次）")
    return new, out


def bind_pending_claim(root: Any, *, claim: Mapping[str, Any],
                       statement_id: str) -> dict[str, Any]:
    """登记拿到号之后，把这一签认领在 pending 台账行上（回写 `statement_id`）。

    为什么必须回写：`bits_after_sign` 在"新建命题"那一档只能按正文 sha 认签
    （那时还没有号），若不在台账行上留下"这一签认给谁了"，同一份正文被登记两次就会
    认领两次 —— 而两笔的 `statement_id` 不同，同一份签会同时被记在两条命题名下
    （`#p2` 不许借 `#p1` 的光，反方向同理）。

    ## 写什么
    只改那一行（按 `verification_id` 定位）：`statement_id` / `stmt_id` 两键同值
    （与 `record_verification` 同一个双写口径），另加 `claimed_at`（什么时候认的）。
    已经绑了别的号 ⇒ 一个字节都不写，返回 `bound_elsewhere`（不覆盖前一笔的认领）。

    ## 怎么写的（全仓唯一一处写 pending 台账）
    pending 台账是 append-only 的（`verifications.record_pending_sign` 追加）；
    这一格是唯一的"回写"——只重写那一行，其余行逐字节原样
    （`splitlines(keepends=True)` 保住行尾），写临时文件再 `replace`（与
    `_write_atomic` 同一手法）。三态：`checked=False` = 没写成（读不出来 / 行不见了 /
    写盘失败），不许折成"已经绑了"。
    """
    out: dict[str, Any] = {"checked": False, "bound": False, "already": False,
                           "statement_id": str(statement_id or ""), "ledger": "",
                           "why": ""}
    sid = str(statement_id or "").strip()
    ledger = str((claim or {}).get("ledger") or "")
    out["ledger"] = ledger
    if not ledger:
        out["why"] = "没有台账落点 ⇒ 没写成（不是「已经绑了」）"
        return out
    if not sid:
        out["why"] = "没有命题号 ⇒ 不猜（这一行仍然算未认领）"
        return out
    rel = ledger.split("#", 1)[0].replace("\\", "/")
    vid = str((claim or {}).get("verification_id") or "").split("#")[-1]
    path = Path(str(root or "")) / rel
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        out["why"] = f"pending 台账读不出来（{type(exc).__name__}: {exc}）⇒ 没写成"
        return out
    lines = raw.splitlines(keepends=True)
    hit = -1
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if str(row.get("verification_id") or "") != vid:
            continue
        hit = i
        current = str(row.get("stmt_id") or row.get("statement_id") or "")
        if current and current != sid:
            out.update(checked=True, bound_elsewhere=current,
                       why=(f"这一签已经认给 stmt:{current} ⇒ 不覆盖"
                            "（同一份正文只认领一次）"))
            return out
        if current == sid:
            out.update(checked=True, already=True, bound=True,
                       why=f"这一签早就认给 stmt:{sid}（幂等：一个字节都没写）")
            return out
        row["statement_id"] = sid
        row["stmt_id"] = sid
        row["claimed_at"] = _now_iso()
        lines[i] = json.dumps(row, ensure_ascii=False, default=str) + "\n"
        break
    if hit < 0:
        out["why"] = (f"`{rel}` 里没有 {vid or '（没有号）'} 那一行 ⇒ 没写成"
                      "（不是「已经绑了」）")
        return out
    tmp = path.with_name(path.name + ".claim.tmp")
    try:
        tmp.write_text("".join(lines), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        out["why"] = f"回写 pending 台账没成（{type(exc).__name__}: {exc}）⇒ 没绑上"
        return out
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass  # 清临时文件失败不许带走"已经写成了"这件事（残留的 .claim.tmp 只是多一个文件）
    out.update(checked=True, bound=True,
               why=(f"这一签认给 stmt:{sid}：pending 台账行回写了 statement_id"
                    "（同一份正文只认领一次）"))
    return out



def _now_iso() -> str:
    """当前时刻（与全仓其它台账同一个写法：`S.now_iso()`）。"""
    from . import schema as _S

    return _S.now_iso()
