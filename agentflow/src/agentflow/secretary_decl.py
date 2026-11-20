# -*- coding: utf-8 -*-
"""秘书的共享声明面：命题 / 档位 / 证明 / 概念这几个轴共用的键与形状（从 secretary.py 逐字搬出）。

我保证哪条不变式：一个跨模块共享的声明只定义一次，且它只依赖比它更低的那几层
（词表 `secretary_vocab` 与拒绝码 `refusals`）。判据面从这里 import 同一个键；
同一个键在两个模块里各写一遍，两份就会在没人改错的情况下慢慢分叉。

## 为什么需要这一层（刀3–刀6 的破环依据）

按 03 号文的模块地图往下切时，`secretary_tier_judge` / `secretary_tier_ledger` /
`secretary_identity` / `secretary_concept` / `secretary_statement` / `secretary_merge` /
`secretary_evidence` / `secretary_deps` / `secretary_label` 这九个模块之间有六组两两
互引（`temp/secsplit2/nodes_all.txt` 里逐条列出）：

    M07 <- M08  _judged_body_sha / _statement_sha / _tier_from_judge_reply
    M08 <- M07  NONTRIVIALITY_SCALE / NONTRIVIALITY_UNJUDGED
    M22 <- M27  PROOF_ROUTES_KEY
    M24 <- M25  STATEMENT_WRITE_TABLES
    M25 <- M29  STATEMENT_BITS_KEYS
    M25 <- M07  NOT_APPLICABLE_KINDS
    M22 <- M25  PROPOSITION_KINDS
    M24 <- M34  经 _is_concept_kind（概念种类判定，三个模块都要问）

每一组的箭头两端都是模块级名字（方法之间走 `self.`，不产生 import）。把它们里"本来
就是声明"的那几个提前抽成一个叶子，环上各方都从叶子 import，谁都不再从对方 import ——
依赖方向重新变成单向的 `secretary -> decl -> {vocab, refusals}`。

## 为什么这些名字能抽（不是"抓一把就搬"）

逐个核过闭包（`temp/secsplit2/leafplan.py`）：九个名字的传递闭包总共 15 行，且闭包
只落到 `secretary_vocab`（`CONCEPT_IDENTITY_KINDS`）与 `refusals`
（`EMPTY_STATEMENT_TEXT`）这两个更低的叶子。没有一个是"要用别的判据才能算出来"的读数，
所以抽出来不改变任何一条判断，也就没有"抽出来之后判据变成两份"的风险。

## 判据

`temp/secsplit2/bodies_all.py --check temp/secsplit2/bodies_precut2.json`：这九个名字
换了文件（moved），`ast_sha` 一个都不变（`CHANGED=0`）。
"""

from __future__ import annotations

from . import refusals as R
from .secretary_vocab import CONCEPT_IDENTITY_KINDS


#: "这一格没判成"的取值（三态里的第三态）。它不在 `NONTRIVIALITY_LEVELS` 里：
#:
#: `0` 是 T0（真的档位），不能再用它表示"没人判过"—— 两个意思折进同一个值，
#: 读的人会把"没人判过"读成"基础定理"。所以这一档是 `None`（JSON 里是 null）。
NONTRIVIALITY_UNJUDGED: None = None


#: 档位台账的刻度的标记（写在每一行里）。
#:
#: 为什么需要它：`out/secretary/nontriviality.jsonl` 是 append-only 的，改前那些行里
#: `nontriviality: 0` 的意思是"判不了"（那时 0 不是档位）。没有这个标记，读侧就会把
#: 历史行 0 读成 T0 —— 那是把"没人判过"冒充成一条基础定理。所以：
#: 有 `scale == NONTRIVIALITY_SCALE` 的行按新刻度读（0 = T0）；
#: 没有这一格的历史行按旧刻度读（0 = 判不了）。
NONTRIVIALITY_SCALE = "T0-T4"


#: 空命题正文的受控码（写侧 `register_statement` 与判档位这一侧共用一个字面量）。
#:
#: 为什么不是复用 `bad_statement`：那一个管的是"只有短版（statement_text）、没有含完整
#: 假设的正文"，这一档管的是"0 字"（连短版都没有）。两种输入的处置相同（整笔不写），
#: 但读数必须分得开 —— 前者是"你给错了栏"，后者是"没有可判的对象"。
#: 字面量的真身住在 `refusals.py`：同一句拒绝在写侧与判档位这一侧必须说同一个词。
EMPTY_STATEMENT_TEXT = R.EMPTY_STATEMENT_TEXT


