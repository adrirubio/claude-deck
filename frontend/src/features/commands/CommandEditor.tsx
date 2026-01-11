import { useState } from 'react';
import { Save, X, Trash2 } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { MarkdownEditor } from '../../components/shared/MarkdownEditor';
import type { SlashCommand } from '../../types/commands';

interface CommandEditorProps {
  command: SlashCommand;
  onSave: (command: SlashCommand) => void;
  onDelete: (command: SlashCommand) => void;
  onCancel: () => void;
}

export function CommandEditor({ command, onSave, onDelete, onCancel }: CommandEditorProps) {
  const [description, setDescription] = useState(command.description || '');
  const [allowedTools, setAllowedTools] = useState<string[]>(command.allowed_tools || []);
  const [content, setContent] = useState(command.content);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({
        ...command,
        description,
        allowed_tools: allowedTools.length > 0 ? allowedTools : undefined,
        content,
      });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = () => {
    onDelete(command);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-2xl font-bold">{command.name}</h2>
            <p className="text-sm text-muted-foreground">{command.path}</p>
          </div>
          <Badge variant={command.scope === 'user' ? 'default' : 'secondary'}>
            {command.scope}
          </Badge>
        </div>
      </div>

      {/* Markdown Editor */}
      <MarkdownEditor
        description={description}
        allowedTools={allowedTools}
        content={content}
        onDescriptionChange={setDescription}
        onAllowedToolsChange={setAllowedTools}
        onContentChange={setContent}
      />

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t">
        <Button variant="destructive" onClick={handleDelete}>
          <Trash2 className="h-4 w-4 mr-2" />
          Delete Command
        </Button>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onCancel}>
            <X className="h-4 w-4 mr-2" />
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            <Save className="h-4 w-4 mr-2" />
            {saving ? 'Saving...' : 'Save Changes'}
          </Button>
        </div>
      </div>
    </div>
  );
}
