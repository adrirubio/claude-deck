import { Button } from '@/components/ui/button'

interface RefreshButtonProps {
  onClick: () => void
  loading?: boolean
}

export function RefreshButton({ onClick, loading = false }: RefreshButtonProps) {
  return (
    <Button
      onClick={onClick}
      disabled={loading}
      variant="outline"
      size="sm"
    >
      {loading ? 'Refreshing...' : 'Refresh'}
    </Button>
  )
}
