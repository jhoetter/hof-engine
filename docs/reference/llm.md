# LLM Integration

hof-engine provides first-class LLM support via the `llm-markdown` library. Define LLM-powered functions using decorators with structured outputs, multimodal inputs, and observability.

## Setup

Configure your LLM provider in `hof.config.py`:

```python
from hof import Config

config = Config(
    app_name="my-app",
    database_url="postgresql://localhost:5432/myapp",
    redis_url="redis://localhost:6379/0",
    llm_provider="openai",
    llm_model="gpt-5",
    llm_api_key="${OPENAI_API_KEY}",  # Reads from environment variable
)
```

## Basic Usage

```python
from hof.llm import llm

@llm()
def summarize(text: str) -> str:
    f"""
    Summarize the following text in 2-3 sentences:

    {text}
    """
```

The function's docstring (or triple-quoted f-string) is the prompt. Parameters are interpolated. The return type defines the expected output format.

## Structured Outputs

Use Pydantic models for structured LLM responses:

```python
from pydantic import BaseModel
from hof.llm import llm

class Category(BaseModel):
    name: str
    confidence: float
    reasoning: str

@llm(reasoning_first=True)
def classify(content: str) -> Category:
    f"""
    Classify the following document into a category.
    Return the category name, your confidence (0-1), and your reasoning.

    Document:
    {content}
    """
```

The `reasoning_first=True` option enables chain-of-thought: the LLM reasons in `<reasoning>` tags before producing the structured output.

## Multimodal (Images)

```python
from hof.llm import llm

@llm()
def describe_image(image_url: str) -> str:
    f"""
    Describe what you see in this image:

    !image[{image_url}]
    """
```

The `!image[url_or_base64]` syntax embeds images in the prompt. Supports URLs and base64-encoded images.

## Using LLM in Flow Nodes

LLM decorators compose with flow node decorators:

```python
from hof import Flow
from hof.llm import llm

pipeline = Flow("analysis")

@pipeline.node
@llm(reasoning_first=True)
def analyze_sentiment(text: str) -> SentimentResult:
    f"""
    Analyze the sentiment of this text:
    {text}
    """

@pipeline.node(depends_on=[analyze_sentiment])
def store_result(name: str, confidence: float, reasoning: str) -> dict:
    # Receives the structured output from the LLM node
    return {"stored": True}
```

## LLM Options

```python
@llm(
    reasoning_first=True,       # Enable chain-of-thought reasoning
    stream=False,               # Enable streaming responses
    max_retries=2,              # Retry on parsing failures
    provider=custom_provider,   # Override the default provider
)
```

## Custom Providers

Implement the `LLMProvider` interface for custom backends:

```python
from hof.llm import LLMProvider

class MyProvider(LLMProvider):
    def query(self, messages, **kwargs):
        # Call your LLM backend
        return response_text

    def query_structured(self, messages, schema, **kwargs):
        # Call with structured output
        return parsed_result

    def supports_structured_output(self):
        return True
```

Register in config:

```python
config = Config(
    llm_provider=MyProvider(api_key="..."),
)
```

## Observability

hof integrates with Langfuse for LLM observability (optional):

```python
config = Config(
    langfuse_public_key="${LANGFUSE_PUBLIC_KEY}",
    langfuse_secret_key="${LANGFUSE_SECRET_KEY}",
)
```

When configured, all LLM calls are automatically logged to Langfuse with:

- Prompt and response content
- Token usage and cost
- Latency
- Metadata (flow name, node name, execution ID)
