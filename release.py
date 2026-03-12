#!/usr/bin/env python3
"""
Local release workflow for Terminal Access for NVDA.

Validates everything BEFORE pushing a release commit to main.
CI (release.yml) handles native builds, tagging, and GitHub Releases.

Usage:
    py -3 release.py <new_version>
    py -3 release.py <new_version> --dry-run
    py -3 release.py <new_version> --allow-test-failures

Examples:
    py -3 release.py 1.3.0
    py -3 release.py 1.3.0 --dry-run
    py -3 release.py 1.3.0 --allow-test-failures
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
BUILDVARS_PATH = PROJECT_ROOT / "buildVars.py"
CHANGELOG_PATH = PROJECT_ROOT / "CHANGELOG.md"
MANIFEST_PATH = PROJECT_ROOT / "addon" / "manifest.ini"
NATIVE_DIR = PROJECT_ROOT / "native"
BUILD_SCRIPT = PROJECT_ROOT / "build.py"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
NVDA_VERSION_RE = re.compile(r"^\d{4}\.\d+(\.\d+)?$")
ADDON_VERSION_RE = re.compile(r'(addon_version\s*=\s*")[^"]+(")')
CHANGELOG_VERSION_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)

REQUIRED_MANIFEST_KEYS = [
	"name", "summary", "description", "author", "url",
	"version", "docFileName", "minimumNVDAVersion", "lastTestedNVDAVersion",
]

REPO_URL = "https://github.com/PratikP1/Terminal-Access-for-NVDA"

# Track whether we have mutated files (for error recovery messages)
_files_mutated = False


# ── Output helpers ─────────────────────────────────────────────────────

def ok(msg: str) -> None:
	print(f"  [OK] {msg}")


def fail(msg: str) -> None:
	print(f"  [FAIL] {msg}")


def info(msg: str) -> None:
	print(f"  -> {msg}")


def abort(msg: str) -> None:
	"""Print error and exit. Show recovery hints if files were mutated."""
	print(f"\n  [FAIL] {msg}")
	if _files_mutated:
		print()
		print("  Files were modified before this failure.")
		print("  To revert: git checkout -- buildVars.py CHANGELOG.md")
		print("  To retry:  py -3 release.py <version>")
	sys.exit(1)


def banner(current: str, new: str) -> None:
	print("=" * 64)
	print(f"  Terminal Access for NVDA -- Release Workflow")
	print(f"  {current} -> {new}")
	print("=" * 64)


def banner_done(version: str) -> None:
	print()
	print("=" * 64)
	print(f"  Release {version} complete!")
	print("=" * 64)


# ── Subprocess helper ──────────────────────────────────────────────────

def run(
	cmd: list[str],
	cwd: Path | str | None = None,
	check: bool = True,
	description: str = "",
) -> subprocess.CompletedProcess:
	"""Execute a command. On failure with check=True, abort."""
	label = " ".join(str(c) for c in cmd)
	print(f"    $ {label}")
	try:
		result = subprocess.run(
			cmd,
			cwd=str(cwd) if cwd else None,
			capture_output=True,
			text=True,
			encoding="utf-8",
		)
	except FileNotFoundError:
		abort(f"Command not found: {cmd[0]}. Is it installed and on PATH?")
	if check and result.returncode != 0:
		desc = description or cmd[0]
		# Truncate long output
		stdout = result.stdout[-3000:] if result.stdout else ""
		stderr = result.stderr[-3000:] if result.stderr else ""
		abort(f"{desc} failed (exit {result.returncode})\n{stdout}\n{stderr}")
	return result


# ── Version helpers ────────────────────────────────────────────────────

def parse_version(v: str) -> tuple[int, int, int]:
	parts = v.split(".")
	return (int(parts[0]), int(parts[1]), int(parts[2]))


def read_current_version() -> str:
	"""Read addon_version from buildVars.py."""
	content = BUILDVARS_PATH.read_text(encoding="utf-8")
	m = re.search(r'addon_version\s*=\s*["\']([^"\']+)["\']', content)
	if not m:
		abort("Could not find addon_version in buildVars.py")
	return m.group(1)


# ── Manifest parser ───────────────────────────────────────────────────

def parse_manifest(path: Path) -> dict[str, str]:
	"""Parse NVDA flat key=value manifest, handling triple-quoted values."""
	result = {}
	text = path.read_text(encoding="utf-8")
	in_triple = False
	current_key = None
	current_value_lines: list[str] = []

	for line in text.splitlines():
		if in_triple:
			if '"""' in line:
				in_triple = False
				current_value_lines.append(line.split('"""')[0])
				result[current_key] = "\n".join(current_value_lines)
			else:
				current_value_lines.append(line)
			continue

		if "=" in line and not line.strip().startswith("#"):
			key, _, value = line.partition("=")
			key = key.strip()
			value = value.strip()

			if value.startswith('"""'):
				rest = value[3:]
				if rest.rstrip().endswith('"""'):
					# Single-line triple-quoted
					result[key] = rest.rstrip()[:-3]
				else:
					in_triple = True
					current_key = key
					current_value_lines = [rest]
			else:
				result[key] = value.strip('"')

	return result


