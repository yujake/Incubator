#!/usr/bin/env python3
"""attack-000000-sg1.py -- exact verification that r(Theta) = 1/2 for k=1 (any single angle)
and for commensurable k=2 families.  Attack plan 000000, subgoal sg1 (owner E).

DEFINITION (identical to exp:000000 / exp:000002 / code/pyjama_theta_bracket.py):
    Theta = {u_1,...,u_k}, u_i unit vectors in R^2,
    r(Theta) = sup_{p in R^2} min_i dist(p . u_i, Z),  dist(t,Z) = |t - round(t)| in [0, 1/2].

TWO MACHINE-CHECKED FACTS (nothing here is judged by a model):
  (U) for every p and every single unit u: dist(p.u,Z) <= 1/2  ==>  r(Theta) <= 1/2 for ANY Theta.
  (L) one explicit point p with min_i dist(p.u_i,Z) = 1/2  ==>  r(Theta) >= 1/2.
  (U)+(L) => r(Theta) = 1/2 EXACTLY.
  k=1: for EVERY single angle the witness is p = u/2 (then p.u = 1/2), so the k=1 statement holds
       for an arbitrary angle, with no rational approximation anywhere.
  k=2: for each commensurable family below the witness is produced exactly by solving the 2x2 linear
       system  p.u_0 = 1/2 + m_0,  p.u_1 = 1/2 + m_1  over integers m_0,m_1 and then machine-checking
       by exact arithmetic that EVERY direction has dist = 1/2.

ARITHMETIC: exact in Q(sqrt3) = {a + b*sqrt3 : a,b in Q (Fraction)}.  Every angle used is a multiple
of pi/6, so all coordinates live in Q(sqrt3) and every comparison (nearest integer, min, equality with
1/2) is decided by an exact sign test on a + b*sqrt3.  Floating point is used ONLY to pick candidate
nearest integers and to print readable decimals.  Exception, clearly labelled: the BONUS block for
k=3..10 is a float grid and yields LOWER-BOUND readings only.

EVIDENCE LEVEL: numeric / cross_check.  Lean is disabled in this session => nothing here is "proof".

Output: one 'PROGRESS: {...}' line per finished item and exactly one 'REPRO_RESULT: {...}' line.
"""

import json
import math
import time
from fractions import Fraction as Fr

import numpy as np


# ---------------------------------------------------------------- exact Q(sqrt 3)
def asQ(o):
    if isinstance(o, QS):
        return o
    return QS(o)


class QS:
    """a + b*sqrt(3) with a,b Fractions."""

    __slots__ = ("a", "b")

    def __init__(self, a, b=0):
        self.a = Fr(a)
        self.b = Fr(b)

    def __add__(self, o):
        o = asQ(o)
        return QS(self.a + o.a, self.b + o.b)

    __radd__ = __add__

    def __neg__(self):
        return QS(-self.a, -self.b)

    def __sub__(self, o):
        o = asQ(o)
        return QS(self.a - o.a, self.b - o.b)

    def __rsub__(self, o):
        return asQ(o).__sub__(self)

    def __mul__(self, o):
        o = asQ(o)
        return QS(self.a * o.a + 3 * self.b * o.b, self.a * o.b + self.b * o.a)

    __rmul__ = __mul__

    def inv(self):
        d = self.a * self.a - 3 * self.b * self.b
        if d == 0:
            raise ZeroDivisionError("zero divisor in Q(sqrt3)")
        return QS(self.a / d, -self.b / d)

    def __truediv__(self, o):
        return self * asQ(o).inv()

    def sign(self):
        """Exact sign of a + b*sqrt3."""
        a, b = self.a, self.b
        if b == 0:
            return (a > 0) - (a < 0)
        if a == 0:
            return (b > 0) - (b < 0)
        if (a > 0) == (b > 0):
            return 1 if a > 0 else -1
        s = a * a - 3 * b * b
        if a > 0:               # b < 0:  value = (a^2-3b^2)/(a+|b|sqrt3)
            return 1 if s > 0 else -1
        return 1 if s < 0 else -1   # a < 0 < b: value = (3b^2-a^2)/(b sqrt3+|a|)

    def abs(self):
        return self if self.sign() >= 0 else self.__neg__()

    def is_zero(self):
        return self.a == 0 and self.b == 0

    def is_int(self):
        return self.b == 0 and self.a.denominator == 1

    def to_float(self):
        return float(self.a) + float(self.b) * math.sqrt(3.0)

    def __repr__(self):
        return "QS(a=%s, b=%s)" % (self.a, self.b)


