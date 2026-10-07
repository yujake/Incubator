# draft/81 Web 端收口总计划与可行性论证（**主控自持，不再逐事请裁**）

> **这份文档回答三件事**：① 剩下的活到底有哪些（按文件/按批/按线，逐条）；② 为什么这些活**做得成**（每条都带盘上读数或已跑通的读数，不是"应该没问题"）；③ 我按什么规则自行推进、什么情况下才会回头找你。
> 所有者本轮指示：「先完善计划，论述可行性后，再推动主线。不再频繁请求裁定。」—— 因此本文档之后，**已裁定的按裁定办，未裁定的由我按下面 §6 的清单自行决定并在盘上留痕**；只在 §10 的四类情形才找你。

---

## §1 完成定义（"Web 端做完了"= 下面全部成立，逐条可复算）

| # | 判据 | 复算命令 / 读数位置 | 现在 |
|---|---|---|---|
| 1 | 六页面每一页都读真数据、三态不塌 | `python -B -m pytest -q tests/test_webui_pages.py`（A 线新建） | ⬜ 待 A |
| 2 | 契约 A–D 全绿（端点/事件/类型/路由四条对齐 + 负控） | `tests/test_webui_contracts.py` ⇒ 现 **26 passed** | ✅ 当前绿（C 落地写端点时会短暂红，见 §6-D2） |
| 3 | 六面读模型 + SSE + 索引各自的正控/负控 | `tests/test_webui_readers.py`·`test_webui_sse.py`·`test_run_index.py` ⇒ 50 条 | ✅ 已绿 |
| 4 | 静态路由 / SPA 回退 / 产物自洽与新鲜度 | `tests/test_webui_static.py` ⇒ 13 条真跑（产物已在盘上） | ✅ 已绿 |
| 5 | 写面三端点 + 授权矩阵四态 + 每次写留审计 | `tests/test_webui_writes.py`（C 计划新建） | 🟡 C 运行中 |
| 6 | 设置写面（key 只写不读 · 原子写 · 不回显） | `tests/test_webui_settings_write.py`（C 计划新建） | 🟡 C 运行中 |
| 7 | 浏览器端到端（opt-in） | `python -B -m pytest -q -m browser` ⇒ 装了 playwright 才真跑 | 🟡 C 写计划新增的 `tests/test_webui_browser.py`；装不装见 §6-D5 |
| 8 | 提示词/工具面快照**不逐条重冻**；确需重冻时一次性 + 逐格归因 | `tests/golden/*.json` + `draft/64 §8.12`；`pytest tests/test_agent_surface_snapshot.py` ⇒ **5 passed** | ✅ 当前未动 |
| 9 | lint `error 0`（warning 数随施工更新到 `DEVELOPMENT.md` 的 `LIVE-READINGS`） | `python -B scripts/lint_rules.py` ⇒ 现 `0 / 17 / 49` | ✅ |
| 10 | 全量门 §8 `0 failed`（逐节读数看报告，不看脚本退出码） | `python -B temp/_merge_gate.py --with-pytest` | 🔄 正在重跑（上一趟因我自造的 collection error 作废，已修） |
| 11 | 旧壳清干净（裁定 P1：迁一面删一面，W5 时 `views.py` 应清空） | `webui/views.py` 行数 + 引用普查 | ⬜ 待 W5 |
| 12 | 文档与盘上一致（README / INDEX / READING-MAP / USER-END-DSH-STYLE / ui/README-DEV） | `tests/test_reading_map.py` + `test_release_all.py` 的实时读数判据 | 🟡 A 在做 |
| 13 | FC-27 那两条改动**已签字**（裁定 6a） | `noai_gate --git --since 5c6e441 --check-approvals` | ⬜ **只有你能做** |
| 14 | 仓库可 push（裁定 8a：签完再推） | §11 的推送前普查 | ⬜ 等 13 |

---

## §2 现状盘点（全部是此刻盘上的读数）

