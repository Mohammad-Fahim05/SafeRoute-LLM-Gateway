"""Unit tests for Phase 9.3 Unified Tool / Function-Calling Normalization."""

import json
import pytest
from pydantic import ValidationError

from app.api.schemas import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionNamedFunction,
    ChatCompletionNamedToolChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionTool,
    ChatMessage,
    FunctionCall,
    FunctionDefinition,
)
from app.core.errors import UnsupportedParameterError
from app.providers.base import model_supports_tools
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider


def test_valid_tool_definitions_pass_validation():
    """Requirement 2: Valid tool definitions pass schema validation."""
    tool = ChatCompletionTool(
        type="function",
        function=FunctionDefinition(
            name="get_current_weather",
            description="Get the current weather for a location.",
            parameters={
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City and state, e.g. London, UK"},
                    "format": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location"],
            },
        ),
    )
    assert tool.type == "function"
    assert tool.function.name == "get_current_weather"

    req = ChatCompletionRequest(
        model="mock-tool-call",
        messages=[ChatMessage(role="user", content="What is the weather in London?")],
        tools=[tool],
        tool_choice="auto",
    )
    assert req.tools is not None
    assert len(req.tools) == 1
    assert req.tool_choice == "auto"


def test_duplicate_tool_names_rejected():
    """Requirement 3: Duplicate tool names are rejected."""
    tool1 = ChatCompletionTool(
        type="function",
        function=FunctionDefinition(name="fetch_data", description="Tool 1"),
    )
    tool2 = ChatCompletionTool(
        type="function",
        function=FunctionDefinition(name="fetch_data", description="Tool 2 duplicate"),
    )
    with pytest.raises(ValidationError, match="Duplicate tool name 'fetch_data'"):
        ChatCompletionRequest(
            model="mock-tool-call",
            messages=[ChatMessage(role="user", content="Run tool")],
            tools=[tool1, tool2],
        )


def test_invalid_json_schemas_rejected():
    """Requirement 4: Invalid JSON Schemas (e.g. non-object root) are rejected."""
    # Invalid root type: 'array' instead of 'object'
    with pytest.raises(ValidationError, match="Root schema type for function parameters must be 'object'"):
        FunctionDefinition(
            name="invalid_schema",
            parameters={"type": "array", "items": {"type": "string"}},
        )

    # Invalid function name with illegal symbols
    with pytest.raises(ValidationError, match="Invalid function name"):
        FunctionDefinition(
            name="invalid func name with spaces!",
            parameters={"type": "object"},
        )


def test_oversized_tool_definitions_rejected():
    """Requirement 5: Oversized tool definitions (>32KB parameter schema) are rejected."""
    # Build schema larger than 32KB
    huge_properties = {f"prop_{i}": {"type": "string", "description": "x" * 200} for i in range(200)}
    with pytest.raises(ValidationError, match="exceeds maximum limit of 32768 bytes"):
        FunctionDefinition(
            name="oversized_tool",
            parameters={"type": "object", "properties": huge_properties},
        )

    # More than 32 tools rejected
    tools = [
        ChatCompletionTool(type="function", function=FunctionDefinition(name=f"tool_{i}"))
        for i in range(33)
    ]
    with pytest.raises(ValidationError, match="exceeds maximum allowed limit of 32"):
        ChatCompletionRequest(
            model="mock-tool-call",
            messages=[ChatMessage(role="user", content="Hi")],
            tools=tools,
        )


def test_named_tool_choice_validation():
    """Validates named tool choice refers to a defined tool."""
    tool1 = ChatCompletionTool(type="function", function=FunctionDefinition(name="get_weather"))
    # Named tool choice for existing tool passes
    req = ChatCompletionRequest(
        model="mock-tool-call",
        messages=[ChatMessage(role="user", content="Hi")],
        tools=[tool1],
        tool_choice=ChatCompletionNamedToolChoice(
            type="function",
            function=ChatCompletionNamedFunction(name="get_weather"),
        ),
    )
    assert req.tool_choice is not None

    # Named tool choice for non-existent tool fails
    with pytest.raises(ValidationError, match="not in provided tools"):
        ChatCompletionRequest(
            model="mock-tool-call",
            messages=[ChatMessage(role="user", content="Hi")],
            tools=[tool1],
            tool_choice=ChatCompletionNamedToolChoice(
                type="function",
                function=ChatCompletionNamedFunction(name="unknown_tool"),
            ),
        )


