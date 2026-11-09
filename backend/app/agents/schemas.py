from pydantic import BaseModel, ConfigDict


class PortalAssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    query: str
    client_turn_id: str | None = None


class PortalAssistantResponse(BaseModel):
    answer: str
    grounded: bool  # True if answer came from retrieved docs, False if we fell back


class AdminAssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    query: str
    client_turn_id: str | None = None


class AdminAssistantResponse(BaseModel):
    answer: str
    tools_used: list[
        str
    ]  # which tools were called, useful for debugging/demo transparency
