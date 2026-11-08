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
3. 证明栏（业主 2026-11-08 的口径；改前是"三段式"，见下）：只写 ③ 穷举论证 ——
   搜索空间多大、怎么算出、对称性/剪枝、为什么不漏、边界怎么处理。
   ① 程序相对地址住在 `experiments.code_path`（配 `code_hash`）、② 程序设计住在
   `experiments.observations["design"]`；两格都不许再抄进 `statements.proof_text`。
   业主逐字：「穷举式的 proof_test 应该是填穷举论证，实验栏填相对路径」＋「乙」（=
   ② 程序设计挪进 `observations["design"]`，`proof_text` 只剩 ③）。
   ③ 由 E 写，B 只负责原样登记（不许自己编、也不许把 E 的读数改写成自己的话）。
   落点是 `statements.proof_text` 一份文本、单段标签固定（:func:`compose_proof_column`）：
   这样 `schema.Statement` 不用加字段，而"B 改了一个字"可以由逐段比对抓出来。
   三档仍然分得开：穷举（命题 + 程序 + 穷举论证 + V 签 ⇒ `theorem`）· 普通数值
   （命题 + 数值结果 + 程序，无 V ⇒ `strong_conjecture`）· F 文字证明（+ V ⇒
   `pre_theorem`）。
4. "形式化"那一格（业主 2026-10-23 晚）：数值实验定理填数值实验程序（相对仓库路径），
   普通理论定理填 Lean 程序（`.lean` 路径）—— 两者同一格、填的东西不同，
   不许互相冒充。判据见 :func:`formal_slot`（判据 ⑧）。

## ②③ 只对"想升格成数值证明"的那一条要求（D-43，业主 2026-10-24）

业主原话：「「程序设计思路/穷举论证」只针对想升格成数值证明的数值实验，对一般数值实验
不做要求」。于是"要不要三件套"绑在意图上，不绑在 `method` 上 —— 判据本体是
:func:`wants_numeric_proof`（`method="exhaustive_search"` / 布尔 true 的 `exhaustive` /
调用方声称 `evidence_kind="proof"`，三者任一）。一般数值实验（`numeric` / `cross_check` /
`heuristic`）⇒ 不要求报告、不报 `problems`、不落空文件；已经写了报告的不因缺块扣分。

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

#: "想升格成数值证明"的方法（业主 2026-10-24 的 D-43：「程序设计思路/穷举论证」只针对
#: 想升格成数值证明的数值实验，对一般数值实验不做要求）。
#:
#: 这一格不是"要不要三件套"的全部判据 —— 判据本体在 :func:`wants_numeric_proof`：
#: 方法只是三条入口之一，另外两条是"脚本报了布尔 true 的 exhaustive"与"调用方声称 proof"。
PROOF_INTENT_METHODS: tuple[str, ...] = ("exhaustive_search",)

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

#: 证明栏的那一段（业主 2026-11-08：「穷举式的 proof_test 应该是填穷举论证，
#: 实验栏填相对路径」⇒ 证明栏只剩 ③）。
#:
#: 写成 `标签：正文`（正文可以续行，解析时归到这一段）。
PROOF_PARTS: tuple[tuple[str, str], ...] = (
    ("穷举论证", "enumeration"),
)
#: 段名 → 标签（同一份表派生，不写第二份）。
PART_NAMES: dict[str, str] = {name: label for label, name in PROOF_PARTS}

#: 改前那两段（2026-11-08 之前的三段式证明栏）。它们不再住证明栏：
#: ① 程序 → `experiments.code_path`、② 程序设计 → `experiments.observations["design"]`。
#: 解析器见到这两个标签就算一条 `problems`（"证明栏里还带着旧三段"），于是
#: B 的入库闸不会再把一份旧形态的证明栏当合格的穷举证明 ——— 而不是静默地把它读成
#: ③ 的一部分。
MISPLACED_PROOF_PARTS: tuple[tuple[str, str], ...] = (
    ("程序", "script"),
    ("程序设计", "design"),
)
#: 旧两段的段名（`problems` 与读数按它点名）。
MISPLACED_PART_NAMES: dict[str, str] = {
    name: label for label, name in MISPLACED_PROOF_PARTS}

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


def wants_numeric_proof(*, method: Any = "",
                        observations: Mapping[str, Any] | None = None,
                        certificate: Mapping[str, Any] | None = None,
                        search_bound: Mapping[str, Any] | None = None,
                        evidence_kind: Any = "") -> bool:
    """这一条实验是不是"想升格成数值证明" —— 要不要 ②③ 三件套的唯一判据（D-43）。

    业主原话（2026-10-24，唯一权威）：「「程序设计思路/穷举论证」只针对想升格成数值证明的
    数值实验，对一般数值实验不做要求」。

    改前这条要求绑在 `method` 上（凡是计算类都问三件套），真机 r34d `000004`-`000009` 与
    cube2 `000001`/`000002` 于是每条都在喊「报告里缺 ['程序设计思路','穷举论证']」，
    盘上还多出一份"两块正文各 0 字"的报告。现在按意图问，三条入口任一成立才算想升格：

    1. `method="exhaustive_search"`：这一档本身就是奔着穷举证明去的；
    2. `exhaustive` 读到布尔 `true`：读口与优先级与 :func:`exhaustion_problems` 同一份
       （`observations` > `certificate.detail` > `search_bound`）—— "说不清"（缺省 /
       `"true"` / `1`）不算想升格，它连穷尽判定都过不去；
    3. 调用方显式声称 `evidence_kind="proof"`：声称了就是想要那一档，材料得按那一档齐。

    为什么"一般数值实验"不要求：②③ 是"把数值证据升格成证明"要交的材料，不是所有数值
    实验的入场券。一般数值实验（`numeric` / `cross_check` / `heuristic`）该说的是
    "算了什么、在什么范围内算了"，那已经落在 `observations` 与 `search_bound` 里。

    三态纪律：本函数只回答"要不要"，不回答"齐不齐"（后者是
    :func:`report_problems` / `exhaustion_problems` 的事）。已经写了报告的一般数值实验
    ⇒ 本函数给 `False`，于是读侧照常读、不因缺块扣分（报告本身仍由 `exhaustionreport`
    读得出、展示得出）。
    """
    if str(method or "").strip() in PROOF_INTENT_METHODS:
        return True
    if str(evidence_kind or "").strip() == "proof":
        return True
    flag, _where = _exhaustive_reading(_as_mapping(observations),
                                       _as_mapping(certificate),
                                       _as_mapping(search_bound))
    return flag is True


