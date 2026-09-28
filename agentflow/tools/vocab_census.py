#!/usr/bin/env python
"""受控词表普查（`G-26` 第一步）：一个取值被定义了、却没有任何地方产出它。

## 这一版只做一半，而且把另一半写出来

本工具只查"死取值"：词表里登记了、而 `src/` 里找不到产出点的取值。
另一个方向 "漏词表"（代码产出了不在任何词表里的字面量）没有实现 ——
它逐字写在输出的"已知缺口"一节里，不靠读者猜。为什么先做这一半：

- "死取值"是可判定的：值在不在文本里出现，是个能机械化的事实；
- "漏词表"需要一个"哪些字面量算产出"的口径，而那个口径正是 `P-22`/`P-23`
  要人裁决的东西（补产出 / 删词表 / 登记为预留）。替人定口径再把它包成红灯，
  等于用门逼出一个未经裁决的改法。

## 为什么有下限断言（反真空，`P16`）

若扫描器读不到词表、或读不到任何产出点，它会把一切都报成"没有死取值" ——
那是假绿。所以这里对"扫到几个词表""扫到几个产出点"各设下限，不满足就报
`unknown`(2)：没查成不是没问题。

## `P-23` 点名但普查看不见的四条（前三条进登记表，会打印在"栏一附"）

`P-23` 的清单里有几条结构上落不进 `dead` 这一栏。它们的登记照样打印
（输出里的"栏一附：已登记为预留、但今天普查看不见它是死取值"），
而不是被悄悄吞掉 —— 登记表里有一条而输出里查无此条，比不登记更糟：

- `DOC_KINDS:survey` —— `survey` 这个字面量在 `providers.py` 里是主题类别
  （provider 返回的 type 描述词那一列），不是文档种类：同形不同义。
- `DEP_KINDS:lemma` —— 普查报它"有产出"，而那个产出是 `formalgw._DECL_KEYWORDS` 里的
  Lean 关键字 `"lemma"`：同名词、不同义。普查用正则找"带引号的字面量"，
  它分辨不了"这个词出现了"与"这个取值被产出了"。
- `DEP_KINDS:dataset` —— 同理：命中的是 `providers.py` 的文献类型码 `"dataset": "Z"`
  与 `agent_g.py` 测试夹具里的一个 kind，都不是 `DEP_KINDS` 的生产点。
- `capabilities:UNKNOWN_SIDE_EFFECT` —— 它不是任何词表里的取值，而是
  `capabilities.py` 里的一个模块级常量（`UNKNOWN_SIDE_EFFECT = "unknown"`）。
  本工具的判据是"以 `VOCAB_SUFFIXES` 结尾的字符串元组"，单个常量不在扫描范围内，
  所以它连"同形不同义"都算不上。它的语义（三态纪律的"未知"档、且被 `_WRITE_LIKE`
  当写者处理）不是词表遗漏，是刻意设计。见 `capabilities.py:70-76`。
  这一条只在本节写明，不进登记表（登记一个不存在于任何词表里的键没有意义）。

⇒ 前三条是已知漏检的一种形态（"字面量出现了，但不是那个意思"），
与 `R010` 的 `ocr.backends` 那条同族。它们在这里逐条写明，不靠读者猜。

## 退出码

`0` = 查过了、没有死取值；`1` = 查过了、有死取值；`2` = 没查成（读不到源码树 / 词表数或产出点数低于下限）。
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import time
from pathlib import Path

#: 词表命名的判据：模块里以这些后缀结尾、且值是"字符串元组"的常量。
#: 刻意不写死"有哪几个词表"（那样新增词表会静默落在普查之外，而数字照样好看）：
#: 取到几个就报几个，并把名单打进输出（`G-32`：数字要能追溯到对象）。
VOCAB_SUFFIXES: tuple[str, ...] = ("_KINDS", "_STATUSES", "_OUTCOMES", "_SCOPES")

#: 反真空下限：这两个数字不是判据，只是"扫描器确实读到东西了"的最低证据；低于它一律判没查成。
#: 真实仓库的当次规模不写死（`G-32`）：由 `python tools/vocab_census.py` 的汇总行当次读
#: —— 观测 2026-09-27 14:56:51 ⇒ 词表 20 个（产出点五万行量级，同一条汇总行当次给）。
MIN_VOCABS = 3
MIN_PRODUCER_LINES = 50

#: 已登记为"预留"的取值：`{(词表名, 取值): 理由}`。
#:
#: ## 为什么这张表存在
#:
#: `P-23` 要求审计输出分两栏（"已登记为预留" / "无人认领"）并且不许合并 ——
#: 合并等于静默豁免：一个"没人认领的死取值"与一个"写明为什么留着"的取值会被读成同一件事。
#:
#: 往这张表里加一条是人的动作：它的语义是"我知道这个取值现在没有产出点，我决定留着，
#: 理由是这个"。所以本工具只提供位置（登记表 + 两栏输出），不替谁填 ——
#: 与"只出 info 不做成红灯"是同一条纪律：不替人做口径裁定。
#:
#: ## `P-22` / `P-23` 的裁定（选项 c：登记为预留）
#:
#: 登记表只能有一处，就是这里。 不许在 `schema.py` 里另写一份"预留"标记：
#: 同一件事两个落点必然漂移，而漂移的表现是"审计说预留、schema 说没有"（FC-03）。
#:
#: 为什么选 c 而不是另外两条路（原裁定理由照抄，`P-23` 自己推荐 c）：
#:
#: - 最便宜且不撒谎。删词表值（选项 b）要动 `schema.py` 且带"追溯性"争议；
#:   补产出（选项 a）对 `quote_mismatch` 不是接线而是新能力 ——
#:   实测：`quoteverify.check_quote` 的 `reason` 取值只有 `no_text_layer` / `empty_quote` /
#:   `substring_match` / `substring_match_outside_declared_range` / `substring_match_fulltext` /
#:   `not_found` / `not_found_page_unknown` —— 根本没有"找到了但不一样"这一档。
#:   所以 (a) 会正好撞上 `P-22` 自己的负控（"只写了名字、没有 code 能算出它 ⇒
#:   审计必须仍然报死取值"）。
#:
#: ## 一处推翻：`FINDING_KINDS.quote_mismatch` 改走 (b)（`E-10` 裁定，2026-09-27）
#:
#: 上面那条"最便宜且不撒谎"的取舍对其余取值仍然成立，但
#: `FINDING_KINDS.quote_mismatch` 这一条被单独重裁为 (b) 删词表值：
#: 它描述的是一个做不到的承诺（词表说会报"引文不符"，实现只给 `not_found`），
#: 而"登记为预留"对一条假承诺不是最便宜的处置 —— 假承诺留在词表里，
#: 读者照样会以为系统会报"引文不符"。所以那个取值已从
#: `schema.FINDING_KINDS` 删除，本登记表里的那一条同时删除
#: （登记一个不存在的取值就是"登记已过期"，会被 `R011` 打进栏一附）。
#: 想恢复这个能力，请作为新条目提出（附阈值标定方案）—— 不许把值加回来。
#:
#: `reserved` 不是"通过"。它必须照样打印（含理由），因为它回答的是
#: "这个取值为什么还留着" —— 静默豁免是本项目最忌的形态（`G-13`/`N-5` 同族）。
#:
#: 本表的键不要求出现在 `dead` 里 —— 有些被点名的取值"同形不同义"，
#: 普查看得见字面量却看不见那是死取值。这类条目会打印在栏一附里，
#: 于是它们既不会静默消失，也不会伪装成"已确认无产出"。
#: `UNKNOWN_SIDE_EFFECT` 是唯一不进本表的被点名项：它不是任何词表里的取值，
#: 而是 `capabilities.py` 的一个模块级常量（见模块 docstring 那一节）。
RESERVED_VALUES: dict[tuple[str, str], str] = {
    # 这里曾经有一条 `("FINDING_KINDS", "quote_mismatch")` 的登记。
    # `E-10` 裁定 (b)（2026-09-27）把那个取值从 `schema.FINDING_KINDS` 删掉了
    # （理由见上面"一处推翻"那一节：它对一条做不到的承诺做预留），
    # 于是这条登记同时消失 —— 登记一个不存在的取值就是"登记已过期"。
    ("DOC_KINDS", "reproduction_report"): (
        "死取值。agent_g 只写 note/paper 一类的稿件，没有任何地方建 kind="
        "'reproduction_report' 的文档行。留着的理由：它对应 E→G 的『独立复现报告』这条交付物，"
        "是设计里明确存在、只是尚未接线的一类产物；删掉它会让『复现报告』在词表里无处安放。"
    ),
    # `FINAL-R7-08` 更正：这里原本还有一份 `("DOC_KINDS", "survey")`，与下面那条同名重复，
    # 字典字面量里后一条静默覆盖前一条 —— 于是这 7 行是死文本，而读登记表的人会以为
    # survey 有两条独立理由。重复的那一份已删，留下的是下面那条（它多写了一句
    # "普查看不见它是死取值"）。
    ("DEP_KINDS", "proposition"): (
        "死取值。agent_g.register_dependency 的 kind 取值里没有 proposition。留着的理由："
        "数学文献里『命题』是与 theorem/lemma 并列的标准依赖种类，删掉会让一条依赖无法如实登记。"
    ),
    ("DEP_KINDS", "prior_art"): (
        "死取值。留着的理由：FC-23 的『先行工作』是必须能与 theorem/experiment 分开的一类依赖 ——"
        "『我引了一篇同类工作』与『我用了一条定理』的证据力完全不同，合并会让依赖计数虚高。"
    ),
    # ---- 下面三条是"同形不同义"：普查看不见它们是死取值，所以它们会打印在栏一附里。
    # 之所以仍然登记（而不是只写在 docstring 里）：登记表是机器可读的那一份，
    # 写在这里才会被打印出来、才会在"这条其实已经接线了"时被人看见。
    ("DOC_KINDS", "survey"): (
        "普查看不见它是死取值：`survey` 这个字面量在 `providers.py` 里是主题类别"
        "（provider 返回的 type 描述词那一列：'survey'/'review'/'introduction'/'textbook'/"
        "'overview'），不是文档种类。同形不同义 ⇒ 正则命中它、而 `DOC_KINDS` 却拿不到产出。"
        "留着的理由：综述是 G 的一类正式交付物，将来 agent_g 会写它；删掉它等于说"
        "『本框架不产出综述』—— 那不是我们的事实。"
    ),
    ("DEP_KINDS", "lemma"): (
        "普查看不见它是死取值：它报的『有产出』来自 `formalgw._DECL_KEYWORDS` 里的 "
        "Lean 关键字 `\"lemma\"`。同名词、不同义 —— 那是『源码里能声明 lemma』，"
        "不是『有一条 kind='lemma' 的依赖被登记』。留着的理由：lemma 是与 theorem 并列的"
        "标准依赖种类，删掉会让一条引理级的依赖无处安放。"
    ),
    ("DEP_KINDS", "dataset"): (
        "普查看不见它是死取值：命中的是 `providers.py` 的文献类型码 `\"dataset\": \"Z\"` "
        "与 `agent_g.py` 里一个测试夹具的 kind。两者都不是 `DEP_KINDS` 的生产点。"
        "留着的理由：引用了外部数据集是一条真实且必须能与 theorem 分开的依赖"
        "（`external_unavailable` 那一档就是为它这类准备的）。"
    ),
}


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码（GBK 下打印中文/符号会抛 UnicodeEncodeError）。

    内联的理由与其它门脚本同：门必须在本包 import 不了时也能跑。规范实现见
    `src/agentflow/console.py::pin_utf8`。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 可以忽略：被重定向或被替换过的流可能没有 reconfigure，不该让门崩掉。
            pass


def _vocab_constants(schema_py: Path) -> dict[str, list[str]]:
    """从 `schema.py` 的 AST 里取词表：`名字以 VOCAB_SUFFIXES 结尾` 且值是字符串序列。"""
    try:
        tree = ast.parse(schema_py.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"schema 读不了或解析失败：{type(exc).__name__}: {exc}") from None

    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not names or not any(n.endswith(VOCAB_SUFFIXES) for n in names):
            continue
        if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            continue
        items = [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if items:
            out[names[0]] = items
    return out


def _producer_text(src_dir: Path, exclude: Path) -> tuple[str, int]:
    """把 `src/**/*.py`（排除词表定义所在的那个文件）读成一大段文本。

    为什么要排除定义点：不排除的话每个取值都会"命中它自己的定义"，于是永远报不出死取值 ——
    那是这条普查最典型的假绿形态。
    """
    parts: list[str] = []
    lines = 0
    for p in sorted(src_dir.rglob("*.py")):
        if p == exclude:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        parts.append(text)
        lines += text.count("\n") + 1
    return "\n".join(parts), lines


def census(root: Path) -> dict:
    """跑一次普查，返回结果字典（`checked` 为假表示没查成）。"""
    src = root / "src"
    schema_py = src / "agentflow" / "schema.py"
    if not schema_py.is_file():
        return {"checked": False, "reason": f"读不到 {schema_py}"}
    try:
        vocabs = _vocab_constants(schema_py)
    except ValueError as exc:
        return {"checked": False, "reason": str(exc)}
    blob, producer_lines = _producer_text(src, schema_py)
    if len(vocabs) < MIN_VOCABS:
        return {"checked": False, "reason": f"只扫到 {len(vocabs)} 个词表（下限 {MIN_VOCABS}）"}
    if producer_lines < MIN_PRODUCER_LINES:
        return {"checked": False, "reason": f"产出点只有 {producer_lines} 行（下限 {MIN_PRODUCER_LINES}）"}

    dead: dict[str, list[str]] = {}
    for name, values in sorted(vocabs.items()):
        missing = [v for v in values if not re.search(rf"['\"]{re.escape(v)}['\"]", blob)]
        if missing:
            dead[name] = missing

    # 两栏分开算、分开给（`P-23`：不许合并 —— 合并等于静默豁免）。
    #
    # 栏一取的是"登记表"而不是"死取值 ∩ 登记表" —— 这个区别是刻意的：
    # 有些被点名的取值机械普查看不见它是死的（`survey` 在 `providers.py` 里是
    # 主题类别 ⇒ 正则命中它；见模块 docstring 的那一节）。若栏一只取交集，
    # 那一条登记就会一个字都不打印 —— 那是比"静默豁免"更糟的形态：
    # 登记表看上去处理了它，而输出里查无此条。
    # 所以栏一按登记表原样打印，并单独标出哪几条今天普查看不见，
    # 让"同形不同义"与"其实已经接线了"这两种情况都必须被人看见。
    reserved: dict[str, list[str]] = {}
    unclaimed: dict[str, list[str]] = {}
    registered_not_dead: dict[str, list[str]] = {}
    dead_pairs = {(name, v) for name, values in dead.items() for v in values}
    for (name, v) in sorted(RESERVED_VALUES):
        bucket = reserved if (name, v) in dead_pairs else registered_not_dead
        bucket.setdefault(name, []).append(v)
    for name, values in dead.items():
        for v in values:
            if (name, v) not in RESERVED_VALUES:
                unclaimed.setdefault(name, []).append(v)
    return {
        "checked": True,
        "vocabs": {k: len(v) for k, v in sorted(vocabs.items())},
        "producer_lines": producer_lines,
        "dead": dead,
        "reserved": reserved,
        "unclaimed": unclaimed,
        #: 已登记为预留、但今天普查不认为它是死取值的那些。两种成因都要人看一眼：
        #: ① 同形不同义（普查看见了字面量，但那是另一个命名空间里的词）；
        #: ② 它其实已经接线了 ⇒ 登记表这一条过期了，应当撤掉。
        "registered_not_dead": registered_not_dead,
        # 这几个数字是分开的，刻意不提供"死取值合计"那一个合并数字当门面 ——
        # 但保留它作诊断（`dead_total`），输出时两栏并列打印。
        "dead_total": sum(len(v) for v in dead.values()),
        "reserved_total": sum(len(v) for v in reserved.values()),
        "unclaimed_total": sum(len(v) for v in unclaimed.values()),
        "registered_not_dead_total": sum(len(v) for v in registered_not_dead.values()),
        "reserved_reasons": {f"{k[0]}.{k[1]}": why for k, why in sorted(RESERVED_VALUES.items())},
        # 没实现的那一半必须出现在输出里（"没查成"与"查过没问题"要能分开）。
        "known_gap": "反向（漏词表：代码产出了不在词表里的字面量）本版未实现 —— 它的口径是 P-22/P-23 的人类裁决项",
    }


def main(argv: list[str] | None = None) -> int:
    _pin_utf8()
    ap = argparse.ArgumentParser(
        prog="vocab_census",
        description=(
            "受控词表普查：找出登记了却没有产出点的取值（死取值）。"
            "退出码 0=没有 / 1=有 / 2=没查成。"
        ),
    )
    ap.add_argument("--root", default=None, help="仓库根（默认本文件的上两级）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args(list(argv) if argv is not None else None)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    t0 = time.monotonic()
    result = census(root)
    secs = time.monotonic() - t0

    if args.json:
        print(json.dumps({**result, "root": str(root), "seconds": round(secs, 2)}, ensure_ascii=False, indent=2))
    elif not result["checked"]:
        print(f"[vocab-census] unknown(2)：没查成 —— {result['reason']}")
    else:
        print(f"[vocab-census] 词表 {len(result['vocabs'])} 个 / 产出点 {result['producer_lines']} 行（{secs:.1f}s）")
        # 两栏必须分开打印、且两栏都打（`P-23`）：合并等于静默豁免。
        # 即使某一栏为空也要打出来 —— "这一栏是空的"本身是信息。
        print(
            f"[vocab-census] 栏一：已登记为预留 {result['reserved_total'] + result['registered_not_dead_total']} 个"
            f"（其中 {result['registered_not_dead_total']} 个今天普查看不见它是死取值 —— 见栏一附）"
        )
        for name, values in sorted(result["reserved"].items()):
            for v in values:
                why = result["reserved_reasons"].get(f"{name}.{v}", "（未写理由：登记表要求写）")
                print(f"  {name}.{v}：预留 —— {why}")
        # 栏一附：登记了、但普查不认为它是死的。必须打印 ——
        # 否则那几条登记在输出里查无此条，等于登记表自己骗自己。
        if result["registered_not_dead_total"]:
            print(
                f"[vocab-census] 栏一附：已登记为预留、但今天普查看不见它是死取值 "
                f"{result['registered_not_dead_total']} 个 ⇒ 需人确认是『同形不同义』还是『登记已过期』"
            )
            for name, values in sorted(result["registered_not_dead"].items()):
                for v in values:
                    why = result["reserved_reasons"].get(f"{name}.{v}", "（未写理由：登记表要求写）")
                    print(f"  {name}.{v}：预留（普查未见其为死取值）—— {why}")
        print(f"[vocab-census] 栏二：无人认领 {result['unclaimed_total']} 个")
        for name, values in sorted(result["unclaimed"].items()):
            print(f"  {name}：{len(values)} 个取值在 src/ 里找不到产出点 —— {values}")
        print(
            f"[vocab-census] 死取值合计 {result['dead_total']} 个"
            "（这一行只是诊断；判定请分别看两栏，不许用合计代替分栏）"
        )
        print(f"[vocab-census] 已知缺口：{result['known_gap']}")

    if not result["checked"]:
        return 2
    return 1 if result["dead_total"] else 0


if __name__ == "__main__":  # pragma: no cover - 由 tests 直接调 main()
    raise SystemExit(main())
