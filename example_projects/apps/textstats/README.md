# textstats — a text analytics CLI in Maylang

Reads text, tokenises it, counts words and prints a ranked frequency report.
It is split across modules and compiles to a **freestanding native executable**
(or runs on the bytecode VM — the same source, both targets).

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
# native executable (ELF on Linux, Mach-O on macOS):
make
./build/textstats < sample.txt
cat somefile.txt | ./build/textstats

# the same code on the bytecode VM:
maylang run main.may < sample.txt
```

Example:

```
$ printf 'red fish blue fish\nred fish\n' | ./build/textstats
----------------------------------------------
  TEXT STATISTICS
----------------------------------------------
words 6  unique 3  avg 3.83
longest three
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
* higher-order functions compiled inline: `map`, `reduce`, and function-valued
  arguments (`|w| len(w)`)
* `match`-free control flow, `??`, and multi-argument `print`
* reading standard input (`read_stdin`)

No floats are used: the average length is printed as a fixed-point value built
from integer arithmetic, so the whole program stays inside the native subset.
