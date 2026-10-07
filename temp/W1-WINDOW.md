# 阶段 B · 窗口 `W1` 的收工账（2026-09-27 21:34 → 22:1x；**待签字**）

> 依据：`temp/STAGE-B-W1-PROMPTS.md`（含两节补遗）+ 所有者 2026-09-27 的授权选项 **A**（"授权整个阶段 B"，
> 条件 = 每个窗口收尾**先贴改动清单 + 逐文件 sha256**，然后才落笔签字）。

## W1.1 三个修理工的交付（各自自证 + 我复核的读数）

| 写者 | 文件 | 关键读数 |
|---|---|---|
| `B-W1-noai-recon` | `scripts/noai_gate.py`、`tests/test_noai_gate.py`、`tests/test_noai_gate_ledger_recon.py`（新） | `--check-ledger` 当前字节 **exit 0**（清单 24 唯一路径 / 台账 23 条 / 差集恰 1 条 `src/agentflow/release_check.py` ⇒ 标"刻意预登记"）；漏登记 exit 1、没查成 exit 2；`--check-consistency` 仍 exit 0；`--paths capabilities.py` 仍 requires_human/2；`X-96.4-1` 旧口径核 18 个符号 → 新口径核 **61 个**（真实清单 0 问题）；副本负控 4 档全红得对 |
| `B-W1-seams` | `capabilities.py`、`agent_e.py`（纯 docstring）、`tools/__init__.py`、`tools/base.py`、`tools/verify_tools.py`、`tests/test_capability_seams.py`（新） | `import agentflow.capabilities` exit 0 且打印 **覆盖 127 / 声明 127 个 property，49 个动作，接缝 1 条**；两条能力层负控（删 sleep 接缝 / 凭空加 property）⇒ 导入失败并逐字点名；工具层负控③ ⇒ `ParamError` 点名注入名；替身夹具 82 passed（改前同数）；未改 `conductor.py`（交付 §7 逐条论证），留一行交接 |
| `B-W1-providers` | `providers.py`、`tests/test_providers_topicality.py`（新） | 英文题面对拍改前字节 **10 项读数全同**；中文题面 **UPSTREAM_CALLS=0**、三档 0/0/0；负控（副本注入恒 False）⇒ 中文原串**重新**被打出去、判据 5 failed；`-k "provider or retriev or evidence"` **166 passed**（基线 154） |
| 父代理 | `DEVELOPMENT.md`、`NOAI-REVIEW-REGISTER.md` | 活读数 `noai_gate_pytest_collected` **116 → 119**（`--collect-only` 实测 119，修掉 3 条红）；11d 登记的两条 doc 卫生项（`:48/:61` 裸 `--check-approvals` → 带 `--paths`；`:405` 不存在测试文件 → 换成真实存在的两个） |

## W1.2 中途的两次**跨写者半截状态**（都已自愈，如实记）

```text
① 21:39 悬空引用判据红：`src/agentflow/tools/base.py:286` 引用的 `_check_param_seams_are_registered`
   当时在 `tools/__init__.py` 里还没定义（全树真符号 0 次）⇒ 21:44 复跑 1 passed。
② 21:44:07 `import agentflow.tools` ImportError：`base.py` 21:43:50 把 `param_seam_violations` 改名成
   `tool_param_seam_violations`，`tools/__init__.py:42` 的 import 没跟上 ⇒ 连带 4 条 test_proof_location_* 红；
   21:46 起 import ok。
⇒ 两次都不是"最终缺陷"，是**并行窗口的半截写入**。教训（对下一窗口有效）：
   **收工读数必须写在"无 writer 在飞"之后**；跨文件改名要把同批的调用方写在同一批里。
```

## W1.3 三条**要独立记账**的事（都不是本窗口的 finding，但必须落账）

```text
① 修理工 `B-W1-providers` 自报：21:49:41 把 `python -m agentflow.providers` 当离线自检跑了，它**真连了网**
   （1 个请求、HTTP 503 后退出、0 USD、无写入）。不在任何验收命令里，之后未重跑 ⇒ 记"越出'零 API 花费'口径一次，
   代价 0 USD、无写入"。
② `evidence.py` 的 `SOURCE_STATUSES` 是闭集 ⇒ 要让逐源 `status` 逐字变成 `query_not_applicable_cjk`，
   需要给 `evidence.py` 加一个取值 + 在 `_retrieve_one` 认第三态（约 3 行）。本窗口做成了"不碰它也 fail-closed"
   （抛异常 ⇒ failed + reason 带状态名）⇒ **新增一行残余**，归 `W2`（落点 `src/agentflow/evidence.py`，非禁改区）。
③ `conductor.py` 的接线（把 `_check_params` 换成 `C.check_params`）**故意没做**：做了会把
   `tests/test_conductor.py` / `test_scheduler.py` 的 82 条替身路径打成 `refused`（因为替身不收 `sleep`）。
   ⇒ **新增一行残余**，归 `W2`（落点 `conductor.py` + 那两个测试文件；R3 的冻结集）。
```

## W1.5 签字前的**预检全量**（我自己跑的，避免 90 分钟的门跑到一半才发现红）