**已落地并合并（master）**
- **W0**：`webui.py`(1268 行) → `webui/` 九文件包（`__init__ __main__ state views writes routes server readers sse`）· 静态路由与 Q1 回退 · `web/emit_theme.py`·`web/emit_types.py` 两个生成器 · `ui/` 骨架 · 契约判据 A–D · 三条零交接缝。
- **B 线**：六面只读模型（`readers.py` 1152 行）· SSE（`sse.py` 426 行）· 趟次索引（`sessions.py` 一族）· L1 收敛入口（`userio.py`）· J2/K2 夹具（`conftest.py`）· 三份判据 50 条。
- **主控补的**：dist 入库（3 文件 42 KB）· 哈希缓存真缺陷修复（`_HASHED` 认 base64url + 反例负控）· 接缝补齐（`HANDLERS` + 三张登记表模块化）· 旧坐标迁移（72 处）· G2 落地（`pyproject.toml` / `tools/release_all.py` 第 7 步 / 新 `tools/frontend_gate.py`）。

**此刻的关键读数**（`python -c` 直读，见提交信息里的命令）
| 项 | 读数 |
|---|---|
| 后端已声明端点 | 8 条：`/api/state` `/api/run/{sid}` `/api/evidence` `/api/artifacts` `/api/acceptance` `/api/machine` `/api/stream` `/answer`；总路由 **12** 条（含页面与静态前缀） |
| 事件词表 | `sse.EVENT_KINDS` = 6 个 kind（与 `ui/src/sse.ts` 的 `KINDS` 逐字相等，契约 B 条已真跑） |
| 生成物 | `ui/src/types.ts` = **38 个接口 / 13,996 字节**，由 `state+readers+writes` 三张子表拼出 |
| 读模型欠账 | `readers.MISSING_TYPES` 只剩 **2** 条：`RunIndex`·`RunIndexDrift`（B 的函数已落地，欠的是 A 的页面消费端） |
| 受核对/欠账接口 | `readers.CHECKED_TYPES` 18 · `UNCHECKED_TYPES` 7（各有理由） |
| 前端骨架 | 6 页面 + 6 组件都在盘上；页面里带"缺/W1"字样的欠账行 **12** 处（A 正在逐条消） |
| web 面判据 | 8 份判据文件（`test_webui*.py` + `test_run_index.py` + `test_release_all.py` + `test_reading_map.py`）⇒ **177 passed / 1 skipped** |
| lint | `error 0 / warning 17 / info 49`（17 里含 1 条 R003「`option_view` 两处独立实现」，裁定 3a 收口后应降 16） |
| 自审器 | `draft/73–81` 的引用与判据：① 硬错 **0** |
| FC-27 | 带基线 `--since 5c6e441` ⇒ 命中 3 条、**3 条未批准**（两条是 G2 那两处，等签；一条是刻意不入库的演示物） |

**在飞（三条子代理）**
- **A**（`line-a`）：W1 六页面 + 前端 SSE + `test_webui_pages.py` + 文档 + 裁定追加（2b 的 A 侧 / 3a L1 / 5a 名字收口 / 1a 的一行 `attach`）。
- **B**（`line-b` 续跑）：B6（写路径可选钩子 + `sse.attach()/detach()`）· B7（`/api/state` 路由迁到 `readers.ROUTES`）。
- **C**（`line-c`）：写面三端点 + 授权矩阵 + 审计台账 + `settings.write_settings()` + 浏览器判据。

---

## §3 剩余工作分解（按批 × 线；每行都写清"交付什么、怎么算做完"）

