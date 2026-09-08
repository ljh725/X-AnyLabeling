"""Small streaming JSON reader for dataset-index fields."""

from __future__ import annotations

import json
from typing import Any, List, Optional, TextIO


class JsonStreamError(ValueError):
    """Report malformed or structurally unexpected streamed JSON."""


class _JsonStreamReader:
    """Read and validate JSON incrementally without retaining skipped values."""

    def __init__(self, stream: TextIO, chunk_size: int) -> None:
        """Initialize a chunked text reader.

        Args:
            stream: Open text stream positioned at the JSON document start.
            chunk_size: Maximum number of characters requested per read.
        """
        self._stream = stream
        self._chunk_size = max(256, chunk_size)
        self._buffer = ""
        self._position = 0
        self._eof = False
        self._decoder = json.JSONDecoder()

    def peek(self) -> Optional[str]:
        """Return the next character without consuming it."""
        if not self._ensure_character():
            return None
        return self._buffer[self._position]

    def take(self) -> str:
        """Consume and return the next character."""
        if not self._ensure_character():
            raise JsonStreamError("Unexpected end of JSON document")
        character = self._buffer[self._position]
        self._position += 1
        return character

    def skip_whitespace(self) -> None:
        """Consume JSON whitespace."""
        while self.peek() in {" ", "\t", "\r", "\n"}:
            self.take()

    def expect(self, expected: str) -> None:
        """Consume one required structural character."""
        actual = self.take()
        if actual != expected:
            raise JsonStreamError(f"Expected {expected!r}, found {actual!r}")

    def read_string(self) -> str:
        """Decode and return one JSON string."""
        value = self.read_value()
        if not isinstance(value, str):
            raise JsonStreamError("Expected a JSON string")
        return value

    def read_value(self) -> Any:
        """Decode one complete value, buffering only that value."""
        self.skip_whitespace()
        self._compact()
        while True:
            try:
                value, end = self._decoder.raw_decode(self._buffer)
            except json.JSONDecodeError as exc:
                if self._eof:
                    raise JsonStreamError(str(exc)) from exc
                self._append_chunk()
                continue
            self._position = end
            return value

    def skip_value(self) -> None:
        """Validate and discard one JSON value incrementally."""
        self.skip_whitespace()
        character = self.peek()
        if character == '"':
            self._skip_string()
        elif character == "{":
            self._skip_object()
        elif character == "[":
            self._skip_array()
        elif character == "t":
            self._consume_literal("true")
        elif character == "f":
            self._consume_literal("false")
        elif character == "n":
            self._consume_literal("null")
        elif character is not None and (
            character == "-" or character.isdigit()
        ):
            self._skip_number()
        else:
            raise JsonStreamError(
                f"Unexpected JSON value prefix {character!r}"
            )

    def _ensure_character(self) -> bool:
        """Ensure at least one unread character is buffered."""
        while self._position >= len(self._buffer) and not self._eof:
            self._compact()
            self._append_chunk()
        return self._position < len(self._buffer)

    def _append_chunk(self) -> None:
        """Append one chunk without discarding an incomplete decoded value."""
        chunk = self._stream.read(self._chunk_size)
        if chunk:
            self._buffer += chunk
        else:
            self._eof = True

    def _compact(self) -> None:
        """Discard already-consumed characters."""
        if self._position:
            self._buffer = self._buffer[self._position :]
            self._position = 0

    def _skip_string(self) -> None:
        """Validate and discard one JSON string."""
        self.expect('"')
        while True:
            character = self.take()
            if character == '"':
                return
            if ord(character) < 0x20:
                raise JsonStreamError("Unescaped control character in string")
            if character != "\\":
                continue
            escape = self.take()
            if escape not in {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}:
                raise JsonStreamError(f"Invalid JSON escape \\{escape}")
            if escape == "u":
                digits = "".join(self.take() for _ in range(4))
                if any(
                    char not in "0123456789abcdefABCDEF" for char in digits
                ):
                    raise JsonStreamError("Invalid JSON unicode escape")

    def _skip_object(self) -> None:
        """Validate and discard one JSON object."""
        self.expect("{")
        self.skip_whitespace()
        if self.peek() == "}":
            self.take()
            return
        while True:
            self.read_string()
            self.skip_whitespace()
            self.expect(":")
            self.skip_value()
            self.skip_whitespace()
            delimiter = self.take()
            if delimiter == "}":
                return
            if delimiter != ",":
                raise JsonStreamError("Expected ',' or '}' in object")
            self.skip_whitespace()

    def _skip_array(self) -> None:
        """Validate and discard one JSON array."""
        self.expect("[")
        self.skip_whitespace()
        if self.peek() == "]":
            self.take()
            return
        while True:
            self.skip_value()
            self.skip_whitespace()
            delimiter = self.take()
            if delimiter == "]":
                return
            if delimiter != ",":
                raise JsonStreamError("Expected ',' or ']' in array")
            self.skip_whitespace()

    def _consume_literal(self, literal: str) -> None:
        """Consume one exact JSON literal."""
        actual = "".join(self.take() for _ in literal)
        if actual != literal:
            raise JsonStreamError(f"Invalid JSON literal {actual!r}")

    def _skip_number(self) -> None:
        """Validate and discard one JSON number."""
        characters = []
        while True:
            character = self.peek()
            if character is None or character in {
                " ",
                "\t",
                "\r",
                "\n",
                ",",
                "]",
                "}",
            }:
                break
            characters.append(self.take())
        token = "".join(characters)
        try:
            value = json.loads(token)
        except json.JSONDecodeError as exc:
            raise JsonStreamError(str(exc)) from exc
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise JsonStreamError(f"Invalid JSON number {token!r}")