```text
python -m pytest tests/ -q -p no:cacheprovider        （2026-09-27T22:09:17 → 22:22:33）
⇒ exit=0   **2480 passed, 3 skipped, 8 deselected, 1 xfailed**（792.43s）
（对照：`b83` 的默认全量是 2439 passed ⇒ +41 = 本窗口三个新判据文件 15+11+12 与其它的和）
原始读数：temp/w1-preflight-suite.txt
```

## W1.6 签字前还要做的三件事（按顺序；做完才起 `b84`）

```text
① `list_agents` 落档"无 writer 在飞" ⇒ 写 temp/writers-cred-b84.txt（真读数，不许弱化）
② python temp\_zone_head_backup.py   ⇒ 23 个禁改区文件的 HEAD + 当前字节两份备份、字节核对失败 0
③ 六个待签文件逐个 `--baseline` + 两遍 `--approve`（见 temp/SIGNING-PACK-W1.md §2 的命令序列），
   然后 `--check-approvals` 复核 2/2 + temp/_ledger_snapshot.py + temp/_zone_signature_check.py
   【执行读数】① 凭据 2343→…（见 W1.7）；② 23/23 备份、字节核对失败 0（22:23:14）；
   ③ 六个文件全 [approved]（22:2x）—— 详见 W1.7
```


## W1.7 签字已执行（2026-09-27T22:2x；所有者授权选项 A）

```text
· `--baseline` 是**与 `--paths` 连用的开关**（我第一版写成 `--baseline <path> --paths <path>` ⇒ argparse 报
  `unrecognized arguments`）⇒ 正确形态：`python scripts/noai_gate.py --baseline --paths <path> --note "<摘要>"`
· 六个文件各 `--baseline` + 两遍 `--approve`（owner-1 / owner-2，`--scope` 逐条写清改了哪一段、`--verdict 逐行走查通过`）；
  第一遍后门会打印「还差 1 名不同 reviewer 才算批准」⇒ 证明 `REQUIRED_APPROVALS_ON_HIT=2` 真的在生效
· 复核：`--check-approvals --paths <六文件>` ⇒ **六个全 [approved]**（hash 与盘上一致 + 2 名不同 reviewer），exit 0
· 台账：entries 23 / reviewers 元素 44 / 分布 {0:1, 2:22} / 0 签只剩 `.noai-approvals.json`（不能自签 = 设计）
  `.noai-approvals.json` 28813 → 31017 B（重新登记 + 12 条新签名）
· `--check-consistency` exit 0；`--git --since HEAD` ⇒ 仍 requires_human / 22 条命中（21 已签 + 台账自己）
· 门自陈的诚实边界：每条 approved 都带「署名归属为**推断**，据 mtime 与会话边界得出，非独立证据」——
  这正是 §93.2 记的**代记名**边界，收口时不许把它读成"真实署名"
```

## W1.8 这一窗口跑完后要买的账

```text
· `b84`（四道门；已起，job pwsh-278）
· 第 12 轮重审五批：`R1d`（noai_gate/两个测试/台账）· `R4`（capabilities/tools/agent_e）·
  `R3`（providers）· `R2b`（verify_tools）· `R6`（DEVELOPMENT/REGISTER）—— 冻结集 `ROUND12-frozen-*`（无主 0）
· `docs/PROPOSALS.md` 回写（阶段 B 的账）
· 新增三行残余（`evidence.py` 第三态、`conductor.py` 接线、`X-91.5-5` 的 `counts['工作区内']` 改判到 `gates.py`）⇒ 进 `W2`
```


```text
① `list_agents` 落档"无 writer 在飞" ⇒ 写 temp/writers-cred-b84.txt（真读数，不许弱化）
② python temp\_zone_head_backup.py   ⇒ 23 个禁改区文件的 HEAD + 当前字节两份备份、字节核对失败 0
③ 六个待签文件逐个 `--baseline` + 两遍 `--approve`（见 temp/SIGNING-PACK-W1.md §2 的命令序列），
   然后 `--check-approvals` 复核 2/2 + temp/_ledger_snapshot.py + temp/_zone_signature_check.py
```


## W1.4 `X-91.5-5`（三处措辞级）的逐项现状

```text
① `tools/__init__.py:93-94` 旧注释        ⇒ **已由 `B-W1-seams` 在本窗口改掉**（见交付 §…）。
② `counts['工作区内']` 在 fail 支不作背景提名 ⇒ 实测这个名字在 `tools/release_all.py` 里**没有**，
   它在 **`gates.py`**（`r.counts["工作区内"]` / `["工作区内不存在"]`，G1 那一支）⇒ **改判落点**，归 `W2`。
③ `R010-c 文案缺空格拼接`                  ⇒ **当前不可复现**：打印 `scripts/lint_rules.py` 的 R010-c 实测输出，
   读者串是"核对了 52 条声明，其中以 info 登记为字面假阳性的 3 条（本次命中 3 条）；还有 49 条声明 `none` 的工具…"
   ⇒ 拼接正常（该子项应随 `G3`/`FIX11` 的文案重写消失）。**登记为"已随重写消失"，附这条逐字读数。**
```
