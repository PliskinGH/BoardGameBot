"""Tests for the snapshot retention command."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from games.models import ActionSnapshot
from games.services import undo
from games.services.errors import NothingToUndo
from tests.factories import play_first, started_match


def play(match, turns):
    """Play ``turns`` actions and return the match."""
    for _ in range(turns):
        match = play_first(match, match.active_seat.player)
    return match


class PruneTests(TestCase):
    def setUp(self):
        self.match, self.players = started_match()
        self.match = play(self.match, 3)

    def test_it_keeps_the_newest_snapshots(self):
        call_command('prune_snapshots', '--keep', '2', stdout=StringIO())

        self.assertEqual(ActionSnapshot.objects.filter(
            action__match=self.match).count(), 2)

    def test_a_dry_run_deletes_nothing(self):
        before = ActionSnapshot.objects.count()

        call_command('prune_snapshots', '--keep', '1', '--dry-run',
                     stdout=StringIO())

        self.assertEqual(ActionSnapshot.objects.count(), before)

    def test_undoing_a_pruned_step_is_refused(self):
        call_command('prune_snapshots', '--keep', '1', stdout=StringIO())
        undo.undo_last_action(self.match.pk, self.players[0], force=True)

        with self.assertRaises(NothingToUndo):
            undo.undo_last_action(self.match.pk, self.players[0], force=True)

    def test_keep_must_keep_one(self):
        with self.assertRaises(CommandError):
            call_command('prune_snapshots', '--keep', '0', stdout=StringIO())
