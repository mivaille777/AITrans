from typing import Literal

from pydantic import BaseModel


class MarkdownDocument(BaseModel):
    filename: str
    markdown: str
    mime_type: Literal["text/markdown;charset=utf-8"] = "text/markdown;charset=utf-8"
