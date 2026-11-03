"""Pure form mapping. Importing this package performs no database/network action."""

from .mapper import MappingError, load_mapping, map_submission, submission_id

__all__ = ["MappingError", "load_mapping", "map_submission", "submission_id"]
