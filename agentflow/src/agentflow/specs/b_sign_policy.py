# -*- coding: utf-8 -*-
"""B 的 policy 里「送审与交稿」那一段的模块级常量。

为什么单独一个文件：`specs/b.py` 受「`src/` 下 > 800 行的文件数」那条体量软基线管着，
而这一段 policy 还在长（改写之后先拿签再入库 / 送审之后挂计时器等 V 的反馈 / 交稿也是
你的义务）。基线不许抬、顶过 800 就拆，所以整段搬到本文件，`specs/b.py` 在原来的位置上
用 `*SIGN_SUBMIT_POLICY` 摊回去。

它承载的是 B 的声明正文，模型按它行动 ⇒ 改它等于改口径；与 `b_ingest_policy.py`
同一个理由（两个文件都是为把 `b.py` 拉回线内而拆出来的）。
"""
from __future__ import annotations

#: 两段 policy 正文；`specs/b.py` 用 `*SIGN_SUBMIT_POLICY` 把它们摊回那一段。
SIGN_SUBMIT_POLICY: tuple[str, ...] = (
    # 2026-11-04（业主裁定 A 甲，逐字）：「B 的改写要有可签的载体：给 B 手稿签块（与 F/E 同形）」。
    # 只教可观察的走法（交正文 → 框架落下 b-proof 稿 → 派 V → 签到位 → 再入库），
    # 不写 V 内部怎么连判（那是框架的事，不该由你推断）。
    # 2026-11-10（T1 收口）：落稿不再是登记的副作用 —— 显式一步 `own.land_manuscript`。
    # 这一段此前教的是「把正文交一次 register_statement，框架会把它落成 b-proof」，
    # D1 之后那句话已经不成立（被拒的登记不再留下稿）。
    "**改写之后先拿签，再入库**：用 `own.land_manuscript` 把这一版正文落成"
    "`reports/b-proof-<命题号>.md`（与 F/E 同形：`## 命题` / `## 证明` / `## 依赖` 三节；"
    "只写文件、幂等 —— 同一份正文重放一个字节不动），然后派 V 审这一份手稿"
    "（`framework_summon` 的 `V.verify_proof`，带 `statement_id` + `proof_manuscript`），"
    "签到位后签块由收方秘书 `secretary:B` 落回稿里；最后用 `own.ingest_manuscript`"
    "按 `target_stmt_id` + `cells=[\"proof_text\"]` 收录（第 3 位翻真、旧正文进 "
    "`proof_history`）。",
    # 收工门按签拦、不按计时器拦（`agent_loop._v_wait_gate_reading`）：`b-proof` 稿没有
    # 现行的 V 签、且那条命题没被放弃 ⇒ 拦。B 这一档的「提交」是「收录进台账」
    # （`own.ingest_manuscript` → `via=ingested_to_ledger`），不是签那一刻自动置位 ——
    # 签触发只服务 F/E 的稿，B 的稿由它自己交进台账（2026-11-11 裁定 ①）。
    "**送审之后这一趟还不能收工**：收工门按签拦 —— `b-proof` 稿没有现行的 V 签、"
    "且那条命题没被放弃 ⇒ 收工受控拒；**V 判「成立」的那一刻这一份稿就「已签」**，"
    "判「有毛病」就按缺陷改稿、重送 V。要等就挂 "
    "`clock.timer_start(wait_for=<V 的名册名或刚派出的 V 的编号>, "
    "reason=<等它回什么结论>)`，别空转、也别「过一会儿再看」。"
    "**交稿也是你的义务**：这一份稿是你产出的（`reports/b-proof-*.md`），签成立之后由你"
    "**自己**把它交进台账（走上面的收录那条路 —— 收录成功那一刻才算「已提交」，"
    "`via=ingested_to_ledger`）；不要等 D / F 替你把「已签、未提交」的那一份交出去，"
    "也不要把「收工扫到它」当成别人的事。",
)
