# 批边界执行手册（写者全停后照这个顺序做，别临场发挥）

> **为什么要有这份手册**：四道门一次约 65 分钟；审计窗口两次作废都发生在"顺序/前提没守住"上。
> 边界上任何一步搞砸，赔的是一小时 + 一轮。所以把顺序、前置断言、期望读数全部写死。
> 观测时刻与证据路径照抄进 `draft/28` 的新节（格式见 §15/§18/§19）。

## 0. 进入条件（三条都满足才开跑）

1. `list_agents` ⇒ **没有任何 writer 在跑**（除我之外全部 `ready`；`running` 的只能是"读"的角色）；
2. 把上一条的**原始输出**落档成 `temp/writers-cred-<标签>.txt`（§73 的教训：裸断言 =
   "它两分钟没写"伪装成"已核实"）；
3. `python temp/run_gates.py <标签> --check-only --assert-no-writers --writers-credential temp/writers-cred-<标签>.txt`
   ⇒ **exit 0**，且 `temp/<标签>-gates.txt` 里有 `✓ 30 秒内 N 个文件逐字节未变`、操作者断言、
   `✓ 落档凭据 …` 三行。
   - 若 exit 2 且点名了文件 ⇒ **那是有写者**，回到第 1 条（**不许**调窗口长度绕过）；
   - 凭据默认 15 分钟内有效（`GATES_CRED_MAX_AGE` 可调，但别调到荒谬的大）。

## 0.5 次序（**先审计、后跑门** —— 这个次序是花钱买来的）

```text
① 静止前提（§0 三条）→ ② 派七批审计（R1d/R2b/R3/R4/R5/R6/R7，同一窗口，我不写 agentflow/）
→ ③ 收账：findings 逐条登记，有 finding 就**修**（修 = 窗口结束）
→ ④ 回到 ①（重新证明静止）→ ⑤ 修完的那一批**重派**（findings 必须为空）
→ ⑥ 七批全空 ⇒ 在**同一个仍然静止的窗口**里跑四道门 → ⑦ 收工核对
```

**为什么不能反过来**：`b74` 那次四道门跑了 87 分钟，读数有效；但只要审计随后报出一条要修的
finding，那次读数就**当场作废**（规则：修了 `agentflow/` 就等于这批读数作废）。
按 ①–⑦ 走，四道门只在"审计已全绿、且不会再改代码"的时刻跑一次。

## 1. 四道门（在**审计之后**、同一窗口内单独跑）

```powershell
cd D:\Incubator
python temp\run_gates.py b<编号> --assert-no-writers --writers-credential temp/writers-cred-b<编号>.txt   # 约 87 分钟，放后台 job
```

期望读数（**写进台账时逐条对照**）：

| 门 | 期望 | 证据 |
|---|---|---|
| 1 lint | `error 0`（warning/info 数照抄） | `temp/b<编号>-lint.txt` + `-gates.txt` |
| 2a 全量（默认） | `0 failed`（passed/skipped/deselected/xfailed 照抄） | `temp/b<编号>-suite-default.txt` |
| 2b 全量（Lean 进 PATH） | `0 failed` | `temp/b<编号>-suite-lean.txt` |
| 3a/3b 逐文件两环境 | `单独跑不过 0`（过/筛掉/豁免/一个用例都没有 各照抄） | `temp/b<编号>-perfile-default.txt` / `-lean.txt` |
| 4 release_all --since HEAD | 顶层 `pass=5 fail=1 unknown=0`，唯一 fail 是 `release-check`；**它内部 8 个分项只有 `noai` 是 fail** | `temp/b<编号>-release-all.json`（用 `python temp/_read_release_all_items.py temp/b<编号>-release-all.json` 读分项） |

**三条硬规矩**：① 不许 `--skip`/`--only`；② 读数出来后 `-gates.txt` 末尾那行"收工核对"必须是
**"窗口内无写入 ⇒ 读数有效"**（若是"作废"，整轮重跑）；③ 任何一道门红了 ⇒ **先修**，
修了 `agentflow/` 就等于这批读数作废，修完必须**重跑全套**。

