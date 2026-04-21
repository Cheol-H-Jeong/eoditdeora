// Eoditdeora shell library: owns the sidecar process lifecycle and the
// Tauri command surface exposed to the Svelte UI.
//
// SPDX-License-Identifier: AGPL-3.0-or-later

mod rpc;

use std::sync::Arc;
use tauri::{Emitter, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

use crate::rpc::{RpcInvokeError, SidecarState};

#[derive(serde::Serialize)]
struct PingResponse {
    ok: bool,
    version: String,
}

#[tauri::command]
async fn rpc_call(
    state: tauri::State<'_, SidecarState>,
    method: String,
    params: serde_json::Value,
) -> Result<serde_json::Value, RpcInvokeError> {
    state.call(&method, params).await
}

#[tauri::command]
async fn open_in_os(path: String, app: tauri::AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener()
        .open_path(path, None::<&str>)
        .map_err(|e| format!("open_in_os: {e:#}"))
}

pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            let sidecar = Arc::new(SidecarState::spawn(app.handle().clone())?);
            app.manage(sidecar.clone());

            let handle = app.handle().clone();
            let chord: Shortcut = "CmdOrCtrl+Shift+Space"
                .parse()
                .expect("valid global shortcut string");
            app.global_shortcut().on_shortcut(chord, move |_, _, event| {
                if event.state == ShortcutState::Pressed {
                    if let Some(win) = handle.get_webview_window("main") {
                        let _ = win.show();
                        let _ = win.set_focus();
                        let _ = handle.emit_to("main", "hotkey:activate", ());
                    }
                }
            })?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![rpc_call, open_in_os])
        .run(tauri::generate_context!())
        .expect("tauri runtime failed");
}
