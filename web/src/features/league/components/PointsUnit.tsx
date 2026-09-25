import { useLanguage } from "../../../i18n/context";

/**
 * The unit after an expected-points figure on a tight line (the decision's captain line, the
 * plan's list rows, the held squad's rows): the short "xP" on screen in both languages, and
 * in Turkish the words "beklenen puan" for a screen reader, so neither the width nor the word
 * "expected" is lost. Where the two agree it is plain text.
 */
export function PointsUnit() {
  const copy = useLanguage().messages.leagueMembers;
  if (copy.pointsUnitAbbreviation === copy.pointsUnitSpoken) return <>{copy.pointsUnitSpoken}</>;
  return (
    <>
      <span aria-hidden="true">{copy.pointsUnitAbbreviation}</span>
      <span className="visually-hidden"> {copy.pointsUnitSpoken}</span>
    </>
  );
}
