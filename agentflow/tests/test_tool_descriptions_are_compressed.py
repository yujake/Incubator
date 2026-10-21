# -*- coding: utf-8 -*-
"""判据：工具说明压到「一两句」，而声明契约一个字都没动。
十个角色的 system prompt 里，工具声明是最大的一块静态文本（实测 G 的工具面 4 237 字符 / 提示词 37 093 字符，而 function-calling 的声明 JSON 是 26 117 字符 = 70.4%）。那一批只压 `summary` 一格
—— 参数 schema、`returns`、`side_effect`、`roles` 都是契约，一个字没动；`summary` 从「一段长文」压到「一两句」，保留做什么 / 什么时候用 / 关键约束，删掉为什么这么设计、历史沿革、长例子与重复
`returns` 的返回键清单。
判据守的是「压缩那一批的说明不得回涨」：86 件的名单冻结在基线 `compression_cohort`，比例只在 cohort 上算（现总量 ≤ 基线 75%）。2026-10-20 新增的 8 件（`lit.stage_add` / `lit.stage_list` /
`lit.stage_withdraw` / `lit.stage_reject` / `lit.overlap_check` / `lit.admit` / `lit.admit_all` / `conductor.escalate`）没被压过，
算进分子分母等于要求新工具自带压缩配额（全库口径 84.1% 会红）。这口径不是放宽：分母 `baseline_summary_chars` 必须逐件等于 `summary_lens_before` 之和，少算一件 `cohort_ratio` 直接抛 `ValueError`。
四条判据各自只证明一件事：① `test_declaration_contracts_are_unchanged` 与 `tests/fixtures/tool_declaration_baseline.json` 里压缩前那份逐键比（`params` / `returns` /
`side_effect` / `roles` 等与工具集合都必须相同；差异只在 `contract_amendments` 有 `reason` 时放行）；② `test_cohort_descriptions_shrank_by_at_least_a_quarter` 看总量
≤75%；③ `test_every_new_tool_is_registered` 要求不在 cohort 里的每件工具在基线 `declarations` 里有一行且带 `added_after_compression: true`；④
`test_every_asserted_literal_survives` 要求 `assert X in <声明面>` 的每条 needle 都还在（不可字面量化的两条由 `test_tool_summary_readings.py` 等守着）。
契约会合法演进：本轮枚举新增 `lit_candidates`（16 → 17 张表），`table.count` / `create` / `delete` / `get` / `list` / `search` / `update` 七件的 `params` 各变两处，
处置是把基线重冻并留 `reason` + 逐项编辑清单（内容寻址：差异要变成 `value_edits` 并与某条 `amendments` 的 `tools` / `key` / `edits` 逐项相等，改另一个枚举值或只动「N 张表之一」都对不上）。
每条负控打在同一条判据函数上：改参数名 / 删 `returns` 键 ⇒ ① 红（`test_negative_control_a_renamed_param_or_a_dropped_returns_key_goes_red`）；偷改 `table.create` 枚举 ⇒
① 红（`test_negative_control_a_silent_table_enum_edit_goes_red`）；塞回 200 字论述 ⇒ ② 红（`test_negative_control_putting_a_long_essay_back_goes_red`）；
删掉 `lit.admit` 那一行 ⇒ ③ 红（`test_negative_control_an_unregistered_new_tool_goes_red`）；删一条 needle ⇒ ④
红（`test_negative_control_deleting_a_needle_goes_red`）。
"""

from __future__ import annotations

import ast
import copy
import json
import re
import tempfile
from collections.abc import Sequence
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
#: 分母 = 压缩批次（`compression_cohort`）压缩前的总量，不是全库 —— 理由见 docstring。
MAX_RATIO = 0.75

#: 新增名单里必须登记的那 8 件（2026-10-20 新增，不在压缩批次里）。
#: 判据只要求「这 8 件都在」；将来再加新工具时只改基线，不必改这里。
EXPECTED_NEW_TOOLS: frozenset[str] = frozenset({
    "lit.stage_add", "lit.stage_list", "lit.stage_withdraw", "lit.stage_reject",
    "lit.overlap_check", "lit.admit", "lit.admit_all", "conductor.escalate",
})

