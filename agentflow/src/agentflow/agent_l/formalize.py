# -*- coding: utf-8 -*-
"""角色 L 的动作 `formalize`：把一条命题写成 `.lean` 落盘，然后交给检查器真跑。

## 为什么需要这一格（它是 L 与 E 唯一的结构差别）

E 那条路是两步拼出来的：`fs.write` 把源码写进 `code/lean/`，再
`run_experiment(method="formal", script_path=…)` 让它落一行 `experiments`。
两步之间的"到底写没写盘"没有任何机器判据 —— 内联 `check_formal(source=…)`
把源码放在临时目录里跑完就删，那份文件既不是 `proof_location`，也无法复跑。
业主 2026-10-22 要的是"L 真的能写 Lean 代码、真的能干活"，所以这一格把
"写盘 + 检查 + 三态结论"收成一个动作，让"写没写盘"变成返回值里的
`path` / `sha256` / `bytes` 三格，而不是一句自述。

## 落点

`code/formal/<短名>.lean`（工作区相对路径）。为什么不是 E 的 `code/lean/`：
"这个 .lean 是谁写的"要一眼看得出来；两个角色写同一个目录时它只能靠猜。

## 名称的两件事（真机读数逼出来的）

盘上的文件名与交给检查器的声明名不是同一件东西：

- 文件名用短名（`code/formal/add_zero_probe.lean`，好认）；
- 交给检查器的是全名：桥接层会往源码尾部追加一条 `#print axioms <名字>`
  （公理审计），而 Lean 4 里命名空间内的定理在文件作用域叫 `LProbe.add_zero_probe`
  —— 只给短名时检查器会报 `unknown constant 'add_zero_probe'`，于是一条真定理
  被记成 compile_error（实测：2026-10-22，本机 Lean 4.7.0）。
  所以 L 自己从源码里把 `namespace … end` 的限定算出来（`:func:`declaration_name_in`），
  调用方给了短名时自动升级成全名；给了全名就照用。

## 三件必须一起成立的事

1. 真的写盘：`write_bytes`（不是 `write_text`：Windows 上它会把 `\\n` 刷成
   `\\r\\n`，于是"这份源码的 sha256"变成一个与内容无关的数）；行尾先统一成 `\\n`，
   sha256 算的是盘上那串字节；
2. 真的检查：`usable` 时把刚写的那个相对路径交给 `check_formal`
   （E 的实现 + 同一个桥接层），结论三态；不是 `usable` 时不起检查器，
   结论 `unknown` + 自检理由码（同一条失败只报一行）；
3. 真的拒绝：源码里没有具名 `theorem` / `lemma`、或者声明名不合法、
   或者目标路径越界 ⇒ 受控 `param_error` / `path_outside_workspace`，
   一个字节都不写（"先写一半再报错"会让盘上留一份来路不明的文件）。

## 忠实复述：从文字义务变成机器可核的读数（2026-10-22 第二班）

改前这一格只核"声明名在源码里"（`_declared_in_source`），而 `claim` 是一段自由
文本 —— 于是"L 形式化的到底是不是 B 登记的那一条"没有任何机器读数，只有一句自述。
这一班补三件东西，缺一件这一格就还是文字义务：

1. `statement_id` 参数：被形式化的那一条命题在 `statements` 表里的编号。给了就
   逐格核它（行在、`statementbody.body_of(row)` 非空、`proof_text` 非空、
   `claim` 与该行正文逐字相同）；四条任一条不成立 ⇒ 受控拒绝（`reason` 是一条
   受控理由码），一个字节都不写。没给时只有一种可证明的来源：`claim` 与某一行的
   正文逐字相同且唯一 —— 那就认这一行（`statement_source="claim_match"`）。
   两者都做不到时：表里一行命题都没有 ⇒ `no_ledger`（见下），否则拒绝。
2. `code/formal/<名字>.steps.jsonl`：逐步对照表，一行一步，
   `{"proof_step", "quote", "lean_lines", "how"}`。`quote` 是 `proof_text` 第 k 步
   压掉连续空白之后的前 60 字（逐字截取，不转述、不摘要），`lean_lines` 是
   `[起, 止]` 行号，`how` 是四档之一（见 `HOW_VALUES`）。
3. `coverage` 读数随返回值一起给出：`steps_total` / `steps_mapped` / `unmapped` /
   `sorry_lines` / `assumptions_added`（外加几格诊断读数）。硬规则只有一条：
   `steps_mapped < steps_total` 或源码里出现 `sorry` / `admit` ⇒ 综合结论只能是
   `unknown`（带理由码），不许 `verified`。

### 消费 B 的定理证明库（2026-10-22 晚业主裁定的第三句）

返回值与 `coverage` 里各有一格 `b_library`（四格读数 + `found`，见
:func:`_library_reading`）。取不到 B 的库（编号不在册 / 没有正文 / 没有证明 / claim
与正文不是同一句）⇒ 受控拒绝、一个字节都不写、也不起检查器；那一分支上
`b_library.found=False` 但仍然在。

### 向 B 汇报形式化困难（同一份裁定的第四句）

`formalize` 判"形式化失败或对不上"时，自己把一条受控形态的汇报投进 B 的收件箱
（`agent_l/report.py` + `proofreport.py`），返回值里那一格是 `report`
（`state` 三档：`reported` / `skipped` / `refused`）。检查器/本地环境那一档
不汇报（B 改不动），理由写在 `report.reason` 里 —— "没汇报"与"汇报了"是两个 `state`。

### 步骤切分口径（写死在这里，判据照它）

`split_proof_steps()` 按三种形态择一切分，顺序即优先级：

1. 主口径 —— 空行分段（连续两个换行以上）。B 的 `proof_text` 最常见的写法是
   一步一段，它也是唯一不依赖"有没有编号"的口径；
2. 退化一 —— 只切出一段、而文本里有编号行（`1.` / `（1）` / `第 1 步`）时按编号行切；
3. 退化二 —— 仍然只有一段时按句末标点切（`。` / `；` / 英文句点后跟空白）；
4. 都不成立 ⇒ 整份算一步（`steps_total=1`）。

`how` 记的是"Lean 这一边怎么接上的"，不是切分口径 —— 切分只有一套（上面那个
优先级），把切分口径也塞进 `how` 会让两件事共用一个格子，读者分不出
"这一步被哪条规则切出来的"与"这一步在 Lean 里是不是直接对应"。

### Lean 这一边怎么找到落点（约定写在这里，L 照着写）

源码里的注释行是唯一机械可认的落点：

- `-- step <k>`（也认 `-- 步骤 <k>`、`-- step: <k>`）：第 k 步的 Lean 块从这一行
  开始，到下一个标记行的前一行结束（最后一个到源码最后一行非空处）；
- `-- assume <文本>`（也认 `-- 假设 <文本>`、`-- 补假设 <文本>`）：这一处补了一个
  原文里隐含的假设，文本原样进 `assumptions_added`；
- 没有任何标记的步骤 ⇒ `how="未映射"`，`lean_lines=[]`，并在 `coverage.unmapped`
  里点名。不许用 `sorry` / `admit` 把它堵住：含 `sorry` 的文件照样编译通过
  （退出码 0），那不是证明 —— 所以 `sorry` 单独有一格读数，且它自己就足以把
  综合结论压回 `unknown`。

`how` 的四档判定（优先级从高到低，越靠前越"不是直接复述"）：

1. `未映射` —— 没有标记；
2. `自足定义` —— 这一块里有 `def` / `abbrev` / `structure` 行（原文用了私有定义，
   Lean 这边换成了自足定义）；
3. `补假设` —— 这一块里有 `-- assume` 标记；
4. `直接对应` —— 以上都没有。

### 综合结论与检查器结论是两件事（不许折叠）

返回值里 `status` 是综合结论（检查器说了什么，叠加忠实复述的读数），
`checker_status` / `checker_reason` / `verified` / `exit_code` / `verifier_output`
是检查器原话。于是"机器核过了"（`checker_status="verified"`）与
"这一趟算数"（`status="verified"`）各有一格读数：前者是检查器的，后者还要
逐步对照过。`faithfulness` 那一格是第三件事的读数
（`complete` / `incomplete` / `holes` / `unknown`）。

压回 unknown 的边界（两类理由的强度不同）：`faithfulness_sorry` 会把
verified 与 failed 两档都盖成 unknown（含 sorry 的文件照样编译通过，把它读成
通过与读成失败都不是我们要的读数）；漏步与多标步只盖 verified —— 检查器已经
说 failed 时不动它，因为"我们写的那份源码编译不过"比逐步对照更强。无论哪一档，
检查器原话都留在 `checker_*` 两格与 `verifier_output` / `exit_code` 里，一个字节不丢。

## 它不做什么

- 不调模型：L 不"生成"Lean 代码，源码是调用方给的（B 的命题 + 证明链路、
  或派活的人写好的）。这条与 E 的 `author_script` 分工相同：模型可以写脚本，
  但判读一步都不许过模型（FC-16）；
- 不写任何数据表：产物是盘上的文件与检查器原话（L 的 `write_set` 因此是空的）；
- 不猜 imports：源码自己 import 什么就加载什么，与 E 的政策同一口径；
- 不核"假设等价"：这一步要读出 Lean 里那条定理的类型再与原文假设置换比对，
  今天的机器读数只到"这一步落在哪几行、它是直接对应还是补了假设"。缺口如实
  记在 `assumptions_added` 里，不假装它被核过。
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from .. import statementbody as _SB
from .. import verifications as _VR   # 证明号 / 证明清单 / 正文 sha 的口径各只有一处
from ..agent_e._support import ExperimentError
from ..canonical import json_default
from ._support import (
    DECLARATION_NAME_RX,
    FORMAL_DIR,
    normalize_source,
    one_line,
    sha256_of_bytes,
)

#: 一条形式化源码的保守下限：至少一条具名定理 / 引理。没有它就是"还没写形式化"。
_HAS_DECL_RX = re.compile(r"(?m)^[ \t]*(?:theorem|lemma)[ \t]+")
#: 具名 `theorem` / `lemma`（短名；全名由命名空间栈拼出来）。
_DECL_RX = re.compile(r"(?m)^[ \t]*(?:theorem|lemma)[ \t]+([A-Za-z_][A-Za-z0-9_']*)")
#: `namespace A.B` / `section` / `end ...`（只用来算限定名，不做 Lean 语法解析）。
_NAMESPACE_RX = re.compile(r"(?m)^[ \t]*namespace[ \t]+([A-Za-z_][A-Za-z0-9_'.]*)")
_SECTION_RX = re.compile(r"(?m)^[ \t]*section(?:[ \t]+[A-Za-z_][A-Za-z0-9_'.]*)?[ \t]*$")
_END_RX = re.compile(r"(?m)^[ \t]*end(?:[ \t]+[A-Za-z_][A-Za-z0-9_'.]*)?[ \t]*$")
#: 调用方给的声明名（可以带命名空间限定：`LProbe.add_zero_probe`）。
_QUALIFIED_RX = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_']*)(?:\.[A-Za-z_][A-Za-z0-9_']*)*$")

#: 第 k 步的 Lean 落点标记（必须独占一行；见模块 docstring 的约定一节）。
_STEP_MARK_RX = re.compile(
    r"(?i)^[ \t]*--[ \t]*(?:step|步骤)[ \t]*[:：]?[ \t]*(\d{1,3})(?![0-9])")
#: "这一处补了一个假设"的标记（独占一行）。
_ASSUME_MARK_RX = re.compile(
    r"(?i)^[ \t]*--[ \t]*(?:assume|假设|补假设)[ \t]*[:：]?[ \t]*(.*)$")
#: `sorry` / `admit` 这两个词（在剥掉注释与字符串之后的代码行上认）。
_SORRY_RX = re.compile(r"(?<![A-Za-z0-9_'])(?:sorry|admit)(?![A-Za-z0-9_'])")
#: "自足定义"那一档认的行首关键字。
_DEF_RX = re.compile(
    r"^[ \t]*(?:(?:private|protected|noncomputable|partial|unsafe)[ \t]+)*"
    r"(?:def|abbrev|structure)[ \t]+")
#: 编号行的三种写法（退化一口径）。
_NUMBERED_RX = re.compile(
    r"^[ \t]*(?:第[ \t]*\d{1,3}[ \t]*步|[(（][ \t]*\d{1,3}[ \t]*[)）]|\d{1,3}[.、)])")
#: 句末标点（退化二口径）。
_SENTENCE_RX = re.compile(r"(?<=[。；;])|(?<=\.)\s+")

#: `steps.jsonl` 每行恰好这四格（多一格就是没登记的口径）。
STEP_ROW_KEYS: tuple[str, ...] = ("proof_step", "quote", "lean_lines", "how")

#: `how` 的四档（顺序即优先级，见模块 docstring）。
HOW_VALUES: tuple[str, ...] = ("未映射", "自足定义", "补假设", "直接对应")

#: `quote` 取第 k 步正文的前多少字。
QUOTE_CHARS = 60

#: 命题台账这一格的受控拒绝理由码（`formalize` 的 `reason` 只从这张表里取）。
STATEMENT_REASONS: tuple[str, ...] = (
    "statement_not_found",
    "statement_id_ambiguous",
    "statement_without_body",
    "statement_without_proof",
    "claim_mismatch",
    "statement_ledger_unreadable",
)

#: 路径这一格的受控拒绝理由码（业主 2026-10-22：「lean 形式化需指明对哪个路径做了
#: 形式化验证」）。两个码各守一种病，处置完全不同：
#:
#: - `proof_path_not_found`：给了一个号，而那个号不在这条命题的证明清单里（含"号认不出"）
#:   ⇒ 要的是"换一个号"；
#: - `proof_path_unspecified`：这条命题有好几份证明（`#p1`、`#p2` …），而这一趟没说验哪一份
#:   ⇒ 一个字节都不写。这一档绝不能默认落到 `#p1`：那会让"验了第 2 条"被记成"验了第 1 条"，
#:   而第 4 位（形式化，二维）里两条路径的读数正好相反。
PROOF_PATH_REASONS: tuple[str, ...] = (
    "proof_path_not_found",
    "proof_path_unspecified",
)

#: "这一趟的路径是谁选的"（`path_source`）的三档：B 指定 / 照 C 的建议 / L 自己决定。
#:
#: 业主的补裁（逐字）：「L 可以通过 C 的建议选择路径，也可以由 B 指定路径，也可以自行决定，
#: 只是在标记和五元位更新时要忠实」。所以这一格是"谁选的"，而"谁验的"是另一个读数
#: （`record` 落的那一行 `observations.recorded_by` = L）—— 两者不许折成一格。
PATH_SOURCES: tuple[str, ...] = ("B", "C", "L")

#: 忠实复述这一格的受控理由码（综合结论被压回 `unknown` 时用它）。
FAITHFULNESS_REASONS: tuple[str, ...] = (
    "faithfulness_incomplete",
    "faithfulness_sorry",
    "faithfulness_extra_steps",
)

#: 本模块追加到 L 的理由词表里的全部取值（`_support.FORMAL_REASONS_L` 的超集口径）。
L_STATEMENT_AND_FAITHFULNESS_REASONS: tuple[str, ...] = (
    tuple(STATEMENT_REASONS) + tuple(PROOF_PATH_REASONS) + tuple(FAITHFULNESS_REASONS))

#: 每一条分支上都成立的"忠实复述读数"键（E-12(a) 的同一条纪律：键集合随分支变，
#: 判据就会在缺键的那条分支上静默失效）。
FAITHFULNESS_KEYS: tuple[str, ...] = (
    "statement_id",
    "statement_source",
    "coverage",
    "faithfulness",
    "steps_path",
    "refused",
    "checker_status",
    "checker_reason",
    # 2026-10-22 晚（业主裁定："消费 B 的定理证明库"）：这一趟从 B 的库读到的
    # 是哪一条、它有多大、依赖链几步 —— 判据（`tests/test_l_collab_surface_is_exactly_this.py`）
    # 读的就是这一格；取不到库的那些分支上它是 `found=False` 的空壳，照样在。
    "b_library",
    # 向 B 汇报的那一条（`agent_l/report.py`）：`state` 三档，`reported` 才是"B 收到了"。
    "report",
    # 2026-10-22 晚（业主裁定：形式化那一位要指明路径）：这一趟验的是哪一份证明、
    # 那份正文的指纹、以及"这个号是谁选的"。四格在每条分支上都成立（被拒时是空值 +
    # `refused=True`）—— 缺一格就会让"验的是哪条路径"在那条分支上无从查起。
    "proof_no",
    "proof_sha256",
    "path_id",
    "path_source",
)

#: `b_library` 的键集合（`coverage.b_library` 与返回值里的那一格逐键相同）。
B_LIBRARY_KEYS: tuple[str, ...] = (
    "stmt_id",
    "label",
    "proof_chars",
    "dependency_steps",
    "found",
)


class _Formalize:
    """`formalize` 这一格（见模块 docstring）。"""

    def formalize(
        self,
        claim: str,
        *,
        source: str,
        statement_id: str | None = None,
        proof_no: Any = None,
        path_source: str = "",
        declaration_name: str | None = None,
        imports: Sequence[str] | None = None,
        timeout_sec: float | None = None,
    ) -> dict:
        """写 `.lean` 落盘 + 逐步对照 + 交给检查器真跑一次。

        返回的键 = `check_formal` 那一套（E 的九个 + L 的四格）再加下面这些：

        - 盘上读数：`path` / `sha256` / `bytes` / `declaration_name` / `written`；
        - 忠实复述读数：`statement_id` / `statement_source` / `coverage` /
          `faithfulness` / `steps_path` / `refused`；
        - 检查器原话（不被忠实复述的读数覆盖）：`checker_status` / `checker_reason`；
        - 路径读数（2026-10-22 晚）：`proof_no`（验的是第几份证明）/ `proof_sha256`
          （那一份正文的指纹）/ `path_source`（这个号是 B 定的、照 C 的建议、还是 L 自己选的）。

        全部键在每一条分支上都成立（被拒时 `written=False`、`coverage={}`、
        `refused=True`）—— 键集合随分支变会让判据在缺失的那条分支上失效。

        `statement_id` 的三条来源（按优先级）：显式给的编号 → `claim` 与台账某一行
        正文逐字相同且唯一 → 台账里一行命题都没有（`no_ledger`，此时没有可对照的
        原文，`faithfulness="unknown"`）。前两条之外一律受控拒绝，一个字节都不写。

        `proof_no` 的两条规矩（业主 2026-10-22：「要指明对哪个路径做了形式化验证」）：
        给了就按它（号不在册 ⇒ `proof_path_not_found`）；没给而这条命题有好几份证明
        ⇒ `proof_path_unspecified`，一个字节都不写。只有一份证明时不拒绝（存量 62 行
        都是这种，它们只有 `#p1`）。落盘名字跟着号走：`#p1` 仍是
        `code/formal/<声明名>.lean`（逐字不变），`#p2` 起是
        `code/formal/<声明名>__p<n>.lean`（不然第二条会把第一条覆盖掉）。
        """
        # ---- 第 0 道闸：`path_source` 是受控三值（业主补裁：「只是在标记和五元位更新时
        # 要忠实」）。空串是"没交代"，不是第四个取值 —— 三态纪律：不许替调用方编一个来源。
        wanted_source = str(path_source or "").strip()
        if wanted_source and wanted_source not in PATH_SOURCES:
            return self._formal_attach(
                self._refusal(
                    claim, "param_error",
                    f"path_source={path_source!r} 不在受控取值里（{list(PATH_SOURCES)}；"
                    "空 = 没交代）。它记的是「这个路径是谁选的」，"
                    "与「谁验的」（这一行的 recorded_by = L）是两个读数，不许混填"),
                name="", written=False)
        text = normalize_source(source if source is not None else "")
        if not text.strip():
            return self._formal_attach(
                self._refusal(claim, "param_error", "source 是空的：没有源码就没有形式化"),
                name="", written=False)
        if not _HAS_DECL_RX.search(text):
            return self._formal_attach(
                self._refusal(
                    claim, "param_error",
                    "源码里没有具名的 theorem / lemma —— 这不是一份形式化源码"
                    "（写一句 `theorem <名字> : <命题> := <证明>` 再来）"),
                name="", written=False)
        given = str(declaration_name or "").strip()
        if given and not _QUALIFIED_RX.match(given):
            return self._formal_attach(
                self._refusal(
                    claim, "param_error",
                    f"声明名 {given!r} 不是合法的 Lean 名字"
                    f"（要求匹配 {_QUALIFIED_RX.pattern}）"),
                name="", written=False)
        derived = declaration_name_in(text)
        if not given and not derived:
            return self._formal_attach(
                self._refusal(
                    claim, "param_error",
                    "取不到声明名：源码里的 theorem / lemma 没有名字，且没给 declaration_name"),
                name="", written=False)
        checker = _checker_name(given, derived)
        stem = checker.rsplit(".", 1)[-1]
        if not DECLARATION_NAME_RX.match(stem):
            return self._formal_attach(
                self._refusal(
                    claim, "param_error",
                    f"声明名的最后一段 {stem!r} 不能当文件名"
                    f"（要求匹配 {DECLARATION_NAME_RX.pattern}）"),
                name=stem, written=False)

        # ---- 忠实复述的第一道闸：先钉住"被形式化的是 B 的哪一条"，再写盘。
        # 位置刻意在所有写操作之前：被拒时盘上不许出现新 .lean / 新 .steps.jsonl。
        picked = self._pick_statement(claim=claim, statement_id=statement_id,
                                      proof_no=proof_no)
        if not picked.get("ok"):
            lost = _library_reading(stmt_id=str(picked.get("statement_id") or ""),
                                    row={}, proof_text="")
            return self._with_report(
                self._formal_attach(
                    self._refusal(claim, str(picked["reason"]), str(picked["detail"])),
                    name=stem, written=False,
                    extra={"statement_id": str(picked.get("statement_id") or ""),
                           "refused": True, "b_library": lost}),
                coverage={}, b_library=lost)

        stmt_id = str(picked.get("statement_id") or "")
        stmt_source = str(picked.get("source") or "")
        # ---- 第二道闸：这一趟验的是哪一份证明（业主 2026-10-22 的裁定）。
        # 位置与上面那道闸一样，在所有写操作之前：多路径未给号时盘上不许出现新文件。
        chosen = _path_choice(picked, proof_no=proof_no)
        if not chosen.get("ok"):
            return self._with_report(
                self._formal_attach(
                    self._refusal(claim, str(chosen["reason"]), str(chosen["detail"])),
                    name=stem, written=False,
                    extra={"statement_id": stmt_id, "statement_source": stmt_source,
                           "refused": True, "path_source": wanted_source,
                           "b_library": _library_reading(stmt_id=stmt_id, row=picked,
                                                         proof_text="")}),
                coverage={}, b_library=_library_reading(stmt_id=stmt_id, row=picked,
                                                        proof_text=""))
        path_no = int(chosen["proof_no"])
        proof_text = str(chosen.get("proof_text") or "")
        #: 这一份正文的指纹：`record` 把它写进 `experiments.observations.proof_sha256`，
        #: 读侧拿它与现行正文比 —— 不符就是"验过、过期了"（`evidencebits` 的 stale）。
        proof_sha256 = _VR.proof_sha(proof_text)
        #: 落盘名跟着证明号走：`#p1` 逐字不变（`code/formal/<声明名>.lean`），
        #: `#p2` 起加 `__p<n>` —— 不加就等于第二条覆盖第一条（`#p1` 的产物被静默换掉）。
        suffix = "" if path_no == 1 else f"__p{path_no}"
        file_stem = f"{stem}{suffix}"
        #: 每条分支都要带的路径四格（见 `FAITHFULNESS_KEYS`）。
        path_extra = {"proof_no": path_no, "proof_sha256": proof_sha256,
                      "path_source": wanted_source}
        b_library = _library_reading(stmt_id=stmt_id, row=picked, proof_text=proof_text)
        reading = self._faithfulness_reading(proof_text=proof_text, source=text)
        coverage = dict(reading.get("coverage") or {})
        coverage["statement_id"] = stmt_id
        coverage["statement_source"] = stmt_source
        # `b_library` 同时进 coverage（`formalize` 的返回值里那一格是它的一份拷贝）：
        # 这一趟"读的是 B 的哪一条、多大、几步"在汇总读数里也读得到。
        coverage["b_library"] = dict(b_library)
        # `verdict` / `why` 读 `statement_source`（`no_ledger` 那一档是 unknown），
        # 所以它必须在来源钉住之后重算一次 —— 早算一次会让 no_ledger 读成 complete。
        coverage["verdict"] = _verdict(coverage)
        coverage["why"] = _verdict_why(coverage)

        rel = f"{FORMAL_DIR}/{file_stem}.lean"
        try:
            target = self._resolve(rel)
        except ExperimentError as exc:
            return self._with_report(
                self._formal_attach(
                    self._refusal(claim, "path_outside_workspace", str(exc)),
                    name=file_stem, written=False,
                    extra={"statement_id": stmt_id, "statement_source": stmt_source,
                           "coverage": coverage, "faithfulness": _verdict(coverage),
                           "b_library": b_library, **path_extra}),
                coverage=coverage, b_library=b_library)
        payload = text.encode("utf-8")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        except OSError as exc:
            return self._with_report(
                self._formal_attach(
                    self._refusal(
                        claim, "tool_failed",
                        f"写不出 {rel}（{type(exc).__name__}: {exc}）⇒ 这次没有落盘，也没有查"),
                    name=file_stem, written=False,
                    extra={"statement_id": stmt_id, "statement_source": stmt_source,
                           "coverage": coverage, "faithfulness": _verdict(coverage),
                           "b_library": b_library, **path_extra}),
                coverage=coverage, b_library=b_library)
        self._log("formalize wrote",
                  **{"path": rel, "sha256": sha256_of_bytes(payload), "bytes": len(payload)})

        # ---- 逐步对照落盘（与 .lean 同目录、同名字干）
        steps_rel = ""
        rows = list(reading.get("rows") or [])
        if rows:
            steps_rel = f"{FORMAL_DIR}/{file_stem}.steps.jsonl"
            try:
                steps_target = self._resolve(steps_rel)
                steps_target.write_bytes(_jsonl_bytes(rows))
            except (ExperimentError, OSError) as exc:
                return self._with_report(
                    self._formal_attach(
                        self._refusal(
                            claim, "tool_failed",
                            f"{rel} 已落盘，但逐步对照 {steps_rel} 写不出来"
                            f"（{type(exc).__name__}: {exc}）⇒ 这一趟没有可核的对照表"),
                        name=file_stem, checker=checker, payload=payload,
                        extra={"statement_id": stmt_id, "statement_source": stmt_source,
                               "coverage": coverage, "faithfulness": _verdict(coverage),
                               "b_library": b_library, **path_extra}),
                    coverage=coverage, b_library=b_library)

        # ---- 自检闸：不是 usable 就不去问检查器（不 spawn、不重试、不抛栈）
        state, why = self._lean_selfcheck()
        if state != "usable":
            out = self._refusal(claim, self._selfcheck_reason(state), one_line(why))
            out["problems"] = [one_line(why)]
            return self._with_report(
                self._formal_attach(
                    out, name=file_stem, checker=checker, payload=payload,
                    extra={"statement_id": stmt_id, "statement_source": stmt_source,
                           "coverage": coverage, "faithfulness": _verdict(coverage),
                           "steps_path": steps_rel, "b_library": b_library, **path_extra}),
                coverage=coverage, b_library=b_library)

        out = dict(self.check_formal(
            claim,
            script_path=rel,
            declaration_name=checker,
            imports=imports,
            timeout_sec=timeout_sec,
        ))
        # 检查器的读数先原样留在 checker_* 两格里，再让忠实复述的硬规则去盖 status。
        #
        # 盖的边界（两类理由的强度不同，所以处置不同）：
        # - `faithfulness_sorry`：检查器这一趟要么说通过、要么说 uses_sorry（那是"这份
        #   证明里有洞"，不是"命题可疑"）⇒ 两档都盖成 unknown，因为含 sorry 的文件
        #   照样编译通过，把它读成通过就是我们要防的那件事；
        # - 其余（漏步 / 多标步）：只盖 `verified`。检查器已经说 failed 时不动它 ——
        #   硬规则说的是"不许 verified"，而"我们写的那份源码编译不过"这条读数比
        #   逐步对照更强，抹掉它等于让读者以为命题没问题。
        out["checker_status"] = str(out.get("status") or "")
        out["checker_reason"] = str(out.get("reason") or "")
        gate = coverage_reason(coverage)
        status = str(out.get("status"))
        should_cover = (status == "verified"
                        or (gate == "faithfulness_sorry" and status == "failed"))
        if gate and should_cover:
            out["status"] = "unknown"
            out["reason"] = gate
            detail = _coverage_detail(gate, coverage)
            out["detail"] = detail
            out["problems"] = [detail]
        return self._with_report(
            self._formal_attach(
                out, name=file_stem, checker=checker, payload=payload,
                extra={"statement_id": stmt_id, "statement_source": stmt_source,
                       "coverage": coverage, "faithfulness": _verdict(coverage),
                       "steps_path": steps_rel, "b_library": b_library, **path_extra}),
            coverage=coverage, b_library=b_library)

    # ------------------------------------------------------------ 命题台账
    def _pick_statement(self, *, claim: str, statement_id: str | None,
                        proof_no: Any = None) -> dict:
        """钉住"被形式化的是 B 登记的哪一条"；返回 `{ok, ...}`（不 ok 时带理由码）。

        三条来源，优先级见 :meth:`formalize` 的 docstring。刻意不在这里写盘：
        这条闸的全部结论都必须是"拒绝"或"某一行"，没有第三种。
        """
        sid = _normalize_statement_id(statement_id)
        try:
            rows = [dict(row) for row in self.store.rows("statements")]
        except Exception as exc:  # noqa: BLE001 - 读不出来是 unknown 的一档，不是"没有"
            return {
                "ok": False,
                "reason": "statement_ledger_unreadable",
                "detail": (f"`statements` 表读不出来（{type(exc).__name__}: {exc}）⇒"
                           " 钉不住被形式化的是哪一条：这次什么都不写、也不查"),
            }
        if sid:
            hit = next((row for row in rows
                        if _normalize_statement_id(row.get("stmt_id")) == sid), None)
            if hit is None:
                return {
                    "ok": False, "statement_id": sid,
                    "reason": "statement_not_found",
                    "detail": (f"`statements` 里没有 {sid} ⇒ 要形式化的那一行不存在"
                               f"（盘上登记了 {len(rows)} 行）。先请 B 登记，再来形式化"),
                }
            return _checked_row(hit, sid=sid, source="explicit", claim=claim,
                                proof_no=proof_no)

        # ---- 没给编号：只认一种可证明的来源 —— claim 与某一行的正文逐字相同且唯一
        want = _flat(claim)
        hits = [row for row in rows if _flat(_SB.body_of(row)) == want and want]
        if len(hits) == 1:
            return _checked_row(hits[0], source="claim_match", claim=claim,
                                proof_no=proof_no)
        if len(hits) > 1:
            ids = sorted(_normalize_statement_id(row.get("stmt_id")) for row in hits)
            return {
                "ok": False, "statement_id": "",
                "reason": "statement_id_ambiguous",
                "detail": (f"claim 与 {len(hits)} 行命题正文逐字相同（{ids}）⇒ 认不出是哪一条。"
                           "显式给 statement_id"),
            }
        if not rows:
            # 台账里一行命题都没有：这一趟没有可对照的原文。它不是"通过"，也不是"拒绝" ——
            # 忠实复述这一格是 unknown（见返回值的 faithfulness 那一格）。
            return {"ok": True, "statement_id": "", "source": "no_ledger",
                    "proof_text": "", "body": ""}
        return {
            "ok": False, "statement_id": "",
            "reason": "statement_not_found",
            "detail": ("没有 statement_id，且 claim 与台账里任何一行命题的正文都不是逐字相同"
                       f"（盘上 {len(rows)} 行）。要么显式给 statement_id，要么把 B 那一条的"
                       " statement_full 逐字当 claim 传进来 —— 转述过的 claim 认不出来源"),
        }

    # ------------------------------------------------------------ 逐步对照
    def _faithfulness_reading(self, *, proof_text: str, source: str) -> dict:
        """逐步对照的读数（`{coverage, rows}`）。

        刻意做成类上的一个方法：反真空那一条判据要 monkeypatch 的正是它
        （把读数钉成"恒 12/12" ⇒ 漏一步的那条判据必须变红）。
        """
        return faithfulness_reading(proof_text=proof_text, source=source)

    # ------------------------------------------------------------ 内部
    def _with_report(self, out: dict, *, coverage: Mapping[str, Any],
                     b_library: Mapping[str, Any]) -> dict:
        """把"要不要向 B 汇报"这一格补上（`formalize` 的每一条分支都过它）。

        为什么要一个方法而不是在五个 return 前面各写一遍：`report` 是
        `FAITHFULNESS_KEYS` 的一格 —— 少写一条分支，那条分支上就没有这个读数，
        而"缺键"在判据上是静默失效（与 `_formal_attach` 同一个理由）。
        """
        out["report"] = self._maybe_report_failure(
            out=out, coverage=coverage, b_library=b_library,
            statement_label=str((b_library or {}).get("label") or ""))
        return out

    def _formal_attach(self, out: dict, *, name: str, checker: str = "",
                       payload: bytes = b"", written: bool | None = None,
                       extra: Mapping[str, Any] | None = None) -> dict:
        """把"盘上那五格 + 忠实复述八格"补进任意一条分支（键集合因此处处成立）。"""
        rel = f"{FORMAL_DIR}/{name}.lean" if name and (payload or written) else ""
        out.setdefault("status", "unknown")
        for key, neutral in _NEUTRAL_FAITHFULNESS.items():
            out.setdefault(key, neutral() if callable(neutral) else neutral)
        out.update({
            "path": rel,
            "sha256": sha256_of_bytes(payload) if payload else "",
            "bytes": len(payload),
            "declaration_name": checker or name,
            "written": bool(payload) if written is None else bool(written),
        })
        if extra:
            out.update({k: v for k, v in dict(extra).items() if k in FAITHFULNESS_KEYS})
        return out


# ---------------------------------------------------------------- 命题台账的小工具
def _normalize_statement_id(value: Any) -> str:
    """命题编号的归一化：去空白、去 `stmt:` 前缀（B 的引用写法与盘上的编号是两件事）。"""
    text = str(value or "").strip()
    if text.lower().startswith("stmt:"):
        text = text.split(":", 1)[1].strip()
    return text


def _flat(text: Any) -> str:
    """逐字比较用的口径：只把连续空白压成一个空格，别的字符一个都不动。"""
    return " ".join(str(text or "").split())


def _path_choice(picked: Mapping[str, Any], *, proof_no: Any = None) -> dict[str, Any]:
    """这一趟形式化的是哪一份证明：`{ok, proof_no, proof_text, paths, reason, detail}`。

    判据（业主 2026-10-22：「lean 形式化需指明对哪个路径做了形式化验证」）：

    - 给了号：号必须是这条命题证明清单里的一个（`verifications.proof_list` 是唯一口径），
      否则 `proof_path_not_found`（含"号认不出"：`0` / `'abc'` / `'#p0'` 都算）；
    - 没给号：这条命题只有一份证明 ⇒ 就是它（存量行全是这种，不拒绝）；有两份及以上
      ⇒ `proof_path_unspecified`。这一档绝不默认 `#p1` —— 那会把"验了第 2 条"记成
      "验了第 1 条"，而第 4 位（二维）里两条路径的读数正好相反。

    `picked` 是 `_pick_statement` / `_checked_row` 的返回值；`no_ledger` 那一档没有
    `row`，按"一条证明都没有的命题"读（`proof_list({})` = `#p1` 空正文）。
    """
    row = dict(picked.get("row") or {})
    paths = [int(no) for no, _text in _VR.proof_list(row)]
    given = str(proof_no if proof_no is not None else "").strip()
    if given:
        no = _VR.as_proof_no(given)
        if no < 1 or no not in paths:
            return {
                "ok": False, "proof_no": no, "proof_text": "", "paths": paths,
                "reason": "proof_path_not_found",
                "detail": (f"证明号 {proof_no!r} 不在命题 "
                           f"{str(picked.get('statement_id') or '') or '（没有编号）'} 的证明清单里"
                           f"（在册的是 {paths}）⇒ 不知道要验哪一份；先请 B 登记那一份证明"
                           "（`register_statement` 的 proofs），再来形式化"),
            }
        return {"ok": True, "proof_no": no, "paths": paths,
                "proof_text": _VR.proof_text_of(row, no)}
    if len(paths) > 1:
        return {
            "ok": False, "proof_no": 0, "proof_text": "", "paths": paths,
            "reason": "proof_path_unspecified",
            "detail": (f"命题 {str(picked.get('statement_id') or '') or '（没有编号）'} 有 "
                       f"{len(paths)} 份证明（{paths}），而这一趟没说验哪一份 ⇒ "
                       "一个字节都不写。第 4 位是二维的（每条证明一格），"
                       "默认落到 #p1 会让另一条的读数反过来：显式给 proof_no"),
        }
    no = paths[0]
    return {"ok": True, "proof_no": no, "paths": paths,
            "proof_text": _VR.proof_text_of(row, no)}


def _checked_row(row: Mapping[str, Any], *, sid: str = "", source: str,
                 claim: str, proof_no: Any = None) -> dict:
    """把"这一行能不能当形式化的对象"逐格核完（正文 / claim / 路径 / 那一份的正文）。

    顺序即优先级：正文（没有可对照的原文）⇒ claim（不是这一条）⇒ 路径（不知道验哪一份）
    ⇒ 那一份证明的正文（那一份是空的）。前两条问"哪一条命题"，后两条问"哪一份证明" ——
    它们判的不是同一件事，所以各有一条理由码。
    """
    got_id = sid or _normalize_statement_id(row.get("stmt_id"))
    body = _SB.body_of(row)
    if not body.strip():
        return {
            "ok": False, "statement_id": got_id,
            "reason": "statement_without_body",
            "detail": (f"命题 {got_id} 没有正文（`statement_full` 与 `statement_text` 都是空的）"
                       " ⇒ 没有可对照的原文，这次什么都不写"),
        }
    want = _flat(claim)
    if want and want != _flat(body):
        return {
            "ok": False, "statement_id": got_id,
            "reason": "claim_mismatch",
            "detail": (f"claim 与命题 {got_id} 的正文不是同一句（盘上是 {_flat(body)[:60]!r}）"
                       " ⇒ 要形式化的不是这一条。把 B 的 statement_full 逐字当 claim 传进来"),
        }
    texts = {no: str(text or "") for no, text in _VR.proof_list(row)}
    if not any(text.strip() for text in texts.values()):
        return {
            "ok": False, "statement_id": got_id,
            "reason": "statement_without_proof",
            "detail": (f"命题 {got_id} 的证明清单里没有一份带正文（`proof_text` 与 "
                       f"`{_VR.PROOFS_KEY}` 都是空的）⇒ 没有证明链路可逐步对照"
                       "（概念行就是这样：它不参与证明这一档）。先请 B 登记证明，再来形式化"),
        }
    picked = {"ok": True, "statement_id": got_id, "source": source, "row": dict(row),
              "label": str(row.get("label") or ""), "body": body}
    chosen = _path_choice(picked, proof_no=proof_no)
    if not chosen.get("ok"):
        return {"ok": False, "statement_id": got_id,
                "reason": str(chosen["reason"]), "detail": str(chosen["detail"])}
    no = int(chosen["proof_no"])
    if not str(chosen.get("proof_text") or "").strip():
        return {
            "ok": False, "statement_id": got_id,
            "reason": "statement_without_proof",
            "detail": (f"命题 {got_id} 的第 {no} 份证明是空的（`proof_text` / "
                       f"`{_VR.PROOFS_KEY}` 里那一项都没有正文）⇒ 那一份没有可对照的证明链路。"
                       "要么验别的那一份（给 proof_no），要么先请 B 补这一份"),
        }
    return {**picked, "proof_no": no, "proof_text": str(chosen["proof_text"]),
            "paths": list(chosen.get("paths") or [])}


# ---------------------------------------------------------------- B 的定理证明库
def _library_reading(*, stmt_id: Any, row: Mapping[str, Any],
                     proof_text: Any) -> dict[str, Any]:
    """这一趟从 B 的定理证明库读到了什么（`b_library` 的唯一产出点）。

    四格读数（业主 2026-10-22 晚裁定："消费 B 的定理证明库"）：

    - `stmt_id`：被形式化的那一条在 `statements` 里的编号；
    - `label`：那一行的标题（人读的那一格；没有就是空串）；
    - `proof_chars`：`proof_text` 的字符数（"这一条证明有多大"）；
    - `dependency_steps`：依赖链的步数（与逐步对照同一个切分口径
      `split_proof_steps` —— 两处口径分家会让"12 步"有两种意思）。
    - `found`：这一趟真的读到了可用的那一条（有正文且有证明）没有。

    `found=False` 时前四格仍是空的但键都在：取不到库那条分支上也要能读
    "我要的是哪一条"（见 `formalize` 被拒时的那一支）。
    """
    proof = str(proof_text or "")
    return {
        "stmt_id": str(stmt_id or ""),
        "label": str((row or {}).get("label") or ""),
        "proof_chars": len(proof),
        "dependency_steps": len(split_proof_steps(proof)) if proof.strip() else 0,
        "found": bool(proof.strip()),
    }


# ---------------------------------------------------------------- 步骤切分
def split_proof_steps(proof_text: Any) -> list[str]:
    """把 `proof_text` 切成有序的几步（口径见模块 docstring 的"步骤切分口径"）。

    三种形态择一（空行 → 编号行 → 句末标点 → 整份算一步）：越前面的越可信，
    因为它越不依赖"作者有没有编号"这件我们无权要求的事。
    """
    text = normalize_source(str(proof_text or "")).strip()
    if not text:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n[ \t]*\n+", text)]
    paragraphs = [part for part in paragraphs if part]
    if len(paragraphs) >= 2:
        return paragraphs
    numbered = _split_by_numbering(text)
    if len(numbered) >= 2:
        return numbered
    sentences = [part.strip() for part in _SENTENCE_RX.split(text)]
    sentences = [part for part in sentences if part]
    if len(sentences) >= 2:
        return sentences
    return [text]


def _split_by_numbering(text: str) -> list[str]:
    """按编号行切（`1.` / `（1）` / `第 1 步`）；没有编号行时返回空清单。"""
    steps: list[list[str]] = []
    for line in text.split("\n"):
        if _NUMBERED_RX.match(line):
            steps.append([line.strip()])
        elif steps:
            steps[-1].append(line.strip())
    return ["\n".join(part).strip() for part in steps if "\n".join(part).strip()]


def step_quote(step_text: Any) -> str:
    """第 k 步的引文：`proof_text` 里那一步的前 `QUOTE_CHARS` 字（逐字截取，不改写）。"""
    return _flat(step_text)[:QUOTE_CHARS]


# ---------------------------------------------------------------- Lean 源码读数
def _strip_comments_and_strings(source: str) -> str:
    """把注释与字符串字面量换成空格（换行保留）—— 只为了让 `sorry` 判据不被注释骗。

    为什么要剥：`-- 不许用 sorry 堵住` 这样的注释会让"出现 sorry"这条读数恒真，
    而恒真的读数等于没有读数。字符串同理（`"sorry"` 不是一个洞）。
    """
    text = normalize_source(source or "")
    out: list[str] = []
    i = 0
    depth = 0
    size = len(text)
    while i < size:
        ch = text[i]
        two = text[i:i + 2]
        if depth:
            if two == "/-":
                depth += 1
                out.append("  ")
                i += 2
                continue
            if two == "-/":
                depth -= 1
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if two == "/-":
            depth = 1
            out.append("  ")
            i += 2
            continue
        if two == "--":
            stop = text.find("\n", i)
            stop = size if stop < 0 else stop
            out.append(" " * (stop - i))
            i = stop
            continue
        if ch == '"':
            out.append('"')
            i += 1
            while i < size:
                inner = text[i]
                if inner == "\\" and i + 1 < size:
                    out.append("  ")
                    i += 2
                    continue
                if inner == '"':
                    out.append('"')
                    i += 1
                    break
                out.append("\n" if inner == "\n" else " ")
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def lean_facts(source: Any) -> dict[str, Any]:
    """一份 Lean 源码里与"逐步对照"有关的读数（全部机械可数，不做语法解析）。

    返回 `line_count` / `step_markers`（步号 → 行号）/ `duplicate_markers` /
    `sorry_lines` / `definition_lines` / `assume_markers`。
    """
    text = normalize_source(source or "")
    lines = text.split("\n")
    markers: dict[int, int] = {}
    duplicates: list[dict[str, int]] = []
    assumes: list[dict[str, Any]] = []
    for number, raw in enumerate(lines, 1):
        step = _STEP_MARK_RX.match(raw)
        if step:
            key = int(step.group(1))
            if key in markers:
                duplicates.append({"proof_step": key, "lean_line": number})
            else:
                markers[key] = number
            continue
        assume = _ASSUME_MARK_RX.match(raw)
        if assume:
            assumes.append({"lean_line": number,
                            "text": one_line(assume.group(1), limit=120)})
    codes = _strip_comments_and_strings(text).split("\n")
    sorry_lines: list[int] = []
    definition_lines: list[int] = []
    for number, code in enumerate(codes, 1):
        if _SORRY_RX.search(code):
            sorry_lines.append(number)
        if _DEF_RX.match(code):
            definition_lines.append(number)
    return {
        "line_count": len(lines),
        "step_markers": markers,
        "duplicate_markers": duplicates,
        "sorry_lines": sorry_lines,
        "definition_lines": definition_lines,
        "assume_markers": assumes,
    }


def step_spans(markers: Mapping[int, int], *, last_line: int) -> dict[int, tuple[int, int]]:
    """步号 → `[起, 止]` 行号：从标记行到下一个标记行的前一行（最后一个到最后非空行）。"""
    ordered = sorted(((int(k), int(v)) for k, v in markers.items()), key=lambda kv: kv[1])
    spans: dict[int, tuple[int, int]] = {}
    for index, (step, start) in enumerate(ordered):
        end = (ordered[index + 1][1] - 1) if index + 1 < len(ordered) else int(last_line)
        spans[step] = (int(start), max(int(start), int(end)))
    return spans


def _last_content_line(source: str) -> int:
    """源码最后一行非空行的行号（从 1 数；空源码返回 1）。"""
    lines = normalize_source(source or "").split("\n")
    for number in range(len(lines), 0, -1):
        if lines[number - 1].strip():
            return number
    return 1


def faithfulness_reading(*, proof_text: Any, source: Any) -> dict[str, Any]:
    """逐步对照的读数：`{coverage, rows}`（实现本体；`_Formalize` 只是转调它）。

    `rows` 就是 `steps.jsonl` 的行（键集合 = `STEP_ROW_KEYS`）；
    `coverage` 是同一件事的汇总（键集合见模块 docstring）。
    """
    steps = split_proof_steps(proof_text)
    facts = lean_facts(source)
    markers = facts["step_markers"]
    spans = step_spans(markers, last_line=_last_content_line(str(source or "")))
    rows: list[dict[str, Any]] = []
    unmapped: list[int] = []
    counts = {key: 0 for key in HOW_VALUES}
    for index, step_text in enumerate(steps, 1):
        span = spans.get(index)
        if span is None:
            how = "未映射"
            lean_lines: list[int] = []
            unmapped.append(index)
        else:
            start, end = span
            has_def = any(start <= n <= end for n in facts["definition_lines"])
            has_assume = any(start <= int(item["lean_line"]) <= end
                             for item in facts["assume_markers"])
            how = "自足定义" if has_def else ("补假设" if has_assume else "直接对应")
            lean_lines = [start, end]
        counts[how] += 1
        rows.append({
            "proof_step": index,
            "quote": step_quote(step_text),
            "lean_lines": lean_lines,
            "how": how,
        })
    assumptions: list[dict[str, Any]] = []
    for item in facts["assume_markers"]:
        line = int(item["lean_line"])
        owner = next((step for step, (start, end) in sorted(spans.items())
                      if start <= line <= end), 0)
        assumptions.append({"proof_step": owner, "lean_line": line, "text": item["text"]})
    extra = sorted(step for step in markers if step < 1 or step > len(steps))
    total = len(steps)
    coverage = {
        "steps_total": total,
        "steps_mapped": total - len(unmapped),
        "unmapped": list(unmapped),
        "sorry_lines": list(facts["sorry_lines"]),
        "assumptions_added": assumptions,
        "extra_steps": extra,
        "duplicate_markers": list(facts["duplicate_markers"]),
        "how": dict(counts),
        "verdict": "",
        "why": "",
    }
    coverage["verdict"] = _verdict(coverage)
    coverage["why"] = _verdict_why(coverage)
    return {"coverage": coverage, "rows": rows}


def coverage_reason(coverage: Mapping[str, Any] | None) -> str:
    """coverage ⇒ 综合结论不许是 `verified` 的那条理由码（空串 = 没有拦的理由）。

    硬规则（业主 2026-10-22）：`steps_mapped < steps_total` 或出现 `sorry` ⇒ 只能是
    `unknown`。`extra_steps`（源码里标了台账没有的那一步）也是同一族：它是"编造落点"
    的形态，比"漏一步"更坏，所以一并拦下。
    """
    if not isinstance(coverage, Mapping) or not coverage:
        return ""
    if coverage.get("sorry_lines"):
        return "faithfulness_sorry"
    total = int(coverage.get("steps_total") or 0)
    mapped = int(coverage.get("steps_mapped") or 0)
    if mapped < total:
        return "faithfulness_incomplete"
    if coverage.get("extra_steps"):
        return "faithfulness_extra_steps"
    return ""


def _verdict(coverage: Mapping[str, Any]) -> str:
    """`faithfulness` 那一格的四档（与 `status` 是三件事，见模块 docstring）。"""
    if not coverage:
        return "unknown"
    if coverage.get("statement_source") == "no_ledger":
        return "unknown"
    if coverage.get("sorry_lines"):
        return "holes"
    if coverage_reason(coverage):
        return "incomplete"
    return "complete"


def _verdict_why(coverage: Mapping[str, Any]) -> str:
    """`coverage.why` 的一行人话（读者不该自己去拼理由）。"""
    if coverage.get("statement_source") == "no_ledger":
        return ("台账里一行命题都没有 ⇒ 这一趟没有可对照的 proof_text："
                "这一格是「没有对象」，不是「通过」")
    if coverage.get("sorry_lines"):
        return (f"源码第 {coverage['sorry_lines']} 行出现 sorry / admit ⇒"
                " 那不是证明（含 sorry 的文件照样编译通过）")
    if coverage.get("extra_steps"):
        return f"源码标了台账证明里没有的那几步 {coverage['extra_steps']} ⇒ 落点是编造的"
    unmapped = coverage.get("unmapped") or []
    if unmapped:
        total = int(coverage.get("steps_total") or 0)
        return (f"{len(unmapped)}/{total} 步在源码里找不到落点（缺第 {unmapped} 步）⇒"
                " 证明链路没有被完整复述")
    if int(coverage.get("steps_total") or 0) == 0:
        return "没有可切的步骤（proof_text 是空的）⇒ 这一格是「没有对象」"
    return ""


def _coverage_detail(reason: str, coverage: Mapping[str, Any]) -> str:
    """综合结论被压回 unknown 时的那一句（点名理由码、附上计数与人话）。"""
    total = int(coverage.get("steps_total") or 0)
    mapped = int(coverage.get("steps_mapped") or 0)
    return one_line(
        f"{reason}：逐步对照只接上 {mapped}/{total} 步；"
        f"未映射 {coverage.get('unmapped') or []}、"
        f"sorry 在第 {coverage.get('sorry_lines') or []} 行、"
        f"台账里没有的那几步 {coverage.get('extra_steps') or []}。"
        f"检查器那边的读数留在 checker_status / verifier_output 里 ——"
        f"「检查器说通过」与「这一趟算数」是两件事")


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """`steps.jsonl` 的字节（UTF-8、无 BOM、行尾 `\\n`；每行恰好 `STEP_ROW_KEYS` 四格）。

    `default=json_default`：这一行是步骤台账的落盘字节，`lean_lines` / `how` 今天是
    纯字符串，但它们是调用方给的 Mapping 里的值 —— 一旦有人把 `Path` 或 dataclass 塞进
    来，改前这里会抛 `TypeError` 并把整条形式化动作打断，而盘上留下的是一份写到一半的
    台账。纯 JSON 载荷不走 `default`，既有字节不变。
    """
    lines: list[str] = []
    for row in rows:
        shaped = {key: row.get(key) for key in STEP_ROW_KEYS}
        lines.append(json.dumps(shaped, ensure_ascii=False, sort_keys=True, default=json_default))
    return ("\n".join(lines) + "\n").encode("utf-8")


#: 每条分支上都要有的忠实复述格子的中性取值（`_formal_attach` 用它兜底）。
_NEUTRAL_FAITHFULNESS: dict[str, Any] = {
    "statement_id": "",
    "statement_source": "",
    "coverage": dict,
    "faithfulness": "unknown",
    "steps_path": "",
    "refused": False,
    "checker_status": "",
    "checker_reason": "",
    "b_library": dict,
    "report": dict,
    "proof_no": 0,
    "proof_sha256": "",
    "path_id": "",
    "path_source": "",
}

assert tuple(_NEUTRAL_FAITHFULNESS) == FAITHFULNESS_KEYS, (
    "兜底表与 FAITHFULNESS_KEYS 必须逐格相同 —— 少一格，那条分支上就没有这个读数")


def declaration_name_in(text: Any) -> str:
    """源码里第一条具名 `theorem` / `lemma` 的限定名（取不到返回空串）。

    为什么要算限定名：桥接层会往源码尾部追加 `#print axioms <名字>`，而 Lean 4 里
    `namespace LProbe` 之内的定理在文件作用域叫 `LProbe.<短名>` —— 只给短名时
    检查器报 `unknown constant`，一条真定理会被记成 `compile_error`（真机读数，
    2026-10-22）。这里用"命名空间栈"把前缀拼出来；它刻意不做 Lean 语法解析：
    认 `namespace` / `section` / `end` 三种行，别的行一概不看（少认一种的后果是
    退回短名，而短名的行为与加这个函数之前逐字相同）。
    """
    body = normalize_source(str(text or ""))
    stack: list[str] = []
    pos = 0
    while pos < len(body):
        line_end = body.find("\n", pos)
        if line_end < 0:
            line_end = len(body)
        line = body[pos:line_end]
        ns = _NAMESPACE_RX.match(line)
        if ns:
            stack.extend(part for part in ns.group(1).split(".") if part)
            pos = line_end + 1
            continue
        if _SECTION_RX.match(line):
            stack.append("")
            pos = line_end + 1
            continue
        if _END_RX.match(line):
            if stack:
                stack.pop()
            pos = line_end + 1
            continue
        decl = _DECL_RX.match(line)
        if decl:
            prefix = [part for part in stack if part]
            return ".".join([*prefix, decl.group(1)])
        pos = line_end + 1
    return ""


def _checker_name(given: str, derived: str) -> str:
    """交给检查器的名字：给了全名就用它；给了短名而源码在命名空间里就升级成全名。"""
    if not given:
        return derived
    if "." in given:
        return given
    if derived and derived.rsplit(".", 1)[-1] == given:
        return derived
    return given


__all__ = [
    "B_LIBRARY_KEYS",
    "FAITHFULNESS_KEYS",
    "FAITHFULNESS_REASONS",
    "HOW_VALUES",
    "L_STATEMENT_AND_FAITHFULNESS_REASONS",
    "QUOTE_CHARS",
    "STATEMENT_REASONS",
    "STEP_ROW_KEYS",
    "coverage_reason",
    "declaration_name_in",
    "faithfulness_reading",
    "lean_facts",
    "split_proof_steps",
    "step_quote",
    "step_spans",
]
