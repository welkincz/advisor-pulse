"""State persistence on R2 with a run lock (issue #45)."""

from pulse.state.sync import STATE_STAGES, StateSync, backfill_rebuild, weeks_between

# One instance per process: restore_state stores the lock token that release_lock needs.
STATE = StateSync()

__all__ = ["STATE", "STATE_STAGES", "StateSync", "backfill_rebuild", "weeks_between"]
