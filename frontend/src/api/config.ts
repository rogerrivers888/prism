/** Where the API lives.
 *
 * Vite inlines `import.meta.env.VITE_*` at BUILD time, not at runtime — the
 * value is baked into the bundle. Setting VITE_API_BASE_URL on the running
 * service therefore does nothing; it has to be present when `npm run build`
 * executes. On Railway, service variables are available to the build step,
 * so setting it on the service is enough.
 *
 * Unset, this falls back to the deployed API rather than to an empty string.
 * That means a missing variable produces a working app pointed at production,
 * not a silent failure to reach anything — but it also means a build intended
 * for a different backend would quietly talk to the live one, so the fallback
 * announces itself in the console and the UI names the URL it tried.
 */
const DEFAULT_API_BASE_URL = "https://api-production-f9083.up.railway.app";

const configured = import.meta.env.VITE_API_BASE_URL;

export const API_BASE_URL: string = configured ?? DEFAULT_API_BASE_URL;

/** True when no VITE_API_BASE_URL was set at build time. */
export const API_BASE_URL_IS_DEFAULT = !configured;

if (API_BASE_URL_IS_DEFAULT) {
  console.info(
    `[prism] VITE_API_BASE_URL was not set at build time; using the default API at ${DEFAULT_API_BASE_URL}`,
  );
}
