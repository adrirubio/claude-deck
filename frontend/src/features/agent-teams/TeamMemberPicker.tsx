import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { groupPickItems, type PickItem } from './teamSources'

/** Checkbox rows, grouped by the team that already holds the member. */
export function TeamMemberPicker({
  items,
  selected,
  onToggle,
  loading,
  emptyText,
}: {
  items: PickItem[]
  selected: string[]
  onToggle: (id: string, checked: boolean) => void
  loading: boolean
  emptyText: string
}) {
  const groups = groupPickItems(items)
  return (
    <div className="max-h-64 space-y-3 overflow-y-auto rounded-md border p-2">
      {loading && <div className="p-3 text-sm text-muted-foreground">Loading…</div>}
      {!loading && items.length === 0 && <div className="p-3 text-sm text-muted-foreground">{emptyText}</div>}
      {!loading && groups.map((group) => (
        <section key={group.title} aria-label={group.title}>
          <h4 className="px-2 text-xs font-semibold uppercase text-muted-foreground">{group.title}</h4>
          {group.items.map((item) => (
            <label key={item.id} className="flex items-center gap-3 rounded-md px-2 py-2 text-sm">
              <Checkbox
                checked={selected.includes(item.id)}
                onCheckedChange={(checked) => onToggle(item.id, checked === true)}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{item.label}</span>
                <span className="block truncate text-xs text-muted-foreground">{item.detail}</span>
              </span>
              {item.team !== null && <Badge variant="secondary">in {item.team}</Badge>}
              {item.status && <Badge variant={item.status === 'offline' ? 'secondary' : 'outline'}>{item.status}</Badge>}
            </label>
          ))}
        </section>
      ))}
    </div>
  )
}
