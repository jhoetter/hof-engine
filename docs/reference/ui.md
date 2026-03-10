# User Interfaces

hof-engine lets you define React components that are compiled and served natively. Components can be standalone pages, human-in-the-loop interfaces for flows, or reusable widgets.

## Project Structure

```
ui/
  components/         # Reusable React components
    ReviewPanel.tsx
    DataTable.tsx
  pages/              # Full pages (routed by filename)
    index.tsx         # → /app/
    dashboard.tsx     # → /app/dashboard
    settings.tsx      # → /app/settings
  package.json        # Auto-managed; add npm dependencies here
```

The framework manages Vite configuration. You write standard React/TypeScript -- no build config needed.

## Writing Components

```tsx
// ui/components/ReviewPanel.tsx
import { useState } from "react";

interface ReviewPanelProps {
  document: { id: string; name: string; content: string };
  classification: { category: string; confidence: number };
  onComplete: (result: { approved: boolean; notes: string }) => void;
}

export function ReviewPanel({ document, classification, onComplete }: ReviewPanelProps) {
  const [notes, setNotes] = useState("");

  return (
    <div className="review-panel">
      <h2>Review: {document.name}</h2>
      <p>Category: {classification.category} ({(classification.confidence * 100).toFixed(0)}%)</p>
      <pre>{document.content}</pre>
      <textarea
        value={notes}
        onChange={e => setNotes(e.target.value)}
        placeholder="Add review notes..."
      />
      <div className="actions">
        <button onClick={() => onComplete({ approved: true, notes })}>
          Approve
        </button>
        <button onClick={() => onComplete({ approved: false, notes })}>
          Reject
        </button>
      </div>
    </div>
  );
}
```

## Writing Pages

Pages are file-system routed. Each `.tsx` file in `ui/pages/` becomes a route.

```tsx
// ui/pages/index.tsx
import { useHofTable } from "@hof-engine/react";

export default function HomePage() {
  const { data: tasks, loading } = useHofTable("task", {
    filter: { done: false },
    orderBy: "-created_at",
    limit: 20,
  });

  if (loading) return <p>Loading...</p>;

  return (
    <div>
      <h1>Open Tasks</h1>
      <ul>
        {tasks.map(task => (
          <li key={task.id}>{task.title}</li>
        ))}
      </ul>
    </div>
  );
}
```

## @hof-engine/react Hooks

The `@hof-engine/react` npm package provides hooks for interacting with the hof backend.

### useHofTable

Query and mutate table data:

```tsx
import { useHofTable } from "@hof-engine/react";

const {
  data,           // Array of records
  loading,        // Boolean
  error,          // Error object or null
  refetch,        // () => void -- re-fetch data
  create,         // (record) => Promise -- create a record
  update,         // (id, fields) => Promise -- update a record
  remove,         // (id) => Promise -- delete a record
} = useHofTable("document", {
  filter: { status: "pending" },
  orderBy: "-created_at",
  limit: 10,
  offset: 0,
});
```

### useHofFunction

Call backend functions:

```tsx
import { useHofFunction } from "@hof-engine/react";

const {
  call,           // (params) => Promise<result>
  loading,        // Boolean
  error,          // Error object or null
  result,         // Last result
} = useHofFunction("classify_document");

// Usage
const result = await call({ document_id: "abc-123" });
```

### useHofFlow

Trigger and monitor flow executions:

```tsx
import { useHofFlow } from "@hof-engine/react";

const {
  run,            // (input) => Promise<execution>
  executions,     // Array of recent executions
  loading,
} = useHofFlow("document_processing");
```

### useHofNode

For human-in-the-loop components -- provides the node context and submission handler:

```tsx
import { useHofNode } from "@hof-engine/react";

export function ReviewPanel() {
  const { input, onComplete, execution } = useHofNode();
  // input = data passed to this human node
  // onComplete = function to submit human response
  // execution = current flow execution metadata

  return (
    <div>
      <pre>{JSON.stringify(input, null, 2)}</pre>
      <button onClick={() => onComplete({ approved: true })}>
        Approve
      </button>
    </div>
  );
}
```

## Adding npm Dependencies

The `ui/package.json` is auto-generated on `hof dev`. To add dependencies:

```bash
cd ui && npm install chart.js react-chartjs-2
```

Or edit `ui/package.json` directly. The Vite dev server picks up changes automatically.

## Styling

Use any CSS approach:

- Plain CSS files (imported in components)
- CSS Modules (`*.module.css`)
- Tailwind CSS (add to `ui/package.json` and configure in `ui/tailwind.config.js`)

The admin UI uses its own isolated styles and does not conflict with user styles.

## How UI Integrates with Flows

When a flow reaches a `@human_node`, the framework:

1. Pauses the flow execution
2. Creates a pending action in the database
3. The admin UI (or a custom page) shows the pending action
4. The specified React component is rendered with the node's input data as props
5. When the human calls `onComplete(result)`, the result is sent to the API
6. The flow resumes with the human's response as the node's output
