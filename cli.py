# cli.py
# A CLI for interacting with the Webhook MCP Service API.

import click
import httpx
import json
import sys
from typing import Dict, Any, Optional, List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.prompt import Confirm

# --- Configuration ---
API_BASE_URL = "http://127.0.0.1:8000"
console = Console()

# --- API Client Helper ---
# A small wrapper around httpx to handle common tasks like error handling.

class ApiClient:
    """A simple client for the Webhook MCP Service API."""
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.Client()

    def _request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """Internal request method."""
        try:
            response = self.client.request(method, f"{self.base_url}{endpoint}", **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            # Handle API-level errors (4xx, 5xx)
            try:
                error_details = e.response.json().get("detail", e.response.text)
            except json.JSONDecodeError:
                error_details = e.response.text
            console.print(f"[bold red]API Error ({e.response.status_code}):[/] {error_details}")
            sys.exit(1)
        except httpx.RequestError as e:
            # Handle network-level errors
            console.print(f"[bold red]Connection Error:[/] Could not connect to {e.request.url}. Is the service running?")
            sys.exit(1)

    def get_templates(self) -> List[Dict[str, Any]]:
        """Fetch all templates."""
        return self._request("GET", "/templates/").json()

    def get_template(self, template_id: str) -> Dict[str, Any]:
        """Fetch a single template by ID."""
        return self._request("GET", f"/templates/{template_id}").json()
        
    def find_template_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find a template by its unique name."""
        templates = self.get_templates()
        for t in templates:
            if t['name'] == name:
                return t
        return None

    def create_template(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new template."""
        return self._request("POST", "/templates/", json=data).json()

    def delete_template(self, template_id: str) -> None:
        """Delete a template by ID."""
        self._request("DELETE", f"/templates/{template_id}")
    
    def trigger_template(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger a templated webhook."""
        return self._request("POST", "/webhooks/trigger/template", json=data).json()
        
    def trigger_adhoc(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger an ad-hoc webhook."""
        return self._request("POST", "/webhooks/trigger/adhoc", json=data).json()

# Instantiate the client
api = ApiClient(API_BASE_URL)

# --- CLI Command Structure ---

@click.group()
def cli():
    """A CLI for the Webhook MCP Service."""
    pass

@cli.group()
def templates():
    """Manage webhook templates."""
    pass

@cli.group()
def webhooks():
    """Send webhooks."""
    pass

def _get_template_by_id_or_name(id_or_name: str) -> Dict[str, Any]:
    """Helper to resolve a template from either its ID or name."""
    # Try as ID first
    if len(id_or_name) == 36: # UUIDs have a fixed length
        try:
            template = api.get_template(id_or_name)
            if template:
                return template
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
    
    # Fallback to searching by name
    template = api.find_template_by_name(id_or_name)
    if not template:
        console.print(f"[bold red]Error:[/] Template '{id_or_name}' not found.")
        sys.exit(1)
    return template

# --- Template Commands ---

@templates.command("list")
def list_templates():
    """List all available webhook templates."""
    with console.status("[cyan]Fetching templates..."):
        all_templates = api.get_templates()

    if not all_templates:
        console.print("[yellow]No templates found.[/]")
        return

    table = Table(title="Webhook Templates", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Method")
    table.add_column("URL Template")

    for t in all_templates:
        table.add_row(t['id'], t['name'], t['method'], t['url_template'])
    
    console.print(table)

@templates.command("get")
@click.argument("id_or_name")
def get_template(id_or_name: str):
    """Get details for a specific template by its ID or name."""
    with console.status(f"[cyan]Fetching template '{id_or_name}'..."):
        template = _get_template_by_id_or_name(id_or_name)

    # Pretty print JSON content
    headers_syntax = Syntax(json.dumps(template['headers_template'], indent=2), "json", theme="monokai", line_numbers=False)
    body_syntax = Syntax(json.dumps(template['body_template'], indent=2), "json", theme="monokai", line_numbers=False)

    display_panel = Panel(
        f"[bold]ID:[/] {template['id']}\n"
        f"[bold]Method:[/] {template['method']}\n"
        f"[bold]URL Template:[/] {template['url_template']}\n\n"
        f"[bold]Headers Template:[/]\n"
        f"{headers_syntax.code}\n\n"
        f"[bold]Body Template:[/]\n"
        f"{body_syntax.code}",
        title=f"[bold cyan]Template: {template['name']}[/]",
        border_style="green",
        expand=True
    )
    console.print(display_panel)

@templates.command("create")
@click.option("--name", required=True, help="A unique, human-readable name for the template.")
@click.option("--url", "url_template", required=True, help="URL template, e.g., 'https://api.example.com/users/{user_id}'.")
@click.option("--method", default="POST", show_default=True, help="HTTP method.")
@click.option("--header", "headers", multiple=True, help="Headers as 'Key:Value'. Can be used multiple times.")
@click.option("--body", "body_template_str", help="JSON body as a string. e.g., '{\"key\": \"{value}\"}'.")
def create_template(name, url_template, method, headers, body_template_str):
    """Create a new webhook template."""
    headers_template = dict(h.split(":", 1) for h in headers)
    body_template = json.loads(body_template_str) if body_template_str else {}

    payload = {
        "name": name,
        "url_template": url_template,
        "method": method,
        "headers_template": headers_template,
        "body_template": body_template
    }

    with console.status("[cyan]Creating template..."):
        new_template = api.create_template(payload)
    
    console.print(f"[bold green]Success![/] Template '{new_template['name']}' created with ID: {new_template['id']}")

@templates.command("delete")
@click.argument("id_or_name")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt.")
def delete_template(id_or_name: str, yes: bool):
    """Delete a template by its ID or name."""
    template = _get_template_by_id_or_name(id_or_name)
    
    if not yes:
        if not Confirm.ask(f"Are you sure you want to delete the template '[bold]{template['name']}[/]'?"):
            console.print("Deletion cancelled.")
            return

    with console.status(f"[cyan]Deleting template '{template['name']}'..."):
        api.delete_template(template['id'])
    
    console.print(f"[bold green]Success![/] Template '{template['name']}' has been deleted.")

@templates.command("trigger")
@click.argument("id_or_name")
@click.option("--value", "values", multiple=True, help="Values for placeholders as 'key=value'. Can be used multiple times.")
@click.option("--async", "async_mode", is_flag=True, help="Send the webhook asynchronously without waiting for a response.")
def trigger_template(id_or_name: str, values: List[str], async_mode: bool):
    """Trigger a webhook from a template."""
    template = _get_template_by_id_or_name(id_or_name)
    
    # Parse key=value pairs
    template_values = dict(v.split("=", 1) for v in values)
    
    payload = {
        "template_id": template['id'],
        "values": template_values,
        "wait_for_response": not async_mode
    }

    console.print(f"Triggering template '[bold]{template['name']}[/]'...")
    with console.status("[cyan]Sending webhook..."):
        result = api.trigger_template(payload)

    # Handle different response formats based on async or sync mode
    if async_mode:
        console.print(Panel(
            f"[bold]Status:[/] {result['webhook_status']}\n"
            f"[bold]Message:[/] {result['message']}\n"
            f"[bold]Method:[/] {result['webhook_request']['method']}\n"
            f"[bold]URL:[/] {result['webhook_request']['url']}",
            title="[bold green]Webhook Request Sent Asynchronously[/]",
            border_style="green"
        ))
    else:
        # Format the response body for display
        try:
            response_body = Syntax(
                json.dumps(result['webhook_response']['body'], indent=2), 
                "json", 
                theme="monokai"
            )
        except (TypeError, KeyError):
            # Handle case where response body is text or has a different structure
            response_body = result['webhook_response'].get('body', 'No response body')
        
        console.print(Panel(
            f"[bold]Status:[/] {result['webhook_status']}\n"
            f"[bold]HTTP Status Code:[/] {result['webhook_response']['status_code']}\n\n"
            f"[bold]Response Body:[/]\n"
            f"{response_body.code}",
            title="[bold green]Webhook Response[/]",
            border_style="green"
        ))


# --- Webhook Commands ---

@webhooks.command("adhoc")
@click.option("--method", default="POST", show_default=True, help="HTTP method.")
@click.option("--url", required=True, help="Target URL for the webhook.")
@click.option("--header", "headers", multiple=True, help="Headers as 'Key:Value'. Can be used multiple times.")
@click.option("--body", "body_str", help="JSON body as a string. e.g., '{\"key\": \"value\"}'.")
@click.option("--async", "async_mode", is_flag=True, help="Send the webhook asynchronously without waiting for a response.")
def trigger_adhoc(method: str, url: str, headers: List[str], body_str: str, async_mode: bool):
    """Send an ad-hoc webhook request."""
    headers_dict = dict(h.split(":", 1) for h in headers) if headers else {}
    body = json.loads(body_str) if body_str else {}

    payload = {
        "method": method,
        "url": url,
        "headers": headers_dict,
        "body": body,
        "wait_for_response": not async_mode
    }

    console.print(f"Sending ad-hoc webhook to '[bold]{url}[/]'...")
    with console.status("[cyan]Sending webhook..."):
        result = api.trigger_adhoc(payload)

    # Handle different response formats based on async or sync mode
    if async_mode:
        console.print(Panel(
            f"[bold]Status:[/] {result['webhook_status']}\n"
            f"[bold]Message:[/] {result['message']}\n"
            f"[bold]Method:[/] {result['webhook_request']['method']}\n"
            f"[bold]URL:[/] {result['webhook_request']['url']}",
            title="[bold green]Webhook Request Sent Asynchronously[/]",
            border_style="green"
        ))
    else:
        # Format the response body for display
        try:
            response_body = Syntax(
                json.dumps(result['webhook_response']['body'], indent=2), 
                "json", 
                theme="monokai"
            )
        except (TypeError, KeyError):
            # Handle case where response body is text or has a different structure
            response_body = result['webhook_response'].get('body', 'No response body')
        
        console.print(Panel(
            f"[bold]Status:[/] {result['webhook_status']}\n"
            f"[bold]HTTP Status Code:[/] {result['webhook_response']['status_code']}\n\n"
            f"[bold]Response Body:[/]\n"
            f"{response_body.code}",
            title="[bold green]Webhook Response[/]",
            border_style="green"
        ))


if __name__ == "__main__":
    cli()
