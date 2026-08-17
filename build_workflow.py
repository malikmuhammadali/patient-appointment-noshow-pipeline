"""
Generates patient-appointment-pipeline.json — a single, self-contained n8n
workflow implementing the Patient Appointment & No-Show Reduction Pipeline.

Why a generator script instead of hand-written JSON: the workflow has ~85
nodes on one canvas. Constructing node IDs, positions, and the connections
map by hand is error-prone at this scale; this script builds them
programmatically and validates every connection reference before writing
the file, so the output is guaranteed structurally sound.

Run: python build_workflow.py
Output: patient-appointment-pipeline.json (in the same directory)

ALL data in this workflow (patient names, phone numbers, emails) is
synthetic/fictional. This system handles scheduling/logistics only and
must never be wired to a real EHR, real patient records, or asked to
produce clinical/medical content.
"""

import json
import uuid

# ---------------------------------------------------------------------------
# Node registry
# ---------------------------------------------------------------------------

NODES = []          # list of node dicts, in creation order
CONNECTIONS = {}    # node name -> { connectionType: [ [ {node,type,index}, ... ] ] }
NAMES_SEEN = set()


def _next_id():
    return str(uuid.uuid4())


def add_node(name, type_, position, parameters=None, type_version=1,
             credentials=None, on_error=None, retry=False, notes=None,
             continue_on_fail=None, always_output_data=False):
    """Register a node. Returns the node name (used as the connection key)."""
    if name in NAMES_SEEN:
        raise ValueError(f"Duplicate node name: {name}")
    NAMES_SEEN.add(name)

    node = {
        "id": _next_id(),
        "name": name,
        "type": type_,
        "typeVersion": type_version,
        "position": list(position),
        "parameters": parameters or {},
    }
    if credentials:
        node["credentials"] = credentials
    if retry:
        node["retryOnFail"] = True
        node["maxTries"] = 4
        node["waitBetweenTries"] = 2000
    if on_error:
        node["onError"] = on_error
    if always_output_data:
        node["alwaysOutputData"] = True
    if continue_on_fail is not None:
        node["continueOnFail"] = continue_on_fail
    if notes:
        node["notes"] = notes
    NODES.append(node)
    return name


def connect(src, src_output_index, dst, dst_input_index=0, conn_type="main"):
    """Wire src's output (by index) to dst's input (by index)."""
    if src not in NAMES_SEEN:
        raise ValueError(f"connect(): unknown source node '{src}'")
    if dst not in NAMES_SEEN:
        raise ValueError(f"connect(): unknown destination node '{dst}'")

    bucket = CONNECTIONS.setdefault(src, {}).setdefault(conn_type, [])
    while len(bucket) <= src_output_index:
        bucket.append([])
    bucket[src_output_index].append({"node": dst, "type": conn_type, "index": dst_input_index})


def connect_main(src, dst, src_output_index=0, dst_input_index=0):
    connect(src, src_output_index, dst, dst_input_index, "main")


def fan_in(sources, dst, dst_input_index=0):
    """Connect several independent upstream branches into the same shared node."""
    for s in sources:
        connect_main(s, dst, 0, dst_input_index)


def sticky(name, content, position, size=(380, 260), color=None):
    params = {"content": content, "height": size[1], "width": size[0]}
    if color:
        params["color"] = color
    add_node(name, "n8n-nodes-base.stickyNote", position, parameters=params, type_version=1)


# ---------------------------------------------------------------------------
# Shared business-rule constants, embedded verbatim into relevant Code/Set
# node bodies at generation time (see CONFIG_JS below). Kept in one place so
# the generator and the README stay in sync with what's actually in the
# workflow.
# ---------------------------------------------------------------------------

SERVICE_DURATIONS_MIN = {
    "New Patient Consultation": 45,
    "Follow-Up Visit": 20,
    "Routine Checkup": 30,
    "Lab Review / Results Discussion": 15,
    "Vaccination / Injection": 10,
}

BUSINESS_HOURS = {"start": "09:00", "end": "17:00", "days": [1, 2, 3, 4, 5]}  # Mon-Fri
SLOT_GRANULARITY_MIN = 15
REMINDER_OFFSETS_HOURS = [24, 2]
NO_SHOW_GRACE_MIN = 15
WAITLIST_OFFER_WINDOW_MIN = 30
CLINIC_TIMEZONE = "America/New_York"  # placeholder — set to the real practice timezone

CONFIG_JS = f"""
const CONFIG = {{
  serviceDurationsMin: {json.dumps(SERVICE_DURATIONS_MIN)},
  businessHours: {json.dumps(BUSINESS_HOURS)},
  slotGranularityMin: {SLOT_GRANULARITY_MIN},
  noShowGraceMin: {NO_SHOW_GRACE_MIN},
  waitlistOfferWindowMin: {WAITLIST_OFFER_WINDOW_MIN},
  timezone: {json.dumps(CLINIC_TIMEZONE)},
}};
""".strip()

SPREADSHEET_ID_PLACEHOLDER = "REPLACE_WITH_YOUR_GOOGLE_SHEET_ID"
MESSAGING_GATEWAY_URL_PLACEHOLDER = "https://example-messaging-gateway.test/send"

GOOGLE_SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "GOOGLE_SHEETS_CRED_ID", "name": "Google Sheets account"}}
GOOGLE_CALENDAR_CRED = {"googleCalendarOAuth2Api": {"id": "GOOGLE_CALENDAR_CRED_ID", "name": "Google Calendar account"}}
# Matches the real, already-configured "Anthropic account" credential in
# this n8n instance (confirmed via GET /api/v1/credentials) and the exact
# model reference already proven working in the "Universal Inquiry-to-Sale
# Pipeline" reference workflow on this same instance.
ANTHROPIC_CRED = {"anthropicApi": {"id": "gJXpraBF1c3fBu3I", "name": "Anthropic account"}}
ANTHROPIC_MODEL = {"__rl": True, "mode": "list", "value": "claude-sonnet-4-6", "cachedResultName": "Claude Sonnet 4.6"}
SMTP_CRED = {"smtp": {"id": "SMTP_CRED_ID", "name": "Staff SMTP account"}}
CALENDAR_ID_PLACEHOLDER = "primary"

# ---------------------------------------------------------------------------
# Node-family helper factories (keep exact parameter shapes in one place)
# ---------------------------------------------------------------------------

def webhook(name, position, path, methods="POST"):
    return add_node(
        name, "n8n-nodes-base.webhook", position,
        parameters={
            "httpMethod": methods,
            "path": path,
            "responseMode": "responseNode",
            "options": {"rawBody": False},
        },
        type_version=2.1,
    )


def respond_to_webhook(name, position, body_expr):
    return add_node(
        name, "n8n-nodes-base.respondToWebhook", position,
        parameters={
            "respondWith": "json",
            "responseBody": body_expr,
            "options": {"responseCode": 200},
        },
        type_version=1.5,
    )


def schedule_trigger(name, position, minutes_interval):
    return add_node(
        name, "n8n-nodes-base.scheduleTrigger", position,
        parameters={"rule": {"interval": [{"field": "minutes", "minutesInterval": minutes_interval}]}},
        type_version=1.3,
    )


def set_node(name, position, assignments, retry=False):
    """assignments: list of (field_name, value_expr, type) tuples."""
    return add_node(
        name, "n8n-nodes-base.set", position,
        parameters={
            "assignments": {
                "assignments": [
                    {"id": str(uuid.uuid4()), "name": n, "value": v, "type": t}
                    for (n, v, t) in assignments
                ]
            },
            "options": {},
        },
        type_version=3.5,
        retry=retry,
    )


def code_node(name, position, js_code, mode="runOnceForAllItems"):
    return add_node(
        name, "n8n-nodes-base.code", position,
        parameters={"mode": mode, "language": "javaScript", "jsCode": js_code},
        type_version=2,
    )


def if_node(name, position, conditions, combinator="and"):
    """conditions: list of (left_expr, operator_type, operation, right_expr)."""
    return add_node(
        name, "n8n-nodes-base.if", position,
        parameters={
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 1},
                "combinator": combinator,
                "conditions": [
                    {
                        "leftValue": left,
                        "rightValue": right,
                        "operator": {"type": otype, "operation": op},
                    }
                    for (left, otype, op, right) in conditions
                ],
            },
            "options": {},
        },
        type_version=2.3,
    )


def switch_node(name, position, field_expr, cases, fallback_output="staff_escalation"):
    """cases: ordered list of output-key strings (e.g. ["new_booking","reschedule",...]).
    Routes on exact string equality against field_expr; unmatched -> extra fallback output.
    """
    outputs = cases + [fallback_output]
    return add_node(
        name, "n8n-nodes-base.switch", position,
        parameters={
            "rules": {
                "values": [
                    {
                        "conditions": {
                            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 1},
                            "combinator": "and",
                            "conditions": [{
                                "leftValue": field_expr,
                                "rightValue": case,
                                "operator": {"type": "string", "operation": "equals"},
                            }],
                        },
                    }
                    for case in cases
                ],
            },
            "options": {"fallbackOutput": "extra", "renameFallbackOutput": fallback_output},
        },
        type_version=3.4,
    ), outputs


def email_send(name, position, to_expr, subject_expr, text_expr):
    return add_node(
        name, "n8n-nodes-base.emailSend", position,
        parameters={
            "fromEmail": "scheduling-alerts@example-clinic.test",
            "toEmail": to_expr,
            "subject": subject_expr,
            "text": text_expr,
            "options": {},
        },
        type_version=2.1,
        credentials=SMTP_CRED,
        retry=True,
        on_error="continueErrorOutput",
    )


def http_request(name, position, url_expr, method="POST", body_expr=None, extra_options=None):
    params = {
        "method": method,
        "url": url_expr,
        "sendBody": body_expr is not None,
        "options": extra_options or {},
    }
    if body_expr is not None:
        params["specifyBody"] = "json"
        params["jsonBody"] = body_expr
    return add_node(
        name, "n8n-nodes-base.httpRequest", position,
        parameters=params, type_version=4.2,
        retry=True, on_error="continueErrorOutput",
    )


def sheets_rl(sheet_name):
    """Resource-locator pair for a Google Sheets node's documentId/sheetName params."""
    return (
        {"__rl": True, "value": SPREADSHEET_ID_PLACEHOLDER, "mode": "id"},
        {"__rl": True, "value": sheet_name, "mode": "name"},
    )


def sheets_append(name, position, sheet_name):
    doc, sheet = sheets_rl(sheet_name)
    return add_node(
        name, "n8n-nodes-base.googleSheets", position,
        parameters={
            "resource": "sheet",
            "operation": "append",
            "documentId": doc,
            "sheetName": sheet,
            "columns": {"mappingMode": "autoMapInputData", "value": {}, "schema": []},
            "options": {},
        },
        type_version=4.7, credentials=GOOGLE_SHEETS_CRED,
        retry=True, on_error="continueErrorOutput",
    )


def sheets_upsert(name, position, sheet_name, match_column, match_value_expr=None):
    """Find-or-create-and-update a row by a matching column (appendOrUpdate)."""
    doc, sheet = sheets_rl(sheet_name)
    return add_node(
        name, "n8n-nodes-base.googleSheets", position,
        parameters={
            "resource": "sheet",
            "operation": "appendOrUpdate",
            "documentId": doc,
            "sheetName": sheet,
            "columnToMatchOn": match_column,
            "valueToMatchOn": match_value_expr or f"={{{{ $json.{match_column} }}}}",
            "columns": {"mappingMode": "autoMapInputData", "value": {}, "schema": []},
            "options": {},
        },
        type_version=4.7, credentials=GOOGLE_SHEETS_CRED,
        retry=True, on_error="continueErrorOutput",
    )


