"""Unit tests for Pydantic request and response schemas."""

import pytest
from pydantic import ValidationError

from app.api.schemas import ChatCompletionRequest, ChatMessage


def test_valid_chat_message():
    """Verify standard valid chat messages for system, user, and assistant."""
    for role in ["system", "user", "assistant"]:
        msg = ChatMessage(role=role, content="Hello, gateway!")
        assert msg.role == role
        assert msg.content == "Hello, gateway!"


def test_chat_message_rejects_empty_content():
    """Ensure empty or whitespace-only messages are rejected."""
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="")

    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="   ")


def test_chat_message_rejects_unsupported_role():
    """Ensure roles other than system, user, and assistant are rejected."""
    for invalid_role in ["function", "tool", "admin"]:
        with pytest.raises(ValidationError):
            ChatMessage(role=invalid_role, content="Test content")


def test_chat_message_forbids_extra_fields():
    """Ensure extra attributes like name or function_call are rejected."""
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="Hi", name="Alice")  # type: ignore


def test_valid_chat_completion_request():
    """Verify valid request instantiates correctly with defaults."""
    req = ChatCompletionRequest(
        model="mock-model",
        messages=[ChatMessage(role="user", content="Hello")],
        temperature=0.7,
        max_completion_tokens=100,
    )
    assert req.model == "mock-model"
    assert len(req.messages) == 1
    assert req.temperature == 0.7
    assert req.max_completion_tokens == 100
    assert req.stream is False


def test_request_rejects_streaming():
    """Ensure stream=True is rejected."""
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=True,
        )


def test_request_forbids_extra_fields():
    """Ensure extra unsupported parameters are strictly rejected."""
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello")],
            presence_penalty=0.5,  # type: ignore
        )


def test_request_temperature_bounds():
    """Verify temperature must be between 0.0 and 2.0."""
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello")],
            temperature=-0.1,
        )

    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello")],
            temperature=2.1,
        )


def test_request_max_tokens_positive():
    """Verify max_completion_tokens must be positive."""
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello")],
            max_completion_tokens=0,
        )

    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello")],
            max_completion_tokens=-50,
        )
