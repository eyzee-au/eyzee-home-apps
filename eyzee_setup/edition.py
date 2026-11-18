"""Customer edition branding for the single EyZEE codebase and version stream.

There is one product codebase and one release version.  The activated
entitlement plan selects the customer-facing edition:

* ``core`` -> EyZEE(R) Core, the DIY product installed on customer hardware.
* ``home`` -> EyZEE(R) Home, the complete supplied hardware/software product.

Only customer-visible product wording changes.  Internal lowercase routes and
identifiers (``/eyzee-home/``, ``eyzee_home``, dashboard IDs and file paths) are
never rewritten.
"""
from __future__ import annotations

from collections.abc import Mapping

CORE = "core"
HOME = "home"

_PLAIN = {CORE: "EyZEE Core", HOME: "EyZEE Home"}
_REGISTERED = {CORE: "EyZEE\u00ae Core", HOME: "EyZEE\u00ae Home"}

# Ordered longest/most specific first.  The registered spelling does not
# contain the plain spelling, but keeping the order explicit prevents a future
# replacement from changing the trademark symbol.
_REPLACEMENTS = (
    ("EyZEE\u00ae Home", "EyZEE\u00ae Core"),
    ("EyZEE Home", "EyZEE Core"),
)


def normalise(plan):
    """Return the supported plan name, defaulting unknown plans to Core."""
    if isinstance(plan, str):
        value = plan.strip().lower()
        if value == HOME:
            return HOME
    return CORE


def _entitlement_plan(subscription):
    """Read the plan without mutating subscription state or making requests."""
    if isinstance(subscription, str):
        return subscription
    if isinstance(subscription, Mapping):
        plan = subscription.get("plan")
        if plan is None and isinstance(subscription.get("entitlement"), Mapping):
            plan = subscription["entitlement"].get("plan")
        return plan
    state = getattr(subscription, "state", None)
    if isinstance(state, Mapping):
        entitlement = state.get("entitlement")
        if isinstance(entitlement, Mapping) and entitlement.get("plan") is not None:
            return entitlement.get("plan")
    summary = getattr(subscription, "summary", None)
    if callable(summary):
        try:
            value = summary()
        except Exception:
            value = None
        if isinstance(value, Mapping):
            return value.get("plan")
    return None


def plan_for(subscription):
    """Return ``core`` or ``home`` for an activated subscription.

    A missing subscription means the legacy/local installer keeps the existing
    Home content.  A configured subscription defaults to Core when the service
    has not returned a recognised plan, matching the Setup screen's default.
    """
    if subscription is None:
        return HOME
    return normalise(_entitlement_plan(subscription))


def product_name(plan, registered=False):
    """Return the customer-facing product name for an edition plan."""
    names = _REGISTERED if registered else _PLAIN
    return names[normalise(plan)]


def render(content, plan):
    """Render product wording for an edition.

    ``content`` may be ``str`` or UTF-8 ``bytes``; the same type is returned.
    Home content is returned byte-for-byte unchanged.  Only the two visible
    product spellings are replaced, so lowercase internal routes and
    identifiers such as ``/eyzee-home/`` and ``eyzee_home`` are preserved.
    """
    if normalise(plan) == HOME:
        return content
    if isinstance(content, bytes):
        return (content.replace(b"EyZEE\xc2\xae Home", b"EyZEE\xc2\xae Core")
                       .replace(b"EyZEE Home", b"EyZEE Core"))
    if isinstance(content, str):
        for old, new in _REPLACEMENTS:
            content = content.replace(old, new)
        return content
    raise TypeError("Edition content must be text or bytes.")
