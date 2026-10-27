# Birthday

A Red 3.5 cog for Paimon. Replace `[p]` below with your command prefix.

1. Install the cog with Red's downloader and load it: `[p]load birthday`.
2. Configure announcements: `[p]birthday setup #birthdays Happy birthday, {member}! Have a wonderful day! 🎂`
3. Copy the link to an existing message sent by Paimon, then run `[p]birthday attach MESSAGE_LINK`.
4. Members click **Set my birthday**, enter **MM/DD**, and receive a private confirmation.

The selected message must belong to Paimon in the same server and have no existing buttons/components. Its text and embeds are preserved. Buttons continue working after cog reloads and bot restarts.

## Settings

- `[p]birthday schedule America/Toronto 9`: announce at 9 a.m. local time. This is the default. Use an IANA timezone name and an hour from 0 through 23. Daylight saving is handled automatically.
- `[p]birthday settings`: show channel, schedule, and custom text.
- `[p]birthday setup #channel New custom text`: change the destination or greeting.
- `[p]birthday disable`: stop signup and announcements, keeping existing dates.
- `[p]birthday forget`: delete your own birthday in this server.

Setup, attach, schedule, settings, and disable require bot administrator status or Manage Server permission.

Use `{member}` wherever you want the member's mention. If omitted, the mention is added at the start. Only the birthday member can be pinged; role mentions and @everyone are suppressed. Messages may contain up to 1,800 characters.

## Scheduling and saved data

The cog checks every minute and announces once per member per year. It catches up later the same day if Paimon restarts after the scheduled time. It does not announce birthdays missed on previous dates. February 29 birthdays are celebrated on February 28 in non-leap years. Members who have left the server are skipped.

Dates are stored separately for each server through Red Config, with no birth year or age collected. Clicking the button again updates the date. Changing a birthday after an announcement does not generate a second announcement that year. Red's user-data deletion requests are supported.

Paimon needs access to the signup message and View Channel / Send Messages in the announcement channel. Keep Paimon running for scheduled announcements. A crash between Discord accepting a message and saving its sent marker can produce a duplicate on restart.

## Validation

Run `python -m unittest discover -s birthday/tests -v`. Live Discord signup, message editing, and announcements should also be checked on a test server.
