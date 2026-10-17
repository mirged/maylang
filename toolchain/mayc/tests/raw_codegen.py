#!/usr/bin/env python3
"""Linux x86-64 RAW correctness and semantic disassembly regressions (#76)."""
import argparse
from pathlib import Path
import random
import re
import signal
import subprocess
import tempfile

from backends import compiler_binary, compile_source
from raw_performance import CHECKSUMS, parse_output

HERE = Path(__file__).resolve().parent


def run(binary, status=0):
    result = subprocess.run([str(binary)], capture_output=True, timeout=15)
    assert result.returncode == status, result
    return result.stdout.decode()


def disassemble(binary):
    return subprocess.check_output(['objdump', '-d', '-Mintel', '--no-show-raw-insn', str(binary)], text=True)


def function(assembly, name):
    match = re.search(r'<module0::' + name + r'>:\n(.*?\bret\b)', assembly, re.S)
    assert match, name
    return match[1]


def call_arguments(compiler, work):
    source, binary = work / 'calls.may', work / 'calls'
    declarations, checks = [], []
    for count in range(11):
        parameters = ', '.join(f'a{i}: Any' for i in range(count))
        expression = ' + '.join(f'a{i} * {i + 1}' for i in range(count)) or '17'
        arguments = ', '.join(f'bias + {i + 1}' for i in range(count))
        expected = sum((i + 4) * (i + 1) for i in range(count)) if count else 17
        declarations += [f'fun weighted{count}({parameters}) -> Any {{ return {expression}; }}',
                         f'fun caller{count}(bias: Any) -> Any {{ return weighted{count}({arguments}); }}']
        checks.append(f'if caller{count}(3) != {expected} {{ exit(30); }}')
    declarations += [
        'mut order: Any = 0;',
        'fun record(n: Any) -> Any { order = order * 10 + n; return n; }',
        'fun missing(a: Any, b: Any, c: Any, d: Any, e: Any, f: Any, g: Any, h: Any) -> Any { return g == nil and h == nil; }',
        'fun recurse(n: Any) -> Any { if n == 0 { return 0; } return 1 + recurse(n - 1); }']
    checks += ['if weighted1(record(1), record(2)) != 1 or order != 12 { exit(31); }',
               'if not missing(1, 2, 3, 4, 5, 6) { exit(32); }',
               'if recurse(30) != 30 { exit(33); }', 'exit(0);']
    source.write_text('\n'.join(declarations + checks))
    for options in [('--raw', '--legacy'), ('--legacy',)]:
        compile_source(compiler, source, binary, *options)
        run(binary)
        if '--raw' not in options:
            continue
        assembly = disassemble(binary)
        for count in range(11):
            body = function(assembly, f'caller{count}')
            # The first six arguments enter the ABI body without a stack
            # trampoline; overflow arguments alone use actual ABI stack slots.
            assert len(re.findall(r'\bpush\s+rax\b', body)) == max(count - 6, 0), body
            assert not re.search(r'\bpop\s+rax\b', body), body
            assert re.search(r'\bcall\s+[^\n]*<module0::weighted' + str(count) + '>', body), body
    print('PASS raw/tagged calls with 0..10 arguments, direct body entry, padding, extra-argument effects and recursion', flush=True)


def address_arguments(compiler, work):
    source, binary = work / 'addresses.may', work / 'addresses'
    source.write_text('fun emit() -> Any { return syscall(1, 1, addr("Hello, world!\\n"), 14); }\n'
                      'if len("a\\nb") != 3 { exit(40); }\n'
                      'if load8(cstr("A")) != 65 { exit(41); }\n'
                      'fun offset() -> Any { return 1 + addr("ABC"); }\n'
                      'if load8(offset()) != 66 { exit(42); }\n'
                      'emit();\n')
    compile_source(compiler, source, binary, '--raw', '--legacy')
    assert run(binary) == 'Hello, world!\n'
    assembly = disassemble(binary)
    body = function(assembly, 'emit')
    assert not re.search(r'\b(?:r1[2-5]|movabs)\b|\b(?:push|pop)\s+rax\b', body), body
    assert re.search(r'\bmov\s+esi,0x[0-9a-f]+', body), body
    # The source literal is consumed as metadata; store only one NUL-terminated
    # copy and emit no discarded pointer definition or callee-save register.
    assert binary.read_bytes().count(b'Hello, world!\n\0') == 1
    for name in ['addr', 'cstr', 'len']:
        source.write_text(f'fun {name}(s: Any) -> Any {{ return load8(s); }}\n'
                          f'if {name}("Q") != 81 {{ exit(43); }}\nexit(0);\n')
        compile_source(compiler, source, binary, '--raw')
        run(binary)
    print('PASS direct compact address operands, literal metadata liveness, single data copy and builtin shadowing', flush=True)


