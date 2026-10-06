//! Tests for the `maylang check` static-analysis pass.

use std::path::PathBuf;
use std::process::{Command, Stdio};

fn maylang() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_maylang"))
}

#[test]
fn check_reports_definite_errors() {
    let dir = std::env::temp_dir().join(format!("maylang_check_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let file = dir.join("bad.may");
    std::fs::write(
        &file,
        "let x = 1;\nx = 2;\nbreak;\nreturn 3;\nlet n = 5;\nn();\nfun add(a, b) { a + b }\nadd(1);\n",
    )
    .unwrap();

    let out = Command::new(maylang())
        .arg("check")
        .arg(&file)
        .stdin(Stdio::null())
        .output()
        .expect("run maylang check");
    assert!(!out.status.success());
    let err = String::from_utf8_lossy(&out.stderr);
    for needle in [
        "immutable `x`",
        "`break` outside a loop",
        "`return` outside a function",
        "cannot call a value of type `Int`",
        "expects 2 argument(s), got 1",
    ] {
        assert!(err.contains(needle), "missing `{needle}` in:\n{err}");
    }

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn check_parametric_and_generic_types() {
    let dir = std::env::temp_dir().join(format!("maylang_types_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();

    let good = dir.join("good.may");
    std::fs::write(
        &good,
        "fun add(a: Int, b: Int) -> Int { a + b }\n\
         fun head<T>(xs: List<T>) -> T { xs[0] }\n\
         let xs: List<Int> = [1, 2, 3];\n\
         print(add(1, 2), head(xs));\n",
    )
    .unwrap();
    let out = run_check(&good);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));

    let bad = dir.join("bad.may");
    std::fs::write(
        &bad,
        "fun add(a: Int, b: Int) -> Int { a + b }\n\
         fun head<T>(xs: List<T>) -> T { xs[0] }\n\
         print(add(1, \"x\"));\n\
         let ys: List<Int> = [\"a\"];\n\
         print(head(\"no\"));\n",
    )
    .unwrap();
    let out = run_check(&bad);
    assert!(!out.status.success());
    let err = String::from_utf8_lossy(&out.stderr);
    assert!(err.contains("argument 2 type mismatch"), "{err}");
    assert!(err.contains("argument 1 type mismatch"), "{err}");
    assert!(err.contains("initializer type mismatch"), "{err}");

    let _ = std::fs::remove_dir_all(&dir);
}

fn run_check(file: &std::path::Path) -> std::process::Output {
    Command::new(maylang())
        .arg("check")
        .arg(file)
        .stdin(Stdio::null())
        .output()
        .expect("run maylang check")
}

#[test]
fn check_accepts_valid_programs() {
    let file = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../../examples/hello.may");
    let out = Command::new(maylang())
        .arg("check")
        .arg(&file)
        .stdin(Stdio::null())
        .output()
        .expect("run maylang check");
    assert!(
        out.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}