### W1（当前主战场）
| 归属 | 交付 | 收工判据 |
|---|---|---|
| A | 六页面接线（Home/Run/Evidence/Artifacts/Machine/Acceptance）：每页每栏位照 `draft/74` 矩阵落；`Run.tsx` 接 O2 索引（`run_index_report` 的 `tri != computed` 显红）；删 `readers.MISSING_TYPES` 那两条 | `test_webui_pages.py` 每页一条（真读数 + 空态 + 三态）；现有 17 条仍绿；`readers.MISSING_TYPES` 归零 |
| A | 前端 SSE（`sse.ts` 的 6 kind 注册 + 断线重连 + `?since=`） | 契约 B 条 + `test_webui_sse.py` 一起绿；判据 B 的负控仍在 |
| A | `state.py` L1 收敛（`option_view` 变转发）· 删 W0 的 `Checkpoint`/`CheckpointSpend` 并重跑生成器 · `server.py` 删 `handle_state` 与 `_OWN` 那行 · `serve()` 一行 `sse.attach()` | lint warning 17→16；`temp/_verify_w0.py check` 硬读数全同；`test_webui_contracts.py` 26 条仍绿 |
| B | B6/B7（见 §2 在飞） | 四条正控 + detach 负控；`readers.ROUTES` 的 `/api/state` 进了总表且与 `W.snapshot` 同值 |
| C | C1–C4（见 §2 在飞） | 授权矩阵四态真 HTTP 码 + 每次写留审计 + key 三处不回显 + 浏览器 opt-in skip 理由写明 |

### W2（SSE 端到端）
- 后端：B6 落地后 `attach()` 挂上（A 一行）；`checkpoint` 事件**明确不做**（需要 watch/poll，与"不做后台轮询"冲突），在 `draft/75 §1.2` 那一行加注。
- 前端：A 的 `sse.ts` 消费六 kind；一条端到端判据"盘上新增 ⇒ 页面出现"（A 的 pages 判据 + B 的 sse 判据分工）。

### W3（写面）
- C 交付写面三端点（`/answer` `/api/stop` `/api/submit`；`/api/task` 不做 —— 裁定 I1）· 审计台账 `web-actions.jsonl` · 授权矩阵四态 · "不许绕闸门"的负控（换桩 ⇒ 审计 `result` 跟着变）。
- 主控合并时补 `ui/src/api.ts` 三行字面量（`stop`/`submit`/`settings`），使契约 A 条回到"集合相等"。

### W4（设置写面 + 浏览器 + 文档）
- C：`settings.write_settings()`（key 只写不读 · 原子写 · 权限读数）· `tests/test_webui_browser.py`（`-m browser`，默认被 `addopts` 排除）· `/api/settings` 端点。
- A：`USER-END-DSH-STYLE.md` / `README.md` / `INDEX.md` / `READING-MAP.md` / `ui/README-DEV.md` 同步到"盘上真读数"。
- 主控：**尝试**装 `playwright` + 浏览器（见 §6-D5）；装不上则浏览器判据保持 skip（记 `unknown`，不当 pass）。

### W5（旧壳清仓，最后、单独一批）
- **普查已跑**（`temp/_w5_legacy_census.py`，见 §12 的表）：`views.py` 9 个顶层符号里 **5 个无任何引用**（`_top` `_option_html` `_question_card` `_run_row` `_event_card`）→ 可直接删；`_page`/`_not_found`/`render_root`/`render_run` 被 `server.py` 读，其中 `render_root`/`render_run` 还由 `__init__.py` **再导出**（public face）。
- A：按裁定 P1「迁一面删一面」先删那 5 个无引用件；`web/assets.py` 里 `APP_CSS` 无引用可删、`STYLESHEET` 随旧壳一起退场、`THEME_CSS` 被 `emit_theme.py` 读（**那是主题的唯一来源，不许删**）。
- **公开面收窄（这是 P1 的必然结果，我按 P1 执行、留痕）**：六页面全部迁到 SPA 之后，`render_root`/`render_run` 从 `webui.__all__` 里退场，`views.py` 清空；随之要改的三处**都是我自己的账**：
  1. `tests/test_webui.py` 那一组（**17 条**，测的是服务端渲染的旧壳：选项渲染 / 转义 / 投影稳定 / 409 与 303）**迁移**到 SPA 面（`/api/state` 的 JSON + `POST /answer` 的状态码与三态 + 页面消费），迁移后条数不许减少；
  2. `temp/_verify_w0.py` 的公开面基线**记一次"公开面修订"事件**（8 个公开名里去掉那两个，基线文件更新并写明理由与日期）；
  3. `docs/READING-MAP.md` / `README.md` 同步。
