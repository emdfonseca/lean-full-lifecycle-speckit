"""Start coverage inside subprocesses the suite spawns.

Half the tests here drive a script the way a person does -- `subprocess.run([
sys.executable, "scripts/validate_source.py", ...])` -- because the refusal
text is what a reader sees. Coverage measures the parent only, so every
`check:` component read as "nothing in the suite executed it" while the suite
was in fact exercising all 34 of them.

`coverage.process_startup()` is a no-op unless `COVERAGE_PROCESS_START` names a
config file, so this file is inert for anyone who puts it on PYTHONPATH without
asking for a measurement.
"""
try:
    import coverage
except ImportError:  # pragma: no cover - a tree without the dev extra
    pass
else:
    coverage.process_startup()
