#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::fs;
use serde::Serialize;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, State};

fn generate_sidecar_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::fill(&mut buf).expect("failed to generate random bytes for sidecar token");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

#[derive(Serialize)]
struct DesktopRuntimeInfo {
    is_desktop: bool,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct BackendRuntimeInfo {
    api_base_url: String,
    pid: u32,
    port: u16,
    sidecar_token: String,
}

struct ManagedBackend {
    child: Child,
    info: BackendRuntimeInfo,
}

struct BackendState {
    process: Mutex<Option<ManagedBackend>>,
}

struct AllowedPaths {
    set: Mutex<std::collections::HashSet<String>>,
}

const MAX_READABLE_FILE_SIZE: u64 = 100 * 1024 * 1024; // 100 MB
const MIN_EPHEMERAL_PORT: u16 = 49152;
const MAX_EPHEMERAL_PORT: u16 = 65535;
const STARTUP_PORT_ATTEMPTS: usize = 8;

#[tauri::command]
fn get_desktop_runtime_info() -> DesktopRuntimeInfo {
    DesktopRuntimeInfo { is_desktop: true }
}

fn random_ephemeral_port() -> Result<u16, String> {
    let mut bytes = [0u8; 2];
    getrandom::fill(&mut bytes).map_err(|e| e.to_string())?;
    let n = u16::from_be_bytes(bytes);
    let span = MAX_EPHEMERAL_PORT - MIN_EPHEMERAL_PORT + 1;
    Ok(MIN_EPHEMERAL_PORT + (n % span))
}

fn startup_probe_proof(sidecar_token: &str, nonce: &str) -> Result<String, String> {
    let mut mac =
        Hmac::<Sha256>::new_from_slice(sidecar_token.as_bytes()).map_err(|e| e.to_string())?;
    mac.update(nonce.as_bytes());
    Ok(hex::encode(mac.finalize().into_bytes()))
}

fn startup_status_reachable(addr: SocketAddr, sidecar_token: &str) -> bool {
    let mut nonce_bytes = [0u8; 16];
    if getrandom::fill(&mut nonce_bytes).is_err() {
        return false;
    }
    let nonce = hex::encode(nonce_bytes);
    let expected_proof = match startup_probe_proof(sidecar_token, &nonce) {
        Ok(proof) => proof,
        Err(_) => return false,
    };

    let mut stream = match TcpStream::connect_timeout(&addr, Duration::from_millis(250)) {
        Ok(stream) => stream,
        Err(_) => return false,
    };

    let _ = stream.set_read_timeout(Some(Duration::from_millis(250)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(250)));

    if stream
        .write_all(format!(
            "GET /startup_status_probe HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Startup-Nonce: {nonce}\r\nConnection: close\r\n\r\n"
        ).as_bytes())
        .is_err()
    {
        return false;
    }

    let mut response_bytes = Vec::with_capacity(512);
    if stream.read_to_end(&mut response_bytes).is_err() {
        return false;
    }
    let response = String::from_utf8_lossy(&response_bytes);
    if !(response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")) {
        return false;
    }
    let Some((_, body)) = response.split_once("\r\n\r\n") else {
        return false;
    };
    body.trim() == expected_proof
}

/// Dev-only: locate the backend source tree relative to this crate.
///
/// This uses `env!("CARGO_MANIFEST_DIR")`, which bakes the absolute build-time
/// path (and thus the build machine's username/layout) into the binary as a
/// string literal — something `--remap-path-prefix` cannot scrub. It is
/// therefore compiled ONLY in debug builds and never ships in the release app,
/// which always launches the bundled sidecar instead.
#[cfg(debug_assertions)]
fn backend_root_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("backend")
}

/// Backend directory used to augment `PATH` with a bundled venv, if present.
///
/// In release builds this is only ever the bundled resource directory; the
/// dev-source fallback (which embeds a build path) is compiled out so the
/// shipped binary never references it.
fn resolved_backend_dir(app: &AppHandle) -> Option<PathBuf> {
    if let Some(dir) = bundled_backend_dir(app) {
        return Some(dir);
    }
    #[cfg(debug_assertions)]
    {
        Some(backend_root_dir())
    }
    #[cfg(not(debug_assertions))]
    {
        None
    }
}

