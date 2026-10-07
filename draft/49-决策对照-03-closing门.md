# draft/49 决策对照 03：收工门与验收表（closing）

> 本文件是**待拍板项的方案对照**：只取证、只列方案与成本，**不给最终裁定建议**。
> 覆盖簇「收工门与验收表（closing）」的 **8 个决策点**，逐点按同一格式给出「现状与证据 / 方案 / 不裁的默认后果 / 取舍点」。
> 本文件**只写这一个文件**：不改 `agentflow/src/`、不改工作区、不跑 pytest / 模型 / 网络。
> 取证方式：`read` / `grep` / `glob` + `python -B -c` 只读复算（`check_closing(checks=("acceptance",))`、
> `_leg_reading` 逐档实跑、`artifacts.verify_entries` 逐条、`Store.rows` 计数）。**未写工作区任何文件。**

---

## 0. 口径与分级

### 0.1 分级标记（照 `draft/47` §0）

- `[我复核]` = 本文件用只读命令**独立复算过**（命令在 §0.4）。
- `[子代理]` = 直接引用 `draft/46-04`（该报告自述为子代理产出、`draft/47` §1 如此登记），本文件**未独立复算**。
- `[本次确认]` = 本文件用 `read` 打开源码并**逐字核对**过的行号/原文。
- `[判断类]` = 可行性与批次取舍，**不是测量值**。

### 0.2 两根工作区根（任何读数必须标根）

| 代号 | 盘上路径 | 验收表 | `REPORT.md` | `ARTIFACTS.jsonl` |
|---|---|---:|---:|---:|
| **根 A** | `D:\Incubator\agentflow\projects` | **33** `[我复核]` | **46** `[我复核]` | **57** 个目录 `[我复核]` |
| **根 B** | `D:\Incubator\projects` | **0** `[我复核]` | 0（`46-04` 序言写 1 份，与 `48-04` §0.1 的 0 冲突） | **8** 个目录 `[我复核]` |

**纪律：**「33 份表 / 204 行」这一族统计**只代表根 A**；根 B **0 份**验收表 ⇒
凡是「改后哪几格从 pass→fail」的预测，**在根 B 上没有落点**（根 B 的格只能靠直接调 `_leg_reading` 采录）。
回放一律 `sid=None`（CLI 口径），与 `conductor.closing` 走 `sid=<这一趟>` 的差异本次未逐趟核对。

### 0.3 本文件现算的真机基线（全部 `[我复核]`）

| 读数 | 值 | 命令 |
|---|---|---|
| `closing.py` 行数 | **2087** | `len(CL.__file__ 内容.splitlines())` |
| `reviewaccept.py` 行数 | **555** | 同上 |
| `agent_prompts.py` 行数 | **1878** | 同上 |
| `DEFAULT_CHECKS` | **7 格**：`anchor / contradictions / load_bearing / report_shape / user_pending / substance / acceptance`（`closing.py:49` `[本次确认]`） | — |
| `LEG_CHECK_KINDS` | **30 档** | — |
| 33 份表逐格 | **32 fail / 1 unknown（`p6i`）/ 0 pass** | §0.4 命令 1 |
| 204 行轴阈值 | `min>0` **184** / 字面 `0` **11** / 未写 **9**；`na` 行 **4** | §0.4 命令 2 |
| 排除 4 行 `na` 后的轴 | `min>0` **184** / `0` **8** / 未写 **8**（合计 200） | §0.4 命令 2 |
| 真正吃到 `implicit_min` | **8** 行（`citation_records_vs_bibitems` 6 + `unfinished_request_rows` 2）；表里 `min` ≠ 该档 `implicit_min` = **0** | §0.4 命令 3 |
| 附件三件套 | **红 9/46**（`p5-run6`；`p6-research-from-zero`/`p6e`/`p6k`/`p6o`/`p8f`；`p6n`/`p6q`；`p7-open-questions`） | §0.4 命令 4 |
| 九节 | **短 1/46**（`p5-run6`，缺七/八/九；报告总数 46） | §0.4 命令 4 |
| `ARTIFACTS` 台账 | 根 A **57 目录 / 1387 ok / 0 changed**；根 B **8 目录 / 2599 ok / 589 changed** | §0.4 命令 5 |
| `for_question_id` 覆盖 | 根 A：`experiments` **54/217**、`conjectures` **0/66**、`statements` **0/138**、`documents` **0/69**；根 B：四项**全 0** | §0.4 命令 6 |
| `documents` 的引用面 | 根 A：`claims` **281** 条、**281 条都有 citations**、`exp:` 165 / `rel:` 18 / `lit:` 179；根 B：`claims` 168、`exp:` 217 / `rel:` 0 / `lit:` 14 | §0.4 命令 7 |
| `readings["acceptance"]` 的键 | **`checks_file` / `rows` / `research_chain`**（**没有** `reading_version`） | §0.4 命令 1 |

### 0.4 复算命令（只读，可原样重跑）

环境：`workdir D:\Incubator\agentflow`；`$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; $env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="D:\Incubator\agentflow\src"`

```powershell
# 1) 33 份逐格 + readings["acceptance"] 的键（本文件 §0.3 第 7 行、§0.3 的 32/1/0）
python -B -c "import pathlib,collections; from agentflow import closing as CL; from agentflow.store import Store; root=pathlib.Path(r'D:\Incubator\agentflow\projects'); fs=sorted(root.glob('*/out/paper/ACCEPTANCE-CHECKS.json')); c=collections.Counter(CL.check_closing(Store(p.parents[2]),project_dir='.',checks=('acceptance',)).status.get('acceptance') for p in fs); print(len(fs),dict(c)); print(sorted((CL.check_closing(Store(root/'p8g-fermat-shorter-proof'),project_dir='.',checks=('acceptance',)).readings.get('acceptance') or {}).keys()))"

# 2) 204 行轴与排除 na 后的轴（本文件 §0.3 第 4/5 行）
python -B -c "import pathlib,json,collections; root=pathlib.Path(r'D:\Incubator\agentflow\projects'); a=collections.Counter(); b=collections.Counter(); na=0
for p in sorted(root.glob('*/out/paper/ACCEPTANCE-CHECKS.json')):
    d=json.loads(p.read_text(encoding='utf-8'))
    for r in (d if isinstance(d,list) else d.get('checks') or []):
        k='absent' if 'min' not in r else ('zero' if int(r.get('min') or 0)==0 else 'gt0'); a[k]+=1
        if r.get('na') is True: na+=1
        else: b[k]+=1
print(dict(a),sum(a.values()),'na',na); print(dict(b),sum(b.values()))"

# 3) 真正吃到 implicit_min 的 8 行 + 表里 min ≠ implicit_min 的 0 行
python -B -c "import pathlib,json; from agentflow import closing as CL; from agentflow.store import Store; root=pathlib.Path(r'D:\Incubator\agentflow\projects'); hits=[]; mis=[]
for p in sorted(root.glob('*/out/paper/ACCEPTANCE-CHECKS.json')):
    ws=p.parents[2]; d=json.loads(p.read_text(encoding='utf-8'))
    for r in (d if isinstance(d,list) else d.get('checks') or []):
        if r.get('na') is True: continue
        k=str(r.get('kind') or '')
        if k not in CL.LEG_CHECK_KINDS: continue
        try: got,det=CL._leg_reading(Store(ws),k,ws)
        except Exception: continue
        im=det.get('implicit_min')
        if im is None: continue
        if not int(r.get('min') or 0): hits.append((ws.name,r.get('id'),k,im,got))
        if 'min' in r and int(r.get('min') or 0)!=int(im): mis.append((ws.name,r.get('id'),k,r.get('min'),im))
print('eat implicit_min',len(hits),hits); print('mismatch',len(mis),mis)"

# 4) 附件三件套 9 份 + 九节短 1 份
python -B -c "import pathlib; from agentflow import closing as CL; root=pathlib.Path(r'D:\Incubator\agentflow\projects'); rs=sorted(root.glob('*/out/review/REPORT.md')); print(len(rs)); print([(p.parents[2].name,[f for f in CL.ATTACHMENT_FIELDS if f not in p.read_text(encoding='utf-8')]) for p in rs if [f for f in CL.ATTACHMENT_FIELDS if f not in p.read_text(encoding='utf-8')]]); print([(p.parents[2].name,[n for n,_ in CL.REPORT_SECTIONS if n not in p.read_text(encoding='utf-8')]) for p in rs if [n for n,_ in CL.REPORT_SECTIONS if n not in p.read_text(encoding='utf-8')]])"

# 5) ARTIFACTS 分根全量
python -B -c "import pathlib,collections; from agentflow import artifacts as A
for root in [r'D:\Incubator\agentflow\projects', r'D:\Incubator\projects']:
    rp=pathlib.Path(root); tot=collections.Counter(); n=0
    for d in sorted(rp.iterdir()):
        if not (d/A.LEDGER_NAME).is_file(): continue
        n+=1; recs,_=A.read_ledger(d)
        for v in A.verify_entries(d,recs): tot[str(v.get('status'))]+=1
    print(root,'dirs',n,dict(tot))"

# 6) for_question_id 覆盖（两个根）
python -B -c "import pathlib; from agentflow.store import Store
for root in [r'D:\Incubator\agentflow\projects', r'D:\Incubator\projects']:
    rp=pathlib.Path(root); print('ROOT',root)
    for t in ['experiments','conjectures','statements','documents']:
        tot=has=0
        for d in sorted(rp.iterdir()):
            if not d.is_dir(): continue
            try: rows=list(Store(d).rows(t))
            except Exception: continue
            for r in rows:
                tot+=1; has+= 1 if r.get('for_question_id') else 0
        print('  ',t,has,'/',tot)"

# 7) documents.claims 的引用面
python -B -c "import pathlib,collections; from agentflow.store import Store
for root in [r'D:\Incubator\agentflow\projects', r'D:\Incubator\projects']:
    rp=pathlib.Path(root); cl=wc=e=r_=l=0
    for d in sorted(rp.iterdir()):
        if not d.is_dir(): continue
        try: docs=list(Store(d).rows('documents'))
        except Exception: continue
        for doc in docs:
            for c in (doc.get('claims') or []):
                cl+=1; cits=[str(x) for x in (c.get('citations') or [])]; wc+= 1 if cits else 0
                e+=sum(1 for x in cits if x.startswith('exp:')); r_+=sum(1 for x in cits if x.startswith('rel:')); l+=sum(1 for x in cits if x.startswith('lit:'))
    print(root,'claims',cl,'with_citations',wc,'exp',e,'rel',r_,'lit',l)"
```

---

## 1. 决策点一至八（方案对照）

### 决策 1（E-04b）— 覆盖面 `marked` 要不要收紧：一行 `na` 允许不允许把「整环的覆盖面」也一并关掉