def nearest_int_and_dist(t):
    """(n, |t-n|) with n the nearest integer -- chosen by EXACT comparison."""
    n0 = int(round(t.to_float()))
    best_n, best_d = None, None
    for n in range(n0 - 2, n0 + 3):
        d = (t - n).abs()
        if best_d is None or (d - best_d).sign() < 0:
            best_n, best_d = n, d
    return best_n, best_d


def dist_to_int(t):
    return nearest_int_and_dist(t)[1]


def f_at(p, us):
    """f(p) = min_i dist(p . u_i, Z), exactly."""
    m = None
    for u in us:
        d = dist_to_int(p[0] * u[0] + p[1] * u[1])
        if m is None or (d - m).sign() < 0:
            m = d
    return m


def eq_half(d):
    return (asQ(d) - Fr(1, 2)).is_zero()


def qstr(x):
    x = asQ(x)
    if x.b == 0:
        return str(x.a)
    return "(%s) + (%s)*sqrt3" % (x.a, x.b)


# ---------------------------------------------------------------- directions (multiples of pi/6)
H = QS(Fr(1, 2))
S = QS(0, Fr(1, 2))
ONE = QS(1)
ZERO = QS(0)
MONE = QS(-1)
MINUS_H = QS(Fr(-1, 2))
MINUS_S = QS(0, Fr(-1, 2))

# DIR6[j] = (cos(j*pi/6), sin(j*pi/6)); verified below to be exactly unit vectors.
DIR6 = [
    (ONE, ZERO),        # 0
    (S, H),             # pi/6
    (H, S),             # pi/3
    (ZERO, ONE),        # pi/2
    (MINUS_H, S),       # 2pi/3
    (MINUS_S, H),       # 5pi/6
    (MONE, ZERO),       # pi
    (MINUS_S, QS(Fr(-1, 2))),   # 7pi/6
    (MINUS_H, QS(0, Fr(-1, 2))),  # 4pi/3
    (ZERO, MONE),       # 3pi/2
    (H, QS(0, Fr(-1, 2))),        # 5pi/3
    (S, QS(Fr(-1, 2))),           # 11pi/6
]


def unit_ok(u):
    n2 = u[0] * u[0] + u[1] * u[1]
    return (n2 - 1).is_zero()


def label(j):
    return "%d*pi/6" % j


# ---------------------------------------------------------------- k=2 witness by exact linear solve
def solve_witness(us, mrange=4):
    """Search integer offsets (m0,m1) so that p.u_0 = 1/2+m0, p.u_1 = 1/2+m1 and dist = 1/2 for ALL u."""
    u0, u1 = us[0], us[1]
    det = u0[0] * u1[1] - u0[1] * u1[0]
    if det.is_zero():
        return None, "det=0 (parallel directions)"
    for m0 in range(-mrange, mrange + 1):
        for m1 in range(-mrange, mrange + 1):
            r0 = QS(Fr(1, 2) + m0)
            r1 = QS(Fr(1, 2) + m1)
            x = (r0 * u1[1] - u0[1] * r1) / det
            y = (u0[0] * r1 - r0 * u1[0]) / det
            p = (x, y)
            ok = True
            for u in us:
                d = dist_to_int(p[0] * u[0] + p[1] * u[1])
                if not eq_half(d):
                    ok = False
                    break
            if ok:
                return (p, (m0, m1)), "witness_found"
    return None, "no consistent integer offsets in [-%d,%d]^2" % (mrange, mrange)


def sample_max_exact(us, lo=-2, hi=2, steps=32):
    """Exact max of f over the rational grid {(lo + i*h, lo + j*h)}, h=(hi-lo)/steps."""
    best = None
    best_p = None
    cnt = 0
    for i in range(steps + 1):
        x = QS(Fr(lo) + Fr(i * (hi - lo), steps))
        for j in range(steps + 1):
            y = QS(Fr(lo) + Fr(j * (hi - lo), steps))
            d = f_at((x, y), us)
            cnt += 1
            if best is None or (d - best).sign() > 0:
                best, best_p = d, (x, y)
    return best, best_p, cnt


