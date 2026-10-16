use std::{env, path::PathBuf};

fn main() {
    let versatile = env::var_os("CARGO_FEATURE_VERSATILEPB").is_some();
    let blueangel = env::var_os("CARGO_FEATURE_BLUEANGEL").is_some();
    let pxa = env::var_os("CARGO_FEATURE_PXA_REFERENCE").is_some();
    let e2b = env::var_os("CARGO_FEATURE_E2B").is_some();
    assert!(
        usize::from(versatile) + usize::from(blueangel) + usize::from(pxa) + usize::from(e2b) == 1,
        "select exactly one BSP"
    );
    let board = if versatile {
        "versatilepb"
    } else if blueangel {
        "blueangel"
    } else if e2b {
        "e2b"
    } else {
        "pxa-reference"
    };
    let root = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let linker = root.join("link").join(format!("{board}.ld"));
    println!("cargo:rustc-link-arg=-T{}", linker.display());
    println!("cargo:rerun-if-changed={}", linker.display());
    println!("cargo:rerun-if-changed=link/sections.ld");
    println!("cargo:rustc-link-arg=-L{}", root.join("link").display());
}
