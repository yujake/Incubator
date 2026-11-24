"""lpsec_core.py -- deterministic numeric core for central cross-sections of B_p^3.

B_p^3 = { x in R^3 : |x1|^p + |x2|^p + |x3|^p <= 1 }   (p > 0)
A_p(n) = 2-dim area of { x in B_p^3 : n.x = 0 },  n unit.

Main method (polar quadrature)
------------------------------
Let (u,v) be an orthonormal basis of n^perp.  B_p^3 is the unit ball of the l_p
norm, so its radial function in that plane is
    rho(psi) = || cos(psi) u + sin(psi) v ||_p^{-1}
and therefore
    A_p(n) = (1/2) * int_0^{2pi} || cos(psi) u + sin(psi) v ||_p^{-2} dpsi .
The integrand is analytic except where some component cos(psi) u_i + sin(psi) v_i
vanishes (algebraic behaviour |psi-psi0|^p at the end point) and, in the
p -> infinity limit, where |w_i| = |w_j| (transition layers of width O(1/p)).
Both families of points are computed in closed form and used as panel end
points; each panel is integrated with the double-exponential (tanh-sinh) rule,
which resolves endpoint algebraic behaviour and geometric layers.  Convergence
is checked by halving the step h: every level is returned.

Independent cross-check: `area_nested` never uses the polar formula -- for each
s it solves || s u + t v ||_p = 1 for t by bisection and integrates 2 t(s).

Exact checks for polytopes: `section_area_edges` clips the edge set of a
polytope (octahedron = B_1^3, cube = B_inf^3) with the plane and returns the
shoelace area of the resulting convex polygon.
"""

import math

try:  # numpy is only a speed-up; every routine has a pure-python path
    import numpy as _np
    HAVE_NP = True
except Exception:  # pragma: no cover
    _np = None
    HAVE_NP = False

TWO_PI = 2.0 * math.pi
_TS_CACHE = {}


# ---------------------------------------------------------------- small helpers
def lp_norm3(w, p):
    return (abs(float(w[0])) ** p + abs(float(w[1])) ** p + abs(float(w[2])) ** p) ** (1.0 / p)


def unit(v):
    nrm = math.sqrt(float(v[0]) ** 2 + float(v[1]) ** 2 + float(v[2]) ** 2)
    if nrm == 0.0:
        raise ValueError("zero vector")
    return (float(v[0]) / nrm, float(v[1]) / nrm, float(v[2]) / nrm)


def plane_basis(n):
    """Orthonormal (n_hat, u, v) with u,v spanning n^perp."""
    nh = unit((n[0], n[1], n[2]))
    a = (1.0, 0.0, 0.0)
    if abs(nh[0]) > 0.9:
        a = (0.0, 1.0, 0.0)
    d = a[0] * nh[0] + a[1] * nh[1] + a[2] * nh[2]
    u = unit((a[0] - d * nh[0], a[1] - d * nh[1], a[2] - d * nh[2]))
    v = (nh[1] * u[2] - nh[2] * u[1],
         nh[2] * u[0] - nh[0] * u[2],
         nh[0] * u[1] - nh[1] * u[0])
    return nh, u, unit(v)


def break_points(u, v, tol=1e-13):
    """psi in [0,2pi) where some w_i vanishes, or where two |w_i| coincide.

    These are the only places where the polar integrand is not analytic
    (vanishings: algebraic |psi-psi0|^p behaviour; coincidences: the O(1/p)
    layers of the p -> infinity limit).  All of them are exact roots of a
    two-term trig equation, hence computable in closed form.
    """
    cands = []
    for i in range(3):
        A, B = float(u[i]), float(v[i])
        if abs(A) < tol and abs(B) < tol:
            continue
        _p0 = math.atan2(-A, B) % TWO_PI
        cands.append(_p0)
        cands.append((_p0 + math.pi) % TWO_PI)
    for i in range(3):
        for j in range(i + 1, 3):
            for sgn in (1.0, -1.0):
                A = float(u[i]) - sgn * float(u[j])
                B = float(v[i]) - sgn * float(v[j])
                if abs(A) < tol and abs(B) < tol:
                    continue
                _p0 = math.atan2(-A, B) % TWO_PI
                cands.append(_p0)
                cands.append((_p0 + math.pi) % TWO_PI)
    pts = [0.0]
    for c in sorted(cands):
        if c - pts[-1] > 1e-11 and TWO_PI - c > 1e-11:
            pts.append(c)
    pts.append(TWO_PI)
    return pts


