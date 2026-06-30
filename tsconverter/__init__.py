"""TS-MP4-converter internal package.

Houses the media/engine layer being extracted from the original flat
app.py / converter.py modules. Import-time side effects are kept minimal so
the package is safe to pull into both the GUI and headless contexts.
"""
