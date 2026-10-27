"""Questionnaire definitions kept separate from Discord interactions."""

QUESTIONS = [
    ("Logging channels", "Please list all logging channels you use for member moderation. For example: server-log for Discord events, connection-log for joins/leaves, and staff-log for bans, kicks and other staff actions."),
    ("Streamer role", "Do you want a dedicated Streamer Role? Members receive it when they go live and lose it when they finish."),
    ("Boost announcements", "Do you want the App to announce when someone boosts the server?"),
    ("Welcome message", "Do you want a custom welcome message when someone joins the server?"),
    ("XP levelling", "Do you wish to enable an XP Levelling system?"),
    ("Stream alerts", "Do you want Twitch/YouTube stream alerts to be posted?"),
    ("Stream alert message", "Do you want to specify a message for stream alerts? Choose Yes to enter a message or use the default; choose No to leave the message unspecified."),
    ("Ticketing system", "Do you want a ticketing system for reports, help, applications and similar requests?"),
    ("Autokick", "Do you want an autokick setup if a member has not obtained the required role(s) within a set timeframe? This can help control bot accounts."),
]

# label, placeholder, required
FIELDS = {
    0: [("Logging channels and purposes", "server-log: Discord events; staff-log: staff actions", True)],
    1: [("Streamer role name", "For example: Live Now", True)],
    2: [("Boost announcement message", "Leave blank to use the App's default message", False)],
    3: [("Welcome message", "Leave blank to use the App's default message", False)],
    5: [("Role to ping", "Role name or ID, or 'none' for no ping", True)],
    6: [("Stream alert message", "Leave blank to use the App's default message", False)],
    8: [
        ("Required roles", "List the role names or IDs members must obtain", True),
        ("Time allowed after joining", "For example: 30 minutes, 2 hours, or 3 days", True),
        ("Kick notification channel (optional)", "Channel name or ID; leave blank for no notification", False),
        ("Role requirement", "Describe which roles members need to avoid being kicked", True),
    ],
}

TICKET_NOTICE = "Due to how extensive this setup can be, please reach out manually to set this up."


def next_step(step, answers):
    step += 1
    if step == 6 and answers.get("5", {}).get("choice") != "Yes":
        step += 1
    return step


def answer_text(answer):
    lines = [answer["choice"]] if answer.get("choice") else []
    lines.extend(f"{key}: {value}" for key, value in answer.get("details", {}).items())
    return "\n".join(lines) or "Not specified"


def report(session):
    lines = [
        "ONBOARDING RESPONSE",
        f"Respondent: {session['user_name']} (ID: {session['user_id']})",
        f"Requested by: {session['requester_id']}",
        f"Source server: {session['guild_name']} (ID: {session['guild_id']})",
        f"Questionnaire reference: {session['token']}",
    ]
    for index, (title, _) in enumerate(QUESTIONS):
        answer = session["answers"].get(str(index))
        lines.extend(["", f"{index + 1}. {title}", answer_text(answer) if answer else "Skipped (stream alerts declined)"])
    return "\n".join(lines)
