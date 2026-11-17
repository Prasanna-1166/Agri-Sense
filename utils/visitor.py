"""
AgriSense AI - anonymous per-visitor data scoping

Why this exists
---------------
AgriSense has no accounts, but it does store a little per-user data on the
server: prediction history and the optional "My Farm" profile. Run on a
single laptop that is fine. On a *public* website, though, one shared file
would mean every visitor sees everyone else's farm locations and predictions,
and anyone could wipe them.

So each browser gets a random, anonymous id in a first-party cookie
(`agrisense_vid`), and that id selects its own sub-folder:

    <DATA_DIR>/users/<visitor-id>/prediction_history.json
    <DATA_DIR>/users/<visitor-id>/farm_profile.json

This is NOT authentication: the id is an unguessable random token that works
like a private notebook key. It carries no personal information, is not used
for tracking or analytics, and the folder can be deleted at any time. Folders
that go untouched for AGRISENSE_USER_DATA_RETENTION_DAYS are pruned at startup.
"""
import logging
import os
import re
import shutil
import time
import uuid
from typing import Optional

from flask import g, has_request_context, request

from config.settings import USER_DATA_DIR

log = logging.getLogger(__name__)

VISITOR_COOKIE = "agrisense_vid"
COOKIE_MAX_AGE = 365 * 24 * 3600  # one year
_VID_RE = re.compile(r"^[a-f0-9]{32}$")

# Used outside a request (scripts, some tests) so code never crashes there.
_NO_REQUEST_ID = "0" * 32


def get_visitor_id() -> str:
    """Return this request's anonymous visitor id, minting one if needed.

    A brand-new id is remembered on `flask.g` so the response hook can set the
    cookie. Anything that is not exactly 32 lowercase hex characters is
    rejected, which also makes path traversal via a forged cookie impossible.
    """
    if not has_request_context():
        return _NO_REQUEST_ID
    cached = g.get("visitor_id")
    if cached:
        return cached
    cookie = request.cookies.get(VISITOR_COOKIE, "")
    if _VID_RE.match(cookie):
        g.visitor_id = cookie
    else:
        g.visitor_id = uuid.uuid4().hex
        g.visitor_is_new = True
    return g.visitor_id


def visitor_path(filename: str, visitor_id: Optional[str] = None) -> str:
    """Absolute path of one of this visitor's data files. Never creates it."""
    vid = visitor_id or get_visitor_id()
    return os.path.join(USER_DATA_DIR, vid, filename)


def attach_visitor_cookie(response):
    """`after_request` hook: set the cookie, but only for a freshly minted id
    (so static files, crawlers and plain API reads never receive a cookie)."""
    if has_request_context() and g.get("visitor_is_new"):
        response.set_cookie(
            VISITOR_COOKIE,
            g.visitor_id,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=request.is_secure,
        )
    return response


def prune_stale_visitor_dirs(max_age_days: int) -> int:
    """Delete visitor folders whose newest file is older than `max_age_days`.
    Returns how many were removed. Never raises."""
    if max_age_days <= 0 or not os.path.isdir(USER_DATA_DIR):
        return 0
    cutoff = time.time() - max_age_days * 24 * 3600
    removed = 0
    try:
        for name in os.listdir(USER_DATA_DIR):
            folder = os.path.join(USER_DATA_DIR, name)
            if not (os.path.isdir(folder) and _VID_RE.match(name)):
                continue
            mtimes = [os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder)]
            newest = max(mtimes) if mtimes else os.path.getmtime(folder)
            if newest < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
    except OSError as e:
        log.warning(f"Visitor-data cleanup skipped: {e}")
    if removed:
        log.info(f"Removed {removed} stale visitor data folder(s)")
    return removed