def dead_expressions(compiler, work):
    source, binary = work / 'dead.may', work / 'dead'
    source.write_text('mut seen: Any = 0;\nfun effect(n: Any) -> Any { seen = seen * 10 + n; return n; }\nfun unused(a: Any) -> Any { (a + 3) * (a - 7); not a; a < 8; return 17; }\nfun effects() -> Any { (effect(1) + effect(2)) * 17; return seen; }\nif unused(9) != 17 or effects() != 12 { exit(44); }\nexit(0);\n')
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    body = function(disassemble(binary), 'unused')
    assert not re.search(r'\b(?:r1[2-5])\b', body), body
    assert not re.search(r'\b(?:add|sub|imul|cmp|neg|test)\s+(?:rax|rcx|rdx|eax)\b|\bset\w+\b', body), body
    for expression, status in [('(1 / 0 + 3) * 7', -signal.SIGFPE),
                               ('(load64(0) + 3) * 7', -signal.SIGSEGV)]:
        source.write_text(expression + ';\nexit(0);')
        compile_source(compiler, source, binary, '--raw')
        run(binary, status)
    print('PASS cascading raw dead expressions, removed callee-save registers, retained calls and nested faults', flush=True)


def raw_integer(n):
    # Source literals use the compiler's tagged range; expressions can construct
    # every raw 64-bit pattern, including INT64_MIN and INT64_MAX.
    high, low = divmod(n, 1 << 32)
    return f'({high} * 4294967296 + {low})'


def remainder_branches(compiler, work):
    source, binary = work / 'remainder-branches.may', work / 'remainder-branches'
    declarations, checks, names = [], [], []
    rng = random.Random(76)
    inputs = [-(1 << 63), (1 << 63) - 1, -4097, -128, -3, -2, -1, 0, 1, 2, 3, 128, 4097]
    inputs += [rng.randrange(-(1 << 63), 1 << 63) for _ in range(20)]
    for shift in [0, 1, 2, 7, 16, 30]:
        divisor = 1 << shift
        for op in ['==', '!=']:
            for reversed in [False, True]:
                name = f'branch{len(names)}'
                names.append(name)
                comparison = f'0 {op} n % {divisor}' if reversed else f'n % {divisor} {op} 0'
                declarations.append(f'fun {name}(n: Any) -> Any {{ if {comparison} {{ return 7; }} else {{ return 3; }} }}')
                for n in inputs:
                    divisible = n % divisor == 0
                    expected = 7 if divisible == (op == '==') else 3
                    checks.append(f'if {name}({raw_integer(n)}) != {expected} {{ exit(48); }}')
    declarations += ['fun observed_remainder(n: Any) -> Any { let r: Any = n % 8; if r == 0 { return r + 7; } return r; }',
                     'fun nonzero(n: Any) -> Any { if n % 8 == 1 { return 7; } return 3; }',
                     'fun other_divisor(n: Any) -> Any { if n % 3 == 0 { return 7; } return 3; }',
                     'fun effects(p: Any) -> Any { if load64(p) % 8 == 0 { return 7; } return 3; }']
    checks += ['if observed_remainder(-9) != -1 or observed_remainder(-8) != 7 { exit(49); }',
               'if nonzero(-7) != 3 or nonzero(9) != 7 or other_divisor(-9) != 7 { exit(50); }',
               'let p: Any = syscall(9, 0, 4096, 3, 34, -1, 0); store64(p, -8); if effects(p) != 7 { exit(51); }',
               'exit(0);']
    source.write_text('\n'.join(declarations + checks))
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    assembly = disassemble(binary)
    for name in names:
        body = function(assembly, name)
        assert re.search(r'\btest\s+rax,0x[0-9a-f]+', body), body
        assert not re.search(r'\b(?:sar|shr|and|idiv|set\w+)\b', body), body
    for name in ['observed_remainder', 'nonzero']:
        assert re.search(r'\bsar\b', function(assembly, name)), name
    source.write_text('if load64(0) % 8 == 0 { exit(0); } exit(1);')
    compile_source(compiler, source, binary, '--raw')
    run(binary, -signal.SIGSEGV)
    print(f'PASS {len(names) * len(inputs)} full-width signed divisibility branches, reversed operands, observed remainders and retained load faults', flush=True)


