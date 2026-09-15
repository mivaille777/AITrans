#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    path::{Path, PathBuf},
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
    thread,
    time::Duration,
};
use tauri::{Manager, PhysicalPosition};

static OVERLAY_MOVE_GENERATION: AtomicU64 = AtomicU64::new(0);
const OVERLAY_CORNER_RADIUS_CSS_PX: f64 = 24.0;
const LLM_CREDENTIAL_TARGET_PREFIX: &str = "AITranslator/ai";
const MAX_LLM_API_KEY_BYTES: usize = 4096;

fn llm_credential_target(provider: &str) -> Result<String, String> {
    let normalized = provider.trim().to_ascii_lowercase().replace('-', "_");
    match normalized.as_str() {
        "deepseek" | "openai_compatible" => {
            Ok(format!("{LLM_CREDENTIAL_TARGET_PREFIX}/{normalized}"))
        }
        _ => Err("Unsupported AI provider credential namespace.".to_string()),
    }
}

#[cfg(windows)]
fn wide_string(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(windows)]
fn llm_credential_is_configured(provider: &str) -> Result<bool, String> {
    use std::ptr::null_mut;
    use windows_sys::Win32::Foundation::GetLastError;
    use windows_sys::Win32::Security::Credentials::{
        CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC,
    };

    let target = wide_string(&llm_credential_target(provider)?);
    let mut credential: *mut CREDENTIALW = null_mut();
    let result = unsafe { CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut credential) };
    if result == 0 {
        let error = unsafe { GetLastError() };
        return match error {
            1168 => Ok(false),
            _ => Err("Unable to read the saved AI provider credential.".to_string()),
        };
    }

    let configured = unsafe { !credential.is_null() && (*credential).CredentialBlobSize > 0 };
    unsafe { CredFree(credential.cast()) };
    Ok(configured)
}

#[cfg(not(windows))]
fn llm_credential_is_configured(_provider: &str) -> Result<bool, String> {
    Err("AI credential storage is available only on Windows.".to_string())
}

#[cfg(windows)]
fn save_llm_credential_value(provider: &str, api_key: &str) -> Result<(), String> {
    use windows_sys::Win32::Security::Credentials::{
        CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
    };

    let target_name = llm_credential_target(provider)?;
    let secret = api_key.trim();
    if secret.is_empty() {
        return Err("API Key must not be empty.".to_string());
    }
    if secret.len() > MAX_LLM_API_KEY_BYTES {
        return Err("API Key is too long.".to_string());
    }

    let mut target = wide_string(&target_name);
    let mut username = wide_string(provider.trim());
    let mut credential: CREDENTIALW = unsafe { std::mem::zeroed() };
    credential.Type = CRED_TYPE_GENERIC;
    credential.TargetName = target.as_mut_ptr();
    credential.UserName = username.as_mut_ptr();
    credential.CredentialBlobSize =
        u32::try_from(secret.len()).map_err(|_| "API Key is too long.".to_string())?;
    credential.CredentialBlob = secret.as_ptr().cast_mut();
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE;

    if unsafe { CredWriteW(&credential, 0) } == 0 {
        return Err("Unable to save the AI provider credential.".to_string());
    }
    Ok(())
}

#[cfg(not(windows))]
fn save_llm_credential_value(_provider: &str, _api_key: &str) -> Result<(), String> {
    Err("AI credential storage is available only on Windows.".to_string())
}

#[cfg(windows)]
fn delete_llm_credential_value(provider: &str) -> Result<(), String> {
    use windows_sys::Win32::Foundation::GetLastError;
    use windows_sys::Win32::Security::Credentials::{CredDeleteW, CRED_TYPE_GENERIC};

    let target = wide_string(&llm_credential_target(provider)?);
    if unsafe { CredDeleteW(target.as_ptr(), CRED_TYPE_GENERIC, 0) } == 0 {
        let error = unsafe { GetLastError() };
        if error != 1168 {
            return Err("Unable to delete the saved AI provider credential.".to_string());
        }
    }
    Ok(())
}

