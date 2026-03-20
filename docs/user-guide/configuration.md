# Configuration

SciCD uses a YAML-based configuration system to manage workspace settings and task defaults.

## Configuration Discovery

SciCD automatically searches for its configuration in the following order:

1. **`SCICD_CONFIG_PATH`** (Environment Variable)
2. **`scicd.yaml`** (Project Root)
3. **`.scicd/config.yaml`**
4. **`.scicd/scicd.yaml`**

## Workspace Configuration (`repository`, `remote`)

The `repository` section defines your source control platform, while `remote` handles data synchronization.

```yaml
repository:
  platform: gitlab
  url: https://gitlab.com
  project: org/repo
  cicd:
    default:
      image: python:3.10

remote:
  protocol: rclone
  url: s3://my-bucket
  root: /data
```

## Task Defaults (`task`)

The `task` key provides global defaults for every task instance in your DAG. These are automatically merged into each task's `TaskConfig`.

```yaml
task:
  cpu: 1
  memory: 4Gi
  retry: 3
  tags: ["standard"]
```