#: 没有"证明正文"这一档、因而不做力气判档的那几档 kind（"不适用"的适用范围，唯一一处）。
#:
#: 为什么它与 :data:`CONCEPT_IDENTITY_KINDS` 分开住：那一格管"同一性按定义项
#: 判"（只有 `concept` 一档 —— `definition` 行的标签常常是空的，拿它当键会把一堆不相关的
#: 定义并到同一行），这一格管"有没有证明正文可判"（概念与定义都没有）。两件事折成一张表
#: 会让"并错了"与"判错了"互相牵制，而它们的处置完全不同：前者是多一行还是少一行，
#: 后者是多一档读数还是少一档读数。
NOT_APPLICABLE_KINDS: tuple[str, ...] = ("concept", "definition")


#: 证明的"路子"说明住在哪：行 JSON 里一个 `{证明号: 一句话}` 的字典。
#:
#: 路线写在证明这一层。它不能待在命题的 label 里 ——
#: 那条 label 是定理名（`Sylow 三定理`），带"（路线一：…）"之后，同一条定理的三种证法
#: 就成了三条不同的命题。所以：
#: 定理名归 label，路子归证明号（这一格），依赖的路径分组归 `Dependency.path_group`。
#: 键是证明号的字符串形式（JSON 的键只能是字符串），读侧一律走 :func:`proof_route_of`。
PROOF_ROUTES_KEY = "_proof_routes"


#: 秘书的写集（B 交内容、秘书落盘）。只有这两张表，
#: 且只经 `Secretary.record_statement` 一处 —— 声明与实现同一位。
STATEMENT_WRITE_TABLES: tuple[str, str] = ("statements", "dependencies")


#: 参与"同一命题"判定的 kind（命题性的那几档）。
#:
#: 为什么需要这一格：`Statement.kind` 刻意是自由文本（`schema.Statement` 的类 docstring
#: 写明"不参与任何判据分支"），于是"两条表述几乎相同的命题是同一个"这句话不能对所有
#: kind 都成立 —— 一条 `definition` 不是命题，把一条定理并进一条定义（或反过来）会让
#: 台账上少掉一整类条目，而"并了"这件事在盘上看起来完全合法。真机反例就在本仓的判据里：
#: `tests/test_agent_b_concept_registration_carries_kind.py` 用"同一条正文、只换
#: theorem / definition"核对五个位是否逐字相同 —— 那两条本来就该是两行。
#: 反过来，`theorem` 与 `lemma` 之间要能并：同一份东西在两篇文献里被叫成两种名字是常态，
#: 而那不是"两条命题"。
#: 认不出的 kind 一律不并（保守：并错一条的代价比漏并大）。
#:
#: `example`（玩具例子）也在这
#: 一张表里：它只是给人看的标签，处理与普通命题一致 —— 落稿 / 过形态闸 / 送 V /
#: 按五元位算等级，一条都不特殊。它进来是为了让"命题性的那几档"与"正文里能收进
#: `Example` 环境的那一档"是同一份名单：手稿头写 `- 命题类型：example`、B 收录时按它
#: 落 kind（`_declared_manuscript_kind` 只认这张表）。不是为 example 单开一个分支：
#: 这里加一个取值，`derive_grade` / `judge_proposition_form` / `verify_proof` 一个字不动。
PROPOSITION_KINDS: tuple[str, ...] = ("theorem", "lemma", "proposition", "corollary",
                                      "conjecture", "example")


#: `statements.bits` 一栏必须齐的 10 个键（写侧的唯一清单）。
#:
#: 现场（`temp/rmk90-audit/REPORT-R-mk-infinite-90-20261105.md` ② / A-3）：
#: `data/events.jsonl:3671`（20:54:32，`record_statement` sid=000019）写进去的
#: `bits` 是 `{}` —— 同一路径写其余 20 行都是这 10 键齐的 dict。于是 `statements`
#: 里 000019 的 `bits` 是空的（档位、等级全读不出来）。
#:
#: 根因不在 `bits` 的校验器（`schema.Statement.validate` 已经调
#: `evidencebits.bits_shape_problems`），而在「空表被当成没有形状问题」：
#: `bits_shape_problems({})` 返回 `[]` ⇒ 一条 `bits` 整块没填的行照样过闸。
#: 而 `_statement_from` 里那一格写的是 `dict(body.get("bits") or {})` —— 调用方
#: 没交 `bits` 时落盘的就是空表。B 那次走的是 `table.create`（`row` 里没有 `bits`），
#: 被路由到秘书的正路，于是"路由对了、内容少了一格"。
#:
#: 这张清单与 `evidencebits.bits_of` / `normalize_raw` 的产出逐键相同（那两份是
#: 构造器）；这里只在写侧回答"齐了没有"。
STATEMENT_BITS_KEYS: tuple[str, ...] = (
    "numeric", "proof", "reviewed", "formal", "audited",
    "origin", "evidence", "voided_by", "grade", "audited_badge",
)


def _is_concept_kind(kind: Any) -> bool:
    """这个 kind 算不算"概念行"（决定它走定义项那一档同一性判据）。"""
    return str(kind or "").strip().lower() in CONCEPT_IDENTITY_KINDS
