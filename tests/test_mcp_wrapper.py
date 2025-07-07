import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from app.main import app, db
from app.mcp_wrapper import mcp_server
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.streamable_http import streamablehttp_client
import uuid

# Use TestClient for synchronous tests of FastAPI routes
# For MCP, we will use an async client against the running app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(autouse=True)
def clear_db_before_each_test():
    db.clear()
    yield # This is where the test runs
    db.clear()


@pytest.mark.asyncio
async def test_mcp_trigger_adhoc_webhook(client: TestClient):
    """Test the MCP adhoc webhook tool."""
    # The MCP client needs the server to be running.
    # We'll use the streamablehttp_client to connect to our FastAPI app.
    # The base_url needs to point to a running instance of the app.
    # For these tests, we'll assume the app is running on http://127.0.0.1:8000
    # The `client` fixture (TestClient) is used for setup (e.g. creating templates via API)

    APP_BASE_URL = "http://127.0.0.1:8000" # Assume server is running here for MCP tests

    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Prepare adhoc webhook data
            adhoc_data = {
                "method": "POST",
                "url": "https://httpbin.org/post", # Using httpbin for reliable external testing
                "headers": {"X-Test-Header": "mcp-adhoc"},
                "body": {"test_key": "test_value_adhoc"},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" not in result, f"MCP tool returned an error: {result.get('error')}"
            assert result.get("webhook_status") == "success"
            assert result["webhook_request"]["method"] == "POST"
            assert result["webhook_request"]["url"] == "https://httpbin.org/post"
            # httpbin.org/post echoes back the JSON body under the 'json' key
            assert result["webhook_response"]["body"]["json"] == adhoc_data["body"]
            assert result["webhook_response"]["body"]["headers"]["X-Test-Header"] == "mcp-adhoc"

@pytest.mark.asyncio
async def test_mcp_trigger_templated_webhook(client: TestClient):
    """Test the MCP templated webhook tool."""

    # 1. Create a template via the standard API first
    template_name = f"test-template-{uuid.uuid4()}"
    template_data = {
        "name": template_name,
        "method": "POST",
        "url_template": "https://httpbin.org/post?id={user_id}",
        "headers_template": {"X-Template-Test": "mcp-{env}"},
        "body_template": {"message": "Hello {name} from {source}", "user_id": "{user_id}"},
    }
    response = client.post("/templates/", json=template_data)
    assert response.status_code == 201
    template_id = response.json()["id"]

    APP_BASE_URL = "http://127.0.0.1:8000"

    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Prepare templated webhook trigger data
            trigger_data = {
                "template_id": template_id,
                "values": {"user_id": "123", "env": "test", "name": "MCP User", "source": "mcp-test"},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_templated_webhook_mcp", trigger_data)

            assert result is not None
            assert "error" not in result, f"MCP tool returned an error: {result.get('error')}"
            assert result.get("webhook_status") == "success"

            expected_url = template_data["url_template"].format(**trigger_data["values"])
            expected_body = {
                "message": f"Hello {trigger_data['values']['name']} from {trigger_data['values']['source']}",
                "user_id": trigger_data['values']['user_id']
            }
            expected_header_value = template_data["headers_template"]["X-Template-Test"].format(**trigger_data["values"])

            assert result["webhook_request"]["url"] == expected_url
            # httpbin.org/post echoes back the JSON body under the 'json' key
            assert result["webhook_response"]["body"]["json"] == expected_body
            assert result["webhook_response"]["body"]["headers"]["X-Template-Test"] == expected_header_value

@pytest.mark.asyncio
async def test_mcp_trigger_templated_webhook_template_not_found(client: TestClient):
    """Test MCP templated webhook tool when template ID does not exist."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            non_existent_template_id = str(uuid.uuid4())
            trigger_data = {
                "template_id": non_existent_template_id,
                "values": {"some_key": "some_value"},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_templated_webhook_mcp", trigger_data)

            assert result is not None
            assert "error" in result
            assert result["error"]["status_code"] == 404
            assert non_existent_template_id in result["error"]["detail"]

@pytest.mark.asyncio
async def test_mcp_trigger_templated_webhook_missing_placeholder(client: TestClient):
    """Test MCP templated webhook tool when a placeholder value is missing."""
    template_name = f"test-template-missing-{uuid.uuid4()}"
    template_data = {
        "name": template_name,
        "url_template": "https://httpbin.org/get?name={name}&id={user_id}", # Requires name and user_id
    }
    response = client.post("/templates/", json=template_data)
    assert response.status_code == 201
    template_id = response.json()["id"]

    APP_BASE_URL = "http://127.0.0.1:8000"

    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            trigger_data = {
                "template_id": template_id,
                "values": {"name": "MCP User"}, # Missing user_id
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_templated_webhook_mcp", trigger_data)

            assert result is not None
            assert "error" in result
            assert result["error"]["status_code"] == 400
            assert "Missing value for placeholder" in result["error"]["detail"]
            assert "user_id" in result["error"]["detail"]

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_fire_and_forget(client: TestClient):
    """Test MCP adhoc webhook with wait_for_response=False."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            adhoc_data = {
                "method": "POST",
                "url": "https://httpbin.org/delay/3", # Use a delay to ensure it's async
                "headers": {},
                "body": {"key": "value"},
                "wait_for_response": False,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "accepted"
            assert "Webhook request has been sent asynchronously" in result.get("message", "")
            assert result["webhook_request"]["url"] == adhoc_data["url"]

# Example of how to list tools (optional, but good for verifying MCP server setup)
@pytest.mark.asyncio
async def test_list_mcp_tools(client: TestClient):
    """Verify that the MCP tools are listed by the server."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_response = await session.list_tools()

            assert tools_response is not None
            tool_names = [tool.name for tool in tools_response.tools]

            assert "trigger_adhoc_webhook_mcp" in tool_names
            assert "trigger_templated_webhook_mcp" in tool_names

            adhoc_tool = next(t for t in tools_response.tools if t.name == "trigger_adhoc_webhook_mcp")
            assert adhoc_tool.description == "MCP tool to trigger an ad-hoc webhook.\nMirrors the /webhooks/trigger/adhoc endpoint."

            templated_tool = next(t for t in tools_response.tools if t.name == "trigger_templated_webhook_mcp")
            assert templated_tool.description == "MCP tool to trigger a templated webhook.\nMirrors the /webhooks/trigger/template endpoint."

            # Check input schema for one of the tools (optional detailed check)
            # This part can be quite verbose if you want to check all arguments
            # For example, checking 'trigger_adhoc_webhook_mcp'
            adhoc_input_schema = adhoc_tool.inputSchema
            assert "method" in adhoc_input_schema["properties"]
            assert "url" in adhoc_input_schema["properties"]
            assert "headers" in adhoc_input_schema["properties"]
            assert "body" in adhoc_input_schema["properties"]
            assert "wait_for_response" in adhoc_input_schema["properties"]
            assert adhoc_input_schema["properties"]["wait_for_response"]["default"] == True
            assert "method" in adhoc_input_schema["required"]
            assert "url" in adhoc_input_schema["required"]
            assert "headers" in adhoc_input_schema["required"]
            assert "body" in adhoc_input_schema["required"]

# To run these tests, you'll need pytest and pytest-asyncio
# pip install pytest pytest-asyncio
# Then run: pytest
# Ensure your FastAPI app is configured to run for testing (e.g., using TestClient)
# Also ensure httpbin.org is accessible for external calls.
# If httpbin.org is not preferred, mock the httpx.AsyncClient.request call.
# For these tests, we are making actual HTTP calls to httpbin.org.
# If the main FastAPI app has dependencies (like a database) that need setup/teardown for tests,
# ensure those are handled by fixtures (like the clear_db_before_each_test example).
# The `client` fixture provided by `fastapi.testclient.TestClient` handles app startup/shutdown.
# The `streamablehttp_client` connects to this test server instance.