- **现状与证据：**
  - `research_chain_gaps` 今天把 `na` 行算作**已覆盖**：`closing.py:342-349` `[本次确认]`
    （`:343` `hit = [k for k in members if k in used]`、`:344` `marked = [k for k in members if k in na_used]`、
    `:347` `if researched and not hit and not marked:`）。`na_kinds` 由 `:1304-1305` 从 `out` 里 `na is True` 的行取出。
  - **E-04a 堵住的「大部分」是哪一半**：E-04a 改的是**四条自动分支的守卫**（`:1319` / `:1340` / `:1360` / `:1378`，`[本次确认]`），
    把这四条从「`out` 里有没有这个 `kind`」改成「`computed_kinds` 里有没有」。四条分支是**门替没写进表里的档说话**的那四条：
    `reviewed_current_rows`（改完没复核）/ `document_body_rows`（骨架稿）/ `claim_evidence_fit_rows`（引文对不上）/ `manuscript_rows`（账本被模板灌满）。
    这四条认的四个档，**三档（`reviewed_current_rows` / `document_body_rows` / `claim_evidence_fit_rows`）在 33 份真表上出现 0 次**
    （`46-04` §2.7 末；本文件未独立复算「26/30 档出现过」，标 `[子代理]`）。
    ⇒ E-04a 之后，**给这四档写一行 `na` 不再能静默那一条分支**。
  - **剩下的是哪一半（本文件现算，`[我复核]`）**：E-04a 动的只是「分支」，**不动 `:344` 的 `marked`**。
    于是「一行 `na` 关掉整环覆盖面」这条后门**完全不变**：`p7b` 的 `B1`（`numeric_experiment_rows`，`na:true`）让
    「算或造」整环 `marked` 非空 ⇒ `missing` 里不出现「算或造」。逐字复算 `p7b-open-questions` 的读数：
    `na_groups = {'算或造': ['numeric_experiment_rows'], '交（手稿落盘）': ['supported_claims']}`，
    `missing` 里**没有**这两个环（`missing` 只有「检索（真的取回）」「看（关系分析）」「攻（攻坚推进）」「闭（请求闭环）」）；
    `groups['算或造'] = ['numeric_experiment_rows']`（同一行既算 `hit` 也算 `marked`）。
    ⇒ 「一行 `na` ⇒ 整环算覆盖 + 该环的自动分支一并关掉」这个**二合一后门**里，
    E-04a 只拆掉了「该环的自动分支」那半，**「整环算覆盖」那半原封不动**。
    另外 E-04a 覆盖不到的还有一层：**四条分支之外没有任何守卫**（未被表声明的档在 `_check_acceptance` 里不留下不发红的东西）。
  - **收紧要连坐的 4 行合法 `na`**（`draft/44` J-17 / `46-04` §2.1 末段 / §6.5 `[子代理]`，本文件逐行复核 `[我复核]`）；
    逐行把「改后 `missing` 会多出什么」现算如下：

    | 工作区 | 行 | `kind` | `na` 所在环 | 该环还有别的非 `na` 行吗 | 收紧后 `missing` 的实际变化 |
    |---|---|---|---|---|---|
    | `p7b-open-questions` | `B1` | `numeric_experiment_rows` | `算或造` | **没有**（`groups['算或造']=['numeric_experiment_rows']`） | **新增「算或造」**（`p7b` 的「算或造」整环正是被这一行撑起来） |
    | `p7b-open-questions` | `D2` | `supported_claims` | `交（手稿落盘）` | **有**（`document_literature_citations` 非 `na`） | **不新增环**（该环仍被另一行覆盖），该行改为不计覆盖 |
    | `p8d-fermat-shorter-proof` | `A2` | `reviewed_proof_rows` | `算或造` | **没有** | **新增「算或造」** |
    | `p8g-fermat-shorter-proof` | `C10` | `proof_experiment_rows` | `算或造` | **有**（`search_frontier_rows` 非 `na`） | **不新增环**（`p8g` 改前 `missing` 已是 `[]`，改后仍 `[]`） |

    ⇒ 4 行里**只有 2 行会让 `missing` 真的多出一个环标签**（`p7b` / `p8d` 各新增「算或造」），
    另 2 行（`p7b D2` / `p8g C10`）失去的是「这一行算覆盖」的资格、**不改变任何环的缺口清单**。
    这与 `48-04` §CL-02 预告的「4 处原因行变化」**不完全一致**：按本文件逐格复算，`missing` 一侧是 **2 处**，
    另 2 处只影响 `na_groups`/读数面。此差异必须在施工前用真机逐格采录对齐（本文件只算了 `missing`/`groups`/`na_groups` 三个键）。
  - `na` 出口的来历是 `draft/39` D49（`46-04` §2.1、`43-C` C-16 `[子代理]`）——**明确要保留**的第三态出口。

- **方案 A：`marked` 降级为「不计覆盖 + 读数警告」（读数级收紧）**
  - **做法：** 只在 `research_chain_gaps` 里新增读数键（例如 `na_only_groups`：哪些环只被 `na` 行覆盖），
    `:347` 的 `not marked` **一字不动** ⇒ `missing` 算法不变 ⇒ blocker `acceptance_stage_uncovered` 的语义不变。
  - **理由：** 只把「一行 `na` 关掉整环」这件事**变成看得见**，不改变门的判据强度（`46-04` §2.1 提供的形态之一）。
  - **成本：** 文件 **1** 个（`closing.py`）；落点 **1-2** 处（`:342-349` 的返回 dict + 新键）；估计 **+8 / -0** 行；
    会红的既有测试：**预期 0 条**（`tests/test_closing_gate.py:1312` 的 `chain["na_groups"]["算或造"]` 非空与 `:1351` 的
    `chain["missing"] == []` 都不动，因为 `missing` 与 `na_groups` 都不变）；
    快照/文档同步点：`readings["acceptance"]["research_chain"]` 新增一个键（`tests/test_closing_gate.py:793-804` 只比 `status`，不读该键）；
    真机影响：**33 份逐格 `status` 与 `findings.detail` 全部不变**（`missing` 不变 ⇒ `unmet` 不变）。
  - **风险与不可逆点：** 后门**仍在**：一行 `na` 依旧能让整环在覆盖面这一层「算覆盖」，
    且读数键**不参与判据** ⇒ 只是留痕，不改门的强度。
  - **兼容闸：** 33 份表 204 行的 `missing`/`got` 全部可比（无口径变更）；204 行历史行的 **`min` 轴 / `kind` 字面契约不受影响**。
  - **禁改区：** `closing.py` **不在 FC-27 清单**（`draft/47` §3-C2 `[我复核]` 该节结论；`46-04` §6.5 末行）⇒ 可按普通改动走。

- **方案 B：把 `marked` 从「算覆盖」降成「不算覆盖」（真收紧，`missing` 算法也改）**
  - **做法：** `:347` 改成 `if researched and not hit:`（或等价的「`marked` 只进读数、不进缺口判定」），
    并按 `46-04` §6.5 的「高风险」判定配负控与逐格采录。
  - **理由：** 堵住「用一行 `na` 关掉整档与整环」的后门；这是 E-04 家族的另一半（`draft/44` J-17 单列此条）。
  - **成本：** 文件 **1** 个（`closing.py`，若要同批改 `:356-363` 的 `note` 则仍是同文件）；落点 **2-3** 处（`:347` + `:344` 的语义 + `:356-363` 的说明文字）；
    估计 **+15 / -5** 行；会红的既有测试（本文件逐条读过断言，`[本次确认]`）：
    `tests/test_closing_gate.py:1312`（`:1350` `assert chain["na_groups"]["算或造"]`、`:1351` `assert chain["missing"] == []`）
    —— `:1325-1338` 的夹具给「算或造」「想」「检索（真的取回）」「攻（攻坚推进）」「看（关系分析）」五行都标了 `na`，
    它们各自的环**没有别的非 `na` 行** ⇒ `missing` 会从 `[]` 变成 5 项，`:1351` **必红**；
    `tests/test_closing_gate.py:1705`（`:1728` `assert "R8" not in "；".join(f.detail for f in rep.blockers)`）
    —— `:1719-1721` 把 `_FULL_COVER` 的 `R8`（`unfinished_request_rows`）换成 `na`，
    「闭（请求闭环）」环的成员只有 `unfinished_request_rows` 一档 ⇒ `missing` 新增「闭（请求闭环）」⇒ **必红**；
    `tests/test_closing_gate.py:1860`（E-04a 同批也要改这一条，见 `48-04` §CL-01，`[子代理]`）。
    快照/文档同步点：新读数键 + `:356-363` 的 `note` 里「某一档对这个项目天然不适用时就写 `na`」那一句要同步改写，
    否则读数与说明互相矛盾；真机影响（逐格、比 `findings.detail` 的原因行）：
    `p7b` 的覆盖面原因行新增「算或造」、`p8d` 新增「算或造」（两处 `fail → fail`，但原因行变了）；
    `p8g` 与 `p5-review-t17` 的覆盖面原因行**不变**；其余 29 份的 `missing` 不变（本文件只逐格核了这 4 行的三键，
    其余 29 份未逐格采录 `missing` ⇒ 施工前必须先跑一遍命令 1/2 采录改前原因行）。
  - **风险与不可逆点：** 把 D49 想要保留的合法出口**部分作废**（`p7b` / `p8d` 的「算或造」在真机表上从此必红）；
    `46-04` §6.5 逐字判「**高风险，须单独裁定**」，`draft/44` J-17 逐字「不许同批收紧」。
  - **兼容闸：** 33 份表的 `na` 行语义**变严**⇒ 「33 份表逐格 `status`」不变（今天全 `fail`），但**原因行变了 2 处**
    ⇒ 204 行的可比性必须按「原因行」而非「状态词」记账（`draft/44` J-20 的回放口径）。
  - **禁改区：** 无（`closing.py` 不在清单）；但**不许把 `na` 从词表/出口删掉**（D49 的合法出口）。

- **方案 C：同批把 `marked` 与四条分支守卫一起收紧（即 E-04a + E-04b 合成一批）**
  - **做法：** 在方案 B 的基础上，与 `:1319/1340/1360/1378` 的守卫改动同批上线。
  - **理由：** 一次把「一行 `na` 关掉整档与四条自动分支」整条后门封死。
  - **成本：** 文件 **1** 个；落点 **6-7** 处；估计 **+50 / -15** 行；
    会红的既有测试：**`1312` + `1705` + `1860` 三条同时红**（`:1860` 的 `:1877` `assert rep.status["acceptance"] == "pass"` 在 E-04a 下就必红，
    见 `48-04` §CL-01）；真机影响：E-04a 半 0 处翻转 + E-04b 半 2 处原因行变化（同上表）；
    快照/文档同步点：`48-04` §CL-01 的 `na_covered_groups`/`na_hidden_defects` + 本方案的 `na_only_groups` + `:356-363` 的 `note`。
  - **风险与不可逆点：** 两条改动的**反判据重叠**（`:1860` 同时被两条碰）⇒ 一次改两处判据时，
    「哪一条改动让哪一条测试红」不再可分辨，出事时无法二分定位；
    `draft/44` J-17 逐字把这条组合列为**不许**（「不许同批」）。
  - **兼容闸：** 同方案 B；且 `:1860` 的语义改写与「`na` 合法出口」的保留之间必须同时写清，否则测试与纪律互斥。
  - **禁改区：** 无。

- **不裁的默认后果：** 今天不做 ⇒ `research_chain_gaps:344` 的 `marked` 继续把 `na` 算作覆盖，
  `p7b` / `p8d` / `p8g` 的 `missing` **保持空**（逐字：`p7b` 的 `missing` 不含「算或造」），
  E-04a 单独上线后这 2 份工作区的 `acceptance` 仍可从 `fail` 回到 `pass`（只要给那几环补 `na` 行）。
  E-04a 落地后，后门**只剩覆盖面这一半**；不裁则这一半永久保留。

- **取舍点：** 分歧在「`na` 是**行的第三态**还是**环的第三态**」——收紧等于承认 `na` 只能豁免那一行，
  不收紧等于承认 `na` 可以豁免一整个环节（D49 的原话支持后者，E-04 的洞也是后者）。

