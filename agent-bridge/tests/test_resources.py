import os
import sys

import pytest

from agent_bridge import cli, core, heavy, resources, watch


def write_group(path, maximum="max", current=0, quota="max", usage=0, oom=0, throttled=0):
    path.mkdir(parents=True, exist_ok=True)
    (path / "memory.max").write_text(str(maximum))
    (path / "memory.current").write_text(str(current))
    (path / "memory.events").write_text(f"oom 0\noom_kill {oom}\n")
    (path / "cpu.max").write_text(f"{quota} 100000")
    (path / "cpu.stat").write_text(f"usage_usec {usage}\nnr_throttled {throttled}\nthrottled_usec 0\n")


@pytest.fixture
def budgets(monkeypatch, tmp_path):
    proc, cgroup = tmp_path / "proc", tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text("MemTotal: 10000000 kB\nMemAvailable: 8000000 kB\n")
    (proc / "loadavg").write_text("0.01 0 0 1/100 200\n")
    relative = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/codex.slice/job.scope"
    (proc / "self/cgroup").write_text(f"0::/{relative}\n")
    job = cgroup / relative
    path = job
    while path != cgroup:
        write_group(path)
        path = path.parent
    write_group(job, maximum=2500 * resources.MIB, current=500 * resources.MIB, quota="300000")
    write_group(job.parent, maximum=7 * 1024 * resources.MIB, current=4000 * resources.MIB,
                quota="600000", oom=14)
    monkeypatch.setattr(resources, "PROC", proc)
    monkeypatch.setattr(resources, "CGROUP", cgroup)
    monkeypatch.setenv("AGENT_BRIDGE_HEAVY_DIR", str(tmp_path / "queue"))
    for key in ("SLOTS", "MIN_AVAILABLE_MIB", "MAX_LOAD", "ACTIVE"):
        monkeypatch.delenv("AGENT_BRIDGE_HEAVY_" + key, raising=False)
    return proc, job


def test_tighter_host_slice_and_job_headroom(budgets):
    proc, job = budgets
    sample = resources.pressure()
    assert sample.capacity == 2500 * resources.MIB
    assert sample.headroom == 2000 * resources.MIB
    assert sample.shared_capacity == 7 * 1024 * resources.MIB
    assert sample.shared_headroom == 3168 * resources.MIB
    assert resources.limits(sample).available == 1024 * resources.MIB
    assert sample.slice.oom_kill == 14
    write_group(job.parent, maximum=7 * 1024 * resources.MIB, current=7000 * resources.MIB)
    assert resources.pressure().headroom == 168 * resources.MIB
    assert resources.pressure().shared_headroom == 168 * resources.MIB
    (proc / "meminfo").write_text("MemTotal: 10000000 kB\nMemAvailable: 1000 kB\n")
    assert resources.pressure().headroom == 1000 * 1024
    assert resources.pressure().shared_headroom == 1000 * 1024


@pytest.mark.parametrize("kind", ["memory", "cpu", "throttled"])
def test_admission_waits_for_cgroup_budget(budgets, monkeypatch, capsys, kind):
    _, job = budgets
    if kind == "memory":
        (job.parent / "memory.current").write_text(str(7000 * resources.MIB))
    clock = iter(range(100))
    monkeypatch.setattr(resources.time, "clock_gettime", lambda _: next(clock))
    sleeps = []

    def tick(_):
        sleeps.append(1)
        if kind == "cpu":
            usage = 6000000
            (job.parent / "cpu.stat").write_text(f"usage_usec {usage}\nnr_throttled 0\n")
        if kind == "throttled":
            (job.parent / "cpu.stat").write_text("usage_usec 1\nnr_throttled 1\n")
        if len(sleeps) == 2:
            (job.parent / "memory.current").write_text(str(4000 * resources.MIB))

    class Executed(Exception):
        pass

    def execute(name, command, env):
        env.clear()
        assert len(sleeps) == 2
        raise Executed

    monkeypatch.setattr(heavy.time, "sleep", tick)
    monkeypatch.setattr(heavy.os, "execvpe", execute)
    with pytest.raises(Executed):
        heavy.run(["unused"])
    assert ("headroom" if kind == "memory" else "CPU busy/throttled") in capsys.readouterr().err


def test_inherited_scope_is_kept_even_when_a_smaller_cap_is_requested(budgets, monkeypatch, capsys):
    def unrelated_scope(_):
        pytest.fail("must not move a worker out of its existing job scope")

    class Executed(Exception):
        pass

    def execute(name, command, env):
        env.clear()
        raise Executed

    monkeypatch.setattr(heavy, "scope_prefix", unrelated_scope)
    monkeypatch.setattr(heavy.time, "sleep", lambda _: None)
    monkeypatch.setattr(heavy.os, "execvpe", execute)
    with pytest.raises(Executed):
        heavy.run(["unused"], "100")
    assert "requested cap not applied" in capsys.readouterr().err


