.PHONY: validate test build smoke official

validate:
	python scripts/validate_source.py

test:
	python -m unittest discover -s tests -v

build: validate test
	python scripts/build_release.py

# Authoritative check. The online form cannot resolve references from a source
# checkout, so the source gate is --offline.
official:
	specify bundle validate --path bundle/ --offline
	specify bundle build --path bundle/ --output dist/

smoke:
	python scripts/smoke_test.py --integration opencode
