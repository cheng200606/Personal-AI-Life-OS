"""Local source selection, privacy preview, and authenticated import commands."""

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
import typer

from personal_ai_life_os.parsers.chatgpt_export import (
    UnsupportedExportError,
    list_chatgpt_conversations,
    select_chatgpt_export,
)
from personal_ai_life_os.parsers.memory_markdown import parse_memory_markdown

app = typer.Typer(
    name="lifeos",
    help="Select, preview, and sync personal source files to Personal AI Life OS.",
    no_args_is_help=True,
)
DEFAULT_API_URL = "http://127.0.0.1:8000"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_BATCH_BYTES = 50 * 1024 * 1024
MAX_DIRECTORY_FILES = 100
IGNORED_DIRECTORY_NAMES = {".git", ".obsidian", ".venv", "node_modules", "__pycache__"}
SUPPORTED_TEXT_SUFFIXES = {".md", ".markdown", ".json"}


@dataclass(frozen=True, slots=True)
class FilePreview:
    path: Path
    kind: str
    size_bytes: int
    sha256: str
    summary: dict


def _api_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise typer.BadParameter("Use an API base URL such as http://127.0.0.1:8000.")
    if parsed.scheme == "http" and parsed.hostname not in local_hosts:
        raise typer.BadParameter("Use HTTPS when the API is not running on this computer.")
    return normalized


def _credentials_path() -> Path:
    override = os.getenv("LIFEOS_CREDENTIALS_FILE")
    return Path(override).expanduser() if override else Path.home() / ".personal-ai-life-os" / "credentials.json"


