# textstats — a text analytics CLI in Maylang

Reads text, tokenises it, counts words and prints a ranked frequency report.
It uses typed modules, records and collections and compiles to a native
Linux x86-64 executable with the full runtime. Toolchain bundle verification
builds it using the extracted compiler and checks a known frequency report.

```
example_projects/apps/textstats/
├── src/
│   ├── text.may     whitespace normalisation, punctuation stripping, tokenising
│   ├── stats.may    counting, ranking, average length, longest word
│   └── report.may   padding, bars, table rendering
├── build/           compiled executable
├── main.may         driver (reads stdin)
└── sample.txt       example input
```

## Build and run

```sh
# native executable (Linux x86-64 full runtime):
make
./build/textstats < sample.txt
cat somefile.txt | ./build/textstats
```

Example:

```
$ printf 'red fish blue fish\nred fish\n' | ./build/textstats
----------------------------------------------
  TEXT STATISTICS
----------------------------------------------
words 6  unique 3  avg 3.66
longest fish
----------------------------------------------
fish               3     ###
red                2     ##
blue               1     #
----------------------------------------------
```

## What it exercises in the native backend

* dynamic strings and concatenation (`+`), `str`, and the prelude's
  `split` / `trim` / `to_lower` / `repeat`
* string indexing and `char_at` / `char_from` (used to normalise whitespace and
  strip punctuation)
* maps for counting, with `map_get` / `map_set` / `keys`
* lists, `push`, `len`, `for … in`
* typed higher-order functions: `map`, `reduce`, and function-valued
  arguments (`|w: Str| -> Int { return len(w); }`)
* `match`-free control flow, `??`, and multi-argument `print`
* reading standard input (`read_stdin`)

The average length uses integer arithmetic. Maps and records require the full
runtime, so the core cross-target subset does not support this application.

Input tokenization currently recognizes ASCII letters and digits; punctuation
and non-ASCII letters are removed. A later Unicode tokenizer needs its own
behavioral tests.
