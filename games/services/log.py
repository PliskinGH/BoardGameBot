"""Turn the stored action log into the lines a front end shows."""

from typing import Any

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from games.models import Action, Match

DEFAULT_LIMIT = 20
BOARD_LIMIT = 5
WEB_LIMIT = DEFAULT_LIMIT


def entries(match: Match, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Return the log lines of the latest actions, oldest first."""
    actions = list(match.actions.select_related('actor')
                   .order_by('-seq')[:limit])
    lines: list[dict[str, Any]] = []
    for action in reversed(actions):
        stored = action.result.get('log', [])
        actor = action.actor.display_name if action.actor else ''
        for entry in stored:
            lines.append({'seq': action.seq, 'text': entry.get('text', ''),
                          'kind': entry.get('kind', 'info'), 'actor': actor})
        if not stored:
            lines.append({'seq': action.seq, 'text': _fallback(action),
                          'kind': 'info', 'actor': actor})
    return lines


def _fallback(action: Action) -> str | Promise:
    """Describe an action the engine wrote no log line for."""
    if action.type == 'undo':
        return _('Undid step %(seq)s.') % {
            'seq': action.payload.get('undoes', '?')}
    if action.type == 'close_match':
        return _('Closed the match.')
    if action.type == 'rules_upgrade':
        return _('Upgraded the rules from v%(from)s to v%(to)s.') % {
            'from': action.payload.get('from', '?'),
            'to': action.payload.get('to', '?'),
        }
    return _('Action: %(type)s') % {'type': action.type}
