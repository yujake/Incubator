# -*- coding: utf-8 -*-
"""验证者（V）的证明级审校台账（`draft/39` §3.21 五）。

## 先分清三个"档"（R-EVID 审查的 ③；零行为改动，只是点明词）

同一个"档"字在这一族里指三根不同的轴，谁都不许拿一根去顶另一根：

* `evidence_kind`（本模块最常说的"档位"）—— 真身 `schema.EVIDENCE_KINDS`
  （`proof` / `proof_review` / `cross_check` / `heuristic`，从强到弱）。它回答
  "这条断言的证据是哪一类"。本模块只用它判一件事：够不够格被引
  （`CITATION_EVIDENCE_FLOOR`，现算前缀，不抄字面量）。
* `GRADES`（本模块说的"定理档"）—— 真身 `evidencebits.GRADES`
  （`conjecture` / `strong_conjecture` / `pre_theorem` / `theorem`）。它由五元位
  派生（`evidencebits.derive_grade`），本模块的 `statement_grade` /
  `_highest_grade` 只是在多证明模型里"取最高"。
* `T0`–`T4`（非平凡性档）—— 不归本模块：真身在 `secretary.py`
  （`nontriviality_label` 与它那张 band 表）。本模块一个字都不定义它。

五元证据位（§3.14）的第 3 位（"审过"）的 owner 是 V：一个 F 配一个验证者，它把 F 交回来的
证明按写成后的样子整体重读，做三件事（用户点名的 I12/I10/I17）：① I12 冷启动 —— 每次审校开
新会话，只给对象（证明全文）+ 只读查询面的读数，不给 F 的叙述、不给 store 句柄 ⇒ "独立性"
是结构性质而不是一句约定；② I10 硬禁令 + 同段依据 —— 逐条查（无条件前提 / 无依据的步骤 /
"易证、显然、trivial"这类缝 / 引用的命题是否干净），每条问题指到那一步并给理由；③ I17 整篇
重读 —— 把证明当一次输入整体读（"这些缝正是正确的事实变成错误证明的地方"），而不是只逐单元
核对。
## 落点与形态（与手稿同一形态：追加式 JSONL，不新增台账表）
`<工作区>/verifications/<命题号>.jsonl`：一行 = 一次审校，至少要有输入证明的 `sha256`、两态
结论、逐条 findings（每条带步号）、用了哪个只读面、验证者实例名；编号 `v-0001…` 按文件内顺序
发（与手稿编号、台账 id 同一套做法）。
## V 的判词只是陈述；轴只有两态，且只由秘书的语义分析给出（p247）
`VERDICTS` 只有 `有毛病` / `成立` 两格，但它们现在是轴（clean / fault）的两个名字，
不是 `parse_verdict` 的词表。台账行上的 `verdict` 是 V 写下的陈述：它原样落盘、
原样读出（:func:`read_verdict`），框架不从它推任何状态 —— 第三次收紧的
原话：「V 的判词只是陈述」「不做折档」「不许按词面把判不了 / 看不出来 / 拿不准 /
我无法判断折成任何一态」。每一转的轴由 V 的秘书读这段回复后语义判定
（`secretary_judge.axis`，唯一读口 :func:`secretary_axis`，`clean` / `fault`），
连续次数与签发只看那个轴。秘书判 fault 而 V 没给 `defect_step` 时，由秘书定出那一步
（`Secretary.judge_v_reply` 的 `defect_step` 读数）。

"检查器自己没跑成"（模型输出不是合法 JSON、缺 `verdict` 字段、findings 形状坏）不是轴 ——
`record()` 在没有可解析的陈述时抛 `VerificationError`，绝不写一行"没查成"来冒充"审过了"。
历史值「看不出来」（旧行）仍读得出，
但它不折成任何一态、不算票、也不签。

### p247：连"历史值按成立读并计票"也取消了
改前（2026-11-02 到 p246）读侧给老行上的 `看不出来` 留了一条"按成立读并计票"的兼容支。
p247 的口径是"判词只是陈述" ⇒ 那条兼容支也删了：老行的陈述原样读出，轴为空
（:func:`secretary_axis` 读成空串）⇒ :func:`_hold_run_lengths` 对它按"这一行的轴读不出来"
处理（不算票、也不清零），:func:`row_signable` 为假。这是收紧方向：老工作区的连续数会回到
"只数得出真有秘书轴的行"，不会再把一个已经不存在的档当成通过。
* 台账文件不改写（追加式，迁移要重写历史行 ⇒ 不做）：盘上那四个字仍是原始读数。
签"审过"（§3.21 五）：轴是 `clean` 且 findings 里没有未解决的 `error` ⇒ `signs_bit3()`，
`bit3_payload()` 给出五元位第 3 位那份读数（`reviewed=True` + 凭据）。
## 「复核过的是哪一份」怎么记（治那处结构性断链）

签的身份 = 正文 sha + `statement_id` + 稿路径（签文件已不写 `proof_no`；老台账行上仍有
`proof_no` / `rev` 这些历史键，读侧照旧认、写侧不再写）。
每条证明各自有第 3 位（`reviewed`）：签的是"这一份的每一步站得住"，别的证明不许借光。
判定永远看那条证明现在这一份正文：它的现行 sha 有「成立」那一签 ⇒ `signed`；
签的是旧版 ⇒ `stale`（待复核，第 3 位不计）；被签过、结论不是「成立」⇒ `rejected`；
一次都没签 ⇒ `unsigned`。命题级的定理档 = 在 in-sync 的证明里取最高
（:func:`statement_grade`），一条 in-sync 都没有 ⇒ 猜想。
哈希只回答"这份稿在你签完之后有没有被改过"，它是读数，不是授权凭证：任何写入路径都不因
sha 不符而拒收（`proof_review_gaps` 明确把 `stale` 当成"待复核"这个读数，而不是"没有凭据"）。
签名落盘之后「同一次写」把那条证明的 `reviewed` 翻上去（:func:`sign_statement`）：
先追加台账那一行、再在 `statements` 的事务里改那一行；事务没成就把刚追加的那一行撤回。
逐条证明的第 3 位落在命题行的 `bits.evidence.reviewed_by_proof`（老行的 `{"1": true, "2": false}`），
而 `bits.reviewed` 仍是"任一份成立即为 True"的汇总位（老读者只认它）。汇总位要按"任一份
仍 in-sync"读，就必须知道每一签盖住的是哪一份正文 ⇒ 同一次写还落一张 `bits.evidence.
reviewed_sha_by_proof`（`{"1": "<sha256>", "2": ""}`，见 `evidencebits.REVIEWED_SHA_BY_PROOF_KEY`）。
## 老键与老行（兼容，不迁移）
更早的真机行只有 `statement_id`（没有 `stmt_id`），更早的写法还可能把证明号写成 `rev`。
读侧认这三对写法：`stmt_id` 缺 ⇒ 读 `statement_id`；`proof_no` 缺 ⇒ 读 `rev`；
两个都没有 ⇒ `1`（见 `proofloc`）。写侧只写正名 —— 迁移要重写历史台账，
而兼容只需要一行读法，且不会把"谁在什么时候签的"改成"我们改写过它"。
## 引用核实（V 要核 F 的引用，而 F 的引用不是逐字引文）
F 在 `dependencies` 上登记"这一份证明用到哪条在册命题"（`used_by` / `path_group` /
`source_stmt_id` / 那一行的人话）。那是自然语言描述（"由引理 2"、"由 Sylow I 可知"），
不是逐字引文 ⇒ 只把编号交给 V 没有用，V 必须看到两样东西：F 是怎么说的、被引命题真正
说的是什么（`agent_v.core._citation_material` 把两边一起取出来，正文摘要一起进提示词）。
V 逐条给一档结论（:data:`CITATION_VERDICTS`：`consistent` / `weaker` / `stronger` /
`unrelated` / `inadmissible` / `unknown`），读数是 `citation_checks` 那五格
（:data:`CITATION_CHECK_KEYS`；第 5 格 `in_material` 说明这一条是不是这一份证明登记的引用），
随台账那一行落盘。签字前置（:func:`signs_bit3`）：
只要有一条 `stronger` / `unrelated` / `inadmissible` / `unknown`，这一签就不许落地
（:func:`citation_gate` 点名是哪一条、差在哪）；`weaker` 可以签，但读数里点名"只用到了
弱形式"；档位不够格（低于 `proof_review`，业主逐字「proof_review级及以上才可引用」）
是事实而不是判断，由 :func:`evidence_kind_admissible` 从 `schema.EVIDENCE_KINDS` 现算。
"""

