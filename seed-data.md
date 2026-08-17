# Seed Data (Synthetic — for demo/testing only)

All names, phone numbers, and emails below are fictional. Paste these rows into the
corresponding tabs of your Google Sheet (see README.md for the full schema) before
running a live demo, so lookups and reschedule/cancellation flows have something to
find.

Fake phone numbers use the reserved-for-fiction `555-01XX` exchange. Fake emails use
the reserved `example.test` / `example.com` domains.

## Patients

| patient_id | name | phone | email | preferred_channel | created_at |
|---|---|---|---|---|---|
| PT-0001 | Jordan Rivera | +1-555-0101 | jordan.rivera@example.test | web | 2026-08-01T09:00:00Z |
| PT-0002 | Amara Osei | +1-555-0102 | amara.osei@example.test | whatsapp | 2026-08-02T10:15:00Z |
| PT-0003 | Priya Nadar | +1-555-0103 | priya.nadar@example.test | phone | 2026-08-03T14:30:00Z |
| PT-0004 | Sam Whitfield | +1-555-0104 | sam.whitfield@example.test | web | 2026-08-04T11:00:00Z |
| PT-0005 | Lena Torres | +1-555-0105 | lena.torres@example.test | whatsapp | 2026-08-05T16:45:00Z |

## Appointments

| appointment_id | patient_id | patient_contact | channel | service_type | calendar_event_id | start_time | end_time | status | checkin_status | reminder_24h_status | reminder_2h_status | created_at | updated_at |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AP-1001 | PT-0001 | +1-555-0101 | web | Follow-Up Visit | (fill after Calendar create) | 2026-08-19T14:00:00Z | 2026-08-19T14:20:00Z | confirmed | none | pending | pending | 2026-08-17T09:00:00Z | 2026-08-17T09:00:00Z |
| AP-1002 | PT-0002 | +1-555-0102 | whatsapp | Routine Checkup | (fill after Calendar create) | 2026-08-18T10:00:00Z | 2026-08-18T10:30:00Z | confirmed | none | pending | pending | 2026-08-17T09:05:00Z | 2026-08-17T09:05:00Z |

## Waitlist

Columns: `waitlist_id, patient_id, patient_contact, channel, service_type, desired_window_start, desired_window_end, status, offer_expires_at, offer_slot_start, offer_slot_end, created_at, priority`

`offer_slot_start`/`offer_slot_end` are only populated once a slot is actually offered (they record which specific freed slot was offered, so an expiry/decline can re-offer the same slot to the next candidate).

| waitlist_id | patient_id | patient_contact | channel | service_type | desired_window_start | desired_window_end | status | offer_expires_at | offer_slot_start | offer_slot_end | created_at | priority |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WL-2001 | PT-0004 | +1-555-0104 | web | Routine Checkup | 2026-08-18T09:00:00Z | 2026-08-18T17:00:00Z | waiting | | | | 2026-08-16T12:00:00Z | 1 |
| WL-2002 | PT-0005 | +1-555-0105 | whatsapp | Routine Checkup | 2026-08-18T09:00:00Z | 2026-08-18T17:00:00Z | waiting | | | | 2026-08-16T13:00:00Z | 2 |

## NoShowLog / Escalations / ErrorLog / Dashboard

Leave these tabs with header rows only — they are populated automatically by the
workflow as it runs.

## Sample inbound payloads for manual testing

**Web Booking Form Intake**
```json
{
  "name": "Sam Whitfield",
  "phone": "+1-555-0104",
  "email": "sam.whitfield@example.test",
  "service_type": "Routine Checkup",
  "preferred_date": "2026-08-20",
  "preferred_time_window": "morning",
  "message": "Looking for a routine checkup sometime in the morning."
}
```

**WhatsApp Intake (Simulated Stand-In)** — shaped like a WhatsApp Business Cloud webhook
```json
{
  "entry": [{
    "changes": [{
      "value": {
        "messages": [{
          "from": "15550105",
          "timestamp": "1755000000",
          "text": { "body": "Hi, can I book a follow-up visit this week?" }
        }],
        "contacts": [{ "profile": { "name": "Lena Torres" } }]
      }
    }]
  }]
}
```

**Phone Transcript Intake** — from an existing call-transcription service
```json
{
  "call_id": "CALL-77213",
  "caller_phone": "+1-555-0103",
  "timestamp": "2026-08-17T15:02:00Z",
  "transcript_text": "Hi, this is Priya Nadar, I need to reschedule my appointment to next Tuesday afternoon if possible."
}
```

**Reminder Action Intake** (tapped from a reminder message)
```json
{ "appointment_id": "AP-1001", "action": "confirm", "channel": "web", "contact": "+1-555-0101" }
```

**Waitlist Offer Response Intake**
```json
{ "waitlist_id": "WL-2001", "response": "accept" }
```

**Clinical-content example (must escalate, never be answered by the system)**
```json
{
  "name": "Jordan Rivera",
  "phone": "+1-555-0101",
  "email": "jordan.rivera@example.test",
  "message": "I've had chest pain since yesterday, should I still come in for my checkup or go to the ER?"
}
```
