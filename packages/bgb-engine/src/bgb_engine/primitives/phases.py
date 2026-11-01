"""Ordered phases, without any rule about what a phase allows."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseMachine:
    """An ordered list of phases; the game decides what each one allows."""

    phases: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.phases:
            raise ValueError('A phase machine needs at least one phase.')
        if len(set(self.phases)) != len(self.phases):
            raise ValueError('Phases must be unique.')

    @property
    def first(self) -> str:
        return self.phases[0]

    @property
    def last(self) -> str:
        return self.phases[-1]

    def is_last(self, phase: str) -> bool:
        return phase == self.last

    def next(self, phase: str) -> str | None:
        """Return the phase after ``phase``, or ``None`` after the last one."""
        index = self.phases.index(phase)
        if index + 1 == len(self.phases):
            return None
        return self.phases[index + 1]
