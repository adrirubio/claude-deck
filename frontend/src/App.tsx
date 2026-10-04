import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Toaster } from 'sonner'
import { ProjectProvider } from './contexts/ProjectContext'
import { ProviderProvider } from './contexts/ProviderContext'
import { MainLayout } from './components/layout/MainLayout'
import { ProjectsPage } from './features/projects/ProjectsPage'
import { NativeRoute } from './features/native-settings/NativeRoute'
import { HarnessesPage } from './features/harnesses/HarnessesPage'
import { OverviewPage, WorkPage, WorkDetailPage, RepositoriesPage, RepositoryPage } from './features/factory/FactoryPages'
import { BridgeEntry, MailEntry } from './features/factory/ContextPages'
import { AgentTeamsPage } from './features/agent-teams/AgentTeamsPage'

function TeamsAlias() { const { search, hash } = useLocation(); return <Navigate replace to={`/teams${search}${hash}`} /> }

function App() {
  return (
    <ProjectProvider>
      <ProviderProvider>

          <BrowserRouter>
            <Toaster richColors position="top-right" />
            <Routes>
              <Route path="/" element={<MainLayout />}>
                <Route index element={<OverviewPage />} />
                <Route path="work" element={<WorkPage />} />
                <Route path="work/:workItemId" element={<WorkDetailPage />} />
                <Route path="repositories" element={<RepositoriesPage />} />
                <Route path="repositories/:scopeId" element={<RepositoryPage />} />
                <Route path="harnesses" element={<HarnessesPage />} />
                <Route path="harnesses/:providerId" element={<HarnessesPage />} />
                <Route path="harnesses/:providerId/:surface" element={<NativeRoute />} />
                <Route path="harnesses/:providerId/plans/:filename" element={<NativeRoute surface="plans" detail="plan" />} />
                <Route path="harnesses/:providerId/sessions/:projectFolder/:sessionId" element={<NativeRoute surface="sessions" detail="session" />} />
                <Route path="teams" element={<AgentTeamsPage />} />
                <Route path="teams/:teamId" element={<AgentTeamsPage />} />
                <Route path="config" element={<NativeRoute surface="config" />} />
                <Route path="mcp" element={<NativeRoute surface="mcp" />} />
                <Route path="commands" element={<NativeRoute surface="commands" />} />
                <Route path="plugins" element={<NativeRoute surface="plugins" />} />
                <Route path="hooks" element={<NativeRoute surface="hooks" />} />
                <Route path="permissions" element={<NativeRoute surface="permissions" />} />
                <Route path="agents" element={<NativeRoute surface="agents" />} />
                <Route path="skills" element={<NativeRoute surface="skills" />} />
                <Route path="memory" element={<NativeRoute surface="memory" />} />
                <Route path="projects" element={<ProjectsPage />} />
                <Route path="backup" element={<NativeRoute surface="backup" />} />
                <Route path="output-styles" element={<NativeRoute surface="output-styles" />} />
                <Route path="statusline" element={<NativeRoute surface="statusline" />} />
                <Route path="sessions/:projectFolder/:sessionId" element={<NativeRoute surface="sessions" detail="session" />} />
                <Route path="sessions" element={<NativeRoute surface="sessions" />} />
                <Route path="agent-bridge" element={<BridgeEntry />} />
                <Route path="cc-bridge" element={<BridgeEntry />} />
                <Route path="agent-mail" element={<MailEntry />} />
                <Route path="agent-teams" element={<TeamsAlias />} />
                <Route path="plans/:filename" element={<NativeRoute surface="plans" detail="plan" />} />
                <Route path="plans" element={<NativeRoute surface="plans" />} />
                <Route path="context" element={<NativeRoute surface="context" />} />
                <Route path="usage" element={<NativeRoute surface="usage" />} />
              </Route>
            </Routes>
          </BrowserRouter>

      </ProviderProvider>
    </ProjectProvider>
  )
}

export default App
