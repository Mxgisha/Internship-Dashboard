PY ?= python3

.PHONY: config test check collect serve docs

test:
	$(PY) -m unittest discover -s tests -v

check:
	$(PY) -m compileall -q .
	$(PY) -m unittest discover -s tests

collect:
	$(PY) collect.py --refresh

serve:
	$(PY) server.py

docs:
	$(PY) tools/md2pdf.py BRIEF.md
