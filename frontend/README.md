# Prism frontend

React + Vite + TypeScript + Tailwind v4. No component library — the visual
language is specific and a kit would fight it.

## Running

```sh
npm install
npm run dev      # http://localhost:5173, talks to the deployed API by default
```

Point it somewhere else with `VITE_API_BASE_URL` (see `.env.example`).

## Commands

| command | does |
|---|---|
| `npm run dev` | dev server |
| `npm run build` | typecheck and build to `dist/` |
| `npm test` | vitest |
| `npm run typecheck` | tsc only |
| `npm run api:types` | regenerate `src/api/schema.d.ts` from the API's OpenAPI schema |

Run `api:types` after any backend change to the response shapes: the types are
generated, not hand-written, so a breaking change surfaces as a type error
rather than at runtime.

## Colour

All colour is CSS custom properties in OKLCH, with a light and a dark set in
`src/index.css`. Components reference semantic tokens (`surface`, `text-muted`,
`border`, …) and never raw colours.

The six lens hues live alone in `src/styles/lens-hues.css`. Lightness and
chroma are constant across all six — only hue angle varies — so no lens reads
as more important than another. Hue means one thing: which lens. Score is
carried by bar fill and opacity. To retune, edit the angles in that one file.

Contrast is asserted, not eyeballed: `src/theme/contrast.test.ts` checks every
text/background pair in both themes against WCAG AA.
