"""A graph board: named nodes and undirected edges."""

from collections import deque
from dataclasses import dataclass
from functools import cached_property


@dataclass(frozen=True)
class BoardGraph:
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        known = set(self.nodes)
        if len(known) != len(self.nodes):
            raise ValueError('Nodes must be unique.')
        for left, right in self.edges:
            if left not in known or right not in known:
                raise ValueError(f'Edge {left}-{right} uses an unknown node.')

    @cached_property
    def adjacency(self) -> dict[str, tuple[str, ...]]:
        neighbours: dict[str, list[str]] = {node: [] for node in self.nodes}
        for left, right in self.edges:
            neighbours[left].append(right)
            neighbours[right].append(left)
        return {node: tuple(values) for node, values in neighbours.items()}

    def neighbours(self, node: str) -> tuple[str, ...]:
        return self.adjacency[node]

    def distance(self, start: str, end: str) -> int | None:
        """Return the number of edges between two nodes, or ``None``."""
        if start == end:
            return 0
        seen = {start}
        queue = deque([(start, 0)])
        while queue:
            node, steps = queue.popleft()
            for neighbour in self.neighbours(node):
                if neighbour == end:
                    return steps + 1
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append((neighbour, steps + 1))
        return None

    def connected(self, start: str, end: str) -> bool:
        return self.distance(start, end) is not None
