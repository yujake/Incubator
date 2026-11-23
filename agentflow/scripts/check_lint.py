"""`check_lint` —— 机械可查规则（R001–R012）的一层包装：error>0 就退出 1。

用法：

```
python scripts/check_lint.py                    # 扫本产品根（脚本的上一级）
python scripts/check_lint.py --root . --strict    # 严格模式（warning 也算失败）
python scripts/check_lint.py --json
python scripts/check_lint.py --selftest
```

退出码（三态）：

- `0` = 查过了、0 条 error；
- `1` = 查过了、有 error（`--strict` 下 warning 也算这条）；
- `2` = 没查成（产品根不在、读不到 `scripts/lint_rules.py`、内层 linter 自己以 2 结束、
  超时、或它写不出可解析的 JSON）。

## 为什么不在这里重写规则

12 条规则的实现、豁免表、反真空下限都在 `scripts/lint_rules.py` 里，改它们要按禁改区
的规矩走（它自己就在 `.noai-paths` 的 auth-audit 分组里）。本脚本一个判据都不写：
它只负责（1）在目标根上把 linter 跑起来，（2）把内层的退出码与 `error_count` 翻成
三态，（3）把逐条 error 原样带出来。重写一份等于造第二个判据，两份迟早分家。

## 为什么内层要按目标根去找

`--root` 可以指另一棵树（干净 clone、候选检出）。那一棵树上的 lint 必须由它自己的
`scripts/lint_rules.py` 判 —— 用本机的规则去判别人的树，判的是这一台的口径。
目标根没有 `scripts/lint_rules.py` 时才退回本脚本同级那一份，并在读数里点名用的是哪一份。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROG = "check_lint"

EXIT_OK = 0
EXIT_BAD = 1
EXIT_UNKNOWN = 2

#: 内层 linter 的默认超时（秒）。本机实测全量 419 个 src 文件约 50 秒，留足余量；
#: 超时按"没查成"（2）处理，绝不按"0 error"处理。
DEFAULT_TIMEOUT = 900

#: 逐条 error 最多带出几条（`--max-errors` 可改；JSON 里 `error_count` 仍是全量）。
DEFAULT_MAX_ERRORS = 20


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码（GBK 重定向下打印 `⇒` 会抛，进程退 1 = 假红）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _product_root() -> Path:
    """本脚本所属的产品根（`scripts/` 的上一级）。"""
    return Path(__file__).resolve().parents[1]


def resolve_linter(root: Path) -> tuple[Path | None, str]:
    """找这一趟要用的 linter：目标根的同名脚本优先，其次本脚本同级。

    返回 `(路径, 来源说明)`；两处都没有时路径为 `None`。
    """
    in_root = Path(root) / "scripts" / "lint_rules.py"
    if in_root.is_file():
        return in_root, "目标根自己的 scripts/lint_rules.py"
    sibling = Path(__file__).resolve().parent / "lint_rules.py"
    if sibling.is_file():
        return sibling, "本脚本同级的 lint_rules.py（目标根没有这一份）"
    return None, "两处都读不到 lint_rules.py"


def _tail(text: str, limit: int = 1200) -> str:
    """取输出尾部（报错现场在最后几行，抬头那几行信息量最低）。"""
    clean = (text or "").strip()
    return clean if len(clean) <= limit else "…" + clean[-limit:]


def _trim_errors(errors: list, limit: int) -> list[dict]:
    """把内层的逐条 error 收成短字典清单（只留能复算现场的那几个字段）。"""
    out: list[dict] = []
    for one in errors[: max(int(limit), 0)]:
        if not isinstance(one, dict):
            continue
        out.append({"rule": str(one.get("rule") or ""),
                    "path": str(one.get("path") or ""),
                    "line": one.get("line"),
                    "message": str(one.get("message") or "")})
    return out


def run(root: Path | str, *, strict: bool = False, timeout: int = DEFAULT_TIMEOUT,
        max_errors: int = DEFAULT_MAX_ERRORS) -> tuple[int, dict]:
    """跑一遍 linter 并给出 `(退出码, 读数)`。任何"没跑成"都落 2。"""
    root_path = Path(root).resolve()
    payload: dict = {
        "script": PROG,
        "root": str(root_path),
        "linter": "",
        "linter_from": "",
        "strict": bool(strict),
        "inner_exit": None,
        "counts": {},
        "rules_run": [],
        "scanned": {},
        "errors": [],
        "stdout_tail": "",
        "stderr_tail": "",
        "state": "unknown",
        "exit_code": EXIT_UNKNOWN,
        "reason": "",
    }
    if not root_path.is_dir():
        payload["reason"] = f"产品根不存在：{root_path} ⇒ 没查成（不是「0 条 error」）"
        return EXIT_UNKNOWN, payload

    linter, where = resolve_linter(root_path)
    payload["linter_from"] = where
    if linter is None:
        payload["reason"] = (f"{where} ⇒ 没查成（本脚本刻意不重写规则："
                             "判据本体只有 scripts/lint_rules.py 一份）")
        return EXIT_UNKNOWN, payload
    payload["linter"] = str(linter)

    with tempfile.TemporaryDirectory(prefix="b7-check-lint-") as tmp:
        out_json = Path(tmp) / "lint-report.json"
        cmd = [sys.executable, str(linter), "--root", str(root_path),
               "--json-out", str(out_json)]
        if strict:
            cmd.append("--strict")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            payload["reason"] = (f"内层 linter 超过 {timeout} 秒没结束 ⇒ 没查成"
                                 "（超时不是「0 条 error」）")
            return EXIT_UNKNOWN, payload
        except OSError as exc:
            payload["reason"] = f"起不了内层 linter：{type(exc).__name__}: {exc} ⇒ 没查成"
            return EXIT_UNKNOWN, payload

        payload["inner_exit"] = proc.returncode
        payload["stdout_tail"] = _tail(proc.stdout)
        payload["stderr_tail"] = _tail(proc.stderr)

        if proc.returncode == EXIT_UNKNOWN:
            payload["reason"] = ("内层 linter 自己以 2 结束（扫描失败 / 读不到源码树）"
                                 "⇒ 没查成")
            return EXIT_UNKNOWN, payload
        if proc.returncode not in (EXIT_OK, EXIT_BAD):
            payload["reason"] = (f"内层 linter 的退出码是 {proc.returncode}（既不是 0/1/2）"
                                 f"⇒ 检查器自身失败，没查成。stderr：{payload['stderr_tail']}")
            return EXIT_UNKNOWN, payload

        if not out_json.is_file():
            payload["reason"] = (f"内层 linter 没有写出 {out_json}"
                                 f"（退出码 {proc.returncode}）⇒ 读不到逐条读数，没查成")
            return EXIT_UNKNOWN, payload
        try:
            doc = json.loads(out_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            payload["reason"] = f"内层 linter 的 JSON 读不出来：{type(exc).__name__}: {exc} ⇒ 没查成"
            return EXIT_UNKNOWN, payload

    error_count = int(doc.get("error_count") or 0)
    warning_count = int(doc.get("warning_count") or 0)
    payload["counts"] = {"error": error_count, "warning": warning_count,
                         "info": int(doc.get("info_count") or 0)}
    payload["rules_run"] = list(doc.get("rules_run") or ())
    payload["scanned"] = dict(doc.get("scanned") or {})
    payload["errors"] = _trim_errors(list(doc.get("errors") or ()), max_errors)

    # 内层自相矛盾（说 0 而报告里 error 非 0）不是"通过"，也不是"检出缺陷" ——
    # 那是检查器坏了：读数不可信，按没查成落 2。
    if error_count > 0 and proc.returncode == EXIT_OK:
        payload["reason"] = (f"内层 linter 以 0 结束、却报告 error {error_count} 条"
                             "⇒ 检查器自相矛盾，没查成（不许读成通过）")
        return EXIT_UNKNOWN, payload

    if error_count > 0:
        payload["state"], code = "bad", EXIT_BAD
        payload["reason"] = (f"error {error_count} 条"
                             f"（warning {warning_count} 条不改退出码）")
    elif proc.returncode == EXIT_BAD:
        payload["state"], code = "bad", EXIT_BAD
        payload["reason"] = (f"内层以 1 结束（--strict 下 warning {warning_count} 条也算失败）")
    else:
        payload["state"], code = "ok", EXIT_OK
        payload["reason"] = f"0 条 error（warning {warning_count} 条 / info {payload['counts']['info']} 条）"
    payload["exit_code"] = code
    return code, payload


def render_text(payload: dict) -> str:
    """人读版：抬头三行、逐条 error、末尾结论与理由。"""
    lines = [f"产品根 {payload['root']}",
             f"三态   state={payload['state']}  exit={payload['exit_code']}"]
    if payload["linter"]:
        lines.append(f"判据   {payload['linter']}")
        lines.append(f"来源   {payload['linter_from']}")
    counts = payload.get("counts") or {}
    if counts:
        mode = "严格（发布级）" if payload["strict"] else "日常"
        lines.append(f"读数   error {counts.get('error')} / warning {counts.get('warning')} "
                     f"/ info {counts.get('info')}；规则 {len(payload['rules_run'])} 条；模式 {mode}")
        scanned = payload.get("scanned") or {}
        if scanned:
            lines.append(f"扫描面 src {scanned.get('src_py')} 个 .py / tests {scanned.get('tests_py')} 个 .py")
    errors = payload.get("errors") or []
    if errors:
        total = counts.get("error") or len(errors)
        lines.append("")
        lines.append(f"逐条 error（带出 {len(errors)} / 共 {total} 条）：")
        for one in errors:
            lines.append(f"  {one['rule']} {one['path']}:{one['line']}  {one['message'][:200]}")
    elif payload["state"] == "ok":
        lines.append("")
        lines.append("逐条 error：无（查过了、没有 error）")
    if payload.get("stderr_tail"):
        lines.append("")
        lines.append("内层 stderr 尾部：")
        lines.append("  " + payload["stderr_tail"].replace("\n", "\n  "))
    lines.append("")
    lines.append({0: "结论：0 条 error（0）",
                  1: "结论：有 error（1）—— 逐条见上",
                  2: "结论：没查成（2）—— 0 不是「没有 error」"}[payload["exit_code"]])
    lines.append(f"理由：{payload['reason']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 自测
#: 夹具里的内层 linter 替身。它只做一件事：按模式写一份与 `lint_rules.py`
#: 同形状的 JSON，并以对应的码结束。自测测的是本脚本的三态映射契约，不是 12 条规则。
_FIXTURE_LINTER = '''"""(夹具) 内层 linter 的替身：按 MODE 给 0 / 1 / 崩 三种读数。"""

import argparse
import json
import sys

MODE = {mode!r}

ap = argparse.ArgumentParser()
ap.add_argument("--root")
ap.add_argument("--json-out")
ap.add_argument("--strict", action="store_true")
args = ap.parse_args()

if MODE == "crash":
    print("夹具：内层 linter 自己崩了", file=sys.stderr)
    raise SystemExit(3)

one = {{"rule": "FIXTURE", "level": "error", "path": "src/agentflow/x.py", "line": 7,
        "message": "夹具造的红：bare except pass", "snippet": "except Exception: pass"}}
errors = [one, dict(one, line=9)] if MODE == "red" else []
doc = {{"errors": errors, "warnings": [], "infos": [],
        "error_count": len(errors), "warning_count": 0, "info_count": 0,
        "rules_run": ["FIXTURE"], "scanned": {{"src_py": 1, "tests_py": 0}}}}
with open(args.json_out, "w", encoding="utf-8", newline="") as fh:
    fh.write(json.dumps(doc, ensure_ascii=False))
raise SystemExit(1 if errors else 0)
'''


def _write_lf(path: Path, text: str) -> None:
    """按 UTF-8 + LF 写文本（新文件带 CRLF 会被 lint 的 R012 记成 error）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _fixture(root: Path, mode: str) -> Path:
    """造一个夹具产品根，内层 linter 是 `_FIXTURE_LINTER` 的那个替身。"""
    _write_lf(root / "scripts" / "lint_rules.py", _FIXTURE_LINTER.format(mode=mode))
    _write_lf(root / "src" / "agentflow" / "x.py", '"""夹具源码。"""\n')
    return root


