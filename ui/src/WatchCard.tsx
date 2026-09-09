import { FIELDS } from "./vinted";
import { RULES, type Query, type Watch } from "./types";

interface Props {
  watch: Watch;
  onChange: (next: Watch) => void;
  onRemove: () => void;
}

const SHOPIFY_FIELDS = [
  { name: "base_url", label: "Store URL", input: "text" },
  { name: "collection", label: "Collection", input: "text" },
  { name: "max_products", label: "Max products", input: "number" },
];

export default function WatchCard({ watch, onChange, onRemove }: Props) {
  const set = (patch: Partial<Watch>) => onChange({ ...watch, ...patch });

  const setQuery = (name: string, raw: string, isList: boolean) => {
    const query: Query = { ...watch.query };
    if (raw.trim() === "") {
      delete query[name];
    } else {
      query[name] = isList ? raw.split(",").map((v) => v.trim()).filter(Boolean) : raw;
    }
    set({ query });
  };

  const toggleRule = (rule: string) => {
    const notify_on = watch.notify_on.includes(rule)
      ? watch.notify_on.filter((r) => r !== rule)
      : [...watch.notify_on, rule];
    set({ notify_on: notify_on.length ? notify_on : ["new_listing"] });
  };

  const fields =
    watch.source === "vinted"
      ? FIELDS.map((f) => ({ name: f.name, label: f.label, input: f.input, list: f.list }))
      : SHOPIFY_FIELDS.map((f) => ({ ...f, list: false }));

  return (
    <div className={`card${watch.enabled ? "" : " disabled"}`}>
      <div className="card-head">
        <label className="switch" title={watch.enabled ? "Enabled" : "Disabled"}>
          <input
            type="checkbox"
            checked={watch.enabled}
            onChange={(e) => set({ enabled: e.target.checked })}
          />
        </label>
        <input
          type="text"
          value={watch.label ?? ""}
          placeholder={watch.id}
          aria-label="Watch label"
          onChange={(e) => set({ label: e.target.value })}
          style={{ flex: "1 1 200px", width: "auto", fontWeight: 600 }}
        />
        <span className="chip">{watch.source}</span>
        <button className="btn danger" onClick={onRemove} aria-label={`Remove ${watch.id}`}>
          Remove
        </button>
      </div>

      <div className="grid">
        <div>
          <label htmlFor={`${watch.id}-id`}>Watch ID</label>
          <input
            id={`${watch.id}-id`}
            type="text"
            value={watch.id}
            onChange={(e) => set({ id: e.target.value })}
          />
        </div>
        {watch.source === "vinted" && (
          <div>
            <label htmlFor={`${watch.id}-host`}>Vinted site</label>
            <input
              id={`${watch.id}-host`}
              type="text"
              value={String(watch.query.host ?? "")}
              onChange={(e) => setQuery("host", e.target.value, false)}
            />
          </div>
        )}
        {fields.map((field) => {
          const value = watch.query[field.name];
          return (
            <div key={field.name}>
              <label htmlFor={`${watch.id}-${field.name}`}>{field.label}</label>
              <input
                id={`${watch.id}-${field.name}`}
                type={field.input === "number" ? "number" : "text"}
                value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
                placeholder={field.list ? "comma separated" : ""}
                onChange={(e) => setQuery(field.name, e.target.value, field.list)}
              />
            </div>
          );
        })}
      </div>

      <div className="actions">
        <span className="muted">Notify on</span>
        {RULES.map((rule) => (
          <label key={rule} className="switch">
            <input
              type="checkbox"
              checked={watch.notify_on.includes(rule)}
              onChange={() => toggleRule(rule)}
            />
            {rule.replace(/_/g, " ")}
          </label>
        ))}
      </div>
    </div>
  );
}
