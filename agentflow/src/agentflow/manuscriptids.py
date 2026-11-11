# -*- coding: utf-8 -*-
"""手稿号源：每一族各有一套号，与命题号 / 计划号 / 实验号都无关。

## 业主裁定（逐字）

2026-11-10（F 那一族）：「F 的稿自己维护一套号源，不依赖命题号和计划号。」

2026-11-11（B / E 两族，本模块泛化的依据）：
```text
「b侧稿号和命题号耦合是错的，这犯了原先F稿号不独立一样的问题，
  B侧稿和F侧稿的维护方法一致。你也再盯一下E侧稿的形状」
```

改前只有 F 有自己的号段（`counters.manuscript`），B 与 E 的稿名用的是「命题号 /
实验号」：`reports/b-proof-<命题号>.md`、`reports/e-proof-<实验号>.md`、
`reports/e-num-<实验号>.md`。那是同一种耦合 —— 一条命题的第二份证明、或一份稿换了
落点，都会去动别人那个号段；而"稿"与"命题/实验"本来是两个计数面。

## 四条纪律（与 F 那一套逐条相同，判据 `tests/test_manuscript_ids_are_per_family.py`）

1. 每族一条计数器（`:data:`FAMILY_COUNTERS`）：`f-proof` → `manuscript`（F 既有的
   那个键，不改名）、`b-proof` → `bmanuscript`、`e-proof` → `emanuscript`、
   `e-num` → `enummanuscript`；
2. 占用检查：`reports/<前缀><号>.md` 已存在 ⇒ 号继续往前推，绝不覆盖别人的稿；
3. 并发安全：同一进程内串行（模块级 `RLock`）；跨进程并发不在本号源的承诺里
   （`store` 的写者锁管不到 `reports/`）；
4. 越界保护：六位用尽（`999999` 之后）⇒ 受控抛 :class:`ManuscriptIdError`，
   不静默升位宽（与 `store.alloc_id` 的 `IdExhausted` 同一条口径）。

## 为什么另起一个号源、不走 `store.alloc_id`

`store.alloc_id(kind)` 的契约是"取号 + 在建行的那张表里查占用"：它要求事务声明目标表，
否则受控抛 `StoreError`（`F-2`：跳过占用检查会让发号器发出已被占用的号，而 `upsert`
按主键静默覆盖旧行）。手稿没有表 —— 它的占用面是盘上的 `reports/<前缀><号>.md`。
所以手稿号走这里：同一个 `data/counters.json`、同一个六位形制，但占用检查的对象是
`reports/` 里的文件。

## 老盘（只读兼容）

`b-proof-<命题号>` / `e-proof-<实验号>` / `e-num-<实验号>` 这些名字的形状与新名字
逐字相同（都是 `reports/<前缀><六位号>.md`），所以读侧（`manuscriptfamily` 的五档、
`vsigns` 的签载体与签块、`depsection` 的族判定）一个字都不用改：它们只认形状，不认
"这个数字是谁发的"。新号源只是不再把命题号 / 实验号写进稿名。

名字相同不等于身份相同：新稿的号来自本模块的计数器，稿与命题 / 实验的对应关系记在
稿头 `- 命题号：stmt:<号>` / `- 实验号：exp:<号>` 那几行里（读侧按那几行找，不按名字
里的数字猜）。这就是"B 稿号与命题号解耦"的落点：名字只回答"这是第几份稿"。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from types import MappingProxyType
from typing import Any

from . import manuscriptfamily as _MFAM
from . import schema as _S

#: 族 ⇒ `data/counters.json` 里这一族的键（每族一条；F 那一格沿用既有的
#: `manuscript`，改名会让老盘上的计数器失去意义）。
#:
#: 为什么键名长这样：`manuscript` 是 F 已经发出去的那一条（2026-11-10 上线，老工作区里
#: 已经有值）；B / E 两条是 2026-11-11 新开的，用 `<族字母>manuscript` 的形态与它并列。
FAMILY_COUNTERS = MappingProxyType({
    "f-proof": "manuscript",
    "b-proof": "bmanuscript",
    "e-proof": "emanuscript",
    "e-num": "enummanuscript",
})

#: 缺省族（老调用方 `next_manuscript_id(root)` 的语义逐字不变：F 的稿）。
FAMILY_F = "f-proof"

#: `data/counters.json` 里 F 这一档的键（与 `stmt` / `plan` 并列）。
COUNTER_KEY = FAMILY_COUNTERS[FAMILY_F]

#: 手稿落点目录（工作区相对）。与 `manuscriptfamily.MANUSCRIPT_DIR` 同一个值。
MANUSCRIPT_DIR = _MFAM.MANUSCRIPT_DIR

#: 六位形制（`schema.ID_DIGITS` 的唯一来源；这里只做本模块自己的越界判断）。
ID_DIGITS = _S.ID_DIGITS
MAX_ID = 10 ** ID_DIGITS - 1

#: 计数器文件（工作区相对）。
COUNTERS_REL = "data/counters.json"

#: 同一进程内串行取号（跨进程不在承诺里，见模块 docstring）。
_LOCK = threading.RLock()


class ManuscriptIdError(RuntimeError):
    """手稿号发不出来（号段用尽 / 计数器文件不可用）。受控异常，不是"没号可用"。"""


def families() -> tuple[str, ...]:
    """有自己号段的四族（顺序固定，与 `manuscriptfamily.FAMILY_ORDER` 同一处口径）。"""
    return tuple(_MFAM.FAMILY_ORDER)


def counter_key(family: Any = FAMILY_F) -> str:
    """族 ⇒ 计数器键；未知族 ⇒ :class:`ManuscriptIdError`（不猜一条号段出来）。"""
    got = FAMILY_COUNTERS.get(str(family or "").strip())
    if not got:
        raise ManuscriptIdError(
            f"未知的手稿族 {family!r}：只有 {', '.join(FAMILY_COUNTERS)}；"
            "每一族一条计数器，别的族没有号段")
    return got


def format_id(n: int) -> str:
    """整数 ⇒ 六位手稿号（与 `schema.format_id` 同一形态）。"""
    return _S.format_id(int(n))


def is_manuscript_id(value: Any) -> bool:
    """这个字符串是不是一个合法的六位手稿号（旧四位号不再作为新稿号）。"""
    text = str(value or "").strip()
    return (len(text) == ID_DIGITS and text.isdigit()
            and 0 <= int(text) <= MAX_ID)


def canonical_rel(manuscript_id: Any, proof_no: Any = 1, *,
                  family: Any = FAMILY_F, legacy: bool = False) -> str:
    """手稿号 ⇒ 规范手稿路径：`reports/<前缀><号>.md`（新写路径不产生 `-p<N>`）。

    `family` 缺省是 F（`f-proof-`）—— 老调用方的位置参数与返回值逐字不变。
    2026-11-11（业主裁定）：一个稿号 = 一份文件 = 一份证明。新写路径不再按
    `proof_no` 拼后缀；`proof_no` 只在 `legacy=True`（老盘只读兼容：`reports/
    f-proof-<号>-p2.md` 那一族仍在盘上）时参与命名。缺省两格都等于"不带后缀"。
    号形不对 / 未知族 ⇒ 空串（不猜、不拼一个看起来像号的路径）。
    """
    mid = str(manuscript_id or "").strip()
    if not is_manuscript_id(mid):
        return ""
    no = 1
    if legacy:
        try:
            no = int(proof_no or 1)
        except (TypeError, ValueError):
            no = 0
        if no < 1:
            no = 1
    return _MFAM.relpath(str(family or FAMILY_F), mid, no, strict=False)


def manuscript_path(root: Any, manuscript_id: Any, proof_no: Any = 1, *,
                    family: Any = FAMILY_F, legacy: bool = False) -> str:
    """手稿号 ⇒ 工作区相对路径（`canonical_rel` 的别名，便于调用方读）。"""
    return canonical_rel(manuscript_id, proof_no, family=family, legacy=legacy)


def family_of_rel(rel: Any) -> str:
    """这一份稿属于哪一族（只按名字形状；`reports/` 之外也是这个名字的族）。

    读侧用它把"一份稿"翻译成"该去哪条计数器核号"；认不出 ⇒ 空串（不猜）。
    """
    reading = _MFAM.classify_name(rel)
    fam = str(reading.get("name_family") or "")
    return fam if fam in FAMILY_COUNTERS else ""


def _root_of(root: Any) -> Any:
    """`root` 可以是工作区路径，也可以是带 `.root` 的 `Store`。

    注意 `pathlib.Path.root` 是路径锚点（`"\\"` / `"/"`）—— 不能拿 `getattr(root, "root")`
    判类型，否则传路径进来会被读成盘符根，号源写到别处去。
    """
    if isinstance(root, (str, bytes, Path)):
        return root
    return getattr(root, "root", root)


def _counters_path(root: Any) -> Path:
    return Path(str(_root_of(root))) / COUNTERS_REL


def _read_doc(root: Any) -> dict:
    """读 `data/counters.json`；读不出来 ⇒ 空计数器（坏值当 0，与 `store.alloc_id` 同口径）。

    读不出来不是"没有号可用"：占用检查会兜住被占的号，而计数器落后只是多发一次
    候选号。文件坏到完全不是对象时才当空文档（不让一次 `json.JSONDecodeError` 变成
    traceback）。
    """
    path = _counters_path(root)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {"schema_version": _S.SCHEMA_VERSION, "counters": {}}
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"schema_version": _S.SCHEMA_VERSION, "counters": {}}
    if not isinstance(doc, dict):
        return {"schema_version": _S.SCHEMA_VERSION, "counters": {}}
    counters = doc.get("counters")
    if not isinstance(counters, dict):
        doc["counters"] = {}
    return doc


def _write_doc(root: Any, doc: dict) -> None:
    """把 counters 文档原子写回（临时名带 pid + 线程 id，`os.replace` 同目录原子）。"""
    path = _counters_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    payload = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False,
                         default=str) + "\n"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as exc:  # noqa: BLE001 —— 写不进去要受控报出来，不是"号发完了"
        # 临时文件删不掉不影响主文件是否落盘：它只会在同目录留一个 .tmp，
        # 清理失败不该把"这一号没发出去"的受控异常换成另一个异常。
        try:
            tmp.unlink(missing_ok=True)
        except OSError:  # noqa: BLE001 —— 见上：清理失败不改变本笔的结论
            pass
        raise ManuscriptIdError(
            f"手稿号计数器写不进去（{type(exc).__name__}: {exc}）⇒ 这一号没发出去"
        ) from exc


def _occupied(root: Any, manuscript_id: str, *, family: Any = FAMILY_F) -> bool:
    """`reports/<前缀><号>.md` 在不在（占用检查只看规范名，见模块 docstring）。"""
    rel = canonical_rel(manuscript_id, family=family)
    return bool(rel) and (Path(str(_root_of(root))) / rel).is_file()


def reserved_manuscript_id(root: Any, manuscript_id: Any, *,
                           family: Any = FAMILY_F) -> bool:
    """这个号在这一族里已经有一份稿（供调用方判"复用同一份稿"时核占用）。"""
    return _occupied(root, str(manuscript_id or "").strip(), family=family)


def next_manuscript_id(root: Any, *, family: Any = FAMILY_F) -> str:
    """发一个这一族自己的手稿号：`counters.<族键>` + 1，占用就继续往前推。

    返回六位号（如 `000003`）；发完把这一族的计数器推到 `号 + 1`。号段用尽 ⇒
    :class:`ManuscriptIdError`（受控，不静默升位宽）。各族互不干扰：B 发号只读
    / 写 `bmanuscript` 那一格，与 F 的 `manuscript`、E 的两条各管各的。
    """
    key = counter_key(family)
    with _LOCK:
        doc = _read_doc(root)
        counters = doc.setdefault("counters", {})
        raw = counters.get(key, 0)
        try:
            nxt = int(raw)
        except (TypeError, ValueError):
            nxt = 0
        if nxt < 0:
            nxt = 0
        # 占用检查：规范名已存在 ⇒ 这不是"空号"，绝不覆盖别人的稿。
        while nxt <= MAX_ID and _occupied(root, format_id(nxt), family=family):
            nxt += 1
        if nxt > MAX_ID:
            raise ManuscriptIdError(
                f"手稿号段（{ID_DIGITS} 位，族 {family}）已用尽（上限 {MAX_ID}）。"
                "请勿静默升位宽 —— 那会破坏所有历史手稿号的解析；"
                "要么手工归档 `reports/` 里的旧稿，要么由人裁定新号段。"
            )
        allocated = format_id(nxt)
        counters[key] = nxt + 1
        _write_doc(root, doc)
        return allocated


def peek_manuscript_counter(root: Any, *, family: Any = FAMILY_F) -> int:
    """只读：这一族的计数器现在指到哪（不写盘）。

    读不出来 ⇒ 0（"没查成"由调用方按占用面判）。
    """
    key = counter_key(family)
    doc = _read_doc(root)
    try:
        return int((doc.get("counters") or {}).get(key, 0))
    except (TypeError, ValueError):
        return 0