## 2. 同一静止窗口内派审计（**第二波也一起派**：2026-09-27 的实际做法与理由）

- 手册原本写"分两波（避免 CPU 争用把逐文件测试压出假超时）"。本会话**一次派了七批**
  （`R1d`/`R2b`/`R3`/`R4`/`R5`/`R6`/`R7`）—— 理由：**此时四道门还没开跑**，
  没有"逐文件门在跑 100+ 个子进程"那种压力源，争用只落在各审计者自己的定向探针上。
- **残余风险（如实记）**：七批并发仍可能让某个审计者的探针**超时**，而"超时"与"判据红"
  在读数上可能混同。收账时对任何"超时型"读数**必须复核一遍**（重跑那条探针），
  不许直接把超时当成 finding 或当成通过。
- 若将来把审计与四道门放在同一个时间窗里并发，则**必须**回到"分两波"的老规矩。

派单文本 = `temp/reaudit5-COMMON.md` §0/§0.1/§1/§2/§3 + `temp/reaudit5-DISPATCH.md` 的本批增量
+ `§0.2 的三条新约定`（冻结集=scope 清单 / 静止证明落档 / 旧探针可能已过期）。
每批都要**逐字写明冻结集**，并要求审计者落 `temp/REAUDIT6-<批>.sha-before.txt` / `.json`
（**第 6 轮的产物名字用 `REAUDIT6-*`，不许覆盖第 5 轮的 `REAUDIT5-*`** —— 那些是作废轮的对照物）。

**审计期间我不写 `agentflow/`**（硬约束，§40.2）—— 这一条不看"精确的文件集"，从宽执行。
窗口从"四道门跑完"到"最后一波审计收工"一直有效（期间没有写者）。

## 3. 收账（审计回来之后）

1. 把每批的 `findings` 逐条登记（含 low）：新 id、级别、落点、**状态**（`已修且自证` /
   `待人裁` / `接受为残余` / `不成立`）+ `temp/` 证据；
2. **七批只要有一批 `findings` 非空**，就开一个修复批次（同一落点文件族），修完回到第 0 条
   **重跑门**、并**重派那一批**（该批必须回一个空的 `findings` 才算绿）；
3. 台账收口（**2026-09-27 的现实**：`§16` 与 `§15.13` 的"未处置"都已是 0，这里只剩增量）：
   - 新条目 `D-13`（守护 `D3` 的判据本身用退出码判用法错误）已进 `§2` → `§16` 为 `已修且自证`；
   - `§16` 里仍标"无独立逐条探针"的行：`temp/batchE1-<条目>.txt` / `batchE2-*.txt` 接进
     `_build_s16.py` 的证据覆盖层（`evidence_suffix()` 会自动带上观测时刻）；
4. 复跑三条台账判据：`python temp/_s16_evidence.py`、`python temp/_findings_open.py`、
   `python temp/_check_s7.py`；全部 0 缺口才算判据一绿；
5. `docs/PROPOSALS.md` 第四次回写（用 `temp/_append_proposals.py`，它带结构自检）。

## 4. 判据五（HARD）在边界上的动作

- `.noai-approvals.json`：跑 `python scripts/noai_gate.py --git --since HEAD` ⇒ 必须 **exit 1 /
  requires_human**；台账 16 条 / `reviewers` 0 / `audits` 0（**不许**跑 `--baseline`）；
- 每个禁改区文件都要有**改前备份 + 前后 sha256**：HEAD 锚在 `temp/zone-head-backups.tsv`（15/15），
  批前备份在各批的 `temp/batch*-*.bak`；本轮结束后把新改的补进那张表（`temp/_zone_head_backup.py` 重跑即可）；
- 有任何一步需要人做（例如 `--baseline` 收敛 `stale`）⇒ 写进交接，**不许**用非人类动作代替。
