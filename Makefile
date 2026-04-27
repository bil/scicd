.PHONY: pipeline run

pipeline: .gitlab-ci.yml
run:
	@scicd gitlab run

.gitlab-ci.yml: utils/pipeline.py
	@scicd luigi build -m utils.pipeline -t Pipeline -b gitlab
