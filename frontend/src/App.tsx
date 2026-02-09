import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { ProjectProvider } from './contexts/ProjectContext'
import { MainLayout } from './components/layout/MainLayout'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { ConfigViewerPage } from './features/config/ConfigViewerPage'
import { ProjectsPage } from './features/projects/ProjectsPage'
import { MCPServersPage } from './features/mcp/MCPServersPage'
import { CommandsPage } from './features/commands/CommandsPage'
import { PluginsPage } from './features/plugins/PluginsPage'
import { HooksPage } from './features/hooks/HooksPage'
import { PermissionsPage } from './features/permissions/PermissionsPage'
import { AgentsPage } from './features/agents/AgentsPage'
import { SkillsPage } from './features/skills/SkillsPage'
import { BackupPage } from './features/backup/BackupPage'
import { OutputStylesPage } from './features/output-styles/OutputStylesPage'
import { StatusLinePage } from './features/statusline/StatusLinePage'
import { SessionsPage } from './features/sessions/SessionsPage'
import { SessionViewPage } from './features/sessions/SessionViewPage'
import { UsagePage } from './features/usage/UsagePage'
import { MemoryPage } from './features/memory/MemoryPage'
import { ContextPage } from './features/context/ContextPage'

function App() {
  return (
    <ProjectProvider>
      <BrowserRouter>
        <Toaster richColors position="top-right" />
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="config" element={<ConfigViewerPage />} />
            <Route path="mcp" element={<MCPServersPage />} />
            <Route path="commands" element={<CommandsPage />} />
            <Route path="plugins" element={<PluginsPage />} />
            <Route path="hooks" element={<HooksPage />} />
            <Route path="permissions" element={<PermissionsPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="skills" element={<SkillsPage />} />
            <Route path="memory" element={<MemoryPage />} />
            <Route path="projects" element={<ProjectsPage />} />
            <Route path="backup" element={<BackupPage />} />
            <Route path="output-styles" element={<OutputStylesPage />} />
            <Route path="statusline" element={<StatusLinePage />} />
            <Route path="sessions/:projectFolder/:sessionId" element={<SessionViewPage />} />
            <Route path="sessions" element={<SessionsPage />} />
            <Route path="context" element={<ContextPage />} />
            <Route path="usage" element={<UsagePage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ProjectProvider>
  )
}

export default App
