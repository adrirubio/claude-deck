const HAS_TIME_ZONE = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i

/** Parse API timestamps as UTC when they omit an explicit time zone. */
export function parseServerTime(value: string): Date {
  const timestamp = value.includes('T') && !HAS_TIME_ZONE.test(value)
    ? `${value}Z`
    : value
  return new Date(timestamp)
}

export function formatServerTime(value: string, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(undefined, options).format(parseServerTime(value))
}
