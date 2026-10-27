"""Adapter support ceilings; native session state can restrict them further."""

from dataclasses import dataclass, fields
from typing import Literal


@dataclass(frozen=True)
class AdapterCapabilities:
    queued_messages: bool
    mid_turn_steering: bool
    approvals_survive_restart: bool  # Inbox restart, not a provider restart.
    history_while_unloaded: bool
    images: bool
    interrupt: bool
    commands: bool
    questions: bool
    # opt_in_next_turn is read-only until opted in; the relay waits for the next native turn.
    reply_mode: Literal["direct", "opt_in_next_turn", "none"]

    def __post_init__(self):
        if any(type(getattr(self, field.name)) is not bool for field in fields(self)
               if field.name != "reply_mode") or self.reply_mode not in (
                   "direct", "opt_in_next_turn", "none",
               ):
            raise ValueError("Invalid adapter capabilities")
