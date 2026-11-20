import {
  Children,
  isValidElement,
  useId,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import type { ComputePhase } from "../advice/useAdviceJob";
import { openingAction, plannedWeeks } from "./planComparison";

interface GroupProps {
  className: string;
  label(index: number): string;
  children: ReactNode;
}

/** Only completed three-week decisions get an opening label. */
function openingKey(state?: ComputePhase, conflict?: boolean) {
  if (conflict || state?.phase !== "done") return null;
  const plan = state.envelope.payload;
  if (plan.window !== 3 || !plannedWeeks(plan)) return null;
  if (plan.solver_status && !["OPTIMAL", "FEASIBLE"].includes(plan.solver_status)) return null;
  const { incoming, outgoing, chip } = openingAction(plan);
  return JSON.stringify([plan.gameweek, incoming, outgoing, chip]);
}

function GroupedPaths({ className, label, children }: GroupProps) {
  const prefix = useId();
  const [known, setKnown] = useState<string[]>([]);
  const ungrouped: ReactElement<{ id: string }>[] = [];
  const groups = new Map<string, typeof ungrouped>();
  Children.toArray(children).forEach((node, index) => {
    const element = isValidElement<{ state?: ComputePhase; conflict?: boolean }>(node)
      ? node
      : null;
    const key = element?.key ?? index;
    const card = (
      <div key={`card-${key}`} id={`${prefix}-${encodeURIComponent(String(key))}`}>
        {node}
      </div>
    );
    const opening = openingKey(element?.props.state, element?.props.conflict);
    if (opening === null) ungrouped.push(card);
    else groups.set(opening, [...(groups.get(opening) ?? []), card]);
  });
  const additions = [...groups.keys()].filter((key) => !known.includes(key));
  const order = additions.length ? [...known, ...additions] : known;
  if (order !== known) setKnown(order);

  // Keep cards as keyed siblings while their decisions arrive. The named group
  // owns the same cards in the accessibility tree without remounting them.
  const rows: ReactNode[] = [...ungrouped];
  order.forEach((opening, index) => {
    const cards = groups.get(opening);
    if (!cards) return;
    const heading = `${prefix}-opening-${index}`;
    rows.push(
      <section
        key={opening}
        data-path-group={opening}
        aria-labelledby={heading}
        aria-owns={cards.map((card) => card.props.id).join(" ")}
      >
        <h3 id={heading}>{label(index + 1)}</h3>
      </section>,
      ...cards,
    );
  });
  return <div className={className}>{rows}</div>;
}

export function PlanPathGroups({
  enabled,
  runId,
  ...props
}: GroupProps & { enabled: boolean; runId?: string }) {
  if (!enabled) return <div className={props.className}>{props.children}</div>;
  return <GroupedPaths key={runId} {...props} />;
}
