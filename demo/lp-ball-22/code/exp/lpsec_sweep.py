"""lpsec_sweep.py -- maximal central sections of B_p^3 (deterministic numeric sweep).

CLAIM UNDER TEST (refutation-first design)
  C1  For every p in PS the maximal area of a central section of B_p^3 is attained on the
      boundary of the fundamental domain 0 <= a <= b <= c of sorted |n_i|, i.e. at a
      coordinate direction (0,0,1), a face diagonal (1,1,0)/sqrt2, a body diagonal
      (1,1,1)/sqrt3, or on one of the two arcs (1,1,t) / (0,1,t) with t in [0,inf].
      REFUTED iff some strictly interior direction beats every boundary direction by more
      than TOL_REL (relative); then that (p, n, area, boundary max) is the counterexample.
  C2  r(p) = A_diag/A_coord changes sign of (r - 1) at p = 2:  r < 1 for p < 2, r > 1 for p > 2.

NUMBERS
  A_p(n) = (1/2) int_0^{2pi} ||cos(psi) u + sin(psi) v||_p^{-2} dpsi,  (u,v) an orthonormal
  basis of n^perp, evaluated by tanh-sinh panels between ALL closed-form break points
  (component vanishing, component coincidence) -- see lpsec_core.  The kernel is checked
  against analytic anchors in exp:000003 (lpsec_validate.py): p=2 -> pi, p=1 vs exact
  octahedron clipping, p=1000 vs the exact cube values 4 / 3sqrt3 / 4sqrt2, coordinate
  section vs 4*G(1+1/p)^2/G(1+2/p) to 1e-15.

OUTPUT
  one PROGRESS line per p, one REPRO_RESULT line at the end.
"""

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lpsec_core as C

PS = [1.05, 1.1, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 8.0, 16.0, 1000.0]
HL = (0.25, 0.125, 0.0625, 0.03125)
HL_FINE = (0.125, 0.0625, 0.03125, 0.015625)
TOL_REL = 3e-7
NGRID = 20
NSTART = 3
ROUNDS = 6
FAM = 80
T0 = time.time()
NEVAL = [0]


def A(n, p, hl=HL):
    a, e, info = C.area_polar(n, p, h_list=hl)
    NEVAL[0] += 1
    return a, e


def nfun(u, v):
    return (float(u), float(v), 1.0)


def cls_of(n):
    v = sorted(abs(float(x)) for x in n)
    s = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if s == 0.0:
        raise ValueError("zero normal")
    return [v[0] / s, v[1] / s, v[2] / s]


def classify(c):
    if c[2] > 1.0 - 1e-6:
        return "coordinate-type", "e3"
    if c[0] < 1e-6 and abs(c[1] - c[2]) < 1e-6:
        return "face-diagonal-type", "(1,1,0)/sqrt2"
    if abs(c[0] - c[2]) < 1e-6:
        return "body-diagonal-type", "(1,1,1)/sqrt3"
    return "intermediate", ""


def grid_scan(p):
    rows = []
    for i in range(NGRID + 1):
        u = i / float(NGRID)
        for j in range(i, NGRID + 1):
            v = j / float(NGRID)
            a, _ = A(nfun(u, v), p)
            rows.append((a, u, v))
    rows.sort(key=lambda r: -r[0])
    return rows


def refine(p, u0, v0, interior_only):
    h = 1.0 / NGRID
    s1 = 2.0 * h / 3.0
    u, v = u0, v0
    best, _ = A(nfun(u, v), p)
    for r in range(ROUNDS):
        s = s1 / (4.0 ** r)
        for i in range(-3, 4):
            for j in range(-3, 4):
                if i == 0 and j == 0:
                    continue
                uu = u + i * s
                vv = v + j * s
                if uu < 0.0 or vv > 1.0 or uu > vv:
                    continue
                if interior_only and not (uu > 1e-9 and vv < 1.0 - 1e-9 and uu < vv - 1e-9):
                    continue
                a, _ = A(nfun(uu, vv), p)
                if a > best:
                    best, u, v = a, uu, vv
    return best, u, v


def dir_of_family(kind, t):
    if t is None or (isinstance(t, float) and math.isinf(t)):
        return (0.0, 0.0, 1.0)
    if kind == "11":
        return (1.0, 1.0, float(t))
    return (0.0, 1.0, float(t))


