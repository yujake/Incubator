# -*- coding: utf-8 -*-
"""`--record-audit` 这条 CLI 通路与 `--check-approvals` 的口径一致性。

## 为什么要一个独占的文件（`R6-R1d-1` 的根因）

`R6-R1d-1`（high）不是"某个函数算错了"，而是"库函数有牙、入口没人跑"：
`_run_record_audit` 里读了一个 `record_audit()` 内部才有的局部名（`updated`），
于是 `--record-audit` 每一次调用都以未捕获的 `NameError` 结束，而三个测试文件
（含 R1c 新加的 11 条）全都只调 `G.record_audit(...)` —— 全仓 `tests/` 里
`--record-audit` 这个 CLI 字面量 0 命中。

所以本文件的判据全部走真 CLI（`G.main([...])`），并且写成成对对照：

- 正控：合成工作区里 `--baseline` ⇒ 0，再 `--record-audit` ⇒ 0，台账里真的多一条；
- 负控：把 `scripts/noai_gate.py` 的当前字节复制到 `tmp_path`，只改那一行改回改前形态，
  用子进程跑同一套 CLI，断言非 0 且 stderr 里有那条错误，并打印副本的 sha256
  作为"我跑的是改后/改前版本"的指纹。副本里改不回那一行 ⇒ 判据自己报错
  （防"锚点漂了却静默通过"）。这条负控是自足的：不依赖 `git show`，也不依赖外部环境。

另有一段是本批 low finding 的 CLI 侧读数：`R6-R1d-5`（观察面只由被审对象里真实存在的
标识符构成）、`R6-R1d-6`（CLI 报的维度计数与 JSON 的 `distinct_dimensions` 同口径）、
`R6-R1d-7`（空字形填充码位不许把同一个可见名字算成两个人）。

## 为什么本文件也改 `tests/test_noai_gate_audit_channel.py`

（如实登记，供父代理对账）那个文件不在 FIX6-PLAN 第 1 节给我的清单里，但 `R6-R1d-4`
把判据 0 从"只挡完全独占"改成"直接判 `len(owned) > max_share`"，它的 `_six_clean_audits`
夹具（2 名审计者 × 各 3 个维度）正好落在新判据的下线外 —— 不改它，9 条用例会因为
"夹具本身不合规"而红，而它们的主题（证据锚/回执链）与判据 0 无关。改的是夹具的
审计者分布与两处受影响的断言，判据一条都没放宽。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

#: 仓库根（`scripts/` 是顶层包；conftest 只注入了 `src/`）。
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import noai_gate as G  # noqa: E402

#: 被审对象的相对路径（写进清单与台账的键）。
REL = "src/a.py"

#: 被审对象的正文：定义处包含 alpha / beta / gamma 三个标识符
#: （`_identifiers_of` 取的是定义处的名字，所以 `return alpha + beta` 里的用法不算数）。
TARGET_SRC = '"""夹具：三个符号。"""\n\nalpha = 1\nbeta = 2\n\n\ndef gamma() -> int:\n    return alpha + beta\n'

#: 合规负控（`R5-R1b-6` 四条：长度 ≥40、有"怎么比"、有"比出来什么"、不是重复填充）。
NEGATIVE_CONTROL = (
    "负控：拿改前那一版（`git show HEAD:src/a.py`）跑同一套判据，"
    "它报出『scope 里没有真实标识符』这条红；改后这一版不报。"
)

#: 合规独立性声明（`H-1e`）。台账条目的 `authored` 由 `--baseline` 写成 `unknown`
#: （不给 `--authored` 时的默认值），所以这条声明是必填的。
INDEPENDENCE = "我是子审计代理 F1，与该条目的作者不是同一主体，未参与这次改动的编写。"

#: 门脚本本体（注入负控要复制它）。
GATE = ROOT / "scripts" / "noai_gate.py"


def _sha256_file(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture()
def ws(tmp_path: pathlib.Path):
    """一个合成工作区：被审对象 + 清单 + 证据文件 + 回执链落点。

    回执链落点显式给（`--receipt-log`）：默认落点是仓库自己的 `.noai-audit-receipts.jsonl`，
    测试去写它会污染真仓库（`--record-audit` 与 `--check-approvals` 都接受这个参数）。
    """
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / REL).write_text(TARGET_SRC, encoding="utf-8", newline="\n")
    (root / G.MANIFEST_NAME).write_text(
        "[category: auth-audit] 夹具用的分组\n\n"
        f"{REL}  [category: auth-audit]  夹具用的条目\n",
        encoding="utf-8", newline="\n",
    )
    ev = tmp_path / "evidence.txt"
    ev.write_text(
        "审计者：subagent-A\n"
        f"开审版本 sha256 = {_sha256_file(root / REL)}\n"
        "覆盖 scope 符号：alpha beta gamma\n"
        "负控：拿改前那一版去比，它报红；这一版不报。\n",
        encoding="utf-8", newline="\n",
    )
    receipt = tmp_path / "receipts.jsonl"
    return {
        "root": root,
        "manifest": root / G.MANIFEST_NAME,
        "ledger": root / G.LEDGER_NAME,
        "evidence": ev,
        "receipt": receipt,
    }


def _record_args(ws: dict, scope: str = "alpha beta gamma") -> list[str]:
    """一次合规的 `--record-audit` 的完整参数（少一项就被写入侧拒）。"""
    root = ws["root"]
    return [
        "--record-audit", REL,
        "--root", str(root),
        "--manifest", str(ws["manifest"]),
        "--ledger", str(ws["ledger"]),
        "--receipt-log", str(ws["receipt"]),
        "--auditor", "subagent-A",
        "--dimension", "axes",
        "--evidence", "temp/audit.txt",
        "--evidence-path", str(ws["evidence"]),
        "--evidence-sha256", _sha256_file(ws["evidence"]),
        "--audit-scope", scope,
        "--audit-started-sha256", _sha256_file(root / REL),
        "--independence", INDEPENDENCE,
        "--negative-control", NEGATIVE_CONTROL,
    ]


def _entry_audits(ws: dict) -> list[dict]:
    raw = json.loads(ws["ledger"].read_text(encoding="utf-8"))
    return raw["entries"][0]["audits"]


# ============================================================ 正控：真 CLI 走通


def test_record_audit_cli_exits_zero_and_writes_exactly_one_audit(
    ws: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    """`R6-R1d-1` 正控：`--baseline` ⇒ 0，`--record-audit` ⇒ 0，且台账里多一条审计。"""
    base = G.main(["--baseline", "--paths", REL, "--root", str(ws["root"]),
                   "--manifest", str(ws["manifest"]), "--ledger", str(ws["ledger"]),
                   "--note", "夹具登记"])
    assert base == 0, f"--baseline 没能登记：{base}"
    capsys.readouterr()

    code = G.main(_record_args(ws))
    out = capsys.readouterr()
    assert code == 0, (
        "`--record-audit` 非 0 —— 这条 CLI 通路又断了（`R6-R1d-1` 的形态："
        f"库函数有牙、入口没人跑）。stdout={out.out!r} stderr={out.err!r}"
    )
    assert "Traceback" not in out.err, out.err
    assert "NameError" not in out.err, out.err
    assert "AttributeError" not in out.err, out.err
    # 盘上真的多了一条（"退出码 0"本身不是证据：崩溃发生在写台账之后）
    audits = _entry_audits(ws)
    assert len(audits) == 1, audits
    assert audits[0]["auditor"] == "subagent-A" and audits[0]["dimension"] == "axes"
    # 写入侧的读数要出现在 stdout 里
    assert "[record-audit]" in out.out, out.out
    assert "不同维度" in out.out, out.out


def test_check_approvals_json_and_cli_agree_on_the_dimension_count(
    ws: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    """`R6-R1d-6`：CLI 打印的维度计数与 `--check-approvals --json` 的 `distinct_dimensions` 同口径。

    改前形态：CLI 打 `len(info['distinct_dimensions'])`（先取长度再格式化），
    JSON 里同名字段是列表 —— 两处口径不一致，读报告的人对不上账。
    """
    assert G.main(["--baseline", "--paths", REL, "--root", str(ws["root"]),
                   "--manifest", str(ws["manifest"]), "--ledger", str(ws["ledger"])]) == 0
    assert G.main(_record_args(ws)) == 0
    cli_out = capsys.readouterr().out
    assert "不同维度 1/3" in cli_out, cli_out

    code = G.main(["--check-approvals", "--paths", REL, "--json",
                   "--root", str(ws["root"]), "--manifest", str(ws["manifest"]),
                   "--ledger", str(ws["ledger"]), "--receipt-log", str(ws["receipt"])])
    seen = capsys.readouterr().out
    payload = json.loads(seen)
    one = payload["approvals"][0]
    assert code == 1, code          # 只有 1 名审计者 × 1 个维度 ⇒ 未批准（查过了、没批准）
    assert one["approval_status"] == "unapproved", one
    assert one["distinct_dimensions"] == ["axes"], one["distinct_dimensions"]
    assert one["distinct_auditors"] == 1, one
    # 同口径：CLI 打的分子就是 JSON 列表的长度
    assert f"不同维度 {len(one['distinct_dimensions'])}/" in cli_out, cli_out


# ============================================================ 负控：注入副本必须变红


def _mutate_gate(dest: pathlib.Path, old: str, new: str) -> str:
    """把当前字节复制到 `dest` 并做一处替换；返回副本 sha256。

    锚点找不到（或出现多次）⇒ 直接 `pytest.fail`：那说明"这一行已经不在了"，
    此时静默通过等于"我测的是别的东西"（本仓记过的形态：锚点漂了却静默通过）。
    """
    src = GATE.read_text(encoding="utf-8")
    if src.count(old) != 1:
        pytest.fail(f"注入锚点在当前字节里出现 {src.count(old)} 次（期望恰好 1 次）：{old!r}")
    dest.write_text(src.replace(old, new), encoding="utf-8", newline="\n")
    got = _sha256_file(dest)
    assert got != _sha256_file(GATE), "副本与当前字节相同 ⇒ 注入没生效"
    return got


def _run_gate(script: pathlib.Path, argv: list[str]) -> tuple[int, str, str]:
    """用子进程跑一份门脚本副本；返回 `(退出码, stdout, stderr)`。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, str(script), *argv],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=str(ROOT))
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def test_negative_control_nameerror_copy_is_red(
    ws: dict, tmp_path: pathlib.Path
) -> None:
    """`R6-R1d-1` 负控（证明注入生效）：把那一行改回改前形态 ⇒ 同一条 CLI 非 0 + NameError。

    改前形态就是 R1c 交付的那一版：`updated.counted_audits`（`updated` 只是
    `record_audit()` 内部的局部名）。注入点不是会被下一行覆盖的那一行 ——
    它是这一处判据唯一的赋值点（`dim_problem = ...`），并打印副本 sha256 作指纹。
    """
    script = tmp_path / "gate-nameerror.py"
    fingerprint = _mutate_gate(
        script,
        "        new_ledger.entry_for(info[\"path\"]).counted_audits, target_text",
        "        updated.counted_audits, target_text",
    )
    assert G.main(["--baseline", "--paths", REL, "--root", str(ws["root"]),
                   "--manifest", str(ws["manifest"]), "--ledger", str(ws["ledger"])]) == 0

    code, out, err = _run_gate(script, _record_args(ws))
    assert code != 0, (
        f"注入副本（sha256 {fingerprint[:16]}）没有失败 ⇒ 负控假绿：{out!r} {err!r}"
    )
    assert "NameError" in err and "updated" in err, err


