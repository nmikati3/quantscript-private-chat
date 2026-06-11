/**
 * Cross-platform `tauri build` orchestrator.
 *
 * Replaces the macOS-only shell one-liner that previously lived in the
 * `tauri:build` npm script. Doing the orchestration in Node means the exact
 * same release pipeline runs on macOS, Windows and Linux without depending on
 * a POSIX shell, the `env` command, or `$HOME` expansion:
 *
 *   1. verify the desktop configuration         (verify-desktop-setup.mjs)
 *   2. clear stale DMGs                          (clean-dmg-artifacts.mjs; no-op off macOS)
 *   3. scrub the build machine's home path from the compiled binary (RUSTFLAGS)
 *   4. run `tauri build` for the platform's bundle targets
 *   5. enforce the release privacy scan          (privacy-scan.mjs)
 *
 * Bundle targets default per platform (override with `--bundles=...`):
 *   macOS   -> app,dmg
 *   Windows -> nsis        (one-click installer .exe; WebView2 auto-installs)
 *   Linux   -> deb,appimage
 *
 * Flags:
 *   --bundles=<list>   comma-separated Tauri bundle targets
 *   --fancy-dmg        macOS only: build the AppleScript DMG layout (CI unset)
 * Any other args are passed straight through to `tauri build`.
 */
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..", "..");
const require = createRequire(import.meta.url);

const DEFAULT_BUNDLES = {
  darwin: "app,dmg",
  win32: "nsis",
  linux: "deb,appimage",
};

const platform = os.platform();

let bundles = DEFAULT_BUNDLES[platform] || "app";
let fancyDmg = false;
const passthrough = [];
for (const arg of process.argv.slice(2)) {
  if (arg.startsWith("--bundles=")) {
    bundles = arg.slice("--bundles=".length);
  } else if (arg === "--fancy-dmg") {
    fancyDmg = true;
  } else {
    passthrough.push(arg);
  }
}

function runNodeScript(scriptName) {
  const res = spawnSync(process.execPath, [path.join("scripts", "desktop", scriptName)], {
    cwd: frontendRoot,
    stdio: "inherit",
  });
  if (res.status !== 0) {
    process.exit(res.status ?? 1);
  }
}

async function main() {
  // 1 & 2: pre-build checks / cleanup.
  runNodeScript("verify-desktop-setup.mjs");
  runNodeScript("clean-dmg-artifacts.mjs");

  // 3: privacy — strip the build machine's home directory from any path the
  // Rust compiler would otherwise bake into the binary. `--remap-path-prefix`
  // works the same on every platform; os.homedir() yields the right root.
  const home = os.homedir();
  const remap = `--remap-path-prefix=${home}=`;
  process.env.RUSTFLAGS = [process.env.RUSTFLAGS, remap].filter(Boolean).join(" ");

  // `CI=true` makes Tauri's macOS DMG step use the simple, headless-friendly
  // layout instead of the flaky Finder/AppleScript one. `--fancy-dmg` opts out
  // for a polished local DMG. Harmless on Windows/Linux.
  if (fancyDmg) {
    delete process.env.CI;
  } else {
    process.env.CI = "true";
  }

  // 4: build via the Tauri CLI's Node API (no shell, so no cross-platform
  // quoting pitfalls). `run` rejects on a non-zero CLI exit.
  const { run } = require(path.join(frontendRoot, "node_modules", "@tauri-apps", "cli"));
  const buildArgs = ["build", "--bundles", bundles, ...passthrough];
  console.log(`> tauri ${buildArgs.join(" ")} (platform=${platform}, CI=${process.env.CI ?? "unset"})`);
  await run(buildArgs, "tauri");

  // 5: enforce the release privacy scan on the produced artifacts.
  runNodeScript("privacy-scan.mjs");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
