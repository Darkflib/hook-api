# Webhook MCP Service

A FastAPI-based service for creating, managing, and triggering templated webhooks for testing and integration purposes.

## Overview

This service provides a RESTful API to:

- **Manage Webhook Templates**: Create, retrieve, update, and delete reusable webhook templates. Templates define the HTTP method, URL, headers, and body structure.

- **Trigger Webhooks**:
  - **Ad-hoc**: Send a one-off webhook with a specified payload.
  - **Templated**: Trigger a webhook based on a saved template, dynamically substituting values into placeholders.
  - **Asynchronous or Synchronous**: Choose whether to wait for the webhook response or fire-and-forget.

Placeholders use Python's `.format()` string syntax (e.g., `{user_id}`).

## Setup and Running the Service

### Prerequisites

- Python 3.8+
- uv

### Create a virtual environment (recommended)

```bash
uv venv
uv sync
```

### Run the application

Save the API code as main.py and run the following command in your terminal:

```bash
chmod +x run.sh
./run.sh
```

### Access the API Docs

Once the server is running, you can access the interactive API documentation (provided by Swagger UI) at:
`http://127.0.0.1:8000/docs`

## API Endpoints

The base URL is `http://127.0.0.1:8000`.

### Template Management

#### POST /templates/

Create a new webhook template.

Example curl command:

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/templates/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
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
}'
```

#### GET /templates/{template_id}

Retrieve a specific template by its ID.

#### GET /templates/

List all created templates.

#### PUT /templates/{template_id}

Update an existing template. The request body is the same as the create endpoint.

#### DELETE /templates/{template_id}

Delete a template.

### Webhook Triggers

#### POST /webhooks/trigger/adhoc

Send a one-off webhook, either synchronously or asynchronously.

Example curl command:

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/webhooks/trigger/adhoc' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "method": "POST",
  "url": "https://httpbin.org/post",
  "headers": {"X-Custom-Header": "adhoc-test"},
  "body": {"message": "Hello, World!"},
  "wait_for_response": true
}'
```

Set `wait_for_response` to `false` to send the webhook asynchronously without waiting for a response.

#### POST /webhooks/trigger/template

Trigger a webhook from a saved template, providing values for its placeholders, either synchronously or asynchronously.

Example curl command:
(Assuming you created the "New User Notification" template from the example above)

```bash
curl -X 'POST' \
  'http://127.0.0.1:8000/webhooks/trigger/template' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "template_id": "YOUR_TEMPLATE_ID_HERE",
  "values": {
    "service_id": "T123ABC",
    "username": "darkflib",
    "email": "mike@example.com"
  },
  "wait_for_response": true
}'
```

This will send a POST request to `https://hooks.example.com/services/T123ABC` with the substituted username and email in the body.

Set `wait_for_response` to `false` to send the webhook asynchronously without waiting for a response.

## MCP (Model Context Protocol) Integration

This service also exposes its webhook triggering capabilities via the Model Context Protocol (MCP) at the `/mcp` endpoint.
This allows MCP-compatible clients (like certain AI models or development tools) to interact with the webhook service programmatically.

### MCP Server Details

- **MCP Endpoint**: `http://127.0.0.1:8000/mcp` (when running locally)
- **Authentication**: None (for this local wrapper)

### Available MCP Tools

The following tools are exposed via the MCP server:

1.  **`trigger_adhoc_webhook_mcp`**
    *   Description: Triggers an ad-hoc (non-templated) webhook. Mirrors the functionality of the `/webhooks/trigger/adhoc` HTTP endpoint.
    *   Input Schema:
        *   `method` (string, required): HTTP method (e.g., "POST", "GET").
        *   `url` (string, required): The complete target URL for the webhook.
        *   `headers` (object, required): Dictionary of HTTP headers.
        *   `body` (object, required): JSON body for the webhook.
        *   `wait_for_response` (boolean, optional, default: `true`): Whether to wait for and return the target server's response.
    *   Output: A dictionary containing the result of the webhook call, similar to the `/webhooks/trigger/adhoc` HTTP endpoint's response. Includes `webhook_status`, `webhook_request`, and `webhook_response` (if `wait_for_response` is true). Returns an `error` object if the call fails.

