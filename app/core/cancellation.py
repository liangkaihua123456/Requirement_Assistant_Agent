"""Cooperative cancellation for running tasks.

LangGraph executes nodes synchronously in a worker thread, so an in-flight LLM
call cannot be interrupted. The queue marks the task instead, and every node
checks the flag on entry; the next node boundary aborts the run.
"""

from __future__ import annotations

_cancelled: set[str] = set()


class TaskCancelled(Exception):
    """Raised at a node boundary when the task has been cancelled."""

    def __init__(self, task_id: str) -> None:
        super().__init__(f"Task {task_id} cancelled")
        self.task_id = task_id


def request_cancel(task_id: str) -> None:
    _cancelled.add(task_id)


def is_cancelled(task_id: str) -> bool:
    return task_id in _cancelled


def clear_cancel(task_id: str) -> None:
    _cancelled.discard(task_id)
