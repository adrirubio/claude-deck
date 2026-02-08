import { Badge } from '@/components/ui/badge'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

interface Props {
  name: string
  id: string
  input: Record<string, unknown>
}

export function ToolUseBlock({ name, id, input }: Props) {
  // Specialized renderers for common tools
  if (name === 'Bash') {
    return (
      <div className="border border-purple-500/50 rounded-lg p-3 bg-purple-50/10">
        <div className="flex items-center gap-2 mb-2">
          <Badge variant="outline" className="text-purple-700">Bash</Badge>
          <span className="text-xs text-muted-foreground">{id}</span>
        </div>
        <SyntaxHighlighter language="bash" style={oneDark} PreTag="div">
          {(input.command as string) || ''}
        </SyntaxHighlighter>
      </div>
    )
  }

  if (name === 'Write' || name === 'Edit') {
    return (
      <div className="border border-blue-500/50 rounded-lg p-3 bg-blue-50/10">
        <div className="flex items-center gap-2 mb-2">
          <Badge variant="outline" className="text-blue-700">{name}</Badge>
          <span className="text-xs text-muted-foreground">{(input.file_path as string) || ''}</span>
        </div>
        {typeof input.content === 'string' && (
          <SyntaxHighlighter language="typescript" style={oneDark} PreTag="div">
            {input.content.substring(0, 500) + (input.content.length > 500 ? '\n... (truncated)' : '')}
          </SyntaxHighlighter>
        )}
      </div>
    )
  }

  // Generic tool use
  return (
    <div className="border border-gray-500/50 rounded-lg p-3 bg-gray-50/10">
      <div className="flex items-center gap-2 mb-2">
        <Badge variant="outline">{name}</Badge>
        <span className="text-xs text-muted-foreground">{id}</span>
      </div>
      <pre className="text-xs overflow-x-auto">
        {JSON.stringify(input, null, 2)}
      </pre>
    </div>
  )
}
