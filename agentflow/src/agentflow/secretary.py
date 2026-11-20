# -*- coding: utf-8 -*-
"""「秘书」：每个智能体自带的随员。
它不是一个同级角色：不占 `schema.ROLES`、不加注册工具、不改权限面声明、不改 `llmseam` 的
enum、不重冻快照 ⇒ 一个计数都不变。同一个类，每角色一份配置（自己的定位 + 收发箱）。
## 四条职责
| # | 职责 | 谁的秘书做 | 本模块的落点 |
|---|---|---|---|
| 1 | 格式与内容优化 | 发件方 | :meth:`Secretary.optimize_outbound`（对齐参数表/必填/工具真名；不替本体承诺） |
| 2 | 委派评估 | 发件方 | :meth:`Secretary.assess_delegation`（收件方真做得到吗 + 该不该派） |
| 4 | 委托加工 | 收件方 | :meth:`Secretary.rework_inbound`（按本角色定位改说法，不加码不减码） |
| 3 | 闭环提醒 | 收件方 | :meth:`Secretary.remind_closure`（未接手 / 未反馈；经 M） |
职责 1 另有一件同样是"看"的事（「秘书处理将发出的信息时，要看内容是否
与接受面相符」）：:meth:`Secretary.judge_recipient_face` —— 公告栏里点名并下指令、或一份稿子里
装了多件派活 ⇒ 这一条退回本体，一个字节都不写盘（判据机械可判、零模型调用）。
两条实质性红线：格式补不全、或加工后发现实质缺陷 ⇒ 与对方协商、不静默修
（:meth:`Secretary.negotiate` ≤2 轮 + 台账留痕）—— 它从不替本体表态。手稿通道的增/改/查也在
这里：`handoff_add` / `handoff_revise` / `handoff_query`，智能体侧只留"查"。
## 权限与失败姿态
库表只读（写集 ∅）；文件两处写：手稿通道 + 自己的台账 `out/secretary/<role>.jsonl`；不使用注册
工具；信息面 ≤ 本体，且 V 的秘书不读 F 的叙述（I12 的独立性不许被绕过）。fail-open：超时/出错
⇒ 原样放行 + 留痕，唯一例外是手稿执笔失败必须报错留痕。它是判断者不是仪表盘：不做任何统计
（那套统计是坏设计），成本靠 :meth:`Secretary.should_engage` 的机器预筛控制
（只在预筛报警 / 重复候选 / 闭环逾期 / 首次遇见该形态时才叫秘书；默认路径确定性）。
"""
from __future__ import annotations

import datetime as _dt
import functools
import hashlib
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import manuscripts as MS
from . import clock
from . import proofloc as _PL
from . import propositionkey as _PK
from . import refusals as R
from . import schema as S
from . import statementbody as _SB
from . import statementledger as SL
from . import proofregistry as _PR
# 再导出（依赖方向单向：本文件 -> secretary_port.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_port import (  # noqa: F401 — 再导出，保持公开面不变
    bind_factory, new_secretary,
)


# 再导出（依赖方向单向：本文件 -> secretary_time.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_time import (  # noqa: F401 — 再导出，保持公开面不变
    _as_mapping, _now_iso, _older_than,
)


# 再导出（依赖方向单向：本文件 -> secretary_ledger.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_ledger import (  # noqa: F401 — 再导出，保持公开面不变
    DISPATCH_FIT_LEDGER, NONTRIVIALITY_LEDGER, PROPOSITION_FORM_LEDGER,
    PROPOSITION_VERDICT_LEDGER, RELAY_ID_PREFIX, RELAY_LEDGER, ROSTER_DIR, SECRETARY_DIR,
    STATEMENT_SAME_LEDGER, SURFACES_DIR, _APPEND_LOCKS, _APPEND_LOCKS_GUARD, _ROSTER_DEPTH,
    _ROSTER_LOCKS, _ROSTER_LOCKS_GUARD, _ROSTER_PENDING, _ROSTER_SIDECAR_SUFFIXES, _append_lock,
    _append_locked, _roster_guarded, _roster_pending_key, _roster_section, append_jsonl,
    append_jsonl_stamped, archive_dir, decisions_path, dispatch_fit_path, forget_roster_pending,
    nontriviality_path, note_roster_pending, proposition_form_path, proposition_verdicts_path,
    refusals_path, relay_path, retired_path, roster_index_path, roster_path, roster_pending,
    statement_same_path, surface_dir, surfaces_path,
)


# 再导出（依赖方向单向：本文件 -> secretary_axes.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_axes import (  # noqa: F401 — 再导出，保持公开面不变
    _proposition_verdict_key, append_dispatch_fit, append_proposition_form,
    append_proposition_verdict, append_statement_same, dispatch_fit_rows, proposition_form_of,
    proposition_form_rows, proposition_verdict_of, proposition_verdict_rows,
    statement_same_rows,
)


