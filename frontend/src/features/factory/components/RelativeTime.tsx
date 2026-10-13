import { relativeAge } from "@/lib/relativeAge";
import { formatServerTime } from "@/lib/serverTime";

// A short age for dense lists. The exact local time is in the hover text and
// in the text that a screen reader and a text search read.
export function RelativeTime({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted-foreground">Unknown</span>;
  return (
    <time dateTime={value} title={formatServerTime(value)} className="text-muted-foreground">
      <span aria-hidden="true">{relativeAge(value)}</span>
      {" "}
      <span className="sr-only">{formatServerTime(value)}</span>
    </time>
  );
}
