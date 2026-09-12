"""Private handshake between the host-control utility and ScholarDesk."""

from __future__ import annotations

import ipaddress
import os
import secrets

from fastapi import Request


HOST_CONTROL_TOKEN_ENVIRONMENT = "SCHOLARDESK_HOST_CONTROL_TOKEN"
HOST_CONTROL_TOKEN_HEADER = "x-scholardesk-host-token"


def is_authorized_host_control_request(request: Request) -> bool:
    """Accept shutdown commands only from the local host-control process."""
    token = os.environ.get(HOST_CONTROL_TOKEN_ENVIRONMENT)
    submitted_token = request.headers.get(HOST_CONTROL_TOKEN_HEADER)
    client_host = request.client.host if request.client is not None else ""
    try:
        is_loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        is_loopback = False
    return bool(
        token
        and submitted_token
        and is_loopback
        and secrets.compare_digest(submitted_token, token)
    )
