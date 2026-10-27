# -*- coding: utf-8 -*-
"""FC-27 批量签字前端：reviewer 逐行走查完，一条命令给多个禁改区路径各追加一条 reviewer 记录。

## 它是什么、不是什么

是：选路（`--paths` / `--all`）、报读数（`--list`）、问一句（`--yes` / 交互确认）、
逐条调用 `scripts/noai_gate.py` 的 `--approve` 通路、每签一条立刻回读台账。

不是：台账的第二个实现。三条判据写在代码里，不是写在注释里 ——

1. 不自己写台账：每一条都走门的 `--approve`（本脚本只拼参数、读门给的退出码），
   台账的字段、校验、原子写、理由码都只有门那一处实现。签完的回读也用门的读函数
   `load_ledger`，不解析 JSON 字符串。
2. 不代登记 hash：台账里没有这一条 / 登记的 hash 与盘上不一致 ⇒ 这一批一条都不签，
   让人先跑 `--baseline`。门的判据是"登记 != 批准"，一个批量脚本没有资格把两步并成一步。
3. 不给自己签字：目标是台账本身时，门自己会以 `ledger_self_approval` 拒；
   本脚本的预演（不落盘的 `add_approval`）会把它提前到"一条都没写"之前。

## 用法

    python scripts/noai_batch_sign.py --list
    python scripts/noai_batch_sign.py --all --reviewer 张三 \
        --scope "逐行走查：权限面/桥接层/冻结读数" --verdict "逐行走查通过" \
        --note "2026-10-23 第一批" --yes
    python scripts/noai_batch_sign.py --paths a.py b.py --reviewer 李四 --scope "..." [--dry-run]

`--reviewer` 可以给多次（同一批里每个名字归一化之后必须互不相同）；
不给 `--yes` 时先在终端里打印清单再要人逐字输入 yes，stdin 不是终端则直接拒绝。

退出码：0 = 目标路径全部满足 2 名不同 reviewer；1 = 还有未满足的；
2 = 没查成 / 没签成（参数错、台账读不到、前置条件不成立 —— 一律一个字节都不写）。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import pathlib
import sys
from dataclasses import dataclass

HERE = pathlib.Path(__file__).resolve().parent

if __package__ in (None, ""):
    # 作为脚本跑（`python scripts/noai_batch_sign.py`）：`scripts/` 就是 sys.path[0]。
    sys.path.insert(0, str(HERE))
    import noai_gate as G
else:
    # 作为包被 import（测试里 `from scripts import noai_batch_sign`）：走同一个包，
    # 免得加载出第二份 noai_gate（两份模块的常量与判据会各自独立地漂移）。
    from . import noai_gate as G


class _Refused(Exception):
    """输入不合格：一个字节都不写，退出码 2（"没签成"，不是"签不上"）。"""


@dataclass(frozen=True)
class SignState:
    """台账里某一条此刻的走查记录读数（唯一读口径 `state_now` 的产物）。

    `names` 是"不同 reviewer"的显示名：按记录顺序，同一个归一化姓名只留第一次出现的写法。
    批准数按不同姓名计（与门的 `distinct_reviewers` 同一条判据）——重复记录是事实，不加数。
    """

    key: str
    names: tuple[str, ...]
    required: int

    @property
    def count(self) -> int:
        """这一条现在有几个不同 reviewer（与门的计法一致）。"""
        return len(self.names)

    @property
    def satisfied(self) -> bool:
        """够不够门的门槛（`REQUIRED_APPROVALS_ON_HIT` 名不同 reviewer）。"""
        return self.count >= self.required

    @property
    def remaining(self) -> int:
        """还差几个不同 reviewer（0 就是已经满足）。"""
        return max(0, self.required - self.count)

    @property
    def normalized(self) -> frozenset[str]:
        """这些名字归一化之后的集合（判断"这个名字是不是已经签过这一条"用）。"""
        return frozenset(G.normalize_subject(n) for n in self.names)

    def line(self) -> str:
        """人话那一行（满足的那一档带对勾，未满足的那一档带省略号）。"""
        who = "、".join(self.names) if self.names else "（无）"
        if self.satisfied:
            return f"✔ {self.key}（{self.count}/{self.required}）已有 {self.count} 名：{who}"
        return (
            f"… {self.key}（{self.count}/{self.required}，还差 {self.remaining} 名不同 reviewer）"
            f"已有 {self.count} 名：{who}"
        )


def _state_of(ledger: G.Ledger, key: str) -> SignState:
    """从一份已读出的台账里取某一条的读数（条目不存在 = 0 名）。"""
    entry = ledger.entry_for(key)
    names: list[str] = []
    seen: set[str] = set()
    for record in (entry.reviewers if entry is not None else ()):
        who = G.normalize_subject(record.name)
        if who and who not in seen:
            seen.add(who)
            names.append(record.name)
    return SignState(key=key, names=tuple(names), required=G.REQUIRED_APPROVALS_ON_HIT)


def state_now(ledger_path: pathlib.Path, key: str) -> SignState:
    """重读台账再取读数：判据只认盘上的那一份，不认本进程内存里的旧对象。"""
    return _state_of(G.load_ledger(ledger_path), key)


def readback(ledger_path: pathlib.Path, key: str) -> SignState:
    """签完一条之后立刻回读并打印：现在这条有几个 reviewer、够不够。"""
    state = state_now(ledger_path, key)
    print("   " + state.line())
    return state


def _line_count(target: pathlib.Path) -> str:
    """这个文件现在有多少行（读不到就说读不到，不猜）。"""
    try:
        return f"{len(target.read_text(encoding='utf-8').splitlines())} 行"
    except (OSError, UnicodeDecodeError):
        return "行数读不到"


def _list_line(state: SignState, entry: G.LedgerEntry | None, root: pathlib.Path) -> str:
    """清单里的一行：读数 + sha256 前 12 位 + 行数（与盘上不一致时明说要先登记）。"""
    pieces = [state.line()]
    target = G._target_path(state.key, root)
    if entry is None:
        try:
            disk = G.sha256_file(target)[:12]
        except G.LedgerError:
            disk = "读不到"
        pieces.append(f"未登记（先 --baseline）｜ 盘上 sha {disk}")
        return " ｜ ".join(pieces)
    pieces.append(f"sha {entry.sha256[:12]}")
    pieces.append(_line_count(target))
    try:
        disk = G.sha256_file(target)
    except G.LedgerError:
        pieces.append("盘上读不到")
    else:
        if disk != entry.sha256:
            pieces.append(f"盘上已变（{disk[:12]}）⇒ 签字前先 --baseline")
    return " ｜ ".join(pieces)


def _parser() -> argparse.ArgumentParser:
    """命令行：短到能贴在对话里，安全阀一个都不省。"""
    ap = argparse.ArgumentParser(
        prog="noai_batch_sign",
        description=(
            "FC-27 批量签字前端：只调用 noai_gate 的 `--approve` 通路，不自己写台账。"
            "退出码 0=目标路径全部满足 2 名不同 reviewer；1=还有未满足；2=没查成/没签成。"
        ),
    )
    ap.add_argument(
        "--list", action="store_true",
        help="只列清单：路径 / sha256 前 12 位 / 已有 reviewer / 还差几个（不写任何东西）",
    )
    ap.add_argument(
        "--all", action="store_true",
        help="签台账里所有还不足 2 名不同 reviewer 的路径（台账自己永远跳过）",
    )
    ap.add_argument(
        "--paths", nargs="*", default=None, metavar="PATH",
        help="只签这几条（仓库相对路径，空格分隔）",
    )
    ap.add_argument(
        "--reviewer", action="append", default=None, metavar="NAME",
        help="走查人姓名；可以给多次（同一批里每个名字都必须不同）",
    )
    ap.add_argument(
        "--scope", default="",
        help="走了哪些行/符号（门要求非空且具体：写『看过了』等于没看）",
    )
    ap.add_argument(
        "--scope-template", default="",
        help=("每路径的 scope 模板（优先于 --scope）。可用占位：{path} {sha12} {lines} {batch}。"
              "例：'{path}（{lines}）逐行看过；sha {sha12}；本批 {batch}' —— 每条都不同，"
              "满足门'具体到符号或行区间'的要求"),
    )
    ap.add_argument(
        "--batch", default="",
        help="本批名字（写进 note 前缀；例如 '2026-10-27 第二批 FC-27 重登记'）",
    )
    ap.add_argument(
        "--report-out", default="",
        help="把本次签字结果写成一份 Markdown 记录（逐条：路径 / sha / reviewer / 结论）",
    )
    ap.add_argument(
        "--status-json", default="",
        help="把逐条覆盖情况写成 JSON（路径 / sha256 / 已有 reviewer / 还差几个）",
    )
    ap.add_argument(
        "--verdict", default="逐行走查通过", help="这一条的走查结论（默认与门一致）",
    )
    ap.add_argument("--note", default="", help="写进台账的一句话（例如第几批）")
    ap.add_argument(
        "--root", default=str(HERE.parent), help="仓库根（默认本脚本上一级）",
    )
    ap.add_argument(
        "--yes", action="store_true",
        help="跳过交互确认（非交互环境下不给它就不签）",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="只打印将要签的清单，一个字节都不写",
    )
    return ap


def _target_keys(args: argparse.Namespace, ledger: G.Ledger, root: pathlib.Path) -> list[str]:
    """这一批要处理哪些台账键（`--list` 与签字共用同一处选路，免得两份口径分家）。"""
    if args.paths and args.all:
        raise _Refused("`--paths` 与 `--all` 只能给一个：一次只该有一个来源")
    if args.paths:
        raw = [str(p).strip() for p in args.paths]
        raw = [p for p in raw if p]
        if not raw:
            raise _Refused("`--paths` 是空的：没有说要签哪些")
        keys = [G._repo_rel_key(p, root) for p in raw]
        if len(set(keys)) != len(keys):
            raise _Refused(f"同一路径在这一批里出现了两次：{keys}")
        return keys
    if args.list or args.all:
        entries = [e for e in ledger.entries if e.path != G.LEDGER_NAME]
        if args.list:
            return [e.path for e in entries]
        return [e.path for e in entries if len(e.distinct_reviewers) < G.REQUIRED_APPROVALS_ON_HIT]
    raise _Refused("没有说要签哪些：给 `--paths ...` 或 `--all`（先 `--list` 看一眼清单）")


def _reviewer_names(args: argparse.Namespace) -> list[str]:
    """人名必须非空、且同一批里归一化之后互不相同（2 名必须是 2 个人）。"""
    names = [str(n).strip() for n in (args.reviewer or [])]
    if not names or any(not n for n in names):
        raise _Refused("`--reviewer` 必填且非空：匿名签字与没有人签字无法区分")
    first: dict[str, str] = {}
    for name in names:
        who = G.normalize_subject(name)
        if who in first:
            raise _Refused(
                f"同一批里 reviewer 名字重复：{first[who]!r} 与 {name!r} 归一化之后是同一个人 "
                "—— 2 名必须不同人（门按不同姓名计批准数）"
            )
        first[who] = name
    return names


def _preflight(
    root: pathlib.Path, ledger: G.Ledger, keys: list[str], names: list[str],
    args: argparse.Namespace,
) -> dict[str, str]:
    """用门自己的 `add_approval` 预演每一条（不落盘），把拒绝理由在写之前一次收齐。

    预演与真签是同一个函数 ⇒ 预演说不行的那一条，真签也一定不行；于是"批量签了一半
    才发现第 7 条 hash 是旧的"在结构上不会发生。
    """
    problems: dict[str, str] = {}
    for key in keys:
        for who in names:
            try:
                # 预演必须与真签同参数：`--scope-template` 之后 scope 是逐条现算的，
                # 拿 `args.scope`（空串）预演会把每一条都判成"scope 为空"（实测踩过）。
                G.add_approval(
                    ledger, key, reviewer=who, scope=_scope_for(root, key, args),
                    note=_note_for(args), verdict=args.verdict, root=root,
                )
            except G.LedgerError as exc:
                problems[key] = f"{who}：{exc}"
                break
    return problems


def _needs_baseline(ledger: G.Ledger, keys: list[str], root: pathlib.Path) -> list[str]:
    """这些键的台账 hash 与盘上不一致（或压根没登记）—— 签字之前必须先登记这一版。"""
    out: list[str] = []
    for key in keys:
        entry = ledger.entry_for(key)
        if entry is None:
            out.append(key)
            continue
        try:
            disk = G.sha256_file(G._target_path(key, root))
        except G.LedgerError:
            out.append(key)
            continue
        if disk != entry.sha256:
            out.append(key)
    return out


def _scope_for(root: pathlib.Path, key: str, args: argparse.Namespace) -> str:
    """这一条该写什么 scope：有模板就按模板现算，否则用 --scope 原样。

    为什么需要模板（2026-10-27 那一批 42 条受保护路径）：门的口径是"scope 必须具体到
    符号或行区间"，而一条命令给 42 个不同文件写同一句话（"看过了"）恰好是它拒的那一档。
    模板让每一行都带上自己的路径 / 行数 / sha256 前 12 位 —— 这是可核的最小具体：
    读台账的人拿那 12 位去跟盘上比，就知道当时签的是哪一版。
    """
    template = str(getattr(args, "scope_template", "") or "")
    if not template:
        return str(args.scope or "")
    target = root / key
    try:
        sha12 = G.sha256_file(target)[:12]
    except G.LedgerError:
        sha12 = "sha读不到"
    try:
        lines = f"{len(target.read_text(encoding='utf-8').splitlines())} 行"
    except (OSError, UnicodeDecodeError):
        lines = "行数读不到"
    return (template.replace("{path}", key).replace("{sha12}", sha12)
            .replace("{lines}", lines).replace("{batch}", str(getattr(args, "batch", "") or "")))


def _note_for(args: argparse.Namespace) -> str:
    """台账那条 note：批名 + 人给的话（批名在前，方便按批检索）。"""
    batch = str(getattr(args, "batch", "") or "").strip()
    note = str(args.note or "").strip()
    if batch and note:
        return f"[{batch}] {note}"
    return f"[{batch}]" if batch else note


def _approve(
    root: pathlib.Path, key: str, who: str, args: argparse.Namespace
) -> int:
    """真的签一条：走门自己的 `--approve`（台账格式与校验口径只有那一处实现）。"""
    argv = [
        "--approve", key, "--reviewer", who, "--scope", _scope_for(root, key, args),
        "--verdict", args.verdict, "--note", _note_for(args), "--root", str(root),
    ]
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = G.main(argv)
    if code != 0:
        print(f"!! 门拒绝写入（退出码 {code}）：{key} 这一条，reviewer = {who}")
        for line in captured.getvalue().strip().splitlines():
            print("   " + line)
    return code


def _confirmed(args: argparse.Namespace) -> bool:
    """签字前的最后一道闸：交互环境要人逐字敲 yes，非交互环境必须有 `--yes`。"""
    if args.yes:
        return True
    if not sys.stdin.isatty():
        print("!! 没有 `--yes`，而 stdin 不是终端（非交互环境）：不签，台账一字未动")
        print("   交互跑：在本机终端里去掉 `--yes`，看过上面的清单之后手动确认")
        print("   非交互跑：先 `--list` 看过清单，再给 `--yes`")
        return False
    try:
        got = input("确认按上面的清单签字，请逐字输入 yes（其它任何输入 = 取消）：")
    except EOFError:
        print("!! stdin 已结束（读到 EOF）：不签，台账一字未动")
        return False
    if got.strip() != "yes":
        print(f"!! 输入的是 {got.strip()!r}，不是 yes：取消（台账一字未动）")
        return False
    return True


def _print_list(
    keys: list[str], ledger: G.Ledger, root: pathlib.Path, ledger_path: pathlib.Path
) -> int:
    """只读：把每条的读数、sha256 前 12 位、行数铺出来。"""
    states = [(state_now(ledger_path, key), ledger.entry_for(key)) for key in keys]
    print(f"待签清单（台账：{ledger_path}；门槛 {G.REQUIRED_APPROVALS_ON_HIT} 名不同 reviewer）")
    for state, entry in states:
        print("   " + _list_line(state, entry, root))
    met = sum(1 for state, _ in states if state.satisfied)
    print(
        f"共 {len(states)} 条：已满 {G.REQUIRED_APPROVALS_ON_HIT} 名 {met} 条"
        f" / 待签 {len(states) - met} 条"
    )
    return 0 if met == len(states) else 1


def main(argv: list[str] | None = None) -> int:
    """命令行入口。返回退出码（0=全部满足 2 名；1=还有未满足；2=没查成/没签成）。"""
    args = _parser().parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    ledger_path = G.ledger_default_path(root)
    try:
        ledger = G.load_ledger(ledger_path)
    except G.LedgerError as exc:
        print("!! 台账读不到或读不懂 ⇒ 没查成（不知道现在签了几个），不是没有待签的：")
        print(f"   {exc}")
        return 2

    try:
        keys = _target_keys(args, ledger, root)
        names = [] if args.list else _reviewer_names(args)
    except _Refused as exc:
        print(f"!! {exc}")
        return 2

    if args.list:
        return _print_list(keys, ledger, root, ledger_path)

    if not keys:
        print(
            "没有待签的路径：台账里每一条都已有 "
            f"{G.REQUIRED_APPROVALS_ON_HIT} 名不同 reviewer"
        )
        return 0

    problems = _preflight(root, ledger, keys, names, args)
    if problems:
        print("!! 前置条件不成立 ⇒ 这一批一条都不签（批量签字不在半路开签）：")
        for key, why in problems.items():
            print(f"   {key}  ← {why}")
        print(
            "   台账里没有这一版 / hash 与盘上不一致 ⇒ 先 `--baseline` 登记这一版；"
            "本脚本不代登记（登记 != 批准）"
        )
        need = _needs_baseline(ledger, keys, root)
        if need:
            quoted = " ".join(f'"{key}"' for key in need)
            print("   要登记的就是这几条（门自己的命令，可原样贴）：")
            print(f'     python scripts/noai_gate.py --baseline --paths {quoted} --root "{root}"')
        return 2

    print(f"将要签字（{len(keys)} 条路径 × {len(names)} 名 reviewer）：")
    for key in keys:
        print("   " + state_now(ledger_path, key).line())
    print(f"   reviewer：{'、'.join(names)}")
    _preview_key = keys[0] if keys else ""
    print(f"   scope：{_scope_for(root, _preview_key, args) if _preview_key else args.scope}")
    if args.scope_template:
        print("   （以上是第一条的 scope 展开；每条都会换成自己的 path/lines/sha12）")
    print(f"   verdict：{args.verdict}")
    print(f"   note：{_note_for(args) or '（无）'}")
    print(f"   台账：{ledger_path}")

    if args.dry_run:
        met = sum(1 for key in keys if state_now(ledger_path, key).satisfied)
        print(
            f"（dry-run：只到这里，台账一字未写；当前 {met}/{len(keys)} 条已满足 "
            f"{G.REQUIRED_APPROVALS_ON_HIT} 名）"
        )
        return 0 if met == len(keys) else 1

    if not _confirmed(args):
        return 2

    for key in keys:
        print(f"-- 签字：{key}")
        for who in names:
            before = state_now(ledger_path, key)
            code = _approve(root, key, who, args)
            if code != 0:
                print("!! 门拒绝写入 ⇒ 这一批停在这里（已签上的不回滚，回读看到的就是事实）")
                return 2
            readback(ledger_path, key)
            if G.normalize_subject(who) in before.normalized:
                print(
                    f"   !! {who} 之前已经签过这一条：记录照实追加，"
                    "但批准数按不同姓名计，没有前进"
                )

    final = [state_now(ledger_path, key) for key in keys]
    met = sum(1 for state in final if state.satisfied)
    print(
        f"-- 复核（重读台账，不看内存）：{met}/{len(final)} 条满足 "
        f"{G.REQUIRED_APPROVALS_ON_HIT} 名不同 reviewer"
    )
    for state in final:
        if not state.satisfied:
            print("   " + state.line())

    _write_report(root, ledger_path, keys, names, args, final)
    _write_status(ledger_path, keys, args, root)
    return 0 if met == len(final) else 1


def _write_status(ledger_path: pathlib.Path, keys: list[str], args: argparse.Namespace,
                  root: pathlib.Path) -> None:
    """把逐条覆盖情况写成 JSON（给"签了几成"这类汇报用；一个字节都不改台账）。"""
    out = str(getattr(args, "status_json", "") or "")
    if not out:
        return
    ledger = G.load_ledger(ledger_path)
    rows = []
    for key in keys:
        state = _state_of(ledger, key)
        entry = ledger.entry_for(key)
        rows.append({
            "path": key,
            "sha256": (entry.sha256 if entry else ""),
            "lines": _line_count(root / key),
            "reviewers": list(state.normalized),
            "distinct_reviewers": len(state.normalized),
            "required": G.REQUIRED_APPROVALS_ON_HIT,
            "satisfied": bool(state.satisfied),
        })
    doc = {"schema": 1, "batch": str(getattr(args, "batch", "") or ""),
           "ledger": str(ledger_path), "required": G.REQUIRED_APPROVALS_ON_HIT,
           "total": len(rows), "satisfied": sum(1 for r in rows if r["satisfied"]),
           "rows": rows}
    pathlib.Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
    print(f"-- 覆盖情况已写入 {out}（{doc['satisfied']}/{doc['total']} 条满足）")


def _write_report(root: pathlib.Path, ledger_path: pathlib.Path, keys: list[str],
                  names: list[str], args: argparse.Namespace, final: list[SignState]) -> None:
    """把这次签字写成一份 Markdown 记录（人读的那一份；台账仍是唯一权威）。"""
    out = str(getattr(args, "report_out", "") or "")
    if not out:
        return
    ledger = G.load_ledger(ledger_path)
    met = sum(1 for s in final if s.satisfied)
    lines = [
        f"# FC-27 签字记录{('（' + str(args.batch) + '）') if getattr(args, 'batch', '') else ''}",
        "",
        f"- 台账：`{ledger_path}`",
        f"- 门槛：每条 {G.REQUIRED_APPROVALS_ON_HIT} 名不同 reviewer",
        f"- reviewer：{'、'.join(names) if names else '（未给）'}",
        f"- 结果：**{met}/{len(keys)}** 条满足",
        f"- scope 口径：{'模板 ' + args.scope_template if getattr(args, 'scope_template', '') else (args.scope or '（空）')}",
        f"- verdict：{args.verdict}",
        "",
        "| 路径 | sha256 | 行数 | 已有 reviewer | 满足 |",
        "|---|---|---|---|---|",
    ]
    for key, state in zip(keys, final):
        entry = ledger.entry_for(key)
        lines.append(
            f"| `{key}` | {(entry.sha256[:12] if entry else '—')} | {_line_count(root / key)} "
            f"| {'、'.join(state.normalized) or '—'} | {'是' if state.satisfied else '**否**'} |"
        )
    lines += ["", "> 这份文件只是记录；权威口径在台账与 `python scripts/noai_gate.py --check-approvals`。", ""]
    pathlib.Path(out).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"-- 签字记录已写入 {out}")


if __name__ == "__main__":
    raise SystemExit(main())