- 主控：删完跑一次全量门；**只有在确需重冻 golden 时才冻，且一次性 + 逐格归因 `draft/64 §8.12`**。

---

## §4 依赖与关键路径

```
（已合）W0 ──► B 线六面 ──┐
                          ├─► A(W1 六页面+L1+2b A侧) ──┐
        B6/B7（钩子/路由迁移）┘                          ├─► 主控合并轮 A/B/C ──► 全量门 ──► W5 清仓 ──► 全量门 ──► 交签(6a) ──► push(8a)
        C（写面/审计/设置/浏览器）──────────────────────┘
```

- **关键路径** = A 的 W1 页面 → 主控合并 → 门 → W5 → 门（约 **4 轮合并 × 每轮一趟门**）。
- **并行度**：A / B / C 三条线此刻真并行且文件零交（`temp/_check_line_ownership.py` 的机械证明仍在；2b 之后 `/api/state` 那条路由的归属变了，我会在合并时重跑该证明的读数口径）。
- **不需要串行的**：文档（A）、审计台账与设置写面（C）、W5 的"哪些旧函数没人引用"普查（主控，见 §7 仪器）都可以与页面开发并行。

---

## §5 可行性论证（逐条给"为什么做得成"的依据）

1. **六页面接线**（W1 最大的一块）：六个只读端点**全部已在盘上并各自有判据**（`routes.api_paths()` 8 条，六面函数 `readers.state_face/run_view/evidence_chain/artifacts_face/acceptance_face/machine_face` 都在）；`ui/src/types.ts` 已有 38 个接口且由生成器保证与后端字段逐字对齐（判据 C 逐键比对，含双向）；每页"读什么、展示什么"的映射在 `draft/74` 里逐行写死；夹具（`artifacts_ws`）能造出六件产物/台账/交接/验收/体例/秘书决定/检查点/验证台账。
   ⇒ **剩余的不确定性只是"照表落"的工作量**（页面欠账行 12 处），不是"接口还没定"。**风险可控**。
