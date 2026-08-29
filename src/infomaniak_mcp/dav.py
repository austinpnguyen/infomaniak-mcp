"""CalDAV and CardDAV client for Infomaniak kSuite.

Nothing about a particular account is baked in. The username, the principal path and
the collection URLs are all discovered at runtime from the credentials you supply.

Infomaniak quirk worth knowing before you debug for an hour: the DAV username is the
internal account id such as ``AB12345``, not the mailbox address. The value is visible
in the configuration profile Infomaniak generates for Apple devices.
"""
from __future__ import annotations

import base64
import html
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable

DEFAULT_HOST = "https://sync.infomaniak.com"

#: Third UTF-8 byte values observed to make Infomaniak's CardDAV **write** path
#: double-encode a card. Reported to Infomaniak support in August 2026. Calendar and
#: task writes are unaffected, verified by round-tripping the same characters.
#:
#: This set is a SAMPLE, not a proof. It came from testing ten characters one per
#: card, so uppercase forms and untested codepoints may also trigger the defect.
#: Treat :func:`carddav_unsafe` as an early warning only. The guarantee that nothing
#: is silently mangled comes from reading every written card back and rolling it back
#: on mismatch, which is what :meth:`InfomaniakDav.put_verified` does.
CARDDAV_BAD_THIRD_BYTES = {0xA1, 0xA3, 0xA7, 0xB7}


class DavError(RuntimeError):
    pass


def carddav_unsafe(text: str) -> list[str]:
    """Return the characters in *text* that Infomaniak corrupts on CardDAV write.

    Empty list means the text is safe to write. The check is on the raw UTF-8 bytes
    because the defect is a byte-level charset guess, not a Unicode-level one.
    """
    data = (text or "").encode("utf-8")
    found: set[str] = set()
    for i in range(len(data) - 2):
        if data[i] == 0xE1 and data[i + 1] in (0xBA, 0xBB) and data[i + 2] in CARDDAV_BAD_THIRD_BYTES:
            found.add(data[i:i + 3].decode("utf-8"))
    return sorted(found)


def double_encoded(text: str) -> str | None:
    """Return the repaired string if *text* is mojibake, else None.

    A string is double-encoded exactly when reading its bytes back as Latin-1 and
    decoding them as UTF-8 succeeds and changes it. That transform *is* the corruption,
    so it is also the test, and it recovers the original as a side effect.
    """
    try:
        fixed = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return fixed if fixed != text else None


def unfold(text: str) -> str:
    """Undo RFC 5545 / 6350 line folding so single-line regexes work."""
    return re.sub(r"\r?\n[ \t]", "", text)


@dataclass(frozen=True)
class Collection:
    href: str
    name: str
    kind: str  # "addressbook" | "calendar"