# 再导出（依赖方向单向：本文件 -> secretary_vocab.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_vocab import (  # noqa: F401 — 再导出，保持公开面不变
    ACCEPT_PROPOSAL, BRIEF_MAX, CLUE_NOTE, CLUE_VERB, CONCEPT_IDENTITY_KINDS,
    CONCEPT_IDENTITY_UNJUDGED, DECISIONS, DECISION_ACCEPTED, DECISION_PROPOSED,
    DECISION_READDRESS, DECISION_REARRANGE, DECISION_REJECTED, DEFAULT_DEADLINE_SEC,
    DEPS_MISSING_ABSENT, DEPS_MISSING_NOT_APPLICABLE, DEPS_MISSING_PRESENT, DEPS_MISSING_STATES,
    DISPATCH_FIT_OK, DISPATCH_FIT_QUESTION, DISPATCH_FIT_UNSUITABLE, DISPATCH_FIT_VERDICTS,
    DISPATCH_VERB, JUDGE_UNCHECKED, JUDGE_VERDICTS, KIND_DECISION, KIND_HANDOFF,
    KIND_NEGOTIATION, KIND_NOTICE, KIND_OPTIMIZED, KIND_PROPOSAL, LABEL_FROM_STATEMENT_CHARS,
    LABEL_WASH_ROUTE, LABEL_WASH_WORKING, LABEL_WORKING_NAME_RULES, LIVE_TASK_STATUSES,
    MAX_NEGOTIATION_ROUNDS, MAX_REMINDERS, NONTRIVIALITY_LEVELS, OUTCOME_WASH_PROPOSED,
    PROOF_KIND_VERDICTS, PROPOSAL_KEYS, PROPOSITION_FORM_REFUSED, PROPOSITION_VERDICTS,
    RAN_STATUSES, REJECT_PROPOSAL, ROW_AXIS_AGENT, ROW_AXIS_ITEM_CLOSED, ROW_AXIS_ITEM_OPEN,
    ROW_AXIS_OTHER, ROW_AXIS_ROOT, SAME_AS_WRAPPER_CHARS, SIGN_ISSUE, SIGN_WITHHOLD,
    STATEMENT_VERDICTS, STATE_LABELS, TASK_TEXT_MAX, TOP_LEVEL_ACTION, V_REPLY_AXIS,
    V_REPLY_CLEAN, V_REPLY_FAULT, V_REPLY_VERDICTS, _JUDGE_UNDECIDED, _NONTRIVIALITY_LABELS,
    _SENTENCE_END, _nontriviality_level, nontriviality_label,
)


# 再导出（依赖方向单向：本文件 -> secretary_decl.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_decl import (  # noqa: F401 — 再导出，保持公开面不变
    EMPTY_STATEMENT_TEXT, NONTRIVIALITY_SCALE, NONTRIVIALITY_UNJUDGED, NOT_APPLICABLE_KINDS,
    PROOF_ROUTES_KEY, PROPOSITION_KINDS, STATEMENT_BITS_KEYS, STATEMENT_WRITE_TABLES,
    _is_concept_kind,
)


# 再导出（依赖方向单向：本文件 -> secretary_prompts.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_prompts import (  # noqa: F401 — 再导出，保持公开面不变
    JUDGE_MATERIAL_CAP, _abandon_difficulty_system, _judge_material, _judge_prompt,
    _judge_system, _proposition_form_system, _statement_keywords_system, _wash_v_system,
)

# 再导出（依赖方向单向：本文件 -> secretary_judge.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_judge import (  # noqa: F401 — 再导出，保持公开面不变
    JudgeMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_judge.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_judge import (  # noqa: F401 — 再导出，保持公开面不变
    declarations_candidates,
)

# 再导出（依赖方向单向：本文件 -> secretary_tier_ledger.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_tier_ledger import (  # noqa: F401 — 再导出，保持公开面不变
    TierLedgerMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_tier_ledger.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_tier_ledger import (  # noqa: F401 — 再导出，保持公开面不变
    _NT_INDEX_CACHE, _fold_nontriviality, _judged_body_sha, _level_from_row,
    _nontriviality_index, _row_matches_stmt_id, _row_path_group, _statement_sha,
    _tier_from_judge_reply, _tier_from_legacy_decision, append_nontriviality, nontriviality_of,
    nontriviality_rows,
)

# 再导出（依赖方向单向：本文件 -> secretary_tier_judge.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_tier_judge import (  # noqa: F401 — 再导出，保持公开面不变
    TierJudgeMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_tier_judge.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_tier_judge import (  # noqa: F401 — 再导出，保持公开面不变
    EFFORT_TOOL_CLUSTERS, NONTRIVIALITY_NOT_APPLICABLE_BASIS, PROOF_BODY_CAP,
    _EFFORT_DETOUR_WORDS, _EFFORT_LEMMA_RE, _EFFORT_PROOF_MARKERS, _EFFORT_STEP_PATTERNS,
    _EFFORT_THEOREM_RE, _EFFORT_UPGRADE_STEPS, _is_not_applicable_kind, _is_trivial_verdict,
    _looks_like_a_proof, filing_tier_note, filing_tier_reading, material_truncation,
    proof_effort_readings,
)

# 再导出（依赖方向单向：本文件 -> secretary_tier_record.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_tier_record import (  # noqa: F401 — 再导出，保持公开面不变
    TierRecordMixin,
)

# 再导出（依赖方向单向：本文件 -> secretary_sign.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_sign import (  # noqa: F401 — 再导出，保持公开面不变
    SignMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_sign.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_sign import (  # noqa: F401 — 再导出，保持公开面不变
    v_reply_fault_reading,
)

# 再导出（依赖方向单向：本文件 -> secretary_axis.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_axis import (  # noqa: F401 — 再导出，保持公开面不变
    AxisMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_axis.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_axis import (  # noqa: F401 — 再导出，保持公开面不变
    _diagnose_line, _state_reading, _status_enum, is_live_agent, ran_but_unnamed, row_axis,
)

