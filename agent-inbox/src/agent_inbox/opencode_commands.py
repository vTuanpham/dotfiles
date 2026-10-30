import json

from .commands import Choice, Command, Commands
from .models import text
from .opencode_http import location_query


def commands(api, info):
    query = location_query(info)
    models = api.call("GET", "/api/model?" + query)["data"]
    agents = api.call("GET", "/api/agent?" + query)["data"]
    native = api.call("GET", "/api/command?" + query)["data"]
    if any(type(value) is not list for value in (models, agents, native)):
        raise ValueError("Invalid native controls")
    options = []
    for model in models:
        if model["enabled"] is not True:
            continue
        ref = {"id": text(model["id"], "model id", 200),
               "providerID": text(model["providerID"], "provider id", 200)}
        options.append(Choice(json.dumps(ref, sort_keys=True), text(model["name"], "model name", 200)))
        if type(model["variants"]) is not list:
            raise ValueError("Invalid native model variants")
        for variant in model["variants"]:
            name = text(variant["id"], "model variant", 200)
            options.append(Choice(json.dumps({**ref, "variant": name}, sort_keys=True),
                                  model["name"] + " · " + name))
    current = json.dumps(info["model"], sort_keys=True) if "model" in info else None
    controls = [Command("model", "Model", "select", options, current, "Next turns"),
                Command("agent", "Agent", "select", [Choice(text(row["id"], "agent id", 200),
                                                          text(row["name"], "agent name", 200))
                                                       for row in agents if row["mode"] != "subagent"
                                                       and not row.get("hidden", False)], info.get("agent")),
                Command("interrupt", "Stop turn", "action")]
    for command in native:
        name = text(command["name"], "native command", 100)
        description = command.get("description", "")
        if type(description) is not str:
            raise ValueError("Invalid native command description")
        controls.append(Command("slash:" + name, "/" + name, "text", description=description))
    return Commands(controls, "Terminal-only menus remain in OpenCode.")


def execute(api, path, command, value):
    if command == "model":
        api.call("POST", path + "/model", {"model": json.loads(value)})
    elif command == "agent":
        api.call("POST", path + "/agent", {"agent": value})
    elif command == "interrupt":
        api.call("POST", path + "/interrupt")
    elif command.startswith("slash:"):
        api.call("POST", path + "/command", {"name": command[6:], "text": value})
    else:
        raise ValueError("Unsupported native command")
