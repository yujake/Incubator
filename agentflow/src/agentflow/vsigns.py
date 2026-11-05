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
import re
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

#: 写签者那一格的两个取值。
#:
#: 2026-11-02（业主）：`written_by` 不再写笼统的 `"secretary"` —— 收方秘书必须点名，
#: 所以新签写 `"secretary:F"` / `"secretary:B"`（见 :data:`SECRETARY_OF`）。直调写入口
#: （夹具 / `record_verification(flip=True)`，没有收方秘书）仍写这个值：两者都真实发生过，
#: 把后者也写成 secretary 会让"这张签是谁发的"变成假话。
WRITTEN_BY_DIRECT = "sign_statement(direct)"
#: 历史取值（84 的两份签文件写的就是它）：只读，不再写。
#: 读侧不许因为它是旧值就把它读成"没有写签者"。
WRITTEN_BY_SECRETARY = "secretary"

#: 收方秘书的身份值（业主 2026-11-02：`by=` 必填，只认"送审那一方的秘书"）。
#:
#: 为什么是这三家：落签是收方的动作（F 的秘书落 F 的稿、E 的秘书落 E 的数值证明稿、
#: B 的秘书落 B 收录的命题），而 V 与 F / E / B 本身都不许落 —— 这正是
#: 「防止F自己给自己签」那条口径的结构落点。
#: 别的值（`secretary:V` 也算）⇒ 受控拒绝 `not_a_secretary`、零字节。
#:
#: 2026-11-03（业主逐字：「E 在数值证明拿 V 签的时候流程和 F 一模一样，若未实现请先实现」）：
#: 加 `secretary:E`。改前这里只有 F / B ⇒ E 派 V 的那一签「能颁发、没人能落」：
#: `Secretary.actor_label` 读 `secretary_id("E")` 得到空串 ⇒ `land_unregistered_sign`
#: 受控拒绝 `not_a_secretary` ⇒ E 的证明稿上永远不会有签块（V 只交信封那一侧是对的，
#: 缺的是"收方是谁"这一格）。这不是放宽：收方仍然只有"送审的那一方"，
#: 而 E 是 V 的第三个入口（`specs/e.py` 的 `edges` 含 `V`，2026-10-23 加）。
SECRETARY_OF: tuple[str, ...] = ("secretary:F", "secretary:B", "secretary:E")

#: 非收方秘书来落签时的原因码（受控拒绝；调用方按它分句，不许折成"系统故障"）。
NOT_A_SECRETARY = "not_a_secretary"

#: 「签」的三道必填闸（业主 2026-11-05；每个码都是受控拒绝，零字节）。
#:
#: 现场（`temp/rmk90-audit/REPORT-R-mk-infinite-90-20261105.md` §A-1/A-2）：
#: `out/vsigns/issued.json` 里 8 条「连续 3/3 成立」的签，4 条的 `statement_id` 是空串、
#: 4 条的 `ledger` 指向稿头自己那一行签块（`reports/<稿>#V签`），`passes` 三格全是占位。
#: 三件事合起来就是「稿头自己写已签 3/3」也能拿到一份签 —— 签不再是证据，只是一句话。
#:
#: ## 2026-11-05 晚 业主裁定（这一版的口径，取代同日上午那一条）
#:
#: > 「V 就不能假定有号，全签在稿上，B 侧录入时从稿拿签。这是已有口径」
#:
#: 所以「没有命题号」不是拒签理由：`命题号=未在册` 是合法形态（真机
#: `f-proof-000019.md` 就是这样，它是真签）。真假只由「有没有独立台账背书」判：
#:
#: | 码 | 什么被拒 | 判据 |
#: |---|---|---|
#: | `statement_id_missing` | 连对象都没有 | `statement_id` 空 且 `ledger` 也空 ⇒ 没有可签的对象；没号就先落 `verifications/pending/<正文sha>.jsonl`，不是拒签 |
#: | `ledger_not_verification` | 台账不是 V 自己那本 | 必须 `verifications/<号>.jsonl#v-…`（有号）或 `verifications/pending/<正文sha>.jsonl#u-…`（没号）；稿头自述（`reports/<稿>#V签`）不是证据 |
#: | `passes_incomplete` | 三转里有一转没有读数 | 每一转都要 `verification_id` / `at` / `proof_sha256`；三格全空的占位不算「成立」 |
STATEMENT_ID_MISSING = "statement_id_missing"
LEDGER_NOT_VERIFICATION = "ledger_not_verification"
PASSES_INCOMPLETE = "passes_incomplete"

#: 认签时「这一签没有独立台账背书」的那几个码（业主 2026-11-05 晚：真假只看背书）。
#:
#: 现场（真机 `projects/R-mk-infinite-90/reports`）：
#: `b-proof-000016.md` 的块写 `台账=reports/b-proof-000016.md#V签`、
#: `f-proof-plan-000011.md` 的块写 `台账=reports/f-proof-plan-000011.md#V签` ——
#: 两个都指向稿自己，盘上没有任何一份 V 的台账行记过那一签。改前它们照样被
#: `bits_after_sign` 认下来（探针实测 `applied=True`、`bits.reviewed=True`），
#: 于是「稿头自己写已签 3/3」在 B 这一侧也能换到第 3 位。
#:
#: 三档分开（三态纪律：没查成 / 查过了没有 / 有但签不住不许折平）：
#: - `sign_without_ledger`：`ledger` 不是两种台账锚点之一（含稿头自述、空串）；
#: - `ledger_row_missing`：锚点形状对，但那一份台账里没有那一个 `verification_id`；
#: - `ledger_sha_mismatch`：行在，但它的 `proof_sha256` 不是这一份正文的 sha；
#: - `ledger_not_signable`：行在、sha 也对，但那一行自己签不住（结论不是成立 / 有未解决 error）。
SIGN_WITHOUT_LEDGER = "sign_without_ledger"
LEDGER_ROW_MISSING = "ledger_row_missing"
LEDGER_SHA_MISMATCH = "ledger_sha_mismatch"
LEDGER_NOT_SIGNABLE = "ledger_not_signable"

#: 命题号的形态（与 `schema.is_valid_id` 同一套：当前六位、旧四位读侧兼容）。
#: 这里不 import `schema`：`vsigns` 是产物层，判据只认"号是不是号"这一件事。
_STATEMENT_ID_RE = re.compile(r"^\d{4,6}$")

#: V 台账的锚点形状：`verifications/<命题号>.jsonl#v-<号>`。
#: 这是「有号」那一档的背书 —— 稿头自述（`reports/… #V签`）不在这条射程内。
#: 「没号」那一档的背书是 :data:`_PENDING_ANCHOR_RE`（两者都算，业主 2026-11-05 晚）。
_LEDGER_ANCHOR_RE = re.compile(
    r"^verifications/(?P<sid>\d{4,6})\.jsonl#(?P<vid>v-[0-9]+)$")

#: 「没号」那一档的台账锚点：`verifications/pending/<正文 sha>.jsonl#u-<号>`。
#:
#: 业主 2026-11-05 晚：「V 就不能假定有号，全签在稿上，B 侧录入时从稿拿签」——
#: 没号的签落 pending 台账（D-34 的落点），锚点里的 sha 就是被签的那一份正文的 sha
#: （文件名按正文 sha 分文件的同一把尺，见 `verifications.pending_ledger_path`）。
#: `vid` 的 `u-` 前缀是 `verifications.PENDING_PREFIX`（u = 未登记）；读取侧一并接受
#: 历史 `v-` 写法（同一份台账两种前缀都出现过，行号才是真身）。
_PENDING_ANCHOR_RE = re.compile(
    r"^verifications/pending/(?P<sha>[0-9a-f]{64})\.jsonl#(?P<vid>(?:[a-z]+-)?\d+)$")

#: 颁发时写给收方秘书的那个信封的 `kind`（它是签文件里的一格，不是另一份文件）。
#:
#: 为什么要有它：颁发（V）与落签（收方）拆开之后，"这签该由谁落"必须有一处写得下来
#: 且读得回来 —— 写在文件外（只在返回值里）的话，落签那一步就没有可比对的收件人，
#: 谁都能来落。`to` 只认 :data:`SECRETARY_OF` 里的值。
ENVELOPE_KIND = "v-sign-issued"


def secretary_id(role: Any) -> str:
    """角色名 ⇒ 收方秘书的身份值（`"F"` ⇒ `"secretary:F"`；别的角色 ⇒ 空串）。

    只认 F / E / B：V 是颁发方、M 没有 V 签的编辑权（业主 2026-11-02），其余角色连
    "收方"都不是。空串 = 这一趟没有可落的秘书（不是"随便谁都能落"）。
    2026-11-03：E 是 V 的第三个入口（穷举证据会审） ⇒ E 的秘书也是收方之一。
    """
    text = str(role or "").strip()
    want = f"secretary:{text}"
    return want if want in SECRETARY_OF else ""

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
#:
#: 2026-11-02（业主裁定）：加第 9 格 `手稿号`，值是裸稿号（`000000` / `plan-0001` / `a`），
#: 不是文件名 —— 写法上要把"哪一种号"带进值里（`f-proof-plan-0001.md` ⇒ `plan-0001`），
#: 否则 `f-proof-plan-0001.md` 与 `f-proof-0001.md` 会在数字上撞车（都读成 `0001`）。
#: 这一格回答"这一块属于哪一份稿"，与 `正文sha`（回答"签的是哪一份正文"）是两件事：
#: 稿会被改名 / 搬走 / 复制，正文 sha 不会跟着变，所以两格都要有。
SIGN_BLOCK_KEYS: tuple[str, ...] = ("已签", "判词", "连续", "正文sha", "时间",
                                    "签名者", "台账", "命题号", "手稿号")

#: 第 9 格的三态（读侧；2026-11-02）。三态不许折成两态：
#:
#: | 值 | 什么时候 | 不许读成 |
#: |---|---|---|
#: | `resolved` | 格里的裸稿号 == 它所处那份稿的裸稿号 | —— |
#: | `unmatched` | 格里的号与这份稿对不上（块被搬过 / 格是空的 / 认不出这份稿的号 / 没给稿路径） | 不许读成"签过了" |
#: | `legacy` | 旧 8 格块（当时还没有这一格） | 绝不许读成"没签"：它是当时真的签过 |
MANUSCRIPT_ID_STATES: tuple[str, ...] = ("resolved", "unmatched", "legacy")

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


#: 多证明手稿名认不出来时的受控码（2026-11-04 业主裁定）。
MANUSCRIPT_NAME_BAD = "bad_manuscript_name"

#: 计划稿不是签的载体（业主 2026-11-05）。
#:
#: 现场（`REPORT-R-mk-infinite-90-20261105.md` §A-8）：`reports/f-proof-plan-000011.md`
#: 拿到了 3/3 的 V 签，签块第 9 格写 `plan-000011`、`identity_state=resolved` ——
#: 计划稿被当成了一份手稿。
#:
#: ## 两件事必须分开（父裁定，2026-11-05）
#: ```text
#: 计划稿不是签的载体   ⇒ 签发 / 落签 / 认签只认 `reports/(f|b|e)-proof-<数字>.md`
#: 计划稿是合法的落稿名 ⇒ `manuscriptform.name_reading` 仍按计划名拼、仍能解析
#: ```
#: 「先落计划名、拿到号再改名」是 F 的既有工作流；所以 :func:`parse_manuscript_name`
#: 一个字节都不改（`plan-<数字>` 仍是它认得的一种号），只在签的那三个入口
#: （:func:`is_sign_carrier` / :func:`manuscript_sign_reading` 的身份判定 /
#: :func:`land`）上把计划稿排除掉。
MANUSCRIPT_NAME_PLAN = "plan_is_not_a_sign_carrier"

#: 证明手稿名的显式规则（业主 2026-11-04 裁定）：
#: `<prefix>-proof-<号>[-p<N>].md` ⇒ `(裸稿号, proof_no=N)`。
#: - 号：4–6 位十进制（在册命题）或 `plan-<数字>`（F 立项那一轮，落稿名合法）；
#: - `-p<N>`：N 是 ≥1 的十进制，缺省 1（canonical）；`-p0` / `-pabc` / 号里带别的
#:   后缀一律不认（认不出就受控拒绝，不猜）。
_MANUSCRIPT_NAME_RE = re.compile(
    r"^(?P<prefix>.*?)-proof-(?P<id>\d{4,6}|plan-\d+)(?:-p(?P<no>[1-9]\d*))?$")

#: 「签的载体」这一族的名字（2026-11-05）：只认 `reports/(f|b|e)-proof-<数字>[-p<N>].md`。
#: 计划稿（`f-proof-plan-<数字>`）不在这里 —— 它是合法的落稿名，但不是签的载体。
#:
#: 目录那一格与 `depsection.MANUSCRIPT_DIR` 同值（`"reports"`）。这里不 import 它：
#: 本模块的判据只认"名字长什么样"，而 `vsigns` 是产物层（`depsection` 反过来会 import
#: 本模块的读口）；两处一旦分家，`test_noai_gate` 那条符号存在性判据也看不出来 ——
#: 所以用一个具名常量，回落的那一条由下面 `sign_carrier_reading` 的 docstring 钉住。
SIGN_CARRIER_DIR = "reports"
_SIGN_CARRIER_RE = re.compile(
    r"^(?P<prefix>f|b|e)-proof-(?P<id>\d{4,6})(?:-p(?P<no>[1-9]\d*))?$")


