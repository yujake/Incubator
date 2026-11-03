# -*- coding: utf-8 -*-
"""第 17.1 节检测面的判据：五处登记的失败信息必须带可粘贴的账骨架。

## 为什么这五条判据值得存在

「红必须带着账骨架来」如果没有判据，它就只是一句口径：有人把失败信息改回
「只报差在哪、让人自己抄」时，不会有任何东西响。所以这里逐处钉三件事：

1. 正控（a）：造一个「缺一条登记」，把真正的判据函数跑一遍（输入注入在内存 /
   `tmp_path` 里，不往仓库写任何东西），从 `AssertionError` 的文本里取出骨架，
   并证明它真的能粘贴 —— 能按目标文件的数据结构解析出来（字典条目 / 元组条目 /
   JSON 对象 / markdown 行 / 那一整句），不是一段像模像样的散文；
2. 反真空（b）：把那条骨架从失败信息里删掉（其余字节不动），同一条钉法必须变红
   —— 否则「包含」可能只是在验一句恒真的话；
3. 入口两态（c）：`scripts/render_registration_skeletons.py` 在无缺口时输出
   「无缺口」（退出码 0），有缺口时输出骨架（退出码 1）。

## 这条判据不做什么

它不验「骨架生成之后文件被改了」—— 恰恰相反：第 17.3 / 17.4 节要求它绝不写盘。
第 4 条（d）跑一次生成器，比对五个目标文件的 sha256 与 mtime：一个字节变了就红。

## 为什么是「跑真的判据函数」而不是「只调一遍渲染函数」

只调渲染函数能证明「这个函数会拼字符串」，证明不了「失败信息里嵌的是它」。
每条正控都把目标判据函数真跑一遍，从异常的文本里取骨架 —— 接线错了就红。
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import _skeleton as SK

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "render_registration_skeletons.py"

#: 第 4 条（d）要比对的目标文件：五处登记各自的落点。
TARGET_FILES: tuple[Path, ...] = (
    REPO / "tests" / "test_release_all.py",
    REPO / "tests" / "test_refusals.py",
    REPO / "tests" / "fixtures" / "tool_declaration_baseline.json",
    REPO / "docs" / "INDEX.md",
    REPO / "docs" / "READING-MAP.md",
)

#: `docs/INDEX.md` 入册行：`| [名字](名字) | 一行说明 |`。
_INDEX_REGISTERED_ROW = re.compile(r"^\| \[`([^`]+\.md)`\]\(([^)]+)\) \| (.+) \|$", re.M)
#: `docs/INDEX.md` 第 6 节不入册行：`| `名字` | 为什么不入册 |`。
_INDEX_UNREGISTERED_ROW = re.compile(r"^\| `([^`]+\.md)` \| (.+) \|$", re.M)

#: 读图开头那一整句（三格读数 + `agent_loop.py` 行数）。
_HEADLINE = re.compile(
    r"> \*\*(?P<files>\d+) 个 `\.py`、(?P<lines>[\d,]+) 行\*\*，"
    r"\*\*(?P<big>\d+) 个文件超过 800 行\*\*（\*\*全仓最大的是 `agent_loop\.py`，"
    r"(?P<loop>[\d,]+) 行\*\*")

#: 基线 JSON 代码块（`contract_amendments` 的账骨架）。
_JSON_FENCE = re.compile(r"```json\n(.*?)\n```", re.S)


# ---------------------------------------------------------------- 粘贴性的钉法
#
# 每一条都是「把这段文本当成目标文件的字节来解析」：解析不过 = 粘不进去 = 骨架没用。
# 它们既是 a 的判据，也是 b 的判据（删掉骨架之后，同一个函数必须抛 AssertionError）。


def plain_failure_message(message: str) -> str:
    """还原 pytest 给断言消息加的续行缩进（`_format_assertmsg`：换行后统一加两格）。

    为什么需要它：pytest 会把 `assert x, msg` 里 msg 的每一个续行前面补两个空格，
    而这一组判据要读的正是 msg 的字节（markdown 行以 `|` 开头、JSON 代码块以
    ``` 开头）。先还原成判据自己写出来的那一份，再按目标文件的格式解析。
    """
    lines = message.splitlines()
    if not lines:
        return message
    restored = [lines[0]]
    restored.extend(line[2:] if line.startswith("  ") else line for line in lines[1:])
    return "\n".join(restored)


def top_level_entries(message: str) -> dict[str, str]:
    """从失败信息里解析出 `_AGENTFLOW_TOP_LEVEL_MODULES` 的条目（键 -> 理由）。"""
    out: dict[str, str] = {}
    for line in message.splitlines():
        stripped = line.strip()
        if not (stripped.startswith('"') and stripped.endswith(",")):
            continue
        try:
            row = ast.literal_eval("{" + stripped + "}")
        except (SyntaxError, ValueError):
            continue
        if isinstance(row, dict):
            out.update({str(k): str(v) for k, v in row.items()})
    return out


def require_top_level_entry(message: str, name: str) -> None:
    """a①的钉法：失败信息里必须有 `name` 的整行，且理由占位非空。"""
    entries = top_level_entries(message)
    assert name in entries, f"失败信息里没有 `{name}` 的可粘贴登记行：{sorted(entries)}"
    assert entries[name].strip(), f"`{name}` 那一行的理由占位是空的 ⇒ 粘回去也没写理由"


def refusal_entries(message: str) -> dict[tuple[str, str], str]:
    """从失败信息里解析出 `_FAILURES_NOT_REFUSALS` 的条目（(文件, kind) -> 理由）。"""
    out: dict[tuple[str, str], str] = {}
    for line in message.splitlines():
        stripped = line.strip()
        if not (stripped.startswith('("') and stripped.endswith(",")):
            continue
        try:
            row = ast.literal_eval("{" + stripped + "}")
        except (SyntaxError, ValueError):
            continue
        if isinstance(row, dict):
            out.update({(str(k[0]), str(k[1])): str(v) for k, v in row.items()})
    return out


def require_refusal_entry(message: str, rel: str, kind: str) -> None:
    """a②的钉法：失败信息里必须有 `(rel, kind)` 的元组行，且理由占位非空。"""
    entries = refusal_entries(message)
    assert (rel, kind) in entries, (
        f"失败信息里没有 `({rel!r}, {kind!r})` 的可粘贴元组行：{sorted(entries)}")
    assert entries[(rel, kind)].strip(), "那一行的理由占位是空的 ⇒ 粘回去也没写理由"


def json_fragments(message: str) -> list[dict]:
    """从失败信息里解析出账骨架的 JSON 对象（解析不过的直接跳过）。

    代码块里是「数组元素」形态（每个对象带末尾逗号、缩进 4，照基线字节），
    所以解析时补上一对方括号：可粘贴的形态与可校验的形态在这里是同一种字节。
    """
    out: list[dict] = []
    for match in _JSON_FENCE.finditer(message):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            payloads = json.loads("[" + raw.rstrip().rstrip(",") + "]")
        except ValueError:
            continue
        if isinstance(payloads, list):
            out.extend(one for one in payloads if isinstance(one, dict))
    return out


def require_contract_fragment(message: str, tool: str, key: str,
                              expected_to: object) -> None:
    """a③的钉法：失败信息里必须有 `tool` / `key` 那一条 amendment，edits 逐项能对上。"""
    hits = [one for one in json_fragments(message)
            if one.get("tools") == [tool] and one.get("key") == key]
    assert hits, f"失败信息里没有 `{tool}` 的 `{key}` amendment：{json_fragments(message)}"
    payload = hits[0]
    assert str(payload.get("reason") or "").strip(), "amendment 的 reason 还是空串"
    assert str(payload.get("date") or "").strip(), "amendment 没有 date"
    edits = payload.get("edits") or []
    assert any(one.get("to") == expected_to for one in edits), (
        f"amendment 的 edits 没有落到 {expected_to!r}：{edits}")


def require_index_rows(message: str, name: str) -> None:
    """a④的钉法：失败信息里必须同时有「入册」与「不入册」两种落位的整行。"""
    registered = [m.group(1) for m in _INDEX_REGISTERED_ROW.finditer(message)]
    unregistered = [m.group(1) for m in _INDEX_UNREGISTERED_ROW.finditer(message)]
    assert registered.count(name) >= 1, (
        f"失败信息里没有 `{name}` 的入册行（`| [名字](名字) | 说明 |`）：{registered}")
    assert unregistered.count(name) >= 1, (
        f"失败信息里没有 `{name}` 的不入册行（`| 名字 | 为什么不入册 |`）：{unregistered}")
    for match in _INDEX_REGISTERED_ROW.finditer(message):
        if match.group(1) == name:
            assert match.group(2) == name, "入册行的链接目标与文件名不一致 ⇒ 粘不进 INDEX"
            assert match.group(3).strip(), "入册行的说明格是空的"
    for match in _INDEX_UNREGISTERED_ROW.finditer(message):
        if match.group(1) == name:
            assert match.group(2).strip(), "不入册行的理由格是空的"


def require_headline(message: str, files: int, total: int, big: int,
                     loop_lines: int) -> None:
    """a⑤的钉法：失败信息里必须有整句原文，且四格读数就是现算值。"""
    found = _HEADLINE.search(message)
    assert found, "失败信息里没有开头那一整句（三格 + agent_loop.py 行数）可粘贴原文"
    got = (int(found.group("files")), int(found.group("lines").replace(",", "")),
           int(found.group("big")), int(found.group("loop").replace(",", "")))
    assert got == (files, total, big, loop_lines), (
        f"整句里的读数 {got} 与现算 {(files, total, big, loop_lines)} 不一致")


# ---------------------------------------------------------------- 注入：造「缺一条登记」


def _inject_new_top_level_module(monkeypatch) -> str:
    """① 盘上多一个 `_probe_x.py`（`R6-AN-1` 那次注入的形态，只在内存里）。"""
    TRA = importlib.import_module("test_release_all")
    on_disk = [*TRA._agentflow_top_level_modules_on_disk(), "_probe_x.py"]
    monkeypatch.setattr(TRA, "_agentflow_top_level_modules_on_disk", lambda: on_disk)
    with pytest.raises(AssertionError) as caught:
        TRA.test_agentflow_top_level_modules_match_the_registry()
    return plain_failure_message(str(caught.value))


def _inject_unregistered_hand_rolled_failure(monkeypatch, tmp_path) -> str:
    """② 一个角色动作模块里手写 `ok=False` 而没登记（盘在 tmp_path，不碰仓库）。"""
    TRF = importlib.import_module("test_refusals")
    src = tmp_path / "src"
    for index in range(8):
        directory = src / f"agent_{chr(ord('a') + index)}"
        directory.mkdir(parents=True)
        body = ('def f():\n    return {"ok": False, "kind": "probe_failed"}\n'
                if index == 0 else 'def g():\n    return {"ok": True}\n')
        (directory / "mod.py").write_text(body, encoding="utf-8")
    monkeypatch.setattr(TRF, "SRC", src)
    with pytest.raises(AssertionError) as caught:
        TRF.test_every_hand_rolled_failure_is_registered_and_the_table_is_not_stale()
    return plain_failure_message(str(caught.value))


def _inject_contract_change() -> str:
    """③ 现盘上有一格 `returns` 与基线不同、且没有逐项记账。"""
    TTC = importlib.import_module("test_tool_descriptions_are_compressed")
    frozen = TTC.baseline()
    current = TTC.declarations()
    current["table.list"] = dict(current["table.list"],
                                 returns="PROBE-RETURNS-CONTRACT-CHANGE")
    with pytest.raises(AssertionError) as caught:
        TTC.test_declaration_contracts_are_unchanged(current, frozen)
    return plain_failure_message(str(caught.value))


def _inject_new_doc(monkeypatch, tmp_path) -> str:
    """④ 盘上多出没登记的文档（`docs/` 换成 tmp_path，INDEX 仍读真的）。"""
    TDI = importlib.import_module("test_docs_index_covers_every_doc")
    docs = tmp_path / "docs"
    docs.mkdir()
    for index in range(TDI.MIN_DOCS + 1):
        (docs / f"PROBE-DOC-{index:02d}.md").write_text("# 探针\n", encoding="utf-8")
    monkeypatch.setattr(TDI, "DOCS", docs)
    with pytest.raises(AssertionError) as caught:
        TDI.test_every_doc_is_registered_or_explicitly_not()
    return plain_failure_message(str(caught.value))


def _inject_stale_headline(monkeypatch, tmp_path) -> tuple[str, tuple[int, int, int, int]]:
    """⑤ 读图开头那一句的四格全过期（文档换到 tmp_path，现算仍读真的 `src/`）。"""
    TRC = importlib.import_module("test_reading_map_counts")
    live = TRC._live()
    files, total, big, loop_lines = live
    doc = tmp_path / "READING-MAP.md"
    doc.write_text(
        "# 读图的入口\n\n"
        f"> **{files - 3} 个 `.py`、{total - 11:,} 行**，**{big + 2} 个文件超过 800 行**"
        f"（**全仓最大的是 `agent_loop.py`，{loop_lines + 17:,} 行**\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(TRC, "READING_MAP", doc)
    with pytest.raises(AssertionError) as caught:
        TRC.test_the_headline_counts_equal_the_disk()
    return plain_failure_message(str(caught.value)), live


# ---------------------------------------------------------------- a：正控（五处各一条）


def test_a1_a_new_top_level_module_failure_carries_its_registry_line(monkeypatch):
    message = _inject_new_top_level_module(monkeypatch)
    require_top_level_entry(message, "_probe_x.py")


def test_a2_an_unregistered_hand_rolled_failure_carries_its_refusal_line(monkeypatch,
                                                                       tmp_path):
    message = _inject_unregistered_hand_rolled_failure(monkeypatch, tmp_path)
    require_refusal_entry(message, "agent_a/mod.py", "probe_failed")


def test_a3_a_contract_change_failure_carries_the_whole_edits_fragment():
    message = _inject_contract_change()
    require_contract_fragment(message, "table.list", "returns",
                              "PROBE-RETURNS-CONTRACT-CHANGE")


def test_a4_a_missing_doc_failure_carries_both_index_landing_rows(monkeypatch, tmp_path):
    message = _inject_new_doc(monkeypatch, tmp_path)
    require_index_rows(message, "PROBE-DOC-00.md")


def test_a5_a_stale_headline_failure_carries_the_whole_sentence(monkeypatch, tmp_path):
    message, live = _inject_stale_headline(monkeypatch, tmp_path)
    require_headline(message, *live)


# ---------------------------------------------------------------- b：反真空（删掉骨架就红）


def test_b1_removing_the_registry_line_turns_a1_red(monkeypatch):
    message = _inject_new_top_level_module(monkeypatch)
    line = SK.top_level_module_line("_probe_x.py")
    assert line in message, "夹具前提：a1 取到的失败信息里真的有那一行"
    stripped = message.replace(line, "")
    assert stripped != message
    with pytest.raises(AssertionError):
        require_top_level_entry(stripped, "_probe_x.py")


def test_b2_removing_the_refusal_line_turns_a2_red(monkeypatch, tmp_path):
    message = _inject_unregistered_hand_rolled_failure(monkeypatch, tmp_path)
    line = SK.refusal_line("agent_a/mod.py", "probe_failed")
    assert line in message, "夹具前提：a2 取到的失败信息里真的有那一行"
    stripped = message.replace(line, "")
    assert stripped != message
    with pytest.raises(AssertionError):
        require_refusal_entry(stripped, "agent_a/mod.py", "probe_failed")


def test_b3_removing_the_edits_fragment_turns_a3_red():
    message = _inject_contract_change()
    blocks = _JSON_FENCE.findall(message)
    assert blocks, "夹具前提：a3 取到的失败信息里真的有那段 JSON"
    stripped = message
    for raw in blocks:
        stripped = stripped.replace("```json\n" + raw + "\n```", "")
    assert stripped != message
    with pytest.raises(AssertionError):
        require_contract_fragment(stripped, "table.list", "returns",
                                  "PROBE-RETURNS-CONTRACT-CHANGE")


def test_b4_removing_the_index_rows_turns_a4_red(monkeypatch, tmp_path):
    message = _inject_new_doc(monkeypatch, tmp_path)
    line = SK.docs_index_registered_row("PROBE-DOC-00.md")
    assert line in message, "夹具前提：a4 取到的失败信息里真的有那一行"
    stripped = message.replace(line, "")
    assert stripped != message
    with pytest.raises(AssertionError):
        require_index_rows(stripped, "PROBE-DOC-00.md")


def test_b5_removing_the_headline_turns_a5_red(monkeypatch, tmp_path):
    message, live = _inject_stale_headline(monkeypatch, tmp_path)
    sentence = SK.reading_map_headline(*live)
    assert sentence in message, "夹具前提：a5 取到的失败信息里真的有那一整句"
    stripped = message.replace(sentence, "")
    assert stripped != message
    with pytest.raises(AssertionError):
        require_headline(stripped, *live)


# ---------------------------------------------------------------- c：开发入口的两态


def _entry_module():
    """按路径加载 `scripts/render_registration_skeletons.py`（与发布门一条路）。"""
    return importlib.import_module("scripts.render_registration_skeletons")


def test_c1_the_entry_says_no_gap_when_there_is_none(monkeypatch, capsys):
    entry = _entry_module()
    monkeypatch.setattr(entry, "collect_gaps", lambda: [])
    assert entry.main([]) == 0, "无缺口必须以 0 退出（三态里的第一档）"
    out = capsys.readouterr().out
    assert "无缺口" in out, out
    assert "== " not in out, "无缺口时不许打印任何一处骨架"


def test_c2_the_entry_prints_the_skeleton_when_there_is_a_gap(monkeypatch, capsys):
    entry = _entry_module()
    body = SK.top_level_modules_message(["未登记：['_probe_x.py']"], ["_probe_x.py"], {})
    monkeypatch.setattr(entry, "collect_gaps", lambda: [(entry.TITLES[0], body)])
    assert entry.main([]) == 1, "有缺口必须以 1 退出（0 是「无缺口」，2 是「没查成」）"
    out = capsys.readouterr().out
    assert "无缺口" not in out
    assert SK.top_level_module_line("_probe_x.py") in out, out
    assert entry.TITLES[0] in out, "打印出来的骨架必须带得上它属于哪一处"


# ---------------------------------------------------------------- d：生成器绝不写盘


def _fingerprint(path: Path) -> tuple[str, int]:
    """(内容 sha256, mtime 纳秒) —— 一个字节或一次落盘都会让它变。"""
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mtime_ns


def test_d_one_generator_run_changes_not_one_byte_on_disk():
    """跑一次骨架生成 ⇒ 五个目标文件的 hash 与 mtime 一个字节都不许变。

    第 17.3 / 17.4 节的硬约束：自动写盘等于让实现成为规格，自动重冻等于让
    「改参数名 / 删返回键」从一条红变成一次静默放行。判据就是这句「没变」。
    """
    before = {path: _fingerprint(path) for path in TARGET_FILES}
    done = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900,
    )
    blob = done.stdout + done.stderr
    assert done.returncode in (0, 1), f"生成器必须落在两态之一（0 无缺口 / 1 有缺口）：\n{blob[-800:]}"
    assert ("无缺口" in done.stdout) != ("== " in done.stdout), (
        "输出必须恰好落在「无缺口」与「有缺口」两态之一（第三种是 2 + stderr）")
    after = {path: _fingerprint(path) for path in TARGET_FILES}
    changed = sorted(str(path) for path in TARGET_FILES if before[path] != after[path])
    assert not changed, (
        "生成器改了盘上的文件（它只许打印）：" + "、".join(changed))
