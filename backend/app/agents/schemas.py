from pydantic import BaseModel, ConfigDict, Field


class PortalAssistantRequest(BaseModel):
    session_id: str
    query: str


class PortalAssistantResponse(BaseModel):
    answer: str
    grounded: bool  # True if answer came from retrieved docs, False if we fell back


class AdminAssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_\-\.:]+$",
        description="Client session identifier",
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Administrative query or instruction",
    )


class AdminAssistantResponse(BaseModel):
    answer: str
    tools_used: list[
        str
    ]  # which tools were called, useful for debugging/demo transparency
