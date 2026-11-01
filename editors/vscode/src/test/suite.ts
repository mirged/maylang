// Extension-host tests for the language server lifecycle. Each step changes a
// setting the way a user would and observes the extension's state and the
// fake server's log (test-fixtures/fake-maylsp).
import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import { commands, ConfigurationTarget, extensions, Uri, window, workspace } from "vscode";
import type { MaylangApi, ServerState } from "../extension";

interface Token {
  c: string;
  t: string;
}

/** TextMate tokens for a file, from the command VS Code's colorizer tests use. */
async function tokens(file: string, text: string): Promise<Token[]> {
  fs.writeFileSync(file, text);
  return (await commands.executeCommand<Token[]>("_workbench.captureSyntaxTokens", Uri.file(file))) ?? [];
}

function scopes(all: Token[], text: string): string {
  const token = all.find((t) => t.c.replace(/`/g, "").trim() === text);
  assert.ok(token, `token ${JSON.stringify(text)} in ${JSON.stringify(all)}`);
  return token.t;
}

interface Event {
  event: string;
  pid: number;
  strict?: boolean;
}

const LOG = process.env.FAKE_MAYLSP_LOG as string;
const FAKE = path.join(process.env.FAKE_MAYLSP_ROOT as string, "test-fixtures", "fake-maylsp");

function events(): Event[] {
  if (!fs.existsSync(LOG)) return [];
  return fs.readFileSync(LOG, "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line) as Event);
}

async function waitFor(what: string, predicate: () => boolean, timeout = 15000): Promise<void> {
  const deadline = Date.now() + timeout;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}; log: ${JSON.stringify(events())}`);
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
}

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function set(section: string, value: unknown): Promise<void> {
  await workspace.getConfiguration("maylang").update(section, value, ConfigurationTarget.Workspace);
}

async function settle(api: MaylangApi, state: ServerState, starts: number): Promise<void> {
  await waitFor(`state ${state} after ${starts} starts`, () => api.state() === state && api.starts() === starts);
  await api.settled();
  assert.strictEqual(api.state(), state);
}

async function step(name: string, body: () => Promise<void>): Promise<void> {
  await body();
  console.log(`PASS ${name}`);
}

export async function run(): Promise<void> {
  const extension = extensions.getExtension<MaylangApi>("maylang.maylang");
  assert.ok(extension, "extension maylang.maylang is installed");
  const folder = workspace.workspaceFolders?.[0];
  assert.ok(folder, "a workspace is open");
  const api = await extension.activate();

  await step("waits for a Maylang document before starting a server", async () => {
    // The Markdown preview activates the extension for fence highlighting.
    await new Promise((resolve) => setTimeout(resolve, 500));
    await api.settled();
    assert.strictEqual(api.starts(), 0);
    assert.strictEqual(api.state(), "stopped");
  });

  await step("highlights Maylang fences in the Markdown preview", async () => {
    const md = { options: { highlight: (code: string, lang: string) => `other:${lang}` } };
    api.extendMarkdownIt(md);
    const html = md.options.highlight('fun add(a: Int) -> Int { return a + 1; } // "x" <y>\nprint("${a}", nil);', "may");
    for (const expected of [
      '<span class="hljs-keyword">fun</span>',
      '<span class="hljs-title function_">add</span>',
      '<span class="hljs-type">Int</span>',
      '<span class="hljs-number">1</span>',
      '<span class="hljs-comment">// &quot;x&quot; &lt;y&gt;</span>',
      '<span class="hljs-built_in">print</span>',
      '<span class="hljs-string">&quot;${a}&quot;</span>',
      '<span class="hljs-literal">nil</span>',
    ]) {
      assert.ok(html.includes(expected), `${expected} in ${html}`);
    }
    assert.strictEqual(md.options.highlight("x", "maylang").startsWith("<div>"), true);
    assert.strictEqual(md.options.highlight("x", "js"), "other:js");
    // The built-in Markdown extension loads the plugin through its contribution.
    const rendered = await commands.executeCommand<string>("markdown.api.render", "```may\nfun go() -> Nil { return; }\n```\n");
    assert.ok(rendered.includes('<span class="hljs-keyword">fun</span>'), rendered);
  });

  await step("scopes doc comments and fenced Maylang in Markdown", async () => {
    const doc = await tokens(
      path.join(folder.uri.fsPath, "doc.may"),
      "/// Scale `amount`.\n///\n/// Returns: the product.\n// plain `y`\nfun scale(x: Int) -> Int { return x; }\n"
    );
    assert.match(scopes(doc, "amount"), /comment\.line\.documentation\.maylang.*markup\.inline\.raw\.string\.maylang/);
    assert.match(scopes(doc, "Returns"), /keyword\.other\.documentation\.maylang/);
    assert.match(scopes(doc, "// plain y"), /comment\.line\.double-slash\.maylang/);
    const markdown = await tokens(
      path.join(folder.uri.fsPath, "doc.md"),
      "# Title\n\n```may\nfun scale(x: Int) -> Int { return x; }\n```\n\n```maylang\nlet n: Int = 1;\n```\n"
    );
    assert.match(scopes(markdown, "scale"), /meta\.embedded\.block\.maylang.*entity\.name\.function\.maylang/);
    assert.match(scopes(markdown, "let"), /meta\.embedded\.block\.maylang/);
  });

  await window.showTextDocument(await workspace.openTextDocument(path.join(folder.uri.fsPath, "main.may")));

  await step("discovers the configured server and passes strict mode", async () => {
    await settle(api, "running", 1);
    const starts = events().filter((e) => e.event === "initialize");
    assert.strictEqual(starts.length, 1);
    assert.strictEqual(starts[0].strict, true);
  });

  await step("restarts with the new value when maylang.strict changes", async () => {
    const first = events()[0].pid;
    await set("strict", false);
    await settle(api, "running", 2);
    await waitFor("old server exit", () => !alive(first));
    const log = events();
    assert.deepStrictEqual(log.filter((e) => e.pid === first).map((e) => e.event), ["initialize", "shutdown", "exit"]);
    assert.strictEqual(log.filter((e) => e.event === "initialize").pop()?.strict, false);
  });

  await step("does not restart when only maylang.trace.server changes", async () => {
    await set("trace.server", "messages");
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await api.settled();
    assert.strictEqual(api.starts(), 2);
    assert.strictEqual(api.state(), "running");
  });

  await step("stops the old server and reports a missing explicit serverPath", async () => {
    const running = events().filter((e) => e.event === "initialize").pop()!.pid;
    await set("serverPath", "/nonexistent/maylang/maylsp");
    await waitFor("missing state", () => api.state() === "missing");
    await api.settled();
    assert.strictEqual(api.starts(), 2, "no process is spawned for a missing path");
    await waitFor("old server exit", () => !alive(running));
  });

  await step("reports a serverPath command that cannot be started", async () => {
    await set("serverPath", "maylsp-not-installed-for-tests");
    await settle(api, "failed", 3);
  });

  await step("starts again when serverPath is fixed", async () => {
    await set("serverPath", FAKE);
    await settle(api, "running", 4);
    assert.strictEqual(events().filter((e) => e.event === "initialize").length, 3);
  });

  await step("serializes rapid setting changes into one running server", async () => {
    await set("strict", true);
    await set("strict", false);
    await set("strict", true);
    await waitFor("three restarts", () => api.starts() === 7);
    await api.settled();
    assert.strictEqual(api.state(), "running");
    const live = events().filter((e) => e.event === "initialize").map((e) => e.pid).filter(alive);
    assert.strictEqual(live.length, 1, `exactly one server process remains: ${live}`);
  });

  await step("deactivate shuts the server down cleanly", async () => {
    const running = events().filter((e) => e.event === "initialize").pop()!.pid;
    // The extension host has already loaded this module; require returns it.
    const module = require(path.join(extension.extensionPath, "out", "extension.js")) as {
      deactivate(): Thenable<void>;
    };
    await module.deactivate();
    assert.strictEqual(api.state(), "stopped");
    await waitFor("server exit", () => !alive(running));
    assert.deepStrictEqual(events().filter((e) => e.pid === running).map((e) => e.event), ["initialize", "shutdown", "exit"]);
  });
}