---

### 决策 2（E-05）— 阈值/分母的取法：`min` 与表里 `min` 的关系、引文分母换不换只读基线

- **现状与证据：**
  - 今天的阈值是「**显式优先**」：`closing.py:1213` `want_min = int(row.get("min") or 0)  # 0 = 让这一档自己定阈值`
    与 `:1266-1275`（`:1266` `if not want_min:` ⇒ `:1269` 读 `implicit_min`）`[本次确认]`。
    ⇒ 写表的人可以用一个**更小**的显式 `min` 把该档自算的阈值压低。
  - 引文分母今天取「**主稿优先**」：`:575-577` `draft = out/paper/main.tex` → `base = source/main.tex` →
    `src = draft if draft.is_file() else base`；读数键 `:593` `counted_from` 逐字记着「从哪儿数的」`[本次确认]`。
  - `manuscript_edited` 今天比 **sha**（一个字节即算改过）：`:560-563` `same = d_sha == b_sha` ⇒ `(0 if same else 1)` `[本次确认]`。
  - **真机三条读数**（`draft/44` J-18 / `46-04` §2.2 `[子代理]`；本文件独立复算前两条 `[我复核]`）：
    ①**表里 `min` ≠ 该档 `implicit_min` 的行 = 0**（逐行核对，`mismatch` 列表为空）；
    ②**真正吃到 `implicit_min` 的只有 8 行**：`citation_records_vs_bibitems` 6 行（全 `min` 未写、`implicit_min=7`）
    + `unfinished_request_rows` 2 行（`p8f` `C5` / `p8g` `C8`，`min` 未写、`implicit_min=0`）；
    第 **9** 行是 `p8g` `C2`（`retrieval_ok_rows`，显式 `min=3`、`implicit_min=3` ⇒ **取大后产出不变**）；
    ③`citation_records_vs_bibitems` 的 6 次使用中主稿与基线的 `\bibitem` **都是 7** ⇒ 换分母不改读数；
    `manuscript_edited` 9 次 `got=1` 去空白后仍全不相同 ⇒ 规范化不改读数（③ 标 `[子代理]`，本文件未复算字节差）。
  - **口径差（必须记账，不许折平）**：`46-04` §3.1 写「`min>0` **184** / `min=0` **8** / 未写 **8**」（合计 **200**，
    另有 4 行 `na` **未计入**该轴）；本文件复算的**全 204 行轴**是 `184 / 11 / 9`。
    两轴的 `min>0` **一致（184）**，差异全部落在 `min=0` 与「未写」的边界上（排除 4 行 `na` 后正是 `184 / 8 / 8`）。
    ⇒ 施工时以「`min>0` = 184」为共同锚点，`8/8` 与 `11/9` 两个小口径不许混用。
  - 「取大」的一个**必须写清的边角**：`unfinished_request_rows` 的两行**只写 `max: 0`、完全不写 `min`**，
    该档的 `implicit_min` 是 `0`（`closing.py:793` `"implicit_min": 0, "implicit_max": 0`）`[本次确认]`，
    而 `:1273` 的既有语义是「只声明了上限的档 ⇒ `want_min = 0`」。
    若「取大」被实现成 `max(int(row.get("min") or 0), int(detail.get("implicit_min") or 0))` **而不保留 `:1273` 的分支**，
    这两行的 `want_min` 会从 0 变成……仍是 0（因为该档 `implicit_min` 字面就是 `0`）⇒ **产出不变**；
    但**换作任何「有 `implicit_max` 且 `implicit_min` 缺省为 1」的档就会立刻翻红** —— 这是实现层面的分叉，不是口径层面的。

- **方案 A：`min` 与 `implicit_min` **取大**（`min` 从此只能把阈值提高）+ 分母换只读基线 + `manuscript_edited` 去空白规范化**
  - **做法：** 三处同改：①`:1266-1275` 改成 `effective = max(declared, kind_min)`（并保留 `:1273` 的「只有上限」分支）；
    ②`:577` 改成 `src = base`（只读基线）；③`:560-563` 改成「去空白规范化后比哈希」，读数并列 `raw_changed` / `substantive`。
    新增读数键 `min_overridden: {declared, kind_min, effective}` / `denominator_from` / `draft_bibitems`。
  - **理由：** 把「写表的人可以合法挑松的那一套」（`43-C` C-05）关掉；让「改没改稿」不被空白差异误判。
  - **成本：** 文件 **1** 个代码 + **1** 个规格说明（`specs/m.py:75` 的措辞同步，**FC-27 禁改区**，见下）；
    落点 **3** 处（`:1266-1278` / `:575-596` / `:549-568`）；估计 **+40 / -14** 行；
    会红的既有测试（本文件逐条读过断言，`[本次确认]`）：
    `tests/test_closing_gate.py:371`（`:397` `row["min"] == 3`、`:408` `fail`、`:420` `pass`；夹具在 `:386` **只写 `out/paper/main.tex`**）
    ⇒ **换基线后该夹具的 `source/main.tex` 不在盘上 ⇒ 整格会变 unknown，这条必红**（须补夹具）；
    `tests/test_closing_gate.py:322`（`:351` `fail`、`:360` `pass`、`:366` `unknown` + `:367-368` `== ["acceptance_leg_unreadable"]`）
    ⇒ 取大与规范化**不改**这条的夹具结果（`:333` vs `:357` 差「改过了」三字是**实质**差异），
    但 `:366` 的 `unknown` 会被 CC-05 的第四态改掉 ⇒ **本方案必须与 CC-05 同批**（`48-04` §CL-03/CL-11）；
    快照/文档同步点：三处新读数键进 `readings["acceptance"]`；`specs/m.py`（禁改区）与 `closing.py:78-80` 的词表说明；
    **真机影响（33 份逐格）：0 处**——8 行吃到 `implicit_min` 的行里没有一行会因「取大」改变 `ok`；
    6 行引文档的主稿/基线 `\bibitem` 都是 7（换分母不改数）；`manuscript_edited` 去空白后仍全不同（不改数）；
    `p6i` 这一格在本方案单独上线时仍 `unknown`，**与 CC-05 同批后**才 `rows: 0→11`、`unknown→fail`（`46-04` §6.3 `[子代理]`）。
  - **风险与不可逆点：** 换分母后「基线不在盘上」的情形**必须有归宿**：今天的 `ValueError` ⇒ 整格 `unknown`（`:1254-1265` catch-all + `:578-579`）
    ⇒ 与 CC-05 的第四态**互为前提**；不配套就会出现「只有主稿 ⇒ 整格没查成」。
    `46-04` §6.4 第 1 条把「历史 `got` 是旧口径下的数」列为**不可逆点**：必须按 `draft/45:12` 在 `draft/44` 记「从哪一趟起口径变了」。
  - **兼容闸：** 「表里 `min` ≠ `implicit_min` = 0」是**零翻转**的直接证据（本文件 `[我复核]`）⇒ 33 份表 / 204 行的 `ok` 面可比；
    `kind` 的字符串契约不许改（`46-04` §6.4 第 2 条）。
  - **禁改区：** `specs/m.py` **是 FC-27 禁改区**（`[category: auth-audit]`，`AGENTS.md` 逐字「角色 M 的声明真身……改这里等于改权限面本身」）
    ⇒ 该处镜像同步**必须走人审（人编写或人逐行走查 + 2 名 reviewer 批准）**；`closing.py` 本身不在清单。

- **方案 B：保持现状（「显式优先」+ 主稿优先 + 比 sha）**
  - **做法：** 三处一字不改。
  - **理由：** 三条被指控的口子在真机上**从未被用过**（`min` 压低自算阈值 = 0 行；分母差异 = 0；空白差异 = 0）——
    是「潜在风险」，不是「有真机证据的缺陷」（`46-04` 的判定原文）。
  - **成本：** 文件 **0** 个；落点 **0** 处；估计 **+0 / -0** 行；会红的既有测试：**0 条**；
    真机影响：**0 格**（什么都不变）。
  - **风险与不可逆点：** 口子留着；将来有人写一张 `min: 1` 的表就能把 7 条的引文阈值压到 1，
    而这**不会**在任何既有测试里红（今天没有一条用例覆盖「显式 `min` 比 `implicit_min` 小」）。
  - **兼容闸：** 无需记账（口径未变）。
  - **禁改区：** 不涉及。

- **方案 C：只对「有基线的工作区」换分母（分母按可获得性分档）**
  - **做法：** `:577` 改成「`base` 在 ⇒ 用 `base`；`base` 不在而 `draft` 在 ⇒ 用 `draft` 并在读数里标 `counted_from`」，
    即分母**随可获得性**切换，而不是「只读基线」。
  - **理由：** 保住 `:371` 那个「只写主稿」的既有夹具（不必补 `source/main.tex`），同时让有基线的工作区按基线数。
  - **成本：** 文件 **1** 个；落点 **1** 处（`:575-596`）；估计 **+10 / -3** 行；会红的既有测试：**预期 0 条**
    （`:371` 的夹具只写主稿 ⇒ 仍走 `draft` 分支 ⇒ `:397` `min == 3` / `:408` / `:420` 全不变）；
    快照/文档同步点：新读数键 `denominator_from` 的取值集合变成三态（`base` / `draft` / 缺），说明要写清；
    真机影响：**33 份逐格 0 处**（6 次使用里主稿与基线都是 7，两个方向同数）。
  - **风险与不可逆点：** 「同一份表、同一个工作区、不同趟次」可能**换分母**（今天有 `source/`、明天没有 ⇒ 数出来的阈值不一样），
    这正是 `46-04` §6.4 第 1 条点名的「历史 `got` 不可比」的来源之一；三态读数比两态更难在回放里比原因行。
  - **兼容闸：** 与方案 A 相同的「0 处翻转」证据；但**可解释性更弱**（读数里出现两种分母）。
  - **禁改区：** 同方案 A（`specs/m.py` 的措辞仍要同步，否则人与门两套口径）。

- **不裁的默认后果：** 今天不做 ⇒ `:1213` 的「显式优先」继续生效，
  `p8g` `C2`（`min: 3` / `implicit_min: 3`）与另外 8 行的读数**全部不变**；
  `citation_records_vs_bibitems` 的 6 行继续按**主稿**数 `\bibitem`（今天两处都是 7 ⇒ 无差异）；
  `manuscript_edited` 继续**按字节**判「改过」（9 次全为实质差异 ⇒ 无差异）。
  ⇒ 不裁在真机上**一格不动**，代价是三条潜在口子继续存在，且**没有测试守着它们**。

- **取舍点：** 分歧在「零真机翻转的潜在风险要不要现在花一次口径变更的代价去堵」——
  堵，就要付「历史 `got` 换口径 + `specs/m.py` 走人审 + 与 CC-05 同批」的成本；不堵，就要接受「没有测试守着的口子」。

---

### 决策 3（S-05）— 三条腿怎么处置：有结论的实验 / 我方派生命题 / 交稿↔问题

