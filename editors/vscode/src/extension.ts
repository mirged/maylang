import * as fs from "fs";
import * as path from "path";
import {
  ExtensionContext,
  window,
  workspace,
} from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

function serverCommand(): string {
  const configured = workspace
    .getConfiguration("maylang")
    .get<string>("serverPath", "maylsp");
  return configured && configured.length > 0 ? configured : "maylsp";
}

export function activate(context: ExtensionContext): void {
  const command = serverCommand();

  // If an explicit path is configured but missing, warn early.
  if (command.includes(path.sep) && !fs.existsSync(command)) {
    window.showWarningMessage(
      `Maylang: language server not found at "${command}". ` +
        `Build toolchain/maylsp with the self-hosted mayc compiler or set "maylang.serverPath".`
    );
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

  client = new LanguageClient(
    "maylang",
    "Maylang Language Server",
    serverOptions,
    clientOptions
  );

  client.start();
}

export function deactivate(): Thenable<void> | undefined {
  return client ? client.stop() : undefined;
}
