## Detailed Code Changes with Rationale

This document enumerates every source change made during the assessment, with context and reasoning. Paths are relative to the repo root unless noted.

### 1) Backend – `integrations_technical_assessment/backend/integrations/hubspot.py`

Added full HubSpot integration (OAuth + data loading).

- Implemented OAuth authorize endpoint builder, callback token exchange, credential retrieval, and item loading for HubSpot Contacts/Companies.
- URL/state handling hardened to prevent state-mismatch errors and to ensure correct encoding with HubSpot.

Key additions and why:

```python
# New file content implemented
import json, base64, secrets, requests, urllib.parse
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
from integrations.integration_item import IntegrationItem
from redis_client import add_key_value_redis, get_value_redis, delete_key_redis

CLIENT_ID = '...'  # reason: required for OAuth
CLIENT_SECRET = '...'  # reason: required for OAuth

REDIRECT_URI = 'http://localhost:8000/integrations/hubspot/oauth2callback'
authorization_url = (
    f'https://app.hubspot.com/oauth/authorize?client_id={CLIENT_ID}'
    f'&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe="")}'
    f'&response_type=code'
)

SCOPE = (
    'crm.objects.contacts.read crm.schemas.contacts.read '
    'crm.objects.companies.read crm.schemas.companies.read oauth'
)

encoded_client_id_secret = base64.b64encode(f'{CLIENT_ID}:{CLIENT_SECRET}'.encode()).decode()

async def authorize_hubspot(user_id, org_id):
    # reason: generate CSRF state and persist for later validation
    state_data = { 'state': secrets.token_urlsafe(32), 'user_id': user_id, 'org_id': org_id }
    encoded_state = base64.urlsafe_b64encode(json.dumps(state_data).encode('utf-8')).decode('utf-8')
    await add_key_value_redis(f'hubspot_state:{org_id}:{user_id}', json.dumps(state_data), expire=600)

    # reason: encode scope/redirect correctly for HubSpot
    scope_param = urllib.parse.quote(SCOPE, safe="")
    return f'{authorization_url}&scope={scope_param}&state={encoded_state}'

async def oauth2callback_hubspot(request: Request):
    # reason: handle provider error and state validation
    if request.query_params.get('error'):
        raise HTTPException(status_code=400, detail=request.query_params.get('error_description') or request.query_params.get('error'))
    code = request.query_params.get('code')
    encoded_state = request.query_params.get('state')
    state_data = json.loads(base64.urlsafe_b64decode(encoded_state).decode('utf-8'))
    original_state = state_data.get('state'); user_id = state_data.get('user_id'); org_id = state_data.get('org_id')
    saved_state = await get_value_redis(f'hubspot_state:{org_id}:{user_id}')
    if not saved_state:
        raise HTTPException(status_code=400, detail='State not found (expired). Please retry Connect.')
    if original_state != json.loads(saved_state).get('state'):
        raise HTTPException(status_code=400, detail='State mismatch. Please retry Connect and complete in the most recent popup.')

    # reason: exchange code for tokens
    token_response = requests.post(
        'https://api.hubapi.com/oauth/v1/token',
        data={ 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI, 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET },
        headers={ 'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': f'Basic {encoded_client_id_secret}' },
    )
    await delete_key_redis(f'hubspot_state:{org_id}:{user_id}')
    if token_response.status_code != 200:
        raise HTTPException(status_code=400, detail=f'HubSpot token exchange failed: {token_response.text}')
    await add_key_value_redis(f'hubspot_credentials:{org_id}:{user_id}', json.dumps(token_response.json()), expire=600)
    return HTMLResponse(content='\n    <html><script>window.close();</script></html>\n    ')

async def get_hubspot_credentials(user_id, org_id):
    # reason: return stored credentials to the frontend after popup closed
    credentials = await get_value_redis(f'hubspot_credentials:{org_id}:{user_id}')
    if not credentials:
        raise HTTPException(status_code=400, detail='No credentials found.')
    credentials = json.loads(credentials)
    await delete_key_redis(f'hubspot_credentials:{org_id}:{user_id}')
    return credentials

def _create_integration_item_from_contact(contact: dict) -> IntegrationItem:
    # reason: normalize API response into IntegrationItem
    props = contact.get('properties', {}) or {}
    name = (props.get('firstname') or '') + ' ' + (props.get('lastname') or '')
    name = name.strip() or props.get('email') or contact.get('id')
    return IntegrationItem(id=f"{contact.get('id')}_contact", type='contact', name=name)

def _create_integration_item_from_company(company: dict) -> IntegrationItem:
    props = company.get('properties', {}) or {}
    name = props.get('name') or props.get('domain') or company.get('id')
    return IntegrationItem(id=f"{company.get('id')}_company", type='company', name=name)

async def get_items_hubspot(credentials):
    # reason: fetch demo data to prove OAuth worked
    creds = json.loads(credentials)
    token = creds.get('access_token');
    if not token: raise HTTPException(status_code=400, detail='Missing access token.')
    headers = { 'Authorization': f'Bearer {token}' }
    items = []
    r = requests.get('https://api.hubapi.com/crm/v3/objects/contacts', params={'limit': 20, 'properties': 'firstname,lastname,email'}, headers=headers)
    if r.status_code == 200:
        for c in r.json().get('results', []): items.append(_create_integration_item_from_contact(c))
    r = requests.get('https://api.hubapi.com/crm/v3/objects/companies', params={'limit': 20, 'properties': 'name,domain'}, headers=headers)
    if r.status_code == 200:
        for c in r.json().get('results', []): items.append(_create_integration_item_from_company(c))
    return items
```

