// Issue14 synthetic acceptance fixture. Run through product-heavy after npm run build.
// Inline data is deliberately independent of the immutable P01/v1 fixtures.
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { spawn, execFileSync } from 'node:child_process';
import assert from 'node:assert/strict';

const evidence = process.env.AUTONOMY_EVIDENCE_DIR;
assert(evidence, 'AUTONOMY_EVIDENCE_DIR is required');
await fs.mkdir(evidence, { recursive: true });
const measureOnly = process.env.AUTONOMY_MEASURE_ONLY === '1';
const stamp = '2026-10-04T12:00:00Z';
const long = 'synthetic-long-repository-and-issue-name-without-secret-material-';
const preset = { id: 1, name: 'Synthetic autonomy team', created_at: stamp, updated_at: stamp,
  autonomy_enabled: false, slots: [{ id: 1, preset_id: 1, display_name: 'Synthetic Leader',
    provider: 'codex-cli', repo_path: '/fixture/product', enabled: true, position: 0,
    launch_mode: 'plain', launch_options: {}, created_at: stamp, updated_at: stamp }] };
const scopes = [1, 2].map(id => ({ id, preset_id: 1, repo_owner: 'synthetic',
  repo_name: id === 1 ? long.repeat(2) : 'second-repo', repo_path: '/fixture/' + long.repeat(2),
  dispatch_label: 'ready-' + long, design_label: 'design-' + long, merge_policy: 'human',
  github_auth_mode: 'app', github_auth_configured: true, github_poll_token_configured: true,
  max_approval_rounds: 3, max_concurrent_dispatched: 1, max_verification_retries: 2,
  max_auto_merges_per_day: 0, base_ref: 'origin/integration', builds_out_of_tree: false,
  build_dir_template: 'build', build_command_hint: null, max_build_parallelism: 1,
  continuation_enabled: false, max_continuation_revisions: 3, max_continuation_failed_heads: 8,
  max_failed_heads_per_revision: 2, max_scope_paths: 4, max_scope_commands: 8,
  enabled: true, created_at: stamp, updated_at: stamp, last_polled_at: stamp }));
const items = ['pending', 'ready_for_review', 'escalated', 'merged'].map((status, i) => ({
  id: i + 1, scope_id: i === 3 ? 2 : 1, repo_owner: 'synthetic',
  repo_name: i === 3 ? 'second-repo' : scopes[0].repo_name, issue_number: i + 101,
  issue_title: 'Synthetic ' + long.repeat(3), issue_url: `https://example.test/issues/${i + 101}`,
  issue_type: 'code', dispatch_status: status, owner_slot_id: 1, routing_method: 'leader_fallback',
  pending_reason: status === 'pending' ? 'queued_slot_busy' : null,
  escalation_reason: status === 'escalated' ? 'approval_rounds_exhausted' : null,
  status_note: status === 'escalated' ? 'Synthetic reason ' + long.repeat(2) : null,
  pr_number: i === 0 ? null : i + 201, approval_round_count: 1,
  retry_count: i, diagnostic_retry_count: i, active_scope_revision: 0,
  attempt_phase: 'implementation', retry_allowed: false, retry_block_code: 'owner_still_active',
  created_at: stamp, updated_at: stamp, github_updated_at: stamp,
  workspace_path: '/fixture/' + long.repeat(3), continuation_block_code: 'continuation_disabled' }));
