import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { SecretField } from '@/components/shared/SecretField'
import { MODAL_SIZES } from '@/lib/constants'

const INSTALLATION_GUIDE_URL = 'https://github.com/adrirubio/claude-deck/blob/master/docs/guide/installation.md'

export function OperatorTokenDialog({
  open,
  value,
  error,
  reason,
  onValueChange,
  onSubmit,
  onCancel,
}: {
  open: boolean
  value: string
  error: string | null
  reason?: string
  onValueChange: (value: string) => void
  onSubmit: () => void
  onCancel: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onCancel() }}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <DialogTitle>Director key</DialogTitle>
          <DialogDescription>
            Paste the Director key for this Deck installation. It is the value of <code>OPERATOR_TOKEN</code> on the server. Deck keeps it in this browser tab only.
          </DialogDescription>
        </DialogHeader>
        {reason && <p className="text-sm">Deck needs the key {reason}.</p>}
        <details className="text-sm text-muted-foreground">
          <summary className="cursor-pointer text-foreground">First time? Set up the key on the server</summary>
          <p className="mt-2">On the machine running Deck, run <code>openssl rand -hex 32</code>. Add the result as <code>operator_token=&lt;value&gt;</code> in <code>backend/.env</code>, run <code>chmod 600 backend/.env</code>, then restart the backend. Do not export the key into the agent environment. See the <a className="underline" href={INSTALLATION_GUIDE_URL} target="_blank" rel="noreferrer">installation guide</a>.</p>
        </details>
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        <form onSubmit={(event) => { event.preventDefault(); onSubmit() }} className="space-y-4">
          <SecretField
            id="autonomy-operator-token"
            label="Director key"
            value={value}
            onChange={onValueChange}
            required
            autoComplete="off"
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
            <Button type="submit" disabled={!value.trim()}>Use key</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
