.PHONY: generate generate-check validate test build smoke official coverage measure

generate:
	python scripts/generate_manifests.py
	python scripts/generate_catalogs.py
	python scripts/generate_item_templates.py
	python scripts/generate_constitution_guidance.py
	python scripts/generate_compat_matrix.py

# Generated files must match the manifests; CI runs this so a hand-edit fails.
generate-check:
	python scripts/generate_manifests.py --check
	python scripts/generate_catalogs.py --check
	python scripts/generate_item_templates.py --check
	python scripts/generate_constitution_guidance.py --check

validate: generate-check
	python scripts/validate_source.py
	python scripts/validate_requirements.py

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

# Does a requirement's cited tests actually run the code it names? Runs the
# suite under coverage with per-test contexts, so it is slow and deliberately
# outside `validate`. It runs alongside the marker system for a release before
# anything is removed on its evidence.
measure:
	python scripts/measure_traceability.py --run

# Requirement coverage, for the CI step summary.
coverage:
	python scripts/validate_requirements.py --report md

