import { Conversation } from './Conversation'
import type { SessionConversation } from '@/types/sessions'

interface Props {
  conversations: SessionConversation[]
}

export function ConversationList({ conversations }: Props) {
  return (
    <div className="space-y-8">
      {conversations.map((convo, idx) => (
        <Conversation key={idx} conversation={convo} />
      ))}
    </div>
  )
}
