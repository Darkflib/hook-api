from typing import Any, Dict, List, Union

def format_recursive(item: Union[str, dict, list], values: Dict[str, Any]) -> Union[str, dict, list]:
    """Recursively format strings in nested dict/list structures."""
    if isinstance(item, str):
        return item.format(**values)
    if isinstance(item, dict):
        return {k: format_recursive(v, values) for k, v in item.items()}
    if isinstance(item, list):
        return [format_recursive(i, values) for i in item]
    return item
