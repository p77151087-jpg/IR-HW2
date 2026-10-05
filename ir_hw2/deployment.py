"""Server-side switches shared by the local app and public demo entrypoint."""
import os


def is_read_only() -> bool:
    return os.environ.get("IR_HW2_READ_ONLY", "").strip().lower() in {"1", "true", "yes"}
