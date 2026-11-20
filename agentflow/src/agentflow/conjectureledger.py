# -*- coding: utf-8 -*-
"""猜想台账的唯一写点（生产侧：E 的实验、F 的稿命题、B 的收录）。

## 为什么它从工具层搬到库层（业主 2026-11-13 裁定）

裁定逐字：「D 不该立项临时命题，D 只给研究方向让下面的人去研究，请确认 D 自己这没有
自己的一套命题。」

改前那一版是 D 的动作 `register_conjecture`（工具 `conjecture.register_conjecture`，
`roles=("D",)`）：真机 42 个工作区 111 行 `conjectures` 的 `created_by` 全部是
`agent-D`，而且 D 会把 E 的实验号、F 的稿 + V 的签、B 的拒收读进来自己改 `status` 与
`notes` —— 那就是"D 自己的一套命题"的完整形态（证据：
`projects/octahedron-20261113/sessions/20261113.jsonl:1550`）。
于是本模块只做一件事：把「把自己已经产出的那条命题如实记进台账」这一笔从 D 手上收回，
交回产出侧三族。没有任何角色有「立一条猜想」这个动作 —— 台账里的行只能由
E 的 `run_experiment`、F 的 `attack.step` 落稿、B 的 `register_statement` 收录产生。

## 三族的落账时机（各自都已经有"命题在手里"的那一刻）

| 族 | 落账点 | 起手 status |
|---|---|---|
| E | `run_experiment` 的事务内、`tx.upsert("experiments")` 之后（要能核到那行实验） | `supports` ⇒ `supported_not_proved`；`refutes` ⇒ `refuted`（带反例实验号）；`inconclusive` ⇒ `testing` |
| F | `_open_manuscript` 那一刻（命题过了形态闸、稿已开） | `proposed`（有 `testable` 时）/ `needs_evidence`（没有可检验形式时，必须写 `notes`） |
| B | `register_statement` 收录成功之后（事务外） | 既有行 ⇒ 原状态不动 + 落一条 `[landed] stmt:N` 的读数；没有既有行 ⇒ `needs_evidence` + notes |

## 被拒那一档（`refuted`）的两条证据，缺一不可

`schema.Conjecture` 的 `refuted` 从此认两条并列的证据：

- `counterexample_experiment_id`：E 跑出了反例（`result="refutes"`，`verify` 另核它真是反例）；
- `refusal_ref`：谁拒了它（V 的 `verifications/<命题号>.jsonl#v-...`，或 B 的
  `b-refusal:<受控码>#<手稿/命题>`）。

两条都空 ⇒ `validate()` 拒收。为什么不能只有一条：把"V 判了有毛病"折成"没有反例"会让
一条被专家判死的命题在台账上看起来只是"还没验"；反过来把"没有反例"折成"被拒"会让一次
没跑成的实验变成一次判决（三态纪律：没查成 ≠ 查过了没问题）。

## 唯一写点的另一半：通用写口不许碰这张表

`store.direct_write_refusal("conjectures")` 会拒 `table.create` / `table.update`（以及任何
带 `tool:` 记号的裸事务）—— 改前那张表是敞着的（`store.py` 的拒信表里只有
`statements` / `dependencies` / `lit_candidates`），于是任何非只读角色都能用通用写口绕开
判重与悬空引用检查落一行（现成形态：`faculty_checks.selftest` 就是直接 `tx.upsert`）。
"""


from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

from . import schema as S
from .store import StoreError

__all__ = [
    "ConjectureError",
    "promoted_to_statement",
    "register",
    "status_for_experiment",
]


#: 台账里"已进命题台账"的那一条读数的键名（`promoted_to_statement`）。
#:
#: 为什么不落成 `status="promoted"`（2026-11-13 裁定 ①）：`promoted` 今天指的是
#: "升格进稿件断言"（`promoted_to={"kind": "document_claim", "id": "<稿号>#<断言号>"}`），
#: 而且 `validate` 还要求一条 `method="formal"` 的 `proof_experiment_id` ——
#: B 把一条文字证明收录成 `statements` 行不是那件事，硬写成 `promoted` 会被
#: `verify._check_12` 判 `promotion_target_missing`（升格落空）。
#: 所以这一档只加读数、不改 schema："已进台账"由 `promoted_to_statement` 给号，
#: 猜想行自己的状态仍是它被证据支持到的那一档（`supported_not_proved` 等）。
PROMOTED_TO_STATEMENT = "promoted_to_statement"

