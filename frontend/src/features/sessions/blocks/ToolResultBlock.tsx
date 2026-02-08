import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChevronDown, ChevronUp } from 'lucide-react'

interface Props {
  tool_use_id: string
  content: string | Record<string, unknown> | unknown[]
  is_error: boolean
}

export function ToolResultBlock({ tool_use_id, content, is_error }: Props) {
  const [expanded, setExpanded] = useState(false)

  const contentStr = typeof content === 'string' ? content : JSON.stringify(content)
  const isTruncated = contentStr.length > 500
  const displayContent = expanded ? contentStr : contentStr.substring(0, 500)

  return (
    <div
      className={`border rounded-lg p-3 ${
        is_error
          ? 'border-red-500/50 bg-red-50/10'
          : 'border-green-500/50 bg-green-50/10'
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <Badge variant={is_error ? 'destructive' : 'outline'}>
          {is_error ? 'Error' : 'Result'}
        </Badge>
        <span className="text-xs text-muted-foreground">{tool_use_id}</span>
      </div>

      <pre className="text-xs whitespace-pre-wrap overflow-x-auto">
        {displayContent}
        {isTruncated && !expanded && '... (truncated)'}
      </pre>

      {isTruncated && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setExpanded(!expanded)}
          className="mt-2"
        >
          {expanded ? (
            <>
              <ChevronUp className="h-4 w-4 mr-1" />
              Show less
            </>
          ) : (
            <>
              <ChevronDown className="h-4 w-4 mr-1" />
              Show more
            </>
          )}
        </Button>
      )}
    </div>
  )
}
