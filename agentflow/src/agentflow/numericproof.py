# -*- coding: utf-8 -*-
"""E 签的数值证据：穷举证明（`proof_reason="exhaustion"`）与「有数值实验支持」的分界。

业主 2026-10-23 的裁定（要点逐字）：

> 「如果纯数值实验直接把整个命题证掉了，那也能拿 proof 标识，理由是穷举，签名是对应的
> 程序脚本。一般的理论命题只是拿不完全的数值实验探路的不能靠此拿 proof，只能说有数值
> 实验支持。这些有关数值实验的都由 E 来签。若要入定理证明库，证明栏写程序地址
> （相对于仓库）。」

于是本模块是这几件事的唯一口径（判据、写侧、读侧都从这里取，不许各写一份）：

1. 穷举判定：一次计算类实验的记录里，只要「整个论域被穷尽验证」这件事是可核的
   （搜索空间 + 布尔 true 的 exhaustive + ② 程序设计 + ③ 穷举论证），它就够 proof
   这一档；缺任何一条 —— 包括「说不清」的那一档 —— 都只能落到
   :data:`SUPPORTED_ONLY_KIND`（即 `cross_check`，它的定义本来就写着
   "数值/穷举交叉验证，不构成证明"）。
2. 签名主体（业主 2026-10-23 晚更正）：签字由 V，`signed_by` 只能是
   :data:`PROOF_SIGNER`（V），不许出现 `signed_by="E"`；E 是 :data:`NUMERIC_AUTHOR`，
   写进 `proof_authors`（②③ 的原作者）。V 的逐行走查仍不覆盖数值证据 ——
   "签字"与"逐行审阅"是两件事（见 :func:`verifier_covers` / :func:`verifier_problems`）。
   B 不许给自己产出的命题自签 proof。
3. 证明栏（业主 2026-10-23 晚的硬口径）：必须由三部分组成 ——
   ① 程序相对地址（相对仓库）、② 程序设计（要解决什么、按什么结构搜、为什么覆盖全域）、
   ③ 穷举论证（搜索空间多大、怎么算出、对称性/剪枝、为什么不漏、边界怎么处理）。
   ②③ 都由 E 写，B 只负责原样登记（不许自己编、也不许把 E 的读数改写成自己的话）。
   落点是 `statements.proof_text` 一份文本、三段标签固定（:func:`compose_proof_column`）：
   这样 `schema.Statement` 不用加字段，而"B 改了一个字"可以由逐段比对抓出来。
4. "形式化"那一格（业主 2026-10-23 晚）：数值实验定理填数值实验程序（相对仓库路径），
   普通理论定理填 Lean 程序（`.lean` 路径）—— 两者同一格、填的东西不同，
   不许互相冒充。判据见 :func:`formal_slot`（判据 ⑧）。

## 为什么「穷尽证据」这几个键就够（而不是再要一份证书）

`certificate` 说的是"在 B 内没有反例"的证书，`search_bound` 说的是那个 B —— 它们是
穷举类方法在数据面上的既有载体（`schema.Experiment` 硬约束 2c）。而业主点名要的是
更基本的几件：搜索空间是什么、是不是 exhaustive、以及 ②③ 那两段人话。前两件本来就在
`search_bound` / 脚本自报的 `observations` 里，后两件只有写它们的人（E）说得清。
所以判据读这几件，`certificate` 有则一并留下、没有也不强求（`method="exhaustive_search"`
那一档仍由 schema 的硬约束 2c 强制要证书）。

## 三态纪律在这里的样子

`exhaustive` 只认布尔值本身：缺省、`"true"`、`1` 一律当"这一格没说清"（判不了），
不许读成"说过了"。判不了与"明确说不是"在结论上都是"拿不到 proof"，但理由不同 ——
`problems` 里逐条写清缺哪一条，读的人才知道该补什么。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

#: 能让「穷举直接证掉整个命题」成立的方法（计算类）。
#:
#: 与 `schema.EXPERIMENT_METHODS` 的关系：那四种 = 这三种 + `formal`。两份不许漂，
#: 判据 `tests/test_t0_tier_and_exhaustion_proof.py::test_calculation_methods_cover_schema`
#: 钉着这一点（这里不 import schema：schema 要 import 本模块，反向 import 会成环）。
CALCULATION_METHODS: tuple[str, ...] = ("numeric", "symbolic", "exhaustive_search")

#: 形式化那一档的方法名（它的证据由检查器说，不由本模块签）。
FORMAL_METHOD = "formal"

#: 「证明理由」的受控词表。今天只有一档：穷举。
#:
#: 为什么必须受控：`proof` 这一档一旦能由计算类方法拿到，"凭什么"就成了整条链上
#: 最关键的一句话；自由文本写"因为我都算过了"与写"exhaustion"在下游读起来不一样。
PROOF_REASON_EXHAUSTION = "exhaustion"
PROOF_REASONS: tuple[str, ...] = (PROOF_REASON_EXHAUSTION,)

#: 证明的签名主体（业主 2026-10-23 晚的更正：签字由 V，不是 E）。
#:
#: 这一格经过一次改口径，两个版本都记在这里，免得后人以为哪个是笔误：
#: 先前那版写「这些有关数值实验的都由 E 来签」⇒ `signed_by="E"`；业主随后更正为
#: 「签字仍然由 V 签（不是 E）。E 是 ②③ 的原作者，但签名主体是 V」⇒ 现在
#: `signed_by` 只能是 :data:`PROOF_SIGNER`（V），不许出现 `signed_by="E"`
#: （判据 ⑦ 与 `filing_problems` 都会拒）。E 的位置是 :data:`NUMERIC_AUTHOR`：
#: ②③ 的作者，写进 `proof_authors`。
PROOF_SIGNER = "V"
#: ②③ 的作者（业主：「② 与 ③ 都由 E 写」）。
NUMERIC_AUTHOR = "E"
#: 形式化那一档那条程序的作者（`.lean` 由 L 落库，`evidencebits.BIT_OWNERS["formal"]`）。
FORMAL_AUTHOR = "L"
#: 兼容别名：早先那一版把这个名字当"签名者"用，现在它的意思是"②③ 的作者"。
#: 读侧只该用它来问"这两块是谁写的"，签名者一律走 :data:`PROOF_SIGNER`。
NUMERIC_SIGNER = NUMERIC_AUTHOR

#: 「只是有数值实验支持」那一档的取值 —— 沿用既有受控词表，不新造词。
#:
#: `schema.EVIDENCE_KINDS` 里 `cross_check` 的定义逐字是"数值/穷举交叉验证，
#: 不构成证明"，所以"有数值实验支持"这句话的落点本来就有，不必加第五个取值。
SUPPORTED_ONLY_KIND = "cross_check"
#: 上面那一档给人读的名字（读数与拒信里用它，免得读者去猜 `cross_check` 是什么）。
SUPPORTED_ONLY_LABEL = "有数值实验支持（cross_check，不构成证明）"

#: 穷尽证据的几格在盘上的键名（`observations` / `certificate.detail` / `search_bound`）。
EXHAUSTIVE_KEY = "exhaustive"
#: ③ 穷举论证的键名。`coverage` 是它的历史别名（同一件事的两种写法都认，
#: 但新写的一律用 `enumeration`）：业主 2026-10-23 晚把这一格的含义说全了 ——
#: 「搜索空间多大、怎么算出、对称性/剪枝、为什么不漏、边界怎么处理」。
ENUMERATION_KEY = "enumeration"
ENUMERATION_ALIASES: tuple[str, ...] = ("enumeration", "coverage")
#: ② 程序设计的键名（业主：「思路：要解决什么、按什么结构搜、为什么覆盖全域」）。
DESIGN_KEY = "design"
#: 搜索空间的候选键名（脚本自报时常见的那几种写法）。
SPACE_KEYS: tuple[str, ...] = ("search_space", "space", "domain", "enumerated")

#: E 的签名落在 `experiments.observations` 的这一格（不新增列）。
#:
#: 为什么不加一列：`schema.Experiment` 是磁盘格式契约，加字段要走人裁；
#: 而 `observations` 本来就是"这一次到底算了什么"的机器可读格，签名是它的自然成员。
SIGNATURE_KEY = "e_signature"

#: 签名里"这两块是谁写的"那一格（业主 2026-10-23 晚：②③ 的作者必须是 E）。
PROOF_AUTHORS_KEY = "proof_authors"

#: 证明栏的三段（业主 2026-10-23 晚的硬口径：证明栏必须由三部分组成）。
#:
#: 每一段写成 `标签：正文` 的单行（正文可以续行，解析时归到上一段）。
#: 顺序就是业主给的那个顺序：① 程序相对地址、② 程序设计、③ 穷举论证。
PROOF_PARTS: tuple[tuple[str, str], ...] = (
    ("程序", "script"),
    ("程序设计", "design"),
    ("穷举论证", "enumeration"),
)
#: 标签 → 段名、段名 → 标签（同一份表派生，不写第二份）。
PART_LABELS: dict[str, str] = {label: name for label, name in PROOF_PARTS}
PART_NAMES: dict[str, str] = {name: label for label, name in PROOF_PARTS}

#: 程序脚本的常见后缀（证明栏写的是脚本时用它判"这是不是一段代码而不是一段散文"）。
SCRIPT_SUFFIXES: tuple[str, ...] = (
    ".py", ".jl", ".r", ".m", ".sage", ".sh", ".ps1", ".cpp", ".cc", ".c",
    ".rs", ".hs", ".lean", ".ipynb",
)


def is_calculation(method: Any) -> bool:
    """这个方法是不是"计算类"（数值/符号/穷举）—— 本模块只管这三档。"""
    return str(method or "") in CALCULATION_METHODS


def signer_of(method: Any) -> str:
    """这一档证明的签名主体：一律 V（业主 2026-10-23 晚的更正）。

    两档（数值/形式化）的签名主体是同一个：V 是这张台账上"签字"的那一岗。
    变的只是 ②③ 或 `.lean` 的作者（见 :func:`author_of`）。
    """
    return PROOF_SIGNER


def author_of(method: Any) -> str:
    """证明材料（②③ / `.lean` 程序）的作者：计算类归 E，形式化归 L。"""
    return NUMERIC_AUTHOR if is_calculation(method) else FORMAL_AUTHOR


def verifier_covers(method: Any) -> bool:
    """V 的逐行走查（`verify.verify_proof` 那一趟"审每步依据"的活）覆不覆盖这一类证据。

    签名主体是 V（见 :func:`signer_of`），但"签字"与"逐行走查"是两件事：
    数值证据的材料是程序 + E 的 ②③，V 没有跑过那份程序，所以逐行走查不覆盖它 ——
    这一签是数值证据的背书，不是对一段自然语言证明的逐行审阅（两条读数分开写，
    见 `verifier_problems`）。把它折成"V 审过了"就是替 E 说话。
    """
    return not is_calculation(method)


def is_script_path(text: Any) -> bool:
    """这一串字是不是"工作区内的程序脚本相对路径"（证明栏的合法形态）。

    三条同时成立：非空、没有盘符/不以 `/` 开头、不以 `..` 分段、后缀在白名单里。
    后一条是刻意的：`proof_text="穷举验证过"` 这种自然语言摘要也是非空字符串，
    只查"非空"等于让"拿摘要冒充程序地址"照样过关。
    """
    raw = str(text or "").strip().replace("\\", "/")
    if not raw:
        return False
    if raw.startswith("/") or ":" in raw:
        return False
    if ".." in raw.split("/"):
        return False
    return raw.lower().endswith(SCRIPT_SUFFIXES)


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _flag(mapping: Mapping[str, Any]) -> bool | None:
    """从一格字典里读 `exhaustive`：只认布尔值本身。

    缺省 ⇒ `None`（没说）；`"true"` / `1` / `"yes"` ⇒ 也是 `None`（这一格没说清，
    不许替它读成 true）；`False` ⇒ `False`（明确说不是）。
    """
    value = mapping.get(EXHAUSTIVE_KEY)
    return value if isinstance(value, bool) else None


def _exhaustive_reading(observations: Mapping[str, Any],
                        certificate: Mapping[str, Any],
                        search_bound: Mapping[str, Any]) -> tuple[bool | None, str]:
    """按优先级读 `exhaustive`，返回 `(值, 出处)`。出处进签名与拒信。"""
    detail = _as_mapping(certificate.get("detail"))
    for where, mapping in (("observations", observations),
                           ("certificate.detail", detail),
                           ("search_bound", search_bound)):
        flag = _flag(mapping)
        if flag is not None:
            return flag, where
    return None, ""


def _enumeration_reading(observations: Mapping[str, Any],
                         certificate: Mapping[str, Any],
                         search_bound: Mapping[str, Any]) -> tuple[str, str]:
    """读 ③ 穷举论证：`enumeration`（或历史别名 `coverage`）的非空字符串。"""
    detail = _as_mapping(certificate.get("detail"))
    for where, mapping in (("observations", observations),
                           ("certificate.detail", detail),
                           ("search_bound", search_bound)):
        for key in ENUMERATION_ALIASES:
            text = str(mapping.get(key) or "").strip()
            if text:
                return text, f"{where}.{key}"
    return "", ""


def _design_reading(observations: Mapping[str, Any],
                    certificate: Mapping[str, Any],
                    search_bound: Mapping[str, Any]) -> tuple[str, str]:
    """读 ② 程序设计：`design` 的非空字符串（三处任一）。"""
    detail = _as_mapping(certificate.get("detail"))
    for where, mapping in (("observations", observations),
                           ("certificate.detail", detail),
                           ("search_bound", search_bound)):
        text = str(mapping.get(DESIGN_KEY) or "").strip()
        if text:
            return text, f"{where}.{DESIGN_KEY}"
    return "", ""


def _space_reading(observations: Mapping[str, Any],
                   certificate: Mapping[str, Any],
                   search_bound: Mapping[str, Any]) -> tuple[Any, str]:
    """读搜索空间：`search_bound` 非空对象，或脚本自报的三类键之一。返回 `(值, 出处)`。"""
    if search_bound:
        return dict(search_bound), "search_bound"
    for where, mapping in (("observations", observations),
                           ("certificate.detail", _as_mapping(certificate.get("detail")))):
        for key in SPACE_KEYS:
            value = mapping.get(key)
            if isinstance(value, bool) or value in (None, "", [], {}):
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            return value, f"{where}.{key}"
    return None, ""


def exhaustion_problems(*, method: Any,
                        observations: Mapping[str, Any] | None = None,
                        certificate: Mapping[str, Any] | None = None,
                        search_bound: Mapping[str, Any] | None = None,
                        code_path: Any = "",
                        result: Any = "supports") -> list[str]:
    """穷尽判定：空清单 = 整个论域被穷尽验证过（够 proof）；非空 = 缺什么，逐条写清。

    要的东西就是业主 2026-10-23 晚点名的三块（证明栏的三段，作者都是 E）：
    ① 程序相对地址（`code_path`）、② 程序设计（`design`）、③ 穷举论证（`enumeration`），
    外加"可核"这件事本身：布尔 true 的 `exhaustive` 与一个说得出范围的搜索空间。
    """
    problems: list[str] = []
    if not is_calculation(method):
        problems.append(
            f"method={method!r} 不是计算类方法（"
            f"{CALCULATION_METHODS}）⇒ 这一档不由本模块判"
            "（形式化的证据由检查器说，走 formal 那一支）")
    if str(result or "") == "refutes":
        problems.append(
            "result='refutes' ⇒ 反例推翻命题，不是对命题的证明；把证否标成 proof 会让下游误读")
    obs = _as_mapping(observations)
    cert = _as_mapping(certificate)
    bound = _as_mapping(search_bound)
    flag, flag_where = _exhaustive_reading(obs, cert, bound)
    if flag is not True:
        problems.append(
            f"没有可核的 exhaustive 标记（读到 {flag!r}，出处 {flag_where or '（三处都没有这一格）'}）："
            "穷举证明要的是布尔 true 本身 —— \"true\" / 1 / 缺省都算没说清，"
            "而'说不清'不许读成'说过了'")
    design, _design_where = _design_reading(obs, cert, bound)
    if not design:
        problems.append(
            f"缺「程序设计」（{DESIGN_KEY}）：要解决什么、按什么结构搜、为什么覆盖全域 ——"
            "没有它，那份程序只是'跑过'，读的人不知道它在搜什么")
    enumeration, _enum_where = _enumeration_reading(obs, cert, bound)
    if not enumeration:
        problems.append(
            f"缺「穷举论证」（{ENUMERATION_KEY}）：搜索空间多大、怎么算出、"
            "对称性/剪枝、为什么不漏、边界怎么处理 —— 没有它，"
            "'在 B 内没有反例'与'整个论域没有反例'是两句话，而只有后者能叫证明")
    space, _space_where = _space_reading(obs, cert, bound)
    if space is None:
        problems.append(
            "缺搜索空间（search_bound 或 observations 里的 "
            f"{SPACE_KEYS}）：证书脱离边界就没有意义，"
            "读的人无法复核'穷尽了什么'")
    script = str(code_path or "").strip().replace("\\", "/")
    if not is_script_path(script):
        problems.append(
            f"缺程序脚本的相对路径（code_path 读到 {code_path!r}）：穷举证明的签名就是那份程序，"
            "证明栏的第 ① 段要写它的相对路径（含后缀，不含盘符与 `..`）")
    # ---- ②③ 的落盘核查（业主 2026-10-23 晚：「E 写的报告要能落下来」）
    #
    # 判据本体只有一份：`exhaustionreport.landing_problems`（报告在不在、三块齐不齐、
    # 落点与实验号对不对得上、字节数与 sha256 记没记）。这里只把它的结论并进来 ——
    # 缺一份落在盘上、三块齐的读数 ⇒ 本函数的返回值非空 ⇒ 这一行拿不到 proof。
    # 为什么并进这里而不是各入口各写一份：等级的方向由本函数单点决定
    # （`exhaustion_verdict` 只看 `problems` 空不空），所以"报告没落成"与
    # "没有 exhaustive 标记"在下游是同一句话：这条证据不够 proof，逐条说明缺什么。
    problems.extend(report_problems({"observations": obs}))
    return problems


def compose_proof_column(*, script_path: Any, design: Any, enumeration: Any) -> str:
    """把证明栏那三段拼成一份可解析的文本（E 写，B 原样登记）。

    形态（段序固定，标签逐字）::

        程序：code/enum.py
        程序设计：要解决什么、按什么结构搜、为什么覆盖全域
        穷举论证：搜索空间多大、怎么算出、对称性/剪枝、为什么不漏、边界怎么处理

    为什么是这一种而不是三个字段：`statements` 的"证明"栏只有 `proof_text` 一栏，
    加字段要走人裁（schema 是禁改区）。三段合一、标签固定 ⇒ 既不加字段，又能被
    :func:`parse_proof_column` 逐段核（B 改一个字就对不上 E 的签名）。
    """
    return "\n".join(
        f"{label}：{str(value or '').strip()}"
        for label, value in (("程序", script_path), ("程序设计", design), ("穷举论证", enumeration)))


def parse_proof_column(text: Any) -> dict[str, Any]:
    """把证明栏拆成三段：`{"script","design","enumeration","problems","raw"}`。

    解析规则只有一条：以三段标签（`程序：` / `程序设计：` / `穷举论证：`）开头的行换段，
    其余行接在当前段后面（E 可以把一段写成好几行）。认不出的段一律 `""` ——
    宁可判"缺这一段"，也不许把一句散文读成程序地址。
    """
    raw = str(text or "")
    parts: dict[str, str] = {name: "" for _label, name in PROOF_PARTS}
    current = ""
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        hit = ""
        for label, name in PROOF_PARTS:
            if stripped.startswith(f"{label}：") or stripped.startswith(f"{label}:"):
                hit = name
                parts[name] = stripped[len(label) + 1:].strip()
                break
        if hit:
            current = hit
        elif current:
            parts[current] = (parts[current] + "\n" + stripped).strip()
    problems: list[str] = []
    if not is_script_path(parts["script"]):
        problems.append(
            f"缺第 ① 段「程序」的相对路径（读到 {parts['script']!r}）："
            "穷举证明的签名就是那份程序")
    if not parts["design"]:
        problems.append("缺第 ② 段「程序设计」（要解决什么、按什么结构搜、为什么覆盖全域）")
    if not parts["enumeration"]:
        problems.append(
            "缺第 ③ 段「穷举论证」（搜索空间多大、怎么算出、对称性/剪枝、"
            "为什么不漏、边界怎么处理）")
    return {**parts, "problems": problems, "raw": raw}


def proof_column_script(text: Any) -> str:
    """从证明栏里取出第 ① 段的程序路径（认不出 ⇒ 空串）。

    两形态都认：三段式证明栏，以及"只写了一行程序路径"的历史形态（那一种拿不到
    proof，但读侧要认得出它是"数值证据"——V 用它判"这条不归我审"）。
    """
    parsed = parse_proof_column(text)
    if parsed["script"] and is_script_path(parsed["script"]):
        return str(parsed["script"]).strip().replace("\\", "/")
    raw = str(text or "").strip().replace("\\", "/")
    return raw if is_script_path(raw) else ""


def is_exhaustion_proof_column(text: Any) -> bool:
    """这一份证明栏是不是"三段齐全、第 ① 段是程序"（形态判据，不判归属）。"""
    return not parse_proof_column(text)["problems"]


def exhaustion_verdict(*, method: Any,
                       observations: Mapping[str, Any] | None = None,
                       certificate: Mapping[str, Any] | None = None,
                       search_bound: Mapping[str, Any] | None = None,
                       code_path: Any = "",
                       result: Any = "supports") -> dict[str, Any]:
    """一次计算类实验的穷尽判定读数（写侧、B 的入库闸、审计三处共用这一份）。

    返回的 `evidence_kind` 只有两个取值：够 proof（且签名者 E、理由 exhaustion），
    或者 :data:`SUPPORTED_ONLY_KIND`（"有数值实验支持"，不构成证明）。
    """
    problems = exhaustion_problems(method=method, observations=observations,
                                   certificate=certificate, search_bound=search_bound,
                                   code_path=code_path, result=result)
    obs = _as_mapping(observations)
    cert = _as_mapping(certificate)
    bound = _as_mapping(search_bound)
    design, design_where = _design_reading(obs, cert, bound)
    enumeration, enum_where = _enumeration_reading(obs, cert, bound)
    space, space_where = _space_reading(obs, cert, bound)
    script = str(code_path or "").strip().replace("\\", "/")
    enough = not problems
    return {
        "exhaustive": enough,
        "evidence_kind": "proof" if enough else SUPPORTED_ONLY_KIND,
        "label": ("proof（穷举，签名者 E）" if enough else SUPPORTED_ONLY_LABEL),
        "proof_reason": PROOF_REASON_EXHAUSTION if enough else "",
        "signed_by": signer_of(method),
        # ②③ 的作者：业主 2026-10-23 晚的点名 —— 这两块都由 E 写。
        "proof_authors": [author_of(method)],
        # 证明栏：三段齐全才给；不够时留空（不许拿它冒充证据）。
        "script_path": script if enough else "",
        "design": design,
        "enumeration": enumeration,
        "proof_text": (compose_proof_column(script_path=script, design=design,
                                           enumeration=enumeration) if enough else ""),
        "coverage_where": enum_where,
        "design_where": design_where,
        "search_space": space,
        "search_space_where": space_where,
        "problems": problems,
    }


def sign_experiment(*, method: Any,
                    derived: Mapping[str, Any] | None = None,
                    code_path: Any = "",
                    code_hash: Any = "",
                    certificate: Mapping[str, Any] | None = None,
                    search_bound: Mapping[str, Any] | None = None,
                    experiment_id: Any = "") -> dict[str, Any]:
    """写侧：把签名与（可能的）proof 升档算成"这一行该怎么登记"。

    返回 `{}` 表示"这一档不归本模块管"（`formal`：证据由检查器说，调用方原样登记）。
    否则返回 `{"evidence_kind", "observations"}`：

    - `evidence_kind`：穷尽证据齐备、结论是 `supports`、且 ②③ 的落盘读数也在
      （`exhaustionreport.landing_problems` 空清单）⇒ `proof`；否则保留推导侧给的等级
      （典型是 `cross_check`）。业主 2026-10-23 晚：「E 没给 ②③ ⇒ B 不许把这条登记成
      proof（只能『有数值实验支持』）」—— 所以落盘核查这一关在签名这一刻就问，
      不留到 B 那一侧才发现。
    - `observations`：在既有读数之上加一格 :data:`SIGNATURE_KEY` —— 签名主体、
      ②③ 的作者、证明理由、三段式证明栏原文、脚本哈希、以及"缺什么"。
      签名落在这里而不是新加一列：`observations` 是"这一次到底算了什么"的机器可读格。
    """
    if not is_calculation(method):
        return {}
    facts = _as_mapping(derived)
    obs = _as_mapping(facts.get("observations"))
    verdict = exhaustion_verdict(method=method, observations=obs,
                                 certificate=certificate, search_bound=search_bound,
                                 code_path=code_path, result=facts.get("result"))
    problems = list(verdict["problems"])
    kind = "proof" if verdict["exhaustive"] else str(
        facts.get("evidence_kind") or SUPPORTED_ONLY_KIND)
    composed = verdict["proof_text"]
    if verdict["exhaustive"]:
        # ②③ 落盘核查（`exhaustionreport` 那一侧是唯一实现）：空清单才算齐。
        provisional = {"experiment_id": str(experiment_id or ""),
                       "method": str(method), "evidence_kind": "proof",
                       "observations": obs}
        report = report_problems(provisional)
        if report:
            problems.extend(report)
            kind = str(facts.get("evidence_kind") or SUPPORTED_ONLY_KIND)
            composed = ""
    signature = {
        "signed_by": verdict["signed_by"],
        PROOF_AUTHORS_KEY: list(verdict["proof_authors"]),
        "method": str(method),
        "evidence_kind": ("proof" if kind == "proof" else SUPPORTED_ONLY_KIND),
        "proof_reason": (verdict["proof_reason"] if kind == "proof" else ""),
        "script_path": verdict["script_path"],
        "script_sha256": str(code_hash or ""),
        "design": verdict["design"],
        "enumeration": verdict["enumeration"],
        "proof_text": composed,
        "search_space": verdict["search_space"],
        "problems": problems,
    }
    out_obs = dict(obs)
    out_obs[SIGNATURE_KEY] = signature
    return {"evidence_kind": kind, "observations": out_obs}


def signature_of(experiment: Mapping[str, Any] | None) -> dict[str, Any]:
    """读一行实验上的 E 签名（没有就 `{}`；不猜、不补）。"""
    row = _as_mapping(experiment)
    obs = _as_mapping(row.get("observations"))
    return _as_mapping(obs.get(SIGNATURE_KEY))


def is_signed_exhaustion(experiment: Mapping[str, Any] | None) -> bool:
    """这一行实验是不是"V 签下、E 写 ②③ 的那份穷举证明"。

    四条同时成立（业主 2026-10-23 晚：`signed_by="V"`、`proof_authors` 含 `"E"`）：
    方法属于计算类、`evidence_kind="proof"`、签名主体是 V、②③ 的作者里有 E、
    证明理由在受控词表里且是 exhaustion。
    缺一条都不算 —— 宁可读成"没有这份证据"，也不许把一条只是"数值支持"的行读成证明。
    `signed_by="E"` 的行在这里是 False（那是改口径之前的那一版，判据 ⑦ 明确拒它）。
    """
    row = _as_mapping(experiment)
    if not is_calculation(row.get("method")):
        return False
    if str(row.get("evidence_kind") or "") != "proof":
        return False
    sig = signature_of(row)
    if str(sig.get("signed_by") or "") != PROOF_SIGNER:
        return False
    authors = sig.get(PROOF_AUTHORS_KEY)
    if not isinstance(authors, (list, tuple)) or NUMERIC_AUTHOR not in [str(a) for a in authors]:
        return False
    return str(sig.get("proof_reason") or "") in PROOF_REASONS


def proof_column(experiment: Mapping[str, Any]) -> str:
    """这一行实验进"定理证明库"时，证明栏该写什么：E 写的那份三段式证明栏。

    老行（签名里没有 `proof_text`）退回第 ① 段（程序路径）—— 那一档在业主 2026-10-23
    晚的口径下不够 proof，读侧据此判"缺 ②③"。
    """
    row = _as_mapping(experiment)
    sig = signature_of(row)
    composed = str(sig.get("proof_text") or "").strip()
    if composed:
        return composed
    return str(sig.get("script_path") or row.get("code_path") or "").strip().replace("\\", "/")


def signed_exhaustion_experiments(experiments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """台账里所有"E 按穷举签下的 proof"行（审计与入库闸共用这一份筛选）。"""
    return [dict(r) for r in (experiments or ()) if isinstance(r, Mapping) and is_signed_exhaustion(r)]


def norm_rel(path: Any) -> str:
    """相对路径的归一（`\\` → `/`，去掉前导 `./`）；比较两个路径一律走它。"""
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def find_signed_exhaustion(experiments: Sequence[Mapping[str, Any]],
                           script_path: Any) -> dict[str, Any] | None:
    """按程序路径找那一条 E 签的穷举证明（找不到 ⇒ `None`，不是"随便找一条"）。"""
    want = norm_rel(script_path)
    if not want:
        return None
    for row in signed_exhaustion_experiments(experiments):
        if norm_rel(proof_column_script(proof_column(row))) == want \
                or norm_rel(row.get("code_path")) == want:
            return row
    return None


def find_signed_exhaustion_for_column(experiments: Sequence[Mapping[str, Any]],
                                      proof_text: Any) -> dict[str, Any] | None:
    """按"B 交来的那份证明栏"找 E 的签名：先认第 ① 段的程序路径，再认整份逐字相同。"""
    raw = str(proof_text or "").strip()
    if not raw:
        return None
    for row in signed_exhaustion_experiments(experiments):
        if norm_rel(norm_text(proof_column(row))) == norm_rel(norm_text(raw)):
            return row
    return find_signed_exhaustion(experiments, proof_column_script(raw))


def norm_text(text: Any) -> str:
    """多行文本的归一：统一换行、去掉每行行尾空白与首尾空行（只用于"是不是同一份"）。"""
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def report_problems(experiment_row: Mapping[str, Any] | None) -> list[str]:
    """②③ 的落盘核查：交给 `exhaustionreport`（那一侧是唯一实现，本模块不抄第二份）。

    业主 2026-10-23 晚的口径把 ②③ 的载体落成"一份可核的读数"（`exhaustionreport`
    那一侧判它在不在盘上、与实验行对不对得上）。本模块只做一次转发：

    - 那一侧还没落地（import 失败）⇒ 返回空清单，并用 :func:`report_check_available`
      把"这一格没查成"如实暴露出去（不许把"没查成"读成"查过了没问题"）；
    - 那一侧在、但它自己抛了 ⇒ 返回一条"没查成"的问题（同样是如实，不吞）；
    - 正常 ⇒ 原样返回它的问题清单（空 = 齐了）。
    """
    try:
        from . import exhaustionreport as _ER
    except Exception as exc:  # noqa: BLE001 —— 那一侧可能还没落地（并发开发期）
        # 2026-10-23：这里原来是 fail-open（返回空清单 = 没问题），而「没查成」与
        # 「查过了没问题」是两件事 —— 导入失败就等于这一格没查，必须如实报出来，
        # 否则一条 ②③ 根本没落盘的实验会被当成「齐了」。空清单只留给真查过且齐了。
        return [f"②③ 的落盘核查没查成（exhaustionreport 不可导入：{type(exc).__name__}: {exc}）"]
    try:
        return [str(p) for p in (_ER.landing_problems(_as_mapping(experiment_row)) or [])]
    except Exception as exc:  # noqa: BLE001 —— 判据自己坏了也是"没查成"
        return [f"②③ 的落盘核查没查成（exhaustionreport 抛了 {type(exc).__name__}: {exc}）"]


def report_check_available() -> bool:
    """`exhaustionreport` 那一侧在不在（"这一格查得了吗"，与"查过了没问题"分开）。"""
    try:
        from . import exhaustionreport as _ER  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def find_exhaustion_record(experiments: Sequence[Mapping[str, Any]],
                           proof_text: Any) -> dict[str, Any] | None:
    """按证明栏找那条"穷举 proof"记录 —— 不管它签名对不对（为了给出准确的拒信）。

    与 :func:`find_signed_exhaustion_for_column` 的分工：那个只回"签名合格的"，
    这个回"是这一条，但签名可能不合格" —— 两者都只在它们的射程里回答，
    拒信因此能说清是"没有这条记录"还是"有记录但签名不对"（两种欠账的处置不同）。
    """
    raw = str(proof_text or "").strip()
    if not raw:
        return None
    want_text = norm_text(raw)
    want_script = norm_rel(proof_column_script(raw))
    for row in (experiments or ()):
        if not isinstance(row, Mapping) or not is_calculation(row.get("method")):
            continue
        if str(row.get("evidence_kind") or "") != "proof":
            continue
        column = proof_column(row)
        if norm_text(column) == want_text:
            return dict(row)
        if want_script and norm_rel(proof_column_script(column)) == want_script:
            return dict(row)
    return None


# ---------------------------------------------------------------- 第三方签字（V 的会审）

#: 第三方签字那一档的"签住了"取值（词表真身是 `verifications.VERDICTS` 的最后一档）。
THIRD_PARTY_VERDICT_OK = "成立"


def latest_third_party_sign(root: Any, *, proof_text: Any = "",
                            statement_id: str = "") -> dict[str, Any]:
    """读 `verifications/<命题号>.jsonl`，取「盖住这一份证明栏的最近一签」。

    为什么需要这一格（业主 2026-10-23 晚「签字仍然由 V 签」的落地）：改前 B 的入库闸读的是
    `experiments.observations.e_signature.signed_by` —— 那是 E 自己在 `build_experiment` 里
    盖的章。实测：真穷举实验跑完、`verifications/` 目录根本不存在，B 仍然登记成功，落成
    `kind=theorem` / `evidence_kind=proof` / `bits.reviewed=False`。也就是说"谁签的"这一格
    从头到尾只有一个人（E）说过话，而"第三方"这三个字没有任何东西核过。

    读法与 `agent_c.proof_chain._verified_ok` 同一口径（那个函数是"V 的台账里有没有成立"
    的既有读法）：台账是 `<工作区>/verifications/<命题号>.jsonl`，一行一次审校、追加式，
    所以最后一行就是最近一签。这里只多做两件事那个函数不做的事：

    1. 取「最近一签」（同一份正文被签过两次时以最后一次为准：先成立、后改判有毛病的那一份
       不能被早先那一签救活）；
    2. 那一签的 `proof_sha256` 必须与这一份证明正文「对得上」（`verifications.proof_sha`
       的口径；sha 不符 = 签的是别的正文 / 改稿前的旧版，一律不算）。

    按命题号读、不按"扫全目录找同文"读：`sha 相符` 只回答"这份稿被签过"，而命题这一行的
    第 3 位是按命题记的。扫全目录会让"签在 stmt:000000 上的那一签"给 stmt:000001
    借光（业主 2026-10-23 晚的坑：`kind=theorem` / `evidence_kind=proof` /
    `bits.reviewed=False` 正是"别人的签顶了这一行"的形态）。

    返回 `{"checked","found","verdict","proof_sha256","ledger","why"}`：

    - `checked=False` ⇒ 「没查成」（没给工作区根 / 没给命题号 / 台账读不出来），不是"没有签"；
    - `checked=True, found=False` ⇒ 查过了：台账不在盘上，或最近一签盖的不是这一份正文；
    - `checked=True, found=True` ⇒ `verdict` / `proof_sha256` / `ledger` 是那一签的读数。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "verdict": "",
                           "proof_sha256": "", "ledger": "", "why": ""}
    sid = str(statement_id or "").strip()
    if not sid:
        out["why"] = ("没给命题号 ⇒ 不知道读哪一份台账（V 只审在册的命题；"
                      "这一格没查成，不是「没有签」）")
        return out
    if root is None or not str(root).strip():
        out["why"] = ("没给工作区根 ⇒ `verifications/` 无从读起（这一格没查成，"
                      "不是「没有签」）")
        return out
    try:
        from . import verifications as _VR   # 惰性：目录名 / sha / 台账写法的唯一口径
    except Exception as exc:  # noqa: BLE001 —— 那一侧读不到就是"没查成"
        out["why"] = f"verifications 模块读不到（{type(exc).__name__}: {exc}）"
        return out
    text = str(proof_text or "")
    if not text.strip():
        out["why"] = "证明栏是空的 ⇒ 没有可签的对象"
        return out
    # 两种写法都认：原样那一份，以及去掉行尾空白/首尾空行之后的同一份（签的人可能
    # 贴的是归一化过的那一份）。两个 sha 之外的一律不算 —— 宽松会让改稿后的旧签生效。
    want = {_VR.proof_sha(text)}
    relaxed = norm_text(text)
    if relaxed != text:
        want.add(_VR.proof_sha(relaxed))
    path = Path(root) / _VR.VERIFICATIONS_DIR / f"{sid}.jsonl"
    if not path.is_file():
        out.update(checked=True,
                   why=(f"`{_VR.VERIFICATIONS_DIR}/{sid}.jsonl` 不在盘上 ⇒ "
                        "这一条命题一次审校都没有（V 没审过它）"))
        return out
    try:
        sign = None
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            # 最近一签 = 最后一行；这里只留下"最近"这一份的读数（不做"任一成立即算"）。
            sign = (lineno, row)
    except Exception as exc:  # noqa: BLE001 —— 读不动/坏行 ⇒ 没查成
        out["why"] = (f"台账 {sid}.jsonl 读不出来（{type(exc).__name__}: {exc}）⇒ "
                      "这一格没查成，不许当成签过、也不许当成没签过")
        return out
    out["checked"] = True
    if sign is None:
        out["why"] = f"`{_VR.VERIFICATIONS_DIR}/{sid}.jsonl` 是空台账（一行都没有）"
        return out
    lineno, last = sign
    out.update(found=str(last.get("proof_sha256") or "") in want,
               verdict=str(last.get("verdict") or ""),
               proof_sha256=str(last.get("proof_sha256") or ""),
               ledger=f"{_VR.VERIFICATIONS_DIR}/{sid}.jsonl#"
                      f"{last.get('verification_id') or f'line{lineno}'}")
    if out["found"]:
        out["why"] = (f"{out['ledger']} 是最近一签，verdict={out['verdict']!r}、"
                      "`proof_sha256` 与这一份证明栏相符")
    else:
        out["why"] = (f"{out['ledger']} 是最近一签（verdict={out['verdict']!r}），"
                      "而它的 `proof_sha256` 与这一份证明栏对不上 —— 签的是改稿前的旧版"
                      "或别的正文")
    return out


