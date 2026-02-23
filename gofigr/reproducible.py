"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

Reproducible decorator for executing functions in a clean room environment
with optional interactive widgets for parameter exploration.
"""
# pylint: disable=global-statement, import-outside-toplevel, import-error
import ast
import contextvars
import functools
import importlib
import inspect
import textwrap
import traceback
import types
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, get_type_hints

from gofigr.cleanroom import (Param, SliderParam, DropdownParam, CheckboxParam,  # pylint: disable=unused-import  # noqa: F401
                               TextParam, StaticParam, infer_param)
from gofigr.utils import read_resource_text


@dataclass(frozen=True)
class ReproducibleContext:
    """Captures the execution context of a @reproducible function."""
    source_code: str
    function_name: str
    packages: Dict[str, str]
    imports: Dict[str, str]
    package_versions: Dict[str, str]
    parameters: Dict[str, Any]
    param_descriptors: Optional[Dict[str, Param]] = None


_reproducible_context: contextvars.ContextVar[Optional['ReproducibleContext']] = contextvars.ContextVar(
    '_reproducible_context', default=None
)


# Default package registry - common data science packages
DEFAULT_PACKAGES = {
    "pd": "pandas",
    "np": "numpy",
    "plt": "matplotlib.pyplot",
    "sns": "seaborn",
}

# Global default packages that can be modified by users
_global_default_packages: Dict[str, str] = DEFAULT_PACKAGES.copy()


def set_default_packages(packages: Dict[str, str], merge: bool = True) -> None:
    """
    Set the global default packages available in reproducible functions.

    :param packages: Dictionary mapping alias to module name, e.g. {"pd": "pandas"}
    :param merge: If True, merge with existing defaults. If False, replace entirely.

    Example:
        set_default_packages({"tf": "tensorflow", "torch": "torch"})
    """
    global _global_default_packages
    if merge:
        _global_default_packages.update(packages)
    else:
        _global_default_packages = packages.copy()


def get_default_packages() -> Dict[str, str]:
    """Return a copy of the current default packages."""
    return _global_default_packages.copy()


def reset_default_packages() -> None:
    """Reset default packages to the built-in defaults."""
    global _global_default_packages
    _global_default_packages = DEFAULT_PACKAGES.copy()


def _extract_function_body(func: Callable) -> str:
    """\
    Extract the body of a function as dedented source code, stripping the
    decorator(s) and ``def`` line.

    Uses ``ast.parse`` for robust extraction that handles multi-line decorators,
    docstrings, and arbitrary decorator syntax.

    :param func: The function whose body to extract.
    :return: The dedented source code of the function body.
    """
    source = inspect.getsource(func)
    dedented = textwrap.dedent(source)
    lines = dedented.splitlines(keepends=True)

    tree = ast.parse(dedented)
    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func.__name__:
                func_node = node
                break
    if func_node is None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_node = node
                break

    if func_node is None or not func_node.body:
        return dedented

    body_start = func_node.body[0].lineno - 1
    body_end = func_node.body[-1].end_lineno
    body_lines = lines[body_start:body_end]

    return textwrap.dedent("".join(body_lines))


def _is_interactive_env() -> bool:
    """
    Detect if running in an interactive Jupyter/IPython environment.

    Returns True if:
    - Running in a Jupyter notebook (has kernel)
    - Running in IPython with a display capability

    Returns False if:
    - Running as a plain Python script
    - IPython is not available
    """
    try:
        from IPython import get_ipython
        ipy = get_ipython()
        if ipy is None:
            return False
        # Check if we have a kernel (Jupyter) or at least IPython
        return hasattr(ipy, 'kernel') or 'IPKernelApp' in ipy.config
    except ImportError:
        return False


def _resolve_package_versions(packages: Dict[str, str]) -> Dict[str, str]:
    """\
    Resolve installed versions for each package.

    :param packages: Dictionary mapping alias to module name
    :return: Dictionary mapping canonical package name to version string (or None)
    """
    from importlib.metadata import version, PackageNotFoundError

    result = {}
    for module_name in set(packages.values()):
        top_level = module_name.split(".")[0]
        ver = None

        try:
            ver = version(top_level)
        except PackageNotFoundError:
            try:
                from importlib.metadata import packages_distributions
                dist_map = packages_distributions()
                dists = dist_map.get(top_level, [])
                if dists:
                    ver = version(dists[0])
            except (ImportError, PackageNotFoundError):
                pass

        result[top_level] = ver

    return result


def _build_clean_globals(packages: Dict[str, str],
                         extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Build a clean globals dictionary by importing the specified packages.

    :param packages: Dictionary mapping alias to module name
    :param extra: Additional entries to inject (e.g. publish function)
    :return: Dictionary suitable for use as function globals
    """
    clean = {"__builtins__": __builtins__}

    for alias, module_name in packages.items():
        try:
            clean[alias] = importlib.import_module(module_name)
        except ImportError as e:
            warnings.warn(f"Could not import {module_name} as {alias}: {e}")

    if extra:
        clean.update(extra)

    return clean


