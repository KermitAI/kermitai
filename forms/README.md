# Forms

Load with `[p]load forms` after installing the cog.

## Administrator commands

- `[p]forms create`: shows embed prompts for the display name (for example, Mod App), unique form ID, response channel, and question text. The builder updates one existing embed throughout setup. Click **Enter answer** and use a modal for text fields; choose the response destination from a text-channel dropdown. No channel replies are needed. Choose the answer type with **Short text**, **Paragraph**, **Number**, or **Yes / No** buttons. After each question use **Save**, **Save and exit**, **Cancel**, or **Add another question**. **Save** checkpoints the form and keeps the action buttons open. Only the administrator running the builder can use its buttons; used or expired buttons are disabled. Cancellation or a five-minute step timeout discards only unsaved changes.
- `[p]forms edit <form_id>`: resume adding questions to a saved form.
- `[p]forms list`: list saved forms and IDs.
- `[p]forms delete <form_id>`: delete the saved form and remove its launch buttons from all linked messages, preserving message content and unrelated buttons. Missing messages are skipped. If Discord denies cleanup, the command reports it and keeps the failed bindings so you can restore access and run deletion again. Existing member drafts can still be completed from their DMs.
- `[p]forms attach <form_id> <message_link> [button label]`: add a persistent button to an existing message authored by this bot in the same server. Messages with existing components are declined to preserve their controls.

These commands require Manage Server or the configured Red administrator role. Only one builder runs per server at a time. The builder uses buttons and modals after the initial command. Prefix commands still require the usual Red command setup.

## Member experience

Click the attached button in the server to receive a private DM embed. The embed shows one question, its expected answer type, and any saved answer. Click **Answer question** to open a modal for that question. Sending a valid answer saves it and advances the DM embed to the next question.

Use **Back** to review or change an earlier answer, **Save for later** to pause, or **Cancel** to delete the draft. After the last question, the embed shows a short preview and attaches a complete text review. **Submit** sends all responses to the configured server channel as a UTF-8 text attachment, including member ID, form ID and submission ID.

Answer types are short text, paragraph text, number, and yes/no. All questions are required. There is no configured question-count limit. Question labels and form names have a 45-character limit; answers allow up to 4,000 characters. Closing a modal discards unsent text; answers already sent remain saved.

Click the original server button to resume a saved draft or recover a deleted DM message. If another form is already in progress for that server, the bot resumes that draft first. Members must allow DMs from the bot; blocked DMs produce a private notice in the server. Answers stay in DMs until submission.

One draft per member per server is retained, with a snapshot of the questions. Editing the saved form does not change an active draft. Launch buttons, DM controls, and drafts survive restarts. Old five-question-page drafts are migrated to question navigation when resumed. Builder conversations do not resume after restart.

The bot needs View Channel, Send Messages, and Attach Files in the response channel. Delivery failures retain the draft for retry. Drafts are deleted on successful submission, cancellation, or a Red user-data deletion request. Submitted channel messages and existing DM messages must be removed from Discord separately. Drafts have no automatic expiry.

## Validation

Run `python -m unittest discover -s forms/tests`. These dependency-free checks validate answer types and syntax. A live Red/Discord smoke test is still required for button persistence, permissions, DM delivery, question navigation and channel delivery.
