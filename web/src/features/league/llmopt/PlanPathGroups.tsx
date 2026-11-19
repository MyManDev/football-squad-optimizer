import { Children, isValidElement, type ReactNode } from "react";
import type { ComputePhase } from "../advice/useAdviceJob";
import { openingAction } from "./planComparison";

/** Later routes sharing the same first decision stay together. */
export function PlanPathGroups({
  enabled,
  className,
  label,
  children,
}: {
  enabled: boolean;
  className: string;
  label(index: number): string;
  children: ReactNode;
}) {
  if (!enabled) return <div className={className}>{children}</div>;
  const groups = new Map<string, ReactNode[]>();
  Children.toArray(children).forEach((node, index) => {
    const state = isValidElement<{ state?: ComputePhase }>(node) ? node.props.state : undefined;
    const plan = state?.phase === "done" ? state.envelope.payload : undefined;
    const opening = plan ? openingAction(plan) : undefined;
    const key =
      plan?.window === 3 && opening
        ? JSON.stringify([plan.gameweek, opening.incoming, opening.outgoing, opening.chip])
        : `pending-${index}`;
    groups.set(key, [...(groups.get(key) ?? []), node]);
  });
  return (
    <div>
      {[...groups].map(([key, nodes], index) => (
        <section key={key} data-path-group={key}>
          <h3>{label(index + 1)}</h3>
          <div className={className}>{nodes}</div>
        </section>
      ))}
    </div>
  );
}
