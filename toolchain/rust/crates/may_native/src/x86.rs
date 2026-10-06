//! A tiny x86-64 machine-code encoder.
//!
//! Only the instructions the Maylang native backend needs are implemented. The
//! encoder targets the System V AMD64 ABI (shared by Linux and macOS user
//! space); the two differ only in syscall numbers and executable container.

pub type Reg = u8;

pub const RAX: Reg = 0;
pub const RCX: Reg = 1;
pub const RDX: Reg = 2;
pub const RBX: Reg = 3;
pub const RSP: Reg = 4;
pub const RBP: Reg = 5;
pub const RSI: Reg = 6;
pub const RDI: Reg = 7;
pub const R8: Reg = 8;
pub const R9: Reg = 9;
pub const R10: Reg = 10;
pub const R11: Reg = 11;
pub const R12: Reg = 12;
pub const R13: Reg = 13;
pub const R14: Reg = 14;
pub const R15: Reg = 15;

/// Condition codes for `jcc` / `setcc`.
pub const CC_O: u8 = 0x0;
pub const CC_NO: u8 = 0x1;
pub const CC_E: u8 = 0x4;
pub const CC_NE: u8 = 0x5;
pub const CC_B: u8 = 0x2;
pub const CC_BE: u8 = 0x6;
pub const CC_A: u8 = 0x7;
pub const CC_AE: u8 = 0x3;
pub const CC_L: u8 = 0xC;
pub const CC_LE: u8 = 0xE;
pub const CC_G: u8 = 0xF;
pub const CC_GE: u8 = 0xD;
pub const CC_S: u8 = 0x8;
pub const CC_NS: u8 = 0x9;

/// Where an absolute 8-byte address fixup points.
#[derive(Debug, Clone)]
pub enum AbsRef {
    /// Offset into the data segment (strings, globals).
    Data(usize),
    /// A named data symbol (resolved once all data is laid out).
    DataSym(String),
    /// Code position (a function symbol).
    Code(usize),
    /// A named function symbol, resolved at finalize.
    CodeSym(String),
}

/// A growing code buffer with labels and deferred address fixups.
pub struct Asm {
    pub code: Vec<u8>,
    pub data: Vec<u8>,
    labels: Vec<Option<usize>>,
    label_fixups: Vec<Vec<usize>>,
    /// (position of imm64, target) resolved at finalize.
    pub abs_fixups: Vec<(usize, AbsRef)>,
    /// (position of rel32 operand, symbol name) for `call`.
    pub call_fixups: Vec<(usize, String)>,
    /// (data offset, symbol name): patch a code address into the data segment.
    pub data_code_fixups: Vec<(usize, String)>,
    /// Name -> offset into the data segment, for late-bound globals.
    pub data_symbols: std::collections::HashMap<String, usize>,
    /// Bytes of demand-zero (BSS) memory appended after the stored data.
    pub bss_size: usize,
    pub symbols: std::collections::HashMap<String, usize>,
    /// (code offset, source line) markers for DWARF `.debug_line`.
    pub lines: Vec<(usize, u32)>,
}

impl Default for Asm {
    fn default() -> Self {
        Self::new()
    }
}

impl Asm {
    pub fn new() -> Self {
        Asm {
            code: Vec::new(),
            data: Vec::new(),
            labels: Vec::new(),
            label_fixups: Vec::new(),
            abs_fixups: Vec::new(),
            call_fixups: Vec::new(),
            data_code_fixups: Vec::new(),
            data_symbols: std::collections::HashMap::new(),
            bss_size: 0,
            symbols: std::collections::HashMap::new(),
            lines: Vec::new(),
        }
    }

    // ----- labels --------------------------------------------------------

    pub fn new_label(&mut self) -> usize {
        self.labels.push(None);
        self.label_fixups.push(Vec::new());
        self.labels.len() - 1
    }

    pub fn here(&self) -> usize {
        self.code.len()
    }

