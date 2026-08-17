# Patient Appointment & No-Show Reduction Pipeline (Demo)

A single, self-contained n8n workflow demonstrating a practice-agnostic
appointment scheduling and no-show reduction system for clinics/private
practices. **Portfolio/demonstration build.**

- **All patient data anywhere in this workflow is synthetic test data.**
  Never connect it to a real EHR, real scheduling system, or real
  individuals' information.
- **Scheduling and logistics only.** The workflow detects anything
  clinical-sounding, urgent, or ambiguous and routes it to staff — it never
  generates medical/clinical content.
- Already created in your local n8n instance as **"Patient Appointment &
  No-Show Reduction Pipeline (Demo)"** (inactive). It won't run correctly
  until you complete the setup below — the credentials it references are
  placeholders for Google Sheets/Calendar/SMTP.

## Architecture

Everything lives on **one canvas**, no `Execute Workflow` sub-workflows.
Reusable logic (classification, calendar verification, outbound messaging,
staff escalation, error handling) is implemented as **shared node groups**
that multiple upstream branches feed into (fan-in) — sticky notes on the
canvas mark each shared block and explain why it's shared. A carried
"envelope" object (`intent`, `origin_stage`, `channel`, `contact.*`,
`patient_id`, `service_type`, etc.) flows through the graph, and `Switch`
nodes route on `origin_stage`/`intent` after a shared block finishes to send
results back to the correct next step.

Two distinct reply mechanisms are used deliberately:
- **Respond to Webhook** — only for a direct, synchronous reply to whoever
  is *currently* hitting a webhook (the booking/reschedule/cancellation
  caller, or someone tapping a reminder/waitlist-offer action link).
- **HTTP Request → outbound messaging gateway** — for anything with no live
  request to reply to, or where the recipient differs from whoever
  triggered the current execution (24h/2h reminders, waitlist offers to a
  *different* patient than whoever cancelled, no-show follow-ups).

Stages on the canvas (sticky-note sectioned, matches the spec 1:1):
1. Multi-Channel Intake & Normalization (web form / simulated WhatsApp /
   phone transcript) → shared Patient Lookup/Create
2. Request Understanding (Claude classification + structured extraction) →
   Staff Escalation gate → intent routing
3. Calendar Verification — "Find Available Slot in Window" (booking/
   reschedule) and "Verify Specific Slot Still Open" (waitlist fill)
4. Booking/Reschedule Confirmation & Reply
5. Multi-Stage Reminders (24h / 2h, poll every 15 min)
6. Reminder Action Intake (confirm / reschedule / cancel from a reminder)
7. Cancellation & Waitlist Fill
8. Waitlist Offer Response & Expiry (the explicit "don't hold a slot open
   indefinitely" race-condition handling)
9. No-Show Detection
10. Staff Escalation (shared, fed from 8 different trigger points)
11. Reliability Layer (retry/backoff + shared error-alert fan-in)
12. Reporting / Visibility (hourly metrics snapshot)

## Regenerating the workflow

The workflow JSON is generated, not hand-written, by `build_workflow.py`
(~85 helper-built + hand-specified nodes, 133 total including sticky
notes). This keeps node IDs/positions/connections internally consistent —
the script validates every connection reference and does a JS syntax check
equivalent before writing the file.

```
python build_workflow.py
```

Produces `patient-appointment-pipeline.json`, which was pushed to the local
n8n instance via `POST /api/v1/workflows` using the API key in `.env`. To
push an updated version after editing the script, either re-run the same
POST against `PATCH /api/v1/workflows/<id>` (this workflow's id is printed
by the push, or visible in the n8n UI URL), or re-import the JSON file
manually via n8n's "Import from File".

## Required setup before this can actually run

1. **Google Sheets credential** — create a "Google Sheets OAuth2 API"
   credential in n8n and assign it on every Google Sheets node (they
   currently reference a placeholder credential ID). Create one spreadsheet
   with the tabs below, and replace `REPLACE_WITH_YOUR_GOOGLE_SHEET_ID` in
   `build_workflow.py`'s `SPREADSHEET_ID_PLACEHOLDER` (then regenerate/
   re-push), or just fix the `documentId` value on each Sheets node
   directly in the n8n UI.