#: needle 的收集口径：断言右操作数（或整条 assert 源码）里出现这些词 ⇒ 它断言的是
#: 「声明面」的文字。刻意不写成「任何测试字符串」—— 理由见文件 docstring。
#: `line` / `面` 也在里面：`assert "sha256" in detail_line` 这种读的是这一行的读数，
#: 与 `text` / `desc` 是同一族（读数面）。
SURFACE_HINTS: tuple[str, ...] = (
    "summary", "prompt", "text", "desc", "tools_lines", "spec", "line", "面",
)

#: needle 最短长度（字符）。更短的（`ok` / `id` / 单字）没有判别力。
MIN_NEEDLE = 5

#: 基线 `contract_amendments` 里的编辑词汇。改这里等于改「什么算记过账」。
EDIT_OPS: tuple[str, ...] = (
    "append_item", "remove_item", "replace_item", "add_key", "remove_key", "set_scalar",
)


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


def summaries_of(current: dict[str, dict]) -> dict[str, str]:
    return {name: row["summary"] for name, row in current.items()}


# ---------------------------------------------------------------- 契约差异：结构化编辑
#
# 契约判据与基线里的 `contract_amendments` 共用同一套编辑词汇：这样「记了 reason」
# 不是一句嘴上的豁免，而是一份必须逐项对上的编辑清单（内容寻址）。


def _minus(items: list, other: list) -> list:
    """多重集差：`items` 里有、`other` 里没有的（按出现次数扣减），保持原顺序。"""
    budget = list(other)
    out: list = []
    for item in items:
        if item in budget:
            budget.remove(item)
        else:
            out.append(item)
    return out


def value_edits(before: object, after: object, path: str = "") -> list[dict]:
    """两份 JSON 值之间的结构化差异（词汇见 `EDIT_OPS`；空列表 = 完全相同）。

    粒度刻意选在「叶子」上：字典逐键递归、等长列表逐位比、不等长列表按多重集
    增删、标量给 `from`/`to`。表枚举那种「列表里多一项」记成 `append_item`，
    而在原位改掉一个值记成 `replace_item` —— 后者与前者对不上，这正是
    「偷偷改一个枚举值」抓得住的原因。
    """
    out: list[dict] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after), key=str):
            sub = f"{path}/{key}" if path else str(key)
            if key not in before:
                out.append({"op": "add_key", "path": sub, "value": after[key]})
            elif key not in after:
                out.append({"op": "remove_key", "path": sub, "value": before[key]})
            else:
                out.extend(value_edits(before[key], after[key], sub))
        return out
    if isinstance(before, list) and isinstance(after, list):
        if len(before) == len(after):
            for index, (old, new) in enumerate(zip(before, after)):
                if old != new:
                    out.append({"op": "replace_item", "path": path,
                                "index": index, "from": old, "to": new})
            return out
        for item in _minus(after, before):
            out.append({"op": "append_item", "path": path, "item": item})
        for item in _minus(before, after):
            out.append({"op": "remove_item", "path": path, "item": item})
        return out
    if before != after or type(before) is not type(after):
        out.append({"op": "set_scalar", "path": path, "from": before, "to": after})
    return out


def _resolve(root: object, path: str) -> object:
    node = root
    for part in path.split("/"):
        if isinstance(node, dict):
            node = node[part]
        elif isinstance(node, list):
            node = node[int(part)]
        else:  # pragma: no cover - 基线里写了走不通的路径才会到这里
            raise TypeError(f"路径 {path!r} 走到 {type(node).__name__} 上，走不下去")
    return node


