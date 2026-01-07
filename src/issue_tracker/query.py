"""Query DSL: shared filter/search semantics for CLI and TUI.

Syntax:
  field:value  - match field (owner, status, label, reviewer, cc, attention, blocks, blocked)
  -term        - negation
  text         - full-text search in all fields
  Multiple terms are ANDed together

Examples:
  owner:alice status:review
  -label:wontfix
  owner:alice bug
"""
import yaml
from dataclasses import dataclass
from typing import Optional

from .store import num


@dataclass
class Term:
    """A single query term."""
    field: Optional[str]  # None for full-text search
    value: str
    negate: bool = False


def parse_query(text: str) -> list[Term]:
    """Parse query text into list of terms.

    Args:
        text: Query string like "owner:alice status:review -label:wontfix"

    Returns:
        List of Term objects
    """
    terms = []
    for token in text.split():
        negate = token.startswith('-')
        if negate:
            token = token[1:]

        if ':' in token:
            field, value = token.split(':', 1)
            terms.append(Term(field=field, value=value.lower(), negate=negate))
        else:
            terms.append(Term(field=None, value=token.lower(), negate=negate))

    return terms


def matches(issue: dict, terms: list[Term]) -> bool:
    """Check if issue matches all query terms.

    Args:
        issue: Issue dict with fields like owner, status, labels, etc.
        terms: List of Term objects from parse_query()

    Returns:
        True if issue matches ALL terms (AND semantics)
    """
    for term in terms:
        match = _match_term(issue, term)
        if term.negate:
            match = not match
        if not match:
            return False
    return True


def _match_term(issue: dict, term: Term) -> bool:
    """Check if issue matches a single term (ignoring negation)."""
    val = term.value

    if term.field is None:
        # Full-text search
        return val in yaml.dump(issue).lower()

    field = term.field
    if field == 'owner':
        return val in issue.get('owner', '').lower()
    elif field == 'status':
        return val in issue.get('status', '').lower()
    elif field == 'label':
        return any(val in l.lower() for l in issue.get('labels', []))
    elif field == 'reviewer':
        return any(val in r.lower() for r in issue.get('reviewers', []))
    elif field == 'cc':
        return any(val in c.lower() for c in issue.get('cc', []))
    elif field == 'attention':
        return any(val in a.lower() for a in issue.get('attention', []))
    elif field == 'blocks':
        return any(val in str(num(b)) for b in issue.get('blocks', []))
    elif field == 'blocked':
        return any(val in str(num(b)) for b in issue.get('blocked_by', []))
    else:
        # Unknown field: fall back to full-text search
        return val in yaml.dump(issue).lower()


def filter_issues(issues: list[dict], query_text: str) -> list[dict]:
    """Filter issues using query DSL.

    Args:
        issues: List of issue dicts
        query_text: Query string

    Returns:
        Filtered list of issues matching the query
    """
    if not query_text or not query_text.strip():
        return issues
    terms = parse_query(query_text)
    return [i for i in issues if matches(i, terms)]
