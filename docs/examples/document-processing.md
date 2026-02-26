# Example: Document Processing Pipeline

This walkthrough builds a complete document processing pipeline -- the same one shown in the hof admin UI screenshot. It demonstrates tables, functions, flows with parallel nodes, LLM classification, human-in-the-loop review, and a React UI.

## What We're Building

A pipeline that:

1. Receives a document file
2. Detects the file type (spreadsheet, markdown, PDF, etc.)
3. Extracts and analyzes the content (type-specific processing)
4. Classifies the document using an LLM
5. Matches it to a "dataroom" (a logical grouping)
6. Presents a human review UI for approval
7. Discovers and stores structured attributes from the document

Multiple branches run in parallel where possible.

## Project Setup

```bash
hof new project document-processor
cd document-processor
```

Edit `hof.config.py`:

```python
from hof import Config

config = Config(
    app_name="document-processor",
    database_url="${DATABASE_URL}",
    redis_url="${REDIS_URL}",
    llm_provider="openai",
    llm_model="gpt-5",
    llm_api_key="${OPENAI_API_KEY}",
    admin_username="admin",
    admin_password="${HOF_ADMIN_PASSWORD}",
)
```

## Step 1: Define Tables

```python
# tables/document.py
from hof import Table, Column, ForeignKey, types

class Dataroom(Table):
    """A logical grouping of related documents."""
    name = Column(types.String, required=True, unique=True)
    description = Column(types.Text, nullable=True)

class Document(Table):
    """A processed document with extracted metadata."""
    name = Column(types.String, required=True)
    file_path = Column(types.String, required=True)
    file_type = Column(types.String, nullable=True)
    category = Column(types.String, nullable=True)
    content_summary = Column(types.Text, nullable=True)
    metadata = Column(types.JSON, default={})
    attributes = Column(types.JSON, default={})
    status = Column(types.Enum(
        "pending", "processing", "classified",
        "review_pending", "approved", "rejected"
    ), default="pending")
    dataroom_id = ForeignKey(Dataroom, nullable=True, on_delete="SET NULL")

class DocumentAttribute(Table):
    """A discovered attribute from a document."""
    document_id = ForeignKey(Document, on_delete="CASCADE")
    key = Column(types.String, required=True)
    value = Column(types.Text, required=True)
    source = Column(types.String, nullable=True)
    approved = Column(types.Boolean, default=False)
```

Apply migrations:

```bash
hof db migrate
```

## Step 2: Define Shared Functions

These functions are reusable across flows and callable standalone.

```python
# functions/file_processing.py
from hof import function
import mimetypes

@function(tags=["files"])
def detect_file_type(file_path: str) -> dict:
    """Detect file type from extension and MIME type."""
    ext = file_path.rsplit(".", 1)[-1].lower()
    mime_type, _ = mimetypes.guess_type(file_path)

    type_map = {
        "xlsx": "spreadsheet", "xls": "spreadsheet", "csv": "spreadsheet",
        "md": "markdown", "txt": "markdown",
        "pdf": "pdf",
        "docx": "document", "doc": "document",
        "json": "structured",
    }

    return {
        "file_type": type_map.get(ext, "unknown"),
        "extension": ext,
        "mime_type": mime_type,
        "file_path": file_path,
    }
```

```python
# functions/analysis.py
from hof import function
from tables.document import Document

@function(tags=["analysis"])
def analyze_spreadsheet(file_path: str) -> dict:
    """Analyze Excel spreadsheet structure and extract metadata."""
    import openpyxl
    wb = openpyxl.load_workbook(file_path, read_only=True)
    sheets = wb.sheetnames
    row_counts = {s: wb[s].max_row for s in sheets}
    return {
        "sheets": sheets,
        "row_counts": row_counts,
        "total_rows": sum(row_counts.values()),
    }

@function(tags=["analysis"])
def read_markdown(file_path: str) -> dict:
    """Read markdown file content."""
    with open(file_path) as f:
        content = f.read()
    return {"content": content, "length": len(content)}
```

## Step 3: Define LLM Functions

