import { ruleName } from "../i18n";

/** A rule as its Vietnamese name with the original id beneath, so the id can still be quoted. */
export default function RuleLabel({ id }: { id: string }) {
  const name = ruleName(id);
  return (
    <span className="rule-label">
      {name !== id && <span className="rule-name">{name}</span>}
      <span className="rule-id code">{id}</span>
    </span>
  );
}
