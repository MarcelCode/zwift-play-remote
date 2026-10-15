from dataclasses import dataclass


@dataclass(frozen=True)
class ButtonDown:
    button: str


@dataclass(frozen=True)
class ButtonUp:
    button: str


def diff(before: frozenset[str], after: frozenset[str]) -> list[ButtonDown | ButtonUp]:
    """Events that turn the `before` button state into `after`. Releases come first."""
    return [ButtonUp(b) for b in sorted(before - after)] + [ButtonDown(b) for b in sorted(after - before)]
