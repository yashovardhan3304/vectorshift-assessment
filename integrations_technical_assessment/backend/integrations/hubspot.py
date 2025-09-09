# hubspot.py

import json
import base64
import secrets
import asyncio
import requests
import urllib.parse
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse

from integrations.integration_item import IntegrationItem
from redis_client import add_key_value_redis, get_value_redis, delete_key_redis

# Replace with your HubSpot app credentials for testing
CLIENT_ID = 'your-client-id'
CLIENT_SECRET = 'your-client-secret'

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
    state_data = {
        'state': secrets.token_urlsafe(32),
        'user_id': user_id,
        'org_id': org_id,
    }
    encoded_state = base64.urlsafe_b64encode(json.dumps(state_data).encode('utf-8')).decode('utf-8')
    await add_key_value_redis(f'hubspot_state:{org_id}:{user_id}', json.dumps(state_data), expire=600)

    scope_param = urllib.parse.quote(SCOPE, safe="")
    auth_url = f'{authorization_url}&scope={scope_param}&state={encoded_state}'
    return auth_url

async def oauth2callback_hubspot(request: Request):
    if request.query_params.get('error'):
        # HubSpot sends `error` and `error_description` on failure
        raise HTTPException(status_code=400, detail=request.query_params.get('error_description') or request.query_params.get('error'))

    code = request.query_params.get('code')
    encoded_state = request.query_params.get('state')
    state_data = json.loads(base64.urlsafe_b64decode(encoded_state).decode('utf-8'))

    original_state = state_data.get('state')
    user_id = state_data.get('user_id')
    org_id = state_data.get('org_id')

    saved_state = await get_value_redis(f'hubspot_state:{org_id}:{user_id}')
    if not saved_state:
        raise HTTPException(status_code=400, detail='State not found (expired). Please retry Connect.')
    saved_state_obj = json.loads(saved_state)
    if original_state != saved_state_obj.get('state'):
        raise HTTPException(status_code=400, detail='State mismatch. Please retry Connect and complete in the most recent popup.')

    # Exchange code for tokens
    token_response = requests.post(
        'https://api.hubapi.com/oauth/v1/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
        },
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {encoded_client_id_secret}',
        },
    )

    await delete_key_redis(f'hubspot_state:{org_id}:{user_id}')

    if token_response.status_code != 200:
        raise HTTPException(status_code=400, detail=f'HubSpot token exchange failed: {token_response.text}')

    await add_key_value_redis(
        f'hubspot_credentials:{org_id}:{user_id}',
        json.dumps(token_response.json()),
        expire=600,
    )

    close_window_script = """
    <html>
        <script>
            window.close();
        </script>
    </html>
    """
    return HTMLResponse(content=close_window_script)

async def get_hubspot_credentials(user_id, org_id):
    credentials = await get_value_redis(f'hubspot_credentials:{org_id}:{user_id}')
    if not credentials:
        raise HTTPException(status_code=400, detail='No credentials found.')
    credentials = json.loads(credentials)
    await delete_key_redis(f'hubspot_credentials:{org_id}:{user_id}')
    return credentials

def _create_integration_item_from_contact(contact: dict) -> IntegrationItem:
    properties = contact.get('properties', {}) or {}
    first_name = properties.get('firstname') or ''
    last_name = properties.get('lastname') or ''
    email = properties.get('email')
    display_name = (first_name + ' ' + last_name).strip() or email or contact.get('id')
    return IntegrationItem(
        id=f"{contact.get('id')}_contact",
        type='contact',
        name=display_name,
        url=None,
    )

def _create_integration_item_from_company(company: dict) -> IntegrationItem:
    properties = company.get('properties', {}) or {}
    name = properties.get('name') or properties.get('domain') or company.get('id')
    return IntegrationItem(
        id=f"{company.get('id')}_company",
        type='company',
        name=name,
        url=None,
    )

async def get_items_hubspot(credentials):
    """Fetch a small sample of HubSpot CRM objects and return as IntegrationItems."""
    credentials = json.loads(credentials)
    access_token = credentials.get('access_token')
    if not access_token:
        raise HTTPException(status_code=400, detail='Missing access token.')

    headers = { 'Authorization': f'Bearer {access_token}' }

    items: list[IntegrationItem] = []

    # Contacts
    contacts_resp = requests.get(
        'https://api.hubapi.com/crm/v3/objects/contacts',
        params={'limit': 20, 'properties': 'firstname,lastname,email'},
        headers=headers,
    )
    if contacts_resp.status_code == 200:
        for c in contacts_resp.json().get('results', []):
            items.append(_create_integration_item_from_contact(c))

    # Companies
    companies_resp = requests.get(
        'https://api.hubapi.com/crm/v3/objects/companies',
        params={'limit': 20, 'properties': 'name,domain'},
        headers=headers,
    )
    if companies_resp.status_code == 200:
        for c in companies_resp.json().get('results', []):
            items.append(_create_integration_item_from_company(c))

    print(f'list_of_integration_item_metadata: {items}')
    return items