def third_party_problems(proof_text: Any, *, root: Any = None,
                         statement_id: str = "") -> list[str]:
    """这一份证明栏有没有第三方（V）的会审签名 —— 空清单 = 有，且最近一签是「成立」。

    三态（业主 2026-10-23 晚的口径，与 `verifications` 的三态纪律同向）：
    - 没查成（没给根 / 没给命题号 / 台账读不出来）⇒ 拒（不许折成"通过"）；
    - 没有签（台账不在盘上）⇒ 拒，点名"缺 V 的会审签名"；
    - 最近一签不是「成立」⇒ 拒，把那一签的 `verdict` 与台账行写进拒信；
    - 最近一签「成立」且 sha 对得上 ⇒ 空清单（这一条才够 proof）。
    """
    sig = latest_third_party_sign(root, proof_text=proof_text, statement_id=statement_id)
    if not sig["checked"]:
        return [f"缺 V 的会审签名：这一格没查成 —— {sig['why']}。"
                "没查成不是「签过」，所以这一条拿不到 proof"]
    if not sig["found"]:
        return ["缺 V 的会审签名：" + str(sig["why"]) +
                "。业主 2026-10-23 晚：「签字仍然由 V 签（不是 E）」—— "
                "E 的 `observations.e_signature` 是 E 自己盖的章，它不构成第三方签字；"
                "这一条要 proof，先让 V 会审这一份证明栏（产物就是 "
                "`verifications/<命题号>.jsonl` 的那一行），签「成立」之后再来登记；"
                f"补不齐就最多是 {SUPPORTED_ONLY_KIND}（{SUPPORTED_ONLY_LABEL}）"]
    if str(sig["verdict"]) != THIRD_PARTY_VERDICT_OK:
        return [f"缺 V 的会审签名：V 对这份证明栏的最近一签是 verdict={sig['verdict']!r}"
                f"（{sig['ledger']}）⇒ 那一签没有签住它，这一条不许 proof。"
                "改完证明栏要重新送审（新的一签盖住新的正文），"
                f"在那之前这一条最多是 {SUPPORTED_ONLY_KIND}（{SUPPORTED_ONLY_LABEL}）"]
    return []