#[cfg(not(windows))]
fn delete_llm_credential_value(_provider: &str) -> Result<(), String> {
    Err("AI credential storage is available only on Windows.".to_string())
}

#[tauri::command]
fn get_llm_credential_status(provider: String) -> Result<bool, String> {
    llm_credential_is_configured(&provider)
}

#[tauri::command]
fn save_llm_credential(provider: String, api_key: String) -> Result<(), String> {
    save_llm_credential_value(&provider, &api_key)
}

#[tauri::command]
fn delete_llm_credential(provider: String) -> Result<(), String> {
    delete_llm_credential_value(&provider)
}

#[cfg(test)]
mod credential_tests {
    use super::llm_credential_target;

    #[test]
    fn credential_targets_are_limited_to_supported_providers() {
        assert_eq!(
            llm_credential_target("deepseek").as_deref(),
            Ok("AITranslator/ai/deepseek")
        );
        assert_eq!(
            llm_credential_target("openai-compatible").as_deref(),
            Ok("AITranslator/ai/openai_compatible")
        );
        assert!(llm_credential_target("other").is_err());
    }
}

#[cfg(windows)]
fn enforce_overlay_borderless_frame(window: &tauri::WebviewWindow) -> Result<(), String> {
    use std::ptr::null_mut;
    use windows_sys::Win32::Foundation::HWND as Win32Hwnd;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetWindowLongPtrW, SetWindowLongPtrW, SetWindowPos, GWL_EXSTYLE, GWL_STYLE,
        SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER,
        WS_CAPTION, WS_MAXIMIZEBOX, WS_MINIMIZEBOX, WS_POPUP, WS_SYSMENU, WS_THICKFRAME,
        WS_EX_CLIENTEDGE, WS_EX_DLGMODALFRAME, WS_EX_STATICEDGE, WS_EX_WINDOWEDGE,
    };

    let hwnd = window.hwnd().map_err(|error| error.to_string())?;
    let hwnd = hwnd.0 as Win32Hwnd;

    // Tauri/tao currently has an upstream Windows issue where a transparent,
    // undecorated window can expose a ghost Win32 caption after focus or drag
    // transitions. `set_decorations(false)` alone does not reliably remove that
    // compositor layer. Strip the caption/frame style bits directly from the
    // HWND and force Windows to recalculate the non-client frame.
    let style = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } as u32;
    let borderless_style = (style
        & !(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU))
        | WS_POPUP;
    if borderless_style != style {
        unsafe {
            SetWindowLongPtrW(hwnd, GWL_STYLE, borderless_style as isize);
        }
    }

    let ex_style = unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) } as u32;
    let borderless_ex_style = ex_style
        & !(WS_EX_DLGMODALFRAME | WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE);
    if borderless_ex_style != ex_style {
        unsafe {
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, borderless_ex_style as isize);
        }
    }

    let result = unsafe {
        SetWindowPos(
            hwnd,
            null_mut(),
            0,
            0,
            0,
            0,
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        )
    };
    if result == 0 {
        return Err("SetWindowPos(SWP_FRAMECHANGED) failed".to_string());
    }

    Ok(())
}

#[cfg(not(windows))]
fn enforce_overlay_borderless_frame(_window: &tauri::WebviewWindow) -> Result<(), String> {
    Ok(())
}

#[cfg(windows)]
fn apply_overlay_window_region(window: &tauri::WebviewWindow) -> Result<(), String> {
    use windows_sys::Win32::Foundation::HWND as Win32Hwnd;
    use windows_sys::Win32::Graphics::Gdi::{
        CreateRoundRectRgn, DeleteObject, SetWindowRgn, HGDIOBJ,
    };

    let hwnd = window.hwnd().map_err(|error| error.to_string())?;
    let size = window.outer_size().map_err(|error| error.to_string())?;
    let scale_factor = window.scale_factor().map_err(|error| error.to_string())?;
    let width = i32::try_from(size.width).map_err(|_| "overlay width is too large")?;
    let height = i32::try_from(size.height).map_err(|_| "overlay height is too large")?;

    if width <= 0 || height <= 0 {
        return Err("overlay window has an invalid size".to_string());
    }

    let radius = (OVERLAY_CORNER_RADIUS_CSS_PX * scale_factor)
        .round()
        .clamp(1.0, f64::from(width.min(height) / 2)) as i32;
    let region = unsafe { CreateRoundRectRgn(0, 0, width, height, radius * 2, radius * 2) };

    if region.is_null() {
        return Err("CreateRoundRectRgn failed".to_string());
    }

    let result = unsafe { SetWindowRgn(hwnd.0 as Win32Hwnd, region, 1) };
    if result == 0 {
        unsafe {
            DeleteObject(region as HGDIOBJ);
        }
        return Err("SetWindowRgn failed".to_string());
    }

    // SetWindowRgn takes ownership of `region` after a successful call.
    Ok(())
}

