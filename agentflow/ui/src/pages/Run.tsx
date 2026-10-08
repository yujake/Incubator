/*
 * 一趟详情 —— 运行态（`draft/74 §3.2` 逐行落）。
 *
 * 输入两条端点 + 一次共享快照：
 *
 * - `api.getRun(sid)` → `RunView`（`runs` / `report` / `checkpoint`）；
 * - `api.getRunIndex()` → `RunIndexDrift`（裁定 O2：趟次索引与它对账的结论）；
 * - `live.snapshot` → 台账读数（`ledger`）与「轮次之外的零散事件」（`orphans` /
 *   `orphan_summary`）。
 *
 * SSE：`state` / `checkpoint` / `stop`（`live` 层订阅一次）。
 *
 * 三态纪律在这页上的落点（逐条对着 `draft/74 §3.2` 的八行）：
 *
 * - 花销有两个来源，**并排摆**：首选取检查点的 `spend`，第二读数取事件求和
 *   （`Σ runs[].usd` 与 `Σ runs[].unknown_usd`）。两边都读到时才谈"是否一致"；
 *   任一边没读到 ⇒ 那一格是"没查成"，不是"对上了"，更不是 0；
 * - `stop_reason` / `last_shape` 读不到就是 `unknown`，不写成空串；
 * - 交付说明走 `ReportTri`（`ok` / `missing` / `unknown`）那一套词表，
 *   与别处的 `computed / unreadable / not_applicable` 不互相顶替；
 * - 台账行数旁边**必须**带着 `tables_note` 那句"含顶趟行"；
 * - 轮次之外的零散事件单独一栏，**不许并进 runs**（后台那条既有的判据
 *   `test_events_outside_a_run_never_become_a_run` 守的就是这件事）。
 *
 * 两处**如实标注的缺口**（不是我漏做）：停机状态与检索腿那两栏，`draft/74` 写的
 * 输入是 `GET /api/state` 的 `stop` 与 `search_requests` 两个键，而 `snapshot()`
 * 的顶层键是公开面对账钉住的 10 个（`temp/_verify_w0.py`），那两个键不在其中，
 * 今天也没有别的端点给它们 —— 所以那两栏渲染成 `not_applicable` 并写明原因。
 */
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConfirmButton } from "../components/ConfirmButton";
import { Money } from "../components/Money";
import { Table } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace, useLive } from "../live";
import type { CheckpointSpendView, CheckpointView, RunRow } from "../types";

export interface RunProps {
  sid: string;
}

/** 检查点的花销子树（类型上是联合：读不到时后端给的是空对象）。 */
function spendOf(ck: CheckpointView | null): CheckpointSpendView | null {
  if (ck === null) {
    return null;
  }
  const s = ck.spend;
  if (typeof s === "object" && s !== null && "usd" in s && "calls" in s) {
    return s as CheckpointSpendView;
  }
  return null;
}

/** 事件求和（第二读数）：一次都没读到 `usd` ⇒ `null`（不是 0）。 */
function eventSum(runs: RunRow[]): { usd: number | null; unknown: number } {
  const known = runs.filter((r) => r.usd !== null);
  const unknown = runs.reduce((acc, r) => acc + r.unknown_usd, 0);
  if (known.length === 0) {
    return { usd: null, unknown };
  }
  return { usd: known.reduce((acc, r) => acc + (r.usd ?? 0), 0), unknown };
}

function text(value: string): string {
  return value === "" ? "unknown" : value;
}