- **现状与证据：**
  - 词表今天**没有任何一档**问「数学往前走了没有」（`46-04` §2.5 ②）；`RESEARCH_CHAIN_GROUPS` 八环 20 档在 `closing.py:272-319` `[本次确认]`。
  - **腿 1（有结论的实验）可做**：伪码 `conclusive_experiment_rows = experiments 里 result ∈ {supports, refutes} 且
    (claim/certificate/search_bound 至少一项非空) 的行数`；基线 `experiments` 根 A 217 = `supports` 55 / `refutes` 24 / `inconclusive` 138（63.6%），
    根 B 189 = 124 / 0 / 65，**合计 406 中 `inconclusive` 203（50.0%）**（`46-04` §2.5 `[子代理]`；`draft/44:41`）。
    本文件另测：根 B 逐目录 `experiments` 合计 **85** 行（4 个目录 25 行 / 1 个 26 行 / 2 个 29 行 / 1 个 5 行），
    与 `46-04` 的 189 **不一致** ⇒ 根 B 的分母本身有口径未对齐（标 `[我复核]` 的 85 与 `[子代理]` 的 189 冲突，**不许折平**）。
  - **腿 2（我方派生命题 + 等级）已判不可行**：`statements` 根 A **138** 行、`origin=own_result` **13** 行，
    而 `bits_from_row` 的 `grade` **全部 `conjecture`**（`pre_theorem` 6 行全是 `external_lit`）
    ⇒ 这一档**恒为 0**，只会制造一条**恒红判据**（`46-04` §6.5 / `draft/44` J-22 `[子代理]`）。
    前置是 **F-01 / EE-12**（`agent_b/register_statement.py` 要写 `bits`）。
  - **腿 3（交稿↔问题）字段面撑不住**（本文件逐项独立复核，`[我复核]`）：
    `schema.py:2394` 的 `documents` 只有 `sections` / `claims` / `open_problems`（数组维度登记表，逐字）；
    `Document` 数据类（`schema.py:1326-1357`）的 `claims` 元素是
    `{"claim_id","section","text","evidence_kind","citations":[...],"is_negative","negation_kind","disclaimer"}`，
    `citations` 形如 `rel:0007` / `lit:0003#p.4` / `exp:0002` —— **没有任何 `for_question_id`**。
    `for_question_id` 在 `schema.py` 里只挂在三处：`SearchRequest:219`、`Experiment:1080`、`AttackPlan:1211`。
    真机覆盖：`experiments` **54/217**、`conjectures` **0/66**、`statements` **0/138**、`documents` **0/69**；根 B 四项**全 0**。
    引用面（本文件现算）：根 A `documents.claims` **281** 条、**281 条都带 citations**（`exp:` 165 / `rel:` 18 / `lit:` 179）；
    根 B `claims` 168 条（`exp:` 217 / `rel:` 0 / `lit:` 14）。
    ⇒ 走引用链时，`exp:` 那一部分**只有约四分之一**能回落到带 `for_question_id` 的实验行上（54/217），
    `conjectures` 与 `statements` 这两条回落路径**今天恒为 0**。
  - 「腿 3 不许进覆盖面」（`46-04` §2.5 ③ 逐字：第三档**先只做读数、不进覆盖面**）；
    `schema.py` 是 **FC-27 禁改区**（`[category: schema-migration]`，逐字「表结构与版本号 —— 改它等于改磁盘格式契约」）。

- **方案 A（腿 1，可做）：新增 `conclusive_experiment_rows` 并挂进「算或造」环（或新开一环）**
  - **做法：** 词表加一档（`closing.py:80-244`）+ `_leg_reading` 加一段（`:470-1126`）+ 挂环（`:287-291`）；
    读数**必须并列分母** `experiments_total`；镜像三处（`agent_prompts.py` 八环点名段与逐字清单、`specs/m.py:69-79`）**挂在 CC-03/CC-09 同批**。
  - **理由：** 纯读数、今天即非零（179/406 有结论），不改既有档口径。
  - **成本：** 文件 **1** 个代码 + **2** 个镜像（其中 `specs/m.py` 禁改区）；落点 **3** 处 + 镜像 3 处；估计 **+60** 行；
    会红的既有测试：`tests/test_agent_prompts.py:196-201`（`:200` `missing = [k for k in CL.LEG_CHECK_KINDS if k not in text]`）
    ⇒ **加档后必红**，除非同批把该档写进 M 的 brief（`[本次确认]` 该断言形态）；
    `tests/test_conductor_tools.py:101-115` 按 `CL.DEFAULT_CHECKS` 比、**不按 `LEG_CHECK_KINDS`** ⇒ 本方案不红（只要不加第八格）；
    快照/文档同步点：`draft/44` 要记「`research_chain` 的 `missing` 口径从哪一趟起变了」（`46-04` §5.1 末）；
    真机影响：**33 份逐格 0 处原因行变化**（新档不在任何一份历史表里，204 行里没有它）；
    唯一可能变的是 `research_chain.groups` 的成员集合变大（加成员**不会**让已有环变「未覆盖」）；
    口径锚点 `p8g`（唯一覆盖面 8/8 齐的工作区）改后 `missing` 仍应为 `[]`（本文件 `[我复核]` `p8g` 改前 `missing == []`）。
  - **风险与不可逆点：** 加档即改「覆盖面可用成员」这一口径；若新档被写进历史表则历史 `got` 不可比 ⇒ 必须登记口径变更。
    新档的 `got` **今天没有真机样本**（只能现算），`46-04` §7.6 明确「不核 3 档的语义边界」。
  - **兼容闸：** 30 档取值不变 + 只加档 ⇒ 204 行历史表的 `kind` 字面契约不受影响；`min>0 = 184` 的锚点不受影响。
  - **禁改区：** `specs/m.py`（镜像）**是禁改区 ⇒ 人审**；`closing.py` / `agent_prompts.py` 不在清单。

- **方案 B（腿 2，不得单独上线）：`own_result_statement_rows`（我方派生命题 + 等级）**
  - **做法：** 伪码 `statements 里 origin=own_result 且 bits_from_row(r)["grade"] ∉ {conjecture}` 的行数。
  - **理由：** 它问的正是「我们自己的命题有没有走到 conjecture 之上」这件事，方向正确。
  - **成本：** 文件 **1** 个代码 + **1** 个前置模块（`agent_b/register_statement.py`，属 F-01/EE-12）；
    落点 3 处；估计 **+40** 行；会红的既有测试：**不适用**——它的后果不是「某条测试红」，
    而是**门永远红**（`statements` 138 行里 `own_result` 13 行的 `grade` 全是 `conjecture` ⇒ `got=0`）；
    真机影响：若硬上，**33 份表的覆盖面/验收行里凡写这一档的行恒 `fail`**（今天 0 份写它 ⇒ 无样本，
    但一旦写就是恒红读数）。**本文件按 `46-04` §6.5 与 `draft/44` J-22 的判定，不把它列为可做。**
  - **风险与不可逆点：** 制造一条**恒红判据**（比「某条测试红」更重：它把门变成常红，读数失去分辨力）。
  - **兼容闸：** 前置未落地前**无兼容闸可言**（恒红）。
  - **禁改区：** 前置实现涉及 `agent_b/register_statement.py` 与 `bits` 的落盘面（属 F-01/EE-12 的裁定面）。

- **方案 C1（腿 3，改 `schema` 加字段）：给 `documents.claims[].for_question_id` 加字段**
  - **做法：** 在 `schema.py` 的 `Document.claims` 元素形状里加 `for_question_id`（并同步 `ARRAY_FIELD_KINDS` / `TABLES` / `SCHEMA_VERSION` 的裁定面），
    然后按「直接读字段」实现 `question_delivery_rows`。
  - **理由：** 这是「交稿↔问题」唯一**结构上成立**的实现路径（今天只能走引用链）。
  - **成本：** 文件 **≥2** 个（`schema.py` + `closing.py`）+ 若干写入口（G 的建文档路径）+ 历史快照校验面；
    落点 ≥4 处；估计 **+50** 行以上；会红的既有测试：**未知**（`schema.py` 的字段面改动牵动
    `tests/` 里所有快照与 `validate_table` 用例，`draft/47` §3-C1 记着「1322 份历史快照逐份 `validate_table`」的同类证据 `[子代理]`）；
    真机影响：字段今天**全空**（`documents` 0/69）⇒ 改后 `got=0`，**这一档在真机上恒红**，直到写入口开始填值。
  - **风险与不可逆点：** **命中最重的禁改区**：`schema.py` 是 `[category: schema-migration]`（改它等于改磁盘格式契约），
    同时 `[category: eval-criteria]`；历史数据不会自动获得该字段（要么恒空、要么迁移）。
  - **兼容闸：** 有历史行可比性风险（新字段全空 ⇒ 「没查成」与「0」的区分必须靠三态，不能靠 `0`）。
  - **禁改区：** **`schema.py` 是 FC-27 禁改区 ⇒ 必须人审**（人编写或人逐行走查 + 2 名 reviewer 批准）。

- **方案 C2（腿 3，降级为「可判链」读数）：只做读数、不进覆盖面**
  - **做法：** 按引用链回落：`documents.claims[].citations` 里的 `exp:<id>` / `rel:<id>` → `experiments.for_question_id` /
    `conjectures.for_question_id`，数**不同 `question_id`** 的个数；读数**并列 `unlinked_claims`**（回落不到问题上的断言条数）
    与分母；**不进覆盖面**（`46-04` §2.5 ③ 逐字）。
  - **理由：** 不动禁改区、不改磁盘契约，把「有多少断言挂得上问题」这件事实**变成可见读数**。
  - **成本：** 文件 **1** 个代码 + **2** 个镜像；落点 3 处 + 镜像 3 处；估计 **+50** 行；会红的既有测试：
    与腿 1 同一条（`tests/test_agent_prompts.py:200`，加档必红）；真机影响：新档不在历史表里 ⇒ **33 份逐格 0 处**；
    读数的真机形态可从本文件 §0.3 的引用面**预先算出**：根 A 的 `exp:` 引用 165 处，
    但可回落的实验只有 54/217 带 `for_question_id` ⇒ `unlinked_claims` 在真机上**会很大**（本文件未逐条算该数）。
  - **风险与不可逆点：** 把「25% 覆盖率」的链路当成「链路可用」是**明确禁止**的（`48-04` §CL-08 边界逐字）；
    读数的分母（`experiments_total` / `claims_total`）必须与 `got` 并列，否则「0」会被读成「没问题」。
  - **兼容闸：** 不进覆盖面 ⇒ 不改 `missing` 口径 ⇒ 无需登记「口径从哪一趟起变了」（若进覆盖面则必须登记）。
  - **禁改区：** 无（`closing.py` 不在清单）；`specs/m.py` 的镜像仍是禁改区 ⇒ 人审。

- **方案 C3（腿 3，挂起）**
  - **做法：** 什么都不做，在 `draft/44` 保留「未变」的空白记录。
  - **理由：** 字段面撑不住时，「挂起」是最省成本且不制造假读数的处置。
  - **成本：** 文件 **0** 个；落点 **0** 处；估计 **+0 / -0** 行；会红的既有测试：**0 条**；真机影响：**0 格**。
  - **风险与不可逆点：** 「交稿有没有回答立起来的问题」这件事在收工门上**继续没有任何读数**；
    引用链的 25% 覆盖率与 `conjectures`/`statements` 的 0 覆盖继续不被看见。
  - **兼容闸：** 无需记账。
  - **禁改区：** 不涉及。

- **不裁的默认后果：** 今天不做 ⇒ 词表仍是 30 档、八环 20 档（`closing.py:272-319`）不变；
  「数学往前走了没有」在收工门上**一格读数都没有**：`inconclusive` 203/406（50%）可以**全绿收工**；
  `p8g` 的覆盖面仍是 8/8 齐、`missing == []`（本文件 `[我复核]`）。
  腿 2 不裁 ⇒ 不会上线（它一上线就是恒红）；腿 3 不裁 ⇒ 引用链的 25% 覆盖率继续不被记录。