    pub fn bind(&mut self, label: usize) {
        let target = self.code.len();
        self.labels[label] = Some(target);
        for pos in std::mem::take(&mut self.label_fixups[label]) {
            let rel = target as i64 - (pos as i64 + 4);
            self.code[pos..pos + 4].copy_from_slice(&(rel as i32).to_le_bytes());
        }
    }

    // ----- raw emission --------------------------------------------------

    fn byte(&mut self, b: u8) {
        self.code.push(b);
    }

    fn u32(&mut self, v: u32) {
        self.code.extend_from_slice(&v.to_le_bytes());
    }

    fn rex(&mut self, w: bool, reg: u8, index: u8, base: u8) {
        let mut v = 0x40;
        if w {
            v |= 0x08;
        }
        if reg >= 8 {
            v |= 0x04;
        }
        if index >= 8 {
            v |= 0x02;
        }
        if base >= 8 {
            v |= 0x01;
        }
        self.byte(v);
    }

    fn modrm_reg(&mut self, reg: u8, rm: u8) {
        self.byte(0xC0 | ((reg & 7) << 3) | (rm & 7));
    }

    /// Emit a ModRM (+SIB when `base` is RSP/R12) and displacement for
    /// `[base + disp]`. RBP/R13 force a displacement; RSP/R12 require a SIB byte
    /// with no index.
    fn modrm_mem(&mut self, reg: u8, base: u8, disp: i32) {
        let base_low = base & 7;
        let need_sib = base_low == 4; // RSP / R12
        if disp == 0 && base_low != 5 {
            self.byte(((reg & 7) << 3) | if need_sib { 4 } else { base_low });
            if need_sib {
                self.byte(0x24); // scale=0, index=none, base=RSP/R12
            }
        } else if (-128..=127).contains(&disp) {
            self.byte(0x40 | ((reg & 7) << 3) | if need_sib { 4 } else { base_low });
            if need_sib {
                self.byte(0x24);
            }
            self.byte(disp as u8);
        } else {
            self.byte(0x80 | ((reg & 7) << 3) | if need_sib { 4 } else { base_low });
            if need_sib {
                self.byte(0x24);
            }
            self.u32(disp as u32);
        }
    }

    // ----- moves ---------------------------------------------------------

    pub fn mov_reg_imm64(&mut self, reg: Reg, imm: i64) {
        self.rex(true, 0, 0, reg);
        self.byte(0xB8 + (reg & 7));
        self.code.extend_from_slice(&imm.to_le_bytes());
    }

    pub fn mov_reg_reg(&mut self, dst: Reg, src: Reg) {
        self.rex(true, src, 0, dst);
        self.byte(0x89);
        self.modrm_reg(src, dst);
    }

    pub fn mov_reg_mem(&mut self, reg: Reg, base: Reg, disp: i32) {
        self.rex(true, reg, 0, base);
        self.byte(0x8B);
        self.modrm_mem(reg, base, disp);
    }

    pub fn mov_mem_reg(&mut self, base: Reg, disp: i32, reg: Reg) {
        self.rex(true, reg, 0, base);
        self.byte(0x89);
        self.modrm_mem(reg, base, disp);
    }

    pub fn mov_byte_mem_imm(&mut self, base: Reg, disp: i32, imm: u8) {
        self.rex(false, 0, 0, base);
        self.byte(0xC6);
        self.modrm_mem(0, base, disp);
        self.byte(imm);
    }

    pub fn mov_byte_mem_reg(&mut self, base: Reg, disp: i32, reg: Reg) {
        if reg >= 4 || base >= 8 {
            self.rex(false, reg, 0, base);
        }
        self.byte(0x88);
        self.modrm_mem(reg, base, disp);
    }

    pub fn lea(&mut self, reg: Reg, base: Reg, disp: i32) {
        self.rex(true, reg, 0, base);
        self.byte(0x8D);
        self.modrm_mem(reg, base, disp);
    }

