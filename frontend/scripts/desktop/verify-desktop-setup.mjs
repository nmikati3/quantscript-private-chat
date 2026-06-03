// Verifies the Tauri desktop configuration is sane before a build/release.
//
// Checks (fails the process with a non-zero exit code on any problem):
//   - tauri.conf.json exists and parses
//   - identifier / productName / version are set
//   - a restrictive CSP is present (no wildcard/unsafe script sources)
//   - the backend sidecar is wired up via externalBin
//   - the bundled backend resources are declared
//   - the capability set does not request obviously dangerous shell/fs perms
//
// Run via `npm run desktop:verify`.

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..", "..");
const tauriRoot = path.join(frontendRoot, "src-tauri");
const tauriConfPath = path.join(tauriRoot, "tauri.conf.json");
const capabilitiesPath = path.join(tauriRoot, "capabilities", "default.json");

const problems = [];
const checks = [];

function ok(message) {
  checks.push(`ok   ${message}`);
}

function fail(message) {
  problems.push(message);
}

async function readJson(filePath) {
  const raw = await fs.readFile(filePath, "utf8");
  return JSON.parse(raw);
}

async function verifyTauriConf() {
  let conf;
  try {
    conf = await readJson(tauriConfPath);
  } catch (error) {
    fail(`could not read/parse ${path.relative(frontendRoot, tauriConfPath)}: ${error.message}`);
    return;
  }
  ok("tauri.conf.json parses");

  if (!conf.identifier) fail("tauri.conf.json: missing `identifier`");
  else ok(`identifier = ${conf.identifier}`);

  if (!conf.productName) fail("tauri.conf.json: missing `productName`");
  else ok(`productName = ${conf.productName}`);

  if (!conf.version) fail("tauri.conf.json: missing `version`");
  else ok(`version = ${conf.version}`);

  const csp = conf?.app?.security?.csp;
  if (!csp || typeof csp !== "string") {
    fail("tauri.conf.json: missing `app.security.csp` (a CSP is required for the desktop webview)");
  } else {
    ok("CSP is present");
    const required = ["default-src 'self'", "object-src 'none'", "frame-src 'none'"];
    for (const directive of required) {
      if (!csp.includes(directive)) {
        fail(`CSP is missing required directive: ${directive}`);
      }
    }
    // Guard against the two most common ways to neuter a CSP.
    if (/script-src[^;]*'unsafe-inline'/.test(csp)) {
      fail("CSP allows 'unsafe-inline' in script-src — scripts must not be inline-executable");
    }
    if (/script-src[^;]*\*/.test(csp)) {
      fail("CSP allows a wildcard (*) script source");
    }
  }

  const externalBin = conf?.bundle?.externalBin ?? [];
  if (!externalBin.some((entry) => entry.includes("quantscript-backend"))) {
    fail("tauri.conf.json: `bundle.externalBin` does not reference the quantscript-backend sidecar");
  } else {
    ok("backend sidecar declared in externalBin");
  }

  const resources = conf?.bundle?.resources ?? [];
  if (!resources.some((entry) => entry.includes("resources/backend"))) {
    fail("tauri.conf.json: `bundle.resources` does not include resources/backend");
  } else {
    ok("backend resources declared in bundle.resources");
  }
}

async function verifyCapabilities() {
  let caps;
  try {
    caps = await readJson(capabilitiesPath);
  } catch (error) {
    fail(`could not read/parse ${path.relative(frontendRoot, capabilitiesPath)}: ${error.message}`);
    return;
  }
  ok("capabilities/default.json parses");

  const permissions = caps.permissions ?? [];
  // These permission namespaces would let the webview run arbitrary commands or
  // read arbitrary files — they should never be granted in this local-only app.
  const dangerous = ["shell:allow-execute", "shell:default", "fs:allow-read", "fs:default"];
  for (const perm of permissions) {
    const name = typeof perm === "string" ? perm : perm?.identifier;
    if (name && dangerous.includes(name)) {
      fail(`capabilities grant a dangerous permission: ${name}`);
    }
  }
  ok(`capabilities permissions reviewed (${permissions.length} declared)`);
}

async function main() {
  await verifyTauriConf();
  await verifyCapabilities();

  for (const line of checks) console.log(line);

  if (problems.length > 0) {
    console.error("\nDesktop configuration verification FAILED:");
    for (const problem of problems) console.error(`  - ${problem}`);
    process.exitCode = 1;
    return;
  }
  console.log("\nDesktop configuration verification passed.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
