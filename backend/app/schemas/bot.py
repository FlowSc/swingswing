from pydantic import BaseModel


class BotControlIn(BaseModel):
    enabled: bool


class BotControlOut(BaseModel):
    user_id: str
    enabled: bool


class WatchTickIn(BaseModel):
    test_mode: bool = False
    dry_run: bool = False
