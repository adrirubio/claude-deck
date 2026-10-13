export function Time({
  value,
  label = "Updated",
}: {
  value: string | null;
  label?: string;
}) {
  return (
    <span className="text-xs text-muted-foreground">
      {label}:{" "}
      {value ? (
        <time dateTime={value}>{new Date(value).toLocaleString()}</time>
      ) : (
        "Unknown"
      )}
    </span>
  );
}
