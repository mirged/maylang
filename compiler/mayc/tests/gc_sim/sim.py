#!/usr/bin/env python3
"""MOSAIC M1 simulator: replay an allocation trace under grouping policies.

Reads a trace written by trace.py (format in trace_hooks.may) and, at every
collection the real program performed, simulates:

  ms          object-level mark-sweep (the current collector, the baseline)
  window      static groups: 64 KiB segments filled in allocation order
              (a generational/region proxy)
  site        static groups: one segment stream per allocation site
  learned     learned cohorts: one segment stream per lifetime class; a
              site's class comes from the survival it has shown so far
              (first-collection survival, then age at death)
  learned+fx  learned plus non-moving fracturing of reached segments that
              have survived two collections and are mostly dead
  oracle      an upper bound, not an implementable policy: one segment
              stream per actual death collection, read from the trace in a
              first pass. If the oracle fails, no lifetime predictor can pass.

(The roadmap's "static groups by fiber" policy is omitted: none of the
workloads uses fibers, so it would equal `window`.)

A cohort policy keeps a summary of outgoing edges per segment. At a
collection it marks the segments named by roots, traverses the segment graph,
and reclaims every unreached segment whole. Work is counted as:

  scanned   objects read to build or refresh summaries: every member of a
            reached segment that was never summarized or that joined it since,
            plus members whose pointers changed since the previous collection
            (a card-marking barrier), plus objects read by fracturing
  graph     segments visited plus segment edges followed plus root words

Mark-sweep work is the objects it marks; its sweep, which walks every block
of the heap, is reported separately (`ms_swept_blocks`) because a block visit
in a sweep is much cheaper than a mark. An object
reclaimed by a policy while mark-sweep finds it live is a simulator bug and
aborts the run. Dead objects keep the pointers they had when they died (an
unreachable object cannot be written), so nepotism through dead members of a
reached segment is modelled exactly.

Known optimism: the learned classes and the fracture decision use exact
survival counts from the trace, where an implementation would sample them.
Known pessimism: pointer changes are detected per collection, so a card
written and restored between collections is missed (none are counted), and
segments of new objects are scanned in full when reached.
"""
import argparse
import bisect
import json
import subprocess
import sys
import time
from array import array
from collections import deque
from pathlib import Path

SEGMENT = 65536
LARGE = 16384
TAG = 72057594037927936
LOW48 = (1 << 48) - 1
ALLOC_WORDS = 3
SITE_WORDS = 25


