"""Discord webhook notifications."""
import json
import os
import sys
import urllib.request
import urllib.error


_TEAM_REPO = "git@github.com:dmodel-ai/discord-logseq-bot.git"
_team_cache = None

# Extra Discord users not in the logseq bot's team.json
_EXTRA_DISCORD_IDS = {
    "kunal": "1368985626913013841",
}
_EXTRA_EMAILS = {
    "kunal": ["kunal@dmodel.ai"],
}


_TEAM_LOCAL = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                           "issue-tracker", "discord-logseq-bot")


def _get_team():
    """Fetch team mapping via a shallow clone (cached for process lifetime)."""
    global _team_cache
    if _team_cache is not None:
        return _team_cache
    extra_aliases = {e.split("@")[0]: n for n, emails in _EXTRA_EMAILS.items() for e in emails}
    fallback = {"discord_user_ids": dict(_EXTRA_DISCORD_IDS), "email_aliases": extra_aliases}
    try:
        import subprocess
        os.makedirs(os.path.dirname(_TEAM_LOCAL), exist_ok=True)
        if os.path.isdir(os.path.join(_TEAM_LOCAL, ".git")):
            subprocess.run(["git", "-C", _TEAM_LOCAL, "pull", "--ff-only"],
                           capture_output=True, timeout=10)
        else:
            subprocess.run(["git", "clone", "--depth=1", _TEAM_REPO, _TEAM_LOCAL],
                           capture_output=True, check=True, timeout=30)
        with open(os.path.join(_TEAM_LOCAL, "team.json")) as f:
            raw = json.load(f)
        aliases = {}
        for cname, emails in raw.get("emails", {}).items():
            for email in emails:
                aliases[email.split("@")[0]] = cname
        ids = {**raw["discord_user_ids"], **_EXTRA_DISCORD_IDS}
        aliases.update(extra_aliases)
        _team_cache = {"discord_user_ids": ids, "email_aliases": aliases}
    except Exception as e:
        print(f"Warning: failed to fetch team.json: {e}", file=sys.stderr)
        _team_cache = fallback
    return _team_cache


def _resolve_discord_id(name: str) -> str | None:
    """Resolve a name or email prefix to a Discord user ID."""
    team = _get_team()
    ids = team["discord_user_ids"]
    if name in ids:
        return ids[name]
    canonical = team["email_aliases"].get(name)
    if canonical:
        return ids.get(canonical)
    return None


def _pings(issue: dict) -> str:
    """Return Discord mention string for everyone in the attention set."""
    names = issue.get("attention", [])
    ids = {_resolve_discord_id(n) for n in names}
    ids.discard(None)
    return " ".join(f"<@{did}>" for did in ids)


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

    secret_name = os.environ.get("ISSUE_DISCORD_SECRET", "issue-tracker/qa-updates")
    try:
        import boto3
    except ImportError:
        print("Warning: boto3 not installed, Discord notifications disabled. Reinstall: uv tool install -e ~/src/issue-tracker --reinstall", file=sys.stderr)
        _webhook_url_cache = ""
        return ""
    try:
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-2")
        client = boto3.client("secretsmanager", region_name=region)
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
    raw_title = issue.get('title', '')
    title = raw_title[:50] + ("..." if len(raw_title) > 50 else "")

    pings = _pings(issue)

    if old_issue is None:
        notify(f"**New issue** {ref}: {title} {pings}")
        return

    old_status = old_issue.get('status')
    new_status = issue.get('status')
    if old_status != new_status:
        notify(f"**{ref}** {old_status} -> {new_status}: {title} {pings}")
        return

    old_comments = old_issue.get('comments', [])
    new_comments = issue.get('comments', [])
    if len(new_comments) > len(old_comments):
        c = new_comments[-1]
        text = c['text'][:100] + ("..." if len(c['text']) > 100 else "")
        notify(f"**{ref}** comment by {c['author']}: {text} {pings}")
        return

    notify(f"**{ref}** updated: {title} {pings}")
