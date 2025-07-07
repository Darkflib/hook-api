# main.py
# The entry point for the FastAPI application.

from fastapi import FastAPI, HTTPException, status
from typing import Dict, Any, List
import httpx
import uuid
import asyncio
from pydantic import BaseModel, Field

# --- In-memory "database" ---
# A simple dictionary to store templates. In a real application,
# you would replace this with a proper database (e.g., PostgreSQL, MongoDB).
db: Dict[str, Dict[str, Any]] = {}

class WebhookTemplateBase(BaseModel):
    """
    Base model for a webhook template.
    
    Attributes:
        name: A unique, human-readable name for the template. This must be unique across all templates.
        method: HTTP method to use for the webhook (GET, POST, PUT, DELETE, etc.). Defaults to POST.
        url_template: URL template with optional placeholders using Python's format syntax {variable}.
            Example: https://api.example.com/users/{user_id}/notifications
        headers_template: Dictionary of HTTP headers with optional placeholders.
            Example: {"Authorization": "Bearer {token}", "X-Event-Type": "user.created"}
        body_template: JSON body template with optional placeholders. Can contain nested structures.
            Example: {"username": "{username}", "email": "{email}", "metadata": {"source": "webhook-mcp"}}
    """
    name: str = Field(..., description="A unique, human-readable name for the template.")
    method: str = Field("POST", description="HTTP method to use for the webhook (GET, POST, PUT, DELETE, etc.).")
    url_template: str = Field(..., description="URL template with optional placeholders using Python's format syntax {variable}.")
    headers_template: Dict[str, str] = Field({}, description="Dictionary of HTTP headers with optional placeholders.")
    body_template: Dict[str, Any] = Field({}, description="JSON body template with optional placeholders. Can contain nested structures.")

class WebhookTemplateCreate(WebhookTemplateBase):
    """
    Model for creating a new template.
    
    This model inherits all fields from WebhookTemplateBase and is used
    specifically for the request body when creating a new webhook template.
    """
    pass

class WebhookTemplate(WebhookTemplateBase):
    """
    Model for a template as it is stored and returned from the API.
    
    This model extends WebhookTemplateBase by adding an ID field.
    
    Attributes:
        id: A unique identifier (UUID) automatically generated for the template.
    """
    id: str = Field(..., description="Unique identifier for the template.")

class AdhocWebhookTrigger(BaseModel):
    """
    Model for triggering a one-off, ad-hoc webhook.
    
    This model is used when you want to send a webhook directly without
    using a saved template. All values are provided explicitly.
    
    Attributes:
        method: HTTP method for the request (GET, POST, PUT, etc.). Defaults to POST.
        url: The complete target URL for the webhook.
        headers: Dictionary of HTTP headers to include in the request.
        body: JSON body to send with the request.
        wait_for_response: Whether to wait for and return the response. Defaults to True.
            If set to False, the webhook is sent asynchronously and the response is not waited for.
    """
    method: str = Field("POST", description="HTTP method for the webhook request (GET, POST, PUT, DELETE, etc.).")
    url: str = Field(..., description="The complete target URL for the webhook.")
    headers: Dict[str, str] = Field({}, description="Dictionary of HTTP headers to include in the request.")
    body: Dict[str, Any] = Field({}, description="JSON body to send with the webhook request.")
    wait_for_response: bool = Field(True, description="Whether to wait for and return the response. If False, webhook is sent asynchronously.")

class TemplatedWebhookTrigger(BaseModel):
    """
    Model for triggering a webhook from a saved template.
    
    This model is used when you want to send a webhook using a pre-saved
    template and substitute values into its placeholders.
    
    Attributes:
        template_id: The ID of the template to use.
        values: Dictionary of values to substitute into the template's placeholders.
            The keys in this dictionary should match the placeholder names in the template.
            For example, if the template URL is "https://api.example.com/users/{user_id}",
            then values should contain a "user_id" key.
        wait_for_response: Whether to wait for and return the response. Defaults to True.
            If set to False, the webhook is sent asynchronously and the response is not waited for.
    """
    template_id: str = Field(..., description="The ID of the template to use.")
    values: Dict[str, Any] = Field({}, description="Values to substitute into the template's placeholders. Keys should match the placeholder names in the template.")
    wait_for_response: bool = Field(True, description="Whether to wait for and return the response. If False, webhook is sent asynchronously.")


# --- FastAPI App Instance ---
app = FastAPI(
    title="Webhook MCP Service",
    description="An API for creating, managing, and triggering templated webhooks.",
    version="0.1.0",
)

# --- Helper Function to Send Webhook ---

