# infomaniak-mcp

An MCP server and CLI for [Infomaniak kSuite](https://www.infomaniak.com/en/ksuite)
contacts, calendars and reminders, over the standard CalDAV and CardDAV endpoints.

No third party dependencies. It runs on the Python that ships with macOS and most
Linux distributions, 3.9 or newer, so there is nothing to install.

## Why

Infomaniak exposes CalDAV and CardDAV at `sync.infomaniak.com`, but two details make
it awkward to automate, and both are handled here:

1. The DAV username is the internal account id such as `AB12345`, not the mailbox
   address, and nothing in the public documentation says so. Worse, the wrong value
   does not fail cleanly: the server accepts any username at the authentication step
   and echoes it straight back as the principal path, so a mailbox address signs in
   successfully and only fails later with a `404` on a principal that was never real.
   The id appears in the configuration profile Infomaniak generates for Apple devices.
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

You need two values. Neither is your normal login password, and neither is your email
address, which is the part that trips most people up.

### 1. The application password

1. Sign in at [manager.infomaniak.com](https://manager.infomaniak.com).
2. Open the account menu at the top right, then **My Profile**.
3. In the left sidebar choose **Application password(s)**.
4. Click **Generate an application password**, give it a name such as
   `mcp`, and confirm.
5. Use the **Copy** button in the dialog. Do not select the text by hand: the value is
   displayed in groups of four characters and a manual selection tends to lose part of
   it. Spaces are ignored, so `AB12 CD34` and `ABCD1234` are the same password.
6. Save it now. The dialog says so and means it: once closed, the value is gone and you
   have to generate a new one.

Application passwords belong to a single account. If you have more than one Infomaniak
account, check which one you are signed in as before generating, because a password
made in one account returns `401` on another.

### 2. The account id

This is the DAV username, an internal identifier such as `AB12345`. It is **not** your
mailbox address, and no page in the interface presents it as "your username", so it has
to be read out of the configuration profile Infomaniak generates for Apple devices.

1. Open [ksuite.infomaniak.com](https://ksuite.infomaniak.com) and go to **Contacts**.
2. In the left sidebar click **Synchronise your contacts on all your devices**.
3. Follow the Apple route. macOS shows an install dialog for a profile called
   *Infomaniak autoconfiguration*, and the **User Name** field on it is your account id.
   You do not have to install the profile, reading the dialog is enough.

If you would rather read the file directly, the downloaded `.mobileconfig` is plain XML:

```bash
grep -A1 CardDAVUsername ~/Downloads/*.mobileconfig
```

### Putting them together

```bash
export INFOMANIAK_USER=AB12345              # the account id from step 2
export INFOMANIAK_APP_PASSWORD=xxxxxxxxxxxx # the password from step 1
```

Check the pair before going further:

```bash
PYTHONPATH=src python3 -m infomaniak_mcp.cli collections
```

That prints every address book and calendar the account can reach. If it fails instead,
the cause is almost always one of these:

| Symptom | Cause |
|---|---|
| `the principal ... does not exist` | `INFOMANIAK_USER` is a mailbox address, or any other string that is not the account id. Authentication passed, discovery did not |
| `401` after generating a new password | The password was generated in a different Infomaniak account. Each account needs its own |
| `401` on a fresh copy and paste | Part of the value was lost selecting it by hand. Generate a new one and use the **Copy** button |

Note that a wrong username does not produce a `401`. Only a wrong password does. That
is why the error above names the principal rather than talking about credentials.

### Optional settings

```bash
export INFOMANIAK_DAV_URL=https://sync.infomaniak.com   # default
export INFOMANIAK_ADDRESSBOOK="Personal"                # default: the first one found
export INFOMANIAK_CALENDAR="Personal"                   # default: the first one found
```

Run `collections` to see the exact names to use for the last two.

Everything else, the principal path and the collection URLs, is discovered at runtime.
Nothing about an account is hard coded.

## Install into an MCP client

Both clients below run the server as a subprocess and talk to it on stdin and stdout,
so the only things they need are a command and the two environment variables.

Replace `/path/to/infomaniak-mcp` with wherever you cloned this, and `AB12345` with
your account id.

### Claude Code

```bash
claude mcp add infomaniak --scope user \
  -e INFOMANIAK_USER=AB12345 \
  -e INFOMANIAK_APP_PASSWORD=xxxxxxxxxxxx \
  -e PYTHONPATH=/path/to/infomaniak-mcp/src \
  -- python3 -m infomaniak_mcp
```

`--scope user` makes it available in every project. Use `--scope project` instead to
share it with a repository through a checked in `.mcp.json`, but do not do that with
credentials written inline, see [below](#keeping-the-password-out-of-the-config).

Check it came up:

```bash
claude mcp list
```

It should print `infomaniak: ... - ✓ Connected`. To remove it again:

```bash
claude mcp remove infomaniak --scope user
```

### Claude Desktop

Edit the configuration file, creating it if it does not exist:

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

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

Restart Claude Desktop afterwards. The server appears under the tools icon in the
message box.

On Windows, use `python` rather than `python3`, and write the path with forward
slashes or escaped backslashes.

### Keeping the password out of the config

Both methods above put the application password in a file that other tools read, sync
and back up. A small launcher avoids that by reading the value at startup instead:

```sh
#!/bin/sh
# infomaniak-mcp-launch
SECRETS="$HOME/.config/infomaniak.env"     # INFOMANIAK_USER=... and INFOMANIAK_APP_PASSWORD=...
REPO="/path/to/infomaniak-mcp"

[ -r "$SECRETS" ] || { echo "cannot read $SECRETS" >&2; exit 1; }
INFOMANIAK_USER=$(grep '^INFOMANIAK_USER=' "$SECRETS" | cut -d= -f2- | tr -d ' \n')
INFOMANIAK_APP_PASSWORD=$(grep '^INFOMANIAK_APP_PASSWORD=' "$SECRETS" | cut -d= -f2- | tr -d ' \n')
export INFOMANIAK_USER INFOMANIAK_APP_PASSWORD
export PYTHONPATH="$REPO/src"

exec python3 -m infomaniak_mcp
```

```bash
chmod 700 ~/bin/infomaniak-mcp-launch
chmod 600 ~/.config/infomaniak.env
claude mcp add infomaniak --scope user -- ~/bin/infomaniak-mcp-launch
```

The client config then holds a path and nothing else. Because the launcher reads the
file itself rather than taking an argument, the password never appears in the process
list either. Rotating the password means editing one file, with no client config to
update.

### Any other client

The server speaks JSON-RPC 2.0 on stdin and stdout. Anything that can run a command
and exchange line delimited JSON can drive it:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | PYTHONPATH=src python3 -m infomaniak_mcp
```

## Tools

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
