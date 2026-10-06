# draft/46 施工级调查 04：`src/agentflow/closing.py`

- 仓库：`D:\Incubator\agentflow`；包 `agentflow`；源码 `src/agentflow/`；测试 `tests/`。
- 范围：`closing.py`（盘上 **2087 行**）。覆盖条目 **E-04 / E-05 / E-06 / E-08 / S-05 / F-06 / CC-03 / CC-05 / CC-06 / EE-05 / EE-10**。
- 行号口径：全部按**盘上当前版本**（`git status --short` 只有 `draft/43-*.md` 一处已改与未跟踪的 `out/`、`projects/`；`closing.py` 无未提交改动）。
- 取证：`read` / `grep` / `glob`；`python -B -c` 只读复算（AST 清点、`_leg_reading` 逐档实跑、`check_closing(checks=("acceptance",))` 实跑、`renderanchor.check_package` 实跑、`artifacts.verify_entries` 实跑）。**未跑模型、未跑网络、未跑全量 pytest、未写工作区任何文件**；唯一写入是本报告。
- 真机证据：根 A = `agentflow/projects`（**33** 份 `ACCEPTANCE-CHECKS.json`、32 份 `RENDER-ANCHOR.json`、45 份 `REPORT.md`）；根 B = `D:\Incubator\projects`（**0** 份验收表、8 份 `ARTIFACTS.jsonl`、1 份 `REPORT.md`）。

---

## 1. 现状总览

### 1.1 顶层对象（`closing.py`）

| 名字 file:line | 一句话职责 |
|---|---|
| `DEFAULT_CHECKS` `:49` | 七格 `anchor/contradictions/load_bearing/report_shape/user_pending/substance/acceptance` |
| `SUBSTANCE_TABLES` `:60` / `ACCEPTANCE_CHECKS_NAME` `:76` | 五张表 / `out/paper/ACCEPTANCE-CHECKS.json`（E-08 的耦合入口） |
| `LEG_CHECK_KINDS` `:80-244` | 受控词表 **30 档**；段界注释在 `:162`（研究类）与 `:210`（数学进度） |
| `REVIEWED_DOC_STATUSES` `:252` / `RESEARCH_CHAIN_GROUPS` `:272-319` | `("accepted","revised")` / 研究链 **8 环 20 档** |
| `research_chain_gaps` `:322-364` | 覆盖面 `hit or marked`（`:347`，E-04 的一半） |
| `_numbers_in` `:368` / `_FIT_STOPWORDS` `:376` / `_words_in` `:389` / `citation_fit` `:395-467` | 断言↔引文确定性比对（三态 `fit/mismatch/unjudged`） |
| `_leg_reading` `:470-1126` | 30 段 `if kind == ...` 链（657 行） |
| `_acceptance_unknown` `:1129-1142` | 把"整格没查成"写成 finding + reading（CC-05 落点） |
| `_check_acceptance` `:1145-1401` | 逐行现算 + `na` + 覆盖面 + **四条自动分支** |
| `NO_SESSION` `:1412` | 第三态会话身份 |
| `REPORT_SECTIONS` `:1415-1425` / `ATTACHMENT_FIELDS` `:1428` / `SPLIT_MARKERS` `:1431` | 九节 / 附件三件套 / 分栏标记（E-06） |
| `MUST_T3_CONDITIONS` `:1438` / `MUST_T3_GAP_NOTE` `:1462` | T3 四条与其缺口说明 |
| `Finding` `:1468-1478` / `ClosingReport` `:1482-1525` | `check/code/level/detail` / `status/findings/readings`；`can_close` 在 `:1505`，`summary` 在 `:1520` |
| `resolve_under_workspace` `:1530-1553` / `_reports_subdir_of` `:1556-1576` / `_has_paper_package` `:1579-1599` | 路径解析（无包含性检查，41-F B14）/ 读 `config.yaml` / 论文包实物判据 |
| `_check_anchor` `:1602-1668` | 锚那一格（`RA.check_package`） |
| `pollution_set` `:1671-1699` / `_check_contradictions` `:1702-1816` | `derived_from` 传递闭包 / 五因 + 污染面 |
| `_has_t3` `:1819-1823` / `_check_load_bearing` `:1826-1899` | T3 形态 / 承重结论 |
| `_check_report_shape` `:1902-1942` | 九节 + 分栏（E-06） |
| `_check_substance` `:1945-1993` / `_check_user_pending` `:1996-2039` | 五张表 / 待答问题 |
| `check_closing` `:2044-2078` / `tri_state_exit_code` `:2081-2087` | 入口 / 0·1·2 |

### 1.2 `_leg_reading` 30 个分支的起始行（`closing.py`）

`quote_verified_rows` 476 · `proof_experiment_rows` 487 · `reviewed_documents` 492 · `reviewed_current_rows` 499 · `manuscript_edited` 549 · `citation_records_vs_bibitems` 569 · `manuscript_rows` 597 · `retrieval_ok_rows` 645 · `document_body_rows` 666 · `claim_evidence_fit_rows` 693 · `document_claim_rows` 706 · `document_rows` 722 · `unfinished_request_rows` 753 · `retrieval_attempts` 801 · `research_question_rows` 818 · `analysis_report_rows` 823 · `c_analysis_runs` 828 · `attack_plan_rows` 846 · `report_files` 851 · `reviewed_proof_rows` 885 · `numeric_experiment_rows` 915 · `document_literature_citations` 918 · `claims_supported_by_their_evidence` 950 · `supported_claims` 994 · `conjecture_rows` 1026 · `statement_rows` 1038 · `plan_progress_rows` 1049 · `counterexample_or_proof_rows` 1060 · `search_frontier_rows` 1072 · `enumeration_optimization_rows` 1079。词表外档位的 `raise ValueError` 在 `:1126`。

### 1.3 四条自动报告分支（`_check_acceptance` 内）

| 分支 | 触发条件 | 行 |
|---|---|---|
| `reviewed_current_rows`（改完没复核） | `if "reviewed_current_rows" not in {kind of out}` | `1319-1337` |
| `document_body_rows`（骨架稿） | 同上形态 | `1340-1356` |
| `claim_evidence_fit_rows`（引文对不上） | 同上 | `1360-1374` |
| `manuscript_rows`（账本被模板灌满） | 同上 | `1378-1392` |

四条的前提都是"**这一档没写进表里**"，而 `out` 里**包含 `na` 行**（`:1243`）⇒ **一行 `na` 即可关掉对应分支**。E-04 的机理就在这四处 + `:1233-1245` + `:347`。

### 1.4 `_check_acceptance` 关键行

`1152-1158` 没给 `project_dir` ⇒ unknown · `1160-1186` 表不在 ⇒ 研究型 fail / 非研究型 pass · `1187-1196` 顶层数组或 `{"checks":[…]}` · **`:1213` `want_min = int(row.get("min") or 0)`（0 = 没给）** · `1222-1224` `want_max` · **`1233-1245` `na` 分支（只校验 `note` 非空，`ok=True` 并 `continue`）** · `1246-1253` 词表外 `kind` ⇒ 整表 unknown · **`1254-1265` `_leg_reading` 抛异常 ⇒ 整格 unknown** · **`1266-1275` `implicit_min` 兜底（`not want_min` 时才用）** · `1276-1277` `implicit_max` 兜底 · `1278` `ok_row = got >= want_min and (max is None or got <= max)` · `1291-1298` 整表全 `na` ⇒ fail · `1302-1314` 覆盖面 · `1319-1392` 四条自动分支 · `1393-1401` `unmet` 非空 ⇒ fail。

### 1.5 谁调用它（生产调用面）

| `file:line` | 内容 |
|---|---|
| `cli.py:2082` / `:2090` / `:2091-2098` | `agentflow closing`：`check_closing(st, project_dir, report_path)`；`:2088` 自动补 `<project>/out/review/REPORT.md`；**不传 sid ⇒ `sid=None` ⇒ 读缺省会话**；逐格打印 + 三态退出码 |
| `tools/conductor_tools.py:983` / `:986-988` / `:990` / `:1049` | M 的 `conductor.closing`（注入 `root`+`sid`）；`tri_state_exit_code`；装配清单 `('store','session')` |
| `tools/conductor_tools.py:863` | `conductor.acceptance` 复用 `resolve_under_workspace` |
| `reviewaccept.py:105` / `:451` / `:506` / `:231-233` | 复用 `resolve_under_workspace` / `NO_SESSION` |
| `reviewaccept.py:476-478` | **`check_closing(store, checks=("load_bearing",))`** —— `_check_load_bearing` 的第二个调用方 |
| `tools/__init__.py:398` | 仅 docstring 说明 |

**零引用**（已 grep 确认）：`statusreport.py`（E-15 要接的正是它）、`deliver.py`、`gates.py`、`faculty_checks.py`、`artifacts.py`、`signatures.py`。`closing.py` 全文**从未出现 `artifacts`**（EE-05/EE-10 的关联点见 §2.10/§2.11）。

---

## 2. 逐改动点

### 2.1 E-04：一行 `na` 关掉整档与四条自动分支

**① 位置。** `closing.py:1233-1245`（`na` 分支）+ 四守卫 `:1319 / :1340 / :1360 / :1378` + 覆盖面 `:347`。

**② 原文。**

```python
1233:        if row.get("na") is True:
1234:            if not note.strip():
1235:                _acceptance_unknown(...)
1241:                return
1242:            na_rows.append(cid)
1243:            out.append({"id": cid, "name": name, "kind": kind, "min": want_min, "max": None,
1244:                        "got": None, "ok": True, "na": True, "note": note})
1245:            continue
```

