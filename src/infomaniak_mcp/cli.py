"""Command line front end. Same operations as the MCP server."""
from __future__ import annotations

import argparse
import json
import sys

from . import tools
from .dav import DavError, InfomaniakDav


def _out(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="infomaniak_mcp.cli")
    area = parser.add_subparsers(dest="area", required=True)

    where = area.add_parser("collections", help="list address books and calendars")
    where.set_defaults(run=lambda dav, a: tools.collections(dav))

    contacts = area.add_parser("contacts").add_subparsers(dest="cmd", required=True)
    find = contacts.add_parser("find")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=50)
    find.add_argument("--addressbook")
    find.set_defaults(run=lambda dav, a: tools.contacts_search(
        dav, a.query, a.limit, a.addressbook))
    add = contacts.add_parser("add")
    add.add_argument("--name", required=True)
    add.add_argument("--phone", action="append", dest="phones")
    add.add_argument("--email", action="append", dest="emails")
    add.add_argument("--organisation", default="")
    add.add_argument("--note", default="")
    add.add_argument("--addressbook")
    add.set_defaults(run=lambda dav, a: tools.contacts_create(
        dav, a.name, a.phones, a.emails, a.organisation, a.note, a.addressbook))

    cal = area.add_parser("cal").add_subparsers(dest="cmd", required=True)
    listing = cal.add_parser("list")
    listing.add_argument("--days", type=int, default=14)
    listing.add_argument("--start")
    listing.add_argument("--timezone")
    listing.add_argument("--calendar")
    listing.set_defaults(run=lambda dav, a: tools.calendar_list(
        dav, a.days, a.start, a.timezone, a.calendar))
    make = cal.add_parser("add")
    make.add_argument("--title", required=True)
    make.add_argument("--start", required=True)
    make.add_argument("--end")
    make.add_argument("--all-day", action="store_true", dest="all_day")
    make.add_argument("--note", default="")
    make.add_argument("--timezone")
    make.add_argument("--calendar")
    make.set_defaults(run=lambda dav, a: tools.calendar_create(
        dav, a.title, a.start, a.end, a.all_day, a.note, a.timezone, a.calendar))
    drop = cal.add_parser("del")
    drop.add_argument("resource")
    drop.set_defaults(run=lambda dav, a: tools.calendar_delete(dav, a.resource))

    todo = area.add_parser("todo").add_subparsers(dest="cmd", required=True)
    tlist = todo.add_parser("list")
    tlist.add_argument("--all", action="store_true", dest="include_done")
    tlist.add_argument("--timezone")
    tlist.add_argument("--calendar")
    tlist.set_defaults(run=lambda dav, a: tools.tasks_list(
        dav, a.include_done, a.timezone, a.calendar))
    tadd = todo.add_parser("add")
    tadd.add_argument("--title", required=True)
    tadd.add_argument("--due")
    tadd.add_argument("--note", default="")
    tadd.add_argument("--timezone")
    tadd.add_argument("--calendar")
    tadd.set_defaults(run=lambda dav, a: tools.tasks_create(
        dav, a.title, a.due, a.note, a.timezone, a.calendar))
    tdone = todo.add_parser("done")
    tdone.add_argument("resource")
    tdone.set_defaults(run=lambda dav, a: tools.tasks_complete(dav, a.resource))

    args = parser.parse_args(argv)
    try:
        _out(args.run(InfomaniakDav(), args))
    except DavError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
