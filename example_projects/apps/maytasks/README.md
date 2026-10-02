# maytasks

A tiny, everyday task manager written in Maylang. It keeps one JSON file
(`$HOME/.maytasks.json`) and can be used interactively or as a one-shot CLI.

## Build

```sh
make
./build/maytasks add "buy oat milk"
```

## One-shot commands

```sh
./build/maytasks add "buy oat milk"
./build/maytasks add "write the GC docs"
./build/maytasks list
./build/maytasks done 2
./build/maytasks edit 1 "buy oat milk and bread"
./build/maytasks find milk
./build/maytasks stats
./build/maytasks rm 2
./build/maytasks clear
```

## Interactive shell

Run it with no arguments:

```sh
$ ./build/maytasks
maytasks — your list is saved to /home/you/.maytasks.json
Type `help` for commands.
tasks> add walk the dog
  added #1: walk the dog
tasks> ls
Open (1):
  1. [ ] walk the dog
tasks> done 1
  completed: walk the dog
tasks> stats
  total 1 | open 0 | done 1 (100%)
tasks> q
by the way, you have 0 open task(s).
```

## Commands

| Command | Effect |
|---------|--------|
| `add <text>` | add a task |
| `list`, `ls` | show open and completed tasks |
| `done <id>` | mark complete |
| `undone <id>` | mark incomplete |
| `edit <id> <text>` | replace text |
| `rm <id>` | delete |
| `clear` | delete completed tasks |
| `find <text>` | search text (case-insensitive) |
| `stats` | counts and completion % |
| `help` | help |
| `quit`, `q`, `exit` | leave the shell |

## Files

* `src/tasks.may` — the task model and JSON persistence.
* `main.may` — entry point, argument handling, dispatcher and shell.
