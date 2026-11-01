#!/usr/bin/env python3
"""Regenerate list-only API pages from Maylang declarations and descriptions."""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CATALOG = json.loads((ROOT / 'tools/maylsp/docs/reference.json').read_text())
DESCRIPTIONS = json.loads((HERE / 'descriptions.json').read_text())
sys.path.insert(0, str(HERE))
import docstrings  # noqa: E402

GUIDE = 'docs/guide/DOCSTRINGS.md'


def inline(value):
    # Flatten multiline source without letting // comments swallow later code.
    def flatten(match):
        token = match[0]
        if token.startswith('"'):
            return token.replace('\n', r'\n').replace('\r', r'\r').replace('\t', r'\t')
        return ' '
    value = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|\s+', flatten, str(value), flags=re.S).strip()
    fence = '``' if '`' in value else '`'
    return fence + value + fence


def masked(text):
    # Preserve offsets/newlines while ignoring braces in strings and comments.
    return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                  lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), text, flags=re.S)


def declarations(path):
    source = path.read_text()
    lines = source.split('\n')
    mask = masked(source)
    depth = [0] * (len(mask) + 1)
    for i, c in enumerate(mask):
        depth[i + 1] = depth[i] + (c == '{') - (c == '}')
    found = []
    for m in re.finditer(r'^(?P<pub>pub\s+)?(?P<kind>fun|struct|enum|let|mut)\s+(?P<name>\w+)', source, re.M):
        if depth[m.start()] != 0:
            continue
        kind = m['kind']
        if kind in ('let', 'mut'):
            end = mask.find(';', m.end()) + 1
            body = ''
            signature = source[m.start():end].strip()
        else:
            opening = mask.find('{', m.end())
            end = opening + 1
            while end < len(mask) and depth[end + 1] != 0:
                end += 1
            end += 1
            body = source[opening + 1:end - 1]
            signature = source[m.start():opening].strip()
            if kind != 'fun':
                signature = source[m.start():end].strip()
        line = source.count('\n', 0, m.start()) + 1
        block, first = docstrings.comment_block(lines, line - 1)
        found.append(dict(name=m['name'], kind=kind, public=bool(m['pub']),
                          signature=signature, body=body, doc=docstrings.parse(block),
                          raw=lines[first:line - 1], line=line))
    return found


PROSE = ('summary', 'parameters', 'returns', 'faults', 'notes', 'example')


def catalog():
    """The editor catalog, with source-backed entries filled from their /// comments.

    An entry such as `"sort": {"source": "native.may"}` names the stdlib file
    that defines the function; its signature, prose and example come from the
    declaration there, so the catalog cannot drift from the source.
    """
    resolved = {group: dict(entries) for group, entries in CATALOG.items()}
    sources = {}
    for name, e in CATALOG['Functions'].items():
        if 'source' not in e:
            continue
        extra = [k for k in e if k != 'source']
        assert not extra, f'reference.json {name}: remove {extra}; write them in the /// comment in stdlib/{e["source"]} ({GUIDE})'
        if e['source'] not in sources:
            sources[e['source']] = {d['name']: d for d in declarations(ROOT / 'stdlib' / e['source'])}
        d = sources[e['source']].get(name)
        assert d and d['kind'] == 'fun', f'reference.json {name}: no function {name} in stdlib/{e["source"]}'
        doc = d['doc']
        assert doc['summary'] and doc['example'] is not None, f'stdlib/{e["source"]}:{d["line"]}: {name} needs a summary and an Example: section'
        params = docstrings.parameter_names(d['signature'])
        resolved['Functions'][name] = dict(
            signature=name + '(' + ', '.join(params) + ')', summary=doc['summary'],
            parameters=[dict(name=n, description=t) for n, t in doc['params']],
            returns=doc['returns'], faults=doc['faults'], notes='\n\n'.join(doc['details']),
            example=doc['example'], source=e['source'])
    return resolved


def lint(path, ds):
    # Every documented declaration must follow the docstring standard.
    out = []
    rel = path.relative_to(ROOT).as_posix()
    for d in ds:
        for problem in docstrings.problems(d['doc'], d['kind'], d['signature'], d['raw']):
            out.append(f'{rel}:{d["line"]}: {d["name"]}: {problem}')
    return out