```python
# functions/classification.py
from hof.llm import prompt
from hof import function
from pydantic import BaseModel

class DocumentCategory(BaseModel):
    category: str
    subcategory: str
    confidence: float
    reasoning: str

@function(tags=["ai", "classification"])
@prompt()
def classify_document_content(content: str, file_type: str) -> DocumentCategory:
    """Classify the following {file_type} document into a category.

    Choose from: finance, legal, technical, marketing, hr, operations, other.
    Also provide a subcategory.

    Document content:
    {content}"""

class DataroomMatch(BaseModel):
    dataroom_name: str
    confidence: float
    reasoning: str

@function(tags=["ai", "matching"])
@prompt()
def match_to_dataroom(
    content_summary: str,
    category: str,
    available_datarooms: list[str],
) -> DataroomMatch:
    """Match this document to the most appropriate dataroom.

    Document category: {category}
    Document summary: {content_summary}

    Available datarooms:
    {available_datarooms}"""
```

## Step 4: Define the Flow

```python
# flows/document_processing.py
from hof import Flow, human_node
from hof.llm import prompt
from pydantic import BaseModel

from tables.document import Document, Dataroom, DocumentAttribute
from functions.file_processing import detect_file_type
from functions.analysis import analyze_spreadsheet, read_markdown
from functions.classification import classify_document_content, match_to_dataroom

pipeline = Flow("document_processing")

# --- Entry node: detect file type ---
pipeline.add_node(detect_file_type)

# --- Branch by file type ---
@pipeline.node(depends_on=[detect_file_type])
def route_by_type(file_type: str, file_path: str, **kwargs) -> dict:
    """Route to the appropriate analysis function based on file type."""
    if file_type == "spreadsheet":
        result = analyze_spreadsheet(file_path)
        summary = f"Spreadsheet with {result['total_rows']} rows across {len(result['sheets'])} sheets"
    elif file_type == "markdown":
        result = read_markdown(file_path)
        summary = result["content"][:500]
    else:
        summary = f"File of type {file_type}"
        result = {}

    doc = Document.create(
        name=file_path.rsplit("/", 1)[-1],
        file_path=file_path,
        file_type=file_type,
        content_summary=summary,
        status="processing",
    )
    return {"document_id": doc.id, "content_summary": summary, "file_type": file_type}

# --- Classify (LLM) ---
@pipeline.node(depends_on=[route_by_type])
def classify(document_id: str, content_summary: str, file_type: str) -> dict:
    """Classify the document using LLM."""
    result = classify_document_content(content=content_summary, file_type=file_type)
    Document.update(document_id, category=result.category, status="classified")
    return {
        "document_id": document_id,
        "category": result.category,
        "subcategory": result.subcategory,
        "confidence": result.confidence,
        "content_summary": content_summary,
    }

# --- Match to dataroom (LLM, runs in parallel with attribute discovery) ---
@pipeline.node(depends_on=[classify])
def match_dataroom(document_id: str, category: str, content_summary: str, **kwargs) -> dict:
    """Match document to a dataroom."""
    datarooms = [d.name for d in Dataroom.query()]
    if not datarooms:
        return {"document_id": document_id, "dataroom_match": None}

    result = match_to_dataroom(
        content_summary=content_summary,
        category=category,
        available_datarooms=datarooms,
    )
    return {
        "document_id": document_id,
        "dataroom_match": result.dataroom_name,
        "match_confidence": result.confidence,
    }

# --- Discover attributes (runs in parallel with dataroom matching) ---
class DiscoveredAttribute(BaseModel):
    key: str
    value: str
    source: str

class AttributeList(BaseModel):
    attributes: list[DiscoveredAttribute]

@pipeline.node(depends_on=[classify])
@prompt()
def discover_attributes(content_summary: str, category: str) -> AttributeList:
    """Extract structured attributes from this {category} document.

    For example, if it's a financial document, extract: date, amount, currency, parties.
    If it's a legal document, extract: parties, effective_date, jurisdiction, contract_type.

    Document content:
    {content_summary}"""

# --- Human review (waits for both parallel branches) ---
@pipeline.node(depends_on=[match_dataroom, discover_attributes])
@human_node(ui="DataroomReview", timeout="48h")
def review_dataroom_match(
    document_id: str,
    dataroom_match: str,
    match_confidence: float,
    attributes: list,
    **kwargs,
) -> dict:
    """Human reviews the dataroom match and discovered attributes."""
    pass

# --- Finalize ---
@pipeline.node(depends_on=[review_dataroom_match])
def finalize(
    document_id: str,
    approved_dataroom: str,
    approved_attributes: list,
    **kwargs,
) -> dict:
    """Store the approved results."""
    if approved_dataroom:
        dataroom = Dataroom.query(filters={"name": approved_dataroom})
        if dataroom:
            Document.update(document_id, dataroom_id=dataroom[0].id, status="approved")

    for attr in approved_attributes:
        DocumentAttribute.create(
            document_id=document_id,
            key=attr["key"],
            value=attr["value"],
            source=attr.get("source", "llm"),
            approved=True,
        )

    return {"document_id": document_id, "status": "approved"}
```