def read_top_level_array(
    stream: TextIO,
    key: str,
    *,
    chunk_size: int = 64 * 1024,
    metadata: Optional[dict] = None,
) -> List[Any]:
    """Read one top-level array while streaming past all other JSON fields.

    Args:
        stream: Open JSON text stream.
        key: Top-level property whose array value should be returned.
        chunk_size: Number of characters read from the stream per chunk.

    Returns:
        The final array assigned to ``key``, or an empty list if absent.

    Raises:
        JsonStreamError: If the document is malformed or ``key`` is not an
            array.
    """
    reader = _JsonStreamReader(stream, chunk_size)
    result: List[Any] = []
    reader.skip_whitespace()
    reader.expect("{")
    reader.skip_whitespace()
    if reader.peek() == "}":
        reader.take()
    else:
        while True:
            property_name = reader.read_string()
            reader.skip_whitespace()
            reader.expect(":")
            reader.skip_whitespace()
            if property_name == key:
                if reader.peek() != "[":
                    raise JsonStreamError(f"Property {key!r} is not an array")
                result = _read_array(reader)
            elif metadata is not None and property_name in {
                "imageWidth",
                "imageHeight",
            }:
                metadata[property_name] = reader.read_value()
            else:
                reader.skip_value()
            reader.skip_whitespace()
            delimiter = reader.take()
            if delimiter == "}":
                break
            if delimiter != ",":
                raise JsonStreamError("Expected ',' or '}' at document root")
            reader.skip_whitespace()
    reader.skip_whitespace()
    if reader.peek() is not None:
        raise JsonStreamError("Unexpected data after JSON document")
    return result


def _read_array(reader: _JsonStreamReader) -> List[Any]:
    """Decode one array value item by item."""
    values = []
    reader.expect("[")
    reader.skip_whitespace()
    if reader.peek() == "]":
        reader.take()
        return values
    while True:
        values.append(reader.read_value())
        reader.skip_whitespace()
        delimiter = reader.take()
        if delimiter == "]":
            return values
        if delimiter != ",":
            raise JsonStreamError("Expected ',' or ']' in selected array")
        reader.skip_whitespace()
