"""Persistence package namespace.

This package intentionally has no import-time facade. Import concrete
submodules such as :mod:`breezy.persistence.catalog` directly so package import
cannot carry catalog or Arrow registration side effects.

Verified safe. One entry, `breezy.runtime.quote_tape_preflight_cli`, registers
54 instead of 60 Nautilus arrow schemas once the facade is gone; its read path
(`feather_preflight` -> `feather_read`) uses only `pyarrow` and `fsspec` and
never decodes through Nautilus's `ArrowSerializer`, so no registration it lost
is used. Every other entry's `_SCHEMAS` key set and `register_arrow`
reachability is unchanged.
"""
