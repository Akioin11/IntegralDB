import pkgutil
import importlib
from typing import List, Tuple, Callable


def discover_modules(package: str) -> List[Tuple[str, str, Callable]]:
    """Discover modules in the given package.

    Returns a list of tuples: (module_name, title, app_callable)
    """
    modules = []
    pkg = importlib.import_module(package)
    if not hasattr(pkg, "__path__"):
        return modules

    for finder, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        if ispkg:
            continue
        fullname = f"{package}.{name}"
        try:
            mod = importlib.import_module(fullname)
        except Exception:
            # Skip modules that fail to import
            continue

        title = getattr(mod, "TITLE", name)
        app_fn = getattr(mod, "app", None)
        if callable(app_fn):
            modules.append((name, title, app_fn))

    # Sort by title
    modules.sort(key=lambda t: t[1].lower())
    return modules