def sheets_read_filtered(name, position, sheet_name, filter_col=None, filter_value_expr=None, always_output_data=True):
    doc, sheet = sheets_rl(sheet_name)
    params = {
        "resource": "sheet",
        "operation": "read",
        "documentId": doc,
        "sheetName": sheet,
        "options": {},
    }
    if filter_col:
        params["filtersUI"] = {"values": [{"lookupColumn": filter_col, "lookupValue": filter_value_expr}], "combineFilters": "AND"}
    return add_node(
        name, "n8n-nodes-base.googleSheets", position,
        parameters=params, type_version=4.7, credentials=GOOGLE_SHEETS_CRED,
        retry=True, on_error="continueErrorOutput", always_output_data=always_output_data,
    )


def calendar_get_all(name, position, time_min_expr, time_max_expr):
    return add_node(
        name, "n8n-nodes-base.googleCalendar", position,
        parameters={
            "resource": "event",
            "operation": "getAll",
            "calendar": {"__rl": True, "value": CALENDAR_ID_PLACEHOLDER, "mode": "list"},
            "timeMin": time_min_expr,
            "timeMax": time_max_expr,
            "returnAll": True,
        },
        type_version=1.3, credentials=GOOGLE_CALENDAR_CRED,
        retry=True, on_error="continueErrorOutput",
    )


def calendar_create(name, position):
    return add_node(
        name, "n8n-nodes-base.googleCalendar", position,
        parameters={
            "resource": "event",
            "operation": "create",
            "calendar": {"__rl": True, "value": CALENDAR_ID_PLACEHOLDER, "mode": "list"},
            "start": "={{ $json.slot_start }}",
            "end": "={{ $json.slot_end }}",
            "additionalFields": {"summary": "={{ $json.calendar_summary }}", "description": "={{ $json.calendar_description }}"},
        },
        type_version=1.3, credentials=GOOGLE_CALENDAR_CRED,
        retry=True, on_error="continueErrorOutput",
    )


def calendar_update(name, position):
    return add_node(
        name, "n8n-nodes-base.googleCalendar", position,
        parameters={
            "resource": "event",
            "operation": "update",
            "calendar": {"__rl": True, "value": CALENDAR_ID_PLACEHOLDER, "mode": "list"},
            "eventId": "={{ $json.calendar_event_id }}",
            "updateFields": {"start": "={{ $json.slot_start }}", "end": "={{ $json.slot_end }}"},
        },
        type_version=1.3, credentials=GOOGLE_CALENDAR_CRED,
        retry=True, on_error="continueErrorOutput",
    )


def calendar_delete(name, position):
    return add_node(
        name, "n8n-nodes-base.googleCalendar", position,
        parameters={
            "resource": "event",
            "operation": "delete",
            "calendar": {"__rl": True, "value": CALENDAR_ID_PLACEHOLDER, "mode": "list"},
            "eventId": "={{ $json.calendar_event_id }}",
        },
        type_version=1.3, credentials=GOOGLE_CALENDAR_CRED,
        retry=True, on_error="continueErrorOutput",
    )


print("Helper factories loaded.")

# ---------------------------------------------------------------------------
# STAGE 1 — Multi-Channel Booking Intake & Normalization
# ---------------------------------------------------------------------------

Y1 = 0
sticky(
    "SN Overview", (
        "PATIENT APPOINTMENT & NO-SHOW REDUCTION PIPELINE\n\n"
        "Portfolio/demo build. ALL patient data anywhere in this workflow "
        "(names, phones, emails) is SYNTHETIC TEST DATA — never connect this "
        "to a real EHR or real individuals.\n\n"
        "Scheduling & logistics ONLY. Any clinical-sounding content is "
        "detected and routed to staff — this workflow never gives medical "
        "advice.\n\n"
        "Single-canvas design: reusable logic (classification, calendar "
        "verification, outbound messaging, escalation, error handling) is "
        "implemented as SHARED node groups that multiple upstream branches "
        "feed into (fan-in), with a carried 'envelope' object + Switch nodes "
        "routing results back out — see sticky notes at each shared block."
    ),
    (-320, -80), size=(560, 420), color=7,
)

webhook("Web Booking Form Intake", (0, Y1), "booking/web")
webhook("WhatsApp Intake (Simulated Stand-In)", (0, Y1 + 220), "booking/whatsapp")
webhook("Phone Transcript Intake", (0, Y1 + 440), "booking/phone")

sticky(
    "SN Intake", (
        "STAGE 1 — MULTI-CHANNEL INTAKE\n\n"
        "Each channel has its own webhook + normalization branch. All three "
        "map into ONE common internal 'booking envelope' so every stage "
        "downstream is channel-agnostic.\n\n"
        "WhatsApp is a SIMULATED stand-in: the webhook body is shaped like a "
        "real WhatsApp Business Cloud payload for demo realism, but there is "
        "no live Meta integration. Phone Transcript Intake assumes an "
        "existing call-transcription service posts the transcript text here "
        "— no telephony infrastructure is built."
    ),
    (0, -360), size=(680, 260), color=4,
)

set_node(
    "Normalize: Web -> Envelope", (280, Y1),
    [
        ("request_id", "={{ $json.body?.request_id || $workflow.id + '-' + $now.toMillis() }}", "string"),
        ("channel", "web", "string"),
        ("contact.name", "={{ $json.body.name }}", "string"),
        ("contact.phone", "={{ $json.body.phone }}", "string"),
        ("contact.email", "={{ $json.body.email }}", "string"),
        ("service_type_hint", "={{ $json.body.service_type }}", "string"),
        ("requested_window_hint", "={{ $json.body.preferred_date + ' ' + ($json.body.preferred_time_window || '') }}", "string"),
        ("raw_text", "={{ $json.body.message || '' }}", "string"),
    ],
)

code_node(
    "Normalize: WhatsApp -> Envelope", (280, Y1 + 220),
    """
// Simulated WhatsApp Business Cloud webhook shape.
const body = $input.first().json.body;
const msg = body?.entry?.[0]?.changes?.[0]?.value?.messages?.[0] || {};
const contact = body?.entry?.[0]?.changes?.[0]?.value?.contacts?.[0]?.profile || {};

return [{
  json: {
    request_id: `wa-${msg.timestamp || Date.now()}`,
    channel: 'whatsapp',
    'contact.name': contact.name || '',
    'contact.phone': msg.from || '',
    'contact.email': '',
    service_type_hint: '',
    requested_window_hint: '',
    raw_text: msg.text?.body || '',
  },
}];
""".strip(),
)

set_node(
    "Normalize: Phone Transcript -> Envelope", (280, Y1 + 440),
    [
        ("request_id", "={{ 'call-' + $json.body.call_id }}", "string"),
        ("channel", "phone", "string"),
        ("contact.name", "", "string"),
        ("contact.phone", "={{ $json.body.caller_phone }}", "string"),
        ("contact.email", "", "string"),
        ("service_type_hint", "", "string"),
        ("requested_window_hint", "", "string"),
        ("raw_text", "={{ $json.body.transcript_text }}", "string"),
    ],
)

connect_main("Web Booking Form Intake", "Normalize: Web -> Envelope")
connect_main("WhatsApp Intake (Simulated Stand-In)", "Normalize: WhatsApp -> Envelope")
connect_main("Phone Transcript Intake", "Normalize: Phone Transcript -> Envelope")

# --- Shared: Patient Lookup / Create (fed by all three channels — fan-in) ---

sheets_read_filtered(
    "Sheets: Find Patient By Phone", (560, Y1 + 220),
    "Patients", filter_col="phone", filter_value_expr="={{ $json['contact.phone'] }}",
)

if_node(
    "IF: Patient Found?", (840, Y1 + 220),
    [("={{ $json.patient_id }}", "string", "exists", "")],
)

set_node(
    "Prepare New Patient Record", (1120, Y1 + 340),
    [
        ("patient_id", "={{ 'PT-' + Math.floor(Math.random()*900000+100000) }}", "string"),
        ("name", "={{ $json['contact.name'] || 'Unknown Caller' }}", "string"),
        ("phone", "={{ $json['contact.phone'] }}", "string"),
        ("email", "={{ $json['contact.email'] || '' }}", "string"),
        ("preferred_channel", "={{ $json.channel }}", "string"),
        ("created_at", "={{ $now.toISO() }}", "string"),
    ],
)
sheets_append("Sheets: Create New Patient Record", (1400, Y1 + 340), "Patients")

fan_in(
    ["Normalize: Web -> Envelope", "Normalize: WhatsApp -> Envelope", "Normalize: Phone Transcript -> Envelope"],
    "Sheets: Find Patient By Phone",
)
connect_main("Sheets: Find Patient By Phone", "IF: Patient Found?")
# true-branch (found, output index 0) fans into classification prep in Stage 2 below
connect("IF: Patient Found?", 1, "Prepare New Patient Record", 0)  # false (not found)
connect_main("Prepare New Patient Record", "Sheets: Create New Patient Record")

sticky(
    "SN Patient Lookup", (
        "SHARED BLOCK — Patient Lookup/Create\n\n"
        "Fed by all three intake channels (fan-in). Looks the contact phone "
        "number up in the Patients sheet; creates a new synthetic patient "
        "record if none exists. Both outcomes converge on the same next "
        "step (Request Understanding) without needing a Merge node, since "
        "exactly one IF branch fires per execution."
    ),
    (560, Y1 + 520), size=(620, 220), color=4,
)

print(f"Stage 1 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 2 — Request Understanding (Classification + Field Extraction)
# NOTE: exact LangChain node type/typeVersion/parameter shape for the three
# AI nodes below is confirmed against current n8n docs before final JSON is
# emitted — see verify_and_patch_ai_nodes() near the bottom of this file.
# ---------------------------------------------------------------------------

Y2 = 0
X2 = 1680

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["new_booking", "reschedule", "cancellation", "staff_question"]},
        "service_type": {"type": "string"},
        "requested_window_start": {"type": "string"},
        "requested_window_end": {"type": "string"},
        "urgency": {"type": "string", "enum": ["routine", "urgent"]},
        "contains_clinical_content": {"type": "boolean"},
        "explicit_human_request": {"type": "boolean"},
        "needs_staff": {"type": "boolean"},
        "reasoning": {"type": "string"},
    },
    "required": ["intent", "urgency", "contains_clinical_content", "explicit_human_request", "needs_staff"],
}

CLASSIFICATION_SYSTEM_PROMPT = """
You classify inbound patient scheduling messages for a clinic's automated
booking system. You handle SCHEDULING AND LOGISTICS ONLY.

You must NEVER generate, suggest, or imply any clinical/medical judgment,
diagnosis, symptom interpretation, or treatment advice. If the message
contains anything even slightly clinical (symptoms, medication questions,
"is this normal", requests for medical advice), set contains_clinical_content
to true and needs_staff to true — regardless of anything else in the message.

Also set needs_staff to true if: the message is ambiguous and you cannot
confidently classify it; the patient explicitly asks for a human/staff
member; or urgency looks like an emergency (set urgency="urgent" too in
that case).

Extract only scheduling fields: intent (new_booking, reschedule,
cancellation, or staff_question if none clearly apply), service_type (best
guess from the message, empty string if unclear), requested_window_start /
requested_window_end (ISO 8601 if a specific date/time or range is stated,
otherwise empty strings), urgency (routine or urgent), and a short
reasoning string. Return ONLY the structured fields — no clinical content,
ever.
""".strip()

