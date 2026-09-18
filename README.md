# Agent skills

Reusable, open-source instructions and companion scripts for AI coding agents.
This repository currently contains one skill:

| Skill | Purpose |
| --- | --- |
| [az-azd](skills/az-azd/SKILL.md) | Run Azure CLI and Azure Developer CLI with separate configuration and authentication profiles. |

## Layout

Each skill is self-contained under `skills/<name>`. Its `SKILL.md` provides
discovery metadata and operating instructions; companion scripts live beside it.

```text
skills/
  az-azd/
    SKILL.md
    az-azd.py
```

This distribution contains skill instructions and runtime scripts only.
Evaluation suites, fixtures, results, and optimization artifacts are not included.

## Use with an agent

Copy the entire `skills/az-azd` directory into a skill location supported by
your agent, keeping `SKILL.md` and `az-azd.py` together. For example, GitHub
Copilot supports project skills in `.github/skills/az-azd` and personal skills
in `~/.copilot/skills/az-azd`. Retain the [license](LICENSE) when redistributing
the files.

Reload skills as required by your client. Ask the agent to use `az-azd` for an
Azure CLI task and supply the intended tenant and subscription. Installation
does not install Azure tools or authenticate an account.

## Run the wrapper directly

Requirements:

- Python 3.10 or newer; no third-party Python packages are required.
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) for `az`
  commands and [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
  for `azd` commands, available on `PATH`.
- Both CLIs for `shell` mode. Windows also needs Azure CLI for the default WAM
  configuration step, including when running `azd` or `exec`.
- An interactive terminal and browser when human sign-in is needed.

From this repository in PowerShell, inspect the profile wiring without signing
in or contacting Azure:

```powershell
python .\skills\az-azd\az-azd.py --profile example-dev --tenant example.onmicrosoft.com show
```

Replace the example tenant with your intended tenant before authenticating.
`show` creates local profile directories. On macOS/Linux, use `python3` and
`./skills/az-azd/az-azd.py`.

See the [skill instructions](skills/az-azd/SKILL.md) for login, command execution,
environment selection, and platform-specific behavior.

## Safety

Profiles persist and may contain authentication tokens. Keep them outside
source control and reuse them only intentionally. The wrapper separates CLI
configuration; it is not a security sandbox, does not validate a cached login's
tenant, and does not select or enforce a target subscription. Confirm the
isolated account context before operating on resources.

Human sign-in uses browser authentication rather than device code. Deployments
and other Azure operations can change resources or incur costs; follow your
agent host's approval requirements.

## License

[MIT](LICENSE).
