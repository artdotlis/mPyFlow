ROOT_MAKEFILE:=$(abspath $(patsubst %/, %, $(dir $(abspath $(lastword $(MAKEFILE_LIST))))))

include $(ROOT_MAKEFILE)/.env

export

$(eval UVEL := $(shell which uv && echo "true" || echo ""))
UVE = $(if ${UVEL},'uv',$(UV_INSTALL_DIR)/uv)
UV_ENV := $(UV_INSTALL_DIR)/env

dev: setup
	$(UVE) sync --frozen --all-groups
	$(UVE) run lefthook uninstall 2>&1
	$(UVE) run lefthook install

tests: setup
	$(UVE) sync --frozen --no-group docs --no-group dev

build: setup
	$(UVE) sync --frozen --no-group test --no-group docs --no-group dev

docs: setup
	$(UVE) sync --froze --no-group test --no-group dev

setup:
	git lfs install || echo '[FAIL] git-lfs could not be installed'
	which uv || [ -d "${UV_INSTALL_DIR}" ] || (curl -LsSf https://astral.sh/uv/install.sh | sh)
	which uv || $(UVE) python install $(PYV)
	rm -rf .venv
	$(UVE) venv --python=$(PYV) --relocatable --link-mode=copy --seed
	which uv || $(UVE) pip install --upgrade pip


RAN := $(shell awk 'BEGIN{srand();printf("%d", 65536*rand())}')

runAct:
	echo "source .venv/bin/activate; source $(UV_ENV); rm /tmp/$(RAN)" > /tmp/$(RAN)
	bash --init-file /tmp/$(RAN)

runChecks:
	$(UVE) run lefthook run pre-commit --all-files -f

runDocs:
	$(UVE) run mkdocs build -f configs/dev/mkdocs.yml -d ../../public

serveDocs:
	$(UVE) run mkdocs serve -f configs/dev/mkdocs.yml

runTests:
	$(UVE) run tox

runBuild:
	$(UVE) build

runBump:
	cz bump --files-only --yes --changelog
	git add .
	cz version --project | xargs -i git commit -am "bump: release {}"

runUV:
	$(UVE) run $(CMD)

runLock runUpdate: %: export_%
# add all packages rquired to be build
	$(UVE) export --frozen --format requirements.txt > requirements.txt
	$(UVE) export --frozen --only-group dev --format requirements.txt > configs/dev/requirements.dev.txt
	$(UVE) export --frozen --only-group test --format requirements.txt > configs/dev/requirements.test.txt
	$(UVE) export --frozen --only-group docs --format requirements.txt > configs/dev/requirements.docs.txt

export_runLock:
	$(UVE) lock

export_runUpdate:
	$(UVE) lock -U

com commit:
	$(UVE) run cz commit

recom recommit:
	$(UVE) run cz commit --retry
