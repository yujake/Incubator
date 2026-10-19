# -*- coding: utf-8 -*-
"""判据：工具说明压到「一两句」，而**声明契约一个字都没动**。

## 这一批改了什么

十个角色的 system prompt 里，工具声明是最大的一块静态文本（实测 G 的工具面
4 237 字符 / 提示词 37 093 字符；而 function-calling 的声明 JSON 是 26 117 字符
= 提示词的 70.4%）。声明里能压的只有一格：`summary`（工具说明）。参数 schema、
`returns`、`side_effect`、`roles` 全都不许动 —— 它们是契约。

所以本轮只做一件事：把每件工具的 `summary` 从「一段长文」压到「一两句」，
保留 **做什么 / 什么时候用 / 关键约束**，删掉 **为什么这么设计 / 历史沿革 /
长例子 / 与别的工具的比较论述 / 重复 `returns` 已逐字列过的返回键清单**。

## 三条判据，各自只能证明一件事

1. `test_declaration_contracts_are_unchanged`（① 契约不变）
   —— 与 `tests/fixtures/tool_declaration_baseline.json` 里**压缩前**那份声明逐键比：
   `params` / `returns` / `side_effect` / `external` / `roles` / `tags` / `handler_name`
   必须完全相同（工具集合也必须相同）。它**不能**证明说明压得好不好 —— 那是第 2 条。

2. `test_descriptions_shrank_by_at_least_a_quarter`（② 说明变短）
   —— 全部 `summary` 的字符总数必须 ≤ 基线的 75%。它**不能**证明删掉的是废话 ——
   那是第 3 条与人的 review。

3. `test_every_asserted_literal_survives`（③ needle 全在）
   —— needle = tests 里 `assert X in <声明面>`（summary / prompt / text / desc / spec）
   形态的字面量 X，且压缩前逐字出现在某件工具的 `summary` 里。每一条都必须还在。
   它**不能**证明没删掉别的重要字句 —— 那是「删什么」这件事本身要靠 review。

## 为什么负控是这三条

没有负控的门就是橡皮图章。三条负控各自打在**同一条判据函数**上（不是另写一套）：

- 改一个参数名 / 删一个 `returns` 键 ⇒ ① 必须红；
- 把某条说明加回长论述（回到压缩前那种长度）⇒ ② 必须红；
- 删掉一条 needle ⇒ ③ 必须红。

还有两条「反负控」：真没改的契约不许被误判成改动、压缩前的说明长度**必须**判红 ②
（否则 ② 的门只是「比 0 大」的橡皮章）。

## 口径上的两个刻意选择（写在代码里，别猜）

- **needle 的收集口径**是「`assert X in Y` 且 Y 是声明面」，不是「任何测试字符串」：
  `assert "sha256" in res.data` 那种断言与说明的措辞无关（它断言的是返回数据里有
  这个键），把它算成 needle 只会逼着人把说明写成一份返回键清单。
- **`table.schema` 的「N 张表」与 `conductor.closing` 的八格点名**不是字面量形态，
  它们由另外几条既有判据守着（`test_tool_summary_readings.py` /
  `test_conductor_tools.py::test_the_closing_tool_advertises_every_gate_cell`）。
  本文件不重复它们，只在下面 `SEMANTIC_RULES` 里把**与措辞直接相关**的那两条
  （`verify.check_formal` 的「真跑」、`search.download` 的失败类别集合）保留下来，
  因为它们要证明的正是「压说明不许把关键约束压掉」。
"""

from __future__ import annotations

import ast
import json
import re
import tempfile
from pathlib import Path

import pytest

from agentflow.store import Store
from agentflow.tools import ROLES, build_registry

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
BASELINE_PATH = TESTS / "fixtures" / "tool_declaration_baseline.json"

#: 声明里属于「契约」的那几格：只改 summary，这几格必须逐键相同。
CONTRACT_KEYS: tuple[str, ...] = (
    "params", "returns", "side_effect", "external", "roles", "tags", "handler_name",
)

#: 说明总量最多留下基线的这个比例（业主批准的打法：降 ≥25%）。
MAX_RATIO = 0.75

#: needle 的收集口径：断言右操作数（或整条 assert 源码）里出现这些词 ⇒ 它断言的是
#: 「声明面」的文字。刻意不写成「任何测试字符串」—— 理由见文件 docstring。
#: `line` / `面` 也在里面：`assert "sha256" in detail_line` 这种读的是**这一行的读数**，
#: 与 `text` / `desc` 是同一族（读数面）。
SURFACE_HINTS: tuple[str, ...] = (
    "summary", "prompt", "text", "desc", "tools_lines", "spec", "line", "面",
)

