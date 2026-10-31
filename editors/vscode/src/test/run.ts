// Downloads a pinned VS Code build (cached in .vscode-test/) and runs the
// extension-host suite in a throwaway workspace. Needs a display; CI uses
// xvfb-run. MAYLANG_VSCODE_VERSION overrides the pinned version.
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { runTests } from "@vscode/test-electron";

// The oldest version allowed by "engines" in package.json.
const VERSION = process.env.MAYLANG_VSCODE_VERSION || "1.82.0";

async function main(): Promise<void> {
  const root = path.resolve(__dirname, "../..");
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "maylang-vscode-"));
  const workspace = path.join(work, "workspace");
  fs.mkdirSync(path.join(workspace, ".vscode"), { recursive: true });
  fs.writeFileSync(path.join(workspace, "main.may"), 'print("hello");\n');
  fs.writeFileSync(
    path.join(workspace, ".vscode", "settings.json"),
    JSON.stringify({ "maylang.serverPath": path.join(root, "test-fixtures", "fake-maylsp") }, null, 2)
  );
  try {
    await runTests({
      version: VERSION,
      cachePath: path.join(root, ".vscode-test"),
      extensionDevelopmentPath: root,
      extensionTestsPath: path.join(__dirname, "suite"),
      extensionTestsEnv: { FAKE_MAYLSP_LOG: path.join(work, "server.log"), FAKE_MAYLSP_ROOT: root },
      launchArgs: [workspace, "--disable-extensions", "--disable-workspace-trust", "--user-data-dir", path.join(work, "user")],
    });
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

main().catch((error: unknown) => {
  console.error(error);
  process.exit(1);
});