def apply_edits(value: object, edits: list[dict], reverse: bool = False) -> object:
    """把编辑清单应用到一个值上（`reverse=True` 则逐项退回）。

    存在的理由：正控要证明「基线里记过的那一次演进真的被放行」—— 只有能
    把现值退回改动前，才能拿出那份差异去撞判据。退不回去的编辑清单 = 记的账
    与盘上的东西对不上，必须报错而不是悄悄跳过。
    """
    out = copy.deepcopy(value)
    for edit in edits:
        op = edit["op"]
        if op not in EDIT_OPS:  # pragma: no cover - 词表外的 op 是基线写坏了
            raise AssertionError(f"基线 contract_amendments 里出现了词表外的编辑 {op!r}")
        if op in ("append_item", "remove_item", "replace_item"):
            # 列表类编辑的 path 指的是列表本身（不是「列表/键」）
            target = _resolve(out, str(edit["path"]))
            if op == "append_item":
                target.remove(edit["item"]) if reverse else target.append(copy.deepcopy(edit["item"]))
            elif op == "remove_item":
                target.append(copy.deepcopy(edit["item"])) if reverse else target.remove(edit["item"])
            else:
                target[edit["index"]] = copy.deepcopy(edit["from"] if reverse else edit["to"])
            continue
        # 键类编辑：path 的最后一段是键名，前面是它的容器
        parent_path, _, leaf = str(edit["path"]).rpartition("/")
        parent = _resolve(out, parent_path) if parent_path else out
        if op == "add_key":
            if reverse:
                del parent[leaf]
            else:
                parent[leaf] = copy.deepcopy(edit["value"])
        elif op == "remove_key":
            if reverse:
                parent[leaf] = copy.deepcopy(edit["value"])
            else:
                del parent[leaf]
        else:  # set_scalar
            parent[leaf] = copy.deepcopy(edit["from"] if reverse else edit["to"])
    return out


def apply_contract_edits(row: dict, key: str, edits: list[dict],
                         reverse: bool = False) -> object:
    """按记账把「一行声明里的那一格」推进/退回。

    路径以整行为根（`params` / `returns` / … 是路径的第一段）——与
    `contract_diffs` 里 `value_edits(..., path=key)` 的口径完全同一套，否则记的账
    与撞判据用的差异会长得不一样。
    """
    return apply_edits({key: row[key]}, edits, reverse=reverse)[key]


def describe_edit(edit: dict) -> str:
    """一条编辑的人话描述（差异读数是给人看的，别让人去数括号）。"""
    op, path = edit["op"], edit["path"]
    if op == "append_item":
        return f"{path}：追加 {edit['item']!r}"
    if op == "remove_item":
        return f"{path}：删掉 {edit['item']!r}"
    if op == "replace_item":
        return f"{path}[{edit['index']}]：{edit['from']!r} → {edit['to']!r}"
    if op == "add_key":
        return f"{path}：新增键（值 {edit['value']!r}）"
    if op == "remove_key":
        return f"{path}：删掉键（原值 {edit['value']!r}）"
    return f"{path}：{edit['from']!r} → {edit['to']!r}"


def canonical(edits: list[dict]) -> tuple[str, ...]:
    """编辑清单的比较口径：逐项序列化后排序（顺序不影响「是不是同一件事」）。"""
    return tuple(sorted(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in edits))


def amendment_for(amendments: Sequence[dict], name: str, key: str,
                  edits: list[dict]) -> dict | None:
    """找一条逐项对上的已记账演进；没有就返回 None（= 没记 `reason`）。"""
    want = canonical(edits)
    for amend in amendments or ():
        if amend.get("key") != key:
            continue
        if name not in tuple(amend.get("tools") or ()):
            continue
        if not str(amend.get("reason") or "").strip():
            # 记了账但没写理由 = 没记（「理由」是这条记录唯一可审的部分）
            continue
        if canonical(amend.get("edits") or []) == want:
            return amend
    return None


def contract_diffs(before: dict[str, dict], after: dict[str, dict],
                   amendments: Sequence[dict] = ()) -> list[str]:
    """逐键比对两份声明，返回差异描述（空列表 = 契约完全相同或差异已逐项记账）。"""
    diffs: list[str] = []
    for name in sorted(set(before) - set(after)):
        diffs.append(f"{name}：这件工具不见了（基线里有、现盘上没有）—— 删工具也要在基线里登记")
    for name in sorted(set(after) - set(before)):
        diffs.append(f"{name}：多出一件基线里没有的工具 —— 新增工具必须在基线里登记")
    for name in sorted(set(before) & set(after)):
        for key in CONTRACT_KEYS:
            old, new = before[name][key], after[name][key]
            if old == new:
                continue
            edits = value_edits(old, new, path=key)
            if amendment_for(amendments, name, key, edits) is not None:
                continue
            diffs.append(
                f"{name}：{key} 变了，基线里没有逐项对上的 reason —— "
                + "；".join(describe_edit(e) for e in edits)
            )
    return diffs


# ---------------------------------------------------------------- 比例：只在压缩批次上算


