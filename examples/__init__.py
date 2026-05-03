"""Forge example .eml files (bundled with the PyPI wheel).

This package exists only so setuptools.find can pick up the
examples/ directory and ship its .eml content alongside the
compiler. There is no Python code here -- treat the .eml
files as data, accessible via importlib.resources:

    from importlib.resources import files
    eml_text = files("examples").joinpath("hello.eml").read_text()

For interactive use, just:

    eml-compile examples/hello.eml --target python

from a Forge checkout, or copy the files out of the wheel
install path.
"""