def symbols(binary):
    table = []
    out = subprocess.run(['nm', '-n', str(binary)], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in 'tT':
            table.append((int(parts[0], 16), parts[2]))
    return [address for address, _ in table], [name for _, name in table]


class Sites:
    """Allocation site = the first return address inside user code (the exact
    call instruction) on the rebuilt call chain; runtime and prelude frames
    are skipped.

    The trace records the first 24 return-address-shaped words above the
    allocation hook, many of them stale. The chain starts at the return into
    rt_alloc_kind whose call targets rt_trace_alloc, and each next link is the
    first later candidate whose `call rel32` targets the function containing
    the current link. A stale word almost never continues the chain."""

    def __init__(self, binary):
        self.addresses, self.names = symbols(binary)
        self.image = Path(binary).read_bytes()
        self.user = {}
        self.ids = {}
        self.labels = []
        self.chains = 0
        self.broken = 0
        self.cache = {}

    def function(self, r):
        return bisect.bisect_right(self.addresses, r) - 1

    def target(self, r):
        offset = r - 0x400000
        if offset < 4 or offset > len(self.image):
            return None
        return r + int.from_bytes(self.image[offset - 4:offset], 'little', signed=True)

    def is_user(self, r):
        known = self.user.get(r)
        if known is None:
            index = self.function(r)
            name = self.names[index] if index >= 0 else ''
            # Module functions are `moduleN::name`; top-level code has no
            # symbol of its own and follows the `_start` entry; lambdas are
            # `Nlambda`. Prelude helpers (join, str, ...) count as runtime,
            # so their caller is the site.
            known = ('::' in name or name[:1].isdigit()
                     or (name == '_start' and r - self.addresses[index] > 0x20))
            self.user[r] = known
        return known

    def label(self, r):
        index = self.function(r)
        return f'{self.names[index]}+{r - self.addresses[index]:#x}' if index >= 0 else hex(r)

    def chain(self, rets):
        start = None
        for position, r in enumerate(rets):
            if r and self.names[self.function(r)] == 'rt_alloc_kind':
                target = self.target(r)
                if target is not None and self.names[self.function(target)] == 'rt_trace_alloc':
                    start = position
                    break
        if start is None:
            return []
        links = [rets[start]]
        for r in rets[start + 1:]:
            if not r:
                continue
            target = self.target(r)
            if target is not None and self.function(target) == self.function(links[-1]):
                links.append(r)
        return links

    def site(self, rets):
        key = tuple(rets)
        known = self.cache.get(key)
        if known is not None:
            return known
        links = self.chain(rets)
        self.chains += 1
        chosen = 0
        for r in links[1:]:
            if self.is_user(r):
                chosen = r
                break
        if not chosen:
            self.broken += 1
            chosen = links[-1] if links else 0
        site = self.ids.get(chosen)
        if site is None:
            site = len(self.labels)
            self.ids[chosen] = site
            self.labels.append(self.label(chosen) if chosen else '(no chain)')
        self.cache[key] = site
        return site


class Policy:
    def __init__(self, name, fracture=False):
        self.name = name
        self.fracture = fracture
        self.seg_of = array('i')
        self.members = []          # segment -> list of object ids
        self.fill = []             # bytes allocated into the segment
        self.summarized = []       # bool
        self.unscanned = []        # members added since the last scan
        self.age = []              # collections survived
        self.active = set()
        self.open = {}             # stream key -> open segment
        self.reclaimed = bytearray()
        self.totals = {'scanned': 0, 'graph': 0, 'segments_reached': 0, 'segment_edges': 0,
                       'fracture_scanned': 0, 'fractured_segments': 0}
        self.collections = []

    def new_segment(self):
        segment = len(self.members)
        self.members.append([])
        self.fill.append(0)
        self.summarized.append(False)
        self.unscanned.append(0)
        self.age.append(0)
        self.active.add(segment)
        return segment

    def place(self, obj, size, key):
        self.reclaimed.append(0)
        if size > LARGE:
            segment = self.new_segment()
        else:
            segment = self.open.get(key)
            if segment is None or segment not in self.active or self.fill[segment] + size > SEGMENT:
                segment = self.new_segment()
                self.open[key] = segment
        self.members[segment].append(obj)
        self.fill[segment] += size
        self.unscanned[segment] += 1
        self.seg_of.append(segment)


class Simulator:
    def __init__(self, sites, death):
        self.sites = sites
        self.death = death
        self.size = array('q')
        self.site = array('i')
        self.birth = array('i')
        self.address = {}
        self.edges = {}
        self.collections = 0
        self.policies = [Policy('window'), Policy('site'), Policy('learned'),
                         Policy('learned+fx', fracture=True), Policy('oracle')]
        self.site_stats = {}       # site -> [seen1, survived1, died_old, death_age_sum]
        self.ms = []

    # ---- learned classification ----------------------------------------
    def lifetime_class(self, site):
        stats = self.site_stats.get(site)
        if stats is None or stats[0] < 32:
            return 'unknown'
        seen1, survived1, died_old, age_sum = stats
        if survived1 < 0.1 * seen1:
            return 'ephemeral'
        if survived1 - died_old > 0.7 * survived1:
            return 'persistent'
        mean = age_sum / died_old if died_old else 99
        return 'dies-2' if mean <= 2.5 else 'dies-4' if mean <= 4.5 else 'dies-8'

    # ---- events ----------------------------------------------------------
    def allocate(self, payload, size, kind, rets):
        obj = len(self.size)
        self.size.append(size)
        site = self.sites.site(rets)
        self.site.append(site)
        self.birth.append(self.collections)
        self.address[payload] = obj
        klass = self.lifetime_class(site)
        for policy in self.policies:
            if policy.name == 'window':
                key = 0
            elif policy.name == 'site':
                key = site
            elif policy.name == 'oracle':
                key = self.death[obj] if obj < len(self.death) else -1
            else:
                key = klass
            policy.place(obj, size, key)

    def grow(self, payload, size):
        obj = self.address.get(payload)
        if obj is not None:
            self.size[obj] = size

    def collect(self, roots, blocks, live_addresses):
        self.collections += 1
        k = self.collections
        address = self.address
        heap = set()
        dirty = set()
        edges_heap = 0
        for payload, targets in blocks:
            obj = address[payload]
            heap.add(obj)
            resolved = tuple(sorted({address[t] for t in targets}))
            edges_heap += len(resolved)
            old = self.edges.get(obj)
            if old is not None and old != resolved:
                dirty.add(obj)
            self.edges[obj] = resolved
        root_objs = {address[r] for r in roots}
        live = {address[p] for p in live_addresses}
        edges = self.edges
        # The hooks run just before the real collector at the same stack
        # depth, so it can find a stale word they left behind and keep an
        # object no recorded root reaches. The real collector's result
        # defines the effective roots: such objects become roots.
        reach = set(root_objs)
        work = list(root_objs)
        while work:
            obj = work.pop()
            for target in edges.get(obj, ()):
                if target not in reach:
                    reach.add(target)
                    work.append(target)
        added = [obj for obj in live if obj not in reach]
        if added:
            root_objs |= set(added)
        unreached_marked = len(reach - live)
        size = self.size
        live_bytes = sum(size[o] for o in live)
        edges_live = sum(len(edges.get(o, ())) for o in live)
        # Mark-sweep baseline: every live object is marked once.
        ms = {'collection': k, 'live_objects': len(live), 'live_bytes': live_bytes,
              'heap_objects': len(heap), 'edges_live': edges_live, 'edges_heap': edges_heap,
              'roots': len(root_objs), 'dirty': len(dirty), 'roots_added': len(added),
              'reachable_but_swept': unreached_marked}
        self.ms.append(ms)
        for policy in self.policies:
            self.collect_policy(policy, k, root_objs, live, dirty, live_bytes)
        # Lifetime statistics, after the policies used the earlier ones.
        stats = self.site_stats
        birth = self.birth
        site = self.site
        for obj in heap:
            age = k - birth[obj]
            entry = stats.get(site[obj])
            if entry is None:
                entry = stats[site[obj]] = [0, 0, 0, 0]
            alive = obj in live
            if age == 1:
                entry[0] += 1
                if alive:
                    entry[1] += 1
            elif not alive:
                entry[2] += 1
                entry[3] += age
        # Forget pointers no policy can still need.
        for obj in heap:
            if obj not in live and all(policy.reclaimed[obj] for policy in self.policies):
                del edges[obj]
        for payload in [p for p, o in address.items() if o in heap and o not in live]:
            del address[payload]

    def collect_policy(self, policy, k, root_objs, live, dirty, live_bytes):
        seg_of = policy.seg_of
        reclaimed = policy.reclaimed
        members = policy.members
        edges = self.edges
        reached = set()
        queue = deque()
        incoming = {} if policy.fracture else None
        for obj in root_objs:
            segment = seg_of[obj]
            if segment not in reached:
                reached.add(segment)
                queue.append(segment)
        scanned = 0
        segment_edges = 0
        while queue:
            segment = queue.popleft()
            group = members[segment]
            if policy.summarized[segment]:
                scanned += policy.unscanned[segment] + sum(1 for obj in group if obj in dirty)
            else:
                scanned += len(group)
            policy.summarized[segment] = True
            policy.unscanned[segment] = 0
            targets = set()
            for obj in group:
                for target in edges.get(obj, ()):
                    other = seg_of[target]
                    if other != segment:
                        targets.add(other)
                        if incoming is not None:
                            incoming.setdefault(other, set()).add(target)
            segment_edges += len(targets)
            for other in targets:
                if other not in reached:
                    reached.add(other)
                    queue.append(other)
        # Reclaim every unreached segment whole.
        for segment in policy.active - reached:
            for obj in members[segment]:
                reclaimed[obj] = 1
            members[segment] = []
        policy.active = reached
        fracture_scanned = 0
        fractured = 0
        if policy.fracture:
            for segment in reached:
                policy.age[segment] += 1
                group = members[segment]
                if policy.age[segment] < 2 or not group:
                    continue
                dead = sum(1 for obj in group if obj not in live)
                if dead * 2 <= len(group):
                    continue
                # A local trace from the segment's incoming edges and roots.
                fracture_scanned += len(group) + len(incoming.get(segment, ()))
                fractured += 1
                inside = set(group)
                keep = set(obj for obj in incoming.get(segment, ()) if obj in inside)
                keep |= {obj for obj in group if obj in root_objs}
                work = list(keep)
                while work:
                    obj = work.pop()
                    for target in edges.get(obj, ()):
                        if target in inside and target not in keep:
                            keep.add(target)
                            work.append(target)
                for obj in group:
                    if obj not in keep:
                        reclaimed[obj] = 1
                members[segment] = [obj for obj in group if obj in keep]
        else:
            for segment in reached:
                policy.age[segment] += 1
        lost = [obj for obj in live if reclaimed[obj]]
        if lost:
            raise SystemExit(f'{policy.name}: collection {k} reclaimed {len(lost)} live objects (simulator bug)')
        size = self.size
        retained = 0
        retained_objects = 0
        for segment in reached:
            for obj in members[segment]:
                retained += size[obj]
                retained_objects += 1
        graph = len(reached) + segment_edges + len(root_objs)
        totals = policy.totals
        totals['scanned'] += scanned + fracture_scanned
        totals['graph'] += graph
        totals['segments_reached'] += len(reached)
        totals['segment_edges'] += segment_edges
        totals['fracture_scanned'] += fracture_scanned
        totals['fractured_segments'] += fractured
        policy.collections.append({
            'collection': k, 'scanned': scanned + fracture_scanned, 'graph': graph,
            'segments': len(reached), 'segment_edges': segment_edges,
            'retained_bytes': retained, 'dead_retained_bytes': retained - live_bytes,
            'retained_objects': retained_objects})


def deaths(path):
    """First pass: the collection at which each object was found dead (2^30
    for objects that outlive the trace)."""
    death = array('i')
    address = {}
    heap = []
    live = set()
    k = 0
    ending = False

    def close():
        for payload in heap:
            if payload not in live:
                obj = address.pop(payload, None)
                if obj is not None:
                    death[obj] = k

    with open(path, 'rb') as stream:
        tail = array('Q')
        while True:
            data = stream.read((1 << 22) * 8)
            words = array('Q')
            words.extend(tail)
            if data:
                words.frombytes(data[:len(data) - len(data) % 8])
            n = len(words)
            i = 0
            while i < n:
                word = words[i]
                tag = word >> 56
                if ending and tag != 7:
                    close()
                    ending = False
                if tag == 1:
                    if i + ALLOC_WORDS > n and data:
                        break
                    address[word & LOW48] = len(death)
                    death.append(1 << 30)
                    i += ALLOC_WORDS
                    continue
                if tag == 8:
                    if i + 2 > n and data:
                        break
                    i += 2
                    continue
                if tag == 10:
                    if i + SITE_WORDS > n and data:
                        break
                    i += SITE_WORDS
                    continue
                if tag == 2:
                    k += 1
                    heap = []
                    live = set()
                elif tag == 4:
                    heap.append(word & LOW48)
                elif tag == 6:
                    ending = True
                elif tag == 7:
                    live.add(word & LOW48)
                i += 1
            tail = words[i:] if i < n else array('Q')
            if not data:
                break
    if ending:
        close()
    return death


def read_trace(path, simulator, chunk_words=1 << 22):
    signatures = {0: [0] * 24}
    roots = []
    blocks = []
    live = []
    state = None
    current = None
    tail = array('Q')
    with open(path, 'rb') as stream:
        while True:
            data = stream.read(chunk_words * 8)
            words = array('Q')
            words.extend(tail)
            if data:
                words.frombytes(data[:len(data) - len(data) % 8])
            n = len(words)
            i = 0
            final = not data
            while i < n:
                word = words[i]
                tag = word >> 56
                if state == 'end' and tag != 7:
                    # The live list ended: the collection is complete.
                    simulator.collect(roots, blocks, live)
                    state = None
                    roots, blocks, live = [], [], []
                if tag == 1:
                    if i + ALLOC_WORDS > n and not final:
                        break
                    value = word & LOW48
                    kind = (word >> 48) & 255
                    simulator.allocate(value, words[i + 1], kind, signatures[words[i + 2]])
                    i += ALLOC_WORDS
                    continue
                if tag == 8:
                    if i + 2 > n and not final:
                        break
                    simulator.grow(word & LOW48, words[i + 1])
                    i += 2
                    continue
                if tag == 10:
                    if i + SITE_WORDS > n and not final:
                        break
                    signatures[word & LOW48] = list(words[i + 1:i + SITE_WORDS])
                    i += SITE_WORDS
                    continue
                value = word & LOW48
                if tag == 2:
                    state = 'begin'
                    roots = []
                    blocks = []
                    current = None
                elif tag == 3:
                    roots.append(value)
                elif tag == 4:
                    current = (value, [])
                    blocks.append(current)
                elif tag == 5:
                    current[1].append(value)
                elif tag == 6:
                    state = 'end'
                    live = []
                elif tag == 7:
                    live.append(value)
                elif tag == 9:
                    pass
                else:
                    raise SystemExit(f'bad trace word {word:#x} at {i}')
                i += 1
            tail = words[i:] if i < n else array('Q')
            if final:
                break
    if state == 'end':
        simulator.collect(roots, blocks, live)


def summarize(name, simulator):
    ms = simulator.ms
    count = len(ms)
    ms_work = sum(row['live_objects'] for row in ms)
    ms_swept = sum(row['heap_objects'] for row in ms)
    live_bytes = sum(row['live_bytes'] for row in ms)
    edges_live = sum(row['edges_live'] for row in ms)
    rows = {'ms': {'work': ms_work, 'scanned': ms_work, 'graph': 0, 'dead_retained_ratio': 0.0}}
    for policy in simulator.policies:
        totals = policy.totals
        dead = sum(row['dead_retained_bytes'] for row in policy.collections)
        rows[policy.name] = {
            'work': totals['scanned'] + totals['graph'], 'scanned': totals['scanned'], 'graph': totals['graph'],
            'segments_reached': totals['segments_reached'], 'segment_edges': totals['segment_edges'],
            'fracture_scanned': totals['fracture_scanned'], 'fractured_segments': totals['fractured_segments'],
            'dead_retained_ratio': round(dead / live_bytes, 4) if live_bytes else 0.0,
            'segment_edges_over_live_edges': round(totals['segment_edges'] / edges_live, 4) if edges_live else 0.0,
        }
    static = min(rows['window']['work'], rows['site']['work'])
    best = rows['learned+fx']
    gate = {
        'collections': count,
        'learned_vs_best_static_work': round(static / best['work'], 3) if best['work'] else None,
        'learned_vs_ms_work': round(ms_work / best['work'], 3) if best['work'] else None,
        'dead_retained_ratio': best['dead_retained_ratio'],
        'segment_edges_over_live_edges': best['segment_edges_over_live_edges'],
    }
    gate['passes'] = bool(count and gate['learned_vs_best_static_work'] and gate['learned_vs_best_static_work'] >= 2
                          and gate['dead_retained_ratio'] <= 0.10 and gate['segment_edges_over_live_edges'] < 0.10)
    return {'workload': name, 'collections': count, 'ms_swept_blocks': ms_swept, 'objects': len(simulator.size), 'sites': len(simulator.sites.labels),
            'ms_live_objects_total': ms_work, 'ms_live_bytes_total': live_bytes, 'edges_live_total': edges_live,
            'policies': rows, 'gate': gate,
            'per_collection': {'ms': ms, **{p.name: p.collections for p in simulator.policies}}}


def simulate(name, trace, binary):
    sites = Sites(binary)
    started = time.perf_counter()
    simulator = Simulator(sites, deaths(trace))
    read_trace(trace, simulator)
    result = summarize(name, simulator)
    result['simulated_seconds'] = round(time.perf_counter() - started, 1)
    stats = simulator.site_stats
    top = sorted(stats.items(), key=lambda item: -item[1][0])[:12]
    result['signatures'] = sites.chains
    result['signatures_without_user_frame'] = sites.broken
    result['top_sites'] = [{'site': sites.labels[site], 'seen_at_first_collection': s[0],
                            'survived_first': s[1], 'died_later': s[2],
                            'class': simulator.lifetime_class(site)} for site, s in top]
    return result


def main():
    global SEGMENT, LARGE
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('traces', type=Path, help='directory written by trace.py')
    parser.add_argument('--only', nargs='+', default=None)
    parser.add_argument('--json', type=Path, default=None)
    parser.add_argument('--segment', type=int, default=SEGMENT,
                        help='segment bytes; 16 puts every object in its own segment, which must '
                             'reproduce mark-sweep exactly (a self-check)')
    args = parser.parse_args()
    SEGMENT = args.segment
    LARGE = min(LARGE, SEGMENT // 4) if SEGMENT >= 64 else 0
    manifest = json.loads((args.traces / 'manifest.json').read_text())
    results = []
    for name, entry in manifest.items():
        if args.only and name not in args.only:
            continue
        result = simulate(name, entry['trace'], entry['binary'])
        result['trace_policy'] = entry.get('policy', {})
        results.append(result)
        gate = result['gate']
        policies = result['policies']
        print(f"{name}: {result['collections']} collections, {result['objects']} objects, {result['sites']} sites, "
              f"{result['simulated_seconds']} s", flush=True)
        for key, row in policies.items():
            print(f"  {key:11} work {row['work']:>12,}  scanned {row['scanned']:>12,}  graph {row['graph']:>10,}  "
                  f"dead/live {row['dead_retained_ratio']:.3f}", flush=True)
        print(f"  ms sweep visits {result['ms_swept_blocks']:,} blocks", flush=True)
        print(f"  gate: learned+fx vs best static {gate['learned_vs_best_static_work']}x, vs ms "
              f"{gate['learned_vs_ms_work']}x, dead/live {gate['dead_retained_ratio']}, "
              f"E_C/E {gate['segment_edges_over_live_edges']} -> {'PASS' if gate['passes'] else 'fail'}", flush=True)
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')


if __name__ == '__main__':
    main()
