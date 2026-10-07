# draft/80 待裁选择题（Web 端施工·合并 W0/B 线之后）—— **一次裁干净**

> **怎么用**：每题给你的都是「盘上事实 → 选项 → 每个选项的代价 → 我的建议 → 不裁会怎样」。
> 你只要回一串字母（例如 `1a 2a 3a 4a 5a 6a 7a 8a`，或直接说"全按你建议的"）。**我按你的裁定派活，不再回来问**。
> 事实都带 `file:line` 或可复算命令；不确定的地方我写"我没验"，不编。
> 前情：W0（骨架/拆包/dist）与 B 线（只读面/索引/SSE/夹具）**已合并进 master**；C 线（写面）与 A 线的六页面**尚未开工**，等你裁完就派。

---

## 1. SSE 的"发送点"放哪（**唯一挡着 W2 收尾的题**）

**事实**：`webui/sse.py` 的广播器与 `GET /api/stream` 已落地且判据绿（B 线 `test_webui_sse.py` 12 条，含端到端"盘上新增 ⇒ 流里出现"）。
但 `sse.publish` **今天没有任何调用者** —— 真实运行时该发事件的四处（`draft/75 §1.2` 的触发点列）分别是
`sessions.append`（`state`）· `userio.ask_user`（`question`）· `userio.answer_question`（`answered`）· `stopctl.request_stop`/`clear_stop`（`stop`）。
B 线**没有**去改这四个既有函数体，理由写在它的报告里：那是跨线语义（"谁写谁发"），得先裁。

| 选项 | 做法 | 代价 |
|---|---|---|
| **1a（建议）** | B 线在 `sessions.py`/`userio.py` 的这几个函数上加**可选回调钩子**（`on_event=None` 缺省 ⇒ 行为逐字节不变），并扩 B 的边界把 `stopctl.py` 一并纳入（只加同样一个钩子）。`serve()` 起服务时把 `sse.publish` 挂上去 | 要动既有函数签名（加一个缺省参数）+ `stopctl.py` 的归属要重划（它此前不在三条线任何一条里） |
| 1b | A 线在服务端**轮询**盘上变化后广播（不碰任何写路径） | 判据⑤"盘上新增 ⇒ 流里出现"从"写时发"退化成"轮询发现"，延迟与语义都变了；且与界面纪律"状态一律从盘上派生、不做后台轮询线程"直接冲突 |
| 1c | 服务端起一个 watcher 线程盯文件并广播 | 同样与"不做后台轮询"的纪律冲突；还要处理"谁关它"（B 已经踩过：`srv.shutdown()` 停不住请求线程） |

**不裁会怎样**：`/api/stream` 是一条**永远沉默**的通道 —— 前端订阅了、判据绿了、真实运行时不发任何事件（典型的"绿灯但没接上"）。

---

## 2. `/api/state` 归谁

**事实**：A 线的 `routes._OWN` 里有 `("GET", "/api/state", "handle_state")`（`webui/routes.py:97`），实现是 `state.snapshot`；
B 线也写了 `readers.state_face`（`readers.py:251`）与 `handle_state_face`（`:842`），但**故意没有登记路由**（它的报告里点名"不去抢 A 的这条"）。
公开面对账（`temp/_verify_w0.py`）钉住的 `snapshot()` 顶层 10 键由 `state.snapshot` 产出，而该对账的硬读数今天全绿。

| 选项 | 代价 |
|---|---|
| **2a（建议）** | 保持 A 自有：`/api/state` 仍走 `state.snapshot`；`readers.state_face` 作为**页面层可直接调的函数**存在（六面里的"state"面），不占路由 | `readers.state_face` 与 `state.snapshot` 两份读同一件事的实现并存 ⇒ 需要一条"两处同值"的判据（B 已经用 `option_view` 两处同值那条做过同类） |
| 2b | 把这条路由迁到 `readers.ROUTES`，`handle_state` 转调 `readers.state_face` | 动公开面（10 个顶层键的产出者换人）⇒ 要重跑公开面对账；收益只是"六面都在一个模块里" |

