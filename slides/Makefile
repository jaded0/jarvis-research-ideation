# Markdown -> PDF slides. Needs pandoc and xelatex (TeX Live with beamer + metropolis).
# One slide per level-1 heading; images go in img/ and are referenced as ![](img/foo.png).

slides.pdf: slides.md $(wildcard img/*)
	pandoc $< -t beamer --pdf-engine=xelatex --resource-path=.:img \
		-V aspectratio=169 -V theme=metropolis -o $@

clean:
	rm -f slides.pdf

.PHONY: clean