# 再导出（依赖方向单向：本文件 -> secretary_roster_read.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_roster_read import (  # noqa: F401 — 再导出，保持公开面不变
    RosterReadMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_roster_read.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_roster_read import (  # noqa: F401 — 再导出，保持公开面不变
    _fold_index, _fold_roster, registration_refusals, retired_row_gaps, roster_owners,
)

# 再导出（依赖方向单向：本文件 -> secretary_addressing.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_addressing import (  # noqa: F401 — 再导出，保持公开面不变
    AddressingMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_addressing.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_addressing import (  # noqa: F401 — 再导出，保持公开面不变
    _clip_text,
)

# 再导出（依赖方向单向：本文件 -> secretary_retire.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_retire import (  # noqa: F401 — 再导出，保持公开面不变
    RetireMixin,
)

# 再导出（依赖方向单向：本文件 -> secretary_inbox.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_inbox import (  # noqa: F401 — 再导出，保持公开面不变
    InboxMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_inbox.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_inbox import (  # noqa: F401 — 再导出，保持公开面不变
    _task_text, brief_from_task,
)

# 再导出（依赖方向单向：本文件 -> secretary_roster_write.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_roster_write import (  # noqa: F401 — 再导出，保持公开面不变
    RosterWriteMixin,
)

# 再导出（依赖方向单向：本文件 -> secretary_session.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_session import (  # noqa: F401 — 再导出，保持公开面不变
    SessionMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_session.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_session import (  # noqa: F401 — 再导出，保持公开面不变
    _pid_alive,
)

# 再导出（依赖方向单向：本文件 -> secretary_wash.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_wash import (  # noqa: F401 — 再导出，保持公开面不变
    WashMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_wash.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_wash import (  # noqa: F401 — 再导出，保持公开面不变
    STATEMENT_KEY_ALIASES, STATEMENT_PARAM_KEYS, STEP_KEY_ALIASES, STEP_SOURCE_KEYS, _dep_label,
    _dep_ref, _dep_step_key, _statement_key_candidate, _stmt_edge_count, _wash_dep_groups,
    normalize_same_as,
)

# 再导出（依赖方向单向：本文件 -> secretary_label.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_label import (  # noqa: F401 — 再导出，保持公开面不变
    LabelMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_label.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_label import (  # noqa: F401 — 再导出，保持公开面不变
    _brackets_balanced, _clip_label, _first_readable_claim, _readable_label,
    _strip_working_names, _tidy_label, wash_working_name,
)

# 再导出（依赖方向单向：本文件 -> secretary_identity.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_identity import (  # noqa: F401 — 再导出，保持公开面不变
    IdentityMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_identity.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_identity import (  # noqa: F401 — 再导出，保持公开面不变
    PROPOSITION_VERDICT_CANDIDATES, PROPOSITION_VERDICT_TEXT_CHARS, _is_proposition_kind,
    _proposition_judgment_missing,
)

# 再导出（依赖方向单向：本文件 -> secretary_proofkind.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_proofkind import (  # noqa: F401 — 再导出，保持公开面不变
    ProofkindMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_proofkind.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_proofkind import (  # noqa: F401 — 再导出，保持公开面不变
    PROOF_KIND_UNJUDGED, PROOF_SAME_JACCARD, PROOF_SAME_KIND,
)

# 再导出（依赖方向单向：本文件 -> secretary_evidence.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_evidence import (  # noqa: F401 — 再导出，保持公开面不变
    EvidenceMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_evidence.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_evidence import (  # noqa: F401 — 再导出，保持公开面不变
    PROOF_TEXT_NEEDS_MANUSCRIPT_SIGN, _bits_bear_evidence, _complete_statement_bits,
    _manuscript_upgrade_basis, _semantic_quote_evidence_refusal, _signed_exhaustion_terminal,
    proof_text_manuscript_sign_gate,
)

# 再导出（依赖方向单向：本文件 -> secretary_statement.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_statement import (  # noqa: F401 — 再导出，保持公开面不变
    StatementMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_statement.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_statement import (  # noqa: F401 — 再导出，保持公开面不变
    STATEMENT_ABANDON_PATCH_KEYS, STATEMENT_LAND_OPS, STATEMENT_META_KINDS,
    STATEMENT_META_PATCH_KEYS, STATEMENT_RETIRE_PATCH_KEYS, STATEMENT_WRITER_ROLES,
)

# 再导出（依赖方向单向：本文件 -> secretary_deps.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_deps import (  # noqa: F401 — 再导出，保持公开面不变
    DepsMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_deps.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_deps import (  # noqa: F401 — 再导出，保持公开面不变
    _assign_path_group_in_tx, _deps_missing_reading, _existing_path_group_in_tx,
    _note_path_material, _path_material_numbers, _resolve_dep_steps, _stamp_path_number,
)

# 再导出（依赖方向单向：本文件 -> secretary_concept.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_concept import (  # noqa: F401 — 再导出，保持公开面不变
    ConceptMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_concept.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_concept import (  # noqa: F401 — 再导出，保持公开面不变
    concept_identity_action, concept_identity_gate,
)

# 再导出（依赖方向单向：本文件 -> secretary_merge.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_merge import (  # noqa: F401 — 再导出，保持公开面不变
    MergeMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_merge.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_merge import (  # noqa: F401 — 再导出，保持公开面不变
    MERGED_BY_ADJUDICATION, SAME_PROPOSITION_JACCARD, proof_route_of, proof_routes_of,
)

# 再导出（依赖方向单向：本文件 -> secretary_statement_tx.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_statement_tx import (  # noqa: F401 — 再导出，保持公开面不变
    StatementTxMixin,
)

