"""Shape final scores for the web standings."""

from typing import Any


def rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one name and its labelled score details per seat."""
    rows = []
    for index, row in enumerate(summary.get('scores') or []):
        name = row.get('name') or f'Seat {int(row.get("position", index)) + 1}'
        details = [(str(key).replace('_', ' ').capitalize(), value)
                   for key, value in row.items()
                   if key not in ('name', 'position')]
        rows.append({'name': name, 'details': details})
    return rows
