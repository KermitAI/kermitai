"""Read-only repository inventory, separate from command permission auditing."""
from collections import defaultdict


def belongs(module, package):
    return module == package or module.startswith(package + ".")


def repo_name(item):
    # Older Red preserves the original name privately when a repo is missing.
    return (getattr(item, "_json_repo_name", None)
            or getattr(item, "repo_name", None) or "(unknown repo)")


def build_repo_report(repos, installed, libraries, extensions, cogs, commands, app_commands=()):
    repos = list(repos)
    installed = list(installed)
    libraries = list(libraries)
    commands = list(commands)
    app_commands = list(app_commands)
    by_repo = defaultdict(list)
    libs_by_repo = defaultdict(list)
    for item in installed:
        by_repo[repo_name(item)].append(item)
    for item in libraries:
        libs_by_repo[repo_name(item)].append(item.name)
    repo_map = {repo.name: repo for repo in repos}
    known_names = set(repo_map) | set(by_repo) | set(libs_by_repo)
    counts = {"repos": len(repos), "installed": len(installed), "unloaded": 0, "candidates": 0}
    lines = [
        "REPOSITORY AND COG AUDIT", "",
        "Read-only snapshot: no commands/checks executed, no cogs loaded or unloaded, no repos updated or removed.",
        "Unloaded does not mean broken. Historical load errors and command execution failures are not available here.",
        "Zero commands can be normal for listeners, tasks, menus, or shared-library cogs.",
        "Candidate means no Downloader-tracked cogs or shared libraries; verify manual installs/dependencies before removal.",
        "Source availability is from the local repo checkout, not a fresh upstream check.", "",
    ]
    matched_extensions = set()
    for name in sorted(known_names, key=str.casefold):
        repo = repo_map.get(name)
        items = by_repo[name]
        libs = libs_by_repo[name]
        candidate = repo is not None and not items and not libs
        if candidate:
            counts["candidates"] += 1
        lines.append(f"REPO: {name}")
        if repo is None:
            lines.append("  REVIEW: installed modules reference a repo that is no longer added.")
        elif candidate:
            lines.append("  CLEANUP CANDIDATE: no tracked cogs or shared libraries installed.")
        elif not items and libs:
            lines.append("  KEEP/REVIEW: shared libraries installed, even though no cogs are tracked.")
        if libs:
            lines.append("  Shared libraries: " + ", ".join(sorted(libs)))
        available = {item.name for item in getattr(repo, "available_cogs", ())} if repo else set()
        for item in sorted(items, key=lambda item: item.name.casefold()):
            # Red normally loads downloaded packages by their installed package name.
            # Never infer ownership by substring or the user-facing Cog class name.
            matches = [key for key in extensions if key == item.name]
            matched_extensions.update(matches)
            loaded_modules = {item.name}
            loaded_modules.update(getattr(extensions[key], "__name__", key) for key in matches)
            associated = [cog for cog in cogs.values() if any(
                belongs(type(cog).__module__, module) for module in loaded_modules)]
            text = [cmd for cmd in commands if getattr(cmd, "cog", None) in associated
                    or any(belongs(getattr(cmd, "module", None) or "", module) for module in loaded_modules)]
            apps = [cmd for cmd in app_commands if any(
                belongs(getattr(cmd, "module", None) or "", module) for module in loaded_modules)
                or getattr(cmd, "binding", None) in associated]
            active = bool(matches or associated or text or apps)
            if not active:
                counts["unloaded"] += 1
            lines.append(f"  COG: {item.name} - {'LOADED' if active else 'UNLOADED (reason unknown)'}")
            if repo is not None and item.name not in available:
                lines.append("    REVIEW: not in local repo's available cogs (removed, hidden, or disabled in metadata).")
            if getattr(item, "pinned", False):
                lines.append("    Pinned: updates intentionally held.")
            lines.append(f"    Registered text commands: {len(text)}; application entries: {len(apps)}")
            if active and not text and not apps:
                lines.append("    REVIEW: loaded with no registered commands; may provide background features.")
            for cmd in sorted(text, key=lambda cmd: cmd.qualified_name.casefold()):
                flags = []
                chain = [cmd, *getattr(cmd, "parents", ())]
                if any(getattr(node, "hidden", False) for node in chain):
                    flags.append("hidden (self or parent)")
                if any(not getattr(node, "enabled", True) for node in chain):
                    flags.append("disabled (self or parent)")
                lines.append(f"      {cmd.qualified_name}" + (f" [{'; '.join(flags)}]" if flags else ""))
            for cmd in sorted(apps, key=lambda cmd: cmd.qualified_name.casefold()):
                lines.append(f"      /{cmd.qualified_name} [application entry]")
        if not items:
            lines.append("  Installed cogs: none")
        lines.append("")
    lines.extend(["LOADED EXTENSIONS NOT MATCHED TO DOWNLOADER INSTALLS", 
                  "Includes core/manual extensions; these are not removal recommendations."])
    lines.extend(f"- {key}" for key in sorted(set(extensions) - matched_extensions))
    lines.extend(["", "NEXT STEPS",
                  "- Review empty repos first, then intentionally unused unloaded cogs.",
                  "- To investigate an unloaded cog, deliberately load it and inspect the resulting error/logs.",
                  "- For registered commands missing from help, check hidden flags, permissions and help settings.",
                  "- Keep repos that provide cogs or libraries you still use; this snapshot cannot prove a command works."])
    return "\n".join(lines), counts


async def downloader_inventory(bot):
    """Support Red both before and after the 3.5.25 Downloader extraction."""
    downloader = bot.get_cog("Downloader")
    if downloader is None:
        raise RuntimeError("Load Downloader first, then run checkrepos again.")
    ready = getattr(downloader, "_ready", None)
    if ready is not None and not ready.is_set():
        raise RuntimeError("Downloader is still initializing. Try again once it is ready.")
    if getattr(downloader, "_ready_raised", False):
        raise RuntimeError("Downloader initialization failed. Check your bot logs first.")
    try:
        from redbot.core import _downloader as source
    except ImportError:
        source = downloader
    manager = getattr(source, "_repo_manager", None)
    if manager is None:
        raise RuntimeError("This Red version does not expose the repository inventory.")
    installed = await source.installed_cogs()
    libraries = await source.installed_libraries()
    return manager.repos, installed, libraries
