.PHONY: all clean

all: simple_make/foo.txt simple_make/bar.txt simple_make/wow.txt

# this gets split into separate executions for both foo/bar
# the in-line configuration overrides the default from scicd.yaml > task
simple_make/foo.txt simple_make/bar.txt: simple_make/%.txt: simple_make/pre_%.txt
	@# scicd: image=python:3.10
	@echo "Making $@"
	@touch $@

# this is a grouped rule and only runs once, producing all outputs
# it also includes examples of setting more configuration keys
simple_make/wow.txt simple_make/omg.txt&:
	@# scicd: tags=['pc2']
	@# scicd: variables.test=hi there!
	@mkdir -p $(@D)
	@echo "Grouped rule! Making wow.txt and omg.txt (triggered on $@)"
	@touch simple_make/wow.txt
	@touch simple_make/omg.txt

simple_make/pre_%.txt:
	@mkdir -p $(@D)
	@touch $@


clean:
	rm -f simple_make
