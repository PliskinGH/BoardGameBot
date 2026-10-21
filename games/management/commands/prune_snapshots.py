"""Delete action snapshots older than the newest ones of each match."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from games.models import ActionSnapshot, Match

DEFAULT_KEEP = 50


class Command(BaseCommand):
    """Keep undo working for the latest steps, without unbounded growth."""

    help = 'Delete old action snapshots, keeping the newest per match.'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('--keep', type=int, default=DEFAULT_KEEP,
                            help=f'Snapshots to keep per match '
                                 f'(default {DEFAULT_KEEP}).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be deleted.')

    def handle(self, *args: Any, **options: Any) -> None:
        keep = int(options['keep'])
        if keep < 1:
            raise CommandError('--keep must be at least 1.')
        dry_run = bool(options['dry_run'])
        verb = 'would delete' if dry_run else 'deleted'
        total = 0
        matches = (Match.objects.filter(actions__isnull=False)
                   .distinct().order_by('pk'))
        for match in matches.iterator():
            stale = list(ActionSnapshot.objects.filter(action__match=match)
                         .order_by('-action__seq')
                         .values_list('pk', flat=True)[keep:])
            if not stale:
                continue
            total += len(stale)
            if not dry_run:
                ActionSnapshot.objects.filter(pk__in=stale).delete()
            self.stdout.write(f'Match {match.pk}: kept {keep}, '
                              f'{verb} {len(stale)}.')
        self.stdout.write(self.style.SUCCESS(
            f'{verb.capitalize()} {total} snapshots.'))
