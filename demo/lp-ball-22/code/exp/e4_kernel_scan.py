#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E 任务 4：核尺度扫描。

DeltaK(t) = int_0^{2pi} exp(-t * ||e_D(th)||_p^p) dth - int_0^{2pi} exp(-t * ||e_F(th)||_p^p) dth

e_D(th) = cos th * u + sin th * v,   u = (1,-1,0)/sqrt2,  v = (1,1,-2)/sqrt6
   => ||e_D||_p^p = (2/sqrt6)^p * (|cos(th-pi/6)|^p + |cos(th+pi/6)|^p + |sin th|^p)
                  = (2/3)^{p/2} * S_D(th)           （F 稿 000002 第 4-5 步的同一组分量）
e_F(th) = cos th * w1 + sin th * w2,  w1 = (1,-1,0)/sqrt2,  w2 = (0,0,1)
   => ||e_F||_p^p = 2^{1-p/2} |cos th|^p + |sin th|^p = S_F(th)

（派活文本里「下面 params 的显式表达式」未随消息到达：本脚本按上面这同一组基向量把
 e_D、e_F 显式写出，口径与 exp:000014 / exp:000015 里核过的 A_diag、A_face 完全一致
 —— 两条曲线在 t 上的积分分别对应两个方向的截面问题的核。）

求积：逐段 tanh-sinh(DE)。断点取 S_D 三个绝对值的零点 {0,pi/3,2pi/3,pi,4pi/3,5pi/3,2pi}
与 S_F 的 cos/sin 零点 {0,pi/2,pi,3pi/2,2pi}；被积函数是指数光滑的，DE 在断点上达机器精度。
节点与被积的 ||e||^p 值只算一次，之后对 200 个 t 只做 exp（做法写进 scaling/design 口径）。

判据（脚本硬编码、由脚本判）：
  对每个 p in {2.5,3,4,6,10}，在 t in [1e-3,1e3] 的 200 点对数网格上数 DeltaK 的符号变化次数；
  全部 p 的变号次数 <= 1 => result = supports；任一 p 出现 >= 2 次变号 => result = refutes，
  并把那段区间（p, t1, t2, DeltaK 值）作为 counterexample 打出来。
