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
from raw_performance import CHECKSUMS, EXTENDED_CHECKSUMS, parse_output

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


def dead_branch_copies(compiler, work):
    source, binary = work / 'branch-copies.may', work / 'branch-copies'
    source.write_text('''
mut seen: Any = 0;
fun effect(n: Any) -> Any { seen = seen * 10 + n; return n; }
fun chain(n: Any) -> Any {
    mut result: Any = 0;
    if n == 0 { result = 11; }
    else if n == 1 { result = 22; }
    else if n == 2 { result = 33; }
    else { result = 44; }
    return result;
}
fun observed(n: Any) -> Any { return if n == 0 { 11 } else if n == 1 { 22 } else { 33 }; }
fun effects(n: Any) -> Any { if n == 0 { effect(1); } else if n == 1 { effect(2); } else { effect(3); } return seen; }
if chain(0) != 11 or chain(1) != 22 or chain(2) != 33 or chain(3) != 44 { exit(56); }
if observed(0) != 11 or observed(1) != 22 or observed(2) != 33 { exit(57); }
if effects(0) != 1 or effects(1) != 12 or effects(2) != 123 { exit(58); }
exit(0);
''')
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    body = function(disassemble(binary), 'chain')
    assert len(re.findall(r'\bcmp\b', body)) == 3, body
    assert not re.search(r'\bset\w+\b|\btest\s+rax,rax\b', body), body
    print('PASS cascading unread branch copies, direct else-if comparisons, observable joins and retained branch effects', flush=True)


def raw_integer(n):
    # Source literals use the compiler's tagged range; expressions can construct
    # every raw 64-bit pattern, including INT64_MIN and INT64_MAX.
    high, low = divmod(n, 1 << 32)
    return f'({high} * 4294967296 + {low})'


def signed64(value):
    value &= (1 << 64) - 1
    return value - (1 << 64) if value >= (1 << 63) else value


def raw_ccall6_words(compiler, work):
    source, binary = work / 'ccall6-words.may', work / 'ccall6-words'
    minimum = raw_integer(-(1 << 63))
    maximum = raw_integer((1 << 63) - 1)
    source.write_text(f'''
let code: Any = syscall(9, 0, 4096, 7, 34, -1, 0);
if code < 0 {{ exit(90); }}
store8(code, 72); store8(code + 1, 137); store8(code + 2, 248); store8(code + 3, 195);
if __ccall6(code, {minimum}, 0, 0, 0, 0, 0) != {minimum} {{ exit(91); }}
if __ccall6(code, {maximum}, 0, 0, 0, 0, 0) != {maximum} {{ exit(92); }}
store64(code + 9, {maximum});
if load64(code + 9) != {maximum} {{ exit(93); }}
exit(0);
''')
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    print('PASS raw __ccall6 preserves full-width words and unaligned load64 pointers', flush=True)


def raw_full_width_bitwise(compiler, work):
    source, binary = work / 'full-width-bitwise.may', work / 'full-width-bitwise'
    declarations = [
        'fun bit_and(a: Int, b: Int) -> Int { return a & b; }',
        'fun bit_or(a: Int, b: Int) -> Int { return a | b; }',
        'fun bit_xor(a: Int, b: Int) -> Int { return a ^ b; }',
        'fun bit_not(a: Int) -> Int { return ~a; }',
        'fun shift_left(a: Int, b: Int) -> Int { return a << b; }',
        'fun shift_right(a: Int, b: Int) -> Int { return a >> b; }',
    ]
    rng = random.Random(92)
    values = [-(1 << 63), -(1 << 62), -1, 0, 1, 1 << 62, (1 << 63) - 1]
    values += [rng.randrange(-(1 << 63), 1 << 63) for _ in range(32)]
    checks = []
    case = 0

    def check(expression, expected):
        nonlocal case
        checks.append(f'if {expression} != {raw_integer(expected)} {{ exit({100 + case}); }}')
        case += 1

    for value in values:
        check(f'bit_not({raw_integer(value)})', signed64(~value))
        for shift in sorted({0, 1, 31, 32, 61, 62, 63, rng.randrange(64)}):
            check(f'shift_left({raw_integer(value)}, {shift})',
                  signed64(value << shift))
            check(f'shift_right({raw_integer(value)}, {shift})', value >> shift)
        other = rng.randrange(-(1 << 63), 1 << 63)
        check(f'bit_and({raw_integer(value)}, {raw_integer(other)})', value & other)
        check(f'bit_or({raw_integer(value)}, {raw_integer(other)})', value | other)
        check(f'bit_xor({raw_integer(value)}, {raw_integer(other)})', value ^ other)

    source.write_text('\n'.join(declarations + checks + ['exit(0);']) + '\n')
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    print(f'PASS {case} raw bitwise oracle cases preserve native 64-bit values through typed calls', flush=True)


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


def truncating(n, d):
    quotient = abs(n) // d * (1 if n >= 0 else -1)
    return quotient, n - quotient * d


def wide_powers(compiler, work):
    # #84: powers of two above imm32 masks use shifts instead of idiv.
    source, binary = work / 'wide-powers.may', work / 'wide-powers'
    shifts = [30, 31, 32, 33, 40, 47, 58, 59]
    rng = random.Random(84)
    inputs = [-(1 << 63), (1 << 63) - 1, -(1 << 62), 1 << 62, -1, 0, 1]
    for shift in shifts:
        inputs += [(1 << shift) - 1, 1 << shift, (1 << shift) + 1, -(1 << shift) + 1, -(1 << shift), -(1 << shift) - 1]
    inputs += [rng.randrange(-(1 << 63), 1 << 63) for _ in range(24)]
    declarations, checks, names = [], [], []
    for shift in shifts:
        divisor = 1 << shift
        for op, index in [('/', 0), ('%', 1)]:
            name = f'{"quotient" if op == "/" else "remainder"}{shift}'
            names.append(name)
            declarations.append(f'fun {name}(n: Any) -> Any {{ return n {op} {divisor}; }}')
            for n in inputs:
                expected = truncating(n, divisor)[index]
                checks.append(f'if {name}({raw_integer(n)}) != {raw_integer(expected)} {{ exit(52); }}')
        # A remainder only compared with zero takes the general path above imm32.
        declarations.append(f'fun divisible{shift}(n: Any) -> Any {{ if n % {divisor} == 0 {{ return 7; }} return 3; }}')
        for n in inputs:
            checks.append(f'if divisible{shift}({raw_integer(n)}) != {7 if n % divisor == 0 else 3} {{ exit(53); }}')
    declarations += [
        # load32 * 1024 is proven nonnegative, so the remainder is a plain mask.
        'fun bounded(p: Any) -> Any { return (load32(p) * 1024) % 4294967296 + (load32(p) * 1024) / 4294967296; }',
        'fun hash(n: Any) -> Any { mut h: Any = 2166136261; mut i: Any = 0; '
        'while i < n { h = (h * 16777619 + i % 251 + 1) % 4294967296; i = i + 1; } return h; }']
    h = 2166136261
    for i in range(1000):
        h = (h * 16777619 + i % 251 + 1) % 4294967296
    checks += ['let p: Any = syscall(9, 0, 4096, 3, 34, -1, 0); store32(p, 4294967295);',
               f'if bounded(p) != {(4294967295 * 1024) % 4294967296 + (4294967295 * 1024) // 4294967296} {{ exit(54); }}',
               f'if hash(1000) != {h} {{ exit(55); }}', 'exit(0);']
    source.write_text('\n'.join(declarations + checks))
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    assembly = disassemble(binary)
    for name in names + ['bounded', 'hash']:
        assert not re.search(r'\bidiv\b', function(assembly, name)), name
    assert 'mov    eax,eax' in function(assembly, 'remainder32')
    assert not re.search(r'\bsar\b', function(assembly, 'bounded'))
    # Tagged code shares the signed sequence; check it executes too.
    source.write_text('fun r(n: Any) -> Any { return n % 4294967296; }\n'
                      'fun q(n: Any) -> Any { return n / 4294967296; }\n'
                      'if r(-4294967297) != -1 or q(-4294967297) != -1 or r(12884901893) != 5 or q(12884901893) != 3 { exit(56); }\n'
                      'exit(0);')
    compile_source(compiler, source, binary)
    run(binary)
    print(f'PASS {len(names) * len(inputs)} wide power-of-two quotients/remainders and {len(shifts) * len(inputs)} divisibility checks without idiv', flush=True)


