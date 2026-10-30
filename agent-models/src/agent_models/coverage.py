"""Generated native-to-benchmark coverage; lexical matches never establish entitlement."""

import re


def key(value):
    return tuple(re.findall(r"[a-z]+|\d+", value.casefold()))


def matches(model, label):
    # Provider routing and parenthesized run settings are not model identity.
    native = model["model"].rsplit("/", 1)[-1]
    measured = label.split(" (", 1)[0]
    return key(native) == key(measured)


def labels(source):
    if "points" in source:
        for row in source["points"].get("Overall", []):
            yield row["model"], source.get("efforts", {}).get(row["model"])
    elif "rows" in source:
        for row in source["rows"]:
            yield row["model_name"], None
    else:
        for table in source.get("tables", []):
            header = next((r for r in table if "Model" in r or "Models" in r), None)
            if header is None:
                continue
            index = header.index("Model" if "Model" in header else "Models")
            for row in table[table.index(header) + 1:]:
                if len(row) > index and row[index]:
                    yield row[index], None


def summarize(catalog, snapshot, query=""):
    rows = []
    observations = {}
    for name, source in snapshot["sources"].items():
        if source["status"] != "ok":
            continue
        indexed = observations[name] = {}
        for label, effort in labels(source):
            indexed.setdefault(key(label.split(" (", 1)[0]), []).append((label, effort))
    for model in catalog["models"]:
        if query and not any(key(query) == key(value) or
                             "".join(key(query)) in "".join(key(value))
                             for value in (model["id"], model["model"])):
            continue
        measured = {}
        for name, evidence in observations.items():
            found = []
            for label, effort in evidence.get(key(model["model"].rsplit("/", 1)[-1]), []):
                suffix = re.search(r" \(([^()]+)\)$", label)
                setting = effort or (suffix[1] if suffix else None)
                entry = {"label": label, "setting": setting,
                         "native_effort_supported": (
                             setting.casefold() in [e.casefold() for e in model["efforts"]]
                             if setting and model["efforts"] is not None
                             and re.fullmatch(r"[\w-]+", setting) else None)}
                if entry not in found:
                    found.append(entry)
            if found:
                measured[name] = found
        rows.append({**model, "coverage": "matched" if measured else "no exact benchmark identity",
                     "sources": measured})
    return {**catalog, "benchmark_retrieved": snapshot["retrieved"], "models": rows,
            "matching": "Exact model tokens after separating provider routing and run settings; "
                        "no family/version substitution. Check harness and configuration comparability."}
