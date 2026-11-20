# -*- coding: utf-8 -*-
"""秘书的读写面池（一槽一主，从 secretary.py 的 U07 逐字搬出）。

我保证哪条不变式：一槽一主；退役即归还（槽位与号一起释放，不许留一个没有主的槽）。

## 为什么它能单独成文件（依赖方向）

`secretary_surface` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_surface` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    _roster_guarded,
    append_jsonl,
    archive_dir,
    surface_dir,
    surfaces_path,
)

from .secretary_outbound import (  # noqa: F401 — 这些名字由 secretary_outbound 定义
    reach_fit,
)

from .secretary_time import (  # noqa: F401 — 这些名字由 secretary_time 定义
    _now_iso,
)


class SurfaceMixin:
    """读写面池（一槽一主）（从 secretary.py 搬出的混入类）。"""

    # ---- 读写面与槽位池（S1n）
    def surface_rows(self, owner: str) -> tuple[list[dict[str, Any]], list[str]]:
        """池的折叠视图（`(槽位列表, 坏行)`）。"""
        from . import jsonlfile as JF

        rows, bad = JF.read_jsonl(surfaces_path(self.root, owner))
        return _fold_surfaces(rows), bad

    def surface_state(self, owner: str) -> dict[str, Any]:
        """池的三态读数：`{"checked","in_use":[{slot,name}],"free":[…],"pending_release":[…],"reason"}`。

        读不成 ⇒ `checked=False`（不许返回空池冒充"都空闲"）。
        """
        try:
            rows, bad = self.surface_rows(owner)
        except Exception as exc:  # noqa: BLE001
            return {"checked": False, "in_use": [], "free": [], "pending_release": [],
                    "reason": f"{type(exc).__name__}: {exc}"}
        if bad:
            return {"checked": False, "in_use": [], "free": [], "pending_release": [],
                    "reason": f"池事件有 {len(bad)} 行读不出来：{bad[0]}"}
        return {"checked": True,
                "in_use": [{"slot": r["slot"], "name": r["name"]} for r in rows
                           if r["state"] == "在用"],
                "free": [r["slot"] for r in rows if r["state"] == "空闲"],
                "pending_release": [{"slot": r["slot"], "name": r["name"],
                                     "reason": r.get("reason", "")} for r in rows
                                    if r["state"] == "待释放"],
                "reason": ""}

    @_roster_guarded
    def surface_alloc(self, *, owner: str, want: str = "", name: str = "") -> dict[str, Any]:
        """从池里取一个干净的槽位给 `name` 用（派活那一刻，与 `roster_add` 同一趟）。

        - `want` 给了 ⇒ 要求它是空闲的（在用 / 待释放 ⇒ 受控拒绝，不静默换一个）；
        - 没给 ⇒ 取"空闲里最小的"；池里没有空闲 ⇒ 新建一个（`S<两位数>`，序号只增不减）；
        - 返回 `{"slot","path","problem"}`；拿不到 ⇒ `problem` 非空（调用方按受控拒绝处理）。
        """
        state = self.surface_state(owner)
        if not state.get("checked"):
            return {"slot": "", "path": "", "problem": f"池没读成（{state.get('reason')}）"}
        in_use = {str(x["slot"]) for x in state["in_use"]}
        pend = {str(x["slot"]) for x in state["pending_release"]}
        if want:
            slot = str(want)
            if slot in in_use or slot in pend:
                return {"slot": slot, "path": "",
                        "problem": f"槽位 {slot} 不在空闲池里（在用或待释放）⇒ 受控拒绝"}
        else:
            free = sorted(state["free"])
            if free:
                slot = free[0]
            else:
                used = in_use | pend | {str(x) for x in state["free"]}
                n = 1
                while f"S{n:02d}" in used:
                    n += 1
                slot = f"S{n:02d}"
        path = surface_dir(self.root, owner, slot)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"slot": slot, "path": "", "problem": f"面建不出来：{type(exc).__name__}: {exc}"}
        ok, why = append_jsonl(surfaces_path(self.root, owner),
                               {"kind": "alloc", "owner": owner, "slot": slot,
                                "name": str(name), "at": _now_iso()})
        if not ok:
            return {"slot": slot, "path": str(path), "problem": f"池事件没写成：{why}"}
        return {"slot": slot, "path": str(path), "problem": ""}

    @_roster_guarded
    def surface_release(self, *, owner: str, name: str, slot: str) -> tuple[str, str]:
        """归还一个槽位：先归档面里的东西，再写 `release`；归档失败 ⇒ `archive_failed`
        （槽位停在"待释放"、不入池）。返回 `(落成的状态, 问题)`。"""
        src = surface_dir(self.root, owner, slot)
        dst = archive_dir(self.root, owner, name)
        state = "空闲"
        if src.is_dir() and any(src.iterdir()):
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    import shutil

                    shutil.rmtree(dst)
                import shutil

                shutil.move(str(src), str(dst))
                src.mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # noqa: BLE001 —— 没归档干净就不许放回池
                state, why = "待释放", f"{type(exc).__name__}: {exc}"
                append_jsonl(surfaces_path(self.root, owner),
                             {"kind": "archive_failed", "owner": owner, "slot": slot,
                              "name": str(name), "reason": why, "at": _now_iso()})
                return state, why
        ok, why2 = append_jsonl(surfaces_path(self.root, owner),
                                {"kind": "release", "owner": owner, "slot": slot,
                                 "name": str(name), "at": _now_iso()})
        if not ok:
            return "待释放", f"池事件没写成：{why2}"
        return state, ""

    def surface_of(self, *, owner: str, task_id: str) -> dict[str, Any]:
        """某个调用行「此刻」该用的读写面：`{"checked","name","slot","path","reason"}`。

        为什么必须两步查（实测踩过）：`task_id` 的当前值在对照表里（`_fold_index`
        认 `bind`），而名册的 `add` 行记的是第一次那个调用 ⇒ 只读名册会把
        "复用过的名字"（`draft/92` I-12）判成"这一行没有面"，于是那一趟静默不切面。
        顺序：对照表 `task_id → name`，再名册 `name → surface`。

        已退役 ⇒ `checked=False`：退役时槽位已经归还池里，可能已经分给别人了，
        照旧读出那个槽位就等于让两个人的面重叠（跨代理写同一份文件）。
        读不成一律 `checked=False`（调用方按"没切面"处理，不许假装切过）。
        """
        name, why = self.name_of(owner=owner, task_id=str(task_id))
        if not name:
            return {"checked": False, "name": "", "slot": "", "path": "",
                    "reason": why or f"对照表里没有 {task_id!r}"}
        rows, bad = self.roster_rows(owner)
        if bad:
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"名册有 {len(bad)} 行读不出来：{bad[0]}"}
        item = next((r for r in rows if str(r.get("name") or "") == name), None)
        if item is None:
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"名册里没有 {name}（对照表里有 ⇒ 半份登记）"}
        if item.get("retired"):
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"{name} 已退役 ⇒ 面已归还池里（不照旧读，免得与别人重叠）"}
        slot = str(item.get("surface") or "")
        if not slot:
            return {"checked": False, "name": name, "slot": "", "path": "",
                    "reason": f"{name} 名下没登记读写面（老项或补登记）"}
        return {"checked": True, "name": name, "slot": slot,
                "path": str(surface_dir(self.root, owner, slot)), "reason": ""}

    # ------------------------------------------------------------ 面适配（S1g-2）
    def surface_fit(self, *, action: str, params: Mapping[str, Any],
                    face: str = "", base: str = "") -> dict[str, Any]:
        """这件活落在被派人的读写面里做不做得成（三态读数，只报不改）。

        「"超越职责"的一个主要可能是无法在被分配的读写面内完成任务，这个秘书也要帮忙看，
        不只是看任务是否符合角色设计」。
        ## 判什么：只判声明里给出的盘上路径（参数名由 :func:`surface_path_args` 一处给出，与执行期硬拦同一张表）。
        逐条给"这一句话在两边的所指是不是同一个文件"：
        | `verdict` | 判据 | 意思 |
        |---|---|---|
        | `escapes` | 解析结果落在面外 | 越界：面内做不成 |
        | `in_face` | 解析结果在面里（面已知时才给这一档） | 做得到 |
        | `not_in_face` | 父视角那一份（`base/<raw>`）盘上有，而面内那一份盘上没有 | 错位：同一句路径在两边不是同一个文件 |
        | `unknown` | 面未定 / 盘上两边都没有 / 解析不了 | 判不了（不许折成 in_face） |
        ## 为什么 `not_in_face` 不需要知道槽位：新起一个子代理时槽位还没分（`surface_alloc` 与 `roster_add` 同一趟），
        所以"落点在这一族的面里的哪一格"判不了。但 `escapes` 与 `not_in_face` 两档的判据是"两份所指不是同一个
        文件"，与槽位无关 —— 它们正是"面内做不成"的主体，于是这条读数在派活那一刻就有用。
        ## 为什么只报不改：路径值是内容面：把它改写成另一条路径 = 替父决定"这件事
        该在哪儿做"。秘书的活是把它变成看得见的事，处置权在父。参数：`face` 收件方这趟的面（`surface_of` 读得出）；
        `base` 本实例自己的根（父视角的基准）—— 不给 ⇒ 用 `self.root`（顶层那一趟两者相同；子代理那一趟它自己的
        根是它的面，调用方要传进来）。
        """
        out: dict[str, Any] = {"checked": False, "fits": None, "paths": [],
                               "reason": ""}
        names = surface_path_args(action)
        if not names:
            out["reason"] = (f"{action or '（没给动作）'} 不是 fs 动作 ⇒ 面这一维不适用"
                             "（不适用不是通过）")
            return out
        try:
            root = Path(str(base or self.root))
            face_dir = Path(str(face)).resolve() if str(face or "") else None
        except Exception as exc:  # noqa: BLE001 —— 读不成 ⇒ 判不了（不是"没问题"）
            out["reason"] = f"面/基准读不成（{type(exc).__name__}: {exc}）⇒ 判不了"
            out["checked"] = True
            return out
        given = params or {}
        rows: list[dict[str, Any]] = []
        # 判定与坏路径名单同趟收：原先 rows 建好后再扫两遍（verdicts 一遍、bad 一遍）。
        verdicts: set[str] = set()
        bad: list[dict[str, Any]] = []
        for key in names:
            raw = given.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue                       # 没给这一格 ⇒ 没有可判的路径（如实记在 reason 里）
            row = self._judge_one_path(key, raw.strip(), root=root, face_dir=face_dir)
            verdict = str(row.get("verdict") or "")
            rows.append(row)
            verdicts.add(verdict)
            if verdict in ("escapes", "not_in_face"):
                bad.append(row)
        if not rows:
            out.update(checked=True,
                       reason=f"{action} 这一件没给路径参数（{'/'.join(names)}）⇒ 判不了"
                              "（不是通过）")
            return out
        fits: bool | None
        if verdicts & {"escapes", "not_in_face"}:
            fits = False
        elif verdicts == {"in_face"}:
            fits = True
        else:
            fits = None                        # 全是 unknown ⇒ 判不了（三态不许折平）
        reason = ""
        if fits is False:
            reason = "；".join(
                f"{r['where']}={r['value']!r} {r['why']}" for r in bad)
        elif fits is None:
            reason = "；".join(str(r.get("why") or "") for r in rows) or "没有可判的路径 ⇒ 判不了"
        out.update(checked=True, fits=fits, paths=rows, reason=reason)
        return out

    def _judge_one_path(self, where: str, raw: str, *, root: Path,
                        face_dir: Path | None) -> dict[str, Any]:
        """一条路径的判决（纯计算；`surface_fit` 的逐条那一半）。

        分两种情形（`face_dir` 有没有给），判据都只有一条：这一句话在两边指的是不是
        同一个文件。
        """
        row: dict[str, Any] = {"where": where, "value": raw, "face": "", "ws": "",
                               "face_exists": None, "ws_exists": None,
                               "verdict": "unknown", "why": ""}
        try:
            p = Path(raw)
            ws_path = (p if p.is_absolute() else (root / raw)).resolve()
        except Exception as exc:  # noqa: BLE001 —— 解析不了 ⇒ unknown（不许猜）
            row["why"] = f"路径解析不了（{type(exc).__name__}: {exc}）"
            return row
        row["ws"] = str(ws_path)
        if face_dir is not None:
            try:
                face_path = (p if p.is_absolute() else (face_dir / raw)).resolve()
            except Exception as exc:  # noqa: BLE001
                row["face"] = str(face_dir)
                row["why"] = f"面内落点算不出来（{type(exc).__name__}: {exc}）"
                return row
            row["face"] = str(face_path)
            row["face_exists"] = bool(face_path.exists())
            row["ws_exists"] = bool(ws_path.exists())
            try:
                face_path.relative_to(face_dir)
            except ValueError:
                row["verdict"] = "escapes"
                row["why"] = "越出了收件方这趟的读写面（面外一律不做）"
                return row
            if row["face_exists"] or face_path == ws_path:
                # 面里就有这一份（父已经把它切进面了），或两边算出来是同一个文件
                # ⇒ 做得到。面内的新文件也走这一档（T23："若子代理想新写文件，
                # 这个是允许的"）—— 见下面"两边都没有"那一格。
                row["verdict"] = "in_face"
                row["why"] = "落在面内（面内的新文件本来就允许）"
                return row
            if row["ws_exists"]:
                # 父视角那一份在工作区里（父指的就是它），而面内的落点不是同一个
                # 文件、且面里没有这一份 ⇒ 子在它那边找的是另一条路径：错位。
                row["verdict"] = "not_in_face"
                row["why"] = ("这一份在工作区里（父的视角指得到它），而收件方那趟的根是"
                              "它的面 ⇒ 子在它那边找的是另一条路径：面内做不成（要么把"
                              "这一份切进它的面，要么这一件就是『职责之外』那一档）")
                return row
            row["verdict"] = "unknown"
            row["why"] = ("两边都没有这一份 ⇒ 判不了（面内新建是允许的；若父要的是工作区"
                          "那一份，它现在还不存在）")
            return row
        # ---- 面未定（新起一个子代理）：判"父视角那一份在不在面可能覆盖的范围内"
        family = (root / "out" / "surfaces" / str(self.task_id or "")).resolve()
        try:
            ws_path.relative_to(root.resolve())
            in_workspace = True
        except ValueError:
            in_workspace = False
        row["ws_exists"] = bool(ws_path.exists())
        if not in_workspace:
            row["verdict"] = "escapes"
            row["why"] = ("落点在整个工作区之外（面是工作区里的一个子目录）⇒ 面内做不成")
            return row
        try:
            ws_path.relative_to(family)
            in_family = True
        except ValueError:
            in_family = False
        if in_family:
            row["verdict"] = "unknown"
            row["why"] = ("落点在这一族的面里，但槽位要到派活那一刻才分 ⇒ 判不了"
                          "（不是通过）")
            return row
        if row["ws_exists"]:
            row["verdict"] = "not_in_face"
            row["why"] = ("这一份在工作区里（父的视角指得到它），而收件方那趟的根是它的面"
                          "⇒ 子在它那边找的是另一条路径：面内做不成（要么把这一份切进它的"
                          "面，要么这一件就是『职责之外』那一档）")
            return row
        row["verdict"] = "unknown"
        row["why"] = "盘上没有这一份、也不在这一族的面里 ⇒ 判不了（新文件本来就允许）"
        return row

    def surface_readings(self, shape: str, payload: Mapping[str, Any],
                         *, face: str = "", base: str = "") -> dict[str, Any]:
        """派活形状 → 面适配读数（`summon` 一条；`summon_many` 逐项）。

        不派活的形状（`handoff` / `message` / `retire` / `roster`）⇒ 这一维不适用，
        如实说清（不适用不是通过）。
        """
        try:
            if shape == "summon":
                role = str(payload.get("role") or "")
                action = str(payload.get("action") or "")
                raw_params = payload.get("params")
                got = self.surface_fit(action=action,
                                       params=(raw_params
                                               if isinstance(raw_params, Mapping) else {}),
                                       face=face, base=base)
                # 能力面那一维（业主 2026-10-14）：这个动作被派人（连同它出边上的伙伴）
                # 做不做得成。与路径面各判一维，两条一起给父看。
                return {**got, "shape": shape, "reach": reach_fit(role, action)}
            if shape == "summon_many":
                targets = payload.get("targets")
                if not isinstance(targets, (list, tuple)):
                    return {"shape": shape, "checked": False, "fits": None, "items": [],
                            "reason": "targets 不是数组 ⇒ 面这一维判不了"}
                items = []
                # 汇总与两张名单同趟收（原先同一批 items 扫四遍）：有 False ⇒ False；
                # 非空且没有"不是 True" ⇒ True；其余 ⇒ None —— 三态照旧保留。
                bad: list[dict[str, Any]] = []
                reach_bad: list[dict[str, Any]] = []
                saw_false = saw_not_true = False
                for i, item in enumerate(targets):
                    sub = item if isinstance(item, Mapping) else {}
                    action = str(sub.get("action") or "")
                    raw_params = sub.get("params")
                    fit = self.surface_fit(
                        action=action,
                        params=(raw_params if isinstance(raw_params, Mapping) else {}),
                        face=face, base=base)
                    reach = reach_fit(str(sub.get("role") or ""), action)
                    row = {"index": i, **fit, "reach": reach}
                    items.append(row)
                    if fit.get("fits") is False:
                        saw_false = True
                        bad.append(row)
                    elif fit.get("fits") is not True:
                        saw_not_true = True
                    # 能力面那一维的汇总：哪几项在"被派人 + 它出边上的伙伴"里没人做得到
                    if (reach or {}).get("verdict") == "unreachable":
                        reach_bad.append(row)
                fits: bool | None
                if saw_false:
                    fits = False
                elif items and not saw_not_true:
                    fits = True
                else:
                    fits = None
                return {"shape": shape, "checked": True, "fits": fits, "items": items,
                        "reach_bad": [x["index"] for x in reach_bad],
                        "reason": "；".join(f"targets[{x['index']}]：{x.get('reason')}"
                                            for x in bad),
                        "reach_reason": "；".join(
                            f"targets[{x['index']}]：{(x.get('reach') or {}).get('reason')}"
                            for x in reach_bad)}
        except Exception as exc:  # noqa: BLE001 —— 面这一维没查成不许打断派活
            return {"shape": shape, "checked": False, "fits": None,
                    "reason": f"面适配没跑成（{type(exc).__name__}: {exc}）"}
        return {"shape": shape, "checked": False, "fits": None,
                "reason": f"{shape} 不派活 ⇒ 面这一维不适用（不适用不是通过）"}

    def _face_of_name(self, *, owner: str, name: str) -> str:
        """名册名 → 它此刻的面目录（读不成 / 已退役 / 没登记 ⇒ 空串 + 不假装查过）。"""
        want = str(name or "")
        if not want:
            return ""
        try:
            rows, bad = self.roster_rows(owner)
            if bad:
                return ""
            item = next((r for r in rows if str(r.get("name") or "") == want), None)
            if item is None or item.get("retired"):
                return ""
            slot = str(item.get("surface") or "")
            if not slot:
                return ""
            return str(surface_dir(self.root, owner, slot))
        except Exception:  # noqa: BLE001
            return ""


#: 哪些工具的哪些参数是"落在盘上的路径"（`draft/90` §1.11 / §2 的 E22）。
#:
#: 默认规则：`fs.*` 的 `path`。名字不叫 `path` 的逐条登记在这里 —— 今天只有
#: `fs.move`（它的 schema 是 `{'src','dst'}`，没有 `path`，于是它在 S1n-b 的硬拦里
#: 整个漏掉了：子代理可以用它把面外的文件搬进自己的面）。
#:
#: 这张表只有一处，两个时机共用：预看（`Secretary.surface_fit`）与硬拦
#: （`AgentLoop._surface_refusal`）。分两份写迟早出现"预看说越界、硬拦放过去"
#: 这种自相矛盾，而两边的判据都会是绿的。
SURFACE_PATH_ARGS: dict[str, tuple[str, ...]] = {"fs.move": ("src", "dst")}


def surface_path_args(action: str) -> tuple[str, ...]:
    """某个工具/动作里"是路径"的那几个参数名（空元组 = 这个动作没有可判的盘上路径）。

    读不到名字（空串）⇒ 空元组；非 `fs.` 的动作一律空元组（面这一维今天只说 `fs.*`，
    与 `AgentLoop._surface_refusal` 同一条范围）。
    """
    name = str(action or "")
    if not name.startswith("fs."):
        return ()
    return ("path",) + tuple(SURFACE_PATH_ARGS.get(name, ()))


def _fold_surfaces(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把池事件流折叠成"每个槽位此刻在哪一档"（空闲 / 在用 / 待释放）。"""
    items: dict[str, dict[str, Any]] = {}
    for raw in rows:
        r = dict(raw)
        slot = str(r.get("slot") or "")
        if not slot:
            continue
        item = items.setdefault(slot, {"slot": slot, "name": "", "state": "空闲"})
        kind = str(r.get("kind") or "")
        if kind == "alloc":
            item["name"] = str(r.get("name") or "")
            item["state"] = "在用"
        elif kind == "release":
            item["name"] = ""
            item["state"] = "空闲"
            item.pop("reason", None)
        elif kind == "archive_failed":
            item["name"] = str(r.get("name") or "")
            item["state"] = "待释放"
            item["reason"] = str(r.get("reason") or "")
    return [items[k] for k in sorted(items)]
