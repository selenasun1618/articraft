from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.examples import search_example_documents
from agent.tools.base import (
    BaseDeclarativeTool,
    BaseToolInvocation,
    ToolParamsModel,
    ToolResult,
    make_tool_schema,
    validate_tool_params,
)


class FindExamplesParams(ToolParamsModel):
    query: str
    limit: int = 3


class FindExamplesInvocation(BaseToolInvocation[FindExamplesParams, list[dict[str, object]]]):
    def __init__(
        self,
        params: FindExamplesParams,
        *,
        sdk_package: str,
        include_paths: bool,
    ) -> None:
        super().__init__(params)
        self.sdk_package = sdk_package
        self.include_paths = include_paths

    def get_description(self) -> str:
        return (
            f"Run lexical example search over curated {self.sdk_package} examples for "
            f"query={self.params.query!r} (limit={self.params.limit})"
        )

    async def execute(self) -> ToolResult:
        query = self.params.query.strip()
        if not query:
            return ToolResult(error="query must not be empty")
        if self.params.limit < 1:
            return ToolResult(error="limit must be >= 1")

        if self.sdk_package == "sdk_lego":
            from sdk_lego import find_lego_parts

            matches = find_lego_parts(query, limit=self.params.limit)
            return ToolResult(output=[self._serialize_lego_part(part) for part in matches])

        matches = search_example_documents(
            query,
            sdk_package=self.sdk_package,
            limit=self.params.limit,
        )
        return ToolResult(output=[self._serialize_match(doc) for doc in matches])

    def _serialize_lego_part(self, part: Any) -> dict[str, object]:
        ldraw_ids = list(getattr(part, "ldraw_ids", ()) or ())
        content = (
            f"LEGO catalog part {part.part_num}: {part.name}\n"
            f"- Rebrickable part_num: {part.part_num}\n"
            f"- LDraw IDs: {', '.join(ldraw_ids) if ldraw_ids else part.part_num}\n"
            f"- Suggested LDraw file: {part.ldraw_filename}\n"
            f"- Nominal stud footprint: {part.nominal_size or 'unknown'}\n"
            "- Use with sdk_lego.ArticulatedObject.part(...)."
        )
        result: dict[str, object] = {
            "example_id": f"lego_part:{part.part_num}",
            "title": part.name,
            "description": f"LEGO catalog part {part.part_num}",
            "tags": ["lego", "part", str(getattr(part, "part_cat_id", "") or "unknown")],
            "content": content,
            "match_quality": "catalog",
            "matched_tokens": [],
            "matched_fields": ["rebrickable_catalog"],
            "part_num": part.part_num,
            "ldraw_ids": ldraw_ids,
            "ldraw_filename": part.ldraw_filename,
            "nominal_size": part.nominal_size,
        }
        if self.include_paths:
            result["path"] = f"rebrickable://lego/parts/{part.part_num}"
        return result

    def _serialize_match(self, doc: Any) -> dict[str, object]:
        relative_path = doc.path.relative_to(Path(__file__).resolve().parents[2]).as_posix()
        result: dict[str, object] = {
            "example_id": relative_path,
            "title": doc.title,
            "description": doc.description,
            "tags": list(doc.tags),
            "content": doc.content,
            "match_quality": doc.match_quality,
            "matched_tokens": list(doc.matched_tokens),
            "matched_fields": list(doc.matched_fields),
        }
        if self.include_paths:
            result["path"] = relative_path
        return result


class FindExamplesTool(BaseDeclarativeTool):
    def __init__(self, *, sdk_package: str, include_paths: bool = True) -> None:
        self.sdk_package = sdk_package
        self.include_paths = include_paths
        schema = make_tool_schema(
            name="find_examples",
            description=(
                "Run lexical search over curated example documents for the active SDK and "
                "return sufficiently relevant full markdown matches.\n\n"
                "Search checks file names, titles, descriptions, tags, prose, and code "
                "identifiers. It works best with short concrete queries such as object names, "
                "feature names, geometry operations, CadQuery API names, or exact example "
                "titles.\n\n"
                "When strong matches do not exist, the tool may return `[weakly relevant]` "
                "results as inspiration-only hints. Treat those cautiously.\n\n"
                "This does not search SDK docs, tests, test helper APIs, or arbitrary "
                "repository code. It is not a general API search tool.\n\n"
                "If relevance is weak, the search may return fewer than limit results."
            ),
            parameters={
                "query": {
                    "type": "string",
                    "description": (
                        "Short lexical query. Prefer concrete nouns, feature names, API names, "
                        "or example titles over long natural-language descriptions."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Maximum number of full example documents to return. Search may return "
                        "fewer if relevance is weak."
                    ),
                },
            },
            required=["query"],
        )
        super().__init__("find_examples", schema)

    async def build(self, params: dict) -> FindExamplesInvocation:
        validated = validate_tool_params(FindExamplesParams, params)
        return FindExamplesInvocation(
            validated,
            sdk_package=self.sdk_package,
            include_paths=self.include_paths,
        )