#: 落盘的"已登记"格（FIX186-E，2026-11-19）：这条猜想被 B 收录成了哪一条命题。
#:
#: 与 `promoted_to_statement` 的分工：那个是"按正文现算的读数"（只在收录那一刻算一次、
#: 改写即丢、无消费者）；这一格是写在行上的事实 —— 收录成功即写、后续写不改它。
#: 于是「待登记」视图与收工门的 `conjecture_rows` 能读到"这一条已经从猜想台账毕业了"，
#: 已登记的从活跃集消失（业主三态口径：放弃 / 完工的条目直接踢出）。
#:
#: 为什么是"多一格可选字段"而不是 `status="registered"`：`CONJECTURE_STATUSES` 是受控
#: 词表，加一档等于放宽一整根轴（FC-27）；而"进了命题台账"不是猜想自己的证据状态
#: （它可能同时是 supported_not_proved / refuted）。老行没有这一格 ⇒ 读成空串（未登记）。
REGISTERED_STMT_ID = "registered_stmt_id"


class ConjectureError(ValueError):
    """业务失败（带受控 `kind`），与"调用方写错了"分开报。"""

    def __init__(self, message: str, *, kind: str = "conjecture_error", **details: Any):
        super().__init__(message)
        self.kind = kind
        self.details = details


def _text(value: Any) -> str:
    return str(value or "").strip()


def norm_statement(text: Any) -> str:
    """判重用的规范化 `statement`（`draft/39` §3.9/§3.12 D13 的判据）。

    去掉空白与标点（中英文都去）、全角转半角不做（那要一张映射表，换一个库就漂），
    只做"同一句话换个说法就躲过判重"里最常见的那一类：空格与标点。
    判重键取它的 sha 前 16 位（够用且可读；与 `_summon_key` 的口径一致）。
    """
    stripped = re.sub(r"[\s，。；：、,.;:!?！？（）()\[\]【】\"'“”‘’…—-]+", "", str(text or ""))
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:16]


def status_for_experiment(result: Any) -> str:
    """E 的那一条实验读成猜想的起手状态（唯一映射，别处不许再判一次）。

    三态纪律：`inconclusive` 落 `testing`，不许落 `refuted` —— 没查成不是查过了被否证。
    """
    got = str(result or "").strip()
    if got == "supports":
        return "supported_not_proved"
    if got == "refutes":
        return "refuted"
    return "testing"


# --------------------------------------------------------------------------- 写点


