"""Pydantic schemas for the OpenAI-compatible chat completions API."""

from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatMessage(BaseModel):
    """Chat message schema strictly supporting plain-text system, user, and assistant roles."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"] = Field(
        ...,
        description="The role of the message author. In Phase 1, only 'system', 'user', and 'assistant' are permitted.",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="The plain-text content of the message. Multimodal input is rejected.",
    )

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message content cannot be empty or whitespace only.")
        return v


class ChatCompletionRequest(BaseModel):
    """Request payload for /v1/chat/completions."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(
        ...,
        min_length=1,
        description="The target model ID. Must belong to the configured allowed_models.",
    )
    messages: List[ChatMessage] = Field(
        ...,
        min_length=1,
        description="List of messages comprising the conversation so far.",
    )
    temperature: Optional[float] = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature between 0 and 2.",
    )
    max_completion_tokens: Optional[int] = Field(
        default=None,
        gt=0,
        description="Maximum number of tokens to generate. Must be a positive integer.",
    )
    stream: Optional[bool] = Field(
        default=False,
        description="Stream responses. Must be false in Phase 1.",
    )

    @field_validator("model")
    @classmethod
    def validate_model_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Model name cannot be empty or whitespace only.")
        return v.strip()

    @field_validator("stream")
    @classmethod
    def validate_stream_not_supported(cls, v: Optional[bool]) -> Optional[bool]:
        if v is True:
            raise ValueError("Streaming ('stream': true) is not supported in Phase 1.")
        return v


class UsageInfo(BaseModel):
    """Token usage reporting, explicitly labeled for mock estimates."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    is_mock_estimate: bool = Field(
        default=True,
        description="True if token counts are deterministic mock estimates rather than real provider reports.",
    )


class ChatChoiceMessage(BaseModel):
    """The generated message from the assistant."""

    model_config = ConfigDict(extra="forbid")

    role: str = "assistant"
    content: str


class ChatChoice(BaseModel):
    """A single completion choice."""

    model_config = ConfigDict(extra="forbid")

    index: int = 0
    message: ChatChoiceMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    model_config = ConfigDict(extra="forbid")

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]
    usage: UsageInfo
