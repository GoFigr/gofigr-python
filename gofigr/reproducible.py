"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

Reproducible decorator for executing functions in a clean room environment
with optional interactive widgets for parameter exploration.
"""
# pylint: disable=global-statement, import-outside-toplevel, import-error
import contextvars
import functools
import importlib
import inspect
import traceback
import types
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, get_type_hints, get_origin, get_args, Literal

from gofigr.utils import read_resource_text


@dataclass(frozen=True)
class ReproducibleContext:
    """Captures the execution context of a @reproducible function."""
    source_code: str
    function_name: str
    packages: Dict[str, str]
    parameters: Dict[str, Any]


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


def _build_clean_globals(packages: Dict[str, str]) -> Dict[str, Any]:
    """
    Build a clean globals dictionary by importing the specified packages.

    :param packages: Dictionary mapping alias to module name
    :return: Dictionary suitable for use as function globals
    """
    clean = {"__builtins__": __builtins__}

    for alias, module_name in packages.items():
        try:
            clean[alias] = importlib.import_module(module_name)
        except ImportError as e:
            warnings.warn(f"Could not import {module_name} as {alias}: {e}")

    return clean


def _infer_param_type(param_name: str, param_value: Any, type_hints: Dict[str, Any]) -> Dict[str, Any]:
    """
    Infer the widget type for a parameter based on its value and type hints.

    Returns a dict with:
    - type: "slider", "checkbox", "dropdown", "text", or "static"
    - Additional metadata depending on type (choices, min, max, etc.)
    """
    hint = type_hints.get(param_name)

    # Check for Literal type hint (dropdown)
    if hint is not None:
        origin = get_origin(hint)
        if origin is Literal:
            choices = list(get_args(hint))
            return {"type": "dropdown", "choices": choices}

    # Infer from value type
    if isinstance(param_value, bool):
        return {"type": "checkbox"}
    elif isinstance(param_value, (int, float)):
        # Determine reasonable slider bounds
        if param_value == 0:
            min_val, max_val = 0, 100
        else:
            min_val = 0
            max_val = param_value * 2 if param_value > 0 else param_value * 0.5
        step = 1 if isinstance(param_value, int) else 0.1
        return {"type": "slider", "min": min_val, "max": max_val, "step": step}
    elif isinstance(param_value, str):
        return {"type": "text"}
    else:
        # Complex types (DataFrames, etc.) are static
        return {"type": "static"}


def _get_interactive_params(func: Callable, bound_args: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Analyze function parameters and return metadata for building widgets.

    Returns dict mapping param_name -> {type, value, ...metadata}
    """
    try:
        type_hints = get_type_hints(func)
    except Exception:  # pylint: disable=broad-exception-caught
        type_hints = {}

    params = {}
    for name, value in bound_args.items():
        info = _infer_param_type(name, value, type_hints)
        info["value"] = value
        info["name"] = name
        params[name] = info

    return params


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
               show_plot: bool = True) -> Any:
    """
    Execute a function in a clean room environment with isolated globals.

    :param func: The function to execute
    :param params: Keyword arguments to pass to the function
    :param packages: Package mapping for the clean globals
    :param show_plot: Whether to call plt.show() after execution
    :return: The function's return value
    """
    clean_globals = _build_clean_globals(packages)

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

    # Analyze parameters and build widget metadata
    param_meta = _get_interactive_params(func, bound_args)

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
                parameters=merged_params,
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
                 merge_packages: bool = True) -> Callable:
    """
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

    Example:
        @reproducible(interactive=True)
        def my_plot(data, bins: int = 20, show_legend: bool = True):
            sns.histplot(data=data, x='value', bins=bins)
            if show_legend:
                plt.legend()

        @reproducible(packages={"pd": "pandas", "px": "plotly.express"})
        def plotly_chart(df):
            return px.scatter(df, x='x', y='y')
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
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

            # Determine effective interactive mode
            effective_interactive = interactive and _is_interactive_env()

            if interactive and not effective_interactive:
                warnings.warn(
                    f"@reproducible(interactive=True) on '{func.__name__}' is ignored "
                    "because we're not in an interactive environment. "
                    "Running in non-interactive mode.",
                    stacklevel=2
                )

            ctx = ReproducibleContext(
                source_code=inspect.getsource(func),
                function_name=func.__name__,
                packages=effective_packages,
                parameters=dict(bound.arguments),
            )
            token = _reproducible_context.set(ctx)
            try:
                if effective_interactive:
                    _run_interactive(func, bound.arguments, effective_packages, ctx)
                    return None  # Interactive mode doesn't return values
                else:
                    return _run_clean(func, bound.arguments, effective_packages)
            finally:
                _reproducible_context.reset(token)

        return wrapper
    return decorator


# Param class for explicit parameter configuration
class Param:
    """
    Explicit parameter configuration for reproducible functions.

    Use this to specify widget behavior for function parameters.

    Example:
        @reproducible(interactive=True)
        def my_plot(
            data,
            bins=Param(20, min=5, max=100, step=5),
            species=Param("Adelie", choices=["Adelie", "Chinstrap", "Gentoo"]),
            show_grid=Param(True)
        ):
            ...
    """
    def __init__(self, default: Any, *,
                 min: Optional[float] = None,  # pylint: disable=redefined-builtin
                 max: Optional[float] = None,  # pylint: disable=redefined-builtin
                 step: Optional[float] = None,
                 choices: Optional[list] = None):
        self.default = default
        self.min = min
        self.max = max
        self.step = step
        self.choices = choices

    def __repr__(self):
        return f"Param({self.default!r})"
