"""The vCard and iCalendar builders, exercised through a fake DAV layer."""
import unittest

from infomaniak_mcp import tools
from infomaniak_mcp.dav import Collection, DavError


class FakeDav:
    def __init__(self, corrupt=False):
        self.store = {}
        self.corrupt = corrupt
        self.deleted = []

    def pick(self, kind, name=None):
        return Collection(f"/{kind}s/acct/book/", "Test", kind)

    def put_verified(self, href, body, ctype, must_contain):
        stored = body.encode("utf-8").decode("latin-1") if self.corrupt else body
        self.store[href] = stored
        if must_contain not in stored:
            self.deleted.append(href)
            del self.store[href]
            raise DavError("rolled back")

    def put(self, href, body, ctype):
        self.store[href] = body

    def get(self, href):
        return self.store[href]

    def delete(self, href):
        self.deleted.append(href)
        self.store.pop(href, None)


class TestContactCreate(unittest.TestCase):
    def test_writes_a_well_formed_card(self):
        dav = FakeDav()
        out = tools.contacts_create(dav, "Jane Doe", ["+15551234567"], ["j@example.com"])
        card = dav.store[out["resource"]]
        self.assertIn("BEGIN:VCARD", card)
        self.assertIn("FN:Jane Doe", card)
        self.assertIn("TEL;TYPE=CELL:+15551234567", card)
        self.assertIn("EMAIL;TYPE=INTERNET:j@example.com", card)
        self.assertTrue(card.endswith("END:VCARD\r\n"))

    def test_escapes_separators(self):
        dav = FakeDav()
        out = tools.contacts_create(dav, "Doe, Jane; the second")
        self.assertIn(r"FN:Doe\, Jane\; the second", dav.store[out["resource"]])

    def test_rolls_back_when_the_server_corrupts(self):
        dav = FakeDav(corrupt=True)
        with self.assertRaises(DavError):
            tools.contacts_create(dav, "Bạn Thử")
        self.assertEqual(dav.store, {})
        self.assertEqual(len(dav.deleted), 1)


class TestEventCreate(unittest.TestCase):
    def test_timed_event_is_written_in_utc(self):
        dav = FakeDav()
        out = tools.calendar_create(dav, "Dentist", "2026-09-05 14:30", timezone="UTC")
        body = dav.store[out["resource"]]
        self.assertIn("DTSTART:20260905T143000Z", body)
        self.assertIn("DTEND:20260905T153000Z", body)
        self.assertIn("SUMMARY:Dentist", body)
        self.assertFalse(out["all_day"])

    def test_date_only_start_becomes_all_day(self):
        dav = FakeDav()
        out = tools.calendar_create(dav, "Holiday", "2026-09-05")
        self.assertTrue(out["all_day"])
        self.assertIn("DTSTART;VALUE=DATE:20260905", dav.store[out["resource"]])

    def test_vietnamese_is_kept_verbatim(self):
        dav = FakeDav()
        title = "Hẹn Bạn Ảo Ầm Đặng"
        out = tools.calendar_create(dav, title, "2026-09-05 14:30", timezone="UTC")
        self.assertIn(f"SUMMARY:{title}", dav.store[out["resource"]])


class TestTaskCreate(unittest.TestCase):
    def test_task_has_status_and_due(self):
        dav = FakeDav()
        out = tools.tasks_create(dav, "Renew passport", due="2026-10-01")
        body = dav.store[out["resource"]]
        self.assertIn("BEGIN:VTODO", body)
        self.assertIn("STATUS:NEEDS-ACTION", body)
        self.assertIn("DUE;VALUE=DATE:20261001", body)

    def test_complete_sets_completed(self):
        dav = FakeDav()
        out = tools.tasks_create(dav, "Call the bank")
        tools.tasks_complete(dav, out["resource"])
        body = dav.store[out["resource"]]
        self.assertIn("STATUS:COMPLETED", body)
        self.assertIn("COMPLETED:", body)


class TestParseWhen(unittest.TestCase):
    def test_rejects_nonsense(self):
        import datetime
        with self.assertRaises(ValueError):
            tools.parse_when("next tuesday", datetime.timezone.utc)


if __name__ == "__main__":
    unittest.main()


class TestUnescapeOnRead(unittest.TestCase):
    def test_round_trip_through_escaping(self):
        from infomaniak_mcp.tools import _esc, _unesc
        for raw in ("Doe, Jane; the second", "Họp, bàn giao; lần 2",
                    "line one\nline two", r"back\slash"):
            self.assertEqual(_unesc(_esc(raw)), raw, raw)

    def test_plain_text_is_untouched(self):
        from infomaniak_mcp.tools import _unesc
        self.assertEqual(_unesc("Dentist"), "Dentist")
