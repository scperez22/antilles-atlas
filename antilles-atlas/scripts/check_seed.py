import sys, yaml, pathlib

for p in pathlib.Path("seed").glob("*.yaml"):
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        sys.exit(f"{p}: {e}")
    if doc is None:
        print(f"{p}: empty")
        continue
    claims = doc.get("claims") or []
    keys = {s["key"] for s in (doc.get("sources") or [])}
    for c in claims:
        for a in c.get("attachments") or []:
            if a["source"] not in keys:
                sys.exit(f"{c['id']}: unknown source {a['source']!r}")
    print(f"{p}: {len(keys)} sources, {len(claims)} claims")