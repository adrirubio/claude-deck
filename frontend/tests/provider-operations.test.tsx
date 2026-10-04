import { useEffect } from 'react'
import { render, act, cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { ProviderProvider, useProviderContext } from '../src/contexts/ProviderContext'
import { HarnessesPage } from '../src/features/harnesses/HarnessesPage'
import { NativeRoute } from '../src/features/native-settings/NativeRoute'
import { nativeAccess, nativeAdapter, updateNativeCatalog, updateNativeMetadata, assertNativeAction } from '../src/features/native-settings/surfaceRegistry'
import { refreshProviderOperations, resetProviderOperations, isProviderOperations, useProviderOperations } from '../src/hooks/useProviders'
import { apiClient } from '../src/lib/api'
import { providerOperationKeys, type AgentProviderId, type AgentProviderStatus, type ProviderOperations } from '../src/types/providers'
import fixture from './fixtures/provider-operations/v1/catalog.json'
import { fixtureFetch, jsonResponse, operationsFixtureResponse, renderRoute, settle } from './helpers/factory'

vi.mock('../src/features/config/ConfigViewerPage', () => ({ ConfigViewerPage: function Editor() {
  const { selectedProviderId } = useProviderContext()
  useEffect(() => { void apiClient(selectedProviderId === 'codex-cli' ? 'codex-config' : 'config').catch(() => undefined) }, [selectedProviderId])
  return <p>Mounted {selectedProviderId} editor</p>
} }))
vi.mock('../src/features/dashboard/DashboardPage', () => ({ DashboardPage: () => <p>Mounted summary</p> }))
vi.mock('../src/features/plans/PlanDetailPage', () => ({ PlanDetailPage: () => <p>Mounted plan</p> }))
vi.mock('../src/features/sessions/SessionViewPage', () => ({ SessionViewPage: () => <p>Mounted transcript</p> }))
vi.mock('../src/contexts/DashboardContext', () => ({
 DashboardProvider: ({children}: {children: React.ReactNode}) => children,
 useDashboard: () => ({stats: {providerId:'codex-cli',warnings:[],unsupportedFeatures:[], sessionMetricKind:'live',settingsKeys:0},loading:false,error:null,lastFetched:null,refreshDashboard:()=>undefined}),
}))
vi.mock('../src/contexts/ProjectContext', () => ({ useProjectContext: () => ({projects:[]}) }))

const catalogs = fixture.providers as unknown as Record<AgentProviderId, ProviderOperations>
const scenarios = fixture.scenarios as unknown as Record<string, ProviderOperations>
const ids = Object.keys(catalogs) as AgentProviderId[]
const statuses = ids.map(id => ({ id, display_name: id, installed: true, version: 'fixture', config_paths: {}, binary_path: null, capabilities: {config:true,plugins:true,usage:true}, capability_matrix: {...catalogs[id].native_capabilities, config:{state:'write_capable'},plugins:{state:'write_capable'},usage:{state:'supported'}} })) as AgentProviderStatus[]
function answer(path: string) { return operationsFixtureResponse(path) ?? jsonResponse(path === 'providers' ? {providers:statuses} : {}) }
function native(path = '/harnesses/codex-cli/config', route = '/harnesses/:providerId/:surface', element = <NativeRoute />) {
 window.history.replaceState({}, '', path)
 return renderRoute(<ProviderProvider>{element}</ProviderProvider>, path, route)
}
function probe(id: AgentProviderId) { function Probe() { const c = useProviderOperations(id); return <p>{c.state}</p> } return <Probe/> }
function deferred<T>() { let resolve!: (value:T)=>void; const promise=new Promise<T>(r=>{resolve=r}); return {promise,resolve} }
beforeEach(() => { resetProviderOperations(); updateNativeMetadata([]); localStorage.clear(); window.history.replaceState({}, '', '/') })
afterEach(() => { cleanup(); resetProviderOperations(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('accepted provider operations', () => {
 it.each(ids)('validates %s and intersects each catalog with the frozen static adapters', id => {
  const catalog=catalogs[id]
  expect(isProviderOperations(catalog,id)).toBe(true)
  expect(Object.keys(catalog.operations).sort()).toEqual([...providerOperationKeys].sort())
  updateNativeMetadata(statuses); updateNativeCatalog(id,catalog)
  for(const [surface,reported] of Object.entries(catalog.native_surfaces)) {
   const adapter=nativeAdapter(id,surface)
   const access=nativeAccess(id,surface)
   if(!adapter) expect(access).toBeNull()
   else { expect(reported.adapter_id).toBe(`${id}:${surface}:${adapter.component}`); expect(access).toBe(reported.access==='read_only'?'read_only':'write_capable') }
  }
 })
 it('shows all five sourced operation sets with separate credential and generic session unknowns', async () => {
  localStorage.setItem('claude-deck:selected-provider','pi-cli')
  const {requests}=fixtureFetch(answer)
  renderRoute(<ProviderProvider><HarnessesPage/></ProviderProvider>,'/harnesses','/harnesses'); await settle()
  expect(screen.getAllByText('Configured for launch')).toHaveLength(5)
  expect(screen.getAllByText(/Credentials not checked/)).toHaveLength(5)
  expect(screen.getAllByText(/No team slot selected/)).toHaveLength(5)
  expect(screen.getAllByText('Operations and conditions')).toHaveLength(5)
  expect(screen.getByText('execution controls: unsupported')).toBeInTheDocument()
  expect(screen.getAllByText('execution controls: unknown')).toHaveLength(2)
  for(const id of ['copilot-cli','opencode-cli','pi-cli']) expect(within(screen.getByRole('navigation',{name:new RegExp(id==='pi-cli'?'Pi':id==='opencode-cli'?'OpenCode':'Copilot')})).queryByRole('link')).toBeNull()
  expect(requests.filter(r=>r.path.endsWith('/operations'))).toHaveLength(5)
  expect(requests.every(r=>r.method==='GET')).toBe(true)
  expect(localStorage.getItem('claude-deck:selected-provider')).toBe('pi-cli')
 })
 it.each(['binary_missing','mail_not_positively_configured','pending','probe_failed'])('preserves %s configuration uncertainty without claiming credentials or session readiness', async name => {
  fixtureFetch(path=>path.endsWith('/operations')?jsonResponse(scenarios[name]):answer(path))
  renderRoute(<ProviderProvider><HarnessesPage/></ProviderProvider>,'/harnesses/codex-cli','/harnesses/:providerId');await settle()
  expect(screen.queryByText('Configured for launch')).toBeNull()
  expect(screen.getByText(name==='binary_missing'||name==='mail_not_positively_configured'?'Configuration blocked':'Configuration unknown')).toBeInTheDocument()
  expect(screen.getByText(/Credentials not checked/)).toBeInTheDocument()
  expect(screen.getByText(/No team slot selected/)).toBeInTheDocument()
 })
 it('does not fetch the catalog in independent delivery consumers', async () => {
  const {requests}=fixtureFetch(answer)
  renderRoute(<ProviderProvider><p>Delivery fixture</p></ProviderProvider>);await settle()
  expect(requests.map(r=>r.path)).toEqual(['providers'])
 })
})

describe('required catalog native guards', () => {
 it('waits for the catalog before mounting or fetching the editor, with canonical context independent of saved preference', async () => {
  localStorage.setItem('claude-deck:selected-provider','pi-cli')
  const pending=deferred<Response>();const {requests}=fixtureFetch(path=>path.endsWith('/operations')?pending.promise:answer(path))
  native();await settle()
  expect(screen.queryByText(/Mounted/)).toBeNull();expect(requests.map(r=>r.path)).toEqual(['providers','providers/codex-cli/operations'])
  await act(async()=>{pending.resolve(jsonResponse(catalogs['codex-cli']))});await settle()
  expect(screen.getByText('Mounted codex-cli editor')).toBeInTheDocument()
  expect(requests.map(r=>r.path)).toContain('codex-config');expect(requests.map(r=>r.path)).not.toContain('config')
  expect(localStorage.getItem('claude-deck:selected-provider')).toBe('pi-cli')
 })
 it.each(['http_error','missing','wrong_provider','wrong_schema','missing_operation','bound_generic_session'])('fails closed for %s before any native API fetch', async failure => {
  const broken=structuredClone(catalogs['codex-cli'])
  const value:unknown=failure==='missing'?{}:failure==='wrong_provider'?catalogs['claude-code']:failure==='wrong_schema'?{...broken,schema_version:2}:broken
  if(failure==='missing_operation') delete (broken.operations as Partial<typeof broken.operations>).launch
  if(failure==='bound_generic_session') broken.readiness.session={...broken.readiness.session,state:'bound',team_id:1,slot_id:2,member_id:3,session_id:4,observed_provider:'codex-cli'}
  const {requests}=fixtureFetch(path=>path.endsWith('/operations')?jsonResponse(value,failure==='http_error'?503:200):answer(path))
  native();await settle()
  expect(screen.getByText('Native page unavailable')).toBeInTheDocument();expect(screen.queryByText(/Mounted/)).toBeNull()
  await expect(apiClient('codex-config')).rejects.toThrow(/unavailable/)
  expect(requests.map(r=>r.path)).toEqual(['providers','providers/codex-cli/operations'])
 })
 it.each(['/harnesses/codex-cli/config','/config'])('blocks adapter mismatch at canonical/legacy %s', async path => {
  localStorage.setItem('claude-deck:selected-provider','codex-cli')
  const {requests}=fixtureFetch(p=>p.endsWith('/operations')?jsonResponse(scenarios.adapter_mismatch):answer(p))
  native(path,path==='/config'?'/config':'/harnesses/:providerId/:surface',path==='/config'?<NativeRoute surface="config"/>:<NativeRoute/>);await settle()
  expect(screen.getByText('Native page unavailable')).toBeInTheDocument();expect(requests.every(r=>r.path==='providers'||r.path.endsWith('/operations'))).toBe(true)
 })
 it.each(['read_only_config','unknown_config'])('narrows %s and refuses an explicit write override', async name => {
  fixtureFetch(path=>path.endsWith('/operations')?jsonResponse(scenarios[name]):answer(path));native();await settle()
  expect(screen.getByText(name==='read_only_config'?'Native settings are read-only':'Native page unavailable')).toBeInTheDocument()
  expect(screen.queryByText(/Mounted/)).toBeNull()
  expect(()=>assertNativeAction('codex-cli','config','codex-config','PATCH','write_capable')).toThrow()
 })
 it('keeps nested MCP/plugin restrictions even when the config catalog grants writes', async () => {
  const c=structuredClone(catalogs['codex-cli']);c.native_surfaces.mcp.access='read_only';c.native_surfaces.plugins.access='read_only'
  const {requests}=fixtureFetch(path=>path.endsWith('/operations')?jsonResponse(c):answer(path));native();await settle()
  const before=requests.length
  await expect(apiClient('providers/codex-cli/mcp',{method:'POST'})).rejects.toThrow(/does not permit/)
  await expect(apiClient('providers/codex-cli/plugins/example',{method:'DELETE'})).rejects.toThrow(/does not permit/)
  expect(requests).toHaveLength(before)
 })
 it.each([['/harnesses/codex-cli/plans/example','/harnesses/:providerId/plans/:filename','plan'],['/sessions/project/id','/sessions/:projectFolder/:sessionId','session']])('guards detail route %s before mount', async(path,route,detail)=>{
  localStorage.setItem('claude-deck:selected-provider','claude-code')
  const {requests}=fixtureFetch(p=>p.endsWith('/operations')?jsonResponse({},503):answer(p))
  native(path,route,<NativeRoute surface={detail==='plan'?'plans':'sessions'} detail={detail as 'plan'|'session'}/>);await settle()
  expect(screen.getByText('Native page unavailable')).toBeInTheDocument();expect(screen.queryByText(/Mounted/)).toBeNull()
  expect(requests.every(r=>r.path==='providers'||r.path.endsWith('/operations'))).toBe(true)
 })
 it('guards unavailable summary data sources despite a valid summary adapter', async()=>{
  const c=structuredClone(catalogs['codex-cli']); c.native_surfaces.config={...c.native_surfaces.config,state:'unavailable',adapter_id:null,access:'none'}
  const {requests}=fixtureFetch(path=>path.endsWith('/operations')?jsonResponse(c):answer(path));native('/harnesses/codex-cli/summary');await settle()
  expect(screen.getByText('Mounted summary')).toBeInTheDocument()
  const before=requests.length;await expect(apiClient('codex-config')).rejects.toThrow(/unavailable/);await expect(apiClient('providers/codex-cli/features')).rejects.toThrow(/unavailable/);expect(requests).toHaveLength(before)
 })
 it('permits only the known exact operations GET bootstrap and no catalog POST/subpaths', async()=>{
  const {requests}=fixtureFetch(answer);window.history.replaceState({},'', '/harnesses/codex-cli/config')
  await apiClient('providers/codex-cli/operations')
  for(const path of ['providers/foreign/operations','providers/codex-cli/operations/extra']) await expect(apiClient(path)).rejects.toThrow(/known provider GET/)
  await expect(apiClient('providers/codex-cli/operations',{method:'POST'})).rejects.toThrow(/known provider GET/)
  expect(requests).toHaveLength(1)
 })
})

describe('shared catalog observation identity',()=>{
 it('shares one in-flight read for two consumers',async()=>{
  const pending=deferred<Response>();const {requests}=fixtureFetch(()=>pending.promise)
  renderRoute(<>{probe('codex-cli')}{probe('codex-cli')}</>);await settle()
  expect(requests).toHaveLength(1)
  await act(async()=>pending.resolve(jsonResponse(catalogs['codex-cli'])));await settle()
  expect(screen.getAllByText('ready')).toHaveLength(2)
 })
 it('does not let an invalidated late response reinstall permissions',async()=>{
  const old=deferred<Response>();let calls=0;fixtureFetch(()=>++calls===1?old.promise:jsonResponse(scenarios.adapter_mismatch))
  updateNativeMetadata(statuses)
  const first=refreshProviderOperations('codex-cli');resetProviderOperations()
  await refreshProviderOperations('codex-cli');old.resolve(jsonResponse(catalogs['codex-cli']));await first
  expect(nativeAccess('codex-cli','config')).toBeNull()
 })
 it('drops permissions before a refresh and retains no permissive data after failure',async()=>{
  let fail=false;const {requests}=fixtureFetch(path=>path.endsWith('/operations')&&fail?jsonResponse({},503):answer(path))
  native();await settle();expect(screen.getByText('Mounted codex-cli editor')).toBeInTheDocument()
  fail=true;await act(async()=>refreshProviderOperations('codex-cli'));await settle()
  expect(screen.queryByText(/Mounted/)).toBeNull()
  const before=requests.length;await expect(apiClient('codex-config',{method:'PATCH'})).rejects.toThrow(/unavailable/);expect(requests).toHaveLength(before)
 })
 it('expires cached permissions before a newly mounted route can fetch',async()=>{
  fixtureFetch(answer);updateNativeMetadata(statuses);await refreshProviderOperations('codex-cli')
  const time=Date.now();vi.spyOn(Date,'now').mockReturnValue(time+60_001)
  expect(nativeAccess('codex-cli','config')).toBeNull()
  const {requests}=fixtureFetch(path=>path.endsWith('/operations')?jsonResponse({},503):answer(path));native();await settle()
  expect(screen.queryByText(/Mounted/)).toBeNull();expect(requests.map(r=>r.path)).not.toContain('codex-config')
 })
 it('retains the current provider identity after an older route response arrives',async()=>{
  const old=deferred<Response>();const {requests}=fixtureFetch(path=>path==='providers/codex-cli/operations'?old.promise:answer(path))
  function Switch(){const navigate=useNavigate();return <><button onClick={()=>{window.history.replaceState({},'', '/harnesses/claude-code/config');navigate('/harnesses/claude-code/config')}}>Switch route</button><NativeRoute/></>}
  window.history.replaceState({},'', '/harnesses/codex-cli/config')
  render(<MemoryRouter initialEntries={['/harnesses/codex-cli/config']}><ProviderProvider><Routes><Route path="/harnesses/:providerId/:surface" element={<Switch/>}/></Routes></ProviderProvider></MemoryRouter>)
  await settle();fireEvent.click(screen.getByText('Switch route'));await settle();expect(screen.getByText('Mounted claude-code editor')).toBeInTheDocument()
  await act(async()=>old.resolve(jsonResponse(catalogs['codex-cli'])));await settle()
  expect(screen.getByText('Mounted claude-code editor')).toBeInTheDocument();expect(requests.map(r=>r.path)).not.toContain('codex-config')
 })
 it('narrows dashboard native destinations with the same catalog intersection',async()=>{
  const {DashboardPage}=await vi.importActual<typeof import('../src/features/dashboard/DashboardPage')>('../src/features/dashboard/DashboardPage')
  localStorage.setItem('claude-deck:selected-provider','codex-cli')
  fixtureFetch(path=>path.endsWith('/operations')?jsonResponse(scenarios.read_only_config):answer(path))
  renderRoute(<ProviderProvider><DashboardPage/></ProviderProvider>);await settle()
  expect(screen.getByRole('button',{name:/View Codex config/})).toBeDisabled()
  expect(screen.getByRole('button',{name:/Manage feature flags/})).toBeDisabled()
  expect(screen.getByRole('button',{name:/View all plans/})).toBeEnabled()
  expect(screen.getByText(/Configured for launch.*Credentials: unknown.*Session: unknown/)).toBeInTheDocument()
 })
})
