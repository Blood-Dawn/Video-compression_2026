# start.ps1 - Launch SVCS with GPU + SR enhancement support
# Usage: .\start.ps1
# Optional: .\start.ps1 --port 8080

uv run --extra enhance python run_gui.py @args