# 2026-11-20（VERSPLIT2：体量软基线不抬，只拆）：18 个模块按 SPLIT-2 的设计搬进
# `v_*.py`，本文件只剩门面 —— 下面按模块再导出全部 177 个顶层名字，所以所有
# `from .verifications import ...` 的调用点一个字都不用改。
#
# 打桩面没有变弱：测试 `monkeypatch.setattr(verifications, "<名字>", ...)` 改的是本模块
# 的全局字典，而搬走的代码对那 34 个名字的读全部写成 `verifications.<名字>` —— 调用那
# 一刻才查这张字典，所以单点打桩仍然到得了实现（判据见 `temp/versplit2/`）。

# 下面这一段是搬家前的同一张 import 表，刻意留在门面上：它此前是"公开面"的一部分
# （`VR.JF.read_jsonl` / `VR.S` / `VR.DEFAULT_PROOF_NO` 这类读法在测试与调用方里都有），
# 搬走的块各自 import 自己那一份，而这一份只为了让 `verifications.<名字>` 一个都不少。
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import depsection as _DS  # 可引门槛的唯一定义（`CITATION_MIN_LEVEL`）
from . import evidencebits as EB  # 等级的唯一派生口（`derive_grade` / 反算表）
from . import jsonlfile as JF
from . import manuscriptproducers as _MSUB  # 产出方格（路径族 × V 的父名单）
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）
from . import statementbody as _SB  # 命题正文的唯一读口（被引命题的正文从这里取）
from . import statementledger as SL  # 命题台账的查口（按号 / 按关键词，只读、零模型）
from . import textutil as T  # 引用解析的唯一实现（`citation_ref_parts`，`P-5`）
from .proofloc import DEFAULT_PROOF_NO  # canonical 证明号只有一个出处（`proofloc`）

