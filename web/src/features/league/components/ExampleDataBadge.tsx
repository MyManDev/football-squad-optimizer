import { Badge } from "../../../design/components/Badge";
import { useLanguage } from "../../../i18n/context";
import type { LeagueViewEnvelope } from "../types";

export function ExampleDataBadge({
  sourceKind,
}: {
  sourceKind: LeagueViewEnvelope<unknown>["source_kind"];
}) {
  const { messages } = useLanguage();
  return sourceKind === "example" ? (
    <Badge tone="warn">{messages.leagueMembers.exampleData}</Badge>
  ) : null;
}