def ratio_of(baseline_total: int, current_total: int) -> float:
    """现值的比例（1.0 = 一个字没压；≤ MAX_RATIO 才算压到了）。"""
    if baseline_total <= 0:
        raise ValueError("基线总量不是正数 ⇒ 这条判据失去对象（反真空）")
    return current_total / baseline_total


def cohort_ratio(frozen: dict, summaries: dict[str, str]) -> float:
    """压缩批次的说明比例：分子分母都只取 `compression_cohort` 那批人。

    少算一件就抛 `ValueError`：一件工具从现盘上消失，等于把它的字数从分子分母
    里一起抹掉 —— 那不是「压得更狠」，那是判据失去对象。
    """
    cohort = tuple(frozen["compression_cohort"])
    base = int(frozen["baseline_summary_chars"])
    if not cohort:
        raise ValueError("compression_cohort 是空的 ⇒ 比例判据失去对象（反真空）")
    missing = [name for name in cohort if name not in summaries]
    if missing:
        raise ValueError(
            f"压缩批次的工具在现盘上不见了：{missing} —— 少算一件就是把它的字数"
            f"从分子分母里一起抹掉"
        )
    current_total = sum(len(summaries[name]) for name in cohort)
    return ratio_of(base, current_total)


def cohort_problems(frozen: dict) -> list[str]:
    """基线内部一致性：名单 / 逐件长度 / 总量 / 新增标记四者必须互相对得上。

    这是「比例判据」的锚：分母 8932 必须逐件等于 `summary_lens_before` 之和，
    所以想靠「把某件工具从 cohort 里踢出去」来减分母，改一处就会在这里露出来。
    """
    problems: list[str] = []
    cohort = list(frozen["compression_cohort"])
    decl = frozen["declarations"]
    added = list((frozen.get("added_after_compression") or {}).get("tools") or ())
    lens = frozen["summary_lens_before"]

    if len(set(cohort)) != len(cohort):
        problems.append("compression_cohort 里有重名")
    if len(cohort) != int(frozen.get("n_cohort", len(cohort))):
        problems.append(f"compression_cohort 有 {len(cohort)} 件，n_cohort 写的是 {frozen.get('n_cohort')}")
    unknown = sorted(name for name in cohort if name not in decl)
    if unknown:
        problems.append(f"compression_cohort 里的这些名字基线里没有声明：{unknown}")
    if len(decl) != int(frozen["n_tools"]):
        problems.append(f"基线声明 {len(decl)} 件，n_tools 写的是 {frozen['n_tools']}")
    if set(lens) != set(cohort):
        problems.append(
            "summary_lens_before 的键与 compression_cohort 不是同一批："
            f"多 {sorted(set(lens) - set(cohort))}，少 {sorted(set(cohort) - set(lens))}"
        )
    flagged = {name for name, row in decl.items()
               if row.get("added_after_compression") is True}
    if set(added) != flagged:
        problems.append(
            "added_after_compression.tools 与逐行标记的真值不是同一批："
            f"名单多 {sorted(set(added) - flagged)}，标记多 {sorted(flagged - set(added))}"
        )
    both = sorted(set(cohort) & (set(added) | flagged))
    if both:
        problems.append(f"这些工具既在压缩批次里又标了 added_after_compression：{both}")
    if set(cohort) | set(added) != set(decl):
        problems.append(
            "基线声明必须正好等于「压缩批次 ∪ 新增」："
            f"没归类的 {sorted(set(decl) - set(cohort) - set(added))}"
        )
    lens_total = sum(int(lens[name]) for name in cohort if name in lens)
    if lens_total != int(frozen["baseline_summary_chars"]):
        problems.append(
            f"baseline_summary_chars 写的是 {frozen['baseline_summary_chars']}，"
            f"压缩批次逐件加出来是 {lens_total} —— 分母被改过（或漏加/多加了一件）"
        )
    return problems


# ---------------------------------------------------------------- 新工具登记


