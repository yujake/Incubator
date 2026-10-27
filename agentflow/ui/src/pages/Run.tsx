/*
 * 一趟详情 —— 运行态（`draft/74 §3.2` 逐行落）。
 *
 * 输入三条端点 + 一次共享快照：
 *
 * - `api.getRun(sid)` → `RunView`（`runs` / `report` / `checkpoint`）；
 * - `api.getRunIndex()` → `RunIndexDrift`（裁定 O2：趟次索引与它对账的结论）；
 * - `api.getRunEvents(sid, { sinceIndex, limit })` → `RunEventsView`（题 T2-a：一趟的
 *   逐条事件，游标分页；旧壳那张"逐条事件卡片"退场后唯一能逐条复核的那一层）；
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
 * 两处缺口现在只剩一处（2026-10-12 更正）：**停机**那一栏已经接上了 ——
 * 后端 `GET /api/live`（在飞面）给停机开关与历史、`POST /api/stop` 给按钮，
 * 所以这一页的「停机」卡片是真能按的（写面没开时后端回 403，回执如实显示）。
 * 仍然缺的是**检索腿**（`search_requests` 汇总）：`snapshot()` 的顶层键被公开面
 * 对账钉住（10 个），要给它读数得新增一条只读端点 —— 那一栏照旧渲染
 * `not_applicable` 并写明，不许自己编一个数。
 */
import { api, whyOf } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { StopButtons } from "../components/Stop";
import { Money } from "../components/Money";
import { Table } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace, useLive } from "../live";
import { useEffect, useState } from "preact/hooks";
import type { CheckpointSpendView, CheckpointView, EventRow } from "../types";

export interface RunProps {
  sid: string;
}

/** 一页多少条逐条事件（与后端 `EVENTS_LIMIT_DEFAULT` 一致；上限是 500）。 */
const EVENTS_PAGE = 50;

/** 检查点的花销子树（类型上是联合：读不到时后端给的是空对象）。
 *
 * 2026-10-27 起它只供 `calls` / `tokens_in` / `tokens_out` 三格用（后端没把这三格
 * 单列）；金额那一格统一走 `RunView.checkpoint_spend_usd` —— 同一件事只许有一条
 * 读数路径，否则"两处一致"这条判据自己就站在一个可能漂的数上。
 */
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

function text(value: string): string {
  return value === "" ? "unknown" : value;
}

/** 一行摘要：优先事件的 `text`，其次 `payload` / `result` 的 JSON，都没有就留空。 */
function eventSummary(e: EventRow): string {
  const body = typeof e.text === "string" ? e.text : "";
  if (body !== "") {
    return body.length > 200 ? `${body.slice(0, 200)}…` : body;
  }
  const blob = e.payload ?? e.result;
  if (blob !== undefined) {
    const raw = JSON.stringify(blob);
    return raw.length > 200 ? `${raw.slice(0, 200)}…` : raw;
  }
  return "";
}

/**
 * 逐条事件（一趟回放）—— 旧壳那张"逐条事件卡片"退场之后，用户端唯一能逐条复核的地方
 * （题 T2-a 的消费端）。
 *
 * 三态在这一块上是"三档各有一句"：
 *
 * - `computed`：真读数 + 游标区间 + "继续加载"（`since_index` 续取）；
 * - `unreadable`：这一栏**没查成**，显 TriState + 理由，**不是一张空列表**（也绝不把
 *   条数写成 0）；
 * - `not_applicable`：会话文件在盘上但还没有事件（合法初态），同样不是一张空列表。
 *
 * "继续加载"攒下来的页只在第一页的 `to_index` 没变时有效：它一变（换了会话，或盘上
 * 又写进了事件）就把攒的那几页作废 —— 否则页面上会把两段读数接在一起而看不出来。
 */