def test_negative_control_target_text_key_copy_is_red(
    ws: dict, tmp_path: pathlib.Path
) -> None:
    """`R6-R1d-6` 负控（证明注入生效）：把 `_target_text` 加回公开返回值、并让 CLI 只依赖它
    ⇒ 副本自己读被审对象这件事被撤掉之后，同一条 CLI 会抛 `KeyError`。

    这一条守的是"`_run_record_audit` 自己读目标文件"这个修法：此前它读的是
    `record_audit` 的内部中间量，而那个中间量一旦不在（比如被拿掉），
    整条 CLI 通路就会以未捕获的异常结束 —— 正是 `R6-R1d-1` 的形态。
    """
    script = tmp_path / "gate-keyerror.py"
    fingerprint = _mutate_gate(
        script,
        "        new_ledger.entry_for(info[\"path\"]).counted_audits, target_text",
        "        new_ledger.entry_for(info[\"path\"]).counted_audits, info[\"_target_text\"]",
    )
    assert G.main(["--baseline", "--paths", REL, "--root", str(ws["root"]),
                   "--manifest", str(ws["manifest"]), "--ledger", str(ws["ledger"])]) == 0

    code, out, err = _run_gate(script, _record_args(ws))
    assert code != 0, (
        f"注入副本（sha256 {fingerprint[:16]}）没有失败 ⇒ 负控假绿：{out!r} {err!r}"
    )
    assert "KeyError" in err and "_target_text" in err, err