def sign_carrier_reading(path: Any) -> dict[str, Any]:
    """这一份稿是不是「签的载体」（2026-11-05 业主：计划稿不是）。

    判据刻意只排除计划稿（`*-proof-plan-<数字>`），不把别的名字一并拒掉：
    既有口径允许 `notes/proof.md` 这类认不出号的名字被签（第 9 格落空、B 按
    `unmatched` 处理），而「先落计划名、拿到号再改名」是 F 的落稿流程。两件事分开：

    - 计划稿：合法的落稿名，不是签的载体 ⇒ `ok=False`、码
      :data:`MANUSCRIPT_NAME_PLAN`；
    - 正式手稿名（`reports/(f|b|e)-proof-<数字>.md`）：签的载体，第 9 格能认出号；
    - 其余名字：`ok=True`（不是计划稿就不在这一条判据上拒），但第 9 格可能认不出号
      （由 :func:`manuscript_id_of` 判，空号 ⇒ 身份 `unmatched`）。

    返回 `{ok, code, reason, name}`；`ok=False` 不许折成"可以签"。
    """
    name = str(path or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith(".md"):
        name = name[:-3]
    out: dict[str, Any] = {"ok": False, "code": MANUSCRIPT_NAME_BAD,
                           "reason": "", "name": name}
    if not name:
        out["reason"] = "没有手稿名 ⇒ 不是签的载体（签要有对象，稿要有名字）"
        return out
    if _SIGN_CARRIER_RE.match(name):
        out.update(ok=True, code="")
        return out
    if re.match(r"^(?:f|b|e)-proof-plan-\d+(?:-p[1-9]\d*)?$", name) \
            or re.match(r"^.*-proof-plan-\d+$", name):
        out.update(code=MANUSCRIPT_NAME_PLAN,
                   reason=(f"`{name}` 是计划稿（`*-proof-plan-<数字>`）：它是合法的落稿名"
                           "（F 先落计划名、拿到号再改名），但不是签的载体 —— "
                           "签要盖在一条命题的证明上，计划稿写的是下一步怎么做。"
                           "要签就把它转成 `reports/{f,b,e}-proof-<命题号>.md`"))
        return out
    # 既不是正式手稿名、也不是计划稿：沿用既有口径（可以签，第 9 格按号认不认得出走）。
    out.update(ok=True, code="")
    return out


def is_sign_carrier(path: Any) -> bool:
    """`sign_carrier_reading(path)["ok"]` 的布尔读法（判据只走那一个函数）。"""
    return bool(sign_carrier_reading(path).get("ok"))


def parse_manuscript_name(path: Any) -> dict[str, Any]:
    """把手稿文件名解析成 `(裸稿号, proof_no)`（显式规则，认不出不猜）。

    返回 `{"checked", "family", "manuscript_id", "proof_no", "code", "reason", "name"}`：

    | 名字 | 结果 |
    |---|---|
    | `reports/f-proof-000000.md` | `family=True, id=000000, proof_no=1` |
    | `reports/f-proof-000000-p2.md` | `family=True, id=000000, proof_no=2` |
    | `reports/f-proof-plan-0001.md` | `family=True, id=plan-0001, proof_no=1`（落稿名合法；签的载体另判，见 :func:`sign_carrier_reading`） |
    | `notes/proof.md` | `family=False, id="", checked=True`（不是这个家族，不拒绝） |
    | `reports/f-proof-abc.md` | `checked=False, code=bad_manuscript_name`（受控拒） |

    `family=False` 与 `checked=False` 是两件事：前者是"这个文件名不在 `*-proof-<号>`
    家族里"（V 仍可签别的文件，只是第 9 格认不出号），后者是"它明明像一份证明手稿，
    号却认不出"（写块那一步必须拒，不能猜一个号）。

    2026-11-05（父裁定）：这里不改 —— 计划稿仍是合法的落稿名（F 的流程是"先落计划名、
    拿到号再改名"）。不许拿它当签的载体是另一条判据，落在 :func:`sign_carrier_reading`。
    """
    out: dict[str, Any] = {"checked": True, "family": False, "manuscript_id": "",
                           "proof_no": 0, "code": "", "reason": "", "name": ""}
    name = str(path or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith(".md"):
        name = name[:-3]
    out["name"] = name
    if not name:
        return out
    matched = _MANUSCRIPT_NAME_RE.match(name)
    if matched is None:
        if "-proof-" not in name:
            out["reason"] = ("不是 `*-proof-<号>` 家族的名字（没有可解析的稿号；"
                             "例如 `notes/proof.md` 仍可签，只是第 9 格认不出号）")
            return out
        out.update(checked=False, family=True, code=MANUSCRIPT_NAME_BAD,
                   reason=(f"手稿名 {name!r} 认不出号：要 "
                           "`<prefix>-proof-<号>[-p<证明号>].md`（号是 4–6 位十进制，"
                           "或 `plan-<数字>`；`-p<N>` 的 N 是 ≥1 的十进制）"))
        return out
    no = int(matched.group("no") or 1)
    out.update(family=True, manuscript_id=str(matched.group("id")), proof_no=no,
               reason=(f"`{name}` ⇒ 稿号 {matched.group('id')}、证明号 {no}"))
    return out


def manuscript_id_of(path: Any) -> str:
    """手稿路径 ⇒ 裸稿号（`reports/f-proof-000000.md` ⇒ `000000`；`...-plan-0001.md` ⇒ `plan-0001`）。

    2026-11-04（业主裁定，多证明命名）：`f-proof-000000-p2.md` 的裸稿号是 `000000`
    （`-p2` 是证明号，不是稿号的一部分）—— 否则 B 的签块闸会拿 `000000-p2` 去
    `statements` 里找，永远对不上。解析本体在 :func:`parse_manuscript_name`；
    认不出就回空串（不猜一个号），第 9 格宁可落 `unmatched`。
    """
    return str(parse_manuscript_name(path).get("manuscript_id") or "")


def manuscript_proof_no_of(path: Any) -> int:
    """手稿路径 ⇒ 证明号（`...-p2.md` ⇒ 2；缺省 1；认不出 ⇒ 0，不猜）。"""
    return int(parse_manuscript_name(path).get("proof_no") or 0)


def render_manuscript_sign(*, proof_sha: Any, streak: Any, need: Any,
                           verdict: str = "成立", signer: str = "V", at: str = "",
                           ledger: str = "", statement_id: str = "",
                           manuscript_id: str = "",
                           signed: bool = True) -> str:
    """渲染那一行签块（纯字符串；判据在 :func:`stamp_manuscript_sign`）。

    `signed=False` 写的是"审过了、没过"那一档：同一行、同一个落点，`已签=false` +
    真实判词。2026-11-03 起生产写口不再写这一档（甲口径：负判不是签）：`draft/178`
    的边界是「V 不写手稿里的签块」，负判的落点改成 `verifications/pending/<sha>.jsonl`
    （见 `agent_v/core.py::_review_unregistered_prose`）。这个参数只留给读侧兼容与夹具
    构造旧块（84/85/86 的现场）—— 不是给生产路径用的。

    `manuscript_id` 是第 9 格（裸稿号，业主 2026-11-02）：写侧由
    :func:`manuscript_id_of` 从稿路径现算，不接受"手抄一个号"。
    """
    sha = str(proof_sha or "").strip().lower()
    return (f"{SIGN_MARK}已签={'true' if signed else 'false'}；"
            f"判词={str(verdict or '成立')}；"
            f"连续={int(streak or 0)}/{int(need or 0)}；正文sha={sha}；"
            f"时间={str(at or '')}；签名者={str(signer or 'V')}；"
            f"台账={str(ledger or '')}；命题号={str(statement_id or '未在册')}；"
            f"手稿号={str(manuscript_id or '')}")


def stamp_manuscript_sign(text: str, *, proof_sha: Any, streak: Any, need: Any,
                          verdict: str = "成立", signer: str = "V", at: str = "",
                          ledger: str = "", statement_id: str = "",
                          manuscript_id: str = "",
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
        manuscript_id=manuscript_id, signed=signed)
    at_i = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("- 计划："):
            at_i = i + 1
            break
    else:
        at_i = min(2, len(lines))
    lines.insert(at_i, mark)
    return "\n".join(lines)


def manuscript_sign_reading(text: str, *, manuscript_path: Any = "") -> dict[str, Any]:
    """读手稿里那一行签块（纯读；没有就是 `found=False`，不是"没签"）。

    返回键：`found` / `signed` / `verdict` / `streak` / `need` / `proof_sha256` /
    `at` / `signer` / `ledger` / `statement_id` / `mark` / `problem`，外加第 9 格那一族
    （2026-11-02）：`manuscript_id`（格里的裸稿号）/ `manuscript_key`（它所处那份稿的
    裸稿号，`manuscript_path` 现算）/ `identity_state`（:data:`MANUSCRIPT_ID_STATES` 三态）。

    三态纪律：块在但读不成形（坏行 / 缺 `正文sha`）⇒ `found=True, signed=False`，
    并在 `problem` 里说缺什么 —— 不许折成"没有签"。
    `identity_state` 同理：旧 8 格块是 `legacy`（当时真的签过），不是"没有这一格所以不算"
    （那一档会把 84 的两份真签读成没签）。
    """
    out: dict[str, Any] = {"found": False, "signed": False, "verdict": "", "streak": 0,
                           "need": 0, "proof_sha256": "", "at": "", "signer": "",
                           "ledger": "", "statement_id": "", "mark": "", "problem": "",
                           "manuscript_id": "", "manuscript_key": manuscript_id_of(
                               manuscript_path), "identity_state": "unmatched",
                           "identity_why": ""}
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
        # ---- 第 9 格（2026-11-02）：三态不许折成两态 ----
        if "手稿号" not in cells:
            out["identity_state"] = "legacy"
            out["identity_why"] = ("这一块是旧 8 格写法（当时还没有「手稿号」）⇒ legacy："
                                   "它是当时真的签过，不许读成「没签」")
        else:
            out["manuscript_id"] = str(cells.get("手稿号") or "").strip()
            if not out["manuscript_id"]:
                out["identity_state"] = "unmatched"
                out["identity_why"] = "签块里的「手稿号」是空的 ⇒ 这一块认不出属于哪一份稿"
            elif not str(manuscript_path or "").strip():
                out["identity_state"] = "unmatched"
                out["identity_why"] = ("读的时候没给手稿路径 ⇒ 这一格对不上任何一份稿"
                                       "（不是「签过了」）")
            elif out["manuscript_key"] and out["manuscript_id"] == out["manuscript_key"]:
                # 2026-11-05（父裁定）：号对上还不够 —— 它必须是签的载体。
                # 计划稿（`f-proof-plan-*`）的号是 `plan-<数字>`，与它所在的稿同名，
                # 改前因此被判 `resolved`（真机 883c3097：`plan-000011` 拿到 3/3 签）。
                # 签的载体只认 `reports/(f|b|e)-proof-<数字>.md`。
                _carrier = sign_carrier_reading(manuscript_path)
                if not _carrier.get("ok"):
                    out["identity_state"] = "unmatched"
                    out["identity_why"] = (
                        f"签块的手稿号 {out['manuscript_id']} 与这一份稿相同，"
                        f"但这一份稿不是签的载体：{_carrier.get('reason')}")
                else:
                    out["identity_state"] = "resolved"
                    out["identity_why"] = (f"签块的手稿号 {out['manuscript_id']} 与这一份稿相同")
            else:
                out["identity_state"] = "unmatched"
                out["identity_why"] = (
                    f"签块写的是手稿号 {out['manuscript_id']!r}，而它所在的那一份稿是 "
                    f"{out['manuscript_key'] or '（认不出的名字）'!r} ⇒ 块被搬过 / 号写错了")
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
                           "path": "", "line": 0, "why": "", "reading": {},
                           "code": "", "body_mismatch": None,
                           "body_sha256": "", "signed_sha256": ""}
    if not isinstance(doc, Mapping):
        out["why"] = "签文件没读成 ⇒ 这一格没查成（不是「没写」）"
        return out
    got = doc.get("manuscript_write")
    if not isinstance(got, Mapping):
        out["why"] = ("这份签文件没有 `manuscript_write` 那一格（旧版只把结果留在"
                      "返回值里）⇒ 这一格没记录，不是「没写」")
        return out
    for key in ("written", "idempotent", "missing", "path", "line", "why", "reading",
                "code", "body_mismatch", "body_sha256", "signed_sha256"):
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


def _block_verdict_allows_sign(reading: Mapping[str, Any]) -> bool:
    """签块里的「判词」是不是「成立」那一档（负判不是签；业主 2026-11-03 甲）。

    ## 为什么这一格必须单独判

    `render_manuscript_sign` 的 `已签` 与 `判词` 是两个独立格子：前者是一个布尔，
    后者是 V 的结论。生产写口从 2026-11-03 起只写正判块（负判落 pending 台账），
    但盘上仍可能有自相矛盾的块（`已签=true；判词=有毛病`：手工改过、别的写者把
    两格拼错、或旧版本留下的）。`manuscript_sign_standing` 改前只读 `已签` 那一格
    ⇒ 一条负判会被读成签，而业主逐字的口径是「负判不是签」。

    ## 三态

    `read_verdict` 是结论的唯一读口：老行上的 `看不出来` 读成 `成立`（2026-11-02
    的追加裁定），`有毛病` 原样留下，空串不是成立 ⇒ 一律不许当签（fail-closed：
    缺了判词格子的块，宁可读成 rejected，也不拿 `已签=true` 冒充签）。
    """
    from . import verifications as _VR   # 惰性：与 manuscript_sign_standing 同一条纪律

    return _VR.read_verdict({"verdict": str(reading.get("verdict") or "")}) == "成立"


def _block_identity_conflicts(reading: Mapping[str, Any]) -> bool:
    """这一块签的是不是它所在那一份稿（第 9 格 `手稿号` 的读侧判据）。

    ## 为什么这一格要参与"算不算签"

    `manuscript_sign_reading` 已经把三态读出来了（`resolved` / `unmatched` /
    `legacy`），`test_sign_block_ninth_cell_is_the_manuscript_id` 也逐字写着
    `unmatched` 不许读成"签过了"。但 `manuscript_sign_standing`（F 的交付读数、
    B 的收录认签、V 的"已经签过"短接、秘书的升档依据都走它）改前不看这一格：
    同一份正文的签块从 000000 的稿搬进 000001 的稿，照样读成 signed。

    ## 三态（判不了就不判）

    只在两边的号都认得出、而且不同时判"搬过"：
    - 块没写第 9 格（旧 8 格）⇒ `legacy`，不是搬块（当时真的签过）；
    - 没给稿路径 / 稿名认不出裸稿号 ⇒ `identity_state=unmatched` 但 `manuscript_key`
      为空 ⇒ 判不了，原样往下走（旧调用点逐字不变）；
    - 块的号是空的（例如签在 `notes/…` 这种认不出号的稿上）⇒ 同样判不了 ——
      那一档由 B 的 `manuscript_sign_gate`（`manuscript_id_missing`）在收录时挡。
    """
    if str(reading.get("identity_state") or "") != "unmatched":
        return False
    mid = str(reading.get("manuscript_id") or "")
    key = str(reading.get("manuscript_key") or "")
    return bool(mid and key and mid != key)


def manuscript_sign_standing(text: str, *, proof_sha: Any = "",
                             manuscript_path: Any = "") -> dict[str, Any]:
    """签块相对"现在这一份正文"的读数（`signed` / `stale` / `rejected` / `unsigned`）。

    判据（与 `bits_after_sign` 同一把尺，不另立）：
    - 没有块 ⇒ `unsigned`（"这一份还没签"，不是"查不成"）；
    - 块在、`已签=true`、`连续>=require`、且块里的 `正文sha` == 这一份正文的 sha
      ⇒ `signed`；sha 不符 ⇒ `stale`（签完之后正文改过）；
    - 块在但 `已签=false`，或判词不是「成立」（两个格子互相矛盾时按负判读）
      ⇒ `rejected`（负判不是签，业主 2026-11-03 甲）；
    - 块与它所在的稿对不上号（第 9 格 `手稿号` 与稿的裸稿号都认得出、而不同）
      ⇒ `unsigned`（块被搬过 / 号写错了：它不给这一份稿作证）。

    `manuscript_path` 除了喂给 :func:`manuscript_sign_reading` 的第 9 格那一族，
    也参与"这一块属于哪一份稿"的判定（上面最后一条）。旧调用点不传它时
    `identity_state` 落 `unmatched` 而 `manuscript_key` 为空 ⇒ 判不了，行为逐字不变。
    """
    got = manuscript_sign_reading(text, manuscript_path=manuscript_path)
    out = {**got, "state": "unsigned", "checked": True,
           "sha_matches": None, "body_mismatch": False, "body_sha256": "",
           "why": ""}
    # ---- 2026-11-02：「这一块签的正文」与「这份稿现在的正文」是两个问题 ----
    #
    # `sha_matches` 回答"签块盖的是不是调用方问的那一份正文"（`proof_sha`）；
    # `body_mismatch` 回答"签块盖的是不是这份稿里现在这一份正文"。两者可以同时
    # 一真一假（84：块与登记的那一份相符，而盘上这份稿已经是另一版）—— 折成一个
    # 布尔就会让"签过"把改稿盖过去。
    try:
        from . import verifications as _VR

        out["body_sha256"] = _VR.proof_sha(manuscript_proof_body(text))
    except Exception:  # noqa: BLE001 —— 算不出正文 sha 就留空，不许折成"相符"
        out["body_sha256"] = ""
    if out["found"] and got.get("proof_sha256") and out["body_sha256"]:
        out["body_mismatch"] = got.get("proof_sha256") != out["body_sha256"]
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
    if not _block_verdict_allows_sign(got):
        # 两个格子互相矛盾：`已签=true`，而判词是负判（或缺失）。按负判读 ——
        # 业主 2026-11-03 甲：「负判不是签」。这一支排在 sha / 连续次数之前：
        # 负判就是负判，不因为"sha 恰好相符、次数恰好够"变成签。
        out.update(state="rejected",
                   why=(f"签块写「已签=true」，但判词是「{got.get('verdict') or '（空）'}」"
                        " ⇒ 负判不是签（两个格子自相矛盾时按判词读）；"
                        "要让这一份算签，V 得重新审成「成立」"))
        return out
    if _block_identity_conflicts(got):
        # 第 9 格写的稿号与这一份稿对不上：块被搬过 / 号写错了。它不给这一份稿作证 ——
        # 正文 sha 对得上也不行（签是"随稿走的那一份"，不是"谁抄到谁名下都算"）。
        out.update(state="unsigned",
                   why=(f"签块的手稿号是 {got.get('manuscript_id')!r}，而它所在的这份稿是 "
                        f"{got.get('manuscript_key')!r} ⇒ 对不上（块被搬过 / 号写错了）："
                        "这一块不给这份稿作证"))
        return out
    if not out["sha_matches"]:
        out.update(state="stale",
                   why=(f"手稿里的签盖的是另一版（{got.get('proof_sha256')[:12]}… ≠ "
                        f"{want[:12]}…）⇒ 签完之后正文改过，要重签"))
        return out
    if out["body_mismatch"]:
        # 2026-11-02：签块与调用方问的那一份相符，但这份稿里现在这一份正文
        # 已经不是它了（84 的形态）⇒ 这一块不许给这份稿作证。
        out.update(state="stale",
                   why=(f"这份稿的「## 证明」正文 sha 是 {out['body_sha256'][:12]}…，"
                        f"而签块盖的是 {got.get('proof_sha256')[:12]}… "
                        "⇒ 不是同一份正文（body_mismatch），要重签"))
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


def manuscript_body_matches(text: str, *, artifact_sha: Any) -> dict[str, Any]:
    """这一份稿的「## 证明」正文 == 被签的那一份吗（纯读；业主 2026-11-02）。

    返回 `{checked, matches, body_mismatch, body_sha256, signed_sha256, why}`。
    三态：被签的 sha 认不出 ⇒ `checked=False, matches=None`（没查成，不是"相符"）；
    查成了 ⇒ `matches` 真/假，且 `body_mismatch` 是它的反面（读侧只读这一格，不自己取反）。

    为什么落块前必须过这一道：`正文sha` 只说明"V 签的是哪一份正文"，不保证眼前这份稿
    还是那一份（84 就是"块盖 #p3、文件正文 #p2"）。少了这一道，改过的稿会被盖上一块
    不属于它的签，而读侧每一处都会"看起来成功了"。
    """
    from . import verifications as _VR

    out: dict[str, Any] = {"checked": False, "matches": None, "body_mismatch": False,
                           "body_sha256": "", "signed_sha256": "", "why": ""}
    signed = str(artifact_sha or "").strip().lower()
    out["signed_sha256"] = signed
    if len(signed) != 64 or any(ch not in _HEX for ch in signed):
        out["why"] = (f"被签的正文 sha 认不出（收到 {artifact_sha!r}）⇒ 这一格没查成，"
                       "不拿它当「相符」")
        return out
    out["checked"] = True
    body = manuscript_proof_body(text)
    out["body_sha256"] = _VR.proof_sha(body)
    out["matches"] = out["body_sha256"] == signed
    out["body_mismatch"] = not out["matches"]
    if out["matches"]:
        out["why"] = (f"这一份稿的「## 证明」正文与签块的正文sha 相符"
                       f"（{signed[:12]}…）")
    elif "## 证明" not in str(text or ""):
        out["why"] = (
            f"稿里没有「## 证明」那一节 ⇒ 它的正文是空的，与签块的正文sha "
            f"{signed[:12]}… 不是同一份（不拿空正文冒充「签过空集」）")
    else:
        out["why"] = (
            f"这一份稿的「## 证明」正文 sha 是 {out['body_sha256'][:12]}…，"
            f"而签块盖的是 {signed[:12]}… ⇒ 不是同一份正文（改一个字就不算同一份），"
            "不盖块")
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
    `why` / `reading`，外加 `body_mismatch` / `body_sha256` / `signed_sha256` / `code`
    （2026-11-02：落块前核「这份稿的正文 == 被签的那一份」）。`state` 只取
    :data:`MANUSCRIPT_WRITE_STATES` 里的三个词：

    - `written`：块在稿里（`idempotent=True` 表示本来就在、没重写）；
    - `failed`：有手稿落点、但没写进去（`why` 说为什么；`missing=True` 是稿不在盘上；
      `code="body_mismatch"` 是"正文不是被签的那一份"——这一档在写盘之前就退回，
      一个字节都不写）；
    - `not_attempted`：没有手稿路径（这一签本来就只写侧文件，不是"写失败"）。

    `line` 是签块在正文里的行号（1 起；没写成 ⇒ 0）—— `write_sign` 会把它和
    `path` 一起落进签文件的 `manuscript_write` 那一格（见 :func:`manuscript_write_reading`）。
    """
    out: dict[str, Any] = {"state": "not_attempted", "written": False,
                           "idempotent": False, "missing": False,
                           "path": "", "line": 0, "why": "", "reading": {},
                           "code": "", "body_mismatch": False,
                           "body_sha256": "", "signed_sha256": ""}
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
    # ---- 2026-11-02（业主：「落块前要核实这份稿的正文 == 被签的那一份」）----
    #
    # 位置在"读到了稿"之后、"写"之前：这一档必须零字节退回 —— 写一半再后悔
    # （块已经盖进改过的稿）是抹不掉的（手稿是替换式写的，没有历史版本）。
    match = manuscript_body_matches(old, artifact_sha=proof_sha)
    out.update(body_mismatch=bool(match.get("body_mismatch")),
               body_sha256=str(match.get("body_sha256") or ""),
               signed_sha256=str(match.get("signed_sha256") or ""))
    if not match.get("checked"):
        out.update(state="failed", code="body_unreadable",
                   why=f"不盖块：{match.get('why')}（一个字节都没写）")
        return out
    if not match.get("matches"):
        out.update(state="failed", code="body_mismatch",
                   why=f"不盖块：{match.get('why')}（一个字节都没写）")
        return out
    new = stamp_manuscript_sign(old, proof_sha=proof_sha, streak=streak, need=need,
                                verdict=verdict, signer=signer, at=at,
                                ledger=ledger, statement_id=statement_id,
                                manuscript_id=manuscript_id_of(rel),
                                signed=signed)
    out["reading"] = manuscript_sign_reading(new, manuscript_path=rel)
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


# ---------------------------------------------------------------- 重判之后刷签块（缺陷 A）
#
# 真机 `projects/paper-rewrite-87` 2026-11-05 的读数（这一笔的现场）：
#
# ```text
# reports/f-proof-000000.md:5
#   - V 签：已签=true；判词=成立；连续=3/3；正文sha=43a2b34…685e；时间=2026-11-05T02:50:58+08:00；
#     签名者=secretary:F；台账=verifications/000000.jsonl#v-000008；…
# 同一 sha 之后还有：v-000009（02:53:31，判词=有毛病，defect_step=6）→ v-000010（成立）→ v-000011（成立）
# ```
#
# 签本身有效（V 确实发过、收方秘书确实落过），不一致的是记录：块说"最新一签是
# v-000008"，账上最新是 v-000011。
#
# 病根两处，都在本模块：
#
# 1. :func:`land` 把签文件里的 `at` / `ledger` 原样抄进块。而 :func:`issue` 是"一稿一签"：
#    同一份正文重签时它走 `idempotent`、一个字节都不重写（那是刻意的 —— 第 need+1 次成立
#    不改签）⇒ 块上那两格永远是第一次发签那一行。重签之后它还会退回旧那一行。
# 2. 重判（同 sha 的新台账行）没有任何写者去碰块：`record_verification` 只追加台账，
#    签块那边一个调用点都没有。
#
# 修法（业主 2026-11-05 择 a）：块是给人读的「这一份现在凭什么算签过」，指旧签会让
# 人以为没重判过。于是：
#
# - 每一行同 sha 的新台账行落下之后，把块的 `台账=` / `时间=` 两格刷到那一行；
# - 那一行是「有毛病」⇒ 整块降为未签（`已签=false`、`判词=`该行判词、`连续=0/need`、
#   `台账=`/`时间=` 两格=该行）：负判之后还挂着旧签，正是这一笔要堵的形态；
# - 降为未签之后，后续的「成立」行不把它翻回来（发签门槛是同一趟连续 need 次，
#   单行成立不足以重签）：块停在那条打回上 —— 它是"现在凭什么不算签"的依据 ——
#   直到新签由 :func:`land` 整块重写；
# - :func:`land` 里那两格改成从台账现锚（:func:`ledger_anchor`），不再是抄签文件：
#   重签同一份正文时 `issue` 不动签文件，抄它就会退回旧那一行。
#
# 三态：刷块的每一档结局都写在 :data:`SIGN_REFRESH_STATES` 里，没有一档叫"没事"；
# `checked=False` 只用于"这一格没查成"（手稿读不出来 / 台账读不出来），不许折成
# "刷过了"或"没有要刷的"。

#: 签块里「跟着台账走」的那两格（业主 2026-11-05 择 a：只刷这两格）。
SIGN_BLOCK_TRACKED_KEYS: tuple[str, ...] = ("台账", "时间")

#: :func:`refresh_manuscript_sign` 的结局词表（每一次刷块都要落在其中一档上）。
SIGN_REFRESH_STATES: tuple[str, ...] = (
    #: 两格刷到了台账上更新的那一行（`成立` 那一档）
    "refreshed",
    #: 已经是最新那一行（幂等：一个字节都没写）
    "unchanged",
    #: 同 sha 的新行判的是「有毛病」⇒ 整块降为未签
    "demoted",
    #: 这一份稿里没有签块（"没有可刷的"，不是"刷过了"）
    "no_block",
    #: 块盖的是另一份正文（sha 不同）⇒ 不拿这一行去刷别人的块
    "not_this_sha",
    #: 这份稿的「## 证明」正文已经不是被签的那一份 ⇒ 块是 stale，不许给它一个新锚
    "body_changed",
    #: 块没有命题号（未在册那一档）⇒ 没有台账可锚
    "no_statement",
    #: 台账里没有盖着这个 sha 的行 ⇒ 不猜
    "no_row",
    #: 已经是「未签」那一档：单行成立不足以重签，块停在打回那一行
    "unsigned_until_resigned",
    #: 找不到这一份正文的落点（没点名、也没有签文件）
    "manuscript_missing",
    #: 稿读不出来（OSError / 非 UTF-8）—— 这一格没查成
    "unreadable",
    #: 台账读不出来 —— 这一格没查成
    "ledger_unreadable",
)


def manuscript_path_for(root: Any, *, artifact_sha: Any = "", statement_id: str = "",
                        manuscript: str = "") -> dict[str, Any]:
    """这一份正文的签块落点（三处按序找；只算路径，不建也不写）。

    次序与 :func:`_vsign_payload` 同一口径（那一条是"签该盖在哪一份稿"的唯一判据）：

    1. 调用方点名的那一份（`manuscript`，本行台账带来的载体）—— 在盘上才算；
    2. 签文件里的 `artifact_path`（颁发那一刻写下的载体）—— 在盘上才算；
    3. 按号扫盘（`depsection.manuscript_relpaths`，只在这一份正文真有签文件时才扫：
       没有签文件就不可能有块，"扫盘猜一份"在这里只会把别人的稿当成落点）。

    返回 `{checked, found, path, source, why}`。三态：`checked=False` 只在第 3 步扫盘
    抛异常时出现（"没查成"），其余两档是"找到了 / 没有"。
    """
    out: dict[str, Any] = {"checked": True, "found": False, "path": "", "source": "",
                           "why": ""}
    root_p = Path(str(root or ""))
    named = str(manuscript or "").strip().replace("\\", "/")
    if named and (root_p / named).is_file():
        out.update(found=True, path=named, source="named")
        return out
    try:
        key = _sha_key(artifact_sha)
    except VsignError:
        out["why"] = (f"被签的正文 sha 认不出（收到 {artifact_sha!r}）⇒ 找不到签块的落点"
                      "（没查成，不是「没有签块」）")
        out["checked"] = False
        return out
    got = sign_of(root, key)
    if not got.get("found"):
        out["why"] = (f"`{got.get('path')}` 不在盘上 ⇒ 这一份正文没有签、也没有签块"
                      "（不扫盘猜一份稿）")
        return out
    from_file = str(dict(got.get("sign") or {}).get("artifact_path") or "").strip()
    from_file = from_file.replace("\\", "/")
    if from_file and (root_p / from_file).is_file():
        out.update(found=True, path=from_file, source="sign_file")
        return out
    if not str(statement_id or "").strip():
        out["why"] = (f"签文件里有签，但 `artifact_path` 是 {from_file!r}（不在盘上），"
                      "而这一签没有命题号可扫 ⇒ 找不到落点")
        return out
    try:
        from . import depsection as _DS

        for rel in _DS.manuscript_relpaths(statement_ids=[str(statement_id)]):
            if (root_p / str(rel)).is_file():
                out.update(found=True, path=str(rel), source="scan",
                           why=(f"签文件里的载体 {from_file!r} 不在盘上 ⇒ 按号扫到 "
                                f"`{rel}`"))
                return out
    except Exception as exc:  # noqa: BLE001 —— 扫盘抛异常 = 这一格没查成
        out.update(checked=False,
                   why=f"按号扫盘时抛了（{type(exc).__name__}: {exc}）⇒ 这一格没查成")
        return out
    out["why"] = (f"签文件里的载体 {from_file!r} 不在盘上，按号也没扫到一份稿 "
                  "⇒ 这一格的落点找不到")
    return out


def ledger_anchor(root: Any, *, statement_id: Any, proof_no: Any = 1,
                  artifact_sha: Any, clean_only: bool = False) -> dict[str, Any]:
    """这一份正文在台账上的锚：最后一行盖着这个 sha 的台账行（纯读）。

    `clean_only=True` 时只认干净的「成立」行（`:func:`land` 用它：签落在一条成立行上，
    一条「有毛病」永远不是签的依据）；`clean_only=False` 时最后一行是谁就是谁
    （:func:`refresh_manuscript_sign` 用它：它要看得见打回才能把块降为未签）。

    返回 `{checked, found, ledger, verification_id, at, verdict, clean, defect_steps, why}`：

    - `checked=False` ⇒ 台账读不出来 / 命题号不是编号形态（"没查成"，不是"没有行"）；
    - `found=False` ⇒ 查成了，台账里没有盖着这个 sha 的行（不猜一行出来）。

    `clean` 与 `verifications.signs_bit3` 同一把尺：结论词是「成立」，且秘书没有判
    fault（`vsigns.verdict_axis` 为空）—— 两档合起来才算"这一行不是打回"。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "ledger": "",
                           "verification_id": "", "at": "", "verdict": "",
                           "clean": False, "defect_steps": [], "why": ""}
    from . import verifications as _VR

    sid = str(statement_id or "").strip()
    sha = str(artifact_sha or "").strip().lower()
    if not sid:
        out["why"] = "没有命题号（未在册那一档）⇒ 台账上没有可锚的行"
        out["checked"] = True
        return out
    if len(sha) != 64 or any(ch not in _HEX for ch in sha):
        out["why"] = f"被签的正文 sha 认不出（收到 {artifact_sha!r}）⇒ 这一格没查成"
        return out
    try:
        no = int(_VR.as_proof_no(proof_no) or 1)
    except (TypeError, ValueError):
        no = 1
    try:
        rows, problems = _VR.list_verifications(root, statement_id=sid, limit=None)
    except Exception as exc:  # noqa: BLE001 —— 台账读不出来 = 这一格没查成
        out["why"] = f"台账读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
        return out
    if problems:
        out["why"] = ("台账里有读不出来的行（" + "；".join(str(p) for p in problems[:2])
                      + "）⇒ 这一格没查成（不拿读了一半的账当判据）")
        return out
    out["checked"] = True
    out["ledger"] = f"{_VR.VERIFICATIONS_DIR}/{sid}.jsonl"
    picked: dict[str, Any] | None = None
    for row in rows:
        one = dict(row)
        if int(_VR.as_proof_no(one.get("proof_no")) or 1) != no:
            continue
        if str(one.get("proof_sha256") or "").strip().lower() != sha:
            continue
        if clean_only and (verdict_axis(one) or _VR.read_verdict(one) != "成立"):
            continue
        picked = one
    if picked is None:
        out["why"] = (f"台账里没有盖着 {sha[:12]}… 的"
                      + ("干净「成立」" if clean_only else "")
                      + "行 ⇒ 没有可锚的那一行（不猜）")
        return out
    vid = str(picked.get("verification_id") or "")
    out.update(found=True, verification_id=vid, at=str(picked.get("at") or ""),
               verdict=_VR.read_verdict(picked),
               clean=(not verdict_axis(picked)) and _VR.read_verdict(picked) == "成立",
               defect_steps=defect_steps(picked))
    out["ledger"] = f"{_VR.VERIFICATIONS_DIR}/{sid}.jsonl#{vid}"
    if out["clean"]:
        out["why"] = f"台账上最后一行盖着这个 sha 的是 {vid}（成立，{out['at']}）"
    else:
        out["why"] = (f"台账上最后一行盖着这个 sha 的是 {vid}"
                      f"（判词 {out['verdict'] or '（空）'}，{out['at']}）⇒ 这一份不是签着的")
    return out


def refresh_manuscript_sign(root: Any, *, artifact_sha: Any = "", statement_id: str = "",
                            proof_no: Any = 1, manuscript: str = "") -> dict[str, Any]:
    """重判之后把签块刷到台账最新那一行（缺陷 A 的修法 a；唯一写口之一，永不抛）。

    什么时候调：每一行台账落下之后（`verifications.record_verification` 的三个追加
    分支），以及任何"想确认块与账对得上"的地方。

    判据（缺一条就走对应的那一档，见 :data:`SIGN_REFRESH_STATES`）：

    1. 这一份正文有签块（没有 ⇒ `no_block`）；
    2. 块盖的就是这一行落的 sha（不是 ⇒ `not_this_sha`：不拿别人的签刷这一份）；
    3. 这份稿的「## 证明」正文仍是被签的那一份（不是 ⇒ `body_changed`：块本来就 stale，
       给它一个新锚等于把改过的稿盖成"刚重判过"）；
    4. 块有命题号（没有 ⇒ `no_statement`：未在册那一档没有台账）；
    5. 台账读得出来、且有一行盖着这个 sha（否则 `ledger_unreadable` / `no_row`）。

    然后按锚那一行分两档：

    - 干净「成立」⇒ `已签=true`、`判词=成立`、`连续=` 块上原值（签是那一签的，不重写），
      `台账=`/`时间=` 两格换成那一行；
    - 「有毛病」⇒ 整块降为未签：`已签=false`、`判词=`该行判词、`连续=0/need`、
      `台账=`/`时间=` 两格换成那一行。

    已经是未签的块（`unsigned_until_resigned`）不再被后续的「成立」行翻回来。

    返回键：`checked` / `state` / `path` / `line` / `artifact_sha` / `ledger` / `at` /
    `before`（刷之前那几格）/ `after`（刷之后那几格）/ `why`。
    """
    out: dict[str, Any] = {"checked": False, "state": "", "path": "", "line": 0,
                           "artifact_sha": "", "ledger": "", "at": "",
                           "before": {}, "after": {}, "why": ""}
    try:
        key = _sha_key(artifact_sha)
    except VsignError as exc:
        out.update(state="skipped", why=f"{exc} ⇒ 刷不了签块（这一格没查成）")
        return out
    out["artifact_sha"] = key
    where = manuscript_path_for(root, artifact_sha=key, statement_id=statement_id,
                                manuscript=manuscript)
    if not where.get("found"):
        out.update(checked=bool(where.get("checked")), state="manuscript_missing",
                   why=f"{where.get('why')} ⇒ 没有可刷的签块")
        return out
    rel = str(where.get("path") or "")
    out["path"] = rel
    path = Path(str(root or "")) / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        out.update(state="unreadable",
                   why=(f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）"
                        "⇒ 这一格没查成（不是「刷过了」）"))
        return out
    out["checked"] = True
    block = manuscript_sign_reading(text, manuscript_path=rel)
    if not block.get("found"):
        out.update(state="no_block",
                   why=f"`{rel}` 里没有 V 签块 ⇒ 没有可刷的（不是「刷过了」）")
        return out
    if str(block.get("proof_sha256") or "") != key:
        out.update(state="not_this_sha",
                   why=(f"`{rel}` 的签块盖的是 "
                        f"{str(block.get('proof_sha256') or '（空）')[:12]}…，"
                        f"而这一行落的是 {key[:12]}… ⇒ 不拿这一行去刷别人的块"))
        return out
    match = manuscript_body_matches(text, artifact_sha=key)
    if not match.get("matches"):
        out.update(state="body_changed", why=f"块本来就 stale：{match.get('why')}")
        return out
    sid = str(block.get("statement_id") or "")
    if not sid:
        out.update(state="no_statement",
                   why="签块没有命题号（未在册那一档）⇒ 没有台账可锚，两格保持原值")
        return out
    anchor = ledger_anchor(root, statement_id=sid, proof_no=proof_no,
                           artifact_sha=key, clean_only=False)
    out["ledger"] = str(anchor.get("ledger") or "")
    out["at"] = str(anchor.get("at") or "")
    if not anchor.get("checked"):
        out.update(state="ledger_unreadable", checked=False,
                   why=f"{anchor.get('why')} ⇒ 这一格没查成（块一个字节都没动）")
        return out
    if not anchor.get("found"):
        out.update(state="no_row", why=f"{anchor.get('why')} ⇒ 不拿一行猜的去刷块")
        return out
    before = {"signed": bool(block.get("signed")), "verdict": str(block.get("verdict") or ""),
              "streak": int(block.get("streak") or 0), "need": int(block.get("need") or 0),
              "at": str(block.get("at") or ""), "ledger": str(block.get("ledger") or ""),
              "signer": str(block.get("signer") or "")}
    out["before"] = before
    need = int(block.get("need") or 0)
    if (not block.get("signed")) or (not _block_verdict_allows_sign(block)):
        out.update(state="unsigned_until_resigned",
                   why=("这一块已经是「未签」那一档 ⇒ 后续的单行「成立」不把它翻回来"
                        "（发签门槛是同一趟连续 "
                        f"{need} 次）；要它重新算签，得由 V 重签、收方秘书重落"))
        return out
    if anchor.get("clean"):
        state = "refreshed"
        want = {"signed": True, "verdict": "成立", "streak": before["streak"],
                "need": need, "at": str(anchor.get("at") or ""),
                "ledger": str(anchor.get("ledger") or ""), "signer": before["signer"]}
    else:
        state = "demoted"
        want = {"signed": False, "verdict": str(anchor.get("verdict") or ""),
                "streak": 0, "need": need, "at": str(anchor.get("at") or ""),
                "ledger": str(anchor.get("ledger") or ""), "signer": before["signer"]}
    stamped = stamp_manuscript_sign(
        text, proof_sha=key, streak=want["streak"], need=want["need"],
        verdict=want["verdict"], signer=want["signer"], at=want["at"],
        ledger=want["ledger"], statement_id=sid,
        manuscript_id=manuscript_id_of(rel), signed=want["signed"])
    out["after"] = dict(want)
    if stamped == text:
        out.update(state="unchanged",
                   why=("块上那两格已经指着台账最新那一行（幂等：一个字节都没写）"
                        if state == "refreshed" else
                        "块已经是这一档（幂等：一个字节都没写）"))
        return out
    tmp = path.with_name(path.name + ".refresh.tmp")
    try:
        tmp.write_text(stamped, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        out.update(state=state, checked=False,
                   why=(f"刷块没写成（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
                        "（块还是刷之前那一版）"))
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass  # 清临时文件失败不许带走"这一笔没写成"这件事（与 `write_manuscript_sign` 同一处理）
        return out
    out["line"] = _sign_block_line(stamped)
    out["state"] = state
    if state == "demoted":
        out["why"] = (f"同 sha 的新行判「{want['verdict']}」（{want['ledger']}）"
                      f"⇒ `{rel}` 第 {out['line']} 行的签块降为未签（连续 0/{need}）")
    else:
        out["why"] = (f"`{rel}` 第 {out['line']} 行的签块跟上台账："
                      f"台账={want['ledger']}、时间={want['at']}")
    return out


# ---------------------------------------------------------------- 颁发（V 的动作）

def sign_object_gate(*, artifact_sha: Any, statement_id: Any, ledger: Any,
                     passes: Any, need: Any, artifact_path: Any = "") -> dict[str, Any]:
    """「这一份签有没有对象、有没有证据」的三道必填闸（纯读；一个字节都不写）。

    业主 2026-11-05 晚的裁定落在三件事上（现场见模块常量那一段）：

    1. 没有命题号不是拒签理由：`命题号=未在册` 是合法形态（真机
       `f-proof-000019.md` 就是）。`statement_id` 空 ⇒ 签照样颁发，背书落
       `verifications/pending/<正文sha>.jsonl#u-<号>`；只有「号也没有、台账也没有」
       才受控拒绝 :data:`STATEMENT_ID_MISSING`（那一档没有可签的对象）；
    2. 台账只能是 V 自己那本：有号 ⇒ `verifications/<号>.jsonl#v-<号>`；没号 ⇒
       `verifications/pending/<正文sha>.jsonl#u-<号>`，且锚点里的 sha 就是这一份正文。
       稿头自己写的「已签 3/3」（`reports/<稿>#V签`）不是证据 ⇒
       :data:`LEDGER_NOT_VERIFICATION`；
    3. 三转都要有读数：`passes` 至少 `need` 条，每条都要带
       `verification_id` / `at` / `proof_sha256`，且 sha 就是被签的正文 sha；末尾那一转
       必须正是 `ledger` 指的那一签 —— 三格全空的占位不许被数成「连续 3/3」，
       受控拒绝 :data:`PASSES_INCOMPLETE`；
    4. 载体：给了 `artifact_path` 就必须是「签的载体」（计划稿不是，见
       :func:`sign_carrier_reading`）；没号那一档还要求它是
       `reports/(f|b|e)-proof-<数字>[-pN].md` —— 没号先签的签只能落在正式手稿上。

    三态：返回 `{ok, code, reason, ledger_kind}`。`ok=False` 的每一档都是"这一签不成立"，
    调用方按 `code` 分句；这里不抛异常（拒绝是读数，不是故障）。

    为什么闸放在 :func:`issue` 里：它是写签的唯一入口（模块 docstring 那一句
    「本函数是写签的唯一入口」）。放在调用点各判一次，等于给第二条写入口留缝。
    """
    out: dict[str, Any] = {"ok": False, "code": "", "reason": "", "ledger_kind": ""}
    sid = str(statement_id or "").strip()
    text = str(ledger or "").strip()
    if sid and not _STATEMENT_ID_RE.match(sid):
        out.update(code=STATEMENT_ID_MISSING, reason=(
            f"`statement_id={sid!r}` 不是命题号形态（4–6 位十进制，与 "
            "`statements.stmt_id` 同一套）⇒ 这一签不颁发（一个字节都不写）："
            "没有可指认的对象，签就没有落点（没号那一档 `statement_id` 留空、走 pending 台账）"))
        return out
    if not text:
        if not sid:
            out.update(code=STATEMENT_ID_MISSING, reason=(
                "没有可签的对象：既没有命题号、也没有台账落点 ⇒ 这一签不颁发"
                "（一个字节都不写）。没有号不是拒签理由：没号就先让 V 把这一签落进 "
                "`verifications/pending/<正文sha>.jsonl`（三转各一行），签块照旧盖在 "
                "`reports/(f|b|e)-proof-<数字>.md` 上，B 收录时按正文 sha 从稿上拿签。"
                "这里拒的是「连 pending 台账都没有」——那一签没有任何背书。"))
            return out
        out.update(code=LEDGER_NOT_VERIFICATION, reason=(
            f"命题 {sid} 的这一签没有台账落点（`ledger` 是空的）⇒ 不颁发："
            "签必须有独立台账背书 —— 有号走 `verifications/<号>.jsonl#v-<号>`，"
            "没号走 `verifications/pending/<正文sha>.jsonl#u-<号>`"))
        return out
    pend = _PENDING_ANCHOR_RE.match(text)
    anchor = _LEDGER_ANCHOR_RE.match(text)
    if pend is None and anchor is None:
        out.update(code=LEDGER_NOT_VERIFICATION, reason=(
            f"`ledger={text!r}` 不是 V 自己那本台账（要 "
            "`verifications/<命题号>.jsonl#v-<号>` 或 "
            "`verifications/pending/<正文sha>.jsonl#u-<号>`）⇒ 这一签不颁发"
            "（一个字节都不写）。稿头上自己写的「已签 3/3」（`reports/<稿>#V签`）"
            "不是证据：它只是这份稿的一句话，拿它当台账等于自己给自己作证 —— "
            "真机 `b-proof-000016` / `f-proof-plan-000011` 上的那两块就是这种假签。"))
        return out
    sha = str(artifact_sha or "").strip().lower()
    if pend is not None:
        out["ledger_kind"] = "pending"
        if sid:
            out.update(code=LEDGER_NOT_VERIFICATION, reason=(
                f"台账 `{text}` 是「没号」那一档的落点，而这一签要签 stmt:{sid} ⇒ "
                "不颁发：已经有号的命题要把签落进 `verifications/<号>.jsonl#v-<号>`"
                "（同一份签不许两处记）"))
            return out
        # 锚点里的那个 sha 是这一份 pending 台账的键：散文那一档是正文 sha（`object_path`
        # 为空 ⇒ `record_pending_sign` 按正文 sha 分文件），E 的穷举那一档是那份报告的字节
        # sha（B 的第三方签字闸按它认签）。所以这里不比文件名与正文 sha —— 真判据是
        # 「那一行自己记的 `proof_sha256` 就是这一份正文」，由 :func:`sign_ledger_backing`
        # （有 root、读得到行）判，`issue` 在写签文件之前会调它。
        carrier = sign_carrier_reading(artifact_path) if str(artifact_path or "").strip() else {
            "ok": False, "code": MANUSCRIPT_NAME_BAD,
            "reason": "没号那一档的签必须落在正式手稿上（`reports/(f|b|e)-proof-<数字>.md`），"
                      "这一签没有给载体"}
        _name = str(artifact_path or "").strip().replace("\\", "/")
        _bare = _name.rsplit("/", 1)[-1]
        if _bare.lower().endswith(".md"):
            _bare = _bare[:-3]
        if not str(_name).startswith(f"{SIGN_CARRIER_DIR}/") \
                or _SIGN_CARRIER_RE.match(_bare) is None:
            out.update(code=str(carrier.get("code") or MANUSCRIPT_NAME_BAD), reason=(
                f"没号那一档的载体必须是 `reports/(f|b|e)-proof-<数字>.md`，收到 "
                f"{str(artifact_path or '')!r} ⇒ 这一签不颁发（一个字节都不写）："
                f"{carrier.get('reason') or '计划稿 / 别的文件都不是签的载体'}"))
            return out
    else:
        out["ledger_kind"] = "registered"
        if sid and str(anchor.group("sid")) != sid:
            out.update(code=LEDGER_NOT_VERIFICATION, reason=(
                f"台账 `{text}` 是命题 {anchor.group('sid')} 的，而这一签要签 "
                f"stmt:{sid} ⇒ 不颁发（同一份正文被别的命题复用不算签过）"))
            return out
        if str(artifact_path or "").strip():
            # 有号那一档只挡计划稿（乙③）：别的名字问题（`f-proof-abc` 那种认不出号）
            # 归 `land` 那一步判 —— 「颁发看内容、落签看稿名」这两步的分工是 2026-11-02
            # 定的（`test_issue_and_land_are_two_steps` 的 k 档钉着它）。计划稿不同：
            # 它是"看起来完全合法、签上去永远认不了"的那一档，必须挡在颁发之前。
            carrier = sign_carrier_reading(artifact_path)
            if str(carrier.get("code") or "") == MANUSCRIPT_NAME_PLAN:
                out.update(code=MANUSCRIPT_NAME_PLAN, reason=(
                    f"这一签的载体 {str(artifact_path)!r} 是计划稿 ⇒ 不颁发"
                    f"（一个字节都不写）：{carrier.get('reason') or ''}"))
                return out
    entries = [dict(p) for p in (passes or ()) if isinstance(p, Mapping)]
    want = max(1, int(need or 1))
    if len(entries) < want:
        out.update(code=PASSES_INCOMPLETE, reason=(
            f"`passes` 只有 {len(entries)} 条，而门槛是连续 {want} 次「成立」⇒ 不算 "
            f"{want}/{want}（一个字节都不写）：每一转都要有自己的读数，"
            "没有读数的「成立」不是票"))
        return out
    for i, one in enumerate(entries, 1):
        missing = [k for k in ("verification_id", "at", "proof_sha256")
                   if not str(one.get(k) or "").strip()]
        if missing:
            out.update(code=PASSES_INCOMPLETE, reason=(
                f"第 {i} 转的 `passes` 缺 {missing} ⇒ 三格全空的占位不算「成立」："
                "每一转都要点名台账行（`verification_id`）、时间、被签正文的 sha，"
                "否则「连续 3/3」只是三个空对象（这一签不颁发，一个字节都不写）"))
            return out
        if str(one.get("proof_sha256") or "").strip().lower() != sha:
            out.update(code=PASSES_INCOMPLETE, reason=(
                f"第 {i} 转的 `proof_sha256` 不是被签正文的 sha（{sha[:12]}…）⇒ "
                "这三转不是同一份正文的票，不算连续「成立」（这一签不颁发）"))
            return out
    vid = str(entries[-1].get("verification_id") or "").strip()
    if vid != str((pend or anchor).group("vid")):
        out.update(code=PASSES_INCOMPLETE, reason=(
            f"`ledger` 指向 `{(pend or anchor).group('vid')}`，而 `passes` 最后一转是 "
            f"`{vid}` ⇒ 台账与票不是同一次送审，这一签不颁发（一签只认同一趟的那几转）"))
        return out
    out.update(ok=True)
    return out


def sign_ledger_backing(root: Any, ledger: Any, *, proof_sha256: Any) -> dict[str, Any]:
    """这一签的 `台账` 那一格有没有独立台账背书（纯读；业主 2026-11-05 晚）。

    ## 为什么必须有这一格（真机两种假签）

    `projects/R-mk-infinite-90/reports` 上两块「已签 3/3」的 `台账` 都指向稿自己：

    ```text
    b-proof-000016.md    台账=reports/b-proof-000016.md#V签       ← 假签
    f-proof-plan-000011.md 台账=reports/f-proof-plan-000011.md#V签  ← 假签
    ```

    改前 `bits_after_sign` 只核「稿名 → 号」与「正文 sha」，不核「台账那一行在不在」——
    于是这两块照样换到第 3 位（探针实测 `applied=True`）。业主的口径是：真假的判据
    不在"有没有号"，而在「有没有一份独立的 V 台账记过这一签」，两种都算：

    - 有号：`verifications/<命题号>.jsonl#v-<号>`；
    - 没号：`verifications/pending/<键>.jsonl#u-<号>`（D-34 的落点；`<键>` 是这份
      pending 台账的键 —— 散文那一档是正文 sha，E 的穷举那一档是那份报告的字节 sha，
      由 `verifications.record_pending_sign` 的 `object_sha256 or proof_sha256` 定）。
      所以这里不比锚点里的 sha 与正文 sha：行上的 `proof_sha256` 才是"签的是哪一份正文"。

    ## 四档（三态不许折平）

    | 结局 | `code` |
    |---|---|
    | 那一格压根不是台账锚点（稿头自述 / 空串 / 别的路径） | :data:`SIGN_WITHOUT_LEDGER` |
    | 锚点形状对，但那一份台账 / 那一行不在盘上 | :data:`LEDGER_ROW_MISSING` |
    | 行在，但它的 `proof_sha256` 不是这一份正文的 sha | :data:`LEDGER_SHA_MISMATCH` |
    | 行在、sha 也对，但那一行自己签不住（不是「成立」/ 有未解决 error / 引用挡） | :data:`LEDGER_NOT_SIGNABLE` |

    `checked=False` 只在"台账读不出来"（读盘抛错）时给：那是"没查成"，不是"没有背书"。
    返回 `{checked, ok, code, row, path, verification_id, why}`。
    """
    from . import verifications as _VR   # 惰性：`row_signable` 的口径只有一处

    out: dict[str, Any] = {"checked": False, "ok": False, "code": "", "row": {},
                           "path": "", "verification_id": "", "why": ""}
    text = str(ledger or "").strip().replace("\\", "/")
    sha = str(proof_sha256 or "").strip().lower()
    pend = _PENDING_ANCHOR_RE.match(text)
    reg = _LEDGER_ANCHOR_RE.match(text)
    if pend is None and reg is None:
        out.update(checked=True, code=SIGN_WITHOUT_LEDGER, why=(
            f"`台账={text!r}` 不是 V 自己那本台账（要 "
            "`verifications/<命题号>.jsonl#v-<号>` 或 "
            "`verifications/pending/<正文sha>.jsonl#u-<号>`）⇒ 这一签没有独立台账背书："
            "台账指向稿自己（`reports/… #V签`）时，那一行只是这份稿自己的一句话"))
        return out
    vid = str((pend or reg).group("vid"))
    out["verification_id"] = vid
    if pend is not None:
        out["path"] = f"verifications/pending/{pend.group('sha')}.jsonl"
    else:
        out["path"] = f"verifications/{reg.group('sid')}.jsonl"
    path = Path(str(root or "")) / out["path"]
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        out.update(checked=True, code=LEDGER_ROW_MISSING, why=(
            f"`{out['path']}` 不在盘上 ⇒ 这一签没有台账背书（锚点指着 `{vid}`，"
            "但那一份台账一次审校都没落过）"))
        return out
    row: dict[str, Any] | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            one = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(one, dict) and str(one.get("verification_id") or "") == vid:
            row = dict(one)
            break
    if row is None:
        out.update(checked=True, code=LEDGER_ROW_MISSING, why=(
            f"`{out['path']}` 里没有 `{vid}` 那一行 ⇒ 这一签没有台账背书"
            "（锚点写着它，那一行却不存在）"))
        return out
    out["row"] = row
    out["checked"] = True
    if str(row.get("proof_sha256") or "").strip().lower() != sha:
        out.update(code=LEDGER_SHA_MISMATCH, why=(
            f"`{out['path']}#{vid}` 的 `proof_sha256` 不是这一份正文的 sha"
            f"（行上是 `{str(row.get('proof_sha256') or '')[:12]}…`，"
            f"这一份是 `{sha[:12]}…`）⇒ 签的不是这一版正文"))
        return out
    if not _VR.row_signable(row):
        out.update(code=LEDGER_NOT_SIGNABLE, why=(
            f"`{out['path']}#{vid}` 那一行自己签不住（结论 "
            f"{str(row.get('verdict') or '')!r}、未解决 error "
            f"{int(row.get('unresolved_errors') or 0)} 条）⇒ 有台账也不构成签"))
        return out
    out.update(ok=True, why=(f"`{out['path']}#{vid}` 是 V 的台账行"
                             f"（结论 {str(row.get('verdict') or '')!r}，"
                             f"正文 sha 相符）⇒ 这一签有独立背书"))
    return out


def issue(root: Any, *, artifact_sha: Any, streak: int, need: int,
          artifact_path: str = "", ledger: str = "", statement_id: str = "",
          proof_no: int = 1, passes: Sequence[Mapping[str, Any]] = (),
          objections: Sequence[Mapping[str, Any]] = (), at: str = "",
          by: str = "") -> dict[str, Any]:
    """颁发一份签：`out/vsigns/<artifact_sha>.json` + `issued.json` + 信封（纯写这一半）。

    ## 2026-11-02：颁发与落签拆开（业主口径）
    ```text
    V 只颁发：`out/vsigns/<sha>.json` 由颁发工具自动写（合规）；手稿块与台账位由收方秘书落。
    ```
    所以本函数只做 V 那一半：写证据文件、更新派生归档、把"这签该由谁落"写进信封
    （签文件里的一格 `envelope`，读侧 :func:`sign_envelope` 读）。手稿块与台账位一个字节
    都不碰 —— 那是 :func:`land` 的事，而且只有收方秘书（`by`）能落。

    ## `by`：收方秘书的身份值（只认 :data:`SECRETARY_OF`）
    - `by="secretary:F"` / `"secretary:B"` ⇒ 签文件写 `written_by` = 它，信封 `to` = 它；
    - `by=""` ⇒ 直调 / 夹具那一档（没有收方秘书）：`written_by=WRITTEN_BY_DIRECT`，
      信封 `to` 空 —— 这一档能颁发，但不能落块（:func:`land` 的 `by` 必填）；
    - 别的值（含 `"secretary:V"`）⇒ 受控拒绝 :data:`NOT_A_SECRETARY`，一个字节都不写
      （连 `out/vsigns/` 都不建）。

    ## 门槛也在这里再判一次（不允许绕过 `signs_bit3` 直接写签）
    `streak < need` ⇒ 「一个字节都不写」（`written=False` + 理由）。理由：本函数是
    "写签"的唯一入口，若它只看调用方说的 `written=True`，那 `sign_statement` 那一侧的
    连续闸一旦泄漏，盘上就会出现"一次成立也有一份签"——而那正是这一笔要堵的形态。

    ## 一稿一签（已存在就不许覆盖）
    同一份正文只该有一个签。已存在且逐字相同 ⇒ `idempotent`（不重写，但仍补一次归档：
    上一次归档失败的话，这一次顺手修好）；已存在而内容不同 ⇒ `conflict`，「不写、不覆盖」，
    理由串说清哪一格不同 —— 覆盖会把"先签了后来又不认"这段历史抹掉。

    返回键：`written` / `idempotent` / `conflict` / `path` / `archive_error` /
    `archive_count` / `reason` / `sign` / `envelope` / `code` / `refused_below_need`。
    """
    out: dict[str, Any] = {"written": False, "idempotent": False, "conflict": False,
                           "path": "", "archive_error": "", "archive_count": 0,
                           "reason": "", "sign": {}, "envelope": {}, "code": "",
                           #: 这一笔被"未达门槛"拒掉（与"文件写不成"分开：前者是两道守卫
                           #: 不一致时的读数，后者是整笔失败）。
                           "refused_below_need": False}
    # ---- 收方秘书这一格先验（零字节）：拒绝要发生在建目录之前 ----
    who = str(by or "").strip()
    if who and who not in SECRETARY_OF:
        out.update(code=NOT_A_SECRETARY,
                   reason=(f"`by={who!r}` 不是收方秘书 ⇒ 不颁发（一个字节都不写）："
                           f"只认 {list(SECRETARY_OF)} —— 落签是送审那一方（F / E / B）"
                           "的秘书的动作，V 与 F / E / B 本身都不许落（防止自己给自己签）"))
        return out
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
    # ---- 2026-11-05：签的对象与证据（三道必填闸，零字节）----------------------
    #
    # 位置在"门槛"之后、"建目录/写文件"之前：拒绝要发生在任何一个字节落盘之前
    # （与上面 `by` 与 sha 两道前置判据同一条纪律）。三档各自有码，调用方按码分句。
    gate = sign_object_gate(artifact_sha=key, statement_id=statement_id,
                            ledger=ledger, passes=passes, need=need,
                            artifact_path=artifact_path)
    if not gate.get("ok"):
        out.update(code=str(gate.get("code") or ""),
                   reason=str(gate.get("reason") or ""))
        return out
    # ---- 2026-11-05 晚（业主）：签必须有独立台账背书，而且那一行要真是这一份正文 ----
    #
    # 闸在 `sign_object_gate` 只判"台账的形状对不对"（它没有 root，读不了行）。
    # 背书这一半在 `sign_ledger_backing` 一处（签块 / 签文件 / 颁发三个入口共用）：
    # 行要在盘上、`proof_sha256` 要是这一份正文、那一行自己签得住。位置同样在写签
    # 之前 —— 拒绝零字节。
    backing = sign_ledger_backing(root, ledger, proof_sha256=key)
    if not backing.get("ok"):
        out.update(code=str(backing.get("code") or ""),
                   reason=(str(backing.get("why") or "") + " ⇒ 这一签不颁发"
                           "（一个字节都不写）：签没有独立台账背书，就只是一句话"))
        return out
    envelope = {"kind": ENVELOPE_KIND, "to": who, "at": str(at or ""),
                "issued_by": "V"}
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
        #: 谁落签（2026-11-02）：收方秘书的身份值；直调那一档是
        #: :data:`WRITTEN_BY_DIRECT`（历史值 `"secretary"` 只读、不再写）。
        "written_by": who or WRITTEN_BY_DIRECT,
        "envelope": envelope,
    }
    out["envelope"] = envelope
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
            out["envelope"] = dict(doc.get("envelope") or {})
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
    return out


def sign_envelope(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """读一份签文件里的信封那一格（纯读；旧签没有它 ⇒ `to=""`，不冒充"已经写了"）。

    返回 `{to, kind, at, issued_by, recorded}`：`recorded=False` = 这份签文件是 2026-11-02
    之前的写法（还没有密码封这一格），那一档的落签不受 `to` 约束（见 :func:`land`）。
    """
    out: dict[str, Any] = {"to": "", "kind": "", "at": "", "issued_by": "",
                           "recorded": False}
    if not isinstance(doc, Mapping):
        return out
    got = doc.get("envelope")
    if not isinstance(got, Mapping):
        return out
    out.update(recorded=True, to=str(got.get("to") or ""),
               kind=str(got.get("kind") or ""), at=str(got.get("at") or ""),
               issued_by=str(got.get("issued_by") or ""))
    return out


# ---------------------------------------------------------------- 落签（收方秘书的动作）

def _record_manuscript_write(root: Any, key: str, mw: Mapping[str, Any], *,
                             by: str = "") -> dict[str, Any]:
    """把手稿块那一笔的读数补进签文件（`manuscript_write`；落成时连 `written_by`）。

    为什么要补：这一格此前只活在返回值里，于是 84 的两份签文件读出来是 `null`，
    而稿上明明有块（`draft/84` ①）。读的人的下一步是照 `null` 去找，所以"没落成"
    也要落成一条可读的读数（`failed` / `not_attempted`），不许静默。
    一稿一签：已存在的那份签只在落签这一步被补一次这两格，正文与 `passes` 一个字不动。
    """
    out: dict[str, Any] = {"recorded": False, "why": ""}
    path = sign_path(root, key)
    try:
        current, problem = _read_json(path)
        if current is None:
            out["why"] = f"手稿签块读数没写进签文件（{problem}）"
            return out
        if current.get("manuscript_write") and mw.get("idempotent"):
            # 一稿一签：块本来就在、这一笔没重写 ⇒ 签文件也不许重写（哪怕读数逐字相同，
            # 重写一次就把"第 4 转不改签文件"那条判据变成了寄希望于字节恰好稳定）。
            out["recorded"] = True
            return out
        current["manuscript_write"] = dict(mw or {})
        if str(by or "").strip():
            current["written_by"] = str(by)
        _write_atomic(path, current)
    except OSError as exc:
        out["why"] = (f"手稿签块读数没写进签文件（{type(exc).__name__}: {exc}）")
        return out
    out["recorded"] = True
    return out


def land(root: Any, *, artifact_sha: Any, by: str, manuscript_path: Any = "",
         store: Any = None, statement_id: str = "", proof_no: Any = None,
         ledger_bit: bool = True) -> dict[str, Any]:
    """落签：把一份已经颁发的签盖进手稿（第 9 格 = 裸稿号）+ 落台账位。

    ## 只有收方秘书能落（`by` 必填）
    `by` 只认 :data:`SECRETARY_OF`（`secretary:F` / `secretary:E` / `secretary:B`）；
    别的一律受控拒绝 :data:`NOT_A_SECRETARY`，零字节（不盖块、不改签文件、不翻台账位）。
    为什么：落签是收方的动作 —— F 的秘书落 F 的稿、E 的秘书落 E 的数值证明稿、
    B 的秘书落 B 收录的命题。V 与 F / E / B 本身都不许落，否则「防止F自己给自己签」
    在结构上就不成立。

    ## 两道前置判据（缺一不落）
    1. 信封收件人：签文件里 `envelope.to` 非空而 `!= by` ⇒ `addressed_to_another_secretary`
       （零字节：别的秘书的签不许被这一位落）；
    2. 正文逐字：`manuscript_proof_body(稿)` 的 sha 必须等于签文件的 `artifact_sha`
       （:func:`manuscript_body_matches`）⇒ 不符即 `body_mismatch`，零字节。

    ## 落什么
    - 手稿块：:func:`write_manuscript_sign`（9 格，`手稿号` 由稿路径现算）。块上
      `台账=` / `时间=` 两格从台账现锚（:func:`ledger_anchor`，`clean_only=True`，
      只认干净的「成立」行），不再抄签文件：`issue` 是一稿一签，重签同一份正文时签文件
      不重写，抄它会让块退回旧那一签（缺陷 A，真机 87）。锚不到时逐字回到改前那一版
      （抄签文件），读数在 `anchor` / `anchor_source` 两格里；
    - 签文件：补 `manuscript_write`（三态 + `path`/`line`），`written_by` 改成 `by`
      （2026-11-02：点名是哪一位收方秘书；只在新落成时改写，旧签不回头补）；
    - 台账位：给了 `store` 才落（`bits.evidence.reviewed_by_proof` /
      `reviewed_sha_by_proof` 那一格）。V 那条路的外层事务已经落了位，
      所以那里传 `store=None` ⇒ 读数 `not_attempted` 并说明"由外层事务落"，
      不许折成"落了"。

    返回键：`checked` / `landed` / `state`（`landed` / `refused` / `no_sign`）/
    `code` / `by` / `artifact_sha` / `manuscript_id` / `body_mismatch` /
    `manuscript_write` / `ledger_bit` / `ledger_why` / `sign_recorded` / `anchor` /
    `anchor_source` / `reason`。
    """
    out: dict[str, Any] = {
        "checked": False, "landed": False, "state": "refused", "code": "",
        "by": str(by or "").strip(), "artifact_sha": str(artifact_sha or "").strip().lower(),
        "manuscript_id": "", "body_mismatch": False, "manuscript_write": {},
        "ledger_bit": "not_attempted", "ledger_why": "", "sign_recorded": False,
        #: 块上那两格（`台账=` / `时间=`）从哪来：`anchor` 是台账现锚的读数，
        #: `anchor_source` 取 `ledger`（锚到了）/ `sign_file`（退回抄签文件）。
        "anchor": {}, "anchor_source": "",
        "reason": ""}
    who = str(by or "").strip()
    if who not in SECRETARY_OF:
        out.update(code=NOT_A_SECRETARY,
                   reason=(f"`by={who!r}` 不是收方秘书 ⇒ 不落签（一个字节都不写）："
                           f"只认 {list(SECRETARY_OF)}"))
        return out
    try:
        key = _sha_key(artifact_sha)
    except VsignError as exc:
        out["reason"] = f"{exc} ⇒ 落不了签（没查成）"
        return out
    out["artifact_sha"] = key
    got = sign_of(root, key)
    out["checked"] = bool(got.get("checked"))
    if not got.get("checked"):
        out["reason"] = f"{got.get('why')} ⇒ 落不了签（没查成）"
        return out
    if not got.get("found"):
        out.update(state="no_sign",
                   reason=(f"`{got.get('path')}` 不在盘上 ⇒ 没有可落的签"
                           "（先由 V 颁发，再由收方秘书落）"))
        return out
    doc = dict(got.get("sign") or {})
    env = sign_envelope(doc)
    if env.get("to") and env.get("to") != who:
        out.update(code="addressed_to_another_secretary",
                   reason=(f"这一签的信封写给 {env.get('to')!r}，不是 {who!r} ⇒ 不落"
                           "（零字节：别的秘书的签不许被这一位落）"))
        return out
    rel_manuscript = str(manuscript_path or doc.get("artifact_path") or "").strip()
    # ---- 2026-11-04（业主裁定）：像证明手稿、号却认不出 ⇒ 受控拒，不猜 ----------
    #
    # `notes/proof.md` 这类"不在 `*-proof-<号>` 家族里"的名字仍可签（第 9 格落空、
    # B 按 unmatched 处理）；但 `f-proof-abc.md` / `f-proof-000000-p0.md` 这种"明明
    # 是证明手稿、号却认不出"的名字必须在这里拒：猜一个号会把签盖到别的命题头上。
    _parsed_name = parse_manuscript_name(rel_manuscript)
    if _parsed_name.get("family") and not _parsed_name.get("checked"):
        out.update(code=str(_parsed_name.get("code") or MANUSCRIPT_NAME_BAD),
                   reason=(f"落签没成：{_parsed_name.get('reason') or '手稿名认不出号'}"
                           " ⇒ 一个字节都不写"))
        return out
    # ---- 2026-11-05（父裁定）：计划稿不是签的载体，落签也不许盖到它上面 --------
    #
    # `parse_manuscript_name` 照旧认计划名（F 的落稿流程要用），但"签的载体"是另一条
    # 判据：只认 `reports/(f|b|e)-proof-<数字>.md`。计划稿的签块会让 B 的收录认签读到
    # 一个 `plan-<数字>` 的稿号（真机 883c3097），而那个号在 `statements` 里不存在。
    _carrier = sign_carrier_reading(rel_manuscript)
    if str(rel_manuscript or "").strip() and not _carrier.get("ok"):
        out.update(code=str(_carrier.get("code") or MANUSCRIPT_NAME_BAD),
                   reason=(f"落签没成：{_carrier.get('reason') or '这不是签的载体'}"
                           " ⇒ 一个字节都不写"))
        return out
    # ---- 缺陷 A（2026-11-05）：块上那两格从台账现锚，不再抄签文件的旧值 --------
    #
    # `issue` 是"一稿一签"：同一份正文重签时它 `idempotent`、签文件一个字都不重写 ⇒
    # 签文件里的 `at` / `ledger` 永远是第一次发签那一行。抄它，块就退回旧那一签
    # （真机 87：块停在 v-000008，而账上最新是 v-000011）。
    #
    # 锚只认干净的「成立」行（`clean_only=True`）：一条「有毛病」永远不是签的依据。
    # 锚不到（未在册 / 台账里还没有这一行 / 直调夹具）⇒ 逐字回到改前那一版（抄签文件）。
    _sid_for_anchor = str(statement_id or doc.get("statement_id") or "").strip()
    _no_for_anchor = proof_no if proof_no is not None else doc.get("proof_no")
    _anchor = ledger_anchor(root, statement_id=_sid_for_anchor,
                            proof_no=_no_for_anchor, artifact_sha=key,
                            clean_only=True) if _sid_for_anchor else {
        "checked": True, "found": False, "why": "这一签没有命题号（未在册那一档）⇒ 没有台账可锚"}
    out["anchor"] = dict(_anchor)
    at_for_block = str(_anchor.get("at") or doc.get("at") or "")
    ledger_for_block = str(_anchor.get("ledger") or doc.get("ledger") or "")
    if _anchor.get("checked") and _anchor.get("found"):
        out["anchor_source"] = "ledger"
    else:
        out["anchor_source"] = "sign_file"
    mw = write_manuscript_sign(
        root, rel_manuscript, proof_sha=doc.get("artifact_sha"),
        streak=doc.get("streak"), need=doc.get("need"),
        verdict=str(doc.get("verdict") or "成立"),
        # 2026-11-03（件一）：块是收方秘书落的，`签名者` 就写落块的那一位
        # （`secretary:<F|B>`）—— V 只颁发，不再让块冒名说"V 写的"。
        signer=who,
        at=at_for_block, ledger=ledger_for_block,
        statement_id=str(doc.get("statement_id") or ""))
    out["manuscript_write"] = mw
    out["manuscript_id"] = manuscript_id_of(rel_manuscript)
    out["body_mismatch"] = bool(mw.get("body_mismatch"))
    if mw.get("code") == "body_mismatch":
        # 安全档：正文不是被签的那一份 ⇒ 零字节（签文件也不许被这一次改写）。
        out.update(code="body_mismatch", reason=f"落签没成：{mw.get('why')}")
        return out
    # 其余没落成的那几档（没有落点 / 稿不在盘 / 读不出来）仍把读数落进签文件：
    # 它们是"这一签没落"的事实，不是安全拒绝；旧行为（读数只活在返回值里）正是
    # 84 那两份签文件读成 `null` 的病根，不在这里复发。
    recorded = _record_manuscript_write(root, key, mw, by=who if mw.get("written") else "")
    out["sign_recorded"] = bool(recorded.get("recorded"))
    if recorded.get("why"):
        out["reason"] = recorded["why"]
    if not rel_manuscript:
        out.update(code="no_manuscript_path",
                   reason=("这一签没有手稿落点（`artifact_path` 是空的）⇒ 手稿块没地方落"
                           f"（未尝试，不是失败）：{mw.get('why')}"))
        return out
    if not mw.get("written"):
        code = str(mw.get("code") or "")
        if not code:
            code = "manuscript_missing" if mw.get("missing") else "manuscript_not_written"
        out.update(code=code, reason=f"落签没成：{mw.get('why')}")
        return out
    # 签文件补两格（`manuscript_write` + 落成时的 `written_by`）。
    recorded = _record_manuscript_write(root, key, mw, by=who)
    out["sign_recorded"] = bool(recorded.get("recorded"))
    if recorded.get("why"):
        out["reason"] = recorded["why"]
    # 台账位（只在这一层有 store 时落；V 那条路由外层事务落，见 docstring）。
    if not ledger_bit:
        out["ledger_bit"] = "not_attempted"
        out["ledger_why"] = "调用方说这一笔的台账位由外层事务落（`ledger_bit=False`）"
    elif store is None:
        out["ledger_bit"] = "not_attempted"
        out["ledger_why"] = ("没有 store ⇒ 台账位不在这里落（V 那条路由外层 "
                             "`sign_statement` 的事务落）")
    else:
        sid = str(statement_id or doc.get("statement_id") or "")
        no = proof_no if proof_no is not None else doc.get("proof_no")
        got_bit = _land_ledger_bit(store, statement_id=sid, proof_no=no, sha=key,
                                   ledger=str(doc.get("ledger") or ""), by=who)
        out["ledger_bit"] = str(got_bit.get("state") or "not_attempted")
        out["ledger_why"] = str(got_bit.get("why") or "")
    out.update(state="landed", landed=True,
               reason=(f"签块落进 `{rel_manuscript}` 第 {mw.get('line')} 行"
                       f"（手稿号 {out['manuscript_id'] or '（认不出）'}）"
                       + (f"；{out['reason']}" if out["reason"] else "")))
    return out


def _land_ledger_bit(store: Any, *, statement_id: str, proof_no: Any, sha: str,
                     ledger: str, by: str) -> dict[str, Any]:
    """把这一签落到台账位（`bits.evidence.reviewed_by_proof` 那一格；纯写这一处）。

    为什么独立一格：`land` 在 V 那条路上不落位（外层事务已经落了），而在"收方秘书单独
    落一份已经颁好的签"这条路上必须自己落 —— 两种调用都要看得见"落没落、为什么没落"。
    三态：`written` / `no_statement`（册上没有那一条）/ `failed`（事务写不成）/ `not_attempted`。
    """
    from . import verifications as _VR

    out: dict[str, Any] = {"state": "not_attempted", "statement_id": str(statement_id or ""),
                           "proof_no": 0, "why": ""}
    try:
        no = int(_VR.as_proof_no(proof_no) or 0)
    except (TypeError, ValueError):
        no = 0
    out["proof_no"] = no
    sid = str(statement_id or "").strip()
    if not sid:
        out["why"] = "这一签没有命题号（未在册那一档）⇒ 没有可翻的位"
        return out
    if no < 1:
        out["why"] = f"证明号认不出（收到 {proof_no!r}）⇒ 不翻位（不猜 #p1）"
        return out
    try:
        with store.tx("statements", actor=f"verifier-{by}",
                      note=f"vsign.land:{sid}#p{no}") as tx:
            row = tx.find("statements", stmt_id=sid)
            if row is None:
                out.update(state="no_statement",
                           why=f"`statements` 里没有命题 {sid} ⇒ 没有可翻的位")
                return out
            found = dict(row)
            bits = dict(found.get("bits") or {})
            found["bits"] = _apply_review_to_bits(
                bits, verification_id="", evidence=str(ledger or ""), findings=[],
                verdict="成立", proof_no=no, sha=str(sha or ""),
                kind=str(found.get("kind") or ""))
            tx.upsert("statements", found, note=f"vsign.land:{sid}#p{no}")
    except Exception as exc:  # noqa: BLE001 —— 翻位失败要如实报（块已经落了）
        out.update(state="failed",
                   why=f"台账位没写成（{type(exc).__name__}: {exc}）⇒ 块已落、位没跟")
        return out
    out.update(state="written",
               why=(f"{sid}#p{no} 的 reviewed_by_proof 与 reviewed_sha_by_proof 已落"
                    f"（sha {str(sha or '')[:12]}…）"))
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

#: B 收录时"这一块不能认"的三档原因码（2026-11-02 业主）。
#:
#: 每一档都带一句原因 + 一句建议（建议必须点名真工具 / 真字段，收方照着就能改）：
#:
#: | 码 | 什么时候 | 建议指向 |
#: |---|---|---|
#: | `manuscript_id_missing` | 签块没有第 9 格「手稿号」（旧 8 格块 / 空格） | `vsigns.land` 会写第 9 格 |
#: | `manuscript_id_unresolved` | 格里的号解析不到在册命题 / 与它所在那份稿对不上 | `register_statement` 拿号，或让 D 的清单把地址写对 |
#: | `manuscript_not_of_this_statement` | 号解析成了别的命题，或这份稿的正文 sha 与要登记的正文不符 | 交这一条自己的稿 / 用 `vsigns.land` 把签落回它自己的稿 |
SIGN_GATE_CODES: tuple[str, ...] = ("manuscript_id_missing", "manuscript_id_unresolved",
                                    "manuscript_not_of_this_statement")


def _mark_pending_candidate(out: dict[str, Any], *, statement_id: Any,
                            code: Any, why: str = "") -> None:
    """`manuscript_id_unresolved` 遇到"正在新建命题"时留一格"可以继续按正文 sha 认领"。

    2026-11-05（D1）：空号（`statement_id=""`）这一档的 `manuscript_id_unresolved`
    不是硬拒 —— 号还没发，签块与在册册子的关系是「登记之后」才可能为真的事；这一签
    仍然可能由 `verifications/pending/<正文 sha>.jsonl` 那一行独立背书。所以判据只留
    读数（`pending_candidate=True` + 一句为什么），由 :func:`bits_after_sign` 继续走
    :func:`_claim_pending_sign`（按正文 sha，号无关）。

    非空号（已在册那一档）不设这一格：那一档的号必须在册，是硬判据。
    `why` 让调用点说清"这一格的 unresolved 是哪一种"（例如签块被搬过 / 计划稿不是载体）。
    """
    if str(statement_id or "").strip():
        return
    if str(code or "") != "manuscript_id_unresolved":
        return
    out["pending_candidate"] = True
    out["pending_candidate_why"] = why or (
        "这一笔正在新建命题（`statement_id` 为空）：第 9 格的号在不在册是登记之后才可能"
        "为真的事 ⇒ 这一道不硬拒；继续按正文 sha 去 pending 台账认那一签"
        "（签块必须真的盖着这份正文，且要有一行 V 的台账记过它）")


def manuscript_sign_gate(reading: Mapping[str, Any], *, statement_id: str = "",
                         registered: Iterable[Any] = ()) -> dict[str, Any]:
    """B 收录时对签块的两道判据（纯读；2026-11-02 业主）。

    判据一：手稿号 → 在册命题的映射（第 9 格那一族）；
    判据二：正文逐字相同（`body_mismatch`：签块盖的是不是这份稿里现在这一份正文）。
    两道都过、且块是「成立」⇒ `admitted=True`；否则 `code` 是 :data:`SIGN_GATE_CODES`
    里的一档（`code=""` 且 `admitted=False` 的那两档是"没有块"与"块判过没过"，
    它们由调用方按既有读数处置，不在这里冒充"号有问题"）。

    为什么这一层不写任何东西：它是 B 的读侧判据。B 的写路径一个字都不动
    （业主：B 的写路径不许改；这里只加只读判据与受控拒信）。
    """
    out: dict[str, Any] = {
        "checked": bool(reading.get("found")), "admitted": False, "code": "",
        "manuscript_id": str(reading.get("manuscript_id") or ""),
        "manuscript_key": str(reading.get("manuscript_key") or ""),
        "identity_state": str(reading.get("identity_state") or ""),
        "body_mismatch": bool(reading.get("body_mismatch")),
        "reason": "", "suggestion": ""}
    if not reading.get("found"):
        out["reason"] = "手稿里没有 V 签块（这一份还没签）"
        out["suggestion"] = (
            "让 F 把这份证明送 V：`summon` V 的 `verify.verify_proof` 带 "
            "`proof_manuscript`；签到位后由收方秘书 `vsigns.land(by=\"secretary:F\")` 落块回稿。")
        return out
    mid = out["manuscript_id"]
    ident = out["identity_state"]
    ids = {str(x) for x in (registered or ()) if str(x)}
    if ident == "legacy" or not mid:
        out.update(code="manuscript_id_missing",
                   reason=("签块里没有「手稿号」这一格（旧 8 格写法 / 空格）⇒ 这一块映射不到"
                           "任何一条在册命题，B 不拿它作证"),
                   suggestion=("让收方秘书重落一次：`vsigns.land(by=\"secretary:F\")` 会按稿路径"
                               "现算并写上第 9 格 `手稿号`（裸稿号），再收录。"))
        return out
    if ident == "unmatched" and out["manuscript_key"]:
        # 理由按 `manuscript_sign_reading` 那一条现成的 `identity_why` 说（2026-11-05 晚）：
        # 计划稿那一档是"号对得上、但它不是签的载体"，改前这里一律印成"手稿号对不上"——
        # 拒是拒了，拒信却在说另一件事（真机 `f-proof-plan-000011` 的读者会去查号，
        # 而号根本没错）。
        out.update(code="manuscript_id_unresolved",
                   reason=(str(reading.get("identity_why") or "").strip() or (
                       f"第 9 格写的手稿号 {mid!r} 与它所在那份稿的裸稿号 "
                       f"{out['manuscript_key'] or '（认不出）'!r} 对不上 ⇒ 这一块要么被搬过、"
                       "要么是照别人的稿抄的")),
                   suggestion=("先确认稿与号是同一份（稿名 `reports/f-proof-<裸稿号>.md`），"
                               "再用 `vsigns.land(by=\"secretary:F\")` 落块；号与稿不一致时"
                               "不许拿 `bits_after_sign` 认签。"))
        # ---- 2026-11-05（D1 的第二半）：签块与稿号对不上时不直接 return ----------
        #
        # 这一档的签块「不能」给这份稿作证（块被搬过 / 号写错了），但它盖的那一份正文
        # 仍可能由 `verifications/pending/<正文 sha>.jsonl` 独立背书（V 在命题还没在册
        # 时审的就是这一份正文）⇒ 空号这一档继续落到 pending 认领，由那一行自己判
        # "签的是不是这一版"。计划稿（`identity_why` 说它不是签的载体）不在此列：
        # `mid == manuscript_key`，那是"这份稿永远不该有签"，继续认领只会把拒信说成
        # 另一件事 —— 仍是硬拒。
        if mid != str(out["manuscript_key"] or ""):
            _mark_pending_candidate(
                out, statement_id=statement_id, code=out["code"],
                why=("签块的第 9 格手稿号与它所在那份稿对不上（块被搬过 / 号写错了）⇒ "
                     "这一块不直接作证；改按正文 sha 去 pending 台账认那一签"
                     "（那一行自己的 sha 对得上才算）"))
        return out
    if ident == "unmatched":
        # 没有稿路径可比对（`proof_manuscript` 直递 / 走 D 的清单之前的那一档）⇒ 这一格
        # 没查成，不是"对不上"：不拿它拒，但读数里留一格说清"号没核过"。
        out["identity_unverified"] = True
    if ids and mid not in ids and mid != str(statement_id or ""):
        if str(statement_id or "").strip():
            out.update(code="manuscript_id_unresolved",
                       reason=(f"第 9 格的手稿号 {mid!r} 在 `statements` 里找不到对应的在册命题 ⇒ "
                               "这条签挂不到任何一条已收录的命题上"),
                       suggestion=("先 `register_statement` 登记这一条命题拿到 `stmt_id`（或让 D 的"
                                   "携带单把那一条的 `手稿路径` 写对），再落签。"))
            return out
        # ---- 2026-11-05（D1，阻断级）：正在新建的命题不判"号必须在册" ------------
        #
        # `statement_id=""` 是「这一笔还没登记、号还没发」那一档：号在不在册是「登记
        # 之后」才可能为真的事。改前这条判据对空号也生效，于是判据量的不是"号对不对"，
        # 而是"册子里有没有别人"：空册（`ids` 为空）短路通过，非空册一律拒
        # （`manuscript_id_unresolved`）⇒ 真实工作区里"先签后登记"的正统路整条不通。
        # 所以这里只留读数，不进 `code`：签块照旧走下面那两道（正文 sha 相符 +
        # `sign_ledger_backing` 的独立台账背书）—— 空册与非空册同一把尺，与册子里
        # 有没有别人无关。已登记命题（非空号）那一支仍是硬拒，一个字都不改。
        #
        # 这一档「不设」 `pending_candidate`：门既然放行了，就该用签块自己那条路
        # （它会把 `backing` 带出来）；`pending_candidate` 只留给"门确实判
        # `manuscript_id_unresolved`、而这一笔还没号"的那一档（见
        # `_mark_pending_candidate`：签块与稿号对不上时，仍可按正文 sha 去 pending 认）。
        out["new_statement_number_unregistered"] = True
        out["new_statement_number_why"] = (
            f"第 9 格的手稿号 {mid!r} 还不在 `statements` 里 —— 这一笔正在新建命题"
            "（`statement_id` 为空），号在不在册是登记之后才可能为真的事 ⇒ 这一道不拒；"
            "改由正文 sha 与独立台账背书继续判")
    if str(statement_id or "").strip() and mid != str(statement_id):
        out.update(code="manuscript_not_of_this_statement",
                   reason=(f"这一块的手稿号是 {mid!r}，而这一笔要登记的是 stmt:"
                           f"{str(statement_id).strip()} ⇒ 签是别条命题的"),
                   suggestion=("要登记哪一条就交哪一条的稿：让 F 用 `proof_manuscript` 递这一条的"
                               "稿，或用 `vsigns.land(by=\"secretary:F\")` 把这一签落回它自己的稿。"))
        return out
    if out["body_mismatch"]:
        out.update(code="manuscript_not_of_this_statement",
                   reason=("这份稿的「## 证明」正文 sha 与签块里的 `正文sha` 不是同一份"
                           "（改一个字就不算同一份）⇒ 不许借这一块"),
                   suggestion=("让 F 把这一份正文重送 V，重拿签后用 "
                               "`vsigns.land(by=\"secretary:F\")` 落块（`正文sha` 与 `手稿号` "
                               "两格会一起更新）。"))
        return out
    out["admitted"] = str(reading.get("state") or "") == "signed"
    if not out["admitted"]:
        out["reason"] = str(reading.get("why") or "签块不是「成立」那一档")
    return out


def _registered_ids(store: Any) -> tuple[str, ...]:
    """在册命题号（只读；没有 store / 读不出来 ⇒ 空元组，判据按"没有册"那一档走）。"""
    if store is None:
        return ()
    try:
        return tuple(str(r.get("stmt_id") or "") for r in store.rows("statements")
                     if str(r.get("stmt_id") or ""))
    except Exception:  # noqa: BLE001 —— 读不到册不是"没有命题"：这一格留空，判据退到"没有册"
        return ()


def _pending_claim_from_backing(*, backing: Mapping[str, Any], ledger: Any,
                                sha: str) -> dict[str, Any] | None:
    """签块那条路认到的是 `pending` 台账行时，产出与 `_claim_pending_sign` 同形的 claim。

    D3（2026-11-05）：签块与"按正文 sha 的 pending 认领"认的是同一份证据（同一行 V 的
    台账），回写（`bind_pending_claim`）就必须两条路都交得出来 —— 否则"同一份正文只
    认领一次"的锁只在没有签块那一半生效。签块走的是有号台账（`verifications/<号>.jsonl`）
    时回 `None`：那不是一次"待认领"，不需要回写。

    返回 `{ledger, verification_id, proof_sha256, object_sha256, bound_id, bound}`；
    `bound_id` 非空 = 这一行早被某条命题认过（调用方判"是不是同一号"）。
    """
    from . import verifications as _VR

    path = str((backing or {}).get("path") or "")
    if not path.startswith(f"{_VR.VERIFICATIONS_DIR}/{_VR.PENDING_DIR_NAME}/"):
        return None
    row = dict((backing or {}).get("row") or {})
    bound = str(row.get("stmt_id") or row.get("statement_id") or "")
    return {"ledger": str(ledger or ""),
            "verification_id": str((backing or {}).get("verification_id") or ""),
            "proof_sha256": str(row.get("proof_sha256") or sha or ""),
            "object_sha256": str(row.get("object_sha256") or ""),
            "bound_id": bound, "bound": bool(bound)}


def bits_after_sign(bits: Mapping[str, Any], *, root: Any, proof_text: str,
                    statement_id: str = "", proof_no: Any = 1,
                    kind: str = "", manuscript_text: str = "",
                    manuscript_path: Any = "", store: Any = None,
                    ) -> tuple[dict[str, Any], dict[str, Any]]:
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

    ## 返回的 `claim`（签块这一支与 pending 认领这一支都交）
    `{ledger, verification_id, proof_sha256, object_sha256, bound_id, bound}`：
    `bound_id` 非空 = 这一签早被别的命题认过（`bound=True`，这一笔不认；`code`
    给 `already_claimed`）；空 = 这一笔刚认下、等登记回写。
    2026-11-05（D3）：签块这一支认到 `pending` 背书时也交同一形状的 `claim`
    （改前只有 `_claim_pending_sign` 交，签块那条路 return 时不带 —— 于是
    `register_statement` 的 `bind_pending_claim` 那一笔从来没跑过，"同一份正文只认领
    一次"的锁不落）。有号台账（`verifications/<号>.jsonl`）那一档不产生 `claim`：
    那不是"待认领"。
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
        block = manuscript_sign_standing(str(manuscript_text), proof_sha=sha,
                                         manuscript_path=manuscript_path)
        out.update(checked=bool(block.get("checked")),
                   found=bool(block.get("found")), artifact_sha=sha,
                   why=str(block.get("why") or ""), block=dict(block))
        # ---- 2026-11-02：两道判据（业主：「稿号→在册命题 映射 + 正文逐字 sha」）----
        #
        # 位置在"块说 signed"之前：块自己说 signed（sha 与连续次数都对）也不够 ——
        # 它还必须挂得到这一条在册命题上，而且盖的是这份稿里现在这一份正文。
        # 不过那两道就认签（84 的"块盖 #p3、文件正文 #p2"正是这样被认过去的）。
        gate = manuscript_sign_gate(block, statement_id=str(statement_id or ""),
                                    registered=_registered_ids(store))
        out["gate"] = dict(gate)
        # ---- 2026-11-05（D1）：`manuscript_id_unresolved` 在"新建命题"这一档不硬拒 ----
        #
        # 改前这里按 `gate.code` 一律提前 return，于是 `vsigns.py` 末尾那段"按正文 sha
        # 认领 pending"（`:func:`_claim_pending_sign``）根本走不到：非空册的第 4 步整笔
        # 被拒 `proof_without_v_sign`，而 pending 三票（u-000001/2/3）就在盘上。
        # 门那一侧已经把"空号不判在册"的理由写进 `pending_candidate`（见
        # `_mark_pending_candidate`）：这一档继续往下走，按正文 sha 认那一签；
        # 已登记命题（非空号）那一档仍是硬拒，一个字都不改。
        if gate.get("code") and not gate.get("pending_candidate"):
            out.update(applied=False, code=str(gate["code"]),
                       reason=str(gate.get("reason") or ""),
                       suggestion=str(gate.get("suggestion") or ""),
                       why=(f"{gate.get('reason')} ⇒ 不认这一块"
                            f"（{gate.get('code')}）；建议：{gate.get('suggestion')}"))
            return dict(bits), out
        if gate.get("pending_candidate"):
            # 读数（不是静默放过）：签块这一道没判成"号在册"，改由下面的 pending 认领
            # 按正文 sha 判；块自己的读数留在 `out["block"]` / `out["gate"]` 里。
            out["gate_pending_claim"] = {
                "code": str(gate.get("code") or ""),
                "why": str(gate.get("pending_candidate_why") or ""),
                "suggestion": str(gate.get("suggestion") or "")}
            out["why"] = (str(gate.get("pending_candidate_why") or "")
                          or "新建命题：号在不在册不在这一道判")
        if not gate.get("pending_candidate") and str(block.get("state") or "") == "signed":
            # ---- 2026-11-05 晚（业主）：真假只看「有没有独立台账背书」 --------------
            #
            # 判据在 `sign_ledger_backing` 一处（签块与签文件两条来源共用）：块的
            # `台账` 那一格必须是 V 的台账锚点，且那一行在盘上、正文 sha 相符、那一行
            # 自己签得住。真机 `b-proof-000016` / `f-proof-plan-000011` 的块写的是
            # `reports/… #V签`（指向稿自己）⇒ 改前照样被认下来，现在拒。
            backing = sign_ledger_backing(root, block.get("ledger"), proof_sha256=sha)
            out["backing"] = dict(backing)
            if not backing.get("ok"):
                out.update(applied=False, code=str(backing.get("code") or ""),
                           reason=str(backing.get("why") or ""),
                           why=(f"{backing.get('why')} ⇒ 不认这一块"
                                f"（{backing.get('code')}）：稿上的「已签 3/3」只是一句话，"
                                "要有 V 的台账行记过它才算签"))
                return dict(bits), out
            # ---- 2026-11-05（D3，证据级）：签块这条认领路也要交 claim --------------
            #
            # 改前这一支认到 pending 背书之后「不带 `claim`」就 return：`register_statement`
            # 只在 `v_sign.claim` 存在时调 `bind_pending_claim`（那里的注释写着同一句
            # 纪律），于是 pending 行的 `statement_id` 一直是空的 —— "同一份正文只认领
            # 一次"那把锁从来没落上。第二笔（同一正文 sha、另一条命题、另一份没有签块的稿）
            # 于是又认了同一签，两条命题都凭同一组三票拿到 proof_review（#p2 借 #p1 的光）。
            # 现在：签块这一支与 `_claim_pending_sign` 交同一形状的 claim（ledger /
            # verification_id / sha / bound_id），登记拿到号之后照常回写；
            # 已经认给别的命题 ⇒ 当场 `already_claimed`（不认、不覆盖）。
            _claim = _pending_claim_from_backing(
                backing=backing, ledger=str(block.get("ledger") or ""), sha=sha)
            if _claim is not None:
                out["claim"] = dict(_claim)
                _bound = str(_claim.get("bound_id") or "")
                if _bound and _bound != str(statement_id or "").strip():
                    out.update(applied=False, code="already_claimed",
                               reason=(f"`{block.get('ledger')}` 这一签已经认给 "
                                       f"stmt:{_bound} ⇒ 不再认领"),
                               why=(f"`{block.get('ledger')}` 这一签已经认给 stmt:{_bound} ⇒ "
                                    "不再认领（同一份正文只认领一次；改稿请重签，"
                                    "登记不产生第二份签）"))
                    return dict(bits), out
            new = _apply_review_to_bits(
                bits,
                verification_id=str(backing.get("verification_id") or ""),
                evidence=str(block.get("ledger") or ""),
                findings=[], verdict="成立", proof_no=no, sha=sha,
                kind=str(kind or ""))
            out["applied"] = True
            out["why"] = (f"手稿里的签块：连续 {block.get('streak')}/{block.get('need')}"
                          f" 成立且正文 sha 相符（签于 {block.get('at') or '（没有时间）'}），"
                          f"台账 `{block.get('ledger')}` 一行对得上 ⇒ 第 3 位按手稿里的签写")
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
    # 签文件这一条来源同样要核背书（业主 2026-11-05 晚）：手写一份 `out/vsigns/<sha>.json`
    # 把 `台账` 写成稿自己，改前也能换到第 3 位。
    backing = sign_ledger_backing(root, sign.get("ledger"), proof_sha256=sha)
    out["backing"] = dict(backing)
    if not backing.get("ok"):
        out.update(applied=False, code=str(backing.get("code") or ""),
                   reason=str(backing.get("why") or ""),
                   why=(f"{backing.get('why')} ⇒ 不认这份签文件"
                        f"（{backing.get('code')}）"))
        return dict(bits), out
    new = _apply_review_to_bits(
        bits, verification_id=str(last.get("verification_id") or ""),
        evidence=str(sign.get("ledger") or ""), findings=[],
        verdict="成立", proof_no=no, sha=sha, kind=str(kind or ""))
    out["applied"] = True
    out["why"] = (f"这一份正文有签（连续 {sign.get('streak')}/{sign.get('need')} 次成立，"
                  f"签于 {str(sign.get('at') or '')}）⇒ 第 3 位按签写")
    return new, out


def bits_with_review(bits: Mapping[str, Any], *, proof_no: Any,
                     proof_sha256: str, kind: str = "", verdict: str = "成立",
                     verification_id: str = "", evidence: str = "",
                     findings: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """把"这一份正文已经签过"写进五元位第 3 位（:func:`_apply_review_to_bits` 的公开入口）。

    ## 谁用、为什么必须有这一个入口（2026-11-03，87 的第 ② 处）
    `agent_b.register_statement` 换正文那一笔要"按现行正文重新判定后重写"
    `reviewed_by_proof` / `reviewed_sha_by_proof` 那两张表（不许清空即通过）。而这两张
    表的唯一写法是 `_apply_review_to_bits`（签文件 / pending / 手稿块三条路共用）。
    让调用方各写一份，两张表迟早分家 —— 那正是这一批要修的形态。所以这里只加一个
    公开入口，判据与落点一个字都不新写。

    ## 它不判"该不该签"
    调用方必须自己先判过（`verifications.review_standing` 的唯一结论 /
    `vsigns.bits_after_sign` 的认签）。这一格只负责把"有这一签"落成五元位的形状。
    """
    from . import verifications as _VR

    no = _VR.as_proof_no(proof_no)
    return _apply_review_to_bits(
        bits, verification_id=str(verification_id or ""), evidence=str(evidence or ""),
        findings=findings, verdict=str(verdict or "成立"), proof_no=int(no),
        sha=str(proof_sha256 or ""), kind=str(kind or ""))


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


#: pending 台账行允许的载体（业主 2026-11-04 裁定 · 乙-14；2026-11-05 晚收紧）。
#:
#: 为什么要有这一格：pending 台账是"命题还没在册时 V 审过"的落点，`bits_after_sign`
#: 在新建命题那一档按正文 sha 认领它、直接写 `bits.reviewed=True` —— 这一笔没有签文件、
#: 也没有手稿签块。改前只要 pending 里有这一份正文就能认领，于是纯内联旧行
#: （`object_path=""`）也能把第 3 位翻上去。业主要的口径：只认 pending 行的
#: `object_path` 是一份手稿（`reports/(f|b|e)-proof-<数字>.md`）或 E 的穷举读数报告
#: （`out/experiments/<实验号>/exhaustion.md`）的认领；纯内联旧行不认。
#:
#: 2026-11-05 晚：判据搬进 :func:`_pending_carrier_path` 的唯一实现（它要同时拒计划稿、
#: 要认 `-pN` 多证明名），这里只留一句话的读数面 —— 两个字面量各写一遍就会分家。
PENDING_CARRIER_RULE = (
    "pending 行可被认领的载体只有 `reports/(f|b|e)-proof-<数字>[-pN].md` "
    "与 `out/experiments/<实验号>/exhaustion.md`（计划稿与纯内联旧行都不算）")


def _pending_carrier_path(row: Mapping[str, Any]) -> str:
    """pending 行的载体路径（空串 = 这一行没有载体，不许认领）。

    三态（判不了就不认）：
    - 手稿：`reports/(f|b|e)-proof-<数字>[-pN].md`（2026-11-05 晚业主：只有这三种
      前缀 + 数字号的正式手稿是签的载体；`f-proof-plan-<数字>` 是合法落稿名，不是载体，
      真机 `f-proof-plan-000011` 上那块 3/3 就是假签）；
    - E 的穷举读数报告：`out/experiments/<实验号>/exhaustion.md`（E 的 pending 行
      按对象 sha 落的就是这一份报告，B 的第三方签字闸读它）；
    - 其余（含空串 / 纯内联旧行 / `notes/…` / 任意别的路径）⇒ 空串，不认。
    """
    path = str((row or {}).get("object_path") or "").strip().replace("\\", "/")
    if not path:
        return ""
    parts = path.split("/")
    if (len(parts) == 2 and parts[0] == SIGN_CARRIER_DIR
            and path.endswith(".md")):
        carrier = sign_carrier_reading(path)
        if carrier.get("ok") and _SIGN_CARRIER_RE.match(parts[1][:-3]):
            return path
    parts = path.split("/")
    if (len(parts) == 4 and parts[0] == "out" and parts[1] == "experiments"
            and parts[2] and parts[3] == "exhaustion.md"):
        return path
    return ""


def _claim_pending_sign(bits: Mapping[str, Any], *, root: Any, sha: str,
                        proof_no: Any, kind: str,
                        out: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """`statement_id` 为空（正在新建命题）时，按正文 sha 去 pending 台账认那一签。

    判据与 V 那条 pending 台账同一把尺（`verifications.row_signable`：结论「成立」、
    没有未解决的 error、引用核实不挡；连续次数这一档在 pending 这条路上结构上不存在，
    理由见 `verifications._gap_from_pending`）。四个结局都写进 `out["why"]`，拒绝折平。

    ## 2026-11-04（业主裁定 · 乙-14）：先看这一行有没有载体

    pending 认领是"没有签文件、没有签块也能翻第 3 位"的唯一一条正路。它的合法性来自
    「V 在命题还没在册时对一份稿出的结论」—— 那一份稿是这一签的载体。纯内联旧行
    （`object_path=""`）没有载体，不许认领（`_pending_carrier_path`）。
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
             "proof_sha256": str(got.get("proof_sha256") or ""),
             "object_sha256": str(got.get("object_sha256") or ""),
             "bound_id": "", "bound": False}
    # ---- 2026-11-05 晚（业主）：sha 必须逐字相同 --------------------------------
    #
    # `pending_sign` 按 `proof_shas` 匹配，但认领这一步还要自己再看一眼：返回行上的
    # `proof_sha256` 必须就是这一份正文的 sha（"改一个字就不算同一份"）。不相等 ⇒
    # 受控拒绝（三态：这不是"没有签"，是"有签但不是这一版"）。
    if str(row.get("proof_sha256") or "").strip().lower() != str(sha or "").strip().lower():
        out.update(applied=False, code=LEDGER_SHA_MISMATCH,
                   why=(f"{ledger} 那一行的 `proof_sha256` 不是这一份正文的 sha"
                        f"（行上是 `{str(row.get('proof_sha256') or '')[:12]}…`，"
                        f"这一份是 `{str(sha or '')[:12]}…`）⇒ 不认领："
                        "改一个字就不算同一份，签不能挪到这一版上来"))
        return dict(bits), out
    bound = str(row.get("stmt_id") or row.get("statement_id") or "")
    if bound:
        claim.update(bound_id=bound, bound=True)
        out["claim"] = claim
        out.update(applied=False, code="already_claimed")
        out["why"] = (f"{ledger} 这一签已经认给 stmt:{bound} ⇒ 不再认领"
                      "（同一份正文只认领一次；改稿请重签，登记不产生第二份签）")
        return dict(bits), out
    carrier = _pending_carrier_path(row)
    out["carrier"] = carrier
    if not carrier:
        out.update(applied=False, code=MANUSCRIPT_NAME_PLAN
                   if sign_carrier_reading(str(row.get("object_path") or "")).get("code")
                   == MANUSCRIPT_NAME_PLAN else "carrier_missing")
        out["why"] = (
            f"{ledger} 这一行没有载体（`object_path` 不是 "
            "`reports/(f|b|e)-proof-<数字>.md`，也不是 "
            "`out/experiments/<实验号>/exhaustion.md`）⇒ 不认领："
            "计划稿 / 纯内联正文的 pending 行不给第 3 位。处置：让 V 带 `proof_manuscript` "
            "重审（签块落回那一份正式稿），或让 E 交 `reports/e-proof-<实验号>.md`。")
        return dict(bits), out
    if not _VR.row_signable(row):
        out.update(applied=False, code=LEDGER_NOT_SIGNABLE)
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
    这一份 pending 台账里的每一行（一行是一转）：`statement_id` / `stmt_id` 两键
    同值（与 `record_verification` 同一个双写口径），另加 `claimed_at`（什么时候认的）。
    为什么不是只改锚点那一行：pending 台账按对象内容分文件（`<sha>.jsonl`），里面的行
    是同一份签的几转 —— 只绑最后一转，"这一份正文被谁认领了"在读侧就取决于"从哪一行
    读"，而 D3 的现场正是这样漏的（第一笔之后三行仍全空，第二笔又认了同一签）。
    整份文件一起绑，`already_claimed` 才是在"这一份正文"的粒度上判的。

    任何一行已经绑了别的号 ⇒ 一个字节都不写，返回 `bound_elsewhere`（不覆盖前一笔的认领）；
    每一行都早就绑给同一个号 ⇒ `already=True`（幂等，一个字节都不写）。

    ## 怎么写的（全仓唯一一处写 pending 台账）
    pending 台账是 append-only 的（`verifications.record_pending_sign` 追加）；
    这一格是唯一的"回写"——只重写这些行，其余行逐字节原样
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
    bound_elsewhere = ""
    targets: list[tuple[int, dict[str, Any]]] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(row, dict):
            continue
        if str(row.get("verification_id") or "") == vid:
            hit = i
        current = str(row.get("stmt_id") or row.get("statement_id") or "")
        if current and current != sid:
            bound_elsewhere = current
            break
        if current == sid:
            continue                      # 已绑给同一号：一个字不动
        targets.append((i, row))
    if bound_elsewhere:
        out.update(checked=True, bound_elsewhere=bound_elsewhere,
                   why=(f"这一签已经认给 stmt:{bound_elsewhere} ⇒ 不覆盖"
                        "（同一份正文只认领一次）"))
        return out
    if hit < 0:
        out["why"] = (f"`{rel}` 里没有 {vid or '（没有号）'} 那一行 ⇒ 没写成"
                      "（不是「已经绑了」）")
        return out
    if not targets:
        out.update(checked=True, already=True, bound=True,
                   why=f"这一签早就认给 stmt:{sid}（幂等：一个字节都没写）")
        return out
    for i, row in targets:
        row["statement_id"] = sid
        row["stmt_id"] = sid
        row["claimed_at"] = _now_iso()
        lines[i] = json.dumps(row, ensure_ascii=False, default=str) + "\n"
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
