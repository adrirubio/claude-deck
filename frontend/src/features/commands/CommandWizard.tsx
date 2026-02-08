import { useState } from 'react';
import { ChevronLeft, ChevronRight, Check } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Card, CardContent } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { COMMAND_TEMPLATES, type CommandTemplate } from '../../types/commands';
import { apiClient } from '../../lib/api';
import { toast } from 'sonner';

interface CommandWizardProps {
  onComplete: () => void;
  onCancel: () => void;
}

export function CommandWizard({ onComplete, onCancel }: CommandWizardProps) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState('');
  const [namespace, setNamespace] = useState('');
  const [scope, setScope] = useState<'user' | 'project'>('user');
  const [selectedTemplate, setSelectedTemplate] = useState<CommandTemplate | null>(null);
  const [description, setDescription] = useState('');
  const [allowedTools, setAllowedTools] = useState<string[]>([]);
  const [content, setContent] = useState('');
  const [creating, setCreating] = useState(false);

  const steps = ['Name & Namespace', 'Scope', 'Frontmatter', 'Content'];

  const isStep1Valid = name.trim().length > 0;
  const isStep2Valid = true; // Scope always has a value
  const isStep3Valid = true; // Frontmatter is optional
  const isStep4Valid = content.trim().length > 0;

  const handleNext = () => {
    if (step < 4) setStep(step + 1);
  };

  const handleBack = () => {
    if (step > 1) setStep(step - 1);
  };

  const handleSelectTemplate = (template: CommandTemplate) => {
    setSelectedTemplate(template);
    setContent(template.defaultContent);
    if (template.defaultAllowedTools) {
      setAllowedTools(template.defaultAllowedTools);
    }
  };

  const handleCreate = async () => {
    setCreating(true);
    try {
      const fullName = namespace ? `${namespace}:${name}` : name;
      await apiClient("commands", {
        method: "POST",
        body: JSON.stringify({
          name: fullName,
          scope,
          description: description || undefined,
          allowed_tools: allowedTools.length > 0 ? allowedTools : undefined,
          content,
        }),
      });
      toast.success('Command created successfully');
      onComplete();
    } catch {
      toast.error('Failed to create command');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold">Create New Command</h2>
        <p className="text-sm text-muted-foreground">
          Step {step} of {steps.length}: {steps[step - 1]}
        </p>
      </div>

      {/* Progress Bar */}
      <div className="flex gap-2">
        {steps.map((_, index) => (
          <div
            key={index}
            className={`h-2 flex-1 rounded-full ${
              index < step ? 'bg-primary' : 'bg-muted'
            }`}
          />
        ))}
      </div>

      {/* Step Content */}
      <div className="min-h-[300px]">
        {/* Step 1: Name and Namespace */}
        {step === 1 && (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Command Name *</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-command"
                autoFocus
              />
              <p className="text-sm text-muted-foreground">
                The command name (without leading slash). Use lowercase and hyphens.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="namespace">Namespace (Optional)</Label>
              <Input
                id="namespace"
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
                placeholder="tools"
              />
              <p className="text-sm text-muted-foreground">
                Group commands by namespace (e.g., "tools" for /tools:analyze).
                Use colons to create sub-namespaces (e.g., "git:hooks").
              </p>
            </div>

            {(name || namespace) && (
              <Card className="bg-muted">
                <CardContent className="pt-4">
                  <p className="text-sm font-medium">Command will be accessible as:</p>
                  <code className="text-lg font-mono">
                    /{namespace ? `${namespace}:${name}` : name}
                  </code>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* Step 2: Scope */}
        {step === 2 && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Choose where to save this command:
            </p>
            <div className="grid gap-4">
              <Card
                className={`cursor-pointer transition-colors ${
                  scope === 'user'
                    ? 'border-primary bg-primary/5'
                    : 'hover:border-primary/50'
                }`}
                onClick={() => setScope('user')}
              >
                <CardContent className="pt-6">
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="font-semibold flex items-center gap-2">
                        User Scope
                        <Badge variant="default">~/.claude/commands/</Badge>
                      </h3>
                      <p className="text-sm text-muted-foreground mt-2">
                        Available in all your Claude Code projects. Commands saved here
                        are personal and not shared with the project repository.
                      </p>
                    </div>
                    {scope === 'user' && <Check className="h-5 w-5 text-primary" />}
                  </div>
                </CardContent>
              </Card>

              <Card
                className={`cursor-pointer transition-colors ${
                  scope === 'project'
                    ? 'border-primary bg-primary/5'
                    : 'hover:border-primary/50'
                }`}
                onClick={() => setScope('project')}
              >
                <CardContent className="pt-6">
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="font-semibold flex items-center gap-2">
                        Project Scope
                        <Badge variant="secondary">.claude/commands/</Badge>
                      </h3>
                      <p className="text-sm text-muted-foreground mt-2">
                        Specific to this project. Commands saved here are checked into
                        version control and shared with your team.
                      </p>
                    </div>
                    {scope === 'project' && <Check className="h-5 w-5 text-primary" />}
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        )}

        {/* Step 3: Frontmatter Options */}
        {step === 3 && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Configure optional metadata for your command:
            </p>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="description">Description (Optional)</Label>
                <Input
                  id="description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Brief description of what this command does"
                />
              </div>

              <div className="space-y-2">
                <Label>Allowed Tools (Optional)</Label>
                <p className="text-sm text-muted-foreground">
                  Select which tools this command can use. Leave empty to allow all tools.
                </p>
                <div className="flex flex-wrap gap-2">
                  {['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep', 'WebFetch', 'Task'].map((tool) => (
                    <Badge
                      key={tool}
                      variant={allowedTools.includes(tool) ? 'default' : 'outline'}
                      className="cursor-pointer"
                      onClick={() => {
                        if (allowedTools.includes(tool)) {
                          setAllowedTools(allowedTools.filter((t) => t !== tool));
                        } else {
                          setAllowedTools([...allowedTools, tool]);
                        }
                      }}
                    >
                      {tool}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Step 4: Initial Content */}
        {step === 4 && (
          <div className="space-y-4">
            <div>
              <Label>Choose a Template or Start Blank</Label>
              <p className="text-sm text-muted-foreground">
                Select a template to get started quickly:
              </p>
            </div>
            <div className="grid gap-2">
              {COMMAND_TEMPLATES.map((template) => (
                <Card
                  key={template.name}
                  className={`cursor-pointer transition-colors ${
                    selectedTemplate?.name === template.name
                      ? 'border-primary bg-primary/5'
                      : 'hover:border-primary/50'
                  }`}
                  onClick={() => handleSelectTemplate(template)}
                >
                  <CardContent className="pt-4 pb-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <h4 className="font-semibold capitalize">{template.name}</h4>
                        <p className="text-sm text-muted-foreground">
                          {template.description}
                        </p>
                      </div>
                      {selectedTemplate?.name === template.name && (
                        <Check className="h-5 w-5 text-primary" />
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>

            <div className="pt-4">
              <Label>Command Content *</Label>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                className="w-full h-40 p-4 mt-2 font-mono text-sm border rounded-md resize-y focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder="Write your command instructions here..."
              />
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t">
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <div className="flex gap-2">
          {step > 1 && (
            <Button variant="outline" onClick={handleBack}>
              <ChevronLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
          )}
          {step < 4 ? (
            <Button
              onClick={handleNext}
              disabled={
                (step === 1 && !isStep1Valid) ||
                (step === 2 && !isStep2Valid) ||
                (step === 3 && !isStep3Valid)
              }
            >
              Next
              <ChevronRight className="h-4 w-4 ml-2" />
            </Button>
          ) : (
            <Button onClick={handleCreate} disabled={!isStep4Valid || creating}>
              {creating ? 'Creating...' : 'Create Command'}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