# ------------------------------------------------------------------- quadrature
def ts_nodes(h, T=4.2):
    """tanh-sinh nodes: psi = c + d*tanh((pi/2) sinh t), t = k h, |t| <= T."""
    key = (h, T)
    got = _TS_CACHE.get(key)
    if got is not None:
        return got
    kmax = int(math.ceil(T / h))
    ths = []
    wcs = []
    for k in range(-kmax, kmax + 1):
        t = k * h
        arg = 0.5 * math.pi * math.sinh(t)
        ths.append(math.tanh(arg))
        ch = math.cosh(arg)
        wcs.append(0.5 * math.pi * math.cosh(t) / (ch * ch))
    _TS_CACHE[key] = (ths, wcs)
    return ths, wcs


def _ts_panel(f, a, b, h, T=4.2):
    d = 0.5 * (b - a)
    if d <= 0.0:
        return 0.0
    c = 0.5 * (a + b)
    ths, wcs = ts_nodes(h, T)
    xs = [c + d * t for t in ths]
    fx = f(xs)
    if HAVE_NP:
        return float(_np.dot(_np.asarray(fx, dtype=float), _np.asarray(wcs, dtype=float)) * d * h)
    return sum(fv * wv for fv, wv in zip(fx, wcs)) * d * h


def make_integrand(u, v, p):
    """psi |-> ||cos(psi) u + sin(psi) v||_p^{-2} ; accepts a list, returns list/array."""
    u1, u2, u3 = float(u[0]), float(u[1]), float(u[2])
    v1, v2, v3 = float(v[0]), float(v[1]), float(v[2])
    if HAVE_NP:
        def f(psi):
            x = _np.asarray(psi, dtype=float)
            c = _np.cos(x)
            s = _np.sin(x)
            t = (_np.abs(c * u1 + s * v1) ** p
                 + _np.abs(c * u2 + s * v2) ** p
                 + _np.abs(c * u3 + s * v3) ** p)
            return t ** (-2.0 / p)
        return f

    def f(psi):
        out = []
        for x in psi:
            c = math.cos(x)
            s = math.sin(x)
            t = (abs(c * u1 + s * v1) ** p
                 + abs(c * u2 + s * v2) ** p
                 + abs(c * u3 + s * v3) ** p)
            out.append(t ** (-2.0 / p))
        return out
    return f


def area_polar(n, p, h_list=(0.5, 0.25, 0.125, 0.0625), T=4.2):
    """A_p(n) by polar quadrature; returns (value_finest_h, err_est, info)."""
    nh, u, v = plane_basis(n)
    pts = break_points(u, v)
    f = make_integrand(u, v, p)
    vals = []
    for h in h_list:
        tot = 0.0
        for j in range(len(pts) - 1):
            tot += _ts_panel(f, pts[j], pts[j + 1], h, T)
        vals.append(0.5 * tot)
    best = vals[-1]
    err = abs(vals[-1] - vals[-2]) if len(vals) > 1 else float("nan")
    return best, err, {"vals": vals, "panels": len(pts) - 1}