    /// `movabs reg, [absolute address]` with a fixup.
    pub fn mov_reg_abs(&mut self, reg: Reg, reference: AbsRef) {
        self.rex(true, 0, 0, reg);
        self.byte(0xB8 + (reg & 7));
        let pos = self.code.len();
        self.code.extend_from_slice(&0i64.to_le_bytes());
        self.abs_fixups.push((pos, reference));
    }

    pub fn mov_reg_mem_abs(&mut self, reg: Reg, addr_reg: Reg) {
        self.rex(true, reg, 0, addr_reg);
        self.byte(0x8B);
        self.modrm_mem(reg, addr_reg, 0);
    }

    pub fn mov_mem_abs_reg(&mut self, addr_reg: Reg, reg: Reg) {
        self.rex(true, reg, 0, addr_reg);
        self.byte(0x89);
        self.modrm_mem(reg, addr_reg, 0);
    }

    // ----- arithmetic / logic -------------------------------------------

    fn alu_rr(&mut self, opcode: u8, dst: Reg, src: Reg) {
        self.rex(true, src, 0, dst);
        self.byte(opcode);
        self.modrm_reg(src, dst);
    }

    pub fn add_rr(&mut self, dst: Reg, src: Reg) {
        self.alu_rr(0x01, dst, src);
    }
    pub fn sub_rr(&mut self, dst: Reg, src: Reg) {
        self.alu_rr(0x29, dst, src);
    }
    pub fn and_rr(&mut self, dst: Reg, src: Reg) {
        self.alu_rr(0x21, dst, src);
    }
    pub fn or_rr(&mut self, dst: Reg, src: Reg) {
        self.alu_rr(0x09, dst, src);
    }
    pub fn xor_rr(&mut self, dst: Reg, src: Reg) {
        self.alu_rr(0x31, dst, src);
    }
    pub fn cmp_rr(&mut self, a: Reg, b: Reg) {
        self.alu_rr(0x39, a, b);
    }
    pub fn test_rr(&mut self, a: Reg, b: Reg) {
        self.alu_rr(0x85, a, b);
    }
    pub fn imul_rr(&mut self, dst: Reg, src: Reg) {
        self.rex(true, dst, 0, src);
        self.byte(0x0F);
        self.byte(0xAF);
        self.modrm_reg(dst, src);
    }

    /// `bsr r64, r64` — index of the highest set bit (undefined for 0).
    pub fn bsr_rr(&mut self, dst: Reg, src: Reg) {
        self.rex(true, dst, 0, src);
        self.byte(0x0F);
        self.byte(0xBD);
        self.modrm_reg(dst, src);
    }

    /// `bt r64, imm8` — test a bit (sets CF).
    pub fn bt_imm(&mut self, reg: Reg, bit: u8) {
        self.rex(true, 0, 0, reg);
        self.byte(0x0F);
        self.byte(0xBA);
        self.modrm_reg(4, reg);
        self.byte(bit);
    }

    pub fn add_imm32(&mut self, reg: Reg, imm: i32) {
        self.rex(true, 0, 0, reg);
        self.byte(0x81);
        self.modrm_reg(0, reg);
        self.u32(imm as u32);
    }

    pub fn sub_imm32(&mut self, reg: Reg, imm: i32) {
        self.rex(true, 0, 0, reg);
        self.byte(0x81);
        self.modrm_reg(5, reg);
        self.u32(imm as u32);
    }

    pub fn cmp_imm32(&mut self, reg: Reg, imm: i32) {
        self.rex(true, 0, 0, reg);
        self.byte(0x81);
        self.modrm_reg(7, reg);
        self.u32(imm as u32);
    }

    fn unary_f7(&mut self, group: u8, reg: Reg) {
        self.rex(true, 0, 0, reg);
        self.byte(0xF7);
        self.modrm_reg(group, reg);
    }

