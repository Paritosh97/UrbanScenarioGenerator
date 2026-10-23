"""usg.dsl - pedestrian-aware extension of ``scenariogeneration``.

Scenario scripts do::

    from usg.dsl import *

and get the full ``xosc`` module (anything built with scenariogeneration still works) plus
the pedestrian/VR-task layer: Place, MapQuery, ScenarioBuilder, task and failure classes.
"""
from scenariogeneration import xosc

from .core import (CATEGORIES, Collision, FailureCondition, FollowTrajectory, MapQuery, Place,
                   SignalViolation, SurfaceAdherence, Target, Timeout, TriggerFailure, VRTask,
                   VRTaskCommand, at, task_action)
from .builder import (ScenarioBuilder, StartWhen, TaskHandle, USER, VEHICLE_MODELS, WALKER_MODELS,
                      when_task_done, when_task_starts, when_time, when_user_within)

__all__ = [
    "xosc", "CATEGORIES", "Collision", "FailureCondition", "FollowTrajectory", "MapQuery", "Place",
    "SignalViolation", "SurfaceAdherence", "Target", "Timeout", "TriggerFailure", "VRTask",
    "VRTaskCommand", "at", "task_action", "ScenarioBuilder", "StartWhen", "TaskHandle", "USER",
    "VEHICLE_MODELS", "WALKER_MODELS", "when_task_done", "when_task_starts", "when_time",
    "when_user_within",
]
