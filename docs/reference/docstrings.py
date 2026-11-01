"""Parse and check Maylang `///` doc comments.

The format is described in docs/guide/DOCSTRINGS.md. Both API generators
(docs/reference/generate.py and tools/maylsp/docs/generate.py) read doc
comments through this module, so the source comment is the only place a
declaration's description is written.
"""
import re

SECTIONS = ('Params', 'Returns', 'Faults', 'Example')
WIDTH = 100
HEADER = re.compile(r'^(?P<name>[A-Z][a-z]+):(?:\s+(?P<rest>.*))?$')
# Section names that are easy to type instead of the standard ones.
NEAR_MISSES = {'Param', 'Parameters', 'Args', 'Arguments', 'Return', 'Fault', 'Errors',
               'Raises', 'Throws', 'Examples', 'Usage'}
PARAM = re.compile(r'^- `(?P<name>[A-Za-z_]\w*(?:\.\.\.)?)`: (?P<text>.+)$')
# Leading words that make a summary descriptive rather than imperative.
NOT_IMPERATIVE = {'A', 'An', 'The', 'This', 'Whether', 'True', 'False', 'Number', 'Used',
                  'Internal', 'Helper', 'Wrapper', 'Function', 'Returns'}
IMPERATIVE_S = {'Focus'}


def comment_block(lines, index):
    """Return the raw `///` block that ends just above line `index` (0-based).

    Each line loses its indentation, the `///` marker and one following
    space; further indentation is kept for code and list continuations.
    """
    block = []
    i = index - 1
    while i >= 0 and lines[i].lstrip().startswith('///'):
        text = lines[i].lstrip()[3:]
        block.insert(0, (text[1:] if text.startswith(' ') else text).rstrip())
        i -= 1
    return block, i + 1


def parse(block):
    """Split a raw comment block into summary, details and sections."""
    doc = dict(summary='', details=[], params=[], returns='', faults='', example=None,
               order=[], errors=[])
    prelude, current, fence = [], None, False
    sections = {name: [] for name in SECTIONS}
    for line in block:
        header = None if fence else HEADER.match(line)
        if header and header['name'] in SECTIONS:
            current = header['name']
            if current in doc['order']:
                doc['errors'].append(f'repeated {current}: section')
            doc['order'].append(current)
            if header['rest']:
                sections[current].append(header['rest'])
            continue
        if header and header['name'] in NEAR_MISSES:
            doc['errors'].append(f'unknown section {header["name"]}:; use one of '
                                 + ', '.join(s + ':' for s in SECTIONS))
        if line.strip().startswith('```'):
            fence = not fence
        (prelude if current is None else sections[current]).append(line)
    if fence:
        doc['errors'].append('unterminated ``` fence')
    paragraphs = [' '.join(part.split()) for part in '\n'.join(prelude).split('\n\n') if part.strip()]
    if paragraphs:
        doc['summary'], doc['details'] = paragraphs[0], paragraphs[1:]
    for line in sections['Params']:
        if not line.strip():
            continue
        item = PARAM.match(line)
        if item:
            doc['params'].append([item['name'], item['text'].strip()])
        elif line.startswith('  ') and doc['params']:
            doc['params'][-1][1] += ' ' + line.strip()
        else:
            doc['errors'].append('Params: items must look like "- `name`: description": ' + line.strip())
    doc['params'] = [tuple(p) for p in doc['params']]
    for name in ('Returns', 'Faults'):
        doc[name.lower()] = ' '.join(' '.join(sections[name]).split())
    if 'Example' in doc['order']:
        body = '\n'.join(sections['Example']).strip('\n')
        match = re.fullmatch(r'```may\n(.*?)\n?```', body, re.S)
        if match:
            doc['example'] = match[1]
        else:
            doc['errors'].append('Example: must be a single ```may fenced block')
    if doc['order'] != sorted(doc['order'], key=SECTIONS.index):
        doc['errors'].append('sections must appear in the order ' + ', '.join(SECTIONS))
    return doc


def parameter_names(signature):
    """Names of the parameters in a `fun` signature (generic clauses skipped)."""
    head = signature.split('(', 1)
    if len(head) < 2:
        return []
    depth, current, names = 0, '', []
    for c in head[1]:
        if c in '(<[{':
            depth += 1
        elif c == '>' and current.endswith('-'):
            pass  # the arrow of a function type
        elif c in ')>]}':
            if depth == 0:
                break
            depth -= 1
        if c == ',' and depth == 0:
            names.append(current)
            current = ''
        else:
            current += c
    names.append(current)
    return [n.split(':')[0].strip() for n in names if n.strip()]


def problems(doc, kind, signature, raw_lines):
    """Ways a parsed comment departs from the standard."""
    found = list(doc['errors'])
    summary = doc['summary']
    if not summary:
        return found + ['missing /// doc comment']
    if not summary.endswith(('.', '.`', '.)')):
        found.append('summary must be a sentence ending with a period')
    first = summary.split()[0]
    if kind == 'fun' and (first in NOT_IMPERATIVE or (first.endswith('s') and not first.endswith('ss') and first not in IMPERATIVE_S
                                                      and first[0].isupper())):
        found.append(f'function summary must start with an imperative verb, not "{first}"')
    if kind == 'fun':
        actual = parameter_names(signature)
        for name, _ in doc['params']:
            if name not in actual:
                found.append(f'Params: documents `{name}`, which is not a parameter')
    elif doc['params']:
        found.append('Params: is only for functions')
    for line in raw_lines:
        if len(line) > WIDTH:
            found.append(f'doc comment line longer than {WIDTH} columns')
            break
    return found


def markdown(doc, params=True):
    """Render a parsed comment as the Markdown used by editor hovers."""
    parts = [doc['summary']] + doc['details']
    if params and doc['params']:
        parts.append('**Parameters**\n' + '\n'.join(f'- `{n}`: {t}' for n, t in doc['params']))
    if doc['returns']:
        parts.append('**Returns:** ' + doc['returns'])
    if doc['faults']:
        parts.append('**Faults:** ' + doc['faults'])
    if doc['example'] is not None:
        parts.append('**Example**\n```may\n' + doc['example'] + '\n```')
    return '\n\n'.join(p for p in parts if p)
