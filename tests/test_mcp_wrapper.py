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

# Additional comprehensive unit tests for MCP wrapper

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_invalid_method(client: TestClient):
    """Test MCP adhoc webhook with invalid HTTP method."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            adhoc_data = {
                "method": "INVALID_METHOD",
                "url": "https://httpbin.org/post",
                "headers": {},
                "body": {"test": "data"},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" in result
            assert result["error"]["status_code"] == 400
            assert "Invalid HTTP method" in result["error"]["detail"]

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_invalid_url(client: TestClient):
    """Test MCP adhoc webhook with malformed URL."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            adhoc_data = {
                "method": "POST",
                "url": "not-a-valid-url",
                "headers": {},
                "body": {"test": "data"},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" in result
            assert result["error"]["status_code"] == 400
            assert "Invalid URL format" in result["error"]["detail"]

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_get_method(client: TestClient):
    """Test MCP adhoc webhook with GET method."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            adhoc_data = {
                "method": "GET",
                "url": "https://httpbin.org/get?test=value",
                "headers": {"User-Agent": "MCP-Test"},
                "body": {},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            assert result["webhook_request"]["method"] == "GET"
            assert result["webhook_response"]["body"]["headers"]["User-Agent"] == "MCP-Test"

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_put_method(client: TestClient):
    """Test MCP adhoc webhook with PUT method."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            test_data = {"updated_field": "new_value", "id": 123}
            adhoc_data = {
                "method": "PUT",
                "url": "https://httpbin.org/put",
                "headers": {"Content-Type": "application/json"},
                "body": test_data,
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            assert result["webhook_request"]["method"] == "PUT"
            assert result["webhook_response"]["body"]["json"] == test_data

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_delete_method(client: TestClient):
    """Test MCP adhoc webhook with DELETE method."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            adhoc_data = {
                "method": "DELETE",
                "url": "https://httpbin.org/delete",
                "headers": {"Authorization": "Bearer fake-token"},
                "body": {},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            assert result["webhook_request"]["method"] == "DELETE"
            assert result["webhook_response"]["body"]["headers"]["Authorization"] == "Bearer fake-token"

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_empty_body(client: TestClient):
    """Test MCP adhoc webhook with empty body."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            adhoc_data = {
                "method": "POST",
                "url": "https://httpbin.org/post",
                "headers": {},
                "body": {},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            assert result["webhook_response"]["body"]["json"] == {}

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_large_payload(client: TestClient):
    """Test MCP adhoc webhook with large payload."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Create a reasonably large payload
            large_data = {"data": "x" * 1000, "items": [{"id": i, "value": f"item_{i}"} for i in range(100)]}
            adhoc_data = {
                "method": "POST",
                "url": "https://httpbin.org/post",
                "headers": {"Content-Type": "application/json"},
                "body": large_data,
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            assert result["webhook_response"]["body"]["json"] == large_data

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_special_characters(client: TestClient):
    """Test MCP adhoc webhook with special characters in payload."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            special_data = {
                "unicode": "こんにちは世界",
                "emojis": "🚀🌟💫",
                "special_chars": "!@#$%^&*()_+-=[]{}|;:,.<>?",
                "quotes": 'He said "Hello" and she replied \'Hi\'',
                "newlines": "Line 1\nLine 2\r\nLine 3",
            }
            adhoc_data = {
                "method": "POST",
                "url": "https://httpbin.org/post",
                "headers": {"Content-Type": "application/json; charset=utf-8"},
                "body": special_data,
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            assert result["webhook_response"]["body"]["json"] == special_data

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_missing_required_fields(client: TestClient):
    """Test MCP adhoc webhook with missing required fields."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Missing method field
            adhoc_data = {
                "url": "https://httpbin.org/post",
                "headers": {},
                "body": {"test": "data"},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" in result
            assert result["error"]["status_code"] == 400
            assert "method" in result["error"]["detail"]

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_connection_error(client: TestClient):
    """Test MCP adhoc webhook with connection error."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            adhoc_data = {
                "method": "POST",
                "url": "https://nonexistent-domain-12345.com/webhook",
                "headers": {},
                "body": {"test": "data"},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            assert "error" in result
            assert result["error"]["status_code"] == 500
            assert "connection" in result["error"]["detail"].lower()

@pytest.mark.asyncio
async def test_mcp_templated_webhook_with_nested_values(client: TestClient):
    """Test MCP templated webhook with nested template values."""
    template_name = f"test-nested-{uuid.uuid4()}"
    template_data = {
        "name": template_name,
        "method": "POST",
        "url_template": "https://httpbin.org/post",
        "headers_template": {"X-User": "{user.name}", "X-Team": "{user.team}"},
        "body_template": {
            "user_info": {
                "name": "{user.name}",
                "email": "{user.email}",
                "team": "{user.team}"
            },
            "action": "{action}",
            "timestamp": "{timestamp}"
        },
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
                "values": {
                    "user.name": "John Doe",
                    "user.email": "john@example.com",
                    "user.team": "Engineering",
                    "action": "login",
                    "timestamp": "2023-01-01T12:00:00Z"
                },
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_templated_webhook_mcp", trigger_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            
            expected_body = {
                "user_info": {
                    "name": "John Doe",
                    "email": "john@example.com",
                    "team": "Engineering"
                },
                "action": "login",
                "timestamp": "2023-01-01T12:00:00Z"
            }
            assert result["webhook_response"]["body"]["json"] == expected_body
            assert result["webhook_response"]["body"]["headers"]["X-User"] == "John Doe"
            assert result["webhook_response"]["body"]["headers"]["X-Team"] == "Engineering"

@pytest.mark.asyncio
async def test_mcp_templated_webhook_with_numeric_values(client: TestClient):
    """Test MCP templated webhook with numeric template values."""
    template_name = f"test-numeric-{uuid.uuid4()}"
    template_data = {
        "name": template_name,
        "method": "POST",
        "url_template": "https://httpbin.org/post",
        "body_template": {
            "user_id": "{user_id}",
            "score": "{score}",
            "price": "{price}",
            "count": "{count}"
        },
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
                "values": {
                    "user_id": "123",
                    "score": "95.5",
                    "price": "29.99",
                    "count": "42"
                },
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_templated_webhook_mcp", trigger_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            
            expected_body = {
                "user_id": "123",
                "score": "95.5",
                "price": "29.99",
                "count": "42"
            }
            assert result["webhook_response"]["body"]["json"] == expected_body

@pytest.mark.asyncio
async def test_mcp_templated_webhook_empty_values(client: TestClient):
    """Test MCP templated webhook with empty values."""
    template_name = f"test-empty-{uuid.uuid4()}"
    template_data = {
        "name": template_name,
        "method": "POST",
        "url_template": "https://httpbin.org/post",
        "body_template": {
            "name": "{name}",
            "description": "{description}",
            "optional": "{optional}"
        },
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
                "values": {
                    "name": "",
                    "description": "",
                    "optional": ""
                },
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_templated_webhook_mcp", trigger_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            
            expected_body = {
                "name": "",
                "description": "",
                "optional": ""
            }
            assert result["webhook_response"]["body"]["json"] == expected_body

@pytest.mark.asyncio
async def test_mcp_templated_webhook_fire_and_forget(client: TestClient):
    """Test MCP templated webhook with fire-and-forget mode."""
    template_name = f"test-async-{uuid.uuid4()}"
    template_data = {
        "name": template_name,
        "method": "POST",
        "url_template": "https://httpbin.org/delay/2",
        "body_template": {"message": "Async webhook test"},
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
                "values": {},
                "wait_for_response": False,
            }

            result = await session.call_tool("trigger_templated_webhook_mcp", trigger_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "accepted"
            assert "asynchronously" in result.get("message", "")

@pytest.mark.asyncio
async def test_mcp_templated_webhook_invalid_template_id_format(client: TestClient):
    """Test MCP templated webhook with invalid template ID format."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            trigger_data = {
                "template_id": "invalid-uuid-format",
                "values": {},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_templated_webhook_mcp", trigger_data)

            assert result is not None
            assert "error" in result
            assert result["error"]["status_code"] == 400
            assert "invalid" in result["error"]["detail"].lower()

@pytest.mark.asyncio
async def test_mcp_session_reuse(client: TestClient):
    """Test that MCP session can be reused for multiple calls."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # First call
            adhoc_data1 = {
                "method": "GET",
                "url": "https://httpbin.org/get?call=1",
                "headers": {},
                "body": {},
                "wait_for_response": True,
            }
            result1 = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data1)
            assert result1["webhook_status"] == "success"

            # Second call with same session
            adhoc_data2 = {
                "method": "GET",
                "url": "https://httpbin.org/get?call=2",
                "headers": {},
                "body": {},
                "wait_for_response": True,
            }
            result2 = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data2)
            assert result2["webhook_status"] == "success"

            # Verify calls were different
            assert result1["webhook_response"]["body"]["args"]["call"] == "1"
            assert result2["webhook_response"]["body"]["args"]["call"] == "2"

@pytest.mark.asyncio
async def test_mcp_tools_schema_validation(client: TestClient):
    """Test MCP tools have proper schema validation."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_response = await session.list_tools()

            # Check adhoc webhook tool schema
            adhoc_tool = next(t for t in tools_response.tools if t.name == "trigger_adhoc_webhook_mcp")
            schema = adhoc_tool.inputSchema
            
            # Verify required fields
            assert set(schema["required"]) == {"method", "url", "headers", "body"}
            
            # Verify property types
            assert schema["properties"]["method"]["type"] == "string"
            assert schema["properties"]["url"]["type"] == "string"
            assert schema["properties"]["headers"]["type"] == "object"
            assert schema["properties"]["body"]["type"] == "object"
            assert schema["properties"]["wait_for_response"]["type"] == "boolean"
            assert schema["properties"]["wait_for_response"]["default"] == True

            # Check templated webhook tool schema
            templated_tool = next(t for t in tools_response.tools if t.name == "trigger_templated_webhook_mcp")
            schema = templated_tool.inputSchema
            
            # Verify required fields
            assert set(schema["required"]) == {"template_id", "values"}
            
            # Verify property types
            assert schema["properties"]["template_id"]["type"] == "string"
            assert schema["properties"]["values"]["type"] == "object"
            assert schema["properties"]["wait_for_response"]["type"] == "boolean"
            assert schema["properties"]["wait_for_response"]["default"] == True

@pytest.mark.asyncio
async def test_mcp_concurrent_requests(client: TestClient):
    """Test MCP with concurrent requests."""
    import asyncio
    
    APP_BASE_URL = "http://127.0.0.1:8000"
    
    async def make_request(session, call_id):
        adhoc_data = {
            "method": "GET",
            "url": f"https://httpbin.org/get?call={call_id}",
            "headers": {},
            "body": {},
            "wait_for_response": True,
        }
        result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)
        return result, call_id
    
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Make 3 concurrent requests
            tasks = [make_request(session, i) for i in range(3)]
            results = await asyncio.gather(*tasks)
            
            # Verify all requests succeeded
            for result, call_id in results:
                assert result["webhook_status"] == "success"
                assert result["webhook_response"]["body"]["args"]["call"] == str(call_id)

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_timeout_handling(client: TestClient):
    """Test MCP adhoc webhook timeout handling."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Use a very long delay to test timeout (if implemented)
            adhoc_data = {
                "method": "GET",
                "url": "https://httpbin.org/delay/10",
                "headers": {},
                "body": {},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)
            
            # Result should either succeed or timeout gracefully
            assert result is not None
            if "error" in result:
                assert "timeout" in result["error"]["detail"].lower()
            else:
                assert result["webhook_status"] == "success"

@pytest.mark.asyncio
async def test_mcp_adhoc_webhook_status_codes(client: TestClient):
    """Test MCP adhoc webhook with different HTTP status codes."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Test 404 status code
            adhoc_data = {
                "method": "GET",
                "url": "https://httpbin.org/status/404",
                "headers": {},
                "body": {},
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_adhoc_webhook_mcp", adhoc_data)

            assert result is not None
            # Should handle non-2xx status codes gracefully
            if "error" in result:
                assert "404" in str(result["error"]["detail"])
            else:
                assert result["webhook_status"] == "success"
                assert result["webhook_response"]["status_code"] == 404

@pytest.mark.asyncio
async def test_mcp_templated_webhook_complex_json_body(client: TestClient):
    """Test MCP templated webhook with complex JSON body structures."""
    template_name = f"test-complex-{uuid.uuid4()}"
    template_data = {
        "name": template_name,
        "method": "POST",
        "url_template": "https://httpbin.org/post",
        "body_template": {
            "metadata": {
                "version": "1.0",
                "source": "mcp-test"
            },
            "user": {
                "id": "{user_id}",
                "profile": {
                    "name": "{name}",
                    "preferences": {
                        "theme": "{theme}",
                        "notifications": True
                    }
                }
            },
            "actions": [
                {
                    "type": "login",
                    "timestamp": "{timestamp}"
                },
                {
                    "type": "view",
                    "page": "{page}"
                }
            ]
        },
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
                "values": {
                    "user_id": "12345",
                    "name": "Jane Doe",
                    "theme": "dark",
                    "timestamp": "2023-01-01T12:00:00Z",
                    "page": "dashboard"
                },
                "wait_for_response": True,
            }

            result = await session.call_tool("trigger_templated_webhook_mcp", trigger_data)

            assert result is not None
            assert "error" not in result
            assert result.get("webhook_status") == "success"
            
            response_json = result["webhook_response"]["body"]["json"]
            assert response_json["metadata"]["version"] == "1.0"
            assert response_json["user"]["id"] == "12345"
            assert response_json["user"]["profile"]["name"] == "Jane Doe"
            assert response_json["user"]["profile"]["preferences"]["theme"] == "dark"
            assert response_json["actions"][0]["timestamp"] == "2023-01-01T12:00:00Z"
            assert response_json["actions"][1]["page"] == "dashboard"

# Additional edge case tests for comprehensive coverage
@pytest.mark.asyncio
async def test_mcp_tools_error_handling_edge_cases(client: TestClient):
    """Test various edge cases for MCP tools error handling."""
    APP_BASE_URL = "http://127.0.0.1:8000"
    async with streamablehttp_client(f"{APP_BASE_URL}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Test calling non-existent tool
            try:
                result = await session.call_tool("non_existent_tool", {})
                # Should either raise an exception or return error
                if result is not None:
                    assert "error" in result
            except Exception as e:
                # Exception is acceptable for non-existent tools
                assert "not found" in str(e).lower() or "unknown" in str(e).lower()

            # Test with None arguments
            try:
                result = await session.call_tool("trigger_adhoc_webhook_mcp", None)
                if result is not None:
                    assert "error" in result
            except Exception:
                # Exception is acceptable for None arguments
                pass

            # Test with empty arguments
            result = await session.call_tool("trigger_adhoc_webhook_mcp", {})
            assert result is not None
            assert "error" in result
            assert result["error"]["status_code"] == 400