# ============================================================ 本批 low finding 的 CLI 侧读数


def test_dimension_independence_runs_on_the_cli_and_reports_it(
    ws: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    """`R6-R1d-1` / `R6-R1d-4`：CLI 里那处维度独立性判据真的在跑，且会报出来。

    1 条审计只有 1 个维度 ⇒ 判据 0 的前置（维度数 > 1）不成立 ⇒ 不报红，
    但 CLI 必须仍然打印"还差什么"，而不是崩掉（改前形态就是崩）。
    """
    assert G.main(["--baseline", "--paths", REL, "--root", str(ws["root"]),
                   "--manifest", str(ws["manifest"]), "--ledger", str(ws["ledger"])]) == 0
    assert G.main(_record_args(ws)) == 0
    out = capsys.readouterr().out
    assert "⇒ 还差：" in out, out
    assert "不同审计者 1 名" in out, out
    assert "不同维度 2 个" in out, out


def test_normalize_subject_folds_empty_glyph_fillers(
    ws: dict, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`R6-R1d-7`：有类别、没字形的填充码位（`U+3164` 一类）必须被折掉。

    改前形态：同一个人把名字写成 `'reaudit5-H' + U+3164` 就算两个人
    （`_mentions_word` 的词边界对 `U+3164` 一律放行），而肉眼是同一个名字。
    正控：中文真姓名照旧合格（不许改成"只允许 ASCII"）。
    负控：把折叠那一行注入成 `pass` ⇒ 归一化重新算成两个串（同一个可见名字两个人）。
    """
    hidden = ("\u3164", "\u115f", "\u1160", "\uffa0", "\u2800")
    assert G.normalize_subject("reaudit5-H") == "reaudit5-h"
    for ch in hidden:
        assert G.normalize_subject("reaudit5-H" + ch) == "reaudit5-h", hex(ord(ch))
    # 正控：真姓名仍然合格、仍然两两不同
    assert G._reviewer_identity_problem("reviewer-甲") == ""
    assert G._reviewer_identity_problem("reviewer-甲乙") == ""
    assert G.normalize_subject("reviewer-甲") != G.normalize_subject("reviewer-甲乙")
    assert G._reviewer_identity_problem("\u3164") != ""      # 只剩填充码位 ⇒ 不是一个"人"的标识

    # 负控（注入生效）：把折叠那一行撤成 `pass` ⇒ 同一个可见名字重新算成两个串
    script = tmp_path / "gate-no-filler-fold.py"
    fingerprint = _mutate_gate(
        script,
        '        if ch in _INVISIBLE_FILLERS:\n            continue\n',
        '        if ch in _INVISIBLE_FILLERS:\n            pass\n',
    )
    probe = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('g', r'{script}')\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "sys.modules['g'] = m\n"
        "spec.loader.exec_module(m)\n"
        "a = m.normalize_subject('reaudit5-H')\n"
        "b = m.normalize_subject('reaudit5-H' + chr(0x3164))\n"
        # 只打 ASCII 词：这个探针的输出要能被断言逐字比对，不该依赖终端怎么渲染填充码位
        "print('FILLER_FOLDED' if a == b else 'FILLER_NOT_FOLDED', len(a), len(b))\n"
    )
    code, out, err = _run_gate(script, ["--help"])
    assert code == 0, (fingerprint, err[:400])
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "FILLER_NOT_FOLDED 10 11", (
        f"注入副本（sha256 {fingerprint[:16]}）没有复现改前形态：{proc.stdout!r} {proc.stderr!r}"
    )

    # 真 CLI 上再来一次端到端正控：带填充码位的审计者名写得进去，且归一化后是一个名字
    assert G.main(["--baseline", "--paths", REL, "--root", str(ws["root"]),
                   "--manifest", str(ws["manifest"]), "--ledger", str(ws["ledger"])]) == 0
    args = _record_args(ws)
    args[args.index("--auditor") + 1] = "subagent-A\u3164"
    assert G.main(args) == 0
    capsys.readouterr()
    assert _entry_audits(ws)[0]["auditor"] == "subagent-A\u3164"
