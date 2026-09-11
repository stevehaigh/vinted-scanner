import { useCallback, useEffect, useState } from "react";
import yaml from "js-yaml";
import Finds from "./Finds";
import WatchCard from "./WatchCard";
import * as gh from "./github";
import { parseSearchUrl, suggestId } from "./vinted";
import type { ScanEvent, Watch, WatchFile } from "./types";

const WATCHES_PATH = "watches.yaml";

/** The scanner accepts `notify_on: price_drop` as shorthand for a one-item list. */
function asList(value: string | string[]): string[] {
  return Array.isArray(value) ? value : [value];
}

/** What scanner.config.parse would reject, caught before it can break every scan. */
function invalidWatches(watches: Watch[]): string {
  const seen = new Set<string>();
  for (const w of watches) {
    // Hand-edited YAML can carry a numeric id or no query at all.
    const id = String(w.id ?? "").trim();
    if (!id) return "Every watch needs an ID.";
    if (seen.has(id)) return `Two watches share the ID "${id}".`;
    seen.add(id);
    if (!w.query || typeof w.query !== "object") return `Watch "${id}" needs a query.`;
    if (w.platform === "shopify" && !String(w.query.base_url ?? "").trim())
      return `Watch "${id}" needs a store URL.`;
  }
  return "";
}

type Tab = "watches" | "finds";

export default function App() {
  const [tab, setTab] = useState<Tab>("watches");
  const [token, setTokenState] = useState(gh.getToken());
  const [watches, setWatches] = useState<Watch[]>([]);
  const [sha, setSha] = useState<string>();
  const [events, setEvents] = useState<ScanEvent[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [pastedUrl, setPastedUrl] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [file, log] = await Promise.all([
        gh.readFile(WATCHES_PATH),
        gh.readRaw(gh.currentMonthPath()),
      ]);
      if (file) {
        const parsed = yaml.load(file.text) as WatchFile;
        setWatches(
          (parsed?.watches ?? []).map((w) => ({
            ...w,
            enabled: w.enabled ?? true,
            notify_on: asList(w.notify_on ?? parsed?.defaults?.notify_on ?? ["new_listing"]),
          })),
        );
        setSha(file.sha);
      }
      setEvents(
        log
          ? log
              .trim()
              .split("\n")
              .filter(Boolean)
              .map((line) => JSON.parse(line) as ScanEvent)
              .reverse()
              .slice(0, 200)
          : [],
      );
      setDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Don't let a phone tab-switch quietly discard unsaved watches.
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const update = (next: Watch[]) => {
    setWatches(next);
    setDirty(true);
    setNote("");
  };

  const save = async () => {
    const problem = invalidWatches(watches);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body: WatchFile = { version: 1, watches };
      const text =
        "# Managed by the scanner UI and by hand. Both are fine.\n" +
        yaml.dump(body, { lineWidth: 100, noRefs: true });
      const newSha = await gh.writeFile(
        WATCHES_PATH,
        text,
        sha,
        `watches: update from UI (${watches.length} watches)`,
      );
      setSha(newSha);
      setDirty(false);
      setNote("Saved. The next scheduled scan will pick it up.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const addFromUrl = () => {
    setError("");
    try {
      const query = parseSearchUrl(pastedUrl);
      const base = suggestId(query);
      const taken = new Set(watches.map((w) => w.id));
      let id = base;
      for (let n = 2; taken.has(id); n += 1) id = `${base}-${n}`;

      update([
        ...watches,
        { id, label: "", platform: "vinted", enabled: true, notify_on: ["new_listing"], query },
      ]);
      setPastedUrl("");
      setTab("watches");
    } catch {
      setError("That doesn't look like a Vinted search URL.");
    }
  };

  const addBlank = (platform: string) => {
    const taken = new Set(watches.map((w) => w.id));
    let id = `new-${platform}`;
    for (let n = 2; taken.has(id); n += 1) id = `new-${platform}-${n}`;
    update([
      ...watches,
      {
        id,
        label: "",
        platform,
        enabled: false,
        notify_on: platform === "vinted" ? ["new_listing"] : ["price_drop"],
        query: platform === "vinted" ? { host: "www.vinted.co.uk", order: "newest_first" } : {},
      },
    ]);
  };

  const saveToken = (value: string) => {
    gh.setToken(value.trim());
    setTokenState(value.trim());
    void load();
  };

  return (
    <div className="wrap">
      <header>
        <h1>Scanner</h1>
        <span className="repo">{gh.REPO}</span>
      </header>

      <nav>
        <button role="tab" aria-selected={tab === "watches"} onClick={() => setTab("watches")}>
          Watches {watches.length > 0 && `(${watches.length})`}
        </button>
        <button role="tab" aria-selected={tab === "finds"} onClick={() => setTab("finds")}>
          Recent finds {events.length > 0 && `(${events.length})`}
        </button>
      </nav>

      {error && <div className="banner error">{error}</div>}
      {note && <div className="banner ok">{note}</div>}

      {!token && (
        <div className="card">
          <label htmlFor="token">GitHub token</label>
          <input
            id="token"
            type="password"
            placeholder="github_pat_…"
            onBlur={(e) => saveToken(e.target.value)}
          />
          <p className="muted" style={{ marginBottom: 0 }}>
            A fine-grained token with <strong>Contents: read and write</strong> on this repository
            only. Stored in this browser, sent only to api.github.com. Needed to save; reading a
            public repo works without one.
          </p>
        </div>
      )}

      {tab === "watches" ? (
        <>
          <div className="card">
            <label htmlFor="paste">Add from a Vinted search URL</label>
            <input
              id="paste"
              type="text"
              value={pastedUrl}
              placeholder="https://www.vinted.co.uk/catalog?search_text=…"
              onChange={(e) => setPastedUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && pastedUrl && addFromUrl()}
            />
            <div className="actions">
              <button className="btn primary" onClick={addFromUrl} disabled={!pastedUrl}>
                Import
              </button>
              <button className="btn" onClick={() => addBlank("vinted")}>
                Blank Vinted watch
              </button>
              <button className="btn" onClick={() => addBlank("shopify")}>
                Blank Shopify watch
              </button>
            </div>
          </div>

          {busy && watches.length === 0 && <p className="muted">Loading…</p>}

          {watches.map((watch, index) => (
            <WatchCard
              key={index}
              watch={watch}
              onChange={(next) => update(watches.map((w, i) => (i === index ? next : w)))}
              onRemove={() => update(watches.filter((_, i) => i !== index))}
            />
          ))}

          <div className="actions">
            <button className="btn primary" onClick={save} disabled={!dirty || busy || !token}>
              {busy ? "Saving…" : "Save to GitHub"}
            </button>
            <button className="btn subtle" onClick={() => void load()} disabled={busy}>
              Reload
            </button>
            {dirty && <span className="muted">Unsaved changes</span>}
            {token && (
              <button className="btn subtle" onClick={() => saveToken("")}>
                Forget token
              </button>
            )}
          </div>
        </>
      ) : (
        <Finds events={events} />
      )}
    </div>
  );
}