export function Run(props: RunProps) {
  const live = useLive();
  const view = useFace(() => api.getRun(props.sid));
  const index = useFace(() => api.getRunIndex());

  if (props.sid === "") {
    return (
      <Card title="一趟详情" right={<TriState tri="not_applicable" reason="URL 里没有会话号" />}>
        <span class="empty">
          这一页要看的是 `/run/&lt;会话号&gt;`。会话号在首页的「会话概览」里点得进来。
        </span>
      </Card>
    );
  }

  if (view.data === null) {
    return (
      <Card
        title="一趟详情"
        subtitle={`会话 ${props.sid}`}
        tone={view.problem === "" ? "plain" : "problem"}
        right={
          view.problem === ""
            ? null
            : <TriState tri="unreadable" reason={view.problem} label="这一趟" />
        }
      >
        <span class="readings">
          {view.problem === "" ? "正在读盘……" : `读数没拿到：${view.problem}`}
        </span>
      </Card>
    );
  }

  const v = view.data;
  const runs = v.runs;
  const ckpt = v.checkpoint;
  const spend = spendOf(ckpt);
  const second = eventSum(runs);
  const sameAmount =
    spend !== null && second.usd !== null
      ? Math.abs((spend.usd ?? 0) - second.usd) < 1e-9
      : null;
  const ledger = live.snapshot === null ? null : live.snapshot.ledger;
  const orphans = live.snapshot === null ? null : live.snapshot.orphans;
  const orphanSummary = live.snapshot === null ? null : live.snapshot.orphan_summary;

  return (
    <>
      <Card
        title="一趟详情"
        subtitle={`会话 ${props.sid} · 盘上 ${v.path}`}
        tone={isUnreadable(v.tri) ? "problem" : "plain"}
        right={<TriState tri={v.tri} label="这一面" reason={v.reason} />}
      >
        <div class="readings">
          趟数 <span class="mono">{runs.length}</span> · 这一趟的原始读数（JSON）：
          <a href={`/run/${encodeURIComponent(props.sid)}`}>/run/{props.sid}</a>
        </div>
      </Card>

      <Card
        title="趟次索引（裁定 O2）"
        subtitle={index.data === null ? "还没读到" : `tri=${index.data.tri}`}
        tone={index.data !== null && index.data.tri !== "computed" ? "problem" : "plain"}
        right={
          index.data === null ? (
            <TriState tri="unreadable" reason={index.problem || "索引读数还没回来"} label="索引" />
          ) : (
            <TriState tri={index.data.tri} label="索引对账" reason={index.data.reason} />
          )
        }
      >
        {index.data === null ? (
          <span class="readings">{index.problem === "" ? "正在读盘……" : index.problem}</span>
        ) : (
          <>
            <div class="readings">
              可用 <span class="mono">{String(index.data.usable)}</span> · 索引里的会话{" "}
              <span class="mono">{index.data.sessions.length}</span> 场 · 索引本体{" "}
              <span class="mono">
                {index.data.index === null ? "unknown（没读成）" : `v${index.data.index.version}`}
              </span>
            </div>
            {index.data.tri !== "computed" ? (
              <div class="readings">
                <Badge
                  kind="badge-fail"
                  text={index.data.drift.length > 0 ? "索引与现算对不上" : "索引不可用（没建或读不出）"}
                />
                <span class="readings">
                  本页的趟次因此是回退现算的（`sessions.runs_in_session` 从会话文件现切），
                  索引不可信 —— 先把上面那一条理由处理掉。
                </span>
              </div>
            ) : null}
            {index.data.drift.length === 0 ? (
              <span class="empty">索引与事件现算结果逐趟一致（drift 是 0 条）。</span>
            ) : (
              index.data.drift.map((d, i) => (
                <div class="row drift" key={i}>
                  <span class="mono">{d}</span>
                </div>
              ))
            )}
          </>
        )}
      </Card>

      <Card title="时间线" subtitle={`${runs.length} 趟`}>
        {runs.length === 0 ? (
          <span class="empty">
            这一段会话里一趟都没有（读到了，里面是 0 趟 —— 不是「没查成」）。
          </span>
        ) : (
          <Table
            rows={runs}
            empty="这一段会话里一趟都没有。"
            columns={[
              { key: "start_index", title: "起始下标" },
              { key: "role", title: "角色" },
              { key: "task", title: "任务" },
              { key: "steps", title: "步数" },
              { key: "llm_calls", title: "模型调用" },
              {
                key: "usd",
                title: "花销（事件求和）",
                render: (r) => <Money usd={r.usd} unknownCalls={r.unknown_usd} />,
              },
              { key: "last_shape", title: "最后一步形态", render: (r) => text(r.last_shape) },
              { key: "stop_reason", title: "停止理由", render: (r) => text(r.stop_reason) },
              { key: "waiting_on", title: "在等哪个问题" },
              { key: "events_in_run", title: "趟内事件" },
              { key: "start_ts", title: "起" },
              { key: "end_ts", title: "止", render: (r) => text(r.end_ts) },
            ]}
          />
        )}
      </Card>

      <Card
        title="花销（两个来源并排）"
        tone={sameAmount === false ? "problem" : "plain"}
        right={
          sameAmount === null ? (
            <TriState
              tri="unreadable"
              label="两处是否一致"
              reason="有一个来源没读到（检查点或事件求和）⇒ 这一格没查成，不是「一致」"
            />
          ) : (
            <Badge
              kind={sameAmount ? "badge-pass" : "badge-fail"}
              text={sameAmount ? "两处一致" : "两处不一致"}
            />
          )
        }
      >
        <div class="row">
          <span class="caption">首选：检查点</span>
          {spend === null ? (
            <span class="mono">unknown</span>
          ) : (
            <Money
              usd={spend.usd}
              unknownCalls={spend.unknown_usd_calls}
              calls={spend.calls}
              tokensIn={spend.tokens_in}
              tokensOut={spend.tokens_out}
            />
          )}
        </div>
        <div class="row">
          <span class="caption">第二读数：事件求和</span>
          <Money usd={second.usd} unknownCalls={second.unknown} />
        </div>
        <div class="readings">
          检查点{" "}
          <span class="mono">
            {ckpt === null
              ? `unknown（${v.checkpoint_reason === "" ? "没读到" : v.checkpoint_reason}）`
              : `${ckpt.role} / step ${ckpt.step} / ${ckpt.at}`}
          </span>
        </div>
      </Card>

      <Card
        title="交付说明"
        subtitle="out/review/REPORT.md"
        right={<TriState tri={v.report.status} label="交付说明" />}
      >
        {v.report.status === "ok" ? (
          <pre class="mono pre">{v.report.text}</pre>
        ) : (
          <span class="empty">
            {v.report.status === "missing"
              ? "还没有交付说明（合法初态：这一趟还没写它 —— 不是「没查成」）。"
              : `交付说明读不出来（没查成，不是空报告）：${v.report.text}`}
          </span>
        )}
      </Card>

      <Card title="台账" subtitle="第二个独立读数">
        {ledger === null ? (
          <TriState tri="unreadable" label="台账" reason="共享快照还没读到" />
        ) : (
          <>
            <div class="readings">
              事件{" "}
              <span class="mono">{ledger.events === null ? "unknown" : ledger.events}</span> 条 ·
              tasks 行数{" "}
              <span class="mono">{ledger.tables === null ? "unknown" : ledger.tables}</span> · 落点{" "}
              <span class="mono">{ledger.path}</span>
            </div>
            <div class="readings">{ledger.tables_note}</div>
            {ledger.note === "" ? null : <div class="readings">{ledger.note}</div>}
          </>
        )}
      </Card>

      <Card
        title="轮次之外的零散事件"
        subtitle={orphanSummary === null ? "共享快照还没读到" : `${orphanSummary.count} 条`}
      >
        <div class="readings">
          没有开始标记的事件不是「一趟 0 步的运行」：它们单独收在这一栏，不许并进时间线。
        </div>
        {orphans === null || orphanSummary === null ? (
          <TriState tri="unreadable" label="零散事件" reason="共享快照还没读到" />
        ) : orphans.length === 0 ? (
          <span class="empty">没有轮次之外的零散事件（读到了，是 0 条）。</span>
        ) : (
          <Table
            rows={orphans}
            empty="没有轮次之外的零散事件。"
            columns={[
              { key: "sid", title: "会话" },
              { key: "index", title: "事件下标" },
              { key: "kind", title: "kind" },
              { key: "role", title: "角色" },
              { key: "ts", title: "时间", render: (o) => text(o.ts) },
            ]}
          />
        )}
      </Card>

      <Card
        title="停机状态（缺口）"
        right={
          <TriState
            tri="not_applicable"
            label="停机面"
            reason="draft/74 说这一栏读 GET /api/state 的 stop 键，而 snapshot() 的顶层键被公开面对账钉住（10 个），没有它；今天也没有别的端点给停机读数"
          />
        }
      >
        <div class="readings">
          叫停（`POST /api/stop`）属于 C 线 W3，后端今天没有这条路由 ⇒ 按钮点不动。
        </div>
        <ConfirmButton
          action="叫停这一趟"
          impact="会给工作区落一个停机开关，并请求正在跑的循环收尾"
          onConfirm={() => undefined}
          requireForce
          disabled
          note="写端点还没上线（C 线 W3）—— 点不动，也不假装成功"
        />
      </Card>

      <Card
        title="检索腿（缺口）"
        right={
          <TriState
            tri="not_applicable"
            label="search_requests"
            reason="draft/74 说这一栏读 GET /api/state 的 search_requests 汇总，而 snapshot() 的顶层键被钉住，没有它；今天也没有别的端点给这一栏"
          />
        }
      >
        <div class="readings">
          这一栏要新增一条只读端点（`store.rows("search_requests")`）才能给读数 ——
          按纪律，页面不许自己编一个数。
        </div>
      </Card>
    </>
  );
}
