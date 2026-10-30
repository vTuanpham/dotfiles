"""Public benchmark evidence for a reviewer; never selects models or edits the guide."""

import csv
import hashlib
import io
import json
import math
import re
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from agent_accounts import providers
from agent_accounts.models import loads

from . import coverage
from .shortlist import frontier, table_views
from .state import HOME

MAX_BYTES = 8_000_000
LIVE = "https://livebench.ai/"
ARENA = "https://datasets-server.huggingface.co/parquet?"
DATASET = "lmarena-ai/leaderboard-dataset"
CACHE = HOME / "benchmarks"
DOMAINS = ("overall", "reasoning", "backend", "coding", "terminal", "design", "browser", "research", "data",
           "writing", "vision", "documents", "long-context", "tools", "finance", "legal", "tax")
ARENA_BOARDS = {"agent": "agent", "webdev": "webdev", "text": "text_style_control",
                "vision": "vision_style_control", "document": "document_style_control", "search": "search"}


def fetch_bytes(url):
    with urlopen(Request(url, headers={"User-Agent": "model-guide/0.1"}), timeout=25) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("source exceeds size limit")
    return data


def fetch(url):
    return fetch_bytes(url).decode("utf-8")


def number(value, *, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("expected numeric measurement")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (maximum is not None and result > maximum):
        raise ValueError("measurement out of range")
    return result


def csv_rows(text):
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if (not rows or not reader.fieldnames or "model" not in reader.fieldnames
            or len(set(reader.fieldnames)) != len(reader.fieldnames)):
        raise ValueError("empty or ambiguous CSV")
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("ragged CSV")
    identifiers = [row["model"] for row in rows]
    if any(not identifier for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("empty or duplicate model ID")
    return rows


def livebench():
    page = fetch(LIVE)
    script = re.search(r'src="\./(static/js/main\.[a-z0-9]+\.js)"', page)
    if not script:
        raise ValueError("LiveBench release script changed; review current source")
    code = fetch(LIVE + script[1])
    releases = re.findall(r'\["\d{8}"(?:,"\d{8}")*\]', code)
    dates = {value for group in releases for value in json.loads(group)}
    if not dates:
        raise ValueError("LiveBench release catalog changed")
    release = max(dates)
    if datetime.strptime(release, "%Y%m%d").date() > date.today():
        raise ValueError("LiveBench catalog contains a future release")
    base = f"{LIVE}data/{release}/"
    raw = {name: fetch(base + name) for name in ("table.csv", "categories.json", "cost.csv")}
    rows = csv_rows(raw["table.csv"])
    costs = {row["model"]: row for row in csv_rows(raw["cost.csv"])}
    categories = loads(raw["categories.json"])
    if type(categories) is not dict:
        raise ValueError("invalid LiveBench categories")
    weights = categories.pop("_overall_weights", {})
    if type(weights) is not dict or not categories or set(weights) - set(categories):
        raise ValueError("invalid LiveBench categories/weights")
    fields = []
    for category, columns in categories.items():
        if not isinstance(columns, list) or len(columns) != 1 or not isinstance(columns[0], str):
            raise ValueError("LiveBench suite layout changed")
        weight = number(weights.get(category, 1))
        if weight <= 0:
            raise ValueError("invalid LiveBench weight")
        fields.append((category, columns[0], weight))
    if len({field for _, field, _ in fields}) != len(fields):
        raise ValueError("duplicate LiveBench suite")
    points = {name: [] for name in (*categories, "Overall")}
    for row in rows:
        cost = costs.get(row["model"], {})
        scores = {}
        total_cost = total_tasks = 0
        complete_cost = True
        for category, field, _ in fields:
            value = row[field]
            point = {"model": row["model"], "score": None, "cost": None}
            points[category].append(point)
            if value == "":
                complete_cost = False
                continue
            score = number(value, maximum=100)
            point["score"] = score
            scores[category] = score
            if cost.get(field, "") == "" or cost.get("nq_" + field, "") == "":
                complete_cost = False
                continue
            spend, count = number(cost[field]), number(cost["nq_" + field])
            if count <= 0 or not count.is_integer():
                raise ValueError("invalid LiveBench task count")
            total_cost += spend
            total_tasks += count
            if score > 0:
                point["cost"] = spend / count / (score / 100)
        overall = None
        overall_cost = None
        if len(scores) == len(fields):
            overall = sum(scores[name] * w for name, _, w in fields) / sum(w for _, _, w in fields)
            if overall > 0 and complete_cost and total_tasks:
                overall_cost = total_cost / total_tasks / (overall / 100)
        points["Overall"].append({"model": row["model"], "score": overall, "cost": overall_cost})
    version = re.search(r"LiveBench (\d+\.\d+) -", page)
    if not version:
        raise ValueError("LiveBench version not published in page title")
    efforts = dict(re.findall(r'"([^"{}]+)":\{displayName:"[^"{}]+"[^{}]*?effort:"([^"{}]+)"', code))
    return {"url": LIVE, "release": release, "version": version[1], "efforts": efforts,
            "rows": rows, "categories": categories, "weights": weights,
            "cost_rows": list(costs.values()), "points": points,
            "frontiers": {name: frontier(values) for name, values in points.items()},
            "sha256": {base + name: hashlib.sha256(text.encode()).hexdigest()
                       for name, text in raw.items()},
            "limits": "One run per suite; effort must be checked in site metadata. "
                      "Overall cost/success divides mean task cost by weighted overall score; "
                      "it is a composite proxy, not a retry guarantee. Incomplete rows excluded "
                      "from the frontier, never filled with zero. Time per task unavailable."}


def arena(config, catalog):
    import polars as pl

    if type(catalog) is not dict or catalog.get("partial") is not False:
        raise ValueError("incomplete Arena export catalog")
    files = [item for item in catalog["parquet_files"]
             if item["config"] == config and item["split"] == "latest"]
    if not files or len(files) > 8:
        raise ValueError("Arena latest export unavailable")
    rows, digests, total = [], {}, 0
    for item in files:
        url, size = item["url"], item["size"]
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "huggingface.co"
                or not parsed.path.startswith(f"/datasets/{DATASET}/resolve/")
                or type(size) is not int or not 0 < size <= MAX_BYTES):
            raise ValueError("invalid Arena export URL/size")
        raw = fetch_bytes(url)
        if len(raw) != size or url in digests:
            raise ValueError("incomplete or duplicate Arena export")
        digests[url] = hashlib.sha256(raw).hexdigest()
        try:
            frame = pl.read_parquet(io.BytesIO(raw), n_rows=20001)
            total += frame.height
            if total > 20000:
                raise ValueError("Arena export exceeds row limit")
            rows.extend(frame.filter(pl.col("category") == "overall").to_dicts())
        except pl.exceptions.PolarsError as error:
            raise ValueError("invalid Arena Parquet/schema") from error
    score_fields = (("score", "score_ci_lower", "score_ci_upper") if config == "agent"
                    else ("rating", "rating_lower", "rating_upper"))
    for row in rows:
        for key in score_fields:
            if type(row[key]) not in (int, float) or not math.isfinite(row[key]):
                raise ValueError("invalid Arena score")
        if not row[score_fields[1]] <= row[score_fields[0]] <= row[score_fields[2]]:
            raise ValueError("invalid Arena confidence interval")
        if type(row["model_name"]) is not str or not row["model_name"]:
            raise ValueError("invalid Arena model name")
        date.fromisoformat(row["leaderboard_publish_date"][:10])
    if not rows or len({json.dumps(r, sort_keys=True) for r in rows}) != len(rows):
        raise ValueError("empty or duplicate Arena records")
    names = Counter(r["model_name"] for r in rows)
    dates = {r["leaderboard_publish_date"] for r in rows}
    if len(dates) != 1:
        raise ValueError("mixed Arena publication dates")
    return {"url": f"https://huggingface.co/datasets/{DATASET}", "config": config,
            "metric": "net improvement" if config == "agent" else "preference rating",
            "published": next(iter(dates)), "rows": rows, "sha256": digests,
            "ambiguous_names": [name for name, count in names.items() if count > 1],
            "limits": "Arena-published overall category for this modality; raw score scale and "
                      "confidence intervals retained. Preference and agent net-improvement scores "
                      "are distinct. Dataset does not supply task cost/time. CC-BY-4.0, Arena."}


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.text = [], []
        self.table = self.row = self.cell = None
        self.skipping = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skipping = True
        elif tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if not self.skipping:
            self.text.append(data)
            if self.cell is not None:
                self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skipping = False
        elif tag in ("th", "td") and self.cell is not None and self.row is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def webpage(url):
    raw = fetch(url)
    parsed = Tables()
    parsed.feed(raw)
    tables = [t for t in parsed.tables if len(t) > 2 and any("Model" in c for r in t[:3] for c in r)]
    if not tables:
        raise ValueError("benchmark table absent; review source layout")
    text = " ".join(" ".join(parsed.text).split())
    metadata = re.findall(r"(?:Version \d+(?:\.\d+)*|Updated \d{1,2}/\d{1,2}/\d{4})", text)
    methodology = None
    if "artificialanalysis.ai" in url:
        methodology = "https://artificialanalysis.ai/methodology/intelligence-benchmarking"
        methods = fetch(methodology)
        versions = re.findall(r"Intelligence Index v(\d+\.\d+)", methods)
        if not versions:
            raise ValueError("Artificial Analysis methodology version missing")
        metadata.append("Intelligence Index v" + versions[0])
    return {"url": url, "metadata": metadata, "methodology_url": methodology, "tables": tables,
            "effort_tradeoffs": effort_tradeoffs(tables) if methodology else [],
            "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "limits": "Published table cells retained verbatim, including effort/harness and "
                      "task cost/time columns. Verify methodology/version before comparing. "
                      "Missing values have not been filled. Response latency is not agent task "
                      "completion time; retain the source's exact duration/workload label."}


def vals_terminal():
    index = "https://www.vals.ai/benchmarks/vals_index"
    raw = fetch(index)
    paths = set(re.findall(r'href=[\"\'](?:https://www\.vals\.ai)?'
                           r'(/benchmarks/terminal-bench-\d+(?:-\d+)*)[\"\']', raw))
    if not paths:
        raise ValueError("Vals Index no longer links a Terminal-Bench release")
    path = max(paths, key=lambda p: tuple(int(v) for v in re.findall(r"\d+", p)))
    return {**webpage("https://www.vals.ai" + path), "discovered_from": index}


def effort_tradeoffs(tables):
    """Neighboring measured settings by cost within a model/configuration, not an effort ladder."""
    groups = {}
    for table in tables:
        header = next((r for r in table if "Cost per Task USD" in r), None)
        if header is None:
            continue
        indexes = {name: header.index(name) for name in
                   ("Model", "Artificial Analysis Intelligence Index", "Cost per Task USD",
                    "Latency First Chunk (s)", "Total Response (s)")}
        for row in table[table.index(header) + 1:]:
            if len(row) != len(header):
                raise ValueError("Artificial Analysis table width changed")
            match = re.fullmatch(r"(.+) \(([^()]+)\)", row[indexes["Model"]])
            if not match:
                continue
            measurements = {}
            for name, index in indexes.items():
                if name != "Model":
                    value = row[index].removeprefix("$").replace(",", "")
                    measurements[name] = None if value in ("--", "") else number(value)
            setting = match[2]
            configuration = "with fallback" if setting.endswith(" with fallback") else ""
            setting = setting.removesuffix(" with fallback")
            key = (match[1], configuration)
            group = groups.setdefault(key, {})
            if setting in group:
                raise ValueError("duplicate model/effort measurement")
            group[setting] = measurements
    result = []
    for (model, configuration), levels in groups.items():
        measured = sorted(((setting, values) for setting, values in levels.items()
                           if values["Cost per Task USD"] is not None),
                          key=lambda item: item[1]["Cost per Task USD"])
        for (before_effort, before), (after_effort, after) in zip(measured, measured[1:]):
            deltas = {key: round(after[key] - value, 6)
                      if value is not None and after[key] is not None else None
                      for key, value in before.items()}
            result.append({"model": model, "configuration": configuration,
                           "from": before_effort, "to": after_effort,
                           "before": before, "after": after, "delta": deltas})
    return result


def collect(name, loader):
    try:
        return name, {"status": "ok", **loader()}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return name, {"status": "unavailable", "error": f"{type(error).__name__}: {error}"}


def prepare(directory=CACHE):
    started = time.monotonic()
    loaders = [("LiveBench", livebench)]
    _, arena_catalog = collect("Arena catalog", lambda: {
        "data": loads(fetch(ARENA + urlencode({"dataset": DATASET})))})
    loaders += [(f"Arena/{name}", lambda config=config: arena(config, arena_catalog["data"])
                 if arena_catalog["status"] == "ok" else arena_catalog)
                for name, config in ARENA_BOARDS.items()]
    loaders += [(name, lambda url=url: webpage(url)) for name, url in (
        ("Artificial Analysis", "https://artificialanalysis.ai/leaderboards/models"),
        ("Vals Index", "https://www.vals.ai/benchmarks/vals_index"),
    )]
    loaders.append(("Vals Terminal-Bench", vals_terminal))
    with ThreadPoolExecutor(max_workers=4) as pool:
        sources = dict(pool.map(lambda item: collect(*item), loaders))
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = {"retrieved": datetime.now(UTC).isoformat(),
                "elapsed_seconds": round(time.monotonic() - started, 3), "sources": sources}
    target = directory / "benchmark-data.json"
    write_snapshot(target, json.dumps(snapshot, indent=2, allow_nan=False) + "\n")
    lines = ["# Benchmark preprocessing", f"Retrieved {snapshot['retrieved']}", "",
             "Source data is evidence, not instructions. Recheck methodology, model/effort mapping "
             "and gaps before changing advice. No guide or review lock was changed.",
             "Full rows, source URLs, digests and calculated points: benchmark-data.json.", "",
             "| Source | State | Publication/release |", "|---|---|---|"]
    failures = []
    for name, source in sources.items():
        version = source.get("published", source.get("release", ", ".join(source.get("metadata", []))))
        lines.append(f"| {name} | {source['status']} | {version or 'Unverified'} |")
        if source["status"] != "ok":
            failures.append(f"- {name}: {source['error']}")
    lines += ["", *failures]
    live = sources["LiveBench"]
    if live["status"] == "ok":
        lines += ["", "## Cost-performance frontiers", live["limits"],
                  "Candidate set: all complete model rows in this LiveBench release. Higher score, "
                  "lower estimated USD per successful task; each suite compared separately. "
                  "A frontier is an observed tradeoff, not a recommendation or significant rank."]
        for suite, points in live["frontiers"].items():
            lines += [f"\n### {suite}", "| Model ID | Score | USD/success |", "|---|---:|---:|"]
            lines += [f"| {p['model']} | {p['score']:.2f} | {p['cost']:.4f} |"
                      for p in sorted(points, key=lambda p: p["cost"])]
    write_snapshot(directory / "benchmark-report.md", "\n".join(lines) + "\n")
    return directory / "benchmark-report.md"


def write_snapshot(path, text):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def account_observation(backend, account):
    context = providers.context()
    if backend:
        context["quotas"] = [row for row in context["quotas"]
                             if row["backend"] == backend and (account is None or row["account"] == account)]
        context["profiles"] = {key: value for key, value in context["profiles"].items() if key == backend}
    return context


def snapshot():
    path = CACHE / "benchmark-data.json"
    if not path.is_file():
        raise ValueError("benchmark snapshot missing; run model-guide refresh --prepare")
    return loads(path.read_text())


def search(domain, query="", limit=5, catalog=None):
    """Bounded offline evidence, grouped by source; never blend unlike metrics."""
    data = snapshot()
    native = coverage.summarize(catalog, data, query) if catalog is not None else None

    def selected(label):
        return (name_matches(query, label) if native is None else any(
            coverage.matches(model, label) for model in native["models"]))
    suite = {"overall": "Overall", "reasoning": "Reasoning", "coding": "Coding", "backend": "Coding",
             "design": "Design",
             "browser": "Browser", "research": "Research", "data": "Data Analysis"}.get(domain)
    arena_config = {"overall": "agent", "design": "webdev", "writing": "text", "vision": "vision",
                    "documents": "document", "research": "search", "tools": "agent"}.get(domain)
    wanted = ({"LiveBench"} if suite else set())
    if arena_config:
        wanted.add("Arena/" + arena_config)
    if domain in ("overall", "finance", "legal", "tax", "data"):
        wanted.add("Vals Index")
    if domain in ("backend", "coding", "terminal"):
        wanted.add("Vals Terminal-Bench")
    if domain == "overall" or query:
        wanted.add("Artificial Analysis")
    results = {}
    for name, source in data["sources"].items():
        if name not in wanted:
            continue
        info = {key: value for key, value in source.items()
                if key not in ("rows", "tables", "cost_rows", "points", "frontiers", "sha256", "efforts",
                               "effort_tradeoffs", "categories", "weights")}
        if source["status"] != "ok":
            results[name] = info
            continue
        if name == "LiveBench":
            assert suite is not None
            values = source["points"][suite]
            matches = [p for p in values if selected(p["model"])]
            efficient = sorted(frontier(matches), key=lambda p: (p["cost"], -p["score"]))
            pareto = {p["model"] for p in efficient}
            info["metric"] = suite + " score; estimated USD per successful task"
            quality = sorted(matches, key=lambda p: (p["score"] is None, -(p["score"] or 0)))
            for field, points in (("results", quality), ("efficient_results", efficient)):
                info[field] = [{"model": p["model"], "effort": source["efforts"].get(p["model"]),
                                "score": round(p["score"], 2) if p["score"] is not None else None,
                                "usd_per_success": round(p["cost"], 4) if p["cost"] is not None else None,
                                "time_per_task": None, "on_frontier": p["model"] in pareto}
                               for p in points[:limit]]
            info["efficient_matches"] = len(efficient)
            info["frontier_scope"] = (
                "Matching candidates in this release/suite after native/query filtering; "
                "higher score, lower estimated USD/success. Not subscription usage.")
        elif name.startswith("Arena/"):
            matches = [r for r in source["rows"] if selected(r["model_name"])]
            info["results"] = sorted(matches, key=lambda r: r["rank"])[:limit]
        else:
            info["tables"] = []
            matches = []
            for table in source["tables"]:
                header = next(i for i, row in enumerate(table) if any("Model" in c for c in row))
                model_column = next(i for i, cell in enumerate(table[header]) if "Model" in cell)
                start = header + 1
                # Multi-level headers belong to the evidence, not to the model search.
                while start < len(table) and not any(
                    re.fullmatch(r"\$?\d+(?:[.,]\d+)*(?:\s*%|[kKmM])?", c)
                    for c in table[start][1:]):
                    start += 1
                found = [r for r in table[start:] if selected(r[model_column])]
                matches.extend(found)
                if name != "Artificial Analysis" or domain == "overall":
                    info["tables"].append(table_views(table[header:start], found, limit))
            trades = [r for r in source.get("effort_tradeoffs", []) if selected(r["model"])]
            info["effort_tradeoffs"] = trades[:limit]
            info["effort_tradeoff_matches"] = len(trades)
            if trades:
                info["comparison_order"] = "Increasing measured cost; no universal effort order."
            if name == "Artificial Analysis" and domain != "overall":
                info["metric_scope"] = "Broad-index effort tradeoffs; not a domain score."
        info["matches"] = len(matches)
        info["limit_per_table"] = limit
        results[name] = info
    if native is not None:
        groups = []
        for info in results.values():
            returned = []
            # Interleave views so the native context budget also preserves cheap candidates.
            for index in range(limit):
                for field in ("results", "efficient_results"):
                    if index < len(info.get(field, [])):
                        row = info[field][index]
                        returned.append(row.get("model", row.get("model_name", "")))
            returned.extend(r["model"] for r in info.get("effort_tradeoffs", []))
            for table in info.get("tables", []):
                header = next(r for r in table["headers"] if any("Model" in c for c in r))
                index = next(i for i, c in enumerate(header) if "Model" in c)
                for position in range(limit):
                    for field in ("rows", "efficient_rows"):
                        if position < len(table.get(field, [])):
                            returned.append(table[field][position][index])
            groups.append(list(dict.fromkeys(returned)))
        returned = [group[i] for i in range(max(map(len, groups), default=0))
                    for group in groups if i < len(group)]
        all_models = native.pop("models")
        candidates = [{key: value for key, value in m.items() if key not in ("sources", "coverage")}
                      for m in all_models if any(coverage.matches(m, label) for label in returned)]
        candidates.sort(key=lambda m: next(i for i, label in enumerate(returned)
                                            if coverage.matches(m, label)))
        native["models"] = candidates[:limit]
        native["matches"] = len(candidates)
        native["limit"] = limit
        missing = [m["id"] for m in all_models if not m["sources"]]
        native["unmeasured_count"] = len(missing)
        native["unmeasured_ids"] = missing[:limit]
        native["coverage_command"] = "model-guide models --backend " + native["backend"] + " --json"
    return {"retrieved": data["retrieved"], "domain": domain, "query": query,
            "native_catalog": native,
            "coverage_notes": (["Backend uses coding and terminal proxies; database design, security "
                                "and service architecture are not directly measured."] if domain == "backend"
                               else ["Writing uses style-controlled text preference, not a dedicated "
                                     "writing-quality or factual-accuracy benchmark."] if domain == "writing"
                               else []),
            "sources": results, "gaps": "Missing measurements/settings are unknown; source scales differ.",
            "review_sources": (
                ["https://longbench2.github.io/"] if domain == "long-context" else
                ["https://gorilla.cs.berkeley.edu/leaderboard.html"] if domain == "tools" else []),
            "full_snapshot": str(CACHE / "benchmark-data.json")}


def name_matches(query, value):
    # Display names and native IDs differ in separators; search never establishes identity.
    def normalize(text):
        return "".join(c for c in text.casefold() if c.isalnum())
    return normalize(query) in normalize(value)
