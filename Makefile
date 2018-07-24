all: txz

clean:
	rm -rf google-analytics.txz

.PHONY: txz
txz:
	tar --transform 's#^#serverboards.google.analytics/#' -cJf google-analytics.txz static manifest.yaml *.py *.sh *.txt
