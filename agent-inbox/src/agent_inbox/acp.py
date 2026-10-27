"""Root-only Antigravity ACP adapter."""

from .acp_runtime import RuntimePool
from .capabilities import AdapterCapabilities
from .commands import Choice, Command, Commands
from .context import Metric, SessionContext
from .forms import Forms
from .media import decode_images
from .models import DeliveryRejected, Outgoing, RootInfo, Snapshot, Target, text


def _commands(state):
    controls = []
    config_options = state["config_options"]
    mode_config = any(option.category == "mode" for option in config_options)
    for option in config_options:
        choices = [Choice(value, label) for value, label in option.choices]
        current = str(option.current).lower() if type(option.current) is bool else option.current
        controls.append(
            Command("config:" + option.id, option.name, "select", choices, current, "Next prompts")
        )
    modes = state["modes"]
    if modes is not None and not mode_config:
        controls.append(
            Command(
                "mode",
                "Mode",
                "select",
                [Choice(value, label) for value, label in modes.choices],
                modes.current,
                "Next prompts",
            )
        )
    for native in state["commands"]:
        description = native.description
        if native.hint:
            description = (description + "\n" if description else "") + "Input: " + native.hint
        kind = "text" if native.hint else "action"
        controls.append(Command("slash:" + native.name, "/" + native.name, kind, description=description))
    if state["active"]:
        controls.append(Command("interrupt", "Stop turn", "action"))
    return Commands(controls)


class ACP:
    capabilities = AdapterCapabilities(
        queued_messages=False, mid_turn_steering=False, approvals_survive_restart=False,
        history_while_unloaded=False, images=True, interrupt=True, commands=True, questions=False,
        reply_mode="direct",
    )

    def __init__(self, runtimes=None):
        self.runtimes = runtimes if runtimes is not None else RuntimePool()

    def discover(self, seed: Target):
        sessions = self.runtimes.discover(seed)
        return [RootInfo(item.id, item.label, "unknown", saved=True) for item in sessions]

    def snapshot(self, target: Target, cursor=None, since=None):
        value = self.runtimes.call(target, "snapshot", cursor, since)
        return Snapshot(**value)

    def send(self, target: Target, message: Outgoing):
        if message.delivery != "queue":
            raise DeliveryRejected("ACP does not support mid-turn steering")
        text_value = message.text
        images = decode_images(message.images)
        if not images or text_value:
            text(text_value, "message")
        prompt = []
        if text_value:
            prompt.append({"type": "text", "text": text_value})
        for image in images:
            header, separator, encoded = image.partition(",")
            if not separator or not header.startswith("data:image/") or not header.endswith(";base64"):
                raise ValueError("Invalid ACP image input")
            mime = header[len("data:") : -len(";base64")]
            prompt.append({"type": "image", "mimeType": mime, "data": encoded})
        reason = self.runtimes.call(target, "send", prompt)
        if reason not in ("end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"):
            raise RuntimeError("ACP did not confirm the prompt result")
        return "completed"

    def commands(self, target: Target):
        return _commands(self.runtimes.call(target, "controls"))

    def execute(self, target: Target, command, value):
        controls = self.runtimes.call(target, "controls")
        selected = _commands(controls).selected(command, value)
        if selected.id == "interrupt":
            return self.runtimes.call(target, "cancel")
        if selected.id == "mode":
            return self.runtimes.call(target, "mode", value)
        if selected.id.startswith("config:"):
            identifier = selected.id[len("config:") :]
            option = next(option for option in controls["config_options"] if option.id == identifier)
            parsed = value == "true" if option.kind == "boolean" else value
            return self.runtimes.call(target, "config", identifier, parsed)
        if selected.id.startswith("slash:"):
            name = selected.id[len("slash:") :]
            reason = self.runtimes.call(target, "slash", name, value)
            if reason not in ("end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"):
                raise RuntimeError("ACP did not confirm the command result")
            return "applied"
        raise DeliveryRejected("ACP command is no longer available")

    def forms(self, target: Target):
        self.runtimes.call(target, "controls")
        return Forms(
            [],
            "ACP permission requests are declined by the inbox. Open this root in its native client "
            "to approve them.",
        )

    def context(self, target: Target):
        state = self.runtimes.call(target, "context")
        notices = []
        if state["denied_permissions"]:
            notices.append("The inbox declined an ACP permission request; review it in the native client.")
        metrics = []
        usage = state["usage"]
        if usage is not None:
            metrics.extend((Metric("Context used", usage.used, "tokens"),
                            Metric("Context window", usage.size, "tokens")))
            if usage.cost_amount is not None and usage.currency is not None:
                metrics.append(Metric("Session cost", usage.cost_amount, usage.currency))
        return SessionContext(metrics=metrics, notices=notices)
