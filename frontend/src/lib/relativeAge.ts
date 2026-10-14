import { parseServerTime } from "@/lib/serverTime";

// A short age: "just now", "5 min ago", "3 h ago", "2 d ago".
export function relativeAge(value: string, now = Date.now()) {
  const minutes = Math.floor((now - parseServerTime(value).getTime()) / 60000);
  if (!Number.isFinite(minutes) || minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}
