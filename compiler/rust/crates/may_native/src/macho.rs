//! Mach-O 64 executable writer (macOS, x86-64, MH_EXECUTE, `LC_MAIN`).
//!
//! The layout is a single `__TEXT` segment containing one `__text` section.
//! Entry is declared with `LC_MAIN`, so the kernel jumps straight to `_start`.

/// mach_header_64 (32) + LC_SEGMENT_64 (72) + section_64 (80) + LC_MAIN (24).
pub const HEADER_SIZE: usize = 32 + 72 + 80 + 24;

const LC_SEGMENT_64: u32 = 0x19;
const LC_MAIN: u32 = 0x8000_0028;
const MH_EXECUTE: u32 = 2;
const CPU_TYPE_X86_64: i32 = 0x0100_0007;
const CPU_SUBTYPE_X86_64_ALL: i32 = 3;
const S_ATTR_PURE_INSTRUCTIONS: u32 = 0x8000_0000;
const S_ATTR_SOME_INSTRUCTIONS: u32 = 0x0000_0400;

fn name16(name: &str) -> [u8; 16] {
    let mut out = [0u8; 16];
    let bytes = name.as_bytes();
    let n = bytes.len().min(16);
    out[..n].copy_from_slice(&bytes[..n]);
    out
}

pub fn build(base: u64, code: &[u8], data: &[u8], entry_pos: usize, bss: usize) -> Vec<u8> {
    let code_off = HEADER_SIZE;
    let total = code_off + code.len() + data.len();
    let vmsize = (((total + bss) as u64) + 0xfff) & !0xfff;

    let mut out = Vec::with_capacity(total);

    // --- mach_header_64 ---
    out.extend_from_slice(&0xFEED_FACFu32.to_le_bytes()); // magic
    out.extend_from_slice(&CPU_TYPE_X86_64.to_le_bytes());
    out.extend_from_slice(&CPU_SUBTYPE_X86_64_ALL.to_le_bytes());
    out.extend_from_slice(&MH_EXECUTE.to_le_bytes());
    out.extend_from_slice(&2u32.to_le_bytes()); // ncmds
    out.extend_from_slice(&176u32.to_le_bytes()); // sizeofcmds
    out.extend_from_slice(&0u32.to_le_bytes()); // flags
    out.extend_from_slice(&0u32.to_le_bytes()); // reserved

    // --- LC_SEGMENT_64 ---
    out.extend_from_slice(&LC_SEGMENT_64.to_le_bytes());
    out.extend_from_slice(&72u32.to_le_bytes());
    out.extend_from_slice(&name16("__TEXT"));
    out.extend_from_slice(&base.to_le_bytes()); // vmaddr
    out.extend_from_slice(&vmsize.to_le_bytes()); // vmsize
    out.extend_from_slice(&0u64.to_le_bytes()); // fileoff
    out.extend_from_slice(&(total as u64).to_le_bytes()); // filesize
    out.extend_from_slice(&7i32.to_le_bytes()); // maxprot
    out.extend_from_slice(&7i32.to_le_bytes()); // initprot (writable: globals live here)
    out.extend_from_slice(&1u32.to_le_bytes()); // nsects
    out.extend_from_slice(&0u32.to_le_bytes()); // flags

    // --- section_64 __text ---
    out.extend_from_slice(&name16("__text"));
    out.extend_from_slice(&name16("__TEXT"));
    out.extend_from_slice(&(base + code_off as u64).to_le_bytes()); // addr
    out.extend_from_slice(&(code.len() as u64).to_le_bytes()); // size
    out.extend_from_slice(&(code_off as u32).to_le_bytes()); // offset
    out.extend_from_slice(&4u32.to_le_bytes()); // align
    out.extend_from_slice(&0u32.to_le_bytes()); // reloff
    out.extend_from_slice(&0u32.to_le_bytes()); // nreloc
    out.extend_from_slice(&(S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS).to_le_bytes());
    out.extend_from_slice(&0u32.to_le_bytes()); // reserved1
    out.extend_from_slice(&0u32.to_le_bytes()); // reserved2
    out.extend_from_slice(&0u32.to_le_bytes()); // reserved3

    // --- LC_MAIN ---
    out.extend_from_slice(&LC_MAIN.to_le_bytes());
    out.extend_from_slice(&24u32.to_le_bytes());
    out.extend_from_slice(&((code_off + entry_pos) as u64).to_le_bytes()); // entryoff
    out.extend_from_slice(&0u64.to_le_bytes()); // stacksize

    debug_assert_eq!(out.len(), HEADER_SIZE);

    out.extend_from_slice(code);
    out.extend_from_slice(data);
    out
}
