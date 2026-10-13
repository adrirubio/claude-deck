import { formatServerTime, parseServerTime } from "@/lib/serverTime";

function ago(value: string) {
  const minutes = Math.floor((Date.now() - parseServerTime(value).getTime()) / 60000);
  if (!Number.isFinite(minutes) || minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

// A short age for dense lists. The exact local time is in the hover text and
// in the text that a screen reader and a text search read.
export function RelativeTime({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted-foreground">Unknown</span>;
  return (
    <time dateTime={value} title={formatServerTime(value)} className="text-muted-foreground">
      <span aria-hidden="true">{ago(value)}</span>
      {" "}
      <span className="sr-only">{formatServerTime(value)}</span>
    </time>
  );
}