# 再导出（依赖方向单向：本文件 -> secretary_statement_meta.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_statement_meta import (  # noqa: F401 — 再导出，保持公开面不变
    StatementMetaMixin,
)

# 再导出（依赖方向单向：本文件 -> secretary_vacant.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_vacant import (  # noqa: F401 — 再导出，保持公开面不变
    VacantMixin,
)

# 再导出（依赖方向单向：本文件 -> secretary_identity_side.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_identity_side import (  # noqa: F401 — 再导出，保持公开面不变
    IdentitySideMixin,
)

# 再导出（依赖方向单向：本文件 -> secretary_outbound.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_outbound import (  # noqa: F401 — 再导出，保持公开面不变
    OutboundMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_outbound.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_outbound import (  # noqa: F401 — 再导出，保持公开面不变
    _TARGET_OPENERS, _dispatch_clue, dispatch_targets, reach_fit,
)

# 再导出（依赖方向单向：本文件 -> secretary_handoff.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_handoff import (  # noqa: F401 — 再导出，保持公开面不变
    HandoffMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_handoff.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_handoff import (  # noqa: F401 — 再导出，保持公开面不变
    _MANUSCRIPT_HEAD_FIELD_RE, _manuscript_head_fields,
)

# 再导出（依赖方向单向：本文件 -> secretary_relay.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_relay import (  # noqa: F401 — 再导出，保持公开面不变
    RelayMixin,
)

# 再导出（依赖方向单向：本文件 -> secretary_surface.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_surface import (  # noqa: F401 — 再导出，保持公开面不变
    SurfaceMixin,
)


# 再导出（依赖方向单向：本文件 -> secretary_surface.py）；`from .secretary import ...` 的调用点一个字不改。
from .secretary_surface import (  # noqa: F401 — 再导出，保持公开面不变
    SURFACE_PATH_ARGS, _fold_surfaces, surface_path_args,
)


# ---------------------------------------------------------------- 名册与对照表（S1k）
#
# 落点：`out/roster/<owner>.jsonl`（名册）、`<owner>-index.jsonl`（电话簿）、`<owner>-retired.jsonl`（销号名单）、`refusals/<owner>.jsonl`（拒绝流水，子目录）。四份都 append-only，读侧折叠。
# 为什么不放 `out/secretary/`：`webui/readers.py` 是目录 glob（`*.jsonl`），
# 同目录会把名册行混进"秘书决定台账"那一面。


# ---------------------------------------------------------------- 读写面与槽位池（S1n）
#
# 业主 T23：子代理只能读写父切割给它的面；父原则上必须把各子代理的面拆开（不重叠）；
# 面内的新文件允许。退役之后面归还"可分配池"（名字不回收，面回收）。
# 落点：`out/surfaces/<owner>/<slot>/`（面本体）、`out/roster/<owner>-surfaces.jsonl`（池事件）、
# `out/surfaces/archive/<owner>-<name>/`（归还前的归档）。


# ---------------------------------------------------------------- 发出口：内容与收件面相符吗
#
# 业主原话（2026-10-26，逐字）：「秘书处理将发出的信息时，要看内容是否与接受面相符，这条显然
# 该拆两条单独派活，这是秘书没有意识，未向 M 提醒」。
#
# 现场（`projects/mp3-r3` 的真机手稿 000000）：一条 `handoff(to=ALL)` 的正文里装着两件派活
# （给 A、给 D），秘书照发 —— 而同一段内容若走 `message` 会被 `public_is_not_a_conversation`
# 拒（公告栏里点名 + 指令语气），`handoff` 这条路不过那道判据 ⇒ 换个通道就绕过去了。
#
# 这里加的不是一套新码、也不是一条新通道：判断落在秘书本来就有的发出口
# （:meth:`Secretary.optimize_outbound` + :meth:`Secretary.note_decision` 那一条
# `secretary_decision` 台账），用的也是既有码（`invalid_params` 与
# `public_is_not_a_conversation`）；名册与公告那两条判据本体由调用方注入
# （与 `admission=message_admission` 同一种做法，本文件不抄第二份）。


