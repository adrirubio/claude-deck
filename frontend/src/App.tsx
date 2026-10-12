import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Toaster } from 'sonner'
import { ProjectProvider } from './contexts/ProjectContext'
import { ProviderProvider } from './contexts/ProviderContext'
import { MainLayout } from './components/layout/MainLayout'
import { ProjectsPage } from './features/projects/ProjectsPage'
import { NativeRoute } from './features/native-settings/NativeRoute'
import { LegacyNativeRedirect } from './features/native-settings/LegacyNativeRedirect'
import { HarnessesPage } from './features/harnesses/HarnessesPage'
import { OverviewPage } from './features/factory/pages/OverviewPage'
import { WorkPage } from './features/factory/pages/WorkPage'
import { WorkDetailPage } from './features/factory/pages/WorkDetailPage'
import { RepositoriesPage } from './features/factory/pages/RepositoriesPage'
import { RepositoryPage } from './features/factory/pages/RepositoryPage'
import { BridgeEntry, MailEntry } from './features/factory/ContextPages'
import { AgentTeamsPage } from './features/agent-teams/AgentTeamsPage'
import { RepositorySetupPage } from './features/factory/RepositorySetupPage'
import { AuditMetricsPage } from './features/factory/AuditMetricsPanel'

function TeamsAlias() { const { search, hash } = useLocation(); return <Navigate replace to={`/teams${search}${hash}`} /> }

function App() {
  return (
    <BrowserRouter>
      <ProjectProvider>
        <ProviderProvider>

            <Toaster richColors position="top-right" />
            <Routes>
              <Route path="/" element={<MainLayout />}>
                <Route index element={<OverviewPage />} />
                <Route path="work" element={<WorkPage />} />
                <Route path="audit" element={<AuditMetricsPage />} />
                <Route path="work/:workItemId" element={<WorkDetailPage />} />
                <Route path="repositories" element={<RepositoriesPage />} />
                <Route path="repositories/new" element={<RepositorySetupPage />} />
                <Route path="repositories/:scopeId" element={<RepositoryPage />} />
                <Route path="harnesses" element={<HarnessesPage />} />
                <Route path="harnesses/:providerId" element={<HarnessesPage />} />
                <Route path="harnesses/:providerId/:surface" element={<NativeRoute />} />
                <Route path="harnesses/:providerId/plans/:filename" element={<NativeRoute surface="plans" detail="plan" />} />
                <Route path="harnesses/:providerId/sessions/:projectFolder/:sessionId" element={<NativeRoute surface="sessions" detail="session" />} />
                <Route path="teams" element={<AgentTeamsPage />} />
                <Route path="teams/:teamId" element={<AgentTeamsPage />} />
                <Route path="config" element={<LegacyNativeRedirect />} />
                <Route path="mcp" element={<LegacyNativeRedirect />} />
                <Route path="commands" element={<LegacyNativeRedirect />} />
                <Route path="plugins" element={<LegacyNativeRedirect />} />
                <Route path="hooks" element={<LegacyNativeRedirect />} />
                <Route path="permissions" element={<LegacyNativeRedirect />} />
                <Route path="agents" element={<LegacyNativeRedirect />} />
                <Route path="skills" element={<LegacyNativeRedirect />} />
                <Route path="memory" element={<LegacyNativeRedirect />} />
                <Route path="projects" element={<Navigate replace to="/harnesses/folders" />} />
                <Route path="harnesses/folders" element={<ProjectsPage />} />
                <Route path="backup" element={<LegacyNativeRedirect />} />
                <Route path="output-styles" element={<LegacyNativeRedirect />} />
                <Route path="statusline" element={<LegacyNativeRedirect />} />
                <Route path="sessions/:projectFolder/:sessionId" element={<LegacyNativeRedirect />} />
                <Route path="sessions" element={<LegacyNativeRedirect />} />
                <Route path="agent-bridge" element={<BridgeEntry />} />
                <Route path="cc-bridge" element={<BridgeEntry />} />
                <Route path="agent-mail" element={<MailEntry />} />
                <Route path="agent-teams" element={<TeamsAlias />} />
                <Route path="plans/:filename" element={<LegacyNativeRedirect />} />
                <Route path="plans" element={<LegacyNativeRedirect />} />
                <Route path="context" element={<LegacyNativeRedirect />} />
                <Route path="usage" element={<LegacyNativeRedirect />} />
              </Route>
            </Routes>

        </ProviderProvider>
      </ProjectProvider>
    </BrowserRouter>
  )
}

export default App