fn bundled_backend_dir(app: &AppHandle) -> Option<PathBuf> {
    app.path()
        .resolve("backend", tauri::path::BaseDirectory::Resource)
        .ok()
        .filter(|path| path.exists())
}

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
fn target_triple() -> Option<&'static str> {
    Some("aarch64-apple-darwin")
}

#[cfg(all(target_os = "macos", target_arch = "x86_64"))]
fn target_triple() -> Option<&'static str> {
    Some("x86_64-apple-darwin")
}

#[cfg(all(target_os = "windows", target_arch = "x86_64"))]
fn target_triple() -> Option<&'static str> {
    Some("x86_64-pc-windows-msvc")
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn target_triple() -> Option<&'static str> {
    Some("x86_64-unknown-linux-gnu")
}

#[cfg(all(target_os = "linux", target_arch = "aarch64"))]
fn target_triple() -> Option<&'static str> {
    Some("aarch64-unknown-linux-gnu")
}

#[cfg(not(any(
    all(target_os = "macos", target_arch = "aarch64"),
    all(target_os = "macos", target_arch = "x86_64"),
    all(target_os = "windows", target_arch = "x86_64"),
    all(target_os = "linux", target_arch = "x86_64"),
    all(target_os = "linux", target_arch = "aarch64"),
)))]
fn target_triple() -> Option<&'static str> {
    None
}

fn sidecar_name_candidates() -> Vec<String> {
    let mut names = vec![String::from("quantscript-backend")];
    if let Some(triple) = target_triple() {
        names.push(format!("quantscript-backend-{triple}"));
    }
    if cfg!(windows) {
        let with_exe: Vec<String> = names.iter().map(|name| format!("{name}.exe")).collect();
        names.extend(with_exe);
    }
    names
}

fn bundled_backend_binary_path(app: &AppHandle) -> Option<PathBuf> {
    let candidates = sidecar_name_candidates();

    // Tauri externalBin places sidecars next to the main executable (Contents/MacOS/ on macOS).
    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            for candidate in &candidates {
                let path = exe_dir.join(candidate);
                if path.exists() {
                    return Some(path);
                }
            }
        }
    }

    // Also check the Resource directory (Contents/Resources/ on macOS).
    for candidate in &candidates {
        for lookup in [candidate.clone(), format!("binaries/{candidate}")] {
            if let Ok(path) = app
                .path()
                .resolve(&lookup, tauri::path::BaseDirectory::Resource)
            {
                if path.exists() {
                    return Some(path);
                }
            }
        }
    }
    None
}

fn apply_desktop_storage_env(app: &AppHandle, command: &mut Command) -> Result<(), String> {
    let data_root = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("failed to resolve app data directory: {e}"))?;
    let cache_dir = data_root.join("cache");
    let model_dir = data_root.join("models");
    let tmp_dir = data_root.join("tmp");
    let conversations_dir = data_root.join("storage").join("conversations");
    fs::create_dir_all(&cache_dir).map_err(|e| e.to_string())?;
    fs::create_dir_all(&model_dir).map_err(|e| e.to_string())?;
    fs::create_dir_all(&tmp_dir).map_err(|e| e.to_string())?;
    fs::create_dir_all(&conversations_dir).map_err(|e| e.to_string())?;

    // Pin conversations to Tauri's app-data dir. Browser mode (uvicorn) computes
    // the same <app-data>/com.quantscript.desktop/storage/conversations path, so
    // both modes share one location:
    //   macOS: ~/Library/Application Support/com.quantscript.desktop/storage/conversations
    command
        .env("QUANTSCRIPT_CONVERSATIONS_DIR", &conversations_dir)
        .env("QUANTSCRIPT_DATA_DIR", &data_root)
        .env("HF_HOME", &cache_dir)
        .env("TRANSFORMERS_CACHE", &cache_dir)
        .env("SENTENCE_TRANSFORMERS_HOME", &cache_dir)
        .env("LLAMA_CPP_HOME", &model_dir)
        .env("TMPDIR", &tmp_dir)
        .env("TMP", &tmp_dir)
        .env("TEMP", &tmp_dir);
    Ok(())
}

