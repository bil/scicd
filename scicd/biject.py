import luigi
import json
import fire
import importlib


def run(module: str, family: str, params_json: str):
    # Dynamically import the module where the task lives
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        print(f"Error: Could not find module {module}")
        raise e

    # Get the class from the module
    task_cls = getattr(mod, family)

    # Load params and instantiate
    params = json.loads(params_json)
    task_instance = task_cls.from_str_params(params)

    # 4. Execute
    print(f"--- Running {module}.{family} ---")
    luigi.build([task_instance], local_scheduler=True)


if __name__ == "__main__":
    fire.Fire()
