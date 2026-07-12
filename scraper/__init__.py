"""Typed public surfaces for the bal-gul scraper."""

from typing import Final

from scraper.registry import (
    DuplicateSourceError,
    NewspaperSource,
    RegistryCountError,
    RegistryError,
    RegistryReadError,
    RegistrySchemaError,
    load_registry,
    parse_registry_json,
)

__all__: Final = (
    "DuplicateSourceError",
    "NewspaperSource",
    "RegistryCountError",
    "RegistryError",
    "RegistryReadError",
    "RegistrySchemaError",
    "load_registry",
    "parse_registry_json",
)
