/*
 * 错误动作那一栏（业主：「ui侧加一个大栏专门显示各角色错误动作计数」）。
 *
 * 这一栏只回答一件事：盘上每个角色撞上了哪一类判据、各几次。读数来自
 * `GET /api/errors`（后端把 `readouts.errors_readout(root)` 逐字转发，计数口径全在
 * `errorstats`：角色归属 / 一条记录只算一次 / 三态）；每一格旁边那句"这个类目指什么"
 * 来自 `GET /api/errors/categories`（真身是 `errorstats.ERROR_CATEGORIES`，网页不另写一份）。
 *
 * ## 三态（这一栏最要紧的一条）
 *
 * - `state === "checked"`：画矩阵。这时 0 是一个真的读数（"这一类这个角色没撞上"）。
 * - `state === "unknown"`：整栏只画「读不到」与理由，一个矩阵格都不画。为什么不画一张
 *   0 行的表：空表会被读成"没有角色出错"，而那一刻的事实是"没查到" —— 这一栏存在的
 *   意义正是"什么时候没数据"也要看得见。
 * - 端点本身没成（`face.problem`）：走同一个「读不到」形态，但理由写明是请求没成。
 *
 * ## 屏幕上的四段（从两段扩成四段）
 *
 * 1. 抬头四行：角色侧 / 系统侧 / 状态读数（**三个数刻意不相加**）、逐类三态（读到 / 没查成 /
 *    不适用）、最集中的类目 top3、逐源读数；
 * 2. **按类**（新）：一行一类，列 = 类目 / 桶 / 条数 / 角色分布 / 这一趟·更早 / 三态；
 *    点一行展开它的 `samples`（`source · ref · ts` 与那一句原话）——"哪里在漏"由这一段答；
 * 3. **按角色**：矩阵，行=角色（`by_role` 的键，按合计降序），列=类目（`categories` 的键），
 *    格=计数。全 0 的格灰显（`empty` 那一档配色），非 0 的格加粗；
 * 4. 点某一列 ⇒ 只看这一类；点某一行 ⇒ 展开该角色的类目明细（计数 + 类目释义那一句）。
 *
 * 三态纪律（扩面后更严）：一个源读不到只让**那一类**变 `unknown`，整页不因此变 0；而
 * "这一类这一趟 0 条"仍然是 `checked` 的绿 —— 这两件事在屏幕上必须长得不一样
 * （"按类"那一段的三态列就是它）。
 *
 * ## 为什么取数不挂 `useFace`
 *
 * `useFace` 每来一条 SSE 事件就重取一次。这一条端点是一次全量扫描（事件流 + 全部会话
 * 记录：真机工作区上十几秒），跟着流重取会把页面拖死。所以这里是一次取数加一个
 * 「重新读」按钮，抬头写明"读数时间" —— 读的是某一刻的盘上事实，不是实时的。
 */
import { useEffect, useRef, useState } from "preact/hooks";

import { api, whyOf } from "../api";
import type {
  ErrorCategoryGlossary,
  ErrorClassRow,
  ErrorSignalSample,
  RoleErrorsView,
} from "../types";
import { Badge } from "./Badge";
import { Card } from "./Card";

/** 抬头那一句"最集中的类目"取前几名。 */
const TOP_LIMIT = 3;

/** 一格的计数：`by_role[角色][类目]`。缺这一格就是 0（后端只记出现过的格）。 */
export function cellCount(view: RoleErrorsView, role: string, category: string): number {
  const row = view.data.by_role[role];
  const got = row === undefined ? undefined : row[category];
  return got === undefined ? 0 : got;
}

/** 矩阵的行：角色。合计大的在前（同一屏里最该先看的就是那个），同数按名字。 */
export function matrixRows(view: RoleErrorsView): string[] {
  return Object.keys(view.data.by_role).sort((a, b) => {
    const diff = (view.data.role_total[b] ?? 0) - (view.data.role_total[a] ?? 0);
    return diff !== 0 ? diff : a.localeCompare(b);
  });
}

/** 矩阵的列：类目。顺序就是后端给的那一份（`ERROR_CATEGORIES` 的顺序，只留非 0 的）。 */
export function matrixColumns(view: RoleErrorsView): string[] {
  return Object.keys(view.data.categories);
}

