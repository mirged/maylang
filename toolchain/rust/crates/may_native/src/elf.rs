//! ELF64 executable writer (Linux, x86-64, ET_EXEC).
//!
//! A single `PT_LOAD` segment holds the code and data; `BSS` extends `p_memsz`.
//! After the loadable image we append `.symtab`/`.strtab` and a minimal DWARF
//! v2 `.debug_line` section, then the section-header table.

/// Size of the ELF header plus one program header.
pub const HEADER_SIZE: usize = 64 + 56;

const SHT_PROGBITS: u32 = 1;
const SHT_SYMTAB: u32 = 2;
const SHT_STRTAB: u32 = 3;
const SHT_NOBITS: u32 = 8;
const SHF_ALLOC: u64 = 0x2;
const SHF_EXECINSTR: u64 = 0x4;

fn uleb(out: &mut Vec<u8>, mut v: u64) {
    loop {
        let mut b = (v & 0x7f) as u8;
        v >>= 7;
        if v != 0 {
            b |= 0x80;
        }
        out.push(b);
        if v == 0 {
            break;
        }
    }
}

fn sleb(out: &mut Vec<u8>, mut v: i64) {
    loop {
        let b = (v & 0x7f) as u8;
        v >>= 7;
        let sign = b & 0x40 != 0;
        if (v == 0 && !sign) || (v == -1 && sign) {
            out.push(b);
            break;
        }
        out.push(b | 0x80);
    }
}

/// Build a DWARF v2 `.debug_line` program mapping code offsets to source lines.
fn build_debug_line(code_off: u64, base: u64, lines: &[(usize, u32)]) -> Vec<u8> {
    let rows: Vec<(usize, u32)> = if lines.is_empty() {
        vec![(0, 1)]
    } else {
        lines.to_vec()
    };

    // Line-number program.
    let mut prog = Vec::new();
    let first_addr = base + code_off + rows[0].0 as u64;
    prog.push(0); // DW_LNE_set_address
    uleb(&mut prog, 9);
    prog.push(2);
    prog.extend_from_slice(&first_addr.to_le_bytes());
    prog.push(3); // DW_LNS_advance_line
    sleb(&mut prog, rows[0].1 as i64 - 1);
    prog.push(1); // DW_LNS_copy
    let (mut prev_off, mut prev_line) = rows[0];
    for (off, line) in &rows[1..] {
        prog.push(2); // DW_LNS_advance_pc
        uleb(&mut prog, (*off - prev_off) as u64);
        prog.push(3); // DW_LNS_advance_line
        sleb(&mut prog, *line as i64 - prev_line as i64);
        prog.push(1); // DW_LNS_copy
        prev_off = *off;
        prev_line = *line;
    }
    prog.push(0); // DW_LNE_end_sequence
    uleb(&mut prog, 1);
    prog.push(1);

    // Unit header.
    let mut unit = Vec::new();
    unit.extend_from_slice(&2u16.to_le_bytes()); // version
    let header_len_pos = unit.len();
    unit.extend_from_slice(&0u32.to_le_bytes()); // header_length (patched)
    let header_start = unit.len();
    unit.push(1); // minimum_instruction_length
    unit.push(1); // default_is_stmt
    unit.push(0xfb); // line_base = -5
    unit.push(14); // line_range
    unit.push(13); // opcode_base
    unit.extend_from_slice(&[0, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1]);
    unit.push(0); // include_directories terminator
    unit.extend_from_slice(b"source.may\0");
    unit.push(0); // directory index
    uleb(&mut unit, 0); // mtime
    uleb(&mut unit, 0); // length
    unit.push(0); // file_names terminator
    let header_len = (unit.len() - header_start) as u32;
    unit[header_len_pos..header_len_pos + 4].copy_from_slice(&header_len.to_le_bytes());
    unit.extend_from_slice(&prog);

    let mut out = Vec::new();
    out.extend_from_slice(&(unit.len() as u32).to_le_bytes()); // unit_length
    out.extend_from_slice(&unit);
    out
}

