//! End-to-end tests for module namespacing: qualified access, aliases and
//! collision detection.

use std::path::PathBuf;
use std::process::{Command, Stdio};

fn maylang() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_maylang"))
}

fn write(dir: &std::path::Path, name: &str, body: &str) {
    std::fs::write(dir.join(name), body).unwrap();
}

#[cfg(target_os = "linux")]
#[test]
#[ignore = "the historical Rust compiler cannot parse the current strict prelude"]
fn qualified_import_aliases_and_collisions() {
    let dir = std::env::temp_dir().join(format!("maylang_ns_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();

    write(
        &dir,
        "a.may",
        "pub fun square(x) { x * x }\npub fun tag() { \"a\" }\nfun secret() { 1 }\n",
    );
    write(&dir, "b.may", "pub fun square(x) { x * x * x }\npub fun tag() { \"b\" }\n");
    write(
        &dir,
        "main.may",
        "import \"a\" as a;\nimport \"b\" as b;\nprint(a.square(3), b.square(3), a.tag() + b.tag());\n",
    );

    let out = Command::new(maylang())
        .arg("run")
        .arg(dir.join("main.may"))
        .stdin(Stdio::null())
        .output()
        .expect("run maylang");
    assert!(
        out.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&out.stdout).trim(), "9 27 ab");

    // Two plain imports exporting the same name must be an error, not a silent
    // first-definition-wins.
    write(&dir, "clash.may", "import \"a\";\nimport \"b\";\nprint(tag());\n");
    let out = Command::new(maylang())
        .arg("run")
        .arg(dir.join("clash.may"))
        .stdin(Stdio::null())
        .output()
        .expect("run maylang");
    assert!(!out.status.success());
    assert!(
        String::from_utf8_lossy(&out.stderr).contains("disambiguate"),
        "stderr: {}",
        String::from_utf8_lossy(&out.stderr)
    );

    // Accessing a non-`pub` name in a module that uses `pub` is rejected.
    write(&dir, "priv.may", "import \"a\" as a;\nprint(a.secret());\n");
    let out = Command::new(maylang())
        .arg("run")
        .arg(dir.join("priv.may"))
        .stdin(Stdio::null())
        .output()
        .expect("run maylang");
    assert!(!out.status.success());
    assert!(
        String::from_utf8_lossy(&out.stderr).contains("private"),
        "stderr: {}",
        String::from_utf8_lossy(&out.stderr)
    );

    let _ = std::fs::remove_dir_all(&dir);
}
