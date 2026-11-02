"""Public v1 contract for tools embedded in the ComiTrans retouch editor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from PIL import Image


API_VERSION = 1
Box = tuple[int, int, int, int]  # Left, top, right, bottom, with exclusive ends.
Point = tuple[int, int]


@dataclass(frozen=True)
class Selection:
    box: Box


@dataclass(frozen=True)
class Stroke:
    points: tuple[Point, ...]  # In drawing order. A click has one point.


@dataclass(frozen=True)
class IntOption:
    key: str
    label: str
    default: int
    minimum: int
    maximum: int


@dataclass(frozen=True)
class ColorOption:
    key: str
    label: str
    default: str  # Opaque RGB as #rrggbb.


class RetouchCancelled(Exception):
    """Raised by check_cancelled when the host cancels a tool invocation."""


@dataclass(frozen=True)
class ToolRequest:
    background: Image.Image  # Private RGB snapshot of the current cleaned draft.
    gesture: Selection | Stroke
    options: Mapping[str, int | str]
    check_cancelled: Callable[[], None]


@dataclass(frozen=True)
class PixelPatch:
    """Final RGB pixels replacing exactly box in the cleaned background."""

    box: Box
    pixels: Image.Image


@dataclass(frozen=True)
class RetouchTool:
    id: str
    label: str
    input_kind: Literal["selection", "stroke"]
    run: Callable[[ToolRequest], PixelPatch | None]
    options: tuple[IntOption | ColorOption, ...] = ()


class RetouchPlugin(Protocol):
    """The entry module of each installed plugin provides this function."""

    def create_tools(self) -> tuple[RetouchTool, ...]: ...