    pub fn neg(&mut self, reg: Reg) {
        self.unary_f7(3, reg);
    }
    pub fn not(&mut self, reg: Reg) {
        self.unary_f7(2, reg);
    }
    pub fn idiv(&mut self, reg: Reg) {
        self.unary_f7(7, reg);
    }
    pub fn div(&mut self, reg: Reg) {
        self.unary_f7(6, reg);
    }
    pub fn cqo(&mut self) {
        self.byte(0x48);
        self.byte(0x99);
    }

    pub fn sar_imm(&mut self, reg: Reg, imm: u8) {
        self.shift_imm(7, reg, imm);
    }
    pub fn shl_imm(&mut self, reg: Reg, imm: u8) {
        self.shift_imm(4, reg, imm);
    }
    pub fn shr_imm(&mut self, reg: Reg, imm: u8) {
        self.shift_imm(5, reg, imm);
    }
    /// `shl r64, cl`.
    pub fn shl_cl(&mut self, reg: Reg) {
        self.rex(true, 0, 0, reg);
        self.byte(0xD3);
        self.modrm_reg(4, reg);
    }
    /// `shr r64, cl`.
    pub fn shr_cl(&mut self, reg: Reg) {
        self.rex(true, 0, 0, reg);
        self.byte(0xD3);
        self.modrm_reg(5, reg);
    }
    fn shift_imm(&mut self, group: u8, reg: Reg, imm: u8) {
        self.rex(true, 0, 0, reg);
        self.byte(0xC1);
        self.modrm_reg(group, reg);
        self.byte(imm);
    }

    pub fn setcc(&mut self, cc: u8, reg: Reg) {
        // REX for byte registers spl/bpl/sil/dil (reg >= 4).
        if reg >= 4 {
            self.rex(false, 0, 0, reg);
        }
        self.byte(0x0F);
        self.byte(0x90 + cc);
        self.modrm_reg(0, reg);
    }

    pub fn movzx_byte(&mut self, dst: Reg, src: Reg) {
        self.rex(true, dst, 0, src);
        self.byte(0x0F);
        self.byte(0xB6);
        self.modrm_reg(dst, src);
    }

    /// `movzx r64, byte [base + disp]`
    pub fn movzx_byte_mem(&mut self, dst: Reg, base: Reg, disp: i32) {
        self.rex(true, dst, 0, base);
        self.byte(0x0F);
        self.byte(0xB6);
        self.modrm_mem(dst, base, disp);
    }

    /// `movzx r64, word [base + disp]`
    pub fn movzx_word_mem(&mut self, dst: Reg, base: Reg, disp: i32) {
        self.rex(false, dst, 0, base);
        self.byte(0x0F);
        self.byte(0xB7);
        self.modrm_mem(dst, base, disp);
    }

    /// `mov r32, [base + disp]` (zero-extends into the 64-bit register).
    pub fn mov32_reg_mem(&mut self, dst: Reg, base: Reg, disp: i32) {
        self.rex(false, dst, 0, base);
        self.byte(0x8B);
        self.modrm_mem(dst, base, disp);
    }

    /// `mov word [base + disp], r16`
    pub fn mov_mem16_reg(&mut self, base: Reg, disp: i32, reg: Reg) {
        self.byte(0x66);
        self.rex(false, reg, 0, base);
        self.byte(0x89);
        self.modrm_mem(reg, base, disp);
    }

    /// `mov dword [base + disp], r32`
    pub fn mov_mem32_reg(&mut self, base: Reg, disp: i32, reg: Reg) {
        self.rex(false, reg, 0, base);
        self.byte(0x89);
        self.modrm_mem(reg, base, disp);
    }

    /// `call reg` (indirect call, used by the C-ABI trampoline).
    pub fn call_reg(&mut self, reg: Reg) {
        self.rex(false, 0, 0, reg);
        self.byte(0xFF);
        self.modrm_reg(2, reg);
    }

