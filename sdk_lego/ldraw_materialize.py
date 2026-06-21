from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]

_IDENTITY_MATRIX: Matrix3 = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)
_ZERO_VECTOR: Vector3 = (0.0, 0.0, 0.0)
_DEFAULT_COLOR_ID = 7
_CURRENT_COLOR_ID = 16
_LDRAW_UNIT_TO_METERS = 0.0004

_FALLBACK_COLORS: dict[int, tuple[str, tuple[float, float, float], float]] = {
    0: ("black", (0.02, 0.02, 0.02), 1.0),
    1: ("blue", (0.0, 0.2, 0.7), 1.0),
    2: ("green", (0.0, 0.5, 0.2), 1.0),
    3: ("dark_turquoise", (0.0, 0.45, 0.5), 1.0),
    4: ("red", (0.75, 0.05, 0.05), 1.0),
    5: ("dark_pink", (0.8, 0.15, 0.4), 1.0),
    6: ("brown", (0.35, 0.18, 0.08), 1.0),
    7: ("light_gray", (0.62, 0.62, 0.58), 1.0),
    8: ("dark_gray", (0.28, 0.28, 0.28), 1.0),
    9: ("light_blue", (0.35, 0.7, 1.0), 1.0),
    10: ("bright_green", (0.25, 0.85, 0.35), 1.0),
    11: ("light_turquoise", (0.45, 0.85, 0.8), 1.0),
    12: ("salmon", (0.95, 0.45, 0.35), 1.0),
    13: ("pink", (1.0, 0.6, 0.8), 1.0),
    14: ("yellow", (0.95, 0.8, 0.05), 1.0),
    15: ("white", (0.92, 0.92, 0.88), 1.0),
    16: ("current", (0.62, 0.62, 0.58), 1.0),
    24: ("edge", (0.08, 0.08, 0.08), 1.0),
}


class LDrawParseError(ValueError):
    """Raised when an LDraw/MPD line cannot be parsed."""


class LDrawResolutionError(FileNotFoundError):
    """Raised when a referenced LDraw subfile cannot be resolved."""


@dataclass(frozen=True, slots=True)
class LDrawSubfileRef:
    color_id: int
    translation: Vector3
    matrix: Matrix3
    filename: str
    line_number: int


@dataclass(frozen=True, slots=True)
class LDrawTriangle:
    color_id: int
    vertices: tuple[Vector3, Vector3, Vector3]
    line_number: int


@dataclass(frozen=True, slots=True)
class LDrawQuad:
    color_id: int
    vertices: tuple[Vector3, Vector3, Vector3, Vector3]
    line_number: int


LDrawCommand = LDrawSubfileRef | LDrawTriangle | LDrawQuad


@dataclass(frozen=True, slots=True)
class LDrawFile:
    name: str
    commands: tuple[LDrawCommand, ...]


@dataclass(frozen=True, slots=True)
class LDrawDocument:
    files: dict[str, LDrawFile]
    main_file: str


@dataclass(frozen=True, slots=True)
class LDrawMeshTriangle:
    color_id: int
    vertices: tuple[Vector3, Vector3, Vector3]


@dataclass(frozen=True, slots=True)
class LDrawMesh:
    triangles: tuple[LDrawMeshTriangle, ...]


@dataclass(frozen=True, slots=True)
class LDrawObjMaterialization:
    obj_path: Path
    mtl_path: Path
    triangle_count: int
    material_count: int

    def to_sidecar(self, *, asset_root: Path | None = None) -> dict[str, object]:
        obj_path = self.obj_path
        mtl_path = self.mtl_path
        if asset_root is not None:
            try:
                obj_path = obj_path.relative_to(asset_root)
                mtl_path = mtl_path.relative_to(asset_root)
            except ValueError:
                pass
        return {
            "format": "obj",
            "path": obj_path.as_posix(),
            "material_path": mtl_path.as_posix(),
            "triangle_count": self.triangle_count,
            "material_count": self.material_count,
            "coordinate_frame": "articraft_z_up_meters",
        }