# ── Gate 1: Pre-flight checks ─────────────────────────────────────────

def gate_preflight(new_version: str) -> str:
	"""Validate preconditions. Returns current version."""
	print()
	print("[Gate 1/6] Pre-flight checks")

	# 1a. Build dependencies
	missing_deps = []
	for mod in ("SCons", "markdown"):
		try:
			__import__(mod)
		except ImportError:
			missing_deps.append(mod.lower())
	if missing_deps:
		fail(f"Missing Python packages: {', '.join(missing_deps)}")
		abort(f"Install with: py -3 -m pip install {' '.join(missing_deps)}")
	ok("Build dependencies available (scons, markdown)")

	# 1b. Version format
	if not VERSION_RE.match(new_version):
		fail(f"Invalid version format: {new_version}")
		abort("Version must be MAJOR.MINOR.PATCH (e.g., 1.3.0)")
	ok(f"Version format valid: {new_version}")

	# 1c. Read current version and compare
	current = read_current_version()
	if parse_version(new_version) <= parse_version(current):
		fail(f"New version {new_version} is not greater than current {current}")
		abort(f"New version must be strictly greater than {current}")
	ok(f"Version bump: {current} -> {new_version}")

	# 1d. Tag does not exist
	tag_check = run(
		["git", "tag", "--list", f"v{new_version}"],
		check=False,
		description="git tag check",
	)
	if tag_check.stdout.strip():
		fail(f"Tag v{new_version} already exists")
		abort(f"Tag v{new_version} already exists. This version may have been released.")
	ok(f"Tag v{new_version} does not exist")

	# 1e. Working tree clean
	status = run(
		["git", "status", "--porcelain"],
		check=False,
		description="git status",
	)
	if status.stdout.strip():
		fail("Working tree has uncommitted changes")
		print(f"    {status.stdout.strip()}")
		abort("Commit or stash changes before releasing.")
	ok("Working tree clean")

	# 1f. On main branch
	branch = run(
		["git", "branch", "--show-current"],
		check=False,
		description="git branch",
	)
	current_branch = branch.stdout.strip()
	if current_branch != "main":
		fail(f"On branch '{current_branch}', not 'main'")
		abort("Switch to main branch before releasing.")
	ok(f"On branch: {current_branch}")

	return current


# ── Gate 2: Changelog validation ──────────────────────────────────────

def gate_changelog(new_version: str) -> None:
	"""Validate [Unreleased] section has content and new version is not already present."""
	print()
	print("[Gate 2/6] Changelog validation")

	content = CHANGELOG_PATH.read_text(encoding="utf-8")
	lines = content.splitlines()

	# 2a. Find [Unreleased] section
	unreleased_idx = None
	next_version_idx = None
	for i, line in enumerate(lines):
		if re.match(r"^## \[Unreleased\]\s*$", line, re.IGNORECASE):
			unreleased_idx = i
		elif unreleased_idx is not None and re.match(r"^## \[", line):
			next_version_idx = i
			break

	if unreleased_idx is None:
		fail("[Unreleased] section not found in CHANGELOG.md")
		abort("CHANGELOG.md must have a ## [Unreleased] section.")

	# 2b. Check for bullet points between [Unreleased] and next version header
	section_end = next_version_idx if next_version_idx else len(lines)
	section_lines = lines[unreleased_idx + 1 : section_end]
	bullet_count = sum(1 for l in section_lines if l.strip().startswith("- "))

	if bullet_count == 0:
		fail("[Unreleased] section has no entries")
		abort(
			"No changelog entries found under [Unreleased].\n"
			"  Please document changes before releasing."
		)
	ok(f"[Unreleased] section has {bullet_count} entries")

	# 2c. No existing entry for the new version
	if re.search(rf"^## \[{re.escape(new_version)}\]", content, re.MULTILINE):
		fail(f"CHANGELOG.md already has an entry for {new_version}")
		abort(f"Version {new_version} already exists in CHANGELOG.md.")
	ok(f"No existing entry for v{new_version}")