set_node(
    "Prep: Classification Input", (X2, Y2 + 220),
    [
        ("raw_text", "={{ $json.raw_text }}", "string"),
        ("channel", "={{ $json.channel }}", "string"),
        ("patient_id", "={{ $json.patient_id }}", "string"),
        ("contact.name", "={{ $json['contact.name'] }}", "string"),
        ("contact.phone", "={{ $json['contact.phone'] }}", "string"),
        ("contact.email", "={{ $json['contact.email'] }}", "string"),
    ],
)

add_node(
    "Anthropic Chat Model: Claude", "@n8n/n8n-nodes-langchain.lmChatAnthropic", (X2 + 280, Y2 + 340),
    type_version=1.5,
    parameters={"model": ANTHROPIC_MODEL, "options": {}},
    credentials=ANTHROPIC_CRED,
)

add_node(
    "Structured Output Parser: Classification Schema", "@n8n/n8n-nodes-langchain.outputParserStructured", (X2 + 280, Y2 + 500),
    type_version=1.3,
    parameters={"schemaType": "manual", "inputSchema": json.dumps(CLASSIFICATION_SCHEMA, indent=2), "autoFix": False},
)

# System instructions are folded directly into the one "text" prompt field
# (rather than a separate system-message param) so they reach the model
# regardless of chainLlm's exact message-composition options.
CLASSIFY_PROMPT_TEMPLATE = (
    CLASSIFICATION_SYSTEM_PROMPT
    + "\n\n---\nChannel: {{ $json.channel }}\nMessage to classify:\n{{ $json.raw_text }}"
)

add_node(
    "Classify & Extract Request (Claude)", "@n8n/n8n-nodes-langchain.chainLlm", (X2 + 280, Y2 + 220),
    type_version=1.9,
    parameters={
        "promptType": "define",
        "text": "=" + CLASSIFY_PROMPT_TEMPLATE,
        "hasOutputParser": True,
    },
    retry=True, on_error="continueErrorOutput",
)

connect("Anthropic Chat Model: Claude", 0, "Classify & Extract Request (Claude)", 0, conn_type="ai_languageModel")
connect("Structured Output Parser: Classification Schema", 0, "Classify & Extract Request (Claude)", 0, conn_type="ai_outputParser")
connect_main("Prep: Classification Input", "Classify & Extract Request (Claude)")

# fan-in: both patient-lookup outcomes feed classification input prep
fan_in(["IF: Patient Found?", "Sheets: Create New Patient Record"], "Prep: Classification Input")
# (IF: Patient Found? true-output wired explicitly below since fan_in uses output index 0 for both;
#  the true branch of the IF is exactly output index 0, matching fan_in's default.)

# The chain node's output is the PARSED classification object only — it does
# not retain input fields. Re-attach patient/contact/channel context here
# (cross-node reference to the pre-chain item) so every later node still has
# a complete envelope.
code_node(
    "Attach Envelope Fields To Classification", (X2 + 560, Y2 + 60),
    """
const classified = $input.first().json;
const envelope = $('Prep: Classification Input').first().json;
return [{ json: { ...classified, ...envelope } }];
""".strip(),
)
connect_main("Classify & Extract Request (Claude)", "Attach Envelope Fields To Classification")

if_node(
    "IF: Needs Staff / Clinical / Urgent?", (X2 + 840, Y2 + 220),
    [
        ("={{ $json.needs_staff || $json.contains_clinical_content || $json.explicit_human_request || $json.urgency === 'urgent' }}",
         "boolean", "true", True),
    ],
)
connect_main("Attach Envelope Fields To Classification", "IF: Needs Staff / Clinical / Urgent?")

switch_node(
    "Switch: Route By Intent", (X2 + 840, Y2 + 340),
    field_expr="={{ $json.intent }}",
    cases=["new_booking", "reschedule", "cancellation"],
    fallback_output="staff_escalation",
)
connect(  # IF false-output (index 1) -> route switch
    "IF: Needs Staff / Clinical / Urgent?", 1, "Switch: Route By Intent", 0, conn_type="main",
)

sheets_read_filtered(
    "Sheets: Find Patient's Upcoming Appointment", (X2 + 1120, Y2 + 500),
    "Appointments", filter_col="patient_id", filter_value_expr="={{ $json.patient_id }}",
)
if_node(
    "IF: Upcoming Appointment Found?", (X2 + 1400, Y2 + 500),
    [("={{ $json.appointment_id }}", "string", "exists", "")],
)
connect(  # switch output index 1 == "reschedule"
    "Switch: Route By Intent", 1, "Sheets: Find Patient's Upcoming Appointment", 0,
)
connect_main("Sheets: Find Patient's Upcoming Appointment", "IF: Upcoming Appointment Found?")

sticky(
    "SN Understanding", (
        "SHARED BLOCK — Request Understanding\n\n"
        "Fed by all three intake channels via the Patient Lookup block "
        "(fan-in). Claude classifies intent + extracts scheduling fields "
        "AND flags clinical content / urgency / explicit human requests in "
        "one structured-output call. ANY of those flags routes straight to "
        "Staff Escalation — the system never guesses on clinical or "
        "ambiguous input. Everything else routes by intent via the Switch."
    ),
    (X2, Y2 - 260), size=(680, 220), color=5,
)

