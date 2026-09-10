import type { ScanEvent } from "./types";

const SYMBOLS: Record<string, string> = { GBP: "£", EUR: "€", USD: "$" };

function price(event: ScanEvent): string {
  const amount = event.attributes.price;
  if (amount == null) return "";
  const symbol = SYMBOLS[String(event.attributes.currency ?? "")] ?? "";
  return `${symbol}${amount}`;
}

function detail(event: ScanEvent): string {
  return ["brand", "size", "condition", "variant"]
    .map((key) => event.attributes[key])
    .filter((v) => v && v !== "Default Title")
    .join(" · ");
}

function headline(event: ScanEvent): string | null {
  if (event.kind === "appeared") return null;
  if (event.changes.price) {
    const [before, after] = event.changes.price;
    return `price ${before} → ${after}`;
  }
  if (event.changes.available) {
    return event.changes.available[1] ? "back in stock" : "sold out";
  }
  return Object.keys(event.changes).join(", ");
}

export default function Finds({ events }: { events: ScanEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="muted">
        Nothing recorded this month yet. The scanner writes here when it finds something new.
      </p>
    );
  }

  return (
    <div className="card">
      {events.map((event) => {
        const flag = headline(event);
        const image = event.extra.image as string | undefined;
        return (
          <div className="find" key={`${event.entity_key}:${event.at}`}>
            {image ? <img src={image} alt="" loading="lazy" /> : <div className="find-noimg" />}
            <div style={{ minWidth: 0 }}>
              <a href={event.url} target="_blank" rel="noreferrer">
                {event.title}
              </a>
              {flag && <span className="chip" style={{ marginLeft: 6 }}>{flag}</span>}
              <div className="price">{price(event)}</div>
              <div className="meta">
                {detail(event)}
                {detail(event) && " · "}
                {new Date(event.at).toLocaleString()}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