# ---------------------------------------------------------------- BONUS float block (lower bound only)
def bonus_numeric(k, G=161, hill=6):
    us = [(math.cos(i * math.pi / k), math.sin(i * math.pi / k)) for i in range(k)]
    xs = np.linspace(-1.0, 1.0, G)
    X, Y = np.meshgrid(xs, xs)
    best = np.full(X.shape, 1.0)
    for ux, uy in us:
        t = X * ux + Y * uy
        d = np.abs(t - np.round(t))
        best = np.minimum(best, d)
    bi = np.unravel_index(np.argmax(best), best.shape)
    bx, by, bv = float(X[bi]), float(Y[bi]), float(best[bi])
    step = 2.0 / (G - 1)
    for _ in range(60):                       # deterministic 8-direction hill climb
        improved = False
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = bx + dx * step, by + dy * step
            v = 1.0
            for ux, uy in us:
                t = nx * ux + ny * uy
                v = min(v, abs(t - round(t)))
            if v > bv:
                bx, by, bv = nx, ny, v
                improved = True
        if not improved:
            step *= 0.5
            if step < 1e-9:
                break
    return {"k": k, "lb_float": bv, "at": [bx, by], "grid": [G, G],
            "needed_1_over_2k": 1.0 / (2.0 * k)}


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    failures = []

    # sanity: every direction in DIR6 is exactly a unit vector
    for j, u in enumerate(DIR6):
        if not unit_ok(u):
            failures.append({"item": "unit_vector_%s" % label(j), "reason": "u.u != 1 exactly"})

    # ---- (U) spot-check of the universal upper bound on a rational grid
    upper_check = {"checked": 0, "violations": 0}
    for j in range(6):
        u = DIR6[j]
        for i in range(9):
            for l in range(9):
                p = (QS(Fr(i, 4)), QS(Fr(l, 4)))
                d = dist_to_int(p[0] * u[0] + p[1] * u[1])
                upper_check["checked"] += 1
                if (d - Fr(1, 2)).sign() > 0:
                    upper_check["violations"] += 1
    if upper_check["violations"]:
        failures.append({"item": "upper_bound_1/2", "reason": "a grid point had dist > 1/2"})

    # ---- k = 1 : ANY single angle, witness p = u/2, dist(p.u,Z) = 1/2 exactly
    k1_rows = []
    for j in range(6):
        u = DIR6[j]
        p = (u[0] * Fr(1, 2), u[1] * Fr(1, 2))
        d = f_at(p, [u])
        ok = eq_half(d)
        k1_rows.append({"angle": label(j), "witness": [qstr(p[0]), qstr(p[1])],
                        "p_dot_u": qstr(nearest_int_and_dist(p[0] * u[0] + p[1] * u[1])[0]
                                         + (p[0] * u[0] + p[1] * u[1])
                                         - QS(nearest_int_and_dist(p[0] * u[0] + p[1] * u[1])[0])),
                        "dist": qstr(d), "equals_1/2": ok,
                        "r_lower": "1/2", "r_upper": "1/2"})
        if not ok:
            failures.append({"item": "k1_%s" % label(j), "reason": "witness dist != 1/2"})
        print("PROGRESS: " + json.dumps({"item": "k1", "angle": label(j),
                                         "dist_exact": qstr(d), "ok": ok}))
    sample1 = sample_max_exact([DIR6[2]], lo=-1, hi=1, steps=16)

    # ---- k = 2 : commensurable families (all angles multiples of pi/6)
    pairs = [(0, 3), (0, 2), (1, 3), (2, 3), (0, 1), (1, 2), (0, 4), (1, 4), (3, 4)]
    k2_rows = []
    for (j0, j1) in pairs:
        us = [DIR6[j0], DIR6[j1]]
        fam = "{" + label(j0) + ", " + label(j1) + "}"
        sol, status = solve_witness(us, mrange=4)
        row = {"family": fam, "status": status}
        if sol is None:
            row.update({"r_upper": "1/2 (universal)", "r_lower": "not certified by this witness form"})
            failures.append({"item": "k2_%s" % fam, "reason": status})
        else:
            p, offs = sol
            dvals = [dist_to_int(p[0] * u[0] + p[1] * u[1]) for u in us]
            allhalf = all(eq_half(d) for d in dvals)
            row.update({"witness": [qstr(p[0]), qstr(p[1])], "offsets": list(offs),
                        "dists": [qstr(d) for d in dvals], "all_dist_equal_1/2": allhalf,
                        "r_lower": "1/2", "r_upper": "1/2 (universal)"})
            if not allhalf:
                failures.append({"item": "k2_%s" % fam, "reason": "witness verification failed"})
        # exact dense rational grid sampling: eps = 1/2 - max_sampled
        gmax, gp, cnt = sample_max_exact(us, lo=-2, hi=2, steps=32)
        eps = QS(Fr(1, 2)) - gmax
        row.update({"grid_points": cnt, "grid_max_exact": qstr(gmax),
                    "grid_max_float": round(gmax.to_float(), 12),
                    "eps_grid = 1/2 - grid_max": round(eps.to_float(), 12),
                    "eps_exact": qstr(eps),
                    "grid_argmax": [qstr(gp[0]), qstr(gp[1])]})
        k2_rows.append(row)
        print("PROGRESS: " + json.dumps({"item": "k2", "family": fam, "status": status,
                                         "r_lower": row.get("r_lower"),
                                         "eps_grid": row.get("eps_grid = 1/2 - grid_max")}))

    # ---- BONUS : k=3..10 equally spaced, float grid, LOWER BOUND readings only
    bonus = []
    for k in range(3, 11):
        try:
            b = bonus_numeric(k, G=121)
            b["meets_1_over_2k"] = (b["lb_float"] >= b["needed_1_over_2k"])
            bonus.append(b)
            print("PROGRESS: " + json.dumps({"item": "bonus", "k": k, "lb_float": round(b["lb_float"], 6)}))
        except Exception as e:                                  # noqa: BLE001
            bonus.append({"k": k, "error": "%s: %s" % (type(e).__name__, e)})
            print("PROGRESS: " + json.dumps({"item": "bonus", "k": k, "error": str(e)}))

    n_k1_ok = sum(1 for r in k1_rows if r["equals_1/2"])
    n_k2_ok = sum(1 for r in k2_rows if r.get("all_dist_equal_1/2") is True)
    everything_ok = (n_k1_ok == len(k1_rows) and n_k2_ok == len(k2_rows)
                     and upper_check["violations"] == 0 and not failures)

    elapsed = round(time.time() - t0, 3)
    res = {
        "result": "supports" if everything_ok else "inconclusive",
        "claim_checked": "attack plan 000000 / sg1: k=1 r(Theta)=1/2 for every single angle; "
                         "k=2 commensurable families admit an exact witness with dist=1/2 hence r=1/2",
        "scope": "k=1: all single angles (exact, no approximation). k=2: exactly the families "
                 "{j0*pi/6, j1*pi/6} listed in k2 (all angles of Theta are multiples of pi/6, so "
                 "everything is exact in Q(sqrt3)). NOT covered: general k=2 with irrational angle "
                 "differences, and k>=3 (bonus block gives float lower bounds only).",
        "upper_bound": "r(Theta) <= 1/2 for ANY Theta (dist(p.u,Z) <= 1/2 for every p and u); "
                       "spot-checked exactly on %d grid points, violations=%d"
                       % (upper_check["checked"], upper_check["violations"]),
        "lower_bound": "explicit exact points with min_i dist = 1/2: k=1 witness p=u/2 for each of "
                       "%d angles; k=2 witnesses solved over integer offsets for %d/%d families"
                       % (n_k1_ok, n_k2_ok, len(k2_rows)),
        "r_exact": "1/2 for every item above (upper 1/2 and lower 1/2 meet)",
        "bound": {"r_upper": 0.5, "r_lower": 0.5,
                  "eps_grid_worst": max([r.get("eps_grid = 1/2 - grid_max", 0.0) for r in k2_rows] or [0.0])},
        "strategy": "exact arithmetic in Q(sqrt3)=a+b*sqrt3 with Fraction; k=2 witness from a 2x2 "
                    "linear solve over integer offsets m in [-4,4]^2; independent dense rational grid "
                    "(33x33 over [-2,2]^2) as an exact eps reading; bonus: float 121x121 grid + "
                    "8-direction hill climb for k=3..10",
        "scaling": {"k1_items": len(k1_rows), "k2_families": len(k2_rows),
                    "k2_witness_found": n_k2_ok,
                    "grid_points_per_family": k2_rows[0]["grid_points"] if k2_rows else 0,
                    "bonus_k": [b.get("k") for b in bonus], "seconds_total": elapsed,
                    "state_space_note": "state count is O(#families x #offsets^2 x #grid points); "
                                        "no enumeration of graphs -- all costs are linear in the printed counts"},
        "k1": k1_rows, "k2": k2_rows, "bonus": bonus,
        "failures": failures,
        "evidence_level": "numeric/cross_check (Lean disabled this session; not proof)",
    }
    print("REPRO_RESULT: " + json.dumps(res))


if __name__ == "__main__":
    main()