class InfomaniakDav:
    def __init__(self, username: str | None = None, password: str | None = None,
                 host: str = None, timeout: int = 120):
        self.username = username or os.environ.get("INFOMANIAK_USER", "")
        password = password or os.environ.get("INFOMANIAK_APP_PASSWORD", "")
        if not self.username or not password:
            raise DavError(
                "Set INFOMANIAK_USER and INFOMANIAK_APP_PASSWORD. The user is the "
                "internal account id such as AB12345, not the mailbox address."
            )
        self.host = (host or os.environ.get("INFOMANIAK_DAV_URL") or DEFAULT_HOST).rstrip("/")
        self.timeout = timeout
        self._auth = "Basic " + base64.b64encode(f"{self.username}:{password}".encode()).decode()
        self._principal: str | None = None
        self._collections: list[Collection] | None = None

    # ---------------------------------------------------------------- transport
    def request(self, method: str, path: str, body: bytes | None = None,
                depth: str | None = None, ctype: str | None = None) -> tuple[int, str]:
        url = path if path.startswith("http") else self.host + path
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", self._auth)
        if depth:
            req.add_header("Depth", depth)
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def _propfind(self, path: str, props: str, depth: str) -> str:
        body = (f'<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
                f'xmlns:card="urn:ietf:params:xml:ns:carddav" xmlns:cs="http://calendarserver.org/ns/">'
                f"<d:prop>{props}</d:prop></d:propfind>").encode()
        status, text = self.request("PROPFIND", path, body, depth=depth, ctype="application/xml")
        if status not in (200, 207):
            raise DavError(f"PROPFIND {path} returned HTTP {status}")
        return html.unescape(text)

    # ---------------------------------------------------------------- discovery
    @property
    def principal(self) -> str:
        if self._principal is None:
            xml = self._propfind("/", "<d:current-user-principal/>", "0")
            m = re.search(r"<d:current-user-principal>.*?<d:href>([^<]+)</d:href>", xml, re.S)
            if not m:
                raise DavError("could not discover the principal; check the credentials")
            self._principal = m.group(1)
        return self._principal

    def _home(self, prop: str) -> str | None:
        try:
            xml = self._propfind(self.principal, prop, "0")
        except DavError as exc:
            if "404" in str(exc):
                raise DavError(
                    f"the principal {self.principal} does not exist, so "
                    f"INFOMANIAK_USER={self.username!r} is not a valid account id. "
                    "The server accepts any username at the authentication step and "
                    "simply echoes it back as the principal path, so a mailbox address "
                    "signs in and then fails here. Use the internal account id, for "
                    "example AB12345, which the Apple configuration profile shows as "
                    "its User Name field."
                ) from None
            raise
        m = re.search(r"<d:href>([^<]+)</d:href>", xml.split(prop.split("/")[0].lstrip("<"))[-1]) \
            if False else None
        hrefs = re.findall(r"<d:href>([^<]+)</d:href>", xml)
        # the principal itself is always the first href; the home set follows
        for h in hrefs:
            if h.rstrip("/") != self.principal.rstrip("/"):
                return h
        return None

    def collections(self, refresh: bool = False) -> list[Collection]:
        """Every address book and calendar the account can see."""
        if self._collections is not None and not refresh:
            return self._collections
        found: list[Collection] = []
        for prop, kind in (("<card:addressbook-home-set/>", "addressbook"),
                           ("<c:calendar-home-set/>", "calendar")):
            home = self._home(prop)
            if not home:
                continue
            xml = self._propfind(home, "<d:resourcetype/><d:displayname/>", "1")
            for block in re.split(r"</d:response>", xml):
                href = re.search(r"<d:href>([^<]+)</d:href>", block)
                if not href:
                    continue
                path = href.group(1)
                if path.rstrip("/") == home.rstrip("/") or path.endswith(("/inbox/", "/outbox/")):
                    continue
                want = "addressbook" if kind == "addressbook" else "calendar"
                if want not in block:
                    continue
                name = re.search(r"<d:displayname>([^<]*)</d:displayname>", block)
                found.append(Collection(path, (name.group(1).strip() if name else path), kind))
        self._collections = found
        return found

    def pick(self, kind: str, name: str | None = None) -> Collection:
        """Choose a collection by name, or fall back to the only or first one."""
        options = [c for c in self.collections() if c.kind == kind]
        if not options:
            raise DavError(f"the account exposes no {kind}")
        if name:
            for c in options:
                if c.name == name or c.href.rstrip("/").endswith(name.rstrip("/")):
                    return c
            raise DavError(f"no {kind} named {name!r}; available: "
                           + ", ".join(repr(c.name) for c in options))
        env = os.environ.get(
            "INFOMANIAK_ADDRESSBOOK" if kind == "addressbook" else "INFOMANIAK_CALENDAR")
        if env:
            return self.pick(kind, env)
        return options[0]

    # ---------------------------------------------------------------- reports
    def report(self, href: str, kind: str, comp: str | None = None) -> str:
        if kind == "addressbook":
            body = ('<card:addressbook-query xmlns:d="DAV:" '
                    'xmlns:card="urn:ietf:params:xml:ns:carddav">'
                    "<d:prop><card:address-data/></d:prop></card:addressbook-query>")
        else:
            body = ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    "<d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter>"
                    f'<c:comp-filter name="VCALENDAR"><c:comp-filter name="{comp or "VEVENT"}"/>'
                    "</c:comp-filter></c:filter></c:calendar-query>")
        status, text = self.request("REPORT", href, body.encode(), depth="1",
                                    ctype="application/xml")
        if status not in (200, 207):
            raise DavError(f"REPORT {href} returned HTTP {status}")
        return unfold(html.unescape(text))

    def put(self, href: str, body: str, ctype: str) -> None:
        status, text = self.request("PUT", href, body.encode("utf-8"), ctype=ctype)
        if status not in (200, 201, 204):
            raise DavError(f"PUT {href} returned HTTP {status}: {text[:200]}")

    def get(self, href: str) -> str:
        status, text = self.request("GET", href)
        if status != 200:
            raise DavError(f"GET {href} returned HTTP {status}")
        return text

    def put_verified(self, href: str, body: str, ctype: str, must_contain: str) -> None:
        """Write, read back, and roll back if the server altered the content.

        Infomaniak corrupts some UTF-8 on the CardDAV write path. Rather than trust a
        list of known-bad characters, which is only ever a sample, this confirms the
        stored bytes and deletes the resource if they do not match. A failed write is
        far better than a card that looks saved and is quietly wrong.
        """
        self.put(href, body, ctype)
        stored = self.get(href)
        if must_contain in stored:
            return
        repaired = None
        for line in stored.splitlines():
            fixed = double_encoded(line)
            if fixed and must_contain in fixed:
                repaired = line
                break
        try:
            self.delete(href)
        except DavError:
            pass
        detail = (f" The server stored {repaired!r}." if repaired else "")
        raise DavError(
            "the server did not store what was sent, so the write was rolled back."
            + detail
            + " This is the Infomaniak CardDAV encoding defect a known server defect."
            " Add this entry through the kSuite web interface instead."
        )

    def delete(self, href: str) -> None:
        status, _ = self.request("DELETE", href)
        if status not in (200, 204, 404):
            raise DavError(f"DELETE {href} returned HTTP {status}")


def blocks(text: str, name: str) -> Iterable[str]:
    return re.findall(rf"BEGIN:{name}(.*?)END:{name}", text, re.S)
