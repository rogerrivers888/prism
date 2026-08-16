/** WCAG AA contrast, asserted rather than eyeballed.
 *
 * The previous prototype failed on muted greys and Roger could not read them,
 * so every text/background pair the UI actually uses is checked here in both
 * themes. Values mirror the tokens in src/index.css. */
import { describe, expect, it } from "vitest";

type Oklch = { l: number; c: number; h: number };

const LIGHT = {
  surface: { l: 0.985, c: 0.003, h: 250 },
  surfaceRaised: { l: 1.0, c: 0, h: 0 },
  surfaceSunken: { l: 0.955, c: 0.005, h: 250 },
  text: { l: 0.24, c: 0.012, h: 250 },
  textMuted: { l: 0.46, c: 0.014, h: 250 },
  positive: { l: 0.52, c: 0.14, h: 152 },
  negative: { l: 0.53, c: 0.17, h: 25 },
  warning: { l: 0.58, c: 0.14, h: 75 },
} satisfies Record<string, Oklch>;

const DARK = {
  surface: { l: 0.19, c: 0.012, h: 255 },
  surfaceRaised: { l: 0.235, c: 0.014, h: 255 },
  surfaceSunken: { l: 0.15, c: 0.01, h: 255 },
  text: { l: 0.95, c: 0.006, h: 255 },
  textMuted: { l: 0.76, c: 0.014, h: 255 },
  positive: { l: 0.76, c: 0.15, h: 152 },
  negative: { l: 0.7, c: 0.16, h: 25 },
  warning: { l: 0.8, c: 0.13, h: 75 },
} satisfies Record<string, Oklch>;

/** OKLCH -> linear sRGB -> WCAG relative luminance. */
function relativeLuminance({ l, c, h }: Oklch): number {
  const hr = (h * Math.PI) / 180;
  const a = c * Math.cos(hr);
  const b = c * Math.sin(hr);

  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;

  const L = l_ ** 3;
  const M = m_ ** 3;
  const S = s_ ** 3;

  const toLinear = (v: number) => v;
  const r = toLinear(4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S);
  const g = toLinear(-1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S);
  const bl = toLinear(-0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S);

  const clamp = (v: number) => Math.max(0, Math.min(1, v));
  return 0.2126 * clamp(r) + 0.7152 * clamp(g) + 0.0722 * clamp(bl);
}

function contrast(a: Oklch, b: Oklch): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

const AA_NORMAL = 4.5;

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
])("%s theme meets WCAG AA", (_name, T) => {
  const backgrounds = [
    ["surface", T.surface],
    ["surface-raised", T.surfaceRaised],
    ["surface-sunken", T.surfaceSunken],
  ] as const;

  it.each(backgrounds)("body text on %s", (_bg, background) => {
    expect(contrast(T.text, background)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  // The pair that failed last time.
  it.each(backgrounds)("muted text on %s", (_bg, background) => {
    expect(contrast(T.textMuted, background)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it.each(backgrounds)("warning text on %s", (_bg, background) => {
    expect(contrast(T.warning, background)).toBeGreaterThanOrEqual(3);
  });
});