def registration_problems(frozen: dict, current: dict[str, dict]) -> list[str]:
    """③ 新增工具必须在基线里登记（带 `added_after_compression: true`）。

    双向都查：名单说有 ⇒ 基线里必须有行、有标记、现盘上必须有这件工具；
    现盘上有而不在压缩批次里 ⇒ 必须登记、必须有标记、必须在名单里。
    任一条不成立都返回描述（空列表 = 全部登记好了）。
    """
    problems: list[str] = []
    cohort = set(frozen["compression_cohort"])
    decl = frozen["declarations"]
    added = list((frozen.get("added_after_compression") or {}).get("tools") or ())

    for name in added:
        row = decl.get(name)
        if row is None:
            problems.append(f"{name}：名单里说它是新增的，基线里却没有它的声明行（= 没登记）")
        elif row.get("added_after_compression") is not True:
            problems.append(f"{name}：基线里有它的声明行，但没带 added_after_compression: true")
        if name not in current:
            problems.append(f"{name}：基线标它是新增的，现盘上却没有这件工具")

    for name in sorted(set(current) - cohort):
        row = decl.get(name)
        if row is None:
            problems.append(f"{name}：现盘上有这件工具，基线里没登记它")
        elif row.get("added_after_compression") is not True:
            problems.append(f"{name}：基线里登记了，但没标 added_after_compression: true")
        elif name not in added:
            problems.append(f"{name}：标了 added_after_compression 但不在 added_after_compression.tools 名单里")
    return problems


# ---------------------------------------------------------------- needle


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

     不用 `ast.get_source_segment`：它每次都把整份源码重新切一遍，413 个测试文件
    逐个 assert 调一次要两分钟。这里自己算行首字节偏移（`col_offset` 是 UTF-8
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
# 这两条断言不是字面量形态（比的是集合与单词），而它们要证明的正是
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
    diffs = contract_diffs(frozen["declarations"], current,
                           frozen.get("contract_amendments") or ())
    assert diffs == [], (
        "工具的声明契约被改动了 —— 这一批只许改 summary；合法的演进要在基线 "
        "`contract_amendments` 里留一条带 reason 的**逐项编辑清单**：\n  "
        + "\n  ".join(diffs)
    )
    assert len(current) == frozen["n_tools"], (
        f"名册规模变了：基线 {frozen['n_tools']} 件，现在 {len(current)} 件"
    )


def test_the_recorded_amendments_are_the_only_thing_they_excuse(
        current: dict[str, dict], frozen: dict) -> None:
    """正控：基线里记过账的那一次演进真的被放行，且只放行它自己那一次。

    不做这条，"记了 reason 就放行"这句话没有任何人验过 —— 而一条从不生效的
    豁免机制与一段死代码在读数上分不开。
    """
    declarations_baseline = frozen["declarations"]
    amendments = frozen.get("contract_amendments") or ()
    assert amendments, "基线里没有任何 contract_amendments ⇒ 这条正控失去对象"

    for amend in amendments:
        key = amend["key"]
        assert amend["reason"].strip(), f"这条 amendment 没写 reason：{amend}"
        first = amend["tools"][0]
        # 记的账必须真能退回改动前（退不回去 = 账与盘上的东西对不上）
        reverted_first = apply_contract_edits(current[first], key, amend["edits"], reverse=True)
        assert canonical(amend["edits"]) == canonical(
            value_edits(reverted_first, current[first][key], path=key)
        ), f"基线里那条 amendment 的 edits 与它声明的 key 对不上：{amend}"

        # 把「改动前的那一版」重建成一份声明，拿它当 before、现盘当 after：
        # 这份差异就是基线记过账的那一次演进，逐项能对上。
        preamended = {name: dict(row) for name, row in current.items()}
        for name in amend["tools"]:
            preamended[name] = dict(preamended[name])
            preamended[name][key] = apply_contract_edits(current[name], key, amend["edits"],
                                                         reverse=True)

        # 没有记账 ⇒ 这份差异必须红（否则「记账」这件事没有对手方）
        assert contract_diffs(preamended, current), (
            f"{amend['tools']}：把记过账的那次改动退回去却没红 ⇒ 契约判据没在看 {key}"
        )
        # 有记账 ⇒ 同一份差异必须被放行
        assert contract_diffs(preamended, current, amendments) == [], (
            f"{amend['tools']}：基线里明明记过这次演进，契约判据却仍判红 —— "
            f"记账机制失效了（那条 amendment 成了死代码）"
        )
        # 而现盘对基线（两边都是改动后）必须本来就干净
        assert contract_diffs(declarations_baseline, current, amendments) == []


# ---------------------------------------------------------------- 2) 说明没回涨


