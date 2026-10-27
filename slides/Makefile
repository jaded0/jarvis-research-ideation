# Markdown -> PDF slides with Marp. Needs Node (npx) and Chrome/Chromium.
# Slides are separated by `---`; images go in img/ and are referenced as ![](img/foo.png).

MARP = npx -y @marp-team/marp-cli@4.5.1 --allow-local-files
export CHROME_PATH ?= $(shell command -v google-chrome || command -v chromium || command -v chromium-browser)

slides.pdf: slides.md $(wildcard img/*)
	$(MARP) $< --pdf -o $@

# Live preview in the browser; re-renders on save.
watch:
	$(MARP) -s .

clean:
	rm -f slides.pdf

.PHONY: watch clean
