"""Streamlit Community Cloud entrypoint for the public, read-only demo."""
import os
from pathlib import Path
import runpy


# Set on the server, before any application controls are created.
os.environ["IR_HW2_READ_ONLY"] = "1"
runpy.run_path(str(Path(__file__).resolve().with_name("app.py")), run_name="__main__")
