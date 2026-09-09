export type Query = Record<string, string | string[] | number | boolean>;

export interface Watch {
  id: string;
  label?: string;
  source: string;
  enabled: boolean;
  notify_on: string[];
  query: Query;
}

export interface WatchFile {
  version?: number;
  defaults?: { notify_on?: string[] };
  watches: Watch[];
}

/** One line of data/observations/YYYY-MM.jsonl. */
export interface ScanEvent {
  at: string;
  kind: "appeared" | "changed";
  watch_id: string;
  source: string;
  entity_key: string;
  url: string;
  title: string;
  attributes: Record<string, unknown>;
  extra: Record<string, unknown>;
  changes: Record<string, [unknown, unknown]>;
}

export const RULES = ["new_listing", "price_drop", "back_in_stock", "went_on_sale"] as const;
