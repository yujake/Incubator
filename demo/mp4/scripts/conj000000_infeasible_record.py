#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conjectures:000000：『合格估计器』不存在性的确定性记录（不产生任何 delta_N 读数）。

本脚本只做确定性算术与枚举，回答一个问题：
  在本会话的执行面上，是否存在一个能过 GATE Q1-Q4
  （scripts/conj000000_verdict_gate.py）的 delta_N(X_k) 估计器？

它不做的事（明确禁止的空转）：
  - 不跑 delta_N = ln V_N / ln N（已作废：随 N 发散，不是维数）；
  - 不跑字面微态球 Haar 体积 MC（命中率 ~e^-2839，不可行）。
  这两条只用解析式复算它们的量级，作为『为什么被排除』的确定性依据。

输出：JSON（stdout），并写到 reports/conj000000_infeasible_record.json。
"""
from __future__ import annotations

import json
import math
import os

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNGS = [8, 16, 32, 64]
KS = [2, 3, 4]
JS = [4, 5, 6, 7, 8]
GATE_Q1_TOL = 0.15
GATE_Q2_TOL = 0.10
GATE_Q4_TOL = 0.10
M_MAX = 200000  # 本会话 E 可执行面已在 exp:000001/exp:000003 用过的单档 MC 上限


def literal_ball_volume():
    """E1：字面口径 mu_N(B_r) ~ r^(k N^2)（r = 2^-j）的确定性量级复算。"""
    rows = []
    for k in KS:
        for N in RUNGS:
            for j in JS:
                ln_p = k * N * N * (-j) * math.log(2.0)
                rows.append({
                    "k": k,
                    "N": N,
                    "r": "2^-%d" % j,
                    "ln_p": round(ln_p, 1),
                    "log10_p": round(ln_p / math.log(10.0), 1),
                    "p_approx": 0.0 if ln_p < -745 else math.exp(ln_p),
                    "samples_needed_for_one_hit": "10^%.1f" % (-ln_p / math.log(10.0)),
                    "feasible": bool(math.exp(ln_p) * M_MAX >= 1.0),
                })
    best = max(rows, key=lambda r: r["ln_p"])  # 最有利的一格
    return {
        "approach_id": "E1",
        "name": "literal_microstate_ball_Haar_volume",
        "estimator": "delta_N(r) = ln mu_N(B_r) / (N^2 ln r)，外推 1/|ln r| -> 0",
        "status": "excluded_infeasible",
        "feasibility_criterion": "直接 MC 估计 mu_N(B_r) 期望命中数 = M * p >= 1，即 M >= 1/p；本会话执行面单档上限 M=%d（exp:000001/exp:000003 实测档）" % M_MAX,
        "magnitude": {
            "formula": "mu_N(B_r) ~ r^(k N^2)，r = 2^-j，k 个自由生成元共 k N^2 个实自由度",
            "most_favorable_cell": {"k": best["k"], "N": best["N"], "r": best["r"], "ln_p": best["ln_p"]},
            "log10_p_k2_N8_r2^-4": next(r["log10_p"] for r in rows if r["k"] == 2 and r["N"] == 8 and r["r"] == "2^-4"),
            "ln_p_k2_N16_r2^-8": next(r["ln_p"] for r in rows if r["k"] == 2 and r["N"] == 16 and r["r"] == "2^-8"),
            "samples_needed_k2_N16_r2^-8": next(r["samples_needed_for_one_hit"] for r in rows if r["k"] == 2 and r["N"] == 16 and r["r"] == "2^-8"),
            "feasible_cells": sum(1 for r in rows if r["feasible"]),
            "total_cells": len(rows),
        },
        "why_infeasible_here": "最有利的一格（最小的 k、最小的 N、最大的 r=2^-4）hit rate 仍远低于 1/M_max；要把 1/p 个样本跑完不是『需要更多算力』的量级差，而是需要能在 B_r 内直接生成微态的重要性采样/变分构造（E4），本会话执行面上没有。",
    }


def proxy_divergence():
    """E2：已作废代理量 delta_N = ln V_N / ln N 的 Q1/Q3 确定性复算（只算比值，不当估值用）。"""
    rows = []
    for k in KS:
        byn = {N: N * math.log(2 * k - 1) / math.log(N) for N in RUNGS}
        checks = []
        for N in RUNGS:
            if 2 * N in byn:
                ratio = byn[2 * N] / byn[N]
                checks.append({
                    "N": N,
                    "N'": 2 * N,
                    "ratio": round(ratio, 4),
                    "abs_ratio_minus_1": round(abs(ratio - 1.0), 4),
                    "pass_Q1": bool(abs(ratio - 1.0) <= GATE_Q1_TOL),
                })
        rows.append({
            "k": k,
            "delta_by_N": {str(n): round(v, 4) for n, v in byn.items()},
            "range_violations_Q3": [n for n, v in byn.items() if not (0.0 < v <= k)],
            "q1_checks": checks,
        })
    return {
        "approach_id": "E2",
        "name": "proxy_ln_V_N_over_ln_N",
        "estimator": "delta_N = ln V_N / ln N，V_N = 1 + sum_{l<=N} 2k(2k-1)^(l-1)",
        "status": "excluded_divergent",
        "feasibility_criterion": "GATE Q1：同 (k, estimator) 相邻倍档 N 与 2N 的均值比 |r-1| <= %.2f；GATE Q3：0 < delta_hat <= k" % GATE_Q1_TOL,
        "magnitude": {"per_k": rows},
        "why_infeasible_here": "ln V_N ~ N ln(2k-1) => delta_N ~ N ln(2k-1)/ln N -> 无穷。N 翻倍时比值 = 2 ln N / ln 2N -> 2，|ratio-1| -> 1，Q1 每一档都必然超 %.2f；同时 N 一大 delta_hat > k，Q3 也破。它不是维数，用它读 ①/② 只会恒真到无意义。" % GATE_Q1_TOL,
    }


def remaining_approaches():
    return [
        {
            "approach_id": "E3",
            "name": "cumulant_defect_D_N",
            "estimator": "无（D_N(L) = max_{|w|<=L} |tau_N(w) - tau_free(w)| 不是 delta_N 的估计器）",
            "status": "excluded_no_bridge",
            "feasibility_criterion": "要作估计器，必须给出 D_N 与 delta_N 之间已证的定量桥（D_N -> delta_N 的不等式）",
            "magnitude": {"existing_readings": "无：本计划没有产出 D_N 的读数（轮 1 §A6 只写了口径，未执行）"},
            "why_infeasible_here": "D_N 量的是『采样点离自由 Haar 有多近』，delta_N 量的是微态球体积的 N 次幂增长率；两者之间本计划没有任何已证的桥。把 D_N 的衰减率当 delta_N 用就是又一个作废代理量（与 E2 同类错误）。",
        },
        {
            "approach_id": "E4",
            "name": "importance_sampling_or_variational_microstate_sampler",
            "estimator": "（尚未构造）能在 B_r(X) 内直接产生微态的重要性采样器或变分族，再用其权重给 mu_N(B_r) 的无偏/有界估计",
            "status": "not_wired",
            "feasibility_criterion": "① 存在对 Haar 测度绝对连续、支撑覆盖 B_r 的提议分布且权重可比；② 在 M=%d 内使 ESS >= 100；③ 估计量对 normalization_scale 不变" % M_MAX,
            "magnitude": {"existing_readings": "无；本会话 E 的可执行面只有『写脚本 + 数值跑』，没有这类构造的实现，也没有它的数学形式"},
            "why_infeasible_here": "这是本会话未接线的一条研究路线：它需要先给出提议分布/变分族的解析形式与权重有界性论证，再才是写脚本。缺的是数学构造，不是算力，也不是数据。",
        },
    ]


def qualified_estimator_spec():
    return {
        "what_counts_as_qualified_estimator": [
            "S1 它是 delta_N(X_k) 的估计器：必须写出 delta_N 的定义式（如 log mu_N(B_r)/(N^2 log r) 的 r->0 外推、或与之等价的极限），并说明为什么该量的 N->无穷 极限等于微态熵维数 delta_0；只给『代理量』不算。",
            "S2 可执行：给出可直接运行的脚本规范（参数名、取值范围、种子派生规则、样本数、收敛判据阈值），并由 E 在至少两个 (k,N) 档上实际跑出读数。",
            "S3 过 GATE Q1（不发散）：rel_se 随 N 单调不增且末档 rel_se <= 0.1，delta_hat 在 N=32 -> 64 相对变化 <= 0.2。",
            "S4 过 GATE Q2（种子可复现）：同一 (k,N) 至少两个 seed，delta_hat 极差 <= 0.10。",
            "S5 过 GATE Q3（量程）：每条读数 0 < delta_hat <= k。",
            "S6 过 GATE Q4（归一化不变）：同一 (k,N,seed) 在不同 normalization_scale 下 delta_hat 相对差 <= 0.05。",
            "S7 可行性：feasible=false 的 (k,N) 档数 <= 1；否则不能支撑全序列判定（Q4 的可行性口径）。",
            "S8 输出字段齐全：estimator、k、N、seed、delta_hat、rel_se、converged、feasible、normalization_scale，且读数落成 experiments 行。",
        ],
        "how_to_check": "把 S8 的读数写成 --readings JSON，跑 scripts/conj000000_verdict_gate.py --readings <json> --out <json>；status=qualified（或 qualified_except_Q4）才算过闸。",
    }


def main():
    record = {
        "target": "attack_plans:000000 / conjectures:000000 — 是否存在能过 GATE Q1-Q4 的 delta_N(X_k) 估计器",
        "verdict": "no_qualified_estimator_in_this_session",
        "reason_code": "estimator_not_qualified",
        "reason_label_zh": "结构性缺口（缺估计器）",
        "not_to_be_confused_with": "数据不足：本会话没有产出任何 delta_N 读数，不是因为读数不够，而是没有任何口径被点名成合格估计器。",
        "gate_script": "scripts/conj000000_verdict_gate.py",
        "gate_tolerances": {"Q1": GATE_Q1_TOL, "Q2": GATE_Q2_TOL, "Q4": GATE_Q4_TOL, "Q3": "0 < delta_hat <= k"},
        "session_execution_surface": {"M_max_per_cell": M_MAX, "rungs_N": RUNGS, "ks": KS, "j_values_r": JS},
        "excluded_approaches": [literal_ball_volume(), proxy_divergence()] + remaining_approaches(),
        "qualified_estimator_spec": qualified_estimator_spec(),
        "note": "本文件只记录『为什么没有合格估计器』与『要什么才算合格』，不产生任何 delta_N 读数，也不是对猜想 000000 的支持或反驳。",
    }
    out_path = os.path.join(WS, "reports", "conj000000_infeasible_record.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print("REPRO_RESULT: " + json.dumps({
        "verdict": record["verdict"],
        "reason_code": record["reason_code"],
        "excluded": [a["approach_id"] + ":" + a["status"] for a in record["excluded_approaches"]],
        "spec_items": len(record["qualified_estimator_spec"]["what_counts_as_qualified_estimator"]),
        "written": out_path,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
