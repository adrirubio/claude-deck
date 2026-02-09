import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { ChevronDown, ChevronRight, Info } from 'lucide-react'
import type { ContextComposition, ContextCompositionCategory } from '@/types/context'

interface ContextCompositionChartProps {
  composition?: ContextComposition
  showHelp?: boolean
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function BarSegment({
  category,
  widthPct,
}: {
  category: ContextCompositionCategory
  widthPct: number
}) {
  if (widthPct < 0.3) return null

  return (
    <div
      className="h-full relative group"
      style={{ width: `${widthPct}%`, backgroundColor: category.color }}
      title={`${category.category}: ${formatTokens(category.estimated_tokens)} (${category.percentage}%)`}
    >
      {widthPct > 6 && (
        <span className="absolute inset-0 flex items-center justify-center text-[10px] text-white font-medium truncate px-1">
          {category.percentage >= 1 ? `${Math.round(category.percentage)}%` : '<1%'}
        </span>
      )}
    </div>
  )
}

function CategoryRow({
  category,
  isExpandable,
}: {
  category: ContextCompositionCategory
  isExpandable: boolean
}) {
  const [expanded, setExpanded] = useState(false)

  const sortedItems = category.items
    ? [...category.items].sort((a, b) => b.estimated_tokens - a.estimated_tokens)
    : []

  return (
    <>
      <tr
        className={isExpandable ? 'cursor-pointer hover:bg-muted/50' : ''}
        onClick={isExpandable ? () => setExpanded(!expanded) : undefined}
      >
        <td className="py-1.5 pr-3">
          <div className="flex items-center gap-2">
            {isExpandable ? (
              expanded ? (
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
              )
            ) : (
              <span className="w-3.5 flex-shrink-0" />
            )}
            <span
              className="inline-block w-3 h-3 rounded-sm flex-shrink-0"
              style={{ backgroundColor: category.color }}
            />
            <span className="text-sm">{category.category}</span>
          </div>
        </td>
        <td className="py-1.5 text-right text-sm tabular-nums pr-3">
          {formatTokens(category.estimated_tokens)}
        </td>
        <td className="py-1.5 text-right text-sm text-muted-foreground tabular-nums">
          {category.percentage}%
        </td>
      </tr>
      {expanded && sortedItems.map((item) => (
        <tr key={item.name} className="text-muted-foreground">
          <td className="py-0.5 pr-3">
            <div className="flex items-center gap-2 pl-9">
              <span className="text-xs truncate max-w-[220px]" title={item.name}>
                {item.name}
              </span>
            </div>
          </td>
          <td className="py-0.5 text-right text-xs tabular-nums pr-3">
            {formatTokens(item.estimated_tokens)}
          </td>
          <td className="py-0.5" />
        </tr>
      ))}
    </>
  )
}

export function ContextCompositionChart({ composition, showHelp }: ContextCompositionChartProps) {
  if (!composition || composition.categories.length === 0) {
    return null
  }

  // Filter out categories with 0 tokens except Free Space
  const visibleCategories = composition.categories.filter(
    (c) => c.estimated_tokens > 0 || c.category === 'Free Space'
  )

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Context Composition</CardTitle>
        {showHelp && (
          <CardDescription>
            Breaks down what is consuming space in the context window. Expand any category to see individual items.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Stacked horizontal bar */}
        <div className="flex h-7 rounded-md overflow-hidden border">
          {visibleCategories.map((cat) => (
            <BarSegment
              key={cat.category}
              category={cat}
              widthPct={(cat.estimated_tokens / composition.context_limit) * 100}
            />
          ))}
        </div>

        {/* Legend table */}
        <table className="w-full">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="text-left pb-1 font-medium">Category</th>
              <th className="text-right pb-1 font-medium pr-3">Tokens</th>
              <th className="text-right pb-1 font-medium">%</th>
            </tr>
          </thead>
          <tbody>
            {visibleCategories.map((cat) => (
              <CategoryRow
                key={cat.category}
                category={cat}
                isExpandable={!!cat.items && cat.items.length > 0}
              />
            ))}
          </tbody>
        </table>
        {showHelp && (
          <div className="bg-muted p-3 rounded text-xs space-y-1 mt-3">
            <p className="font-medium flex items-center gap-1.5">
              <Info className="h-3.5 w-3.5" />
              Category Glossary
            </p>
            <p><span className="font-medium">System Prompt</span> — Claude's base instructions and personality.</p>
            <p><span className="font-medium">System Tools</span> — built-in tool definitions (Read, Write, Bash, etc.).</p>
            <p><span className="font-medium">MCP Tools</span> — tools from connected MCP servers.</p>
            <p><span className="font-medium">Agents</span> — custom agent definitions loaded for this project.</p>
            <p><span className="font-medium">Memory</span> — CLAUDE.md files and project memory loaded at startup.</p>
            <p><span className="font-medium">Skills</span> — skill definitions available in this session.</p>
            <p><span className="font-medium">Messages</span> — the actual conversation (prompts, responses, tool results).</p>
            <p><span className="font-medium">Autocompact Buffer</span> — space reserved for auto-compaction.</p>
            <p><span className="font-medium">Free Space</span> — remaining capacity for more conversation.</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
