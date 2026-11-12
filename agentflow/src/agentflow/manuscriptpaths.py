# -*- coding: utf-8 -*-
"""多证明的路径号（B 收录时分配）。

一条命题已有 N 条路径 ⇒ 新正文排第 N+1；同一份稿（同正文 sha / 同路径）重复
收录 ⇒ 沿用原号。依赖行与 `verifications` 行都用这个号。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .manuscriptproducers import _manuscript_id_of


# --------------------------------------------------------------------- 路径号（多证明）
#: 逐路径那份稿记录在命题行上的键名：`{路径号: 工作区相对路径}`（2026-11-13，V1-A）。
#:
#: 为什么是"路径"而不是"稿号"：稿号是路径的纯函数（`manuscriptproducers._manuscript_id_of`
#: 是全仓唯一那把尺），反过来不成立 —— 同一个六位号在 `f-proof` / `b-proof` 两个号段里
#: 各有一份稿。所以这里存路径，稿号在读侧现算（`paths[].manuscript_id`），不存两份会分家的
#: 事实。旧盘没有这一格 ⇒ 本格不贡献任何路径（退回 `manuscript_id` 那一个旧口径）。
PER_PATH_KEY = "manuscripts"


def _per_path_manuscripts(row: Any) -> tuple[dict[int, str], list[str]]:
    """命题行上的逐路径稿记录 ⇒ `({路径号: 稿路径}, 读数问题)`。

    三态（与 `path_reading` 同一套纪律）：
    - 这一格不存在 ⇒ `({}, [])`：老盘，退回旧口径（不是"读不出来"）；
    - 这一格存在而读得出 ⇒ 逐条给出路径号与稿路径；
    - 这一格存在却读不成（不是映射 / 路径号不是正整数 / 稿是空的）⇒ 问题清单非空。
      调用方把问题原样带进 `path_reading` 的 `problems`，V 那一侧据此 fail-closed
      （"没读成"绝不折成"没有这一条路径"）。
    """
    raw = row.get(PER_PATH_KEY) if isinstance(row, Mapping) else None
    if raw is None:
        return {}, []
    if not isinstance(raw, Mapping):
        return {}, [f"`{PER_PATH_KEY}` 不是映射（{type(raw).__name__}）⇒ 逐路径稿记录读不出来"]
    out: dict[int, str] = {}
    problems: list[str] = []
    for group_raw, rel_raw in raw.items():
        try:
            group = int(group_raw)
        except (TypeError, ValueError):
            problems.append(f"`{PER_PATH_KEY}` 里有一个读不出的路径号 {group_raw!r}")
            continue
        rel = str(rel_raw or "").strip().replace("\\", "/")
        if group < 1 or not rel:
            problems.append(f"`{PER_PATH_KEY}.{group_raw}` 不是一条有效记录"
                            f"（路径号 {group!r}、稿 {rel_raw!r}）")
            continue
        out[group] = rel
    return out, problems


def path_reading(store: Any, root: Any, *, statement_id: str) -> dict[str, Any]:
    """一条命题现在有几条「证明路径」、每条是哪份稿（稿号 + 正文 sha）。

    四条来源 join：
    - `dependencies` 行的 `path_group`（B 收录时写的那个号；老盘只有 1）；
    - `statements` 行的证明清单（每条路径的正文 sha）；
    - `statements` 行的逐路径稿记录（`manuscripts`：路径号 ⇒ 稿路径，B 收录每一笔
      写一格）。它是"这一条路径是哪份稿"的第一手记录：收录前落下的 pending 行在
      认领之前不属于任何命题（`list_verifications` 读不到），签行那一面就只剩
      正文 sha、没有稿号 —— 这一格正好补上那一段；
    - `verifications` 行的 `path_group`（V 落行时可能还没有，B 收录后由
      :func:`stamp_verification_path_group` 补齐）。没有这一格的签行按正文 sha
      认回已有那条路径、只补 `manuscript`，不新增路径；认不回来才留成 0 号
      （不计入 `paths`，不替它编组号）。

    每条路径的 `manuscript` 按"签的载体优先、收录记录其次、被审对象兜底"取：
    签行里的 `manuscript`（V 真的把签盖在那份稿上）最硬；逐路径稿记录次之；
    `object_path`（被审的对象，同一份正文可以有多份副本）只在整条路径都没有稿时兜底。
    """
    sid = str(statement_id or "").strip()
    out: dict[str, Any] = {"checked": False, "statement_id": sid, "paths": [],
                           "count": 0, "why": ""}
    if not sid:
        out["why"] = "没有命题号 ⇒ 路径数判不了"
        return out
    by_group: dict[int, dict[str, Any]] = {}
    #: 没有 `path_group` 的签行里、只有 `object_path` 的那几行（路径号 ⇒ 对象路径）。
    #: 它们只在同一条路径找不到任何带 `manuscript` 的签行时才兜底 —— 否则同一份正文
    #: 的副本会把路径指到副本上（见下面那段注释）。
    objects_only: dict[int, str] = {}
    problems: list[str] = []
    try:
        deps = store.rows("dependencies") if store is not None else []
    except Exception as exc:  # noqa: BLE001
        return {"checked": False, "statement_id": sid, "paths": [], "count": 0,
                "why": f"`dependencies` 读不出来（{type(exc).__name__}: {exc}）"}
    for row in deps:
        used = str(row.get("used_by") or "")
        if used.split("#", 1)[0] != f"stmt:{sid}":
            continue
        try:
            group = int(row.get("path_group") or 1)
        except (TypeError, ValueError):
            group = 1
        one = by_group.setdefault(group, {"path_group": group, "manuscript_id": "",
                                          "body_sha": "", "manuscript": "",
                                          "sources": []})
        one["sources"].append(str(row.get("source_stmt_id")
                                  or row.get("source_lit_id")
                                  or row.get("source_experiment_id")
                                  or row.get("label") or ""))
    # ---- 命题行自己的证明清单也是路径面（v3：不再只靠依赖行 / 签行） -------------
    #
    # 一条命题的 canonical 正文 + `proofs` 清单逐份就是它的路径。改前这里只读
    # `dependencies` 与 `verifications`：一份"自足、没有依赖行、签还没落成行"的证明
    # 在路径面上是 0 条 ⇒ 第二份收录会被分到第 1 条（同号）。补上这一面之后
    # "已有几条路径"与"这一行上有几份证明"同源（`verifications.proof_list` 是唯一
    # 读口，canonical 是 #p1）。
    row_self = None
    try:
        rows_self = store.rows("statements") if store is not None else []
    except Exception:  # noqa: BLE001 —— 读不到就不加这一面（"没查成"不冒充"没有"）
        rows_self = []
        problems.append("statements 读不出来 ⇒ 路径面只按依赖行 / 签行读")
    for one_row in rows_self:
        if str(one_row.get("stmt_id") or "") == sid:
            row_self = one_row
            break
    if row_self is not None:
        from . import verifications as _VRself

        for proof_no, body in _VRself.proof_list(row_self):
            try:
                group = int(proof_no)
            except (TypeError, ValueError):
                continue
            if group < 1 or not str(body or "").strip():
                continue
            one = by_group.setdefault(group, {"path_group": group, "manuscript_id": "",
                                              "body_sha": "", "manuscript": "",
                                              "sources": []})
            if not one["body_sha"]:
                one["body_sha"] = str(_VRself.text_sha(str(body)) or "")
    try:
        from . import verifications as _VR

        rows, _vbad = _VR.list_verifications(root, statement_id=sid, limit=None)
        if _vbad:
            problems.extend(f"verifications: {x}" for x in _vbad)
    except Exception as exc:  # noqa: BLE001
        rows = []
        problems.append(f"`verifications` 读不出来（{type(exc).__name__}: {exc}）")
    for row in rows or ():
        doc = row or {}
        sha = str(doc.get("proof_sha256") or "").strip().lower()
        rel = str(doc.get("manuscript") or doc.get("object_path") or "").strip()
        raw_group = doc.get("path_group")
        group: int | None
        try:
            group = int(raw_group) if raw_group not in (None, "") else None
        except (TypeError, ValueError):
            group = None
        if group is None:
            # 老行没有这一格：先按正文 sha 认回已有那条路径 —— 收录之前 / 之后由 V
            # 落下的签行都可能没有路径号，而它记的那份稿仍是这条路径的载体。
            if sha:
                same = next(
                    (one for one in by_group.values()
                     if str(one.get("body_sha") or "").strip().lower() == sha), None)
                if same is not None:
                    # 优先用 `manuscript` 那一格（签的载体）；pending 行的 `object_path`
                    # 是"被审的对象"，同一份正文可以有多份副本，拿它当路径的稿会把
                    # 路径指到副本上。只有整条路径都找不到 `manuscript` 时才兜底用它。
                    rel_man = str(doc.get("manuscript") or "").strip()
                    if rel_man and not same["manuscript"]:
                        same["manuscript"] = rel_man
                        same["manuscript_id"] = _manuscript_id_of(rel_man)
                    elif rel and not same["manuscript"]:
                        objects_only.setdefault(
                            int(same.get("path_group") or 0), rel)
                    continue
            # 认不回来（老盘 / 正文改过）：只按 sha 记一条读数，不替它编组号。
            if not sha and not rel:
                continue
            group = 0
        one = by_group.setdefault(group, {"path_group": group, "manuscript_id": "",
                                          "body_sha": "", "manuscript": "",
                                          "sources": []})
        if not one["body_sha"]:
            one["body_sha"] = sha
        #: "这一条路径的稿"只认 `manuscript` 那一格（V 真的把签盖在那份稿上）。
        #: `object_path` 是"被审的对象"—— 同一份正文可以有多份副本（夹具 / 转抄 /
        #: 优化副本），拿它当路径的稿会把路径指到副本上。2026-11-13 起 B 收录时
        #: 连 pending 行也盖路径号（`stamp_verification_path_group`）⇒ 这些行会走到
        #: 这一支，所以这里不能再无条件吃 `rel`：`object_path` 降为兜底
        #: （`objects_only`，整条路径都找不到稿时才用）。
        man = str(doc.get("manuscript") or "").strip()
        if man and not one["manuscript"]:
            one["manuscript"] = man
            one["manuscript_id"] = _manuscript_id_of(man)
        if rel and not one["manuscript"]:
            objects_only.setdefault(int(group), rel)
    # ---- 命题行上的逐路径稿记录（`manuscripts`）：每条路径各那一份 ---------------
    #
    # 放在签行之后、`object_path` 兜底之前：签的载体最硬（V 真的盖了），收录时
    # 记下的那一份次之，被审对象（可能是副本）最后。这一格补的正是签行给不出的
    # 那一段：收录前落下的 pending 行在认领之前读不进 `list_verifications`，于是
    # 那条路径只剩正文 sha、没有稿号 —— 靠这一格才认得出它是第几条路径的稿。
    _per_path, _per_bad = _per_path_manuscripts(row_self)
    problems.extend(_per_bad)
    for group, path_rel in _per_path.items():
        one = by_group.setdefault(group, {"path_group": group, "manuscript_id": "",
                                          "body_sha": "", "manuscript": "",
                                          "sources": []})
        if not one["manuscript"]:
            one["manuscript"] = path_rel
            one["manuscript_id"] = _manuscript_id_of(path_rel)
    for group, rel in objects_only.items():
        one = by_group.get(int(group))
        if one is not None and not one["manuscript"]:
            one["manuscript"] = rel
            one["manuscript_id"] = _manuscript_id_of(rel)
    paths = [by_group[g] for g in sorted(by_group) if int(g) >= 1]
    out.update(checked=True, paths=paths, count=len(paths),
               why=(f"`stmt:{sid}` 有 {len(paths)} 条路径"
                    + (f"；{len(problems)} 条读数问题" if problems else "")))
    if problems:
        out["problems"] = problems
    return out


def assign_path_group(*, store: Any, root: Any, statement_id: str,
                      manuscript: str, body_sha: str = "") -> dict[str, Any]:
    """B 收录时给这一份证明分配「第几条路径」。

    规则：这条命题已经有 N 条路径 ⇒ 新正文排第 N+1 条；同一份稿（同正文 sha / 同
    路径）重复收录 ⇒ 沿用原来的号，不新增路径。老盘没有 `path_group` 的行不猜号
    （只贡献它有的组号；一条都没有 ⇒ 第 1 条）。
    """
    sid = str(statement_id or "").strip()
    rel = str(manuscript or "").strip().replace("\\", "/")
    sha = str(body_sha or "").strip().lower()
    got = path_reading(store, root, statement_id=sid)
    out: dict[str, Any] = {"checked": bool(got.get("checked")), "path_group": 1,
                           "existing": False, "count": int(got.get("count") or 0),
                           "statement_id": sid, "manuscript": rel, "body_sha": sha,
                           "paths": list(got.get("paths") or []), "why": "",
                           "problems": list(got.get("problems") or [])}
    if not sid:
        out.update(checked=False, why="没有命题号 ⇒ 路径号分不了（不是「第 1 条」）")
        return out
    if not got.get("checked"):
        out.update(checked=False, why=f"路径数没读成：{got.get('why') or '未知原因'}")
        return out
    for one in got.get("paths") or []:
        same_sha = sha and str(one.get("body_sha") or "").lower() == sha
        same_path = rel and str(one.get("manuscript") or "") == rel
        if same_sha or same_path:
            if int(one.get("path_group") or 0) >= 1:
                out.update(path_group=int(one["path_group"]), existing=True,
                           why=(f"这一份正文（sha {sha[:12]}…）已经是第 "
                                f"{one['path_group']} 条路径 ⇒ 沿用，不新增"))
                return out
    groups = [int(p.get("path_group") or 0) for p in (got.get("paths") or [])]
    group = max([g for g in groups if g >= 1] or [0]) + 1
    out.update(path_group=group, existing=False,
               why=(f"这条命题已有 {out['count']} 条路径 ⇒ 新收的这一份排第 {group} 条"))
    return out


def stamp_verification_path_group(*, root: Any, statement_id: str, body_sha: str,
                                  manuscript: str, path_group: int) -> dict[str, Any]:
    """把 B 分配的路径号回写到覆盖同一份正文的 `verifications` 行（老行补格）。

    为什么必须回写：V 落行时 B 还没收录（路径号还没分配），而同一份证明的依赖行与
    verification 行必须用同一个号。写法是"只读-判-重写"：已有同一个号 ⇒ 一个字节不动；
    已有别的号 ⇒ 不覆盖、如实报；其余行逐字节原样。

    ## pending 行也盖（2026-11-13，V1-B）

    改前这一格跳过未认领的 pending 行（判据是"文件名不等于 `<命题号>.jsonl`"）。
    而 pending 台账的文件名是正文 sha（`verifications.pending_ledger_path`），
    永远不等于 `<命题号>.jsonl` ⇒ 收录前落下的那一签永远拿不到路径号，只剩"哪份正文"
    而没有"第几条路径"。于是"一条路径若从未在册重签、只剩 pending 行"这一档里，
    路径号只能靠 B 收录这一笔来补 —— 现在补，且不看认领状态（盖号不是认领：
    `statement_id` 那一格仍然只有 `vsigns.bind_pending_claim` 能写）。
    已有别的号 ⇒ 照旧不覆盖（并发 / 同一份正文被两条命题收录时如实报出来）。
    """
    sid = str(statement_id or "").strip()
    sha = str(body_sha or "").strip().lower()
    rel = str(manuscript or "").strip().replace("\\", "/")
    group = int(path_group or 0)
    out: dict[str, Any] = {"checked": False, "stamped": 0, "pending_stamped": 0,
                           "files": [], "problems": [], "why": ""}
    if not sid:
        out["why"] = "没有命题号 ⇒ 路径号回写不了（不是「已经写过」）"
        return out
    if group < 1:
        out["why"] = f"路径号必须是正整数（收到 {path_group!r}）"
        return out
    try:
        from . import verifications as _VR

        files = [_VR.verification_ledger_path(root, sid)]
        pending = _VR.pending_dir(root)
        if pending.is_dir():
            files.extend(sorted(pending.glob("*.jsonl")))
    except Exception as exc:  # noqa: BLE001
        out["why"] = f"verifications 目录读不出来（{type(exc).__name__}: {exc}）"
        return out
    pending_dir_path = pending
    bad_any = False
    for path in files:
        if not path.is_file():
            continue
        #: 这一份文件是不是 pending 那一条叠（只用来分开报读数，不改写法）。
        is_pending = path.parent == pending_dir_path
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            out["problems"].append(f"{path.name} 读不出来（{type(exc).__name__}: {exc}）")
            continue

        lines = raw.splitlines(keepends=True)
        changed = 0
        pending_changed = 0
        bad = False
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(row, dict):
                continue
            row_sid = str(row.get("stmt_id") or row.get("statement_id") or "")
            row_sha = str(row.get("proof_sha256") or "").strip().lower()
            row_rel = str(row.get("manuscript") or row.get("object_path") or "").strip()
            if not ((sha and row_sha == sha) or (rel and row_rel == rel)):
                continue
            if row_sid and row_sid != sid:
                out["problems"].append(
                    f"{path.name} 有一行属于 stmt:{row_sid}（不是 stmt:{sid}）⇒ 不回写")
                bad = True
                continue
            current = row.get("path_group")
            try:
                current_no = int(current) if current not in (None, "") else 0
            except (TypeError, ValueError):
                current_no = 0
            if current_no == group:
                continue
            if current_no >= 1:
                out["problems"].append(
                    f"{path.name} 的 {row.get('verification_id') or '一行'} 已有路径号 "
                    f"{current_no}（不是 {group}）⇒ 不覆盖")
                bad = True
                continue
            row["path_group"] = group
            lines[i] = json.dumps(row, ensure_ascii=False, default=str) + (
                "\n" if line.endswith("\n") else "")
            changed += 1
            if is_pending:
                pending_changed += 1
        if changed and not bad:
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                tmp.write_text("".join(lines), encoding="utf-8")
                tmp.replace(path)
            except OSError as exc:
                out["problems"].append(f"{path.name} 写不进去（{type(exc).__name__}: {exc}）")
                try:
                    tmp.unlink()
                except OSError:  # noqa: R001 —— 临时文件删不掉不改变"这笔没写成"的结论
                    pass
                continue
            out["stamped"] += changed
            out["pending_stamped"] += pending_changed
            out["files"].append(str(path))
        bad_any = bad_any or bad
    out["checked"] = not bad_any
    out["why"] = (
        f"回写了 {out['stamped']} 条 verification 行（路径号 {group}"
        + (f"，其中 pending 行 {out['pending_stamped']} 条" if out["pending_stamped"] else "")
        + "）"
        if not bad_any else "有行已有别的路径号 / 属于别的命题 ⇒ 没有覆盖")
    return out



