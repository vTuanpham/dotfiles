from dataclasses import MISSING, asdict, fields

import pytest

from agent_inbox.adapters import ADAPTERS
from agent_inbox.capabilities import AdapterCapabilities


@pytest.mark.parametrize("kind", ADAPTERS)
def test_every_adapter_explicitly_decides_every_capability(kind):
    assert "capabilities" in type(ADAPTERS[kind]).__dict__
    capabilities = ADAPTERS[kind].capabilities
    assert type(capabilities) is AdapterCapabilities
    for field in fields(AdapterCapabilities):
        assert field.default is MISSING and field.default_factory is MISSING
        values = asdict(capabilities)
        del values[field.name]
        with pytest.raises(TypeError):
            AdapterCapabilities(**values)


@pytest.mark.parametrize("field,value", [("images", 1), ("questions", None), ("reply_mode", "auto")])
def test_capabilities_reject_coercion_and_invented_reply_modes(field, value):
    values = asdict(ADAPTERS["codex"].capabilities)
    values[field] = value
    with pytest.raises(ValueError):
        AdapterCapabilities(**values)


def test_claude_capabilities_describe_only_the_existing_opt_in_relay():
    capabilities = ADAPTERS["claude"].capabilities
    assert capabilities.reply_mode == "opt_in_next_turn"
    assert not any((capabilities.queued_messages, capabilities.mid_turn_steering,
                    capabilities.approvals_survive_restart, capabilities.commands,
                    capabilities.questions, capabilities.interrupt))
