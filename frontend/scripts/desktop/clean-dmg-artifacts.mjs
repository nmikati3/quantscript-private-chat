/**
 * Removes stale .dmg files under target/release/bundle/{macos,dmg}.
 * Leftovers cause `hdiutil: convert failed - File exists` when bundling.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const targetRoot = process.env.CARGO_TARGET_DIR
  ? path.join(process.env.CARGO_TARGET_DIR, "release/bundle")
  : path.join(__dirname, "../../src-tauri/target/release/bundle");

for (const sub of ["macos", "dmg"]) {
  const dir = path.join(targetRoot, sub);
  if (!fs.existsSync(dir)) continue;
  for (const name of fs.readdirSync(dir)) {
    if (!name.endsWith(".dmg")) continue;
    try {
      fs.unlinkSync(path.join(dir, name));
    } catch {
      /* ignore */
    }
  }
}
