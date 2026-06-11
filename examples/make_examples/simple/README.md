# Make Example: Simple

Makefiles are also supported as a language for specifying the workflow.

To specify task configuration, in-line comments can be used at the very start of the rule's recipe.

In order to place workflow outputs relative to an environment variable, the `data_root` configuration is used by SciCD when generating CI/CD.
This uses `make`'s `-C` flag to run the workflow relative to the provided directory.
