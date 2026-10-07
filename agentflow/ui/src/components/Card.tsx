/** 一张卡片：标题 + 可选副标题 + 内容（纯呈现，不做任何取数）。 */
import type { ComponentChildren } from "preact";

export interface CardProps {
  title: string;
  subtitle?: string;
  children?: ComponentChildren;
}

export function Card(props: CardProps) {
  return (
    <section class="card">
      <div class="card-head">
        <span class="caption">{props.title}</span>
        {props.subtitle === undefined ? null : <span class="readings">{props.subtitle}</span>}
      </div>
      {props.children}
    </section>
  );
}
