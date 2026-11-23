"""`check_closing_gate` —— 对一个工作区现算八格收工门，只读、零模型调用。

用法：

```
python scripts/check_closing_gate.py --workspace projects/lp-ball-15
python scripts/check_closing_gate.py --workspace projects/lp-ball-15 --json
python scripts/check_closing_gate.py --workspace projects/lp-ball-15 --sid 2026-11-21b
python scripts/check_closing_gate.py --selftest
```

退出码（与 `agentflow closing` 同一条口径，由 `closing.tri_state_exit_code` 给）：

- `0` = 可交付：八格没有 fail / unknown 格、至少一格判过且 pass、`m_says_done`、
  `retire.complete`、程序都停了、没有 blocker；
- `1` = 被拦住：有格 fail / 有 blocker / M 自己说没做完 / retire 不干净 / 程序没停；
- `2` = 没查成：工作区不在、import 不到 `agentflow`、门受控拒绝（会话号不在盘上）、
  或任一格 `unknown`（读不到台账就等于没判过）。

## 为什么不在这里写判据

八格的判据、四态（`pass` / `fail` / `unknown` / `na`）、机器口径（`m_says_done` ∧
`retire.complete` ∧ `programs_ok`）与"唯一一份权威结论"都在
`src/agentflow/closing.py` 里（`check_closing` 现算、`closing_verdict` 出结论）。
本脚本只做三件事：打开工作区、把机器口径的两个喂参喂进去、把那一份结论原样打出来。
重写一份八格就是再造一个"这一趟能不能交"的判据 —— 2026-11-19 的 ROOTGATE-① 正是
为了消灭第二个结论而做的。

## 只读

不写任何表、不建索引（`agentflow closing` 的 `index/run-index.json` 那一步在 CLI 里，
不在 `check_closing` 里）。跑一趟只读盘。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROG = "check_closing_gate"

EXIT_OK = 0
EXIT_BAD = 1
EXIT_UNKNOWN = 2


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码（GBK 重定向会把"发现问题"打印成进程失败）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _product_root() -> Path:
    """本脚本所属的产品根（`scripts/` 的上一级）。"""
    return Path(__file__).resolve().parents[1]


def load_closing(root: Path):
    """从目标根的 `src/` 里导入 `agentflow.closing` 与 `agentflow.store`。

    返回 `(closing 模块, Store 类, 没查成的理由)`：理由非空时前两项是 `None`。
    为什么要求 import 到的包真的在目标根下：本机可能另有一份 `agentflow`
    （可编辑安装 / PYTHONPATH），拿别的树的判据去判这一棵的盘，结论是假的。
    """
    src = Path(root) / "src"
    if not (src / "agentflow" / "closing.py").is_file():
        return None, None, (f"读不到 {src / 'agentflow' / 'closing.py'}"
                            "（八格的判据本体）⇒ 没查成。本脚本刻意不重写判据")
    sys.path.insert(0, str(src))
    try:
        from agentflow import closing as CL  # noqa: PLC0415 - 必须在改过 sys.path 之后
        from agentflow.store import Store  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - 导入失败就是"没查成"
        return None, None, f"导入 agentflow 失败：{type(exc).__name__}: {exc} ⇒ 没查成"
    where = Path(getattr(CL, "__file__", "") or "").resolve()
    try:
        where.relative_to(Path(root).resolve())
    except ValueError:
        return None, None, (f"import 到的 agentflow 是 {where}，不在 {Path(root).resolve()} 下"
                            " ⇒ 判据不是这一棵树的，没查成")
    return CL, Store, ""


def _verdict_payload(rep) -> dict:
    """把 `ClosingReport` 的那一份权威结论取成纯数据（失败时如实留一句，不抛）。"""
    try:
        got = rep.verdict
    except Exception as exc:  # noqa: BLE001 - 结论本身算不出来 = 没查成
        return {"verdict": "unknown", "exit_code": EXIT_UNKNOWN,
                "reason": f"closing_verdict 自己抛了：{type(exc).__name__}: {exc}",
                "cells": [], "counts": {}, "blockers": []}
    return dict(got or {})


def run(workspace: Path | str, *, root: Path | str | None = None,
        project_dir: str = ".", report: str = "", sid: str | None = None,
        goal: str = "", goal_met: bool | None = None, basis: str = "") -> tuple[int, dict]:
    """跑一遍八格并给出 `(退出码, 读数)`。任何"没跑成"都落 2。"""
    ws = Path(workspace).expanduser().resolve()
    product = Path(root).expanduser().resolve() if root else _product_root()
    payload: dict = {
        "script": PROG,
        "workspace": str(ws),
        "product_root": str(product),
        "project_dir": project_dir,
        "report": report,
        "sid": sid if sid is not None else "",
        "verdict": {},
        "cells": [],
        "counts": {},
        "blockers": [],
        "machine": {},
        "reason": "",
        "state": "unknown",
        "exit_code": EXIT_UNKNOWN,
    }
    if not ws.is_dir():
        payload["reason"] = (f"工作区不在：{ws} ⇒ 没查成（不是「八格都过」，"
                             "也不是「被拦住」）")
        return EXIT_UNKNOWN, payload

    CL, Store, why = load_closing(product)
    if CL is None:
        payload["reason"] = why
        return EXIT_UNKNOWN, payload

    try:
        store = Store(ws)
    except Exception as exc:  # noqa: BLE001
        payload["reason"] = f"打不开工作区台账：{type(exc).__name__}: {exc} ⇒ 没查成"
        return EXIT_UNKNOWN, payload

    # 机器口径的两个喂参（`retire` / `programs`）：与运行内 `conductor.closing`、
    # 运行外 `agentflow closing` 走同一个 `machine_feeders`。喂不上就是 None，
    # 结论会如实落 `not_wired`（不是"通过"）。
    feed: dict = {"retire": None, "programs": None}
    try:
        feed = dict(CL.machine_feeders(store) or {})
    except Exception as exc:  # noqa: BLE001 - 喂参读不出来只丢这一格，不动八格现算
        payload["machine_feed_error"] = f"{type(exc).__name__}: {exc}"

    report_path = str(report or "")
    if not report_path and str(project_dir or "").strip():
        resolved = CL.resolve_under_workspace(store, project_dir)
        candidate = Path(resolved) / "out" / "report" / "REPORT.md"
        if candidate.is_file():
            report_path = str(candidate)

    try:
        rep = CL.check_closing(store, project_dir=str(project_dir or ""),
                               report_path=report_path, sid=sid,
                               retire=feed.get("retire"), programs=feed.get("programs"),
                               goal=str(goal or ""), goal_met=goal_met,
                               basis=str(basis or ""))
    except Exception as exc:  # noqa: BLE001 - 门自己抛了 = 没查成，不许折成 fail
        payload["reason"] = f"check_closing 自己抛了：{type(exc).__name__}: {exc} ⇒ 没查成"
        return EXIT_UNKNOWN, payload

    verdict = _verdict_payload(rep)
    payload["verdict"] = verdict
    payload["cells"] = list(verdict.get("cells") or ())
    payload["counts"] = dict(verdict.get("counts") or {})
    payload["blockers"] = list(verdict.get("blockers") or ())
    payload["machine"] = {"m_says_done": bool(verdict.get("m_says_done")),
                          "retire": dict(verdict.get("retire") or {}),
                          "programs": dict(verdict.get("programs") or {}),
                          "machine_pass": bool(verdict.get("machine_pass")),
                          "can_close": verdict.get("can_close"),
                          "authoritative": bool(verdict.get("authoritative"))}
    payload["session"] = dict((getattr(rep, "readings", {}) or {}).get("session") or {})
    payload["refusal"] = rep.refusal if getattr(rep, "refusal", None) else None
    payload["report_used"] = report_path
    payload["status"] = dict(getattr(rep, "status", None) or {})
    payload["full_gate"] = bool(getattr(rep, "full_gate", False))

    try:
        code = int(CL.tri_state_exit_code(rep))
    except Exception as exc:  # noqa: BLE001
        payload["reason"] = f"tri_state_exit_code 自己抛了：{type(exc).__name__}: {exc} ⇒ 没查成"
        return EXIT_UNKNOWN, payload
    payload["exit_code"] = code
    payload["state"] = {0: "pass", 1: "fail", 2: "unknown"}.get(code, "unknown")
    payload["reason"] = str(verdict.get("reason") or "")
    if payload.get("refusal"):
        payload["reason"] = (f"门没跑（受控拒绝：{payload['refusal'].get('code')}）："
                             f"{payload['refusal'].get('detail')}")
    return code, payload


def render_text(payload: dict) -> str:
    """人读版：先给三态与结论，再逐格，再机器口径与 blocker。"""
    lines = [f"工作区 {payload['workspace']}",
             f"三态   state={payload['state']}  exit={payload['exit_code']}"]
    v = payload.get("verdict") or {}
    counts = payload.get("counts") or {}
    if counts:
        lines.append(f"八格   pass {counts.get('pass', 0)} / fail {counts.get('fail', 0)} / "
                     f"unknown {counts.get('unknown', 0)} / na {counts.get('na', 0)}")
    if v:
        lines.append(f"结论   verdict={v.get('verdict')}  can_close={v.get('can_close')}  "
                     f"machine_pass={v.get('machine_pass')}  "
                     f"authoritative={payload['machine'].get('authoritative')}")
        lines.append(f"判据   M 自己说达成={payload['machine'].get('m_says_done')}"
                     f"（M 没提交判据时这一栏是 False 且结论必为 unknown）")
        lines.append(f"落位   project_dir={payload['project_dir']!r}  "
                     f"report={payload.get('report_used') or '（没给、盘上也没有）'}")
    session = payload.get("session") or {}
    if session.get("note"):
        lines.append(f"会话   {session['note']}")

    cells = payload.get("cells") or []
    if cells:
        lines.append("")
        lines.append("逐格：")
        for cell in cells:
            why = str(cell.get("why") or "").replace("\n", " ")
            lines.append(f"  [{cell.get('status')}] {cell.get('check')}"
                         + (f"  —— {why[:400]}" if why else ""))

    machine = payload.get("machine") or {}
    retire = dict(machine.get("retire") or {})
    programs = dict(machine.get("programs") or {})
    if retire or programs:
        lines.append("")
        lines.append("机器口径：")
        lines.append(f"  retire   checked={retire.get('checked')} complete={retire.get('complete')} "
                     f"state={retire.get('state')}"
                     + (f"  reason={str(retire.get('reason'))[:300]}" if retire.get("reason") else ""))
        auto = dict(retire.get("auto_retire") or {})
        if auto.get("would_retire") or auto.get("would_void"):
            lines.append(f"          收尾前会自动销号 {len(auto.get('would_retire') or [])} 个节点、"
                         f"作废 {len(auto.get('would_void') or [])} 条通知")
        lines.append(f"  programs checked={programs.get('checked')} ok={programs.get('ok')} "
                     f"running={programs.get('running_count')} unowned={programs.get('unowned_count')}"
                     + (f"  reason={str(programs.get('reason'))[:300]}" if programs.get("reason") else ""))
    if payload.get("machine_feed_error"):
        lines.append(f"  （喂参读数没查成：{payload['machine_feed_error']}）")

    blockers = payload.get("blockers") or []
    if blockers:
        lines.append("")
        lines.append(f"blocker（{len(blockers)} 条）：")
        for one in blockers:
            lines.append(f"  {one.get('check')} · {one.get('code')}：{str(one.get('why'))[:400]}")

    lines.append("")
    lines.append({0: "结论：可交付（0）",
                  1: "结论：被拦住（1）—— 逐格见上",
                  2: "结论：没查成（2）—— 0 不是「可交付」"}[payload["exit_code"]])
    lines.append(f"理由：{payload['reason'] or '（门没给原因）'}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 自测
def _fixture_report(CL, *, unknown_cell: str = "", fail_cell: str = "",
                    met: bool = True, retire_complete: bool = True,
                    programs_ok: bool = True):
    """造一份八格读数（`ClosingReport`）：夹具是"判据对象"的夹具，不是工作区的夹具。

    为什么不去造一个"八格全过的真工作区"：那需要一份真交付（齐的台账、报告、验收表、
    会话记录、销号干净的树），而那份东西正是本工具要查的对象 —— 造它等于先做一遍
    这一趟活。`closing_verdict` 是这份判据的唯一入口，直接喂它一份读数就能把三态
    映射测清楚，而且测的是真判据、不是替身。
    """
    rep = CL.ClosingReport()
    status = {name: "pass" for name in CL.DEFAULT_CHECKS}
    if unknown_cell:
        status[unknown_cell] = "unknown"
    if fail_cell:
        status[fail_cell] = "fail"
    rep.status = status
    rep.full_gate = True
    rep.authoritative = True
    rep.m_verdict = {"goal": "夹具目标", "met": bool(met), "basis": "夹具依据",
                     "at": "2026-11-22T00:00:00+08:00"}
    retire = {"checked": True, "complete": bool(retire_complete), "projected": False,
              "state": "干净" if retire_complete else "不干净",
              "reason": "" if retire_complete else "夹具：名下还有在册节点",
              "auto_retire": {}}
    programs = {"checked": True, "ok": bool(programs_ok),
                "running_count": 0 if programs_ok else 2,
                "unowned": [], "reason": "" if programs_ok else "夹具：还有程序在跑"}
    rep.readings["machine_caliber"] = CL.machine_caliber(
        m_says_done=bool(met), retire=retire, programs=programs)
    return rep


def selftest() -> int:
    """三条自测：通过 / 失败 / 没查成（外加"工作区不在"那条文件系统路径）。"""
    _CL, _Store, why = load_closing(_product_root())
    if _CL is None:
        print(f"自测没跑成：{why}")
        return EXIT_UNKNOWN
    rows: list[tuple[str, str, int, int]] = []
    cases = (
        ("通过", "八格全 pass + m_says_done + retire 干净", {}, EXIT_OK),
        ("失败", f"{_CL.DEFAULT_CHECKS[0]} 一格 fail", {"fail_cell": _CL.DEFAULT_CHECKS[0]}, EXIT_BAD),
        ("没查成", f"{_CL.DEFAULT_CHECKS[-1]} 一格 unknown",
         {"unknown_cell": _CL.DEFAULT_CHECKS[-1]}, EXIT_UNKNOWN),
    )
    for kind, detail, kwargs, want in cases:
        rep = _fixture_report(_CL, **kwargs)
        got = int(_CL.tri_state_exit_code(rep))
        rows.append((kind, detail, want, got))
    # 第四条：文件系统路径 —— 工作区不在 ⇒ 2（这条不碰判据，只碰入口）
    code, _payload = run(Path(_product_root()) / "no-such-workspace-here")
    rows.append(("没查成", "工作区不在", EXIT_UNKNOWN, code))

    print("自测（夹具是 ClosingReport 读数；判据是 agentflow.closing 的原函数，未重写）")
    bad = 0
    for kind, detail, want, got in rows:
        flag = "OK  " if want == got else "BAD "
        if want != got:
            bad += 1
        print(f"  [{flag}] {kind:4s} 期望 exit={want} 实际 exit={got}  （{detail}）")
    print(f"自测结论：{len(rows) - bad}/{len(rows)} 条符合期望")
    return EXIT_OK if not bad else EXIT_UNKNOWN


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数、跑八格、按三态返回退出码。"""
    _pin_utf8()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=("对一个工作区现算八格收工门（只读）："
                     "0 可交付 / 1 被拦住 / 2 没查成"),
        allow_abbrev=False,
    )
    parser.add_argument("--workspace", default="",
                        help="工作区根（必填，例如 projects/lp-ball-15）")
    parser.add_argument("--root", default=str(_product_root()),
                        help="产品根（缺省 = 本脚本的上一级；判据从它的 src/ 里导入）")
    parser.add_argument("--project-dir", default=".",
                        help="项目目录（工作区相对；缺省 `.` = 工作区根）")
    parser.add_argument("--report", default="",
                        help="报告路径（缺省由 project_dir 推 out/report/REPORT.md）")
    parser.add_argument("--sid", default=None,
                        help="会话号（不给 = 读缺省会话，运维口径；给了不在盘上 = 受控拒绝 2）")
    parser.add_argument("--goal", default="", help="M 的目标自述（可选）")
    parser.add_argument("--basis", default="", help="M 的判断依据自述（可选）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--goal-met", dest="goal_met", action="store_const", const=True,
                       help="代述 M 的判据：达成（缺省读盘上 out/report/m-verdicts.jsonl）")
    group.add_argument("--goal-not-met", dest="goal_met", action="store_const", const=False,
                       help="代述 M 的判据：没达成")
    parser.add_argument("--json", action="store_true", help="输出机器读数")
    parser.add_argument("--selftest", action="store_true",
                        help="自测三条（通过 / 失败 / 没查成）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    if not str(args.workspace or "").strip():
        print("必须给 --workspace <工作区根>（八格判的是「这一份交付」，没有工作区就没有可判对象）",
              file=sys.stderr)
        return EXIT_UNKNOWN

    code, payload = run(args.workspace, root=args.root, project_dir=args.project_dir,
                        report=args.report, sid=args.sid, goal=args.goal,
                        goal_met=args.goal_met, basis=args.basis)
    if args.json:
        try:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        except (TypeError, ValueError) as exc:  # pragma: no cover - 兜底，别让呈现变成崩
            print(f"读数打不出来（{type(exc).__name__}: {exc}）", file=sys.stderr)
            return EXIT_UNKNOWN
    else:
        print(render_text(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
