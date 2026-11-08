.PHONY: video video-record video-captions video-assemble video-check video-sheets

VENV ?= .venv/bin/python

video: video-record video-captions video-assemble video-check
	@echo "video pipeline complete -> video/out/"

video-record:
	$(VENV) video/record_all.py

video-captions:
	$(VENV) video/build_captions.py

video-assemble:
	$(VENV) video/assemble.py

video-check:
	$(VENV) video/check.py

video-sheets:
	@mkdir -p video/out/sheets
	@f=video/out/demo_full_captioned.mp4; \
	 test -f $$f || f=video/out/demo_full_clean.mp4; \
	 ffmpeg -y -i $$f -vf "fps=1/2,scale=320:-1,tile=6x6" video/out/sheets/contact_%03d.png
	@echo "contact sheets in video/out/sheets/"
