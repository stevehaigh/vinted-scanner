/**
 * Vinted search-URL import.
 *
 * The field table is imported from the Python package so the TypeScript and
 * Python parsers cannot drift apart.
 */
import spec from "../../src/scanner/sources/vinted_params.json";
import type { Query } from "./types";

interface Field {
  name: string;
  url_param: string;
  list: boolean;
  label: string;
  input: string;
}

export const FIELDS: Field[] = spec.fields;
export const HOSTS: string[] = spec.hosts;
export const DEFAULTS: Record<string, string | number> = spec.defaults;

export function parseSearchUrl(raw: string): Query {
  const url = new URL(raw.includes("//") ? raw : `https://${raw}`);
  const query: Query = { host: url.hostname };

  for (const field of FIELDS) {
    const values = url.searchParams.getAll(field.url_param).filter(Boolean);
    if (values.length === 0) continue;
    query[field.name] = field.list ? values : values[0];
  }
  for (const [key, value] of Object.entries(DEFAULTS)) {
    if (query[key] === undefined) query[key] = value;
  }
  return query;
}

/** A slug good enough to be a watch id, derived from the search text. */
export function suggestId(query: Query): string {
  const text = String(query.search_text ?? "watch")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40);
  return text || "watch";
}