def logical_branches(compiler, work):
    # #85: and/or that only steer a branch become jump chains. Leaves record
    # their evaluation order, so short-circuiting and effect order are checked.
    source, binary = work / 'logical-branches.may', work / 'logical-branches'
    rng = random.Random(85)
    comparisons = ['<', '<=', '>', '>=', '==', '!=']

    def tree(depth):
        if depth == 0 or rng.random() < 0.3:
            kind = rng.randrange(3)
            if kind == 0:
                return ('probe', rng.randrange(1, 9), rng.choice('ab'), rng.choice(comparisons), rng.randrange(-3, 4))
            if kind == 1:
                return ('compare', rng.choice('ab'), rng.choice(comparisons), rng.randrange(-3, 4))
            return ('truth', rng.choice('ab'))
        return (rng.choice(['and', 'or']), tree(depth - 1), tree(depth - 1))

    def render(node):
        if node[0] == 'probe':
            return f'probe({node[1]}, {node[2]}) {node[3]} {node[4]}'
        if node[0] == 'compare':
            return f'{node[1]} {node[2]} {node[3]}'
        if node[0] == 'truth':
            return node[1]
        return f'({render(node[1])} {node[0]} {render(node[2])})'

    def evaluate(node, env, trace):
        if node[0] == 'probe':
            trace.append(node[1])
            return eval(f'{env[node[2]]} {node[3]} {node[4]}')
        if node[0] == 'compare':
            return eval(f'{env[node[1]]} {node[2]} {node[3]}')
        if node[0] == 'truth':
            return env[node[1]] != 0
        left = evaluate(node[1], env, trace)
        if node[0] == 'and':
            return left and evaluate(node[2], env, trace)
        return left or evaluate(node[2], env, trace)

    def sequence(trace):
        value = 0
        for item in trace:
            value = (value * 31 + item) % 1000000007
        return value

    declarations = ['mut sequence: Any = 0;',
                    'fun probe(k: Any, v: Any) -> Any { sequence = (sequence * 31 + k) % 1000000007; return v; }']
    checks, functions = [], 0
    pairs = [(a, b) for a in range(-2, 3) for b in (0, 3)]
    for index in range(40):
        # Only and/or results are normalized to 0/1, so the root is always one.
        node = (rng.choice(['and', 'or']), tree(2), tree(2))
        condition = render(node)
        forms = [
            (f'fun r{index}(a: Any, b: Any) -> Any {{ if {condition} {{ return 7; }} else {{ return 3; }} }}',
             f'r{index}', lambda truth: 7 if truth else 3),
            (f'fun s{index}(a: Any, b: Any) -> Any {{ mut x: Any = 1; if {condition} {{ x = 5; }} return x; }}',
             f's{index}', lambda truth: 5 if truth else 1),
            (f'fun e{index}(a: Any, b: Any) -> Any {{ mut x: Any = 1; if {condition} {{ x = 5; }} else {{ x = 2; }} return x; }}',
             f'e{index}', lambda truth: 5 if truth else 2),
            (f'fun v{index}(a: Any, b: Any) -> Any {{ return if {condition} {{ 9 }}; }}',
             f'v{index}', lambda truth: 9 if truth else 0),
            (f'fun b{index}(a: Any, b: Any) -> Any {{ let flag: Any = {condition}; return flag; }}',
             f'b{index}', lambda truth: 1 if truth else 0)]
        for declaration, name, expected in forms:
            declarations.append(declaration)
            functions += 1
            for a, b in pairs:
                trace = []
                truth = evaluate(node, {'a': a, 'b': b}, trace)
                checks.append(f'sequence = 0; if {name}({a}, {b}) != {expected(truth)} or sequence != {sequence(trace)} {{ exit(60); }}')
        # A loop condition re-evaluates the chain on every iteration.
        declarations.append(f'fun w{index}(a: Any, b: Any) -> Any {{ mut n: Any = 0; '
                            f'while n < 3 and {condition} {{ n = n + 1; }} return n; }}')
        functions += 1
        for a, b in pairs:
            trace, n = [], 0
            while n < 3 and evaluate(node, {'a': a, 'b': b}, trace):
                n += 1
            checks.append(f'sequence = 0; if w{index}({a}, {b}) != {n} or sequence != {sequence(trace)} {{ exit(61); }}')
    declarations += [
        # The right operand's load runs only when the guard allows it.
        'fun guarded(p: Any) -> Any { if p != 0 and load64(p) > 5 { return 7; } return 3; }',
        'fun either(p: Any) -> Any { if p == 0 or load64(p) > 5 { return 7; } return 3; }',
        'fun scan(p: Any, n: Any, key: Any) -> Any { mut j: Any = n - 1; '
        'while j >= 0 and load64(p + j * 8) > key { j = j - 1; } return j; }',
        'fun observed(a: Any, b: Any) -> Any { let flag: Any = a > 0 and b > 0; return flag + 1; }',
        # Earlier operands jump to the else label of a cmov-eligible final diamond (#78).
        'fun shared(a: Any) -> Any { let b: Any = a + 0; mut x: Any = 1; '
        'if (b < -1 and b != -2) and b == 3 { x = 5; } else { x = 2; } return x + b + b + b; }']
    guards = ['let p: Any = syscall(9, 0, 4096, 3, 34, -1, 0);',
              'store64(p, 1); store64(p + 8, 9); store64(p + 16, 8);',
              'if guarded(0) != 3 or guarded(p + 8) != 7 or guarded(p) != 3 { exit(62); }',
              'if either(0) != 7 or either(p + 8) != 7 or either(p) != 3 { exit(63); }',
              'if scan(p, 3, 5) != 0 or scan(p, 3, 0) != -1 or scan(p, 0, 5) != -1 { exit(64); }',
              'if observed(1, 2) != 2 or observed(1, 0) != 1 { exit(65); }',
              'if shared(0) != 2 or shared(-5) != -13 or shared(-2) != -4 { exit(66); }']
    # Keep compiler memory bounded while growing the oracle.
    for offset in range(0, len(checks), 600):
        source.write_text('\n'.join(declarations + checks[offset:offset + 600] + guards + ['exit(0);']))
        compile_source(compiler, source, binary, '--raw')
        run(binary)
    assembly = disassemble(binary)
    for name in ['guarded', 'either', 'scan']:
        body = function(assembly, name)
        assert not re.search(r'\bset\w+\b', body), body
    # Observable Booleans keep their materialized value.
    assert re.search(r'\bset\w+\b', function(assembly, 'observed'))
    for source_text, status in [('if 0 != 0 and load64(0) > 5 { exit(1); } exit(0);', 0),
                                ('if 1 != 0 and load64(0) > 5 { exit(1); } exit(0);', -signal.SIGSEGV),
                                ('if 1 == 1 or load64(0) > 5 { exit(0); } exit(1);', 0)]:
        source.write_text(source_text)
        compile_source(compiler, source, binary, '--raw')
        run(binary, status)
    print(f'PASS {len(checks)} short-circuit branch oracles over {functions} functions; effect order, load guards, faults and observable Booleans hold', flush=True)