def test_cpu_controller_absence_is_visible(budgets):
    _, job = budgets
    (job.parent / "cpu.max").unlink()
    (job.parent / "cpu.stat").write_text("usage_usec 100\n")
    report = heavy.status()
    assert "oom_kill=14" in report.summary
    assert "cpu_quota=unavailable/unlimited" in report.summary
    assert "throttled_usec=None" in report.summary


def test_watch_reports_oom_totals_and_increases_once(budgets, monkeypatch, tmp_path, capsys):
    _, job = budgets
    monkeypatch.setattr(watch, "JOBS", tmp_path / "absent")
    clock = iter([0, 11, 22, 33, 44])
    monkeypatch.setattr(watch.time, "time", lambda: next(clock))

    def tick(_):
        (job.parent / "memory.events").write_text("oom_kill 15\n")

    monkeypatch.setattr(watch.time, "sleep", tick)
    watch.watch(["absent"])
    output = capsys.readouterr().out
    assert output.count("WARNING: codex.slice oom_kill=14 (total recorded)") == 1
    assert output.count("WARNING: codex.slice oom_kill=15 (increased)") == 1


@pytest.mark.parametrize("file,value", [("memory.max", "-1"), ("memory.current", "bad"),
                                        ("memory.events", "oom_kill 1\noom_kill 2"),
                                        ("cpu.max", "300000 0"), ("cpu.stat", "usage_usec nan")])
def test_malformed_cgroup_data_fails_closed(budgets, file, value):
    _, job = budgets
    (job / file).write_text(value)
    with pytest.raises(ValueError):
        resources.pressure()
    assert heavy.status().sample is None


def test_root_outside_slice_still_reads_worker_slice(budgets):
    proc, job = budgets
    root = job.parents[1] / "root.scope"
    write_group(root)
    (proc / "self/cgroup").write_text(f"0::/{root.relative_to(resources.CGROUP)}\n")
    assert resources.pressure().slice.oom_kill == 14


@pytest.mark.parametrize("memory,cpu", [("4G", "400%"), ("7G", "600%"), ("512M", "50%")])
def test_job_caps_use_slice_budget_instead_of_calling_job_limit(budgets, memory, cpu):
    resources.validate_caps(memory, cpu)


@pytest.mark.parametrize("memory,cpu", [("8G", "400%"), ("4G", "700%"), ("0", "400%"),
                                      ("4G", "0%"), ("nan", "300%"), ("4G", "nan%")])
def test_caps_above_slice_or_malformed_are_rejected(budgets, memory, cpu):
    with pytest.raises(ValueError):
        resources.validate_caps(memory, cpu)


def test_capped_command_keeps_environment_defaults_and_honors_job_override(monkeypatch):
    monkeypatch.setenv("CODEX_JOB_MEMORY_MAX", "2000M")
    monkeypatch.setenv("CODEX_JOB_CPU_QUOTA", "200%")
    monkeypatch.setattr(core.shutil, "which", lambda _: "/usr/bin/systemd-run")
    assert "MemoryMax=2000M" in core.capped(["program"])
    assert "CPUQuota=200%" in core.capped(["program"])
    command = core.capped(["program"], {"memoryMax": "4G", "cpuQuota": "400%"})
    assert "MemoryMax=4G" in command and "CPUQuota=400%" in command


def test_start_and_resume_choose_caps_at_next_launch(budgets, monkeypatch, tmp_path):
    job = tmp_path / "jobs/owner/job"
    job.mkdir(parents=True)
    (job / "prompt.md").write_text("work")
    monkeypatch.delenv(core.WORKER_FLAG, raising=False)
    monkeypatch.setattr(cli, "resolve_job", lambda _: job)
    monkeypatch.setattr(cli.reference, "warning", lambda: None)
    monkeypatch.setattr(cli.codex, "active_account", lambda: "1")
    monkeypatch.setattr(cli, "linger", lambda *args: None)
    calls = []

    def run(job, state, path, prompt, resume=False):
        calls.append((prompt, resume, core.job_caps(state)))
        state["threadId"] = "original"
        core.save(path, state)
        core.log(job, "turn_completed")

    monkeypatch.setattr(cli.codex, "run", run)
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "start", "owner/job", "--backend", "codex",
                                     "--title", "Cap probe", "--cwd", str(tmp_path),
                                     "--sandbox", "workspace-write", "--memory", "4G", "--cpu", "400%"])
    cli.main()
    monkeypatch.setattr(sys, "argv", ["agent-bridge", "resume", "owner/job",
                                     "--memory", "5G", "--cpu", "500%"])
    cli.main()
    assert calls == [("work", False, {"memoryMax": "4G", "cpuQuota": "400%"}),
                     ("Continue.", True, {"memoryMax": "5G", "cpuQuota": "500%"})]
    assert core.load_state(job)["threadId"] == "original"
