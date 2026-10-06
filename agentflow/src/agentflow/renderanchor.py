# -*- coding: utf-8 -*-
"""渲染锚与编译回执：判"这份论文包还是不是库里现在的样子"，以及"PDF 是从哪个 tex 编出来的"。

## 这一层为什么从项目脚本里搬进来（`draft/28` §191）

原先这两件事都写在项目脚本 `code/make_paper.py` 里，于是：

1. 只读角色核对不了。H 是只读角色，结构性拿不到 `exec` 工具（它执行项目脚本），
   而"这份包与库一致吗"本来是最该由审校者自己回答的问题。判据搬进框架成纯函数之后，
   一个 `read` 工具就能调它 —— 不起子进程、不出网。
2. 锚的设计缺陷没有单一的修处。原锚把源文件与编译产物放进同一张哈希表
   （`main.tex` 与 `main.pdf` 都在里面），而锚是在渲染那一刻写的 ⇒
   先写锚、后编译必然报 `main.pdf` 漂移，"0 漂移"在物理上不可达（实测见 `draft/28` §188.3）。
   分成两件东西才是对的：
   - 锚（渲染时写）：源表行数 + 规范哈希，加渲染产出的源文件的 sha256
     （PDF 不在内 —— 它是编译产物，不是渲染产物）；
   - 编译回执（编译时写）：这份 PDF 由哪一个 tex 哈希编出、几页、标记缺不缺、
     编译器的原始退出码。于是"PDF 是从旧 tex 编的"变成一个精确可判的事实。

## 三态（不许折平）

`check()` 逐维给结论（`tables` / `files` / `receipt`），总体取最坏的一档：
`consistent` / `drifted` / `unknown`（锚不在，或回执不在 ⇒ 有一维判不了，
而"判不了"不许写成"没问题"）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

#: 参与论文包的源表 —— 它们一变，包里的表就该跟着变。
ANCHOR_TABLES: tuple[str, ...] = ("documents", "dependencies", "experiments", "conjectures",
                                  "literature", "review_findings")
#: 锚与回执的文件名（都在包目录 `out/paper/` 下）。
ANCHOR_NAME = "RENDER-ANCHOR.json"
RECEIPT_NAME = "COMPILE-RECEIPT.json"
#: 构建历史：追加式日志（一次渲染/编译一行；`draft/28` §193 加）。
#:
#: 为什么是"当前状态 + 追加历史"，而不是给锚与回执加时间戳文件名：
#: 后者会让"最新一次结论在哪"从读一个常量变成读一个目录 —— 而那正是每条判据
#: 每天都要回答的问题。于是沿用本仓既有的形态（`ARTIFACTS.jsonl` / `work_items.jsonl`
#: / `sessions/*.jsonl`）：当前状态仍是两个固定文件名，历史另记一行。
HISTORY_NAME = "BUILD-HISTORY.jsonl"

#: 编译产物：不进锚（它们每次编译都变，锚是渲染时写的）。
#: `BUILD-HISTORY.jsonl` 也在这一栏：它是追加式日志，每写一行它自己就变了 ——
#: 把它收进锚会让"每次构建都报漂移"，与 PDF 当年那个坑同形（`draft/28` §188.3）。
COMPILE_PRODUCTS: tuple[str, ...] = ("main.pdf", "compile.log", HISTORY_NAME)
#: LaTeX 的中间产物：连回执也不记（每次编译都变，且没有信息量）。
COMPILE_SUFFIXES: tuple[str, ...] = (".aux", ".log", ".out", ".toc", ".fls",
                                     ".fdb_latexmk", ".synctex.gz")

#: 三维的判定词表。`unknown` 只用于"这一维没判成"。
VERDICTS: tuple[str, ...] = ("consistent", "drifted", "unknown")


def file_digest(path: Path) -> str:
    """文件内容哈希（读不到返回空串 —— 调用方按"读不到"处理，不编哈希）。"""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def rows_digest(rows: list[Mapping[str, Any]]) -> str:
    """一组行的规范哈希（键排序、无空白、非 ASCII 原样）——与 `signatures` 同一套口径。"""
    from .canonical import canonical_sha256

    return canonical_sha256([dict(r) for r in rows])


def package_files(package_dir: Path) -> dict[str, str]:
    """渲染产出的源文件 → sha256（排除编译产物与 LaTeX 中间产物）。

    锚要能回答"包里的表还是不是库里现在的样子"，所以它收的是渲染写出来的那些文件；
    PDF 交给编译回执管（见模块 docstring）。
    """
    files: dict[str, str] = {}
    for p in sorted(package_dir.rglob("*")):
        if not p.is_file() or p.name in (ANCHOR_NAME, RECEIPT_NAME):
            continue
        if p.name in COMPILE_PRODUCTS or p.suffix in COMPILE_SUFFIXES:
            continue
        files[p.relative_to(package_dir).as_posix()] = file_digest(p)
    return files


def build_anchor(store: Any, package_dir: Path | str) -> dict[str, Any]:
    """算一次锚：各源表的 `{rows, sha256}` + 包内源文件的 sha256。"""
    import datetime as _dt

    out = Path(package_dir)
    tables: dict[str, dict[str, Any]] = {}
    for name in ANCHOR_TABLES:
        try:
            rows = [dict(r) for r in store.rows(name)]
        except Exception as exc:  # noqa: BLE001 —— 表读不了要留痕，不能当成"0 行"
            tables[name] = {"rows": -1, "sha256": "", "problem": f"{type(exc).__name__}: {exc}"}
            continue
        tables[name] = {"rows": len(rows), "sha256": rows_digest(rows)}
    return {
        "generated_at": _dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "tables": tables,
        "files": package_files(out),
        "note": (
            "渲染锚：`tables` 是渲染时各源表的行数与规范哈希，`files` 是那次渲染产出的"
            "**源文件**哈希（编译产物不在内，它们由 `" + RECEIPT_NAME + "` 管）。"
            "`check()` 重算并比对 —— 它回答的是「这份包还是不是库里现在的样子」。"
        ),
    }


def build_receipt(package_dir: Path | str, *, tex_sha256: str, pages: int | None,
                  markers_missing: list[str] | None, pdf_bytes: int | None,
                  compiler_exit_codes: list[int | None] | None = None,
                  note: str = "") -> dict[str, Any]:
    """算一份编译回执：这份 PDF 由哪个 tex 哈希编出、几页、标记缺不缺。

    `pdf_bytes` 可以是 `None`（`draft/39` §6.36 的 D46）：没编出 PDF 时也要能写回执
    —— 否则调用方拿到的是 `TypeError`，而"这一趟没编出 PDF"这件事连回执都留不下来
    （真机读数：T3 预检里 `pdflatex` 崩在 MiKTeX 的用户目录权限上，PDF 没产出，
    脚本当场抛 `TypeError: int() argument must be ... not 'NoneType'` ⇒ 回执缺失，
    收工门的 `receipt` 那一维只能判 `unknown`）。`None` = "没有 PDF 可量"，不是 0 字节。
    """
    import datetime as _dt

    out = Path(package_dir)
    pdf = out / "main.pdf"
    return {
        "compiled_at": _dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "tex_sha256": tex_sha256,
        "pdf_sha256": file_digest(pdf),
        "pdf_bytes": (int(pdf_bytes) if pdf_bytes is not None else None),
        "pages": pages,
        "markers_missing": list(markers_missing or []),
        # 原始退出码一字不改：本机 MiKTeX 会写完 PDF 却以 0xC0000409 退出，
        # 把它改写成"成功/失败"都是丢信息（判据是 PDF 的内容）。
        "compiler_exit_codes": list(compiler_exit_codes or []),
        "note": note or "编译回执：`tex_sha256` 是这次编译用的 `main.tex` 的内容哈希。",
    }


def append_history(package_dir: Path | str, event: Mapping[str, Any]) -> str:
    """往 `BUILD-HISTORY.jsonl` 追加一行（时间戳由这里补）。返回问题串（空 = 写成了）。

    这是写操作，只由两个写脚本（渲染 / 编译）调用 —— `check_package` 不写
    （核对是只读动作，让它写盘等于"看一眼就把包改了"）。
    """
    import datetime as _dt

    record = dict(event)
    record.setdefault("at", _dt.datetime.now().astimezone().replace(microsecond=0).isoformat())
    path = Path(package_dir) / HISTORY_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


def history(package_dir: Path | str, *, limit: int | None = None) -> dict[str, Any]:
    """读构建历史。返回 `{present, path, events, total, renders, compiles, problems}`。

    坏行逐条记进 `problems`（不是静默跳过）：历史是审计材料，读不出来必须看得见。
    `limit` 给最后 N 条（`events` 按时间正序）。
    """
    path = Path(package_dir) / HISTORY_NAME
    if not path.is_file():
        # 形状与"读到了历史"那一支逐键一致：调用方不必先判 `present` 才能安全读键
        # （本仓在 `steps[*]` 那件事上已经吃过一次同类亏）。
        return {"present": False, "path": str(path), "events": [], "total": 0,
                "renders": 0, "compiles": 0, "last_render_at": None, "last_compile_at": None,
                "problems": [f"读不到 {HISTORY_NAME}"]}
    events: list[dict[str, Any]] = []
    problems: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {"present": True, "path": str(path), "events": [], "total": 0, "renders": 0,
                "compiles": 0, "last_render_at": None, "last_compile_at": None,
                "problems": [f"{type(exc).__name__}: {exc}"]}
    for i, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            problems.append(f"第 {i} 行不是合法 JSON")
            continue
        if not isinstance(obj, dict):
            problems.append(f"第 {i} 行不是对象")
            continue
        events.append(obj)
    total = len(events)
    tail = events[-int(limit):] if limit else events
    return {"present": True, "path": str(path), "events": tail, "total": total,
            "renders": sum(1 for e in events if str(e.get("event")) == "render"),
            "compiles": sum(1 for e in events if str(e.get("event")) == "compile"),
            "last_render_at": next((e.get("at") for e in reversed(events)
                                    if str(e.get("event")) == "render"), None),
            "last_compile_at": next((e.get("at") for e in reversed(events)
                                     if str(e.get("event")) == "compile"), None),
            "problems": problems}


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    """读一个 JSON 对象。返回 `(数据, 问题)`；读不到或不是对象时数据为 None。

    问题串里写完整路径（不是文件名）：真机实测（`draft/28` §195）—— H 把包目录
    `out/paper` 当成 `project` 传进来，工具回了"读不到 RENDER-ANCHOR.json"，H 读不出
    "它到底去哪找过"，只能自己推断"是路径拼接缺陷"。路径写出来的话，一眼就能看见
    `…/out/paper/out/paper/RENDER-ANCHOR.json` 这个双重拼接。
    """
    if not path.is_file():
        return None, f"读不到 {path}（这里找过）"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path} 读不成 JSON：{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, f"{path} 不是一个 JSON 对象"
    return data, ""


def check_package(project_root: Path | str, *, store: Any = None) -> dict[str, Any]:
    """核对一份论文包：源表 / 源文件 / 编译回执三维。

    `store` 不给时按项目根自己开一个（只读用 `rows`）。返回：

    `{verdict, dimensions:{tables,files,receipt}, drift:[...], anchor_present,
     receipt_present, checked:{tables,files}, receipt:{...}, problems:[...]}`
    """
    root = Path(project_root)
    out = root / "out" / "paper"
    drift: list[str] = []
    problems: list[str] = []

    anchor, anchor_problem = _read_json(out / ANCHOR_NAME)
    if anchor is None:
        problems.append(anchor_problem)
        dimensions = {"tables": "unknown", "files": "unknown", "receipt": "unknown"}
        return _result(dimensions, drift, problems, anchor=None, receipt=None, out=out)

    if store is None:
        from .store import Store

        store = Store(root)

    # ---- 维度 1：源表（行数 + 规范哈希）
    tables_now: dict[str, dict[str, Any]] = {}
    for name in ANCHOR_TABLES:
        try:
            rows = [dict(r) for r in store.rows(name)]
        except Exception as exc:  # noqa: BLE001 —— 读不了就是判不了这一维
            tables_now[name] = {"rows": -1, "sha256": "", "problem": f"{type(exc).__name__}: {exc}"}
            continue
        tables_now[name] = {"rows": len(rows), "sha256": rows_digest(rows)}
    tables_verdict = "consistent"
    for name in ANCHOR_TABLES:
        was = (anchor.get("tables") or {}).get(name) or {}
        now = tables_now[name]
        if now.get("problem"):
            tables_verdict = "unknown"
            problems.append(f"表 {name} 读不了：{now['problem']}")
            continue
        if was.get("rows") != now["rows"] or was.get("sha256") != now["sha256"]:
            tables_verdict = "drifted"
            drift.append(f"表 {name}：锚 {was.get('rows')} 行/{str(was.get('sha256'))[:12]} ≠ "
                         f"现在 {now['rows']} 行/{now['sha256'][:12]}")

    # ---- 维度 2：源文件（编译产物不在内；老锚里若还记着 PDF，跳过它）
    files_now = package_files(out)
    files_was = {k: v for k, v in (anchor.get("files") or {}).items()
                 if k not in COMPILE_PRODUCTS and not any(k.endswith(s) for s in COMPILE_SUFFIXES)}
    files_verdict = "consistent"
    for rel, sha in sorted(files_was.items()):
        if rel not in files_now:
            files_verdict = "drifted"
            drift.append(f"文件 {rel}：锚里有、盘上没了")
        elif files_now[rel] != sha:
            files_verdict = "drifted"
            drift.append(f"文件 {rel}：内容与渲染时不同（{str(sha)[:12]} ≠ {files_now[rel][:12]}）")
    for rel in sorted(set(files_now) - set(files_was)):
        files_verdict = "drifted"
        drift.append(f"文件 {rel}：盘上有、锚里没有（渲染之后新加/改名的）")

    # ---- 维度 3：编译回执（这份 PDF 是从哪个 tex 编出来的）
    receipt, receipt_problem = _read_json(out / RECEIPT_NAME)
    receipt_verdict = "unknown"
    if receipt is None:
        problems.append(receipt_problem + " ⇒ PDF 的来路判不了（不是「一致」）")
    else:
        tex_now = file_digest(out / "main.tex")
        was_tex = str(receipt.get("tex_sha256") or "")
        if not tex_now or not was_tex:
            receipt_verdict = "unknown"
            problems.append("main.tex 或回执里的 tex_sha256 读不到 ⇒ 这一维判不了")
        elif tex_now != was_tex:
            receipt_verdict = "drifted"
            drift.append(f"main.pdf：是从旧 tex 编出来的（回执 {was_tex[:12]} ≠ "
                         f"现在 {tex_now[:12]}）—— 重新编译一次")
        elif file_digest(out / "main.pdf") != str(receipt.get("pdf_sha256") or ""):
            receipt_verdict = "drifted"
            drift.append("main.pdf：内容与编译回执不符（编译之后被换过？）")
        else:
            receipt_verdict = "consistent"

    dimensions = {"tables": tables_verdict, "files": files_verdict, "receipt": receipt_verdict}
    return _result(dimensions, drift, problems, anchor=anchor, receipt=receipt, out=out)


def _result(dimensions: Mapping[str, str], drift: list[str], problems: list[str], *,
            anchor: Mapping[str, Any] | None, receipt: Mapping[str, Any] | None,
            out: Path) -> dict[str, Any]:
    """把三维的结论合成总体结论（取最坏的一档），并附上读数。"""
    order = {"consistent": 0, "unknown": 1, "drifted": 2}
    verdict = "consistent"
    for v in dimensions.values():
        if order.get(v, 1) > order[verdict]:
            verdict = v
    hist = history(out, limit=5)
    return {
        "verdict": verdict,
        "dimensions": dict(dimensions),
        "drift": drift,
        "problems": problems,
        "anchor_present": (out / ANCHOR_NAME).is_file(),
        "receipt_present": (out / RECEIPT_NAME).is_file(),
        "anchor_path": str(out / ANCHOR_NAME),
        "receipt_path": str(out / RECEIPT_NAME),
        "rendered_at": (anchor or {}).get("generated_at"),
        "compiled_at": (receipt or {}).get("compiled_at"),
        "receipt": dict(receipt or {}),
        "checked": {"tables": len(ANCHOR_TABLES),
                    "files": len((anchor or {}).get("files") or {})},
        # 历史是读数不是判据：它回答"这份包被渲染/编译过几次、最近一次是什么时候"，
        # 不参与三维判定（判定只看当前状态）。
        "history": {"present": hist["present"], "total": hist["total"],
                    "renders": hist["renders"], "compiles": hist["compiles"],
                    "last_render_at": hist.get("last_render_at"),
                    "last_compile_at": hist.get("last_compile_at"),
                    "problems": hist["problems"]},
        "note": ("三维：tables（源表行数+规范哈希）/ files（渲染出的源文件）/ "
                 "receipt（PDF 由哪个 tex 编出）。总体取最坏的一档；"
                 "unknown = 这一维判不了，不许读成没问题。"),
    }


def selftest() -> int:
    """自检（离线、临时目录里造一个假项目）：三维各自的漂移与"判不了"。"""
    import tempfile

    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="renderanchor-selftest-") as td:
        root = Path(td) / "proj"
        out = root / "out" / "paper"
        out.mkdir(parents=True)
        from .store import Store

        st = Store(root)
        # `force=True`：自检先摆好包目录（`out/paper/`）再 init，正是 init 守卫要拦的
        # 形态（"非空且不像工作区"）—— 这里显式声明意图，与项目脚本 `p10_p11_meta.py` 同。
        st.init(force=True)
        (out / "main.tex").write_text("\\date{2026-01-01}\nbody\n", encoding="utf-8")
        (out / "main.pdf").write_bytes(b"%PDF-1.4 fake")

        # 没有锚 ⇒ unknown（不是一致）
        got = check_package(root, store=st)
        if got["verdict"] != "unknown" or not got["problems"]:
            problems.append(f"没有锚时没判 unknown：{got}")

        anchor = build_anchor(st, out)
        (out / ANCHOR_NAME).write_text(json.dumps(anchor), encoding="utf-8")
        # 有锚、没有回执 ⇒ receipt 那一维 unknown ⇒ 总体 unknown
        got = check_package(root, store=st)
        if got["verdict"] != "unknown" or got["dimensions"]["receipt"] != "unknown":
            problems.append(f"没有回执时没判 unknown：{got['dimensions']}")

        receipt = build_receipt(out, tex_sha256=file_digest(out / "main.tex"), pages=1,
                                markers_missing=[], pdf_bytes=13, compiler_exit_codes=[0])
        (out / RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
        got = check_package(root, store=st)
        if got["verdict"] != "consistent":
            problems.append(f"锚+回执都齐时没判一致：{got['drift']} {got['problems']}")

        # 表漂移：往 `conjectures` 里真写一行（字段按 `schema.Conjecture` 的必填项给全）
        with st.tx("conjectures", actor="selftest") as tx:
            tx.upsert("conjectures", {"conjecture_id": "0001", "statement": "x 收敛",
                                      "negation_statement": "x 不收敛", "form": "universal",
                                      "testable": True, "origin": "selftest",
                                      "status": "proposed", "experiment_ids": [],
                                      "created_at": "2026-01-01T00:00:00",
                                      "created_by": "selftest"})
        got = check_package(root, store=st)
        if got["verdict"] != "drifted" or got["dimensions"]["tables"] != "drifted":
            problems.append(f"表漂移没判出来：{got['dimensions']} {got['drift']}")

        # 源文件漂移
        (out / ANCHOR_NAME).write_text(json.dumps(build_anchor(st, out)), encoding="utf-8")
        (out / "main.tex").write_text("\\date{2026-01-02}\nbody changed\n", encoding="utf-8")
        got = check_package(root, store=st)
        if got["dimensions"]["files"] != "drifted":
            problems.append(f"文件漂移没判出来：{got['dimensions']}")

        # 回执与 tex 不符（"PDF 是从旧 tex 编的"）
        (out / ANCHOR_NAME).write_text(json.dumps(build_anchor(st, out)), encoding="utf-8")
        got = check_package(root, store=st)
        if got["dimensions"]["receipt"] != "drifted" or "旧 tex" not in " ".join(got["drift"]):
            problems.append(f"旧 tex 那一格没判出来：{got['dimensions']} {got['drift']}")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（三维：锚缺/回执缺 → unknown；表漂移、文件漂移、旧 tex → drifted）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())