function EventTimeline(props: { sid: string }) {
  const first = useFace(() => api.getRunEvents(props.sid, { limit: EVENTS_PAGE }));
  const [older, setOlder] = useState<EventRow[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const data = first.data;
  const toIndex = data === null ? null : data.to_index;

  useEffect(() => {
    setOlder([]);
    setCursor(toIndex);
    setProblem("");
  }, [toIndex, props.sid]);

  const loadMore = (): void => {
    if (cursor === null) {
      return;
    }
    setBusy(true);
    setProblem("");
    api
      .getRunEvents(props.sid, { sinceIndex: cursor, limit: EVENTS_PAGE })
      .then((next) => {
        if (next.tri !== "computed") {
          setProblem(`续取没查成（tri=${next.tri}）：${next.reason}`);
        } else {
          setOlder((prev) => prev.concat(next.events));
          setCursor(next.to_index);
        }
        setBusy(false);
      })
      .catch((exc: unknown) => {
        setProblem(whyOf(exc));
        setBusy(false);
      });
  };

  if (data === null) {
    return (
      <Card
        title="逐条事件（一趟回放）"
        subtitle={`会话 ${props.sid}`}
        tone={first.problem === "" ? "plain" : "problem"}
        right={
          first.problem === ""
            ? null
            : <TriState tri="unreadable" reason={first.problem} label="逐条事件" />
        }
      >
        <span class="readings">
          {first.problem === "" ? "正在读盘……" : `读数没拿到：${first.problem}`}
        </span>
      </Card>
    );
  }

  if (data.tri !== "computed") {
    return (
      <Card
        title="逐条事件（一趟回放）"
        subtitle={`会话 ${props.sid}`}
        tone="problem"
        right={<TriState tri={data.tri} label="逐条事件" reason={data.reason} />}
      >
        <span class="empty">
          {data.tri === "unreadable"
            ? `这一栏没查成（不是一张空列表）：${data.reason}`
            : `这一趟还没有事件可回放（合法初态，不是一张空列表）：${data.reason}`}
        </span>
        <div class="readings">
          事件条数那一格因此是 <span class="mono">unknown</span>，不是 0：没读到就不写数。
        </div>
      </Card>
    );
  }

  const rows = data.events.concat(older);
  const more = data.total !== null && cursor !== null && cursor < data.total;
  return (
    <Card
      title="逐条事件（一趟回放）"
      subtitle={`会话 ${props.sid} · 已给 ${rows.length} 条`}
      right={<TriState tri={data.tri} label="逐条事件" reason={data.reason} />}
    >
      <div class="readings">
        事件总条数 <span class="mono">{data.total}</span> · 本页区间{" "}
        <span class="mono">[{data.from_index}, {data.to_index})</span> · 还没给完{" "}
        <span class="mono">{String(data.truncated)}</span>
      </div>
      <div class="readings">
        <span class="mono">index</span> 与「趟次」那张表的 <span class="mono">start_index</span> /{" "}
        <span class="mono">end_index</span> 是同一套编号（会话里第几条事件，0 起）；
        花销那一列的 <span class="mono">—</span> = 这一行没有 <span class="mono">usd</span>{" "}
        这一栏（不是 0），<span class="mono">unknown</span> = 有这一栏但算不出价钱。
      </div>
      <Table
        rows={rows}
        empty="这一页是空的（读到了，游标已经到末尾 —— 不是「没查成」）。"
        columns={[
          { key: "index", title: "#" },
          { key: "kind", title: "kind" },
          { key: "ts", title: "时间", render: (e) => text(e.ts) },
          { key: "role", title: "角色", render: (e) => text(e.role) },
          { key: "shape", title: "形态" },
          { key: "ok", title: "成功" },
          {
            key: "usd",
            title: "花销",
            render: (e) =>
              e.usd === undefined ? "—" : <Money usd={e.usd} unknownCalls={0} />,
          },
          { key: "text", title: "一行摘要 / 正文", render: (e) => eventSummary(e) },
        ]}
      />
      {problem === "" ? null : (
        <TriState tri="unreadable" label="续取" reason={problem} />
      )}
      {more ? (
        <button type="button" disabled={busy} onClick={loadMore}>
          {busy ? "正在续取……" : `继续加载（从第 ${cursor ?? 0} 条起）`}
        </button>
      ) : (
        <span class="readings">已经给到末尾了（没有更多事件）。</span>
      )}
    </Card>
  );
}

export function Run(props: RunProps) {
  const live = useLive();
  const view = useFace(() => api.getRun(props.sid));
  const index = useFace(() => api.getRunIndex());
  // 在飞面：这一页只用它的「停机开关」那一格（谁按的、按没按过）。
  // 它是一个独立的 hook，所以必须在下面那些 early return **之前**调 ——
  // hooks 的调用顺序是 React/Preact 的硬约束，放进分支里会当场炸。
  const liveFace = useFace(() => api.getLive());

  if (props.sid === "") {
    return (
      <Card title="一趟详情" right={<TriState tri="not_applicable" reason="URL 里没有会话号" />}>
        <span class="empty">
 这一页要看的是 /run/&lt;会话号&gt;。会话号在首页的「会话概览」里点得进来。
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
  // 两个数必须同范围（2026-10-27 业主裁定 ⑥-4）：左边是"这一趟（同一 role）的检查点
  // 累计"，右边是"这一段会话里同一 role 那一趟的事件求和"—— 两格都由后端给，
  // 页面不再自己对 `runs` 求和（改前那句 `eventSum(v.runs)` 求的是整段会话每一趟
  // 之和，跟一份检查点比，多趟/多代理时必然不等，于是恒挂一条假红）。
  const ckAmount = v.checkpoint_spend_usd;
  const runAmount = v.same_run_spend_usd;
  // 两边都读到才算得出"一致 / 不一致"：任一为 `null` 是"没查成"，不是"对不上"。
  const sameAmount =
    ckAmount !== null && runAmount !== null
      ? Math.abs(ckAmount - runAmount) < 1e-9
      : null;
  // 本段会话每一趟的合计：只作参考读数摆出来，不参与上面那个判据（跨趟不同范围）。
  const sessionTotal = runs.reduce((acc, r) => acc + (r.usd ?? 0), 0);
  const sessionUnknown = runs.reduce((acc, r) => acc + r.unknown_usd, 0);
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
 本页的趟次因此是回退现算的（sessions.runs_in_session 从会话文件现切），
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

      <EventTimeline sid={props.sid} />

      <Card
        title="花销（同一趟的两个来源并排）"
        subtitle={
          v.same_run_start_index === null
            ? "这一段会话里没有与检查点同角色的那一趟 ⇒ 第二个读数读不到"
            : `比的是同一趟：${v.checkpoint_role} 那一趟（第 ${v.same_run_start_index} 条事件起）`
        }
        tone={sameAmount === false ? "problem" : "plain"}
        right={
          sameAmount === null ? (
            <TriState
              tri="unreadable"
              label="两处是否一致"
              reason="有一个来源没读到（检查点的累计、或同一趟的事件求和）⇒ 这一格没查成，不是「一致」"
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
          <span class="caption">首选：检查点（这一趟的累计）</span>
          <Money
            usd={ckAmount}
            unknownCalls={spend === null ? 0 : spend.unknown_usd_calls}
            calls={spend === null ? undefined : spend.calls}
            tokensIn={spend === null ? undefined : spend.tokens_in}
            tokensOut={spend === null ? undefined : spend.tokens_out}
          />
        </div>
        <div class="row">
          <span class="caption">第二读数：同一趟的事件求和</span>
          <Money usd={runAmount} unknownCalls={v.same_run_unknown_usd} />
        </div>
        <div class="readings">
          检查点{" "}
          <span class="mono">
            {ckpt === null
              ? `unknown（${v.checkpoint_reason === "" ? "没读到" : v.checkpoint_reason}）`
              : `${ckpt.role} / step ${ckpt.step} / ${ckpt.at}`}
          </span>
        </div>
        <div class="readings tri-reason">
          本段会话每一趟的合计（参考读数，不与上面那个数比 —— 跨趟是不同范围）：
          <Money usd={sessionTotal} unknownCalls={sessionUnknown} />
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
              {/* D21（与 Home 的「台账」卡同一个口径）：`events` 不再是 events.jsonl
                  的总行数，它是写入笔数（`upserts`）；其中的 commit 标记行数单列。 */}
              台账写入{" "}
              <span class="mono">{ledger.upserts === null ? "unknown" : ledger.upserts}</span> 笔
              （其中 commit 标记{" "}
              <span class="mono">{ledger.commit_markers === null ? "unknown" : ledger.commit_markers}</span> 行）·
              tasks 行数{" "}
              <span class="mono">{ledger.tables === null ? "unknown" : ledger.tables}</span> · 落点{" "}
              <span class="mono">{ledger.path}</span>
            </div>
            {ledger.events_note === "" ? null : (
              <div class="readings">{ledger.events_note}</div>
            )}
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
        title="停机"
        right={
          liveFace.data === null ? null : (
            <Badge
              kind={liveFace.data.switch_present ? "badge-fail" : "badge-pass"}
              text={liveFace.data.switch_present ? "盘上有停机开关" : "盘上没有停机开关"}
            />
          )
        }
      >
        <div class="readings">
 叫停的落点是一个跨进程开关（工作区 runs/ 下那一份）：在飞的循环在下一个步检查点
          读到它就收工，把已做过的事留在台账与会话记录里。这一页的按钮写的就是它；
          「在飞」页能看到开关是谁按的、以及最近几条停机历史，那里也有同一对按钮。
          {liveFace.data === null
            ? ""
            : ` 现在盘上${liveFace.data.switch_present ? "有" : "没有"}停机开关。`}
        </div>
        {/* R93：这对按钮与「在飞」页共用同一份实现（`components/Stop.tsx`）——
            以前两页各写一份，用户报的是"网页里找不到停机开关"，根因就是它只长在这一页。 */}
        <StopButtons onDone={() => liveFace.reload()} />
      </Card>

      <Card
        title="检索腿（仍是缺口）"
        right={
          <TriState
            tri="not_applicable"
            label="search_requests"
            reason="要一条读 store.rows('search_requests') 的只读端点才有读数；今天还没有那条端点"
          />
        }
      >
        <div class="readings">
 这一栏要新增一条只读端点（store.rows("search_requests")）才能给读数 ——
          按纪律，页面不许自己编一个数。
        </div>
      </Card>
    </>
  );
}
