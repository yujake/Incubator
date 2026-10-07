"""W5 清仓前的普查（裁定 P1「迁一面删一面」的前置）：每个旧壳符号**谁真的在读它**。

## 为什么要重写一版

第一版按"裸名字在文件里出现过"匹配，于是把无关的同名局部量当成引用：
`tests/test_locallib.py:149` 的 `_page, exc = excerpt_for(...)`、`tests/test_secretary.py:565`
自定义的 `def _run_row(...)` 都被算成"判据在读 views 的私有函数" —— **假引用**。
假引用会让 W5 的删除面凭空缩小（该删的不敢删），所以口径必须收到"真引用形态"上：

1. **限定名**：`views.<name>` · `assets.<name>`（含 `webui.views.<name>` / `web.assets.<name>`）；
2. **导入表**：`from .views import a, b, <name>` / `from agentflow.webui.views import …`
   （**逗号列表也要认** —— `__init__.py` 就是 `from .views import _STOP_BADGES, render_root, render_run`）；
3. **包级再导出**：`webui.<name>` / `W.<name>`（判据里大量用 `W.render_root` 这种形态）；
4. **属性访问链**：`getattr(views, "<name>")` 这类显式字符串（少见但有）。

另外把路径修对：`assets.py` 在 **`web/assets.py`**（不是 `webui/assets.py`）—— 第一版写错了目录，
于是报"不在盘上"，那是一条**假读数**（真读数：30,415 字节，8 个定义）。

重算：
    cd D:\\Incubator\\agentflow
    python -B ..\\temp\\_w5_legacy_census.py
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
import tokenize

ROOT = pathlib.Path(r"D:\Incubator\agentflow")
UI = ROOT / "ui"
#: 旧壳的两个文件（W0 拆包后它们仍在；裁定 P1 要求 W5 时 `views.py` 清空）。
#: 路径按**盘上实况**：`assets.py` 在 `web/` 下，不在 `webui/` 下。
TARGETS = (
    (ROOT / "src" / "agentflow" / "webui" / "views.py", ("views", "webui.views")),
    (ROOT / "src" / "agentflow" / "web" / "assets.py", ("assets", "web.assets")),
)


def _strip_python(text: str) -> str:
    """去掉注释与字符串，**但保留换行与缩进布局**（口径与判据一致：只在"真代码"里数引用）。

    为什么不能用 `" ".join(token.string)`（第一版就是这么写的）：那会把整份文件压成一行，
    于是 `from …views… import ([^\\n]+)` 这类"逐行"的正则一口气吃到文件尾 ⇒ 解析不出导入表，
    `render_root` 这种**真被 `__init__.py` 导入**的符号也被判成"无引用"（假读数，方向危险：
    它会让人以为可以随手删公开面）。现在按 token 的行列把注释/字符串原地抹成空格。
    """
    lines = text.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError:
        return text
    for tok in tokens:
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        for row in range(srow, erow + 1):
            if row - 1 >= len(lines):
                continue
            line = lines[row - 1]
            start = scol if row == srow else 0
            end = ecol if row == erow else len(line.rstrip("\r\n"))
            lines[row - 1] = line[:start] + " " * max(0, end - start) + line[end:]
    return "".join(lines)


def _defs(path: pathlib.Path) -> list[str]:
    """顶层定义：函数 / 类 / **模块级常量名**。

    为什么要带上常量：`web/assets.py` 的文件体几乎全是常量（`THEME_CSS` / `APP_CSS` /
    `STYLESHEET`），只列函数/类会让它显示"0 个顶层定义"，把 W5 对它的判断变成盲区。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.append(node.target.id)
    return out


