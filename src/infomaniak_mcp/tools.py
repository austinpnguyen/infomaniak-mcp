"""The operations the MCP server and the CLI both use."""
from __future__ import annotations

import datetime
import re
import unicodedata
import uuid
import zoneinfo

from .dav import Collection, DavError, InfomaniakDav, blocks, carddav_unsafe

VCARD_CT = "text/vcard; charset=utf-8"
ICAL_CT = "text/calendar; charset=utf-8"


def _tz(name: str | None) -> datetime.tzinfo:
    try:
        return zoneinfo.ZoneInfo(name) if name else datetime.datetime.now().astimezone().tzinfo
    except Exception:
        return datetime.timezone.utc


def _esc(value: str) -> str:
    return (str(value).replace("\\", "\\\\").replace(";", r"\;")
            .replace(",", r"\,").replace("\n", r"\n"))


def _unesc(value: str) -> str:
    """Undo RFC 5545 and RFC 6350 text escaping when reading a property back."""
    out, i = [], 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"n": "\n", "N": "\n"}.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _fold(name: str) -> str:
    text = unicodedata.normalize("NFKD", (name or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _uid() -> str:
    return uuid.uuid4().hex


def parse_when(value: str, tz: datetime.tzinfo) -> tuple[datetime.datetime, bool]:
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.datetime.strptime(value, "%Y-%m-%d"), True
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt).replace(tzinfo=tz), False
        except ValueError:
            continue
    raise ValueError(f"unrecognised date or time: {value!r}")


def _utc(when: datetime.datetime) -> str:
    return when.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_dt(raw: str, tz: datetime.tzinfo) -> datetime.datetime | None:
    try:
        if raw.endswith("Z"):
            return (datetime.datetime.strptime(raw, "%Y%m%dT%H%M%SZ")
                    .replace(tzinfo=datetime.timezone.utc).astimezone(tz))
        if "T" in raw:
            return datetime.datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz)
        return datetime.datetime.strptime(raw[:8], "%Y%m%d").replace(tzinfo=tz)
    except ValueError:
        return None


# ---------------------------------------------------------------- contacts
def contacts_search(dav: InfomaniakDav, query: str, limit: int = 50,
                    addressbook: str | None = None) -> list[dict]:
    book = dav.pick("addressbook", addressbook)
    xml = dav.report(book.href, "addressbook")
    digits = re.sub(r"\D", "", query)
    hits: list[dict] = []
    for card in re.findall(r"BEGIN:VCARD.*?END:VCARD", xml, re.S):
        name = re.search(r"^FN:(.*)$", card, re.M)
        entry = {
            "name": _unesc(name.group(1).strip()) if name else "",
            "phones": [t.split(":")[-1].strip() for t in re.findall(r"^TEL[^:]*:(.*)$", card, re.M)],
            "emails": [m.split(":")[-1].strip() for m in re.findall(r"^EMAIL[^:]*:(.*)$", card, re.M)],
            "organisation": (_unesc(re.search(r"^ORG:(.*)$", card, re.M).group(1).strip())
                             if re.search(r"^ORG:(.*)$", card, re.M) else ""),
            "note": (_unesc(re.search(r"^NOTE:(.*)$", card, re.M).group(1).strip())
                     if re.search(r"^NOTE:(.*)$", card, re.M) else ""),
        }
        haystack = _fold(" ".join([entry["name"], entry["organisation"], entry["note"],
                                   " ".join(entry["emails"])]))
        phone_blob = re.sub(r"\D", "", " ".join(entry["phones"]))
        if _fold(query) in haystack or (len(digits) >= 4 and digits in phone_blob):
            hits.append(entry)
    hits.sort(key=lambda e: _fold(e["name"]))
    return hits[:limit]


def contacts_create(dav: InfomaniakDav, name: str, phones=None, emails=None,
                    organisation: str = "", note: str = "",
                    addressbook: str | None = None) -> dict:
    book = dav.pick("addressbook", addressbook)
    resource = f"{book.href}{_uid()}.vcf"
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"N:;{_esc(name)};;;", f"FN:{_esc(name)}"]
    for phone in phones or []:
        lines.append(f"TEL;TYPE=CELL:{phone}")
    for email in emails or []:
        lines.append(f"EMAIL;TYPE=INTERNET:{email}")
    if organisation:
        lines.append(f"ORG:{_esc(organisation)}")
    if note:
        lines.append(f"NOTE:{_esc(note)}")
    lines += [f"UID:{resource.rsplit('/', 1)[-1][:-4]}", "END:VCARD"]
    dav.put_verified(resource, "\r\n".join(lines) + "\r\n", VCARD_CT,
                     must_contain=_esc(name))
    return {"name": name, "resource": resource,
            "warned_characters": carddav_unsafe(name + " " + note)}


