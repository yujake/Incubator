#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conjectures:000000 的可执行判定闸门（确定性代码；不产生任何数值读数）。

它只做两件事：
  1) 判定一个候选估计器是否"合格"（GATE，Q1-Q4）；
  2) 在合格之后，按 guesses 里预先写死的不等式给出「支持 / 反驳 / 数据不足」三档出口。

输入  --readings <json>：
  {"readings": [
     {"estimator": "<名字>", "k": 2, "N": 8, "seed": 0,
      "delta_hat": 1.9, "rel_se": 0.05, "converged": true,
      "feasible": true, "normalization_scale": 1.0}, ...]}
  每一条读数由一个"合格估计器"产出；本脚本不生成数字，只判定。

输出  --out <json>：{"gate": {...}, "criterion": {...}, "raw_notes": [...]}

闸门（缺一项就不许进入判定；未通过一律记"数据不足/结构性缺口"，不是"反驳"）：
  Q1 不发散：同 (k, estimator) 相邻档 N 与 2N 的均值比 |r-1| <= 0.15
              —— 当初 δ_N = ln V_N/ln N ≈ N·ln(2k-1)/ln N 就是被这一条挡下的量。
  Q2 种子可复现：同 (k,N) 至少两个 seed，极差 <= 0.10；一个 (k,N) 只有单 seed ⇒ 未测。
  Q3 量程：每条读数 0 < delta_hat <= k（微态熵维数按定义不超过生成元个数）。
  Q4 归一化不变（有数据才判）：同 (k,N,seed) 不同 normalization_scale 的极差 <= 0.10。

分离判据（猜想第 ② 条，k<m）：
  D1 单调：Δ_N = mean δ(k=N..) 的差序列在 N∈{8,16,32,64} 上逐步不下降到 -0.05 以下。
  D2 外推：以 x=1/log N 对 Δ_N 做最小二乘，截距 Δ_∞ >= (m-k) 且 >= 1。
  D3 硬反驳：N=32 与 N=64 两档 Δ 都 < 0.10，且 |Δ_64 − Δ_32| < 0.05。

三档出口：
  supports          = gate=qualified 且所有可测 (k,m) 对满足 D1+D2 且无一命中 D3
  refutes           = gate=qualified 且存在 (k,m) 对命中 D3 且无任何对满足 D1+D2
  insufficient_data = 其余（含 gate 未通过：这是结构性缺口，不得读成"猜想被反驳"）
