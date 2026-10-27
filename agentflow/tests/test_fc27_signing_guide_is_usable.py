"""FC-27 签字说明书的可用性判据：说明书本身也是要被机器核的。

为什么单独立一条：说明书最容易烂成"写的时候对、三个月后每条命令都变了"。
这份文档是给人操作的单子 —— 它里面的命令跑不通，人就会自己发明流程，
而那正好是 FC-27 最怕的形态（"测试全绿、上线即越权"的同一类：流程看着有、其实没走）。

判据只钉"可操作性"与"三条硬边界在不在"，不钉里面那份会变的数字（待签条数）：
那条数字以 `python scripts/noai_batch_sign.py --list` 为准，说明书自己写着"以命令为准"。
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "FC27-SIGNING-GUIDE-2026-10-27.md"
SIGN = ROOT / "scripts" / "noai_batch_sign.py"
GATE = ROOT / "scripts" / "noai_gate.py"


def _doc() -> str:
    assert DOC.is_file(), f"说明书不见了：{DOC}（它是这一批签字流程的唯一操作单）"
    return DOC.read_text(encoding="utf-8")


def test_the_guide_exists_and_names_the_two_human_tools() -> None:
    """正控：说明书点名了「签字前端」与「门」两件工具，且都真的在盘上。"""
    text = _doc()
    assert "scripts/noai_batch_sign.py" in text, "说明书没点名签字前端"
    assert "scripts/noai_gate.py" in text, "说明书没点名门本体"
    assert SIGN.is_file() and GATE.is_file(), "说明书点名的工具不在盘上"


def test_the_three_hard_lines_are_written_down() -> None:
    """三条不许越过的线必须逐条写着（缺一条，读的人就会自己补一条）。"""
    text = _doc()
    for needle, why in (
        ("登记 ≠ 批准", "登记与批准必须分开写，否则人会拿 --baseline 当签字"),
        ("两条不同的名字", "批准数是按不同姓名计的，这条不说清就会有人自己签两次"),
        ("scope", "scope 必须具体，否则门会拒（而人不知道为什么）"),
    ):
        assert needle in text, f"说明书缺了「{why}」那一条（找不到 {needle!r}）"


def test_the_guide_gives_a_runnable_scope_template() -> None:
    """模板必须带 `{path}` 与 `{sha12}`：只有它们让每条 scope 各自具体。

    反真空：把这两处占位从文档里删掉 ⇒ 这条红（说明"模板在文档里"是可被破坏的事实）。
    """
    text = _doc()
    assert "--scope-template" in text, "说明书没给 --scope-template（只给 --scope 会写不出逐条具体的 scope）"
    for ph in ("{path}", "{lines}", "{sha12}", "{batch}"):
        assert ph in text, f"scope 模板缺占位 {ph}"


def test_the_guide_forbids_the_ai_from_signing() -> None:
    """硬边界第四条：AI 不许代办批准。这条必须写在说明书里，不能只写在代码注释里。"""
    text = _doc()
    assert "--approve" in text, "说明书没提到 --approve（人签字的那个动作）"
    assert "AI" in text, "说明书没写「AI 不许签」这一条"


def test_the_cli_actually_supports_what_the_guide_promises() -> None:
    """接线：说明书承诺的每个开关，`--help` 里都得真有。

    这一条是"文档与实现同源"的机械核：文档里出现 `--xxx`，CLI 的 help 里就必须有它。
    只核说明书正文里出现的那几个（`--all` / `--scope-template` / `--report-out` /
    `--status-json` / `--dry-run` / `--reviewer` / `--batch`），不去解析全量 help。
    """
    help_text = subprocess.run(
        [sys.executable, str(SIGN), "--help"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    assert help_text.returncode == 0, help_text.stderr[-400:]
    promised = sorted(set(re.findall(r"`?(--[a-z][a-z-]+)`?", _doc())))
    checked = [p for p in promised if p in {
        "--all", "--paths", "--scope", "--scope-template", "--batch", "--note",
        "--report-out", "--status-json", "--dry-run", "--yes", "--reviewer",
        "--verdict", "--list",
    }]
    assert len(checked) >= 6, f"说明书里能认出的开关太少（{checked}）⇒ 这条判据失去对象"
    missing = [p for p in checked if p not in help_text.stdout]
    assert not missing, f"说明书承诺了这些开关，而 CLI 的 --help 里没有：{missing}"
