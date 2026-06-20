import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { ListEditor, SelectSetting } from '../field-components'
import { WORKTREE_BASE_REF_OPTIONS, WORKTREE_BG_ISOLATION_OPTIONS } from '../constants'
import type { SettingsCardProps } from '../types'

export function WorktreeCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Worktrees</CardTitle>
        <CardDescription>Behavior when creating git worktrees from Claude Code</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SelectSetting
          id="worktreeBaseRef"
          label="Base Ref"
          description="Which ref new worktrees branch from. Fresh branches from origin/<default-branch>; HEAD branches from your current local HEAD."
          value={getSetting<string>('worktree.baseRef', '')}
          onValueChange={(v) => updateSetting('worktree.baseRef', v)}
          placeholder="Fresh (default)"
          options={WORKTREE_BASE_REF_OPTIONS}
        />

        <SelectSetting
          id="worktreeBgIsolation"
          label="Background Isolation"
          description="Isolation mode for background sessions. Worktree blocks Edit/Write in the main checkout until EnterWorktree; None edits the working copy directly. Requires Claude Code v2.1.143+."
          value={getSetting<string>('worktree.bgIsolation', '')}
          onValueChange={(v) => updateSetting('worktree.bgIsolation', v)}
          placeholder="Worktree (default)"
          options={WORKTREE_BG_ISOLATION_OPTIONS}
        />

        <div className="grid gap-2">
          <Label>Symlink Directories</Label>
          <p className="text-sm text-muted-foreground">
            Directories to symlink into new worktrees to avoid duplicating large ignored folders.
          </p>
          <ListEditor
            value={getSetting<string[]>('worktree.symlinkDirectories', [])}
            onChange={(v) => updateSetting('worktree.symlinkDirectories', v)}
            placeholder="e.g., node_modules"
          />
        </div>

        <div className="grid gap-2">
          <Label>Sparse Paths</Label>
          <p className="text-sm text-muted-foreground">
            Gitignore-style patterns for paths to check out via sparse-checkout in new worktrees.
          </p>
          <ListEditor
            value={getSetting<string[]>('worktree.sparsePaths', [])}
            onChange={(v) => updateSetting('worktree.sparsePaths', v)}
            placeholder="e.g., src/**, docs/**"
          />
        </div>
      </CardContent>
    </Card>
  )
}
