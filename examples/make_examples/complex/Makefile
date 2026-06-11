# Variables
STEMS := $(shell seq 1 10)
PROCESSED_FILES := $(STEMS:%=complex_out/processed_%.txt)

.PHONY: clean all

# Default target
all: complex_out/summary.md complex_out/another_file.md

# Aggregation
# these get split into separate work!
complex_out/summary.md complex_out/another_file.md: $(PROCESSED_FILES) complex_out/metadata.json complex_out/metadata.csv
	@# scicd: image=python:3.12 variables.test=2
	@echo "--> Aggregating into $@"
	@mkdir -p $(dir $@)
	@cat $^ > $@

# no recipe here, but you can add a dep
complex_out/summary.md: complex_out/A_precursor_1.txt

# this is not a prerequisite of `all` and will not be included as a job
complex_out/.orphan.md:
	@mkdir -p $(dir $@)
	@touch $@

# implicit rules are grouped automatically, don't need &:
complex_out/processed_%.txt complex_out/sidecar_%.txt: complex_out/raw_%.csv complex_out/metadata.json
	@# scicd: cpu=2 memory=16gb
	@echo "Making complex_out/processed_$*.txt"
	@mkdir -p complex_out
	@touch complex_out/processed_$*.txt
	@echo "Making complex_out/sidecar_$*.txt"
	@touch complex_out/sidecar_$*.txt

complex_out/raw_%.csv: complex_out/A_precursor_%.txt
	@# scicd: compute_type=Performance
	@echo "--> Generating mock raw data for $@..."
	@mkdir -p $(dir $@)
	@touch $@

# instead of mapping each implicit rule instnace to its own job
# you can have them be handled by two workers
complex_out/A_precursor_%.txt:
	@# scicd: concurrency.method=slice concurrency.workers=2
	@mkdir -p $(dir $@)
	@touch $@

# Grouped metadata generation
complex_out/metadata.json complex_out/metadata.csv complex_out/random_file.md&:
	@echo "::: Generating mock metadata..."
	@mkdir complex_out
	@touch complex_out/metadata.json
	@touch complex_out/metadata.csv
	@touch complex_out/random_file.md

clean:
	@echo "--> Cleaning up..."
	rm -rf complex_out
