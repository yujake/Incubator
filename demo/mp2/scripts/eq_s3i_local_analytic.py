#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3 local analytic re-check of already-registered minimizers P* (plan 000000,
conjecture 000000, claim_key=equichordal_ellipse_none).

SCOPE (hard): read-only re-check of the points already registered in
data/s3_ref_coords.json.  NO global search, NO new candidate generation.
The only numbers produced here that were not on disk before are
 (a) high-accuracy Var_phi L_P at those fixed points (float64 + mpmath 50 dps),
 (b) the 2x2 Hessian of Var(P) at those fixed points (central differences),
 (c) for the one point whose 2D coordinate was never registered (a/b=5,
     abs_only) a strictly LOCAL reconstruction confined to |delta| <= 2e-3.

Chord-length closed form, ellipse x^2/a^2 + y^2/b^2 = 1, line P + t*(cos,sin):
    A t^2 + B t + C = 0
    A = c^2/a^2 + s^2/b^2
    B = 2*(Px*c/a^2 + Py*s/b^2)
    C = Px^2/a^2 + Py^2/b^2 - 1        ( < 0 for P strictly inside )
    L_P(phi) = (t+ - t-) = sqrt(B^2 - 4AC)/A
    Var_phi L_P = mean(L^2) - mean(L)^2   over N uniform directions (midpoint rule)

Criteria taken verbatim from the coordinate file (not re-interpreted):
    Hessian PSD  AND  Var(P*) > 1e-18  AND  rel.diff vs registered var_8000 < 1e-6
      => point numerically certified as local minimum with strictly positive
         variance  (cross_check level, NOT a proof)
    Var(P*) < 1e-18 with |P*| clearly nonzero => counterexample (refutes)
This session has Lean disabled: evidence_kind can be at most cross_check.

