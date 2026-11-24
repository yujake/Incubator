"""lpsec_arcs.py -- do intermediate directions (1,1,t), (0,1,t) ever beat the three vertices?

The symmetry group of B_p^3 (p != 2) is the hyperoctahedral group of signed coordinate
permutations (order 48), so the section area depends only on the sorted multiset of |n_i|.
Fundamental domain: 0 <= a <= b <= c.  Its boundary consists of

    face a = 0        : n propto (0,1,t),  t in [0,inf)   -- coordinate (0,1,0) at t=0,
                                                            coordinate (0,0,1) at t=inf,
                            face diagonal (0,1,1) at t=1
    face a = b        : n propto (1,1,t),  t in [1,inf)   -- body diagonal at t=1, (0,0,1) at t=inf
    face b = c        : n propto (1,1,t),  t in [0,1]     -- face diagonal at t=0, body diag at t=1

Hence the whole boundary is the two vertices e3 = (0,0,1), (1,1,0)/sqrt2 plus the single
arc family (1,1,t) with t in [0,inf) (which contains the body diagonal at t=1).

This script scans BOTH arcs on a log grid t in [1e-4, 1e4] (161 log points) plus t = 0, 1,
and the limit t -> inf, for every p in PS, and answers:

  * is the maximum on the arc attained at an endpoint / at t = 1, or at a strictly
    intermediate t ?
  * how much (relative) better is an intermediate point than the best of the three
    vertex directions?

`refutes` iff for some p some scanned arc point beats max(coord, face, diag) by more than
1e-9 relative.  The quadrature is lpsec_core.area_polar, certified in exp:000003 to
machine precision on p=2 / p=1 exact values and on the coordinate closed form.
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lpsec_core as C

PS = [1.05, 1.1, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 8.0, 16.0, 1000.0]
COORD = (0.0, 0.0, 1.0)
FACE = (1.0, 1.0, 0.0)
DIAG = (1.0, 1.0, 1.0)
HL = (0.5, 0.25, 0.125, 0.0625, 0.03125)
TOL_REL = 1e-9


def P(obj):
    print("PROGRESS: " + json.dumps(obj))


def A(v, p):
    return C.area_polar(v, p, h_list=HL)[0]


def tgrid():
    ts = {0.0, 1.0, 1e-4, 1e4}
    for i in range(161):
        ts.add(round(10.0 ** (-4.0 + 8.0 * i / 160.0), 12))
    return sorted(ts)


TS = tgrid()
t0 = time.time()
P({"stage": "start", "ps": PS, "n_t": len(TS), "t_range": [TS[0], TS[-1]],
   "grammar": "arc11: n=(1,1,t); arc01: n=(0,1,t); both normalised"})

rows = []
problems = []
for p in PS:
    ac = A(COORD, p)
    af = A(FACE, p)
    ad = A(DIAG, p)
    bmax = max(ac, af, ad)
    btyp = "coordinate" if bmax == ac else ("body-diagonal" if bmax == ad else "face-diagonal")

    best11 = (-1.0, None)
    best11_int = (-1.0, None)   # strictly interior t (0 < t < inf), excluding t = 0
    best01 = (-1.0, None)
    best01_int = (-1.0, None)
    for t in TS:
        a11 = A((1.0, 1.0, t), p)
        a01 = A((0.0, 1.0, t), p)
        if a11 > best11[0]:
            best11 = (a11, t)
        if t > 1e-9 and a11 > best11_int[0]:
            best11_int = (a11, t)
        if a01 > best01[0]:
            best01 = (a01, t)
        if t > 1e-9 and a01 > best01_int[0]:
            best01_int = (a01, t)

    arc_max = max(best11[0], best01[0], best11_int[0], best01_int[0])
    excess_rel = (arc_max - bmax) / bmax
    beats = arc_max > bmax * (1.0 + TOL_REL)
    if beats:
        problems.append("p=%g: an arc direction beats every vertex by %.3e relative"
                        % (p, excess_rel))
    # which arc point is the global maximum of the section over the scanned set
    cand = [("coordinate", ac, 0.0), ("face-diagonal", af, 0.0), ("body-diagonal", ad, 1.0),
            ("arc(1,1,t)", best11[0], best11[1]), ("arc(0,1,t)", best01[0], best01[1])]
    gtyp, gval, gt = max(cand, key=lambda c: c[1])
    row = {"p": p, "A_coord": ac, "A_coord_closed_form": C.area_coord_analytic(p),
           "A_face": af, "A_diag": ad,
           "r_face": af / ac, "r_diag": ad / ac,
           "vertex_max": bmax, "vertex_type": btyp,
           "arc11_best_t": best11[1], "arc11_best_area": best11[0],
           "arc11_best_interior_t": best11_int[1], "arc11_best_interior_area": best11_int[0],
           "arc01_best_t": best01[1], "arc01_best_area": best01[0],
           "arc01_best_interior_t": best01_int[1], "arc01_best_interior_area": best01_int[0],
           "arc_max": arc_max, "arc_minus_vertex_rel": excess_rel,
           "arc_beats_vertex": beats,
           "global_type": gtyp, "global_type_t": gt,
           "all_directions_equal": abs(p - 2.0) < 1e-12,
           "argmax_class_sorted_abs": sorted(abs(x) for x in
                                             (COORD if gtyp == "coordinate" else
                                              (FACE if gtyp == "face-diagonal" else
                                               (DIAG if gtyp == "body-diagonal" else
                                                ((1.0, 1.0, gt) if gtyp == "arc(1,1,t)"
                                                 else (0.0, 1.0, gt))))))}
    rows.append(row)
    P({"stage": "arc-scan", "p": p, "vertex_max": bmax, "vertex_type": btyp,
       "arc11_best_t": best11[1], "arc11_best_area": best11[0],
       "arc11_int_t": best11_int[1], "arc11_int_area": best11_int[0],
       "arc01_best_t": best01[1], "arc01_best_area": best01[0],
       "arc01_int_t": best01_int[1], "arc01_int_area": best01_int[0],
       "arc_minus_vertex_rel": excess_rel, "global_type": gtyp})

# --------------------------------------------------- threshold where diag type loses to face
# A_diag - A_face changes sign once between p = 4 and p = 5; bisect it here (deterministic).
def diff(p):
    return A(DIAG, p) - A(FACE, p)

lo, hi = 4.0, 5.0
dlo, dhi = diff(lo), diff(hi)
if dlo == 0.0:
    p_star = lo
elif dhi == 0.0:
    p_star = hi
elif dlo * dhi < 0.0:
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        dm = diff(mid)
        if dm == 0.0:
            lo = hi = mid
            break
        if dlo * dm < 0.0:
            hi, dhi = mid, dm
        else:
            lo, dlo = mid, dm
    p_star = 0.5 * (lo + hi)
else:
    p_star = None
P({"stage": "diag_vs_face_crossing", "p_star": p_star,
   "d_at_4": dlo, "d_at_5": diff(5.0)})

res = "supports" if not problems else "refutes"
payload = {
    "result": res,
    "bound": ("p in %s; arc (1,1,t) and (0,1,t) scanned on a log grid t in [1e-4,1e4] "
              "(161 points) plus t=0,1 and the limit t->inf; the three vertex directions "
              "scanned exactly" % PS),
    "strategy": ("tanh-sinh polar quadrature between closed-form break points "
                 "(certified in exp:000003 to ~1e-15); full boundary of the fundamental "
                 "domain scanned, not sampled around one guess"),
    "scaling": {"wall_sec": round(time.time() - t0, 3), "area_evals": len(PS) * (2 * len(TS) + 3)},
    "data": {"per_p": rows, "p_star_diag_equals_face": p_star,
             "problem": problems,
             "note": ("relative tolerance 1e-9: an arc point must beat every vertex by more "
                      "than that to count as a refutation; p=2 is isotropic (all directions "
                      "equal), so there 'arc11_best_t' is degenerate by construction")},
}
if problems:
    payload["counterexample"] = {"problems": problems,
                                 "per_p_violating": [r for r in rows if r["arc_beats_vertex"]]}
print("REPRO_RESULT: " + json.dumps(payload))
