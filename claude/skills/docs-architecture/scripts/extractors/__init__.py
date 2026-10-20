"""Extractors: each module exposes extract(root) -> {components, edges, boundaries, unknowns, confidence}."""
from . import terraform

EXTRACTORS = [("terraform", terraform)]
