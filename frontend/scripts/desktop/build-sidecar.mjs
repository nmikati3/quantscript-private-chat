import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import os from "node:os";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..", "..");
const repoRoot = path.resolve(frontendRoot, "..");
const binariesDir = path.join(frontendRoot, "src-tauri", "binaries");
const specFile = path.join(__dirname, "quantscript-backend.spec");
const backendDir = path.join(repoRoot, "backend");

function detectTriple() {
  const arch = os.arch();
  const plat = os.platform();
  const archMap = { arm64: "aarch64", x64: "x86_64" };
  const a = archMap[arch] || arch;
  if (plat === "darwin") return `${a}-apple-darwin`;
  if (plat === "win32") return `${a}-pc-windows-msvc`;
  return `${a}-unknown-linux-gnu`;
}

function systemPython() {
  return os.platform() === "win32" ? "python" : "python3";
}

function venvPython() {
  const bin = os.platform() === "win32" ? "Scripts" : "bin";
  return path.join(backendDir, "venv", bin, os.platform() === "win32" ? "python.exe" : "python3");
}

function run(command, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: "inherit", ...opts });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} exited with code ${code}`));
    });
  });
}

async function exists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function ensureVenv() {
  const venv = venvPython();
  if (await exists(venv)) {
    console.log(`Using existing venv: ${path.dirname(path.dirname(venv))}`);
    return venv;
  }
  console.log("Creating backend venv...");
  await run(systemPython(), ["-m", "venv", path.join(backendDir, "venv")]);
  return venv;
}

// Pin PyInstaller so release builds are reproducible. Bump deliberately.
const PYINSTALLER_VERSION = "6.20.0";

async function ensurePyInstaller(python) {
  console.log(`Ensuring PyInstaller==${PYINSTALLER_VERSION}...`);
  await run(python, ["-m", "pip", "install", `pyinstaller==${PYINSTALLER_VERSION}`]);
}

async function ensureBackendDeps(python) {
  const reqLockFile = path.join(backendDir, "requirements.lock");

  // requirements.lock is the single source of truth for builds and CI.
  // Intentionally do NOT also install requirements.txt here: a second,
  // looser install can silently drift the bundled runtime away from the lock.
  if (await exists(reqLockFile)) {
    console.log("Installing pinned dependencies from requirements.lock...");
    await run(python, ["-m", "pip", "install", "-r", reqLockFile]);
  } else {
    throw new Error(`requirements.lock not found at ${reqLockFile}`);
  }
}

async function main() {
  const targetArg = process.argv.find((a) => a.startsWith("--target="));
  const triple = targetArg ? targetArg.replace("--target=", "") : detectTriple();
  const outputName = `quantscript-backend-${triple}`;
  const python = await ensureVenv();

  console.log(`Building sidecar for ${triple} (python: ${python})...`);

  await ensurePyInstaller(python);
  await ensureBackendDeps(python);

  const distDir = path.join(frontendRoot, "dist-pyinstaller");

  await run(python, ["-m", "PyInstaller", "--noconfirm", "--distpath", distDir, specFile], {
    cwd: repoRoot,
    env: { ...process.env, QUANTSCRIPT_OUTPUT_NAME: outputName },
  });

  const ext = triple.includes("windows") ? ".exe" : "";
  const builtBinary = path.join(distDir, outputName + ext);
  const destBinary = path.join(binariesDir, outputName + ext);

  await fs.mkdir(binariesDir, { recursive: true });
  await fs.copyFile(builtBinary, destBinary);

  if (os.platform() !== "win32") {
    await fs.chmod(destBinary, 0o755);
  }

  console.log(`Sidecar binary ready: ${destBinary}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
