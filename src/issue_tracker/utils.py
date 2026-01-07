"""Core utilities: colors, helpers, config."""
import os, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

DIR = Path(".issues")

C = {
    'reset': '\033[0m', 'bold': '\033[1m', 'dim': '\033[2m',
    'red': '\033[31m', 'green': '\033[32m', 'yellow': '\033[33m',
    'blue': '\033[34m', 'magenta': '\033[35m', 'cyan': '\033[36m',
}

def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)

def edit(initial=""):
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write(initial)
        f.flush()
        subprocess.run(f'{editor} "{f.name}"', shell=True)
        return Path(f.name).read_text()

def now():
    return datetime.utcnow().isoformat() + 'Z'

def user():
    try:
        email = subprocess.run(["git", "config", "user.email"],
                               capture_output=True, text=True, check=True).stdout.strip()
        return email.split('@')[0]
    except subprocess.CalledProcessError:
        return "unknown"

def ago(ts):
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    diff = datetime.now(dt.tzinfo) - dt
    if diff.days > 0:
        return f"{diff.days}d ago"
    if diff.seconds > 3600:
        return f"{diff.seconds // 3600}h ago"
    if diff.seconds > 60:
        return f"{diff.seconds // 60}m ago"
    return "just now"