def test_cohort_descriptions_shrank_by_at_least_a_quarter(
        current: dict[str, dict], frozen: dict) -> None:
    """② 压缩批次（86 件）的说明总量降 ≥25%（比例写死，写死的数字比『看起来短了』可审）。"""
    problems = cohort_problems(frozen)
    assert problems == [], "基线的「压缩批次」口径自身对不上：\n  " + "\n  ".join(problems)
    assert frozen["max_ratio"] == MAX_RATIO, (
        f"基线 max_ratio={frozen['max_ratio']} 与判据 MAX_RATIO={MAX_RATIO} 不一致 —— "
        f"改基线里的那个数就是在改门槛"
    )

    summaries = summaries_of(current)
    ratio = cohort_ratio(frozen, summaries)
    total = sum(len(summaries[name]) for name in frozen["compression_cohort"])
    base = frozen["baseline_summary_chars"]
    assert ratio <= MAX_RATIO, (
        f"压缩批次（{len(frozen['compression_cohort'])} 件）的说明总量 {total} 字符 = "
        f"基线的 {ratio:.2%}，要求 ≤ {MAX_RATIO:.0%}（基线 {base} 字符）。"
        f"超了 {total - int(base * MAX_RATIO)} 字符。"
    )
    # 反真空：总量不能是 0 或退化成"所有工具一句极短的话" —— 那样 ② 会被白送。
    assert total > 0 and all(row["summary"].strip() for row in current.values()), (
        "有工具的说明变成空的了：说明是给人和模型看的唯一一句，删字不是删信息"
    )
    # 新工具不进比例：它们从没被压过，既不在分子也不在分母。
    assert not set(frozen["compression_cohort"]) & set(
        (frozen.get("added_after_compression") or {}).get("tools") or ())
    # 反真空：现盘上真的存在「不在压缩批次里」的工具，否则「只在 cohort 上算」
    # 与「全库一起算」是同一个数，这条口径就是一句空话。
    extra = sum(len(summaries[name]) for name in current
                if name not in set(frozen["compression_cohort"]))
    assert extra > 0, (
        "现盘上没有任何不在压缩批次里的工具 ⇒ 「比例只在 cohort 上算」失去对象"
    )


# ---------------------------------------------------------------- 3) 新工具已登记


def test_every_new_tool_is_registered(current: dict[str, dict], frozen: dict) -> None:
    """③ 新 8 件都在基线里、且带 `added_after_compression: true`（不登记 ⇒ 红）。"""
    problems = registration_problems(frozen, current)
    assert problems == [], "新增工具没在基线里登记好：\n  " + "\n  ".join(problems)

    added = set((frozen.get("added_after_compression") or {}).get("tools") or ())
    missing = sorted(EXPECTED_NEW_TOOLS - added)
    assert missing == [], f"基线新增名单里少了这几件（2026-10-20 的那一批）：{missing}"
    for name in sorted(EXPECTED_NEW_TOOLS):
        row = frozen["declarations"][name]
        assert row.get("added_after_compression") is True, (
            f"{name}：基线里登记了，但没写 added_after_compression: true —— "
            f"没有这个标记，下一轮没人知道它不该进压缩比例"
        )
        assert name in current, f"{name}：基线说有这件工具，现盘上没有"
    # 反真空：新增名单不能空，否则这条判据就是纸面通过。
    assert len(added) >= len(EXPECTED_NEW_TOOLS)
    note = str((frozen.get("added_after_compression") or {}).get("note") or "")
    assert "2026-10-20" in note and "不计入压缩比例" in note, (
        "基线新增名单旁边没写清「2026-10-20 新增、不计入压缩比例」—— 下一轮的人只能猜"
    )


# ---------------------------------------------------------------- 4) needle 全在


def test_every_asserted_literal_survives(current: dict[str, dict], frozen: dict) -> None:
    """④ 被测试断言过的字面量一条不少（含"新加的断言不许指向已删的字句"）。"""
    summaries = summaries_of(current)
    gone = missing_needles(frozen["needles"], summaries)
    assert gone == [], "压缩把测试断言过的字面量删掉了：\n  " + "\n  ".join(gone)

    # 反真空：needle 清单不能是空的（空了 ④ 就是纸面通过）。
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


# ---------------------------------------------------------------- 负控（五条）