# ── Gate 3: Run tests ─────────────────────────────────────────────────

def gate_tests(allow_failures: bool) -> None:
	"""Run Rust and Python test suites."""
	print()
	print("[Gate 3/6] Running tests")

	# 3a. Rust tests
	print("  Rust tests:")
	rust = run(
		["cargo", "test", "--all"],
		cwd=NATIVE_DIR,
		check=False,
		description="Rust tests",
	)
	if rust.returncode == 0:
		# Extract test count from cargo output
		test_line = ""
		for line in rust.stdout.splitlines():
			if "test result:" in line and "passed" in line:
				test_line = line.strip()
		ok(f"Rust tests passed{': ' + test_line if test_line else ''}")
	else:
		fail("Rust tests failed")
		# Rust failures always block — no override
		stderr_tail = rust.stderr[-2000:] if rust.stderr else ""
		stdout_tail = rust.stdout[-2000:] if rust.stdout else ""
		abort(f"Rust tests must pass before releasing.\n{stdout_tail}\n{stderr_tail}")

	# 3b. Python tests
	print("  Python tests:")
	py = run(
		["py", "-3", "-m", "pytest", "tests/", "-o", "addopts=", "-v", "--tb=short"],
		cwd=PROJECT_ROOT,
		check=False,
		description="Python tests",
	)
	if py.returncode == 0:
		ok("Python tests passed")
	else:
		# Extract summary line
		summary = ""
		for line in py.stdout.splitlines():
			if "passed" in line or "failed" in line or "error" in line:
				summary = line.strip()
		if allow_failures:
			print(f"  ! Python tests had failures (--allow-test-failures): {summary}")
			print("    Proceeding despite failures.")
		else:
			fail(f"Python tests failed: {summary}")
			abort(
				"Python tests must pass before releasing.\n"
				"  Use --allow-test-failures to override for pre-existing failures."
			)


# ── Gate 4: Version bump + changelog promotion ────────────────────────

def gate_bump(new_version: str, dry_run: bool) -> None:
	"""Mutate buildVars.py and CHANGELOG.md."""
	global _files_mutated
	print()
	print("[Gate 4/6] Version bump + changelog promotion")

	today = date.today().isoformat()

	# 4a. Promote [Unreleased] in CHANGELOG.md
	changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
	new_header = f"## [Unreleased]\n\n## [{new_version}] - {today}"
	updated_changelog = changelog.replace("## [Unreleased]", new_header, 1)

	if updated_changelog == changelog:
		abort("Failed to promote [Unreleased] section in CHANGELOG.md")

	if dry_run:
		info(f"[DRY RUN] Would update CHANGELOG.md: [Unreleased] -> [{new_version}] - {today}")
	else:
		CHANGELOG_PATH.write_text(updated_changelog, encoding="utf-8")
		_files_mutated = True
		ok(f"CHANGELOG.md: [Unreleased] -> [{new_version}] - {today}")

	# 4b. Bump addon_version in buildVars.py
	buildvars = BUILDVARS_PATH.read_text(encoding="utf-8")
	updated_buildvars = ADDON_VERSION_RE.sub(rf"\g<1>{new_version}\g<2>", buildvars)

	if updated_buildvars == buildvars:
		abort("Failed to update addon_version in buildVars.py — regex did not match")

	if dry_run:
		info(f'[DRY RUN] Would update buildVars.py: addon_version = "{new_version}"')
	else:
		BUILDVARS_PATH.write_text(updated_buildvars, encoding="utf-8")
		_files_mutated = True
		ok(f'buildVars.py: addon_version = "{new_version}"')


# ── Gate 5: Build & validate ──────────────────────────────────────────