def register(*, store: Any = None, tx: Any = None, statement: str, origin: str,
             conjecture_id: str | None = None,
             testable: Mapping[str, Any] | None = None,
             form: str | None = None,
             negation_statement: str | None = None,
             status: str | None = None,
             experiment_ids: Sequence[str] | None = None,
             proof_experiment_id: str | None = None,
             counterexample_experiment_id: str | None = None,
             refusal_ref: str | None = None,
             promoted_to: Mapping[str, Any] | None = None,
             known_lit_id: str | None = None,
             withdraw_reason: str | None = None,
             registered_stmt_id: str | None = None,
             notes: str | None = None,
             defaults: Mapping[str, Any] | None = None,
             force_new: bool = False,
             actor: str = "producer") -> dict:
    """新建或更新一条猜想。返回落库后的 `conjectures` 行（外加 `duplicate` 读数）。

    ## 三态在这里的落点：`None` = "调用方没提这件事"

    所有可选参数的默认值都是 `None`（不是 `""` / `"proposed"`）。这一个选择决定了更新
    语义：`None` ⇒ 保留库里已有的值；若默认写成 `status="proposed"`，一次"只改 notes"
    的调用会把一条 `supported_not_proved` 的猜想静默退回 `proposed` —— 那是把"我没提
    状态"读成了"状态是 proposed"。新建（没有库里那一份）时兜默认值：
    `status="proposed"`、`form="universal"`。

    `defaults` 是"新建那一笔才写得进去"的兜底（`None` 且库里没有这一格时用）：
    E / F / B 是同一个命题的三个时刻，重复落账不该把前一处写的 `notes` 冲掉。

    `origin` 必填（防"凭空出现的猜想"，`Conjecture.validate` 逐字要求）——它的取值就是
    "这条猜想是从哪来的"，三族各写各的：`experiment:<实验号>` / `f-manuscript:<稿路径>` /
    `statements:<命题号>`。

    ## 判重：没给 `conjecture_id` 时先按规范化 `statement` 找同一条（`draft/39` §3.9）

    真机读数（改前 p6e 对 D 的 25 次派活）：5 次成功落了 5 行，其中 3 行的规范化
    `statement` sha 完全相同、1 行只差标点 —— 原因是"重试即新建" + "想更新却没带 id"。
    修法：没给 id 时先找同一条（规范化后相等）⇒ 命中就返回既有行并把本次给的状态 /
    证据合并进去（结果里记 `duplicate=true` 与命中 id）；真要新建必须显式
    `force_new=True`（那是调用方的决定，不是默认行为）。

    ## `tx` 形参：调用方已经持有事务时把它交进来（E 的那一条）

    E 在 `run_experiment` 的事务里落实验行，猜想必须与它同生共死（要么都在、要么都不在），
    所以那一支传 `tx=`；F / B 不持事务，给 `store=` 由本函数自己开
    （`note="conjectureledger:register"`，不是 `tool:` 记号 —— 见 `store.tx` 的说明）。
    """
    if not _text(statement):
        raise ConjectureError("statement 不能为空：猜想必须是一条可判真假的陈述句",
                              kind="validation_error")
    if not _text(origin):
        raise ConjectureError(
            "origin 必填：猜想的来源必须可追（`experiment:<号>` / `f-manuscript:<稿>` / "
            "`statements:<号>`）", kind="validation_error")
    if tx is not None:
        return _upsert(
            tx, statement=str(statement), origin=str(origin), conjecture_id=conjecture_id,
            testable=testable, form=form, negation_statement=negation_statement,
            status=status, experiment_ids=experiment_ids,
            proof_experiment_id=proof_experiment_id,
            counterexample_experiment_id=counterexample_experiment_id,
            refusal_ref=refusal_ref, promoted_to=promoted_to, known_lit_id=known_lit_id,
            withdraw_reason=withdraw_reason, registered_stmt_id=registered_stmt_id,
            notes=notes, defaults=defaults,
            force_new=force_new, actor=actor)
    if store is None:
        raise ConjectureError("store 与 tx 至少要给一个（没接线不是『库里没有猜想』）",
                              kind="not_wired")
    with store.tx("conjectures", "experiments", "literature", "documents",
                  actor=actor, note="conjectureledger:register") as own:
        return _upsert(
            own, statement=str(statement), origin=str(origin), conjecture_id=conjecture_id,
            testable=testable, form=form, negation_statement=negation_statement,
            status=status, experiment_ids=experiment_ids,
            proof_experiment_id=proof_experiment_id,
            counterexample_experiment_id=counterexample_experiment_id,
            refusal_ref=refusal_ref, promoted_to=promoted_to, known_lit_id=known_lit_id,
            withdraw_reason=withdraw_reason, registered_stmt_id=registered_stmt_id,
            notes=notes, defaults=defaults,
            force_new=force_new, actor=actor)


