# -*- coding: utf-8 -*-
"""「拒绝」只有一个形态，且它必须自报理由（`draft/37` §88）。
## 这一组守的是什么
T1 第 2 趟真机（2026-10-04）：`B.register_statement` 被召唤 14 次，其中 8 次返回`{"ok": False, "kind": ..., "error": ...}`，而
`tasks` 台账把它们全记成 `outcome=ok`（detail 还写着"按有产出处理"）—— 主控以为命题登记好了，于是不再改参数，而 `statements` 是 0 行，整条链在这一步静默停住。同一趟里另外 6
次抛异常的调用反倒记成 `failed`："拒绝"与"崩溃"同形，"成功"与"什么都没写"也同形。
修法分两处，判据也分两处：
1. 终态映射（`Conductor._end_from_payload`）不再把 `ok=False` 折叠成 `ok`
—— 判据在 `tests/test_conductor_payload_outcomes.py`；
2. 角色动作的拒绝走同一个落点 :func:`agentflow.refusals.refuse`，并带上受控的
`refusal_reason` —— 判据在本文件。
第 2 条为什么要机器守：它是一条形态纪律（"拒绝要自报理由"），而形态纪律只能靠"新写的代码会被当场抓住"来维持。所以本文件用一个 AST 扫描盯住角色动作模块：凡是手写的
`{"ok": False, ...}` 都必须逐条登记在下面的表里并写明理由（那些是"执行了、没成功"的真失败，不是拒绝），扫描结果与表双向比对 ——表里多一条（豁免腐烂）与少一条（新写的漏网）都会红。
## 2026-10-13：登记表里 `agent_g/paper_package.py` 那三档随旧路退场
业主裁定逐字：「paper_package 里那些东西都是古早废案了，我们要智能体写文章」，范围 A（整条 `paper_package` 路退场）⇒ 那个模块连同它的三档手写失败（`package_build_failed` /
`state_failed` / `anchor_script_failed`）一起删除（退场面与逐条理由见 `draft/117`）。这一条判据的对象是"模块里手写的 `ok=False`"，模块不在了就没有对象可判 ——
所以这里删掉那三行，而不是给一个不存在的机制编新判据。它留下的那一课是失败要把外部工具自己说的话带回来（旧路只回一句"脚本不在盘上"，而脚本的 stderr 当时就在手边，`draft/116` §4）；
接手的判据在`tests/test_papercompile.py`：`test_the_engine_tail_is_carried_when_the_compile_fails`与
`test_the_receipt_on_disk_carries_the_engine_tail`。
"""
from __future__ import annotations

import ast
import pathlib
from collections import Counter

from agentflow import schema as S
from agentflow.refusals import PRECONDITION_REASON, refuse

#: 账骨架渲染（`docs/DEVELOPMENT-SPEC.md` 第 17.1 节）：把「差」渲染成可以直接
#: 粘贴回 `_FAILURES_NOT_REFUSALS` / `_REPEAT_COUNTS` 的整行。只渲染，不写盘。
import _skeleton as SK

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"

