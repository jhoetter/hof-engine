# Functions

Functions are reusable backend operations exposed as API endpoints and CLI commands. They are the building blocks of your application -- usable standalone, in flows, from the UI, or via CLI.

## Defining a Function

```python
from hof import function

@function
def classify_document(document_id: str, model: str = "default") -> dict:
    """Classify a document into a category."""
    # Your logic here
    return {"category": "finance", "confidence": 0.95}
```

The `@function` decorator registers the function in the hof registry. It becomes:

- An API endpoint: `POST /api/functions/classify_document`
- A CLI command: `hof fn classify_document --document-id=abc --model=custom`
- Importable and callable from flows, other functions, or any Python code

## Type Annotations

Function parameters and return types are used for:

1. **API schema generation** -- request/response validation via Pydantic
2. **CLI argument parsing** -- automatic flag generation from parameter names
3. **Flow data passing** -- type checking between connected nodes

Supported parameter types:

```python
from typing import Optional
from pydantic import BaseModel

# Primitives
@function
def example(
    name: str,              # Required string
    count: int = 10,        # Optional int with default
    active: bool = True,    # Optional bool
    score: float = 0.0,     # Optional float
) -> dict:
    ...

# Pydantic models for complex inputs/outputs
class ClassificationResult(BaseModel):
    category: str
    confidence: float
    tags: list[str]

@function
def classify(document_id: str) -> ClassificationResult:
    ...
```

## Async Functions

```python
@function
async def fetch_and_process(url: str) -> dict:
    """Async functions are natively supported."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    return {"status": response.status_code}
```

## Using Tables in Functions

```python
from hof import function
from tables.document import Document

@function
def process_document(document_id: str) -> dict:
    doc = Document.get(document_id)
    # ... processing logic ...
    Document.update(document_id, status="processed")
    return {"processed": True}
```

## Function Options

```python
@function(
    name="custom-name",         # Override the auto-generated name
    description="...",          # Override docstring for API docs
    tags=["documents", "ai"],   # Tags for organization in admin UI
    timeout=300,                # Max execution time in seconds (default: 60)
    retries=3,                  # Auto-retry on failure
)
def my_function(x: str) -> dict:
    ...
```

## Auto-Generated API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/functions/{name}` | Execute the function |
| `GET` | `/api/functions` | List all registered functions |
| `GET` | `/api/functions/{name}/schema` | Get input/output schema |

Request body matches function parameters:

```json
POST /api/functions/classify_document
{
    "document_id": "abc-123",
    "model": "custom"
}
```

Response:

```json
{
    "result": {"category": "finance", "confidence": 0.95},
    "duration_ms": 142,
    "function": "classify_document"
}
```

## CLI Usage

```bash
# Call a function
hof fn classify_document --document-id=abc-123

# List all functions
hof fn list

# Show function schema
hof fn schema classify_document

# Call with JSON input
hof fn classify_document --json '{"document_id": "abc-123"}'
```

## Error Handling

```python
from hof import function, HofError

@function
def risky_operation(document_id: str) -> dict:
    doc = Document.get(document_id)
    if doc is None:
        raise HofError("Document not found", status_code=404)
    return {"ok": True}
```

`HofError` is returned as a structured error response with the appropriate HTTP status code.