- **取舍点：** 分歧在「腿 3 值不值得为一个今天全空、只能给 `unlinked_claims` 的读数，
  去支付 `schema.py` 禁改区的人审成本（C1）；还是只做不承担判据的读数（C2）；还是干脆不记（C3）」。

---

### 决策 4（EE-05）— `ARTIFACTS.jsonl` 完整性读数要不要升成 `DEFAULT_CHECKS` 的第 8 格

- **现状与证据：**
  - `closing.py` 全文**零处**提到 `artifacts`（`48-04` §CL-13 逐字；本文件 `grep for_question_id`/相关复核一致，标 `[本次确认]` 该事实由 `46-04` §2.10 ① 给出）。
  - **两根真机读数（本文件独立复算，`[我复核]`）**：
    根 A：`ARTIFACTS` 目录 **57** 个 ⇒ `{'ok': 1387}`，**`changed` = 0**；
    根 B：`ARTIFACTS` 目录 **8** 个 ⇒ `{'ok': 2599, 'changed': 589}`（≈18.75%）。
    与 `46-04` §2.10 / `draft/44` J-24 逐字一致；`draft/47` §2 第 20 组的「4575 行 / 抽验 80 行 = 77 ok / 3 changed」是**抽样**口径，两者不冲突。
  - **「进格 = 立刻把 `changed` 变成 fail」的后果链条（逐格写清）：**
    `artifact_ledger_bad_rows` 的 `got = changed + missing + unreadable`，`implicit_max = 0` ⇒
    凡把该档写进表的工作区，根 B 的 8 个目录里任一条 `changed` ⇒ 该行 `ok is False` ⇒ `unmet` 非空 ⇒ `acceptance = fail`。
    **但今天是 0 格立刻翻**：根 B **0 份验收表**（本文件 §0.2 `[我复核]`）⇒ 根 B 的 589 条 `changed`
    **不会**出现在任何真机表的逐行判定里。要让它们翻，必须有表把这一档写进去（今天没有）。
    ⇒ 「进格」的真机后果分两步：**第一步 0 格**（没有表写它）；**第二步**（一旦 F-06 生成器或人把该档写进表）
    根 B 的表会在 `acceptance` 上从 `pass`/`fail` 变成**因 589 条 `changed` 而 `fail`**。
  - 「是否进 `DEFAULT_CHECKS` 第八格 = 独立裁定」（`46-04` §2.10 ③ 逐字）；`draft/47` §5 第③点把它列为人裁点。
  - 既有反判据（本文件逐字读过，`[本次确认]`）：`tests/test_conductor_tools.py:101-115`
    （`:113` `missing = [name for name in CL.DEFAULT_CHECKS if name not in text]`、`:115` `assert "五条" not in text`）
    —— 它**按 `DEFAULT_CHECKS` 比**，所以 7→8 会红，6→7 也一样红（`:115` 的「五条」是历史遗留断言）。
  - 已存在的陈旧陈述：`tests/test_release_all.py:2232` 把 `closing.py` 的职责写成「五条」（今天已是七格）`[本次确认]`；
    `conductor_tools.py:30-31` 的顶部工具表也写「五条」（`48-04` §CL-15 `[子代理]`）。

- **方案 A：升成第 8 格（`DEFAULT_CHECKS` 7→8）**
  - **做法：** 新增 `artifact_ledger_bad_rows` 档（`closing.py:80-244` + `:470-1126`）+ 把 `"artifact_ledger_bad_rows"` 加进 `:49` 的 `DEFAULT_CHECKS` + 同步 `conductor.closing` 的描述/`returns` 与 `cli.py` 的逐格打印。
  - **理由：** 它对上一条已写进纪律的红线（「产物登记必须与盘上一致」，`draft/44:134`）。
  - **成本：** 文件 **3-4** 个（`closing.py`、`tools/conductor_tools.py`、`tests/test_conductor_tools.py`、(可选) `tests/test_release_all.py` / `cli.py`）；
    落点 **4-5** 处；估计 **+45** 行；
    会红的既有测试（逐字）：`tests/test_conductor_tools.py:113`（`:113` 的 `missing` 会含新格名）⇒ **必红，除非同批改工具描述**；
    `tests/test_conductor_tools.py:115`（`"五条" not in text`）—— 今天已通过（描述里没有「五条」），改成八格后仍需保持不含「五条」；
    `tests/test_agent_prompts.py:196-201`（新档必须同批进 M 的 brief，与 CC-03/CC-09 同族）；
    快照/文档同步点：`DEFAULT_CHECKS` 的计数出现在 `conductor_tools.py:30-31` 的顶部工具表、`conductor.closing` 的 summary/returns、
    `tests/test_release_all.py:2232` 的模块职责行；真机影响（逐格、比原因行）：
    **根 A 的 57 个目录逐目录 `got == 0`、该行 `ok is True`**（原因行 `--`，本来没有坏行）；
    **根 B 的 8 个目录凡把该档写进表的行 `got >= 1` ⇒ `ok is False`**，
    原因行形态 =「产物台账与盘上不一致：`changed` 589 条（例：<最多 8 条明细>）」。
    六格回放集（`p8e`/`p8f`/`p8g`/`p7b`/`p6q`/`p5-review-t17`）**全部 `--`**（那六个工作区没有 artifacts 相关 `kind` 写进表）。
  - **风险与不可逆点：** 一旦进格，「格数」就成为**七格/八格两套口径**（`cli.py` 的逐格打印、工具描述、发布说明三处必须同时改，
    漏一处就是「人与门两套口径」）；且 589 条 `changed` 会在**没有验收表的根 B** 上永远读不到 ——
    进格并不会让根 B 的表出现，只会让**将来**的表一写就红。
  - **兼容闸：** 204 行历史表不受影响（新格是 `DEFAULT_CHECKS` 的格，不是 `kind`）；33 份验收表的逐格读数不受影响
    （除非表里写这一档，今天 0 份写）。
  - **禁改区：** `closing.py` / `conductor_tools.py` 均不在 FC-27 清单（`draft/47` §3-C2 `[我复核]` 的该节结论）。

- **方案 B：只留 `findings` 里的一条（不进格，加读数）**
  - **做法：** 新增 `artifact_ledger_bad_rows` **档**并实现读数，但**不动 `DEFAULT_CHECKS`**；
    是否要在没有表时也报一条 finding，是这一方案的次级分叉（`48-04` §CL-13 只保证「读数可独立」）。
  - **理由：** 不动格数 ⇒ 不牵动工具描述、CLI、发布说明三处；真机影响面最小。
  - **成本：** 文件 **2** 个（`closing.py` + `tests/test_agent_prompts.py` 的镜像同批）；落点 2-3 处；估计 **+40** 行；
    会红的既有测试：`tests/test_agent_prompts.py:196-201`（加档必红，与 CC-03/CC-09 同批处理）；
    `tests/test_conductor_tools.py:101-115` **不红**（按 `DEFAULT_CHECKS` 比，格数未变）；
    真机影响：**0 格**（无表写它；`DEFAULT_CHECKS` 未变 ⇒ 七格读数逐格不变）。
  - **风险与不可逆点：** 「产物登记必须与盘上一致」这条红线**没有门在守**（只有读数）⇒
    读数不参与判据时，589 条 `changed` 只是「看得见」，不是「会被拦」。
  - **兼容闸：** 无需记账（口径未变；`kind` 词表加一档属词表变更，须登记）。
  - **禁改区：** 无（`specs/m.py` 若被镜像则仍是禁改区 ⇒ 人审）。

- **方案 C：不动（不加档、不加格、不加读数）**
  - **做法：** `closing.py` 一字不改。
  - **理由：** 今天的真机后果是 **0 格**（根 B 无表、根 A `changed=0`）⇒ 「没有可判的对象」。
  - **成本：** 文件 **0** 个；落点 **0** 处；估计 **+0 / -0** 行；会红的既有测试：**0 条**；真机影响：**0 格**。
  - **风险与不可逆点：** 根 B 的 589 条 `changed`（18.75%）继续**没有任何收工门读数**；
    交付物台账与盘上不一致这件事，在 `closing` 这一侧永远沉默（PDF 那一维有对照组：`renderanchor.py:306-308`）。
  - **兼容闸：** 无需记账。
  - **禁改区：** 不涉及。

- **不裁的默认后果：** 今天不做 ⇒ 七格不动，`DEFAULT_CHECKS` 仍是 7；
  根 A 的 57 个目录 / 1387 条 `ok` 与根 B 的 8 个目录 / 2599 `ok` + 589 `changed`
  **在收工门上一格都不出现**；`tests/test_release_all.py:2232` 的「五条」继续是陈旧陈述（今天已七格，改与不改都不红）。

- **取舍点：** 分歧在「一根 0 份验收表的根（根 B）的 589 条 `changed`，值不值得用 `DEFAULT_CHECKS 7→8` 的
  三处描述同步 + 一条既有断言改写的成本，去换一个**今天不会翻任何格**的第八格」。

---

### 决策 5（CC-03 / CC-09）— 一个词表装两代 30 档：分组形态怎么定

- **现状与证据：**
  - `LEG_CHECK_KINDS` **30 档**（`closing.py:80-244`），段界注释只有两处：`:162`（研究类）与 `:210`（数学对象进度）`[本次确认]`。
  - **`kind` 是 204 行历史表的字面契约**（`46-04` §6.4 第 2 条逐字：30 档的**名字**不能删、不能改名）——
    「按类型分两张表」会让一半历史行变成词表外 ⇒ `:1246-1253` 判**整表 unknown**（比 CC-05 更重的不可逆面）；
    `46-04` §6.5 逐字判「**高风险，不建议**」。
  - **按行号分段分不出评审向/研究向**：`draft/45` 的 `:81-161` / `:163-209` / `:211-243` 是第一段行号切分，
    而 **5 个研究档住在第一段区间里**（`draft/44` J-23 逐字；`46-04` §2.7 ③ 列出了它们：
    `retrieval_ok_rows:111` / `document_rows:119` / `document_body_rows:126` / `document_claim_rows:133` / `claim_evidence_fit_rows:139`）。
  - **正确分法是「按在什么工作区算得出数」**（`46-04` §2.7 ③ / J-23）：
    `KIND_REQUIRES_BASELINE = ("manuscript_edited", "citation_records_vs_bibitems")`；
    研究型专用 16 档；两代共用 8 档（`research_question_rows` / `retrieval_attempts` / `numeric_experiment_rows` /
    `reviewed_documents` / `proof_experiment_rows` / `quote_verified_rows` / `report_files` / `attack_plan_rows`）—— 全部标 `[子代理]`。
  - **`CC-09` 的提示词逐字清单只有 29 档（缺 `c_analysis_runs`）——本文件独立复核，`[我复核]`**：
    `agent_prompts.py:1095-1106` 的「受控档位逐字列在这里」段里，反引号包起来的档名去重后是 **29** 个；
    与 `set(LEG_CHECK_KINDS)` 的差集**恰好是 `{'c_analysis_runs'}`**（本文件用正则从该段抽名后求差）。
    而 `tests/test_agent_prompts.py:200` 的判据是**子串包含**（`k not in text`）⇒ 它**今天靠散文过**：
    `c_analysis_runs` 出现在 M 的 policy 散文里（`agent_prompts.py` 的「第五环」那一段，逐字
    「验收表里加一行 `c_analysis_runs`」）⇒ 判据绿，清单却漏。
    `specs/m.py:69-79` 的平铺清单里**逐字点了 `c_analysis_runs`**（该文件是禁改区）。
  - 相关既有反判据（本文件逐字读过）：`tests/test_agent_prompts.py:196-201`（`:200` 的 `missing` 列表）；
    处置照 `46-04` §6.1：改成「逐字清单解析出的集合 == `set(LEG_CHECK_KINDS)`（集合相等）」。