Protocol: one line "REPRO_RESULT: {...}" plus one "PROGRESS: {...}" per point.
"""

import json
import math
import os
import sys
import time

T0 = time.time()
WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(WS, "data", "s3_ref_coords.json")
DPS = 50
VAR_POS_TOL = 1e-18
REL_TOL = 1e-6
ABS_P_NONZERO = 1e-3          # |P*| "clearly nonzero" threshold for the refute branch
EPS_D = 2.3e-16               # double-precision eps, for the finite-difference noise estimate

try:
    import mpmath as mp
    mp.mp.dps = DPS
    HAVE_MP = True
    MP_ERR = None
except Exception as exc:      # pragma: no cover
    HAVE_MP = False
    MP_ERR = repr(exc)


# ---------------------------------------------------------------- Var_phi L_P
def chord_var_f64(a, b, px, py, n):
    """Var of the chord length over n uniform directions, double precision."""
    ia = 1.0 / (a * a)
    ib = 1.0 / (b * b)
    base = px * px * ia + py * py * ib - 1.0
    two_pi = 2.0 * math.pi
    s = 0.0
    s2 = 0.0
    for k in range(n):
        ph = two_pi * (k + 0.5) / n
        c = math.cos(ph)
        sn = math.sin(ph)
        A = c * c * ia + sn * sn * ib
        B = 2.0 * (px * c * ia + py * sn * ib)
        d = B * B - 4.0 * A * base
        if d < 0.0:
            d = 0.0
        L = math.sqrt(d) / A
        s += L
        s2 += L * L
    m = s / n
    v = s2 / n - m * m
    return v if v > 0.0 else 0.0


def chord_var_mp(a, b, px, py, n):
    """Var of the chord length over n uniform directions, mpmath at DPS digits."""
    A_ = 1 / mp.mpf(repr(float(a))) ** 2
    B_ = 1 / mp.mpf(repr(float(b))) ** 2
    PX = mp.mpf(repr(float(px)))
    PY = mp.mpf(repr(float(py)))
    base = PX * PX * A_ + PY * PY * B_ - 1
    two_pi = 2 * mp.pi
    s = mp.mpf(0)
    s2 = mp.mpf(0)
    for k in range(n):
        ph = two_pi * (k + 0.5) / n
        c = mp.cos(ph)
        sn = mp.sin(ph)
        Aa = c * c * A_ + sn * sn * B_
        Bb = 2 * (PX * c * A_ + PY * sn * B_)
        d = Bb * Bb - 4 * Aa * base
        if d < 0:
            d = mp.mpf(0)
        L = mp.sqrt(d) / Aa
        s += L
        s2 += L * L
    m = s / n
    return s2 / n - m * m


# ------------------------------------------------------------------- Hessian
def hessian_f64(a, b, px, py, h, n):
    """2x2 Hessian of Var(P) at (px,py): central differences, step h, n directions."""
    f = lambda x, y: chord_var_f64(a, b, x, y, n)
    f0 = f(px, py)
    fxp = f(px + h, py)
    fxm = f(px - h, py)
    fyp = f(px, py + h)
    fym = f(px, py - h)
    fpp = f(px + h, py + h)
    fpm = f(px + h, py - h)
    fmp = f(px - h, py + h)
    fmm = f(px - h, py - h)
    hxx = (fxp - 2.0 * f0 + fxm) / (h * h)
    hyy = (fyp - 2.0 * f0 + fym) / (h * h)
    hxy = (fpp - fpm - fmp + fmm) / (4.0 * h * h)
    return {"hxx": hxx, "hyy": hyy, "hxy": hxy, "f_at_P": f0}


def eig2(hxx, hyy, hxy):
    tr = hxx + hyy
    disc = math.sqrt(max(0.0, ((hxx - hyy) / 2.0) ** 2 + hxy * hxy))
    lo = tr / 2.0 - disc
    hi = tr / 2.0 + disc
    return lo, hi


# ------------------------------------------------- local reconstruction (only a/b=5)
def local_refine(a, b, px, py, n=2000, max_disp=2e-3, cap=200):
    """Strictly local coordinate descent around (px,py), |delta| <= max_disp."""
    best = chord_var_f64(a, b, px, py, n)
    x0, y0 = px, py
    steps = [1e-3, 3e-4, 1e-4, 3e-5, 1e-5, 3e-6, 1e-6, 3e-7, 1e-7,
             3e-8, 1e-8, 3e-9, 1e-9, 3e-10, 1e-10, 3e-11, 1e-11]
    for st in steps:
        improved = True
        it = 0
        while improved and it < cap:
            improved = False
            it += 1
            for dx, dy in ((st, 0.0), (-st, 0.0), (0.0, st), (0.0, -st)):
                nx = px + dx
                ny = py + dy
                if abs(nx - x0) > max_disp or abs(ny - y0) > max_disp:
                    continue
                if nx * nx / (a * a) + ny * ny / (b * b) >= 0.999999:
                    continue
                v = chord_var_f64(a, b, nx, ny, n)
                if v < best:
                    best = v
                    px, py = nx, ny
                    improved = True
    return px, py, {"start": [x0, y0], "end": [px, py], "disp": [px - x0, py - y0],
                    "var_at_end_f64_n2000": best, "max_disp": max_disp, "n_dirs": n}


# ----------------------------------------------------------------------- main
def main():
    with open(REF, "r", encoding="utf-8") as fh:
        ref = json.load(fh)
    dirs = ref.get("directions", {})
    n2000 = int(dirs.get("confirm_2000", 2000))
    n8000 = int(dirs.get("confirm_8000", 8000))
    points = ref["points"]
    n_total = len(points)

    print("=== S3 local analytic re-check (no global search) ===")
    print("input: data/s3_ref_coords.json  criteria: %s" % ref.get("criteria", "")[:120])
    print("mpmath available: %s (dps=%d)" % (HAVE_MP, DPS))
    print("directions: %d / %d ; hessian steps: 1e-4 and 1e-5 ; n_dirs for hessian: %d"
          % (n2000, n8000, n8000))
    print("")

    out = []
    for idx, p in enumerate(points):
        tp = time.time()
        label = "a/b=%g" % float(p["a_over_b"])
        a = float(p["a"])
        b = float(p["b"])
        abs_only = bool(p.get("abs_only", False))
        if p.get("P_star") is None:
            px, py = 0.0, -float(p["abs_P_star"])
            coord_src = ("abs_only: no 2D coordinate was ever registered; "
                         "start (0, -|P*|) with |P*| from the coordinate file")
        else:
            px = float(p["P_star"][0])
            py = float(p["P_star"][1])
            coord_src = "registered 2D P* (data/s3_ref_coords.json)"

        refine = None
        if abs_only:
            px, py, refine = local_refine(a, b, px, py, n=n2000)
            coord_src += ("; locally reconstructed here (|delta| <= %g from the "
                          "registered |P*|), NOT a registered coordinate"
                          % refine["max_disp"])

        v2000 = chord_var_f64(a, b, px, py, n2000)
        v8000 = chord_var_f64(a, b, px, py, n8000)
        if HAVE_MP:
            vm2000 = chord_var_mp(a, b, px, py, n2000)
            vm8000 = chord_var_mp(a, b, px, py, n8000)
            vm2000f = float(vm2000)
            vm8000f = float(vm8000)
        else:
            vm2000f = None
            vm8000f = None

        ref_var = p.get("var_8000_mp")
        rel8000 = None
        rel2000 = None
        if ref_var is not None and ref_var != 0.0:
            if vm8000f is not None:
                rel8000 = (vm8000f - float(ref_var)) / float(ref_var)
            else:
                rel8000 = (v8000 - float(ref_var)) / float(ref_var)
            if vm2000f is not None:
                rel2000 = (vm2000f - float(ref_var)) / float(ref_var)
            else:
                rel2000 = (v2000 - float(ref_var)) / float(ref_var)

        h1 = hessian_f64(a, b, px, py, 1e-4, n8000)
        h2 = hessian_f64(a, b, px, py, 1e-5, n8000)
        lam1_lo, lam1_hi = eig2(h1["hxx"], h1["hyy"], h1["hxy"])
        lam2_lo, lam2_hi = eig2(h2["hxx"], h2["hyy"], h2["hxy"])
        # negative-eigenvalue tolerance from the finite-difference noise scale:
        # |noise| ~ 4*eps*Var/h^2  (worst case h=1e-5), plus a 1e-13 floor.
        noise_h5 = 4.0 * EPS_D * max(v8000, 1e-30) / (1e-5 ** 2)
        noise_h4 = 4.0 * EPS_D * max(v8000, 1e-30) / (1e-4 ** 2)
        scale = max(abs(lam1_lo), abs(lam1_hi), abs(lam2_lo), abs(lam2_hi))
        neg_tol = -(1e-9 * scale + 1e-13 + noise_h5)
        psd1 = lam1_lo >= neg_tol
        psd2 = lam2_lo >= neg_tol
        psd_ok = psd1 and psd2
        if abs(lam2_lo) > 0:
            lam_stab = abs(lam1_lo - lam2_lo) / max(abs(lam2_lo), 1e-300)
        else:
            lam_stab = None
        var_pos = (vm8000f if vm8000f is not None else v8000) > VAR_POS_TOL
        rel_ok = (rel8000 is not None) and (abs(rel8000) < REL_TOL)
        criteria_ok = bool(psd_ok and var_pos and rel_ok)

        rec = {
            "label": label,
            "a_over_b": float(p["a_over_b"]),
            "a": a, "b": b,
            "P_used": [px, py],
            "abs_P": math.hypot(float(p["abs_P_star"]), 0.0) if False else abs_only_abs(p),
            "coordinate_source": coord_src,
            "abs_only": abs_only,
            "local_refine": refine,
            "var2000_f64": v2000,
            "var8000_f64": v8000,
            "var2000_mp50": vm2000f,
            "var8000_mp50": vm8000f,
            "registered_var_8000_mp": ref_var,
            "rel_diff_vs_registered_8000": rel8000,
            "rel_diff_vs_registered_2000": rel2000,
            "hessian_h1e-4": {"hxx": h1["hxx"], "hyy": h1["hyy"], "hxy": h1["hxy"],
                              "lambda_min": lam1_lo, "lambda_max": lam1_hi},
            "hessian_h1e-5": {"hxx": h2["hxx"], "hyy": h2["hyy"], "hxy": h2["hxy"],
                              "lambda_min": lam2_lo, "lambda_max": lam2_hi},
            "lambda_min_rel_change_h1e-4_vs_1e-5": lam_stab,
            "fd_noise_scale": {"noise_h1e-5": noise_h5, "noise_h1e-4": noise_h4,
                               "neg_tol_used": neg_tol},
            "checks": {"hessian_psd_h1e-4": psd1, "hessian_psd_h1e-5": psd2,
                       "var_gt_1e-18": bool(var_pos),
                       "rel_diff_lt_1e-6": bool(rel_ok)},
            "criteria_ok": criteria_ok,
        }
        out.append(rec)

        print("[%d/%d] %s  P=(%.12g, %.12g)  |P|=%.12g%s"
              % (idx + 1, n_total, label, px, py, rec["abs_P"],
                 "  [abs_only]" if abs_only else ""))
        print("      Var2000 f64=%.12e  Var8000 f64=%.12e" % (v2000, v8000))
        print("      Var2000 mp50=%s  Var8000 mp50=%s  registered=%s"
              % (fmt(vm2000f), fmt(vm8000f), fmt(ref_var)))
        print("      rel_diff vs registered (8000 dirs, mp50)=%s  (2000 dirs)=%s"
              % (fmt(rel8000), fmt(rel2000)))
        print("      Hessian h=1e-4: hxx=%.6e hyy=%.6e hxy=%.6e  lam_min=%.6e lam_max=%.6e"
              % (h1["hxx"], h1["hyy"], h1["hxy"], lam1_lo, lam1_hi))
        print("      Hessian h=1e-5: hxx=%.6e hyy=%.6e hxy=%.6e  lam_min=%.6e lam_max=%.6e"
              % (h2["hxx"], h2["hyy"], h2["hxy"], lam2_lo, lam2_hi))
        print("      lam_min rel.change between the two steps: %s ; neg_tol=%.3e"
              % (fmt(lam_stab), neg_tol))
        print("      criteria: psd(h=1e-4)=%s psd(h=1e-5)=%s var>1e-18=%s rel<1e-6=%s => %s"
              % (psd1, psd2, var_pos, rel_ok, "PASS" if criteria_ok else "NOT-PASS"))
        print("")
        print("PROGRESS: " + json.dumps(
            {"point": label, "done": idx + 1, "of": n_total,
             "var8000_mp50": vm8000f, "var8000_f64": v8000,
             "lambda_min_h1e-5": lam2_lo, "criteria_ok": criteria_ok,
             "elapsed_s": round(time.time() - T0, 3)}, ensure_ascii=False))

    # ------------------------------------------------------------- verdict
    refute_pts = [r for r in out
                  if (r["var8000_mp50"] if r["var8000_mp50"] is not None else r["var8000_f64"]) < VAR_POS_TOL
                  and r["abs_P"] > ABS_P_NONZERO]
    fail_pts = [r for r in out if not r["criteria_ok"]]

    if refute_pts:
        result = "refutes"
        counterexample = []
        for r in refute_pts:
            v = r["var8000_mp50"] if r["var8000_mp50"] is not None else r["var8000_f64"]
            counterexample.append({
                "a_over_b": r["a_over_b"], "a": r["a"], "b": r["b"],
                "P_star": r["P_used"], "abs_P": r["abs_P"],
                "Var_phi_L_P_value": v, "direction_count": n8000,
                "mp_dps": DPS if HAVE_MP else None,
                "why": ("Var_phi L_P at the registered 'minimum' is below 1e-18 while "
                        "|P*| is clearly nonzero: if P* is an equichordal point then the "
                        "registered claim that the minimizer is a genuine variance "
                        "minimum with strictly positive variance fails at this point")})
    elif fail_pts:
        result = "inconclusive"
        counterexample = None
    else:
        result = "supports"
        counterexample = None

    payload = {
        "result": result,
        "claim_key": "equichordal_ellipse_none",
        "what_was_checked": ("local analytic re-check of the P* already registered in "
                             "data/s3_ref_coords.json: Var_phi L_P by the closed-form "
                             "chord length on 2000/8000 uniform directions (float64 and "
                             "mpmath %d dps) and the 2x2 Hessian of Var(P) at P* by "
                             "central differences with h=1e-4 and h=1e-5" % DPS),
        "bound": {
            "covered_points_a_over_b": [r["a_over_b"] for r in out],
            "direction_counts": [n2000, n8000],
            "hessian_steps": [1e-4, 1e-5],
            "mp_dps": DPS if HAVE_MP else None,
            "not_covered": ref.get("not_covered", []),
            "no_new_global_search": True,
        },
        "strategy": ("closed_form_chord_length + uniform_direction_midpoint_quadrature "
                     "+ central_difference_hessian (no enumeration of candidate points)"),
        "scaling": {"n_points": n_total, "mpmath_evaluations": (n2000 + n8000) * n_total if HAVE_MP else 0,
                    "float64_chord_evaluations": (n2000 + n8000 + 18 * n8000) * n_total,
                    "elapsed_s": round(time.time() - T0, 3)},
        "criteria_verbatim": ref.get("criteria"),
        "tolerances": {"var_positive": VAR_POS_TOL, "rel_diff": REL_TOL,
                       "abs_P_nonzero_for_refute": ABS_P_NONZERO,
                       "neg_eigen_tol_rule": "-(1e-9*max|lambda| + 1e-13 + 4*eps*Var/h^2)"},
        "points": out,
        "fail_points": [r["label"] for r in fail_pts],
        "refute_points": [r["label"] for r in refute_pts],
        "evidence_level": "cross_check (numeric; Lean disabled in this session, no proof claim)",
    }
    if counterexample is not None:
        payload["counterexample"] = counterexample

    print("")
    print("=== summary ===")
    for r in out:
        print("  %-10s criteria_ok=%-5s var8000_mp50=%-14s lam_min(h=1e-5)=%.4e rel_diff=%s"
              % (r["label"], r["criteria_ok"],
                 fmt(r["var8000_mp50"] if r["var8000_mp50"] is not None else r["var8000_f64"]),
                 r["hessian_h1e-5"]["lambda_min"], fmt(r["rel_diff_vs_registered_8000"])))
    print("  points checked: %d ; not passing: %d ; refuting: %d"
          % (n_total, len(fail_pts), len(refute_pts)))
    print("  NOTE: local check only; no global minimality claim; cross_check level, not a proof.")
    print("")
    print("REPRO_RESULT: " + json.dumps(payload, ensure_ascii=False))
    return 0


def fmt(x):
    return "None" if x is None else "%.6e" % x


def abs_only_abs(p):
    return float(p.get("abs_P_star"))

if __name__ == "__main__":
    sys.exit(main())
