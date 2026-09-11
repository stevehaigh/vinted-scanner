/**
 * Reads and writes this repository through the GitHub Contents API.
 *
 * The token is a fine-grained PAT scoped to this one repository's contents,
 * held in localStorage and never sent anywhere but api.github.com. The repo is
 * public, so its blast radius is content that is already public.
 */

const API = "https://api.github.com";
const TOKEN_KEY = "scanner.token";

export const REPO = (import.meta.env.VITE_REPO as string) ?? "stevehaigh/vinted-scanner";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private browsing; the app still works read-only for a public repo */
  }
}

export interface FileContent {
  text: string;
  sha: string;
}

export class GitHubError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function headers(): HeadersInit {
  const token = getToken();
  return {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function fail(response: Response, what: string): Promise<never> {
  const detail = await response.text().catch(() => "");
  let message = `${what} failed (HTTP ${response.status})`;
  if (response.status === 401) message = "Token rejected. Check it hasn't expired.";
  if (response.status === 403) message = "Token lacks Contents: read and write on this repo.";
  if (response.status === 409) message = "The file changed since you loaded it. Reload and retry.";
  throw new GitHubError(detail ? `${message} — ${detail.slice(0, 200)}` : message, response.status);
}

/** Returns null when the file does not exist, which is not an error. */
export async function readFile(path: string): Promise<FileContent | null> {
  const response = await fetch(`${API}/repos/${REPO}/contents/${path}`, {
    headers: headers(),
    cache: "no-store",
  });
  if (response.status === 404) return null;
  if (!response.ok) await fail(response, `Reading ${path}`);

  const body = await response.json();
  // atob gives Latin-1; round-trip through TextDecoder so accents survive.
  const bytes = Uint8Array.from(atob(body.content.replace(/\n/g, "")), (c) => c.charCodeAt(0));
  return { text: new TextDecoder().decode(bytes), sha: body.sha };
}

/** Plain text, for files the JSON Contents API refuses to inline (over 1 MB). */
export async function readRaw(path: string): Promise<string | null> {
  const response = await fetch(`${API}/repos/${REPO}/contents/${path}`, {
    headers: { ...headers(), Accept: "application/vnd.github.raw+json" },
    cache: "no-store",
  });
  if (response.status === 404) return null;
  if (!response.ok) await fail(response, `Reading ${path}`);
  return response.text();
}

export async function writeFile(
  path: string,
  text: string,
  sha: string | undefined,
  message: string,
): Promise<string> {
  if (!getToken()) throw new GitHubError("Add a GitHub token before saving.", 401);

  const content = btoa(String.fromCharCode(...new TextEncoder().encode(text)));
  const response = await fetch(`${API}/repos/${REPO}/contents/${path}`, {
    method: "PUT",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ message, content, ...(sha ? { sha } : {}) }),
  });
  if (!response.ok) await fail(response, `Saving ${path}`);
  return (await response.json()).content.sha;
}

export function currentMonthPath(date = new Date()): string {
  const month = `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
  return `data/observations/${month}.jsonl`;
}
