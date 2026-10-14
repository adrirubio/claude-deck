import { useEffect } from 'react'

import type { InstanceIdentity } from '@/types/status'

const BASE_TITLE = 'Claude Deck'

// The tab title carries the instance name only when the operator chose one.
export function useInstanceDocumentTitle(instance?: InstanceIdentity | null) {
  const name = instance?.name_configured ? instance.name : null
  useEffect(() => {
    document.title = name ? `${name} · ${BASE_TITLE}` : BASE_TITLE
  }, [name])
}
