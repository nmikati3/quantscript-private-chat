import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..", "..");
const repoRoot = path.resolve(frontendRoot, "..");

// Our own artifacts — scanned in full. This is where QuantScript's code, the
// PyInstaller backend sidecar, and the bundled backend sources live, and it is
// scanned *before* the OS bundlers vendor any third-party content, so it is the
// authoritative privacy boundary for everything we ship.
const ownScanRoots = [
  "dist",
  "src-tauri/binaries",
  "src-tauri/resources",
];

// Packaged bundle outputs — scanned too, but with OS/toolchain-vendored content
// excluded (see `isVendoredOrPackaged`). The app binary, sidecar, and backend
// sources here are byte-for-byte the same files already scanned in full above;
// what's *new* in these dirs is third-party material the bundlers pull in
// (e.g. linuxdeploy copies the GTK/glib/GnuTLS stack into the AppImage), which
// is not ours to audit and legitimately contains upstream build paths and TLS
// test-vector keys.
const bundleScanRoots = [
  // macOS
  "src-tauri/target/release/bundle/macos",
  "src-tauri/target/release/bundle/dmg",
  // Windows
  "src-tauri/target/release/bundle/nsis",
  "src-tauri/target/release/bundle/msi",
  // Linux
  "src-tauri/target/release/bundle/deb",
  "src-tauri/target/release/bundle/appimage",
];

// Within bundle outputs only: shared libraries vendored by the OS toolchain and
// the opaque packaged containers themselves. Their contents are either
// already-scanned app files or third-party libraries, so scanning them yields
// only false positives. NOTE: these skips apply *only* to bundle roots — our
// own Windows sidecar (`binaries/*.exe`) is always scanned in full.
const vendoredLibPattern = /\.(so|dylib|dll)(\.\d+)*$/i;
const packagedArtifactPattern = /\.(appimage|deb|rpm|dmg|msi|exe)$/i;

function isVendoredOrPackaged(filePath) {
  const base = path.basename(filePath);
  return vendoredLibPattern.test(base) || packagedArtifactPattern.test(base);
}

const blockedFileNames = new Set([
  ".DS_Store",
  ".env",
  ".env.local",
  ".env.development",
  ".env.production",
]);

const blockedDirNames = new Set([
  "__pycache__",
]);

const blockedExtensions = new Set([
  ".db",
  ".key",
  ".log",
  ".p12",
  ".p8",
  ".pem",
  ".pyc",
  ".pyo",
  ".sqlite",
  ".sqlite3",
]);

const secretPatterns = [
  [/-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/g, "private key block"],
  [/\bsk-[A-Za-z0-9_-]{20,}\b/g, "OpenAI-style API key"],
  [/\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9_]{20,}\b/g, "GitHub token"],
  [/\bgithub_pat_[A-Za-z0-9_]{20,}\b/g, "GitHub fine-grained token"],
  [/\bhf_[A-Za-z0-9]{20,}\b/g, "Hugging Face token"],
  [/\bAKIA[0-9A-Z]{16}\b/g, "AWS access key"],
  [/\bxox[baprs]-[A-Za-z0-9-]{20,}\b/g, "Slack token"],
  [/\bAIza[0-9A-Za-z_-]{20,}\b/g, "Google API key"],
];

