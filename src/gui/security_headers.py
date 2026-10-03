"""
src/gui/security_headers.py

Browser hardening headers on every dashboard response (PT-02, pentest
2026-10-03).

The SEC-001 CSRF guard refuses a state-changing request whose Origin is a
foreign site. It cannot see clickjacking: a hostile page that loads the
dashboard in an invisible iframe gets the browser's cached Basic-Auth
credential for free, and every click the operator is tricked into making
comes from the dashboard's OWN origin, so it passes the Origin check.

The dashboard is never meant to be embedded anywhere (it frames nothing of
its own either), so refusing to be framed costs nothing:

  * X-Frame-Options: DENY                    - older browsers
  * Content-Security-Policy: frame-ancestors 'none'  - the modern equivalent
  * X-Content-Type-Options: nosniff          - user-supplied media is served
    back to the browser; never let it be sniffed into HTML or script
  * Referrer-Policy: same-origin             - dashboard URLs carry paths and
    camera ids; do not hand them to any outside site

Headers are only set when a route has not set its own, so a future route
that needs something different is not silently overridden.

Author: Victor De Souza Teixeira, 2026-10-03 (PT-02 fix).
"""

from __future__ import annotations

from flask import Flask, Response

SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


def install_security_headers(app: Flask) -> None:
    """Add SECURITY_HEADERS to every response the app sends."""

    @app.after_request
    def _add_security_headers(resp: Response) -> Response:
        for name, value in SECURITY_HEADERS.items():
            resp.headers.setdefault(name, value)
        return resp
