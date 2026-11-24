# V 审阅报告 v-review-000001

- 生成时间：2026-11-24T18:36:33+08:00
- 被审稿：`manuscripts/F/f-proof-000000.md`
- 稿族 / 稿号：`f-proof` / `000000`
- 被审正文 sha256：`1f6095c1b769f813d680a2d38a636e22a85b9f3c703274251f4d26e692fadb7d`
- 结论：有毛病（V 的秘书语义判定：fault）
- 判词原文：有毛病
- 缺陷步：第 3 步
- 缺陷类别：math
- 台账锚点：`verifications/pending/bfe78f85fca1df894a28d8d4c99124b24c6920864b90af5e527ca2a4ad407907.jsonl#u-000001`

## findings（含 warning）

- [error] 第 10 步 · 换元方向/双射断言错误：令 c=2^{1/2-1/p}，T(t,z)=(ct,z)。若 (t,z) 满足 |t|^p+|z|^p≤1，则像 (x,y)=(ct,z) 满足 2^{1-p/2}|x|^p+|y|^p = 2^{1-p/2}c^p|t|^p+|z|^p = |t|^p+|z|^p≤1，故 T 把标准圆盘送入该截面；反过来要由原截面条件得到 |x|^p+|y|^p≤1 需 c^p=2^{1-p/2}，而所取 c 满足的是 c^p=2^{p/2-1}，两者除 p=2 外不同。因此“T 把 {2^{1-p/2}|t|^p+|z|^p≤1} 双射到标准圆盘”不成立，不能按稿面由 area(T(E))=|det T|area(E) 推出后面的面积等式；应改为说明 T 把标准圆盘映到该截面，或改取逆尺度并相应调整面积关系。
- [error] 第 3 步 · citation_not_in_citable_pool：`stmt:000017`（在哪一步：证明正文第 3 步）· 类别：不进可引池（这一条本来就不会有证明稿）（`citation_not_in_citable_pool`） · 期望：被引的是一条进得了可引池的命题（门槛 pre_theorem：手稿在盘上、且盖着 V 的签） · 实得：这一条不进可引池：`kind=concept` 不进等级链（`evidencebits.derive_grade` 对它短路成 `not_applicable`），名下不会有一份证明稿（盘上也确实没有它的稿：找过 ['manuscripts/F/f-proof-000017.md', 'manuscripts/B/b-proof-000017.md']） · 怎么改：改号或去掉这一引：这一档的命题不靠「稿上的 V 签」取等级 ⇒ 引它取不到任何等级。概念该写进正文（`## 命题` 里说清定义），不要当定理引；要引就引一条有稿有签的命题
- [error] 第 4 步 · citation_not_in_citable_pool：`stmt:000018`（在哪一步：证明正文第 4 步）· 类别：不进可引池（这一条本来就不会有证明稿）（`citation_not_in_citable_pool`） · 期望：被引的是一条进得了可引池的命题（门槛 pre_theorem：手稿在盘上、且盖着 V 的签） · 实得：这一条不进可引池：`kind=concept` 不进等级链（`evidencebits.derive_grade` 对它短路成 `not_applicable`），名下不会有一份证明稿（盘上也确实没有它的稿：找过 ['manuscripts/F/f-proof-000018.md', 'manuscripts/B/b-proof-000018.md']） · 怎么改：改号或去掉这一引：这一档的命题不靠「稿上的 V 签」取等级 ⇒ 引它取不到任何等级。概念该写进正文（`## 命题` 里说清定义），不要当定理引；要引就引一条有稿有签的命题
- [error] 第 5 步 · citation_not_in_citable_pool：`stmt:000016`（在哪一步：证明正文第 5 步）· 类别：不进可引池（这一条本来就不会有证明稿）（`citation_not_in_citable_pool`） · 期望：被引的是一条进得了可引池的命题（门槛 pre_theorem：手稿在盘上、且盖着 V 的签） · 实得：这一条不进可引池：`kind=concept` 不进等级链（`evidencebits.derive_grade` 对它短路成 `not_applicable`），名下不会有一份证明稿（盘上也确实没有它的稿：找过 ['manuscripts/F/f-proof-000016.md', 'manuscripts/B/b-proof-000016.md']） · 怎么改：改号或去掉这一引：这一档的命题不靠「稿上的 V 签」取等级 ⇒ 引它取不到任何等级。概念该写进正文（`## 命题` 里说清定义），不要当定理引；要引就引一条有稿有签的命题
- [error] 第 7 步 · citation_not_in_citable_pool：`stmt:000001`（在哪一步：证明正文第 7 步）· 类别：不进可引池（这一条本来就不会有证明稿）（`citation_not_in_citable_pool`） · 期望：被引的是一条进得了可引池的命题（门槛 pre_theorem：手稿在盘上、且盖着 V 的签） · 实得：这一条不进可引池：`kind=concept` 不进等级链（`evidencebits.derive_grade` 对它短路成 `not_applicable`），名下不会有一份证明稿（盘上也确实没有它的稿：找过 ['manuscripts/F/f-proof-000001.md', 'manuscripts/B/b-proof-000001.md']） · 怎么改：改号或去掉这一引：这一档的命题不靠「稿上的 V 签」取等级 ⇒ 引它取不到任何等级。概念该写进正文（`## 命题` 里说清定义），不要当定理引；要引就引一条有稿有签的命题