/** 最集中的那几类（合计降序；同数保持后端给的顺序，即类目表的顺序）。 */
export function topCategories(view: RoleErrorsView, limit: number): Array<{ name: string; count: number }> {
  return matrixColumns(view)
    .map((name) => ({ name, count: view.data.categories[name] ?? 0 }))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit);
}

/** 桶的读法（后端 `bucket` 的四个取值）。四种单位不同，页面上必须分开写。 */
const BUCKETS: Record<string, string> = {
  error: "角色侧",
  system: "系统侧",
  state: "状态读数",
  process: "过程读数",
};

/**
 * "按类"那一段的行：非 0 的要出现；**0 条但没查成的更要出现**。
 *
 * 为什么 0 条还要留一行：这一栏回答的是"哪里在漏"，而"这一类这一趟 0 条（绿）"与
 * "这一类根本没接上（未知）"必须分得开 —— 只留非 0 的话，后者会整行消失，看起来像绿。
 */
export function classRows(view: RoleErrorsView): ErrorClassRow[] {
  return (view.data.classes ?? []).filter(
    (one) => one.count > 0 || one.state !== "checked",
  );
}

/** 逐类三态的合计（页面顶部那一行"X 类读到 / Y 类没查成 / Z 类不适用"）。 */
export function classTally(view: RoleErrorsView): { checked: number; unknown: number; na: number } {
  let checked = 0;
  let unknown = 0;
  let na = 0;
  for (const one of view.data.classes ?? []) {
    if (one.state === "checked") {
      checked += 1;
    } else if (one.state === "not_applicable") {
      na += 1;
    } else {
      unknown += 1;
    }
  }
  return { checked, unknown, na };
}

/** 一条样本的"去哪看"：`source` + `ref`（有 `ts` 就带上）。 */
export function sampleWhere(one: ErrorSignalSample): string {
  const where = `${one.source}${one.ref === "" ? "" : ` · ${one.ref}`}`;
  return one.ts === "" ? where : `${where} · ${one.ts}`;
}

/** 按类那一行的角色分布：`A 3 · D 12`（没有角色就写清楚，不写空串）。 */
export function roleSpread(one: ErrorClassRow): string {
  const parts = Object.keys(one.by_role).map((role) => `${role} ${one.by_role[role]}`);
  return parts.length === 0 ? "（无角色）" : parts.join(" · ");
}

/** 一类三态在页面上的说法（三档三句话，不许把 unknown 写成 0）。 */
function stateWord(one: ErrorClassRow): string {
  if (one.state === "checked") {
    return one.count === 0 ? "读到（0 条）" : "读到";
  }
  if (one.state === "not_applicable") {
    return "不适用";
  }
  return one.reason === "" ? "没查成" : `没查成：${one.reason}`;
}

/**
 * "按类"那一段：一行一类，点开看这一类的 source 明细。
 *
 * 为什么这一段排在最前面：业主的原话是"一眼看出系统哪里在漏"，而"按角色"那张矩阵回答的
 * 是"谁出错了" —— 两种问法。这一段的顺序是**桶 → 条数**（后端 `by_class()` 排好的），
 * 三种单位不会混在同一个降序里。
 */
