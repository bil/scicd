# Getting Started

Get up and running with SciCD in a few simple steps.

## Installation

SciCD requires Python 3.10+.

```bash
# Clone the repository
git clone <your-repo-url>
cd scicd

# Install dependencies and the package
pip install -r requirements.txt
pip install -e .
```

## Your First Pipeline

1. **Create a Configuration**: Place a `scicd.yaml` in your project root.
2. **Define a Task**: Create a Python file (e.g., `workflow.py`) with a Luigi task inheriting from `HashTask`.
3. **Build the CI/CD Pipeline**:

   ```bash
   scicd build --module workflow --target MyTask
   ```

4. **Deploy**: Commit the generated `.gitlab-ci.yml` and push!