#: needle 最短长度（字符）。更短的（`ok` / `id` / 单字）没有判别力。
MIN_NEEDLE = 5


# ---------------------------------------------------------------- 装配面


def handler_identity(handler: object) -> str:
    """稳定的 handler 身份：不带内存地址（`repr` 会带 `0x…`，两次跑就不一样）。"""
    mod = getattr(handler, "__module__", None)
    qual = getattr(handler, "__qualname__", None) or getattr(handler, "__name__", None)
    if mod and qual:
        return f"{mod}.{qual}"
    cls = type(handler)
    return f"{cls.__module__}.{cls.__qualname__}"


def declarations() -> dict[str, dict]:
    """现算全部工具的声明：与 `tests/test_tool_summary_readings.py` 同一条装配口径。"""
    ws = Path(tempfile.mkdtemp(prefix="tool-desc-gate-")) / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    store = Store(ws)
    store.init()
    reg = build_registry(store=store, workspace_root=ws, roles=tuple(ROLES),
                         strict=True).registry
    return {
        spec.name: {
            "summary": spec.summary,
            "params": spec.params,
            "returns": spec.returns,
            "side_effect": spec.side_effect,
            "external": spec.declared_external,
            "roles": list(spec.roles),
            "tags": list(spec.tags),
            "handler_name": handler_identity(spec.handler),
        }
        for spec in reg._specs.values()
    }


def baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 三条判据的纯函数
#
# 三条都抽成纯函数：负控若自己另写一套判断，它证明的只是"另写的那套会红"。


def contract_diffs(before: dict[str, dict], after: dict[str, dict]) -> list[str]:
    """逐键比对两份声明，返回差异描述（空列表 = 契约完全相同）。"""
    diffs: list[str] = []
    for name in sorted(set(before) - set(after)):
        diffs.append(f"{name}：这件工具不见了")
    for name in sorted(set(after) - set(before)):
        diffs.append(f"{name}：多出一件基线里没有的工具")
    for name in sorted(set(before) & set(after)):
        for key in CONTRACT_KEYS:
            if before[name][key] != after[name][key]:
                diffs.append(f"{name}：{key} 变了（{before[name][key]!r} → {after[name][key]!r}）")
    return diffs


def description_ratio(baseline_total: int, current_total: int) -> float:
    """现值的比例（1.0 = 一个字没压；≤ MAX_RATIO 才算压到了）。"""
    if baseline_total <= 0:
        raise ValueError("基线总量不是正数 ⇒ 这条判据失去对象（反真空）")
    return current_total / baseline_total


def missing_needles(needles: dict[str, list[str]], summaries: dict[str, str]) -> list[str]:
    """返回「本应还在、却找不到了」的 needle（空列表 = 一条不少）。"""
    gone: list[str] = []
    for name, items in needles.items():
        text = summaries.get(name)
        if text is None:
            gone.append(f"{name}：工具不见了，它的 {len(items)} 条 needle 无从谈起")
            continue
        for needle in items:
            if needle not in text:
                gone.append(f"{name}：说明里找不到被断言的 {needle!r}")
    return gone


def assert_needles_of(path: Path) -> list[str]:
    """从一份测试文件里抽「`assert X in <声明面>`」形态的字面量 X。

    ⚠️ 不用 `ast.get_source_segment`：它每次都把整份源码重新切一遍，413 个测试文件
    逐个 assert 调一次要两分钟。这里自己算行首**字节**偏移（`col_offset` 是 UTF-8
    字节偏移），一次拿全。
    """
    data = path.read_bytes()
    try:
        tree = ast.parse(data.decode("utf-8", errors="replace"))
    except SyntaxError:  # pragma: no cover - 语法错的测试文件轮不到本判据管
        return []
    lines = data.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))

    def seg(node: ast.AST) -> str:
        raw = data[starts[node.lineno - 1] + node.col_offset:
                   starts[node.end_lineno - 1] + node.end_col_offset]
        return raw.decode("utf-8", errors="replace")

    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        if not any(hint in seg(node) for hint in SURFACE_HINTS):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Compare):
                continue
            if not all(isinstance(op, (ast.In, ast.NotIn)) for op in sub.ops):
                continue
            for left, right in zip([sub.left, *sub.comparators[:-1]], sub.comparators):
                if not (isinstance(left, ast.Constant) and isinstance(left.value, str)):
                    continue
                if any(hint in seg(right) for hint in SURFACE_HINTS):
                    out.append(left.value)
    return out