def _read_credentials() -> dict:
    path = _credentials_path()
    if path.is_symlink():
        raise typer.BadParameter("The local credential path must not be a symbolic link.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise typer.BadParameter("The local credential file cannot be read. Run 'lifeos login' again.") from error
    return value if isinstance(value, dict) else {}


def _write_credentials(credentials: dict) -> None:
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    handle, temporary_name = tempfile.mkstemp(prefix="credentials-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(credentials, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
        if os.name != "nt":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _access_token(api_url: str) -> str:
    token = os.getenv("LIFEOS_ACCESS_TOKEN")
    if token:
        return token
    credential = _read_credentials().get(api_url)
    if isinstance(credential, dict) and isinstance(credential.get("access_token"), str):
        return credential["access_token"]
    raise typer.BadParameter("Not signed in to this API. Run 'lifeos login' first.")


def _request_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"API request failed with HTTP {response.status_code}."
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        code = error.get("code", "request_failed")
        message = error.get("message", "The request was rejected.")
        return f"{code}: {message}"
    return f"API request failed with HTTP {response.status_code}."


def _authed_client(api_url: str) -> httpx.Client:
    return httpx.Client(
        base_url=api_url,
        headers={"Authorization": f"Bearer {_access_token(api_url)}"},
        timeout=httpx.Timeout(60.0, connect=10.0),
    )


def _local_source_key(path: Path) -> str:
    normalized = os.path.normcase(str(path.resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _preview_file(path: Path) -> FilePreview:
    if path.is_symlink() or not path.is_file():
        raise typer.BadParameter(f"{path.name} is not a regular file.")
    stat = path.stat()
    if stat.st_size > MAX_FILE_BYTES:
        raise typer.BadParameter(f"{path.name} is larger than the {MAX_FILE_BYTES}-byte import limit.")
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise typer.BadParameter(f"{path.name} is not UTF-8 Markdown.") from error
        sections = parse_memory_markdown(text, path.name)
        summary = {
            "section_count": len(sections),
            "sections": [
                {
                    "title": item.title,
                    "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
                    "line_start": item.source_locator["line_start"],
                    "line_end": item.source_locator["line_end"],
                }
                for item in sections
            ],
        }
        return FilePreview(path, "memory_markdown", stat.st_size, digest, summary)
    if suffix == ".json":
        try:
            conversations = list_chatgpt_conversations(payload)
        except UnsupportedExportError as error:
            raise typer.BadParameter(f"{path.name}: {error}") from error
        return FilePreview(
            path,
            "chatgpt_export",
            stat.st_size,
            digest,
            {"conversation_count": len(conversations), "conversations": conversations},
        )
    raise typer.BadParameter(f"Unsupported source file type: {path.suffix or '(no extension)'}.")


def _candidate_paths(path: Path) -> list[Path]:
    selected = path.expanduser()
    if selected.is_symlink():
        raise typer.BadParameter("Choose a regular file or directory, not a symbolic link.")
    try:
        selected = selected.resolve(strict=True)
    except OSError as error:
        raise typer.BadParameter("The selected file or directory does not exist.") from error
    if selected.is_file():
        return [selected]
    if not selected.is_dir():
        raise typer.BadParameter("Choose a regular file or directory.")
    candidates: list[Path] = []
    for directory, child_directories, filenames in os.walk(selected, followlinks=False):
        current = Path(directory)
        child_directories[:] = [
            name
            for name in child_directories
            if name not in IGNORED_DIRECTORY_NAMES and not (current / name).is_symlink()
        ]
        for filename in filenames:
            candidate = current / filename
            if candidate.is_symlink() or candidate.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
                continue
            if candidate.name.startswith("."):
                continue
            candidates.append(candidate)
            if len(candidates) > MAX_DIRECTORY_FILES:
                raise typer.BadParameter(
                    f"The selected directory contains more than {MAX_DIRECTORY_FILES} supported files. "
                    "Choose a narrower directory."
                )
    return sorted(candidates)


def _preview_payload(preview: FilePreview) -> dict:
    return {
        "filename": preview.path.name,
        "kind": preview.kind,
        "size_bytes": preview.size_bytes,
        "sha256": preview.sha256,
        **preview.summary,
    }


def _choose_conversations(preview: FilePreview, requested_ids: list[str]) -> list[str]:
    conversations = preview.summary["conversations"]
    available = {str(item["id"]): item for item in conversations}
    if requested_ids:
        missing = set(requested_ids) - available.keys()
        if missing:
            raise typer.BadParameter("One or more selected conversation IDs are not in the local preview.")
        return list(dict.fromkeys(requested_ids))

    for index, conversation in enumerate(conversations, 1):
        created = conversation["created_at"].date().isoformat() if conversation["created_at"] else "date unknown"
        typer.echo(
            f"  {index}. {conversation['title']} | {created} | "
            f"{conversation['message_count']} messages | ID {conversation['id']}"
        )
    raw = typer.prompt("Conversation numbers to upload (comma-separated; blank cancels)", default="")
    indexes = [value.strip() for value in raw.split(",") if value.strip()]
    if not indexes:
        raise typer.Abort()
    try:
        chosen = [str(conversations[int(value) - 1]["id"]) for value in indexes]
    except (ValueError, IndexError) as error:
        raise typer.BadParameter("Use the conversation numbers shown in the preview.") from error
    return list(dict.fromkeys(chosen))


def _get_or_create_source(
    client: httpx.Client,
    preview: FilePreview,
    selected_ids: list[str],
) -> str:
    scope = {
        "local_source_key": _local_source_key(preview.path),
        "filename": preview.path.name,
        "file_sha256": preview.sha256,
    }
    if selected_ids:
        scope["conversation_ids"] = selected_ids

    response = client.get("/api/v1/sources")
    if response.status_code != 200:
        raise typer.BadParameter(_request_error(response))
    existing = next(
        (
            source
            for source in response.json()
            if source["kind"] == preview.kind
            and source["selected_scope"].get("local_source_key") == scope["local_source_key"]
        ),
        None,
    )
    if existing:
        source_id = existing["id"]
        response = client.patch(
            f"/api/v1/sources/{source_id}/scope",
            json={"selected_scope": scope, "consent_version": "source-consent-v1"},
        )
    else:
        response = client.post(
            "/api/v1/sources",
            json={
                "kind": preview.kind,
                "name": preview.path.name,
                "selected_scope": scope,
                "consent_version": "source-consent-v1",
            },
        )
    if response.status_code not in {200, 201}:
        raise typer.BadParameter(_request_error(response))
    return response.json()["id"]


def _markdown_name(title: str, stable_id: str) -> str:
    safe = re.sub(r"[^\w-]+", "-", title, flags=re.UNICODE).strip("-_")[:72] or "lifeos-note"
    return f"{safe}-{stable_id[:8]}.md"


def _atomic_write(path: Path, content: bytes) -> None:
    handle, temporary_name = tempfile.mkstemp(prefix=".lifeos-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_export_file(destination: Path, filename: str, content: bytes, on_conflict: str) -> str:
    root = destination.resolve(strict=True)
    path = root / filename
    if path.is_symlink():
        raise typer.BadParameter(f"Refusing to replace symbolic link {path.name}.")
    if not path.resolve().is_relative_to(root):
        raise typer.BadParameter("The export target escapes the selected directory.")
    if not path.exists():
        _atomic_write(path, content)
        return "created"
    if path.read_bytes() == content:
        return "unchanged"
    if on_conflict == "keep":
        return "kept"
    if on_conflict == "overwrite":
        _atomic_write(path, content)
        return "overwritten"
    stem = path.stem + "-lifeos-copy"
    copy = root / (stem + path.suffix)
    index = 2
    while copy.exists():
        if copy.is_symlink():
            raise typer.BadParameter(f"Refusing to write through symbolic link {copy.name}.")
        if copy.read_bytes() == content:
            return "unchanged"
        copy = root / (stem + "-" + str(index) + path.suffix)
        index += 1
    if not copy.resolve().is_relative_to(root):
        raise typer.BadParameter("The export target escapes the selected directory.")
    _atomic_write(copy, content)
    return "copied"


@app.command()
def register(
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True),
    timezone: str = typer.Option("UTC", help="IANA timezone, for example Asia/Shanghai."),
    invite_code: str | None = typer.Option(None, envvar="LIFEOS_INVITE_CODE"),
    api_url: str = typer.Option(DEFAULT_API_URL, envvar="LIFEOS_API_URL"),
) -> None:
    """Create an account and store a short-lived CLI access token locally."""
    if len(password) < 12:
        raise typer.BadParameter("Use a password with at least 12 characters.")
    base_url = _api_url(api_url)
    response = httpx.post(
        f"{base_url}/api/v1/auth/register",
        json={"email": email, "password": password, "timezone": timezone, "invite_code": invite_code},
        timeout=30,
    )
    if response.status_code != 201:
        raise typer.BadParameter(_request_error(response))
    credentials = _read_credentials()
    credentials[base_url] = {
        "access_token": response.json()["access_token"],
        "saved_at": datetime.now(UTC).isoformat(),
    }
    _write_credentials(credentials)
    typer.echo(f"Signed in to {base_url} as {response.json()['user']['email']}.")


@app.command()
def login(
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True),
    api_url: str = typer.Option(DEFAULT_API_URL, envvar="LIFEOS_API_URL"),
) -> None:
    """Sign in and store a short-lived CLI access token locally."""
    base_url = _api_url(api_url)
    response = httpx.post(
        f"{base_url}/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if response.status_code != 200:
        raise typer.BadParameter(_request_error(response))
    credentials = _read_credentials()
    credentials[base_url] = {
        "access_token": response.json()["access_token"],
        "saved_at": datetime.now(UTC).isoformat(),
    }
    _write_credentials(credentials)
    typer.echo(f"Signed in to {base_url} as {response.json()['user']['email']}.")


@app.command()
def logout(api_url: str = typer.Option(DEFAULT_API_URL, envvar="LIFEOS_API_URL")) -> None:
    """Remove the saved CLI token for an API."""
    base_url = _api_url(api_url)
    credentials = _read_credentials()
    credentials.pop(base_url, None)
    _write_credentials(credentials)
    typer.echo(f"Removed saved credentials for {base_url}.")


@app.command()
def whoami(api_url: str = typer.Option(DEFAULT_API_URL, envvar="LIFEOS_API_URL")) -> None:
    """Show the signed-in account for an API."""
    base_url = _api_url(api_url)
    with _authed_client(base_url) as client:
        response = client.get("/api/v1/auth/me")
    if response.status_code != 200:
        raise typer.BadParameter(_request_error(response))
    user = response.json()
    typer.echo(f"{user['email']} | timezone {user['timezone']} | account {user['id']}")


@app.command()
def preview(path: Path, as_json: bool = typer.Option(False, "--json")) -> None:
    """Inspect a selected source locally without uploading message bodies."""
    candidates = _candidate_paths(path)
    previews: list[FilePreview] = []
    for candidate in candidates:
        try:
            previews.append(_preview_file(candidate))
        except typer.BadParameter as error:
            typer.echo(f"Skipped {candidate.name}: {error.message}", err=True)
    if as_json:
        typer.echo(
            json.dumps(
                [_preview_payload(item) for item in previews],
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return
    for item in previews:
        typer.echo(f"{item.path.name} | {item.kind} | {item.size_bytes} bytes | SHA-256 {item.sha256}")
        if item.kind == "memory_markdown":
            for section in item.summary["sections"]:
                occurred = section["occurred_at"] or "date unknown"
                typer.echo(
                    f"  {occurred} | lines {section['line_start']}-{section['line_end']} | {section['title']}"
                )
        else:
            typer.echo(
                f"  {item.summary['conversation_count']} conversations; "
                "message bodies stay local during preview."
            )


@app.command()
def sync(
    path: Path,
    conversation_id: list[str] = typer.Option(  # noqa: B008 - Typer requires parameter metadata here.
        [], "--conversation-id", help="Selected ID; repeat as needed."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm after showing the local upload preview."),
    api_url: str = typer.Option(DEFAULT_API_URL, envvar="LIFEOS_API_URL"),
) -> None:
    """Preview an explicit file or folder, confirm scope, then upload selected records."""
    base_url = _api_url(api_url)
    candidates = _candidate_paths(path)
    if not candidates:
        raise typer.BadParameter("No supported Markdown or JSON files were found under the selected path.")

    previews: list[FilePreview] = []
    for candidate in candidates:
        try:
            previews.append(_preview_file(candidate))
        except typer.BadParameter as error:
            typer.echo(f"Skipped {candidate.name}: {error.message}", err=True)
    if not previews:
        raise typer.BadParameter("No supported source files could be previewed.")

    chat_files = [item for item in previews if item.kind == "chatgpt_export"]
    if conversation_id and len(chat_files) > 1:
        raise typer.BadParameter(
            "Select a single ChatGPT export when using --conversation-id, or choose IDs interactively."
        )
    selections: dict[str, list[str]] = {}
    for item in previews:
        typer.echo(f"{item.path.name} | {item.kind} | {item.size_bytes} bytes | SHA-256 {item.sha256}")
        if item.kind == "memory_markdown":
            typer.echo(f"  {item.summary['section_count']} sections; contents remain local until confirmation.")
        else:
            typer.echo(f"  {item.summary['conversation_count']} conversations available.")
            selections[str(item.path)] = _choose_conversations(item, conversation_id)

    total_size = sum(item.size_bytes for item in previews)
    if total_size > MAX_BATCH_BYTES:
        raise typer.BadParameter(f"The selected batch exceeds the {MAX_BATCH_BYTES}-byte upload limit.")
    if not yes and not typer.confirm(
        f"Upload {len(previews)} selected file(s), {total_size} bytes total, to {base_url}?",
        default=False,
    ):
        raise typer.Abort()

    with _authed_client(base_url) as client:
        for item in previews:
            current_payload = item.path.read_bytes()
            if hashlib.sha256(current_payload).hexdigest() != item.sha256:
                raise typer.BadParameter(
                    f"{item.path.name} changed after preview. Run sync again to review the new content."
                )
            selected_ids = selections.get(str(item.path), [])
            upload_payload = (
                select_chatgpt_export(current_payload, set(selected_ids))
                if item.kind == "chatgpt_export"
                else current_payload
            )
            source_id = _get_or_create_source(client, item, selected_ids)
            content_type = "application/json" if item.kind == "chatgpt_export" else "text/markdown"
            form_data = {"conversation_ids": json.dumps(selected_ids)} if selected_ids else None
            response = client.post(
                f"/api/v1/sources/{source_id}/imports",
                data=form_data,
                files={"file": (item.path.name, upload_payload, content_type)},
            )
            if response.status_code != 201:
                raise typer.BadParameter(_request_error(response))
            run = response.json()["sync_run"]
            typer.echo(
                f"Imported {item.path.name}: {run['items_created']} new, "
                f"{run['items_duplicate']} unchanged; sync {run['id']}."
            )


@app.command()
def export(
    destination: Annotated[Path, typer.Argument(help="Existing Obsidian vault folder or Markdown output folder.")],
    item_id: Annotated[list[str] | None, typer.Option("--item-id", help="Export only this item ID; repeat to select several.")] = None,
    reviews: Annotated[bool, typer.Option("--reviews", help="Include confirmed weekly reviews.")] = False,
    on_conflict: Annotated[
        Literal["keep", "overwrite", "copy"],
        typer.Option(help="Keep hand-edited files, explicitly overwrite, or write a separate copy."),
    ] = "keep",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the write confirmation; edited files are still kept by default.")] = False,
    api_url: Annotated[str, typer.Option(envvar="LIFEOS_API_URL")] = DEFAULT_API_URL,
) -> None:
    """Preview and safely export selected timeline items as portable Markdown."""
    item_id = item_id or []
    if not destination.exists() or not destination.is_dir():
        raise typer.BadParameter("Choose an existing destination directory.")
    root = destination.resolve(strict=True)
    base_url = _api_url(api_url)
    planned: list[tuple[str, bytes]] = []
    with _authed_client(base_url) as client:
        selected_items: list[dict] = []
        cursor: str | None = None
        while True:
            params: dict[str, str | int] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            response = client.get("/api/v1/timeline", params=params)
            if response.status_code != 200:
                raise typer.BadParameter(_request_error(response))
            page = response.json()
            selected_items.extend(page["items"])
            cursor = page.get("next_cursor")
            if not cursor:
                break
        if item_id:
            wanted = set(item_id)
            selected_items = [item for item in selected_items if item["id"] in wanted]
            found = {item["id"] for item in selected_items}
            if wanted - found:
                raise typer.BadParameter("One or more selected item IDs are unavailable to this account.")

        for item in selected_items:
            source_response = client.get("/api/v1/sources/" + item["source_id"])
            source_name = source_response.json().get("name", "Life OS") if source_response.status_code == 200 else "Life OS"
            organization_response = client.get("/api/v1/items/" + item["id"] + "/organization")
            organization = organization_response.json() if organization_response.status_code == 200 else {"tags": [], "collections": []}
            frontmatter = [
                "---",
                "id: " + item["id"],
                "source: " + json.dumps(source_name, ensure_ascii=False),
                "occurred_at: " + (item["occurred_at"] or "unknown"),
                "source_locator: " + json.dumps(item["source_locator"], ensure_ascii=False),
                "tags: " + json.dumps([tag["name"] for tag in organization.get("tags", [])], ensure_ascii=False),
                "collections: " + json.dumps([collection["name"] for collection in organization.get("collections", [])], ensure_ascii=False),
                "---",
                "",
                "# " + item["title"],
                "",
                item["content_text"],
                "",
            ]
            planned.append(
                (_markdown_name(item["title"], item["id"]), "\n".join(frontmatter).encode("utf-8"))
            )

        if reviews:
            review_response = client.get("/api/v1/reviews")
            if review_response.status_code != 200:
                raise typer.BadParameter(_request_error(review_response))
            for review in review_response.json():
                if review["status"] != "confirmed":
                    continue
                export_response = client.get("/api/v1/reviews/" + review["id"] + "/export.md")
                if export_response.status_code != 200:
                    raise typer.BadParameter(_request_error(export_response))
                filename = "weekly-review-" + review["period_start"][:10] + "-" + review["id"][:8] + ".md"
                planned.append((filename, export_response.content))

    if not planned:
        typer.echo("No selected timeline items or confirmed reviews are available to export.")
        return
    changes = 0
    for filename, content in planned:
        target = root / filename
        if target.is_symlink():
            raise typer.BadParameter(f"Refusing to write through symbolic link {filename}.")
        if not target.exists() or target.read_bytes() != content or on_conflict == "copy":
            changes += 1
        outcome = "unchanged" if target.exists() and target.read_bytes() == content else "write"
        if target.exists() and target.read_bytes() != content:
            outcome = "conflict → " + on_conflict
        typer.echo(f"{outcome:18} {filename}")
    typer.echo(f"{len(selected_items)} timeline item(s), {len(planned) - len(selected_items)} confirmed review(s).")
    if changes and not yes and not typer.confirm(f"Write {changes} file(s) under {root}?", default=False):
        raise typer.Abort()

    for filename, content in planned:
        outcome = _write_export_file(root, filename, content, on_conflict)
        if outcome == "kept":
            typer.echo(f"kept edited file: {filename}")
        elif outcome != "unchanged":
            typer.echo(f"{outcome}: {filename}")


if __name__ == "__main__":
    app()