---

## 3. L1 收敛（"待答/选项"的唯一来源）落谁手里

**事实**：裁定 L1 要求删掉 `webui/state.py` 里那两段与 `option_view`/`_opts_view`，改调 `userio.pending_questions/coerce_option`。
B 线只做了它那半边（`userio.py:452-538` 的 `option_view`/`question_view`/`reply_view`/`pending_view`/`workspace_pending_view`，并有一条"两处 `option_view` 逐值相等"的判据）。
`webui/state.py` 是 **A 线**的文件，B 没动。

| 选项 | 代价 |
|---|---|
| **3a（建议）** | A 线做：`state.py:240/248/256-268` 三处改成调 `userio`，`state.option_view` 变成转发 | A 线本来就要动 `state.py`（W1 的 Home 页要读它），顺路做最省 |
| 3b | 主控做（现在就能做） | 主控正在跑合并与门，插进去会让"A 线的改动"混在主控提交里，事后难归因 |
| 3c | 让 B 线扩边界做 | B 已收工；再开一轮的通信成本 > 改动本身 |

**不裁会怎样**：`R003` 会一直有那一条 warn（同名 `option_view` 两处独立实现）；且"待答口径"有两个来源，将来必漂。

---

## 4. `draft/73 §2.3` 点名的五个"面函数"要不要独立存在

**事实**：`draft/73` 原文点名 `handoffs` / `artifact_ledger` / `machine_readings` / `provider_states` / `verifications` 五个函数名；
而 `draft/75 §1.1` 的 C1 表只有**六行端点**。B 线按 C1 实现：这五样东西的数据都在六面里（交接在 `artifacts_face["handoffs"]`、台账在 `["ledger"]`、本机在 `machine_face`、验证在 `evidence_chain["verifications"]`），**没有**另立五个独立函数名。

| 选项 | 代价 |
|---|---|
| **4a（建议）** | 保持现状：它们是六面里的"栏位"，不是五个独立函数；在 `draft/73` 那一行加一句更正说明 | 与 `draft/73` 的字面不一致（所以要改那句） |
| 4b | 另立五个独立函数名（`readers.handoffs()` 等）并加判据 | 多五个只有一层转发的函数；判据与维护面都涨，收益是"名字与 draft/73 字面一致" |

---

## 5. `Checkpoint` 与 `CheckpointView` 两对名字并存

**事实**：W0 在 `test_webui_contracts.py` 的 `_W0_UNCHECKED_TYPES` 里登记了 `Checkpoint` / `CheckpointSpend`（"本批无读数"）；
B 线实现 `RunView` 时用的是自己的 `CheckpointView` / `CheckpointSpendView`（字段出自 `agent_loop.save_run_checkpoint` 与 `llmseam.SeamSpend.to_dict`）。两对并存**没有**触发"登记过期"的反向断言（B 实跑绿）。

| 选项 | 代价 |
|---|---|
| **5a（建议）** | 保留 B 的新名（它带真读数），W0 那两条登记在 A 线把 `Checkpoint` 真读出来后**从表里删掉**（或者现在就删、由 A 的 backend 提供 `Checkpoint` 键） | 过渡期两对名字并存（读 types.ts 的人会看到 4 个相关接口） |
| 5b | 统一成一对（改 `types.ts` + 页面 + B 的 `type_decls()`） | 要重跑生成器与契约判据；收益只是名字干净 |

---

## 6. G2 那两处禁改区的**签字**

**事实**：已按你「允许动禁改区」落地（提交 `498bd75`）。带基线读数
`python -B scripts/noai_gate.py --git --since 5c6e441 --check-approvals` ⇒ 命中 3 条、**3 条未获批准**
（`stale` 2 = `pyproject.toml` + `tools/release_all.py`；`unregistered` 1 = 刻意不入库的演示物）。
走查清单与签法在 `draft/77 §2.4/§2.5`。