from .v_vocab import (  # noqa: F401 — 再导出：词表与常量
    CITATION_BLOCKING,
    CITATION_CHECK_KEYS,
    CITATION_DIGEST_CHARS,
    CITATION_EVIDENCE_FLOOR,
    CITATION_SIGNABLE,
    CITATION_VERDICTS,
    CODE_AUDIT,
    CODE_WRITE,
    DISPROVED,
    EXHAUSTION_SIGN_STREAK_NEED,
    FAULT_CAUSES,
    FAULT_KINDS,
    FAULT_KIND_SOURCES,
    FAULT_KIND_VALUES,
    FINDING_LEVELS,
    GRADE_BACKFILL_COLUMNS,
    GRADE_RECOMPUTED_KEY,
    HARD_BAN_MARKERS,
    NO_SECRETARY_JUDGE,
    NO_THIRD_STATES,
    PENDING_DIR_NAME,
    PENDING_LOCK_SUFFIX,
    PENDING_LOCK_TIMEOUT,
    PENDING_PREFIX,
    PROOFS_KEY,
    PROOF_CHANGED_SINCE_DISPATCH,
    PROOF_KIND,
    PROOF_NO_KEYS,
    PROOF_REVIEW_KIND,
    REFUTES,
    REQUIRED_FIELDS,
    REVIEW_STATES,
    SECRETARY_JUDGE_AXES,
    SECRETARY_JUDGE_KEY,
    SIGN_STREAK_NEED,
    TWO_STATE_LINE,
    VERDICTS,
    VERIFICATIONS_DIR,
    WEAKER_THAN_PRE_THEOREM_GRADES,
    WEAKER_THAN_PROOF_REVIEW,
    _FAULT_VERDICT,
    _REPORT_GAP_MARKERS,
    _SELF_DECLARED_MARKERS,
    _STYLE_MARKERS,
)

from .v_paths import (  # noqa: F401 — 再导出：台账路径 + 证明号/哈希/判词解析
    _now_iso,
    _producer_cells,
    _read_proof_no,
    _sign_sha,
    as_proof_no,
    VerificationError,
    kind_upgrade_witness,
    parse_verdict,
    producer_reading,
    proof_label,
    proof_list,
    proof_no_of,
    proof_no_strict,
    proof_text_of,
    text_sha,
    verification_ledger_path,
    verifications_dir,
)

from .v_pending_write import (  # noqa: F401 — 再导出：pending 写口（两层锁 + 跨文件发号）
    _PENDING_LOCKS,
    _PENDING_LOCKS_GUARD,
    _next_pending_verification_id,
    _pending_lock_for,
    pending_write_lock,
    record_pending_sign,
)

