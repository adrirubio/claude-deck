import { useState } from 'react';
import { ChevronDown, ChevronUp, HelpCircle } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Badge } from '../ui/badge';
import { AVAILABLE_TOOLS } from '../../types/commands';

interface MarkdownEditorProps {
  description?: string;
  allowedTools?: string[];
  content: string;
  onDescriptionChange: (value: string) => void;
  onAllowedToolsChange: (value: string[]) => void;
  onContentChange: (value: string) => void;
}

export function MarkdownEditor({
  description = '',
  allowedTools = [],
  content,
  onDescriptionChange,
  onAllowedToolsChange,
  onContentChange,
}: MarkdownEditorProps) {
  const [frontmatterOpen, setFrontmatterOpen] = useState(true);
  const [showToolHelp, setShowToolHelp] = useState(false);
  const [showPlaceholderHelp, setShowPlaceholderHelp] = useState(false);

  const handleToolToggle = (tool: string) => {
    if (allowedTools.includes(tool)) {
      onAllowedToolsChange(allowedTools.filter((t) => t !== tool));
    } else {
      onAllowedToolsChange([...allowedTools, tool]);
    }
  };

  return (
    <div className="space-y-4">
      {/* Frontmatter Section */}
      <Card>
        <CardHeader className="cursor-pointer" onClick={() => setFrontmatterOpen(!frontmatterOpen)}>
          <CardTitle className="flex items-center justify-between text-lg">
            <span>Frontmatter (YAML Metadata)</span>
            {frontmatterOpen ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
          </CardTitle>
        </CardHeader>
        {frontmatterOpen && (
          <CardContent className="space-y-4">
            {/* Description */}
            <div className="space-y-2">
              <Label htmlFor="description">Description (Optional)</Label>
              <Input
                id="description"
                value={description}
                onChange={(e) => onDescriptionChange(e.target.value)}
                placeholder="Brief description of what this command does"
              />
            </div>

            {/* Allowed Tools */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Label>Allowed Tools (Optional)</Label>
                <HelpCircle
                  className="h-4 w-4 cursor-pointer text-muted-foreground hover:text-foreground"
                  onClick={() => setShowToolHelp(!showToolHelp)}
                />
              </div>
              {showToolHelp && (
                <Card className="bg-muted">
                  <CardContent className="pt-4 text-sm">
                    <p>Select which tools this command can use. If none selected, all tools are allowed.</p>
                  </CardContent>
                </Card>
              )}
              <div className="flex flex-wrap gap-2">
                {AVAILABLE_TOOLS.map((tool) => (
                  <Badge
                    key={tool}
                    variant={allowedTools.includes(tool) ? 'default' : 'outline'}
                    className="cursor-pointer"
                    onClick={() => handleToolToggle(tool)}
                  >
                    {tool}
                  </Badge>
                ))}
              </div>
            </div>
          </CardContent>
        )}
      </Card>

      {/* Markdown Content Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">Command Content (Markdown)</CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowPlaceholderHelp(!showPlaceholderHelp)}
            >
              <HelpCircle className="h-4 w-4 mr-2" />
              Placeholders
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {showPlaceholderHelp && (
            <Card className="bg-muted">
              <CardContent className="pt-4 text-sm space-y-2">
                <p className="font-semibold">Available Argument Placeholders:</p>
                <ul className="list-disc list-inside space-y-1">
                  <li><code className="bg-background px-1">$ARGUMENTS</code> - All arguments passed to the command</li>
                  <li><code className="bg-background px-1">$1, $2, $3...</code> - Individual positional arguments</li>
                  <li><code className="bg-background px-1">$@</code> - All arguments as separate strings</li>
                </ul>
                <p className="mt-2">Example: <code className="bg-background px-1">/review src/app.ts</code> → $ARGUMENTS = "src/app.ts"</p>
              </CardContent>
            </Card>
          )}
          <textarea
            value={content}
            onChange={(e) => onContentChange(e.target.value)}
            className="w-full h-80 p-4 font-mono text-sm border rounded-md resize-y focus:outline-none focus:ring-2 focus:ring-primary"
            placeholder="Write your command instructions here...

Usage: /command-name <args>

You can use markdown formatting:
- **Bold text**
- *Italic text*
- `Code blocks`
- Lists and more"
          />
        </CardContent>
      </Card>
    </div>
  );
}