| 选项 | 代价 |
|---|---|
| **6a（建议）** | 你有空时按 `draft/77 §2.4` 四条走查、按 §2.5 签两名 reviewer | 需要你花几分钟；不签则这两条在台账上一直是"未批准" |
| 6b | 先回退 `addopts` 那一行（改回 `-m 'not network'`，把"默认排除 browser"改到 `tests/conftest.py` 里做） | 少一处禁改区改动，但要在 B 的文件里加十行且语义更绕 |
| 6c | 保持现状不签 | `noai_gate --git --since` 会一直以 1 结束（`requires_human`）；这是**诚实**状态，只是审计上没闭环 |

---

## 7. 前端发布步在本沙箱恒为 `unknown`（`spawn EPERM`）

**事实**：`tools/frontend_gate.py` 本机实测：`typecheck` **pass**；`vite build` 因为"沙箱不许 Node 用管道 stdio 起子进程"报 `spawn EPERM` ⇒ 整步记 **`unknown(2)`**（不是 pass）。
dist 本身**已经在盘上并入库**（我用更宽的执行权限跑通了 `pnpm build`，三个文件：`index.html` 920 B · `assets/index.Bpmfy4ek.js` 21,611 B · `assets/index.DQaZOKq-.css` 19,297 B），`tests/test_webui_static.py` 的产物自洽/新鲜度判据已从 skip 变成真跑且绿。

| 选项 | 代价 |
|---|---|
| **7a（建议）** | 接受：发布门里这一步在本机记 `unknown`（三态纪律要求如此），要真判它就在不受沙箱约束的环境跑 | 发布报告里这一步永远是 `unknown`（不是绿），读报告的人要理解这是环境限制 |
| 7b | 每次改前端后，由主控用更宽权限跑一次 `pnpm build` 并提交，同时在提交信息里写明"这一步在沙箱外验证过" | 依赖主控记得做；门本身仍然 `unknown` |
| 7c | 去掉这一步（回到 6 步） | 前端产物与源码脱节就再也无人拦（B1 的代价） |

---

## 8. 现在要不要把 master push 到 GitHub

**事实**：仓库已干净（上一轮你点名的那件事）：受跟踪 1,238 文件 / 36.8 MB（最大 1.86 MB）· `/temp/*` 与 `/_env/`、`/_archive/`、`node_modules/`、`agentflow/settings.json` 都已忽略 · 未跟踪只剩 3 条刻意不入库的登记物。
**但**：master 里有 ① 前端构建产物（裁定 B1 要入库，约 42 KB）· ② 未签字的禁改区两处（题 6）· ③ 六个 R 批 + Web 批的 draft 文档（含内部裁定细节）。

| 选项 | 代价 |
|---|---|
| **8a（建议）** | **等题 6 签完再 push**：签完这一版就是"审计闭环"的版本，push 出去以后不用再解释"这两处为什么没签" | 晚几天 |
| 8b | 现在就 push（未签的两处照实带上） | 快；但远端历史里会出现"禁改区改动未获批准"的状态，之后补签也要在远端留记录 |
| 8c | 先 push 到一个私有远端/分支，签完再并进 main | 多一步；适合你想先让协作者看到 | 
| 8d | 暂不 push（先把 C 线与 A 线做完） | 最大的一批改动还没进来，届时仍要再 push 一次 |

**另外顺带一句事实**（不是题）：`.git` 现在 33 MB 左右，`_env/`（约 5 GB）与 `_archive/`（约 3.3 GB）只在本机、已被忽略 —— push 不会把它们带上去。

---

## 我的建议速览

`1a 2a 3a 4a 5a 6a 7a 8a` —— 也就是说：SSE 发送点用"写路径上的可选钩子"（并把 `stopctl.py` 划给 B 线）；`/api/state` 仍归 A；L1 收敛交 A 线；五个面函数名不另立（改 draft/73 那一句）；`Checkpoint` 名字保留 B 的新名；G2 你有空签；前端步接受 `unknown`；**签完再 push**。