def reciprocal_oracle():
    # Independent arbitrary-precision model of the sufficient reciprocal error
    # bound. Exhaust every signed dividend/non-power divisor at small widths.
    for width in range(3, 11):
        limit = 1 << (width - 1)
        for divisor in range(3, limit):
            if divisor & (divisor - 1) == 0:
                continue
            shift = 0
            while True:
                numerator = 1 << (width + shift)
                magic = (numerator + divisor - 1) // divisor
                if magic * divisor - numerator <= 1 << (shift + 1):
                    break
                shift += 1
            assert magic < 1 << width
            encoded = magic if magic < limit else magic - (1 << width)
            for n in range(-limit, limit):
                high = (n * encoded) >> width
                if encoded < 0:
                    high += n
                quotient = (high >> shift) + (n < 0)
                expected = abs(n) // divisor * (-1 if n < 0 else 1)
                assert quotient == expected, (width, divisor, n, magic, shift)
    print('PASS exhaustive signed reciprocal model for widths 3 through 10', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True)
    args = parser.parse_args()
    compiler = compiler_binary(args.compiler)
    reciprocal_oracle()
    with tempfile.TemporaryDirectory(prefix='mayc-raw-codegen-') as directory:
        work = Path(directory)
        source, binary = work / 'test.may', work / 'test'
        source.write_text('''
mut sequence: Any = 0;
fun step(n: Any) -> Any { sequence = sequence * 10 + n; return n; }
fun snapshot() -> Any { let before: Any = sequence; return sequence + step(1) - before; }
fun pure(a: Any, b: Any) -> Any { return (a + b) * (a - b); }
fun immediate(a: Any) -> Any { return (a + 7) * 73 - 129; }
fun wide(a: Any) -> Any { return (a + 4294967295) * 4294967296 - 4294967297; }
fun bounded(p: Any) -> Any { return (load8(p) + load8(p + 1) + load8(p + 2)) % 2; }
fun halve(p: Any) -> Any { return load32(p) / 8; }
fun wrapped(p: Any) -> Any { return (1152921504606846975 * 16 + load8(p)) % 2; }
fun pressure(a: Any, b: Any) -> Any {
    return a + (b * (a + (b * (a + (b * (a + (b * (a + b))))))));
}
fun spilled(a: Any, b: Any) -> Any { return b + if a < b { a } else { b }; }
fun stores(p: Any, n: Any) -> Any {
    store8(p, n); store16(p + 2, n); store32(p + 4, n); store64(p + 8, n);
    return load8(p) + load16(p + 2) + load32(p + 4) + load64(p + 8);
}
fun statement(a: Any, b: Any) -> Any {
    mut total: Any = 0;
    if a < b { total = total + 7; }
    if a >= b { total = total + 13; }
    return total;
}
fun reused(a: Any, b: Any) -> Any {
    let flag: Any = a < b;
    mut n: Any = flag + 7;
    if flag { n = n + flag; }
    return n;
}
if pure(7, 3) != 40 { exit(1); }
if immediate(-2) != 236 { exit(1); }
if wide(3) != 4294967295 { exit(1); }
if pressure(2, 3) != 485 { exit(2); }
if spilled(2, 3) != 5 or spilled(7, 3) != 6 { exit(2); }
if (step(1) + step(2)) * (step(3) - step(4)) != -3 { exit(3); }
if sequence != 1234 { exit(4); }
let p: Any = syscall(9, 0, 4096, 3, 34, -1, 0);
if p < 0 { exit(5); }
store8(p, 1); store8(p + 1, 2); store8(p + 2, 4);
if bounded(p) != 1 or halve(p) != 32832 or wrapped(p) != -1 { exit(5); }
if stores(p, 4294967297) != 4294967300 { exit(6); }
store64(p + step(5), step(6));
if sequence != 123456 or load64(p + 5) != 6 { exit(7); }
// Syscalls clobber rcx/r11; pending operands must survive in allocated homes.
if 7 + syscall(39) <= 7 { exit(8); }
mut i: Any = 0; mut sum: Any = 0; mut swapped: Any = 1;
while i < 40 {
    if i % 2 == 0 { sum = sum + pure(i, 1); }
    else { sum = sum - pure(i, 2); }
    let old: Any = swapped; swapped = sum; sum = sum + old;
    i = i + 1;
}
if sum != 487512880 or swapped != 301298131 { exit(9); }
if statement(-1, 1) != 7 or statement(2, 1) != 13 { exit(10); }
if reused(-1, 1) != 9 or reused(2, 1) != 7 { exit(11); }
''')
        operations = {'eq': '==', 'ne': '!=', 'lt': '<', 'le': '<=', 'gt': '>', 'ge': '>='}
        checks = []
        for name, op in operations.items():
            checks += [f'fun branch_{name}(a: Any, b: Any) -> Any {{ if a {op} b {{ return 1; }} else {{ return 0; }} }}',
                       f'fun value_{name}(a: Any, b: Any) -> Any {{ return a {op} b; }}']
            for a, b in [(-7, 3), (3, -7), (0, 0), (-7, -7), (3, 3)]:
                expected = int(eval(f'{a} {op} {b}'))
                checks += [f'if branch_{name}({a}, {b}) != {expected} {{ exit(12); }}',
                           f'if value_{name}({a}, {b}) != {expected} {{ exit(13); }}']
        checks += ['if step(7) < step(8) { if step(9) != 9 { exit(14); } } else { exit(15); }',
                   'if sequence != 123456789 { exit(16); }',
                   'if false and step(1) == 1 { exit(17); }',
                   'if true or step(2) == 2 {} else { exit(18); }',
                   'if sequence != 123456789 { exit(19); }', 'if snapshot() != 1 { exit(20); }', 'exit(0);']
        source.write_text(source.read_text() + '\n'.join(checks))
        compile_source(compiler, source, binary, '--raw')
        run(binary)
        assembly = disassemble(binary)
        for name in ['pure', 'pressure', 'spilled', 'stores', 'statement', *('branch_' + n for n in operations)]:
            body = function(assembly, name)
            assert not re.search(r'\b(?:push|pop)\s+rax\b', body), (name, body)
            if name == 'statement' or name.startswith('branch_'):
                assert not re.search(r'\b(?:set\w+|movzx|test)\b', body), (name, body)
                assert re.search(r'\bcmp\b[^\n]*\n[^\n]*\bj(?:e|ne|l|le|g|ge)\b', body), (name, body)
        assert re.search(r'\badd\s+rax,QWORD PTR \[rbp-', function(assembly, 'spilled'))
        assert re.search(r'\badd\s+rax,QWORD PTR \[rbp-', function(assembly, 'pure'))
        immediate = function(assembly, 'immediate')
        assert re.search(r'\badd\s+rax,0x7\b', immediate)
        assert re.search(r'\bimul\s+rax,rax,0x49\b', immediate)
        assert re.search(r'\bsub\s+rax,0x81\b', immediate)
        assert not re.search(r'\bmov\s+(r1[2-5]),rax\s*\n[^\n]*\bmov\s+rax,\1\b', immediate), immediate
        assert not re.search(r'\bmov\s+r1[2-5],rax\b', immediate), immediate
        assert re.search(r'\b(?:add|imul|sub)\s+rax,r11\b', function(assembly, 'wide'))
        bounded = function(assembly, 'bounded')
        assert re.search(r'\band\s+rax,0x1\b', bounded) and not re.search(r'\bsar\b', bounded), bounded
        assert re.search(r'\bshr\s+rax,0x3\b', function(assembly, 'halve'))
        assert re.search(r'\bsar\s+rcx,0x3f\b', function(assembly, 'wrapped'))
        for name in operations:
            assert re.search(r'\bset\w+\b', function(assembly, 'value_' + name))
        assert re.search(r'\bsetl\b', function(assembly, 'reused'))
        print('PASS register/spill operands, stores, loop backedges, calls/syscalls, evaluation order and comparison fusion', flush=True)

        # Deterministic full-width signed arithmetic oracle. This covers the
        # power-of-two/reciprocal fast paths and hardware division fallback.
        rng = random.Random(76)
        dividends = [-(1 << 63), -(1 << 63) + 1, (1 << 63) - 1, (1 << 63) - 2,
                     -4294967296, -2147483649, -2147483648, -1, 0, 1,
                     2147483647, 2147483648, 4294967295, 4294967296]
        dividends += [rng.randrange(-(1 << 63), 1 << 63) for _ in range(40)]
        divisors = [1, 2, 4, 8, 256, 1024, 1073741824, 2147483648,
                    3, 7, 13, 17, 2147483647, 1000000007, -1, -2, -7, -2147483648]
        divisors += [(1 << bit) + delta for bit in (15, 31, 32, 40, 50, 59) for delta in (-1, 1)]
        divisors += [(1 << 59), (1 << 60) - 1]
        divisors += [rng.randrange(3, 1 << 60) for _ in range(8)]
        declarations, calls = [], []
        for index, d in enumerate(divisors):
            declarations.append(f'fun check{index}(n: Any, q: Any, r: Any) -> Any {{ '
                                f'if n / {d} != q {{ exit(21); }} '
                                f'if n % {d} != r {{ exit(22); }} return 0; }}')
            values = set(dividends)
            for multiple in (-3, -1, 1, 3, ((1 << 63) - 1) // abs(d)):
                for delta in (-1, 0, 1):
                    n = multiple * abs(d) + delta
                    if -(1 << 63) <= n < 1 << 63:
                        values.add(n)
            for n in sorted(values):
                if n == -(1 << 63) and d == -1:
                    continue  # x86 idiv overflow traps, tested separately below.
                q = abs(n) // abs(d) * (-1 if (n < 0) != (d < 0) else 1)
                r = n - q * d
                calls.append(f'check{index}({raw_integer(n)}, {raw_integer(q)}, {raw_integer(r)});')
        seen = set()
        # Keep compiler memory bounded while growing the arithmetic oracle.
        for offset in range(0, len(calls), 512):
            source.write_text('\n'.join(declarations + calls[offset:offset + 512] + ['exit(0);']))
            compile_source(compiler, source, binary, '--raw')
            run(binary)
            assembly = disassemble(binary)
            for index, divisor in enumerate(divisors):
                if f'<module0::check{index}>:' not in assembly:
                    continue
                seen.add(index)
                body = function(assembly, f'check{index}')
                if divisor > 0 and divisor & (divisor - 1):
                    assert not re.search(r'\bidiv\b', body), (divisor, body)
                    assert re.search(r'\bimul\s+rdx\b', body), (divisor, body)
                elif divisor < 0 or divisor > 1 << 30:
                    assert re.search(r'\bidiv\b', body), (divisor, body)
        assert seen == set(range(len(divisors)))
        sweeps = []
        for divisor in range(3, 64):
            if divisor & (divisor - 1) == 0:
                continue
            checksum = 0
            for n in range(-4097, 4098):
                quotient = abs(n) // divisor * (-1 if n < 0 else 1)
                checksum += quotient * (n + 5000) + (n - quotient * divisor) * (n + 6000)
            sweeps.append(f'fun sweep{divisor}() -> Any {{ mut checksum: Any = 0; mut n: Any = -4097; '
                          f'while n <= 4097 {{ checksum = checksum + (n / {divisor}) * (n + 5000) '
                          f'+ (n % {divisor}) * (n + 6000); n = n + 1; }} return checksum; }}\n'
                          f'if sweep{divisor}() != {checksum} {{ exit(23); }}')
        source.write_text('\n'.join(sweeps + ['exit(0);']))
        compile_source(compiler, source, binary, '--raw')
        run(binary)
        print('PASS every dividend -4097..4097 for every non-power divisor 3..63', flush=True)
        for expression in ['1 / 0', f'{raw_integer(-(1 << 63))} / -1', f'{raw_integer(-(1 << 63))} % -1']:
            source.write_text(f'exit({expression});')
            compile_source(compiler, source, binary, '--raw')
            run(binary, -signal.SIGFPE)
        for statement, status in [('1 / 0;', -signal.SIGFPE), ('load64(0);', -signal.SIGSEGV)]:
            source.write_text(statement + '\nexit(0);')
            compile_source(compiler, source, binary, '--raw')
            run(binary, status)
        print(f'PASS {len(calls)} full-width signed division/remainder cases, reciprocal selection and unchanged traps', flush=True)

        call_arguments(compiler, work)
        address_arguments(compiler, work)
        dead_expressions(compiler, work)
        remainder_branches(compiler, work)

        unit = work / 'unit'
        compile_source(compiler, HERE / 'backend/x86_codegen.may', unit)
        assert run(unit) == 'x86-codegen-ok\n'
        print('PASS immediate/reciprocal boundaries, IR_TRUE/IR_FALSE and fusion guards', flush=True)

        compile_source(compiler, HERE / 'backend/raw_performance.may', binary, '--raw')
        for _ in range(3):
            results = parse_output(run(binary))
            assert {name: row['checksum'] for name, row in results.items()} == CHECKSUMS
        reference = work / 'reference'
        subprocess.run(['gcc', '-O3', '-march=native', '-std=c11',
                        str(HERE / 'backend/raw_performance.c'), '-o', str(reference)], check=True)
        assert {name: row['checksum'] for name, row in parse_output(run(reference)).items()} == CHECKSUMS
        print('PASS all six issue #76 workload checksums across three runs', flush=True)


if __name__ == '__main__':
    main()
