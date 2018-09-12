all: txz

clean:
	rm -rf google-analytics.txz

FILES=static manifest.yaml serverboards_aio.py serverboards-google-analytics.py pcolor.py *.sh *.txt

.PHONY: txz
txz:
	tar --transform 's#^#serverboards.google.analytics/#' -cJf google-analytics.txz ${FILES}
