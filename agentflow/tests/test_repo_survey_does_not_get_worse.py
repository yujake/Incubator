"""软判据：仓库的体量读数不许比基线更差（`tools/repo_survey.py` 的守门人）。

## 为什么是"软"判据

体量不是缺陷。一个 5000 行的文件可能是该那么大，一个 4000 行的类也可能是该那么大。
所以这条判据不判定"多少行算坏"，它只判定一件事：不许比基线更差。
基线是常量（下面 `BASELINE`），实测是脚本现跑一遍的数 —— 于是"这棵树在长大"
这件事第一次有了机器读数，而不是靠谁哪天翻一遍文件列表说一句"好像又胖了"。

## 为什么基线写死、且必须带日期

写死是刻意的：如果基线跟着实测一起动，"≤ 基线"就永远成立，这条判据会退化成
一句同义反复（本项目最忌的形态：看起来在检查，实际什么都没检查）。
所以基线写死，破了就得有人来改它 —— 而改它这一步必须有人回答"这次长大是不是有意的"。
`BASELINE_OBSERVED` 记的是这组常量观测到的时刻，没有它，下一个人无法判断
"这个数是当次值还是三年前的值"。

## 反真空：没扫到不等于没问题

扫描面被打桩成空目录时，`tools/repo_survey.py` 的 `survey()` 会返回
`scanned_ok=False` 而不是一份"0 个大文件"的漂亮读数。这里的那条负控就是为了证明
它真的会红：`test_empty_scan_surface_is_not_green` 把扫描面换成空目录，
断言判据会报"没扫到 = 没查成"。没有这条负控的话，"0 个大文件 ≤ 60"会让一棵
空树或一个写错的根路径无条件通过 —— 而"通过"与"没查到"混在一起，正是这个仓库
反复踩过的那个坑（三态纪律）。

## 量法

判据不另写一套算法，它 import `tools/repo_survey.py` 并调它的 `survey()`
（判据与被判的对象必须是同一份实现，"量法不同"是这个项目最贵的那类缺陷）。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: 被判的脚本（只读巡检；不进发布门）。
SURVEY_PATH = REPO / "tools" / "repo_survey.py"

#: 基线（常量，不随实测漂）：键名 = `_metrics()` 的键。
#:
#: 观测时刻：2026-10-23（本轮清洁审计的改前读数，`python tools/repo_survey.py`）。
#: 三个口径分别是：`>800` 行的 src 文件数 / 源码跨度 `>200` 行的函数个数
#: （不含 class —— 函数 63 与 def+class 合计 105 是两个都成立的事实，
#: 基线钉的是函数那一格，因为"函数在长"才是那段代码在失去结构的信号）/
#: 跨文件逐字重复的 docstring 段数（>= 80 字符）。
BASELINE: dict[str, int] = {
    "src_files_gt800_lines": 60,
    "src_functions_gt200_lines": 63,
    "dup_docstring_segments": 4,
}

#: 基线观测时刻（写在这里，是为了让"这组常量有多旧"这件事一眼可见）。
BASELINE_OBSERVED = "2026-10-23"


def _load_survey():
    """按文件路径加载被判的脚本（不依赖 `tools/` 是不是一个包）。"""
    spec = importlib.util.spec_from_file_location("agentflow_tools_repo_survey", SURVEY_PATH)
    assert spec and spec.loader, f"加载不了 {SURVEY_PATH} —— 判据失去对象（不是通过）"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _metrics(data: dict) -> dict[str, int]:
    """把 `survey()` 的读数抽成与 `BASELINE` 同名的三格。"""
    return {
        "src_files_gt800_lines": data["big_files"]["gt800"],
        "src_functions_gt200_lines": data["long_defs"]["function_gt200"],
        "dup_docstring_segments": data["dup_docstring_segments"],
    }


def baseline_problems(data: dict, baseline: dict[str, int] | None = None) -> list[str]:
    """读数 vs 基线 ⇒ 问题清单（空 = 成立）。返回清单而不是布尔，红时要能说清差在哪。

    第一条判据是"扫到了没有"：扫描面为空（或根写错）时，`survey()` 给的是
    `scanned_ok=False`，这里必须报"没查成"而不是让"0 ≤ 60"通过。
    """
    base = dict(BASELINE if baseline is None else baseline)
    if not data.get("scanned_ok"):
        return [
            "没扫到 = 没查成："
            + str(data.get("vacuum_reason") or "扫描面返回 scanned_ok=False（没有原因，这本身是缺陷）")
            + " —— 这一份读数不可用，它不构成'体量没变坏'的证据"
        ]
    got = _metrics(data)
    problems: list[str] = []
    for key, limit in base.items():
        now = got.get(key)
        if now is None:
            problems.append(f"读数里缺 `{key}` —— 判据失去对象（不是通过）")
        elif now > limit:
            problems.append(f"`{key}` 已越过基线：现在 {now}，基线 {limit}"
                            f"（基线观测于 {BASELINE_OBSERVED}；要抬基线请先说明为什么这次长大是有意的）")
    return problems


def test_survey_reports_numbers_and_stays_within_baseline():
    """正向：真的跑一遍巡检，三格读数都要读得出来、且都不许越过基线。

    "读得出来"不是形式主义：`scanned_ok=True` 之后三格如果全是 0，那更像扫描器没接上
    而不是这棵树空了 —— 所以这里额外断言三格都大于 0（反真空）。今天它们分别是
    60 / 63 / 4。
    """
    mod = _load_survey()
    data = mod.survey(REPO)
    assert data.get("scanned_ok"), data.get("vacuum_reason")
    assert data["scanned"]["src_files"] > 0, "src 下 0 个 .py —— 这不是'体量很干净'，是没扫到"
    got = _metrics(data)
    zero = [k for k, v in got.items() if v <= 0]
    assert not zero, f"这几格读成了 0，扫描器可能没接上（不是'没问题'）：{zero}；读数={got}"
    problems = baseline_problems(data)
    assert not problems, problems


def test_empty_scan_surface_is_not_green(tmp_path):
    """负控（反真空）：把扫描面打桩成空目录 ⇒ 判据必须红，且理由要写"没查成"。

    打桩的是扫描面（`src_rel` 指向一个空目录），不是把 `survey()` 换掉 ——
    换掉实现证明不了"判据会在真实现上红"，而这条负控要证的正是那个方向。
    """
    mod = _load_survey()
    empty = tmp_path / "not_a_source_tree"
    empty.mkdir()
    data = mod.survey(tmp_path, src_rel=empty.name, tests_rel="tests")
    assert data.get("scanned_ok") is False, "空扫描面被读成了'扫到了'（这一条必须红）"
    problems = baseline_problems(data)
    assert problems, "空扫描面下判据给了'没问题' —— 反真空失效"
    assert "没查成" in problems[0], f"红是红了，但没写清'没扫到 = 没查成'：{problems}"
    assert "0 ≤ 60" not in problems[0], "不许把空扫描面读成'0 个大文件、比基线还好'"


def test_the_script_exits_2_when_it_cannot_measure(tmp_path):
    """负控（三态）：脚本自己的退出码也要分得开 —— 0 = 量到了，2 = 没量成。"""
    mod = _load_survey()
    empty = tmp_path / "no_source_here"
    empty.mkdir()
    code = mod.main(["--root", str(tmp_path), "--src", empty.name, "--json"])
    assert code == 2, "扫描面为空时脚本必须以 2 退出（0 会把它读成'查过了、没问题'）"


def test_baseline_criterion_has_teeth():
    """负控：把某格读数抬到基线之上 ⇒ `baseline_problems` 必须报出来。

    这条防的是"比较写反了"（例如把 `>` 写成 `>=` 或把两边对调）：
    那时代码照样跑、照样绿，而它已经从判据退化成了装饰。
    """
    mod = _load_survey()
    data = mod.survey(REPO)
    assert data.get("scanned_ok"), data.get("vacuum_reason")

    def _with(src_files_gt800: int, functions_gt200: int, dups: int) -> dict:
        """把三格读数换成给定值（其余读数原样带着），用于测比较本身。"""
        return {
            **data,
            "big_files": {**data["big_files"], "gt800": src_files_gt800},
            "long_defs": {**data["long_defs"], "function_gt200": functions_gt200},
            "dup_docstring_segments": dups,
        }

    over = _with(BASELINE["src_files_gt800_lines"] + 1,
                 BASELINE["src_functions_gt200_lines"],
                 BASELINE["dup_docstring_segments"])
    assert baseline_problems(over), "越过基线却没报 —— 这条判据没有牙"
    # 另一侧：三格恰好等于基线时必须成立（基线是"不许更差"，不是"不许一样"）。
    equal = _with(BASELINE["src_files_gt800_lines"],
                  BASELINE["src_functions_gt200_lines"],
                  BASELINE["dup_docstring_segments"])
    assert not baseline_problems(equal), "读数恰好等于基线就被判红 —— 基线的语义写错了"


def test_json_flag_prints_parseable_readings():
    """正向（可复跑）：`--json` 那一档真的能被打成 JSON 并读回同样的三格。

    为什么值得一条：`--json` 是这条巡检被别处引用的唯一形态（人读版会随措辞变），
    它坏掉时没有任何别的东西会红。
    """
    p = subprocess.run(
        [sys.executable, str(SURVEY_PATH), "--root", str(REPO), "--json"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data.get("scanned_ok"), data.get("vacuum_reason")
    assert not baseline_problems(data), baseline_problems(data)