from .v_pending_read import (  # noqa: F401 — 再导出：pending 读侧（哪一行算那一签）
    _claimed_pending_rows,
    _issued_anchor_of_pending,
    _pending_claim_of,
    _pending_claim_streak,
    _pending_ledgers,
    _pending_sign_row,
    _pending_signed,
    _pending_stack_of_row,
    _pending_standing_rows,
    pending_dir,
    pending_ledger_path,
    pending_rows,
    pending_sign,
    pending_stacks,
)

from .v_prompt import (  # noqa: F401 — 再导出：冷启动提示词（只有对象，没有句柄）
    _cold_start_proof_strength,
    _cold_start_review_checklist,
    _cold_start_submission_gate,
    citations_block,
    cold_start_prompt,
)

from .v_ledger_write import (  # noqa: F401 — 再导出：台账写口（追加 + 可撤回）
    _append_verification,
    _mark_landed,
    _note_conjecture_refutation,
    _retrack_sign_block,
    _rollback_append,
    _verification_line,
    next_verification_id,
    record_verification,
)

from .v_rowread import (  # noqa: F401 — 再导出：行轴与签资格（轴只由秘书给）
    _already_signed_locator,
    _is_legacy_row,
    _ledger_mirror_rows,
    _ledger_table_state,
    _statement_id_of,
    _streak_number,
    axis_reading,
    bit3_already_signed,
    bit3_payload,
    historical_axis,
    ledger_axis,
    ledger_reading,
    list_verifications,
    read_verdict,
    row_signable,
    secretary_axis,
    secretary_judge_cell,
    secretary_judged,
    secretary_unjudged,
    signing_gate_problem,
    signs_bit3,
    streak_ok,
)

from .v_defect import (  # noqa: F401 — 再导出：缺陷分类与投票（纯读）
    _fault_kind_text,
    _findings_of,
    _has_math_evidence,
    _looks_like_report_gap,
    _looks_like_self_declared,
    _looks_like_style,
    _mechanical_gate_of,
    banned_markers_in,
    fault_kind_of,
    is_a_vote,
    report_fix_list,
    says_only_a_report_gap,
    vote_reading,
)

from .v_streak import (  # noqa: F401 — 再导出：连续票与打回（同一份正文才算数）
    _hold_run_lengths,
    _hold_runs,
    _rows_of_proof,
    consecutive_holds,
    signed_rows,
    void_after_rejection,
)

from .v_sign import (  # noqa: F401 — 再导出：签落位（台账与 statements 同一次写）
    _framework_holds,
    land_sign_without_ledger,
    sign_statement,
)

from .v_sign_flip import (  # noqa: F401 — 再导出：签落位（翻位/降级/义务）
    _exhaustion_proof_channel,
    _grade_recomputed_from_signature,
    _kind_upgrade_from_signature,
    _registration_after_sign,
    _registration_after_vsign,
    _reviewed_statement_row,
    _vsign_payload,
    _vsigns_write_after_flip,
    registration_after_unregistered_sign,
)

from .v_standing import (  # noqa: F401 — 再导出：第 3 位读数（签的是哪一份）
    _highest_grade,
    _statement_reading_why,
    _superseded_reading,
    review_standing,
    statement_grade,
    statement_review_reading,
)

from .v_gap_read import (  # noqa: F401 — 再导出：凭据缺口读数（pending/短回路）
    _bit3_blockers,
    _gap_from_pending,
    _issued_verification_pointer,
    issued_sign_short_circuit,
    proof_review_gap,
    proof_review_gaps,
    weaker_than_evidence_gaps,
)

from .v_grades import (  # noqa: F401 — 再导出：等级反算（apply 才写盘）
    _apply_grade_backfill,
    recompute_grades,
)

from .v_unverified import (  # noqa: F401 — 再导出：未审命题（在册 / pending 两路）
    _claimed_pending_by_statement,
    unverified_statement_refs,
)

from .v_evidence import (  # noqa: F401 — 再导出：证据同一性（同一份读数只算一份）
    _freeze,
    evidence_identity,
    one_evidence_used_twice,
    opposite_direction_evidence,
)

from .v_selftest import (  # noqa: F401 — 再导出：自检
    selftest,
)

from .v_citation import (  # noqa: F401 — 再导出：引用核实（签字前置，纯函数）
    _citation_checks_raw,
    admissible_evidence_kinds,
    apply_citation_gate,
    citation_blocks,
    citation_gate,
    citation_grade_admissible,
    evidence_kind_admissible,
    reconcile_citation_checks,
)


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())