#: 手写 `{"ok": False, ...}` 的登记表：`(模块相对路径, kind)` → 为什么它不是"拒绝"。
#:
#: 判据是双向的：新出现一条没登记的就红（新写的动作漏用了 `refuse`），
#: 登记表里有一条扫不到的也红（豁免腐烂成"看起来还在挡着什么"）。
_FAILURES_NOT_REFUSALS: dict[tuple[str, str], str] = {
    ("agent_b/register_statement.py", ""):
        "盘上五处手写 `ok=False`，全是子结果 / 读数格，不是动作自己手写的终态拒绝："
        "① `_numeric_manuscript_channel` 的「这一笔不是 E 的普通数值手稿 / 读不成」"
        "（内部判读的三态返回值，调用方据此继续走普通登记路；真受控拒由收录口按 "
        "`refusals.refuse` 报 `numeric_manuscript_refused` 一类）；"
        "② `_ingest_empty_envelope`（`own.ingest_manuscript` 的固定键信封，受控码走 "
        "`refused`/`reason`）；③ `_land_citation_manuscript` 的 `out` 初值（引文侧开 "
        "b-稿的骨架）；④ `_land_b_manuscript` 的 `out` 初值（B 改写稿的骨架，`refused` "
        "由 `land_rewrite` 那一侧写）；⑤ `_note_conjecture_landing` 的 `ledger`"
        "（猜想台账记账失败时折进 `conjecture_ledger` 的读数，`kind` 取 "
        "`store_error_kind`）。动作层按 `refused` 落终态，这里不各写一次 `refuse`",
    ("agent_b/land_manuscript.py", ""):
        "`land_manuscript` 的返回骨架 `out` 初值（`ok=False`，受控码写在 `refused` 那一格）："
        "与 `register_statement.py` 里那几个同形骨架是同一件事 —— 不是手写的终态拒绝，"
        "由动作层按 `refused` 落终态（T1/D1 收口后一动作一文件拆出来的新模块）",
    # 2026-11-11（B 的优化副本）：同一族的第三处返回骨架。
    ("agent_b/open_polish_copy.py", ""):
        "`open_polish_copy` 的返回骨架 `out` 初值（`ok=False`，受控码写在 `refused` 那一格，"
        "由 `_polish_refusal` 统一写）：与 `land_manuscript` / `register_statement.py` 里"
        "那几个同形骨架是同一件事 —— 不是手写的终态拒绝，由动作层按 `refused` 落终态",
    ("agent_d/poll.py", ""):
        "工具 `research.poll_waiting` 自己失败了（不是参数不对、也不是前置条件不满足）"
        "⇒ 这是「执行了、没成功」，该落 `failed`，不该冒充 `refused`",
    # 2026-10-30（业主口径：三次 = V 连判）：`AgentV._review_one_pass` 的三条"没查成"
    # （模型没给出可解析结论 / 结论不合法 / 台账写不进去）是执行了、没成功，
    # 不是"这次调用不成立" —— 它们必须落 `failed`（每条都带 reason 与 detail），
    # 不许冒充 `refused`：冒充会让"没查成"看起来像"审过了、有毛病"。
    ("agent_v/core.py", ""):
        "V 的一转审校没查成（拿不到合法结论 / 台账写不进去）—— 执行了、没成功，"
        "该落 failed 且逐条带 reason；冒充 refused 会把「没查成」说成「审过了」",
    # 2026-11-12（F1「V 认稿先认逐路径记录」）：同一模块新增的三处身份判定子结果。
    # `_decide_registered_manuscript_identity` 的 `ok=False` 说的是「这一份稿不是这一条
    # 命题的稿 / 逐路径记录没读成」，调用方 `_registered_manuscript_body` 把它们折成
    # `verify_proof` 的 `checked=False`（`kind` / `reason` 照传），终态 payload 里根本没有
    # `refused` / `refusal_reason` 这一格（判据
    # `tests/test_the_first_path_is_still_auditable_after_the_second_one_lands.py` 断言的
    # 正是 `checked is False` + `kind == "bad_manuscript_name"`）⇒ 这是"没查成"的子结果，
    # 不是动作自己手写的终态拒绝。不走 `refusals.refuse`：走它会给「没读成 / 不是这条
    # 命题的稿」盖上 `refusal_reason=invalid_params`，把「没查成」错贴成「你参数写错了」
    # —— 与 `agent_e/author_script.py` 那三条登记在防的是同一个错贴标签。
    # 处数 3 见 `_REPEAT_COUNTS`（逐路径记录认领 / 记录没读成 / 退回老口径后号不等）。
    ("agent_v/core.py", "bad_manuscript_name"):
        "身份判定的三处子结果（行上稿号不是这一条命题的稿 / 逐路径记录没读成 / 退回"
        "老口径「稿名里的号 == 命题号」后仍不等）：`_registered_manuscript_body` 折成"
        "`verify_proof` 的 `checked=False`（没查成），不是终态的受控拒；走 `refuse` 会"
        "给「没查成」错盖 `refusal_reason=invalid_params`（同 `agent_e/author_script.py` "
        "那三条在防的错贴标签）。按处数 3 登记。",
    # 注：`agent_g/paper_package.py` 的三档（`package_build_failed` / `state_failed` /
    # `anchor_script_failed`）2026-10-13 随整条 `paper_package` 路退场而删除
    # （业主裁定与退场面见文件头 docstring 与 `draft/117`）。
    # `E.author_script`（S-10(a)）的三档：都不是"这次调用不成立"，而是
    # "执行了、没成功" ⇒ 该落 `failed`，不许冒充 `refused`（冒充会把
    # "模型网关炸了"记成"你参数写错了"，调用方于是去改一个没错的参数）。
    ("agent_e/author_script.py", "judge_failed"):
        "模型缝没答上来（网关异常 / 回了坏 JSON）：判据与参数都没问题，是这一跳没查成 "
        "⇒ 执行失败。它同一支的另两档（`bad_source` / `write_failed`）见下面两条",
    ("agent_e/author_script.py", "bad_source"):
        "模型回了一份不合格的脚本（没有 `REPRO_RESULT` / 空 / 过长）：调用本身成立、"
        "产出不能用 ⇒ 执行失败",
    ("agent_e/author_script.py", "write_failed"):
        "写盘失败（含落点越界）：读盘/写盘失败是「执行了、没成功」，不等于这次调用"
        "不成立 ⇒ 执行失败（同族的还有工具层的 `paper_compile_failed`：编不出来只是"
        "没编成，不是调用方参数写错了）",
    # `agent_f/core.py` 的两处（P3-6 / F 闭环那批新增的两个产物出口的内部返回值）：
    # 都是子结果，不是动作的终态 payload —— `_apply_round` 只把 `ok` / `why` / `path`
    # 折进 `detail` 与 `history`，`ok=False` 从不冒充一次"拒绝"（判据守的那个坑
    # 是"拒绝被台账记成 ok"，这里根本没有拒绝可记）。所以按登记走，不改道
    # `refusals.refuse`：走它会给这两笔盖上 `refusal_reason=invalid_params`，
    # 而那正是 `author_script` 那三条登记在防的错贴标签（"磁盘满了"被记成"你参数写错了"）。
    # `kind` 这一格是为此加的：两处失败各有一个名字，登记表才能逐条点名、计数也对得上。
    ("agent_f/core.py", "report_write_failed"):
        "攻坚台账 `reports/attack-<plan_id>.md` 写盘失败（`_report_append`）："
        "执行了、没写成 ⇒ 执行失败；而且它**不许**让整轮崩掉，返回值只说"
        "「这一行没落盘」，由调用方在 `detail` 里如实写出来",
    # 注（2026-11-07，解耦落地后的第二次退役）：`statement_handoff_failed` /
    # `statement_handoff_refused` 这两条登记也退役了 —— 那两个手写 `{"ok": False}`
    # 分支现在走 `refusals.refuse`（`_hand_proof` 的受控拒），盘上再也扫不到这两个
    # 名字。按本文件"登记过期就删"的规矩退役；告警方向没变：再手写一个没登记的
    # `ok=False` 照样落进 `missing`。
    # `agent_c/path_shape.py` 的 `_no_spine()`（2026-10-22 登记）：它是子结果，
    # 不是动作的终态 payload —— `{"ok": False, "nodes": [], "edges": [], "length": 0}`
    # 在那一支里的意思逐字是"这条候选路径没算出一条承重脊"（没走到根 / 成环 / 超深度 /
    # 分支超上限），调用方 `_shape_of` 只把它折进该行的 `spine_found=False` 与前沿读数；
    # `path_shapes()` 交出去的 payload 是 `checked` / `rows` / `frontier`，没有 `ok` 这一格
    # ⇒ 这里根本没有"拒绝"可记。不走 `refusals.refuse`：走它会给一条正常的读数盖上
    # `refusal_reason=invalid_params`，那正是 `agent_e/author_script.py` 那三条登记
    # 在防的错贴标签（"没算出脊"被记成"你参数写错了"）。
    ("agent_c/path_shape.py", ""):
        "子结果读数，不是拒绝：`_no_spine()` 表示「这条候选路径没有算出承重脊」"
        "（没走到根 / 成环 / 超深度 / 分支超上限），只被 `_shape_of` 折进该行的"
        "`spine_found=False` 与前沿读数，从不出现在动作的终态 payload 里 ⇒ "
        "「执行了、没成功」与「这次调用不成立」都不是它要表达的东西",
    # 注：同一方法里 `bad_spec` / `no_seam` 两档不在这里 —— 它们是"这次调用本身
    # 不成立"（判据不全 / 没接缝），走 `refusals.refuse`（先例：`A.search_literature`
    # 的 `no_provider` 与 `A.ingest_local` 的 `bad_books_dir`）。所以 `author_script`
    # 那一族只登记 `judge_failed` / `bad_source` / `write_failed` 这三档；
    # 扫出来多一条或少一条都会红。
    # ---- 2026-10-26（H3）补登的五个模块：都是"子结果 / 读数格"，不是动作的终态拒绝。
    # 它们全是新模块（L 的形式化入口、E 的报告读数、F 的手稿出口、D 的逐行记录面）
    # 落地时带进来的，判据在它们落地的同一天就该登记 —— 这一批补的是登记，不是口径。
    ("agent_l/formalize.py", ""):
        "子结果，不是拒绝：`_pick_statement` / `_path_choice` / `_checked_row` 那十一处"
        "`{\"ok\": False, ...}` 说的是「这一条候选（声明 / 证明路径）不成立」，"
        "调用方 `formalize` 拿它去拼 `self._refusal(...)` —— 那一条才走 `refusals.refuse`，"
        "受控理由与 `refusal_reason` 都在那一侧。所以这里没有一次独立的拒绝可记。"
        "不走 `refuse` 的理由同 `agent_c/path_shape.py` 那一格：会给一条正常的"
        "「换一条证明路径」的读数贴上 `refusal_reason=invalid_params`。"
        "2026-11-09 多出第十二处（同一格）：按号取待形式化那一条改走查口之后，"
        "`statements` 读不出来时回 `statement_ledger_unreadable` —— 那是「没查成」，"
        "冒充受控拒会把「读不出来」说成「你说错了」，所以照旧落 `failed`",
    # 2026-11-05（p241 手稿统一之后复核）：这一格只剩 `preview_dependencies()` 的 `out`
    # 那一处；`proof_manuscript()` 的写盘失败已随 910b3031 搬进
    # `manuscriptform.commit_manuscript`（那里返回 `{"ok": False, ...}` 的 `got`，由
    # `proof_manuscript` 折成 `"ok": bool(got.get("ok"))`，不再是手写字面量）。
    # 不删这一条：盘上实测仍有一处（`preview_dependencies()` 的 `out` 初值），处数见
    # `_REPEAT_COUNTS` 的 1。`manuscriptform.py` 那几处 `{"ok": False, ...}` 不进本表：
    # 本判据的扫描面是 `_role_action_modules()`（只收 `agent_a` … `agent_h` 下的模块），
    # 而它是跨族共用的实现层，那几处都是子结果（命名 / 形状 / 落盘事务的读数），
    # 由 F/B 的转发层折进各自返回，从不直接作为角色动作的终态 payload。
    ("agent_f/manuscript.py", ""):
        "子结果：`preview_dependencies()` 的 `out` 是「这一节读不出依赖边」的读数，"
        "被 `agent_f/core.py` 折进 `detail` / `history`，从不冒充动作的终态拒绝，"
        "也没有受控 `kind` 可记（同族的写盘失败已搬进 `manuscriptform.commit_manuscript`，"
        "那一层不是角色动作模块、不归本表）。"
        "2026-11-10（稿号口径，p272/p274/p275）：`proof_manuscript()` 另有两处同形的返回骨架 ——"
        "「手稿号不是六位号 ⇒ 这一份稿不落盘」与「手稿号拼不出规范路径 ⇒ 这一份稿不落盘」。"
        "号由框架的号源（`manuscriptids.next_manuscript_id`）发，坏号是内部数据不一致"
        "（执行了、没成功），不是调用方的参数错 ⇒ 它们仍是子结果，由 `_wash_manuscript` / "
        "detail 折进返回值，不走 `refusals.refuse`（走它会给内部读数错贴 `invalid_params`）。"
        "2026-11-11（拿签冻结，业主裁定 ②）：`proof_manuscript()` 的第三处骨架是"
        "`_frozen.frozen` 那一支（`refused=kind=manuscript_frozen`）—— 它同样是子结果"
        "（由 `_hand_proof` 折成动作层的受控拒），不是手写的终态 payload；处数 3 → 4。"
        "2026-11-13（业主裁定 B）：`proof_manuscript()` 的第四处骨架是 `_missing`"
        "（没有 `product.proposition` ⇒ 这一版没有可渲染的 `## 命题`，"
        "`refused=kind=proposition_missing`）：它由动作层的形态闸折成受控拒，"
        "这一层只是「一个字节都不写」的兜底读数；处数 4 → 5。",
    ("agent_f/core.py", ""):
        "子结果（三处）：① 手稿那一支的局部 `manuscript = {\"ok\": False, ...}`（没写成时给"
        "调用方看的读数）。与同文件里那四条带 `kind` 的真失败不同，它没有名字、不进终态 "
        "payload，只在 detail 里留一句；② 2026-11-11（p286，`attack.step(product=…)` 通道）"
        "新增的 `parse_handed_product()` 的返回骨架 `out` 初值 —— 它是三态解析器的初值"
        "（`checked` / `ok` / `kind` / `product` / `problems` / `label`），`ok=False` 的"
        "意思是「还没核完」，不是「这一轮被拒」：真正的受控拒由 `_handed_product_round` "
        "在 `refusal` 里带 `kind=HANDED_PRODUCT_REFUSED` 的那一支产出（受控码 + 逐条点名 + "
        "`next_step`，落 history 的 `refusal` 格），动作终态 payload 里根本没有 `ok` 这一格。"
        "③ 2026-11-14（TR 收口）`_ledger_open_manuscript()` 的 `ledger`：开稿台账读/写失败"
        "时折进返回值的读数（`kind` 取 `store_error_kind`）—— 执行了、没成功，不是一次拒绝。"
        "⇒ 三处都不是动作自己手写的终态拒绝，按处数登记，不走 `refusals.refuse`"
        "（走它会给一份正常的解析读数贴上 `refusal_reason=invalid_params`）",
    ("agent_d/write_report.py", ""):
        "读数格：`rec` 是逐行登记的记录（`{\"statement_id\": ..., \"ok\": False, ...}`），"
        "落进报告的表格里；它不是动作的返回值，也不会被台账当成一次拒绝",
    ("agent_e/run_experiment.py", ""):
        "读数格（`report` / `manuscript` 两处）：一般数值实验既不写报告、也不落手稿的那一支，"
        "`{\"path\": \"\", \"bytes\": 0, \"sha256\": \"\", \"ok\": False, ...}` 说的是「这一趟没有落盘物」"
        "（终态 payload 的 `report_path` / `proof_manuscript` 因此读成空串、`problems` 为空），"
        "只是被折进那几格读数的局部值，不是一次拒绝；动作本身的拒绝走 `refuse`（那一族都带 `kind`）"
        " ⇒ 要表达「这次调用不成立」请走 `refuse`，不要在这里手写 ok=False。"
        "2026-11-14（TR 收口）第三处：实验台账写失败时折进返回值的 `_ledger`"
        "（`kind` 取 `store_error_kind`）—— 执行了、没成功，同样是读数格",
}


