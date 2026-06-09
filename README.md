# `action-generate-build-matrix`

> Generates a dynamic JSON build matrix (compiler x sanitizer combinations) for CMake build workflows.

## Usage

```yaml
- uses: Framework-R-D/action-generate-build-matrix@a867325d7153f7fcc7d64fc69eafcb2b97edae39 # v1
  with:
    input-name: value
```

## Inputs

| Name | Description | Required | Default |
|------|-------------|----------|---------|
| `user-input` | The user-provided build combinations from a workflow_dispatch event | false | `` |
| `comment-body` | The body of the issue comment that triggered the workflow | false | `` |

## Outputs

| Name | Description |
|------|-------------|
| `matrix` | The generated build matrix in JSON format |

## License

[Apache 2.0](LICENSE)
