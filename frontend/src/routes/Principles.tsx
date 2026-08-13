import { useState } from "react";
import { PRINCIPLES } from "../content/principles";
import { useGlossary } from "../components/GlossaryProvider";

export default function Principles() {
  const { prose } = useGlossary();
  const [open, setOpen] = useState<string>(PRINCIPLES[0].slug);

  return (
    <div className="mx-auto max-w-3xl p-6">
      <header>
        <h1 className="font-display text-2xl uppercase tracking-wide">Principles</h1>
        <p className="mt-1 text-sm text-text-muted">
          What Prism has settled on and why, written down so the reasoning survives.
          About ten minutes to reread the whole thing.
        </p>
      </header>

      <nav className="mt-4 flex flex-wrap gap-1.5">
        {PRINCIPLES.map((principle) => (
          <button
            key={principle.slug}
            type="button"
            onClick={() => setOpen(principle.slug)}
            aria-pressed={open === principle.slug}
            className={`rounded border px-2.5 py-1 text-xs ${
              open === principle.slug
                ? "border-border bg-surface-sunken font-medium"
                : "border-border text-text-muted"
            }`}
          >
            {principle.title}
          </button>
        ))}
      </nav>

      {PRINCIPLES.filter((p) => p.slug === open).map((principle) => (
        <article key={principle.slug} className="mt-6">
          <h2 className="font-display text-xl font-semibold">{principle.title}</h2>
          <p className="mt-1 text-sm italic text-text-muted">{principle.standfirst}</p>

          {principle.sections.map((section) => (
            <section key={section.heading} className="mt-6">
              <h3 className="font-display text-base font-semibold">{section.heading}</h3>
              {section.paragraphs.map((paragraph, index) => (
                <p key={index} className="mt-2 text-sm leading-relaxed">
                  {/* Glossary terms link on first mention across the whole page. */}
                  {prose(paragraph)}
                </p>
              ))}
            </section>
          ))}
        </article>
      ))}
    </div>
  );
}
