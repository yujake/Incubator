# -*- coding: utf-8 -*-
"""形态读数：同一趟里有没有把一条定理拆成多条独立命题（D-54，只报不拦）。

## 这一份回答的问题

业主 2026-10-24 在真机上看到的现象（`projects/sylow3`）：同一条 Sylow 定理被登记成三条
独立命题（`000000` 正规化子路线 / `000003` Wielandt 路线 / `000006` S3 归纳路线），
`bits.evidence.proofs` 全为空、`proof_no` 全为 None、`path_group` 只有一组。
多证明机制（`proofs=[{proof_no, text}]`、`used_by="stmt:<号>#pN"`、二维 `path_group`、
`reviewed_by_proof`、对应表带 `proof_no`）早就齐了，缺的是"该用它"的口径与一种形态读数。

这一份补的就是那个读数：一条定理被拆成几条命题、而没有任何一条用上第 2 份证明，
这种形态在台账上看起来完全正常（三条表述不同、各有自己的证明），只有把它们放在一起看
才看得出来。判重（`secretary` 的 `_same_proposition_candidate`）只看"同一次登记的正文
是否相同"，看不见"三条不同的表述其实是同一条定理"。

## 判据的三段

1. 候选面：这一批 `statements` 行里，跳过概念行（概念不是命题）与被否证 / 被取代 /
   待补定义的行（`schema.STATEMENT_UNUSABLE_STATUSES`），剩下的按 `statement_full` 两两判同一性。
2. 同一性：只读复用 `propositionkey.same_proposition`（键相同直接判同；键不同再比规范化
   词面相似度，均值 Jaccard 达到阈值才算）。阈值是参数，缺省取
   `propositionkey.SAME_PROPOSITION_JACCARD`（0.85）—— 与"这是不是同一条命题"那一轴
   同一个尺度，不另立一个数。
3. 形态：命中的行按同一性做传递闭包成簇（A 与 B 判同、B 与 C 判同 ⇒ 三条一簇）。
   簇内没有任何一条有 `proof_no > 1`（即所有行都只有 canonical 那一份证明）⇒ 报一条读数，
   点名是哪几条。有一条用了第 2 份证明 ⇒ 这一簇归入 `multi`（多证明机制被用上了，不报）。

## 三态（这一份自己的纪律）

- `readings` 非空 = 查过了，命中了；
- `readings` 为空且 `reason` 为空 = 查过了，没命中（这是"没有这种形态"，不是"没查成"）；
- `readings` 为空且 `reason` 非空 = 没查成（可用命题少于 2 条，或全批都判不了）。

判不了的那一档单独放在 `unknown` 里（文本太短 / 纯符号），绝不折成"不同"：
折平等于把"判不了"读成"没有拆命题"，正是本项目三态纪律最忌的一折。

## 边界

- 纯函数：不读盘、不读 store、不写文件、不调模型；入参是调用方已经读出来的行。
- 不拦门：没有返回值能让任何门变红，它只产出读数（D-54 明确"先让它可见"）。
- 不猜趟：入参就是"这一趟"的那批行（调用方按趟取）；本函数不按 `created_at` 聚趟 ——
  按时间切片会造出"同一趟被切成两半"的假读数，而切法本身没有唯一答案。
- 概念行、被否证行不参与：它们不是"这条定理的一条独立表述"。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from . import propositionkey as PK
from . import schema as S
from . import verifications as VR

#: 读数种类码（进返回值，读的人据此分流；不是错误码，不改变任何门）。
KIND_SUSPECTED_SPLIT = "suspected_split_proposition"

#: 形状读数里"已用上多证明"的那一档（不报，但要留读数：它证明这一簇不是拆命题）。
KIND_ALREADY_MULTI = "already_multi_proof"

#: 同一性阈值（缺省 = 命题轴那一档，见 `propositionkey.SAME_PROPOSITION_JACCARD`）。
SPLIT_JACCARD = PK.SAME_PROPOSITION_JACCARD

#: 报出来的读数里"最高相似度"那一格的精度（与 `propositionkey` 的返回一致）。
_DIGITS = 4


def proof_numbers(row: Mapping[str, Any]) -> list[int]:
    """这条命题在册的证明号（`#p1` 恒在；第 2 份起在 `proofs` 清单里）。"""
    return [int(no) for no, _text in VR.proof_list(row)]


def max_proof_no(row: Mapping[str, Any]) -> int:
    """这条命题的最高证明号：1 = 只有 canonical 那一份（多证明机制没被用上）。"""
    got = proof_numbers(row)
    return max(got) if got else 1


def _stmt_id(row: Mapping[str, Any]) -> str:
    return str(row.get("stmt_id") or "").strip()


def _statement(row: Mapping[str, Any]) -> str:
    return str(row.get("statement_full") or "")


def _skip_reason(row: Mapping[str, Any]) -> str:
    """这一行为什么不进候选面（空串 = 进）。"""
    if not _stmt_id(row):
        return "没有 stmt_id（读不出它属于哪一条命题）"
    if str(row.get("kind") or "") == "concept":
        return "概念行（概念不是命题，没有'几种证明'这回事）"
    status = str(row.get("status") or "")
    if status in S.STATEMENT_UNUSABLE_STATUSES:
        return f"状态是 {status}（不再被当作依据，不能拿去判'是不是同一条'）"
    if not _statement(row).strip():
        return "statement_full 是空的（没有可比的正文）"
    return ""


def _union_find(sizes: int) -> list[int]:
    return list(range(sizes))


def _find(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _union(parent: list[int], i: int, j: int) -> None:
    left, right = _find(parent, i), _find(parent, j)
    if left != right:
        parent[max(left, right)] = min(left, right)


def _describe(reading: Mapping[str, Any]) -> str:
    """一条读数的人话（点名是哪几条、凭什么、缺什么）。"""
    ids = list(reading.get("stmt_ids") or [])
    pairs = list(reading.get("pairs") or [])
    best = max((float(p.get("similarity") or 0.0) for p in pairs), default=0.0)
    return (f"疑似把一条定理拆成了 {len(ids)} 条命题（{' / '.join(ids)}）："
            f"规范化表述两两重合（最高 {best:.4f}），而没有一条有 proof_no>1 "
            f"⇒ 多证明机制没被用上；这是读数，不拦门")


def suspected_splits(rows: Iterable[Mapping[str, Any]], *,
                     threshold: float = SPLIT_JACCARD,
                     scope: str = "") -> dict[str, Any]:
    """形态读数：这一批命题里有没有"同一条定理被拆成多条独立命题"。

    入参 `rows` 是"这一趟"的那批 `statements` 行（调用方按趟取），`scope` 只进读数
    （写明这是哪一趟，便于人就地核对），不参与判据。

    返回（每一格都是确定的，不依赖行的物理顺序）：

    | 键 | 含义 |
    |---|---|
    | `checked` | 进候选面的命题行数（跳过的不算） |
    | `skipped` | 被跳过的行与理由（概念 / 弃用状态 / 空正文 / 没号），逐条点名 |
    | `same_pairs` / `different_pairs` / `unknown_pairs` | 两两判定的三档计数 |
    | `readings` | 命中的簇，每条 = `{kind, stmt_ids, pairs, max_proof_no, proof_nos, note}` |
    | `multi` | 命中的簇里已经用上第 2 份证明的那些（不报，但留读数） |
    | `unknown` | 判不了的对（文本太短 / 纯符号），逐对给理由 |
    | `threshold` / `scope` | 这一次用的阈值与趟标签 |
    | `reason` | 空 = 查过了；非空 = 没查成（可用命题少于 2 条） |
    """
    material = [dict(row) for row in rows if isinstance(row, Mapping)]
    skipped: list[dict[str, str]] = []
    usable: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in material:
        why = _skip_reason(row)
        if why:
            skipped.append({"stmt_id": _stmt_id(row) or "（空）", "why": why})
            continue
        sid = _stmt_id(row)
        if sid in seen_ids:
            skipped.append({"stmt_id": sid, "why": "同一条命题在这一批里出现了两次（读入口有重复行）"})
            continue
        seen_ids.add(sid)
        usable.append({"stmt_id": sid, "row": row, "text": _statement(row)})

    out: dict[str, Any] = {
        "checked": len(usable), "skipped": skipped,
        "same_pairs": 0, "different_pairs": 0, "unknown_pairs": 0,
        "readings": [], "multi": [], "unknown": [],
        "threshold": round(float(threshold), _DIGITS), "scope": str(scope or ""),
        "reason": "",
    }
    if len(usable) < 2:
        out["reason"] = (f"这一批只有 {len(usable)} 条可比命题 ⇒ 形态检测没得比"
                         "（这不是「没有拆命题」）")
        return out

    parent = _union_find(len(usable))
    #: 两两判定只跑一次并留在这里：第二次再判会造出"计数与读数各判一回"的两个口径
    #: （同一个对子在两处给出不同的相似度时，没有任何东西会红）。
    verdicts: dict[tuple[int, int], dict[str, Any]] = {}
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            left, right = usable[i], usable[j]
            verdict = PK.same_proposition(left["text"], right["text"],
                                          threshold=float(threshold))
            verdicts[(i, j)] = verdict
            state = str(verdict.get("state") or "")
            if state == PK.STATE_SAME:
                out["same_pairs"] += 1
                _union(parent, i, j)
            elif state == PK.STATE_UNKNOWN:
                out["unknown_pairs"] += 1
                out["unknown"].append({
                    "a": left["stmt_id"], "b": right["stmt_id"],
                    "state": state, "reason": str(verdict.get("reason") or ""),
                })
            else:
                out["different_pairs"] += 1

    clusters: dict[int, list[int]] = {}
    for i in range(len(usable)):
        clusters.setdefault(_find(parent, i), []).append(i)

    pairs_by_cluster: dict[int, list[dict[str, Any]]] = {}
    # 读数要给人看"凭什么"：相似度取自上面那一轮的同一份判定，不重算。
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        pairs: list[dict[str, Any]] = []
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                left, right = usable[members[x]], usable[members[y]]
                verdict = verdicts.get((min(members[x], members[y]),
                                        max(members[x], members[y])), {})
                if str(verdict.get("state") or "") != PK.STATE_SAME:
                    continue
                left_id, right_id = sorted((left["stmt_id"], right["stmt_id"]))
                pairs.append({
                    "a": left_id, "b": right_id,
                    "similarity": round(float(verdict.get("similarity") or 0.0), _DIGITS),
                    "basis": str(verdict.get("basis") or ""),
                })
        pairs.sort(key=lambda p: (p["a"], p["b"]))
        pairs_by_cluster[root] = pairs

    for root in sorted(clusters):
        members = clusters[root]
        if len(members) < 2:
            continue
        ids = sorted(usable[i]["stmt_id"] for i in members)
        proof_nos = {usable[i]["stmt_id"]: proof_numbers(usable[i]["row"]) for i in members}
        top = max((max(no) if no else 1) for no in proof_nos.values())
        entry: dict[str, Any] = {
            "stmt_ids": ids,
            "pairs": pairs_by_cluster.get(root, []),
            "max_proof_no": int(top),
            "proof_nos": {sid: sorted({int(n) for n in proof_nos[sid]} or {1})
                          for sid in sorted(proof_nos)},
        }
        if top > 1:
            entry.update(kind=KIND_ALREADY_MULTI,
                         note="这一簇里已经有第 2 份证明 ⇒ 多证明机制被用上了，不报")
            out["multi"].append(entry)
        else:
            entry.update(kind=KIND_SUSPECTED_SPLIT)
            entry["note"] = ("同一趟里这几条命题的规范化表述高度重合，而没有一条有 "
                             "proof_no>1 ⇒ 疑似把一条定理拆成多条命题（D-54）；"
                             "处置是并成一条 stmt 的 proof_no 1..N，不是删行（读数不拦门）")
            out["readings"].append(entry)
    for key in ("readings", "multi"):
        out[key].sort(key=lambda item: tuple(item.get("stmt_ids") or ()))
    out["unknown"].sort(key=lambda item: (item.get("a") or "", item.get("b") or ""))
    return out


def describe(reading: Mapping[str, Any]) -> str:
    """把一条读数写成一句人话（点名是哪几条、凭什么、缺什么）。"""
    return _describe(reading)


def summary(reading: Mapping[str, Any]) -> str:
    """这一批的总体读数（一行；`reason` 非空时如实写"没查成"）。"""
    reason = str(reading.get("reason") or "")
    scope = str(reading.get("scope") or "")
    head = f"[{scope}] " if scope else ""
    if reason:
        return f"{head}形态检测没查成：{reason}"
    hits = list(reading.get("readings") or [])
    multi = list(reading.get("multi") or [])
    return (f"{head}可比命题 {reading.get('checked')} 条 · 判同 {reading.get('same_pairs')} 对 · "
            f"判不同 {reading.get('different_pairs')} 对 · 判不了 {reading.get('unknown_pairs')} 对 ⇒ "
            f"疑似拆命题 {len(hits)} 簇 · 已用多证明 {len(multi)} 簇"
            + (f"；{'; '.join(_describe(r) for r in hits)}" if hits else ""))


def selftest() -> int:
    """自检（不读盘、不写盘）：造一批"同一条定理的两种写法 + 一条无关命题"。返回 0 = 全过。"""
    rows = [
        {"stmt_id": "000001", "kind": "theorem", "status": "active",
         "statement_full": "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。",
         "proof_text": "证明：由轨道-稳定子定理。"},
        {"stmt_id": "000002", "kind": "theorem", "status": "active",
         "statement_full": "假设 G 为有限群，p 为素数，于是 G 的 Sylow p-子群存在。",
         "proof_text": "证明：由群作用与轨道计数。"},
        {"stmt_id": "000003", "kind": "theorem", "status": "active",
         "statement_full": "设 H 是交换群；则 H 的每个子群都正规。",
         "proof_text": "证明：交换群的共轭作用恒等。"},
    ]
    got = suspected_splits(rows, scope="selftest")
    hits = got.get("readings") or []
    ok = bool(hits) and list(hits[0].get("stmt_ids") or []) == ["000001", "000002"]
    print(summary(got))
    if not ok:
        print(f"FAIL: 自检夹具应当报出 000001/000002，实际 {hits!r}")
        return 1
    print("statementfission selftest: 1/1 条通过")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手工自检入口
    raise SystemExit(selftest())
