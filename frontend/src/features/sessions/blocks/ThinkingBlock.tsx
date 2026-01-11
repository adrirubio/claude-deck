import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  thinking: string
}

export function ThinkingBlock({ thinking }: Props) {
  const [collapsed, setCollapsed] = useState(true)

  return (
    <div className="border border-amber-500/50 rounded-lg p-3 bg-amber-50/10">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-1 text-amber-700 hover:text-amber-900"
      >
        {collapsed ? (
          <ChevronRight className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
        <span className="font-semibold">Thinking</span>
      </Button>

      {!collapsed && (
        <div className="mt-2 text-sm whitespace-pre-wrap text-amber-900">
          {thinking}
        </div>
      )}
    </div>
  )
}
