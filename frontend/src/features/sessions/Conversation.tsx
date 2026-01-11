import { Message } from './Message'
import type { SessionConversation } from '@/types/sessions'

interface Props {
  conversation: SessionConversation
}

export function Conversation({ conversation }: Props) {
  return (
    <div className="space-y-4">
      {conversation.messages.map((msg, idx) => (
        <Message key={idx} message={msg} />
      ))}
      {conversation.is_continuation && (
        <div className="text-xs text-muted-foreground italic text-center">
          (continuation)
        </div>
      )}
    </div>
  )
}
