/*
 * 产物（`draft/74 §3.4` 逐行落）。
 *
 * 输入：`api.getArtifacts()` → `ArtifactsView`（B 线的 `readers.artifacts_face`）。
 * SSE：`state`。
 *
 * 七栏，每栏自己一个三态：
 *
 * 1. 产物台账 `ledger`：路径 / `producer` / `sha256` / `exit_code` / `kind`，
 *    外加 `ledger_verify`（台账里钉的 sha 与盘上**现在**这一版是不是同一版）；
 * 2. 交接手稿 `handoffs`：`body` 截断显示（后端 `webui/state.py` 的 `CLIP=400`
 *    是同一口径，这里跟它对齐，长文不许把表格撑爆）；
 * 3. 验收表的机器可判行 `checks`；
 * 4. 报告体例 `style.sections`；
 * 5. 六件产物 `products`（裁定 J2：真机无样本 ⇒ 夹具造，页面标明"夹具样本"）；
 * 6. 任务产物 `tasks`（`out/tasks/t-*.json` 与 `tasks` 台账行对应）；
 * 7. 文献库 `library` —— **如实标注的缺口**：`draft/74` 说这一栏从产物面读
 *    `store.rows("literature")`，而 `ArtifactsView` 里没有这一栏，今天也没有别的
 *    端点给它 ⇒ 渲染 `not_applicable` 并写明，不编数。
 */
import type { ComponentChildren } from "preact";

import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { Table, cell } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";

/** 长文截断（与后端 `webui/state.py` 的 `CLIP` 同一口径：两头留、中间省）。 */
const CLIP = 400;

function clip(text: string): string {
  if (text.length <= CLIP) {
    return text === "" ? "unknown" : text;
  }
  return `${text.slice(0, CLIP - 40)} …（共 ${text.length} 字，已截断）`;
}

/** 台账那一行在盘上还对得上吗（`artifacts.STATUSES` 的五档词，一个都不折成布尔）。 */
function verifyBadge(status: string): ComponentChildren {
  if (status === "ok") {
    return <Badge kind="badge-pass" text="对得上" />;
  }
  if (status === "missing") {
    return <Badge kind="badge-na" text="文件不在盘上" />;
  }
  if (status === "changed") {
    return <Badge kind="badge-fail" text="盘上已改版" />;
  }
  if (status === "not_a_file") {
    return <Badge kind="badge-fail" text="台账指的是一个目录" />;
  }
  if (status === "unreadable") {
    return <Badge kind="badge-unknown" text="读不出来（没查成）" />;
  }
  return <Badge kind="badge-unknown" text={status === "" ? "unknown" : status} />;
}