def small_multipliers(compiler, work):
    source, binary = work / 'multipliers.may', work / 'multipliers'
    rng = random.Random(7611)
    inputs = [-(1 << 63), (1 << 63) - 1, -(1 << 62), -17, -1, 0, 1, 17, 1 << 62]
    inputs += [rng.randrange(-(1 << 63), 1 << 63) for _ in range(20)]
    factors = [0, 1, 2, 3, 4, 5, 7, 8, 9, 64, 1 << 30, 1 << 31, 1 << 40, 1 << 59, 6, -3]
    declarations, checks = [], []
    for index, factor in enumerate(factors):
        declarations.append(f'fun multiply{index}(n: Any) -> Any {{ return n * {factor}; }}')
        for n in inputs:
            expected = (n * factor + (1 << 63)) % (1 << 64) - (1 << 63)
            checks.append(f'if multiply{index}({raw_integer(n)}) != {raw_integer(expected)} {{ exit(52); }}')
    source.write_text('\n'.join(declarations + checks + ['exit(0);']))
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    assembly = disassemble(binary)
    for index, factor in enumerate(factors):
        body = function(assembly, f'multiply{index}')
        if factor in [3, 5, 9]:
            assert re.search(r'\blea\s+rax,', body) and not re.search(r'\bimul\b', body), body
        elif factor in [2, 4, 8, 64, 1 << 30, 1 << 31, 1 << 40, 1 << 59]:
            assert re.search(r'\bshl\s+rax,', body) and not re.search(r'\bimul\b', body), body
        elif factor in [0, 1]:
            assert not re.search(r'\b(?:imul|shl|lea)\s+rax,', body), body
        else:
            assert re.search(r'\bimul\b', body), body
    source.write_text('mut seen: Any = 0; fun effect() -> Any { seen = seen + 1; return 7; }\n'
                      'if effect() * 0 != 0 or seen != 1 { exit(53); } exit(0);')
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    source.write_text('load64(0) * 0; exit(0);')
    compile_source(compiler, source, binary, '--raw')
    run(binary, -signal.SIGSEGV)
    print(f'PASS {len(inputs) * len(factors)} full-width constant products, wraparound, instruction selection and retained effects/faults', flush=True)


def local_recurrences(compiler, work):
    source, binary = work / 'recurrences.may', work / 'recurrences'
    cases = [
        ('bounded', 1, 5, 97, ''),
        ('negative', -1, 5, 97, ''),
        ('overflow', 8, (1 << 60) - 1, 97, ''),
        ('reset', 1, 5, 97, 'if i == 7 { state = -5; }'),
        ('memory', 1, 5, 97, 'load8(addr("Q"));'),
        ('unknown', 1, 5, 97, 'if i == 7 { state = seed; }')]
    rng = random.Random(7612)
    for index in range(24):
        divisor = rng.randrange(3, 10000)
        factor = rng.randrange(1, 1000000)
        cases.append((f'bounded{index}', rng.randrange(divisor), factor, divisor, ''))
    for index in range(16):
        cases.append((f'overflow{index}', rng.randrange(2, 97), rng.randrange(1 << 58, 1 << 60), 97, ''))
    declarations, checks = [], []
    for name, initial, factor, divisor, extra in cases:
        declarations.append(f'fun {name}(seed: Any) -> Any {{ mut state: Any = {initial}; mut i: Any = 0; '
                            f'while i < 20 {{ state = state * {factor} % {divisor}; {extra} i = i + 1; }} return state % 4; }}')
        state = initial
        for i in range(20):
            product = (state * factor + (1 << 63)) % (1 << 64) - (1 << 63)
            quotient = abs(product) // divisor * (-1 if product < 0 else 1)
            state = product - quotient * divisor
            if i == 7 and name in ['reset', 'unknown']:
                state = -5
        expected = abs(state) % 4 * (-1 if state < 0 else 1)
        checks.append(f'if {name}(-5) != {expected} {{ exit(54); }}')
    # Two recurrence steps share one inductive bound, including backedges and
    # nested branches. A constant reset is deliberately outside this rule.
    declarations.append('fun alternatives() -> Any { mut state: Any = 1; mut i: Any = 0; while i < 40 { '
                        'if i % 2 == 0 { state = state * 5 % 97; } else { state = state * 7 % 101; } '
                        'i = i + 1; } return state % 4; }')
    state = 1
    for i in range(40):
        state = state * (5 if i % 2 == 0 else 7) % (97 if i % 2 == 0 else 101)
    checks += [f'if alternatives() != {state % 4} {{ exit(55); }}', 'exit(0);']
    source.write_text('\n'.join(declarations + checks))
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    assembly = disassemble(binary)
    bounded = function(assembly, 'bounded')
    assert re.search(r'\band\s+rax,0x3\b', bounded), bounded
    assert not re.search(r'\b(?:sar\s+rcx|shr\s+rax),0x3f\b', bounded), bounded
    for name, *_ in cases:
        body = function(assembly, name)
        if name.startswith('bounded'):
            assert not re.search(r'\b(?:sar\s+rcx|shr\s+rax),0x3f\b', body), (name, body)
        else:
            assert re.search(r'\bsar\s+rcx,0x3f\b', body), (name, body)
    print(f'PASS {len(cases) + 1} local recurrence oracles, alternative steps, negative/unknown/reset values, overflow and memory barriers', flush=True)


def local_registers(compiler, work):
    source, binary = work / 'local-registers.may', work / 'local-registers'
    declarations = '''
fun counter() -> Any { mut i: Any = 0; mut total: Any = 0; while i < 100 { total = total + i; i = i + 1; } return total; }
fun pressure(seed: Any) -> Any {
    mut a: Any = seed; mut b: Any = 2; mut c: Any = 3; mut d: Any = 4; mut e: Any = 5; mut f: Any = 6; mut i: Any = 0;
    while i < 32 {
        let old: Any = a;
        if i % 3 == 0 { a = b + c; b = old + d; }
        else { a = a + e; b = b - c; }
        c = (c + a) % 97; d = d + old; e = e + f; f = (f + e) % 101; i = i + 1;
    }
    return a + b * 3 + c * 5 + d * 7 + e * 11 + f * 13;
}
fun nested() -> Any {
    mut i: Any = 0; mut total: Any = 0;
    while i < 50 {
        i = i + 1; if i % 7 == 0 { continue; }
        mut j: Any = 0;
        while j < 10 { if j == 5 { break; } total = total + i + j; j = j + 1; }
    }
    return total;
}
fun snapshots(seed: Any) -> Any {
    mut n: Any = seed; mut total: Any = 0; mut i: Any = 0;
    while i < 7 { total = total + n + if i % 2 == 0 { n = n + 1; } else { n = n - 1; }; i = i + 1; }
    return total + n * 100;
}
fun eight(a: Any, b: Any, c: Any, d: Any, e: Any, f: Any, g: Any, h: Any) -> Any {
    mut n: Any = a + b + c + d + e + f + g + h; mut i: Any = 0;
    while i < 20 { n = n * 3 + 1; i = i + 1; } return n;
}
fun one() -> Any { return 1; }
fun calls() -> Any { mut i: Any = 0; while i < 20 { i = i + one(); } return i; }
fun memory(p: Any) -> Any { mut i: Any = 0; while i < 20 { store8(p, i); i = i + 1; } return i; }
'''
    wrap = lambda n: (n + (1 << 63)) % (1 << 64) - (1 << 63)
    def mod(n, d):
        return abs(n) % d * (-1 if n < 0 else 1)
    def oracle(seed):
        a, b, c, d, e, f = seed, 2, 3, 4, 5, 6
        for i in range(32):
            old = a
            if i % 3 == 0:
                a, b = wrap(b + c), wrap(old + d)
            else:
                a, b = wrap(a + e), wrap(b - c)
            c = mod(wrap(c + a), 97)
            d, e = wrap(d + old), wrap(e + f)
            f = mod(wrap(f + e), 101)
        return wrap(a + b * 3 + c * 5 + d * 7 + e * 11 + f * 13)
    seeds = [-(1 << 63), (1 << 63) - 1, -7, 0, 7, 9]
    checks = [f'if pressure({raw_integer(n)}) != {raw_integer(oracle(n))} {{ exit(59); }}' for n in seeds]
    for seed in seeds:
        n, total = seed, 0
        for i in range(7):
            old = n; n = wrap(n + (1 if i % 2 == 0 else -1)); total = wrap(total + old + n)
        checks.append(f'if snapshots({raw_integer(seed)}) != {raw_integer(wrap(total + n * 100))} {{ exit(59); }}')
    eight = 36
    for _ in range(20):
        eight = eight * 3 + 1
    nested = sum(i + j for i in range(1, 51) if i % 7 for j in range(5))
    checks += [f'if counter() != 4950 or nested() != {nested} {{ exit(60); }}',
               f'if counter() + pressure(7) + pressure(9) != {raw_integer(wrap(4950 + oracle(7) + oracle(9)))} {{ exit(61); }}',
               f'if counter() + eight(1, 2, 3, 4, 5, 6, 7, 8) != {eight + 4950} {{ exit(61); }}',
               'let p: Any = syscall(9, 0, 4096, 3, 34, -1, 0);',
               'if calls() != 20 or memory(p) != 20 or load8(p) != 19 { exit(62); }', 'exit(0);']
    source.write_text(declarations + '\n'.join(checks))
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    assembly = disassemble(binary)
    body = function(assembly, 'counter')
    assert re.search(r'\brbx\b', body), body
    assert not re.search(r'\b(?:mov|add|cmp)\s+rax,QWORD PTR \[rbp-', body), body
    # Direct calls (#86) and RAW load/store intrinsics (#79) allow promotion.
    assert re.search(r'\brbx\b', function(assembly, 'calls'))
    assert re.search(r'\brbx\b', function(assembly, 'memory'))
    print('PASS whole-function local registers, full-width snapshots/spills, nested loop joins/break/continue, live caller values, call and memory-loop promotion', flush=True)


