import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..", "..");
const repoRoot = path.resolve(frontendRoot, "..");
const backendRoot = path.join(repoRoot, "backend");
const resourcesRoot = path.join(frontendRoot, "src-tauri", "resources");
const bundledBackendRoot = path.join(resourcesRoot, "backend");

// Explicit allowlist: only copy runtime backend sources needed by the sidecar.
const allowedPaths = [
  "app",
];

// Hard denylist for accidental secret/data leaks.
const blockedPathSubstrings = [
  `${path.sep}data${path.sep}`,
  `${path.sep}.git${path.sep}`,
];

const blockedFileNames = new Set([
  ".env",
  ".env.local",
  ".env.development",
  ".env.production",
]);

const blockedExtensions = new Set([
  ".pem",
  ".key",
  ".p12",
  ".crt",
  ".sqlite",
  ".sqlite3",
  ".db",
  ".log",
]);

// Build artifacts / OS cruft that must never ship inside the app bundle.
// Crucially, compiled .pyc files embed absolute build paths (co_filename),
// which would leak the build machine's username and directory layout to every
// user. These are silently skipped during copy rather than treated as errors.
const ignoredDirNames = new Set(["__pycache__"]);
const ignoredFileNames = new Set([".DS_Store"]);
const ignoredExtensions = new Set([".pyc", ".pyo"]);

function shouldIgnoreEntry(entry) {
  if (entry.isDirectory()) {
    return ignoredDirNames.has(entry.name);
  }
  if (ignoredFileNames.has(entry.name)) {
    return true;
  }
  return ignoredExtensions.has(path.extname(entry.name).toLowerCase());
}

async function exists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

function assertSafeRelativePath(relPath) {
  const normalized = relPath.replaceAll("\\", path.sep);
  const base = path.basename(normalized);
  const ext = path.extname(base).toLowerCase();

  if (blockedFileNames.has(base)) {
    throw new Error(`Blocked sensitive file name while bundling backend: ${relPath}`);
  }
  if (blockedExtensions.has(ext)) {
    throw new Error(`Blocked sensitive file extension while bundling backend: ${relPath}`);
  }
  for (const blockedSubstring of blockedPathSubstrings) {
    if (normalized.includes(blockedSubstring)) {
      throw new Error(`Blocked sensitive backend path while bundling: ${relPath}`);
    }
  }
}

async function copyAllowedPath(relPath) {
  const sourcePath = path.join(backendRoot, relPath);
  const destPath = path.join(bundledBackendRoot, relPath);
  const srcStat = await fs.stat(sourcePath);

  if (srcStat.isDirectory()) {
    await fs.mkdir(destPath, { recursive: true });
    const entries = await fs.readdir(sourcePath, { withFileTypes: true });
    for (const entry of entries) {
      if (shouldIgnoreEntry(entry)) {
        continue;
      }
      const childRelPath = path.join(relPath, entry.name);
      assertSafeRelativePath(childRelPath);
      await copyAllowedPath(childRelPath);
    }
    return;
  }

  await fs.mkdir(path.dirname(destPath), { recursive: true });
  await fs.copyFile(sourcePath, destPath);
}

async function scanBundledTreeForSensitiveFiles(root) {
  const entries = await fs.readdir(root, { withFileTypes: true });
  for (const entry of entries) {
    const absPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      await scanBundledTreeForSensitiveFiles(absPath);
      continue;
    }
    const relPath = path.relative(bundledBackendRoot, absPath);
    assertSafeRelativePath(relPath);
    if (ignoredFileNames.has(entry.name) || ignoredExtensions.has(path.extname(entry.name).toLowerCase())) {
      throw new Error(`Build artifact leaked into bundle (embeds local paths): ${relPath}`);
    }
  }
}

// Express a path relative to the repo root with forward slashes, so the
// manifest never leaks an absolute home-directory path into the bundled app.
function repoRelative(absPath) {
  return path.relative(repoRoot, absPath).split(path.sep).join("/");
}

// Ship the project license and third-party attribution inside the app bundle
// so the distributed binary carries its legal notices (Apache-2.0 §4).
async function copyLegalFiles() {
  for (const name of ["LICENSE", "NOTICE"]) {
    const sourcePath = path.join(repoRoot, name);
    if (!(await exists(sourcePath))) {
      throw new Error(`Required legal file not found: ${sourcePath}`);
    }
    await fs.mkdir(resourcesRoot, { recursive: true });
    await fs.copyFile(sourcePath, path.join(resourcesRoot, name));
  }
}

async function writeManifest() {
  const manifestPath = path.join(resourcesRoot, "backend-manifest.json");
  const manifest = {
    generatedAt: new Date().toISOString(),
    source: repoRelative(backendRoot),
    target: repoRelative(bundledBackendRoot),
  };
  await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2), "utf8");
}

async function main() {
  if (!(await exists(backendRoot))) {
    throw new Error(`Backend directory not found: ${backendRoot}`);
  }
  await fs.rm(bundledBackendRoot, { recursive: true, force: true });
  for (const relPath of allowedPaths) {
    assertSafeRelativePath(relPath);
    await copyAllowedPath(relPath);
  }
  await scanBundledTreeForSensitiveFiles(bundledBackendRoot);
  await copyLegalFiles();
  await writeManifest();
  console.log(`Bundled backend resources into ${bundledBackendRoot}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
