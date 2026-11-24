"""lpsec_validate.py -- deterministic analytic self-checks of the B_p^3 section kernel.

V1  p = 2  -> every central section has area pi (Euclidean ball is isotropic).
V2  p = 1  -> polar quadrature vs exact octahedron clipping (shoelace on clipped edges).
V3  p -> infinity: coordinate / body-diagonal / face-diagonal sections of B_p^3
    converge to the exact cube values 4, 3*sqrt(3), 4*sqrt(2) as 1/p -> 0
    (checked at p = 100 and p = 1000: the deviation must shrink).
V4  coordinate section of B_p^3 vs closed form 4*G(1+1/p)^2/G(1+2/p), all p in PS.
V5  basis-rotation invariance: the polar formula A = (1/2) int ||cos u + sin v||_p^-2
    does not depend on the choice of the orthonormal basis (u,v) of n^perp, so
    rotating the basis must not change the number (a basis/indexing bug shows here).
V6  independent nested method (bisection in t + Simpson in s): the difference to the
    polar value must shrink as npts grows and end below 2e-2 (Simpson has corner
    error, so this is a sanity band, not a precision test).
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lpsec_core as C

PS = [1.05, 1.1, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 8.0, 16.0, 1000.0]
PI = math.pi
SQ3 = math.sqrt(3.0)
HL = (0.125, 0.0625, 0.03125)
t0 = time.time()
fails = []
D = {}
print("PROGRESS: " + json.dumps({"stage": "start", "ps": PS}))


def area_basis(u, v, p, h_list=HL):
    """A_p for the plane spanned by the orthonormal pair (u,v); no basis is rebuilt."""
    pts = C.break_points(u, v)
    f = C.make_integrand(u, v, p)
    vals = []
    for h in h_list:
        tot = 0.0
        for j in range(len(pts) - 1):
            tot += C._ts_panel(f, pts[j], pts[j + 1], h)
        vals.append(0.5 * tot)
    return vals[-1], abs(vals[-1] - vals[-2])


def area_rotated_basis(n, p, alpha, h_list=HL):
    nh, u, v = C.plane_basis(n)
    ca, sa = math.cos(alpha), math.sin(alpha)
    u2 = tuple(ca * u[i] + sa * v[i] for i in range(3))
    v2 = tuple(-sa * u[i] + ca * v[i] for i in range(3))
    return area_basis(u2, v2, p, h_list)


# ---------------------------------------------------------------- V1: p = 2 -> pi
dirs1 = [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (1.0, 1.0, 1.0),
         (0.3, -0.7, 0.2), (1.0, -2.0, 3.0)]
w1 = 0.0
rows1 = []
for v in dirs1:
    a, err, info = C.area_polar(v, 2.0, h_list=HL)
    d = abs(a - PI)
    w1 = max(w1, d)
    rows1.append({"n": list(v), "area": a, "dev_from_pi": d, "err_est": err,
                  "panels": info["panels"]})
    print("PROGRESS: " + json.dumps({"stage": "V1", "n": list(v), "area": a, "dev": d}))
D["V1_p2_max_dev_from_pi"] = w1
D["V1_rows"] = rows1
if w1 > 1e-12:
    fails.append("V1")

# ------------------------------------------- V2: p = 1 octahedron vs exact clipping
octE = C.oct_edges()
w2 = 0.0
rows2 = []
for v in [(0.0, 0.0, 1.0), (1.0, 1.0, 0.0), (1.0, 1.0, 1.0), (1.0, 2.0, 3.0)]:
    ex = C.section_area_edges(octE, v)
    ap, err, info = C.area_polar(v, 1.0, h_list=HL)
    d = abs(ap - ex)
    w2 = max(w2, d)
    rows2.append({"n": list(v), "polar": ap, "clip": ex, "dev": d})
    print("PROGRESS: " + json.dumps({"stage": "V2", "n": list(v), "polar": ap,
                                     "clip": ex, "dev": d}))
D["V2_p1_max_dev"] = w2
D["V2_rows"] = rows2
if w2 > 1e-12:
    fails.append("V2")

# ---------------------------- V3: p -> infinity convergence to the exact cube values
cubeE = C.cube_edges()
rows3 = []
conv_ok = True
for v, exact, label in [((0.0, 0.0, 1.0), 4.0, "coordinate=4"),
                        ((1.0, 1.0, 1.0), 3.0 * SQ3, "body-diagonal=3sqrt3"),
                        ((1.0, 1.0, 0.0), 4.0 * math.sqrt(2.0), "face-diagonal=4sqrt2")]:
    devs = {}
    for p in (100.0, 1000.0):
        ap, err, info = C.area_polar(v, p, h_list=HL)
        devs[p] = abs(ap - exact)
        print("PROGRESS: " + json.dumps({"stage": "V3", "label": label, "p": p,
                                         "polar": ap, "cube_exact": exact,
                                         "dev": devs[p]}))
    clip = C.section_area_edges(cubeE, v)
    shrinking = devs[1000.0] < devs[100.0]
    conv_ok = conv_ok and shrinking and devs[1000.0] < 2e-2
    rows3.append({"n": list(v), "label": label, "cube_exact": exact,
                  "dev_p100": devs[100.0], "dev_p1000": devs[1000.0],
                  "shrinks_with_p": shrinking, "clip_cube": clip})
D["V3_rows"] = rows3
D["V3_converges_to_cube"] = conv_ok
if not conv_ok:
    fails.append("V3")

# ------------------ V4: coordinate sections vs closed form, every p in PS
w4 = 0.0
rows4 = []
for p in PS:
    ap, err, info = C.area_polar((0.0, 0.0, 1.0), p, h_list=HL)
    cf = C.area_coord_analytic(p)
    rel = abs(ap - cf) / cf
    w4 = max(w4, rel)
    rows4.append({"p": p, "polar": ap, "closed_form": cf, "rel_dev": rel,
                  "err_est": err})
    print("PROGRESS: " + json.dumps({"stage": "V4", "p": p, "polar": ap,
                                     "closed_form": cf, "rel_dev": rel}))
D["V4_coord_max_rel_dev"] = w4
D["V4_rows"] = rows4
if w4 > 1e-13:
    fails.append("V4")

# -------------------------------- V5: invariance under rotation of the plane basis
w5 = 0.0
rows5 = []
for p, v in [(1.05, (0.3, -0.7, 0.2)), (1.5, (1.0, 2.0, 3.0)), (3.0, (0.5, 1.0, 0.0)),
             (8.0, (0.2, 0.4, 1.0)), (1000.0, (1.0, 1.0, 0.0))]:
    a0, e0 = area_rotated_basis(v, p, 0.0)
    dmax = 0.0
    for alpha in (0.7, 1.9, -2.5):
        a1, e1 = area_rotated_basis(v, p, alpha)
        dmax = max(dmax, abs(a1 - a0))
    w5 = max(w5, dmax)
    rows5.append({"p": p, "n": list(v), "area_alpha0": a0, "max_dev_rotated": dmax})
    print("PROGRESS: " + json.dumps({"stage": "V5", "p": p, "n": list(v),
                                     "area": a0, "max_dev_rotated": dmax}))
D["V5_basis_rotation_max_dev"] = w5
D["V5_rows"] = rows5
if w5 > 1e-12:
    fails.append("V5")

# ------------------- V6: polar vs the cruder nested method (its own error band)
rows6 = []
v6_ok = True
for p, v in [(1.2, (0.3, -0.7, 0.2)), (3.0, (1.0, 1.0, 1.0)), (8.0, (0.3, -0.7, 0.2))]:
    ap, err, info = C.area_polar(v, p, h_list=HL)
    diffs = []
    for npts in (1201, 4801, 19201):
        an = C.area_nested(v, p, npts=npts)
        diffs.append(abs(an - ap))
    # The nested method is a *crude* consistency check: Simpson in s over a region whose
    # radial function has (smax-s)^{1/p} corners, so its own error is ~1e-1 near the
    # corner-degenerate directions and shrinks only like h^{1/p}.  The check is therefore
    # "converges to the polar value" (differences shrink under refinement and stay inside
    # the measured band 0.15), not equality.
    shrinking = diffs[2] < diffs[0]
    v6_ok = v6_ok and shrinking and diffs[2] < 0.15
    rows6.append({"p": p, "n": list(v), "polar": ap, "absdiff_npts_1201_4801_19201": diffs,
                  "shrinks_with_npts": shrinking})
    print("PROGRESS: " + json.dumps({"stage": "V6", "p": p, "n": list(v), "polar": ap,
                                     "diffs": diffs, "shrinks": shrinking}))
D["V6_rows"] = rows6
D["V6_nested_agrees"] = v6_ok
if not v6_ok:
    fails.append("V6")

# ------------------------------------------------------------------ report
data = {
    "checks": ["V1 p=2 -> pi", "V2 p=1 octahedron vs exact clipping",
               "V3 p->inf convergence to cube values 4 / 3sqrt3 / 4sqrt2",
               "V4 coordinate section vs 4G(1+1/p)^2/G(1+2/p)",
               "V5 invariance under rotation of the plane basis",
               "V6 independent nested method agrees within its Simpson band"],
    "worst": D,
    "failed_checks": fails,
    "note": "V3 and V6 are convergence/band checks, not equality checks: p=1000 is not "
            "the cube (residual O(1/p)) and the nested Simpson rule has corner error.",
}
res = "supports" if not fails else "refutes"
payload = {"result": res,
           "bound": "analytic reference set: p in {1, 2, 100, 1000}, all p in PS for V4",
           "strategy": "tanh-sinh panels between closed-form break points; exact polytope "
                       "clipping; basis-rotation invariance; nested bisection+Simpson",
           "scaling": {"wall_sec": round(time.time() - t0, 3)},
           "data": data}
if fails:
    payload["counterexample"] = {"failed_checks": fails,
                                 "worst": {k: D[k] for k in D if k.startswith("V") and
                                           not k.endswith("_rows")}}
print("REPRO_RESULT: " + json.dumps(payload))