def _upsert(tx: Any, *, statement: str, origin: str, conjecture_id: str | None,
            testable: Mapping[str, Any] | None, form: str | None,
            negation_statement: str | None, status: str | None,
            experiment_ids: Sequence[str] | None, proof_experiment_id: str | None,
            counterexample_experiment_id: str | None, refusal_ref: str | None,
            promoted_to: Mapping[str, Any] | None, known_lit_id: str | None,
            withdraw_reason: str | None, registered_stmt_id: str | None,
            notes: str | None,
            defaults: Mapping[str, Any] | None, force_new: bool, actor: str) -> dict:
    """在给定事务里落一行（判重 / 合并 / 单行判据 / 跨对象存在性）。"""
    key = norm_statement(statement)
    cid = _text(conjecture_id)
    dup_of = ""
    if not cid and not force_new:
        for r in tx.rows("conjectures"):
            if norm_statement(str(r.get("statement") or "")) == key:
                dup_of = str(r.get("conjecture_id") or "")
                break
        if dup_of:
            cid = dup_of
    prev: dict = {}
    if cid:
        row = tx.find("conjectures", conjecture_id=cid)
        if row is None:
            raise ConjectureError(
                f"猜想 {cid} 不存在 ⇒ 不许把一次更新静默变成新建"
                "（那会产生一条重复的猜想，而两条看起来都正常）",
                kind="unknown_conjecture", conjecture_id=cid)
        prev = dict(row)
    else:
        cid = tx.alloc_id("conjecture")

    fallbacks = dict(defaults or {})

    def pick(name: str, given: Any, default: Any = "") -> Any:
        """`None`（没提）⇒ 库里那一份；库里也没有 ⇒ `defaults` 那一份；再没有 ⇒ `default`。"""
        if given is not None:
            return given
        if name in prev:
            return prev.get(name)
        if name in fallbacks:
            return fallbacks[name]
        return default

    # ---- FIX186-F（2026-11-19）：`experiment_ids` 是并集，不是替换 ---------
    #
    # 改前 `experiment_ids` 给了就用给的、不给才用库里的 ⇒ "最后一次写的人说了算"。
    # lp-ball-11 的 c000002 共 11 次写（`data/events.jsonl` seq=1036…1541），每一笔只带
    # 自己那条实验号 ⇒ 最终行上只剩 exp:000017，前十条证据从读数里消失。
    prev_exp = [_text(x) for x in (prev.get("experiment_ids") or []) if _text(x)]
    exp_ids = sorted({*prev_exp, *[_text(x) for x in (experiment_ids or []) if _text(x)]})
    # ---- FIX186-F：反例号不许被「非反例的那一笔」清空 --------------------------
    #
    # `agent_e/run_experiment.py` 的台账那一笔总是显式传
    # `counterexample_experiment_id=(eid if refutes else "")` ⇒ 一次 supports / testing
    # 就把已经记下的反例抹掉（c000002：最终 status=supported_not_proved、反例号为空，
    # 而 notes 里还写着 exp:000002 refutes —— 行自己跟自己矛盾）。
    prev_cex = _text(prev.get("counterexample_experiment_id"))
    counterexample = _text(counterexample_experiment_id) or prev_cex
    # ---- FIX186-F：`refuted` 是终态，后来的实验不许把它静默改成「有支持」 ------
    #
    # 只有显式撤下（`withdrawn`，schema 要求带理由）才允许越过这一格。判据读的是行上
    # 已有的证据（反例实验号 / 拒收引用）—— 两条都在才谈得上"已经判死"。
    status_given = _text(pick("status", status, "proposed"))
    prev_status = _text(prev.get("status"))
    if (prev_status == "refuted"
            and (prev_cex or _text(prev.get("refusal_ref")))
            and status_given not in ("refuted", "withdrawn")):
        status_given = "refuted"
    row_obj = S.Conjecture(
        conjecture_id=cid,
        statement=_text(statement),
        negation_statement=_text(pick("negation_statement", negation_statement)),
        form=_text(pick("form", form, "universal")),
        testable=dict(testable if testable is not None
                      else (prev.get("testable") or fallbacks.get("testable") or {})),
        origin=_text(origin),
        status=status_given,
        experiment_ids=exp_ids,
        proof_experiment_id=_text(pick("proof_experiment_id", proof_experiment_id)),
        counterexample_experiment_id=counterexample,
        refusal_ref=_text(pick("refusal_ref", refusal_ref)),
        promoted_to=dict(promoted_to if promoted_to is not None
                         else (prev.get("promoted_to") or fallbacks.get("promoted_to") or {})),
        known_lit_id=_text(pick("known_lit_id", known_lit_id)),
        withdraw_reason=_text(pick("withdraw_reason", withdraw_reason)),
        notes=_text(pick("notes", notes)),
        created_at=str(prev.get("created_at") or S.now_iso()),
        updated_at=S.now_iso(),
        created_by=str(prev.get("created_by") or actor),
        # SH-10：这一次写的人（并进来的第二笔会改它，`created_by` 不动）。
        updated_by=str(actor or ""),
    )
    # 单行内判据只有这一处：schema 说不行就是不行（§7.5 状态机的每一句都在这里）
    row_obj.validate()
    # ---- 跨对象的存在性在写入期就核一遍（与 `register_dependency` 的
    # `status='closed'` 同一条纪律）：schema 只能查字段非空，
    # 查不出 `exp:9999` 根本不在库里。`verify.verify_all` 是第二道闸。
    for eid in exp_ids + [row_obj.proof_experiment_id, row_obj.counterexample_experiment_id]:
        if eid and not any(str(r.get("experiment_id")) == eid for r in tx.rows("experiments")):
            raise ConjectureError(
                f"猜想 {cid} 引用了不存在的实验 {eid!r}："
                "schema 查不出这一点（它看不见别的表）—— 引用一次不存在的实验，"
                "等于把一条没有证据的猜想说成有证据",
                kind="dangling_experiment", conjecture_id=cid, experiment_id=eid)
    if row_obj.known_lit_id and not any(
            str(r.get("lit_id")) == row_obj.known_lit_id for r in tx.rows("literature")):
        raise ConjectureError(
            f"猜想 {cid} 的 known_lit_id={row_obj.known_lit_id!r} 不在 literature 表里："
            "『别人证过』这句话必须指向一篇真的在库里的文献",
            kind="dangling_lit", conjecture_id=cid, lit_id=row_obj.known_lit_id)
    data = row_obj.to_dict()
    # FIX186-E：这一格不在 `Conjecture` 的字段里（不抬 schema 版本），但它是落盘的
    # 事实：`tx.upsert` 原样写、`rebuild` 会把非 schema 键原样保留（见 store 的
    # "合并而非替换"）。读侧（"待登记"视图 / 收工门 `conjecture_rows`）按它判"毕业"。
    # 给空串也是一个值（"查过了、还没登记"）—— 与"没有这一格"（老行）分开。
    data[REGISTERED_STMT_ID] = _text(pick(REGISTERED_STMT_ID, registered_stmt_id))
    # 读数：这一次是"命中既有行"还是"真的新建"，命中的是哪一条。调用方要能机械地
    # 看到"我这次的登记没有产生新行"，那才是"重复登记"这个病被治好的证据。
    data["duplicate"] = bool(dup_of)
    if dup_of:
        data["duplicate_of"] = dup_of
    tx.upsert("conjectures", data)
    return data


