# -*- coding: utf-8 -*-
"""命题同一性与同种证明的判据（纯函数、确定性、零模型调用）。

## 先读这一节：本模块现在管到哪一层（业主改口径；收两档）

业主逐字：「不用机械判据，让秘书洗定理名，让秘书判。」以及一句准绳：「定理描述一致
（什么条件推出什么结论），就是一个定理」。

所以"这两条是不是同一个定理"的终判不在本模块：它在
`secretary.Secretary.adjudicate_proposition`（一次模型调用，只回 same / different 两档；
判不了 = 没判成 `checked=False`，按正文 sha256 缓存判成了的那两档）。候选也不再由本模块
粗筛：秘书自己挑数学关键词 → 代码按关键词在 `statements` 里检索（`label` /
`statement_full` 归一后包含该词）→ 只把命中的那几条交给一次判定
（`Secretary.pick_statement_keywords` / `statementledger.by_keywords`）。本模块在那一层
的上游只做三件事：

| 层 | 在哪 | 做什么 | 不许做什么 |
|---|---|---|---|
| 终判 | `secretary.adjudicate_proposition` | 读条件与结论，判同一 / 不同，并洗出定理名 | 不许拿字符串相同当"同一" |
| 概念档 | 本模块 `same_concept` | 定义项（标签，或正文里的「概念（X）」/「定义（X）」）相同 ⇒ 同一个概念 | 不发模型调用（概念没有"条件 ⇒ 结论"） |
| 兜底 | 本模块 `proposition_key` / `same_proposition` | 只在秘书这一格没判成（没缝 / 开关关着 / 超时）时兜住旧口径 | 不许覆盖秘书给过的结论 |

最后一行是兜底口径（判据
`tests/test_secretary_recognizes_the_same_proposition.py` 钉着它），保留它是因为
"秘书没接上时整条写入路不许因此瘫掉"：那时它退成"一模一样才并"，比"什么都不并"更接近
真相。秘书一旦判了（`checked=True`），它说了算 —— 包括判 different；试过而没判成
（`attempted=True` + `checked=False`）不是第三种结论，上层按受控拒处置（不新建、不合并）；
没有判断面（没缝 / 开关关着）才退回这一档确定性兜底。

## 这一份回答的两个问题（业主的原话）

业主逐字：「我怕 B 的秘书看到对表述几乎相同的定理，不会有种意识它们是同一个，然后把
截然不同的证明并列记录（如果证明方式几乎相同，视为同种证明，可选：各取所长混合表述，
重拿 V 签）。」

两个问题必须分开判，因为它们的处置不同：

| 问题 | 判据 | 命中之后 |
|---|---|---|
| 这两条命题是不是同一条 | 秘书挑词 → 关键词检索 → 一次判定（`secretary.adjudicate_proposition`） | 不新建命题行，落成那条命题的另一条路径（一个稿号 = 一份文件 = 一份证明） |
| 同一命题下这两份证明是不是同一种证法 | `same_kind_proof` | 不新增路径号，受控拒绝 `proof_same_kind`（或 `merge=true` 合成一份并重拿 V 签）；判不了 ⇒ 受控拒 `proof_kind_unjudged` |

## 命题键（`proposition_key`）

一条定理的不同写法要落成同一个键。规范化六步（顺序固定，写在这里是因为"哪一步先做"
会改变结果）：

1. 上标先于 NFKC：`NFKC` 把 `pᵃ` 拆成 `pa`、把 `²` 拆成 `2`，上标信息就没了。所以先把
   上标字符映射成 `^a` 这种带 `^` 的写法，再做 NFKC（全角、兼容字符、希腊字母变体）。
2. 统一记号：`p^{a}` / `p^(a)` / `p^a` 一律 `p^a`；`∣` 与 `|` 一律 `|`；`≤` 与 `<=`
   一律 `<=`；`→` / `⇒` 一律 `->`；`−` / `–` / `—` 一律 `-`；LaTeX 的 `\\le` / `\\cdot`
   之类按同一张表换掉。这一条是"同一份数学内容的两种排版"。
3. 去编号与标签前缀：`定理 3.2：` / `Theorem 2.1.` / `[3]` / `(1.2)` / `1.2` 这类开头
   一律去掉（它们说的是"第几条"，不是"哪条定理"）。
4. 去行政尾注：`非平凡性素材` / `落点：` / `源文件` / `路线：` 这些是登记时附带给秘书
   判档的元数据，不是命题本体。只在这里切，不切正文里的数学内容（标记表是显式的、
   可审阅的，见 `_METADATA_MARKERS`）。
5. 去引导词：句首的 `设` / `若` / `则` / `故` / `令`，以及 `假设` / `于是` / `那么` /
   `因此` / `从而` 这类连接词。它们改变的是行文，不是命题。
6. 排序无关的集合化：按标点切成分句；每个分句里取 `拉丁词元 + 中文二元组` 作为记号，
   分句内记号排序、分句之间排序，拼成一个字符串。于是"条件在前 / 结论在前"两种写法
   得到同一个键。

第 6 步为什么用中文二元组而不是单字集合：单字集合会把 `常值` 与 `常数值` 判成同一个键
（`数` 在 `函数` 里已经出现过），而它们是两种写法 —— 二元组保留这一层区分，同时仍然
是排序无关的集合。

## 判不了 = 没判成（`judgeable`）

`proposition_key` 与 `prose_similarity` 对"判不了"的文本返回空串 / 0.0。两轴对它的表达
分成两种（业主逐字：「没有判不了」）：

- `same_proposition`（命题轴的确定性兜底）：仍返回 `state="unknown"` —— 它不归模型判，
  调用方（`statementfission` 的形态读数与 `_same_proposition_candidate` 的兜底）读的是
  这个三态里的"判不了"；那是命题轴的历史口径，本模块不改。
- `same_kind_proof` / `same_concept`：判不了 = 没判成（`checked=False`、`state=""`），
  不返回第三种结论。调用方据此 fail-closed（受控拒：不新增证明号 / 不新建概念行）；
  不许把它折成 `different`。

两轴"没判成"的口径（不按字数预判死）：

- `same_kind_proof`：不再看 `MIN_CONTENT_UNITS` —— 短证明照样判（"取 δ=ε 逐点验证"
  与"用有限覆盖"是两种证法，判得出）。只剩一种没判成：没有可比的文本（空串）。
  理由留在 `reason` 里。
- `same_concept`：从来不用 `MIN_CONTENT_UNITS`（它没有"文本长度"这一轴）；"没判成"
  是两侧都抽不出定义项（标签是空的、正文也不是「概念（X）」/「定义（X）」形态）。

`MIN_CONTENT_UNITS` 今天只剩一处用处：命题轴的确定性兜底（`judgeable`，被
`proposition_key` / `same_proposition` / `prose_similarity` 调用）。`x = 1` 与 `y = 1`
的词面相似度是 2/3，光看相似度会把两条不同断言判成"高度重合"——那一档仍是 `unknown`
（`statementfission` 的形态读数也依赖它），不在本件收两档的范围内。

## 相似度（兜底的那一档）

`prose_similarity` 与 `proof_similarity` 是同一套算法作用在不同文本上：中文按字 + 中文
二元组、拉丁按词，取"单字 Jaccard 与二元组 Jaccard 的均值"。键相同优先；键不同时它
兜住"表述高度重合"那一档（例如只多了一个词）。阈值是两个模块常量，可注入：

- `SAME_PROPOSITION_JACCARD = 0.85`：命题这一轴宁可不并 —— 把两条不同的定理并成一条，
  代价是一条真命题在台账上消失；漏并的代价只是多一条待人工合并的记录。
- `PROOF_SAME_JACCARD = 0.80`：证明这一轴略松，因为证明文本长、措辞波动大；同时命中
  之后不是静默丢，而是受控拒绝（拒信点名与第几份同种）或由调用方选择 `merge=true`
  合成一份并重拿 V 签 —— 两种处置都可逆。

## 概念同一性（`same_concept`）

一条 `kind="concept"` 的行没有"条件 ⇒ 结论"：它是一句定义。上面那一整套判据在它上面
等于失效（键比的是条件与结论的记号集合，两条把同一个术语定义了两遍的行会因此退化成
"不同"）—— 所以概念这一档另有一条判据，同样是纯函数：

| 依据 | 判什么 | `basis` |
|---|---|---|
| 定义项（标签） | 两侧的标签规范化后相同 | `concept_label` |
| 定义项（正文里的术语） | 正文开头「概念（X）」/「定义（X）」抽出的 X 相同 | `concept_defined_term` |

两档：两侧至少有一侧抽得出定义项、而两侧不相等 ⇒ `different`；定义项相同
⇒ `same`。两侧都抽不出（空标签、正文不是一句定义）⇒ 判不了 = 没判成
（`checked=False`、`state=""`）：调用方受控拒、不新建第二行。`checked=False` 不许折成
`different`（"判不了当不同"会让同一个概念还是被登记两行），也不许折成 `same`。

抽出来的定义项先去标点与空白再比：`有限维 Lie 代数` 与 `有限维Lie代数` 是同一个键，
`finite-dimensional Lie algebra` 与 `finite dimensional lie algebra` 也是。通用的那几个
词（`CONCEPT_GENERIC_TERMS`）不算定义项 —— 拿"概念"当键会把所有没命名的概念并成一条。

## 边界

- 纯函数：不读盘、不读 store、不写任何文件、不调模型；同样的入参永远同样的出参。
- 阈值是参数：`same_proposition(..., threshold=...)` / `same_kind_proof(..., threshold=...)`
  都收显式阈值；模块常量只是缺省值。
- 中文不分词：不引入分词器（那是另一份依赖，而且分词器的版本会让键漂移）。

## 判据

`tests/test_secretary_recognizes_the_same_proposition.py` 钉的是命题那一份的行为（键命中 /
相似度兜底 / 命题轴三态 / 同种证明 / 以及"把判据打桩之后调用方必须变红"的反真空）；
概念那一份（`same_concept`）钉在 `tests/test_one_concept_is_one_row.py`；两轴的"判不了 =
没判成 + 调用方受控拒"钉在 `tests/test_unjudged_axes_are_fail_closed.py`。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

#: 概念定义项的抽取住在概念行那一层（`conceptrows`：概念行的唯一读写口）；
#: 这里只回引两个 public 名字 —— `_concept_key_text` 与 `concept_keys` 读它们。
from .conceptrows import CONCEPT_GENERIC_TERMS, defined_term

#: 命题这一轴的阈值：键不同时，词面重合度到多少才算"同一条命题"。
#:
#: 0.85 这个数的来由（不是拍的）：命题的两种写法如果只差引导词、编号、记号排版，
#: 键就已经相同（走不到这一档）；走到这一档的是"多一个词 / 换一个同义词"那一类。
#: 同一命题的
#: 两种写法落在 0.86 以上，而两条不同的定理（哪怕同属一个主题）在 0.55 以下。
#: 取 0.85 意味着"宁可漏并，不许错并"：错并会让一条真命题在台账上消失。
SAME_PROPOSITION_JACCARD = 0.85

#: 证明这一轴的阈值：两份证明的词面重合度到多少才算同一种证法。
#:
#: 证明比命题长，措辞波动更大（同一套证法换个叙述顺序、换几句过渡），所以比命题轴
#: 松 0.05。命中的处置是可逆的（受控拒绝 / `merge=true` 合成并重拿 V 签），
#: 所以这里可以比命题轴更愿意报"同种"。
PROOF_SAME_JACCARD = 0.80

#: 命题轴"判不了"的下限：内容单元（拉丁词元 + 中文字）少于这个数 ⇒ `unknown`。
#:
#: 用途（只剩这一处）：命题轴的确定性兜底 —— `judgeable` 被
#: `proposition_key` / `same_proposition` / `prose_similarity` 调用。`x = 1` 与 `y = 1`
#: 的词面相似度是 2/3，光看相似度会把两条不同断言判成"高度重合"；太短的命题没有足够
#: 信息支撑任何结论，所以那一档仍走"判不了"（`unknown`），不是"不同"。
#:
#: 同种证明 / 概念同一性两轴不再用它（短证明照样判，见
#: `_judge` 的 docstring）。概念轴从来没用过它。
MIN_CONTENT_UNITS = 4

#: `same_proposition` / `same_kind_proof` 的三态取值。
#:
#: 只有这三个：`same`（判成同一个）、`different`（判成不同）、`unknown`（判不了）。
#: 调用方读 `state`；`basis` 说依据（键 / 相似度 / 空），`similarity` 给读数。
STATE_SAME = "same"
STATE_DIFFERENT = "different"
STATE_UNKNOWN = "unknown"

#: 命中的依据（进返回值与拒信，读的人要能分辨"凭什么并的"）。
BASIS_KEY = "proposition_key"
BASIS_SIMILARITY = "prose_similarity"
BASIS_PROOF_SIMILARITY = "proof_similarity"

#: 上标字符 -> 基字符。必须在 NFKC 之前做：NFKC 会把 `ᵃ` 直接折成 `a`，
#: 上标那一层信息就丢了（`p^a` 与 `pa` 于是不可分）。键里这两者不同：一个是幂，一个是词。
_SUPERSCRIPT = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6",
    "⁷": "7", "⁸": "8", "⁹": "9", "⁺": "+", "⁻": "-", "⁼": "=", "⁽": "(",
    "⁾": ")", "ⁿ": "n", "ⁱ": "i", "ᵃ": "a", "ᵇ": "b", "ᶜ": "c", "ᵈ": "d",
    "ᵉ": "e", "ᶠ": "f", "ᵍ": "g", "ʰ": "h", "ʲ": "j", "ᵏ": "k", "ˡ": "l",
    "ᵐ": "m", "ᵒ": "o", "ᵖ": "p", "ʳ": "r", "ˢ": "s", "ᵗ": "t", "ᵘ": "u",
    "ᵛ": "v", "ʷ": "w", "ˣ": "x", "ʸ": "y", "ᶻ": "z",
}
_SUPERSCRIPT_RUN = re.compile("[" + "".join(_SUPERSCRIPT) + "]+")

#: 记号变体 -> 统一写法。左边是"同一个数学意思的另一种排版"，右边是键里用的那一种。
_SYMBOLS = {
    "≤": "<=", "⩽": "<=", "≦": "<=", "≧": ">=", "⩾": ">=", "≥": ">=",
    "≠": "!=", "≡": "equiv", "∤": "notdiv", "∣": "|", "❘": "|", "｜": "|",
    "−": "-", "–": "-", "—": "-", "‐": "-", "‑": "-", "―": "-",
    "→": "->", "⇒": "->", "⟹": "->", "⇔": "<->", "⟺": "<->", "←": "<-",
    "∈": "in", "∉": "notin", "∀": "forall", "∃": "exists", "∅": "emptyset",
    "∩": "cap", "∪": "cup", "×": "*", "⋅": "*", "·": "*", "∙": "*",
    "⊆": "subset", "⊂": "subset", "⊇": "supset", "⊃": "supset",
    "∘": "circ", "⊕": "oplus", "⊗": "otimes", "∑": "sum", "∏": "prod",
    "∞": "infty", "∂": "partial", "√": "sqrt", "±": "+-", "∓": "-+",
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omicron", "π": "pi",
    "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi",
    "χ": "chi", "ψ": "psi", "ω": "omega", "Γ": "Gamma", "Δ": "Delta",
    "Θ": "Theta", "Λ": "Lambda", "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma",
    "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega",
}

#: LaTeX 命令 -> 统一写法（先换掉命令名，再走 `_SYMBOLS`，所以 `\\le` 与 `≤` 同一条路）。
_LATEX = {
    r"\le": "<=", r"\leq": "<=", r"\ge": ">=", r"\geq": ">=", r"\ne": "!=",
    r"\neq": "!=", r"\equiv": "equiv", r"\mid": "|", r"\in": "in",
    r"\notin": "notin", r"\to": "->", r"\rightarrow": "->",
    r"\Rightarrow": "->", r"\Leftrightarrow": "<->", r"\forall": "forall",
    r"\exists": "exists", r"\cap": "cap", r"\cup": "cup", r"\cdot": "*",
    r"\times": "*", r"\subseteq": "subset", r"\subset": "subset",
    r"\emptyset": "emptyset", r"\sum": "sum", r"\prod": "prod",
    r"\infty": "infty", r"\partial": "partial", r"\sqrt": "sqrt",
    r"\alpha": "alpha", r"\beta": "beta", r"\gamma": "gamma", r"\delta": "delta",
    r"\epsilon": "epsilon", r"\theta": "theta", r"\lambda": "lambda",
    r"\mu": "mu", r"\pi": "pi", r"\rho": "rho", r"\sigma": "sigma",
    r"\tau": "tau", r"\phi": "phi", r"\psi": "psi", r"\omega": "omega",
}

#: 编号与标签前缀（只认开头）。三条形态各自成组，命中就整段去掉：
#: 标签词 + 号、方/圆括号里的号、纯点号编号。
_LABEL = re.compile(
    r"^\s*(?:"
    # 标签词 + 号：定理 3.2 / Theorem 2.1. / Lemma A.1 / 命题 1
    r"(?:定理|引理|命题|推论|猜想|定义|注|例|lemma|theorem|proposition|corollary|"
    r"conjecture|definition|remark|example|thm|lem|prop|cor|def|notation)"
    r"\s*[\.\s:：]?\s*(?:[0-9]+(?:\.[0-9]+)*|[a-z]\.?\s*[0-9]+)?\s*[\.\s:：]?\s*"
    r"|"
    # 括号里的号：[3] / (1.2) / 【A.1】
    r"[\(\[（【]\s*(?:[0-9]+(?:\.[0-9]+)*|[a-z]\s*\.?\s*[0-9]+|[a-z])\s*[\)\]）】]"
    r"\s*[\.:：]?\s*"
    r"|"
    # 纯点号编号：1.2 / 3.4.1（至少要有一个点，否则 "3 是素数" 会被误削）
    r"[0-9]+(?:\.[0-9]+)+\s*[\.:：]?\s*"
    r")"
)

#: 切尾注时要看的"段落边界"：标记前两个字符里出现这些字符，才认为它另起一段。
#: 为什么必须要求边界：`另一条路线：先证引理…` 是证明正文的一种正常开头（"路线"两个字
#: 不是元数据），而 `…(mod p)。\n\n非平凡性素材：…` 才是登记时附带的元数据。没有这一条，
#: 任何以"路线/落点"起头的句子都会被腰斩。
_BOUNDARY = "\n。；;！!？?：: "
#: 行政尾注的起点（在这之前是命题本体，之后是登记时附带的元数据）。
_METADATA_MARKERS: tuple[str, ...] = (
    "非平凡性素材", "非平凡性", "供秘书判档", "给秘书", "落点：", "落点:",
    "源文件", "路线与可复用", "路线：", "路线:", "证明路线", "备注：", "备注:",
)

#: 连接词：句首出现的一律去掉（它们说的是行文，不是命题）。
_LEAD_GLUE: tuple[str, ...] = (
    "假设", "假定", "已知", "设", "若", "则", "故", "令", "且", "又", "即",
    "对于", "对", "任意", "于是", "那么", "因此", "从而", "可得", "并且", "而且",
)
#: 句中出现的多字连接词（去它们不会伤到数学内容：这些词在中文数学里只作过渡）。
_ANY_GLUE: tuple[str, ...] = (
    "假设", "假定", "于是", "那么", "因此", "从而", "可得", "并且", "而且", "使得",
    "一个", "这种", "那种", "本结论", "该结论",
)
#: 系词：`是` / `为` 在中文数学里是同一个意思，键里统一成 `是`。
_Copula = ("为", "是")

#: 分句标点（含数学里当逗号用的分号、顿号、换行）。
_CLAUSE_SPLIT = re.compile(r"[。；;，,、\n\r]+")
#: 拉丁词元（含 `p^a` / `n_p` / `3-正则` 的数字部分这类原子）。
_LATIN_ATOM = re.compile(r"[a-z][a-z0-9]*(?:[_^][a-z0-9]+)*|[0-9]+")
#: 拉丁短语里的二元组（同一个空白分句内相邻的两个拉丁词元）。
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_WS = re.compile(r"\s+")
#: 只折叠空白、保留换行的那一份：键要按分句切开再排序，换行是分句边界（见 `proposition_key`）。
_WS_KEEP_LINES = re.compile(r"[ \t\f\v\u00a0]+")


# ------------------------------------------------------------------ 规范化


def _superscripts(text: str) -> str:
    """上标字符 -> `^基字符`（必须早于 NFKC，理由见 `_SUPERSCRIPT`）。"""
    return _SUPERSCRIPT_RUN.sub(lambda m: "^" + "".join(_SUPERSCRIPT[c] for c in m.group(0)), text)


def _latex(text: str) -> str:
    """LaTeX 命令 -> 统一记号（先长命令后短命令，避免 `\\le` 吃掉 `\\leq`）。"""
    out = text
    for needle in sorted(_LATEX, key=len, reverse=True):
        out = out.replace(needle, _LATEX[needle])
    # `p^{a}` / `p^(a)` -> `p^a`；多字符的组保留成 `^(ab)` 这种带括号形态（不猜它是什么）
    out = re.sub(r"\^\s*\{\s*([^{}]{1,12})\s*\}", lambda m: "^" + m.group(1).strip(), out)
    out = re.sub(r"\^\s*\(\s*([^()]{1,12})\s*\)", lambda m: "^" + m.group(1).strip(), out)
    out = re.sub(r"_\s*\{\s*([^{}]{1,12})\s*\}", lambda m: "_" + m.group(1).strip(), out)
    return out


def _symbols(text: str) -> str:
    """统一记号变体（全角、连字符、集合符号、希腊字母的两种写法）。"""
    return "".join(_SYMBOLS.get(ch, ch) for ch in text)


def _main_claim(text: str) -> str:
    """切掉行政尾注：从最早一个"另起一段"的元数据标记处往后全部丢掉。

    为什么必须切：登记时 B 常把"路线 / 非平凡性素材 / 落点"附在 `statement_full` 后面
    （sylow3 的六条真数据都带）。判"是不是同一条命题"看的是命题本体，而尾注的长短
    与措辞会把相似度整体拉下去（同一命题的两条登记会因此判成不同）。
    怎么切：只认 `_METADATA_MARKERS` 里的显式标记，且标记之前两个字符里必须有段落边界
    （换行或句末标点）—— `另一条路线：先证引理…` 是证明正文，不是尾注。
    没命中任何标记 ⇒ 原样返回（不猜）。
    """
    out = str(text or "")
    cuts: list[int] = []
    for marker in _METADATA_MARKERS:
        start = out.find(marker)
        while start > 0:
            window = out[max(0, start - 2): start]
            if any(ch in window for ch in _BOUNDARY):
                cuts.append(start)
                break
            start = out.find(marker, start + 1)
    if not cuts:
        return out
    kept = out[: min(cuts)]
    # 切完只剩一小段 ⇒ 那不是"命题本体 + 尾注"，而是整段都在讲路线/落点：
    # 保留原文（宁可多带一点尾注，也不把命题本体整段丢掉）。
    return kept if len(kept.strip()) >= 6 else out


def _strip_label(text: str) -> str:
    """去掉开头的编号 / 标签前缀（可能连着两层，例如 `1.2 定理 3.2：`）。"""
    out = str(text or "")
    for _ in range(3):
        newer = _LABEL.sub("", out, count=1)
        if newer == out:
            break
        out = newer
    return out


def _canonical(text: str, *, strip_glue: bool) -> str:
    """一条文本的规范形态（`strip_glue` 决定去不去引导词，键与相似度各要一份）。"""
    out = _main_claim(text)
    out = _superscripts(out)
    out = unicodedata.normalize("NFKC", out)
    out = out.lower()
    out = _latex(out)
    out = _symbols(out)
    out = _strip_label(out)
    # 系词统一（`为` -> `是`）：这一条与去引导词无关，键与相似度都做 —— 否则
    # "G 为 p-群" 与 "G 是 p-群" 在相似度那一轴会被记成两种写法。
    out = out.replace(_Copula[0], _Copula[1])
    if strip_glue:
        clauses = []
        for raw in _CLAUSE_SPLIT.split(out):
            clause = raw
            for glue in _ANY_GLUE:
                clause = clause.replace(glue, " ")
            clause = clause.strip()
            for _ in range(4):
                stripped = clause
                for glue in _LEAD_GLUE:
                    if stripped.startswith(glue):
                        stripped = stripped[len(glue):].strip()
                if stripped == clause:
                    break
                clause = stripped
            if clause:
                clauses.append(clause)
        # 分句之间用换行留着边界：`proposition_key` 要按分句取记号集合再排序，
        # 一条定理的"条件在前 / 结论在前"两种写法才是同一个键。整段折叠成一行的话，
        # 拉丁词元的相邻二元组会跨过分句边界（"p 是素数，G 是群" 里 `p` 与 `g`
        # 会成一对），分句换序就不再是同一个键了。
        out = _WS_KEEP_LINES.sub(" ", "\n".join(clauses))
    else:
        out = _CLAUSE_SPLIT.sub(" ", out)
        out = _WS.sub(" ", out)
    return out.strip()


def _atoms(text: str) -> list[str]:
    """拉丁词元（按出现顺序）与中文连续段（按出现顺序），各自保留原来的先后。"""
    out: list[str] = []
    for m in re.finditer(_LATIN_ATOM.pattern + "|" + _CJK_RUN.pattern, text):
        out.append(m.group(0))
    return out


def _units(text: str, *, bigrams: bool) -> set[str]:
    """把规范形态切成记号集合。

    `bigrams=False`：拉丁词元 + 中文字（相似度的"单字"那一轴）；
    `bigrams=True`：拉丁词元 + 相邻拉丁词元的二元组 + 中文二元组（单字中文兜底）。
    中文不分词：不引入分词器（版本会让键漂移），用二元组是中文相似度的标准做法。
    """
    got: set[str] = set()
    # 记号只切一趟：`bigrams=True` 原先在算完中文之后又对同一段文本调一次 `_atoms`，
    # 只为了取拉丁词元的相邻对（同一个正则、同一份输入、同一个纯函数）。
    atoms = _atoms(text)
    for chunk in atoms:
        if _CJK_RUN.fullmatch(chunk):
            if len(chunk) == 1:
                got.add(chunk)
            elif bigrams:
                got.update(chunk[i: i + 2] for i in range(len(chunk) - 1))
            else:
                got.update(chunk)
        else:
            got.add(chunk)
    if bigrams:
        latin = [c for c in atoms if not _CJK_RUN.fullmatch(c)]
        for left, right in zip(latin, latin[1:]):
            got.add(left + " " + right)
    return got


def judgeable(text: str, *, minimum: int = MIN_CONTENT_UNITS) -> dict[str, Any]:
    """这段文本够不够格让判据给结论（三态里的"判不了"那一档的判据本体）。

    返回 `{"ok": bool, "units": n, "minimum": m, "reason": ""/"为什么判不了"}`。
    两档判不了：内容单元太少（`x = 1` 这种），或者一个中文/拉丁字母都没有
    （`≤ ≥ ≡` 这种纯符号）。两档的 `reason` 不同 —— "太短"可以补上下文，
    "纯符号"要补文字，处置不同。
    """
    # 空文本那一档在规范化之前就给答案（原来的顺序也是先算 units 再丢掉、返回 0）：
    # 规范形态只算一次：单元数（判"太短"）与"有没有文字"两档读的是同一份规范形态。
    if not str(text or "").strip():
        return {"ok": False, "units": 0, "minimum": int(minimum),
                "reason": "文本是空的（没有可比的内容）"}
    canonical = _canonical(text, strip_glue=False)
    units = len(_units(canonical, bigrams=False))
    minimum = int(minimum)
    if not re.search(r"[a-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", canonical):
        return {"ok": False, "units": units, "minimum": minimum,
                "reason": "全是符号与数字（没有一个可比的文字）"}
    if units < minimum:
        return {"ok": False, "units": units, "minimum": minimum,
                "reason": (f"文本太短（内容单元 {units} < {minimum}）⇒ "
                           "判不了，不许折成不同")}
    return {"ok": True, "units": units, "minimum": minimum, "reason": ""}


# ------------------------------------------------------------------ 命题键


def proposition_key(statement_full: str) -> str:
    """一条命题的确定性键（空串 = 判不了）。

    规范化见模块 docstring 的六步。键的形态是"按分句排序后拼起来的记号集合"，于是
    它有两个性质（这两条正是业主那句"表述几乎相同"要的）：
    - 条件与结论的先后、分句的先后都不影响键；
    - 编号 / 标签 / 引导词 / 记号排版的差异都不影响键。

    为什么返回可读字符串而不是哈希：键要能进拒信与返回值让人核对（"为什么并了"），
    而哈希只能给一个相等/不相等。可读键的长度在几十到几百字符，进 JSON 没有负担。
    """
    probe = judgeable(statement_full)
    if not probe["ok"]:
        return ""
    canonical = _canonical(statement_full, strip_glue=True)
    clause_keys: list[str] = []
    for clause in canonical.split("\n"):
        tokens = _units(clause, bigrams=True)
        if tokens:
            clause_keys.append(" ".join(sorted(tokens)))
    if not clause_keys:
        return ""
    return " || ".join(sorted(clause_keys))


def _jaccard(left: set[str], right: set[str]) -> float:
    """集合 Jaccard；两边都空 ⇒ 0.0（而不是 1.0：两个空集不构成"相同表述"）。"""
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _lexical_similarity(a: str, b: str) -> tuple[float, dict[str, Any]]:
    """词面相似度：单字那一轴与二元组那一轴的均值（两轴都空 ⇒ 0.0）。

    为什么取均值而不是最大值：最大值会让"词一样但语序/结构完全不同"的两段文本拿到
    接近 1 的分数（同一批字换一种说法就能骗过它）；均值要求两轴同时重合，才配得上
    "表述高度重合"这句话。
    """
    canon_a = _canonical(a, strip_glue=False)
    canon_b = _canonical(b, strip_glue=False)
    uni_a, uni_b = _units(canon_a, bigrams=False), _units(canon_b, bigrams=False)
    bi_a, bi_b = _units(canon_a, bigrams=True), _units(canon_b, bigrams=True)
    j_uni = _jaccard(uni_a, uni_b)
    j_bi = _jaccard(bi_a, bi_b)
    if not bi_a or not bi_b:
        score = j_uni
    elif not uni_a or not uni_b:
        score = j_bi
    else:
        score = 0.5 * j_uni + 0.5 * j_bi
    detail = {"unigram": round(j_uni, 4), "bigram": round(j_bi, 4),
              "n_unigram_a": len(uni_a), "n_unigram_b": len(uni_b),
              "n_bigram_a": len(bi_a), "n_bigram_b": len(bi_b)}
    return round(score, 4), detail


def prose_similarity(a: str, b: str) -> float:
    """两段命题表述的词面相似度，值域 [0, 1]（兜底那一档的判据本体）。

    键不同时用它判"表述高度重合"：`state` 由 `same_proposition` 决定，这里只给读数。
    两边有任意一边判不了（太短 / 纯符号）⇒ 0.0，由调用方走 `unknown` 那一档，不许
    把 0.0 直接读成"不同"。
    """
    if not judgeable(a)["ok"] or not judgeable(b)["ok"]:
        return 0.0
    return _lexical_similarity(a, b)[0]


def _judge(a: str, b: str, *, threshold: float, basis: str,
           what: str, unknown_is_unjudged: bool = False) -> dict[str, Any]:
    """两段文本的同一性判定（依据 + 读数 + `checked`），命题与证明共用这一处。

    `what` 只用于文案（"命题"/"证明"），不参与判据 —— 两轴的算法刻意是同一套，
    不同的只有阈值与命中之后的处置（处置在调用方，不在这里）。

    `unknown_is_unjudged`：判不了时怎么表达。`False`（命题轴）照旧 `state="unknown"`；
    `True`（证明轴）`checked=False` + `state=""` —— "判不了"不是第三种
    结论，是"没判成"。

    ## 两轴不按"内容单元 < `MIN_CONTENT_UNITS`"预判死
    短证明照样判："取 δ=ε 逐点验证"与"用有限覆盖"是两种证法，词面相似度判得出来。
    长度阈值只留给命题轴的确定性兜底（`same_proposition` / `proposition_key` /
    `prose_similarity`）。证明轴只剩一种"没判成"：没有可比的文本（空串）——
    那是没东西可判，不是字数不够。
    """
    left_probe, right_probe = judgeable(a), judgeable(b)
    out: dict[str, Any] = {
        "checked": False, "state": STATE_UNKNOWN, "basis": "", "similarity": 0.0,
        "key_a": "", "key_b": "", "detail": {}, "reason": "",
        "threshold": float(threshold), "what": what,
    }
    out["judgeable"] = {"a": left_probe, "b": right_probe}
    if unknown_is_unjudged:
        if not str(a or "").strip() or not str(b or "").strip():
            out.update(state="", reason=("判不了 = 没判成：至少一侧的证明正文是空的"
                                         "（没有可比的文本，不是字数不够）"))
            return out
    elif not left_probe["ok"] or not right_probe["ok"]:
        missing = [probe["reason"] for probe in (left_probe, right_probe) if not probe["ok"]]
        out["reason"] = (f"判不了：{'；'.join(missing)} ⇒ 不并、也不记成不同（三态纪律）")
        return out
    out["checked"] = True
    if basis == BASIS_KEY:
        key_a, key_b = proposition_key(a), proposition_key(b)
        out["key_a"], out["key_b"] = key_a, key_b
        if key_a and key_a == key_b:
            out.update(state=STATE_SAME, basis=BASIS_KEY, similarity=1.0,
                       reason="proposition_key 相同（编号 / 引导词 / 记号排版 / 分句顺序的差异已规范化掉）")
            return out
        score, detail = _lexical_similarity(a, b)
        out["similarity"], out["detail"] = score, detail
        if score >= float(threshold):
            out.update(state=STATE_SAME, basis=BASIS_SIMILARITY,
                       reason=(f"键不同，但词面相似度 {score:.4f} >= 阈值 {float(threshold):.2f}"
                               f"（单字 {detail['unigram']:.4f} / 二元组 {detail['bigram']:.4f}）"))
            return out
        out.update(state=STATE_DIFFERENT,
                   reason=(f"键不同、词面相似度 {score:.4f} < 阈值 {float(threshold):.2f}"))
        return out
    score, detail = _lexical_similarity(a, b)
    out["similarity"], out["detail"] = score, detail
    if score >= float(threshold):
        out.update(state=STATE_SAME, basis=BASIS_PROOF_SIMILARITY,
                   reason=(f"证明文本的词面相似度 {score:.4f} >= 阈值 {float(threshold):.2f}"
                           f"（单字 {detail['unigram']:.4f} / 二元组 {detail['bigram']:.4f}）"))
        return out
    out.update(state=STATE_DIFFERENT,
               reason=(f"证明文本的词面相似度 {score:.4f} < 阈值 {float(threshold):.2f}"))
    return out


def same_proposition(a: str, b: str, *,
                     threshold: float = SAME_PROPOSITION_JACCARD) -> dict[str, Any]:
    """两条命题表述是不是同一条（三态：same / different / unknown）。

    先比键，键不同再比词面相似度。返回值（调用方与拒信都读这一份，不各算一遍）：
    `checked` / `state` / `basis` / `similarity` / `key_a` / `key_b` / `detail` /
    `reason` / `threshold` / `judgeable`。
    `basis` 只有 `proposition_key`、`prose_similarity` 两档；`unknown` 时为空串。
    命题轴的"判不了"仍是第三态 `state="unknown"`（`checked=False`）：这一轴是确定性兜底，
    不在 "收两档"的范围内（理由见模块 docstring）。
    """
    return _judge(a, b, threshold=threshold, basis=BASIS_KEY, what="命题")


def proof_similarity(a: str, b: str) -> float:
    """两份证明的词面相似度，值域 [0, 1]（同种证明那一档的读数）。

    与 `prose_similarity` 同一套算法（"证明方式几乎相同"与"表述几乎相同"是同一类判断），
    刻意只差在阈值与调用点：两套算法会让"证明像不像"与"命题像不像"在两个尺度上，
    而读的人无从比较。
    """
    if not judgeable(a)["ok"] or not judgeable(b)["ok"]:
        return 0.0
    return _lexical_similarity(a, b)[0]


def same_kind_proof(a: str, b: str, *,
                    threshold: float = PROOF_SAME_JACCARD) -> dict[str, Any]:
    """两份证明是不是同一种证法（两档：same / different；没判成 = `checked=False`）。

    业主：「没有判不了」⇒ 判不了不是第三种结论，是 `checked=False`
    （`state=""`）；调用方据此 fail-closed（不新增证明号，受控拒
    `proof_kind_unjudged`）。

    ## 不按字数预判死
    短证明照样判：词面相似度判得出"取 δ=ε 逐点验证" ≠ "用有限覆盖"。所以这一轴
    不看 `MIN_CONTENT_UNITS`；`checked=False` 只剩"没有可比的文本"（空串）——
    那是没东西可判，不是字数不够。两种折平都不许：折成 different 会让同一种证法被
    并列记录；折成 same 会让一份真的另一种证法被拒。
    """
    return _judge(a, b, threshold=threshold, basis=BASIS_PROOF_SIMILARITY, what="证明",
                  unknown_is_unjudged=True)


# ------------------------------------------------------------------ 概念同一性


#: 概念那一档的两条依据（进返回值；读的人要能分辨"凭标签还是凭术语判的"）。
BASIS_CONCEPT_LABEL = "concept_label"
BASIS_CONCEPT_TERM = "concept_defined_term"


#: 定义项里不参与比较的记号（标点、空白、连字符）：`有限维 Lie 代数` 与
#: `有限维Lie代数` 是同一个术语的两种排版，`finite-dimensional` 与 `finite dimensional`
#: 也是。与 `proposition_key` 那条"记号排版不算差别"同一个口径。
_CONCEPT_KEY_DROP = re.compile(r"[\s\-_·/\\|,，、;；:：.。'\"“”‘’()（）\[\]【】]+")




def _concept_key_text(text: str) -> str:
    """一段术语 → 可比的定义项键（空串 = 这一侧抽不出可比的东西）。

    门槛只剩一道：通用词（`CONCEPT_GENERIC_TERMS`）不算定义项。

    不许按长度预判死：删掉"规范化之后不足两个字符的不算"。
    单字概念名（`群` / `环` / `谱`）是数学文献里最正常不过的东西；按字数把它判成
    "抽不出定义项"会让 fail-closed 把整个概念表堵死（只要有这么一行在册，之后每一条
    新概念都判不了）。通用词那条保留：拿"概念"当键会把所有没命名的概念并成一条，
    那比漏并更坏。
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    canonical = _canonical(raw, strip_glue=False)
    key = _CONCEPT_KEY_DROP.sub("", canonical)
    if key in CONCEPT_GENERIC_TERMS:
        return ""
    return key