2. **Google Calendar credential** — create a "Google Calendar OAuth2 API"
   credential and assign it on every Google Calendar node. The `calendar`
   parameter defaults to `"primary"` — point it at whatever calendar you
   want to act as the clinic's calendar of record.
3. **SMTP credential** — create an SMTP credential for staff email alerts
   (escalations + unhandled errors) and assign it on the two Email nodes.
4. **Anthropic** — already wired to your existing "Anthropic account"
   credential and the `claude-sonnet-4-6` model reference already proven
   working in your other workflow on this instance. No action needed
   unless you want a different model.
5. Seed the Google Sheet with the synthetic rows in `seed-data.md` so
   lookups/reschedule/cancellation have something to find.
6. Point `MESSAGING_GATEWAY_URL_PLACEHOLDER` (currently
   `https://example-messaging-gateway.test/send`) at a real SMS/WhatsApp/
   telephony send API if you want reminders/waitlist offers to actually
   deliver — otherwise that call will simply fail (and correctly route to
   the error-alert chain).
7. Activate the workflow once credentials are in place.

## Google Sheet schema

One spreadsheet, these tabs (see `seed-data.md` for fictional sample rows
and example inbound payloads for manual testing):

- **Patients**: `patient_id, name, phone, email, preferred_channel, created_at`
- **Appointments**: `appointment_id, patient_id, patient_contact, channel, service_type, calendar_event_id, start_time, end_time, status, checkin_status, reminder_24h_status, reminder_2h_status, created_at, updated_at`
- **Waitlist**: `waitlist_id, patient_id, patient_contact, channel, service_type, desired_window_start, desired_window_end, status, offer_expires_at, offer_slot_start, offer_slot_end, created_at, priority`
- **NoShowLog**: `log_id, appointment_id, patient_id, service_type, scheduled_time, detected_at`
- **Escalations**: `escalation_id, timestamp, channel, patient_contact, raw_text, system_understood_json, reason, status`
- **ErrorLog**: `error_id, timestamp, node_name, stage, error_message, item_snapshot`
- **Dashboard**: `snapshot_at, bookings_made_total, reminders_sent_total, confirmation_rate, no_show_rate, waitlist_fill_count, escalation_count`

`status` values on Appointments: `confirmed | cancelled | no_show | completed`.
`status` values on Waitlist: `waiting | offered | booked | declined | expired`.

## Webhook endpoints (once active)

- `POST /webhook/booking/web` — web booking form
- `POST /webhook/booking/whatsapp` — simulated WhatsApp Business Cloud payload
- `POST /webhook/booking/phone` — call-transcription service output
- `POST /webhook/reminder-action` — `{appointment_id, action: confirm|reschedule|cancel, channel, contact}`
- `POST /webhook/waitlist-response` — `{waitlist_id, response: accept|decline}`

Full example payloads for each are in `seed-data.md`, including a
clinical-content example that should escalate to staff instead of being
answered by the system.

## Known limitations (by design, documented rather than silently broken)

- **Business hours / service durations / reminder offsets / no-show grace /
  waitlist offer window** are hardcoded constants in `build_workflow.py`
  (`CONFIG_JS`, embedded into the relevant Code nodes) rather than a config
  sheet — swap these for a real config table if you productionize this.
- **No-show detection and waitlist-offer-expiry checks process the single
  most-urgent item per poll cycle**, not a batch. Both feed shared node
  groups that use single-item cross-node references (`$('Node').first()`);
  a genuine multi-item batch would need a `Split In Batches` loop. Nothing
  is silently dropped — any additional overdue/expired row is still overdue/
  expired on the very next 15/10-minute cycle.
- **WhatsApp is fully simulated.** Swap the "WhatsApp Intake (Simulated
  Stand-In)" webhook for n8n's real WhatsApp Business Cloud trigger/node if
  you have Meta developer access.
- **Alternative-slot selection is single-round.** If no exact slot is
  available, the patient is offered up to 3 alternatives and expected to
  reply with their choice as a new free-text message (which flows back
  through normal intake) rather than a structured "pick one" UI.