function ClassTable(props: {
  view: RoleErrorsView;
  picked: string;
  onPick: (category: string) => void;
}) {
  const { view, picked, onPick } = props;
  const [open, setOpen] = useState<string>("");
  const rows = classRows(view);
  if (rows.length === 0) {
    return (
      <div class="empty">
        四个桶里一条都没有，而且每一类都是读出来的 0（state=checked）——
        这不是"没查成"，是"查过了、真的没有"。
      </div>
    );
  }
  const out = [];
  for (const one of rows) {
    const isOpen = open === one.category;
    const samples = one.samples ?? [];
    out.push(
      <tr key={one.category} class={picked === one.category ? "err-picked" : undefined}>
        <th>
          <button
            class="err-pick"
            type="button"
            title="点这一类看它的 source 明细"
            onClick={() => {
              setOpen(isOpen ? "" : one.category);
              onPick(one.category);
            }}
          >
            <span class="mono">{one.category}</span>
          </button>
        </th>
        <td class="tri-reason">{BUCKETS[one.bucket] ?? one.bucket}</td>
        <td class={one.count === 0 ? "mono err-zero" : "mono err-hot"}>{one.count}</td>
        <td class="tri-reason">{roleSpread(one)}</td>
        <td class="mono">
          {one.this_run} / {one.earlier}
          {one.no_ts > 0 ? `（${one.no_ts} 条没记时间）` : ""}
        </td>
        <td class="tri-reason">{stateWord(one)}</td>
      </tr>,
    );
    if (isOpen) {
      out.push(
        <tr key={`${one.category}-open`}>
          <td colSpan={6}>
            <div class="err-detail">
              <div class="section-title">{one.category} —— {one.meaning}</div>
              {one.state !== "checked" ? (
                <div class="tri-reason">{stateWord(one)}</div>
              ) : null}
              {samples.length === 0 ? (
                <div class="tri-reason">
                  这一类没有留样的明细（0 条，或者样本是为 0 的旧读数）。
                </div>
              ) : (
                <ul class="list">
                  {samples.map((s) => (
                    <li key={`${s.source}|${s.ref}|${s.ts}|${s.code}`}>
                      <span class="mono">{sampleWhere(s)}</span>
                      <span class="tri-reason"> — {s.detail}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </td>
        </tr>,
      );
    }
  }
  return (
    <div class="err-scroll">
      <table class="grid err-matrix">
        <thead>
          <tr>
            <th>类目</th>
            <th>桶</th>
            <th>条数</th>
            <th>角色</th>
            <th>这一趟 / 更早</th>
            <th>三态</th>
          </tr>
        </thead>
        <tbody>{out}</tbody>
      </table>
    </div>
  );
}

/** 类目 → 释义（`GET /api/errors/categories` 那一份；没读到就是空表，另有一句话说清）。 */function meaningsOf(gloss: ErrorCategoryGlossary | null): Record<string, string> {
  const out: Record<string, string> = {};
  for (const one of gloss === null ? [] : gloss.categories) {
    out[one.name] = one.meaning;
  }
  return out;
}

/** 这一次读数是什么时候取的（抬头那一行要用它，免得把旧数当实时数）。 */
function stamp(): string {
  const now = new Date();
  return now.toLocaleTimeString();
}

/**
 * 读不到那一档的整栏形态：只画「读不到」与理由，不画矩阵。
 *
 * 为什么它单独是一个组件：`state === "unknown"` 与"端点没成"两档必须长得一模一样
 * （都是"没读到"），而它们都必须与"读到了、里面是 0"长得不一样。
 */
export function UnreadableBand(props: { reason: string }) {
  return (
    <Card
      title="错误动作"
      subtitle="按角色 × 类目（只读）"
      tone="problem"
      right={<Badge kind="badge-unknown" text="读不到" />}
    >
      <div class="readings">
        读不到：
        {props.reason === ""
          ? "这一份没查成，而且它没给出原因（那就是它自己的读数）"
          : props.reason}
      </div>
      <div class="empty">
        没读到的时候不画矩阵：0 行的表会被读成"没有角色出错"，而事实是"没查成"。
        这一栏存在的意义之一，就是这两种情形在屏幕上必须分得开。
      </div>
    </Card>
  );
}

/** 点开某一行之后的那一段：该角色每个类目的计数，外加那一句释义。 */
function RoleDetail(props: {
  view: RoleErrorsView;
  role: string;
  meanings: Record<string, string>;
  glossReady: boolean;
  glossProblem: string;
}) {
  const { view, role, meanings, glossReady, glossProblem } = props;
  const cats = matrixColumns(view).filter((one) => cellCount(view, role, one) > 0);
  /** 这一格没有释义时该说哪句话：还在读 / 表里没登记，是两句不同的话。 */
  const why = (category: string): string => {
    if (meanings[category] !== undefined) {
      return meanings[category];
    }
    return glossReady
      ? "（这一类在 errorstats 的类目表里没有登记释义）"
      : "（类目释义还在读）";
  };
  return (
    <div class="err-detail">
      <div class="section-title">
        <span class="mono">{role}</span> 的类目明细（合计{" "}
        <span class="mono">{view.data.role_total[role] ?? 0}</span>）
      </div>
      {glossProblem === "" ? null : (
        <div class="tri-reason">
          类目释义没读到（{glossProblem}）—— 计数是读到的，只有那句释义这一格没读到。
        </div>
      )}
      <ul class="list">
        {cats.map((category) => (
          <li key={category}>
            <span class="mono">{category}</span> {cellCount(view, role, category)}
            <span class="tri-reason"> — {why(category)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * 那一栏本体：抬头三行 + 矩阵 + 展开与过滤。
 *
 * 状态只有四个：还在读、端点没成、没读到（unknown）、读到了。矩阵只在最后一个状态里画。
 */
export function RoleErrors() {
  const [view, setView] = useState<RoleErrorsView | null>(null);
  const [problem, setProblem] = useState("");
  const [gloss, setGloss] = useState<ErrorCategoryGlossary | null>(null);
  const [glossProblem, setGlossProblem] = useState("");
  const [readAt, setReadAt] = useState("");
  const [tick, setTick] = useState(0);
  const [openRole, setOpenRole] = useState("");
  const [onlyCategory, setOnlyCategory] = useState("");
  /** 矩阵那一层（量它有没有横向溢出）。 */
  const scrollRef = useRef<HTMLDivElement>(null);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .getErrors()
      .then((got) => {
        if (alive) {
          setView(got);
          setProblem("");
          setReadAt(stamp());
        }
      })
      .catch((exc: unknown) => {
        if (alive) {
          setProblem(whyOf(exc));
        }
      });
    api
      .getErrorCategories()
      .then((got) => {
        if (alive) {
          setGloss(got);
          setGlossProblem("");
        }
      })
      .catch((exc: unknown) => {
        if (alive) {
          setGlossProblem(whyOf(exc));
        }
      });
    return () => {
      alive = false;
    };
  }, [tick]);

  /*
   * 量一次"这张矩阵有没有横向溢出"，溢出就说一句话。
   *
   * 为什么要量而不是按类目数估：列宽由类目名的长度决定（`multi_call_executed_calls`
   * 一格顶三格），同一个类目数在不同屏宽下结论不同。不量的话，最右那几列看起来像
   * "没有这一类"——那是这一栏最不该犯的错。
   *
   * 这个 effect 不带依赖时，每次渲染后都会读一次 `scrollWidth` —— 那是同步回流
   * （读一次量一次布局），而这一栏的表在事件密集时每个事件都会重渲染一次。
   * 所以只在"影响溢出的那几件事"变了才量：
   * 显示了哪几列（`measureKey`）与窗口尺寸（同一条 effect 里挂 `resize`）。
   */
  const measureKey = `${onlyCategory}|${view === null ? "" : Object.keys(view.data.categories).length}`;
  useEffect(() => {
    const measure = (): void => {
      const box = scrollRef.current;
      setOverflowing(box !== null && box.scrollWidth > box.clientWidth + 1);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("resize", measure);
    };
  }, [measureKey]);

  if (problem !== "") {
    return <UnreadableBand reason={`读这一栏的端点没成（${problem}）`} />;
  }
  if (view === null) {
    return (
      <Card title="错误动作" subtitle="按角色 × 类目（只读）">
        <span class="empty">
          正在读——这一条要扫事件流与全部会话记录，大工作区上十几秒。
        </span>
      </Card>
    );
  }
  if (view.state !== "checked") {
    return <UnreadableBand reason={view.reason} />;
  }

  const columns = matrixColumns(view);
  const shown = onlyCategory === "" || columns.indexOf(onlyCategory) < 0
    ? columns
    : [onlyCategory];
  const rows = matrixRows(view);
  const top = topCategories(view, TOP_LIMIT);
  const tally = classTally(view);
  const boundary = view.data.run_boundary ?? "";
  const meanings = meaningsOf(gloss);
  const events = view.data.sources.events ?? {};
  const sessions = view.data.sources.sessions ?? {};
  return (
    <Card
      title="错误动作"
      subtitle="按角色 × 类目（只读；零模型调用）"
      right={
        <button
          class="btn"
          type="button"
          onClick={() => {
            setTick((t) => t + 1);
          }}
        >
          重新读
        </button>
      }
    >
      <div class="readings">
        角色侧 <b class="mono">{view.data.total}</b>
        <span class="tri-reason"> · </span>
        系统侧 <b class="mono">{view.data.system_total}</b>
        <span class="tri-reason"> · </span>
        状态读数 <b class="mono">{view.data.state_readings_total}</b>
        <span class="tri-reason">
          {" "}
          · 三个数刻意不相加：三种单位（谁做错了 / 系统哪里坏了 / 现在积着什么）·
          {" "}
          {rows.length} 个角色有记录 · 读数时间 {readAt === "" ? "（未记）" : readAt}
          （盘上一变就要重新读）
        </span>
      </div>
      <div class="readings">
        逐类三态：
        <span class="mono">
          15 类里读到 {tally.checked} / 没查成 {tally.unknown} / 不适用 {tally.na}
        </span>
        <span class="tri-reason">
          {" "}
          · 没查成的那几类不是 0：它们的数没算出来，页面上要点开看理由
        </span>
      </div>
      <div class="readings">
        最集中的类目：
        {top.length === 0 ? (
          <span class="empty">一个类目都没命中（全 0，而且这是读出来的 0）</span>
        ) : (
          top.map((one, index) => (
            <span key={one.name}>
              {index === 0 ? " " : " · "}
              <span class="mono">{one.name}</span> {one.count}
            </span>
          ))
        )}
      </div>
      <div class="readings">
        三态：
        <Badge kind="badge-pass" text={`checked=${String(view.checked)}`} />
        <span class="mono"> state={view.state}</span>
        <span class="tri-reason">
          {" "}
          · 事件流 {events.events ?? 0} 条（{events.bad_lines ?? 0} 行读不明白） / 会话记录{" "}
          {sessions.records ?? 0} 条（{sessions.files ?? 0} 个文件，{sessions.bad_lines ?? 0}{" "}
          行读不明白）· 口径在 errorstats（六档归属 / 一条记录只算一次 / 主码 + 结构化类目）
        </span>
      </div>
      {view.problems.length === 0 ? null : (
        <ul class="list">
          {view.problems.map((one) => (
            <li key={one.code} class="tri-reason">
              {one.code}：{one.detail}
            </li>
          ))}
        </ul>
      )}

      <div class="section-title">按类（哪里在漏：点一行看它的 source）</div>
      <div class="tri-reason">
        {" "}
        「这一趟 / 更早」的边界 = 最后一处 `agent_run_start` 的 ts
        {boundary === "" ? "（这一次没读到边界 ⇒ 全部记在'更早'，不假分趟）" : `（${boundary}）`}
        。状态读数是快照，会随 ack 回落；它与角色侧、系统侧的单位不同。
      </div>
      <ClassTable
        view={view}
        picked={onlyCategory}
        onPick={(category) => {
          setOnlyCategory(onlyCategory === category ? "" : category);
        }}
      />

      <div class="section-title">按角色（谁出错了）</div>
      {rows.length === 0 ? (
        <div class="empty">
          全 0：这个工作区里没有任何角色留下错误动作（已读出，checked=true）。
          它不是"没查到"—— 这一栏在没查到时显示的是另一个样子。
        </div>
      ) : (
        <div class="err-scroll" ref={scrollRef}>
          <table class="grid err-matrix">
            <thead>
              <tr>
                <th>角色</th>
                {shown.map((category) => (
                  <th key={category}>
                    <button
                      class="err-pick"
                      type="button"
                      title="点这一列只看这一类"
                      onClick={() => {
                        setOnlyCategory(onlyCategory === category ? "" : category);
                      }}
                    >
                      <span class="mono">{category}</span>
                    </button>
                  </th>
                ))}
                <th>合计</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((role) => (
                <tr key={role}>
                  <th>
                    <button
                      class="err-pick"
                      type="button"
                      title="点这一行展开它的类目明细"
                      onClick={() => {
                        setOpenRole(openRole === role ? "" : role);
                      }}
                    >
                      <span class="mono">{role}</span>
                    </button>
                  </th>
                  {shown.map((category) => {
                    const count = cellCount(view, role, category);
                    return (
                      <td key={category} class={count === 0 ? "mono err-zero" : "mono err-hot"}>
                        {count}
                      </td>
                    );
                  })}
                  <td class="mono err-hot">{view.data.role_total[role] ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {overflowing ? (
        <div class="tri-reason">
          类目比屏宽：这张表可以横向滚（左右两头分别钉着角色与合计，滚到中间也还知道
          这一行是谁）。没滚出来的那几列不是没有 —— 它们就在右边。
        </div>
      ) : null}

      {onlyCategory === "" ? null : (
        <div class="readings">
          只看这一类：<span class="mono">{onlyCategory}</span>
          {meanings[onlyCategory] === undefined ? null : (
            <span class="tri-reason">（{meanings[onlyCategory]}）</span>
          )}
          <button
            class="btn"
            type="button"
            onClick={() => {
              setOnlyCategory("");
            }}
          >
            取消过滤
          </button>
        </div>
      )}
      {openRole === "" ? null : (
        <RoleDetail
          view={view}
          role={openRole}
          meanings={meanings}
          glossReady={gloss !== null}
          glossProblem={glossProblem}
        />
      )}
    </Card>
  );
}