def render_module(path, module=None):
    module = module or path.relative_to(ROOT / 'stdlib').as_posix()
    ds = declarations(path)
    explicit = any(d['public'] for d in ds)
    out = ['- **' + module + '** — ' + DESCRIPTIONS['modules'][module],
           '- Availability: ' + 'full Linux x86-64 runtime.',
           '- Import: ' + inline('import "' + module.removesuffix('.may') + '" as library;') + '.',
           '- Signatures below reproduce the source, including dynamic `Any` boundaries; parameter order and types are the call contract.',
           '- Visibility: ' + ('only declarations marked `pub` are exported.' if explicit else 'all top-level declarations are exported because this module has no `pub` declarations.'),
           '- Source: [implementation](' + '../' * (3 + module.count('/')) + 'stdlib/' + module + ').',
           '- Shared contracts: [mutation, errors, Unicode, numeric limits and supported runtimes](' + '../' * (3 + module.count('/')) + 'stdlib/CONTRACTS.md).']
    for note in DESCRIPTIONS.get('notes', {}).get(module, []):
        out.append('- ' + note)
    for d in ds:
        name, doc = d['name'], d['doc']
        out.append('- **' + name + '** — ' + inline(d['signature']) + ' — ' + doc['summary'])
        if explicit and not d['public']:
            out.append('- ' + inline(name) + ': private implementation helper; unavailable to importing modules.')
        out.extend('- ' + inline(name) + ': ' + note for note in doc['details'])
        for p, text in doc['params']:
            out.append('- ' + inline(name) + ' parameter ' + inline(p) + ': ' + text)
        if doc['returns']:
            out.append('- ' + inline(name) + ' returns: ' + doc['returns'])
        if doc['faults']:
            out.append('- ' + inline(name) + ' faults: ' + doc['faults'])
        if d['kind'] == 'fun':
            # Keep literal failure messages as useful, source-verifiable preconditions.
            errors = re.findall(r'\b(?:fail|raise_error|net_fault)\(\s*("(?:\\.|[^"\\])*")', d['body'])
            if errors:
                out.append('- ' + inline(name) + ' explicit fault strings: ' + ', '.join(inline(s) for s in dict.fromkeys(errors)) + '; runtime/callback faults can also propagate.')
        if doc['example'] is not None:
            out.append('- ' + inline(name) + ' example: ' + inline(doc['example']) + '.')
    return '\n'.join(out) + '\n', ds


def render_catalog(groups):
    out = ['- **Language catalog** — syntax, types and operators for the strict self-hosted compiler.',
           '- Read [language guide](LANGUAGE.md) for semantics and implementation restrictions; signatures and examples here come from the maintained editor catalog.']
    for group in groups:
        out.append('- **' + group + '**.')
        for name, e in CATALOG[group].items():
            out.append('- **' + name + '** — ' + inline(e['signature']) + ' — ' + e['summary'])
            if e.get('notes'):
                out.append('- ' + inline(name) + ': ' + e['notes'])
            out.append('- ' + inline(name) + ' example: ' + inline(e['example']) + '.')
    return '\n'.join(out) + '\n'


