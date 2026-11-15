"""F 手稿里的依赖段：唯一解析点 ＋ 引用档位的唯一判据。

## 分工

    作者只写内容，登记由收方读稿产生（与 V 读 F 的手稿再签字同构）。所以：

- F 在证明手稿里写一节固定格式的依赖段（表格三列必填：引用 / 命题号 / 用在哪一步，
  见 :data:`COLUMN_KEYS`）；
- B 在入库时读那一节，落 `dependencies`（`used_by="stmt:<命题号>#pN"` ＋ `path_group`
  ＋ `source_stmt_id`）；F 自己不写依赖台账，也没有写台账的工具。

## 为什么格式必须固定

若证明正文是中文散文，秘书那条扫描只认
`stmt:` / `lit:` / `exp:` / `doc:` 四种前缀，散文里一条都扫不出来，而"扫不到"与"没有"
在读数上长得一样。固定表格把"作者心里的依赖"变成"机器读得动的一行"，缺列、坏号、
第几行读不懂都能逐行点名。

## 三条判据（本文件是它们的唯一实现，B 与 F 的只读预览都读它）

1. 解析：段标题 `## 依赖`，下面一张三列表（引用 / 命题号 / 用在哪一步）；缺表头 / 缺列 /
   列数不对 / 命题号形状不对 ⇒ 逐条进 `problems`（带行号与列名），调用方整笔受控拒绝。
   路径号不进稿（由 B 的秘书在收录事务里分配）⇒ 那一列可省；老盘带那一列的四列表仍读得回，
   只是路径号不是正整数同样进 `problems`；
2. 引用门槛（读等级）：来源那一行的可引资格只由
   `evidencebits.derive_grade` 现算的等级决定，`pre_theorem` 及以上才可引
   （= 有 V 签）。
   允许集合从等级序现算（:func:`citation_levels`），不写死字面量；等级算不出来 ⇒
   fail-closed。`statements.evidence_kind` 只是一列历史，判定面不再读它；
3. 三态读数（`present` / `missing` / `not_applicable`）：读数实现仍是秘书那一份
   （`secretary._deps_missing_reading`），本文件只负责把"手稿里有没有依赖段"这件事
   如实叠上去 —— 手稿没有段而证明正文里出现了 `stmt:` 引用，是 `missing`，不是 0。

## 边界

本文件不写任何表：B 落库那一步仍走 `Secretary.record_statement`（它有 `statements` 与
`dependencies` 两张表的写权），F 那一侧只有"写自己的手稿"和"只读预览"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import evidencebits as EB
from . import manuscriptfamily as _MFAM  # 手稿族/号/后缀的唯一判定表（T2）
from . import schema as S
from . import statementledger as SL   # 命题台账的查口（全表→索引的唯一实现）


#: 依赖段的段标题（固定，逐字）。
SECTION_HEADING = "## 依赖"

#: F 的证明手稿落点（工作区相对目录；唯一真身在 `manuscriptfamily.MANUSCRIPT_DIR`）。
MANUSCRIPT_DIR = _MFAM.MANUSCRIPT_DIR
#: 按命题号命名的那一种（登记取到号之后的名字；前缀从表派生）。
MANUSCRIPT_STMT_PREFIX = _MFAM.prefix_of("f-proof")
#: 按计划号命名的那一种（立项那一轮还没有命题号时用的是它，也是兜底读盘认的第二个名）。
#: `plan-<数字>` 是 f-proof 号形的一部分，所以它就是"命题号前缀 + plan-"。
MANUSCRIPT_PLAN_PREFIX = f"{MANUSCRIPT_STMT_PREFIX}plan-"

#: 手稿从哪来（四态，进返回值与读数，不许折平）：
#:
#: - `param`：调用方把正文递进来了（这一笔不必读盘）；
#: - `carried_by_D`：D 交研究手稿给 B 入库时把它一并带过来了（`## 携带的证明手稿` 那一节
#:   点名的落点，见 :func:`read_carried_manuscript`）—— 业主 2026-10-26 的原话是
#:   「是通过D传吗」，所以这条链上 D 是携带者、B 是收方，B 自己去盘上撞是兜底而不是主路；
#: - `disk`：前两处都没有，按约定路径在盘上真读到了 F 的稿（历史调用 / 直调的那一档）；
#: - `none`：三处都查过、一处都没有。
SOURCE_PARAM = "param"
SOURCE_CARRIED = "carried_by_D"
SOURCE_DISK = "disk"
SOURCE_NONE = "none"

#: `proof_text` 的来源（与上面那一组分开的一格读数）。
#:
#: 上面那四个说的是"这份稿从哪来"，这一个说的是"落进 `proof_text` 的正文是不是
#: 那份稿"。口径是：F 侧实际上是 D 侧，F 的东西都在 D 的手稿上记了一笔：
#: 主路是 B 按 D 的携带单寻址 → 取到稿正文 → 落成 `proof_text`（:data:`SOURCE_MANUSCRIPT`）。
#: `param` = 调用方直递的正文（它优先）；空串 = 这一笔没有正文要写。
SOURCE_MANUSCRIPT = "manuscript"

#: 二次寻址的三种形态（二次寻址必须是确定性工具，不许消耗 LLM 的 token）。
#:
#: | 值 | 什么时候 |
#: |---|---|
#: | `auto` | 由本模块的纯函数寻址（`read_carried_manuscript` / `read_manuscript`），零模型调用 |
#: | `model` | 寻址这一步被模型参与过（本仓的结构里不该出现；出现了要能读出来） |
#: | `unknown` | 这一趟没有寻址 / 没查成（不许折成「auto」） |
ADDRESS_MODES: tuple[str, ...] = ("auto", "model", "unknown")

#: 携带单点了名、而那个地址读不到 ⇒ 受控拒绝。
#:
#: 为什么它必须是拒绝而不是"降级去盘上自己找"：D 的清单是 B 的唯一寻址依据
#: （「B 侧需寻址获得 F 侧证明及 V 签」）。清单点名却读不到，说明清单与盘不一致
#: —— 那时换一条自己找的路，就是把"照单收录"换成了"猜一份稿"。
REFUSED_ADDRESS = "manuscript_address_unreadable"

#: D 的研究报告里那一节的段标题（携带单；逐字固定，渲染与解析共用一个常量）。
CARRIED_HEADING = "## 携带的证明手稿"
#: 携带单的列（命题号 / 手稿路径 / sha256 / 证明号）。
#: 携带单第一格认两种键：
#: `stmt:<命题号>`（F 的证明手稿，命题已在册）与 `exp:<实验号>`（E 的穷举证明手稿，
#: 命题可能还没进台账 —— 那条链里 E 从来没有命题号可用）。
#:
#: 为什么不是另开一张单：携带机制本来就只做三件事（键 → 地址 → 文件 sha256），
#: E 那一份与 F 那一份在这三件事上完全同形；差别只在"键是什么"。
#: 第二格是地址，读侧按它到盘上取文件并核 sha（`read_carried_manuscript`）。
#:
#: 第四格 `proof_no`：这一份的稿号（一个稿号 = 一份文件 = 一份证明）。
#: 交付里若没有这一格，调用方只能靠猜（canonical 空则 #p1 /
#: 否则最大号 + 1）。老行只有三格 ⇒ 读成 `#p1`（老数据的读数不变）；
#: 第四格留空同样读成 `#p1` —— "没写"与"写了 1"在稿号上是同一件事。
CARRIED_COLUMNS: tuple[str, ...] = ("命题号（stmt:NNNNNN / exp:NNNNNN / mss:<族>-<号>）",
                                    "手稿路径",
                                    "sha256", "证明号（#pN，可空）")

#: 携带单的最少列数（第四列 `proof_no` 是新增的可省略列：老行三列照读）。
CARRIED_MIN_COLUMNS = 3

#: 携带单第一格的前缀（`stmt:` 是命题号、`exp:` 是 E 的实验号、`mss:` 是稿号）。
#:
#: `mss:` 是第三档：F 的手稿登记条目先落盘、命题号由 B 在
#: V 签之后才发 ⇒ 那一轮 D 携带的是一份"还没有命题号"的 F 稿。它不能写 `stmt:`
#: （号不存在），也不能伪装成 `exp:`（那是 E 的实验），所以用稿做键；B 按正文 sha 认领。
#:
#: ## 稿的键带族（2026-11-16：与 `5ccb2041` 的「稿的身份 = (族, 稿号)」对齐）
#:
#: 写侧写 `mss:<族>-<号>`（`mss:f-proof-000000` / `mss:e-num-000000`），族名与
#: `manuscriptfamily.FAMILY_ORDER` 逐字相同、形状与 `refvocab` 的 `mss:<family>-<id>`
#: 同一形（携带单第一格与引用词表里写的是同一个东西）。
#:
#: 为什么必须带族：四族各有自己的号段、都从 `000000` 起（`manuscriptids` 的四条计数器）
#: ⇒ 同一号跨族在真机上是常态。单号做键时，`f-proof-000000` 与 `e-num-000000` 会被折成
#: 一行（`carried_manuscripts` 的 `seen` 把后到的那行当重列丢掉、索引里两族的稿只剩一份）
#: —— 携带单少一行，B 按清单寻址不到那一份，而读数与"那一份没签"同形。
#:
#: 老键 `mss:<号>`（2026-11-16 之前写的）仍读：族由载体路径定（`reports/f-proof-…`
#: 的族是 `f-proof`）。族认不出、或同一号在单上跨族出现 ⇒ 不猜，按调用点的三态语义
#: 受控拒/unknown，并在读数里点名「跨族同号、无法唯一定位」。键里的族与载体路径的族
#: 对不上 ⇒ 那一行读不懂（否则就是把另一族的稿读成这一份）。
CARRIED_KEYS: tuple[str, ...] = ("stmt:", "exp:", "mss:")

#: 证明正文那一节的段标题（预览时"引用了哪些 `stmt:`"只在这一节里数 —— 手稿开头的
#: 元信息（"命题号：stmt:000002"）不是引用，把它数进来会让读数虚高）。
SECTION_PROOF = "## 证明"

#: `## 证明` 那一节的三态读数。不许折成两态：
#:
#: | 值 | 什么时候 | 不许读成 |
#: |---|---|---|
#: | `present` | 稿里有这一节（`body` 是那一节的正文；这一节可能是空的） | —— |
#: | `absent` | 稿里没有这一节 | 「证明是空的」或者「整份稿就是证明」 |
#: | `unreadable` | 文件读不出来（不在盘上 / 权限 / 不是 UTF-8） | 「没有这一节」—— 没读到 ≠ 没有 |
#:
#: `unreadable` 只在读文件那一层出现（:func:`read_proof_body`）；:func:`proof_body_reading`
#: 拿到的已经是正文，只可能 `present` / `absent`。
PROOF_PRESENT = "present"
PROOF_ABSENT = "absent"
PROOF_UNREADABLE = "unreadable"

#: 命题正文那一节的段标题（V 只读手稿之后，命题正文从这一节来）。
SECTION_STATEMENT = "## 命题"

#: 表格的列：`(字段名, 认得出的关键词, 人读的列名)`。三列必填（引用 / 命题号 / 用在哪一步），
#: 路径号那一列可省 —— 它不进稿，由 B 的秘书在收录事务里分配（老盘带那一列的表仍读得回）。
#:
#: 识别按关键词（表头写"命题号（stmt:NNNNNN）"也认），但三列必填缺一不可、顺序不限 ——
#: 顺序不限不是放宽：缺哪一列会被点名，而"列数不对"同样进 `problems`。
COLUMN_KEYS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("quote", ("引用",), "引用（F 的原话）"),
    ("stmt_id", ("命题号", "stmt"), "命题号（stmt:NNNNNN）"),
    ("step", ("步",), "用在哪一步"),
    ("path_group", ("路径",), "路径号（第几条证明）"),
)

#: 引用门槛的那一档（「proof_review 级及以上才可引用」的落点）。
#:
#: 这是等级不是档位：`proof_review` 在新等级制里的对应值是
#: `pre_theorem`（= 有 V 签、但不是机器可核）。判据面一律读等级（业主裁定：
#: 「cross_check 等价于强猜想等价于有普通数值实验支撑的猜想……不妨就用等级制平替掉」），
#: 所以门槛写在 `EB.GRADES` 的坐标系里；档位词表只剩历史列。
CITATION_MIN_LEVEL = "pre_theorem"

#: 解析失败的受控码（B 那一侧据此整笔拒绝）。
REFUSED_SECTION = "dependency_section_unreadable"
#: 手稿没有 `## 依赖` 那一节、而证明正文引用了在册命题（整笔拒绝）。
REFUSED_SECTION_MISSING = "dependency_section_missing"
#: 来源不在册 / 不可用 / 档位读不到 / 档位不够，各一档受控码。
REFUSED_UNKNOWN_SOURCE = "dependency_source_not_registered"
REFUSED_SOURCE_STATUS = "dependency_source_not_usable"
REFUSED_LEVEL_UNREADABLE = "citation_level_unreadable"
REFUSED_LEVEL_TOO_LOW = "citation_below_proof_review"
#: 兜底审计（2026-10-27）：盘上那份 `reports/f-proof-*.md` 缺洗稿元信息 ⇒
#: 它不是框架渲染的产物（手写 / 换名绕过），整笔拒绝，请 F 用 `proof` 动作重写。
REFUSED_NOT_WASHED = "manuscript_not_washed"
#: 依赖段与证明正文对不上：`## 依赖` 那张表在、但 0 行数据，而证明正文
#: 点了在册命题的号 ⇒ 整份退回。改前这一形态两处都放行：`validate_manuscript` 只看
#: "那一节在不在"，B 的登记入口也只看 `present`；`deps_missing_reading` 虽然把它读成
#: "说不一致"，但那条读数不拦人（它此前只有 `why` 一句话）。
REFUSED_TABLE_DISAGREES = "deps_table_disagrees_with_proof"
#: 依赖段那一行"用在哪一步"与证明正文那一步的 `cites` 对不上（表述错误里的 b 类）。
#: 这个字面量此前只是两个调用点各写的，现在收成一个常量（值一个字不改）。
REFUSED_STEP_MISMATCH = "dependency_step_mismatch"

#: 引文与被引命题的原文对不上（表述错误里的 a 类：引错内容）。
#:
#: 为什么必须有一个专门的码（四元组口径）：b / c 两类已经各有
#: 受控码（:data:`REFUSED_STEP_MISMATCH` / :data:`REFUSED_TABLE_DISAGREES` 覆盖
#: "步号对不上"与"表与正文的引用集合不一致"），而"表里那一行的引文写的是另一条
#: 在册命题的原文"此前没有任何码 —— 它长得像 c（表里确实有一行），读的人会照着去改
#: 错的地方：该改的是号或引文，不是把行删掉。
#:
#: 判据面刻意保守（见 :func:`quote_mismatch_finding`）：只有能证明那段引文逐字
#: 属于另一条在册命题时才报。F 的渲染器把"这一步的原话"写进引文那一格，它本来
#: 就不等于被引命题的正文 —— 拿"不像"当判据会把每一份正常手稿都判红。
REFUSED_QUOTE_MISMATCH = "citation_quote_mismatch"

#: 引用面异常的四元组六格（机器形态：每格只回答一个问题）。
#:
#: | 格 | 回答什么 |
#: |---|---|
#: | `stmt_id` | 是哪一条引用（那个号） |
#: | `where` | 在哪一步 / 依赖表第几行 |
#: | `kind` | 是哪一类问题（受控码，见 :data:`CITATION_KIND_LABELS`） |
#: | `expected` | 期望什么 |
#: | `got` | 实际读到什么 |
#: | `fix` | 该怎么改（一句话可执行） |
#:
#: 缺一格就是读的人要多猜一次：没有号就只能重读整份稿，没有步骤就只能自己找，
#: 没有期望 / 实得就不知道差在哪，没有 `fix` 就只知道"有问题"而不知道下一步。
FINDING_CELLS: tuple[str, ...] = ("stmt_id", "where", "kind", "expected", "got", "fix")

#: 受控分类：受控码 → 报文里逐字出现的类别名（一码一名，不许互借）。
#:
#: "不许把两类混成一句（例如把『不在册』与『等级不到』写成
#: 同一句『依赖面有问题』）"。所以类别名按码固定，读的人据此知道该去登记、该去签、
#: 还是该改号；码本身也逐字进报文（机器读它）。
CITATION_KIND_LABELS: dict[str, str] = {
    REFUSED_UNKNOWN_SOURCE: "该条不存在（未在册）",
    REFUSED_SOURCE_STATUS: "该条不可用（状态不是 active）",
    REFUSED_LEVEL_UNREADABLE: "等级读不出来（判不了）",
    REFUSED_LEVEL_TOO_LOW: "等级不到可引门槛",
    REFUSED_TABLE_DISAGREES: "表述错误·表与正文的引用集合不一致",
    REFUSED_STEP_MISMATCH: "表述错误·步号对不上",
    REFUSED_QUOTE_MISMATCH: "表述错误·引文与被引命题的原文对不上",
    REFUSED_SECTION: "依赖段读不懂（格式不对）",
    REFUSED_SECTION_MISSING: "依赖段缺失（正文引了、手稿里没有这一节）",
}

#: `manuscript_not_washed` 的下一步。
#:
#: 为什么必须逐字写进报文：那句"请让 F 用 proof 动作重写"点的是一个不存在的
#: 动作 —— F 的动作表里只有 `create_plan` / `step` / `status` / `list_plans`
#: （`specs/f.py`），`proof` 只是 `step` 的一种产物。拿到那句话的调用方（D 或 F 自己）
#: 没有任何可执行的动作，于是 `projects/R-mk-infinite-90` 里同形状重交到 `attack-000016`
#:（15 轮）仍走不出去。
#:
#: 为什么"重交同一条路径"永远不行：洗稿元信息那一行只有 F 的秘书在一轮 proof 里盖得上
#: （`agent_f.core._wash_manuscript` → `depsection.mark_washed`）。把同一份手写稿的路径
#: 再交给 B，那一行没有谁补 —— 这不缺"再试一次"，缺的是换一条递送路径。
NOT_WASHED_NEXT_STEP = (
    "下一步（逐字）：只能让 F 用 `step` 动作重交这一轮 —— "
    '`framework_summon(role="F", action="step", params={"plan_id": "<这一轮的计划号>"})`；'
    "F 的那一轮会渲染手稿并由秘书盖 `- 依赖面洗稿：` 那一行，然后必须把正文递进来"
    "（`proof_manuscript=<正文>`）。不要只给路径：只给路径时那一行没有谁补，"
    "重交同一条路径还是这一拒。"
)


#: 框架渲染的手稿族（四族都算"框架产物"）：F 的证明稿 / B 的改写稿 /
#: E 的穷举证明稿 / E 的普通数值手稿。族名是"谁写的、要不要 V 签"在路径上的唯一区分。
#:
#: 前缀从 `manuscriptfamily.FAMILIES` 派生（设计 3.2 第 5 处），
#: 本模块不再保有自己的字符串；顺序按表的 `FAMILY_ORDER`。
MANUSCRIPT_FAMILY_PREFIXES: tuple[str, ...] = tuple(
    _MFAM.prefix_of(name) for name in _MFAM.FAMILY_ORDER)


def is_framework_manuscript(rel: Any) -> bool:
    """`rel` 是不是框架渲染的手稿（四族：`reports/{f,b}-proof-*` / `e-proof-*` / `e-num-*`）。

    判据只用一处定义（前缀与目录名都从本模块的常量读）：调用方拿它区分
    "这是框架约定的那份稿"与"别的文件" —— 兜底审计只在它是的那一档上生效。
    空串 / 非 `.md` / 不在 `reports/` 下 / 名字不带任何一族前缀 ⇒ False（宁可不动手）。

    2026-11-08（业主裁定）：E 的普通数值手稿 `reports/e-num-<实验号>.md` 也是框架渲染的
    —— 它必须与 `e-proof-*` 一样挡住手写（A/B 换个名字绕过那条口子）。要不要洗稿
    是另一件事（只有 F 的稿走 `- 依赖面洗稿：` 那一行，见 :func:`needs_wash`）。
    """
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) < 2 or parts[0].casefold() != MANUSCRIPT_DIR.casefold():
        return False
    name = parts[-1].casefold()
    if not name.endswith(".md"):
        return False
    return any(name.startswith(prefix) for prefix in MANUSCRIPT_FAMILY_PREFIXES)


def needs_wash(rel: Any) -> bool:
    """这份稿要不要 F 的秘书盖洗稿元信息（只有 F 的 `reports/f-proof-*` 要）。

    为什么 B / E 的稿不要：那一行元信息只有 F 的那一轮 proof 盖得上；拿同一道审计去拦
    E 的稿会把"框架渲染过的 e-proof / e-num"判成"手写稿"而整笔拒掉 ——
    而 E 那两族的作者与洗稿义务在 E 的写侧（`exhaustionreport`）。
    """
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) < 2 or parts[0].casefold() != MANUSCRIPT_DIR.casefold():
        return False
    return parts[-1].casefold().startswith(MANUSCRIPT_STMT_PREFIX)


def citation_levels() -> frozenset[str]:
    """`CITATION_MIN_LEVEL` 及以上那几档等级 —— 从等级序现算，不写死字面量。

    两处声明的交叉核对（缺一条就是"读错顺序也能过"）：

    - 等级序 `evidencebits.GRADES`（由弱到强：`conjecture` · `strong_conjecture` ·
      `pre_theorem` · `theorem`）—— 唯一的等级排序声明；
    - 档位只是历史列：`evidencebits.LEGACY_KINDS` 必须与 `schema.EVIDENCE_KINDS`
      互逆（两套词表的换算只有 :data:`evidencebits.GRADE_TO_KIND` 一处）。漂开就在
      导入期炸 —— 否则"档位若还出现只能由等级反算"这句话在代码里没有守卫。

    返回的集合从 `CITATION_MIN_LEVEL` 那一位切到最强端：今天是
    `{pre_theorem, theorem}`，但它是算出来的（换一档门槛会跟着变）。
    """
    ordered = tuple(EB.GRADES)
    declared = tuple(S.EVIDENCE_KINDS)
    legacy = tuple(EB.LEGACY_KINDS)
    assert legacy == tuple(reversed(declared)), (
        f"`evidencebits.LEGACY_KINDS`={legacy} 与 `schema.EVIDENCE_KINDS`={declared} "
        "不是互逆关系 ⇒ 档位反算表与历史词表漂开了（等级序必须只有一份定义）")
    assert CITATION_MIN_LEVEL in ordered, (
        f"引用门槛 {CITATION_MIN_LEVEL!r} 不在等级序 {ordered} 里 ⇒ 门槛切不出来")
    return frozenset(ordered[ordered.index(CITATION_MIN_LEVEL):])


#: 允许被引用的等级集合（导入期算一次；值来自 `citation_levels()`，不是手抄的列表）。
CITATION_LEVELS: frozenset[str] = citation_levels()


def statement_grade(row: Mapping[str, Any]) -> str:
    """一条 `statements` 行的等级 —— 唯一实现在这里（另一处是转发）。

    唯一入口是 `evidencebits.bits_from_row`（它内部现算 `derive_grade`，并做占位签 /
    旧稿 / 形式化过期那三档读侧降档）。空行 / 读不出来 ⇒ 空串（"判不了"），
    调用方必须 fail-closed —— 空串不是"最弱的猜想"。

    为什么落在这里：本模块是"可引门槛"的唯一定义点（`CITATION_MIN_LEVEL` /
    `citation_level_allowed`），而 `verifications` 已经依赖本模块（`import depsection`）。
    `verifications.statement_grade(root, row)` 只是同名的转发（`R003` 收掉两份实现的
    那一笔）：判据只有这一份，`root` 那一格在两处都必须给，但等级不从台账现读 ——
    它由 `bits` 现算（台账签只写第 3 位）。
    """
    try:
        return str(EB.bits_from_row(dict(row or {})).get("grade") or "")
    except Exception:  # noqa: BLE001 —— 算不出来要如实说，不许猜一档
        return ""


def citation_level_allowed(level: str) -> bool:
    """这一档等级够不够「pre_theorem 级及以上」（判据只有这一处，三条路径都读它）。

    空串 / 词表外的取值一律返回假：排不出等级的档位不许当成"合格"
    （三态纪律：读不到不是"查过了、够格"）。传历史档位词（`proof_review` 等）同样返回假
    —— 判定面只认等级；档位要走 `evidencebits.kind_from_grade` 先换算。
    """
    return str(level or "").strip() in CITATION_LEVELS


def citable_pool(statement_rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """可引池：`{命题号: 等级}`，只含在册（`status=active`）且等级 ≥ `pre_theorem` 的。

    「F 应该无法读到尚未在册的命题，特别地，F 只可引用
    proof review（或者说准定理级）及以上等级的命题」。于是"F 能读到什么"与
    "B / V 收稿时允许引什么"必须是同一张表（两处各算一份 ⇒ 一处宽一处严，而
    宽的那处会把一条读不到的引用记成依赖）：

    - `agent_f/manuscript._Manuscript.citable_statements` 用它算提示词里那份清单；
    - `gate_rows` / `dependency_review` 用它判正文与依赖表里点名的号能不能引；
    - B 的登记入口与 V 的依赖面审计吃的是同一个池子。

    不在册 / 非 `active` / 等级算不出来 / 等级不够 ⇒ 一律不在池子里（fail-closed：
    读不到不是"够格"）。
    """
    pool: dict[str, str] = {}
    for row in statement_rows:
        if str(row.get("status") or "").strip() != "active":
            continue
        level = statement_grade(row)
        if level and citation_level_allowed(level):
            pool[str(row.get("stmt_id") or "")] = level
    return pool


def _citation_where(*, step: Any = None, line: int = 0, site: str = "") -> str:
    """四元组里"哪一步"那一格：步号 / 表行 / 站点，能写几样就写几样。

    为什么要三样一起写：同一个异常可能同时有"表第几行"与"正文第几步"两个坐标
    （表里那一行说它用在第 2 步），只给一个的话，读的人还得自己把另一个找出来 ——
    而找错一步就是改错一处。
    """
    try:
        no = int(step) if str(step if step is not None else "").strip() else 0
    except (TypeError, ValueError):
        no = 0
    line_no = int(line or 0)
    site_text = str(site or "").strip()
    if line_no and no > 0:
        return f"依赖段第 {line_no} 行（表里写用在哪一步：第 {no} 步）"
    if line_no:
        return f"依赖段第 {line_no} 行"
    if no > 0 and site_text:
        return f"{site_text}第 {no} 步"
    if no > 0:
        return f"第 {no} 步"
    return f"{site_text}（未标步号的行）" if site_text else "（未标步号的行）"


def finding_sentence(record: Mapping[str, Any]) -> str:
    """一条引用面异常的人话：号 / 哪一步 / 哪一类 / 怎么改，四件都在同一句里。

    形如：

        `stmt:000008`（在哪一步：证明正文第 2 步）· 类别：等级不到可引门槛
        （`citation_below_proof_review`）· 期望：… · 实得：… · 怎么改：…

    为什么拼成一句而不是只给 dict：这一句会进拒信、V 的 `finding.detail`、
    洗稿打回的 `reason` —— 读它的人（提交证明者、D、F 的秘书）手里没有 dict，
    只有这句话。四个问句的答案缺一个，读的人就要多猜一次。
    """
    sid = str(record.get("stmt_id") or "")
    kind = str(record.get("kind") or "")
    label = CITATION_KIND_LABELS.get(kind, "引用面异常")
    head = f"`stmt:{sid}`" if sid else "（这一条没有可认的命题号）"
    return (
        f"{head}（在哪一步：{record.get('where')}）· 类别：{label}（`{kind}`）"
        f" · 期望：{record.get('expected')} · 实得：{record.get('got')}"
        f" · 怎么改：{record.get('fix')}"
    )


def citation_finding(*, stmt_id: str, where: str, kind: str, expected: str,
                     got: str, fix: str, step: Any = None) -> dict[str, Any]:
    """造一条六格齐全的引用面异常（`detail` 是 :func:`finding_sentence` 那句人话）。

    六格就是 :data:`FINDING_CELLS`；`step` 是给调用方排序 / 指 `defect_step` 用的
    整数步号（没有就 `None`，"没标步号"与"第 0 步"是两件事）。
    """
    no = step if isinstance(step, int) else None
    out: dict[str, Any] = {
        "stmt_id": str(stmt_id or ""),
        "where": str(where or "（未标步号的行）"),
        "kind": str(kind or ""),
        "expected": str(expected or ""),
        "got": str(got or ""),
        "fix": str(fix or ""),
        "step": no,
    }
    out["detail"] = finding_sentence(out)
    return out


def uncitable_statement_finding(
        sid: str, statement_rows: Iterable[Mapping[str, Any]] | None, *,
        where: str = "", line: int = 0, step: Any = None) -> dict[str, Any]:
    """`stmt:<sid>` 为什么不可引 ⇒ 六格；空字典 = 可引（在册 ∧ 等级够）。

    三态不折平：不在册 / 状态不可用 / 等级算不出来 / 等级不够，各有各的受控码与
    期望 / 实得 / 怎么改 —— 把它们折成一句"不够格"，读的人就不知道该去登记、
    该去签、还是该改号（业主 2026-11-06："不许把两类混成一句"）。

    不在册那一档的实得逐字带着「F 读不到它，这不是待接的悬空边」：那是业主那一句
    「F 应该无法读到尚未在册的命题」的落点，读的人据此知道该改号而不是去补一条边。

    `statement_rows=None` = 调用方手里没有台账（只拿得到可引集合）：这一档只报
    "不在可引池里"，不冒充知道原因（原因四档都要真读台账）。
    """
    site = str(where or "").strip()
    where_text = _citation_where(step=step, line=line, site=site or "依赖段")
    if statement_rows is None:
        return citation_finding(
            stmt_id=str(sid), where=where_text, kind=REFUSED_UNKNOWN_SOURCE,
            expected=(f"在册且等级 ≥ {CITATION_MIN_LEVEL}（这一层只拿得到可引池，"
                      "看不到每一条的状态与等级）"),
            got="不在这一轮的可引池里",
            fix=("核对号：把这一格换成 `attack.step` 返回值里本轮可引的 id；"
                 "若它本来就该在册，先让 B 登记、让 V 签，再来引"),
            step=step)
    index = SL.index_by_id(statement_rows)
    anchor = index.get(str(sid))
    if anchor is None:
        return citation_finding(
            stmt_id=str(sid), where=where_text, kind=REFUSED_UNKNOWN_SOURCE,
            expected="在册（只有已收录的命题才可引）",
            got=(f"不在册（台账里现有 {len(index)} 条命题）—— F 读不到它，"
                 "这不是待接的悬空边"),
            fix=("改号：把这一格的 `stmt:" + str(sid) + "` 换成台账里真实的一条在册命题号"
                 "（`attack.step` 的返回值里有本轮可引的 id 清单）；"
                 "若这一条本来就该在册，先让 B 登记它、再引"),
            step=step)
    status = str(anchor.get("status") or "").strip()
    if status != "active":
        return citation_finding(
            stmt_id=str(sid), where=where_text, kind=REFUSED_SOURCE_STATUS,
            expected="在册且 status=active（只有 active 才算已收录）",
            got=f"statements.status={status or '（空）'}",
            fix=("补登记：让 B 把这条命题重新登记成 active（或换一条已收录的号），"
                 "再来引"),
            step=step)
    level = statement_grade(anchor)
    if not level:
        return citation_finding(
            stmt_id=str(sid), where=where_text, kind=REFUSED_LEVEL_UNREADABLE,
            expected=f"{CITATION_MIN_LEVEL} 级及以上（要有 V 签）",
            got="等级算不出来（五元位读不出 / 现算出空）",
            fix=(f"先让它过签：让 V 走查签「成立」（或形式化 / 穷举核过）把它升到 "
                 f"{CITATION_MIN_LEVEL} 级，再引它"),
            step=step)
    if not citation_level_allowed(level):
        return citation_finding(
            stmt_id=str(sid), where=where_text, kind=REFUSED_LEVEL_TOO_LOW,
            expected=(f"门槛 {CITATION_MIN_LEVEL}（引用要求 {CITATION_MIN_LEVEL} "
                      "级及以上）"),
            got=f"等级 {level}",
            fix=(f"先让它过签：让 V 的逐行走审把它抬到 {CITATION_MIN_LEVEL} 级，"
                 "再来引它（或换一条已经够格的命题）"),
            step=step)
    return {}


def uncitable_statement_problem(
        sid: str, statement_rows: Iterable[Mapping[str, Any]] | None, *,
        where: str = "", line: int = 0, step: Any = None) -> tuple[str, str]:
    """`stmt:<sid>` 为什么不可引：`(受控码, 人话)`；空串对 = 可引（在册 ∧ 等级够）。

    这一层只是 :func:`uncitable_statement_finding` 的两格视图（旧调用方读的形态）；
    判据与六格只有一份实现 —— 两处各写一套才是"另一个人读到的理由不一样"。
    """
    got = uncitable_statement_finding(sid, statement_rows, where=where, line=line,
                                      step=step)
    if not got:
        return "", ""
    return str(got["kind"]), str(got["detail"])


def dep_kind_of(statement_kind: str) -> str:
    """来源那一行的 `statements.kind` 该记成哪一档 `schema.DEP_KINDS`。

    `Dependency.validate` 只认 `DEP_KINDS`，而 `Statement.kind` 是自由文本。
    落在表外的 kind 一律按 `theorem` 记 —— 保守方向：不把一条命题说成比它更弱或更强。
    """
    got = str(statement_kind or "").strip().lower()
    return {
        "theorem": "theorem",
        "lemma": "lemma",
        "proposition": "proposition",
        "corollary": "proposition",
        "definition": "definition",
        "concept": "definition",
        "conjecture": "proposition",
        "prior_art": "prior_art",
        "experiment": "experiment",
    }.get(got, "theorem")


# ------------------------------------------------------------------ 解析


def _cells(line: str) -> list[str]:
    """一行 Markdown 表格 ⇒ 逐格（去首尾空白；首尾的 `|` 不算格子）。"""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_separator(cells: Sequence[str]) -> bool:
    """Markdown 表的分隔行（`|---|:--:|`）。"""
    return bool(cells) and all(
        cell and set(cell) <= set("-: ") and "-" in cell for cell in cells)


#: 手稿里"节"的标题闭集 —— 框架渲染节名的单一来源。
#:
#: `depsection`（切节 / 形状读数）、`manuscriptform`（渲染与形状正则）、
#: `proofregistry`（分节哈希与"只换 `## 证明`"）三处都读这一张表；将来加节名
#: （例如"附录"）只改这一处，不改任何切节算法。
#:
#: ## 为什么层级规则之外还要这一张表
#:
#: 真实数学写作会在 `## 证明` 下面直接用 `## 记号与约定` / `## 第一步` 分小节 ——
#: 这与 `## 证明` 是同一级。只按"标题层级 ≤ 本节层级"判结束，正文仍会被截成
#: 空串；而 `## 依赖` 必须照旧是边界。两者只能靠"这一行是不是手稿的一节"区分：
#: 同级的已知节名才是下一节，同级的自由小标题算本节内容；更高级的标题（`# `）
#: 无论叫什么都是新的一节（手稿若用 `# 命题` 一级标题，`# ` 就是边界）。
#:
#: 末位的 `## 数值结果` 与 `exhaustionreport.NUMERIC_RESULT_HEADING` 是同一字面量
#: （那一侧是渲染、这一侧是解析；两侧互相 import 会成环，所以这里留字面并在此点名）。
SECTION_TITLES: tuple[str, ...] = (
    SECTION_STATEMENT, SECTION_PROOF, SECTION_HEADING, "## 数值结果")


def heading_level(line: str) -> int:
    """一行 Markdown 标题的层级（行首 `#` 连写的个数）；不是标题 ⇒ 0。

    ## 为什么按层级而不是"任何 `#` 都算边界"

    真实的数学写作几乎都会在 `## 证明` 下面再分小节（`## 记号与约定` / `## 第一步` …，
    或更深的 `### 情形一`）。若 :func:`section_lines` 遇到任何以 `#` 开头的行就结束
    这一节 ⇒ `## 证明` 的下一行若是 `## 记号与约定`，正文立刻被截成空串，落稿闸报
    `empty_proof_section`（"`## 证明` 那一节是空的 ⇒ 没有可签的正文"）—— 稿其实写满了，
    只是切节切错了。

    ## 判据

    层级只看行首那一段连续的 `#`：`#` ⇒ 1、`##` ⇒ 2、`###` ⇒ 3 …… 到第一个非 `#`
    为止；空行 / 非标题 ⇒ 0。`##命题`（标题后没有空格）也按 2 算：本仓的手稿标题是
    中文直写，历史上就允许 `## 命题` 与 `##命题` 两种写法（:func:`section_lines` 的
    匹配口径不变），这一格只负责数 `#` 的个数。
    """
    level = 0
    for ch in str(line or "").lstrip():
        if ch != "#":
            break
        level += 1
    return level


def is_section_heading(line: str) -> bool:
    """这一行是不是手稿的一节标题（:data:`SECTION_TITLES` 之一，逐字前缀）。

    只认标题文字，不看层级：层级由 :func:`heading_level` 单独给。调用方按
    "同级 ∧ 是一节 ⇒ 边界；更高级 ⇒ 边界；更深 ⇒ 节内内容" 组合这两格。
    """
    norm = str(line or "").strip()
    return any(norm.startswith(title) for title in SECTION_TITLES)


def section_lines(text: str, heading: str = SECTION_HEADING) -> tuple[list[tuple[int, str]], int]:
    """取出某一节的正文行 ⇒ `([(行号, 原文)], 段标题所在行号)`；没有这一节 ⇒ `([], 0)`。

    段从标题行下一行开始，到下一个同级或更高级的标题，或文末为止：`## 证明`（二级）
    这一节的边界是 `## ` 或 `# `，而 `### ` 及更深的小标题算节内内容（不截断）。
    边界按 :func:`heading_level` 现算，不写死 `##` —— 手稿若用 `# 命题`（一级），那
    `# ` 也是边界。

    ## 同级的自由小标题算节内

    真实写作会在 `## 证明` 下面用 `## 记号与约定` / `## 第一步` 分小节 —— 同级、
    但不是手稿的一节。只按层级判，它们的正文仍会被截成空串（落稿闸报
    `empty_proof_section`）。所以同级还要求"这一行是 :data:`SECTION_TITLES` 之一"
    才算边界；`## 依赖` 在同一张表里，所以它照旧结束证明那一节。标题参数本身不是
    `#` 标题时（历史调用没有这种）退回"任何标题都算边界"的老口径。
    """
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    start = 0
    for i, line in enumerate(lines, 1):
        norm = line.strip()
        if not norm.startswith(heading):
            continue
        rest = norm[len(heading):]
        if rest and not rest.startswith(("（", "(", " ", "\t")):
            continue
        start = i
        break
    if not start:
        return [], 0
    section_level = heading_level(heading)
    body: list[tuple[int, str]] = []
    for i, line in enumerate(lines[start:], start + 1):
        level = heading_level(line)
        if level and (section_level <= 0
                      or level < section_level
                      or (level == section_level and is_section_heading(line))):
            break
        body.append((i, line))
    return body, start


def statement_body(text: str) -> str:
    """手稿里「命题」那一节的正文（没有这一节 ⇒ 空串）。

    （V 只对手稿负责，不看台账）：V 的命题正文只从这一节读，
    不再从 `statements.statement_full` 读。空串是"这份稿没有命题页"这一事实的诚实读数，
    调用方必须自己判它（`agent_v` 会用占位句进提示词，不拿空串冒充一条命题）。

    归一与 :func:`proof_body` 同一套：只去掉首尾空行，段内的换行与缩进逐字保留 ——
    命题正文是 F 的署名内容，读侧不做任何再排版。
    """
    body, _start = section_lines(text, SECTION_STATEMENT)
    return "\n".join(raw for _ln, raw in body).strip("\n").strip()


def proof_body_reading(text: Any) -> dict[str, Any]:
    """手稿里 `## 证明` 那一节的三态读数（正文这一层：`present` / `absent`）。

    ## 为什么必须有这一格
    若 :func:`proof_body` 在缺节时回退到 `## 依赖` 节正文、再回退到整份全文 ⇒
    "没这一块"变成"拿了别的块"：真机 `reports/e-num-000000.md`（没有 `## 证明`）的
    `proof_body` 是 1597 字符的整份文件，只是被绿色通道 `_green.ok` 挡住，纯属运气。
    回退删除之后，"缺节"必须是读数，而不是另一个块。

    ## 三态（不许折平）
    - `present`：稿里有这一节。`body` 是那一节的正文（逐字，只按行 join，不去首尾空行
      —— 与改前的归一一致：调用方自己 `.strip("\\n")` 后算 sha）；这一节可能是空的。
    - `absent`：稿里没有这一节。`body=""`；调用方必须自己判（受控拒 / 留空并报读数），
      不许拿 `## 依赖` 或整份全文顶替。
    - `unreadable`：只在这一格读文件时可能出现（:func:`read_proof_body`）——
      本函数拿到的已经是正文，所以恒不返回这一态（"没读到"与"没有"分在两处）。

    返回 `{checked, state, present, heading_line, body, chars, why}`。
    """
    raw = str(text or "")
    body, heading_line = section_lines(raw, SECTION_PROOF)
    present = bool(heading_line)
    rendered = "\n".join(single for _ln, single in body)
    out: dict[str, Any] = {
        "checked": True,
        "state": PROOF_PRESENT if present else PROOF_ABSENT,
        "present": present,
        "heading_line": int(heading_line or 0),
        "body": rendered,
        "chars": len(rendered.strip()),
        "why": "",
    }
    if present:
        out["why"] = (f"稿里有 `{SECTION_PROOF}` 那一节（第 {out['heading_line']} 行起，"
                      f"正文 {out['chars']} 字）")
    else:
        out["why"] = (f"稿里没有 `{SECTION_PROOF}` 那一节 ⇒ 没有可读的证明正文"
                      "（不拿 `## 依赖` 或整份全文顶替）")
    return out


def proof_body(text: Any) -> str:
    """手稿里 `## 证明` 那一节的正文；没有这一节 ⇒ 空串。

    为什么单独取这一节：预览要回答的是"证明正文里引了哪些在册命题"，而手稿开头的
    元信息（"命题号：stmt:000002"）不是引用 —— 把它数进来会让 `refs` 与
    `derived_from` 都虚高，而那种虚高不会让任何判据红，只会让读数难看。

    ## 这里没有回退（这是本函数唯一的判据）
    缺节若依次退到 `## 依赖` 节正文、再退到整份全文；那让"这份稿没有证明"变成
    "这份稿的别的块（甚至整份文件）就是证明"。现在缺节一律 `""`，三态读数见
    :func:`proof_body_reading`（`present` / `absent`），读文件那一层见
    :func:`read_proof_body`（多一个 `unreadable`）。

    调用方不许把 `""` 读成"证明为空所以没问题"：它同时意味着"没有这一节"。
    需要三态的地方调用 :func:`proof_body_reading`；确实需要"退而取全文"的调用
    :func:`proof_body_or_whole`（另一个名字，返回值带 `fell_back=True`），不许在
    本函数里恢复静默回退。
    """
    return str(proof_body_reading(text).get("body") or "")


def proof_body_or_whole(text: Any) -> dict[str, Any]:
    """显式的"退而取全文"：`## 证明` 那一节；没有这一节 ⇒ 整份正文。

    这不是 `proof_body` 的隐藏回退 —— 它是一个另起的名字，返回值里带
    `fell_back=True` / `fell_back=False`，调用方必须自己看这一格（"拿的是哪一段"
    不许静默）。

    只有一类调用方该用它：拿到的本来就是一段证明正文、而它没有 markdown 小节标题
    （典型：`read_manuscript` 的"按证明正文认稿"要算这一笔 `proof_text` 的指纹；
    那不要求它带 `## 证明`）。写台账 / 认签 / 落稿一律用 :func:`proof_body`
    （缺节 ⇒ 空串），不许用这一格给"没有证明"找替身。

    返回 :func:`proof_body_reading` 的键 + `fell_back`；`state` 仍是诚实的
    `absent`（`fell_back=True` 说的才是"`body` 现在是整份正文"）。
    """
    reading = proof_body_reading(text)
    if str(reading.get("state") or "") == PROOF_PRESENT:
        return {**reading, "fell_back": False}
    whole = str(text or "")
    return {**reading, "state": PROOF_ABSENT, "present": False,
            "body": whole, "chars": len(whole.strip()), "fell_back": True,
            "why": (f"稿里没有 `{SECTION_PROOF}` 那一节 ⇒ 这一格显式退到整份正文"
                    f"（`fell_back=true`，{len(whole)} 字符）；这不是「证明正文那一节」")}


def read_proof_body(root: Any, rel: Any) -> dict[str, Any]:
    """读一份手稿文件的 `## 证明` ⇒ 三态（`present` / `absent` / `unreadable`）。

    与 :func:`proof_body_reading` 的分工：这一格负责"文件读不读得出来"，读出来之后
    再交给纯函数判"有没有那一节"。两者合起来才是审计 D4 要的三态 —— 少任何一格，
    "文件不在盘上"与"稿里没有这一节"就会折成同一句话。

    返回键：`{checked, state, path, text, body, chars, heading_line, why}`。

    - `present` / `absent`：`checked=True`，`text` 是整份稿（依赖段 / 签块还要用）；
    - `unreadable`：`checked=False`。文件不在盘上、读失败、不是 UTF-8 文本、
      或 `rel` 不是一个工作区相对路径 —— 全都落这一态，`why` 逐条点名是哪一种。
      这一态不是 `absent`：没读到不等于"稿里没有这一节"。

    绝对路径 / `..` 一律拒绝（`unreadable`）：这一格只读工作区相对路径，不给
    "按任意路径读一盘"的口子（与 `read_manuscript` 的候选路径同一纪律）。
    """
    raw_rel = str(rel or "").strip().replace("\\", "/")
    out: dict[str, Any] = {
        "checked": False, "state": PROOF_UNREADABLE, "path": raw_rel,
        "text": "", "body": "", "chars": 0, "heading_line": 0, "why": "",
    }
    root_text = str(root or "").strip()
    if not root_text:
        out["why"] = "没有工作区根（`root` 是空的）⇒ 这一份稿没读到（不是「没有 ## 证明」）"
        return out
    parts = Path(raw_rel).parts if raw_rel else ()
    if not raw_rel or Path(raw_rel).is_absolute() or ".." in parts:
        out["why"] = (f"{raw_rel!r} 不是工作区相对路径（绝对路径 / `..` 不收）⇒ "
                      "这一份稿没读到（不是「没有 ## 证明」）")
        return out
    try:
        text = (Path(root_text) / raw_rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        out["why"] = (f"手稿读不出来：{raw_rel}（{type(exc).__name__}: {exc}）⇒ "
                      "这一份稿没读到（不是「没有 ## 证明」）")
        return out
    reading = proof_body_reading(text)
    out.update(checked=True, text=text, state=str(reading.get("state") or ""),
               body=str(reading.get("body") or ""),
               chars=int(reading.get("chars") or 0),
               heading_line=int(reading.get("heading_line") or 0),
               why=str(reading.get("why") or ""))
    return out


def parse_dependency_section(text: str) -> dict[str, Any]:
    """把一份手稿里的依赖段解析成行 ⇒ 三态读数（`checked` / `present` / `problems`）。

    返回键：
    - `checked`：解析跑了没有（本函数恒为 True —— 它没有"没查成"的路径；
      "段不存在"是 `present=False`，不是没查成）；
    - `present`：手稿里有没有 `## 依赖` 这一节；
    - `heading_line`：段标题在第几行（1 起；没有段 ⇒ 0）；
    - `rows`：`[{quote, stmt_id, step, path_group, line}]`（按文件顺序）；
    - `problems`：`[{line, why}]` —— 缺表头 / 缺列 / 列数不对 / 命题号形状 / 路径号；
    - `refused`：`REFUSED_SECTION` 或空串（调用方据此整笔拒绝）；
    - `reason`：一句话（拒信的第一句，带行号与列名）。
    """
    body, heading_line = section_lines(text)
    out: dict[str, Any] = {
        "checked": True, "present": bool(heading_line), "heading_line": heading_line,
        "rows": [], "problems": [], "refused": "", "reason": "",
    }
    if not heading_line:
        return out
    table = [(ln, raw) for ln, raw in body if raw.strip().startswith("|")]
    if not table:
        out["problems"].append({
            "line": heading_line,
            "why": (f"`{SECTION_HEADING}` 下面没有表格：要给一张表"
                    f"（{' / '.join(name for _f, _k, name in COLUMN_KEYS)}；"
                    "最后一列 `路径号` 可省 —— 路径号由收录时的秘书分配，产出侧不写）")})
    header_cells: list[str] = []
    #: 本表实际有哪几列（字段名，按 `COLUMN_KEYS` 的顺序）。产出侧不写路径号 ⇒
    #: `path_group` 是唯一可省的一列，其余三列（引用 / 命题号 / 步）缺一不可。
    #: 省了它 ⇒ `deps_groups` 里那一格按 `assign_path_group` 的默认（第 1 条）落，
    #: 由秘书在收录事务里覆盖成它分配的号。
    present_fields: list[str] = [field for field, _k, _n in COLUMN_KEYS]
    #: 逐行解析用的列序。表头认得全就照表头取列（上面 `COLUMN_KEYS` 说的
    #: 「顺序不限」只有在这里真的按表头解析时才是事实；此前 `found` 只进了
    #: 出参 `column_index`，正文一律按位置读 —— 表头换个顺序，`step` 与
    #: `path_group` 就静默互换，`problems` 一条都不报，读出两个依赖面）。
    #: 表头认不全时退回位置序：缺列/列数不对已经在上面报过，那一档照旧整笔拒。
    parse_order: list[int] = list(range(len(COLUMN_KEYS)))
    if table:
        header_line, header_raw = table[0]
        header_cells = _cells(header_raw)
        found: dict[str, int] = {}
        for idx, cell in enumerate(header_cells):
            low = cell.lower()
            for field, keys, _name in COLUMN_KEYS:
                if field in found:
                    continue
                if any(key.lower() in low for key in keys):
                    found[field] = idx
                    break
        required = [f for f, _k, _n in COLUMN_KEYS if f != "path_group"]
        missing = [name for field, _keys, name in COLUMN_KEYS
                   if field in required and field not in found]
        present_fields = [f for f, _k, _n in COLUMN_KEYS if f in found]
        if missing:
            out["problems"].append({
                "line": header_line,
                "why": (f"表头缺列：{missing}（这一节要 {len(required)} 列，逐列固定："
                        f"{' / '.join(name for _f, _k, name in COLUMN_KEYS if _f in required)}）")})
        elif len(header_cells) != len(found):
            # 表头里有一列认不出来（多出来的那一列）：列数要恰好等于认出的字段数。
            out["problems"].append({
                "line": header_line,
                "why": (f"表头有 {len(header_cells)} 列，只有 {len(found)} 列认得出："
                        f"{' / '.join(name for _f, _k, name in COLUMN_KEYS)}")})
        out["columns"] = present_fields
        out["column_index"] = dict(found)
        if not missing and len(header_cells) == len(found):
            parse_order = [found[f] for f in present_fields]
    # ---- 逐行读表格（表头之后：分隔行跳过，其余每一行都要是完整的一条）
    # 字段名 → (表头认列用的键, 人话列名)。改前这一格是逐行逐格现扫一遍
    # `next((k, n) for f, k, n in COLUMN_KEYS if f == field)`（行数 × 列数 次
    # 4 元素线性查找，每个格还要建一个生成器）；`COLUMN_KEYS` 是模块级常量、
    # 循环里不动它 ⇒ 建一次映射，逐格 O(1) 取。取到的 `(keys, name)` 与改前逐字相同。
    _column_of = {field: (keys, name) for field, keys, name in COLUMN_KEYS}
    for line_no, raw in table[1:]:
        cells = _cells(raw)
        if _is_separator(cells):
            continue
        if len(cells) != len(present_fields):
            out["problems"].append({
                "line": line_no,
                "why": (f"这一行读出来 {len(cells)} 列，应有 {len(present_fields)} 列："
                        f"{cells!r}（{SECTION_HEADING} 那张表一行一条依赖）")})
            continue
        row: dict[str, Any] = {"line": line_no}
        bad: list[str] = []
        for idx, field in enumerate(present_fields):
            _keys, name = _column_of[field]
            src = parse_order[idx]
            value = (cells[src] if src < len(cells) else "").strip().strip("`").strip()
            if not value:
                bad.append(f"缺 `{name}`")
                continue
            if field == "stmt_id":
                if not value.startswith("stmt:"):
                    bad.append(f"`{name}` 要是 `stmt:NNNNNN`（收到 {value!r}）")
                    continue
                sid = value[len("stmt:"):].strip()
                if not S.is_valid_id(sid):
                    bad.append(f"`{name}` 的号不是 {S.ID_DIGITS} 位十进制（收到 {sid!r}）")
                    continue
                row["stmt_id"] = sid
                continue
            if field == "path_group":
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    bad.append(f"`{name}` 要是正整数（收到 {value!r}）")
                    continue
                if number < 1:
                    bad.append(f"`{name}` 要是正整数（收到 {value!r}）")
                    continue
                row["path_group"] = number
                continue
            row[field] = value
        if bad:
            out["problems"].append({"line": line_no, "why": "；".join(bad)})
            continue
        if "path_group" not in row:
            # 产出侧不写路径号 ⇒ 这一格不是"缺列"，是"还没分配"：收录时由秘书在
            # 事务里给出（这一列的默认值只是让读取方拿到一个整数，不是权威）。
            row["path_group"] = 1
        out["rows"].append(row)
    if out["problems"]:
        out["refused"] = REFUSED_SECTION
        first = out["problems"][0]
        out["reason"] = (f"手稿的依赖段读不懂（`{SECTION_HEADING}`，第 {first['line']} 行起）："
                         + "；".join(f"第 {p['line']} 行——{p['why']}" for p in out["problems"])
                         + "。怎么改：" + _section_problem_fix(str(first["why"]))
                         + "（逐条六格见 `section_problem_findings`）")
    return out


def stmt_refs(text: str) -> list[str]:
    """一段正文里点名的 `stmt:` 引用（裸号，按出现顺序去重）。

    扫描实现不在这里：`textutil.find_citations` 是全仓唯一那一条（秘书的
    `_scan_proof_deps` 也读它）—— 两份扫描会漂，漂的形态是"B 读到的引用数"
    与"秘书扫到的引用数"不一致，而那份不一致没有任何地方会报。
    """
    from . import textutil as T

    out: list[str] = []
    for ref in T.find_citations(str(text or "")):
        if str(ref.get("prefix")) != "stmt":
            continue
        code = str(ref.get("code") or "").strip()
        # 只要真号：手稿里那张表的表头写着 `stmt:NNNNNN`（占位符），它不是一条引用。
        if code and S.is_valid_id(code) and code not in out:
            out.append(code)
    return out


def _first_step_of(ref: str, steps: Mapping[int, Mapping[str, Any]]) -> int | None:
    """正文里第一次引 `ref` 的那一步（没有就 `None` —— 不猜步号）。"""
    nos = [int(no) for no, step in steps.items()
           if str(ref) in (str(x) for x in (step.get("cites") or []))]
    return min(nos) if nos else None


def _first_number(text: Any) -> int | None:
    """一段"用在哪一步"的文字里的第一个整数（没有就 `None`，不猜）。

    表里那一格是自由文本（`第 1、3 步` / `1` / `第 2 步`），四元组只需要一个能指路
    的步号；多个步号时取最小的那个，其余仍留在原文里（读数不丢）。
    """
    nos = _step_numbers(text)
    return nos[0] if nos else None


def dependency_consistency_findings(
        text: str, *, known_ids: Iterable[str] | None = None,
        statement_rows: Iterable[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """`## 依赖` 与证明正文对不上 ⇒ 逐条六格；空列表 = 一致（或这一层不该管）。

    每一条异常单独一条记录（业主 2026-11-06："每一条异常都必须给出四元组"）——
    把三条引用折成一句"表与正文不一致"，读的人仍然得自己回去数哪几条。

    三态（不折平）：

    - 那一节缺了 / 读不懂：不是本函数的事（调用方那两支已各有受控码），返回空列表；
    - 正文点了不可引的号（不在册 / 等级不够）：每条一条
      （``REFUSED_UNKNOWN_SOURCE`` / ``REFUSED_LEVEL_TOO_LOW`` …），带步号；
    - 那一节在、表 0 行、正文点了 N 条可引命题 ⇒ 每条一条
      （``REFUSED_TABLE_DISAGREES``），带"在证明正文第 N 步"；
    - 那一节在、表 0 行、正文一条可引引用都没点 ⇒ 空列表（自足）。

    为什么表里有行就不再往下查：这一层是"落稿 / 收方"的闸，它只回答"这张表是不是
    漏写成了 0 行"；"表里多一行"与"步号对不上"由 V 的 :func:`dependency_review`
    逐条核（那里拿得到整份正文与台账，这两档需要它们）。
    """
    raw = str(text or "")
    section = parse_dependency_section(raw)
    if not section.get("present") or section.get("refused"):
        return []
    steps = proof_steps(raw)
    #: 2026-11-09（D4）：缺 `## 证明` ⇒ 空串 ⇒ 正文引用集合为空（不拿 `## 依赖` /
    #: 整份全文凑引用）。这一层只回答"正文点到的号可不可引"：没有正文可数时它不产生
    #: finding；"表里有行而正文没点"由 V 那一侧的 `dependency_review` ④ 逐条报。
    refs = stmt_refs(proof_body(raw))
    findings: list[dict[str, Any]] = []
    known = {str(x) for x in known_ids} if known_ids is not None else None
    if known is not None:
        for ref in refs:
            if str(ref) in known:
                continue
            #: 池子与台账由调用方从同一次 `statements` 读里算出来 ⇒ 不在这里另立一条
            #: "池子少了它"的判据：不可引的原因只有 `uncitable_statement_finding` 一处。
            got = uncitable_statement_finding(
                str(ref), statement_rows, where="证明正文",
                step=_first_step_of(str(ref), steps))
            if got:
                findings.append(got)
        refs = [ref for ref in refs if str(ref) in known]
    if section.get("rows") or not refs:
        return findings
    for ref in refs:
        no = _first_step_of(str(ref), steps)
        findings.append(citation_finding(
            stmt_id=str(ref), where=_citation_where(step=no, site="证明正文"),
            kind=REFUSED_TABLE_DISAGREES,
            expected=(f"`{SECTION_HEADING}` 那张表里有一行 `stmt:{ref}`"
                      "（写明它用在哪一步）"),
            got="那张表 0 行（正文点了它，表里没有这一行）",
            fix=("把表里那一行补上（号与用在哪一步都写对），或把这些号写进那几步的 "
                 "`cites`（框架按它渲染 `## 依赖`）—— 正文里的「（依据：stmt:…）」"
                 "不等于登记了依赖：框架只读每一步的 `cites`"),
            step=no))
    return findings


def dependency_consistency_problem(
        text: str, *, known_ids: Iterable[str] | None = None,
        statement_rows: Iterable[Mapping[str, Any]] | None = None) -> tuple[str, str]:
    """`## 依赖` 那张表与证明正文说的是不是同一件事：`(受控码, 人话)`；空串 = 一致。

    三态（不折平）：

    - 那一节缺了 / 读不懂：不是本函数的事（调用方那两支已各有受控码），返回空串；
    - 正文点了不可引的号（不在册 / 等级不够）：受控拒，`why` 逐字点名那个号与
      原因（``REFUSED_UNKNOWN_SOURCE`` / ``REFUSED_LEVEL_TOO_LOW`` 等）；
    - 那一节在、表 0 行、正文点了 N 条可引命题 ⇒ 对不上
      （``REFUSED_TABLE_DISAGREES``），`why` 逐条点名"哪个号在第几步"；
    - 那一节在、表 0 行、正文一条可引引用都没点 ⇒ 放行（自足）。

    ## `known_ids` 是"可引池"，不是"在册号集合"

    业主逐字：「F 应该无法读到尚未在册的命题，特别地，F 只可引用 proof review
    （或者说准定理级）及以上等级的命题」。所以：

    - `known_ids` = 在册 ∧ 等级 ≥ pre_theorem 的那一批（:func:`citable_pool`）；
    - 正文里出现一个不在这张表里的号 ⇒ 不是"合法的待接边"，而是这一笔写错了 ——
      F 读不到它，不可能在引用它 ⇒ 受控拒，不许照写、也不许落 dangling；
    - `statement_rows` 只用来把拒信写准（不在册 / 状态不可用 / 等级读不到 / 等级不够
      四档各有各的话）；不给它时只报"不在可引池里"，不冒充知道原因。

    旧做法是"不在册的引用不参与比对，走 dangling 那条路、整笔照写"
    —— 那一条据的是另一条裁定，口径纠正：那种号 F 根本读不到。
    调用方要判"可引"就必须把同一个池子交进来；读不到台账的那一层
    （`manuscriptform` 的落稿校验没有 store）交不出两格，只能按全量比表与正文 ——
    那一档至多多退回一份手写稿，池子那一道在 B 的登记入口与 V 的审计里。

    为什么这一道必须是门而不是读数（2026-11-05 现场）：`deps_missing_reading` 早就把
    这一形态读成"说不一致"，但读数不拦人 —— `manuscriptform.validate_manuscript` 与
    B 的登记入口都只看"那一节在不在"。正文里的「（依据：stmt:…）」是散文，
    框架不把它读回成引用（引用只有一个来源：每一步的 `cites`，见
    `attackround._clean_step`）⇒ 两处一旦分家，没有任何一跳会自己发现。
    """
    raw = str(text or "")
    got = dependency_consistency_findings(raw, known_ids=known_ids,
                                          statement_rows=statement_rows)
    if not got:
        return "", ""
    return str(got[0]["kind"]), "；".join(str(f["detail"]) for f in got)


def _section_problem_fix(why: str) -> str:
    """按解析器那句话给一句可执行的改法（四元组的第四格）。"""
    if "没有表格" in why:
        return "在 `## 依赖` 下面补一张三列表（引用 / 命题号 / 用在哪一步）"
    if "表头缺列" in why or "表头有" in why:
        return "把表头改成三列（引用 / 命题号 / 用在哪一步），一列都不许少；路径号不进稿"
    if "命题号" in why:
        return ("把那一格写成 `stmt:NNNNNN`（六位十进制号；号要从台账或 `attack.step` "
                "的清单里取）")
    if "路径号" in why:
        return "把路径号写成正整数（第几条证明；1 = 主证明）"
    if "列" in why:
        return "把这一行补齐成三列（引用 / 命题号 / 用在哪一步）"
    return "按上面那句改这一行（三列表，三列必填）"


def section_problem_findings(text: str,
                             section: Mapping[str, Any]) -> list[dict[str, Any]]:
    """依赖段读不懂 ⇒ 逐条六格（表头缺列 / 列数不对 / 号形状 / 路径号）。

    这一档没有"被引的那一条"可指时 `stmt_id` 是空串（表头缺列就是没有号可指），
    报文里逐字写"这一条没有可认的命题号" —— 三态纪律：不拿一个瞎猜的号填空。
    行里能扫出 `stmt:<号>` 时照实收进 `stmt_id`，读的人至少知道是哪一行。
    """
    import re as _re

    lines = str(text or "").replace("\r\n", "\n").split("\n")
    out: list[dict[str, Any]] = []
    for problem in section.get("problems") or []:
        line = int(problem.get("line") or 0)
        raw = lines[line - 1] if 0 < line <= len(lines) else ""
        hit = _re.search(r"stmt:\s*([0-9]+)", raw)
        sid = hit.group(1) if hit and S.is_valid_id(hit.group(1)) else ""
        why = str(problem.get("why") or "")
        out.append(citation_finding(
            stmt_id=sid, where=_citation_where(line=line, site="依赖段"),
            kind=REFUSED_SECTION,
            expected=("一张三列表（引用 / 命题号 / 用在哪一步）里的一条合法依赖"
                      "（号形如 `stmt:NNNNNN`）"),
            got=why, fix=_section_problem_fix(why)))
    return out


def missing_section_findings(text: str, refs: Iterable[str], *,
                             got_extra: str = "") -> list[dict[str, Any]]:
    """手稿里没有 `## 依赖` 那一节而正文点了号 ⇒ 每条一条六格。

    为什么逐条而不是"正文引用了 N 条"：读的人要照着改，而"哪一条、在哪一步"正是
    他要找的东西（业主 2026-11-06："每一条异常都必须给出四元组"）。
    """
    steps = proof_steps(text)
    out: list[dict[str, Any]] = []
    for ref in refs:
        no = _first_step_of(str(ref), steps)
        out.append(citation_finding(
            stmt_id=str(ref), where=_citation_where(step=no, site="证明正文"),
            kind=REFUSED_SECTION_MISSING,
            expected=(f"手稿里有一节 `{SECTION_HEADING}`，里面一行 `stmt:{ref}`"
                      "（写明它用在哪一步）"),
            got=("手稿里没有 `## 依赖` 这一节（正文点了它，表里没有登记）"
                 + (f"；{got_extra}" if got_extra else "")),
            fix=("让 F 用 `step` 动作重交这一轮（框架会按每一步的 `cites` 渲染 "
                 f"`{SECTION_HEADING}`），或在手稿里补那一节（三列必填；路径号不进稿）"
                 "—— 补上那一节再交"),
            step=no))
    return out


#: 兜底读盘这一格为什么要存在（写在这里而不是写在调用方）：
#:
#: `B.register_statement` 的 `proof_manuscript` 从来没有人传过值 —— 它是可选参数，
#: 而 B 的提示词只印必填参数（`proof_manuscript` 在 B 的段里没出现过），于是
#: "B 读 F 的手稿登记依赖面"这条正路一次都没走过（sylow5/sylow6：`reports/f-proof-*.md`
#: 0 份、会话里 `## 依赖` 0 次、依赖表 0 行）。只改装配（让调用方记得传）不够：那条装配
#: 一旦漏一次，形态是"静默地没有依赖边"，而它长得和"这条证明确实自足"一模一样。
#: 所以这里把"按约定路径去盘上找"做成唯一一个实现，参数空的时候必须走它。


def manuscript_relpath(*, statement_id: str = "", plan_id: str = "") -> str:
    """手稿的约定路径（工作区相对）—— 有命题号按命题号，只有计划号按计划号，都没有返回空串。

    两种名是同一件事的两个时刻：立项那一轮还没有命题号（`f-proof-plan-<plan>.md`），
    登记取到号之后叫 `f-proof-<号>.md`。兜底读盘两种都认（:func:`manuscript_relpaths`），
    于是"登记之前写的稿"与"登记之后写的稿"都能被收方找到。

    （F/B 两族形式统一）：拼接与解析本体收在
    `manuscriptform.name_reading`（内部只走 `vsigns.parse_manuscript_name`）。这里
    只留一个薄转发 —— 低层常量仍由本模块持有，命名规则不许有两个落点。
    """
    from . import manuscriptform as _MF

    got = _MF.name_reading(_MF.FAMILY_F, statement_id=statement_id, plan_id=plan_id)
    return str(got.get("path") or "") if got.get("ok") else ""


def manuscript_relpaths(*, statement_ids: Iterable[str] = (), plan_id: str = "") -> list[str]:
    """兜底读盘的候选路径（按优先次序，去重后返回）。

    优先次序就是这个函数存在的理由：按命题号命名的那些排在前（它精确指向"这一条命题的
    证明手稿"），计划号那一个排在最后（它说的是"这个计划的稿"，比命题号宽）。
    一条候选都没有时返回空列表 —— 调用方据此落 `none`，而不是拿空串去拼一个目录名。
    """
    out: list[str] = []
    for sid in statement_ids or ():
        rel = manuscript_relpath(statement_id=str(sid))
        if rel and rel not in out:
            out.append(rel)
    rel = manuscript_relpath(plan_id=str(plan_id or ""))
    if rel and rel not in out:
        out.append(rel)
    return out


#: 兜底读盘两种认法（进 `read_manuscript` 的读数 `matched_by`，三态里的"怎么命中的"）。
MATCH_BY_PATH = "path"
MATCH_BY_PROOF_BODY = "proof_body"


def _body_key(body: Any) -> str:
    """一段证明正文的归一指纹（逐行去首尾空白、丢空行与洗稿标记行）。"""
    text = str(body or "").replace("\r\n", "\n")
    return "\n".join(line.strip() for line in text.split("\n")
                     if line.strip() and not line.strip().startswith(WASH_MARK))


def _proof_body_key(text: Any) -> str:
    """一段"证明正文"的指纹（`## 证明` 那一节；没有这一节 ⇒ 显式整份正文）。

    ## 为什么这里允许"退而取全文"（这一句是给后人的）
    这一格的入参不是一份手稿，而是一段证明正文（`read_manuscript` 第二段拿这一笔的
    `proof_text` 来比）；一段正文本来就不带 `## 证明` 标题。若在这里也走严格口径，
    "按正文认稿"这一整条路会退化成永远算空指纹（2026-11-09 实测：登记那一笔的正文 sha
    会变成空串的 sha）。所以这里走 `proof_body_or_whole` 的显式回退
    （`fell_back=True`），而不是在 `proof_body` 里偷偷退。

    为什么是逐行归一而不是逐字：手稿是渲染出来的（`agent_f/manuscript.py` 按步拼行），
    而 B 收下来的 `proof_text` 可能多/少一个尾随空行 —— 那是排版，不是另一份证明。
    反过来，改一个字指纹就变（判据里有负控）⇒ 它比"文件名"精确、比"正文包含"严格。

    洗稿元信息那一行（`WASH_MARK`）不算证明内容，指纹里剔掉：`mark_washed` 在
    "没有 `- 计划：` 那一行"的稿子上会把它插到第 2 行之后 —— 那种形状下它会落进
    `## 证明` 那一节，留着就会让"同一份证明"读成"不同"（真机手稿有页头，不会撞到；
    但判据夹具与手写稿会）。

    候选稿那一侧不走这一格：先过 `proof_body_reading`，缺节的稿不按正文认（下面那段）。
    """
    reading = proof_body_or_whole(text)
    return _body_key(reading.get("body"))


def _plan_named_manuscripts(base: Path) -> list[str]:
    """`reports/f-proof-plan-*.md` 的候选（工作区相对、按名字排序）。

    为什么按名字排序而不是按 mtime：这个兜底要用"内容"认，不用"新旧"认 ——
    计划号那一份稿每一轮都会被覆盖（87 的 plan-000001 改写 3 次），按 mtime 取最新
    会把上一轮的证明当成这一轮的。排序只为了让同一批候选的顺序可复现。
    """
    directory = base / MANUSCRIPT_DIR
    try:
        if not directory.is_dir():
            return []
        names = sorted(p.name for p in directory.glob(f"{MANUSCRIPT_PLAN_PREFIX}*.md"))
    except OSError:  # noqa: BLE001 —— 探不到目录要能如实说，不许当成"没有候选"
        return []
    return [f"{MANUSCRIPT_DIR}/{name}" for name in names]


def read_manuscript(root: Any, *, statement_ids: Iterable[str] = (),
                    plan_id: str = "", proof_text: Any = "",
                    manuscript_paths: Iterable[str] = ()) -> dict[str, Any]:
    """按约定路径（必要时按证明正文）在盘上找 F 的证明手稿。

    返回 `{checked, source, text, path, tried, why, matched_by}`。

    ## 两段认法

    ① 按名字：调用方点名的那一份（`reports/f-proof-<稿号>.md` —— 稿号由 F 自己发，
       与命题号、计划号无关）排在最前（`manuscript_paths`）；其次
       `manuscript_relpaths` 的兼容候选（按命题号 / 计划号拼出的旧名）；
       命中 ⇒ `matched_by="path"`。
    ② 按内容（`proof_text` 非空、且第 ① 段一个都没命中时）：扫
       `reports/f-proof-plan-*.md`，把每一份的 `## 证明` 那一节与这一笔的 `proof_text`
       逐行归一后比 —— 相同才认，命中 ⇒ `matched_by="proof_body"`。

    ## 为什么必须补第 ② 段
    F 的稿在拿到命题号之前叫 `f-proof-plan-<计划号>.md`，而"登记成功之后改名成
    `f-proof-<命题号>.md`"只发生在 F 自己的 outlet 登记成功那一笔（`publish_manuscript`）。
    （2026-11-10 后：稿按稿号命名 —— F 的稿从写到收录都叫 `f-proof-<稿号>.md`，
    下面这一段按命题号改名是那一代的读数。）
    87 里六份稿全叫 plan 名、按号命名的 0 份（outlet 因"没有覆盖正文的 V 签"整笔拒），
    于是 B 的兜底读盘永远只查 `f-proof-<号>.md` ⇒ 读到 0 份 ⇒ 依赖面 0 行。第 ② 段补的
    就是"盘上那份稿还在、只是叫计划名"这一档。

    ## 为什么它只补一半（这一条必须写在读数旁边，不许被读成"补了就好"）
    内容认法的前提是"盘上那一份还是登记时那一份"。计划号那份稿会被后续轮次覆盖
    （87 实测：六份里三份的正文与登记进台账的 `proof_text` 已经不是同一份）——
    那一档必须继续受控拒绝（`source=none` ⇒ 有在册引用时 B 整笔拒
    `dependency_section_missing`），不许按 glob 取最新去猜一份。真机读数：
    87 的六份稿里第 ② 段认得出 3 份（000000→stmt:000001、000002→stmt:000003、
    000003→stmt:000007），另外 3 份正是"被后续轮次覆盖"的那一半。

    ## 本函数不产出证明号（别与携带单第四列混成一个）
    `#pN` 只有两个来路：调用方给的 `proof_no`、D 携带单第四列（`CARRIED_COLUMNS`）。
    内容命中的是一份正文，不是"第几条证明" —— 这里不猜号、也不回填号；读数只用
    `matched_by` 说"是靠名字还是靠正文命中的"（`tried` 逐条也带这一格）。

    三态（与全仓同一条纪律，不许折平）：

    - `checked=False`：压根没查成（没有工作区根）⇒ `source=none` 只是如实说"没读到"，
      `why` 点名缺的是哪一个上下文；
    - `checked=True` + `source=disk`：真读到了一处，`path` 是那一处、`text` 是全文；
    - `checked=True` + `source=none`：约定路径逐条查过、内容也认过，一处都不对，
      `tried` 逐条列出查过哪些路径 / 比过哪些正文 —— 于是"我没找"与"找了没有"分得开。

    读文件本身失败（权限 / 编码）不吞：那一条进 `tried` 的 `why`，继续找下一处；
    全部失败时 `why` 会带上它们，调用方据此知道该修什么。
    """
    root_text = str(root or "").strip()
    if not root_text:
        return {"checked": False, "source": SOURCE_NONE, "text": "", "path": "",
                "tried": [], "matched_by": "",
                "why": "没有工作区根（`root` 是空的）⇒ 按约定路径找手稿这一趟没查成"}
    base = Path(root_text)
    tried: list[dict[str, Any]] = []
    #: 调用方点名的候选路径排在最前（F 自己的稿号 `f-proof-<稿号>.md`、D 携带单给的
    #: 那一份）。它们不按命题号也不按计划号命名，只靠 `manuscript_relpaths` 找不到。
    _named: list[str] = []
    for _rel in manuscript_paths or ():
        _rel = str(_rel or "").strip().replace("\\", "/")
        if _rel and _rel not in _named:
            _named.append(_rel)
    candidates = _named + [r for r in manuscript_relpaths(
        statement_ids=statement_ids, plan_id=plan_id) if r not in _named]
    for rel in candidates:
        path = base / rel
        try:
            exists = path.is_file()
        except OSError as exc:  # noqa: BLE001 - 探一次盘都会失败时要说出来，不许当成"不在"
            tried.append({"path": rel, "exists": False, "matched_by": MATCH_BY_PATH,
                          "why": f"探不到（{type(exc).__name__}: {exc}）"})
            continue
        if not exists:
            tried.append({"path": rel, "exists": False, "matched_by": MATCH_BY_PATH, "why": ""})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:  # noqa: BLE001 - 读失败与"不在盘上"是两件事
            tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PATH,
                          "why": f"读不出来（{type(exc).__name__}: {exc}）"})
            continue
        if not text.strip():
            tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PATH,
                          "why": "文件在，但正文是空的"})
            continue
        tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PATH, "why": ""})
        return {"checked": True, "source": SOURCE_DISK, "text": text, "path": rel,
                "tried": tried, "matched_by": MATCH_BY_PATH, "why": ""}
    # ---- 第 ② 段：按证明正文认（只在第 ① 段全 miss、且调用方给了正文时） -------------
    #: 这一笔的正文可以是"一段不带标题的证明正文" ⇒ `_proof_body_key` 显式退到整份
    #: 正文算指纹（`proof_body_or_whole` 的 `fell_back=True`，读数在这一格内部）。
    want = _proof_body_key(proof_text) if str(proof_text or "").strip() else ""
    compared = 0
    if want:
        for rel in _plan_named_manuscripts(base):
            path = base / rel
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:  # noqa: BLE001 —— 读不出来要如实说，继续比下一份
                tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PROOF_BODY,
                              "why": f"读不出来（{type(exc).__name__}: {exc}）"})
                continue
            #: 2026-11-09（D4）：候选稿缺 `## 证明` ⇒ 不按正文认（不拿依赖段 /
            #: 整份全文当"这一份的证明正文"）。这一档只进 `tried`，不许命中。
            cand = proof_body_reading(text)
            if str(cand.get("state") or "") != PROOF_PRESENT:
                tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PROOF_BODY,
                              "why": (f"稿里没有 `{SECTION_PROOF}` 那一节 ⇒ 不按正文认"
                                      "（缺节不等于整份稿就是证明）")})
                continue
            compared += 1
            if _body_key(cand.get("body")) == want:
                tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PROOF_BODY,
                              "why": "`## 证明` 与这一笔的 proof_text 逐行相同"})
                return {
                    "checked": True, "source": SOURCE_DISK, "text": text, "path": rel,
                    "tried": tried, "matched_by": MATCH_BY_PROOF_BODY,
                    "why": (f"按名字没找到；按证明正文认出了 {rel}"
                            f"（比过 {compared} 份计划名手稿）")}
            tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PROOF_BODY,
                          "why": "`## 证明` 与这一笔的 proof_text 不同（不是这一份）"})
    checked_paths = [str(t.get("path") or "") for t in tried]
    why = ("按约定路径找过 " + (f"{len(checked_paths)} 处：" + "、".join(checked_paths)
                                if checked_paths else "0 处（没有命题号也没有计划号可定位）")
           + " —— 这几种名一处都不在盘上（或者读不出来，原因逐条见 `tried`）")
    if want:
        why += (f"；又按证明正文比过 {compared} 份 `{MANUSCRIPT_DIR}/{MANUSCRIPT_PLAN_PREFIX}"
                "*.md`，没有一份与这一笔的 proof_text 相同"
                "（那一半只能等 F 在登记成功后把稿改名成按命题号的那一份）")
    return {"checked": True, "source": SOURCE_NONE, "text": "", "path": "",
            "tried": tried, "matched_by": "", "why": why}


# ------------------------------------------------------------------ D 携带（走的正是这条主路）

#: D 的研究报告候选名：跨趟那一份手稿，以及 `write_report` 渲染的每问题工作稿。
D_REPORT_NAMES: tuple[str, ...] = ("RESEARCH.md",)
D_WORKING_SUFFIX = "-research.md"
#: 携带单最多列几条（超出只报条数，不静默截断）。
CARRIED_LIMIT = 50


def d_report_paths(root: Any) -> list[str]:
    """D 的研究报告相对路径（跨趟手稿排在前，其余按名字排序）。"""
    base = Path(str(root or ""))
    out: list[str] = []
    d = base / MANUSCRIPT_DIR
    for name in D_REPORT_NAMES:
        if (d / name).is_file():
            out.append(f"{MANUSCRIPT_DIR}/{name}")
    if d.is_dir():
        for p in sorted(d.glob(f"*{D_WORKING_SUFFIX}")):
            rel = f"{MANUSCRIPT_DIR}/{p.name}"
            if rel not in out:
                out.append(rel)
    return out


def _mss_key(family: Any, manuscript_id: Any) -> str:
    """稿 ⇒ 携带键：`mss:<族>-<号>`；族认不出 ⇒ 老形 `mss:<号>`（不带族，读侧按唯一性裁定）。

    族那一格不在这里另写前缀表：`<族>` 直接取 `manuscriptfamily.FAMILY_ORDER` 里的名字
    （`f-proof` / `b-proof` / `e-proof` / `e-num`），与 `refvocab` 的 `mss:<family>-<id>`
    同一形 —— 携带单第一格与引用词表里写的是同一个东西，不各造一份写法。
    """
    fam = str(family or "").strip()
    mid = str(manuscript_id or "").strip()
    return f"mss:{fam}-{mid}" if fam and mid else f"mss:{mid}"


def _mss_split(text: Any) -> tuple[str, str]:
    """`mss:` 那一段 ⇒ `(族, 稿号)`；没写族 ⇒ `("", 原文)`（族留给读侧按唯一性裁定）。

    `f-proof-000000` ⇒ `("f-proof", "000000")`、`f-proof-plan-42` ⇒ `("f-proof", "plan-42")`、
    `000000` ⇒ `("", "000000")`。前缀逐个从 `manuscriptfamily` 的族表取（唯一真身），
    四族前缀互不为前缀 ⇒ 拆分无歧义，不需要第二条正则。
    """
    raw = str(text or "").strip()
    for family in _MFAM.FAMILY_ORDER:
        prefix = _MFAM.prefix_of(family)
        if prefix and raw.startswith(prefix):
            return family, raw[len(prefix):].strip()
    return "", raw


def _family_of_carrier(rel: Any) -> str:
    """载体路径 ⇒ 这一份稿的族（名字里的族前缀）；认不出 ⇒ 空串（不猜）。

    老键 `mss:<号>` 没有族那一格，族只能从它指的那份稿的名字读出来
    （`reports/e-num-000000.md` ⇒ `e-num`）。名字不是手稿形（`notes/foo.md`）⇒ 空串 ——
    那时"族唯一确定"不成立，读侧不许替它挑一族。
    """
    got = _MFAM.classify_manuscript(str(rel or ""))
    return str(got.get("name_family") or "")


def _mss_lookup(index: Mapping[str, dict[str, Any]],
                by_bare_mid: Mapping[str, list[dict[str, Any]]],
                sid: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """携带单 `mss:` 那一档的寻址 ⇒ `(命中行, 歧义读数)`；三态，绝不猜。

    - 带族（`f-proof-000000`）⇒ 只认那一族那一号（索引里就是带族键，唯一）；
    - 裸号而单上只属一行 ⇒ 用它（族已由载体路径读出来，不猜）；
    - 裸号而单上跨族出现 ⇒ 回歧义读数（「跨族同号、无法唯一定位」），调用方受控拒。
    """
    family, mid = _mss_split(sid)
    if family:
        return index.get(_mss_key(family, mid)), None
    rows = by_bare_mid.get(mid) or []
    if len(rows) == 1:
        return rows[0], None
    if len(rows) > 1:
        fams = [str(r.get("family") or "") for r in rows]
        keys = [str(r.get("key") or "") for r in rows]
        return None, {
            "manuscript_id": mid,
            "families": [f for f in fams if f],
            "keys": keys,
            "paths": [str(r.get("path") or "") for r in rows],
            "why": (f"D 的携带单上稿号 `{mid}` 跨族同号、无法唯一定位"
                    f"（同一号出现在 {'、'.join(f or '族未知' for f in fams)}："
                    + "、".join(keys)
                    + "）⇒ 不猜是哪一份稿；要读哪一族，单上要写 `mss:<族>-<号>`"),
        }
    return None, None


def carried_manuscripts(report_text: Any) -> dict[str, Any]:
    """读 D 研究报告里"携带给 B 的证明手稿"那一节 ⇒ 三态读数。

    返回 `{checked, present, heading_line, rows, problems, refused, reason}`：
    `rows` 是 `[{statement_id, experiment_id, manuscript_id, family, key, path, sha256,
    line, proof_no}]`（按文件顺序，同号先到先得 —— `mss:` 的"同号"是 (族, 号)：
    跨族同号是两份稿、不是重列）；`problems` 逐行点名（缺列 / 命题号形状不对 / 路径为空），
    `refused` 非空时调用方不许把这一节读成"携带单是空的"—— 读不懂与没有是两件事。
    """
    import re as _re

    body, heading_line = section_lines(report_text, CARRIED_HEADING)
    out: dict[str, Any] = {"checked": True, "present": bool(heading_line),
                           "heading_line": heading_line, "rows": [], "problems": [],
                           "refused": "", "reason": ""}
    if not heading_line:
        return out
    table = [(ln, raw) for ln, raw in body if raw.strip().startswith("|")]
    seen: set[str] = set()
    for line_no, raw in table:
        cells = _cells(raw)
        if _is_separator(cells):
            continue
        if cells and cells[0].lower().startswith("---"):
            continue
        if len(cells) not in (CARRIED_MIN_COLUMNS, len(CARRIED_COLUMNS)):
            # 表头那一行（列名的名字）在两种列数里也对不上 ⇒ 用"第一格是不是命题号"区分
            if all(not c.startswith("stmt:") and not S.is_valid_id(c) for c in cells):
                continue
            out["problems"].append({
                "line": line_no,
                "why": (f"这一行读出来 {len(cells)} 列，应有 {CARRIED_MIN_COLUMNS} 或 "
                        f"{len(CARRIED_COLUMNS)} 列（{' / '.join(CARRIED_COLUMNS)}；"
                        "老行没有第四列 ⇒ 证明号读成 #p1）")})
            continue
        raw_id, raw_path, raw_sha = (c.strip().strip("`").strip() for c in cells[:3])
        raw_no = cells[3].strip().strip("`").strip() if len(cells) > 3 else ""
        #: 这一行的身份前缀（`stmt:` / `exp:` / `mss:`）。改前同一件事算两遍 ——
        #: `any(raw_id.startswith(p) ...)` 判"是不是表头"、`next(...)` 再取前缀，
        #: 两次扫的都是同一张三元组、同一个 `raw_id`。取一次，"有没有前缀"看它是否为空
        #: （`CARRIED_KEYS` 里没有空串 ⇒ `next` 取到的非空串 ⇔ `any` 为真）。
        key = next((p for p in CARRIED_KEYS if raw_id.startswith(p)), "")
        if not key:
            # 表头那一行（"命题号（stmt:NNNNNN ...）"）不算坏行：它第一格不以上面的前缀开头
            if raw_id.startswith("命题号") or not raw_id:
                continue
            out["problems"].append({"line": line_no,
                                    "why": ("命题号那一格要是 `stmt:NNNNNN` 或 "
                                            f"`exp:NNNNNN`（收到 {raw_id!r}）")})
            continue
        proof_no = 1
        if raw_no:
            # 第四格写了但认不出 ⇒ 整节读不懂（不许静默折成 #p1：那正是"号给错了"的形态）
            try:
                proof_no = int(raw_no) if not raw_no.startswith("#") else int(raw_no[2:])
            except (TypeError, ValueError):
                proof_no = 0
            if proof_no < 1:
                out["problems"].append({
                    "line": line_no,
                    "why": (f"证明号那一格要是 >= 1 的整数（可写 `2` / `#p2`；收到 "
                            f"{raw_no!r}）—— 留空才是 #p1")})
                continue
        sid = raw_id[len(key):].strip()
        family = ""
        if key == "mss:":
            # 稿号不是 `stmt:` 那种 6 位十进制：它是 `plan-<计划号>` 或数字稿号
            # （`vsigns.manuscript_id_of` 读出来的那一个），新写法前面还带族
            # （`mss:f-proof-000000` / `mss:e-num-000000`）。只判形状安全，不判在册 —
            # 在不在册由读侧按路径 / sha 核（这一格只是"清单里怎么称呼它"）。
            family, sid = _mss_split(sid)
            if not _re.fullmatch(r"[A-Za-z0-9_.\-]+", sid or ""):
                out["problems"].append({
                    "line": line_no,
                    "why": (f"稿号那一格要是 `mss:<族>-<号>` 或 `mss:<号>`"
                            f"（收到 {sid!r}）")})
                continue
            carrier_family = _family_of_carrier(raw_path)
            if not family:
                # 老键（`mss:<号>`，2026-11-16 之前写的）：族只能从载体路径读出来 ——
                # 名字是 `<族>-<号>.md` 时唯一确定；不是手稿形 ⇒ 留空（读侧按唯一性裁定，
                # 不在这里替它挑一族）。
                family = carrier_family
            elif carrier_family and carrier_family != family:
                # 键说这一份是甲族、载体却是乙族的稿 ⇒ 读下去就是把乙族的稿当成甲族那一份
                # （"两族的稿混成一个"）。清单与盘不一致 ⇒ 整节读不懂（受控拒）。
                out["problems"].append({
                    "line": line_no,
                    "why": (f"稿的族对不上：键写的是 `{family}`，而载体路径 {raw_path!r} 是 "
                            f"`{carrier_family}` 的稿 ⇒ 会把另一族的稿读成这一份")})
                continue
        elif not S.is_valid_id(sid):
            out["problems"].append({"line": line_no,
                                    "why": f"命题号的号不是 {S.ID_DIGITS} 位十进制（收到 {sid!r}）"})
            continue
        if not raw_path:
            out["problems"].append({"line": line_no, "why": "手稿路径那一格是空的"})
            continue
        # 键的身份决定这一行是谁的稿：`stmt:` ⇒ 命题行（F 的稿）；`exp:` ⇒ E 的实验
        # （那条链里命题可能还没进台账，没有命题号可写）；`mss:` ⇒ F 的登记条目
        # （稿在盘上、命题号还没发）。三档落同一个 `rows` 结构，只是三个身份格
        # 各有一格是空的。
        #
        # `mss:` 的行身份是 (族, 号)，不是单号：四族各有自己的号段、都从 000000 起，
        # 单号做身份会把 `f-proof-000000` 与 `e-num-000000` 折成"重列"⇒ 后到的那一行被
        # 静默丢掉（携带单少一行、B 按清单寻址不到它）。族认不出时退回裸号（那时单上
        # 只有这一条能指到它，读侧会按唯一性裁定）。
        row_key = f"{key}{family + '-' if (key == 'mss:' and family) else ''}{sid}"
        if row_key in seen:
            continue
        seen.add(row_key)
        out["rows"].append({"statement_id": sid if key == "stmt:" else "",
                            "experiment_id": sid if key == "exp:" else "",
                            "manuscript_id": sid if key == "mss:" else "",
                            "family": family if key == "mss:" else "",
                            "key": row_key,
                            "path": raw_path,
                            "sha256": raw_sha.lower(),
                            #: 这一份是第几份证明（第四格；老行 / 空格 ⇒ #p1）。
                            "proof_no": int(proof_no),
                            "line": line_no})
    if out["problems"]:
        first = out["problems"][0]
        out["refused"] = REFUSED_SECTION
        out["reason"] = (f"D 报告的携带单读不懂（`{CARRIED_HEADING}`，第 {first['line']} 行起）："
                         + "；".join(f"第 {p['line']} 行——{p['why']}" for p in out["problems"]))
    return out


def render_carried_section(rows: Iterable[Mapping[str, Any]],
                           *, note: str = "") -> str:
    """把携带行渲染成那一节（D 侧写、B 侧读；渲染与解析共用 `CARRIED_HEADING` 与列名）。

    `rows` 的每一行用 `statement_id`（F 的稿，`stmt:`）/ `experiment_id`（E 的稿，
    `exp:`）/ `manuscript_id`（F 的稿还没拿到命题号时，`mss:<族>-<号>`）其中之一做键；
    都给时按 命题号 → 实验号 → 稿号 的次序取（命题已在册时它更精确）。

    稿的族优先读行上的 `family`，没有就从 `path` 的名字读（`reports/e-num-000000.md`
    ⇒ `e-num`）—— 两条都认不出时才写老形 `mss:<号>`（读侧按唯一性裁定，不猜一族）。
    """
    lines = [CARRIED_HEADING, "",
             "D 交研究手稿给 B 入库时把证明手稿一并带过来（「是通过D传吗」）：",
             "下表每一行是 `命题号 → 手稿路径 → 那份文件字节的 sha256 → 第几份证明`，",
             "B 读稿登记依赖面。第四列留空 ⇒ 第 1 份（老行没有这一列，读数相同）。",
             "E 的穷举证明手稿用 `exp:<实验号>` 做键：那条链里命题可能还没进台账；",
             "F 的稿还没拿到命题号（登记条目先落、号由 B 在 V 签之后发）⇒ 用"
             " `mss:<族>-<号>`（四族各有号段，同号跨族是常态 ⇒ 单号做键会把两族的稿折成一行）。",
             ""]
    lines.append("| " + " | ".join(CARRIED_COLUMNS) + " |")
    lines.append("|" + "|".join("---" for _ in CARRIED_COLUMNS) + "|")
    count = 0
    for row in rows:
        sid = str(row.get("statement_id") or "")
        eid = str(row.get("experiment_id") or "")
        msid = str(row.get("manuscript_id") or "")
        if sid:
            key = f"stmt:{sid}"
        elif eid:
            key = f"exp:{eid}"
        elif msid:
            key = _mss_key(str(row.get("family") or "") or _family_of_carrier(row.get("path")),
                           msid)
        else:
            continue
        no = str(row.get("proof_no") or "").strip()
        lines.append(f"| {key} | {row.get('path')} | {row.get('sha256') or ''} | {no} |")
        count += 1
    if not count:
        lines.append("")
        lines.append("（这一趟没有可携带的证明手稿：不是省略，是确实没有 —— 盘上没有"
                     "任何一条按稿号命名的 `reports/f-proof-<稿号>.md`（稿号由 F 自己发，"
                     "与命题号、计划号无关），也没有一份"
                     "已签的 `reports/e-proof-<实验号>.md`。）")
    if str(note or "").strip():
        lines.append("")
        lines.append(str(note).strip())
    return "\n".join(lines) + "\n"


def _carried_target(base: Path, hit: Mapping[str, Any],
                    tried: list[dict[str, Any]]) -> tuple[str, str]:
    """按携带单的一行到盘上去读那份 F 稿 ⇒ `(text, 文件 sha256)`。

    读不到就回 `("", "")`，并把原因追加进 `tried`（不在这一层抛、也不静默）。
    判据三条：路径不许越出工作区 / 文件要在盘上 / 携带单给了 sha256 就必须相符。
    """
    import hashlib

    rel = str(hit.get("path") or "")
    raw_target = Path(rel)
    if raw_target.is_absolute() or ".." in raw_target.parts:
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": "携带单里的路径越出工作区（绝对路径或含 ..）⇒ 不读"})
        return "", ""
    target = base / raw_target
    if not target.is_file():
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": "携带单点名的文件不在盘上"})
        return "", ""
    try:
        blob = target.read_bytes()
    except OSError as exc:  # noqa: BLE001 - 读失败与"不在"分得开
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": f"读不出来（{type(exc).__name__}: {exc}）"})
        return "", ""
    sha = hashlib.sha256(blob).hexdigest()
    want = str(hit.get("sha256") or "")
    if want and want != sha:
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": (f"sha256 对不上（携带单写 {want[:12]}…，盘上是 {sha[:12]}…）"
                              "⇒ 这份稿不是 D 交的那一版，不拿它登记")})
        return "", ""
    text = blob.decode("utf-8", errors="replace")
    if not text.strip():
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": "文件在，但正文是空的"})
        return "", ""
    return text, sha


def read_carried_manuscript(root: Any, *, statement_ids: Iterable[Any] = (),
                            proof_text: Any = "") -> dict[str, Any]:
    """在 D 的报告里找"这一条命题的证明手稿"，找到就把正文读回来（纯读，零模型调用）。

    返回 `{checked, source, text, path, sha256, carried_by, tried, why, named, address,
    item, list_report, list_line, list_sha256, matched_by, ambiguous}`。

    ## 怎么认这一笔（两条路，都在清单里找，绝不自己到盘上猜）
    1. 按候选命题号（`statement_ids`）命中清单里的那一行；命题号没命中时试 `mss:` 那一档
       （见下节的三态）；
    2. 号对不上时（首次登记还没有号、`proof_manuscript` 也没给），按正文命中：
       逐行按地址去读那份 F 稿，谁的「## 证明」正文 sha 等于 `proof_text` 的 sha 就是它。
       2026-11-02 业主：「B侧需寻址获得F侧证明及V签」—— 号还不知道时，正文是清单里
       唯一能对上的东西；这一步仍是清单内寻址，不是"按约定路径撞见一份稿"。

    ## `mss:` 那一档：键带族，三态（2026-11-16）

    稿的身份是 (族, 稿号)（`5ccb2041`；四族各有号段、都从 `000000` 起），携带单的
    `mss:` 键因此写 `mss:<族>-<号>`。读侧三态，绝不猜：

    | 单上这一号 | 怎么读 |
    |---|---|
    | 带族键（`mss:f-proof-000000`） | 只认那一族那一号 |
    | 老键 `mss:000000`、单上只此一行 | 用它（族已由载体路径读出来，唯一） |
    | 老键 / 裸号、单上跨族都出现 | 不猜：`named=True` + `source=none` + `ambiguous` 读数点名「跨族同号、无法唯一定位」 |

    第三档不是"没找到"：调用方必须受控拒绝（`REFUSED_ADDRESS`），不许降级去盘上撞一份
    —— 两族的稿被折成一份，比读不到更坏。

    `source=carried_by_D` 只在"清单里有这一条、文件读得到、sha256 相符（给了就核）"时成立；
    任何一处不成立都落到 `none` 并把原因写进 `tried` / `why` —— 静默用一份对不上的稿
    比读不到更坏（依赖边会挂到别人的论证上）。

    ## `named`（2026-11-02）
    `named=True` 表示"清单点了这一笔的名"（按号或按正文命中了那一行）：即便地址读不到，
    调用方也必须受控拒绝而不是降级去盘上自己找（`depsection.REFUSED_ADDRESS`）。
    `address` / `item` / `list_report` / `list_line` / `list_sha256` 五格是"按哪条清单、
    第几项、什么地址"的读数。
    """
    import hashlib

    root_text = str(root or "").strip()
    out: dict[str, Any] = {"checked": False, "source": SOURCE_NONE, "text": "", "path": "",
                           "sha256": "", "carried_by": "", "tried": [], "why": "",
                           "named": False, "address": "", "item": 0,
                           "list_report": "", "list_line": 0, "list_sha256": "",
                           "proof_no": 0, "matched_by": "", "manuscript_id": "",
                           #: 跨族同号、无法唯一定位时的读数（空 dict = 没有这一档）。
                           "ambiguous": {}}
    if not root_text:
        out["why"] = "没有工作区根（`root` 是空的）⇒ 读 D 报告里那张携带单这一趟没查成"
        return out
    base = Path(root_text)
    tried: list[dict[str, Any]] = out["tried"]
    #: 键 ⇒ 清单里的那一行。三个键空间：命题号（`stmt:`）、`mss:<族>-<号>`（新写法）、
    #: `mss:<号>`（老写法，族已从载体路径补上时也落成带族键；补不上才落裸键）。
    index: dict[str, dict[str, Any]] = {}
    #: 裸稿号 ⇒ 单上同号的各行（跨族歧义的唯一判据）：同一号在两张行上出现 ⇒
    #: 这一号属于两族、读侧不许替调用方挑一族。
    by_bare_mid: dict[str, list[dict[str, Any]]] = {}
    candidates: list[dict[str, Any]] = []
    for rel in d_report_paths(root_text):
        try:
            text = (base / rel).read_text(encoding="utf-8")
        except OSError as exc:  # noqa: BLE001 - 读不出报告要说出来（它可能就是带稿的那一份）
            tried.append({"report": rel, "why": f"读不出来（{type(exc).__name__}: {exc}）"})
            continue
        got = carried_manuscripts(text)
        tried.append({"report": rel, "present": bool(got.get("present")),
                      "rows": len(got.get("rows") or []),
                      "problems": len(got.get("problems") or [])})
        for i, row in enumerate(got.get("rows") or [], 1):
            one = {**row, "report": rel, "item": i}
            candidates.append(one)
            index.setdefault(str(row["statement_id"]), one)
            mid = str(row.get("manuscript_id") or "")
            if mid:
                index.setdefault(_mss_key(str(row.get("family") or ""), mid), one)
                by_bare_mid.setdefault(mid, []).append(one)
    out["checked"] = True

    def _hit(one: Mapping[str, Any], *, matched_by: str) -> dict[str, Any]:
        """把清单里的这一行写进读数（按号命中 / 按正文命中共用一处）。"""
        out.update(named=True, address=str(one.get("path") or ""),
                   item=int(one.get("item") or 0),
                   list_report=str(one.get("report") or ""),
                   list_line=int(one.get("line") or 0),
                   list_sha256=str(one.get("sha256") or ""),
                   #: 携带单第四列（这一份是第几份证明；老行 / 空格 ⇒ #p1）。
                   proof_no=int(one.get("proof_no") or 1),
                   manuscript_id=str(one.get("manuscript_id") or ""),
                   matched_by=matched_by)
        return out

    ambiguous: dict[str, Any] | None = None
    for raw in statement_ids or ():
        sid = str(raw or "").strip().split("#", 1)[0].split(":", 1)[-1].strip()
        if not sid:
            continue
        hit = index.get(sid)
        if hit is None:
            # 命题号没命中 ⇒ 试 `mss:` 那一档（带族号 / 老裸号，三态见 `_mss_lookup`）。
            # 跨族同号的那一笔不在这里挑，记下来继续扫：后面的候选号若唯一命中，
            # 那是一次确定的对上（不是猜）。
            hit, amb = _mss_lookup(index, by_bare_mid, sid)
            if amb is not None:
                if ambiguous is None:
                    ambiguous = amb
                continue
        if hit is None:
            continue
        text, sha = _carried_target(base, hit, tried)
        _hit(hit, matched_by="statement_id")
        if not text:
            continue
        return {**out, "source": SOURCE_CARRIED, "text": text,
                "path": str(hit.get("path") or ""), "sha256": sha,
                "carried_by": str(hit.get("report") or ""), "why": ""}
    # ---- 2026-11-02：号还不知道时按正文命中（仍在清单内寻址）----
    want = (hashlib.sha256(str(proof_text or "").encode("utf-8")).hexdigest()
            if str(proof_text or "").strip() else "")
    unreadable: list[dict[str, Any]] = []
    if want and candidates:
        for hit in candidates:
            text, sha = _carried_target(base, hit, tried)
            if not text:
                unreadable.append(dict(hit))
                continue
            # 2026-11-09（D4）：缺 `## 证明` ⇒ 空串 ⇒ sha 与非空正文的 want 不可能相等
            # ⇒ 这一份不算"按正文命中的那一份"（不拿依赖段 / 全文凑一个 sha）。
            body = proof_body(text).strip("\n")
            got = hashlib.sha256(body.encode("utf-8")).hexdigest()
            if got != want:
                tried.append({"statement_id": hit.get("statement_id"),
                              "path": hit.get("path"),
                              "why": ("清单里这一份的「## 证明」正文 sha 与这一笔登记的不是"
                                      "同一份 ⇒ 不是它")})
                continue
            _hit(hit, matched_by="proof_sha")
            return {**out, "source": SOURCE_CARRIED, "text": text,
                    "path": str(hit.get("path") or ""), "sha256": sha,
                    "carried_by": str(hit.get("report") or ""), "why": ""}
        if len(unreadable) == len(candidates):
            # 清单里的每一条地址都读不到 ⇒ 这不是"清单里没有这一笔"，是"按清单寻址失败"。
            # 调用方必须受控拒绝（`REFUSED_ADDRESS`），不许降级去盘上自己找一份。
            first = unreadable[0]
            _hit(first, matched_by="")
            out["why"] = ("D 的携带单点了名，而清单里的地址一条都读不到："
                          + "；".join(str(t.get("why") or "") for t in tried[-len(unreadable):]))
            return out
    if ambiguous is not None:
        # 裸号命中了、但那一号在单上跨族出现 ⇒ 不许猜（也不许折成"单里没有这一笔"让
        # 调用方降级去盘上撞一份 —— 那正是"清单与盘不一致时猜一份稿"，本函数要防的事）。
        # 按那个调用点原本的三态语义：这一格算"清单点了名、却定位不到唯一一份"⇒
        # `named=True` + `source=none`，B 那一侧据此受控拒（`REFUSED_ADDRESS`）。
        out.update(named=True, ambiguous=dict(ambiguous),
                   address="", item=0, list_report="", list_line=0, list_sha256="",
                   manuscript_id=str(ambiguous.get("manuscript_id") or ""), why="")
        out["why"] = str(ambiguous.get("why") or "")
        tried.append({"manuscript_id": str(ambiguous.get("manuscript_id") or ""),
                      "families": list(ambiguous.get("families") or []),
                      "paths": list(ambiguous.get("paths") or []),
                      "why": out["why"]})
        return out
    if not candidates:
        out["why"] = ("D 的报告里没有「携带的证明手稿」那一节（或那一节是空的）"
                      + ("；查过：" + "、".join(str(t.get("report") or "") for t in tried)
                         if tried else "；工作区里连一份 D 报告都没有"))
    elif statement_ids:
        out["why"] = (f"D 的携带单里有 {len(index)} 条手稿，没有一条对得上这一笔的命题号"
                      f"{[str(x) for x in statement_ids][:4]}")
    else:
        out["why"] = (f"D 的携带单里有 {len(index)} 条手稿，按正文 sha 一条都没对上这一笔")
    return out

def manuscript_proof_no(text: str) -> int:
    """手稿稿头那一行"证明号：<N>"⇒ 这一份是第几份证明（没写 ⇒ 0）。

    为什么是 0 而不是 1：这一格要区分"交付里写了号"与"交付里没写"——
    后者要回退（`proof_no_source=fallback`），前者要用它（`crafted`）。
    缺省 `#p1` 的读法由调用方在"没写"那一档自己落（`or 1`），不在这里折平。

    认的写法与 `verifications.as_proof_no` 同源（`2` / `#p2` / `p2`），但只认稿头前
    12 行里以 `- 证明号` 开头的那一行 —— 正文里出现"证明号"三个字不是元信息。
    """
    head = str(text or "").replace("\r\n", "\n").split("\n")[:12]
    import re as _re

    for raw in head:
        line = raw.strip()
        if not line.startswith("- 证明号"):
            continue
        hit = _re.search(r"[:：]\s*(?:#?\s*[pP]?\s*)?([0-9]+)", line)
        if not hit:
            continue
        no = int(hit.group(1))
        if no >= 1:
            return no
    return 0


def candidate_statement_ids(*, derived_from: Iterable[Any] = (), proof_text: Any = "",
                            extra: Iterable[Any] = ()) -> list[str]:
    """"去盘上试哪几个命题号"⇒ 候选号（裸号，按出现次序去重）。

    ## 这一格只回答"试哪些名字"，不回答"能不能用那份稿"（2026-11-05 走查 D1）

    候选表里有 `derived_from`（承重链：这条证明引用了谁）与证明正文里的 `stmt:` 引用，
    是因为读数 `tried` 要能说清"按哪些号找过"（真机排障靠这一格）。但命中之后，
    那份稿能不能当这一条命题的稿用是另一件事，判据在收方
    （`agent_b/register_statement.py::_manuscript_usable`）：兜底读盘命中一份
    "号不是本行"的稿时不许用它 —— 改前正是缺了这一道，`walk-e2e-20261105` 的
    `stmt:000001` 才把 `stmt:000000` 的稿读成了自己的正文（连签一起借来）。

    - `derived_from`：B 交上来的承重链（自己的或外部的上下文命题）；
    - 证明正文里的 `stmt:` 引用（`stmt_refs` 是全仓唯一那条扫描，这里不另写一份）；
    - `extra`：调用方手上多出来的号（例如 D 的手稿点名了 F 的那一条）。

    只要形状是合法号（`schema.is_valid_id`）就收：这一层判的是"去盘上找哪几个名字"，
    "那个号在不在册"不是它的判据（盘上找得到稿、而号不在册，是另一件事，
    由引用档位门与 `derived_from` 那几处各自点名）。
    """
    out: list[str] = []

    def _take(raw: Any) -> None:
        sid = str(raw or "").strip().split("#", 1)[0].split(":", 1)[-1].strip()
        if sid and S.is_valid_id(sid) and sid not in out:
            out.append(sid)

    for raw in derived_from or ():
        _take(raw)
    for raw in stmt_refs(proof_text):
        _take(raw)
    for raw in extra or ():
        _take(raw)
    return out



def gate_rows(rows: Iterable[Mapping[str, Any]],
              statement_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """逐条核"来源在册 / 可用 / 档位够不够" ⇒ 一份可整笔拒绝的读数。

    返回 `{"checked", "ok", "refused", "reason", "levels", "finding", "findings"}`。
    `refused` 是受控码、`reason` 是四元组那句人话（号 + 第几行 / 第几步 + 类别 +
    期望 / 实得 + 怎么改），`finding` / `findings` 是同一句话的六格形态（业主
    2026-11-06：每条异常都要给得出"是哪一条、哪一类、差在哪、怎么改"）。
    判据顺序：在册 → 状态可用 → 档位读得到 → 档位够。先报最具体的那一条
    （"这条号不在册"比"档位不够"更能让人立刻改对）。

    ## 不在册 / 等级不够 ⇒ 受控拒（2026-11-06 业主口径的纠正）

    改前（`53ec0477`）不许整笔拒：不在册的那一行落 `dangling` 交回调用方、整笔照写。
    业主 2026-11-06 纠正：「F 应该无法读到尚未在册的命题」—— 那种号 F 读不到，
    所以依赖表里点它只可能是这一笔写错了。这一档恢复成 `REFUSED_UNKNOWN_SOURCE`
    （受控拒），拒信逐字点名那个号、说清"它不在册，F 读不到它"；等级不够那一档
    照旧 `REFUSED_LEVEL_TOO_LOW`（`pre_theorem` 以下不可引）。两档都由
    :func:`uncitable_statement_problem` 一处产生，与 F 的可引池同源。
    """
    index = SL.index_by_id(statement_rows)
    ledger = list(index.values())
    levels: dict[str, str] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or "")
        if sid in index:
            levels[sid] = statement_grade(index[sid])
        #: 四元组里的"哪一步"两样都写：表行号（`line`）与表里自己写的步号。
        got = uncitable_statement_finding(
            sid, ledger, where="依赖段", line=int(row.get("line") or 0),
            step=_first_number(row.get("step")))
        if got:
            return {"checked": True, "ok": False, "refused": str(got["kind"]),
                    "levels": levels, "reason": str(got["detail"]),
                    "finding": got, "findings": [got]}
    return {"checked": True, "ok": True, "refused": "", "reason": "", "levels": levels,
            "finding": {}, "findings": []}


def deps_groups(rows: Iterable[Mapping[str, Any]],
                kinds: Mapping[str, str]) -> list[list[dict[str, Any]]]:
    """解析出来的行 ⇒ 秘书那一侧要的二维列表（外层 = 路径组，内层 = 组内每一步）。

    组号 = 路径号（"第几条证明"）：一份证明就是一条可选路径，于是 `used_by` 会落成
    `stmt:<命题号>#pN`，`path_group` 也是 N —— 与多证明模型的两维口径同一个意思
    （组内 AND／组间 OR）。第 1 组不带 `#pN` 尾巴（`proofloc` 的既有口径）。

    `kinds` 是台账里那批命题的 `{号: kind}`（调用方按 `statements` 现读）。不在册的
    行到不了这里：`gate_rows` 已经在上一道把它们受控拒了（2026-11-06 业主口径：
    F 读不到尚未在册的命题）。所以这里只负责把已核实过的行翻成步骤。
    """
    groups: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or "")
        group = int(row.get("path_group") or 1)
        groups.setdefault(group, []).append({
            "stmt_id": sid,
            "kind": str(kinds.get(sid) or "theorem"),
            "label": f"手稿依赖段（第 {row.get('line')} 行）：{row.get('quote')}",
            "quote": str(row.get("quote") or ""),
            "path_group": group,
            # 多证明那一维：`_write_dep_steps` 据此落 `used_by="stmt:<号>#pN"`。
            "proof_no": group,
            # 手稿里点名的步骤（读数用，不参与落库）
            "manuscript_step": str(row.get("step") or ""),
        })
    return [groups[no] for no in sorted(groups)]


#: 引文对比的两个长度门槛（归一之后）：太短的片段（"由定理""见上文"）在几十条命题里
#: 必然撞上，报出来就是噪音 —— 噪音会把整条告警训练成没人看（DEVELOPMENT-SPEC §8 P15）。
#: "整段相等"比"是它的一段摘录"更硬，所以门槛更低一点。
QUOTE_MATCH_MIN_CHARS = 16
QUOTE_EQUAL_MIN_CHARS = 10


def _norm_citation_text(text: Any) -> str:
    """引文对比用的归一：去空白 / 标点 / markdown 记号，只留字与数字。"""
    return "".join(ch for ch in str(text or "") if ch.isalnum())


def _summary(text: Any, *, limit: int = 48) -> str:
    """一句话摘要（对比读数用；超过 `limit` 截断并加省略号，不把整段原文抄进拒信）。"""
    raw = " ".join(str(text or "").split())
    return raw if len(raw) <= limit else raw[:limit] + "…"


def _quote_matches(quote: str, row: Mapping[str, Any], *,
                   exact_floor: int = QUOTE_EQUAL_MIN_CHARS,
                   contain_floor: int = QUOTE_MATCH_MIN_CHARS) -> bool:
    """归一后的引文是不是这一行的原文（整段相等，或一段不短于门槛的原文摘录）。"""
    for field in ("statement_full", "statement_text"):
        text = _norm_citation_text(row.get(field))
        if not text:
            continue
        if quote == text and len(quote) >= exact_floor:
            return True
        if quote in text and len(quote) >= contain_floor:
            return True
    return False


def quote_mismatch_finding(row: Mapping[str, Any],
                           statement_rows: Iterable[Mapping[str, Any]]
                           ) -> dict[str, Any]:
    """表里那一行的引文是不是另一条在册命题的原文 ⇒ 一条六格（表述错误 a 类）。

    ## 只有"能证明"才报（这一条决定了它会不会变成噪音）
    引文那一格在 F 的渲染器里写的是"这一步的原话"，它本来就不等于被引命题的正文
    （`agent_f/manuscript.py::dependency_rows`）。所以拿"读起来不像"当判据，会把每一份
    正常手稿都判红。可判的只有一件事：这段引文逐字（归一空白与标点后）等于另一条
    在册命题的 `statement_full` / `statement_text` —— 那时号和引文至少有一个写错了，
    而两种情况都有确定的改法（改号 / 改引文）。

    先看被引的那一条：引文对得上它 ⇒ 放行（哪怕它同时也像别人）。

    空字典 = 没发现可判的引错内容（不是"核过了、没问题"的另一种写法：这一档的判据
    面就是上面那一条，核不到另一条命题的原文时它没有结论可说）。
    """
    sid = str(row.get("stmt_id") or "")
    quote = _norm_citation_text(row.get("quote"))
    if len(quote) < QUOTE_EQUAL_MIN_CHARS:
        return {}
    index = SL.index_by_id(statement_rows)
    anchor = index.get(sid) or {}
    if _quote_matches(quote, anchor, exact_floor=0, contain_floor=0):
        return {}
    for other_id, other in index.items():
        if other_id == sid or not _quote_matches(quote, other):
            continue
        return citation_finding(
            stmt_id=sid,
            where=_citation_where(line=int(row.get("line") or 0),
                                  step=_first_number(row.get("step"))),
            kind=REFUSED_QUOTE_MISMATCH,
            expected=(f"引文对得上 `stmt:{sid}` 的原文（`statement_full`）："
                      f"{_summary(anchor.get('statement_full'))}"),
            got=(f"引文「{_summary(row.get('quote'))}」与 `stmt:{other_id}` 的原文逐字相同："
                 f"{_summary(other.get('statement_full'))}"),
            fix=(f"改号或改引文：若引的其实是 `stmt:{other_id}`，把这一行的命题号改成它；"
                 f"若引的是 `stmt:{sid}`，把引用那一格换成它的原文摘要"),
            step=_first_number(row.get("step")))
    return {}


def manuscript_citation_resolver(
        cited: Mapping[str, Mapping[str, Any]]):
    """V 只读手稿时的可引资格解析器（供 :func:`dependency_review` 的 `admissibility=`）。

    `cited` 的形如 `{stmt_id: {found, manuscript, statement_full, signed, why, tried}}`
    （`agent_v.core._cited_manuscripts` 的产物）。返回一个
    `(sid, *, where, line, step) -> 六格 finding 或 {}` 的闭包。

    为什么用一个解析器而不是再写一份 `dependency_review`：④⑤⑦ 三项（表与正文一致 /
    步号 / 引文归属）与"册子"那一版逐字相同，只有 ①②③ 的"可引资格"来源不同 ——
    抄第二份判据必然漂，而漂的那一处正好会是"V 放行了一条其实不可引的引用"。
    """
    def _resolve(sid: str, *, where: str = "", line: int = 0,
                 step: Any = None) -> dict[str, Any]:
        return manuscript_uncitable_finding(str(sid), cited, where=where,
                                            line=line, step=step)
    return _resolve


def manuscript_uncitable_finding(
        sid: str, cited: Mapping[str, Mapping[str, Any]], *,
        where: str = "", line: int = 0, step: Any = None) -> dict[str, Any]:
    """`stmt:<sid>` 在"V 只读手稿"这一口径下为什么不可引 ⇒ 六格；空字典 = 可引。

    可引判据与册子那一版同一条政策（`CITATION_MIN_LEVEL = "pre_theorem"`），
    但证据来源换成手稿：被引命题必须有一份盘上的手稿（`reports/f-proof-<号>.md` 或
    `reports/b-proof-<号>.md`），而且那份稿的现在这一份正文上盖着一份 V 签
    （`vsigns.manuscript_sign_standing` 的 `signed`）。

    两档受控码刻意复用既有码，不新造：
    - 手稿不在 / 读不成 ⇒ `REFUSED_LEVEL_UNREADABLE`（"等级读不出来（判不了）"）——
      读不到正文与签，就判不了它够不够格；
    - 手稿在、没有盖住现行正文的签 ⇒ `REFUSED_LEVEL_TOO_LOW`（"等级不到可引门槛"）。
    两档的期望 / 实得 / 怎么改都按"稿"写，不冒充"不在册"（V 读不到册，说"不在册"
    就是编一句它没查过的话）。
    """
    site = str(where or "").strip()
    where_text = _citation_where(step=step, line=line, site=site or "依赖段")
    item = dict(cited.get(str(sid)) or {})
    if not item.get("found"):
        return citation_finding(
            stmt_id=str(sid), where=where_text, kind=REFUSED_LEVEL_UNREADABLE,
            expected=(f"盘上有一份这一条命题的手稿（`reports/f-proof-<号>.md`；"
                      f"V 只读手稿：正文与签都在稿上）"),
            got=(f"盘上没有这一条命题的手稿（找过：{item.get('tried') or '（没记）'}）"
                 "⇒ 读不到它的正文，也读不到它的签"),
            fix=("先把这一条命题的证明落成一份手稿（`reports/f-proof-<号>.md`，"
                 "`## 命题` / `## 证明` / `## 依赖` 三节），再引它；"
                 "V 不从台账读正文"),
            step=step)
    if not item.get("signed"):
        return citation_finding(
            stmt_id=str(sid), where=where_text, kind=REFUSED_LEVEL_TOO_LOW,
            expected=(f"`{item.get('manuscript')}` 的现在这一份正文上有一份 V 签"
                      f"（等级 ≥ {CITATION_MIN_LEVEL}）"),
            got=(f"`{item.get('manuscript')}` 上没有盖住正文 sha 的 V 签"
                 f"（{item.get('why') or '未签'}）"),
            fix=("先让 V 把这一条命题的证明审成「成立」、签落在稿上"
                 f"（到 {CITATION_MIN_LEVEL} 级），再来引它"),
            step=step)
    return {}


def dependency_review(text: str,
                      statement_rows: Iterable[Mapping[str, Any]],
                      *, admissibility: Any = None) -> dict[str, Any]:
    """V 审稿时对 `## 依赖` 面的六项逐条核 ⇒ 一份可并入 verdict 的读数。

    业主 2026-11-06 逐字：「引用未在册命题应该在 V 审阅时就被打回，轮不到 B」。
    所以 V 是第一道（主要防线），B 的受控拒是第二道兜底；两道都保留，判据同源
    （同一个 :func:`citable_pool` / :func:`uncitable_statement_problem`）。

    ## 六项（任一项不成立 ⇒ 一条 `level=error` 的 finding，点名哪个号、差在哪）

    | # | 项目 | 判据 |
    |---|---|---|
    | ① | 正文里每个 `stmt:<号>` 都在册 | `uncitable_statement_finding` |
    | ② | 每个被引号等级 ≥ `pre_theorem` | 同上（`conjecture` / `strong_conjecture` 不可引） |
    | ③ | `## 依赖` 表每一行点名的号同样满足 ① 与 ② | 同上，坐标写成"第几行 + 表里写的步号" |
    | ④ | 表与正文的引用集合一致 | 两边的差集逐条点名（正文点了没写行 / 表里多一行） |
    | ⑤ | 表里"用在哪一步"与正文那一步的 `cites` 对得上（可核时） | 步号不在正文 / 那一步没引这个号 |
    | ⑥ | 引用强度（不得把被引命题写强） | 不在这里：已有那一档（`citation_checks` / `citation_gate`） |
    | ⑦ | 引文与被引命题的原文是不是同一条（表述错误 a 类） | `quote_mismatch_finding`（只在能证明引文属于另一条在册命题时才报） |

    ①②③ 的「可引资格」来源可由 `admissibility=` 换（2026-11-08：V 只读手稿那一档传
    :func:`manuscript_citation_resolver`，判据变成"被引命题的手稿在盘上、且盖着 V 签"）；
    缺省仍是册子那一版（`:func:`uncitable_statement_finding`），B / 旧调用方逐字不变。

    ⑤的边界（如实说）：手稿的三列表里没有被引命题的 `proof_no` / 正文 sha 这两格，
    所以"proof_no / sha"那一半没有可核的载体；能核的是"表里说用在第几步"与
    "正文那一步的 `cites`"对不对得上。正文没有编号行（`proof_steps` 为空）时这一项
    不核（"可核时"），不猜。

    ## 返回（每一条都带四元组六格）

    `{"checked", "ok", "findings", "defect_step", "why"}`。`findings` 的每一项是
    台账那一行的四格 `{"level": "error", "step": 步号, "kind": 受控码, "detail": 人话}`
    再加上引用面的六格（`:data:`FINDING_CELLS`）：`stmt_id` / `where` / `expected` /
    `got` / `fix`。六格为什么同时写进 `detail`：台账那一行的 finding 形状由
    `verifications.parse_verdict` 钉死为四格（另一个落点，本模块不越界），所以
    人话是那一行里唯一能承载六格的地方；结构化六格供调用方（与判据）直接读。

    `detail` 的每一句都逐字含"那个号 + 在哪一步 + 哪一类 + 期望 / 实得 + 怎么改"
    （业主 2026-11-06：「反馈给提交证明者的信息需指出具体是哪条」）。
    """
    raw = str(text or "")
    ledger = [dict(r) for r in statement_rows]
    steps = proof_steps(raw)
    #: 2026-11-09（D4）：缺 `## 证明` ⇒ 正文引用为空（不回退）。这不是"自足"的证明：
    #: 表里每一行都会在 ④ 被报成"证明正文没有点它"，由调用方整笔拒。
    body_refs = stmt_refs(proof_body(raw))
    section = parse_dependency_section(raw)
    rows = [dict(r) for r in (section.get("rows") or [])]
    findings: list[dict[str, Any]] = []
    flagged: set[str] = set()

    def _step_of(ref: str) -> int | None:
        return _first_step_of(ref, steps)

    def _row_step(row: Mapping[str, Any]) -> int | None:
        nos = _step_numbers(row.get("step"))
        present = [n for n in nos if n in steps]
        if present:
            return min(present)
        if nos:
            return min(nos)
        return _step_of(str(row.get("stmt_id") or ""))

    def _add(record: Mapping[str, Any]) -> None:
        """六格记录 + 台账那一行的四格 ⇒ 一条 finding（同一条判据两处落点）。"""
        step = record.get("step") if isinstance(record.get("step"), int) else None
        findings.append({
            "level": "error", "step": step, "kind": str(record.get("kind") or ""),
            "detail": str(record.get("detail") or ""),
            # 六格：台账那一行留不住它们（`parse_verdict` 只留四格），但返回读数留住，
            # 而 `detail` 那句人话把六格的值全写进去了。
            "stmt_id": str(record.get("stmt_id") or ""),
            "where": str(record.get("where") or ""),
            "expected": str(record.get("expected") or ""),
            "got": str(record.get("got") or ""),
            "fix": str(record.get("fix") or ""),
        })

    def _admissible(ref: str, *, where: str, step: Any = None,
                    line: int = 0) -> dict[str, Any]:
        """①②③ 的可引资格：调用方给了 `admissibility` 就用它（V 只读手稿那一档），
        否则仍走册子那一版。判据本体只有一处，两种来源在这一格分叉、四个判据共用。"""
        if admissibility is not None:
            return dict(admissibility(str(ref), where=where, step=step, line=line) or {})
        return uncitable_statement_finding(ref, ledger, where=where, step=step,
                                           line=line)

    # ①② 正文里的号：在册 ∧ 等级够。
    for ref in body_refs:
        got = _admissible(ref, where="证明正文", step=_step_of(ref))
        if not got:
            continue
        flagged.add(ref)
        _add(got)

    # ③ `## 依赖` 表里的号：同样要在册 ∧ 等级够（同一个判据，坐标换成行号 + 表里写的步号）。
    # `table_set` 就是下面 ④ 要用的那张集合：改前先攒一个 `table_ids` 列表（每行一次
    # `sid not in table_ids` 的线性查重 ⇒ O(行数²)）再 `set(table_ids)` 转一次，
    # 而那个列表除了这一次转换没有任何读者。这里是同一趟里直接进集合。
    table_set: set[str] = set()
    for row in rows:
        sid = str(row.get("stmt_id") or "")
        table_set.add(sid)
        if sid in flagged:
            continue
        got = _admissible(
            sid, where="依赖段", line=int(row.get("line") or 0),
            step=_first_number(row.get("step")))
        if got:
            flagged.add(sid)
            _add(got)

    # ⑦ 表述错误 a 类：表里那一行的引文写的是另一条在册命题的原文。
    for row in rows:
        got = quote_mismatch_finding(row, ledger)
        if got:
            _add(got)

    # ④ 表与正文的引用集合必须一致：两边差集逐条点名（表多一行也是缺陷）。
    body_set = set(body_refs)
    for ref in body_refs:
        if ref in table_set:
            continue
        no = _step_of(ref)
        _add(citation_finding(
            stmt_id=ref, where=_citation_where(step=no, site="证明正文"),
            kind=REFUSED_TABLE_DISAGREES,
            expected=(f"手稿的 `{SECTION_HEADING}` 表里有一行 `stmt:{ref}`"
                      "（写明它用在哪一步）"),
            got="表里没有这一行",
            fix=("把表里那一行补上（号与用在哪一步都写对）；正文是 F 的署名作品，"
                 "表按它补齐 —— 两处必须说的是同一件事"),
            step=no))
    for row in rows:
        sid = str(row.get("stmt_id") or "")
        if sid in body_set:
            continue
        no = _row_step(row)
        _add(citation_finding(
            stmt_id=sid, where=_citation_where(step=no, line=int(row.get("line") or 0)),
            kind=REFUSED_TABLE_DISAGREES,
            expected="证明正文里有一步 cite 它（那一步的 `cites` 里含这个号）",
            got="证明正文没有点它（0 处引用）",
            fix=("删掉表里那一行（它多出来了），或把正文那一步的 `cites` 补上它 —— "
                 "两处必须说的是同一件事"),
            step=no))

    # ⑤ 表里"用在哪一步"与正文那一步的 cites 对得上（正文有编号行时才核）。
    if steps:
        for row in rows:
            sid = str(row.get("stmt_id") or "")
            nos = _step_numbers(row.get("step"))
            if not nos or sid in flagged:
                continue
            absent = [n for n in nos if n not in steps]
            if absent:
                _add(citation_finding(
                    stmt_id=sid,
                    where=_citation_where(line=int(row.get("line") or 0),
                                          step=min(absent)),
                    kind=REFUSED_STEP_MISMATCH,
                    expected=(f"证明正文里有第 {'、'.join(str(n) for n in absent)} 步"
                              "（表说它用在那一步）"),
                    got=(f"证明正文只有第 {'、'.join(str(n) for n in sorted(steps))} 步，"
                         "没有表里写的那一步"),
                    fix=("把表里'用在哪一步'改成正文里真实的那一步（号不变）；"
                         "若那一步本来就该在，先把它补进正文再交"),
                    step=min(absent)))
                continue
            cited_here: set[str] = set()
            for n in nos:
                cited_here.update(str(x) for x in (steps[n].get("cites") or []))
            if sid not in cited_here:
                shown = "、".join(f"stmt:{x}" for x in sorted(cited_here)) or "（没有引用）"
                _add(citation_finding(
                    stmt_id=sid,
                    where=_citation_where(step=min(nos),
                                          line=int(row.get("line") or 0)),
                    kind=REFUSED_STEP_MISMATCH,
                    expected=(f"第 {'、'.join(str(n) for n in nos)} 步的 `cites` 里含 "
                              f"`stmt:{sid}`"),
                    got=f"第 {'、'.join(str(n) for n in nos)} 步引的是 {shown}",
                    fix=("改表里那一格：写正文真正引它的那一步；若表是对的，就把正文"
                         "那一步的 `cites` 补上它（正文与表必须说的是同一件事）"),
                    step=min(nos)))

    if not findings:
        return {"checked": True, "ok": True, "findings": [], "defect_step": None,
                "why": ""}
    stepped = [int(f["step"]) for f in findings if isinstance(f.get("step"), int)]
    defect_step = min(stepped) if stepped else (min(steps) if steps else 1)
    shown = "；".join(str(f["detail"]) for f in findings[:3])
    more = f"；另有 {len(findings) - 3} 条" if len(findings) > 3 else ""
    return {"checked": True, "ok": False, "findings": findings,
            "defect_step": defect_step, "why": shown + more}


# ------------------------------------------------------------------ 渲染（唯一实现）

def render_dependency_section(rows: Iterable[Mapping[str, Any]]) -> str:
    """把依赖行渲染成那一节固定格式的表格（表头三列，逐字与解析器对齐）。

    唯一实现放在这里（解析与渲染必须同一个人写，否则"渲染出来的格式解析器读不懂"
    这种形态没有任何地方会报）：F 的手稿渲染与秘书洗稿后的重渲染都读它。
    产出侧只写必填列：路径号（第几条证明）由 B 的秘书在收录时分配，不进稿
    （对齐之后产出侧不标注它）。老盘上带那一列的四列表仍读得回（解析侧可选列）。
    一条引用都没有时也把表头留着，并写一行"空表就是声明" —— 于是"这份证明是自足的"
    与"作者忘写了这一节"在收方那侧读得不一样（三态不是靠猜的）。
    """
    shown = [one for one in COLUMN_KEYS if one[0] != "path_group"]
    head = "| " + " | ".join(name for _f, _k, name in shown) + " |"
    rule = "|" + "|".join("---" for _ in shown) + "|"
    lines = [SECTION_HEADING, "", head, rule]
    count = 0
    for row in rows:
        lines.append("| {quote} | stmt:{sid} | {step} |".format(
            quote=str(row.get("quote") or "").replace("|", "／"),
            sid=str(row.get("stmt_id") or ""),
            step=str(row.get("step") or "")))
        count += 1
    if not count:
        lines.append("")
        lines.append("（这一份证明没有引用任何在册命题 —— 空表就是声明。）")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ 作者侧洗稿（F 的秘书）
#
# 业主 2026-10-26 晚的原话（逐字）：「F写证明时务必加依赖面命题号，且由F的秘书对无引用
# 证明忘加空依赖面的补空，对有引用证明的命题号核实（即秘书帮它洗一遍）」
# 「F的秘书工作的时候是F写好了，提交证明给V前」。
#
# 所以这一段是"提交给 V 之前"的那一遍：它只动依赖面（命题号 / 那一段的格式），
# 绝不改证明正文（正文是 F 的署名作品）。洗出来的那一份才是交给 V、交给 D 携带的稿。

#: 无引用而缺节 ⇒ 秘书补一个空节的读数。
WASH_FILLED_EMPTY = "empty_by_secretary"
#: 有引用而缺节 / 那一段读不懂 ⇒ 秘书按证明正文的 `cites` 重渲染那一节的读数
#: （依赖面永远由代码生成，不由模型自由发挥）。
WASH_RENDERED = "rendered_from_proof"
#: 洗不动而退回 F 的受控码（"这一份先别交给 V"）。
WASH_REFUSED_ROW = "dependency_row_unverified"
#: 依赖段里的号不在册（退回 F）—— 与 B 那一侧同一个受控码。
WASH_REFUSED_UNKNOWN = REFUSED_UNKNOWN_SOURCE


def proof_steps(text: str) -> dict[int, dict[str, Any]]:
    """`## 证明` 那一节里"第几步说了什么、引了哪些 `stmt:`"⇒ `{步号: {text, cites}}`。

    步号取行首的 `N.`（F 的渲染器与真机手稿都是这个形状）。认不出步号的行不进
    这张表：它是"没有编号的散文"，不是第几步。
    """
    import re as _re

    body, _start = section_lines(text, SECTION_PROOF)
    if not body:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for _ln, raw in body:
        line = str(raw or "").strip()
        if not line:
            continue
        hit = _re.match(r"^(\d+)\s*[.、)]\s*(.*)$", line)
        if not hit:
            continue
        no = int(hit.group(1))
        out[no] = {"text": hit.group(2).strip(), "cites": stmt_refs(hit.group(2))}
    return out


def _step_numbers(step_text: Any) -> list[int]:
    """依赖段那一格"第 1、3 步"⇒ `[1, 3]`（认不出就是个空列表，不猜）。"""
    import re as _re

    return [int(x) for x in _re.findall(r"\d+", str(step_text or ""))]


def _rows_from_proof(text: str) -> list[dict[str, Any]]:
    """按证明正文的 `cites` 现渲染依赖行（洗稿重建那一节的唯一口径）。

    与 `agent_f/manuscript.py::dependency_rows` 同一件事（一处渲染、一处解析；
    这里用的是同一份 `proof_steps`），所以"F 渲染出来的"与"秘书重建出来的"同形。
    """
    steps = proof_steps(text)
    rows: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for no in sorted(steps):
        for cite in steps[no]["cites"]:
            if cite in index:
                rows[index[cite]]["steps"].append(no)
                continue
            index[cite] = len(rows)
            rows.append({"stmt_id": cite, "quote": str(steps[no]["text"])[:80],
                         "steps": [no], "path_group": 1})
    for row in rows:
        row["step"] = "第 " + "、".join(str(n) for n in row.pop("steps")) + " 步"
    return rows


def _replace_section(text: str, section_text: str) -> str:
    """把 `## 依赖` 那一节整段换成 `section_text`（没有那一节就接在文末）。

    边界与 :func:`section_lines` 同一份口径（2026-11-10：同级 / 更高级的标题才是边界，
    `### ` 算节内）—— 改前这里另抄了一遍"任何 `#` 都截断"，收成一份之后洗稿不会
    把 `## 依赖` 下面更深的小标题当成下一节而留在原地。
    """
    raw = str(text or "").replace("\r\n", "\n")
    lines = raw.split("\n")
    body, start = section_lines(raw)
    if not start:
        return raw.rstrip("\n") + "\n\n" + section_text
    end = start + len(body)
    head = lines[: start - 1]
    tail = lines[end:]
    while head and not head[-1].strip():
        head.pop()
    out = "\n".join(head + [""] + section_text.rstrip("\n").split("\n"))
    rest = "\n".join(tail).strip("\n")
    return out + ("\n\n" + rest if rest else "") + "\n"


#: 洗过的那一份手稿里那一行元信息的固定前缀（B 侧据此读 `manuscript_washed=true`）。
WASH_MARK = "- 依赖面洗稿："
#: 洗稿元信息的行内键（渲染与解析共用，避免两处各写一个拼法）。
WASH_MARK_ACTOR = "执行者"
WASH_MARK_FILLED = "补节"
WASH_MARK_TAG = "已洗"


def mark_washed(text: str, *, actor: str = "", filled: str = "") -> str:
    """在洗过的手稿里盖一行元信息（幂等：先删旧的同一行，再插到 `- 计划：` 之后）。

    为什么要把"这一份被秘书洗过"写进正文而不是只存在调用方内存里：D 携带、B 读的
    都是盘上那一份文件；读数必须跟着文件走，否则"B 读到的是不是洗过的那一版"
    在收方那侧无从判断（而那正是这条链要回答的问题）。
    """
    raw = str(text or "").replace("\r\n", "\n")
    lines = [ln for ln in raw.split("\n") if not ln.strip().startswith(WASH_MARK)]
    parts = [f"{WASH_MARK_TAG}=true"]
    if str(actor or "").strip():
        parts.append(f"{WASH_MARK_ACTOR}={str(actor).strip()}")
    if str(filled or "").strip():
        parts.append(f"{WASH_MARK_FILLED}={str(filled).strip()}")
    # 形如：`- 依赖面洗稿：已洗=true；执行者=secretary-F；补节=empty_by_secretary`
    mark = WASH_MARK + "；".join(parts)
    at = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("- 计划："):
            at = i + 1
            break
    else:
        at = min(2, len(lines))
    lines.insert(at, mark)
    return "\n".join(lines)


def manuscript_wash_reading(text: str) -> dict[str, Any]:
    """读手稿里那一行洗稿元信息 ⇒ `{washed, actor, filled, mark}`（没有就 `washed=False`）。

    三态纪律：没有那一行 = "这一份没被洗过"（`washed=False`），不是"洗过、没变化"。
    """
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line.startswith(WASH_MARK):
            continue
        body = line[len(WASH_MARK):]
        cells = dict(
            tuple(cell.split("=", 1)) for cell in body.split("；") if "=" in cell)
        return {"washed": str(cells.get(WASH_MARK_TAG) or "").lower() == "true",
                "actor": str(cells.get(WASH_MARK_ACTOR) or ""),
                "filled": str(cells.get(WASH_MARK_FILLED) or ""),
                "mark": line}
    return {"washed": False, "actor": "", "filled": "", "mark": ""}


def wash_dependency_section(text: str, *,
                            statement_rows: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """秘书那一遍洗稿：只洗依赖面，不改证明正文（业主 2026-10-26 晚的裁定）。

    三件事，按顺序：

    1. `## 依赖` 那一节缺了、或者读不懂 ⇒ 由代码重渲染（有 `cites` 就按正文现算行，
       一条都没有就落一个空节 + 一行"空表就是声明"）。读数 `deps_section_filled`：
       `empty_by_secretary`（无引用补空）/ `rendered_from_proof`（按正文重渲染）；
    2. 每一条依赖行的命题号逐条核：
       - 不在册 ⇒ 洗不动，整份退回 F（`deps_refused=dependency_source_not_registered`，
         点名第几行、哪个号）—— 这一份不许交给 V；
       - 在册、而且它说"用在哪一步"与那一步 `cites` 对不上 ⇒ 能确定正确号时洗成那个号
         （`deps_washing=[{line, from, to, why}]`），不能确定（那一步引了不止一条，
         或一条都没引）⇒ 退回；
       - 对得上 ⇒ 原样留下。
    3. 洗过才重渲染那一节（没动过就逐字原样返回，`washed=False` —— 这一步是幂等的）。

    ## 为什么用"那一步的 cites"当核实依据，而不是拿 label 与 F 的原话比
    `quote` 那一格是 F 说"我在这一步怎么用它"，不是那条命题的正文 —— 拿它去和
    label 比相似度，得到的是措辞的巧合，而不是判断（本仓最忌的"看起来像判据"）。
    真正可判的是同一份手稿里两处对同一个号的说法：正文那一步引了谁、依赖表说引了谁。
    它们对不上时，错的只能是依赖表那一格（正文是 F 的署名作品，秘书不改它）。

    返回 `{checked, washed, text, deps_section_filled, deps_washing, deps_refused,
    reason, section, rows, columns_ok}`：`text` 是洗过的那一份（退回时是原文）。
    """
    raw = str(text or "")
    index = SL.index_by_id(statement_rows)
    section = parse_dependency_section(raw)
    out: dict[str, Any] = {
        "checked": True, "washed": False, "text": raw,
        "deps_section_filled": "", "deps_washing": [], "deps_refused": "",
        "reason": "", "section": section, "rows": [],
        # 认不出的行 / 列问题由 `section` 自己带（`problems`），这里只回放它的结论。
        "columns_ok": not bool(section.get("problems")),
    }
    # 2026-11-09（D4）：缺 `## 证明` ⇒ refs 为空（不回退）⇒ 依赖段缺了也只按
    # `proof_steps` 重建；"正文里引了而表里没写"这一档需要正文存在，缺节时无从谈起。
    refs = stmt_refs(proof_body(raw))
    filled = ""
    rows: list[dict[str, Any]]
    if not section.get("present"):
        rows = _rows_from_proof(raw)
        filled = WASH_RENDERED if rows else WASH_FILLED_EMPTY
    elif section.get("problems"):
        rows = _rows_from_proof(raw)
        filled = WASH_RENDERED
    else:
        rows = [dict(r) for r in section.get("rows") or []]
        # 那一节读得懂但是空的、而正文里确实有 `stmt:` 引用 ⇒ 表是漏写的：
        # 按正文的 `cites` 重建（这是"能确定"的那一档，不猜）。
        if not rows and refs:
            rows = _rows_from_proof(raw)
            if rows:
                filled = WASH_RENDERED
    steps = proof_steps(raw)
    kept: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    def _finding(*, line: int, quote: str, got: str, expected: str, why: str,
                 how_to_fix: str, stmt_id: str = "",
                 kind: str = WASH_REFUSED_ROW,
                 step: Any = None) -> dict[str, Any]:
        """一条"打回"的逐条说明（哪一行 / 写的什么 / 该是什么 / 为什么 / 怎么改）。

        洗稿这一侧原有的六个键（`line` / `quote` / `got` / `expected` / `why` /
        `how_to_fix`）一个不改 —— 它们是 F 的秘书那一侧既有的读法。这里补上四元组
        缺的 `stmt_id` 与 `where`、受控码 `kind`、`fix`（与 `how_to_fix` 同值，
        四元组那一边的名字）与 `detail`（号 + 哪一步 + 哪一类 + 怎么改 的那一句）。
        """
        where_text = _citation_where(line=int(line), step=step, site="依赖段")
        record = citation_finding(
            stmt_id=stmt_id, where=where_text, kind=kind, expected=expected,
            got=(got if not quote else f"{got}（表里那一行的引文：{_summary(quote)}）"),
            fix=how_to_fix, step=step)
        return {"line": int(line), "quote": str(quote or ""), "got": str(got or ""),
                "expected": str(expected or ""), "why": str(why or ""),
                "how_to_fix": str(how_to_fix or ""),
                "stmt_id": record["stmt_id"], "where": record["where"],
                "kind": record["kind"], "fix": record["fix"],
                "detail": record["detail"]}

    # 结构都读不懂、而正文里又没有 `cites` 可以据以重建 ⇒ 打回（不许猜一行出来）。
    # 注意"缺节 + 一条引用都没有"不是这一档：那是自足证明，秘书补一个空节即可。
    if not rows and (refs or section.get("problems")):
        reason = str(section.get("reason") or "").strip()
        findings.append(_finding(
            line=int(section.get("heading_line") or 0),
            quote="（依赖段缺失或读不懂）",
            got=f"present={bool(section.get('present'))}，problems={len(section.get('problems') or [])}",
            expected="一张三列的表（引用 / 命题号 / 用在哪一步）",
            why=(reason or f"手稿里没有 `{SECTION_HEADING}` 这一节，而证明正文里也没有可据以重建的 `stmt:` 引用"),
            how_to_fix=(f"在证明手稿里补一节 `{SECTION_HEADING}`（三列必填；路径号不进稿），"
                        "或者在证明正文的每一步写明依据（`stmt:NNNNNN`）—— 依赖面由代码按它渲染"),
            kind=REFUSED_SECTION))
    for row in rows:
        sid = str(row.get("stmt_id") or "")
        line = int(row.get("line") or 0)
        quote = str(row.get("quote") or "")
        anchor = index.get(sid)
        step_no = _first_number(row.get("step"))
        if anchor is None:
            findings.append(_finding(
                line=line, quote=quote, got=f"stmt:{sid}", stmt_id=sid,
                kind=REFUSED_UNKNOWN_SOURCE, step=step_no,
                expected="（无法确定 —— 请自己指认台账里真实的那一条）",
                why=(f"第 {line} 行点名的 `stmt:{sid}` 不在册"
                     f"（台账里现有 {len(index)} 条命题）"),
                how_to_fix=(f"把 `stmt:{sid}` 改成台账里真实的一条在册命题号"
                            "（`attack.step` 的返回值里有本轮可引 id 清单），并让正文那一步写明依据")))
            continue
        level = statement_grade(anchor)
        if not level:
            findings.append(_finding(
                line=line, quote=quote, got=f"stmt:{sid}（等级算不出来）", stmt_id=sid,
                kind=REFUSED_LEVEL_UNREADABLE, step=step_no,
                expected=f"{CITATION_MIN_LEVEL} 级及以上",
                why=(f"第 {line} 行点名的 `stmt:{sid}` 等级算不出来"
                     "（五元位读不出 / 现算出空）⇒ 读不到就不许引"),
                how_to_fix=("先让 V 走查签「成立」（或形式化 / 穷举核过）把它升到 "
                            f"{CITATION_MIN_LEVEL} 级，再引它")))
            continue
        if not citation_level_allowed(level):
            findings.append(_finding(
                line=line, quote=quote, got=f"stmt:{sid}（{level}）", stmt_id=sid,
                kind=REFUSED_LEVEL_TOO_LOW, step=step_no,
                expected=f"{CITATION_MIN_LEVEL} 级及以上",
                why=(f"第 {line} 行点名的 `stmt:{sid}` 现在是 `{level}`，"
                     f"引用要求 {CITATION_MIN_LEVEL} 级及以上"),
                how_to_fix=(f"先让它过 V 的逐行走审站到 {CITATION_MIN_LEVEL} 级"
                            "（或换一条已经够格的命题），再来引它")))
            continue
        cited: list[str] = []
        for no in _step_numbers(row.get("step")):
            cited.extend((steps.get(no) or {}).get("cites") or [])
        cited = list(dict.fromkeys(cited))
        if not cited:
            # 那一步没有 `cites`（前提步 / 没有编号）⇒ 这一层核不了号，
            # 在读数的 `rows` 里如实标 unverified，不把它说成"核过了"。
            kept.append({**row, "verified": "unverified"})
            continue
        if sid in cited:
            kept.append({**row, "verified": "cited"})
            continue
        fixable = [x for x in cited if x in index]
        if len(fixable) == 1:
            # 能确定（那一步只点名了一条在册命题）⇒ 直接洗成它，留逐行记录。
            out["deps_washing"].append({
                "line": line, "from": sid, "to": fixable[0],
                "why": (f"第 {row.get('step')} 的 `cites` 只点名了 `stmt:{fixable[0]}`，"
                        f"而依赖表写的是 `stmt:{sid}` ⇒ 按正文洗成 `stmt:{fixable[0]}`")})
            kept.append({**row, "stmt_id": fixable[0], "verified": "washed"})
            continue
        findings.append(_finding(
            line=line, quote=quote, got=f"stmt:{sid}", stmt_id=sid,
            kind=REFUSED_STEP_MISMATCH, step=step_no,
            expected="（无法唯一确定 —— 请自己指认）",
            why=(f"第 {line} 行写的是 `stmt:{sid}`，而第 {row.get('step')} 的 `cites` 是 "
                 f"{['stmt:' + x for x in cited]} ⇒ 号与正文对不上"),
            how_to_fix=("在依赖表里写清真正的那一条在册命题号，并让正文那一步的 `cites` 同步它")))
    if findings:
        out.update(
            deps_refused=WASH_REFUSED_ROW,
            deps_refused_findings=findings,
            reason=("依赖面的命题号核实不过（这一份不许提交给 V，退回 F 重写）："
                    + "；".join(f"{f['detail']}（为什么：{f['why']}）"
                                for f in findings)),
            rows=[dict(r) for r in rows])
        return out
    out["rows"] = kept
    changed = bool(filled) or bool(out["deps_washing"])
    if not changed:
        # 已经洗过（幂等）：逐字返回，`washed=False` —— 读的人据此知道"这一遍没动它"。
        return out
    out.update(washed=True, deps_section_filled=filled,
               text=_replace_section(raw, render_dependency_section(kept)))
    out["section"] = parse_dependency_section(str(out["text"]))
    return out



def deps_missing_reading(*, proof_text: Any, deps_written: int,
                         derived_from: Sequence[str] = (), stmt_id: str = "",
                         proof_no: int = 0, refs: int = 0,
                         section: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """"这一条命题的依赖面建起来没有" ⇒ 三态读数（实现仍是秘书那一份）。

    秘书那份读数的三个状态（`present` / `missing` / `not_applicable`）一个字都不改；
    这里只把"手稿里有没有依赖段 ＋ 正文引了几条"叠上去（`manuscript` 那一格），
    并按业主 2026-10-24 的口径定三档的边界：

    - 正文一条 `stmt:` 引用都没有（不管手稿有没有那一节）⇒ `not_applicable`：
      自足的证明合法，既不拒收、也不记成"缺依赖"（`missing` 只留给"该有而没有"）；
    - 有引用、手稿也有那一节 ⇒ 用秘书那份读数（段里落了边就是 `present`）；
    - 有引用、手稿没有那一节 ⇒ `missing`，`why` 写清"作者没写依赖段"。
      （B 那一侧对这种手稿是整笔受控拒绝 `dependency_section_missing`；这一档读数
      留给只读预览与别的调用方，它说的是同一件事。）
    """
    from .secretary import _deps_missing_reading

    base = dict(_deps_missing_reading(
        proof_text=proof_text, deps_written=deps_written, derived_from=list(derived_from),
        stmt_id=str(stmt_id or ""), proof_no=int(proof_no or 0), scan={"refs": int(refs)}))
    sec = dict(section or {})
    if not sec:
        return base
    base["manuscript"] = {
        "present": bool(sec.get("present")),
        "heading_line": int(sec.get("heading_line") or 0),
        "rows": len(sec.get("rows") or []),
        "problems": len(sec.get("problems") or []),
        "refs_in_proof": int(refs),
    }
    if int(refs) <= 0:
        # 一条在册引用都没有 ⇒ 依赖面这一格不适用（自足证明合法）。
        # 这一档刻意与 `missing` 分开：`missing` 说的是"引了却没记"，不是"没引"。
        #
        # 2026-11-05（缺陷 1a）：三态词表一个字不改（自足的证明仍必须放行），但"有证明
        # 正文而依赖 0 行"必须变成看得见的读数 —— 改前这一支只说"没有引用任何在册命题"，
        # 于是"写了 5000 字证明、一条依赖边都没有"与"这一格没查"在读数上分不开；底层
        # `secretary._deps_missing_reading` 本来给的是 `missing`，被这一支盖掉了
        # （读数面与后果见 `temp/dep_probe/REPORT-dependency-surface.md` 第 5 条）。
        chars = int(base.get("proof_chars") or 0)
        edges = int(base.get("deps_written") or 0)
        base["state"] = "not_applicable"
        if chars > 0 and edges <= 0:
            if sec.get("present"):
                base["why"] = (
                    f"这一份有 {chars} 字正文、0 条依赖边，作者在手稿里交了一张空的 "
                    f"`{SECTION_HEADING}` 表（声明自足）⇒ 依赖面这一格不适用"
                    "（自足的证明合法：既不拒收，也不记成「缺依赖」）；"
                    "一旦正文引用了在册命题，手稿就必须有那一节")
            else:
                base["why"] = (
                    f"这一份有 {chars} 字正文、0 条依赖边，而手稿里没有 "
                    f"`{SECTION_HEADING}` 那一节 ⇒ 缺节（格式没交，与自足是两件事）；"
                    "这一格按三态仍记「不适用」：正文没有引用在册命题时，B 不会因此拒收")
        else:
            base["why"] = ("这一份证明没有引用任何在册命题 ⇒ 依赖面这一格不适用"
                           "（自足的证明合法：既不拒收，也不记成「缺依赖」）；"
                           "一旦正文引用了在册命题，手稿就必须有那一节")
        base["next_step"] = ""
        return base
    if not sec.get("present"):
        base["state"] = "missing"
        base["why"] = (f"手稿里没有 `{SECTION_HEADING}` 这一节，而证明正文里出现了 "
                       f"{refs} 条 `stmt:` 引用 ⇒ 依赖面没有按格式登记（这不是「依赖为零」，"
                       "是「作者没写依赖段」）；B 入库时会整笔拒收 `dependency_section_missing`")
        base["next_step"] = (f"让 F 在证明手稿里补一节 `{SECTION_HEADING}`（三列表，见 "
                             "`agentflow.depsection.COLUMN_KEYS`），再由 B 重新入库")
        return base
    if not (sec.get("rows") or []) and int(base.get("deps_written") or 0) <= 0:
        # 2026-11-05（缺陷 1a 的第二档）：表在、但 0 行，而正文点了 N 条在册命题。
        # 这不是自足 —— 表与正文对不上。`state` 仍走三态里的 `missing`（不判红、
        # 不新增词），但 `why` 必须自己说清"正文点了 N 条"，否则读的人分不清
        # "真自足"与"该写没写"（业主 2026-11-05 的追加裁定）。
        base["state"] = "missing"
        base["why"] = (f"说不一致：证明正文里点了 {refs} 条在册命题（`stmt:` 引用），"
                       f"而手稿的 `{SECTION_HEADING}` 表 0 行 ⇒ 表与正文对不上，"
                       "不该读成「自足」；这些引用在读数里落在 `derived_from`"
                       f"（{list(base.get('derived_from') or [])}）—— 依赖信息在盘上，"
                       "没落成依赖边")
        base["next_step"] = ("把那几条引用写进 `cites`（框架会按它渲染那一节），或者把表里"
                             "那几行补齐 —— 正文与表必须说的是同一件事")
    return base


