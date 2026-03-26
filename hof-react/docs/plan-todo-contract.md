# Plan checklist progress (long-term contract)

## Wire

During **`plan_execute`**, the engine may yield NDJSON rows:

```json
{ "type": "plan_todo_update", "done_indices": [0, 1] }
```

These are emitted when the model calls **`hof_builtin_update_plan_todo_state`** (`hof/agent/builtin_tools.py`) and the stream loop forwards them (`hof/agent/stream.py`).

**Intended semantics:** `done_indices` are **0-based** positions in the plan’s `- [ ]` task list (top line = `0`), **cumulative** “all rows complete so far” unless the model sends deltas only (the UI merges either way).

## Client (`@hof-engine/react`)

1. **`resolvePlanTodoUpdateWireEvent`** (`src/agent/planTodoStream.ts`)  
   Normalizes wire values against the **approved plan markdown** using **`normalizePlanTodoWireIndices`** (`planMarkdownTodos.ts`) so common mistakes (e.g. `1…n` instead of `0…n-1`) still drive the checklist.

2. **`mergePlanTodoDoneIndices`**  
   Merges each update into React state used by **`HofAgentPlanCard`**.

3. **`applyStreamEvent`** (`hofAgentChatModel.ts`)  
   Appends **`plan_step_progress`** blocks for the transcript; receives the **same normalized** event the context passes in.

4. **`PlanStepProgressRow`** (`HofAgentChatBlocks.tsx`)  
   Renders **one badge per index** in each block (no single aggregated line for multiple todos).

## Engine / model

- System prompt: **`_AGENT_CHAT_PLAN_EXECUTE_SUFFIX`** in `hof/agent/stream.py` — requires calling the builtin **during** execution, not only at the end.
- Changing wire shape requires updating **`resolvePlanTodoUpdateWireEvent`**, **`HofStreamEvent` handling**, and this document.
