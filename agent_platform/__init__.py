"""Read-only Heating Agent Platform.

Phase 1 contains deterministic observation components only. It does not expose
Home Assistant actuator/service APIs.
"""

from .pipeline import Phase1Pipeline

__all__ = ["Phase1Pipeline"]
