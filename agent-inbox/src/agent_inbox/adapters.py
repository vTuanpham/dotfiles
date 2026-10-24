from .acp import ACP
from .claude import Claude
from .codex import Codex
from .models import Snapshot, fields, https_url
from .opencode import OpenCode


class NativeLink:
    def discover(self, seed):
        return None

    def snapshot(self, target, cursor=None, since=None):
        fields(target.settings, ("url",))
        return Snapshot("native", False, [], native_url=https_url(target.settings["url"]))

    def send(self, target, message):
        raise ValueError("Open this root in its native remote interface to send messages")


ADAPTERS = {"codex": Codex(), "claude": Claude(), "opencode": OpenCode(),
            "acp": ACP(), "native": NativeLink()}


def adapter(target):
    try:
        return ADAPTERS[target.adapter]
    except KeyError:
        raise ValueError("This root's adapter is not installed") from None
