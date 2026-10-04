"""Fallback for companies where no Greenhouse/Lever/Ashby feed could be
found (e.g. they use Workday, a custom-built page, or heavy client-side
rendering requests can't see).

Generic careers-page scraping is unreliable enough (wildly different HTML
per site, most modern ones render job lists with JavaScript a plain HTTP
request never executes) that silently "scraping" it would likely produce
wrong or empty results and look like coverage that isn't really there.
Rather than fake that, this module just confirms the careers URL is
reachable and leaves the company flagged `manual_check_needed` so it shows
up clearly for a human to check by hand -- see db.set_company_manual_check_needed.
"""

from __future__ import annotations

import requests

REQUEST_TIMEOUT = 10


def careers_url_is_reachable(careers_url: str) -> bool:
    """Best-effort check that the careers page still resolves. False on any
    network error, non-2xx/3xx status, or missing URL -- callers should treat
    False as 'needs a human to check', not as proof the page is gone."""
    if not careers_url:
        return False
    try:
        resp = requests.get(careers_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except requests.RequestException:
        return False
    return resp.status_code < 400