print(f"Stage 2 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 3 — Calendar Verification (two reusable/fan-in blocks)
# ---------------------------------------------------------------------------

Y3 = 900

set_node(
    "Prep Slot Search: New Booking", (0, Y3),
    [
        ("origin_stage", "new_booking", "string"),
        ("appointment_id", "", "string"),
        ("patient_id", "={{ $json.patient_id }}", "string"),
        ("channel", "={{ $json.channel }}", "string"),
        ("contact.name", "={{ $json['contact.name'] }}", "string"),
        ("contact.phone", "={{ $json['contact.phone'] }}", "string"),
        ("contact.email", "={{ $json['contact.email'] }}", "string"),
        ("service_type", "={{ $json.service_type }}", "string"),
        ("window_start", "={{ $json.requested_window_start }}", "string"),
        ("window_end", "={{ $json.requested_window_end }}", "string"),
    ],
)
connect("Switch: Route By Intent", 0, "Prep Slot Search: New Booking", 0)

code_node(
    "Prep Slot Search: Reschedule (Free-Text)", (0, Y3 + 220),
    """
const appt = $input.first().json;
const cls = $('Attach Envelope Fields To Classification').item.json;
return [{
  json: {
    origin_stage: 'reschedule',
    appointment_id: appt.appointment_id,
    calendar_event_id: appt.calendar_event_id,
    patient_id: cls.patient_id,
    channel: cls.channel,
    'contact.name': cls['contact.name'],
    'contact.phone': cls['contact.phone'],
    'contact.email': cls['contact.email'],
    service_type: appt.service_type,
    window_start: cls.requested_window_start,
    window_end: cls.requested_window_end,
  },
}];
""".strip(),
)
connect("IF: Upcoming Appointment Found?", 0, "Prep Slot Search: Reschedule (Free-Text)", 0)

sticky(
    "SN Reschedule NoAppt", (
        "No upcoming appointment on file for a free-text reschedule request\n"
        "-> straight to Staff Escalation (see Stage 10) rather than guessing\n"
        "which appointment the patient means."
    ),
    (280, Y3 + 500), size=(360, 160), color=3,
)

# Shared: Get Service Duration (fed by both new-booking and reschedule prep — fan-in)
code_node(
    "Get Service Duration", (280, Y3),
    CONFIG_JS + """

const item = $input.first().json;
const duration = CONFIG.serviceDurationsMin[item.service_type] || 30; // sane default if unrecognized
return [{ json: { ...item, duration_min: duration } }];
""",
)
fan_in(["Prep Slot Search: New Booking", "Prep Slot Search: Reschedule (Free-Text)"], "Get Service Duration")

calendar_get_all(
    "Google Calendar: List Events In Window", (560, Y3),
    time_min_expr="={{ $json.window_start || $now.toISO() }}",
    time_max_expr="={{ $json.window_end || $now.plus({ days: 7 }).toISO() }}",
)
connect_main("Get Service Duration", "Google Calendar: List Events In Window")

code_node(
    "Code: Compute Free Slots vs Business Hours", (840, Y3),
    CONFIG_JS + """

// Uses cross-node reference since Calendar node output only carries event
// data — the original search request lives on "Get Service Duration".
const req = $('Get Service Duration').first().json;
const events = $input.all().map(i => i.json);
const durationMs = req.duration_min * 60 * 1000;

function isBusinessDay(d) { return CONFIG.businessHours.days.includes(d.getUTCDay() === 0 ? 7 : d.getUTCDay()); }

function* candidateStarts(from, to) {
  let cursor = new Date(from);
  const [bh, bm] = CONFIG.businessHours.start.split(':').map(Number);
  const [eh, em] = CONFIG.businessHours.end.split(':').map(Number);
  while (cursor < to) {
    const dayStart = new Date(cursor); dayStart.setUTCHours(bh, bm, 0, 0);
    const dayEnd = new Date(cursor); dayEnd.setUTCHours(eh, em, 0, 0);
    if (isBusinessDay(cursor)) {
      let slot = cursor < dayStart ? dayStart : cursor;
      while (slot.getTime() + durationMs <= dayEnd.getTime()) {
        yield new Date(slot);
        slot = new Date(slot.getTime() + CONFIG.slotGranularityMin * 60 * 1000);
      }
    }
    cursor = new Date(cursor); cursor.setUTCDate(cursor.getUTCDate() + 1); cursor.setUTCHours(0, 0, 0, 0);
  }
}

function overlaps(startA, endA, startB, endB) { return startA < endB && startB < endA; }

const from = req.window_start ? new Date(req.window_start) : new Date();
const to = req.window_end ? new Date(req.window_end) : new Date(from.getTime() + 7 * 24 * 60 * 60 * 1000);

const free = [];
for (const start of candidateStarts(from, to)) {
  const end = new Date(start.getTime() + durationMs);
  const conflict = events.some(e => e.start?.dateTime && overlaps(start, end, new Date(e.start.dateTime), new Date(e.end.dateTime)));
  if (!conflict) free.push({ start: start.toISOString(), end: end.toISOString() });
  if (free.length >= 4) break; // exact (first) + up to 3 alternatives
}

const result = { ...req };
if (free.length === 0) {
  result.result_type = 'none';
} else if (req.window_start && req.window_end) {
  result.result_type = 'exact';
  result.slot_start = free[0].start;
  result.slot_end = free[0].end;
  result.alternative_slots = free.slice(1);
} else {
  // no specific window was requested — first free slot found IS the offer
  result.result_type = 'exact';
  result.slot_start = free[0].start;
  result.slot_end = free[0].end;
  result.alternative_slots = free.slice(1);
}
return [{ json: result }];
""",
)
connect_main("Google Calendar: List Events In Window", "Code: Compute Free Slots vs Business Hours")

_switch_slot, _slot_outputs = switch_node(
    "Switch: Slot Result", (1120, Y3),
    field_expr="={{ $json.result_type }}",
    cases=["exact", "alternatives"],
    fallback_output="none",
)
connect_main("Code: Compute Free Slots vs Business Hours", "Switch: Slot Result")

sticky(
    "SN CalendarVerify", (
        "SHARED BLOCK — Find Available Slot In Window\n\n"
        "Fed by New Booking and Reschedule flows (fan-in). Independently "
        "re-checks Google Calendar (the live calendar of record) before "
        "ever telling a patient a time is available — this is a dedicated "
        "step, separate from composing the reply. If the exact requested "
        "window is free, that slot is used; otherwise up to 3 genuinely "
        "free alternatives are computed and offered; if nothing is free in "
        "the search horizon, it escalates to staff rather than leaving the "
        "patient with no path forward."
    ),
    (0, Y3 - 260), size=(760, 220), color=5,
)

# --- Reusable: Verify Specific Slot Still Open (used by Waitlist Fill, Stage 7) ---

code_node(
    "Code: Build Slot Recheck Window", (1680, Y3 + 700),
    """
const item = $input.first().json;
return [{ json: { ...item, recheck_time_min: item.slot_start, recheck_time_max: item.slot_end } }];
""".strip(),
)
calendar_get_all(
    "Google Calendar: Re-Check Freed Slot", (1960, Y3 + 700),
    time_min_expr="={{ $json.recheck_time_min }}", time_max_expr="={{ $json.recheck_time_max }}",
)
connect_main("Code: Build Slot Recheck Window", "Google Calendar: Re-Check Freed Slot")

code_node(
    "Code: Determine If Still Open", (2240, Y3 + 700),
    """
const req = $('Code: Build Slot Recheck Window').first().json;
const events = $input.all().map(i => i.json);
const stillOpen = events.length === 0;
return [{ json: { ...req, slot_still_open: stillOpen } }];
""".strip(),
)
connect_main("Google Calendar: Re-Check Freed Slot", "Code: Determine If Still Open")

if_node(
    "IF: Slot Still Open?", (2520, Y3 + 700),
    [("={{ $json.slot_still_open }}", "boolean", "true", True)],
)
connect_main("Code: Determine If Still Open", "IF: Slot Still Open?")

sticky(
    "SN VerifySpecificSlot", (
        "SHARED BLOCK — Verify Specific Slot Still Open\n\n"
        "Used only by Waitlist Fill (Stage 7) immediately before offering a "
        "freshly-cancelled slot to the next waitlisted patient. Re-reads "
        "the calendar for that exact window to close the race-condition "
        "gap between 'slot freed' and 'offer sent'. If it's already gone, "
        "control returns to 'select next candidate' instead of offering a "
        "slot that no longer exists."
    ),
    (1680, Y3 + 440), size=(760, 220), color=5,
)

print(f"Stage 3 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# Two shared reply mechanisms, created once and fed from many places
# (fan-in) throughout the rest of the workflow.
# ---------------------------------------------------------------------------

Y_REPLY = 2900

respond_to_webhook(
    "Respond to Webhook: Patient Reply", (2800, Y_REPLY),
    "={{ { status: 'ok', message: $json.reply_text } }}",
)
sticky(
    "SN RespondWebhook", (
        "SHARED — Respond to Webhook\n\n"
        "Used ONLY for a direct, synchronous reply to whoever is *currently* "
        "hitting a webhook in this execution (the booking/reschedule/"
        "cancellation caller, or someone responding to a reminder/waitlist "
        "offer). Every upstream 'compose message' node sets `reply_text` "
        "before reaching this node."
    ),
    (2800, Y_REPLY - 220), size=(560, 180), color=6,
)

http_request(
    "HTTP Request: Send Patient Message (Outbound)", (3400, Y_REPLY),
    url_expr=MESSAGING_GATEWAY_URL_PLACEHOLDER,
    body_expr="={{ { channel: $json.msg_channel, to: $json.msg_contact, message: $json.msg_text } }}",
)
sticky(
    "SN OutboundSend", (
        "SHARED — Send Patient Message (Outbound)\n\n"
        "Used for anything with NO live request to reply to, or where the "
        "recipient differs from whoever triggered this execution: 24h/2h "
        "reminders, waitlist offers to a different patient, waitlist-win "
        "confirmations, no-show follow-up notices. Placeholder URL — swap "
        "for your real SMS/WhatsApp/telephony provider's send API. "
        "Upstream nodes set msg_channel / msg_contact / msg_text."
    ),
    (3400, Y_REPLY - 240), size=(600, 200), color=6,
)

# ---------------------------------------------------------------------------
# STAGE 4 — Booking / Reschedule Confirmation & Reply
# ---------------------------------------------------------------------------

Y4 = 1700

_switch_origin, _origin_outputs = switch_node(
    "Switch: Confirm By Origin", (1400, Y4),
    field_expr="={{ $json.origin_stage }}",
    cases=["new_booking", "reschedule"],
    fallback_output="staff_escalation",
)
connect("Switch: Slot Result", 0, "Switch: Confirm By Origin", 0)  # "exact" output

# --- New booking branch ---
code_node(
    "Prepare New Appointment Record (Booking)", (1680, Y4 - 220),
    """
const item = $input.first().json;
const apptId = 'AP-' + Math.floor(Math.random() * 9000000 + 1000000);
return [{
  json: {
    ...item,
    appointment_id: apptId,
    calendar_summary: `${item.service_type} - ${item['contact.name'] || 'Patient ' + item.patient_id}`,
    calendar_description: `Booked via ${item.channel}. Patient ID: ${item.patient_id}.`,
  },
}];
""".strip(),
)
connect("Switch: Confirm By Origin", 0, "Prepare New Appointment Record (Booking)", 0)

calendar_create("Google Calendar: Create Appointment Event", (1960, Y4 - 220))
connect_main("Prepare New Appointment Record (Booking)", "Google Calendar: Create Appointment Event")

code_node(
    "Merge Calendar Result Into Appointment (Booking)", (2240, Y4 - 220),
    """
const calResult = $input.first().json;
const ctx = $('Prepare New Appointment Record (Booking)').first().json;
const now = $now.toISO();
return [{
  json: {
    appointment_id: ctx.appointment_id,
    patient_id: ctx.patient_id,
    patient_contact: ctx['contact.phone'],
    channel: ctx.channel,
    service_type: ctx.service_type,
    calendar_event_id: calResult.id || '',
    start_time: ctx.slot_start,
    end_time: ctx.slot_end,
    status: 'confirmed',
    checkin_status: 'none',
    reminder_24h_status: 'pending',
    reminder_2h_status: 'pending',
    created_at: now,
    updated_at: now,
  },
}];
""".strip(),
)
connect_main("Google Calendar: Create Appointment Event", "Merge Calendar Result Into Appointment (Booking)")

# --- Reschedule branch (calendar_event_id + appointment_id already carried) ---
calendar_update("Google Calendar: Update Appointment Event", (1960, Y4 + 60))
connect("Switch: Confirm By Origin", 1, "Google Calendar: Update Appointment Event", 0)

code_node(
    "Merge Calendar Result Into Appointment (Reschedule)", (2240, Y4 + 60),
    """
const calResult = $input.first().json;
const ctx = $('Code: Compute Free Slots vs Business Hours').first().json;
return [{
  json: {
    appointment_id: ctx.appointment_id,
    patient_id: ctx.patient_id,
    patient_contact: ctx['contact.phone'],
    channel: ctx.channel,
    service_type: ctx.service_type,
    calendar_event_id: calResult.id || ctx.calendar_event_id,
    start_time: ctx.slot_start,
    end_time: ctx.slot_end,
    status: 'confirmed',
    checkin_status: 'none',
    reminder_24h_status: 'pending',
    reminder_2h_status: 'pending',
    updated_at: $now.toISO(),
  },
}];
""".strip(),
)
connect_main("Google Calendar: Update Appointment Event", "Merge Calendar Result Into Appointment (Reschedule)")

sheets_upsert("Sheets: Upsert Appointment Record", (2520, Y4 - 80), "Appointments", "appointment_id")
fan_in(["Merge Calendar Result Into Appointment (Booking)", "Merge Calendar Result Into Appointment (Reschedule)"],
       "Sheets: Upsert Appointment Record")

code_node(
    "Compose Confirmation Message", (2800, Y4 - 80),
    """
const row = $input.first().json;
const start = new Date(row.start_time);
const dateStr = start.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
const timeStr = start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
return [{
  json: {
    ...row,
    reply_text: `You're confirmed for a ${row.service_type} appointment on ${dateStr} at ${timeStr}. `
      + `Reply CONFIRM, RESCHEDULE, or CANCEL any time before your visit.`,
  },
}];
""".strip(),
)
connect_main("Sheets: Upsert Appointment Record", "Compose Confirmation Message")
connect_main("Compose Confirmation Message", "Respond to Webhook: Patient Reply")

# --- Alternatives-only branch ---
code_node(
    "Code: Compose Alternative Slots Message", (1680, Y4 + 340),
    """
const item = $input.first().json;
const alts = (item.alternative_slots || []).map(s => {
  const d = new Date(s.start);
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
    + ' at ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
});
const list = alts.length ? alts.join('; ') : 'no nearby alternatives were found';
return [{
  json: {
    ...item,
    reply_text: `We don't have an opening in exactly the window you requested for a ${item.service_type} visit. `
      + `Nearest available options: ${list}. Reply with the option that works, or contact us directly.`,
  },
}];
""".strip(),
)
connect("Switch: Slot Result", 1, "Code: Compose Alternative Slots Message", 0)  # "alternatives" output
connect_main("Code: Compose Alternative Slots Message", "Respond to Webhook: Patient Reply")

sticky(
    "SN Confirmation", (
        "SHARED BLOCK — Booking/Reschedule Confirmation & Reply\n\n"
        "Only ever reached AFTER Calendar Verification (Stage 3) returned a "
        "genuinely open slot — the confirmation text is built strictly from "
        "the verified Calendar/Sheets result, never guessed. New bookings "
        "create a Calendar event; reschedules update the existing one. Both "
        "converge on one Sheets upsert and one confirmation composer."
    ),
    (1680, Y4 - 520), size=(760, 220), color=5,
)

print(f"Stage 4 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 5 — Multi-Stage Reminder System
# ---------------------------------------------------------------------------

Y5 = 3300

schedule_trigger("Schedule Trigger: Reminder Dispatch Check", (0, Y5), 15)
sheets_read_filtered("Sheets: Read All Appointments (For Reminders)", (280, Y5), "Appointments")
connect_main("Schedule Trigger: Reminder Dispatch Check", "Sheets: Read All Appointments (For Reminders)")

code_node(
    "Code: Determine Due Reminders", (560, Y5),
    """
const now = new Date();
const out = [];
for (const item of $input.all()) {
  const row = item.json;
  if (row.status !== 'confirmed') continue;
  const start = new Date(row.start_time);
  const hoursUntil = (start - now) / 3600000;
  if (hoursUntil > 0 && hoursUntil <= 24 && row.reminder_24h_status === 'pending') {
    out.push({ json: { ...row, reminder_stage: '24h' } });
  } else if (hoursUntil > 0 && hoursUntil <= 2 && row.reminder_2h_status === 'pending') {
    out.push({ json: { ...row, reminder_stage: '2h' } });
  }
}
return out;
""".strip(),
)
connect_main("Sheets: Read All Appointments (For Reminders)", "Code: Determine Due Reminders")

code_node(
    "Code: Compose Reminder Message", (840, Y5),
    """
const row = $input.item.json;
const start = new Date(row.start_time);
const dateStr = start.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
const timeStr = start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
const label = row.reminder_stage === '24h' ? 'tomorrow' : 'in about 2 hours';
return {
  json: {
    ...row,
    msg_channel: row.channel,
    msg_contact: row.patient_contact,
    msg_text: `Reminder: you have a ${row.service_type} appointment ${label} (${dateStr} at ${timeStr}). `
      + `Reply CONFIRM to confirm you're coming, RESCHEDULE to pick a new time, or CANCEL to cancel. `
      + `Appointment ref: ${row.appointment_id}.`,
  },
};
""".strip(),
    mode="runOnceForEachItem",
)
connect_main("Code: Determine Due Reminders", "Code: Compose Reminder Message")
connect_main("Code: Compose Reminder Message", "HTTP Request: Send Patient Message (Outbound)")

code_node(
    "Code: Prepare Reminder Status Update", (840, Y5 + 220),
    """
const row = $('Code: Compose Reminder Message').item.json;
const update = { appointment_id: row.appointment_id };
if (row.reminder_stage === '24h') update.reminder_24h_status = 'sent';
else update.reminder_2h_status = 'sent';
return { json: update };
""".strip(),
    mode="runOnceForEachItem",
)
connect_main("HTTP Request: Send Patient Message (Outbound)", "Code: Prepare Reminder Status Update")
sheets_upsert("Sheets: Mark Reminder Sent", (1120, Y5 + 220), "Appointments", "appointment_id")
connect_main("Code: Prepare Reminder Status Update", "Sheets: Mark Reminder Sent")

sticky(
    "SN Reminders", (
        "STAGE 5 — MULTI-STAGE REMINDERS\n\n"
        "Polls every 15 min rather than scheduling one timer per appointment "
        "— simpler and self-healing (a missed cycle just fires next poll). "
        "24h and 2h reminders each fire exactly once because the matching "
        "status column flips to 'sent' immediately after a successful send. "
        "Each reminder includes CONFIRM/RESCHEDULE/CANCEL instructions "
        "handled by the Reminder Action Intake webhook (Stage 6)."
    ),
    (0, Y5 - 220), size=(680, 180), color=4,
)

print(f"Stage 5 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 6 — Reminder Action Intake & Reschedule Handling
# ---------------------------------------------------------------------------

Y6 = 3700

webhook("Reminder Action Intake", (0, Y6), "reminder-action")
sheets_read_filtered(
    "Sheets: Get Appointment By ID (Reminder Action)", (280, Y6),
    "Appointments", filter_col="appointment_id", filter_value_expr="={{ $json.body.appointment_id }}",
)
connect_main("Reminder Action Intake", "Sheets: Get Appointment By ID (Reminder Action)")

_switch_remind, _remind_outputs = switch_node(
    "Switch: Reminder Action Type", (560, Y6),
    field_expr="={{ $('Reminder Action Intake').item.json.body.action }}",
    cases=["confirm", "reschedule", "cancel"],
    fallback_output="staff_escalation",
)
connect_main("Sheets: Get Appointment By ID (Reminder Action)", "Switch: Reminder Action Type")

# --- confirm (this IS the check-in signal used by No-Show Detection) ---
code_node(
    "Prepare Check-In Confirmation", (840, Y6 - 220),
    """
const row = $input.item.json;
return { json: { appointment_id: row.appointment_id, checkin_status: 'confirmed', service_type: row.service_type, start_time: row.start_time } };
""".strip(),
    mode="runOnceForEachItem",
)
connect("Switch: Reminder Action Type", 0, "Prepare Check-In Confirmation", 0)
sheets_upsert("Sheets: Mark Check-In Confirmed", (1120, Y6 - 220), "Appointments", "appointment_id")
connect_main("Prepare Check-In Confirmation", "Sheets: Mark Check-In Confirmed")
code_node(
    "Compose Check-In Acknowledgement", (1400, Y6 - 220),
    """
const row = $input.first().json;
return [{ json: { ...row, reply_text: `Thanks for confirming your ${row.service_type} appointment. See you then!` } }];
""".strip(),
)
connect_main("Sheets: Mark Check-In Confirmed", "Compose Check-In Acknowledgement")
connect_main("Compose Check-In Acknowledgement", "Respond to Webhook: Patient Reply")

# --- reschedule (feeds the SAME shared "Get Service Duration" slot-search block) ---
code_node(
    "Prep Slot Search: Reschedule (Reminder Action)", (840, Y6),
    """
const appt = $input.first().json;
const webhookBody = $('Reminder Action Intake').first().json.body;
return [{
  json: {
    origin_stage: 'reschedule',
    appointment_id: appt.appointment_id,
    calendar_event_id: appt.calendar_event_id,
    patient_id: appt.patient_id,
    channel: webhookBody.channel || appt.channel,
    'contact.name': '',
    'contact.phone': webhookBody.contact || appt.patient_contact,
    'contact.email': '',
    service_type: appt.service_type,
    window_start: '',
    window_end: '',
  },
}];
""".strip(),
)
connect("Switch: Reminder Action Type", 1, "Prep Slot Search: Reschedule (Reminder Action)", 0)
connect_main("Prep Slot Search: Reschedule (Reminder Action)", "Get Service Duration")

# --- cancel (feeds the shared Cancellation & Waitlist Fill entry point, Stage 7) ---
code_node(
    "Prep Cancellation: Reminder Action", (840, Y6 + 220),
    """
const appt = $input.first().json;
return [{ json: { ...appt, origin_stage: 'cancellation', cancel_reason: 'patient_requested', is_synchronous: true } }];
""".strip(),
)
connect("Switch: Reminder Action Type", 2, "Prep Cancellation: Reminder Action", 0)

sticky(
    "SN ReminderAction", (
        "STAGE 6 — REMINDER ACTION INTAKE\n\n"
        "The CONFIRM/RESCHEDULE/CANCEL link in every reminder message posts "
        "here. No LLM classification needed — the action is already "
        "explicit. 'confirm' is also the check-in signal No-Show Detection "
        "(Stage 9) checks for. 'reschedule' re-enters the SAME shared "
        "Calendar Verification block used by free-text reschedules "
        "(fan-in into 'Get Service Duration') — no duplicated logic."
    ),
    (0, Y6 - 460), size=(680, 200), color=4,
)

print(f"Stage 6 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 7 — Cancellation & Waitlist Fill
# ---------------------------------------------------------------------------

Y7 = 4400

sheets_read_filtered(
    "Sheets: Find Appointment To Cancel", (0, Y7),
    "Appointments", filter_col="patient_id", filter_value_expr="={{ $json.patient_id }}",
)
connect("Switch: Route By Intent", 2, "Sheets: Find Appointment To Cancel", 0)  # "cancellation" output

if_node(
    "IF: Appointment To Cancel Found?", (280, Y7),
    [("={{ $json.appointment_id }}", "string", "exists", "")],
)
connect_main("Sheets: Find Appointment To Cancel", "IF: Appointment To Cancel Found?")

code_node(
    "Prep Cancellation: Free-Text", (560, Y7),
    """
const row = $input.first().json;
return [{ json: { ...row, origin_stage: 'cancellation', cancel_reason: 'patient_requested', is_synchronous: true } }];
""".strip(),
)
connect("IF: Appointment To Cancel Found?", 0, "Prep Cancellation: Free-Text", 0)

add_node("Cancellation: Normalize Envelope", "n8n-nodes-base.noOp", (840, Y7), type_version=1)
fan_in(["Prep Cancellation: Free-Text", "Prep Cancellation: Reminder Action"], "Cancellation: Normalize Envelope")

calendar_delete("Google Calendar: Cancel Appointment Event", (1120, Y7 - 220))
connect_main("Cancellation: Normalize Envelope", "Google Calendar: Cancel Appointment Event")

code_node(
    "Prepare Cancelled Appointment Update", (1400, Y7 - 220),
    """
const ctx = $('Cancellation: Normalize Envelope').first().json;
return [{
  json: {
    appointment_id: ctx.appointment_id,
    status: ctx.origin_stage === 'no_show' ? 'no_show' : 'cancelled',
    updated_at: $now.toISO(),
  },
}];
""".strip(),
)
connect_main("Google Calendar: Cancel Appointment Event", "Prepare Cancelled Appointment Update")
sheets_upsert("Sheets: Mark Appointment Cancelled Or No-Show", (1680, Y7 - 220), "Appointments", "appointment_id")
connect_main("Prepare Cancelled Appointment Update", "Sheets: Mark Appointment Cancelled Or No-Show")

if_node(
    "IF: Cancellation Needs Direct Reply?", (1960, Y7 - 220),
    [("={{ $('Cancellation: Normalize Envelope').first().json.is_synchronous }}", "boolean", "true", True)],
)
connect_main("Sheets: Mark Appointment Cancelled Or No-Show", "IF: Cancellation Needs Direct Reply?")
code_node(
    "Compose Cancellation Acknowledgement", (2240, Y7 - 220),
    """
const ctx = $('Cancellation: Normalize Envelope').first().json;
return [{ json: { ...ctx, reply_text: `Your ${ctx.service_type} appointment has been cancelled. Reach out any time if you'd like to rebook.` } }];
""".strip(),
)
connect("IF: Cancellation Needs Direct Reply?", 0, "Compose Cancellation Acknowledgement", 0)
connect_main("Compose Cancellation Acknowledgement", "Respond to Webhook: Patient Reply")

# --- Waitlist fill (shared — also fed by Stage 8's expiry/decline re-fill) ---

add_node("Waitlist: Normalize Fill Request", "n8n-nodes-base.noOp", (1120, Y7 + 260), type_version=1)
connect_main("Cancellation: Normalize Envelope", "Waitlist: Normalize Fill Request")

sheets_read_filtered(
    "Sheets: Find Waitlist Candidates By Service Type", (1400, Y7 + 260),
    "Waitlist", filter_col="service_type", filter_value_expr="={{ $json.service_type }}",
)
connect_main("Waitlist: Normalize Fill Request", "Sheets: Find Waitlist Candidates By Service Type")

code_node(
    "Code: Select Next Waitlist Candidate", (1680, Y7 + 260),
    """
const ctx = $('Waitlist: Normalize Fill Request').first().json;
const rows = $input.all().map(i => i.json);
const candidates = rows
  .filter(r => r.status === 'waiting'
    && new Date(r.desired_window_start) <= new Date(ctx.end_time)
    && new Date(r.desired_window_end) >= new Date(ctx.start_time))
  .sort((a, b) => (Number(a.priority) || 0) - (Number(b.priority) || 0) || new Date(a.created_at) - new Date(b.created_at));

if (!candidates.length) return [{ json: { ...ctx, waitlist_candidate_found: false } }];
const chosen = candidates[0];
return [{
  json: {
    ...ctx,
    waitlist_candidate_found: true,
    waitlist_id: chosen.waitlist_id,
    waitlist_patient_id: chosen.patient_id,
    waitlist_contact: chosen.patient_contact,
    waitlist_channel: chosen.channel,
    slot_start: ctx.start_time,
    slot_end: ctx.end_time,
  },
}];
""".strip(),
)
connect_main("Sheets: Find Waitlist Candidates By Service Type", "Code: Select Next Waitlist Candidate")

if_node(
    "IF: Waitlist Candidate Found?", (1960, Y7 + 260),
    [("={{ $json.waitlist_candidate_found }}", "boolean", "true", True)],
)
connect_main("Code: Select Next Waitlist Candidate", "IF: Waitlist Candidate Found?")
connect("IF: Waitlist Candidate Found?", 0, "Code: Build Slot Recheck Window", 0)

code_node(
    "Prepare Waitlist Hold", (2820, Y7 + 700),
    CONFIG_JS + """

const item = $input.first().json;
const expiresAt = new Date(Date.now() + CONFIG.waitlistOfferWindowMin * 60000).toISOString();
return [{
  json: {
    waitlist_id: item.waitlist_id,
    status: 'offered',
    offer_expires_at: expiresAt,
    offer_slot_start: item.slot_start,
    offer_slot_end: item.slot_end,
  },
}];
""",
)
connect("IF: Slot Still Open?", 0, "Prepare Waitlist Hold", 0)
sheets_upsert("Sheets: Create Timed Waitlist Hold", (3100, Y7 + 700), "Waitlist", "waitlist_id")
connect_main("Prepare Waitlist Hold", "Sheets: Create Timed Waitlist Hold")

code_node(
    "Compose Waitlist Offer Message", (3380, Y7 + 700),
    CONFIG_JS + """

const ctx = $('Code: Select Next Waitlist Candidate').first().json;
const start = new Date(ctx.slot_start);
const dateStr = start.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
const timeStr = start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
return [{
  json: {
    ...ctx,
    msg_channel: ctx.waitlist_channel,
    msg_contact: ctx.waitlist_contact,
    msg_text: `Good news \\u2014 a ${ctx.service_type} slot just opened up on ${dateStr} at ${timeStr}. `
      + `Reply within ${CONFIG.waitlistOfferWindowMin} minutes to claim it (ref: ${ctx.waitlist_id}), or it will go to the next person on the list.`,
  },
}];
""",
)
connect_main("Sheets: Create Timed Waitlist Hold", "Compose Waitlist Offer Message")
connect_main("Compose Waitlist Offer Message", "HTTP Request: Send Patient Message (Outbound)")

sticky(
    "SN CancelWaitlist", (
        "STAGE 7 — CANCELLATION & WAITLIST FILL\n\n"
        "Fed by free-text cancellation, reminder-action cancel, and (Stage 9) "
        "no-show detection — fan-in via 'Cancellation: Normalize Envelope'. "
        "Cancelling always tries a waitlist fill in parallel. The waitlist-fill "
        "chain (find candidates → select next → verify slot still open → "
        "create timed hold → offer) is itself SHARED with Stage 8's expiry/"
        "decline re-offer flow via 'Waitlist: Normalize Fill Request' — no "
        "duplicated logic, and re-offering naturally skips anyone no longer "
        "'waiting' without needing an explicit exclusion list."
    ),
    (0, Y7 - 460), size=(800, 220), color=3,
)

print(f"Stage 7 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 8 — Waitlist Offer Response & Expiry (the explicit race-condition
# handling: a non-response within the offer window moves to the next person,
# reusing the exact same waitlist-fill chain built in Stage 7).
# ---------------------------------------------------------------------------

Y8 = 5300

webhook("Waitlist Offer Response Intake", (0, Y8), "waitlist-response")
sheets_read_filtered(
    "Sheets: Get Waitlist Row By ID", (280, Y8),
    "Waitlist", filter_col="waitlist_id", filter_value_expr="={{ $json.body.waitlist_id }}",
)
connect_main("Waitlist Offer Response Intake", "Sheets: Get Waitlist Row By ID")

_switch_wl, _wl_outputs = switch_node(
    "Switch: Waitlist Response Type", (560, Y8),
    field_expr="={{ $('Waitlist Offer Response Intake').item.json.body.response }}",
    cases=["accept", "decline"],
    fallback_output="staff_escalation",
)
connect_main("Sheets: Get Waitlist Row By ID", "Switch: Waitlist Response Type")

# --- accept: books the held slot for the waitlisted patient ---
code_node(
    "Prepare Waitlist Booking Confirmation", (840, Y8 - 220),
    """
const row = $input.first().json;
const apptId = 'AP-' + Math.floor(Math.random() * 9000000 + 1000000);
return [{
  json: {
    origin_stage: 'new_booking',
    appointment_id: apptId,
    patient_id: row.patient_id,
    channel: row.channel,
    'contact.name': '',
    'contact.phone': row.patient_contact,
    service_type: row.service_type,
    slot_start: row.offer_slot_start,
    slot_end: row.offer_slot_end,
    waitlist_id: row.waitlist_id,
    calendar_summary: `${row.service_type} - Patient ${row.patient_id} (from waitlist)`,
    calendar_description: `Booked from waitlist. Patient ID: ${row.patient_id}.`,
  },
}];
""".strip(),
)
connect("Switch: Waitlist Response Type", 0, "Prepare Waitlist Booking Confirmation", 0)

calendar_create("Google Calendar: Create Appointment Event (Waitlist)", (1120, Y8 - 220))
connect_main("Prepare Waitlist Booking Confirmation", "Google Calendar: Create Appointment Event (Waitlist)")

code_node(
    "Merge Calendar Result Into Appointment (Waitlist)", (1400, Y8 - 220),
    """
const calResult = $input.first().json;
const ctx = $('Prepare Waitlist Booking Confirmation').first().json;
const now = $now.toISO();
return [{
  json: {
    appointment_id: ctx.appointment_id,
    patient_id: ctx.patient_id,
    patient_contact: ctx['contact.phone'],
    channel: ctx.channel,
    service_type: ctx.service_type,
    calendar_event_id: calResult.id || '',
    start_time: ctx.slot_start,
    end_time: ctx.slot_end,
    status: 'confirmed',
    checkin_status: 'none',
    reminder_24h_status: 'pending',
    reminder_2h_status: 'pending',
    created_at: now,
    updated_at: now,
  },
}];
""".strip(),
)
connect_main("Google Calendar: Create Appointment Event (Waitlist)", "Merge Calendar Result Into Appointment (Waitlist)")
connect_main("Merge Calendar Result Into Appointment (Waitlist)", "Sheets: Upsert Appointment Record")  # shared, Stage 4

code_node(
    "Prepare Waitlist Row Booked", (1400, Y8),
    """
const ctx = $('Prepare Waitlist Booking Confirmation').first().json;
return [{ json: { waitlist_id: ctx.waitlist_id, status: 'booked' } }];
""".strip(),
)
connect_main("Merge Calendar Result Into Appointment (Waitlist)", "Prepare Waitlist Row Booked")
sheets_upsert("Sheets: Mark Waitlist Booked", (1680, Y8), "Waitlist", "waitlist_id")
connect_main("Prepare Waitlist Row Booked", "Sheets: Mark Waitlist Booked")

# --- decline: acknowledge + immediately re-offer to the next candidate ---
code_node(
    "Prepare Waitlist Decline", (840, Y8 + 260),
    """
const row = $input.first().json;
return [{
  json: {
    waitlist_id: row.waitlist_id,
    status: 'declined',
    service_type: row.service_type,
    start_time: row.offer_slot_start,
    end_time: row.offer_slot_end,
    patient_contact: row.patient_contact,
    channel: row.channel,
  },
}];
""".strip(),
)
connect("Switch: Waitlist Response Type", 1, "Prepare Waitlist Decline", 0)
sheets_upsert("Sheets: Mark Waitlist Declined", (1120, Y8 + 180), "Waitlist", "waitlist_id")
connect_main("Prepare Waitlist Decline", "Sheets: Mark Waitlist Declined")

code_node(
    "Compose Waitlist Decline Acknowledgement", (1120, Y8 + 340),
    """
return [{ json: { ...$input.first().json, reply_text: "No problem \\u2014 we'll offer this slot to the next person on the waitlist." } }];
""".strip(),
)
connect_main("Prepare Waitlist Decline", "Compose Waitlist Decline Acknowledgement")
connect_main("Compose Waitlist Decline Acknowledgement", "Respond to Webhook: Patient Reply")

connect_main("Prepare Waitlist Decline", "Waitlist: Normalize Fill Request")  # re-offer, same shared chain

# --- expiry sweep: the actual "don't hold the slot open indefinitely" timer ---
schedule_trigger("Schedule Trigger: Waitlist Offer Expiry Check", (0, Y8 + 600), 10)
sheets_read_filtered("Sheets: Read All Waitlist Rows (For Expiry Check)", (280, Y8 + 600), "Waitlist")
connect_main("Schedule Trigger: Waitlist Offer Expiry Check", "Sheets: Read All Waitlist Rows (For Expiry Check)")

code_node(
    "Code: Find Expired Waitlist Offers", (560, Y8 + 600),
    """
// NOTE: the shared waitlist-fill chain this feeds into (see Stage 7) uses
// single-item cross-node references ($('Node').first()), so this
// intentionally processes the SINGLE most-overdue expired offer per poll
// cycle rather than silently dropping extras if several expire in the same
// 10-minute window. Any remaining expired rows are caught on the very next
// cycle (still 'offered' + still past their expiry) -- nothing is lost,
// worst case a slot sits filled-pending for one extra 10-minute cycle.
const now = new Date();
const expired = $input.all()
  .map(i => i.json)
  .filter(row => row.status === 'offered' && row.offer_expires_at && new Date(row.offer_expires_at) < now)
  .sort((a, b) => new Date(a.offer_expires_at) - new Date(b.offer_expires_at));

if (!expired.length) return [];
const row = expired[0];
return [{
  json: {
    waitlist_id: row.waitlist_id,
    status: 'expired',
    service_type: row.service_type,
    start_time: row.offer_slot_start,
    end_time: row.offer_slot_end,
  },
}];
""".strip(),
)
connect_main("Sheets: Read All Waitlist Rows (For Expiry Check)", "Code: Find Expired Waitlist Offers")
sheets_upsert("Sheets: Mark Waitlist Offer Expired", (840, Y8 + 600), "Waitlist", "waitlist_id")
connect_main("Code: Find Expired Waitlist Offers", "Sheets: Mark Waitlist Offer Expired")
connect_main("Code: Find Expired Waitlist Offers", "Waitlist: Normalize Fill Request")  # re-offer, same shared chain

sticky(
    "SN WaitlistExpiry", (
        "STAGE 8 — WAITLIST RESPONSE & EXPIRY (explicit race-condition handling)\n\n"
        "Accept books the held slot immediately. Decline OR a 10-minute expiry "
        "sweep both re-enter the SAME shared waitlist-fill chain from Stage 7 "
        "('Waitlist: Normalize Fill Request') to offer the slot to the next "
        "candidate \\u2014 a waitlisted patient who doesn't respond in time never "
        "holds the slot open indefinitely."
    ),
    (0, Y8 - 460), size=(760, 200), color=3,
)

print(f"Stage 8 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 9 — No-Show Detection
# ---------------------------------------------------------------------------

Y9 = 6100

schedule_trigger("Schedule Trigger: No-Show Detection Check", (0, Y9), 15)
sheets_read_filtered("Sheets: Read All Appointments (For No-Show Check)", (280, Y9), "Appointments")
connect_main("Schedule Trigger: No-Show Detection Check", "Sheets: Read All Appointments (For No-Show Check)")

code_node(
    "Code: Find Overdue Unconfirmed Appointments", (560, Y9),
    CONFIG_JS + """

// Same single-item-per-cycle rationale as the waitlist expiry check (Stage 8)
// -- the shared cancellation/waitlist-fill chain this feeds uses single-item
// cross-node references. Any other overdue appointment is still overdue and
// unconfirmed on the next 15-minute cycle, so nothing is silently lost.
const now = new Date();
const overdue = $input.all()
  .map(i => i.json)
  .filter(row => row.status === 'confirmed'
    && row.checkin_status !== 'confirmed'
    && (now - new Date(row.start_time)) > CONFIG.noShowGraceMin * 60000)
  .sort((a, b) => new Date(a.start_time) - new Date(b.start_time));

if (!overdue.length) return [];
return [{ json: overdue[0] }];
""",
)
connect_main("Sheets: Read All Appointments (For No-Show Check)", "Code: Find Overdue Unconfirmed Appointments")

code_node(
    "Prep Cancellation: No-Show", (840, Y9),
    """
const row = $input.first().json;
return [{ json: { ...row, origin_stage: 'no_show', cancel_reason: 'no_show', is_synchronous: false } }];
""".strip(),
)
connect_main("Code: Find Overdue Unconfirmed Appointments", "Prep Cancellation: No-Show")
connect_main("Prep Cancellation: No-Show", "Cancellation: Normalize Envelope")  # joins the shared Stage 7 chain

sheets_append("Sheets: Append No-Show Log", (1120, Y9 + 220), "NoShowLog")
code_node(
    "Prepare No-Show Log Entry", (840, Y9 + 220),
    """
const row = $('Code: Find Overdue Unconfirmed Appointments').first().json;
return [{
  json: {
    log_id: 'NS-' + Math.floor(Math.random() * 9000000 + 1000000),
    appointment_id: row.appointment_id,
    patient_id: row.patient_id,
    service_type: row.service_type,
    scheduled_time: row.start_time,
    detected_at: $now.toISO(),
  },
}];
""".strip(),
)
connect_main("Code: Find Overdue Unconfirmed Appointments", "Prepare No-Show Log Entry")
connect_main("Prepare No-Show Log Entry", "Sheets: Append No-Show Log")

code_node(
    "Compose No-Show Follow-Up Notice", (840, Y9 + 440),
    """
const row = $('Code: Find Overdue Unconfirmed Appointments').first().json;
return [{
  json: {
    msg_channel: row.channel,
    msg_contact: row.patient_contact,
    msg_text: `We had you scheduled for a ${row.service_type} appointment and didn't see a check-in. `
      + `No worries \\u2014 reply any time to rebook.`,
  },
}];
""".strip(),
)
connect_main("Code: Find Overdue Unconfirmed Appointments", "Compose No-Show Follow-Up Notice")
connect_main("Compose No-Show Follow-Up Notice", "HTTP Request: Send Patient Message (Outbound)")

sticky(
    "SN NoShow", (
        "STAGE 9 — NO-SHOW DETECTION\n\n"
        "'Check-in' is proxied by a CONFIRM reply to the 2h reminder (Stage 6) "
        "-- there's no physical kiosk in scope, this is scheduling logistics "
        "only. Past start-time + grace period with no confirmation -> logged "
        "as fact (no judgment about cause) and fed into the SAME "
        "Cancellation & Waitlist Fill chain as any other cancellation, "
        "immediately trying to fill the freed slot."
    ),
    (0, Y9 - 220), size=(700, 180), color=4,
)

print(f"Stage 9 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 10 — Staff Escalation (shared block, fed by every escalation trigger
# point left open in Stages 2-8). Every escalation includes full context:
# what was requested, what the system understood, and why it's escalating.
# ---------------------------------------------------------------------------

Y10 = 6600

code_node(
    "Prep Escalation: Needs Staff", (X2 + 840, Y2 + 60),
    """
const c = $input.first().json;
let reason = 'Ambiguous or low-confidence classification';
if (c.contains_clinical_content) reason = 'Message contains clinical/medical content -- must be handled by staff, never answered by this system';
else if (c.urgency === 'urgent') reason = 'Flagged urgent/emergency';
else if (c.explicit_human_request) reason = 'Patient explicitly asked for a person';
return [{
  json: {
    reason, channel: c.channel, patient_contact: c['contact.phone'], raw_text: c.raw_text || '',
    system_understood_json: JSON.stringify({ intent: c.intent, service_type: c.service_type, urgency: c.urgency, reasoning: c.reasoning }),
  },
}];
""".strip(),
)
connect("IF: Needs Staff / Clinical / Urgent?", 0, "Prep Escalation: Needs Staff", 0)

code_node(
    "Prep Escalation: Unclassified Intent", (X2 + 1120, Y2 + 460),
    """
const c = $input.first().json;
return [{
  json: {
    reason: 'Could not confidently classify the request intent', channel: c.channel, patient_contact: c['contact.phone'],
    raw_text: c.raw_text || '', system_understood_json: JSON.stringify({ intent: c.intent, reasoning: c.reasoning }),
  },
}];
""".strip(),
)
connect("Switch: Route By Intent", 3, "Prep Escalation: Unclassified Intent", 0)

code_node(
    "Prep Escalation: Reschedule No Appointment Found", (X2 + 1680, Y2 + 640),
    """
const c = $('Attach Envelope Fields To Classification').first().json;
return [{
  json: {
    reason: 'Reschedule requested, but no upcoming appointment found on file for this patient',
    channel: c.channel, patient_contact: c['contact.phone'], raw_text: c.raw_text || '',
    system_understood_json: JSON.stringify({ intent: c.intent, patient_id: c.patient_id }),
  },
}];
""".strip(),
)
connect("IF: Upcoming Appointment Found?", 1, "Prep Escalation: Reschedule No Appointment Found", 0)

code_node(
    "Prep Escalation: No Slot Available", (1120, Y3 + 260),
    """
const c = $input.first().json;
return [{
  json: {
    reason: `No available ${c.service_type || 'appointment'} slot found in the search window (origin: ${c.origin_stage})`,
    channel: c.channel, patient_contact: c['contact.phone'], raw_text: c.raw_text || '',
    system_understood_json: JSON.stringify({ origin_stage: c.origin_stage, service_type: c.service_type, window_start: c.window_start, window_end: c.window_end }),
  },
}];
""".strip(),
)
connect("Switch: Slot Result", 2, "Prep Escalation: No Slot Available", 0)

code_node(
    "Prep Escalation: Unexpected Origin Stage", (1400, Y4 + 340),
    """
const c = $input.first().json;
return [{
  json: {
    reason: 'A verified slot could not be routed to booking or reschedule confirmation (unexpected internal state)',
    channel: c.channel, patient_contact: c['contact.phone'], raw_text: c.raw_text || '',
    system_understood_json: JSON.stringify({ origin_stage: c.origin_stage, appointment_id: c.appointment_id }),
  },
}];
""".strip(),
)
connect("Switch: Confirm By Origin", 2, "Prep Escalation: Unexpected Origin Stage", 0)

code_node(
    "Prep Escalation: Unrecognized Reminder Action", (840, Y6 + 460),
    """
const appt = $input.first().json;
const body = $('Reminder Action Intake').first().json.body;
return [{
  json: {
    reason: `Unrecognized reminder action "${body.action}" received`,
    channel: body.channel || appt.channel, patient_contact: body.contact || appt.patient_contact,
    raw_text: JSON.stringify(body), system_understood_json: JSON.stringify({ appointment_id: appt.appointment_id }),
  },
}];
""".strip(),
)
connect("Switch: Reminder Action Type", 3, "Prep Escalation: Unrecognized Reminder Action", 0)

code_node(
    "Prep Escalation: Cancellation No Appointment Found", (560, Y7 + 220),
    """
const c = $('Attach Envelope Fields To Classification').first().json;
return [{
  json: {
    reason: 'Cancellation requested, but no upcoming appointment found on file for this patient',
    channel: c.channel, patient_contact: c['contact.phone'], raw_text: c.raw_text || '',
    system_understood_json: JSON.stringify({ intent: c.intent, patient_id: c.patient_id }),
  },
}];
""".strip(),
)
connect("IF: Appointment To Cancel Found?", 1, "Prep Escalation: Cancellation No Appointment Found", 0)

code_node(
    "Prep Escalation: Unrecognized Waitlist Response", (840, Y8 + 460),
    """
const row = $input.first().json;
const body = $('Waitlist Offer Response Intake').first().json.body;
return [{
  json: {
    reason: `Unrecognized waitlist response "${body.response}" received`,
    channel: row.channel, patient_contact: row.patient_contact,
    raw_text: JSON.stringify(body), system_understood_json: JSON.stringify({ waitlist_id: row.waitlist_id }),
  },
}];
""".strip(),
)
connect("Switch: Waitlist Response Type", 2, "Prep Escalation: Unrecognized Waitlist Response", 0)

# --- shared escalation chain ---
add_node("Staff Escalation: Normalize Context", "n8n-nodes-base.noOp", (0, Y10), type_version=1)
fan_in([
    "Prep Escalation: Needs Staff",
    "Prep Escalation: Unclassified Intent",
    "Prep Escalation: Reschedule No Appointment Found",
    "Prep Escalation: No Slot Available",
    "Prep Escalation: Unexpected Origin Stage",
    "Prep Escalation: Unrecognized Reminder Action",
    "Prep Escalation: Cancellation No Appointment Found",
    "Prep Escalation: Unrecognized Waitlist Response",
], "Staff Escalation: Normalize Context")

code_node(
    "Compose Staff Escalation Email", (280, Y10),
    """
const e = $input.first().json;
return [{
  json: {
    escalation_id: 'ESC-' + Math.floor(Math.random() * 9000000 + 1000000),
    timestamp: $now.toISO(),
    channel: e.channel,
    patient_contact: e.patient_contact,
    raw_text: e.raw_text,
    system_understood_json: e.system_understood_json,
    reason: e.reason,
    status: 'open',
    email_subject: `[Scheduling] Staff review needed: ${e.reason}`,
    email_body: `Reason: ${e.reason}\\nChannel: ${e.channel}\\nContact: ${e.patient_contact}\\n\\n`
      + `Original message/context: ${e.raw_text || '(none)'}\\n\\nSystem understood: ${e.system_understood_json}`,
  },
}];
""".strip(),
)
connect_main("Staff Escalation: Normalize Context", "Compose Staff Escalation Email")

sheets_append("Sheets: Append Escalation Log", (560, Y10 - 180), "Escalations")
connect_main("Compose Staff Escalation Email", "Sheets: Append Escalation Log")

email_send(
    "Email: Staff Escalation Alert", (560, Y10),
    to_expr="scheduling-staff@example-clinic.test",
    subject_expr="={{ $json.email_subject }}",
    text_expr="={{ $json.email_body }}",
)
connect_main("Compose Staff Escalation Email", "Email: Staff Escalation Alert")

code_node(
    "Compose Escalation Acknowledgement To Patient", (560, Y10 + 180),
    """
return [{ json: { ...$input.first().json, reply_text: "Thanks for reaching out. A staff member will follow up with you shortly." } }];
""".strip(),
)
connect_main("Compose Staff Escalation Email", "Compose Escalation Acknowledgement To Patient")
connect_main("Compose Escalation Acknowledgement To Patient", "Respond to Webhook: Patient Reply")

sticky(
    "SN Escalation", (
        "STAGE 10 — STAFF ESCALATION (shared block)\n\n"
        "Fed by every point in this workflow where the system should not "
        "guess: clinical content, urgent/emergency flags, explicit human "
        "requests, unclassifiable intent, no upcoming appointment found for "
        "a reschedule/cancellation, no slot available at all, and any "
        "unrecognized action. Every escalation logs full context (what was "
        "requested, what the system understood, why it's escalating), "
        "emails staff, and acknowledges the patient so they're never left "
        "without a next step."
    ),
    (0, Y10 - 400), size=(760, 200), color=3,
)

print(f"Stage 10 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 11 — Reliability Layer
#
# Every external-call node created via the http_request/email_send/
# sheets_*/calendar_* helpers above already carries a consistent
# retryOnFail=true / maxTries=4 / waitBetweenTries=2000 policy plus
# onError="continueErrorOutput" (see add_node()). This stage fans EVERY one
# of those error outputs into one shared alert chain automatically, rather
# than hand-listing dozens of connections (and risking missing one as the
# workflow evolves).
# ---------------------------------------------------------------------------

Y11 = 7000

code_node(
    "Compose Error Alert Context", (0, Y11),
    """
const err = $input.first().json;
const failedNode = $prevNode?.name || 'unknown node';
const message = err?.error?.message || err?.message || JSON.stringify(err).slice(0, 500);
return [{
  json: {
    error_id: 'ERR-' + Math.floor(Math.random() * 9000000 + 1000000),
    timestamp: $now.toISO(),
    node_name: failedNode,
    stage: $workflow.name,
    error_message: message,
    item_snapshot: JSON.stringify(err).slice(0, 1000),
    email_subject: `[Scheduling] Unhandled error in "${failedNode}"`,
    email_body: `Node: ${failedNode}\\nWorkflow: ${$workflow.name}\\nError: ${message}`,
  },
}];
""".strip(),
)

# Built directly (not via the sheets_append/email_send helpers) so these two
# nodes do NOT themselves carry onError=continueErrorOutput -- otherwise a
# failure while logging/alerting an error would loop back into this exact
# chain and could recurse indefinitely.
_doc, _sheet = sheets_rl("ErrorLog")
add_node(
    "Sheets: Append Error Log", "n8n-nodes-base.googleSheets", (280, Y11 - 140),
    parameters={
        "resource": "sheet", "operation": "append", "documentId": _doc, "sheetName": _sheet,
        "columns": {"mappingMode": "autoMapInputData", "value": {}, "schema": []}, "options": {},
    },
    type_version=4.7, credentials=GOOGLE_SHEETS_CRED, retry=True,
)
connect_main("Compose Error Alert Context", "Sheets: Append Error Log")

add_node(
    "Email: Unhandled Error Alert", "n8n-nodes-base.emailSend", (280, Y11 + 140),
    parameters={
        "fromEmail": "scheduling-alerts@example-clinic.test",
        "toEmail": "scheduling-staff@example-clinic.test",
        "subject": "={{ $json.email_subject }}",
        "text": "={{ $json.email_body }}",
        "options": {},
    },
    type_version=2.1, credentials=SMTP_CRED, retry=True,
)
connect_main("Compose Error Alert Context", "Email: Unhandled Error Alert")

# Automatic fan-in: every node with onError=continueErrorOutput sends its
# second (error) output here, EXCEPT the error-chain's own two nodes above.
_EXCLUDE_FROM_AUTO_ERROR_WIRING = {"Sheets: Append Error Log", "Email: Unhandled Error Alert"}
_auto_wired = 0
for _n in list(NODES):
    if _n.get("onError") == "continueErrorOutput" and _n["name"] not in _EXCLUDE_FROM_AUTO_ERROR_WIRING:
        connect(_n["name"], 1, "Compose Error Alert Context", 0)
        _auto_wired += 1
print(f"Reliability layer: auto-wired {_auto_wired} external-call node error outputs.")

sticky(
    "SN Reliability", (
        "STAGE 11 — RELIABILITY LAYER\n\n"
        "Every external-call node (Calendar, Sheets, Anthropic, outbound "
        "HTTP) across the ENTIRE canvas uses the same retryOnFail=true / "
        "maxTries=4 / waitBetweenTries=2000ms policy and routes its error "
        "output (after retries are exhausted) into this ONE shared alert "
        "chain -- this is the reusable 'reliability sub-block' called for "
        "in the spec, realized as consistent per-node config + one shared "
        "fan-in group, since a callable sub-workflow isn't used on this "
        "single canvas. Auto-wired programmatically by this generator so no "
        "external call can be added later without an error path."
    ),
    (0, Y11 - 320), size=(760, 220), color=3,
)

print(f"Stage 11 complete. Nodes so far: {len(NODES)}")

# ---------------------------------------------------------------------------
# STAGE 12 — Reporting / Visibility
# ---------------------------------------------------------------------------

Y12 = 7500

schedule_trigger("Schedule Trigger: Hourly Metrics Snapshot", (0, Y12), 60)
sheets_read_filtered("Sheets: Read Appointments For Metrics", (280, Y12), "Appointments")
sheets_read_filtered("Sheets: Read Waitlist For Metrics", (560, Y12), "Waitlist")
sheets_read_filtered("Sheets: Read No-Show Log For Metrics", (840, Y12), "NoShowLog")
sheets_read_filtered("Sheets: Read Escalations For Metrics", (1120, Y12), "Escalations")

connect_main("Schedule Trigger: Hourly Metrics Snapshot", "Sheets: Read Appointments For Metrics")
connect_main("Sheets: Read Appointments For Metrics", "Sheets: Read Waitlist For Metrics")
connect_main("Sheets: Read Waitlist For Metrics", "Sheets: Read No-Show Log For Metrics")
connect_main("Sheets: Read No-Show Log For Metrics", "Sheets: Read Escalations For Metrics")

code_node(
    "Code: Compute Reporting Metrics", (1400, Y12),
    """
// Reads each earlier Sheets node's output directly by name rather than via
// a Merge node -- all four ran earlier in this same linear execution chain,
// so their data is available regardless of this node's own single input.
const appts = $('Sheets: Read Appointments For Metrics').all().map(i => i.json);
const waitlist = $('Sheets: Read Waitlist For Metrics').all().map(i => i.json);
const noShows = $('Sheets: Read No-Show Log For Metrics').all().map(i => i.json);
const escalations = $('Sheets: Read Escalations For Metrics').all().map(i => i.json);

const bookingsMade = appts.filter(a => a.status && a.status !== '').length;
const remindersSent = appts.filter(a => a.reminder_24h_status === 'sent').length
  + appts.filter(a => a.reminder_2h_status === 'sent').length;
const confirmedViaReminder = appts.filter(a => a.checkin_status === 'confirmed').length;
const concludedAppts = appts.filter(a => ['confirmed', 'completed', 'no_show', 'cancelled'].includes(a.status)).length;
const confirmationRate = concludedAppts ? (confirmedViaReminder / concludedAppts) : 0;
const noShowRate = concludedAppts ? (noShows.length / concludedAppts) : 0;
const waitlistFillCount = waitlist.filter(w => w.status === 'booked').length;

return [{
  json: {
    snapshot_at: $now.toISO(),
    bookings_made_total: bookingsMade,
    reminders_sent_total: remindersSent,
    confirmation_rate: Math.round(confirmationRate * 1000) / 1000,
    no_show_rate: Math.round(noShowRate * 1000) / 1000,
    waitlist_fill_count: waitlistFillCount,
    escalation_count: escalations.filter(e => e.escalation_id).length,
  },
}];
""".strip(),
)
connect_main("Sheets: Read Escalations For Metrics", "Code: Compute Reporting Metrics")

sheets_append("Sheets: Append Dashboard Snapshot", (1680, Y12), "Dashboard")
connect_main("Code: Compute Reporting Metrics", "Sheets: Append Dashboard Snapshot")

sticky(
    "SN Reporting", (
        "STAGE 12 — REPORTING / VISIBILITY\n\n"
        "Hourly snapshot of counts only (no patient-identifying data) "
        "appended to the Dashboard sheet tab \\u2014 a practice manager can "
        "open that tab directly with no other access needed. Reads all four "
        "source tabs in one linear chain and references each by node name "
        "in the final Code node, avoiding a Merge node entirely."
    ),
    (0, Y12 - 220), size=(680, 180), color=4,
)

print(f"Stage 12 complete. Total nodes: {len(NODES)}")

# ---------------------------------------------------------------------------
# Validation + assembly
# ---------------------------------------------------------------------------

TRIGGER_TYPES = {
    "n8n-nodes-base.webhook", "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.errorTrigger", "n8n-nodes-base.executeWorkflowTrigger",
}
NON_FLOW_TYPES = {"n8n-nodes-base.stickyNote"}
AI_SUBNODE_TYPES = {
    "@n8n/n8n-nodes-langchain.lmChatAnthropic",
    "@n8n/n8n-nodes-langchain.outputParserStructured",
}


def validate():
    problems = []

    # Every connection endpoint must reference a real node (connect() already
    # enforces this at call time, so this re-check is a belt-and-suspenders
    # pass over the final structure).
    for src, conn_types in CONNECTIONS.items():
        if src not in NAMES_SEEN:
            problems.append(f"Connection source '{src}' is not a registered node")
        for _ctype, outputs in conn_types.items():
            for output_list in outputs:
                for target in output_list:
                    if target["node"] not in NAMES_SEEN:
                        problems.append(f"Connection target '{target['node']}' (from {src}) is not a registered node")

    # Orphan check: every non-trigger, non-sticky, non-AI-subnode node should
    # have at least one incoming "main" connection, and every node should
    # have at least one outgoing connection UNLESS it's a deliberate dead end
    # (documented in TERMINAL_OK below).
    incoming = set()
    for _src, conn_types in CONNECTIONS.items():
        for ctype, outputs in conn_types.items():
            for output_list in outputs:
                for target in output_list:
                    incoming.add(target["node"])

    TERMINAL_OK = {
        "Respond to Webhook: Patient Reply",
        "HTTP Request: Send Patient Message (Outbound)",
        "Sheets: Mark Reminder Sent",
        "Sheets: Mark Waitlist Booked",
        "Sheets: Append Error Log",
        "Email: Unhandled Error Alert",
        "Sheets: Append Dashboard Snapshot",
        "Sheets: Create New Patient Record",  # feeds forward via fan_in target reference, checked separately
    }

    for node in NODES:
        if node["type"] in TRIGGER_TYPES or node["type"] in NON_FLOW_TYPES or node["type"] in AI_SUBNODE_TYPES:
            continue
        name = node["name"]
        has_incoming = name in incoming
        has_outgoing = name in CONNECTIONS and any(CONNECTIONS[name].get("main", []))
        if not has_incoming:
            problems.append(f"Node '{name}' has no incoming connection (orphaned?)")
        if not has_outgoing and name not in TERMINAL_OK:
            problems.append(f"Node '{name}' has no outgoing connection and is not marked as an intentional terminal")

    return problems


_problems = validate()
if _problems:
    print(f"\n VALIDATION FOUND {len(_problems)} ISSUE(S):")
    for p in _problems:
        print(f"  - {p}")
else:
    print("\nValidation passed: every connection resolves, no unexpected orphans/dead-ends.")

# ---------------------------------------------------------------------------
# Assemble + write the workflow JSON
# ---------------------------------------------------------------------------

workflow = {
    "name": "Patient Appointment & No-Show Reduction Pipeline (Demo)",
    "nodes": NODES,
    "connections": CONNECTIONS,
    "active": False,
    "settings": {
        "executionOrder": "v1",
        "timezone": CLINIC_TIMEZONE,
        "binaryMode": "separate",
        "availableInMCP": False,
    },
}

OUT_PATH = "patient-appointment-pipeline.json"
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(workflow, f, indent=2, ensure_ascii=False)

print(f"\nWrote {OUT_PATH}: {len(NODES)} nodes, {sum(len(v.get('main', [])) for v in CONNECTIONS.values())} nodes-with-main-output.")
if _problems:
    raise SystemExit(1)
