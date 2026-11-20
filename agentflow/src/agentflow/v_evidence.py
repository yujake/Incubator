# -*- coding: utf-8 -*-
"""证据同一性（同一份读数只算一份）。

2026-11-20（VERSPLIT2）：`v_evidence.py` 是从 `verifications.py` 搬出的 4 块 / 173 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import textutil as T  # 引用解析的唯一实现（`citation_ref_parts`，`P-5`）


def opposite_direction_evidence(claim: Mapping[str, Any],
                                experiment: Mapping[str, Any]) -> dict[str, Any] | None:
    """这条断言引用这条实验时，方向是不是反的 —— 判据本体（纯读，`None` = 不反）。

    ## 判的是什么（可机械化的那一半）
    一条实验行自己的结论是 `result="refutes"`（连同 `negation_kind="disproved"`，这是
    `schema.Experiment.validate` 强制的），意思是"它检验的那条命题被证否了"。一条正文断言
    把它列进 `citations` 当支撑时，台账上必须能读出"这条断言正是在说「我们证否了它」"——
    机械读法就是 `is_negative=True` 且 `negation_kind="disproved"`（`doc_tools.check_proofs`
    2026-10-13 的口径，真机现场：`projects/p6t2-research-20261012b` 的 claim-2 把 `exp:0002`
    （`result="refutes"`）列进 `citations` 当支撑，一路写库）。判据只需要两个字段：证据行的
    `result` / `negation_kind`，断言的 `is_negative` / `negation_kind` —— 都在 schema 里。
    ## 哪一半判不了（如实登记，不硬造）
    反方向的那一支 —— 断言登记成"已证否"、却引一条 `result="supports"` 的实验 —— 不归本判据管：
    `supports` 是相对于实验行自己的 `claim` 说的，而一条否定型断言（例如「不存在这样的图」）完全
    可能由一条 `supports` 的实验支持；更常见的是 `supports` 只是 `cross_check`（数值支持）。要判
    它，必须让实验行声明"它检验的命题相对于这条正文断言的正负极性"（例如 `tests_claim_id` +
    `direction` 两格），那是 schema 改动，不是审计侧能单方面补的。同理，`result="refutes"` 引一条
    正面断言也只有在"实验检验的就是这条断言所说的命题"时才是真相反 —— 本判据把"引用关系"当成
    那个链接（与写入期、收工门同一口径）。
    ## 返回值：不反 ⇒ `None`；反 ⇒ 一个 dict（`experiment_id` / `result` / 断言侧字段 / `why`），写入期与审计期各自决定怎么呈现（`problem` / `Issue`），判定本身不重复。
    """
    if str(experiment.get("result") or "") != REFUTES:
        return None
    if bool(claim.get("is_negative")) and str(claim.get("negation_kind") or "") == DISPROVED:
        return None
    eid = str(experiment.get("experiment_id") or "")
    return {
        "experiment_id": eid,
        "result": REFUTES,
        "claim_is_negative": bool(claim.get("is_negative")),
        "claim_negation_kind": str(claim.get("negation_kind") or ""),
        "why": (
            f"它引了 {('exp:' + eid) if eid else '这条实验'} 当支撑，而那条实验自己的结论是 "
            f"`result={REFUTES!r}`（否证）⇒ 一条否证被当成支撑用了。"
            "要么把这条断言改成否定型并写 `is_negative=True` + "
            f"`negation_kind={DISPROVED!r}`（「我们证否了它」），"
            "要么换一条真正支持它的证据；只在正文里解释「那只是脚本内部判据的问题」不算数 —— "
            "台账上它仍然是 refutes。"
        ),
    }


def _freeze(value: Any) -> Any:
    """把 `observations.data` 变成可比较的规范形（dict 的键序不参与同一性）。"""
    if isinstance(value, Mapping):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def evidence_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """一条实验行的"证据身份"：同一份读数只该算一份证据。

    ## 为什么身份不能只是 `experiment_id`
    真机读数（`draft/39` §6.27 的 D39，T2 第 9 趟 `p6k`）：一个脚本被派了 9 次，claim 分别是
    W(2)/W(3)/W(4)…，每次都打印逐字相同的 `data`（30 顶点 / 度 3）—— 始终是同一个图。台账上于是
    有 9 条 `result="supports"`，手稿把它们当 9 份独立证据引：同一份读数被当成了九份。这 9 条的
    `experiment_id` 各不相同，所以"按 `experiment_id` 判重"看不见它。
    ## 身份的定义（与 E 写入期那条 note 同一处）：有 `observations.data`（非空）⇒ 同脚本
    （`code_hash`）+ 同 `data` 即同一份证据（`code_hash` 为空也照比：历史行没有哈希时，"同 data" 仍是唯一可比的读数）；没有 `data` ⇒ 退回
    `experiment_id`（同一行被引两次是同一份证据；两行都没有 data 时不合并 —— 那会靠猜）。
    此前它只在 `agent_e.run_experiment._reused_evidence_note` 里，现在两边都读这一个函数（FC-03：同一件事不许有两份定义）。
    """
    obs = row.get("observations")
    data = dict(obs.get("data") or {}) if isinstance(obs, Mapping) else {}
    if data:
        return ("data", str(row.get("code_hash") or ""), _freeze(data))
    return ("row", str(row.get("experiment_id") or ""))


def one_evidence_used_twice(documents: Iterable[Mapping[str, Any]],
                            experiments: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """同一份证据被同一份稿件里的两条不同断言当独立证据用 —— 纯读。

    ## 判据（一条）：把每份稿件的 `claims[].citations` 里的 `exp:` 引用按 :func:
    `evidence_identity` 归组；同一组里出现 ≥ 2 个不同的 `claim_id` ⇒ 报一条。
    为什么 warning 不是 error（与 `opposite_direction_evidence` 的 error 不同）：同一份证据被两条
    断言引用可以是正当的（定理与推论、综述复述同一条读数、两条表述压在同一次计算上）。台账分不出
    "两条独立支撑"与"一份支撑被数了两遍"，所以它必须是看得见的读数，不是硬拦（会红掉合规稿件），
    而完全不说又正是 D39 的形态。处置写进 `why`：是复现就在正文与实验行 `notes` 里说清。
    ## 范围只在一份稿件内：跨稿件复用同一份证据是正常的（综述与论文引同一条实验）；判据只在
    同一份 `documents` 行内部比较 —— 返回值 `[{doc_id, claim_ids, experiment_ids, why}]`；
    空列表 = 不报（正常形态）。
    """
    exp_by_id: dict[str, Mapping[str, Any]] = {}
    #: 同一行实验被几条断言各引一次时，`_freeze(observations.data)` 只算一次（第一次被引时缓存）。
    ident: dict[str, tuple[Any, ...]] = {}
    for row in experiments:
        if not isinstance(row, Mapping):
            continue
        eid = str(row.get("experiment_id") or "")
        if eid:
            exp_by_id[eid] = row
    out: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, Mapping):
            continue
        doc_id = str(doc.get("doc_id") or "")
        groups: dict[tuple[Any, ...], dict[str, list[str]]] = {}
        for claim in doc.get("claims") or []:
            if not isinstance(claim, Mapping):
                continue
            cid = str(claim.get("claim_id") or "")
            if not cid:
                continue
            for cite in claim.get("citations") or []:
                kind, ref = T.citation_ref_parts(cite)
                if kind != "exp":
                    continue
                row = exp_by_id.get(ref)
                if row is None:
                    continue          # 悬空引用由 `dangling_citation` 报，不在这里重复
                key = ident.get(ref)
                if key is None:
                    key = ident[ref] = evidence_identity(row)
                group = groups.setdefault(key,
                                          {"claim_ids": [], "experiment_ids": []})
                if cid not in group["claim_ids"]:
                    group["claim_ids"].append(cid)
                if ref not in group["experiment_ids"]:
                    group["experiment_ids"].append(ref)
        for group in groups.values():
            claim_ids = sorted(group["claim_ids"])
            if len(claim_ids) < 2:
                continue
            experiment_ids = sorted(group["experiment_ids"])
            evidence = " / ".join(f"exp:{eid}" for eid in experiment_ids)
            if len(experiment_ids) == 1:
                same = f"同一条实验行（{evidence}）"
            else:
                same = (f"{evidence} 是同脚本 + 同 `data` 的两次运行"
                        "（`observations.data` 逐字相同）")
            out.append({
                "doc_id": doc_id,
                "claim_ids": claim_ids,
                "experiment_ids": experiment_ids,
                "why": (
                    f"稿件 {doc_id} 的断言 {'、'.join(claim_ids)} 都把 {evidence} 当独立证据用，"
                    f"而它是同一份证据（{same}）⇒ 一条证据被算成了两份。"
                    "若这是复现（同一个对象被核了两次），请在正文与实验行的 `notes` 里"
                    "说清「这不是第二份独立证据」；否则换一条真正独立的证据。"
                ),
            })
    return out


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    DISPROVED,
    REFUTES,
)