class Secretary(JudgeMixin, TierLedgerMixin, TierJudgeMixin, TierRecordMixin, SignMixin, AxisMixin, RosterReadMixin, AddressingMixin, RetireMixin, InboxMixin, RosterWriteMixin, SessionMixin, WashMixin, LabelMixin, IdentityMixin, ProofkindMixin, EvidenceMixin, StatementMixin, DepsMixin, ConceptMixin, MergeMixin, StatementTxMixin, StatementMetaMixin, VacantMixin, IdentitySideMixin, OutboundMixin, HandoffMixin, RelayMixin, SurfaceMixin):
    """一名智能体的秘书（`draft/53` v3 §4：一个共享类 + 每角色一个实例）。

    参数
    ----
    role : 它服务的那名智能体（`"M"` / `"A"`…/`"V"`）。台账按它分文件。
    root : 工作区根（手稿通道与台账都挂在它下面）。
    store : 可选的 `Store`（只读：`tasks` / 会话事件）。给了就读，不给就跳过那一层读数。
    registry : 可选的工具注册表（只读：判"工具名是不是真名"）。
    seam : 可选的 `LlmSeam`（用本智能体自己的缝，`scope="secretary"`）；不给 ⇒ 判断那一格判不了
        （`judge()` 返回 `checked=False`），预筛与留痕照常。生产装配把它打开是一行的事
        （`Secretary(..., seam=<本体的缝>, enable_model=True)`）。
    enable_model : 要不要用模型做"判断"（见 :meth:`judge`）。默认 False：确定性预筛是机器该做的，而
        "要不要为此花钱"是一次明确的取舍（`P-09` 的粒度）；生产装配把它打开是一行的事。
    log : 可选日志口子（失败留痕的第二个落点）。
    写集只有两格（业主 2026-10-09：「写入侧应该都是B的活，让B的秘书帮它洗格式、拿编号、改表、查重…B 纯粹
    负责消化理解」）：`statements` 与 `dependencies` —— 都只经 :meth:`record_statement` 一处（B 交内容、秘书
    落盘）；它不写别的库表、不改任何受保护文件。两类产物分得很清（这是本项目最忌的那种折平）：
    | 类 | 判据 | 形态 | 例子 |
    |---|---|---|---|
    | 预筛 | 确定性、来自既有声明 | 报警清单（字符串） | 参数缺必填 / 工具名不是真名 / 动作不在能力表 |
    | 判断 | 需要语义、"该不该" | :meth:`judge` 一次模型调用 + 台账 | 重复候选算不算正当重试 / 错名映到哪个 / 建议重排成什么 |
    """

    #: 装配口（业主口径②）：从混入模块来的那一侧要造"下一跳秘书"时只经这一处。
    #:
    #: 为什么是一个类属性而不是混入模块里的 `from .secretary import Secretary`：那一条
    #: 是混入层反向 import 组装层，而组装层为了再导出又必须 import 混入模块 —— 两个方向
    #: 同时成立就是 ImportError。类属性把"造哪一门子"的答案挂在类上，混入类只写
    #: `self._new_secretary(...)`；真身在 `secretary_port.py`（它谁都不 import）。
    #: 判据 `tests/test_secretary_has_one_assembly_port.py` 钉住"只经这一处"。
    _new_secretary = staticmethod(new_secretary)

    def __init__(self, role: str, *, root: str | Path, store: Any = None,
                 registry: Any = None, seam: Any = None, log: Any = None,
                 deadline_sec: float = DEFAULT_DEADLINE_SEC,
                 enable_model: bool = False, sid: str | None = None,
                 model_source: str = "",
                 same_proposition_jaccard: float = SAME_PROPOSITION_JACCARD,
                 proof_same_jaccard: float = PROOF_SAME_JACCARD) -> None:
        self.role = str(role)
        self.root = Path(str(root))
        self.store = store
        self.registry = registry
        self.seam = seam
        # ---- 装配期类型闸（`AGENTFLOW_STRICT_SEAM=1` 时生效；默认关）
        #
        # 为什么在这里也接一道：`Secretary(..., seam=_Seam())` 是彩排最常见的一种
        # 「构造期直接替换」——静态扫描看不见，三格也没有对象。判据本体只有一处
        # （`llmseam.assert_real_seam`），这里只报出「是谁收到的」。
        from .llmseam import assert_real_seam

        assert_real_seam(seam, where="Secretary.__init__(seam=...)")
        self.log = log
        self.deadline_sec = float(deadline_sec)
        #: 同一命题 / 同种证明的两个阈值。可注入的理由：这两条判据的
        #: 松紧是口径问题，不是实现问题 —— 不同工作区的表述习惯不同（带
        #: 长尾注的登记与短句式的登记），阈值该能被一次实验性调参改掉，而不必改代码。
        self.same_proposition_jaccard = float(same_proposition_jaccard)
        self.proof_same_jaccard = float(proof_same_jaccard)
        #: 会话号（花销归因要读 `llm_call` 事件；`None` = 缺省会话，与 `llmseam` 同一口径）。
        self.sid = sid
        #: 判断类要不要真发一次模型调用。
        #: 关着的时候 :meth:`judge` 仍然返回三态中的"没查成"（`checked=False` + 理由），
        #: 于是"判断没做"与"判断过了、可派"在台账上永远分得开。
        #:
        #: 生产装配由 `agent_loop._secretary_for` 打开它。
        #: 那一口还会按配置换一把 key：设置文件里配了
        #: `secretary` 档 ⇒ 秘书走全角色共用的那一档模型
        #: （`llmseam.LlmSeam.for_secretary`）；没配 ⇒ 退回本体那一个缝。
        self.enable_model = bool(enable_model)
        #: 秘书这一趟的模型是从哪一档来的（读数：`secretary（…）` / `body（…）`）。
        #: 它回答"这次判断花的是共用那把 key，还是本体那把" —— 而这正是
        #: 「所有智能体的秘书另外共用一个 api key」是否生效的唯一机器读数。
        #:
        #: 构造参数，不是构造之后补写的字段：装配层本来就先算出缝与来源
        #: （`for_role_wired` / `agent_loop._secretary_for`），再构造秘书。此前它先造
        #: 对象、再补 `sec.model_source = source`，于是"补之前"的任何一次 `judge()`
        #: 读到的都是空串 —— 读数里少了「为什么没有判断面」那一句。现在它和 `seam=`
        #: 同生：没有来源就没有这条缝，两者在构造期一起定下。
        self.model_source: str = str(model_source or "")
        #: 写集的声明式落点：它让"秘书有没有写集、写哪几张表"成为一个可读的事实，
        #: 而不是"读遍本文件找不到 store.tx 所以大概没有"。
        #: 不是空集：B 的写入代理要落 `statements`（含概念行）与 `dependencies`，
        #: 只走 :meth:`record_statement` 一处。
        self.writes: frozenset[str] = frozenset(STATEMENT_WRITE_TABLES)
        self._negotiations: list[dict[str, Any]] = []
        #: 这个秘书服务的实例（台账号）。由 `bind_task` 在循环开跑时绑上：
        #: 绑上之后台账分片到 `out/secretary/<role>-<task_id>.jsonl`，于是同角色的并发实例
        #: 各写各的片（今天只有角色维度 ⇒ 两个 D 实例会把记录写进同一个文件，读的人分不出是谁）。
        #: 存储格是 `_task_id`（不是公开字段）：读走只读属性 :attr:`task_id`，
        #: 写只有 :meth:`bind_task` 一处 —— 理由见该属性的 docstring。
        self._task_id: str = ""
        #: 最近一次判断的墙钟（秒）—— 读数，不是判据（fail-open 的代价要看得见，
        #: 但不许拿它去卡任何一条委托）。
        #:
        self._last_judge_elapsed = 0.0
        #: 入库审美的同题不重判表。
        #:
        #: 判断的对象只有那段文本（加一句自证不平凡的说明），所以同一份文本问第二遍不会
        #: 有别的结论 —— 记下来，省掉那几次模型调用，也让"再交一遍"这件事在读数上立刻
        #: 变便宜且答案不变（于是没有理由反复试）。
        #:
        #: 键 = `(statement_full, why_this_is_not_trivial)` 的摘要；值 = 第一次的结论。
        #: 只记 `checked=True` 的结论：没查成（没缝 / 超时 / 坏 JSON）不许缓存 ——
        #: 那会把"这一次没查成"变成"以后都别查了"，而缝是可能好起来的。
        self._statement_verdicts: dict[str, dict[str, Any]] = {}
        #: 命题同一性的同题不重判表。
        #:
        #: 键 = 命题正文的 sha256（见 `_proposition_verdict_key`）；值 = 第一次的判定。
        #: 这一层只是进程内的快表：盘上那份 append-only 台账
        #: （`out/secretary/proposition_verdicts.jsonl`，见 `proposition_verdict_of`）才是
        #: 跨进程/跨趟的缓存 —— 没有盘上那一份，"同一条正文第二次进来不再花钱"这句话只在
        #: 同一个秘书实例活着的时候成立。
        self._proposition_verdicts: dict[str, dict[str, Any]] = {}
        #: 工具面真名表的缓存。`registry=None` 那一档的兜底是
        #: `build_registry(store=...)` —— 装配一整套工具要十几毫秒，而 `prescreen`
        #: 每次委派都问一遍。
        #: 工具面是静态的（`tools/_MODULES` 那张表在进程内不变），所以这份名单
        #: 只缓存"读成功了"的那一次；空表（读不成）不缓存 —— 那会把"这一次没读成"
        #: 变成"以后都没有真名"，而三态纪律不许这么折。
        self._tool_names_cache: list[str] | None = None

    @property
    def task_id(self) -> str:
        """这一名秘书绑到的实例号（只读；全仓唯一写点是 :meth:`bind_task`）。

        为什么做成只读属性：2026-11-20 的取证（`05-VERDICT.md` §顺带上报）里有两处
        `xxx.task_id = ...` 绕过 `bind_task`。其中 `conductor.guide` 那一支连存活标记
        都没落，于是 `secretary_alive()` 把"绑过、只是没标记"读成"没绑过实例"；
        `_peer_secretary` 那一支代表的是另一个号（转发链下一跳），它本来就不该
        写标记。一个可直写的字段让"绑上"与"落标记"在类型上分不开；只读之后，
        外部那一句是 `AttributeError`，纪律不再靠自觉。
        判据：`tests/test_secretary_task_id_has_one_write_point.py`。
        """
        return self._task_id


