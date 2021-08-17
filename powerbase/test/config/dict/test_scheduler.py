
from powerbase.config import parse_dict

from powerbase.core import Scheduler, Scheduler
from powerbase.parse import parse_condition

from powerbase.conditions import AlwaysFalse

from textwrap import dedent

import sys
import pytest

@pytest.fixture(autouse=True)
def set_sys_path(tmpdir):
    # Code that will run before your test, for example:
    sys.path.append(str(tmpdir))
    print(sys.path)
    # A test function will be run at this point
    yield
    # Code that will run after your test, for example:
    sys.path.remove(str(tmpdir))

def test_no_config():
    scheduler = parse_dict(
        {}
    )
    assert scheduler is None

def test_minimal_scheduler():
    scheduler = parse_dict(
        {"scheduler": {}}
    )
    assert isinstance(scheduler, Scheduler)

def test_full_featured(tmpdir, session):
    
    with tmpdir.as_cwd() as old_dir:

        # A throw-away file to link all pre-set tasks
        tmpdir.join("funcs.py").write(dedent("""
        def do_a_task():
            pass
        """))

        project_dir = tmpdir.mkdir("projects")

        task_1 = project_dir.mkdir("annuals")
        task_1.join("main.py").write(dedent("""
        def main():
            pass
        """))
        task_1.join("config.yaml").write(dedent("""
        start_cond: daily starting 10:00
        """))

        # Task 2 will miss config file and should never run (automatically)
        project_dir.mkdir("quarterly").join("main.py").write(dedent("""
        def main():
            pass
        """))

        scheduler = parse_dict(
            {
                "parameters": {
                    "mode": "test"
                },
                "tasks": {
                    "maintain.notify-1": {"class": "FuncTask", "func": "funcs.do_a_task", "execution": "main"},
                    "maintain.notify-start-up": {"class": "FuncTask", "func": "funcs.do_a_task", "execution": "main", "on_startup": True},
                    "maintain.notify-shut-down": {"class": "FuncTask", "func": "funcs.do_a_task", "execution": "main", "on_shutdown": True},

                    "fetch.stock-prices": {"class": "FuncTask", "func": "funcs.do_a_task"},
                    "fetch.fundamentals": {"class": "FuncTask", "func": "funcs.do_a_task", "start_cond": "daily"},
                    "calculate.signals": {"class": "FuncTask", "func": "funcs.do_a_task"},
                    "report.signals": {"class": "FuncTask", "func": "funcs.do_a_task"},

                    "maintain.fetch": {"class": "FuncTask", "func": "funcs.do_a_task", "start_cond": {"class": "IsGitBehind", "fetch": True}, "execution": "main"},
                    "maintain.pull": {"class": "FuncTask", "func": "funcs.do_a_task", "execution": "main"},
                    "maintain.status": {"class": "FuncTask", "func": "funcs.do_a_task", "execution": "main"},
                },
                "sequences": {
                    "sequence.signals-1": {
                        "start_cond": "daily starting 19:00", # Start condition for the first task of the sequence
                        "tasks": [
                            "fetch.stock-prices",
                            "calculate.signals",
                            "report.signals",
                        ],
                    },
                    "sequence.signals-2": {
                        "start_cond": "daily starting 19:00", # Start condition for the first task of the sequence
                        "tasks": [
                            "fetch.fundamentals",
                            "calculate.signals",
                            "report.signals",
                        ]
                    },
                    "sequence.maintain": {
                        "tasks": [
                            "maintain.fetch",
                            "maintain.pull",
                            "maintain.status",
                        ]
                    },
                },
                "scheduler": {
                    "name": "my_scheduler",
                    "restarting": "relaunch",
                    "parameters": {"maintainers": ["myself"]}
                }
            }
        )
        
        assert isinstance(scheduler, Scheduler)

        # Assert found tasks
        tasks = {task.name for task in scheduler.tasks}
        assert {
            "fetch.stock-prices", 
            "fetch.fundamentals", 
            "calculate.signals",
            "report.signals",

            # From ProjectFinder
            # "annuals",
            # "quarterly",

            "maintain.notify-1", 
            "maintain.fetch",
            "maintain.pull",
            "maintain.status",

            "maintain.notify-start-up",
            "maintain.notify-shut-down"
        } == tasks

        assert {
            # Globals
            "mode": "test",
            # Locals
            "maintainers": ["myself"],
        } == dict(**scheduler.session.parameters)

        # Test sequences
        cond = parse_condition("daily starting 19:00")
        cond.kwargs["task"] = session.get_task("fetch.stock-prices")
        assert session.get_task("fetch.stock-prices").start_cond == cond

        
        cond = parse_condition("daily") & parse_condition("daily starting 19:00")
        cond[0].kwargs["task"] = session.get_task("fetch.fundamentals")
        cond[1].kwargs["task"] = session.get_task("fetch.fundamentals")
        assert session.get_task("fetch.fundamentals").start_cond == cond


def test_scheduler_tasks_set(tmpdir, session):
    with tmpdir.as_cwd() as old_dir:
        tmpdir.join("some_funcs.py").write(dedent("""
        def do_task_1():
            pass
        def do_task_2():
            pass
        def do_maintain():
            pass
        """))

        scheduler = parse_dict(
            {
                "tasks": {
                    "task_1": {"class": "FuncTask", "func": "some_funcs.do_task_1"},
                    "task_2": {"class": "FuncTask", "func": "some_funcs.do_task_2"},
                    "maintain.task_1": {"class": "FuncTask", "func": "some_funcs.do_maintain", "execution": "main"}
                },
                "scheduler": {
                    "name": "my_scheduler",
                    "restarting": "relaunch",
                    "parameters": {"param_a": 1, "param_b": 2}
                }
            }
        )
        assert isinstance(scheduler, Scheduler)
        assert ["task_1", "task_2", "maintain.task_1"] == [task.name for task in scheduler.tasks]
        assert ["do_task_1", "do_task_2", "do_maintain"] == [task.func.__name__ for task in scheduler.tasks]

        assert {"param_a": 1, "param_b": 2} == dict(**scheduler.session.parameters)
    