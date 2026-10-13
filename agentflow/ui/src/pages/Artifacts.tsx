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
import { Table, cell, plain } from "../components/Table";
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
          <span class="mono">out/secretary/</span> 下的 <span class="mono">*.jsonl</span>
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
            empty="暂无产物台账行。"
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
              { key: "task_id", title: "任务" },
              { key: "at", title: "登记时间", render: (r) => cell(r.at) },
              // R93 体检：这里原来还有一列「退出码」。台账的格式里**有** `exit_code`
              // 这一栏（`artifacts.FIELDS`），但真机上登记的都是 `out/tasks/` 下那些
              // "任务结果文件"——那种东西没有退出码，于是整列恒 `unknown`
              // （本机实测：t1-review-2 的 6 行全是）。退出码真正的落点是「证据链 →
              // 实验」那一张表（`experiments.exit_code`，那里是真读数），所以这一列撤掉。
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
              { key: "summary", title: "摘要", render: (r) => plain(r.summary) },
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
              { key: "body", title: "正文（截断）", render: (r) => plain(clip(r.body)) },
            ]}
          />
        )}
      </Card>

      <Card
        title="验收表的机器可判行"
        subtitle={
          art.checks_tri === "not_applicable"
            ? "这一趟没有这份表"
            : `${art.checks.length} 行`
        }
        right={<TriState tri={art.checks_tri} label="checks" />}
      >
        {/* R93 体检：这张卡原先在"没有这份文件"时照样铺满一张表（每格 `不适用`），
            读者看到的是"一屏不适用"，而不是"这一趟没走到这一步"。现在按三态分档：
            没这份表 ⇒ 一句话说清它是谁写的、什么时候会有；有才画表。 */}
        {isUnreadable(art.checks_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : art.checks.length === 0 ? (
          <span class="readings">
            这一趟没有 <span class="mono">out/paper/ACCEPTANCE-CHECKS.json</span> ——
            它是收工那一步（G 的收工门 / `closing`）写给论文包看的机器可判行，
            还没走到那一步就没有它（不是"0 行"，也不是没查成）。
          </span>
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
        subtitle={
          art.style_tri === "not_applicable"
            ? "M 还没声明体例"
            : `${art.style.sections.length} 节`
        }
        right={<TriState tri={art.style_tri} label="REPORT-STYLE" />}
      >
        {/* 体例是 M 在收工前自己声明的那一份（`out/review/REPORT-STYLE.json`）。
            它缺席 = "M 还没声明"，不是"没读到"—— 这一档要在页面上说出来。 */}
        {isUnreadable(art.style_tri) ? (
          <span class="empty">这一栏没查成（不是"0 节"）。</span>
        ) : art.style.sections.length === 0 ? (
          <span class="readings">
            M 还没声明交付说明的体例（<span class="mono">out/review/REPORT-STYLE.json</span>
            不在盘上）。它在收工前由主控写；写完这一栏会逐节列出来。
          </span>
        ) : (
          <ol class="list">
            {art.style.sections.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        )}
      </Card>

      {/* R93 体检：原来这里还有一张「六件产物」卡（`run-manifest.json` /
          `model-transcript.jsonl` / `evidence.json` / `claims.json` / `cost.json` /
          `report.md`）。那六件属于 **`agentflow project run` 那条流水线**
          （`out/run-N/` 下的运行产物），审阅型项目里一张都不会有 ⇒ 整卡恒 `不适用`
          （本机实测：t1-review-2 六件全是 not_applicable）。所以整卡改成一句导引；
          真有那个目录时（`project run` 跑过的项目）照旧画表。 */}
      {art.run_dir === "" ? (
        <Card title="六件产物（属于另一条流水线）">
          <div class="readings">
            六件产物（<span class="mono">run-manifest.json</span> /
            <span class="mono">model-transcript.jsonl</span> /
            <span class="mono">evidence.json</span> / <span class="mono">claims.json</span> /
            <span class="mono">cost.json</span> / <span class="mono">report.md</span>）
            是 <span class="mono">agentflow project run</span> 那条流水线落在
            <span class="mono">out/run-N/</span> 下的运行产物。本项目是审阅型，
            没有那个目录 —— 这一趟的产物看上面的台账、交接手稿与
            <span class="mono">out/paper/</span>。
          </div>
        </Card>
      ) : (
        <Card
          title="六件产物"
          subtitle={art.run_dir}
          right={<TriState tri={art.products_tri} label="products" />}
        >
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
                  render: (r) =>
                    r.lines === null ? "unknown（非 JSONL，按设计没有行数）" : String(r.lines),
                },
                { key: "sha256", title: "sha256", render: (r) => cell(r.sha256) },
                { key: "tri", title: "三态", render: (r) => <TriState tri={r.tri} /> },
              ]}
            />
          )}
        </Card>
      )}

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
            empty="tasks 台账为空。"
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
 processed 三态、download.status/bytes/sha256、matched 那几栏要新增一条
          只读端点才能给读数 —— 页面不许自己编一个数。
        </div>
      </Card>
    </>
  );
}