def statement_id_for_body(statements: Sequence[Mapping[str, Any]],
                          statement_full: Any) -> str:
    """在册的同一条命题的号（正文归一后逐字比；认不出 ⇒ 空串，不猜一个号）。

    为什么要按正文认号：B 在写库之前手上没有号（号是秘书在事务里现发的），而 V 只审在册的
    命题。所以"这一条有没有签"只能问"册上那条同文的命题有没有签" —— 与
    `register_statement._v_signature_for` 同一个认法（那边也走 `textutil.normalize` +
    `statementbody.body_of`）。没有同文行 ⇒ 回空串（调用方据此判"V 没有可审的对象"）。
    """
    key = str(statement_full or "").strip()
    if not key:
        return ""
    try:
        from . import statementbody as _SB
        from . import textutil as _T
    except Exception:  # noqa: BLE001 —— 认不出号就是"没有同文行"，不猜
        return ""
    want = _T.normalize(_SB.body_of({"statement_full": key}))
    if not want:
        return ""
    for row in (statements or ()):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("kind") or "") == "concept":
            continue
        if _T.normalize(_SB.body_of(dict(row))) == want:
            return str(row.get("stmt_id") or "")
    return ""


def filing_problems(*, origin: Any, evidence_kind: Any, proof_text: Any,
                    experiments: Sequence[Mapping[str, Any]] = (),
                    root: Any = None, statements: Sequence[Mapping[str, Any]] = (),
                    statement_full: Any = "") -> list[str]:
    """B 的入库闸：`proof` 这一档不许 B 自签，也不许 B 替 E 写 ②③。

    只拦一种情形：`origin="own_result"` 且 `evidence_kind="proof"` ——
    那是我方结果自称"已证明"，它必须要么指到一条 V 签、E 写 ②③ 的穷举证明
    （且证明栏就是 E 写的那三段、逐字相同），要么指到一条 `method="formal"` +
    `evidence_kind="proof"` 的形式化实验（那是"自证定理经核验后进库"的既有正路）。

    判据（业主 2026-10-23 晚的硬口径）：
    - ⑥ 只有程序路径、没有 ②③ ⇒ 不许 proof（拒信点名缺"程序设计"/"穷举论证"）；
    - ⑦ 签名主体必须是 V、②③ 的作者必须是 E（`proof_authors` 含 E）；
      B 自称作者 / 改写 E 的读数 / 签名写成 `signed_by="E"` ⇒ 受控拒绝；
    - ②③ 的落盘核查交给 `exhaustionreport`（那一侧在时；不在时如实记"没查成"）；
    - 第三方签字（`root` / `statements` / `statement_full` 给了才查得了）：按正文认出在册
      的那条命题，读 `verifications/<命题号>.jsonl` 的最近一签，要求 verdict=成立、
      且 `proof_sha256` 与这一份证明栏对得上。E 的 `observations.e_signature` 是 E 自己
      盖的章，它不算第三方；没有在册的同文命题 / 台账里没有那一签 / 最近一签是有毛病 /
      sha 对不上 ⇒ 拒，拒信点名"缺 V 的会审签名"与最近一签的 verdict。缺了这几个参数 ⇒
      这一格没查成 ⇒ 也拒（三态纪律：没查成不许折成通过）；
    - 都没有 ⇒ 最多到 :data:`SUPPORTED_ONLY_KIND`。

    为什么 `external_lit` 不在这条闸的射程内：文献里的定理本来就带着它的证明，
    那一档的凭据是逐字引文（`quote_verified` / V 的逐行走查），不是 E 的一次实验。
    """
    kind = str(evidence_kind or "")
    if kind != "proof" or str(origin or "") != "own_result":
        return []
    text = str(proof_text or "").strip()
    parsed = parse_proof_column(text)
    if parsed["problems"]:
        # ⑥：只有程序路径（或只有其中一段）⇒ 不许 proof，且点名缺哪一块。
        return [
            "这一条的证明栏不够格拿 proof：" + "；".join(parsed["problems"]) +
            "。业主 2026-10-23 晚的硬口径：数值实验定理的证明栏必须由三部分组成 ——"
            "① 程序相对地址（相对仓库）、② 程序设计（要解决什么、按什么结构搜、"
            "为什么覆盖全域）、③ 穷举论证（搜索空间多大、怎么算出、对称性/剪枝、"
            "为什么不漏、边界怎么处理），而且 ②③ 由 E 写、B 只原样登记。"
            f"补齐之前这一条最多是 {SUPPORTED_ONLY_KIND}（{SUPPORTED_ONLY_LABEL}）"
        ]
    found = find_signed_exhaustion_for_column(experiments, text)
    if found is None:
        near = find_exhaustion_record(experiments, text)
        if near is not None:
            sig = signature_of(near)
            authors = [str(a) for a in (sig.get(PROOF_AUTHORS_KEY) or [])]
            if str(sig.get("signed_by") or "") == NUMERIC_AUTHOR:
                # ⑦：签字由 V（业主 2026-10-23 晚的更正）—— 写 signed_by="E" 的那一版不算数。
                return [
                    "这条实验的签名主体写的是 E（signed_by='E'）⇒ 那一版口径已经作废："
                    "签字由 V，E 只是 ②③ 的作者。把签名改成 signed_by='V'、"
                    "proof_authors 含 'E' 之后再来登记"
                ]
            return [
                f"这条实验的签名不齐：signed_by={sig.get('signed_by')!r}、"
                f"{PROOF_AUTHORS_KEY}={authors!r} ⇒ 签名主体应是 {PROOF_SIGNER!r}、"
                f"②③ 的作者应含 {NUMERIC_AUTHOR!r}。业主 2026-10-23 晚：程序设计"
                "与穷举论证都由 E 写，签字由 V，B 只原样登记 —— B 自称作者（或替 E 写）"
                "这一条拿不到 proof"
            ]
        return [
            "证明栏是三段式的，但台账里没有与它对应的穷举证明"
            "（experiments 里要有 code_path 指向第 ① 段那份程序、evidence_kind='proof'、"
            "observations.e_signature 里 signed_by='V'、proof_authors 含 'E'、"
            "proof_reason='exhaustion'）⇒ B 不许自签，也不许替 E 把 ②③ 写出来："
            "这条先把实验跑成 proof（E 的 run_experiment，E 给出 ②③），再来原样登记"
        ]
    sig = signature_of(found)
    authors = [str(a) for a in (sig.get(PROOF_AUTHORS_KEY) or [])]
    want_design = str(sig.get("design") or "").strip()
    want_enum = str(sig.get("enumeration") or "").strip()
    if (norm_text(parsed["design"]) != norm_text(want_design)
            or norm_text(parsed["enumeration"]) != norm_text(want_enum)):
        # ⑦ 的另一半：改写成自己的话也算"替 E 写"。
        return [
            "证明栏的 ②③ 与 E 签名里的原文不一致 ⇒ B 不许把 E 的读数改写成自己的话"
            "（业主 2026-10-23 晚：B 只负责原样登记）。"
            "把 E 给的那两段逐字贴回来，或让 E 重出一份"
        ]
    # ②③ 的落盘核查（`exhaustionreport` 那一侧；不在时这一格是"没查成"，不是"通过了"）。
    _report = report_problems(found)
    if _report:
        return ["②③ 的落盘核查没通过：" + "；".join(_report)
                + f"。补齐之前这一条最多是 {SUPPORTED_ONLY_KIND}（{SUPPORTED_ONLY_LABEL}）"]
    # ---- 第三方签字：E 自己盖的章不算（业主 2026-10-23 晚「签字仍然由 V 签」）。
    #
    # 改前这一格只读 `experiments.observations.e_signature.signed_by`，而那串字是 E 在
    # `build_experiment` 里自己写上去的 ⇒ "第三方"两个字没有任何东西核过。实测：真穷举
    # 实验跑完、`verifications/` 目录根本不存在，B 仍然登记成功（kind=theorem、
    # evidence_kind=proof、bits.reviewed=False）。现在必须盘上真有一签：按正文认出在册
    # 的那条命题，读 `verifications/<命题号>.jsonl` 的最近一签，verdict 要成立、
    # `proof_sha256` 要与这一份证明栏对得上（判据本体 `latest_third_party_sign` /
    # `third_party_problems`，读法与 `agent_c.proof_chain._verified_ok` 同一口径）。
    sid = statement_id_for_body(statements, statement_full)
    if not sid:
        return [
            "缺 V 的会审签名：命题台账里没有与这一条同文的在册命题 ⇒ V 没有可审的对象"
            "（它只审在册的命题，`verify_proof` 对不在册的命题直接报 `statement_missing`）。"
            "业主 2026-10-23 晚：「签字仍然由 V 签（不是 E）」—— E 的 "
            "`observations.e_signature` 是 E 自己盖的章，它不构成第三方签字。"
            "正路：① 先按猜想把这一条登记（`kind=\"conjecture\"`，证明栏照交）；"
            "② 请 V 会审这一份证明栏（`verify_proof`，产物就是 "
            "`verifications/<命题号>.jsonl` 那一行）；③ 签「成立」之后把同一份内容再交一次、"
            "kind 改回定理级。补不齐就最多是 "
            f"{SUPPORTED_ONLY_KIND}（{SUPPORTED_ONLY_LABEL}）"
        ]
    return third_party_problems(text, root=root, statement_id=sid)