def test_tool_message_validation():
    """Requirement 14: Validates tool role requirements (tool_call_id and content)."""
    # Tool message without tool_call_id fails
    with pytest.raises(ValidationError, match="must specify a non-empty 'tool_call_id'"):
        ChatMessage(role="tool", content="15 degrees")

    # Tool message without content fails
    with pytest.raises(ValidationError, match="Message with role 'tool' must specify 'content'"):
        ChatMessage(role="tool", tool_call_id="call_123")

    # Valid tool message passes
    valid_tool_msg = ChatMessage(role="tool", tool_call_id="call_123", content="15 degrees Celsius")
    assert valid_tool_msg.role == "tool"
    assert valid_tool_msg.tool_call_id == "call_123"


def test_model_supports_tools_classification():
    """Requirement 8 & 12: Model tool support classification is accurate."""
    assert model_supports_tools("llama3.1:8b") is True
    assert model_supports_tools("llama3.2:1b") is True
    assert model_supports_tools("mistral") is True
    assert model_supports_tools("qwen2.5-coder:7b-instruct-q4_K_M") is True
    assert model_supports_tools("mock-tool-call") is True

    # Non-tool models and removed external models
    assert model_supports_tools("phi3:mini") is False
    assert model_supports_tools("mock-malformed") is False
    assert model_supports_tools("some-no-tools-model") is False
    assert model_supports_tools("claude-sonnet-4-6") is False
    assert model_supports_tools("gemini-3.8-flash") is False


@pytest.mark.anyio
async def test_mock_tool_calling_deterministic():
    """Requirement 9: Mock tool calls work deterministically."""
    provider = MockProvider()
    tool = ChatCompletionTool(
        type="function",
        function=FunctionDefinition(
            name="get_stock_price",
            description="Get current stock price",
            parameters={"type": "object", "properties": {"ticker": {"type": "string"}}},
        ),
    )
    req = ChatCompletionRequest(
        model="mock-tool-call",
        messages=[ChatMessage(role="user", content="What is AAPL trading at?")],
        tools=[tool],
        tool_choice="auto",
    )
    res = await provider.complete(req)
    assert res.choices[0].finish_reason == "tool_calls"
    assert res.choices[0].message.tool_calls is not None
    assert len(res.choices[0].message.tool_calls) == 1
    tc = res.choices[0].message.tool_calls[0]
    assert tc.function.name == "get_stock_price"
    args = json.loads(tc.function.arguments)
    assert "ticker" in args


@pytest.mark.anyio
async def test_mock_multiple_tool_calls_preserves_ordering():
    """Requirement 10: Multiple tool calls preserve ordering and IDs."""
    provider = MockProvider()
    tools = [
        ChatCompletionTool(type="function", function=FunctionDefinition(name="get_weather")),
        ChatCompletionTool(type="function", function=FunctionDefinition(name="get_time")),
    ]
    req = ChatCompletionRequest(
        model="mock-tool-call-multiple",
        messages=[ChatMessage(role="user", content="Weather in London and Paris?")],
        tools=tools,
    )
    res = await provider.complete(req)
    assert res.choices[0].finish_reason == "tool_calls"
    tcs = res.choices[0].message.tool_calls
    assert tcs is not None
    assert len(tcs) == 2
    assert tcs[0].id == "call_mock_multi_1"
    assert tcs[0].function.name == "get_weather"
    assert tcs[1].id == "call_mock_multi_2"
    assert tcs[1].function.name == "get_time"


@pytest.mark.anyio
async def test_mock_malformed_arguments_safety():
    """Requirement 11: Malformed provider arguments produce a safe result."""
    provider = MockProvider()
    tool = ChatCompletionTool(type="function", function=FunctionDefinition(name="query_db"))
    req = ChatCompletionRequest(
        model="mock-tool-call-malformed-args",
        messages=[ChatMessage(role="user", content="Run query")],
        tools=[tool],
    )
    res = await provider.complete(req)
    # The malformed argument string is preserved safely as raw string without raising unhandled exception
    tc = res.choices[0].message.tool_calls[0]
    assert tc.function.arguments == '{"location": "London", "days": '


@pytest.mark.anyio
async def test_ollama_rejects_unsupported_model_for_tools():
    """Requirement 8 & 12: Ollama provider explicitly rejects tool requests on unsupported models."""
    provider = OllamaProvider()
    tool = ChatCompletionTool(type="function", function=FunctionDefinition(name="search"))
    req = ChatCompletionRequest(
        model="phi3:mini",
        messages=[ChatMessage(role="user", content="Search this")],
        tools=[tool],
    )
    with pytest.raises(UnsupportedParameterError, match="does not support tool calling in Ollama adapter"):
        await provider.complete(req)