def selftest() -> int:
    """三条自测：通过（0 error）/ 失败（2 error）/ 没查成（内层崩溃），外加根不在。"""
    rows: list[tuple[str, str, int, int]] = []
    with tempfile.TemporaryDirectory(prefix="b7-check-lint-") as tmp:
        base = Path(tmp)
        for mode, kind, detail, want in (
            ("green", "通过", "内层 0 条 error", EXIT_OK),
            ("red", "失败", "内层 2 条 error", EXIT_BAD),
            ("crash", "没查成", "内层以 3 结束、没写 JSON", EXIT_UNKNOWN),
        ):
            code, _payload = run(_fixture(base / mode, mode), max_errors=5)
            rows.append((kind, detail, want, code))
        code, _payload = run(base / "does-not-exist")
        rows.append(("没查成", "产品根不存在", EXIT_UNKNOWN, code))

    print("自测（夹具是 tempfile 里的最小产品根；内层 linter 是替身，"
          "本脚本只测三态映射契约，12 条规则由 scripts/lint_rules.py 自己负责）")
    bad = 0
    for kind, detail, want, got in rows:
        flag = "OK  " if want == got else "BAD "
        if want != got:
            bad += 1
        print(f"  [{flag}] {kind:4s} 期望 exit={want} 实际 exit={got}  （{detail}）")
    print(f"自测结论：{len(rows) - bad}/{len(rows)} 条符合期望")
    return EXIT_OK if not bad else EXIT_UNKNOWN


def main(argv: list[str] | None = None) -> int:
    """入口：解析参数、跑 linter、按三态返回退出码。"""
    _pin_utf8()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=("机械规则（scripts/lint_rules.py）的包装："
                     "0 无 error / 1 有 error / 2 没查成"),
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=str(_product_root()),
                        help="产品根（缺省 = 本脚本的上一级，即 agentflow/）")
    parser.add_argument("--strict", action="store_true",
                        help="严格模式：warning 也算失败（原样传给内层 linter）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"内层 linter 的超时秒数（缺省 {DEFAULT_TIMEOUT}；超时按没查成）")
    parser.add_argument("--max-errors", type=int, default=DEFAULT_MAX_ERRORS,
                        help=f"逐条带出几条 error（缺省 {DEFAULT_MAX_ERRORS}；计数仍是全量）")
    parser.add_argument("--json", action="store_true", help="输出机器读数")
    parser.add_argument("--selftest", action="store_true",
                        help="用 tempfile 造最小夹具自测（通过 / 失败 / 没查成）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    code, payload = run(args.root, strict=args.strict, timeout=args.timeout,
                        max_errors=args.max_errors)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
