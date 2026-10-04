"""Validate the model manifest before passing any resources into native code."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def installation_root() -> Path:
    return (
        Path(
            os.environ.get("SOMNILOOP_LIVE2D_DIR", Path(__file__).resolve().parents[3] / ".live2d")
        )
        .expanduser()
        .resolve()
    )


@dataclass
class CharacterConfig:
    enabled: bool = True
    scale: float = 1.0
    offset_x: int = 16
    offset_y: int = 16
    opacity: float = 1.0
    idle: bool = True
    interaction: bool = False
    reactions: bool = True
    captions: bool = False
    voice: bool = False

    @classmethod
    def load(cls, repository):
        try:
            raw = json.loads(repository.get_setting("live2d_config", "{}"))
            value = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
            for key in ("enabled", "idle", "interaction", "reactions", "captions", "voice"):
                if not isinstance(getattr(value, key), bool):
                    raise ValueError("Invalid boolean configuration")
            value.scale = max(0.5, min(2.0, float(value.scale)))
            value.opacity = max(0.1, min(1.0, float(value.opacity)))
            value.offset_x = max(-1000, min(1000, int(value.offset_x)))
            value.offset_y = max(-1000, min(1000, int(value.offset_y)))
            return value
        except (ValueError, TypeError, AttributeError, OverflowError):
            return cls()

    def save(self, repository):
        repository.set_setting("live2d_config", json.dumps(asdict(self)))


class ModelResources:
    def __init__(self, manifest: Path):
        self.manifest = manifest.resolve(strict=True)
        self.root = self.manifest.parent
        self.data = json.loads(self.manifest.read_text(encoding="utf-8-sig"))
        if self.data.get("Version") != 3:
            raise ValueError("Only Cubism model3 manifests are supported")
        refs = self.data["FileReferences"]
        self.resolve(refs["Moc"])
        self.textures = [self.resolve(path) for path in refs["Textures"]]
        if not self.textures:
            raise ValueError("Model has no textures")
        for key in ("Physics", "Pose", "UserData", "DisplayInfo"):
            if refs.get(key):
                path = self.resolve(refs[key])
                json.loads(path.read_text(encoding="utf-8-sig"))
        self.motions = refs.get("Motions", {})
        self.expressions = {item["Name"]: item["File"] for item in refs.get("Expressions", [])}
        for entries in self.motions.values():
            for item in entries:
                json.loads(self.resolve(item["File"]).read_text(encoding="utf-8-sig"))
                if item.get("Sound"):
                    self.resolve(item["Sound"])
        for path in self.expressions.values():
            json.loads(self.resolve(path).read_text(encoding="utf-8-sig"))
        self.display_info = (
            json.loads(self.resolve(refs["DisplayInfo"]).read_text(encoding="utf-8-sig"))
            if refs.get("DisplayInfo")
            else {}
        )

    def resolve(self, name: str) -> Path:
        if not isinstance(name, str) or not name or "\\" in name or Path(name).is_absolute():
            raise ValueError("Invalid Live2D resource path")
        path = (self.root / name).resolve(strict=True)
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError("Live2D resource escapes the model directory")
        if not 0 < path.stat().st_size <= 64 * 1024 * 1024:
            raise ValueError("Empty or oversized Live2D resource")
        return path

    def expression_named(self, stem: str) -> str | None:
        return next(
            (
                name
                for name in self.expressions
                if name.casefold().removesuffix(".exp3.json") == stem.casefold()
            ),
            None,
        )


def epsilon_manifest() -> Path:
    return installation_root() / "epsilon/epsilon_pro/runtime/Epsilon.model3.json"