async def send_webhook(method: str, url: str, headers: Dict[str, str], json_body: Dict[str, Any], wait_for_response: bool = True) -> Dict[str, Any]:
    """
    Asynchronously sends a webhook request using httpx.
    
    Args:
        method: The HTTP method (e.g., 'POST', 'GET').
        url: The target URL.
        headers: A dictionary of request headers.
        json_body: A dictionary for the JSON request body.
        wait_for_response: Whether to wait for and return the response.
            If False, the webhook is sent asynchronously and a simple acknowledgment is returned.

    Returns:
        A dictionary containing information about the webhook call:
        - If wait_for_response is True:
            {
                "webhook_status": "success",
                "webhook_request": {
                    "method": method,
                    "url": url,
                    "headers": headers (with sensitive values redacted)
                },
                "webhook_response": {
                    "status_code": HTTP status code,
                    "headers": Response headers,
                    "body": Response body (parsed JSON if possible)
                }
            }
        - If wait_for_response is False:
            {
                "webhook_status": "accepted",
                "message": "Webhook request has been sent asynchronously",
                "webhook_request": {
                    "method": method,
                    "url": url
                }
            }
    """
    # Prepare a record of the request (with sensitive headers redacted)
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
                # Fire and forget - don't wait for response
                # Start the request but don't await the result
                # Schedule the task to run in the background
                asyncio.create_task(client.request(method, url, headers=headers, json=json_body, timeout=10.0))
                return {
                    "webhook_status": "accepted",
                    "message": "Webhook request has been sent asynchronously",
                    "webhook_request": {
                        "method": method,
                        "url": url
                    }
                }
            
            # Standard synchronous behavior - wait for response
            response = await client.request(method, url, headers=headers, json=json_body, timeout=10.0)
            
            # Attempt to parse response as JSON, fallback to text if not possible
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
            # Broad exception for network errors, DNS failures, etc.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"An error occurred while sending the webhook to {exc.request.url!r}: {exc}"
            )
        except Exception as exc:
            # Catch-all for other potential errors during the request.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred: {str(exc)}"
            )


# --- API Endpoints ---

@app.get("/", tags=["Health Check"])
async def read_root():
    """A simple health check endpoint."""
    return {"status": "ok", "message": "Welcome to the Webhook MCP Service"}

# --- Template Management Endpoints ---

@app.post("/templates/", response_model=WebhookTemplate, status_code=status.HTTP_201_CREATED, tags=["Templates"])
async def create_template(template: WebhookTemplateCreate):
    """
    Create a new webhook template.
    
    This endpoint allows you to create a reusable webhook template that can be triggered
    later with different values substituted into its placeholders.
    
    Parameters:
        template: A WebhookTemplateCreate object containing:
            - name: A unique, human-readable name for the template
            - method: HTTP method (defaults to POST)
            - url_template: URL with optional placeholders like {variable}
            - headers_template: Dictionary of headers with optional placeholders
            - body_template: JSON body with optional placeholders
    
    Example request body:
    ```json
    {
      "name": "New User Notification",
      "method": "POST",
      "url_template": "https://hooks.example.com/services/{service_id}",
      "headers_template": {
        "X-Event-Type": "user.created"
      },
      "body_template": {
        "username": "{username}",
        "email": "{email}",
        "source": "mcp-tester"
      }
    }
    ```
    
    Returns:
        The created template object including its generated ID.
        
    Raises:
        409: If a template with the same name already exists
    """
    template_id = str(uuid.uuid4())
    if any(t['name'] == template.name for t in db.values()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A template with the name '{template.name}' already exists."
        )
    
    new_template = WebhookTemplate(id=template_id, **template.dict())
    db[template_id] = new_template.dict()
    return new_template

@app.get("/templates/{template_id}", response_model=WebhookTemplate, tags=["Templates"])
async def get_template(template_id: str):
    """
    Retrieve a specific webhook template by its ID.
    
    Parameters:
        template_id: The unique identifier of the template to retrieve
        
    Returns:
        The complete webhook template object
        
    Raises:
        404: If no template with the given ID exists
    """
    if template_id not in db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return db[template_id]

@app.get("/templates/", response_model=List[WebhookTemplate], tags=["Templates"])
async def list_templates():
    """
    List all available webhook templates.
    
    Returns:
        A list of all webhook templates currently stored in the system
    """
    return list(db.values())

@app.put("/templates/{template_id}", response_model=WebhookTemplate, tags=["Templates"])
async def update_template(template_id: str, template_update: WebhookTemplateCreate):
    """
    Update an existing webhook template.
    
    Parameters:
        template_id: The unique identifier of the template to update
        template_update: A WebhookTemplateCreate object with the updated fields
        
    The request body has the same format as the create template endpoint.
    
    Returns:
        The updated webhook template object
        
    Raises:
        404: If no template with the given ID exists
        409: If attempting to rename to a name that conflicts with another template
    """
    if template_id not in db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    
    # Check for name collision if the name is being changed
    if any(t['name'] == template_update.name and t_id != template_id for t_id, t in db.items()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A template with the name '{template_update.name}' already exists."
        )

    updated_template_data = template_update.dict()
    db[template_id].update(updated_template_data)
    return WebhookTemplate(id=template_id, **db[template_id])


