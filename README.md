# infomaniak-mcp

An MCP server and CLI for [Infomaniak kSuite](https://www.infomaniak.com/en/ksuite)
contacts, calendars and reminders, over the standard CalDAV and CardDAV endpoints.

No third party dependencies. It runs on the Python that ships with macOS and most
Linux distributions, 3.9 or newer, so there is nothing to install.

## Why

Infomaniak exposes CalDAV and CardDAV at `sync.infomaniak.com`, but two details make
it awkward to automate, and both are handled here:

1. The DAV username is the internal account id such as `AB12345`, not the mailbox
   address. Nothing in the public documentation says so. The value appears in the
   configuration profile Infomaniak generates for Apple devices.
2. The CardDAV **write** path double-encodes some UTF-8, so a contact saved from a
   phone can be silently corrupted. See [Known server defect](#known-server-defect).

## Install

```bash
git clone https://github.com/<you>/infomaniak-mcp
cd infomaniak-mcp
python3 -m unittest discover -s tests   # optional, confirms it runs here
```

That is the whole install. There is nothing to build and nothing to download.
The macOS system interpreter at `/usr/bin/python3` is enough.

## Credentials

Generate an application password in the Infomaniak manager under
**My Profile → Application password(s)**, then export two variables:

```bash
export INFOMANIAK_USER=AB12345              # internal account id, not the email
export INFOMANIAK_APP_PASSWORD=xxxxxxxxxxxx
```

To find your account id, open **Contacts → Synchronise your contacts on all your
devices** in kSuite and look at the generated Apple configuration profile. The
`User Name` field in it is the id.

Optional:

```bash
export INFOMANIAK_DAV_URL=https://sync.infomaniak.com   # default
export INFOMANIAK_ADDRESSBOOK="Personal"            # default: the first one found
export INFOMANIAK_CALENDAR="Personal"                   # default: the first one found
```

Everything else, the principal path and the collection URLs, is discovered at runtime.
Nothing about an account is hard coded.

## Use as an MCP server

```json
{
  "mcpServers": {
    "infomaniak": {
      "command": "python3",
      "args": ["-m", "infomaniak_mcp"],
      "env": {
        "PYTHONPATH": "/path/to/infomaniak-mcp/src",
        "INFOMANIAK_USER": "AB12345",
        "INFOMANIAK_APP_PASSWORD": "xxxxxxxxxxxx"
      }
    }
  }
}
```

Tools exposed:

| Tool | What it does |
|---|---|
| `list_collections` | Address books and calendars the account can reach |
| `search_contacts` | Accent insensitive search over name, organisation, note, email, phone |
| `create_contact` | Add a contact, verified on write |
| `list_events` | Upcoming events, with a day window |
| `create_event` | Add a timed or all day event |
| `delete_event` | Remove an event by resource path |
| `list_tasks` | Reminders stored as `VTODO` |
| `create_task` | Add a reminder, optionally with a due date |
| `complete_task` | Mark a reminder done |

## Use as a CLI

```bash
export PYTHONPATH=src

python3 -m infomaniak_mcp.cli contacts find "nguyen"
python3 -m infomaniak_mcp.cli contacts add --name "Jane Doe" --phone +15551234567
python3 -m infomaniak_mcp.cli cal list --days 30
python3 -m infomaniak_mcp.cli cal add --title "Dentist" --start "2026-09-05 14:30"
python3 -m infomaniak_mcp.cli todo add --title "Renew passport" --due 2026-10-01
python3 -m infomaniak_mcp.cli todo list
```

## Known server defect

Infomaniak's CardDAV **write** path reinterprets some valid UTF-8 as ISO-8859-1 and
re-encodes it. Sending the bytes `E1 BA A1` for `ạ` stores `C3 A1 C2 BA C2 A1`, and one
affected character corrupts every field on the card. Confirmed on two separate
accounts and from a real iPhone, so it is not client specific.

Reads are unaffected. Calendar and task writes are unaffected, verified by round
tripping the same characters. Importing through the kSuite web interface is unaffected.

Reported to Infomaniak support in August 2026.

### How this library protects you

`create_contact` writes the card, reads it back, and **deletes it and raises** if the
stored bytes differ from what was sent. A failed write is far better than a card that
looks saved and is quietly wrong.

There is also `carddav_unsafe(text)`, which flags characters observed to trigger the
defect. Treat it as an early warning only: the list came from sampling ten characters,
so untested codepoints may also be affected. The read back is the guarantee.

`double_encoded(text)` repairs a mojibake string, and returns `None` if the text was
already fine. A string is double-encoded exactly when reading its bytes back as
Latin-1 and decoding them as UTF-8 succeeds and changes it, which is the corruption
itself, so it is also the test.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests cover the encoding helpers and the vCard and iCalendar builders. They do not
touch the network, so they run without credentials. They are also the fastest way to
confirm the interpreter on a given machine is new enough.

## Notes

Times without an explicit zone are read in the host's local zone. Pass `timezone` with
an IANA name to override.

Reminders are `VTODO` components stored on the calendar collection, which is what the
Infomaniak server advertises support for.

## Licence

MIT
