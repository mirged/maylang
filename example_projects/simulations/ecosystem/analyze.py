#!/usr/bin/env python3
"""Plot recorded data; never run or implement the ecosystem simulation."""
import argparse
import json
import os
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('summary', type=Path)
    args = parser.parse_args()
    os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir())/'maylang-ecosystem-matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data = json.loads(args.summary.read_text())
    rows = data['history']
    generations = [row['generation'] for row in rows]
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), layout='constrained')
    colors = {'grazer': '#348848', 'hunter': '#bd4536', 'scavenger': '#a67920', 'mixed': '#5b5a99', 'inactive': '#999999'}
    for name, color in colors.items():
        axes[0, 0].plot(generations, [r['strategies'][name] for r in rows], label=name, color=color, linewidth=1.5)
    axes[0, 0].set(title='Observed adult strategies', ylabel='Creatures')
    axes[0, 0].legend(ncol=3, fontsize=8)
    for key, label in [('mean_metabolic_pace', 'metabolic pace'), ('mean_mobility', 'mobility'), ('mean_diet', 'animal digestion'), ('mean_armor', 'armor')]:
        axes[0, 1].plot(generations, [r[key] for r in rows], label=label)
    axes[0, 1].set(title='Inherited physiology', ylabel='Mean gene value', ylim=(-0.05, 1.05))
    axes[0, 1].legend(fontsize=8)
    axes[1, 0].plot(generations, [r['population_next'] for r in rows], color='#3d6080', label='offspring population')
    axes[1, 0].set(title='Population and trait diversity', ylabel='Admitted offspring')
    right = axes[1, 0].twinx()
    right.plot(generations, [r['genetic_variance'] for r in rows], color='#b37735', alpha=.8)
    right.set_ylabel('Mean physiology variance', color='#b37735')
    axes[1, 1].plot(generations, [r['kills_total'] for r in rows], color=colors['hunter'])
    axes[1, 1].set(title='Cumulative live-prey kills', ylabel='Kills')
    for ax in axes.flat:
        ax.set_xlabel('Genetic generation')
        ax.grid(alpha=.2)
        ax.ticklabel_format(axis='x', style='plain')
    fig.suptitle(f"Artificial Ecosystem — seed {data['config']['seed']}, {data['generations_completed']:,} generations", fontsize=15)
    prefix = args.summary.with_name(args.summary.name.removesuffix('.summary.json'))
    for extension in ('png', 'svg'):
        fig.savefig(str(prefix)+'.'+extension, dpi=160)
    last = data['last_cohort']
    total = data['totals']
    first = total['first_hunt']
    note = ('No live-prey kill occurred.' if first < 0 else f'The first live-prey kill occurred in generation {first:,}.')
    text = f'''# Recorded experiment

Seed {data['config']['seed']}; {data['generations_completed']:,} actual genetic generations;
status `{data['status']}`; final population {data['population']}.
Measured simulation time: {data['elapsed_seconds']:.1f} seconds, summed across workers.

{note} There were {total['kills']:,} kills from {total['attacks']:,} attacks.
Assimilated energy totals: plants {total['plant_energy']:.1f},
carrion {total['scavenged_energy']:.1f}, live prey {total['hunted_energy']:.1f}.

Last sampled adult cohort (generation {last['generation']:,}):
{last['strategies']['grazer']} grazers, {last['strategies']['hunter']} hunters,
{last['strategies']['scavenger']} scavengers, {last['strategies']['mixed']} mixed,
{last['strategies']['inactive']} inactive.
Mean mass {last['mean_mass']:.3f}, metabolic pace {last['mean_metabolic_pace']:.3f},
mobility {last['mean_mobility']:.3f}, diet {last['mean_diet']:.3f},
armor {last['mean_armor']:.3f}, reproductive reserve {last['mean_reproduction_reserve']:.3f}.
Mean physiology variance {last['genetic_variance']:.6f}.

Energy ledger residual: {data['energy_error']:.6g} energy units, versus
{total['initial_energy'] + total['sunlight']:.6g} cumulative input.

![Recorded strategies and traits]({prefix.name}.png)

These are observations from one finite-population simulation. They depend on
its resource supply, discrete cohort life cycle, mutation settings and neural
controller. They do not establish universal evolutionary outcomes. Strategy
labels describe actual intake; they were not assigned to creatures in advance.
The summary and lossless checkpoint record the complete settings.
'''
    prefix.with_suffix('.md').write_text(text)
    print(f'Wrote {prefix.name}.png, .svg and .md from recorded simulation data')


if __name__ == '__main__':
    main()