#: 装配口登记（见 `class Secretary._new_secretary`）：本模块是唯一知道"秘书类是谁"的地方，
#: 类定义之后立刻把入口交给 `secretary_port`；混入模块那一侧从此只认那一个函数。
bind_factory(Secretary)


# ---------------------------------------------------------------- 判档位的"力气"读数
#
# 业主 2026-10-24 的裁定（逐字）：「"后面哪一步会用到它 / 比已知那条强在哪"这俩和非平凡度
# 有啥关系？不一定一条定理后面要用，也不一定存在"已知那条"，看证明花的力气就能判非平凡度」。
# 所以判据从"会不会被用到 / 比已知强在哪"换成这份证明花的力气。四项读数各有定义、
# 各有计分权重（唯一一处定义就在下面这张表）：
#
# | 读数 | 怎么数 | 计分 |
# |---|---|---|
# | 体量 chars | 证明正文的字符数（超过 PROOF_BODY_CAP 就判不了） | 每 2000 字 1 分 |
# | 步骤 steps | 编号步骤行 / 分节标题 / 「步骤 N」「第 N 步」三者取最大 | 每 6 步 1 分 |
# | 引理 lemmas | 正文里点名的不同引理号（引理 / 推论 / Lemma / Corollary） | 每 2 条 1 分 |
# | 跨度 clusters | 命中的工具簇个数（见 EFFORT_TOOL_CLUSTERS） | 每多一簇 1 分 |
# | 绕路 detour | 正文自述绕开了熟路（"不使用 / 绕开 / 另证 / 自足"等） | 命中 +1 分 |
#
# 四档边界（分数 = 上面五项之和，整数）：
#
# | 档 | 分数 | 典型读数 |
# |---|---|---|
# | T0 | 0–1 | 正文 < 2000 字、步骤 < 6、引理 < 2、单一工具簇、不绕路 |
# | T1 | 2–3 | 只有一项读数刚过线（例如正文 2000–4000 字） |
# | T2 | 4–7 | 体量大：约 5000 字 + 6 步 + 2 条引理 + 跨一簇 |
# | T3 | 8–15 | 技巧多或跨领域：约 8000 字 + 10 条引理 + 3 簇 |
# | T4 | 16 以上 | 极长或极偏：两万字以上，且引理与工具簇都拉满 |
#
# 三态纪律不变：一项都读不到（没有证明正文）或正文被截断 ⇒ 档位是 None，且原因必须点名
# 缺的是哪一项读数 —— 不许拿 0 冒充"判不了"，也不许拿"材料不足"冒充"输入不完整"。


