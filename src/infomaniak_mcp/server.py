"""Model Context Protocol server for Infomaniak kSuite over CalDAV and CardDAV.

Speaks JSON-RPC 2.0 on stdin and stdout with no third party dependencies, so it runs
under any Python 3.11 or newer without an install step.
"""
from __future__ import annotations

import json
import sys
import traceback

from . import tools
from .dav import DavError, InfomaniakDav

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "infomaniak-mcp", "version": "0.1.0"}

_dav: InfomaniakDav | None = None


def dav() -> InfomaniakDav:
    global _dav
    if _dav is None:
        _dav = InfomaniakDav()
    return _dav


def _text(payload) -> dict:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": body}]}


TOOLS = [
    {
        "name": "list_collections",
        "description": "List the address books and calendars this account can reach. "
                       "Useful when the account has more than one and you need the exact name.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_contacts",
        "description": "Search the address book by name, organisation, note, email or phone "
                       "digits. Accent insensitive.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name fragment or phone digits"},
                "limit": {"type": "integer", "default": 50},
                "addressbook": {"type": "string", "description": "Address book name, optional"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_contact",
        "description": "Add a contact. The write is read back and rolled back if the server "
                       "altered it, so a success means the stored card matches what was sent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "phones": {"type": "array", "items": {"type": "string"}},
                "emails": {"type": "array", "items": {"type": "string"}},
                "organisation": {"type": "string"},
                "note": {"type": "string"},
                "addressbook": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_events",
        "description": "Upcoming calendar events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 14},
                "start": {"type": "string", "description": "YYYY-MM-DD, defaults to today"},
                "timezone": {"type": "string", "description": "IANA name, defaults to the host zone"},
                "calendar": {"type": "string"},
            },
        },
    },
    {
        "name": "create_event",
        "description": "Add a calendar event. Give start as 'YYYY-MM-DD HH:MM' for a timed "
                       "event or 'YYYY-MM-DD' for an all day one.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "all_day": {"type": "boolean", "default": False},
                "note": {"type": "string"},
                "timezone": {"type": "string"},
                "calendar": {"type": "string"},
            },
            "required": ["title", "start"],
        },
    },
    {
        "name": "delete_event",
        "description": "Delete a calendar event by its resource path, as returned by list_events.",
        "inputSchema": {
            "type": "object",
            "properties": {"resource": {"type": "string"}},
            "required": ["resource"],
        },
    },
    {
        "name": "list_tasks",
        "description": "Reminders and tasks stored as VTODO on the calendar.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_done": {"type": "boolean", "default": False},
                "timezone": {"type": "string"},
                "calendar": {"type": "string"},
            },
        },
    },
    {
        "name": "create_task",
        "description": "Add a reminder, optionally with a due date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "due": {"type": "string", "description": "'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'"},
                "note": {"type": "string"},
                "timezone": {"type": "string"},
                "calendar": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a reminder done by its resource path, as returned by list_tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {"resource": {"type": "string"}},
            "required": ["resource"],
        },
    },
]

HANDLERS = {
    "list_collections": lambda a: tools.collections(dav()),
    "search_contacts": lambda a: tools.contacts_search(dav(), **a),
    "create_contact": lambda a: tools.contacts_create(dav(), **a),
    "list_events": lambda a: tools.calendar_list(dav(), **a),
    "create_event": lambda a: tools.calendar_create(dav(), **a),
    "delete_event": lambda a: tools.calendar_delete(dav(), **a),
    "list_tasks": lambda a: tools.tasks_list(dav(), **a),
    "create_task": lambda a: tools.tasks_create(dav(), **a),
    "complete_task": lambda a: tools.tasks_complete(dav(), **a),
}


def handle(message: dict) -> dict | None:
    method = message.get("method")
    ident = message.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": ident, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }}

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": ident, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": ident, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            return {"jsonrpc": "2.0", "id": ident,
                    "error": {"code": -32601, "message": f"unknown tool {name!r}"}}
        try:
            return {"jsonrpc": "2.0", "id": ident, "result": _text(handler(arguments))}
        except DavError as exc:
            return {"jsonrpc": "2.0", "id": ident,
                    "result": {"isError": True,
                               "content": [{"type": "text", "text": str(exc)}]}}
        except Exception as exc:  # surfaced to the client, never swallowed
            return {"jsonrpc": "2.0", "id": ident,
                    "result": {"isError": True, "content": [{"type": "text", "text": (
                        f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")}]}}

    if ident is None:
        return None
    return {"jsonrpc": "2.0", "id": ident,
            "error": {"code": -32601, "message": f"unknown method {method!r}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