自检：t=0 时两条积分都必须是 2pi（DE 节点权重之和），偏差 > 1e-10 则报告但照实记。
"""
import json
import math
import time

PI = math.pi


def tanhsinh_nodes(a, b, h=0.04, tmax=6.0):
    """返回 [(x, w)]，使 int_a^b f ≈ sum_i w_i f(x_i)（标准双指数公式）。"""
    if b <= a:
        return []
    c = 0.5 * (b - a)
    d = 0.5 * (a + b)
    out = []
    n = int(tmax / h)
    for k in range(-n, n + 1):
        t = k * h
        u = (PI / 2.0) * math.sinh(t)
        if u > 400.0 or u < -400.0:
            continue
        x = math.tanh(u)
        if x >= 1.0 or x <= -1.0:
            continue
        ch = math.cosh(u)
        w = (PI / 2.0) * math.cosh(t) / (ch * ch)
        out.append((d + c * x, w * c * h))
    return out


BRK_D = [0.0, PI / 3.0, 2.0 * PI / 3.0, PI, 4.0 * PI / 3.0, 5.0 * PI / 3.0, 2.0 * PI]
BRK_F = [0.0, PI / 2.0, PI, 3.0 * PI / 2.0, 2.0 * PI]


def quad_plan(breaks):
    nodes = []
    for i in range(len(breaks) - 1):
        nodes.extend(tanhsinh_nodes(breaks[i], breaks[i + 1]))
    return nodes


def uD(p, th):
    s = (abs(math.cos(th - PI / 6.0)) ** p
         + abs(math.cos(th + PI / 6.0)) ** p
         + abs(math.sin(th)) ** p)
    return (2.0 / 3.0) ** (p / 2.0) * s


def uF(p, th):
    return 2.0 ** (1.0 - p / 2.0) * abs(math.cos(th)) ** p + abs(math.sin(th)) ** p


def build(p):
    nd = [(w, uD(p, th)) for th, w in quad_plan(BRK_D)]
    nf = [(w, uF(p, th)) for th, w in quad_plan(BRK_F)]
    return nd, nf


def kd_and_kf(t, nd, nf):
    kd = 0.0
    for w, u in nd:
        kd += w * math.exp(-t * u)
    kf = 0.0
    for w, u in nf:
        kf += w * math.exp(-t * u)
    return kd, kf


def dK(t, nd, nf):
    kd, kf = kd_and_kf(t, nd, nf)
    return kd - kf


def sign(x, eps):
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def refine(nd, nf, t1, t2, eps):
    """在 log t 上二分到相对宽度 1e-12。"""
    l1, l2 = math.log(t1), math.log(t2)
    s1 = sign(dK(t1, nd, nf), eps)
    for _ in range(60):
        lm = 0.5 * (l1 + l2)
        tm = math.exp(lm)
        sm = sign(dK(tm, nd, nf), eps)
        if sm == 0:
            return tm
        if sm == s1:
            l1, t1 = lm, tm
        else:
            l2, t2 = lm, tm
    return math.exp(0.5 * (l1 + l2))


def main():
    t0 = time.time()
    ps = [2.5, 3.0, 4.0, 6.0, 10.0]
    npts = 200
    lt0, lt1 = -3.0, 3.0
    ts = [10.0 ** (lt0 + (lt1 - lt0) * i / (npts - 1)) for i in range(npts)]

    rows = []
    any_multi = False
    any_ambig = False
    worst_weight_err = 0.0
    counterexample = None

    for p in ps:
        tp = time.time()
        nd, nf = build(p)
        sumwd = sum(w for w, u in nd)
        sumwf = sum(w for w, u in nf)
        werr = max(abs(sumwd - 2 * PI), abs(sumwf - 2 * PI)) / (2 * PI)
        worst_weight_err = max(worst_weight_err, werr)

        # 总体一阶量：d/dt DeltaK|_{t=0} = int uF - int uD
        m1d = sum(w * u for w, u in nd)
        m1f = sum(w * u for w, u in nf)
        slope0 = m1f - m1d

        vals = []
        for t in ts:
            vals.append(dK(t, nd, nf))
        scale = max(abs(v) for v in vals)
        eps = 1e-13 * max(scale, 1e-30)

        svals = [sign(v, eps) for v in vals]
        changes = []
        for i in range(len(ts) - 1):
            a, b = svals[i], svals[i + 1]
            if a == 0 or b == 0:
                continue
            if a != b:
                changes.append(refine(nd, nf, ts[i], ts[i + 1], eps))
        nz = [s for s in svals if s != 0]
        ambiguous = len(nz) < len(svals)

        snap = {}
        for tt in (1e-3, 1e-1, 1.0, 1e1, 1e3):
            snap["%.0e" % tt] = dK(tt, nd, nf)

        row = {
            "p": p,
            "sign_at_t_min": svals[0],
            "sign_at_t_max": svals[-1],
            "DeltaK_t1e-3": vals[0],
            "DeltaK_t1e3": vals[-1],
            "n_sign_changes": len(changes),
            "t_cross": (changes[0] if len(changes) == 1 else None),
            "t_cross_all": changes,
            "slope_at_0_dKdt": slope0,
            "max_abs_DeltaK": scale,
            "weight_selfcheck_rel_err": werr,
            "snapshot": snap,
            "sec": round(time.time() - tp, 3),
        }
        if len(changes) >= 2:
            any_multi = True
            i = 0
            for j in range(len(ts) - 1):
                if svals[j] != 0 and svals[j + 1] != 0 and svals[j] != svals[j + 1]:
                    if counterexample is None:
                        counterexample = {
                            "p": p, "t_lo": ts[j], "t_hi": ts[j + 1],
                            "DeltaK_t_lo": vals[j], "DeltaK_t_hi": vals[j + 1],
                            "sign_pattern": "%+d -> %+d" % (svals[j], svals[j + 1]),
                        }
                    i += 1
        if ambiguous:
            any_ambig = True
        rows.append(row)
        print("PROGRESS: " + json.dumps(row))

    if any_multi:
        result = "refutes"
    elif any_ambig:
        result = "inconclusive"
    else:
        result = "supports"

    payload = {
        "result": result,
        "eD": "e_D(th)=cos th*(1,-1,0)/sqrt2 + sin th*(1,1,-2)/sqrt6 => ||e_D||_p^p=(2/3)^(p/2)*(|cos(th-pi/6)|^p+|cos(th+pi/6)|^p+|sin th|^p)",
        "eF": "e_F(th)=cos th*(1,-1,0)/sqrt2 + sin th*(0,0,1) => ||e_F||_p^p=2^(1-p/2)|cos th|^p+|sin th|^p",
        "bound": "p in {2.5,3,4,6,10}; t in [1e-3,1e3] (200 log-spaced points)",
        "strategy": "piecewise tanh-sinh(DE,h=0.04) nodes fixed once per p; ||e||^p values cached on nodes; DeltaK(t) evaluated by one exp pass per t; sign-change count + log-t bisection refinement",
        "tolerance_sign": "eps = 1e-13 * max|DeltaK| on grid",
        "worst_weight_selfcheck_rel_err": worst_weight_err,
        "counterexample": counterexample,
        "scaling": {"total_sec": round(time.time() - t0, 3),
                    "per_p_sec": [r["sec"] for r in rows],
                    "nodes_per_plan": [len(build(p)[0]) for p in ps[:1]]},
        "rows": rows,
    }
    print("REPRO_RESULT: " + json.dumps(payload))


if __name__ == "__main__":
    main()