def _load_widget_js() -> str:
    """Load the widget JavaScript from the resources directory."""
    return read_resource_text("gofigr.resources", "reproducible_widget.js")


class ReproducibleWidget:
    """
    Lazy-loaded widget class that wraps anywidget.
    Only imports anywidget when actually instantiated.
    """
    _widget_class = None

    @classmethod
    def _get_widget_class(cls):
        if cls._widget_class is None:
            import anywidget
            import traitlets

            js_code = _load_widget_js()

            class _ReproducibleWidgetImpl(anywidget.AnyWidget):
                _esm = js_code
                params = traitlets.Dict().tag(sync=True)
                param_meta = traitlets.Dict().tag(sync=True)

            cls._widget_class = _ReproducibleWidgetImpl
        return cls._widget_class

    def __new__(cls, **kwargs):
        widget_class = cls._get_widget_class()
        return widget_class(**kwargs)  # pylint: disable=not-callable


def _run_clean(func: Callable, params: Dict[str, Any], packages: Dict[str, str],
               show_plot: bool = True, extra_globals: Optional[Dict[str, Any]] = None) -> Any:
    """
    Execute a function in a clean room environment with isolated globals.

    :param func: The function to execute
    :param params: Keyword arguments to pass to the function
    :param packages: Package mapping for the clean globals
    :param show_plot: Whether to call plt.show() after execution
    :param extra_globals: Additional entries to inject into the clean globals
    :return: The function's return value
    """
    clean_globals = _build_clean_globals(packages, extra=extra_globals)

    # Create isolated function with clean globals
    # Preserve closures if the function has any
    isolated_func = types.FunctionType(
        func.__code__,
        clean_globals,
        name=func.__name__,
        argdefs=func.__defaults__,
        closure=func.__closure__
    )

    # Copy over any function attributes
    isolated_func.__kwdefaults__ = func.__kwdefaults__
    isolated_func.__annotations__ = func.__annotations__

    result = isolated_func(**params)  # pylint: disable=not-callable

    # Show plot if matplotlib was used
    if show_plot and "plt" in clean_globals:
        plt = clean_globals["plt"]
        if plt.get_fignums():  # Only show if there are figures
            plt.show()

    return result


def _run_interactive(func: Callable, bound_args: Dict[str, Any],  # pylint: disable=too-many-locals
                     packages: Dict[str, str],
                     base_ctx: Optional['ReproducibleContext'] = None) -> None:
    """
    Run function with interactive widgets for parameter exploration.

    :param func: The decorated function
    :param bound_args: All bound arguments
    :param packages: Package mapping for clean globals
    :param base_ctx: ReproducibleContext from the wrapper, used to set context var on each re-render
    """
    # Lazy imports for interactive mode
    import ipywidgets as widgets
    from IPython.display import display, clear_output

    # Build widget metadata from Param descriptors stored in the context
    descriptors = (base_ctx.param_descriptors or {}) if base_ctx else {}
    param_meta = {}
    for name, value in bound_args.items():
        desc = descriptors.get(name)
        if desc is None:
            desc = infer_param(name, value)
        meta = desc.to_widget_meta()
        meta["value"] = value
        meta["name"] = name
        param_meta[name] = meta

    # Separate interactive params from static ones
    interactive_params = {k: v["value"] for k, v in param_meta.items()
                          if v["type"] != "static"}
    static_params = {k: v["value"] for k, v in param_meta.items()
                     if v["type"] == "static"}

    # Filter metadata to only interactive params
    interactive_meta = {k: v for k, v in param_meta.items()
                        if v["type"] != "static"}

    # Create widget
    widget = ReproducibleWidget(params=interactive_params, param_meta=interactive_meta)

    # Output widget to capture plots and prints
    out = widgets.Output()

    def on_change(change):
        with out:
            clear_output(wait=True)
            merged_params = {**static_params, **change['new']}
            ctx = ReproducibleContext(
                source_code=base_ctx.source_code,
                function_name=base_ctx.function_name,
                packages=base_ctx.packages,
                imports=base_ctx.imports,
                package_versions=base_ctx.package_versions,
                parameters=merged_params,
                param_descriptors=base_ctx.param_descriptors,
            ) if base_ctx is not None else None
            token = _reproducible_context.set(ctx) if ctx is not None else None
            try:
                _run_clean(func, merged_params, packages, show_plot=True)
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"Error: {e}")
                traceback.print_exc()
            finally:
                if token is not None:
                    _reproducible_context.reset(token)

    widget.observe(on_change, names='params')  # pylint: disable=no-member

    display(widget)
    display(out)

    # Initial render
    with out:
        token = _reproducible_context.set(base_ctx) if base_ctx is not None else None
        try:
            _run_clean(func, bound_args, packages, show_plot=True)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error: {e}")
            traceback.print_exc()
        finally:
            if token is not None:
                _reproducible_context.reset(token)