def concept_keys(label: str, statement_full: str = "") -> dict[str, str]:
    """一条概念行的两个定义项键（`label` 那一格与正文里抽出的术语那一格）。

    两个都空 ⇒ 这一行判不了（不是"不同"）。为什么要两个而不是一个：标签与
    定义句各有可能缺席（标签是英文而定义句是中文、或者标签只写"概念"），只留一个键
    会把"这一侧读不出"错当成"两侧不一样"。
    """
    return {"label": _concept_key_text(label),
            "term": _concept_key_text(defined_term(statement_full))}


def same_concept(a_label: str, a_full: str = "", b_label: str = "",
                 b_full: str = "") -> dict[str, Any]:
    """同一概念的两条行是不是同一个概念（定义项相同；两档，确定性，零模型调用）。

    返回值（调用方与读数都读这一份）：
    `checked` / `state` / `basis` / `key_a` / `key_b` / `label_key_a` / `label_key_b` /
    `term_key_a` / `term_key_b` / `reason`。
    判据顺序固定：标签相同优先（它就是"定义项"的规范落点），其次正文里的术语。
    标签不同而术语相同 ⇒ 仍判 `same`（两行标签相同，但"标签改过一次、
    正文里的术语还是那个"的形态同样不该新建第二行）。

    两档：判得出 ⇒ `checked=True` + `state="same"/"different"`；
    两侧都抽不出定义项 ⇒ `checked=False` + `state=""`（没判成，调用方受控拒
    `concept_identity_unjudged`）。第三态 `unknown` 不再从这里出去。
    """
    left = concept_keys(a_label, a_full)
    right = concept_keys(b_label, b_full)
    out: dict[str, Any] = {
        "checked": False, "state": "", "basis": "", "key_a": "", "key_b": "",
        "label_key_a": left["label"], "label_key_b": right["label"],
        "term_key_a": left["term"], "term_key_b": right["term"],
        "reason": "",
    }
    if left["label"] and left["label"] == right["label"]:
        out.update(checked=True, state=STATE_SAME, basis=BASIS_CONCEPT_LABEL,
                   key_a=left["label"], key_b=right["label"],
                   reason=(f"定义项（标签）规范化后相同：{left['label']!r}"
                           " ⇒ 同一个概念，不许新建第二行"))
        return out
    if left["term"] and left["term"] == right["term"]:
        out.update(checked=True, state=STATE_SAME, basis=BASIS_CONCEPT_TERM,
                   key_a=left["term"], key_b=right["term"],
                   reason=(f"正文里被定义的术语相同：{left['term']!r}"
                           "（标签不同，但定义项是同一个）⇒ 同一个概念，不许新建第二行"))
        return out
    if (left["label"] or left["term"]) and (right["label"] or right["term"]):
        out.update(checked=True, state=STATE_DIFFERENT,
                   reason=(f"定义项不同（这一条 {left['label'] or left['term']!r} / "
                           f"在册那一条 {right['label'] or right['term']!r}）⇒ 两条概念"))
        return out
    missing = [name for name, side in (("这一条", left), ("在册那一条", right))
               if not (side["label"] or side["term"])]
    out["reason"] = (f"判不了 = 没判成：{'、'.join(missing)}抽不出定义项（标签是空的，正文也"
                     "不是一句「概念（X）」/「定义（X）」形态）⇒ 调用方受控拒、不新建第二行"
                     "（判不了不等于不同）。改法：把定义项写出来 —— 标签写具体术语，或正文"
                     "写成「概念（X）」/「定义（X）」；若它确实与在册某一条不同，写出不同的"
                     "定义项，判据会判 different 并照常新建")
    return out


