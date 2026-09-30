#!/usr/bin/env python3
"""Load seed/corpus.yaml into the database.   Usage: python scripts/load_seed.py [path]

Runs in one transaction: either the whole file loads or nothing does.
Needs the package installed (pip install -e .) and `make up && make migrate` done.
"""

import pathlib
import sys

import yaml

from app.db import SessionLocal
from app.seed import SeedError, load_seed

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "seed/corpus.yaml")

try:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
except (OSError, yaml.YAMLError) as e:
    sys.exit(f"{path}: {e}")

with SessionLocal() as db:
    try:
        counts = load_seed(db, doc, base_dir=path.parent)
        db.commit()
    except SeedError as e:
        db.rollback()
        sys.exit(f"{path}: {e}")

print(f"{path}: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
