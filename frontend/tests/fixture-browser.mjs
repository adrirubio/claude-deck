// Isolated P01 fixture UI checks. Run only through product-heavy.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import assert from "node:assert/strict";
const evidence = process.env.P02_EVIDENCE_DIR;
assert(evidence, "P02_EVIDENCE_DIR is required");
await fs.mkdir(evidence, { recursive: true });
const fixtures = async (name) =>
  JSON.parse(await fs.readFile(`tests/fixtures/factory/v1/${name}.json`));
const [overview, work, detail, repos, repo] = await Promise.all(
  ["overview", "work-items", "work-item", "repositories", "repository"].map(
    fixtures,
  ),
);
const providers = [
  "claude-code",
  "codex-cli",
  "copilot-cli",
  "opencode-cli",
  "pi-cli",
].map((id) => ({
  id,
  display_name: id,
  installed: true,
  version: "fixture",
  capabilities: {
    config: true,
    plugins: true,
    usage: true,
    plans: true,
    sessions: true,
  },
  capability_matrix: {
    config: { state: "write_capable" },
    plugins: { state: "write_capable" },
    usage: { state: "supported" },
  },
  config_paths: {},
}));
const stamp = "2026-09-30T12:00:00Z";
const preset = {
  id: 1,
  name: "Fixture team 1",
  description: "Fixture roster",
  created_at: stamp,
  updated_at: stamp,
  autonomy_enabled: false,
  slots: [1, 2].map((id) => ({
    id,
    preset_id: 1,
    display_name: id === 1 ? "Leader" : "Owner",
    provider: "codex-cli",
    repo_path: "/fixture/product",
    role: id === 1 ? "Leader" : "Implementer",
    charter: "Fixture",
    launch_mode: "plain",
    launch_options: {},
    enabled: true,
    position: id - 1,
    created_at: stamp,
    updated_at: stamp,
  })),
};
const requests = [],
  unknown = [];
