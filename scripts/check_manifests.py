"""Static consistency checks, not a replacement for applying to a test cluster."""
from pathlib import Path
import yaml

root = Path(__file__).resolve().parents[1]
paths = sorted(p for p in root.rglob("*.yml") if not any(x in p.parts for x in (".cache", "work", ".git")))
paths += sorted(p for p in root.rglob("*.yaml") if not any(x in p.parts for x in (".cache", "work", ".git")))
for path in paths:
    list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
objects = list(yaml.safe_load_all((root / "kubernetes/resources.yaml").read_text()))
names = {(obj["kind"], obj["metadata"]["name"]) for obj in objects}
assert len(names) == len(objects), "duplicate Kubernetes object"
for obj in objects:
    if obj["kind"] in ("Deployment", "StatefulSet"):
        spec = obj["spec"]
        labels = spec["template"]["metadata"]["labels"]
        assert all(labels[k] == v for k, v in spec["selector"]["matchLabels"].items())
        for container in spec["template"]["spec"]["containers"]:
            assert "resources" in container and "readinessProbe" in container
            for source in container.get("envFrom", []):
                if "configMapRef" in source:
                    assert ("ConfigMap", source["configMapRef"]["name"]) in names
    if obj["kind"] == "ConfigMap" and obj["metadata"]["name"] == "privateai-schema":
        assert obj["data"]["001_init.sql"] == (root / "migrations/001_init.sql").read_text()
print(f"Parsed {len(paths)} YAML files; checked {len(objects)} Kubernetes objects and embedded migration consistency.")
