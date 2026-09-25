# Independent numerical reproduction of

**Jiaqi Yu, _Cospectral periodic graphs: the spectrum does not determine the
graph_, 2026-09-21 (unpublished)**

Everything in this directory was written from the paper's **text** alone. The
paper's own scripts (`code/verify_all.py`, `code/spec_K_proof.py`) were **not
distributed** with the manuscript and were not available to us, so **nothing
here is copied** — the algorithms, the derivation of the chamber-graph Floquet
matrix, and every check are independent. All five experiments end with
`ALL CHECKS PASS` on a clean run and each has at least one negative control that
forces `ALL CHECKS FAIL` with a non-zero exit code.

**Nothing here is a proof.** Every `REPRO_RESULT` line carries
`"evidence_kind": "cross_check"`. The paper says the same about its own Section 5
(`main-paper-text.txt:404`: *"No numerical output is used as a proof: every
statement is proved in the text."*).

Line references of the form `text:NNN` point to
`../main-paper-text.txt`; `pdf:pN` means page N of `../main.pdf` (checked with
PyMuPDF 1.28.2).

---

## 1. Files

| file | role |
|---|---|
| `repro_common.py` | shared building blocks: `K(m)`, the affine Weyl group `W_a = Q^v ⋊ S_m`, girth algorithms, Floquet matrices for both graphs, spectral utilities |
| `repro_lattice.py` | exact-integer lattice bookkeeping (period lattice `Q^v`, `Λ = mQ^v`, its index, the cell `V_K/Λ`) |
| `repro_result.py` | the tiny harness: `REPRO_RESULT` line, `ALL CHECKS PASS/FAIL` banner, exit code, JSON file |
| `exp1_k_spectrum.py` | Theorem 1.3 — `Spec K(m) = [-m, m]` |
| `exp2_girths.py` | Theorem 1.4 — `girth K(m) = 6`, `girth S̃_m = 6` (m=3) / `4` (m≥4) |
| `exp3_chamber_spectrum.py` | Remark 1.6 / the open problem — the spectrum of `S̃_m` |
| `exp4_size_regularity.py` | Lemma 2.2 + Remark 2.3 — cell size and regularity |
| `exp5_noniso.py` | Theorem 1.5 — same spectrum, different girth, not isomorphic |
| `run_all.py` | runs all five, then all nine negative controls, prints one table and `ALL CHECKS PASS/FAIL` |

Run everything:

```powershell
cd D:\Incubator\test\test2\repro
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python run_all.py --json ..\repro-summary.json
```

Every experiment also runs standalone:

```powershell
python exp1_k_spectrum.py --m 3,4,5 --json ..\out.json
python exp1_k_spectrum.py --inject-bug double_count --json ..\out.json   # must FAIL
```

### Hard time budget — no script can hang

Every experiment takes `--max-seconds` and enforces it between units of work.
When the budget runs out the script **stops starting new work**, records an
explicit `budget_not_exceeded` check with severity `undecided`, prints
`ALL CHECKS INCONCLUSIVE` and exits with code **2**. It never runs until an
external timeout kills it.

| script | default `--max-seconds` | measured clean runtime |
|---|---|---|
| `exp1_k_spectrum.py` | 60 | ~1.7 s |
| `exp2_girths.py` | 60 | ~0.4 s |
| `exp3_chamber_spectrum.py` | 300 (the 720×720 `m=6` cell needs ~160 s) | ~177 s |
| `exp4_size_regularity.py` | 60 | ~0.7 s |
| `exp5_noniso.py` | 60 | ~0.4 s |

Exit-code contract: `0` = `ALL CHECKS PASS` (result `supports`), `1` =
`ALL CHECKS FAIL` (result `refutes`), `2` = `ALL CHECKS INCONCLUSIVE` (result
`inconclusive`). `run_all.py` refuses to count an inconclusive or crashed run as
a positive conclusion.

Example of the budget path in action:

```
$ python exp3_chamber_spectrum.py --max-seconds 5
REPRO_RESULT: {..., "result": "inconclusive", "evidence_kind": "cross_check",
               "negation_kind": "no_local_evidence", ...}
ALL CHECKS INCONCLUSIVE
  UNDECIDED CHECK budget_not_exceeded :: exp3: 14.7s elapsed of the 5.0s budget
  -- work stopped at 'start of open case m=6'. ... the run is INCONCLUSIVE
  rather than a hang.
[exit code: 2]
```

---

## 2. Experiment → claim map

| experiment | paper claim | text reference | result |
|---|---|---|---|
| exp1 (a) | identity character gives the adjacency matrix, extremes exactly `±m` | Lemma 3.1(iii) `text:234-246`; §5 `text:392-397` | cross_check |
| exp1 (b) | sampled eigenvalues stay in `[-m, m]` | triangle inequality `text:291-292` | cross_check |
| exp1 (c) | explicit witness for `S = 0` (not grid-searched) | `text:293-296` | cross_check |
| exp1 (d) | continuous path sweeps the interval | connectedness `text:297-298` | cross_check |
| exp1 (e) | coarse grid misses `S = 0` | Remark 3.3 `text:305-310` | cross_check + **not reproduced**, see §6 |
| exp1 (f) | double-counting edges gives `λmax = 2m-1` | Remark 3.5 `text:315-320` | cross_check |
| exp2 | `girth K(m) = 6`; `girth S̃_3 = 6`, `girth S̃_m = 4` (m≥4) | Theorem 1.4 `text:70-71`, `text:323-380`; Example 1.8 `text:89-104` | cross_check |
| exp3 | `Spec S̃_m = [-m,m]` for `3 ≤ m ≤ 5` | **Remark 1.6 `text:77-81` — QUOTED from [6, Thm. 6.5], not proved here** | cross_check, `not_proved` |
| exp3 (m=6) | equality for `m ≥ 6` | **open problem `text:407-417`** | cross_check, no claim |
| exp4 | `|V_K/Λ| = 2m^{m-1}` = 18/128/1250, `m`-regular | Lemma 2.2 `text:127-145`, Remark 2.3 `text:146-163`, §5 `text:389-391` | cross_check |
| exp5 | `m ∈ {4,5}`: same degree, same rank, same spectrum, girth `6 ≠ 4` ⇒ not isomorphic | Theorem 1.5 `text:72-76` | cross_check |

All `evidence_kind` values are `cross_check`. No other kind is ever emitted.

---

## 3. What the paper proves vs. what we independently verified

| claim | status in the paper | what we did | verdict |
|---|---|---|---|
| `K(m)` is `Q^v`-periodic, rank `m-1`, **exactly two orbits**, `m`-regular, vertex-transitive | proved (Lemma 2.2, `text:127-145`) | recomputed: 2 levels, all vertices have exactly `m` neighbours in `V_K`, translation by coroots preserves adjacency | cross_check ✓ |
| `[Q^v : mQ^v] = m^{m-1}` | proved (Remark 2.3, `text:158-162`) | exact integer arithmetic: determinant of the coordinate matrix of `mQ^v` in the coroot basis, its Smith normal form, and a residue count — all three agree (9 / 64 / 625) | cross_check ✓ |
| `|V_K/Λ| = 2m^{m-1}` = 18 / 128 / 1250 | proved (§5, `text:389-391`) | canonical residues `(x_1..x_{m-1} mod m, Σx_i)`; **all** `2m^{m-1}` residue pairs are realised by vertices | cross_check ✓ |
| cell of `K(m)`: two vertices, `m` parallel edges, voltages `0, e_1, …, e_{m-1}`, `Spec A_χ = {±|S(χ)|}` | proved (Lemma 3.1, `text:234-246`) | implemented the multigraph Floquet matrix per Definition 2.4 + Remark 2.6; `λmax = m` = degree at `χ = 1` | cross_check ✓ |
| `Spec K(m) = [-m, m]`, all `m ≥ 3` | **proved** (Theorem 1.3, `text:278-299`) | sampled `χ` on grids + 200 random characters; explicit algebraic witnesses for `S = 0` (errors ≤ 4.1e-16); continuous paths from `χ₀` to the witness | cross_check ✓ |
| `girth K(m) = 6` | **proved** (Theorem 1.4, `text:323-337`) | two independent algorithms (edge-deletion shortest cycle, exhaustive simple-cycle DFS) + exhaustive enumeration of cycles through `0^m` of length 3…7 (`{3:0, 4:0, 5:0, 6:6, 7:0}` for m=3) + the paper's explicit 6-cycle verified edge by edge | cross_check ✓ |
| `girth S̃_3 = 6`, `girth S̃_m = 4` (m≥4) | **proved** (Theorem 1.4, `text:338-380`) | same two algorithms on the radius-6 word-metric ball (64 / 195 / 456 elements) + explicit 4-cycle `1,s_1,s_1s_3,s_3` and the parabolic 6-cycle `1,s_i,s_is_j,s_is_js_i,(s_is_j)²,s_j,1` | cross_check ✓ |
| `Spec S̃_m = [-m, m]` for `3 ≤ m ≤ 5` | **QUOTED, not proved**: `[6, Thm. 6.5]` (Remark 1.6, `text:77-81`) | built the cell `W_a/Q^v ≅ S_m` from Definition 1.2 and sampled its `m! × m!` Floquet matrix; no counterexample found; Hermiticity gate passes | **not independently verified** — only "no counterexample found" |
| `Spec S̃_m = [-m, m]` for `m ≥ 6` | **OPEN** (`text:407-417`); only `⊆ [-m,m]` and the endpoints `±m` are proved | sampled `m = 6` (720×720 cell) on a 3-points-per-angle grid (243 characters, 174 960 eigenvalues, ~198 s) and along 3 paths; eigenvalues stayed inside `[-6,6]`, endpoints reached | **no claim**; the paper's obstruction is untouched |
| `K(m) ≇ S̃_m` for `m = 4,5` | **proved** (Theorem 1.5, `text:72-76`) | degree 4/4 and 5/5; girth 6 vs 4 by two algorithms + explicit cycles; the two cell sizes differ (2 vs `m!`) | cross_check ✓ |
| the *pair is cospectral* | rests on the **quote** above | endpoint agreement and containment were checked numerically | **partially cross-checked only** |

### The unbridgeable half

`Spec S̃_m = [-m, m]` for `3 ≤ m ≤ 5` is the load-bearing external input of
Theorem 1.5. It is **quoted** from a companion book `[6]` whose bibliographic
data the paper does not even give (`text:457-458` says only *"Companion book on
quotient lattices, tori and periodic graphs, vol. 11, Theorem 6.5"*). That book
is **not in our reach**, so:

* we cannot verify the quoted theorem;
* we can only build the cell independently and **fail to find a counterexample**;
* consequently, **the cospectrality half of Theorem 1.5 is not independently
  verified by this reproduction**. It is only *not contradicted*.

The paper is explicit and honest about this itself (`text:439-442`,
"Provenance of `S̃_m`'s spectrum").

---

## 4. The Floquet matrix of `S̃_m` — my own derivation

This is the most valuable part of the reproduction, because the paper only
states the cell as "m! vertices" and never writes the matrix down. Derivation
(from Definitions 1.2 / 2.4 and Remark 2.6 only):

1. The translation lattice acts by **left** translation,
   `μ·(w, λ) = (w, λ+μ)` (`text:61-63`: *"it acts on `W_a` by left translation"*).
   Therefore the cell — the quotient by the translation lattice — is
   ```
   W_a / Q^v  ≅  S_m ,    class of (w, λ)  ↦  w ,
   ```
   with `m!` vertices (Lemma 2.2, `text:130`), and the class is exactly the
   permutation part.
2. Right multiplication by a generator `s = (s_w, λ_s)` is
   ```
   (w, λ)·s = (w s_w, λ + w(λ_s)) .
   ```
   So it takes the class `w` to the class `w s_w`, and the translation vector
   **realising** that transition is `w(λ_s)` — it depends on the **source**
   class `w`, not only on the target.
3. Definition 2.4 (`text:164-172`) defines the Floquet entry as the sum of
   `χ(λ)` over all adjacencies inducing the class transition, and Remark 2.6
   (`text:197-201`) says parallel edges are summed. Hence
   ```
   A_χ(w, w·s_w)  +=  χ( w(λ_s) )      for every generator s ∈ {s_0, …, s_{m-1}},
   ```
   with `χ(λ) = exp(2πi ⟨z, (λ_1,…,λ_{m-1})⟩)`, `z ∈ [0,1)^{m-1}`. The first
   `m-1` coordinates determine `λ` because `Σλ_i = 0`.
4. Specialisation: for `s_i` (i ≥ 1) `λ_s = 0`, so `χ(0) = 1`; only `s_0` is
   non-trivial. `θ = e_1 - e_m` has first `m-1` coordinates `(1,0,…,0)`, so
   `w(θ)_1 = 1 ⟺ w^{-1}(1) = 1`.

**How the formula was checked** (the checks would fail if the derivation were
wrong, which is the point):

* **Hermiticity** `‖A_χ − A_χ^H‖ < 1e-12` on every sampled character. The
  reverse transition is realised by `χ(w'(λ_s)) = conj(χ(w(λ_s)))`, so the
  correct voltage is automatically Hermitian. Measured defect: **exactly 0.0**
  (the entries are exact conjugates because the same generator set is used in
  both directions).
* **`χ = 1` is the genuine adjacency matrix** of the Cayley graph of `S_m` on
  `{τ_0,…,τ_{m-1}}`: measured `λmax = m`, `λmin = -m` to 1e-12 (e.g. for `m=4`
  the 24 eigenvalues run `-4, -2 (×7), 0 (×8), +2 (×7), +4`).
* **Voltage well-definedness**: replacing the representative `(w,λ)` by
  `(w, λ+μ)` (same class) must keep the target class and shift the voltage by
  exactly `μ` — verified on all classes for `m = 4` (96 trials).
* **Cell degree**: every class has exactly `m` outgoing Cayley edges and no
  self-loop (all generators satisfy `s_w ≠ 1`).
* **Second numerical route**: `eigvalsh(A_χ)` agrees with the eigenvalues of the
  real symmetric `2n × 2n` form to ≤ 1e-9.
* **`χ = 1` endpoint = degree**, the very comparison that catches the error of
  Remark 3.5.
* **Negative control `transpose_voltage`** (using `χ(λ_s)` instead of
  `χ(w(λ_s))`) destroys Hermiticity: defect `4.9` (m=3), `9.6` (m=4), `21.9`
  (m=5) — the 1e-12 gate catches it immediately.

### Group-law conventions (a genuine trap)

`W_a = Q^v ⋊ S_m` with `(w,λ)(v,μ) = (wv, λ + w(μ))` (`text:49-50`, `text:399`)
is only associative if the composition of permutations and the coordinate action
are chosen consistently. We use

* `perm_mul(w,v) = w ∘ v`, i.e. `(wv)(i) = w(v(i))`, and
* `perm_act(w,x)_i = x_{w^{-1}(i)}` (the standard coordinate action).

With the inconsistent mixture `(wv, λ + v(μ))` associativity **fails** (caught
by a named check on random triples), and the radius-6 ball for `m=3` grows from
**64** to **114** elements while the girth is still computed as 6 — so **the
girth alone cannot detect a wrong group law**; the associativity check and the
ball size are what catch it. Independently, `s_0 = (τ_0, θ)` is verified to act
as the affine reflection `x ↦ x − (⟨x,θ⟩ − 1)θ`, i.e. in the wall `⟨x,θ⟩ = 1`,
which pins the realisation down geometrically.

*Verified group facts:* `s_i² = e`; `(s_i s_j)^{m_ij} = e` with `m_ij` read off
the **affine Cartan matrix** (`A_ij A_ji = 4cos²(π/m_ij)`), which matches the
orders measured in the realised group for `m = 3,4,5`; the `m` generators are
distinct; associativity holds; and for every ball element with `λ = 0` the word
length equals the inversion number of `w`.

*Labelling warning (worth recording):* with `s_0 = (τ_0, θ)`, `τ_0 = (1 m)`, the
affine node `s_0` is adjacent in the Dynkin diagram to `s_1` **and** `s_{m-1}` —
so the diagram is the cycle `0-1-…-(m-1)-0`, but **not in cycle order**: reading
the nodes `0,1,…,m-1` does not walk around the cycle. In particular
`(s_0 s_2)³ = e`, not `(s_0 s_2)² = e`. The paper's Definition 1.2 is correct;
the naive "cycle order" reading of the labels is what is wrong.

---

## 5. Negative controls (`--inject-bug`)

Every control is run by `run_all.py` too, and the aggregate check requires that
each control **failed with the right check named** (not merely non-zero exit).

| `--inject-bug` | script | what error it simulates | which check catches it | observed |
|---|---|---|---|---|
| `coarse_grid` | exp1 | Remark 3.3's trap: trusting a coarse character grid to find `S = 0` | `m*.e.coarse_grid_finds_the_zero` | 60-point grid (offset half a step) reports `min|S| ≈ 0.052` (m=3,4), `0.0058` (m=5) instead of `0` |
| `double_count` | exp1 | Remark 3.5: counting each of the `2m` directed steps as its own cell edge | `m*.a.identity_char_lambda_max_is_degree`, `m*.b.sampled_eigenvalues_in_interval`, `m*.f.lambda_max_catches_double_count` | `S(1) = 2m−1` (= 5/7/9), `λmax = 2m−1 ≠ m` |
| `allow_backtrack` | exp2 | counting `x → x+e_i → x` as a 2-cycle | `m*.K.no_backtrack_2cycles`, `m*.S.girth_matches_theorem` | girth reported as 2 for both graphs |
| `wrong_s0` | exp2 | dropping the translation part of `s_0`: `s_0 = (τ_0, 0)` | `m*.S.affine_reflection_intact`, `m*.S.girth_matches_theorem` | the radius-6 ball collapses to `m!` (6 for m=3), girth `S̃_3` becomes 4 |
| `transpose_voltage` | exp3 | voltage `χ(λ_s)` instead of `χ(w(λ_s))` (the `w·` dropped) | `m*.Hermiticity_gate`, also `m*.sampled_union_fills_interval`, `m*.real_symmetric_form_agrees` | Hermiticity defect 4.9 / 9.6 / 21.9 ≫ 1e-12 |
| `lattice_Q` | exp4 | using `Λ = Q^v` instead of `Λ = mQ^v` (Remark 2.3's warning) | `m*.class_count_is_2_m_pow_m_minus_1` | class count collapses to **2** instead of 18/128/1250 |
| `same_girth` | exp5 | reporting `girth S̃_m` as equal to `girth K(m)` | `m*.not_isomorphic_because_girth_differs` | the only isomorphism separator becomes vacuous |

**Every assertion can fail.** No check is a tautology: all of them compare a
computed number against a value fixed *before* the computation, and each was
observed to fail under its control. `run_all.py` verifies not merely that each
control exited non-zero, but that the failing check is **named** in the JSON.

### Two measured incidents worth recording (framework behaviour)

**(1) A failed check was refused as evidence.** During acceptance the harness
(role `E`, `AgentE.run_experiment`) ran the five scripts and reported:

```
[0004] nonisomorphic_cospectral  result=inconclusive  kind=heuristic  neg=no_local_evidence
       exit=1  runtime=5.984s
```

`exp5_noniso.py` then had an over-coarse grid in an interval-filling check
(8 points per angle ⇒ a 0.586 gap on `[-4,4]`, 7.3% of the interval), so that one
check failed and the script exited 1. The framework **refused** to record the run
as evidence: it logged `inconclusive / no_local_evidence` and preserved the raw
stdout, even though the stdout carried a `REPRO_RESULT` line. That is the correct
behaviour for "computational results are not proofs, and a crash is never a
conclusion".

**(2) An over-eager fix then *hung*, and that was worse.** Reaching for a denser
grid to make that check pass (16 points per angle for the 120×120 `m=5` cell =
65 536 characters × `eigvalsh`) turned a 6-second script into one that produced
no output for minutes. A reproduction script that hangs is worse than one that
fails: in a framework it burns a 900-second timeout and drags the whole
acceptance chain with it.

**The fix was to correct the experiment's scope, not to patch the number.**
Interval-*filling* is an analytic statement — continuity of `χ ↦ |S(χ)|` on the
connected torus together with the two attained values — so it belongs to `exp1`
(`K(m)`, which has the explicit witness and the continuous path) and `exp3`
(`S̃_m`). `exp5` needs only the *endpoint* agreement, which the identity character
gives exactly. In addition every script now enforces a hard `--max-seconds`
budget (see §1) so that no future resolution change can silently hang. Measured
effect: `exp5` went from hanging (> 180 s, killed) to **0.4 s**, and it still
catches its injected bug.

---

## 6. Claims we could **not** verify / refuse to claim

1. **`Spec S̃_m = [-m, m]` for `3 ≤ m ≤ 5` is not verified.** It is a quote from
   `[6, Thm. 6.5]`; the book is unavailable and the paper omits its full
   bibliographic data. We independently built the cell and searched for a
   counterexample; we found none. "No counterexample found" ≠ "verified", and
   the `REPRO_RESULT` for exp3 says `supports` **with**
   `"negation_kind": "not_proved"` and `"independently_verified": false`.
2. **The open case `m ≥ 6` is not resolved.** Our numerics for `m = 6` are
   *consistent* with `Spec S̃_6 = [-6,6]` (243 characters, 174 960 eigenvalues,
   all inside `[-6,6]`, both endpoints reached, max gap 0.121 = 1.0% of the
   interval; 3 continuous paths, 1 860 eigenvalues, max gap 0.022). But the
   paper's obstruction is that *"one must show that two branches meet, with no
   explicit witness available"* (`text:414-417`). Filling an interval with
   samples can never show that two eigenvalue branches **intersect**; the
   `m = 6` block is marked `resolves_the_obstruction: false` and the run reports
   it as a counterexample search only.
3. **`m = 5` and `m = 6` `S̃_m` "branch meeting"** is a related weak point: a
   *single* generic character already gives `min|λ| ≈ 0` because the two branches
   cross somewhere, so `min|λ|` is a very weak signal. That check is deliberately
   coarse (threshold `0.05·m`) and its detail string says so; it is reported next
   to the raw `min|λ|` so a reader can judge for themselves.
4. **Remark 3.3's "≈ 0.04" is not reproduced — and we do not claim it is.** In
   our natural parameterisation `χ(e_i) = exp(2πi z_i)` with the grid
   `z ∈ {j/60}^{m-1}`, the sampled minimum of `|S|` for `m = 4` is **exactly 0**,
   not 0.04: the witness `(z_1,z_2,z_3) = (0.4, 0.5, 0.9)` (i.e. `1 + (−1) +
   i + (−i)`) *is* a grid point. Only after offsetting the grid by half a step
   does the coarse minimum become nonzero (0.0058–0.052). So the specific number
   0.04 depends on the grid convention and is not reproducible from the paper's
   description; what **is** reproducible and true is the underlying point — a
   coarse grid can miss the zero, which is why the explicit witness matters. The
   `coarse_grid` control therefore *constructs* the convention under which a
   coarse grid misses zero and shows the check firing; it is a **diagnostic**,
   not a reproduction of the number 0.04.
5. **`Spec K(m)` for large `m` is only sampled at `m = 3,4,5`.** The proof is
   for all `m ≥ 3`; our numerics cover three values. (The witness argument for
   `S = 0` is written for general `m` and was checked at `m = 3..6`.)
6. **The affine Coxeter length formula is not verified.** We verified
   `l(w) = inv(w)` for all ball elements with `λ = 0`; the length formula for
   `λ ≠ 0` needs the affine root system with roots `α + kδ` paired with the
   coroots, which this code does not implement. The group law is instead pinned
   down by associativity, the Cartan/Coxeter-matrix match, and the affine
   reflection test.
7. **Conventions.** The paper typesets equation (6) with `S` in *both*
   off-diagonal slots (`pdf:p5`), while its own sentence says *"and the conjugate
   in the opposite direction"* and it asserts `Spec A_χ = {±|S|}`. We implement
   the conjugate (the typeset version would not even be Hermitian for complex
   `S`). This is a typographical ambiguity in the paper, not an error of
   substance. Likewise the paper's `s_1 s_0` is written `(1 0 2 3)`; with our
   composition convention the product is the transposition `(1 m)`, which **is**
   `(1 0 2 3)` read as a one-line map `1 ↦ 0`, `0 ↦ 1` — consistent, but it
   shows the paper and this code use the same one-line convention read in
   opposite directions. This does not affect any computed invariant (the Cayley
   graph is isomorphic under `w ↦ w^{-1}` and the generators are involutions).
8. **`m` regularity via a box needs care.** A box-induced degree profile over
   the *whole* box is **not** a valid regularity test: neighbours that leave the
   box are lost, so for `m = 3`, box 2, the induced degrees are `{2,3}` and one
   would wrongly conclude irregularity. `exp4` therefore tests (a) the neighbour
   count in `V_K` (exactly `m` everywhere) and (b) the induced degree of
   **interior** vertices only (exactly `m`), and reports the boundary effect
   explicitly.
9. **Counting classes by enumerating a box is wrong.** `V_K ∩ [-b,b]^m` reduced
   modulo `m` misses classes (a representative may need large coordinates), so
   the count is done by residue algebra and then verified to be **onto** the
   `2m^{m-1}` candidate pairs.
10. **We did not check that no finer spectral invariant separates the pair**
    (Remark 1.7, `text:82-88`, explicitly leaves the density of states open),
    and we did not attempt it.
11. **Cell isomorphism is not a graph invariant.** The cells of `K(m)` and `S̃_m`
    have 2 and `m!` vertices, which is structural information about the chosen
    period lattices; the paper's actual separator is the girth, and that is what
    we use (`text:421-424` mentions the cell question as a separate one).

---

## 7. Scope decisions (what each experiment deliberately does *not* do)

* **`exp5` does not re-check interval filling.** It checks (i) degree, (ii)
  periodic rank, (iii) girths `6 ≠ 4` by two algorithms plus explicit cycles,
  (iv) both spectra attain exactly `±m` and lie inside `[-m,m]`, (v) the cells
  differ. Filling is an analytic statement and is covered by exp1 (K) and exp3
  (`S̃`). This keeps `exp5` at ~0.5 s and avoids re-measuring a grid.
* **`exp3`'s `m = 6` block is reported, not asserted.** Its fill check has
  *severity* `undecided`: a miss yields `result = "inconclusive"` and
  `negation_kind = "no_local_evidence"` rather than a claim in either direction.
* **Resolution is always recorded in the JSON** (`grid_points_per_angle`,
  `grid_total`, `n_eigenvalues`, `seconds`, `path_*`), so no sampling density is
  hidden.
* **The 60-point grid time cost is bounded on purpose.** For `m = 6` the cell is
  720×720 and one `eigvalsh` costs ≈ 0.27 s, so the grid resolution was chosen
  from a measured budget (243 characters ≈ 97 s, plus 3 paths ≈ 0.6 s) — well
  inside the 300 s per-`m` budget, and stated in the JSON.

---

## 8. Environment

* Python 3.11.4, NumPy 2.4.6, PyMuPDF 1.28.2 (PDF reading only).
* Standard library + NumPy only; **no SciPy, no NetworkX**.
* The paper's own verification scripts were not distributed and were not used.

---

## 9. Actual run output

Command (exactly the one required by the task):

```powershell
cd D:\Incubator\test\test2\repro
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python run_all.py --json ..\repro-summary.json
```

Result: **`ALL CHECKS PASS`**, exit code 0, **total wall time 193.7 s**.

```
script                     result     kind       checks   failed  seconds
-------------------------------------------------------------------------
exp1_k_spectrum.py         supports   cross_check     15        0     1.44
exp2_girths.py             supports   cross_check     24        0     0.39
exp3_chamber_spectrum.py   supports   cross_check     42        0   166.80
exp4_size_regularity.py    supports   cross_check     24        0     0.61
exp5_noniso.py             supports   cross_check     20        0     0.38
-------------------------------------------------------------------------
exp1_k_spectrum.py  caught_the_injected_bug  cross_check  18  3   9.59  [--inject-bug coarse_grid]
exp1_k_spectrum.py  caught_the_injected_bug  cross_check  18  6   1.68  [--inject-bug double_count]
exp2_girths.py      caught_the_injected_bug  cross_check  27  6   0.35  [--inject-bug allow_backtrack]
exp2_girths.py      caught_the_injected_bug  cross_check  30  4   0.33  [--inject-bug wrong_s0]
exp3_chamber_spectrum.py caught_the_injected_bug cross_check 40 6  11.49 [--inject-bug transpose_voltage]
exp4_size_regularity.py  caught_the_injected_bug cross_check 21  3   0.31 [--inject-bug lattice_Q]
exp5_noniso.py      caught_the_injected_bug  cross_check  20  2   0.37  [--inject-bug same_girth]

criteria:
  all five experiments report supports .......... True
  every result carries evidence_kind=cross_check True
  every negative control was caught ............. True
  banners match (PASS clean / FAIL injected) .... True
  no script crashed or timed out ................ True

ALL CHECKS PASS
```

Key numbers from the clean runs (all reproducible from
`../repro-summary.json`):

* **exp1** `m3.a`: `λmax = 3.000000000000` = degree `m`; `S(1) = 3+0i`.
  `m3.b`: 3 600 sampled eigenvalues inside `[-3,3]`. `m3.c`: explicit witness
  `z = [1/3, 2/3]` gives `|S| = 3.14e-16`. `m4.c`: `z = [0.5, 0, 0.5]` gives
  `2.45e-16`. `m5.c`: `z = [0.5, 0, 1/3, 2/3]` gives `4.00e-16`.
  Path check: 5 614 path eigenvalues sweep `[-m,m]` with max gap 0.0105 / 0.0157
  / 0.0176 (0.17% / 0.20% / 0.18% of the interval).
* **exp1 `--inject-bug double_count`**: `S(1) = 5 / 7 / 9 = 2m-1`,
  `λmax = 5 / 7 / 9 ≠ m` — Remark 3.5's error, caught by the `λmax` vs degree
  comparison.
* **exp2** `m3.K.girth_equals_6` (ball 19, radius 3); exhaustive DFS agrees;
  cycles through `0³` by length: `{3:0, 4:0, 5:0, 6:6, 7:0}`. `S̃_3` girth 6
  (ball 64), `S̃_4` girth 4 (ball 195), `S̃_5` girth 4 (ball 456).
* **exp3** `cell.voltage_well_defined` (96 trials) and `cell.degree_is_m` pass
  first; Hermiticity defect **exactly 0.0** at every sampled character;
  `λmax = ±m` at `χ = 1` for the 6 / 24 / 120-vertex cells; `m=6` (720×720, 243
  characters, 174 960 eigenvalues, 160.5 s): all inside `[-6,6]`, max gap
  0.1206 = 1.01% of the interval, 3 paths give gap 0.0414, and the run reports
  `resolves_the_obstruction: false`.
* **exp4** `[Q^v : mQ^v]`: determinant 9/64/625, Smith normal form
  `[3,3]`/`[4,4,4]`/`[5,5,5,5]`, residue count 9/64/625 — all equal `m^{m-1}`.
  Class counts 18 / 128 / 1250 with every residue pair realised. Interior
  degrees exactly `m`; boundary degrees smaller (the boundary effect).
* **exp5** degrees `4/4`, `5/5`; girths `6 vs 4`; spectra both `[-4,4]` /
  `[-5,5]` with the endpoints attained exactly.

---

## 10. Corrections and findings about the paper / the brief

Findings from the original task description were checked against the paper text;
the following are worth recording:

1. **The brief's `cycles` cross-check had an off-by-one** in the direction the
   brief suggested ("closed walks of length `k` with pairwise-distinct
   intermediate vertices"): implemented literally it reports *bogus 5-cycles in a
   bipartite graph*. Only cycles of `k` **steps** with `k-1` intermediate
   vertices are genuine cycles. After fixing this, the exact counts for `K(3)`
   are `{3:0, 4:0, 5:0, 6:6, 7:0}`, matching `girth = 6`.
2. **The brief's "BFS back-edge gives `girth = dist(u)+dist(v)+1`" is not
   correct** as a girth algorithm. That quantity is the length of a closed walk
   obtained by concatenating two BFS-tree paths; the concatenation can contain a
   chord, so it can be strictly larger than the girth. The concrete failure we
   hit: for `K(3)` it reported **5** (impossible in a bipartite graph — a useful
   sanity signal in itself). This code uses the edge-deletion algorithm
   (`girth = min over edges {a,b} of dist_{G−ab}(a,b) + 1`; each candidate is a
   shortest path plus an edge, hence chordless) and cross-checks it with
   exhaustive simple-cycle DFS. The edge-deletion routine additionally refuses
   to report a candidate whose induced edge count is not exactly the cycle
   length.
3. **The brief's `S̃_m` Floquet formula is right, and the Hermiticity check is
   the right gate** — with the caveat that the *permutation-action convention*
   must be consistent with the composition convention, otherwise the group law
   is not associative (see §4). Also, `s_0`'s translation in this convention has
   `w(λ_s)_1 = 1` iff `w[0] == 0` (presentation-dependent in form, invariant in
   the resulting graph).
4. **The brief's claim that `s_1` and `s_3` "commute because they are
   non-adjacent"** reproduces the paper's own wording (`text:374-375`) but the
   fact is more robust than the diagram it is derived from: `τ_1` acts on
   `{1,2}` and `τ_3` on `{3,4}`, hence they commute for any `m ≥ 4` because the
   supports are disjoint — no diagram adjacency needs to be inspected.
5. **`wrong_s0` is caught by the affine reflection test, not by the Coxeter
   relations.** With `s_0 = (τ_0, 0)` the affine diagram happens to still be
   realised (the Coxeter-matrix check passes), and the ball collapses to the
   finite `S_m`; what fails is (i) `s_0` no longer acting as the affine
   reflection and (ii) the girth of `S̃_3` becoming 4. The brief's expectation
   ("girth ≠ theorem") is confirmed, but the primary labelled failure is the
   reflection test.
6. **Reading the brief's "Floquet matrix `[[0, S],[conj(S), 0]]`" against the
   PDF**: the text layer of equation (6) shows `S` in both slots; the sentence
   and the eigenvalue claim force the conjugate. Worth flagging as a typo.