```python
1338:    # ---- 稿件是骨架还是手稿（`draft/39` §6.48 的 D63）：有 sections 却每节都空的行，
1340:    if "document_body_rows" not in {str(r.get("kind") or "") for r in out}:
```

```python
342:    for label, members in RESEARCH_CHAIN_GROUPS:
343:        hit = [k for k in members if k in used]
344:        marked = [k for k in members if k in na_used]
347:        if researched and not hit and not marked:
```

**③ 改成什么（接口级）。** `na` 收窄为"**只关掉本行自己的阈值判定**"：`_check_acceptance` 拆出 `computed_kinds`（真算过的行）与 `na_kinds`，四条分支的守卫改为对 `computed_kinds` 求集合；分支本体改为"**读台账**"（先跑 `_leg_reading`，读到缺陷才 `unmet.append`），`na` 行只在读数里留痕。保留两条既有守卫（`note` 非空 `:1234`；整表全 `na` ⇒ `acceptance_all_na` `:1291`）。新增读数 `na_covered_groups` 与 `na_hidden_defects`（哪些缺陷本会被分支报出、却因缺那一行而被 `na` 顶掉）。覆盖面 `:347` 的 `marked` **保留**（D49 的合法出口）。

**④ 依据。** `draft/44:155`；`draft/41-F` B2（262-267 行）、B3（269-274）、B4（276-281）。

**实测（真机数据 + 内存复算，盘上零改动）。** 用真实工作区的表追加 `na` 行、在内存里重跑 `_check_acceptance`：

| 工作区 | 原表 | 追加 | 结果 |
|---|---|---|---|
| `p7b-open-questions` | 7 行 `fail` | 6 行（`retrieval_ok_rows`/`c_analysis_runs`/`plan_progress_rows`/`unfinished_request_rows`/`claim_evidence_fit_rows`/`manuscript_rows`） | **`pass`，findings 为空** |
| `p5-review-t17` | 5 行 `fail` | 3 行（`document_body_rows`/`claim_evidence_fit_rows`/`manuscript_rows`） | **`pass`** |
| `p8g-fermat-shorter-proof` | 10 行 `fail` | 3 行（同上） | **`pass`** |

复算方式：把 `closing.Path` 换成一个"只对 `ACCEPTANCE-CHECKS.json` 返回内存字符串、其余委托真 `Path`"的包装类，再调 `check_closing(checks=('acceptance',))`。（41-F 的 `gh_probe_1.py::A_na_bypass` 只在临时工作区验过；本报告把它搬到了**真机工作区的真表**上。）

**E-04 对 33 份真表的实际影响 = 0 处翻转。** 4 行 `na` 是 `numeric_experiment_rows`（p7b `B1`）、`supported_claims`（p7b `D2`）、`reviewed_proof_rows`（p8d `A2`）、`proof_experiment_rows`（p8g `C10`）——**没有一行落在四条分支认的四个档上**。原文（缩写）：

```json
{"id":"B1","kind":"numeric_experiment_rows","min":0,"na":true,"note":"任务为「调查开放问题、交付清单」，不要求算或造；experiments 0 行是如实读数，不是缺口"}
{"id":"D2","kind":"supported_claims","min":0,"na":true,"note":"本任务为调查型…不跑数值实验、不产出 REPRO_RESULT 支持性结论"}
{"id":"A2","kind":"reviewed_proof_rows","min":0,"na":true,"note":"本轮是文献调查型任务：…statements 3 行全部 origin=external_lit，这一档天然不适用"}
{"id":"C10","kind":"proof_experiment_rows","na":true,"note":"形式化未核到：0002/0003/0004 三次 method=formal 全部 compile_error…同一命题已试满 3 次，按纪律收手"}
```

**必须裁定的分叉：** `draft/45` 只要求"`na` 不能关掉四条自动分支"。若顺手把"`na` 不再算覆盖面 `marked`"（`:344`）也改，会把上面四行**合法** `na` 一起变红（p7b 的"算或造"整环正是被 `B1` 一行覆盖的，§3.4）。**不要与 E-04 同批。**

### 2.2 E-05：阈值不许被压低 / 自证

**① 位置。** `closing.py:1213` + `:1266-1278`（`min` 与 `implicit_min` 的关系）；`:575-596`（引文档的分母取自主稿）；`:549-568`（`manuscript_edited` 一个字节即算改过）。

**② 原文。**

```python
1213:        want_min = int(row.get("min") or 0)     # 0 = 让这一档自己定阈值（见下面的 implicit_min）
1266:        if not want_min:
1269:            implicit = detail.get("implicit_min")
1270:            if implicit is None:
1273:                want_min = 0 if detail.get("implicit_max") is not None else 1
1274:            else:
1275:                want_min = int(implicit)
1278:        ok_row = got >= want_min and (want_max is None or got <= want_max)
```

```python
577:        src = draft if draft.is_file() else base      # draft = out/paper/main.tex, base = source/main.tex
589:            # 这一档的阈值由主稿自己定：每条 `\bibitem` 一条记录。调用方给了 `min`
590:            # 就用它的（显式优先），没给就按这个
592:            "implicit_min": bibitems,
593:            "counted_from": "out/paper/main.tex" if src is draft else "source/main.tex",
```

```python
560:        d_sha = RA.file_digest(draft)
561:        b_sha = RA.file_digest(base)
562:        same = d_sha == b_sha
563:        return (0 if same else 1), {... "edited": not same}
```

**③ 改成什么（接口级）。** ①阈值改为**取大**：`want_min = max(int(row.get("min") or 0), int(detail.get("implicit_min") or 0))`，并新增读数 `min_overridden: {declared, kind_min, effective}`；`min` 从此只能把阈值**提高**。②引文档分母改为**只读基线** `source/main.tex`（基线不在 ⇒ 第四态，见 CC-05），读数并列 `denominator_from` 与 `draft_bibitems`。③`manuscript_edited` 改为"**去空白规范化后仍有差异**"（`re.sub(r"\s+"," ",text).strip()` 后比哈希），读数并列 `raw_changed` 与 `substantive`，取值用后者。④其余给 `implicit_min` 的档（`:660 :686 :700 :717 :540 :592`）产出不变，但同样不可被更小的 `min` 覆盖。

**④ 依据。** `draft/44:156`；`draft/41-F` B5（283-288 行）、B8（304-309 行）。

**实测（33 份表 / 204 行）。** 184 行显式写 `min>0`、8 行写 `min=0`、8 行未写 `min`；2 行写 `max`（都是 `unfinished_request_rows`，值 0）。**9 行**吃到该档自算的 `implicit_min`（`citation_records_vs_bibitems` 6 + `unfinished_request_rows` 2 + `retrieval_ok_rows` 1）；**表里 `min` 与该档 `implicit_min` 不一致的行 = 0** ⇒ "`min` 压低自算阈值"这条口子在盘上**从未被用过**（是潜在风险，不是已发生的事故）。引文档 6 次使用中主稿与基线的 `\bibitem` 条数**全相等（都是 7）**。`manuscript_edited` 的 9 次 `got=1` 逐字节差 1258/262/1195/182/614/138/555/1012 字节，**去空白后仍全不相同**。⇒ **E-05 的实测影响也是 0 处翻转**——这正是"收紧不误伤历史"的直接证据。

### 2.3 E-06：九节与附件判据做实

**① 位置。** `closing.py:1415-1425`、`:1428`、`:1919-1942`。

**② 原文。**

```python
1919:    text = path.read_text(encoding="utf-8")
1920:    missing = [f"{num}、{name}" for num, name in REPORT_SECTIONS
1921:               if f"{num}、" not in text and name not in text]
1922:    missing_split = [m for m in SPLIT_MARKERS if m not in text]
1923:    has_attach = [f for f in ATTACHMENT_FIELDS if f in text]
1924:    rep.readings["report_shape"] = {
1926:        "missing_sections": missing, "missing_split_markers": missing_split,
1927:        "attachment_fields": has_attach, }
1929:    problems: list[str] = []
1930:    if missing:
1931:        problems.append(f"缺 {len(missing)} 节（{'、'.join(missing[:4])}）")
1932:    if missing_split:
1933:        problems.append(f"缺分栏标记（{'、'.join(missing_split)}）—— …")
```

`grep has_attach` 全仓只命中 `1923` / `1927` —— **算出来了，从不参与判定**（41-F B7）。

**③ 改成什么（接口级）。** ①九节改为**标题级 + 节体非空**：`_SECTION_RE = re.compile(r"^#{2,3}\s*([一二三四五六七八九])、(.+)$", re.M)`（与 `reviewaccept.py:54` 同形态，但**修掉 `reviewaccept.py:117` 的起点偏移 bug**），逐节取"标题→下一标题"之间文本，要求 `strip()` 非空；可选再加 `reviewaccept._LEDGER_REF_RE` 的"有读数"要求（与 CC-06 同批决定）。②附件三件套**真的判**：`missing_attach` 非空 ⇒ 进 `problems`；**必须并入同一个 `report_incomplete` finding**，否则 `tests/test_closing_gate.py:799` 的 `== ["report_incomplete"]` 会红。③读数新增 `empty_sections` / `missing_attachment_fields` / `section_bodies`。

**④ 依据。** `draft/44:157`；`draft/41-F` B7（297-302 行）。

