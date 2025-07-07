# main.py
# The entry point for the FastAPI application.

from fastapi import FastAPI, HTTPException, status
from typing import List, Dict, Any
import uuid
import contextlib

# Import shared components from app.core
from app.core import (
    db,
    send_webhook,
    WebhookTemplate,
    WebhookTemplateCreate,
    AdhocWebhookTrigger,
    TemplatedWebhookTrigger,
)
from app.mcp_wrapper import mcp_server # Import the MCP server

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp_server.session_manager.run())
        yield

app = FastAPI(
    title="Webhook MCP Service",
    description="An API for creating, managing, and triggering templated webhooks, with MCP support.",
    version="0.1.0",
    lifespan=lifespan # Add the lifespan manager
)

# Mount the MCP server
app.mount("/mcp", mcp_server.streamable_http_app())

# --- API Endpoints ---
# Note: send_webhook, db, and Pydantic models are now imported from app.core

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

