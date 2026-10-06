//! End-to-end test for the `maytasks` project: build it, then drive it with
//! one-shot commands against a temporary HOME.

use std::path::PathBuf;
use std::process::{Command, Stdio};

fn maylang() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_maylang"))
}

fn project_main() -> PathBuf {
    PathBuf::from(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../../example_projects/apps/maytasks/main.may"
    ))
}

#[cfg(target_os = "linux")]
#[ignore = "the current MayTasks example uses strict syntax unsupported by the historical Rust parser"]
#[test]
fn maytasks_add_list_done_and_persist() {
    let dir = std::env::temp_dir().join(format!("maytasks_test_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let exe = dir.join("maytasks");

    let status = Command::new(maylang())
        .arg("build")
        .arg("-o")
        .arg(&exe)
        .arg(project_main())
        .status()
        .expect("build maytasks");
    assert!(status.success());

    let run = |args: &[&str]| {
        let out = Command::new(&exe)
            .args(args)
            .env("HOME", &dir)
            .stdin(Stdio::null())
            .output()
            .expect("run maytasks");
        assert!(out.status.success(), "maytasks failed: {args:?}");
        String::from_utf8_lossy(&out.stdout).into_owned()
    };

    run(&["add", "buy oat milk"]);
    run(&["add", "walk the dog"]);
    let listed = run(&["list"]);
    assert!(listed.contains("buy oat milk"), "{listed}");
    assert!(listed.contains("walk the dog"), "{listed}");

    run(&["done", "1"]);
    let listed = run(&["list"]);
    assert!(listed.contains("[x] buy oat milk"), "{listed}");
    assert!(listed.contains("[ ] walk the dog"), "{listed}");

    // Persistence: a fresh process sees the saved tasks.
    let stats = run(&["stats"]);
    assert!(stats.contains("done 1"), "{stats}");

    run(&["rm", "2"]);
    let listed = run(&["list"]);
    assert!(!listed.contains("walk the dog"), "{listed}");

    let _ = std::fs::remove_dir_all(&dir);
}