def promoted_parameters(compiler, work):
    # #86: parameters and locals of bodies with direct calls use RBX/r12-r15.
    source, binary = work / 'promoted-parameters.may', work / 'promoted-parameters'
    wrap = lambda n: (n + (1 << 63)) % (1 << 64) - (1 << 63)
    declarations = '''
fun leaf(x: Any) -> Any { return x * 3 + 1; }
fun clobber(a: Any, b: Any, c: Any, d: Any, e: Any, f: Any) -> Any {
    mut i: Any = 0; mut s: Any = 0;
    while i < 10 { s = s + a * i + b - c + d * e - f; i = i + 1; }
    return s;
}
fun keeps(a: Any, b: Any, c: Any) -> Any {
    mut t: Any = 0; mut i: Any = 0;
    while i < 30 { t = t + leaf(i) + clobber(i, a, b, c, t % 7, i) % 1000 + a - b * c; i = i + 1; }
    return t + a + b + c;
}
fun nine(a: Any, b: Any, c: Any, d: Any, e: Any, f: Any, g: Any, h: Any, k: Any) -> Any {
    mut t: Any = 0; mut i: Any = 0;
    while i < 12 { t = t + a * i + b + c * d - e + f * g + h - k + leaf(t % 5); i = i + 1; }
    return t * 2 + k + h + g;
}
fun fib(n: Any) -> Any { if n < 2 { return n; } return fib(n - 1) + fib(n - 2); }
fun ackermann(m: Any, n: Any) -> Any {
    if m == 0 { return n + 1; }
    if n == 0 { return ackermann(m - 1, 1); }
    return ackermann(m - 1, ackermann(m, n - 1));
}
fun pids(n: Any) -> Any {
    mut i: Any = 0; mut t: Any = 0; let pid: Any = syscall(39);
    while i < n { t = t + syscall(39) - pid + i * n; i = i + 1; }
    return t + n;
}
fun scan(p: Any, n: Any, key: Any) -> Any {
    mut count: Any = 0; mut i: Any = 0;
    while i < n { if load64(p + i * 8) > key { count = count + 1; } i = i + 1; }
    return count;
}
fun stack(n: Any) -> Any { mut i: Any = 0; mut t: Any = 0; while i < n { t = t + i; i = i + 1; } return t + __sp() * 0; }
fun mapped(size: Any, flags: Any, fd: Any, offset: Any) -> Any {
    mut total: Any = 0; mut i: Any = 0;
    while i < 3 {
        // syscall arguments use r10/r8/r9, so their values cannot live there (#87).
        let p: Any = syscall(9, 0, size + i - i, 3, flags + i - i, fd + i - i, offset + i - i);
        if p < 0 { return p; }
        store64(p, i + size); total = total + load64(p); i = i + 1;
    }
    return total;
}
'''
    def leaf(x):
        return wrap(x * 3 + 1)
    def clobber(a, b, c, d, e, f):
        s = 0
        for i in range(10):
            s = wrap(s + a * i + b - c + d * e - f)
        return s
    def mod(n, d):
        return abs(n) % d * (-1 if n < 0 else 1)
    def keeps(a, b, c):
        t = 0
        for i in range(30):
            t = wrap(t + leaf(i) + mod(clobber(i, a, b, c, mod(t, 7), i), 1000) + a - b * c)
        return wrap(t + a + b + c)
    def nine(a, b, c, d, e, f, g, h, k):
        t = 0
        for i in range(12):
            t = wrap(t + a * i + b + c * d - e + f * g + h - k + leaf(mod(t, 5)))
        return wrap(t * 2 + k + h + g)
    def ackermann(m, n):
        while m:
            n = 1 if n == 0 else ackermann(m, n - 1)
            m -= 1
        return n + 1
    checks = []
    for a, b, c in [(0, 0, 0), (7, -3, 11), (-100, 55, -9), (123456789, -987654321, 31337)]:
        checks.append(f'if keeps({a}, {b}, {c}) != {keeps(a, b, c)} {{ exit(70); }}')
    for args in [(1, 2, 3, 4, 5, 6, 7, 8, 9), (-9, 8, -7, 6, -5, 4, -3, 2, -1), (0, 0, 0, 0, 0, 0, 0, 0, 1 << 40)]:
        checks.append(f'if nine({", ".join(map(str, args))}) != {nine(*args)} {{ exit(71); }}')
    checks += [f'if fib(20) != 6765 or ackermann(2, 3) != {ackermann(2, 3)} {{ exit(72); }}',
               f'if pids(40) != {sum(i * 40 for i in range(40)) + 40} {{ exit(73); }}',
               'let p: Any = syscall(9, 0, 4096, 3, 34, -1, 0);',
               'mut i: Any = 0; while i < 64 { store64(p + i * 8, i * 7 % 13); i = i + 1; }',
               f'if scan(p, 64, 6) != {sum(1 for i in range(64) if i * 7 % 13 > 6)} or stack(10) != 45 {{ exit(74); }}',
               'if mapped(4096, 34, -1, 0) != 3 + 3 * 4096 { exit(75); }',
               'exit(0);']
    source.write_text(declarations + '\n'.join(checks))
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    assembly = disassemble(binary)
    for name in ['keeps', 'nine', 'pids', 'scan']:
        assert re.search(r'\brbx\b', function(assembly, name)), name
    # Promoted parameters are never reloaded from their frame slots.
    for name in ['scan', 'keeps']:
        assert not re.search(r'PTR \[rbp-0x(?:8|10|18)\]', function(assembly, name)), function(assembly, name)
    # #87: call arguments use r10, only values spanning a call take callee-saved
    # registers, and no jump targets the next instruction.
    body = function(assembly, 'fib')
    assert re.search(r'\bmov\s+rdi,r10\b', body) and not re.search(r'\br1[34]\b', body), body
    lines = re.findall(r'^\s*([0-9a-f]+):\s+(\w+)\s*(.*)$', body, re.M)
    for (address, mnemonic, operand), following in zip(lines, lines[1:]):
        if mnemonic == 'jmp':
            assert not operand.startswith(following[0] + ' '), body
    # __sp still exposes the stack and excludes the body.
    assert not re.search(r'\b(?:rbx|r12)\b', function(assembly, 'stack')), function(assembly, 'stack')
    print('PASS promoted parameters, stack arguments, locals across calls/recursion/syscalls and __sp exclusion', flush=True)


