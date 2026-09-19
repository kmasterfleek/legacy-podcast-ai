"""Bounded input contracts shared by the browser and API."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal, Optional
from urllib.parse import urlparse


class Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class Credentials(Input):
    email: str = Field(min_length=3,max_length=254)
    password: str = Field(min_length=1,max_length=1024)


class Opportunity(Input):
    title: str = Field(min_length=3,max_length=500)
    source_url: str = Field(default="",max_length=2000)

    @model_validator(mode="after")
    def safe_url(self):
        if self.source_url and urlparse(self.source_url).scheme not in {"https","http"}:
            raise ValueError("Source links must use HTTP or HTTPS")
        return self


class NewClip(Input):
    passage_id: str = Field(min_length=1,max_length=64)


class ClipEdit(Input):
    title: str = Field(min_length=1,max_length=250)
    caption: str = Field(default="",max_length=5000)
    start: float = Field(ge=0,allow_inf_nan=False)
    end: float = Field(gt=0,allow_inf_nan=False)
    format: Literal["9:16","1:1","16:9"] = "9:16"
    asset_id: Optional[str] = Field(default=None,max_length=64)
    alignment_confirmed: bool = False
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def range(self):
        if self.end<=self.start or self.end-self.start>180:
            raise ValueError("Choose a clip between 0 and 180 seconds long")
        return self


class Source(Input):
    name: str = Field(min_length=2,max_length=100)
    url: str = Field(min_length=8,max_length=2000)