**实测（46 份真机 `REPORT.md`，两个根）。** 严格标题 + 节体非空：**45/46 本来就已经合格**，只有 `p5-run6` 是 5 节（缺六/七/八/九）。附件三件套改后**红 9/46**：`p5-run6`（缺 `origin=own_result`）、`p6-research-from-zero`/`p6e`/`p6k`/`p6o`/`p8f`（缺 `origin=own_result`+`依据`）、`p6n`/`p6q`（缺 `origin=own_result`+`sha`）、`p7-open-questions`（缺 `origin=own_result`）。⇒ **"九节查节体"只翻 1 份（`p5-run6`），"附件三件套真的判"翻 9 份**。

| 六格回放集 | 改前 `report_shape` | 改后 | 原因 |
|---|---|---|---|
| `p8e` / `p8g` / `p7b` / `p5-review-t17` | pass | **pass** | 三件套齐 |
| `p8f` | pass | **fail** | 缺 `origin=own_result`、`依据` |
| `p6q` | pass | **fail** | 缺 `origin=own_result`、`sha` |

### 2.4 E-08：锚与验收表解耦

**① 位置。** `closing.py:76`（落点）+ `renderanchor.py:74-87`（`package_files` 收全部非编译产物）+ `renderanchor.py:276-289`（files 维度三方向判漂移）。

**② 原文。**

```python
 renderanchor.py:74: def package_files(package_dir: Path) -> dict[str, str]:
 81:    for p in sorted(package_dir.rglob("*")):
 82:        if not p.is_file() or p.name in (ANCHOR_NAME, RECEIPT_NAME):
 83:            continue
 84:        if p.name in COMPILE_PRODUCTS or p.suffix in COMPILE_SUFFIXES:
 85:            continue
 86:        files[p.relative_to(package_dir).as_posix()] = file_digest(p)
```

```python
276:    files_now = package_files(out)
277:    files_was = {k: v for k, v in (anchor.get("files") or {}).items()
278:                 if k not in COMPILE_PRODUCTS and not any(k.endswith(s) for s in COMPILE_SUFFIXES)}
287:    for rel in sorted(set(files_now) - set(files_was)):
288:        files_verdict = "drifted"
289:        drift.append(f"文件 {rel}：盘上有、锚里没有（渲染之后新加/改名的）")
```

```python
closing.py:76: ACCEPTANCE_CHECKS_NAME = "out/paper/ACCEPTANCE-CHECKS.json"
```

**③ 改成什么（接口级）。** 新增与 `COMPILE_PRODUCTS` 同族的 `PROCESS_PRODUCTS = ("ACCEPTANCE-CHECKS.json", "ACCEPTANCE.md")`（或前缀 `ACCEPTANCE-`）；`package_files` 不收它们，`check_package` 的 `files_was` 过滤（`:277-278`）**同时**加这一条。**两侧必须对称**，否则老锚会因"锚里有、盘上没了"被判 `drifted`（这正是 `draft/45:45` 记的风险，实测可避免）。按**文件名**匹配而不是按相对路径——`p6i` 的锚键是 `out/paper/main.tex` 这种带前缀的形状。读数新增 `excluded_process_products`。

**④ 依据。** `draft/44:159`；`draft/41-F` B10（318-323 行）。

**实测。** 32 份锚中 **10 份**的 `files` 含 `ACCEPTANCE-CHECKS.json`（`p5-review-t9…t17`、`p6r-paper-from-results`），当前全 `consistent`。在 `p5-review-t17` 上把 `RA.package_files` 换成"验收表 sha 被改过"的版本后重跑 `check_package`：

```
原状:          verdict=consistent dims={'tables':'consistent','files':'consistent','receipt':'consistent'}
改验收表之后:  verdict=drifted      dims={'tables':'consistent','files':'drifted','receipt':'consistent'}
drift: ["文件 ACCEPTANCE-CHECKS.json：内容与渲染时不同（3bc8778efbf2 ≠ 000000000000）"]
```

⇒ **交付时改一次验收表就足以把 `anchor` 打红**，互咬成立。对称过滤后 10 份老锚**全部保持 `consistent`（0 处翻转）**。

### 2.5 S-05：研究产出读数

**① 位置。** 三处落点：`:80-244`（词表）、`:470-1126`（新分支）、`:272-319`（若要进覆盖面）；镜像三处：`agent_prompts.py:1009-1110`、`agent_prompts.py:1095-1106`、`specs/m.py:69-79`。

**② 原文（现状 = 没有一档问"数学往前走了没有"）。**

```python
  23:    ("立题", ("research_question_rows",)),
 287:    ("算或造", ("numeric_experiment_rows", "search_frontier_rows",
 288:                "enumeration_optimization_rows", "reviewed_proof_rows",
 289:                "counterexample_or_proof_rows")),
 290:    ("想（猜想或判决性证据）", ("conjecture_rows", "statement_rows",
 291:                                "counterexample_or_proof_rows")),
```

**③ 改成什么（接口级）。** 新增三档（**只加档、不改既有档口径**）：

```
conclusive_experiment_rows = experiments 里 result ∈ {supports, refutes} 且
                             (claim/certificate/search_bound 至少一项非空) 的行数
own_result_statement_rows  = statements 里 origin=own_result 且
                             evidencebits.bits_from_row(r)["grade"] ∉ {conjecture} 的行数
question_delivery_rows     = 交稿↔问题：documents.claims[].citations 经 exp:<id>/rel:<id>
                             回落到 experiments.for_question_id / conjectures.for_question_id
                             得到的**不同 question_id** 数
```

前两档挂进"算或造"/"想"两环（或新开一环），第三档**先只做读数、不进覆盖面**。三档的读数都必须并列分母（`experiments_total` / `statements_total` / `research_question_rows`）。

**④ 依据。** `draft/44:41`（"`inconclusive` 203/406 = 50% 仍可全绿"）；`draft/41-F` §1.6/§1.7（129-158 行）。

**实测基线（独立复算）。** `experiments`：根 A 217 = `supports` 55 / `refutes` 24 / `inconclusive` **138（63.6%）**；根 B 189 = 124 / 0 / **65（34.4%）**；合计 406 中 `inconclusive` **203（50.0%）**（与 44 一致）。`statements`：根 A 138 行、`origin=own_result` **13** 行，但 `bits_from_row` 的 `grade` **全部 `conjecture`**（`pre_theorem` 6 行全是 `external_lit`）⇒ **"我方派生命题 + 等级"这一档今天结构性恒为 0**（同 41-F B13 之因：`agent_b/register_statement.py` 不传 `bits`）。`for_question_id` 覆盖：根 A `experiments` 54/217（25%）、`conjectures` **0/66**、`statements` **0/138**；根 B 三项全 0。

**施工结论（分级）：**
- 腿 1（有结论的实验）**高可行**：纯读数，今天即非零（179/406）。
- 腿 2（我方命题 + 等级）**依赖 F-01/EE-12**，落地前恒红 ⇒ **不要单独上**。
- 腿 3（交稿↔问题）**字段面撑不住**：`schema.py:2394` 的 `documents` 只有 `sections/claims/open_problems`，没有 `for_question_id`；只能走引用链，而该字段只有 25% 的实验有值。要么加 `documents.claims[].for_question_id`（**禁改区 `schema.py`**，须人裁），要么降级成"可判链"读数并同列 `unlinked_claims`。

### 2.6 F-06：验收表由台账生成

**① 位置。** `closing.py:1160-1186`（表不在的分支）+ `:1187-1196`（解析）+ `:1246-1253`（词表外 ⇒ 整表 unknown）。

**② 原文。**

```python
1160:    if not path.is_file():
1164:        try:
1165:            chain = research_chain_gaps(store, ())
1174:        if chain["researched"]:
1175:            rep.status["acceptance"] = "fail"
1176:            rep.findings.append(Finding(
1177:                "acceptance", "acceptance_missing_for_research", "blocker", …))
1183:        else:
1184:            rep.status["acceptance"] = "pass"
1185:            rep.readings["acceptance"]["note"] = f"这个项目没有 {ACCEPTANCE_CHECKS_NAME}"
1186:        return
```

**③ 改成什么（接口级）。** 新增纯函数 `generate_acceptance_rows(store, project_root) -> list[dict]`：对 `LEG_CHECK_KINDS` 逐档调 `_leg_reading`，产出 `{"id","name","kind","min","max","generated_by":"framework"}`；`min` 取该档 `implicit_min`（没有则 1），`max` 取 `implicit_max`。表不在的分支改为"先生成、再走同一套 `:1203-1392` 判定"，读数新增 `generated: true` 与 `table_source: "file" | "generated"`；**生成不出可判行时仍然红**（保留 `acceptance_missing_for_research` 语义）。`na` **不由生成器写**（那是人或模型的知识）；老表缺 `generated_by` 不报错。

**④ 依据。** `draft/44:30`；`draft/41-F` B11（325-330）、B12（332-337）。

**实测。** 33/33 份真机工作区**都有**验收表 ⇒ F-06 在盘上 **0 处翻转**（它改的是"没有表"那条路）。**注意别混批：** `conductor.acceptance`（`conductor_tools.py:838-875`，读的是人读 `out/paper/ACCEPTANCE.md`，解析器 `:1100-1149`）与 `closing.acceptance`（读 JSON）是两份不同的东西；CC-02 的"8/54 份 `.md` 读成 0 行"属于前者。

### 2.7 CC-03：一个词表装两代 30 档

**① 位置。** `closing.py:80-244`；段界注释 `:162` 与 `:210`；镜像 `agent_prompts.py:1095-1106`（逐字 **29** 档清单）与 `specs/m.py:75`。

**② 原文（段界）。**