def _reference_patterns(name: str, aliases: tuple[str, ...]) -> tuple[list[re.Pattern[str]],
                                                                    list[re.Pattern[str]]]:
    """返回 `(强匹配, 弱匹配)`。

    强匹配 = 只可能是"引用这个模块的这个符号"的形态：限定名（`views.render_root`）与
    包级再导出（`webui.render_root` / `W.render_root`）。
    弱匹配 = 裸名字与显式字符串：**可能是同名局部量**（第一版就是被这两条骗了：
    `tests/test_locallib.py` 的局部变量 `_page`、`tests/test_secretary.py` 自己定义的
    `def _run_row(...)`）。弱匹配只打印、**不参与判定**。
    另有 `_import_forms()`（`from …views… import a, b, name`）算强匹配 —— 逗号列表也要认。
    """
    strong = [
        re.compile(rf"(?<![A-Za-z0-9_])(?:{'|'.join(re.escape(a) for a in aliases)})"
                   rf"\.{re.escape(name)}(?![A-Za-z0-9_])"),
        re.compile(rf"(?<![A-Za-z0-9_])(?:webui|W)\.{re.escape(name)}(?![A-Za-z0-9_])"),
    ]
    weak = [
        re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(name)}(?![A-Za-z0-9_])"),
        re.compile(rf"[\"']{re.escape(name)}[\"']"),
    ]
    return strong, weak


def _import_forms(name: str, text: str) -> bool:
    """`from … import … name …` 这一族（逗号列表）单独判，避免 ③ 把局部量算进来。"""
    for m in re.finditer(rf"from\s+[\w.]*(?:views|assets)\s+import\s+([^\n]+)", text):
        imported = {chunk.strip().split(" as ")[0].strip() for chunk in m.group(1).split(",")}
        if name in imported:
            return True
    return False


def main() -> int:
    print("[w5 census] 真引用形态：限定名 / 导入表 / 包级再导出 / 显式字符串")
    scan_py = [p for p in (ROOT / "src").rglob("*.py")] + [p for p in (ROOT / "tests").rglob("*.py")]
    corpus = {p: _strip_python(p.read_text(encoding="utf-8", errors="replace")) for p in scan_py}
    ui_text = {p: p.read_text(encoding="utf-8", errors="replace")
               for p in list(UI.rglob("*.ts")) + list(UI.rglob("*.tsx")) + list(UI.rglob("*.html"))}

    for target, aliases in TARGETS:
        if not target.is_file():
            print(f"\n== {target.relative_to(ROOT)}：**不在盘上**（已被删过？这一件算完成）")
            continue
        lines = target.read_text(encoding="utf-8").splitlines()
        print(f"\n== {target.relative_to(ROOT)}：{len(lines)} 行，{len(_defs(target))} 个顶层定义")
        for name in _defs(target):
            strong, weak = _reference_patterns(name, aliases)
            prod: list[str] = []
            tests: list[str] = []
            weak_prod: list[str] = []
            weak_tests: list[str] = []
            for path, text in corpus.items():
                if path == target:
                    continue
                row = f"{path.relative_to(ROOT).as_posix()}"
                bucket = tests if "tests" in path.parts else prod
                weak_bucket = weak_tests if "tests" in path.parts else weak_prod
                if _import_forms(name, text) or any(p.search(text) for p in strong):
                    bucket.append(row)
                elif any(p.search(text) for p in weak):
                    weak_bucket.append(row)
            front = [p.relative_to(UI).as_posix() for p, text in ui_text.items()
                     if any(pat.search(text) for pat in strong)]
            verdict = ("**判据在读 ⇒ 先改判据再谈删**" if tests
                       else ("生产在读 ⇒ 先迁调用方" if prod
                             else ("页面在消费它的产出 ⇒ 可迁" if front else "**无引用 ⇒ 可删**")))
            note = f"（另有 {len(weak_prod) + len(weak_tests)} 处同名弱匹配，不参与判定）" \
                if (weak_prod or weak_tests) else ""
            print(f"  {name:26s} 生产 {len(prod):2d} · 判据 {len(tests):2d} · 前端 {len(front):2d}"
                  f"  ⇒ {verdict}{note}")
            for row in prod[:3]:
                print(f"        生产: {row}")
            for row in tests[:3]:
                print(f"        判据: {row}")
    print("\n提示：本仪器只回答'谁引用'；'该不该删'还要对着 `draft/73 §2` 的迁移面逐条看，"
          "并注意 `render_root`/`render_run` 是**包级再导出**（public face），删它们等于改公开面。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