fn build_bundled_backend_command(app: &AppHandle, port: u16) -> Option<Command> {
    if let Some(binary_path) = bundled_backend_binary_path(app) {
        let mut cmd = Command::new(binary_path);
        cmd.arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string());
        if let Some(backend_dir) = bundled_backend_dir(app) {
            cmd.arg("--backend-dir").arg(backend_dir);
        }
        return Some(cmd);
    }
    None
}

#[cfg(debug_assertions)]
fn build_python_backend_command(app: &AppHandle, port: u16) -> Result<Command, String> {
    let backend_dir = bundled_backend_dir(app).unwrap_or_else(backend_root_dir);
    if !backend_dir.exists() {
        return Err(format!(
            "backend directory not found at {}",
            backend_dir.display()
        ));
    }

    let venv_python = backend_dir.join("venv").join("bin").join("python3");
    let python_bin = if venv_python.exists() {
        venv_python.to_string_lossy().into_owned()
    } else {
        resolve_python_executable()?
    };

    let mut cmd = Command::new(python_bin);
    cmd.arg("-m")
        .arg("uvicorn")
        .arg("app.api.main:app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .current_dir(&backend_dir);
    Ok(cmd)
}

#[cfg(debug_assertions)]
fn resolve_python_executable() -> Result<String, String> {
    #[cfg(target_os = "windows")]
    {
        return Ok(String::from("python"));
    }

    #[cfg(not(target_os = "windows"))]
    {
        let mut candidates: Vec<String> = vec![
            String::from("/opt/homebrew/opt/python@3.14/bin/python3"),
            String::from("/opt/homebrew/bin/python3"),
            String::from("/usr/local/bin/python3"),
            String::from("/usr/bin/python3"),
            String::from("python3"),
        ];
        candidates.dedup();

        for candidate in &candidates {
            if candidate.contains('/') {
                if Path::new(candidate).exists() {
                    return Ok(candidate.clone());
                }
                continue;
            }
            return Ok(candidate.clone());
        }
        Err(String::from("could not resolve a python3 executable"))
    }
}

fn physical_cpu_count() -> usize {
    let cores = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    // Assume hyper-threading: physical cores ≈ logical / 2, floor at 2
    (cores / 2).max(2)
}

fn augmented_path() -> String {
    let system_path = std::env::var("PATH").unwrap_or_default();
    let extra_dirs: &[&str] = &[
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ];
    let mut parts: Vec<&str> = extra_dirs.to_vec();
    for segment in system_path.split(':') {
        if !parts.contains(&segment) {
            parts.push(segment);
        }
    }
    parts.join(":")
}

/// Terminate a backend process and all of its descendants by killing the
/// entire process group.  Sends SIGTERM first, waits up to 3 s for a clean
/// exit, then escalates to SIGKILL.
#[cfg(unix)]
fn kill_backend_process(child: &mut Child) {
    let pgid = child.id() as libc::pid_t;
    unsafe { libc::killpg(pgid, libc::SIGTERM); }

    let deadline = Instant::now() + Duration::from_secs(3);
    while Instant::now() < deadline {
        if child.try_wait().ok().flatten().is_some() {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    unsafe { libc::killpg(pgid, libc::SIGKILL); }
    let _ = child.wait();
}

#[cfg(not(unix))]
fn kill_backend_process(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

fn configure_backend_command(app: &AppHandle, command: &mut Command, sidecar_token: &str) -> Result<(), String> {
    apply_desktop_storage_env(app, command)?;

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }

    if cfg!(debug_assertions) {
        command.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    } else {
        command.stdout(Stdio::null()).stderr(Stdio::piped());
    }

    let threads = physical_cpu_count().to_string();

    let mut path = augmented_path();
    if let Some(backend_dir) = resolved_backend_dir(app) {
        let venv_bin = backend_dir.join("venv").join("bin");
        if venv_bin.is_dir() {
            path = format!("{}:{path}", venv_bin.display());
        }
    }

    command
        .env("PATH", &path)
        .env("ALLOWED_HOSTS", "127.0.0.1,localhost")
        .env(
            "CORS_ORIGINS",
            "tauri://localhost,http://tauri.localhost,http://localhost:5173",
        )
        .env("QUANTSCRIPT_SIDECAR_TOKEN", sidecar_token)
        .env("OMP_NUM_THREADS", &threads)
        .env("MKL_NUM_THREADS", &threads)
        .env("OPENBLAS_NUM_THREADS", &threads)
        .env("NUMEXPR_MAX_THREADS", &threads)
        .env("TOKENIZERS_PARALLELISM", "false");
    Ok(())
}

fn read_child_stderr(child: &mut Child) -> String {
    let Some(stderr) = child.stderr.take() else {
        return String::new();
    };
    let mut buf = Vec::with_capacity(4096);
    let _ = std::io::Read::take(stderr, 4096).read_to_end(&mut buf);
    String::from_utf8_lossy(&buf).trim().to_string()
}

fn spawn_and_wait(
    mut command: Command,
    port: u16,
    timeout: Duration,
    sidecar_token: &str,
) -> Result<Child, String> {
    let mut child = command
        .spawn()
        .map_err(|e| format!("failed to launch backend sidecar: {e}"))?;
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let start = Instant::now();

    while start.elapsed() < timeout {
        if startup_status_reachable(addr, sidecar_token) {
            return Ok(child);
        }
        if let Some(status) = child
            .try_wait()
            .map_err(|e| format!("failed to inspect backend sidecar process: {e}"))?
        {
            let stderr = read_child_stderr(&mut child);
            let detail = if stderr.is_empty() {
                String::new()
            } else {
                format!(" — stderr: {stderr}")
            };
            return Err(format!("backend sidecar exited early with status {status}{detail}"));
        }
        std::thread::sleep(Duration::from_millis(120));
    }

    kill_backend_process(&mut child);
    Err(format!(
        "backend sidecar did not become reachable on 127.0.0.1:{port}"
    ))
}

/// Async wrapper so the long-running spawn-and-poll work runs on a blocking
/// worker thread instead of Tauri's main (event-loop) thread. A synchronous
/// command would freeze the webview for the entire backend boot — a blank
/// window and the macOS beachball — until the sidecar became reachable.
#[tauri::command]
async fn start_backend_sidecar(app: AppHandle) -> Result<BackendRuntimeInfo, String> {
    tauri::async_runtime::spawn_blocking(move || start_backend_sidecar_blocking(&app))
        .await
        .map_err(|e| format!("backend sidecar startup task failed to complete: {e}"))?
}

fn start_backend_sidecar_blocking(app: &AppHandle) -> Result<BackendRuntimeInfo, String> {
    let state = app.state::<BackendState>();
    let mut guard = state.process.lock().map_err(|e| e.to_string())?;
    if let Some(existing) = guard.as_mut() {
        if existing
            .child
            .try_wait()
            .map_err(|e| format!("failed to inspect sidecar process: {e}"))?
            .is_none()
        {
            return Ok(existing.info.clone());
        }
    }
    *guard = None;

    let sidecar_token = generate_sidecar_token();
    let startup_timeout = Duration::from_secs(90);
    let mut attempts: Vec<String> = Vec::new();

    let (child, port) = {
        let mut launched: Option<(Child, u16)> = None;
        if bundled_backend_binary_path(app).is_some() {
            for idx in 0..STARTUP_PORT_ATTEMPTS {
                let port = random_ephemeral_port()?;
                let Some(mut bundled_command) = build_bundled_backend_command(app, port) else {
                    attempts.push(String::from("bundled backend binary disappeared before launch"));
                    break;
                };
                configure_backend_command(app, &mut bundled_command, &sidecar_token)?;
                match spawn_and_wait(bundled_command, port, startup_timeout, &sidecar_token) {
                    Ok(child) => {
                        launched = Some((child, port));
                        break;
                    }
                    Err(err) => attempts.push(format!(
                        "bundled launch attempt {}/{} on port {} failed: {}",
                        idx + 1,
                        STARTUP_PORT_ATTEMPTS,
                        port,
                        err
                    )),
                }
            }
        }

        if launched.is_none() {
            #[cfg(debug_assertions)]
            {
                for idx in 0..STARTUP_PORT_ATTEMPTS {
                    let port = random_ephemeral_port()?;
                    let mut python_command = build_python_backend_command(app, port)?;
                    configure_backend_command(app, &mut python_command, &sidecar_token)?;
                    match spawn_and_wait(python_command, port, startup_timeout, &sidecar_token) {
                        Ok(child) => {
                            launched = Some((child, port));
                            break;
                        }
                        Err(err) => attempts.push(format!(
                            "python launch attempt {}/{} on port {} failed: {}",
                            idx + 1,
                            STARTUP_PORT_ATTEMPTS,
                            port,
                            err
                        )),
                    }
                }
            }
            #[cfg(not(debug_assertions))]
            {
                let detail = if attempts.is_empty() {
                    String::from("no bundled backend binary found")
                } else {
                    attempts.join("; ")
                };
                return Err(format!(
                    "bundled backend sidecar could not be started; refusing python fallback in release build. {detail}",
                ));
            }
        }

        launched.ok_or_else(|| {
            if attempts.is_empty() {
                String::from("failed to launch backend sidecar")
            } else {
                attempts.join("; ")
            }
        })?
    };
    let api_base_url = format!("http://127.0.0.1:{port}");
    let pid = child.id();

    let info = BackendRuntimeInfo {
        api_base_url,
        pid,
        port,
        sidecar_token,
    };
    *guard = Some(ManagedBackend {
        child,
        info: info.clone(),
    });
    Ok(info)
}

fn is_sensitive_path(path: &Path) -> bool {
    let path_str = path.to_string_lossy();
    let blocked_patterns: &[&str] = &[
        ".ssh",
        ".gnupg",
        ".aws",
        ".config/gcloud",
        ".azure",
        ".kube",
        ".docker",
        ".gitconfig",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_ed25519",
        "known_hosts",
        "authorized_keys",
    ];
    for pattern in blocked_patterns {
        if path_str.contains(pattern) {
            return true;
        }
    }
    false
}

#[tauri::command]
fn authorize_file_path(path: String, state: State<AllowedPaths>) -> Result<(), String> {
    let canonical = fs::canonicalize(&path)
        .map_err(|_| String::from("cannot resolve the provided path"))?
        .to_string_lossy()
        .into_owned();
    let canonical_path = Path::new(&canonical);
    if is_sensitive_path(canonical_path) {
        return Err(String::from("access to this path is not allowed"));
    }
    state
        .set
        .lock()
        .map_err(|e| e.to_string())?
        .insert(canonical);
    Ok(())
}

#[tauri::command]
fn read_binary_file(path: String, state: State<AllowedPaths>) -> Result<Vec<u8>, String> {
    let canonical = fs::canonicalize(&path)
        .map_err(|_| String::from("failed to resolve the provided path"))?;
    let canonical_str = canonical.to_string_lossy().into_owned();

    {
        let mut allowed = state.set.lock().map_err(|e| e.to_string())?;
        if !allowed.remove(&canonical_str) {
            return Err(String::from("path not authorized — use the file dialog to select a file"));
        }
    }

    // Defense-in-depth: re-check the resolved path against the denylist.
    if is_sensitive_path(&canonical) {
        return Err(String::from("access to this path is not allowed"));
    }

    // Open the file ONCE and perform every subsequent check against that open
    // handle (fstat + bounded read), never the path. This removes the TOCTOU
    // window between canonicalize/metadata/read where a symlink swap could
    // redirect us to a different (e.g. sensitive) file or one that grew past
    // the size cap after the check.
    let mut file = fs::File::open(&canonical)
        .map_err(|_| String::from("failed to open the file"))?;

    let metadata = file
        .metadata()
        .map_err(|_| String::from("failed to read file metadata"))?;
    if !metadata.is_file() {
        return Err(String::from("not a regular file"));
    }
    if metadata.len() > MAX_READABLE_FILE_SIZE {
        return Err(format!(
            "file too large ({} bytes, max {})",
            metadata.len(),
            MAX_READABLE_FILE_SIZE
        ));
    }

    // Bound the read even if the file grows between fstat and read.
    let mut buf = Vec::with_capacity(metadata.len() as usize);
    std::io::Read::take(&mut file, MAX_READABLE_FILE_SIZE)
        .read_to_end(&mut buf)
        .map_err(|_| String::from("failed to read the file"))?;
    Ok(buf)
}

#[tauri::command]
fn stop_backend_sidecar(state: State<BackendState>) -> Result<(), String> {
    let mut guard = state.process.lock().map_err(|e| e.to_string())?;
    if let Some(mut managed) = guard.take() {
        kill_backend_process(&mut managed.child);
    }
    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendState {
            process: Mutex::new(None),
        })
        .manage(AllowedPaths {
            set: Mutex::new(std::collections::HashSet::new()),
        })
        .invoke_handler(tauri::generate_handler![
            get_desktop_runtime_info,
            start_backend_sidecar,
            stop_backend_sidecar,
            authorize_file_path,
            read_binary_file
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.app_handle().try_state::<BackendState>() {
                    if let Ok(mut guard) = state.process.lock() {
                        if let Some(mut managed) = guard.take() {
                            kill_backend_process(&mut managed.child);
                        }
                    }
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build tauri app");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<BackendState>() {
                if let Ok(mut guard) = state.process.lock() {
                    if let Some(mut managed) = guard.take() {
                        kill_backend_process(&mut managed.child);
                    }
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sensitive_paths_are_blocked() {
        let blocked = [
            "/Users/alice/.ssh/id_rsa",
            "/Users/alice/.ssh/id_ed25519",
            "/home/bob/.aws/credentials",
            "/home/bob/.config/gcloud/access_tokens.db",
            "/home/bob/.gnupg/secring.gpg",
            "/home/bob/.kube/config",
            "/home/bob/.docker/config.json",
            "/home/bob/.gitconfig",
            "/home/bob/.netrc",
            "/home/bob/.npmrc",
            "/home/bob/.pypirc",
            "/etc/ssh/known_hosts",
            "/home/bob/.ssh/authorized_keys",
        ];
        for p in blocked {
            assert!(is_sensitive_path(Path::new(p)), "expected blocked: {p}");
        }
    }

    #[test]
    fn ordinary_paths_are_allowed() {
        let allowed = [
            "/Users/alice/Documents/data.csv",
            "/Users/alice/Downloads/report.pdf",
            "/tmp/upload-1234.png",
            "/home/bob/projects/notes.txt",
        ];
        for p in allowed {
            assert!(!is_sensitive_path(Path::new(p)), "expected allowed: {p}");
        }
    }

    #[test]
    fn startup_probe_proof_is_deterministic_and_matches_hmac() {
        let token = "0123456789abcdef0123456789abcdef";
        let nonce = "fedcba9876543210";

        let a = startup_probe_proof(token, nonce).expect("proof");
        let b = startup_probe_proof(token, nonce).expect("proof");
        assert_eq!(a, b, "same inputs must yield the same proof");

        // SHA-256 digest hex-encoded is always 64 chars.
        assert_eq!(a.len(), 64);

        // Independently recompute the HMAC to confirm correctness.
        let mut mac = Hmac::<Sha256>::new_from_slice(token.as_bytes()).unwrap();
        mac.update(nonce.as_bytes());
        let expected = hex::encode(mac.finalize().into_bytes());
        assert_eq!(a, expected);
    }

    #[test]
    fn startup_probe_proof_changes_with_nonce() {
        let token = "shared-secret-token";
        let a = startup_probe_proof(token, "nonce-a").unwrap();
        let b = startup_probe_proof(token, "nonce-b").unwrap();
        assert_ne!(a, b, "different nonces must yield different proofs");
    }

    #[test]
    fn ephemeral_port_stays_in_range() {
        for _ in 0..2000 {
            let port = random_ephemeral_port().expect("port");
            assert!(
                (MIN_EPHEMERAL_PORT..=MAX_EPHEMERAL_PORT).contains(&port),
                "port {port} out of ephemeral range"
            );
        }
    }

    #[test]
    fn generated_sidecar_token_is_64_hex_chars() {
        let token = generate_sidecar_token();
        assert_eq!(token.len(), 64, "32 random bytes => 64 hex chars");
        assert!(token.chars().all(|c| c.is_ascii_hexdigit()));
        // Two independent tokens should not collide.
        assert_ne!(token, generate_sidecar_token());
    }
}
