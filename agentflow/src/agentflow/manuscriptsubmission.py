# -*- coding: utf-8 -*-
"""手稿的「产出方」与「已提交」读数。

## 这一层回答三个问题（三块共用，别各写一份）

1. 这份稿的产出方是谁：事实来源只有手稿路径的族前缀
   （`manuscripts/F/f-proof-*` ⇒ F；`manuscripts/E/e-proof-*` / `work/E/e-num-*` ⇒ E；
   `manuscripts/B/b-proof-*` ⇒ B；`reports/*` 是退役布局 ⇒ 产出方 `unknown`）
   —— :func:`producer_of`。它再拿
   `capabilities.ALLOWED_EDGES` 现算「V 的父名单」做校验（不写死一张字面量表）。
2. 这份稿提交了没有、怎么提交的：
   :func:`submission_reading` 把三处 join 起来 —— 路径族、V 的颁发表
   （`out/vsigns/<正文 sha>.json`）、`tasks.artifacts` 里的 `mss:` 记号。
3. 收录（B）写哪一枚记号：:func:`mark_ingested`。收工（E）那一半在
   `manuscriptclosing.auto_submit_for`。两个都复用 `agent_f/submission.py` 的那一套
   `mss:` 记号拼装 / 解析（本模块不新造字符串格式）。

## 稿的身份 = (族, 稿号)（2026-11-16）

四族各有自己的号段、都从 `000000` 起 ⇒ 同一号跨族是常态。`mss:` 记号写
`mss:<族>-<号>`；读侧按 (族, 稿号) 取，老记号 `mss:<号>` 的族由载体路径 / 调用点
上下文唯一确定，跨族同号 ⇒ 不猜（:func:`agent_f.submission.resolve_submission` 的三态，
读数逐字点名「跨族同号」）。为什么必须：改前 `e-proof-000000` 与 `e-num-000000`
各一枚记号时，`_task_tokens` 按单号建字典只留一枚 ⇒ `submission_reading` 报
`state=submitted` 却带着另一族那一枚的 path/via。

## 三态纪律

- `checked=False` = 这一格没查成（目录列不出来 / 台账读不出来），
  不是「没有已签稿」、也不是「没有提交」；
- 老验证行没有 `producer_role` 这一格 ⇒ :func:`verification_producer_reading`
  读 `unknown`，不按族硬填一个 F；
- 族认不出（坏路径 / `notes/` / `legacy`）⇒ `producer_role="unknown"` 并带理由，
  不猜一个角色。

## 边（V 的父名单）

`ALLOWED_EDGES` 的形状是 `dict[str, frozenset[str]]`（角色 → 它能召唤的角色），
不是 `list[tuple]`。所以「谁是 V 的父」= 所有值里含 `"V"` 的那些键；见
:func:`parents_of`。这一格每次现读 capabilities，不缓存、不抄一份常量表。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import manuscriptfamily as _MFAM
from . import schema as S

#: 稿族 ⇒ 产出方角色的唯一一张映射表在 `manuscriptproducers`（本模块只回引，
#: 不再抄第二份 —— 抄出来的那张表在 import 之后永远不生效，读者却会以为改它有用）。

#: 「已提交」记号的前缀与字段 —— 真身在 `agent_f/submission.py`，这里只做懒引用。
SUBMISSION_PREFIX = "mss:"

#: 任务的终态（`block` 不算：它能被唤醒，不是终态）。
TERMINAL_TASK_STATUSES: tuple[str, ...] = tuple(
    s for s in S.TASK_STATUSES if s not in ("pending", "running", "block"))

#: `via` 的三档（统一读口的三条读数之一）：F/E 收工、B 收录、V 签发那一刻。
#:
#: 签是事件、收工是轮询 —— 轮询会漏掉「签晚于收工」那一次，
#: 所以签成功那一刻框架也走 `mss:` 这条路把稿置为已提交（:func:`mark_sign_submitted`）。
#: 两条路写同一个记号格式，只差 `via=` 这一格，读的人分得清是谁置的。
VIA_CLOSING = "closing_auto_submit"
VIA_INGEST = "ingested_to_ledger"
VIA_SIGN = "sign_issued"


# --------------------------------------------------------------------- 记号（复用 F 那一套）
def _submission():
    """懒取 `agent_f.submission`（它那套 `mss:` 记号格式/解析器是唯一真身）。"""
    from .agent_f import submission as _SUB

    return _SUB


def submission_token(**kwargs: Any) -> str:
    """拼一枚 `mss:` 记号（薄转发，格式由 `agent_f/submission.py` 定义）。"""
    return _submission().submission_token(**kwargs)


def parse_submission(token: Any) -> dict[str, Any] | None:
    return _submission().parse_submission(token)


def submissions_of(artifacts: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    return _submission().submissions_of(artifacts)


def resolve_submission(records: Any, *, family: Any = "", manuscript_id: Any = "",
                       families: Any = ()) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """按 (族, 稿号) 取一枚提交记号 ⇒ `(记号, 读数)`（转发 `agent_f.submission`）。"""
    return _submission().resolve_submission(
        records, family=family, manuscript_id=manuscript_id, families=families)


def submission_key(family: Any, manuscript_id: Any) -> str:
    """身份 ⇒ 带族键 `<族>:<稿号>`（转发 `agent_f.submission`）。"""
    return _submission().submission_key(family, manuscript_id)


from .manuscriptproducers import (
    PRODUCER_OF_FAMILY, UNKNOWN, _manuscript_id_of, parents_of, producer_of,
    verification_producer_reading,
)
from .manuscriptpaths import (  # 路径号（B 收录时分配；一个稿号 = 一份文件 = 一份证明）
    assign_path_group, path_reading, stamp_verification_path_group,
)
# --------------------------------------------------------------------- 盘上事实
def _proof_sha(text: str) -> str:
    """`## 证明` 那一节的 sha256（全仓一把尺：`proofregistry.proof_sha`）。"""
    from . import proofregistry as _PR

    return _PR.proof_sha(text)


def _sign_reading(root: Any, body_sha: str) -> dict[str, Any]:
    """V 的颁发表里那一份签（逐份文件；`issued.json` 只是派生归档，不拿它下结论）。"""
    from . import vsigns as _VS

    sha = str(body_sha or "").strip().lower()
    if len(sha) != 64:
        return {"checked": False, "found": False, "signed": False, "sign": {},
                "sign_sha": "", "at": "", "why": "没有可查的正文 sha"}
    got = _VS.credential_reading(root, sha)
    doc = dict(got.get("sign") or {})
    sign_sha = ""
    path = str(got.get("path") or "")
    if path:
        try:
            sign_sha = hashlib.sha256((Path(str(root)) / path).read_bytes()).hexdigest()
        except OSError:
            sign_sha = ""
    return {
        "checked": bool(got.get("checked")), "found": bool(got.get("found")),
        "signed": bool(doc) and bool(got.get("recomputable")),
        "recomputable": bool(got.get("recomputable")),
        "sign": doc, "sign_sha": sign_sha, "at": str(doc.get("at") or ""),
        "artifact_sha": str(got.get("artifact_sha") or ""),
        "why": str(got.get("why") or ""),
    }


def _read_tasks(store: Any) -> tuple[list[dict[str, Any]], str]:
    if store is None:
        return [], "没有 store ⇒ `tasks.artifacts` 读不到（不是「没有提交」）"
    try:
        return [dict(r) for r in store.rows("tasks")], ""
    except Exception as exc:  # noqa: BLE001
        return [], f"`tasks` 读不出来（{type(exc).__name__}: {exc}）"


def _task_tokens(tasks: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]],
                                                             dict[str, dict[str, Any]],
                                                             list[str]]:
    """`tasks.artifacts` ⇒ `({身份键: 记号}, {身份键: 写记号的那一行}, 问题)`。

    键由 `submissions_of` 给：一个号只在一族出现 ⇒ 老键 `<稿号>`；同号跨族 ⇒
    `<族>:<稿号>`（两族的记号各成一条，不再折成一行）。按 (族, 稿号) 取的时候走
    :func:`resolve_submission`，别直接拿单号来 `in` 这张字典。
    """
    tokens: dict[str, dict[str, Any]] = {}
    owners: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for row in tasks or ():
        got, bad = submissions_of((row or {}).get("artifacts") or ())
        problems.extend(bad)
        for key, rec in got.items():
            tokens.setdefault(str(key), dict(rec))
            owners.setdefault(str(key), dict(row or {}))
    return tokens, owners, problems


def _families_for_mid(root: Any, mid: str) -> list[str]:
    """盘上这一号出现在哪几族（`manuscripts/<角色>/<前缀><号>.md`）⇒ 族的清单（纯读、不猜）。

    给 :func:`resolve_submission` 的 `families` 用：老记号没写族时，"这一号在盘上
    只有一族"才允许按它读；两族以上 ⇒ 不猜（跨族同号）。列不出来 ⇒ 空列表 ——
    那是"这一格没读到"，不是"没有别的族"（调用方还会拿记号自己的读数兜底）。
    """
    if not mid:
        return []
    base = Path(str(root))
    families: list[str] = []
    for family in _MFAM.FAMILY_ORDER:
        prefix = _MFAM.prefix_of(family)
        d = base / _MFAM.dir_of(family)
        try:
            paths = sorted(d.glob(f"{prefix}{mid}*.md")) if d.is_dir() else []
        except OSError:
            paths = []
        for path in paths:
            if _manuscript_id_of(f"{_MFAM.dir_of(family)}/{path.name}") == mid:
                families.append(family)
                break
    return families


def _find_rel_for_mid(root: Any, mid: str) -> str:
    """按稿号在 `manuscripts/<角色>/` 下找那份稿（一个稿号 = 一份文件；多份 ⇒ 空串，不挑一份）。"""
    if not mid:
        return ""
    hits: list[str] = []
    base = Path(str(root))
    for family in _MFAM.FAMILY_ORDER:
        prefix = _MFAM.prefix_of(family)
        d = base / _MFAM.dir_of(family)
        try:
            paths = sorted(d.glob(f"{prefix}{mid}*.md")) if d.is_dir() else []
        except OSError:
            paths = []
        for path in paths:
            rel = f"{_MFAM.dir_of(family)}/{path.name}"
            if _manuscript_id_of(rel) == mid:
                hits.append(rel)
    uniq = sorted(set(hits))
    return uniq[0] if len(uniq) == 1 else ""


# --------------------------------------------------------------------- B：收录即提交
def _task_row_for(tasks: Sequence[Mapping[str, Any]], *, role: str,
                  task_id: str) -> tuple[dict[str, Any] | None, str]:
    tid = str(task_id or "")
    if not tid:
        return None, "这一趟没有召唤号 ⇒ 没有可写的 task 行"
    found = next((r for r in tasks if str(r.get("task_id") or "") == tid), None)
    if found is None:
        return None, f"召唤号 {tid!r} 不在 `tasks` 表里 ⇒ 没有可写的 task 行"
    if str(found.get("role") or "") != str(role):
        return None, (f"召唤号 {tid!r} 那一行的角色是 {found.get('role')!r}，"
                      f"不是 {role}")
    if str(found.get("status") or "") in TERMINAL_TASK_STATUSES:
        return None, f"召唤号 {tid!r} 那一行已经是终态 {found.get('status')!r}"
    return found, ""


def mark_ingested(*, store: Any, root: Any, manuscript: Any, out: dict[str, Any],
                  task_id: str = "", stamp: str = "") -> dict[str, Any]:
    """B 把一份 `b-proof-*` 存进台账（收录成功）时，在 B 自己那一行写提交记号。

    只在 `out["ok"] is True` 且路径族是 `b-proof` 时动手；受控拒 / 别的族 ⇒ 原样返回，
    不写一个字节。没有 task 行时把理由写进 `out["b_submission"]`（不静默）。
    幂等按 (族, 稿号)：所有 B 行里已有 `b-proof` 这一份的记号 ⇒ 不再写。
    """
    rel = str(manuscript or "").strip().replace("\\", "/")
    result: dict[str, Any] = {"checked": False, "written": False, "already": False,
                              "manuscript_id": "", "family": "", "token": "",
                              "via": VIA_INGEST,
                              "path_group": int((out.get("path_group") or {}).get(
                                  "path_group") or 0),
                              "why": ""}
    out["b_submission"] = result
    if not isinstance(out, dict) or not bool(out.get("ok")):
        result["why"] = "收录没有成功（受控拒 / 未写成）⇒ 不置已提交"
        return out
    if not task_id:
        try:
            from . import conductor as _CND

            task_id = str(_CND.current_task_id() or "")
        except Exception:  # noqa: BLE001 —— 读不到就是没有 task 行
            task_id = ""
    if not stamp:
        stamp = S.now_iso()
    prod = producer_of(rel)
    if str(prod.get("producer_role") or "") != "B":
        result["why"] = (f"`{rel}` 不是 B 的稿（产出方 "
                         f"{prod.get('producer_role') or 'unknown'}）⇒ 这一笔不写 B 的提交记号")
        result["checked"] = True
        return out
    mid = str(prod.get("manuscript_id") or "")
    fam = str(prod.get("family") or "")
    result["manuscript_id"] = mid
    result["family"] = fam
    path = Path(str(root)) / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        result["why"] = f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 提交记号写不了"
        return out
    body_sha = _proof_sha(text)
    sign = _sign_reading(root, body_sha)
    sign_rec = dict(sign.get("sign") or {})
    stmt_id = str((out.get("target") or {}).get("stmt_id")
                  or (out.get("register") or {}).get("stmt_id")
                  or out.get("stmt_id") or "")
    # `tasks` 只读一次：原先 `_task_row_for` 与下面那次 `_read_tasks` 各读一遍整表。
    tasks, tasks_why = _read_tasks(store)
    row, row_why = ((None, tasks_why) if tasks_why
                    else _task_row_for(tasks, role="B", task_id=task_id))
    if row is None:
        result.update(checked=True, why=f"没有 task 行可写：{row_why}")
        return out
    submitted, _owners, _bad = _task_tokens(
        [r for r in tasks if str(r.get("role") or "") == "B"])
    hit, reading = resolve_submission(submitted, family=fam, manuscript_id=mid,
                                      families=_families_for_mid(root, mid))
    if hit is not None:
        result.update(checked=True, already=True, why=(
            f"`tasks.artifacts` 里已经有 {fam} 稿号 {mid} 的提交记号 ⇒ 幂等：不重复写"))
        return out
    try:
        token = submission_token(
            manuscript_id=mid, family=fam, path=rel, body_sha=body_sha,
            sign_sha=str(sign.get("sign_sha") or ""), file_sha=hashlib.sha256(
                path.read_bytes()).hexdigest(),
            proof_no=int(sign_rec.get("proof_no") or prod.get("proof_no") or 1),
            statement_id=stmt_id, at=str(sign.get("at") or ""),
            submitted_at=str(stamp or ""), via=VIA_INGEST)
    except (ValueError, OSError) as exc:
        result["why"] = f"提交记号拼不出来（{type(exc).__name__}: {exc}）"
        return out
    try:
        with store.tx("tasks", actor="B", note="b.ingest:auto_submit") as tx:
            cur = tx.find("tasks", task_id=str(task_id))
            if cur is None:
                result["why"] = f"事务里找不到 {task_id!r} 那一行 ⇒ 提交记号没写"
                return out
            existing: dict[str, dict[str, Any]] = {}
            for one in tx.rows("tasks"):
                if str(one.get("role") or "") != "B":
                    continue
                got, _bad = submissions_of(one.get("artifacts") or ())
                for key, rec in got.items():
                    existing.setdefault(str(key), dict(rec))
            hit, _reading = resolve_submission(
                existing, family=fam, manuscript_id=mid,
                families=_families_for_mid(root, mid))
            if hit is not None:
                result.update(checked=True, already=True,
                              why=f"并发下另一笔已经写了 {fam} 稿号 {mid} 的提交记号")
                return out
            cur["artifacts"] = S.sorted_unique(list(cur.get("artifacts") or ()) + [token])
            tx.upsert("tasks", cur, note="b.ingest:auto_submit")
    except Exception as exc:  # noqa: BLE001
        result["why"] = f"提交记号写不进 `tasks`（{type(exc).__name__}: {exc}）"
        return out
    result.update(checked=True, written=True, token=token,
                  why=f"收录成功 ⇒ {fam} 稿号 {mid} 置为已提交（via={VIA_INGEST}）")
    return out


def _producer_row(*, store: Any, role: str, task_id: str = "",
                  manuscript: str = "") -> tuple[dict[str, Any] | None, str]:
    """签触发提交要写的那一行：先按召唤链找，再退到这份稿的产出实例那一行。

    与 :func:`_task_row_for` 的两点不同（都是这一条路必须的）：

    1. 沿 `parent_task_id` 往上找：签那一刻的召唤是 V，而稿是它的父（F/E/B）产的；
       收方秘书那条链让 V 的 parent 就是送审的产出方；
    2. 允许写到终态行：签可能晚于收工 —— 这一条路存在的理由就是补上那个次序，所以
       终态不是拒绝理由。`tasks.artifacts` 是 append-only，晚到的提交记号不改变那一行
       已有的任何一格。

    ## 退路改成「这份稿的产出实例」（K8 / EM-07）

    改前退到 `mine[-1]`（该角色最近结束的一行）：签晚于收工时，记号会写进另一个
    同角色实例的那一行 —— 那一行不是这份稿的主人。现在退路只认一个事实：这份稿在
    产物台账里的产出实例（`manuscript_producer` 的 `producer_instance`），再在 `tasks`
    里找那个实例的行（实例标签按 `identity.resolve_identity` 逐行读，名册名优先）。
    找不到就受控失败（`row=None` + 理由），不拿"最近的一行"凑。
    """
    tasks, why = _read_tasks(store)
    if why:
        return None, why
    by_id = {str(r.get("task_id") or ""): r for r in tasks}
    cur = str(task_id or "")
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        row = by_id.get(cur)
        if row is None:
            break
        if str(row.get("role") or "") == str(role):
            return dict(row), ""
        cur = str(row.get("parent_task_id") or "")
    instance = ""
    if str(manuscript or "").strip():
        instance = _manuscript_instance(store, str(manuscript))
    mine = [dict(r) for r in tasks if str(r.get("role") or "") == str(role)]
    if not mine:
        return None, f"`tasks` 里没有 {role} 的行 ⇒ 签触发提交没有可写的台账行"
    if not instance:
        if len(mine) == 1:
            # 唯一才认：这个角色只有一行 ⇒ 「哪一行」不是选择，是事实。
            return mine[0], ""
        return None, (f"沿召唤链找不到产出方那一行，而这份稿在产物台账里没有实例归属、"
                      f"这个角色又有 {len(mine)} 行 ⇒ 不猜是哪一行（不拿「最近的一行」当它）")
    same = [r for r in mine if _row_instance(store, role, str(r.get("task_id") or "")) == instance]
    if not same:
        return None, (f"产出实例 {instance} 在 `tasks` 里没有台账号行 ⇒ 签触发提交没有"
                      "可写的行（不猜一个同角色的行）")
    same.sort(key=lambda r: (str(r.get("started_at") or ""), str(r.get("task_id") or "")))
    return same[-1], ""


def _manuscript_instance(store: Any, manuscript: str) -> str:
    """这份稿的产出实例标签（读不出来 / 没有归属 ⇒ 空串，不猜）。"""
    try:
        from .agent_f import pending as _FP

        got = dict(_FP.manuscript_producer(str(getattr(store, "root", "") or ""), manuscript))
    except Exception:  # noqa: BLE001 —— 读不成按「没有归属」处置
        return ""
    return str(got.get("producer_instance") or "")


def _row_instance(store: Any, role: str, task_id: str) -> str:
    """一个台账号那一趟的实例标签（`identity.resolve_identity`；台账号兜底不算）。"""
    try:
        from . import identity as _ID

        got = dict(_ID.resolve_identity(store, role, task_id=task_id))
    except Exception:  # noqa: BLE001 —— 读不成 ⇒ 不认这一行
        return ""
    if str(got.get("source") or "") == "task_id":
        return ""
    return str(got.get("instance") or "")


def mark_sign_submitted(*, store: Any, root: Any, artifact_sha: Any,
                        artifact_path: str = "", task_id: str = "",
                        stamp: str = "") -> dict[str, Any]:
    """V 签发成功那一刻：把这一份稿在产出方那一行置为已提交（`via=sign_issued`）。

    为什么要这一条：「签是事件，收工是轮询；轮询会漏掉「签晚于收工」这种病态」——
    收工那一趟扫盘时还没签，稿会停在「已签、未提交」。这条路把「签发成功」本身当成
    提交事件。

    复用：记号格式与解析全部来自 `agent_f/submission.py`（本模块只转发），
    不新造第二套字符串；幂等键与收工那一条相同 —— (族, 稿号)：`e-proof-000000`
    已提交不意味着 `e-num-000000` 已提交（四族各有号段、同号是常态）。

    三态：`checked=False` = 这一格没查成（签读不出 / 台账读不出），不是「没签」；
    `written=False, already=True` = 之前已经有一条记号（签触发 + 收工各一次只剩一条）；
    `written=False, checked=True` + `why` = 查过了，这一份不该提交（族不对 / 签不住 /
    签后正文又变了 / 没有可写的行）。

    返回键：`checked` / `written` / `already` / `manuscript_id` / `family` /
    `producer_role` / `task_id` / `token` / `via` / `why`。
    """
    out: dict[str, Any] = {
        "checked": False, "written": False, "already": False,
        "manuscript_id": "", "family": "", "producer_role": "", "task_id": "",
        "token": "", "via": VIA_SIGN, "why": "",
    }
    # 「先按召唤链找」那一档的入口（`_producer_row` 的第一条策略）：调用方不给
    # `task_id` 时取这一趟送审的送审者（`conductor.current_parent()`）—— 签那一刻
    # 跑着的是 V，稿是它的父（F/E/B）产的，父那一行就是产出方（找不到再退回当前
    # 这一趟的台账号，让 `_producer_row` 沿 `parent_task_id` 继续上行）。
    # 2026-11-19 修：改前两个调用点（`vsigns._sign_submission` /
    # `verifications.sign_statement`）都不传，第一条策略永远不生效，退路只剩
    # 「这份稿的产出实例」；而产出实例在没给实例标签时记的是台账号本身
    # （`identity.resolve_identity` 的 task_id 兜底），`_row_instance` 又不认它
    # ⇒ `C2 证明链` 的 F 行拿不到 `mss:` 记号（`written=False` + "没有可写的行"）。
    if not str(task_id or "").strip():
        try:
            from . import conductor as _CND

            _parent_id, _parent_role = _CND.current_parent()
            task_id = str(_parent_id or "") or str(_CND.current_task_id() or "")
        except Exception:  # noqa: BLE001 —— 没有挂点 = 直调 / 单测，照旧走后面那两条
            task_id = ""
    sha = str(artifact_sha or "").strip().lower()
    sign = _sign_reading(root, sha)
    if not sign.get("checked"):
        out["why"] = (f"这一签没查成（{sign.get('why') or '签不在盘上'}）⇒ "
                      "不写提交记号（不是「没签」）")
        return out
    if not sign.get("signed"):
        out["why"] = (f"签这一格不是可复算的「成立」（{sign.get('why') or '?'}）⇒ "
                      "不写提交记号：签不住就不算提交")
        return out
    doc = dict(sign.get("sign") or {})
    rel = str(artifact_path or doc.get("artifact_path") or "").strip().replace("\\", "/")
    prod = producer_of(rel)
    role = str(prod.get("producer_role") or UNKNOWN)
    mid = str(prod.get("manuscript_id") or "")
    fam = str(prod.get("family") or "")
    out.update(producer_role=role, manuscript_id=mid, family=fam)
    if role not in ("F", "E"):
        out["checked"] = True
        out["why"] = (f"`{rel or '（没有稿路径）'}` 的产出方是 {role} ⇒ "
                      "签触发提交只认 F / E 的稿（B 的稿「提交」= 收录进台账，"
                      "走 `mark_ingested` 那条 `via=ingested_to_ledger`）")
        return out
    path = Path(str(root)) / rel
    try:
        blob = path.read_bytes()
        text = blob.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        out["why"] = (f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ "
                      "提交记号写不了（没查成）")
        return out
    body_sha = _proof_sha(text)
    if body_sha != sha:
        out["checked"] = True
        out["why"] = (f"这一份签的是 `{sha}`，盘上现行正文是 `{body_sha}` ⇒ "
                      "签后正文又变了，不提交（按只读/冻结纪律这不该发生）")
        return out
    tasks, tasks_why = _read_tasks(store)
    if tasks_why:
        out["why"] = tasks_why
        return out
    if not stamp:
        stamp = S.now_iso()
    row, row_why = _producer_row(store=store, role=role, task_id=task_id,
                                 manuscript=rel)
    if row is None:
        out.update(checked=True, why=f"没有可写的 task 行：{row_why}")
        return out
    out["task_id"] = str(row.get("task_id") or "")
    # 幂等面只读这一行（EM-08）：记号本来就写在这一行上；跨实例合并会把另一个
    # 实例交过的同一稿号读成"这一趟已经交过了"。
    submitted, _owners, _bad = _task_tokens([row])
    hit, _reading = resolve_submission(submitted, family=fam, manuscript_id=mid,
                                       families=_families_for_mid(root, mid))
    if hit is not None:
        out.update(checked=True, already=True, why=(
            f"`tasks.artifacts` 里已经有 {fam} 稿号 {mid} 的提交记号 ⇒ 幂等：不重复写"
            f"（原有 via={hit.get('via') or '（老记号没这一格）'}）"))
        return out
    try:
        token = submission_token(
            manuscript_id=mid, family=fam, path=rel, body_sha=sha,
            sign_sha=str(sign.get("sign_sha") or ""),
            file_sha=hashlib.sha256(blob).hexdigest(),
            statement_id=str(doc.get("statement_id") or ""),
            at=str(doc.get("at") or ""), submitted_at=str(stamp), via=VIA_SIGN)
    except (ValueError, OSError) as exc:
        out["why"] = f"提交记号拼不出来（{type(exc).__name__}: {exc}）"
        return out
    try:
        with store.tx("tasks", actor=str(role), note="sign:auto_submit") as tx:
            cur = tx.find("tasks", task_id=out["task_id"])
            if cur is None:
                out["checked"] = True
                out["why"] = f"事务里找不到 {out['task_id']!r} 那一行 ⇒ 提交记号没写"
                return out
            existing: dict[str, dict[str, Any]] = {}
            got, _bad = submissions_of(cur.get("artifacts") or ())
            existing.update({str(k): dict(v) for k, v in got.items()})
            hit, _reading = resolve_submission(
                existing, family=fam, manuscript_id=mid,
                families=_families_for_mid(root, mid))
            if hit is not None:
                out.update(checked=True, already=True,
                           why=f"并发下另一笔已经写了 {fam} 稿号 {mid} 的提交记号")
                return out
            cur["artifacts"] = S.sorted_unique(
                list(cur.get("artifacts") or ()) + [token])
            tx.upsert("tasks", cur, note="sign:auto_submit")
    except Exception as exc:  # noqa: BLE001 —— 写不进去必须如实说
        out["why"] = f"提交记号写不进 `tasks`（{type(exc).__name__}: {exc}）"
        return out
    out.update(checked=True, written=True, token=token, why=(
        f"签发成功 ⇒ {fam} 稿号 {mid} 置为已提交（via={VIA_SIGN}）"))
    return out


def submission_reading(store: Any, root: Any, *, manuscript: Any = "",
                       manuscript_id: Any = "", producer_code: str = "") -> dict[str, Any]:
    """统一读口：给定稿号 / 路径 ⇒ 产出方 + 提交状态 + 时刻 + via。

    三处 join：
    1. 路径族（`manuscriptfamily.classify_manuscript`）⇒ `producer_role`；
    2. V 的颁发表（`out/vsigns/<正文 sha>.json`）⇒ `signed` / `signed_sha` / `sign_sha`；
    3. `tasks.artifacts` 里的 `mss:` 记号 ⇒ `state` / `submitted_at` / `via`。

    `via`：F / E 的稿 ⇒ `closing_auto_submit`；B 的稿 ⇒ `ingested_to_ledger`。
    没有记号 ⇒ `state="unsubmitted"`、`submitted_at=""`、`via=""`（不是「没查」）。
    老验证行的产出方格由 :func:`verification_producer_reading` 读（缺格 ⇒ unknown）。

    ## (族, 稿号)：`manuscript` 给了就以它的族为准

    `e-proof-000000` 与 `e-num-000000` 是两份稿：给路径 ⇒ 只读那一族的记号；只给稿号
    而这一号在多族都有 ⇒ 不许猜 —— `checked=False` + `why` 点名「跨族同号、无法
    唯一定位」（`ambiguous` 那一格带 families/keys），绝不把另一族那一枚的 path/via
    读成这一份的。
    """
    mid = str(manuscript_id or "").strip()
    rel = str(manuscript or "").strip().replace("\\", "/")
    tasks, tasks_why = _read_tasks(store)
    tokens, owners, problems = _task_tokens(tasks)
    if not mid:
        mid = _manuscript_id_of(rel) if rel else ""
    #: 这一号在盘上出现在哪几族（老记号没写族时，"唯一确定"要靠它）。
    on_disk = _families_for_mid(root, mid) if mid else []
    if not rel and mid:
        # 先看记号自己带的地址（改前语义：记号里的 `path` 优先），再看盘上唯一的那份。
        probe, _probe_reading = resolve_submission(tokens, manuscript_id=mid,
                                                   families=on_disk)
        if probe and probe.get("path"):
            rel = str(probe["path"])
        else:
            rel = _find_rel_for_mid(root, mid)
    if not mid and rel:
        mid = _manuscript_id_of(rel)
        on_disk = _families_for_mid(root, mid) if mid else []
    #: 稿的族：路径认得出就用它（`notes/` 一类历史目录也按名字里的族读）。
    family = str(_MFAM.classify_manuscript(rel).get("name_family") or "") if rel else ""
    rec, reading = resolve_submission(tokens, family=family, manuscript_id=mid,
                                      families=on_disk)
    rec = dict(rec or {})
    owner = dict(owners.get(str(reading.get("key") or "")) or {})
    prod = producer_of(rel) if rel else {
        "producer_role": UNKNOWN, "producer_code": "", "family": "", "tier": "",
        "manuscript_id": mid, "checked": False, "why": "没有稿路径 ⇒ 产出方 unknown"}
    signed_sha = str(rec.get("body_sha") or "")
    if not signed_sha and rel:
        try:
            signed_sha = _proof_sha((Path(str(root)) / rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            signed_sha = ""
    sign = _sign_reading(root, signed_sha) if signed_sha else {
        "checked": False, "found": False, "signed": False, "sign": {},
        "sign_sha": "", "at": "", "why": "没有正文 sha ⇒ 签查不了"}
    role = str(prod.get("producer_role") or UNKNOWN)
    if rec:
        # 记号自己带着 `via`（三条路各写各的）；老记号没有这一格 ⇒
        # 按产出方族回落（B ⇒ 收录，其余 ⇒ 收工扫到的），不把它读成「没提交」。
        via = str(rec.get("via") or (VIA_INGEST if role == "B" else VIA_CLOSING))
        state = "submitted"
    else:
        via, state = "", "unsubmitted"
    out: dict[str, Any] = {
        # 键集是本函数的公开面（工具声明逐字读它）⇒ 不加新顶层键：族与「跨族同号」
        # 都写在 `why` / `problems` 里（两个键本来就在声明里）。
        "checked": True, "manuscript": rel, "manuscript_id": mid,
        "producer_role": role,
        "producer_code": str(producer_code or prod.get("producer_code") or ""),
        "state": state, "submitted_at": str(rec.get("submitted_at") or ""),
        "via": via,
        "signed": bool(sign.get("signed")),
        "signed_sha": str(sign.get("artifact_sha") or signed_sha),
        "sign_sha": str(sign.get("sign_sha") or ""),
        "sign_at": str(sign.get("at") or ""),
        "token": str(rec.get("token") or ""),
        "task_id": str(owner.get("task_id") or ""),
        "task_role": str(owner.get("role") or ""),
        "problems": list(problems), "why": "",
    }
    if tasks_why:
        out["problems"].append(tasks_why)
    if role != UNKNOWN and owner and str(owner.get("role") or "") != role:
        out["problems"].append(
            f"写提交记号的是 {owner.get('role')}（{owner.get('task_id')}），"
            f"而路径族说产出方是 {role}")
    if str(reading.get("state") or "") == "ambiguous":
        # 「查过了、但定不下来是哪一份」：不折成「未提交」，也不折成「已提交」；
        # 读数逐字点名「跨族同号」（families / keys 一并给在 why 里）。
        why = str(reading.get("why") or "")
        out["checked"] = False
        out["why"] = why
        out["problems"].append(why)
    elif not rel:
        out["checked"] = False
        out["why"] = ("没有手稿路径 / 稿号 ⇒ 这一格没查成（不是「没有提交」）")
    elif not rec:
        out["why"] = (f"`tasks.artifacts` 里没有 {family or '任何族'} 稿号 "
                      f"{mid or '?'} 的 `mss:` 记号 ⇒ 未提交（via 没有来源）")
    else:
        out["why"] = (f"已提交（族={family or '（老记号没写族）'}，via={via}，"
                      f"submitted_at={out['submitted_at'] or '未记录'}）")
    return out