# ---------------------------------------------------------------- calendar
def calendar_list(dav: InfomaniakDav, days: int = 14, start: str | None = None,
                  timezone: str | None = None, calendar: str | None = None) -> list[dict]:
    cal = dav.pick("calendar", calendar)
    tz = _tz(timezone)
    begin = (datetime.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=tz) if start
             else datetime.datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0))
    finish = begin + datetime.timedelta(days=days)
    xml = dav.report(cal.href, "calendar", "VEVENT")
    out: list[dict] = []
    for response in re.split(r"</d:response>", xml):
        href = re.search(r"<d:href>([^<]+)</d:href>", response)
        for event in blocks(response, "VEVENT"):
            raw = re.search(r"^DTSTART[^:]*:(\S+)", event, re.M)
            if not raw:
                continue
            when = _read_dt(raw.group(1), tz)
            if when is None:
                continue
            recurring = "RRULE" in event
            if not (begin <= when < finish or (recurring and when < finish)):
                continue
            summary = re.search(r"^SUMMARY:(.*)$", event, re.M)
            out.append({
                "start": when.isoformat(),
                "title": _unesc(summary.group(1).strip()) if summary else "",
                "recurring": recurring,
                "resource": href.group(1) if href else "",
            })
    out.sort(key=lambda e: e["start"])
    return out


def calendar_create(dav: InfomaniakDav, title: str, start: str, end: str | None = None,
                    all_day: bool = False, note: str = "", timezone: str | None = None,
                    calendar: str | None = None) -> dict:
    cal = dav.pick("calendar", calendar)
    tz = _tz(timezone)
    begin, detected_all_day = parse_when(start, tz)
    all_day = all_day or detected_all_day
    finish = parse_when(end, tz)[0] if end else begin + datetime.timedelta(
        days=1 if all_day else 0, hours=0 if all_day else 1)
    resource = f"{cal.href}{_uid()}.ics"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//infomaniak-mcp//EN",
             "BEGIN:VEVENT", f"UID:{resource.rsplit('/', 1)[-1][:-4]}",
             "DTSTAMP:" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")]
    if all_day:
        lines.append("DTSTART;VALUE=DATE:" + begin.strftime("%Y%m%d"))
        lines.append("DTEND;VALUE=DATE:" + finish.strftime("%Y%m%d"))
    else:
        lines.append("DTSTART:" + _utc(begin))
        lines.append("DTEND:" + _utc(finish))
    lines.append(f"SUMMARY:{_esc(title)}")
    if note:
        lines.append(f"DESCRIPTION:{_esc(note)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    dav.put_verified(resource, "\r\n".join(lines) + "\r\n", ICAL_CT,
                     must_contain=_esc(title))
    return {"title": title, "start": begin.isoformat(), "all_day": all_day,
            "resource": resource}


def calendar_delete(dav: InfomaniakDav, resource: str) -> dict:
    dav.delete(resource)
    return {"deleted": resource}


# ---------------------------------------------------------------- reminders
def tasks_list(dav: InfomaniakDav, include_done: bool = False,
               timezone: str | None = None, calendar: str | None = None) -> list[dict]:
    cal = dav.pick("calendar", calendar)
    tz = _tz(timezone)
    xml = dav.report(cal.href, "calendar", "VTODO")
    out: list[dict] = []
    for response in re.split(r"</d:response>", xml):
        href = re.search(r"<d:href>([^<]+)</d:href>", response)
        for todo in blocks(response, "VTODO"):
            done = bool(re.search(r"^STATUS:COMPLETED", todo, re.M))
            if done and not include_done:
                continue
            summary = re.search(r"^SUMMARY:(.*)$", todo, re.M)
            due = re.search(r"^DUE[^:]*:(\S+)", todo, re.M)
            when = _read_dt(due.group(1), tz) if due else None
            out.append({
                "title": _unesc(summary.group(1).strip()) if summary else "",
                "due": when.isoformat() if when else None,
                "done": done,
                "resource": href.group(1) if href else "",
            })
    out.sort(key=lambda t: (t["due"] is None, t["due"] or ""))
    return out


def tasks_create(dav: InfomaniakDav, title: str, due: str | None = None, note: str = "",
                 timezone: str | None = None, calendar: str | None = None) -> dict:
    cal = dav.pick("calendar", calendar)
    tz = _tz(timezone)
    resource = f"{cal.href}{_uid()}.ics"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//infomaniak-mcp//EN",
             "BEGIN:VTODO", f"UID:{resource.rsplit('/', 1)[-1][:-4]}",
             "DTSTAMP:" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
             f"SUMMARY:{_esc(title)}", "STATUS:NEEDS-ACTION"]
    if due:
        when, all_day = parse_when(due, tz)
        lines.append("DUE;VALUE=DATE:" + when.strftime("%Y%m%d") if all_day
                     else "DUE:" + _utc(when))
    if note:
        lines.append(f"DESCRIPTION:{_esc(note)}")
    lines += ["END:VTODO", "END:VCALENDAR"]
    dav.put_verified(resource, "\r\n".join(lines) + "\r\n", ICAL_CT,
                     must_contain=_esc(title))
    return {"title": title, "due": due, "resource": resource}


def tasks_complete(dav: InfomaniakDav, resource: str) -> dict:
    body = dav.get(resource)
    if "STATUS:" in body:
        body = re.sub(r"^STATUS:.*$", "STATUS:COMPLETED", body, flags=re.M)
    else:
        body = body.replace("END:VTODO", "STATUS:COMPLETED\r\nEND:VTODO", 1)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if "COMPLETED:" not in body:
        body = body.replace("END:VTODO", f"COMPLETED:{stamp}\r\nEND:VTODO", 1)
    dav.put(resource, body, ICAL_CT)
    return {"completed": resource}


def collections(dav: InfomaniakDav) -> list[dict]:
    return [{"kind": c.kind, "name": c.name, "href": c.href} for c in dav.collections()]