def render_runtime():
    out = ['- **Runtime API** — built-ins and automatically available full-runtime functions for self-hosted mayc.',
           '- These signatures describe calls; dynamic values may have several runtime types. Read [native module](stdlib/native.md) for exact source-defined signatures and additional automatically loaded helpers.',
           '- Availability: full Linux x86-64 runtime.',
           '- String method syntax forwards the receiver as the first argument: `s.trim()` = `trim(s)`, `s.split(",")` = `split(s, ",")`; the same convention applies to library helpers.',
           '- Errors: I/O, parsing, arithmetic, type, indexing and callback faults may propagate; catch recoverable failures with `may ... otherwise`.',
           '- Pointer operations use integer machine addresses; syscall results/ABI and memory validity remain the caller’s responsibility.']
    for name, e in catalog()['Functions'].items():
        if name == 'err':
            out.append('- **err** — handler-scoped structured error value, not a callable function; fields include kind, message and stack.')
            continue
        out.append('- **' + name + '** — ' + inline(e['signature']) + ' — ' + e['summary'])
        for p in e.get('parameters', []):
            out.append('- ' + inline(name) + ' parameter ' + inline(p['name']) + ': ' + p['description'])
        if e.get('returns'):
            out.append('- ' + inline(name) + ' returns: ' + e['returns'])
        if e.get('faults'):
            out.append('- ' + inline(name) + ' faults: ' + e['faults'])
        if e.get('notes'):
            out.append('- ' + inline(name) + ': ' + e['notes'])
        out.append('- ' + inline(name) + ' example: ' + inline(e['example']) + '.')
    for name, (signature, description) in DESCRIPTIONS['runtime_extra'].items():
        out.append('- **' + name + '** — ' + inline(signature) + ' — ' + description)
    out.extend(['- Additional automatic helpers: [native API](stdlib/native.md) includes pi/e, hyperbolic functions, chr/ord, sign, parse_int/parse_float, range_step, Result/Option constructors, list utilities and error/JSON support.',
                '- Low-level C: `ccall(fn, args)` reads at most six integer arguments; `extern_c(fn)` creates a wrapper with exactly six positional parameters. Typed extern declarations handle supported scalar C signatures instead.',
                '- Compiler intrinsic implementation names beginning with `__` are reserved support machinery: host allocation/write/exit, floating-point operations, stack/unwind operations and fiber entry/switch. They are not user-level APIs.',
                '- Full-runtime `range` takes two arguments; `input` takes a prompt (use nil to suppress it). Source-defined helpers in native.may override historical shorthand from older toolchains.'])
    return '\n'.join(out) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='verify generated pages and coverage without writing')
    args = parser.parse_args()
    outputs = {HERE / 'SYNTAX.md': render_catalog(['Keywords', 'Types', 'Operators']),
               HERE / 'RUNTIME.md': render_runtime()}
    inventory, problems = [], []
    allowed = {'modules', 'notes', 'runtime_extra'}
    for key in sorted(set(DESCRIPTIONS) - allowed):
        problems.append(f'docs/reference/descriptions.json: remove "{key}"; declarations are described by their /// comments ({GUIDE})')
    sources = [(path, path.relative_to(ROOT / 'stdlib').as_posix()) for path in sorted((ROOT / 'stdlib').rglob('*.may'))]
    for path, module in sources:
        content, ds = render_module(path, module)
        problems.extend(lint(path, ds))
        outputs[HERE / 'stdlib' / Path(module).with_suffix('.md')] = content
        explicit = any(d['public'] for d in ds)
        inventory.extend(dict(module=module, name=d['name'], kind=d['kind'], signature=d['signature'], line=d['line'],
                              exported=d['public'] or not explicit,
                              runtime='full', platform='Linux x86-64',
                              status='supported') for d in ds)
    out = ['- **Standard library index** — all top-level functions, records, enums and bindings, including private helpers explicitly labeled on their module pages.',
           '- The active full-runtime sidecar is `compiler/mayc/native.may`; `stdlib/native.may` is a byte-identical mirror, checked by `make check`, that the language server and these pages read. `prelude.may` is auto-loaded; ordinary modules are imported explicitly.',
           '- Prefer namespace or selective imports when a helper shares a name with the native library.',
           '- `Any` is the actual declared type in many modules; descriptions state expected runtime values without promising additional static checks.']
    for path, module in sources:
        count = sum(d['module'] == module for d in inventory)
        out.append('- [' + module + '](stdlib/' + str(Path(module).with_suffix('.md')) + ') — ' + DESCRIPTIONS['modules'][module] + f' {count} declarations.')
    outputs[HERE / 'STDLIB.md'] = '\n'.join(out) + '\n'
    # The compiler loads runtime/math.may beside the native library, so its
    # comments appear in editor hovers too.
    math = ROOT / 'compiler/mayc/runtime/math.may'
    problems.extend(lint(math, declarations(math)))
    if problems:
        sys.exit('\n'.join(problems) + f'\n{len(problems)} doc comment problems; see {GUIDE}.')
    outputs[HERE / 'inventory.json'] = json.dumps(inventory, indent=2, ensure_ascii=False) + '\n'
    for path, content in outputs.items():
        if path.suffix == '.md':
            assert all(line.startswith('- ') for line in content.splitlines() if line.strip()), path
        if args.check:
            assert path.exists() and path.read_text() == content, f'Regenerate {path}'
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if args.check:
        for path in HERE.rglob('*.md'):
            assert all(line.startswith('- ') for line in path.read_text().splitlines() if line.strip()), f'Non-list content: {path}'
    print(f'{"Checked" if args.check else "Generated"} {len(outputs)} files; {len(inventory)} declarations across {len(DESCRIPTIONS["modules"])} modules.')


if __name__ == '__main__':
    main()
