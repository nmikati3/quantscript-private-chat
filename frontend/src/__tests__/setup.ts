/**
 * Vitest global setup — runs before every test file.
 *
 * Stubs browser/Tauri APIs that are unavailable in the jsdom environment.
 */

// Stub import.meta.env values vitest doesn't provide automatically
if (!import.meta.env.VITE_API_BASE_URL) {
  (import.meta.env as Record<string, string>).VITE_API_BASE_URL = "";
}
