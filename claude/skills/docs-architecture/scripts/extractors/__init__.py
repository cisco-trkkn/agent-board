"""Extractors: each module exposes extract(root) -> {components, edges, boundaries, unknowns, confidence}."""
from . import terraform, gitlab_ci, procfile

EXTRACTORS = [("terraform", terraform), ("gitlab_ci", gitlab_ci), ("procfile", procfile)]
