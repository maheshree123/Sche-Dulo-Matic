"""Sche-Dulo-Matic: a clash-free college timetable generator."""
from .models import Teacher, Room, LabRoom, Subject, Division
from .scheduler import Timetable, find_conflicts
from .loader import load_config

__all__ = ["Teacher", "Room", "LabRoom", "Subject", "Division",
           "Timetable", "find_conflicts", "load_config"]
