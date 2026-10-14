import type { ReminderAttention } from '@/types/agentTeams'

// Plain words for the unanswered-reminder signal (#528). The wire is not trusted:
// a row of an unknown kind, or with values of the wrong type, is ignored.

export interface ReminderRow {
  kind: ReminderAttention['kind']
  workItemId: number | null
  issueNumber: number | null
  issueNumbers: number[]
  owner: string | null
  count: number
  cap: number
  elapsedSeconds: number | null
}

const positive = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0

const nonNegative = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

export function parseReminders(value: unknown): ReminderRow[] {
  if (!Array.isArray(value)) return []
  const rows: ReminderRow[] = []
  for (const entry of value.slice(0, 64)) {
    if (!entry || typeof entry !== 'object') continue
    const row = entry as Record<string, unknown>
    if (row.kind !== 'workspace_release' && row.kind !== 'backlog_reconcile') continue
    if (!nonNegative(row.reminder_count) || !positive(row.reminder_cap)) continue
    const issueNumber = positive(row.issue_number) ? row.issue_number : null
    if (row.kind === 'workspace_release' && issueNumber === null) continue
    const issueNumbers = Array.isArray(row.issue_numbers) ? row.issue_numbers.filter(positive).slice(0, 8) : []
    rows.push({
      kind: row.kind,
      workItemId: positive(row.work_item_id) ? row.work_item_id : null,
      issueNumber,
      issueNumbers,
      owner: typeof row.owner_name === 'string' && row.owner_name.trim() ? row.owner_name.trim().slice(0, 160) : null,
      count: row.reminder_count,
      cap: row.reminder_cap,
      elapsedSeconds: nonNegative(row.elapsed_seconds) ? row.elapsed_seconds : null,
    })
  }
  return rows
}

/** "6 h", "12 min", "under 1 min", "2 d". */
export function reminderAge(seconds: number | null): string | null {
  if (seconds === null) return null
  const minutes = Math.floor(seconds / 60)
  if (minutes < 1) return 'under 1 min'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  return hours < 48 ? `${hours} h` : `${Math.floor(hours / 24)} d`
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`

/** The whole sentence in one piece, so the Overview shows one item for one signal. */
export function reminderSentence(row: ReminderRow): string {
  const age = reminderAge(row.elapsedSeconds)
  const owner = row.owner ?? (row.kind === 'workspace_release' ? 'The owner' : 'The Leader')
  if (row.kind === 'workspace_release') {
    return `Release needed: ${owner} still holds the workspace of #${row.issueNumber} after ${plural(row.count, 'reminder', 'reminders')}${age ? ` (${age})` : ''}`
  }
  const issues = row.issueNumbers.length ? ` (${row.issueNumbers.map((n) => `#${n}`).join(', ')})` : ''
  return `${owner} has not assessed the backlog${issues} after ${row.count} of ${row.cap} requests${age ? ` (${age})` : ''}`
}