    // ----- stack / control ----------------------------------------------

    pub fn push(&mut self, reg: Reg) {
        if reg >= 8 {
            self.rex(false, 0, 0, reg);
        }
        self.byte(0x50 + (reg & 7));
    }

    pub fn pop(&mut self, reg: Reg) {
        if reg >= 8 {
            self.rex(false, 0, 0, reg);
        }
        self.byte(0x58 + (reg & 7));
    }

    pub fn ret(&mut self) {
        self.byte(0xC3);
    }

    pub fn syscall(&mut self) {
        self.byte(0x0F);
        self.byte(0x05);
    }

    // ----- SSE2 (scalar double) -----------------------------------------

    /// Emit a two-byte-prefixed SSE instruction with a Register/Memory operand.
    fn sse(&mut self, prefix: &[u8], opcode: u8, reg: u8, rm: u8) {
        for byte in prefix {
            self.byte(*byte);
        }
        self.rex(false, reg, 0, rm);
        self.byte(0x0F);
        self.byte(opcode);
        self.modrm_reg(reg, rm);
    }

    fn sse_mem(&mut self, prefix: &[u8], opcode: u8, reg: u8, base: Reg, disp: i32) {
        for byte in prefix {
            self.byte(*byte);
        }
        self.rex(false, reg, 0, base);
        self.byte(0x0F);
        self.byte(opcode);
        self.modrm_mem(reg, base, disp);
    }

    pub fn movsd_load(&mut self, xmm: u8, base: Reg, disp: i32) {
        self.sse_mem(&[0xF2], 0x10, xmm, base, disp);
    }
    pub fn movsd_store(&mut self, base: Reg, disp: i32, xmm: u8) {
        self.sse_mem(&[0xF2], 0x11, xmm, base, disp);
    }
    pub fn movsd_rr(&mut self, dst: u8, src: u8) {
        self.sse(&[0xF2], 0x10, dst, src);
    }
    pub fn addsd(&mut self, dst: u8, src: u8) {
        self.sse(&[0xF2], 0x58, dst, src);
    }
    pub fn subsd(&mut self, dst: u8, src: u8) {
        self.sse(&[0xF2], 0x5C, dst, src);
    }
    pub fn mulsd(&mut self, dst: u8, src: u8) {
        self.sse(&[0xF2], 0x59, dst, src);
    }
    pub fn divsd(&mut self, dst: u8, src: u8) {
        self.sse(&[0xF2], 0x5E, dst, src);
    }
    pub fn sqrtsd(&mut self, dst: u8, src: u8) {
        self.sse(&[0xF2], 0x51, dst, src);
    }
    pub fn comisd(&mut self, dst: u8, src: u8) {
        self.sse(&[0x66], 0x2F, dst, src);
    }
    pub fn ucomisd(&mut self, dst: u8, src: u8) {
        self.sse(&[0x66], 0x2E, dst, src);
    }
    pub fn xorpd(&mut self, dst: u8, src: u8) {
        self.sse(&[0x66], 0x57, dst, src);
    }
    pub fn xorps(&mut self, dst: u8, src: u8) {
        self.sse(&[], 0x57, dst, src);
    }
    /// `cvtsi2sd xmm, r64`
    pub fn cvtsi2sd(&mut self, xmm: u8, gpr: Reg) {
        self.byte(0xF2);
        self.rex(true, xmm, 0, gpr);
        self.byte(0x0F);
        self.byte(0x2A);
        self.modrm_reg(xmm, gpr);
    }
    /// `cvttsd2si r64, xmm`
    pub fn cvttsd2si(&mut self, gpr: Reg, xmm: u8) {
        self.byte(0xF2);
        self.rex(true, gpr, 0, xmm);
        self.byte(0x0F);
        self.byte(0x2C);
        self.modrm_reg(gpr, xmm);
    }