#: 同一 `(模块, kind)` 出现多次时的处数（不在表里的默认 1 处）。
#:
#: 2026-10-26（H3）把这条能力从"在判据体里手写一行覆盖"改成一张显式表：有两个以上
#: 同 `(模块, kind)` 的模块都在这里点名，计数逐条来自盘上实测。为什么需要它：
#: 登记表是 `(模块, kind)` → 理由，一个模块里同一种子结果出现十一处也只写一条理由；
#: 不给处数的话，"十一处里删掉三处"这种改动没有任何东西看得见 —— 而那张表声称的
#: 正是"每一处都在册"。两个方向都照旧：盘上比表里多 ⇒ `missing` 红，表里比盘上多
#: ⇒ `stale` 红（豁免腐烂）。
_REPEAT_COUNTS: dict[tuple[str, str], int] = {
    # 2026-11-10（T1/D1 收口 + 拆包）：`register_statement.py` 的 `ok=False` 返回骨架
    # 是 3 处；`land_manuscript` 的那一处随一动作一文件拆到自己的模块
    # （见 `_FAILURES_NOT_REFUSALS` 里那两条的登记理由：都是 `out` 初值 / 固定键信封，
    # 受控码走 `refused`，不是手写的终态拒绝）。2026-11-14（TR 收口）盘上 5 处：
    # 另两处是 `_land_b_manuscript` 的骨架与 `_note_conjecture_landing` 的台账读数
    # （理由同在那一格：子结果，不是终态拒绝）⇒ 3 → 5。
    ("agent_b/register_statement.py", ""): 5,
    ("agent_b/land_manuscript.py", ""): 1,
    # L 的形式化入口：十一条"这一条候选不成立"的子结果（`_pick_statement` 五条、
    # `_path_choice` 五条、`_checked_row` 一条），kind 都是空串；2026-11-09 多出第十二处
    # （按号取待形式化改走查口之后，`statements` 读不出来那一档）。
    ("agent_l/formalize.py", ""): 12,
    # 2026-11-10（稿号口径）：`proof_manuscript()` 多出两处同形的返回骨架
    # （手稿号不是六位号 / 拼不出规范路径，各一处），加上 `preview_dependencies()` 的
    # 读数一条 ⇒ 1 → 3。2026-11-11（拿签冻结）：`manuscript_frozen` 那一支的返回骨架
    # 也是同形读数（`ok=False` + `refused/kind`），3 → 4。2026-11-13（业主裁定 B）：
    # `proposition_missing` 那一支的 `_missing` 骨架，4 → 5。五处都是子结果，理由见
    # `_FAILURES_NOT_REFUSALS` 里那一格。
    ("agent_f/manuscript.py", ""): 5,
    # 2026-11-11（p286）：`agent_f/core.py` 的空 kind 处数 1 → 2。新增的那一处是
    # `parse_handed_product()` 的返回骨架 `out` 初值（三态解析器的"还没核完"，不是终态
    # 拒绝；真正的受控拒由 `_handed_product_round` 的 `refusal` 那一支产出）。
    # 2026-11-14（TR 收口）第三处：`_ledger_open_manuscript()` 的台账读数，2 → 3。
    ("agent_f/core.py", ""): 3,
    # 2026-10-30（业主口径：三次 = V 连判）：`AgentV._review_one_pass` 有三条"没查成"
    # （拿不到合法结论 / 结论不合法 / 台账写不进去），三处逐条都在盘上。
    ("agent_v/core.py", ""): 3,
    # 2026-11-12（F1）：同一模块身份判定的三处子结果（`bad_manuscript_name`，见
    # `_FAILURES_NOT_REFUSALS` 里那一格的理由）—— 逐路径记录认领 / 记录没读成 /
    # 退回老口径后号不等，三处逐条都在盘上。
    ("agent_v/core.py", "bad_manuscript_name"): 3,
    # `agent_e/run_experiment.py` 一般数值实验那一支的两处读数格：`report`（报告没落）
    # 与 `manuscript`（`reports/e-proof-<号>.md` 没落，2026-11-03 E 的手稿读数落地时
    # 成为第二处）。2026-11-14（TR 收口）第三处：实验台账写失败时的 `_ledger`，2 → 3。
    # 三处 kind 都是空串，所以靠这张表记处数。
    ("agent_e/run_experiment.py", ""): 3,
    # 2026-11-04（同上）：`agent_d/write_report.py` 的 `rec` 是逐行记录的读数格，
    # 盘上有两处 —— `statement` 那一张与 `experiment` 那一张；两处 kind 都是空串。
    # 2026-11-07（解耦落地）：第三处 —— F 的登记条目（`mss:` 行）也是同形的读数格
    # （`_deliver_f_manuscript_row` 的 `rec`：还没递出去时 `ok=False`，它不是动作返回、
    # 不进台账）。计数 2 → 3，理由与该表里那两处逐字相同。
    ("agent_d/write_report.py", ""): 3,
}