# ---------------------------------------------------------------- 命题同一性的旁支台账


# ---------------------------------------------------------------- 命题形态判定台账


# ---------------------------------------------------------------- 同一命题检索台账（2026-11-08）


# ---------------------------------------------------------------- 证明的路子说明


def for_role(role: str, *, root: str | Path, **kw: Any) -> Secretary:
    """造一名某角色的秘书（`draft/53` §5 的"批量给 A–H 装"：批量 = 配置 + 测试）。

    装配点只有两个：`agent_loop.run_role`（所有角色共用的驱动，经
    `agent_loop._secretary_for`）与 `conductor.Conductor`（M 的派活路径）——
    两者都不在 FC-27 名册。生产路径会传 `seam=<本角色自己的 LlmSeam>` 与
    `enable_model=True`（主控裁定 A5），于是三条判断真的发生、花销记在本体账上。

    这一支自己不去造缝（`seam=None` 就是"没有判断面"，`judge()` 会如实报
    `checked=False`）。手上没有缝的构造点该调 :func:`for_role_wired` ——
    它在造秘书之前先把缝拿来，并把"缝从哪来"写进 `Secretary.model_source`。
    """
    return Secretary(str(role), root=Path(str(root)), **kw)


def _ambient_session_sid() -> str | None:
    """这一趟的会话号（`conductor.calling_as` 挂的那一个）；不知道 ⇒ `None`。

    为什么秘书装配要读它：`for_role_wired` 的调用点里有一批拿不到 host 的 `sid=`
    （`AgentV._secretary`、`AgentB._statement_secretary`、若干工具的秘书）。改前它们
    一律传 `sid=None` ⇒ 秘书档的 `llm_call` 事件落进缺省会话
    （`sessions/<当天日期>.jsonl`）：账本按 ambient task 归口，看不出少了一趟；
    但"这一笔不在本趟的审计面上"是事实（RC2 彩排实测 7 条里 4 条是这么来的）。

    为什么不把"空串"当 `sid` 传下去：`sid=""` 与 `sid=None` 在 `sessions.append`
    里同义（都落缺省会话），但调用方要能分开"这一层不知道"与"就用缺省会话"。
    所以这里只在取到会话号时替换 `None`；取不到就保持 `None`，与从前逐字同义。
    """
    try:
        from .llmseam import ambient_sid
        return ambient_sid() or None
    except Exception:  # noqa: BLE001 —— 取不到就是不知道，保持旧行为（sid=None）
        return None


def seam_for_secretary(role: str, *, root: str | Path, seam: Any = None,
                       sid: str | None = None, store: Any = None,
                       meter: Any = None) -> tuple[Any, str]:
    """秘书判断面那一条缝：`(缝 或 None, 读数)` —— 拿不到时读数就说清为什么。

    ## 为什么需要这一处

    不传 `seam=` 的 `Secretary(...)` 会让整条命题同一性判定变成死路：
    `record_statement` 调 :meth:`adjudicate_proposition`，后者调 :meth:`judge`，
    而 `judge` 的第二道闸是"没有缝 ⇒ `checked=False`"。全仓的构造点分散在
    `tools/table_tools.py` / `conductor.py` / `closing.py` / `tools/conductor_tools.py`
    等处，逐个记得传缝不现实 ⇒ 收在 `LlmSeam.for_secretary` 一处现造，
    并把"造没造出来"如实写进读数（没 key / 开关关着 / 装配器不给 ⇒ 各自的 reason）。

    ## 账本：有账本就必须接上

    `meter` 显式给了就用；没给而有 `store` ⇒ 现造 `TokenMeter(store)`；两样都没有
    （单测里的裸缝、没有工作区可落账）⇒ `meter=None`，那一档的 `no_meter` 是
    "没有账本可写"，不是漏接线 —— 漏接线的形态是"有工作区却没记账"，
    那会让一笔真实花销既不在已归口、也不在 `unattributed`，是没有下落。

    接上之后每笔都进账：在召唤上下文里 ⇒ 记到那次召唤的 `task_id`（并回写 `tasks.usd`）；
    不在任何召唤里 ⇒ `task_id=None` + `note` 写明 `unattributed`，由 `reconcile_usage`
    单列一栏点名。三态纪律：发了请求的钱只有"已归口"与"点名说清为什么归不了"两种。
    """
    if sid is None:
        sid = _ambient_session_sid()
    if seam is not None:
        return seam, "body（调用方给的缝）"
    try:
        from .llmseam import LlmSeam
    except Exception as exc:  # noqa: BLE001 —— 拿不到缝的工厂 ⇒ 读数写清，不猜
        return None, f"none（拿不到 llmseam：{type(exc).__name__}: {exc}）"
    # 账本接不接得上与缝要不要造是两件事：接不上不许把判断面关掉（fail-open），
    # 但要把"这一次的 no_meter 是账本没接上"写进读数。
    meter_problem = ""
    if meter is None and store is not None:
        try:
            from . import tokenmeter as _TM
            meter = _TM.TokenMeter(store)
        except Exception as exc:  # noqa: BLE001
            meter_problem = (f"meter 没接上（{type(exc).__name__}: {exc}）"
                             "⇒ 本条缝的调用会落 no_meter")
    try:
        got = LlmSeam.for_secretary(owner_role=str(role), session_root=Path(str(root)),
                                    sid=sid, meter=meter)
    except Exception as exc:  # noqa: BLE001 —— 造缝失败是"没接线"，不是"没有结论"
        return None, f"none（造缝失败：{type(exc).__name__}: {exc}）"
    if got is None:
        return None, "none（LlmSeam.for_secretary 返回 None：造不出秘书档的缝）"
    if not getattr(got, "wired", False):
        return None, ("none（秘书那一档没有配模型 key ⇒ for_secretary 造出来的是空缝；"
                      "这里不把空缝装上去：空缝会把『从来没有判断面』写成『试过了、没成』）")
    if meter_problem:
        return got, f"secretary（LlmSeam.for_secretary；{meter_problem}）"
    return got, "secretary（LlmSeam.for_secretary）"


