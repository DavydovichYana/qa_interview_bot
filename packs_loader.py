import os
from typing import Dict, Any, List
import yaml
import random

def load_packs(dir_path: str = "data/packs") -> Dict[str, Any]:
    packs: Dict[str, Any] = {}
    if not os.path.isdir(dir_path):
        return packs
    for name in os.listdir(dir_path):
        if not name.endswith(".yaml"):
            continue
        path = os.path.join(dir_path, name)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        code = data["pack"]["code"]
        packs[code] = data
    return packs

def pick_questions(pack: Dict[str, Any], n: int = 10) -> List[Dict[str, Any]]:
    qs = list(pack.get("questions", []))
    random.shuffle(qs)
    return qs[:n]