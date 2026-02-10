import { useState, useMemo } from 'react'
import { Plus, X, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { PERMISSION_TOOLS, PATTERN_EXAMPLES } from '@/types/permissions'

interface PermissionRulesEditorProps {
  allowRules: string[]
  denyRules: string[]
  askRules: string[]
  onAllowChange: (rules: string[]) => void
  onDenyChange: (rules: string[]) => void
  onAskChange: (rules: string[]) => void
}

type RuleCategory = 'allow' | 'deny' | 'ask'

const CATEGORY_CONFIG: Record<RuleCategory, { label: string; color: string; badgeClass: string; description: string }> = {
  allow: {
    label: 'Allow',
    color: 'border-green-500/30 bg-green-500/5',
    badgeClass: 'bg-green-600 hover:bg-green-700 text-white',
    description: 'Auto-approved operations',
  },
  ask: {
    label: 'Ask',
    color: 'border-amber-500/30 bg-amber-500/5',
    badgeClass: 'bg-amber-600 hover:bg-amber-700 text-white',
    description: 'Prompt for confirmation',
  },
  deny: {
    label: 'Deny',
    color: 'border-red-500/30 bg-red-500/5',
    badgeClass: 'bg-red-600 hover:bg-red-700 text-white',
    description: 'Blocked operations',
  },
}

// Quick-add patterns per tool
const QUICK_PATTERNS: Record<string, { label: string; pattern: string }[]> = {
  Bash: [
    { label: 'npm run *', pattern: 'npm run *' },
    { label: 'git *', pattern: 'git *' },
    { label: 'git diff *', pattern: 'git diff *' },
    { label: 'docker *', pattern: 'docker *' },
  ],
  WebFetch: [
    { label: 'github.com', pattern: 'domain:github.com' },
    { label: '*.anthropic.com', pattern: 'domain:*.anthropic.com' },
  ],
  MCP: [
    { label: 'server:*', pattern: 'server:*' },
  ],
}

export function PermissionRulesEditor({
  allowRules,
  denyRules,
  askRules,
  onAllowChange,
  onDenyChange,
  onAskChange,
}: PermissionRulesEditorProps) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogCategory, setDialogCategory] = useState<RuleCategory>('allow')
  const [tool, setTool] = useState('')
  const [argument, setArgument] = useState('')
  const [expandedSections, setExpandedSections] = useState<Record<RuleCategory, boolean>>({
    allow: true,
    ask: true,
    deny: true,
  })

  const rulesMap: Record<RuleCategory, { rules: string[]; onChange: (rules: string[]) => void }> = {
    allow: { rules: allowRules, onChange: onAllowChange },
    deny: { rules: denyRules, onChange: onDenyChange },
    ask: { rules: askRules, onChange: onAskChange },
  }

  const selectedTool = useMemo(
    () => PERMISSION_TOOLS.find((t) => t.name === tool),
    [tool]
  )

  const buildPattern = () => {
    if (!tool) return ''
    if (!argument) return tool
    return `${tool}(${argument})`
  }

  const relevantExamples = useMemo(() => {
    if (!tool) return PATTERN_EXAMPLES
    return PATTERN_EXAMPLES.filter((ex) => ex.pattern.startsWith(tool))
  }, [tool])

  const pattern = buildPattern()

  const openAddDialog = (category: RuleCategory) => {
    setDialogCategory(category)
    setTool('')
    setArgument('')
    setDialogOpen(true)
  }

  const addRule = () => {
    if (!pattern) return
    const { rules, onChange } = rulesMap[dialogCategory]
    if (!rules.includes(pattern)) {
      onChange([...rules, pattern])
    }
    setDialogOpen(false)
  }

  const removeRule = (category: RuleCategory, index: number) => {
    const { rules, onChange } = rulesMap[category]
    onChange(rules.filter((_, i) => i !== index))
  }

  const toggleSection = (category: RuleCategory) => {
    setExpandedSections((prev) => ({ ...prev, [category]: !prev[category] }))
  }

  const totalRules = allowRules.length + denyRules.length + askRules.length

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label>Permission Rules</Label>
        {totalRules > 0 && (
          <span className="text-xs text-muted-foreground">{totalRules} rule{totalRules !== 1 ? 's' : ''}</span>
        )}
      </div>

      {(['allow', 'ask', 'deny'] as const).map((category) => {
        const config = CATEGORY_CONFIG[category]
        const { rules } = rulesMap[category]
        const isExpanded = expandedSections[category]

        return (
          <Collapsible key={category} open={isExpanded} onOpenChange={() => toggleSection(category)}>
            <div className={`rounded-lg border ${config.color} p-3`}>
              <div className="flex items-center justify-between">
                <CollapsibleTrigger asChild>
                  <button type="button" className="flex items-center gap-2 text-sm font-medium hover:opacity-80">
                    <ChevronDown className={`h-4 w-4 transition-transform ${isExpanded ? '' : '-rotate-90'}`} />
                    <Badge className={config.badgeClass}>{config.label}</Badge>
                    <span className="text-muted-foreground">{config.description}</span>
                    {rules.length > 0 && (
                      <span className="text-xs text-muted-foreground">({rules.length})</span>
                    )}
                  </button>
                </CollapsibleTrigger>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7"
                  onClick={() => openAddDialog(category)}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add
                </Button>
              </div>

              <CollapsibleContent>
                {rules.length > 0 ? (
                  <div className="flex flex-wrap gap-2 mt-3">
                    {rules.map((rule, index) => (
                      <div
                        key={index}
                        className="flex items-center gap-1 bg-background border rounded-md px-2 py-1 text-sm font-mono"
                      >
                        <span>{rule}</span>
                        <button
                          type="button"
                          onClick={() => removeRule(category, index)}
                          className="text-muted-foreground hover:text-foreground ml-1"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground mt-2">No rules configured</p>
                )}
              </CollapsibleContent>
            </div>
          </Collapsible>
        )
      })}

      {/* Add Rule Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>
              Add{' '}
              <Badge className={CATEGORY_CONFIG[dialogCategory].badgeClass}>
                {CATEGORY_CONFIG[dialogCategory].label}
              </Badge>{' '}
              Rule
            </DialogTitle>
            <DialogDescription>
              Add a permission rule pattern
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {/* Tool Selection */}
            <div className="space-y-2">
              <Label>Tool</Label>
              <Select value={tool} onValueChange={(v) => { setTool(v); setArgument('') }}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a tool..." />
                </SelectTrigger>
                <SelectContent>
                  {PERMISSION_TOOLS.map((t) => (
                    <SelectItem key={t.name} value={t.name}>
                      <span className="flex items-center gap-2">
                        <code className="text-sm bg-muted px-1 rounded">{t.name}</code>
                        <span className="text-muted-foreground text-sm">{t.description}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Pattern Input */}
            <div className="space-y-2">
              <Label>Pattern (optional)</Label>
              <Input
                value={argument}
                onChange={(e) => setArgument(e.target.value)}
                placeholder={selectedTool?.hint || 'e.g., npm run *, *.py, /etc/*'}
                onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addRule())}
              />
              {selectedTool?.hint && (
                <p className="text-xs text-muted-foreground">
                  Hint: {selectedTool.name}({selectedTool.hint})
                </p>
              )}
            </div>

            {/* Quick-add buttons */}
            {tool && QUICK_PATTERNS[tool] && (
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Quick Patterns</Label>
                <div className="flex flex-wrap gap-2">
                  {QUICK_PATTERNS[tool].map((qp) => (
                    <Button
                      key={qp.pattern}
                      variant="outline"
                      size="sm"
                      onClick={() => setArgument(qp.pattern)}
                      className="h-7 text-xs"
                    >
                      {qp.label}
                    </Button>
                  ))}
                </div>
              </div>
            )}

            {/* Pattern Preview */}
            {pattern && (
              <div className="space-y-2">
                <Label>Preview</Label>
                <div className="p-3 bg-muted rounded-md font-mono text-sm">
                  <Badge className={`${CATEGORY_CONFIG[dialogCategory].badgeClass} mr-2`}>
                    {dialogCategory}
                  </Badge>
                  {pattern}
                </div>
              </div>
            )}

            {/* Examples */}
            {tool && relevantExamples.length > 0 && (
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Examples</Label>
                <div className="space-y-1 text-sm max-h-32 overflow-y-auto">
                  {relevantExamples.map((ex) => (
                    <div
                      key={ex.pattern}
                      className="flex items-center gap-2 p-1.5 hover:bg-muted rounded cursor-pointer"
                      onClick={() => {
                        const match = ex.pattern.match(/^(\w+)(?:\((.+)\))?$/)
                        if (match) {
                          setTool(match[1])
                          setArgument(match[2] || '')
                        }
                      }}
                    >
                      <code className="text-xs bg-muted px-1 rounded">{ex.pattern}</code>
                      <span className="text-muted-foreground text-xs">{ex.description}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={addRule} disabled={!pattern}>
              Add Rule
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