def concept_similarity(a_label: str, a_full: str = "", b_label: str = "",
                       b_full: str = "") -> float:
    """概念这一档的读数：判成同一个概念是 1.0，其余（different / 没判成）是 0.0。

    只给"排个序、读个数"用，不参与判据 —— 判据只有 `same_concept` 一处，这里是它的
    读数投影（两处各算一遍判据是同一件事两个实现的老毛病）。
    """
    got = same_concept(a_label, a_full, b_label, b_full)
    return 1.0 if str(got.get("state") or "") == STATE_SAME else 0.0


def selftest() -> int:
    """自检：各条判据的最小形态（不读盘、不写盘）。返回 0 = 全过。"""
    a = "设 G 是 3-正则群；则弦长函数不是常值。"
    b = "假设 G 为 3-正则群，于是弦长函数不是常值。"
    c = "设 H 是有限群；则 H 的阶有限。"
    same = same_proposition(a, b)
    cross = same_proposition(a, c)
    proof_same = same_kind_proof("1. 由定义直接得到。\n2. 由 1 得结论。",
                                "1. 由定义直接得到。\n2. 由第 1 步得结论。")
    proof_cross = same_kind_proof("1. 由定义直接得到。\n2. 由 1 得结论。",
                                 "另一条路线：先证引理，再由引理得结论。")
    tiny = same_proposition("x = 1", "y = 1")
    same_concept_hit = same_concept("finite-dimensional Lie algebra",
                                   "概念（有限维 Lie 代数）：设 K 为特征 0 的域。",
                                   "finite-dimensional Lie algebra",
                                   "概念（有限维 Lie 代数）：设 K 为域。")
    two_concepts = same_concept("有限维李代数", "概念（有限维李代数）：dim < ∞。",
                                "幂零李代数", "概念（幂零李代数）：降中心列终止。")
    tiny_proof = same_kind_proof("显然。", "由定义。")
    empty_proof = same_kind_proof("", "由定义。")
    tiny_concept = same_concept("", "不是一句定义", "", "也不是一句定义")
    checks = [
        (proposition_key(a) == proposition_key(b), "同一命题的两种写法键相同", proposition_key(a)),
        (same["state"] == STATE_SAME, "同一命题判成 same", same),
        (cross["state"] == STATE_DIFFERENT, "无关命题判成 different", cross),
        (proof_same["state"] == STATE_SAME, "同种证明判成 same", proof_same),
        (proof_cross["state"] == STATE_DIFFERENT, "不同证明判成 different", proof_cross),
        (tiny["state"] == STATE_UNKNOWN, "命题轴太短的文本仍是 unknown（兜底口径）", tiny),
        (tiny_proof["checked"] is True and tiny_proof["state"] == STATE_DIFFERENT,
         "短证明照样判（不按字数预判死）", tiny_proof),
        (empty_proof["checked"] is False and empty_proof["state"] == "",
         "同种证明轴没有可比的文本 ⇒ checked=False / state=''", empty_proof),
        (same_concept_hit["state"] == STATE_SAME, "同一概念判成 same", same_concept_hit),
        (two_concepts["state"] == STATE_DIFFERENT, "两个概念判成 different", two_concepts),
        (tiny_concept["checked"] is False and tiny_concept["state"] == "",
         "概念轴判不了 ⇒ checked=False / state=''", tiny_concept),
    ]
    bad = [(ok, why, got) for ok, why, got in checks if not ok]
    for ok, why, got in bad:
        print(f"FAIL: {why} -> {got!r}")
    print(f"propositionkey selftest: {len(checks) - len(bad)}/{len(checks)} 条通过")
    return 0 if not bad else 1


if __name__ == "__main__":  # pragma: no cover - 手工自检入口
    raise SystemExit(selftest())