def collected_needles(summaries: dict[str, str]) -> dict[str, list[str]]:
    """现算一遍 needle（与基线同一口径）：新增的断言若指向已删的字句，这里会露出来。"""
    literals: set[str] = set()
    for path in sorted(TESTS.rglob("*.py")):
        literals.update(assert_needles_of(path))
    literals = {x for x in literals if len(x) >= MIN_NEEDLE}
    out: dict[str, list[str]] = {}
    for name, text in summaries.items():
        got = sorted((x for x in literals if x in text), key=len, reverse=True)
        keep: list[str] = []
        for item in got:
            if not any(item in kept for kept in keep):
                keep.append(item)
        if keep:
            out[name] = sorted(keep)
    return out


# ---------------------------------------------------------------- 语义钉子（两条）
#
# 这两条断言不是字面量形态（比的是**集合**与**单词**），而它们要证明的正是
# 「压说明不许把关键约束压掉」，所以留在这里；各自对应的既有判据在 docstring 里。


def download_class_names(text: str) -> set[str]:
    """`search.download` 的说明+声明里出现的失败类别（受控词表里的 + `http_NNN`）。"""
    from agentflow import fetch as F

    return {k for k in set(F.ERROR_KINDS) if k in text} | set(re.findall(r"http_\d{3}", text))


def a_manual_class_names() -> set[str]:
    """A 的「找文献」技能正文里出现的失败类别（`test_agent_a_recovery_face.py` 的对齐面）。"""
    from agentflow import agent_skills as AS

    for skill in AS.skills_for("A"):
        if skill.slug.startswith("找文献"):
            return download_class_names(str(skill.body))
    raise AssertionError("A 的『找文献』技能不见了 —— 这条对齐失去了对手方")


# ---------------------------------------------------------------- 夹具


@pytest.fixture(scope="module")
def current() -> dict[str, dict]:
    return declarations()


@pytest.fixture(scope="module")
def frozen() -> dict:
    return baseline()


# ---------------------------------------------------------------- 1) 契约不变


def test_declaration_contracts_are_unchanged(current: dict[str, dict], frozen: dict) -> None:
    """① 契约不变：与压缩前的声明快照逐键相同（参数名/类型/required/枚举/默认值/returns…）。"""
    diffs = contract_diffs(frozen["declarations"], current)
    assert diffs == [], (
        "工具的声明契约被改动了 —— 这一批只许改 summary：\n  " + "\n  ".join(diffs)
    )
    assert len(current) == frozen["n_tools"], (
        f"名册规模变了：基线 {frozen['n_tools']} 件，现在 {len(current)} 件"
    )


# ---------------------------------------------------------------- 2) 说明变短


def test_descriptions_shrank_by_at_least_a_quarter(current: dict[str, dict], frozen: dict) -> None:
    """② 说明总量降 ≥25%（判据写死比例，写死的数字比『看起来短了』可审）。"""
    total = sum(len(row["summary"]) for row in current.values())
    base = frozen["baseline_summary_chars"]
    ratio = description_ratio(base, total)
    assert ratio <= MAX_RATIO, (
        f"工具说明总量 {total} 字符 = 基线的 {ratio:.1%}，要求 ≤ {MAX_RATIO:.0%}"
        f"（基线 {base} 字符）。差值 {total - int(base * MAX_RATIO)} 字符。"
    )
    # 反真空：总量不能是 0 或退化成"所有工具一句极短的话" —— 那样 ② 会被白送。
    assert total > 0 and all(row["summary"].strip() for row in current.values()), (
        "有工具的说明变成空的了：说明是给人和模型看的唯一一句，删字不是删信息"
    )


# ---------------------------------------------------------------- 3) needle 全在


def test_every_asserted_literal_survives(current: dict[str, dict], frozen: dict) -> None:
    """③ 被测试断言过的字面量一条不少（含"新加的断言不许指向已删的字句"）。"""
    summaries = {name: row["summary"] for name, row in current.items()}
    gone = missing_needles(frozen["needles"], summaries)
    assert gone == [], "压缩把测试断言过的字面量删掉了：\n  " + "\n  ".join(gone)

    # 反真空：needle 清单不能是空的（空了 ③ 就是纸面通过）。
    assert sum(len(v) for v in frozen["needles"].values()) >= 20, (
        "基线里的 needle 太少 ⇒ 这条判据失去对象"
    )
    # 收集口径不许悄悄变窄：基线里那 25 条必须仍然能被同一口径收出来。
    live = collected_needles(summaries)
    lost_from_collection = sorted(
        f"{name}:{needle}"
        for name, items in frozen["needles"].items()
        for needle in items
        if needle not in live.get(name, [])
    )
    assert lost_from_collection == [], (
        "这些 needle 现在收不出来了（收集口径被改窄，或者说明里那几句被删了）：\n  "
        + "\n  ".join(lost_from_collection)
    )


