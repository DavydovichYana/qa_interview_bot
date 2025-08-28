from pathlib import Path
import yaml

_DEFAULT_MAP = {}

def load_tags_map(path: str | Path = "data/tags_map.yaml") -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return _DEFAULT_MAP
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # ключи как str, значения как str
    return {str(k): str(v) for k, v in data.items()}

# Удобный хелпер
def render_tags(tags: list[str], mapping: dict[str, str]) -> str:
    if not tags:
        return "—"
    human = [mapping.get(t, t) for t in tags]
    # убрать дубликаты, сохранив порядок
    seen = set()
    ordered = []
    for t in human:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ", ".join(ordered)