2.  **`trigger_templated_webhook_mcp`**
    *   Description: Triggers a webhook based on a pre-defined template. Mirrors the functionality of the `/webhooks/trigger/template` HTTP endpoint.
    *   Input Schema:
        *   `template_id` (string, required): The ID of the template to use.
        *   `values` (object, required): Dictionary of values to substitute into the template's placeholders.
        *   `wait_for_response` (boolean, optional, default: `true`): Whether to wait for and return the target server's response.
    *   Output: A dictionary containing the result of the webhook call, similar to the `/webhooks/trigger/template` HTTP endpoint's response. Includes `webhook_status`, `webhook_request`, and `webhook_response` (if `wait_for_response` is true). Returns an `error` object if the template is not found, placeholder values are missing, or the call fails.

### Example MCP Client Usage (Conceptual Python)

```python
# Conceptual example using the mcp-sdk
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def call_adhoc_webhook_via_mcp():
    mcp_service_url = "http://127.0.0.1:8000/mcp" # Ensure the service is running
    async with streamablehttp_client(mcp_service_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            adhoc_params = {
                "method": "POST",
                "url": "https://httpbin.org/post",
                "headers": {"X-Mcp-Test": "true"},
                "body": {"message": "Hello from MCP tool!"},
                "wait_for_response": True
            }
            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_params)
            print(result)

async def call_templated_webhook_via_mcp(template_id: str):
    mcp_service_url = "http://127.0.0.1:8000/mcp" # Ensure the service is running
    async with streamablehttp_client(mcp_service_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            template_params = {
                "template_id": template_id, # Assumes template_id exists
                "values": {"user_id": "mcp-user-789", "custom_param": "test value"},
                "wait_for_response": True
            }
            result = await session.call_tool("trigger_templated_webhook_mcp", template_params)
            print(result)

# To run these examples, you would need to have the mcp sdk installed
# and potentially run them within an asyncio event loop.
# The webhook service (FastAPI app) must be running at http://127.0.0.1:8000.
```

## API Response Format

### Webhook Trigger Response

When triggering a webhook (either ad-hoc or templated), the response format depends on the `wait_for_response` parameter:

#### When wait_for_response is true (default)

```json
{
  "webhook_status": "success",
  "webhook_request": {
    "method": "POST",
    "url": "https://hooks.example.com/services/T123ABC",
    "headers": {
      "X-Event-Type": "user.created",
      "Authorization": "REDACTED"  // Sensitive headers are redacted
    }
  },
  "webhook_response": {
    "status_code": 200,
    "headers": {
      "Content-Type": "application/json",
      "Server": "nginx/1.19.0"
    },
    "body": {
      "success": true,
      "message": "Webhook received"
    }
  }
}
```

#### When wait_for_response is false

```json
{
  "webhook_status": "accepted",
  "message": "Webhook request has been sent asynchronously",
  "webhook_request": {
    "method": "POST",
    "url": "https://hooks.example.com/services/T123ABC"
  }
}
```

## Notes

### Make sure your FastAPI service is running first

```bash
./run.sh
```

### CLI Examples

List all templates:

```bash
python cli.py templates list
```

Create a new template:

```bash
python cli.py templates create \
  --name "GitHub Issue Notifier" \
  --url "https://api.github.com/repos/{owner}/{repo}/issues" \
  --header "Authorization:Bearer {token}" \
  --body '{"title": "New Alert: {alert_name}", "body": "Details: {details}"}'
```

Get the template you just created (using its name):

```bash
python cli.py templates get "GitHub Issue Notifier"
```

Trigger it:

```bash
python cli.py templates trigger "GitHub Issue Notifier" \
  --value "owner=darkflib" \
  --value "repo=webhook-mcp" \
  --value "token=YOUR_GITHUB_TOKEN" \
  --value "alert_name=High CPU" \
  --value "details=Server xyz is on fire"
```

Or send it asynchronously without waiting for a response:

```bash
python cli.py templates trigger "GitHub Issue Notifier" \
  --value "owner=darkflib" \
  --value "repo=webhook-mcp" \
  --value "token=YOUR_GITHUB_TOKEN" \
  --value "alert_name=High CPU" \
  --value "details=Server xyz is on fire" \
  --async
```

Send an ad-hoc webhook:

```bash
python cli.py webhooks adhoc \
  --method POST \
  --url "https://httpbin.org/post" \
  --header "Content-Type:application/json" \
  --header "X-Custom-Header:test" \
  --body '{"message": "Hello from CLI", "source": "webhook-mcp"}'
```

Delete it:

```bash
python cli.py templates delete "GitHub Issue Notifier"
```
