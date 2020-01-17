TEST_PYPI :=  https://test.pypi.org/legacy/
RM := rm -rf

mkvenv:
	dephell venv create

convert:
	dephell deps convert --from=pyproject.toml --to Pipfile

build:
	make convert
	dephell project build

test:
	make build
	dephell venv run --env=pytest pip install .
	dephell venv run --env=pytest pip install inflection
	dephell venv run --env=pytest pytest

upload:
	twine upload dist/*

test-upload:
	twine upload --verbose --repository-url $(TEST_PYPI) dist/*

release:
	make test
	dephell project bump --tag release
	make build

fake-release:
	make test
	dephell project bump pre
	make build
	make test-upload


full-release:
	make release
	make upload