def for_role_wired(role: str, *, root: str | Path, seam: Any = None,
                   store: Any = None, registry: Any = None,
                   sid: str | None = None, enable_model: bool = True,
                   **kw: Any) -> Secretary:
    """造一名"判断面接上了线"的某角色秘书（手上没有缝的构造点调这一支）。

    与 :func:`for_role` 只差一件事：造秘书之前先把缝拿来
    （:func:`seam_for_secretary`），于是 `judge()` 不会因为"没人传 seam="而永远返回
    `checked=False`。真机 sylow5 的形态就是后一种：五个构造点一个都没传 `seam=`，
    命题同一性判定一次都没发生。

    参数
    ----
    seam : 调用方手上已有的缝（`None` ⇒ 现造一条秘书档的，见 :func:`seam_for_secretary`）。
    enable_model : 与 :class:`Secretary` 同义，缺省 `True` —— 这一支的整个存在意义就是
        把判断面打开；关着的时候 `judge()` 仍然如实返回 `checked=False`（说"开关关着"），
        所以"我明确不要模型判断"也读得出来。
    kw : 其余关键字参数原样交给 :class:`Secretary`（`deadline_sec` / `log` / 两个阈值…）。

    读数：`Secretary.model_source` 记的是"缝从哪来"（三档见 :func:`seam_for_secretary`），
    没有缝时它连着为什么 —— `judge()` 的 `checked=False` 那一格会把这句话一并带出来，
    于是"判不了"在返回值与台账上都能见到原因，而不是静默退回机械判据。
    """
    if sid is None:
        sid = _ambient_session_sid()
    seam_now, source = seam_for_secretary(str(role), root=root, seam=seam, sid=sid,
                                          store=store)
    return Secretary(str(role), root=Path(str(root)), store=store, registry=registry,
                     seam=seam_now, sid=sid, enable_model=bool(enable_model),
                     model_source=source, **kw)


def selftest() -> int:
    """最小自检：台账分角色、手稿增改查、fail-open 与"执笔失败必须报错"。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="secretary_selftest_"))
    checks: list[tuple[str, bool]] = []
    s = Secretary("D", root=root)
    rec = s.handoff_add(to="F", summary="把猜想交给你", body="证明它。")
    checks.append(("执笔的 sender 是被服务的角色", rec.get("sender") == "D"))
    rev = s.handoff_revise(mid=rec["id"], summary="交接（订正）", body="证明它（第二版）。",
                           reason="引错了一处")
    checks.append(("旧行还在", MS.row_of(root, rec["id"]) is not None))
    checks.append(("订正指回旧行", (MS.row_of(root, rev["id"]) or {}).get("revises") == rec["id"]))
    checks.append(("查得到订正", [r["id"] for r in s.handoff_query(revises=rec["id"])] == [rev["id"]]))
    checks.append(("台账分角色", decisions_path(root, "D").is_file()
                   and not decisions_path(root, "M").exists()))
    # S1m：分片之后"台账分角色"这一条要按两种落点都认（老文件 / 实例分片），
    # 并且保留一条"老文件仍可读"的反负控 —— 否则分片会悄悄改掉历史工作区的读侧口径。
    shard = Secretary("E", root=root)
    shard.bind_task("t-0007")
    shard.note_decision(duty=1, kind=KIND_OPTIMIZED, decision="已优化", reason="自检：分片写入")
    checks.append(("台账按实例分片", shard.decisions_path().is_file()
                   and shard.decisions_path().name == "E-t-0007.jsonl"))
    checks.append(("分片读得回来（且老文件仍可读）",
                   len(shard.decisions()) == 1
                   and str(shard.decisions()[0].get("task_id")) == "t-0007"
                   and decisions_path(root, "E").exists() is False))
    checks.append(("存活读数三态", shard.secretary_alive().get("checked") is True
                   and shard.secretary_alive().get("alive") is True
                   and shard.close().get("closed") is True
                   and shard.secretary_alive().get("alive") is False))
    loud = False
    try:
        s.handoff_add(to="F", summary="", body="")
    except ValueError:
        loud = True
    checks.append(("执笔失败必须报错（不静默放行）", loud))
    checks.append(("写集恒为 ∅", s.writes == frozenset()))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())

