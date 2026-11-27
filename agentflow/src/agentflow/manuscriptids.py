# -*- coding: utf-8 -*-
"""手稿号源：每一族各有一套号，与命题号 / 计划号 / 实验号都无关。

## 业主口径

「F 的稿自己维护一套号源，不依赖命题号和计划号。」B / E 两族同理：B 侧稿和 F 侧稿
的维护方法一致。

稿名若挂在命题号 / 实验号上（`reports/b-proof-<命题号>.md` 一类），改稿就会去动
别人那个号段；而"稿"与"命题/实验"本来是两个计数面。

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
from typing import Any, Mapping

from . import manuscriptfamily as _MFAM
from . import schema as _S

#: 族 ⇒ `data/counters.json` 里这一族的键（每族一条；F 那一格沿用既有的
#: `manuscript`，改名会让老盘上的计数器失去意义）。
#:
#: 为什么键名长这样：`manuscript` 是 F 已在用的那一条（老工作区里已有值）；B / E
#: 用 `<族字母>manuscript` 的形态与它并列。
FAMILY_COUNTERS = MappingProxyType({
    "f-proof": "manuscript",
    "b-proof": "bmanuscript",
    "e-proof": "emanuscript",
    "e-num": "enummanuscript",
    # 2026-11-27（MSOWN，业主「一种角色一套稿号」）：A 的入库汇报稿、C 的分析报告稿
    # 各一套号；与证明族互不共用计数器（裸号跨族会撞，族是身份的一半）。
    "a-report": "amanuscript",
    "c-analysis": "cmanuscript",
    "d-research": "dmanuscript",
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

#: 稿件占用登记（工作区相对）：`{键: {owner, role, task_id, at, ...}}`。
#:
#: 为什么要它（E，2026-11-15）：真机两个并行的 F（`F#1` / `F#2`）把稿落到同一个
#: `reports/f-proof-000001.md` 上（一个起草、一个改稿+转送）—— 两个写者共用一个
#: 文件名。号源只回答"这个号在盘上被占了没有"，回答不了"这一份稿归谁写"。
#:
#: 两种键（K17，2026-11-19）：写者登记的键是裸 `rel`；收编登记（B 读一份 F/E 稿、
#: 把它登成命题）的键是 `intake:<rel>` —— 同一份稿的"谁写"与"谁收编"是两个问题，
#: 不互相覆盖。两种 holder 都带 `owner` / `instance`，收编那一档另带稿身份
#: `sha256` / `family` / `target`。
CLAIMS_REL = "runs/manuscript-claims.json"

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
    """手稿号 ⇒ 规范手稿路径：`reports/<前缀><号>.md`（产出侧不产生 `-p<N>`）。

    `family` 缺省是 F（`f-proof-`）—— 老调用方的位置参数与返回值逐字不变。
    一个稿号 = 一份文件 = 一份证明：名字只由稿号决定。`proof_no` / `legacy` 两个形参
    保留只为旧调用点不必改签名，它们不参与命名（对齐之后没有第二种名字）。
    号形不对 / 未知族 ⇒ 空串（不猜、不拼一个看起来像号的路径）。
    """
    mid = str(manuscript_id or "").strip()
    if not is_manuscript_id(mid):
        return ""
    return _MFAM.relpath(str(family or FAMILY_F), mid, strict=False)


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


def identity_key(family: Any, manuscript_id: Any) -> str:
    """稿身份键：`<族>:<稿号>`（K6② —— 稿身份是 `(族, 稿号)`，不是裸号）。

    `f-proof:000000` 与 `b-proof:000000` 是两个不同的键；同族同号仍是同一个键
    （幂等判据用它）。族或号缺一 ⇒ 空串（不拼一个看起来像身份的键）。
    """
    fam = str(family or "").strip()
    mid = str(manuscript_id or "").strip()
    if not fam or not is_manuscript_id(mid):
        return ""
    return f"{fam}:{mid}"


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


# ---------------------------------------------------------------- 稿件归谁写（E）


def claims_path(root: Any) -> Path:
    """稿件占用登记落在哪：`<工作区>/runs/manuscript-claims.json`。"""
    return Path(str(_root_of(root))) / CLAIMS_REL


def _read_claims(root: Any) -> tuple[dict[str, dict[str, Any]], bool]:
    """读占用登记：`({rel: holder}, 查成了没有)`。

    文件不在盘上 = 查成了、没有任何占用（空表）；文件在但读不出来 / 顶层不是对象 =
    没查成（`False`）—— 三态：不许把"读不出来"折成"没人占"。
    """
    path = claims_path(root)
    if not path.is_file():
        return {}, True
    try:
        raw = path.read_text(encoding="utf-8")
        doc = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError):
        return {}, False
    if not isinstance(doc, dict):
        return {}, False
    claims = doc.get("claims")
    if not isinstance(claims, dict):
        return {}, False
    return {str(k): dict(v) for k, v in claims.items() if isinstance(v, dict)}, True


def _write_claims(root: Any, claims: dict[str, dict[str, Any]]) -> None:
    """把占用登记原子写回（临时名带 pid + 线程 id，`os.replace` 同目录原子）。"""
    path = claims_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    payload = json.dumps({"schema_version": _S.SCHEMA_VERSION, "claims": claims},
                         ensure_ascii=False, indent=2, default=str) + "\n"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:  # noqa: BLE001 —— 写不进去要受控报出来，不是"没人占"
        try:
            tmp.unlink(missing_ok=True)
        except OSError:  # noqa: BLE001 —— 清理失败不改变本笔结论
            pass
        raise ManuscriptIdError(
            f"稿件占用登记写不进去（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
        ) from exc


def claim_for_write(root: Any, rel: Any, *, owner: Any = "", role: Any = "",
                    task_id: Any = "", instance: Any = "",
                    identity: Mapping[str, Any] | None = None,
                    purpose: Any = "", sha256: Any = "", family: Any = "",
                    target: Any = "", takeover: bool = False) -> dict[str, Any]:
    """落稿前登记/核对"这一份稿归谁写"（E；落稿入口的唯一占用判据）。

    `owner` 是写者身份（F 那一侧传 `self.actor`：host 造的是 `agent-F-<实例>`，
    真机 `F#1` / `F#2` 两个实例因此分得开；同一个实例跨 task 续写自己的稿仍是"我"——
    所以续跑不会被自己上一次的占用挡住）。

    返回 `{checked, state, rel, holder, why}`，`state` 四档：

    | `state` | 含义 | 调用方 |
    |---|---|---|
    | `free` | 没人占 / 文件不在盘上，这一笔把它登记给我 | 照常写 |
    | `mine` | 原来就是我（同一写者续写同一份稿） | 照常写 |
    | `other` | 被另一个写者占着 | 受控拒（不许两个写者共用一个文件名；`takeover=True` 时见下） |
    | `unknown` | 占用判据没查成（登记读不出/写不进/没有写者身份） | 受控拒（判不了 ≠ 可以写） |

    ## `purpose` / `sha256` / `family` / `target` / `takeover`（K17，2026-11-19）

    收编（B 读一份 F/E 稿、把它登成命题）也要回答"这一笔是谁的稿"，但它与"谁写这份稿"
    是两件事：F 早已按 `rel` 登记成写者，B 若走同一个键会被自己的写者判成 `other`。
    所以 `purpose` 给登记键加一段命名空间（`intake:<rel>`），同一份稿的写者登记与收编
    登记互不覆盖；`sha256` / `family` / `target` 是这一笔收编的稿身份（哪一版、哪一族、
    落到哪一条命题），原样落在 holder 里 —— 回执凭它回答"这一笔是谁的稿"。

    `takeover=True` 只给收编那一档：同一份稿被另一个实例收编过之后，后来的那一笔
    仍要能登记（收编是事件，不是永久所有权）—— 覆盖并把 `previous`（上一笔的 holder）
    带回来；写者登记（`takeover=False`）仍然是"一个名字一个写者"的互斥。

    反真空：把本函数打成恒 `{"state": "free"}` ⇒ 同一路径的第二个写者会照写覆盖
    （判据 `test_two_fs_never_share_one_manuscript_path.py` 的 a 条必红）。
    """
    rel_txt = str(rel or "").strip().replace("\\", "/")
    purpose_txt = str(purpose or "").strip()
    key = f"{purpose_txt}:{rel_txt}" if purpose_txt and rel_txt else rel_txt
    out: dict[str, Any] = {"checked": True, "state": "free", "rel": rel_txt,
                           "holder": {}, "why": "",
                           "identity": dict(identity or {})}
    if not rel_txt:
        out.update(checked=False, state="unknown", why="没有目标稿件路径 ⇒ 判不了")
        return out
    who = str(owner or "").strip()
    if not who:
        # 没有写者身份就无法判"是不是别人"。不据此互斥（否则直调 / 夹具全被挡），
        # 但要如实说这一格没查成 —— 不许折成"没人占"。
        out.update(checked=False, state="unknown",
                   why=("没有写者身份（owner 为空）⇒ 判不了这一份稿是不是别人的，"
                        "不据此互斥"))
        return out
    with _LOCK:
        # ---- 跨进程互斥（K5，2026-11-18） --------------------------------------
        #
        # 模块级 RLock 只罩得住同一个解释器；真机是两个进程各写各的 claim 文件。
        # 占用登记是"同一路径只允许一个实例写"的判据本体，读-改-写必须在跨进程锁里
        # （与 `vreviews.record_review` 的两层锁同形）。拿不到锁 ⇒ `unknown`（判不了
        # 也是拒，不是"没人占"）。
        lock_path = claims_path(root).with_name(claims_path(root).name + ".lock")
        try:
            from filelock import FileLock, Timeout

            lock_path.parent.mkdir(parents=True, exist_ok=True)
            _gate = FileLock(str(lock_path), timeout=10.0)
            _gate.acquire()
        except Timeout:
            out.update(checked=False, state="unknown",
                       why=(f"`{CLAIMS_REL}` 的写锁等不到（另一个写者卡住了）⇒ "
                            "占用判据没查成（不是「没人占」）"))
            return out
        except OSError as exc:
            out.update(checked=False, state="unknown",
                       why=(f"`{CLAIMS_REL}` 的写锁建不出来（{type(exc).__name__}: {exc}）"
                            "⇒ 占用判据没查成（不是「没人占」）"))
            return out
        try:
            claims, ok = _read_claims(root)
            if not ok:
                out.update(checked=False, state="unknown",
                           why=(f"`{CLAIMS_REL}` 读不出来 ⇒ 占用判据没查成"
                                "（不是「没人占」）"))
                return out
            holder = dict(claims.get(key) or {})
            held = str(holder.get("owner") or "")
            if held and held != who and not takeover:
                out.update(state="other", holder=holder,
                           why=(f"`{rel_txt}` 已经由 {held} 占着"
                                f"（task={holder.get('task_id') or '未记'}，"
                                f"at={holder.get('at') or '未记'}）⇒ 不许两个写者共用同一个文件名"))
                return out
            fresh = {"owner": who, "role": str(role or ""),
                     "task_id": str(task_id or ""),
                     # 实例身份三格（K1/K2）：`instance` 是规范标签、`attributed` 是
                     # 「真的归因了吗」、`identity_conflict` 是未归因的原因（空串 = 没有
                     # 冲突）。老行没有这三格时读侧按「未记」处理（新键不改旧键）。
                     "instance": str(instance or dict(identity or {}).get("instance") or ""),
                     "attributed": bool(dict(identity or {}).get("attributed", False)),
                     "identity_conflict": str(dict(identity or {}).get("conflict") or ""),
                     #: 稿身份三格（K17）：这一笔登记的是哪一版 / 哪一族 / 落到哪条命题。
                     #: 写者登记不传它们（空串），收编那一档由 B 交进来。
                     "purpose": purpose_txt,
                     "sha256": str(sha256 or "").strip().lower(),
                     "family": str(family or "").strip(),
                     "target": str(target or "").strip(),
                     #: 这一笔覆盖了谁那一笔（`takeover` 才可能非空）。
                     "previous": holder if (held and held != who) else {},
                     "at": _now_iso()}
            claims[key] = fresh
            try:
                _write_claims(root, claims)
            except ManuscriptIdError as exc:
                out.update(checked=False, state="unknown", why=str(exc))
                return out
            state = "free" if not held else ("replaced" if held != who else "mine")
            out.update(state=state, holder=fresh, why="")
            return out
        finally:
            try:
                _gate.release()
            except Exception:  # noqa: BLE001 —— 释放失败不改变本笔已落盘的结论
                pass


#: 收编占用的命名空间（K17：B 读一份 F/E 稿、把它登成命题时登记的那一笔）。
INTAKE_PURPOSE = "intake"


def claim_intake(root: Any, rel: Any, *, owner: Any = "", role: Any = "B",
                 task_id: Any = "", instance: Any = "",
                 identity: Mapping[str, Any] | None = None,
                 sha256: Any = "", family: Any = "", target: Any = "") -> dict[str, Any]:
    """登记"这一笔收编是我做的"（K17；键 = `intake:<rel>`，不挡写者登记）。

    判据本体只有 :func:`claim_for_write` 一处；本函数只固定收编那一档的三个参数：
    命名空间、`takeover=True`（收编是事件，后来的那一笔能覆盖并带回 `previous`）、
    以及稿身份三格。回执凭 holder 里的 `owner` / `instance` / `sha256` / `family`
    回答"这一笔是谁的稿"。

    反真空：把 `claim_intake` 打桩成返回 `{}` ⇒ 收编回执里没有 `intake_claim`
    （`tests/test_k17_b_intake_registers_its_occupancy.py` 的 e 条必红）。
    """
    return claim_for_write(
        root, rel, owner=owner, role=role, task_id=task_id, instance=instance,
        identity=identity, purpose=INTAKE_PURPOSE, sha256=sha256,
        family=family, target=target, takeover=True)


def intake_claim(root: Any, rel: Any) -> dict[str, Any]:
    """读回"这一份稿最近一笔收编"（没登记过 ⇒ `{}`；读不出来也 `{}` —— 读侧不抛）。"""
    rel_txt = str(rel or "").strip().replace("\\", "/")
    if not rel_txt:
        return {}
    claims, ok = _read_claims(root)
    if not ok:
        return {}
    return dict(claims.get(f"{INTAKE_PURPOSE}:{rel_txt}") or {})


def claim_refusal(claim: Mapping[str, Any], rel: Any, *, path_taken: str,
                  unchecked: str) -> dict[str, Any] | None:
    """占用判定的受控拒读数（`None` = 放行）；两个受控码由调用方给。

    把 `claim_for_write` 的 `other` / `unknown` 两档翻成同一形状，供 F 写稿口
    的两支（新稿 / 重写）共用 —— 两支各写一遍必然漂，而漂的那一支正好会漏判。
    """
    state = str((claim or {}).get("state") or "")
    if state not in ("other", "unknown"):
        return None
    holder = dict((claim or {}).get("holder") or {})
    code = str(path_taken if state == "other" else unchecked)
    if state == "other":
        why = (f"`{rel}` 已经归另一个写者（{holder.get('owner') or '未记'}，"
               f"task={holder.get('task_id') or '未记'}）⇒ 这一份稿不落盘："
               "同一路径不许两个写者共用。要写自己的证明，用新的稿号另开一份")
    else:
        why = (f"`{rel}` 的占用判据没查成（{(claim or {}).get('why') or '没有原因'}）"
               "⇒ 这一份稿不落盘：判不了「这一份是不是别人的」就不写")
    return {"refused": code, "kind": code, "claim": dict(claim or {}), "why": why}


def _claimed_by_other(root: Any, manuscript_id: str, *, family: Any,
                      owner: Any = "") -> bool:
    """这个号对应的规范路径已被另一个写者登记（发号时跳过它）。"""
    rel = canonical_rel(manuscript_id, family=family)
    if not rel:
        return False
    claims, ok = _read_claims(root)
    if not ok:
        return False            # 登记读不出来时不据此跳号；落稿入口会受控拒
    holder = claims.get(rel) or {}
    held = str(holder.get("owner") or "")
    return bool(held) and held != str(owner or "")


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def reserved_manuscript_id(root: Any, manuscript_id: Any, *,
                           family: Any = FAMILY_F) -> bool:
    """这个号在这一族里已经有一份稿（供调用方判"复用同一份稿"时核占用）。"""
    return _occupied(root, str(manuscript_id or "").strip(), family=family)


def next_manuscript_id(root: Any, *, family: Any = FAMILY_F, owner: Any = "",
                       role: Any = "", task_id: Any = "",
                       identity: Mapping[str, Any] | None = None) -> str:
    """发一个这一族自己的手稿号：`counters.<族键>` + 1，占用就继续往前推。

    返回六位号（如 `000003`）；发完把这一族的计数器推到 `号 + 1`。号段用尽 ⇒
    :class:`ManuscriptIdError`（受控，不静默升位宽）。各族互不干扰：B 发号只读
    / 写 `bmanuscript` 那一格，与 F 的 `manuscript`、E 的两条各管各的。

    `owner` 给了 ⇒ 把发出去的号顺手登记给这个写者（与 `claim_for_write` 同一份
    登记、同一把锁）：这是"自动分号"那一半（同一路径被别的写者占着 ⇒ 跳过这个号）；
    落稿入口那一半负责"显式指定了别人的号 ⇒ 受控拒"。
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
        # 占用检查：规范名已存在（或已被别的写者登记）⇒ 这不是"空号"，绝不覆盖别人的稿。
        while nxt <= MAX_ID and (_occupied(root, format_id(nxt), family=family)
                                 or _claimed_by_other(root, format_id(nxt),
                                                      family=family, owner=owner)):
            nxt += 1
        if nxt > MAX_ID:
            raise ManuscriptIdError(
                f"手稿号段（{ID_DIGITS} 位，族 {family}）已用尽（上限 {MAX_ID}）。"
                "请勿静默升位宽 —— 那会破坏所有历史手稿号的解析；"
                f"要么手工归档 `{_MFAM.MANUSCRIPT_DIR}/` 里的旧稿，要么由人裁定新号段。"
            )
        allocated = format_id(nxt)
        counters[key] = nxt + 1
        _write_doc(root, doc)
        if str(owner or "").strip():
            claim_for_write(root, canonical_rel(allocated, family=family),
                            owner=owner, role=role, task_id=task_id,
                            identity=identity)
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


def instance_numbers(root: Any, *, owner: Any = "", family: Any = FAMILY_F) -> list[str]:
    """这个写者在某一族里登记过的号（升序）。空列表 = 它还没拿过这一族的号。

    业主口径（2026-11-27）：「每个实例记录自己拿的稿号列表」—— 清单的唯一真身是
    `claim_for_write` 那份占用登记（`next_manuscript_id` 发号时把号顺手登记给写者，
    两条路同一份登记、同一把锁）。这里只按 `holder.owner` 过滤，不另存一份清单：
    另存一份就是第二个真相源。
    """
    who = str(owner or "").strip()
    fam = str(family or FAMILY_F).strip()
    if not who:
        return []
    claims, ok = _read_claims(root)
    if not ok:
        return []
    out: list[str] = []
    for key, holder in claims.items():
        rel = str(holder.get("rel") or key.split(":", 1)[-1])
        shape = _MFAM.classify_manuscript(rel)
        if shape.get("family") != fam or shape.get("tier") != _MFAM.TIER_FAMILY:
            continue
        if str(holder.get("owner") or "").strip() != who:
            continue
        mid = str(shape.get("manuscript_id") or "")
        if mid:
            out.append(mid)
    return sorted(set(out))