def verifier_problems(statement: Mapping[str, Any],
                      experiments: Sequence[Mapping[str, Any]] = ()) -> list[str]:
    """V 的逐行走查（`verify.verify_proof`）不覆盖这一条命题的理由（空清单 = 它照旧管）。

    签名主体是 V，但"签字"与"逐行走查"是两件事：这条命题的"证明"是程序
    （证明栏里第 ① 段是脚本路径，或整份就是一行程序路径）⇒ V 没有跑过那份程序，
    所以逐行走查不覆盖它 —— 那一签要说清是"对数值证据的背书"，
    而不能被下游读成"V 逐行审过这份证明了"。
    """
    row = _as_mapping(statement)
    text = str(row.get("proof_text") or "").strip()
    script = proof_column_script(text)
    if not script:
        return []
    found = find_signed_exhaustion_for_column(experiments, text)
    detail = ("台账里有它对应的穷举证明（V 签、②③ 由 E 写）" if found is not None
              else "台账里还没有与它对应的穷举证明（那说明它连 proof 都还不够）")
    return [
        f"这条命题的证明栏是程序 {script!r}（{detail}）⇒ 这是数值证据："
        "签字由 V（业主 2026-10-23 晚），但那是一签对数值证据的背书，"
        "不是 V 的逐行走查 —— V 审的是自然语言证明的每步依据，它没有跑过这份程序，"
        "所以逐行走查这一格对数值证据不适用（也绝不该被读成'V 逐行审过'）"
    ]