def direct_local_operations(compiler, work):
    source, binary = work / 'direct-locals.may', work / 'direct-locals'
    wrap = lambda n: (n + (1 << 63)) % (1 << 64) - (1 << 63)
    specs = [(f'n * {factor} + {offset}', lambda n, c=factor, b=offset: wrap(n * c + b))
             for factor in [3, 5, 9] for offset in [0, 1, 128]]
    specs += [(f'n * 3 + {offset}', lambda n, b=offset: wrap(n * 3 + b)) for offset in [-1, 2147483647, 2147483648]]
    for divisor in [1, 2, 4, 128, 1 << 30, 3]:
        def quotient(n, d=divisor):
            return abs(n) // d * (-1 if n < 0 else 1)
        specs += [(f'n / {divisor}', quotient), (f'n % {divisor}', lambda n, d=divisor, q=quotient: n - q(n) * d)]
    declarations, checks = [], []
    seeds = [-(1 << 63), (1 << 63) - 1, -17, -1, 0, 17]
    for place in range(5):
        prefix = ''.join(f'mut g{i}: Any = 0;' for i in range(place))
        updates = ''.join(f'g{i} = g{i} + 1;' for i in range(place))
        result = 'n' + ''.join(f' + g{i}' for i in range(place))
        for index, (expression, oracle) in enumerate(specs):
            name = f'local{place}_{index}'
            # Straight-line bodies rank by declaration order, so g0..g{place-1}
            # take the first registers and n the next one.
            declarations.append(f'fun {name}(seed: Any) -> Any {{ {prefix} mut n: Any = seed; '
                                f'n = {expression}; {updates} return {result}; }}')
            for n in seeds:
                checks.append(f'if {name}({raw_integer(n)}) != {raw_integer(wrap(oracle(n) + place))} {{ exit(63); }}')
    declarations += ['fun observed(seed: Any) -> Any { mut n: Any = seed; mut i: Any = 0; mut result: Any = 0; '
                     'while i < 3 { result = if n > 0 { n = n * 3 + 1; } else { n = n + 1; }; i = i + 1; } return n + result * 17; }']
    for seed in [-7, 0, 7]:
        n = seed
        for _ in range(3):
            n = n * 3 + 1 if n > 0 else n + 1
        checks.append(f'if observed({seed}) != {n * 18} {{ exit(64); }}')
    source.write_text('\n'.join(declarations + checks + ['exit(0);']))
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    assembly = disassemble(binary)
    for place, register in enumerate(['rbx', 'r12', 'r13', 'r14', 'r15']):
        body = function(assembly, f'local{place}_1')
        assert re.search(r'\blea\s+' + register + r',\[' + register, body), body
    for expression, seed in [('n / 0', 1), ('n / -1', -(1 << 63)), ('n % -1', -(1 << 63))]:
        source.write_text('fun trap(seed: Any) -> Any { mut n: Any = seed; mut i: Any = 0; '
                          f'while i < 1 {{ n = {expression}; i = i + 1; }} return n; }} exit(trap({raw_integer(seed)}));')
        compile_source(compiler, source, binary, '--raw')
        run(binary, -signal.SIGFPE)
    print(f'PASS {5 * len(specs) * len(seeds)} full-width direct-local arithmetic cases across RBX/R12-R15, observable assignments and division traps', flush=True)


REGISTERS = ['rax', 'rcx', 'rdx', 'rbx', 'rsp', 'rbp', 'rsi', 'rdi'] + [f'r{n}' for n in range(8, 16)]


def memory_encodings(compiler, work):
    """Decode every x86_memory form with objdump as an independent oracle (#79)."""
    binary = work / 'memory-encoding'
    compile_source(compiler, HERE / 'backend/x86_memory_encoding.may', binary)
    rows, blob = [], bytearray()
    for line in run(binary).splitlines():
        base, index, scale, displacement, wide, text = line.split()
        rows.append((len(blob), int(base), int(index), int(scale), int(displacement), wide == 'true'))
        blob += bytes.fromhex(text)
    raw = work / 'memory-encoding.bin'
    raw.write_bytes(blob)
    listing = subprocess.check_output(['objdump', '-D', '-b', 'binary', '-m', 'i386:x86-64', '-Mintel',
                                       '--no-show-raw-insn', str(raw)], text=True)
    decoded = {int(match[1], 16): match[2].strip() for match in re.finditer(r'^\s*([0-9a-f]+):\s+(.*)$', listing, re.M)}
    for offset, base, index, scale, displacement, wide in rows:
        address = REGISTERS[base] + (f'+{REGISTERS[index]}*{scale}' if index >= 0 else '')
        if displacement or base % 8 == 5:
            address += f'+0x{displacement:x}' if displacement >= 0 else f'-0x{-displacement:x}'
        expected = f"mov    {'rcx' if wide else 'ecx'},{'QWORD' if wide else 'DWORD'} PTR [{address}]"
        assert decoded.get(offset) == expected, (offset, decoded.get(offset), expected)
    print(f'PASS {len(rows)} base/index/scale/displacement encodings decoded by objdump', flush=True)


