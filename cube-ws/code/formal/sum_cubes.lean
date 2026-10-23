import Mathlib

-- step 1 （命题：对任意正整数 n，1^3+2^3+...+n^3 = (n(n+1)/2)^2）
-- step 2 （两条相互独立的证明路径：(a) 归纳法；(b) 差分/telescoping，互不引用）
-- step 3 （记号：S(n) := 1^3+2^3+...+n^3）
-- step 4 （P(n)：S(n) = (n(n+1)/2)^2）
-- step 5 （路径 (a)：数学归纳法）

/-- 两条路径共用的一步：ℕ 上 n(n+1) 恒为偶数，因此 ℕ 里的 /2 是精确值。 -/
theorem two_dvd_mul_succ (m : ℕ) : 2 ∣ m * (m + 1) := by
  induction m with
  | zero => simp
  | succ m ih =>
      obtain ⟨c, hc⟩ := ih
      refine ⟨c + (m + 1), ?_⟩
      have hstep : (m + 1) * (m + 1 + 1) = m * (m + 1) + 2 * (m + 1) := by ring
      rw [hstep, hc]
      ring

/-- ℕ 里的 /2 是精确的：2 * (m(m+1)/2) = m(m+1)。 -/
theorem two_mul_div (m : ℕ) : 2 * (m * (m + 1) / 2) = m * (m + 1) := by
  obtain ⟨c, hc⟩ := two_dvd_mul_succ m
  omega

/-- 路径 (a)：4 * S(n) = (n(n+1))^2（等价形式，避开 ℕ 除法）。 -/
theorem four_mul_sum_cubes (n : ℕ) :
    4 * (Finset.sum (Finset.range (n + 1)) (fun k => k ^ 3)) = (n * (n + 1)) ^ 2 := by
  induction n with
  | zero =>
      -- step 6 （路径 a 的基始：原文 n = 1；ℕ 版取 n = 0 两边同为 0，n = 1 是它的特例）
      simp
  | succ n ih =>
      -- step 7 （归纳步：设对某个正整数 n 有 P(n)，证 P(n+1)）
      -- step 8 （(H)：S(n) = (n(n+1)/2)^2；这里用等价式 4*S(n) = (n(n+1))^2）
      -- step 9 （目标：S(n+1) = ((n+1)(n+2)/2)^2）
      -- step 10 （第 1 步：拆出末项 S(n+1) = S(n) + (n+1)^3）
      rw [Finset.sum_range_succ]
      -- step 11 （代入 (H)：S(n+1) = (n(n+1)/2)^2 + (n+1)^3）
      rw [Nat.mul_add, ih]
      -- step 12 （第 2 步：通分到分母 4）
      -- step 13 （S(n+1) = [ n^2(n+1)^2 + 4(n+1)^3 ] / 4）
      -- step 14 （第 3 步：提取公因子 (n+1)^2）
      -- step 15 （n^2(n+1)^2 + 4(n+1)^3 = (n+1)^2 [ n^2 + 4(n+1) ]）
      -- step 16 （于是）
      -- step 17 （S(n+1) = (n+1)^2 [ n^2 + 4(n+1) ] / 4）
      -- step 18 （第 4 步：展开方括号 n^2 + 4(n+1) = n^2 + 4n + 4 = (n+2)^2）
      -- step 19 （第 5 步：配方）
      -- step 20 （S(n+1) = (n+1)^2 (n+2)^2 / 4 = [ (n+1)(n+2)/2 ]^2）
      -- step 21 （末一等号用到 (ab)^2 = a^2 b^2 与 4 = 2^2）
      -- 第 12–21 步是同一条多项式恒等式的归一化：(n(n+1))^2 + 4(n+1)^3 = ((n+1)(n+2))^2
      simp only [Nat.succ_eq_add_one]
      ring
      -- step 22 （路径 (a) 结论：由基始与归纳步，对一切 n 成立）

