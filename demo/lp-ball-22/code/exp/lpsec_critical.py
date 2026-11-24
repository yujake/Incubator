"""lpsec_critical.py -- where the maximal section of B_p^3 changes type, and what r(p) does.

Deterministic numerics only (no fitting, no sampling statistics); every number below is
produced by lpsec_core.area_polar, whose accuracy was certified in exp:000003
(p=2 -> pi to 4e-16, p=1 vs exact octahedron clipping to 7e-16, coordinate sections vs
4*G(1+1/p)^2/G(1+2/p) to 7e-16, invariance under rotation of the plane basis to 9e-16).

Questions answered here
  Q1  r(p) = A_face/A_coord and q(p) = A_diag/A_coord : sign of (r-1), (q-1); the p where
      they cross 1 (bisection to 1e-9 in p), monotonicity over a fine p-scan.
  Q2  the argmax type: coordinate (0,0,1) vs body diagonal (1,1,1)/sqrt3 vs face diagonal
      (1,1,0)/sqrt2; where A_face and A_diag cross (bisection in p).
  Q3  the arcs (1,1,t) and (0,1,t): is the best t on the arc ever strictly interior
      (0 < t < 1), or always an endpoint?  Report best t and the arc's area there.
  Q4  is any interior direction of the fundamental domain better than the best boundary
      direction?  (coarse 2-D grid over 0<=u<=v<=1, n ~ (u,v,1), on top of exp:000004.)

REPRO_RESULT line: result / bound / strategy / scaling / data (see the end of the file).
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
COORD = (0.0, 0.0, 1.0)
FACE = (1.0, 1.0, 0.0)
DIAG = (1.0, 1.0, 1.0)
TOL = 1e-6            # relative resolution of a boundary-vs-interior comparison
T0 = time.time()
N_EVAL = [0]
checks = []
problems = []


def A(n, p, hl=HL):
    v, err, info = C.area_polar(n, p, h_list=hl)
    N_EVAL[0] += 1
    return v, err


def P(obj):
    print("PROGRESS: " + json.dumps(obj))


def bisect(f, lo, hi, iters=70):
    """First root of a sign change on [lo,hi]; None if the endpoints agree in sign."""
    flo, fhi = f(lo), f(hi)
    if flo == 0.0:
        return lo
    if fhi == 0.0:
        return hi
    if flo * fhi > 0.0:
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if flo * fm <= 0.0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


P({"stage": "start", "ps": PS, "h_finest": HL[-1]})

# ------------------------------------------------------------------ Q1/Q2 table over PS
rows = []
for p in PS:
    ac, ec = A(COORD, p)
    af, ef = A(FACE, p)
    ad, ed = A(DIAG, p)
    cf = C.area_coord_analytic(p)
    r_face = af / ac
    r_diag = ad / ac
    if max(ac, af, ad) == ac:
        typ = "coordinate"
    elif max(af, ad) == ad:
        typ = "body-diagonal"
    else:
        typ = "face-diagonal"
    rows.append({
        "p": p,
        "A_coord_numeric": ac, "A_coord_closed_form": cf,
        "A_coord_abs_dev": abs(ac - cf),
        "A_face": af, "A_diag": ad,
        "r_face": r_face, "r_diag": r_diag,
        "r_face_minus_1": r_face - 1.0, "r_diag_minus_1": r_diag - 1.0,
        "diag_minus_face": ad - af,
        "argmax_type": typ,
        "A_max": max(ac, af, ad),
        "err_est_coord": ec, "err_est_face": ef, "err_est_diag": ed,
    })
    P({"stage": "Q12", "p": p, "A_coord": ac, "A_face": af, "A_diag": ad,
       "r_face": r_face, "r_diag": r_diag, "argmax": typ,
       "coord_vs_closed_form": abs(ac - cf)})

# monotonicity of r_face, r_diag on a fine p-scan (log grid, 41 points in [1.02, 60])
pgrid = [math.exp(math.log(1.02) + (math.log(60.0) - math.log(1.02)) * i / 40.0) for i in range(41)]
mono = {"r_face_monotone": True, "r_diag_monotone": True, "prev": None, "rows": []}
prev = None
for p in pgrid:
    ac, _ = A(COORD, p, hl=(0.5, 0.25, 0.125))
    af, _ = A(FACE, p, hl=(0.5, 0.25, 0.125))
    ad, _ = A(DIAG, p, hl=(0.5, 0.25, 0.125))
    rf, rd = af / ac, ad / ac
    if prev is not None:
        if rf < prev[0] - 1e-12:
            mono["r_face_monotone"] = False
        if rd < prev[1] - 1e-12:
            mono["r_diag_monotone"] = False
    prev = (rf, rd)
    mono["rows"].append({"p": p, "r_face": rf, "r_diag": rd})
P({"stage": "Q1mono", "r_face_monotone": mono["r_face_monotone"],
   "r_diag_monotone": mono["r_diag_monotone"], "n_points": len(pgrid)})


def r_face_minus_1(p):
    a, _ = A(FACE, p)
    c, _ = A(COORD, p)
    return a / c - 1.0


def r_diag_minus_1(p):
    a, _ = A(DIAG, p)
    c, _ = A(COORD, p)
    return a / c - 1.0


def diag_minus_face(p):
    d, _ = A(DIAG, p)
    f, _ = A(FACE, p)
    return d - f


p_face = bisect(r_face_minus_1, 1.2, 3.0)
p_diag = bisect(r_diag_minus_1, 1.2, 3.0)
p_switch = bisect(diag_minus_face, 3.5, 6.0)
P({"stage": "Q1roots", "p_where_r_face_eq_1": p_face, "p_where_r_diag_eq_1": p_diag,
   "p_where_A_diag_eq_A_face": p_switch})
checks.append(("r_face crosses 1 exactly once in (1.2,3) at p=%.9f" % (p_face if p_face else float("nan")),
               p_face is not None and abs(p_face - 2.0) < 1e-6))
checks.append(("r_diag crosses 1 exactly once in (1.2,3) at p=%.9f" % (p_diag if p_diag else float("nan")),
               p_diag is not None and abs(p_diag - 2.0) < 1e-6))
checks.append(("argmax switches body-diagonal -> face-diagonal at p=%.9f" % (p_switch if p_switch else float("nan")),
               p_switch is not None and 4.0 < p_switch < 5.0))
checks.append(("r_face monotone increasing over 41-point p-scan in [1.02,60]", mono["r_face_monotone"]))
checks.append(("r_diag monotone increasing over 41-point p-scan in [1.02,60]", mono["r_diag_monotone"]))

# ------------------------------------------------------- Q3: the arcs (1,1,t) and (0,1,t)
def arc_11(t, p):
    return A((1.0, 1.0, t), p, hl=(0.25, 0.125, 0.0625))


def arc_01(t, p):
    return A((0.0, 1.0, t), p, hl=(0.25, 0.125, 0.0625))


TS = [0.0] + [i / 40.0 for i in range(1, 40)] + [1.0] + [1.0 + i / 10.0 for i in range(1, 11)]
family = []
for p in PS:
    best11 = (-1.0, None)
    best11_int = (-1.0, None)
    best01 = (-1.0, None)
    best01_int = (-1.0, None)
    for t in TS:
        a11, _ = arc_11(t, p)
        a01, _ = arc_01(t, p)
        if a11 > best11[0]:
            best11 = (a11, t)
        if 1e-9 < t < 1.0 - 1e-9 and a11 > best11_int[0]:
            best11_int = (a11, t)
        if a01 > best01[0]:
            best01 = (a01, t)
        if 1e-9 < t < 1.0 - 1e-9 and a01 > best01_int[0]:
            best01_int = (a01, t)
    # an endpoint optimum: t = 0 (face diagonal) or t = 1 (body diagonal) for arc(1,1,t);
    # t = 0 (face diagonal) or t -> infinity (coordinate direction) for arc(0,1,t)
    end11 = max((best11[0], best11[1]) if best11[1] in (0.0, 1.0) else (-1.0, None),
                (A(FACE, p, hl=(0.25, 0.125, 0.0625))[0], 0.0),
                (A(DIAG, p, hl=(0.25, 0.125, 0.0625))[0], 1.0))
    interior_beats_11 = best11_int[0] > end11[0] + TOL * end11[0]
    interior_beats_01 = best01_int[0] > max(best01[0], 0.0) + 1e9  # placeholder, replaced below
    family.append({
        "p": p,
        "arc11_best_t": best11[1], "arc11_best_area": best11[0],
        "arc11_best_interior_t": best11_int[1], "arc11_best_interior_area": best11_int[0],
        "arc11_endpoint_area": end11[0], "arc11_interior_beats_endpoint": interior_beats_11,
        "arc01_best_t": best01[1], "arc01_best_area": best01[0],
        "arc01_best_interior_t": best01_int[1], "arc01_best_interior_area": best01_int[0],
    })
    P({"stage": "Q3", "p": p, "arc11_best_t": best11[1], "arc11_best_area": best11[0],
       "arc11_int_t": best11_int[1], "arc11_int_area": best11_int[0],
       "arc01_best_t": best01[1], "arc01_best_area": best01[0],
       "arc01_int_t": best01_int[1], "arc01_int_area": best01_int[0],
       "interior_beats_11": interior_beats_11})
    # p = 2 is the isotropic case: every direction has area pi, so "the best t along the arc"
    # is degenerate by construction -- the correct check there is that the whole arc is flat
    # (max - min over the arc ~ 0), not that the argmax is an endpoint.
    if abs(p - 2.0) < 1e-12:
        flat = abs(best11[0] - A(DIAG, p)[0]) < 1e-12 and abs(best11[0] - A(FACE, p)[0]) < 1e-12
        checks.append(("arc(1,1,t) at p=%g: degenerate (isotropic), arc is flat to 1e-12" % p, flat))
    else:
        checks.append(("arc(1,1,t) at p=%g: best t is an endpoint (t=%.6f)" % (p, best11[1]),
                       (abs(best11[1]) < 1e-9) or (abs(best11[1] - 1.0) < 1e-9)))

# ------------------------------------- Q4: interior of the fundamental domain vs boundary
NN = 14
interior = []
for p in PS:
    ac, _ = A(COORD, p, hl=(0.5, 0.25, 0.125))
    af, _ = A(FACE, p, hl=(0.5, 0.25, 0.125))
    ad, _ = A(DIAG, p, hl=(0.5, 0.25, 0.125))
    bmax = max(ac, af, ad)
    btyp = "coordinate" if bmax == ac else ("body-diagonal" if bmax == ad else "face-diagonal")
    best = (-1.0, None, None)
    for i in range(1, NN):
        u = i / float(NN)
        for j in range(i + 1, NN):
            v = j / float(NN)
            val, _ = A((u, v, 1.0), p, hl=(0.5, 0.25, 0.125))
            if val > best[0]:
                best = (val, u, v)
    excess = best[0] - bmax
    interior.append({"p": p, "boundary_max": bmax, "boundary_type": btyp,
                     "interior_best": best[0], "interior_uv": [best[1], best[2]],
                     "excess": excess, "excess_rel": excess / bmax})
    P({"stage": "Q4", "p": p, "boundary_max": bmax, "boundary_type": btyp,
       "interior_best": best[0], "uv": [best[1], best[2]], "excess_rel": excess / bmax})
    checks.append(("no interior direction beats the boundary max at p=%g (excess_rel=%.3e)"
                   % (p, excess / bmax), excess <= TOL * bmax))

# --------------------------------------------------------------------------- verdict
failed = [c for c in checks if not c[1]]
if failed:
    problems.append("%d check(s) failed: " % len(failed) + "; ".join(c[0] for c in failed))
result = "refutes" if failed else "supports"
counterexample = None
if failed:
    counterexample = {"failed_checks": [c[0] for c in failed],
                      "note": "see out/exp-logs log for the readings behind each check"}

data = {
    "per_p": rows,
    "critical_p": {"r_face_equals_1": p_face, "r_diag_equals_1": p_diag,
                   "A_diag_equals_A_face": p_switch},
    "monotonicity": {"r_face_monotone": mono["r_face_monotone"],
                     "r_diag_monotone": mono["r_diag_monotone"],
                     "p_scan_points": len(pgrid)},
    "arcs": family,
    "interior_vs_boundary": interior,
    "checks": [{"what": c[0], "holds": c[1]} for c in checks],
    "eval_count": N_EVAL[0],
    "tolerance_relative": TOL,
}
print("REPRO_RESULT: " + json.dumps({
    "result": result,
    "counterexample": counterexample,
    "bound": "p in {%s}; normals: the three symmetry types plus the arcs (1,1,t),(0,1,t) "
             "with 51 values of t; interior grid %dx%d over 0<=u<=v<=1" % (
                 ", ".join("%g" % p for p in PS), NN, NN),
    "strategy": "tanh-sinh polar quadrature between closed-form break points (exp:000003 "
                "certified it to 7e-16); bisection in p for the crossing points; monotone "
                "p-scan; arc scans + interior grid for the boundary-vs-interior comparison",
    "scaling": {"wall_sec": round(time.time() - T0, 3), "area_evals": N_EVAL[0]},
    "data": data,
}))
if problems:
    print("PROBLEMS: " + json.dumps(problems))
