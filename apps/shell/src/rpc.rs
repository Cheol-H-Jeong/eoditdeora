// JSON-RPC over stdio bridge to the Python sidecar.
//
// The sidecar is a PyInstaller-frozen executable named `eoditdeora-core`
// bundled via Tauri's `externalBin`. We speak LSP-style framing:
// `Content-Length: N\r\n\r\n<json>`. A single background task muxes
// responses back to the Tauri command handlers via a HashMap of
// pending oneshot channels keyed by request id.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicI64, Ordering},
    Arc,
};

use anyhow::{anyhow, Context, Result};
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::{oneshot, Mutex};

pub struct SidecarState {
    next_id: AtomicI64,
    pending: Arc<Mutex<HashMap<i64, oneshot::Sender<serde_json::Value>>>>,
    // We keep the child alive via its stdin writer. `CommandChild` exposes
    // `write` which handles framing from the Rust side.
    child: Arc<Mutex<CommandChild>>,
}

impl SidecarState {
    pub fn spawn(app: AppHandle) -> Result<Self> {
        // Resolve sidecar path. In dev we run `python -m
        // eoditdeora.api.rpc_server` so contributors don't need to freeze
        // the binary on every iteration.
        let (cmd_name, cmd_args): (String, Vec<String>) = if cfg!(debug_assertions) {
            let repo_root = resolve_repo_root(&app).unwrap_or_else(|| PathBuf::from("."));
            (
                "python3".to_string(),
                vec![
                    "-u".into(),
                    "-m".into(),
                    "eoditdeora.api.rpc_server".into(),
                ],
            )
                .tap(|_| tracing::info!(dir = ?repo_root, "spawning python sidecar in dev mode"))
        } else {
            ("eoditdeora-core".to_string(), Vec::new())
        };

        let shell = app.shell();
        let command = if cfg!(debug_assertions) {
            shell
                .command(&cmd_name)
                .args(cmd_args)
                .current_dir(resolve_repo_root(&app).unwrap_or_else(|| PathBuf::from(".")))
                .envs(vec![("PYTHONPATH", "core".to_string())])
        } else {
            shell.sidecar(&cmd_name).context("resolve bundled sidecar")?
        };
        let (mut rx, child) = command.spawn().context("spawn sidecar")?;

        let pending: Arc<Mutex<HashMap<i64, oneshot::Sender<serde_json::Value>>>> =
            Arc::new(Mutex::new(HashMap::new()));

        let pending_rx = pending.clone();
        tokio::spawn(async move {
            // Accumulating byte buffer for LSP-style framing.
            let mut buf: Vec<u8> = Vec::with_capacity(64 * 1024);
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(chunk) => {
                        buf.extend_from_slice(&chunk);
                        while let Some((msg, rest)) = try_take_message(&buf) {
                            buf = rest;
                            if let Err(e) = dispatch_message(&pending_rx, &msg).await {
                                tracing::warn!(error = %e, "dispatch_message failed");
                            }
                        }
                    }
                    CommandEvent::Stderr(chunk) => {
                        if let Ok(s) = std::str::from_utf8(&chunk) {
                            tracing::debug!(target: "sidecar.stderr", "{}", s.trim_end());
                        }
                    }
                    CommandEvent::Terminated(payload) => {
                        tracing::error!(?payload, "sidecar terminated");
                        break;
                    }
                    _ => {}
                }
            }
        });

        Ok(Self {
            next_id: AtomicI64::new(1),
            pending,
            child: Arc::new(Mutex::new(child)),
        })
    }

    pub async fn call(&self, method: &str, params: serde_json::Value) -> Result<serde_json::Value> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (tx, rx) = oneshot::channel();
        {
            let mut p = self.pending.lock().await;
            p.insert(id, tx);
        }
        let payload = serde_json::json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });
        let body = serde_json::to_vec(&payload)?;
        let mut framed =
            format!("Content-Length: {}\r\n\r\n", body.len()).into_bytes();
        framed.extend_from_slice(&body);
        {
            let mut child = self.child.lock().await;
            child
                .write(&framed)
                .map_err(|e| anyhow!("sidecar write: {e:#}"))?;
        }
        let value = rx.await.map_err(|_| anyhow!("sidecar response channel closed"))?;
        if let Some(err) = value.get("error") {
            return Err(anyhow!("rpc_error: {}", err));
        }
        Ok(value
            .get("result")
            .cloned()
            .unwrap_or(serde_json::Value::Null))
    }
}

fn try_take_message(buf: &[u8]) -> Option<(serde_json::Value, Vec<u8>)> {
    // Find header terminator "\r\n\r\n"
    let sep = b"\r\n\r\n";
    let sep_pos = buf.windows(sep.len()).position(|w| w == sep)?;
    let header = std::str::from_utf8(&buf[..sep_pos]).ok()?;
    let mut length: Option<usize> = None;
    for line in header.split("\r\n") {
        if let Some((k, v)) = line.split_once(':') {
            if k.trim().eq_ignore_ascii_case("content-length") {
                length = v.trim().parse::<usize>().ok();
            }
        }
    }
    let length = length?;
    let start = sep_pos + sep.len();
    if buf.len() < start + length {
        return None;
    }
    let body = &buf[start..start + length];
    let value = serde_json::from_slice::<serde_json::Value>(body).ok()?;
    let rest = buf[start + length..].to_vec();
    Some((value, rest))
}

async fn dispatch_message(
    pending: &Arc<Mutex<HashMap<i64, oneshot::Sender<serde_json::Value>>>>,
    msg: &serde_json::Value,
) -> Result<()> {
    let Some(id) = msg.get("id").and_then(|v| v.as_i64()) else {
        // Notifications not expected from sidecar; ignore.
        return Ok(());
    };
    let mut p = pending.lock().await;
    if let Some(tx) = p.remove(&id) {
        let _ = tx.send(msg.clone());
    }
    Ok(())
}

fn resolve_repo_root(app: &AppHandle) -> Option<PathBuf> {
    // In development we bubble up three levels from the .app/exe to reach
    // the monorepo root so Python sees the `core/` module.
    let exe = app.path().resource_dir().ok()?;
    Some(exe.parent()?.parent()?.parent()?.to_path_buf())
}

// Local tap for side-effect logging without consuming the value.
trait Tap: Sized {
    fn tap<F: FnOnce(&Self)>(self, f: F) -> Self {
        f(&self);
        self
    }
}
impl<T> Tap for T {}