def exhaustion_problems(*, method: Any,
                        observations: Mapping[str, Any] | None = None,
                        certificate: Mapping[str, Any] | None = None,
                        search_bound: Mapping[str, Any] | None = None,
                        code_path: Any = "",
                        result: Any = "supports",
                        evidence_kind: Any = "") -> list[str]:
    """穷尽判定：空清单 = 整个论域被穷尽验证过（够 proof）；非空 = 缺什么，逐条写清。

    要的东西就是业主 2026-10-23 晚点名的三块（2026-11-08 的居所：① 在
    `experiments.code_path`、② 在 `observations["design"]`、③ 在证明栏）：
    ① 程序相对地址（`code_path`）、② 程序设计（`design`）、③ 穷举论证（`enumeration`），
    外加"可核"这件事本身：布尔 true 的 `exhaustive` 与一个说得出范围的搜索空间。

    `evidence_kind` 只是 :func:`wants_numeric_proof` 的第三条入口（调用方显式声称 proof），
    缺省空串表示这一趟没人在喊"我要 proof"。
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
    #
    # D-43（业主 2026-10-24）：「「程序设计思路/穷举论证」只针对想升格成数值证明的数值实验，
    # 对一般数值实验不做要求」⇒ 这一步只对 `wants_numeric_proof` 为真的那一条问。
    # 一般数值实验没有报告不是欠账 —— 改前它对每一条计算类实验都问，于是 numeric/cross_check
    # 的行上也挂着"报告里缺 ②③"，那是把"升格材料"当成了"所有数值实验的入场券"。
    if wants_numeric_proof(method=method, observations=obs, certificate=cert,
                           search_bound=bound, evidence_kind=evidence_kind):
        problems.extend(report_problems({"method": str(method or ""),
                                         "observations": obs,
                                         "certificate": cert,
                                         "search_bound": bound,
                                         "evidence_kind": str(evidence_kind or "")}))
    return problems


def compose_proof_column(*, enumeration: Any) -> str:
    """把证明栏那一整段拼成一份可解析的文本（E 写，B 原样登记）。

    形态（标签逐字）::

        穷举论证：搜索空间多大、怎么算出、对称性/剪枝、为什么不漏、边界怎么处理

    ## 为什么只剩一段（业主 2026-11-08，唯一权威）

    「穷举式的 proof_test 应该是填穷举论证，实验栏填相对路径」；② 程序设计按「乙」挪进
    `experiments.observations["design"]`。所以：① 程序路径住 `experiments.code_path`、
    ② 程序设计住 `observations["design"]`，两者都不许再抄进证明栏 —— 证明栏只有 ③。

    为什么仍是"一段文本"而不是加字段：`statements` 的"证明"栏只有 `proof_text` 一栏，
    加字段要走人裁（schema 是禁改区）。单段 + 标签固定 ⇒ 既不加字段，又能被
    :func:`parse_proof_column` 逐字核（B 改一个字就对不上 E 的签名）。
    """
    return "\n".join(
        f"{label}：{str(value or '').strip()}"
        for label, value in (("穷举论证", enumeration),))


def parse_proof_column(text: Any, *, code_path: Any = "") -> dict[str, Any]:
    """把证明栏拆开：`{"script","design","enumeration","problems","raw","numeric"}`。

    ## 新口径（2026-11-08）：单段（穷举论证）+ 实验行的 `code_path` 非空

    判据（业主那两句裁定）：
    - 证明栏里必须有 ③「穷举论证」那一段；
    - 程序路径不在证明栏里，在 `experiments.code_path` 那一格 —— 调用方把那一格的值
      当 `code_path` 传进来，本函数用 `is_script_path` 核它；
    - 证明栏里若还带着旧两段（`程序：` / `程序设计：`）⇒ 记一条 `problems`：那是改前
      形态，程序该在 `code_path`、设计该在 `observations["design"]`，不许拿它冒充新形态。

    `script` / `design` 两格仍返回，但只从参数 / 旧标签读：新文本下 `design` 恒为空，
    `script` 恒等于传入的 `code_path`（合法时）。认不出的段一律 `""` —— 宁可判"缺这一段"，
    也不许把一句散文读成程序地址。
    """
    raw = str(text or "")
    parts: dict[str, str] = {name: "" for _label, name in PROOF_PARTS}
    current = ""
    misplaced: list[str] = []
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
            continue
        stray = ""
        for label, name in MISPLACED_PROOF_PARTS:
            if stripped.startswith(f"{label}：") or stripped.startswith(f"{label}:"):
                stray = name
                break
        if stray:
            # 旧两段不再属于证明栏：整行丢掉、记一条问题（不许把它续进 ③ 的正文里）。
            if stray not in misplaced:
                misplaced.append(stray)
            current = ""
            continue
        if current:
            parts[current] = (parts[current] + "\n" + stripped).strip()
    script = str(code_path or "").strip().replace("\\", "/")
    problems: list[str] = []
    if misplaced:
        shown = "、".join(f"「{MISPLACED_PART_NAMES[name]}」" for name in misplaced)
        problems.append(
            f"证明栏里还带着旧形态的 {shown} 段：按 2026-11-08 的口径，证明栏只写"
            "「穷举论证」，程序路径在 experiments.code_path、程序设计在 "
            "observations['design'] —— 把这两段从证明栏里删掉，别拿旧形态冒充新形态")
    if not parts["enumeration"]:
        problems.append(
            "缺穷举论证（③：搜索空间多大、怎么算出、对称性/剪枝、"
            "为什么不漏、边界怎么处理）")
    if not is_script_path(script):
        problems.append(
            f"缺程序路径（code_path）：读到 {code_path!r} —— 穷举证明的签名就是那份程序，"
            "它住在 experiments.code_path（含后缀，不含盘符与 `..`），不在证明栏里")
    return {**parts, "script": script if is_script_path(script) else "",
            #: ② 程序设计不在证明栏里（住 `observations["design"]`）：这一格恒空，
            #: 保留它只为读侧形状不变（旧调用方读 `parsed["design"]` 不会 KeyError）。
            "design": "",
            "problems": problems, "raw": raw,
            #: 这一份文本是不是"数值证据的证明栏"（单段标签在；旧三段也算，读侧要认得出
            #: 它归数值那一档，见 `verifier_problems`）。散文证明 ⇒ False。
            "numeric": bool(parts["enumeration"] or misplaced)}


def proof_column_script(text: Any) -> str:
    """从旧形态的证明栏里取出程序路径（认不出 ⇒ 空串）。

    只用于读历史数据（改前 `程序：` 那一段，或整份就是一行程序路径）：2026-11-08 之后
    程序路径住在 `experiments.code_path`，新证明栏里没有它。读侧判"这条命题是不是数值
    证据"应看 :func:`parse_proof_column` 的 `numeric` 那格，而不是本函数。
    """
    parsed = parse_proof_column(text)
    if parsed["script"] and is_script_path(parsed["script"]):
        return str(parsed["script"]).strip().replace("\\", "/")
    raw = str(text or "").strip().replace("\\", "/")
    if is_script_path(raw):
        return raw
    for line in str(text or "").splitlines():
        stripped = line.strip()
        for label, _name in MISPLACED_PROOF_PARTS:
            if stripped.startswith(f"{label}：") or stripped.startswith(f"{label}:"):
                value = stripped[len(label) + 1:].strip().replace("\\", "/")
                if is_script_path(value):
                    return value
    return ""


# ---------------------------------------------------------------- 穷举上界 vs 枚举量（只报不判）

#: "枚举了多少例"的候选键（按优先级；脚本自报时常见的那几种写法）。
CASE_COUNT_KEYS: tuple[str, ...] = ("n_cases", "cases", "enumerated_total", "n_enumerated")

#: 上界与枚举量比对的三档读数。它不是判据：`mismatch` 只让读数可见，不改任何档。
BOUND_CHECK_VERDICTS: tuple[str, ...] = ("consistent", "mismatch", "no_bound")


def _case_count_of(*maps: Mapping[str, Any]) -> int | None:
    """从三处读"枚举了多少例"（读到第一个正整数就停；没读到 ⇒ `None`）。"""
    for mapping in maps:
        for key in CASE_COUNT_KEYS:
            value = mapping.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value > 0:
                return value
            if isinstance(value, str) and value.strip().isdigit():
                got = int(value.strip())
                if got > 0:
                    return got
    return None


def _bound_dimensions(space: Mapping[str, Any]) -> tuple[int | None, list[str]]:
    """搜索空间的"各维乘积"：只认 `[lo, hi]` 形态的整数区间。

    为什么只认区间、不认裸整数：真机行（`projects/mp3-r4` 的 `000000`）里
    `search_bound` 长这样 —— `{"N_range": [2, 8], "D_range": [2, 10], "cells": 63,
    "max_dim_A": 43758, "per_cell_exhaustive": "…"}`。两个区间的长度乘积 7 × 9 = 63
    正好等于它自报的 `cells`，而 `max_dim_A` 是某一格里的派生量，把它乘进去
    会把界放大 43758 倍。所以裸整数一律不参与乘积（它们多半已经是算过的计数），
    认不出任何一个区间 ⇒ `(None, [])`。
    """
    dims: dict[str, int] = {}
    for key, value in space.items():
        if isinstance(value, (list, tuple)) and len(value) == 2:
            lo, hi = value
            if isinstance(lo, bool) or isinstance(hi, bool):
                continue
            if isinstance(lo, int) and isinstance(hi, int) and hi >= lo >= 0:
                dims[str(key)] = hi - lo + 1
    if not dims:
        return None, []
    total = 1
    for size in dims.values():
        total *= size
    return total, sorted(dims)


def bound_check(*, observations: Mapping[str, Any] | None = None,
                certificate: Mapping[str, Any] | None = None,
                search_bound: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """穷举上界与枚举量的比对读数 —— 三档 `consistent` / `mismatch` / `no_bound`。

    只报不判（2026-10-27 业主裁定）：`mismatch` 不进 `problems`、不改 `evidence_kind`、
    不挡任何签字。理由：这一族从来没有任何判据把"界"与"跑了多少例"对起来过
    （`exhaustion_problems` 只问界"有没有"、`landing_problems` 只核报告字节与三块字数），
    先把它变成可见的读数，观察一批之后再决定要不要升级成判据。

    三档的语义：
    - `consistent`：枚举量 ≥ 各维乘积（"在 B 内没有反例"至少覆盖了声称的 B）；
    - `mismatch`：枚举量 < 各维乘积（声称穷尽了 B，实际只跑了一部分）；
    - `no_bound`：至少一端算不出来 —— `missing` 说清是哪一端（没有区间形态的界 /
      没有 `n_cases`）。这一档不是"一致"，也不是"不一致"。
    """
    obs = _as_mapping(observations)
    cert = _as_mapping(certificate)
    bound = _as_mapping(search_bound)
    detail = _as_mapping(cert.get("detail"))
    out: dict[str, Any] = {
        "verdict": "no_bound", "cases": None, "bound_cases": None,
        "dimensions": [], "missing": [], "why": "",
    }
    cases = _case_count_of(obs, detail, bound)
    space, _where = _space_reading(obs, cert, bound)
    bound_cases, dims = _bound_dimensions(_as_mapping(space))
    out.update(cases=cases, bound_cases=bound_cases, dimensions=dims)
    missing: list[str] = []
    if cases is None:
        missing.append("n_cases")
    if bound_cases is None:
        missing.append("search_bound")
    out["missing"] = missing
    if missing:
        out["why"] = ("无从比对（缺 " + "、".join(missing) + "）："
                      + ("没有 `" + "/".join(CASE_COUNT_KEYS) + "` 这一格" if cases is None else "")
                      + ("；" if cases is None and bound_cases is None else "")
                      + ("界里没有 `[lo, hi]` 形态的整数区间" if bound_cases is None else "")
                      + "。这一档是'判不了'，不是'一致'，也不是'不一致'")
        return out
    if cases >= bound_cases:
        out["verdict"] = "consistent"
        out["why"] = (f"枚举 {cases} 例 ≥ 界 {bound_cases} 例"
                      f"（各维 {'×'.join(str(k) for k in dims)}）⇒ 至少覆盖了声称的 B")
    else:
        out["verdict"] = "mismatch"
        out["why"] = (f"枚举 {cases} 例 < 界 {bound_cases} 例"
                      f"（各维 {'×'.join(str(k) for k in dims)}）⇒ 声称穷尽了 B，"
                      "实际只跑了一部分（只报不判）")
    return out


def exhaustion_verdict(*, method: Any,
                       observations: Mapping[str, Any] | None = None,
                       certificate: Mapping[str, Any] | None = None,
                       search_bound: Mapping[str, Any] | None = None,
                       code_path: Any = "",
                       result: Any = "supports",
                       evidence_kind: Any = "") -> dict[str, Any]:
    """一次计算类实验的穷尽判定读数（写侧、B 的入库闸、审计三处共用这一份）。

    返回的 `evidence_kind` 只有两个取值：够 proof（且签名者 E、理由 exhaustion），
    或者 :data:`SUPPORTED_ONLY_KIND`（"有数值实验支持"，不构成证明）。

    `evidence_kind` 形参是调用方"这一条想登记成什么"的声称（传给
    :func:`wants_numeric_proof` 的第三条入口），不是本函数要返回的那一格。
    """
    problems = exhaustion_problems(method=method, observations=observations,
                                   certificate=certificate, search_bound=search_bound,
                                   code_path=code_path, result=result,
                                   evidence_kind=evidence_kind)
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
        # 证明栏：穷举论证那一段（2026-11-08）；不够时留空（不许拿它冒充证据）。
        "script_path": script if enough else "",
        "design": design,
        "enumeration": enumeration,
        "proof_text": (compose_proof_column(enumeration=enumeration) if enough else ""),
        "coverage_where": enum_where,
        "design_where": design_where,
        "search_space": space,
        "search_space_where": space_where,
        #: 穷举上界与枚举量的比对读数（2026-10-27，`bound_check`）：只报不判 ——
        #: 它不出现在 `problems` 里，也不改 `evidence_kind`。这一族此前没有任何判据
        #: 把"界"与"跑了多少例"对起来过，先让它可见。
        "bound_check": bound_check(observations=obs, certificate=cert, search_bound=bound),
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
      穷举论证的作者、证明理由、证明栏原文（2026-11-08 起只有 ③）、脚本哈希、
      以及"缺什么"。签名落在这里而不是新加一列：`observations` 是"这一次到底算了什么"
      的机器可读格。
    """
    if not is_calculation(method):
        return {}
    facts = _as_mapping(derived)
    obs = _as_mapping(facts.get("observations"))
    verdict = exhaustion_verdict(method=method, observations=obs,
                                 certificate=certificate, search_bound=search_bound,
                                 code_path=code_path, result=facts.get("result"),
                                 # 调用方显式声称 proof 也是"想升格"的入口（D-43）：
                                 # 声称了就是想要那一档，三件套得按那一档问。
                                 evidence_kind=facts.get("evidence_kind"))
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
        #: 上界 ↔ 枚举量的比对读数（2026-10-27）：随签名落在行上，只报不判。
        #: 为什么放进签名而不是新加一列：`observations` 是"这一次到底算了什么"的
        #: 机器可读格（同 `SIGNATURE_KEY` 的理由），加列要走人裁（`schema` 是禁改区）。
        "bound_check": dict(verdict.get("bound_check") or {}),
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
    """这一行实验进"定理证明库"时，证明栏该写什么：E 写的那份「穷举论证」。

    老行（签名里没有 `proof_text`，或签名里还是改前的三段式）原样交回 —— 读侧
    （`parse_proof_column`）会把旧两段记成问题，于是它拿不到 proof 的复核；
    程序路径一律去 `experiments.code_path` 读（`proof_column_script` 只认旧形态）。
    """
    row = _as_mapping(experiment)
    sig = signature_of(row)
    composed = str(sig.get("proof_text") or "").strip()
    if composed:
        return composed
    return str(sig.get("enumeration") or "").strip()


