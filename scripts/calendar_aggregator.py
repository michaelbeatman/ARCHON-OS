"""
calendar_aggregator.py
======================
HTTP micro-server (port 8421) that merges Google Calendar and Outlook/Exchange
events into a unified JSON format consumed by the Next.js API route
GET /api/calendar/events.

Start:
    python scripts/calendar_aggregator.py

Environment variables (put in .env or set before starting):
    GOOGLE_CREDENTIALS_FILE  Path to your Google service-account JSON or
                             OAuth2 credentials file. Get it from:
                             https://console.cloud.google.com/apis/credentials
                             (OAuth 2.0 Desktop App → download JSON)

    GOOGLE_CALENDAR_ID       Calendar ID, e.g. "primary" or
                             "user@gmail.com". Defaults to "primary".

    OUTLOOK_TENANT_ID        Azure AD tenant ID for Microsoft Graph.
    OUTLOOK_CLIENT_ID        Azure AD app client ID.
    OUTLOOK_CLIENT_SECRET    Azure AD app client secret.
    OUTLOOK_USER_EMAIL       The mailbox to read (e.g. user@company.com).
                             Uses app-level calendar.read permission.
                             (Alternative: set OUTLOOK_ICS_URL to an ICS feed)

    OUTLOOK_ICS_URL          Optional: direct ICS/webcal feed URL from Outlook.
                             Simpler than Graph API for read-only access.

    LOOK_AHEAD_DAYS          How many days ahead to fetch (default: 30).
    LOOK_BACK_DAYS           How many days back to fetch (default: 7).
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import List, Dict, Any

# Load .env file manually if it exists
try:
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PORT = 8421
LOOK_AHEAD = int(os.getenv("LOOK_AHEAD_DAYS", "30"))
LOOK_BACK = int(os.getenv("LOOK_BACK_DAYS", "7"))


# ─── Unified event schema ──────────────────────────────────────────────────────

def make_event(
    event_id: str,
    title: str,
    start: str,
    end: str,
    source: str,
    location: str = "",
    attendees: list = None,
    description: str = "",
) -> Dict[str, Any]:
    return {
        "id": event_id or str(uuid.uuid4()),
        "title": title or "(Kein Titel)",
        "start": start,
        "end": end,
        "source": source,          # "google" | "outlook"
        "location": location or "",
        "attendees": attendees or [],
        "description": description or "",
    }


def iso_now_range():
    now = datetime.now(timezone.utc)
    t_min = (now - timedelta(days=LOOK_BACK)).isoformat()
    t_max = (now + timedelta(days=LOOK_AHEAD)).isoformat()
    return t_min, t_max


# ─── Google Calendar ───────────────────────────────────────────────────────────

def get_google_credentials() -> Any:
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
    if not creds_file or not os.path.exists(creds_file):
        log.warning("GOOGLE_CREDENTIALS_FILE not set or missing.")
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except ImportError:
        log.warning("google-auth-oauthlib or google-auth not installed.")
        return None

    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    TOKEN_FILE = "google_token.json"
    creds = None

    if os.path.exists(TOKEN_FILE):
        try:
            # Read token first to check its scopes
            with open(TOKEN_FILE, "r") as f:
                token_data = json.load(f)
            token_scopes = token_data.get("scopes", [])
            # If the stored scopes do not cover what we require (full calendar), force re-auth
            if not all(s in token_scopes for s in SCOPES):
                log.warning("Stored token lacks required scopes. Forcing re-authorization.")
                creds = None
            else:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            log.warning("Error reading credentials file: %s", e)
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                log.error("Failed to refresh Google token, forcing fresh login: %s", e)
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
                    creds = flow.run_local_server(port=0)
                except Exception as ex:
                    log.error("Google login flow failed: %s", ex)
                    return None
        else:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                log.error("Google login flow failed: %s", e)
                return None
        
        if creds:
            try:
                with open(TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
            except Exception as e:
                log.error("Could not write token file: %s", e)

    return creds


def fetch_google_events() -> List[Dict[str, Any]]:
    """
    Fetches events via google-auth + googleapiclient.
    """
    try:
        from googleapiclient.discovery import build
        creds = get_google_credentials()
        if not creds:
            return []

        cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
        service = build("calendar", "v3", credentials=creds)
        t_min, t_max = iso_now_range()

        result = service.events().list(
            calendarId=cal_id,
            timeMin=t_min,
            timeMax=t_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        ).execute()

        events = []
        for item in result.get("items", []):
            start_raw = item.get("start", {})
            end_raw = item.get("end", {})
            start = start_raw.get("dateTime") or (start_raw.get("date", "") + "T00:00:00Z")
            end   = end_raw.get("dateTime")   or (end_raw.get("date", "") + "T00:00:00Z")
            attendees = [a.get("email", "") for a in item.get("attendees", [])]
            events.append(make_event(
                event_id=item.get("id", ""),
                title=item.get("summary", ""),
                start=start,
                end=end,
                source="google",
                location=item.get("location", ""),
                attendees=attendees,
                description=item.get("description", ""),
            ))

        log.info("Google Calendar: fetched %d events.", len(events))
        return events

    except ImportError:
        log.warning("google-api-python-client not installed. Run: pip install google-api-python-client")
        return []
    except Exception as e:
        log.error("Google Calendar error: %s", e)
        return []


def create_google_event(title: str, start: str, end: str, location: str = "", description: str = "", attendees: list = None) -> Dict[str, Any]:
    """
    Creates a new event in Google Calendar.
    """
    try:
        from googleapiclient.discovery import build
        creds = get_google_credentials()
        if not creds:
            return {"success": False, "error": "Failed to authenticate with Google Calendar"}

        cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
        service = build("calendar", "v3", credentials=creds)

        event_body = {
            "summary": title,
            "start": {
                "dateTime": start,
                "timeZone": "UTC"
            },
            "end": {
                "dateTime": end,
                "timeZone": "UTC"
            }
        }
        if location:
            event_body["location"] = location
        if description:
            event_body["description"] = description
        if attendees:
            event_body["attendees"] = [{"email": email} for email in attendees]

        created_event = service.events().insert(calendarId=cal_id, body=event_body).execute()
        log.info("Google Calendar: created event '%s' (ID: %s)", title, created_event.get("id"))
        return {"success": True, "event_id": created_event.get("id")}
    except Exception as e:
        log.error("Google Calendar create_event error: %s", e)
        return {"success": False, "error": str(e)}


# ─── Outlook via Microsoft Graph API ──────────────────────────────────────────

def fetch_outlook_graph_events() -> List[Dict[str, Any]]:
    """
    Fetches events via Microsoft Graph API using MSAL.
    Install with: pip install msal requests
    """
    tenant   = os.getenv("OUTLOOK_TENANT_ID", "")
    client   = os.getenv("OUTLOOK_CLIENT_ID", "")
    secret   = os.getenv("OUTLOOK_CLIENT_SECRET", "")
    user_email = os.getenv("OUTLOOK_USER_EMAIL", "")

    if not all([tenant, client, secret, user_email]):
        log.warning("Outlook Graph credentials incomplete — skipping Graph API.")
        return []

    try:
        import msal
        import requests as req

        authority = f"https://login.microsoftonline.com/{tenant}"
        app = msal.ConfidentialClientApplication(client, authority=authority, client_credential=secret)
        token_result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])

        if "access_token" not in token_result:
            log.error("Could not acquire Graph token: %s", token_result.get("error_description"))
            return []

        token = token_result["access_token"]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        t_min, t_max = iso_now_range()
        url = (
            f"https://graph.microsoft.com/v1.0/users/{user_email}/calendarView"
            f"?startDateTime={t_min}&endDateTime={t_max}&$top=250"
            f"&$select=id,subject,start,end,location,attendees,bodyPreview"
        )

        res = req.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        items = res.json().get("value", [])

        events = []
        for item in items:
            start = item.get("start", {}).get("dateTime", "") + "Z"
            end   = item.get("end",   {}).get("dateTime", "") + "Z"
            attendees = [
                a.get("emailAddress", {}).get("address", "")
                for a in item.get("attendees", [])
            ]
            location = item.get("location", {}).get("displayName", "")
            events.append(make_event(
                event_id=item.get("id", ""),
                title=item.get("subject", ""),
                start=start,
                end=end,
                source="outlook",
                location=location,
                attendees=attendees,
                description=item.get("bodyPreview", ""),
            ))

        log.info("Outlook Graph: fetched %d events.", len(events))
        return events

    except ImportError:
        log.warning("msal not installed. Run: pip install msal requests")
        return []
    except Exception as e:
        log.error("Outlook Graph error: %s", e)
        return []


# ─── Outlook via ICS feed (simpler alternative) ────────────────────────────────

def fetch_outlook_ics_events() -> List[Dict[str, Any]]:
    """
    Parses an ICS feed URL (e.g. from Outlook's 'Publish online' feature).
    Set OUTLOOK_ICS_URL to your ICS URL.
    Install: pip install icalendar requests
    """
    ics_url = os.getenv("OUTLOOK_ICS_URL", "")
    if not ics_url:
        return []

    try:
        import requests as req
        from icalendar import Calendar

        res = req.get(ics_url, timeout=10)
        res.raise_for_status()
        cal = Calendar.from_ical(res.content)

        events = []
        t_min, t_max = iso_now_range()
        dt_min = datetime.fromisoformat(t_min.replace("Z", "+00:00"))
        dt_max = datetime.fromisoformat(t_max.replace("Z", "+00:00"))

        for component in cal.walk():
            if component.name != "VEVENT":
                continue

            dtstart = component.get("DTSTART").dt
            dtend   = component.get("DTEND").dt

            # Make tz-aware
            if not hasattr(dtstart, "tzinfo") or dtstart.tzinfo is None:
                dtstart = datetime(dtstart.year, dtstart.month, dtstart.day, tzinfo=timezone.utc)
            if not hasattr(dtend, "tzinfo") or dtend.tzinfo is None:
                dtend = datetime(dtend.year, dtend.month, dtend.day, tzinfo=timezone.utc)

            if dtstart < dt_min or dtstart > dt_max:
                continue

            events.append(make_event(
                event_id=str(component.get("UID", "")),
                title=str(component.get("SUMMARY", "")),
                start=dtstart.isoformat(),
                end=dtend.isoformat(),
                source="outlook",
                location=str(component.get("LOCATION", "")),
                description=str(component.get("DESCRIPTION", "")),
            ))

        log.info("Outlook ICS: fetched %d events.", len(events))
        return events

    except ImportError:
        log.warning("icalendar not installed. Run: pip install icalendar requests")
        return []
    except Exception as e:
        log.error("Outlook ICS error: %s", e)
        return []


# ─── Aggregator ────────────────────────────────────────────────────────────────

def get_combined_events() -> List[Dict[str, Any]]:
    """Merge events from all configured sources, deduplicate by id."""
    events: List[Dict[str, Any]] = []
    events.extend(fetch_google_events())

    # Prefer Graph API, fall back to ICS if Graph creds not provided
    outlook_graph = fetch_outlook_graph_events()
    if outlook_graph:
        events.extend(outlook_graph)
    else:
        events.extend(fetch_outlook_ics_events())

    # Deduplicate by id
    seen = set()
    unique = []
    for ev in events:
        key = ev["id"]
        if key not in seen:
            seen.add(key)
            unique.append(ev)

    # Sort chronologically
    unique.sort(key=lambda e: e["start"])
    return unique


# ─── HTTP Server ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info(fmt, *args)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path not in ("/events", "/events/"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')
            return

        try:
            events = get_combined_events()
            body = json.dumps({"events": events, "count": len(events)}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            log.error("Handler error: %s", e)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_POST(self):
        if self.path not in ("/create-google-event", "/create-google-event/"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')
            return

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))

            title = params.get("title")
            start = params.get("start")
            end = params.get("end")
            location = params.get("location", "")
            description = params.get("description", "")
            attendees = params.get("attendees", [])

            res = create_google_event(
                title=title,
                start=start,
                end=end,
                location=location,
                description=description,
                attendees=attendees
            )

            body = json.dumps(res, ensure_ascii=False).encode()
            self.send_response(200 if res.get("success") else 400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            log.error("POST Handler error: %s", e)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())


if __name__ == "__main__":
    log.info("Calendar Aggregator starting on port %d ...", PORT)
    log.info("Google Credentials: %s", os.getenv("GOOGLE_CREDENTIALS_FILE", "(not set)"))
    log.info("Outlook mode:       %s",
        "Graph API" if os.getenv("OUTLOOK_TENANT_ID") else
        "ICS Feed" if os.getenv("OUTLOOK_ICS_URL") else
        "(not configured)")

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    log.info("Ready. Listening at http://localhost:%d/events", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        server.server_close()