@app.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Templates"])
async def delete_template(template_id: str):
    """
    Delete a webhook template.
    
    Parameters:
        template_id: The unique identifier of the template to delete
        
    Returns:
        No content (204) on successful deletion
        
    Raises:
        404: If no template with the given ID exists
    """
    if template_id not in db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    del db[template_id]
    return

# --- Webhook Trigger Endpoints ---

@app.post("/webhooks/trigger/adhoc", status_code=status.HTTP_200_OK, tags=["Webhooks"])
async def trigger_adhoc_webhook(trigger: AdhocWebhookTrigger):
    """
    Trigger a single, non-templated webhook immediately.
    
    This endpoint allows you to send a one-off webhook without first creating a template.
    You provide all the details directly in the request.
    
    Parameters:
        trigger: An AdhocWebhookTrigger object containing:
            - method: HTTP method (GET, POST, PUT, etc.). Defaults to POST.
            - url: The complete target URL for the webhook.
            - headers: Dictionary of HTTP headers to include in the request.
            - body: JSON body to send with the request.
            - wait_for_response: Whether to wait for and return the response. Defaults to True.
                If set to False, the webhook is sent asynchronously and a simple acknowledgment is returned.
    
    Example request body:
    ```json
    {
      "method": "POST",
      "url": "https://httpbin.org/post",
      "headers": {"X-Custom-Header": "adhoc-test"},
      "body": {"message": "Hello, World!"},
      "wait_for_response": true
    }
    ```
    
    Returns:
        If wait_for_response is True:
            Detailed information about the webhook call, including:
            - webhook_status: "success"
            - webhook_request: Details about the sent request
            - webhook_response: The full response from the target server
        If wait_for_response is False:
            An acknowledgment that the webhook was sent asynchronously:
            - webhook_status: "accepted"
            - message: "Webhook request has been sent asynchronously"
            - webhook_request: Basic details about the sent request
        
    Raises:
        500: For general server errors
        503: If the webhook target is unreachable (only when wait_for_response is True)
    """
    return await send_webhook(
        method=trigger.method,
        url=trigger.url,
        headers=trigger.headers,
        json_body=trigger.body,
        wait_for_response=trigger.wait_for_response
    )

@app.post("/webhooks/trigger/template", status_code=status.HTTP_200_OK, tags=["Webhooks"])
async def trigger_templated_webhook(trigger: TemplatedWebhookTrigger):
    """
    Trigger a webhook using a pre-defined template.
    
    This endpoint allows you to trigger a webhook based on a saved template,
    dynamically substituting values into the template's placeholders.
    
    Parameters:
        trigger: A TemplatedWebhookTrigger object containing:
            - template_id: The ID of the template to use
            - values: A dictionary of values to substitute into the template's placeholders
            - wait_for_response: Whether to wait for and return the response. Defaults to True.
                If set to False, the webhook is sent asynchronously and a simple acknowledgment is returned.
    
    Example values dictionary:
        If your template URL is "https://api.example.com/users/{user_id}/notify",
        your values might be {"user_id": "123", "message": "Hello"}
    
    Example request body:
    ```json
    {
      "template_id": "YOUR_TEMPLATE_ID_HERE",
      "values": {
        "service_id": "T123ABC",
        "username": "darkflib",
        "email": "mike@example.com"
      },
      "wait_for_response": true
    }
    ```
    
    Returns:
        If wait_for_response is True:
            Detailed information about the webhook call, including:
            - webhook_status: "success"
            - webhook_request: Details about the sent request
            - webhook_response: The full response from the target server
        If wait_for_response is False:
            An acknowledgment that the webhook was sent asynchronously:
            - webhook_status: "accepted"
            - message: "Webhook request has been sent asynchronously"
            - webhook_request: Basic details about the sent request
        
    Raises:
        404: If the template with the given ID is not found
        400: If required placeholder values are missing
        500: For general server errors
        503: If the webhook target is unreachable (only when wait_for_response is True)
    """
    template_id = trigger.template_id
    if template_id not in db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    template = db[template_id]
    values = trigger.values

    # Substitute placeholders in URL, headers, and body
    try:
        url = template['url_template'].format(**values)
        
        headers = {k: v.format(**values) for k, v in template['headers_template'].items()}
        
        # A simple recursive function to format strings in a nested dict/list structure
        def format_recursive(item):
            if isinstance(item, str):
                return item.format(**values)
            if isinstance(item, dict):
                return {k: format_recursive(v) for k, v in item.items()}
            if isinstance(item, list):
                return [format_recursive(i) for i in item]
            return item

        body = format_recursive(template['body_template'])
        
        # Ensure body is a dictionary
        if not isinstance(body, dict):
            body = {"data": body}

    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing value for placeholder: {e}"
        )

    return await send_webhook(
        method=template['method'],
        url=url,
        headers=headers,
        json_body=body,
        wait_for_response=trigger.wait_for_response
    )

