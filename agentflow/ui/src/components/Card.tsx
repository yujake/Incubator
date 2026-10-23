/** 一张卡片：标题 + 可选副标题 + 可选右侧动作 + 内容（纯呈现，不做任何取数）。 */
import type { ComponentChildren } from "preact";

export interface CardProps {
  title: string;
  subtitle?: string;
  /** 标题右侧那一格（放 TriState 徽标或一句读数）。 */
  right?: ComponentChildren;
  /** `problem` 那一档给卡片描一圈警示色（"没查成"要在视觉上看得出来）。 */
  tone?: "plain" | "problem";
  /** 这一张卡的锚点（`<section id=…>`）：别的页面要链到"某一栏"时用它。 */
  id?: string;
  children?: ComponentChildren;
}

export function Card(props: CardProps) {
  const cls = props.tone === "problem" ? "card problem" : "card";
  return (
    <section class={cls} id={props.id}>
      <div class="card-head">
        <span class="card-title">{props.title}</span>
        {props.subtitle === undefined ? null : <span class="readings">{props.subtitle}</span>}
        {props.right === undefined ? null : <span class="card-right">{props.right}</span>}
      </div>
      {props.children}
    </section>
  );
}
