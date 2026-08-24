.PHONY: generate generate-check validate test build smoke official coverage p12-exit

generate:
	python scripts/generate_manifests.py
	python scripts/generate_catalogs.py
	python scripts/generate_item_templates.py
	python scripts/generate_compat_matrix.py

# Generated files must match the manifests; CI runs this so a hand-edit fails.
generate-check:
	python scripts/generate_manifests.py --check
	python scripts/generate_catalogs.py --check
	python scripts/generate_item_templates.py --check

validate: generate-check
	python scripts/validate_source.py
	python scripts/validate_requirements.py
	python scripts/validate_acceptance.py

test:
	python -m pytest

build: validate test
	python scripts/build_release.py

# Authoritative check. The online form cannot resolve references from a source
# checkout, so the source gate is --offline.
official:
	specify bundle validate --path bundle/ --offline
	specify bundle build --path bundle/ --output dist/

smoke:
	python scripts/smoke_test.py --integration opencode

# Requirement coverage, for the CI step summary.
coverage:
	python scripts/validate_requirements.py --report md

p12-exit: validate
	$(MAKE) official
	python -m pytest -m "not wording"
	python scripts/validate_acceptance.py --phase p12