def test_the_two_semantic_pins_hold(current: dict[str, dict]) -> None:
    """语义钉子：`verify.check_formal` 的「真跑」还在；`search.download` 的失败类别与 A 手册相等。"""
    cf = current["verify.check_formal"]["summary"]
    assert "真跑" in cf, "`verify.check_formal` 的说明不再写「真跑」⇒ 模型会以为它只是登记"
    assert "未接线" not in cf, "它已经接线了，说明里不许再写「未接线」"

    dl = current["search.download"]
    tool_classes = download_class_names(dl["summary"] + "\n" + dl["returns"])
    assert tool_classes == a_manual_class_names(), (
        f"`search.download` 的失败类别 {sorted(tool_classes)} 与 A 的手册 "
        f"{sorted(a_manual_class_names())} 对不上 —— 两边必须是同一个集合（少一边就有读者被漏掉）"
    )


# ---------------------------------------------------------------- 负控（三条）


def test_negative_control_a_renamed_param_or_a_dropped_returns_key_goes_red(
        current: dict[str, dict], frozen: dict) -> None:
    """负控①：改一个**参数名**、删一个 **returns 键** ⇒ ① 必须红。"""
    renamed = {name: dict(row) for name, row in current.items()}
    params = json.loads(json.dumps(renamed["table.get"]["params"]))
    assert "id" in params.get("properties", {}), "夹具前提：table.get 的参数里真的有一个 `id`"
    params["properties"]["row_id"] = params["properties"].pop("id")
    renamed["table.get"]["params"] = params
    assert contract_diffs(frozen["declarations"], renamed), (
        "改了一个参数名而 ① 没红 ⇒ 它钉的不是契约"
    )

    dropped = {name: dict(row) for name, row in current.items()}
    dropped["table.get"]["returns"] = "去掉键之后的 returns"
    assert contract_diffs(frozen["declarations"], dropped), (
        "改了 returns 而 ① 没红 ⇒ 它钉的不是契约"
    )

    # 反负控：一个字都没改的那一份不许被误判（否则 ① 会变成"凡有差异都红"）
    assert contract_diffs(frozen["declarations"], current) == []


def test_negative_control_putting_a_long_essay_back_goes_red(
        current: dict[str, dict], frozen: dict) -> None:
    """负控②：把某条说明加回长论述 ⇒ ② 必须红；而"没压够一半"也要红。"""
    base = frozen["baseline_summary_chars"]
    total = sum(len(row["summary"]) for row in current.values())

    # (a) 整批说明退回压缩前那种体量
    assert description_ratio(base, base) > MAX_RATIO, "没压过的说明居然过了 ②"
    # (b) 只把最长的三条说明退回压缩前（其余保持压缩后）
    restored = dict(current)
    for name in ("conductor.closing", "search.download", "conductor.state"):
        before_len = frozen["summary_lens_before"][name]
        restored[name] = dict(restored[name], summary="x" * before_len)
    restored_total = total - sum(len(current[n]["summary"]) for n in
                                 ("conductor.closing", "search.download", "conductor.state")) \
        + sum(frozen["summary_lens_before"][n] for n in
              ("conductor.closing", "search.download", "conductor.state"))
    assert description_ratio(base, restored_total) > MAX_RATIO, (
        f"把三条最长的说明退回压缩前的体量（{restored_total} 字符）而 ② 没红 ⇒ 它其实没在量"
    )
    # (c) 反负控：压缩后的现值必须过
    assert description_ratio(base, total) <= MAX_RATIO

    # (d) 基线总量不是正数 ⇒ 判据失去对象，必须抛错而不是判"通过"
    with pytest.raises(ValueError):
        description_ratio(0, 0)


def test_negative_control_deleting_a_needle_goes_red(
        current: dict[str, dict], frozen: dict) -> None:
    """负控③：删一条 needle（`review_acceptance`）⇒ ③ 必须红。"""
    summaries = {name: row["summary"] for name, row in current.items()}
    mutilated = dict(summaries)
    needle = "review_acceptance"
    assert needle in summaries["conductor.closing"], "夹具前提：这条 needle 现在真的在里面"
    mutilated["conductor.closing"] = summaries["conductor.closing"].replace(needle, "（删掉了）")
    gone = missing_needles(frozen["needles"], mutilated)
    assert gone, "删了一条 needle 而 ③ 没红 ⇒ 它钉的不是「一条不少」"

    # 反负控：一件工具整个不见了，同样必须被报出来（不是静默跳过）
    assert missing_needles({"conductor.closing": [needle]}, {}), "工具不见了却没人报"

    # 反负控：原样那一份不许被误判
    assert missing_needles(frozen["needles"], summaries) == []