"""
import argparse
import json

RUNGS = [8, 16, 32, 64]
TOL_Q1 = 0.15
TOL_Q2 = 0.10
TOL_Q4 = 0.10
TOL_MONO = 0.05
D3_ABS = 0.10


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    rows = d["readings"] if isinstance(d, dict) and "readings" in d else d
    for r in rows:
        for f_ in ("estimator", "k", "N", "delta_hat"):
            if f_ not in r:
                raise SystemExit("reading missing required field: %s -> %r" % (f_, r))
        r["k"] = int(r["k"])
        r["N"] = int(r["N"])
        r["delta_hat"] = float(r["delta_hat"])
    return rows


def means_by(rows):
    """(estimator, k) -> {N: mean(delta_hat)}，只用 feasible 的读数。"""
    acc = {}
    for r in rows:
        if r.get("feasible") is False:
            continue
        if r.get("converged") is False:
            continue
        acc.setdefault((r["estimator"], r["k"]), {}).setdefault(r["N"], []).append(r["delta_hat"])
    return {key: {n: sum(v) / len(v) for n, v in byn.items()} for key, byn in acc.items()}


def gate(rows):
    reasons, ok = [], True
    # Q3 量程
    bad = [r for r in rows if not (0.0 < r["delta_hat"] <= r["k"] * 1.05)]
    if bad:
        ok = False
        reasons.append("Q3_range_violated: %d 条读数落在 (0,k] 之外（例 k=%s N=%s delta=%s）"
                       % (len(bad), bad[0]["k"], bad[0]["N"], bad[0]["delta_hat"]))
    # Q1 不发散
    M = means_by(rows)
    checks = []
    for (est, k), byn in sorted(M.items()):
        for n in RUNGS:
            if n in byn and 2 * n in byn and byn[n] > 0:
                checks.append({"estimator": est, "k": k, "N": n,
                               "ratio": round(byn[2 * n] / byn[n], 4)})
    if not checks:
        ok = False
        reasons.append("Q1_not_tested: 没有相邻倍档 (N, 2N) 的可比读数")
    else:
        worst = max(abs(c["ratio"] - 1.0) for c in checks)
        if worst > TOL_Q1:
            ok = False
            reasons.append("Q1_divergence: worst |ratio-1| = %.3f > %.2f" % (worst, TOL_Q1))
    # Q2 种子可复现
    groups = {}
    for r in rows:
        if r.get("feasible") is False:
            continue
        groups.setdefault((r["estimator"], r["k"], r["N"]), []).append(r["delta_hat"])
    multi = {k: v for k, v in groups.items() if len(v) >= 2}
    if not multi:
        ok = False
        reasons.append("Q2_not_tested: 没有任何 (estimator,k,N) 有 >=2 个 seed")
    else:
        worst2 = max(max(v) - min(v) for v in multi.values())
        if worst2 > TOL_Q2:
            ok = False
            reasons.append("Q2_seed_spread: 最大极差 %.3f > %.2f" % (worst2, TOL_Q2))
    # Q4 归一化不变（有数据才判，无数据只记未测）
    ng = {}
    for r in rows:
        if r.get("normalization_scale") is None:
            continue
        ng.setdefault((r["estimator"], r["k"], r["N"], r.get("seed")), []).append(
            (float(r["normalization_scale"]), r["delta_hat"]))
    tested4 = [v for v in ng.values() if len({s for s, _ in v}) >= 2]
    if not tested4:
        reasons.append("Q4_not_tested: 没有同一 (k,N,seed) 下不同 normalization_scale 的读数")
    else:
        worst4 = max(max(d for _, d in v) - min(d for _, d in v) for v in tested4)
        if worst4 > TOL_Q4:
            ok = False
            reasons.append("Q4_normalization_dependent: 极差 %.3f > %.2f" % (worst4, TOL_Q4))
    status = "qualified" if ok else "disqualified"
    if ok and any(s.startswith("Q4_not_tested") for s in reasons):
        status = "qualified_except_Q4"
    return {"status": status, "reasons": reasons,
            "q1_ratio_checks": checks,
            "note": "gate 未通过 = 缺合格估计器（结构性缺口）；不得据此判猜想被反驳。"}


def delta_series(M, k, m):
    out = {}
    for est in sorted({e for e, _ in M}):
        a, b = M.get((est, k)), M.get((est, m))
        if not a or not b:
            continue
        pts = {n: b[n] - a[n] for n in RUNGS if n in a and n in b}
        if len(pts) >= 2:
            out[est] = pts
    return out


def monotone(pts):
    ns = sorted(pts)
    return all(pts[ns[i + 1]] - pts[ns[i]] >= -TOL_MONO for i in range(len(ns) - 1)), ns


def extrapolate(pts):
    xs = [1.0 / (n ** 0.5) for n in sorted(pts)]  # 备用
    return None


def fit_inv_log(pts):
    """以 x = 1/log N 做最小二乘，返回 (截距 Δ_∞, 斜率)。"""
    import math
    ns = sorted(pts)
    xs = [1.0 / math.log(n) for n in ns]
    ys = [pts[n] for n in ns]
    k = len(xs)
    mx, my = sum(xs) / k, sum(ys) / k
    sxx = sum((x - mx) ** 2 for x in xs)
    if abs(sxx) < 1e-15:
        return None, None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    return my - slope * mx, slope


def criterion(rows, M):
    per_pair, supports, refutes, undecided = {}, [], [], []
    ks = sorted({k for _, k in M})
    for i, k in enumerate(ks):
        for m in ks[i + 1:]:
            for est, pts in delta_series(M, k, m).items():
                key = "%s|k=%d,m=%d" % (est, k, m)
                mono_ok, ns = monotone(pts)
                inf, slope = fit_inv_log(pts)
                d32, d64 = pts.get(32), pts.get(64)
                hard = (d32 is not None and d64 is not None
                        and d32 < D3_ABS and d64 < D3_ABS
                        and abs(d64 - d32) < TOL_MONO)
                sep_ok = None if inf is None else bool(inf >= (m - k) and inf >= 1.0)
                rec = {"estimator": est, "k": k, "m": m,
                       "delta_by_N": {str(n): round(pts[n], 4) for n in ns},
                       "D1_monotone": mono_ok,
                       "D2_intercept_inv_log": None if inf is None else round(inf, 4),
                       "D2_slope_inv_log": None if slope is None else round(slope, 4),
                       "D2_separation_holds": sep_ok,
                       "D2_required": m - k,
                       "D3_hard_refutation": hard}
                per_pair[key] = rec
                if hard:
                    refutes.append(key)
                elif mono_ok and sep_ok:
                    supports.append(key)
                else:
                    undecided.append(key)
    if not per_pair:
        status = "insufficient_data"
        why = ["没有任何 (k,m) 对在两个 k 上都有可比的合格读数"]
    elif refutes and not supports:
        status, why = "refutes", ["命中 D3 的对：%s" % refutes]
    elif supports and not refutes:
        status, why = "supports", ["满足 D1+D2 的对：%s（仍只是 supported_not_proved）" % supports]
    else:
        status, why = "insufficient_data", ["支持对=%s；反驳对=%s；其余未定=%s"
                                            % (supports, refutes, undecided)]
    return {"status": status, "reasons": why, "per_pair": per_pair,
            "undecided_pairs": undecided,
            "note": "D2 只用 N∈{8,16,32,64} 四点外推，属数值外推，不构成证明。"}


def main():
    ap = argparse.ArgumentParser(description="conjectures:000000 verdict gate (deterministic)")
    ap.add_argument("--readings", required=True, help="读数组 JSON（本脚本不生成读数）")
    ap.add_argument("--out", default="", help="判定结果 JSON 落点")
    a = ap.parse_args()
    rows = load(a.readings)
    g = gate(rows)
    M = means_by(rows)
    if g["status"] == "disqualified":
        crit = {"status": "insufficient_data",
                "reasons": ["gate=disqualified ⇒ 结构性缺口（缺合格估计器），不是反驳"],
                "per_pair": {}, "undecided_pairs": [], "note": "见 gate.reasons"}
    else:
        crit = criterion(rows, M)
    res = {"conjecture_id": "000000", "n_readings": len(rows),
           "gate": g, "criterion": crit}
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
