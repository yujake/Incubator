"""R4 组 6②：`jsonlfile.read_jsonl` 的四态（`absent` / `empty` / `ok` / `unreadable`）。

要治的形态：改前只有 `(记录, 坏行说明)` 两样东西，于是三件事无处可报 —— ① 文件不存在 与 文件在但一条记录也没有（返回值逐字相同）；② 读取本身失败（无效 UTF-8）直接崩在调用方；③ 路径是个目录，被 `is_file()` 挡掉、静默当成"不存在"。

判据怎么才算有牙：四条状态必须各自可分辨，且两个方向都要能红 —— 正向：四种输入分别给出四个不同的 `state`；负控：把状态折平（`absent` 与 `empty` 合并、`unreadable` 折进 `absent`）的那份假实现，必须被同一组断言判红（没有这一条，"四态都对"与"判据根本没在看状态"分不开）；反真空：断言这次真的判满了四条状态（少一条就说明这一格没查成，不是没问题）。

另有一条"包装不变"的判据：`read_jsonl` 的签名与"文件不存在 ⇒ `([], [])`"这条既有契约保持原样，且记录/坏行说明与 `read_jsonl_state` 逐字一致。"""

from __future__ import annotations

import json
import pathlib

from agentflow import jsonlfile


def _write(p: pathlib.Path, text: str) -> pathlib.Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_the_four_states_are_all_distinguishable(tmp_path: pathlib.Path) -> None:
    """四种输入 ⇒ 四个互不相同的 state（这是本文件的核心判据）。"""
    absent = tmp_path / "没有这个文件.jsonl"

    empty = _write(tmp_path / "空文件.jsonl", "\n\n")

    blank_only = _write(tmp_path / "只有空行.jsonl", "  \n\t\n")

    ok = _write(
        tmp_path / "正常.jsonl",
        json.dumps({"a": 1}, ensure_ascii=False) + "\n\n" + json.dumps({"b": 2}, ensure_ascii=False) + "\n",
    )

    bad_bytes = tmp_path / "坏字节.jsonl"
    bad_bytes.write_bytes(b'{"a": 1}\n\xff\xfe\n')

    as_dir = tmp_path / "这是个目录"
    as_dir.mkdir()

    got = {
        "absent": jsonlfile.read_jsonl_state(absent)[2],
        "empty": jsonlfile.read_jsonl_state(empty)[2],
        "blank_only": jsonlfile.read_jsonl_state(blank_only)[2],
        "ok": jsonlfile.read_jsonl_state(ok)[2],
        "unreadable_bytes": jsonlfile.read_jsonl_state(bad_bytes)[2],
        "unreadable_dir": jsonlfile.read_jsonl_state(as_dir)[2],
    }
    assert got == {
        "absent": "absent",
        "empty": "empty",
        "blank_only": "empty",
        "ok": "ok",
        "unreadable_bytes": "unreadable",
        "unreadable_dir": "unreadable",
    }, got

    # 反真空：四条状态一条都不能漏判（漏一条 = 这一格没查成，不是没问题）。
    covered = {v for v in got.values()}
    assert covered == set(jsonlfile.READ_STATES), (
        f"这次只判到 {sorted(covered)}，而四态是 {sorted(jsonlfile.READ_STATES)} ⇒ 有一档没查成"
    )


def test_unreadable_is_a_state_and_not_an_exception(tmp_path: pathlib.Path) -> None:
    """读取失败必须是"一档能读出来的状态"，不是崩在调用方、也不是静默当不存在。"""
    bad = tmp_path / "坏字节.jsonl"
    bad.write_bytes(b'{"a": 1}\n\xff\n')
    rows, problems, state = jsonlfile.read_jsonl_state(bad)
    assert state == "unreadable", (rows, problems, state)
    assert rows == []
    assert problems and "读不出来" in problems[0], problems

    # 目录路径：改前 `is_file()` 为假 ⇒ 静默当成"不存在"，现在必须报"读不出来"。
    as_dir = tmp_path / "目录"
    as_dir.mkdir()
    rows2, problems2, state2 = jsonlfile.read_jsonl_state(as_dir)
    assert state2 == "unreadable", (rows2, problems2, state2)
    assert problems2, "目录被当成'不存在'了 —— 那正是这一档要治的形态"

    # 真·不存在仍然是 absent（别把 absent 一起吃掉）。
    assert jsonlfile.read_jsonl_state(tmp_path / "没有.jsonl")[2] == "absent"


