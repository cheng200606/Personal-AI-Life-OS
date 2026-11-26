#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use std::{
    io::{BufRead, BufReader, Write},
    os::windows::process::CommandExt,
    path::Path,
    process::{Child, Command, Stdio},
    sync::{mpsc, Mutex},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{menu::MenuBuilder, tray::TrayIconBuilder, AppHandle, Manager};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_notification::NotificationExt;
use winreg::{enums::HKEY_CURRENT_USER, RegKey};

#[derive(Clone, Serialize)]
struct Runtime {
    origin: String,
    secret: String,
}

#[derive(Deserialize)]
struct Ready {
    port: u16,
}

struct Sidecar {
    child: Child,
    runtime: Runtime,
    path_key: [u8; 32],
}

fn new_key() -> Result<[u8; 32], String> {
    let mut key = [0; 32];
    getrandom::fill(&mut key).map_err(|error| error.to_string())?;
    Ok(key)
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

impl Sidecar {
    fn start(executable: &Path, data: &Path) -> Result<Self, String> {
        let secret = hex(&new_key()?);
        let path_key = new_key()?;
        std::fs::create_dir_all(data).map_err(|error| error.to_string())?;
        let mut child = Command::new(executable)
            .arg(data)
            .current_dir(data)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .spawn()
            .map_err(|error| format!("Sidecar could not start: {error}"))?;
        let ready = (|| {
            let stdin = child.stdin.as_mut().ok_or("Missing sidecar stdin.")?;
            writeln!(stdin, "{secret}\n{}", hex(&path_key)).map_err(|error| error.to_string())?;
            let stdout = child.stdout.take().ok_or("Missing sidecar stdout.")?;
            let (sender, receiver) = mpsc::sync_channel(1);
            thread::spawn(move || {
                let mut reader = BufReader::new(stdout);
                let mut line = String::new();
                let value = reader
                    .read_line(&mut line)
                    .ok()
                    .and_then(|_| serde_json::from_str::<Ready>(&line).ok());
                let _ = sender.send(value);
                let _ = std::io::copy(&mut reader, &mut std::io::sink());
            });
            receiver
                .recv_timeout(Duration::from_secs(45))
                .ok()
                .flatten()
                .filter(|ready| ready.port != 0)
                .ok_or_else(|| "Sidecar did not become ready. See logs/sidecar.log.".to_owned())
        })();
        match ready {
            Ok(ready) => Ok(Self {
                child,
                runtime: Runtime {
                    origin: format!("http://127.0.0.1:{}", ready.port),
                    secret,
                },
                path_key,
            }),
            Err(error) => {
                stop_child(&mut child);
                Err(error)
            }
        }
    }
}

fn stop_child(child: &mut Child) {
    drop(child.stdin.take());
    let deadline = Instant::now() + Duration::from_secs(8);
    while Instant::now() < deadline {
        if !matches!(child.try_wait(), Ok(None)) {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
    let _ = child.kill();
    let _ = child.wait();
}

impl Drop for Sidecar {
    fn drop(&mut self) {
        stop_child(&mut self.child);
    }
}

struct Supervisor(Mutex<Option<Sidecar>>);

#[tauri::command]
fn desktop_autostart(enabled: Option<bool>) -> Result<bool, String> {
    const RUN_KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
    const APP: &str = "PersonalAILifeOS";
    let registry = RegKey::predef(HKEY_CURRENT_USER);
    let (run, _) = registry
        .create_subkey(RUN_KEY)
        .map_err(|error| error.to_string())?;
    if let Some(enabled) = enabled {
        if enabled {
            let executable = std::env::current_exe().map_err(|error| error.to_string())?;
            let command = format!("\"{}\" --background", executable.display());
            run.set_value(APP, &command)
                .map_err(|error| error.to_string())?;
        } else {
            match run.delete_value(APP) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.to_string()),
            }
        }
    }
    Ok(run.get_value::<String, _>(APP).is_ok())
}

#[derive(Serialize)]
struct PathGrant {
    payload: String,
    signature: String,
}

#[tauri::command]
async fn desktop_pick_chat(app: AppHandle) -> Result<Option<PathGrant>, String> {
    let selected = app
        .dialog()
        .file()
        .set_title("选择聊天导出")
        .add_filter("聊天导出", &["json", "jsonl"])
        .blocking_pick_file();
    let Some(selected) = selected else {
        return Ok(None);
    };
    sign_path(
        &app,
        &selected.into_path().map_err(|error| error.to_string())?,
        "chat",
    )
    .map(Some)
}

#[tauri::command]
async fn desktop_pick_backup(app: AppHandle) -> Result<Option<PathGrant>, String> {
    let selected = app
        .dialog()
        .file()
        .set_title("选择 Life OS 备份")
        .add_filter("Life OS 备份", &["zip"])
        .blocking_pick_file();
    let Some(selected) = selected else {
        return Ok(None);
    };
    sign_path(
        &app,
        &selected.into_path().map_err(|error| error.to_string())?,
        "restore",
    )
    .map(Some)
}

#[tauri::command]
async fn desktop_pick_folder(app: AppHandle, purpose: String) -> Result<Option<PathGrant>, String> {
    let title = match purpose.as_str() {
        "markdown" => "选择 Markdown 记录目录",
        "obsidian" => "选择 Obsidian Vault",
        "chat_folder" => "选择聊天导出目录",
        "backup" => "选择备份目录",
        "export" => "选择 Markdown 导出目录",
        _ => return Err("Unsupported folder purpose.".into()),
    };
    let Some(selected) = app.dialog().file().set_title(title).blocking_pick_folder() else {
        return Ok(None);
    };
    sign_path(
        &app,
        &selected.into_path().map_err(|error| error.to_string())?,
        &purpose,
    )
    .map(Some)
}

fn sign_path(app: &AppHandle, selected: &Path, purpose: &str) -> Result<PathGrant, String> {
    let path = selected.to_str().ok_or("Unsupported file name.")?;
    let issued = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_secs();
    let payload =
        serde_json::json!({"path": path, "purpose": purpose, "issued": issued}).to_string();
    let state = app.state::<Supervisor>();
    let process = state.0.lock().map_err(|error| error.to_string())?;
    let sidecar = process.as_ref().ok_or("Desktop service is not running.")?;
    let mut signer =
        Hmac::<Sha256>::new_from_slice(&sidecar.path_key).map_err(|e| e.to_string())?;
    signer.update(payload.as_bytes());
    Ok(PathGrant {
        payload,
        signature: hex(&signer.finalize().into_bytes()),
    })
}

#[tauri::command]
async fn desktop_runtime(app: AppHandle) -> Result<Runtime, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<Supervisor>();
        let mut process = state.0.lock().map_err(|error| error.to_string())?;
        if let Some(sidecar) = process.as_mut() {
            if matches!(sidecar.child.try_wait(), Ok(None)) {
                return Ok(sidecar.runtime.clone());
            }
        }
        let executable = app
            .path()
            .resource_dir()
            .map_err(|error| error.to_string())?
            .join("sidecar")
            .join("lifeos-sidecar.exe");
        let executable = if cfg!(debug_assertions) && !executable.is_file() {
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../dist/lifeos-sidecar/lifeos-sidecar.exe")
        } else {
            executable
        };
        let data = app
            .path()
            .local_data_dir()
            .map_err(|error| error.to_string())?
            .join("PersonalAILifeOS");
        #[cfg(debug_assertions)]
        let data = std::env::var_os("LIFEOS_SMOKE_DATA")
            .map(std::path::PathBuf::from)
            .filter(|path| path.is_absolute())
            .unwrap_or(data);
        let sidecar = Sidecar::start(&executable, &data)?;
        let runtime = sidecar.runtime.clone();
        *process = Some(sidecar);
        Ok(runtime)
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn desktop_stop_sidecar(app: AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        let supervisor = app.state::<Supervisor>();
        let mut process = supervisor.0.lock().map_err(|error| error.to_string())?;
        process.take();
        Ok(())
    })
    .await
    .map_err(|error| error.to_string())?
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[tauri::command]
fn desktop_notify_due(app: AppHandle, count: u32) -> Result<(), String> {
    if count == 0 {
        return Ok(());
    }
    app.notification()
        .builder()
        .title("Personal AI Life OS")
        .body(format!("有 {count} 条提醒已到期"))
        .show()
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn desktop_tray_status(app: AppHandle, active: u32, needs_attention: bool) {
    if let Some(tray) = app.tray_by_id("lifeos-tray") {
        let status = if needs_attention {
            "部分来源需要处理".to_owned()
        } else {
            format!("{active} 个授权目录正在同步")
        };
        let _ = tray.set_tooltip(Some(format!("Personal AI Life OS · {status}")));
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            show_main(app)
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(Supervisor(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            desktop_runtime,
            desktop_pick_chat,
            desktop_pick_folder,
            desktop_autostart,
            desktop_pick_backup,
            desktop_stop_sidecar,
            desktop_notify_due,
            desktop_tray_status
        ])
        .setup(|app| {
            let menu = MenuBuilder::new(app)
                .text("open", "打开 Personal AI Life OS")
                .separator()
                .text("quit", "退出")
                .build()?;
            let mut tray = TrayIconBuilder::with_id("lifeos-tray")
                .menu(&menu)
                .tooltip("Personal AI Life OS")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "open" => show_main(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let tauri::tray::TrayIconEvent::Click {
                        button: tauri::tray::MouseButton::Left,
                        button_state: tauri::tray::MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            if std::env::args().any(|argument| argument == "--background") {
                if let Some(window) = app.get_webview_window("main") {
                    window.hide()?;
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("desktop app initialization failed");
    app.run(|app, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            if let Ok(mut process) = app.state::<Supervisor>().0.lock() {
                process.take();
            }
        }
    });
}
