import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { formatDistanceToNow } from 'date-fns'
import { ContentBlockRenderer } from './ContentBlockRenderer'
import type { SessionMessage } from '@/types/sessions'

interface Props {
  message: SessionMessage
}

export function Message({ message }: Props) {
  const isUser = message.type === 'user'
  const timeAgo = formatDistanceToNow(new Date(message.timestamp), { addSuffix: true })

  // Calculate total tokens if usage available
  const totalTokens = message.usage
    ? (message.usage.input_tokens || 0) +
      (message.usage.output_tokens || 0) +
      (message.usage.cache_creation_input_tokens || 0) +
      (message.usage.cache_read_input_tokens || 0)
    : null

  return (
    <Card
      className={`p-4 ${
        isUser
          ? 'border-blue-500/50 bg-blue-50/10'
          : 'border-gray-500/50 bg-gray-50/10'
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Badge variant={isUser ? 'default' : 'secondary'}>
            {isUser ? 'User' : 'Assistant'}
          </Badge>
          {message.model && (
            <Badge variant="outline" className="text-xs">
              {message.model}
            </Badge>
          )}
          <span className="text-xs text-muted-foreground">{timeAgo}</span>
        </div>

        {totalTokens && (
          <Badge variant="outline" className="text-xs">
            {totalTokens.toLocaleString()} tokens
          </Badge>
        )}
      </div>

      {/* Content Blocks */}
      <div className="space-y-3">
        {message.content.map((block, idx) => (
          <ContentBlockRenderer key={idx} block={block} />
        ))}
      </div>

      {/* Token Usage Detail (if available) */}
      {message.usage && (
        <div className="mt-3 pt-3 border-t text-xs text-muted-foreground flex gap-4">
          {message.usage.input_tokens && (
            <span>Input: {message.usage.input_tokens}</span>
          )}
          {message.usage.output_tokens && (
            <span>Output: {message.usage.output_tokens}</span>
          )}
          {message.usage.cache_creation_input_tokens && (
            <span>Cache Create: {message.usage.cache_creation_input_tokens}</span>
          )}
          {message.usage.cache_read_input_tokens && (
            <span>Cache Read: {message.usage.cache_read_input_tokens}</span>
          )}
        </div>
      )}
    </Card>
  )
}