```python
 161:                            "少了它，「请求提交了没人做」在收工门上一个读数都没有",
 162:    # ---- 研究类（`draft/38` 的 T2：从零做一轮研究，考察 A/B/D/E/F 与 M 的调度）----
 163:    "research_question_rows": "立起来的研究问题行数（`research_questions`）…
 209:                        "（那正是这一档要逼出来的那句实话）",
 210:    # ---- 数学对象的进度（`draft/37` §133：判「数学」，不判「台账厚度」）----
 211:    "conjecture_rows": "可检验的猜想条数（`conjectures` 里 `statement` 与 `testable` 都非空的行）"
```

**③ 改成什么（接口级）。** 关键施工事实：**按行号分段分不出"评审向 vs 研究向"**——`retrieval_ok_rows`（`:111`）、`document_rows`（`:119`）、`document_body_rows`（`:126`）、`document_claim_rows`（`:133`）、`claim_evidence_fit_rows`（`:139`）都在第一段行号区间里，但它们全是 D59–D63（T5 研究趟）加的。正确分法要**按"这一档在什么工作区能算出数"**：

- `KIND_REQUIRES_BASELINE = ("manuscript_edited", "citation_records_vs_bibitems")`（实测：前者 9 次用于审阅型 + 1 次误用于 `p6i`；后者 6 次全在审阅型）。
- 研究型专用 16 档（实测只在研究型工作区出现过）：`document_literature_citations` / `conjecture_rows` / `plan_progress_rows` / `search_frontier_rows` / `statement_rows` / `supported_claims` / `c_analysis_runs` / `counterexample_or_proof_rows` / `reviewed_proof_rows` / `unfinished_request_rows` / `claims_supported_by_their_evidence` / `enumeration_optimization_rows` / `manuscript_rows` / `analysis_report_rows` / `retrieval_ok_rows` / `document_rows`。
- 两代共用：`research_question_rows`（研究 22 + 其他 1）、`retrieval_attempts`（研究 14 + 审阅 5）、`numeric_experiment_rows`（研究 16）、`reviewed_documents`（审阅 10 + 研究 2）、`proof_experiment_rows`（审阅 10 + 研究 1）、`quote_verified_rows`、`report_files`、`attack_plan_rows`。
- **30 档取值不变**（`kind` 是 204 行历史表的字面契约）；只加 `LEG_CHECK_GROUPS: dict[str, tuple[str, ...]]`（`review_only`/`research_only`/`shared`）与 `LEG_CHECK_HINTS`，并让 `research_chain_gaps` 对"研究型工作区拿到 review-only 档"给读数级警告。
- 镜像必须补上 **`c_analysis_runs`**（今天逐字清单 29 档、代码 30 档），并把 `tests/test_agent_prompts.py:200` 的"子串包含"改成"**清单 == 词表**"（集合相等）。

**④ 依据。** `draft/44:118`；`draft/41-F` §4 第 401 行。

**实测。** 33 份表 / 204 行用掉 **26 档**；**未出现的 4 档 = `reviewed_current_rows` / `document_body_rows` / `document_claim_rows` / `claim_evidence_fit_rows`** —— 四条自动分支覆盖的四个档里，**三档在 33 份真表上一次都没被声明过**，这正是 E-04 为什么重要。

### 2.8 CC-05：一行不适用废掉整表 unknown

**① 位置。** `closing.py:1254-1265`（catch-all ⇒ 整格 unknown）+ 两处抛错档 `:556-559`、`:578-579` + 落点 `:1129-1142`。

**② 原文。**

```python
1254:        try:
1255:            got, detail = _leg_reading(store, kind, Path(resolve_under_workspace(store, project_dir)))
1256:        except Exception as exc:  # noqa: BLE001
1257:            _acceptance_unknown(
1258:                rep, "acceptance_leg_unreadable",
1259:                f"验收行 {cid}（{kind}）的读数算不出来（{type(exc).__name__}: {exc}）"
1260:                f"⇒ 这一行没查成（不是「不满足」，也不是「满足」）。" …)
1265:            return
```

```python
556:        if not draft.is_file():
557:            raise ValueError(f"可改的主稿不在盘上：{draft} ⇒ 这一档没查成")
558:        if not base.is_file():
559:            raise ValueError(f"只读基线不在盘上：{base} ⇒ 这一档没查成（比不出'改没改'）")
```

**③ 改成什么（接口级）。** 档位可获得性做成**第四态**：新增 `LegNotApplicable(kind, reason)`，`manuscript_edited` / `citation_records_vs_bibitems` 在缺 `source/` 时抛它；`_check_acceptance` 捕获后**不整格 return**，该行落 `{"ok": None, "not_applicable": true, "reason": …}` 且不进 `unmet`；新增 `rows_read` / `rows_not_applicable` 两个读数。真正的读错（台账读不到、JSON 坏）仍整格 unknown（保留 `acceptance_leg_unreadable`），判据是"**缺基线 = 不适用**"vs"**读不到台账 = 没查成**"。顺带：`research_chain_gaps` 的 `marked` 也要认这些"不适用"行，否则 `p6i` 会在两层各红一次。

**④ 依据。** `draft/44:120`；`draft/41-F` §1.7 第 150-152 行；`closing.py:1135-1137` 的 docstring 逐字记着 `p6i` 那次事故。

**实测。** 33 份表中 `manuscript_edited` 有 23 处不可读（缺 `source/`）、`citation_records_vs_bibitems` 有 21 处；**真表用到且踩中的只有 `p6i-research-from-zero` 一处**。当前：`acceptance=unknown`、`code=acceptance_leg_unreadable`、**`rows=0`**（后面 10 行连读数都没留下）。改后：`rows=11` 全部有读数，`acceptance=fail`（`P10 document_literature_citations` `got=0` + 覆盖面缺环），第一行变成 `not_applicable`。

### 2.9 CC-06：删掉重复的"报告九节"判据

**① 位置。** `closing.py:1920-1921` + `:1929-1942`（宽松）对 `reviewaccept.py:54` + `:113-135`（严格标题正则 + 每节要有读数，`:117` 有 bug）。

**② 原文。**

```python
reviewaccept.py: 54: _SECTION_RE = re.compile(r"^#{2,3}\s*([一二三四五六七八九])、(.+)$", re.M)
reviewaccept.py:113:    sections = _SECTION_RE.findall(text)
reviewaccept.py:117:        start = text.find(f"{num}、")        # <-- 没有起点偏移：取到前言里第一次出现
reviewaccept.py:121:        if not re.search(r"\d", body) and not _LEDGER_REF_RE.search(body):
reviewaccept.py:122:            empty.append(f"{num}、{name.strip()}")
```

```python
closing.py:1920:    missing = [f"{num}、{name}" for num, name in REPORT_SECTIONS
1921:               if f"{num}、" not in text and name not in text]
```

**③ 改成什么（接口级）。** 顺序**必须是**：先在 `closing` 做出 E-06 的严格判据（含"节体非空"与"每节有读数"两条，`_SECTION_RE` 从 `reviewaccept` **搬**来并修掉 `:117`），跑通真机回放，**然后**才删 `reviewaccept` 全模块（555 行）；`CRITERIA` 六条里唯一没落点的 `report_sections_have_readings` 由 `closing.report_shape` 唯一承担（`attachment_is_honest` 的三件套正好被 E-06 接住）。连带删 `tests/test_review_acceptance.py`，并改 `tests/test_ledger_charging.py:33`、`tests/test_intake_actions.py`、`tests/test_sid_scoped_questions.py`、`tests/test_relative_paths_under_workspace.py` 的引用。`reviewaccept.py:476-478` 的 `check_closing(checks=("load_bearing",))` 随模块消失 ⇒ `_check_load_bearing` 的调用方从两个减到一个。**`closing` 侧必须同时给出 `section_readings`（逐节是否含数字/台账引用）**，否则"两处口径"变成"一处更弱的口径"。

**④ 依据。** `draft/44:121`；`draft/41-F` §4 第 405 行、B12。

**实测。** 报告总数 46；`reviewaccept` 在生产代码里唯一的调用是自身 `check_review`（无生产调用点）。`p5-review-t10` 那类"同一报告两个相反结论"在本报告口径下复算：`closing.report_shape=pass`，而 `reviewaccept._c_report` 的 `:117` 会把节体截断到前言里第一次出现的 `f"{num}、"` ⇒ 误判"节里没有读数"。

### 2.10 EE-05：`ARTIFACTS.jsonl` 完整性没有读数

**① 位置。** `closing.py` 全文**零处**提到 `artifacts`（grep 确认）。要加只能新增：`:80-244`（新档）+ `:470-1126`（新分支）+ `:49`（若要成第八格）。

**② 原文（对照组：PDF 那一维是有的）。**

```python
 renderanchor.py:306:        elif file_digest(out / "main.pdf") != str(receipt.get("pdf_sha256") or ""):
 renderanchor.py:307:            receipt_verdict = "drifted"
 renderanchor.py:308:            drift.append("main.pdf：内容与编译回执不符（编译之后被换过？）")
```

**③ 改成什么（接口级）。** 新增一档 `artifact_ledger_bad_rows`：`got = changed + missing + unreadable`，`implicit_max = 0`（与 `unfinished_request_rows` 同一根轴：越少越好）；读数给 `{ok, changed, missing, unreadable}` 与明细（最多 8 条）。是否进 `DEFAULT_CHECKS` 第八格 = 独立裁定（七格→八格要动 `conductor.closing` 的工具描述与 `tests/test_conductor_tools.py:101-115`）。