2. **O2 索引的页面消费**：B 的三个函数已落地（`compute_run_index` 返回 `{version, generated_at, sessions:{sid:{runs,last_end_index,digest}}}`；`reconcile_run_index` 返回 `{tri, drift[], reason, sessions[]}`；`run_index_report` 返回 `{usable, tri, reason, drift, sessions, index}`），欠的只有 `RunIndex`/`RunIndexDrift` 两个 TS 接口 —— **生成器一条命令就能补**（`python -B -m agentflow.web.emit_types`），因为 `type_decls()` 的子表机制已就位。
3. **SSE 真接线**：词表（6 kind）与广播器已落地、端到端判据已绿（"盘上新增 ⇒ 流里出现"）；缺的只是"谁来 publish" —— B6 用**缺省 `None` 的可选钩子**接上，钩子只在装配后生效（`detach()` 负控证明"不装就不发"），**既有函数在缺省情形下逐字节不变**（判据要求既有测试全绿）。这条风险点是"改既有函数签名"，已用"只新增带默认值的关键字参数 + 既有判据全绿"钉住。
4. **写面**：三个写操作的**闸门都已存在**（`/answer` ⇒ `userio.answer_question`；`/api/stop` ⇒ `stopctl.request_stop_detail`/`kill_registered`；`/api/submit` ⇒ `interactions.next_prefixed_id` + `store.tx` + `row.validate()`）⇒ **不触发 H1**（"没有既有闸门时停下报你"）。授权矩阵四态（未开写面/缺确认/未知端点/未知 sid）全是**本地可造的输入**，不需要外部依赖。
5. **设置写面**：`settings.py` 已有完整的**读**侧（`settings_path`/`load_settings`/三族 `*_settings`/`env_or_setting`/`resolve_setting_path`）与"优先级 env > 文件 > 默认"的单一实现 ⇒ 写侧只需"读-改-写 + 原子落盘 + 权限 + 不回显"。**key 不回显**这条有现成机制可依（`modelgw.redacted()` 已在用）。
6. **前端产物与构建**：本机 **已成功构建过两次**（`pnpm -C agentflow/ui build` ⇒ `index.html` 920 B + `assets/index.Bpmfy4ek.js` 21,611 B + `assets/index.DQaZOKq-.css` 19,297 B），且与入库产物**逐字节相同**（`git hash-object` == `HEAD:<path>`）；沙箱内构建会撞 `spawn EPERM`，**证据是固定的**（`tools/frontend_gate.py` 报 `unknown(2)` 并写明原因），而我有更宽权限这一条通路（本会话已用过两次）。
7. **类型层这道门**：`node node_modules/typescript/bin/tsc --noEmit` 直跑 **exit 0**（绕开 pnpm 的 pre-run install 检查）⇒ 类型检查不是 `unknown`。
8. **全量门**：结构上就是"9 节读数"，上一趟 §0–§7 与 §9 全绿，§8 因**我自造的 collection error** 作废（一行代码被我的批量正则改坏），修法与"以后不复发"都已固化（`temp/_r009_strip.py` 改成 tokenize/ast 定位 + `ast.parse` 自检；教训 FC-28/FC-29 写进 `draft/LESSONS…md`）。⇒ 门本身的可用性没有疑问。
9. **签字与 push**：FC-27 的两条改动**已落地**，只欠"人走查 + 2 名 reviewer"（`draft/67 §3b` 已备好逐条走查清单与命令）；push 前普查（密钥形态、大文件、未跟踪面）**已跑过一次干净**（3,402 blobs / 345.9 MB 无密钥形态串；受跟踪 1,238 文件 / 36.8 MB）。⇒ 卡点只有一个：**你签字**（这也是唯一必须由人做的动作）。
10. **文档一致性**：`draft/73–81` 的引用自审 ① 硬错 0；`DEVELOPMENT.md` 的 `LIVE-READINGS` 有判据强制与实测同步（本轮已同步一次：warning 12→17）。
11. **旧壳清仓（W5）**：做法上先普查后删（§7 的仪器），每个被删函数都能回答"谁在读它"；删完的判据是"17 条仍绿 + 全量门绿"，**不需要新的判据**。

**结论**：剩余工作的每一块都有"已在盘上的接口/机制/判据"做支撑，**没有一条依赖尚未确定的设计或未经证实的外部能力**；两个已知环境限制（沙箱内构建、playwright 未装）都有明确记账方式（`unknown` 而不是假绿）。⇒ **可行，且不需要再向你征求裁定**。

---

## §6 我自行决定的事项（清单 + 理由 + 可回退性；你不同意可以直接推翻）

