//! End-to-end tests for the `textstats` project: the multifile source must
//! compile to a working native executable, both via `run` and via `build`.

use std::path::PathBuf;
use std::process::{Command, Stdio};

fn maylang() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_maylang"))
}

fn workspace_stdlib() -> PathBuf {
    PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../../../../stdlib"))
}

fn textstats_main() -> PathBuf {
    PathBuf::from(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../../example_projects/apps/textstats/main.may"
    ))
}

#[test]
#[ignore = "the current TextStats example uses strict syntax unsupported by the historical Rust parser"]
fn textstats_runs_natively() {
    let output = Command::new(maylang())
        .arg("run")
        .arg(textstats_main())
        .env("MAYLANG_STDLIB", workspace_stdlib())
        .stdin(Stdio::null())
        .output()
        .expect("run maylang");
    assert!(
        output.status.success(),
        "native run failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8_lossy(&output.stdout);
    assert!(text.contains("TEXT STATISTICS"), "{text}");
    assert!(text.contains("words 31"), "{text}");
    assert!(text.contains("fox"), "{text}");
}

#[cfg(target_os = "linux")]
#[test]
#[ignore = "the current TextStats example uses strict syntax unsupported by the historical Rust parser"]
fn textstats_compiles_into_a_running_native_executable() {
    let out = std::env::temp_dir().join(format!("textstats_native_{}", std::process::id()));
    let status = Command::new(maylang())
        .arg("build")
        .arg("-o")
        .arg(&out)
        .arg(textstats_main())
        .status()
        .expect("build maylang");
    assert!(status.success());

    let output = Command::new(&out)
        .stdin(Stdio::null())
        .output()
        .expect("run native binary");
    assert!(
        output.status.success(),
        "native failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8_lossy(&output.stdout);
    assert!(text.contains("TEXT STATISTICS"), "{text}");
    assert!(text.contains("longest sleepy"), "{text}");
    let _ = std::fs::remove_file(&out);
}
