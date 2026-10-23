"""Tell the human the baton is theirs. Goes straight from the daemon, never through the agent."""

import html
import subprocess
import urllib.request

from agent_baton import inject

APP_ID = "agent-baton"
# A 64px orange disc with a white baton, written next to the registry entry below.
ICON = "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAABF0lEQVR42u3b0Q3CQAyD4Q7AUqzOYiAe+liBerFj5xyJAb5fSK16uePIZGjzej7e//y2A48KUoW2i4GGy4Zgw6VCdOPbIqjAW0Ko4ikR1PHQCC54SAQ3fGkEV3xZhK0DqCC+Q4+ghD+HGkENvxphBJ4WQRm/EmEMHhrBBX83gmyAlSkLMB3/M8IOeKkAHXiZAF34ywC74C8j7IRvC6CCbwmghKcHUMNTAyjiaQFU8ZQAynh4AHU8NIADHvY2aI1fDeCChwRwwpcHcMOXfhUah7/zL3DCwz6KuuChZwNj8Kingd1RucKBZuuegMKRdvuiROdSQ7ZEsiOUTbHsCmZbNPvC2RjPvYHcGsndodweyx3CXJ3NZGDzAQ6otCSgQdreAAAAAElFTkSuQmCC"
# Registering our own toast identity shows "agent-baton" and the icon instead of "Windows PowerShell".
REGISTER = r"""
$dir = Join-Path $env:LOCALAPPDATA 'agent-baton'
$icon = Join-Path $dir 'icon.png'
if (-not (Test-Path $icon)) {{
  New-Item -ItemType Directory -Force $dir | Out-Null
  [IO.File]::WriteAllBytes($icon, [Convert]::FromBase64String('{icon}'))
}}
$key = 'HKCU:\Software\Classes\AppUserModelId\{app}'
if (-not (Test-Path $key)) {{ New-Item $key -Force | Out-Null }}
Set-ItemProperty $key -Name DisplayName -Value 'agent-baton'
Set-ItemProperty $key -Name IconUri -Value $icon
Set-ItemProperty $key -Name ShowInSettings -Value 0 -Type DWord
"""
TOAST = """\
<toast scenario="reminder" activationType="protocol" launch="{link}">
  <visual><binding template="ToastGeneric"><text>{title}</text><text>{body}</text></binding></visual>
  <actions>{actions}</actions>
  <audio src="ms-winsoundevent:Notification.Reminder"/>
</toast>"""
ACTION = '<action content="{label}" activationType="protocol" arguments="{url}"/>'
SCRIPT = """\
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('{xml}')
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$toast.Tag = '{tag}'
$toast.Group = '{group}'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app}').Show($toast)
"""
CLEAR = """\
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotificationManager]::History.Remove('{tag}', '{group}', '{app}')
"""
GROUP = "agent-baton"


def headline(baton):
    if baton["kind"] == "question":
        return f"{baton['by']} has a question"
    if baton["kind"] == "run":
        return f"{baton['by']} wants to run a command"
    if baton["kind"] == "ask":
        return f"{baton['by']} needs: " + ", ".join(f["label"] for f in baton["fields"])[:100]
    return f"{baton['by']} needs you to sign in: {baton['site']}"


def body(baton):
    if baton["kind"] == "question":
        return "Open the form to answer. Do not enter secrets."
    if baton["kind"] == "run":
        return baton["command"][:140]
    if baton["kind"] == "ask":
        return (baton["reason"] or "Open the form to answer.")[:140]
    reason = baton["reason"][:140]
    return f"Agent says: {reason}" if reason else "Sign in in your own window, then hand it back."


def buttons(baton, link):
    """(label, url) pairs. A command needs the page (it takes a POST and a password), so one button."""
    if baton["kind"] == "run":
        return [("Review and run", link)]
    if baton["kind"] in ("ask", "question"):
        return [("Open the form", link)]
    return [("Done, hand it back", f"{link}/back"), ("Cancel", f"{link}/cancel")]


def toast_script(baton, link):
    xml = TOAST.format(
        link=html.escape(link),
        title=html.escape(headline(baton)),
        body=html.escape(body(baton)),
        actions="".join(
            ACTION.format(label=html.escape(label), url=html.escape(url))
            for label, url in buttons(baton, link)
        ),
    )
    show = SCRIPT.format(xml=xml.replace("'", "''"), app=APP_ID, tag=baton["id"], group=GROUP)
    return REGISTER.format(icon=ICON, app=APP_ID) + show


def toast(baton, link):
    powershell(toast_script(baton, link))


def dismiss(baton):
    """Take our toast off the screen once the baton is settled, so a stale button can't be clicked."""
    try:
        powershell(CLEAR.format(tag=baton["id"], group=GROUP, app=APP_ID))
    except (OSError, subprocess.SubprocessError):
        pass  # no PowerShell means no toast was ever raised; a stale one is only cosmetic


def powershell(script):
    # Wait with real pipes: a PowerShell whose output goes to /dev/null silently raises no toast.
    result = inject.run_script(script, timeout=20)
    if result.returncode:
        raise OSError(f"powershell exited {result.returncode}")


def ntfy(topic, baton, link):
    """The push goes through a public server, so it carries no site, reason, field or command: the page does."""
    request = urllib.request.Request(
        topic,
        data=b"Tap to see what for and answer.",
        headers={
            "Title": f"{baton['by']} needs you".encode("ascii", "replace").decode(),
            "Priority": "urgent",
            "Tags": "key",
            "Click": link,
            # ntfy splits an action on commas, so a label may not contain one
            "Actions": "; ".join(
                f"view, {label.replace(',', '')}, {url}" for label, url in buttons(baton, link)
            ),
        },
    )
    urllib.request.urlopen(request, timeout=10).close()


def notify(baton, local_link, cfg, public_link=None):
    """Fire every configured channel; return what worked. One broken channel never blocks the rest."""
    channels = [("toast", lambda: toast(baton, local_link))]
    if cfg["ntfy"]:
        channels.append(("ntfy", lambda: ntfy(cfg["ntfy"], baton, public_link or local_link)))
    sent = []
    for name, send in channels:
        try:
            send()
            sent.append(name)
        except Exception as error:  # noqa: BLE001
            sent.append(f"{name}-failed:{type(error).__name__}")
    return sent
