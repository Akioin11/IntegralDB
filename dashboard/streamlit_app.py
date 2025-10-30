"""Modular Streamlit dashboard entrypoint.

This app discovers modules in `dashboard.modules` and renders a sidebar to
select which module to run. Each module should expose `TITLE` and `app()`.
"""
import streamlit as st
import sys
from pathlib import Path

# Try relative import first (works when package is imported). When running
# via `streamlit run dashboard/streamlit_app.py` the package root may not be
# on sys.path, so fall back to adding the repo root and importing absolutely.
try:
    # If `dashboard` is a package import this way when executed as a package
    from . import utils
except Exception:
    # Ensure repo root is on sys.path, then import the package module
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from dashboard import utils


def main():
    st.set_page_config(page_title="IntegralDB Dashboard", layout="wide")
    st.sidebar.title("IntegralDB")
    st.sidebar.markdown("Select a tool from the list below")

    modules = utils.discover_modules("dashboard.modules")

    if not modules:
        st.sidebar.error("No dashboard modules found. Add modules to `dashboard/modules`.")
        st.write("No modules available.")
        return

    names = [t[1] for t in modules]
    idx = st.sidebar.radio("Choose tool", options=list(range(len(names))), format_func=lambda i: names[i])

    # Display selected module
    selected = modules[idx]
    st.sidebar.markdown(f"**Active:** {selected[1]}")

    # Run the module's app function
    try:
        selected[2]()
    except Exception as e:
        st.error(f"Error running module '{selected[0]}': {e}")


if __name__ == "__main__":
    main()
