import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL } from "./config";

export type ExternalLink = { label: string; url: string; source_type: string };

export type GlossaryTerm = {
  slug: string;
  term: string;
  aliases: string[];
  short_definition: string;
  full_explanation: string;
  worked_example: string | null;
  how_to_read_it: string | null;
  common_mistakes: string | null;
  related_slugs: string[];
  external_links: ExternalLink[];
  category: string;
  user_note: string | null;
  user_note_updated_at: string | null;
};

export function useGlossaryTerms() {
  return useQuery<GlossaryTerm[]>({
    queryKey: ["glossary"],
    // The glossary changes only when the seed does, and every screen needs it
    // to auto-link prose, so it is fetched once and kept.
    staleTime: 60 * 60 * 1000,
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/glossary`);
      if (!response.ok) throw new Error("could not load the glossary");
      return response.json();
    },
  });
}

export function useSaveNote() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, { slug: string; note: string }>({
    mutationFn: async ({ slug, note }) => {
      const response = await fetch(`${API_BASE_URL}/glossary/${slug}/note`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ note }),
      });
      if (!response.ok) throw new Error("could not save the note");
      return response.json();
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["glossary"] }),
  });
}

export const CATEGORY_LABEL: Record<string, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  trend: "Trend",
  momentum: "Momentum",
  cycle: "Cycle",
  context: "Context",
  lens: "The six lenses",
  platform: "How Prism works",
  backtest: "Backtesting and statistics",
};
