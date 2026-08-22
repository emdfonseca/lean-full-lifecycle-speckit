.PHONY: validate test build smoke

validate:
	python scripts/validate_source.py

test:
	python -m unittest discover -s tests -v

build: validate test
	python scripts/build_release.py

smoke:
	python scripts/smoke_test.py --integration opencode
