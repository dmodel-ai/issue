"""Discord webhook notifications."""
import json
import os
import sys
import urllib.request
import urllib.error


def _in_test():
    """Check if running under pytest."""
    return "pytest" in sys.modules

_webhook_url_cache = None


def _get_webhook_url():
    """Get webhook URL from env or AWS Secrets Manager."""
    global _webhook_url_cache
    if _webhook_url_cache is not None:
        return _webhook_url_cache

    url = os.environ.get("ISSUE_DISCORD_WEBHOOK")
    if url:
        _webhook_url_cache = url
        return url

    secret_name = os.environ.get("ISSUE_DISCORD_SECRET", "issue-tracker/test-plain")
    try:
        import boto3
    except ImportError:
        print("Warning: boto3 not installed, Discord notifications disabled. Reinstall: uv tool install -e ~/src/issue-tracker --reinstall", file=sys.stderr)
        _webhook_url_cache = ""
        return ""
    try:
        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=secret_name)
        _webhook_url_cache = resp["SecretString"]
        return _webhook_url_cache
    except Exception as e:
        print(f"Warning: failed to get Discord webhook from Secrets Manager ({secret_name}): {e}", file=sys.stderr)
        _webhook_url_cache = ""
        return ""


def _post_webhook(content: str):
    """Post message to Discord webhook (blocking)."""
    if _in_test():
        return
    url = _get_webhook_url()
    if not url:
        return
    data = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "issue-tracker/1.0",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        if resp.status >= 400:
            print(f"Warning: Discord webhook returned {resp.status}: {resp.read().decode()[:200]}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f"Warning: Discord webhook HTTP error {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"Warning: Discord webhook failed: {e.reason}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Discord webhook unexpected error: {e}", file=sys.stderr)


def notify(content: str):
    """Post message to Discord."""
    _post_webhook(content)


def notify_issue_change(issue: dict, old_issue: dict | None = None):
    """Notify about an issue change."""
    from .store import num
    ref = issue.get('alias') or f"#{num(issue['id'])}"
    title = issue.get('title', '')[:50]

    if old_issue is None:
        notify(f"**New issue** {ref}: {title}")
        return

    old_status = old_issue.get('status')
    new_status = issue.get('status')
    if old_status != new_status:
        notify(f"**{ref}** {old_status} -> {new_status}: {title}")
        return

    old_comments = old_issue.get('comments', [])
    new_comments = issue.get('comments', [])
    if len(new_comments) > len(old_comments):
        c = new_comments[-1]
        notify(f"**{ref}** comment by {c['author']}: {c['text'][:100]}")
        return

    notify(f"**{ref}** updated: {title}")
