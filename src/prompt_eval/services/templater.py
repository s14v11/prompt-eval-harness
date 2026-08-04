"""Jinja2-based rendering of prompt templates.

Templates are user-authored content, so rendering uses Jinja2's sandboxed
environment to prevent access to unsafe attributes or builtins.
"""

from __future__ import annotations

from jinja2 import meta
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

_env = SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True)


class TemplateRenderError(Exception):
    """Raised when a Jinja2 template fails to parse or render."""


def extract_variables(template: str) -> list[str]:
    """Return the sorted list of undeclared variable names referenced by `template`.

    Args:
        template: A Jinja2 template source string.

    Returns:
        Sorted variable names the template expects the caller to supply.

    Raises:
        TemplateRenderError: If the template has a syntax error.
    """
    try:
        ast = _env.parse(template)
    except TemplateError as exc:
        raise TemplateRenderError(f"Invalid template syntax: {exc}") from exc
    return sorted(meta.find_undeclared_variables(ast))


def render_prompt(template: str, variables: dict) -> str:
    """Render a Jinja2 prompt template with the given variables.

    Args:
        template: A Jinja2 template source string.
        variables: Mapping of variable names to values used during rendering.

    Returns:
        The rendered prompt text.

    Raises:
        TemplateRenderError: If the template fails to parse or render.
    """
    try:
        compiled = _env.from_string(template)
        return compiled.render(**variables)
    except TemplateError as exc:
        raise TemplateRenderError(f"Failed to render template: {exc}") from exc
