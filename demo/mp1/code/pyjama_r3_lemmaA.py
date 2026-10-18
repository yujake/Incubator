import json, math, random

RSEED = 20261018
rng = random.Random(RSEED)

def dist1(x):
    return abs(x - round(x))

# ---------------- Part A1: forward claim (a_i+b_i odd => dist = 1/2 at p=(1/2,1/2)) ----------------
n_sets = 200
exceptions = []
k_list = []
for t in range(n_sets):
    k = rng.randint(3, 20)
    normals = []
    guard = 0
    while len(normals) < k and guard < 20000:
        guard += 1
        a = rng.randint(-20, 20); b = rng.randint(-20, 20)
        if a == 0 and b == 0:
            continue
        if (a + b) % 2 == 0:
            continue
        normals.append((a, b))
    bad = []
    for (a, b) in normals:
        s = a + b
        d = dist1(s / 2.0)
        if abs(d - 0.5) > 1e-12:
            bad.append([a, b, s, d])
    if bad:
        exceptions.append({"k": k, "bad": bad, "normals": normals})
    k_list.append(k)

# ---------------- Part A2: reverse direction ----------------
def find_solution(normals, qmax):
    # p=(x/q,y/q) ; need 2*(a_i x + b_i y) == q (mod 2q) for all i
    for q in range(2, qmax + 1, 2):   # odd q impossible by parity (2*(ax+by)-q is odd)
        Q = q // 2
        for x in range(q):
            for y in range(q):
                ok = True
                for (a, b) in normals:
                    if (a * x + b * y - Q) % (2 * Q) != 0:
                        ok = False
                        break
                if ok:
                    return {"q": q, "x": x, "y": y}
    return None

QMAX = 30
n_rev = 200
rev_sets = 0
rev_found = []
rev_half = 0
rev_checked = 0
for t in range(n_rev):
    k = rng.randint(3, 10)
    normals = []
    guard = 0
    while len(normals) < k and guard < 20000:
        guard += 1
        a = rng.randint(-20, 20); b = rng.randint(-20, 20)
        if a == 0 and b == 0:
            continue
        normals.append((a, b))
    evens = [(a, b) for (a, b) in normals if (a + b) % 2 == 0]
    if not evens:
        continue
    rev_sets += 1
    sol = find_solution(normals, QMAX)
    rev_checked += 1
    if sol is not None:
        rev_found.append({"normals": normals, "even_normals": evens, "solution": sol})
        if sol["q"] == 2:
            rev_half += 1

out = {
    "result": "supports" if len(exceptions) == 0 else "refutes",
    "bound": {"forward_sets": n_sets, "k_range": [min(k_list), max(k_list)],
              "reverse_sets_with_even_sum": rev_sets, "qmax_reverse": QMAX},
    "strategy": "exact parity certificate at p=(1/2,1/2) (a_i+b_i / 2, odd numerator => distance exactly 1/2) + exact integer brute force over rational p=(x/q,y/q), even q<=30, for the reverse direction",
    "scaling": {"forward_cost": str(n_sets) + " sets x k<=20 point evaluations (O(sum k))",
                "reverse_cost": "sum over even q<=30 of q^2 * k modular checks per set"},
    "data": {
        "forward_exceptions_count": len(exceptions),
        "forward_exceptions": exceptions[:5],
        "reverse_witnesses_found": len(rev_found),
        "reverse_examples": rev_found[:3],
        "reverse_half_integer_points": rev_half
    }
}
if out["result"] == "refutes":
    out["counterexample"] = exceptions[0] if exceptions else None
print("REPRO_RESULT: " + json.dumps(out))