# --------------------------------------------------------------------------- 被拒那一档


def mark_refuted(*, store: Any = None, tx: Any = None, conjecture_id: str = "",
                 statement: str = "", refusal_ref: str, notes: str | None = None,
                 actor: str = "producer") -> dict:
    """把一条猜想落成"被拒"（`refuted` + `refusal_ref`）。

    `conjecture_id` 与 `statement` 二选一：给号优先（调用方手上有号时不必再判重）。
    找不到那一条 ⇒ 返回 `{"ok": False, "kind": "unknown_conjecture"}`（不许静默新建：
    "被拒"总得有一条被拒的东西；凭空造一行会把一次误判变成一条新猜想）。
    """
    cid = _text(conjecture_id)
    if not cid:
        if not _text(statement):
            raise ConjectureError("mark_refuted 需要 conjecture_id 或 statement 之一",
                                  kind="validation_error")
        if store is None:
            raise ConjectureError("按 statement 找行时需要 store（没接线不是『没被拒』）",
                                  kind="not_wired")
        key = norm_statement(statement)
        for r in store.rows("conjectures"):
            if norm_statement(str(r.get("statement") or "")) == key:
                cid = str(r.get("conjecture_id") or "")
                break
        if not cid:
            return {"ok": False, "kind": "unknown_conjecture",
                    "reason": "台账里没有这条命题 ⇒ 不新建一行（被拒的必须是被登记过的那一条）"}
    got = register(store=store, tx=tx, conjecture_id=cid, statement=statement or _statement_of(
        store, tx, cid), origin=_origin_of(store, tx, cid), status="refuted",
        refusal_ref=refusal_ref, notes=notes, actor=actor)
    got["ok"] = True
    got["refuted"] = True
    return got


