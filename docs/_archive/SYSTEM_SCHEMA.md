# SYSTEM_SCHEMA.md
# AgenticOS-2026 System Overview

## PocketBase Instance
- URL: http://host.docker.internal:8090
- Superuser: michaelbeatman@outlook.com (OAuth token stored in frontend/localStorage)

## Collections

### kontakte
| Field | Type | Description |
|-------|------|-------------|
| id | string (auto) | Primary key |
| name | string | Full name |
| rolle | string | Job title/role |
| unternehmen | string | Company |
| region | string | Location/region |
| email | string | Email address |
| telefon_1 | string | Primary phone |
| telefon_2 | string | Secondary phone |
| linkedin_url | string | LinkedIn profile URL |
| profilbild | file | Profile picture (image) |
| nachrichtenverlauf | jsonArray | Array of message objects (each with absender, datum, text, richtung) |
| rating | integer (0-5) | Derived from message count (0=0,1=1,2=2-3,3=4-6,4=7-9,5=>=10) |
| status | string | Contact status (e.g., Vernetzt, Erstnachricht, Gesperrt_1Jahr) |
| tags | stringArray | Keywords (e.g., c-level, c-tier) |
| vernetzt_am | dateTime | Timestamp when connection established |
| einladung_zurueckgezogen_am | dateTime | Timestamp when invitation withdrawn |
| Vernetzt_seit | dateTime | Timestamp when status became Vernetzt (redundant?) |
| created | dateTime (auto) | Record creation timestamp |
| updated | dateTime (auto) | Record last update timestamp |
| deleted_at | dateTime, nullable | Soft delete timestamp (if set, record is considered deleted) |

### termine
| Field | Type | Description |
|-------|------|-------------|
| id | string (auto) | Primary key |
| titel | string | Event title |
| start | dateTime | Start time (ISO 8601) |
| ende | dateTime | End time (ISO 8601) |
| ort | string | Location |
| notiz | string | Description/notes |
| kontakt | string | Reference to kontakte.id (optional) |
| created | dateTime (auto) | Record creation timestamp |
| updated | dateTime (auto) | Record last update timestamp |

### MediaBoard
| Field | Type | Description |
|-------|------|-------------|
| id | string (auto) | Primary key |
| titel | string | Title/description |
| url | string | External link |
| notiz | string | Notes |
| bild | file | Image file |
| created | dateTime (auto) | Record creation timestamp |
| updated | dateTime (auto) | Record last update timestamp |

## API Ports
- Next.js Frontend: http://localhost:3005 (Docker container crm-frontend)
- PocketBase API: http://host.docker.internal:8090
- Calendar Aggregator (optional): http://localhost:8421 (Python service for Google/Outlook sync)

## Scripts Directory (/scripts/)
- rescore_contacts.py: Recalculates rating based on nachrichtenverlauf length.
- dsgvo_purge.py: Permanently deletes kontakt records where deleted_at is older than 30 days.
- import_linkedin_messages.py: Imports LinkedIn messages from CSV backup.
- dedupe_messages.py: Removes duplicate messages based on sender+normalized text.

## Frontend Source Structure (/frontend/src/)
- app/crm/page.tsx: Main CRM page with sidebar and route handlers.
- components/: Reusable UI components (KontaktDrawer, NachrichtenverlaufPanel, AlleNachrichtenView, PipelineAnalytics, etc.)
- lib/pocketbase.ts: PocketBase client initialization.
- styles/: Tailwind CSS configuration.

## Deployment
- Frontend built via `crm-neu-bauen.bat` (Windows) which runs `docker compose up -d --build crm-frontend`.
- PocketBase runs via Docker Compose (service `pb`).