def test_negative_control_a_renamed_param_or_a_dropped_returns_key_goes_red(
        current: dict[str, dict], frozen: dict) -> None:
    """负控①：改一个参数名、删一个 returns 键 ⇒ ① 必须红。"""
    amendments = frozen.get("contract_amendments") or ()

    renamed = {name: dict(row) for name, row in current.items()}
    params = json.loads(json.dumps(renamed["table.get"]["params"]))
    assert "id" in params.get("properties", {}), "夹具前提：table.get 的参数里真的有一个 `id`"
    params["properties"]["row_id"] = params["properties"].pop("id")
    renamed["table.get"] = dict(renamed["table.get"], params=params)
    assert contract_diffs(frozen["declarations"], renamed, amendments), (
        "改了一个参数名而 ① 没红 ⇒ 它钉的不是契约"
    )

    dropped = {name: dict(row) for name, row in current.items()}
    dropped["table.get"] = dict(dropped["table.get"], returns="去掉键之后的 returns")
    assert contract_diffs(frozen["declarations"], dropped, amendments), (
        "改了 returns 而 ① 没红 ⇒ 它钉的不是契约"
    )

    # 反负控：一个字都没改的那一份不许被误判（否则 ① 会变成"凡有差异都红"）
    assert contract_diffs(frozen["declarations"], current, amendments) == []


def test_negative_control_a_silent_table_enum_edit_goes_red(
        current: dict[str, dict], frozen: dict) -> None:
    """负控⑤：偷改表枚举里的一个值（基线没记逐项对上的 reason）⇒ ① 必须红。

    这是「`params` 不许变」这条判据有没有被放宽的试金石：本轮为了「表枚举新增
    `lit_candidates`」重冻了七件 `table.*` 的 `params`，如果那条 amendment 被写成
    「table.* 的 params 随便动」，下面第一条就会绿 —— 那才是真正的放宽。
    """
    amendments = frozen.get("contract_amendments") or ()

    tampered = copy.deepcopy(current)
    enum = tampered["table.create"]["params"]["properties"]["table"]["enum"]
    seat = enum.index("lit_candidates")
    enum[seat] = "lit_candidatez"
    assert contract_diffs(frozen["declarations"], tampered, amendments), (
        "把 lit_candidates 偷偷改成 lit_candidatez 而契约判据没红 ⇒ amendment 变成了通行证"
    )

    # 只动「N 张表之一」那句、不带枚举：编辑清单同样对不上 ⇒ 也必须红
    prose = copy.deepcopy(current)
    prose["table.create"]["params"]["properties"]["table"]["description"] = "若干张表之一"
    assert contract_diffs(frozen["declarations"], prose, amendments), (
        "只改了表枚举那句描述而契约判据没红 ⇒ amendment 变成了一张空白支票"
    )

    # 记了账但没写理由 = 没记
    unreasoned = [dict(amend, reason="") for amend in amendments]
    if unreasoned:
        reverted = {name: dict(row) for name, row in current.items()}
        first = amendments[0]
        name = first["tools"][0]
        reverted[name] = dict(reverted[name])
        reverted[name][first["key"]] = apply_contract_edits(
            current[name], first["key"], first["edits"], reverse=True)
        assert contract_diffs(frozen["declarations"], reverted, unreasoned), (
            "reason 是空串的 amendment 居然也放行了 ⇒ 「记 reason」这句话没被检查"
        )


