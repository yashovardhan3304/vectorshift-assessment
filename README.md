## Integrations Technical Assessment – Setup and Usage

This project contains a FastAPI backend and a React frontend that demonstrate OAuth integrations for HubSpot, Airtable, and Notion, plus a simple item-loading flow.

### Prerequisites
- Python 3.11+
- Node.js 16+ and npm
- Redis (recommended via Docker)

### Project layout
- `integrations_technical_assessment/backend`: FastAPI app and integrations
- `integrations_technical_assessment/frontend`: React app (Create React App)

### 1) Backend setup
From the repository root:

```bash
# Create and activate a venv
python -m venv .venv
. .venv/Scripts/Activate.ps1   # Windows PowerShell

# Install dependencies
pip install --upgrade pip
pip install -r integrations_technical_assessment/backend/requirements.txt

# Run Redis (recommended)
# If you have Docker: `docker run -d --name redis -p 6379:6379 redis:7-alpine`

# Start the FastAPI server
python -m uvicorn main:app --app-dir integrations_technical_assessment/backend --port 8000
```

Notes (Windows): if `pycurl` or `uvloop` fail to install, you can temporarily remove them from the requirements to run locally. The app does not rely on them for this assessment.

### 2) Frontend setup
In a new terminal:

```bash
cd integrations_technical_assessment/frontend
npm install
npm start
```

By default, the frontend runs on `http://localhost:3000` and expects the backend at `http://localhost:8000`.

### 3) OAuth app configuration
You must provide your own client credentials and whitelist redirect URIs for testing. Update the files below and set the exact redirect URIs in each provider’s developer console.

- HubSpot: `integrations_technical_assessment/backend/integrations/hubspot.py`
  - Set `CLIENT_ID`, `CLIENT_SECRET`
  - Redirect URI: `http://localhost:8000/integrations/hubspot/oauth2callback`
  - Example scopes: `crm.objects.contacts.read crm.schemas.contacts.read crm.objects.companies.read crm.schemas.companies.read`

- Airtable: `integrations_technical_assessment/backend/integrations/airtable.py`
  - Set `CLIENT_ID`, `CLIENT_SECRET`
  - Redirect URI: `http://localhost:8000/integrations/airtable/oauth2callback`
  - Ensure your account has accessible bases and include read scopes.

- Notion: `integrations_technical_assessment/backend/integrations/notion.py`
  - Set `CLIENT_ID`, `CLIENT_SECRET`
  - Redirect URI: `http://localhost:8000/integrations/notion/oauth2callback`

Important: The redirect URIs must match exactly (scheme, host, port, path) in both code and provider settings.

### 4) Using the app
1. Open the frontend at `http://localhost:3000`.
2. Choose an integration from the dropdown (HubSpot, Airtable, Notion).
3. Click “Connect” to start OAuth in a popup; complete consent.
4. After the popup closes, click “Load Data” to fetch items.
5. The resulting Integration Items are displayed as JSON in the UI and logged by the backend.

### Troubleshooting
- CORS blocked: The backend allows `http://localhost:3000` and `http://127.0.0.1:3000` (and Vite defaults on 5173). If you use a different origin, add it in `backend/main.py` `allow_origins`.
- State mismatch / expired: Ensure Redis is running so state survives, or avoid auto-reload while completing OAuth. You can run Uvicorn without `--reload` during OAuth.
- HubSpot invalid client_id: Confirm the correct credentials (Dev vs Prod) and that the redirect URI is whitelisted.
- Airtable returns empty: Usually missing scopes or no accessible bases in the authorized account. Reconnect with valid scopes and an account that has bases.

### Key backend endpoints
- `POST /integrations/{airtable|notion|hubspot}/authorize` – returns the OAuth authorization URL
- `GET /integrations/{airtable|notion|hubspot}/oauth2callback` – provider callback to exchange code for tokens
- `POST /integrations/{airtable|notion|hubspot}/credentials` – returns stored credentials once login completes
- `POST /integrations/{airtable|notion|hubspot}/load` – fetches and returns Integration Items

### Notes on performance
- The frontend shows loaded data as formatted JSON; for large payloads, a preview + expand pattern is recommended to minimize re-render cost.

### License
For assessment use only.


