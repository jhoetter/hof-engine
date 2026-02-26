# Flows

Flows are directed acyclic graphs (DAGs) of nodes that define multi-step workflows. Nodes can be fully automated, use LLMs, or require human input. Independent nodes execute in parallel automatically.

## Defining a Flow

```python
from hof import Flow

document_flow = Flow("document_processing")
```

## Adding Nodes

Nodes are Python functions decorated with `@flow.node`. Each node receives input, performs work, and returns output that downstream nodes consume.

```python
@document_flow.node
def detect_type(file_path: str) -> dict:
    """Detect file type from extension."""
    ext = file_path.rsplit(".", 1)[-1]
    return {"file_type": ext, "file_path": file_path}

@document_flow.node(depends_on=[detect_type])
def extract_content(file_path: str, file_type: str) -> dict:
    """Extract text content from the file."""
    content = read_file(file_path)
    return {"content": content}
```

### How `depends_on` Works

- Nodes without `depends_on` are entry nodes -- they receive the flow's initial input.
- Nodes with `depends_on` receive the merged outputs of their dependencies.
- Independent nodes (no dependency relationship) run in parallel via Celery.

```python
flow = Flow("parallel_example")

@flow.node
def step_a(input_data: str) -> dict:
    return {"a_result": "from A"}

@flow.node
def step_b(input_data: str) -> dict:
    return {"b_result": "from B"}

# step_c depends on both a and b -- it waits for both to complete
# and receives {"a_result": "from A", "b_result": "from B"}
@flow.node(depends_on=[step_a, step_b])
def step_c(a_result: str, b_result: str) -> dict:
    return {"combined": f"{a_result} + {b_result}"}
```

## Node Options

```python
@flow.node(
    depends_on=[other_node],    # Upstream dependencies
    retries=3,                  # Retry on failure (default: 0)
    retry_delay=60,             # Seconds between retries (default: 30)
    timeout=300,                # Max execution time in seconds (default: 60)
    tags=["extraction"],        # Tags for filtering in admin UI
)
def my_node(data: str) -> dict:
    ...
```

## Human-in-the-Loop Nodes

Human nodes pause the flow and present a React UI for human input. The flow resumes when the human submits their response.

```python
from hof import Flow, human_node

review_flow = Flow("review_pipeline")

@review_flow.node
def prepare_review(document_id: str) -> dict:
    doc = Document.get(document_id)
    return {"document": doc.to_dict(), "suggestions": generate_suggestions(doc)}

@review_flow.node(depends_on=[prepare_review])
@human_node(
    ui="ReviewPanel",           # React component name (from ui/components/)
    timeout="24h",              # How long to wait for human input
    assignee_field="reviewer",  # Optional: field in input that specifies the assignee
)
def human_review(document: dict, suggestions: list) -> dict:
    # The function body is not executed -- the framework renders the UI instead.
    # The return type defines what the human's response must contain.
    pass

@review_flow.node(depends_on=[human_review])
def apply_review(document: dict, approved: bool, notes: str) -> dict:
    if approved:
        Document.update(document["id"], status="approved")
    return {"applied": True}
```

The corresponding React component:

```tsx
// ui/components/ReviewPanel.tsx
import { useHofNode } from "@hof-engine/react";

export function ReviewPanel({ document, suggestions, onComplete }) {
  const [notes, setNotes] = useState("");

  return (
    <div>
      <h2>Review: {document.name}</h2>
      <ul>
        {suggestions.map((s, i) => <li key={i}>{s}</li>)}
      </ul>
      <textarea value={notes} onChange={e => setNotes(e.target.value)} />
      <button onClick={() => onComplete({ approved: true, notes })}>
        Approve
      </button>
      <button onClick={() => onComplete({ approved: false, notes })}>
        Reject
      </button>
    </div>
  );
}
```

## LLM Nodes

Combine `@flow.node` with `@llm` from hof's LLM integration:

```python
from hof import Flow
from hof.llm import llm
from pydantic import BaseModel

class Category(BaseModel):
    name: str
    confidence: float

classify_flow = Flow("classification")

@classify_flow.node
@llm(reasoning_first=True)
def classify_document(content: str) -> Category:
    f"""
    Classify the following document into a category.

    Document content:
    {content}
    """
```

The `@llm` decorator turns the function's docstring into an LLM prompt. The return type (`Category`) defines the structured output schema.

## Triggering Flows

### From CLI

```bash
hof flow run document_processing --input '{"file_path": "/data/report.pdf"}'
```

### From API

```
POST /api/flows/document_processing/run
{"file_path": "/data/report.pdf"}
```

### From Python Code

```python
from flows.document_processing import document_flow

execution = document_flow.run(file_path="/data/report.pdf")
print(execution.id)  # UUID of the execution
```

### From Another Flow (Sub-flows)

```python
from hof import Flow

parent = Flow("parent_pipeline")

@parent.node
def trigger_child(data: dict) -> dict:
    from flows.child_pipeline import child_flow
    execution = child_flow.run(**data)
    return {"child_execution_id": execution.id}
```

## Monitoring Executions

### CLI

```bash
hof flow list document_processing                  # List all executions
hof flow list document_processing --status=running # Filter by status
hof flow get <execution-id>                        # Get execution details
hof flow get <execution-id> --nodes                # Show per-node status
hof flow cancel <execution-id>                     # Cancel a running execution
hof flow retry <execution-id>                      # Retry a failed execution
```

### API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/flows/{name}/run` | Trigger a new execution |
| `GET` | `/api/flows/{name}/executions` | List executions |
| `GET` | `/api/flows/executions/{id}` | Get execution details |
| `POST` | `/api/flows/executions/{id}/cancel` | Cancel execution |
| `POST` | `/api/flows/executions/{id}/retry` | Retry failed execution |
| `POST` | `/api/flows/executions/{id}/nodes/{node}/submit` | Submit human input |

## Execution States

| State | Description |
|-------|-------------|
| `pending` | Created, waiting to be picked up by a worker |
| `running` | At least one node is executing |
| `waiting_for_human` | Paused at a human node, awaiting input |
| `completed` | All nodes finished successfully |
| `failed` | A node failed (after exhausting retries) |
| `cancelled` | Manually cancelled by user |

## Reusing Nodes Across Flows

Nodes are plain functions -- define them once, use them in multiple flows:

```python
# functions/shared_nodes.py
from hof import function

@function
def extract_text(file_path: str) -> dict:
    """Extract text from a file. Reusable across flows."""
    return {"text": read_file(file_path)}

# flows/pipeline_a.py
from hof import Flow
from functions.shared_nodes import extract_text

pipeline_a = Flow("pipeline_a")
pipeline_a.add_node(extract_text)  # Reuse the same function as a node

# flows/pipeline_b.py
from hof import Flow
from functions.shared_nodes import extract_text

pipeline_b = Flow("pipeline_b")
pipeline_b.add_node(extract_text)  # Same function, different flow
```
