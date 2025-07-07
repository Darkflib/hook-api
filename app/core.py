# app/core.py
# Contains shared models, database instance, and utility functions

from fastapi import HTTPException, status
from typing import Dict, Any, List
import httpx
import asyncio
from pydantic import BaseModel, Field

# --- In-memory "database" ---
db: Dict[str, Dict[str, Any]] = {}

# --- Pydantic Models ---

class WebhookTemplateBase(BaseModel):
    """
    Base model for a webhook template.
    """
    name: str = Field(..., description="A unique, human-readable name for the template.")
    method: str = Field("POST", description="HTTP method to use for the webhook (GET, POST, PUT, DELETE, etc.).")
    url_template: str = Field(..., description="URL template with optional placeholders using Python's format syntax {variable}.")
    headers_template: Dict[str, str] = Field({}, description="Dictionary of HTTP headers with optional placeholders.")
    body_template: Dict[str, Any] = Field({}, description="JSON body template with optional placeholders. Can contain nested structures.")

class WebhookTemplateCreate(WebhookTemplateBase):
    """
    Model for creating a new template.
    """
    pass

class WebhookTemplate(WebhookTemplateBase):
    """
    Model for a template as it is stored and returned from the API.
    """
    id: str = Field(..., description="Unique identifier for the template.")

class AdhocWebhookTrigger(BaseModel):
    """
    Model for triggering an ad-hoc webhook.
    """
    method: str = Field("POST", description="HTTP method for the webhook request (GET, POST, PUT, DELETE, etc.).")
    url: str = Field(..., description="The complete target URL for the webhook.")
    headers: Dict[str, str] = Field({}, description="Dictionary of HTTP headers to include in the request.")
    body: Dict[str, Any] = Field({}, description="JSON body to send with the webhook request.")
    wait_for_response: bool = Field(True, description="Whether to wait for and return the response. If False, webhook is sent asynchronously.")

class TemplatedWebhookTrigger(BaseModel):
    """
    Model for triggering a webhook from a saved template.
    """
    template_id: str = Field(..., description="The ID of the template to use.")
    values: Dict[str, Any] = Field({}, description="Values to substitute into the template's placeholders. Keys should match the placeholder names in the template.")
    wait_for_response: bool = Field(True, description="Whether to wait for and return the response. If False, webhook is sent asynchronously.")

# --- Helper Function to Send Webhook ---

async def send_webhook(method: str, url: str, headers: Dict[str, str], json_body: Dict[str, Any], wait_for_response: bool = True) -> Dict[str, Any]:
    """
    Asynchronously sends a webhook request using httpx.
    """
    safe_headers = {k: ("REDACTED" if k.lower() in ["authorization", "x-api-key", "api-key"] else v)
                    for k, v in headers.items()}
    request_info = {
        "method": method,
        "url": url,
        "headers": safe_headers
    }

    async with httpx.AsyncClient() as client:
        try:
            if not wait_for_response:
                asyncio.create_task(_handle_async_task(client.request(method, url, headers=headers, json=json_body, timeout=10.0)))
                return {
                    "webhook_status": "accepted",
                    "message": "Webhook request has been sent asynchronously",
                    "webhook_request": {
                        "method": method,
                        "url": url
                    }
                }

            response = await client.request(method, url, headers=headers, json=json_body, timeout=10.0)

            try:
                response_body = response.json()
            except (ValueError, TypeError):
                response_body = response.text

            return {
                "webhook_status": "success",
                "webhook_request": request_info,
                "webhook_response": {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response_body
                }
            }
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"An error occurred while sending the webhook to {exc.request.url!r}: {exc}"
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred: {str(exc)}"
            )