#[cfg(not(windows))]
fn apply_overlay_window_region(_window: &tauri::WebviewWindow) -> Result<(), String> {
    Ok(())
}

#[cfg(windows)]
fn apply_overlay_window_shape(window: &tauri::WebviewWindow) -> Result<(), String> {
    use std::{ffi::c_void, mem::size_of};
    use windows_sys::Win32::Foundation::HWND as Win32Hwnd;
    use windows_sys::Win32::Graphics::Dwm::{
        DwmSetWindowAttribute, DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE,
        DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND,
    };

    enforce_overlay_borderless_frame(window)?;

    let hwnd = window.hwnd().map_err(|error| error.to_string())?;
    let hwnd = hwnd.0 as Win32Hwnd;

    // The overlay has a 24 CSS-pixel radius, which is intentionally larger
    // than Windows 11's standard DWM corner radius. Letting DWM round the HWND
    // while CSS rounds the WebView produces the doubled / clipped corner halos
    // visible on high-DPI displays. Disable DWM rounding and use one exact
    // SetWindowRgn clip whose radius is derived from the current scale factor.
    let corner_preference: i32 = DWMWCP_DONOTROUND;
    let _ = unsafe {
        DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE as u32,
            &corner_preference as *const i32 as *const c_void,
            size_of::<i32>() as u32,
        )
    };

    // Windows 11 can draw a one-pixel frame around an undecorated HWND. That
    // frame is especially visible at transparent corners, so explicitly
    // suppress it and let the CSS shell draw the only visible glass outline.
    let border_color: u32 = DWMWA_COLOR_NONE;
    let _ = unsafe {
        DwmSetWindowAttribute(
            hwnd,
            DWMWA_BORDER_COLOR as u32,
            &border_color as *const u32 as *const c_void,
            size_of::<u32>() as u32,
        )
    };

    apply_overlay_window_region(window)
}

#[cfg(not(windows))]
fn apply_overlay_window_shape(_window: &tauri::WebviewWindow) -> Result<(), String> {
    Ok(())
}

#[cfg(windows)]
fn apply_overlay_visual_theme(
    window: &tauri::WebviewWindow,
    theme: &str,
) -> Result<(), String> {
    use std::{ffi::c_void, mem::size_of};
    use windows_sys::Win32::Foundation::HWND as Win32Hwnd;
    use windows_sys::Win32::Graphics::Dwm::{
        DwmSetWindowAttribute, DWMSBT_NONE, DWMSBT_TRANSIENTWINDOW,
        DWMWA_SYSTEMBACKDROP_TYPE, DWMWA_USE_IMMERSIVE_DARK_MODE,
    };

    enforce_overlay_borderless_frame(window)?;

    let hwnd = window.hwnd().map_err(|error| error.to_string())?;
    let hwnd = hwnd.0 as Win32Hwnd;
    let dark_mode: i32 = if theme.eq_ignore_ascii_case("dark") { 1 } else { 0 };

    // Keep the native non-client color mode aligned with the React theme. This
    // is best-effort because older Windows releases may not expose the DWM
    // attributes used by Windows 11.
    let dark_mode_result = unsafe {
        DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE as u32,
            &dark_mode as *const i32 as *const c_void,
            size_of::<i32>() as u32,
        )
    };
    if dark_mode_result < 0 {
        eprintln!(
            "DWM immersive dark mode is unavailable for the overlay: HRESULT {dark_mode_result:#x}"
        );
    }

    let backdrop_type: i32 = if theme.eq_ignore_ascii_case("light") {
        DWMSBT_TRANSIENTWINDOW
    } else {
        DWMSBT_NONE
    };
    let backdrop_result = unsafe {
        DwmSetWindowAttribute(
            hwnd,
            DWMWA_SYSTEMBACKDROP_TYPE as u32,
            &backdrop_type as *const i32 as *const c_void,
            size_of::<i32>() as u32,
        )
    };
    if backdrop_result < 0 {
        eprintln!(
            "DWM system backdrop is unavailable for the overlay: HRESULT {backdrop_result:#x}"
        );
    }

    // DWM attribute updates can trigger another non-client frame calculation.
    // Reapply the HWND style contract after the theme mutation as well.
    enforce_overlay_borderless_frame(window)
}

