//! AArch64 (ARM64) backend scaffold.
//!
//! This provides the pieces Phase 7 needs — an instruction encoder, an
//! AArch64 ELF64 writer, and a hand-assembled `_start` — and emits a working
//! "Hello, aarch64" ELF (`EM_AARCH64`). It is verified structurally (ELF
//! header, machine type, instruction encodings); it cannot be executed in this
//! environment because no AArch64 emulator/host is available. Porting the full
//! code generator and runtime to AArch64 is the remaining work.

/// ELF header (64) + one program header (56).
const HEADER_SIZE: usize = 64 + 56;
const EM_AARCH64: u16 = 183;
const BASE: u64 = 0x40_0000;

// Linux AArch64 syscall numbers.
const SYS_WRITE: u64 = 64;
const SYS_EXIT: u64 = 93;

fn movz(rd: u32, imm: u16, shift: u32) -> u32 {
    0xD280_0000 | ((shift / 16) << 21) | ((imm as u32) << 5) | rd
}

fn movk(rd: u32, imm: u16, shift: u32) -> u32 {
    0xF280_0000 | ((shift / 16) << 21) | ((imm as u32) << 5) | rd
}

fn svc0() -> u32 {
    0xD400_0001
}

/// `movz`+3×`movk`, setting a 64-bit immediate.
fn mov_imm64(rd: u32, val: u64) -> Vec<u32> {
    vec![
        movz(rd, val as u16, 0),
        movk(rd, (val >> 16) as u16, 16),
        movk(rd, (val >> 32) as u16, 32),
        movk(rd, (val >> 48) as u16, 48),
    ]
}

/// Emit an AArch64 ELF that writes `Hello, aarch64\n` and exits.
pub fn build_hello() -> Vec<u8> {
    let msg = b"Hello, aarch64\n";

    // Instruction count is fixed, so the message address is known up front.
    let insn_count = 1 + 4 + 1 + 1 + 1 + 1 + 1 + 1; // 11
    let code_off = HEADER_SIZE;
    let msg_off = code_off + insn_count * 4;
    let msg_addr = BASE + msg_off as u64;

    let mut ins: Vec<u32> = Vec::new();
    ins.push(movz(0, 1, 0)); // x0 = fd 1
    ins.extend(mov_imm64(1, msg_addr)); // x1 = message
    ins.push(movz(2, msg.len() as u16, 0)); // x2 = length
    ins.push(movz(8, SYS_WRITE as u16, 0));
    ins.push(svc0());
    ins.push(movz(0, 0, 0));
    ins.push(movz(8, SYS_EXIT as u16, 0));
    ins.push(svc0());

    let mut code = Vec::with_capacity(ins.len() * 4);
    for i in ins {
        code.extend_from_slice(&i.to_le_bytes());
    }

    let total = msg_off + msg.len();
    let entry = BASE + code_off as u64;

    let mut file = vec![0u8; HEADER_SIZE];
    file[0..4].copy_from_slice(&[0x7f, b'E', b'L', b'F']);
    file[4] = 2; // ELFCLASS64
    file[5] = 1; // little-endian
    file[6] = 1;
    file[7] = 0;
    file[16..18].copy_from_slice(&2u16.to_le_bytes()); // ET_EXEC
    file[18..20].copy_from_slice(&EM_AARCH64.to_le_bytes());
    file[20..24].copy_from_slice(&1u32.to_le_bytes());
    file[24..32].copy_from_slice(&entry.to_le_bytes()); // e_entry
    file[32..40].copy_from_slice(&(64u64).to_le_bytes()); // e_phoff
    file[52..54].copy_from_slice(&(64u16).to_le_bytes());
    file[54..56].copy_from_slice(&(56u16).to_le_bytes());
    file[56..58].copy_from_slice(&(1u16).to_le_bytes()); // e_phnum

    let ph = 64;
    file[ph..ph + 4].copy_from_slice(&1u32.to_le_bytes()); // PT_LOAD
    file[ph + 4..ph + 8].copy_from_slice(&7u32.to_le_bytes()); // R|W|X
    file[ph + 8..ph + 16].copy_from_slice(&(0u64).to_le_bytes());
    file[ph + 16..ph + 24].copy_from_slice(&BASE.to_le_bytes());
    file[ph + 24..ph + 32].copy_from_slice(&BASE.to_le_bytes());
    file[ph + 32..ph + 40].copy_from_slice(&(total as u64).to_le_bytes());
    file[ph + 40..ph + 48].copy_from_slice(&(total as u64).to_le_bytes());
    file[ph + 48..ph + 56].copy_from_slice(&(0x1000u64).to_le_bytes());

    file.extend_from_slice(&code);
    file.extend_from_slice(msg);
    file
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn instructions_encode_as_expected() {
        assert_eq!(movz(0, 1, 0), 0xD280_0020); // mov x0, #1
        assert_eq!(svc0(), 0xD400_0001); // svc #0
        assert_eq!(movk(1, 0, 16), 0xF2A0_0001); // movk x1, #0, lsl #16
    }

    #[test]
    fn hello_elf_has_aarch64_machine() {
        let img = build_hello();
        assert_eq!(&img[0..4], b"\x7fELF");
        assert_eq!(u16::from_le_bytes(img[18..20].try_into().unwrap()), EM_AARCH64);
        assert_eq!(u16::from_le_bytes(img[16..18].try_into().unwrap()), 2); // ET_EXEC
    }
}
