import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "./config";
import type { components } from "./schema";

/** Types come from the backend's OpenAPI schema, so a backend change that
 *  breaks this screen shows up as a type error rather than at runtime. */
export type UniverseOut = components["schemas"]["UniverseOut"];
export type UniverseRow = components["schemas"]["UniverseRow"];
export type LensCell = components["schemas"]["LensCell"];

export const LENSES = [
  "trend",
  "growth",
  "quality",
  "value",
  "momentum",
  "cycle",
] as const;
export type LensName = (typeof LENSES)[number];

/** Tailwind cannot see a class name built at runtime, so the mapping is
 *  spelled out and stays statically analysable. */
export const LENS_BAR_CLASS: Record<LensName, string> = {
  trend: "bg-lens-trend",
  growth: "bg-lens-growth",
  quality: "bg-lens-quality",
  value: "bg-lens-value",
  momentum: "bg-lens-momentum",
  cycle: "bg-lens-cycle",
};

/** Statically spelled out, like the others: a class name assembled at runtime
 *  is invisible to Tailwind's scanner and silently produces no style. */
export const LENS_STROKE_CLASS: Record<LensName, string> = {
  trend: "stroke-lens-trend",
  growth: "stroke-lens-growth",
  quality: "stroke-lens-quality",
  value: "stroke-lens-value",
  momentum: "stroke-lens-momentum",
  cycle: "stroke-lens-cycle",
};

export const LENS_TEXT_CLASS: Record<LensName, string> = {
  trend: "text-lens-trend",
  growth: "text-lens-growth",
  quality: "text-lens-quality",
  value: "text-lens-value",
  momentum: "text-lens-momentum",
  cycle: "text-lens-cycle",
};

export async function fetchUniverse(): Promise<UniverseOut> {
  const response = await fetch(`${API_BASE_URL}/universe`);
  if (!response.ok) {
    throw new Error(`universe request failed: ${response.status}`);
  }
  return response.json();
}

export function useUniverse() {
  return useQuery({
    queryKey: ["universe"],
    queryFn: fetchUniverse,
    // Scores change once a night; refetching on every focus is pure noise.
    staleTime: 5 * 60 * 1000,
  });
}
