from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from videouniq.core.params import UniqueParams
from videouniq.core.probe import MediaInfo


class FileStatus(str, Enum):
    PENDING = "pending"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class FileItem:
    path: str
    item_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    info: MediaInfo | None = None
    preview_path: str = ""
    status: FileStatus = FileStatus.PENDING
    progress: float = 0.0
    copies_done: int = 0
    copies_total: int = 0
    error: str = ""
    output_dir: str = ""
    message: str = ""
    kind: str = "video"  # video | project
    project_path: str = ""
    project_dict: dict | None = None


@dataclass
class CopyJob:
    item_id: str
    source_path: str
    copy_index: int
    copies_total: int
    dest: str
    params: UniqueParams
    media: MediaInfo
    project_dict: dict | None = None
    save_master: bool = False
    is_master: bool = False