- **方案 A：按「在什么工作区算得出数」分组标注（`LEG_CHECK_GROUPS` + `LEG_CHECK_HINTS`）**
  - **做法：** 30 档取值**一字不改**；新增 `LEG_CHECK_GROUPS: dict[str, tuple[str, ...]]`（`review_only` / `research_only` / `shared`）
    与 `LEG_CHECK_HINTS`，并让 `research_chain_gaps` 对「研究型工作区拿到 review-only 档」给**读数级警告**；
    镜像三处补 `c_analysis_runs`，并把 `tests/test_agent_prompts.py:200` 的「子串包含」改成「清单 == 词表」。
  - **理由：** 这是 `46-04` §2.7 与 `draft/44` J-23 给出的**唯一**正确分法（按可读性，不按行号/工作区类型）。
  - **成本：** 文件 **3** 个（`closing.py`、`agent_prompts.py`、`specs/m.py`（禁改区））+ 1 个测试文件；
    落点 **4** 处（`:80-244` 的分组表 + `research_chain_gaps` 的警告 + 两处镜像）；估计 **+40 / -5** 行；
    会红的既有测试：`tests/test_agent_prompts.py:200`（改成集合相等后，漏 `c_analysis_runs` 的清单**必红** ⇒
    必须同批把那 1 档补进两处镜像）；`tests/test_conductor_tools.py:101-115` **不红**（按 `DEFAULT_CHECKS` 比）；
    快照/文档同步点：`agent_prompts.py:1095-1106` 的逐字清单 29 → **30 档**；`specs/m.py:75` 同（**禁改区，人审**）；
    真机影响：**33 份逐格 0 处原因行变化**——分组标注**不参与 `_check_acceptance` 的判据**
    （30 档取值不变 ⇒ `:1246-1253` 的整表 unknown 风险为零；覆盖面 `:342-349` 只看 `used`/`na_used`，不看分组）。
    新警告的真机命中面**今天未采录**（`46-04` §2.7 只给了「哪些档在哪些工作区出现过」的统计）⇒ 列为未核实项。
  - **风险与不可逆点：** 分组表与词表**脱节**的风险（分组键漏一档或改名）⇒ 必须配一条「`LEG_CHECK_GROUPS` 的键集合 == `set(LEG_CHECK_KINDS)`」的元判据
    （本文件已把该形态记下，标 `[判断类]`，因为 `46-04` §6.2 没给 CC-03 的负控）。
  - **兼容闸：** 30 档取值不变 ⇒ **204 行历史表的字面契约完整**；33 份表的逐格读数不变。
  - **禁改区：** `specs/m.py` **是 FC-27 禁改区**（`[category: auth-audit]`）⇒ 镜像那一处**必须人审**
    （`AGENTS.md`：命中禁改区「由人编写，或人逐行走查」+ **2 名 reviewer 批准**）；
    `closing.py` / `agent_prompts.py` 不在清单。

- **方案 B：按类型分两张表（已判高风险，不得开工）**
  - **做法：** 把 30 档拆成「评审向」与「研究向」两张受控表，各自独立的 `kind` 词表。
  - **理由：** 表面上是「两代不要混在一个词表里」最直白的实现。
  - **成本：** 文件 **≥2** 个 + 全部历史表；落点不可枚举（每个解析点都要分表）；估计 **+100** 行以上；
    会红的既有测试：`tests/test_closing_gate.py` 里所有写 `kind` 的用例族（55 个 `def test_`，`46-04` §4.2）；
    真机影响：**分区后一半历史行成为词表外 ⇒ `:1246-1253` 判整表 unknown** ⇒
    33 份表里凡写另一侧档的表从 `fail` 变成 `unknown`（读数从「红得精确」退化为「没查成」）。
  - **风险与不可逆点：** `46-04` §6.4 第 2 条点名的**磁盘契约**：历史表按 `kind` 字面引用；分区即毁掉可比性。
  - **兼容闸：** **不可兼容**（204 行历史行的词表外问题）。
  - **禁改区：** 同方案 A（镜像），且 `kind` 名字本身不许删/改名。
  - **说明：** 本文件按 `46-04` §6.5 与 `draft/44` J-23 的判定，**不把它写成可做**。

- **方案 C：不动（只加读数、不加分组）**
  - **做法：** 不新增 `LEG_CHECK_GROUPS`，只在 `research_chain_gaps` 的读数里加「哪些档用过 / 在哪些工作区可读」的现成统计（不落词表）。
  - **理由：** 零结构变更；不动 `tests/test_agent_prompts.py:200` 的判据。
  - **成本：** 文件 **1** 个（`closing.py`）；落点 1-2 处；估计 **+15** 行；会红的既有测试：**0 条**；
    真机影响：**0 格**（读数不参与判据）。
  - **风险与不可逆点：** 提示词逐字清单仍然**只有 29 档**（缺 `c_analysis_runs`），而 `tests/test_agent_prompts.py:200`
    继续靠**子串包含**过 —— 「清单 == 词表」这件事继续**没有判据守着**。
  - **兼容闸：** 无变更。
  - **禁改区：** 不涉及。

- **不裁的默认后果：** 今天不做 ⇒ 段界注释仍是两处行号注释（`:162` / `:210`），
  「哪一档该在哪种工作区用」只能靠提示词的散文（`agent_prompts.py:1107-1110` 那段）；
  提示词**逐字清单 29 档 ≠ 代码 30 档**这个差异继续存在，而 `tests/test_agent_prompts.py:200` 不红。

- **取舍点：** 分歧在「分组标注要不要落成**代码里的结构化表**（要付 `specs/m.py` 禁改区的人审 + 改一条既有断言），
  还是只把统计塞进读数（不碰禁改区，但清单 ≠ 词表的问题继续无判据）」。

---

### 决策 6 — `reading_version` 要不要落：口径变更的可追溯性放在代码里还是文档里

- **现状与证据：**
  - `readings["acceptance"]` 今天的键是 **`checks_file` / `rows` / `research_chain`**（本文件 §0.3 第 7 行、`[我复核]`）
    ⇒ **没有版本号**；`check_closing` 的其它格读数同样没有全局版本键。
  - 「历史验收表的可比性」被列为**不可逆点第 1 条**（`46-04` §6.4 第 1 条逐字）：
    「33 份表 / 204 行今天读出的 `got` 是**旧口径下的数**。S-05 的三档、E-05 的分母换基线、CC-05 的第四态
    都会改变『同一份表、同一个工作区、不同趟次读出的数』。按 `draft/45:12`：**每改一次口径必须在 `draft/44` 那一行
    写下『从哪一趟起口径变了』**。建议同批在 `readings["acceptance"]` 里落一个 `"reading_version"`（今天没有），
    并以 `p8g`（唯一覆盖面 8/8 齐的工作区）作口径锚点。」
  - 本文件现算：`p8g` 改前 `research_chain.missing == []`、覆盖面 8/8 齐（`[我复核]`）⇒ 锚点今天成立。

- **方案 A：在 `readings["acceptance"]` 里加版本号（今天没有）**
  - **做法：** `:1290` 的 `rep.readings["acceptance"] = {...}` 增一个键（例如 `"reading_version": <常量>`），
    常量落在 `closing.py` 顶层（与 `ACCEPTANCE_CHECKS_NAME:76` 同族）；`46-04` §6.4 第 1 条同时要求在 `draft/44` 记一行。
  - **理由：** 让「这一趟读数是在哪一版口径下算的」**随读数一起落盘**，而不是只写在文档里。
  - **成本：** 文件 **1** 个代码 + **1** 个文档（`draft/44` 的口径变更行）；落点 **2** 处（`:1290` + 顶层常量）；
    估计 **+6 / -0** 行；会红的既有测试：**预期 0 条**——
    `tests/test_closing_gate.py:793-804` 只比 `status`（`:803-804` 的 dict 比较只看状态词），不读 `readings` 的键；
    但**若**有测试断言 `readings["acceptance"]` 的**键集合**，就会红（本文件只逐条读了 `:793-804`，
    未穷举 `tests/` 里对该键集合的断言 ⇒ 施工前必须跑一遍全量确认）；
    快照/文档同步点：`conductor.closing` 的 `returns`（`conductor_tools.py:952-957`）按 `readings` **整包透传**，不需要改；
    真机影响：**0 格**（`status` 与 `findings.detail` 都不变）。
  - **风险与不可逆点：** 版本号一旦落盘就成了**读数格式的一部分**；此后每次口径变更都要递增，
    否则「有版本号但没变」比「没有版本号」更容易误导（`draft/47` 的三态纪律：把「没标」与「标了同一版」折平是同一类病）。
  - **兼容闸：** 不改 `kind` 契约、不改 204 行的 `min` 轴 ⇒ 历史行仍可比；版本号本身**不参与任何判据**。
  - **禁改区：** 无（`closing.py` 不在清单）。

- **方案 B：只写在 `draft/44` 的口径变更行（不进读数）**
  - **做法：** 按 `draft/45:12` 的要求逐次登记「从哪一趟起口径变了」，代码一字不改。
  - **理由：** 这是 `draft/45:12` 的**原始要求**；版本号只是 `46-04` 的「建议」。
  - **成本：** 文件 **1** 个（文档）；落点 **1** 处（`draft/44` 对应行）；估计 **+2 / -0** 行（文档）；
    会红的既有测试：**0 条**；真机影响：**0 格**。
  - **风险与不可逆点：** 「口径」与「读数」**分处两地**：读一份历史 JSON 读数时，
    无法从读数本身知道它是哪一版口径算的（只能靠人记得去查 `draft/44` 的那一行）。
  - **兼容闸：** 无代码面变更。
  - **禁改区：** 不涉及。

- **方案 C：不动（既不落版本号，也不新增口径变更行）**
  - **做法：** 一字不改。
  - **理由：** 今天三条收紧在真机上**0 处翻转**（E-05 / E-08 的实测判定）⇒ 「同一份表、同一工作区」的 `got` 今天确实没变，
    `draft/44` 的既有记录已够。
  - **成本：** 文件 **0** 个；落点 **0** 处；估计 **+0 / -0** 行；会红的既有测试：**0 条**；真机影响：**0 格**。
  - **风险与不可逆点：** 一旦后续任一条（S-05 新档进覆盖面 / E-05 分母 / CC-05 第四态）落地并改变读数，
    就从「0 处翻转」变成「有处翻转」，而**那一天**才补记，历史读数与口径的对应关系已经断开一次。
  - **兼容闸：** 无。
  - **禁改区：** 不涉及。

- **不裁的默认后果：** 今天不做 ⇒ `readings["acceptance"]` 保持三键；
  33 份表 / 204 行的 `got` 继续是「旧口径下的数」而**读数本身不声明自己是哪一版**；
  口径锚点 `p8g` 继续只以「`missing == []`」的形式存在，没有任何版本标记。

- **取舍点：** 分歧在「口径变更的**可追溯性**要落在**读数里**（格式多一个键、以后每次都要递增）
  还是落在**文档里**（原始要求，但读一份历史 JSON 时看不出口径）」。

