import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { ListEditor, SwitchSetting } from '../field-components'
import type { SettingsCardProps } from '../types'

export function WorktreeCard({ getSetting, updateSetting }: SettingsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Worktrees</CardTitle>
        <CardDescription>Behavior when creating git worktrees from Claude Code</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <SwitchSetting
          label="Symlink Directories"
          description="Symlink ignored/untracked directories (e.g., node_modules, venv) into new worktrees to save time and disk."
          checked={getSetting<boolean>('worktree.symlinkDirectories', false)}
          onCheckedChange={(v) => updateSetting('worktree.symlinkDirectories', v)}
        />

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