## 理由

V 明确指认步骤10的换元方向写反、双射断言不成立，属于证明链上的实质缺陷。；步骤10的线性换元方向写反：所取 T 实际把标准圆盘映到该截面，而不是把截面映到标准圆盘，故随后面积等式的双射依据不成立。；`stmt:000017`（在哪一步：证明正文第 3 步）· 类别：不进可引池（这一条本来就不会有证明稿）（`citation_not_in_citable_pool`） · 期望：被引的是一条进得了可引池的命题（门槛 pre_theorem：手稿在盘上、且盖着 V 的签） · 实得：这一条不进可引池：`kind=concept` 不进等级链（`evidencebits.derive_grade` 对它短路成 `not_applicable`），名下不会有一份证明稿（盘上也确实没有它的稿：找过 ['manuscripts/F/f-proof-000017.md', 'manuscripts/B/b-proof-000017.md']） · 怎么改：改号或去掉这一引：这一档的命题不靠「稿上的 V 签」取等级 ⇒ 引它取不到任何等级。概念该写进正文（`## 命题` 里说清定义），不要当定理引；要引就引一条有稿有签的命题；`stmt:000018`（在哪一步：证明正文第 4 步）· 类别：不进可引池（这一条本来就不会有证明稿）（`citation_not_in_citable_pool`） · 期望：被引的是一条进得了可引池的命题（门槛 pre_theorem：手稿在盘上、且盖着 V 的签） · 实得：这一条不进可引池：`kind=concept` 不进等级链（`evidencebits.derive_grade` 对它短路成 `not_applicable`），名下不会有一份证明稿（盘上也确实没有它的稿：找过 ['manuscripts/F/f-proof-000018.md', 'manuscripts/B/b-proof-000018.md']） · 怎么改：改号或去掉这一引：这一档的命题不靠「稿上的 V 签」取等级 ⇒ 引它取不到任何等级。概念该写进正文（`## 命题` 里说清定义），不要当定理引；要引就引一条有稿有签的命题；`stmt:000016`（在哪一步：证明正文第 5 步）· 类别：不进可引池（这一条本来就不会有证明稿）（`citation_not_in_citable_pool`） · 期望：被引的是一条进得了可引池的命题（门槛 pre_theorem：手稿在盘上、且盖着 V 的签） · 实得：这一条不进可引池：`kind=concept` 不进等级链（`evidencebits.derive_grade` 对它短路成 `not_applicable`），名下不会有一份证明稿（盘上也确实没有它的稿：找过 ['manuscripts/F/f-proof-000016.md', 'manuscripts/B/b-proof-000016.md']） · 怎么改：改号或去掉这一引：这一档的命题不靠「稿上的 V 签」取等级 ⇒ 引它取不到任何等级。概念该写进正文（`## 命题` 里说清定义），不要当定理引；要引就引一条有稿有签的命题；另有 1 条（依据：v_reply.why："步骤10的线性换元方向写反：所取 T 实际把标准圆盘映到该截面，而不是把截面映到标准圆盘，故随后面积等式的双射依据不成立。"；v_reply.findings[0].detail："因此“T 把 {2^{1-p/2}|t|^p+|z|^p≤1} 双射到标准圆盘”不成立，不能按稿面由 area(T(E))=|det T|area(E) 推出后面的面积等式"；v_reply.defect_step=10（回复自己点到的步号））

## 判据（写报告的人与读报告的人都按这一条读）

- 只要不是完全没毛病就叫有毛病；`warning` 也算有毛病。
- 程序性 / 文风 fault 同样落这份报告（它不是对数学缺陷的认定，但它是「这一份没有通过」的读数）。