## Step 5: Build the Review UI

```tsx
// ui/components/DataroomReview.tsx
import { useState } from "react";

interface Attribute {
  key: string;
  value: string;
  source: string;
}

interface DataroomReviewProps {
  document_id: string;
  dataroom_match: string | null;
  match_confidence: number;
  attributes: Attribute[];
  onComplete: (result: {
    approved_dataroom: string | null;
    approved_attributes: Attribute[];
  }) => void;
}

export function DataroomReview({
  document_id,
  dataroom_match,
  match_confidence,
  attributes,
  onComplete,
}: DataroomReviewProps) {
  const [selectedDataroom, setSelectedDataroom] = useState(dataroom_match);
  const [editedAttributes, setEditedAttributes] = useState(attributes);

  const toggleAttribute = (index: number) => {
    setEditedAttributes(prev =>
      prev.map((attr, i) =>
        i === index ? { ...attr, _excluded: !attr._excluded } : attr
      )
    );
  };

  const handleSubmit = () => {
    onComplete({
      approved_dataroom: selectedDataroom,
      approved_attributes: editedAttributes.filter(a => !a._excluded),
    });
  };

  return (
    <div style={{ maxWidth: 800, margin: "0 auto", padding: 24 }}>
      <h2>Review Document Classification</h2>
      <p>Document ID: <code>{document_id}</code></p>

      <section>
        <h3>Dataroom Match</h3>
        <p>
          Suggested: <strong>{dataroom_match || "None"}</strong>
          {match_confidence && (
            <span> (confidence: {(match_confidence * 100).toFixed(0)}%)</span>
          )}
        </p>
        <input
          type="text"
          value={selectedDataroom || ""}
          onChange={e => setSelectedDataroom(e.target.value)}
          placeholder="Override dataroom name..."
        />
      </section>

      <section>
        <h3>Discovered Attributes</h3>
        <table>
          <thead>
            <tr><th>Include</th><th>Key</th><th>Value</th><th>Source</th></tr>
          </thead>
          <tbody>
            {editedAttributes.map((attr, i) => (
              <tr key={i} style={{ opacity: attr._excluded ? 0.4 : 1 }}>
                <td>
                  <input
                    type="checkbox"
                    checked={!attr._excluded}
                    onChange={() => toggleAttribute(i)}
                  />
                </td>
                <td>{attr.key}</td>
                <td>{attr.value}</td>
                <td>{attr.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div style={{ marginTop: 24, display: "flex", gap: 12 }}>
        <button onClick={handleSubmit}>
          Approve & Continue
        </button>
        <button onClick={() => onComplete({ approved_dataroom: null, approved_attributes: [] })}>
          Reject All
        </button>
      </div>
    </div>
  );
}
```

## Step 6: Run It

```bash
# Start the dev server
hof dev

# Trigger the pipeline
hof flow run document_processing --input '{"file_path": "/data/quarterly-report.xlsx"}'

# Monitor execution
hof flow list document_processing --status running

# Check execution details
hof flow get <execution-id> --nodes
```

Open `http://localhost:8000/admin` to see:

- The flow DAG visualization (like the screenshot)
- Execution progress with per-node status
- The human review UI when the flow reaches the review node
- Table browser for documents, datarooms, and attributes

## Flow DAG Visualization

The admin UI renders the flow as a visual DAG:

```
detect_file_type
       |
  route_by_type
       |
    classify
      / \
     /   \
match_dataroom  discover_attributes
     \   /
      \ /
review_dataroom_match  (human-in-the-loop)
       |
    finalize
```

The `match_dataroom` and `discover_attributes` nodes run in parallel because they both depend only on `classify` and not on each other.