export function Artifacts() {
  const face = useFace(() => api.getArtifacts());

  if (face.data === null) {
    return (
      <Card
        title="产物"
        tone={face.problem === "" ? "plain" : "problem"}
        right={face.problem === "" ? null : <TriState tri="unreadable" reason={face.problem} label="产物面" />}
      >
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
      </Card>
    );
  }

  const art = face.data;

  return (
    <>
      <Card
        title="产物"
        subtitle={`七栏 · 整面 tri=${art.tri}`}
        tone={isUnreadable(art.tri) ? "problem" : "plain"}
        right={<TriState tri={art.tri} label="产物面" reason={art.reason} />}
      >
        <div class="readings">
          台账 <span class="mono">ARTIFACTS.jsonl</span> · 交接{" "}
          <span class="mono">manuscripts/handoffs.jsonl</span> · 验收表{" "}
          <span class="mono">out/paper/ACCEPTANCE-CHECKS.json</span> · 体例{" "}
          <span class="mono">out/review/REPORT-STYLE.json</span> · 秘书{" "}
          <span class="mono">out/secretary/*.jsonl</span>
        </div>
      </Card>

      <Card
        title="产物台账"
        subtitle={`${art.ledger.length} 行`}
        right={<TriState tri={art.ledger_tri} label="ledger" />}
      >
        {isUnreadable(art.ledger_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : (
          <Table
            rows={art.ledger}
            empty="台账 0 行（读到了，里面是空的 —— 这一趟还没登记过产物）。"
            columns={[
              { key: "path", title: "路径" },
              { key: "producer", title: "谁产出的" },
              { key: "kind", title: "类别" },
              { key: "sha256", title: "sha256" },
              {
                key: "bytes",
                title: "字节",
                render: (r) => String(r.bytes),
              },
              {
                key: "exit_code",
                title: "退出码",
                render: (r) => (r.exit_code === null ? "unknown" : String(r.exit_code)),
              },
              { key: "task_id", title: "任务" },
              { key: "at", title: "登记时间", render: (r) => cell(r.at) },
            ]}
          />
        )}
      </Card>

      <Card
        title="台账对账（台账里钉的 sha vs 盘上现在这一版）"
        subtitle={`${art.ledger_verify.length} 行`}
        right={<TriState tri={art.ledger_verify_tri} label="verify_entries" />}
      >
        {isUnreadable(art.ledger_verify_tri) ? (
          <span class="empty">这一栏没查成（不是"全部对得上"）。</span>
        ) : (
          <Table
            rows={art.ledger_verify}
            empty="没有可对账的台账行（台账是空的）。"
            columns={[
              { key: "path", title: "路径" },
              { key: "sha256", title: "台账里的 sha" },
              { key: "sha256_now", title: "盘上现在的 sha" },
              { key: "status", title: "结论", render: (r) => verifyBadge(r.status) },
              { key: "producer", title: "谁产出的" },
            ]}
          />
        )}
      </Card>

      <Card
        title="交接手稿 / 账本"
        subtitle={`${art.handoffs.length} 条`}
        right={<TriState tri={art.handoffs_tri} label="handoffs" />}
      >
        {isUnreadable(art.handoffs_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : (
          <Table
            rows={art.handoffs}
            empty="交接台账 0 条（读到了，里面是空的）。"
            columns={[
              { key: "id", title: "编号" },
              { key: "sender", title: "发" },
              { key: "to", title: "收" },
              { key: "summary", title: "摘要" },
              { key: "refs", title: "引用" },
              { key: "sha256", title: "sha256" },
              { key: "sid", title: "会话", render: (r) => cell(r.sid) },
              { key: "task_id", title: "任务", render: (r) => cell(r.task_id) },
              { key: "format", title: "格式" },
              {
                key: "bytes",
                title: "字节",
                render: (r) => String(r.bytes),
              },
              { key: "body", title: "正文（截断）", render: (r) => clip(r.body) },
            ]}
          />
        )}
      </Card>

      <Card
        title="验收表的机器可判行"
        subtitle={`${art.checks.length} 行`}
        right={<TriState tri={art.checks_tri} label="checks" />}
      >
        <div class="readings">
          真机样本是 8 行 C1–C8；夹具造的是 3 行（`tests/conftest.py` 的
          <span class="mono"> ACCEPTANCE_CHECKS_SAMPLE</span>）—— 判据与页面都标明"夹具样本"。
        </div>
        {isUnreadable(art.checks_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : (
          <Table
            rows={art.checks}
            empty="验收表还没写（合法初态：这一趟还没声明机器可判行）。"
            columns={[
              { key: "id", title: "编号" },
              { key: "name", title: "名字" },
              { key: "kind", title: "判据类型" },
              {
                key: "min",
                title: "下限",
                render: (r) => String(r.min),
              },
              { key: "note", title: "备注" },
            ]}
          />
        )}
      </Card>

      <Card
        title="报告体例兑现"
        subtitle={`${art.style.sections.length} 节`}
        right={<TriState tri={art.style_tri} label="REPORT-STYLE" />}
      >
        {isUnreadable(art.style_tri) ? (
          <span class="empty">这一栏没查成（不是"0 节"）。</span>
        ) : art.style.sections.length === 0 ? (
          <span class="empty">体例文件里没有声明任何一节（读到了，里面是空的）。</span>
        ) : (
          <ol class="list">
            {art.style.sections.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        )}
      </Card>

      <Card
        title="六件产物"
        subtitle={art.run_dir === "" ? "没找到 out/run-N/" : art.run_dir}
        right={<TriState tri={art.products_tri} label="products" />}
      >
        <div class="readings">
          {art.products_reason === "" ? "（裁定 J2：真机无样本 ⇒ 判据用夹具造，页面标明）" : art.products_reason}
        </div>
        {isUnreadable(art.products_tri) ? (
          <span class="empty">这一栏没查成（不是"六件都不在"）。</span>
        ) : (
          <Table
            rows={art.products}
            empty="六件产物一件都没有（读到了，里面是空的）。"
            columns={[
              { key: "name", title: "名字" },
              {
                key: "exists",
                title: "在不在",
                render: (r) => (
                  <Badge
                    kind={r.exists ? "badge-pass" : "badge-na"}
                    text={r.exists ? "在" : "不在"}
                  />
                ),
              },
              {
                key: "bytes",
                title: "字节",
                render: (r) => (r.bytes === null ? "unknown" : String(r.bytes)),
              },
              {
                key: "lines",
                title: "行数",
                render: (r) => (r.lines === null ? "unknown（非 JSONL，按设计没有行数）" : String(r.lines)),
              },
              { key: "sha256", title: "sha256", render: (r) => cell(r.sha256) },
              { key: "tri", title: "三态", render: (r) => <TriState tri={r.tri} /> },
            ]}
          />
        )}
      </Card>

      <Card
        title="任务产物"
        subtitle={`${art.tasks.length} 行`}
        right={<TriState tri={art.tasks_tri} label="tasks" />}
      >
        {isUnreadable(art.tasks_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : (
          <Table
            rows={art.tasks}
            empty="tasks 台账 0 行（读到了，里面是空的）。"
            columns={[
              { key: "task_id", title: "任务号" },
              { key: "role", title: "角色" },
              { key: "action", title: "动作" },
              { key: "called_by", title: "谁调的" },
              { key: "status", title: "状态" },
              { key: "outcome", title: "结局", render: (r) => cell(r.outcome) },
              {
                key: "usd",
                title: "花销",
                render: (r) => (r.usd === null ? "unknown" : `${r.usd.toFixed(6)} USD`),
              },
              { key: "detail", title: "说明", render: (r) => clip(r.detail) },
            ]}
          />
        )}
      </Card>

      <Card
        title="文献库（缺口）"
        right={
          <TriState
            tri="not_applicable"
            label="library"
            reason="draft/74 说这一栏从产物面读 store.rows('literature')，而 ArtifactsView 里没有这一栏，今天也没有别的端点给它"
          />
        }
      >
        <div class="readings">
          `processed` 三态、`download.status/bytes/sha256`、`matched` 那几栏要新增一条
          只读端点才能给读数 —— 页面不许自己编一个数。
        </div>
      </Card>
    </>
  );
}