| # | 决定 | 理由 | 怎么回退 |
|---|---|---|---|
| **D1** | 合并顺序仍 **A → B → C**，每一轮合并后跑一趟全量门（约 18 分钟/趟） | A 的结构是另两条的地基；B/C 的文件与 A 零交，顺序只影响"谁的接口先落地" | 改成任意顺序都可，只是冲突预案要重写 |
| **D2** | C 落地写端点时 `test_webui_contracts.py` 的 A 条会**短暂红**（`api.ts` 少三行），由我在**合并那一轮**补 `ui/src/api.ts` 的 `stop`/`submit`/`settings` 三行 | 判据 A 是集合相等，两边必须同一次落地；让 C 去改 A 的文件会破坏零交与归因 | 三行删掉即回到现状 |
| **D3** | `_W0_UNCHECKED_TYPES` 里 `Checkpoint`/`CheckpointSpend` 两条登记：等 5a 落地（`state.type_decls()` 删掉那对）后由我删 | 避免两条线同时改同一文件（A 的判据文件） | 登记表本来就在判据里，加回即恢复 |
| **D4** | `draft/78 §2` 的"零交"证明口径在 2b 之后**重跑一次**并更新读数（`/api/state` 路由归属变了） | 文档里的读数必须与盘上一致 | 不适用（这是维护性动作） |
| **D5** | W4 时**尝试**装 playwright（`pip install playwright` + `playwright install chromium`）；装不上就让浏览器判据保持 `skip`（`unknown`） | 浏览器判据是 opt-in 的，`unknown` 是诚实状态；装了能真跑就更好 | 卸载即可；判据不变 |
| **D6** | `checkpoint` 那个 SSE 事件**本批不做**，在 `draft/75 §1.2` 那一行加注说明 | 需要 watch/poll 点，与"状态一律从盘上派生、不做后台轮询"的界面纪律直接冲突 | 将来要做得先改那条纪律（那是设计级改动，届时才找你） |
| **D7** | golden 快照**不重冻**，除非 W5 清仓后确有必要（那时一次性 + 逐格归因） | 快照是"声明与行为没变"的唯一可比对象；本项目纪律是攒到一次性重冻 | 不适用 |
| **D8** | W5 清仓采用"**先普查、再逐件删**"，普查仪器 `temp/_w5_legacy_census.py`（我写）给出"每个旧函数的引用者清单" | 裁定 P1 要求"迁一面删一面"，先有引用清单才谈得上删 | 不适用 |
| **D9** | 六页面的"空态/三态"视觉映射按 `draft/75 §1.3` 末尾那段**已有映射**执行，不新造第四态 | 与裁定 N1 一致 | 不适用 |
| **D10** | 三条线的子代理**不碰禁改区**；需要禁改区改动时统一由我落地并留痕（本轮 G2 已如此） | 与 `AGENTS.md` 的"人编写或人逐行走查 + 2 名 reviewer"一致；子代理无法承担签字责任 | 不适用 |
| **D11** | 发布门的豁免表（`tools/run_each_test_file.py`，FC-27）加一条 `tests/test_webui_browser.py` 并把上限 1→2 | 它与既有的 `test_providers_online.py` **同构**（整文件被默认筛掉 + 未装依赖即 skip），不是缺陷；不登记就会在发布门里常驻一格 `unknown` | 撤掉那一行、上限回 1；已登记为 `draft/67 §3b` 的第 3 条待签项 |
| **D12** | Windows 上的"权限收紧"**接受**现状口径：`chmod` 尽力 + 回读校验 + 如实回报（本机实测 `0o666` / `mode_enforced=False`） | POSIX 模式位在 Windows 上管不到 ACL；真收紧要 `icacls` 一类要起子进程，本会话沙箱会 EPERM。key 的保护不押在 ACL 上，押在裁定 E1 的"只写不读 + `***`"（已判三处读数） | 将来要上 ACL 就单开一批（那是权限面改动，届时报 §10.2） |
| **D13** | W1 里**第一块迁的就是 `/`**：`handle_root`（`GET /` 与 `/index.html`）改成服务 SPA 外壳（复用 `handle_static` 的 CSRF 注入逻辑，不写第二份），旧 `views.render_root` 留到 W5 给 `/run/{sid}` 用 | C 线实测"`GET /` 仍是旧壳、页面里没有 `#app` ⇒ 浏览器里到不了 SPA 首页"，即 P1 要迁的第一面；不迁的话六页面在真浏览器里没有入口 | 把 `handle_root` 改回旧壳一行即可；`tests/test_webui.py` 里被 `/` 影响的断言按 P1 迁移（条数不许减少） |

---

## §7 主控要写的仪器（不为交差，是为了"删/改"有据）