**④ 依据。** `draft/44:134`（"加（红线：产物登记必须与盘上一致）"）。

**实测（独立复现 44 的数字）。** `artifacts.verify_entries` 逐条：根 A 57 个台账目录 = **1387 `ok`** / 0 changed；根 B 8 个 = **2599 `ok` / 589 `changed`**（≈18.75%，与 44 逐字一致）。kind 分布（根 B）：`paper` 2985 / `script` 105 / `task-result` 91 / `report` 7。

### 2.11 EE-10：同一份产物在两个台账里各钉一次

**① 位置（`closing` 侧的实际接口点）。**

```python
closing.py:510:        from . import signatures as SIG
closing.py:513:        recs, bad_lines = SIG.read_ledger(SIG.ledger_path(project_root))
closing.py:521:        pinned = [d for d in claimed if SIG.signed_revision(d, recs) is not None]
closing.py:613:        from . import manuscripts as MS
closing.py:615:        all_rows, bad_lines = MS.read_rows(project_root)
```

**② 原文（重复实现清单，按盘上真实情况**更正** 44 的措辞）。**

| 函数 | 落点一 | 落点二 | 备注 |
|---|---|---|---|
| `ledger_path` | `artifacts.py:79` | `signatures.py:153` | 两条台账的两个落点 |
| `read_ledger` | `artifacts.py:165` | `signatures.py:170` | 返回 `(records, bad_lines)`，形状相同 |
| `sha256_of` / `file_digest` | `artifacts.py:108` | `renderanchor.py:59` | 同一件事的两份实现 |
| `summarize` / `render_markdown` | `artifacts.py:249` / `:264` | 无对应 | 44 说"signatures 也有一份"**不成立** |
| `slugify` | `textutil.py:164` | `fetch.py:233` | **不在 artifacts/signatures** |

**③ 改成什么（接口级）。** 合并 `ledger_path`/`read_ledger`/`sha256_of` 到一处（`jsonlfile` 已并掉"怎么读 JSONL"那一层，见 `draft/36:152` 的 T-6）；`closing` 侧只改一处调用（`:513`），并在 `reviewed_current_rows` 读数里新增 `ledger_module`。**不要**把两条台账合并成一条——那是磁盘契约（`禁`），且规模不小：根 A **57** 个目录有 `ARTIFACTS.jsonl`、**40** 个有 `DOC-SIGNATURES.jsonl`（59 条签名记录）；根 B 是 **8** 与 **7**。

**④ 依据。** `draft/44:144`；`draft/41-F` §1.5 第 120-127 行。

**实测（真机双钉实例）。** 根 B 的 `p2-review` 与 `p4-polish`：`ARTIFACTS.jsonl` 里 `out/paper/main.tex` 的 `sha256=49404e4d159e180f…` 判 `ok`，同一份交付的 `DOC-SIGNATURES.jsonl` 钉的是稿件**内容哈希** `dc8a062c57cc4b01…`（现行版一致，旧版 `ac7ff9a33cd822b6…` 也在册）。两条台账对"交付还对不对得上"给的是**两个哈希空间的两个答案**，而 `closing` 只读后者。根 A 侧相反：57 个目录有产物台账，但 `out/paper/main.tex` **没有**一条进过它（`p5-review-t17` 只进签名台账）——两代的落点习惯也不同。

---

## 3. 验收表与受控档的真实用法基线（全部实测）

### 3.1 33 份 `ACCEPTANCE-CHECKS.json` 逐档统计

- **文件 33**（**全在根 A**；根 B **0 份**）；**行数 204**；**`na` 行 4**；用到 **26 / 30 档**。
- 阈值声明：`min>0` **184** 行、`min=0` **8** 行、未写 `min` **8** 行；写 `max` **2** 行（都是 `unfinished_request_rows` = 0）。
- 吃到该档自算 `implicit_min` 的 **9** 行；**表里 `min` 与该档 `implicit_min` 不同的行 = 0**。

| 档 | 用量 | `na` | 写了 `min` | 工作区类型 | 档 | 用量 | `na` | 写了 `min` | 类型 |
|---|---|---:|---:|---:|---|---:|---:|---:|---|
| `research_question_rows` | 23 | 0 | 23 | 研究 22 | `report_files` | 6 | 0 | 6 | 研究 5 |
| `retrieval_attempts` | 20 | 0 | 20 | 研究 14+审阅 5 | `statement_rows` | 6 | 0 | 6 | 研究 |
| `document_literature_citations` | 19 | 0 | 19 | 研究 | `supported_claims` | 5 | 1 | 5 | 研究 |
| `conjecture_rows` | 19 | 0 | 19 | 研究 | `c_analysis_runs` | 5 | 0 | 5 | 研究 |
| `numeric_experiment_rows` | 17 | 1 | 17 | 研究 16 | `quote_verified_rows` | 4 | 0 | 4 | 审阅 |
| `plan_progress_rows` | 14 | 0 | 14 | 研究 | `attack_plan_rows` | 4 | 0 | 4 | 研究 3 |
| `reviewed_documents` | 12 | 0 | 12 | 审阅 10+研究 2 | `counterexample_or_proof_rows` | 3 | 0 | 3 | 研究 |
| `proof_experiment_rows` | 11 | 1 | 10 | 审阅 10+研究 1 | `reviewed_proof_rows` | 2 | 1 | 2 | 研究 |
| `manuscript_edited` | 10 | 0 | 10 | 审阅 9+研究 1（`p6i` 抛错） | `unfinished_request_rows` | 2 | 0 | 0（只写 `max:0`） | 研究 |
| `search_frontier_rows` | 10 | 0 | 10 | 研究 | 其余 6 档各 1 次 | 6 | 0 | 6（1 个写 0） | 研究（含 `p6p`） |
| `citation_records_vs_bibitems` | 6 | 0 | **0** | 审阅 | —— | —— | —— | —— | —— |

`unfinished_request_rows` 的 2 行**完全不写 `min`，只写 `max: 0`**（`p8f` `C5`、`p8g` `C8`）；`citation_records_vs_bibitems` 的 6 行也**完全不写阈值**，全靠该档自算的 `implicit_min`（= 基线里 `\bibitem` 条数）。

"其余 6 档"= `claims_supported_by_their_evidence` / `enumeration_optimization_rows` / `manuscript_rows` / `analysis_report_rows` / `retrieval_ok_rows` / `document_rows`。

### 3.2 逐格现状（`check_closing(checks=("acceptance",))`，33 个工作区）

| 结果 | 个数 | 工作区 |
|---|---:|---|
| `fail`（`acceptance_unmet`） | **32** | 除 `p6i` 外全部 |
| `unknown`（`acceptance_leg_unreadable`） | **1** | `p6i-research-from-zero` |
| `pass` | **0** | —— |

**施工含义：今天没有任何一份真实验收表能过门。** 所以"改前/改后"在 `acceptance` 这一格几乎全是 `fail → fail`，**必须比 `findings.detail` 里的原因行**而不是状态词。六格回放集改前的原因：

| 工作区 | 改前 `acceptance` 的原因 |
|---|---|
| `p8e` | 覆盖面缺「检索（真的取回）」+「闭（请求闭环）」；`reviewed_current_rows` 陈旧签名（`0000` 现行 `68bfc4c7…` vs 签名 `e7346eb7…`，`status=revised, revision=2`）；`claim_evidence_fit_rows` mismatch（`0000/claim-4`） |
| `p8f` | 覆盖面缺「检索（真的取回）」+「交（手稿落盘）」；`manuscript_rows` 62 行全是框架派生 |
| `p8g` | `document_body_rows`：`0000` 三节 body 全空；`claim_evidence_fit_rows`：`claim-1/2/3` 全 mismatch（含两条 exp 数字互换） |
| `p7b` | 覆盖面缺 4 环；`claim_evidence_fit_rows` mismatch（`0000/claim-3`、`0000/claim-11`） |
| `p6q` | 覆盖面缺 3 环；`manuscript_rows` 96 行全是框架派生 |
| `p5-review-t17` | `document_body_rows`：`0000` 五节 body 全空；`claim_evidence_fit_rows` mismatch（`claim-2/claim-3`）；`manuscript_rows` 92 行全是框架派生 |

### 3.3 `_leg_reading` 每个分支在真机上的可读性（30 档 × 33 工作区 = 990 次实跑）

| 档 | 抛错次数 | 类型 | 原因 |
|---|---:|---|---|
| `manuscript_edited` | **23 / 33** | `ValueError` | 缺 `source/main.tex` 或 `out/paper/main.tex`（`:556-559`） |
| `citation_records_vs_bibitems` | **21 / 33** | `ValueError` | 两者都不在盘上（`:578-579`） |
| 其余 28 档 | **0** | —— | 33 个工作区都有全套表 |

**真表用到的档里会抛错的只有 `p6i` 的 `manuscript_edited`（1 处）**；另外 43 次抛错都落在"没被表用到"的档上。事故只发生一次，但它是**结构性**的（`agent_prompts.py:1107-1110` 的提示词还专门警告过）。

### 3.4 一个额外的真机事实（`na` 覆盖面）

`p7b` 的 `B1`（`numeric_experiment_rows` + `na`）让"算或造"这一环（5 个成员档）**整环算覆盖**：`p7b` 的 `research_chain.missing` = `['检索（真的取回）','看（关系分析）','攻（攻坚推进）','闭（请求闭环）']`——**"算或造"不在其中**。这是 B3 在真机上的样子，也是 E-04 的"关掉整档"在覆盖面这一层的第二个落点。

