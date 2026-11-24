"""lpsec_family.py -- independent 1-D formulas for the diagonal families of B_p^3.

Nothing here uses polar coordinates in the plane: the section of B_p^3 is written
in Cartesian (x,z) coordinates and reduced to a 1-D quadrature.  These routines
are therefore an independent cross-check of lpsec_core.area_polar, and they also
give closed forms along one whole edge of the fundamental domain.

Family (0,1,t):  n = (0,1,t)/sqrt(1+t^2), plane  y + t z = 0.
  Parametrise the plane as (x,z) -> x*e1 + z*(0,-t,1); the area element is
  sqrt(1+t^2), the constraint becomes |x|^p + (1+t^p)|z|^p <= 1, hence

      A_01t(p,t) = 4 sqrt(1+t^2) (1+t^p)^{-1/p} J(p),
      J(p) = Gamma(1+1/p)^2 / Gamma(1+2/p) = int_0^1 (1-u^p)^{1/p} du.

  In particular A_01t(p,0) = 4 J(p) is the coordinate section and
  A_01t(p,1) = 4 sqrt(2) 2^{-1/p} J(p) is the face-diagonal section, so the
  ratio along this edge is the closed-form  sqrt((1+t^2)/2) (2/(1+t^p))^{1/p}.

Family (1,1,t):  n = (1,1,t)/sqrt(2+t^2), plane  x + y + t z = 0.
  Parametrise as (x,z) -> x*(1,-1,0) + z*(0,-t,1); area element sqrt(2+t^2);
  the constraint |x|^p + |x+t z|^p + |z|^p <= 1 is convex in x for fixed z, so
  the x-fibre is an interval [x_-(z), x_+(z)] located by bisection and

      A_11t(p,t) = sqrt(2+t^2) int_{-zmax}^{zmax} (x_+ - x_-) dz,
      zmax = (1 + 2 (t/2)^p)^{-1/p},

  computed with the tanh-sinh rule, which absorbs the |zmax - z|^{1/p} endpoint
  behaviour.
"""
import math

import lpsec_core as core

BIS = 70


def J(p):
    """int_0^1 (1-u^p)^{1/p} du = Gamma(1+1/p)^2 / Gamma(1+2/p)."""
    return math.gamma(1.0 + 1.0 / p) ** 2 / math.gamma(1.0 + 2.0 / p)


def area_01t_closed(p, t):
    """Closed-form area of the central section with normal (0,1,t)."""
    at = abs(t)
    return 4.0 * math.sqrt(1.0 + at * at) * (1.0 + at ** p) ** (-1.0 / p) * J(p)


def ratio_01t_closed(p, t):
    """A_01t(p,t)/A_01t(p,0): sqrt((1+t^2)/2) * (2/(1+t^p))^{1/p}."""
    at = abs(t)
    return math.sqrt((1.0 + at * at) / 2.0) * (2.0 / (1.0 + at ** p)) ** (1.0 / p)


def _x_fibre(z, p, t):
    """Interval [x_-, x_+] of {x : |x|^p + |x+tz|^p <= 1-|z|^p}, or None."""
    c = 1.0 - abs(z) ** p
    if c <= 0.0:
        return None
    xm = -0.5 * t * z              # minimiser of |x|^p + |x+tz|^p
    fm = abs(xm) ** p + abs(xm + t * z) ** p
    if fm > c:
        return None
    cp = c ** (1.0 / p)

    def feas(x):
        return abs(x) ** p + abs(x + t * z) ** p <= c

    lo, hi = xm, cp + 1.0          # x_+ : feasible at xm, infeasible high up
    for _ in range(BIS):
        mid = 0.5 * (lo + hi)
        if feas(mid):
            lo = mid
        else:
            hi = mid
    x_plus = 0.5 * (lo + hi)

    lo, hi = -abs(t * z) - cp - 1.0, xm   # feasible at xm, infeasible far left
    for _ in range(BIS):
        mid = 0.5 * (lo + hi)
        if feas(mid):
            hi = mid
        else:
            lo = mid
    x_minus = 0.5 * (lo + hi)
    return x_minus, x_plus


def zmax_11t(p, t):
    return (1.0 + 2.0 * (abs(t) / 2.0) ** p) ** (-1.0 / p)


def area_11t_indep(p, t, h=0.125, T=4.2):
    """Independent (non-polar) area of the central section with normal (1,1,t)."""
    zm = zmax_11t(p, t)

    def f(zs):
        out = []
        for z in zs:
            r = _x_fibre(z, p, t)
            out.append(0.0 if r is None else r[1] - r[0])
        return out

    tot = 0.0
    for a, b in ((-zm, 0.0), (0.0, zm)):
        tot += core._ts_panel(f, a, b, h, T)
    return math.sqrt(2.0 + t * t) * tot
