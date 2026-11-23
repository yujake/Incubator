"""`check_declaration` —— 用户声明（`RELIABLE-REFERENCES.json`）与盘面对不对得上。

用法：

```
python scripts/check_declaration.py --workspace projects/lp-ball-15
python scripts/check_declaration.py --workspace projects/lp-ball-15 --json
python scripts/check_declaration.py --selftest
```

四项读数（每项 `clear` / `hit` / `unknown` / `na` 四态）：

| # | 项 | 判什么 |
|---|---|---|
| 1 | `declaration` | 声明读得出来吗（复用 `locallib.declaration_verdict` 的三态） |
| 2 | `declared_empty` | 声明点到的目录是不是空的 / 点到的对象在不在盘上 |
| 3 | `reference_count` | `reference/`（种子与用户材料的投放处）里有几份东西 |
| 4 | `stray_books` | 工作区里既不在书架、也不在投放处、又没被声明的书（游离文件） |

退出码（三态）：

- `0` = 四项都查了、都没有命中；
- `1` = 查过了、至少一项命中；
- `2` = 没查成（工作区不在、import 不到 `agentflow`、声明不在盘上 / 读不出来、或某项列不了目录）——
  命中优先于没查成（已知的坏不许被旁边一项的读不到盖住）。

## 为什么"声明不在"与"声明读不出来"都是 2 而不是 1

`locallib.declaration_verdict` 的三态已经把这件事定死了：文件不在盘上是 `absent`
（没点名）、形状不对是 `unreadable`（`checked=False`）。本脚本问的是"声明与盘面
对不对得上"：没有声明文件时，这个问题没有可核的对象 —— 折成"用户没声明"
（命中）或"声明是空的"（命中）都说过假话，而且方向相反。所以 `absent` 与
`unreadable` 一律落 `unknown`、整条落 2；工作区里有几份书照样写进 detail
（"有 N 份书却没有声明，入库被 fail-closed 关着"），但那是没查成的原因，
不是"查过了、结论是坏的"。

"声明在盘上、`paths` 是空的"才是另一种事：文件在、读得出来、用户这一次没点名 ——
那一档由第 2 项 `declared_empty` 报命中（`paths` 空），整条落 1。两档不可折叠
（P2，2026-11-22：`temp/smoke/ws1` 上没有声明文件，却被报成"声明读出来了但 paths
是空的"）。

## 第 4 项的口径（什么叫"游离文件"）

书（`.pdf` / `.epub` / `.djvu` / `.ps` / `.dvi`）只有两种合法位置：

- `library/`：已登记书架（每个文件要有 `literature` 行引用 —— 那条由
  `check_landing_gates` 的第 4 项判）；
- `reference/`（或旧名 `source/`）：投放处，用户把材料放这里再说"这些都是可靠参考文献"。

其余位置（根目录、`downloads/` 之类）出现的书，只有在被声明覆盖时才不算游离：
声明认整条路径、裸文件名、目录三种写法（`locallib.is_declared` 是唯一判据）。
这份读数要的是"盘上有没有一份谁都管不着的书"，不是"这棵树脏不脏"。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

PROG = "check_declaration"

EXIT_OK = 0
EXIT_BAD = 1
EXIT_UNKNOWN = 2

CLEAR = "clear"
HIT = "hit"
UNKNOWN = "unknown"
NA = "na"

#: 算"书"的后缀（大小写不敏感）。
BOOK_SUFFIXES: tuple[str, ...] = (".pdf", ".epub", ".djvu", ".ps", ".dvi")

#: 结构目录：这些地方出现的书不算游离（各有各的用途，清单短且每条都能指到东西）。
#: `seed` 是种子包（`seed/literature/files/`，由 `seed/MANIFEST.json` 管、由 `seedinject`
#: 投进工作区的投放处）—— 它不是工作区的书；把产品树当工作区喂进来时，这一条让读数不
#: 至于把 25 份种子读成"25 份游离文件"。
STRUCTURAL_DIRS: frozenset[str] = frozenset({
    "library", "reference", "source", "data", "sessions", "out", "runs",
    "manuscripts", "reports", "notes", "skills", "code", "documents",
    "verifications", "projects", "seed", "__pycache__", ".git",
})

#: 投放处的候选名字（`reference/` 是新布局，`source/` 是文档里仍在用的旧名）。
#: 与 `locallib.DROP_ZONES` 是同一份口径（收编时"投放处里的字节只复制"读的就是那一份；
#: 两处由 `tests/test_the_declared_seed_stays_in_its_drop_zone.py` 钉在一起 —— 一漂，
#: 声明门与收编路就会对同一份文件给两个答案）。
DROP_ZONES: tuple[str, ...] = ("reference", "source")

#: 问"有没有书需要声明"时要扫的地方 = 结构目录去掉投放处（投放处里的书正是要被点名的）。
#: 书架 `library/` 与种子包 `seed/` 不在其内：前者已登记，后者是产品自带材料。
NON_INPUT_DIRS: frozenset[str] = STRUCTURAL_DIRS - frozenset(DROP_ZONES)

DEFAULT_MAX_ITEMS = 12


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


def load_locallib(root: Path):
    """从目标根的 `src/` 导入 `agentflow.locallib`；返回 `(模块, 没查成的理由)`。"""
    src = Path(root) / "src"
    if not (src / "agentflow" / "locallib.py").is_file():
        return None, (f"读不到 {src / 'agentflow' / 'locallib.py'}"
                      "（声明判据的本体）⇒ 没查成")
    sys.path.insert(0, str(src))
    try:
        from agentflow import locallib as LL  # noqa: PLC0415 - 必须在改过 sys.path 之后
    except Exception as exc:  # noqa: BLE001 - 导入失败就是"没查成"
        return None, f"导入 agentflow 失败：{type(exc).__name__}: {exc} ⇒ 没查成"
    where = Path(getattr(LL, "__file__", "") or "").resolve()
    try:
        where.relative_to(Path(root).resolve())
    except ValueError:
        return None, (f"import 到的 agentflow 是 {where}，不在 {Path(root).resolve()} 下"
                      " ⇒ 判据不是这一棵树的，没查成")
    return LL, ""


def _state_row(name: str, state: str, detail: str, items: list[str] | None = None) -> dict:
    """一项读数的统一形状。"""
    return {"check": name, "state": state, "detail": detail, "items": list(items or ())}


def _iter_books(workspace: Path, *,
                skip_dirs: frozenset[str] = STRUCTURAL_DIRS) -> list[tuple[str, Path]]:
    """工作区里的书：`[(工作区相对 posix 路径, 绝对路径)]`，跳过 `skip_dirs` 下的。"""
    out: list[tuple[str, Path]] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in BOOK_SUFFIXES:
            continue
        rel = path.relative_to(workspace)
        if rel.parts and rel.parts[0] in skip_dirs:
            continue
        if any(part == "__pycache__" or part.startswith(".") for part in rel.parts):
            continue
        out.append((rel.as_posix(), path))
    return out


def _count_files(base: Path) -> int:
    """目录下（递归）有几个文件；列不了时抛（由调用方落 unknown）。"""
    return sum(1 for p in base.rglob("*") if p.is_file())


def _declaration_state(LL, workspace: Path) -> tuple[str, tuple[str, ...], str]:
    """声明文件此刻的三态 `(state, paths, problem)` —— 本脚本唯一的判定点。

    只回答"文件在不在、读不读得出、读出来的 paths 是什么"，不掺"工作区里有没有
    书"：那一层是第 1 项自己的措辞，第 2 项问的是"有没有可核的声明项"。两项共用这
    一个函数，才不会一边说"没有声明"、另一边说"声明是空的"（P2 的现场就是后者）。

    判据本体仍在 `locallib.declaration_verdict`（产品侧的唯一实现）；这里只做解包。
    """
    verdict = dict(LL.declaration_verdict(workspace))
    return (str(verdict.get("state") or ""),
            tuple(str(p) for p in (verdict.get("paths") or ())),
            str(verdict.get("problem") or ""))


def _check_declaration(LL, workspace: Path, books_all: list[tuple[str, Path]],
                       max_items: int) -> dict:
    """第 1 项：声明本身读得出来吗。"""
    try:
        state, paths, problem = _declaration_state(LL, workspace)
    except Exception as exc:  # noqa: BLE001 - 判据自己抛了 = 没查成
        return _state_row("declaration", UNKNOWN,
                          f"判据自己抛了：{type(exc).__name__}: {exc} ⇒ 这一项没查成")
    if state == LL.DECLARATION_UNREADABLE:
        return _state_row("declaration", UNKNOWN,
                          (f"{LL.DECLARATION_NAME} 在盘上但读不出来（{problem or '没给原因'}）"
                           " ⇒ 没查成（既不是「用户没点名」也不是「用户都点名了」）"))
    if state == LL.DECLARATION_ABSENT:
        # 文件不在 ⇒ 没查成（2）。有书这件事写进 detail：它解释了"为什么这一格要紧"，
        # 但不把 absent 折成命中 —— 没有声明可核时，"声明与盘面一致/不一致"都不可判。
        if books_all:
            return _state_row("declaration", UNKNOWN,
                              (f"没有 {LL.DECLARATION_NAME}，工作区里却有 {len(books_all)} 份书"
                               " ⇒ 声明这一格没查成（入库这条路仍被 fail-closed 关着；"
                               "要有人把用户原话抄成声明）"),
                              [rel for rel, _p in books_all[:max_items]])
        return _state_row("declaration", UNKNOWN,
                          (f"没有 {LL.DECLARATION_NAME}，工作区里也没有书"
                           " ⇒ 声明这一格没查成（没有可核的声明项，"
                           "这不是「声明与盘面一致」）"))
    if state == LL.DECLARATION_READ:
        detail = f"读出来了：`paths` {len(paths)} 条"
        if paths:
            detail += "（" + "、".join(paths[:max_items]) + "）"
        return _state_row("declaration", CLEAR, detail, list(paths[:max_items]))
    return _state_row("declaration", UNKNOWN, f"判据给了不认识的 state={state!r} ⇒ 没查成")


def _check_declared_empty(LL, workspace: Path, decl_row: dict, max_items: int) -> dict:
    """第 2 项：声明点到的目录是不是空的、点到的对象在不在盘上。

    三态（P2，2026-11-22）：

    * 文件不在 / 读不出 ⇒ `unknown`（这一项没查成）—— 不是「声明是空的」；
    * 文件在、读得出来、`paths=[]` ⇒ `hit` `declared_empty`（用户这一次一份都没点名）；
    * `paths` 非空 ⇒ 逐条核目录空不空 / 对象在不在。

    为什么这里要重新问一次状态，而不是只看第 1 项的行：第 1 项会因为"工作区里有没有
    书"改写措辞，而"有没有可核的声明项"只取决于声明文件本身。两问分开，才不会被同行
    的措辞带偏。
    """
    if decl_row["state"] in (UNKNOWN, NA):
        return _state_row("declared_empty", UNKNOWN,
                          "声明本身没读成 / 文件不在 ⇒ 没有可核的声明项"
                          "（这不是「声明是空的」）")
    try:
        state, paths, problem = _declaration_state(LL, workspace)
    except Exception as exc:  # noqa: BLE001
        return _state_row("declared_empty", UNKNOWN,
                          f"读声明时判据自己抛了：{type(exc).__name__}: {exc} ⇒ 这一项没查成")
    if state == LL.DECLARATION_ABSENT:
        return _state_row("declared_empty", UNKNOWN,
                          (f"没有 {LL.DECLARATION_NAME} ⇒ 没有可核的声明项"
                           "（文件不在不等于「声明是空的」）"))
    if state == LL.DECLARATION_UNREADABLE or problem:
        return _state_row("declared_empty", UNKNOWN,
                          f"声明读不出来（{problem or '判据说 unreadable 但没给原因'}）"
                          " ⇒ 这一项没查成")
    if state != LL.DECLARATION_READ:
        return _state_row("declared_empty", UNKNOWN,
                          f"声明给了一个不认识的状态 state={state!r} ⇒ 这一项没查成")
    if not paths:
        return _state_row("declared_empty", HIT,
                          "声明读出来了但 `paths` 是空的 ⇒ 一份都没点名（等价于没声明）")
    empty: list[str] = []
    missing: list[str] = []
    filled: list[str] = []
    for raw in paths:
        rel = str(raw).replace("\\", "/").strip().strip("/")
        if not rel:
            continue
        target = workspace / rel
        if target.is_dir():
            try:
                count = _count_files(target)
            except OSError as exc:
                return _state_row("declared_empty", UNKNOWN,
                                  f"列不了声明点到的目录 {target}：{type(exc).__name__}: {exc}"
                                  " ⇒ 这一项没查成")
            if count == 0:
                empty.append(f"{rel}（目录，0 个文件）")
            else:
                filled.append(f"{rel}（{count} 个文件）")
        elif target.is_file():
            filled.append(rel)
        else:
            missing.append(rel)
    detail = f"声明项 {len(filled) + len(empty) + len(missing)} 条：有内容 {len(filled)}、空 {len(empty)}、不在盘上 {len(missing)}"
    if empty or missing:
        parts = []
        if empty:
            parts.append("声明为空：" + "；".join(empty[:max_items]))
        if missing:
            parts.append("声明点了但盘上没有：" + "；".join(missing[:max_items]))
        return _state_row("declared_empty", HIT, detail + "；" + "；".join(parts),
                          empty + missing)
    return _state_row("declared_empty", CLEAR, detail, filled[:max_items])


def _check_reference(workspace: Path, max_items: int) -> dict:
    """第 3 项：`reference/` 里有几份东西（投放处的读数）。"""
    present = [workspace / name for name in DROP_ZONES if (workspace / name).is_dir()]
    if not present:
        return _state_row("reference_count", NA,
                          "没有 `reference/`（也没有旧名 `source/`）⇒ 没有投放处可数"
                          "（旧工作区的种子直接铺在 `library/` 里）")
    counts: list[str] = []
    total = 0
    for base in present:
        try:
            count = _count_files(base)
        except OSError as exc:
            return _state_row("reference_count", UNKNOWN,
                              f"列不了 {base}：{type(exc).__name__}: {exc} ⇒ 这一项没查成")
        total += count
        counts.append(f"{base.name}/={count}")
    detail = "投放处：" + "、".join(counts)
    if total == 0:
        return _state_row("reference_count", HIT,
                          detail + "；投放处存在但一份文件都没有（空投放处）")
    return _state_row("reference_count", CLEAR, detail)


def _check_stray(LL, workspace: Path, decl_row: dict, max_items: int) -> dict:
    """第 4 项：既不在书架/投放处、也没被声明覆盖的书。"""
    try:
        declared, problem = LL.read_declaration(workspace)
    except Exception as exc:  # noqa: BLE001
        return _state_row("stray_books", UNKNOWN,
                          f"读声明时判据自己抛了：{type(exc).__name__}: {exc} ⇒ 这一项没查成")
    if problem:
        return _state_row("stray_books", UNKNOWN,
                          (f"声明读不出来（{problem}）⇒ 判不了「有没有被声明覆盖」，"
                           "这一项没查成"))
    try:
        candidates = _iter_books(workspace, skip_dirs=STRUCTURAL_DIRS)
        # "算不算有书"要连书架一起数（只排掉种子包）：只有书架上有书时，"没有游离的书"
        # 才是一条判过的结论；连书架都空 ⇒ 没有可判对象（na，不是 clear）。
        considered = _iter_books(workspace, skip_dirs=frozenset({"seed"}))
    except OSError as exc:
        return _state_row("stray_books", UNKNOWN,
                          f"遍历工作区失败：{type(exc).__name__}: {exc} ⇒ 这一项没查成")
    if not candidates:
        if not considered:
            return _state_row("stray_books", NA,
                              "工作区里一本书都没有 ⇒ 没有可判对象（不是「没有游离文件」）")
        return _state_row("stray_books", CLEAR,
                          f"工作区里没有游离的书（书 {len(considered)} 份，都在书架/投放处里）")
    stray: list[str] = []
    covered: list[str] = []
    for rel, _path in candidates:
        if declared and LL.is_declared(rel, declared):
            covered.append(rel)
        else:
            stray.append(rel)
    detail = (f"结构目录之外的书 {len(candidates)} 份：被声明覆盖 {len(covered)}、"
              f"游离 {len(stray)}")
    if stray:
        return _state_row("stray_books", HIT,
                          detail + "；游离的既没被点名也不在书架/投放处："
                          + "；".join(stray[:max_items]), stray)
    return _state_row("stray_books", CLEAR, detail, covered[:max_items])


def _looks_like_workspace(workspace: Path, LL) -> tuple[bool, str]:
    """这个目录看起来是一个工作区吗；返回 `(像不像, 理由)`。

    为什么要先问这一句：`--workspace` 指错（指到产品树、指到仓库根）时，四项会照样给读数
    —— 而产品树带着 `seed/literature/files/` 下 25 份种子 PDF，于是"25 份书却没有声明"
    看起来像一条真缺陷。那不是判据的问题，是喂错了对象。三态纪律要求这种情况落
    "没查成"并说清原因，而不是落一条像样的红。

    判据三条（命中任一即算，不猜）：工作区标记 `.agentflow-workspace`；`data/` 下有
    表文件（`.json` 文档）；工作区根上有 `RELIABLE-REFERENCES.json`（刚 init、还没建表的
    工作区也算）。
    """
    if (workspace / ".agentflow-workspace").is_file():
        return True, "有 .agentflow-workspace 标记"
    if (workspace / LL.DECLARATION_NAME).is_file():
        return True, f"有 {LL.DECLARATION_NAME}"
    data = workspace / "data"
    if not data.is_dir():
        return False, f"没有 {data}"
    try:
        tables = [p.name for p in data.iterdir() if p.is_file() and p.suffix == ".json"]
    except OSError as exc:
        return False, f"列不了 {data}：{type(exc).__name__}: {exc}"
    if tables:
        return True, f"data/ 里有 .json {len(tables)} 份"
    return False, (f"data/ 里一份 .json 都没有（也没有 .agentflow-workspace、"
                   f"也没有 {LL.DECLARATION_NAME}）—— 这不是一个已初始化的工作区")


def run(workspace: Path | str, *, root: Path | str | None = None,
        max_items: int = DEFAULT_MAX_ITEMS) -> tuple[int, dict]:
    """跑四项并给出 `(退出码, 读数)`。"""
    ws = Path(workspace).expanduser().resolve()
    product = Path(root).expanduser().resolve() if root else _product_root()
    payload: dict = {
        "script": PROG,
        "workspace": str(ws),
        "product_root": str(product),
        "workspace_marker": {},
        "checks": [],
        "problem_items": [],
        "unknown_checks": [],
        "na_checks": [],
        "state": UNKNOWN,
        "exit_code": EXIT_UNKNOWN,
        "reason": "",
    }
    if not ws.is_dir():
        payload["reason"] = f"工作区不在：{ws} ⇒ 没查成（不是「声明与盘面一致」）"
        return EXIT_UNKNOWN, payload
    LL, why = load_locallib(product)
    if LL is None:
        payload["reason"] = why
        return EXIT_UNKNOWN, payload

    looks, why_not = _looks_like_workspace(ws, LL)
    payload["workspace_marker"] = {"looks_like_workspace": looks, "detail": why_not}
    if not looks:
        payload["reason"] = (f"{ws} 不像一个工作区：{why_not}"
                             " ⇒ 没查成（声明是工作区根上的一份文件，判的是工作区）")
        return EXIT_UNKNOWN, payload

    try:
        books_all = _iter_books(ws, skip_dirs=NON_INPUT_DIRS)
    except OSError as exc:
        payload["reason"] = f"遍历工作区失败：{type(exc).__name__}: {exc} ⇒ 没查成"
        return EXIT_UNKNOWN, payload

    decl_row = _check_declaration(LL, ws, books_all, max_items)
    checks = [
        decl_row,
        _check_declared_empty(LL, ws, decl_row, max_items),
        _check_reference(ws, max_items),
        _check_stray(LL, ws, decl_row, max_items),
    ]
    payload["checks"] = checks
    payload["problem_items"] = [f"{c['check']}：{c['detail']}" for c in checks if c["state"] == HIT]
    payload["unknown_checks"] = [c["check"] for c in checks if c["state"] == UNKNOWN]
    payload["na_checks"] = [c["check"] for c in checks if c["state"] == NA]

    if payload["problem_items"]:
        payload["state"], code = HIT, EXIT_BAD
        payload["reason"] = ("命中了 " + "、".join(c["check"] for c in checks if c["state"] == HIT)
                             + "（已知的坏优先于旁边没查成的那一项）")
        if payload["unknown_checks"]:
            payload["reason"] += "；另有没查成的项：" + "、".join(payload["unknown_checks"])
    elif payload["unknown_checks"]:
        payload["state"], code = UNKNOWN, EXIT_UNKNOWN
        payload["reason"] = ("这些项没查成：" + "、".join(payload["unknown_checks"])
                             + " ⇒ 没查成（不是「声明与盘面一致」）")
    elif not [c for c in checks if c["state"] == CLEAR]:
        # 四项全是 na：一项都没判过（没有声明、没有投放处、没有游离的书）。
        # 照 closing 的同一条规矩，这里不落 0 —— 没有可判对象不等于「与盘面一致」。
        payload["state"], code = UNKNOWN, EXIT_UNKNOWN
        payload["reason"] = ("四项都没有可判对象（不适用：" + "、".join(payload["na_checks"])
                             + "）⇒ 没查成（不是「声明与盘面一致」）")
    else:
        payload["state"], code = CLEAR, EXIT_OK
        payload["reason"] = "四项都查了、都没有命中"
        if payload["na_checks"]:
            payload["reason"] += "（不适用：" + "、".join(payload["na_checks"]) + "）"
    payload["exit_code"] = code
    return code, payload


def render_text(payload: dict) -> str:
    """人读版：一行一项，命中的逐条列出来。"""
    lines = [f"工作区 {payload['workspace']}",
             f"三态   state={payload['state']}  exit={payload['exit_code']}"]
    marker = payload.get("workspace_marker") or {}
    if marker.get("detail"):
        lines.append(f"工作区 {'是' if marker.get('looks_like_workspace') else '否'}：{marker['detail']}")
    lines.append("")
    for cell in payload["checks"]:
        lines.append(f"  [{cell['state']}] {cell['check']}")
        lines.append(f"          {cell['detail']}")
        for item in cell["items"]:
            lines.append(f"            - {item}")
    lines.append("")
    lines.append({0: "结论：声明与盘面一致（0）",
                  1: "结论：有命中（1）—— 逐项见上",
                  2: "结论：没查成（2）—— 0 不是「一致」"}[payload["exit_code"]])
    lines.append(f"理由：{payload['reason']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 自测
def _write_lf(path: Path, text: str) -> None:
    """按 UTF-8 + LF 写文本（新文件带 CRLF 会被 lint 的 R012 记成 error）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _write_json(path: Path, doc: dict) -> None:
    """按 UTF-8 + LF 写一份 JSON（声明文件就是这种形状）。"""
    _write_lf(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def _fixture_clean(LL, ws: Path) -> Path:
    """干净夹具：声明点名 `library/`，书在书架里，投放处有种子。"""
    _write_json(ws / LL.DECLARATION_NAME,
                {"paths": ["library/"], "verbatim": "library/ 下都是可靠参考文献（夹具）"})
    _write_lf(ws / "library" / "book.pdf", "%PDF-1.4 夹具\n")
    _write_lf(ws / "reference" / "seed.pdf", "%PDF-1.4 夹具种子\n")
    _write_lf(ws / "reference" / "SEED-README.md", "# 种子\n")
    return ws


def _fixture_dirty(LL, ws: Path) -> Path:
    """脏夹具：声明点了一个空目录、一个不存在的目录，另有一份游离的书。"""
    _write_json(ws / LL.DECLARATION_NAME,
                {"paths": ["library/", "empty-dir/", "ghost/"],
                 "verbatim": "library/ 与 empty-dir/ 下都是可靠参考文献（夹具）"})
    (ws / "empty-dir").mkdir(parents=True, exist_ok=True)
    _write_lf(ws / "downloads" / "stray.pdf", "%PDF-1.4 夹具游离书\n")
    return ws


def _fixture_unreadable(LL, ws: Path) -> Path:
    """没查成夹具：声明在盘上、形状不对（`paths` 不是数组）。"""
    _write_json(ws / LL.DECLARATION_NAME, {"paths": "library/", "verbatim": "形状不对"})
    return ws


def _fixture_absent(LL, ws: Path) -> Path:
    """没查成夹具：工作区里有书，但 `RELIABLE-REFERENCES.json` 不在盘上。

    走的是 P2 的现场（`temp/smoke/ws1`）：文件不在 ≠ 声明是空的 ⇒ 没查成（2），
    而不是第 2 项报一条 `declared_empty` 的命中。
    """
    _write_json(ws / "data" / "tasks.json", {"rows": []})
    _write_lf(ws / "reference" / "seed.pdf", "%PDF-1.4 夹具种子\n")
    return ws


def selftest() -> int:
    """四条自测：通过 / 失败 / 没查成（形状不对）/ 没查成（声明文件不在）。"""
    LL, why = load_locallib(_product_root())
    if LL is None:
        print(f"自测没跑成：{why}")
        return EXIT_UNKNOWN
    rows: list[tuple[str, str, int, int]] = []
    with tempfile.TemporaryDirectory(prefix="b7-declaration-") as tmp:
        base = Path(tmp)
        cases = (
            ("通过", "声明点名 library/、书架与投放处都有东西", _fixture_clean, EXIT_OK),
            ("失败", "声明点空目录 + 点不存在的目录 + 一份游离书", _fixture_dirty, EXIT_BAD),
            ("没查成", "声明形状不对（paths 不是数组）", _fixture_unreadable, EXIT_UNKNOWN),
            ("没声明", "声明文件不在盘上（有书）⇒ 没查成，不是 declared_empty",
             _fixture_absent, EXIT_UNKNOWN),
        )
        for kind, detail, build, want in cases:
            code, _payload = run(build(LL, base / kind))
            rows.append((kind, detail, want, code))

    print("自测（夹具是 tempfile 里的最小工作区；判据是 locallib.declaration_verdict 与 is_declared）")
    bad = 0
    for kind, detail, want, got in rows:
        flag = "OK  " if want == got else "BAD "
        if want != got:
            bad += 1
        print(f"  [{flag}] {kind:4s} 期望 exit={want} 实际 exit={got}  （{detail}）")
    print(f"自测结论：{len(rows) - bad}/{len(rows)} 条符合期望")
    return EXIT_OK if not bad else EXIT_UNKNOWN


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数、跑四项、按三态返回退出码。"""
    _pin_utf8()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=("声明与盘面的体检（只读）：声明识读、声明为空的目录、reference/ 份数、"
                     "游离文件；0 一致 / 1 命中 / 2 没查成"),
        allow_abbrev=False,
    )
    parser.add_argument("--workspace", default="", help="工作区根（必填，例如 projects/lp-ball-15）")
    parser.add_argument("--root", default=str(_product_root()),
                        help="产品根（缺省 = 本脚本的上一级；判据从它的 src/ 里导入）")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS,
                        help=f"每项最多点名几条（缺省 {DEFAULT_MAX_ITEMS}；计数仍是全量）")
    parser.add_argument("--json", action="store_true", help="输出机器读数")
    parser.add_argument("--selftest", action="store_true",
                        help="用 tempfile 造最小工作区自测（通过 / 失败 / 没查成 / 没声明）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    if not str(args.workspace or "").strip():
        print("必须给 --workspace <工作区根>（声明是工作区根上的一份文件）", file=sys.stderr)
        return EXIT_UNKNOWN

    code, payload = run(args.workspace, root=args.root, max_items=args.max_items)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
