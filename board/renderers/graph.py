"""Shape a graph render model for the templates."""

from math import cos, isfinite, pi, sin
from typing import Any

from bgb_engine.base import GraphView, RenderModel, TokenView

VIEW_WIDTH = 1000.0
VIEW_HEIGHT = 700.0
PADDING = 70.0
TOKEN_RADIUS = 18.0
VIEW_BOX = f'0 0 {int(VIEW_WIDTH)} {int(VIEW_HEIGHT)}'


def rows(model: RenderModel) -> dict[str, Any] | None:
    """Return an SVG-ready graph, or None without a graph board."""
    board = model.board
    if not isinstance(board, GraphView):
        return None
    nodes = _unique_nodes(board)
    positions = _positions(nodes)
    tokens = _tokens(board, positions)
    edges = _edges(board, positions)
    return {
        'view_box': VIEW_BOX,
        'nodes': [
            {'id': node.id, 'label': node.label, 'kind': node.kind,
             'x': positions[node.id][0], 'y': positions[node.id][1],
             'tokens': tokens.get(node.id, [])}
            for node in nodes
        ],
        'edges': edges,
    }


def _unique_nodes(board: GraphView) -> list[Any]:
    """Return finite nodes with unique ids, preserving board order."""
    seen: set[str] = set()
    nodes = []
    for node in board.nodes:
        if (node.id in seen or not isfinite(node.x)
                or not isfinite(node.y)):
            continue
        seen.add(node.id)
        nodes.append(node)
    return nodes


def _positions(nodes: list[Any]) -> dict[str, tuple[float, float]]:
    if not nodes:
        return {}
    xs = [float(node.x) for node in nodes]
    ys = [float(node.y) for node in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    center_x, center_y = VIEW_WIDTH / 2, VIEW_HEIGHT / 2
    plot_width = VIEW_WIDTH - 2 * PADDING
    plot_height = VIEW_HEIGHT - 2 * PADDING
    if min_x == max_x and min_y == max_y:
        radius = min(plot_width, plot_height) / 2
        return {
            node.id: (round(center_x + cos(2 * pi * index / len(nodes))
                            * radius, 2),
                      round(center_y + sin(2 * pi * index / len(nodes))
                            * radius, 2))
            for index, node in enumerate(nodes)
        }
    return {
        node.id: (
            round(PADDING + ((float(node.x) - min_x) / (max_x - min_x))
                  * plot_width, 2) if max_x != min_x else center_x,
            round(PADDING + ((float(node.y) - min_y) / (max_y - min_y))
                  * plot_height, 2) if max_y != min_y else center_y,
        )
        for node in nodes
    }


def _tokens(board: GraphView,
            positions: dict[str, tuple[float, float]]
            ) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[TokenView]] = {}
    for token in board.tokens:
        if token.node in positions:
            grouped.setdefault(token.node, []).append(token)
    result: dict[str, list[dict[str, Any]]] = {}
    for node_id, node_tokens in grouped.items():
        x, y = positions[node_id]
        result[node_id] = []
        for index, token in enumerate(node_tokens):
            offset_x, offset_y = _offset(index, len(node_tokens))
            result[node_id].append({
                'node': token.node,
                'label': token.label,
                'owner': token.owner,
                'x': round(x + offset_x, 2),
                'y': round(y + offset_y, 2),
            })
    return result


def _offset(index: int, count: int) -> tuple[float, float]:
    if count == 1:
        return 0.0, -TOKEN_RADIUS
    angle = 2 * pi * index / count - pi / 2
    return cos(angle) * TOKEN_RADIUS, sin(angle) * TOKEN_RADIUS


def _edges(board: GraphView,
           positions: dict[str, tuple[float, float]]
           ) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    edges = []
    for edge in board.edges:
        if edge.source not in positions or edge.target not in positions:
            continue
        key = ((edge.source, edge.target) if edge.source <= edge.target
               else (edge.target, edge.source))
        if edge.source == edge.target or key in seen:
            continue
        seen.add(key)
        x1, y1 = positions[edge.source]
        x2, y2 = positions[edge.target]
        edges.append({
            'source': edge.source, 'target': edge.target,
            'kind': edge.kind, 'label': edge.label,
            'owners': edge.owners,
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'label_x': round((x1 + x2) / 2, 2),
            'label_y': round((y1 + y2) / 2, 2),
        })
    return edges
