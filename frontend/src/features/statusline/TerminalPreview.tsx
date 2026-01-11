import { cn } from "@/lib/utils";

interface TerminalPreviewProps {
  output: string;
  loading?: boolean;
  error?: string | null;
  className?: string;
}

export function TerminalPreview({
  output,
  loading,
  error,
  className,
}: TerminalPreviewProps) {
  return (
    <div
      className={cn(
        "rounded-lg border-2 border-zinc-700 overflow-hidden",
        className
      )}
    >
      {/* Terminal title bar */}
      <div className="flex items-center gap-2 px-3 py-2 bg-zinc-800 border-b border-zinc-700">
        <div className="flex gap-1.5">
          <div className="w-3 h-3 rounded-full bg-red-500" />
          <div className="w-3 h-3 rounded-full bg-yellow-500" />
          <div className="w-3 h-3 rounded-full bg-green-500" />
        </div>
        <span className="text-xs text-zinc-400 ml-2">Status Line Preview</span>
      </div>

      {/* Terminal content */}
      <div className="bg-zinc-900 p-4 min-h-[60px] flex items-center">
        {loading ? (
          <span className="text-zinc-500 font-mono text-sm animate-pulse">
            Executing script...
          </span>
        ) : error ? (
          <span className="text-red-400 font-mono text-sm">{error}</span>
        ) : (
          <span className="text-green-400 font-mono text-sm whitespace-pre-wrap">
            {output || "(empty output)"}
          </span>
        )}
      </div>
    </div>
  );
}
