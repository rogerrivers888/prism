import { useState } from "react";
import { PRINCIPLES } from "../content/principles";
import { useGlossary } from "../components/GlossaryProvider";
import { PagePurpose } from "../components/PagePurpose";
import { useRegisterScreen } from "../components/ScreenContext";

export default function Principles() {
  const { prose } = useGlossary();
  const [open, setOpen] = useState<string>(PRINCIPLES[0].slug);

  useRegisterScreen("Principles", { reading: open }, [
    "Summarise this page for someone with no finance background",
    "What is the single most important idea here?",
  ]);

  return (
    <div className="mx-auto max-w-3xl p-6">
      <header>
        <h1 className="font-display text-2xl uppercase tracking-wide">Principles</h1>
        <div className="mt-3 max-w-3xl">
          <PagePurpose
            id="principles"
            title="Principles"
            what="Why Prism works the way it does, in four short pieces. Most of it is about why investing ideas that look good usually are not, which is the single most useful thing here."
            firstStep="reading 'Why we test the way we do'. It ends with a real example: an idea that looked profitable until it was compared with doing nothing, and then wasn't."
          />
        </div>
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
