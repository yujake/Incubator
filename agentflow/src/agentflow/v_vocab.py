# -*- coding: utf-8 -*-
"""词表与常量。

2026-11-20（VERSPLIT2）：`v_vocab.py` 是从 `verifications.py` 搬出的 44 块 / 434 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import depsection as _DS  # 可引门槛的唯一定义（`CITATION_MIN_LEVEL`）
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）


#: 验证台账目录（工作区根下）。
VERIFICATIONS_DIR = "verifications"


#: V 的结论（轴）—— 只有两态（业主 2026-11-01 裁定，逐字：「不应该有『看不出来』，
#: 『看不出来错』就是没毛病，没有『看不出来对』」）。顺序就是从"找到了缺陷"到"没找到缺陷"；
#: 最后一格永远是 `成立`（`numericproof.THIRD_PARTY_VERDICT_OK` 按 `[-1]` 引用它）。
#:
#: p247（业主第三次收紧）：这两格是轴（clean / fault）的名字，不是 `parse_verdict` 的词表。
#: 台账行上的 `verdict` 是 V 的陈述，不是判据；轴只由 :func:`secretary_axis` 给。
#: `parse_verdict` 因此不再按 `verdict` 的字面折档（判不了 / 看不出来 / 拿不准
#: 一个都不折；连"有毛病"也不由它定轴）。"看不出对"这回事不存在：V 永远拿不出
#: "它一定正确"的证据，那一档从来就不是它的一项结论。
#:
#: 与秘书那一条是同一条口径：秘书读 V 的回复后语义判定 `clean` / `fault`，
#: 连续次数与签发只看那个轴，不看 V 自己写的那两个字。
VERDICTS: tuple[str, ...] = ("有毛病", "成立")


#: 已经取消的那一档的历史值不再立一张词表（2026-11-16 裁定 ④：「把看不出来这档
#: 删干净」）。业主 2026-11-01 裁定逐字：「不应该有『看不出来』，『看不出来错』就是
#: 没毛病，没有『看不出来对』」。p247 起读侧连"折成成立"也不做：
#: :func:`read_verdict` 原样返回台账上的陈述，轴由秘书给。老台账里若还残留那四个字，
#: 它只是一句历史陈述（读得出、不崩），不产生任何轴、不算票、不签；写侧再也产不出它。
#: 台账不改写（追加式文件，迁移要重写历史行 ⇒ 不做）。
#: 业主 2026-11-01 逐字要求写进 V 可见面的那两句：两态的定义，与"看不出错就是成立"。
#:
#: 为什么它们是常量而不是散在提示词里的字面量：`verifications.cold_start_prompt` 是 V
#: 每次审阅真正读到的入口，`specs/v.py` 的 `policy` 是渲染进 system prompt 的那一份
#: （那一处不能 import 本模块 —— 本模块 import 它，反过来会成环）。两处必须逐字相同，
#: 而"逐字相同"只能由渲染面判据钉住：`tests/test_v_verdict_is_two_states.py` 的 s4
#: 在渲染之后的提示词上核这两句（不是核源码里的常量）。
TWO_STATE_LINE = (
    "成立（没找到缺陷 —— 不要求你证明它正确）"
    "/ 有毛病（找到了缺陷，必须指到步号与原句）")


NO_THIRD_STATES = (
    "『看不出错』就是成立；不存在『看不出来』这一档，也不存在『看不出对』这回事")


#: findings 的级别 —— 别名，不抄第二份：词表真身是 `schema.FINDING_LEVELS`
#: （`parse_verdict` 与 `schema.ReviewFinding` 判的是同一件事，两处各写一份字面量
#: 就会在加一档时一处认、一处拒）。
FINDING_LEVELS: tuple[str, ...] = S.FINDING_LEVELS


#: 硬禁令的清单（I10 的最小形态）：命中这些短语的步骤必须被指出来。
#: 用户 2026-10-05 口径："F 禁止写'易证/显然/trivial/clearly/it is easy to see'"。
HARD_BAN_MARKERS: tuple[str, ...] = (
    "易证", "显然", "trivial", "clearly", "it is easy to see", "无须证明", "显然成立",
)


#: 一次审校至少要交代的四件事（缺一就不是"审过了"）。
REQUIRED_FIELDS: tuple[str, ...] = ("verdict", "statement_id", "proof_sha256")


#: 引用核实的档位结论（业主 2026-10-26 裁定，两批）。
#:
#: 口径逐字：「正常写证明就是不会逐字的」、「proof_review级及以上才可引用」。所以判据不是
#: "字面像不像"，而是"F 对这一条被引命题的用法成不成立、以及这一条够不够格被引" ——
#: 改写、压缩、换符号都合法，只要条件与结论没被换掉：
#:
#: - `consistent`：F 的用法与这条命题真正说的条件/结论一致（措辞当然可以不同）；
#: - `weaker`：F 只用到了它的弱形式（不等于错，是情报；可以签，但读数里点名）；
#: - `stronger`：F 用到的结论比命题本身更强（引用被夸大，或悄悄去掉了它要的假设）；
#: - `unrelated`：这条命题与这一步无关（引错了）；
#: - `inadmissible`：被引命题的档位低于 `proof_review`（`cross_check` / `heuristic` / 空）
#:   ⇒ 它不够格被当作依据引（不管用法一致不一致）；
#: - `unknown`：V 判不了（材料不足 / 被引命题不在册）；它不是 `consistent`。
CITATION_VERDICTS: tuple[str, ...] = (
    "consistent", "weaker", "stronger", "unrelated", "inadmissible", "unknown",
)


#: 能签「成立」的两档：弱形式不是错。`weaker` 会被点名，但它不挡签字。
CITATION_SIGNABLE: frozenset[str] = frozenset(("consistent", "weaker"))


#: 挡住「成立」的四档（逐条点名是哪一条、差在哪）。`unknown` 也在里面：判不了不是一致；
#: `inadmissible` 也在里面：档位不够不是"用法对不对"能救的。
CITATION_BLOCKING: frozenset[str] = frozenset(
    ("stronger", "unrelated", "inadmissible", "unknown"))


#: 一条核实读数落盘时的五格。`quote_verbatim` 只是信息（F 那句话是不是逐字抄的），
#: 它不参与判定 —— 业主裁定"逐字"不能当标准，写证明不会逐字引。
#:
#: `in_material`（2026-10-27 补）是这一格为什么挡住签字的语境，必须随读数落盘：
#: `reconcile_citation_checks` 会给"V 多给的、材料里没有的那几条"标 `False`，
#: 而签字前置（`citation_gate`）明确不拿它们挡签（它们不是这一份证明登记的引用）。
#: 改前这一格只在内存里：落盘时被洗掉 ⇒ `signs_bit3` 读 `citation_blocks` 时
#: 把材料外的那条也算成挡签，于是"V 判成立、闸也说 ok"的一签落盘后读回
#: `rejected`，理由是"verdict='成立' ⇒ 结论不是成立"（自相矛盾，且写的人无从修）。
#: 老行没有这一格 ⇒ 按"材料内"读（它们本来就是按材料内判定写下的）。
CITATION_CHECK_KEYS: tuple[str, ...] = (
    "stmt_id", "verdict", "quote_verbatim", "note", "in_material")


#: 进 V 的审查材料的"被引命题正文摘要"长度上界（正文本身留在 `citations` 的全文格里）。
CITATION_DIGEST_CHARS = 600


#: 被引命题的等级下限 —— 直接引用 `depsection.CITATION_MIN_LEVEL`（唯一门槛定义）。
#:
#: 2026-11-05 改口径前这里是档位字面量 `"proof_review"`，与 `depsection` 各写一份；
#: 真机反例 `mp3-r3/000000`（档位 `proof_review`、等级 `conjecture`）上两处给相反答案：
#: B 拒、V 放行。业主裁定「判定面一律读等级」之后，这里不再写第二份字面量：
#: 阈值与允许集合都从 `depsection` 那一个定义取。
CITATION_EVIDENCE_FLOOR = _DS.CITATION_MIN_LEVEL


#: 「命题还没在册时审的那一签」落在哪：`verifications/pending/<sha>.jsonl`（D-34）。
#:
#: 为什么单独一个子目录（而不是塞进 `verifications/` 顶层）：顶层那一层是"每个命题一份台账"，
#: `list_verifications` 与收工门 R10 都按顶层 `*.jsonl` 逐个命题读 —— 混进一份没有命题号的
#: 台账会让那些读法把一行"还不属于任何命题"的签算到某个命题头上。子目录不进那条 glob，
#: 而认领它的入口只有一个：:func:`pending_sign`（按对象内容的 sha）。
#:
#: 2026-11-10（缺陷：收录后 `list_verifications` 读成 0 行）：认领之后那一行已经属于
#: 某一条命题，物理位置不变（签块 / 签文件的 `台账=` 仍指着这个文件），但
#: `list_verifications` 的读侧会把它并进在册台账 —— 并入口只有
#: :func:`_claimed_pending_rows` 一处（只并已认领的，未认领的不算任何命题）。
PENDING_DIR_NAME = "pending"


#: pending 台账里那一行的编号前缀（`u-NNNNNN`：u = 未登记）。
PENDING_PREFIX = "u-"


#: K6①（2026-11-18，业主 2026-11-18 裁定）：「判词挂 V 读到的那一版」。
#:
#: V 读 v1 →（F 在 V 判完/签发之前改稿）盘上已是 v2 时，签发这一步必须受控拒：
#: 判词 / V 稿 / 台账行都只挂读到的那一版（`proof_sha256`），不许把 v2 的正文
#: 按 v1 的判词签出去。改前 lp-ball-8 的现场是「判 c023、记 a1741」。
PROOF_CHANGED_SINCE_DISPATCH = "proof_changed_since_dispatch"


#: pending 台账的跨进程锁文件名（与目录同级：`verifications/pending.lock`）。
#:
#: 为什么不按"一份台账一把锁"：号源（`_next_pending_verification_id`）扫的是
#: `pending/*.jsonl` 全部文件 —— 锁按文件加时，两个进程各写各的文件仍然会读到
#: 同一份最大值、各发同一个号（K14 的 a 条）。所以这把锁罩的是整个 pending 目录的
#: 读-取号-追加，粒度与号源的射程相同。
PENDING_LOCK_SUFFIX = ".lock"


#: 等锁上限（秒）。超时是受控失败（`VerificationError`），不折成"没锁"——
#: 拿不到锁还去发号，正是会撞号的那条路。
PENDING_LOCK_TIMEOUT = 30.0


#: 一条证明（或一条命题）相对「它现在这一份正文」的六种读数（唯一口径在
#: :func:`review_standing` / :func:`statement_review_reading`）。
#:
#: 顺序是"从查清了到没查成"：`signed`（现行版有「成立」那一签，且连续次数够了）/
#: `holding`（签过、判成立，但连续次数还没到 `SIGN_STREAK_NEED`）/ `stale`（签的是旧版，
#: 待复核）/ `rejected`（现行版被签过，结论不是「成立」）/ `unsigned`（一次都没签）/
#: `unreadable`（台账读不出来 / 证明号认不出 —— 没查成，不是通过、也不是没签过）。
#:
#: 为什么 stale 与 rejected 必须分开（三态纪律）：前者是"签过、但签的不是现在这一份"，
#: 后者是"签的就是这一份、结论是没过"。把两者折成同一个"不算"会让"改完稿还没送审"
#: 与"审过了、没过"在读数上长得一样，而处置完全不同（前者重派 V，后者改证明）。
#:
#: 为什么 `holding` 必须单列（业主 2026-10-29「连续 3 次」）：第 1、2 次「成立」只落台账、
#: 不翻位（`:func:`sign_statement``）。若把它们折进 `unsigned`，那一档的措辞是"一次都没签"——
#: 而台账上明明有 1、2 行签，读的人会拿到一句假话；折进 `rejected` 更坏（"复核过、结论不是
#: 成立"同样是假话）。三档的处置也不同：holding = 再派两次审阅；unsigned = 派一次；rejected = 改证明。
REVIEW_STATES: tuple[str, ...] = ("signed", "holding", "stale", "rejected",
                                  "unsigned", "unreadable")


#: 「一次送审内部连续几次成立才发签」（业主 2026-11-02 定稿）。
#:
#: 语义写死在这里，后来人不许再把它读成"跨送审累计"：
#: - 门槛 = `sign_counting` 现数（系统计次，2026-11-17 业主裁定）：同一份正文、同一个
#:   `review_call` 内 `review_pass=1..need` 连续 clean 的台账行数。一次 `verify_proof` 调用
#:   里 V 连判 `SIGN_STREAK_NEED` 轮（`agent_v.core.review_pass_bound` 现读这个数）；三轮里
#:   任一轮「有毛病」⇒ 立刻停、打回、不签；三轮都干净 ⇒ `sign_counting` 从台账数够门槛
#:   ⇒ 发签。调用方自报的轮数（`within_call`，即 V 那一趟的 `pass_no`）只是读数，
#:   不参与发不发签的判定。
#: - 跨两次送审绝不累计：每份正文的签只由"某一次送审内部的那几轮"决定
#:   （业主逐字：「不允许跨两次送审累计成功数」）。旧台账里那些没有 `review_call` /
#:   `review_pass` 的行是历史形态（`legacy_rows`），读得出、但不参与新签判断。
#: - 名字里的 "STREAK" 只指"同一趟调用内连着几轮 clean"（由 `sign_counting` 从台账现数），
#:   不是"跨趟累计的台账尾部连续几行"。
#:
#: 为什么是一个常量而不是散在各处的 `3`：判据（`review_standing` / `signs_bit3` /
#: `sign_statement`）与读数（`proof_review_gap` 的 checklist、`review_standing` 的
#: `streak/need/streak_ok`）必须说同一个数。抄成三份之后，调一次口径就会留下两处
#: 还按旧数算的暗门 —— 而那种暗门没有任何一条判据会报。
SIGN_STREAK_NEED: int = 3


#: 穷举型证据（E 那一档）的过审门槛（业主 2026-11-17 追加裁定）。
#:
#: 业主逐字：「因为实验侧报告不承重（承重的是程序），E 这条路的过审门槛从三次降成
#: 一次（need=1）」。所以：
#:
#: - 与 F / B 同构的只是「连续过审 → 系统计数 → 落签」这个形状：V 只裁不定不落、
#:   一次过审不发签（need 决定几次）、同一份判词复制多份不算、跨送审不累计；
#: - E 这条路的 `need` 是 1，F / B 仍是 `SIGN_STREAK_NEED`（3）—— 三个数不许混写。
#:
#: 机械会审（`exhaustionreport.review`）仍是 E 的判词来路（2026-10-23 裁定仍然有效：
#: 机械可核的事实不该让模型判）；一条机械判词在 `sign_counting` 里整组只算 1 轮，
#: 在 E 的 need=1 下就够，在 F / B 的 need=3 下永远不够（负控）。
EXHAUSTION_SIGN_STREAK_NEED: int = 1


#: 台账行上「秘书语义判定」那一格的键（业主 2026-10-29 的 B 段）。
#:
#: 它是行上的一格而不是 statements 的新列：连续计数从台账派生（`draft/125` §二 A），
#: 于是 `schema.py` / `store.py` 这两个 FC-27 一个字节都不用动。历史行没有这一格
#: ⇒ 读侧按「没判过」处理（空轴既不攒票也不清零；2026-11-02 起 `historical_axis` 恒空）；
#: 「计入连续」是这条口径上线之前的行为，已经不是今天的读法。
SECRETARY_JUDGE_KEY = "secretary_judge"


#: 台账行上「秘书语义判定」那一格的写侧轴（业主 2026-10-29 的 B 段；
#: 2026-10-30 第三次裁定收成两档）：`clean` = 没问题（计入连续）/
#: `fault` = 有缺陷要指出（清零）。
#:
#: 为什么没有第三格：业主逐字「不可能有判不了…只要不是完全没毛病都叫有毛病」。写侧
#: （`record_verification`）只收这两格 —— 传别的值一律落成空轴（"这一行没有轴" =
#: 这一趟没查成），于是"新判定产生第三档"在结构上不可能发生。
#:
#: 2026-11-02（追加裁定：那一档连历史兼容读也不留）：改前这里还有第二个常量
#: `SECRETARY_JUDGE_HISTORICAL_AXES = ("unsure",)` —— 老台账行上那个轴名"读得出、
#: 不计票、也不清零"。那个常量、:func:`secretary_axis` 的兼容支与
#: :func:`_hold_run_lengths` 里对应的一支一起删了：老行上的那个轴名现在读出来是
#: 空轴（"这一行没有轴"），不再有任何一格替它留位置。
SECRETARY_JUDGE_AXES: tuple[str, ...] = ("clean", "fault")


#: 写口拿不到秘书判定时，往 `SECRETARY_JUDGE_KEY` 那一格里写的东西（"未判成"）。
#:
#: ## 它挡的是哪一条（业主裁定 2：「看究竟谁登记的成立，绕过秘书登记才是缺陷」）
#: 改前两个台账写口都把这一格写成条件写入：调用方不给 `secretary_judge` ⇒ 这一格
#: 根本不落盘。而读侧的 :func:`historical_axis` 只对"没有这一格"的行生效，那一支是按
#: `verdict` 的字面给轴的（成立 ⇒ clean）。于是"省掉这一格"不是"没判"，
#: 而是把轴让给了一个字符串：
#:
#:     三次 `record_verification(verdict={"verdict": "成立"})`（一次秘书都不问）
#:     ⇒ 每行 `historical_axis` = clean ⇒ `row_signable` = True
#:     ⇒ `consecutive_holds.streak` = 3 ⇒ `bit3_payload(...)["reviewed"]` = True
#:
#: 那就是"绕过秘书登记成立"，而且是能签住第 3 位的那一条（现场读数见
#: `tests/test_v_axis_comes_from_the_secretary.py::test_l_*`）。所以写口现在无条件
#: 写这一格：给了判定就写调用方给的（轴仍然是唯一来源），没给就写这一格 ——
#: `checked=False` + 空轴 ⇒ `row_signable` 为假、连续计数既不算票也不清零
#: （fail-closed，与"问过、没判成"同一档）。
#:
#: 为什么不是"干脆写 `verdict=未判成`"：`verdict` 是 V 的陈述（p247），
#: 写盘时改它等于改历史；"未判成"是这一行有没有判过的性质，落在这一格上。
NO_SECRETARY_JUDGE: dict[str, Any] = {
    "axis": "",
    "checked": False,
    "decision": "",
    "reason": ("这一行没有秘书判定 ⇒ 未判成（轴只能由 V 的秘书给；"
               "写口 fail-closed，不按 verdict 的字面补轴）"),
}


#: 多证明模型的落点（业主 2026-10-22：不加 schema 字段）。
#:
#: 一条命题可以有几份证明：canonical 是 `#p1`，它的正文就是行上既有的 `proof_text`
#: （老写者只会写那一格，所以它必须继续是 `#p1` 的权威正文）；其余证明落在行 JSON
#: 里一个额外的键 `proofs`：`[{"proof_no": 2, "proof_text": "..."}, ...]`。
#: `schema.row_from_dict` 只取它认识的键（"未知字段会被忽略"），所以盘上多这一个键
#: 不需要动 `schema` —— 而"证明清单"本身是数据，不是磁盘格式契约的新字段。
PROOFS_KEY = "proofs"


#: 证明号在行上的键名。`proof_no` 是正名；`rev` 是更早的写法。
#:
#: 为什么读侧认两个名字、而不是做一次迁移：台账是追加式文件（`verifications/*.jsonl`），
#: 改键名只能重写历史行 —— 那会把"谁在什么时候签的"改成"我们改写过它"。兼容的代价是
#: 一行读法，迁移的代价是不可逆的审计记录。`no` 是清单项里更短的那个旧别名。
PROOF_NO_KEYS: tuple[str, ...] = ("proof_no", "rev", "no")


#: 哪一档 `verdict` 算"这条命题被判死了"（业主 2026-11-13 裁定 ②）。
#:
#: V 判「有毛病」与 E 跑出反例是两条并列的来路，都落猜想台账的 `refuted`：
#: 前者带 `refusal_ref`（这一签的落点），后者带 `counterexample_experiment_id`。
#: 只用一条会把"被判死"折成"还没验"，把一次没跑成的实验折成一次判决。
_FAULT_VERDICT = "有毛病"


#: D3（2026-11-09）的四类「缺陷类别」——与轴正交的一格，不是第三档轴。
#:
#: 轴仍然是 :data:`SECRETARY_JUDGE_AXES` 的两档（clean / fault）；本词表回答的是
#: 「这一行判 fault 时，fault 的内容是哪一类」：
#:
#: - `math`：证明链本身的错/洞（findings 里有 `level=error` 且指到某一步，或 `defect_step`）；
#: - `procedural`：V 自己说「我没逐行验证 / 我判不了」——它没有做出判定；
#: - `style`：依据落在排版 / 术语 / 文风 / 价值判断这类不归 V 判的面上；
#: - `contract`：稿的形态 / 契约不合格（缺 `## 证明`、引用不可核、sha 不符、稿名解析不出）。
#:
#: `report_gap`（见 :data:`FAULT_KIND_VALUES`）不在这里：它是业主 2026-11-09 裁定 ①
#: 从 `procedural` 里单列出来的读数（「没记录反例构造尝试」不算缺陷），不是 fault。
FAULT_KINDS: tuple[str, ...] = ("math", "procedural", "style", "contract")


#: :func:`fault_kind_of` 的 `kind` 全部取值（与 :data:`FAULT_KINDS` 逐字相同）。
#:
#: 业主 2026-11-09 裁定 ① 之后 `report_gap` 不是 kind：它是
#: :data:`FAULT_CAUSES` 里的一档（「没记录反例构造尝试」不是缺陷，不锁 sha、不挡签）。
#: 把它留在 kind 里会让 `is_a_vote` 的第 ③ 条把一条 clean 行判成"矛盾行"，
#: 于是裁定 ① 想让它算的那一票又被静默吞掉。
FAULT_KIND_VALUES: tuple[str, ...] = FAULT_KINDS


#: `fault_kind_of` 的 `cause` 全部取值（只对 `procedural` 有意义；`""` = 没有细分原因）。
#:
#: - `report_gap`：缺"反例尝试 / 逐关核对"的记录 —— 不是缺陷（裁定 ①）；
#: - `self_declared`：V 自己说"我没逐行验证 / 判不了" —— 仍然是 fault。
FAULT_CAUSES: tuple[str, ...] = ("report_gap", "self_declared")


#: :func:`fault_kind_of` 的 `source` 全部取值。
#:
#: `row` = 新行自己在 `secretary_judge` 里带了 `fault_kind` 这一格（键在；值为空 =
#: 明确的 clean，值为四类之一 = 那类缺陷）。键在不在是"新行 / 老行"的唯一分界：
#: D3 之后每一行都必须写这一格（可空），老行没有这一格，才走下面三档读侧推定。
#: 其余三个是读侧推定：`legacy_math_evidence`（行上带数学证据）/ `legacy_shape`
#: （按行形状推定）/ `legacy_default`（说不清 ⇒ 按 math 兜底，继续锁）。另加一个只往
#: 更严方向折的 `guard:carries_math_evidence`（写侧护栏在读侧的同一条）。
FAULT_KIND_SOURCES: tuple[str, ...] = (
    "row", "legacy_math_evidence", "legacy_shape", "legacy_default",
    "guard:carries_math_evidence")


#: 「没记录反例构造尝试」这一档的措辞（98b 的 4 条 fault 逐字命中其中一条）。
#:
#: 这些是报告质量的读数，不是缺陷（业主 2026-11-09 裁定 ①）：它们不锁 sha、不挡签，
#: 只让「V 的报告缺了什么」第一次可见。
_REPORT_GAP_MARKERS: tuple[str, ...] = (
    "没有记录任何反例构造尝试",
    "没有记录任何反例",
    "没有记录反例",
    "没有尝试记录",
    "没有记录尝试",
    "未构造出反例",
)


#: V 自己说「我没逐行验证 / 我判不了」——这一档仍然是 fault（它没有做出判定）。
_SELF_DECLARED_MARKERS: tuple[str, ...] = (
    "没有逐行验证", "没逐行验证", "未逐行验证", "无法逐行验证",
    "我判不了", "判不了", "无法判断", "不能判定", "给不出判定", "拿不准",
)


#: 依据落在不归 V 判的那几样（排版 / 术语 / 文风 / 价值判断）。
_STYLE_MARKERS: tuple[str, ...] = (
    "排版", "术语", "文风", "措辞", "价值判断", "笔误", "标点", "版式",
)


#: 机器核过的那一档（`schema.EVIDENCE_KINDS` 的最强端）。回填只认它"比 proof_review 强"。
PROOF_KIND = str(S.EVIDENCE_KINDS[0])


#: V 落签之后"按现行签把档位重算一遍"那一格的读数键（业主 2026-11-04）。
#:
#: 与秘书那一支的 `_evidence_kind_upgrade` 刻意分成两格：那一格记的是"同一份内容再交
#: 一次、这一回来的声明更强"（提交方声明的来路）；这一格记的是"签刚落位、按盘上那一签
#: 重算"（盘上凭据的来路）。两件事的来路不同，读的人要能分开看 —— 否则"这一格是谁改的"
#: 永远查不出来。
GRADE_RECOMPUTED_KEY = "_grade_recomputed"


#: `proof_review` 这一档的凭据判据码（2026-10-19，堵「假 proof_review」）。
#:
#: 两个码各有落点，不许合成一个（一个是写入期拒收，一个是审计期点名 ——
#: 同一句话在两个出口上的读者不同：写者要"改哪里"，审计要"存量有多少"）：
#:
#: - `CODE_WRITE`：写入期闸（`store.tx` 提交时）—— 当场拒收，一行都不写；
#: - `CODE_AUDIT`：审计期档（`verify._check_13`）—— error 级点名，存量照读。
CODE_WRITE = "proof_review_without_evidence"


CODE_AUDIT = "proof_review_without_verification"


#: `proof_review` 这一档在 `statements.evidence_kind` 里的取值（口径见 `schema.EVIDENCE_KINDS`）。
PROOF_REVIEW_KIND = "proof_review"


#: 比 `pre_theorem` 更弱的等级（降档告警用；2026-11-05 起读等级，不读档位）。
WEAKER_THAN_PRE_THEOREM_GRADES: tuple[str, ...] = ("conjecture", "strong_conjecture")


#: 历史档位名（保留导出只因 `secretary.py` 仍读它；那条 lane 的"声明档位退场"后延）。
#: 判定面不再用它：`weaker_than_evidence_gaps` 读的是 :data:`WEAKER_THAN_PRE_THEOREM_GRADES`。
WEAKER_THAN_PROOF_REVIEW: tuple[str, ...] = ("heuristic", "cross_check")


#: `recompute_grades` 的四栏（顺序 = CLI 的打印顺序；2026-11-05 改口径后第二栏
#: 从"已是最高"改成"已经一致"—— 重刷不只往上升，也纠 105 条虚报）。
#:
#: 名字是字符串而不是枚举，是因为它们直接进 `--json` 与四栏表：读的人拿到的就是
#: 这四个键。`not_enough` 里的 `state` 逐字取自 :func:`proof_review_gap`（不在本命令
#: 里另造一套词表），`unchecked` 只收 `checked=False` 的那一档。
GRADE_BACKFILL_COLUMNS: tuple[str, ...] = ("will_upgrade", "already_consistent",
                                           "not_enough", "unchecked")


#: `experiments.result` 里"方向"只有两档有值；`inconclusive` 没有方向。
#: 真身是 `schema.EXPERIMENT_RESULTS`，这里只把"相反"那一个取值点名。
REFUTES = "refutes"


#: `negation_kind` 里"已证否"那一档（受控词表真身是 `schema.NEGATION_KINDS`）。
DISPROVED = "disproved"


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
