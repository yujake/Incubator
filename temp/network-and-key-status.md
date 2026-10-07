# 出网与密钥现状（2026-09-26，主控亲自实测）

## 1. 互联网出网：**通**（推翻 `draft/24` §7 / `draft/25` §9.5 记的"本机零出网"）

原始输出（`temp/net-probe.txt`，命令：`python temp/_net_probe.py`，工作目录 `agentflow`）：

```
exit=0
http_status=401
body_head='Authentication Fails (governor)'
```

判读：`GET https://api.deepseek.com/v1/models`（**不带** `Authorization` 头）收到
服务端 **401 + 服务端自己生成的 JSON 文案**。这同时证明三件事：
1. DNS 解析到了真实主机；2. TLS 握手成功（httpx 用的是自己的 CA bundle，不经 Schannel）；
3. HTTP 往返拿到了服务端的语义响应（不是 MITM 占位页 —— 占位页不会说
   "Authentication Fails"）。

`Test-NetConnection api.deepseek.com:443` = `True`；`1.1.1.1:443` = `False`
（后者只说明那个 IP 的 443 被挡，不构成"零出网"）。

⇒ **`-m network` 的 8 条用例"因为本机不能出网所以从没验过绿"这条免责，今天不成立了。**
它们该被重跑一次（尤其 `tests/test_providers_online.py`；它打的是 crossref/openalex，
是否可达要另测，不许把"deepseek 通"外推成"所有域都通"）。

### 1b. 各 provider 域逐个探（`temp/net-probe-domains.txt`）

| 域 | 结果 | 判读 |
|---|---|---|
| `api.crossref.org` | **200**，1734 字节 | 通，且返回真内容 |
| `api.openalex.org` | **200**，8068 字节 | 通 |
| `export.arxiv.org` | **200**，1844 字节 | 通（http，非 https） |
| `api.semanticscholar.org` | **429**，174 字节 | 可达但被限流（**不是**"不可达"） |
| `api.unpaywall.org` | **404**，207 字节 | 可达（404 是我给的假 DOI，服务端语义响应） |
| `github.com`（EasyOCR 模型源） | **EXC `CERTIFICATE_VERIFY_FAILED`**（`unable to get local issuer certificate`） | **不通**：TLS 链验证失败 |

⇒ 所以"出网"这件事**要分域说**，不许一句话概括：
- Crossref / OpenAlex / arXiv：通 ⇒ `-m network` 里依赖它们的用例**可以验绿**；
- Semantic Scholar：限流 ⇒ 只能验"限流被正确处置"，不能验"检索成功"；
- **github.com：证书链验证失败** ⇒ `ocr.run` 首次构造 easyocr Reader 的 ~100MB 模型
  **下不下来**。这条对"企业级交付"是硬约束：装机环境要么预置模型，要么换镜像源
  （并且它是 `ocr.run` 声明 `egress+write_local` 的实证依据）。

## 2. 模型密钥：**本机没有**

- `Get-ChildItem env:` 里没有 `AGENTFLOW_MODEL_API_KEY`（也没有 `DEEPSEEK_API_KEY` 等别名）；
  与 `DEEPSEEK`/`API_KEY` 沾边的只有 DSH 自己的 `DSH_HOME` / `DSH_SESSION_ID` / `DSH_SHELL` / `DSH_WEB_URL`。
- 代码侧口径（`src/agentflow/modelgw.py:68` `ENV_KEY = "AGENTFLOW_MODEL_API_KEY"`、
  `spec_from_env` 的 docstring）：**密钥只从环境变量读，刻意不落盘**
  （"密钥一旦落盘就会进版本库与备份"）。
- ⇒ 大规模真调（`D:\books` 文献 + 真 API）现在**跑不了**，缺的不是代码而是那一件事：
  由人把密钥注入到执行环境（`$env:AGENTFLOW_MODEL_API_KEY='...'` 或密钥管理系统）。
  没有它时网关**不发起任何网络请求**（`ModelSpec.configured` 的判据），
  所以"没 key"不会伪装成"调用失败" —— 这是好事，但它也意味着
  **"挂上 key 能跑通"这句话目前仍未核实**。

## 3. 这一条对验收口径的影响

`draft/25` 的"未核实面"里原先写着"真实 key/provider 端到端"与"`-m network` 8 条"。
现在这两条的**阻塞原因不同了**：
- `-m network`：可以查（出网通）⇒ 应由机器跑出来，不许再当"没查成"；
- 真实 key 端到端：缺密钥 ⇒ 仍然只能写"未核实"，并且**必须**写成
  "缺 `AGENTFLOW_MODEL_API_KEY`（人注入）"，而不是"环境不支持"。

## 4. `-m network` 8 条：**已跑，8 passed**（2026-09-26 02:42:12 → 02:42:41 观测）

```
start=2026-09-26T02:42:12.7676711+08:00     （命令：python -m pytest -m network -q -p no:cacheprovider）
........                                                                 [100%]
8 passed, 1873 deselected in 28.42s
exit=0
```

采集清单（`temp/network-collect.txt`，观测 02:42:0x）：**8/1881 collected（1873 deselected）**，
全部在 `tests/test_providers_online.py`：
`test_crossref_all_modes_do_not_400[broad|topical|precise]`、
`test_openalex_all_modes_return_something[broad|topical|precise]`、
`test_precise_results_are_on_topic`、`test_openalex_returns_wellformed_candidates`。

⇒ **"从未验过绿"这条免责可以注销了**（原始输出 `temp/pytest-network-run1.txt`）。
⚠️ 但要注意**它证明的是什么**：它证明的是"crossref / openalex 这条路真的能跑通"，
**不**证明"所有 provider 都能跑通"（Semantic Scholar 实测 429、github 证书验证失败）。
