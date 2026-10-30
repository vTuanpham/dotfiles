"""Comparable quality/cost views and compact evidence output; no model recommendation."""

import math


def frontier(points):
    """Quality increases; cost decreases. Call separately for each comparable metric."""
    measured = [p for p in points if p["score"] is not None and p["cost"] is not None]
    return [point for point in measured if not any(
        other["score"] >= point["score"] and other["cost"] <= point["cost"]
        and (other["score"] > point["score"] or other["cost"] < point["cost"])
        for other in measured
    )]


def measurement(cell):
    if cell in ("", "--", "—", "N/A"):
        return None
    value = float(cell.removeprefix("$").removesuffix("%").replace(",", ""))
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid table cost/score")
    return value


def table_views(headers, rows, limit):
    result = {"headers": headers, "rows": rows[:limit]}
    header = headers[0]
    score = next((header.index(name) for name in ("Score", "Accuracy") if name in header), None)
    if score is None or "Cost / Test" not in header:
        return result
    cost = header.index("Cost / Test")
    harness = header.index("Harness") if "Harness" in header else None
    groups = {}
    for index, row in enumerate(rows):
        groups.setdefault(row[harness] if harness is not None else "", []).append(
            {"row": index, "score": measurement(row[score]), "cost": measurement(row[cost])})
    efficient = [p for points in groups.values() for p in frontier(points)]
    efficient.sort(key=lambda p: (p["cost"], -p["score"]))
    result.update(efficient_rows=[rows[p["row"]] for p in efficient[:limit]],
                  efficient_matches=len(efficient),
                  frontier_scope="Matching candidates within this table, separately per harness; "
                                 "higher score, lower API USD/test. Unknown measurements excluded.")
    return result


def brief(data):
    lines = [f"{data['domain']} · retrieved {data['retrieved']}"]
    native = data.get("native_catalog")
    if native:
        lines.append(f"Native {native['backend']}: {native['matches']} matching routes; "
                     f"showing {len(native['models'])}")
        lines += [f"  {m['id']}" + (f" → {m['model']}" if m["id"] != m["model"] else "")
                  + f" · {m.get('effort_control', 'effort')}: "
                  + (", ".join(m["efforts"]) if m["efforts"] else "efforts unknown or unavailable")
                  for m in native["models"]]
        if native["unmeasured_count"]:
            lines.append(f"Unmeasured native IDs: {native['unmeasured_count']} · "
                         + ", ".join(native["unmeasured_ids"]))
    for name, source in data["sources"].items():
        version = source.get("release", source.get("published",
                             ", ".join(dict.fromkeys(source.get("metadata", [])))))
        if source.get("version"):
            version = source["version"] + " · " + version
        lines += ["", f"{name} · {version}"]
        if source["status"] != "ok":
            lines.append("Unavailable: " + source["error"])
            continue
        lines.append(source.get("metric", source.get("metric_scope", "Published table metrics")))
        for title, field in (("Quality", "results"), ("Efficient", "efficient_results")):
            rows = source.get(field, [])
            if not rows:
                continue
            lines.append(title + ":")
            for row in rows:
                if "usd_per_success" in row:
                    cost = row["usd_per_success"]
                    lines.append(f"  {row['model']} ({row['effort'] or 'effort unknown'}) · "
                                 f"score {row['score']} · "
                                 + (f"${cost}/success" if cost is not None else "cost unknown"))
                else:
                    score = "rating" if "rating" in row else "score"
                    low, high = (("rating_lower", "rating_upper") if score == "rating"
                                 else ("score_ci_lower", "score_ci_upper"))
                    lines.append(f"  {row['model_name']} · {row[score]:.2f} "
                                 f"[{row[low]:.2f}, {row[high]:.2f}] · rank {row['rank']}")
        for table in source.get("tables", []):
            lines.append(" | ".join(table["headers"][0]))
            for header in table["headers"][1:]:
                lines.append(" | ".join(header))
            for title, field in (("Quality", "rows"), ("Efficient", "efficient_rows")):
                if table.get(field):
                    lines.append(title + ":")
                    lines += ["  " + " | ".join(row) for row in table[field]]
            if "frontier_scope" in table:
                lines.append(table["frontier_scope"])
        trades = source.get("effort_tradeoffs", [])
        if trades:
            lines.append(f"Effort steps: {source['effort_tradeoff_matches']} · showing {len(trades)}")
        for trade in trades:
            fields = ("Artificial Analysis Intelligence Index", "Cost per Task USD", "Total Response (s)")
            before, after = trade["before"], trade["after"]
            values = " · ".join(f"{field}: {before[field]} → {after[field]}" for field in fields)
            lines.append(f"  {trade['model']} {trade['from']} → {trade['to']} "
                         f"({trade['configuration'] or 'published run'}) · {values}")
        if "frontier_scope" in source:
            lines.append(source["frontier_scope"])
        if source.get("limits"):
            lines.append(source["limits"])
        efficient = f" · efficient {source['efficient_matches']}" if "efficient_matches" in source else ""
        lines.append(f"Matches: {source['matches']}{efficient} · "
                     f"limit {source['limit_per_table']} per view/table")
        if "ambiguous_names" in source and source["ambiguous_names"]:
            lines.append("Separate evaluations share names: " + ", ".join(source["ambiguous_names"]))
        lines.append(source["url"])
    accounts = data.get("account_observation")
    if accounts:
        lines += ["", "Accounts · " + accounts["scope"]]
        for backend, profile in accounts["profiles"].items():
            lines.append(f"  {backend}: " + ", ".join(f"{k}={v}" for k, v in profile.items()))
        for account in accounts["quotas"]:
            windows = ", ".join(f"{w['group']} {w['label']}={w['remaining_percent']}%".lstrip()
                                + (f" reset {w['resets']}" if w["resets"] else "")
                                for w in account["windows"])
            flags = " · ".join(str(v) for v in (account["plan"], account["freshness"], account["status"],
                                               "active profile" if account["active"] else None) if v)
            lines.append(f"  {account['backend']}/{account['account']} · {flags} · {windows}")
        lines += accounts["errors"]
    lines += ["", *data.get("coverage_notes", []), data["gaps"], "Full evidence: " + data["full_snapshot"]]
    return "\n".join("".join(c for c in line if c.isprintable()) for line in lines)