# ------------------------------------------------- independent nested method
def area_nested(n, p, npts=2401, bisect_iters=80):
    """A_p(n) without the polar formula: t-interval by bisection, Simpson in s."""
    nh, u, v = plane_basis(n)
    up = lp_norm3(u, p)
    vp = lp_norm3(v, p)
    smax = 1.0 / up
    u1, u2, u3 = u
    v1, v2, v3 = v

    def tmax(s):
        lo, hi = 0.0, 1.0 / vp
        for _ in range(bisect_iters):
            mid = 0.5 * (lo + hi)
            w0 = s * u1 + mid * v1
            w1 = s * u2 + mid * v2
            w2 = s * u3 + mid * v3
            q = (abs(w0) ** p + abs(w1) ** p + abs(w2) ** p) ** (1.0 / p)
            if q <= 1.0:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-16 * max(1.0, hi):
                break
        return 0.5 * (lo + hi)

    m = npts if (npts % 2 == 1) else npts + 1
    step = 2.0 * smax / (m - 1)
    tot = 0.0
    for i in range(m):
        s = -smax + i * step
        val = 2.0 * tmax(s)
        if i == 0 or i == m - 1:
            tot += val
        elif i % 2 == 1:
            tot += 4.0 * val
        else:
            tot += 2.0 * val
    return tot * step / 3.0


# --------------------------------------------------------- exact polytope check
CUBE_VERTS = [(sx, sy, sz) for sx in (-1.0, 1.0) for sy in (-1.0, 1.0) for sz in (-1.0, 1.0)]


def cube_edges():
    E = []
    V = CUBE_VERTS
    for i in range(len(V)):
        for j in range(i + 1, len(V)):
            d = sum(1 for k in range(3) if V[i][k] != V[j][k])
            if d == 1:
                E.append((V[i], V[j]))
    return E


OCT_VERTS = [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
             (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)]


def oct_edges():
    V = OCT_VERTS
    E = []
    for i in range(len(V)):
        for j in range(i + 1, len(V)):
            if (abs(V[i][0] + V[j][0]) + abs(V[i][1] + V[j][1]) + abs(V[i][2] + V[j][2])) < 0.5:
                continue  # antipodal pair: not an edge
            E.append((V[i], V[j]))
    return E


def section_area_edges(edges, n):
    """Area of the section of a polytope by the plane n.x = 0 (shoelace)."""
    nh, u, v = plane_basis(n)
    pts = []
    for (a, b) in edges:
        da = nh[0] * a[0] + nh[1] * a[1] + nh[2] * a[2]
        db = nh[0] * b[0] + nh[1] * b[1] + nh[2] * b[2]
        if abs(da) < 1e-15:
            pts.append((float(a[0]), float(a[1]), float(a[2])))
        if abs(db) < 1e-15:
            pts.append((float(b[0]), float(b[1]), float(b[2])))
        if da * db < 0.0:
            t = da / (da - db)
            pts.append((a[0] + t * (b[0] - a[0]),
                        a[1] + t * (b[1] - a[1]),
                        a[2] + t * (b[2] - a[2])))
    uniq = []
    for q in pts:
        if not any((q[0] - r[0]) ** 2 + (q[1] - r[1]) ** 2 + (q[2] - r[2]) ** 2 < 1e-24 for r in uniq):
            uniq.append(q)
    if len(uniq) < 3:
        return 0.0
    order = sorted(range(len(uniq)),
                   key=lambda i: math.atan2(_dot(uniq[i], v), _dot(uniq[i], u)))
    P = [uniq[i] for i in order]
    acc = 0.0
    for i in range(len(P)):
        q = P[i]
        r = P[(i + 1) % len(P)]
        acc += _dot(q, u) * _dot(r, v) - _dot(r, u) * _dot(q, v)
    return 0.5 * abs(acc)


def _dot(a, b):
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


# ------------------------------------------------------------------ closed form
def area_coord_analytic(p):
    """Coordinate section of B_p^3: 4 Gamma(1+1/p)^2 / Gamma(1+2/p)."""
    return 4.0 * math.gamma(1.0 + 1.0 / p) ** 2 / math.gamma(1.0 + 2.0 / p)