def _row_of(store: Any, tx: Any, cid: str) -> dict:
    """按号取回那一行（`tx` 优先：调用方持有事务时读它那一份缓存）。

    只有 `Tx` 有 `find`（`Store` 只有 `rows`）⇒ 这一处刻意不调 `find`，两种情况都走
    `rows()` 的一个小循环，省得"有没有 find"变成调用方的分支。
    """
    source = tx if tx is not None else store
    for row in source.rows("conjectures"):
        if str(row.get("conjecture_id") or "") == cid:
            return dict(row)
    return {}


def _statement_of(store: Any, tx: Any, cid: str) -> str:
    """按号取回那一行的 `statement`（`register` 的正文是必填，更新语义下不许改写它）。"""
    return _text(_row_of(store, tx, cid).get("statement"))


def _origin_of(store: Any, tx: Any, cid: str) -> str:
    """按号取回那一行的 `origin`（同上：更新不许把来路改掉）。"""
    return _text(_row_of(store, tx, cid).get("origin")) or "refusal"


# --------------------------------------------------------------------------- 读数


def promoted_to_statement(store: Any, row: Mapping[str, Any]) -> dict:
    """这条猜想是不是已经进了命题台账（三态读数，纯读，不写盘）。

    2026-11-13 裁定 ①：`promoted` 那一档今天指的是"升格进稿件断言"，B 把文字证明收进
    `statements` 不是那件事（硬写会被 `verify` 判升格落空）⇒ 这一档只给读数：
    `promoted_to_statement=<命题号>`，让"已进台账"看得见，而猜想行自己的状态不动。

    返回 `{checked, statement, reason, matches, stmt_id}`：

    - `checked=True` + `stmt_id` 非空：台账里有一条 `statement_full` 规范化后与它相同的命题；
    - `checked=True` + `stmt_id` 空：查过了，台账里没有这一条；
    - `checked=False` + `reason`：没查成（`statements` 读不出来）—— 三态纪律，
      "没查成"绝不等于"没进台账"。
    """

    text = _text(row.get("statement"))
    out: dict[str, Any] = {"checked": False, "statement": text, "reason": "",
                           "matches": [], "stmt_id": ""}
    if not text:
        out["reason"] = "这一行没有 statement ⇒ 没有可比的正文（不是『没进台账』）"
        return out
    try:
        rows = [dict(r) for r in store.rows("statements")]
    except Exception as exc:  # noqa: BLE001 —— 读不到要说出来，不许折成"没有"
        out["reason"] = f"`statements` 读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
        return out
    key = norm_statement(text)
    hits = [str(r.get("stmt_id") or "") for r in rows
            if norm_statement(r.get("statement_full")) == key and str(r.get("stmt_id") or "")]
    out["checked"] = True
    out["matches"] = sorted(hits)
    out["stmt_id"] = sorted(hits)[0] if hits else ""
    out["reason"] = ("台账里有同一条命题" if hits else "台账里没有同一条命题（查过了）")
    return out


def store_error_kind(exc: BaseException) -> str:
    """把存储故障与业务失败分开报（`conjecture_tools` 那一层原先的 `_guard_result` 口径）。

    留在本模块是为了三族共用一份：E / F / B 各自 try/except 一遍会让同一个故障在三处
    读出三个 `kind`。
    """
    if isinstance(exc, ConjectureError):
        return str(exc.kind)
    if isinstance(exc, StoreError):
        return "store_error"
    if isinstance(exc, ValueError):
        return "validation_error"
    return "store_error"