# ---------------------------------------------------------------- 形式化那一格（判据 ⑧）

#: "形式化"那一格的两类填法（业主 2026-10-23 晚）：
#:
#: > 「对应的"形式化"那个地方用数值实验程序填；其它正常理论性的定理的形式化栏填 lean 程序」
#:
#: 两者占同一格，填的东西不同；混着填就是"拿另一类定理的证据冒充这一类"。
FORMAL_SLOT_NUMERIC = "numeric_program"
FORMAL_SLOT_LEAN = "lean_program"
FORMAL_SLOT_KINDS: tuple[str, ...] = (FORMAL_SLOT_NUMERIC, FORMAL_SLOT_LEAN)
#: Lean 源码的后缀（理论定理那一格只认它）。
LEAN_SUFFIXES: tuple[str, ...] = (".lean",)


def is_lean_path(path: Any) -> bool:
    """这一串字是不是一份 Lean 源码的相对路径。"""
    text = str(path or "").strip().replace("\\", "/").lower()
    return bool(text) and text.endswith(LEAN_SUFFIXES) and ":" not in text \
        and not text.startswith("/") and ".." not in text.split("/")


def proof_channel(statement: Mapping[str, Any],
                  experiments: Sequence[Mapping[str, Any]] = ()) -> str:
    """这条命题的证明走的是哪一条通道：`"numeric"` / `"formal"` / `""`（没有通道）。

    判据（顺序即口径）：
    1. 证明栏能用 `proof_column_script` 取出程序，且台账里有一条与之对应的穷举证明
       ⇒ `numeric`（数值实验定理）；
    2. 否则证明栏是程序（.lean）且台账里有 `method="formal"` + `evidence_kind="proof"` 的行
       ⇒ `formal`（理论定理的 Lean 程序）；
    3. 都不是 ⇒ 空串（没有这一类证明栏，这一格对它不适用）。
    """
    row = _as_mapping(statement)
    text = str(row.get("proof_text") or "").strip()
    script = proof_column_script(text)
    if script and find_signed_exhaustion_for_column(experiments, text) is not None:
        return "numeric"
    if script and is_lean_path(script):
        return "formal"
    lean_rows = [r for r in (experiments or ()) if isinstance(r, Mapping)
                 and str(r.get("method") or "") == FORMAL_METHOD
                 and str(r.get("evidence_kind") or "") == "proof"
                 and is_lean_path(r.get("code_path") or r.get("proof_location"))]
    if lean_rows and not script:
        return "formal"
    return ""


