# -*- coding: utf-8 -*-
"""冷启动提示词（只有对象，没有句柄）。

2026-11-20（VERSPLIT2）：`v_prompt.py` 是从 `verifications.py` 搬出的 5 块 / 357 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from typing import Any, Iterable, Iterator, Mapping, Sequence


def citations_block(citations: Sequence[Mapping[str, Any]],
                    problem: str = "") -> str:
    """引用核实那一节怎么印进提示词（纯字符串拼装，只有材料、没有句柄）。

    业主 2026-10-26：F 的"引用"是自然语言描述，不是逐字引文 ⇒ 光给编号没有用，
    V 要看到"F 是怎么说的"与"被引命题真正说的"两样东西才能判它成不成立。
    所以每一条都印三样：F 那句话（含它出自依赖行哪个键）、被引命题正文摘要、
    被引命题现在的档位（够不够格被引）。
    """
    lines: list[str] = ["## 引用核实（F 在依赖面登记的引用；逐条核 F 是不是这么用的）"]
    if problem:
        lines.append(f"- 依赖台账读不出来（{problem}）⇒ 这一档没查成：没有材料就不能判"
                     "「一致」，判不了就写 unknown（它挡住「成立」）。")
    if not citations:
        if not problem:
            lines.append("- 这一份证明没有登记任何被引命题（`dependencies` 里没有指向本条命题"
                         "这一份证明的 `stmt:` 依赖）⇒ `citation_checks` 给空数组。")
        else:
            lines.append("- 材料读不到时不许说「这一份证明没有引用」：那是把「没查成」说成"
                         "「核过、没有引用」。")
        return "\n".join(lines)
    lines.append(f"- 登记了 {len(citations)} 条被引命题。每一条都要给一档结论："
                 "少给一条就按 unknown 算，而 unknown 挡住「成立」。")
    for i, item in enumerate(citations, 1):
        sid = str(item.get("stmt_id") or "")
        groups = "、".join(str(g) for g in (item.get("path_groups") or [])) or "1"
        lines.append("")
        lines.append(f"### {i}. {sid}（路径组 {groups}）")
        if item.get("statement_missing"):
            lines.append("- 册子里没有这条命题（不在册）⇒ 只能判 unknown，不许判一致。")
        else:
            kind = str(item.get("evidence_kind") or "")
            if item.get("admissible"):
                lines.append(f"- 它现在的档位：`{kind}`（够格被引）")
            else:
                lines.append(
                    f"- 它现在的档位：`{kind or '（空：没有档位）'}`，"
                    f"够不上 `{CITATION_EVIDENCE_FLOOR}` 级 ⇒ 不够格被引："
                    "这一条要判 inadmissible（不管原文一致不一致）。")
            lines.append(f"- 被引命题正文：{item.get('statement_digest') or '（正文为空）'}")
        for path in (item.get("paths") or []):
            note = str(path.get("note") or "")
            where = str(path.get("note_source") or "")
            lines.append(
                f"- F 的说法（路径组 {path.get('path_group')}，依赖行 "
                f"{path.get('dep_id') or '?'} 的 `{where or '（没有话）'}`）："
                f"{note or '（F 没有写为什么引它）'}")
            quote = str(path.get("quote") or "")
            # 引文原话单独印一次，但若 F 那句话里已经含着它（写侧常把 quote 拼进 label，
            # 例如"手稿依赖段（第 4 行）：由引理 2"）就不再重复一遍。
            if quote and quote not in note:
                lines.append(f"- 依赖行上的引文原话：{quote}")
            status = str(path.get("status") or "")
            if status:
                lines.append(f"- 这条依赖的状态：{status}")
    return "\n".join(lines)


def _cold_start_review_checklist() -> str:
    """`cold_start_prompt` 的「审阅清单（这是嘱托，不是门）」那一节。

    2026-11-06 从 `cold_start_prompt` 里原样搬出来（纯机械抽取：字面、顺序、空行一个
    字节都没动）。为什么抽它：它自成一节、且只吃常量字面（不读任何入参），而
    `cold_start_prompt` 已经越过 200 行那条软线 —— 抽成函数之后调用处只剩一行转调。
    改这里的文案等于改提示词（要抬 `PROMPT_VERSION`、重冻十一格摘要），属人审范围。
    """
    return (
        # ---- 审阅清单（draft/122 按 F 的交付面重剪；S5 的提示词落点）----
        #
        # 为什么清单在提示词里、而它又明说"不是门"：`docs/DEVELOPMENT-SPEC.md` §13 的分工
        # —— 提示词管"想让它这么做"，判据管"不许它不这么做"。下面每一条都是"怎么读"的
        # 方法（判不了），所以只能是嘱托；而"V 是不是逐行验证过"本来也不可机器判
        # （draft/126 §三 的同一句）。完整版在 V 的技能手册里
        # （`skills/V/产出-只产意见-签分两档.md`），这里给压缩版 —— 它每次审阅都要带，
        # 而手册是按需读的。
        "\n## 审阅清单（这是嘱托，不是门）\n"
        "`docs/DEVELOPMENT-SPEC.md` §13：提示词管「想让它这么做」，判据管「不许它不这么做」。"
        "下面这一份属于前者 —— 没有任何一格会因为「你没按清单逐条走」而变红；"
        "你不按它走时，你写「成立」的那句话就只是一句印象。\n"
        "清单按 F 在本框架里实际交付的那种证明重剪（带显式假设清单的条件性证明 = 假设清单"
        "＋ 定理链＋ 由构造给出的中间对象 ＋ 条件性结论 ＋ 指数/常数记账），每关只问 F 能回答的问题：\n"
        "- 假设关：H-1 每条假设里的符号有没有公式级定义（只有描述 ⇒ 它不是数学命题）；"
        "H-2 这条假设的构造有没有用到结论本身（循环）；H-3 它给的界够不够支撑用到它的那一步；"
        "H-4 假设只在某个区域给控制、而证明用在区域之外；H-5 每条假设是不是真在某一步被用到。\n"
        "- 定理链关：T-1 每一步的「由…得」有没有真推导（引理名与适用范围；只写"
        "「由上式可得」而无中间代数的按空洞处理）；T-2 依赖有没有断在某条没证完的 Lemma 上；"
        "T-3 常数是否依赖于正在取极限的参数（把「对每个固定 X 存在 Y」当成一致界）；"
        "T-4 逐项取极限/求和/积分的依据是哪一条（一致收敛 / 绝对收敛 / 控制收敛 / 有限性）；"
        "T-5 用恒等定理时两边是否都是确定的亚纯函数（陈述带 1 + O(·) 的，先改成显式因子）；"
        "T-6 Lemma 的陈述与证明给的结论是否同一件事；T-7 例外情形（小素数 / 整除判别式 /"
        "边界指数 / 退化）有没有单独处理；T-8 主定理的结论逐字对回假设 —— 多出来的部分靠什么。\n"
        "- 记号关（这一关必须真的算）：N-1 变量替换有没有改回去（定义了 C(s)=s+c 之后，"
        "全篇还有几处把 C(s) 写成 s）；N-2 反函数回代时实部/虚部各移了多少、结论里说清没有；"
        "N-3 指数账 —— 把全篇的指数与常数（3/16、1/4、δ1、δ2、ε(q,t)…）列成一张表逐个代入核对，"
        "同一常数在两节取不同值就报出来；N-4 文中说「更强/更弱」时与真正需要的条件并列比较。\n"
        "- 条件性措辞关：C-1「在 (H1)–(Hn) 下」是否精确（每条假设良定义吗）；"
        "C-2 有没有把「猜想」当「定理」用；C-3 有没有把「未核实的外部结果」当标准事实"
        "（写「标准/众所周知/经典结果」的，要求它给出本情形的确切陈述；"
        "你只判「说没说清」，不去查文献）；C-4 正文的自我定位与标题/摘要是否一致。\n"
        "- 明确不归 F 的（不许拿这些凑数）：文献真伪与页码级核对（归 B；C-3 只判说清没说清）、"
        "实验数值 / 复现结果（归 E）、稿件排版 / 术语统一 / 写作风格（归 G / C）、"
        "「这篇论文有没有价值 / 想法好不好」（那是 M 的）。"
        "回复里若主要以这些作为「发现问题」的依据 ⇒ 它们不是这份证明的缺陷，"
        "但这也不是「成立」：判 `有毛病`，把「理由面错位」写成一条 finding"
        "（`kind` 写明「理由面错位」，`step` 与 `defect_step` 指到你拿来质疑的那一步）——"
        "秘书只看 `findings` 与 `defect_step`，写进 `why` 不算数。\n"
        "- 结论语法：有毛病 ⇒ 逐条三段式（位置（步号）/ 原文逐字 / 类型编号 / 为何不成立 / "
        "需补什么）；成立 ⇒ 说清走过哪几关、每关的核对记录。尽量写清你尝试过的反驳"
        "（在哪一处试着构造反例、为什么失败）—— 没写这一条不算缺陷，只会被记成 "
        "`report_gap`（报告质量读数，不挡签）。但「我没有逐行验证 / 我判不了」仍然是"
        "有缺陷要指出（那是没有做出判定，不是报告写得简）：把「核到哪一步、从哪一步起没核」"
        "写进 `findings`（带步号）并在 `defect_step` 指到那一步；秘书按题面判「有缺陷要指出」，"
        "这一签不签发 —— 不许写成「成立 + 一条备注」。\n"
    )


def _cold_start_proof_strength(*, lean_on: bool) -> str:
    """`cold_start_prompt` 的「成立是什么强度」那一节（两类 proof 并列 + 穷举会审）。

    与 `_cold_start_review_checklist` 同一笔抽出，同样逐字节未动。唯一的入参是
    `lean_on`（原 `cold_start_prompt` 里那个 `_lean_on` 开关读数）：它只决定
    「本会话 Lean 形式化：已开启 / 已关闭」那一句。
    改这里的文案等于改提示词（要抬 `PROMPT_VERSION`、重冻十一格摘要），属人审范围。
    """
    return (
        # 2026-10-17（Lean 审计 S3）：这是 V 的真实入口（`agent_v/core.py` 用它，
        # 而 `system_prompt("V")` 全仓没有生产路径渲染）⇒ 开关与"成立≠proof"必须写在这里，
        # 否则 V 在 Lean 开着/关着时行为完全一样，而 H 会把它签的第 3 位当凭据。
        #
        # 2026-10-23 晚（业主：「E 写的报告要能落下来，且 V 也要会审这种东西，加 E 派 V 的边」）：
        # 这里此前写的是「evidence_kind=proof 只由 verify.check_formal 的检查器输出产生；
        # 要 proof 就请 M 派 E 走 formal 那条路」—— 那句话现在是假话（穷举证据也能拿 proof，
        # 而签字的人正是 V），它会让 V 把 E 交来的穷举证明读成"不归我审"，或者反过来去要
        # 一份自然语言证明。所以改成两类 proof 并列，并把穷举那一档的入口写在这里。
        # 2026-11-01（业主 P0-2）：这两句此前是「签字的人是你」与「七项全过才签」——
        # 两处都把签说成 V 自己发的，与同一份提示词第 8 行那句互斥（p248 起那一句分成
        # 在册 / 未在册两档：在册「发不发签由你的秘书判定并落盘」，未在册「由你颁发签信封、
        # 由收方秘书落块」）。现在统一：在册档 V 给判定、发签在秘书；未在册档 V 颁发信封、
        # 收方秘书落块（业主 2026-11-04 的明文例外，见 `specs/v.py` 与 `agent_v/core.py`）。
        "\n## 你这个「成立」是什么强度：两类 proof 并列\n"
        f"- 本会话 Lean 形式化：{'已开启' if lean_on else '已关闭'}；\n"
        "- `proof` 级证据有两类，并列、不分高低：\n"
        "  ① Lean 形式化 —— 凭据是 `formal.check_formal` 的检查器原话；\n"
        "  ② 穷举 —— 凭据是 E 写的那份程序 + ②③；发签分两档：在册档由你的秘书判定并落盘，"
        "未在册档不问秘书（机械会审全过即由你颁发签信封、收方秘书落块）；你只给结论，"
        "见下面那一档；\n"
        # 2026-10-24：判据 long 期望这一句「不构成 `proof`」—— 它的意思是"
        # 你这一次逐行走查的「成立」本身不是 proof 级凭据：proof 档要那两类里的某一份"
        # （检查器原话 / 穷举那份程序），你这一签是给它们背书的，不是替代它们。
        "- 要说清强度：你这一次的「成立」本身不构成 `proof` —— 它是对上面两类里某一份的背书；"
        "`proof` 级证据仍然要那一份凭据（检查器原话，或穷举那份程序 + ②③）。\n"
        # 2026-11-04（审 C 区）：这一句此前一个字都没有 —— 而档位回填
        # （`_grade_recomputed_from_signature`）正是由这一签触发的：在册那一行在签落位那一刻
        # 按现行签把 `evidence_kind` 重算一遍，目标档按通道给。V 不知道这件事，就会把
        # "穷举那一篇"读成"我审过了、所以是 proof_review"（那是错的终态，`draft/178`）。
        "- 等级不归你算：B 收录这份稿、认出这一签时，按现行签**现算等级**（只升不降，"
        "`_grade_recomputed_from_signature`）—— 通道是穷举程序"
        "（三段式证明栏 + 实验台账里那条由你签下的穷举证明）⇒ `theorem`；通道是文字证明 ⇒ "
        "`pre_theorem`。`evidence_kind`（`proof` / `proof_review`）只是由等级反算的历史列名。"
        "判据只有一处（`numericproof.find_signed_exhaustion_for_column`）："
        "穷举那一篇停在 `pre_theorem` 是错的终态，因为 V 不能逐行走查一份程序。\n"
        "- 所以别在理由里写「已形式化验证」（那是第 ① 类的说法）；穷举那一类你要写的是"
        "「穷尽性与会审七项已核」。\n"
        "\n## 穷举型证据会审（证明栏第 ① 段是程序、且不是 `.lean` 时走这一档）\n"
        "- 你的入口是七项机械会审，一条一项、逐条给读数：① 程序地址在不在盘上、读不读得出来；"
        "② 报告落盘且三块齐（`out/experiments/<实验号>/exhaustion.md`）；"
        "③ 搜索空间的数字与代码里的循环/参数一致；④ 对称性/剪枝的理由成不成立；"
        "⑤ 边界覆盖写没写、数字对不对得上；⑥ 结论是穷尽而不是抽样；"
        "⑦ 形式化那一格填的类别对不对（数值定理填数值程序、理论定理填 `.lean`）。\n"
        "- 结论落在三格：`exhaustion_review`（整份会审读数）/ `checks`（七项逐项 ok）/ "
        "`missing`（缺哪一块材料）。\n"
        "- 缺材料（报告没落地、实验行没有、②③ 缺一块）⇒ 这一格没查成：点名缺哪一块，"
        "既不判 `成立`、也不判 `有毛病`，台账里也不留那一行（留一行会把「没查成」"
        "冒充成「审过了」）；材料补齐之后重新送审。\n"
        "- 七项全过才判 `成立`；会不会发签分两档：在册档由你的秘书按这一趟送审的门槛判，未在册档按机械"
        "会审的门槛判（`source=exhaustion_report`，不经秘书）—— 这一签是「对数值证据的背书」，"
        "不是「你逐行读过一份自然语言证明」。\n"
    )


def _cold_start_submission_gate() -> str:
    """`cold_start_prompt` 的「一次送审的门槛按这一趟算」那一节。

    为什么必须在这里再说一遍：`specs/v.py` 的 policy 渲染进 `system_prompt("V")`，
    而 V 的真机审阅不走 system prompt —— `agent_v/core.py::verify_proof` 用
    `cold_start_prompt` 拼好问题直接问一次（全仓没有任何生产路径渲染
    `system_prompt("V")`）。只在 policy 里写，真机上的 V 一个字都读不到。

    业主 2026-11-04 逐字：「就说拿到 V 签，不需要知道 V 内部会连续三次审」⇒
    这里不写轮数、不写「三转 / 连判」这类教程式说法，只说框架按这一趟送审自己数门槛。
    判据 `tests/test_v_internal_streak_is_not_taught.py` 的 e/f（复用同一份 FORBIDDEN）。
    """
    return (
        "\n## 一次送审的门槛按这一趟算\n"
        "- 轮数与门槛由框架按这一趟送审自己数（你不需要推断它，也别在回复里写"
        "「再来一轮就到了」）；**跨趟不累计**：上一次送审判过的，这一次不算"
        "（同一份正文改过之后也是一趟新的）。\n"
        "- **任一转判 `fault` ⇒ 立刻终止**：那一转就是终局，不接着判后面的轮次。"
        "秘书把这一份**有毛病**落成 V 稿 `verifications/reviews/v-review-NNNNNN.md`"
        "（审的是哪份稿 / 有毛病 / findings 与理由），并投给**被审者**（F / E / B）——"
        "那是信息型板项，读到你就算收讫，**不要求你或他再 ack 一次**。\n"
    )


def cold_start_prompt(statement_full: str, proof_text: str,
                      *, readonly_facts: str = "",
                      citations: Sequence[Mapping[str, Any]] = (),
                      citations_problem: str = "") -> str:
    """V 的冷启动提示词（纯函数：只有对象 + 只读读数，没有 F 的叙述、没有 store 句柄）。

    为什么把"提示词怎么拼"做成纯函数而不是塞进角色循环里：I12 是一个结构性质 ——
    "给它的上下文里有没有 F 的叙述 / 有没有 store 句柄"必须能被判据直接断言
    （`tests/test_verifier_role.py` 就是这么判的）。塞进循环里之后，它只能靠"读代码相信"。

    `readonly_facts` 是已经渲染好的只读读数（命题/文献/实验台账的摘要，由调用方
    从只读查询面取好传进来）—— 传字符串而不是传 store，是为了让"它能碰什么"在接口上
    就固定下来。

    `citations` 是引用核实的材料（`agent_v.core._citation_material` 的返回）：F 对每条被引命题的说法
    与被引命题的正文摘要一起进来。它仍然只是一串字符串（没有 store 句柄），
    但它是 F 的叙述 —— 所以接口上多这一格是刻意的：V 要核 F 的引用，就必须看到 F 的
    说法，这是 `draft/39` 里"不给作者叙述"那条纪律的一处有边界的例外（只给被引命题的
    依赖行，不给整份证明的作者解释）。
    """
    # 开关读数（读不懂按"关"算：与 settings 的 fail-closed 同向）
    try:
        from .settings import lean_enabled as _le

        _lean_on = bool(_le()[0])
    except Exception:  # noqa: BLE001
        _lean_on = False
    return (
        "你是验证者（V）。你这一次只做一件事：把下面这份证明按写成后的样子整体重读一遍，"
        "判断它站不站得住。\n\n"
        "你不写、不改证明；不判这命题值不值得做；不做稿件级正式审查。\n\n"
        # ---- 业主 2026-11-01：V 的结论只有两态（逐字见下）----
        #
        # 这一段是结论词那一根轴，与秘书那一条（它判的是回复的措辞）是两张词表。
        # 判据：`tests/test_v_verdict_is_two_states.py` 的 s4（这一份与 system prompt
        # 都要有两态那两句，且 `看不出来` 只许出现在那句否定式里）。
        "## 结论只有两态\n"
        "- " + TWO_STATE_LINE + "。\n"
        "- " + NO_THIRD_STATES + "。\n"
        "- 你判「成立」时不需要证明它正确，只需要说明你沿下面那几条角度都没找到缺陷。"
        "你的 `verdict` 只是陈述，不是判据：框架不会按这两个字机械定轴 —— 每一转的"
        "clean / fault 由你的秘书读这段回复后语义判定（它会写清依据）。所以拿不准、信息不足、"
        "某个记号没定义时，别用一句话糊过去：把「卡在哪一步」写进 `findings`（带步号）与"
        "`defect_step`，让秘书判得出 fault；不许写成「成立 + 一条备注」。「成立」= 零 finding："
        "`findings` 必须为空；只要有一处要改的（哪怕只是措辞建议、`level=info`），就是 `有毛病`，要指到那一步。\n\n"
        # ---- 业主 2026-10-29 追加口径：V 只产意见；发签的判定与写盘都不在 V 手上
        # （在册档由秘书判定、框架侧落盘；未在册档由 V 颁发信封、收方秘书落块 ‖
        # S5 的提示词落点；两档的边界见 `specs/v.py` 的「发签权的边界」）----
        #
        # 这一段的判据是 v9（`tests/test_v_sign_gate_streak.py` 的 c4）：V 的可见文本里
        # 不出现「签在我」「我已经签过了」这类说法，而「签由秘书」（在册档那半句）
        # 必须写出来。
        "## 你产出什么、不由你决定什么\n"
        "- 你只审手稿：命题正文读稿的 `## 命题`，证明全文读 `## 证明`，依赖面读 `## 依赖`；"
        "你产出一份审稿意见（下面那个 JSON），它进 `verifications/<命题号>.jsonl` 那一行。\n"
        "- 签落在稿上（`- V 签：` 那一行签块）；侧文件在 `out/vsigns/<被审正文的 sha>.json`"
        "（一稿一签：正文改一个字，那一签就作废），落块由收方秘书做。"
        "在册档发不发签由你的秘书判定并落盘；未在册档由你颁发签信封、由收方秘书落块。"
        "你写「成立」不等于签上了：到位没有看稿上的签块与那一个侧文件，不是你的判词。"
        "所以别在回复里写「我已经签过了」「这一条签住了」。\n"
        # ---- 2026-11-08（业主「V 只对手稿负责」）：签落在稿上，命题位 / 等级 / 路径号归 B ----
        #
        # 改前这一格写着「看签文件与五元位第 3 位」、并把台账那一行叫「签的正本」——
        # 那两句在 V 不看 statements 之后都成了假话（`specs/v.py` 的写集为空，
        # `agent_v.core` 的命题正文只从稿的 `## 命题` 读）。判据：
        # `tests/test_v_prompt_owns_the_manuscript_only.py`。
        # 2026-11-11（业主裁定：签跟着正文走）：签的身份是正文 sha + 稿路径，不是"第几份证明"。
        "- 命题位（第 3 位）、等级、以及这份稿算哪条证明路径（`path_group`），都由 B 收录这份稿时"
        "决定，不在你这一侧；**签的身份是正文 sha + 稿路径**（`proof_manuscript`，"
        "sha 就是那份稿 `## 证明` 现在的 sha）：你只负责这一份手稿站不站得住。\n"
        + verifications._cold_start_submission_gate()
        # ---- 2026-11-08（业主「V 只对手稿负责」）：签完之后那两格读数要读得懂 ----
        + "\n## 你这一签之后：两格读数与六档\n"
        "- 稿上已签、已入台账是两格分开的读数：稿上已签看稿里的 `- V 签：` 签块"
        "（`已签` / `连续` / `正文sha`），已入台账看 `statements` 里这一份正文的 sha 与第 3 位。\n"
        "- `signed_pending_filing`：稿上已签、册里还没有证明行（或第 3 位没翻）⇒ 等 B 收录；"
        "这不是「签丢了」。\n"
        "- `signed_stale_in_ledger`：稿上已签、册里是旧版 ⇒ 签还在，等 B 收录这一版；"
        "册里现行那一版的号与 sha 会在读数里点名。\n"
        "- 另外四档：`filed`（两格都对上）/ `unsigned`（都没签）/ `abandoned`（明确放弃）/ "
        "`unreadable`（没查成）。\n"
        "- 你看不到审阅之外的任何东西：你只看见下面这份命题、证明与只读读数；"
        "谁读你的意见、之后怎么处理，都不进你的输入，也不该出现在你的输出里。\n\n"
        "## 硬禁令（命中哪一条就指到那一步）\n"
        "- 无条件前提（结论要的前提没写出来）；\n"
        "- 无依据的步骤（既没引到在册的 id，也没有同段内的推导）；\n"
        f"- 缝：{'、'.join(HARD_BAN_MARKERS)} 这类「跳过去」的措辞；\n"
        "- 引用到一条不干净的命题（还是猜想 / 已作废 / 只是 assumption）。\n\n"
        "## 只读读数（你只能看这些；没有 store 句柄，也不给你作者的任何解释）\n"
        f"{readonly_facts.strip() or '（调用方没有附只读读数）'}\n\n"
        "## 命题（含完整假设）\n"
        f"{str(statement_full or '').strip() or '（空）'}\n\n"
        "## 证明全文\n"
        f"{str(proof_text or '').strip() or '（空）'}\n\n"
        f"{citations_block(citations, citations_problem)}\n\n"
        "## 只输出一个 JSON 对象（不要解释文字、不要代码围栏）\n"
        '{"verdict": "成立|有毛病", "defect_step": <整数或 null>, '
        '"quote": "<命中的原话，逐字>", "why": "<一句话理由>", '
        '"findings": [{"level": "error|warning|info", "step": <整数或 null>, '
        '"kind": "<短语>", "detail": "<指到那一步的说明>"}], '
        '"citation_checks": [{"stmt_id": "<被引命题号>", '
        '"verdict": "consistent|weaker|stronger|unrelated|inadmissible|unknown", '
        '"quote_verbatim": <true 或 false>, "note": "<一句话依据：一致在哪 / 差在哪>"}]}\n'
        "- `defect_step`：有毛病时必须给出那一步的编号（从 1 起数，按证明里的步骤顺序）；\n"
        "- `成立` = `findings` 为空（零 finding）；有一条要改的就是 `有毛病`，"
        "在 `defect_step` 指到那一步、把那一条写进 `findings`。\n"
        "- 没有第三个词：写成「判不了 / 我无法判断」不是一种结论 —— 那是没做完审；"
        "框架不折档（不把它算成成立、也不算成有毛病），由秘书读这段回复后语义判成"
        "clean / fault，并在 `findings`（带步号）与 `defect_step` 里对得上卡在哪一步；"
        "秘书按题面判「有缺陷要指出」时，这一签不签发。如果你确实找不出缺陷，就把核对记录"
        "写出来（" + NO_THIRD_STATES + "），不是让你写一句「判不了」当答案。\n"
        + _cold_start_review_checklist()
        # ---- 引用核实那一档的口径（业主 2026-10-26 两批裁定，逐字见 CITATION_VERDICTS）
        + "\n## 引用核实怎么判（正常写证明就是不会逐字的；判据不是字面像不像）\n"
        "- `consistent`：F 的用法与这条命题真正说的条件/结论一致（改写、压缩、换符号都行）；\n"
        "- `weaker`：F 只用到了它的弱形式 —— 不等于错，是情报；这一档可以判成立，"
        "但 note 要写清只用到哪一部分；\n"
        "- `stronger`：F 用到的结论比命题本身更强（把结论说强了、或悄悄去掉了它要的假设）；\n"
        "- `unrelated`：这条命题与这一步无关（引错了）；\n"
        f"- `inadmissible`：被引命题的**等级**低于 `{CITATION_EVIDENCE_FLOOR}`（"
        "`conjecture` / `strong_conjecture` / 空）⇒ 不够格被当作依据引，不管用法一致不一致；\n"
        "- `unknown`：材料不足判不了（不在册 / 正文读不到）—— 它不是 `consistent`。\n"
        "- `quote_verbatim` 只当信息记（F 那句话是不是逐字抄的），它不影响结论、也不影响签字。\n"
        "- 有一条 `stronger` / `unrelated` / `inadmissible` / `unknown` ⇒ 这一份不许判 `成立`"
        "（你写成成立也会被改判）；只有全部 `consistent` / `weaker` 才签得成。\n"
        + _cold_start_proof_strength(lean_on=_lean_on)
    )


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    CITATION_EVIDENCE_FLOOR,
    HARD_BAN_MARKERS,
    NO_THIRD_STATES,
    TWO_STATE_LINE,
)