def test_negative_control_putting_a_long_essay_back_goes_red(
        current: dict[str, dict], frozen: dict) -> None:
    """负控②：把 cohort 里某条说明塞回 200 字论述 / 整批退回压缩前 ⇒ ② 必须红。"""
    summaries = summaries_of(current)
    base = int(frozen["baseline_summary_chars"])
    cohort = tuple(frozen["compression_cohort"])

    # (a) 整批说明退回压缩前那种体量
    assert ratio_of(base, base) > MAX_RATIO, "没压过的说明居然过了 ②"
    restored_all = {name: "x" * int(frozen["summary_lens_before"][name]) for name in cohort}
    assert cohort_ratio(frozen, restored_all) > MAX_RATIO, (
        "整批退回压缩前的长度而 ② 没红 ⇒ 它其实没在量"
    )

    # (b) 只把 cohort 里最短的那条塞回 200 字论述
    victim = min(cohort, key=lambda name: len(summaries[name]))
    essay = summaries[victim] + "论述" * 100
    assert len(essay) - len(summaries[victim]) == 200, "夹具前提：塞进去的正好 200 字符"
    with_essay = dict(summaries, **{victim: essay})
    assert cohort_ratio(frozen, with_essay) > MAX_RATIO, (
        f"把 {victim} 的说明塞回 200 字论述（{len(essay)} 字符）而 ② 没红 ⇒ 它没在量回涨"
    )

    # (b2) 只把压得最狠的那一件退回压缩前长度（业主口径里的「改回压缩前长度」）
    worst = max(cohort,
                key=lambda name: int(frozen["summary_lens_before"][name]) - len(summaries[name]))
    only_one = dict(summaries, **{worst: "x" * int(frozen["summary_lens_before"][worst])})
    assert cohort_ratio(frozen, only_one) > MAX_RATIO, (
        f"只把 {worst} 一件退回压缩前长度（{frozen['summary_lens_before'][worst]} 字符）"
        f"而 ② 没红 ⇒ 它只能抓「整批回涨」，抓不住「一件一件慢慢长回去」"
    )

    # (c) 反负控：压缩后的现值必须过
    assert cohort_ratio(frozen, summaries) <= MAX_RATIO

    # (d) 一件 cohort 工具从现盘上消失 ⇒ 抛错（不是静默把它从分子分母里抹掉）
    dropped = {name: text for name, text in summaries.items() if name != victim}
    with pytest.raises(ValueError):
        cohort_ratio(frozen, dropped)
    # (e) 基线总量不是正数 / 名单是空的 ⇒ 判据失去对象，必须抛错而不是判"通过"
    with pytest.raises(ValueError):
        ratio_of(0, 0)
    with pytest.raises(ValueError):
        cohort_ratio(dict(frozen, compression_cohort=[]), summaries)


def test_negative_control_an_unregistered_new_tool_goes_red(frozen: dict,
                                                            current: dict[str, dict]) -> None:
    """负控④：从基线里删掉 `lit.admit` 那一行（模拟「新工具不登记」）⇒ ③ 必须红。"""
    amputed = copy.deepcopy(frozen)
    assert "lit.admit" in amputed["declarations"], "夹具前提：基线里真的有 lit.admit 这一行"
    del amputed["declarations"]["lit.admit"]
    amputed["n_tools"] = len(amputed["declarations"])
    problems = registration_problems(amputed, current)
    assert problems, "删了一件新工具的登记行而 ③ 没红 ⇒ 它钉的不是「必须登记」"
    assert any("lit.admit" in p for p in problems), f"报的不是 lit.admit：{problems}"

    # (b) 行还在、但把 added_after_compression 标记摘掉 ⇒ 同样红
    unflagged = copy.deepcopy(frozen)
    unflagged["declarations"]["lit.admit"].pop("added_after_compression")
    assert registration_problems(unflagged, current), (
        "摘掉 added_after_compression 标记而 ③ 没红 ⇒ 那个标记没人看"
    )
    # (c) 名单里偷偷加一件 cohort 工具（拿老工具冒充新工具）⇒ 也必须红
    smuggled = copy.deepcopy(frozen)
    smuggled["added_after_compression"]["tools"].append("table.get")
    assert registration_problems(smuggled, current), (
        "把一件压缩批次里的老工具塞进新增名单而 ③ 没红 ⇒ 名单可以随便糊"
    )
    # (d) 反负控：原样那一份不许被误判
    assert registration_problems(frozen, current) == []


def test_negative_control_deleting_a_needle_goes_red(
        current: dict[str, dict], frozen: dict) -> None:
    """负控⑥：删一条 needle（`review_acceptance`）⇒ ④ 必须红。"""
    summaries = summaries_of(current)
    mutilated = dict(summaries)
    needle = "review_acceptance"
    assert needle in summaries["conductor.closing"], "夹具前提：这条 needle 现在真的在里面"
    mutilated["conductor.closing"] = summaries["conductor.closing"].replace(needle, "（删掉了）")
    gone = missing_needles(frozen["needles"], mutilated)
    assert gone, "删了一条 needle 而 ④ 没红 ⇒ 它钉的不是「一条不少」"

    # 反负控：一件工具整个不见了，同样必须被报出来（不是静默跳过）
    assert missing_needles({"conductor.closing": [needle]}, {}), "工具不见了却没人报"

    # 反负控：原样那一份不许被误判
    assert missing_needles(frozen["needles"], summaries) == []