def reproducible(interactive: bool = False,
                 packages: Optional[Dict[str, str]] = None,
                 merge_packages: bool = True,
                 publisher=None) -> Callable:
    """\
    Decorator that executes functions in a clean room environment.

    The decorated function runs with an isolated globals namespace containing
    only the specified packages, ensuring reproducibility by preventing
    accidental dependencies on external state.

    :param interactive: If True, display interactive widgets for numeric, boolean,
                       and categorical parameters. Only works in Jupyter notebooks.
    :param packages: Dictionary mapping alias to module name, e.g. {"pd": "pandas"}.
                    If None, uses the global default packages.
    :param merge_packages: If True, merge provided packages with defaults.
                          If False, use only the provided packages.
    :param publisher: Optional Publisher instance. When provided, ``publish`` is
                     injected into the clean room globals so figures can be
                     published from inside the decorated function.

    Example::

        pub = Publisher(workspace="Demo", analysis="Analysis")

        @reproducible(publisher=pub)
        def my_plot(data, bins: int = 20):
            sns.histplot(data=data, x='value', bins=bins)
            publish(plt.gcf(), target="Histogram")

        @reproducible(packages={"pd": "pandas", "px": "plotly.express"})
        def plotly_chart(df):
            return px.scatter(df, x='x', y='y')
    """
    from gofigr.cleanroom import (validate_params, round_trip_params,
                                  check_clean_room_size)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:  # pylint: disable=too-many-branches
            # Build effective packages
            if packages is None:
                effective_packages = get_default_packages()
            elif merge_packages:
                effective_packages = get_default_packages()
                effective_packages.update(packages)
            else:
                effective_packages = packages.copy()

            # Bind arguments
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()

            # Unwrap Param defaults and build param_descriptors
            try:
                type_hints = get_type_hints(func)
            except Exception:  # pylint: disable=broad-exception-caught
                type_hints = {}

            param_descriptors: Dict[str, Param] = {}
            for name, value in list(bound.arguments.items()):
                if isinstance(value, Param):
                    param_descriptors[name] = value
                    bound.arguments[name] = value.default
                else:
                    param_descriptors[name] = infer_param(name, value, type_hints)

            # Determine effective interactive mode
            effective_interactive = interactive and _is_interactive_env()

            if interactive and not effective_interactive:
                warnings.warn(
                    f"@reproducible(interactive=True) on '{func.__name__}' is ignored "
                    "because we're not in an interactive environment. "
                    "Running in non-interactive mode.",
                    stacklevel=2
                )

            # Validate parameter types
            try:
                validate_params(bound.arguments)
            except Exception:  # pylint: disable=broad-exception-caught
                warnings.warn(
                    f"@reproducible on '{func.__name__}': parameters contain unsupported types. "
                    "Falling back to direct execution without clean room.",
                    stacklevel=2
                )
                return func(*args, **kwargs)

            # Check DataFrame memory limits
            if not check_clean_room_size(bound.arguments):
                return func(*args, **kwargs)

            # Round-trip parameters through serialization
            rt_args = round_trip_params(bound.arguments)

            # Resolve package versions
            pkg_versions = _resolve_package_versions(effective_packages)

            # Build extra globals for the clean room
            extra = {}
            if publisher is not None:
                extra["publish"] = publisher.publish

            ctx = ReproducibleContext(
                source_code=_extract_function_body(func),
                function_name=func.__name__,
                packages=effective_packages,
                imports=effective_packages,
                package_versions=pkg_versions,
                parameters=rt_args,
                param_descriptors=param_descriptors,
            )
            token = _reproducible_context.set(ctx)
            try:
                if effective_interactive:
                    _run_interactive(func, rt_args, effective_packages, ctx)
                    return None  # Interactive mode doesn't return values
                else:
                    return _run_clean(func, rt_args, effective_packages,
                                     extra_globals=extra or None)
            finally:
                _reproducible_context.reset(token)

        return wrapper
    return decorator
