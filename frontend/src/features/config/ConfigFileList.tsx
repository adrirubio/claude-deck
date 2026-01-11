import type { ConfigFile } from '@/types/config'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface ConfigFileListProps {
  files: ConfigFile[]
  selectedFile: string | null
  onSelectFile: (path: string) => void
}

export function ConfigFileList({ files, selectedFile, onSelectFile }: ConfigFileListProps) {
  const userFiles = files.filter(f => f.scope === 'user' && f.exists)
  const projectFiles = files.filter(f => f.scope === 'project' && f.exists)

  const FileItem = ({ file }: { file: ConfigFile }) => (
    <button
      onClick={() => onSelectFile(file.path)}
      className={cn(
        'w-full text-left p-2 rounded-md text-sm transition-colors',
        selectedFile === file.path
          ? 'bg-primary text-primary-foreground'
          : 'hover:bg-accent hover:text-accent-foreground'
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate">{file.path.split('/').pop()}</span>
        <Badge variant={file.scope === 'user' ? 'default' : 'secondary'} className="text-xs shrink-0">
          {file.scope}
        </Badge>
      </div>
      <div className="text-xs text-muted-foreground truncate mt-1">
        {file.path}
      </div>
    </button>
  )

  return (
    <div className="space-y-4">
      {userFiles.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-2">User Config Files</h3>
          <div className="space-y-1">
            {userFiles.map(file => (
              <FileItem key={file.path} file={file} />
            ))}
          </div>
        </div>
      )}

      {projectFiles.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-2">Project Config Files</h3>
          <div className="space-y-1">
            {projectFiles.map(file => (
              <FileItem key={file.path} file={file} />
            ))}
          </div>
        </div>
      )}

      {files.length === 0 && (
        <Card className="p-4">
          <p className="text-sm text-muted-foreground text-center">
            No configuration files found
          </p>
        </Card>
      )}
    </div>
  )
}
