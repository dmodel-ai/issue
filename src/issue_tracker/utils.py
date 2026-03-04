"""Core utilities: helpers, config."""
import os, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path


class IssueError(Exception):
    pass


def die(msg):
    raise IssueError(msg)

def edit(initial=""):
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write(initial)
        tmp_path = f.name
    try:
        subprocess.run(f'{editor} "{tmp_path}"', shell=True)
        with open(tmp_path, "r") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)

def now():
    return datetime.utcnow().isoformat() + 'Z'

def user_info():
    """Return (username, source) tuple."""
    if u := os.environ.get("ISSUE_USER"):
        return u, "ISSUE_USER environment variable"
    try:
        email = subprocess.run(["git", "config", "user.email"],
                               capture_output=True, text=True, check=True).stdout.strip()
        return email.split('@')[0], f"git config user.email ({email})"
    except subprocess.CalledProcessError:
        return "unknown", "fallback (git config failed)"

def user():
    return user_info()[0]

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