    // ----- x87 FPU ------------------------------------------------------
    //
    // The x87 unit gives us hardware transcendental functions (`fsin`,
    // `fcos`, `fyl2x`, `f2xm1`, ...) without linking a libm, which keeps the
    // emitted executables freestanding.

    /// `fld m64fp` — push an IEEE-754 double from memory onto the x87 stack.
    pub fn fldl(&mut self, base: Reg, disp: i32) {
        self.byte(0xDD);
        self.modrm_mem(0, base, disp);
    }

    /// `fstp m64fp` — pop the x87 stack into an IEEE-754 double in memory.
    pub fn fstpl(&mut self, base: Reg, disp: i32) {
        self.byte(0xDD);
        self.modrm_mem(3, base, disp);
    }

    /// `fld st(i)`.
    pub fn fld_st(&mut self, i: u8) {
        self.byte(0xD9);
        self.byte(0xC0 + i);
    }

    /// `fstp st(i)`.
    pub fn fstp_st(&mut self, i: u8) {
        self.byte(0xDD);
        self.byte(0xD8 + i);
    }

    /// `fxch st(i)`.
    pub fn fxch_st(&mut self, i: u8) {
        self.byte(0xD9);
        self.byte(0xC8 + i);
    }

    pub fn fadd_st0_st(&mut self, i: u8) {
        self.byte(0xD8);
        self.byte(0xC0 + i);
    }
    pub fn fmul_st0_st(&mut self, i: u8) {
        self.byte(0xD8);
        self.byte(0xC8 + i);
    }
    pub fn fsub_st0_st(&mut self, i: u8) {
        self.byte(0xD8);
        self.byte(0xE0 + i);
    }
    pub fn fsubr_st0_st(&mut self, i: u8) {
        self.byte(0xD8);
        self.byte(0xE8 + i);
    }
    pub fn fdiv_st0_st(&mut self, i: u8) {
        self.byte(0xD8);
        self.byte(0xF0 + i);
    }

    pub fn faddp_st0_st(&mut self, i: u8) {
        self.byte(0xDE);
        self.byte(0xC0 + i);
    }
    pub fn fmulp_st0_st(&mut self, i: u8) {
        self.byte(0xDE);
        self.byte(0xC8 + i);
    }
    /// `fsubrp st(i), st(0)` — `st(i) = st(0) - st(i)`, then pop.
    pub fn fsubrp_st0_st(&mut self, i: u8) {
        self.byte(0xDE);
        self.byte(0xE0 + i);
    }
    /// `fsubp st(i), st(0)` — `st(i) = st(i) - st(0)`, then pop.
    pub fn fsubp_st0_st(&mut self, i: u8) {
        self.byte(0xDE);
        self.byte(0xE8 + i);
    }
    pub fn fdivp_st0_st(&mut self, i: u8) {
        self.byte(0xDE);
        self.byte(0xF8 + i);
    }
    pub fn fdivrp_st0_st(&mut self, i: u8) {
        self.byte(0xDE);
        self.byte(0xF0 + i);
    }

    /// `fucomip st(0), st(i)` — compare and pop.
    pub fn fucomip_st0_st(&mut self, i: u8) {
        self.byte(0xDF);
        self.byte(0xE8 + i);
    }

