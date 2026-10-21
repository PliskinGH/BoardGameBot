"""Seeded randomness, so a match can be replayed from its seed."""

import random


def rng_for(seed: int, salt: str = '') -> random.Random:
    """Return a generator seeded from a match seed and a stable salt."""
    return random.Random(f'{seed}:{salt}')
