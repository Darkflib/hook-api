from mcp.server.fastmcp import FastMCP
# Import from app.core now
from app.core import AdhocWebhookTrigger, TemplatedWebhookTrigger, send_webhook, db, HTTPException

mcp_server = FastMCP("WebhookMCP")

@mcp_server.tool()
async def trigger_adhoc_webhook_mcp(
    method: str, url: str, headers: dict, body: dict, wait_for_response: bool = True
) -> dict:
    """
    MCP tool to trigger an ad-hoc webhook.
    Mirrors the /webhooks/trigger/adhoc endpoint.
    """
    trigger = AdhocWebhookTrigger(
        method=method,
        url=url,
        headers=headers,
        body=body,
        wait_for_response=wait_for_response,
    )
    try:
        return await send_webhook(
            method=trigger.method,
            url=trigger.url,
            headers=trigger.headers,
            json_body=trigger.body,
            wait_for_response=trigger.wait_for_response,
        )
    except HTTPException as e:
        # MCP tools should ideally not raise HTTPExceptions directly.
        # Convert to a dict that can be serialized.
        return {"error": {"status_code": e.status_code, "detail": e.detail}}
    except Exception as e:
        return {"error": {"status_code": 500, "detail": str(e)}}

@mcp_server.tool()
async def trigger_templated_webhook_mcp(
    template_id: str, values: dict, wait_for_response: bool = True
) -> dict:
    """
    MCP tool to trigger a templated webhook.
    Mirrors the /webhooks/trigger/template endpoint.
    """
    trigger = TemplatedWebhookTrigger(
        template_id=template_id, values=values, wait_for_response=wait_for_response
    )
    if trigger.template_id not in db:
        return {
            "error": {
                "status_code": 404,
                "detail": f"Template with id {trigger.template_id} not found.",
            }
        }

    template = db[trigger.template_id]

    try:
        url = template['url_template'].format(**trigger.values)
        headers = {
            k: v.format(**trigger.values)
            for k, v in template['headers_template'].items()
        }

        def format_recursive(item):
            if isinstance(item, str):
                return item.format(**trigger.values)
            if isinstance(item, dict):
                return {k: format_recursive(v) for k, v in item.items()}
            if isinstance(item, list):
                return [format_recursive(i) for i in item]
            return item

        body = format_recursive(template['body_template'])
        if not isinstance(body, dict):
            body = {"data": body} # Ensure body is a dict

    except KeyError as e:
        return {
            "error": {
                "status_code": 400,
                "detail": f"Missing value for placeholder: {e}",
            }
        }
    except Exception as e: # Catch other formatting errors
        return {
            "error": {
                "status_code": 400,
                "detail": f"Error during template formatting: {str(e)}",
            }
        }

    try:
        return await send_webhook(
            method=template['method'],
            url=url,
            headers=headers,
            json_body=body,
            wait_for_response=trigger.wait_for_response,
        )
    except HTTPException as e:
        return {"error": {"status_code": e.status_code, "detail": e.detail}}
    except Exception as e:
        return {"error": {"status_code": 500, "detail": str(e)}}