    pub fn fld1(&mut self) {
        self.byte(0xD9);
        self.byte(0xE8);
    }
    pub fn fldz(&mut self) {
        self.byte(0xD9);
        self.byte(0xEE);
    }
    pub fn fldpi(&mut self) {
        self.byte(0xD9);
        self.byte(0xEB);
    }
    pub fn fldl2e(&mut self) {
        self.byte(0xD9);
        self.byte(0xEA);
    }
    pub fn fldl2t(&mut self) {
        self.byte(0xD9);
        self.byte(0xE9);
    }
    pub fn fldlg2(&mut self) {
        self.byte(0xD9);
        self.byte(0xEC);
    }
    pub fn fldln2(&mut self) {
        self.byte(0xD9);
        self.byte(0xED);
    }
    pub fn fabs(&mut self) {
        self.byte(0xD9);
        self.byte(0xE1);
    }
    pub fn fchs(&mut self) {
        self.byte(0xD9);
        self.byte(0xE0);
    }
    pub fn fsqrt(&mut self) {
        self.byte(0xD9);
        self.byte(0xFA);
    }
    pub fn fsin(&mut self) {
        self.byte(0xD9);
        self.byte(0xFE);
    }
    pub fn fcos(&mut self) {
        self.byte(0xD9);
        self.byte(0xFF);
    }
    /// `fptan` — `st(0) = tan(st(0))`, then pushes `1.0`.
    pub fn fptan(&mut self) {
        self.byte(0xD9);
        self.byte(0xF2);
    }
    /// `fpatan` — `st(1) = atan2(st(1), st(0))`, then pop.
    pub fn fpatan(&mut self) {
        self.byte(0xD9);
        self.byte(0xF3);
    }
    /// `fyl2x` — `st(1) = st(1) * log2(st(0))`, then pop.
    pub fn fyl2x(&mut self) {
        self.byte(0xD9);
        self.byte(0xF1);
    }
    pub fn fyl2xp1(&mut self) {
        self.byte(0xD9);
        self.byte(0xF9);
    }
    /// `f2xm1` — `st(0) = 2**st(0) - 1` for `|st(0)| <= 1`.
    pub fn f2xm1(&mut self) {
        self.byte(0xD9);
        self.byte(0xF0);
    }
    /// `fscale` — `st(0) = st(0) * 2**trunc(st(1))`.
    pub fn fscale(&mut self) {
        self.byte(0xD9);
        self.byte(0xFD);
    }
    pub fn frndint(&mut self) {
        self.byte(0xD9);
        self.byte(0xFC);
    }
    /// `jmp reg` (computed jump, used by the `may` unwinder).
    pub fn jmp_reg(&mut self, reg: Reg) {
        self.rex(false, 0, 0, reg);
        self.byte(0xFF);
        self.modrm_reg(4, reg);
    }

    /// `sub rsp, imm32`, returning the position of the immediate for patching.
    pub fn sub_rsp_placeholder(&mut self) -> usize {
        self.rex(true, 0, 0, RSP);
        self.byte(0x81);
        self.modrm_reg(5, RSP);
        let pos = self.code.len();
        self.u32(0);
        pos
    }

    pub fn patch_u32(&mut self, pos: usize, value: u32) {
        self.code[pos..pos + 4].copy_from_slice(&value.to_le_bytes());
    }

    pub fn jmp(&mut self, label: usize) {
        self.byte(0xE9);
        let pos = self.code.len();
        self.u32(0);
        self.record_jump(label, pos);
    }

    pub fn jcc(&mut self, cc: u8, label: usize) {
        self.byte(0x0F);
        self.byte(0x80 + cc);
        let pos = self.code.len();
        self.u32(0);
        self.record_jump(label, pos);
    }

    /// Patch a jump immediately when its label is already bound (backward
    /// reference) or defer it until the label binds (forward reference).
    fn record_jump(&mut self, label: usize, pos: usize) {
        if let Some(target) = self.labels[label] {
            let rel = target as i64 - (pos as i64 + 4);
            self.code[pos..pos + 4].copy_from_slice(&(rel as i32).to_le_bytes());
        } else {
            self.label_fixups[label].push(pos);
        }
    }

    pub fn call_sym(&mut self, name: &str) {
        self.byte(0xE8);
        let pos = self.code.len();
        self.u32(0);
        self.call_fixups.push((pos, name.to_string()));
    }

    /// Unconditional jump to a symbol (tail call), resolved at finalize.
    pub fn jmp_sym(&mut self, name: &str) {
        self.byte(0xE9);
        let pos = self.code.len();
        self.u32(0);
        self.call_fixups.push((pos, name.to_string()));
    }

