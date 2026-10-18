# MayWar

Core War written in Maylang. In Core War, two or more programs share a ring of
memory called the *core*. Each program tries to make its opponents run an
illegal instruction (`DAT`), so the last one still running wins. The programs
are called *warriors* and are written in an assembly language called Redcode.

MayWar has four parts:

* **an assembler** for ICWS'94 Redcode: labels, `EQU`, `ORG`/`END`,
  expressions, all 16 opcodes, the 7 modifiers and the 8 addressing modes;
* **a MARS** (Memory Array Redcode Simulator) with process queues, `SPL`
  multitasking and '94 operand semantics, including the post-increment timing
  that silk-style papers rely on;
* **a live view** that draws the 8000-cell core as a 24-bit colour map in
  the terminal. Each warrior has its own colour, which fades as its writes get
  older. DAT bombs are dim and running processes are white;
* **a hill**: a round-robin tournament with a standings table and the head-to-head
  points for each pairing.

## Build and play

MayWar is a [`may` workspace](../../../tools/may/README.md). Build the `may`
runner once from the repository root, then run commands from this directory:

```sh
compiler/mayc/mayc_new tools/may/main.may -o /tmp/may
export MAYC="$PWD/compiler/mayc/mayc_new"
cd examples/games/maywar
/tmp/may run -- demo                       # Nosferatu vs Silkworm vs Lookout, live
/tmp/may run -- watch dwarf mice           # any two (or more) warriors
/tmp/may run -- battle mice dwarf --rounds 50
/tmp/may run -- hill                       # every built-in warrior
```

The examples below write `maywar` for `/tmp/may run --`.

`watch` needs a terminal with 24-bit colour that is at least 102 columns wide
and 45 lines tall. Use `--cols 80` on narrower terminals, and `--speed`/`--delay`
to change the playback speed. If you interrupt it with Ctrl-C, run `tput cnorm`
to get the cursor back.

## The built-in hill

| Name | Strategy |
| --- | --- |
| `imp` | `MOV 0, 1` copies itself one cell ahead. It is almost impossible to kill, and it never kills anything. |
| `dwarf` | Drops a `DAT` on every fourth cell. Its body is four cells long, so the bombs land beside it. |
| `mice` | A replicator from 1986: it copies its body, splits into the copy, and repeats. |
| `silkworm` | Silk-style paper: eight processes copy the body in lockstep, and the colony grows exponentially. |
| `lookout` | A scanner: it searches the core for anything that is not empty and traps it with `SPL 0`. Then it clears the core with `DAT` and becomes an imp. |
| `nosferatu` | A vampire: it scatters `JMP` fangs that send enemy processes into a pit, then closes the pit. |

Like rock-paper-scissors, no warrior beats all the others. Paper outlasts
bombers, scanners catch paper, and vampires feed on bombers:

```
$ maywar hill --rounds 10
  #  warrior       W    L    T  score | Silk Mice Look Nosf  Imp Dwar
  1  Silkworm     21    5   24     87 |    -    5   20   20   12   30
  2  Mice         21    7   22     85 |   20    -    3   24   16   22
  3  Lookout      14   15   21     63 |    5   24    -   11   10   13
  ...
```

## Write your own warrior

Use `maywar show dwarf > dwarf.red` to get a starting point, then edit
the file:

```
;name   Stepper
;author you
step    EQU     3044             ; a multiple of 4 never lands on our own code
bomb    DAT     #0, #0
start   ADD     #step, bomb      ; move the target
        MOV     bomb, @bomb      ; drop the bomb there
        JMP     start
        END     start
```

Choose the step with care. With `step EQU 2667`, the third bomb lands on
`2667 × 3 = 8001`, which is one cell past `bomb`: the warrior's own `ADD`.
That version loses every round.

`maywar check stepper.red` prints the assembled listing in canonical
form, with modifiers and relative offsets. Any `.red` file can be used wherever
a built-in name is accepted:

```sh
maywar battle stepper.red dwarf --rounds 100
maywar hill stepper.red imp dwarf mice silkworm lookout nosferatu
```

Default rules: core size 8000, 8000 processes per warrior, 80000 cycles per
round, warriors up to 100 instructions, placed at least 100 cells apart. Change
them with `--core` and `--cycles`. Placement is random but reproducible: use
`--seed`.

## Tests

```sh
/tmp/may build test
```

The `test` task builds the app and runs `tests/test_maywar.py` against it. It
is a task rather than a `may test` group because it drives the compiled binary
from Python. The suite covers assembler output and error reports, the semantics of each
instruction family, lone survival of every built-in warrior, deterministic
matches and classic matchups (for example, Mice beats Dwarf).

## Files

* `src/redcode.may`: opcodes, modifiers, addressing modes and '94 default modifiers.
* `src/asm.may`: the two-pass assembler and expression evaluator.
* `src/mars.may`: the simulator, warrior placement and match play.
* `src/view.may`: the terminal colour map.
* `src/hill.may`: the built-in warriors.
* `main.may`: the command-line interface and the hill tournament.

Not implemented: P-space (`LDP`/`STP`) and the `FOR`/`ROF` macros.
