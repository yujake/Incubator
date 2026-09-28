"""`R012`（编排层写产物必须控行尾）：`G-42` 的机器判据（`c-12`）。

## 为什么这条规则要有自己的测试文件

`c-12` 的缺陷不是"少了一条规则"，而是"「被引用的禁令在门里根本不存在」"：
`tools/release_all.py` 的注释写着 `G-42：禁止 Path.write_text()`，而全仓 grep
显示 `RULES` 里当时只有 R001–R011，没有 G-42、也没有任何一条管行尾的规则。
散文不是判据 —— 它会随文件一起漂，而漂的方向永远是"没人再记得它"。

所以这里既测「判据本身」（正控：命中 / 不命中），也测「判据被接上了」
（`RULES` 里有 R012、`--strict` 的退出码会因此变），还测「豁免不会静默」。

## 负控怎么写才算"证明注入生效"

每条正控都配一条「同形的、必然触发的」输入（同一段源码、只改一个关键字），
并且断言两条路径的结论「不同」 —— 只断言"源码里有这个串"是没有判别力的。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("_lint_rules_for_r012",
                                                  ROOT / "scripts" / "lint_rules.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load()


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8", newline="")
    return root


def _write_text_violations(root: Path) -> list[str]:
    return [f"{f.path}:{f.line}" for f in L.rule_R012_write_text_newline(root)]


# ============================================================ 判据本身


def test_r012_is_registered() -> None:
    """规则必须在册 —— 否则"接上了"只是一句注释（`c-12` 的原缺陷形态）。"""
    assert any("R012" in str(entry) for entry in L.RULES), "R012 没有注册到 RULES"


def test_write_text_without_newline_is_a_finding(tmp_path: Path) -> None:
    """正控：`Path(...).write_text(...)` 不带 `newline=` ⇒ 命中（且点名行号）。"""
    root = _tree(tmp_path / "t", {
        "scripts/a.py": '"""a。"""\nimport json\nfrom pathlib import Path\n\n\ndef f(p):\n'
                        '    Path(p).write_text(json.dumps({"a": 1}), encoding="utf-8")\n',
        "tools/keep.py": '"""k。"""\n',
    })
    got = L.rule_R012_write_text_newline(root)
    hits = [f for f in got if f.level == "warning"]
    assert len(hits) == 1, [f.message for f in got]
    assert hits[0].path == "scripts/a.py" and hits[0].line == 7, hits[0]
    assert "newline" in hits[0].message


def test_negative_control_open_with_newline_is_not_a_finding(tmp_path: Path) -> None:
    """负控（同形、只换关键字）：把 `write_text` 换成 `open(..., newline="")` ⇒ 不命中。

    注入口在「同一位置、同一语义」，所以两条结论的差异只能来自那个关键字 ——
    这就是"注入生效"的证据（不是"换个文件所以没命中"）。
    """
    root = _tree(tmp_path / "t", {
        "scripts/a.py": '"""a。"""\nimport json\n\n\ndef f(p):\n'
                        '    with open(p, "w", encoding="utf-8", newline="") as fh:\n'
                        '        fh.write(json.dumps({"a": 1}))\n',
        "tools/keep.py": '"""k。"""\n',
    })
    assert [f for f in L.rule_R012_write_text_newline(root) if f.level == "warning"] == []


def test_write_text_with_explicit_newline_is_allowed(tmp_path: Path) -> None:
    """正控（另一条合规写法）：`write_text(..., newline="")` 不算违规。

    这条与上一条一起说明判据打的是"有没有控住行尾"，不是"用没用 write_text"。
    """
    root = _tree(tmp_path / "t", {
        "scripts/a.py": '"""a。"""\nfrom pathlib import Path\n\n\ndef f(p):\n'
                        '    Path(p).write_text("x\\n", encoding="utf-8", newline="")\n',
        "tools/keep.py": '"""k。"""\n',
    })
    assert [f for f in L.rule_R012_write_text_newline(root) if f.level == "warning"] == []


def test_write_bytes_is_allowed(tmp_path: Path) -> None:
    """正控：`write_bytes` 自己给字节 ⇒ 天然不经过平台换行转换，不算违规。"""
    root = _tree(tmp_path / "t", {
        "scripts/a.py": '"""a。"""\nfrom pathlib import Path\n\n\ndef f(p):\n'
                        '    Path(p).write_bytes(b"x\\n")\n',
        "tools/keep.py": '"""k。"""\n',
    })
    assert [f for f in L.rule_R012_write_text_newline(root) if f.level == "warning"] == []


def test_tests_directory_is_out_of_scope(tmp_path: Path) -> None:
    """边界：`tests/` 不在扫描范围里（它写的是 `tmp_path`，换行不影响任何门）。

    这条把"口径的边界"钉成可判定的：如果有人把 R012 扩大到全仓，
    它会立刻红 —— 那时必须回来重新裁"哪些写法的行尾真的要紧"。
    """
    root = _tree(tmp_path / "t", {
        "scripts/keep.py": '"""k。"""\n',
        "tools/keep.py": '"""k。"""\n',
        "src/agentflow/m.py": '"""m。"""\nfrom pathlib import Path\n\n\ndef f(p):\n'
                              '    Path(p).write_text("x", encoding="utf-8")\n',
        "tests/test_x.py": '"""x。"""\nfrom pathlib import Path\n\n\ndef f(p):\n'
                           '    Path(p).write_text("x", encoding="utf-8")\n',
    })
    got = L.rule_R012_write_text_newline(root)
    assert [f for f in got if f.level == "warning"] == [], [f.path for f in got]


def test_unreadable_file_says_not_checked_instead_of_staying_silent(tmp_path: Path) -> None:
    """反真空：解析不了的 `.py` ⇒ 一条"没查成"的 finding，不许静默跳过。

    "静默跳过"会让"我没读出来"与"这里没问题"在报告里同形 —— 三态纪律。
    """
    root = _tree(tmp_path / "t", {
        "scripts/broken.py": "def f(:\n    pass\n",
        "tools/keep.py": '"""k。"""\n',
    })
    got = [f for f in L.rule_R012_write_text_newline(root) if "没查成" in f.message]
    assert got and got[0].level == "warning", [f.message for f in L.rule_R012_write_text_newline(root)]


def test_missing_orchestrator_dir_says_not_checked(tmp_path: Path) -> None:
    """反真空：连 `scripts/` 都读不到 ⇒ 报"这一半没查成"（不是"干净"）。"""
    root = _tree(tmp_path / "t", {"tools/keep.py": '"""k。"""\n'})
    got = [f for f in L.rule_R012_write_text_newline(root) if "没查成" in f.message]
    assert got, [f.message for f in L.rule_R012_write_text_newline(root)]
    assert "scripts" in got[0].message


# ============================================================ 豁免不许静默


def test_exemption_table_is_not_stale_on_the_real_tree() -> None:
    """正控：真仓库上的豁免登记必须「仍然指着一个真存在、且真的用了 write_text 的文件」。

    登记过期与漏登记同样危险：过期登记让人以为"这一条有人看着"。
    """
    for rel in L.R012_NEWLINE_EXEMPTIONS:
        p = ROOT / rel
        assert p.is_file(), f"豁免指向不存在的文件：{rel}"
        assert "write_text" in p.read_text(encoding="utf-8")
    got = [f for f in L.rule_R012_write_text_newline(ROOT) if f.level == "info"
           and "豁免登记" in f.message]
    assert got == [], [f.message for f in got]


def test_negative_control_a_stale_exemption_is_reported(tmp_path: Path) -> None:
    """负控：豁免表里放一个「不再用 write_text」 的文件 ⇒ 必须报一条 `info` 提醒删登记。"""
    root = _tree(tmp_path / "t", {
        "scripts/keep.py": '"""k。"""\n',
        "tools/keep.py": '"""k。"""\n',
        "tools/exempt.py": '"""e。"""\n',
    })
    saved = dict(L.R012_NEWLINE_EXEMPTIONS)
    try:
        L.R012_NEWLINE_EXEMPTIONS["tools/exempt.py"] = "（桩）理由"
        got = [f for f in L.rule_R012_write_text_newline(root) if "已过期" in f.message]
        assert got and got[0].level == "info", [f.message for f in got]
    finally:
        L.R012_NEWLINE_EXEMPTIONS.clear()
        L.R012_NEWLINE_EXEMPTIONS.update(saved)


def test_negative_control_an_exemption_for_a_missing_file_is_reported(tmp_path: Path) -> None:
    """负控：豁免表指向不存在的文件 ⇒ 也必须报一条 `info`。"""
    root = _tree(tmp_path / "t", {
        "scripts/keep.py": '"""k。"""\n',
        "tools/keep.py": '"""k。"""\n',
    })
    saved = dict(L.R012_NEWLINE_EXEMPTIONS)
    try:
        L.R012_NEWLINE_EXEMPTIONS["tools/gone.py"] = "（桩）理由"
        got = [f for f in L.rule_R012_write_text_newline(root) if "不存在的文件" in f.message]
        assert got and got[0].level == "info", [f.message for f in got]
    finally:
        L.R012_NEWLINE_EXEMPTIONS.clear()
        L.R012_NEWLINE_EXEMPTIONS.update(saved)


# ============================================================ 判据在真仓库上的读数


def test_real_tree_has_no_unexempted_write_text_in_the_orchestrator_layer() -> None:
    """正控（`c-12` 的验收判据）：真仓库的 `scripts/` + `tools/` 里没有漏网的 `write_text`。

    这条是"两处改造干净了"的机器证据：`scripts/release_check.py` 与
    `scripts/lint_rules.py` 的 `--json` 出口本轮都改成了 `open(..., newline="")`，
    所以今天唯一的 `write_text` 是那条登记过的豁免（`tools/make_demo_dataset.py`）。
    """
    hits = [f for f in L.rule_R012_write_text_newline(ROOT) if f.level == "warning"]
    assert hits == [], [(f.path, f.line, f.message) for f in hits]


def test_the_json_artifacts_of_the_orchestrator_layer_are_pure_lf(tmp_path: Path) -> None:
    """正控（`c-12` 的字节级判据）：真跑两个 `--json` 出口 ⇒ 产物里没有 CR。

    `lint_rules.py --root <桩树>` 是秒级的；发布门那一侧只需要走"全部 skip"的
    记账路径（由 `tests/test_release_check_items.py` 覆盖，这里只查 linter 那一处，
    避免同一件事跑两遍）。
    """
    tree = _tree(tmp_path / "tree", {
        "src/agentflow/m.py": '"""m。"""\n',
        # `scripts/keep.py` 必须自带三档退出码（R008），`.noai-paths` 是 R009 判定
        # 禁改区用的（桩树里没有它 ⇒ R009 报一条 error），豁免表里的文件也必须存在。
        "scripts/keep.py": '"""k。"""\n\n\ndef main():\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
        "tools/make_demo_dataset.py": (ROOT / "tools" / "make_demo_dataset.py").read_text(
            encoding="utf-8"),
        ".noai-paths": (ROOT / ".noai-paths").read_text(encoding="utf-8"),
    })
    out = tmp_path / "lint.json"
    p = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lint_rules.py"), "--root", str(tree),
         "--json", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    # 判据只关心「产物的字节」：先断言"脚本真的跑成了"（不是自身失败 2，
    # 也不是因为桩树缺东西而报 error 的 1）——
    # 这一步同时是"我没把桩树写成必然失败"的自校。
    assert p.returncode != 2, p.stdout + p.stderr
    assert "error 0" in p.stdout, ("桩树被写成必然报 error 了（本用例只测产物字节）：\n"
                                   + p.stdout[-600:])
    raw = out.read_bytes()
    assert b"\r" not in raw, "linter 的 --json 产物里有 CR"
    # 顺带断言产物真的是这份 JSON（不是空文件）
    assert json.loads(raw.decode("utf-8"))["rules_run"]