    /// `movabs reg, <code address>` with a placeholder resolved to a later code
    /// position by [`Asm::set_abs_code`].
    pub fn mov_reg_abs_code_placeholder(&mut self, reg: Reg) -> usize {
        self.rex(true, 0, 0, reg);
        self.byte(0xB8 + (reg & 7));
        let pos = self.code.len();
        self.code.extend_from_slice(&0i64.to_le_bytes());
        self.abs_fixups.push((pos, AbsRef::Code(0)));
        pos
    }

    /// Resolve a placeholder emitted by [`Asm::mov_reg_abs_code_placeholder`].
    pub fn set_abs_code(&mut self, immediate: usize, code_pos: usize) {
        for (pos, reference) in self.abs_fixups.iter_mut() {
            if *pos == immediate {
                *reference = AbsRef::Code(code_pos);
            }
        }
    }

    // ----- symbols & data -------------------------------------------------

    pub fn bind_symbol(&mut self, name: &str) {
        self.symbols.insert(name.to_string(), self.code.len());
    }

    /// Record that subsequent code corresponds to `line` (for debug info).
    pub fn mark_line(&mut self, line: u32) {
        if line == 0 {
            return;
        }
        if self.lines.last().map(|(_, l)| *l) == Some(line) {
            return;
        }
        self.lines.push((self.code.len(), line));
    }

    /// Pad the data segment to an 8-byte boundary (keeps pointer tags valid).
    fn align_data(&mut self) {
        while !self.data.len().is_multiple_of(8) {
            self.data.push(0);
        }
    }

    /// Intern bytes in the data segment, prefixed with an 8-byte length.
    /// Returns the offset of the length field (used as a tagged string ptr).
    pub fn intern(&mut self, bytes: &[u8]) -> usize {
        self.align_data();
        let offset = self.data.len();
        self.data
            .extend_from_slice(&(bytes.len() as u64).to_le_bytes());
        self.data.extend_from_slice(bytes);
        offset
    }

    /// Intern raw bytes (no length prefix), 8-byte aligned.
    pub fn intern_raw(&mut self, bytes: &[u8]) -> usize {
        self.align_data();
        let offset = self.data.len();
        self.data.extend_from_slice(bytes);
        offset
    }

    /// Reserve an 8-byte zero-initialised global slot.
    pub fn alloc_global(&mut self) -> usize {
        self.align_data();
        let offset = self.data.len();
        self.data.extend_from_slice(&0u64.to_le_bytes());
        offset
    }

    /// Intern a first-class function object: `{ magic, code, 0 }`.
    pub fn alloc_function_value(&mut self, symbol: &str) -> usize {
        self.align_data();
        let offset = self.data.len();
        self.data.extend_from_slice(&u64::MAX.to_le_bytes());
        self.data.extend_from_slice(&0u64.to_le_bytes()); // code address
        self.data.extend_from_slice(&0u64.to_le_bytes());
        self.data_code_fixups.push((offset + 8, symbol.to_string()));
        offset
    }

    /// Reserve `n` zero bytes in the stored data segment on an 8-byte boundary
    /// (used for scratch regions such as the saved-register block).
    pub fn reserve_zeros(&mut self, n: usize) -> usize {
        self.align_data();
        let offset = self.data.len();
        self.data.resize(self.data.len() + n, 0);
        offset
    }

    /// Reserve `n` bytes of demand-zero memory appended after the stored data
    /// (not written to the executable file). Must be called after all data has
    /// been interned.
    pub fn reserve_bss(&mut self, n: usize) -> usize {
        self.align_data();
        let offset = self.data.len() + self.bss_size;
        self.bss_size += n;
        offset
    }

    /// Bind a data offset to a name so fixups can reference it before all data
    /// has been laid out.
    pub fn bind_data_symbol(&mut self, name: &str, offset: usize) {
        self.data_symbols.insert(name.to_string(), offset);
    }
}