# ------------------------------------------------------------------ 一、共享落点

def test_refuse_shape_is_complete_and_controlled():
    """正控：`refuse` 四件套齐备，理由取自受控词表。"""
    out = refuse("bad_mode", "mode 不认识", mode="precise")
    assert out["ok"] is False
    assert out["kind"] == "bad_mode" and out["error"] == "mode 不认识"
    assert out["refusal_reason"] == PRECONDITION_REASON, out
    assert out["refusal_reason"] in S.REFUSAL_REASONS, (
        "拒绝理由必须是受控词表里的值 —— `Task.validate` 逐字要求"
        "（不许自由文本），不在表里会在写台账那一刻抛")
    assert out["mode"] == "precise", "动作自己的读数不许因为改形状而丢"


def test_the_precondition_reason_matches_the_vocabulary_note():
    """负控（判据的接点）：`invalid_params` 这一档必须仍在词表里、且语义仍是这一档。

    这一条挡的是"词表被人悄悄改名/删档"：那时 `refuse` 造出的每一条拒绝都会在
    写台账时抛异常 —— 而错误信息会指向词表，排查方向离这里很远。
    """
    assert PRECONDITION_REASON == "invalid_params"
    assert isinstance(S.REFUSAL_REASONS, tuple), "理由词表是元组（一处定义）"
    assert "invalid_params" in S.REFUSAL_REASONS