def parse_ldraw_mpd(text: str, *, default_name: str = "main.ldr") -> LDrawDocument:
    files: dict[str, LDrawFile] = {}
    current_name: str | None = None
    current_commands: list[LDrawCommand] = []
    main_file: str | None = None

    def flush_current() -> None:
        nonlocal current_commands, current_name, main_file
        if current_name is None:
            return
        files[current_name] = LDrawFile(current_name, tuple(current_commands))
        if main_file is None:
            main_file = current_name
        current_commands = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("0"):
            tokens = line.split(maxsplit=2)
            if len(tokens) >= 3 and tokens[1].upper() == "FILE":
                flush_current()
                current_name = tokens[2].strip()
            continue
        if current_name is None:
            current_name = default_name
        if line[0] in {"2", "5"}:
            continue
        current_commands.append(_parse_command(line, line_number=line_number))

    flush_current()
    if not files:
        files[default_name] = LDrawFile(default_name, ())
        main_file = default_name
    assert main_file is not None
    return LDrawDocument(files=files, main_file=main_file)


class LDrawResolver:
    def __init__(self, document: LDrawDocument, *, library_root: Path | str | None = None) -> None:
        self.document = document
        self.library_root = Path(library_root) if library_root is not None else None
        self._cache: dict[str, LDrawFile] = {
            _normalize_ldraw_name(name): ldraw_file for name, ldraw_file in document.files.items()
        }

    def resolve(self, filename: str) -> LDrawFile:
        key = _normalize_ldraw_name(filename)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if self.library_root is None:
            raise LDrawResolutionError(
                f"LDraw subfile {filename!r} is not embedded in the MPD and no library root is configured"
            )

        local_path = self._find_local_file(filename)
        local_doc = parse_ldraw_mpd(local_path.read_text(encoding="utf-8"), default_name=filename)
        for name, ldraw_file in local_doc.files.items():
            self._cache[_normalize_ldraw_name(name)] = ldraw_file
        resolved = self._cache.get(key) or local_doc.files[local_doc.main_file]
        self._cache[key] = resolved
        return resolved

    def _find_local_file(self, filename: str) -> Path:
        relative = Path(filename.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise LDrawResolutionError(f"Unsafe LDraw subfile reference: {filename!r}")

        names = [relative]
        lower_relative = Path(relative.as_posix().lower())
        if lower_relative != relative:
            names.append(lower_relative)

        candidates: list[Path] = []
        for name in names:
            candidates.append(self.library_root / name)
            if not name.parts or name.parts[0].lower() != "parts":
                candidates.append(self.library_root / "parts" / name)
            if not name.parts or name.parts[0].lower() != "p":
                candidates.append(self.library_root / "p" / name)

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        searched = ", ".join(path.as_posix() for path in candidates)
        raise LDrawResolutionError(
            f"LDraw subfile {filename!r} was not found under {self.library_root} "
            f"(searched: {searched})"
        )


def flatten_ldraw_document(
    document: LDrawDocument,
    *,
    resolver: LDrawResolver | None = None,
    main_file: str | None = None,
    default_color_id: int = _DEFAULT_COLOR_ID,
) -> LDrawMesh:
    resolver = resolver or LDrawResolver(document)
    root_name = main_file or document.main_file
    root = resolver.resolve(root_name)
    triangles: list[LDrawMeshTriangle] = []
    _flatten_file(
        root,
        resolver=resolver,
        transform=(_IDENTITY_MATRIX, _ZERO_VECTOR),
        inherited_color_id=default_color_id,
        triangles=triangles,
        stack=(),
    )
    return LDrawMesh(tuple(triangles))


def materialize_ldraw_mpd_to_obj(
    mpd_text: str,
    *,
    output_path: Path,
    library_root: Path | str | None = None,
    default_color_id: int = _DEFAULT_COLOR_ID,
    ldraw_unit_to_meters: float = _LDRAW_UNIT_TO_METERS,
) -> LDrawObjMaterialization:
    document = parse_ldraw_mpd(mpd_text)
    if library_root is None:
        env_root = os.environ.get("ARTICRAFT_LDRAW_CACHE_DIR")
        library_root = Path(env_root) if env_root else Path("data/cache/lego/ldraw")
    resolver = LDrawResolver(document, library_root=library_root)
    mesh = flatten_ldraw_document(
        document,
        resolver=resolver,
        default_color_id=default_color_id,
    )
    return write_ldraw_mesh_obj(
        mesh,
        output_path=output_path,
        ldraw_unit_to_meters=ldraw_unit_to_meters,
    )


def write_ldraw_mesh_obj(
    mesh: LDrawMesh,
    *,
    output_path: Path,
    ldraw_unit_to_meters: float = _LDRAW_UNIT_TO_METERS,
) -> LDrawObjMaterialization:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = output_path.with_suffix(".mtl")
    material_ids = _ordered_unique(triangle.color_id for triangle in mesh.triangles)

    obj_lines = [
        "# Articraft LDraw OBJ materialization",
        f"mtllib {mtl_path.name}",
        "o lego_ldraw_model",
    ]
    vertex_index = 1
    active_material: int | None = None
    for triangle in mesh.triangles:
        if triangle.color_id != active_material:
            obj_lines.append(f"usemtl {_material_name(triangle.color_id)}")
            active_material = triangle.color_id
        for vertex in triangle.vertices:
            x, y, z = _ldraw_to_articraft_meters(vertex, scale=ldraw_unit_to_meters)
            obj_lines.append(f"v {_num(x)} {_num(y)} {_num(z)}")
        obj_lines.append(f"f {vertex_index} {vertex_index + 1} {vertex_index + 2}")
        vertex_index += 3
    obj_lines.append("")

    mtl_lines = ["# Articraft LDraw material fallback table"]
    for color_id in material_ids or [_DEFAULT_COLOR_ID]:
        name, (red, green, blue), alpha = _color_info(color_id)
        mtl_lines.extend(
            [
                f"newmtl {_material_name(color_id)}",
                f"# LDraw color {color_id}: {name}",
                f"Kd {_num(red)} {_num(green)} {_num(blue)}",
                f"d {_num(alpha)}",
                "Ka 0 0 0",
                "Ks 0.08 0.08 0.08",
                "Ns 16",
                "",
            ]
        )

    output_path.write_text("\n".join(obj_lines), encoding="utf-8")
    mtl_path.write_text("\n".join(mtl_lines), encoding="utf-8")
    return LDrawObjMaterialization(
        obj_path=output_path,
        mtl_path=mtl_path,
        triangle_count=len(mesh.triangles),
        material_count=len(material_ids),
    )


def _parse_command(line: str, *, line_number: int) -> LDrawCommand:
    record_type = line[0]
    if record_type == "1":
        tokens = line.split(maxsplit=14)
        if len(tokens) != 15:
            raise LDrawParseError(
                f"Invalid type 1 subfile reference on line {line_number}: {line!r}"
            )
        color_id = _parse_int(tokens[1], line_number=line_number)
        numbers = [_parse_float(token, line_number=line_number) for token in tokens[2:14]]
        translation = (numbers[0], numbers[1], numbers[2])
        matrix = (
            (numbers[3], numbers[4], numbers[5]),
            (numbers[6], numbers[7], numbers[8]),
            (numbers[9], numbers[10], numbers[11]),
        )
        return LDrawSubfileRef(
            color_id=color_id,
            translation=translation,
            matrix=matrix,
            filename=tokens[14].strip(),
            line_number=line_number,
        )
    if record_type == "3":
        tokens = line.split()
        if len(tokens) != 11:
            raise LDrawParseError(f"Invalid type 3 triangle on line {line_number}: {line!r}")
        color_id = _parse_int(tokens[1], line_number=line_number)
        numbers = [_parse_float(token, line_number=line_number) for token in tokens[2:]]
        return LDrawTriangle(
            color_id=color_id,
            vertices=(
                (numbers[0], numbers[1], numbers[2]),
                (numbers[3], numbers[4], numbers[5]),
                (numbers[6], numbers[7], numbers[8]),
            ),
            line_number=line_number,
        )
    if record_type == "4":
        tokens = line.split()
        if len(tokens) != 14:
            raise LDrawParseError(f"Invalid type 4 quad on line {line_number}: {line!r}")
        color_id = _parse_int(tokens[1], line_number=line_number)
        numbers = [_parse_float(token, line_number=line_number) for token in tokens[2:]]
        return LDrawQuad(
            color_id=color_id,
            vertices=(
                (numbers[0], numbers[1], numbers[2]),
                (numbers[3], numbers[4], numbers[5]),
                (numbers[6], numbers[7], numbers[8]),
                (numbers[9], numbers[10], numbers[11]),
            ),
            line_number=line_number,
        )
    raise LDrawParseError(f"Unsupported LDraw record type {record_type!r} on line {line_number}")


def _flatten_file(
    ldraw_file: LDrawFile,
    *,
    resolver: LDrawResolver,
    transform: tuple[Matrix3, Vector3],
    inherited_color_id: int,
    triangles: list[LDrawMeshTriangle],
    stack: tuple[str, ...],
) -> None:
    file_key = _normalize_ldraw_name(ldraw_file.name)
    if file_key in stack:
        cycle = " -> ".join((*stack, file_key))
        raise LDrawResolutionError(f"Cyclic LDraw subfile reference detected: {cycle}")
    stack = (*stack, file_key)
    for command in ldraw_file.commands:
        if isinstance(command, LDrawSubfileRef):
            child = resolver.resolve(command.filename)
            child_color = _resolve_color(command.color_id, inherited_color_id)
            _flatten_file(
                child,
                resolver=resolver,
                transform=_compose_transform(transform, (command.matrix, command.translation)),
                inherited_color_id=child_color,
                triangles=triangles,
                stack=stack,
            )
            continue
        if isinstance(command, LDrawTriangle):
            color_id = _resolve_color(command.color_id, inherited_color_id)
            triangles.append(
                LDrawMeshTriangle(
                    color_id=color_id,
                    vertices=tuple(
                        _apply_transform(transform, vertex) for vertex in command.vertices
                    ),
                )
            )
            continue
        if isinstance(command, LDrawQuad):
            color_id = _resolve_color(command.color_id, inherited_color_id)
            v1, v2, v3, v4 = (_apply_transform(transform, vertex) for vertex in command.vertices)
            triangles.append(LDrawMeshTriangle(color_id=color_id, vertices=(v1, v2, v3)))
            triangles.append(LDrawMeshTriangle(color_id=color_id, vertices=(v1, v3, v4)))


def _compose_transform(
    parent: tuple[Matrix3, Vector3],
    child: tuple[Matrix3, Vector3],
) -> tuple[Matrix3, Vector3]:
    parent_matrix, parent_translation = parent
    child_matrix, child_translation = child
    matrix = _matmul(parent_matrix, child_matrix)
    translation = _add(_matvec(parent_matrix, child_translation), parent_translation)
    return matrix, translation


def _apply_transform(transform: tuple[Matrix3, Vector3], vertex: Vector3) -> Vector3:
    matrix, translation = transform
    return _add(_matvec(matrix, vertex), translation)


def _matmul(left: Matrix3, right: Matrix3) -> Matrix3:
    return tuple(
        tuple(sum(left[row][k] * right[k][col] for k in range(3)) for col in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _matvec(matrix: Matrix3, vector: Vector3) -> Vector3:
    return tuple(sum(matrix[row][col] * vector[col] for col in range(3)) for row in range(3))  # type: ignore[return-value]


def _add(left: Vector3, right: Vector3) -> Vector3:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def _ldraw_to_articraft_meters(vertex: Vector3, *, scale: float) -> Vector3:
    x, y, z = vertex
    return (x * scale, z * scale, -y * scale)


def _resolve_color(color_id: int, inherited_color_id: int) -> int:
    if color_id == _CURRENT_COLOR_ID:
        return inherited_color_id if inherited_color_id != _CURRENT_COLOR_ID else _DEFAULT_COLOR_ID
    return color_id


def _ordered_unique(values: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _color_info(color_id: int) -> tuple[str, tuple[float, float, float], float]:
    return _FALLBACK_COLORS.get(color_id, (f"color_{color_id}", (0.7, 0.7, 0.7), 1.0))


def _material_name(color_id: int) -> str:
    name, _, _ = _color_info(color_id)
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_") or "color"
    return f"ldraw_{color_id}_{safe_name}"


def _normalize_ldraw_name(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def _parse_int(value: str, *, line_number: int) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise LDrawParseError(f"Invalid integer {value!r} on line {line_number}") from exc


def _parse_float(value: str, *, line_number: int) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise LDrawParseError(f"Invalid number {value!r} on line {line_number}") from exc


def _num(value: float) -> str:
    if abs(value) < 1e-12:
        value = 0.0
    return f"{float(value):.9g}"