def fam_scan(p, kind):
    """scan t = w/(1-w), w in [0,1]; w=1 is the t=infinity end (the coordinate axis)."""
    ws = [i / float(FAM) for i in range(FAM + 1)]

    def area_at_w(w):
        t = None if w >= 1.0 else w / (1.0 - w)
        return A(dir_of_family(kind, t), p)[0]

    vals = [(area_at_w(w), w) for w in ws]
    best = max(vals)
    k = vals.index(best)
    lo = ws[max(0, k - 1)]
    hi = ws[min(len(ws) - 1, k + 1)]
    if hi - lo <= 1e-14:
        tbest = None if best[1] >= 1.0 else best[1] / (1.0 - best[1])
        return best[0], best[1], tbest
    g = (math.sqrt(5.0) - 1.0) / 2.0
    a1, b1 = lo, hi
    c1 = b1 - g * (b1 - a1)
    c2 = a1 + g * (b1 - a1)
    f1, f2 = area_at_w(c1), area_at_w(c2)
    for _ in range(70):
        if f1 < f2:
            a1, c1, f1 = c1, c2, f2
            c2 = a1 + g * (b1 - a1)
            f2 = area_at_w(c2)
        else:
            b1, c2, f2 = c2, c1, f1
            c1 = b1 - g * (b1 - a1)
            f1 = area_at_w(c1)
    wg = 0.5 * (a1 + b1)
    cands = [(best[0], best[1]), (f1, c1), (f2, c2), (max(f1, f2), wg)]
    abest, wbest = max(cands)
    tbest = None if wbest >= 1.0 - 1e-15 else wbest / (1.0 - wbest)
    return abest, wbest, tbest


def analyse(p):
    t_start = time.time()
    rows = grid_scan(p)
    best_all, ua, va = rows[0]
    for (a, u, v) in rows[:NSTART]:
        b, uu, vv = refine(p, u, v, False)
        if b > best_all:
            best_all, ua, va = b, uu, vv

    irows = [r for r in rows if r[1] > 1e-9 and r[2] < 1.0 - 1e-9 and r[1] < r[2] - 1e-9]
    best_in, ui, vi = -1.0, None, None
    for (a, u, v) in irows[:NSTART]:
        b, uu, vv = refine(p, u, v, True)
        if b > best_in:
            best_in, ui, vi = b, uu, vv

    a_coord, _ = A((0.0, 0.0, 1.0), p)
    a_coord_cf = C.area_coord_analytic(p)
    a_face, _ = A((0.0, 1.0, 1.0), p)
    a_diag, _ = A((1.0, 1.0, 1.0), p)
    a_f11, w11, t11 = fam_scan(p, "11")
    a_f01, w01, t01 = fam_scan(p, "01")
    boundary_max = max(a_coord, a_face, a_diag, a_f11, a_f01)

    n_in = nfun(ui, vi) if ui is not None else (0.0, 0.0, 1.0)
    cands = [
        (a_coord, "vertex(0,0,1)", (0.0, 0.0, 1.0)),
        (a_face, "vertex(0,1,1)", (0.0, 1.0, 1.0)),
        (a_diag, "vertex(1,1,1)", (1.0, 1.0, 1.0)),
        (a_f11, "arc(1,1,t)", dir_of_family("11", t11)),
        (a_f01, "arc(0,1,t)", dir_of_family("01", t01)),
        (best_all, "2D-closed-refine", nfun(ua, va)),
        (best_in, "2D-interior-refine", n_in),
    ]
    a_max, lab, n_of_max = max(cands, key=lambda z: z[0])
    cls = cls_of(n_of_max)
    famtype, special = classify(cls)

    a_max_fine, e_max_fine = A(n_of_max, p, HL_FINE)
    a_coord_fine, _ = A((0.0, 0.0, 1.0), p, HL_FINE)
    a_face_fine, _ = A((0.0, 1.0, 1.0), p, HL_FINE)
    a_diag_fine, _ = A((1.0, 1.0, 1.0), p, HL_FINE)

    specials = [a_coord, a_face, a_diag, a_f11, a_f01]
    degenerate = (max(specials) - min(specials)) < 1e-9 * max(specials)
    interior_excess = (best_in - boundary_max) if best_in > 0.0 else 0.0
    tol_abs = TOL_REL * max(1.0, a_max)
    rec = {
        "p": p,
        "A_max": a_max_fine,
        "A_max_quad": a_max,
        "A_max_err_est": e_max_fine,
        "argmax_from": lab,
        "argmax_component": [round(float(x), 9) for x in n_of_max],
        "argmax_class_sorted_abs": [round(x, 9) for x in cls],
        "argmax_type": famtype,
        "argmax_special": special,
        "argmax_uv": [ua, va],
        "A_coord_numeric": a_coord_fine,
        "A_coord_closed_form": a_coord_cf,
        "A_face": a_face_fine,
        "A_diag": a_diag_fine,
        "r_diag": a_diag_fine / a_coord_cf,
        "r_face": a_face_fine / a_coord_cf,
        "best_t_family_11": t11,
        "A_family_11": a_f11,
        "best_t_family_01": t01,
        "A_family_01": a_f01,
        "interior_best": best_in,
        "interior_uv": [ui, vi] if ui is not None else None,
        "interior_excess": interior_excess,
        "boundary_max": boundary_max,
        "tol_abs": tol_abs,
        "all_directions_equal": degenerate,
        "sec": round(time.time() - t_start, 2),
    }
    print("PROGRESS: " + json.dumps(rec, sort_keys=True))
    return rec, (interior_excess > tol_abs)


