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

## Deployment

Railpack builds a Node image from `package.json`, so the container has Node and
nothing else — no Caddy, no nginx. `dist/` is served by `serve`, which is a
runtime dependency for exactly that reason:

```
npx serve -s dist -l $PORT
```

`-s` rewrites unknown paths to `index.html`, so client-side routes resolve
instead of 404ing.

**`VITE_API_BASE_URL` is read at BUILD time, not runtime.** Vite inlines it
into the bundle, so setting it on a running service has no effect — it must be
present when `npm run build` runs. Railway exposes service variables to the
build step, so setting it on the service is enough, but a change to it requires
a rebuild, not just a restart. Unset, the app falls back to the deployed API
and says so in the console; if a request then fails, the error names the URL it
tried.

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
