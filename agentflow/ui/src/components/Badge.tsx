/** 一个徽标：`kind` 决定视觉档（pass / fail / unknown / plain），`text` 是逐字读数。
 *
 * `title` 是悬停说明（可选）：只放读数背后的那一句"为什么"，不放另一份数字 ——
 * 徽标上印的是读数，悬停里再印一遍同一个数会让两处各说各话。
 */
export interface BadgeProps {
  kind: string;
  text: string;
  title?: string;
}

export function Badge(props: BadgeProps) {
  return (
    <span class={`badge ${props.kind}`} title={props.title}>
      {props.text}
    </span>
  );
}