let firstRun = false;
const requests = [], unknown = [], errors = [], observations = [], keyboard = [], failures = [];
function respond(url) {
  const key = url.pathname.replace('/api/v1/', '');
  if (key === 'agent-teams/presets') return { presets: [preset] };
  if (key.endsWith('/github-scopes')) return { scopes: firstRun ? [] : scopes };
  if (key.endsWith('/github-work-items')) return { items: firstRun ? [] : items };
  if (key === 'agent-teams/github-recovery-gate/active') return { active: false };
  if (key.endsWith('/scope-revisions')) return [];
  if (key.endsWith('/activity')) return { preset_id: 1, slots: [], valid_until: new Date(Date.now()+15000).toISOString() };
  if (key.endsWith('/coordination')) return { scope_id: Number(key.split('/')[2]),
    repo: 'synthetic/repo', enabled: false, version: 1, issue_numbers: [], entries: [],
    fallback_seconds: 1800, max_daily_requests: 12, requests_today: 0, status: 'disabled',
    last_polled_at: null, observation_expires_at: null, last_assessed_at: null,
    active_implementations: null, execution_limit: 1, available_workspaces: null,
    leased_workspaces: null, eligible_count: null, assessment_current: false };
  if (key.endsWith('/launch-options')) return { provider: key.split('/')[1],
    supported_launch_modes: ['plain'], supported_launch_options: [], platform_options: [],
    model_options: [], reasoning_effort_options: [], context_tier_options: [], profile_options: [], warnings: [] };
  if (key === 'agent-bridge/sessions') return { sessions: [], count: 0 };
  if (key === 'agent-mail/team') return { members: [], presets: [], slots: [] };
  if (key === 'projects') return { projects: [], count: 0 };
  if (key === 'providers') return { providers: [], count: 0 };
  if (key === 'status') return { active_sessions: 0, providers: {}, instance: {
    name: 'Synthetic autonomy fixture', hostname: 'fixture', accent: 'blue' }, environment: {} };
  unknown.push(key); return null;
}
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://fixture.test');
    if (url.pathname.startsWith('/api/v1/')) {
      requests.push({ path: url.pathname, method: req.method });
      assert.equal(req.method, 'GET', 'Synthetic browser must never mutate');
      const data = respond(url);
      res.writeHead(data === null ? 404 : 200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(data)); return;
    }
    const root = path.resolve('dist');
    let file = path.resolve(root, '.' + decodeURIComponent(url.pathname));
    assert(file === root || file.startsWith(root + path.sep), 'Invalid asset path');
    try { if (!(await fs.stat(file)).isFile()) file = path.join(root, 'index.html'); }
    catch { file = path.join(root, 'index.html'); }
    res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' :
      file.endsWith('.css') ? 'text/css' : file.endsWith('.png') ? 'image/png' : 'text/html');
    res.end(await fs.readFile(file));
  } catch (error) { errors.push(String(error)); res.writeHead(500); res.end('Synthetic fixture error'); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;
const profile = await fs.mkdtemp(path.join(evidence, 'chrome-profile-'));
const chrome = spawn('/usr/bin/google-chrome', ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', `--user-data-dir=${profile}`, '--remote-debugging-port=0', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let ws;
try {
  let debugPort;
  for (let i = 0; i < 100; i++) {
    try { debugPort = Number((await fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]); break; }
    catch { await sleep(100); }
  }
  assert(debugPort, 'Chrome debugging unavailable');
  const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
  ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let seq = 0;
  const pending = new Map();
  ws.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.id) { const p = pending.get(data.id); pending.delete(data.id);
      if (data.error) p.reject(Error(JSON.stringify(data.error))); else p.resolve(data.result); }
    else if (data.method === 'Runtime.exceptionThrown') errors.push(data.params.exceptionDetails);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params })); });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails)); return result.result.value;
  };
  const waitFor = async expression => {
    for (let i = 0; i < 100; i++) { if (await evaluate(expression)) return; await sleep(50); }
    throw Error('Timed out: ' + expression);
  };
  const key = async (name, modifiers = 0) => {
    const codes = { Tab: 9, Enter: 13, Escape: 27, ArrowDown: 40, ArrowUp: 38, End: 35, Home: 36 };
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: name, code: name, windowsVirtualKeyCode: codes[name], modifiers,
      ...(name === 'Enter' ? { text: '\r', unmodifiedText: '\r' } : {}) });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: name, code: name, windowsVirtualKeyCode: codes[name], modifiers });
    await sleep(30);
  };
  const focus = async selector => {
    assert(await evaluate(`Boolean(document.querySelector(${JSON.stringify(selector)}))`), 'Missing focus target '+selector);
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).focus()`);
    await key('Tab'); await key('Tab', 8); // enter through keyboard to reveal focus-visible
    const focused = await evaluate(`({target:document.activeElement===document.querySelector(${JSON.stringify(selector)}),visible:document.activeElement.matches(':focus-visible'),outline:getComputedStyle(document.activeElement).outlineStyle,shadow:getComputedStyle(document.activeElement).boxShadow})`);
    assert(focused.target && focused.visible, 'Keyboard focus lost: '+selector); keyboard.push({selector,...focused});
  };
  const capture = async (name, width, theme) => {
    // Bring the evidence subject into view; Teams summary cards precede this tab.
    await evaluate(`(() => {if(document.querySelector('[role=dialog],[role=alertdialog]'))return;
      const subject=${JSON.stringify(name)}==='first-run'
        ? document.querySelector('[role=tabpanel][data-state=active]')
        : [...document.querySelectorAll('h3')].find(el=>el.textContent==='Activity');
      subject?.scrollIntoView({block:'start',inline:'nearest'});})()`);
    await sleep(100);
    const layout = await evaluate(`(() => {
      const rect = el => {if(!el)return null;const r=el.getBoundingClientRect();return {width:el.clientWidth,scrollWidth:el.scrollWidth,left:r.left,right:r.right};};
      const main=document.querySelector('main'),pane=document.querySelector('[role=tabpanel][data-state=active]'),dialog=document.querySelector('[role=dialog],[role=alertdialog]');
      const table=document.querySelector('table'),scroll=table?.parentElement;
      const controls=[...document.querySelectorAll(dialog?'[role=dialog] button,[role=alertdialog] button':'[role=tabpanel][data-state=active] button')].filter(b=>/^(Save repo|Save policy|Cancel|Clear operator token|Refresh)$/.test(b.textContent.trim())).map(b=>({text:b.textContent.trim(),...rect(b)}));
      return {viewport:innerWidth,theme:document.documentElement.className,documentWidth:document.documentElement.scrollWidth,main:rect(main),pane:rect(pane),dialog:rect(dialog),tableScroll:rect(scroll),controls,
      overflowElements:[...document.querySelectorAll(dialog?'[role=dialog] *':'main *')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0 && r.right>innerWidth+1 && !el.closest('table')}).slice(0,12).map(el=>({tag:el.tagName,text:el.textContent.slice(0,80),...rect(el)}))};})()`);
    observations.push({name,width,requestedTheme:theme,...layout});
    if(layout.documentWidth>width+1) failures.push(`${name}/${theme}/${width}: document ${layout.documentWidth}`);
    for(const field of ['main','pane','dialog']) {const box=layout[field];if(box&&box.scrollWidth>box.width+1)failures.push(`${name}/${theme}/${width}: ${field} ${box.scrollWidth}/${box.width}`);}
    if(layout.dialog&&(layout.dialog.left< -1||layout.dialog.right>width+1))failures.push(`${name}/${theme}/${width}: dialog outside viewport`);
    for(const control of layout.controls)if(control.left< -1||control.right>width+1)failures.push(`${name}/${theme}/${width}: clipped ${control.text}`);
    if(layout.dialog){
      const reach=await evaluate(`(() => {const d=document.querySelector('[role=dialog],[role=alertdialog]');return [...d.querySelectorAll('button')].filter(b=>/^(Save repo|Save policy|Cancel)$/.test(b.textContent.trim())).map(b=>{b.scrollIntoView({block:'nearest',inline:'nearest'});const r=b.getBoundingClientRect(),box=d.getBoundingClientRect();return {text:b.textContent.trim(),reachable:r.left>=box.left-1&&r.right<=box.right+1&&r.top>=Math.max(0,box.top)-1&&r.bottom<=Math.min(innerHeight,box.bottom)+1};});})()`);
      keyboard.push({dialogControls:name,width,theme,reach});
      for(const control of reach)if(!control.reachable)failures.push(`${name}/${theme}/${width}: unreachable ${control.text}`);
    }
    const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
    await fs.writeFile(path.join(evidence,`${name}-${theme}-${width}.png`),Buffer.from(shot.data,'base64'));
  };
  const openDialog = async selector => {
    await focus(selector); await key('Enter'); await waitFor('Boolean(document.querySelector("[role=dialog],[role=alertdialog]"))');
    for(let i=0;i<18;i++){await key('Tab');assert(await evaluate('Boolean(document.activeElement.closest("[role=dialog],[role=alertdialog]"))'),'Dialog focus escaped');}
  };
  const closeDialog = async selector => {
    await key('Escape');await waitFor('!document.querySelector("[role=dialog],[role=alertdialog]")');
    const restored=await evaluate(`({returned:document.activeElement===document.querySelector(${JSON.stringify(selector)}),active:document.activeElement.outerHTML.slice(0,300)})`);
    keyboard.push({closedDialog:selector,...restored});
    if(!restored.returned){failures.push('Dialog focus did not return: '+selector);if(!measureOnly)assert(restored.returned,'Dialog focus did not return');}
  };
  await send('Page.enable');await send('Runtime.enable');
  for(const theme of ['light','dark'])for(const width of [1440,768,360]){
    await send('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
    firstRun=false;
    await send('Page.addScriptToEvaluateOnNewDocument',{source:`localStorage.setItem('theme',${JSON.stringify(theme)});sessionStorage.setItem('claude-deck.agent-teams.operator-token','synthetic-browser-only');`});
    await send('Page.navigate',{url:`http://127.0.0.1:${port}/teams/1?tab=autonomy`});
    await waitFor('Boolean(document.querySelector("table tbody tr"))');
    await capture('populated',width,theme);
    if(width===1440){
      await focus('button[role=switch][aria-label="Enable autonomous GitHub dispatch"]');
      const seen=[];
      for(let i=0;i<55;i++){seen.push(await evaluate(`({name:document.activeElement.getAttribute('aria-label')||document.activeElement.textContent.trim(),id:document.activeElement.id})`));await key('Tab');}
      keyboard.push({tabJourney:seen,theme,width});
      for(const required of ['Clear operator token','Refresh','What do statuses, phases, and routes mean?','View issue #103 details'])assert(seen.some(e=>e.name===required),'Missing natural Tab target '+required);
      for(const id of ['activity-repo-filter','activity-status-filter'])assert(seen.some(e=>e.id===id),'Missing natural Tab target '+id);
    }
    const help='button[aria-controls=autonomy-activity-help]';
    await focus(help);await key('Enter');await waitFor('Boolean(document.querySelector("#autonomy-activity-help"))');
    await capture('help-open',width,theme);
    const detail='button[aria-label="View issue #103 details"]';
    await openDialog(detail);await capture('detail-dialog',width,theme);await closeDialog(detail);
    const edit=`button[aria-label=${JSON.stringify('Edit synthetic/'+scopes[0].repo_name)}]`;
    await openDialog(edit);
    await focus('#scope-merge-policy');await key('Enter');await waitFor('Boolean(document.querySelector("[role=listbox]"))');
    await key('ArrowDown');await key('Enter');
    await capture('scope-dialog',width,theme);await closeDialog(edit);
    const remove=`button[aria-label=${JSON.stringify('Remove synthetic/'+scopes[0].repo_name)}]`;
    await openDialog(remove);await capture('remove-dialog',width,theme);await closeDialog(remove);
    for(const selector of ['#activity-repo-filter','#activity-status-filter']){
      await focus(selector);await key('Enter');await waitFor('Boolean(document.querySelector("[role=listbox]"))');await key('ArrowDown');await key('Enter');
    }
    // Open the named switch by keyboard, then cancel without protected mutation.
    const toggle='button[role=switch][aria-label="Enable autonomous GitHub dispatch"]';
    await openDialog(toggle);await capture('enable-dialog',width,theme);await closeDialog(toggle);
    firstRun=true;
    await send('Page.navigate',{url:`http://127.0.0.1:${port}/teams/1?tab=autonomy`});
    await waitFor('document.body.innerText.includes("Before you enable autonomy")');
    await capture('first-run',width,theme);
    const add='button';
    await evaluate(`window.fixtureAdd=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Add repo');window.fixtureAdd.setAttribute('data-fixture-add','true')`);
    await openDialog(add+'[data-fixture-add]');await capture('add-dialog',width,theme);await closeDialog(add+'[data-fixture-add]');
  }
  assert.equal(unknown.length,0,'Unknown synthetic API route');assert.equal(errors.length,0,'Browser/server errors');
  assert(requests.every(r=>r.method==='GET'),'Protected mutation attempted');
  if(!measureOnly)assert.deepEqual(failures,[],'Autonomy layout acceptance failed');
} finally {
  const head=execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
  const dirty=execFileSync('git',['status','--porcelain=v1'],{encoding:'utf8'}).trim();
  await fs.writeFile(path.join(evidence,'browser.json'),JSON.stringify({head,dirty,synthetic:true,measureOnly,observations,keyboard,failures,requests,unknown,errors},null,2)+'\n');
  console.log(JSON.stringify({head,measureOnly,screenshots:observations.length,keyboardChecks:keyboard.length,failures,unknown,errors:errors.length}));
  ws?.close();
  if(chrome.exitCode===null&&chrome.signalCode===null){const exited=new Promise(resolve=>chrome.once('exit',resolve));chrome.kill();await exited;}
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  await fs.rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}