---

### 决策 7（E-06 两半）— 附件三件套判实 / 九节节体非空判实：先做哪半、要不要同批

- **现状与证据：**
  - 附件三件套今天**算了不判**：`closing.py:1923` `has_attach = [f for f in ATTACHMENT_FIELDS if f in text]`
    只进读数 `:1927`，不进 `:1929-1934` 的 `problems` `[本次确认]`；
    `grep has_attach` 全仓只命中 `:1923` / `:1927`（`48-04` §CL-04 `[子代理]`，本文件逐字确认了这两行）。
  - 九节今天只判「节名或序号出现在正文任意位置」：`:1920-1921` `if f"{num}、" not in text and name not in text` `[本次确认]`。
  - **两根真机读数（本文件独立复算，`[我复核]`，报告总数 46）**：
    **附件三件套判实 ⇒ 红 9 份**：`p5-run6`（缺 `origin=own_result`）、`p6-research-from-zero` / `p6e` / `p6k` / `p6o` / `p8f`
    （缺 `origin=own_result` + `依据`）、`p6n` / `p6q`（缺 `origin=own_result` + `sha`）、`p7-open-questions`（缺 `origin=own_result`）；
    **九节判实 ⇒ 只红 1 份**：`p5-run6`（本文件在「按节名」口径下读到缺 **七/八/九** 三节；
    `46-04` §2.3 说它是 5 节、缺六/七/八/九 —— 两口径都不影响「只有这一份」这个结论，但**缺哪几节的逐字清单两处不一致**，须施工时采录）。
    ⇒ 收益不对称：**9 : 1**（`draft/44` J-19）。
  - **硬约束：附件问题必须并入同一个 `report_incomplete` code**（J-19 逐字）；
    既有反判据 `tests/test_closing_gate.py:793`（`:799` `assert [f.code for f in rep.blockers] == ["report_incomplete"]`）
    —— 本文件逐字读过：`:796` 的夹具 `_write_report(tmp_path, drop_section="七", drop_split=True)`、
    `:801` `any("我们做的补救" in m for m in rd["missing_sections"])`、`:803-804` 断言其余六格全 `pass` `[本次确认]`。
    ⇒ **新开第二个 code 会让 `:799` 当场红**。
  - 门只有七格，`report_shape` 是其中一格（`:49`）⇒ 附件、九节、分栏标记共用这一格的状态。

- **方案 A：先做附件三件套（收益 9 份）**
  - **做法：** `:1923` 改成 `missing_attach = [f for f in ATTACHMENT_FIELDS if f not in text]`，
    `:1929-1934` 里加 `if missing_attach: problems.append(...)`；读数新增 `missing_attachment_fields`（保留 `attachment_fields` 作兼容读数）；
    **不新增 finding code**（并入 `:1936-1940` 的 `report_incomplete`）。
  - **理由：** 收益 9 份、改动面收敛在两行（`grep has_attach` 只命中 `:1923/:1927`）、且三件套是既有报告的字面契约。
  - **成本：** 文件 **1** 个（`closing.py`）；落点 **3** 处（`:1923` 的算法 + `:1929-1934` 的 `problems` + `:1924-1927` 的读数键）；
    估计 **+15 / -4** 行；会红的既有测试：`tests/test_closing_gate.py:793` —— **并入同一 code 即不红**（`:799` 仍只含 `report_incomplete`）；
    但 `:803-804` 断言其余六格全 `pass` ⇒ 新读数键**不许影响状态面**；
    快照/文档同步点：`readings["report_shape"]` 新增 `missing_attachment_fields`；
    真机影响（逐格、比 `report_shape` 的原因行）：`p8e` / `p8g` / `p7b` / `p5-review-t17`：`pass → pass`（原因行 `--`，三件套齐）；
    **`p8f`：`pass → fail`**，原因行从**空**变成「缺 `origin=own_result`、`依据`」；
    **`p6q`：`pass → fail`**，原因行从**空**变成「缺 `origin=own_result`、`sha`」；
    另 7 份（`p5-run6` / `p6-research-from-zero` / `p6e` / `p6k` / `p6o` / `p6n` / `p7-open-questions`）从 `pass → fail`。
  - **风险与不可逆点：** 9 份真机报告从「看起来通过」变成「红」——
    这正是「算了不判 = 假读数」的修正，但会改变 46 份的 `report_shape` 分布（`pass` 从 46 降到 37）。
  - **兼容闸：** `ATTACHMENT_FIELDS`（`:1428`）的三个字符串**不许改**（既有报告的字面契约）；
    33 份验收表不受影响（这是第七格另一格，不是验收行）。
  - **禁改区：** 无（`closing.py` 不在清单）。

- **方案 B：先做九节节体非空（收益 1 份）**
  - **做法：** 把 `_SECTION_RE` 从 `reviewaccept.py:54` **搬**来（`^#{2,3}\s*([一二三四五六七八九])、(.+)$`，`re.M`），
    逐节取「标题→下一标题」之间的文本，要求 `strip()` 非空；读数新增 `empty_sections` / `section_bodies`；
    **同时修掉 `reviewaccept.py:117` 的起点偏移 bug**（`:117` `start = text.find(f"{num}、")` 没有起点偏移）`[本次确认]`。
  - **理由：** 把「节名出现在前言里就算齐」这个假读数修掉；顺带修掉 `reviewaccept` 侧的同一类 bug。
  - **成本：** 文件 **2** 个（`closing.py` + `reviewaccept.py`（若本方案就顺手修 `:117`））；落点 **3-4** 处；
    估计 **+45 / -12** 行；会红的既有测试：`tests/test_closing_gate.py:793`（`:799` 的同一 code 约束；
    新判据下「缺七节」仍应是 `missing_sections` 非空 ⇒ `:801` 的 `any("我们做的补救" in m ...)` 需确认仍成立）；
    `tests/test_review_acceptance.py:65-66,238`（从 `closing.REPORT_SECTIONS` 取九节）—— 本方案**不动**该模块时**不红**；
    快照/文档同步点：`REPORT_SECTIONS`（`:1415-1425`）的**九节字符串不改**；
    真机影响（逐格、比原因行）：**本方案预期只翻 1 份** —— `p5-run6`（改前原因行为空、改后 = 「缺 N 节（…）」形态，
    具体格式由 `:1931` 的 `f"缺 {len(missing)} 节（{'、'.join(missing[:4])}）"` 决定）；
    六格回放集 **全部 `--`**（`p8e`/`p8f`/`p8g`/`p7b`/`p6q`/`p5-review-t17` 的九节本来就合格，
    且它们的附件问题在**本方案**里不判 ⇒ `p8f`/`p6q` 保持 `pass`）。
  - **风险与不可逆点：** 只做九节 = 只翻 1 份；**「算了不判」的 9 份继续假绿**（`has_attach` 仍在 `:1923` 只进读数）。
  - **兼容闸：** 九节字符串不改；`rep.readings["report_shape"]` 的既有键（`path` / `chars` / `missing_sections` /
    `missing_split_markers`）**不许改名**（`:1924-1927` 已被测试读）。
  - **禁改区：** `reviewaccept.py` **不在 FC-27 清单**（`draft/47` §3-C2）⇒ 可普通改动走。

- **方案 C：两半同批（一次把 `report_shape` 做实）**
  - **做法：** 方案 A + 方案 B 一起改 `_check_report_shape`，**两半的问题都并入同一个 `report_incomplete` code**。
  - **理由：** 一次把「算了不判」与「按节名就算齐」两类假读数同时修掉；`report_shape` 这一格只动一次。
  - **成本：** 文件 **1-2** 个（`closing.py`（+ 若修 `:117` 则 `reviewaccept.py`））；落点 **6-7** 处；估计 **+60 / -16** 行；
    会红的既有测试：`tests/test_closing_gate.py:793`（`:799` 的**单 code 约束**必须同时被两半满足；
    `:801` 的 `missing_sections` 断言在新判据下需确认）、`:803-804`（其余六格全 `pass`）；
    快照/文档同步点：`:1924-1927` 新增 `missing_attachment_fields` / `empty_sections` / `section_bodies` 三键（**不许改既有键名**）；
    真机影响（逐格、比 `report_shape` 的原因行）：**9 份附件红 + 1 份九节红，去重后 9 份**
    （`p5-run6` 两半都红 ⇒ 同一格、同一 code，原因行里两段拼接）；
    六格回放集：`p8f` / `p6q`：`pass → fail`（附件原因行），`p8e`/`p8g`/`p7b`/`p5-review-t17`：`--`。
  - **风险与不可逆点：** 一次改两半 ⇒ 出错时「哪一半让哪一条测试红」不可二分；
    `46-04` §6.2 给的是**两条独立负控**（`test_the_attachment_triple_is_judged_not_just_read` /
    `test_an_empty_section_body_is_not_a_section`）⇒ 同批上线时两条负控必须都在「改前必红」状态下先跑过。
  - **兼容闸：** 同 A + B；且 `report_incomplete` 的 **code 数量必须保持 1**。
  - **禁改区：** 同 A + B。

- **不裁的默认后果：** 今天不做 ⇒ `:1923` 的 `has_attach` 继续只进读数：
  **9 份真机报告（含回放集里的 `p8f`、`p6q`）的 `report_shape` 继续保持 `pass`**（假绿）；
  九节继续按「节名出现在正文任意位置」判 ⇒ `p5-run6` 的 `report_shape` 继续 `pass`。
  ⇒ 46 份里 9 份的「附件三件套」这一条判据**继续没有裁判**。

- **取舍点：** 分歧在「先用 1 份的改动量换来 9 份的判据做实（附件半），
  还是先换 1 份（九节半），还是承受『一次动两半 ⇒ 反判据不可二分』的代价一次做完」。

---

### 决策 8（F-06）— 验收表由台账生成：生成 / 手写 / 只做校验器

- **现状与证据：**
  - 今天「表不在」的分支是**直接判**：`closing.py:1160` `if not path.is_file():` → `:1164-1171` 读覆盖面 →
    `:1174-1182` 研究型 ⇒ `fail` + `acceptance_missing_for_research`（blocker）→ `:1183-1186` 非研究型 ⇒ `pass` `[本次确认]`。
  - **真机读数**：33/33 份真机工作区**都有**验收表（本文件 §0.2 `[我复核]`）⇒ F-06 在盘上 **0 处翻转**（它改的是「没有表」那条路）。
    而「没有表」那条路的真机样本**存在**：`43-C` C-16 ③ 记「26 个工作区有 `research_questions` 行，其中 **4 个没有**
    `ACCEPTANCE-CHECKS.json`（`p6f` / `p6h` / `p6j` / `p6l`）⇒ `acceptance_missing_for_research`」（`48-04` §CL-10 `[子代理]`，本文件未复算这 4 个工作区）。
  - **同批关系（硬约束）**：`draft/44` J-21 逐字「F-06 必须与 **P-03 退场** + `tests/test_agent_prompts.py:808` 同批」。
    `tests/test_agent_prompts.py:808-825` 的判据（本文件逐字读过，`[本次确认]`）：
    `:818` `name = CL.ACCEPTANCE_CHECKS_NAME.split("/")[-1]`、`:821` `assert name in text`（M 的 brief 里必须点名该文件名）、
    `:823-825` 反面断言（该文件名**只许**出现在 M 的 brief 里）—— **P-03 退场后必红**（M 的 brief 不再教人写表）。
  - **「两套真相」的风险（用户点名的约束）**：手写表与生成表**并存**时，
    同一份工作区会有两份「验收口径」：一份是 `out/paper/ACCEPTANCE-CHECKS.json`（人/模型写的），
    一份是 `generate_acceptance_rows` 现算的。门必须只用一份（今天只用文件那份），
    否则「门判的」与「人写的」不是同一组行 —— 这正是 `43-C` C-04 记的「验收表里写的与门实际判的不是同一组行」。
  - 生成器的接口面（`48-04` §CL-10 `[子代理]`）：对 `LEG_CHECK_KINDS` 逐档调 `_leg_reading`，
    产出 `{"id","name","kind","min","max","generated_by":"framework"}`；`min` 取该档 `implicit_min`（没有则 1），`max` 取 `implicit_max`；
    **`na` 不由生成器写**（那是人或模型的知识）；老表缺 `generated_by` **不报错**。