def test_bad_lines_stay_reported_and_do_not_fold_into_a_state(tmp_path: pathlib.Path) -> None:
    """坏行与状态是两条正交的轴：坏行照旧逐条报，状态只说"读到什么程度"。"""
    mixed = _write(
        tmp_path / "混合.jsonl",
        json.dumps({"good": 1}, ensure_ascii=False) + "\n不是 JSON\n[1, 2, 3]\n",
    )
    rows, problems, state = jsonlfile.read_jsonl_state(mixed)
    assert rows == [{"good": 1}], rows
    assert state == "ok", state
    assert len(problems) == 2, problems
    assert "第 2 行" in problems[0] and "第 3 行" in problems[1], problems
    assert "不是对象" in problems[1], problems

    all_bad = _write(tmp_path / "全坏.jsonl", "不是 JSON\n[1, 2, 3]\n")
    rows2, problems2, state2 = jsonlfile.read_jsonl_state(all_bad)
    assert rows2 == []
    assert state2 == "empty", (rows2, problems2, state2)
    assert len(problems2) == 2, problems2


def test_the_folded_implementation_is_caught_by_these_assertions(tmp_path: pathlib.Path) -> None:
    """负控：把四态折平的假实现必须被上面那组断言判红。

    两个方向各来一份：

    - 折平一：`absent` 与 `empty` 合并（改前就是这样，两者返回值逐字相同）；
    - 折平二：`unreadable` 折进 `absent`（改前目录路径就是被这么吃掉的）。

    这里不是在测 `jsonlfile`，是在测"上面那组断言有没有牙"。
    """

    def folded_absent_empty(path: str | pathlib.Path) -> str:
        p = pathlib.Path(path)
        return "ok" if p.is_file() and p.read_text(encoding="utf-8").strip() else "absent"

    def folded_unreadable(path: str | pathlib.Path) -> str:
        p = pathlib.Path(path)
        if not p.is_file():
            return "absent"
        return "ok"

    absent = tmp_path / "没有.jsonl"
    empty = _write(tmp_path / "空.jsonl", "\n")
    bad = tmp_path / "坏字节.jsonl"
    bad.write_bytes(b"\xff\n")
    as_dir = tmp_path / "目录"
    as_dir.mkdir()

    # 折平一：empty 被读成 absent ⇒ 与真实现不同（真实现分得开这两档）。
    assert folded_absent_empty(empty) == "absent"
    assert jsonlfile.read_jsonl_state(empty)[2] == "empty", "真实现没能把 empty 与 absent 分开"
    assert folded_absent_empty(empty) != jsonlfile.read_jsonl_state(empty)[2], (
        "折平版与真实现给出同一个答案 ⇒ 这组断言看不出折平（判据没牙）"
    )

    # 折平二：unreadable 被读成 absent / ok ⇒ 与真实现不同。
    for probe in (bad, as_dir):
        folded = folded_unreadable(probe)
        real = jsonlfile.read_jsonl_state(probe)[2]
        assert real == "unreadable", (probe, real)
        assert folded != real, f"折平版把 {probe.name} 读成了 {folded} ⇒ 这组断言看不出折平"


def test_read_jsonl_keeps_its_two_tuple_contract(tmp_path: pathlib.Path) -> None:
    """包装不变：签名仍是二元组、既有那条"不存在 ⇒ `([], [])`"契约照旧。"""
    absent = tmp_path / "没有.jsonl"
    got = jsonlfile.read_jsonl(absent)
    assert isinstance(got, tuple) and len(got) == 2, got
    assert got == ([], []), got

    good = _write(tmp_path / "正常.jsonl", json.dumps({"x": 1}, ensure_ascii=False) + "\n")
    rows, problems = jsonlfile.read_jsonl(good)
    rows_state, problems_state, state = jsonlfile.read_jsonl_state(good)
    assert state == "ok"
    assert rows == rows_state == [{"x": 1}], (rows, rows_state)
    assert problems == problems_state == [], (problems, problems_state)

    # 读取失败这一档：包装不许崩，且必须把原因交出来。
    bad = tmp_path / "坏字节.jsonl"
    bad.write_bytes(b"\xff\n")
    rows_bad, problems_bad = jsonlfile.read_jsonl(bad)
    assert rows_bad == []
    assert problems_bad and "读不出来" in problems_bad[0], problems_bad