---

## 4. 调用面

### 4.1 `src/` 调用点

已在 §1.5 逐条给出（`cli.py:2082/2090/2091-2098`、`tools/conductor_tools.py:983/986-988/990/1049/863`、`reviewaccept.py:105/451/506/231-233/476-478`、`tools/__init__.py:398`）。**零引用**：`statusreport.py`、`deliver.py`、`gates.py`、`faculty_checks.py`、`artifacts.py`、`signatures.py`、`manuscripts.py`。

### 4.2 `tests/` 覆盖（`file:line`）

| 文件与行 | 覆盖什么 |
|---|---|
| `tests/test_closing_gate.py`（**55** 个 `def test_`，171…1860） | 七格正控/负控、验收表逐档、`na`、覆盖面、四条分支 |
| `tests/test_closing_gate.py:171` | 正控：七格全过 |
| `:322` / `:371` | `manuscript_edited` / `citation_records_vs_bibitems`（**E-05 会碰**） |
| `:793` | `report_shape` 单独红（**E-06 会碰**） |
| `:948` / `:966` / `:989` / `:1011` | 覆盖面四条（**F-06 会碰 `:948`**） |
| `:1270` | 不可读档 ⇒ 整格 unknown（**CC-05 会碰**） |
| `:1295` / `:1312` / `:1354` / `:1368` | 自造 `kind` ⇒ 整表 unknown；三条 `na` 判据 |
| `:1705` / `:1860` | `na` 作为合法出口（**E-04 会碰 `:1860`**） |
| `:1428` / `:1481` / `:1520` / `:1545` / `:1567` / `:1604` / `:1639` / `:1673` / `:1731` / `:1800` / `:1827` | 逐档判据（`citation_fit`、`document_body_rows`、`document_claim_rows`、`document_rows`、`retrieval_ok_rows`、`unfinished_request_rows`、`reviewed_current_rows`） |
| `tests/test_contradiction_fixtures.py:22,61,159,166` | `contradictions` 与 `pollution_set` |
| `tests/test_review_chain_endorse.py:23,87,93,118` | `load_bearing` 三态 |
| `tests/test_relative_paths_under_workspace.py:16,76,91,135` | `resolve_under_workspace` 四个落点 |
| `tests/test_sid_scoped_questions.py:13,43,52,63` | `sid` 三态 |
| `tests/test_session_context_wiring.py:30,92,113,139,151,152,160` | 会话身份不折叠 |
| `tests/test_write_report_path.py:18,112,119,122` | `report_files` 与 `check_closing` |
| `tests/test_research_progress.py:25,104-110` | `search_frontier_rows` / `enumeration_optimization_rows` |
| `tests/test_agent_prompts.py:196-201` | 30 档都要出现在 M 的 brief（**子串包含 ⇒ CC-03/CC-09 会碰**） |
| `tests/test_agent_prompts.py:808-825` | `ACCEPTANCE-CHECKS.json` 文件名必须点名（**F-06+P-03 会碰**） |
| `tests/test_conductor_tools.py:101-115` | `conductor.closing` 描述要点名每一格，不许写旧条数 |
| `tests/test_ledger_charging.py:33` / `tests/test_review_acceptance.py:65-66,238` | `import closing` / 从 `closing.REPORT_SECTIONS` 取九节（**CC-06 删除时一起走**） |
| `tests/test_release_all.py:2232` | 发布说明里把 `closing.py` 的职责写成"五条"（**陈述陈旧：今天七格**） |

### 4.3 `conductor_tools.py` 的两个验收入口（**不是同一件事**）

| 工具 | 读什么 | 实现 |
|---|---|---|
| `conductor.acceptance`（`:813`, `:838-875`） | `out/paper/ACCEPTANCE.md`（人读 markdown，表头 `| 判据 | 名称 | 结论 | 读数 |`） | `_parse_acceptance:1100-1149`；结论列必须逐字 `成立`（`:1141`） |
| `conductor.closing`（`:930-998`） | `out/paper/ACCEPTANCE-CHECKS.json` | `closing._check_acceptance:1145-1401` |

CC-02（8/54 份 `.md` 读成 0 行）属于前者，**与 E-04/E-05/E-06 不是同一批**。

---

## 5. 可行性与改动量