def signed_exhaustion_experiments(experiments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """台账里所有"E 按穷举签下的 proof"行（审计与入库闸共用这一份筛选）。"""
    return [dict(r) for r in (experiments or ()) if isinstance(r, Mapping) and is_signed_exhaustion(r)]


#: "可疑的自签背书"这一档的读数码（2026-10-27，业主裁定：先报不拦）。
SUSPECT_SELF_SIGNED = "suspect_self_signed"


def suspect_self_signed(experiments: Sequence[Mapping[str, Any]], *, root: Any,
                        statements: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """声称 V 签下了穷举证明、而 `verifications/` 里拿不出那一签的实验行 —— 只报不拦。

    ## 治哪一处（R-EVID ① 的 D4，业主 2026-10-27 裁定"先报不拦"）

    `is_signed_exhaustion` 读的 `signed_by="V"` 是 E 在 `sign_experiment` 里写进去的
    一格自述 —— V 从来没有在这条路径上盖过章。真正的第三方签字在
    `verifications/<命题号>.jsonl`（判据本体 `third_party_problems`）。
    2026-11-03 之后：收工门（`closing._has_t3` 的穷举支路）与 B 的入库闸都改调
    `exhaustion_backing` —— 那一格不再给"V 没真签过"的穷举行背书。本函数仍是读数
    （覆盖全工作区、不只被正文引到的那几条），但它算的是同一份判据，不再另有一套口径。

    为什么不直接删掉/升级成闸：它数的是"全工作区有多少条声称 V 签下"，承重门只判
    "被正文引到的那几条"；两者集合不同（`draft/154` §4.2），保留读数是为了让没被引到的
    那些行也看得见。但它不再和被引到的那几条各说一遍：收工门那一条 finding 会跳过
    已经逐条点名的实验行（`closing._check_load_bearing` 里的去重）。

    返回 `{"checked", "suspects", "total", "why"}`，另有六格读数（2026-11-03，153-U-06 的丙+乙
    ＋ 154 的四结局）：
    `signer_required`（这一签应当由谁签 —— 恒 `"V"`，`signed_by` 只能是它，E 只是 ②③
    的作者）、`e_signature_backed`（本工作区多少条靠 `e_signature` 背书）、
    `third_party_verdicts`（这些行的第三方签名分布：`已签·成立` / `已签·<判决>` / `没签` /
    `签的是旧版` / `没查成`）、`by_project`（本工作区的名字 → 三个计数；跨工作区的合计数
    不在一个 per-workspace 读数里编造）、`states`（`exhaustion_backing` 的四结局逐条计数）、
    `rows`（逐条的 `state` / `report_sha256` / `defect_step` / `ledger` —— 读的人照着它能
    直接翻到那一签）。`checked=False` 是"没查成"（没给工作区根 ⇒ 查不到
    `verifications/`），不是"没有可疑行"。
    """
    rows = [dict(r) for r in (experiments or ()) if isinstance(r, Mapping)]
    out: dict[str, Any] = {"checked": False, "suspects": [], "total": 0, "why": "",
                           "signer_required": str(PROOF_SIGNER),
                           "e_signature_backed": 0,
                           "third_party_verdicts": {}, "by_project": {},
                           # 四结局的逐条分布（2026-11-03，154）：与 `closing._has_t3`
                           # 的穷举支路同一份判据（`exhaustion_backing`）⇒ 这一格的
                           # "会掉多少条"就是承重门那一格会掉多少条。
                           "states": {s: 0 for s in EXHAUSTION_BACKING_STATES},
                           "rows": []}
    if not str(root or "").strip():
        out["why"] = ("没给工作区根 ⇒ 查不到 `verifications/`（这一格没查成，"
                      "不是「没有可疑行」）")
        return out
    out["checked"] = True
    suspects: list[dict[str, Any]] = []
    backed = 0
    verdicts: dict[str, int] = {}
    states: dict[str, int] = {s: 0 for s in EXHAUSTION_BACKING_STATES}
    detail_rows: list[dict[str, Any]] = []
    for row in rows:
        # 只看"声称自己够 proof 的那一档"：`sign_experiment` 给每一条计算类实验都写
        # `signed_by="V"`（那是签字岗位的名字，不是"V 盖过章"），拿它当射程会把
        # 每一条普通数值实验都点成可疑 —— 那是噪音，不是读数。
        if not is_signed_exhaustion(row):
            continue
        backed += 1
        # 判据只有一处：`exhaustion_backing`（收工门的穷举支路调的是同一个函数）。
        # 改前这里自己算一遍 `third_party_problems` ⇒ 同一条行在两个出口上各有各的说法
        # （`draft/144:505` 说的"与 `_has_t3` 认自签直接对立"）。
        got = exhaustion_backing(row, root=root, statements=statements)
        state = str(got.get("state") or EXHAUSTION_BACKING_UNCHECKED)
        states[state] = states.get(state, 0) + 1
        # 那一签的分布（2026-11-03，乙）：这一格要能分辨"V 审过、判了有毛病"与
        # "压根没签"—— 两者的处置完全不同，而 `total` 一个数把这两种折成一样。
        if state in (EXHAUSTION_BACKING_SIGNED, EXHAUSTION_BACKING_DEFECTIVE):
            label = f"已签·{got.get('verdict') or '（判决空）'}"
        elif state == EXHAUSTION_BACKING_STALE:
            label = "签的是旧版"
        elif state == EXHAUSTION_BACKING_UNCHECKED:
            label = "没查成"
        else:
            label = "没签"
        verdicts[label] = verdicts.get(label, 0) + 1
        detail_rows.append({
            "experiment_id": str(row.get("experiment_id") or row.get("id") or ""),
            "state": state,
            "statement_id": str(got.get("statement_id") or ""),
            "report_path": str(got.get("report_path") or ""),
            "report_sha256": str(got.get("report_sha256") or ""),
            "verdict": str(got.get("verdict") or ""),
            "defect_step": got.get("defect_step"),
            "ledger": str(got.get("ledger") or ""),
        })
        if state == EXHAUSTION_BACKING_SIGNED:
            continue
        suspects.append({
            "experiment_id": str(row.get("experiment_id") or row.get("id") or ""),
            "code": SUSPECT_SELF_SIGNED,
            "statement_id": str(got.get("statement_id") or ""),
            "method": str(row.get("method") or ""),
            "signed_by": str(signature_of(row).get("signed_by") or ""),
            "state": state,
            "defect_step": got.get("defect_step"),
            "why": str(got.get("why") or ""),
        })
    out["suspects"] = suspects
    out["total"] = len(suspects)
    out["e_signature_backed"] = backed
    out["third_party_verdicts"] = verdicts
    out["states"] = states
    out["rows"] = detail_rows
    out["by_project"] = {
        str(root).replace("\\", "/").rstrip("/").split("/")[-1]: {
            "e_signature_backed": backed,
            "would_drop_load_bearing": len(suspects),
            "third_party_signed": states.get(EXHAUSTION_BACKING_SIGNED, 0),
        }
    }
    out["why"] = (f"台账 {len(rows)} 条实验行里有 {len(suspects)} 条声称穷举证明已由 V 签下，"
                  "而 `verifications/` 里拿不出对应的第三方签字行（只报不拦；逐条理由见 "
                  "`rows` 的 `state`）")
    return out


def norm_rel(path: Any) -> str:
    """相对路径的归一（`\\` → `/`，去掉前导 `./`）；比较两个路径一律走它。"""
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def find_signed_exhaustion(experiments: Sequence[Mapping[str, Any]],
                           script_path: Any) -> dict[str, Any] | None:
    """按程序路径找那一条 E 签的穷举证明（找不到 ⇒ `None`，不是"随便找一条"）。

    认法两条（2026-11-08 之后 `code_path` 是程序路径的唯一居所，旧行才看证明栏）：
    ① `experiments.code_path` 与它相同；② 旧形态的证明栏里 `程序：` 那一段与它相同。
    """
    want = norm_rel(script_path)
    if not want:
        return None
    for row in signed_exhaustion_experiments(experiments):
        if norm_rel(row.get("code_path")) == want:
            return row
        if norm_rel(proof_column_script(proof_column(row))) == want:
            return row
    return None


def find_signed_exhaustion_for_column(experiments: Sequence[Mapping[str, Any]],
                                      proof_text: Any, *,
                                      code_path: Any = "",
                                      experiment_id: Any = "") -> dict[str, Any] | None:
    """按"B 交来的那份证明栏"找 E 的签名：按实验号 / `code_path` 认，不再只按文本。

    2026-11-08（业主：「穷举式的 proof_test 应该是填穷举论证，实验栏填相对路径」）：
    证明栏里只剩 ③，程序路径搬去了 `experiments.code_path`。于是"这份证明栏对应哪条
    实验"的认法按优先级是：

    ① `experiment_id`（调用方从 `reports/e-proof-<实验号>.md` 那个名字读出来的号）——
       唯一不会歧义的一格；
    ② ③ 那一段的正文与实验行 `observations.enumeration` 逐字相同（"这份证明栏就是
       这一条写的"）；
    ③ `code_path`（调用方从实验行读到的程序路径）—— 最后才用它：两条实验可以共用
       同一份程序（"同一脚本、换枚举策略"是常态），只按它认会挑到第一条；
    ④ 旧形态：整份证明栏与旧三段式逐字相同（只读历史数据）。

    认不出 ⇒ `None`（不许"随便找一条"）。
    """
    raw = str(proof_text or "").strip()
    want_text = norm_text(raw)
    want_script = norm_rel(code_path)
    want_id = str(experiment_id or "").strip()
    if not (want_text or want_script or want_id):
        return None
    rows = signed_exhaustion_experiments(experiments)
    # 逐优先级扫整张表（不是逐行比全部条件）：两条实验共用同一份程序时，
    # "先撞到哪条"不能决定答案 —— 先按实验号 / 正文认，最后才退到 code_path。
    if want_id:
        for row in rows:
            if str(row.get("experiment_id") or row.get("id") or "") == want_id:
                return row
    if want_text:
        for row in rows:
            if norm_text(enumeration_of(row)) == want_text:
                return row
        for row in rows:
            if norm_text(proof_column(row)) == want_text:
                return row
    if want_script:
        for row in rows:
            if norm_rel(row.get("code_path")) == want_script:
                return row
        return find_signed_exhaustion(experiments, want_script)
    return None


def enumeration_of(experiment: Mapping[str, Any] | None) -> str:
    """这一行实验的 ③ 穷举论证原文（`observations` > `certificate.detail` > `search_bound`）。

    读口与 :func:`exhaustion_problems` 同一份（`_enumeration_reading`）：证明栏现在只剩
    这一段，所以"这份证明栏是不是这一条实验的"按它认（:func:`find_signed_exhaustion_for_column`）。
    """
    row = _as_mapping(experiment)
    value, _where = _enumeration_reading(
        _as_mapping(row.get("observations")),
        _as_mapping(row.get("certificate")),
        _as_mapping(row.get("search_bound")))
    return str(value or "").strip()


def norm_text(text: Any) -> str:
    """多行文本的归一：统一换行、去掉每行行尾空白与首尾空行（只用于"是不是同一份"）。"""
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def report_problems(experiment_row: Mapping[str, Any] | None) -> list[str]:
    """②③ 的落盘核查：只对"想升格成数值证明"的那一条问（D-43），转发到 `exhaustionreport`。

    业主 2026-10-24（唯一权威）：「「程序设计思路/穷举论证」只针对想升格成数值证明的数值
    实验，对一般数值实验不做要求」。所以这里先问一句 :func:`wants_numeric_proof`：

    - 这一行不是想升格的那一条（`numeric` / `cross_check` / `heuristic`，既没有布尔 true 的
      `exhaustive`、也没有声称 `proof`）⇒ 返回空清单。空清单在这里的意思是"这一格不向它要"，
      与"要了且齐了"同形，但两件事都由这一份判据单点决定，下游不必各记一个条件；
    - 想升格的那一条 ⇒ 转发 `exhaustionreport.landing_problems`（那一侧是唯一实现，
      本模块不抄第二份）：
      - 那一侧还没落地（import 失败）⇒ 返回一条"没查成"（不许把"没查成"读成"查过了没问题"）；
      - 那一侧在、但它自己抛了 ⇒ 返回一条"没查成"（同样是如实，不吞）；
      - 正常 ⇒ 原样返回它的问题清单（空 = 齐了）。

    已经写了报告的一般数值实验 ⇒ 本条返回空清单（不因缺块扣分），但那份报告仍由
    `exhaustionreport.read_report` 照常读得出来、展示得出来（读侧没有因为这次放宽改动）。
    """
    row = _as_mapping(experiment_row)
    if not wants_numeric_proof(method=row.get("method"),
                               observations=row.get("observations"),
                               certificate=row.get("certificate"),
                               search_bound=row.get("search_bound"),
                               evidence_kind=row.get("evidence_kind")):
        return []
    try:
        from . import exhaustionreport as _ER
    except Exception as exc:  # noqa: BLE001 —— 那一侧可能还没落地（并发开发期）
        # 2026-10-23：这里原来是 fail-open（返回空清单 = 没问题），而「没查成」与
        # 「查过了没问题」是两件事 —— 导入失败就等于这一格没查，必须如实报出来，
        # 否则一条 ②③ 根本没落盘的实验会被当成「齐了」。空清单只留给真查过且齐了。
        return [f"②③ 的落盘核查没查成（exhaustionreport 不可导入：{type(exc).__name__}: {exc}）"]
    try:
        return [str(p) for p in (_ER.landing_problems(row) or [])]
    except Exception as exc:  # noqa: BLE001 —— 判据自己坏了也是"没查成"
        return [f"②③ 的落盘核查没查成（exhaustionreport 抛了 {type(exc).__name__}: {exc}）"]


def find_exhaustion_record(experiments: Sequence[Mapping[str, Any]],
                           proof_text: Any, *, code_path: Any = "",
                           experiment_id: Any = "") -> dict[str, Any] | None:
    """按证明栏找那条"穷举 proof"记录 —— 不管它签名对不对（为了给出准确的拒信）。

    与 :func:`find_signed_exhaustion_for_column` 的分工：那个只回"签名合格的"，
    这个回"是这一条，但签名可能不合格" —— 两者都只在它们的射程里回答，
    拒信因此能说清是"没有这条记录"还是"有记录但签名不对"（两种欠账的处置不同）。

    认法与 `find_signed_exhaustion_for_column` 同一份（实验号 → code_path → ③ 正文 →
    旧形态整份），差别只在不筛签名。
    """
    raw = str(proof_text or "").strip()
    want_text = norm_text(raw)
    want_script = norm_rel(code_path)
    want_id = str(experiment_id or "").strip()
    if not (want_text or want_script or want_id):
        return None
    rows = [dict(r) for r in (experiments or ())
            if isinstance(r, Mapping) and is_calculation(r.get("method"))
            and str(r.get("evidence_kind") or "") == "proof"]
    if want_id:
        for row in rows:
            if str(row.get("experiment_id") or row.get("id") or "") == want_id:
                return row
    if want_text:
        for row in rows:
            if norm_text(enumeration_of(row)) == want_text:
                return row
        for row in rows:
            if norm_text(proof_column(row)) == want_text:
                return row
    if want_script:
        for row in rows:
            if norm_rel(row.get("code_path")) == want_script:
                return row
    return None


# ---------------------------------------------------------------- 索引（D 的报告 = 目录）

#: D 的报告是目录（业主 2026-10-23 夜：「D 侧报告的多半是新成果，B 基本都是从 D 的报告
#: 看到定理（命题），经索引看 F 侧证明或 E 侧报告，并核实 V 签」）。目录那一行就是一条索引，
#: 它必须说清四件事（缺任何一件，读的人就不知道该去取哪一份对象）：
#:
#: | 格 | 键 | 口径 |
#: |---|---|---|
#: | 证据是哪一档 | :data:`INDEX_KIND_FIELD` | :data:`INDEX_KIND_PROOF`（F 的证明）/ :data:`INDEX_KIND_REPORT`（E 的报告） |
#: | 对象的相对路径 | :data:`INDEX_PATH_FIELD` | 相对仓库根（`out/experiments/000000/exhaustion.md` / `proofs/000004-p1.md`） |
#: | 对象的指纹 | :data:`INDEX_SHA_FIELD` | 那份对象的字节 sha256（不是归一化之后的文本） |
#: | V 的签 | :data:`INDEX_SIGN_FIELD` | `{"verdict": "成立", "sha256": <被签那一份的 sha256>}` |
#:
#: 四格只有这一份口径：`papermapping` 的对应表行、B 的入库闸（:func:`filing_problems`）、
#: 以及 D 的提示词都从这里取名字，不各写一套。
INDEX_KIND_FIELD = "evidence_kind"
INDEX_PATH_FIELD = "evidence_path"
INDEX_SHA_FIELD = "evidence_sha256"
INDEX_SIGN_FIELD = "v_signature"
#: 索引指的那份对象是"谁的正文"：F 侧的证明 / E 侧的报告（业主那两句话的落点）。
INDEX_KIND_PROOF = "proof"
INDEX_KIND_REPORT = "report"
INDEX_KINDS: tuple[str, ...] = (INDEX_KIND_PROOF, INDEX_KIND_REPORT)
#: `v_signature` 那一格里的两个键（verdict + 被签那一份的 sha）。
SIGN_VERDICT_FIELD = "verdict"
SIGN_SHA_FIELD = "sha256"


def object_sha256(path: Any) -> str:
    """一份对象字节的 sha256（算在字节上，不算在归一化之后的文本上）。

    与 `verifications.proof_sha` 的分工：那个算的是"一段证明正文"（字符串），这个算的是
    "盘上那一份文件"。索引里的 `evidence_sha256` 与 `v_signature` 的 `sha256` 都用这一份口径，
    否则"签名时那一份"与"现在盘上那一份"会因为换行形态不同而永远对不上。
    """
    import hashlib
    from pathlib import Path

    return hashlib.sha256(Path(str(path)).read_bytes()).hexdigest()


def index_entry_of(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """从一行（对应表那一行 / D 报告的目录行）里取出索引四格（归一成同一形状）。

    缺的格一律空串（`:func:`index_problems` 据此点名缺哪一格）；`v_signature` 不是对象时
    原样放进 `raw_sign`，由判据说它读不懂 —— 不静默当成"签过了"。
    """
    row = _as_mapping(row)
    sign = row.get(INDEX_SIGN_FIELD)
    sig = _as_mapping(sign)
    return {
        "kind": str(row.get(INDEX_KIND_FIELD) or "").strip(),
        "path": norm_rel(row.get(INDEX_PATH_FIELD)),
        "sha256": str(row.get(INDEX_SHA_FIELD) or "").strip().lower(),
        "sign": sig,
        "verdict": str(sig.get(SIGN_VERDICT_FIELD) or "").strip(),
        "sign_sha256": str(sig.get(SIGN_SHA_FIELD) or "").strip().lower(),
        "raw_sign": sign,
    }


def index_problems(entry: Mapping[str, Any] | None) -> list[str]:
    """索引四格齐不齐（空清单 = 四格都在、形状也认得出；判据不碰盘）。

    逐格点名缺哪一件：读的人照着那句话去补那一格，而不是"索引不对"。
    """
    got = index_entry_of(entry)
    problems: list[str] = []
    if not got["kind"]:
        problems.append(
            f"缺 {INDEX_KIND_FIELD}：这份对象是 F 的证明（{INDEX_KIND_PROOF}）"
            f"还是 E 的报告（{INDEX_KIND_REPORT}）没写")
    elif got["kind"] not in INDEX_KINDS:
        problems.append(
            f"{INDEX_KIND_FIELD} = {got['kind']!r} 不在受控词表 {list(INDEX_KINDS)} 里")
    if not got["path"]:
        problems.append(
            f"缺 {INDEX_PATH_FIELD}：对象在仓库里的相对路径没写，读的人不知道该去取哪一份")
    if not got["sha256"]:
        problems.append(
            f"缺 {INDEX_SHA_FIELD}：那份对象的字节 sha256 没写（没有指纹就没法核"
            "「取到的是不是签名时那一份」）")
    if not isinstance(got["raw_sign"], Mapping) or not got["raw_sign"]:
        problems.append(
            f"缺 {INDEX_SIGN_FIELD}：V 的签没写（要 `{{\"{SIGN_VERDICT_FIELD}\": "
            f"\"成立\", \"{SIGN_SHA_FIELD}\": <被签那一份的 sha256>}}`）")
    else:
        if not got["verdict"]:
            problems.append(f"{INDEX_SIGN_FIELD} 里没有 {SIGN_VERDICT_FIELD}（V 的结论）")
        if not got["sign_sha256"]:
            problems.append(
                f"{INDEX_SIGN_FIELD} 里没有 {SIGN_SHA_FIELD}（签的是哪一份的 sha256）")
    return problems


def resolve_index(root: Any, entry: Mapping[str, Any] | None) -> dict[str, Any]:
    """顺索引取对象：四格齐 ⇒ 读盘 ⇒ 算 sha256 ⇒ 与索引和签里那两份 sha 各比一次。

    返回 `{"checked","found","path","sha256","verdict","problems","why"}`：

    - `checked=False` ⇒ 这一格没查成（没给工作区根 / 路径解析不了 / 读不出来），不是"没有对象"；
    - `checked=True, found=False` ⇒ 查过了：索引指不到对象，或对象与指纹对不上；
    - `checked=True, found=True` ⇒ `sha256` 是盘上那一份的字节 sha256，且它同时等于
      `evidence_sha256` 与 `v_signature.sha256`（判据 ④）。

    这是"顺索引取对象"的唯一实现：B 的入库闸与对应表的五档拦门都走它（打桩它，
    两条负控必须同时红 —— 判据 ⑥）。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "path": "", "sha256": "",
                           "verdict": "", "problems": [], "why": ""}
    got = index_entry_of(entry)
    if entry is None or not _as_mapping(entry):
        out.update(checked=True, problems=[
            "D 的报告里没有这一条命题的索引行（目录里没有 E 那本 / F 那本）⇒ 顺索引取不到对象"])
        out["why"] = out["problems"][0]
        return out
    missing = index_problems(entry)
    if missing:
        out.update(checked=True, problems=["索引四格不齐：" + "；".join(missing)])
        out["why"] = out["problems"][0]
        return out
    out["checked"] = True
    out["path"] = got["path"]
    out["verdict"] = got["verdict"]
    if root is None or not str(root).strip():
        out["problems"] = [
            f"没给工作区根 ⇒ 索引里那份对象 {got['path']!r} 无从取（这一格没查成，"
            "不是「对象不在」）"]
        out["why"] = out["problems"][0]
        return out
    target, why = _resolve_under(root, got["path"])
    if target is None:
        out["problems"] = [f"索引里的 {INDEX_PATH_FIELD} 不合口径：{why}"]
        out["why"] = out["problems"][0]
        return out
    if not target.is_file():
        out["problems"] = [
            f"索引指不到对象：{got['path']} 不在盘上（目录说有这一本，盘上没有）⇒ "
            "顺索引取不到，这一条不许当 proof"]
        out["why"] = out["problems"][0]
        return out
    try:
        got_sha = object_sha256(target)
    except OSError as exc:
        out["problems"] = [f"索引指的那份对象读不出来：{got['path']}"
                           f"（{type(exc).__name__}: {exc}）"]
        out["why"] = out["problems"][0]
        return out
    out["sha256"] = got_sha
    if got_sha != got["sha256"]:
        out["problems"] = [
            f"索引里的 {INDEX_SHA_FIELD} 与盘上那份对象不符：索引记 "
            f"{got['sha256'][:12]}…，盘上算得 {got_sha[:12]}… ⇒ 对象被换过 / 索引写的是别的版本"]
        out["why"] = out["problems"][0]
        return out
    if got["sign_sha256"] != got_sha:
        out["problems"] = [
            f"V 的签与对象 sha 不符：{INDEX_SIGN_FIELD} 签的是 "
            f"{got['sign_sha256'][:12]}…，而盘上那份对象是 {got_sha[:12]}… ⇒ "
            "这一签盖的不是这一份（判据 ④）"]
        out["why"] = out["problems"][0]
        return out
    if got["verdict"] != THIRD_PARTY_VERDICT_OK:
        out["problems"] = [
            f"索引里 V 的结论是 {got['verdict']!r}（要 {THIRD_PARTY_VERDICT_OK!r}）⇒ "
            "这一份没有被签住"]
        out["why"] = out["problems"][0]
        return out
    out["found"] = True
    out["why"] = (f"顺索引取到 {got['kind']} 那一份对象 {got['path']}"
                  f"（sha256 {got_sha[:12]}…，与 {INDEX_SHA_FIELD} 和 "
                  f"{INDEX_SIGN_FIELD} 两处都相符）")
    return out


def _resolve_under(root: Any, rel: Any) -> tuple[Any, str]:
    """把一条相对仓库根的路径解析成绝对路径（越界 / 绝对路径 ⇒ `(None, 理由)`）。"""
    from pathlib import Path

    text = norm_rel(rel)
    if not text:
        return None, "路径是空的"
    candidate = Path(text)
    if candidate.is_absolute() or ":" in text:
        return None, "必须是相对仓库根的路径（收到绝对路径）"
    if ".." in text.split("/"):
        return None, "不许用 `..` 跳出仓库根"
    base = Path(root).resolve()
    target = (base / candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None, "解析之后跑到仓库根外面去了"
    return target, ""


def find_index_entry(rows: Sequence[Mapping[str, Any]], *, program: Any = "",
                     proof_text: Any = "") -> dict[str, Any] | None:
    """在 D 报告的目录行里挑出"这一条命题"那一行（挑不到 ⇒ `None`，不猜一行）。

    两条认法，各对应业主说的两本正文：

    - 证明栏是程序（E 侧）：目录那一行的 `file` 就是那份程序 ⇒ 按路径认；
    - 正文是一份证明（F 侧）：手上这一份的内容就是对象 ⇒ 按内容 sha 认
      （目录里 `evidence_sha256` 等于这一份正文的 sha256）。

    先认 F 那一档（内容相同即同一份，不看顺序），再认 E 那一档（按程序路径）。
    """
    want_prog = norm_rel(program)
    text = str(proof_text or "")
    wants = set()
    if text:
        import hashlib
        wants.add(hashlib.sha256(text.encode("utf-8")).hexdigest())
        relaxed = norm_text(text)
        if relaxed != text:
            wants.add(hashlib.sha256(relaxed.encode("utf-8")).hexdigest())
    items = [dict(r) for r in (rows or ()) if isinstance(r, Mapping)]
    if wants:
        for row in items:
            got = index_entry_of(row)
            if got["sha256"] and got["sha256"] in wants:
                return row
    if want_prog:
        for row in items:
            got = index_entry_of(row)
            if got["kind"] in (INDEX_KIND_REPORT, "") \
                    and norm_rel(row.get("file")) == want_prog:
                return row
    return None


# ---------------------------------------------------------------- 第三方签字（V 的会审）

#: 第三方签字那一档的"签住了"取值（词表真身是 `verifications.VERDICTS` 的最后一档）。
THIRD_PARTY_VERDICT_OK = "成立"


def _sign_row_pins(row: Mapping[str, Any], *, want: set[str], want_object: str,
                   want_path: str) -> bool:
    """这一行台账盖的是不是"现在这一份"（认签的唯一判据，两条路共用）。

    判据只有三句（`draft/154` 的逐字口径）：

    1. 给了对象 sha、而这一行有 `object_sha256` ⇒ 必须相等；行上还写了
       `object_path` 时，路径也必须是这一份（同一份字节挂到别人的号上不算）。
       不许退回按 `proof_sha256` 认 —— 报告重跑（②③ 原文未变、读数变了）时正文
       sha 与旧签一致而对象已经换了，退回按正文认就会把"签的是旧版报告"读成"签过"。
    2. 给了对象 sha、而这一行没有那一格（D-34 之前写的 / 手写的行）⇒ 按
       `proof_sha256` 认（存量兼容，与改前逐字相同）。
    3. 没给对象 sha（B 的入库闸按证明栏认签那一路）⇒ 按 `proof_sha256` 认。
    """
    got_obj = str(row.get("object_sha256") or "").strip().lower()
    if want_object and got_obj:
        if got_obj != want_object:
            return False
        got_path = norm_rel(row.get("object_path"))
        return not (want_path and got_path and got_path != want_path)
    return str(row.get("proof_sha256") or "") in want


def _pending_stale_row(root: Any, *, want_object: str,
                       want_path: str) -> tuple[dict[str, Any], str]:
    """pending 台账里"盖的是同一份对象的旧版"的那一行，以及"没查成"的理由。

    只认 `object_path` 相同、`object_sha256` 不同这一种形态：没有对象路径的老行
    与这一份是不是同一个对象，台账上没有可判的事实 —— 那不是"签的是旧版"，
    宁可落到"从没审过"（`unsigned`）也不编一个旧版出来。
    """
    if not want_path:
        return {}, ""
    try:
        from . import verifications as _VR
        rows, problems = _VR.pending_rows(root)
    except Exception as exc:  # noqa: BLE001 —— 读不动 ⇒ "没查成"，不是"没有旧版"
        return {}, (f"`verifications/pending/` 读不出来（{type(exc).__name__}: {exc}）"
                    "⇒ 这一格没查成")
    if problems:
        return {}, f"pending 台账读不出来（{'；'.join(problems[:2])}）⇒ 这一格没查成"
    hit: dict[str, Any] = {}
    for row in rows:
        if norm_rel(row.get("object_path")) != want_path:
            continue
        got = str(row.get("object_sha256") or "").strip().lower()
        if want_object and got and got != want_object:
            hit = dict(row)
    return hit, ""


def latest_third_party_sign(root: Any, *, proof_text: Any = "",
                            statement_id: str = "",
                            object_sha256: str = "",
                            object_path: str = "") -> dict[str, Any]:
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

    返回 `{"checked","found","verdict","proof_sha256","ledger","why","route"}`，
    另有四格读数（2026-11-03，154 那一轮：收工门要按对象认签，也要分得清四结局）：

    - `checked=False` ⇒ 「没查成」（没给工作区根 / 台账读不出来），不是"没有签"；
    - `checked=True, found=False` ⇒ 查过了：台账不在盘上，或最近一签盖的不是这一份正文；
    - `checked=True, found=True` ⇒ `verdict` / `proof_sha256` / `ledger` 是那一签的读数。
    - `row` ⇒ 认到的那一整行（`found=True` 或"认到了但签不住"时非空）。为什么要交出去：
      「有毛病」的 `defect_step` / `findings` 只在行上，不交半行给调用方，读的人就只能知道
      "有毛病"、不知道第几步（`draft/154` 要的正是"第 4 步剪枝没解释"这一句）。
    - `signable` ⇒ 那一行自己够不够格签（`verifications.row_signable`：成立、无未解决 error、
      引用核实不挡、没有"引用核实没查成"）。`found` 的语义没有因此改变（它仍然是
      "认到了那一签"）—— 但收工门要的是"签住了"，那一档由调用方按这一格判。
    - `stale` / `stale_row` ⇒ 查过了、没有盖住这一份的签，但台账里有一行盖的是
      同一份对象的旧版（`object_path` 相同、`object_sha256` 不同），或命题台账最近一签
      盖的是别的正文。这两格把"从没审过"与"签的是旧版"分开 —— 改前两者都是 `found=False`。

    ## 认签的键：有对象格的行按对象核，没有对象格的老行才按正文 sha 核（2026-11-03）

    给了 `object_sha256`（收工门按 E 那份报告的字节 sha 认签）时：

    - 那一行有 `object_sha256` ⇒ 只认"等于它"（再核 `object_path`：行上写了路径、而路径
      不是这一份 ⇒ 不认）。不许退回按 `proof_sha256` 认：报告重跑一次（②③ 原文没变、
      程序/读数那几块变了）时正文 sha 与旧签一致而对象已经换了 —— 退回按正文认会把
      "签的是旧版报告"当成"签过"（那正是 `draft/154` 的第 ④ 种结局）。
    - 那一行没有那一格（D-34 之前写的行 / 手写的行）⇒ 按 `proof_sha256` 认（存量兼容；
      这条老口径一个字都没改）。
    - 没给 `object_sha256`（B 的入库闸那一路按证明栏认签）⇒ 与改前逐字相同：按 `proof_sha256` 认。

    ## D-34：找签改成"按对象内容 sha"（于是顺序不再重要）

    改前只按命题号读。可命题号是"登记之后"才有的：r34b 的真机现场是 `statements` 0 行，
    V 审完只能报 `statement_missing`，那一签没有落点、结论丢了。现在多一路
    :data:`~verifications.PENDING_DIR_NAME`（`verifications/pending/<sha>.jsonl`）：
    命题还没在册时 V 的那一签落在那里，按对象内容的 sha 认领 —— 于是"先签后登记"
    与"先登记后签"是同一件事。

    两路的次序：先读这一条命题自己的台账（若给了命题号），读不到"盖住这一份"的签时
    再读 pending 那一份。两路都按"最近一签说了算"：pending 里最后一次审校（成立/有毛病）
    就是结论。跨命题的台账不扫 —— `object_sha256` 相同的那一份对象只有一把钥匙，
    而"别的命题的签给这一行借光"是另一件事（`verifications` 的那条纪律不动）。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "verdict": "",
                           "proof_sha256": "", "ledger": "", "why": "",
                           "route": "", "object_sha256": "", "object_path": "",
                           # 四格读数（2026-11-03）：那一行本身 / 它够不够格签 / 有没有旧版的签。
                           "row": {}, "signable": False,
                           "stale": False, "stale_row": {}, "stale_ledger": ""}
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
    want_object = str(object_sha256 or "").strip().lower()
    want_path = norm_rel(object_path)
    out["object_sha256"] = want_object
    out["object_path"] = want_path
    if not text.strip() and not want_object:
        out["why"] = "证明栏是空的、也没给对象 sha ⇒ 没有可签的对象"
        return out
    # 两种写法都认：原样那一份，以及去掉行尾空白/首尾空行之后的同一份（签的人可能
    # 贴的是归一化过的那一份）。两个 sha 之外的一律不算 —— 宽松会让改稿后的旧签生效。
    want: set[str] = set()
    if text.strip():
        want = {_VR.proof_sha(text)}
        relaxed = norm_text(text)
        if relaxed != text:
            want.add(_VR.proof_sha(relaxed))
    # ---- 第一路：这一条命题自己的台账（原路，一个字都没改）
    sid = str(statement_id or "").strip()
    statement_why = ""
    if sid:
        path = Path(root) / _VR.VERIFICATIONS_DIR / f"{sid}.jsonl"
        if not path.is_file():
            statement_why = (f"`{_VR.VERIFICATIONS_DIR}/{sid}.jsonl` 不在盘上 ⇒ "
                             "这一条命题一次审校都没有（V 没审过它）")
        else:
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
                statement_why = f"`{_VR.VERIFICATIONS_DIR}/{sid}.jsonl` 是空台账（一行都没有）"
            else:
                lineno, last = sign
                ledger = (f"{_VR.VERIFICATIONS_DIR}/{sid}.jsonl#"
                          f"{last.get('verification_id') or f'line{lineno}'}")
                matched = _sign_row_pins(last, want=want, want_object=want_object,
                                         want_path=want_path)
                out.update(found=bool(matched),
                           row=dict(last) if matched else {},
                           signable=bool(_VR.row_signable(last)),
                           verdict=str(last.get("verdict") or ""),
                           proof_sha256=str(last.get("proof_sha256") or ""),
                           ledger=ledger,
                           route="statement")
                if out["found"]:
                    out["why"] = (f"{out['ledger']} 是最近一签，verdict={out['verdict']!r}、"
                                  "指纹与这一份相符")
                    return out
                # 认到了"这一条命题的最近一签"、但它盖的不是这一份（正文或对象对不上）⇒
                # 这是"签的是旧版"那一档的证据，不折进"从没审过"。
                out.update(stale=True, stale_row=dict(last), stale_ledger=ledger)
                statement_why = (f"{ledger} 是最近一签（verdict={out['verdict']!r}），"
                                 "而它的指纹与这一份对不上 —— "
                                 "签的是改稿前的旧版报告或别的正文")
                out.update(found=False, verdict="", proof_sha256="", ledger="", route="")
    else:
        statement_why = ("没给命题号 ⇒ 这一条还没在册（V 只审在册的命题）；"
                         "按对象 sha 去 pending 那边认领")
    # ---- 第二路：命题还没在册时 V 落的那一签（按对象内容的 sha 认领）
    out["checked"] = True
    try:
        pending = _VR.pending_sign(root, object_sha256=want_object,
                                   proof_shas=tuple(sorted(want)))
    except Exception as exc:  # noqa: BLE001 —— 读不动 pending 台账 ⇒ 没查成
        out["why"] = (f"`{_VR.VERIFICATIONS_DIR}/{_VR.PENDING_DIR_NAME}/` 读不出来"
                      f"（{type(exc).__name__}: {exc}）⇒ 这一格没查成")
        return out
    if pending.get("found"):
        # 判据与命题台账那一路同一条（`signs_bit3`，2026-10-27 收口）：pending 那一行
        # 写着「成立」不等于签住了 —— 未解决的 error、引用核实挡住、引用核实没查成
        # 三条里任一条成立都不算。改前这里只看 `verdict` 那个词，于是同一行内容
        # 放进 `verifications/<号>.jsonl` 会被拒、放进 pending 就被当成签过。
        pending_row = dict(pending.get("row") or {})
        pending_row.setdefault("verdict", str(pending.get("verdict") or ""))
        # 业主 2026-10-29 给 `signs_bit3` 加了「连续 N 次」那一闸；pending 这一签按
        # 对象 sha 认领，审的时候命题还没登记 ⇒ 没有命题台账可数连续次数，那条闸
        # 在这一档不适用。所以这里判的是行局部那一半（`row_signable`）——
        # 这不是放宽：改前 `signs_bit3` 只有这一半，逐字不变；连续闸要读的东西在
        # pending 这条路上根本不存在。
        if not _VR.row_signable(pending_row):
            out["found"] = False
            out["row"] = pending_row          # 认到了，但签不住 —— 行要交出去（defect_step 在行上）
            out["verdict"] = str(pending.get("verdict") or "")
            out["ledger"] = str(pending.get("ledger") or "")
            out["why"] = (f"{out['ledger']} 是 pending 那一路的最近一签，"
                          f"verdict={out['verdict']!r}，但它签不住："
                          # 复用 `verifications` 的私有措辞：拒信里"为什么签不住"只许
                          # 有一份说法（同一句话在两个出口上各写一遍必然漂移）。
                          + _VR._bit3_blockers(pending_row))
            return out
        out.update(found=True, row=pending_row, signable=True,
                   verdict=str(pending.get("verdict") or ""),
                   proof_sha256=str(pending.get("proof_sha256") or ""),
                   ledger=str(pending.get("ledger") or ""), route="pending")
        out["why"] = (f"{out['ledger']} 是 pending 那一路的最近一签，"
                      f"verdict={out['verdict']!r}、按对象 sha 认领到这一份"
                      "（命题登记之前审的那一签不丢）")
        return out
    out["found"] = False
    stale_row, stale_why = _pending_stale_row(root, want_object=want_object,
                                              want_path=want_path)
    if stale_why:
        # 读 pending 的那一步在上面已经查成了（`pending_sign` 读不动就会抛），所以这里
        # 读不出来只可能是两读之间盘上变了 —— 如实记"没查成"，不许折成"没有旧版"。
        out["checked"] = False
        out["why"] = stale_why
        return out
    if stale_row:
        out.update(stale=True, stale_row=dict(stale_row),
                   stale_ledger=(f"{_VR.VERIFICATIONS_DIR}/{_VR.PENDING_DIR_NAME}/"
                                 f"{str(stale_row.get('object_sha256') or stale_row.get('proof_sha256') or '')[:64]}"
                                 f".jsonl#{stale_row.get('verification_id') or '?'}"))
        out["why"] = (f"`{_VR.VERIFICATIONS_DIR}/{_VR.PENDING_DIR_NAME}/` 里有一签盖的是"
                      f"这份对象的旧版（{stale_row.get('object_path')!r}，签的 sha 与"
                      "现在这一份对不上）⇒ 它不算这一份的签")
        return out
    out["why"] = statement_why or (f"`{_VR.VERIFICATIONS_DIR}/"
                                   f"{_VR.PENDING_DIR_NAME}/` 里也没有盖住这一份的签")
    return out


def third_party_problems(proof_text: Any, *, root: Any = None,
                         statement_id: str = "",
                         object_sha256: str = "") -> list[str]:
    """这一份证明栏有没有第三方（V）的会审签名 —— 空清单 = 有，且最近一签是「成立」。

    三态（业主 2026-10-23 晚的口径，与 `verifications` 的三态纪律同向）：
    - 没查成（没给根 / 台账读不出来）⇒ 拒（不许折成"通过"）；
    - 没有签（台账不在盘上）⇒ 拒，点名"缺 V 的会审签名"；
    - 最近一签不是「成立」⇒ 拒，把那一签的 `verdict` 与台账行写进拒信；
    - 最近一签「成立」且 sha 对得上 ⇒ 空清单（这一条才够 proof）。

    `object_sha256` 是 D 报告的索引指的那份对象的字节 sha256（D-34）：给了它，
    "签盖的是不是这一份"这条判据就按对象内容回答 —— 于是命题登记之前审的那一签
    也能被认领（台账在 `verifications/pending/`）。
    """
    # 调用形状与老版本逐字兼容：没有对象 sha 时只传原来那两个关键字 —— 打桩
    # `latest_third_party_sign` 的既有反真空用例（`test_b_third_party_signature_gate.py`
    # 的第 ⑤ 条）因此不用改，它打的那个桩仍然是"读台账"那一路的唯一入口。
    kwargs: dict[str, Any] = {"proof_text": proof_text, "statement_id": statement_id}
    if str(object_sha256 or "").strip():
        kwargs["object_sha256"] = object_sha256
    sig = latest_third_party_sign(root, **kwargs)
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


def statement_id_for_column(statements: Sequence[Mapping[str, Any]],
                            proof_text: Any) -> str:
    """在册命题里"证明栏与这一份逐字相同"的那一条的号（认不出 ⇒ 空串，不猜）。

    为什么按证明栏认号：收工门手上只有实验行（E 的那份穷举证明），没有 B 交来的命题正文；
    "这一份报告被谁签过"的唯一入口是 V 的台账，而台账按命题号分文件。E 的证明栏是
    B 原样登记进 `statements.proof_text` 的那一份（业主：B 只负责原样登记）⇒ 按它认号
    与"按正文认号"是同一件事（`statement_id_for_body` 认的是命题正文，两者不可互换）。
    认不出 ⇒ 空串：调用方据此只读 pending 那一路（D-34：命题未在册时签落 pending）。
    """
    want = norm_text(proof_text)
    if not want:
        return ""
    for row in (statements or ()):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("kind") or "") == "concept":
            continue
        if norm_text(row.get("proof_text")) == want:
            return str(row.get("stmt_id") or "")
    return ""


#: 「V 有没有对这份 E 报告真签过」这一问的结局（`draft/154` 的四结局 + 「没查成」）。
#:
#: 只有 :data:`EXHAUSTION_BACKING_SIGNED` 是背书。其余四种理由各不相同（处置人不同）：
#: `defective` 要 E 去修第几步（`defect_step` 在读数里）、`unsigned` 要派 V 去审、
#: `stale` 要按现在这一份重新送审、`unchecked` 是这一格没查成（不是"没签"）。
EXHAUSTION_BACKING_SIGNED = "signed"
EXHAUSTION_BACKING_DEFECTIVE = "defective"
EXHAUSTION_BACKING_UNSIGNED = "unsigned"
EXHAUSTION_BACKING_STALE = "stale"
EXHAUSTION_BACKING_UNCHECKED = "unchecked"
EXHAUSTION_BACKING_STATES: tuple[str, ...] = (
    EXHAUSTION_BACKING_SIGNED, EXHAUSTION_BACKING_DEFECTIVE,
    EXHAUSTION_BACKING_UNSIGNED, EXHAUSTION_BACKING_STALE,
    EXHAUSTION_BACKING_UNCHECKED,
)


def _finding_detail(row: Mapping[str, Any], step: Any) -> str:
    """那一行台账里"第几步、为什么"的原文（找不到 ⇒ 空串，不编）。

    为什么单列：`defect_step` 只是一个号，读的人还要知道那一步的话才动得了手
    （`draft/154`：`exp:000058` 那一签的 `defect_step=4`，话是"代码里有 ['visited'] 这类
    剪枝/对称性构造，而 ③ 里一个字都没解释"）。
    """
    findings = [f for f in (row.get("findings") or []) if isinstance(f, Mapping)]
    for item in findings:
        if step is not None and item.get("step") == step:
            return str(item.get("detail") or "")
    for item in findings:
        if str(item.get("level") or "") == "error":
            return str(item.get("detail") or "")
    return ""


def _step_text(step: Any, detail: str) -> str:
    """「第几步不成立：那句话」（没点名第几步时如实说没点名，不编一个号）。"""
    if step is None:
        return detail or "（那一签没点名第几步，行上也没有 findings）"
    return f"第 {step} 步不成立" + (f"：{detail}" if detail else "")


def _refusal(why: str) -> str:
    """B 的入库闸那一句拒信（与 `third_party_problems` 同一个开头，读的人不用学两套）。"""
    return ("缺 V 的会审签名：" + why +
            "。E 的 `observations.e_signature` 是 E 自己盖的章，它不构成第三方签字；"
            "这一条要 proof，先让 V 会审这一份报告（产物是 "
            "`verifications/<命题号>.jsonl` 的那一行；命题未在册时落 "
            "`verifications/pending/<对象 sha>.jsonl`），签「成立」之后再来；"
            f"补不齐就最多是 {SUPPORTED_ONLY_KIND}（{SUPPORTED_ONLY_LABEL}）")


def _refusal_unchecked(why: str) -> str:
    """「没查成」那一句（三态：不许折成"签过"，也不许折成"没签"）。"""
    return ("缺 V 的会审签名：这一格没查成 —— " + why +
            "。没查成不是「签过」，所以这一条拿不到 proof")


def exhaustion_backing(experiment: Mapping[str, Any] | None, *, root: Any,
                       statements: Sequence[Mapping[str, Any]] = (),
                       statement_id: str = "") -> dict[str, Any]:
    """V 有没有对这份 E 报告真签过 —— 四结局 + 「没查成」（收工门与 B 的入库闸共用）。

    ## 它问的问题与 `third_party_problems` 不是同一个

    - `third_party_problems` 问「这一份证明栏被 V 签过吗」：B 的入库闸手上是 B 交来的
      三段式正文，按正文 sha 认签（F 侧那一路 / 老台账行全靠它）；
    - 这一个问「这一份 E 报告（`out/experiments/<号>/exhaustion.md` 的字节）被 V 签过吗」：
      收工门手上只有实验行 —— 没有命题正文、也不该去信 `e_signature`。它能按对象认的只有
      报告的 sha256，而 V 的台账行上 `object_sha256` / `object_path` 记的正是它
      （`agent_v/core.py` 落台账时取的就是 `exhaustionreport.review` 的
      `report_sha256` / `report_path`，业主 2026-10-23 夜 D-34 的认领模型）。

    判据逐字（`draft/154`）：「V 台账里存在一行，`object_sha256` == 这份 E 报告的 sha、
    `verdict` == 成立、且钉的 proof/row 与当前一致」。认签/认对象的键只有一处实现
    （:func:`_sign_row_pins`），两条路（命题台账 / pending）与两个调用方都走它。

    ## 四结局（每一种给不同的理由 —— 处置人不同，折平就没人知道该做什么）

    - `signed` ①：那一签判「成立」、签的就是现在这一份、且那一行自己签得住 ⇒ 给背书
      （这是业主裁定允许的那一档：穷举证明可以给承重结论背书，V 签的是 E 报告的
      理论论证部分）；
    - `defective` ②：V 判了「有毛病」（或判「成立」但那一行签不住）⇒ 不给背书，
      `defect_step` 与那一句原文进 `why`、`defect_step` 也单列一格；
    - `unsigned` ③：台账里从来没有这一份的签 ⇒ 不给背书，理由写"没审过"
      （不是"审过、没毛病"）；
    - `stale` ④：台账里有签、但签的是旧版（对象 sha 对不上）⇒ 不给背书，
      理由写"签的是旧版报告"；
    - `unchecked`：没给根 / 台账读不出来 ⇒ 不给背书（三态：没查成不是"签过"）。

    `statements` 只用来认号（:func:`statement_id_for_column`）：认不出也照样能查
    （pending 那一路按对象 sha 认领）。`statement_id` 给了就优先用它（B 的入库闸手上有号）。
    """
    row = _as_mapping(experiment)
    out: dict[str, Any] = {
        "checked": False, "state": EXHAUSTION_BACKING_UNCHECKED, "backed": False,
        "experiment_id": str(row.get("experiment_id") or ""),
        "statement_id": str(statement_id or "").strip(),
        "report_path": "", "report_sha256": "",
        "verdict": "", "defect_step": None, "ledger": "",
        "why": "", "problems": [],
    }
    if not is_signed_exhaustion(row):
        # 不是"E 签下的穷举证明行" ⇒ 这一问对它不成立（调用方据此不给背书，理由要说清
        # 是"这一行不在射程里"，不是"V 没签它"）。
        out.update(checked=True, state=EXHAUSTION_BACKING_UNSIGNED,
                   why="这一行不是「V 签、E 写 ②③」的穷举证明行 ⇒ 没有可签的报告对象")
        out["problems"] = [_refusal(out["why"])]
        return out
    if root is None or not str(root).strip():
        out["why"] = ("没给工作区根 ⇒ `verifications/` 无从读起（这一格没查成，"
                      "不是「没审过」）")
        out["problems"] = [_refusal_unchecked(out["why"])]
        return out
    try:
        from . import exhaustionreport as _ER
        from . import verifications as _VR
    except Exception as exc:  # noqa: BLE001 —— 那一侧读不到就是"没查成"
        out["why"] = (f"判据模块读不到（{type(exc).__name__}: {exc}）⇒ 这一格没查成")
        out["problems"] = [_refusal_unchecked(out["why"])]
        return out
    facts = _ER.report_facts(row)
    want_sha = str(facts.get("sha256") or "").strip().lower()
    want_path = norm_rel(facts.get("path"))
    out.update(report_path=want_path, report_sha256=want_sha)
    if not want_sha or not want_path:
        out.update(checked=True, state=EXHAUSTION_BACKING_UNSIGNED,
                   why=("②③ 没有落盘读数（`observations.exhaustion_report` 里没有 path/sha256）"
                        "⇒ V 没有可签的对象，这一行不算被签过（不是「V 审过、没毛病」）"))
        out["problems"] = [_refusal(out["why"])]
        return out
    column = proof_column(row)
    sid = str(statement_id or "").strip() or statement_id_for_column(statements, column)
    out["statement_id"] = sid
    sig = latest_third_party_sign(root, proof_text=column, statement_id=sid,
                                  object_sha256=want_sha, object_path=want_path)
    if not sig.get("checked"):
        out["why"] = str(sig.get("why") or "")
        out["problems"] = [_refusal_unchecked(out["why"])]
        return out
    out["checked"] = True
    out["ledger"] = str(sig.get("ledger") or "")
    if sig.get("found") and sig.get("signable"):
        verdict = str(_VR.read_verdict(sig.get("row") or {}) or sig.get("verdict") or "")
        out.update(state=EXHAUSTION_BACKING_SIGNED, backed=True, verdict=verdict)
        out["why"] = (f"{out['ledger']} 是最近一签，verdict={verdict!r}、签的就是"
                      f"现在这一份 E 报告（`{want_path}`，sha {want_sha[:12]}…）")
        return out
    if sig.get("row"):
        signed_row = dict(sig["row"])
        verdict = str(_VR.read_verdict(signed_row) or sig.get("verdict") or "")
        step = signed_row.get("defect_step")
        out.update(state=EXHAUSTION_BACKING_DEFECTIVE, verdict=verdict,
                   defect_step=step if isinstance(step, int) else None)
        if verdict == THIRD_PARTY_VERDICT_OK:
            out["why"] = (f"V 对这份 E 报告的最近一签判了「成立」，但那一签签不住"
                          f"（{out['ledger']}）：" + _VR._bit3_blockers(signed_row))
        else:
            out["why"] = (f"V 对这份 E 报告的最近一签判了 {verdict!r}（{out['ledger']}）："
                          + _step_text(step, _finding_detail(signed_row, step)))
        out["problems"] = [_refusal(out["why"])]
        return out
    if sig.get("stale"):
        stale_row = dict(sig.get("stale_row") or {})
        old = str(stale_row.get("object_sha256") or stale_row.get("proof_sha256") or "")
        out.update(state=EXHAUSTION_BACKING_STALE,
                   verdict=str(stale_row.get("verdict") or ""),
                   ledger=str(sig.get("stale_ledger") or ""))
        out["why"] = ("台账里那一签盖的是这份报告的旧版（"
                      + (f"它签的 sha {old[:12]}… " if old else "")
                      + "与现在这一份对不上）⇒ 不是这一份的签；改完要重新送审，"
                      "新的一签盖住新的一份")
        out["problems"] = [_refusal(out["why"])]
        return out
    where = (f"命题 {sid} 的台账里" if sid else
             "命题台账（这一条还没有在册的证明栏）与 pending 两路里")
    out.update(state=EXHAUSTION_BACKING_UNSIGNED,
               why=(f"{where}都没有盖住这一份 E 报告"
                    f"（`{want_path}`，sha {want_sha[:12]}…）的签 —— V 从没审过它"
                    "（不是「审过、没毛病」）"))
    out["problems"] = [_refusal(out["why"])]
    return out


def exhaustion_backing_problems(experiment: Mapping[str, Any] | None, *, root: Any,
                                statements: Sequence[Mapping[str, Any]] = (),
                                statement_id: str = "") -> list[str]:
    """`exhaustion_backing` 的拒信清单（空清单 = 有背书）。

    只做转发：拒信正文由 :func:`exhaustion_backing` 一次写完（两个出口共用同一句话 ——
    同一件事在两个出口上各写一遍必然漂移）。
    """
    return list(exhaustion_backing(experiment, root=root, statements=statements,
                                   statement_id=statement_id).get("problems") or [])


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
                    statement_full: Any = "",
                    index_rows: Sequence[Mapping[str, Any]] = (),
                    manuscript: Any = "") -> list[str]:
    """B 的入库闸：`proof` 这一档不许 B 自签，也不许 B 替 E 写穷举论证。

    只拦一种情形：`origin="own_result"` 且 `evidence_kind="proof"` ——
    那是我方结果自称"已证明"，它必须要么指到一条 V 签、E 写穷举论证的穷举证明
    （且证明栏就是 E 写的那一段、逐字相同），要么指到一条 `method="formal"` +
    `evidence_kind="proof"` 的形式化实验（那是"自证定理经核验后进库"的既有正路）。

    判据（业主 2026-11-08 的口径，替代改前的三段式口径）：
    - ⑥ 缺穷举论证、或 `experiments.code_path` 为空、或证明栏还是旧三段式
      ⇒ 不许 proof（拒信逐字点名"缺穷举论证"/"缺程序路径（code_path）"）；
    - ⑦ 签名主体必须是 V、穷举论证的作者必须是 E（`proof_authors` 含 E）；
      B 自称作者 / 改写 E 的读数 / 签名写成 `signed_by="E"` ⇒ 受控拒绝；
    - ②③ 的落盘核查交给 `exhaustionreport`（那一侧在时；不在时如实记"没查成"）；
    - 第三方签字（`root` / `statements` / `statement_full` 给了才查得了）：E 侧那一路
      调 :func:`exhaustion_backing`（与收工门同一份判据）—— V 的台账里存在一行、
      `object_sha256` == 这份 E 报告的 sha、verdict=成立、且签的就是现在这一份 ⇒ 放行；
      有毛病 / 没审过 / 签的是旧版 / 没查成 ⇒ 拒，拒信点名"缺 V 的会审签名"与
      是哪一种（`defect_step` 也写在里面）。F 侧那一路没有 E 报告，仍按证明栏/索引的
      sha 认（:func:`third_party_problems`）。E 的 `observations.e_signature` 是 E 自己
      盖的章，两条路都不算第三方；缺了这几个参数 ⇒ 这一格没查成 ⇒ 也拒（三态纪律：
      没查成不许折成通过）；
    - 都没有 ⇒ 最多到 :data:`SUPPORTED_ONLY_KIND`。

    `manuscript`（2026-11-08）：B 这一笔递进来的那份手稿的路径。`reports/e-proof-<号>.md`
    那个名字是"这份证明栏钉到哪条实验"的唯一无歧义键（两条实验可以共用同一份程序），
    所以程序路径从那条实验行的 `code_path` 读、而不是从证明栏文本里猜。

    ## D-34：多一路"顺索引取对象"（`index_rows` 是 D 报告里的目录行）

    业主 2026-10-23 夜的模型：D 的报告＝目录（新成果＋索引），F 的证明 / E 的报告＝正文，
    V 的签＝盖章，B＝读者。于是 B 的入库有两条正路，走哪一条由证明栏的形状定：

    - 证明栏是数值证据（有「穷举论证」那一段；2026-11-08 起程序路径在实验行的
      `code_path`）：先过原来那几档（③、落盘核查），再过第三方签字；`index_rows` 给得出
      这一条的索引行时，那一行也是要核的对象（:func:`resolve_index` 取到对象、四格与
      两份 sha 都对得上）—— 索引指不到对象 ⇒ 拒；
    - 证明栏不是数值证据（F 侧的自然语言证明）：以前在 ⑥ 那一档被一律拒（"证明栏不够格拿
      proof"）。现在它由索引进来：目录里那一行说这是 F 的证明（`evidence_kind="proof"`）、
      对象在盘上、sha 与 V 的签相符 ⇒ 允许登记成 proof。没有索引行 ⇒ 仍是 ⑥ 的那条拒信
      （只是补一句"要么给数值证据的证明栏，要么让 D 的报告索引指到这份证明"）。

    索引这一路是可打桩的（判据 ⑥ 的反真空）：`resolve_index` 恒成功 ⇒ 上面那两条负控
    （对象 sha 不符 / 索引指不到对象）必须当场放行。

    为什么 `external_lit` 不在这条闸的射程内：文献里的定理本来就带着它的证明，
    那一档的凭据是逐字引文（`quote_verified` / V 的逐行走查），不是 E 的一次实验。
    """
    kind = str(evidence_kind or "")
    if kind != "proof" or str(origin or "") != "own_result":
        return []
    text = str(proof_text or "").strip()
    # ---- 程序路径现在住在 `experiments.code_path`（2026-11-08） --------------------
    #
    # B 手上没有"那一条实验"时，从 E 的证明手稿名字读实验号（`reports/e-proof-<号>.md`
    # 是唯一不会歧义的键：两条实验可以共用同一份程序）。读到了就顺那条实验行取
    # `code_path`；读不到（F 侧 / 旧数据）再退回证明栏里旧 `程序：` 那一段。
    eid = ""
    resolved_code_path = ""
    exp_rows = [dict(r) for r in (experiments or ()) if isinstance(r, Mapping)]
    _ms = str(manuscript or "").strip().replace("\\", "/")
    if _ms:
        try:
            from . import exhaustionreport as _ER
            if _ER.is_manuscript_relpath(_ms):
                eid = _ER.experiment_id_of(_ms)
        except Exception:  # noqa: BLE001 —— 读不出实验号 = 这一格没接上（不猜）
            eid = ""
    if eid:
        _row = next((r for r in exp_rows
                     if str(r.get("experiment_id") or r.get("id") or "") == eid), None)
        if _row is not None:
            resolved_code_path = str(_row.get("code_path") or "")
    legacy_program = proof_column_script(text)
    if not resolved_code_path:
        # 钉不到实验行时，先按 ③ 的正文认出那一条（旧数据 / 调用方把稿当正文递进来），
        # 认到了就把它的 `code_path` 当程序路径 —— 次序仍是 实验号 > code_path > ③ 正文。
        _found = find_signed_exhaustion_for_column(
            experiments, text, code_path=legacy_program, experiment_id=eid)
        if _found is not None:
            resolved_code_path = str(_found.get("code_path") or "")
    parsed = parse_proof_column(text, code_path=resolved_code_path or legacy_program)
    program = parsed["script"]
    numeric_column = bool(parsed.get("numeric"))
    # ---- 顺索引取对象（D 报告那一行）：E 侧与 F 侧共用这一份判据与这一条取法。
    entry = find_index_entry(index_rows, program=program, proof_text=text) if index_rows else None
    indexed = resolve_index(root, entry) if entry is not None else None
    if indexed is not None and indexed["problems"]:
        return [
            "顺索引取对象没成：" + "；".join(indexed["problems"]) +
            "。业主 2026-10-23 夜的模型：D 的报告是目录，正文是 F 的证明或 E 的报告，"
            "V 的签是盖章 —— 目录那一行的四格（evidence_kind / evidence_path / "
            "evidence_sha256 / v_signature）必须指得到盘上那一份、且 V 签的就是它"
        ]
    want_object = str(indexed["sha256"]) if indexed is not None else ""
    if not numeric_column:
        # F 侧：正文不是数值证据的证明栏（没有「穷举论证」那一段）⇒ 索引是它进
        # proof 的唯一正路（判据 ③）。
        if indexed is None:
            return [
                "这一条的证明栏不够格拿 proof（它不是数值证据的证明栏 —— 没有"
                "「穷举论证」那一段，而 D 的报告里也没有指向它那份证明的索引行）" +
                ("；" + "；".join(parsed["problems"]) if parsed["problems"] else "") +
                "。F 侧的证明要 proof：让 D 的报告（论文对应表）为它写一行索引 —— "
                "evidence_kind=\"proof\"、evidence_path（那份证明在仓库里的相对路径）、"
                "evidence_sha256（它的字节 sha256）、v_signature（verdict + 被签那一份的 sha）；"
                "索引指得到、且 V 的签盖的就是那一份，这一条才登记成 proof。"
                f"补不齐就最多是 {SUPPORTED_ONLY_KIND}（{SUPPORTED_ONLY_LABEL}）"
            ]
        sid = statement_id_for_body(statements, statement_full)
        return third_party_problems(text, root=root, statement_id=sid,
                                    object_sha256=want_object)
    if parsed["problems"]:
        # ⑥：缺 ③ / 缺程序路径 / 还是旧三段式 ⇒ 不许 proof，且逐字点名缺哪一块。
        return [
            "这一条的证明栏不够格拿 proof：" + "；".join(parsed["problems"]) +
            "。业主 2026-11-08 的口径：穷举证明的证明栏只写 ③ 穷举论证；"
            "① 程序路径在 `experiments.code_path`（含后缀、相对仓库根）、"
            "② 程序设计在 `experiments.observations[\"design\"]` —— 两者都不许再抄进"
            "证明栏。③ 由 E 写、B 只原样登记。"
            f"补齐之前这一条最多是 {SUPPORTED_ONLY_KIND}（{SUPPORTED_ONLY_LABEL}）"
        ]
    found = find_signed_exhaustion_for_column(experiments, text,
                                              code_path=program, experiment_id=eid)
    if found is None:
        near = find_exhaustion_record(experiments, text, code_path=program,
                                      experiment_id=eid)
        if near is not None:
            sig = signature_of(near)
            authors = [str(a) for a in (sig.get(PROOF_AUTHORS_KEY) or [])]
            if str(sig.get("signed_by") or "") == NUMERIC_AUTHOR:
                # ⑦：签字由 V（业主 2026-10-23 晚的更正）—— 写 signed_by="E" 的那一版不算数。
                return [
                    "这条实验的签名主体写的是 E（signed_by='E'）⇒ 那一版口径已经作废："
                    "签字由 V，E 只是 ③ 与程序设计的作者。把签名改成 signed_by='V'、"
                    "proof_authors 含 'E' 之后再来登记"
                ]
            return [
                f"这条实验的签名不齐：signed_by={sig.get('signed_by')!r}、"
                f"{PROOF_AUTHORS_KEY}={authors!r} ⇒ 签名主体应是 {PROOF_SIGNER!r}、"
                f"③ 的作者应含 {NUMERIC_AUTHOR!r}。业主 2026-11-08：穷举论证由 E 写、"
                "程序在 code_path，签字由 V，B 只原样登记 —— B 自称作者（或替 E 写）"
                "这一条拿不到 proof"
            ]
        return [
            "证明栏是穷举论证，但台账里没有与它对应的穷举证明"
            "（experiments 里要有 code_path 指向那份程序、evidence_kind='proof'、"
            "observations.e_signature 里 signed_by='V'、proof_authors 含 'E'、"
            "proof_reason='exhaustion'）⇒ B 不许自签，也不许替 E 把穷举论证写出来："
            "这条先把实验跑成 proof（E 的 run_experiment），再来原样登记"
        ]
    sig = signature_of(found)
    authors = [str(a) for a in (sig.get(PROOF_AUTHORS_KEY) or [])]
    want_enum = str(sig.get("enumeration") or "").strip()
    if norm_text(parsed["enumeration"]) != norm_text(want_enum):
        # ⑦ 的另一半：改写成自己的话也算"替 E 写"。
        return [
            "证明栏的穷举论证与 E 签名里的原文不一致 ⇒ B 不许把 E 的读数改写成自己的话"
            "（业主 2026-11-08：B 只负责原样登记）。"
            "把 E 给的那一段逐字贴回来，或让 E 重出一份"
        ]
    if norm_rel(parsed["script"]) != norm_rel(found.get("code_path")):
        return [
            f"证明栏对应的程序 {parsed['script']!r} 与实验行 exp:"
            f"{str(found.get('experiment_id') or found.get('id') or '')} 的 "
            f"`code_path` {str(found.get('code_path') or '')!r} 不是同一份 ⇒ "
            "同一条定理的「实验栏」只能指一份程序（业主 2026-11-08）"
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
    # evidence_kind=proof、bits.reviewed=False）。
    #
    # 2026-11-03（`draft/154` 业主裁定「V 要签的是 E 那份报告的理论论证部分」）：这一格
    # 改成调 `exhaustion_backing` —— 与收工门（`closing._has_t3` 的穷举支路）同一份判据、
    # 同一句话（改前收工门不核第三方签，B 入库核：同一条链两套口径）。
    # 认签的键是 V 台账行上的 `object_sha256`（E 那份报告的字节 sha，`agent_v/core.py`
    # 落台账时取 `exhaustionreport.review` 的 `report_sha256`）；判据本体只有一处
    # （`_sign_row_pins`，经 `latest_third_party_sign` 的两条路读出）。
    # 四结局（成立 / 有毛病 / 没审过 / 签的是旧版）各给各的理由 —— 处置人不同，折平之后
    # 读的人只知道"缺签"、不知道该派谁去做什么。
    sid = statement_id_for_body(statements, statement_full)
    return exhaustion_backing_problems(found, root=root, statements=statements,
                                       statement_id=sid)


def verifier_problems(statement: Mapping[str, Any],
                      experiments: Sequence[Mapping[str, Any]] = ()) -> list[str]:
    """V 的逐行走查（`verify.verify_proof`）不覆盖这一条命题的理由（空清单 = 它照旧管）。

    签名主体是 V，但"签字"与"逐行走查"是两件事：这条命题的"证明"是数值证据
    （证明栏里有「穷举论证」那一段，程序在 `experiments.code_path`）⇒ V 没有跑过那份
    程序，所以逐行走查不覆盖它 —— 那一签要说清是"对数值证据的背书"，
    而不能被下游读成"V 逐行审过这份证明了"。
    """
    row = _as_mapping(statement)
    text = str(row.get("proof_text") or "").strip()
    parsed = parse_proof_column(text)
    if not parsed.get("numeric"):
        return []
    script = proof_column_script(text) or "（见 experiments.code_path）"
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

#: 证明通道的三个取值（`proof_channel` 的返回值；空串 = 这一格对它不适用）。
#:
#: 为什么单独拎出来：`formal_slot` 的 `channel` 与 `kind` 是两件事 —— `kind` 说"该填哪一类"
#: （`FORMAL_SLOT_KINDS`），`channel` 说"这条命题的证明走哪条路"（这里这三个）。
#: 把两者混用（拿 `kind` 去比 `channel`）会让"通道是空的"与"通道是数值的"读成同一个。
PROOF_CHANNEL_NUMERIC = "numeric"
PROOF_CHANNEL_FORMAL = "formal"
#: Lean 源码的后缀（理论定理那一格只认它）。
LEAN_SUFFIXES: tuple[str, ...] = (".lean",)


def is_lean_path(path: Any) -> bool:
    """这一串字是不是一份 Lean 源码的相对路径。"""
    text = str(path or "").strip().replace("\\", "/").lower()
    return bool(text) and text.endswith(LEAN_SUFFIXES) and ":" not in text \
        and not text.startswith("/") and ".." not in text.split("/")


def _bound_formal_rows(statement: Mapping[str, Any],
                       experiments: Sequence[Mapping[str, Any]]
                       ) -> list[Mapping[str, Any]]:
    """台账里绑到这条命题的 formal 证明行（`evidence_kind="proof"` 的 `.lean` 产物）。

    绑定口径只有一处：`evidencebits.formal_row_bound_to`（四处绑定点，与
    `evidencebits.formal_ledger_reading` 同一份）。这里不再写第三套判断。

    为什么必须绑：改前这里只筛 method / evidence_kind / 产物后缀 —— 那是整张表的
    读数（"这台机器上有一条 formal 行"），不是"这条命题被形式化过"。于是 L 只给一条
    命题记 formal，同一张表里别的散文证明的命题也被判成 formal 通道
    （2026-11-05 手工走查 78c：`prop:siegel` / `prop:region` / `prop:barrier` 各多报
    一条 `mapping_lean_missing`，而 L 从未碰过它们）。
    """
    from . import evidencebits as _EB   # 惰性：绑定口径只有一处（也避开模块级环）
    rows: list[Mapping[str, Any]] = []
    for row in (experiments or ()):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("method") or "") != FORMAL_METHOD:
            continue
        if str(row.get("evidence_kind") or "") != "proof":
            continue
        if not is_lean_path(row.get("code_path") or row.get("proof_location")):
            continue
        if not _EB.formal_row_bound_to(row, statement):
            continue
        rows.append(row)
    return rows


def proof_channel(statement: Mapping[str, Any],
                  experiments: Sequence[Mapping[str, Any]] = ()) -> str:
    """这条命题的证明走的是哪一条通道：`"numeric"` / `"formal"` / `""`（没有通道）。

    判据（顺序即口径）：
    1. 证明栏里有「穷举论证」那一段（`parse_proof_column(...)["numeric"]`）、且台账里有
       一条与之对应的穷举证明 ⇒ `numeric`（数值实验定理）；程序路径在那条实验行的
       `code_path` 上；
    2. 否则证明栏是程序（.lean）且台账里有一条 `method="formal"` + `evidence_kind="proof"`
       的行、且那一行绑到这条命题上 ⇒ `formal`（理论定理的 Lean 程序）；
    3. 都不是 ⇒ 空串（没有这一类证明栏，这一格对它不适用）。

    "绑到这条命题"的四处绑定点只有一份口径（`evidencebits.formal_row_bound_to`）：
    台账里别的命题的 formal 行不是这一条的凭据。
    """
    row = _as_mapping(statement)
    text = str(row.get("proof_text") or "").strip()
    parsed = parse_proof_column(text)
    if parsed.get("numeric") and find_signed_exhaustion_for_column(experiments, text) is not None:
        return PROOF_CHANNEL_NUMERIC
    script = parsed["script"] or proof_column_script(text)
    if script and is_lean_path(script):
        return PROOF_CHANNEL_FORMAL
    lean_rows = _bound_formal_rows(row, experiments)
    if lean_rows and not script:
        return PROOF_CHANNEL_FORMAL
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
    - `path`：这一格应当填的那份程序（通道为空时为空）；数值通道那份是实验行的
      `code_path`（2026-11-08：程序不再住在证明栏里）；formal 通道取的那一行必须
      绑到这条命题（`evidencebits.formal_row_bound_to` 的四处绑定点）—— 台账里别的命题
      的 formal 行不是这一条的凭据；
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
    if channel == PROOF_CHANNEL_NUMERIC:
        found = find_signed_exhaustion_for_column(experiments, text)
        path = norm_rel((found or {}).get("code_path"))
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
                     for r in _bound_formal_rows(row, experiments)), "")
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
