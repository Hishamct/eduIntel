from pydantic import BaseModel


class PortalAssistantRequest(BaseModel):
    session_id: str
    query: str


class PortalAssistantResponse(BaseModel):
    answer: str
    grounded: bool  # True if answer came from retrieved docs, False if we fell back


class AdminAssistantRequest(BaseModel):
    session_id: str
    query: str


class AdminAssistantResponse(BaseModel):
    answer: str
    tools_used: list[
        str
    ]  # which tools were called, useful for debugging/demo transparency