档次：**高**（纯读数逻辑、可独立回滚）/**中**（牵动镜像或既有测试断言）/**低**（要动磁盘契约或跨批）。

| 条目 | 位置 | 估计行数 | 档次 | 可独立做？ | 依赖 |
|---|---|---:|---|---|---|
| E-04 `na` 语义收窄 | `:1233-1245` + 四守卫 `:1319/1340/1360/1378` | +35 / −10 | **高** | **可以** | 无（须先裁定"覆盖面 `marked` 不动"） |
| E-05 阈值取大 | `:1213,1266-1278` | +15 / −6 | **高** | 可以 | 无 |
| E-05 分母换基线 + 实质改动 | `:575-596,549-568` | +25 / −8 | **中** | 需同批 | **CC-05**（缺基线要变第四态，否则 `:371` 夹具整格 unknown） |
| E-06 九节/附件做实 | `:1919-1942` + 常量 | +45 / −10 | **中** | 可以 | 无（须并入同一 `report_incomplete` code） |
| E-08 锚解耦 | `renderanchor.py:74-87,277-278` | +12 / −3 | **高** | 可以 | 无（**两侧对称过滤**） |
| S-05 腿 1 | `:80-244,470-1126,287-291` + 3 镜像 | +60 | **高** | 可以 | 无 |
| S-05 腿 2 | 同上 | +40 | **低** | **不可** | F-01 / EE-12（`register_statement` 写 `bits`） |
| S-05 腿 3 | 同上 | +50 | **低** | **不可** | `schema.py` 加 `documents.claims[].for_question_id`（**禁改区**，须人裁）或降级为"可判链"读数 |
| F-06 生成式验收表 | `:1160-1186` + 新函数 | +80 | **中** | 可先做保守版（只做读数） | 与 P-03 退场同批；否则"教人写表"与"门自己生成表"两套口径并存 |
| CC-03 分组标注 | `:80-244` + `agent_prompts.py:1095-1106` + `specs/m.py:75` | +40 / −5 | **中** | 可以 | CC-09；`tests/test_agent_prompts.py:200` 必须改 |
| CC-05 第四态 | `:1254-1265,556-559,578-579,1129-1142` | +45 / −10 | **中** | 与 E-05 分母同批 | E-05 |
| CC-06 删 `reviewaccept` | 删 555 行 + 5 个测试文件 | −700 | **中** | **必须在 E-06 之后** | E-06 |
| EE-05 产物台账档 | `:80-244,470-1126`（+ `:49`） | +40 | 高（读数）/ 中（进第八格） | 读数可独立 | `tests/test_conductor_tools.py:101-115` |
| EE-10 合并台账读法 | `artifacts.py:79,165` / `signatures.py:153,170` + `closing.py:513` | +10 / −30 | **中** | 可以 | 只合并"读法"，不合并台账本体 |

### 5.1 依赖图（必须同批的）

```
E-04 ──独立──>（先裁定：覆盖面 marked 是否一起改；不改则只碰 tests:1860）
E-05(阈值取大) ──独立──>
E-05(分母/实质改动) ──必须与──> CC-05(第四态)
E-06(严格九节 + 附件 + 每节读数) ──必须早于──> CC-06(删 reviewaccept)
E-08 ──closing.py 与 renderanchor.py 同批──>（否则锚读数两套）
F-06 ──必须与──> P-03(M policy 退场) + tests/test_agent_prompts.py:808 改写
CC-03 ──必须与──> CC-09(清单==词表) + agent_prompts.py / specs/m.py 镜像同步
S-05(腿2) ──必须晚于──> F-01 / EE-12
S-05(腿3) ──必须晚于──> schema 裁定
S-05(新档进覆盖面) ──> 改 research_chain 的 missing 口径 ⇒ 必须登记"从哪一趟起口径变了"
EE-05(进第八格) ──> DEFAULT_CHECKS 7→8 ⇒ cli / conductor_tools 描述 + tests/test_conductor_tools.py
```

**与 `statusreport`（E-15）的关系：** `statusreport.py` 今天**不引用** `closing`。E-15 要汇总"未闭环请求 / 待办 / 等级分布 / 污染面 / 未复核稿件"，最省事的做法是让 `statusreport.collect` **直接调 `closing._leg_reading`**（而不是重写一遍），并把 `_leg_reading` 从私有名提升为稳定接口或加一个批量入口 `leg_readings(store, kinds, root)`。**这是 E-15 的施工前提**，不属本次 11 条，但要一起排期。

---

## 6. 风险与验证

### 6.1 会红的既有测试（逐条给 `file:line`）

| 条目 | 测试 | 红的断言 | 处置 |
|---|---|---|---|
| E-04 | `tests/test_closing_gate.py:1860` `test_an_na_row_is_the_way_to_ship_a_deliberately_unreviewed_revision` | `assert rep.status["acceptance"] == "pass"`（`:1877`）——夹具 `:1869` 造了"改稿后签名钉旧版"，`na` 行本来关掉 `reviewed_current_rows` 分支；分支改无条件后必然 `fail` | 语义改写：断言"`fail` + 读数里有 `na` 行 + detail 点名 `stale_signoffs`" |
| E-04（若同时收紧覆盖面 `marked`） | `:1312` / `:1705` / `:1860` | `chain["na_groups"]["算或造"]` 非空（`:1350`）、`chain["missing"] == []`（`:1351`）、`"R8" not in blockers`（`:1728`） | **不要与 E-04 同批**（§2.1 分叉） |
| E-05 分母 | `tests/test_closing_gate.py:371` | `row["min"] == 3`（`:397`）、`fail`（`:408`）、`pass`（`:420`）——夹具 `:386` 只写 `out/paper/main.tex` | 夹具补 `source/main.tex`（同 3 条），并新增"只有主稿 ⇒ 该行不适用而非整格 unknown" |
| E-05 实质改动 | `tests/test_closing_gate.py:322` | "不同 ⇒ got=1" | 夹具差异是实质的 ⇒ 只需补一条"仅空白不同 ⇒ got=0"负控 |
| E-06 | `tests/test_closing_gate.py:793` | `[f.code for f in rep.blockers] == ["report_incomplete"]`（`:799`） | 附件问题**并入同一 code** 即不红；新开 code 则本条必改 |
| CC-05 | `tests/test_closing_gate.py:1270` | `acceptance == "unknown"`（`:1285`）、`[codes] == ["acceptance_leg_unreadable"]`（`:1291-1292`） | 改成"该行 `not_applicable` + 其余行有读数"，另加一条"台账真读不到 ⇒ 整格 unknown"把两种情形分开 |
| F-06 | `tests/test_closing_gate.py:948` | `fail` + blocker `acceptance_missing_for_research`（`:959-961`）、`len(chain["missing"]) == 8`（`:963`） | 改成"生成的行必须逐行判、读数有 `generated: true`" |
| F-06+P-03 | `tests/test_agent_prompts.py:808-825` | `assert name in text`（`:821`）——P-03 退场后必红 | 改成"门与生成器同源"（文件名出现在 F-06 生成器的落点常量里） |
| CC-03/CC-09 | `tests/test_agent_prompts.py:196-201` | `missing = [k for k in CL.LEG_CHECK_KINDS if k not in text]`（`:200`）——今天靠子串过（`c_analysis_runs` 在 `agent_prompts.py:1023/1138/1140` 的散文里） | 改成"逐字清单解析出的集合 == `set(LEG_CHECK_KINDS)`"，并把该档补进两处镜像 |
| CC-06 | `tests/test_review_acceptance.py`（整文件）+ `tests/test_ledger_charging.py:33` | 模块删除后 import 失败 | 与模块同批删/改 |
| EE-05 进第八格 | `tests/test_conductor_tools.py:101-115` | `missing = [name for name in CL.DEFAULT_CHECKS if name not in text]`（`:113`）、`"五条" not in text`（`:115`） | 工具描述同步加第八格 |
| EE-10 | 无直接测试 | —— | 合并后 `tests/test_closing_gate.py:1800/1827/1860` 三条 `reviewed_current_rows` 判据要走新入口 |

### 6.2 每条收紧配的负控（测试名 + 断言；**要求改前必红**）

| 条目 | 负控测试名（建议） | 断言 | 改前必红的理由 |
|---|---|---|---|
| E-04 | `test_an_na_row_cannot_silence_an_automatic_branch` | 有 stale 签名的稿 + 表里写 `{"kind":"reviewed_current_rows","na":true,"note":"x"}` ⇒ `acceptance == "fail"` 且 detail 含"现行版本没有被审校记录钉住" | 今天这条会 `pass`（真机 `p5-review-t17` 已用内存复算证实：+3 行 `na` ⇒ `pass`） |
| E-04 | `test_the_four_auto_branches_read_the_ledger_not_the_table` | 表里不写那四档时，四条分支的 `detail` 键（`stale_signoffs`/`empty_section_docs`/`mismatches`/`derived_rows`）都要出现 | 今天分支只在"表里没有该 kind"时跑，没有统一的四键 |
| E-05 | `test_a_smaller_min_cannot_lower_the_kinds_own_threshold` | `research_questions` 3 行、`outcome=ok` 的检索 1 条、行里写 `"min":1` ⇒ 该行 `ok is False` 且 `min_overridden.effective == 3` | 今天 `:1213` 的"显式优先"让它 `ok is True`（41-F 探针 F 已复现） |
| E-05 | `test_the_citation_denominator_comes_from_the_read_only_baseline` | 主稿 1 条 `\bibitem`、基线 3 条、台账 1 条 ⇒ `ok is False`、`denominator_from == "source/main.tex"` | 今天分母取主稿（`:577`）⇒ 读成 1 并 `ok is True` |
| E-05 | `test_a_whitespace_only_change_is_not_an_edit` | 主稿与基线只差空白 ⇒ `got == 0` | 今天比 sha ⇒ `got == 1` |
| E-06 | `test_a_section_name_in_the_preamble_does_not_count_as_a_section` | 正文只写"本文按一、任务与范围……九、诚实边界组织"，无 `##` 标题 ⇒ `fail` 且 `missing_sections` 有 9 项 | 今天 `:1920-1921` 会判 `pass`（41-F B7 的探针形态） |
| E-06 | `test_an_empty_section_body_is_not_a_section` | 九个 `## 一、…` 标题、每节 body 为空 ⇒ `fail` 且 `empty_sections` 有 9 项 | 今天只看节名 ⇒ `pass` |
| E-06 | `test_the_attachment_triple_is_judged_not_just_read` | 缺 `origin=own_result` ⇒ `fail`，`missing_attachment_fields == ["origin=own_result"]` | 今天 `has_attach` 只进读数不参与 `problems`（`:1923/1927`） |
| E-08 | `test_editing_the_acceptance_table_does_not_drift_the_anchor` | 渲染锚 → 改 `ACCEPTANCE-CHECKS.json` → `check_package` 仍 `consistent`；含该文件的**老锚**也 `consistent` | 今天实测 `drifted`（`p5-review-t17`，§2.4） |
| CC-05 | `test_a_leg_that_needs_the_baseline_is_not_applicable_not_the_whole_cell` | 研究型 + 表里 11 行、首行 `manuscript_edited` ⇒ `rows` 有 11 条读数、首行 `not_applicable is True`、`acceptance` 由其余行决定 | 今天 `rows == 0` 且整格 `unknown`（`p6i` 真机） |
| CC-06 | `test_the_report_shape_criterion_lives_in_exactly_one_module` | `sys.modules` 里没有 `agentflow.reviewaccept`，且 `closing._SECTION_RE` 存在 | 今天两处都在 |
| F-06 | `test_a_missing_acceptance_table_is_generated_from_the_ledger` | 研究型、无 JSON 表 ⇒ `table_source == "generated"` 且逐行 `got`/`ok` 都在；生成不出可判行时仍红 | 今天走 `:1160-1186`，没有生成 |
| EE-05 | `test_the_artifact_ledger_must_match_the_disk` | 造一条 sha 与盘上不同的 `ARTIFACTS.jsonl` 记录 ⇒ 新档 `got >= 1` 且该行 `ok is False` | 今天没有这一档 |
| EE-10 | `test_the_two_ledgers_share_one_reader` | `artifacts.read_ledger` 与 `signatures.read_ledger` 同源；`reviewed_current_rows` 读数含 `ledger_module` | 今天两份实现 |

**负控纪律**（`draft/45:83`）：判据用**独立口径**算（例如直接读台账再数一遍），不抄实现里的表达式——否则实现错、负控也跟着错。

### 6.3 真机回放（可复算命令 + 逐格预测）

**六条命令都已在本机实跑通过，逐条单行可直接粘贴（只读，不改盘）：**

```powershell
cd D:\Incubator\agentflow
$env:PYTHONPATH="src"; $env:PYTHONIOENCODING="utf-8"

# 1) 七格逐格（六格回放集的改前基线）
python -B -c "import pathlib,json; from agentflow import closing as CL; from agentflow.store import Store; [print(n, json.dumps(CL.check_closing(Store(pathlib.Path('projects')/n), project_dir='.', report_path='out/review/REPORT.md').status, ensure_ascii=False)) for n in ['p8e-fermat-shorter-proof','p8f-fermat-shorter-proof','p8g-fermat-shorter-proof','p7b-open-questions','p6q-research-from-zero','p5-review-t17']]"

# 2) 33 份验收表逐格（改前基线：32 fail / 1 unknown / 0 pass）
python -B -c "import pathlib; from agentflow import closing as CL; from agentflow.store import Store; [print(p.parents[2].name, CL.check_closing(Store(p.parents[2]), project_dir='.', checks=('acceptance',)).status.get('acceptance'), [f.code for f in CL.check_closing(Store(p.parents[2]), project_dir='.', checks=('acceptance',)).findings]) for p in sorted(pathlib.Path('projects').glob('*/out/paper/ACCEPTANCE-CHECKS.json'))]"

# 3) 逐档可读性（30 档 x 33 工作区；'ok' 换成 try/except 里的类型名就是在数抛错的档）
python -B -c "import pathlib; from agentflow import closing as CL; from agentflow.store import Store; [print(p.parents[2].name, k, (lambda s: (CL._leg_reading(s,k,p.parents[2])[0],'ok'))(Store(p.parents[2]))) for p in sorted(pathlib.Path('projects').glob('*/out/paper/ACCEPTANCE-CHECKS.json')) for k in CL.LEG_CHECK_KINDS]"

# 4) 锚（32 份，含 10 份把验收表收进去的）
python -B -c "import pathlib,json; from agentflow import renderanchor as RA; [print(p.parents[2].name, 'ACCEPTANCE-CHECKS.json' in (json.loads(p.read_text(encoding='utf-8')).get('files') or {}), RA.check_package(str(p.parents[2]))['verdict']) for p in sorted(pathlib.Path('projects').glob('*/out/paper/RENDER-ANCHOR.json'))]"