| 仪器 | 用途 | 状态 |
|---|---|---|
| `temp/_check_line_ownership.py` | 三条线文件级零交的机械证明 | ✅ 已有（2b 后重跑） |
| `temp/_verify_w0.py` | 公开面不变的对账（10 键 + 页面形状 + 8 个公开名） | ✅ 已有 |
| `temp/_audit_web_drafts.py` | draft/73–81 的引用与判据自审（① 硬错必须 0） | ✅ 已有 |
| `temp/_r009_strip.py` | R009 清理（tokenize/ast 定位，改完 `ast.parse` 自检） | ✅ 已有（已重写） |
| `temp/_gen_cited_ignore.py` | `.gitignore §14` 的证据物登记（被引用且在盘上的 `temp/*`） | ✅ 已有 |
| `temp/_faces_keys_probe.py` | 六面在夹具上真读出来的键（A 补 `_backend_keys()` 的依据） | ✅ 已有 |
| **`temp/_w5_legacy_census.py`** | **W5 用**：两个旧壳文件里每个顶层符号（函数/类/常量）的"真引用形态"清单（限定名 / 导入表 / 包级再导出 / 显式字符串），并给出"可删 / 先迁调用方 / 先改判据" | ✅ 已有（§12 是它的读数） |
| **`temp/_web_final_readings.py`** | **收口用**：一次打印 §1 那 14 条判据的当前读数（给"做完了"一个可复算入口） | ⬜ 待写（W5 之后） |

---

## §8 风险与对策

| 风险 | 早期信号 | 对策 / 兜底 |
|---|---|---|
| 合并冲突（三条线在 `draft/`、`.gitignore`、`api.ts`、`conftest.py` 上撞） | `git merge` 报冲突文件 | 按 `draft/78 §5` 的预案：A 的文件让 A · `conftest.py` 让别人让 B · docs 归 A · `.gitignore`/`temp` 取 master 版并重跑生成器 · `draft/` 我写 |
| 沙箱挡住前端构建 | `spawn EPERM` | 用更宽权限构建（已成功两次）；判据在沙箱内记 `unknown`，`tools/frontend_gate.py` 写明理由 |
| 我的批量文本工具再次误伤代码 | 全量门 §8 以 collection error 收场 | 已根治：工具改成 tokenize/ast 定位 + `ast.parse` 自检（FC-28）；每次改完必跑一次"逐文件编译 + 目标判据" |
| 子代理把"当前形状"写成硬相等，堵死下游 | 下游一开工就报"文件不存在/断言不等" | 已连修两处（`readers.ROUTES == ()`、`writes.ROUTES == (...)`）；口径固化为"钉不随施工阶段变的不变量"，写进两条线的简报与提示词 |
| 引用判据被上游改名打红 | 一次几十条"文件不存在" | 用"旧行原文 → 新结构同文"的迁移口（唯一命中才迁、不猜），本轮 72 处已清；历史快照（`draft/65b/66`）刻意不迁 |
| 判据松到"看起来绿" | 判据改了却没人复核口径 | 任何放宽都要在报告里点名"这是口径改变 + 为什么"，并在判据里留反例（如哈希正则那条：真产物 + 反例双钉） |
| FC-27 迟迟不签 | `noai_gate --git --since` 一直 `requires_human` | 不阻塞施工；阻塞 push（裁定 8a）。`draft/67 §3b` 已备好一页走查清单 |
| 三条线同时写盘导致门读数不可复现 | 门跑期间有人改文件 | 门只在我冻结时起跑；起跑前 `git status` 必须干净（工作树只有刻意不入库的探针） |

---

## §12 W5 的第一批读数（普查仪器已跑，`python -B temp/_w5_legacy_census.py`）

**`webui/views.py`（484 行 / 9 个顶层符号）**

| 符号 | 生产引用 | 判据引用 | 判定 |
|---|---|---|---|
| `_top` `_option_html` `_question_card` `_run_row` `_event_card` | 0 | 0 | **无引用 ⇒ 可直接删**（5 个） |
| `_page` | 1（`webui/server.py:64` 的导入表） | 0 | 先迁调用方 |
| `_not_found` | 1（同上） | 0 | 先迁调用方 |
| `render_root` `render_run` | 2（`server.py` + `__init__.py` **再导出**） | 0 | 先迁调用方；它们是 **public face**，删 = 公开面收窄（§3 W5 已写处置） |