#[cfg(not(windows))]
fn apply_overlay_visual_theme(
    _window: &tauri::WebviewWindow,
    _theme: &str,
) -> Result<(), String> {
    Ok(())
}

fn next_overlay_move_generation() -> u64 {
    OVERLAY_MOVE_GENERATION.fetch_add(1, Ordering::SeqCst) + 1
}

#[tauri::command]
fn cancel_overlay_motion() {
    next_overlay_move_generation();
}

fn resolve_window(
    app: &tauri::AppHandle,
    window_label: &str,
) -> Result<tauri::WebviewWindow, String> {
    app.get_webview_window(window_label)
        .ok_or_else(|| format!("window '{window_label}' is unavailable"))
}

#[tauri::command]
fn window_minimize(app: tauri::AppHandle, window_label: String) -> Result<(), String> {
    resolve_window(&app, &window_label)?
        .minimize()
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn window_toggle_maximize(app: tauri::AppHandle, window_label: String) -> Result<bool, String> {
    let window = resolve_window(&app, &window_label)?;
    let is_maximized = window.is_maximized().map_err(|error| error.to_string())?;

    if is_maximized {
        window.unmaximize().map_err(|error| error.to_string())?;
    } else {
        window.maximize().map_err(|error| error.to_string())?;
    }

    Ok(!is_maximized)
}

#[tauri::command]
fn window_is_maximized(app: tauri::AppHandle, window_label: String) -> Result<bool, String> {
    resolve_window(&app, &window_label)?
        .is_maximized()
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn window_close(app: tauri::AppHandle, window_label: String) -> Result<(), String> {
    resolve_window(&app, &window_label)?
        .close()
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn pick_knowledge_document() -> Option<String> {
    rfd::FileDialog::new()
        .set_title("Add document to Knowledge Library")
        .add_filter(
            "Knowledge documents",
            &["pdf", "docx", "txt", "md", "html", "htm"],
        )
        .pick_file()
        .map(|path| path.to_string_lossy().into_owned())
}

fn evidence_file_path(resource_url: &str) -> Result<PathBuf, String> {
    let parsed = url::Url::parse(resource_url).map_err(|_| "Evidence source URI is invalid.")?;
    if parsed.scheme() != "file" {
        return Err("Only verified local file evidence can be opened.".to_string());
    }
    let path = parsed
        .to_file_path()
        .map_err(|_| "Evidence source URI is not a local file path.")?;
    if !path.is_absolute() {
        return Err("Evidence source path must be absolute.".to_string());
    }
    let canonical = path
        .canonicalize()
        .map_err(|_| "Evidence source file no longer exists.".to_string())?;
    if !canonical.is_file() {
        return Err("Evidence source is not a file.".to_string());
    }
    Ok(canonical)
}

fn launch_file(path: &Path) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    let mut command = Command::new("explorer.exe");
    #[cfg(target_os = "macos")]
    let mut command = Command::new("open");
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = Command::new("xdg-open");

    command
        .arg(path)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Unable to open evidence source: {error}"))
}

#[tauri::command]
fn open_evidence_source(resource_url: String) -> Result<(), String> {
    launch_file(&evidence_file_path(&resource_url)?)
}

#[tauri::command]
fn update_overlay_window_shape(app: tauri::AppHandle) -> Result<(), String> {
    let overlay = app
        .get_webview_window("overlay")
        .ok_or_else(|| "overlay window is unavailable".to_string())?;

    apply_overlay_window_shape(&overlay)
}

#[tauri::command]
fn enforce_overlay_borderless(app: tauri::AppHandle) -> Result<(), String> {
    let overlay = app
        .get_webview_window("overlay")
        .ok_or_else(|| "overlay window is unavailable".to_string())?;

    apply_overlay_window_shape(&overlay)
}

#[tauri::command]
fn set_overlay_visual_theme(app: tauri::AppHandle, theme: String) -> Result<(), String> {
    if theme != "light" && theme != "dark" {
        return Err(format!("unsupported overlay visual theme '{theme}'"));
    }

    let overlay = app
        .get_webview_window("overlay")
        .ok_or_else(|| "overlay window is unavailable".to_string())?;

    apply_overlay_visual_theme(&overlay, &theme)
}

#[tauri::command]
fn animate_overlay_position(
    app: tauri::AppHandle,
    x: i32,
    y: i32,
    duration_ms: u64,
) -> Result<(), String> {
    let overlay = app
        .get_webview_window("overlay")
        .ok_or_else(|| "overlay window is unavailable".to_string())?;
    let start = overlay
        .outer_position()
        .map_err(|error| error.to_string())?;
    let generation = next_overlay_move_generation();
    let delta_x = x - start.x;
    let delta_y = y - start.y;
    let distance = ((delta_x as f64).powi(2) + (delta_y as f64).powi(2)).sqrt();

    if duration_ms == 0 || distance > 720.0 {
        overlay
            .set_position(PhysicalPosition::new(x, y))
            .map_err(|error| error.to_string())?;
        return Ok(());
    }

    thread::spawn(move || {
        // Keep native motion short and responsive. Doing the interpolation here avoids
        // one WebView -> Tauri IPC round-trip for every animation frame.
        let frame_ms = 8_u64;
        let steps = (duration_ms.div_ceil(frame_ms)).clamp(7, 15) as i32;

        for step in 1..=steps {
            if OVERLAY_MOVE_GENERATION.load(Ordering::Relaxed) != generation {
                return;
            }

            let t = step as f64 / steps as f64;
            let eased = 1.0 - (1.0 - t).powi(3);
            let next_x = start.x as f64 + delta_x as f64 * eased;
            let next_y = start.y as f64 + delta_y as f64 * eased;

            if overlay
                .set_position(PhysicalPosition::new(
                    next_x.round() as i32,
                    next_y.round() as i32,
                ))
                .is_err()
            {
                return;
            }

            if step < steps {
                thread::sleep(Duration::from_millis(frame_ms));
            }
        }
    });

    Ok(())
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            if let Some(overlay) = app.get_webview_window("overlay") {
                if let Err(error) = apply_overlay_window_shape(&overlay) {
                    eprintln!("failed to initialize overlay window shape: {error}");
                }
                if let Err(error) = apply_overlay_visual_theme(&overlay, "light") {
                    eprintln!("failed to initialize overlay visual theme: {error}");
                }

                let overlay_for_window_event = overlay.clone();
                overlay.on_window_event(move |event| {
                    if matches!(
                        event,
                        tauri::WindowEvent::Resized(_)
                            | tauri::WindowEvent::ScaleFactorChanged { .. }
                            | tauri::WindowEvent::Focused(_)
                    ) {
                        if let Err(error) = apply_overlay_window_shape(&overlay_for_window_event) {
                            eprintln!("failed to restore overlay window frame: {error}");
                        }
                    }
                });
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_llm_credential_status,
            save_llm_credential,
            delete_llm_credential,
            animate_overlay_position,
            cancel_overlay_motion,
            window_minimize,
            window_toggle_maximize,
            window_is_maximized,
            window_close,
            pick_knowledge_document,
            open_evidence_source,
            update_overlay_window_shape,
            enforce_overlay_borderless,
            set_overlay_visual_theme
        ])
        .run(tauri::generate_context!())
        .expect("error while running AITranslator desktop shell");
}
