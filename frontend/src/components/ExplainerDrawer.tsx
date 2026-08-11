import { explainerFor } from "../content/explainers";
import { Drawer } from "./Drawer";

const SECTIONS: [keyof ReturnType<typeof sectionsOf>, string][] = [
  ["what", "What it is"],
  ["how", "How it's worked out"],
  ["example", "Worked example"],
  ["scale", "Is it good or bad?"],
  ["alongside", "What to read alongside it"],
  ["breaks", "When it breaks"],
];

function sectionsOf(metric: string) {
  return explainerFor(metric) ?? { what: "", how: "", example: "", scale: "", alongside: "", breaks: "", title: metric };
}

export function ExplainerDrawer({
  metric,
  value,
  onClose,
}: {
  metric: string;
  value?: number | null;
  onClose: () => void;
}) {
  const explainer = explainerFor(metric);

  return (
    <Drawer
      title={explainer?.title ?? metric}
      subtitle={
        value === null || value === undefined
          ? "no value for this company"
          : `this company: ${value.toLocaleString(undefined, { maximumFractionDigits: 4 })}`
      }
      onClose={onClose}
    >
      {!explainer ? (
        <p className="text-sm text-text-muted">
          No explainer written for <code className="tabular">{metric}</code> yet.
        </p>
      ) : (
        <div className="space-y-4">
          {SECTIONS.map(([key, heading]) => (
            <section key={key}>
              <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
                {heading}
              </h3>
              <p className="mt-1 text-sm leading-relaxed">{explainer[key]}</p>
            </section>
          ))}
        </div>
      )}
    </Drawer>
  );
}
