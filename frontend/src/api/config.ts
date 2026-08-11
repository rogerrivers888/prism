/** API base URL. Falls back to the deployed backend so a fresh clone works. */
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  "https://api-production-f9083.up.railway.app";
