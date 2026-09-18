---
name: az-azd
description: Use for Azure CLI (az) or Azure Developer CLI (azd) commands to isolate configuration and authentication state across tenants, projects, and agent sessions.
---

# Isolated Azure CLI sessions

Run commands through the adjacent `az-azd.py` wrapper rather than the shared
user-level Azure CLI and Azure Developer CLI profiles. Use the shared profiles
only when the user explicitly requests them.

## Workflow

1. Resolve the tenant and, for subscription-scoped work, the target subscription
   from the user or authoritative project configuration. If either is ambiguous,
   ask before running a CLI command; the shared CLI profile is not a discovery
   source.
2. Choose a profile name containing only letters, digits, and hyphens, such as
   `contoso-dev-session1`. Use a distinct profile for each independent identity
   or concurrent session. Reuse a profile only to intentionally reuse its cached
   sign-in. For concurrent `azd` work in one repository, also choose a distinct
   environment name.
3. Locate `az-azd.py` beside the loaded `SKILL.md`. Invoke it by its resolved
   path with Python 3.10+ and put wrapper options before the mode. Use `show`
   to inspect the intended paths; it creates directories but does not sign in
   or contact Azure.
4. Run the required command with the same profile, tenant, and environment.
   Confirm the active tenant and subscription in that isolated profile before
   subscription-scoped operations. The wrapper does not validate cached identity
   against `--tenant` or select a subscription automatically.
5. Check the command's exit status and intended result. Obtain the agent host's
   required approval before deployments, provisioning, external writes, or
   cost-bearing operations.

## Commands

The examples use PowerShell. Replace the script path and example tenant with
the resolved skill path and the user's tenant. On macOS/Linux, use the equivalent
path and `python3` if needed. The script has no third-party Python dependencies;
`uv run` is also supported when available.

```powershell
$script = 'C:\path\to\az-azd\az-azd.py'
$tenant = 'contoso.onmicrosoft.com'
$context = @('--profile', 'contoso-dev-session1', '--tenant', $tenant, '--environment', 'dev-session1')

python $script @context show
python $script @context az account show
python $script @context azd env list
```

`az` and `azd` modes automatically attempt browser sign-in when their isolated
profile has no authentication artifacts or the CLI reports it is signed out.
An interactive terminal is required for automatic sign-in. Successful login is
checked using CLI authentication status and artifacts in the isolated directory.

For explicit login, pass the tenant to both the wrapper and the CLI:

```powershell
python $script @context az login --tenant $tenant
python $script @context azd auth login --tenant-id $tenant --use-device-code=false
```

If a non-interactive invocation requests authentication, run these wrapped
login commands in an interactive terminal, then retry the original wrapped
command. Login hints printed by the wrapper are bare CLI commands; run them
only inside an isolated shell, or add the wrapper as above.

### Shell and arbitrary commands

```powershell
python $script @context shell
python $script @context exec -- pwsh -NoProfile -Command "az account show"
```

`shell` authenticates **both** CLIs before opening a child shell; both must be
installed. Shell selection can be overridden with `shell --shell-path <path>`.
`exec` supplies the isolated environment but does not perform automatic
authentication or verify login. Authenticate first using `az` or `azd` mode.

Direct `az`/`azd` commands passed through `exec` reject explicit device-code
flags. Nested shell or Python arguments are owned by the launched program,
not parsed by this wrapper. Commands typed inside a shell are likewise not
intercepted.

On Windows, nested Python subprocesses should resolve Azure CLI with
`shutil.which("az.cmd")` or `shutil.which("az.exe")` rather than assuming that
`subprocess.run(["az", ...])` resolves a command shim.

## Isolation and persistence

The wrapper sets `AZURE_CONFIG_DIR` and `AZD_CONFIG_DIR` to separate directories
under the selected profile and exposes the requested tenant as
`AZURE_TENANT_ID`. `--environment` sets `AZURE_ENV_NAME`; an explicit
`azd -e <name>` can also select an environment.

Inherited `AZURE_*` and `AZD_*` variables are removed by default. Use
`--inherit-azure-env` only when deliberately preserving credentials or context,
such as a configured workload identity; isolated config directory values still
take precedence. `--clean-azure-env` is a compatibility alias for the default.

Profiles persist across invocations. The default state root is the first
available of `LOCALAPPDATA\az-azd-sessions`, `XDG_STATE_HOME/az-azd-sessions`,
or `~/.az-azd-sessions`. Set `--state-root <path>` to use another private
directory outside source control. `--cwd <path>` sets the child working directory.
Use `python <script-path> --help` for the complete command interface.

Treat profile directories as credentials. This is configuration separation,
not a sandbox: it neither restricts the child process's filesystem/network
access nor protects profiles from other processes running as the same user.
Reusing the same profile or `azd` environment across concurrent sessions can
still cause collisions.

## Browser authentication and Windows

Human sign-in must use browser-based authentication. If no browser is available,
stop rather than switching to device code. The wrapper rejects explicit
device-code flags. On non-Windows systems it also checks captured login output
for a device-login URL together with a code-entry prompt.

On Windows, login inherits terminal I/O to preserve browser launch, so the
wrapper cannot detect device-code fallback from login output. If such a prompt
appears, stop the flow. Authentication checks alone do not prove which flow
the CLI used.

Windows commands disable Web Account Manager (WAM) by default by setting
`core.enable_broker_on_windows=false` in the isolated Azure CLI config.
This avoids broker UI appearing in a different desktop/session. Consequently,
even `azd` and `exec` modes need `az` installed on Windows under this default.
Use `--enable-wam` only when intentionally retaining broker behavior; it skips
the configuration step and does not reset an existing profile's WAM setting.

For unattended work, prefer workload identities over shared human logins.
Configure authentication explicitly within the isolated environment; the
automatic sign-in flow is designed for interactive users.
