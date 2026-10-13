import { Cog, HelpCircle, Plug, User } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { MailMemberResponse, MailMessageResponse } from '@/types/agentMail'
import { senderKind, senderName, type SenderKind } from './utils'

// A non-agent sender gets an icon with an accessible name. An agent keeps its
// name alone. The icon only labels a message; it grants no authority.
const ICONS: Partial<Record<SenderKind, { Icon: typeof User; title: string; className: string }>> = {
  deck: { Icon: Cog, title: 'Sent by Deck, not by an agent', className: 'text-muted-foreground' },
  director: { Icon: User, title: 'Sent by the Director', className: 'text-blue-700 dark:text-blue-300' },
  legacy: { Icon: HelpCircle, title: 'Recorded before sender types existed', className: 'text-muted-foreground' },
  external: { Icon: Plug, title: 'Sent by an external tool', className: 'text-muted-foreground' },
  unknown: { Icon: HelpCircle, title: 'The sender is not known', className: 'text-muted-foreground' },
}

export function SenderLabel({ message, members }: {
  message: MailMessageResponse
  members: MailMemberResponse[]
}) {
  const icon = ICONS[senderKind(message)]
  return (
    <span className="inline-flex items-center gap-1" data-sender-kind={senderKind(message)}>
      {icon && <icon.Icon role="img" aria-label={icon.title} className={cn('h-3.5 w-3.5 shrink-0', icon.className)} />}
      <span>{senderName(message, members)}</span>
    </span>
  )
}