def gate_build(new_version: str, current_version: str, dry_run: bool) -> None:
	"""Build the addon and validate the manifest."""
	print()
	print("[Gate 5/6] Build and validate")

	# In dry-run, Gate 4 didn't modify files, so build.py uses the current
	# version.  We validate the build pipeline works and the manifest
	# structure is correct; version match is verified against whatever
	# version buildVars.py actually contains.
	expect_version = current_version if dry_run else new_version

	# 5a. Run build.py
	if dry_run:
		info("[DRY RUN] Building with current version to validate pipeline")
	run(
		["py", "-3", str(BUILD_SCRIPT), "--non-interactive"],
		cwd=PROJECT_ROOT,
		description="build.py",
	)

	# 5b. Verify .nvda-addon exists and is non-empty
	addon_file = PROJECT_ROOT / f"terminalAccess-{expect_version}.nvda-addon"
	if not addon_file.exists():
		fail(f"{addon_file.name} not found")
		abort(f"Build did not produce {addon_file.name}")

	size_kb = addon_file.stat().st_size / 1024
	if addon_file.stat().st_size == 0:
		fail(f"{addon_file.name} is empty")
		abort(f"Build produced an empty {addon_file.name}")
	ok(f"{addon_file.name} ({size_kb:.1f} KB)")

	# 5c. Validate manifest.ini
	if not MANIFEST_PATH.exists():
		fail("addon/manifest.ini not found after build")
		abort("build.py did not generate addon/manifest.ini")

	manifest = parse_manifest(MANIFEST_PATH)

	missing = [k for k in REQUIRED_MANIFEST_KEYS if k not in manifest]
	if missing:
		fail(f"manifest.ini missing keys: {', '.join(missing)}")
		abort(f"Manifest is incomplete. Missing: {', '.join(missing)}")
	ok(f"manifest.ini: {len(REQUIRED_MANIFEST_KEYS)}/{len(REQUIRED_MANIFEST_KEYS)} required keys present")

	# 5d. Version match
	manifest_version = manifest.get("version", "").strip()
	if manifest_version != expect_version:
		fail(f"manifest version '{manifest_version}' != '{expect_version}'")
		abort("Manifest version does not match the expected version.")
	ok(f"manifest version matches: {expect_version}")
	if dry_run:
		info(f"During actual release, manifest will show {new_version}")

	# 5e. NVDA version format
	for key in ("minimumNVDAVersion", "lastTestedNVDAVersion"):
		val = manifest.get(key, "").strip()
		if not NVDA_VERSION_RE.match(val):
			fail(f"manifest {key} = '{val}' is not a valid NVDA version")
			abort(f"{key} must be in YYYY.N.N format (e.g., 2025.1.0)")
	ok(f"NVDA version constraints valid")


# ── Gate 6: Commit & push ─────────────────────────────────────────────

def gate_release(new_version: str, dry_run: bool) -> None:
	"""Stage, commit, and push the release."""
	print()
	print("[Gate 6/6] Commit and push")

	if dry_run:
		info("[DRY RUN] Would execute:")
		print("    $ git add buildVars.py CHANGELOG.md")
		print(f'    $ git commit -m "Release v{new_version}"')
		print("    $ git push origin main")
		info(f"CI will create tag v{new_version} and GitHub Release.")
		return

	run(
		["git", "add", "buildVars.py", "CHANGELOG.md"],
		description="git add",
	)
	run(
		["git", "commit", "-m", f"Release v{new_version}"],
		description="git commit",
	)

	# Push — if this fails, the commit exists locally
	push_result = run(
		["git", "push", "origin", "main"],
		check=False,
		description="git push",
	)
	if push_result.returncode != 0:
		fail("git push failed")
		print(f"    {push_result.stderr.strip()}")
		print()
		print("  The commit exists locally. After fixing the issue, run:")
		print("    git push origin main")
		sys.exit(1)

	ok(f"Committed: Release v{new_version}")
	ok("Pushed to origin/main")
	info(f"CI will create tag v{new_version} and GitHub Release.")
	info(f"Monitor: {REPO_URL}/actions")


# ── Main ───────────────────────────────────────────────────────────────

def main() -> int:
	parser = argparse.ArgumentParser(
		description="Local release workflow for Terminal Access for NVDA.",
		epilog="CI handles native builds, tagging, and GitHub Releases after push.",
	)
	parser.add_argument(
		"version",
		help="New version in MAJOR.MINOR.PATCH format (e.g., 1.3.0)",
	)
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="Run all validation gates but don't commit or push.",
	)
	parser.add_argument(
		"--allow-test-failures",
		action="store_true",
		help="Proceed despite Python test failures (for pre-existing issues).",
	)
	args = parser.parse_args()

	os.chdir(PROJECT_ROOT)

	# Read current version first for the banner
	current = read_current_version()
	banner(current, args.version)

	if args.dry_run:
		print("  (DRY RUN -- no files will be committed or pushed)")

	# Gate 1: Pre-flight
	gate_preflight(args.version)

	# Gate 2: Changelog
	gate_changelog(args.version)

	# Gate 3: Tests
	gate_tests(args.allow_test_failures)

	# Gate 4: Bump
	gate_bump(args.version, args.dry_run)

	# Gate 5: Build & validate
	gate_build(args.version, current, args.dry_run)

	# Gate 6: Commit & push
	gate_release(args.version, args.dry_run)

	banner_done(args.version)
	return 0


if __name__ == "__main__":
	sys.exit(main())
