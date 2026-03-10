# LLM Integration

hof-engine provides first-class LLM support via the [`llm-markdown`](https://pypi.org/project/llm-markdown/) library. Define LLM-powered functions using decorators with structured outputs, multimodal inputs, and observability.

## Setup

Configure your LLM provider in `hof.config.py`:

```python
from hof import Config

config = Config(
    app_name="my-app",
    database_url="postgresql://localhost:5432/myapp",
    redis_url="redis://localhost:6379/0",
    llm_provider="openai",
    llm_model="gpt-4o",
    llm_api_key="${OPENAI_API_KEY}",
)
```

## Basic Usage

```python
from hof.llm import prompt

@prompt()
def summarize(text: str) -> str:
    """Summarize the following text in 2-3 sentences:

    {text}"""
```

Three rules (from `llm-markdown`):

1. The **docstring** is the prompt. Use `{param}` to interpolate function arguments.
2. The **return type** controls the output format. `-> str` gives plain text. `-> MyModel` gives validated structured output.
3. **`Image` parameters** are attached as vision inputs automatically.

## Structured Outputs

Return a Pydantic model and the response is validated automatically:

```python
from pydantic import BaseModel
from hof.llm import prompt

class Category(BaseModel):
    name: str
    confidence: float
    reasoning: str

@prompt()
def classify(content: str) -> Category:
    """Classify the following document into a category.
    Return the category name, your confidence (0-1), and your reasoning.

    Document:
    {content}"""
```

The library generates a JSON schema from the Pydantic model and uses the provider's native structured output (e.g. OpenAI's `response_format`). If the provider doesn't support it, it falls back to JSON prompting automatically.

`List[...]` and `Dict[...]` work the same way:

```python
from typing import List

@prompt()
def list_steps(task: str) -> List[str]:
    """List the steps to complete this task: {task}"""
```

## Multimodal (Images)

Use `Image` typed parameters for vision inputs:

```python
from hof.llm import prompt
from llm_markdown import Image

@prompt()
def describe_image(image: Image, question: str) -> str:
    """Answer this question about the image: {question}"""

result = describe_image(
    image=Image("https://example.com/chart.png"),
    question="What trend does this chart show?",
)
```

`Image` accepts URLs, base64 strings, or data URIs. Use `List[Image]` for multiple images.

## Using LLM in Flow Nodes

LLM decorators compose with flow node decorators:

```python
from hof import Flow
from hof.llm import prompt

pipeline = Flow("analysis")

@pipeline.node
@prompt()
def analyze_sentiment(text: str) -> SentimentResult:
    """Analyze the sentiment of this text: {text}"""

@pipeline.node(depends_on=[analyze_sentiment])
def store_result(name: str, confidence: float, reasoning: str) -> dict:
    return {"stored": True}
```

## Streaming

```python
@prompt(stream=True)
def tell_story(topic: str) -> str:
    """Tell a short story about {topic}."""

for chunk in tell_story("a robot learning to paint"):
    print(chunk, end="", flush=True)
```

## LLM Options

```python
@prompt(
    stream=False,               # Enable streaming responses
    provider=custom_provider,   # Override the default provider
    langfuse_metadata={...},    # Metadata for Langfuse observability
)
```

## Custom Providers

Subclass `LLMProvider` from `llm-markdown` for custom backends:

```python
from llm_markdown.providers import LLMProvider

class MyProvider(LLMProvider):
    def complete(self, messages, **kwargs):
        ...  # return response string

    async def complete_async(self, messages, **kwargs):
        ...  # return response string

    # Optional -- enables native structured output
    def complete_structured(self, messages, schema):
        ...  # return parsed dict
```

Register in config:

```python
config = Config(
    llm_provider=MyProvider(api_key="..."),
)
```

## Observability with Langfuse

hof integrates with Langfuse for LLM observability (optional):

```python
config = Config(
    langfuse_public_key="${LANGFUSE_PUBLIC_KEY}",
    langfuse_secret_key="${LANGFUSE_SECRET_KEY}",
)
```

When configured, all LLM calls are automatically logged to Langfuse with prompt/response content, token usage, latency, and metadata.