pub fn build(
    base: u64,
    code: &[u8],
    data: &[u8],
    entry_pos: usize,
    bss: usize,
    symbols: &[(String, usize)],
    lines: &[(usize, u32)],
) -> Vec<u8> {
    let code_off = HEADER_SIZE;
    let load_total = code_off + code.len() + data.len();
    let memsz = (load_total + bss) as u64;
    let entry = base + (code_off + entry_pos) as u64;

    // ----- symbol and string tables --------------------------------------
    let mut strtab: Vec<u8> = vec![0];
    let mut syms: Vec<[u8; 24]> = vec![[0u8; 24]];
    for (name, off) in symbols {
        let name_off = strtab.len() as u32;
        strtab.extend_from_slice(name.as_bytes());
        strtab.push(0);
        let mut sym = [0u8; 24];
        sym[0..4].copy_from_slice(&name_off.to_le_bytes());
        sym[4] = 0x12; // STB_GLOBAL | STT_FUNC
        sym[6..8].copy_from_slice(&1u16.to_le_bytes()); // .text
        sym[8..16].copy_from_slice(&(base + code_off as u64 + *off as u64).to_le_bytes());
        syms.push(sym);
    }

    let debug_line = build_debug_line(code_off as u64, base, lines);

    let shstrtab: Vec<u8> = {
        let mut s = vec![0];
        for name in [
            ".text",
            ".data",
            ".bss",
            ".symtab",
            ".strtab",
            ".debug_line",
            ".shstrtab",
        ] {
            s.extend_from_slice(name.as_bytes());
            s.push(0);
        }
        s
    };

    // Trailing (non-loadable) data layout.
    let symtab_off = load_total;
    let symtab_len = syms.len() * 24;
    let strtab_off = symtab_off + symtab_len;
    let debug_line_off = strtab_off + strtab.len();
    let shstrtab_off = debug_line_off + debug_line.len();
    let shoff = shstrtab_off + shstrtab.len();
    let shnum = 8u16;

    let mut file = vec![0u8; HEADER_SIZE];

    file[0..4].copy_from_slice(&[0x7f, b'E', b'L', b'F']);
    file[4] = 2;
    file[5] = 1;
    file[6] = 1;
    file[7] = 0;

    file[16..18].copy_from_slice(&2u16.to_le_bytes()); // ET_EXEC
    file[18..20].copy_from_slice(&62u16.to_le_bytes()); // EM_X86_64
    file[20..24].copy_from_slice(&1u32.to_le_bytes());
    file[24..32].copy_from_slice(&entry.to_le_bytes());
    file[32..40].copy_from_slice(&(64u64).to_le_bytes()); // e_phoff
    file[40..48].copy_from_slice(&(shoff as u64).to_le_bytes()); // e_shoff
    file[48..52].copy_from_slice(&(0u32).to_le_bytes());
    file[52..54].copy_from_slice(&(64u16).to_le_bytes());
    file[54..56].copy_from_slice(&(56u16).to_le_bytes());
    file[56..58].copy_from_slice(&(1u16).to_le_bytes()); // e_phnum
    file[58..60].copy_from_slice(&(64u16).to_le_bytes()); // e_shentsize
    file[60..62].copy_from_slice(&shnum.to_le_bytes());
    file[62..64].copy_from_slice(&7u16.to_le_bytes()); // e_shstrndx = .shstrtab

    let ph = 64;
    file[ph..ph + 4].copy_from_slice(&1u32.to_le_bytes()); // PT_LOAD
    file[ph + 4..ph + 8].copy_from_slice(&7u32.to_le_bytes());
    file[ph + 8..ph + 16].copy_from_slice(&(0u64).to_le_bytes());
    file[ph + 16..ph + 24].copy_from_slice(&base.to_le_bytes());
    file[ph + 24..ph + 32].copy_from_slice(&base.to_le_bytes());
    file[ph + 32..ph + 40].copy_from_slice(&(load_total as u64).to_le_bytes());
    file[ph + 40..ph + 48].copy_from_slice(&memsz.to_le_bytes());
    file[ph + 48..ph + 56].copy_from_slice(&(0x1000u64).to_le_bytes());

    file.extend_from_slice(code);
    file.extend_from_slice(data);
    for sym in &syms {
        file.extend_from_slice(sym);
    }
    file.extend_from_slice(&strtab);
    file.extend_from_slice(&debug_line);
    file.extend_from_slice(&shstrtab);

    let data_off = (code_off + code.len()) as u64;
    let text_addr = base + code_off as u64;
    let sections: [(u32, u64, u64, u64, u64, u64); 8] = [
        (0, 0, 0, 0, 0, 0),
        (
            SHT_PROGBITS,
            SHF_ALLOC | SHF_EXECINSTR,
            text_addr,
            code_off as u64,
            code.len() as u64,
            0,
        ),
        (
            SHT_PROGBITS,
            SHF_ALLOC,
            base + data_off,
            data_off,
            data.len() as u64,
            0,
        ),
        (
            SHT_NOBITS,
            SHF_ALLOC,
            base + data_off + data.len() as u64,
            data_off + data.len() as u64,
            bss as u64,
            0,
        ),
        (
            SHT_SYMTAB,
            0,
            0,
            symtab_off as u64,
            symtab_len as u64,
            (5u64 << 32) | 1, // link = .strtab, info = first global
        ),
        (SHT_STRTAB, 0, 0, strtab_off as u64, strtab.len() as u64, 0),
        (
            SHT_PROGBITS,
            0,
            0,
            debug_line_off as u64,
            debug_line.len() as u64,
            0,
        ),
        (
            SHT_STRTAB,
            0,
            0,
            shstrtab_off as u64,
            shstrtab.len() as u64,
            0,
        ),
    ];
    let names_off: [u32; 8] = [0, 1, 7, 13, 18, 26, 34, 46];

    for (i, (ty, flags, addr, off, size, li)) in sections.iter().enumerate() {
        let mut sh = [0u8; 64];
        sh[0..4].copy_from_slice(&names_off[i].to_le_bytes());
        sh[4..8].copy_from_slice(&ty.to_le_bytes());
        sh[8..16].copy_from_slice(&flags.to_le_bytes());
        sh[16..24].copy_from_slice(&addr.to_le_bytes());
        sh[24..32].copy_from_slice(&off.to_le_bytes());
        sh[32..40].copy_from_slice(&size.to_le_bytes());
        sh[40..44].copy_from_slice(&((li >> 32) as u32).to_le_bytes()); // sh_link
        sh[44..48].copy_from_slice(&((li & 0xffff_ffff) as u32).to_le_bytes()); // sh_info
        sh[48..56].copy_from_slice(&1u64.to_le_bytes());
        sh[56..64].copy_from_slice(&(if *ty == SHT_SYMTAB { 24u64 } else { 0 }).to_le_bytes());
        file.extend_from_slice(&sh);
    }

    file
}
