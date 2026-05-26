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
  const existingFiles = files.filter((file) => file.exists)
  const groups = [
    { scope: 'user', title: 'User Config Files' },
    { scope: 'project', title: 'Project Config Files' },
    { scope: 'profile', title: 'Profile Config Files' },
    { scope: 'rules', title: 'Rules Files' },
    { scope: 'managed', title: 'Managed Config Files' },
  ] as const

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
      {groups.map(({ scope, title }) => {
        const scopedFiles = existingFiles.filter((file) => file.scope === scope)
        if (scopedFiles.length === 0) return null
        return (
          <div key={scope}>
            <h3 className="text-sm font-semibold mb-2">{title}</h3>
            <div className="space-y-1">
              {scopedFiles.map((file) => (
                <FileItem key={file.path} file={file} />
              ))}
            </div>
          </div>
        )
      })}

      {existingFiles.length === 0 && (
        <Card className="p-4">
          <p className="text-sm text-muted-foreground text-center">
            No configuration files found
          </p>
        </Card>
      )}
    </div>
  )
}
