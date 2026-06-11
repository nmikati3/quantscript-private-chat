/**
 * Strips the SIP-protected `com.apple.macl` extended attribute from the
 * compiled release binary before Tauri's bundling/codesign phase.
 *
 * Background: macOS stamps `com.apple.macl` onto executables, and it cannot be
 * removed with `xattr -c` (SIP restores it immediately). codesign rejects any
 * bundled file carrying it ("resource fork, Finder information, or similar
 * detritus not allowed"). The only reliable workaround is to rewrite the file's
 * bytes into a brand-new inode, which carries no inherited xattrs.
 *
 * Runs as Tauri's `beforeBundleCommand`, whose cwd is the `frontend/` dir.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// `com.apple.macl` is a macOS/SIP-specific extended attribute; there is nothing
// to strip on Windows or Linux, so this step is a no-op off macOS.
if (os.platform() !== "darwin") {
  console.log("strip-build-xattrs: not macOS — skipping (no xattrs to strip).");
  process.exit(0);
}

const releaseDir = process.env.CARGO_TARGET_DIR
  ? path.join(process.env.CARGO_TARGET_DIR, "release")
  : path.join(__dirname, "../../src-tauri/target/release");

// The cargo binary is the one that reliably picks up `com.apple.macl`; the
// PyInstaller sidecar is regenerated fresh each build and signs fine.
const binaries = ["quantscript-desktop"];

function rewriteWithoutXattrs(filePath) {
  if (!fs.existsSync(filePath)) {
    console.warn(`strip-build-xattrs: skipping missing file ${filePath}`);
    return;
  }
  const data = fs.readFileSync(filePath);
  const { mode } = fs.statSync(filePath);
  const tmpPath = `${filePath}.macl-strip`;
  fs.writeFileSync(tmpPath, data);
  fs.chmodSync(tmpPath, mode);
  fs.renameSync(tmpPath, filePath);
  console.log(`strip-build-xattrs: rewrote ${filePath} (cleared inherited xattrs)`);
}

for (const name of binaries) {
  rewriteWithoutXattrs(path.join(releaseDir, name));
}