### 2) Backend – `integrations_technical_assessment/backend/main.py`

Changed routes and CORS.

- Why: Align backend endpoints with frontend expectations and fix CORS errors from 127.0.0.1/localhost and typical dev ports.

Changes:

```python
# CORS origins expanded
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# HubSpot load route aligned with DataForm mapping
@app.post('/integrations/hubspot/load')
async def load_hubspot_data_integration(credentials: str = Form(...)):
    return await get_items_hubspot(credentials)
```

### 3) Backend – `integrations_technical_assessment/backend/redis_client.py`

Added an in-memory fallback store when Redis is unavailable (useful on Windows or when Docker isn’t running) to avoid OAuth flow failures during local testing.

Key changes and why:

```python
# reason: wrap redis calls; fallback to in-memory dict on failure so OAuth can complete locally
_memory_store: dict[str, tuple[bytes, Optional[float]]] = {}

async def add_key_value_redis(key, value, expire=None):
    try:
        await redis_client.set(key, value)
        if expire: await redis_client.expire(key, expire)
    except Exception:
        expire_at = time.time() + expire if expire else None
        _memory_store[str(key)] = ((value if isinstance(value, (bytes, bytearray)) else str(value).encode()), expire_at)

async def get_value_redis(key):
    try:
        return await redis_client.get(key)
    except Exception:
        entry = _memory_store.get(str(key))
        if not entry: return None
        value, expire_at = entry
        if expire_at is not None and time.time() > expire_at:
            _memory_store.pop(str(key), None)
            return None
        return value

async def delete_key_redis(key):
    try: await redis_client.delete(key)
    except Exception: _memory_store.pop(str(key), None)
```

### 4) Frontend – `integrations_technical_assessment/frontend/src/integrations/hubspot.js`

New component to handle HubSpot OAuth on the client.

- Why: Provide a UI button to initiate OAuth, poll popup close, fetch credentials, and mark the integration as connected.

Key content:

```javascript
export const HubspotIntegration = ({ user, org, integrationParams, setIntegrationParams }) => {
  // reason: mirrors Airtable/Notion flow for consistency
  const handleConnectClick = async () => {
    const formData = new FormData();
    formData.append('user_id', user);
    formData.append('org_id', org);
    const { data: authURL } = await axios.post('http://localhost:8000/integrations/hubspot/authorize', formData);
    const win = window.open(authURL, 'HubSpot Authorization', 'width=600,height=600');
    const timer = setInterval(async () => {
      if (win?.closed !== false) { clearInterval(timer); await handleWindowClosed(); }
    }, 200);
  };

  const handleWindowClosed = async () => {
    const formData = new FormData();
    formData.append('user_id', user);
    formData.append('org_id', org);
    const { data: credentials } = await axios.post('http://localhost:8000/integrations/hubspot/credentials', formData);
    if (credentials) setIntegrationParams(prev => ({ ...prev, credentials, type: 'HubSpot' }));
  };
};
```

### 5) Frontend – `integrations_technical_assessment/frontend/src/integration-form.js`

Wired HubSpot into the integration selector.

- Why: Make the HubSpot component accessible from the UI.

Change:

```javascript
import { HubspotIntegration } from './integrations/hubspot';

const integrationMapping = {
  'Notion': NotionIntegration,
  'Airtable': AirtableIntegration,
  'HubSpot': HubspotIntegration, // reason: expose in UI
};
```

### 6) Frontend – `integrations_technical_assessment/frontend/src/data-form.js`

- Mapped HubSpot to its backend endpoint
- Switched Loaded Data field to pretty-printed JSON multiline for clarity

Changes:

```javascript
const endpointMapping = {
  'Notion': 'notion',
  'Airtable': 'airtable',
  'HubSpot': 'hubspot', // reason: enable load for HubSpot
};

// reason: show raw JSON results instead of [object Object]
const [loadedData, setLoadedData] = useState('');
setLoadedData(JSON.stringify(response.data, null, 2));
```

### 7) Root – `README.md`

Added a comprehensive README covering setup, running, OAuth configuration, endpoints, and troubleshooting.

- Why: Provide clear instructions to set up and test all integrations.

### Summary of intent
- Implemented missing HubSpot integration end-to-end.
- Smoothed local dev by fixing CORS, adding Redis fallback, and aligning routes.
- Made the frontend show accurate results and expose HubSpot in the UI.


