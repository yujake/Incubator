"""`check_three_cells` —— 三格现算（体量不许比基线更差），交付面可自检的第一个门。

用法：

```
python scripts/check_three_cells.py                  # 量本产品根（脚本的上一级）
python scripts/check_three_cells.py --root .           # 显式给产品根
python scripts/check_three_cells.py --json
python scripts/check_three_cells.py --selftest
```

三格是：

| 格 | 口径 | 计算处 |
|---|---|---|
| `gt800` | `src/agentflow/**/*.py` 里严格大于 800 行的文件数 | `tools/repo_survey.py::survey` |
| `fn200` | 源码跨度严格大于 200 行的 `def` 个数（`class` 不算进这一格） | 同上 |
| `dup` | 跨文件逐字重复的 docstring 段数（段长 >= 80 字符） | 同上 |

退出码（三态，与 `noai_gate.py` / `check_wellformed.py` 同源）：

- `0` = 量到了、三格都不超过基线；
- `1` = 量到了、至少一格超过基线（逐格打出「现算 / 基线 / 差多少」）；
- `2` = 没量成（产品根不存在、读不到 `tools/repo_survey.py`、扫描面里一个 `.py` 都没有）。

`2` 绝不折成 `0`：这三格的基线是"不许变差"，而"没量"与"没变差"是两件事。

## 为什么基线是脚本里的常量，而不是 `tests/` 里的那一份

业主 2026-11-21 裁定 `tests/` 不随仓库交付，于是
`tests/test_repo_survey_does_not_get_worse.py` 那份基线在交付面上不存在 ——
别人拿到仓库就只能读 `tools/repo_survey.py` 的原始数字，无从判断"这个数字算不算坏"。
数值基线本身只有三个整数，它属于"判据的输入"，写在这里才让"三格"成为一条可执行的门。
它只许被下调：超过它就退出 1 是这条门的全部意义。

## 为什么不在这里重算

三个数的口径里有一堆容易漂的细节（行数用 `splitlines()`、函数跨度用
`end_lineno - lineno + 1`、docstring 段按空行切再逐行 `strip()`、重复要求 >= 80 字符
且跨 >= 2 个文件）。重写一份就等于造第二个口径，两份口径迟早会在某个数上分家，
而这个仓库最贵的缺陷正是这一类。所以本脚本只做三件事：加载 `tools/repo_survey.py`、
拿三个数、与常量比。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

PROG = "check_three_cells"

EXIT_OK = 0
EXIT_BAD = 1
EXIT_UNKNOWN = 2

#: 交付面的三格基线（严格大于即越线）。2026-11-22 15:47 +0800 在本机现盘复测一致：
#: `python tools/repo_survey.py --root . --json` ⇒ `gt800=72` / `function_gt200=95` /
#: `dup_docstring_segments=2`（扫描面 419 个 src `.py`、1373 个 tests `.py`）。
#:
#: 历史读数（不要拿来当"现在"）：`docs/SYSTEM-INTRO.md` §8.1 的表里仍写 `75 / 95 / 2`
#: —— 那个 75 是 2026-11-21 之前的读数，之后本机降到了 72。文档的滞后由这一行如实记下：
#: 脚本里的数才是"这一趟跑出来的数要跟谁比"。
BASELINE: dict[str, int] = {"gt800": 72, "fn200": 95, "dup": 2}

#: 基线是什么时候、在哪棵树上量的（写进 `--json` 的读数里，别让数字失去时间）。
BASELINE_MEASURED_AT = "2026-11-22T15:47+08:00"

#: 三个格名到 `repo_survey.survey()` 返回值的取数路径。键是 `--baseline` 认的名字。
CELL_PATHS: dict[str, tuple[str, ...]] = {
    "gt800": ("big_files", "gt800"),
    "fn200": ("long_defs", "function_gt200"),
    "dup": ("dup_docstring_segments",),
}

#: `--baseline` 的别名（人写 `fn>200` / `dup_segments` 都认，落到同一个格名）。
BASELINE_ALIASES: dict[str, str] = {
    "gt800": "gt800",
    "gt_800": "gt800",
    "big_gt800": "gt800",
    "fn200": "fn200",
    "fn_200": "fn200",
    "fn>200": "fn200",
    "function_gt200": "fn200",
    "dup": "dup",
    "dup_segments": "dup",
    "dup_docstring_segments": "dup",
}

#: 人读的三格说明（一处文案，JSON 里也用它，免得两处各写一句）。
CELL_WHY: dict[str, str] = {
    "gt800": "src 里严格大于 800 行的文件数（软基线：不是缺陷，加一行就成债）",
    "fn200": "源码跨度严格大于 200 行的 def 个数（class 不算进这一格）",
    "dup": "跨文件逐字重复的 docstring 段数（段长 >= 80 字符）",
}


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码。

    不钉的后果（实测）：GBK 重定向下打印含 `⇒` 的行会抛 UnicodeEncodeError，进程以 1
    结束 —— 而那正是"发现问题"的码，于是"打印不出来"被读成"三格越线"。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _product_root() -> Path:
    """本脚本所属的产品根（`scripts/` 的上一级）。"""
    return Path(__file__).resolve().parents[1]


def load_survey(root: Path):
    """按路径加载目标树的 `tools/repo_survey.py`；读不到返回 `None`。

    为什么按目标根加载而不是按本脚本同级：`--root` 可以指另一棵树（例如干净 clone
    或某个候选检出），那一棵树上的体量读数必须由它自己的 `repo_survey.py` 量 ——
    拿本机的计算器去量别人的树，量出来的口径是这一台的，不是那一棵的。
    """
    path = Path(root) / "tools" / "repo_survey.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_repo_survey_for_three_cells", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - 加载失败也是"没查成"，由调用方落 2
        return None
    return mod


def effective_baseline(overrides: list[str] | None) -> tuple[dict[str, int], list[str]]:
    """算这一趟要比的基线：默认常量 + `--baseline k=v`；返回 `(基线, 坏参数)`。

    基线可以下调（局部验收时把门收紧），也可以上调（老树上的读数比新基线差）——
    但两者都会在读数里显式打出"来自命令行"，否则读报告的人会以为它是那个常量。
    """
    base = dict(BASELINE)
    problems: list[str] = []
    for raw in overrides or ():
        text = str(raw).strip()
        if "=" not in text:
            problems.append(f"`--baseline {text}` 不是 key=value 形状")
            continue
        key, _, value = text.partition("=")
        name = BASELINE_ALIASES.get(key.strip().lower(), "")
        if not name:
            problems.append(f"`--baseline` 不认这个格名：{key!r}"
                            f"（认：{sorted(BASELINE)}，别名 {sorted(set(BASELINE_ALIASES))}）")
            continue
        try:
            base[name] = int(value.strip())
        except ValueError:
            problems.append(f"`--baseline {text}` 的值不是整数：{value!r}")
    return base, problems


def _cell_value(data: dict, name: str) -> int | None:
    """从 `repo_survey.survey()` 的返回值里取一格；取不到返回 `None`（不是 0）。"""
    cur: object = data
    for key in CELL_PATHS[name]:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur if isinstance(cur, int) else None


def run(root: Path | str, *, baseline_overrides: list[str] | None = None,
        top: int = 5) -> tuple[int, dict]:
    """量一遍并给出 `(退出码, 读数)`。不给 `repo_survey` 就落 `2`，绝不当 0。"""
    root_path = Path(root).resolve()
    base, bad = effective_baseline(baseline_overrides)
    payload: dict = {
        "script": PROG,
        "root": str(root_path),
        "baseline": dict(base),
        "baseline_defaults": dict(BASELINE),
        "baseline_measured_at": BASELINE_MEASURED_AT,
        "baseline_overrides": list(baseline_overrides or ()),
        "cells": {},
        "problems": list(bad),
        "survey": {"module": "", "scanned": {}, "lines": {}, "unparsable": []},
        "state": "unknown",
        "exit_code": EXIT_UNKNOWN,
        "reason": "",
    }
    if bad:
        payload["reason"] = "命令行给的基线读不懂：" + "；".join(bad) + " ⇒ 没查成"
        return EXIT_UNKNOWN, payload
    if not root_path.is_dir():
        payload["reason"] = f"产品根不存在：{root_path} ⇒ 没查成（不是「三格没越线」）"
        return EXIT_UNKNOWN, payload

    survey = load_survey(root_path)
    if survey is None:
        payload["reason"] = (f"读不到 {root_path / 'tools' / 'repo_survey.py'}"
                             "（三格的计算处）⇒ 没查成。本脚本刻意不重算：重写一份就多一个口径")
        return EXIT_UNKNOWN, payload

    try:
        data = survey.survey(str(root_path), top=max(int(top), 0))
    except Exception as exc:  # noqa: BLE001 - 计算处自己抛了也是"没查成"
        payload["reason"] = f"repo_survey.survey 自己抛了：{type(exc).__name__}: {exc} ⇒ 没查成"
        return EXIT_UNKNOWN, payload

    payload["survey"] = {
        "module": str(Path(root_path) / "tools" / "repo_survey.py"),
        "scanned": dict(data.get("scanned") or {}),
        "lines": dict(data.get("lines") or {}),
        "unparsable": list(data.get("scanned_files_unparsable") or ()),
    }
    if not data.get("scanned_ok"):
        payload["reason"] = str(data.get("vacuum_reason")
                                or "扫描面里一个 .py 都没有 ⇒ 没查成")
        return EXIT_UNKNOWN, payload

    over = False
    for name in CELL_PATHS:
        value = _cell_value(data, name)
        row = {
            "value": value,
            "baseline": base.get(name),
            "why": CELL_WHY[name],
            "ok": None,
            "detail": "",
        }
        if value is None:
            row["detail"] = "计算处没有给出这一格 ⇒ 这一格没查成"
            payload["problems"].append(f"{name}：{row['detail']}")
        elif base.get(name) is not None and value > int(base[name]):
            row["ok"] = False
            row["detail"] = f"现算 {value} > 基线 {base[name]}（多 {value - int(base[name])}）"
            payload["problems"].append(f"{name}：{row['detail']} ⇒ 体量变差了")
            over = True
        else:
            row["ok"] = True
            row["detail"] = f"现算 {value} <= 基线 {base[name]}"
        payload["cells"][name] = row

    missing = [n for n, r in payload["cells"].items() if r["value"] is None]
    if over:
        payload["state"], code = "over", EXIT_BAD
        payload["reason"] = "三格里有格超过基线：" + "；".join(payload["problems"])
    elif missing:
        payload["state"], code = "unknown", EXIT_UNKNOWN
        payload["reason"] = ("这些格计算处没给出读数：" + "、".join(missing)
                             + " ⇒ 没查成（不是「没越线」）")
    else:
        payload["state"], code = "ok", EXIT_OK
        payload["reason"] = "三格现算都不超过基线"
    payload["exit_code"] = code
    return code, payload


def render_text(payload: dict) -> str:
    """人读版：先给结论，再逐格给「现算 / 基线 / 差」。"""
    lines = [f"产品根 {payload['root']}",
             f"三态   state={payload['state']}  exit={payload['exit_code']}"]
    base = payload["baseline"]
    override = payload.get("baseline_overrides") or []
    lines.append(f"基线   gt800={base.get('gt800')}  fn200={base.get('fn200')}  "
                 f"dup={base.get('dup')}（常量，量于 {payload['baseline_measured_at']}"
                 + ("；本次被命令行覆盖" if override else "") + "）")
    sc = payload.get("survey", {}).get("scanned") or {}
    if sc:
        lines.append(f"扫描面 src {sc.get('src_files')} 个 .py / tests {sc.get('tests_files')} 个 .py")
    lines.append("")
    for name, row in payload["cells"].items():
        mark = {True: "ok ", False: "OVER", None: "??? "}[row["ok"]]
        lines.append(f"  [{mark}] {name:8s} {row['detail']}")
        lines.append(f"          {row['why']}")
    bad = payload.get("survey", {}).get("unparsable") or []
    if bad:
        lines.append("")
        lines.append(f"解析不了的文件 {len(bad)} 个（它们不进长定义与重复段两格）：{bad[:5]}")
    problems = payload.get("problems") or []
    if problems:
        lines.append("")
        lines.append("逐条问题：")
        lines.extend(f"  - {one}" for one in problems)
    lines.append("")
    lines.append({0: "结论：三格都没越线（0）",
                  1: "结论：有格越线（1）—— 不许抬基线，先把它降回去",
                  2: "结论：没查成（2）—— 0 不是「没越线」"}[payload["exit_code"]])
    lines.append(f"理由：{payload['reason']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 自测
#: 重复段样本：每段 >= 80 字符（`repo_survey.DUP_SEGMENT_MIN_CHARS`）、在两个文件里逐字相同
#: ⇒ 计 1 段。刻意写这么长：短于 80 字符的段根本不会进这一格，夹具会静默地"量到 0"。
_DUP_SEGMENT = (
    "这一段说明为什么这一格要按段而不是按整段 docstring 计：整段 docstring 的重复几乎只发生在"
    "复制粘贴整个模块头，而真正会漂的是段 —— 一段说明被抄到第二个文件里、改了一边忘了另一边，"
    "那一段就是负债。按段计才能看见它，按整段计只会看见那些一眼就能认出的整模块复制。"
)


def _copy_survey(src: Path, dst: Path) -> None:
    """把计算处原样拷进夹具（先建目录；`shutil.copyfile` 自己不建）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _write_lf(path: Path, text: str) -> None:
    """按 UTF-8 + LF 写文本（`newline=""` 关掉 Windows 的行尾转换）。

    为什么不用 `Path.write_text`：它在 Windows 上把每个 `\\n` 刷成 `\\r\\n`，而 `scripts/`
    下的新文件带 CRLF 会被 `lint_rules` 的 R012 记成 error（入库即 CRLF）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def selftest() -> int:
    """三条自测：通过 / 失败（重复段超基线）/ 没查成（扫描面为空）。

    夹具里放的是目标树自己的 `tools/repo_survey.py`（从本脚本的产品根原样拷过去）——
    这样三条自测走的是真计算处，而不是一个替身。
    """
    src_survey = _product_root() / "tools" / "repo_survey.py"
    rows: list[tuple[str, str, int, int]] = []
    with tempfile.TemporaryDirectory(prefix="b7-three-cells-") as tmp:
        root = Path(tmp)
        if not src_survey.is_file():
            print(f"自测没跑成：读不到 {src_survey}（三格的计算处）")
            return EXIT_UNKNOWN

        # ---- 通过：一个小文件，三格全 0
        ok_root = root / "ok"
        _copy_survey(src_survey, ok_root / "tools" / "repo_survey.py")
        _write_lf(ok_root / "src" / "agentflow" / "small.py",
                  '"""一个很小的模块。"""\n\n\ndef one() -> int:\n'
                  '    """返回 1。"""\n    return 1\n')
        code, _payload = run(ok_root)
        rows.append(("通过", "小树三格全 0", EXIT_OK, code))

        # ---- 失败：3 段互不相同、但都在两个文件里逐字重复的 docstring（基线 dup=2）
        bad_root = root / "bad"
        _copy_survey(src_survey, bad_root / "tools" / "repo_survey.py")
        # 三段必须彼此不同：`repo_survey` 的重复段是按段文本去重的，同一段抄两遍只算 1 段。
        segments = [f"{_DUP_SEGMENT}（第 {i} 段）" for i in (1, 2, 3)]
        for name in ("a.py", "b.py"):
            body = '"""%s"""\n' % ("\n\n".join(segments))
            _write_lf(bad_root / "src" / "agentflow" / name,
                      body + "\n\ndef f() -> int:\n    \"\"\"d.\"\"\"\n    return 1\n")
        code, payload = run(bad_root)
        rows.append(("失败", f"dup 现算 {payload['cells'].get('dup', {}).get('value')} > 2",
                     EXIT_BAD, code))

        # ---- 没查成：src 面是空的（repo_survey 自己报 scanned_ok=False）
        empty_root = root / "empty"
        _copy_survey(src_survey, empty_root / "tools" / "repo_survey.py")
        (empty_root / "src").mkdir(parents=True)
        code, _payload = run(empty_root)
        rows.append(("没查成", "src 面 0 个 .py", EXIT_UNKNOWN, code))

    print("自测（夹具是 tempfile 里的最小树；计算处是 tools/repo_survey.py 原样拷贝）")
    return _print_selftest_rows(rows)


def _print_selftest_rows(rows: list[tuple[str, str, int, int]]) -> int:
    """打三行读数；有一条不符就以 2 结束（自测本身没通过也是没查成）。"""
    bad = 0
    for kind, detail, want, got in rows:
        flag = "OK  " if want == got else "BAD "
        if want != got:
            bad += 1
        print(f"  [{flag}] {kind:4s} 期望 exit={want} 实际 exit={got}  （{detail}）")
    print(f"自测结论：{len(rows) - bad}/{len(rows)} 条符合期望")
    return EXIT_OK if not bad else EXIT_UNKNOWN


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数、跑三格、按三态返回退出码。"""
    _pin_utf8()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=("三格现算（>800 行文件 / >200 行函数 / 重复 docstring 段），"
                     "与脚本里的基线比：0 没越线 / 1 越线 / 2 没查成"),
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=str(_product_root()),
                        help="产品根（缺省 = 本脚本的上一级，即 agentflow/）")
    parser.add_argument("--baseline", action="append", default=None, metavar="KEY=VALUE",
                        help=("覆盖某一格的基线（可重复，例如 --baseline gt800=72）；"
                              "缺省用脚本里的常量。下调=收紧，上调=放宽，读数里会点名"))
    parser.add_argument("--top", type=int, default=5, help="清单每格取前几条（缺省 5；只影响 JSON 里的清单）")
    parser.add_argument("--json", action="store_true", help="输出机器读数")
    parser.add_argument("--selftest", action="store_true",
                        help="用 tempfile 造最小夹具自测三条（通过 / 失败 / 没查成）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    code, payload = run(args.root, baseline_overrides=args.baseline, top=args.top)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
