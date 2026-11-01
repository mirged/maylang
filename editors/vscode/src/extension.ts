import * as fs from "fs";
import * as path from "path";
import {
  ConfigurationChangeEvent,
  ExtensionContext,
  TextDocument,
  window,
  workspace,
} from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";
import { extendMarkdownIt, loadVocabulary, MarkdownIt } from "./highlight";

/**
 * Language server lifecycle:
 *
 * - `maylang.serverPath` (default `maylsp`, found on PATH) is read each time
 *   the server starts. An explicit path that does not exist shows a warning
 *   and the server is not started ("missing"); a command that cannot be run
 *   shows an error ("failed").
 * - Changing `maylang.serverPath` or `maylang.strict` stops the running
 *   server and starts a new one with the new settings. `maylang.trace.server`
 *   applies without a restart.
 * - Starts, restarts and stops run one at a time, in order, so rapid setting
 *   changes cannot leave two servers running.
 * - The Markdown preview also activates the extension (for its Maylang fence
 *   highlighting); the server then waits until a Maylang document is open.
 */
export type ServerState = "starting" | "running" | "missing" | "failed" | "stopped";

/** Returned from `activate` for tests and other extensions. */
export interface MaylangApi {
  state(): ServerState;
  /** Resolves once every queued start, restart or stop has finished. */
  settled(): Promise<void>;
  /** How many times a server process has been started. */
  starts(): number;
  /** markdown-it plugin used by the Markdown preview. */
  extendMarkdownIt<T extends MarkdownIt>(md: T): T;
}

const RESTART_SETTINGS = ["maylang.serverPath", "maylang.strict"];

let client: LanguageClient | undefined;
let state: ServerState = "stopped";
let starts = 0;
let queue: Promise<void> = Promise.resolve();

function serverCommand(): string {
  const configured = workspace
    .getConfiguration("maylang")
    .get<string>("serverPath", "maylsp");
  return configured && configured.length > 0 ? configured : "maylsp";
}

function enqueue(step: () => Promise<void>): Promise<void> {
  queue = queue.then(step, step);
  return queue;
}

async function start(): Promise<void> {
  const command = serverCommand();
  if ((command.includes("/") || command.includes(path.sep)) && !fs.existsSync(command)) {
    state = "missing";
    void window.showWarningMessage(
      `Maylang: language server not found at "${command}". ` +
        `Build tools/maylsp with the self-hosted mayc compiler or set "maylang.serverPath".`
    );
    return;
  }

  const serverOptions: ServerOptions = {
    run: { command, transport: TransportKind.stdio },
    debug: { command, transport: TransportKind.stdio },
  };
  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ scheme: "file", language: "maylang" }],
    initializationOptions: {
      strict: workspace.getConfiguration("maylang").get<boolean>("strict", true),
    },
    synchronize: {
      configurationSection: "maylang",
      fileEvents: workspace.createFileSystemWatcher("**/*.may"),
    },
  };

  const next = new LanguageClient("maylang", "Maylang Language Server", serverOptions, clientOptions);
  client = next;
  state = "starting";
  starts++;
  try {
    await next.start();
    state = "running";
  } catch (error: unknown) {
    client = undefined;
    state = "failed";
    await next.dispose().catch(() => undefined);
    void window.showErrorMessage(
      `Maylang: could not start language server "${command}". ` +
        `Install the toolchain and add its bin directory to PATH, or set "maylang.serverPath" to maylsp's full path. ` +
        String(error)
    );
  }
}

async function stop(): Promise<void> {
  const current = client;
  client = undefined;
  if (current) {
    await current.stop().catch(() => undefined);
    await current.dispose().catch(() => undefined);
  }
  state = "stopped";
}

export function activate(context: ExtensionContext): MaylangApi {
  const vocabulary = loadVocabulary(context.asAbsolutePath("syntaxes/maylang.tmLanguage.json"));
  let wanted = false;
  const want = (document: TextDocument): void => {
    if (!wanted && document.languageId === "maylang") {
      wanted = true;
      void enqueue(start);
    }
  };
  context.subscriptions.push(workspace.onDidOpenTextDocument(want));
  context.subscriptions.push(
    workspace.onDidChangeConfiguration((event: ConfigurationChangeEvent) => {
      if (wanted && RESTART_SETTINGS.some((section) => event.affectsConfiguration(section))) {
        void enqueue(async () => {
          await stop();
          await start();
        });
      }
    })
  );
  workspace.textDocuments.forEach(want);
  return {
    state: () => state,
    settled: () => queue,
    starts: () => starts,
    extendMarkdownIt: (md) => extendMarkdownIt(md, vocabulary),
  };
}

export function deactivate(): Thenable<void> {
  return enqueue(stop);
}