def formal_slot(statement: Mapping[str, Any],
                experiments: Sequence[Mapping[str, Any]] = (),
                filled: Any = "") -> dict[str, Any]:
    """这条定理的"形式化"那一格：该填什么、现在填的东西对不对（判据 ⑧）。

    业主 2026-10-23 晚把这一格的两类填法说死了：
    数值实验定理 ⇒ 数值实验程序（相对仓库路径）；普通理论定理 ⇒ Lean 程序（`.lean`）。
    两者同一格，所以"填对"的标准不同，而互不冒充只有一条判据能挡：
    填的东西的类别必须与证明通道的类别一致。

    `filled` 是那一格现在填的值（论文对应表的 `lean_file` / 形式化栏；也可以拿
    `statements.proof_text` 的第 ① 段来喂）。返回：

    - `channel`：`"numeric"` / `"formal"` / `""`（这一格对它不适用）；
    - `kind`：这一格应当填哪一类（`FORMAL_SLOT_KINDS` 之一；通道为空时也空）；
    - `path`：这一格应当填的那份程序（通道为空时为空）；
    - `problems`：空清单 = 填对了（或"没填"——三态：没填不是填错）。
    """
    row = _as_mapping(statement)
    channel = proof_channel(row, experiments)
    text = str(row.get("proof_text") or "").strip()
    given = str(filled or "").strip().replace("\\", "/")
    problems: list[str] = []
    if not channel:
        return {"channel": "", "kind": "", "path": "", "problems": [],
                "why": "这条命题没有数值/形式化证明通道 ⇒ 形式化那一格对它不适用"}
    if channel == "numeric":
        path = proof_column_script(text)
        kind = FORMAL_SLOT_NUMERIC
        if given and is_lean_path(given):
            problems.append(
                f"这是数值实验定理（证明栏是程序 {path!r}），而形式化那一格填的是 Lean 程序 "
                f"{given!r} ⇒ 两类定理的填法不许互相冒充：数值定理那一格要填"
                "数值实验程序（相对仓库路径）")
        elif given and norm_rel(given) != norm_rel(path):
            problems.append(
                f"形式化那一格填的 {given!r} 不是证明栏那一份程序（{path!r}）⇒ "
                "同一件事两个地址，读的人不知道验的到底是哪一份")
    else:
        lean = next((str(r.get("code_path") or r.get("proof_location") or "")
                     for r in (experiments or ()) if isinstance(r, Mapping)
                     and str(r.get("method") or "") == FORMAL_METHOD
                     and str(r.get("evidence_kind") or "") == "proof"
                     and is_lean_path(r.get("code_path") or r.get("proof_location"))), "")
        if not lean and is_lean_path(proof_column_script(text)):
            lean = proof_column_script(text)
        kind = FORMAL_SLOT_LEAN
        path = norm_rel(lean)
        if given and not is_lean_path(given):
            problems.append(
                f"这是理论定理（形式化那一格该填 Lean 程序），而填的是 {given!r} ⇒ "
                "两类定理的填法不许互相冒充：理论定理那一格只认 `.lean` 路径"
                "（数值实验程序填进这一格等于拿数值证据冒充形式化核验）")
    return {"channel": channel, "kind": kind, "path": path, "problems": problems}


def formal_slot_kind(statement: Mapping[str, Any],
                     experiments: Sequence[Mapping[str, Any]] = ()) -> str:
    """这一格的应当填法（`numeric_program` / `lean_program` / 空串）—— 读侧一句调用。"""
    return str(formal_slot(statement, experiments).get("kind") or "")