# 5) 报告形状（46 份）：附件三件套缺哪些
python -B -c "import pathlib; from agentflow import closing as CL; [print(p.parents[2].name, [f for f in CL.ATTACHMENT_FIELDS if f not in p.read_text(encoding='utf-8')]) for p in sorted(pathlib.Path('projects').glob('*/out/review/REPORT.md'))]"

# 6) 产物台账完整性（EE-05；根 A 1387 ok / 根 B 2599 ok + 589 changed）
python -B -c "import pathlib,collections; from agentflow import artifacts as A; [print(p.name, dict(collections.Counter(str(v.get('status')) for v in A.verify_entries(p, A.read_ledger(p)[0])))) for p in [q for q in [pathlib.Path('projects'), pathlib.Path(r'D:\Incubator\projects')] for q in q.iterdir() if (q/'ARTIFACTS.jsonl').is_file()]]"
```

**逐格预测（六格回放集；`--` 表示不变）：**

| 工作区 | 改前七格 | E-04 | E-05 | E-06 | E-08 | CC-05 | F-06 | 改后 `acceptance` 的原因变化 |
|---|---|---|---|---|---|---|---|---|
| `p8e` | `pass×6 + acceptance fail` | -- | -- | -- | -- | -- | -- | 同改前（fail） |
| `p8f` | 同上 | -- | -- | **`report_shape: pass→fail`**（缺 `origin=own_result`/`依据`） | -- | -- | -- | fail（多一条 report_shape 红） |
| `p8g` | 同上 | -- | -- | -- | -- | -- | -- | 同改前（fail） |
| `p7b` | 同上 | --（真表没写那 4 档） | -- | -- | -- | -- | -- | 同改前（fail） |
| `p6q` | 同上 | -- | -- | **`report_shape: pass→fail`**（缺 `origin=own_result`/`sha`） | -- | -- | -- | fail（多一条 report_shape 红） |
| `p5-review-t17` | `pass×6 + acceptance fail`（anchor 维 `consistent`） | -- | -- | -- | --（10 份含表的老锚保持 `consistent`） | -- | -- | 同改前（fail） |
| `p6i`（第 7 格，CC-05 用） | `acceptance=unknown`、`rows=0` | -- | 该行 `not_applicable` | -- | -- | **`rows: 0→11`，`unknown→fail`** | -- | 由"没查成"变"查过了、缺覆盖面与 `P10`" |

**应当从 pass 变 fail 的格子与理由：**
1. `p8f` / `p6q` 的 `report_shape`——报告确实缺了附件三件套里的一到两件，旧判据"算了不判"把它们读成通过（"算了不判 = 假读数"）。
2. `p6i` 的 `acceptance`——`unknown` → `fail`：三态里两者都不算通过，但 `fail` 留下了 11 行读数。
3. （**仅在被改过表的场景**）`p7b` / `p8g` / `p5-review-t17` 追加 3–6 行 `na` 后会从 `pass` 回到 `fail`——这正是 E-04 要堵的洞，不是回放里的真实格子。

**应当保持不变的格子（负向确认）：** 六格的 `anchor`（含 `p5-review-t17` 的 `consistent`）、`contradictions`、`load_bearing`、`user_pending`、`substance` 全不变；`acceptance` 六格全 `fail`。**E-04/E-05/E-08 在 33 份真表上都是 0 处翻转**——这是"收紧不误伤历史"的核心证据。

### 6.4 不可逆点

1. **历史验收表的可比性。** 33 份表 / 204 行今天读出的 `got` 是**旧口径下的数**。S-05 的三档、E-05 的分母换基线、CC-05 的第四态都会改变"同一份表、同一个工作区、不同趟次读出的数"。按 `draft/45:12`：**每改一次口径必须在 `draft/44` 那一行写下"从哪一趟起口径变了"**。建议同批在 `readings["acceptance"]` 里落一个 `"reading_version"`（今天没有），并以 `p8g`（唯一覆盖面 8/8 齐的工作区）作口径锚点。
2. **`kind` 取值是磁盘契约。** 30 档的**名字**不能删、不能改名（204 行历史表按字面引用它们）；CC-03 只能加分组标注，"按工作区分成两张表"会让一半历史行变成词表外 ⇒ 整表 unknown（比 CC-05 更重的不可逆面）。
3. **锚的 `files` 集合是逐字节记录的。** E-08 的过滤必须**两侧对称**；只过滤 `files_now` 一侧会让 10 份老锚立刻 `drifted`，而"重渲染"会改写 `RENDER-ANCHOR.json` 并**追加** `BUILD-HISTORY.jsonl`（回滚恢复不了）。
4. **`na` 与"缺基线"的语义已经写进提示词与历史表。** `agent_prompts.py:1107-1110` 逐字写着"算不出来 ⇒ 整张表没查成"，`p6i` 就是照这条写的。CC-05 改成"不适用"之后，**提示词那一段必须同批改**，否则人与门两套口径。
5. **签名台账与产物台账的分家。** 两台账钉的是不同哈希空间（§2.11 的 `49404e4d…` vs `dc8a062c…`），历史行无法机械合一 ⇒ **只合并"读法"，不合并"台账本体"**。

### 6.5 判定为不可行 / 高风险的项（附证据）

| 项 | 判定 | 证据 |
|---|---|---|
| S-05 腿 2 单独上线 | **不可行** | `statements` 138 行里 `own_result` 13 行，`bits_from_row` 的 `grade` **全部** `conjecture`（`pre_theorem` 6 行全是 `external_lit`）⇒ 这一档恒为 0，只会制造一条恒红判据（41-F B13） |
| S-05 腿 3 按"直接读字段"实现 | **不可行** | `schema.py:2394` 的 `documents` 只有 `sections/claims/open_problems`；`experiments.for_question_id` 54/217 有值、`conjectures` 0/66、`statements` 0/138 ⇒ 只能走引用链或先改 schema（禁改区） |
| CC-03 按类型分两张表 | **高风险，不建议** | `kind` 是 204 行历史表的字面契约；分区会让一半历史行变词表外 ⇒ 整表 unknown（`:1246-1253`） |
| E-04 顺带收紧"`na` 不算覆盖面 `marked`" | **高风险，须单独裁定** | 会把 p7b `B1`/`D2`、p8d `A2`、p8g `C10` 四行**合法** `na` 一起变红（p7b 的"算或造"整环正是被 `B1` 一行覆盖，§3.4）——那是 D49 明确要保留的出口 |
| `closing.py` 是否禁改区 | **不在 FC-27 清单里** | `.noai-paths` 逐条比对后无 `closing.py`（`draft/44:167` 的 E-16 同此说）；`renderanchor.py`/`signatures.py`/`artifacts.py` 也都不在清单里 ⇒ E-08/E-07/EE-10 可按普通改动走，仍建议先改后报备 |
| `resolve_under_workspace` 越界（41-F B14） | **本次不改** | 它影响 `anchor`/`acceptance`/`manuscript_edited`/`citation_records_vs_bibitems`/`report_shape` 五格的读数来源，属 E-13 家族，与本 11 条正交 |

---

## 7. 本文件"不做"的部分

1. **不改任何代码，不改任何工作区文件。** 只写 `draft/46-施工级调查-04-closing.md`；所有"改后"结论要么来自真机只读调用，要么来自**内存复算**（把 `closing.Path` 换成"只对 `ACCEPTANCE-CHECKS.json` 返回内存字符串、其余委托真 `Path`"的包装类），盘上一个字节没动。
2. **不跑模型、不跑网络、不跑全量 pytest。** "哪些测试会红"是**静态判读**（读测试源码 + 读实现判据），每条都给了 `file:line` 与红色断言原文；施工时必须先跑一遍确认。
3. **不裁定条目。** `draft/44` 的裁决建议原样引用；本文件只答"改哪儿、怎么改、代价、会红什么"。四处需人拍板的分叉已点名：E-04 的覆盖面 `marked`、S-05 腿 3 的 schema 字段、EE-05 是否进第八格、CC-03 的分组形态。
4. **不覆盖 E-07（签名覆盖 `revised`）/ E-15（statusreport 接管现场读数）/ CC-01 / CC-02 / CC-09。** 它们与本 11 条有依赖（§5.1 已标），但判据本体不在 `closing.py` 或属另一批。
5. **不覆盖根 B 的验收表。** 该根 **0 份** `ACCEPTANCE-CHECKS.json` ⇒ 所有"33 份表"的统计**只代表根 A**；根 B 的 8 份 `ARTIFACTS.jsonl` 只用于 EE-05 的完整性读数（§2.10）。
6. **不核 3 档的语义边界。** `reviewed_current_rows` / `document_body_rows` / `document_claim_rows`（以及 `claim_evidence_fit_rows`）在 33 份真表里**一次都没被声明过**，所以"表里写出来时会怎样"没有真机样本；本文件只覆盖它们在自动分支路径上的读数。
7. **不核会话侧读数。** 回放用 `sid=None`（CLI 口径）⇒ 六格 `user_pending` 全 `pass`；`conductor.closing` 走的是 `sid=<这一趟>`，两处差异（`draft/37` §63 的假绿）本次未在 `projects/*/sessions` 上逐趟核对。
8. **不给最终补丁。** 每条的"改成什么"是**接口级伪码**（新分支条件 / 新字段 / 新档位 / 新读数键），不是可粘贴实现；实现时必须按 §6.2 先写负控、确认改前必红，再改实现。
