"""仓库快照 / 比对 —— 用来**机器地**证明一个重审窗口是静止的。

## 为什么需要它（`draft/28` §40.2）

第 5 轮重审 R2 又作废了：它的窗口里有并行写者改了 `quoteverify.py`
（`sha256_unchanged = false`）。这是同一类编排错误第 5 次，根因是"写者与审者被允许并发"。
规则写进了 §40.2，但**规则要靠判据执行**，否则它只是一句愿望。这个脚本就是那条判据：

- `snap`：把当前整棵工作树的 `(sha256, 字节数, mtime)` 落成一份快照；
- `diff <快照>`：与快照比对，**逐条列出变了的文件**；有任何变化 ⇒ 退出码 **1**。

## 三态纪律（本项目的铁律，这里同样适用）

- `0` = 查过了、一个字节都没变；
- `1` = 查过了、**有变化**（把变了的文件逐条列出来，含新旧 sha256）；
- `2` = **没查成**（快照读不到 / 目录不存在 / JSON 坏了 / 快照与当前根不是同一棵树）。
  `2` 绝不是 `0`：把"没查成"读成"没问题"正是本项目反复踩过的坑。

## 用法（父代理派重审前后各跑一次）

```powershell
cd D:\\Incubator\\agentflow
python D:\\Incubator\\temp\\_who_writes.py snap              # 派单前
# …审计者在跑，父代理不写任何文件…
python D:\\Incubator\\temp\\_who_writes.py diff temp\\_snap-last.json
```

`snap` 默认写到 `temp/_snap-<UTC 时间戳>.json`，并额外维护一份 `temp/_snap-last.json`
（"上一次快照"），所以最常用的两句是：

```powershell
python ... _who_writes.py snap && python ... _who_writes.py diff temp\\_snap-last.json
```

第二条在派单**之前**跑：只要输出不是 `未变`，就说明还有写者在跑，**不许派重审**。

`--root <目录>` 只为**测这个工具自己**（在 `temp/` 里的合成小树上做"必然红"的正控）。
根目录**显式传参**、不走全局变量 —— 本仓踩过"`--root` 没改判据落点"的坑（§30）。
比对时还会核对"快照记的根"与"当前的根"是同一棵树，不同就报 `2`（拿别棵树当基线是假绿）。
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

#: 强制 UTF-8 输出：本脚本会打印 `✗`/`⇒` 这类字符，而调用方的控制台可能是 GBK
#: （本机实测：不设这一句时，走到"有变化"那条分支会 `UnicodeEncodeError` 崩掉 ——
#:  于是**退出码 1 与"窗口内被审对象变了"撞车**，把"没查成"读成了一个真读数。
#:  这就是本项目最忌讳的形态；修法两半：① 输出永远能写；② 崩了要报 2 而不是 1。）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:            # pragma: no cover - 老解释器/被重定向的流
    pass

PROJ = Path(r"D:\Incubator\agentflow")
TEMP = Path(r"D:\Incubator\temp")
LAST = TEMP / "_snap-last.json"

#: 参与快照的后缀。只取文本/源码类：本门要守的是"审计者读的那些字节"。
#: `2026-09-27` 补 `.jsonl`：R3 的副作用在仓里建出 `gapprobe/data/events.jsonl`，
#: 而它此前**不在扫描面内**（我自己的盲点 —— 快照说"454 个文件未变"，
#: 而那个目录下还多了一个 0 字节的 `.jsonl`）。加之前核过：两个既有 `.jsonl`
#: （`demo/run/data/events.jsonl` 41962B / `gapprobe/data/events.jsonl` 0B）
#: 在 b73/b74 两个窗口内都没被动过 ⇒ 加它不会造成假红，只会让"看得见"更完整。
SUFFIXES = (".py", ".md", ".json", ".jsonl", ".toml", ".lean", ".txt", ".cfg", ".ini", ".tsv")
#: 明确排除的目录：产物、缓存、虚拟环境、git 内部。
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             ".venv", "venv", "node_modules", ".idea", ".vscode",
             "runs", "workspace", "outputs", ".agentflow"}


def _files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in SUFFIXES:
            continue
        # 台账快照/备份本身不参与（它们就是给这类比对用的，且天天在变）
        if p.name.endswith((".bak", ".orig")):
            continue
        out.append(p)
    return out


def _one(p: Path) -> dict:
    b = p.read_bytes()
    st = p.stat()
    return {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b),
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}


def take(root: Path) -> dict:
    files = _files(root)
    return {"root": str(root), "taken_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(files),
            "files": {str(p.relative_to(root)).replace("\\", "/"): _one(p) for p in files}}


def _die(msg: str) -> int:
    print(f"[unknown] {msg}")
    return 2


def cmd_snap(root: Path) -> int:
    if not root.is_dir():
        return _die(f"目录不存在：{root}")
    snap = take(root)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    out = TEMP / f"_snap-{stamp}.json"
    try:
        TEMP.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
        LAST.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        return _die(f"快照写不出去：{exc}")
    print(f"快照已落：{out}（{snap['count']} 个文件，{snap['taken_at']}，根 {root}）")
    print(f"并为下一次比对更新了：{LAST}")
    return 0


def cmd_diff(root: Path, arg: str | None) -> int:
    path = Path(arg) if arg else LAST
    if not path.is_file():
        return _die(f"快照读不到：{path}（先跑 `snap`）")
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _die(f"快照读不出来/JSON 坏了：{exc}")
    if not isinstance(old, dict) or "files" not in old:
        return _die(f"快照结构不对（缺 files）：{path}")
    if str(root) != str(old.get("root")):
        return _die(f"根不是同一棵树：快照记的是 {old.get('root')!r}，现在给的是 {root!r}"
                    " —— 拿别棵树当基线是假绿")
    if not root.is_dir():
        return _die(f"目录不存在：{root}")

    now = take(root)
    o, n = old["files"], now["files"]
    changed = sorted(k for k in set(o) & set(n) if o[k]["sha256"] != n[k]["sha256"])
    added = sorted(set(n) - set(o))
    gone = sorted(set(o) - set(n))

    print(f"比对：{path.name}（{old.get('taken_at')}） -> 现在（{now['taken_at']}）")
    print(f"  上次 {len(o)} 个文件，现在 {len(n)} 个")
    if not (changed or added or gone):
        print("  未变：一个字节都没动 ⇒ 这个窗口是静止的")
        return 0
    if changed:
        print(f"  ✗ 改了 {len(changed)} 个：")
        for k in changed:
            print(f"      {k}")
            print(f"          {o[k]['sha256'][:16]} ({o[k]['bytes']}B, {o[k]['mtime']})")
            print(f"       -> {n[k]['sha256'][:16]} ({n[k]['bytes']}B, {n[k]['mtime']})")
    if added:
        print(f"  + 新增 {len(added)} 个：{added[:20]}{' …' if len(added) > 20 else ''}")
    if gone:
        print(f"  - 消失 {len(gone)} 个：{gone[:20]}{' …' if len(gone) > 20 else ''}")
    print("  ⇒ 整树口径：窗口内有文件变了。这**不是**『这次审计不作数』的同义词 ——")
    print("     按 `reaudit5-COMMON.md` §0.2 约定一：**以冻结集为准**。")
    print("     ① 变了的文件**在你的冻结集里** ⇒ 那份审计的 sha256_unchanged 必须报 false（真作废）；")
    print("     ② 只在冻结集**之外** ⇒ 逐条列进 `notes` 当**观察**，不要因此报 false。")
    print("     （为什么口径要这么分：窗口里常有『别人批次正在写』的文件，")
    print("       若用整树口径，任何并发窗口都会自动作废，判据二就无法成立。）")
    print("     ③ 而**判据三的四道门**必须在『所有写者停下 + 重新落凭据 + 重证』之后跑，")
    print("       整树读数为零才是它的前置条件 —— 两种口径各有各的用处，不许混用。")
    return 1


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--root"]
    root = PROJ
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 >= len(argv):
            return _die("--root 后面要给目录")
        root = Path(argv[i + 1])
        args = [a for a in args if a != argv[i + 1]]
    if not args or args[0] not in ("snap", "diff"):
        print("用法：_who_writes.py [--root <目录>] snap | diff [快照.json]")
        return 2
    if args[0] == "snap":
        return cmd_snap(root)
    return cmd_diff(root, args[1] if len(args) > 1 else None)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except SystemExit:
        raise
    except BaseException as exc:              # 探针自己崩了 = **没查成** ⇒ 2，绝不是 0 或 1
        print(f"[unknown] 探针自己崩了（没查成）：{type(exc).__name__}: {exc}")
        raise SystemExit(2)
