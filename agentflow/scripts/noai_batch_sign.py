# -*- coding: utf-8 -*-
"""FC-27 批量签字驱动：把「一次逐行走查覆盖多处禁改区改动」做成一条可复核的命令。

## 它是什么、不是什么

是：驱动 `scripts/noai_gate.py` 的人审通路（`--baseline` 刷新 hash → `--approve` 追加
reviewer 记录），把 N 个文件 × 2 名 reviewer 的那一串命令收成一条，并把行级走查材料
（改动 diff、命中清单里的理由串、台账当前 sha 与盘上 sha）先铺出来给人读。

不是：代签。三条硬约束写在代码里，不是写在注释里 ——

1. 默认 dry-run（不带 `--write` 时一个字节都不写）；
2. `--write` 必须同时给 `--reviewer-a` / `--reviewer-b`（两个不同的名字）与 `--attest`
   （走查人自己的那句话，写进台账的 `note`）；
3. 每签完一处，立刻回读台账断言 `reviewers` 里没有"刷新 hash 之前留下的旧签名"。
   这一条是防伪：`--baseline` 只刷新 hash、绝不写 reviewers，若某一天它开始连着旧
   reviewers 一起留，旧签名就会挂在新内容上 —— 那正是 FC-27 最怕的"假 approved"。
   脚本一旦读到这种情况就当场中止并告诉你原因（不继续、不回滚，交给人看）。

## 用法

    # 1) 先看材料（只读）——默认就是这一步
    python -B scripts/noai_batch_sign.py --since HEAD~4

    # 2) 人逐行走查之后（只有人能跑这一步）
    python -B scripts/noai_batch_sign.py --since HEAD~4 --write \
        --reviewer-a 某某甲 --reviewer-b 某某乙 \
        --attest "逐行看过 specs/{c,f,g,h}.py 与 interactions.py 的改动，结论：与裁定一致"

    # 3) 只核当前状态（不写）
    python -B scripts/noai_batch_sign.py --since HEAD~4 --verify-only

`--since <ref>` 用门自己的改动集口径（`--git --print-changed`）取路径，再按清单命中筛出
"需要签字的那些"；也可以直接 `--paths a.py b.py` 指定。

退出码：0 = 材料已铺好且（`--write` 时）全部签成并复核通过；1 = 有需要人处理的项；
2 = 没查成（门读不到清单/台账/改动集 —— 不许读成"没问题"）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
GATE = HERE / "noai_gate.py"


def _run(args: list[str], *, quiet: bool = False) -> tuple[int, str]:
    """跑一次门，返回 `(退出码, 输出)`。不吞退出码 —— 三态纪律在这里也成立。"""
    got = subprocess.run([sys.executable, "-B", str(GATE), *args],
                         capture_output=True, text=True, encoding="utf-8")
    out = (got.stdout or "") + (got.stderr or "")
    if not quiet:
        print(out.rstrip())
    return got.returncode, out


def gate_paths(since: str) -> tuple[int, list[str]]:
    """用门自己的改动集口径取路径（`--git --print-changed`）—— 口径只许有一处实现。"""
    code, out = _run(["--git", "--since", since, "--print-changed"], quiet=True)
    paths = [ln.strip() for ln in out.splitlines() if ln.strip() and not ln.startswith("[")]
    return code, paths


def hits(paths: list[str]) -> tuple[int, list[dict]]:
    """判定这些路径命中哪些禁改区条目（`--json` 拿结构化结果，不解析人话）。

    `--json` 的键是 `violations`（每项 `path` / `glob` / `category` / `reason`）——
    第一版我按 `hits` 取，于是永远"没有命中"（探针自己先查一遍口径这条纪律，
    在这里同样适用）。
    """
    code, out = _run(["--paths", *paths, "--json"], quiet=True)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return 2, []
    return code, list(data.get("violations") or [])


def ledger_reviewers(root: pathlib.Path, rel: str) -> list[str] | None:
    """台账里某一条现有的 reviewer 名字（`None` = 台账/条目读不到 —— 没查成）。

    台账里的 `path` 有两种写法（`src/agentflow/x.py` 与 `agentflow/src/agentflow/x.py`），
    所以三种候选都试 —— 第一版只试了两种，于是"读不到"被误报成"没查成"。
    """
    p = root / ".noai-approvals.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    bare = rel[len("agentflow/"):] if rel.startswith("agentflow/") else rel
    want = {rel, bare, f"agentflow/{bare}"}
    for e in data.get("entries") or []:
        if str(e.get("path") or "") in want:
            return [str(r.get("name") or r.get("reviewer") or r) for r in (e.get("reviewers") or [])]
    return None


def git_root(root: pathlib.Path) -> pathlib.Path:
    """本仓的 git 根（`agentflow/` 是交付物子目录，`.git` 在上一级）—— 路径要按它算。"""
    got = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(root),
                         capture_output=True, text=True, encoding="utf-8")
    top = (got.stdout or "").strip()
    return pathlib.Path(top) if top else root


def show_material(root: pathlib.Path, rel: str, since: str) -> None:
    """铺一处走查材料：清单里的理由串 + 台账/盘上 sha + 这段改动本身的 diff。"""
    print("\n" + "=" * 78)
    print(f"◆ {rel}")
    code, out = _run(["--paths", rel], quiet=True)
    for line in out.splitlines():
        if "命中" in line or "sha" in line or "stale" in line or "reviewer" in line:
            print("   " + line.strip())
    disk = root / rel
    if disk.exists():
        import hashlib
        print(f"   盘上 sha256 = {hashlib.sha256(disk.read_bytes()).hexdigest()[:16]}…")
    revs = ledger_reviewers(root, rel)
    print(f"   台账里的走查记录 = {revs if revs is not None else '（读不到 —— 没查成）'}")
    # diff 的 pathspec 按 git 根算（从 `agentflow/` 里跑 git 时 `agentflow/src/...` 匹配不上）
    diff = subprocess.run(["git", "-C", str(git_root(root)), "diff", "--unified=3",
                           f"{since}..HEAD", "--", rel],
                          capture_output=True, text=True, encoding="utf-8")
    body = (diff.stdout or "").strip()
    if not body:
        print("   （这段区间里这个文件没有改动 —— 那它为什么要签？先确认路径对不对）")
    else:
        shown = body.splitlines()
        print(f"   改动 {len(shown)} 行（下面铺出来，逐行读它）")
        for line in shown[:400]:
            print("     " + line)
        if len(shown) > 400:
            print(f"     …（还有 {len(shown) - 400} 行，自己 `git diff {since}..HEAD -- {rel}` 看全）")


def sign_one(root: pathlib.Path, rel: str, args: argparse.Namespace) -> int:
    """签一处：刷新 hash（`--baseline`）→ 两名 reviewer 各追加一条（`--approve`）。"""
    before = ledger_reviewers(root, rel)
    print(f"\n--- 签字：{rel}")
    code, _ = _run(["--baseline", "--paths", rel, "--note", args.attest])
    if code != 0:
        print(f"!! `--baseline` 退出码 {code} ⇒ 停在这里（没签）")
        return 2
    after = ledger_reviewers(root, rel)
    if after is None:
        print("!! 刷新之后台账读不到 ⇒ 停（没签）")
        return 2
    if after:
        # 门自己的话逐字："必要时重跑 `--baseline`（会清空该条的批准语义）⇒ 再 `--approve`"。
        # 所以刷新之后还留着名字 = 旧签名挂到了新内容上 —— 这正是 FC-27 最怕的"假 approved"。
        print(f"!! 刷新 hash 之后 reviewers 仍然非空（{after}）—— 旧签名会挂在新内容上。"
              "脚本不继续：先让人查清这一条为什么没被清空")
        return 2
    for who in (args.reviewer_a, args.reviewer_b):
        code, _ = _run(["--approve", rel, "--reviewer", who, "--scope", args.scope,
                        "--note", args.attest])
        if code != 0:
            print(f"!! `--approve --reviewer {who}` 退出码 {code} ⇒ 停（后面的人没签）")
            return 2
    revs = ledger_reviewers(root, rel)
    print(f"   签完：reviewers = {revs}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FC-27 批量签字驱动（默认 dry-run；只有人能 --write）")
    ap.add_argument("--root", default=str(HERE.parent), help="仓库根（默认脚本上一级）")
    ap.add_argument("--since", default="HEAD~1", help="改动集基线 ref（喂给门的 `--git --since`）")
    ap.add_argument("--paths", nargs="*", default=None, help="直接给路径（不给就用 --since 取）")
    ap.add_argument("--write", action="store_true", help="真的写台账（默认 dry-run）")
    ap.add_argument("--verify-only", action="store_true", help="只核当前状态，不写")
    ap.add_argument("--reviewer-a", default="", help="走查人甲（必须是人，且与乙不同）")
    ap.add_argument("--reviewer-b", default="", help="走查人乙")
    ap.add_argument("--attest", default="", help="走查人自己的一句话（写进台账 note）")
    ap.add_argument("--scope", default="", help="走了哪些行/函数（默认按 diff 的受影响区间生成）")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    if args.paths:
        paths = list(args.paths)
    else:
        code, paths = gate_paths(args.since)
        if code == 2:
            print("!! 取不到改动集（门的 `--print-changed` 退出码 2）⇒ 没查成，不是没问题")
            return 2
    if not paths:
        print("（改动集是空的 —— 没有要签的东西）")
        return 0

    code, hit_rows = hits(paths)
    if code == 2:
        print("!! 命中判定没查成（门 `--json` 没给出可解析的结果）⇒ 停")
        return 2
    need = sorted({str(h.get("path") or "") for h in hit_rows if h.get("path")})
    if not need:
        print("✅ 这些路径一条都没命中禁改区 —— 不需要签字")
        return 0

    print(f"命中禁改区的路径 {len(need)} 条（改动集 {len(paths)} 条）：")
    for rel in need:
        print(f"   - {rel}")
    for rel in need:
        show_material(root, rel, args.since)

    if args.verify_only:
        print("\n--- 只核（`--check-approvals`）")
        code, _ = _run(["--check-approvals", "--paths", *need])
        return 0 if code == 0 else 1

    if not args.write:
        print("\n（dry-run：材料就铺到这里。逐行走查之后由人加 `--write` 重跑本命令。）")
        return 0

    # ---- 到这里才是"人签字"那一步：三条前置断言，一条都不许省
    if not args.reviewer_a or not args.reviewer_b:
        print("!! `--write` 必须给 `--reviewer-a` 与 `--reviewer-b`（两名不同的走查人）")
        return 2
    if args.reviewer_a.strip() == args.reviewer_b.strip():
        print("!! 两名 reviewer 不能是同一个名字（FC-27 要的是两个独立复核）")
        return 2
    if not args.attest.strip():
        print("!! `--write` 必须给 `--attest`：走查人自己的一句话（会写进台账 note）")
        return 2
    if not args.scope.strip():
        args.scope = f"{args.since}..HEAD 的改动行（逐行走查）"

    failed = 0
    for rel in need:
        failed += sign_one(root, rel, args)

    print("\n--- 签完全部复核一遍（`--check-approvals`）")
    code, _ = _run(["--check-approvals", "--paths", *need])
    if code != 0 or failed:
        print(f"!! 复核退出码 {code}（签字过程里有 {failed} 处中止）⇒ 有需要人处理的项")
        return 1
    print("✅ 全部签成且复核通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