# ------------------------------------------------- 二、形态纪律：手写 ok=False 要登记

def _hand_rolled_ok_false(text: str) -> list[tuple[int, str]]:
    """扫一个源文件里手写的 `{"ok": False, "kind": ...}` ⇒ `[(行号, kind)]`。

    判据取的是"字典字面量里同时出现 `"ok": False`"，因为它对返回与
    `out.update({...})` 两种写法都一样 —— 旧路 `G.paper_package` 用的正是后一种
    （只扫 `return` 会漏掉它，第一版就是这么漏的）。那个动作 2026-10-13 随
    `paper_package` 整条退场了（`draft/117`），但"只扫 `return` 会漏掉另一种写法"
    这条教训与扫描面本身不随它退场 ⇒ 判据照旧收字典字面量，不改成只扫 `return`。
    """
    tree = ast.parse(text)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        pairs = {k.value: v for k, v in zip(node.keys, node.values)
                 if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        ok = pairs.get("ok")
        if not (isinstance(ok, ast.Constant) and ok.value is False):
            continue
        kind = pairs.get("kind")
        found.append((node.lineno, kind.value if isinstance(kind, ast.Constant)
                      and isinstance(kind.value, str) else ""))
    return found


def _role_action_modules() -> list[tuple[str, pathlib.Path]]:
    """角色动作模块清单（`agent_a` … `agent_h` 下的 `.py`）。"""
    out: list[tuple[str, pathlib.Path]] = []
    for d in sorted(SRC.glob("agent_?")):
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.py")):
            out.append((p.relative_to(SRC).as_posix(), p))
    return out


def test_the_scanner_sees_a_synthetic_hit():
    """负控（反真空）：扫描器在人造样本上必须命中，否则"没扫到"无法与"干净"区分。"""
    hits = _hand_rolled_ok_false('def f():\n    return {"ok": False, "kind": "x"}\n')
    assert hits == [(2, "x")], hits
    assert _hand_rolled_ok_false('def f():\n    return {"ok": True, "kind": "x"}\n') == []


def refusal_registration_scan() -> tuple[
        int, Counter[tuple[str, str]], Counter[tuple[str, str]],
        Counter[tuple[str, str]], Counter[tuple[str, str]]]:
    """扫盘并对账 ⇒ `(扫到的模块数, 盘上, 应有, 没登记, 登记过期)`。

    判据本体与开发入口 `scripts/render_registration_skeletons.py` 共用这一处口径：
    两处各扫一遍，就是「同一个差两份实现」，而其中一份迟早会与另一份不一致。
    """
    live: Counter[tuple[str, str]] = Counter()
    scanned = 0
    for rel, path in _role_action_modules():
        text = path.read_text(encoding="utf-8")
        scanned += 1
        for _lineno, kind in _hand_rolled_ok_false(text):
            live[(rel, kind)] += 1
    want = Counter({pair: _REPEAT_COUNTS.get(pair, 1) for pair in _FAILURES_NOT_REFUSALS})
    return scanned, live, want, live - want, want - live


def test_every_hand_rolled_failure_is_registered_and_the_table_is_not_stale():
    """双向判据：手写 `ok=False` 的每一处都要登记；表里每一条都要还能扫到。

    少一条 = 新写的动作漏用了 `refuse`（那一次拒绝又会被记成 ok，回到 T1 的坑）；
    多一条 = 豁免腐烂（登记的理由已经不成立，表在假装还挡着什么）。

    失败信息里嵌的是「账骨架」：没登记的那些直接给成可粘贴的元组行（理由留占位），
    登记过期的那些给成「删哪一行」。这是 `docs/DEVELOPMENT-SPEC.md` 第 17.1 节的
    检测面 —— 红照旧红，人只剩「复核 + 补一句理由」。
    """
    scanned, live, want, missing, stale = refusal_registration_scan()
    assert scanned >= 8, f"只扫到 {scanned} 个角色动作模块 ⇒ 扫描面接错了"

    # 注：这里原本还有一行把 `package_build_failed` 覆盖成 2（"渲染失败 / 编译失败两处"）。
    # `R2b-⑬` 把那两个手写分支合并成了一条（阶段名走 payload 的 `stage` 那一格），
    # 所以这一档现在只剩一处，覆盖行随之删除。这不是放宽判据：`want` 仍逐条来自登记表，
    # 计数对不上（少一处）照样落进下面的 `stale`。

    assert not missing, SK.refusal_missing_message(missing)
    assert not stale, SK.refusal_stale_message(stale)
    for (rel, kind), reason in _FAILURES_NOT_REFUSALS.items():
        assert len(reason) > 20, f"{rel}:{kind} 的登记理由太短，等于没写为什么"


def test_the_three_refusing_actions_really_return_a_controlled_refusal(tmp_path):
    """正控（端到端）：三条动作的拒绝现在都带受控理由 —— 而不是只改了源码形状。

    为什么要落到真对象上：上面那条 AST 判据只能看出"没手写 ok=False"，
    看不出"它真的调了 refuse"。这一条把两个最容易漏的动作各调一次，
    断言那一笔零写入且带 `refusal_reason`。
    """
    from agentflow.agent_a import AgentA
    from agentflow.store import Store

    ws = tmp_path / "ws"
    ws.mkdir()
    st = Store(ws)
    st.init()
    a = AgentA(st, providers=[])

    empty = a.ingest_local(books_dir="  ")
    assert empty["ok"] is False and empty["kind"] == "bad_books_dir", empty
    assert empty["refusal_reason"] == PRECONDITION_REASON, empty

    missing = a.ingest_local(books_dir="没有这个目录")
    assert missing["ok"] is False and missing["kind"] == "dir_not_found", missing
    assert missing["refusal_reason"] == PRECONDITION_REASON, missing
    assert missing["resolved"], "解析出来的路径要给出来（'我指对了没有'不用猜）"

    no_provider = a.search_literature(topic="stable norm of periodic graphs")
    assert no_provider["ok"] is False and no_provider["kind"] == "no_provider", no_provider
    assert no_provider["refusal_reason"] == PRECONDITION_REASON, no_provider

    assert st.rows("literature") == [] and st.rows("search_requests") == [], (
        "被拒的调用不许留下半行")


