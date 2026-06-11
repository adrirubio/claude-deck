import { useEffect } from 'react'

import type { InstanceIdentity } from '@/types/status'

const BASE_TITLE = 'Claude Deck'

export function useInstanceDocumentTitle(instance?: InstanceIdentity | null) {
  useEffect(() => {
    document.title = instance?.name ? `${instance.name} · ${BASE_TITLE}` : BASE_TITLE
  }, [instance?.name])
}