/-- 路径 (b) 引理 L 的加法形式（避开 ℕ 减法）：记 a_j := (j(j+1)/2)^2，
则 a_j + (j+1)^3 = a_{j+1}，即 k^3 = a_k - a_{k-1}。 -/
theorem tel_step (j : ℕ) :
    (j * (j + 1) / 2) ^ 2 + (j + 1) ^ 3 = ((j + 1) * (j + 1 + 1) / 2) ^ 2 := by
  -- step 23 （路径 (b)：差分 / telescoping）
  -- step 24 （引理 L：对每个正整数 k）
  -- step 25 （k^3 = (k(k+1)/2)^2 - ((k-1)k/2)^2，即 a_k - a_{k-1} = k^3；此处写成加法形式）
  set c := j * (j + 1) / 2 with hc
  set d := (j + 1) * (j + 1 + 1) / 2 with hd
  have hc2 : 2 * c = j * (j + 1) := by rw [hc]; exact two_mul_div j
  have hd2 : 2 * d = (j + 1) * (j + 1 + 1) := by rw [hd]; exact two_mul_div (j + 1)
  -- step 26 （引理 L 的验证：纯代数，不引用路径 (a) 的任何内容）
  have e1 : 4 * c ^ 2 = (j * (j + 1)) ^ 2 := by rw [← hc2]; ring
  have e2 : 4 * d ^ 2 = ((j + 1) * (j + 1 + 1)) ^ 2 := by rw [← hd2]; ring
  -- step 27 （右边通分到分母 4：k^2(k+1)^2 - k^2(k-1)^2 全在分母 4 上）
  -- step 28 （方括号内 (k+1)^2 - (k-1)^2 = 4k）
  -- step 29 （右边 = k^2 · 4k / 4 = k^3）
  have key : 4 * (c ^ 2 + (j + 1) ^ 3) = 4 * d ^ 2 := by
    rw [Nat.mul_add, e1, e2]
    ring
  omega

/-- 路径 (b)：裂项相消给出 S(n) = (n(n+1)/2)^2。
Lean 里「裂项相消」以对 n 的归纳实现（每步只用引理 L），不引用路径 (a)。 -/
theorem sum_cubes_telescope (n : ℕ) :
    Finset.sum (Finset.range (n + 1)) (fun k => k ^ 3) = (n * (n + 1) / 2) ^ 2 := by
  -- step 30 （即 (L) 成立）
  -- step 31 （求和（telescoping）：由 (L)，对任意正整数 n）
  -- step 32 （S(n) = sum_{k=1}^{n} k^3 = sum_{k=1}^{n} [ a_k - a_{k-1} ]）
  induction n with
  | zero => simp
  | succ n ih =>
      -- step 33 （把和拆成两个和 / 逐项对齐）
      rw [Finset.sum_range_succ, ih]
      -- step 34 （sum (a_k - a_{k-1}) = a_n - a_0）
      -- step 35 （裂项相消：a_1,...,a_{n-1} 每个各出现一次正号一次负号而相消）
      -- step 36 （S(n) = (n(n+1)/2)^2 - 0 = (n(n+1)/2)^2）
      -- step 37 （这正是 P(n)；本步只用引理 L，不引用路径 (a)）
      simpa using tel_step n

/-- statements.000000 的命题本体：对任意正整数 n，1^3+2^3+...+n^3 = (n(n+1)/2)^2。
这里走路径 (a) 落地；路径 (b) 由 sum_cubes_telescope 独立给出。 -/
theorem sum_cubes (n : ℕ) (hn : 0 < n) :
    Finset.sum (Finset.range (n + 1)) (fun k => k ^ 3) = (n * (n + 1) / 2) ^ 2 := by
  -- assume n 为正整数（0 < n）—— 与 statement_full 的假设一致，显式写出而非隐含
  set t := n * (n + 1) / 2 with ht
  have ht2 : 2 * t = n * (n + 1) := by rw [ht]; exact two_mul_div n
  have h4 := four_mul_sum_cubes n
  have hpow : (n * (n + 1)) ^ 2 = 4 * t ^ 2 := by rw [← ht2]; ring
  -- step 38 （两条路径的关系：本节定理只用路径 (a) 的 four_mul_sum_cubes）
  -- step 39 （只共享命题本身与初等代数事实：与 sum_cubes_telescope 互不依赖）
  omega
