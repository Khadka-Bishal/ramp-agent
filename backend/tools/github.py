import asyncio
import logging
import re

from github import Github

from backend.sandbox.provider import Sandbox, SandboxProvider

logger = logging.getLogger(__name__)


async def create_branch(sandbox_provider: SandboxProvider, sandbox: Sandbox, branch_name: str) -> dict:
    result = await sandbox_provider.run_command(
        sandbox, f"git checkout -b {branch_name}"
    )
    if result.exit_code != 0:
        raise RuntimeError(f"git checkout -b failed: {result.stderr}")
    return {"branch_name": branch_name, "status": "created"}


async def commit_and_push(sandbox_provider: SandboxProvider, sandbox: Sandbox, message: str) -> dict:
    # Escape quotes in message
    safe_message = message.replace('"', '\\"')
    
    # Configure git identity first, as Modal containers might not have it
    await sandbox_provider.run_command(sandbox, 'git config user.email "agent@ramp.com"')
    await sandbox_provider.run_command(sandbox, 'git config user.name "Ramp Agent"')

    for cmd in [
        "git add -A",
        f'git commit -m "{safe_message}"',
    ]:
        result = await sandbox_provider.run_command(sandbox, cmd)
        if result.exit_code != 0 and "add" not in cmd:
            raise RuntimeError(f"{cmd} failed: {result.stderr}")

    # Get current branch name
    result = await sandbox_provider.run_command(sandbox, "git rev-parse --abbrev-ref HEAD")
    branch = result.stdout.strip()

    # Push
    result = await sandbox_provider.run_command(sandbox, f"git push -u origin {branch}")
    if result.exit_code != 0:
        raise RuntimeError(f"git push failed: {result.stderr}")

    # Get commit SHA
    result = await sandbox_provider.run_command(sandbox, "git rev-parse HEAD")
    sha = result.stdout.strip()

    return {"commit_sha": sha, "branch": branch, "status": "pushed"}


async def create_pr(
    sandbox_provider: SandboxProvider,
    sandbox: Sandbox,
    repo_full_name: str,
    title: str,
    body: str,
    github_token: str,
) -> dict:
    # Get current branch
    result = await sandbox_provider.run_command(sandbox, "git rev-parse --abbrev-ref HEAD")
    if result.exit_code != 0:
        raise RuntimeError(f"Could not determine current branch: {result.stderr}")
    branch = result.stdout.strip()

    # Ensure branch is pushed by checking remote
    remote_check = await sandbox_provider.run_command(sandbox, f"git ls-remote --heads origin {branch}")
    if not remote_check.stdout.strip():
        # Branch not on remote, try to push it first if it has commits
        logger.info(f"Branch {branch} not found on remote, attempting to push...")
        push_result = await sandbox_provider.run_command(sandbox, f"git push -u origin {branch}")
        if push_result.exit_code != 0:
             raise RuntimeError(f"Branch {branch} is not on remote and push failed: {push_result.stderr}")

    try:
        g = Github(github_token)
        repo = g.get_repo(repo_full_name)
        pr = repo.create_pull(
            title=title,
            body=body,
            head=branch,
            base=repo.default_branch,
        )
        return {"pr_url": pr.html_url, "pr_number": pr.number, "status": "created"}
    except Exception as e:
        logger.exception("GitHub PR creation failed")
        raise RuntimeError(f"Failed to create Pull Request: {str(e)}")


async def post_review_comment(
    repo_full_name: str, pr_number: int, body: str, github_token: str
) -> None:
    g = Github(github_token)
    repo = g.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)
    pr.create_issue_comment(body)


async def merge_pr(
    repo_full_name: str, pr_number: int, github_token: str
) -> dict:
    g = Github(github_token)
    repo = g.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)
    result = pr.merge()
    return {
        "merged": result.merged,
        "sha": result.sha,
        "message": result.message,
    }


def extract_repo_full_name(repo_url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL."""
    match = re.search(r"github\.com[/:](.+?)(?:\.git)?$", repo_url)
    if not match:
        raise ValueError(f"Cannot parse repo name from URL: {repo_url}")
    return match.group(1).strip("/")