- **方案 A：由台账生成（新增纯函数 + 改「表不在」分支）**
  - **做法：** 新增 `generate_acceptance_rows(store, project_root) -> list[dict]`；
    `:1160-1186` 改成「先生成、再走同一套 `:1203-1392` 判定」；读数新增 `generated: true` 与 `table_source: "file" | "generated"`；
    **生成不出可判行时仍然红**（保留 `acceptance_missing_for_research` 语义）。
  - **理由：** 「教人写表」这条路正是 `draft/37` §137 那个洞（没写表与写了全过在门上长得一样）；
    生成让门自己产生口径。
  - **成本：** 文件 **4** 个（`closing.py` + `tests/test_closing_gate.py` + `tests/test_agent_prompts.py` +
    `P-03` 的退场面）；落点 **4** 处（`:1160-1186` / 新函数 / `:1187-1196` 的解析面 / `:1246-1253` 的整表 unknown 面）；
    估计 **+80** 行；会红的既有测试：
    `tests/test_closing_gate.py:948`（`:959` `acceptance == "fail"`、`:960-961` `"acceptance_missing_for_research" in codes`、
    `:963` `len(chain["missing"]) == 8`）⇒ **必红**（要改成「生成的行必须逐行判、读数有 `generated: true`」）；
    `tests/test_agent_prompts.py:808-825`（`:821`）⇒ **P-03 退场后必红**；
    `tests/test_closing_gate.py:966` / `:989` / `:1011`（覆盖面三条）—— 同族，作为回归跑一次确认（`46-04` §4.2 只点名 `:948`）；
    快照/文档同步点：生成器用的文件名常量**必须复用** `ACCEPTANCE_CHECKS_NAME`（`:76`），
    否则 `tests/test_agent_prompts.py:808-825` 的「同源」判据无落点；读数新增 `generated` / `table_source`；
    真机影响：**33 份逐格 0 处**（33/33 都有表 ⇒ 走不到那条分支）；六格回放集 `--`；
    真机样本面 = `p6f` / `p6h` / `p6j` / `p6l` 四个「有 `research_questions` 行但没有表」的工作区
    （`43-C` 读数），上线后应专门跑这 4 个，比「`acceptance_missing_for_research` 是否仍在、是否多了逐行读数」。
  - **风险与不可逆点：** **两套真相**：生成器一上，手写表与生成表**并存**会产生两份口径；
    必须明确「门只认其中一份」（今天的实现是「文件在 ⇒ 用文件」⇒ 生成器只在**没有文件**时说话），
    但这一条一旦被写进读数（`table_source`），就需要在文档与提示词里同时说清，
    否则写表的人会继续按旧口径写、门按新口径算。
  - **兼容闸：** 204 行历史表**逐字可比**（老表缺 `generated_by` 不报错）；33 份表逐格不变；
    生成器的 `min` 取 `implicit_min` ⇒ 与 E-05 的「取大」方向一致（但**不是同一件事**，见决策 2）。
  - **禁改区：** `closing.py` 不在清单；**P-03 的退场面**与 `agent_prompts.py` 不在清单（`draft/47` §3-C2）。

- **方案 B：保持手写（只在「表不在」那条路上保持现状）**
  - **做法：** `:1160-1186` 一字不改；不新增生成器。
  - **理由：** 验收表是**人的知识**（哪些行成立、哪一行该 `na` + 理由），生成器写不出 `na`（`48-04` §CL-10 逐字）；
    手写表也是「门与提示词同源」这条判据（`tests/test_agent_prompts.py:808-825`）能成立的前提。
  - **成本：** 文件 **0** 个；落点 **0** 处；估计 **+0 / -0** 行；会红的既有测试：**0 条**；真机影响：**0 格**。
  - **风险与不可逆点：** `draft/37` §137 那个洞留着：研究型项目**没写表**时，门给的是
    「`fail` + `acceptance_missing_for_research`」——这条今天是对的判据，但它**只报缺表、不报缺哪几行**；
    4 个真机样本（`p6f` / `p6h` / `p6j` / `p6l`）继续停在「缺表」这一级。
  - **兼容闸：** 无变更（`tests/test_agent_prompts.py:808-825` 继续绿，P-03 不退场）。
  - **禁改区：** 不涉及。

- **方案 C：只做校验器（生成器只产出读数、不改判定路径）**
  - **做法：** 实现 `generate_acceptance_rows`，但**只**把它作为读数写进 `readings["acceptance"]`
    （例如 `generated_preview`）与/或作为「表里的行 vs 台账现算的行」的**一致性读数**；
    `:1160-1186` 的判定路径**一字不改**。
  - **理由：** 拿到「门自己会怎么判」的对照，而不产生第二套真相、不动任何判据；也不牵动 P-03。
  - **成本：** 文件 **2-3** 个（`closing.py` + `tests/test_agent_prompts.py`（若新档/新镜像同批）+ 测试）；
    落点 **2-3** 处；估计 **+60** 行；会红的既有测试：**预期 0 条**
    （`:948` 的判定路径不变 ⇒ `:959-963` 全不变；`tests/test_agent_prompts.py:808-825` 不牵动）；
    真机影响：**0 格**（读数不参与判据）；但对**没有表的 4 个工作区**（`p6f` / `p6h` / `p6j` / `p6l`）
    可以立刻得到「如果生成会得到哪几行」的对照读数。
  - **风险与不可逆点：** 校验器与判定路径**并存**时，两者会漂移（同一份台账两个答案）——
    必须有元判据守着（例如「表在时，表里的行 ⊆ 台账能生成的行」），否则又多一处「同一件事两套结论」（CC-06 那一类病）。
  - **兼容闸：** 无判据变更 ⇒ 204 行历史表与 33 份表逐格不变。
  - **禁改区：** 无。

- **不裁的默认后果：** 今天不做 ⇒ `:1160-1186` 继续「没有表 ⇒ 研究型直接红」；
  33 份表所在的 33 个工作区一格不动；`p6f` / `p6h` / `p6j` / `p6l` 这 4 个「有 `research_questions` 行但没有表」的工作区
  继续只拿到 `acceptance_missing_for_research`（缺表这一级），拿不到「缺哪几行」的读数；
  `tests/test_agent_prompts.py:808-825` 继续把门与提示词钉在一起（P-03 不退场则它继续绿）。

- **取舍点：** 分歧在「验收表是**人的知识**（哪些行成立、哪一行该 `na`）还是**可从台账现算的东西**」——
  生成器能给出后者的全量，但拿不到前者的 `na`；而「生成器一上、手写表与生成表并存会产生两套真相」这件事，
  决定了它是进**判定路径**（方案 A，要同批处理 P-03 与 `:821`）还是只进**读数**（方案 C）。

---

## 2. 决策点索引与相互依赖（供排批用，不含裁定）

| 编号 | 条目 | 一句话要决定什么 | 与其它决策点的硬耦合 |
|---|---|---|---|
| 1 | E-04b | 覆盖面 `marked` 收不收紧 | 不许与 E-04a 同批（`draft/44` J-17）；连坐 4 行合法 `na` |
| 2 | E-05 | `min` 取大 / 分母换基线 / 去空白 | 分母半**必须与 CC-05 同批**（`46-04` §5.1）；`specs/m.py` 禁改区 |
| 3 | S-05 | 三条腿各自做/不做 | 腿 1 与 CC-03/CC-09 同批（`tests/test_agent_prompts.py:200`）；腿 2 等 F-01/EE-12；腿 3-C1 要动禁改区 `schema.py` |
| 4 | EE-05 | 完整性读数进不进第八格 | 进格 ⇒ `DEFAULT_CHECKS 7→8` ⇒ 工具描述 + 发布说明 + 既有断言三处同步 |
| 5 | CC-03/CC-09 | 分组形态 | CC-03 必须与 CC-09 同批（J-21）；`specs/m.py` 禁改区 |
| 6 | 版本号 | 口径变更落在读数还是文档 | 与决策 2 / 3 / 4 的口径变更同批记账才对得上 |
| 7 | E-06 两半 | 附件半 / 九节半 / 同批 | 两半的问题**必须并入同一个 `report_incomplete` code**（J-19） |
| 8 | F-06 | 生成 / 手写 / 只校验 | **必须与 P-03 退场 + `tests/test_agent_prompts.py:808` 同批**（J-21） |

---

## 3. 本文件的边界

1. **不裁定。** 全文只给「现状与证据 / 方案 / 成本 / 不裁的默认后果 / 取舍点」，
   §1 与 §2 里没有一句「建议选 X」；方案之间的排序不代表偏好。
2. **不写代码、不改工作区。** 只写 `draft/49-决策对照-03-closing门.md` 这一个文件；
   未改 `agentflow/src/`、未改工作区、未跑 pytest / 模型 / 网络。
3. **未复算项（照 `draft/47` §4 的纪律，不许折成「没问题」）：**
   - 30 档 × 33 工作区的**可读性矩阵（990 次实跑）**——本文件只复算了「哪些档产出 `implicit_min`」（8 行），**未复算抛错次数**。
   - `manuscript_edited` 9 次 `got=1` 的**字节差**与「去空白后仍全不同」——引 `46-04` §2.2，`[子代理]`。
   - `citation_records_vs_bibitems` 6 次使用中「主稿与基线 `\bibitem` 都是 7」——引 `46-04` §2.2，`[子代理]`。
   - **根 B 的 `experiments` 行数**：`46-04` §2.5 写 **189**，本文件逐目录现算 **85**（4×25 + 26 + 2×29 + 5）⇒ **两口径冲突，不许折平**。
   - `p6f` / `p6h` / `p6j` / `p6l` 四个「没有验收表」的工作区——引 `43-C` C-16 ③，本文件未复算。
   - CC-03 新警告的真机命中面（「研究型工作区里出现 review-only 档」的逐格清单）——`46-04` §2.7 未给。
   - `tests/test_render_anchor*.py` 一族的既有锚回归行号——`46-04` §6.1 只写「E-08 无直接测试」（E-08 不在本簇 8 个决策点内）。
   - 「哪些测试会红」是**静态判读**（读测试源码 + 读实现判据）：本文件逐条读过正文里的断言原文并标了 `[本次确认]`，
     但**没有跑 pytest**；施工时必须先跑一遍留基线（`46-04` §7.2 逐字）。
4. **冲突处理：** 本文件与 `48-04` 冲突处，凡属**测量值**（例如「E-04b 会让几处原因行变」）以本文件的现算为准并已注明差异；
   凡属**判断**（可行性、批次、取舍）两者都只是材料，最终以人的裁定为准。