// Home-directory path shapes for each desktop OS. A release artifact must never
// embed the build machine's home path (it would leak a username/layout to every
// downloader), so we hunt for all three regardless of which OS runs the scan.
const userPathPatterns = [
  /\/Users\/[A-Za-z0-9_.-]+/g, // macOS
  /\/home\/[A-Za-z0-9_.-]+/g, // Linux
  /[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+/g, // Windows
];

function parseAllowedUserRoots() {
  const raw = process.env.QUANTSCRIPT_ALLOWED_EMBEDDED_USER_ROOTS || "";
  const roots = raw
    // Allow either delimiter so a Windows-style ';' list and a POSIX ':' list
    // both parse, without splitting a "C:\..." drive letter.
    .split(/[;\n]/)
    .flatMap((item) => item.split(path.delimiter))
    .map((item) => item.trim())
    .filter(Boolean);

  if (process.env.GITHUB_ACTIONS === "true") {
    // GitHub-hosted runner home directories, per platform.
    roots.push("/Users/runner"); // macOS
    roots.push("/home/runner"); // Linux
    roots.push("C:\\Users\\runneradmin"); // Windows
    roots.push("C:\\Users\\runner"); // Windows (fallback)
  }

  return new Set(roots);
}

const allowedUserRoots = parseAllowedUserRoots();
const problems = [];

function repoRelative(absPath) {
  return path.relative(repoRoot, absPath).split(path.sep).join("/");
}

function redact(value) {
  return value
    .replaceAll(process.env.HOME || "\0", "<HOME>")
    .replaceAll(process.env.USERPROFILE || "\0", "<HOME>")
    .replace(/\/Users\/[A-Za-z0-9_.-]+/g, "/Users/<user>")
    .replace(/\/home\/[A-Za-z0-9_.-]+/g, "/home/<user>")
    .replace(/([A-Za-z]:\\Users\\)[A-Za-z0-9_.-]+/g, "$1<user>")
    .replace(/(sk-|ghp_|gho_|ghu_|ghs_|github_pat_|hf_)[A-Za-z0-9_-]+/g, "$1<redacted>")
    .slice(0, 240);
}

function record(filePath, message, sample = "") {
  problems.push({
    file: repoRelative(filePath),
    message,
    sample: sample ? redact(sample) : "",
  });
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function* walk(root) {
  const entries = await fs.readdir(root, { withFileTypes: true });
  for (const entry of entries) {
    const absPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      if (blockedDirNames.has(entry.name)) {
        record(absPath, `blocked generated directory: ${entry.name}`);
        continue;
      }
      // `*.AppDir` is linuxdeploy's intermediate staging tree for the AppImage:
      // it is full of vendored OS libraries and icon themes, while the only
      // QuantScript files in it duplicate `resources/` (already scanned) and
      // the path-scrubbed Rust binary. Skip it to avoid auditing third-party
      // content we don't control.
      if (entry.name.endsWith(".AppDir")) {
        continue;
      }
      yield* walk(absPath);
      continue;
    }
    if (entry.isFile()) {
      yield absPath;
    }
  }
}

function checkPath(filePath) {
  const base = path.basename(filePath);
  const ext = path.extname(base).toLowerCase();

  if (blockedFileNames.has(base)) {
    record(filePath, `blocked sensitive/generated file name: ${base}`);
  }
  if (blockedExtensions.has(ext)) {
    record(filePath, `blocked sensitive/generated file extension: ${ext}`);
  }
}

function checkEmbeddedUsers(filePath, text) {
  for (const pattern of userPathPatterns) {
    pattern.lastIndex = 0;
    for (const match of text.matchAll(pattern)) {
      const root = match[0];
      if (!allowedUserRoots.has(root)) {
        record(filePath, `embedded local home-directory path: ${root}`, text.slice(match.index, match.index + 180));
      }
    }
  }
}

function checkSecrets(filePath, text) {
  for (const [pattern, label] of secretPatterns) {
    pattern.lastIndex = 0;
    for (const match of text.matchAll(pattern)) {
      record(filePath, `embedded ${label}`, text.slice(match.index, match.index + 180));
    }
  }
}

function readPngChunks(buffer) {
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  if (buffer.length < signature.length || !buffer.subarray(0, signature.length).equals(signature)) {
    return [];
  }

  const chunks = [];
  let offset = signature.length;
  while (offset + 12 <= buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.subarray(offset + 4, offset + 8).toString("ascii");
    const dataStart = offset + 8;
    const dataEnd = dataStart + length;
    if (dataEnd + 4 > buffer.length) break;
    chunks.push({ type, data: buffer.subarray(dataStart, dataEnd) });
    offset = dataEnd + 4;
  }
  return chunks;
}

function checkPngMetadata(filePath, buffer) {
  // iTXt/tEXt/zTXt carry text (incl. XMP); eXIf carries raw EXIF/TIFF — all can
  // embed authoring tool, account IDs, GPS, or device info and must be stripped.
  const metadataChunkTypes = new Set(["iTXt", "tEXt", "zTXt", "eXIf"]);
  for (const chunk of readPngChunks(buffer)) {
    if (!metadataChunkTypes.has(chunk.type)) continue;
    const sample = chunk.data.toString("utf8");
    record(filePath, `PNG metadata must be stripped: ${chunk.type}`, sample);
  }
}

async function scanFile(filePath) {
  checkPath(filePath);

  const buffer = await fs.readFile(filePath);
  const text = buffer.toString("utf8");
  checkEmbeddedUsers(filePath, text);
  checkSecrets(filePath, text);

  if (path.extname(filePath).toLowerCase() === ".png") {
    checkPngMetadata(filePath, buffer);
  }
}

async function scanRoot(relRoot, { skipVendored }) {
  const absRoot = path.join(frontendRoot, relRoot);
  if (!(await exists(absRoot))) {
    return;
  }
  const stat = await fs.stat(absRoot);
  if (stat.isFile()) {
    await scanFile(absRoot);
    return;
  }
  for await (const filePath of walk(absRoot)) {
    if (skipVendored && isVendoredOrPackaged(filePath)) {
      continue;
    }
    await scanFile(filePath);
  }
}

async function main() {
  for (const relRoot of ownScanRoots) {
    await scanRoot(relRoot, { skipVendored: false });
  }
  for (const relRoot of bundleScanRoots) {
    await scanRoot(relRoot, { skipVendored: true });
  }

  if (problems.length > 0) {
    console.error("Desktop privacy scan FAILED:");
    for (const problem of problems) {
      console.error(`  - ${problem.file}: ${problem.message}`);
      if (problem.sample) {
        console.error(`    sample: ${problem.sample}`);
      }
    }
    process.exitCode = 1;
    return;
  }

  console.log("Desktop privacy scan passed.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
