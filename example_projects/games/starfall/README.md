# Starfall Salvage

A bite-sized, turn-based space salvage game built in Maylang. You pilot the
S.V. Wayfarer through a dangerous debris belt: scan a sector, choose whether
to risk a salvage run, keep enough fuel to jump, and spend credits before your
hull gives out. Sector signals are deterministic, so the game rewards planning
instead of dice rolls.

## Build and play

Build the playable native app from the repository root with the self-hosted
compiler:

```sh
make -C example_projects/games/starfall build
example_projects/games/starfall/build/starfall demo
```

The project is also managed with maypkg. Compile its CLI once, then inspect,
check and lock this project:

```sh
toolchain/mayc/mayc_new toolchain/maypkg/main.may -o /tmp/maypkg
cd example_projects/games/starfall
/tmp/maypkg info
/tmp/maypkg tree
/tmp/maypkg check
/tmp/maypkg verify
```

`maypkg build --script` generates `build/maypkg.build.sh` from the project graph.
Run `./build/starfall help` for the game's commands.

Reach sector 4 to lock onto the rescue beacon. Refill at relays and keep your
hull patched on the way. Commands are one action per launch, and the flight is
saved in `$HOME/.starfall.json`:

```sh
./build/starfall status
./build/starfall scan
./build/starfall salvage
./build/starfall repair
./build/starfall refuel
./build/starfall jump
./build/starfall log
```

`./build/starfall reset` starts a fresh flight. `./build/starfall demo` plays a short
unsaved sample turn sequence.

## Project layout

- `main.may` — command-line interface and demo
- `src/model.may` — pilot state and JSON save file
- `src/game.may` — deterministic sector events and turn rules
- `src/view.may` — status and flight-recorder output
- `mayproj.json` — maypkg project metadata