def fused_addresses(compiler, work):
    """Differential oracle for fused RAW addresses and memory-loop locals (#79)."""
    source, binary = work / 'addresses.may', work / 'addresses'
    rng = random.Random(79)
    wrap = lambda n: (n + (1 << 63)) % (1 << 64) - (1 << 63)
    widths = [8, 16, 32, 64]

    def address():
        base, index = rng.choice(['b', 'c']), rng.choice(['i', 'j'])
        scale, offset = rng.choice([1, 2, 4, 8]), rng.choice([0, 1, -1, 8, 127, 128, -129, 4096, -4096])
        forms = [(f'{base} + {index}', lambda e: e[base] + e[index]),
                 (f'{base} + {index} * {scale}', lambda e: e[base] + e[index] * scale),
                 (f'{base} + {index} * {scale} + {offset}', lambda e: e[base] + e[index] * scale + offset),
                 (f'{index} * {scale} + {base}', lambda e: e[index] * scale + e[base]),
                 (f'{scale} * {index} + {base}', lambda e: scale * e[index] + e[base]),
                 (f'{base} + {offset}', lambda e: e[base] + offset),
                 (f'{base} + ({index} + {offset})', lambda e: e[base] + e[index] + offset),
                 (f'({base} + {offset}) + {index} * {scale}', lambda e: e[base] + offset + e[index] * scale),
                 (f'{base} + {index} * {scale} - 64', lambda e: e[base] + e[index] * scale - 64),
                 (f'{base}', lambda e: e[base])]
        return rng.choice(forms)

    def value():
        return rng.choice([('i * 37 + j', lambda e: wrap(e['i'] * 37 + e['j'])), ('acc', lambda e: e['acc']),
                           ('j - i', lambda e: wrap(e['j'] - e['i'])),
                           ('1152921504606846975', lambda e: 1152921504606846975)])

    memory = bytearray(65536)

    def load(at, width):
        # Narrow loads zero-extend; load64 yields the signed 64-bit pattern.
        return wrap(int.from_bytes(memory[at:at + width // 8], 'little'))

    def remainder(n, d):
        return -(-n % d) if n < 0 else n % d

    def store(at, width, number):
        memory[at:at + width // 8] = (number % (1 << width)).to_bytes(width // 8, 'little')

    declarations, checks = ['fun nop() -> Any { return 0; }'], []
    expected = []
    for index in range(120):
        rounds, body, actions = rng.randint(1, 24), [], []
        for count in range(rng.randint(2, 4)):
            kind, width = rng.random(), rng.choice(widths)
            text, at = address()
            if kind < 0.35:
                shown, compute = value()
                body.append(f'store{width}({text}, {shown});')
                actions.append(('store', at, width, compute))
            elif kind < 0.7:
                body.append(f'acc = acc + load{width}({text});')
                actions.append(('add', at, width))
            elif kind < 0.85:
                body.append(f'acc = acc * 3 + load{width}({text}) % 7;')
                actions.append(('mix', at, width))
            else:
                target, other = address(), rng.choice(widths)
                body.append(f'let t{count}: Any = load{width}({text}); store{other}({target[0]}, t{count} + 1);')
                actions.append(('copy', at, width, target[1], other))
        call = rng.random() < 0.2
        declarations.append(f'fun memory{index}(p: Any) -> Any {{ let b: Any = p + 32768; let c: Any = p + 16384; '
                            f'mut acc: Any = 0; mut j: Any = 3; mut i: Any = 0; while i < {rounds} {{ {" ".join(body)} '
                            f'{"acc = acc + nop(); " if call else ""}j = (j * 5 + 1) % 23; i = i + 1; }} return acc; }}')
        env = {'b': 32768, 'c': 16384, 'acc': 0, 'j': 3}
        for i in range(rounds):
            env['i'] = i
            for action in actions:
                if action[0] == 'store':
                    store(action[1](env), action[2], action[3](env))
                elif action[0] == 'add':
                    env['acc'] = wrap(env['acc'] + load(action[1](env), action[2]))
                elif action[0] == 'mix':
                    env['acc'] = wrap(env['acc'] * 3 + remainder(load(action[1](env), action[2]), 7))
                else:
                    store(action[3](env), action[4], load(action[1](env), action[2]) + 1)
            env['j'] = (env['j'] * 5 + 1) % 23
        checks.append(f'if memory{index}(p) != {raw_integer(env["acc"])} {{ exit(72); }}')
    # Snapshots: the store address uses i before the value expression changes it.
    declarations += [
        'fun snapshot(p: Any) -> Any { mut i: Any = 5; let b: Any = p + 100; '
        'store8(b + i, if i > 0 { i = i + 1; i } else { 0 }); store8(b + i, 9); return load8(b + 5) * 100 + load8(b + 6) * 10 + i; }',
        'fun widths(p: Any) -> Any { let b: Any = p + 200; mut i: Any = 0; mut total: Any = 0; '
        'while i < 4 { store64(b + i * 8, -1); store32(b + i * 8 + 1, 0); store16(b + i * 8 + 5, 4660); store8(b + i * 8 + 7, 128); '
        'total = total + load64(b + i * 8) % 1000003 + load32(b + i * 8 + 4) + load16(b + i * 8 + 6) + load8(b + i * 8); i = i + 1; } return total; }',
        # The second displacement sum exceeds imm32 and must not be fused.
        'fun far(p: Any) -> Any { let b: Any = p - 2147483000; let c: Any = p - 3000000000; store8(b + 2147483003, 77); '
        'return load8(b + 2147483003) * 1000 + load8(c + 2000000000 + 1000000003); }',
    ]
    word = (-1 % (1 << 64)) & ~(((1 << 32) - 1) << 8)
    word = (word & ~(0xffff << 40)) | (4660 << 40)
    word = (word & ~(0xff << 56)) | (128 << 56)
    raw_word = word - (1 << 64)
    remainder = -(-raw_word % 1000003) if raw_word < 0 else raw_word % 1000003
    each = remainder + ((word >> 32) & 0xffffffff) + ((word >> 48) & 0xffff) + (word & 0xff)
    checks += [f'if snapshot(p + 60000) != {6 * 100 + 9 * 10 + 6} {{ exit(73); }}',
               f'if widths(p + 60000) != {raw_integer(4 * each)} {{ exit(74); }}',
               'if far(p) != 77077 { exit(75); }', 'exit(0);']
    source.write_text('\n'.join(declarations + ['let p: Any = syscall(9, 0, 196608, 3, 34, -1, 0);'] + checks))
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    assembly = disassemble(binary)
    fused = sum(1 for index in range(120) if re.search(r'PTR \[r\w+\+r\w+\*[248]', function(assembly, f'memory{index}')))
    # Direct calls keep promotion (#86); values spanning them avoid r8-r10 (#87),
    # which the byte-array oracle above checks by execution.
    for index in range(120):
        assert re.search(r'\brbx\b', function(assembly, f'memory{index}')), index
    assert fused >= 30, fused
    # Faults keep their order: the write happens before the faulting load.
    source.write_text('fun fault(p: Any) -> Any { mut i: Any = 0; mut total: Any = 0; '
                      'while i < 2 { syscall(1, 1, addr("A"), 1); total = total + load8(p + i * 8); i = i + 1; } return total; } exit(fault(0));')
    compile_source(compiler, source, binary, '--raw')
    result = subprocess.run([str(binary)], capture_output=True, timeout=15)
    assert result.returncode == -signal.SIGSEGV and result.stdout == b'A', result
    print(f'PASS {len(checks) - 1} fused-address memory oracles; {fused}/120 functions use scaled indexes; '
          'snapshots, widths, displacements, calls and fault order hold', flush=True)
def select_diamonds(compiler, work):
    """Differential oracle for branch-free scalar diamonds (#78)."""
    source, binary = work / 'select.may', work / 'select'
    rng = random.Random(78)
    wrap = lambda n: (n + (1 << 63)) % (1 << 64) - (1 << 63)
    names = ['x', 'y', 'z', 'w']
    literals = [0, 1, 2, 3, 7, 127, 128, 2147483647, 4294967296, 1152921504606846975]
    powers = [1, 2, 4, 8, 1 << 30]

    def divide(n, d):
        return abs(n) // d * (-1 if n < 0 else 1)

    def expression():
        v, u, k = rng.choice(names), rng.choice(names), rng.choice(literals)
        p = rng.choice(powers)
        return rng.choice([('var', v), ('lit', k), ('+', ('var', v), ('lit', k)), ('-', ('var', v), ('lit', k)),
                           ('-', ('lit', k), ('var', v)), ('+', ('var', v), ('var', u)), ('-', ('var', v), ('var', u)),
                           ('*', ('var', v), ('lit', rng.choice([0, 1, 2, 3, 5, 8, 9, 10, 1 << 20]))),
                           ('*', ('lit', rng.choice([3, 7])), ('var', v)), ('*', ('var', v), ('var', u)),
                           ('neg', ('var', v)), ('/', ('var', v), ('lit', p)), ('%', ('var', v), ('lit', p)),
                           ('+', ('*', ('var', v), ('lit', 3)), ('lit', 1))])

    def condition():
        v, u, k = rng.choice(names), rng.choice(names), rng.choice(literals[:8])
        op = rng.choice(['<', '<=', '>', '>=', '==', '!='])
        p = rng.choice(powers[1:])
        return rng.choice([(op, ('var', v), ('lit', k)), (op, ('lit', k), ('var', v)), (op, ('var', v), ('var', u)),
                           ('==', ('%', ('var', v), ('lit', p)), ('lit', 0)), ('!=', ('%', ('var', v), ('lit', p)), ('lit', 0)),
                           ('==', ('lit', 0), ('%', ('var', v), ('lit', p))), ('truthy', ('%', ('var', v), ('lit', p))),
                           ('truthy', ('var', v))])

    def statements(depth):
        result = []
        for _ in range(rng.randint(0 if depth else 1, 2)):
            choice = rng.random()
            if depth < 3 and choice < 0.45:
                otherwise = None
                if rng.random() < 0.7:
                    otherwise = [statements(depth + 1)[0]] if rng.random() < 0.4 and depth < 2 else statements(depth + 1)
                result.append(('if', condition(), statements(depth + 1), otherwise))
            elif choice < 0.52:
                result.append(('ifexpr', rng.choice(names), condition(), expression(), expression()))
            else:
                result.append(('assign', rng.choice(names), expression()))
        return result or [('assign', rng.choice(names), expression())]

    def render(node):
        kind = node[0]
        if kind == 'var':
            return node[1]
        if kind == 'lit':
            return str(node[1])
        if kind == 'neg':
            return f'(-{render(node[1])})'
        if kind == 'truthy':
            return render(node[1])
        return f'({render(node[1])} {kind} {render(node[2])})'

    def render_statements(items):
        out = []
        for item in items:
            if item[0] == 'assign':
                out.append(f'{item[1]} = {render(item[2])};')
            elif item[0] == 'ifexpr':
                out.append(f'{item[1]} = if {render(item[2])} {{ {render(item[3])} }} else {{ {render(item[4])} }};')
            else:
                text = f'if {render(item[1])} {{ {" ".join(render_statements(item[2]))} }}'
                if item[3] is not None:
                    if len(item[3]) == 1 and item[3][0][0] == 'if':
                        text += ' else ' + render_statements(item[3])[0]
                    else:
                        text += f' else {{ {" ".join(render_statements(item[3]))} }}'
                out.append(text)
        return out

    def value(node, env):
        kind = node[0]
        if kind == 'var':
            return env[node[1]]
        if kind == 'lit':
            return node[1]
        if kind == 'neg':
            return wrap(-value(node[1], env))
        if kind == 'truthy':
            return int(value(node[1], env) != 0)
        a, b = value(node[1], env), value(node[2], env)
        return {'+': lambda: wrap(a + b), '-': lambda: wrap(a - b), '*': lambda: wrap(a * b),
                '/': lambda: divide(a, b), '%': lambda: a - divide(a, b) * b,
                '<': lambda: int(a < b), '<=': lambda: int(a <= b), '>': lambda: int(a > b),
                '>=': lambda: int(a >= b), '==': lambda: int(a == b), '!=': lambda: int(a != b)}[kind]()

    def execute(items, env):
        for item in items:
            if item[0] == 'assign':
                env[item[1]] = value(item[2], env)
            elif item[0] == 'ifexpr':
                env[item[1]] = value(item[3] if value(item[2], env) else item[4], env)
            elif value(item[1], env):
                execute(item[2], env)
            elif item[3] is not None:
                execute(item[3], env)

    seeds = [(-(1 << 63), (1 << 63) - 1), (-1, 0), (0, 1), (5, -7), (1 << 40, 3), (6, 6), (-(1 << 62), -9)]
    declarations, checks = [], []
    for index in range(160):
        body = statements(0)
        rounds = rng.randint(1, 4)
        declarations.append(f'fun select{index}(a: Any, b: Any) -> Any {{ mut x: Any = a; mut y: Any = b; mut z: Any = a - b; '
                            f'mut w: Any = 3; mut i: Any = 0; while i < {rounds} {{ {" ".join(render_statements(body))} i = i + 1; }} '
                            'return x + y * 3 + z * 5 + w * 7; }')
        for a, b in rng.sample(seeds, 3):
            env = {'x': a, 'y': b, 'z': wrap(a - b), 'w': 3}
            for _ in range(rounds):
                execute(body, env)
            expected = wrap(env['x'] + env['y'] * 3 + env['z'] * 5 + env['w'] * 7)
            checks.append(f'if select{index}({raw_integer(a)}, {raw_integer(b)}) != {raw_integer(expected)} {{ exit(65); }}')
    # Fixed contracts: untaken traps and loads never run, if-results stay
    # observable, sequential aliasing keeps its order and wrapping is exact.
    declarations += [
        'fun walk(seed: Any) -> Any { mut s: Any = seed; mut x: Any = 0; mut y: Any = 0; mut i: Any = 0; '
        'while i < 64 { s = s * 16807 % 2147483647; let d: Any = s % 4; '
        'if d == 0 { x = x + 1; } else if d == 1 { x = x - 1; } else if d == 2 { y = y + 1; } else { y = y - 1; } i = i + 1; } '
        'return x * 1000 + y; }',
        'fun guarded(n: Any, d: Any) -> Any { mut q: Any = n; mut i: Any = 0; mut r: Any = 0; '
        'while i < 2 { if d == 0 { q = q + 1; } else { q = q / 3; } if q == 12345 { r = q / 0; } i = i + 1; } return q + r; }',
        'fun minimum(n: Any) -> Any { mut q: Any = n; mut i: Any = 0; while i < 1 { if q != -1 { q = q / 2; } else { q = q % 4; } i = i + 1; } return q; }',
        'fun swap(a: Any, b: Any) -> Any { mut x: Any = a; mut y: Any = b; mut i: Any = 0; '
        'while i < 3 { if x < y { x = y; y = x; } else { y = x + 1; x = y - 2; } i = i + 1; } return x * 7 + y; }',
        'fun wide(n: Any) -> Any { mut x: Any = n; mut i: Any = 0; while i < 2 { if x > 0 { x = x + 4294967296; } else { x = x - 1; } i = i + 1; } return x; }',
        'fun loaded(p: Any, n: Any) -> Any { mut x: Any = n; mut i: Any = 0; while i < 4 { if p != 0 { x = x + load8(p); } i = i + 1; } return x; }',
        'fun empty(n: Any) -> Any { mut x: Any = n; mut i: Any = 0; while i < 3 { if x > 0 { } else { } x = x + 1; i = i + 1; } return x; }',
    ]
    s, x, y = 7, 0, 0
    for _ in range(64):
        s = s * 16807 % 2147483647
        d = s % 4
        x, y = x + (d == 0) - (d == 1), y + (d == 2) - (d == 3)
    big = (1 << 63) - 1

    def swap(x, y):
        for _ in range(3):
            if x < y:
                x = y
            else:
                y = x + 1
                x = y - 2
        return x * 7 + y

    def wide(x):
        for _ in range(2):
            x = wrap(x + 4294967296) if x > 0 else x - 1
        return x
    checks += [f'if walk(7) != {x * 1000 + y} {{ exit(66); }}',
               'if guarded(100, 0) != 102 or guarded(100, 5) != 11 { exit(67); }',
               f'if minimum({raw_integer(-(1 << 63))}) != {raw_integer(-(1 << 62))} or minimum(-1) != -1 or minimum(-7) != -3 {{ exit(68); }}',
               f'if swap(1, 5) != {swap(1, 5)} or swap(9, 2) != {swap(9, 2)} {{ exit(69); }}',
               f'if wide({raw_integer(big)}) != {raw_integer(wide(big))} or wide(0) != {wide(0)} {{ exit(70); }}',
               'if loaded(0, 3) != 3 or empty(-1) != 2 { exit(71); }', 'exit(0);']
    source.write_text('\n'.join(declarations + checks))
    compile_source(compiler, source, binary, '--raw')
    run(binary)
    assembly = disassemble(binary)
    converted = sum(1 for index in range(160) if re.search(r'\bcmov', function(assembly, f'select{index}')))
    walk = function(assembly, 'walk')
    assert re.search(r'\bcmove\b', walk) and len(re.findall(r'\bj(?!mp)\w+', walk)) == 1, walk
    for name in ['guarded', 'loaded']:
        assert re.search(r'\bj(?!mp)\w+', function(assembly, name)), name
    assert converted >= 40, converted
    print(f'PASS {len(checks) - 1} branch-free diamond oracles; {converted}/160 random functions use cmov; '
          'traps, loads, if-results and aliasing keep exact behavior', flush=True)


def decode_nops(work, data):
    """objdump as an independent oracle: (mnemonic, length) per instruction."""
    path = work / 'nops.bin'
    path.write_bytes(bytes(data))
    output = subprocess.check_output(['objdump', '-D', '-b', 'binary', '-mi386:x86-64', '-Mintel', str(path)], text=True)
    decoded = []
    for line in output.splitlines():
        match = re.match(r'\s*[0-9a-f]+:\t((?:[0-9a-f]{2} )+) *(?:\t(\S+))?', line)
        if match and match[2]:
            decoded.append([match[2], len(match[1].split())])
        elif match:
            decoded[-1][1] += len(match[1].split())  # objdump wraps long encodings
    return decoded


def code_alignment(compiler, work, unit_output):
    """Function bodies and loop heads are aligned with NOP padding (#83)."""
    lines = unit_output.splitlines()
    assert lines[-1] == 'x86-codegen-ok', unit_output
    pads = [line for line in lines if line.startswith('pad ')]
    assert len(pads) == 40, unit_output
    for line in pads:
        length, data = line[4:].split(': ')
        decoded = decode_nops(work, [int(byte) for byte in data.split()])
        assert all(mnemonic in ('nop', 'xchg') for mnemonic, _ in decoded), (line, decoded)
        # At most nine bytes per instruction, so ceil(length / 9) instructions.
        assert [size for _, size in decoded] == [9] * (int(length) // 9) + ([int(length) % 9] if int(length) % 9 else []), (line, decoded)
    print('PASS every NOP length 1..9 and padding 1..40 decode as single NOP instructions', flush=True)

    source, binary = work / 'align.may', work / 'align'
    loops = '''fun nested(n: Any, skew: Any) -> Any {
    mut p: Any = skew;
    PREFIX    mut total: Any = 0;
    mut i: Any = 0;
    while i < n {
        mut j: Any = 0;
        while j < i {
            j = j + 1;
            if j % 3 == 0 { continue; }
            total = total + j;
            if total > 100000 { break; }
        }
        i = i + 1;
    }
    return total + p;
}
fun unbounded(n: Any) -> Any {
    mut t: Any = 0;
    mut k: Any = 0;
    while true {
        if k >= n { break; }
        t = t + k * 2;
        k = k + 1;
    }
    return t;
}
mut m: Any = 0;
while m < 5 { m = m + 1; }
exit((nested(40, 1) + unbounded(30) + m) % 256);
'''

    def expected(small, large):
        total = 0
        for i in range(40):
            for j in range(1, i + 1):
                if j % 3:
                    total += j
        return (total + 1 + small + 1000 * large + sum(k * 2 for k in range(30)) + 5) % 256

    def heads(assembly):
        """Backward-branch targets and the bytes of NOP padding before each."""
        lines = re.findall(r'^[ \t]*([0-9a-f]+):[ \t]+(\w+)[ \t]*(?:0x)?([0-9a-f]+)?', assembly, re.M)
        addresses = [int(address, 16) for address, _, _ in lines]
        targets = {int(target, 16) for address, op, target in lines
                   if op.startswith('j') and target and int(target, 16) <= int(address, 16)}
        padding = {}
        for target in targets:
            index = addresses.index(target)
            start = index
            while start > 0 and lines[start - 1][1] in ('nop', 'xchg'):
                start -= 1
            padding[target] = target - addresses[start]
        return padding

    residues = set()
    for prefix in range(16):
        # Four- and seven-byte additions shift the loops by every residue.
        small, large = prefix % 4, prefix // 4
        source.write_text(loops.replace('PREFIX', '    p = p + 1;\n' * small + '    p = p + 1000;\n' * large))
        compile_source(compiler, source, binary, '--raw')
        run(binary, expected(small, large))
        assembly = disassemble(binary)
        padding = heads(assembly)
        assert len(padding) == 4 and all(target % 16 == 0 for target in padding), (prefix, padding)
        residues.update(padding.values())
        main_call = int(re.search(r'<_start>:.*?\bcall\s+([0-9a-f]+)', assembly, re.S)[1], 16)
        calls = {int(target, 16) for target in re.findall(r'\bcall\s+([0-9a-f]+)', assembly)} - {main_call}
        assert calls and all(target % 16 == 0 for target in calls), (prefix, calls)
        compile_source(compiler, source, binary, '--raw', '--no-code-align')
        run(binary, expected(small, large))
        assert not re.search(r'\bnop\b', disassemble(binary)), prefix
    # Fall-through entries execute the padding: every amount 0..15 occurs.
    assert residues == set(range(16)), residues
    # RAW exit needs a platform runtime on Windows; a global keeps the result live.
    source.write_text(source.read_text().replace('exit(', 'let result: Any = ('))
    compile_source(compiler, source, work / 'align.exe', '--raw', '--target', 'x86_64-windows')
    padding = heads(disassemble(work / 'align.exe'))
    assert len(padding) == 4 and all(target % 16 == 0 for target in padding), padding
    print('PASS aligned bodies and loop heads at every padding amount 0..15 (ELF, PE), unchanged with --no-code-align', flush=True)


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
        raw_ccall6_words(compiler, work)
        raw_full_width_bitwise(compiler, work)
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
        assert re.search(r'\bshr\s+rcx,0x3f\b', function(assembly, 'wrapped'))
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
                elif divisor < 0:
                    assert re.search(r'\bidiv\b', body), (divisor, body)
                else:
                    # Every positive power of two the compiler represents uses shifts (#84).
                    assert not re.search(r'\bidiv\b', body), (divisor, body)
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
        dead_branch_copies(compiler, work)
        remainder_branches(compiler, work)
        wide_powers(compiler, work)
        logical_branches(compiler, work)
        small_multipliers(compiler, work)
        local_recurrences(compiler, work)
        local_registers(compiler, work)
        promoted_parameters(compiler, work)
        direct_local_operations(compiler, work)
        memory_encodings(compiler, work)
        fused_addresses(compiler, work)
        select_diamonds(compiler, work)

        unit = work / 'unit'
        compile_source(compiler, HERE / 'backend/x86_codegen.may', unit)
        unit_output = run(unit)
        print('PASS immediate/reciprocal boundaries, IR_TRUE/IR_FALSE and fusion guards', flush=True)
        code_alignment(compiler, work, unit_output)

        compile_source(compiler, HERE / 'backend/raw_performance.may', binary, '--raw')
        for _ in range(3):
            results = parse_output(run(binary))
            assert {name: row['checksum'] for name, row in results.items()} == CHECKSUMS
        reference = work / 'reference'
        subprocess.run(['gcc', '-O3', '-march=native', '-std=c11',
                        str(HERE / 'backend/raw_performance.c'), '-o', str(reference)], check=True)
        assert {name: row['checksum'] for name, row in parse_output(run(reference)).items()} == CHECKSUMS
        print('PASS all six issue #76 workload checksums across three runs', flush=True)

        compile_source(compiler, HERE / 'backend/raw_suite.may', binary, '--raw')
        assert parse_output(run(binary), EXTENDED_CHECKSUMS).keys() == EXTENDED_CHECKSUMS.keys()
        subprocess.run(['gcc', '-O3', '-march=native', '-std=c11',
                        str(HERE / 'backend/raw_suite.c'), '-o', str(reference)], check=True)
        assert parse_output(run(reference), EXTENDED_CHECKSUMS).keys() == EXTENDED_CHECKSUMS.keys()
        print('PASS all eleven extended-suite workload checksums against C', flush=True)


if __name__ == '__main__':
    main()
