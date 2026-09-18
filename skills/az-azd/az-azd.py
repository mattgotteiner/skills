#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# ///
"""
Run az and azd with isolated per-session state and browser-based interactive auth.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ISOLATION_MARKER = "AZ_AZD_ISOLATED"
SESSION_ROOT_VARIABLE = "AZ_AZD_SESSION_ROOT"


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    azure_config_dir: Path
    azd_config_dir: Path


def default_state_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "az-azd-sessions"

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "az-azd-sessions"

    return Path.home() / ".az-azd-sessions"


def ensure_session_paths(state_root: Path, profile: str) -> SessionPaths:
    root = (state_root / profile).resolve()
    azure_config_dir = root / "azure-config"
    azd_config_dir = root / "azd-config"
    azure_config_dir.mkdir(parents=True, exist_ok=True)
    azd_config_dir.mkdir(parents=True, exist_ok=True)
    return SessionPaths(root=root, azure_config_dir=azure_config_dir, azd_config_dir=azd_config_dir)


def build_env(
    paths: SessionPaths,
    tenant: str | None,
    environment: str | None,
    inherit_azure_env: bool = False,
) -> dict[str, str]:
    child_env = os.environ.copy()
    if not inherit_azure_env:
        for variable_name in tuple(child_env):
            normalized_name = variable_name.upper()
            if normalized_name.startswith("AZURE_") or normalized_name.startswith(
                "AZD_"
            ):
                child_env.pop(variable_name, None)
    child_env["AZURE_CONFIG_DIR"] = str(paths.azure_config_dir)
    child_env["AZD_CONFIG_DIR"] = str(paths.azd_config_dir)
    child_env[ISOLATION_MARKER] = "1"
    child_env[SESSION_ROOT_VARIABLE] = str(paths.root)
    if tenant:
        child_env["AZURE_TENANT_ID"] = tenant
    if environment:
        child_env["AZURE_ENV_NAME"] = environment
    return child_env


def print_summary(paths: SessionPaths, tenant: str | None, environment: str | None) -> None:
    print(f"profile: {paths.root.name}")
    print(f"session root: {paths.root}")
    print(f"AZURE_CONFIG_DIR={paths.azure_config_dir}")
    print(f"AZD_CONFIG_DIR={paths.azd_config_dir}")
    if tenant:
        print(f"AZURE_TENANT_ID={tenant}")
    if environment:
        print(f"AZURE_ENV_NAME={environment}")
    print()
    print("suggested interactive login commands:")
    if tenant:
        print(f"  az login --tenant {tenant}")
        print(f"  azd auth login --tenant-id {tenant} --use-device-code=false")
    else:
        print("  az login")
        print("  azd auth login --use-device-code=false")


def pick_shell(requested_shell: str | None) -> str:
    if requested_shell:
        return requested_shell
    candidates: tuple[str, ...] = ("pwsh", "powershell") if os.name == "nt" else ("pwsh", "bash", "sh")
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FileNotFoundError("Could not find a suitable shell on PATH.")


def normalize_command(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        return command[1:]
    return command


def format_command(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def resolve_executable(executable: str) -> str:
    resolved = shutil.which(executable)
    if resolved:
        return resolved
    if os.name == "nt":
        for suffix in (".cmd", ".exe", ".bat"):
            resolved = shutil.which(f"{executable}{suffix}")
            if resolved:
                return resolved
    raise FileNotFoundError(f"Could not find '{executable}' on PATH.")


def maybe_disable_wam(child_env: dict[str, str], cwd: Path, disable_wam: bool) -> None:
    if not disable_wam or os.name != "nt":
        return
    completed = subprocess.run(
        [resolve_executable("az"), "config", "set", "core.enable_broker_on_windows=false"],
        env=child_env,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"Failed to disable WAM in the isolated Azure CLI profile: {detail}")


def check_az_auth(child_env: dict[str, str], cwd: Path) -> bool | None:
    completed = subprocess.run(
        [resolve_executable("az"), "account", "show", "--output", "none", "--only-show-errors"],
        env=child_env,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return True
    detail = f"{completed.stdout}\n{completed.stderr}".lower()
    if "please run 'az login' to setup account" in detail or "please run 'az login' to set up account" in detail:
        return False
    return None


def check_azd_auth(child_env: dict[str, str], cwd: Path) -> bool | None:
    completed = subprocess.run(
        [resolve_executable("azd"), "auth", "status"],
        env=child_env,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    detail = f"{completed.stdout}\n{completed.stderr}".lower()
    if "not logged in" in detail or "please run 'azd auth login' to set up account" in detail:
        return False
    if completed.returncode == 0:
        return True
    return None


def is_auth_command(executable: str, tail_args: list[str]) -> bool:
    normalized_tail = normalize_command(tail_args)
    if executable == "az":
        return bool(normalized_tail) and normalized_tail[0].lower() == "login"
    if executable == "azd":
        return len(normalized_tail) >= 2 and normalized_tail[0].lower() == "auth"
    return False


def is_login_command(executable: str, tail_args: list[str]) -> bool:
    normalized_tail = normalize_command(tail_args)
    if executable == "az":
        return bool(normalized_tail) and normalized_tail[0].lower() == "login"
    if executable == "azd":
        return len(normalized_tail) >= 2 and normalized_tail[0].lower() == "auth" and normalized_tail[1].lower() == "login"
    return False


def bool_flag_enabled(argument: str, flag_name: str) -> bool:
    if argument == flag_name:
        return True
    prefix = f"{flag_name}="
    if not argument.startswith(prefix):
        return False
    value = argument[len(prefix) :].strip().lower()
    return value not in {"0", "false", "no", "off"}


def validate_auth_args(executable: str, tail_args: list[str]) -> str | None:
    normalized_tail = normalize_command(tail_args)
    if executable == "az" and any(bool_flag_enabled(argument, "--use-device-code") for argument in normalized_tail):
        return "Device code auth is not allowed with this skill. Use browser-based interactive login instead: az login"
    if executable == "azd" and any(bool_flag_enabled(argument, "--use-device-code") for argument in normalized_tail):
        return (
            "Device code auth is not allowed with this skill. "
            "Use browser-based interactive login instead: azd auth login --use-device-code=false"
        )
    return None


def direct_azure_executable(command: list[str]) -> str | None:
    if not command:
        return None
    name = command[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    for suffix in (".cmd", ".exe", ".bat"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name if name in {"az", "azd"} else None


def print_login_heads_up(executable: str, tenant: str | None) -> None:
    if executable == "az" and not tenant:
        print(
            "Azure CLI browser login may enumerate all accessible tenants and print warning noise "
            "before the target subscription appears. Pass --tenant to reduce that noise.",
            file=sys.stderr,
        )


def has_auth_artifact(config_dir: Path, exact_names: set[str], name_fragments: tuple[str, ...] = ()) -> bool:
    for path in config_dir.rglob("*"):
        if not path.is_file():
            continue
        lowercase_name = path.name.lower()
        if lowercase_name in exact_names or any(fragment in lowercase_name for fragment in name_fragments):
            return True
    return False


def profile_has_auth_artifacts(paths: SessionPaths, executable: str) -> bool:
    if executable == "az":
        return has_auth_artifact(
            paths.azure_config_dir,
            {"accesstokens.json", "azureprofile.json", "msal_token_cache.bin", "msal_token_cache.json"},
            ("token",),
        )
    if executable == "azd":
        return has_auth_artifact(paths.azd_config_dir, set(), ("auth", "token", "msal"))
    raise ValueError(f"Unsupported executable for auth artifact checks: {executable}")


def should_force_login(args: argparse.Namespace, child_env: dict[str, str], executable: str) -> bool:
    if not profile_has_auth_artifacts(args.paths, executable):
        return True
    auth_status = check_az_auth(child_env, args.cwd) if executable == "az" else check_azd_auth(child_env, args.cwd)
    return auth_status is False


def verify_login_succeeded(args: argparse.Namespace, child_env: dict[str, str], executable: str) -> int | None:
    auth_status = check_az_auth(child_env, args.cwd) if executable == "az" else check_azd_auth(child_env, args.cwd)
    if auth_status is not True:
        print(
            "Login completed but the isolated profile still does not report an authenticated session.",
            file=sys.stderr,
        )
        return 1
    if not profile_has_auth_artifacts(args.paths, executable):
        target_dir = args.paths.azure_config_dir if executable == "az" else args.paths.azd_config_dir
        print(
            "Login completed but no auth token artifacts were found in the isolated profile "
            f"({target_dir}).",
            file=sys.stderr,
        )
        return 1
    return None


def login_output_used_device_code(output: str) -> bool:
    lowered_output = output.lower()
    explicit_device_code_markers = (
        "to sign in, use a web browser to open the page",
        "and enter the code",
        "enter code",
    )
    device_login_urls = ("microsoft.com/devicelogin", "aka.ms/devicelogin")
    return any(marker in lowered_output for marker in explicit_device_code_markers) and any(
        url in lowered_output for url in device_login_urls
    )


def run_login_command(command: list[str], child_env: dict[str, str], cwd: Path) -> tuple[int, str]:
    if os.name == "nt":
        # Azure CLI's Windows broker/browser login is sensitive to stdio shape.
        # Inherit the terminal instead of piping output so browser UI is launched
        # from the same interactive session as the wrapper.
        return subprocess.run(command, env=child_env, cwd=cwd, check=False).returncode, ""

    process = subprocess.Popen(
        command,
        env=child_env,
        cwd=cwd,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if process.stdout is None:
        return subprocess.run(command, env=child_env, cwd=cwd, check=False).returncode, ""

    output_chunks: list[str] = []
    with process.stdout:
        for line in process.stdout:
            print(line, end="")
            output_chunks.append(line)
    return process.wait(), "".join(output_chunks)


def build_login_command(executable: str, tenant: str | None) -> list[str]:
    if executable == "az":
        command = [resolve_executable("az"), "login"]
        if tenant:
            command.extend(["--tenant", tenant])
        return command
    if executable == "azd":
        command = [resolve_executable("azd"), "auth", "login", "--use-device-code=false"]
        if tenant:
            command.extend(["--tenant-id", tenant])
        return command
    raise ValueError(f"Unsupported executable for interactive login: {executable}")


def ensure_interactive_auth(
    args: argparse.Namespace,
    child_env: dict[str, str],
    executable: str,
    tail_args: list[str],
) -> int | None:
    if is_auth_command(executable, tail_args):
        return None

    fresh_profile = not profile_has_auth_artifacts(args.paths, executable)
    if not should_force_login(args, child_env, executable):
        return None

    login_command = build_login_command(executable, args.tenant)
    wrapped_command = [resolve_executable(executable), *tail_args]
    if not sys.stdin.isatty():
        print(
            "Browser-based interactive authentication is required for this isolated profile. "
            f"Run {format_command(login_command)} and retry {format_command(wrapped_command)}.",
            file=sys.stderr,
        )
        return 1

    if fresh_profile:
        print(
            f"No login state was found for isolated profile '{args.paths.root.name}'. "
            f"Launching {format_command(login_command)} before retrying {format_command(wrapped_command)}.",
            file=sys.stderr,
        )
    else:
        print(
            f"Authentication is required for isolated profile '{args.paths.root.name}'. "
            f"Launching {format_command(login_command)} before retrying {format_command(wrapped_command)}.",
            file=sys.stderr,
        )
    print_login_heads_up(executable, args.tenant)
    login_returncode, login_output = run_login_command(login_command, child_env, args.cwd)
    if login_returncode != 0:
        return login_returncode
    if login_output_used_device_code(login_output):
        print(
            "The CLI attempted device code auth for this isolated profile. "
            "This skill requires browser-based interactive login.",
            file=sys.stderr,
        )
        return 1
    verification_result = verify_login_succeeded(args, child_env, executable)
    if verification_result is not None:
        return verification_result
    return None


def ensure_shell_auth(args: argparse.Namespace, child_env: dict[str, str]) -> int | None:
    missing = [executable for executable in ("az", "azd") if should_force_login(args, child_env, executable)]
    if not missing:
        return None

    if not sys.stdin.isatty():
        wrapped_tools = " and ".join(missing)
        print(
            f"Browser-based interactive authentication is required for {wrapped_tools} in isolated profile "
            f"'{args.paths.root.name}'. Open an interactive terminal and run the corresponding login command(s).",
            file=sys.stderr,
        )
        return 1

    for executable in missing:
        if not profile_has_auth_artifacts(args.paths, executable):
            print(
                f"No login state was found for isolated profile '{args.paths.root.name}' ({executable}). "
                "Launching browser-based login before opening the shell.",
                file=sys.stderr,
            )
        else:
            print(
                f"Authentication is required for isolated profile '{args.paths.root.name}' ({executable}). "
                "Launching browser-based login before opening the shell.",
                file=sys.stderr,
            )
        print_login_heads_up(executable, args.tenant)
        login_command = build_login_command(executable, args.tenant)
        login_returncode, login_output = run_login_command(login_command, child_env, args.cwd)
        if login_returncode != 0:
            return login_returncode
        if login_output_used_device_code(login_output):
            print(
                "The CLI attempted device code auth for this isolated profile. "
                "This skill requires browser-based interactive login.",
                file=sys.stderr,
            )
            return 1
        verification_result = verify_login_succeeded(args, child_env, executable)
        if verification_result is not None:
            return verification_result

    return None


def run_shell(args: argparse.Namespace, child_env: dict[str, str]) -> int:
    maybe_disable_wam(child_env, args.cwd, args.disable_wam)
    shell = pick_shell(args.shell_path)
    print_summary(args.paths, args.tenant, args.environment)
    auth_result = ensure_shell_auth(args, child_env)
    if auth_result is not None:
        return auth_result
    print("starting interactive shell with isolated az/azd state...")
    return subprocess.run([shell], env=child_env, cwd=args.cwd, check=False).returncode


def run_exec(args: argparse.Namespace, child_env: dict[str, str]) -> int:
    maybe_disable_wam(child_env, args.cwd, args.disable_wam)
    command = normalize_command(args.command)
    if not command:
        raise ValueError("exec requires a command after '--'.")
    azure_executable = direct_azure_executable(command)
    if azure_executable:
        validation_error = validate_auth_args(azure_executable, command[1:])
        if validation_error:
            print(validation_error, file=sys.stderr)
            return 2
    return subprocess.run(command, env=child_env, cwd=args.cwd, check=False).returncode


def run_wrapped_tool(args: argparse.Namespace, child_env: dict[str, str], executable: str, tail_args: list[str]) -> int:
    validation_error = validate_auth_args(executable, tail_args)
    if validation_error:
        print(validation_error, file=sys.stderr)
        return 2
    maybe_disable_wam(child_env, args.cwd, args.disable_wam)
    auth_result = ensure_interactive_auth(args, child_env, executable, tail_args)
    if auth_result is not None:
        return auth_result
    command = [resolve_executable(executable), *tail_args]
    if is_login_command(executable, tail_args):
        print_login_heads_up(executable, args.tenant)
        returncode, login_output = run_login_command(command, child_env, args.cwd)
        if returncode != 0:
            return returncode
        if login_output_used_device_code(login_output):
            print(
                "The CLI attempted device code auth for this isolated profile. "
                "This skill requires browser-based interactive login.",
                file=sys.stderr,
            )
            return 1
        verification_result = verify_login_succeeded(args, child_env, executable)
        if verification_result is not None:
            return verification_result
        return 0
    return subprocess.run(command, env=child_env, cwd=args.cwd, check=False).returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch az and azd with isolated per-session state.")
    parser.add_argument("--profile", required=True, help="Logical profile name, such as contoso-dev or fabrikam-prod.")
    parser.add_argument("--state-root", type=Path, default=default_state_root(), help="Root folder that stores isolated session state.")
    parser.add_argument("--tenant", help="Required tenant ID to expose as AZURE_TENANT_ID.")
    parser.add_argument("--environment", help="Optional azd environment name to expose as AZURE_ENV_NAME.")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Working directory for shell or command execution.")
    environment_group = parser.add_mutually_exclusive_group()
    environment_group.add_argument(
        "--inherit-azure-env",
        action="store_true",
        help=(
            "Preserve inherited AZURE_* and AZD_* credential/context variables. "
            "AZURE_CONFIG_DIR and AZD_CONFIG_DIR remain isolated."
        ),
    )
    environment_group.add_argument(
        "--clean-azure-env",
        dest="inherit_azure_env",
        action="store_false",
        help="Deprecated compatibility spelling; inherited Azure state is cleaned by default.",
    )
    parser.set_defaults(inherit_azure_env=False)
    wam_group = parser.add_mutually_exclusive_group()
    wam_group.add_argument(
        "--disable-wam",
        dest="disable_wam",
        action="store_true",
        default=os.name == "nt",
        help="On Windows, set core.enable_broker_on_windows=false in the isolated Azure CLI profile. This is the default on Windows.",
    )
    wam_group.add_argument(
        "--enable-wam",
        dest="disable_wam",
        action="store_false",
        help="On Windows, allow Azure CLI to use Web Account Manager instead of plain browser auth.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("show", help="Print the isolated session paths and suggested login commands.")
    shell_parser = subparsers.add_parser("shell", help="Open an interactive shell in the isolated environment.")
    shell_parser.add_argument("--shell-path", help="Optional shell executable to launch.")
    exec_parser = subparsers.add_parser("exec", help="Run one command inside the isolated environment.")
    exec_parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run. Prefix with '--' to stop argument parsing.")
    az_parser = subparsers.add_parser("az", help="Run az inside the isolated environment.")
    az_parser.add_argument("az_args", nargs=argparse.REMAINDER, help="Arguments passed to az.")
    azd_parser = subparsers.add_parser("azd", help="Run azd inside the isolated environment.")
    azd_parser.add_argument("azd_args", nargs=argparse.REMAINDER, help="Arguments passed to azd.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.tenant:
        print(
            "ERROR: --tenant is required. Always specify a tenant ID so az-azd uses the correct "
            "Azure tenant and avoids operating in the wrong one.\n"
            "  Example: --tenant <tenant-id-or-domain>  (e.g. --tenant contoso.onmicrosoft.com)\n"
            "  Get the tenant ID from the user or authoritative project configuration; do not "
            "inspect the shared Azure CLI profile to discover it.\n"
            "Re-run the command with --tenant <your-tenant-id>.",
            file=sys.stderr,
        )
        return 2
    paths = ensure_session_paths(args.state_root, args.profile)
    child_env = build_env(paths, args.tenant, args.environment, args.inherit_azure_env)
    args.paths = paths
    args.cwd = args.cwd.resolve()
    if args.mode == "show":
        print_summary(paths, args.tenant, args.environment)
        return 0
    if args.mode == "shell":
        return run_shell(args, child_env)
    if args.mode == "exec":
        return run_exec(args, child_env)
    if args.mode == "az":
        return run_wrapped_tool(args, child_env, "az", args.az_args)
    if args.mode == "azd":
        return run_wrapped_tool(args, child_env, "azd", args.azd_args)
    raise ValueError(f"Unsupported mode: {args.mode}")


if __name__ == "__main__":
    sys.exit(main())