**`web/assets.py`（629 行 / 4 个顶层定义）**

| 符号 | 生产引用 | 判定 |
|---|---|---|
| `THEME_CSS` | `web/emit_theme.py` | **不许删**（主题令牌的唯一来源，`ui/src/theme/generated/theme.css` 由它生成，判据 G 逐字节比） |
| `STYLESHEET` | `webui/views.py` | 随旧壳一起退场 |
| `APP_CSS` | 0 | 可删（它正是"只用令牌"那条判据 `test_app_css_uses_only_tokens` 的被检对象 —— 删它要**同时**处理那条判据，属于"先改判据再谈删"） |
| `__all__` | 1（`tests/test_webui_contracts.py`） | 同上：改 `__all__` 要同时看判据 |

> **仪器自身的两条口径修正也记在这里**（都是"假读数"的实例，值得留痕）：
> ① 第一版按"裸名字出现过"匹配 ⇒ 把 `tests/test_locallib.py` 的局部变量 `_page`、
> `tests/test_secretary.py` 自己定义的 `def _run_row(...)` 算成"判据在读 views 的私有函数"（**假引用**，
> 会让该删的不敢删）；现在只有"限定名 / 导入表 / 包级再导出"算强匹配，裸名字单列且**不参与判定**。
> ② 第一版把 `assets.py` 的路径写成 `webui/assets.py` ⇒ 报"不在盘上"（**假读数**）；真身是
> `web/assets.py`。另外它的文件体是常量，只列函数/类会显示"0 个顶层定义"，现在把模块级常量也列上。

---

## §9 收口判据（到这一步就算"Web 端做完"）

1. §1 的 14 条**除第 13 条（你签字）外全部 ✅**，并把该趟全量门的逐节读数填进 `draft/71 §2`。
2. `python -B temp/_web_final_readings.py` 一屏打印 14 条读数（谁想复核都能一条命令复算）。
3. `draft/78` 的零交证明与 `draft/77` 的台账（批次 × 线两维）更新到最终状态；`draft/80` 的 8 条裁定逐条标"已落地/落在哪个 sha"。
4. 工作树干净（`git status --porcelain` 只剩 3 条刻意不入库的登记物）；`noai_gate` 的读数如实（签字前后各留一份）。

---

## §10 我会回来找你的**只有这四类**（其余自理）

1. **要改已经敲定的设计/口径**（例如 D6 的 checkpoint 事件若要做，得先改"不做后台轮询"那条界面纪律）。
2. **需要新的权限面或新闸门**（H1 那类：某个写操作没有既有闸门可走）。
3. **只能由人做的动作**：FC-27 的 `--approve`（含本轮 G2 那两条）· GitHub push 的最终放行。
4. **交付面发生变化**（例如某条判据必须放宽、某个"完成定义"要改）。

除此之外——包括"先合哪条线、`api.ts` 三行谁补、playwright 装不装、W5 怎么删、文档怎么写"——**我都按 §6 自行决定并在提交信息与 draft 里留痕**。

---

## §11 push 前的普查清单（签完就跑，8a）

1. `git status --porcelain`：只剩 3 条刻意不入库的登记物。
2. 密钥形态扫描：对象库 blob 全扫（跳过 >5 MB），六类模式必须 0 命中。
3. 大文件：受跟踪面**无单文件 > 5 MB**（当前最大 1.86 MB）。
4. `noai_gate --git --since <起点> --check-approvals`：两条 G2 改动应为 `approved`（`reviewers` ≥ 2），其余如实。
5. 全量门一趟（§8 `0 failed`）+ `draft/71 §2` 填好。
6. `.gitignore` 的 `_env/`（约 5 GB）· `_archive/`（约 3.3 GB）· `node_modules/` · `agentflow/settings.json` 仍在忽略面内。