function respond(req) {
  const url = new URL(req.url, "http://fixture.test"),
    key = url.pathname.replace("/api/v1/", "");
  requests.push({
    path: key,
    method: req.method,
    query: Object.fromEntries(url.searchParams),
  });
  assert.equal(req.method, "GET", "Fixture browser must never mutate");
  if (key === "factory/overview") return overview.normal.response;
  if (key === "factory/work-items") {
    const cat = url.searchParams.get("category");
    return work[
      cat && cat !== "all"
        ? cat
        : url.searchParams.has("cursor")
          ? "next_page"
          : "first_page"
    ].response;
  }
  if (key === "factory/work-items/6") return detail.operator_stop_retry_eligible.response;
  if (key.startsWith("factory/work-items/")) return detail.completed.response;
  if (key === "factory/repositories") return repos.normal.response;
  if (key.startsWith("factory/repositories/"))
    return repo.fresh_overlap.response;
  if (key === "codex-config/files") return { files: [], count: 0 };
  if (key === "codex-config")
    return {
      provider: "codex-cli",
      path: "/fixture/config.toml",
      exists: true,
      parse_error: null,
      summary: { projects: {}, profiles: {}, features: {} },
      profile_resolution: null,
    };
  if (key === "providers/codex-cli/doctor")
    return {
      provider: "codex-cli",
      provider_display_name: "Codex",
      exit_code: 0,
      report: { overallStatus: "ok", checks: {} },
      parse_error: null,
      stderr: "",
    };
  if (key === "providers/codex-cli/features")
    return {
      provider: "codex-cli",
      features: [],
      exit_code: 0,
      stderr: "",
      raw_stdout: "",
    };
  if (key === "providers/codex-cli/mcp")
    return {
      provider: "codex-cli",
      servers: {},
      exit_code: 0,
      parse_error: null,
      stderr: "",
      raw_stdout: "",
    };
  if (key === "providers/codex-cli/plugins")
    return {
      provider: "codex-cli",
      plugins: [],
      exit_code: 0,
      mutation_capabilities: Object.fromEntries(
        ["install", "remove", "enable", "disable"].map((k) => [
          k,
          { state: "unsupported", reason: "Fixture read inventory" },
        ]),
      ),
      stderr: "",
      raw_stdout: "",
    };
  if (key === "providers") return { providers, count: 5 };
  if (key === "status")
    return {
      active_sessions: 0,
      providers: Object.fromEntries(providers.map((p) => [p.id, p])),
      instance: {
        name: "Isolated P01 fixture",
        hostname: "fixture",
        accent: "blue",
      },
      environment: {},
    };
  if (key === "projects") return { projects: [], count: 0 };
  if (key === "agent-teams/presets") return { presets: [preset] };
  if (/agent-teams\/presets\/\d+\/github-scopes/.test(key))
    return { scopes: [] };
  if (/agent-teams\/presets\/\d+\/github-work-items/.test(key))
    return { items: [] };
  if (key === "agent-teams/github-recovery-gate/active")
    return { active: false };
  if (key.endsWith("/launch-options"))
    return {
      provider: key.split("/")[1],
      supported_launch_modes: ["plain"],
      supported_launch_options: [],
      platform_options: [],
      model_options: [],
      reasoning_effort_options: [],
      context_tier_options: [],
      profile_options: [],
      warnings: [],
    };
  if (key === "agent-bridge/sessions") return { sessions: [], count: 0 };
  unknown.push(key);
  return null;
}
const server = http.createServer(async (req, res) => {
  try {
    if (req.url.startsWith("/api/v1/")) {
      const data = respond(req);
      res.writeHead(data ? 200 : 404, { "Content-Type": "application/json" });
      res.end(JSON.stringify(data ?? { detail: "No fixture for endpoint" }));
      return;
    }
    let file = path.join(
      process.cwd(),
      "dist",
      decodeURIComponent(req.url.split("?")[0]),
    );
    if (!file.startsWith(path.join(process.cwd(), "dist")))
      throw Error("Invalid asset path");
    try {
      const stat = await fs.stat(file);
      if (!stat.isFile()) file = path.join(process.cwd(), "dist/index.html");
    } catch {
      file = path.join(process.cwd(), "dist/index.html");
    }
    res.setHeader(
      "Content-Type",
      file.endsWith(".js")
        ? "application/javascript"
        : file.endsWith(".css")
          ? "text/css"
          : file.endsWith(".png")
            ? "image/png"
            : "text/html",
    );
    res.end(await fs.readFile(file));
  } catch (error) {
    res.writeHead(500);
    res.end(String(error));
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;
const profile = await fs.mkdtemp(path.join(evidence, "chrome-profile-"));
const chrome = spawn(
  "/usr/bin/google-chrome",
  [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    `--user-data-dir=${profile}`,
    "--remote-debugging-port=0",
    "about:blank",
  ],
  { stdio: "ignore" },
);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let ws;
try {
  let debugPort;
  for (let i = 0; i < 100; i++) {
    try {
      debugPort = Number(
        (
          await fs.readFile(path.join(profile, "DevToolsActivePort"), "utf8")
        ).split("\n")[0],
      );
      break;
    } catch {
      await sleep(100);
    }
  }
  assert(debugPort, "Chrome debug endpoint unavailable");
  const targets = await (
    await fetch(`http://127.0.0.1:${debugPort}/json/list`)
  ).json();
  ws = new WebSocket(
    targets.find((t) => t.type === "page").webSocketDebuggerUrl,
  );
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  let seq = 0;
  const pending = new Map(),
    errors = [];
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.id) {
      const p = pending.get(data.id);
      pending.delete(data.id);
      if (data.error) p.reject(Error(JSON.stringify(data.error)));
      else p.resolve(data.result);
    } else if (data.method === "Runtime.exceptionThrown")
      errors.push(data.params.exceptionDetails);
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  const evaluate = async (expression) =>
    (
      await send("Runtime.evaluate", {
        expression,
        returnByValue: true,
        awaitPromise: true,
      })
    ).result.value;
  await send("Page.enable");
  await send("Runtime.enable");
  const observations = [],
    keyboard = [],
    navigation = [],
    retryConfirmations = [];
  for (const width of [360, 768, 1280]) {
    await send("Emulation.setDeviceMetricsOverride", {
      width,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    for (const [name, route, text] of [
      ["overview", "/", "132 matching work"],
      ["work", "/work", "Work"],
      ["detail", "/work/9", "delivery and human review are unconfirmed"],
      ["retry-confirmation", "/work/6", "Fixture issue 6"],
      ["repository", "/repositories/1", "Same-label overlap"],
      ["harnesses", "/harnesses", "Harnesses"],
      ["native-codex", "/harnesses/codex-cli/config", "Codex Config"],
      [
        "unsupported",
        "/harnesses/opencode-cli/config",
        "Native page unavailable",
      ],
      [
        "launch",
        "/teams/1?slot_id=1&review_launch=1",
        "Review selected slot launch",
      ],
    ]) {
      await send("Page.navigate", { url: `http://127.0.0.1:${port}${route}` });
      for (let i = 0; i < 100; i++) {
        if (
          await evaluate(
            `document.body.innerText.includes(${JSON.stringify(text)})`,
          )
        )
          break;
        await sleep(50);
      }
      assert(
        await evaluate(
          `document.body.innerText.includes(${JSON.stringify(text)})`,
        ),
        `${name} did not render`,
      );
      await sleep(100);
      if (name === "retry-confirmation") {
        // Synthetic cached credential; confirmation/cancellation must remain GET-only.
        await evaluate(`sessionStorage.setItem("claude-deck.agent-teams.operator-token", "fixture-only");
          [...document.querySelectorAll("button")].find(b=>b.textContent==="Retry issue").click()`);
        for (let i = 0; i < 20; i++) {
          if (await evaluate('Boolean(document.querySelector("[role=alertdialog]"))')) break;
          await sleep(50);
        }
        assert(await evaluate('document.querySelector("[role=alertdialog]")?.textContent.includes("discard prior PR, handoff, and attempt markers")'), "Cached retry skipped confirmation");
        assert(!(await evaluate('Boolean(document.querySelector("input[type=password]"))')), "Cached retry unexpectedly prompted for credentials");
      }
      const layout = await evaluate(
        '({width:innerWidth,bodyWidth:document.documentElement.scrollWidth,mainWidth:document.querySelector("main").clientWidth,mainScrollWidth:document.querySelector("main").scrollWidth,heading:document.querySelector("main h2")?.textContent})',
      );
      assert(
        layout.bodyWidth <= width,
        `${name} body overflow at ${width}: ${layout.bodyWidth}`,
      );
      const shot = await send("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: false,
      });
      await fs.writeFile(
        path.join(evidence, `${name}-${width}.png`),
        Buffer.from(shot.data, "base64"),
      );
      observations.push({ name, route, ...layout });
      if (name === "retry-confirmation") {
        await evaluate('[...document.querySelectorAll("[role=alertdialog] button")].find(b=>b.textContent==="Cancel").click()');
        await sleep(100);
        assert(!(await evaluate('Boolean(document.querySelector("[role=alertdialog]"))')), "Retry cancellation left confirmation open");
        assert.equal(requests.filter((r) => r.method !== "GET").length, 0);
        retryConfirmations.push({ width, cached_credential: true, cancelled: true, mutations: 0 });
        await evaluate('sessionStorage.removeItem("claude-deck.agent-teams.operator-token")');
      }
      if (name === "work") {
        await evaluate(
          '[...document.querySelectorAll("button")].find(b=>b.textContent==="Load more").click()',
        );
        for (let i = 0; i < 100; i++) {
          if (
            await evaluate('document.querySelectorAll("tbody tr").length===4')
          )
            break;
          await sleep(50);
        }
        const before = await evaluate(`(() => {
          const main=document.querySelector("main"),table=document.querySelector("[data-work-table]");
          const link=[...document.querySelectorAll("a")].filter(a=>a.textContent==="Open details").at(-1);
          link.focus({preventScroll:true});main.scrollTop=200;table.scrollLeft=180;
          return {top:main.scrollTop,left:table.scrollLeft,href:link.getAttribute("href"),rows:document.querySelectorAll("tbody tr").length};
        })()`);
        const reads = requests.filter(
          (r) => r.path === "factory/work-items",
        ).length;
        await evaluate(
          '[...document.querySelectorAll("a")].filter(a=>a.textContent==="Open details").at(-1).click()',
        );
        for (let i = 0; i < 100; i++) {
          if (
            await evaluate(
              'document.body.innerText.includes("delivery and human review are unconfirmed")',
            )
          )
            break;
          await sleep(50);
        }
        await evaluate(
          'document.querySelector("main").scrollTop=0;history.back()',
        );
        for (let i = 0; i < 100; i++) {
          if (
            await evaluate(
              'document.body.innerText.includes("Live updates paused")',
            )
          )
            break;
          await sleep(50);
        }
        const after = await evaluate(
          '({top:document.querySelector("main").scrollTop,left:document.querySelector("[data-work-table]")?.scrollLeft,href:document.activeElement?.getAttribute("href"),rows:document.querySelectorAll("tbody tr").length,paused:document.body.innerText.includes("Live updates paused")})',
        );
        assert.equal(after.rows, before.rows);
        assert.equal(after.rows, 4);
        assert.equal(after.paused, true);
        assert.equal(after.top, before.top);
        assert.equal(after.left, before.left);
        assert.equal(after.href, before.href);
        assert.equal(
          requests.filter((r) => r.path === "factory/work-items").length,
          reads,
        );
        navigation.push({ width, before, after, extra_first_page_reads: 0 });
        const returned = await send("Page.captureScreenshot", {
          format: "png",
          captureBeyondViewport: false,
        });
        await fs.writeFile(
          path.join(evidence, `work-return-${width}.png`),
          Buffer.from(returned.data, "base64"),
        );
      }
      if (name === "launch") {
        assert(
          !(await evaluate(
            'Boolean(document.querySelector("input[type=password]"))',
          )),
          "Navigation prompted or launched automatically",
        );
        await evaluate(
          '[...document.querySelectorAll("button")].find(b=>b.textContent.includes("Review current authenticated")).focus()',
        );
        await send("Input.dispatchKeyEvent", {
          type: "keyDown",
          text: "\r",
          unmodifiedText: "\r",
          key: "Enter",
          code: "Enter",
          windowsVirtualKeyCode: 13,
        });
        await send("Input.dispatchKeyEvent", {
          type: "keyUp",
          key: "Enter",
          code: "Enter",
          windowsVirtualKeyCode: 13,
        });
        for (let i = 0; i < 20; i++) {
          if (
            await evaluate(
              'Boolean(document.querySelector("input[type=password]"))',
            )
          )
            break;
          await sleep(50);
        }
        const prompt = await evaluate(
          '({prompt:Boolean(document.querySelector("input[type=password]")),active:document.activeElement?.textContent,dialogs:[...document.querySelectorAll("[role=dialog]")].map(d=>d.textContent)})',
        );
        assert(
          prompt.prompt,
          `Keyboard launch review did not request operator authorization: ${JSON.stringify(prompt)}`,
        );
        keyboard.push({
          width,
          case: "offline launch review via Enter",
          token_prompt: true,
          launch: false,
        });
      }
      if (name === "native-codex") {
        assert(
          !(await evaluate(
            '[...document.querySelectorAll("[role=tab]")].some(b=>b.textContent.includes("Scope"))',
          )),
          "Codex exposed Claude scope resolver",
        );
        assert(!requests.some((r) => r.path === "config/resolved"));
      }
    }
  }
  assert.equal(errors.length, 0, "Browser runtime exceptions");
  assert.equal(requests.filter((r) => r.method !== "GET").length, 0);
  assert(
    !requests.some((r) =>
      /operations|native_surfaces|inbox|ack|claim/.test(r.path),
    ),
  );
  const head = execFileSync("git", ["rev-parse", "HEAD"], {
    encoding: "utf8",
  }).trim();
  await fs.writeFile(
    path.join(evidence, "browser.json"),
    JSON.stringify(
      {
        head,
        fixture_source: "eb31749bcae8f456d6df6709273afd5921d094ad",
        fixture_review: "59c8cc9855e1a98f7d28e16abef88171c7da69ca",
        manifest_sha256:
          "b17dea10bb7c2f9ac2047c35f5921b9adb0dacc85b71fdc700849913471d9706",
        observations,
        keyboard,
        navigation,
        retryConfirmations,
        requests,
        unknown,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      head,
      screenshots: observations.length + navigation.length,
      routeReturns: navigation.length,
      unknown,
      errors: errors.length,
    }),
  );
} finally {
  ws?.close();
  // Register before signalling; an already-exited process must not hang cleanup.
  if (chrome.exitCode === null && chrome.signalCode === null) {
    const exited = new Promise((resolve) => chrome.once("exit", resolve));
    chrome.kill();
    await exited;
  }
  await new Promise((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
  // Chrome helpers can briefly finish writes after the parent exits.
  await fs.rm(profile, {
    recursive: true,
    force: true,
    maxRetries: 10,
    retryDelay: 100,
  });
}