def r_minus_one(p, kind):
    ac = C.area_coord_analytic(p)
    n = (1.0, 1.0, 1.0) if kind == "diag" else (0.0, 1.0, 1.0)
    return A(n, p)[0] / ac - 1.0


def crossings(kind):
    table = []
    prev = None
    brackets = []
    for p in PS:
        v = r_minus_one(p, kind)
        table.append((p, v))
        if prev is not None and prev[1] * v <= 0.0:
            brackets.append((prev[0], p))
        prev = (p, v)
    roots = []
    for (lo, hi) in brackets:
        a, b = lo, hi
        flo = r_minus_one(a, kind)
        for _ in range(80):
            m = 0.5 * (a + b)
            fm = r_minus_one(m, kind)
            if flo * fm <= 0.0:
                b = m
            else:
                a, flo = m, fm
        roots.append(0.5 * (a + b))
    return [round(x, 9) for x in roots], [(p, round(v, 12)) for (p, v) in table]


def main():
    print("PROGRESS: " + json.dumps({"stage": "start", "ps": PS, "ngrid": NGRID,
                                     "rounds": ROUNDS, "fam": FAM}))
    results = []
    refuted = []
    for p in PS:
        rec, bad = analyse(p)
        results.append(rec)
        if bad:
            refuted.append({"p": p, "n": rec["argmax_component"],
                            "interior_uv": rec["interior_uv"],
                            "interior_area": rec["interior_best"],
                            "boundary_max": rec["boundary_max"],
                            "excess": rec["interior_excess"]})

    roots_diag, tbl_diag = crossings("diag")
    roots_face, tbl_face = crossings("face")

    c2_ok = bool(roots_diag) and all(abs(x - 2.0) < 0.05 for x in roots_diag)
    sign_ok = True
    for (p, v) in tbl_diag:
        if p < 2.0 - 1e-9 and v > 1e-9:
            sign_ok = False
        if p > 2.0 + 1e-9 and v < -1e-9:
            sign_ok = False
    c2_ok = c2_ok and sign_ok

    counter = None
    if refuted:
        res = "refutes"
        counter = refuted[0]
    elif not c2_ok:
        res = "refutes"
        bad_pair = None
        for (p, v) in tbl_diag:
            if (p < 2.0 and v > 0.0) or (p > 2.0 and v < 0.0):
                bad_pair = {"p": p, "r_diag_minus_one": v}
        counter = bad_pair if bad_pair else {"critical_p_diag": roots_diag}
    else:
        res = "supports"

    payload = {
        "result": res,
        "bound": "p in %s; normals: <=20x20 grid on the fundamental domain "
                 "0<=a<=b<=c (a,b,c = sorted |n_i|) + 6-round nested box refinement + "
                 "full arcs (1,1,t) and (0,1,t), t=w/(1-w) with a 1/80 grid + golden section"
                 % (PS,),
        "strategy": "signed-permutation reduction to the fundamental domain; 2D grid + "
                    "nested box refinement (global and interior-restricted); arc scans; "
                    "polar tanh-sinh quadrature with all closed-form break points; "
                    "coordinate section against the closed form 4G(1+1/p)^2/G(1+2/p)",
        "scaling": {
            "wall_sec": round(time.time() - T0, 2),
            "area_evaluations": NEVAL[0],
            "p_list": PS,
            "sec_per_p": [r["sec"] for r in results],
        },
        "counterexample": counter,
        "data": {
            "per_p": results,
            "r_diag_minus_one_table": tbl_diag,
            "r_face_minus_one_table": tbl_face,
            "critical_p_r_diag": roots_diag,
            "critical_p_r_face": roots_face,
            "interior_max_found": refuted,
            "c1_holds": not refuted,
            "c2_holds": c2_ok,
        },
    }
    print("REPRO_RESULT: " + json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
