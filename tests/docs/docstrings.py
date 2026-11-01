#!/usr/bin/env python3
"""Check the doc comment parser and checker in docs/reference/docstrings.py."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'docs/reference'))
import docstrings  # noqa: E402
import generate  # noqa: E402

SIGNATURE = 'fun scale<T>(x: Int, factor: (T) -> Int) -> Int'


def block(text):
    """Raw comment lines for `text`, as they appear above a declaration."""
    lines = ['/// ' + line if line else '///' for line in text.split('\n')]
    return docstrings.comment_block(lines + ['fun f() -> Nil { return; }'], len(lines))[0]


def problems(text, kind='fun', signature=SIGNATURE):
    lines = ['/// ' + line if line else '///' for line in text.split('\n')] if text else []
    return docstrings.problems(docstrings.parse(block(text) if text else []), kind, signature, lines)


def expect(text, fragment, **kwargs):
    found = problems(text, **kwargs)
    assert any(fragment in p for p in found), (text, fragment, found)


full = docstrings.parse(block('''Scale `x` by `factor`.

Detail with
two lines.

Params:
- `x`: The value.
- `factor`: The multiplier, which
  may be negative.

Returns: The
product.

Faults: `arithmetic` on overflow.

Example:
```may
if (true) {
    print(scale(2, 3));
}
```'''))
assert full['summary'] == 'Scale `x` by `factor`.', full
assert full['details'] == ['Detail with two lines.'], full
assert full['params'] == [('x', 'The value.'), ('factor', 'The multiplier, which may be negative.')], full
assert full['returns'] == 'The product.' and full['faults'] == '`arithmetic` on overflow.', full
assert full['example'] == 'if (true) {\n    print(scale(2, 3));\n}', full
assert full['errors'] == [] and docstrings.parameter_names(SIGNATURE) == ['x', 'factor']
assert docstrings.parameter_names('fun f(g: (Int) -> Int, h: Map<Str, List<Int>>) -> Int') == ['g', 'h']
assert docstrings.parameter_names('fun now() -> Int') == []
assert docstrings.markdown(full) == (
    'Scale `x` by `factor`.\n\nDetail with two lines.\n\n**Parameters**\n- `x`: The value.\n'
    '- `factor`: The multiplier, which may be negative.\n\n**Returns:** The product.\n\n'
    '**Faults:** `arithmetic` on overflow.\n\n**Example**\n```may\nif (true) {\n    print(scale(2, 3));\n}\n```')

# Accepted forms.
assert problems('Return the sum.') == []
assert problems('Report whether `x` is set.') == []
assert problems('Focus the input.') == []
assert problems('Process every item.') == []
assert problems('A TCP socket handle.', kind='struct', signature='struct Socket { fd: Int }') == []
assert problems('Run it.\n\nExample:\n```may\n// Returns: not a section inside a fence\nprint(1);\n```') == []

# Rejected forms.
expect('', 'missing /// doc comment')
expect('Return the sum', 'ending with a period')
expect('Returns the sum.', 'imperative verb, not "Returns"')
expect('Whether `x` is set.', 'imperative verb, not "Whether"')
expect('The first element.', 'imperative verb, not "The"')
expect('Gets the value.', 'imperative verb, not "Gets"')
expect('Scale it.\n\nParameters:\n- `x`: The value.', 'unknown section Parameters:')
expect('Scale it.\n\nParams:\n- `y`: Not a parameter.', 'documents `y`, which is not a parameter')
expect('Scale it.\n\nParams:\nx is the value.', 'Params: items must look like')
expect('Scale it.\n\nReturns: Twice.\n\nParams:\n- `x`: The value.', 'sections must appear in the order')
expect('Scale it.\n\nReturns: One.\n\nReturns: Two.', 'repeated Returns: section')
expect('Scale it.\n\nExample:\nprint(1);', 'Example: must be a single ```may fenced block')
expect('Scale it.\n\nExample:\n```may\nprint(1);', 'unterminated ``` fence')
expect('Scale ' + 'x' * 100 + '.', 'longer than 100 columns')
expect('A handle.\n\nParams:\n- `x`: No.', 'Params: is only for functions', kind='struct', signature='struct S { x: Int }')

# A source-backed catalog entry cannot carry its own text.
saved = generate.CATALOG['Functions']['sort']
try:
    generate.CATALOG['Functions']['sort'] = {'source': 'native.may', 'summary': 'Stale text.'}
    try:
        generate.catalog()
        raise AssertionError('catalog() accepted a source-backed entry with text')
    except AssertionError as error:
        assert "remove ['summary']" in str(error), error
finally:
    generate.CATALOG['Functions']['sort'] = saved
entry = generate.catalog()['Functions']['sort']
assert entry['signature'] == 'sort(xs)' and entry['summary'] and entry['example'], entry

print('PASS doc comment parsing, rendering and checks')
