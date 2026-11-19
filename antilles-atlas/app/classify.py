"""Phase 5 evidence classification: graph helpers over source_derivation.
Independece rule: two sources are independent witnesses only if neither from the other AND they share no ancestor.
Martyr and Las Casas both exceprt the lost Pane Orignal, so they are ONE witness. 

Caveat: no derivation eges means no known lineage, not proven independent,
"""

from __future__ import annotations

from app.models import Source

def lineage(source: Source) -> set[int]:
    """The source's own id plus every ancestor id, following derived_from upward."""
    seen: set[int] = set()
    stack = [source]
    while stack:
        s = stack.pop()
        if s.id in seen:
            continue
        seen.add(s.id)
        stack.extend(edge.origin for edge in s.derived_from)
    return seen

def transmission_depth(source: Source) -> int:
    """Fewest Copy steps to a source with no known parent. 0 = no known parent"""
    depth, frontier, seen = 0, [source], {source.id}
    while True:
        if any(not s.derived_from for s in frontier):
            return depth
        nxt = []
        for s in frontier:
            for edge in s.derived_from:
                if edge.origin.id not in seen:
                    seen.add(edge.origin.id)
                    nxt.append(edge.origin)
        frontier, depth = nxt, depth + 1


def independent(a: Source, b: Source) -> bool:
    """Option a: no shared linage at all."""
    return not (lineage(a) & lineage(b))

def witness_groups(sources: list[Source]) -> list[list[Source]]:
    """Group sources that share lineage. Each group counts as one witness"""
    groups: list[tuple[set[int], list[Source]]] = []
    for s in sources:
        lin = lineage(s)
        touching = [g for g in groups if g[0] & lin]
        merged_ids, merged = set(lin), [s]
        for g in touching:
            merged_ids |= g[0]
            merged = g[1] + merged
            groups.remove(g)
        groups.append((merged_ids, merged))
    return [g[1] for g in groups]